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

function runStateFromValue(value: unknown): RuntimeRunState | null {
  const status = cleanText(value).toLowerCase();
  if (!status) return null;
  if (["failed", "error", "aborted", "cancelled", "blocked", "失败", "受阻"].includes(status)) return "error";
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
  return visibleText(unit.judgment || evidence?.summary || unit.action || unit.next_action, limit);
}

function runStateActionLabel(state: RuntimeRunState) {
  if (state === "success") return "我已经完成这步";
  if (state === "error") return "我这一步卡住了";
  if (state === "waiting") return "我在等下一步确认";
  if (state === "stopped") return "我已停止处理";
  return "我正在处理";
}

function progressMeta(units: RuntimeProgressWorkUnit[], mission: RuntimeProgressMission) {
  if (units.length) {
    const completed = units.filter((unit) => workUnitState(unit, "running") === "success").length;
    return `${completed}/${units.length} 步`;
  }
  const label = visibleText(mission.progress_label, 48);
  const count = label.match(/^\d+\s*\/\s*\d+/)?.[0];
  return count ? `${count.replace(/\s+/g, "")} 步` : "";
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
  const phase = visibleText(current?.title || mission.phase, 72);
  const closeout = runState === "success" ? closeoutHeadline(mission.closeout_summary) : "";
  const currentAction = closeout || unitSummary(current) || visibleText(mission.current_action) || stateLabel(runState);
  const nextAction = runState === "running" || runState === "waiting"
    ? visibleText(current?.next_action || mission.next_action, 160)
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
  const rows = trace.filter((item) => cleanText(item.event_id || item.event_type || item.raw_preview)).slice(-MAX_TRACE_ROWS);
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
  const hasTrace = trace.length > 0;
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
            const summary = visibleText(evidence?.summary || unit.judgment || unit.action || unit.next_action, 180);
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
      <RuntimeTechnicalTraceDrawer trace={trace} />
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
