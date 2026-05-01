"use client";

import { AlertTriangle, CheckCircle2, CircleDot, FileWarning, GitBranch, ShieldCheck } from "lucide-react";

import type { HealthTraceReport } from "@/lib/api";

type TimelineEvent = {
  event_id?: string;
  event_type?: string;
  offset?: number;
  payload?: Record<string, unknown>;
  refs?: Record<string, unknown>;
};

function text(value: unknown, fallback = "-") {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }
  if (Array.isArray(value)) {
    return value.length ? value.join(" / ") : fallback;
  }
  return String(value);
}

function eventTone(eventType: string) {
  if (eventType.includes("error") || eventType.includes("failed")) {
    return "health-trace-step--danger";
  }
  if (eventType.includes("gate") || eventType.includes("blocked")) {
    return "health-trace-step--warning";
  }
  if (eventType.includes("terminal") || eventType.includes("checkpoint")) {
    return "health-trace-step--success";
  }
  return "";
}

function eventIcon(eventType: string) {
  if (eventType.includes("error") || eventType.includes("failed")) {
    return AlertTriangle;
  }
  if (eventType.includes("gate")) {
    return ShieldCheck;
  }
  if (eventType.includes("projection") || eventType.includes("directive")) {
    return GitBranch;
  }
  if (eventType.includes("terminal") || eventType.includes("checkpoint")) {
    return CheckCircle2;
  }
  return CircleDot;
}

function eventLabel(eventType: string) {
  if (eventType.includes("error") || eventType.includes("failed")) return "异常记录";
  if (eventType.includes("gate") || eventType.includes("blocked")) return "门禁判断";
  if (eventType.includes("checkpoint")) return "检查点";
  if (eventType.includes("projection")) return "上下文装配";
  if (eventType.includes("directive")) return "分析指令";
  if (eventType.includes("terminal")) return "运行收口";
  if (eventType.includes("loop_iteration")) return "执行轮次";
  if (eventType.includes("task_run")) return "运行启动";
  return "运行事件";
}

function reasonLabel(value: unknown) {
  const reason = text(value, "");
  if (!reason) return "";
  if (reason === "completed") return "已完成";
  if (reason === "running") return "运行中";
  if (reason === "not_executed_sample") return "样例记录";
  if (reason.includes("checkpoint")) return "检查点已写入。";
  if (reason.includes("projection")) return "上下文已装配。";
  if (reason.length > 80) return "已记录一条运行依据。";
  return reason;
}

function summarizeEvent(event: TimelineEvent) {
  const payload = event.payload ?? {};
  const reason = payload.terminal_reason ?? payload.reason ?? payload.error ?? payload.source;
  if (reason) {
    return reasonLabel(reason);
  }
  if (payload.gate && typeof payload.gate === "object") {
    const gate = payload.gate as Record<string, unknown>;
    return `门禁${text(gate.decision || gate.status, "已记录")}`;
  }
  if (payload.checkpoint_id) {
    return "检查点已写入。";
  }
  if (payload.directive_ref) {
    return "分析指令已绑定。";
  }
  return "已记录运行事件。";
}

function refSummary(refs?: Record<string, unknown>) {
  if (!refs || !Object.keys(refs).length) {
    return [];
  }
  const keys = Object.keys(refs);
  const labels = [
    keys.some((key) => key.includes("prompt")) ? "提示清单" : "",
    keys.some((key) => key.includes("projection")) ? "上下文投影" : "",
    keys.some((key) => key.includes("checkpoint")) ? "检查点" : "",
    keys.some((key) => key.includes("contract")) ? "任务合同" : "",
    keys.some((key) => key.includes("issue")) ? "健康问题" : ""
  ].filter(Boolean);
  return [...new Set(labels.length ? labels : ["运行引用"])];
}

function traceEvents(report: HealthTraceReport | null): TimelineEvent[] {
  const events = report?.task_run_trace?.events;
  if (!Array.isArray(events)) {
    return [];
  }
  return events.map((item) => (typeof item === "object" && item ? item as TimelineEvent : {}));
}

function graphStage(eventType: string) {
  if (eventType.includes("task_run") || eventType.includes("task_contract")) return "入口";
  if (eventType.includes("memory") || eventType.includes("context") || eventType.includes("projection")) return "上下文";
  if (eventType.includes("directive") || eventType.includes("model")) return "模型分析";
  if (eventType.includes("gate") || eventType.includes("tool") || eventType.includes("operation")) return "工具/门禁";
  if (eventType.includes("checkpoint") || eventType.includes("terminal")) return "收口";
  return "运行事件";
}

function graphNodes(events: TimelineEvent[], report: HealthTraceReport | null) {
  const stages = ["入口", "上下文", "模型分析", "工具/门禁", "收口"];
  const problemEvents = new Set((report?.problem_events ?? []).map((event) => String((event as Record<string, unknown>).event_type || "")));
  return stages.map((stage) => {
    const stageEvents = events.filter((event) => graphStage(text(event.event_type, "")) === stage);
    const problemCount = stageEvents.filter((event) => {
      const eventType = text(event.event_type, "");
      return eventTone(eventType) === "health-trace-step--danger" || problemEvents.has(eventType);
    }).length;
    const warningCount = stageEvents.filter((event) => eventTone(text(event.event_type, "")) === "health-trace-step--warning").length;
    return {
      stage,
      count: stageEvents.length,
      keyEvent: stageEvents[stageEvents.length - 1]?.event_type ? eventLabel(text(stageEvents[stageEvents.length - 1]?.event_type, "")) : "暂无事件",
      tone: problemCount ? "danger" : warningCount ? "warning" : stageEvents.length ? "success" : "idle",
      summary: problemCount
        ? `${problemCount} 个异常事件`
        : warningCount
          ? `${warningCount} 个门禁/阻断信号`
          : stageEvents.length
            ? `${stageEvents.length} 个事件`
            : "未记录",
    };
  });
}

export function HealthTraceTimeline({
  report,
  selectedRunId
}: {
  report: HealthTraceReport | null;
  selectedRunId: string;
}) {
  const events = traceEvents(report);

  if (!selectedRunId) {
    return (
      <div className="health-empty-state">
        <FileWarning size={18} />
        <span>选择一条问题分析后查看运行时链路证据。</span>
      </div>
    );
  }

  if (!events.length) {
    return (
      <div className="health-empty-state">
        <FileWarning size={18} />
        <span>当前运行还没有可展示的证据报告。</span>
      </div>
    );
  }

  return (
    <div className="health-trace-workbench">
      <section className="health-problem-graph health-chain-map" aria-label="问题链路节点关系">
        {graphNodes(events, report).map((node, index, nodes) => (
          <article className={`health-problem-node health-problem-node--${node.tone}`} key={node.stage}>
            <div>
              <span>{index + 1}</span>
              <strong>{node.stage}</strong>
              <em>{node.summary}</em>
              <small>{node.keyEvent}</small>
            </div>
            {index < nodes.length - 1 ? <i aria-hidden="true"><b /></i> : null}
          </article>
        ))}
      </section>

      {report?.problem_events?.length ? (
        <section className="health-problem-events">
          <span>优先排查</span>
          {report.problem_events.slice(0, 3).map((event, index) => (
            <article key={`${String(event.event_id || event.event_type || "problem")}-${index}`}>
              <strong>{eventLabel(String(event.event_type || "problem_event"))}</strong>
              <p>{text(event.summary, "发现一个需要复核的链路节点。")}</p>
            </article>
          ))}
        </section>
      ) : null}

      <details className="health-trace-details" open>
        <summary>支撑事件</summary>
        <div className="health-trace-timeline">
          {events.map((event, index) => {
            const eventType = text(event.event_type, "runtime_event");
            const Icon = eventIcon(eventType);
            const refs = refSummary(event.refs);
            return (
              <article className={`health-trace-step ${eventTone(eventType)}`} key={`${event.event_id || eventType}-${index}`}>
                <div className="health-trace-step__icon">
                  <Icon size={15} />
                </div>
                <div className="health-trace-step__body">
                  <div>
                    <strong>{eventLabel(eventType)}</strong>
                    <span>#{text(event.offset ?? index)}</span>
                  </div>
                  <p>{summarizeEvent(event)}</p>
                  {refs.length ? (
                    <div className="health-ref-row">
                      {refs.map((ref) => <em key={ref}>{ref}</em>)}
                    </div>
                  ) : null}
                </div>
              </article>
            );
          })}
        </div>
      </details>
    </div>
  );
}
