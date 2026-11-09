"use client";

import { useEffect, useRef, useState } from "react";
import {
  Activity, AlertCircle, ArrowLeft, ArrowRight, Check, CheckCircle2, Cloud,
  FileImage, FileSpreadsheet, FileText, Info, Layers3, LockKeyhole,
  RotateCcw, UploadCloud,
} from "lucide-react";
import { Badge, Button, Modal, Select, Toggle } from "@/components/ui/primitives";
import { ChunkSettingsFields, chunkModeLabel, chunkModes, chunkSettingsError, chunkSettingsPayload, createChunkForm, type ChunkFormValues } from "@/components/knowledge/chunk-settings";
import {
  ApiError, backendApi, type BuildTaskRead, type ChunkPreviewResponse,
  type ImportItemRead,
  type ChunkMode,
} from "@/lib/api-client";
import type { Role } from "@/lib/types";
import { cn } from "@/lib/utils";

const steps = ["选择文件", "解析与分块", "正在解析", "预览结果", "完成构建"];
const supportedExtensions = new Set(["doc", "docx", "pdf", "md", "markdown", "csv", "xls", "xlsx", "png", "jpg", "jpeg", "bmp", "webp", "tif", "tiff"]);
const tableExtensions = new Set(["csv", "xls", "xlsx"]);
const parseTerminalStatuses = new Set(["preview_ready", "failed", "cancelled"]);
const buildTerminalStatuses = new Set(["ready", "failed", "cancelled"]);

export type UploadFile = {
  file: File;
  name: string;
  size: string;
  kind: string;
  route: "本地解析" | "云端增强" | "不支持" | "待检查";
  accepted?: boolean;
  taskId?: string;
  message?: string;
};

type ImportWizardProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  knowledgeBaseId: string;
  role: Role;
  onComplete: (files: UploadFile[], chunks: number) => void | Promise<void>;
  maxFileSize?: number;
  batchFileLimit?: number;
  tableOnly?: boolean;
};

function safeMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

function fileKey(file: File) {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

export function ImportWizard({
  open, onOpenChange, knowledgeBaseId, role, onComplete, maxFileSize = 100 * 1024 * 1024, batchFileLimit = 20, tableOnly = false,
}: ImportWizardProps) {
  const [step, setStep] = useState(0);
  const [enhanced, setEnhanced] = useState(false);
  const [files, setFiles] = useState<UploadFile[]>([]);
  const [importItems, setImportItems] = useState<readonly ImportItemRead[]>([]);
  const [tasks, setTasks] = useState<BuildTaskRead[]>([]);
  const [previews, setPreviews] = useState<ChunkPreviewResponse[]>([]);
  const [fileError, setFileError] = useState("");
  const [workflowError, setWorkflowError] = useState("");
  const [chunkSettings, setChunkSettings] = useState(() => createChunkForm(null, tableOnly));
  const [fileModes, setFileModes] = useState<Record<string, ChunkMode>>({});
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const taskIds = files.flatMap((file) => file.taskId ? [file.taskId] : []);
  const failedCount = tasks.filter((task) => ["failed", "cancelled"].includes(task.status)).length;
  const readyCount = tasks.filter((task) => task.status === "ready").length;
  const totalChunks = previews.reduce((total, preview) => total + preview.chunks.length, 0);
  const averageProgress = tasks.length
    ? Math.round(tasks.reduce((total, task) => total + task.progress, 0) / tasks.length)
    : 0;

  useEffect(() => {
    if (!open || (step !== 2 && step !== 4) || taskIds.length === 0) return;
    let cancelled = false;
    let timer: number | undefined;

    async function poll() {
      try {
        const current = await Promise.all(taskIds.map((taskId) => backendApi.getBuildTask(role, taskId)));
        if (cancelled) return;
        setTasks(current);
        const terminal = step === 2 ? parseTerminalStatuses : buildTerminalStatuses;
        if (current.every((task) => terminal.has(task.status))) {
          if (step === 2) {
            const previewable = current.filter((task) => task.status === "preview_ready");
            if (previewable.length === 0) {
              setWorkflowError(current.find((task) => task.error_message)?.error_message ?? "所有文件都未能完成解析，请查看失败原因后重试。");
              return;
            }
            let previewResults: ChunkPreviewResponse[];
            try {
              previewResults = await Promise.all(previewable.map((task) => backendApi.previewBuildTask(
                role, task.id, chunkSettingsPayload(chunkSettings, fileModes[task.id]),
              )));
            } catch (error) {
              if (!cancelled) {
                setWorkflowError(safeMessage(error, "分块预览失败，请调整模式或参数后重试。"));
                setStep(1);
              }
              return;
            }
            if (!cancelled) {
              setPreviews(previewResults);
              setWorkflowError(current.some((task) => task.status === "failed")
                ? "部分文件解析失败，成功文件仍可继续构建。"
                : "");
              setStep(3);
            }
          }
          return;
        }
        timer = window.setTimeout(poll, 1_200);
      } catch (error) {
        if (!cancelled) {
          setWorkflowError(safeMessage(error, "无法获取构建进度，系统将继续在后台处理。"));
          timer = window.setTimeout(poll, 3_000);
        }
      }
    }

    void poll();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [chunkSettings, fileModes, open, role, step, taskIds.join("|")]);

  function reset() {
    setStep(0);
    setEnhanced(false);
    setFiles([]);
    setImportItems([]);
    setTasks([]);
    setPreviews([]);
    setFileError("");
    setWorkflowError("");
    setChunkSettings(createChunkForm(null, tableOnly));
    setFileModes({});
    setBusy(false);
  }

  function close(value: boolean) {
    onOpenChange(value);
    if (!value) window.setTimeout(reset, 250);
  }

  function handleFileInput(list: FileList | null) {
    if (!list) return;
    const incoming = Array.from(list);
    const allowedExtensions = tableOnly ? tableExtensions : supportedExtensions;
    const rejected = incoming.filter((file) => {
      const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
      return !allowedExtensions.has(ext) || file.size > maxFileSize;
    });
    const accepted = incoming.filter((file) => {
      const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
      return allowedExtensions.has(ext) && file.size <= maxFileSize;
    }).slice(0, batchFileLimit);
    setFiles(accepted.map((file) => {
      const ext = file.name.split(".").pop()?.toLowerCase() ?? "file";
      return {
        file,
        name: file.name,
        size: file.size > 1024 * 1024
          ? `${(file.size / 1024 / 1024).toFixed(1)} MB`
          : `${Math.max(1, Math.round(file.size / 1024))} KB`,
        kind: ext.toUpperCase(),
        route: "待检查",
      };
    }));
    setWorkflowError("");
    setFileModes({});
    if (rejected.length) {
      setFileError(`${rejected.length} 个文件未加入：格式不受支持或超过 ${Math.round(maxFileSize / 1024 / 1024)} MB。`);
    } else if (incoming.length > batchFileLimit) {
      setFileError(`单批最多导入 ${batchFileLimit} 个文件，其余文件未加入。`);
    } else {
      setFileError("");
    }
  }

  async function inspectFiles() {
    setBusy(true);
    setWorkflowError("");
    try {
      const result = await backendApi.importDocuments(
        role, knowledgeBaseId, files.map((item) => item.file), false, enhanced,
      );
      setImportItems(result.items);
      setFiles((current) => {
        // Updaters can run twice in Strict Mode; keep matching state local.
        const remaining = [...result.items];
        return current.map((file) => {
        const index = remaining.findIndex((item) => item.filename === file.name);
        const item = index >= 0 ? remaining.splice(index, 1)[0] : undefined;
        if (!item) return file;
        return {
          ...file,
          route: item.route.disposition === "cloud" ? "云端增强" : item.route.disposition === "local" ? "本地解析" : "不支持",
          accepted: item.accepted,
          taskId: item.build_task_id ?? undefined,
          message: item.message,
        };
        });
      });
      if (!result.items.some((item) => item.accepted)) {
        setWorkflowError(result.items.map((item) => `${item.filename}：${item.message}`).join("；"));
        return;
      }
      setStep(1);
    } catch (error) {
      setWorkflowError(safeMessage(error, "文件上传失败，请检查存储服务后重试。"));
    } finally {
      setBusy(false);
    }
  }

  function validChunkSettings() {
    const error = chunkSettingsError(chunkSettings, [chunkSettings.mode, ...Object.values(fileModes)]);
    if (error) {
      setWorkflowError(error);
      return false;
    }
    return true;
  }

  async function startParsing() {
    if (!validChunkSettings()) return;
    setBusy(true);
    setWorkflowError("");
    try {
      const configurable = taskIds.filter((id) => !tasks.some((task) => task.id === id && ["failed", "cancelled"].includes(task.status)));
      await Promise.all(configurable.map((id) => backendApi.saveChunkSettings(
        role, id, chunkSettingsPayload(chunkSettings, fileModes[id]),
      )));
      const cloudTasks = importItems.filter(
        (item) => item.accepted && item.route.data_egress_required && item.build_task_id,
      );
      await Promise.all(cloudTasks.map((item) => backendApi.confirmDataEgress(role, item.build_task_id!)));
      setStep(2);
    } catch (error) {
      setWorkflowError(safeMessage(error, "云端解析确认失败，文件未发送，请重试。"));
    } finally {
      setBusy(false);
    }
  }

  async function refreshPreviews() {
    if (!validChunkSettings()) return;
    setBusy(true);
    setWorkflowError("");
    try {
      const previewable = tasks.filter((task) => task.status === "preview_ready");
      const result = await Promise.all(previewable.map((task) => backendApi.previewBuildTask(
        role, task.id, chunkSettingsPayload(chunkSettings, fileModes[task.id]),
      )));
      setPreviews(result);
      setStep(3);
    } catch (error) {
      setWorkflowError(safeMessage(error, "重新分块失败，请调整参数后重试。"));
    } finally {
      setBusy(false);
    }
  }

  async function startBuild() {
    setBusy(true);
    setWorkflowError("");
    try {
      const result = await Promise.all(previews.map((preview) => backendApi.startBuild(
        role, preview.task.id, preview.settings,
      )));
      setTasks(result);
      setStep(4);
    } catch (error) {
      setWorkflowError(safeMessage(error, "索引任务启动失败，原文件和解析结果仍已保留。"));
    } finally {
      setBusy(false);
    }
  }

  const buildDone = step === 4 && tasks.length > 0 && tasks.every((task) => buildTerminalStatuses.has(task.status));

  return (
    <Modal open={open} onOpenChange={close} title="导入资料" description="先检查解析与分块结果，再将内容构建为可检索的知识。" className="max-w-4xl">
      <div className="shrink-0 border-b border-slate-100 bg-slate-50/60 px-6 py-4">
        <div className="mx-auto flex max-w-3xl items-center">
          {steps.map((label, index) => <div key={label} className={cn("flex items-center", index < steps.length - 1 && "flex-1")}><div className="flex items-center gap-2"><span className={cn("flex h-7 w-7 items-center justify-center rounded-full border text-xs font-semibold transition", index < step ? "border-indigo-600 bg-indigo-600 text-white" : index === step ? "border-indigo-600 bg-white text-indigo-600 ring-4 ring-indigo-50" : "border-slate-200 bg-white text-slate-400")}>{index < step ? <Check size={14} /> : index + 1}</span><span className={cn("hidden text-xs font-medium sm:block", index <= step ? "text-slate-700" : "text-slate-400")}>{label}</span></div>{index < steps.length - 1 ? <div className={cn("mx-3 h-px flex-1", index < step ? "bg-indigo-300" : "bg-slate-200")} /> : null}</div>)}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-6">
        {step === 0 ? <FileStep tableOnly={tableOnly} maxFileSize={maxFileSize} batchFileLimit={batchFileLimit} files={files} fileError={fileError} inputRef={inputRef} onInput={handleFileInput} /> : null}
        {step === 1 ? <SettingsStep files={files} settings={chunkSettings} onSettings={setChunkSettings} fileModes={fileModes} onFileModes={setFileModes} busy={busy} /> : null}
        {step === 2 ? <ParsingStep files={files} tasks={tasks} /> : null}
        {step === 3 ? <PreviewStep previews={previews} onRechunk={() => setStep(1)} /> : null}
        {step === 4 ? <CompleteStep fileCount={files.length} readyCount={readyCount} failedCount={failedCount} progress={averageProgress} complete={buildDone} /> : null}
        {workflowError ? <div className="mt-5 flex gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-xs leading-5 text-red-700"><AlertCircle size={16} className="mt-0.5 shrink-0" /><span>{workflowError}</span></div> : null}
      </div>

      <div className="px-6 pb-4">{step === 0 ? <div className="flex items-center justify-between rounded-xl bg-slate-50 p-3"><span className="text-xs leading-5 text-slate-600">默认本地解析正文和表格；图片、扫描件需要云端 OCR。<br />开启云端增强前，请先在系统设置配置 DocMind。</span><Toggle checked={enhanced} onChange={setEnhanced} label="云端增强解析" /></div> : null}</div><div className="flex shrink-0 items-center justify-between border-t border-slate-100 bg-white px-6 py-4">
        <div>{step === 1 || step === 3 ? <Button variant="ghost" disabled={busy} onClick={() => setStep(step === 1 ? 0 : 1)}><ArrowLeft size={15} />{step === 3 ? "调整参数" : "返回"}</Button> : null}</div>
        <div className="flex gap-2">
          {step === 0 ? <Button onClick={() => void inspectFiles()} disabled={!files.length || busy}>{busy ? <Activity size={15} className="animate-spin" /> : null}{busy ? "正在上传…" : "检查解析方式"}{!busy ? <ArrowRight size={15} /> : null}</Button> : null}
          {step === 1 ? <Button onClick={() => previews.length ? void refreshPreviews() : void startParsing()} disabled={busy || !taskIds.length}>{busy ? <Activity size={15} className="animate-spin" /> : <Layers3 size={15} />}{busy ? "正在提交…" : previews.length ? "重新生成预览" : "开始解析"}</Button> : null}
          {step === 2 ? <Button disabled><Activity size={15} className="animate-spin" />解析中 {averageProgress}%</Button> : null}
          {step === 3 ? <Button onClick={() => void startBuild()} disabled={busy || previews.length === 0}>{busy ? <Activity size={15} className="animate-spin" /> : null}{busy ? "正在启动…" : "确认并开始构建"}{!busy ? <ArrowRight size={15} /> : null}</Button> : null}
          {step === 4 ? <Button disabled={!buildDone} onClick={() => { void onComplete(files, totalChunks); close(false); }}>{!buildDone ? <><Activity size={15} className="animate-spin" />构建中 {averageProgress}%</> : <><CheckCircle2 size={15} />完成并返回</>}</Button> : null}
        </div>
      </div>
    </Modal>
  );
}

function FileStep({ tableOnly, files, fileError, inputRef, onInput, maxFileSize, batchFileLimit }: { maxFileSize: number; batchFileLimit: number; files: UploadFile[]; fileError: string; inputRef: React.RefObject<HTMLInputElement | null>; onInput: (files: FileList | null) => void; tableOnly: boolean }) {
  return <div className="space-y-5"><button type="button" onClick={() => inputRef.current?.click()} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); onInput(event.dataTransfer.files); }} className="group flex w-full flex-col items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-slate-50/70 px-6 py-10 text-center transition hover:border-indigo-400 hover:bg-indigo-50/40"><span className="flex h-12 w-12 items-center justify-center rounded-xl bg-white text-indigo-600 shadow-sm transition group-hover:-translate-y-0.5"><UploadCloud size={22} /></span><strong className="mt-4 text-sm text-slate-800">拖入文件，或点击选择</strong><span className="mt-1 text-xs text-slate-500">{tableOnly ? "仅支持 Excel（.xlsx、.xls）和 CSV" : "支持 Word、PDF、Markdown、Excel、CSV 和图片"}，单文件不超过 {Math.round(maxFileSize / 1024 / 1024)} MB</span><input ref={inputRef} type="file" multiple className="hidden" accept={Array.from(tableOnly ? tableExtensions : supportedExtensions).map((ext) => `.${ext}`).join(",")} onChange={(event) => { onInput(event.target.files); event.target.value = ""; }} /></button>{fileError ? <div className="flex gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-xs leading-5 text-red-700"><AlertCircle size={16} className="mt-0.5 shrink-0" /><span>{fileError}</span></div> : null}<div><div className="mb-3 flex items-center justify-between"><h4 className="text-sm font-semibold text-slate-800">待导入文件</h4><span className="text-xs text-slate-400">{files.length}/{batchFileLimit}</span></div>{files.length ? <div className="space-y-2">{files.map((file) => <FileRow key={fileKey(file.file)} file={file} />)}</div> : <div className="rounded-xl border border-dashed border-slate-200 px-4 py-5 text-center text-xs text-slate-400">选择文件后，服务端会判断解析去向。</div>}</div></div>;
}

function FileRow({ file }: { file: UploadFile }) {
  const tone = file.route === "云端增强" ? "indigo" : file.route === "不支持" ? "red" : "slate";
  return <div className="flex items-center gap-3 rounded-xl border border-slate-200 px-4 py-3"><FileIcon kind={file.kind} /><span className="min-w-0 flex-1"><strong className="block truncate text-sm font-medium text-slate-700">{file.name}</strong><small className="text-xs text-slate-400">{file.kind} · {file.size}{file.message ? ` · ${file.message}` : ""}</small></span><Badge tone={tone}>{file.route === "云端增强" ? <Cloud size={11} className="mr-1" /> : <LockKeyhole size={11} className="mr-1" />}{file.route}</Badge></div>;
}

function SettingsStep({ files, settings, onSettings, fileModes, onFileModes, busy }: {
  files: UploadFile[]; settings: ChunkFormValues; onSettings: (next: ChunkFormValues) => void;
  fileModes: Record<string, ChunkMode>; onFileModes: (next: Record<string, ChunkMode>) => void; busy: boolean;
}) {
  const cloudCount = files.filter((file) => file.route === "云端增强" && file.accepted).length;
  const localCount = files.filter((file) => file.route === "本地解析" && file.accepted).length;
  function changeFileMode(taskId: string, mode: string) {
    const next = { ...fileModes };
    if (mode === "inherit") delete next[taskId];
    else next[taskId] = mode as ChunkMode;
    onFileModes(next);
  }
  return <div className="space-y-5">
    <div className="grid gap-3 sm:grid-cols-2">
      <div className="rounded-xl border border-indigo-100 bg-indigo-50/50 p-4"><div className="flex items-center gap-2 text-sm font-semibold text-indigo-900"><Cloud size={17} />云端增强解析</div><p className="mt-2 text-xs leading-5 text-indigo-700">{cloudCount} 个复杂文件将发送至 DocMind，提取版面、表格、图片文字和页码。</p></div>
      <div className="rounded-xl border border-slate-200 bg-slate-50 p-4"><div className="flex items-center gap-2 text-sm font-semibold text-slate-800"><LockKeyhole size={17} />本地结构解析</div><p className="mt-2 text-xs leading-5 text-slate-500">{localCount} 个文件使用本地解析，不产生云端解析费用。语义分块及后续索引按所选模型服务处理。</p></div>
    </div>
    {cloudCount ? <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3"><div className="flex gap-2 text-xs leading-5 text-amber-800"><Info size={16} className="mt-0.5 shrink-0" /><span>点击“开始解析”即确认允许以上 {cloudCount} 个文件发送到已配置的 DocMind 服务，该操作会记入审计日志。</span></div></div> : null}
    <ChunkSettingsFields value={settings} onChange={onSettings} additionalModes={Object.values(fileModes)} disabled={busy} />
    <div className="space-y-3 rounded-xl border border-slate-200 p-5">
      <div><h4 className="text-sm font-semibold text-slate-800">文件分块模式</h4><p className="mt-1 text-xs leading-5 text-slate-500">默认跟随上方设置，也可逐个选择。智能分块会根据解析出的正文和表格结构处理。</p></div>
      {files.filter((file) => file.accepted && file.taskId).map((file) => <div key={file.taskId} className="flex flex-col gap-2 rounded-lg bg-slate-50 p-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0"><strong className="block truncate text-xs font-medium text-slate-700">{file.name}</strong><span className="text-[11px] text-slate-500">{tableExtensions.has(file.kind.toLowerCase()) ? "推荐表格按行" : "可按内容选择适合的模式"}</span></div>
        <Select disabled={busy} className="sm:w-64" aria-label={`${file.name} 分块模式`} value={fileModes[file.taskId!] ?? "inherit"} onChange={(event) => changeFileMode(file.taskId!, event.target.value)}>
          <option value="inherit">跟随默认 · {chunkModeLabel(settings.mode)}</option>
          {chunkModes.map((mode) => <option key={mode.value} value={mode.value}>{mode.label}</option>)}
        </Select>
      </div>)}
    </div>
  </div>;
}

function ParsingStep({ files, tasks }: { files: UploadFile[]; tasks: BuildTaskRead[] }) {
  const progress = tasks.length ? Math.round(tasks.reduce((total, task) => total + task.progress, 0) / tasks.length) : 0;
  const current = tasks.find((task) => !parseTerminalStatuses.has(task.status));
  const currentFile = files.find((file) => file.taskId === current?.id)?.name ?? files[0]?.name;
  return <div className="flex min-h-[400px] flex-col items-center justify-center text-center"><div className="relative flex h-20 w-20 items-center justify-center rounded-2xl bg-indigo-50 text-indigo-600"><Layers3 size={32} /><span className="absolute inset-0 rounded-2xl border-2 border-indigo-300 pulse-soft" /></div><h3 className="mt-6 text-lg font-semibold text-slate-900">正在解析文档结构</h3><p className="mt-2 max-w-md text-sm leading-6 text-slate-500">当前处理：{currentFile ?? "等待 Worker 接收任务"}<br />关闭弹窗不会中断任务，可在“构建任务”继续查看。</p><div className="mt-7 w-full max-w-lg"><div className="mb-2 flex justify-between text-xs"><span className="text-slate-500">识别标题、表格与图片内容</span><span className="font-medium text-indigo-600">{progress}%</span></div><div className="h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-cyan-400 transition-all" style={{ width: `${progress}%` }} /></div></div><div className="mt-8 grid w-full max-w-lg grid-cols-3 gap-3"><MiniState done={progress >= 10} label="格式检查" /><MiniState done={progress >= 25} label="结构解析" /><MiniState done={progress >= 60} label="生成分块" /></div></div>;
}

function PreviewStep({ previews, onRechunk }: { previews: ChunkPreviewResponse[]; onRechunk: () => void }) {
  const chunks = previews.flatMap((preview) => preview.chunks.map((chunk) => ({ ...chunk, taskId: preview.task.id })));
  const tokens = chunks.reduce((total, chunk) => total + chunk.token_count, 0);
  const warnings = [...new Set(previews.flatMap((preview) => preview.warnings ?? []))];
  return <div className="space-y-5"><div className="grid gap-3 sm:grid-cols-3"><Summary value={previews.length.toString()} label="解析文件" /><Summary value={chunks.length.toLocaleString("zh-CN")} label="预计分块" /><Summary value={tokens.toLocaleString("zh-CN")} label="预计 Tokens" /></div>{warnings.length ? <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs leading-5 text-amber-800">{warnings.join("；")}</div> : null}<div className="flex items-center justify-between gap-4"><div><h4 className="text-sm font-semibold text-slate-800">分块预览</h4><p className="mt-1 text-xs text-slate-500">{previews.map((preview) => `${chunkModeLabel(preview.settings.mode)} · 目标 ${preview.settings.target_tokens} Tokens`).join("；")} · 已保留来源位置</p></div><Button variant="secondary" size="sm" onClick={onRechunk}><RotateCcw size={14} />调整参数</Button></div><div className="space-y-3">{chunks.slice(0, 12).map((chunk, index) => <Chunk key={`${chunk.taskId}:${chunk.ordinal}`} index={index + 1} parent={typeof chunk.metadata?.parent_content === "string" ? chunk.metadata.parent_content : undefined} path={`${chunkModeLabel(chunk.metadata?.chunk_mode as ChunkMode)} · ${chunk.title_path?.join(" / ") || (chunk.kind === "table" ? "表格" : "文本")}`} text={chunk.content} meta={[chunk.page_from ? `第 ${chunk.page_from} 页` : null, chunk.sheet_name ? `工作表 ${chunk.sheet_name}` : null, chunk.cell_range, `${chunk.token_count} Tokens`].filter(Boolean).join(" · ")} />)}{chunks.length > 12 ? <p className="text-center text-xs text-slate-400">当前展示前 12 个分块，共 {chunks.length} 个。</p> : null}</div></div>;
}

function CompleteStep({ fileCount, readyCount, failedCount, progress, complete }: { fileCount: number; readyCount: number; failedCount: number; progress: number; complete: boolean }) {
  const allSucceeded = complete && failedCount === 0;
  const title = complete
    ? allSucceeded ? "知识库构建完成" : "构建已结束"
    : "正在构建向量索引";
  const description = !complete
    ? `${fileCount} 个文件正在生成 Embedding 并写入索引，请稍候。`
    : failedCount
      ? `${readyCount} 个文件已可检索，${failedCount} 个失败。可在构建任务中查看原因并重试。`
      : `${readyCount} 个文件已可用于检索和问答，文档与分块统计已更新。`;
  return (
    <div className="flex min-h-[360px] flex-col items-center justify-center text-center">
      <span className={cn("flex h-20 w-20 items-center justify-center rounded-full", allSucceeded ? "bg-emerald-50 text-emerald-600" : complete ? "bg-amber-50 text-amber-600" : "bg-indigo-50 text-indigo-600")}>
        {complete ? <CheckCircle2 size={38} /> : <Activity size={36} className="animate-spin" />}
      </span>
      <h3 className="mt-6 text-xl font-semibold text-slate-900">{title}</h3>
      <p className="mt-2 max-w-md text-sm leading-6 text-slate-500">{description}</p>
      <div className="mt-7 w-full max-w-md">
        <div className="mb-2 flex justify-between text-xs">
          <span className="text-slate-500">{complete ? "索引任务已收敛" : "生成向量与索引"}</span>
          <span className={cn("font-medium", complete ? "text-emerald-600" : "text-indigo-600")}>{progress}%</span>
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-slate-100">
          <div className={cn("h-full rounded-full transition-all", complete ? "bg-emerald-500" : "bg-indigo-500")} style={{ width: `${progress}%` }} />
        </div>
      </div>
    </div>
  );
}

function FileIcon({ kind }: { kind: string }) {
  const className = "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg";
  if (["XLS", "XLSX", "CSV", "EXCEL"].includes(kind)) return <span className={`${className} bg-emerald-50 text-emerald-600`}><FileSpreadsheet size={17} /></span>;
  if (["PNG", "JPG", "JPEG", "BMP"].includes(kind)) return <span className={`${className} bg-amber-50 text-amber-600`}><FileImage size={17} /></span>;
  return <span className={`${className} bg-indigo-50 text-indigo-600`}><FileText size={17} /></span>;
}

function MiniState({ done, label }: { done: boolean; label: string }) {
  return <div className={cn("rounded-lg border px-3 py-3 text-xs font-medium", done ? "border-emerald-100 bg-emerald-50 text-emerald-700" : "border-slate-200 bg-slate-50 text-slate-400")}>{done ? <Check size={13} className="mr-1 inline" /> : <Activity size={13} className="mr-1 inline" />}{label}</div>;
}

function Summary({ value, label }: { value: string; label: string }) {
  return <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3"><strong className="block text-lg font-semibold text-slate-900">{value}</strong><span className="text-xs text-slate-500">{label}</span></div>;
}

function Chunk({ index, path, text, meta, parent }: { index: number; path: string; text: string; meta: string; parent?: string }) {
  return <div className="rounded-xl border border-slate-200 p-4"><div className="flex items-start justify-between gap-3"><div className="flex items-center gap-2"><Badge tone="indigo">分块 {index}</Badge><span className="text-xs font-medium text-slate-600">{path}</span></div><span className="shrink-0 text-[11px] text-slate-400">{meta}</span></div><p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-600">{text}</p>{parent ? <details className="mt-3 border-t border-slate-100 pt-3"><summary className="text-xs font-medium text-indigo-600">查看关联父块上下文</summary><p className="mt-2 whitespace-pre-wrap text-xs leading-6 text-slate-600">{parent}</p></details> : null}</div>;
}
