"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity, Bot, CheckCircle2, ChevronRight, CircleDashed, Database,
  MessageSquareText, Plus, RefreshCw, ShieldCheck, Sparkles, Trash2,
} from "lucide-react";
import { useState } from "react";
import { Badge, Button, Card, Field, Input, Modal, Select, Textarea, Toggle } from "@/components/ui/primitives";
import { ApiError, backendApi, type AssistantRead } from "@/lib/api-client";
import type { Role } from "@/lib/types";

const assistantTones = [
  { line: "bg-indigo-500", avatar: "bg-indigo-50 text-indigo-700" },
  { line: "bg-cyan-500", avatar: "bg-cyan-50 text-cyan-700" },
  { line: "bg-amber-400", avatar: "bg-amber-50 text-amber-700" },
];

const defaultPrompt = "你是企业内部知识助手。仅根据提供的知识库资料回答；用清晰、简洁的中文说明结论，并在相关句末保留引用编号。若资料不足，请明确说明未找到足够依据。";

type FormState = {
  name: string;
  alias: string;
  description: string;
  llmModelId: string;
  rerankModelId: string;
  knowledgeBaseIds: string[];
  systemPrompt: string;
  queryRewrite: boolean;
  publishNow: boolean;
};

const initialForm: FormState = {
  name: "",
  alias: "",
  description: "",
  llmModelId: "",
  rerankModelId: "",
  knowledgeBaseIds: [],
  systemPrompt: defaultPrompt,
  queryRewrite: true,
  publishNow: true,
};

function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : "操作失败，请检查后端服务后重试。";
}

export function AssistantsView({ role, onOpenChat, notify }: { role: Role; onOpenChat: (assistantId: string) => void; notify: (title: string, description?: string) => void }) {
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState<FormState>(initialForm);
  const [formError, setFormError] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<AssistantRead | null>(null);
  const [deleteError, setDeleteError] = useState("");
  const canManage = role !== "user";

  const assistantsQuery = useQuery({
    queryKey: ["assistants", role],
    queryFn: () => backendApi.listAssistants(role),
  });
  const modelsQuery = useQuery({
    queryKey: ["assistant-model-options", role],
    queryFn: () => backendApi.listAssistantModelOptions(role),
    enabled: canManage,
  });
  const knowledgeQuery = useQuery({
    queryKey: ["knowledge-bases", role],
    queryFn: () => backendApi.listKnowledgeBases(role),
    enabled: canManage,
  });
  const createMutation = useMutation({
    mutationFn: () => backendApi.createAssistant(role, {
      name: form.name.trim(),
      alias: form.alias.trim(),
      description: form.description.trim() || undefined,
      status: form.publishNow ? "active" : "draft",
      llm_model_config_id: form.llmModelId,
      rerank_model_config_id: form.rerankModelId || undefined,
      system_prompt: form.systemPrompt.trim(),
      insufficient_evidence_message: "当前知识库未找到足够依据",
      enable_query_rewrite: form.queryRewrite,
      semantic_top_k: 30,
      keyword_top_k: 30,
      rerank_top_k: 20,
      answer_top_k: 6,
      max_context_tokens: 6_000,
      relevance_threshold: 0.5,
      temperature: 0.2,
      max_output_tokens: 2_048,
      knowledge_bases: form.knowledgeBaseIds.map((knowledgeBaseId, index) => ({
        knowledge_base_id: knowledgeBaseId,
        priority: index,
        enabled: true,
      })),
    }),
    onSuccess: async (created) => {
      await queryClient.invalidateQueries({ queryKey: ["assistants"] });
      setCreateOpen(false);
      setForm(initialForm);
      setFormError("");
      notify(created.status === "active" ? "助手已创建并发布" : "助手草稿已创建", created.status === "active" ? "现在可以开始真实对话。" : "构建完知识库后可再发布。");
    },
    onError: (error) => setFormError(errorMessage(error)),
  });
  const publishMutation = useMutation({
    mutationFn: (assistantId: string) => backendApi.updateAssistant(role, assistantId, { status: "active" }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["assistants"] });
      notify("助手已发布", "使用者现在可以看到并开始对话。");
    },
    onError: (error) => notify("发布失败", errorMessage(error)),
  });

  const deleteMutation = useMutation({
    mutationFn: (assistantId: string) => backendApi.deleteAssistant(role, assistantId),
    onSuccess: async () => {
      setDeleteTarget(null);
      setDeleteError("");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["assistants"] }),
        queryClient.invalidateQueries({ queryKey: ["api-keys"] }),
        queryClient.invalidateQueries({ queryKey: ["knowledge-bases"] }),
      ]);
      notify("助手已删除", "知识库、文件和历史对话、日志已保留。");
    },
    onError: (error) => setDeleteError(errorMessage(error)),
  });

  const assistants = assistantsQuery.data ?? [];
  const modelOptions = modelsQuery.data ?? [];
  const llmOptions = modelOptions.filter((model) => model.kind === "llm");
  const rerankOptions = modelOptions.filter((model) => model.kind === "rerank");
  const knowledgeBases = knowledgeQuery.data ?? [];

  function openCreateAssistant() {
    setForm({ ...initialForm, llmModelId: llmOptions.find((model) => model.is_default)?.id ?? "", rerankModelId: rerankOptions.find((model) => model.is_default)?.id ?? "" });
    setFormError("");
    setCreateOpen(true);
  }

  function toggleKnowledgeBase(id: string) {
    setForm((current) => ({
      ...current,
      knowledgeBaseIds: current.knowledgeBaseIds.includes(id)
        ? current.knowledgeBaseIds.filter((item) => item !== id)
        : [...current.knowledgeBaseIds, id],
    }));
  }

  return (
    <div className="space-y-6 fade-in">
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
        <div><h2 className="text-xl font-semibold text-slate-900">知识库助手</h2><p className="mt-1 text-sm text-slate-500">选择一个助手开始对话，或将知识库、模型与回答规则组合成新助手。</p></div>
        {canManage ? <Button disabled={modelsQuery.isFetching} onClick={openCreateAssistant}><Plus size={16} />创建助手</Button> : null}
      </div>

      {role === "user" ? <div className="flex items-center gap-3 rounded-xl border border-indigo-100 bg-indigo-50/70 px-4 py-3 text-sm text-indigo-800"><Sparkles size={18} className="text-indigo-600" /><span><strong>选择最适合的助手。</strong> 回答会严格引用已审核的企业资料。</span></div> : null}
      {assistantsQuery.isError ? <Card className="flex items-center justify-between border-red-100 p-5"><div><strong className="text-sm text-red-800">助手列表加载失败</strong><p className="mt-1 text-xs text-red-600">{errorMessage(assistantsQuery.error)}</p></div><Button variant="secondary" size="sm" onClick={() => { void assistantsQuery.refetch(); }}><RefreshCw size={14} />重试</Button></Card> : null}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {assistantsQuery.isLoading ? [1, 2, 3].map((item) => <Card key={item} className="h-72 animate-pulse bg-slate-50"><span className="sr-only">正在加载助手</span></Card>) : null}
        {assistants.map((assistant, index) => {
          const tone = assistantTones[index % assistantTones.length];
          const active = assistant.status === "active";
          return <Card key={assistant.id} className="group overflow-hidden transition hover:-translate-y-0.5 hover:border-indigo-200 hover:shadow-lg"><div className={`h-1 ${tone.line}`} /><div className="p-5"><div className="flex items-start gap-3"><span className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-sm font-semibold ${tone.avatar}`}>{assistant.name.slice(0, 1)}</span><div className="min-w-0 flex-1"><div className="flex items-center gap-2"><h3 className="truncate font-semibold text-slate-900">{assistant.name}</h3><Badge tone={active ? "green" : "slate"}>{active ? "已发布" : "草稿"}</Badge></div><p className="mt-1 line-clamp-2 min-h-10 text-xs leading-5 text-slate-500">{assistant.description ?? "暂无助手说明"}</p></div>{canManage ? <Button variant="ghost" size="icon" className="shrink-0 text-red-600 hover:bg-red-50 hover:text-red-700" aria-label={`删除助手 ${assistant.name}`} title="删除助手" onClick={() => { setDeleteError(""); setDeleteTarget(assistant); }}><Trash2 size={16} /></Button> : null}</div><div className="mt-5 space-y-2.5 rounded-xl bg-slate-50 p-3"><div className="flex items-center gap-2 text-xs text-slate-600"><Database size={14} className="text-slate-400" /><span className="truncate">{assistant.knowledge_bases.map((item) => item.knowledge_base_name).join(" · ")}</span></div><div className="flex items-center gap-2 text-xs text-slate-600"><Bot size={14} className="text-slate-400" /><span>{assistant.llm_model_name}{assistant.rerank_model_name ? ` · ${assistant.rerank_model_name}` : ""}</span></div><div className="flex items-center gap-2 text-xs text-slate-600"><ShieldCheck size={14} className="text-slate-400" /><span>严格知识库回答 · 显示引用</span></div></div><div className="mt-5 flex items-center justify-between gap-2"><span className="truncate text-[11px] text-slate-400">{assistant.alias} · {new Date(assistant.updated_at).toLocaleDateString("zh-CN")}</span>{active ? <Button size="sm" onClick={() => onOpenChat(assistant.id)}><MessageSquareText size={14} />开始对话</Button> : canManage ? <Button size="sm" variant="secondary" disabled={publishMutation.isPending} onClick={() => publishMutation.mutate(assistant.id)}>{publishMutation.isPending && publishMutation.variables === assistant.id ? <Activity size={14} className="animate-spin" /> : <CircleDashed size={14} />}发布</Button> : null}</div></div></Card>;
        })}
        {!assistantsQuery.isLoading && !assistantsQuery.isError && assistants.length === 0 ? <Card className="col-span-full p-10 text-center"><Bot className="mx-auto text-slate-300" size={30} /><strong className="mt-4 block text-sm text-slate-800">还没有可用助手</strong><p className="mt-1 text-xs text-slate-500">{canManage ? "先完成模型验证和知识库构建，再创建第一个助手。" : "请联系知识库管理人员发布助手。"}</p></Card> : null}
      </div>

      <Card className="overflow-hidden border-indigo-100 bg-gradient-to-r from-indigo-50 to-white p-6"><div className="flex flex-col items-start justify-between gap-5 md:flex-row md:items-center"><div className="flex gap-4"><span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-white text-indigo-600 shadow-sm"><Bot size={21} /></span><div><h3 className="font-semibold text-slate-900">助手如何保证回答可信？</h3><p className="mt-1 max-w-2xl text-sm leading-6 text-slate-600">每次回答先检索已绑定知识库，再对候选证据重排。没有足够证据时明确拒答，不让模型凭常识补齐。</p></div></div><Button variant="secondary" onClick={() => notify("回答策略", "默认候选 20 条、引用 6 条、上下文上限 6000 Tokens。") }>查看检索规则<ChevronRight size={14} /></Button></div></Card>

      <Modal open={deleteTarget !== null} onOpenChange={(open) => { if (!open && !deleteMutation.isPending) { setDeleteTarget(null); setDeleteError(""); } }} title="删除知识库助手" description="请确认要删除的助手。" className="max-w-lg">
        <div className="space-y-4 px-6 py-5">
          <p className="text-sm text-slate-700">确定删除「<strong>{deleteTarget?.name}</strong>」吗？</p>
          <p className="rounded-xl bg-amber-50 p-4 text-sm leading-6 text-amber-900">删除后，该助手将从列表移除，无法再发起新对话或 API 调用。知识库、文件和历史对话、运行日志会保留。</p>
          {deleteError ? <p role="alert" className="text-sm text-red-700">{deleteError}</p> : null}
        </div>
        <div className="flex justify-end gap-2 border-t border-slate-100 px-6 py-4">
          <Button variant="ghost" disabled={deleteMutation.isPending} onClick={() => { setDeleteTarget(null); setDeleteError(""); }}>取消</Button>
          <Button variant="danger" disabled={deleteMutation.isPending || !deleteTarget} onClick={() => { if (deleteTarget) deleteMutation.mutate(deleteTarget.id); }}>
            {deleteMutation.isPending ? <Activity size={15} className="animate-spin" /> : <Trash2 size={15} />}{deleteMutation.isPending ? "正在删除…" : "确认删除"}
          </Button>
        </div>
      </Modal>

      <Modal open={createOpen} onOpenChange={setCreateOpen} title="创建知识库助手" description="把知识库、模型与回答规则组合成一个稳定的问答入口。" className="max-w-3xl">
        <div className="grid max-h-[68vh] gap-5 overflow-y-auto px-6 py-5 md:grid-cols-2">
          <Field label="助手名称"><Input value={form.name} onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} /></Field>
          <Field label="调用别名" hint="英文、数字或 - _ ."><Input value={form.alias} placeholder="policy-assistant" onChange={(event) => setForm((current) => ({ ...current, alias: event.target.value }))} /></Field>
          <Field label="对话模型"><Select value={form.llmModelId} onChange={(event) => setForm((current) => ({ ...current, llmModelId: event.target.value }))}><option value="">请选择已验证 LLM</option>{llmOptions.map((model) => <option key={model.id} value={model.id}>{model.name} · {model.provider_name}{model.is_default ? "（默认）" : ""}</option>)}</Select></Field>
          <Field label="重排模型" hint="可选"><Select value={form.rerankModelId} onChange={(event) => setForm((current) => ({ ...current, rerankModelId: event.target.value }))}><option value="">不使用重排</option>{rerankOptions.map((model) => <option key={model.id} value={model.id}>{model.name} · {model.provider_name}{model.is_default ? "（默认）" : ""}</option>)}</Select></Field>
          <div className="md:col-span-2"><Field label="助手说明"><Input value={form.description} onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))} /></Field></div>
          <div className="md:col-span-2"><span className="mb-2 block text-sm font-medium text-slate-700">绑定知识库</span><div className="grid gap-2 sm:grid-cols-2">{knowledgeBases.map((knowledgeBase) => { const checked = form.knowledgeBaseIds.includes(knowledgeBase.id); return <button type="button" key={knowledgeBase.id} onClick={() => toggleKnowledgeBase(knowledgeBase.id)} className={`flex items-center justify-between rounded-xl border px-4 py-3 text-left transition ${checked ? "border-indigo-300 bg-indigo-50" : "border-slate-200 hover:border-indigo-200"}`}><span><strong className="block text-sm text-slate-800">{knowledgeBase.name}</strong><small className="text-xs text-slate-400">{knowledgeBase.chunk_count.toLocaleString("zh-CN")} 分块 · {knowledgeBase.status === "ready" ? "可用" : "未完成"}</small></span><span className={`h-4 w-4 rounded-full border ${checked ? "border-indigo-600 bg-indigo-600 ring-2 ring-indigo-100" : "border-slate-300"}`} /></button>; })}</div>{knowledgeBases.length === 0 ? <p className="rounded-xl bg-amber-50 p-4 text-xs text-amber-800">暂无知识库，请先建库并完成资料构建。</p> : null}</div>
          <div className="md:col-span-2"><Field label="系统提示词" hint="引用规则"><Textarea rows={5} value={form.systemPrompt} onChange={(event) => setForm((current) => ({ ...current, systemPrompt: event.target.value }))} /></Field></div>
          <div className="md:col-span-2 space-y-3"><div className="flex items-center justify-between rounded-xl border border-slate-200 bg-slate-50 p-4"><div><strong className="text-sm text-slate-800">多轮问题改写</strong><p className="mt-1 text-xs text-slate-500">有历史消息时，先把追问改写成可独立检索的问题。</p></div><Toggle checked={form.queryRewrite} onChange={(value) => setForm((current) => ({ ...current, queryRewrite: value }))} label="多轮问题改写" /></div><div className="flex items-center justify-between rounded-xl border border-slate-200 bg-slate-50 p-4"><div><strong className="text-sm text-slate-800">创建后立即发布</strong><p className="mt-1 text-xs text-slate-500">只有绑定知识库全部可用时才能发布。</p></div><Toggle checked={form.publishNow} onChange={(value) => setForm((current) => ({ ...current, publishNow: value }))} label="创建后立即发布" /></div></div>
          <div className="md:col-span-2 rounded-xl border border-indigo-100 bg-indigo-50 p-4 text-xs leading-5 text-indigo-800"><ShieldCheck size={15} className="mr-2 inline" />严格知识库回答是 1.0 的固定安全策略；证据不足时不会调用模型常识补齐。</div>
          {formError ? <div className="md:col-span-2 rounded-xl bg-red-50 p-4 text-xs text-red-700">{formError}</div> : null}
        </div>
        <div className="flex justify-end gap-2 border-t border-slate-100 px-6 py-4"><Button variant="ghost" onClick={() => setCreateOpen(false)}>取消</Button><Button disabled={createMutation.isPending || !form.name.trim() || !form.alias.trim() || !form.llmModelId || form.knowledgeBaseIds.length === 0} onClick={() => createMutation.mutate()}>{createMutation.isPending ? <Activity size={15} className="animate-spin" /> : <CheckCircle2 size={15} />}{createMutation.isPending ? "正在创建…" : "创建助手"}</Button></div>
      </Modal>
    </div>
  );
}
