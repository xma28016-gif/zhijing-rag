"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, Check, Copy, KeyRound, Plus, RefreshCw, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Badge, Button, Card, Field, Input, Modal, Select, Toggle } from "@/components/ui/primitives";
import { ApiError, backendApi, type ApiKeyCreated } from "@/lib/api-client";
import type { Role } from "@/lib/types";

type KeyForm = {
  name: string;
  allowAll: boolean;
  assistantIds: string[];
  rate: string;
  expiresIn: string;
};

const initialForm: KeyForm = {
  name: "",
  allowAll: false,
  assistantIds: [],
  rate: "60",
  expiresIn: "90",
};

function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : "API Key 操作失败，请稍后重试。";
}

export function ApiKeysView({ role, notify }: { role: Role; notify: (title: string, description?: string) => void }) {
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [createdKey, setCreatedKey] = useState<ApiKeyCreated | null>(null);
  const [form, setForm] = useState<KeyForm>(initialForm);
  const [formError, setFormError] = useState("");

  const keysQuery = useQuery({
    queryKey: ["api-keys", role],
    queryFn: () => backendApi.listApiKeys(role),
  });
  const assistantsQuery = useQuery({
    queryKey: ["assistants", role],
    queryFn: () => backendApi.listAssistants(role),
  });
  const createMutation = useMutation({
    mutationFn: () => {
      const days = form.expiresIn === "never" ? null : Number(form.expiresIn);
      const expiresAt = days == null ? undefined : new Date(Date.now() + days * 86_400_000).toISOString();
      return backendApi.createApiKey(role, {
        name: form.name.trim(),
        assistant_ids: form.allowAll ? [] : form.assistantIds,
        allow_all_assistants: form.allowAll,
        rate_limit_per_minute: Number(form.rate),
        expires_at: expiresAt,
      });
    },
    onSuccess: async (created) => {
      setCreatedKey(created);
      await queryClient.invalidateQueries({ queryKey: ["api-keys"] });
    },
    onError: (error) => setFormError(errorMessage(error)),
  });
  const revokeMutation = useMutation({
    mutationFn: (id: string) => backendApi.revokeApiKey(role, id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["api-keys"] });
      notify("密钥已撤销", "后续调用将立即被拒绝，已有日志不受影响。");
    },
    onError: (error) => notify("撤销失败", errorMessage(error)),
  });

  const keys = keysQuery.data ?? [];
  const activeAssistants = (assistantsQuery.data ?? []).filter((assistant) => assistant.status === "active");
  const assistantNames = new Map(activeAssistants.map((assistant) => [assistant.id, assistant.name]));
  const activeCount = keys.filter((key) => key.status === "active" && (!key.expires_at || new Date(key.expires_at) > new Date())).length;

  function close(open: boolean) {
    setCreateOpen(open);
    if (!open) window.setTimeout(() => {
      setCreatedKey(null);
      setForm(initialForm);
      setFormError("");
    }, 250);
  }

  function toggleAssistant(id: string) {
    setForm((current) => ({
      ...current,
      assistantIds: current.assistantIds.includes(id)
        ? current.assistantIds.filter((item) => item !== id)
        : [...current.assistantIds, id],
    }));
  }

  async function copyKey() {
    if (!createdKey) return;
    await navigator.clipboard.writeText(createdKey.key);
    notify("密钥已复制", "请保存到企业密钥管理系统。");
  }

  const rate = Number(form.rate);
  const canCreate = form.name.trim()
    && (form.allowAll || form.assistantIds.length > 0)
    && Number.isInteger(rate)
    && rate >= 1
    && rate <= 10_000;

  return <div className="space-y-6 fade-in"><div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center"><div><h2 className="text-xl font-semibold text-slate-900">API Key</h2><p className="mt-1 text-sm text-slate-500">向内部系统开放指定助手；调用会进入同一套日志和限流。</p></div><Button onClick={() => setCreateOpen(true)}><Plus size={16} />创建 API Key</Button></div><div className="grid gap-4 lg:grid-cols-3"><Card className="p-5 lg:col-span-2"><div className="flex gap-3"><span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600"><KeyRound size={19} /></span><div><h3 className="text-sm font-semibold text-slate-900">OpenAI 兼容调用</h3><p className="mt-1 text-xs leading-5 text-slate-500">通过 <code className="rounded bg-slate-100 px-1.5 py-0.5">POST /v1/chat/completions</code> 调用，model 填写助手 ID 或别名；引用会出现在 <code className="rounded bg-slate-100 px-1.5 py-0.5">x_rag.citations</code>。</p></div></div></Card><Card className="border-emerald-100 bg-emerald-50/50 p-5"><div className="flex items-center gap-2 text-sm font-semibold text-emerald-900"><ShieldCheck size={18} />安全策略已启用</div><p className="mt-2 text-xs leading-5 text-emerald-700">密钥只展示一次、服务端仅存哈希，并按 Key 执行 Redis 限流。</p></Card></div>{keysQuery.isError ? <Card className="flex items-center justify-between border-red-100 p-5"><div><strong className="text-sm text-red-800">密钥列表加载失败</strong><p className="mt-1 text-xs text-red-600">{errorMessage(keysQuery.error)}</p></div><Button variant="secondary" size="sm" onClick={() => { void keysQuery.refetch(); }}><RefreshCw size={14} />重试</Button></Card> : null}<Card><div className="border-b border-slate-100 px-5 py-4"><h3 className="font-semibold text-slate-900">已创建密钥</h3><p className="mt-1 text-xs text-slate-500">共 {keys.length} 个，其中 {activeCount} 个有效。</p></div><div className="overflow-x-auto"><table className="w-full min-w-[900px] text-left"><thead><tr className="border-b border-slate-100 bg-slate-50/60 text-[11px] font-medium text-slate-400"><th className="px-5 py-3">名称</th><th className="px-4 py-3">密钥</th><th className="px-4 py-3">允许助手</th><th className="px-4 py-3">速率限制</th><th className="px-4 py-3">最近使用</th><th className="px-4 py-3">状态</th><th className="px-5 py-3 text-right">操作</th></tr></thead><tbody className="divide-y divide-slate-100">{keys.map((key) => { const expired = Boolean(key.expires_at && new Date(key.expires_at) <= new Date()); const active = key.status === "active" && !expired; const scopes = key.allow_all_assistants ? "全部已发布助手" : key.assistant_ids.map((id) => assistantNames.get(id) ?? id.slice(0, 8)).join(" · "); return <tr key={key.id} className="hover:bg-slate-50/60"><td className="px-5 py-4"><strong className="block text-sm font-medium text-slate-800">{key.name}</strong><small className="text-[11px] text-slate-400">{key.expires_at ? `${new Date(key.expires_at).toLocaleDateString("zh-CN")} 到期` : "永不到期"}</small></td><td className="px-4 py-4 font-mono text-xs text-slate-500">{key.key_hint}</td><td className="max-w-xs px-4 py-4 text-xs text-slate-600"><span className="line-clamp-2">{scopes || "未绑定"}</span></td><td className="px-4 py-4 text-xs text-slate-600">{key.rate_limit_per_minute} 次/分钟</td><td className="px-4 py-4 text-xs text-slate-500">{key.last_used_at ? new Date(key.last_used_at).toLocaleString("zh-CN") : "从未使用"}</td><td className="px-4 py-4"><Badge tone={active ? "green" : "slate"}>{active ? "有效" : key.status === "revoked" ? "已撤销" : "已过期"}</Badge></td><td className="px-5 py-4 text-right">{active ? <Button variant="danger" size="sm" disabled={revokeMutation.isPending} onClick={() => revokeMutation.mutate(key.id)}>{revokeMutation.isPending && revokeMutation.variables === key.id ? <Activity size={14} className="animate-spin" /> : null}撤销</Button> : null}</td></tr>; })}</tbody></table>{keysQuery.isLoading ? <div className="p-8 text-center text-xs text-slate-400">正在加载密钥…</div> : null}{!keysQuery.isLoading && !keys.length ? <div className="p-8 text-center text-xs text-slate-400">还没有创建 API Key。</div> : null}</div></Card><Modal open={createOpen} onOpenChange={close} title={createdKey ? "API Key 已创建" : "创建 API Key"} description={createdKey ? "请立即复制保存，关闭后无法再次查看完整密钥。" : "限制允许调用的助手、有效期和速率，降低凭据泄露后的影响。"}>{createdKey ? <div className="space-y-5 px-6 py-6"><div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-xs leading-5 text-amber-800">这是唯一一次显示完整密钥。系统只保存不可逆哈希，无法帮助找回。</div><div className="flex items-center gap-2 rounded-xl bg-slate-950 p-4"><code className="min-w-0 flex-1 break-all text-sm text-emerald-300">{createdKey.key}</code><Button variant="ghost" size="icon" className="shrink-0 text-white hover:bg-white/10 hover:text-white" onClick={() => { void copyKey(); }} aria-label="复制密钥"><Copy size={16} /></Button></div><div className="flex items-center gap-2 text-xs text-slate-500"><Check size={15} className="text-emerald-600" />{createdKey.rate_limit_per_minute} 次/分钟 · {createdKey.expires_at ? `${new Date(createdKey.expires_at).toLocaleDateString("zh-CN")} 到期` : "永不到期"}</div></div> : <div className="space-y-5 px-6 py-5"><Field label="密钥名称"><Input value={form.name} onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} /></Field><div className="flex items-center justify-between rounded-xl bg-slate-50 p-4"><div><strong className="text-sm text-slate-800">允许全部已发布助手</strong><p className="mt-1 text-xs text-slate-500">后续新发布的助手也会自动可调用。</p></div><Toggle checked={form.allowAll} onChange={(value) => setForm((current) => ({ ...current, allowAll: value }))} label="允许全部助手" /></div>{!form.allowAll ? <div><span className="mb-2 block text-sm font-medium text-slate-700">允许调用的助手</span><div className="space-y-2">{activeAssistants.map((assistant) => { const checked = form.assistantIds.includes(assistant.id); return <button key={assistant.id} type="button" onClick={() => toggleAssistant(assistant.id)} className={`flex w-full items-center justify-between rounded-xl border px-4 py-3 text-left ${checked ? "border-indigo-300 bg-indigo-50" : "border-slate-200"}`}><span><strong className="block text-sm text-slate-800">{assistant.name}</strong><small className="text-xs text-slate-400">{assistant.alias}</small></span><span className={`h-4 w-4 rounded-full border ${checked ? "border-indigo-600 bg-indigo-600 ring-2 ring-indigo-100" : "border-slate-300"}`} /></button>; })}{!activeAssistants.length ? <p className="rounded-xl bg-amber-50 p-4 text-xs text-amber-800">暂无已发布助手，请先完成助手发布。</p> : null}</div></div> : null}<div className="grid gap-4 sm:grid-cols-2"><Field label="速率限制" hint="每分钟"><Input type="number" min={1} max={10000} value={form.rate} onChange={(event) => setForm((current) => ({ ...current, rate: event.target.value }))} /></Field><Field label="有效期"><Select value={form.expiresIn} onChange={(event) => setForm((current) => ({ ...current, expiresIn: event.target.value }))}><option value="30">30 天</option><option value="90">90 天</option><option value="365">1 年</option><option value="never">永不过期</option></Select></Field></div>{formError ? <div className="rounded-xl bg-red-50 p-4 text-xs text-red-700">{formError}</div> : null}</div>}<div className="flex justify-end gap-2 border-t border-slate-100 px-6 py-4">{createdKey ? <Button onClick={() => close(false)}>我已安全保存</Button> : <><Button variant="ghost" onClick={() => close(false)}>取消</Button><Button disabled={!canCreate || createMutation.isPending} onClick={() => createMutation.mutate()}>{createMutation.isPending ? <Activity size={15} className="animate-spin" /> : <KeyRound size={15} />}{createMutation.isPending ? "正在生成…" : "生成密钥"}</Button></>}</div></Modal></div>;
}
