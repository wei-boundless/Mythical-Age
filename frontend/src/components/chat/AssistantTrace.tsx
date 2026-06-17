"use client";

import React from "react";

import type { ActivityEntry, PublicTimelineActivityTone } from "./PublicTimelineActivity";

export function StatusLine({ entry }: { entry: ActivityEntry }) {
  const statusTone = entry.statusTone ?? "running";
  return (
    <div
      className={`public-run-activity__line public-run-activity__line--status public-run-activity__line--${statusTone}`}
      data-activity-id={entry.id}
      data-activity-kind={entry.statusKind || entry.kind}
      data-status-tone={statusTone}
    >
      <p>
        <span>{entry.text}</span>
        {entry.statusLabel ? (
          <span className={`public-run-activity__tool-window-status public-run-activity__tool-window-status--${statusTone}`}>
            {entry.statusLabel}
          </span>
        ) : null}
      </p>
      {entry.detail ? (
        <div className="public-run-activity__line-detail">
          <p>{entry.detail}</p>
        </div>
      ) : null}
    </div>
  );
}

export function toolRoundStatusLabel(tone: PublicTimelineActivityTone) {
  if (tone === "done") return "已完成";
  if (tone === "soft_error") return "有失败";
  if (tone === "stopped") return "已停止";
  if (tone === "waiting") return "等待中";
  return "运行中";
}
