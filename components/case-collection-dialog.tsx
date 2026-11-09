"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ThumbsDown, ThumbsUp } from "lucide-react";
import { Badge, Button, Field, Input, Modal, Select, Textarea } from "@/components/ui/primitives";
import { ApiError, backendApi, type RunRead } from "@/lib/api-client";
import type { Role } from "@/lib/types";

export function CaseCollectionDialog({ role, run, initialLabel, onClose, onOpenDataset }: {
  role: Role; run: RunRead; initialLabel: "good" | "bad"; onClose: () => void; onOpenDataset: (id: string) => void;
}) {
  const client = useQueryClient();
  const datasets = useQuery({ queryKey: ["datasets", role], queryFn: () => backendApi.listDatasets(role) });
  const [datasetId, setDatasetId] = useState("");
  const [label, setLabel] = useState(initialLabel);
  const [scope, setScope] = useState<"turn" | "history">("turn");
  const [note, setNote] = useState("");
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const selectedId = datasetId || datasets.data?.[0]?.id || "";
  const create = useMutation({
    mutationFn: () => backendApi.createDataset(role, { name: name.trim(), description: "" }),
    onSuccess: (dataset) => { setDatasetId(dataset.id); setCreating(false); setName(""); void client.invalidateQueries({ queryKey: ["datasets"] }); },
  });
  const collect = useMutation({
    mutationFn: () => backendApi.captureCase(role, selectedId, { source_run_id: run.id, label, scope, note }),
    onSuccess: () => { void client.invalidateQueries({ queryKey: ["datasets"] }); void client.invalidateQueries({ queryKey: ["dataset-cases"] }); },
  });
  const error = datasets.error ?? create.error ?? collect.error;
  return <Modal open onOpenChange={(open) => { if (!open && !collect.isPending && !create.isPending) onClose(); }} title="收录到评测集" description="保存本次运行的独立快照，供日常整理和后续评测使用。">
    <div className="space-y-5 overflow-y-auto p-6">
      {collect.data ? <div className="space-y-4 rounded-xl border border-emerald-200 bg-emerald-50 p-5" role="status"><strong className="block text-emerald-800">{collect.data.already_exists ? "该运行已在此评测集中" : "已收录，状态为待补充"}</strong><p className="text-sm leading-6 text-emerald-700">{collect.data.already_exists ? "保留已有标签和批注，可在评测集中继续编辑。" : "已保存问题、回答、引用、配置和现有执行步骤。参考答案可稍后补充。"}</p><Button onClick={() => onOpenDataset(collect.data!.sample.dataset_id)}>查看评测集</Button><Button variant="ghost" onClick={onClose}>继续查看日志</Button></div> : <>
        <div className="rounded-xl bg-slate-50 p-4"><div className="mb-2 flex gap-2"><Badge>{run.request_id}</Badge><Badge>{run.status}</Badge></div><p className="line-clamp-3 whitespace-pre-wrap text-sm leading-6 text-slate-700">{run.query_text}</p></div>
        <div className="grid grid-cols-2 gap-3"><Button variant={label === "good" ? "primary" : "secondary"} aria-pressed={label === "good"} onClick={() => setLabel("good")}><ThumbsUp size={15} />Good Case</Button><Button variant={label === "bad" ? "primary" : "secondary"} aria-pressed={label === "bad"} onClick={() => setLabel("bad")}><ThumbsDown size={15} />Bad Case</Button></div>
        <Field label="目标评测集"><Select value={selectedId} onChange={(event) => setDatasetId(event.target.value)} disabled={datasets.isLoading}><option value="">{datasets.isLoading ? "正在加载…" : "请选择评测集"}</option>{datasets.data?.map((dataset) => <option key={dataset.id} value={dataset.id}>{dataset.name}</option>)}</Select></Field>
        {creating || (!datasets.isLoading && !datasets.isError && !datasets.data?.length) ? <div className="space-y-3 rounded-lg border border-indigo-100 bg-indigo-50/40 p-4"><Field label="新评测集名称"><Input value={name} maxLength={100} onChange={(event) => setName(event.target.value)} placeholder="例如：游戏客服线上精选" /></Field><Button size="sm" disabled={!name.trim() || create.isPending} onClick={() => create.mutate()}>{create.isPending ? "创建中…" : "创建并选中"}</Button></div> : <Button variant="ghost" size="sm" onClick={() => setCreating(true)}>＋ 新建评测集</Button>}
        <Field label="收录范围"><Select value={scope} onChange={(event) => setScope(event.target.value as "turn" | "history")}><option value="turn">本次问答</option><option value="history">本次问答及之前的对话（最多 20 条）</option></Select></Field>
        <Field label="收录原因" hint="选填"><Textarea rows={3} maxLength={10000} value={note} onChange={(event) => setNote(event.target.value)} placeholder="记录表现好的地方，或需要修复的问题" /></Field>
        <p className="text-xs leading-5 text-slate-500">Good / Bad 是你的人工判断，与运行成功或失败分别记录。收录不会重新运行助手，也不会调用模型。</p>
      </>}
      {error ? <p role="alert" className="text-sm text-red-700">{error instanceof ApiError ? error.message : "读取或保存失败，请重试。"}{datasets.isError ? <Button variant="ghost" size="sm" onClick={() => void datasets.refetch()}>重新加载</Button> : null}</p> : null}
    </div>
    {!collect.data ? <div className="flex justify-end gap-3 border-t border-slate-100 px-6 py-4"><Button variant="secondary" onClick={onClose} disabled={collect.isPending}>取消</Button><Button disabled={!selectedId || collect.isPending || create.isPending} onClick={() => collect.mutate()}>{collect.isPending ? "收录中…" : "确认收录"}</Button></div> : null}
  </Modal>;
}
