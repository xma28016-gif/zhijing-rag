"""Small, deterministic provider probes used before persisting a model."""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.models.enums import ModelKind, UsageAccuracy
from app.schemas.model_config import (
    ConnectionTestRequest,
    ConnectionTestResult,
    TokenUsage,
    UsageSource,
)
from app.services.model_providers.templates import (
    get_provider_template,
    provider_model_url,
    rerank_request_body,
    supports_embedding_dimensions,
)


def _estimate_tokens(text: str) -> int:
    # Deliberately labelled as an estimate in the public contract.
    return max(1, (len(text) + 3) // 4)


def _usage(payload: dict[str, Any], fallback_text: str) -> TokenUsage:
    raw = payload.get("usage")
    if isinstance(raw, dict) and any(key in raw for key in ("prompt_tokens", "total_tokens")):
        prompt = int(raw.get("prompt_tokens") or raw.get("input_tokens") or raw.get("total_tokens") or 0)
        completion = int(raw.get("completion_tokens") or raw.get("output_tokens") or 0)
        total = int(raw.get("total_tokens") or prompt + completion)
        return TokenUsage(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            accuracy=UsageAccuracy.EXACT,
            source=UsageSource.PROVIDER,
        )
    estimated = _estimate_tokens(fallback_text)
    return TokenUsage(
        prompt_tokens=estimated,
        completion_tokens=0,
        total_tokens=estimated,
        accuracy=UsageAccuracy.ESTIMATED,
        source=UsageSource.LOCAL_ESTIMATE,
    )


def _safe_error(response: httpx.Response) -> tuple[str, str]:
    code = f"provider_http_{response.status_code}"
    messages = {
        400: "供应商拒绝了测试参数，请核对模型 ID 与模型类型。",
        401: "API Key 无效或与当前服务区域不匹配。",
        403: "当前 API Key 没有调用该模型的权限。",
        404: "未找到模型或接口，请核对 Base URL 与模型 ID。",
        429: "供应商触发限流，请稍后重试或检查账户额度。",
    }
    return code, messages.get(response.status_code, "供应商连接测试失败，请稍后重试。")


class ProviderAdapter:
    """Normalize provider-specific chat, embedding, and rerank probes."""

    def __init__(self, request: ConnectionTestRequest, client: httpx.AsyncClient | None = None) -> None:
        self.request = request
        self.template = get_provider_template(request.provider)
        self.base_url = (request.base_url or self.template.default_base_url).rstrip("/")
        self._client = client

    def _body(self) -> tuple[dict[str, Any], str]:
        probe = "企业知识库连通性测试"
        if self.request.kind is ModelKind.LLM:
            return {
                "model": self.request.model_id,
                "messages": [{"role": "user", "content": probe}],
                "max_tokens": 8,
                "stream": False,
            }, probe
        if self.request.kind is ModelKind.EMBEDDING:
            body: dict[str, Any] = {"model": self.request.model_id, "input": probe}
            if self.request.expected_dimensions and supports_embedding_dimensions(self.request.model_id):
                body["dimensions"] = self.request.expected_dimensions
            return body, probe
        return rerank_request_body(
            self.request.provider,
            model_id=self.request.model_id,
            query=probe,
            documents=["知识库测试文档", "无关内容"],
            top_n=1,
        ), probe

    def _invalid_result(self, *, latency: int, code: str, message: str) -> ConnectionTestResult:
        return ConnectionTestResult(
            ok=False,
            provider=self.request.provider,
            kind=self.request.kind,
            model_id=self.request.model_id,
            latency_ms=latency,
            error_code=code,
            error_message=message,
        )

    async def test(self) -> ConnectionTestResult:
        body, probe = self._body()
        headers = {
            "Authorization": f"Bearer {self.request.api_key.get_secret_value()}",
            "Content-Type": "application/json",
            **self.request.extra_headers,
        }
        started = time.perf_counter()
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self.request.timeout_seconds)
        try:
            response = await client.post(
                provider_model_url(self.request.provider, self.request.kind, self.base_url),
                headers=headers,
                json=body,
            )
            latency = max(0, round((time.perf_counter() - started) * 1000))
            if response.status_code >= 400:
                code, message = _safe_error(response)
                return ConnectionTestResult(
                    ok=False,
                    provider=self.request.provider,
                    kind=self.request.kind,
                    model_id=self.request.model_id,
                    latency_ms=latency,
                    error_code=code,
                    error_message=message,
                )
            payload = response.json()
            provider_code = payload.get("code") if isinstance(payload, dict) else None
            if provider_code:
                return self._invalid_result(
                    latency=latency,
                    code="provider_payload_error",
                    message=f"供应商拒绝了请求（错误码 {str(provider_code)[:80]}）。",
                )
            dimensions = None
            if self.request.kind is ModelKind.EMBEDDING:
                data = payload.get("data") or []
                vector = data[0].get("embedding") if data and isinstance(data[0], dict) else None
                if not isinstance(vector, list) or not vector:
                    return ConnectionTestResult(
                        ok=False,
                        provider=self.request.provider,
                        kind=self.request.kind,
                        model_id=self.request.model_id,
                        latency_ms=latency,
                        error_code="invalid_embedding_response",
                        error_message="供应商未返回有效向量，请确认选择的是 Embedding 模型。",
                    )
                dimensions = len(vector)
                if self.request.expected_dimensions and dimensions != self.request.expected_dimensions:
                    return ConnectionTestResult(
                        ok=False,
                        provider=self.request.provider,
                        kind=self.request.kind,
                        model_id=self.request.model_id,
                        latency_ms=latency,
                        dimensions=dimensions,
                        error_code="embedding_dimension_mismatch",
                        error_message=(
                            f"返回维度为 {dimensions}，与预期 {self.request.expected_dimensions} 不一致。"
                        ),
                    )
            elif self.request.kind is ModelKind.RERANK:
                output = payload.get("output") if isinstance(payload, dict) else None
                results = payload.get("results") if isinstance(payload, dict) else None
                if not isinstance(results, list) and isinstance(output, dict):
                    results = output.get("results")
                if not isinstance(results, list) or not results:
                    return self._invalid_result(
                        latency=latency,
                        code="invalid_rerank_response",
                        message="供应商未返回有效排序结果，请确认选择的是 Rerank 模型。",
                    )
            elif not isinstance(payload.get("choices"), list) or not payload["choices"]:
                return self._invalid_result(
                    latency=latency,
                    code="invalid_llm_response",
                    message="供应商未返回有效对话结果，请确认选择的是 LLM 模型。",
                )
            if self.request.kind is ModelKind.LLM:
                message = payload["choices"][0].get("message", {})
                if not isinstance(message, dict) or not isinstance(message.get("content"), str):
                    return self._invalid_result(
                        latency=latency,
                        code="invalid_llm_response",
                        message="模型未返回文本正文，请检查模型类型。",
                    )
            streaming = False
            if self.request.kind is ModelKind.LLM:
                from app.core.crypto import CredentialCipher
                from app.models.provider import ModelConfig, ModelProvider
                from app.services.model_runtime import ProviderCallError, stream_chat

                cipher = CredentialCipher("connection-probe-ephemeral")
                provider = ModelProvider(
                    key=self.request.provider.value,
                    base_url=self.base_url,
                    encrypted_api_key=cipher.encrypt(self.request.api_key.get_secret_value()),
                    default_headers=self.request.extra_headers,
                    enabled=True,
                )
                model = ModelConfig(model_id=self.request.model_id, extra_headers={}, enabled=True)
                try:
                    events = [
                        event
                        async for event in stream_chat(
                            model,
                            provider,
                            [{"role": "user", "content": "回复 OK"}],
                            cipher,
                            max_tokens=64,
                            client=client,
                        )
                    ]
                    streaming = any(event.delta for event in events)
                except ProviderCallError:
                    # Non-streaming was actually tested above and remains usable.
                    streaming = False
            return ConnectionTestResult(
                ok=True,
                provider=self.request.provider,
                kind=self.request.kind,
                model_id=self.request.model_id,
                returned_model=payload.get("model"),
                latency_ms=latency,
                dimensions=dimensions,
                supports_streaming=streaming,
                usage=_usage(payload, probe),
            )
        except httpx.TimeoutException:
            latency = max(0, round((time.perf_counter() - started) * 1000))
            return ConnectionTestResult(
                ok=False,
                provider=self.request.provider,
                kind=self.request.kind,
                model_id=self.request.model_id,
                latency_ms=latency,
                error_code="provider_timeout",
                error_message="供应商响应超时，请检查网络或稍后重试。",
            )
        except (httpx.HTTPError, ValueError):
            latency = max(0, round((time.perf_counter() - started) * 1000))
            return ConnectionTestResult(
                ok=False,
                provider=self.request.provider,
                kind=self.request.kind,
                model_id=self.request.model_id,
                latency_ms=latency,
                error_code="provider_unreachable",
                error_message="无法连接供应商或响应格式无效。",
            )
        finally:
            if owns_client:
                await client.aclose()


async def test_model_connection(
    request: ConnectionTestRequest, client: httpx.AsyncClient | None = None
) -> ConnectionTestResult:
    return await ProviderAdapter(request, client=client).test()
