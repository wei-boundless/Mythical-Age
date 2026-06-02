"use client";

import {
  Check,
  CheckCircle2,
  ChevronRight,
  Circle,
  CircleDot,
  CircleEllipsis,
  CircleX,
} from "lucide-react";
import React, { useMemo } from "react";

import type {
  RuntimeProgressMission,
  RuntimeProgressPresentation,
  RuntimeProgressTechnicalTrace,
  RuntimeProgressWorkUnit,
  SessionRuntimeAttachment,
} from "@/lib/api";
import type { RuntimeProgressEntry, SessionActivityLevel } from "@/lib/store/types";

const MAX_TRACE_ROWS = 12;

type RuntimeRunState = "error" | "waiting" | "running" | "success" | "stopped";

const INTERNAL_TRACE_EVENT_TYPES = new Set([
  "agent_todo_initialized",
  "runtime_invocation_packet_compiled",
  "task_execution_packet_compiled",
  "task_model_action_wait_heartbeat",
  "model_action_admission_checked",
  "task_run_executor_claimed",
  "task_run_executor_scheduled",
  "task_run_lifecycle_started",
  "task_run_executor_started",
]);

const MACHINE_PHASES = new Set([
  "处理已停止",
  "处理已完成",
  "处理完成",
  "处理遇到阻塞",
  "确认阻塞原因",
  "确认阻塞边界",
  "推进中",
  "失败",
  "受阻",
  "已停止",
]);

function cleanText(value: unknown) {
  return String(value ?? "")
    .replace(/\s+/g, " ")
    .trim();
}

function short(value: unknown, limit = 180) {
  const normalized = cleanText(value);
  return normalized.length > limit ? `${normalized.slice(0, limit - 1)}...` : normalized;
}

function looksLikeRawJson(value: string) {
  const text = value.trim();
  return (text.startsWith("{") && text.endsWith("}")) || (text.startsWith("[") && text.endsWith("]"));
}

function looksLikeInternalReference(value: string) {
  return /^(?:task|taskrun|turn|turnrun|session|taskinst|coordrun|grun|rtevt|rtobs|obs)[:_-]/i.test(value)
    || /^(?:harness|backend|runtime|query|agent_system|capability_system|health_system|task_system)(?:\.[A-Za-z0-9_-]+){2,}$/i.test(value);
}

function visibleText(value: unknown, limit = 180) {
  const text = short(value, limit);
  const lower = text.toLowerCase();
  if (!text) return "";
  if (["true", "false", "null", "none", "running", "working", "ready_to_finish", "completed"].includes(lower)) return "";
  if (text === "已同步最新进展。" || text === "工具调用已完成，正在根据结果继续。") return "";
  if (looksLikeRawJson(text) || looksLikeInternalReference(text)) return "";
  return text;
}

function readableFeedbackText(value: unknown, limit = 180) {
  let text = visibleText(value, Math.max(limit, 320));
  if (!text) return "";
  text = text
    .replace(/\bImage generation is not configured\b/g, "生图服务没有配置")
    .replace(/\bimage generation is not configured\b/gi, "生图服务没有配置")
    .replace(/\btask_executor_schedule_failed\b/g, "任务调度失败")
    .replace(/\bsingle_turn_tool_iteration_limit\b/g, "工具检查次数达到边界")
    .replace(/[（(]\s*target\s+id\s*[:：]\s*[^)）]+[)）]/gi, "")
    .replace(/\btarget\s+id\s*[:：]\s*[A-Za-z0-9_.:-]+/gi, "相关产物")
    .replace(/target_id/gi, "图像目标")
    .replace(/target\s+id/gi, "图像目标")
    .replace(/[（(]\s*错误代码\s*[:：]\s*[^)）]+[)）]/g, "")
    .replace(/\b[A-Za-z]:[\\/][^\s，。；;、]+/g, "相关文件")
    .replace(/\bstorage\/[^\s，。；;、]+/g, "相关文件");
  text = text
    .replace(/图像生成服务不可用[：:，,\s]*/g, "")
    .replace(/图片生成服务不可用[：:，,\s]*/g, "")
    .replace(/\s+([，。；：、])/g, "$1")
    .replace(/([（(])\s+/g, "$1")
    .replace(/\s+([）)])/g, "$1")
    .trim();
  if (/生图服务没有配置/.test(text) && /(?:图像|图片|生图|image_generate)/i.test(text)) {
    return "图像生成这一步卡住了，因为生图服务还没有可用配置。";
  }
  if (/工具检查次数达到边界/.test(text)) {
    return "连续几次工具检查没有拿到新信息，我会基于已有事实收口，或等你指定要继续核查的位置。";
  }
  text = text.replace(/(?:相关产物[、,\s]*){2,}/g, "相关产物");
  return short(text, limit);
}

function runStateFromValue(value: unknown): RuntimeRunState | null {
  const status = cleanText(value).toLowerCase();
  if (!status) return null;
  if (
    ["failed", "error", "aborted", "cancelled", "blocked", "失败", "受阻"].includes(status)
    || status.includes("failed")
    || status.includes("error")
    || status.includes("blocked")
    || status.includes("limit")
    || status.includes("exhausted")
    || status.includes("repair_required")
  ) return "error";
  if (["stopped", "已停止", "user_stopped"].includes(status)) return "stopped";
  if (status.includes("waiting") || status.includes("等待") || status === "queued" || status === "paused") return "waiting";
  if (["completed", "success", "完成", "已完成"].includes(status)) return "success";
  if (["created", "running", "进行中", "运行中"].includes(status)) return "running";
  return null;
}

function stateLabel(state: RuntimeRunState) {
  if (state === "success") return "已完成";
  if (state === "error") return "失败";
  if (state === "waiting") return "等待";
  if (state === "stopped") return "已停止";
  return "进行中";
}

function workUnitState(unit: RuntimeProgressWorkUnit | undefined, runState: RuntimeRunState): RuntimeRunState {
  const state = cleanText(unit?.state).toLowerCase();
  if (state === "error" || state === "failed" || state === "blocked") return "error";
  if (state === "waiting") return "waiting";
  if (state === "completed" || state === "success") return "success";
  return runState === "success" ? "success" : runState;
}

function missionRunState(mission: RuntimeProgressMission | undefined, attachments: SessionRuntimeAttachment[], entries: RuntimeProgressEntry[]): RuntimeRunState {
  const states = [
    runStateFromValue(mission?.state),
    ...attachments.flatMap((attachment) => [
      runStateFromValue(attachment.status),
      runStateFromValue(attachment.lifecycle),
      runStateFromValue(attachment.terminal_reason),
    ]),
    ...entries.map((entry) => runStateFromValue(entry.statusText) || runStateFromLevel(entry.level)),
  ].filter((item): item is RuntimeRunState => Boolean(item));
  if (states.includes("error")) return "error";
  if (states.includes("stopped")) return "stopped";
  if (states.includes("waiting")) return "waiting";
  if (states.includes("running")) return "running";
  return states.includes("success") ? "success" : "running";
}

function runStateFromLevel(level: SessionActivityLevel | undefined): RuntimeRunState | null {
  if (level === "error") return "error";
  if (level === "stopped") return "stopped";
  if (level === "waiting") return "waiting";
  if (level === "success") return "success";
  if (level === "running") return "running";
  return null;
}

function statusIcon(state: RuntimeRunState, size = 14) {
  if (state === "success") return <CheckCircle2 size={size} />;
  if (state === "error") return <CircleX size={size} />;
  if (state === "waiting") return <CircleEllipsis size={size} />;
  if (state === "stopped") return <Circle size={size} />;
  return <CircleDot size={size} />;
}

function visibleTechnicalTraceRows(trace: RuntimeProgressTechnicalTrace[]): RuntimeProgressTechnicalTrace[] {
  return trace
    .map((item): RuntimeProgressTechnicalTrace | null => {
      const eventType = cleanText(item.event_type);
      const stepLike = cleanText(item.event_id || eventType || item.raw_preview);
      if (INTERNAL_TRACE_EVENT_TYPES.has(eventType)) {
        return null;
      }
      if (eventType === "step_summary_recorded" && !cleanText(item.tool_name) && !cleanText(item.target)) {
        return null;
      }
      const rawPreview = cleanText(item.raw_preview);
      const safePreview = looksLikeRawJson(rawPreview) ? "" : readableFeedbackText(rawPreview, 220);
      if (!cleanText(item.tool_name) && !cleanText(item.target) && !safePreview) {
        return null;
      }
      return {
        ...item,
        event_type: traceEventLabel(item),
        raw_preview: safePreview,
        event_id: stepLike,
      };
    })
    .filter((item): item is RuntimeProgressTechnicalTrace => Boolean(item))
    .slice(-MAX_TRACE_ROWS);
}

function traceEventLabel(item: RuntimeProgressTechnicalTrace) {
  const eventType = cleanText(item.event_type);
  if (cleanText(item.tool_name)) {
    return eventType.includes("observation") ? "工具结果" : "工具调用";
  }
  if (eventType.includes("observation")) return "观察结果";
  if (eventType.includes("verification")) return "验证";
  return "执行细节";
}

function normalizePresentation(value: unknown): RuntimeProgressPresentation | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const presentation = value as RuntimeProgressPresentation;
  const hasMission = presentation.mission && typeof presentation.mission === "object";
  const hasUnits = Array.isArray(presentation.work_units) && presentation.work_units.length > 0;
  const hasTrace = Array.isArray(presentation.technical_trace) && presentation.technical_trace.length > 0;
  return hasMission || hasUnits || hasTrace ? presentation : null;
}

function latestPresentation(attachments: SessionRuntimeAttachment[]) {
  return attachments
    .map((attachment) => ({
      attachment,
      presentation: normalizePresentation(attachment.progress_presentation),
      updatedAt: Number(attachment.updated_at ?? attachment.created_at ?? 0) || 0,
    }))
    .filter((item): item is { attachment: SessionRuntimeAttachment; presentation: RuntimeProgressPresentation; updatedAt: number } => Boolean(item.presentation))
    .sort((left, right) => left.updatedAt - right.updatedAt)
    .at(-1);
}

function attachmentRunId(attachment: SessionRuntimeAttachment) {
  return cleanText(attachment.run_id || attachment.task_run_id || attachment.attachment_id);
}

function traceFromProgressEntries(entries: RuntimeProgressEntry[], attachments: SessionRuntimeAttachment[]): RuntimeProgressTechnicalTrace[] {
  const attachmentEntries = attachments.flatMap((attachment) => {
    const runId = attachmentRunId(attachment);
    return Array.isArray(attachment.progress_entries)
      ? attachment.progress_entries.map((item) => ({
          event_id: cleanText(item.id ?? `${runId}:${item.eventType ?? item.event_type ?? ""}`),
          event_type: cleanText(item.eventType ?? item.event_type ?? attachment.latest_event_type ?? "runtime_attachment"),
          tool_name: cleanText(item.toolName ?? item.tool_name ?? ""),
          raw_preview: cleanText(item.body ?? item.publicNote ?? item.public_progress_note ?? item.summary ?? attachment.latest_step_summary ?? ""),
        }))
      : [];
  });
  const liveEntries = entries.map((entry) => ({
    event_id: entry.id,
    event_type: entry.eventType,
    tool_name: entry.toolName,
    raw_preview: cleanText(entry.body || entry.publicNote || entry.agentBrief || entry.title),
  }));
  return [...liveEntries, ...attachmentEntries].filter((item) => item.event_id || item.raw_preview).slice(-MAX_TRACE_ROWS);
}

function fallbackPresentation(entries: RuntimeProgressEntry[], attachments: SessionRuntimeAttachment[]): RuntimeProgressPresentation | null {
  const latestEntry = [...entries].reverse().find((entry) => visibleText(entry.publicNote || entry.body || entry.title));
  const latestAttachment = [...attachments].reverse().find((attachment) => visibleText(attachment.latest_step_summary || attachment.summary || attachment.final_answer));
  const currentAction = visibleText(
    latestEntry?.publicNote
    || latestEntry?.body
    || latestEntry?.title
    || latestAttachment?.latest_step_summary
    || latestAttachment?.summary
    || latestAttachment?.final_answer,
  );
  const trace = traceFromProgressEntries(entries, attachments);
  if (!currentAction && !trace.length) return null;
  return {
    mission: {
      goal: visibleText(latestAttachment?.title) || "处理当前任务",
      phase: runStateFromValue(latestAttachment?.status) === "success" ? "结果收口" : "推进中",
      state: latestAttachment?.status || latestEntry?.statusText || "running",
      current_action: currentAction || "正在处理。",
      progress_label: stateLabel(runStateFromValue(latestAttachment?.status) || runStateFromLevel(latestEntry?.level) || "running"),
      closeout_summary: runStateFromValue(latestAttachment?.status) === "success" ? visibleText(latestAttachment?.final_answer || latestAttachment?.summary) : "",
    },
    work_units: [],
    technical_trace: trace,
    authority: "frontend.runtime_run_summary.fallback",
  };
}

function pickCurrentUnit(units: RuntimeProgressWorkUnit[]) {
  if (!units.length) return null;
  const activeIndex = (() => {
    for (let index = units.length - 1; index >= 0; index -= 1) {
      const state = cleanText(units[index].state).toLowerCase();
      if (state !== "completed" && state !== "success") return index;
    }
    return units.length - 1;
  })();
  return units[activeIndex];
}

function unitSummary(unit: RuntimeProgressWorkUnit | null, limit = 220) {
  if (!unit) return "";
  const evidence = Array.isArray(unit.evidence) ? unit.evidence.find((item) => visibleText(item.summary)) : null;
  return readableFeedbackText(unit.judgment || evidence?.summary || unit.action || unit.next_action, limit);
}

function runStateActionLabel(state: RuntimeRunState) {
  if (state === "success") return "我已经处理完";
  if (state === "error") return "我卡在这里";
  if (state === "waiting") return "我在等你确认";
  if (state === "stopped") return "我已停止";
  return "我正在处理";
}

function progressMeta(units: RuntimeProgressWorkUnit[], mission: RuntimeProgressMission) {
  const label = visibleText(mission.progress_label, 48);
  if (MACHINE_PHASES.has(label)) {
    return "";
  }
  if (/^\d+\s*\/\s*\d+/.test(label)) {
    return "";
  }
  return label;
}

function displayPhase(value: unknown, state: RuntimeRunState) {
  const phase = visibleText(value, 72);
  if (!phase) return "";
  if (MACHINE_PHASES.has(phase)) return "";
  if (state === "error" && /^(处理|确认|失败|受阻|已停止)/.test(phase)) return "";
  return phase;
}

function closeoutHeadline(value: unknown) {
  const text = visibleText(value, 220).replace(/^完成[。；;，,\s]*/, "");
  if (!text) return "";
  const sentence = text.match(/^(.+?[。！？!?])/)?.[1];
  return visibleText(sentence || text, 96);
}

function progressContext(phase: string, meta: string) {
  return [phase, meta].filter(Boolean).join(" · ");
}

function nextActionSentence(value: string) {
  if (!value) return "";
  if (/^(接下来|下一步|然后|我会|继续|等待)/.test(value)) {
    return value;
  }
  return `接下来我会${value.replace(/^[，,。\s]+/, "")}`;
}

function RuntimeMissionStrip({
  mission,
  runState,
  current,
  units,
}: {
  mission: RuntimeProgressMission;
  runState: RuntimeRunState;
  current: RuntimeProgressWorkUnit | null;
  units: RuntimeProgressWorkUnit[];
}) {
  const phase = displayPhase(current?.title || mission.phase, runState);
  const closeout = runState === "success" ? closeoutHeadline(mission.closeout_summary) : "";
  const currentAction = closeout || unitSummary(current) || readableFeedbackText(mission.current_action) || stateLabel(runState);
  const nextAction = runState === "running" || runState === "waiting"
    ? readableFeedbackText(current?.next_action || mission.next_action, 160)
    : "";
  const meta = progressMeta(units, mission);
  const context = progressContext(phase, meta);
  return (
    <header className="runtime-mission-strip">
      <span className="runtime-mission-strip__mark" aria-hidden="true">{statusIcon(runState, 15)}</span>
      <div className="runtime-mission-strip__copy">
        <p className="runtime-mission-strip__sentence">
          <strong>{runStateActionLabel(runState)}</strong>
          {context ? <span>{context}</span> : null}
        </p>
        {currentAction ? <p className="runtime-mission-strip__body">{currentAction}</p> : null}
        {nextAction ? (
          <small className="runtime-mission-strip__next">{nextActionSentence(nextAction)}</small>
        ) : null}
      </div>
    </header>
  );
}

function RuntimeTechnicalTraceDrawer({ trace }: { trace: RuntimeProgressTechnicalTrace[] }) {
  const rows = trace;
  if (!rows.length) return null;
  return (
    <details className="runtime-technical-trace">
      <summary>
        <ChevronRight size={13} aria-hidden="true" />
        <span>查看技术细节</span>
        <em>{rows.length}</em>
      </summary>
      <div className="runtime-technical-trace__rows">
        {rows.map((item, index) => (
          <div className="runtime-technical-trace__row" key={`${item.event_id || item.event_type}:${index}`}>
            <span>{short(item.event_type || item.event_id || "runtime_event", 72)}</span>
            {item.tool_name ? <strong>{short(item.tool_name, 42)}</strong> : null}
            {item.target ? <code>{short(item.target, 160)}</code> : null}
            {item.raw_preview ? <code>{short(item.raw_preview, 220)}</code> : null}
          </div>
        ))}
      </div>
    </details>
  );
}

function RuntimeProgressDetailDrawer({
  units,
  trace,
  runState,
}: {
  units: RuntimeProgressWorkUnit[];
  trace: RuntimeProgressTechnicalTrace[];
  runState: RuntimeRunState;
}) {
  const hasUnits = units.length > 0;
  const visibleTrace = visibleTechnicalTraceRows(trace);
  const hasTrace = visibleTrace.length > 0;
  if (!hasUnits && !hasTrace) return null;
  return (
    <details className="runtime-progress-detail">
      <summary>
        <ChevronRight size={13} aria-hidden="true" />
        <span>查看执行细节</span>
        {hasUnits ? <em>{units.length}</em> : null}
      </summary>
      {hasUnits ? (
        <ol className="runtime-progress-detail__units">
          {units.map((unit) => {
            const state = workUnitState(unit, runState);
            const evidence = Array.isArray(unit.evidence) ? unit.evidence.find((item) => visibleText(item.summary)) : null;
            const summary = readableFeedbackText(evidence?.summary || unit.judgment || unit.action || unit.next_action, 180);
            return (
              <li className={`runtime-progress-detail__unit runtime-progress-detail__unit--${state}`} key={unit.unit_id}>
                <span aria-hidden="true">{state === "success" ? <Check size={12} /> : statusIcon(state, 12)}</span>
                <strong>{visibleText(unit.title) || "推进任务"}</strong>
                {summary ? <small>{summary}</small> : null}
              </li>
            );
          })}
        </ol>
      ) : null}
      <RuntimeTechnicalTraceDrawer trace={visibleTrace} />
    </details>
  );
}

export function RuntimeRunSummary({ entries, attachments = [] }: { entries: RuntimeProgressEntry[]; attachments?: SessionRuntimeAttachment[] }) {
  const prepared = useMemo(() => {
    const latest = latestPresentation(attachments);
    const presentation = latest?.presentation ?? fallbackPresentation(entries, attachments);
    if (!presentation) return null;
    const mission = presentation.mission ?? {};
    const workUnits = Array.isArray(presentation.work_units) ? presentation.work_units : [];
    const trace = [
      ...(Array.isArray(presentation.technical_trace) ? presentation.technical_trace : []),
      ...(latest ? [] : traceFromProgressEntries(entries, attachments)),
    ].slice(-MAX_TRACE_ROWS);
    const runState = missionRunState(mission, latest ? [latest.attachment] : attachments, entries);
    const current = pickCurrentUnit(workUnits);
    return { mission, workUnits, trace, runState, current, hasPresentation: Boolean(latest) };
  }, [entries, attachments]);

  if (!prepared) return null;

  return (
    <section
      aria-label="处理进展"
      className={`runtime-run-summary runtime-run-summary--${prepared.runState} runtime-run-summary--${prepared.hasPresentation ? "presentation" : "inline"}`}
    >
      <RuntimeMissionStrip mission={prepared.mission} runState={prepared.runState} current={prepared.current} units={prepared.workUnits} />
      <RuntimeProgressDetailDrawer units={prepared.workUnits} trace={prepared.trace} runState={prepared.runState} />
    </section>
  );
}
