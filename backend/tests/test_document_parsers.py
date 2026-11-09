from __future__ import annotations

from pathlib import Path

from docx import Document
from openpyxl import Workbook
from pypdf import PdfWriter

from app.models.enums import ChunkKind
from app.schemas.knowledge import ChunkSettings, FileDisposition
from app.services.document_parsers import (
    LocalDocumentParser,
    build_chunk_preview,
    determine_parse_route,
)


def test_route_keeps_markdown_local_and_requires_consent_for_images() -> None:
    local = determine_parse_route("policy.md", b"# title\ncontent")
    image = determine_parse_route("scan.png", b"not-inspected-here")
    assert local.disposition is FileDisposition.LOCAL
    assert local.data_egress_required is False
    assert image.disposition is FileDisposition.CLOUD
    assert image.data_egress_required is True


def test_route_rejects_unsupported_and_oversized_files() -> None:
    unsupported = determine_parse_route("archive.zip", b"zip")
    oversized = determine_parse_route("notes.md", b"1234", max_size_bytes=3)
    assert unsupported.reason_code == "unsupported_file_type"
    assert oversized.reason_code == "file_too_large"


def test_blank_pdf_is_routed_to_cloud_ocr() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    from io import BytesIO

    output = BytesIO()
    writer.write(output)
    route = determine_parse_route("scan.pdf", output.getvalue())
    assert route.disposition is FileDisposition.CLOUD
    assert route.reason_code == "complex_or_scanned_pdf"


def test_markdown_parser_preserves_heading_path(tmp_path: Path) -> None:
    source = tmp_path / "guide.md"
    source.write_text("# 产品\n介绍。\n\n## 安装\n执行命令。", encoding="utf-8")
    result = LocalDocumentParser().parse(source)
    assert [block.title_path for block in result.blocks] == [["产品"], ["产品", "安装"]]


def test_docx_parser_keeps_text_and_table_structure(tmp_path: Path) -> None:
    source = tmp_path / "guide.docx"
    document = Document()
    document.add_heading("交付", level=1)
    document.add_paragraph("交付前完成验收。")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "事项"
    table.cell(0, 1).text = "负责人"
    table.cell(1, 0).text = "验收"
    table.cell(1, 1).text = "张三"
    document.save(source)
    result = LocalDocumentParser().parse(source)
    assert [block.kind for block in result.blocks] == [ChunkKind.TEXT, ChunkKind.TABLE]
    assert all(block.title_path == ["交付"] for block in result.blocks)


def test_xlsx_parser_records_sheet_and_cell_range(tmp_path: Path) -> None:
    source = tmp_path / "data.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "产品"
    sheet.append(["名称", "版本"])
    sheet.append(["控制台", "1.0"])
    workbook.save(source)
    result = LocalDocumentParser().parse(source)
    assert result.blocks[0].sheet_name == "产品"
    assert result.blocks[0].cell_range == "A1:B2"


def test_table_chunking_repeats_header_and_never_splits_a_row(tmp_path: Path) -> None:
    source = tmp_path / "rows.csv"
    source.write_text(
        "name,description\n" + "\n".join(f"item-{index}," + "说明" * 10 for index in range(12)),
        encoding="utf-8",
    )
    parsed = LocalDocumentParser().parse(source)
    chunks = build_chunk_preview(parsed, ChunkSettings(target_tokens=100, overlap_tokens=10))
    assert len(chunks) > 1
    assert all(chunk.content.startswith("| name | description |") for chunk in chunks)
    assert all(chunk.kind is ChunkKind.TABLE for chunk in chunks)
