"use client";

import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import {
  Activity,
  BookOpenCheck,
  Bot,
  Boxes,
  ChevronDown,
  ChevronsLeft,
  ChevronsRight,
  CircleHelp,
  Database,
  LayoutDashboard,
  Menu,
  MessageSquareText,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  UserRound,
  type LucideIcon,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import type { Role, ViewKey } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ServiceHealth } from "@/components/service-health";
import { Button, Input, Modal } from "@/components/ui/primitives";

const roleMeta: Record<Role, { label: string; shortLabel: string; description: string; icon: LucideIcon; avatarClassName: string; selectedClassName: string }> = {
  admin: {
    label: "管理员",
    shortLabel: "管理员",
    description: "模型、系统与全部日志",
    icon: ShieldCheck,
    avatarClassName: "border-violet-200 bg-violet-100 text-violet-700",
    selectedClassName: "border-violet-200 bg-violet-50",
  },
  manager: {
    label: "知识库管理人员",
    shortLabel: "知识管理",
    description: "知识与助手运营",
    icon: BookOpenCheck,
    avatarClassName: "border-cyan-200 bg-cyan-100 text-cyan-700",
    selectedClassName: "border-cyan-200 bg-cyan-50",
  },
  user: {
    label: "使用者",
    shortLabel: "使用者",
    description: "在线问答与会话",
    icon: UserRound,
    avatarClassName: "border-emerald-200 bg-emerald-100 text-emerald-700",
    selectedClassName: "border-emerald-200 bg-emerald-50",
  },
};

function RoleAvatar({ role, compact = false }: { role: Role; compact?: boolean }) {
  const Icon = roleMeta[role].icon;

  return (
    <span
      aria-hidden="true"
      className={cn(
        "flex shrink-0 items-center justify-center border shadow-sm",
        compact ? "h-8 w-8 rounded-lg" : "h-9 w-9 rounded-xl",
        roleMeta[role].avatarClassName,
      )}
    >
      <Icon size={compact ? 17 : 19} strokeWidth={2.2} />
    </span>
  );
}

const navItems: Array<{ key: ViewKey; label: string; icon: typeof LayoutDashboard; roles: Role[] }> = [
  { key: "dashboard", label: "工作台", icon: LayoutDashboard, roles: ["admin", "manager"] },
  { key: "knowledge", label: "知识库", icon: Database, roles: ["admin", "manager"] },
  { key: "assistants", label: "助手", icon: Bot, roles: ["admin", "manager", "user"] },
  { key: "chat", label: "在线对话", icon: MessageSquareText, roles: ["admin", "manager", "user"] },
  { key: "logs", label: "运行日志", icon: Activity, roles: ["admin", "manager"] },
  { key: "datasets", label: "评测集", icon: BookOpenCheck, roles: ["admin", "manager"] },
  { key: "models", label: "模型服务", icon: Boxes, roles: ["admin"] },
  { key: "settings", label: "系统设置", icon: Settings, roles: ["admin"] },
];

export const viewTitles: Record<ViewKey, { title: string; description: string }> = {
  dashboard: { title: "工作台", description: "掌握知识资产、问答质量与系统运行状态" },
  models: { title: "模型服务", description: "集中配置并验证 LLM、Embedding 与 Rerank" },
  knowledge: { title: "知识库", description: "导入资料、检查分块并验证检索效果" },
  assistants: { title: "助手", description: "将模型、知识库与回答规则组合成问答入口" },
  chat: { title: "在线对话", description: "基于企业知识获取有依据、可追溯的回答" },
  logs: { title: "运行日志", description: "分析查询内容、Tokens、耗时和链路异常" },
  datasets: { title: "评测集", description: "汇总线上 Good / Bad Case，沉淀参考答案与判定标准" },
  settings: { title: "系统设置", description: "管理文件解析、日志保留、会话策略和 API Key" },
};

export function allowedViews(role: Role) {
  return navItems.filter((item) => item.roles.includes(role));
}

export function AppShell({ role, activeView, collapsed, onRoleChange, onViewChange, onCollapsedChange, children }: { role: Role; activeView: ViewKey; collapsed: boolean; onRoleChange: (role: Role) => void; onViewChange: (view: ViewKey) => void; onCollapsedChange: (collapsed: boolean) => void; children: ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [quickSearch, setQuickSearch] = useState("");
  const current = viewTitles[activeView];
  const visibleNav = allowedViews(role);

  return (
    <div className="flex min-h-screen">
      <aside className={cn("fixed inset-y-0 left-0 z-40 hidden flex-col border-r border-slate-200 bg-[#f9fafc]/95 backdrop-blur transition-all lg:flex", collapsed ? "w-[76px]" : "w-[236px]")}>
        <div className={cn("flex h-[72px] items-center border-b border-slate-200/70", collapsed ? "justify-center px-3" : "px-5")}>
          <button onClick={() => onViewChange(role === "user" ? "assistants" : "dashboard")} className="flex items-center gap-3 text-left" aria-label="返回工作台">
            <span className="relative flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-indigo-600 text-white shadow-lg shadow-indigo-200">
              <Sparkles size={18} />
              <span className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full border-2 border-white bg-emerald-400" />
            </span>
            {collapsed ? null : <span><strong className="block text-base font-semibold tracking-tight text-slate-900">知境</strong><small className="block text-[10px] tracking-[0.12em] text-slate-400">RAG CONSOLE</small></span>}
          </button>
        </div>

        <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-5" aria-label="主导航">
          {visibleNav.map((item) => {
            const Icon = item.icon;
            const active = activeView === item.key;
            return (
              <button key={item.key} onClick={() => onViewChange(item.key)} title={collapsed ? item.label : undefined} className={cn("group flex h-10 w-full items-center gap-3 rounded-lg px-3 text-sm font-medium transition", active ? "bg-indigo-50 text-indigo-700" : "text-slate-600 hover:bg-white hover:text-slate-900 hover:shadow-sm", collapsed && "justify-center px-0")}>
                <Icon size={18} strokeWidth={active ? 2.2 : 1.8} />
                {collapsed ? null : <span>{item.label}</span>}
                {active && !collapsed ? <span className="ml-auto h-1.5 w-1.5 rounded-full bg-indigo-500" /> : null}
              </button>
            );
          })}
        </nav>

        <div className="border-t border-slate-200/70 p-3">
          <button onClick={() => onCollapsedChange(!collapsed)} className={cn("mb-2 flex h-9 w-full items-center gap-3 rounded-lg px-3 text-sm text-slate-500 hover:bg-white hover:text-slate-800", collapsed && "justify-center px-0")} aria-label={collapsed ? "展开侧栏" : "收起侧栏"}>
            {collapsed ? <ChevronsRight size={17} /> : <><ChevronsLeft size={17} /><span>收起导航</span></>}
          </button>
          <DropdownMenu.Root>
            <DropdownMenu.Trigger asChild>
              <button aria-label={`当前角色：${roleMeta[role].label}，点击切换`} className={cn("flex w-full items-center gap-3 rounded-xl border border-slate-200 bg-white p-2.5 text-left shadow-sm transition hover:border-indigo-200", collapsed && "justify-center p-2")}>
                <RoleAvatar role={role} compact />
                {collapsed ? null : <><span className="min-w-0 flex-1"><strong className="block truncate text-xs font-semibold text-slate-800">{roleMeta[role].label}</strong><small className="block truncate text-[10px] text-slate-400">体验式角色</small></span><ChevronDown size={14} className="text-slate-400" /></>}
              </button>
            </DropdownMenu.Trigger>
            <DropdownMenu.Portal>
              <DropdownMenu.Content side="right" align="end" sideOffset={10} className="z-50 w-64 rounded-xl border border-slate-200 bg-white p-1.5 shadow-xl">
                <div className="px-2.5 py-2 text-xs font-medium text-slate-400">切换当前体验角色</div>
                {(Object.keys(roleMeta) as Role[]).map((roleKey) => {
                  return <DropdownMenu.Item key={roleKey} onSelect={() => onRoleChange(roleKey)} className={cn("flex cursor-pointer items-center gap-3 rounded-lg border border-transparent px-2.5 py-2.5 outline-none transition hover:bg-slate-50 focus:bg-slate-50", roleKey === role && roleMeta[roleKey].selectedClassName)}><RoleAvatar role={roleKey} compact /><span className="min-w-0"><strong className="block truncate text-sm font-medium text-slate-800">{roleMeta[roleKey].label}</strong><small className="block truncate text-xs text-slate-400">{roleMeta[roleKey].description}</small></span></DropdownMenu.Item>;
                })}
                <div className="mt-1 border-t border-slate-100 px-2.5 py-2 text-[10px] leading-4 text-slate-400">当前版本不含登录，角色切换不构成真实安全边界。</div>
              </DropdownMenu.Content>
            </DropdownMenu.Portal>
          </DropdownMenu.Root>
        </div>
      </aside>

      {mobileOpen ? <div className="fixed inset-0 z-50 lg:hidden"><button className="absolute inset-0 bg-slate-950/35" onClick={() => setMobileOpen(false)} aria-label="关闭导航遮罩" /><aside className="absolute inset-y-0 left-0 flex w-[286px] flex-col bg-[#f9fafc] shadow-2xl slide-up"><div className="flex h-[72px] items-center justify-between border-b border-slate-200 px-5"><div className="flex items-center gap-3"><span className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-600 text-white"><Sparkles size={18} /></span><span><strong className="block text-base font-semibold text-slate-900">知境</strong><small className="block text-[10px] tracking-[0.12em] text-slate-400">RAG CONSOLE</small></span></div><Button variant="ghost" size="icon" onClick={() => setMobileOpen(false)} aria-label="关闭导航"><ChevronsLeft size={18} /></Button></div><nav className="flex-1 space-y-1 overflow-y-auto p-3" aria-label="移动端主导航">{visibleNav.map((item) => { const Icon = item.icon; const active = activeView === item.key; return <button key={item.key} onClick={() => { onViewChange(item.key); setMobileOpen(false); }} className={cn("flex h-11 w-full items-center gap-3 rounded-lg px-3 text-sm font-medium", active ? "bg-indigo-50 text-indigo-700" : "text-slate-600 hover:bg-white")}><Icon size={18} /><span>{item.label}</span></button>; })}</nav><div className="border-t border-slate-200 p-4"><p className="mb-2 text-[11px] font-medium text-slate-400">切换体验角色</p><div className="grid grid-cols-3 gap-2">{(Object.keys(roleMeta) as Role[]).map((roleKey) => <button key={roleKey} onClick={() => { onRoleChange(roleKey); setMobileOpen(false); }} aria-label={`切换为${roleMeta[roleKey].label}`} className={cn("flex flex-col items-center gap-1.5 rounded-xl border px-1 py-2 text-[10px] font-medium text-slate-600 transition hover:bg-white", roleKey === role ? roleMeta[roleKey].selectedClassName : "border-slate-200 bg-white")}><RoleAvatar role={roleKey} compact /><span>{roleMeta[roleKey].shortLabel}</span></button>)}</div></div></aside></div> : null}

      <div className={cn("min-w-0 flex-1 transition-all", collapsed ? "lg:ml-[76px]" : "lg:ml-[236px]")}>
        <header className="sticky top-0 z-30 flex h-[72px] items-center gap-4 border-b border-slate-200/80 bg-white/85 px-5 backdrop-blur-xl md:px-8">
          <Button variant="ghost" size="icon" className="lg:hidden" onClick={() => setMobileOpen(true)} aria-label="打开导航"><Menu size={19} /></Button>
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-lg font-semibold tracking-tight text-slate-900">{current.title}</h1>
            <p className="hidden truncate text-xs text-slate-500 sm:block">{current.description}</p>
          </div>
          <div className="relative hidden w-60 xl:block">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={15} />
            <Input aria-label="查找功能" placeholder="查找功能…" value={quickSearch} onChange={(e) => setQuickSearch(e.target.value)} className="h-9 bg-slate-50 pl-9" />{quickSearch ? <div className="absolute top-10 w-full rounded-xl border bg-white p-2 shadow-xl">{visibleNav.filter((item) => item.label.includes(quickSearch)).map((item) => <button key={item.key} className="block w-full rounded-lg p-2 text-left text-sm hover:bg-indigo-50" onClick={() => { onViewChange(item.key); setQuickSearch(""); }}>{item.label}</button>)}{!visibleNav.some((item) => item.label.includes(quickSearch)) ? <p className="p-2 text-xs text-slate-500">没有匹配的功能</p> : null}</div> : null}
          </div>
          <Button variant="ghost" size="icon" aria-label="帮助中心" onClick={() => setHelpOpen(true)}><CircleHelp size={19} /></Button>
          <ServiceHealth />
        </header>
        <Modal open={helpOpen} onOpenChange={setHelpOpen} title="使用指南" description="完成首次知识问答"><div className="space-y-4 px-6 py-5 text-sm leading-7 text-slate-600"><p>1. 管理员在模型服务配置服务商密钥，添加并测试 Embedding、LLM 和可选 Rerank。</p><p>2. 管理员或知识库管理人员新建知识库，导入资料、检查解析结果并开始构建。</p><p>3. 图片、扫描 PDF 和增强解析需要在系统设置配置云端 OCR。</p><p>4. 创建助手并绑定可用知识库，发布后切换为使用者开始对话。</p><p>5. 导入中断后可从构建任务点击“继续处理”；运行日志可查看问题、来源、耗时和模型用量。</p></div></Modal><main className="mx-auto min-h-[calc(100vh-72px)] max-w-[1600px] px-5 py-6 md:px-8 md:py-8">{children}</main>
      </div>
    </div>
  );
}
