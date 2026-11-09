"""Contract checks plus opt-in real PostgreSQL feedback lifecycle verification."""

from __future__ import annotations

import asyncio
import os
import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import psycopg
import pytest
from psycopg import sql
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.v1.endpoints.datasets import scrub_secrets
from app.core.config import Environment, Settings, get_settings
from app.db.session import get_db_session
from app.main import create_app
from app.models.assistant import Assistant
from app.models.chat import ChatConversation, ChatMessage
from app.models.dataset import EvaluationSample
from app.models.enums import ChatRole, ModelKind, RunChannel, RunStatus, RunStepKind
from app.models.provider import ModelConfig, ModelProvider
from app.models.run import RunRecord, RunStep
from app.schemas.dataset import DatasetCreate, SampleUpdate

ROOT = Path(__file__).resolve().parents[2]


def test_case_ready_requires_criteria_and_explicit_confirmation():
    payload = dict(
        revision=1, label="bad", state="ready", note="", reference_answer="", rubric="", ready_confirmed=True
    )
    with pytest.raises(ValidationError):
        SampleUpdate(**payload)
    with pytest.raises(ValidationError):
        SampleUpdate(**{**payload, "rubric": "须引用规则", "ready_confirmed": False})
    assert SampleUpdate(**{**payload, "rubric": "须引用规则"}).state == "ready"
    with pytest.raises(ValidationError):
        DatasetCreate(name="  ")


def test_snapshot_redacts_nested_credentials_without_erasing_usage():
    snapshot = {"api_key": "private", "nested": [{"Authorization": "private", "total_tokens": 23}]}
    assert scrub_secrets(snapshot) == {
        "api_key": "[REDACTED]",
        "nested": [{"Authorization": "[REDACTED]", "total_tokens": 23}],
    }
    assert snapshot["api_key"] == "private"


@pytest.mark.integration
@pytest.mark.skipif(os.getenv("RAG_INTEGRATION_TESTS") != "1", reason="opt-in real PostgreSQL check")
async def test_feedback_persistence_dedup_annotations_and_source_retention():
    source_url = get_settings().database_url
    dsn = source_url.replace("postgresql+psycopg://", "postgresql://")
    admin_dsn = dsn.rsplit("/", 1)[0] + "/postgres"
    database = "case_feedback_test_" + uuid.uuid4().hex[:10]
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    test_url = source_url.rsplit("/", 1)[0] + "/" + database
    engine = create_async_engine(test_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        await asyncio.to_thread(
            subprocess.run,
            [str(ROOT / "backend/.venv/bin/python"), "-m", "alembic", "upgrade", "head"],
            cwd=ROOT / "backend",
            env={**os.environ, "RAG_DATABASE_URL": test_url},
            check=True,
            capture_output=True,
        )
        app = create_app(Settings(environment=Environment.TEST, _env_file=None))

        async def isolated_session():
            async with factory() as session:
                yield session

        app.dependency_overrides[get_db_session] = isolated_session
        now = datetime.now(UTC)
        async with factory() as session:
            provider = ModelProvider(key="case-test", name="test", base_url="http://unused.invalid")
            session.add(provider)
            await session.flush()
            model = ModelConfig(provider_id=provider.id, kind=ModelKind.LLM, name="test", model_id="test")
            session.add(model)
            await session.flush()
            assistant = Assistant(name="验收助手", alias="case-test", llm_model_config_id=model.id)
            session.add(assistant)
            await session.flush()
            conversation = ChatConversation(assistant_id=assistant.id)
            session.add(conversation)
            await session.flush()
            run = RunRecord(
                request_id="case-original",
                assistant_id=assistant.id,
                conversation_id=conversation.id,
                channel=RunChannel.BROWSER,
                status=RunStatus.SUCCEEDED,
                query_text="相同问题",
                answer_text="原始回答",
                config_snapshot={"api_key": "do-not-copy", "top_k": 6},
                started_at=now,
                finished_at=now,
            )
            other = RunRecord(
                request_id="case-other",
                assistant_id=assistant.id,
                channel=RunChannel.API,
                status=RunStatus.FAILED,
                query_text="相同问题",
                error_message="工具超时",
            )
            running = RunRecord(
                request_id="case-running",
                assistant_id=assistant.id,
                channel=RunChannel.BROWSER,
                status=RunStatus.RUNNING,
                query_text="运行中",
            )
            session.add_all([run, other, running])
            await session.flush()
            session.add(
                RunStep(
                    run_id=run.id,
                    sequence=0,
                    kind=RunStepKind.GENERATION,
                    status=RunStatus.SUCCEEDED,
                    input_summary={"question": "相同问题"},
                    output_summary={"answer": "原始回答"},
                )
            )
            session.add_all(
                [
                    ChatMessage(
                        conversation_id=conversation.id,
                        sequence=0,
                        role=ChatRole.USER,
                        content="之前对话",
                        created_at=now - timedelta(minutes=1),
                    ),
                    ChatMessage(
                        conversation_id=conversation.id,
                        sequence=1,
                        role=ChatRole.ASSISTANT,
                        content="未来回答不能收录",
                        created_at=now + timedelta(minutes=1),
                    ),
                ]
            )
            await session.commit()
            run_id, other_id, running_id = str(run.id), str(other.id), str(running.id)
        headers = {"X-Experience-Role": "manager"}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test", headers=headers
        ) as client:
            denied = await client.get("/api/v1/evaluation-datasets", headers={"X-Experience-Role": "user"})
            assert denied.status_code == 403
            created = await client.post("/api/v1/evaluation-datasets", json={"name": "线上精选"})
            assert created.status_code == 201, created.text
            dataset = created.json()["id"]
            path = f"/api/v1/evaluation-datasets/{dataset}/cases"
            payload = {"source_run_id": run_id, "label": "good", "scope": "history", "note": "人工判断"}
            results = await asyncio.gather(client.post(path, json=payload), client.post(path, json=payload))
            assert all(result.status_code == 200 for result in results), [r.text for r in results]
            assert sorted(r.json()["already_exists"] for r in results) == [False, True]
            case = results[0].json()["sample"]
            assert case["state"] == "draft" and case["reference_answer"] == ""
            detail_path = f"{path}/{case['id']}"
            detail = (await client.get(detail_path)).json()
            snapshot = detail["snapshot"]
            assert snapshot["run"]["steps"][0]["output_summary"]["answer"] == "原始回答"
            assert snapshot["run"]["config_snapshot"]["api_key"] == "[REDACTED]"
            assert [item["content"] for item in snapshot["history"]] == ["之前对话"]
            assert detail["source_available"] is True
            duplicate = await client.post(path, json={**payload, "label": "bad"})
            assert duplicate.json()["sample"]["label"] == "good"
            second = await client.post(path, json={**payload, "source_run_id": other_id, "label": "bad"})
            assert second.status_code == 200 and second.json()["sample"]["id"] != case["id"]
            assert (await client.post(path, json={**payload, "source_run_id": running_id})).status_code == 409
            assert (await client.get(path, params={"label": "bad"})).json()["total"] == 1
            update = dict(
                revision=1,
                label="good",
                state="ready",
                note="已检查",
                reference_answer="",
                rubric="",
                ready_confirmed=True,
            )
            assert (await client.patch(detail_path, json=update)).status_code == 422
            update["rubric"] = "必须引用规则"
            saved = await client.patch(detail_path, json=update)
            assert saved.status_code == 200 and saved.json()["revision"] == 2
            assert (await client.patch(detail_path, json=update)).status_code == 409
            archived = await client.patch(detail_path, json={**update, "revision": 2, "state": "archived"})
            assert archived.status_code == 200
            assert (await client.get(path)).json()["total"] == 1
            assert (await client.get(path, params={"state": "archived"})).json()["total"] == 1
            restored = await client.patch(detail_path, json={**update, "revision": 3, "state": "draft"})
            assert restored.json()["revision"] == 4
            counts = (await client.get("/api/v1/evaluation-datasets")).json()[0]
            assert counts["good_count"] == 1 and counts["bad_count"] == 1 and counts["draft_count"] == 2
            # A fresh session reads persisted annotations. Removing the source leaves the snapshot untouched.
            async with factory() as session:
                persisted = await session.scalar(
                    select(EvaluationSample).where(EvaluationSample.id == case["id"])
                )
                assert persisted.revision == 4 and persisted.rubric == "必须引用规则"
                await session.execute(delete(RunRecord).where(RunRecord.id == run_id))
                await session.commit()
            retained = (await client.get(detail_path)).json()
            assert retained["source_available"] is False and retained["snapshot"] == snapshot
            assert (await client.post(path, json=payload)).json()["already_exists"] is True
            # Delete a populated set, including archived cases, without touching other sets or source logs.
            sibling = (await client.post("/api/v1/evaluation-datasets", json={"name": "另一评测集"})).json()
            sibling_path = f"/api/v1/evaluation-datasets/{sibling['id']}/cases"
            sibling_case = (
                await client.post(sibling_path, json={**payload, "source_run_id": other_id})
            ).json()
            assert sibling_case["already_exists"] is False
            assert (
                await client.patch(
                    detail_path,
                    json={
                        **update,
                        "revision": 4,
                        "state": "archived",
                    },
                )
            ).status_code == 200
            delete_path = f"/api/v1/evaluation-datasets/{dataset}"
            assert (
                await client.delete(delete_path, headers={"X-Experience-Role": "user"})
            ).status_code == 403
            assert (await client.get(detail_path)).status_code == 200
            deleted = await client.delete(delete_path)
            assert deleted.status_code == 204 and deleted.content == b""
            assert (await client.get(path)).status_code == 404
            assert (await client.get(detail_path)).status_code == 404
            assert (await client.delete(delete_path)).status_code == 204
            assert (await client.get(sibling_path)).json()["total"] == 1
            assert (await client.get(f"/api/v1/logs/runs/{other_id}")).status_code == 200
            remaining = (await client.get("/api/v1/evaluation-datasets")).json()
            assert [item["id"] for item in remaining] == [sibling["id"]]
            async with factory() as session:
                orphan = await session.scalar(
                    select(EvaluationSample).where(
                        EvaluationSample.dataset_id == dataset,
                    )
                )
                assert orphan is None
    finally:
        await engine.dispose()
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))
