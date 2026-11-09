"use client";

import * as Tabs from "@radix-ui/react-tabs";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArchiveRestore, FileUp, KeyRound, RefreshCw, Save, ServerCog, Settings, Shield, TimerReset } from "lucide-react";
import { useState } from "react";
import { ApiKeysView } from "@/components/api-keys-view";
import { Button, Card, Field, Input, Select, Toggle } from "@/components/ui/primitives";
import { ApiError, backendApi, type SystemSettingsRead } from "@/lib/api-client";
import type { Role } from "@/lib/types";

function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : "系统设置操作失败。";
}

export function SettingsView({ role, notify }: { role: Role; notify: (title: string, description?: string) => void }) {
  return (
    <Tabs.Root defaultValue="general" className="space-y-6 fade-in">
      <div>
        <h2 className="text-xl font-semibold text-slate-900">系统设置</h2>
        <p className="mt-1 text-sm text-slate-500">管理文件解析、日志保留、会话策略和 API Key。</p>
      </div>
      <Tabs.List aria-label="系统设置分类" className="flex flex-wrap gap-1 border-b border-slate-200">
        <Tabs.Trigger value="general" className="flex items-center gap-2 border-b-2 border-transparent px-4 py-3 text-sm font-medium text-slate-500 transition hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 data-[state=active]:border-indigo-600 data-[state=active]:text-indigo-700">
          <Settings size={16} aria-hidden="true" />常规设置
        </Tabs.Trigger>
        <Tabs.Trigger value="keys" className="flex items-center gap-2 border-b-2 border-transparent px-4 py-3 text-sm font-medium text-slate-500 transition hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 data-[state=active]:border-indigo-600 data-[state=active]:text-indigo-700">
          <KeyRound size={16} aria-hidden="true" />API Key
        </Tabs.Trigger>
      </Tabs.List>
      <Tabs.Content value="general" forceMount className="outline-none data-[state=inactive]:hidden">
        <GeneralSettingsView role={role} notify={notify} />
      </Tabs.Content>
      <Tabs.Content value="keys" className="outline-none">
        <ApiKeysView role={role} notify={notify} />
      </Tabs.Content>
    </Tabs.Root>
  );
}

function GeneralSettingsView({ role, notify }: { role: Role; notify: (title: string, description?: string) => void }) {
  const settingsQuery = useQuery({
    queryKey: ["system-settings", role],
    queryFn: () => backendApi.getSystemSettings(role),
  });

  if (settingsQuery.isLoading) return <Card className="h-72 animate-pulse bg-slate-50"><span className="sr-only">正在加载系统设置</span></Card>;
  if (settingsQuery.isError || !settingsQuery.data) return <Card className="flex items-center justify-between border-red-100 p-6"><div><strong className="text-sm text-red-800">系统设置加载失败</strong><p className="mt-1 text-xs text-red-600">{errorMessage(settingsQuery.error)}</p></div><Button variant="secondary" size="sm" onClick={() => { void settingsQuery.refetch(); }}><RefreshCw size={14} />重试</Button></Card>;
  return <SettingsForm key={settingsQuery.data.updated_at} role={role} initial={settingsQuery.data} notify={notify} />;
}

function SettingsForm({ role, initial, notify }: { role: Role; initial: SystemSettingsRead; notify: (title: string, description?: string) => void }) {
  const queryClient = useQueryClient();
  const [fileSizeMb, setFileSizeMb] = useState(String(Math.round(initial.file_size_limit_bytes / 1024 / 1024)));
  const [batchLimit, setBatchLimit] = useState(String(initial.batch_file_limit));
  const [pageLimit, setPageLimit] = useState(String(initial.page_limit));
  const [retentionDays, setRetentionDays] = useState(String(initial.detailed_log_retention_days));
  const [aggregate, setAggregate] = useState(initial.retain_daily_metrics);
  const [browserDays, setBrowserDays] = useState(String(initial.browser_session_days));
  const [defaultRole, setDefaultRole] = useState(initial.default_role);
  const [ocrId, setOcrId] = useState("");
  const [ocrSecret, setOcrSecret] = useState("");
  const [ocrEndpoint, setOcrEndpoint] = useState(initial.docmind_endpoint);
  const [saveError, setSaveError] = useState("");

  const mutation = useMutation({
    mutationFn: () => backendApi.updateSystemSettings(role, {
      file_size_limit_bytes: Number(fileSizeMb) * 1024 * 1024,
      batch_file_limit: Number(batchLimit),
      page_limit: Number(pageLimit),
      detailed_log_retention_days: Number(retentionDays),
      retain_daily_metrics: aggregate,
      browser_session_days: Number(browserDays),
      default_role: defaultRole,
      docmind_endpoint: ocrEndpoint,
      ...(ocrId && ocrSecret ? { docmind_access_key_id: ocrId, docmind_access_key_secret: ocrSecret } : {}),
    }),
    onSuccess: async () => {
      setSaveError("");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["system-settings"] }),
        queryClient.invalidateQueries({ queryKey: ["knowledge-bases"] }),
      ]);
      notify("系统设置已保存", "文件限制已同步到知识库；日志和会话策略将在后续任务中生效。");
    },
    onError: (error) => setSaveError(errorMessage(error)),
  });

  const numericValues = [fileSizeMb, batchLimit, pageLimit, retentionDays, browserDays].map(Number);
  const valid = numericValues.every((value) => Number.isInteger(value) && value > 0)
    && Number(fileSizeMb) <= 1024
    && Number(batchLimit) <= 100
    && Number(pageLimit) <= 5_000
    && Number(retentionDays) <= 3_650
    && Number(browserDays) <= 365
    && Boolean(ocrId) === Boolean(ocrSecret);

  return <div className="space-y-6"><div className="grid gap-5 xl:grid-cols-[1fr_330px]"><div className="space-y-5"><SettingsCard icon={FileUp} title="文件与解析" description="限制会同步到现有知识库"><div className="grid gap-5 sm:grid-cols-3"><Field label="单文件大小上限" hint="MB"><Input type="number" min={1} max={1024} value={fileSizeMb} onChange={(event) => setFileSizeMb(event.target.value)} /></Field><Field label="单批文件数量"><Input type="number" min={1} max={100} value={batchLimit} onChange={(event) => setBatchLimit(event.target.value)} /></Field><Field label="PDF 最大页数"><Input type="number" min={1} max={5000} value={pageLimit} onChange={(event) => setPageLimit(event.target.value)} /></Field></div><div className="rounded-xl bg-slate-50 p-4 text-xs leading-5 text-slate-600">解析路由服务端检测文件内容后决定。需要 DocMind 的文件会在发送前单独要求数据出网确认。</div></SettingsCard><SettingsCard icon={FileUp} title="云端 OCR" description="图片、扫描件与复杂文档使用阿里云 DocMind，无需下载本地模型">
        <p className="text-sm text-slate-600">{initial.docmind_configured ? `已配置 ${initial.docmind_access_key_mask ?? "部署环境凭据"}` : "尚未配置，普通文本资料仍可本地解析。"}</p>
        <Field label="DocMind AccessKey ID" hint="留空保留已有凭据"><Input type="password" autoComplete="new-password" value={ocrId} onChange={(e) => setOcrId(e.target.value)} /></Field>
        <Field label="DocMind AccessKey Secret"><Input type="password" autoComplete="new-password" value={ocrSecret} onChange={(e) => setOcrSecret(e.target.value)} /></Field>
        <Field label="DocMind 服务地址"><Input value={ocrEndpoint} onChange={(e) => setOcrEndpoint(e.target.value)} /></Field>
        <p className="text-xs leading-5 text-slate-500">凭据加密保存在服务端。DocMind 使用阿里云 AccessKey，与通义模型 API Key 分开配置。</p>
      </SettingsCard><SettingsCard icon={TimerReset} title="日志与保留" description="平衡问题追溯、隐私与存储空间"><Field label="详细日志保留" hint="天"><Input type="number" min={1} max={3650} value={retentionDays} onChange={(event) => setRetentionDays(event.target.value)} /></Field><SettingToggle title="长期保留每日统计" description="“每日统计”是按日汇总的调用次数、Token、总耗时和错误数。详细日志过期后，它仍可用于趋势分析，但不包含单次问题或回答原文。" checked={aggregate} onChange={setAggregate} /></SettingsCard><SettingsCard icon={Shield} title="匿名会话" description="当前版本不含登录，角色只用于体验分层"><div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-xs leading-5 text-amber-800">任何访问者都可以切换为管理员。当前权限只减少误操作，不提供真实身份认证或资源隔离；开放公网前必须接入登录。</div><div className="mt-4 grid gap-5 sm:grid-cols-2"><Field label="浏览器会话有效期" hint="天"><Input type="number" min={1} max={365} value={browserDays} onChange={(event) => setBrowserDays(event.target.value)} /></Field><Field label="默认体验角色"><Select value={defaultRole} onChange={(event) => setDefaultRole(event.target.value as Role)}><option value="user">使用者</option><option value="manager">知识库管理人员</option><option value="admin">管理员</option></Select></Field></div></SettingsCard>{saveError ? <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{saveError}</div> : null}<div className="flex justify-end"><Button disabled={!valid || mutation.isPending} onClick={() => mutation.mutate()}>{mutation.isPending ? <ActivityIcon /> : <Save size={15} />}{mutation.isPending ? "正在保存…" : "保存全部设置"}</Button></div></div><div className="space-y-5"><Card className="p-5"><div className="flex items-center gap-2"><ServerCog size={18} className="text-indigo-600" /><h3 className="text-sm font-semibold text-slate-900">生效范围</h3></div><div className="mt-4 space-y-3 text-xs leading-5 text-slate-500"><p>文件限制：现有与新建知识库。</p><p>日志保留：下一次 Celery Beat 清理任务。</p><p>会话期限：新创建的浏览器会话。</p></div><p className="mt-4 border-t border-slate-100 pt-4 text-[11px] text-slate-400">最后更新：{new Date(initial.updated_at).toLocaleString("zh-CN")}</p></Card><Card className="p-5"><div className="flex items-center gap-2"><ArchiveRestore size={18} className="text-emerald-600" /><h3 className="text-sm font-semibold text-slate-900">备份与恢复</h3></div><p className="mt-3 text-xs leading-5 text-slate-500">本机版使用 scripts/native_backup.py 备份数据库、原文件和密钥恢复材料，Docker 版另有 MinIO 备份脚本。恢复操作需显式传入 <code className="rounded bg-slate-100 px-1">--confirm-restore</code>，管理端不会远程执行破坏性恢复。</p></Card></div></div></div>;
}

function ActivityIcon() { return <RefreshCw size={15} className="animate-spin" />; }
function SettingsCard({ icon: Icon, title, description, children }: { icon: typeof FileUp; title: string; description: string; children: React.ReactNode }) { return <Card className="p-6"><div className="flex items-center gap-3 border-b border-slate-100 pb-4"><span className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600"><Icon size={18} /></span><div><h3 className="text-sm font-semibold text-slate-900">{title}</h3><p className="mt-0.5 text-xs text-slate-500">{description}</p></div></div><div className="mt-5 space-y-5">{children}</div></Card>; }
function SettingToggle({ title, description, checked, onChange }: { title: string; description: string; checked: boolean; onChange: (value: boolean) => void }) { return <div className="flex items-center justify-between gap-5 rounded-xl bg-slate-50 p-4"><div className="min-w-0 flex-1"><strong className="text-sm text-slate-800">{title}</strong><p className="mt-1 text-xs leading-5 text-slate-500">{description}</p></div><div className="flex w-12 shrink-0 justify-end"><Toggle checked={checked} onChange={onChange} label={title} /></div></div>; }
