"use client";

import { Field, Input, Select } from "@/components/ui/primitives";
import type { ChunkMode, ChunkSettings } from "@/lib/api-client";

export const chunkModes: ReadonlyArray<{ value: ChunkMode; label: string; use: string; description: string }> = [
  { value: "smart", label: "智能分块", use: "大多数文档，推荐默认", description: "优先保留段落与文档结构，超长正文递归切分；表格按表头和连续行分组。" },
  { value: "title", label: "按标题层级", use: "手册、制度、规范", description: "按识别到的标题合并同节正文，章节之间独立分块，超长章节再按目标长度切分。" },
  { value: "delimiter", label: "自定义分隔符", use: "格式规整的条款、清单", description: "先按指定的文字或换行分隔，再拆分超长内容。分隔符按普通文本匹配。" },
  { value: "fixed", label: "固定长度", use: "无结构的长文本、转写稿", description: "按目标长度连续切分正文，使用相邻重叠保留前后文；结构化表格仍保留完整行。" },
  { value: "parent_child", label: "父子分块", use: "长篇研报、技术文档", description: "建立较大父块和较小子块，用子块匹配检索，并把关联父块提供给回答上下文。" },
  { value: "semantic", label: "语义分块", use: "主题跳跃的长文、访谈纪要", description: "调用知识库绑定的 Embedding 模型计算相邻句段相似度，在主题变化处切分。首次预览或修改参数会额外调用模型并产生费用。" },
  { value: "qa", label: "问答对拆分", use: "FAQ、客服、培训材料", description: "识别 Q:/A: 或 问：/答：标记，每组问答作为完整分块；不会自动生成问答。" },
  { value: "page", label: "按页切分", use: "幻灯片、扫描件、图表多的报告", description: "每个已识别的页面作为一个分块，需要解析结果包含准确页码，页内内容保持完整。" },
  { value: "table_row", label: "表格按行", use: "参数表、价格表、FAQ 表格", description: "按指定行数分组，重复保留表头和工作表位置；需要结构化表格，正文仍保留。" },
];

export type ChunkFormValues = {
  mode: ChunkMode; target: string; overlap: string; delimiter: string;
  parentTarget: string; threshold: string; rows: string;
};

export function createChunkForm(settings?: ChunkSettings | null, tableOnly = false): ChunkFormValues {
  return {
    mode: settings?.mode ?? (tableOnly ? "table_row" : "smart"),
    target: String(settings?.target_tokens ?? 800), overlap: String(settings?.overlap_tokens ?? 120),
    delimiter: (settings?.delimiter ?? "\n\n").replaceAll("\n", "\\n").replaceAll("\t", "\\t"),
    parentTarget: String(settings?.parent_target_tokens ?? 1600),
    threshold: String(settings?.semantic_threshold ?? 0.65), rows: String(settings?.table_rows ?? 1),
  };
}

export function usesOverlap(mode: ChunkMode) {
  return ["smart", "title", "delimiter", "fixed", "parent_child"].includes(mode);
}

export function chunkSettingsPayload(values: ChunkFormValues, mode = values.mode): ChunkSettings {
  return {
    mode, target_tokens: Number(values.target), overlap_tokens: usesOverlap(mode) ? Number(values.overlap) : 0,
    delimiter: mode === "delimiter" ? values.delimiter.replaceAll("\\n", "\n").replaceAll("\\t", "\t") : "\n\n",
    parent_target_tokens: mode === "parent_child" ? Number(values.parentTarget) : 1600,
    semantic_threshold: mode === "semantic" ? Number(values.threshold) : 0.65,
    table_rows: mode === "table_row" ? Number(values.rows) : 1,
  };
}

export function chunkSettingsError(values: ChunkFormValues, modes: ChunkMode[] = [values.mode]): string {
  const size = Number(values.target);
  if (!Number.isInteger(size) || size < 100 || size > 4000) return "分块目标长度需要在 100–4000 Tokens 之间。";
  if (modes.some(usesOverlap)) {
    const overlap = Number(values.overlap);
    if (!Number.isInteger(overlap) || overlap < 0 || overlap > 1000 || overlap >= size) return "重叠长度需为 0–1000 的整数，并小于分块目标长度。";
  }
  if (modes.includes("delimiter") && (!values.delimiter || values.delimiter.length > 100)) return "分隔符不能为空，且最多 100 个字符。";
  const parent = Number(values.parentTarget);
  if (modes.includes("parent_child") && (!Number.isInteger(parent) || parent < 100 || parent > 8000 || parent <= size)) return "父块长度需为 100–8000 的整数，父子分块时须大于子块长度。";
  const threshold = Number(values.threshold);
  if (modes.includes("semantic") && (!values.threshold.trim() || !Number.isFinite(threshold) || threshold < -1 || threshold > 1)) return "语义相似度阈值需要在 -1–1 之间。";
  const rows = Number(values.rows);
  if (modes.includes("table_row") && (!Number.isInteger(rows) || rows < 1 || rows > 100)) return "每块表格行数需为 1–100 的整数。";
  return "";
}

export function chunkModeLabel(mode: ChunkMode = "smart") {
  return chunkModes.find((item) => item.value === mode)?.label ?? "智能分块";
}

export function ChunkSettingsFields({ value, onChange, additionalModes = [], disabled = false }: {
  value: ChunkFormValues; onChange: (next: ChunkFormValues) => void; additionalModes?: ChunkMode[]; disabled?: boolean;
}) {
  const modes = new Set([value.mode, ...additionalModes]);
  const overlapEnabled = [...modes].some(usesOverlap);
  const selected = chunkModes.find((item) => item.value === value.mode)!;
  function update(key: keyof ChunkFormValues, next: string) { onChange({ ...value, [key]: next }); }
  return <div className="space-y-5 rounded-xl border border-slate-200 p-5">
    <Field label="默认分块模式" hint="可按文件单独修改">
      <Select value={value.mode} disabled={disabled} onChange={(event) => update("mode", event.target.value)}>
        {chunkModes.map((mode) => <option key={mode.value} value={mode.value}>{mode.label} — {mode.use}</option>)}
      </Select>
    </Field>
    <div className="rounded-xl bg-indigo-50/60 p-4"><strong className="text-sm text-indigo-900">{selected.label}</strong><p className="mt-1 text-xs leading-5 text-indigo-700">{selected.description}</p></div>
    <div className="grid gap-5 sm:grid-cols-2">
      <Field label={value.mode === "parent_child" ? "子块目标长度" : "分块目标长度"} hint="估算 Tokens">
        <Input disabled={disabled} type="number" min={100} max={4000} value={value.target} onChange={(event) => update("target", event.target.value)} />
      </Field>
      <Field label="相邻分块重叠" hint={overlapEnabled ? "估算 Tokens" : "当前模式不使用重叠"}>
        <Input disabled={disabled || !overlapEnabled} type="number" min={0} max={1000} value={overlapEnabled ? value.overlap : "0"} onChange={(event) => update("overlap", event.target.value)} />
      </Field>
      {modes.has("delimiter") ? <div className="sm:col-span-2"><Field label="自定义分隔符" hint="支持 \\n 换行、\\t 制表符"><Input disabled={disabled} maxLength={100} value={value.delimiter} onChange={(event) => update("delimiter", event.target.value)} placeholder="例如：\\n\\n 或 ###" /></Field></div> : null}
      {modes.has("parent_child") ? <Field label="父块目标长度" hint="大于子块，最多 8000 Tokens"><Input disabled={disabled} type="number" min={100} max={8000} value={value.parentTarget} onChange={(event) => update("parentTarget", event.target.value)} /></Field> : null}
      {modes.has("semantic") ? <Field label="语义相似度阈值" hint="越高越容易切分，范围 -1–1"><Input disabled={disabled} type="number" min={-1} max={1} step={0.05} value={value.threshold} onChange={(event) => update("threshold", event.target.value)} /></Field> : null}
      {modes.has("table_row") ? <Field label="每块表格行数" hint="不含重复表头"><Input disabled={disabled} type="number" min={1} max={100} value={value.rows} onChange={(event) => update("rows", event.target.value)} /></Field> : null}
    </div>
    {modes.has("semantic") ? <p className="rounded-lg bg-amber-50 p-3 text-xs leading-5 text-amber-800">语义预览会将文本句段发送至已配置的 Embedding 服务。相同参数的已保存预览可复用，构建时沿用预览边界。</p> : null}
    <p className="text-xs leading-5 text-slate-500">完整页、问答对和表格行可能超过目标长度，会在预览中提示。来源标题、页码与工作表位置随分块保留。</p>
  </div>;
}
