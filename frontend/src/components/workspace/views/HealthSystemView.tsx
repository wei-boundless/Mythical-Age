"use client";

import {
  Activity,
  AlertTriangle,
  BarChart3,
  Cpu,
  Database,
  Gauge,
  HeartPulse,
  Loader2,
  RefreshCw,
  ShieldAlert,
  Trash2,
  TimerReset,
  WalletCards,
} from "lucide-react";

import {
  compactNumber,
  costConclusion,
  durationLabel,
  numberValue,
  percentLabel,
  riskClass,
  riskLabel,
  riskLabelValue,
  runtimeEventLabelValue,
  statusLabel,
  statusLabelValue,
  taskDisplayTitle,
  taskSecondaryLabel,
  taskTitle,
  timeLabel,
  tokenLabel,
  tokenSourceClass,
  tokenSourceLabel,
  type HealthPage,
} from "@/features/health/healthFormatters";
import { useHealthSystemController } from "@/features/health/useHealthSystemController";
import type { HealthRiskEvent, HealthTaskRecord } from "@/lib/api";
import { Button } from "@/ui/Button";
import { EmptyState } from "@/ui/EmptyState";
import { MetricCard } from "@/ui/MetricCard";
import { Notice } from "@/ui/Notice";

const pages: Array<{ key: HealthPage; title: string; subtitle: string; icon: typeof HeartPulse }> = [
  { key: "overview", title: "总览", subtitle: "风险、成本、效率", icon: HeartPulse },
  { key: "tasks", title: "任务健康", subtitle: "任务记录与风险", icon: Activity },
  { key: "maintenance", title: "任务记录管理", subtitle: "预检与回执", icon: Trash2 },
  { key: "cost", title: "运行成本", subtitle: "Token 与效率", icon: WalletCards },
];

export function HealthSystemView() {
  const {
    activePage,
    detailLoading,
    error,
    loadMaintenance,
    loadOverview,
    loading,
    maintenance,
    maintenanceBusy,
    maintenanceMessage,
    overview,
    pruneRecords,
    setActivePage,
    setSelectedTaskId,
    taskDetail,
    view,
  } = useHealthSystemController();
  const {
    activeTokenBuckets,
    cacheSavingsRatio,
    cacheSavingsTotal,
    cachedTokenTotal,
    efficiencyTasks,
    exactTokenTotal,
    maintenanceCandidates,
    maintenanceSummary,
    maxActiveTokenBucket,
    missingTokenTaskCount,
    monitorGovernance,
    monitorRevision,
    monitorSummary,
    predictionOnlyTaskCount,
    protectedMaintenanceCandidates,
    providerCoverage,
    providerCoverageCaption,
    providerUsageTaskCount,
    risks,
    selectedTask,
    sourceStructureTotal,
    systemRisks,
    tasks,
    tokenChartBucketLabel,
    tokenChartTicks,
    tokenChartTitle,
    tokenInsight,
    tokenLineArea,
    tokenLinePoints,
    tokenLinePolyline,
    tokenRecordCount,
    tokenTasks,
    overallTokenTotal,
    traceEstimateTaskCount,
    weeklyTokenTotal,
  } = view;

  return (
    <div className="workspace-view health-system-view health-governance-view">
      <header className="workspace-view__header">
        <div>
          <p className="workspace-view__eyebrow">Agent 运行治理中心</p>
          <h2 className="workspace-view__title">健康系统</h2>
          <p className="workspace-view__description">管理任务风险、系统风险、Token 消耗和运行效率。任务记录与实时监控会在这里汇总为可处理的健康结论。</p>
        </div>
        <Button chrome="action" disabled={loading} onClick={() => void loadOverview()} variant="primary">
          {loading ? <Loader2 size={15} className="spin" /> : <RefreshCw size={15} />}
          刷新
        </Button>
      </header>

      {error ? <Notice icon={<AlertTriangle size={16} />} tone="error">{error}</Notice> : null}

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
        <EmptyState as="section" className="boundary-empty boundary-empty--large" icon={<Loader2 size={22} className="spin" />} title="正在读取健康治理数据">
          <span>会从任务记录、运行监控和 token 统计中整理当前健康状态。</span>
        </EmptyState>
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

          <section className="health-system-grid">
            <article className="health-system-card">
              <PanelHead title="监控汇总" subtitle={monitorGovernance?.status || "RunMonitor"} />
              <div className="health-overview-metrics">
                <Metric label="运行中" value={monitorSummary.running ?? 0} />
                <Metric label="等待处理" value={monitorSummary.action_required ?? monitorSummary.waiting ?? 0} danger={numberValue(monitorSummary.action_required ?? monitorSummary.waiting) > 0} />
                <Metric label="停滞" value={monitorSummary.stale ?? 0} danger={numberValue(monitorSummary.stale) > 0} />
                <Metric label="诊断" value={monitorSummary.diagnostics ?? 0} danger={numberValue(monitorSummary.diagnostics) > 0} />
              </div>
              <section className="health-semantic-box">
                <span>监控归属</span>
                <p>运行监控页面负责实时状态查看；健康系统只汇总监控事实、风险和建议，不接管运行监控界面。</p>
                <p>Revision：{monitorRevision}</p>
              </section>
            </article>
            <RiskList title="系统风险摘要" risks={systemRisks.length ? systemRisks : (monitorGovernance?.risk_escalations ?? [])} />
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
                  <strong>{taskDisplayTitle(task)}</strong>
                  <small>{statusLabel(task.status)} · {durationLabel(task.duration_seconds)} · {tokenLabel(task.token_total)} tokens</small>
                </button>
              ))}
            </div>
          </div>
          <TaskDetail task={selectedTask} detail={taskDetail} loading={detailLoading} />
        </section>
      ) : null}

      {overview && activePage === "maintenance" ? (
        <section className="health-maintenance-layout">
          <article className="health-system-card health-maintenance-panel">
            <PanelHead title="任务记录管理" subtitle="预检、保护条件和维护回执" />
            <div className="health-overview-metrics">
              <Metric label="候选" value={maintenanceSummary.candidate_count ?? 0} />
              <Metric label="可维护" value={maintenanceSummary.eligible_count ?? 0} />
              <Metric label="受保护" value={maintenanceSummary.protected_count ?? 0} danger={numberValue(maintenanceSummary.protected_count) > 0} />
              <Metric label="回执" value={maintenance?.recent_receipts?.length ?? 0} />
            </div>
            {maintenanceMessage ? <Notice icon={<Trash2 size={16} />}>{maintenanceMessage}</Notice> : null}
            <div className="health-maintenance-actions">
              <Button disabled={Boolean(maintenanceBusy) || numberValue(maintenanceSummary.eligible_count) === 0} onClick={() => void pruneRecords("static")}>
                {maintenanceBusy === "static" ? <Loader2 size={15} className="spin" /> : <Trash2 size={15} />}
                执行受控维护
              </Button>
              <Button disabled={Boolean(maintenanceBusy)} onClick={() => void loadMaintenance()}>
                重新预检
              </Button>
            </div>
            <p className="health-copy">任务记录管理归健康系统，但执行前必须预检影响范围。运行中、近期记录、未形成健康报告的失败记录会被保护。</p>
          </article>

          <article className="health-list-panel">
            <PanelHead title="预检候选" subtitle={`${maintenanceCandidates.length} 条`} />
            <div className="health-task-list">
              {maintenanceCandidates.map((record) => (
                <div className="health-task-row health-task-row--managed" key={String(record.task_run_id)}>
                  <span className={Boolean(record.eligible) ? "health-pill" : "health-pill health-pill--notice"}>{Boolean(record.eligible) ? "可维护" : "受保护"}</span>
                  <strong>{String(record.title || record.task_run_id || "任务记录")}</strong>
                  <small>{statusLabelValue(record.status)} · {durationLabel(record.age_seconds)} old · {String((record.protection_reasons as string[] | undefined)?.join(" / ") || "通过保护规则")}</small>
                  <button disabled={Boolean(maintenanceBusy) || !Boolean(record.eligible)} onClick={() => void pruneRecords("static", [String(record.task_run_id || "")])} type="button">
                    {maintenanceBusy === record.task_run_id ? <Loader2 size={13} className="spin" /> : <Trash2 size={13} />}
                    维护
                  </button>
                </div>
              ))}
              {!maintenanceCandidates.length ? (
                <EmptyState className="health-empty-state" icon={<TimerReset size={18} />} title="暂无维护候选">
                  <span>当前没有通过预检的任务记录。</span>
                </EmptyState>
              ) : null}
            </div>
          </article>

          <article className="health-system-card">
            <PanelHead title="保护规则" subtitle={`${protectedMaintenanceCandidates.length} 条受保护`} />
            <div className="health-risk-list">
              {protectedMaintenanceCandidates.slice(0, 8).map((record) => (
                <section className="health-risk-row" key={String(record.task_run_id)}>
                  <span className="health-pill health-pill--notice">保护</span>
                  <div>
                    <strong>{String(record.title || record.task_run_id || "任务记录")}</strong>
                    <p>{Array.isArray(record.protection_reasons) ? record.protection_reasons.join(" / ") : "受保护记录"}</p>
                    <small>{statusLabelValue(record.status)} · {durationLabel(record.age_seconds)} old</small>
                  </div>
                </section>
              ))}
              {!protectedMaintenanceCandidates.length ? (
                <EmptyState className="health-empty-state" icon={<ShieldAlert size={18} />} title="没有被保护候选">
                  <span>当前预检候选均满足维护条件。</span>
                </EmptyState>
              ) : null}
            </div>
          </article>
        </section>
      ) : null}

      {overview && activePage === "cost" ? (
        <section className="health-token-workbench">
          <section className="health-token-ledger-hero">
            <div className="health-token-ledger-hero__main">
              <span>PromptAccounting Ledger</span>
              <strong>{costConclusion(overview)}</strong>
              <p>{tokenInsight}</p>
              <small>{String(overview.token_usage.note || "provider usage 是精确消耗，local prediction 是请求前预算，trace estimate 只用于旧任务迁移回退。")}</small>
            </div>
            <div className="health-token-ledger-hero__score">
              <Database size={18} />
              <span>真值覆盖率</span>
              <strong>{percentLabel(providerCoverage)}</strong>
              <p>{providerCoverageCaption}</p>
              <div className="health-token-ledger-hero__breakdown" aria-label="Token 口径运行记录数量">
                <span>精确 {providerUsageTaskCount}</span>
                <span>仅预测 {predictionOnlyTaskCount}</span>
                <span>旧估算 {traceEstimateTaskCount}</span>
              </div>
            </div>
          </section>

          <section className="health-token-ledger-strip" aria-label="Token 账本核心指标">
            <TokenStatCard
              accent="exact"
              label="最近 7 天"
              value={tokenLabel(weeklyTokenTotal)}
              detail="按日窗口聚合"
            />
            <TokenStatCard
              accent="neutral"
              label="账本总数"
              value={tokenLabel(overallTokenTotal)}
              detail={`${tokenRecordCount} 条记录 · provider 精确 ${tokenLabel(exactTokenTotal)}`}
            />
            <TokenStatCard
              accent="cache"
              label="缓存节省"
              value={tokenLabel(cacheSavingsTotal)}
              detail={`${percentLabel(cacheSavingsRatio)} 节省率 · ${tokenLabel(cachedTokenTotal)} cached`}
            />
          </section>

          <section className="health-token-structure">
            <div>
              <span>账本口径覆盖</span>
              <strong>按运行记录展示精确、预测、旧估算与无记录</strong>
            </div>
            <div className="health-token-structure__bar" aria-label="Token 账本口径覆盖">
              <i className="health-token-structure__exact" style={{ width: `${Math.max(0, (providerUsageTaskCount / sourceStructureTotal) * 100)}%` }} />
              <i className="health-token-structure__predicted" style={{ width: `${Math.max(0, (predictionOnlyTaskCount / sourceStructureTotal) * 100)}%` }} />
              <i className="health-token-structure__trace" style={{ width: `${Math.max(0, (traceEstimateTaskCount / sourceStructureTotal) * 100)}%` }} />
              <i className="health-token-structure__missing" style={{ width: `${Math.max(0, (missingTokenTaskCount / sourceStructureTotal) * 100)}%` }} />
            </div>
            <div className="health-token-structure__legend">
              <span><b className="health-token-structure__exact" />精确 {providerUsageTaskCount} 个</span>
              <span><b className="health-token-structure__predicted" />仅预测 {predictionOnlyTaskCount} 个</span>
              <span><b className="health-token-structure__trace" />旧估算 {traceEstimateTaskCount} 个</span>
              <span><b className="health-token-structure__missing" />无记录 {missingTokenTaskCount} 个</span>
            </div>
            <p>宽度按运行记录数量计算，避免把预测、精确账单和缓存节省误加为同一笔成本。</p>
          </section>

          <section className="health-cost-grid">
            <section className="health-token-chart-panel">
              <div className="health-panel-head">
                <div>
                  <span>Token Trend</span>
                  <h3>{tokenChartTitle}</h3>
                </div>
                <Activity size={16} />
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
                    <span role="columnheader">有效消耗</span>
                  <span role="columnheader">精确 / 预测 / 旧估算 / 缓存</span>
                  </div>
                  {activeTokenBuckets.map((bucket) => {
                    const tokens = numberValue(bucket.tokens);
                    const exactTokens = numberValue(bucket.exact_tokens);
                    const predictedTokens = numberValue(bucket.predicted_tokens);
                    const traceTokens = numberValue(bucket.trace_estimate_tokens);
                    const cacheTokens = numberValue(bucket.cache_savings_tokens);
                    return (
                      <div className="health-token-table__row" key={String(bucket.bucket)} role="row">
                        <span>{String(bucket.bucket)}</span>
                        <div className="health-token-table__bar">
                          <i style={{ width: `${Math.max(3, (tokens / maxActiveTokenBucket) * 100)}%` }} />
                          <strong>{tokens.toLocaleString()}</strong>
                        </div>
                        <em>{tokenLabel(exactTokens)} / {tokenLabel(predictedTokens)} / {tokenLabel(traceTokens)} / {tokenLabel(cacheTokens)}</em>
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
                  ["任务", "title", (_value, row) => taskDisplayTitle(row)],
                  ["耗时", "duration_seconds", durationLabel],
                  ["评分", "efficiency_score"],
                ]}
              />
            </article>
          </section>

          <section className="health-token-ledger-grid">
            <TokenTaskLedger rows={tokenTasks} />
            <SimpleTable
              title="效率异常任务明细"
              rows={efficiencyTasks}
              columns={[
                ["任务", "title", (_value, row) => taskDisplayTitle(row)],
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
  return <MetricCard className="health-metric" label={label} toneClassName={danger ? "health-metric--danger" : undefined} value={String(value ?? 0)} />;
}

function TokenStatCard({
  label,
  value,
  detail,
  accent,
}: {
  label: string;
  value: string;
  detail: string;
  accent: "exact" | "predicted" | "cache" | "trace" | "neutral";
}) {
  return (
    <article className={`health-token-stat health-token-stat--${accent}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <p>{detail}</p>
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
          <EmptyState className="health-empty-state" icon={<Cpu size={18} />} title="暂无风险">
            <span>当前没有需要处理的健康风险。</span>
          </EmptyState>
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

function TokenTaskLedger({ rows }: { rows: Array<Record<string, unknown>> }) {
  const maxEffectiveTokens = Math.max(1, ...rows.map((row) => numberValue(row.token_total)));
  return (
    <article className="health-list-panel health-token-task-ledger">
      <PanelHead title="高消耗运行账本" subtitle={`${rows.length} 条`} />
      <div className="health-token-task-ledger__rows">
        {rows.length ? rows.map((row, index) => {
          const exact = numberValue(row.exact_token_total);
          const predicted = numberValue(row.predicted_token_total);
          const trace = numberValue(row.trace_estimate_token_total);
          const cache = numberValue(row.cache_savings_tokens);
          const effective = numberValue(row.token_total);
          return (
            <section className="health-token-task-row" key={`${String(row.task_run_id || index)}`}>
              <div className="health-token-task-row__head">
                <div>
                  <strong>{taskDisplayTitle(row)}</strong>
                  <span>{taskSecondaryLabel(row)}</span>
                </div>
                <em className={tokenSourceClass(row.token_source)}>{tokenSourceLabel(row.token_source)}</em>
              </div>
              <div className="health-token-task-row__meter" aria-label="任务有效 token 消耗">
                <i style={{ width: `${Math.max(4, (effective / maxEffectiveTokens) * 100)}%` }} />
                <strong>{tokenLabel(effective)}</strong>
              </div>
              <div className="health-token-task-row__numbers">
                <span>精确 <b>{tokenLabel(exact)}</b></span>
                <span>预测 <b>{tokenLabel(predicted)}</b></span>
                <span>旧估算 <b>{tokenLabel(trace)}</b></span>
                <span>缓存 <b>{tokenLabel(cache)}</b></span>
                <span>风险 <b>{riskLabelValue(row.risk_level)}</b></span>
              </div>
            </section>
          );
        }) : (
          <EmptyState className="health-empty-state" icon={<Gauge size={18} />} title="暂无 token 账本记录">
            <span>模型调用产生 PromptAccounting 记录后会显示在这里。</span>
          </EmptyState>
        )}
      </div>
    </article>
  );
}

function TaskDetail({ task, detail, loading }: { task: HealthTaskRecord | null; detail: Record<string, unknown> | null; loading: boolean }) {
  const risks = (detail?.risks ?? []) as HealthRiskEvent[];
  const events = (detail?.recent_events ?? []) as Array<Record<string, unknown>>;
  return (
    <article className="health-detail-panel">
      <PanelHead title={taskTitle(task)} subtitle={task ? statusLabel(task.status) : "任务详情"} />
      {loading ? <p className="health-copy">正在读取任务详情...</p> : null}
      {task ? (
        <>
          <div className="health-overview-metrics">
            <Metric label="状态" value={statusLabel(task.status)} />
            <Metric label="风险" value={riskLabel(task.risk_level)} danger={["critical", "high"].includes(task.risk_level)} />
            <Metric label="耗时" value={durationLabel(task.duration_seconds)} />
            <Metric label="精确 Token" value={tokenLabel(task.exact_token_total ?? 0)} />
            <Metric label="预测 Token" value={tokenLabel(task.predicted_token_total ?? 0)} />
            <Metric label="缓存节省" value={tokenLabel(task.cache_savings_tokens ?? 0)} />
          </div>
          <section className="health-semantic-box">
            <span>任务记录</span>
            <p>Agent {task.agent_id || "-"} · 工具 {task.tool_call_count} 次 · 事件 {task.event_count} 条 · 错误 {task.error_count} 个</p>
            <p>Token 口径：{tokenSourceLabel(task.token_source)} · 最近进展：{runtimeEventLabelValue(task.latest_event_type)} · 更新时间：{timeLabel(task.updated_at)}</p>
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
  columns: Array<[string, string, ((value: unknown, row: Record<string, unknown>) => string)?]>;
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
                  <td key={label}>{format ? format(row[key], row) : String(row[key] ?? "-")}</td>
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
