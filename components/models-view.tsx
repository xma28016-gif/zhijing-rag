"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Activity, CircleHelp, CloudCog, Cpu, Eye, EyeOff, Plus, RefreshCw, ShieldCheck } from "lucide-react";
import { Button, Card, Field, Input, Modal, Select } from "@/components/ui/primitives";
import { ConfiguredModelList, DefaultModelSettings, ProviderCatalog, modelTypeLabel, type ModelKind } from "@/components/models/model-service-panels";
import { ApiError, backendApi, type ProviderRead, type ModelConfigRead, type ProviderTemplate } from "@/lib/api-client";
import type { Role } from "@/lib/types";

const tongyiRegionUrls = [
  { label: "中国内地（北京）", value: "https://dashscope.aliyuncs.com/compatible-mode/v1" },
  { label: "新加坡", value: "https://dashscope-intl.aliyuncs.com/compatible-mode/v1" },
  { label: "美国（弗吉尼亚）", value: "https://dashscope-us.aliyuncs.com/compatible-mode/v1" },
  { label: "中国香港", value: "https://cn-hongkong.dashscope.aliyuncs.com/compatible-mode/v1" },
] as const;

export function ModelsView({ role, notify }: { role: Role; notify: (title: string, description?: string) => void }) {
  const queryClient = useQueryClient();
  const [dialog, setDialog] = useState<"provider" | "model" | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [showKey, setShowKey] = useState(false);
  const [catalogKind, setCatalogKind] = useState<ModelKind | "all">("all");
  const [continueWithModel, setContinueWithModel] = useState(false);
  const [formError, setFormError] = useState("");
  const [providerForm, setProviderForm] = useState({
    key: "tongyi" as "openrouter" | "aihubmix" | "tongyi",
    name: "通义百炼",
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    apiKey: "",
  });
  const [modelForm, setModelForm] = useState({
    providerId: "",
    kind: "llm" as "llm" | "embedding" | "rerank",
    modelId: "",
    name: "",
    context: "",
    dimension: "",
  });
  const templatesQuery = useQuery({ queryKey: ["provider-templates", role], queryFn: () => backendApi.listProviderTemplates(role) });
  const providersQuery = useQuery({ queryKey: ["model-providers", role], queryFn: () => backendApi.listProviders(role) });
  const modelsQuery = useQuery({ queryKey: ["model-configs", role], queryFn: () => backendApi.listModels(role) });
  const providers = providersQuery.data ?? [];
  const models = modelsQuery.data ?? [];
  const selectedProvider = providers.find((provider) => provider.key === providerForm.key);
  const selectedModelProvider = providers.find((provider) => provider.id === modelForm.providerId);
  const tongyiModelHint = modelForm.kind === "llm"
    ? { id: "qwen-plus", name: "Qwen Plus" }
    : modelForm.kind === "embedding"
      ? { id: "text-embedding-v4", name: "Text Embedding V4" }
      : { id: "qwen3-rerank", name: "Qwen3 Rerank" };

  const openProviderDialog = (provider?: ProviderRead, addAfterSave = false, providerKey: ProviderTemplate["key"] = "tongyi") => {
    const target = provider ?? providers.find((item) => item.key === providerKey);
    const template = templatesQuery.data?.find((item) => item.key === (target?.key ?? providerKey));
    setProviderForm({
      key: (target?.key ?? providerKey) as typeof providerForm.key,
      name: target?.name ?? template?.name ?? providerKey,
      baseUrl: target?.base_url ?? template?.default_base_url ?? "",
      apiKey: "",
    });
    setFormError("");
    setShowKey(false);
    setContinueWithModel(addAfterSave);
    setDialog("provider");
  };

  function openModelDialog(provider?: ProviderRead) {
    const target = provider ?? providers.find((item) => item.enabled && item.api_key_mask);
    if (!target?.enabled || !target.api_key_mask) {
      openProviderDialog(target, true);
      return;
    }
    setEditingId(null);
    setFormError("");
    setModelForm({ providerId: target.id, kind: catalogKind === "all" ? "llm" : catalogKind, modelId: "", name: "", context: "", dimension: "" });
    setDialog("model");
  }

  async function refreshModelOptions() {
    await Promise.all(["model-configs", "embedding-model-options", "rerank-model-options", "assistant-model-options"].map((key) => queryClient.invalidateQueries({ queryKey: [key] })));
  }

  const defaultMutation = useMutation({
    mutationFn: ({ kind, id }: { kind: ModelKind; id: string }) => {
      const current = models.find((model) => model.kind === kind && model.is_default);
      if (id) return backendApi.updateModel(role, id, { is_default: true });
      if (current) return backendApi.updateModel(role, current.id, { is_default: false });
      return Promise.resolve(null);
    },
    onSuccess: (_, { kind, id }) => notify(`${modelTypeLabel[kind]} 默认模型已${id ? "保存" : "清除"}`, "新建知识库或助手时生效。"),
    onSettled: refreshModelOptions,
  });

  const providerMutation = useMutation({
    mutationFn: () => {
      const existing = providers.find((provider) => provider.key === providerForm.key);
      if (existing) {
        return backendApi.updateProvider(role, existing.id, {
          name: providerForm.name.trim(),
          base_url: providerForm.baseUrl.trim(),
          ...(providerForm.apiKey ? { api_key: providerForm.apiKey } : {}),
          enabled: true,
        });
      }
      return backendApi.createProvider(role, {
        key: providerForm.key,
        name: providerForm.name.trim(),
        base_url: providerForm.baseUrl.trim(),
        api_key: providerForm.apiKey,
        enabled: true,
      });
    },
    onSuccess: async (provider) => {
      await queryClient.invalidateQueries({ queryKey: ["model-providers"] });
      await refreshModelOptions();
      if (continueWithModel) {
        setEditingId(null);
        setModelForm({ providerId: provider.id, kind: catalogKind === "all" ? "llm" : catalogKind, modelId: "", name: "", context: "", dimension: "" });
        setDialog("model");
      } else setDialog(null);
      setFormError("");
      setProviderForm((current) => ({ ...current, apiKey: "" }));
      notify("服务商配置已保存", continueWithModel ? "请填写模型 ID，测试通过后即可使用。" : "连接地址或密钥变更后，请重新测试已有模型。");
    },
    onError: (error) => setFormError(error instanceof ApiError ? error.message : "保存服务商失败。"),
  });
  const modelMutation = useMutation({
    mutationFn: async () => {
      const payload = {
        model_id: modelForm.modelId.trim(), name: modelForm.name.trim(),
        embedding_dimension: modelForm.kind === "embedding" && modelForm.dimension ? Number(modelForm.dimension) : undefined,
        max_context_tokens: modelForm.context ? Number(modelForm.context) : undefined,
        enabled: true,
      };
      if (!editingId) return backendApi.createModel(role, {
        ...payload, provider_id: modelForm.providerId, kind: modelForm.kind, is_default: false,
      });
      const updated = await backendApi.updateModel(role, editingId, payload);
      const test = await backendApi.testModel(role, editingId);
      if (!test.ok) throw new ApiError(422, test.error_code ?? "model_test_failed", test.error_message ?? "模型验证失败，配置已保存为待修正状态。");
      return updated;
    },
    onSuccess: async (model) => {
      setDialog(null);
      setFormError("");
      notify("模型测试通过", `${model.name} 已加入可用模型列表。`);
    },
    onError: (error) => setFormError(error instanceof ApiError ? error.message : "模型连通性测试失败。"),
    onSettled: refreshModelOptions,
  });
  const testMutation = useMutation({
    mutationFn: (modelId: string) => backendApi.testModel(role, modelId),
    onSuccess: async (result) => {
      notify(
        result.ok ? "连通性测试通过" : "连通性测试失败",
        result.ok ? `真实请求耗时 ${result.latency_ms}ms。` : result.error_message ?? "请检查配置。",
      );
    },
    onError: (error) => notify("连通性测试失败", error instanceof ApiError ? error.message : "请稍后重试。"),
    onSettled: refreshModelOptions,
  });

  function editModel(model: ModelConfigRead) {
    setEditingId(model.id);
    setModelForm({ providerId: model.provider_id, kind: model.kind, modelId: model.model_id, name: model.name,
      context: model.max_context_tokens ? String(model.max_context_tokens) : "",
      dimension: model.embedding_dimension ? String(model.embedding_dimension) : "" });
    setFormError(""); setDialog("model");
  }
  const deleteMutation = useMutation({
    mutationFn: (id: string) => backendApi.deleteModel(role, id),
    onSuccess: async () => { setDeleteId(null); await refreshModelOptions(); notify("模型配置已删除"); },
  });

  return (
    <div className="space-y-6 fade-in">
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
        <div><h2 className="text-xl font-semibold text-slate-900">模型服务</h2><p className="mt-1 text-sm text-slate-500">接入模型服务商，为知识检索与在线对话选择合适的模型。</p></div>
        <div className="flex gap-2"><Button variant="secondary" onClick={async () => { await Promise.all([providersQuery.refetch(), modelsQuery.refetch(), templatesQuery.refetch()]); notify("模型配置已刷新"); }}><RefreshCw size={15} />刷新</Button><Button onClick={() => openModelDialog()}><Plus size={16} />添加模型</Button></div>
      </div>

      {providersQuery.isError || modelsQuery.isError ? <Card className="flex items-center justify-between gap-4 border-red-100 p-4"><div><strong className="text-sm text-red-800">无法读取模型配置</strong><p className="mt-1 text-xs text-red-600">{(providersQuery.error instanceof ApiError ? providersQuery.error.message : modelsQuery.error instanceof ApiError ? modelsQuery.error.message : "请检查后端服务。")}</p></div><Button variant="secondary" size="sm" onClick={() => { void providersQuery.refetch(); void modelsQuery.refetch(); }}><RefreshCw size={14} />重试</Button></Card> : null}

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_340px] 2xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0 space-y-7">
          <DefaultModelSettings models={models} providers={providers} loading={modelsQuery.isLoading || providersQuery.isLoading || modelsQuery.isError || providersQuery.isError} pending={defaultMutation.isPending} error={defaultMutation.error instanceof ApiError ? defaultMutation.error.message : defaultMutation.error ? "默认模型保存失败，请重试。" : ""} onChange={(kind, id) => defaultMutation.mutate({ kind, id })} />
          <ConfiguredModelList models={models} providers={providers} loading={modelsQuery.isLoading || providersQuery.isLoading} testing={testMutation.isPending} testingId={testMutation.variables} onConfigure={(provider) => openProviderDialog(provider)} onAdd={openModelDialog} onEdit={editModel} onDelete={(model) => { deleteMutation.reset(); setDeleteId(model.id); }} onTest={(id) => testMutation.mutate(id)} />
        </div>
        <div className="min-w-0 xl:sticky xl:top-5">
          {templatesQuery.isError ? <Card className="mb-4 border-red-100 p-4"><p role="alert" className="text-xs text-red-700">服务商目录加载失败</p><Button variant="ghost" size="sm" className="mt-2" onClick={() => { void templatesQuery.refetch(); }}><RefreshCw size={13} />重试</Button></Card> : null}
          <ProviderCatalog templates={templatesQuery.data ?? []} providers={providers} kind={catalogKind} onKindChange={setCatalogKind} loading={templatesQuery.isLoading} onAdd={(template) => { const provider = providers.find((item) => item.key === template.key); if (provider?.enabled && provider.api_key_mask) openModelDialog(provider); else openProviderDialog(provider, true, template.key); }} />
        </div>
      </div>

      <Modal open={dialog === "provider"} onOpenChange={(open) => { if (!providerMutation.isPending) { setDialog(open ? "provider" : null); setFormError(""); } }} title="配置模型服务商" description="填写自己的服务地址与 API Key，保存后添加具体模型。">
        <div className="max-h-[68vh] space-y-5 overflow-y-auto px-6 py-5">
          <Field label="服务商"><Select value={providerForm.key} onChange={(event) => { const key = event.target.value as typeof providerForm.key; const existing = providers.find((item) => item.key === key); const template = templatesQuery.data?.find((item) => item.key === key); setProviderForm({ key, name: existing?.name ?? template?.name ?? key, baseUrl: existing?.base_url ?? template?.default_base_url ?? "", apiKey: "" }); }}><option value="tongyi">通义百炼</option><option value="openrouter">OpenRouter</option><option value="aihubmix">AIHubMix</option></Select></Field>
          <Field label="显示名称"><Input value={providerForm.name} onChange={(event) => setProviderForm((current) => ({ ...current, name: event.target.value }))} /></Field>
          {providerForm.key === "tongyi" ? <Field label="阿里云地域" hint="API Key 必须属于同一地域"><Select value={tongyiRegionUrls.some((item) => item.value === providerForm.baseUrl) ? providerForm.baseUrl : "custom"} onChange={(event) => { if (event.target.value !== "custom") setProviderForm((current) => ({ ...current, baseUrl: event.target.value })); }}>{tongyiRegionUrls.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}<option value="custom">工作空间专属 / 自定义</option></Select></Field> : null}
          <Field label="Base URL"><Input value={providerForm.baseUrl} onChange={(event) => setProviderForm((current) => ({ ...current, baseUrl: event.target.value }))} /></Field>
          <Field label="API Key" hint={selectedProvider?.api_key_mask ? `已保存 ${selectedProvider.api_key_mask}，留空表示不修改` : "将加密保存"}><div className="relative"><Input type={showKey ? "text" : "password"} value={providerForm.apiKey} autoComplete="new-password" placeholder={selectedProvider?.api_key_mask ? "留空保留已有密钥" : "输入真实 API Key"} onChange={(event) => setProviderForm((current) => ({ ...current, apiKey: event.target.value }))} className="pr-11" /><button type="button" onClick={() => setShowKey(!showKey)} aria-label={showKey ? "隐藏密钥" : "显示密钥"} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700">{showKey ? <EyeOff size={16} /> : <Eye size={16} />}</button></div></Field>
          {providerForm.key === "tongyi" ? <div className="rounded-xl border border-amber-100 bg-amber-50 p-4 text-xs leading-5 text-amber-800">建议先使用北京默认地址验证。如使用工作空间专属地址，请填写 <span className="font-mono">https://&lt;WorkspaceId&gt;.cn-beijing.maas.aliyuncs.com/compatible-mode/v1</span>。Rerank 地址由后端自动转换，无需单独配置。</div> : null}
          <div className="rounded-xl border border-indigo-100 bg-indigo-50/60 p-4"><div className="flex gap-3"><ShieldCheck className="mt-0.5 shrink-0 text-indigo-600" size={18} /><div><strong className="text-sm text-indigo-900">密钥安全说明</strong><p className="mt-1 text-xs leading-5 text-indigo-700">前端不会再次读取完整密钥；请求日志会自动过滤 Authorization 与敏感字段。</p></div></div></div>
          {formError ? <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{formError}</div> : null}
        </div>
        <div className="flex justify-end gap-2 border-t border-slate-100 px-6 py-4"><Button variant="ghost" disabled={providerMutation.isPending} onClick={() => setDialog(null)}>取消</Button><Button disabled={providerMutation.isPending || !providerForm.name.trim() || !providerForm.baseUrl.trim() || (!providerForm.apiKey.trim() && !selectedProvider?.api_key_mask)} onClick={() => providerMutation.mutate()}>{providerMutation.isPending ? <Activity size={15} className="animate-spin" /> : <CloudCog size={15} />}{providerMutation.isPending ? "正在保存…" : continueWithModel ? "保存并添加模型" : "保存配置"}</Button></div>
      </Modal>

      <Modal open={dialog === "model"} onOpenChange={(open) => { if (!modelMutation.isPending) { setDialog(open ? "model" : null); setFormError(""); } }} title={editingId ? "编辑模型" : "添加模型"} description="保存前会调用真实最小请求，校验模型类型、维度、流式能力与 Token 返回。">
        <div className="grid max-h-[68vh] gap-5 overflow-y-auto px-6 py-5 sm:grid-cols-2">
          <Field label="模型服务商"><Select disabled={Boolean(editingId)} value={modelForm.providerId} onChange={(event) => setModelForm((current) => ({ ...current, providerId: event.target.value }))}><option value="">请选择</option>{providers.filter((provider) => (provider.enabled && provider.api_key_mask) || provider.id === modelForm.providerId).map((provider) => <option key={provider.id} value={provider.id}>{provider.name}</option>)}</Select></Field>
          <Field label="模型类型"><Select disabled={Boolean(editingId)} value={modelForm.kind} onChange={(event) => setModelForm((current) => ({ ...current, kind: event.target.value as typeof current.kind }))}><option value="llm">LLM</option><option value="embedding">Embedding</option><option value="rerank">Rerank</option></Select></Field>
          <Field label="模型 ID" hint={selectedModelProvider?.key === "tongyi" ? `推荐：${tongyiModelHint.id}` : undefined}><Input value={modelForm.modelId} placeholder={selectedModelProvider?.key === "tongyi" ? tongyiModelHint.id : "输入供应商模型 ID"} onChange={(event) => setModelForm((current) => ({ ...current, modelId: event.target.value }))} /></Field>
          <Field label="显示名称" hint="不同模型类型可同名"><Input value={modelForm.name} placeholder={selectedModelProvider?.key === "tongyi" ? tongyiModelHint.name : "输入显示名称"} onChange={(event) => setModelForm((current) => ({ ...current, name: event.target.value }))} /></Field>
          <Field label="最大上下文"><Input type="number" value={modelForm.context} placeholder="例如 131072" onChange={(event) => setModelForm((current) => ({ ...current, context: event.target.value }))} /></Field>
          <Field label="向量维度" hint="可选，留空自动探测"><Input type="number" value={modelForm.dimension} disabled={modelForm.kind !== "embedding"} placeholder="例如 1024" onChange={(event) => setModelForm((current) => ({ ...current, dimension: event.target.value }))} /></Field>
          <div className="sm:col-span-2 rounded-xl bg-slate-50 p-4 text-xs leading-5 text-slate-500"><CircleHelp size={15} className="mr-2 inline text-slate-400" />{selectedModelProvider?.key === "tongyi" ? "百炼 LLM 与 Embedding 使用 OpenAI 兼容接口，Rerank 使用 DashScope 原生接口，后端会自动适配。" : "Embedding 模型启用后，系统会按实测维度创建独立索引；被知识库使用后不能直接修改维度。"}</div>
          {formError ? <div className="sm:col-span-2 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{formError}</div> : null}
        </div>
        <div className="flex justify-end gap-2 border-t border-slate-100 px-6 py-4"><Button variant="ghost" disabled={modelMutation.isPending} onClick={() => setDialog(null)}>取消</Button><Button disabled={modelMutation.isPending || !modelForm.providerId || !modelForm.modelId.trim() || !modelForm.name.trim()} onClick={() => modelMutation.mutate()}>{modelMutation.isPending ? <Activity size={15} className="animate-spin" /> : <Cpu size={15} />}{modelMutation.isPending ? "正在真实测试…" : editingId ? "保存并测试" : "测试并添加"}</Button></div>
      </Modal>
      <Modal open={Boolean(deleteId)} onOpenChange={(open) => { if (!open) setDeleteId(null); }} title="删除模型配置" description="被知识库或助手使用的模型无法删除。">
        <div className="px-6 py-5 text-sm text-slate-600">删除后可重新创建配置。建议先解除关联，或保留当前配置并编辑修正。
          {deleteMutation.error ? <p className="mt-3 text-red-700">{deleteMutation.error instanceof ApiError ? deleteMutation.error.message : "删除失败"}</p> : null}
        </div><div className="flex justify-end gap-2 border-t px-6 py-4"><Button variant="secondary" onClick={() => setDeleteId(null)}>取消</Button><Button disabled={deleteMutation.isPending} onClick={() => { if (deleteId) deleteMutation.mutate(deleteId); }}>删除配置</Button></div>
      </Modal>
    </div>
  );
}
