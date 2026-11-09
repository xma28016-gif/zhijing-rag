from pathlib import Path

from app.core.config import Environment, Settings
from app.models.enums import ChunkKind, ParserKind
from app.services.document_parsers.docmind import DocMindParser, normalize_docmind_result


class FakeDocMindClient:
    def submit(self, path: Path, filename: str) -> str:
        assert path.exists()
        assert filename == "scan.pdf"
        return "job-123"

    def status(self, job_id: str) -> dict:
        assert job_id == "job-123"
        return {"Data": {"Status": "Success"}}

    def result(self, job_id: str) -> dict:
        return {
            "Data": {
                "PageCountEstimate": 2,
                "Layouts": [
                    {"Type": "title", "Text": "员工手册", "PageNum": 1},
                    {"Type": "table", "MarkdownContent": "| 项目 | 规则 |", "PageNum": 2},
                ],
            }
        }


def test_normalize_docmind_result_preserves_page_and_table() -> None:
    result = normalize_docmind_result(FakeDocMindClient().result("job-123"))
    assert result.parser_kind is ParserKind.DOCMIND
    assert result.page_count == 2
    assert result.blocks[1].kind is ChunkKind.TABLE
    assert result.blocks[1].page_from == 2


def test_docmind_parser_uses_replaceable_client(tmp_path: Path) -> None:
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"fake")
    settings = Settings(
        environment=Environment.TEST,
        docmind_poll_interval_seconds=1,
        docmind_timeout_seconds=60,
        _env_file=None,
    )
    result = DocMindParser(FakeDocMindClient(), settings).parse(source)
    assert result.parser_metadata["job_id"] == "job-123"
