"use client";

import { Activity, PlayCircle, RefreshCw, Route, UserCheck } from "lucide-react";
import type { GraphTaskInstanceMonitor, GraphTaskInstanceSummary } from "@/lib/api";

export function GraphInstanceRunMonitor({
  artifactCount,
  fileCount,
  instance,
  loading,
  monitor,
  nodeSessionCount,
  onRefresh,
  onStartRun,
  runningAction,
}: {
  artifactCount: number;
  fileCount: number;
  instance: GraphTaskInstanceSummary;
  loading: boolean;
  monitor: GraphTaskInstanceMonitor | null;
  nodeSessionCount: number;
  runningAction: string;
  onRefresh: () => void;
  onStartRun: () => void;
}) {
  const activeRunId = instance.active_graph_run_id || monitor?.graph_monitor?.graph_run_id || "";
  const graphRun = asRecord(monitor?.graph_monitor?.graph_run);
  const taskRun = asRecord(monitor?.graph_monitor?.task_run);
  const status = text(graphRun.status) || text(taskRun.status) || instance.status || "created";
  const activeOrders = monitor?.graph_monitor?.active_node_work_order_count ?? 0;
  const eventCount = monitor?.graph_monitor?.event_count ?? 0;
  const pendingHuman = monitor?.human_controls?.pending?.length ?? 0;
  return (
    <aside className="graph-instance-run-monitor" aria-label="项目运行控制">
      <header>
        <div>
          <span>项目运行控制</span>
          <strong>{statusLabel(status)}</strong>
        </div>
        <Activity size={16} />
      </header>
      <div className="graph-instance-run-actions">
        <button disabled={loading || Boolean(runningAction)} onClick={onStartRun} type="button">
          <PlayCircle size={14} />
          <span>{runningAction === "start" ? "启动中" : "启动运行"}</span>
        </button>
        <button disabled={loading || Boolean(runningAction)} onClick={onRefresh} type="button">
          <RefreshCw size={14} />
          <span>刷新</span>
        </button>
      </div>
      <div className="graph-instance-facts">
        <p><span>项目</span><strong>{instance.graph_task_instance_id}</strong></p>
        <p><span>活跃运行</span><strong>{activeRunId || "无"}</strong></p>
        <p><span>节点会话</span><strong>{nodeSessionCount}</strong></p>
        <p><span>文件</span><strong>{fileCount}</strong></p>
        <p><span>产物</span><strong>{artifactCount}</strong></p>
      </div>
      <div className="graph-instance-run-lanes">
        <article>
          <Route size={14} />
          <div>
            <strong>{activeOrders}</strong>
            <span>活跃节点</span>
          </div>
        </article>
        <article>
          <UserCheck size={14} />
          <div>
            <strong>{pendingHuman}</strong>
            <span>待人工决策</span>
          </div>
        </article>
        <article>
          <Activity size={14} />
          <div>
            <strong>{eventCount}</strong>
            <span>运行事件</span>
          </div>
        </article>
      </div>
    </aside>
  );
}

function statusLabel(status: string) {
  if (status === "running") return "运行中";
  if (status === "completed") return "已完成";
  if (status === "failed") return "失败";
  if (status === "paused") return "已暂停";
  if (status === "created") return "已创建";
  return status;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function text(value: unknown) {
  return String(value ?? "").trim();
}
