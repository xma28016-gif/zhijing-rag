"use client";

import { Activity } from "lucide-react";
import { Badge } from "@/components/ui/primitives";
import type { RunDetail } from "@/lib/api-client";

const descriptions: Record<string, [string, string]> = {
  query_rewrite: ["问题改写", "结合历史对话补齐指代，生成用于检索的问题。"],
  embedding: ["查询向量化", "将查询转换成向量，用于查找语义相近的知识分块。"],
  semantic_retrieval: ["语义召回", "按向量相似度查找候选知识。"],
  keyword_retrieval: ["关键词召回", "按关键词匹配查找候选知识。"],
  rrf_fusion: ["RRF 融合", "合并语义和关键词召回结果，综合排名并去重。"],
  rerank: ["结果重排", "重新判断候选分块与问题的相关程度。"],
  generation: ["生成回答", "根据选定的知识证据及上下文生成回答。"],
};
const states: Record<string, string> = { succeeded: "成功", failed: "失败", running: "运行中", cancelled: "已取消", insufficient_evidence: "证据不足" };

export function JsonRecord({ value }: { value: unknown }) {
  return <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-slate-950 p-4 font-mono text-[11px] leading-6 text-slate-200">{JSON.stringify(value, null, 2)}</pre>;
}

export function RunExecutionTranscript({ log }: { log: RunDetail }) {
  return <section className="space-y-4"><div><h3 className="text-sm font-semibold text-slate-900">执行实录</h3><p className="mt-1 text-xs leading-5 text-slate-500">按执行顺序展开节点，查看已记录的输入、输出、用量与异常。旧日志未采集的内容无法补回。</p></div>
    <div className="space-y-3 border-l-2 border-indigo-100 pl-4">{[...log.steps].sort((a, b) => a.sequence - b.sequence).map((step) => <details key={step.id} className="group rounded-xl border border-slate-200 bg-white open:border-indigo-200">
      <summary className="flex cursor-pointer list-none items-center gap-3 p-4 focus-visible:outline-indigo-500"><Activity size={16} className={step.status === "failed" ? "text-red-500" : "text-indigo-500"} /><span className="min-w-0 flex-1"><strong className="block text-sm text-slate-800">{step.sequence + 1}. {descriptions[step.kind]?.[0] ?? step.kind}</strong><small className="mt-1 block text-slate-500">输入 {step.input_tokens} / 输出 {step.output_tokens} Tokens · {step.duration_ms ?? "—"} ms</small></span><Badge tone={step.status === "failed" ? "red" : step.status === "running" ? "indigo" : "green"}>{states[step.status] ?? step.status}</Badge><span className="text-xs text-slate-400 group-open:rotate-90">›</span></summary>
      <div className="space-y-3 border-t border-slate-100 p-4"><p className="text-xs leading-6 text-slate-600">{descriptions[step.kind]?.[1] ?? "此节点的执行内容由运行时记录。"}</p><h4 className="text-xs font-semibold text-slate-600">输入记录</h4><JsonRecord value={step.input_summary} /><h4 className="text-xs font-semibold text-slate-600">输出记录</h4><JsonRecord value={step.output_summary} />{step.error_message || step.error_code ? <div role="alert" className="rounded-lg bg-red-50 p-3 text-xs leading-6 text-red-700"><strong>{step.error_code}</strong><p>{step.error_message}</p></div> : null}<p className="text-[11px] leading-5 text-slate-400">此类历史节点记录的是运行摘要，未记录完整执行代码、Plan / ReAct 事件或模型隐含推理。</p></div>
    </details>)}{!log.steps.length ? <p className="text-xs text-slate-500">该次运行没有步骤记录。</p> : null}</div>
    <details className="rounded-xl border border-slate-200 p-4"><summary className="cursor-pointer text-sm font-medium text-slate-700">调用上下文与配置快照</summary><div className="mt-3"><JsonRecord value={log.config_snapshot} /></div></details>
  </section>;
}
