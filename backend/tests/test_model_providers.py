from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr

from app.models.enums import ModelKind, UsageAccuracy
from app.schemas.model_config import ConnectionTestRequest, ProviderKind
from app.services.model_providers import test_model_connection as probe_model_connection


def make_request(
    kind: ModelKind,
    *,
    dimensions: int | None = None,
    provider: ProviderKind = ProviderKind.OPENROUTER,
    base_url: str = "https://provider.test/v1",
) -> ConnectionTestRequest:
    return ConnectionTestRequest(
        provider=provider,
        kind=kind,
        model_id="vendor/test-model",
        api_key=SecretStr("sk-sensitive"),
        base_url=base_url,
        expected_dimensions=dimensions,
    )


@pytest.mark.asyncio
async def test_embedding_probe_records_exact_usage_and_dimensions() -> None:
    async def handler(incoming: httpx.Request) -> httpx.Response:
        assert incoming.headers["Authorization"] == "Bearer sk-sensitive"
        return httpx.Response(
            200,
            json={
                "model": "vendor/test-model",
                "data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}],
                "usage": {"prompt_tokens": 6, "total_tokens": 6},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await probe_model_connection(make_request(ModelKind.EMBEDDING, dimensions=3), client)
    assert result.ok is True
    assert result.dimensions == 3
    assert result.usage and result.usage.accuracy is UsageAccuracy.EXACT


@pytest.mark.asyncio
async def test_probe_marks_missing_usage_as_local_estimate() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"model": "vendor/test-model", "choices": [{"message": {"content": "OK"}}]}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await probe_model_connection(make_request(ModelKind.LLM), client)
    assert result.ok is True
    assert result.usage and result.usage.accuracy is UsageAccuracy.ESTIMATED
    assert result.supports_streaming is False


@pytest.mark.asyncio
async def test_probe_returns_safe_message_for_invalid_key() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "leaked provider detail"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await probe_model_connection(make_request(ModelKind.LLM), client)
    assert result.ok is False
    assert result.error_code == "provider_http_401"
    assert "leaked" not in (result.error_message or "")


@pytest.mark.asyncio
async def test_embedding_dimension_mismatch_is_rejected() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await probe_model_connection(make_request(ModelKind.EMBEDDING, dimensions=3), client)
    assert result.ok is False
    assert result.error_code == "embedding_dimension_mismatch"


@pytest.mark.asyncio
async def test_tongyi_rerank_probe_uses_native_contract() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/services/rerank/text-rerank/text-rerank"
        body = request.read().decode()
        assert '"input"' in body
        assert '"parameters"' in body
        return httpx.Response(
            200,
            json={
                "output": {"results": [{"index": 0, "relevance_score": 0.91}]},
                "usage": {"total_tokens": 12},
            },
        )

    request = make_request(
        ModelKind.RERANK,
        provider=ProviderKind.TONGYI,
        base_url="https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await probe_model_connection(request, client)
    assert result.ok is True
    assert result.usage and result.usage.total_tokens == 12


@pytest.mark.asyncio
async def test_probe_rejects_wrong_model_type_response() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"output": {"embeddings": []}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await probe_model_connection(make_request(ModelKind.RERANK), client)
    assert result.ok is False
    assert result.error_code == "invalid_rerank_response"
