"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Activity, ArrowRight, Bot, CheckCircle2, CircleAlert, Clock3, Database,
  FileStack, MessageSquareText, RefreshCw, UploadCloud,
} from "lucide-react";
import { ApiError, backendApi, type BuildTaskDetailRead } from "@/lib/api-client";
import type { Role, ViewKey } from "@/lib/types";
import { Badge, Button, Card } from "@/components/ui/primitives";

function formatDuration(value: number) {
  return value < 1_000 ? `${value}ms` : `${(value / 1_000).toFixed(2)}s`;
}

function taskState(task: BuildTaskDetailRead) {
  if (task.status === "ready") return { icon: CheckCircle2, tone: "text-emerald-600 bg-emerald-50", label: "构建完成" };
  if (task.status === "failed" || task.status === "cancelled") return { icon: CircleAlert, tone: "text-red-600 bg-red-50", label: task.status === "failed" ? "等待重试" : "已取消" };
  return { icon: Activity, tone: "text-indigo-600 bg-indigo-50", label: task.status === "preview_ready" ? "等待确认" : "构建中" };
}

export function OperationsOverview({ role, onNavigate }: { role: Role; onNavigate: (view: ViewKey) => void }) {
  const knowledgeQuery = useQuery({
    queryKey: ["knowledge-bases", role],
    queryFn: () => backendApi.listKnowledgeBases(role),
  });
  const assistantsQuery = useQuery({
    queryKey: ["assistants", role],
    queryFn: () => backendApi.listAssistants(role),
  });
  const metricsQuery = useQuery({
    queryKey: ["daily-metrics", role, 14],
    queryFn: () => backendApi.listDailyMetrics(role, 14),
  });
  const tasksQuery = useQuery({
    queryKey: ["dashboard-build-tasks", role, (knowledgeQuery.data ?? []).map((item) => item.id).join("|")],
    queryFn: async () => (await Promise.all((knowledgeQuery.data ?? []).map((knowledgeBase) => backendApi.listBuildTasks(role, knowledgeBase.id)))).flat().sort((left, right) => right.updated_at.localeCompare(left.updated_at)).slice(0, 5),
    enabled: knowledgeQuery.isSuccess && (knowledgeQuery.data?.length ?? 0) > 0,
    refetchInterval: (query) => query.state.data?.some((task) => ["queued", "parsing", "indexing", "replacing"].includes(task.status)) ? 2_000 : false,
  });

  const knowledgeBases = knowledgeQuery.data ?? [];
  const assistants = assistantsQuery.data ?? [];
  const metrics = metricsQuery.data ?? [];
  const readyKnowledge = knowledgeBases.filter((item) => item.status === "ready").length;
  const documentCount = knowledgeBases.reduce((total, item) => total + item.document_count, 0);
  const chunkCount = knowledgeBases.reduce((total, item) => total + item.chunk_count, 0);
  const readiness = knowledgeBases.length ? Math.round((readyKnowledge / knowledgeBases.length) * 100) : 0;
  const today = new Date().toISOString().slice(0, 10);
  const todayMetrics = metrics.filter((item) => item.metric_date === today);
  const todayRequests = todayMetrics.reduce((total, item) => total + item.request_count, 0);
  const todayDuration = todayMetrics.reduce((total, item) => total + item.total_duration_ms, 0);
  const averageDuration = todayRequests ? Math.round(todayDuration / todayRequests) : 0;
  const totalRequests = metrics.reduce((total, item) => total + item.request_count, 0);
  const totalSuccess = metrics.reduce((total, item) => total + item.success_count, 0);
  const buildTasks = tasksQuery.data ?? [];
  const error = knowledgeQuery.error ?? assistantsQuery.error ?? metricsQuery.error ?? tasksQuery.error;

  const daily = new Map<string, number>();
  for (const item of metrics) daily.set(item.metric_date, (daily.get(item.metric_date) ?? 0) + item.request_count);
  const trend = [...daily.entries()].sort(([left], [right]) => left.localeCompare(right));
  const trendMax = Math.max(1, ...trend.map(([, value]) => value));

  const hasKnowledge = knowledgeBases.length > 0;
  const hasChunks = chunkCount > 0;
  const hasAssistant = assistants.length > 0;
  const hasConversation = totalRequests > 0;

  return (
    <div className="space-y-6 fade-in">
      <section className="overflow-hidden rounded-2xl bg-slate-950 text-white shadow-xl shadow-slate-200">
        <div className="soft-grid grid gap-8 px-7 py-7 md:grid-cols-[1fr_auto] md:px-9 md:py-8">
          <div><Badge tone="indigo" className="bg-white/10 text-indigo-100">企业知识中台 · 1.0</Badge><h2 className="mt-4 text-2xl font-semibold tracking-tight md:text-3xl">开始构建可追溯的企业问答</h2><p className="mt-2 max-w-2xl text-sm leading-6 text-slate-300">从导入一份资料开始，系统会完成解析、分块、索引和检索验证。每个回答都能追溯到原始证据。</p><div className="mt-6 flex flex-wrap gap-3"><Button onClick={() => onNavigate("knowledge")} className="bg-white text-slate-900 hover:bg-indigo-50"><UploadCloud size={16} />导入资料</Button><Button onClick={() => onNavigate("chat")} variant="ghost" className="border border-white/15 text-white hover:bg-white/10 hover:text-white"><MessageSquareText size={16} />体验在线对话</Button></div></div>
          <div className="hidden min-w-60 rounded-2xl border border-white/10 bg-white/5 p-5 backdrop-blur md:block"><div className="flex items-center justify-between text-xs text-slate-300"><span>知识就绪度</span><span>{readiness}%</span></div><div className="mt-3 h-2 overflow-hidden rounded-full bg-white/10"><div className="h-full rounded-full bg-gradient-to-r from-indigo-400 to-cyan-300" style={{ width: `${readiness}%` }} /></div><div className="mt-5 grid grid-cols-2 gap-4"><div><strong className="block text-xl">{readyKnowledge}/{knowledgeBases.length}</strong><span className="text-xs text-slate-400">知识库可用</span></div><div><strong className="block text-xl">{totalRequests ? `${((totalSuccess / totalRequests) * 100).toFixed(1)}%` : "—"}</strong><span className="text-xs text-slate-400">14 日成功率</span></div></div></div>
        </div>
      </section>

      {error ? <Card className="flex items-center justify-between border-red-100 p-5"><div><strong className="text-sm text-red-800">工作台数据未完整加载</strong><p className="mt-1 text-xs text-red-600">{error instanceof ApiError ? error.message : "请检查后端服务。"}</p></div><Button variant="secondary" size="sm" onClick={() => { void knowledgeQuery.refetch(); void assistantsQuery.refetch(); void metricsQuery.refetch(); void tasksQuery.refetch(); }}><RefreshCw size={14} />重试</Button></Card> : null}

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Metric icon={Database} tone="bg-indigo-50 text-indigo-600" value={knowledgeBases.length.toLocaleString("zh-CN")} label="知识库" detail={`${documentCount.toLocaleString("zh-CN")} 份资料`} />
        <Metric icon={FileStack} tone="bg-cyan-50 text-cyan-600" value={chunkCount.toLocaleString("zh-CN")} label="知识分块" detail={`${readyKnowledge} 个知识库可用`} />
        <Metric icon={MessageSquareText} tone="bg-emerald-50 text-emerald-600" value={todayRequests.toLocaleString("zh-CN")} label="今日问答" detail={`${assistants.filter((item) => item.status === "active").length} 个已发布助手`} />
        <Metric icon={Clock3} tone="bg-amber-50 text-amber-600" value={todayRequests ? formatDuration(averageDuration) : "—"} label="今日平均耗时" detail="基于日聚合数据" />
      </section>

      <section className="grid gap-6 xl:grid-cols-[1.45fr_1fr]">
        <Card className="p-6"><div className="flex items-start justify-between"><div><h3 className="font-semibold text-slate-900">问答趋势</h3><p className="mt-1 text-xs text-slate-500">最近 14 天的日聚合调用量</p></div><Badge tone="green">真实数据</Badge></div>{trend.length ? <><div className="mt-7 flex h-48 items-end gap-2 border-b border-slate-100 px-1">{trend.map(([date, value]) => <div key={date} title={`${date}：${value} 次`} className="group relative flex h-full flex-1 items-end"><div className="w-full rounded-t-md bg-indigo-200 transition group-hover:bg-indigo-500" style={{ height: `${Math.max(4, (value / trendMax) * 100)}%` }} /></div>)}</div><div className="mt-3 flex justify-between text-[10px] text-slate-400"><span>{trend[0]?.[0]}</span><span>{trend.at(-1)?.[0]}</span></div></> : <div className="flex h-52 items-center justify-center text-xs text-slate-400">暂无问答数据，完成首次对话和聚合任务后显示。</div>}</Card>
        <Card className="p-6"><div className="flex items-start justify-between"><div><h3 className="font-semibold text-slate-900">构建任务</h3><p className="mt-1 text-xs text-slate-500">最近的资料解析与索引任务</p></div><Button variant="ghost" size="sm" onClick={() => onNavigate("knowledge")}>查看全部<ArrowRight size={14} /></Button></div><div className="mt-4 divide-y divide-slate-100">{buildTasks.map((task) => { const state = taskState(task); return <Task key={task.id} icon={state.icon} tone={state.tone} title={task.document_name} detail={`${task.current_step ?? task.status} · ${task.progress}%`} status={state.label} pulse={["queued", "parsing", "indexing", "replacing"].includes(task.status)} />; })}{!buildTasks.length ? <p className="py-10 text-center text-xs text-slate-400">暂无构建任务。</p> : null}</div></Card>
      </section>

      <Card className="p-6"><div className="flex items-center justify-between"><div><h3 className="font-semibold text-slate-900">完成一条知识链路</h3><p className="mt-1 text-xs text-slate-500">进度来自当前系统的真实数据</p></div><Bot className="text-indigo-500" size={24} /></div><div className="mt-6 grid gap-3 md:grid-cols-4"><FlowStep index="01" title="创建知识库" description="选择 Embedding 模型" done={hasKnowledge} /><FlowStep index="02" title="导入与分块" description="预览并构建文档索引" done={hasChunks} /><FlowStep index="03" title="创建助手" description="绑定模型与知识库" done={hasAssistant} /><FlowStep index="04" title="开始对话" description="验证回答、引用与日志" done={hasConversation} /></div></Card>
    </div>
  );
}

function Metric({ icon: Icon, tone, value, label, detail }: { icon: typeof Activity; tone: string; value: string; label: string; detail: string }) { return <Card className="p-5"><span className={`flex h-10 w-10 items-center justify-center rounded-xl ${tone}`}><Icon size={19} /></span><div className="mt-4 text-2xl font-semibold tracking-tight text-slate-900">{value}</div><div className="mt-1 flex items-center justify-between gap-3 text-xs"><span className="font-medium text-slate-600">{label}</span><span className="text-right text-slate-400">{detail}</span></div></Card>; }
function Task({ icon: Icon, tone, title, detail, status, pulse = false }: { icon: typeof Activity; tone: string; title: string; detail: string; status: string; pulse?: boolean }) { return <div className="flex items-center gap-3 py-4"><span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${tone} ${pulse ? "pulse-soft" : ""}`}><Icon size={17} /></span><span className="min-w-0 flex-1"><strong className="block truncate text-sm font-medium text-slate-800">{title}</strong><small className="text-xs text-slate-400">{detail}</small></span><span className="text-xs font-medium text-slate-500">{status}</span></div>; }
function FlowStep({ index, title, description, done = false }: { index: string; title: string; description: string; done?: boolean }) { return <div className={`rounded-xl border p-4 ${done ? "border-indigo-100 bg-indigo-50/60" : "border-slate-200 bg-slate-50/50"}`}><div className="flex items-center justify-between"><span className={`text-xs font-semibold ${done ? "text-indigo-600" : "text-slate-400"}`}>{index}</span>{done ? <CheckCircle2 size={16} className="text-indigo-600" /> : <span className="h-2 w-2 rounded-full bg-slate-300" />}</div><h4 className="mt-5 text-sm font-semibold text-slate-800">{title}</h4><p className="mt-1 text-xs leading-5 text-slate-500">{description}</p></div>; }
