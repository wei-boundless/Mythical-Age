import type { HealthSystemOverview, HealthTaskRecordMaintenance } from "@/lib/api";

import {
  byRisk,
  numberValue,
  tokenBuckets,
  type TokenChartMode,
} from "./healthFormatters";

export type TokenLinePoint = {
  bucket: Record<string, unknown>;
  value: number;
  x: number;
  y: number;
};

export function buildHealthSystemViewModel(
  overview: HealthSystemOverview | null,
  maintenance: HealthTaskRecordMaintenance | null,
  selectedTaskId: string,
  tokenChartMode: TokenChartMode,
) {
  const tasks = [...(overview?.tasks ?? [])].sort(byRisk);
  const selectedTask = tasks.find((task) => task.task_run_id === selectedTaskId) ?? tasks[0] ?? null;
  const risks = overview?.risks ?? [];
  const systemRisks = overview?.system_risks ?? [];
  const tokenTasks = overview?.token_usage?.tasks ?? [];
  const efficiencyTasks = overview?.efficiency?.tasks ?? [];
  const monitorGovernance = overview?.monitor_governance ?? null;
  const tokenUsage = overview?.token_usage;
  const dailyTokenBuckets = tokenBuckets(tokenUsage?.daily);
  const sixHourTokenBuckets = tokenBuckets(tokenUsage?.six_hour);
  const activeTokenBuckets = tokenChartMode === "daily" ? dailyTokenBuckets : sixHourTokenBuckets;
  const maxActiveTokenBucket = Math.max(1, ...activeTokenBuckets.map((bucket) => numberValue(bucket.tokens)));
  const tokenChartTitle = tokenChartMode === "daily" ? "最近 7 天" : "最近 24 小时";
  const tokenChartBucketLabel = tokenChartMode === "daily" ? "日期" : "6 小时窗口";
  const tokenChartTicks = [1, 0.75, 0.5, 0.25, 0].map((ratio) => Math.round(maxActiveTokenBucket * ratio));
  const tokenLinePoints: TokenLinePoint[] = activeTokenBuckets.map((bucket, index, buckets) => {
    const x = buckets.length <= 1 ? 50 : (index / (buckets.length - 1)) * 100;
    const value = numberValue(bucket.tokens);
    const y = 92 - (value / maxActiveTokenBucket) * 76;
    return { bucket, value, x, y };
  });
  const tokenLinePolyline = tokenLinePoints.map((point) => `${point.x},${point.y}`).join(" ");
  const tokenLineArea = tokenLinePoints.length
    ? `0,92 ${tokenLinePolyline} 100,92`
    : "";
  const tokenSummary = tokenUsage?.summary ?? {};
  const exactTokenTotal = numberValue(tokenSummary.exact_total_tokens ?? tokenSummary.total_tokens);
  const predictedTokenTotal = numberValue(tokenSummary.predicted_total_tokens);
  const traceTokenTotal = numberValue(tokenSummary.trace_estimate_total_tokens);
  const cacheSavingsTotal = numberValue(tokenSummary.cache_savings_tokens);
  const cachedTokenTotal = numberValue(tokenSummary.cached_tokens);
  const providerUsageTaskCount = numberValue(tokenSummary.provider_usage_task_count);
  const predictionOnlyTaskCount = numberValue(tokenSummary.prediction_only_task_count);
  const traceEstimateTaskCount = numberValue(tokenSummary.trace_estimate_task_count);
  const tokenRecordCount = Math.max(0, numberValue(tokenSummary.record_count));
  const missingTokenTaskCount = Math.max(
    0,
    tokenRecordCount - providerUsageTaskCount - predictionOnlyTaskCount - traceEstimateTaskCount,
  );
  const providerCoverage = tokenRecordCount ? providerUsageTaskCount / tokenRecordCount : 0;
  const providerCoverageCaption = tokenRecordCount
    ? `${providerUsageTaskCount} / ${tokenRecordCount} 个运行记录已有 provider usage`
    : "暂无可核算运行记录";
  const predictionDelta = exactTokenTotal > 0 ? predictedTokenTotal - exactTokenTotal : 0;
  const predictionDeltaRatio = exactTokenTotal > 0 ? Math.abs(predictionDelta) / exactTokenTotal : 0;
  const cacheSavingsRatio = exactTokenTotal + cacheSavingsTotal > 0
    ? cacheSavingsTotal / (exactTokenTotal + cacheSavingsTotal)
    : 0;
  const sourceStructureTotal = Math.max(
    1,
    providerUsageTaskCount + predictionOnlyTaskCount + traceEstimateTaskCount + missingTokenTaskCount,
  );
  const tokenInsight = providerCoverage >= 0.8
    ? "账本真值覆盖充分，可以直接用精确消耗判断成本。"
    : providerCoverage > 0
      ? "部分运行记录已有 provider usage，仍有记录只停留在预测或旧轨迹估算。"
      : "当前主要依赖预测或旧轨迹估算，精确账单真值还不足。";
  const maintenanceSummary = maintenance?.summary ?? {};
  const maintenanceCandidates = maintenance?.candidates ?? [];
  const protectedMaintenanceCandidates = maintenanceCandidates.filter((item) => !Boolean(item.eligible));
  const monitor = overview?.monitor as Record<string, unknown> | undefined;
  const monitorSummary = monitorGovernance?.summary
    ?? (monitor?.summary as Record<string, unknown> | undefined)
    ?? {};
  const monitorRevision = monitorGovernance?.revision || String(monitor?.revision || "-");

  return {
    activeTokenBuckets,
    cacheSavingsRatio,
    cacheSavingsTotal,
    cachedTokenTotal,
    dailyTokenBuckets,
    efficiencyTasks,
    exactTokenTotal,
    maintenanceCandidates,
    maintenanceSummary,
    maxActiveTokenBucket,
    missingTokenTaskCount,
    monitorGovernance,
    monitorRevision,
    monitorSummary,
    predictedTokenTotal,
    predictionDelta,
    predictionDeltaRatio,
    predictionOnlyTaskCount,
    protectedMaintenanceCandidates,
    providerCoverage,
    providerCoverageCaption,
    providerUsageTaskCount,
    risks,
    selectedTask,
    sixHourTokenBuckets,
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
    traceEstimateTaskCount,
    traceTokenTotal,
  };
}
