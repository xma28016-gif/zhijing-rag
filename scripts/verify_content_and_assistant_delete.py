"""One local smoke check. Disposable rows are rolled back; no model requests."""

import asyncio
import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Environment, Settings
from app.db.session import engine, get_db_session
from app.main import create_app
from app.models.api_key import ApiKey, ApiKeyAssistant
from app.models.assistant import Assistant, AssistantKnowledgeBase
from app.models.chat import BrowserSession, ChatConversation, ChatMessage
from app.models.enums import (
    AssistantStatus, BuildStatus, ChatRole, ChunkKind, DocumentSourceType,
    ModelKind, ParserKind, RunChannel, RunStatus,
)
from app.models.knowledge import Document, DocumentVersion, KnowledgeBase, KnowledgeChunk
from app.models.provider import ModelConfig
from app.models.run import RunRecord
from app.services.api_keys import api_key_can_use_assistant
from app.services.chat_pipeline import prepare_chat
from app.services.object_storage import get_bytes, put_bytes, remove_object


async def main():
    checks = []
    uid = uuid.uuid4().hex
    keys = [f"original/preview-check-{uid}.md", f"parsed/preview-check-{uid}.json"]
    admin = {"X-Experience-Role": "admin"}
    manager = {"X-Experience-Role": "manager"}
    user = {"X-Experience-Role": "user"}
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        ) as session:
            try:
                before = set(await session.scalars(select(Assistant.id)))
                embedding = await session.scalar(select(ModelConfig).where(ModelConfig.kind == ModelKind.EMBEDDING))
                llm = await session.scalar(select(ModelConfig.id).where(ModelConfig.kind == ModelKind.LLM))
                assert embedding and llm, "Configured local model records are required."
                base = KnowledgeBase(
                    name=f"preview-check-{uid}", embedding_model_config_id=embedding.id,
                    embedding_dimension=embedding.embedding_dimension,
                )
                assistant = Assistant(
                    name="Disposable assistant", alias=f"preview-check-{uid}",
                    llm_model_config_id=llm, status=AssistantStatus.ACTIVE,
                )
                session.add_all([base, assistant])
                await session.flush()
                document = Document(
                    knowledge_base_id=base.id, name="preview-check.md",
                    source_type=DocumentSourceType.MARKDOWN, mime_type="text/markdown",
                )
                browser = BrowserSession(
                    token_hash=hashlib.sha256(uid.encode()).hexdigest(),
                    active_assistant_id=assistant.id, expires_at=datetime.now(UTC) + timedelta(days=1),
                )
                key = ApiKey(
                    name="Disposable key", key_prefix=uid[:16], key_hash=uid * 2, key_hint="test-only",
                )
                session.add_all([document, browser, key])
                await session.flush()
                versions = [DocumentVersion(
                    document_id=document.id, version_number=number, content_sha256=str(number) * 64,
                    size_bytes=17, original_object_key=keys[0] if number == 1 else keys[0] + "-v2", parsed_object_key=keys[1],
                    parser_kind=ParserKind.LOCAL, status=BuildStatus.READY,
                ) for number in (1, 2)]
                conversation = ChatConversation(browser_session_id=browser.id, assistant_id=assistant.id)
                session.add_all([*versions, conversation])
                await session.flush()
                chunk = KnowledgeChunk(
                    knowledge_base_id=base.id, document_version_id=versions[0].id,
                    embedding_model_config_id=embedding.id, ordinal=0, kind=ChunkKind.TEXT,
                    content="Historical content", content_sha256="c" * 64, is_active=False,
                )
                run = RunRecord(
                    assistant_id=assistant.id, conversation_id=conversation.id, request_id=uid,
                    channel=RunChannel.BROWSER, status=RunStatus.SUCCEEDED,
                    query_text="Saved question", answer_text="Saved answer",
                )
                session.add_all([
                    chunk, run,
                    AssistantKnowledgeBase(assistant_id=assistant.id, knowledge_base_id=base.id),
                    ApiKeyAssistant(api_key_id=key.id, assistant_id=assistant.id),
                    ChatMessage(conversation_id=conversation.id, role=ChatRole.ASSISTANT,
                                sequence=0, content="Saved answer"),
                ])
                await session.flush()
                await session.commit()
                put_bytes(keys[0], b"# Original source")
                put_bytes(keys[1], json.dumps({
                    "source_type": "markdown", "parser_kind": "local", "page_count": 1,
                    "blocks": [{"ordinal": i, "kind": "text", "content": f"Paragraph {i}"} for i in range(52)],
                    "warnings": [],
                }).encode())
                app = create_app(Settings(environment=Environment.TEST, _env_file=None))

                async def test_session():
                    yield session

                app.dependency_overrides[get_db_session] = test_session
                content_route = f"/api/v1/knowledge-bases/{base.id}/documents/{document.id}"
                delete_route = f"/api/v1/assistants/{assistant.id}"
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                    denied = await client.get(content_route + "/content", headers=user)
                    assert denied.status_code == 403, denied.text
                    content = await client.get(content_route + "/content", headers=manager)
                    assert content.status_code == 200, content.text
                    assert content.json()["version_number"] == 2
                    assert content.json()["total"] == 52 and len(content.json()["blocks"]) == 50
                    page = await client.get(content_route + "/content?offset=50", headers=admin)
                    assert len(page.json()["blocks"]) == 2
                    source = await client.get(f"/api/v1/knowledge-bases/chunks/{chunk.id}/source", headers=admin)
                    assert source.status_code == 200 and source.json()["version_number"] == 1, source.text
                    original = await client.get(content_route + "/original?version_number=1", headers=admin)
                    assert original.status_code == 200 and original.content == b"# Original source", original.text
                    assert "attachment" in original.headers["content-disposition"]
                    wrong_scope = await client.get(content_route.replace(str(base.id), str(uuid.uuid4())) + "/content", headers=admin)
                    assert wrong_scope.status_code == 404, wrong_scope.text
                    checks.append("File preview, pagination, historical chunk version, original download and role/scope checks")

                    denied = await client.delete(delete_route, headers=user)
                    assert denied.status_code == 403, denied.text
                    deleted = await client.delete(delete_route, headers=manager)
                    assert deleted.status_code == 204, deleted.text
                    assert assistant.status is AssistantStatus.DISABLED and assistant.extra_config["deleted_at"]
                    for role in (admin, manager, user):
                        listing = await client.get("/api/v1/assistants", headers=role)
                        assert listing.status_code == 200, listing.text
                        assert str(assistant.id) not in {item["id"] for item in listing.json()}
                    assert (await client.delete(delete_route, headers=admin)).status_code == 204
                    assert (await client.delete(f"/api/v1/assistants/{uuid.uuid4()}", headers=admin)).status_code == 404
                    assert (await client.patch(delete_route, headers=admin, json={"status": "active"})).status_code == 404
                    for role in (admin, user):
                        denied = await client.post(f"/api/v1/chat/assistants/{assistant.id}/completions", headers=role, json={"query": "Blocked"})
                        assert denied.status_code == 404, denied.text
                    try:
                        await prepare_chat(session, assistant_id=assistant.id, query="Blocked", history=[], require_active=False)
                    except ValueError as error:
                        assert str(error) == "assistant_unavailable"
                    else:
                        raise AssertionError("Deleted assistant accepted a new chat")
                    assert not await api_key_can_use_assistant(session, key, assistant.id)
                    checks.append("Assistant deletion: permission denied for users, removed for every role, idempotent, cannot republish/chat/API")

                    assert await session.scalar(select(func.count()).select_from(AssistantKnowledgeBase).where(AssistantKnowledgeBase.assistant_id == assistant.id)) == 0
                    assert await session.scalar(select(func.count()).select_from(ApiKeyAssistant).where(ApiKeyAssistant.assistant_id == assistant.id)) == 0
                    await session.refresh(browser)
                    assert browser.active_assistant_id is None
                    assert await session.get(KnowledgeBase, base.id)
                    assert await session.get(Document, document.id)
                    assert await session.get(KnowledgeChunk, chunk.id)
                    assert get_bytes(keys[0]) == b"# Original source"
                    saved = await client.get(f"/api/v1/logs/runs/{run.id}", headers=admin)
                    assert saved.status_code == 200 and saved.json()["answer_text"] == "Saved answer", saved.text
                    messages = await client.get(f"/api/v1/chat/conversations/{conversation.id}/messages", headers={**user, "X-Browser-Session": uid})
                    assert messages.status_code == 200 and messages.json()[0]["content"] == "Saved answer", messages.text
                    assert set(await session.scalars(select(Assistant.id))) == before | {assistant.id}
                    checks.append("Knowledge/files/history preserved; only assistant bindings and current selection released; user rows unchanged")
            finally:
                await session.close()
                await transaction.rollback()
                for object_key in keys:
                    remove_object(object_key)
    report = {"status": "passed", "checks": checks, "existing_assistants_preserved": len(before)}
    Path("artifacts/content-and-assistant-delete-check.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    asyncio.run(main())
