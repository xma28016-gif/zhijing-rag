"use client";

import * as Tabs from "@radix-ui/react-tabs";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity, AlertTriangle, ArrowLeft, CheckCircle2, ChevronRight,
  CircleAlert, Database, FilePlus2, Files, FileText, FolderOpen,
  Layers3, Plus, RefreshCw, Search, Settings, Trash2, UploadCloud,
} from "lucide-react";
import { useState } from "react";
import { ImportWizard } from "@/components/knowledge/import-wizard";
import { CreateKnowledgeBaseDialog } from "@/components/knowledge/create-knowledge-base-dialog";
import { DocumentPreview, type DocumentPreviewTarget } from "@/components/knowledge/document-preview";
import { TaskResume } from "@/components/knowledge/task-resume";
import { RetrievalTest } from "@/components/knowledge/retrieval-test";
import {
  Badge, Button, Card, EmptyState, Field, Input, Modal, Select, Textarea,
} from "@/components/ui/primitives";
import {
  ApiError, backendApi, type BuildTaskDetailRead, type DocumentRead,
  type KnowledgeBaseRead,
} from "@/lib/api-client";
import type { KnowledgeBase, Role } from "@/lib/types";
import { formatNumber } from "@/lib/utils";

const tabs = [
  { id: "documents", label: "文档", icon: Files },
  { id: "chunks", label: "分块", icon: Layers3 },
  { id: "retrieval", label: "检索测试", icon: Search },
  { id: "tasks", label: "构建任务", icon: Activity },
  { id: "settings", label: "设置", icon: Settings },
];

const knowledgeTones = ["bg-indigo-600", "bg-cyan-600", "bg-violet-600", "bg-emerald-600"];

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  }).format(new Date(value));
}

function formatBytes(value: number) {
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(value / 1024))} KB`;
}

function toViewModel(record: KnowledgeBaseRead): KnowledgeBase {
  const seed = [...record.name].reduce((total, char) => total + char.charCodeAt(0), 0);
  return {
    id: record.id,
    name: record.name,
    description: record.description ?? "暂无用途说明",
    icon: record.name.slice(0, 1),
    tone: knowledgeTones[seed % knowledgeTones.length],
    documents: record.document_count,
    chunks: record.chunk_count,
    updatedAt: formatDate(record.updated_at),
    embedding: `Embedding · ${record.embedding_dimension ?? "未知"} 维`,
    state: record.status,
  };
}

function ErrorCard({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return <Card className="flex items-center justify-between gap-4 border-red-100 p-5">
    <div><strong className="text-sm text-red-800">数据加载失败</strong><p className="mt-1 text-xs text-red-600">{error instanceof ApiError ? error.message : "请检查后端服务并重试。"}</p></div>
    <Button variant="secondary" size="sm" onClick={onRetry}><RefreshCw size={14} />重试</Button>
  </Card>;
}

export function KnowledgeView({ role, notify }: { role: Role; notify: (title: string, description?: string) => void }) {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<KnowledgeBaseRead | null>(null);
  const [deleteError, setDeleteError] = useState("");
  const knowledgeQuery = useQuery({
    queryKey: ["knowledge-bases", role],
    queryFn: () => backendApi.listKnowledgeBases(role),
    refetchInterval: (query) => query.state.data?.some((item) => item.status === "building") ? 2_000 : false,
  });
  const deleteMutation = useMutation({
    mutationFn: (id: string) => backendApi.deleteKnowledgeBase(role, id),
    onSuccess: async (result, id) => {
      queryClient.setQueriesData<KnowledgeBaseRead[]>({ queryKey: ["knowledge-bases"] }, (current) => current?.filter((item) => item.id !== id));
      queryClient.removeQueries({ predicate: (query) => query.queryKey.includes(id) });
      setDeleteTarget(null);
      setDeleteError("");
      notify("知识库已删除", result.storage_cleanup_complete ? "关联文档、分块和构建任务已清理。" : "部分原文件清理失败，请联系管理员查看后台日志。");
      await queryClient.invalidateQueries();
    },
    onError: (error) => setDeleteError(error instanceof ApiError ? error.message : "删除知识库失败，请重试。"),
  });
  const allRecords = knowledgeQuery.data ?? [];
  const records = allRecords.filter((item) => (!search || `${item.name} ${item.description ?? ""}`.toLowerCase().includes(search.toLowerCase())) && (!status || item.status === status));
  const selectedRecord = allRecords.find((item) => item.id === selectedId) ?? null;

  function openCreateKnowledgeBase() {
    setCreateOpen(true);
  }

  if (selectedRecord) {
    return <KnowledgeDetail
      role={role}
      record={selectedRecord}
      knowledgeBase={toViewModel(selectedRecord)}
      onBack={() => setSelectedId(null)}
      importOpen={importOpen}
      onImportOpen={setImportOpen}
      notify={notify}
    />;
  }

  return <div className="space-y-6 fade-in">
    <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
      <div><h2 className="text-xl font-semibold text-slate-900">知识库</h2><p className="mt-1 text-sm text-slate-500">每个知识库使用固定 Embedding 空间，文档构建完成后即可用于检索和问答。</p></div>
      <Button onClick={openCreateKnowledgeBase}><Plus size={16} />新建知识库</Button>
    </div>
    {knowledgeQuery.isError ? <ErrorCard error={knowledgeQuery.error} onRetry={() => { void knowledgeQuery.refetch(); }} /> : null}
    <div className="flex flex-col gap-3 sm:flex-row">
      <div className="relative flex-1"><Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" /><Input aria-label="搜索知识库" placeholder="搜索知识库" className="pl-9" value={search} onChange={(e) => setSearch(e.target.value)} /></div>
      <Select aria-label="知识库状态筛选" className="sm:w-40" value={status} onChange={(e) => setStatus(e.target.value)}><option value="">全部状态</option><option value="ready">可用</option><option value="building">构建中</option><option value="failed">构建失败</option><option value="empty">空知识库</option></Select>
      <Button variant="secondary" onClick={() => { void knowledgeQuery.refetch(); }}><RefreshCw size={15} />刷新</Button>
    </div>
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      {knowledgeQuery.isLoading ? [1, 2, 3].map((item) => <Card key={item} className="min-h-64 animate-pulse bg-slate-50"><span className="sr-only">正在加载知识库</span></Card>) : records.map((record) => {
        const base = toViewModel(record);
        return <Card key={base.id} className="group flex h-full flex-col transition hover:-translate-y-0.5 hover:border-indigo-200 hover:shadow-lg">
          <button type="button" onClick={() => setSelectedId(base.id)} aria-label={`打开知识库 ${base.name}`} className="flex-1 rounded-xl p-5 pb-0 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500">
            <div className="flex items-start gap-4">
              <span className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-sm font-semibold text-white ${base.tone}`}>{base.icon}</span>
              <div className="min-w-0 flex-1"><div className="flex items-center gap-2"><h3 className="truncate font-semibold text-slate-900">{base.name}</h3><StateBadge state={base.state} /></div><p className="mt-1 line-clamp-2 min-h-10 text-xs leading-5 text-slate-500">{base.description}</p></div>
              <ChevronRight size={17} className="text-slate-300 transition group-hover:translate-x-0.5 group-hover:text-indigo-500" />
            </div>
            <div className="mt-5 grid grid-cols-2 gap-3"><div className="rounded-lg bg-slate-50 px-3 py-2.5"><strong className="block text-base text-slate-800">{base.documents}</strong><span className="text-[11px] text-slate-400">文档</span></div><div className="rounded-lg bg-slate-50 px-3 py-2.5"><strong className="block text-base text-slate-800">{formatNumber(base.chunks)}</strong><span className="text-[11px] text-slate-400">知识分块</span></div></div>
          </button>
          <div className="mx-5 mb-4 mt-4 flex flex-wrap items-center gap-3 border-t border-slate-100 pt-3 text-[11px] text-slate-400">
            <span className="min-w-0 flex-1 truncate">{base.embedding}</span><span className="shrink-0">{base.updatedAt}</span>
            <Button variant="danger" size="sm" aria-label={`删除知识库 ${base.name}`} onClick={() => { setDeleteError(""); setDeleteTarget(record); }}><Trash2 size={14} />删除</Button>
          </div>
        </Card>;
      })}
      {!knowledgeQuery.isLoading && !knowledgeQuery.isError ? <button onClick={openCreateKnowledgeBase} className="min-h-64 rounded-xl border border-dashed border-slate-300 bg-white/40 p-6 text-center transition hover:border-indigo-400 hover:bg-indigo-50/30"><span className="mx-auto flex h-11 w-11 items-center justify-center rounded-xl bg-slate-100 text-slate-500"><Plus size={20} /></span><strong className="mt-4 block text-sm text-slate-700">新建知识库</strong><span className="mt-1 block text-xs text-slate-400">选择 Embedding 并开始导入资料</span></button> : null}
    </div>
    <Modal open={deleteTarget !== null} onOpenChange={(open) => { if (!open && !deleteMutation.isPending) setDeleteTarget(null); }} title="删除知识库" description="删除整个知识库后无法撤销，请确认后再操作。">
      <div className="space-y-4 px-6 py-5">
        <p className="break-words text-sm leading-6 text-slate-700">确定删除知识库 <strong className="text-slate-900">“{deleteTarget?.name}”</strong> 吗？</p>
        <div className="rounded-xl border border-red-100 bg-red-50 p-4 text-xs leading-6 text-red-800">将永久删除全部文档（含已删除文档）、知识分块、索引和构建任务，并清理原文件。历史对话记录保留。</div>
        <p className="text-xs leading-5 text-slate-500">若该知识库已被助手引用，请先在助手设置中解除绑定。</p>
        {deleteError ? <div role="alert" className="rounded-xl bg-red-50 p-4 text-xs text-red-700">{deleteError}</div> : null}
      </div>
      <div className="flex justify-end gap-2 border-t border-slate-100 px-6 py-4"><Button variant="ghost" disabled={deleteMutation.isPending} onClick={() => setDeleteTarget(null)}>取消</Button><Button variant="danger" disabled={deleteMutation.isPending || !deleteTarget} onClick={() => { if (deleteTarget) deleteMutation.mutate(deleteTarget.id); }}>{deleteMutation.isPending ? <Activity size={15} className="animate-spin" /> : <Trash2 size={15} />}{deleteMutation.isPending ? "正在删除…" : "确认删除"}</Button></div>
    </Modal>
    {createOpen ? <CreateKnowledgeBaseDialog role={role} onClose={() => setCreateOpen(false)} onCreated={(created) => {
      setCreateOpen(false);
      setSelectedId(created.id);
      setImportOpen(true);
      notify("知识库已创建", "请选择要导入的资料。");
    }} /> : null}
  </div>;
}

function KnowledgeDetail({ role, record, knowledgeBase, onBack, importOpen, onImportOpen, notify }: {
  role: Role; record: KnowledgeBaseRead; knowledgeBase: KnowledgeBase; onBack: () => void;
  importOpen: boolean; onImportOpen: (open: boolean) => void;
  notify: (title: string, description?: string) => void;
}) {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState("documents");
  const [chunkOffset, setChunkOffset] = useState(0);
  const [showDeleted, setShowDeleted] = useState(false);
  const [preview, setPreview] = useState<DocumentPreviewTarget | null>(null);
  const documentsQuery = useQuery({ queryKey: ["knowledge-documents", role, record.id, showDeleted], queryFn: () => backendApi.listDocuments(role, record.id, showDeleted), refetchInterval: record.status === "building" ? 2_000 : false });
  const chunksQuery = useQuery({ queryKey: ["knowledge-chunks", role, record.id, chunkOffset], queryFn: () => backendApi.listChunks(role, record.id, chunkOffset), enabled: activeTab === "chunks" });
  const tasksQuery = useQuery({ queryKey: ["knowledge-tasks", role, record.id], queryFn: () => backendApi.listBuildTasks(role, record.id), enabled: activeTab === "tasks", refetchInterval: (query) => query.state.data?.some((task) => ["queued", "parsing", "preview_ready", "indexing", "replacing"].includes(task.status)) ? 2_000 : false });

  async function refreshKnowledge() {
    setChunkOffset(0);
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["knowledge-bases"] }),
      queryClient.invalidateQueries({ queryKey: ["knowledge-documents"] }),
      queryClient.invalidateQueries({ queryKey: ["knowledge-chunks"] }),
      queryClient.invalidateQueries({ queryKey: ["knowledge-tasks"] }),
    ]);
  }

  return <div className="space-y-5 fade-in">
    <div className="flex flex-col gap-4">
      <button onClick={onBack} className="flex w-fit items-center gap-2 text-sm text-slate-500 hover:text-slate-900"><ArrowLeft size={16} />返回知识库</button>
      <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-center">
        <div className="flex items-start gap-4"><span className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-xl text-sm font-semibold text-white ${knowledgeBase.tone}`}>{knowledgeBase.icon}</span><div><div className="flex items-center gap-2"><h2 className="text-xl font-semibold text-slate-900">{knowledgeBase.name}</h2><StateBadge state={knowledgeBase.state} /></div><p className="mt-1 text-sm text-slate-500">{knowledgeBase.description}</p><div className="mt-2 flex flex-wrap gap-3 text-xs text-slate-400"><span>{knowledgeBase.documents} 个文档</span><span>·</span><span>{formatNumber(knowledgeBase.chunks)} 个分块</span><span>·</span><span>{knowledgeBase.embedding}</span></div></div></div>
        <Button onClick={() => onImportOpen(true)}><UploadCloud size={16} />导入资料</Button>
      </div>
    </div>
    <Tabs.Root value={activeTab} onValueChange={setActiveTab}>
      <Tabs.List className="flex gap-1 overflow-x-auto rounded-xl border border-slate-200 bg-white p-1.5 panel-shadow" aria-label="知识库详情导航">{tabs.map((tab) => { const Icon = tab.icon; return <Tabs.Trigger key={tab.id} value={tab.id} className="inline-flex h-9 shrink-0 items-center gap-2 rounded-lg px-3.5 text-sm font-medium text-slate-500 outline-none transition hover:text-slate-800 data-[state=active]:bg-indigo-50 data-[state=active]:text-indigo-700"><Icon size={15} />{tab.label}</Tabs.Trigger>; })}</Tabs.List>
      <Tabs.Content value="documents" className="mt-5 outline-none"><DocumentsPanel query={documentsQuery} role={role} knowledgeBaseId={record.id} showDeleted={showDeleted} onShowDeleted={setShowDeleted} onChanged={refreshKnowledge} notify={notify} onPreview={(doc) => setPreview({ knowledgeBaseId: record.id, documentId: doc.id, versionNumber: doc.latest_version_number, documentName: doc.name })} /></Tabs.Content>
      <Tabs.Content value="chunks" className="mt-5 outline-none"><ChunksPanel query={chunksQuery} onImport={() => onImportOpen(true)} onPreview={(chunk) => setPreview({ chunkId: chunk.id, documentName: chunk.document_name, excerpt: chunk.content })} /><div className="mt-4 flex items-center justify-end gap-3"><Button variant="secondary" disabled={chunkOffset === 0} onClick={() => setChunkOffset(Math.max(0, chunkOffset - 50))}>上一页</Button><span className="text-xs text-slate-500">第 {Math.floor(chunkOffset / 50) + 1} 页 · 共 {chunksQuery.data?.total ?? 0} 个分块</span><Button variant="secondary" disabled={chunkOffset + 50 >= (chunksQuery.data?.total ?? 0)} onClick={() => setChunkOffset(chunkOffset + 50)}>下一页</Button></div></Tabs.Content>
      <Tabs.Content value="retrieval" className="mt-5 outline-none">{record.chunk_count ? <RetrievalTest knowledgeBaseId={record.id} role={role} /> : <EmptyState icon={<Search size={22} />} title="需要先构建知识" description="至少完成一个文档的解析与索引后，才能验证召回和重排结果。" />}</Tabs.Content>
      <Tabs.Content value="tasks" className="mt-5 outline-none"><TasksPanel role={role} query={tasksQuery} notify={notify} /></Tabs.Content>
      <Tabs.Content value="settings" className="mt-5 outline-none"><SettingsPanel key={record.updated_at} record={record} role={role} notify={notify} /></Tabs.Content>
    </Tabs.Root>
    {preview ? <DocumentPreview target={preview} role={role} onClose={() => setPreview(null)} /> : null}
    <ImportWizard
      open={importOpen}
      onOpenChange={onImportOpen}
      knowledgeBaseId={record.id}
      maxFileSize={record.file_size_limit_bytes}
      batchFileLimit={record.batch_file_limit}
      tableOnly={record.knowledge_base_type === "table"}
      role={role}
      onComplete={async (files) => {
        await refreshKnowledge();
        notify("知识库构建已结束", `${files.length} 个文件的最新状态已同步。`);
      }}
    />
  </div>;
}

type DocumentsQuery = ReturnType<typeof useQuery<DocumentRead[]>>;

function DocumentsPanel({ query, role, knowledgeBaseId, showDeleted, onShowDeleted, onChanged, notify, onPreview }: {
  query: DocumentsQuery; role: Role; knowledgeBaseId: string; showDeleted: boolean;
  onShowDeleted: (value: boolean) => void; onChanged: () => Promise<void>; onPreview: (document: DocumentRead) => void;
  notify: (title: string, description?: string) => void;
}) {
  const [selected, setSelected] = useState<DocumentRead | null>(null);
  const [error, setError] = useState("");
  const deletion = useMutation({
    mutationFn: (id: string) => backendApi.deleteDocument(role, knowledgeBaseId, id),
    onSuccess: async () => {
      setSelected(null);
      await onChanged();
      notify("文档已删除", "相关分块已停止检索，可在“已删除”列表恢复。");
    },
    onError: (failure) => setError(failure instanceof ApiError ? failure.message : "删除失败，请重试。"),
  });
  const restoration = useMutation({
    mutationFn: (id: string) => backendApi.restoreDocument(role, knowledgeBaseId, id),
    onSuccess: async () => {
      await onChanged();
      notify("文档已恢复", "已完成索引的版本恢复检索；未完成的任务可在构建任务中重试。");
    },
    onError: (failure) => setError(failure instanceof ApiError ? failure.message : "恢复失败，请重试。"),
  });
  const busy = deletion.isPending || restoration.isPending;
  const rows = query.data ?? [];
  return <div className="space-y-3">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <p className="text-xs text-slate-500">{showDeleted ? "已删除文档停止参与检索，原文件保留，可随时恢复。" : "管理导入的文件；删除会同步停用该文档所有版本的检索分块。"}</p>
      <div className="flex gap-2">
        <Button size="sm" variant={showDeleted ? "ghost" : "secondary"} aria-pressed={!showDeleted} disabled={busy} onClick={() => { setError(""); onShowDeleted(false); }}>当前文档</Button>
        <Button size="sm" variant={showDeleted ? "secondary" : "ghost"} aria-pressed={showDeleted} disabled={busy} onClick={() => { setError(""); onShowDeleted(true); }}><Trash2 size={14} />已删除</Button>
      </div>
    </div>
    {error && !selected ? <p role="alert" className="rounded-xl bg-red-50 p-4 text-sm text-red-700">{error}</p> : null}
    {query.isError ? <ErrorCard error={query.error} onRetry={() => { void query.refetch(); }} />
      : query.isLoading ? <Card className="h-56 animate-pulse bg-slate-50"><span className="sr-only">正在加载文档</span></Card>
      : !rows.length ? <EmptyState icon={<FolderOpen size={22} />} title={showDeleted ? "没有已删除的文档" : "还没有导入资料"} description={showDeleted ? "删除的文件会显示在这里，可按需恢复。" : "上传 Word、PDF、Markdown、表格或图片，先检查解析分块，再开始构建知识库。"} />
      : <Card><div className="overflow-x-auto"><table className="w-full min-w-[860px] text-left">
        <thead><tr className="border-b border-slate-100 bg-slate-50/60 text-[11px] font-medium text-slate-400">
          <th className="px-5 py-3">文档</th><th className="px-4 py-3">解析方式</th><th className="px-4 py-3">版本</th><th className="px-4 py-3">状态</th><th className="px-4 py-3">{showDeleted ? "删除时间" : "更新时间"}</th><th className="sticky right-0 bg-slate-50 px-4 py-3 text-right">操作</th>
        </tr></thead>
        <tbody className="divide-y divide-slate-100">{rows.map((document) => <tr key={document.id} className="hover:bg-slate-50/60">
          <td className="px-5 py-4"><div className="flex items-center gap-3"><span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600"><FileText size={17} /></span><span><button type="button" aria-label={`查看文件 ${document.name}`} onClick={() => onPreview(document)} className="block max-w-sm truncate rounded text-left text-sm font-medium text-indigo-700 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500" title={document.name}>{document.name}</button><small className="text-xs text-slate-400">{document.source_type.toUpperCase()} · {formatBytes(document.size_bytes)}</small></span></div></td>
          <td className="px-4 py-4"><Badge tone={document.parser_kind === "docmind" ? "indigo" : "slate"}>{document.parser_kind === "docmind" ? "云端增强" : "本地解析"}</Badge></td>
          <td className="px-4 py-4 text-sm text-slate-600">V{document.latest_version_number}</td>
          <td className="px-4 py-4">{showDeleted ? <Badge>已删除</Badge> : <DocumentStatus status={document.latest_status} message={document.error_message} />}</td>
          <td className="whitespace-nowrap px-4 py-4 text-xs text-slate-500">{formatDate(document.deleted_at ?? document.updated_at)}</td>
          <td className="sticky right-0 bg-white px-4 py-4 text-right">{showDeleted
            ? <Button variant="secondary" size="sm" disabled={busy} aria-label={`恢复 ${document.name}`} onClick={() => { setError(""); restoration.mutate(document.id); }}><RefreshCw size={14} />恢复</Button>
            : <Button variant="danger" size="sm" disabled={busy} aria-label={`删除 ${document.name}`} onClick={() => { setError(""); setSelected(document); }}><Trash2 size={14} />删除</Button>}</td>
        </tr>)}</tbody>
      </table></div></Card>}
    <Modal open={Boolean(selected)} onOpenChange={(open) => { if (!open && !deletion.isPending) setSelected(null); }} title="删除知识库文档" description="删除后立即停止检索，可在“已删除”列表恢复。">
      <div className="space-y-4 px-6 py-5"><p className="break-words text-sm text-slate-800">确认删除“{selected?.name}”？</p><p className="text-sm leading-6 text-slate-500">该文件所有版本的分块将停止参与新问答，未完成的构建任务会取消。历史对话和引用快照保留。</p>{error ? <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-700">{error}</p> : null}</div>
      <div className="flex justify-end gap-2 border-t border-slate-100 px-6 py-4"><Button variant="secondary" disabled={deletion.isPending} onClick={() => setSelected(null)}>取消</Button><Button variant="danger" disabled={deletion.isPending || !selected} onClick={() => { if (selected) deletion.mutate(selected.id); }}>{deletion.isPending ? <Activity size={14} className="animate-spin" /> : <Trash2 size={14} />}{deletion.isPending ? "正在删除…" : "确认删除"}</Button></div>
    </Modal>
  </div>;
}

type ChunksQuery = ReturnType<typeof useQuery<Awaited<ReturnType<typeof backendApi.listChunks>>>>;

function ChunksPanel({ query, onImport, onPreview }: { query: ChunksQuery; onImport: () => void; onPreview: (chunk: Awaited<ReturnType<typeof backendApi.listChunks>>["items"][number]) => void }) {
  if (query.isError) return <ErrorCard error={query.error} onRetry={() => { void query.refetch(); }} />;
  if (query.isLoading || !query.isFetched) return <Card className="h-56 animate-pulse bg-slate-50"><span className="sr-only">正在加载分块</span></Card>;
  const chunks = query.data?.items ?? [];
  if (!chunks.length) return <EmptyState icon={<Layers3 size={22} />} title="暂无知识分块" description="导入资料并完成构建后，可在这里查看分块与来源。" action={<Button onClick={onImport}><FilePlus2 size={16} />导入资料</Button>} />;
  return <div className="space-y-4">{chunks.map((chunk) => <Card key={chunk.id} className="p-5"><div><div className="flex flex-wrap items-center gap-2"><Badge tone="indigo">分块 {chunk.ordinal + 1}</Badge><strong className="text-sm font-semibold text-slate-800">{chunk.title_path.join(" / ") || chunk.document_name}</strong></div><p className="mt-2 text-xs text-slate-400"><button type="button" onClick={() => onPreview(chunk)} className="rounded text-indigo-600 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500" aria-label={`查看来源文件 ${chunk.document_name} 分块${chunk.ordinal + 1}`}>{chunk.document_name}</button> · V{chunk.document_version}{chunk.page_from ? ` · 第 ${chunk.page_from} 页` : ""}{chunk.sheet_name ? ` · ${chunk.sheet_name}` : ""} · {chunk.token_count} Tokens</p></div><p className="mt-4 whitespace-pre-wrap text-sm leading-6 text-slate-600">{chunk.content}</p></Card>)}</div>;
}

type TasksQuery = ReturnType<typeof useQuery<BuildTaskDetailRead[]>>;

function TasksPanel({ role, query, notify }: { role: Role; query: TasksQuery; notify: (title: string, description?: string) => void }) {
  const [resumeTask, setResumeTask] = useState<BuildTaskDetailRead | null>(null);
  const queryClient = useQueryClient();
  const action = useMutation({
    mutationFn: ({ taskId, kind }: { taskId: string; kind: "retry" | "retry_local" | "cancel" }) => kind === "cancel" ? backendApi.cancelBuildTask(role, taskId) : backendApi.retryBuildTask(role, taskId, kind === "retry_local"),
    onSuccess: async (task) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["knowledge-tasks"] }),
        queryClient.invalidateQueries({ queryKey: ["knowledge-bases"] }),
        queryClient.invalidateQueries({ queryKey: ["knowledge-documents"] }),
      ]);
      notify(task.status === "queued" ? "已加入重试队列" : "已提交取消", task.status === "queued" ? "任务将从原文件重新解析。" : "正在运行的步骤将在安全点停止。");
    },
    onError: (error) => notify("任务操作失败", error instanceof ApiError ? error.message : "请稍后重试。"),
  });
  if (query.isError) return <ErrorCard error={query.error} onRetry={() => { void query.refetch(); }} />;
  if (query.isLoading || !query.isFetched) return <Card className="h-56 animate-pulse bg-slate-50"><span className="sr-only">正在加载构建任务</span></Card>;
  const tasks = query.data ?? [];
  if (!tasks.length) return <EmptyState icon={<Activity size={22} />} title="暂无构建任务" description="导入文件后，解析、预览和索引进度会出现在这里。" />;
  return <Card><div className="border-b border-slate-100 px-5 py-4"><h3 className="font-semibold text-slate-900">构建任务</h3><p className="mt-1 text-xs text-slate-500">失败原因会直接显示；超时 Worker 任务会自动收敛为可重试状态。</p></div><div className="divide-y divide-slate-100">{tasks.map((task) => <TaskRow key={task.id} task={task} pending={action.isPending && action.variables?.taskId === task.id} onResume={() => setResumeTask(task)} onRetry={() => action.mutate({ taskId: task.id, kind: "retry" })} onRetryLocal={() => action.mutate({ taskId: task.id, kind: "retry_local" })} onCancel={() => action.mutate({ taskId: task.id, kind: "cancel" })} />)}</div>{resumeTask ? <TaskResume task={resumeTask} role={role} onClose={() => setResumeTask(null)} /> : null}</Card>;
}

function TaskRow({ task, pending, onRetry, onRetryLocal, onCancel, onResume }: { task: BuildTaskDetailRead; pending: boolean; onRetry: () => void; onRetryLocal: () => void; onCancel: () => void; onResume: () => void }) {
  const running = ["queued", "parsing", "indexing", "replacing"].includes(task.status);
  const preview = task.status === "preview_ready";
  const failed = task.status === "failed";
  const Icon = failed ? AlertTriangle : task.status === "ready" ? CheckCircle2 : Activity;
  const tone = failed ? "bg-red-50 text-red-600" : task.status === "ready" ? "bg-emerald-50 text-emerald-600" : "bg-indigo-50 text-indigo-600";
  return <div className="flex flex-wrap items-center gap-4 px-5 py-4">
    <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${tone}`}><Icon size={18} className={running ? "animate-spin" : ""} /></span>
    <div className="min-w-0 flex-1">
      <div className="flex items-center justify-between gap-4"><strong className="truncate text-sm font-medium text-slate-800">{task.document_name} · V{task.document_version}</strong><span className="shrink-0 text-xs text-slate-400">{task.progress}%</span></div>
      <p className={`mt-1 text-xs ${failed ? "text-red-600" : "text-slate-500"}`}>{failed ? task.error_message ?? "构建失败" : preview ? "解析完成，等待检查预览并开始构建" : task.current_step ?? task.status}</p>
      {task.progress < 100 && !failed ? <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-indigo-500" style={{ width: `${task.progress}%` }} /></div> : null}
    </div>
    <div className="flex flex-wrap gap-2">
      {(preview && task.current_step !== "queued_for_indexing") || task.current_step === "awaiting_data_egress_confirmation" ? <Button size="sm" onClick={onResume}>继续处理</Button> : null}
      {failed && task.error_code === "docmind_not_configured" ? <Button size="sm" disabled={pending || task.attempt_count >= task.max_attempts} onClick={onRetryLocal}>尝试本地解析</Button> : null}
      {failed || task.status === "cancelled" ? <Button variant="secondary" size="sm" disabled={pending || task.attempt_count >= task.max_attempts} onClick={onRetry}><RefreshCw size={14} />{task.error_code === "docmind_not_configured" ? "重试云端解析" : "重试"}</Button> : null}
      {running || preview ? <Button variant="ghost" size="sm" disabled={pending} onClick={onCancel}>取消</Button> : null}
    </div>
  </div>;
}

function SettingsPanel({ record, role, notify }: { record: KnowledgeBaseRead; role: Role; notify: (title: string, description?: string) => void }) {
  const client = useQueryClient();
  const [name, setName] = useState(record.name);
  const [description, setDescription] = useState(record.description ?? "");
  const mutation = useMutation({
    mutationFn: () => backendApi.updateKnowledgeBase(role, record.id, { name, description }),
    onSuccess: async () => { await client.invalidateQueries({ queryKey: ["knowledge-bases"] }); notify("知识库设置已保存"); },
  });
  return <Card className="p-6"><h3 className="font-semibold text-slate-900">基础设置</h3><div className="mt-5 space-y-5">
    <Field label="知识库名称"><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
    <Field label="用途说明"><Textarea rows={3} value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
    <Field label="Embedding 模型"><Input value={`${record.embedding_dimension ?? "未知"} 维`} disabled /></Field>
    <p className="rounded-xl bg-slate-50 p-4 text-xs leading-5 text-slate-500">Embedding 空间在建库后固定。更换时请使用新模型创建知识库并导入资料，验证后在助手中切换绑定；当前知识库可以继续提供问答。</p>
    {mutation.error ? <p className="text-sm text-red-700">{mutation.error instanceof ApiError ? mutation.error.message : "保存失败"}</p> : null}
    <Button disabled={!name.trim() || mutation.isPending} onClick={() => mutation.mutate()}>保存设置</Button>
  </div></Card>;
}

function DocumentStatus({ status, message }: { status: string; message: string | null }) {
  if (status === "ready") return <span className="inline-flex items-center gap-1.5 text-xs font-medium text-emerald-600"><CheckCircle2 size={14} />可用</span>;
  if (status === "failed") return <span title={message ?? undefined} className="inline-flex items-center gap-1.5 text-xs font-medium text-red-600"><CircleAlert size={14} />构建失败</span>;
  if (status === "cancelled") return <span className="text-xs font-medium text-slate-500">已取消</span>;
  return <span className="inline-flex items-center gap-1.5 text-xs font-medium text-indigo-600"><Activity size={14} className="animate-spin" />{status === "preview_ready" ? "待确认构建" : "处理中"}</span>;
}

function StateBadge({ state }: { state: KnowledgeBase["state"] }) {
  if (state === "ready") return <Badge tone="green">可用</Badge>;
  if (state === "building") return <Badge tone="indigo"><Activity size={11} className="mr-1 animate-spin" />构建中</Badge>;
  if (state === "failed") return <Badge tone="red"><AlertTriangle size={11} className="mr-1" />构建失败</Badge>;
  if (state === "archived") return <Badge tone="slate">已归档</Badge>;
  return <Badge tone="slate">待导入</Badge>;
}
