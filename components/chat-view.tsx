"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bot, Copy, ExternalLink, FileText, MessageSquarePlus, PanelLeftClose,
  RefreshCw, Send, ShieldCheck, Sparkles, Square,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Badge, Button, Card, Drawer, Select, Textarea } from "@/components/ui/primitives";
import {
  ApiError, backendApi, streamAssistantChat, type MessageRead,
} from "@/lib/api-client";
import type { Role } from "@/lib/types";
import { cn } from "@/lib/utils";

const browserTokenKey = "rag-console-browser-session";

type Citation = {
  index: number;
  chunk_id: string;
  document_name: string;
  document_version: number;
  chunk_ordinal: number;
  location: string;
  excerpt: string;
  score: number;
};

type ChatUsage = {
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  exact?: boolean;
};

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  noEvidence?: boolean;
  streaming?: boolean;
  error?: boolean;
  usage?: ChatUsage;
};

function greeting(name: string): Message {
  return {
    id: `greeting-${name}`,
    role: "assistant",
    content: `你好，我是${name}。我会严格根据已绑定的企业资料回答，并标出来源引用。你想了解什么？`,
  };
}

function asCitations(value: unknown): Citation[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is Citation => {
    if (!item || typeof item !== "object") return false;
    const candidate = item as Partial<Citation>;
    return typeof candidate.document_name === "string"
      && typeof candidate.location === "string"
      && typeof candidate.excerpt === "string";
  });
}

function fromHistory(message: MessageRead): Message | null {
  if (message.role !== "user" && message.role !== "assistant") return null;
  return {
    id: message.id,
    role: message.role,
    content: message.content,
    citations: asCitations(message.citations),
    usage: message.usage as ChatUsage,
  };
}

function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : "对话请求失败，请稍后重试。";
}

export function ChatView({ initialAssistantId, role, notify }: { initialAssistantId?: string; role: Role; notify: (title: string, description?: string) => void }) {
  const queryClient = useQueryClient();
  const [assistantId, setAssistantId] = useState(initialAssistantId ?? "");
  const [conversationId, setConversationId] = useState<string>();
  const [browserToken, setBrowserToken] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [citation, setCitation] = useState<Citation | null>(null);
  const [sessionsOpen, setSessionsOpen] = useState(true);
  const [sessionError, setSessionError] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const assistantsQuery = useQuery({
    queryKey: ["assistants", role],
    queryFn: () => backendApi.listAssistants(role),
  });
  const assistants = assistantsQuery.data ?? [];
  const activeAssistant = assistants.find((item) => item.id === assistantId) ?? assistants[0];

  const conversationsQuery = useQuery({
    queryKey: ["chat-conversations", role, browserToken],
    queryFn: () => backendApi.listConversations(role, browserToken),
    enabled: Boolean(browserToken),
  });
  const messagesQuery = useQuery({
    queryKey: ["chat-messages", role, browserToken, conversationId],
    queryFn: () => backendApi.listMessages(role, browserToken, conversationId!),
    enabled: Boolean(browserToken && conversationId),
  });

  useEffect(() => {
    let cancelled = false;
    async function ensureSession() {
      const stored = window.localStorage.getItem(browserTokenKey);
      if (stored) {
        setBrowserToken(stored);
        return;
      }
      try {
        const session = await backendApi.createBrowserSession(role);
        if (!cancelled) {
          window.localStorage.setItem(browserTokenKey, session.token);
          setBrowserToken(session.token);
        }
      } catch (error) {
        if (!cancelled) setSessionError(errorMessage(error));
      }
    }
    void ensureSession();
    return () => { cancelled = true; };
  }, [role]);

  useEffect(() => () => abortRef.current?.abort(), []);

  useEffect(() => {
    if (!activeAssistant || conversationId) return;
    setMessages((current) => current.length ? current : [greeting(activeAssistant.name)]);
  }, [activeAssistant, conversationId]);

  useEffect(() => {
    if (!messagesQuery.data || !activeAssistant || messages.some((message) => message.streaming)) return;
    const history = messagesQuery.data.map(fromHistory).filter((item): item is Message => item !== null);
    setMessages(history.length ? history : [greeting(activeAssistant.name)]);
  }, [activeAssistant, messagesQuery.data]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const isStreaming = messages.some((message) => message.streaming);
  const visibleConversations = (conversationsQuery.data ?? []).filter(
    (conversation) => !activeAssistant || conversation.assistant_id === activeAssistant.id,
  );

  function saveBrowserToken(token: string) {
    window.localStorage.setItem(browserTokenKey, token);
    setBrowserToken(token);
  }

  function newConversation(assistant = activeAssistant) {
    abortRef.current?.abort();
    setConversationId(undefined);
    setMessages(assistant ? [greeting(assistant.name)] : []);
    setInput("");
    notify("已创建新会话", assistant ? `当前助手：${assistant.name}` : undefined);
  }

  function stopStreaming() {
    abortRef.current?.abort();
    abortRef.current = null;
    setMessages((current) => current.map((message) => message.streaming
      ? { ...message, streaming: false, content: `${message.content}\n\n（回答已停止）` }
      : message));
  }

  async function send(customText?: string) {
    const query = (customText ?? input).trim();
    if (!query || isStreaming || !activeAssistant || !browserToken) return;
    setInput("");
    setSessionError("");
    const userMessage: Message = { id: crypto.randomUUID(), role: "user", content: query };
    const assistantMessageId = crypto.randomUUID();
    const assistantMessage: Message = { id: assistantMessageId, role: "assistant", content: "", streaming: true };
    setMessages((current) => [...current, userMessage, assistantMessage]);
    const controller = new AbortController();
    abortRef.current = controller;
    let currentConversationId = conversationId;
    let streamCitations: Citation[] = [];
    let noEvidence = false;

    try {
      await streamAssistantChat({
        role,
        assistantId: activeAssistant.id,
        query,
        conversationId,
        browserToken,
        signal: controller.signal,
        onBrowserToken: saveBrowserToken,
        onEvent: ({ event, data }) => {
          if (event === "metadata") {
            if (typeof data.conversation_id === "string") {
              currentConversationId = data.conversation_id;
              setConversationId(data.conversation_id);
            }
            streamCitations = asCitations(data.citations);
            noEvidence = data.evidence_sufficient === false;
          } else if (event === "delta" && typeof data.content === "string") {
            setMessages((current) => current.map((message) => message.id === assistantMessageId
              ? { ...message, content: message.content + data.content, noEvidence }
              : message));
          } else if (event === "done") {
            setMessages((current) => current.map((message) => message.id === assistantMessageId
              ? { ...message, streaming: false, citations: streamCitations, noEvidence, usage: data.usage as ChatUsage | undefined }
              : message));
          } else if (event === "error") {
            setMessages((current) => current.map((message) => message.id === assistantMessageId
              ? { ...message, streaming: false, error: true, content: typeof data.message === "string" ? data.message : "对话运行失败。" }
              : message));
          }
        },
      });
      if (!controller.signal.aborted) {
        await queryClient.invalidateQueries({ queryKey: ["chat-conversations"] });
        if (currentConversationId) {
          await queryClient.invalidateQueries({ queryKey: ["chat-messages", role, browserToken, currentConversationId] });
        }
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setMessages((current) => current.map((message) => message.id === assistantMessageId
          ? { ...message, streaming: false, error: true, content: errorMessage(error) }
          : message));
      }
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
    }
  }

  function regenerate() {
    const lastUser = [...messages].reverse().find((message) => message.role === "user");
    if (lastUser && !isStreaming) void send(lastUser.content);
  }

  function selectAssistant(id: string) {
    const assistant = assistants.find((item) => item.id === id);
    setAssistantId(id);
    newConversation(assistant);
  }

  async function selectConversation(id: string, nextAssistantId: string) {
    setAssistantId(nextAssistantId);
    setConversationId(id);
    await queryClient.invalidateQueries({ queryKey: ["chat-messages", role, browserToken, id] });
  }

  if (assistantsQuery.isLoading) {
    return <Card className="m-6 h-72 animate-pulse bg-slate-50"><span className="sr-only">正在加载对话助手</span></Card>;
  }
  if (!activeAssistant) {
    return <div className="flex min-h-[60vh] items-center justify-center"><Card className="max-w-md p-8 text-center"><Bot className="mx-auto text-slate-300" size={32} /><h2 className="mt-4 font-semibold text-slate-900">暂无可用助手</h2><p className="mt-2 text-sm leading-6 text-slate-500">请由管理人员完成模型、知识库和助手发布后再开始对话。</p></Card></div>;
  }

  return (
    <div className="-m-5 -mt-6 flex h-[calc(100vh-72px)] overflow-hidden bg-white md:-m-8 md:-mt-8 fade-in">
      {sessionsOpen ? <aside className="hidden w-72 shrink-0 flex-col border-r border-slate-200 bg-slate-50/70 md:flex"><div className="border-b border-slate-200 p-4"><Button className="w-full" onClick={() => newConversation()}><MessageSquarePlus size={16} />新建会话</Button></div><div className="min-h-0 flex-1 overflow-y-auto p-3"><p className="px-2 py-2 text-[11px] font-medium uppercase tracking-wider text-slate-400">最近会话</p>{conversationsQuery.isLoading ? <p className="px-3 py-4 text-xs text-slate-400">正在加载…</p> : visibleConversations.map((conversation) => <button key={conversation.id} onClick={() => { void selectConversation(conversation.id, conversation.assistant_id); }} className={cn("mb-1 w-full rounded-lg px-3 py-3 text-left transition", conversation.id === conversationId ? "bg-white shadow-sm" : "hover:bg-white/70")}><span className={cn("block truncate text-sm", conversation.id === conversationId ? "font-medium text-slate-800" : "text-slate-600")}>{conversation.title ?? "未命名会话"}</span><small className="mt-1 block text-[11px] text-slate-400">{new Date(conversation.updated_at).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}</small></button>)}{!conversationsQuery.isLoading && visibleConversations.length === 0 ? <p className="px-3 py-4 text-xs leading-5 text-slate-400">当前助手还没有会话记录。</p> : null}</div><div className="border-t border-slate-200 p-4 text-[11px] leading-5 text-slate-400">会话历史仅与当前浏览器标识关联，不代表真实用户身份。</div></aside> : null}

      <section className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-[68px] shrink-0 items-center gap-3 border-b border-slate-200 px-4 md:px-6"><Button variant="ghost" size="icon" onClick={() => setSessionsOpen(!sessionsOpen)} aria-label={sessionsOpen ? "收起会话" : "展开会话"}><PanelLeftClose size={18} className={sessionsOpen ? "" : "rotate-180"} /></Button><span className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-600 text-sm font-semibold text-white">{activeAssistant.name.slice(0, 1)}</span><div className="min-w-0 flex-1"><div className="flex items-center gap-2"><h2 className="truncate text-sm font-semibold text-slate-900">{activeAssistant.name}</h2><span className="h-2 w-2 rounded-full bg-emerald-500" /></div><p className="truncate text-[11px] text-slate-400">{activeAssistant.knowledge_bases.map((item) => item.knowledge_base_name).join(" · ")} · {activeAssistant.llm_model_name}</p></div><Select value={activeAssistant.id} onChange={(event) => selectAssistant(event.target.value)} className="hidden h-9 w-48 sm:block">{assistants.map((assistant) => <option key={assistant.id} value={assistant.id}>{assistant.name}</option>)}</Select></header>

        <div className="min-h-0 flex-1 overflow-y-auto bg-slate-50/40">
          <div className="mx-auto max-w-3xl space-y-7 px-4 py-8 md:px-8">
            {sessionError ? <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{sessionError}</div> : null}
            {messagesQuery.isLoading ? <p className="text-center text-xs text-slate-400">正在读取会话历史…</p> : null}
            {messages.map((message) => <ChatMessage key={message.id} message={message} onCitation={setCitation} onCopy={() => { void navigator.clipboard?.writeText(message.content); notify("回答已复制", "已复制到系统剪贴板。"); }} onRegenerate={regenerate} />)}
            <div ref={bottomRef} />
          </div>
        </div>

        <footer className="shrink-0 border-t border-slate-200 bg-white px-4 py-4 md:px-6"><div className="mx-auto max-w-3xl"><div className="relative rounded-2xl border border-slate-200 bg-white p-2 shadow-lg shadow-slate-100 transition focus-within:border-indigo-300 focus-within:ring-4 focus-within:ring-indigo-50"><Textarea value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void send(); } }} rows={2} placeholder="向企业知识提问，Enter 发送，Shift + Enter 换行" className="border-0 pr-14 shadow-none focus:ring-0" /><div className="absolute bottom-3 right-3">{isStreaming ? <Button size="icon" onClick={stopStreaming} aria-label="停止生成"><Square size={15} fill="currentColor" /></Button> : <Button size="icon" onClick={() => { void send(); }} disabled={!input.trim() || !browserToken} aria-label="发送消息"><Send size={16} /></Button>}</div></div><div className="mt-2 flex items-center justify-center gap-1.5 text-[10px] text-slate-400"><ShieldCheck size={12} />回答严格基于已绑定知识库，重要信息请核对引用原文</div></div></footer>
      </section>

      <Drawer open={citation !== null} onOpenChange={(open) => { if (!open) setCitation(null); }} title="引用原文" description={citation ? `${citation.document_name} · ${citation.location}` : undefined}>{citation ? <div className="space-y-5 p-6"><div className="flex items-center justify-between"><Badge tone="green">已用于回答</Badge><Badge tone="amber">相关度 {citation.score.toFixed(4)}</Badge></div><div className="rounded-xl border border-slate-200 bg-slate-50 p-5"><p className="whitespace-pre-wrap text-sm leading-7 text-slate-700">{citation.excerpt}</p></div><div className="grid grid-cols-2 gap-3"><div className="rounded-lg bg-slate-50 p-3"><span className="block text-[11px] text-slate-400">来源位置</span><strong className="mt-1 block text-xs text-slate-700">{citation.location}</strong></div><div className="rounded-lg bg-slate-50 p-3"><span className="block text-[11px] text-slate-400">文档版本</span><strong className="mt-1 block text-xs text-slate-700">V{citation.document_version} · 分块 {citation.chunk_ordinal + 1}</strong></div></div><Button variant="secondary" className="w-full" disabled><ExternalLink size={15} />完整文档预览将在后续版本提供</Button></div> : null}</Drawer>
    </div>
  );
}

function ChatMessage({ message, onCitation, onCopy, onRegenerate }: { message: Message; onCitation: (citation: Citation) => void; onCopy: () => void; onRegenerate: () => void }) {
  if (message.role === "user") return <div className="flex justify-end"><div className="max-w-[85%] rounded-2xl rounded-tr-md bg-indigo-600 px-4 py-3 text-sm leading-6 text-white shadow-sm">{message.content}</div></div>;
  const tokenText = message.usage?.total_tokens != null
    ? `${message.usage.total_tokens.toLocaleString("zh-CN")} Tokens${message.usage.exact === false ? "（估算）" : ""}`
    : null;
  return <div className="flex gap-3"><span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-900 text-white"><Sparkles size={15} /></span><div className="min-w-0 flex-1"><div className={cn("text-sm leading-7 text-slate-700", message.noEvidence && "rounded-xl border border-amber-200 bg-amber-50 p-4 text-amber-900", message.error && "rounded-xl border border-red-200 bg-red-50 p-4 text-red-800")}><p className="whitespace-pre-wrap">{message.content}{message.streaming ? <span className="ml-1 inline-block h-4 w-1 animate-pulse rounded-full bg-indigo-500 align-middle" /> : null}</p>{message.citations?.length ? <div className="mt-4 flex flex-wrap gap-2">{message.citations.map((item) => <button key={`${item.chunk_id}:${item.index}`} onClick={() => onCitation(item)} className="inline-flex items-center gap-1.5 rounded-lg border border-indigo-100 bg-indigo-50 px-2.5 py-1.5 text-xs font-medium text-indigo-700 hover:bg-indigo-100"><FileText size={13} />[{item.index}] {item.document_name}</button>)}</div> : null}</div>{!message.streaming && !message.id.startsWith("greeting-") ? <div className="mt-3 flex items-center gap-1 text-slate-400"><Button variant="ghost" size="icon" className="h-7 w-7" onClick={onCopy} aria-label="复制回答"><Copy size={13} /></Button><Button variant="ghost" size="icon" className="h-7 w-7" onClick={onRegenerate} aria-label="重新生成"><RefreshCw size={13} /></Button>{tokenText ? <span className="ml-2 text-[10px]">{tokenText}</span> : null}</div> : null}</div></div>;
}
