"""Local parsers for data that does not need OCR or layout understanding."""

from __future__ import annotations

import csv
import re
from collections.abc import Iterable
from pathlib import Path

from docx import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from pypdf import PdfReader

from app.models.enums import ChunkKind, ParserKind
from app.schemas.knowledge import ParseResult, StructuredBlock
from app.services.document_parsers.base import DocumentParseError


def _decode_text(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise DocumentParseError("text_encoding_error", "文本编码无法识别，请另存为 UTF-8 后重试。")


def _markdown_table(rows: Iterable[Iterable[object]]) -> str:
    normalized = [["" if cell is None else str(cell).strip() for cell in row] for row in rows]
    normalized = [row for row in normalized if any(row)]
    if not normalized:
        return ""
    width = max(len(row) for row in normalized)
    padded = [row + [""] * (width - len(row)) for row in normalized]
    header = padded[0]
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * width) + " |"]
    lines.extend("| " + " | ".join(row) + " |" for row in padded[1:])
    return "\n".join(lines)


class LocalDocumentParser:
    def parse(self, path: Path, *, filename: str | None = None) -> ParseResult:
        extension = Path(filename or path.name).suffix.casefold()
        try:
            if extension in {".md", ".markdown"}:
                return self._parse_markdown(path)
            if extension == ".csv":
                return self._parse_csv(path)
            if extension == ".docx":
                return self._parse_docx(path)
            if extension == ".xlsx":
                return self._parse_xlsx(path)
            if extension == ".pdf":
                return self._parse_pdf(path)
        except DocumentParseError:
            raise
        except Exception as exc:
            raise DocumentParseError(
                "local_parse_failed", "文件解析失败，文件可能损坏或内容格式不受支持。"
            ) from exc
        raise DocumentParseError("unsupported_local_format", "该格式不能使用本地解析器。")

    def _parse_markdown(self, path: Path) -> ParseResult:
        text = _decode_text(path.read_bytes()).replace("\r\n", "\n")
        headings: list[str] = []
        blocks: list[StructuredBlock] = []
        buffer: list[str] = []

        def flush() -> None:
            content = "\n".join(buffer).strip()
            if content:
                blocks.append(
                    StructuredBlock(
                        ordinal=len(blocks),
                        kind=ChunkKind.TEXT,
                        content=content,
                        title_path=headings.copy(),
                    )
                )
            buffer.clear()

        for line in text.splitlines():
            match = re.match(r"^(#{1,6})\s+(.+?)\s*#*$", line)
            if match:
                flush()
                level = len(match.group(1))
                headings[:] = headings[: level - 1]
                headings.append(match.group(2).strip())
            else:
                buffer.append(line)
        flush()
        return ParseResult(parser_kind=ParserKind.LOCAL, blocks=blocks)

    def _parse_csv(self, path: Path) -> ParseResult:
        text = _decode_text(path.read_bytes())
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.reader(text.splitlines(), dialect=dialect))
        content = _markdown_table(rows)
        blocks = (
            []
            if not content
            else [
                StructuredBlock(
                    ordinal=0,
                    kind=ChunkKind.TABLE,
                    content=content,
                    cell_range=f"A1:{get_column_letter(max(map(len, rows), default=1))}{len(rows)}",
                    metadata={
                        "row_count": len(rows),
                        "row_numbers": [
                            i for i, row in enumerate(rows, 1) if any(str(cell).strip() for cell in row)
                        ],
                    },
                )
            ]
        )
        return ParseResult(parser_kind=ParserKind.LOCAL, blocks=blocks)

    def _parse_docx(self, path: Path) -> ParseResult:
        document = DocxDocument(path)
        headings: list[str] = []
        blocks: list[StructuredBlock] = []
        for child in document.element.body.iterchildren():
            if child.tag.endswith("}p"):
                paragraph = Paragraph(child, document)
                text = paragraph.text.strip()
                if not text:
                    continue
                style = (paragraph.style.name or "") if paragraph.style else ""
                match = re.search(r"Heading\s+(\d+)", style, re.IGNORECASE)
                if match:
                    level = max(1, min(6, int(match.group(1))))
                    headings[:] = headings[: level - 1]
                    headings.append(text)
                else:
                    blocks.append(
                        StructuredBlock(
                            ordinal=len(blocks),
                            kind=ChunkKind.TEXT,
                            content=text,
                            title_path=headings.copy(),
                        )
                    )
            elif child.tag.endswith("}tbl"):
                table = Table(child, document)
                content = _markdown_table([[cell.text for cell in row.cells] for row in table.rows])
                if content:
                    blocks.append(
                        StructuredBlock(
                            ordinal=len(blocks),
                            kind=ChunkKind.TABLE,
                            content=content,
                            title_path=headings.copy(),
                            metadata={"row_count": len(table.rows)},
                        )
                    )
        return ParseResult(parser_kind=ParserKind.LOCAL, blocks=blocks)

    def _parse_xlsx(self, path: Path) -> ParseResult:
        workbook = load_workbook(path, read_only=True, data_only=True)
        blocks: list[StructuredBlock] = []
        warnings: list[str] = []
        for sheet in workbook.worksheets:
            rows = list(sheet.iter_rows(values_only=True))
            content = _markdown_table(rows)
            if not content:
                warnings.append(f"工作表“{sheet.title}”为空，已跳过。")
                continue
            max_columns = max((len(row) for row in rows), default=1)
            blocks.append(
                StructuredBlock(
                    ordinal=len(blocks),
                    kind=ChunkKind.TABLE,
                    content=content,
                    title_path=[sheet.title],
                    sheet_name=sheet.title,
                    cell_range=f"A1:{get_column_letter(max_columns)}{len(rows)}",
                    metadata={
                        "row_count": len(rows),
                        "row_numbers": [
                            i
                            for i, row in enumerate(rows, 1)
                            if any(cell is not None and str(cell).strip() for cell in row)
                        ],
                    },
                )
            )
        workbook.close()
        return ParseResult(parser_kind=ParserKind.LOCAL, blocks=blocks, warnings=warnings)

    def _parse_pdf(self, path: Path) -> ParseResult:
        reader = PdfReader(path)
        blocks = []
        for index, page in enumerate(reader.pages, start=1):
            content = (page.extract_text() or "").strip()
            if content:
                blocks.append(
                    StructuredBlock(
                        ordinal=len(blocks),
                        kind=ChunkKind.TEXT,
                        content=content,
                        page_from=index,
                        page_to=index,
                    )
                )
        if not blocks:
            raise DocumentParseError("pdf_requires_ocr", "PDF 未提取到文本，请改用云端 OCR 解析。")
        return ParseResult(parser_kind=ParserKind.LOCAL, blocks=blocks, page_count=len(reader.pages))
