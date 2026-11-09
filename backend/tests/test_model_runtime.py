from __future__ import annotations

import json

import httpx
import pytest

from app.core.crypto import CredentialCipher
from app.models.enums import ModelKind
from app.models.provider import ModelConfig, ModelProvider
from app.schemas.model_config import ProviderKind
from app.services.model_providers.templates import embedding_batch_limit, provider_model_url
from app.services.model_runtime import (
    ProviderCallError,
    complete_chat,
    embed_texts,
    rerank_documents,
    resolve_credentials,
    stream_chat,
)


def configured_model(kind: ModelKind, provider_key: str = "openrouter"):
    cipher = CredentialCipher("runtime-test")
    base_url = (
        "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
        if provider_key == "tongyi"
        else "https://provider.test/v1"
    )
    provider = ModelProvider(
        key=provider_key,
        name=provider_key,
        base_url=base_url,
        encrypted_api_key=cipher.encrypt("sk-runtime"),
        default_headers={},
        capabilities={},
        configuration_schema={},
    )
    model = ModelConfig(
        provider_id=provider.id,
        provider=provider,
        kind=kind,
        name="test",
        model_id="vendor/model",
        extra_headers={},
        extra_config={},
        embedding_dimension=3 if kind is ModelKind.EMBEDDING else None,
    )
    return model, provider, cipher


def test_unreadable_saved_credential_returns_safe_provider_error() -> None:
    model, provider, _ = configured_model(ModelKind.LLM)
    provider.encrypted_api_key = "v1:not-a-valid-ciphertext"

    with pytest.raises(ProviderCallError) as captured:
        resolve_credentials(model, provider, CredentialCipher("runtime-test"))

    assert captured.value.code == "provider_credential_unreadable"
    assert "ciphertext" not in captured.value.safe_message


@pytest.mark.asyncio
async def test_embed_texts_preserves_provider_index_order() -> None:
    model, provider, cipher = configured_model(ModelKind.EMBEDDING)

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer sk-runtime"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [4.0, 5.0, 6.0]},
                    {"index": 0, "embedding": [1.0, 2.0, 3.0]},
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await embed_texts(model, provider, ["a", "b"], cipher, client=client)
    assert result == [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]


@pytest.mark.asyncio
async def test_tongyi_rerank_uses_native_api_path_and_payload_shape() -> None:
    model, provider, cipher = configured_model(ModelKind.RERANK, "tongyi")

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.url.path == "/api/v1/services/rerank/text-rerank/text-rerank"
        assert body["input"]["query"] == "问题"
        assert body["input"]["documents"] == ["甲", "乙"]
        assert body["parameters"] == {"top_n": 2, "return_documents": False}
        return httpx.Response(
            200,
            json={
                "output": {
                    "results": [
                        {"index": 1, "relevance_score": 0.9},
                        {"index": 0, "relevance_score": 0.4},
                    ]
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await rerank_documents(model, provider, "问题", ["甲", "乙"], cipher, top_n=2, client=client)
    assert result == [(1, 0.9), (0, 0.4)]


@pytest.mark.asyncio
async def test_tongyi_embedding_uses_compatible_endpoint_without_unsupported_fields() -> None:
    model, provider, cipher = configured_model(ModelKind.EMBEDDING, "tongyi")

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.url.path == "/compatible-mode/v1/embeddings"
        assert "encoding_format" not in body
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await embed_texts(model, provider, ["测试"], cipher, client=client)
    assert result == [[0.1, 0.2, 0.3]]


def test_tongyi_endpoint_and_batch_contracts() -> None:
    base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert provider_model_url(ProviderKind.TONGYI, ModelKind.RERANK, base_url) == (
        "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
    )
    assert (
        provider_model_url(
            ProviderKind.TONGYI,
            ModelKind.LLM,
            "https://dashscope.aliyuncs.com/api/v1",
        )
        == "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    )
    assert embedding_batch_limit(ProviderKind.TONGYI) == 10
    assert embedding_batch_limit(ProviderKind.OPENROUTER) == 32


@pytest.mark.asyncio
async def test_runtime_errors_do_not_expose_provider_body() -> None:
    model, provider, cipher = configured_model(ModelKind.EMBEDDING)

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="sensitive upstream detail")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderCallError) as captured:
            await embed_texts(model, provider, ["a"], cipher, client=client)
    assert "sensitive" not in captured.value.safe_message


@pytest.mark.asyncio
async def test_complete_chat_marks_provider_usage_exact() -> None:
    model, provider, cipher = configured_model(ModelKind.LLM)

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "vendor/model",
                "choices": [{"message": {"content": "回答"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await complete_chat(
            model, provider, [{"role": "user", "content": "问题"}], cipher, client=client
        )
    assert result.text == "回答"
    assert result.usage.exact is True
    assert result.usage.total_tokens == 5


@pytest.mark.asyncio
async def test_stream_chat_yields_deltas_and_final_usage() -> None:
    model, provider, cipher = configured_model(ModelKind.LLM)
    body = "\n".join(
        [
            'data: {"model":"vendor/model","choices":[{"delta":{"content":"你"}}]}',
            'data: {"choices":[{"delta":{"content":"好"}}]}',
            'data: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":2,"total_tokens":5}}',
            "data: [DONE]",
            "",
        ]
    )

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        events = [
            event
            async for event in stream_chat(
                model, provider, [{"role": "user", "content": "问题"}], cipher, client=client
            )
        ]
    assert "".join(event.delta for event in events) == "你好"
    assert events[-1].usage and events[-1].usage.total_tokens == 5
