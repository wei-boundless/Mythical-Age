"use client";

import {
  ArrowUpRight,
  CreditCard,
  ExternalLink,
  Filter,
  Globe2,
  Mail,
  Radio,
  Search,
  Sparkles,
  TrendingUp,
  Zap
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";

import type { DateRecord, Industry, IndustryKey, TrendItem, TrendSnapshot } from "@/lib/trends";

type TrendDashboardProps = {
  initialSnapshot: TrendSnapshot;
};

type CheckoutState = {
  tone: "idle" | "loading" | "success" | "error";
  message: string;
};

const SOURCE_LABELS: Record<TrendSnapshot["sourceStatus"], string> = {
  "live-plus-seed": "Live signals",
  "seed-only": "Seed intelligence",
  "live-unavailable": "Live fallback"
};

type LooseTrendSnapshot = Partial<Omit<TrendSnapshot, "dateRecords" | "industries" | "items">> & {
  dateRecords?: Partial<DateRecord>[];
  industries?: Industry[];
  items?: Partial<TrendItem>[];
};

export function TrendDashboard({ initialSnapshot }: TrendDashboardProps) {
  const [selectedIndustry, setSelectedIndustry] = useState<IndustryKey>("all");
  const [selectedDate, setSelectedDate] = useState("all");
  const [snapshot, setSnapshot] = useState<TrendSnapshot>(() => normalizeSnapshot(initialSnapshot, initialSnapshot));
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [keyword, setKeyword] = useState("AI ecommerce agents");
  const [email, setEmail] = useState("");
  const [checkout, setCheckout] = useState<CheckoutState>({
    tone: "idle",
    message: "$5/月，按关键词发送每日机会清单"
  });
  const snapshotView = useMemo(() => normalizeSnapshot(snapshot, initialSnapshot), [initialSnapshot, snapshot]);

  useEffect(() => {
    let active = true;

    fetch(`/api/trends?industry=${selectedIndustry}`)
      .then((response) => {
        if (!response.ok) throw new Error("趋势接口暂时不可用");
        return response.json() as Promise<TrendSnapshot>;
      })
      .then((nextSnapshot) => {
        if (active) setSnapshot(normalizeSnapshot(nextSnapshot, initialSnapshot));
      })
      .catch(() => {
        if (active) {
          setSnapshot((current) =>
            normalizeSnapshot(
              {
                ...current,
                sourceStatus: "live-unavailable"
              },
              initialSnapshot
            )
          );
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [initialSnapshot, selectedIndustry]);

  function handleIndustryChange(industry: IndustryKey) {
    if (industry === selectedIndustry) return;
    setLoading(true);
    setSelectedDate("all");
    setSelectedIndustry(industry);
  }

  const visibleItems = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    const industryItems =
      selectedIndustry === "all"
        ? snapshotView.items
        : snapshotView.items.filter((item) => item.industry === selectedIndustry);

    const datedItems =
      selectedDate === "all"
        ? industryItems
        : industryItems.filter((item) => item.recordDate === selectedDate);

    if (!query) return datedItems;

    return datedItems.filter((item) => {
      const haystack = [item.title, item.summary, item.opportunity, item.source, ...item.tags]
        .join(" ")
        .toLowerCase();
      return haystack.includes(query);
    });
  }, [searchQuery, selectedDate, selectedIndustry, snapshotView.items]);

  const topItem = visibleItems[0] || snapshotView.items[0];
  const liveCount = visibleItems.filter((item) => item.signal === "live").length;
  const averageHeat = visibleItems.length
    ? Math.round(visibleItems.reduce((sum, item) => sum + item.heatScore, 0) / visibleItems.length)
    : 0;

  async function handleCheckout(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCheckout({ tone: "loading", message: "正在创建安全付款链接..." });

    try {
      const response = await fetch("/api/checkout", {
        method: "POST",
        headers: {
          "content-type": "application/json"
        },
        body: JSON.stringify({
          email,
          industry: selectedIndustry,
          keyword
        })
      });
      const payload = (await response.json()) as { checkoutUrl?: string; error?: string };

      if (!response.ok || !payload.checkoutUrl) {
        throw new Error(payload.error || "付款链接创建失败。");
      }

      setCheckout({ tone: "success", message: "付款链接已创建，即将跳转 Stripe。" });
      window.location.assign(payload.checkoutUrl);
    } catch (error) {
      setCheckout({
        tone: "error",
        message: error instanceof Error ? error.message : "付款链接创建失败。"
      });
    }
  }

  return (
    <main className="site-shell">
      <section className="hero-band">
        <div className="topbar">
          <a className="brand" href="#" aria-label="AI Global Trends">
            <span className="brand-mark">
              <Globe2 size={18} strokeWidth={2.4} />
            </span>
            <span>
              <strong>AI Global Trends</strong>
              <small>出海热文雷达</small>
            </span>
          </a>
          <nav className="nav-actions" aria-label="site">
            <a href="#trends">热榜</a>
            <a href="#daily">日报</a>
            <a href="#sources">信号源</a>
          </nav>
          <div className="live-pill" aria-live="polite">
            <Radio size={15} />
            <span>{SOURCE_LABELS[snapshotView.sourceStatus]}</span>
          </div>
        </div>

        <div className="hero-grid">
          <div className="hero-copy">
            <div className="eyebrow">
              <Sparkles size={16} />
              Global AI venture intelligence
            </div>
            <h1>
              <span>AI 出海</span>
              <span>热文雷达</span>
            </h1>
            <p className="hero-lede">
              跟踪全球开发者社区、产品发布、增长案例和商业化讨论，把碎片化热文整理成可判断的行业机会。
            </p>

            <div className="hero-search" role="search">
              <Search size={18} />
              <input
                aria-label="搜索热文关键词"
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="搜索 agents、Shopify、video、SaaS..."
                value={searchQuery}
              />
            </div>

            <div className="metric-strip">
              <Metric icon={<TrendingUp size={17} />} label="Heat" value={averageHeat || "--"} />
              <Metric icon={<Zap size={17} />} label="Live" value={liveCount} />
              <Metric icon={<Filter size={17} />} label="Days" value={snapshotView.dateRecords.length} />
            </div>
          </div>

          <SignalBoard items={visibleItems} />
        </div>
      </section>

      <section className="content-band" id="trends">
        <div className="industry-rail" aria-label="行业分类">
          {snapshotView.industries.map((industry) => (
            <button
              className={industry.key === selectedIndustry ? "industry-button is-active" : "industry-button"}
              key={industry.key}
              onClick={() => handleIndustryChange(industry.key)}
              style={{ "--industry-accent": industry.accent } as React.CSSProperties}
              type="button"
            >
              <Sparkles size={14} />
              <span>{industry.label}</span>
            </button>
          ))}
        </div>

        <div className="date-records" aria-label="日期记录">
          <button
            className={selectedDate === "all" ? "date-record is-active" : "date-record"}
            onClick={() => setSelectedDate("all")}
            type="button"
          >
            <span>全部日期</span>
            <strong>{snapshotView.items.length}</strong>
            <small>records</small>
          </button>
          {snapshotView.dateRecords.map((record) => (
            <button
              className={selectedDate === record.key ? "date-record is-active" : "date-record"}
              key={record.key}
              onClick={() => setSelectedDate(record.key)}
              type="button"
            >
              <span>{record.label}</span>
              <strong>{record.itemCount}</strong>
              <small>{record.liveCount} live · heat {record.topHeatScore}</small>
            </button>
          ))}
        </div>

        <div className="workbench-grid">
          <section className="trend-feed" aria-busy={loading}>
            <div className="section-heading">
              <div>
                <span className="section-kicker">Market heat</span>
                <h2>今日热文与机会信号</h2>
              </div>
              <span className="refresh-note">
                {loading ? "刷新中" : `更新于 ${formatTime(snapshotView.generatedAt)}`}
              </span>
            </div>

            <div className="trend-list">
              {visibleItems.length > 0 ? (
                visibleItems.map((item, index) => <TrendCard item={item} key={item.id} rank={index + 1} />)
              ) : (
                <div className="empty-state">
                  <Search size={24} />
                  <p>当前筛选没有匹配结果。</p>
                </div>
              )}
            </div>
          </section>

          <aside className="right-rail">
            <section className="insight-panel">
              <div className="section-heading compact">
                <span className="section-kicker">Top signal</span>
                <h2>最强机会</h2>
              </div>
              {topItem ? (
                <div className="top-signal">
                  <span className="signal-score">{topItem.heatScore}</span>
                  <h3>{topItem.title}</h3>
                  <p>{topItem.opportunity}</p>
                  <a href={topItem.url} rel="noreferrer" target="_blank">
                    原文信号
                    <ArrowUpRight size={15} />
                  </a>
                </div>
              ) : null}
            </section>

            <section className="subscribe-panel" id="daily">
              <div className="section-heading compact">
                <span className="section-kicker">Daily brief</span>
                <h2>关键词日报</h2>
              </div>
              <form onSubmit={handleCheckout}>
                <label>
                  <span>追踪关键词</span>
                  <input
                    onChange={(event) => setKeyword(event.target.value)}
                    value={keyword}
                    placeholder="AI marketing automation"
                  />
                </label>
                <label>
                  <span>接收邮箱</span>
                  <input
                    onChange={(event) => setEmail(event.target.value)}
                    type="email"
                    value={email}
                    placeholder="founder@company.com"
                  />
                </label>
                <button className="checkout-button" disabled={checkout.tone === "loading"} type="submit">
                  <CreditCard size={17} />
                  <span>订阅 $5/月</span>
                </button>
              </form>
              <p className={`checkout-message ${checkout.tone}`}>
                <Mail size={14} />
                {checkout.message}
              </p>
            </section>

            <section className="source-panel" id="sources">
              <div className="source-row">
                <span>HN</span>
                <strong>{snapshotView.sourceStatus === "live-plus-seed" ? "active" : "standby"}</strong>
              </div>
              <div className="source-row">
                <span>RSS / Blogs</span>
                <strong>ready</strong>
              </div>
              <div className="source-row">
                <span>Search API</span>
                <strong>contract</strong>
              </div>
              <div className="source-row">
                <span>Stripe</span>
                <strong>env gated</strong>
              </div>
              <div className="source-row">
                <span>Date records</span>
                <strong>{snapshotView.dateRecords.length} days</strong>
              </div>
            </section>
          </aside>
        </div>
      </section>
    </main>
  );
}

function normalizeSnapshot(input: LooseTrendSnapshot | null | undefined, fallback: TrendSnapshot): TrendSnapshot {
  const fallbackItems = Array.isArray(fallback.items) ? fallback.items : [];
  const fallbackIndustries = Array.isArray(fallback.industries) ? fallback.industries : [];
  const generatedAt = safeText(input?.generatedAt) || safeText(fallback.generatedAt) || new Date().toISOString();
  const rawItems = Array.isArray(input?.items) ? input.items : fallbackItems;
  const items = rawItems
    .map((item, index) => normalizeTrendItem(item, generatedAt, index))
    .filter((item): item is TrendItem => Boolean(item));
  const providedDateRecords = Array.isArray(input?.dateRecords)
    ? input.dateRecords
        .map((record) => normalizeDateRecord(record))
        .filter((record): record is DateRecord => Boolean(record))
    : [];

  return {
    generatedAt,
    sourceStatus: normalizeSourceStatus(input?.sourceStatus || fallback.sourceStatus),
    industries: Array.isArray(input?.industries) && input.industries.length > 0 ? input.industries : fallbackIndustries,
    dateRecords: providedDateRecords.length > 0 ? providedDateRecords : buildDateRecordsFromItems(items),
    items
  };
}

function normalizeTrendItem(
  item: Partial<TrendItem> | null | undefined,
  capturedAt: string,
  index: number
): TrendItem | null {
  if (!item) return null;

  const title = safeText(item.title) || "Untitled AI signal";
  const publishedAt = safeIsoDate(item.publishedAt, capturedAt);
  const recordDate = safeText(item.recordDate) || dateKeyFromIso(publishedAt);
  const source = safeText(item.source) || "Unknown source";

  return {
    id: safeText(item.id) || `trend:${source}:${title}:${index}`,
    title,
    source,
    sourceType: normalizeSourceType(item.sourceType),
    url: safeText(item.url) || "#",
    publishedAt,
    industry: normalizeIndustryKey(item.industry),
    heatScore: clampScore(item.heatScore, 50),
    growthScore: clampScore(item.growthScore, 50),
    geography: safeText(item.geography) || "Global",
    tags: Array.isArray(item.tags) ? item.tags.map((tag) => safeText(tag)).filter(Boolean) : ["AI"],
    summary: safeText(item.summary) || "这条信号暂时缺少摘要，已保留为待分析记录。",
    opportunity: safeText(item.opportunity) || "需要补充来源上下文后再判断商业机会。",
    signal: item.signal === "live" ? "live" : "seed",
    capturedAt: safeIsoDate(item.capturedAt, capturedAt),
    recordDate,
    comments: normalizeOptionalNumber(item.comments),
    points: normalizeOptionalNumber(item.points)
  };
}

function normalizeDateRecord(record: Partial<DateRecord> | null | undefined): DateRecord | null {
  if (!record) return null;
  const key = safeText(record.key);
  if (!key) return null;

  return {
    key,
    label: safeText(record.label) || formatDateKey(key),
    itemCount: Math.max(0, Math.round(Number(record.itemCount || 0))),
    liveCount: Math.max(0, Math.round(Number(record.liveCount || 0))),
    topHeatScore: clampScore(record.topHeatScore, 0),
    latestPublishedAt: safeText(record.latestPublishedAt) || ""
  };
}

function buildDateRecordsFromItems(items: TrendItem[]): DateRecord[] {
  const buckets = new Map<string, TrendItem[]>();

  for (const item of items) {
    const key = item.recordDate || dateKeyFromIso(item.publishedAt);
    buckets.set(key, [...(buckets.get(key) || []), item]);
  }

  return [...buckets.entries()]
    .map(([key, bucket]) => {
      const sorted = [...bucket].sort(
        (a, b) => new Date(b.publishedAt).getTime() - new Date(a.publishedAt).getTime()
      );
      return {
        key,
        label: formatDateKey(key),
        itemCount: bucket.length,
        liveCount: bucket.filter((item) => item.signal === "live").length,
        topHeatScore: Math.max(0, ...bucket.map((item) => item.heatScore)),
        latestPublishedAt: sorted[0]?.publishedAt || ""
      };
    })
    .sort((a, b) => b.key.localeCompare(a.key));
}

function normalizeSourceStatus(value: unknown): TrendSnapshot["sourceStatus"] {
  if (value === "live-plus-seed" || value === "seed-only" || value === "live-unavailable") return value;
  return "seed-only";
}

function normalizeSourceType(value: unknown): TrendItem["sourceType"] {
  if (value === "hacker-news" || value === "blog" || value === "community" || value === "product" || value === "research") {
    return value;
  }
  return "blog";
}

function normalizeIndustryKey(value: unknown): IndustryKey {
  if (
    value === "all" ||
    value === "ecommerce" ||
    value === "tools" ||
    value === "video" ||
    value === "finance" ||
    value === "enterprise" ||
    value === "marketing"
  ) {
    return value;
  }
  return "tools";
}

function normalizeOptionalNumber(value: unknown): number | undefined {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function clampScore(value: unknown, fallback: number): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(0, Math.min(100, Math.round(parsed)));
}

function safeText(value: unknown): string {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function safeIsoDate(value: unknown, fallback: string): string {
  const text = safeText(value);
  const date = new Date(text);
  if (!Number.isNaN(date.getTime())) return date.toISOString();
  return fallback;
}

function Metric({
  icon,
  label,
  value
}: {
  icon: React.ReactNode;
  label: string;
  value: number | string;
}) {
  return (
    <div className="metric">
      {icon}
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function SignalBoard({ items }: { items: TrendItem[] }) {
  const leaders = items.slice(0, 5);
  return (
    <div className="signal-board" aria-label="全球 AI 出海热度信号">
      <div className="board-header">
        <span>Global signal board</span>
        <strong>{leaders[0]?.heatScore || "--"}</strong>
      </div>
      <div className="signal-lanes">
        {leaders.map((item, index) => (
          <div className="signal-lane" key={item.id}>
            <span>{String(index + 1).padStart(2, "0")}</span>
            <div className="lane-track">
              <i style={{ width: `${Math.max(18, item.heatScore)}%` }} />
            </div>
            <strong>{item.industry}</strong>
          </div>
        ))}
      </div>
      <div className="market-grid" aria-hidden="true">
        {Array.from({ length: 36 }).map((_, index) => (
          <span
            key={index}
            style={{
              animationDelay: `${index * 55}ms`,
              opacity: 0.18 + ((index * 7) % 10) / 20
            }}
          />
        ))}
      </div>
    </div>
  );
}

function TrendCard({ item, rank }: { item: TrendItem; rank: number }) {
  return (
    <article className="trend-card">
      <div className="rank-cell">
        <span>{rank}</span>
        <strong>{item.heatScore}</strong>
      </div>
      <div className="trend-body">
        <div className="trend-meta">
          <span>{item.source}</span>
          <span>{formatTime(item.publishedAt)}</span>
          <span>记录日 {formatDateKey(item.recordDate)}</span>
          <span>{item.signal === "live" ? "live" : "seed"}</span>
        </div>
        <h3>
          <a href={item.url} rel="noreferrer" target="_blank">
            {item.title}
            <ExternalLink size={15} />
          </a>
        </h3>
        <p>{item.summary}</p>
        <div className="opportunity-line">
          <Zap size={15} />
          <span>{item.opportunity}</span>
        </div>
        <div className="tag-row">
          {item.tags.map((tag) => (
            <span key={tag}>{tag}</span>
          ))}
        </div>
      </div>
      <div className="growth-cell">
        <span>growth</span>
        <strong>{item.growthScore}</strong>
      </div>
    </article>
  );
}

function formatTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--";

  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(date);
}

function formatDateKey(key: string): string {
  if (!key || key === "unknown" || !key.includes("-")) return "未知";
  const [, month, day] = key.split("-");
  return `${month}/${day}`;
}

function dateKeyFromIso(value: string): string {
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
