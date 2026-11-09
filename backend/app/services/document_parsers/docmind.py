"""Alibaba Cloud DocMind adapter behind the common parser contract."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Protocol

from alibabacloud_docmind_api20220711 import models as docmind_models
from alibabacloud_docmind_api20220711.client import Client as DocMindSdkClient
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_tea_util import models as util_models

from app.core.config import Settings, get_settings
from app.models.enums import ChunkKind, ParserKind
from app.schemas.knowledge import ParseResult, StructuredBlock
from app.services.document_parsers.base import DocumentParseError


class DocMindClient(Protocol):
    def submit(self, path: Path, filename: str) -> str: ...
    def status(self, job_id: str) -> dict[str, Any]: ...
    def result(self, job_id: str) -> dict[str, Any]: ...


class AlibabaDocMindClient:
    """Thin wrapper around Alibaba's signed official SDK."""

    def __init__(self, settings: Settings | None = None) -> None:
        resolved = settings or get_settings()
        if not resolved.docmind_access_key_id or not resolved.docmind_access_key_secret:
            raise DocumentParseError(
                "docmind_not_configured",
                "云端增强解析尚未配置 DocMind AccessKey，请在系统设置配置，或对普通文本资料改用本地解析。",
            )
        config = open_api_models.Config(
            access_key_id=resolved.docmind_access_key_id.get_secret_value(),
            access_key_secret=resolved.docmind_access_key_secret.get_secret_value(),
        )
        config.endpoint = resolved.docmind_endpoint
        self._client = DocMindSdkClient(config)

    def submit(self, path: Path, filename: str) -> str:
        with path.open("rb") as file_object:
            request = docmind_models.SubmitDocParserJobAdvanceRequest(
                file_name=filename,
                file_url_object=file_object,
                output_format=["markdown"],
                need_header_footer=False,
            )
            response = self._client.submit_doc_parser_job_advance(
                request,
                util_models.RuntimeOptions(connect_timeout=60_000, read_timeout=60_000),
            )
        body = response.body
        if not body or not body.data or not body.data.id:
            raise DocumentParseError("docmind_submit_failed", "DocMind 未返回任务编号，请稍后重试。")
        return body.data.id

    def status(self, job_id: str) -> dict[str, Any]:
        response = self._client.query_doc_parser_status(docmind_models.QueryDocParserStatusRequest(id=job_id))
        return response.body.to_map() if response.body else {}

    def result(self, job_id: str) -> dict[str, Any]:
        layouts: list[dict[str, Any]] = []
        offset = 0
        metadata: dict[str, Any] = {}
        while True:
            response = self._client.get_doc_parser_result(
                docmind_models.GetDocParserResultRequest(id=job_id, layout_num=offset, layout_step_size=3_000)
            )
            payload = response.body.to_map() if response.body else {}
            data = payload.get("Data") or payload.get("data") or {}
            if not isinstance(data, dict):
                raise DocumentParseError("docmind_result_invalid", "云端解析结果格式无效。")
            metadata.update({key: value for key, value in data.items() if key not in {"layouts", "Layouts"}})
            batch = _find_layouts(data)
            layouts.extend(batch)
            if len(batch) < 3_000:
                break
            offset += len(batch)
            if offset > 300_000:
                raise DocumentParseError("docmind_result_too_large", "解析内容过多，请分拆文档后导入。")
        return {"Data": {**metadata, "layouts": layouts}}


def _find_layouts(data: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("Layouts", "layouts", "Layout", "layout"):
        candidate = data.get(key)
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
    nested = data.get("Data") or data.get("data")
    return _find_layouts(nested) if isinstance(nested, dict) else []


def normalize_docmind_result(payload: dict[str, Any]) -> ParseResult:
    data = payload.get("Data") or payload.get("data") or payload
    if not isinstance(data, dict):
        raise DocumentParseError("docmind_result_invalid", "DocMind 返回结果格式无效。")
    layouts = _find_layouts(data)
    blocks: list[StructuredBlock] = []
    for layout in layouts:
        content = next(
            (
                layout.get(key)
                for key in ("MarkdownContent", "markdownContent", "Text", "text", "Content", "content")
                if isinstance(layout.get(key), str) and layout.get(key).strip()
            ),
            "",
        )
        if not content:
            continue
        raw_type = str(layout.get("Type") or layout.get("type") or "text").casefold()
        kind = (
            ChunkKind.TABLE
            if "table" in raw_type
            else (ChunkKind.IMAGE if "image" in raw_type or "figure" in raw_type else ChunkKind.TEXT)
        )
        page_key = next(
            (key for key in ("pageNum", "PageNum", "page", "Page") if layout.get(key) is not None), None
        )
        page = layout.get(page_key) if page_key else None
        # Official lower-camel-case pageNum is zero based. Preserve legacy
        # one-based PageNum responses accepted by the replaceable parser contract.
        page_number = (
            int(page) + (1 if page_key == "pageNum" or page == 0 else 0) if page is not None else None
        )
        blocks.append(
            StructuredBlock(
                ordinal=len(blocks),
                kind=kind,
                content=content.strip(),
                page_from=page_number,
                page_to=page_number,
                object_key=layout.get("ImageUrl") or layout.get("imageUrl"),
                metadata={"docmind_type": raw_type},
            )
        )
    markdown = data.get("Markdown") or data.get("markdown")
    if not blocks and isinstance(markdown, str) and markdown.strip():
        blocks.append(StructuredBlock(ordinal=0, kind=ChunkKind.TEXT, content=markdown.strip()))
    if not blocks:
        raise DocumentParseError("docmind_result_empty", "DocMind 解析完成但未返回可构建的正文内容。")
    page_count = data.get("PageCountEstimate") or data.get("pageCountEstimate")
    return ParseResult(
        parser_kind=ParserKind.DOCMIND,
        blocks=blocks,
        page_count=int(page_count) if page_count is not None else None,
        parser_metadata={"provider": "docmind"},
    )


class DocMindParser:
    def __init__(self, client: DocMindClient | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = client or AlibabaDocMindClient(self.settings)

    def parse(self, path: Path, *, filename: str | None = None) -> ParseResult:
        job_id = self.client.submit(path, filename or path.name)
        deadline = time.monotonic() + self.settings.docmind_timeout_seconds
        while time.monotonic() < deadline:
            status_payload = self.client.status(job_id)
            data = status_payload.get("Data") or status_payload.get("data") or {}
            state = str(data.get("Status") or data.get("status") or "").casefold()
            if state in {"success", "succeeded", "finish", "finished"}:
                result = normalize_docmind_result(self.client.result(job_id))
                result.parser_metadata["job_id"] = job_id
                return result
            if state in {"fail", "failed", "error"}:
                raise DocumentParseError("docmind_parse_failed", "DocMind 未能解析该文件，请检查文件后重试。")
            time.sleep(self.settings.docmind_poll_interval_seconds)
        raise DocumentParseError("docmind_timeout", "DocMind 解析超时，可稍后从构建任务重试。")
