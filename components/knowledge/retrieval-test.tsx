"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Activity, ArrowDownToLine, CheckCircle2, FileSearch, Search,
  SlidersHorizontal, Sparkles,
} from "lucide-react";
import { useState } from "react";
import { Badge, Button, Card, Field, Input, Select } from "@/components/ui/primitives";
import { ApiError, backendApi, type RetrievalTestResponse } from "@/lib/api-client";
import type { Role } from "@/lib/types";

type RetrievalTestProps = {
  knowledgeBaseId: string;
  role: Role;
};

function numericValue(value: string, fallback: number, min: number, max: number) {
  const parsed = Number(value);
  return Number.isInteger(parsed) ? Math.min(max, Math.max(min, parsed)) : fallback;
}

function score(value: number | null | undefined) {
  return value == null ? "--" : value.toFixed(4);
}

function locationOf(result: RetrievalTestResponse["results"][number]) {
  return [
    `V${result.document_version}`,
    result.page_from ? `第 ${result.page_from} 页` : null,
    result.sheet_name ? `工作表 ${result.sheet_name}` : null,
    result.cell_range,
    `分块 ${result.chunk_ordinal + 1}`,
  ].filter(Boolean).join(" · ");
}

export function RetrievalTest({ knowledgeBaseId, role }: RetrievalTestProps) {
  const [query, setQuery] = useState("");
  const [semanticTopK, setSemanticTopK] = useState("30");
  const [keywordTopK, setKeywordTopK] = useState("30");
  const [finalTopK, setFinalTopK] = useState("6");
  const [rerankModelId, setRerankModelId] = useState("");

  const rerankQuery = useQuery({
    queryKey: ["rerank-model-options", role],
    queryFn: () => backendApi.listRerankModelOptions(role),
  });
  const retrieval = useMutation({
    mutationFn: () => backendApi.retrievalTest(role, knowledgeBaseId, {
      query: query.trim(),
      rerank_model_config_id: rerankModelId || undefined,
      semantic_top_k: numericValue(semanticTopK, 30, 1, 100),
      keyword_top_k: numericValue(keywordTopK, 30, 1, 100),
      fusion_top_k: 20,
      final_top_k: numericValue(finalTopK, 6, 1, 20),
    }),
  });

  function run() {
    if (query.trim() && !retrieval.isPending) retrieval.mutate();
  }

  function exportResults() {
    if (!retrieval.data) return;
    const blob = new Blob([JSON.stringify(retrieval.data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `retrieval-test-${Date.now()}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  const result = retrieval.data;
  const totalMs = result
    ? result.embedding_ms + result.retrieval_ms + result.rerank_ms
    : 0;

  return (
    <div className="grid gap-5 xl:grid-cols-[330px_1fr]">
      <Card className="h-fit p-5">
        <div className="flex items-center gap-2">
          <SlidersHorizontal size={17} className="text-indigo-600" />
          <h3 className="text-sm font-semibold text-slate-900">检索参数</h3>
        </div>
        <div className="mt-5 space-y-4">
          <div className="rounded-lg bg-indigo-50 px-3 py-3 text-xs leading-5 text-indigo-700">
            语义与中文关键词并行召回，经 RRF 融合后可选用 Rerank 排序。
          </div>
          <Field label="语义召回数"><Input type="number" min={1} max={100} value={semanticTopK} onChange={(event) => setSemanticTopK(event.target.value)} /></Field>
          <Field label="关键词召回数"><Input type="number" min={1} max={100} value={keywordTopK} onChange={(event) => setKeywordTopK(event.target.value)} /></Field>
          <Field label="最终返回数"><Input type="number" min={1} max={20} value={finalTopK} onChange={(event) => setFinalTopK(event.target.value)} /></Field>
          <Field label="Rerank 模型" hint="可选">
            <Select value={rerankModelId} onChange={(event) => setRerankModelId(event.target.value)} disabled={rerankQuery.isLoading}>
              <option value="">不启用重排</option>
              {(rerankQuery.data ?? []).map((model) => <option key={model.id} value={model.id}>{model.name} · {model.provider_name}{model.is_default ? "（默认）" : ""}</option>)}
            </Select>
          </Field>
          {rerankQuery.isError ? <p className="text-xs leading-5 text-amber-700">Rerank 模型列表加载失败，仍可执行混合检索。</p> : null}
        </div>
      </Card>

      <div className="space-y-4">
        <Card className="p-5">
          <label className="text-sm font-semibold text-slate-800" htmlFor="retrieval-query">输入一个真实问题</label>
          <div className="mt-3 flex gap-2">
            <Input id="retrieval-query" value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") run(); }} placeholder="例如：差旅报销需要哪些材料？" className="h-11" />
            <Button onClick={run} disabled={retrieval.isPending || !query.trim()} className="h-11 shrink-0">{retrieval.isPending ? <Activity size={16} className="animate-spin" /> : <Search size={16} />}{retrieval.isPending ? "检索中" : "检索测试"}</Button>
          </div>
          <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-400"><span>试试：</span>{["这个知识库主要包含什么？", "报销需要哪些材料？", "有哪些适用范围？"].map((item) => <button key={item} onClick={() => setQuery(item)} className="hover:text-indigo-600">{item}</button>)}</div>
        </Card>

        {retrieval.isPending ? <LoadingResults /> : null}
        {retrieval.isError ? <Card className="border-red-100 p-5"><div className="flex gap-3"><FileSearch className="shrink-0 text-red-500" size={20} /><div><strong className="text-sm text-red-800">检索测试失败</strong><p className="mt-1 text-xs leading-5 text-red-600">{retrieval.error instanceof ApiError ? retrieval.error.message : "请检查 Embedding 与数据库连接后重试。"}</p></div></div></Card> : null}

        {result && !retrieval.isPending ? <>
          <Card className="p-5">
            <div className="flex items-start gap-3"><Sparkles size={18} className="mt-0.5 shrink-0 text-indigo-600" /><div><strong className="text-sm text-slate-900">本次执行详情</strong><p className="mt-1 text-xs leading-5 text-slate-500">Embedding {result.embedding_ms}ms · 混合召回 {result.retrieval_ms}ms · Rerank {result.rerank_ms}ms · 内部总耗时 {totalMs}ms</p></div></div>
          </Card>
          <div className="flex items-center justify-between gap-4"><div><h3 className="text-sm font-semibold text-slate-900">{result.results.length ? `检索到 ${result.results.length} 条证据` : "未找到有效证据"}</h3><p className="mt-1 text-xs text-slate-500">{result.results.length ? "结果已按融合或重排分数排序。" : "建议换用资料中出现的关键词，或检查文档是否已构建完成。"}</p></div>{result.results.length ? <Button variant="secondary" size="sm" onClick={exportResults}><ArrowDownToLine size={14} />导出 JSON</Button> : null}</div>
          {result.results.map((item, index) => <Card key={item.chunk_id} className="overflow-hidden"><div className="flex items-start gap-4 p-5"><span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-xs font-semibold text-slate-600">{index + 1}</span><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><strong className="text-sm font-semibold text-slate-800">{item.document_name}</strong><Badge tone="green"><CheckCircle2 size={11} className="mr-1" />检索命中</Badge></div><p className="mt-1 text-xs text-slate-400">{locationOf(item)}{item.title_path.length ? ` · ${item.title_path.join(" / ")}` : ""}</p><p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-600">{item.content}</p><div className="mt-4 flex flex-wrap gap-2"><Badge tone="cyan">语义 {score(item.semantic_score)}</Badge><Badge tone="slate">关键词 {score(item.keyword_score)}</Badge><Badge tone="amber">RRF {score(item.rrf_score)}</Badge>{item.rerank_score != null ? <Badge tone="indigo">重排 {score(item.rerank_score)}</Badge> : null}</div></div></div></Card>)}
        </> : null}
      </div>
    </div>
  );
}

function LoadingResults() {
  return <div className="space-y-3" aria-label="正在加载检索结果">{[1, 2, 3].map((item) => <Card key={item} className="p-5"><div className="flex gap-4"><div className="h-8 w-8 rounded-lg bg-slate-100 pulse-soft" /><div className="flex-1"><div className="h-4 w-40 rounded bg-slate-100 pulse-soft" /><div className="mt-3 h-3 w-full rounded bg-slate-100 pulse-soft" /><div className="mt-2 h-3 w-4/5 rounded bg-slate-100 pulse-soft" /></div></div></Card>)}</div>;
}
