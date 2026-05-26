"use client";

import {
  Activity,
  AlertTriangle,
  BarChart3,
  Cpu,
  HeartPulse,
  Loader2,
  RefreshCw,
  ShieldAlert,
  TimerReset,
  WalletCards,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  getHealthSystemOverview,
  getHealthSystemTaskDetail,
  type HealthRiskEvent,
  type HealthSystemOverview,
  type HealthTaskRecord,
} from "@/lib/api";

type HealthPage = "overview" | "tasks" | "system" | "cost";
type TokenChartMode = "daily" | "six_hour";

const pages: Array<{ key: HealthPage; title: string; subtitle: string; icon: typeof HeartPulse }> = [
  { key: "overview", title: "总览", subtitle: "风险、成本、效率", icon: HeartPulse },
  { key: "tasks", title: "任务健康", subtitle: "任务记录与风险", icon: Activity },
  { key: "system", title: "系统风险", subtitle: "监控与运行环境", icon: ShieldAlert },
  { key: "cost", title: "运行成本", subtitle: "Token 与效率", icon: WalletCards },
];

function numberValue(value: unknown, fallback = 0) {
  const parsed = Number(value ?? fallback);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function timeLabel(value: unknown) {
  const seconds = numberValue(value);
  if (!seconds) return "-";
  return new Date(seconds * 1000).toLocaleString();
}

function durationLabel(seconds: unknown) {
  const total = Math.max(0, Math.round(numberValue(seconds)));
  if (total < 60) return `${total}s`;
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  if (minutes < 60) return `${minutes}m ${rest}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

function tokenLabel(value: unknown) {
  const tokens = numberValue(value);
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(2)}M`;
  if (tokens >= 1_000) return `${(tokens / 1_000).toFixed(1)}K`;
  return String(Math.round(tokens));
}

function tokenBuckets(value: unknown) {
  return Array.isArray(value)
    ? value.map((item) => item as Record<string, unknown>)
    : [];
}

function compactNumber(value: number) {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(value >= 10_000 ? 0 : 1)}k`;
  return String(Math.round(value));
}

function statusLabel(status: string) {
  const map: Record<string, string> = {
    created: "已创建",
    queued: "排队中",
    running: "运行中",
    waiting_approval: "等待确认",
    paused: "已暂停",
    completed: "已完成",
    failed: "失败",
    aborted: "已中止",
    cancelled: "已取消",
  };
  return map[status] || status || "未知";
}

function statusLabelValue(value: unknown) {
  return statusLabel(String(value || ""));
}

function riskLabel(level: string) {
  const map: Record<string, string> = {
    normal: "正常",
    info: "提示",
    warning: "注意",
    high: "高风险",
    critical: "严重",
  };
  return map[level] || level || "正常";
}

function riskLabelValue(value: unknown) {
  return riskLabel(String(value || ""));
}

function riskClass(level: string) {
  if (level === "critical") return "health-pill health-pill--danger";
  if (level === "high") return "health-pill health-pill--warning";
  if (level === "warning") return "health-pill health-pill--notice";
  return "health-pill";
}

function byRisk(a: HealthTaskRecord, b: HealthTaskRecord) {
  const order: Record<string, number> = { critical: 0, high: 1, warning: 2, normal: 3 };
  return (order[a.risk_level] ?? 9) - (order[b.risk_level] ?? 9)
    || numberValue(b.updated_at) - numberValue(a.updated_at);
}

function taskTitle(task: HealthTaskRecord | null) {
  return task?.title || task?.task_id || task?.task_run_id || "未选择任务";
}

function costConclusion(overview: HealthSystemOverview) {
  const highPressure = numberValue(overview.token_usage.summary.high_pressure_session_count);
  const slowTasks = numberValue(overview.efficiency.summary.slow_task_count);
  if (highPressure > 0 && slowTasks > 0) {
    return "Token 压力和慢任务同时存在，建议优先检查上下文注入、任务循环和工具等待。";
  }
  if (highPressure > 0) {
    return "当前主要压力来自高 token 会话，建议压缩上下文或拆分任务。";
  }
  if (slowTasks > 0) {
    return "当前主要压力来自慢任务，建议检查执行等待、循环重试和人工确认。";
  }
  return "当前运行成本处于可控状态，继续观察趋势和高消耗任务即可。";
}

export function HealthSystemView() {
  const [activePage, setActivePage] = useState<HealthPage>("overview");
  const [overview, setOverview] = useState<HealthSystemOverview | null>(null);
  const [tokenChartMode, setTokenChartMode] = useState<TokenChartMode>("daily");
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [taskDetail, setTaskDetail] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");

  const loadOverview = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const payload = await getHealthSystemOverview();
      setOverview(payload);
      const firstTask = [...(payload.tasks ?? [])].sort(byRisk)[0];
      setSelectedTaskId((current) => current || firstTask?.task_run_id || "");
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "健康系统数据加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadOverview();
  }, [loadOverview]);

  useEffect(() => {
    if (!selectedTaskId) {
      setTaskDetail(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    void getHealthSystemTaskDetail(selectedTaskId)
      .then((payload) => {
        if (!cancelled) setTaskDetail(payload);
      })
      .catch(() => {
        if (!cancelled) setTaskDetail(null);
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedTaskId]);

  const tasks = useMemo(() => [...(overview?.tasks ?? [])].sort(byRisk), [overview]);
  const selectedTask = useMemo(
    () => tasks.find((task) => task.task_run_id === selectedTaskId) ?? tasks[0] ?? null,
    [selectedTaskId, tasks],
  );
  const risks = overview?.risks ?? [];
  const systemRisks = overview?.system_risks ?? [];
  const tokenTasks = overview?.token_usage?.tasks ?? [];
  const efficiencyTasks = overview?.efficiency?.tasks ?? [];
  const tokenUsage = overview?.token_usage;
  const dailyTokenBuckets = tokenBuckets(tokenUsage?.daily);
  const sixHourTokenBuckets = tokenBuckets(tokenUsage?.six_hour);
  const activeTokenBuckets = tokenChartMode === "daily" ? dailyTokenBuckets : sixHourTokenBuckets;
  const maxActiveTokenBucket = Math.max(1, ...activeTokenBuckets.map((bucket) => numberValue(bucket.tokens)));
  const tokenChartTitle = tokenChartMode === "daily" ? "最近 7 天" : "最近 24 小时";
  const tokenChartBucketLabel = tokenChartMode === "daily" ? "日期" : "6 小时窗口";
  const tokenChartTicks = [1, 0.75, 0.5, 0.25, 0].map((ratio) => Math.round(maxActiveTokenBucket * ratio));
  const tokenLinePoints = activeTokenBuckets.map((bucket, index, buckets) => {
    const x = buckets.length <= 1 ? 50 : (index / (buckets.length - 1)) * 100;
    const value = numberValue(bucket.tokens);
    const y = 92 - (value / maxActiveTokenBucket) * 76;
    return { bucket, value, x, y };
  });
  const tokenLinePolyline = tokenLinePoints.map((point) => `${point.x},${point.y}`).join(" ");
  const tokenLineArea = tokenLinePoints.length
    ? `0,92 ${tokenLinePolyline} 100,92`
    : "";

  return (
    <div className="workspace-view health-system-view health-governance-view">
      <header className="workspace-view__header">
        <div>
          <p className="workspace-view__eyebrow">Agent 运行治理中心</p>
          <h2 className="workspace-view__title">健康系统</h2>
          <p className="workspace-view__description">管理任务风险、系统风险、Token 消耗和运行效率。任务记录与实时监控会在这里汇总为可处理的健康结论。</p>
        </div>
        <button className="action-button action-button--primary" disabled={loading} onClick={() => void loadOverview()} type="button">
          {loading ? <Loader2 size={15} className="spin" /> : <RefreshCw size={15} />}
          刷新
        </button>
      </header>

      {error ? <div className="boundary-notice boundary-notice--error"><AlertTriangle size={16} />{error}</div> : null}

      <nav className="health-system-tabs health-system-tabs--merged" aria-label="健康系统分页导航">
        {pages.map((page) => {
          const Icon = page.icon;
          return (
            <button
              className={`health-system-tab ${activePage === page.key ? "health-system-tab--active" : ""}`}
              key={page.key}
              onClick={() => setActivePage(page.key)}
              type="button"
            >
              <Icon size={17} />
              <span>{page.title}</span>
              <em>{page.subtitle}</em>
            </button>
          );
        })}
      </nav>

      {loading && !overview ? (
        <section className="boundary-empty boundary-empty--large">
          <Loader2 size={22} className="spin" />
          <strong>正在读取健康治理数据</strong>
          <span>会从任务记录、运行监控和 token 统计中整理当前健康状态。</span>
        </section>
      ) : null}

      {overview && activePage === "overview" ? (
        <section className="health-overview">
          <div className="health-overview-hero">
            <div>
              <span>当前健康结论</span>
              <strong>{risks[0]?.title || "当前没有高优先级健康风险"}</strong>
              <p>{risks[0]?.summary || "监控和任务记录没有显示需要立即处理的任务风险、系统风险或 token 压力。"}</p>
            </div>
            <div className="health-overview-metrics">
              <Metric label="任务" value={overview.summary.task_count} />
              <Metric label="运行中" value={overview.summary.running_task_count} />
              <Metric label="高风险" value={(overview.summary.critical_risk_count || 0) + (overview.summary.high_risk_count || 0)} danger />
              <Metric label="Token" value={tokenLabel(overview.summary.token_total)} />
            </div>
          </div>

          <section className="health-system-grid">
            <RiskList title="最近风险" risks={risks.slice(0, 5)} />
            <RecommendationList items={overview.recommendations ?? []} />
          </section>
        </section>
      ) : null}

      {overview && activePage === "tasks" ? (
        <section className="health-governance-layout">
          <div className="health-list-panel">
            <PanelHead title="任务记录" subtitle={`${tasks.length} 个任务`} />
            <div className="health-task-list">
              {tasks.map((task) => (
                <button
                  className={task.task_run_id === selectedTask?.task_run_id ? "health-task-row health-task-row--active" : "health-task-row"}
                  key={task.task_run_id}
                  onClick={() => setSelectedTaskId(task.task_run_id)}
                  type="button"
                >
                  <span className={riskClass(task.risk_level)}>{riskLabel(task.risk_level)}</span>
                  <strong>{task.title}</strong>
                  <small>{statusLabel(task.status)} · {durationLabel(task.duration_seconds)} · {tokenLabel(task.token_total)} tokens</small>
                </button>
              ))}
            </div>
          </div>
          <TaskDetail task={selectedTask} detail={taskDetail} loading={detailLoading} />
        </section>
      ) : null}

      {overview && activePage === "system" ? (
        <section className="health-system-grid">
          <RiskList title="系统风险" risks={systemRisks} />
          <article className="health-system-card">
            <PanelHead title="监控连接" subtitle="实时运行监控" />
            <Metric label="运行中" value={String((overview.monitor as Record<string, any>)?.summary?.running ?? 0)} />
            <Metric label="等待处理" value={String((overview.monitor as Record<string, any>)?.summary?.waiting ?? 0)} danger={numberValue((overview.monitor as Record<string, any>)?.summary?.waiting) > 0} />
            <Metric label="停滞" value={String((overview.monitor as Record<string, any>)?.summary?.stale ?? 0)} />
          </article>
        </section>
      ) : null}

      {overview && activePage === "cost" ? (
        <section className="health-overview health-cost-view">
          <section className="health-cost-hero">
            <div>
              <span>当前成本结论</span>
              <strong>{costConclusion(overview)}</strong>
              <p>{String(overview.token_usage.note || "读取任务记录、会话历史和运行监控，合并观察 token 消耗、耗时、错误和效率评分。")}</p>
            </div>
            <div className="health-overview-metrics">
              <Metric label="Token 总量" value={tokenLabel(overview.token_usage.summary.total_tokens)} />
              <Metric label="高压会话" value={overview.token_usage.summary.high_pressure_session_count} danger={numberValue(overview.token_usage.summary.high_pressure_session_count) > 0} />
              <Metric label="慢任务" value={overview.efficiency.summary.slow_task_count} danger={numberValue(overview.efficiency.summary.slow_task_count) > 0} />
              <Metric label="平均效率" value={overview.efficiency.summary.average_efficiency_score} />
            </div>
          </section>

          <section className="health-cost-grid">
            <section className="health-token-chart-panel">
              <div className="health-panel-head">
                <div>
                  <span>Token 消耗折线图</span>
                  <h3>{tokenChartTitle}</h3>
                </div>
                <Activity size={16} />
              </div>
              <div className="health-token-switch" role="tablist" aria-label="Token 消耗统计口径">
                <button
                  aria-selected={tokenChartMode === "daily"}
                  className={tokenChartMode === "daily" ? "health-token-switch__item--active" : ""}
                  onClick={() => setTokenChartMode("daily")}
                  role="tab"
                  type="button"
                >
                  每日
                </button>
                <button
                  aria-selected={tokenChartMode === "six_hour"}
                  className={tokenChartMode === "six_hour" ? "health-token-switch__item--active" : ""}
                  onClick={() => setTokenChartMode("six_hour")}
                  role="tab"
                  type="button"
                >
                  每 6 小时
                </button>
              </div>

              <div className="health-token-line-chart" aria-label="Token 消耗折线图">
                <div className="health-token-y-axis" aria-hidden="true">
                  {tokenChartTicks.map((tick, index) => <span key={`${tick}-${index}`}>{compactNumber(tick)}</span>)}
                </div>
                <div className="health-token-line-plot">
                  <div className="health-token-grid-lines" aria-hidden="true">
                    {tokenChartTicks.map((tick, index) => <i key={`${tick}-${index}`} />)}
                  </div>
                  <svg className="health-token-line-svg" viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label={`${tokenChartTitle} token 消耗趋势`}>
                    {tokenLineArea ? <polygon className="health-token-line-area" points={tokenLineArea} /> : null}
                    {tokenLinePolyline ? <polyline className="health-token-line-path" points={tokenLinePolyline} /> : null}
                  </svg>
                  <div className="health-token-line-values">
                    {tokenLinePoints.map((point, index) => (
                      <span key={`${String(point.bucket.bucket)}-value-${index}`} style={{ left: `${point.x}%`, top: `${point.y}%` }}>
                        {compactNumber(point.value)}
                      </span>
                    ))}
                  </div>
                  <div className="health-token-x-axis">
                    {activeTokenBuckets.map((bucket) => (
                      <span key={String(bucket.bucket)}>{String(bucket.bucket)}</span>
                    ))}
                  </div>
                </div>
              </div>

              <details className="health-token-detail-table">
                <summary>查看数据明细</summary>
                <div className="health-token-table" role="table" aria-label="Token 消耗数据明细">
                  <div className="health-token-table__head" role="row">
                    <span role="columnheader">{tokenChartBucketLabel}</span>
                    <span role="columnheader">消耗</span>
                    <span role="columnheader">记录</span>
                  </div>
                  {activeTokenBuckets.map((bucket) => {
                    const tokens = numberValue(bucket.tokens);
                    const records = numberValue(bucket.records ?? bucket.sessions);
                    return (
                      <div className="health-token-table__row" key={String(bucket.bucket)} role="row">
                        <span>{String(bucket.bucket)}</span>
                        <div className="health-token-table__bar">
                          <i style={{ width: `${Math.max(3, (tokens / maxActiveTokenBucket) * 100)}%` }} />
                          <strong>{tokens.toLocaleString()}</strong>
                        </div>
                        <em>{records}</em>
                      </div>
                    );
                  })}
                </div>
              </details>
            </section>

            <article className="health-system-card health-efficiency-panel">
              <PanelHead title="运行效率" subtitle="耗时、错误、效率评分" />
              <div className="health-overview-metrics">
                <Metric label="平均耗时" value={durationLabel(overview.efficiency.summary.average_duration_seconds)} />
                <Metric label="任务数" value={overview.efficiency.summary.task_count} />
              </div>
              <SimpleTable
                title="低效率任务"
                rows={efficiencyTasks.slice(0, 8)}
                columns={[
                  ["任务", "title"],
                  ["耗时", "duration_seconds", durationLabel],
                  ["评分", "efficiency_score"],
                ]}
              />
            </article>
          </section>

          <section className="health-system-grid">
            <SimpleTable
              title="高消耗任务明细"
              rows={tokenTasks}
              columns={[
                ["任务", "title"],
                ["会话", "session_id"],
                ["Token", "token_total", tokenLabel],
                ["风险", "risk_level", riskLabelValue],
              ]}
            />
            <SimpleTable
              title="效率异常任务明细"
              rows={efficiencyTasks}
              columns={[
                ["任务", "title"],
                ["状态", "status", statusLabelValue],
                ["耗时", "duration_seconds", durationLabel],
                ["评分", "efficiency_score"],
              ]}
            />
          </section>
        </section>
      ) : null}
    </div>
  );
}

function PanelHead({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <header className="health-panel-head">
      <div>
        <span>{subtitle}</span>
        <h3>{title}</h3>
      </div>
    </header>
  );
}

function Metric({ label, value, danger = false }: { label: string; value: unknown; danger?: boolean }) {
  return (
    <article className={danger ? "health-metric health-metric--danger" : "health-metric"}>
      <span>{label}</span>
      <strong>{String(value ?? 0)}</strong>
    </article>
  );
}

function RiskList({ title, risks }: { title: string; risks: HealthRiskEvent[] }) {
  return (
    <article className="health-system-card">
      <PanelHead title={title} subtitle={`${risks.length} 条`} />
      <div className="health-risk-list">
        {risks.length ? risks.map((risk) => (
          <section key={risk.event_id} className="health-risk-row">
            <span className={riskClass(risk.severity)}>{riskLabel(risk.severity)}</span>
            <div>
              <strong>{risk.title}</strong>
              <p>{risk.summary}</p>
              <small>{risk.target_ref} · {risk.recommended_action}</small>
            </div>
          </section>
        )) : (
          <div className="runtime-monitor-empty">
            <Cpu size={18} />
            <strong>暂无风险</strong>
            <span>当前没有需要处理的健康风险。</span>
          </div>
        )}
      </div>
    </article>
  );
}

function RecommendationList({ items }: { items: Array<{ title: string; summary: string; priority: string }> }) {
  return (
    <article className="health-system-card">
      <PanelHead title="建议动作" subtitle={`${items.length} 条`} />
      <div className="health-risk-list">
        {items.map((item) => (
          <section className="health-risk-row" key={item.title}>
            <span className={riskClass(item.priority === "high" ? "high" : "info")}>{riskLabel(item.priority)}</span>
            <div>
              <strong>{item.title}</strong>
              <p>{item.summary}</p>
            </div>
          </section>
        ))}
      </div>
    </article>
  );
}

function TaskDetail({ task, detail, loading }: { task: HealthTaskRecord | null; detail: Record<string, unknown> | null; loading: boolean }) {
  const risks = (detail?.risks ?? []) as HealthRiskEvent[];
  const events = (detail?.recent_events ?? []) as Array<Record<string, unknown>>;
  return (
    <article className="health-detail-panel">
      <PanelHead title={taskTitle(task)} subtitle={task ? task.task_run_id : "任务详情"} />
      {loading ? <p className="health-copy">正在读取任务详情...</p> : null}
      {task ? (
        <>
          <div className="health-overview-metrics">
            <Metric label="状态" value={statusLabel(task.status)} />
            <Metric label="风险" value={riskLabel(task.risk_level)} danger={["critical", "high"].includes(task.risk_level)} />
            <Metric label="耗时" value={durationLabel(task.duration_seconds)} />
            <Metric label="Token" value={tokenLabel(task.token_total)} />
          </div>
          <section className="health-semantic-box">
            <span>任务记录</span>
            <p>Agent {task.agent_id || "-"} · 工具 {task.tool_call_count} 次 · 事件 {task.event_count} 条 · 错误 {task.error_count} 个</p>
            <p>最近事件：{task.latest_event_type || "-"} · 更新时间：{timeLabel(task.updated_at)}</p>
          </section>
          <RiskList title="任务风险" risks={risks} />
          <details className="task-graph-runtime-spec-details">
            <summary><BarChart3 size={14} /> 最近事件</summary>
            <pre>{JSON.stringify(events.slice(-40), null, 2)}</pre>
          </details>
        </>
      ) : (
        <p className="health-copy">当前没有可查看的任务记录。</p>
      )}
    </article>
  );
}

function SimpleTable({
  title,
  rows,
  columns,
}: {
  title: string;
  rows: Array<Record<string, unknown>>;
  columns: Array<[string, string, ((value: unknown) => string)?]>;
}) {
  return (
    <article className="health-list-panel">
      <PanelHead title={title} subtitle={`${rows.length} 条`} />
      <div className="health-data-table">
        <table>
          <thead>
            <tr>{columns.map(([label]) => <th key={label}>{label}</th>)}</tr>
          </thead>
          <tbody>
            {rows.length ? rows.map((row, index) => (
              <tr key={`${String(row.task_run_id || row.session_id || index)}`}>
                {columns.map(([label, key, format]) => (
                  <td key={label}>{format ? format(row[key]) : String(row[key] ?? "-")}</td>
                ))}
              </tr>
            )) : (
              <tr>
                <td colSpan={columns.length}>暂无数据</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </article>
  );
}
