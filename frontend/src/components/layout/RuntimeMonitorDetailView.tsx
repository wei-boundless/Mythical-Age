"use client";

import { AlertTriangle, CheckCircle2, Clock3, Network, RefreshCw, RotateCcw } from "lucide-react";

import { TaskGraphRunMonitorPanel } from "@/components/task-graph-monitor/TaskGraphRunMonitorPanel";
import { useAppStore } from "@/lib/store";
import { topLevelTaskGraphMonitorItems } from "../../lib/runtimeMonitorLayering";
import {
  formatTime,
  monitorStatusLabel,
  monitorTimeLabel,
  statusLabel,
  taskTitle,
} from "@/components/layout/runtimeMonitorFormat";
import { useRuntimeNowTicker } from "@/components/layout/runtimeNowTicker";

function text(value: unknown, fallback = "-") {
  const normalized = String(value ?? "").trim();
  return normalized || fallback;
}

export function RuntimeMonitorDetailView({ onClose }: { onClose: () => void }) {
  const {
    globalRuntimeMonitor,
    globalRuntimeMonitorError,
    globalRuntimeMonitorLoading,
    globalRuntimeMonitorSelectedGraphMonitor,
    globalRuntimeMonitorSelectedLiveMonitor,
    globalRuntimeMonitorSelectedTaskRunId,
    refreshGlobalRuntimeMonitor,
  } = useAppStore();
  const tasks = topLevelTaskGraphMonitorItems(globalRuntimeMonitor);
  const selectedTask = tasks.find((item) => item.task_run_id === globalRuntimeMonitorSelectedTaskRunId) ?? tasks[0] ?? null;
  const selectedTaskRunId = selectedTask?.task_run_id ?? "";
  const selectedTaskBucket = selectedTask?.display_bucket ?? "";
  const selectedTaskLive = selectedTask?.is_live ?? false;
  const nowSeconds = useRuntimeNowTicker(Boolean(selectedTaskRunId && (selectedTaskLive || selectedTaskBucket === "stale")));
  const liveMonitor = globalRuntimeMonitorSelectedLiveMonitor;
  const graphMonitor = globalRuntimeMonitorSelectedGraphMonitor;

  return (
    <section className="runtime-monitor-center" aria-label="任务详细监控">
      <header className="runtime-monitor-center__head">
        <div>
          <span>详细监控</span>
          <h2>{selectedTask ? taskTitle(selectedTask) : "未选择任务"}</h2>
          <p>{selectedTask ? selectedTask.task_run_id : "从右侧监控列表选择一个任务图后，这里显示运行细节。"}</p>
        </div>
        <div className="runtime-monitor-center__actions">
          <button disabled={globalRuntimeMonitorLoading} onClick={() => void refreshGlobalRuntimeMonitor()} type="button">
            <RefreshCw size={14} />
            刷新
          </button>
          <button onClick={onClose} type="button">
            <RotateCcw size={14} />
            返回
          </button>
        </div>
      </header>

      {globalRuntimeMonitorError ? (
        <section className="runtime-monitor-center__alert">
          <AlertTriangle size={16} />
          <div>
            <strong>监控读取异常</strong>
            <span>{globalRuntimeMonitorError}</span>
          </div>
        </section>
      ) : null}

      {selectedTask ? (
        <section className="runtime-monitor-center__summary" aria-label="选中任务概览">
          <article>
            <span>状态</span>
            <strong>{monitorStatusLabel(selectedTask)}</strong>
            <em>{monitorTimeLabel(selectedTask, nowSeconds)}</em>
          </article>
          <article>
            <span>事件</span>
            <strong>{selectedTask.event_count}</strong>
            <em>{selectedTask.latest_event_type || "暂无事件"}</em>
          </article>
          <article>
            <span>类型</span>
            <strong>任务图</strong>
            <em>{selectedTask.active_node_id || "等待节点"}</em>
          </article>
          <article>
            <span>最近更新</span>
            <strong>{formatTime(selectedTask.latest_event_at || selectedTask.updated_at)}</strong>
            <em>{selectedTask.coordination_status || selectedTask.terminal_reason || "runtime"}</em>
          </article>
        </section>
      ) : null}

      {!selectedTask ? (
        <div className="runtime-monitor-center__empty">
          <Clock3 size={22} />
          <strong>当前没有可监控任务图</strong>
          <span>启动任务图后，右侧会出现顶层任务图；选择后可在这里查看节点和子进程。</span>
        </div>
      ) : graphMonitor ? (
        <div className="runtime-monitor-center__graph">
          <TaskGraphRunMonitorPanel monitor={graphMonitor} />
        </div>
      ) : liveMonitor ? (
        <section className="runtime-monitor-center__live" aria-label="运行循环详情">
          <article>
            <span>TaskRun</span>
            <strong>{text(liveMonitor.task_run?.task_run_id, selectedTask.task_run_id)}</strong>
          </article>
          <article>
            <span>状态</span>
            <strong>{statusLabel(liveMonitor.status)}</strong>
          </article>
          <article>
            <span>终止原因</span>
            <strong>{liveMonitor.terminal_reason || "-"}</strong>
          </article>
          <article>
            <span>Checkpoint</span>
            <strong>{text(liveMonitor.latest_checkpoint?.checkpoint_id)}</strong>
          </article>
          <article>
            <span>Coordination</span>
            <strong>{liveMonitor.has_coordination ? "已绑定" : "未绑定"}</strong>
          </article>
          <article>
            <span>更新时间</span>
            <strong>{formatTime(liveMonitor.updated_at)}</strong>
          </article>
        </section>
      ) : (
        <div className="runtime-monitor-center__empty">
          {globalRuntimeMonitorLoading ? <RefreshCw className="runtime-monitor-center__spin" size={22} /> : <Network size={22} />}
          <strong>{globalRuntimeMonitorLoading ? "正在读取任务详情" : "等待详情数据"}</strong>
          <span>已选中 {selectedTask.task_run_id}，详情接口返回后会在中间显示。</span>
        </div>
      )}

      {selectedTask && !graphMonitor ? (
        <section className="runtime-monitor-center__footnote">
          {liveMonitor ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
          <span>{liveMonitor ? "当前任务没有任务图详情，已显示运行循环摘要。" : "暂无任务图或运行循环详情，保留全局任务摘要。"}</span>
        </section>
      ) : null}
    </section>
  );
}
