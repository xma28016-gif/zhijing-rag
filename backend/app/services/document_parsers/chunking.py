"""Selectable, source-preserving strategies shared by preview and indexing."""

from __future__ import annotations

import hashlib
import math
import re
from itertools import groupby

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.models.enums import ChunkKind
from app.schemas.knowledge import ChunkMode, ChunkPreview, ChunkSettings, ParseResult, StructuredBlock
from app.services.document_parsers.base import DocumentParseError

_CJK = re.compile(r"[\u3400-\u9fff]")
_WORD = re.compile(r"[A-Za-z0-9_]+|[^\s]")
_QUESTION = re.compile(r"(?im)^\s*(?:Q(?:uestion)?\s*\d*|问(?:题)?\s*\d*)\s*[:：]")
_ANSWER = re.compile(r"(?im)^\s*(?:A(?:nswer)?\s*\d*|答(?:案)?\s*\d*)\s*[:：]")


def estimate_tokens(text: str) -> int:
    """Deterministic estimate; provider usage is accounted for separately."""
    return max(1, len(_CJK.findall(text)) + len(_WORD.findall(_CJK.sub(" ", text))))


def _split(text: str, target: int, overlap: int = 0, *, fixed: bool = False) -> list[str]:
    return RecursiveCharacterTextSplitter(
        chunk_size=target,
        chunk_overlap=overlap,
        length_function=lambda value: estimate_tokens(value) if value.strip() else 0,
        separators=[""] if fixed else ["\n\n", "\n", "。", "；", ". ", " ", ""],
    ).split_text(text)


def _merge(blocks: list[StructuredBlock]) -> StructuredBlock:
    first = blocks[0]
    pages = [p for b in blocks for p in (b.page_from, b.page_to) if p is not None]
    path = first.title_path.copy()
    for block in blocks[1:]:
        length = min(len(path), len(block.title_path))
        for index in range(length):
            if path[index] != block.title_path[index]:
                length = index
                break
        path = path[:length]
    return first.model_copy(
        update={
            "content": "\n\n".join(b.content for b in blocks),
            "title_path": path,
            "page_from": min(pages) if pages else None,
            "page_to": max(pages) if pages else None,
            "metadata": {
                **first.metadata,
                "source_blocks": [
                    {
                        "ordinal": b.ordinal,
                        "title_path": b.title_path,
                        "page_from": b.page_from,
                        "page_to": b.page_to,
                    }
                    for b in blocks
                ],
            },
        }
    )


def _text_groups(result: ParseResult, *, by_title: bool = False) -> list[StructuredBlock]:
    groups: list[StructuredBlock] = []
    pending: list[StructuredBlock] = []
    for block in result.blocks:
        if block.kind is not ChunkKind.TEXT:
            if pending:
                groups.append(_merge(pending))
                pending = []
            groups.append(block)
        else:
            if pending and by_title and pending[-1].title_path != block.title_path:
                groups.append(_merge(pending))
                pending = []
            pending.append(block)
    if pending:
        groups.append(_merge(pending))
    return groups


def _table_parts(block: StructuredBlock, settings: ChunkSettings) -> list[tuple[str, str | None]]:
    lines = [line for line in block.content.splitlines() if line.strip()]
    if len(lines) <= 2:
        return [(block.content, block.cell_range)]
    header, rows = lines[:2], lines[2:]
    parts: list[tuple[str, str | None]] = []
    start = 0
    current: list[str] = []
    cells = re.fullmatch(r"([A-Z]+)(\d+):([A-Z]+)\d+", block.cell_range or "")
    row_numbers = block.metadata.get("row_numbers", [])

    def append() -> None:
        location = block.cell_range
        if cells:
            row_from = int(cells[2]) + 1 + start
            row_to = row_from + len(current) - 1
            if len(row_numbers) > start + len(current):
                row_from, row_to = row_numbers[start + 1], row_numbers[start + len(current)]
            location = f"{cells[1]}{row_from}:{cells[3]}{row_to}"
        parts.append(("\n".join([*header, *current]), location))

    for row in rows:
        if settings.mode is ChunkMode.TABLE_ROW:
            full = len(current) >= settings.table_rows
        else:
            full = estimate_tokens("\n".join([*header, *current, row])) > settings.target_tokens
        if current and full:
            append()
            start += len(current)
            current = []
        current.append(row)
    if current:
        append()
    return parts


def semantic_units(result: ParseResult, settings: ChunkSettings) -> list[StructuredBlock]:
    units: list[StructuredBlock] = []
    for group, block in enumerate(_text_groups(result, by_title=True)):
        if block.kind is not ChunkKind.TEXT:
            continue
        sentences = re.split(r"(?<=[。！？!?；])\s*|(?<=[.!?])\s+|\n\s*\n", block.content)
        for sentence in sentences:
            for content in _split(sentence, settings.target_tokens):
                if content.strip():
                    units.append(
                        block.model_copy(
                            update={
                                "content": content,
                                "metadata": {**block.metadata, "semantic_group": group},
                            }
                        )
                    )
    return units


def _cosine(left: list[float], right: list[float]) -> float:
    norm = math.sqrt(sum(x * x for x in left) * sum(y * y for y in right))
    return sum(x * y for x, y in zip(left, right, strict=True)) / norm if norm else 0


def chunking_warnings(result: ParseResult, settings: ChunkSettings) -> list[str]:
    warnings = list(result.warnings)
    if settings.mode is ChunkMode.TITLE and not any(b.title_path for b in result.blocks):
        warnings.append("未识别到标题层级，按连续正文分组后使用目标长度切分。")
    if settings.mode is ChunkMode.DELIMITER and not any(
        settings.delimiter in b.content for b in _text_groups(result)
    ):
        warnings.append("正文中未找到指定分隔符，使用目标长度对正文切分。")
    if settings.mode in {ChunkMode.PAGE, ChunkMode.QA, ChunkMode.TABLE_ROW, ChunkMode.SEMANTIC}:
        warnings.append("当前模式按完整单元或语义边界分组，不添加相邻分块重叠。")
    if settings.mode is ChunkMode.SEMANTIC:
        warnings.append("语义分块使用知识库 Embedding 服务；首次预览或修改参数会产生额外模型调用。")
    return warnings


def build_chunk_preview(
    result: ParseResult,
    settings: ChunkSettings,
    *,
    vectors: list[list[float]] | None = None,
) -> list[ChunkPreview]:
    mode = settings.mode
    preview: list[ChunkPreview] = []

    def emit(block: StructuredBlock, content: str, **metadata) -> None:
        content = content.strip()
        if content:
            preview.append(
                ChunkPreview(
                    ordinal=len(preview),
                    kind=block.kind,
                    content=content,
                    token_count=estimate_tokens(content),
                    char_count=len(content),
                    title_path=block.title_path,
                    page_from=block.page_from,
                    page_to=block.page_to,
                    sheet_name=block.sheet_name,
                    cell_range=block.cell_range,
                    object_key=block.object_key,
                    metadata={
                        **block.metadata,
                        "source_ordinal": block.ordinal,
                        "chunk_mode": mode.value,
                        **metadata,
                    },
                )
            )

    def emit_table(block: StructuredBlock) -> None:
        for content, location in _table_parts(block, settings):
            emit(block.model_copy(update={"cell_range": location}), content, atomic_unit="table_rows")

    if mode is ChunkMode.PAGE:
        if any(b.page_from is None or b.page_from != b.page_to for b in result.blocks):
            raise DocumentParseError(
                "page_boundaries_missing",
                "按页切分需要准确页码，请使用带页码的 PDF / OCR 结果，或选择其他模式。",
            )
        for _, blocks in groupby(result.blocks, key=lambda b: b.page_from):
            block = _merge(list(blocks)).model_copy(update={"kind": ChunkKind.TEXT})
            emit(block, block.content, atomic_unit="page")
        return preview

    if mode is ChunkMode.TABLE_ROW and not any(b.kind is ChunkKind.TABLE for b in result.blocks):
        raise DocumentParseError(
            "table_structure_missing",
            "未识别到表格结构，请选择 Excel / CSV 或包含结构化表格的解析结果。",
        )

    if mode is ChunkMode.SEMANTIC:
        units = semantic_units(result, settings)
        if vectors is None or len(vectors) != len(units):
            raise DocumentParseError("semantic_vectors_required", "语义分块需要先完成 Embedding 预览。")
        if len({len(v) for v in vectors}) > 1 or any(
            not v or any(not math.isfinite(x) for x in v) for v in vectors
        ):
            raise DocumentParseError(
                "semantic_vectors_invalid", "语义分块收到无效向量，请检查 Embedding 模型。"
            )
        offset = 0
        for _, group_iter in groupby(units, key=lambda b: b.metadata["semantic_group"]):
            group = list(group_iter)
            current: list[str] = []
            for unit in group:
                boundary = bool(current) and (
                    _cosine(vectors[offset - 1], vectors[offset]) < settings.semantic_threshold
                    or estimate_tokens("\n".join([*current, unit.content])) > settings.target_tokens
                )
                if boundary:
                    emit(unit, "\n".join(current))
                    current = []
                current.append(unit.content)
                offset += 1
            emit(group[-1], "\n".join(current))
        for block in result.blocks:
            if block.kind is ChunkKind.TABLE:
                emit_table(block)
            elif block.kind is not ChunkKind.TEXT:
                emit(block, block.content)
        preview.sort(key=lambda item: item.metadata["source_ordinal"])
        for ordinal, item in enumerate(preview):
            item.ordinal = ordinal
        return preview

    blocks = (
        result.blocks
        if mode is ChunkMode.SMART
        else _text_groups(
            result,
            by_title=mode in {ChunkMode.TITLE, ChunkMode.PARENT_CHILD},
        )
    )
    qa_count = 0
    for block in blocks:
        if block.kind is ChunkKind.TABLE:
            emit_table(block)
            continue
        if mode is ChunkMode.PARENT_CHILD:
            for parent_index, parent in enumerate(_split(block.content, settings.parent_target_tokens)):
                parent_id = hashlib.sha256(f"{block.ordinal}:{parent_index}:{parent}".encode()).hexdigest()[
                    :24
                ]
                for child in _split(parent, settings.target_tokens, settings.overlap_tokens):
                    emit(block, child, parent_id=parent_id, parent_content=parent)
        elif mode is ChunkMode.QA:
            matches = list(_QUESTION.finditer(block.content))
            if matches and block.content[: matches[0].start()].strip():
                emit(block, block.content[: matches[0].start()], atomic_unit="preface")
            for index, match in enumerate(matches):
                end = matches[index + 1].start() if index + 1 < len(matches) else len(block.content)
                pair = block.content[match.start() : end]
                if not _ANSWER.search(pair):
                    raise DocumentParseError(
                        "qa_answer_missing",
                        "存在没有回答的问答项，请检查 Q:/A: 或 问：/答：标记。",
                    )
                emit(block, pair, atomic_unit="qa_pair")
                qa_count += 1
            if not matches and block.content.strip():
                emit(block, block.content, atomic_unit="unmatched_text")
        elif mode is ChunkMode.DELIMITER:
            for section in block.content.split(settings.delimiter):
                for content in _split(section, settings.target_tokens, settings.overlap_tokens):
                    emit(block, content)
        else:
            for content in _split(
                block.content, settings.target_tokens, settings.overlap_tokens, fixed=mode is ChunkMode.FIXED
            ):
                emit(block, content)
    if mode is ChunkMode.QA and not qa_count:
        raise DocumentParseError(
            "qa_pairs_missing",
            "未识别到问答对，请使用 Q:/A: 或 问：/答：格式，或选择其他分块模式。",
        )
    return preview
