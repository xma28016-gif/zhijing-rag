"""Regression coverage for the defects reproduced in the original audit.

Run inside backend with PYTHONPATH=. .venv/bin/pytest tests/test_regressions.py.
External dependencies in these tests use protocol fixtures; full infrastructure
coverage lives in scripts/verify_integration.py.
"""

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.core.crypto import CredentialCipher
from app.models.enums import AssistantStatus, KnowledgeBaseStatus, ModelKind
from app.models.knowledge import KnowledgeBase
from app.models.provider import ModelConfig, ModelProvider
from app.schemas.knowledge import RetrievalHit, RetrievalTestResponse
from app.schemas.model_config import ConnectionTestRequest, ProviderKind
from app.services import chat_pipeline
from app.services.document_parsers.docmind import AlibabaDocMindClient, normalize_docmind_result
from app.services.model_providers.adapters import ProviderAdapter
from app.services.model_runtime import ProviderCallError, embed_texts, resolve_credentials, stream_chat


def model_pair(kind=ModelKind.LLM):
    cipher = CredentialCipher("audit-only-key")
    provider = ModelProvider(
        id=uuid.uuid4(),
        key="tongyi",
        name="audit",
        enabled=True,
        base_url="https://provider.test/compatible-mode/v1",
        encrypted_api_key=cipher.encrypt("audit-fake-credential"),
        default_headers={},
    )
    model = ModelConfig(
        id=uuid.uuid4(),
        provider_id=provider.id,
        kind=kind,
        name="audit",
        model_id="text-embedding-v2" if kind is ModelKind.EMBEDDING else "audit-llm",
        enabled=True,
        extra_headers={},
        embedding_dimension=1536 if kind is ModelKind.EMBEDDING else None,
    )
    return model, provider, cipher


def test_docmind_zero_based_pages_are_preserved():
    result = normalize_docmind_result(
        {
            "Data": {
                "layouts": [
                    {"type": "text", "text": "first page", "pageNum": 0},
                    {"type": "text", "text": "second page", "pageNum": 1},
                ]
            }
        }
    )
    assert [block.page_from for block in result.blocks] == [1, 2]


def test_docmind_fetches_all_layout_pages():
    calls = []

    class Sdk:
        def get_doc_parser_result(self, request):
            calls.append(request.layout_num)
            count = 3000 if request.layout_num == 0 else 1
            payload = {"Data": {"layouts": [{"text": "block"}] * count}}
            return SimpleNamespace(body=SimpleNamespace(to_map=lambda: payload))

    client = AlibabaDocMindClient.__new__(AlibabaDocMindClient)
    client._client = Sdk()
    result = normalize_docmind_result(client.result("audit-job"))
    assert len(result.blocks) == 3001, f"fetched offsets={calls}"


@pytest.mark.asyncio
async def test_auto_detected_embedding_dimension_does_not_change_request_contract():
    model, provider, cipher = model_pair(ModelKind.EMBEDDING)

    async def handler(request):
        body = json.loads(request.content)
        if "dimensions" in body:
            return httpx.Response(400, json={"error": "dimensions unsupported"})
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1] * 1536}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        probe = await ProviderAdapter(
            ConnectionTestRequest(
                provider=ProviderKind.TONGYI,
                kind=ModelKind.EMBEDDING,
                model_id=model.model_id,
                api_key="fake",
                base_url=provider.base_url,
            ),
            client,
        ).test()
        assert probe.ok and probe.dimensions == 1536
        # Saved validation records the detected dimension. Runtime must still work.
        vectors = await embed_texts(model, provider, ["audit text"], cipher, client=client)
    assert len(vectors[0]) == 1536


@pytest.mark.asyncio
async def test_llm_probe_does_not_claim_unverified_streaming_support():
    async def handler(request):
        if json.loads(request.content)["stream"]:
            return httpx.Response(400, json={"error": "streaming unsupported"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        probe = await ProviderAdapter(
            ConnectionTestRequest(
                provider=ProviderKind.TONGYI,
                kind=ModelKind.LLM,
                model_id="audit",
                api_key="fake",
            ),
            client,
        ).test()
    assert probe.ok
    assert not probe.supports_streaming, "only non-streaming was tested"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body,content_type",
    [
        (
            'data: {"error":{"code":"provider_error","message":"failed"}}\n\ndata: [DONE]\n\n',
            "text/event-stream",
        ),
        ('{"choices":[{"message":{"content":"non-streaming response"}}]}', "application/json"),
    ],
)
async def test_streaming_errors_or_non_sse_are_not_success(body, content_type):
    model, provider, cipher = model_pair()

    async def handler(request):
        return httpx.Response(200, text=body, headers={"content-type": content_type})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderCallError):
            _ = [
                event
                async for event in stream_chat(
                    model, provider, [{"role": "user", "content": "audit"}], cipher, client=client
                )
            ]


def test_disabled_provider_is_not_used_by_existing_assistants():
    model, provider, cipher = model_pair()
    provider.enabled = False
    with pytest.raises(ProviderCallError):
        resolve_credentials(model, provider, cipher)


async def prepared_case(monkeypatch, *, status=KnowledgeBaseStatus.READY, history=None, scores=(0.95,)):
    model, provider, _ = model_pair()
    kb_id = uuid.uuid4()
    assistant = SimpleNamespace(
        id=uuid.uuid4(),
        extra_config={},
        status=AssistantStatus.ACTIVE,
        llm_model_config_id=model.id,
        knowledge_base_bindings=[SimpleNamespace(enabled=True, priority=0, knowledge_base_id=kb_id)],
        enable_query_rewrite=bool(history),
        rerank_model_config_id=None,
        semantic_top_k=10,
        keyword_top_k=10,
        rerank_top_k=10,
        answer_top_k=5,
        relevance_threshold=0.6,
        max_context_tokens=1000,
        system_prompt="",
    )
    kb = SimpleNamespace(id=kb_id, status=status, chunk_count=4, embedding_model_config_id=model.id)

    class Session:
        async def scalar(self, statement):
            return assistant

        async def get(self, cls, record_id):
            return {KnowledgeBase: kb, ModelConfig: model, ModelProvider: provider}[cls]

    hits = [
        RetrievalHit(
            chunk_id=uuid.uuid4(),
            document_name="audit.md",
            document_version=1,
            chunk_ordinal=index,
            content="Enterprise policy evidence.",
            title_path=[],
            page_from=None,
            page_to=None,
            sheet_name=None,
            cell_range=None,
            semantic_score=score,
            rrf_score=1 / (61 + index),
        )
        for index, score in enumerate(scores)
    ]
    retrieve = AsyncMock(
        return_value=RetrievalTestResponse(
            query="audit",
            results=hits,
            embedding_ms=1,
            retrieval_ms=1,
            rerank_ms=0,
        )
    )
    monkeypatch.setattr(chat_pipeline, "retrieve_for_test", retrieve)
    monkeypatch.setattr(
        chat_pipeline,
        "complete_chat",
        AsyncMock(
            return_value=SimpleNamespace(
                text="annual leave and sick leave days",
                usage=SimpleNamespace(
                    prompt_tokens=10,
                    completion_tokens=4,
                    total_tokens=14,
                    exact=True,
                ),
            )
        ),
    )
    prepared = await chat_pipeline.prepare_chat(
        Session(),
        assistant_id=assistant.id,
        query="How many days for each?",
        history=history or [],
        require_active=True,
    )
    return prepared, retrieve


@pytest.mark.asyncio
async def test_incremental_build_keeps_existing_knowledge_available(monkeypatch):
    prepared, retrieve = await prepared_case(monkeypatch, status=KnowledgeBaseStatus.BUILDING)
    assert retrieve.await_count == 1, "active chunks should remain searchable while adding files"
    assert prepared.evidence_sufficient


@pytest.mark.asyncio
async def test_followup_generation_receives_disambiguated_question_or_history(monkeypatch):
    history = [SimpleNamespace(role=SimpleNamespace(value="user"), content="annual leave and sick leave")]
    prepared, _ = await prepared_case(monkeypatch, history=history)
    final_prompt = json.dumps(prepared.messages)
    assert "annual leave and sick leave" in final_prompt


@pytest.mark.asyncio
async def test_irrelevant_candidates_are_filtered_before_generation(monkeypatch):
    prepared, _ = await prepared_case(monkeypatch, scores=(0.95, 0.05))
    assert prepared.evidence_sufficient
    assert len(prepared.citations) == 1, "below-threshold evidence should be excluded"
