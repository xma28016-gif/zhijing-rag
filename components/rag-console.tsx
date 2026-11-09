"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CheckCircle2, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { AppShell, allowedViews } from "@/components/app-shell";
import { AssistantsView } from "@/components/assistants-view";
import { ChatView } from "@/components/chat-view";
import { DashboardView } from "@/components/dashboard-view";
import { DatasetsView } from "@/components/datasets-view";
import { KnowledgeView } from "@/components/knowledge-view";
import { LogsView } from "@/components/logs-view";
import { ModelsView } from "@/components/models-view";
import { SettingsView } from "@/components/settings-view";
import { Button } from "@/components/ui/primitives";
import { backendApi } from "@/lib/api-client";
import type { Role, ToastMessage, ViewKey } from "@/lib/types";

export function RagConsole() {
  const [queryClient] = useState(() => new QueryClient({ defaultOptions: { queries: { staleTime: 30_000, refetchOnWindowFocus: false } } }));
  const [role, setRole] = useState<Role>("admin");
  const [activeView, setActiveView] = useState<ViewKey>("dashboard");
  const [collapsed, setCollapsed] = useState(false);
  const [assistantId, setAssistantId] = useState("assistant-hr");
  const [logsEntry, setLogsEntry] = useState<{ focus: "requests" | "duration"; days: string } | null>(null);
  const [datasetId, setDatasetId] = useState<string>();
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const toastId = useRef(0);

  useEffect(() => {
    let cancelled = false;
    if (window.location.hash.startsWith("#workbench")) window.history.replaceState(window.history.state, "", window.location.pathname + window.location.search);
    try {
      const saved = JSON.parse(localStorage.getItem("rag-console.preferences.v1") ?? "null") as { role?: Role; view?: ViewKey } | null;
      if (saved?.role && ["admin", "manager", "user"].includes(saved.role)) {
        const views = allowedViews(saved.role);
        setRole(saved.role);
        setActiveView(views.some((view) => view.key === saved.view) ? saved.view! : saved.role === "user" ? "assistants" : "dashboard");
        return;
      }
    } catch { /* Ignore unavailable storage or preferences from an older version. */ }
    void backendApi.getSystemSettings("admin").then((settings) => {
      if (cancelled) return;
      setRole(settings.default_role);
      setActiveView(settings.default_role === "user" ? "assistants" : "dashboard");
    }).catch(() => {
      // The shell remains usable with the local admin default while the API is unavailable.
    });
    return () => { cancelled = true; };
  }, []);

  function remember(nextRole: Role, view: ViewKey) {
    try { localStorage.setItem("rag-console.preferences.v1", JSON.stringify({ role: nextRole, view })); } catch { /* Navigation remains usable without browser storage. */ }
  }

  const dismissToast = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const notify = useCallback((title: string, description?: string) => {
    const id = ++toastId.current;
    setToasts((current) => [...current.slice(-2), { id, title, description, tone: "success" }]);
    window.setTimeout(() => dismissToast(id), 3600);
  }, [dismissToast]);

  function handleRoleChange(nextRole: Role) {
    setRole(nextRole);
    const views = allowedViews(nextRole);
    const nextView = views.some((view) => view.key === activeView) ? activeView : nextRole === "user" ? "assistants" : "dashboard";
    setActiveView(nextView);
    remember(nextRole, nextView);
    notify("角色已切换", nextRole === "admin" ? "现在可以访问模型、密钥和系统设置。" : nextRole === "manager" ? "现在可以管理知识库、助手和业务日志。" : "现在只显示助手、对话与本浏览器会话。")
  }

  function navigate(view: ViewKey) {
    setLogsEntry(null);
    setActiveView(view);
    remember(role, view);
  }

  function openChat(id: string) {
    setAssistantId(id);
    navigate("chat");
  }

  function openLogs(focus: "requests" | "duration") {
    setLogsEntry({ focus, days: "today" });
    setActiveView("logs");
    remember(role, "logs");
  }

  function openDataset(id: string) { setDatasetId(id); navigate("datasets"); }

  let content: React.ReactNode;
  switch (activeView) {
    case "dashboard": content = <DashboardView role={role} onNavigate={navigate} onOpenLogs={openLogs} />; break;
    case "models": content = <ModelsView role={role} notify={notify} />; break;
    case "knowledge": content = <KnowledgeView role={role} notify={notify} />; break;
    case "assistants": content = <AssistantsView role={role} onOpenChat={openChat} notify={notify} />; break;
    case "chat": content = <ChatView initialAssistantId={assistantId} role={role} notify={notify} />; break;
    case "logs": content = <LogsView key={logsEntry ? `${logsEntry.days}-${logsEntry.focus}` : "default"} role={role} initialDays={logsEntry?.days} initialFocus={logsEntry?.focus} onOpenDataset={openDataset} />; break;
    case "datasets": content = <DatasetsView role={role} initialDatasetId={datasetId} onOpenLogs={() => navigate("logs")} />; break;
    case "settings": content = <SettingsView role={role} notify={notify} />; break;
  }

  return (
    <QueryClientProvider client={queryClient}>
      <AppShell role={role} activeView={activeView} collapsed={collapsed} onRoleChange={handleRoleChange} onViewChange={navigate} onCollapsedChange={setCollapsed}>{content}</AppShell>
      <div className="fixed bottom-5 right-5 z-[100] flex w-[calc(100%-2.5rem)] max-w-sm flex-col gap-2" aria-live="polite">
        {toasts.map((toast) => <div key={toast.id} className="slide-up flex items-start gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-xl"><span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-emerald-50 text-emerald-600"><CheckCircle2 size={15} /></span><div className="min-w-0 flex-1"><strong className="block text-sm font-semibold text-slate-800">{toast.title}</strong>{toast.description ? <p className="mt-1 text-xs leading-5 text-slate-500">{toast.description}</p> : null}</div><Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => dismissToast(toast.id)} aria-label="关闭提示"><X size={14} /></Button></div>)}
      </div>
    </QueryClientProvider>
  );
}
