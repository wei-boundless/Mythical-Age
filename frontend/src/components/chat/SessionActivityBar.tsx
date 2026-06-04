"use client";

import { CheckCircle2, CircleDot, PauseCircle, Square } from "lucide-react";
import React from "react";

import type { SessionActivityState } from "@/lib/store/types";

function statusIcon(level: SessionActivityState["level"]) {
  if (level === "success") return <CheckCircle2 size={14} />;
  if (level === "warning") return <CircleDot size={14} />;
  if (level === "error") return <CircleDot size={14} />;
  if (level === "stopped") return <Square size={13} />;
  if (level === "waiting") return <PauseCircle size={14} />;
  if (level === "running") return <CircleDot size={14} />;
  return null;
}

function isMachineNoise(value: string) {
  const text = value.trim();
  if (!text) return true;
  return /^(taskrun|taskinst|turn|runtime_live_monitor|user_message|tool[_:-]|event[_:-])/i.test(text);
}

function publicStatusTitle(level: SessionActivityState["level"], title: string) {
  if (level !== "error") return title;
  return title
    .replace(/处理失败/g, "需要调整")
    .replace(/会话连接失败/g, "会话连接需要处理")
    .replace(/失败/g, "未完成");
}

export function SessionActivityBar({
  activity,
  active,
}: {
  activity: SessionActivityState;
  active: boolean;
}) {
  const receipt = activity.receipt ?? null;
  const rawLevel = receipt?.level ?? activity.level;
  const level = active ? rawLevel : rawLevel === "running" ? "idle" : rawLevel;
  const rawTitle = active || rawLevel !== "running" ? receipt?.title ?? activity.title : "";
  const title = publicStatusTitle(rawLevel, rawTitle);
  const rawDetail = active || rawLevel !== "running" ? receipt?.body ?? activity.detail : "";
  const detailSourceEvent = receipt?.debug?.event ?? activity.event;
  const detail = detailSourceEvent === "error" && rawLevel === "error" && rawDetail
    ? "详情已写入会话。"
    : isMachineNoise(rawDetail) ? "" : rawDetail;
  const artifacts = receipt?.artifacts?.filter((artifact) => artifact.path || artifact.value) ?? [];

  if (!title && !detail && !activity.event) {
    return null;
  }

  return (
    <div className={`session-activity-bar session-activity-bar--${level}`} aria-live="polite">
      <div className="session-activity-bar__main">
        <span className="session-activity-bar__icon">{statusIcon(level)}</span>
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
