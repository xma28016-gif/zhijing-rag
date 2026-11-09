"use client";

import { useId, useState } from "react";
import {
  Activity, ArrowUpRight, Check, CheckCircle2, ChevronDown, ChevronRight,
  CircleAlert, CloudCog, Pencil, Plus, Route, Search, Sparkles, TestTube2, Trash2, Waypoints,
} from "lucide-react";
import { Badge, Button, Card, Input, Select } from "@/components/ui/primitives";
import type { ModelConfigRead, ProviderRead, ProviderTemplate } from "@/lib/api-client";

export type ModelKind = ModelConfigRead["kind"];
export const modelKinds: ModelKind[] = ["llm", "embedding", "rerank"];
export const modelTypeLabel = { llm: "LLM", embedding: "Embedding", rerank: "Rerank" } as const;
const typeDescriptions = {
  llm: "生成回答与理解问题",
  embedding: "将文档转为向量，用于知识检索",
  rerank: "对检索结果重新排序，提高相关性",
};
const providerAppearance: Record<string, { mark: string; tone: string; description: string }> = {
  openrouter: { mark: "OR", tone: "bg-slate-900", description: "通过统一接口接入不同厂商的模型。" },
  aihubmix: { mark: "AH", tone: "bg-violet-600", description: "统一管理多种模型的调用与密钥。" },
  tongyi: { mark: "通", tone: "bg-indigo-600", description: "接入通义千问与百炼平台模型。" },
};

function ProviderMark({ providerKey, name, small = false }: { providerKey: string; name: string; small?: boolean }) {
  const appearance = providerAppearance[providerKey] ?? { mark: name.slice(0, 1), tone: "bg-indigo-600" };
  return <span aria-hidden="true" className={`flex shrink-0 items-center justify-center rounded-xl font-semibold text-white ${small ? "h-8 w-8 text-[10px]" : "h-11 w-11 text-sm"} ${appearance.tone}`}>{appearance.mark}</span>;
}

function KindIcon({ kind }: { kind: ModelKind }) {
  return kind === "llm" ? <Sparkles size={17} /> : kind === "embedding" ? <Waypoints size={17} /> : <Route size={17} />;
}

export function DefaultModelSettings({ models, providers, loading, pending, error, onChange }: {
  models: ModelConfigRead[]; providers: ProviderRead[]; loading: boolean; pending: boolean;
  error: string; onChange: (kind: ModelKind, id: string) => void;
}) {
  const idPrefix = useId();
  const providerMap = new Map(providers.map((provider) => [provider.id, provider]));
  return <Card className="overflow-hidden">
    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 px-5 py-5 sm:px-6">
      <div><h3 className="text-lg font-semibold text-slate-900">设置默认模型</h3><p className="mt-1 text-xs leading-5 text-slate-500">为新建知识库和助手预选模型，已有配置保持各自的选择。</p></div>
      <span role="status" className="inline-flex items-center gap-1.5 rounded-full bg-slate-50 px-2.5 py-1 text-[11px] text-slate-500">{pending ? <Activity size={12} className="animate-spin" /> : <Check size={12} />}{pending ? "保存中…" : "选择后自动保存"}</span>
    </div>
    <div className="divide-y divide-slate-100 px-5 sm:px-6">
      {modelKinds.map((kind) => {
        const current = models.find((model) => model.kind === kind && model.is_default && model.enabled);
        const available = models.filter((model) => model.kind === kind && model.enabled && model.validation_status === "valid" && providerMap.get(model.provider_id)?.enabled);
        const currentUnavailable = current && !available.some((model) => model.id === current.id);
        const selectId = `${idPrefix}-${kind}`;
        return <div key={kind} className="grid gap-3 py-5 sm:grid-cols-[160px_minmax(0,1fr)] sm:items-center xl:grid-cols-[180px_minmax(0,1fr)]">
          <label htmlFor={selectId}><span className="flex items-center gap-2 text-sm font-semibold text-slate-800"><span className="text-indigo-500"><KindIcon kind={kind} /></span>{modelTypeLabel[kind]}</span><span className="mt-1.5 block text-[11px] leading-5 text-slate-400">{typeDescriptions[kind]}</span></label>
          <div>
            <Select id={selectId} aria-label={`默认 ${modelTypeLabel[kind]} 模型`} disabled={loading || pending} value={current?.id ?? ""} onChange={(event) => onChange(kind, event.target.value)} className={`h-12 bg-slate-50/70 ${currentUnavailable ? "border-amber-300" : ""}`}>
              <option value="">{available.length === 0 ? "请先添加并验证模型" : "未设置默认模型"}</option>
              {currentUnavailable ? <option value={current.id} disabled>{current.name} · 需要重新验证</option> : null}
              {available.map((model) => <option key={model.id} value={model.id}>{model.model_id} · {providerMap.get(model.provider_id)?.name} · {model.name}</option>)}
            </Select>
            {currentUnavailable ? <p className="mt-1.5 text-[11px] text-amber-700">当前默认模型不可用，请重新测试或选择其他模型。</p> : null}
          </div>
        </div>;
      })}
    </div>
    {error ? <div role="alert" className="mx-5 mb-5 rounded-lg bg-red-50 px-4 py-3 text-xs text-red-700 sm:mx-6">{error}</div> : null}
  </Card>;
}

export function ConfiguredModelList({ models, providers, loading, testingId, testing, onConfigure, onAdd, onEdit, onDelete, onTest }: {
  models: ModelConfigRead[]; providers: ProviderRead[]; loading: boolean; testingId?: string; testing: boolean;
  onConfigure: (provider: ProviderRead) => void; onAdd: (provider: ProviderRead) => void;
  onEdit: (model: ModelConfigRead) => void; onDelete: (model: ModelConfigRead) => void; onTest: (id: string) => void;
}) {
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState<ModelKind | "all">("all");
  const [collapsed, setCollapsed] = useState<string[]>([]);
  const idPrefix = useId();
  const groups = providers.filter((provider) => provider.api_key_mask || models.some((model) => model.provider_id === provider.id)).map((provider) => ({
    provider,
    models: models.filter((model) => model.provider_id === provider.id && (kind === "all" || model.kind === kind) && `${model.name} ${model.model_id} ${provider.name}`.toLowerCase().includes(search.trim().toLowerCase())),
  })).filter((group) => group.models.length > 0 || (kind === "all" && !search.trim()));

  return <section aria-label="已添加的模型" className="space-y-4">
    <div className="flex items-center gap-2"><h3 className="text-lg font-semibold text-slate-900">已添加的模型</h3><span className="rounded-md bg-slate-200/60 px-2 py-0.5 text-xs font-medium text-slate-500">{models.length}</span></div>
    <div className="flex gap-2">
      <div className="relative min-w-0 flex-1"><Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" /><Input aria-label="搜索已添加模型" placeholder="搜索模型名称或 ID" value={search} onChange={(event) => setSearch(event.target.value)} className="pl-9" /></div>
      <Select aria-label="已添加模型类型" value={kind} onChange={(event) => setKind(event.target.value as ModelKind | "all")} className="w-32"><option value="all">全部类型</option>{modelKinds.map((value) => <option key={value} value={value}>{modelTypeLabel[value]}</option>)}</Select>
    </div>
    {loading ? <Card className="h-40 animate-pulse bg-slate-50"><span className="sr-only">正在加载已添加模型</span></Card> : null}
    {!loading && groups.length === 0 ? <Card className="px-5 py-10 text-center"><CloudCog size={25} className="mx-auto mb-3 text-slate-300" /><p className="text-sm font-medium text-slate-600">{search || kind !== "all" ? "没有找到匹配的模型" : "还没有接入模型"}</p><p className="mt-2 text-xs text-slate-400">{search || kind !== "all" ? "试试其他关键词或模型类型。" : "从可选模型中选择服务商，配置密钥后添加具体模型。"}</p></Card> : null}
    {groups.map(({ provider, models: groupModels }) => {
      const expanded = !collapsed.includes(provider.id);
      const contentId = `${idPrefix}-${provider.id}`;
      return <Card key={provider.id} className="overflow-hidden">
        <div className="flex flex-wrap items-center gap-3 px-5 py-4">
          <button type="button" aria-expanded={expanded} aria-controls={contentId} aria-label={`${expanded ? "收起" : "展开"}${provider.name}模型`} onClick={() => setCollapsed((current) => expanded ? [...current, provider.id] : current.filter((id) => id !== provider.id))} className="flex min-w-0 flex-1 items-center gap-3 rounded-lg text-left outline-none focus-visible:ring-2 focus-visible:ring-indigo-500">
            <ProviderMark providerKey={provider.key} name={provider.name} small /><span className="min-w-0"><strong className="block truncate text-sm font-semibold text-slate-800">{provider.name}</strong><span className="mt-0.5 block text-[11px] text-slate-400">{groupModels.length} 个模型{provider.enabled ? "" : " · 服务商已停用"}</span></span>{expanded ? <ChevronDown size={15} className="text-slate-400" /> : <ChevronRight size={15} className="text-slate-400" />}
          </button>
          <div className="flex gap-1"><Button variant="ghost" size="sm" onClick={() => onConfigure(provider)}><CloudCog size={14} />配置</Button><Button variant="secondary" size="sm" onClick={() => onAdd(provider)}><Plus size={14} />添加模型</Button></div>
        </div>
        {expanded ? <div id={contentId} className="border-t border-slate-100">
          {groupModels.length === 0 ? <p className="px-5 py-6 text-xs text-slate-400">服务商已配置，点击“添加模型”完成连通性验证。</p> : null}
          <ul className="divide-y divide-slate-100">
            {groupModels.map((model) => {
              const valid = model.enabled && model.validation_status === "valid" && provider.enabled;
              const status = !provider.enabled || !model.enabled ? "已停用" : valid ? "可用" : model.validation_status === "invalid" ? "验证失败" : "待验证";
              const capability = model.kind === "embedding" ? `${model.embedding_dimension ?? "未知"} 维` : model.kind === "llm" ? `${model.supports_streaming ? "流式" : "非流式"}${model.max_context_tokens ? ` · ${Math.round(model.max_context_tokens / 1024)}K 上下文` : ""}` : "相关性重排";
              return <li key={model.id} className="px-5 py-4 transition hover:bg-slate-50/70">
                <div className="flex items-start gap-3"><span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600"><KindIcon kind={model.kind} /></span><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><strong className="break-words text-sm font-medium text-slate-800">{model.name}</strong><Badge>{modelTypeLabel[model.kind]}</Badge>{model.is_default ? <Badge tone="indigo">默认</Badge> : null}</div><p className="mt-1 break-all font-mono text-[11px] leading-5 text-slate-400">{model.model_id}</p></div></div>
                <div className="mt-3 flex flex-wrap items-center justify-between gap-2 pl-11"><div className="flex items-center gap-3 text-[11px]"><span className={`inline-flex items-center gap-1 ${valid ? "text-emerald-600" : "text-amber-600"}`}>{valid ? <CheckCircle2 size={12} /> : <CircleAlert size={12} />}{status}</span><span className="text-slate-400">{capability}</span></div><div className="-mr-2 flex items-center"><Button variant="ghost" size="sm" disabled={testing} onClick={() => onTest(model.id)} aria-label={`测试模型 ${model.name} ${modelTypeLabel[model.kind]}`}>{testing && testingId === model.id ? <Activity size={13} className="animate-spin" /> : <TestTube2 size={13} />}测试</Button><Button variant="ghost" size="icon" aria-label={`编辑模型 ${model.name} ${modelTypeLabel[model.kind]}`} title="编辑模型" onClick={() => onEdit(model)}><Pencil size={14} /></Button><Button variant="ghost" size="icon" className="text-slate-400 hover:bg-red-50 hover:text-red-600" aria-label={`删除模型 ${model.name} ${modelTypeLabel[model.kind]}`} title="删除模型" onClick={() => onDelete(model)}><Trash2 size={14} /></Button></div></div>
                {model.validation_error ? <p className="mt-2 break-words pl-11 text-[11px] leading-5 text-red-600">{model.validation_error}</p> : null}
              </li>;
            })}
          </ul>
        </div> : null}
      </Card>;
    })}
  </section>;
}

export function ProviderCatalog({ templates, providers, kind, onKindChange, onAdd, loading }: {
  templates: ProviderTemplate[]; providers: ProviderRead[]; kind: ModelKind | "all";
  onKindChange: (kind: ModelKind | "all") => void; onAdd: (template: ProviderTemplate) => void; loading: boolean;
}) {
  const [search, setSearch] = useState("");
  const filtered = templates.filter((template) => (kind === "all" || template.capabilities.includes(kind)) && `${template.name} ${template.key}`.toLowerCase().includes(search.trim().toLowerCase()));
  return <aside aria-label="可选模型" className="self-start rounded-xl border border-slate-200/80 bg-white/80 p-5 xl:sticky xl:top-5">
    <div className="mb-5"><h3 className="text-lg font-semibold text-slate-900">可选模型</h3><p className="mt-1 text-xs leading-5 text-slate-500">选择服务商，接入你自己的模型。</p></div>
    <div className="relative"><Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" /><Input aria-label="搜索模型服务商" placeholder="搜索服务商" value={search} onChange={(event) => setSearch(event.target.value)} className="bg-white pl-9" /></div>
    <div role="group" aria-label="可选模型类型" className="my-4 flex flex-wrap gap-2">{(["all", ...modelKinds] as const).map((value) => <button type="button" key={value} aria-pressed={kind === value} onClick={() => onKindChange(value)} className={`flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-[11px] font-medium outline-none transition focus-visible:ring-2 focus-visible:ring-indigo-500 ${kind === value ? "border-indigo-200 bg-indigo-50 text-indigo-700" : "border-transparent bg-slate-100 text-slate-500 hover:bg-slate-200"}`}>{value === "all" ? "全部" : modelTypeLabel[value]}<span className={kind === value ? "text-indigo-400" : "text-slate-400"}>{templates.filter((template) => value === "all" || template.capabilities.includes(value)).length}</span></button>)}</div>
    <div className="space-y-3">
      {loading ? <div className="h-36 animate-pulse rounded-xl bg-slate-100"><span className="sr-only">正在加载可选模型</span></div> : null}
      {filtered.map((template) => {
        const provider = providers.find((item) => item.key === template.key);
        const configured = provider?.enabled && Boolean(provider.api_key_mask);
        return <div key={template.key} className="rounded-xl border border-slate-200 bg-white p-4 transition hover:border-indigo-200 hover:shadow-sm">
          <div className="flex items-center gap-3"><ProviderMark providerKey={template.key} name={template.name} /><div className="min-w-0 flex-1"><div className="flex items-center gap-1.5"><h4 className="truncate text-sm font-semibold text-slate-800">{template.name}</h4>{template.documentation_url ? <a href={template.documentation_url} target="_blank" rel="noopener noreferrer" aria-label={`${template.name} 接入文档`} className="rounded p-1 text-slate-400 hover:text-indigo-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"><ArrowUpRight size={14} /></a> : null}</div><p className="mt-0.5 text-[11px] text-slate-400">{configured ? "已配置服务商" : "使用自己的 API Key"}</p></div></div>
          <p className="mt-3 text-[11px] leading-5 text-slate-500">{providerAppearance[template.key]?.description ?? template.name}</p>
          <div className="mt-3 flex flex-wrap gap-1.5">{template.capabilities.map((capability) => <Badge key={capability} className="px-1.5 py-0.5 font-normal">{modelTypeLabel[capability]}</Badge>)}</div>
          <Button variant={configured ? "secondary" : "primary"} size="sm" className="mt-4 w-full" onClick={() => onAdd(template)}><Plus size={14} />{configured ? "添加模型" : "配置并添加"}</Button>
        </div>;
      })}
      {!loading && filtered.length === 0 ? <p className="rounded-lg bg-slate-50 px-4 py-8 text-center text-xs text-slate-500">没有匹配的服务商，请调整搜索条件。</p> : null}
    </div>
    <p className="mt-5 text-[11px] leading-5 text-slate-400">模型需通过真实请求验证后才会出现在默认选项中。具体模型可用性以服务商账户为准。</p>
  </aside>;
}
