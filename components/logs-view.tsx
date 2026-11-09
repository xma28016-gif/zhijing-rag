"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Activity, AlertCircle, ArrowDownToLine, ArrowLeft, CheckCircle2, ChevronRight,
  Clock3, Coins, MessageSquareText, RefreshCw, Search, ThumbsUp, ThumbsDown,
} from "lucide-react";
import { useMemo, useState } from "react";
import { Badge, Button, Card, Input, Select } from "@/components/ui/primitives";
import { ApiError, backendApi, type RunRead } from "@/lib/api-client";
import { CaseCollectionDialog } from "@/components/case-collection-dialog";
import { RunDetailDrawer } from "@/components/run-detail-drawer";
import type { Role } from "@/lib/types";

const statusLabels: Record<string, string> = {
  running: "运行中",
  succeeded: "成功",
  failed: "错误",
  cancelled: "已取消",
  insufficient_evidence: "证据不足",
};

function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : "无法读取运行日志。";
}

function formatDuration(value: number | null | undefined) {
  if (value == null) return "—";
  if (value < 1_000) return `${value}ms`;
  return `${(value / 1_000).toFixed(2)}s`;
}

function csvCell(value: string | number | null | undefined) {
  const text = value == null ? "" : String(value);
  return `"${text.replaceAll('"', '""')}"`;
}

type LogFocus = "requests" | "tokens" | "duration" | "success";

export function LogsView({ role, initialDays = "7", initialFocus, onOpenDataset }: { role: Role; initialDays?: string; initialFocus?: LogFocus; onOpenDataset: (id: string) => void }) {
  const [recordsFocus, setRecordsFocus] = useState<LogFocus | null>(initialFocus ?? null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [capture, setCapture] = useState<{ run: RunRead; label: "good" | "bad" } | null>(null);
  const [queryInput, setQueryInput] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const [assistantId, setAssistantId] = useState("");
  const [status, setStatus] = useState("");
  const [days, setDays] = useState(initialDays);
  const startedAfter = useMemo(() => {
    const date = new Date();
    if (days === "today") date.setHours(0, 0, 0, 0);
    else date.setDate(date.getDate() - Number(days));
    return date.toISOString();
  }, [days]);

  const assistantsQuery = useQuery({
    queryKey: ["assistants", role],
    queryFn: () => backendApi.listAssistants(role),
  });
  const runsQuery = useQuery({
    queryKey: ["runs", role, assistantId, status, appliedQuery, startedAfter],
    queryFn: () => backendApi.listRuns(role, {
      assistantId: assistantId || undefined,
      status: status || undefined,
      query: appliedQuery || undefined,
      startedAfter,
      limit: 100,
    }),
    refetchInterval: (query) => query.state.data?.some((run) => run.status === "running") ? 2_000 : false,
  });
  const metricsQuery = useQuery({
    queryKey: ["daily-metrics", role, days],
    queryFn: () => backendApi.listDailyMetrics(role, days === "today" ? 1 : Number(days)),
  });
  const detailQuery = useQuery({
    queryKey: ["run-detail", role, selectedId],
    queryFn: () => backendApi.getRunDetail(role, selectedId!),
    enabled: Boolean(selectedId),
  });

  const assistants = assistantsQuery.data ?? [];
  const assistantNames = new Map(assistants.map((assistant) => [assistant.id, assistant.name]));
  const runs = [...(runsQuery.data ?? [])].sort((left, right) => recordsFocus === "tokens" ? right.total_tokens - left.total_tokens : recordsFocus === "duration" ? (right.duration_ms ?? 0) - (left.duration_ms ?? 0) : right.started_at.localeCompare(left.started_at));
  const metrics = metricsQuery.data ?? [];
  const totals = metrics.reduce((accumulator, item) => ({
    requests: accumulator.requests + item.request_count,
    successes: accumulator.successes + item.success_count,
    errors: accumulator.errors + item.error_count,
    insufficient: accumulator.insufficient + item.insufficient_evidence_count,
    tokens: accumulator.tokens + item.total_tokens,
    duration: accumulator.duration + item.total_duration_ms,
    maxDuration: Math.max(accumulator.maxDuration, item.max_duration_ms),
  }), { requests: 0, successes: 0, errors: 0, insufficient: 0, tokens: 0, duration: 0, maxDuration: 0 });
  const averageDuration = totals.requests ? Math.round(totals.duration / totals.requests) : 0;
  const successRate = totals.requests ? ((totals.successes / totals.requests) * 100).toFixed(1) : "0.0";
  const dailyBars = useMemo(() => {
    const byDate = new Map<string, number>();
    for (const item of metrics) byDate.set(item.metric_date, (byDate.get(item.metric_date) ?? 0) + item.request_count);
    const entries = [...byDate.entries()].sort(([left], [right]) => left.localeCompare(right));
    const max = Math.max(1, ...entries.map(([, count]) => count));
    return entries.map(([date, count]) => ({ date, count, height: Math.max(4, Math.round((count / max) * 100)) }));
  }, [metrics]);

  function openRecords(focus: LogFocus) {
    setAssistantId("");
    setQueryInput("");
    setAppliedQuery("");
    setStatus(focus === "success" ? "succeeded" : "");
    setRecordsFocus(focus);
  }

  function exportRuns() {
    const header = ["运行ID", "请求ID", "查询", "助手", "渠道", "状态", "Token", "耗时ms", "开始时间", "错误原因"];
    const rows = runs.map((run) => [run.id, run.request_id, run.query_text, assistantNames.get(run.assistant_id) ?? run.assistant_id, run.channel, run.status, run.total_tokens, run.duration_ms, run.started_at, run.error_message]);
    const csv = `\uFEFF${[header, ...rows].map((row) => row.map(csvCell).join(",")).join("\n")}`;
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `run-logs-${new Date().toISOString().slice(0, 10)}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return <div className="space-y-6 fade-in">
    {recordsFocus ? <Button variant="ghost" className="px-0" onClick={() => setRecordsFocus(null)}><ArrowLeft size={15} />返回日志概览</Button> : null}
    <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center"><div><h2 className="text-xl font-semibold text-slate-900">运行日志</h2><p className="mt-1 text-sm text-slate-500">记录每次查询、引用、耗时及 Embedding / Rerank / LLM 的累计用量。</p></div><Button variant="secondary" disabled={!runs.length} onClick={exportRuns}><ArrowDownToLine size={15} />导出 CSV</Button></div>
    {runsQuery.isError || metricsQuery.isError ? <Card className="flex items-center justify-between border-red-100 p-5"><div><strong className="text-sm text-red-800">日志加载失败</strong><p className="mt-1 text-xs text-red-600">{errorMessage(runsQuery.error ?? metricsQuery.error)}</p></div><Button variant="secondary" size="sm" onClick={() => { void runsQuery.refetch(); void metricsQuery.refetch(); }}><RefreshCw size={14} />重试</Button></Card> : null}
    <div style={{ display: recordsFocus ? "none" : undefined }} className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"><Metric icon={MessageSquareText} tone="indigo" value={totals.requests.toLocaleString("zh-CN")} label={days === "today" ? "今日问答" : `近 ${days} 日问答`} onClick={() => openRecords("requests")} detail={`${totals.insufficient} 次证据不足`} /><Metric icon={Coins} tone="cyan" value={totals.tokens.toLocaleString("zh-CN")} label="总 Tokens" onClick={() => openRecords("tokens")} detail="包含各类模型调用，缺失用量单独标记" /><Metric icon={Clock3} tone="amber" value={formatDuration(averageDuration)} label="平均耗时" onClick={() => openRecords("duration")} detail={`最长 ${formatDuration(totals.maxDuration)}`} /><Metric icon={CheckCircle2} tone="green" value={`${successRate}%`} label="成功率" onClick={() => openRecords("success")} detail={`${totals.errors} 次错误`} /></div>
    <div style={{ display: recordsFocus ? "none" : undefined }} className="grid gap-5 xl:grid-cols-[1.4fr_1fr]"><Card className="p-5"><div className="flex items-start justify-between"><div><h3 className="text-sm font-semibold text-slate-900">调用趋势</h3><p className="mt-1 text-xs text-slate-500">按日聚合的请求数</p></div><Badge tone="green">长期保留</Badge></div>{dailyBars.length ? <><div className="mt-6 flex h-40 items-end gap-2 border-b border-slate-100">{dailyBars.map((item) => <div key={item.date} title={`${item.date}：${item.count} 次`} className="flex h-full flex-1 items-end"><div className="w-full rounded-t bg-gradient-to-t from-indigo-500 to-indigo-300" style={{ height: `${item.height}%` }} /></div>)}</div><div className="mt-2 flex justify-between text-[10px] text-slate-400"><span>{dailyBars[0]?.date}</span><span>{dailyBars.at(-1)?.date}</span></div></> : <div className="flex h-44 items-center justify-center text-xs text-slate-400">暂无日聚合数据，定时任务运行后会显示。</div>}</Card><Card className="p-5"><h3 className="text-sm font-semibold text-slate-900">运行结果</h3><div className="mt-5 space-y-4"><Usage label="成功" value={totals.successes} total={totals.requests} tone="bg-emerald-500" /><Usage label="证据不足" value={totals.insufficient} total={totals.requests} tone="bg-amber-400" /><Usage label="错误" value={totals.errors} total={totals.requests} tone="bg-red-500" /></div><p className="mt-6 text-xs leading-5 text-slate-400">“证据不足”是严格知识库策略的正常拒答，不计为系统错误。</p></Card></div>
    <Card><div className="border-b border-slate-100 px-5 py-4"><h3 className="text-sm font-semibold text-slate-800">运行记录 <span className="ml-1 font-normal text-slate-400">{runs.length}</span></h3><p className="mt-1 text-xs text-slate-400">点击查询内容查看问题、回答和引用文件。{recordsFocus === "duration" ? "当前按耗时从高到低排序。" : recordsFocus === "tokens" ? "当前按 Tokens 从高到低排序。" : ""}</p></div><div className="flex flex-col gap-3 border-b border-slate-100 px-5 py-4 lg:flex-row"><div className="relative flex-1"><Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" /><Input value={queryInput} onChange={(event) => setQueryInput(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") setAppliedQuery(queryInput.trim()); }} placeholder="搜索查询内容，Enter 确认" className="h-9 pl-9" /></div><Select value={assistantId} onChange={(event) => setAssistantId(event.target.value)} className="h-9 lg:w-40"><option value="">全部助手</option>{assistants.map((assistant) => <option key={assistant.id} value={assistant.id}>{assistant.name}</option>)}</Select><Select value={status} onChange={(event) => setStatus(event.target.value)} className="h-9 lg:w-36"><option value="">全部状态</option><option value="succeeded">成功</option><option value="insufficient_evidence">证据不足</option><option value="failed">错误</option><option value="cancelled">已取消</option></Select><Select value={days} onChange={(event) => setDays(event.target.value)} className="h-9 lg:w-40"><option value="today">今天</option><option value="1">最近 24 小时</option><option value="7">最近 7 天</option><option value="30">最近 30 天</option><option value="90">最近 90 天</option></Select></div><div className="overflow-x-auto"><table className="w-full min-w-[940px] text-left"><thead><tr className="border-b border-slate-100 bg-slate-50/60 text-[11px] font-medium text-slate-400"><th className="px-5 py-3">查询内容</th><th className="px-4 py-3">助手 / 渠道</th><th className="px-4 py-3">Tokens</th><th className="px-4 py-3">耗时</th><th className="px-4 py-3">状态</th><th className="px-5 py-3">时间</th><th className="w-12 px-3 py-3" /></tr></thead><tbody className="divide-y divide-slate-100">{runs.map((run) => <tr key={run.id} onClick={() => setSelectedId(run.id)} className="cursor-pointer hover:bg-slate-50/70"><td className="px-5 py-4"><button type="button" aria-label={`查看运行记录 ${run.request_id}`} onClick={() => setSelectedId(run.id)} className="block max-w-xs truncate rounded text-left text-sm font-medium text-indigo-700 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500">{run.query_text}</button><small className="font-mono text-[11px] text-slate-400">{run.request_id}</small></td><td className="px-4 py-4"><span className="block text-xs text-slate-600">{assistantNames.get(run.assistant_id) ?? "未知助手"}</span><small className="text-[11px] text-slate-400">{run.channel === "browser" ? "在线对话" : run.channel === "api" ? "API" : "检索测试"}</small></td><td className="px-4 py-4 text-sm text-slate-600">{run.total_tokens ? run.total_tokens.toLocaleString("zh-CN") : "—"}{run.usage_accuracy === "estimated" ? <small className="ml-1 text-amber-600">估</small> : null}</td><td className="px-4 py-4 text-sm text-slate-600">{formatDuration(run.duration_ms)}</td><td className="px-4 py-4"><Status status={run.status} /></td><td className="px-5 py-4 text-xs text-slate-500">{new Date(run.started_at).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}</td><td className="px-3 py-4"><div className="flex gap-1" onClick={(event) => event.stopPropagation()}><Button variant="ghost" size="icon" aria-label={`收录 Good Case ${run.request_id}`} title="Good Case" disabled={run.status === "running"} onClick={() => setCapture({ run, label: "good" })}><ThumbsUp size={15} /></Button><Button variant="ghost" size="icon" aria-label={`收录 Bad Case ${run.request_id}`} title="Bad Case" disabled={run.status === "running"} onClick={() => setCapture({ run, label: "bad" })}><ThumbsDown size={15} /></Button><ChevronRight size={16} className="self-center text-slate-300" /></div></td></tr>)}</tbody></table>{runsQuery.isLoading ? <div className="p-8 text-center text-xs text-slate-400">正在加载日志…</div> : null}{!runsQuery.isLoading && !runs.length ? <div className="p-8 text-center text-xs text-slate-400">当前筛选条件下没有运行记录。</div> : null}</div></Card>
    <RunDetailDrawer role={role} log={detailQuery.data ?? null} loading={detailQuery.isLoading} error={detailQuery.error} onOpenChange={(open) => { if (!open) setSelectedId(null); }} onCollect={(run, label) => { setSelectedId(null); setCapture({ run, label }); }} />
    {capture ? <CaseCollectionDialog key={capture.run.id} role={role} run={capture.run} initialLabel={capture.label} onClose={() => setCapture(null)} onOpenDataset={onOpenDataset} /> : null}
  </div>;
}


function Metric({ icon: Icon, tone, value, label, detail, onClick }: { icon: typeof Activity; tone: "indigo" | "cyan" | "amber" | "green"; value: string; label: string; detail: string; onClick: () => void }) { const tones = { indigo: "bg-indigo-50 text-indigo-600", cyan: "bg-cyan-50 text-cyan-600", amber: "bg-amber-50 text-amber-600", green: "bg-emerald-50 text-emerald-600" }; return <button type="button" aria-label={`查看${label}记录`} onClick={onClick} className="group rounded-xl text-left outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"><Card className="h-full p-5 transition group-hover:border-indigo-200 group-hover:shadow-md"><div className="flex items-center gap-3"><span className={`flex h-9 w-9 items-center justify-center rounded-lg ${tones[tone]}`}><Icon size={17} /></span><span className="text-xs text-slate-500">{label}</span></div><strong className="mt-4 block text-2xl text-slate-900">{value}</strong><span className="mt-1 block text-[11px] text-slate-400">{detail}</span></Card></button>; }
function Usage({ label, value, total, tone }: { label: string; value: number; total: number; tone: string }) { const width = total ? `${Math.max(2, (value / total) * 100)}%` : "0%"; return <div><div className="mb-2 flex justify-between text-xs"><span className="font-medium text-slate-600">{label}</span><span className="text-slate-400">{value.toLocaleString("zh-CN")}</span></div><div className="h-2 overflow-hidden rounded-full bg-slate-100"><div className={`h-full rounded-full ${tone}`} style={{ width }} /></div></div>; }
function Status({ status }: { status: string }) { if (status === "succeeded") return <Badge tone="green"><CheckCircle2 size={11} className="mr-1" />成功</Badge>; if (status === "failed") return <Badge tone="red"><AlertCircle size={11} className="mr-1" />错误</Badge>; if (status === "running") return <Badge tone="indigo"><Activity size={11} className="mr-1 animate-spin" />运行中</Badge>; return <Badge tone="amber">{statusLabels[status] ?? status}</Badge>; }
