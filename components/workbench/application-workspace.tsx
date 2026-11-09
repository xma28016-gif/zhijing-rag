"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Bot, Check, Copy, Save, Sparkles, Star } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge, Button, Card, Field, Input, Select, Textarea } from "@/components/ui/primitives";
import { ApplicationIcon } from "@/components/workbench/application-icon";
import { ApiError, backendApi } from "@/lib/api-client";
import { applicationCategories, workbenchHomeHref, type BusinessApplication } from "@/lib/workbench-apps";
import { emptyApplicationDraft, readApplicationDraft, saveApplicationDraft, type ApplicationDraft } from "@/lib/workbench-store";
import type { Role, ViewKey } from "@/lib/types";

export function ApplicationWorkspace({ app, role, favorite, onFavorite, onNavigate, onOpenChat, notify }: {
  app: BusinessApplication; role: Role; favorite: boolean; onFavorite: () => void;
  onNavigate: (view: ViewKey) => void; onOpenChat: (assistantId: string, prompt: string) => void;
  notify: (title: string, description?: string) => void;
}) {
  const [draft, setDraft] = useState<ApplicationDraft>({ ...emptyApplicationDraft });
  const [loaded, setLoaded] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState("");
  const category = applicationCategories.find((item) => item.id === app.category)!;
  const assistantsQuery = useQuery({ queryKey: ["assistants", role], queryFn: () => backendApi.listAssistants(role) });
  const assistants = (assistantsQuery.data ?? []).filter((assistant) => assistant.status === "active");
  const selectedAssistant = assistants.find((assistant) => assistant.id === draft.assistantId);
  const hasContent = Boolean(draft.task.trim() || draft.reference.trim() || draft.requirements.trim());

  useEffect(() => {
    try { setDraft(readApplicationDraft(window.localStorage, app.id)); }
    catch { setError("当前浏览器无法读取草稿，你仍可填写任务或复制内容。"); }
    setLoaded(true);
  }, [app.id]);

  function update(field: keyof ApplicationDraft, value: string) {
    setDraft((current) => ({ ...current, [field]: value }));
    setDirty(true);
  }

  function taskPrompt() {
    return [`任务类型：${app.name}`, draft.task.trim() ? `任务：${draft.task.trim()}` : "", draft.reference.trim() ? `${app.referenceLabel}：\n${draft.reference.trim()}` : "", draft.requirements.trim() ? `输出要求：\n${draft.requirements.trim()}` : ""].filter(Boolean).join("\n\n");
  }

  function saveDraft() {
    if (!loaded || !hasContent) return;
    try {
      const next = { ...draft, updatedAt: new Date().toISOString() };
      saveApplicationDraft(window.localStorage, app.id, next);
      setDraft(next);
      setDirty(false);
      setError("");
      notify("草稿已保存", "保存在当前浏览器，下次进入此应用可继续填写。");
    } catch { setError("草稿保存失败，浏览器存储可能不可用或空间不足。请先复制任务内容。"); }
  }

  async function copyTask() {
    try { await navigator.clipboard.writeText(taskPrompt()); notify("任务内容已复制"); }
    catch { setError("浏览器未允许复制，请手动选中并复制任务内容。"); }
  }

  function continueInChat() {
    if (!selectedAssistant || !hasContent) return;
    const prompt = taskPrompt();
    if (prompt.length > 8000) {
      setError("当前在线对话最多支持 8000 字符，请精简资料后带入；较长内容可先保存草稿或导入知识库。");
      return;
    }
    onOpenChat(selectedAssistant.id, prompt);
  }

  return <div className="space-y-6 fade-in">
    <a href={workbenchHomeHref} className="inline-flex items-center gap-2 rounded text-sm text-slate-500 hover:text-indigo-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"><ArrowLeft size={16} />返回工作台</a>
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div className="flex items-start gap-4"><ApplicationIcon app={app} /><div><div className="flex flex-wrap items-center gap-2"><h2 className="text-xl font-semibold text-slate-900">{app.name}</h2><Badge>{category.name}</Badge></div><p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">{app.description}</p></div></div>
      <Button variant={favorite ? "secondary" : "ghost"} size="sm" aria-pressed={favorite} onClick={onFavorite}><Star size={15} className={favorite ? "fill-amber-400 text-amber-500" : ""} />{favorite ? "已收藏" : "收藏应用"}</Button>
    </div>
    <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_300px]">
      <Card className="overflow-hidden">
        <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-4 sm:px-6"><div><h3 className="font-semibold text-slate-800">准备工作任务</h3><p className="mt-1 text-xs leading-5 text-slate-500">先整理任务与资料，再保存草稿或交给知识库助手继续处理。</p></div><Badge tone={dirty ? "amber" : draft.updatedAt ? "green" : "slate"}>{dirty ? "尚未保存" : draft.updatedAt ? "草稿已保存" : "基础工作页"}</Badge></div>
        <form onSubmit={(event) => { event.preventDefault(); saveDraft(); }} className="space-y-5 p-5 sm:p-6">
          <Field label="任务主题"><Input disabled={!loaded} maxLength={300} value={draft.task} onChange={(event) => update("task", event.target.value)} placeholder={app.taskPlaceholder} /></Field>
          <div><span className="mb-2 block text-xs text-slate-400">也可以从常见任务开始</span><div className="flex flex-wrap gap-2">{app.examples.map((example) => <button type="button" key={example} disabled={!loaded} onClick={() => update("task", example)} className="rounded-lg border border-slate-200 px-3 py-2 text-left text-xs text-slate-600 transition hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500">{example}</button>)}</div></div>
          <Field label={app.referenceLabel}><Textarea disabled={!loaded} rows={7} maxLength={60000} value={draft.reference} onChange={(event) => update("reference", event.target.value)} placeholder={app.referencePlaceholder} /></Field>
          <Field label="输出要求"><Textarea disabled={!loaded} rows={3} maxLength={10000} value={draft.requirements} onChange={(event) => update("requirements", event.target.value)} placeholder={app.requirementsPlaceholder} /></Field>
          {error ? <p role="alert" className="rounded-lg bg-red-50 px-4 py-3 text-xs leading-5 text-red-700">{error}</p> : null}
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-5"><p className="text-[11px] leading-5 text-slate-400">草稿仅保存在当前浏览器，填写内容不会自动发送给模型。</p><div className="flex gap-2"><Button type="button" variant="secondary" disabled={!loaded || !hasContent} onClick={() => { void copyTask(); }}><Copy size={14} />复制任务</Button><Button type="submit" disabled={!loaded || !hasContent}><Save size={14} />保存草稿</Button></div></div>
        </form>
      </Card>
      <div className="space-y-4">
        <Card className="p-5"><div className="flex items-center gap-2"><Bot size={18} className="text-indigo-500" /><h3 className="text-sm font-semibold text-slate-800">交给知识库助手</h3></div><p className="mt-3 text-xs leading-6 text-slate-500">选择已发布的助手，将本页任务带入在线对话。发送后，助手会依据绑定的知识库回答。</p>
          {assistantsQuery.isError ? <div className="mt-4"><p role="alert" className="text-xs text-red-700">{assistantsQuery.error instanceof ApiError ? assistantsQuery.error.message : "助手列表加载失败。"}</p><Button variant="ghost" size="sm" onClick={() => { void assistantsQuery.refetch(); }}>重新加载</Button></div> : assistantsQuery.isLoading ? <p role="status" className="mt-4 text-xs text-slate-400">正在读取可用助手…</p> : assistants.length === 0 ? <div className="mt-4 rounded-xl bg-slate-50 p-4"><p className="text-xs leading-6 text-slate-500">暂无已发布助手。可以先保存任务草稿，待助手发布后继续处理。</p><Button variant="ghost" size="sm" className="mt-2 px-0" onClick={() => onNavigate("assistants")}>查看助手<ArrowRight size={14} /></Button></div> : <div className="mt-4 space-y-3"><Field label="选择助手"><Select value={selectedAssistant?.id ?? ""} onChange={(event) => update("assistantId", event.target.value)}><option value="">请选择已发布助手</option>{assistants.map((assistant) => <option key={assistant.id} value={assistant.id}>{assistant.name}</option>)}</Select></Field><Button className="w-full" disabled={!selectedAssistant || !hasContent} onClick={continueInChat}><Sparkles size={14} />带入在线对话<ArrowRight size={14} /></Button></div>}
        </Card>
        <Card className="p-5"><h3 className="text-sm font-semibold text-slate-800">使用步骤</h3><ol className="mt-4 space-y-4">{app.steps.map((step, index) => <li key={step} className="flex items-start gap-3 text-xs leading-6 text-slate-500"><span className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-medium ${category.soft} ${category.color}`}>{index + 1}</span>{step}</li>)}</ol></Card>
        <div className="flex gap-2 px-1 text-[11px] leading-5 text-slate-400"><Check size={14} className="mt-0.5 shrink-0" /><p>当前提供任务整理、草稿与助手入口，后续会逐步完善此应用的专属处理流程。</p></div>
      </div>
    </div>
  </div>;
}
