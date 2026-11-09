"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button, Modal } from "@/components/ui/primitives";
import { ChunkSettingsFields, chunkModeLabel, chunkSettingsError, chunkSettingsPayload, createChunkForm } from "@/components/knowledge/chunk-settings";
import { ApiError, backendApi, type BuildTaskDetailRead, type ChunkSettings } from "@/lib/api-client";
import type { Role } from "@/lib/types";

export function TaskResume({ task, role, onClose }: {
  task: BuildTaskDetailRead; role: Role; onClose: () => void;
}) {
  const client = useQueryClient();
  const [settings, setSettings] = useState(() => createChunkForm(task.chunk_settings));
  const [requested, setRequested] = useState<ChunkSettings | null>(() =>
    task.chunk_settings?.mode === "semantic" ? null : chunkSettingsPayload(createChunkForm(task.chunk_settings)),
  );
  const confirmation = task.current_step === "awaiting_data_egress_confirmation";
  const validationError = chunkSettingsError(settings);
  const payload = chunkSettingsPayload(settings);
  const current = JSON.stringify(payload) === JSON.stringify(requested);
  const preview = useQuery({
    queryKey: ["task-preview", role, task.id, requested],
    queryFn: async () => {
      const result = await backendApi.previewBuildTask(role, task.id, requested!);
      void client.invalidateQueries({ queryKey: ["knowledge-tasks"] });
      return result;
    },
    enabled: !confirmation && requested !== null,
    retry: false,
  });
  const action = useMutation({
    mutationFn: () => confirmation
      ? backendApi.confirmDataEgress(role, task.id)
      : backendApi.startBuild(role, task.id, preview.data!.settings),
    onSuccess: async () => {
      await Promise.all(["knowledge-tasks", "knowledge-documents", "knowledge-bases"].map(
        (key) => client.invalidateQueries({ queryKey: [key] }),
      ));
      onClose();
    },
  });
  const error = action.error ?? preview.error;
  return <Modal open onOpenChange={(open) => { if (!open) onClose(); }}
    title={confirmation ? "确认云端解析" : "继续预览与构建"} description={task.document_name}>
    <div className="space-y-4 overflow-y-auto px-6 py-5">
      {confirmation ? <p className="rounded-xl bg-amber-50 p-4 text-sm leading-6 text-amber-900">
        此文件需要发送至阿里云 DocMind 进行解析。请先在系统设置中配置云端 OCR，确认后任务会进入解析队列。
      </p> : <>
        <ChunkSettingsFields value={settings} onChange={setSettings} disabled={action.isPending || preview.isFetching} />
        {validationError ? <p role="alert" className="text-xs text-red-700">{validationError}</p> : null}
        <div className="flex flex-wrap items-center gap-3"><Button variant="secondary" disabled={Boolean(validationError) || preview.isFetching || action.isPending} onClick={() => {
          if (current) void preview.refetch();
          else setRequested(payload);
        }}>{preview.isFetching ? "正在生成预览…" : "更新分块预览"}</Button>
          {!current ? <span className="text-xs text-amber-700">请先生成当前参数的预览，再开始构建。</span> : null}
        </div>
        {preview.data && current ? <><p className="text-xs text-slate-500">{chunkModeLabel(preview.data.settings.mode)} · 共 {preview.data.chunks.length} 个分块，展示前 8 个。关闭后可从任务列表继续。</p>
          {(preview.data.warnings ?? []).map((warning) => <p key={warning} className="text-xs text-amber-700">{warning}</p>)}
          {preview.data.chunks.slice(0, 8).map((chunk) => <div key={chunk.ordinal} className="rounded-xl border border-slate-200 p-4">
            <p className="mb-2 text-xs text-slate-400">分块 {chunk.ordinal + 1} · {chunk.token_count} Tokens</p>
            <p className="whitespace-pre-wrap text-sm leading-6 text-slate-700">{chunk.content}</p>
          </div>)}</> : null}
      </>}
      {error ? <p role="alert" className="text-sm text-red-700">{error instanceof ApiError ? error.message : "操作失败，请重试。"}</p> : null}
    </div>
    <div className="flex justify-end gap-2 border-t px-6 py-4"><Button variant="secondary" onClick={onClose}>稍后继续</Button>
      <Button disabled={action.isPending || (!confirmation && (Boolean(validationError) || !current || preview.isFetching || preview.isError || !preview.data?.chunks.length))} onClick={() => action.mutate()}>
        {action.isPending ? "正在提交…" : confirmation ? "确认并开始解析" : "开始构建"}
      </Button>
    </div>
  </Modal>;
}
