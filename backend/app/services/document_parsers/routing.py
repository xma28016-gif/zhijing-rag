"""Choose local parsing or DocMind before any document leaves the server."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from pypdf import PdfReader

from app.models.enums import ParserKind
from app.schemas.knowledge import FileDisposition, ParseRoute

LOCAL_EXTENSIONS = {".md", ".markdown", ".csv", ".docx", ".xlsx"}
CLOUD_EXTENSIONS = {".doc", ".xls", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
SUPPORTED_EXTENSIONS = LOCAL_EXTENSIONS | CLOUD_EXTENSIONS | {".pdf"}


def _route(
    disposition: FileDisposition,
    extension: str,
    code: str,
    message: str,
    *,
    parser: ParserKind | None,
    egress: bool = False,
    pages: int | None = None,
) -> ParseRoute:
    return ParseRoute(
        disposition=disposition,
        parser_kind=parser,
        reason_code=code,
        reason_message=message,
        data_egress_required=egress,
        detected_extension=extension,
        page_count=pages,
    )


def determine_parse_route(
    filename: str,
    content: bytes,
    *,
    max_size_bytes: int = 100 * 1024 * 1024,
    max_pages: int = 500,
    enhanced: bool = False,
) -> ParseRoute:
    extension = Path(filename).suffix.casefold()
    if not extension or extension not in SUPPORTED_EXTENSIONS:
        return _route(
            FileDisposition.REJECT,
            extension,
            "unsupported_file_type",
            "暂不支持该文件格式，请上传 Word、PDF、Markdown、Excel、CSV 或常见图片。",
            parser=None,
        )
    if len(content) > max_size_bytes:
        return _route(
            FileDisposition.REJECT,
            extension,
            "file_too_large",
            f"文件超过 {max_size_bytes // (1024 * 1024)} MB 限制。",
            parser=None,
        )
    word_images = False
    if extension == ".docx":
        try:
            with ZipFile(BytesIO(content)) as archive:
                word_images = any(name.startswith("word/media/") for name in archive.namelist())
        except BadZipFile:
            return _route(
                FileDisposition.REJECT,
                extension,
                "damaged_word",
                "Word 文件无法读取，请检查文件是否损坏。",
                parser=None,
            )
    if word_images or (enhanced and extension in {".docx", ".xlsx"}):
        return _route(
            FileDisposition.CLOUD,
            extension,
            "enhanced_office_document",
            "该文档将使用云端增强解析，保留图片文字与复杂结构。",
            parser=ParserKind.DOCMIND,
            egress=True,
        )
    if extension in LOCAL_EXTENSIONS:
        return _route(
            FileDisposition.LOCAL,
            extension,
            "local_parser_supported",
            "文件将在当前服务器内解析，不会发送到云端。",
            parser=ParserKind.LOCAL,
        )
    if extension in CLOUD_EXTENSIONS:
        return _route(
            FileDisposition.CLOUD,
            extension,
            "cloud_parser_required",
            "该格式需要云端文档理解/OCR，确认后文件将发送至 DocMind。",
            parser=ParserKind.DOCMIND,
            egress=True,
        )

    try:
        reader = PdfReader(BytesIO(content))
        pages = len(reader.pages)
        if pages > max_pages:
            return _route(
                FileDisposition.REJECT,
                extension,
                "too_many_pages",
                f"PDF 超过 {max_pages} 页限制。",
                parser=None,
                pages=pages,
            )
        text_chars = 0
        has_images = False
        for page in reader.pages:
            text_chars += len((page.extract_text() or "").strip())
            resources = page.get("/Resources") or {}
            xobjects = resources.get("/XObject") if hasattr(resources, "get") else None
            if xobjects:
                has_images = True
        if not enhanced and pages and text_chars / pages >= 40 and not has_images:
            return _route(
                FileDisposition.LOCAL,
                extension,
                "text_pdf",
                "检测到可提取文本的电子 PDF，将在当前服务器内解析。",
                parser=ParserKind.LOCAL,
                pages=pages,
            )
        return _route(
            FileDisposition.CLOUD,
            extension,
            "complex_or_scanned_pdf",
            "检测到扫描页、图片或复杂版式，确认后文件将发送至 DocMind。",
            parser=ParserKind.DOCMIND,
            egress=True,
            pages=pages,
        )
    except Exception:
        return _route(
            FileDisposition.REJECT,
            extension,
            "damaged_pdf",
            "PDF 无法读取，文件可能损坏或已加密。",
            parser=None,
        )
