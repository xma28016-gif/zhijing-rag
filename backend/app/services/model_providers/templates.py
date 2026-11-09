"""Built-in provider metadata. Custom base URLs remain supported."""

from app.models.enums import ModelKind
from app.schemas.model_config import ProviderKind, ProviderTemplate

_TEMPLATES = {
    ProviderKind.OPENROUTER: ProviderTemplate(
        key=ProviderKind.OPENROUTER,
        name="OpenRouter",
        default_base_url="https://openrouter.ai/api/v1",
        capabilities=(ModelKind.LLM, ModelKind.EMBEDDING, ModelKind.RERANK),
        rerank_path="/rerank",
        documentation_url="https://openrouter.ai/docs/guides/evaluate-and-optimize/rag",
        notes="OpenAI-compatible chat and embedding API; model availability depends on the account.",
    ),
    ProviderKind.AIHUBMIX: ProviderTemplate(
        key=ProviderKind.AIHUBMIX,
        name="AIHubMix",
        default_base_url="https://aihubmix.com/v1",
        capabilities=(ModelKind.LLM, ModelKind.EMBEDDING, ModelKind.RERANK),
        rerank_path="/rerank",
        documentation_url="https://docs.aihubmix.com/",
        notes="OpenAI-compatible gateway; a custom base URL can be supplied when using a private route.",
    ),
    ProviderKind.TONGYI: ProviderTemplate(
        key=ProviderKind.TONGYI,
        name="通义百炼",
        default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        capabilities=(ModelKind.LLM, ModelKind.EMBEDDING, ModelKind.RERANK),
        rerank_path="/services/rerank/text-rerank/text-rerank",
        documentation_url="https://help.aliyun.com/zh/model-studio/rerank",
        notes=(
            "LLM/Embedding 使用 OpenAI 兼容地址；Rerank 由系统自动转换为 "
            "DashScope 原生地址。API Key 必须与地域和工作空间匹配。"
        ),
    ),
}


def list_provider_templates() -> list[ProviderTemplate]:
    return list(_TEMPLATES.values())


def get_provider_template(kind: ProviderKind) -> ProviderTemplate:
    return _TEMPLATES[kind]


def provider_model_url(kind: ProviderKind, model_kind: ModelKind, base_url: str) -> str:
    """Build an endpoint without assuming all model types share one base path."""
    normalized = base_url.rstrip("/")
    template = get_provider_template(kind)
    if kind is ProviderKind.TONGYI:
        if model_kind is ModelKind.RERANK:
            # BaiLian exposes chat/embedding through its OpenAI-compatible API
            # but text reranking through the native API on the same host.
            normalized = normalized.replace("/compatible-mode/v1", "/api/v1")
            normalized = normalized.replace("/compatible-api/v1", "/api/v1")
        else:
            # Be forgiving when an administrator pasted the native DashScope
            # base from the rerank documentation into the shared provider form.
            if normalized.endswith("/api/v1"):
                normalized = normalized.removesuffix("/api/v1") + "/compatible-mode/v1"
            normalized = normalized.replace("/compatible-api/v1", "/compatible-mode/v1")
    path = {
        ModelKind.LLM: template.llm_path,
        ModelKind.EMBEDDING: template.embedding_path,
        ModelKind.RERANK: template.rerank_path,
    }[model_kind]
    return f"{normalized}{path}"


def rerank_request_body(
    kind: ProviderKind,
    *,
    model_id: str,
    query: str,
    documents: list[str],
    top_n: int,
) -> dict:
    """Return the provider-specific rerank request contract."""

    if kind is ProviderKind.TONGYI:
        return {
            "model": model_id,
            "input": {"query": query, "documents": documents},
            "parameters": {"top_n": top_n, "return_documents": False},
        }
    return {
        "model": model_id,
        "query": query,
        "documents": documents,
        "top_n": top_n,
    }


def embedding_batch_limit(kind: ProviderKind) -> int:
    """Conservative batch limit shared by indexing and provider contracts."""

    # Current BaiLian text embedding models accept at most ten texts per
    # OpenAI-compatible request. A smaller batch is also valid for older models.
    return 10 if kind is ProviderKind.TONGYI else 32


def supports_embedding_dimensions(model_id: str) -> bool:
    name = model_id.rsplit("/", 1)[-1]
    return name in {"text-embedding-v3", "text-embedding-v4", "qwen3.7-text-embedding"} or (
        name.startswith("text-embedding-3-")
    )
