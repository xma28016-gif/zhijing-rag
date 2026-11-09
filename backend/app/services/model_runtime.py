"""Runtime calls for saved embedding, rerank, and chat model configurations."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.crypto import CredentialCipher, SecretCryptoError
from app.models.enums import ModelKind, ValidationStatus
from app.models.provider import ModelConfig, ModelProvider
from app.schemas.model_config import ProviderKind
from app.services.call_trace import observe, record_usage
from app.services.model_providers.templates import provider_model_url, rerank_request_body


class ProviderCallError(RuntimeError):
    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


@dataclass(slots=True)
class RuntimeCredentials:
    provider_kind: ProviderKind
    base_url: str
    api_key: str
    headers: dict[str, str]


@dataclass(slots=True)
class NormalizedUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    exact: bool


@dataclass(slots=True)
class LLMResult:
    text: str
    returned_model: str | None
    usage: NormalizedUsage


@dataclass(slots=True)
class LLMStreamEvent:
    delta: str = ""
    returned_model: str | None = None
    usage: NormalizedUsage | None = None


def resolve_credentials(
    model: ModelConfig,
    provider: ModelProvider,
    cipher: CredentialCipher,
    *,
    check_validation: bool = True,
) -> RuntimeCredentials:
    if model.enabled is False or provider.enabled is False:
        raise ProviderCallError("model_disabled", "该模型或服务商已停用，请选择可用模型。")
    if check_validation and model.validation_status in {ValidationStatus.INVALID, ValidationStatus.UNTESTED}:
        raise ProviderCallError("model_not_validated", "模型配置已变化或验证失败，请先重新测试。")
    encrypted = model.encrypted_api_key or provider.encrypted_api_key
    if not encrypted:
        raise ProviderCallError("provider_key_missing", "模型供应商尚未配置 API Key。")
    try:
        provider_kind = ProviderKind(provider.key)
    except ValueError as exc:
        raise ProviderCallError("provider_unsupported", "暂不支持该模型供应商。") from exc
    try:
        api_key = cipher.decrypt(encrypted)
    except SecretCryptoError as exc:
        # A rotated master key or corrupted ciphertext must be recoverable from
        # the model-service UI without exposing cryptographic details.
        raise ProviderCallError(
            "provider_credential_unreadable",
            "无法读取已保存的供应商密钥，请重新填写 API Key。",
        ) from exc
    return RuntimeCredentials(
        provider_kind=provider_kind,
        base_url=(model.base_url or provider.base_url).rstrip("/"),
        api_key=api_key,
        headers={**provider.default_headers, **model.extra_headers},
    )


def _headers(credentials: RuntimeCredentials) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {credentials.api_key}",
        "Content-Type": "application/json",
        **credentials.headers,
    }


async def _post(
    url: str,
    *,
    credentials: RuntimeCredentials,
    body: dict[str, Any],
    request_timeout: float = 60,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    owns_client = client is None
    http_client = client or httpx.AsyncClient(timeout=request_timeout)
    try:
        response = await http_client.post(url, headers=_headers(credentials), json=body)
        if response.status_code == 400:
            raise ProviderCallError("provider_bad_request", "供应商拒绝了请求，请核对模型 ID 与模型类型。")
        if response.status_code == 404:
            raise ProviderCallError(
                "provider_model_not_found", "未找到模型或接口，请核对 Base URL 与模型 ID。"
            )
        if response.status_code == 429:
            raise ProviderCallError("provider_rate_limited", "模型供应商触发限流，请稍后重试。")
        if response.status_code in {401, 403}:
            raise ProviderCallError(
                "provider_auth_failed",
                "模型供应商密钥无效、权限不足，或 API Key 与地域不匹配。",
            )
        if response.status_code >= 400:
            raise ProviderCallError("provider_request_failed", "模型供应商请求失败，请检查配置。")
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError
        provider_code = payload.get("code")
        if provider_code:
            normalized_code = str(provider_code)[:80]
            lowered = normalized_code.casefold()
            if "invalidapikey" in lowered or "unauthorized" in lowered:
                raise ProviderCallError(
                    "provider_auth_failed",
                    "模型供应商密钥无效，或 API Key 与地域不匹配。",
                )
            if "throttl" in lowered or "ratelimit" in lowered:
                raise ProviderCallError("provider_rate_limited", "模型供应商触发限流，请稍后重试。")
            raise ProviderCallError(
                "provider_request_failed", f"供应商拒绝了请求（错误码 {normalized_code}）。"
            )
        return payload
    except httpx.TimeoutException as exc:
        raise ProviderCallError("provider_timeout", "模型供应商响应超时。") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise ProviderCallError("provider_unreachable", "无法连接模型供应商或响应格式无效。") from exc
    finally:
        if owns_client:
            await http_client.aclose()


@observe("embedding")
async def embed_texts(
    model: ModelConfig,
    provider: ModelProvider,
    texts: list[str],
    cipher: CredentialCipher,
    *,
    client: httpx.AsyncClient | None = None,
) -> list[list[float]]:
    if not texts:
        return []
    credentials = resolve_credentials(model, provider, cipher)
    body: dict[str, Any] = {"model": model.model_id, "input": texts}
    if model.embedding_dimension and (
        (model.extra_config or {}).get("request_dimensions", False)
        or (
            credentials.provider_kind is ProviderKind.TONGYI
            and model.model_id in {"text-embedding-v3", "text-embedding-v4", "qwen3.7-text-embedding"}
        )
    ):
        body["dimensions"] = model.embedding_dimension
    payload = await _post(
        provider_model_url(credentials.provider_kind, ModelKind.EMBEDDING, credentials.base_url),
        credentials=credentials,
        body=body,
        client=client,
    )
    rows = payload.get("data")
    record_usage(_normalized_usage(payload.get("usage"), prompt_text="\n".join(texts), completion_text=""))
    if not isinstance(rows, list) or len(rows) != len(texts):
        raise ProviderCallError("embedding_response_invalid", "Embedding 返回条数与输入不一致。")
    ordered = sorted(rows, key=lambda item: int(item.get("index", 0)))
    vectors = [item.get("embedding") for item in ordered]
    if any(not isinstance(vector, list) or not vector for vector in vectors):
        raise ProviderCallError("embedding_response_invalid", "Embedding 未返回有效向量。")
    dimensions = {len(vector) for vector in vectors}
    if len(dimensions) != 1 or (model.embedding_dimension and dimensions != {model.embedding_dimension}):
        raise ProviderCallError("embedding_dimension_mismatch", "Embedding 返回维度与配置不一致。")
    return vectors


@observe("rerank")
async def rerank_documents(
    model: ModelConfig,
    provider: ModelProvider,
    query: str,
    documents: list[str],
    cipher: CredentialCipher,
    *,
    top_n: int,
    client: httpx.AsyncClient | None = None,
) -> list[tuple[int, float]]:
    if not documents:
        return []
    credentials = resolve_credentials(model, provider, cipher)
    body = rerank_request_body(
        credentials.provider_kind,
        model_id=model.model_id,
        query=query,
        documents=documents,
        top_n=top_n,
    )
    payload = await _post(
        provider_model_url(credentials.provider_kind, ModelKind.RERANK, credentials.base_url),
        credentials=credentials,
        body=body,
        client=client,
    )
    candidates = payload.get("results")
    record_usage(
        _normalized_usage(payload.get("usage"), prompt_text=query + "\n".join(documents), completion_text="")
    )
    if not isinstance(candidates, list):
        output = payload.get("output") or {}
        candidates = output.get("results") if isinstance(output, dict) else None
    if not isinstance(candidates, list):
        raise ProviderCallError("rerank_response_invalid", "Rerank 未返回有效排序结果。")
    normalized: list[tuple[int, float]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        score = item.get("relevance_score", item.get("score"))
        if isinstance(index, int) and isinstance(score, (int, float)):
            normalized.append((index, float(score)))
    return normalized[:top_n]


def _estimate_text_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def _normalized_usage(raw: Any, *, prompt_text: str, completion_text: str) -> NormalizedUsage:
    if isinstance(raw, dict) and any(key in raw for key in ("prompt_tokens", "input_tokens", "total_tokens")):
        completion = int(raw.get("completion_tokens") or raw.get("output_tokens") or 0)
        prompt = int(
            raw.get("prompt_tokens")
            or raw.get("input_tokens")
            or max(0, int(raw.get("total_tokens") or 0) - completion)
        )
        total = int(raw.get("total_tokens") or prompt + completion)
        return NormalizedUsage(prompt, completion, total, exact=True)
    prompt = _estimate_text_tokens(prompt_text)
    completion = _estimate_text_tokens(completion_text)
    return NormalizedUsage(prompt, completion, prompt + completion, exact=False)


@observe("llm")
async def complete_chat(
    model: ModelConfig,
    provider: ModelProvider,
    messages: list[dict[str, str]],
    cipher: CredentialCipher,
    *,
    temperature: float = 0.2,
    max_tokens: int = 2_048,
    client: httpx.AsyncClient | None = None,
) -> LLMResult:
    credentials = resolve_credentials(model, provider, cipher)
    body = {
        "model": model.model_id,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    payload = await _post(
        provider_model_url(credentials.provider_kind, ModelKind.LLM, credentials.base_url),
        credentials=credentials,
        body=body,
        client=client,
    )
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderCallError("llm_response_invalid", "LLM 未返回有效回答。")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise ProviderCallError("llm_response_invalid", "LLM 未返回文本回答。")
    prompt_text = json.dumps(messages, ensure_ascii=False)
    return LLMResult(
        text=content,
        returned_model=payload.get("model"),
        usage=_normalized_usage(payload.get("usage"), prompt_text=prompt_text, completion_text=content),
    )


@observe("llm")
async def stream_chat(
    model: ModelConfig,
    provider: ModelProvider,
    messages: list[dict[str, str]],
    cipher: CredentialCipher,
    *,
    temperature: float = 0.2,
    max_tokens: int = 2_048,
    client: httpx.AsyncClient | None = None,
) -> AsyncIterator[LLMStreamEvent]:
    credentials = resolve_credentials(model, provider, cipher)
    body = {
        "model": model.model_id,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    owns_client = client is None
    http_client = client or httpx.AsyncClient(timeout=120)
    answer_parts: list[str] = []
    raw_usage: dict[str, Any] | None = None
    returned_model: str | None = None
    prompt_text = json.dumps(messages, ensure_ascii=False)
    try:
        async with http_client.stream(
            "POST",
            provider_model_url(credentials.provider_kind, ModelKind.LLM, credentials.base_url),
            headers=_headers(credentials),
            json=body,
        ) as response:
            if response.status_code == 429:
                raise ProviderCallError("provider_rate_limited", "模型供应商触发限流，请稍后重试。")
            if response.status_code in {401, 403}:
                raise ProviderCallError("provider_auth_failed", "模型供应商密钥无效或权限不足。")
            if response.status_code >= 400:
                raise ProviderCallError("provider_request_failed", "模型供应商请求失败，请检查配置。")
            if "text/event-stream" not in response.headers.get("content-type", "").lower():
                raise ProviderCallError("invalid_stream_protocol", "模型未返回流式响应，请重新测试模型能力。")
            finished = False
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    finished = True
                    continue
                if not data:
                    continue
                try:
                    payload = json.loads(data)
                except json.JSONDecodeError:
                    raise ProviderCallError("invalid_stream_data", "模型返回了无效的流式数据。") from None
                if not isinstance(payload, dict):
                    raise ProviderCallError("invalid_stream_data", "模型返回了无效的流式数据。")
                if payload.get("error") or payload.get("code"):
                    raise ProviderCallError(
                        "provider_stream_error", "模型生成中发生错误，请检查供应商状态后重试。"
                    )
                returned_model = payload.get("model") or returned_model
                if isinstance(payload.get("usage"), dict):
                    raw_usage = payload["usage"]
                choices = payload.get("choices") or []
                if choices and isinstance(choices[0], dict):
                    finish_reason = choices[0].get("finish_reason")
                    if finish_reason in {"error", "content_filter"}:
                        raise ProviderCallError("provider_generation_rejected", "模型未能完成本次回答。")
                    if finish_reason:
                        finished = True
                    delta_payload = choices[0].get("delta") or {}
                    delta = delta_payload.get("content") if isinstance(delta_payload, dict) else None
                    if isinstance(delta, str) and delta:
                        answer_parts.append(delta)
                        yield LLMStreamEvent(delta=delta, returned_model=returned_model)
        answer = "".join(answer_parts)
        if not answer.strip():
            raise ProviderCallError("empty_llm_response", "模型没有返回回答正文，请检查模型能力与参数。")
        if not finished:
            raise ProviderCallError("stream_interrupted", "回答流意外中断，请重试。")
        yield LLMStreamEvent(
            returned_model=returned_model,
            usage=_normalized_usage(raw_usage, prompt_text=prompt_text, completion_text=answer),
        )
    except httpx.TimeoutException as exc:
        raise ProviderCallError("provider_timeout", "模型供应商响应超时。") from exc
    except httpx.HTTPError as exc:
        raise ProviderCallError("provider_unreachable", "无法连接模型供应商。") from exc
    finally:
        if owns_client:
            await http_client.aclose()
