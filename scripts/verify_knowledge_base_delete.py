"""One targeted local check using disposable rows inside a rolled-back transaction.

Run from the project root with PYTHONPATH=backend backend/.venv/bin/python
scripts/verify_knowledge_base_delete.py. No provider requests or user-row mutations.
"""

import asyncio
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Environment, Settings
from app.db.session import engine, get_db_session
from app.main import create_app
from app.models.assistant import Assistant, AssistantKnowledgeBase
from app.models.enums import BuildStatus, BuildTaskType, ChunkKind, DocumentSourceType, ModelKind, ParserKind
from app.models.knowledge import BuildTask, Document, DocumentVersion, KnowledgeBase, KnowledgeChunk
from app.models.provider import ModelConfig
from app.services.build_lock import lock_build_task
from app.services.object_storage import get_bytes, put_bytes, remove_object


async def main():
    checks = []
    uid = uuid.uuid4().hex
    keys = [f"original/delete-check-{uid}/source.md", f"parsed/delete-check-{uid}.json"]
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        ) as session:
            try:
                before = set(await session.scalars(select(KnowledgeBase.id)))
                model = await session.scalar(select(ModelConfig).where(ModelConfig.kind == ModelKind.EMBEDDING))
                llm_id = await session.scalar(select(ModelConfig.id).where(ModelConfig.kind == ModelKind.LLM))
                assert model and llm_id, "Local check requires configured embedding and LLM models."
                base = KnowledgeBase(
                    name=f"删除功能临时验证-{uid}", embedding_model_config_id=model.id,
                    embedding_dimension=model.embedding_dimension,
                )
                session.add(base)
                await session.flush()
                document = Document(
                    knowledge_base_id=base.id, name="删除功能验证.md",
                    source_type=DocumentSourceType.MARKDOWN,
                    deleted_at=datetime.now(UTC),
                )
                session.add(document)
                await session.flush()
                version = DocumentVersion(
                    document_id=document.id, version_number=1, content_sha256="a" * 64,
                    size_bytes=4, original_object_key=keys[0], parsed_object_key=keys[1],
                    parser_kind=ParserKind.LOCAL, status=BuildStatus.PARSING,
                )
                session.add(version)
                await session.flush()
                task = BuildTask(
                    knowledge_base_id=base.id, document_version_id=version.id,
                    task_type=BuildTaskType.IMPORT, status=BuildStatus.PARSING,
                )
                chunk = KnowledgeChunk(
                    knowledge_base_id=base.id, document_version_id=version.id,
                    embedding_model_config_id=model.id,
                    ordinal=0, kind=ChunkKind.TEXT, content="删除验证", content_sha256="b" * 64,
                )
                assistant = Assistant(name="删除引用保护验证", alias=f"delete-check-{uid}", llm_model_config_id=llm_id)
                session.add_all([task, chunk, assistant])
                await session.flush()
                binding = AssistantKnowledgeBase(assistant_id=assistant.id, knowledge_base_id=base.id)
                session.add(binding)
                await session.flush()
                base_id, document_id, task_id, binding_id = base.id, document.id, task.id, binding.id
                await session.commit()
                for key in keys:
                    put_bytes(key, b"test")
                app = create_app(Settings(environment=Environment.TEST, _env_file=None))

                async def test_session():
                    try:
                        yield session
                    except Exception:
                        await session.rollback()
                        raise

                app.dependency_overrides[get_db_session] = test_session
                route = f"/api/v1/knowledge-bases/{base_id}"
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                    denied = await client.delete(route, headers={"X-Experience-Role": "user"})
                    assert denied.status_code == 403, denied.text
                    checks.append("使用者无权删除：403")
                    protected = await client.delete(route, headers={"X-Experience-Role": "admin"})
                    assert protected.status_code == 409, protected.text
                    assert protected.json()["detail"]["code"] == "knowledge_base_in_use"
                    assert get_bytes(keys[0]) == b"test"
                    checks.append("助手引用保护：409，原文件保留")
                    await session.execute(delete(AssistantKnowledgeBase).where(AssistantKnowledgeBase.id == binding_id))
                    await session.commit()
                    deleted = await client.delete(route, headers={"X-Experience-Role": "manager"})
                    assert deleted.status_code == 200, deleted.text
                    assert deleted.json()["storage_cleanup_complete"]
                    checks.append("管理人员删除知识库：200")
                    for table, column, value in (
                        (KnowledgeBase, KnowledgeBase.id, base_id),
                        (Document, Document.knowledge_base_id, base_id),
                        (DocumentVersion, DocumentVersion.document_id, document_id),
                        (BuildTask, BuildTask.knowledge_base_id, base_id),
                        (KnowledgeChunk, KnowledgeChunk.knowledge_base_id, base_id),
                    ):
                        assert await session.scalar(select(func.count()).select_from(table).where(column == value)) == 0
                    assert await lock_build_task(session, task_id) is None
                    checks.append("文档（含已删除记录）、版本、分块、任务级联清理，任务不能继续写入")
                    for key in keys:
                        try:
                            get_bytes(key)
                        except FileNotFoundError:
                            pass
                        else:
                            raise AssertionError("Stored test file still exists.")
                    checks.append("原文件和解析文件已清理")
                    missing = await client.delete(route, headers={"X-Experience-Role": "admin"})
                    assert missing.status_code == 404, missing.text
                    remaining = await client.get("/api/v1/knowledge-bases", headers={"X-Experience-Role": "admin"})
                    assert remaining.status_code == 200
                    assert {uuid.UUID(item["id"]) for item in remaining.json()} == before
                    checks.append("删除后列表更新、重复删除返回404，现有知识库保持不变")
            finally:
                await session.close()
                await transaction.rollback()
                for key in keys:
                    remove_object(key)
    report = {"status": "passed", "checks": checks, "user_knowledge_bases_preserved": len(before)}
    destination = Path("artifacts/knowledge-base-delete-check.json")
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
