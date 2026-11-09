"use client";

import { useState } from "react";
import { ChevronRight, FileText, ThumbsUp, ThumbsDown } from "lucide-react";
import { Badge, Button, Drawer } from "@/components/ui/primitives";
import { RunExecutionTranscript } from "@/components/run-execution-transcript";
import { DocumentPreview, type DocumentPreviewTarget } from "@/components/knowledge/document-preview";
import { ApiError, type RunDetail } from "@/lib/api-client";
import type { Role } from "@/lib/types";

const statusNames: Record<string, string> = { running: "运行中", succeeded: "成功", failed: "错误", cancelled: "已取消", insufficient_evidence: "证据不足" };
const duration = (value: number | null | undefined) => value == null ? "—" : value < 1000 ? `${value}ms` : `${(value / 1000).toFixed(2)}s`;

export function RunDetailDrawer({ role, log, loading, error, onOpenChange, onCollect }: { role: Role; log: RunDetail | null; loading: boolean; error: unknown; onOpenChange: (open: boolean) => void; onCollect?: (log: RunDetail, label: "good" | "bad") => void }) {
  const [preview, setPreview] = useState<DocumentPreviewTarget | null>(null);
  function openEvidence(item: RunDetail["citations"][number]) {
    setPreview({ chunkId: String(item.chunk_id ?? ""), documentName: String(item.document_name ?? "引用文件"), excerpt: typeof item.excerpt === "string" ? item.excerpt : typeof item.content === "string" ? item.content : "", location: String(item.location ?? "") });
  }
  return <>
    <Drawer open={loading || error != null || log !== null} onOpenChange={onOpenChange} title="运行详情" description={log ? `${log.request_id} · ${new Date(log.started_at).toLocaleString("zh-CN")}` : undefined}>
      {loading ? <div className="p-8 text-sm text-slate-500">正在加载运行详情…</div> : error ? <div role="alert" className="p-6 text-sm text-red-700">{error instanceof ApiError ? error.message : "运行详情读取失败。"}</div> : log ? <div className="space-y-6 p-6">
        {onCollect ? <div className="flex flex-wrap gap-2"><Button variant="secondary" size="sm" disabled={log.status === "running"} onClick={() => onCollect(log, "good")}><ThumbsUp size={14} />Good Case</Button><Button variant="secondary" size="sm" disabled={log.status === "running"} onClick={() => onCollect(log, "bad")}><ThumbsDown size={14} />Bad Case</Button><span className="self-center text-xs text-slate-400">手动收录到评测集</span></div> : null}
        <div className="rounded-xl bg-slate-950 p-5 text-white"><div className="flex items-center justify-between"><Badge tone={log.status === "succeeded" ? "green" : log.status === "failed" ? "red" : "amber"}>{statusNames[log.status] ?? log.status}</Badge><span className="text-xs text-slate-400">总耗时 {duration(log.duration_ms)}</span></div><h3 className="mt-4 text-xs font-semibold text-slate-400">查询问题</h3><p className="mt-2 whitespace-pre-wrap break-words text-sm leading-7">{log.query_text}</p><div className="mt-5 grid grid-cols-3 gap-3 border-t border-white/10 pt-4"><SmallMetric value={log.total_tokens.toLocaleString("zh-CN")} label={`Tokens${log.usage_accuracy === "estimated" ? "（估算）" : ""}`} /><SmallMetric value={String(log.citations.length)} label="引用" /><SmallMetric value={String(log.retrieved_chunk_count)} label="召回分块" /></div></div>
        <section><h3 className="text-sm font-semibold text-slate-900">回答内容</h3><p className="mt-3 whitespace-pre-wrap break-words rounded-xl bg-slate-50 p-4 text-sm leading-7 text-slate-700">{log.answer_text || "本次运行暂无回答内容。"}</p></section>
        {log.error_message ? <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-xs leading-5 text-red-700"><strong>{log.error_code ?? "run_error"}</strong><p className="mt-1">{log.error_message}</p></div> : null}
        <EvidenceFiles title="引用文件" items={log.citations} onOpen={openEvidence} />
        {log.retrieval_results.length ? <EvidenceFiles title="检索召回分块" items={log.retrieval_results} onOpen={openEvidence} /> : null}
        <RunExecutionTranscript log={log} />
      </div> : null}
    </Drawer>
    {preview ? <DocumentPreview target={preview} role={role} onClose={() => setPreview(null)} /> : null}
  </>;
}

function EvidenceFiles({ title, items, onOpen }: { title: string; items: RunDetail["citations"]; onOpen: (item: RunDetail["citations"][number]) => void }) {
  return <section><h3 className="text-sm font-semibold text-slate-900">{title}</h3>{items.length ? <div className="mt-3 space-y-2">{items.map((item, index) => <button type="button" key={`${String(item.chunk_id ?? index)}-${index}`} aria-label={`查看引用文件 ${String(item.document_name ?? "未知文档")} ${index + 1}`} onClick={() => onOpen(item)} className="group flex w-full items-center gap-3 rounded-xl border border-slate-200 p-4 text-left transition hover:border-indigo-200 hover:bg-indigo-50/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"><span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600"><FileText size={16} /></span><span className="min-w-0 flex-1"><strong className="block truncate text-sm font-medium text-indigo-700">{String(item.document_name ?? "未知文档")}</strong><small className="mt-1 block text-xs text-slate-400">V{String(item.document_version ?? "—")} · {String(item.location ?? "点击查看分块和完整文件内容")}</small></span><ChevronRight size={15} className="shrink-0 text-slate-300 group-hover:text-indigo-500" /></button>)}</div> : <p className="mt-3 text-xs text-slate-400">本次运行没有引用文件。</p>}</section>;
}

function SmallMetric({ value, label }: { value: string; label: string }) {
  return <div><strong className="block text-sm">{value}</strong><span className="text-[10px] text-slate-400">{label}</span></div>;
}
