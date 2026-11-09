"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, ArrowLeft, BookOpenCheck, Plus, RotateCcw, Search, ThumbsDown, ThumbsUp, Trash2 } from "lucide-react";
import { useState } from "react";
import { Badge, Button, Card, Drawer, EmptyState, Field, Input, Modal, Select, Textarea } from "@/components/ui/primitives";
import { RunDetailDrawer } from "@/components/run-detail-drawer";
import { JsonRecord, RunExecutionTranscript } from "@/components/run-execution-transcript";
import { ApiError, backendApi, type DatasetRead, type RunDetail, type SampleDetail } from "@/lib/api-client";
import type { Role } from "@/lib/types";

const stateLabels = { draft: "待补充", ready: "可评测", archived: "已归档" };
const message = (error: unknown) => error instanceof ApiError ? error.message : "读取或保存失败，请重试。";

export function DatasetsView({ role, initialDatasetId, onOpenLogs }: { role: Role; initialDatasetId?: string; onOpenLogs: () => void }) {
  const client = useQueryClient();
  const [selectedId, setSelectedId] = useState(initialDatasetId ?? "");
  const [caseId, setCaseId] = useState("");
  const [sourceRunId, setSourceRunId] = useState("");
  const [creating, setCreating] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<DatasetRead | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [label, setLabel] = useState("");
  const [state, setState] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const datasets = useQuery({ queryKey: ["datasets", role], queryFn: () => backendApi.listDatasets(role) });
  const selected = datasets.data?.find((dataset) => dataset.id === selectedId);
  const cases = useQuery({ queryKey: ["dataset-cases", role, selectedId, label, state, query, offset], queryFn: () => backendApi.listDatasetCases(role, selectedId, { label, state, query, offset }), enabled: Boolean(selectedId) });
  const detail = useQuery({ queryKey: ["dataset-case", role, selectedId, caseId], queryFn: () => backendApi.getDatasetCase(role, selectedId, caseId), enabled: Boolean(selectedId && caseId) });
  const source = useQuery({ queryKey: ["run-detail", role, sourceRunId], queryFn: () => backendApi.getRunDetail(role, sourceRunId), enabled: Boolean(sourceRunId) });
  const create = useMutation({ mutationFn: () => backendApi.createDataset(role, { name: name.trim(), description }), onSuccess: (dataset) => { setCreating(false); setName(""); setDescription(""); setSelectedId(dataset.id); void client.invalidateQueries({ queryKey: ["datasets"] }); } });
  const remove = useMutation({
    mutationFn: (id: string) => backendApi.deleteDataset(role, id),
    onSuccess: (_, id) => {
      setDeleteTarget(null);
      if (selectedId === id) { setCaseId(""); choose(""); }
      client.setQueryData<DatasetRead[]>(["datasets", role], (current) => current?.filter((dataset) => dataset.id !== id));
      client.removeQueries({ queryKey: ["dataset-cases", role, id] });
      client.removeQueries({ queryKey: ["dataset-case", role, id] });
      void client.invalidateQueries({ queryKey: ["datasets"] });
    },
  });
  function requestDelete(dataset: DatasetRead) { remove.reset(); setDeleteTarget(dataset); }
  function choose(id: string) { setSelectedId(id); setLabel(""); setState(""); setQuery(""); setOffset(0); }
  return <div className="space-y-6 fade-in">
    <div className="flex flex-wrap items-start justify-between gap-4"><div>{selectedId ? <Button variant="ghost" className="mb-2 px-0" onClick={() => choose("")}><ArrowLeft size={15} />全部评测集</Button> : null}<h2 className="text-xl font-semibold text-slate-900">{selectedId ? selected?.name ?? "评测集详情" : "评测集"}</h2><p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">{selectedId ? selected?.description || "从线上运行记录收录 Case，逐步补充参考答案和判定标准。" : "每天从使用日志中收录 Good / Bad Case，整理为独立的数据集。"}</p></div><div className="flex flex-wrap gap-2">{selected ? <Button variant="danger" onClick={() => requestDelete(selected)}><Trash2 size={15} />删除评测集</Button> : null}<Button variant="secondary" onClick={onOpenLogs}>去日志收录</Button><Button onClick={() => setCreating(true)}><Plus size={15} />新建评测集</Button></div></div>
    {datasets.error ? <ErrorNotice error={datasets.error} onRetry={() => void datasets.refetch()} /> : null}
    {!selectedId ? <>{datasets.isLoading ? <p className="p-8 text-sm text-slate-500">正在加载评测集…</p> : datasets.data?.length ? <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">{datasets.data.map((dataset) => <DatasetCard key={dataset.id} dataset={dataset} onOpen={() => choose(dataset.id)} onDelete={() => requestDelete(dataset)} />)}</div> : !datasets.isError ? <EmptyState icon={<BookOpenCheck size={24} />} title="还没有评测集" description="先创建一个评测集，再到运行日志中选择值得保留的 Good Case 和 Bad Case。" action={<Button onClick={() => setCreating(true)}>创建第一个评测集</Button>} /> : null}</> : <>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">{[["Good Case", selected?.good_count ?? 0], ["Bad Case", selected?.bad_count ?? 0], ["待补充", selected?.draft_count ?? 0], ["可评测", selected?.ready_count ?? 0]].map(([title, count]) => <Card key={title} className="p-4"><p className="text-xs text-slate-500">{title}</p><strong className="mt-2 block text-2xl text-slate-900">{count}</strong></Card>)}</div>
      <Card><div className="flex flex-wrap gap-3 border-b border-slate-100 p-4"><div className="relative min-w-48 flex-1"><Search size={15} className="absolute left-3 top-3 text-slate-400" /><Input aria-label="搜索 Case 问题" className="pl-9" placeholder="搜索问题" value={query} onChange={(event) => { setQuery(event.target.value); setOffset(0); }} /></div><Select aria-label="Case 标签筛选" className="w-36" value={label} onChange={(event) => { setLabel(event.target.value); setOffset(0); }}><option value="">全部标签</option><option value="good">Good Case</option><option value="bad">Bad Case</option></Select><Select aria-label="Case 状态筛选" className="w-36" value={state} onChange={(event) => { setState(event.target.value); setOffset(0); }}><option value="">未归档</option><option value="draft">待补充</option><option value="ready">可评测</option><option value="archived">已归档</option></Select></div>
        {cases.error ? <ErrorNotice error={cases.error} onRetry={() => void cases.refetch()} /> : cases.isLoading ? <p className="p-8 text-center text-sm text-slate-500">正在加载 Case…</p> : cases.data?.items.length ? <><div className="divide-y divide-slate-100">{cases.data.items.map((sample) => <button type="button" key={sample.id} className="block w-full p-5 text-left transition hover:bg-slate-50 focus-visible:outline-indigo-500" onClick={() => setCaseId(sample.id)}><div className="mb-3 flex flex-wrap items-center gap-2"><CaseLabel label={sample.label} /><Badge tone={sample.state === "ready" ? "indigo" : "amber"}>{stateLabels[sample.state]}</Badge><span className="ml-auto text-[11px] text-slate-400">{new Date(sample.created_at).toLocaleString("zh-CN")}</span></div><h3 className="line-clamp-2 text-sm font-medium text-slate-800">{sample.question}</h3><p className="mt-2 line-clamp-2 text-xs leading-6 text-slate-500">{sample.note || sample.answer || "该运行没有生成回答，可在详情中查看异常。"}</p></button>)}</div><div className="flex items-center justify-between border-t border-slate-100 p-4 text-xs text-slate-500"><span>共 {cases.data.total} 个 Case · 第 {Math.floor(offset / 50) + 1} 页</span><div className="flex gap-2"><Button variant="secondary" size="sm" disabled={!offset} onClick={() => setOffset(offset - 50)}>上一页</Button><Button variant="secondary" size="sm" disabled={offset + 50 >= cases.data.total} onClick={() => setOffset(offset + 50)}>下一页</Button></div></div></> : <EmptyState icon={<BookOpenCheck size={24} />} title={label || state || query ? "没有符合条件的 Case" : "还没有收录 Case"} description="在运行日志里点击 Good Case 或 Bad Case，选择本评测集即可收录。" action={<Button variant="secondary" onClick={onOpenLogs}>前往运行日志</Button>} />}
      </Card><p className="text-xs leading-6 text-slate-400">人工标签与运行状态分别记录。标记“可评测”只表示资料已准备好，当前模块不自动打分。</p>
    </>}
    <Modal open={creating} onOpenChange={(open) => { if (!create.isPending) setCreating(open); }} title="新建评测集" description="为日常整理的线上案例建立一个独立集合。"><form onSubmit={(event) => { event.preventDefault(); create.mutate(); }} className="space-y-5 overflow-y-auto p-6"><Field label="评测集名称"><Input required maxLength={100} value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：游戏客服线上精选" /></Field><Field label="说明" hint="选填"><Textarea maxLength={2000} rows={3} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="记录这个评测集的用途或收录范围" /></Field>{create.error ? <p role="alert" className="text-sm text-red-700">{message(create.error)}</p> : null}<div className="flex justify-end"><Button type="submit" disabled={!name.trim() || create.isPending}>{create.isPending ? "创建中…" : "创建评测集"}</Button></div></form></Modal>
    <Drawer open={Boolean(caseId)} onOpenChange={(open) => { if (!open) setCaseId(""); }} title="Case 详情" description="原始运行快照与人工标注分别保存。">{detail.isLoading ? <p className="p-6 text-sm text-slate-500">正在读取 Case…</p> : detail.error ? <ErrorNotice error={detail.error} onRetry={() => void detail.refetch()} /> : detail.data ? <CaseEditor key={`${detail.data.id}-${detail.data.revision}`} role={role} sample={detail.data} onSource={() => { setSourceRunId(detail.data!.source_run_id); setCaseId(""); }} /> : null}</Drawer>
    {sourceRunId ? <RunDetailDrawer role={role} log={source.data ?? null} loading={source.isLoading} error={source.error} onOpenChange={(open) => { if (!open) setSourceRunId(""); }} /> : null}
    <Modal open={deleteTarget !== null} onOpenChange={(open) => { if (!open && !remove.isPending) setDeleteTarget(null); }} title="删除评测集" description="删除前请确认评测集和其中的 Case 均不再需要。">
      <div className="space-y-4 overflow-y-auto p-6"><p className="break-words text-sm leading-7 text-slate-700">确定删除评测集 <strong className="text-slate-900">“{deleteTarget?.name}”</strong> 吗？</p><div className="rounded-xl border border-red-100 bg-red-50 p-4 text-sm leading-7 text-red-700">将永久删除此评测集及其中的 {(deleteTarget?.total_count ?? 0) + (deleteTarget?.archived_count ?? 0)} 个 Case（包含已归档 Case）、快照和标注。此操作不可恢复。</div><p className="text-xs leading-6 text-slate-500">来源运行日志和其他评测集中的 Case 会保留。</p>{remove.error ? <p role="alert" className="text-sm text-red-700">{message(remove.error)}</p> : null}<div className="flex justify-end gap-3"><Button variant="secondary" disabled={remove.isPending} onClick={() => setDeleteTarget(null)}>取消</Button><Button className="bg-red-600 hover:bg-red-700 disabled:bg-red-300" disabled={remove.isPending || !deleteTarget} onClick={() => { if (deleteTarget) remove.mutate(deleteTarget.id); }}><Trash2 size={14} />{remove.isPending ? "删除中…" : "确认删除"}</Button></div></div>
    </Modal>
  </div>;
}

function DatasetCard({ dataset, onOpen, onDelete }: { dataset: DatasetRead; onOpen: () => void; onDelete: () => void }) {
  return <Card className="flex h-full flex-col transition hover:border-indigo-300 hover:shadow-md">
    <button type="button" onClick={onOpen} className="block flex-1 rounded-xl p-6 pb-4 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500">
      <div className="flex items-center justify-between"><BookOpenCheck size={22} className="text-indigo-600" /><Badge>{dataset.total_count} 个 Case</Badge></div>
      <h3 className="mt-4 break-words text-base font-semibold text-slate-900">{dataset.name}</h3><p className="mt-2 line-clamp-2 min-h-10 text-xs leading-5 text-slate-500">{dataset.description || "从线上日志沉淀的人工精选案例"}</p>
      <div className="mt-5 flex flex-wrap gap-2"><Badge tone="green">Good {dataset.good_count}</Badge><Badge tone="red">Bad {dataset.bad_count}</Badge><Badge tone="amber">待补充 {dataset.draft_count}</Badge><Badge tone="indigo">可评测 {dataset.ready_count}</Badge></div>
    </button>
    <div className="flex flex-wrap items-center justify-between gap-2 px-6 pb-4"><p className="text-[11px] text-slate-400">创建于 {new Date(dataset.created_at).toLocaleDateString("zh-CN")} · 已归档 {dataset.archived_count}</p><Button variant="ghost" size="sm" className="text-red-600 hover:bg-red-50 hover:text-red-700" aria-label={`删除评测集 ${dataset.name}`} onClick={onDelete}><Trash2 size={14} />删除</Button></div>
  </Card>;
}

function CaseEditor({ role, sample, onSource }: { role: Role; sample: SampleDetail; onSource: () => void }) {
  const client = useQueryClient();
  const [label, setLabel] = useState(sample.label);
  const [note, setNote] = useState(sample.note);
  const [reference, setReference] = useState(sample.reference_answer);
  const [rubric, setRubric] = useState(sample.rubric);
  const [confirmed, setConfirmed] = useState(sample.ready_confirmed);
  const [ready, setReady] = useState(sample.state === "ready");
  const snapshotRun = sample.snapshot.run as RunDetail | undefined;
  const save = useMutation({ mutationFn: (state: "draft" | "ready" | "archived") => backendApi.updateDatasetCase(role, sample.dataset_id, sample.id, { revision: sample.revision, label, state, note, reference_answer: reference, rubric, ready_confirmed: confirmed }), onSuccess: () => { void client.invalidateQueries({ queryKey: ["dataset-case"] }); void client.invalidateQueries({ queryKey: ["dataset-cases"] }); void client.invalidateQueries({ queryKey: ["datasets"] }); } });
  const invalidReady = ready && (!confirmed || !(reference.trim() || rubric.trim()));
  return <div className="space-y-6 p-6">
    <div className="flex flex-wrap items-center justify-between gap-2"><div className="flex gap-2"><CaseLabel label={sample.label} /><Badge>{stateLabels[sample.state]}</Badge></div><span className="text-xs text-slate-400">标注版本 {sample.revision}</span></div>
    <section className="space-y-3 rounded-xl border border-slate-200 p-4"><h3 className="text-sm font-semibold text-slate-800">原始问答 · 只读快照</h3><p className="whitespace-pre-wrap break-words text-sm leading-7 text-slate-700">{sample.question}</p><div className="border-t border-slate-100 pt-3"><p className="text-xs text-slate-400">线上实际回答</p><p className="mt-2 whitespace-pre-wrap break-words text-sm leading-7 text-slate-700">{sample.answer || "该次运行没有生成回答。"}</p></div>{sample.source_available ? <Button size="sm" variant="secondary" onClick={onSource}>查看来源运行日志</Button> : <p className="text-xs text-amber-700">来源日志已不可用，收录时的独立快照仍可查看。</p>}</section>
    <section className="space-y-4"><h3 className="text-sm font-semibold text-slate-900">人工标注</h3><Field label="Case 标签"><Select value={label} onChange={(event) => setLabel(event.target.value as "good" | "bad")}><option value="good">Good Case</option><option value="bad">Bad Case</option></Select></Field><Field label="收录原因与备注"><Textarea rows={3} maxLength={10000} value={note} onChange={(event) => setNote(event.target.value)} /></Field><Field label="参考答案" hint="可稍后补充"><Textarea rows={5} maxLength={100000} value={reference} onChange={(event) => setReference(event.target.value)} placeholder="填写期望的正确回答" /></Field>{sample.answer ? <Button variant="ghost" size="sm" onClick={() => setReference(sample.answer)}>采用线上回答作参考</Button> : null}<Field label="判定标准" hint="可替代参考答案"><Textarea rows={3} maxLength={10000} value={rubric} onChange={(event) => setRubric(event.target.value)} placeholder="例如：必须引用规则中的扣分条件；没有依据时应明确拒答" /></Field><label className="flex items-start gap-2 text-sm leading-6 text-slate-600"><input type="checkbox" className="mt-1" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />我已检查参考答案或判定标准</label><label className="flex items-center gap-2 text-sm text-slate-700"><input type="checkbox" checked={ready} onChange={(event) => setReady(event.target.checked)} />标记为可评测</label>{invalidReady ? <p className="text-xs text-amber-700">请填写参考答案或判定标准，并完成检查确认。</p> : null}{save.error ? <p role="alert" className="text-sm text-red-700">{message(save.error)}</p> : null}<div className="flex flex-wrap gap-2"><Button disabled={save.isPending || invalidReady || sample.state === "archived"} onClick={() => save.mutate(ready ? "ready" : "draft")}>{save.isPending ? "保存中…" : "保存标注"}</Button>{sample.state === "archived" ? <Button variant="secondary" disabled={save.isPending} onClick={() => save.mutate("draft")}><RotateCcw size={14} />恢复为待补充</Button> : <Button variant="ghost" disabled={save.isPending} onClick={() => save.mutate("archived")}><Archive size={14} />归档 Case</Button>}</div></section>
    {snapshotRun?.error_message ? <div className="rounded-xl bg-red-50 p-4 text-sm text-red-700"><strong>{snapshotRun.error_code}</strong><p className="mt-1">{snapshotRun.error_message}</p></div> : null}
    {snapshotRun ? <><RunExecutionTranscript log={snapshotRun} /><details className="rounded-xl border border-slate-200 p-4"><summary className="cursor-pointer text-sm text-slate-700">引用与检索快照</summary><div className="mt-3"><JsonRecord value={{ citations: snapshotRun.citations, retrieval_results: snapshotRun.retrieval_results }} /></div></details></> : null}
    <details className="rounded-xl border border-slate-200 p-4"><summary className="cursor-pointer text-sm text-slate-700">完整收录快照与历史对话</summary><div className="mt-3"><JsonRecord value={sample.snapshot} /></div></details>
  </div>;
}

function CaseLabel({ label }: { label: "good" | "bad" }) { return <Badge tone={label === "good" ? "green" : "red"}>{label === "good" ? <ThumbsUp size={11} className="mr-1" /> : <ThumbsDown size={11} className="mr-1" />}{label === "good" ? "Good Case" : "Bad Case"}</Badge>; }
function ErrorNotice({ error, onRetry }: { error: unknown; onRetry: () => void }) { return <div role="alert" className="flex items-center justify-between gap-4 rounded-xl border border-red-100 bg-red-50 p-5 text-sm text-red-700"><p>{message(error)}</p><Button variant="secondary" size="sm" onClick={onRetry}>重试</Button></div>; }
