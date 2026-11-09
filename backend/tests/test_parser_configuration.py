from __future__ import annotations

import uuid
from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from docx import Document
from fastapi import FastAPI

from app.api.v1.endpoints import knowledge_bases as endpoints
from app.db.session import get_db_session
from app.models.enums import BuildStatus, ParserKind
from app.models.knowledge import BuildTask, DocumentVersion


@pytest.fixture
def parse_api(monkeypatch):
    now = datetime.now(UTC)
    task = SimpleNamespace(
        id=uuid.uuid4(), knowledge_base_id=uuid.uuid4(), document_version_id=uuid.uuid4(),
        status=BuildStatus.FAILED, progress=25, current_step="failed",
        error_code="docmind_not_configured", error_message="missing", error_details={},
        created_at=now, updated_at=now, attempt_count=1, max_attempts=3,
        cancel_requested=False, started_at=now, finished_at=now,
    )
    version = SimpleNamespace(
        parser_kind=ParserKind.DOCMIND, needs_cloud_parse=True, data_egress_confirmed=True,
        original_object_key="original/policy.docx", status=BuildStatus.FAILED,
        preview_settings={"mode": "title", "target_tokens": 800},
    )
    session = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())

    async def get(model, _id):
        return {BuildTask: task, DocumentVersion: version}.get(model)

    session.get = get
    queue = Mock()
    monkeypatch.setattr(endpoints, "require_document_available", AsyncMock())
    monkeypatch.setattr(endpoints, "refresh_knowledge_base_summary", AsyncMock())
    monkeypatch.setattr(endpoints, "docmind_is_configured", AsyncMock(return_value=False))
    monkeypatch.setattr(endpoints.parse_document, "delay", queue)
    app = FastAPI()
    app.include_router(endpoints.router, prefix="/api/v1")
    app.dependency_overrides[get_db_session] = lambda: session
    return SimpleNamespace(app=app, task=task, version=version, session=session, queue=queue)


@pytest.mark.asyncio
async def test_missing_docmind_rejected_before_confirming_or_dispatching(parse_api):
    fixture = parse_api
    fixture.task.status = BuildStatus.QUEUED
    fixture.version.data_egress_confirmed = False
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=fixture.app), base_url="http://test",
        headers={"X-Experience-Role": "admin"},
    ) as client:
        response = await client.post(
            f"/api/v1/knowledge-bases/build-tasks/{fixture.task.id}/confirm-data-egress"
        )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "docmind_not_configured"
    assert fixture.version.data_egress_confirmed is False
    fixture.queue.assert_not_called()
    fixture.session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_cloud_retry_requires_configuration_without_consuming_an_attempt(parse_api):
    fixture = parse_api
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=fixture.app), base_url="http://test",
        headers={"X-Experience-Role": "admin"},
    ) as client:
        response = await client.post(f"/api/v1/knowledge-bases/build-tasks/{fixture.task.id}/retry")
    assert response.status_code == 409
    assert fixture.task.status is BuildStatus.FAILED
    assert fixture.task.attempt_count == 1
    fixture.queue.assert_not_called()


@pytest.mark.asyncio
async def test_local_retry_checks_original_and_keeps_task_and_chunk_settings(parse_api, monkeypatch):
    fixture = parse_api
    document = Document()
    document.add_paragraph("正文内容。")
    data = BytesIO()
    document.save(data)
    monkeypatch.setattr(endpoints, "get_bytes", lambda _: data.getvalue())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=fixture.app), base_url="http://test",
        headers={"X-Experience-Role": "manager"},
    ) as client:
        response = await client.post(
            f"/api/v1/knowledge-bases/build-tasks/{fixture.task.id}/retry?local_parse=true"
        )
    assert response.status_code == 200, response.text
    assert response.json()["id"] == str(fixture.task.id)
    assert fixture.version.parser_kind is ParserKind.LOCAL
    assert fixture.version.needs_cloud_parse is False
    assert fixture.version.data_egress_confirmed is False
    assert fixture.version.preview_settings == {"mode": "title", "target_tokens": 800}
    assert fixture.task.error_code is None
    fixture.queue.assert_called_once_with(str(fixture.task.id))


@pytest.mark.asyncio
async def test_local_retry_does_not_drop_image_content(parse_api, monkeypatch):
    fixture = parse_api
    fixture.version.original_object_key = "original/scan.png"
    monkeypatch.setattr(endpoints, "get_bytes", lambda _: b"image")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=fixture.app), base_url="http://test",
        headers={"X-Experience-Role": "admin"},
    ) as client:
        response = await client.post(
            f"/api/v1/knowledge-bases/build-tasks/{fixture.task.id}/retry?local_parse=true"
        )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "local_parse_unavailable"
    assert fixture.version.parser_kind is ParserKind.DOCMIND
    assert fixture.version.needs_cloud_parse is True
    assert fixture.task.status is BuildStatus.FAILED
    fixture.queue.assert_not_called()


@pytest.mark.asyncio
async def test_missing_cloud_configuration_rejected_before_storing_import(parse_api, monkeypatch):
    fixture = parse_api
    fixture.session.scalar = AsyncMock(return_value=SimpleNamespace(
        id=fixture.task.knowledge_base_id, batch_file_limit=20, knowledge_base_type="general",
        file_size_limit_bytes=100_000, page_limit=500,
    ))
    fixture.session.flush = AsyncMock()
    fixture.session.add_all = Mock()
    store = Mock()
    monkeypatch.setattr(endpoints, "put_bytes", store)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=fixture.app), base_url="http://test",
        headers={"X-Experience-Role": "admin"},
    ) as client:
        response = await client.post(
            f"/api/v1/knowledge-bases/{fixture.task.knowledge_base_id}/imports",
            files={"files": ("scan.png", b"image", "image/png")},
        )
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["accepted"] is False
    assert item["route"]["reason_code"] == "docmind_not_configured"
    assert item["build_task_id"] is None
    store.assert_not_called()
    fixture.queue.assert_not_called()
