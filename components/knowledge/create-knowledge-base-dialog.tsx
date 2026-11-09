"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, Blocks, FileSpreadsheet, FileText, Globe, MessagesSquare, RefreshCw } from "lucide-react";
import { useState } from "react";
import { Button, Input, Modal, Select, Textarea } from "@/components/ui/primitives";
import { ApiError, backendApi, type KnowledgeBaseRead } from "@/lib/api-client";
import type { Role } from "@/lib/types";
import { cn } from "@/lib/utils";

const knowledgeTypes = [
  { id: "general", name: "通用知识库", description: "上传文件，按切块策略构建索引", icon: FileText, available: true },
  { id: "qa", name: "问答对知识库", description: "以问题-答案为单位，适合 FAQ 和客服", icon: MessagesSquare, available: false },
  { id: "table", name: "表格知识库", description: "Excel / CSV 分块索引，保留表头语义", icon: FileSpreadsheet, available: true },
  { id: "website", name: "网站同步", description: "输入站点地址，定时抓取并增量更新", icon: Globe, available: false },
  { id: "feishu", name: "飞书知识库", description: "绑定飞书知识空间，自动同步文档变更", icon: Blocks, available: false },
] as const;

export function CreateKnowledgeBaseDialog({ role, onClose, onCreated }: {
  role: Role; onClose: () => void; onCreated: (record: KnowledgeBaseRead) => void;
}) {
  const queryClient = useQueryClient();
  const [type, setType] = useState<"general" | "table">("general");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [modelId, setModelId] = useState<string>();
  const [error, setError] = useState("");
  const modelsQuery = useQuery({
    queryKey: ["embedding-model-options", role],
    queryFn: () => backendApi.listEmbeddingModelOptions(role),
  });
  const models = modelsQuery.data ?? [];
  const selectedModelId = modelId ?? models.find((model) => model.is_default)?.id ?? "";
  const selectedModel = models.find((model) => model.id === selectedModelId);
  const createMutation = useMutation({
    mutationFn: () => backendApi.createKnowledgeBase(role, {
      name: name.trim(), description: description.trim() || undefined,
      embedding_model_config_id: selectedModelId, knowledge_base_type: type,
    }),
    onSuccess: async (created) => {
      await queryClient.invalidateQueries({ queryKey: ["knowledge-bases"] });
      onCreated(created);
    },
    onError: (cause) => setError(cause instanceof ApiError ? cause.message : "创建知识库失败，请重试。"),
  });
  const busy = createMutation.isPending;
  const canCreate = Boolean(name.trim() && selectedModel && !modelsQuery.isError && !modelsQuery.isFetching && !busy);

  return <Modal open onOpenChange={(open) => { if (!open && !busy) onClose(); }} title="新建知识库" description="选择知识库类型，填写基本信息后导入数据。" className="max-w-5xl [&>div:first-child]:border-b-0">
    <form className="flex min-h-0 flex-1 flex-col" onSubmit={(event) => { event.preventDefault(); if (canCreate) { setError(""); createMutation.mutate(); } }}>
      <div className="min-h-0 flex-1 space-y-6 overflow-y-auto px-6 pb-7 pt-2 sm:px-7">
        <fieldset disabled={busy}>
          <legend className="mb-3 text-sm font-semibold text-slate-900">知识库类型 <span className="ml-1 text-red-500">*</span></legend>
          <div className="grid gap-3 sm:grid-cols-2">
            {knowledgeTypes.map((item) => <label key={item.id} className={cn("relative", item.available ? "cursor-pointer" : "cursor-not-allowed")} title={item.available ? item.description : "该类型尚未接入，暂不可创建。"}>
              <input type="radio" name="knowledge-base-type" value={item.id} aria-label={item.name} checked={type === item.id} disabled={!item.available} onChange={() => { if (item.id === "general" || item.id === "table") setType(item.id); }} className="peer sr-only" />
              <span className="flex h-full min-h-24 gap-3 rounded-xl border-2 border-slate-200/90 bg-white px-4 py-4 transition peer-checked:border-blue-500 peer-checked:bg-blue-50/80 peer-focus-visible:ring-2 peer-focus-visible:ring-blue-300 peer-focus-visible:ring-offset-2 peer-enabled:peer-hover:border-blue-300 sm:gap-4 sm:px-5">
                <item.icon size={25} strokeWidth={1.8} className="mt-0.5 shrink-0 text-blue-500" aria-hidden="true" />
                <span className="min-w-0 flex-1"><span className="flex flex-wrap items-center gap-2"><strong className="text-base font-semibold text-slate-900">{item.name}</strong>{!item.available ? <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-500">待接入</span> : null}</span><span className="mt-1.5 block text-sm leading-6 text-slate-500">{item.description}</span></span>
              </span>
            </label>)}
          </div>
        </fieldset>

        <label className="block"><span className="mb-2 block text-sm font-semibold text-slate-900">名称 <span className="ml-1 text-red-500">*</span></span><Input autoComplete="off" required maxLength={160} disabled={busy} placeholder="例如：华东区域销售政策" value={name} onChange={(event) => setName(event.target.value)} className="h-11 rounded-xl" /></label>
        <label className="block"><span className="mb-2 flex flex-wrap items-center justify-between gap-1"><span className="text-sm font-semibold text-slate-900">简介</span><span className="text-xs text-slate-400">帮助团队了解本库的内容与用途</span></span><Textarea rows={3} disabled={busy} placeholder="说明知识库包含哪些内容、适合回答什么问题" value={description} onChange={(event) => setDescription(event.target.value)} className="resize-y rounded-xl py-3" /></label>

        <div className="grid gap-5 sm:grid-cols-2">
          <label className="block"><span className="mb-2 flex flex-wrap items-center justify-between gap-1"><span className="text-sm font-semibold text-slate-900">索引模型 <span className="ml-1 text-red-500">*</span></span><span className="text-xs text-slate-400">Embedding</span></span><Select required disabled={busy || modelsQuery.isFetching} value={selectedModelId} onChange={(event) => setModelId(event.target.value)} className="h-11 rounded-xl"><option value="">{modelsQuery.isLoading ? "正在加载模型…" : "请选择已验证的模型"}</option>{models.map((model) => <option key={model.id} value={model.id}>{model.name} · {model.embedding_dimension} 维 · {model.provider_name}{model.is_default ? "（默认）" : ""}</option>)}</Select></label>
          <div><span className="mb-2 block text-sm font-semibold text-slate-900">分块方式</span><div className="flex h-11 items-center rounded-xl border border-slate-200 bg-slate-50 px-3 text-sm text-slate-600">{type === "table" ? "按表格结构切分，保留表头" : "按段落与长度切分"}</div></div>
        </div>
        <p className="text-xs leading-5 text-slate-400">{selectedModel ? `当前索引维度 ${selectedModel.embedding_dimension}；` : ""}索引模型在创建后锁定。分块长度和重叠范围可在导入时调整。</p>
        {modelsQuery.isError ? <div role="alert" className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-red-50 p-4 text-xs text-red-700"><span>{modelsQuery.error instanceof ApiError ? modelsQuery.error.message : "模型列表加载失败，请重试。"}</span><Button type="button" size="sm" variant="ghost" onClick={() => { void modelsQuery.refetch(); }}><RefreshCw size={13} />重试</Button></div> : !modelsQuery.isLoading && !models.length ? <p className="rounded-xl bg-amber-50 p-4 text-xs leading-5 text-amber-800">暂无可用索引模型，请先在“模型服务”中添加并验证 Embedding 模型。</p> : null}
        {error ? <p role="alert" className="rounded-xl bg-red-50 p-4 text-sm text-red-700">{error}</p> : null}
      </div>
      <div className="flex shrink-0 justify-end gap-3 border-t border-slate-100 bg-white px-6 py-4 sm:px-7">
        <Button type="button" variant="secondary" disabled={busy} onClick={onClose} className="h-11 rounded-xl px-5">取消</Button>
        <Button type="submit" disabled={!canCreate} className="h-11 rounded-xl bg-blue-500 px-5 hover:bg-blue-600 disabled:bg-blue-300">{busy ? <Activity size={16} className="animate-spin" /> : null}{busy ? "正在创建…" : "创建并导入数据"}</Button>
      </div>
    </form>
  </Modal>;
}
