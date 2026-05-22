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

export function SessionActivityBar({
  activity,
  active,
}: {
  activity: SessionActivityState;
  active: boolean;
}) {
  const hasTool = Boolean(activity.toolName);
  const level = active ? activity.level : activity.level === "running" ? "idle" : activity.level;
  const title = active || activity.level !== "running" ? activity.title : "";
  const detail = active || activity.level !== "running" ? activity.detail : "";

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
      {activity.event ? <code>{activity.event}</code> : null}
    </div>
  );
}
