"use client";

import { useQuery } from "@tanstack/react-query";
import { FileText, FolderOpen, Layers3, RefreshCw } from "lucide-react";
import { useState } from "react";
import { Badge, Button, EmptyState, Modal, Select } from "@/components/ui/primitives";
import { DocumentPreview, type DocumentPreviewTarget } from "@/components/knowledge/document-preview";
import { ApiError, backendApi, type KnowledgeBaseRead } from "@/lib/api-client";
import type { Role } from "@/lib/types";

export function KnowledgeBrowser({ role, bases, initialTab, onClose, onManage }: {
  role: Role; bases: KnowledgeBaseRead[]; initialTab: "documents" | "chunks";
  onClose: () => void; onManage: () => void;
}) {
  const [tab, setTab] = useState(initialTab);
  const [selectedId, setSelectedId] = useState(bases[0]?.id ?? "");
  const [offset, setOffset] = useState(0);
  const [preview, setPreview] = useState<DocumentPreviewTarget | null>(null);
  const baseId = selectedId || bases[0]?.id || "";
  const documentsQuery = useQuery({ queryKey: ["knowledge-documents", role, baseId, false], queryFn: () => backendApi.listDocuments(role, baseId), enabled: Boolean(baseId) && tab === "documents" });
  const chunksQuery = useQuery({ queryKey: ["knowledge-chunks", role, baseId, offset], queryFn: () => backendApi.listChunks(role, baseId, offset), enabled: Boolean(baseId) && tab === "chunks" });
  const activeQuery = tab === "documents" ? documentsQuery : chunksQuery;
  return <>
    <Modal open onOpenChange={(open) => { if (!open) onClose(); }} title={tab === "documents" ? "知识库文件" : "知识分块与来源文件"} description="选择知识库，点击文件名或分块查看完整文件内容。" className="max-w-5xl">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-6 py-3">
        <div className="flex gap-2"><Button variant={tab === "documents" ? "secondary" : "ghost"} size="sm" onClick={() => setTab("documents")}><FileText size={14} />文件</Button><Button variant={tab === "chunks" ? "secondary" : "ghost"} size="sm" onClick={() => setTab("chunks")}><Layers3 size={14} />分块</Button></div>
        <Select aria-label="选择要查看的知识库" value={baseId} className="max-w-sm" onChange={(event) => { setSelectedId(event.target.value); setOffset(0); }}>{!bases.length ? <option value="">暂无知识库</option> : null}{bases.map((base) => <option key={base.id} value={base.id}>{base.name} · {base.document_count} 份文件 · {base.chunk_count} 个分块</option>)}</Select>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-6">
        {!baseId ? <EmptyState icon={<FolderOpen size={24} />} title="暂无知识库" description="新建知识库并导入资料后，即可在这里查看文件和内容。" /> : activeQuery.isError ? <div role="alert" className="rounded-lg bg-red-50 p-4 text-sm text-red-700">{activeQuery.error instanceof ApiError ? activeQuery.error.message : "加载失败，请重试。"}<Button variant="ghost" size="sm" onClick={() => { void activeQuery.refetch(); }}><RefreshCw size={13} />重试</Button></div> : activeQuery.isLoading ? <p role="status" className="py-10 text-center text-sm text-slate-400">正在加载{tab === "documents" ? "文件" : "分块"}…</p> : tab === "documents" ? <div className="divide-y divide-slate-100">
          {(documentsQuery.data ?? []).map((doc) => <button type="button" key={doc.id} aria-label={`查看文件 ${doc.name}`} onClick={() => setPreview({ knowledgeBaseId: baseId, documentId: doc.id, versionNumber: doc.latest_version_number, documentName: doc.name })} className="group flex w-full items-center gap-3 rounded-lg px-3 py-4 text-left transition hover:bg-indigo-50/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"><span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600"><FileText size={18} /></span><span className="min-w-0 flex-1"><strong className="block break-words text-sm font-medium text-slate-800 group-hover:text-indigo-600">{doc.name}</strong><small className="mt-1 block text-xs text-slate-400">{doc.source_type.toUpperCase()} · V{doc.latest_version_number} · {Math.max(1, Math.round(doc.size_bytes / 1024))} KB</small></span><span className="shrink-0 text-xs text-indigo-600">查看内容</span></button>)}
          {documentsQuery.data?.length === 0 ? <EmptyState icon={<FolderOpen size={24} />} title="这个知识库还没有文件" description="导入资料后，点击文件名即可查看内容。" /> : null}
        </div> : <div className="space-y-3">
          {(chunksQuery.data?.items ?? []).map((chunk) => <button type="button" key={chunk.id} aria-label={`查看分块 ${chunk.ordinal + 1} ${chunk.document_name}`} onClick={() => setPreview({ chunkId: chunk.id, documentName: chunk.document_name, excerpt: chunk.content })} className="block w-full rounded-xl border border-slate-200 p-4 text-left transition hover:border-indigo-200 hover:bg-indigo-50/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"><span className="flex flex-wrap items-center gap-2"><Badge tone="indigo">分块 {chunk.ordinal + 1}</Badge><strong className="text-sm font-medium text-indigo-700">{chunk.document_name}</strong><span className="text-xs text-slate-400">V{chunk.document_version} · {chunk.token_count} Tokens</span></span><p className="mt-3 line-clamp-4 whitespace-pre-wrap text-sm leading-6 text-slate-600">{chunk.content}</p><span className="mt-3 block text-xs text-indigo-500">查看来源文件及完整内容</span></button>)}
          {chunksQuery.data?.items.length === 0 ? <EmptyState icon={<Layers3 size={24} />} title="暂无知识分块" description="完成文件解析与索引后，即可查看分块与来源文件。" /> : null}
          {(chunksQuery.data?.total ?? 0) > 50 ? <div className="flex items-center justify-end gap-3"><Button variant="secondary" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>上一页</Button><span className="text-xs text-slate-400">第 {Math.floor(offset / 50) + 1} 页 · {chunksQuery.data?.total} 个分块</span><Button variant="secondary" size="sm" disabled={offset + 50 >= (chunksQuery.data?.total ?? 0)} onClick={() => setOffset(offset + 50)}>下一页</Button></div> : null}
        </div>}
      </div>
      <div className="flex shrink-0 justify-between border-t border-slate-100 px-6 py-4"><Button variant="ghost" onClick={onManage}>管理知识库</Button><Button variant="secondary" onClick={onClose}>关闭列表</Button></div>
    </Modal>
    {preview ? <DocumentPreview target={preview} role={role} onClose={() => setPreview(null)} /> : null}
  </>;
}
