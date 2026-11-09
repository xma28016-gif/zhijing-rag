"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Download, FileText, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge, Button, Modal } from "@/components/ui/primitives";
import { ApiError, backendApi } from "@/lib/api-client";
import type { Role } from "@/lib/types";

export type DocumentPreviewTarget = (
  { knowledgeBaseId: string; documentId: string; versionNumber?: number }
  | { chunkId: string }
) & { documentName?: string; excerpt?: string; location?: string };

export function DocumentPreview({ target, role, onClose }: { target: DocumentPreviewTarget; role: Role; onClose: () => void }) {
  const [mode, setMode] = useState<"parsed" | "original">("parsed");
  const [rawUrl, setRawUrl] = useState("");
  const [downloadError, setDownloadError] = useState("");
  const [downloading, setDownloading] = useState(false);
  const chunkId = "chunkId" in target ? target.chunkId : undefined;
  const sourceQuery = useQuery({ queryKey: ["document-source", role, chunkId], queryFn: () => backendApi.getChunkSource(role, chunkId!), enabled: Boolean(chunkId), retry: false });
  const source = "knowledgeBaseId" in target ? target : sourceQuery.data ? {
    knowledgeBaseId: sourceQuery.data.knowledge_base_id, documentId: sourceQuery.data.document_id,
    versionNumber: sourceQuery.data.version_number,
  } : undefined;
  const contentQuery = useInfiniteQuery({
    queryKey: ["document-content", role, source?.knowledgeBaseId, source?.documentId, source?.versionNumber],
    queryFn: ({ pageParam }) => backendApi.getDocumentContent(role, source!.knowledgeBaseId, source!.documentId, source!.versionNumber, pageParam),
    initialPageParam: 0,
    getNextPageParam: (last) => last.offset + last.blocks.length < last.total ? last.offset + last.limit : undefined,
    enabled: Boolean(source), retry: false,
  });
  const first = contentQuery.data?.pages[0];
  const name = first?.document_name ?? target.documentName ?? sourceQuery.data?.document_name ?? "文件内容";
  const isPdf = name.toLowerCase().endsWith(".pdf");
  const isImage = /\.(png|jpe?g|webp|bmp|tiff?)$/i.test(name);
  const originalQuery = useQuery({
    queryKey: ["document-original", role, source?.knowledgeBaseId, source?.documentId, source?.versionNumber],
    queryFn: () => backendApi.getDocumentOriginal(role, source!.knowledgeBaseId, source!.documentId, source!.versionNumber),
    enabled: mode === "original" && Boolean(source), retry: false, gcTime: 0,
  });
  useEffect(() => {
    if (!originalQuery.data) return;
    const url = URL.createObjectURL(originalQuery.data);
    setRawUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [originalQuery.data]);

  async function download() {
    if (!source) return;
    setDownloading(true); setDownloadError("");
    try {
      const blob = originalQuery.data ?? await backendApi.getDocumentOriginal(role, source.knowledgeBaseId, source.documentId, source.versionNumber);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url; link.download = name; link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) { setDownloadError(error instanceof ApiError ? error.message : "下载失败，请重试。"); }
    finally { setDownloading(false); }
  }

  const error = sourceQuery.error ?? contentQuery.error;
  const loading = sourceQuery.isLoading || (Boolean(source) && contentQuery.isLoading);
  const blocks = contentQuery.data?.pages.flatMap((page) => page.blocks) ?? [];
  return <Modal open onOpenChange={(open) => { if (!open) onClose(); }} title={name} description="查看文件内容与来源版本" className="max-w-5xl">
    <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-6 py-3">
      <div className="flex items-center gap-2"><FileText size={16} className="text-indigo-500" /><Badge tone="indigo">V{first?.version_number ?? source?.versionNumber ?? "—"}</Badge>{first ? <span className="text-xs text-slate-400">{first.total} 个内容段落{first.page_count ? ` · ${first.page_count} 页` : ""}</span> : null}</div>
      <div className="flex gap-2">{isPdf || isImage ? <><Button variant={mode === "parsed" ? "secondary" : "ghost"} size="sm" onClick={() => setMode("parsed")}>解析内容</Button><Button variant={mode === "original" ? "secondary" : "ghost"} size="sm" disabled={!source} onClick={() => setMode("original")}>原文件预览</Button></> : null}<Button variant="secondary" size="sm" disabled={!source || downloading} onClick={() => { void download(); }}><Download size={14} />{downloading ? "下载中…" : "下载原文件"}</Button></div>
    </div>
    <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-6 py-5">
      {first?.deleted_at ? <p className="rounded-lg bg-amber-50 p-3 text-xs text-amber-800">文件已删除，当前查看保留的历史版本；该文件不再参与新问答。</p> : null}
      {target.excerpt ? <section className="rounded-xl border border-indigo-100 bg-indigo-50/60 p-4"><h3 className="text-xs font-semibold text-indigo-800">当前引用分块{target.location ? ` · ${target.location}` : ""}</h3><p className="mt-2 whitespace-pre-wrap break-words text-sm leading-7 text-slate-700">{target.excerpt}</p></section> : null}
      {downloadError ? <p role="alert" className="text-xs text-red-700">{downloadError}</p> : null}
      {loading ? <p role="status" className="py-10 text-center text-sm text-slate-400">正在读取文件内容…</p> : error ? <div role="alert" className="rounded-xl bg-amber-50 p-4 text-sm leading-6 text-amber-800"><p>{error instanceof ApiError ? error.message : "文件内容读取失败。"}</p>{target.excerpt ? <p className="mt-2 text-xs">上方仍保留当次运行的引用快照。</p> : null}<Button variant="ghost" size="sm" className="mt-2" onClick={() => { if (sourceQuery.error) void sourceQuery.refetch(); else void contentQuery.refetch(); }}><RefreshCw size={13} />重试</Button></div> : mode === "original" ? <div>
        {originalQuery.isLoading ? <p className="py-8 text-center text-sm text-slate-400">正在读取原文件…</p> : originalQuery.error ? <p role="alert" className="text-sm text-red-700">{originalQuery.error instanceof ApiError ? originalQuery.error.message : "原文件预览失败，请尝试下载。"}</p> : rawUrl ? isImage ? <img src={rawUrl} alt={name} className="mx-auto max-h-[65vh] max-w-full rounded-lg object-contain" /> : <iframe src={rawUrl} title={name} className="h-[65vh] w-full rounded-lg border border-slate-200" /> : null}
      </div> : <>
        {first?.warnings.map((warning) => <p key={warning} className="rounded-lg bg-slate-50 px-4 py-3 text-xs leading-6 text-slate-500">{warning}</p>)}
        {first?.content_source === "chunks" ? <p className="text-xs text-slate-400">以下为该版本保存的知识分块内容。</p> : null}
        <div className="divide-y divide-slate-100">{blocks.map((block, index) => <section key={`${block.ordinal}-${index}`} className="py-4 first:pt-0">
          {block.title_path?.length || block.page_from || block.sheet_name ? <p className="mb-2 text-xs text-slate-400">{[block.title_path?.join(" / "), block.page_from ? `第 ${block.page_from} 页` : "", block.sheet_name, block.cell_range].filter(Boolean).join(" · ")}</p> : null}
          {block.kind === "table" ? <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded-xl bg-slate-50 p-4 font-mono text-sm leading-7 text-slate-700">{block.content}</pre> : <p className="whitespace-pre-wrap break-words text-sm leading-7 text-slate-700">{block.content}</p>}
          {block.kind === "image" && block.object_key?.startsWith("https://") ? <img src={block.object_key} alt="文档内图片" className="mt-3 max-h-96 max-w-full rounded-lg object-contain" loading="lazy" /> : null}
        </section>)}</div>
        {contentQuery.hasNextPage ? <div className="flex justify-center"><Button variant="secondary" disabled={contentQuery.isFetchingNextPage} onClick={() => { void contentQuery.fetchNextPage(); }}>{contentQuery.isFetchingNextPage ? "正在加载…" : "加载更多内容"}</Button></div> : null}
      </>}
    </div>
  </Modal>;
}
