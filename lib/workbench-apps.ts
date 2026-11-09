export type ApplicationCategoryId = "reports" | "support" | "review" | "marketing" | "office";

export type BusinessApplication = {
  id: string;
  category: ApplicationCategoryId;
  name: string;
  description: string;
  icon: "report" | "support" | "review" | "marketing" | "meeting" | "policy";
  taskPlaceholder: string;
  referenceLabel: string;
  referencePlaceholder: string;
  requirementsPlaceholder: string;
  examples: string[];
  steps: string[];
  keywords: string[];
};

export const applicationCategories = [
  { id: "reports", name: "报告撰写", description: "行业研究、经营分析、项目周报", accent: "bg-blue-500", color: "text-blue-600", soft: "bg-blue-50" },
  { id: "support", name: "智能客服", description: "产品咨询、售后政策、订单问题", accent: "bg-emerald-500", color: "text-emerald-600", soft: "bg-emerald-50" },
  { id: "review", name: "制度与合同审校", description: "合同风险、制度合规、条款比对", accent: "bg-amber-500", color: "text-amber-600", soft: "bg-amber-50" },
  { id: "marketing", name: "营销内容", description: "多渠道文案、活动方案、销售话术", accent: "bg-pink-500", color: "text-pink-600", soft: "bg-pink-50" },
  { id: "office", name: "办公提效", description: "会议纪要、邮件、制度问答", accent: "bg-violet-500", color: "text-violet-600", soft: "bg-violet-50" },
] as const;

export const businessApplications: BusinessApplication[] = [
  {
    id: "industry-report", category: "reports", name: "行业研究报告撰写", icon: "report",
    description: "围绕研究主题整理资料，形成报告提纲与撰写要求。",
    taskPlaceholder: "例如：2026 年企业 AI 知识库行业研究报告",
    referenceLabel: "研究背景与参考资料", referencePlaceholder: "填写研究范围、已有数据、参考资料及需要重点回答的问题。",
    requirementsPlaceholder: "说明报告读者、篇幅、时间范围、章节结构与引用要求。",
    examples: ["梳理行业研究报告提纲", "整理本周项目进展与风险", "对比主要竞品的产品定位"],
    steps: ["明确研究主题与范围", "整理参考资料与关键问题", "保存任务，或交给知识库助手继续处理"],
    keywords: ["报告", "行业", "研究", "分析", "周报", "竞品"],
  },
  {
    id: "customer-service", category: "support", name: "智能客服", icon: "support",
    description: "整理客户问题和服务背景，准备有依据的回复。",
    taskPlaceholder: "例如：为客户解释产品退换货政策",
    referenceLabel: "客户问题与服务背景", referencePlaceholder: "粘贴客户的具体问题，补充产品、订单或售后背景。",
    requirementsPlaceholder: "说明回复语气、服务边界及需要确认的信息。",
    examples: ["回答产品使用问题", "解释售后与退换货政策", "整理常见问题回复口径"],
    steps: ["记录客户问题与背景", "补充服务规则和回复要求", "选择已发布助手，依据知识库组织回复"],
    keywords: ["客服", "客户", "咨询", "售后", "订单", "产品问题", "退换货"],
  },
  {
    id: "contract-review", category: "review", name: "制度与合同审校", icon: "review",
    description: "整理待审文本与审查重点，准备条款核对任务。",
    taskPlaceholder: "例如：核对采购合同中的交付与验收条款",
    referenceLabel: "待审文本与比对依据", referencePlaceholder: "粘贴需要核对的条款，补充合同背景或制度依据。",
    requirementsPlaceholder: "列出审查范围、关注条款及希望使用的结果格式。",
    examples: ["核对交付与验收条款", "梳理制度执行中的疑点", "对比两版合同的主要差异"],
    steps: ["整理待审文本", "明确比对依据与关注范围", "保存审校任务，或结合知识库继续核对"],
    keywords: ["合同", "审校", "审查", "风险", "合规", "条款", "比对"],
  },
  {
    id: "marketing-content", category: "marketing", name: "营销内容创作", icon: "marketing",
    description: "整理受众、卖点与传播渠道，准备文案和活动任务。",
    taskPlaceholder: "例如：为新产品准备公众号推广文案",
    referenceLabel: "产品与活动资料", referencePlaceholder: "填写产品卖点、目标受众、活动背景及可引用的事实资料。",
    requirementsPlaceholder: "说明投放渠道、文案风格、篇幅和行动引导。",
    examples: ["准备产品推广文案", "梳理活动方案的核心信息", "整理销售沟通话术"],
    steps: ["明确传播目标与受众", "整理产品资料和渠道要求", "保存创作任务，或交给助手继续处理"],
    keywords: ["营销", "文案", "活动", "销售", "推广", "公众号", "话术"],
  },
  {
    id: "meeting-minutes", category: "office", name: "会议纪要整理", icon: "meeting",
    description: "整理会议记录、关键结论与待办事项。",
    taskPlaceholder: "例如：整理本周项目例会纪要",
    referenceLabel: "会议记录", referencePlaceholder: "粘贴会议文字记录或整理过的要点。",
    requirementsPlaceholder: "说明是否需要区分议题、决议、负责人和截止时间。",
    examples: ["提炼会议决议与待办事项", "按议题整理项目例会记录", "整理需要进一步确认的问题"],
    steps: ["补充会议主题与文字记录", "明确纪要结构和待办要求", "保存纪要任务，或交给助手继续整理"],
    keywords: ["会议", "纪要", "记录", "待办", "决议", "办公"],
  },
  {
    id: "policy-qa", category: "office", name: "制度问答助手", icon: "policy",
    description: "围绕企业制度提问，通过知识库助手查找制度依据。",
    taskPlaceholder: "例如：出差报销需要准备哪些材料？",
    referenceLabel: "问题背景与补充资料", referencePlaceholder: "填写适用部门、具体场景，以及你已掌握的制度内容。",
    requirementsPlaceholder: "说明是否需要列出办理步骤、所需材料和制度出处。",
    examples: ["查询出差报销的办理流程", "了解请假与考勤制度", "查找采购审批所需材料"],
    steps: ["描述具体制度问题", "补充部门和适用场景", "选择绑定制度知识库的助手继续问答"],
    keywords: ["制度", "问答", "报销", "请假", "考勤", "审批", "流程"],
  },
];

export const applicationHref = (id: string) => `#workbench/app/${encodeURIComponent(id)}`;
export const categoryHref = (id: ApplicationCategoryId) => `#workbench/category/${id}`;
export const workbenchHomeHref = "#workbench";

export function matchingApplications(search: string, category?: ApplicationCategoryId) {
  const query = search.trim().toLowerCase();
  return businessApplications.filter((app) => (!category || app.category === category) && (!query
    || `${app.name} ${app.description} ${app.keywords.join(" ")}`.toLowerCase().includes(query)
    || app.keywords.some((keyword) => query.includes(keyword))));
}

export type WorkbenchRoute = { type: "home" } | { type: "overview" } | { type: "app"; id: string } | { type: "category"; id: ApplicationCategoryId };

export function parseWorkbenchRoute(hash: string): WorkbenchRoute {
  if (hash === "#workbench/overview") return { type: "overview" };
  const match = /^#workbench\/(app|category)\/([^/]+)$/.exec(hash);
  if (!match) return { type: "home" };
  let id: string;
  try { id = decodeURIComponent(match[2]); } catch { return { type: "home" }; }
  if (match[1] === "app") return { type: "app", id };
  return applicationCategories.some((category) => category.id === id) ? { type: "category", id: id as ApplicationCategoryId } : { type: "home" };
}
