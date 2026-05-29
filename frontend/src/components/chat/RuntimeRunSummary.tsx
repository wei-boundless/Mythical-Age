"use client";

import { ChevronRight, CircleDashed } from "lucide-react";
import React from "react";
import { useEffect, useState } from "react";

import type { SessionRuntimeAttachment } from "@/lib/api";
import type { RuntimeProgressEntry } from "@/lib/store/types";

const MAX_ACTIVITY_ROWS = 4;
type RuntimeRunState = "error" | "waiting" | "running" | "success";
type RuntimeStepView = {
  id: string;
  level: RuntimeProgressEntry["level"];
  phase: string;
  output: string;
  status: string;
};

function cleanText(value: string | undefined) {
  let normalized = String(value ?? "")
    .replace(/(?:taskrun|taskinst|rtevt|event|runtime|orderrun|order)[:_-][^\s]+/gi, "")
    .replace(/\bTaskRun\b/gi, "当前工作")
    .replace(/\bruntime packet\b/gi, "上下文")
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
    .replace(/\s+/g, " ")
    .trim();
  return normalized;
}

function truncate(value: string | undefined, limit = 150) {
  const normalized = cleanText(value);
  return normalized.length > limit ? `${normalized.slice(0, limit - 1)}...` : normalized;
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

function isFormalTaskEntry(entry: RuntimeProgressEntry) {
  const taskRunId = String(entry.taskRunId ?? "").trim().toLowerCase();
  if (taskRunId.startsWith("turnrun:")) {
    return false;
  }
  if (taskRunId.startsWith("taskrun:turn:")) {
    return true;
  }
  return entry.kind === "task_order" || entry.kind === "task_draft";
}

function entryLabel(entry: RuntimeProgressEntry | undefined) {
  return truncate(
    entry?.meta?.find((item) => item.label === "目标")?.value
    || entry?.body
    || entry?.toolName
    || entry?.title,
    180,
  ) || entry?.toolName || entry?.title || "";
}

function entryTitle(entry: RuntimeProgressEntry) {
  return truncate(entry.title || entry.toolName || entry.body, 72) || "运行步骤";
}

function statusTextLabel(value: string | undefined) {
  const status = cleanText(value).toLowerCase();
  const map: Record<string, string> = {
    aborted: "已中止",
    blocked: "已阻塞",
    cancelled: "已取消",
    completed: "已完成",
    created: "已创建",
    failed: "失败",
    paused: "已暂停",
    queued: "排队中",
    running: "运行中",
    success: "已完成",
    waiting: "等待",
    waiting_approval: "等待确认",
    waiting_executor: "等待继续",
  };
  return map[status] || cleanText(value);
}

function entryStatus(entry: RuntimeProgressEntry) {
  if (entry.level === "error") return "失败";
  if (entry.level === "success" || entry.completedAt) return entry.statusText ? statusTextLabel(entry.statusText) : "已完成";
  if (entry.level === "waiting") return entry.statusText ? statusTextLabel(entry.statusText) : "等待";
  if (entry.statusText) return statusTextLabel(entry.statusText);
  return "运行中";
}

function statusRunState(value: string | undefined): RuntimeRunState | null {
  const status = cleanText(value).toLowerCase();
  if (!status) return null;
  if (["failed", "error", "aborted", "cancelled", "blocked", "失败", "已阻塞"].includes(status)) return "error";
  if (status.includes("waiting") || status.includes("等待") || status === "queued" || status === "paused") return "waiting";
  if (["completed", "success", "完成", "已完成"].includes(status)) return "success";
  if (["created", "running", "运行中"].includes(status)) return "running";
  return null;
}

function isTerminalEntry(entry: RuntimeProgressEntry | undefined) {
  if (!entry) return false;
  const eventType = String(entry.eventType || "").toLowerCase();
  return entry.kind === "terminal"
    || eventType === "done"
    || eventType.includes("terminal")
    || eventType.includes("finished")
    || eventType.includes("completed");
}

function runtimePhase(entry: RuntimeProgressEntry | undefined) {
  const kind = String(entry?.kind || "");
  const text = cleanText(`${entry?.eventType || ""} ${entry?.title || ""} ${entry?.body || ""}`).toLowerCase();
  if (kind === "task_order" || kind === "task_draft") return "确认目标";
  if (kind === "permission" || text.includes("admission") || text.includes("权限") || text.includes("准入")) return "权限确认";
  if (text.includes("packet") || text.includes("上下文") || text.includes("运行时") || text.includes("装配")) return "整理上下文";
  if (kind === "tool" || text.includes("tool") || text.includes("工具")) return "工具执行";
  if (kind === "verification" || text.includes("repair") || text.includes("验收") || text.includes("修复")) return "验收修复";
  if (kind === "artifact" || text.includes("artifact") || text.includes("产物")) return "产物记录";
  if (kind === "terminal" || text.includes("completed") || text.includes("完成") || text.includes("收尾")) return "结果收口";
  if (kind === "model" || text.includes("助手") || text.includes("model_action") || text.includes("模型")) return "思考下一步";
  return "执行推进";
}

function stageOutput(entry: RuntimeProgressEntry | undefined) {
  const raw = entryLabel(entry) || truncate(entry?.title || entry?.toolName || entry?.body, 72);
  const toolName = String(entry?.toolName || "").trim();
  const normalized = cleanText(raw)
    .replace(/^系统已为当前步骤装配 上下文，并交给 助手 判断下一步。?$/i, "正在整理上下文，准备继续处理。")
    .replace(/^已为当前步骤装配 上下文，并交给 助手 判断下一步。?$/i, "正在整理上下文，准备继续处理。")
    .replace(/^当前工作 上下文 已送入模型，系统正在等待 助手 返回任务动作。?$/i, "正在处理这一步。")
    .replace(/^任务 上下文 已送入模型，系统正在等待 助手 返回任务动作。?$/i, "正在处理这一步。")
    .replace(/^上下文 已送入模型，系统正在等待 助手 返回任务动作。?$/i, "正在处理这一步。")
    .replace(/^系统已执行 助手 请求的任务工具调用。?$/i, toolName ? `${toolName} 调用完成，结果已回到助手。` : "工具调用完成，结果已回到助手。")
    .replace(/^系统已执行 助手 请求的任务工具调用，并把真实观察回灌给 助手。?$/i, toolName ? `${toolName} 调用完成，结果已交回助手。` : "工具结果已交回助手。")
    .replace(/^助手 已返回任务动作请求：respond。?$/i, "助手已选择直接回复。")
    .replace(/^助手 已返回任务动作请求：tool_call。?$/i, toolName ? `助手请求调用 ${toolName}。` : "助手请求调用工具。")
    .replace(/^目标已满足，处理流程已完成收尾.*$/i, "目标已满足，结果已记录。")
    .replace(/^目标已满足。?$/i, "目标已满足，准备交付结果。")
    .replace(/^(?:任务)?模型调用仍在进行中，系统继续等待(?:待)? 助手 动作返回。等待轮次：(\d+)。?$/i, "正在生成下一步动作（第 $1 轮等待）。")
    .replace(/^系统已完成动作准入检查：allow。?$/i, "动作已通过准入检查。")
    .replace(/^当前工作处理流程已建立。?$/i, "已确认目标，开始处理。")
    .replace(/^系统已/, "已")
    .replace(/当前任务步骤/g, "当前步骤")
    .trim();
  if (["completed", "success", "完成"].includes(normalized.toLowerCase())) {
    return "目标已满足，结果已记录。";
  }
  return truncate(normalized || "等待阶段输出", 118);
}

function entryLevelForRun(entry: RuntimeProgressEntry, runState: RuntimeRunState, isLatest: boolean): RuntimeProgressEntry["level"] {
  if (runState === "success") return "success";
  if (runState === "error") return isLatest ? "error" : "success";
  if (runState === "waiting") return isLatest ? "waiting" : "success";
  if (isLatest) {
    if (entry.level === "success" || entry.completedAt || statusRunState(entry.statusText) === "success") return "success";
    if (entry.level === "waiting") return "waiting";
    if (entry.level === "error") return "error";
    return "running";
  }
  return "success";
}

function entryStatusForRun(entry: RuntimeProgressEntry, runState: RuntimeRunState, isLatest: boolean) {
  if (runState === "success") return "已完成";
  if (runState === "error") return isLatest ? "失败" : "已完成";
  if (runState === "waiting") return isLatest ? "等待" : "已完成";
  if (isLatest && (entry.level === "success" || entry.completedAt || statusRunState(entry.statusText) === "success")) return "已完成";
  if (isLatest && entry.level === "error") return "失败";
  return isLatest ? entryStatus(entry) : "已完成";
}

function stepView(entry: RuntimeProgressEntry, runState: RuntimeRunState, isLatest: boolean): RuntimeStepView {
  return {
    id: entry.id,
    level: entryLevelForRun(entry, runState, isLatest),
    phase: runtimePhase(entry),
    output: stageOutput(entry),
    status: entryStatusForRun(entry, runState, isLatest),
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
  return expandedStepViews(entries, runState).slice(-MAX_ACTIVITY_ROWS);
}

function runtimeRunState(entries: RuntimeProgressEntry[]): RuntimeRunState {
  const latest = entries[entries.length - 1];
  const latestStatus = statusRunState(latest?.statusText);
  if (latest?.level === "error" || latestStatus === "error") return "error";
  if (latest?.level === "waiting" || latestStatus === "waiting") return "waiting";
  if (isTerminalEntry(latest) && (latest?.level === "success" || latest?.completedAt || latestStatus === "success")) return "success";
  if (entries.some((entry) => entry.level === "error" && isTerminalEntry(entry))) return "error";
  if (entries.some((entry) => entry.level === "waiting" && isTerminalEntry(entry))) return "waiting";
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
  if (states.includes("waiting")) return "waiting";
  if (states.includes("running")) return "running";
  return "success";
}

function runStateLabel(state: RuntimeRunState) {
  const map: Record<RuntimeRunState, string> = {
    error: "失败",
    waiting: "等待处理",
    running: "运行中",
    success: "已完成",
  };
  return map[state];
}

function summaryText(entries: RuntimeProgressEntry[], state: RuntimeRunState) {
  const runtimeEntries = entries.filter((entry) => entry.kind && entry.kind !== "tool");
  const toolCount = entries.filter((entry) => entry.kind === "tool").length;
  const label = "处理进展";
  if (state === "error") return `${label} · 失败`;
  if (state === "waiting") return `${label} · 等待`;
  if (state === "success") return `${label}完成`;
  if (runtimeEntries.length) return label;
  return toolCount ? `运行 ${toolCount} 个工具` : label;
}

function entriesFromAttachments(attachments: SessionRuntimeAttachment[]): RuntimeProgressEntry[] {
  return attachments.flatMap((attachment) => {
    const progress = Array.isArray(attachment.progress_entries)
      ? attachment.progress_entries.map((item) => ({
          id: String(item.id ?? `${attachment.task_run_id}:${item.eventType ?? item.event_type ?? ""}`),
          level: String(item.level ?? "running") as RuntimeProgressEntry["level"],
          title: String(item.title ?? attachment.title ?? "处理进展"),
          body: String(item.body ?? item.summary ?? attachment.latest_step_summary ?? ""),
          eventType: String(item.eventType ?? item.event_type ?? attachment.latest_event_type ?? "runtime_attachment"),
          kind: String(item.kind ?? "stage") as RuntimeProgressEntry["kind"],
          statusText: String(item.statusText ?? item.status ?? attachment.status ?? ""),
          toolName: String(item.toolName ?? ""),
          taskRunId: attachment.task_run_id,
          createdAt: Number(item.createdAt ?? item.created_at ?? 0) || undefined,
      }))
      : [];
    const artifactRefs = Array.isArray(attachment.artifact_refs) ? attachment.artifact_refs : [];
    const attachmentState = attachmentRunState(attachment);
    const shouldAddStatusEntry = progress.length === 0 || attachmentState === "success" || attachmentState === "error" || attachmentState === "waiting";
    const terminalEntry: RuntimeProgressEntry = {
      id: `${attachment.attachment_id}:status`,
      level: attachmentState === "success" ? "success" : attachmentState === "error" ? "error" : attachmentState === "waiting" ? "waiting" : "running",
      title: attachment.status === "completed" ? "已完成" : attachment.title || "处理进展",
      body: attachment.latest_step_summary || attachment.summary || attachment.final_answer || "",
      eventType: attachment.latest_event_type || "runtime_attachment",
      kind: attachmentState === "success" || attachmentState === "error" ? "terminal" : "task_order",
      statusText: attachment.status,
      taskRunId: attachment.task_run_id,
      artifacts: artifactRefs
        .map((item) => ({
          label: "产物",
          path: String(item.path ?? item.absolute_path ?? ""),
        }))
        .filter((item) => item.path)
        .slice(0, 6),
    };
    return shouldAddStatusEntry ? [...progress, terminalEntry] : progress;
  });
}

export function RuntimeRunSummary({ entries, attachments = [] }: { entries: RuntimeProgressEntry[]; attachments?: SessionRuntimeAttachment[] }) {
  const activities = [...entries, ...entriesFromAttachments(attachments)].filter(isVisibleEntry);
  const hasTaskActivity = activities.some(isFormalTaskEntry);
  const Icon = CircleDashed;
  const runState = combinedRunState(activities, attachments);
  const shouldOpenForAttention = runState === "error" || runState === "waiting";
  const [isOpen, setIsOpen] = useState(shouldOpenForAttention);
  const latestActivity = activities[activities.length - 1];
  const latestView = latestActivity ? stepView(latestActivity, runState, true) : null;
  const allStepViews = expandedStepViews(activities, runState);
  const recentStepViews = compactStepViews(activities, runState);
  const toolCount = activities.filter((entry) => entry.kind === "tool").length;
  const completedCount = allStepViews.filter((entry) => entry.level === "success" || entry.status === "已完成").length;
  const progressPercent = runState === "success"
    ? 100
    : allStepViews.length
      ? Math.max(6, Math.round((completedCount / allStepViews.length) * 100))
      : 0;
  const stepSummary = runState === "success" ? `${allStepViews.length} 步` : `${completedCount}/${allStepViews.length} 步`;

  useEffect(() => {
    if (shouldOpenForAttention) {
      setIsOpen(true);
    }
  }, [shouldOpenForAttention]);

  if (!activities.length) return null;

  return (
    <details
      className={`runtime-run-summary ${hasTaskActivity ? "runtime-run-summary--work" : "runtime-run-summary--inline"} runtime-run-summary--${runState}`}
      aria-label="Runtime activity"
      onToggle={(event) => setIsOpen(event.currentTarget.open)}
      open={isOpen}
    >
      <summary className="runtime-run-summary__header">
        <span className="runtime-run-summary__icon">
          <Icon size={13} />
        </span>
        <span className="runtime-run-summary__summary">
          <span className="runtime-run-summary__line">
            <strong>{summaryText(activities, runState)}</strong>
            <em className="runtime-run-summary__state">{runStateLabel(runState)}</em>
          </span>
          <span className="runtime-run-summary__latest">
            <b>{latestView?.phase || "执行推进"}</b>
            <span>{latestView?.output || "等待阶段进展。"}</span>
          </span>
          <span className="runtime-run-summary__progress" aria-hidden="true">
            <i style={{ width: `${progressPercent}%` }} />
          </span>
        </span>
        <span className="runtime-run-summary__meta">
          {toolCount ? <span>{toolCount} 工具</span> : null}
          <span>{stepSummary}</span>
        </span>
        <ChevronRight size={13} className="runtime-run-summary__chevron" />
      </summary>
      <div className="runtime-run-summary__items">
        {recentStepViews.map((entry) => (
          <div className="runtime-run-summary__item" data-level={entry.level} key={entry.id}>
            <span className="runtime-run-summary__item-copy">
              <strong>{entry.phase}</strong>
              <span>{entry.output}</span>
            </span>
            <em>{entry.status}</em>
          </div>
        ))}
      </div>
    </details>
  );
}
