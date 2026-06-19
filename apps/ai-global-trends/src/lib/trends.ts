export type IndustryKey =
  | "all"
  | "ecommerce"
  | "tools"
  | "video"
  | "finance"
  | "enterprise"
  | "marketing";

export type TrendSourceType = "hacker-news" | "blog" | "community" | "product" | "research";

export type Industry = {
  key: IndustryKey;
  label: string;
  shortLabel: string;
  query: string;
  accent: string;
};

export type TrendItem = {
  id: string;
  title: string;
  source: string;
  sourceType: TrendSourceType;
  url: string;
  publishedAt: string;
  industry: IndustryKey;
  heatScore: number;
  growthScore: number;
  geography: string;
  tags: string[];
  summary: string;
  opportunity: string;
  signal: "live" | "seed";
  capturedAt: string;
  recordDate: string;
  comments?: number;
  points?: number;
};

type RawTrendItem = Omit<TrendItem, "capturedAt" | "recordDate">;

export type DateRecord = {
  key: string;
  label: string;
  itemCount: number;
  liveCount: number;
  topHeatScore: number;
  latestPublishedAt: string;
};

export type TrendSnapshot = {
  generatedAt: string;
  sourceStatus: "live-plus-seed" | "seed-only" | "live-unavailable";
  industries: Industry[];
  dateRecords: DateRecord[];
  items: TrendItem[];
};

type HackerNewsHit = {
  objectID?: string;
  title?: string | null;
  story_title?: string | null;
  url?: string | null;
  story_url?: string | null;
  created_at?: string | null;
  points?: number | null;
  num_comments?: number | null;
  author?: string | null;
};

export const INDUSTRIES: Industry[] = [
  {
    key: "all",
    label: "全站热榜",
    shortLabel: "全站",
    query: "AI startup global SaaS growth",
    accent: "#0877f2"
  },
  {
    key: "ecommerce",
    label: "跨境电商",
    shortLabel: "电商",
    query: "AI ecommerce Shopify sellers global",
    accent: "#00a884"
  },
  {
    key: "tools",
    label: "效率工具",
    shortLabel: "工具",
    query: "AI productivity tool startup",
    accent: "#ff6b35"
  },
  {
    key: "video",
    label: "视频内容",
    shortLabel: "视频",
    query: "AI video creator tool startup",
    accent: "#f2b705"
  },
  {
    key: "finance",
    label: "金融科技",
    shortLabel: "金融",
    query: "AI fintech compliance startup",
    accent: "#24a3ff"
  },
  {
    key: "enterprise",
    label: "企业服务",
    shortLabel: "企服",
    query: "AI enterprise SaaS agent startup",
    accent: "#30b77c"
  },
  {
    key: "marketing",
    label: "营销服务",
    shortLabel: "营销",
    query: "AI marketing automation growth startup",
    accent: "#f06449"
  }
];

const SEED_TRENDS: RawTrendItem[] = [
  {
    id: "seed:ecommerce:agentic-storefront",
    title: "AI 店铺运营从文案工具转向自动化商品实验",
    source: "Seed Market Signal",
    sourceType: "blog",
    url: "https://news.ycombinator.com/",
    publishedAt: "2026-06-18T00:30:00.000Z",
    industry: "ecommerce",
    heatScore: 88,
    growthScore: 91,
    geography: "North America / SEA",
    tags: ["Shopify", "A/B testing", "agent commerce"],
    summary: "跨境卖家正在把 AI 用到 SKU 命名、落地页实验、评论摘要和邮件召回，机会点从单点生成转向运营闭环。",
    opportunity: "适合切入面向中小卖家的轻量增长代理，按 GMV 或实验量计费。",
    signal: "seed"
  },
  {
    id: "seed:tools:solo-saas",
    title: "独立开发者工具产品开始强调可验证工作流，而不是单次聊天",
    source: "Seed Builder Signal",
    sourceType: "community",
    url: "https://www.indiehackers.com/",
    publishedAt: "2026-06-17T22:20:00.000Z",
    industry: "tools",
    heatScore: 84,
    growthScore: 87,
    geography: "Global",
    tags: ["solo SaaS", "workflow", "developer tools"],
    summary: "用户更愿意为能持续执行、可回放、有状态的 AI 工具付费，单纯 prompt wrapper 的吸引力下降。",
    opportunity: "优先设计任务状态、失败恢复、审计记录和团队协作，而不是堆模型入口。",
    signal: "seed"
  },
  {
    id: "seed:video:shorts-localization",
    title: "短视频 AI 出海的下一波增长来自本地化改写与多平台分发",
    source: "Seed Creator Signal",
    sourceType: "product",
    url: "https://www.producthunt.com/",
    publishedAt: "2026-06-17T18:10:00.000Z",
    industry: "video",
    heatScore: 82,
    growthScore: 89,
    geography: "US / LATAM / Japan",
    tags: ["TikTok", "shorts", "localization"],
    summary: "视频生成本身已经拥挤，商业机会更靠近脚本改写、字幕本地化、账号矩阵和投放反馈。",
    opportunity: "用行业模板和地域口味模型服务跨境品牌，而不是只做通用视频生成。",
    signal: "seed"
  },
  {
    id: "seed:finance:risk-agent",
    title: "AI 金融工具的买点集中在合规审查、异常检测和报告自动化",
    source: "Seed Analyst Signal",
    sourceType: "research",
    url: "https://www.cbinsights.com/research/",
    publishedAt: "2026-06-17T14:45:00.000Z",
    industry: "finance",
    heatScore: 79,
    growthScore: 83,
    geography: "US / EU",
    tags: ["compliance", "risk ops", "reporting"],
    summary: "金融客户对幻觉容忍度低，稳定需求来自流程内的证据整理、规则检查和人工复核提效。",
    opportunity: "必须把来源、版本、审批和权限作为产品核心，而不是外层补丁。",
    signal: "seed"
  },
  {
    id: "seed:enterprise:agent-control-plane",
    title: "企业 AI Agent 市场从 demo 竞争转向控制面竞争",
    source: "Seed Enterprise Signal",
    sourceType: "blog",
    url: "https://a16z.com/ai/",
    publishedAt: "2026-06-17T11:00:00.000Z",
    industry: "enterprise",
    heatScore: 92,
    growthScore: 88,
    geography: "US / Europe",
    tags: ["AI agents", "governance", "SaaS"],
    summary: "企业客户开始要求权限、工具边界、执行追踪、成本控制和回滚，成熟 agent 架构成为采购门槛。",
    opportunity: "面向垂直行业做受控 agent 工作台，比泛用聊天入口更容易形成高客单价。",
    signal: "seed"
  },
  {
    id: "seed:marketing:ugc-pipeline",
    title: "AI 营销服务的新热点是从素材生成走向可归因投放流水线",
    source: "Seed Growth Signal",
    sourceType: "community",
    url: "https://www.reddit.com/r/marketing/",
    publishedAt: "2026-06-17T08:15:00.000Z",
    industry: "marketing",
    heatScore: 86,
    growthScore: 90,
    geography: "Global",
    tags: ["UGC", "ad creative", "attribution"],
    summary: "市场不缺生成素材，缺的是把受众洞察、素材变体、投放结果和复盘连接起来的系统。",
    opportunity: "以广告账户和素材库为中心做闭环，商业价值高于单次生成。",
    signal: "seed"
  }
];

export function buildSeedSnapshot(industry: IndustryKey = "all"): TrendSnapshot {
  return buildSnapshot("seed-only", filterByIndustry(SEED_TRENDS, industry));
}

export async function getTrendSnapshot(industry: IndustryKey = "all"): Promise<TrendSnapshot> {
  const seedItems = filterByIndustry(SEED_TRENDS, industry);

  if (process.env.DISABLE_LIVE_FETCH === "1") {
    return buildSnapshot("seed-only", seedItems);
  }

  try {
    const liveItems = await fetchHackerNewsTrends(industry);
    const items = dedupeTrends<RawTrendItem>([...liveItems, ...seedItems])
      .sort((a, b) => b.heatScore - a.heatScore)
      .slice(0, 24);

    return buildSnapshot(liveItems.length > 0 ? "live-plus-seed" : "seed-only", items);
  } catch {
    return buildSnapshot("live-unavailable", seedItems);
  }
}

export function parseIndustryKey(value: string | null): IndustryKey {
  const normalized = String(value || "all").trim().toLowerCase();
  return INDUSTRIES.some((industry) => industry.key === normalized)
    ? (normalized as IndustryKey)
    : "all";
}

function buildSnapshot(sourceStatus: TrendSnapshot["sourceStatus"], rawItems: RawTrendItem[]): TrendSnapshot {
  const generatedAt = new Date().toISOString();
  const items = rawItems.map((item) => normalizeTrendItem(item, generatedAt));

  return {
    generatedAt,
    sourceStatus,
    industries: INDUSTRIES,
    dateRecords: buildDateRecords(items),
    items
  };
}

function normalizeTrendItem(item: RawTrendItem, capturedAt: string): TrendItem {
  return {
    ...item,
    capturedAt,
    recordDate: dateKeyFromIso(item.publishedAt)
  };
}

export function dateKeyFromIso(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "unknown";

  const parts = new Intl.DateTimeFormat("en-CA", {
    day: "2-digit",
    month: "2-digit",
    timeZone: "Asia/Shanghai",
    year: "numeric"
  }).formatToParts(date);

  const year = parts.find((part) => part.type === "year")?.value || "0000";
  const month = parts.find((part) => part.type === "month")?.value || "00";
  const day = parts.find((part) => part.type === "day")?.value || "00";
  return `${year}-${month}-${day}`;
}

function buildDateRecords(items: TrendItem[]): DateRecord[] {
  const buckets = new Map<string, TrendItem[]>();

  for (const item of items) {
    const key = item.recordDate;
    buckets.set(key, [...(buckets.get(key) || []), item]);
  }

  return [...buckets.entries()]
    .map(([key, bucket]) => {
      const sorted = [...bucket].sort(
        (a, b) => new Date(b.publishedAt).getTime() - new Date(a.publishedAt).getTime()
      );
      return {
        key,
        label: formatDateRecordLabel(key),
        itemCount: bucket.length,
        liveCount: bucket.filter((item) => item.signal === "live").length,
        topHeatScore: Math.max(...bucket.map((item) => item.heatScore)),
        latestPublishedAt: sorted[0]?.publishedAt || ""
      };
    })
    .sort((a, b) => b.key.localeCompare(a.key));
}

function formatDateRecordLabel(key: string): string {
  if (key === "unknown") return "未知日期";
  const [, month, day] = key.split("-");
  return `${month}/${day}`;
}

function filterByIndustry<T extends { industry: IndustryKey }>(items: T[], industry: IndustryKey): T[] {
  if (industry === "all") return items;
  return items.filter((item) => item.industry === industry);
}

async function fetchHackerNewsTrends(industry: IndustryKey): Promise<RawTrendItem[]> {
  const config = INDUSTRIES.find((item) => item.key === industry) ?? INDUSTRIES[0];
  const endpoint = new URL("https://hn.algolia.com/api/v1/search_by_date");
  endpoint.searchParams.set("query", config.query);
  endpoint.searchParams.set("tags", "story");
  endpoint.searchParams.set("hitsPerPage", industry === "all" ? "14" : "10");
  endpoint.searchParams.set("numericFilters", `created_at_i>${recentUnixSeconds(30)}`);

  const response = await fetch(endpoint, {
    headers: {
      accept: "application/json",
      "user-agent": "ai-global-trends-mvp"
    },
    next: {
      revalidate: 900
    }
  });

  if (!response.ok) {
    throw new Error(`Hacker News connector failed with ${response.status}`);
  }

  const payload = (await response.json()) as { hits?: HackerNewsHit[] };
  return (payload.hits || [])
    .map((hit) => mapHackerNewsHit(hit, industry))
    .filter((item): item is RawTrendItem => Boolean(item));
}

function mapHackerNewsHit(hit: HackerNewsHit, industry: IndustryKey): RawTrendItem | null {
  const title = cleanText(hit.title || hit.story_title || "");
  const url = hit.url || hit.story_url || "";
  const publishedAt = hit.created_at || "";

  if (!title || !publishedAt) return null;

  const comments = Math.max(0, Number(hit.num_comments || 0));
  const points = Math.max(0, Number(hit.points || 0));
  const normalizedIndustry = industry === "all" ? inferIndustry(title) : industry;
  const tags = industryTags(normalizedIndustry);

  return {
    id: `hn:${hit.objectID || title}`,
    title,
    source: hit.author ? `Hacker News / ${hit.author}` : "Hacker News",
    sourceType: "hacker-news",
    url: url || `https://news.ycombinator.com/item?id=${hit.objectID}`,
    publishedAt,
    industry: normalizedIndustry,
    heatScore: scoreHackerNewsItem(points, comments, publishedAt),
    growthScore: Math.min(98, Math.round(56 + Math.log2(points + comments + 2) * 8)),
    geography: "Global builder community",
    tags,
    summary: `开发者社区正在讨论这个方向。当前互动为 ${points} points / ${comments} comments，可作为早期趋势温度信号。`,
    opportunity: opportunityForIndustry(normalizedIndustry),
    signal: "live",
    comments,
    points
  };
}

function inferIndustry(title: string): IndustryKey {
  const lower = title.toLowerCase();
  if (lower.includes("shopify") || lower.includes("commerce") || lower.includes("store")) return "ecommerce";
  if (lower.includes("video") || lower.includes("creator") || lower.includes("youtube")) return "video";
  if (lower.includes("fintech") || lower.includes("bank") || lower.includes("compliance")) return "finance";
  if (lower.includes("marketing") || lower.includes("seo") || lower.includes("ads")) return "marketing";
  if (lower.includes("enterprise") || lower.includes("agent") || lower.includes("workflow")) return "enterprise";
  return "tools";
}

function scoreHackerNewsItem(points: number, comments: number, publishedAt: string): number {
  const ageHours = Math.max(0, (Date.now() - new Date(publishedAt).getTime()) / 36e5);
  const engagement = Math.min(48, Math.log2(points + comments * 2 + 2) * 7);
  const freshness = Math.max(0, 32 - ageHours) * 0.75;
  return Math.max(42, Math.min(98, Math.round(30 + engagement + freshness)));
}

function recentUnixSeconds(days: number): number {
  return Math.floor((Date.now() - days * 24 * 60 * 60 * 1000) / 1000);
}

function industryTags(industry: IndustryKey): string[] {
  const tags: Record<IndustryKey, string[]> = {
    all: ["AI", "global", "startup"],
    ecommerce: ["commerce", "global sellers", "conversion"],
    tools: ["productivity", "SaaS", "workflow"],
    video: ["creator", "short video", "localization"],
    finance: ["fintech", "compliance", "risk"],
    enterprise: ["enterprise", "agent ops", "governance"],
    marketing: ["growth", "creative ops", "automation"]
  };
  return tags[industry];
}

function opportunityForIndustry(industry: IndustryKey): string {
  const map: Record<IndustryKey, string> = {
    all: "优先观察是否能沉淀为高频刚需、可付费 workflow，而不是一次性内容消费。",
    ecommerce: "关注中小跨境商家的自动化运营、转化实验和多市场本地化。",
    tools: "将 AI 能力包装成可验证、可复用、可协作的工作流，更容易商业化。",
    video: "从生成能力外移到本地化分发、账号运营和素材复盘，机会更清晰。",
    finance: "以合规证据、审计链路和人工复核体验为核心设计产品边界。",
    enterprise: "企业买单点在控制面、权限、可追踪执行和稳定集成。",
    marketing: "素材生成要接入归因和投放反馈，才能从工具费走向增长预算。"
  };
  return map[industry];
}

function dedupeTrends<T extends { title: string; url: string }>(items: T[]): T[] {
  const seen = new Set<string>();
  const result: T[] = [];

  for (const item of items) {
    const key = `${item.url || ""}:${item.title.toLowerCase()}`;
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(item);
  }

  return result;
}

function cleanText(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}
