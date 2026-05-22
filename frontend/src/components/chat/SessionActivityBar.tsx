"use client";

import { AlertTriangle, CheckCircle2, Loader2, PauseCircle, Square, Wrench } from "lucide-react";

import type { SessionActivityState } from "@/lib/store/types";

function statusIcon(level: SessionActivityState["level"], hasTool: boolean) {
  if (hasTool) return <Wrench size={14} />;
  if (level === "success") return <CheckCircle2 size={14} />;
  if (level === "error") return <AlertTriangle size={14} />;
  if (level === "stopped") return <Square size={13} />;
  if (level === "waiting") return <PauseCircle size={14} />;
  if (level === "running") return <Loader2 className="session-activity-bar__spin" size={14} />;
  return null;
}

function isMachineNoise(value: string) {
  const text = value.trim();
  if (!text) return true;
  return /^(taskrun|taskinst|turn|runtime_live_monitor|user_message|tool[_:-]|event[_:-])/i.test(text);
}

export function SessionActivityBar({
  activity,
  active,
}: {
  activity: SessionActivityState;
  active: boolean;
}) {
  const hasTool = Boolean(activity.toolName);
  const receipt = activity.receipt ?? null;
  const rawLevel = receipt?.level ?? activity.level;
  const level = active ? rawLevel : rawLevel === "running" ? "idle" : rawLevel;
  const title = active || rawLevel !== "running" ? receipt?.title ?? activity.title : "";
  const rawDetail = active || rawLevel !== "running" ? receipt?.body ?? activity.detail : "";
  const detail = isMachineNoise(rawDetail) ? "" : rawDetail;
  const artifacts = receipt?.artifacts?.filter((artifact) => artifact.path || artifact.value) ?? [];

  if (!title && !detail && !activity.event) {
    return null;
  }

  return (
    <div className={`session-activity-bar session-activity-bar--${level}`} aria-live="polite">
      <div className="session-activity-bar__main">
        <span className="session-activity-bar__icon">{statusIcon(level, hasTool)}</span>
        <strong>{title}</strong>
        {detail ? <span>{detail}</span> : null}
      </div>
      {artifacts.length ? (
        <div className="session-activity-bar__artifacts" aria-label="本次产物">
          {artifacts.map((artifact, index) => (
            <span key={`${artifact.label}-${artifact.path ?? artifact.value ?? index}`}>
              {artifact.label}：<b>{artifact.path ?? artifact.value}</b>
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}
