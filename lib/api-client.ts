import type { components } from "@/lib/api-schema";
import type { Role } from "@/lib/types";

export type ApiErrorPayload = {
  detail?: string | { code?: string; message?: string };
};

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export type ProviderRead = components["schemas"]["ModelProviderRead"];
export type ProviderTemplate = components["schemas"]["ProviderTemplate"];
export type ModelConfigRead = components["schemas"]["ModelConfigRead"];
export type KnowledgeBaseRead = components["schemas"]["KnowledgeBaseRead"];
export type DocumentRead = components["schemas"]["DocumentRead"];
export type DocumentContentRead = components["schemas"]["DocumentContentRead"];
export type DocumentSourceRead = components["schemas"]["DocumentSourceRead"];
export type BuildTaskDetailRead = components["schemas"]["BuildTaskDetailRead"];
export type ChunkListResponse = components["schemas"]["ChunkListResponse"];
export type EmbeddingModelOption = components["schemas"]["EmbeddingModelOption"];
export type RerankModelOption = components["schemas"]["RerankModelOption"];
export type ImportBatchRead = components["schemas"]["ImportBatchRead"];
export type ImportItemRead = components["schemas"]["ImportItemRead"];
export type BuildTaskRead = components["schemas"]["BuildTaskRead"];
export type ChunkPreviewResponse = components["schemas"]["ChunkPreviewResponse"];
export type ChunkSettings = components["schemas"]["ChunkSettings"];
export type ChunkMode = components["schemas"]["ChunkMode"];
export type ModelConnectionTestResult = components["schemas"]["ModelConnectionTestResult"];
export type RetrievalTestResponse = components["schemas"]["RetrievalTestResponse"];
export type AssistantRead = components["schemas"]["AssistantRead"];
export type AssistantModelOption = components["schemas"]["AssistantModelOption"];
export type BrowserSessionRead = components["schemas"]["BrowserSessionRead"];
export type ConversationRead = components["schemas"]["ConversationRead"];
export type MessageRead = components["schemas"]["MessageRead"];
export type RunRead = components["schemas"]["RunRead"];
export type RunDetail = components["schemas"]["RunDetail"];
export type DatasetRead = components["schemas"]["DatasetRead"];
export type SampleSummary = components["schemas"]["SampleSummary"];
export type SampleDetail = components["schemas"]["SampleDetail"];
export type DailyMetricRead = components["schemas"]["DailyMetricRead"];
export type ApiKeyRead = components["schemas"]["ApiKeyRead"];
export type ApiKeyCreated = components["schemas"]["ApiKeyCreated"];
export type SystemSettingsRead = components["schemas"]["SystemSettingsRead"];

export type ChatStreamEvent = {
  event: "metadata" | "delta" | "done" | "error";
  data: Record<string, unknown>;
};

function errorDetails(payload: ApiErrorPayload | null, status: number) {
  if (payload && typeof payload.detail === "object") {
    return {
      code: payload.detail.code ?? `http_${status}`,
      message: payload.detail.message ?? "请求失败，请稍后重试。",
    };
  }
  return {
    code: `http_${status}`,
    message: typeof payload?.detail === "string" ? payload.detail : "请求失败，请稍后重试。",
  };
}

export async function apiRequest<T>(
  path: string,
  role: Role,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("X-Experience-Role", role);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  let response: Response;
  try {
    response = await fetch(path, { ...init, headers, cache: "no-store" });
  } catch {
    throw new ApiError(
      0,
      "network_unavailable",
      "无法连接后端服务，请确认 FastAPI、数据库、Redis 与 MinIO 已启动。",
    );
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as ApiErrorPayload | null;
    const details = errorDetails(payload, response.status);
    throw new ApiError(response.status, details.code, details.message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const backendApi = {
  listProviderTemplates: (role: Role) =>
    apiRequest<ProviderTemplate[]>("/api/v1/model-services/templates", role),
  listProviders: (role: Role) =>
    apiRequest<ProviderRead[]>("/api/v1/model-services/providers", role),
  createProvider: (
    role: Role,
    payload: {
      key: "openrouter" | "aihubmix" | "tongyi";
      name: string;
      description?: string;
      base_url?: string;
      api_key: string;
      enabled: boolean;
    },
  ) => apiRequest<ProviderRead>("/api/v1/model-services/providers", role, {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  updateProvider: (
    role: Role,
    providerId: string,
    payload: {
      name?: string;
      description?: string;
      base_url?: string;
      api_key?: string;
      enabled?: boolean;
    },
  ) => apiRequest<ProviderRead>(`/api/v1/model-services/providers/${providerId}`, role, {
    method: "PATCH",
    body: JSON.stringify(payload),
  }),
  listModels: (role: Role) =>
    apiRequest<ModelConfigRead[]>("/api/v1/model-services/models", role),
  createModel: (
    role: Role,
    payload: {
      provider_id: string;
      kind: "llm" | "embedding" | "rerank";
      name: string;
      model_id: string;
      embedding_dimension?: number;
      max_context_tokens?: number;
      enabled: boolean;
      is_default: boolean;
    },
  ) => apiRequest<ModelConfigRead>("/api/v1/model-services/models", role, {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  updateModel: (role: Role, modelId: string, payload: components["schemas"]["ModelConfigUpdate"]) =>
    apiRequest<ModelConfigRead>(`/api/v1/model-services/models/${modelId}`, role, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteModel: (role: Role, modelId: string) =>
    apiRequest<void>(`/api/v1/model-services/models/${modelId}`, role, { method: "DELETE" }),
  testModel: (role: Role, modelId: string) =>
    apiRequest<ModelConnectionTestResult>(
      `/api/v1/model-services/models/${modelId}/test`,
      role,
      { method: "POST" },
    ),
  listKnowledgeBases: (role: Role) =>
    apiRequest<KnowledgeBaseRead[]>("/api/v1/knowledge-bases", role),
  listEmbeddingModelOptions: (role: Role) =>
    apiRequest<EmbeddingModelOption[]>(
      "/api/v1/knowledge-bases/embedding-model-options",
      role,
    ),
  listRerankModelOptions: (role: Role) =>
    apiRequest<RerankModelOption[]>(
      "/api/v1/knowledge-bases/rerank-model-options",
      role,
    ),
  createKnowledgeBase: (
    role: Role,
    payload: {
      name: string;
      description?: string;
      embedding_model_config_id: string;
      knowledge_base_type?: "general" | "table";
      chunk_target_tokens?: number;
      chunk_overlap_tokens?: number;
    },
  ) => apiRequest<KnowledgeBaseRead>("/api/v1/knowledge-bases", role, {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  updateKnowledgeBase: (role: Role, id: string, payload: components["schemas"]["KnowledgeBaseUpdate"]) =>
    apiRequest<KnowledgeBaseRead>(`/api/v1/knowledge-bases/${id}`, role, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteKnowledgeBase: (role: Role, id: string) =>
    apiRequest<components["schemas"]["KnowledgeBaseDeleteRead"]>(`/api/v1/knowledge-bases/${id}`, role, { method: "DELETE" }),
  importDocuments: async (
    role: Role,
    knowledgeBaseId: string,
    files: File[],
    confirmDataEgress = false,
    enhanced = false,
  ): Promise<ImportBatchRead> => {
    const items: ImportItemRead[] = [];
    for (const file of files) {
      const body = new FormData();
      body.append("files", file);
      body.append("confirm_data_egress", String(confirmDataEgress));
      body.append("enhanced", String(enhanced));
      const result = await apiRequest<ImportBatchRead>(
        `/api/v1/knowledge-bases/${knowledgeBaseId}/imports`, role, { method: "POST", body },
      );
      items.push(...result.items);
    }
    return { items };
  },
  getBuildTask: (role: Role, taskId: string) =>
    apiRequest<BuildTaskRead>(`/api/v1/knowledge-bases/build-tasks/${taskId}`, role),
  confirmDataEgress: (role: Role, taskId: string) =>
    apiRequest<BuildTaskRead>(
      `/api/v1/knowledge-bases/build-tasks/${taskId}/confirm-data-egress`,
      role,
      { method: "POST" },
    ),
  previewBuildTask: (
    role: Role,
    taskId: string,
    settings: ChunkSettings,
  ) => apiRequest<ChunkPreviewResponse>(
    `/api/v1/knowledge-bases/build-tasks/${taskId}/preview`,
    role,
    { method: "POST", body: JSON.stringify(settings) },
  ),
  saveChunkSettings: (role: Role, taskId: string, settings: ChunkSettings) => apiRequest<ChunkSettings>(
    `/api/v1/knowledge-bases/build-tasks/${taskId}/chunk-settings`, role,
    { method: "PUT", body: JSON.stringify(settings) },
  ),
  startBuild: (
    role: Role,
    taskId: string,
    settings: ChunkSettings,
  ) => apiRequest<BuildTaskRead>(
    `/api/v1/knowledge-bases/build-tasks/${taskId}/build`,
    role,
    {
      method: "POST",
      body: JSON.stringify(settings),
    },
  ),
  retryBuildTask: (role: Role, taskId: string, localParse = false) =>
    apiRequest<BuildTaskRead>(
      `/api/v1/knowledge-bases/build-tasks/${taskId}/retry${localParse ? "?local_parse=true" : ""}`,
      role,
      { method: "POST" },
    ),
  cancelBuildTask: (role: Role, taskId: string) =>
    apiRequest<BuildTaskRead>(
      `/api/v1/knowledge-bases/build-tasks/${taskId}/cancel`,
      role,
      { method: "POST" },
    ),
  listDocuments: (role: Role, knowledgeBaseId: string, deleted = false) =>
    apiRequest<DocumentRead[]>(`/api/v1/knowledge-bases/${knowledgeBaseId}/documents?deleted=${deleted}`, role),
  getDocumentContent: (role: Role, knowledgeBaseId: string, documentId: string, versionNumber?: number, offset = 0) => {
    const params = new URLSearchParams({ offset: String(offset), limit: "50" });
    if (versionNumber) params.set("version_number", String(versionNumber));
    return apiRequest<DocumentContentRead>(`/api/v1/knowledge-bases/${knowledgeBaseId}/documents/${documentId}/content?${params}`, role);
  },
  getChunkSource: (role: Role, chunkId: string) =>
    apiRequest<DocumentSourceRead>(`/api/v1/knowledge-bases/chunks/${chunkId}/source`, role),
  getDocumentOriginal: async (role: Role, knowledgeBaseId: string, documentId: string, versionNumber?: number) => {
    const params = new URLSearchParams();
    if (versionNumber) params.set("version_number", String(versionNumber));
    let response: Response;
    try {
      response = await fetch(`/api/v1/knowledge-bases/${knowledgeBaseId}/documents/${documentId}/original?${params}`, { headers: { "X-Experience-Role": role }, cache: "no-store" });
    } catch { throw new ApiError(0, "network_unavailable", "无法连接文件服务，请稍后重试。"); }
    if (!response.ok) {
      const details = errorDetails(await response.json().catch(() => null) as ApiErrorPayload | null, response.status);
      throw new ApiError(response.status, details.code, details.message);
    }
    return response.blob();
  },
  deleteDocument: (role: Role, knowledgeBaseId: string, documentId: string) =>
    apiRequest<void>(`/api/v1/knowledge-bases/${knowledgeBaseId}/documents/${documentId}`, role, { method: "DELETE" }),
  restoreDocument: (role: Role, knowledgeBaseId: string, documentId: string) =>
    apiRequest<void>(`/api/v1/knowledge-bases/${knowledgeBaseId}/documents/${documentId}/restore`, role, { method: "POST" }),
  listBuildTasks: (role: Role, knowledgeBaseId: string) =>
    apiRequest<BuildTaskDetailRead[]>(
      `/api/v1/knowledge-bases/${knowledgeBaseId}/build-tasks`,
      role,
    ),
  listChunks: (role: Role, knowledgeBaseId: string, offset = 0, limit = 50) =>
    apiRequest<ChunkListResponse>(
      `/api/v1/knowledge-bases/${knowledgeBaseId}/chunks?offset=${offset}&limit=${limit}`,
      role,
    ),
  retrievalTest: (
    role: Role,
    knowledgeBaseId: string,
    payload: {
      query: string;
      rerank_model_config_id?: string;
      semantic_top_k: number;
      keyword_top_k: number;
      fusion_top_k: number;
      final_top_k: number;
    },
  ) => apiRequest<RetrievalTestResponse>(
    `/api/v1/knowledge-bases/${knowledgeBaseId}/retrieval-test`,
    role,
    { method: "POST", body: JSON.stringify(payload) },
  ),
  listAssistants: (role: Role) =>
    apiRequest<AssistantRead[]>("/api/v1/assistants", role),
  listAssistantModelOptions: (role: Role) =>
    apiRequest<AssistantModelOption[]>("/api/v1/assistants/model-options", role),
  createAssistant: (
    role: Role,
    payload: components["schemas"]["AssistantCreate"],
  ) => apiRequest<AssistantRead>("/api/v1/assistants", role, {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  updateAssistant: (
    role: Role,
    assistantId: string,
    payload: components["schemas"]["AssistantUpdate"],
  ) => apiRequest<AssistantRead>(`/api/v1/assistants/${assistantId}`, role, {
    method: "PATCH",
    body: JSON.stringify(payload),
  }),
  deleteAssistant: (role: Role, assistantId: string) =>
    apiRequest<void>(`/api/v1/assistants/${assistantId}`, role, { method: "DELETE" }),
  createBrowserSession: (role: Role) =>
    apiRequest<BrowserSessionRead>("/api/v1/chat/browser-sessions", role, { method: "POST" }),
  listConversations: (role: Role, browserToken: string) =>
    apiRequest<ConversationRead[]>("/api/v1/chat/conversations", role, {
      headers: { "X-Browser-Session": browserToken },
    }),
  listMessages: (role: Role, browserToken: string, conversationId: string) =>
    apiRequest<MessageRead[]>(`/api/v1/chat/conversations/${conversationId}/messages`, role, {
      headers: { "X-Browser-Session": browserToken },
    }),
  listRuns: (
    role: Role,
    filters: {
      assistantId?: string;
      status?: string;
      query?: string;
      startedAfter?: string;
      limit?: number;
    } = {},
  ) => {
    const params = new URLSearchParams();
    if (filters.assistantId) params.set("assistant_id", filters.assistantId);
    if (filters.status) params.set("run_status", filters.status);
    if (filters.query) params.set("query", filters.query);
    if (filters.startedAfter) params.set("started_after", filters.startedAfter);
    params.set("limit", String(filters.limit ?? 100));
    return apiRequest<RunRead[]>(`/api/v1/logs/runs?${params}`, role);
  },
  getRunDetail: (role: Role, runId: string) =>
    apiRequest<RunDetail>(`/api/v1/logs/runs/${runId}`, role),
  listDatasets: (role: Role) => apiRequest<DatasetRead[]>("/api/v1/evaluation-datasets", role),
  createDataset: (role: Role, payload: components["schemas"]["DatasetCreate"]) =>
    apiRequest<DatasetRead>("/api/v1/evaluation-datasets", role, { method: "POST", body: JSON.stringify(payload) }),
  deleteDataset: (role: Role, id: string) =>
    apiRequest<void>(`/api/v1/evaluation-datasets/${id}`, role, { method: "DELETE" }),
  listDatasetCases: (role: Role, id: string, filters: { label?: string; state?: string; query?: string; offset?: number } = {}) => {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(filters)) if (value !== undefined && value !== "") params.set(key, String(value));
    return apiRequest<components["schemas"]["SamplePage"]>(`/api/v1/evaluation-datasets/${id}/cases?${params}`, role);
  },
  captureCase: (role: Role, id: string, payload: components["schemas"]["SampleCapture"]) =>
    apiRequest<components["schemas"]["CaptureResult"]>(`/api/v1/evaluation-datasets/${id}/cases`, role, { method: "POST", body: JSON.stringify(payload) }),
  getDatasetCase: (role: Role, id: string, sampleId: string) =>
    apiRequest<SampleDetail>(`/api/v1/evaluation-datasets/${id}/cases/${sampleId}`, role),
  updateDatasetCase: (role: Role, id: string, sampleId: string, payload: components["schemas"]["SampleUpdate"]) =>
    apiRequest<SampleSummary>(`/api/v1/evaluation-datasets/${id}/cases/${sampleId}`, role, { method: "PATCH", body: JSON.stringify(payload) }),
  listDailyMetrics: (role: Role, days = 30) =>
    apiRequest<DailyMetricRead[]>(`/api/v1/logs/daily?days=${days}`, role),
  listApiKeys: (role: Role) =>
    apiRequest<ApiKeyRead[]>("/api/v1/api-keys", role),
  createApiKey: (
    role: Role,
    payload: components["schemas"]["ApiKeyCreate"],
  ) => apiRequest<ApiKeyCreated>("/api/v1/api-keys", role, {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  revokeApiKey: (role: Role, apiKeyId: string) =>
    apiRequest<ApiKeyRead>(`/api/v1/api-keys/${apiKeyId}/revoke`, role, { method: "POST" }),
  getSystemSettings: (role: Role) =>
    apiRequest<SystemSettingsRead>("/api/v1/system-settings", role),
  updateSystemSettings: (
    role: Role,
    payload: components["schemas"]["SystemSettingsUpdate"],
  ) => apiRequest<SystemSettingsRead>("/api/v1/system-settings", role, {
    method: "PATCH",
    body: JSON.stringify(payload),
  }),
};

export async function streamAssistantChat({
  role,
  assistantId,
  query,
  conversationId,
  browserToken,
  signal,
  onBrowserToken,
  onEvent,
}: {
  role: Role;
  assistantId: string;
  query: string;
  conversationId?: string;
  browserToken?: string;
  signal: AbortSignal;
  onBrowserToken: (token: string) => void;
  onEvent: (event: ChatStreamEvent) => void;
}) {
  const headers = new Headers({
    "Content-Type": "application/json",
    "X-Experience-Role": role,
  });
  if (browserToken) headers.set("X-Browser-Session", browserToken);
  let response: Response;
  try {
    response = await fetch(`/api/v1/chat/assistants/${assistantId}/completions`, {
      method: "POST",
      headers,
      body: JSON.stringify({ query, conversation_id: conversationId }),
      cache: "no-store",
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") return;
    throw new ApiError(0, "network_unavailable", "无法连接对话服务，请检查后端运行状态。");
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as ApiErrorPayload | null;
    const details = errorDetails(payload, response.status);
    throw new ApiError(response.status, details.code, details.message);
  }
  const nextToken = response.headers.get("X-Browser-Session");
  if (nextToken) onBrowserToken(nextToken);
  if (!response.body) throw new ApiError(502, "empty_stream", "对话服务未返回可读取的流。");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let terminal = false;
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    buffer = buffer.replace(/\r\n/g, "\n");
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      let eventName = "";
      const dataLines: string[] = [];
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) eventName = line.slice(6).trim();
        if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      if (!eventName || dataLines.length === 0) continue;
      const data = JSON.parse(dataLines.join("\n")) as Record<string, unknown>;
      if (eventName === "done" || eventName === "error") terminal = true;
      onEvent({ event: eventName as ChatStreamEvent["event"], data });
    }
    if (done) break;
  }
  if (!terminal && !signal.aborted) throw new ApiError(502, "stream_interrupted", "对话连接意外中断，请重试。");
}
