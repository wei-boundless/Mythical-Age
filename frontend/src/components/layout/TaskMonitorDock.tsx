"use client";

import { Activity, ChevronRight, Minimize2, Network, RefreshCw, X } from "lucide-react";
import { useMemo, useState } from "react";

import { TaskGraphRunMonitorPanel } from "@/components/task-graph-monitor/TaskGraphRunMonitorPanel";
import { useAppStore } from "@/lib/store";

export function TaskMonitorDock() {
  const {
    clearTaskGraphMonitorRun,
    evaluateBoundTaskGraphMonitor,
    setTaskGraphRunInteractionOpen,
    taskGraphBoundRunMonitor,
    taskGraphLiveMonitor,
    taskGraphMonitorBinding,
    taskGraphMonitorDecision,
    taskGraphMonitorError,
    taskGraphMonitorLoading,
    taskGraphRunMonitor,
  } = useAppStore();
  const [collapsed, setCollapsed] = useState(false);
  const monitor = taskGraphBoundRunMonitor ?? taskGraphRunMonitor ?? null;
  const hasSignal = Boolean(monitor || taskGraphLiveMonitor || taskGraphMonitorBinding);
  const statusText = useMemo(() => {
    if (taskGraphMonitorLoading) return "同步中";
    if (monitor) return "运行监控";
    if (taskGraphMonitorBinding) return "已绑定";
    if (taskGraphLiveMonitor) return "实时信号";
    return "待命";
  }, [monitor, taskGraphLiveMonitor, taskGraphMonitorBinding, taskGraphMonitorLoading]);

  return (
    <aside className={collapsed ? "task-monitor-dock task-monitor-dock--collapsed" : "task-monitor-dock"} aria-label="任务监控">
      <header className="task-monitor-dock__head">
        <button
          aria-label={collapsed ? "展开任务监控" : "折叠任务监控"}
          className="task-monitor-dock__collapse"
          onClick={() => setCollapsed((current) => !current)}
          type="button"
        >
          {collapsed ? <ChevronRight size={17} /> : <Minimize2 size={16} />}
        </button>
        <div className="task-monitor-dock__title">
          <Activity size={16} />
          <span>监控</span>
        </div>
        {!collapsed && taskGraphMonitorBinding ? (
          <button
            aria-label="解除当前运行监控绑定"
            className="task-monitor-dock__open"
            onClick={clearTaskGraphMonitorRun}
            type="button"
          >
            <X size={15} />
          </button>
        ) : null}
      </header>

      {collapsed ? (
        <button
          className={hasSignal ? "task-monitor-dock__rail task-monitor-dock__rail--active" : "task-monitor-dock__rail"}
          onClick={() => setCollapsed(false)}
          type="button"
        >
          <Network size={18} />
          <span>{statusText}</span>
        </button>
      ) : (
        <div className="task-monitor-dock__body">
          <section className={hasSignal ? "task-monitor-summary task-monitor-summary--active" : "task-monitor-summary"}>
            <div>
              <span>任务状态</span>
              <strong>{statusText}</strong>
            </div>
            <small>{taskGraphMonitorBinding?.title || taskGraphMonitorBinding?.task_run_id || "Agent 开始任务后，这里显示运行信息。"}</small>
            <div className="task-monitor-summary__actions">
              <button
                disabled={!taskGraphMonitorBinding || taskGraphMonitorLoading}
                onClick={() => void evaluateBoundTaskGraphMonitor()}
                type="button"
              >
                <RefreshCw size={13} />
                <span>{taskGraphMonitorLoading ? "监测中" : "执行监测"}</span>
              </button>
              {taskGraphMonitorDecision?.action && taskGraphMonitorDecision.action !== "no_action" ? (
                <button onClick={() => setTaskGraphRunInteractionOpen(true)} type="button">
                  <Activity size={13} />
                  <span>处理提醒</span>
                </button>
              ) : null}
            </div>
          </section>

          {taskGraphMonitorError ? (
            <section className="task-monitor-alert task-monitor-alert--error">
              <strong>监控读取异常</strong>
              <span>{taskGraphMonitorError}</span>
            </section>
          ) : null}

          {taskGraphMonitorDecision ? (
            <section className={taskGraphMonitorDecision.action === "no_action" ? "task-monitor-alert" : "task-monitor-alert task-monitor-alert--attention"}>
              <strong>{taskGraphMonitorDecision.summary || "监测已返回决策"}</strong>
              <span>{taskGraphMonitorDecision.action} / {taskGraphMonitorDecision.reason}</span>
            </section>
          ) : null}

          <div className="task-monitor-dock__panel">
            <TaskGraphRunMonitorPanel monitor={monitor} />
          </div>
        </div>
      )}
    </aside>
  );
}
