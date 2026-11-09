import type { Assistant, KnowledgeBase } from "@/lib/types";

export const knowledgeBases: KnowledgeBase[] = [
  {
    id: "kb-hr",
    name: "人力制度中心",
    description: "员工手册、考勤、休假、报销与福利制度",
    icon: "人",
    tone: "bg-indigo-600",
    documents: 42,
    chunks: 3284,
    updatedAt: "今天 10:24",
    embedding: "qwen3-embedding-8b",
    state: "ready",
  },
  {
    id: "kb-product",
    name: "产品知识库",
    description: "产品说明、交付手册、常见问题与版本记录",
    icon: "产",
    tone: "bg-cyan-600",
    documents: 68,
    chunks: 8126,
    updatedAt: "昨天 18:12",
    embedding: "text-embedding-v4",
    state: "building",
  },
  {
    id: "kb-sales",
    name: "销售支持资料",
    description: "解决方案、行业案例、报价规则与投标材料",
    icon: "销",
    tone: "bg-amber-500",
    documents: 25,
    chunks: 1946,
    updatedAt: "10 月 24 日",
    embedding: "qwen3-embedding-8b",
    state: "ready",
  },
  {
    id: "kb-training",
    name: "员工培训资料",
    description: "等待导入首批课程与培训讲义",
    icon: "培",
    tone: "bg-slate-500",
    documents: 0,
    chunks: 0,
    updatedAt: "刚刚创建",
    embedding: "qwen3-embedding-8b",
    state: "empty",
  },
];

export const assistants: Assistant[] = [
  {
    id: "assistant-hr",
    name: "员工服务助手",
    description: "回答考勤、请假、报销与员工福利问题",
    avatar: "员",
    knowledgeBases: ["人力制度中心"],
    model: "Claude Sonnet 4.5",
    sessions: 1286,
    updatedAt: "5 分钟前",
    status: "online",
  },
  {
    id: "assistant-product",
    name: "产品顾问",
    description: "为售前和交付团队提供产品能力与实施建议",
    avatar: "顾",
    knowledgeBases: ["产品知识库", "销售支持资料"],
    model: "Qwen3-Max",
    sessions: 864,
    updatedAt: "昨天 16:40",
    status: "online",
  },
  {
    id: "assistant-bid",
    name: "投标材料助手",
    description: "基于标准资料辅助查找投标问题答案",
    avatar: "标",
    knowledgeBases: ["销售支持资料"],
    model: "GPT-5 mini",
    sessions: 0,
    updatedAt: "草稿未发布",
    status: "draft",
  },
];

export const documents = [
  { name: "员工报销管理办法.pdf", type: "PDF", size: "3.8 MB", chunks: 86, state: "ready", updatedAt: "10:24", route: "云端增强" },
  { name: "2026 年员工福利手册.docx", type: "Word", size: "1.2 MB", chunks: 54, state: "ready", updatedAt: "09:48", route: "本地解析" },
  { name: "差旅标准明细.xlsx", type: "Excel", size: "824 KB", chunks: 31, state: "ready", updatedAt: "昨天", route: "本地解析" },
  { name: "考勤制度补充说明.md", type: "Markdown", size: "18 KB", chunks: 12, state: "ready", updatedAt: "昨天", route: "本地解析" },
  { name: "组织架构与职责.pdf", type: "PDF", size: "12.4 MB", chunks: 0, state: "failed", updatedAt: "10 月 24 日", route: "云端增强" },
];

export const retrievalResults = [
  {
    title: "员工报销管理办法.pdf",
    location: "第 4 页 · 第 3.2 节 交通费用",
    content: "员工因公出差产生的交通费用，应在行程结束后 10 个工作日内提交报销。市内交通可凭合规票据据实报销，单次超过 200 元需补充行程说明。",
    semantic: 0.82,
    rerank: 0.94,
    used: true,
  },
  {
    title: "差旅标准明细.xlsx",
    location: "差旅标准 · B12:F18",
    content: "一线城市市内交通每日限额 200 元，其他城市每日限额 150 元；确因业务需要超出标准时，须由部门负责人审批。",
    semantic: 0.76,
    rerank: 0.88,
    used: true,
  },
  {
    title: "2026 年员工福利手册.docx",
    location: "费用报销 · 第 2 段",
    content: "报销申请应附发票、支付凭证及对应审批记录。材料不完整时，财务人员可退回申请并说明需要补充的材料。",
    semantic: 0.71,
    rerank: 0.77,
    used: true,
  },
];

export const runLogs = [
  { id: "RUN-10286", query: "出差打车费可以报销吗？", assistant: "员工服务助手", model: "Claude Sonnet 4.5", tokens: 1864, latency: "2.84s", status: "success", time: "10:32:18" },
  { id: "RUN-10285", query: "产品支持哪些部署方式？", assistant: "产品顾问", model: "Qwen3-Max", tokens: 2342, latency: "3.16s", status: "success", time: "10:29:43" },
  { id: "RUN-10284", query: "海外项目的投标授权流程", assistant: "投标材料助手", model: "GPT-5 mini", tokens: 428, latency: "0.91s", status: "no_evidence", time: "10:27:04" },
  { id: "RUN-10283", query: "年假最多可以结转几天？", assistant: "员工服务助手", model: "Claude Sonnet 4.5", tokens: 0, latency: "8.02s", status: "error", time: "10:22:31" },
];
