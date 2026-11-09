"""Content boundaries, source attribution, semantic calls and persisted preview contracts."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from app.api.v1.endpoints import knowledge_bases as endpoints
from app.core.crypto import CredentialCipher
from app.db.session import get_db_session
from app.models.enums import BuildStatus, ChunkKind, ModelKind, ParserKind, ValidationStatus
from app.models.knowledge import BuildTask, DocumentVersion, KnowledgeBase
from app.models.provider import ModelConfig
from app.schemas.knowledge import ChunkSettings, ParseResult, StructuredBlock
from app.services import chunk_previews
from app.services.chunk_previews import cached_preview, generate_preview, preview_snapshot
from app.services.document_parsers import LocalDocumentParser, build_chunk_preview
from app.services.document_parsers.base import DocumentParseError
from app.services.document_parsers.chunking import semantic_units
from app.services.retrieval import retrieval_content, retrieval_parent_id


def parsed(*texts, **kwargs):
    return ParseResult(
        parser_kind=ParserKind.LOCAL,
        blocks=[
            StructuredBlock(ordinal=i, kind=ChunkKind.TEXT, content=text, **kwargs)
            for i, text in enumerate(texts)
        ],
    )


def config(mode, **kwargs):
    return ChunkSettings(mode=mode, target_tokens=100, overlap_tokens=0, **kwargs)


def test_title_merges_paragraphs_without_crossing_chapters():
    result = parsed("第一段", "第二段", title_path=["制度", "范围"])
    result.blocks.append(
        StructuredBlock(ordinal=2, kind=ChunkKind.TEXT, content="例外", title_path=["制度", "例外"])
    )
    chunks = build_chunk_preview(result, config("title"))
    assert [c.content for c in chunks] == ["第一段\n\n第二段", "例外"]
    assert [c.title_path for c in chunks] == [["制度", "范围"], ["制度", "例外"]]


def test_delimiter_is_literal_and_large_sections_still_split():
    chunks = build_chunk_preview(parsed("第一条.*第二条.*" + "长" * 250), config("delimiter", delimiter=".*"))
    assert [c.content for c in chunks[:2]] == ["第一条", "第二条"]
    assert "".join(c.content for c in chunks[2:]) == "长" * 250
    assert all(c.token_count <= 100 for c in chunks)


def test_fixed_length_preserves_text_and_overlap():
    text = "".join(chr(0x4E00 + i) for i in range(260))
    chunks = build_chunk_preview(
        parsed(text), ChunkSettings(mode="fixed", target_tokens=100, overlap_tokens=20)
    )
    assert [len(c.content) for c in chunks] == [100, 100, 100]
    assert chunks[0].content[-20:] == chunks[1].content[:20]
    assert chunks[0].content + "".join(c.content[20:] for c in chunks[1:]) == text


def test_parent_child_stores_children_and_returns_parent_context():
    chunks = build_chunk_preview(parsed("知识" * 240), config("parent_child", parent_target_tokens=200))
    assert len(chunks) > 3
    assert all(c.content in c.metadata["parent_content"] and c.token_count <= 100 for c in chunks)
    assert len({c.metadata["parent_id"] for c in chunks}) == 3
    chunk = SimpleNamespace(
        content=chunks[0].content, source_metadata=chunks[0].metadata, document_version_id=uuid.uuid4()
    )
    assert retrieval_content(chunk) == chunks[0].metadata["parent_content"]
    assert retrieval_parent_id(chunk).startswith(str(chunk.document_version_id))


def test_qa_keeps_question_answer_pairs_and_preface():
    chunks = build_chunk_preview(
        parsed("说明\nQ: 能退货吗？\nA: 七天内可以。\n\n问：如何退款？\n答：原路退回。"), config("qa")
    )
    assert len(chunks) == 3 and chunks[0].content == "说明"
    assert "七天内可以" in chunks[1].content and "如何退款" not in chunks[1].content
    assert "原路退回" in chunks[2].content


def test_page_boundaries_and_same_page_merging():
    result = parsed("页一第一段", "页一第二段", page_from=1, page_to=1)
    result.blocks.append(
        StructuredBlock(ordinal=2, kind=ChunkKind.TEXT, content="页二", page_from=2, page_to=2)
    )
    chunks = build_chunk_preview(result, config("page"))
    assert [c.content for c in chunks] == ["页一第一段\n\n页一第二段", "页二"]
    assert [(c.page_from, c.page_to) for c in chunks] == [(1, 1), (2, 2)]


def test_table_rows_repeat_headers_and_track_actual_rows(tmp_path):
    source = tmp_path / "rows.csv"
    source.write_text("名称,价格\n产品甲,10\n产品乙,20\n产品丙,30")
    chunks = build_chunk_preview(LocalDocumentParser().parse(source), config("table_row", table_rows=2))
    assert len(chunks) == 2 and all(c.content.startswith("| 名称 | 价格 |") for c in chunks)
    assert "产品甲" in chunks[0].content and "产品乙" in chunks[0].content
    assert "产品丙" not in chunks[0].content and "产品丙" in chunks[1].content
    assert [c.cell_range for c in chunks] == ["A2:B3", "A4:B4"]


@pytest.mark.parametrize(
    ("mode", "code"),
    [
        ("page", "page_boundaries_missing"),
        ("qa", "qa_pairs_missing"),
        ("table_row", "table_structure_missing"),
        ("semantic", "semantic_vectors_required"),
    ],
)
def test_missing_structure_has_explicit_error(mode, code):
    with pytest.raises(DocumentParseError) as error:
        build_chunk_preview(parsed("普通正文"), config(mode))
    assert error.value.code == code


def test_invalid_mode_and_parent_size():
    with pytest.raises(ValidationError):
        ChunkSettings(mode="unknown")
    with pytest.raises(ValidationError):
        config("parent_child", parent_target_tokens=100)


def test_semantic_boundaries_follow_embeddings():
    result = parsed("售后支持退货。售后处理退款。新品采用蓝色。新品采用金属。")
    settings = config("semantic", semantic_threshold=0.65)
    assert len(semantic_units(result, settings)) == 4
    chunks = build_chunk_preview(result, settings, vectors=[[1, 0], [0.9, 0.1], [-1, 0], [-0.9, 0.1]])
    assert len(chunks) == 2
    assert "退款" in chunks[0].content and "新品" not in chunks[0].content
    assert "蓝色" in chunks[1].content and "金属" in chunks[1].content


def test_snapshot_replays_and_invalidates_on_settings_or_source():
    settings = config("delimiter", delimiter="###")
    chunks = build_chunk_preview(parsed("甲###乙"), settings)
    snapshot = preview_snapshot(settings, chunks, "parsed/version.json")
    assert cached_preview(snapshot, settings, "parsed/version.json") == chunks
    assert cached_preview(snapshot, config("fixed"), "parsed/version.json") is None
    assert cached_preview(snapshot, settings, "parsed/new.json") is None


@pytest.mark.asyncio
async def test_semantic_uses_configured_model_and_rejects_missing_model(monkeypatch):
    embed = AsyncMock(return_value=[[1.0, 0.0], [0.0, 1.0]])
    monkeypatch.setattr(chunk_previews, "embed_texts", embed)
    model = SimpleNamespace(
        enabled=True,
        kind=ModelKind.EMBEDDING,
        embedding_dimension=2,
        validation_status=ValidationStatus.VALID,
    )
    provider = SimpleNamespace(key="openrouter", enabled=True)
    chunks = await generate_preview(
        parsed("售后退款。新品上市。"),
        config("semantic"),
        model=model,
        provider=provider,
        cipher=CredentialCipher("test-only"),
    )
    assert len(chunks) == 2 and embed.await_count == 1
    assert embed.call_args.args[2] == ["售后退款。", "新品上市。"]
    with pytest.raises(DocumentParseError, match="Embedding"):
        await generate_preview(parsed("正文。"), config("semantic"))


@pytest.mark.asyncio
async def test_api_saves_mode_previews_and_builds_same_snapshot(monkeypatch):
    now = datetime.now(UTC)
    task = SimpleNamespace(
        id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        status=BuildStatus.PREVIEW_READY,
        progress=60,
        current_step="preview_ready",
        error_code=None,
        error_message=None,
        created_at=now,
        updated_at=now,
    )
    version = SimpleNamespace(parsed_object_key="parsed/test.json", preview_settings={})
    kb = SimpleNamespace(embedding_model_config_id=uuid.uuid4())
    session = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())

    async def get(model, _id):
        return {BuildTask: task, DocumentVersion: version, KnowledgeBase: kb, ModelConfig: None}.get(model)

    session.get = get
    app = FastAPI()
    app.include_router(endpoints.router, prefix="/api/v1")
    app.dependency_overrides[get_db_session] = lambda: session
    monkeypatch.setattr(endpoints, "require_document_available", AsyncMock())
    monkeypatch.setattr(endpoints, "get_bytes", lambda _: parsed("甲###乙").model_dump_json().encode())
    queue = Mock()
    monkeypatch.setattr(endpoints.index_document, "delay", queue)
    settings = config("delimiter", delimiter="###").model_dump(mode="json")
    url = f"/api/v1/knowledge-bases/build-tasks/{task.id}"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", headers={"X-Experience-Role": "admin"}
    ) as client:
        assert (await client.put(url + "/chunk-settings", json=settings)).status_code == 200
        response = await client.post(url + "/preview", json=settings)
        assert response.status_code == 200
        assert [c["content"] for c in response.json()["chunks"]] == ["甲", "乙"]
        assert version.preview_settings["mode"] == "delimiter"
        monkeypatch.setattr(
            endpoints, "generate_preview", AsyncMock(side_effect=AssertionError("cache missed"))
        )
        assert (await client.post(url + "/preview", json=settings)).status_code == 200
        assert (await client.post(url + "/build", json=settings)).status_code == 200
        queue.assert_called_once_with(str(task.id))
        assert version.preview_settings["_chunk_cache"]["chunks"][0]["content"] == "甲"
        assert task.current_step == "queued_for_indexing"
        assert (
            await client.put(url + "/chunk-settings", json=config("fixed").model_dump(mode="json"))
        ).status_code == 409
