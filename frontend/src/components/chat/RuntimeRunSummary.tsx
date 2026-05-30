"use client";

import { Check, Circle, CircleDot, CircleEllipsis, CircleX } from "lucide-react";
import React from "react";
import { useEffect, useMemo, useState } from "react";

import type { SessionRuntimeAttachment } from "@/lib/api";
import type { RuntimeProgressEntry, SessionActivityLevel } from "@/lib/store/types";

const MAX_VISIBLE_STEPS = 5;

type RuntimeRunState = "error" | "waiting" | "running" | "success" | "stopped";
type RuntimeStepView = {
  id: string;
  level: SessionActivityLevel;
  phase: string;
  output: string;
  status: string;
  agentBrief?: string;
};

function cleanText(value: unknown) {
  return String(value ?? "")
    .replace(/(?:taskrun|taskinst|rtevt|event|runtime|orderrun|order)[:_-][^\s]+/gi, "")
    .replace(/(?:^|\s)(?:harness|backend|runtime|query|agent_system|capability_system|health_system|task_system)(?:\.[A-Za-z0-9_-]+){2,}(?=\s|$)/gi, " ")
    .replace(/\bTaskRun\b/gi, "当前工作")
    .replace(/\bruntime packet\b/gi, "上下文")
    .replace(/\bruntime\b/gi, "处理流程")
    .replace(/\bRuntimeInvocationPacket\b/gi, "上下文")
    .replace(/\bagent\b/gi, "助手")
    .replace(/当前任务步骤/g, "当前步骤")
    .replace(/执行器/g, "处理流程")
    .replace(/正式任务/g, "当前工作")
    .replace(/任务合同/g, "目标")
    .replace(/任务生命周期/g, "处理流程")
    .replace(/任务运行时/g, "上下文")
    .replace(/任务运行/g, "处理进展")
    .replace(/会话运行/g, "处理进展")
    .replace(/运行装配/g, "整理上下文")
    .replace(/回灌/g, "交回")
    .replace(/系统已/g, "已")
    .replace(/\s+/g, " ")
    .trim();
}

function truncate(value: unknown, limit = 132) {
  const normalized = cleanText(value);
  return normalized.length > limit ? `${normalized.slice(0, limit - 1)}...` : normalized;
}

function statusTextLabel(value: unknown) {
  const status = cleanText(value).toLowerCase();
  const map: Record<string, string> = {
    aborted: "已中止",
    blocked: "受阻",
    cancelled: "已取消",
    completed: "已完成",
    created: "已开始",
    failed: "失败",
    paused: "已暂停",
    queued: "排队中",
    running: "进行中",
    success: "已完成",
    waiting: "等待",
    waiting_approval: "等待确认",
    waiting_executor: "等待继续",
  };
  return map[status] || cleanText(value);
}

function statusRunState(value: unknown): RuntimeRunState | null {
  const status = cleanText(value).toLowerCase();
  if (!status) return null;
  if (["failed", "error", "aborted", "cancelled", "blocked", "失败", "受阻"].includes(status)) return "error";
  if (["stopped", "已停止", "user_stopped"].includes(status)) return "stopped";
  if (status.includes("waiting") || status.includes("等待") || status === "queued" || status === "paused") return "waiting";
  if (["completed", "success", "完成", "已完成"].includes(status)) return "success";
  if (["created", "running", "进行中", "运行中"].includes(status)) return "running";
  return null;
}

function isVisibleEntry(entry: RuntimeProgressEntry) {
  return [
    "artifact",
    "model",
    "system",
    "task_order",
    "task_draft",
    "stage",
    "tool",
    "verification",
    "permission",
    "terminal",
  ].includes(entry.kind || "");
}

function isWorkEntry(entry: RuntimeProgressEntry) {
  const taskRunId = String(entry.taskRunId ?? "").trim().toLowerCase();
  return taskRunId.startsWith("taskrun:turn:") || entry.kind === "task_order" || entry.kind === "task_draft";
}

function isPlanEntry(entry: RuntimeProgressEntry) {
  return entry.kind === "task_order" || entry.kind === "task_draft";
}

function entryBody(entry: RuntimeProgressEntry | undefined) {
  if (!entry) return "";
  return truncate(
    entry.publicNote
      || entry.meta?.find((item) => item.label === "公开进展")?.value
      || entry.meta?.find((item) => item.label === "目标")?.value
      || entry.body
      || entry.toolName
      || entry.title,
  );
}

function runtimePhase(entry: RuntimeProgressEntry | undefined) {
  const kind = String(entry?.kind || "");
  const text = cleanText(`${entry?.eventType || ""} ${entry?.title || ""} ${entry?.body || ""}`).toLowerCase();
  if (kind === "task_order" || kind === "task_draft") return "确认目标";
  if (kind === "permission" || text.includes("admission") || text.includes("权限") || text.includes("准入")) return "确认边界";
  if (text.includes("packet") || text.includes("上下文") || text.includes("运行时") || text.includes("装配")) return "整理上下文";
  if (kind === "tool" || text.includes("tool") || text.includes("工具")) return "执行操作";
  if (kind === "verification" || text.includes("repair") || text.includes("验收") || text.includes("修复")) return "补齐证据";
  if (kind === "artifact" || text.includes("artifact") || text.includes("产物")) return "记录产物";
  if (kind === "terminal" || text.includes("completed") || text.includes("完成") || text.includes("收尾")) return "结果收口";
  if (kind === "model" || text.includes("助手") || text.includes("model_action") || text.includes("模型")) return "思考下一步";
  return "推进中";
}

function stageOutput(entry: RuntimeProgressEntry | undefined) {
  const toolName = String(entry?.toolName || "").trim();
  const normalized = entryBody(entry)
    .replace(/^已为当前步骤装配 上下文，并交给 助手 判断下一步。?$/i, "正在整理上下文，准备继续处理。")
    .replace(/^当前工作 上下文 已送入模型，正在等待 助手 返回任务动作。?$/i, "正在分析当前目标和已有进展，准备决定下一步。")
    .replace(/^任务 上下文 已送入模型，正在等待 助手 返回任务动作。?$/i, "正在分析当前目标和已有进展，准备决定下一步。")
    .replace(/^上下文 已送入模型，正在等待 助手 返回任务动作。?$/i, "正在分析当前目标和已有进展，准备决定下一步。")
    .replace(/^正在处理这一步。?$/i, "正在分析当前目标和已有进展，准备决定下一步。")
    .replace(/^系统正在等待 助手返回下一步.*$/i, "正在等待下一步结果。")
    .replace(/^已执行 助手 请求的任务工具调用。?$/i, toolName ? `${toolName} 调用完成。` : "工具调用完成。")
    .replace(/^已执行 助手 请求的任务工具调用，并把真实观察交回给 助手。?$/i, toolName ? `${toolName} 调用完成，结果已交回助手。` : "工具结果已交回助手。")
    .replace(/^助手 已返回任务动作请求：respond。?$/i, "助手已形成回复方向。")
    .replace(/^助手 已返回任务动作请求：tool_call。?$/i, toolName ? `助手准备调用 ${toolName}。` : "助手准备调用工具。")
    .replace(/^目标已满足，处理流程已完成收尾.*$/i, "目标已满足，结果已记录。")
    .replace(/^目标已满足。?$/i, "目标已满足，准备交付结果。")
    .replace(/^(?:任务)?模型调用仍在进行中，(?:系统)?继续等待(?:待)? 助手 动作返回。等待轮次：\d+。?$/i, "正在根据当前进展形成下一步处理动作。")
    .replace(/^正在生成下一步动作。?$/i, "正在根据当前进展形成下一步处理动作。")
    .replace(/^已完成动作准入检查：allow。?$/i, "执行边界已确认。")
    .replace(/^当前工作处理流程已建立。?$/i, "已确认目标，开始处理。")
    .trim();
  if (!normalized && (entry?.kind === "terminal" || statusRunState(entry?.statusText) === "success" || entry?.level === "success")) {
    return "目标已满足，结果已记录。";
  }
  if (["completed", "success", "完成"].includes(normalized.toLowerCase())) {
    return "目标已满足，结果已记录。";
  }
  return truncate(normalized || "等待阶段进展。", 126);
}

function entryLevel(entry: RuntimeProgressEntry, runState: RuntimeRunState, isLatest: boolean): SessionActivityLevel {
  if (runState === "success") return "success";
  if (runState === "stopped") return isLatest ? "stopped" : "success";
  if (runState === "error") return isLatest ? "error" : "success";
  if (runState === "waiting") return isLatest ? "waiting" : "success";
  if (!isLatest) return "success";
  if (entry.level === "error") return "error";
  if (entry.level === "waiting") return "waiting";
  if (entry.level === "success" || entry.completedAt || statusRunState(entry.statusText) === "success") return "success";
  return "running";
}

function entryStatus(entry: RuntimeProgressEntry, runState: RuntimeRunState, isLatest: boolean) {
  if (!isLatest) return "已完成";
  if (runState === "success") return "已完成";
  if (runState === "stopped") return "已停止";
  if (runState === "error") return "失败";
  if (runState === "waiting") return "等待";
  if (entry.level === "success" || entry.completedAt || statusRunState(entry.statusText) === "success") return "已完成";
  if (entry.level === "error") return "失败";
  return statusTextLabel(entry.statusText || "running") || "进行中";
}

function agentBrief(entry: RuntimeProgressEntry | undefined) {
  const metaBrief = entry?.meta?.find((item) => ["输出", "简要输出", "助手输出"].includes(item.label))?.value;
  const body = cleanText(entry?.agentBrief || metaBrief || "");
  if (!body) return "";
  return truncate(body, 96);
}

function stepView(entry: RuntimeProgressEntry, runState: RuntimeRunState, isLatest: boolean): RuntimeStepView {
  return {
    id: entry.id,
    level: entryLevel(entry, runState, isLatest),
    phase: runtimePhase(entry),
    output: stageOutput(entry),
    status: entryStatus(entry, runState, isLatest),
    agentBrief: agentBrief(entry),
  };
}

function expandedStepViews(entries: RuntimeProgressEntry[], runState: RuntimeRunState) {
  const latestIndex = entries.length - 1;
  return entries
    .map((entry, index) => stepView(entry, runState, index === latestIndex))
    .filter((entry, index, all) => {
      const previous = all[index - 1];
      return !previous || previous.phase !== entry.phase || previous.output !== entry.output || previous.status !== entry.status;
    });
}

function compactStepViews(entries: RuntimeProgressEntry[], runState: RuntimeRunState) {
  const steps = expandedStepViews(entries, runState);
  if (steps.length < 2) {
    return steps;
  }
  return steps.filter((step, index) => {
    const isLast = index === steps.length - 1;
    const previous = steps[index - 1];
    if (isLast && previous && step.level === previous.level && step.phase === previous.phase && step.output === previous.output) {
      return false;
    }
    return true;
  });
}

function isTerminalEntry(entry: RuntimeProgressEntry | undefined) {
  if (!entry) return false;
  const eventType = String(entry.eventType || "").toLowerCase();
  return entry.kind === "terminal" || eventType === "done" || eventType === "stopped" || eventType.includes("terminal") || eventType.includes("finished") || eventType.includes("completed");
}

function runtimeRunState(entries: RuntimeProgressEntry[]): RuntimeRunState {
  const latest = entries[entries.length - 1];
  const latestStatus = statusRunState(latest?.statusText);
  if (latest?.level === "error" || latestStatus === "error") return "error";
  if (latest?.level === "stopped" || latestStatus === "stopped") return "stopped";
  if (latest?.level === "waiting" || latestStatus === "waiting") return "waiting";
  if (isTerminalEntry(latest) && (latest?.level === "success" || latest?.completedAt || latestStatus === "success")) return "success";
  if (entries.some((entry) => entry.level === "error" && isTerminalEntry(entry))) return "error";
  if (entries.some((entry) => entry.level === "running")) return "running";
  return entries.length ? "running" : "success";
}

function attachmentRunState(attachment: SessionRuntimeAttachment): RuntimeRunState | null {
  return statusRunState(attachment.status)
    || statusRunState(attachment.lifecycle)
    || statusRunState(String(attachment.latest_step?.status ?? ""))
    || null;
}

function combinedRunState(entries: RuntimeProgressEntry[], attachments: SessionRuntimeAttachment[]) {
  const states = [
    runtimeRunState(entries),
    ...attachments.map(attachmentRunState).filter((state): state is RuntimeRunState => Boolean(state)),
  ];
  if (states.includes("error")) return "error";
  if (states.includes("stopped")) return "stopped";
  if (states.includes("waiting")) return "waiting";
  if (states.includes("running")) return "running";
  return "success";
}

function stepIcon(level: SessionActivityLevel) {
  if (level === "success") return <Check size={12} />;
  if (level === "error") return <CircleX size={13} />;
  if (level === "waiting") return <CircleEllipsis size={13} />;
  if (level === "stopped") return <Circle size={13} />;
  if (level === "running") return <CircleDot size={13} />;
  return <Circle size={13} />;
}

function entriesFromAttachments(attachments: SessionRuntimeAttachment[]): RuntimeProgressEntry[] {
  return attachments.flatMap((attachment) => {
    const progress = Array.isArray(attachment.progress_entries)
      ? attachment.progress_entries.map((item) => ({
          id: String(item.id ?? `${attachment.task_run_id}:${item.eventType ?? item.event_type ?? ""}`),
          level: String(item.level ?? "running") as SessionActivityLevel,
          title: String(item.title ?? attachment.title ?? "处理进展"),
          body: String(item.body ?? item.summary ?? attachment.latest_step_summary ?? ""),
          publicNote: String(item.publicNote ?? item.public_progress_note ?? item.body ?? item.summary ?? attachment.latest_public_progress_note ?? attachment.latest_step_summary ?? ""),
          agentBrief: String(item.agentBrief ?? item.agent_brief_output ?? attachment.agent_brief_output ?? ""),
          evidenceType: String(item.evidenceType ?? item.evidence_type ?? ""),
          eventType: String(item.eventType ?? item.event_type ?? attachment.latest_event_type ?? "runtime_attachment"),
          kind: String(item.kind ?? "stage") as RuntimeProgressEntry["kind"],
          statusText: String(item.statusText ?? item.status ?? attachment.status ?? ""),
          toolName: String(item.toolName ?? ""),
          taskRunId: attachment.task_run_id,
          createdAt: Number(item.createdAt ?? item.created_at ?? 0) || undefined,
          meta: Array.isArray(item.meta) ? item.meta as RuntimeProgressEntry["meta"] : undefined,
        }))
      : [];
    const artifactRefs = Array.isArray(attachment.artifact_refs) ? attachment.artifact_refs : [];
    const attachmentState = attachmentRunState(attachment);
    const hasTerminalProgress = progress.some((item) => isTerminalEntry(item));
    const hasLatestSummary = Boolean(
      String(attachment.latest_step_summary || attachment.summary || attachment.final_answer || "").trim(),
    );
    const shouldAddStatusEntry =
      progress.length === 0
      || attachmentState === "error"
      || attachmentState === "waiting"
      || (attachmentState === "success" && !hasTerminalProgress && hasLatestSummary);
    const terminalEntry: RuntimeProgressEntry = {
      id: `${attachment.attachment_id}:status`,
      level: attachmentState === "success" ? "success" : attachmentState === "error" ? "error" : attachmentState === "waiting" ? "waiting" : "running",
      title: attachment.status === "completed" ? "已完成" : attachment.title || "处理进展",
      body: attachment.latest_step_summary || attachment.summary || attachment.final_answer || "",
      eventType: attachment.latest_event_type || "runtime_attachment",
      kind: attachmentState === "success" || attachmentState === "error" ? "terminal" : "stage",
      statusText: attachment.status,
      taskRunId: attachment.task_run_id,
      artifacts: artifactRefs
        .map((item) => ({ label: "产物", path: String(item.path ?? item.absolute_path ?? "") }))
        .filter((item) => item.path)
        .slice(0, 6),
    };
    return shouldAddStatusEntry ? [...progress, terminalEntry] : progress;
  });
}

function conversationalLine(step: RuntimeStepView, runState: RuntimeRunState, isLatest: boolean) {
  const output = step.output || step.phase;
  if (runState === "success" && isLatest) {
    return output ? `我已经完成这轮处理：${output}` : "我已经完成这轮处理。";
  }
  if (runState === "stopped" && isLatest) {
    return output ? `这轮生成已停止：${output}` : "这轮生成已停止。";
  }
  if (step.level === "error") {
    return output ? `我遇到了一个需要处理的问题：${output}` : "我遇到了一个需要处理的问题，需要先处理后才能继续。";
  }
  if (step.level === "waiting") {
    return output ? `我需要先等你确认：${output}` : "我需要先等你确认。";
  }
  if (step.level === "success" || step.status === "已完成" || (!isLatest && runState !== "error")) {
    return output ? `我已经处理完这一步：${output}` : "我已经处理完这一步。";
  }
  if (/^我/.test(output)) return output;
  if (/^正在/.test(output)) return `我${output}`;
  return output ? `我正在处理：${output}` : "我正在同步当前进展。";
}

export function RuntimeRunSummary({ entries, attachments = [] }: { entries: RuntimeProgressEntry[]; attachments?: SessionRuntimeAttachment[] }) {
  const activities = useMemo(() => [...entries, ...entriesFromAttachments(attachments)].filter(isVisibleEntry), [entries, attachments]);
  const runState = combinedRunState(activities, attachments);
  const [expanded, setExpanded] = useState(runState === "error" || runState === "waiting");
  const planActivities = activities.filter(isPlanEntry);
  const progressActivities = activities.filter((entry) => !isPlanEntry(entry));
  const progressSource = progressActivities.length ? progressActivities : activities;
  const allSteps = compactStepViews(progressSource, runState);
  const planSteps = compactStepViews(planActivities, runState);
  const detailSteps = expanded ? allSteps.slice(0, -1) : [];
  const visibleSteps = detailSteps.slice(-MAX_VISIBLE_STEPS);
  const latest = allSteps[allSteps.length - 1];
  const hasWorkActivity = activities.some(isWorkEntry);
  const hasMoreSteps = detailSteps.length > visibleSteps.length;
  const hasPlan = planSteps.length > 0;

  useEffect(() => {
    if (runState === "error" || runState === "waiting") {
      setExpanded(true);
    }
  }, [runState]);

  if (!activities.length || !latest) return null;

  return (
    <section
      aria-label="处理进展"
      className={`runtime-run-summary ${hasWorkActivity ? "runtime-run-summary--work" : "runtime-run-summary--inline"} runtime-run-summary--${runState}`}
    >
      <button
        aria-expanded={expanded}
        className="runtime-run-summary__header"
        onClick={() => setExpanded((value) => !value)}
        type="button"
      >
        <span className="runtime-run-summary__mark" aria-hidden="true">{stepIcon(runState === "success" ? "success" : latest.level)}</span>
        <span className="runtime-run-summary__summary">
          <span className="runtime-run-summary__line">
            <span>{conversationalLine(latest, runState, true)}</span>
          </span>
          {latest.agentBrief ? <small className="runtime-run-summary__brief">{latest.agentBrief}</small> : null}
        </span>
      </button>
      {hasPlan ? (
        <div className="runtime-run-summary__plan" aria-label="处理计划">
          <strong>计划</strong>
          <ol>
            {planSteps.map((entry) => (
              <li key={entry.id}>{entry.output}</li>
            ))}
          </ol>
        </div>
      ) : null}
      <div className="runtime-run-summary__items" hidden={!expanded || !visibleSteps.length}>
        {visibleSteps.map((entry) => (
          <div className="runtime-run-summary__item" data-level={entry.level} key={entry.id}>
            <span className="runtime-run-summary__item-mark">{stepIcon(entry.level)}</span>
            <span className="runtime-run-summary__item-copy">
              <span>{conversationalLine(entry, runState, false)}</span>
              {entry.agentBrief ? <small>{entry.agentBrief}</small> : null}
            </span>
          </div>
        ))}
        {hasMoreSteps ? <button className="runtime-run-summary__more" onClick={() => setExpanded(true)} type="button">展开更早进展</button> : null}
      </div>
    </section>
  );
}
