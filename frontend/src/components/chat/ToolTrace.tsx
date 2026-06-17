"use client";

import React, { useEffect, useState } from "react";

import type { ActivityEntry, ActivityRenderUnit } from "./PublicTimelineActivity";

export function ToolRound({ group }: { group: Extract<ActivityRenderUnit, { kind: "tool_round" }> }) {
  const defaultOpen = false;
  const [open, setOpen] = useState(defaultOpen);

  useEffect(() => {
    setOpen(defaultOpen);
  }, [group.id, defaultOpen]);

  return (
    <details
      className={`public-run-activity__tool-round public-run-activity__tool-round--${group.statusTone}`}
      data-tool-count={group.count}
      data-status-tone={group.statusTone}
      onToggle={(event) => setOpen(event.currentTarget.open)}
      open={open}
    >
      <summary>
        <span className="public-run-activity__tool-round-icon" aria-hidden="true" />
        <span className="public-run-activity__tool-round-copy">
          <span className="public-run-activity__tool-round-title">工具调用</span>
          <span className="public-run-activity__tool-round-separator" aria-hidden="true">·</span>
          <span className="public-run-activity__tool-round-preview">{group.preview}</span>
        </span>
        <span className="public-run-activity__tool-round-count">{group.count} 个工具</span>
        <span className={`public-run-activity__tool-window-status public-run-activity__tool-window-status--${group.statusTone}`}>
          {group.statusLabel}
        </span>
      </summary>
      <div className="public-run-activity__tool-round-body">
        {group.entries.map((entry) => (
          <ToolWindow entry={entry} key={entry.id} nested />
        ))}
      </div>
    </details>
  );
}

export function ToolWindow({ entry, nested = false }: { entry: ActivityEntry; nested?: boolean }) {
  const defaultOpen = false;
  const [open, setOpen] = useState(defaultOpen);
  const statusTone = entry.statusTone ?? "running";
  const outputText = entry.outputText
    || (statusTone === "running" || statusTone === "waiting" ? "等待系统返回" : "无输出");

  useEffect(() => {
    setOpen(defaultOpen);
  }, [entry.id, defaultOpen]);

  return (
    <details
      className={`public-run-activity__tool-window public-run-activity__tool-window--${statusTone}${nested ? " public-run-activity__tool-window--nested" : ""}`}
      data-activity-id={entry.id}
      data-activity-kind={entry.kind}
      data-status-tone={statusTone}
      onToggle={(event) => setOpen(event.currentTarget.open)}
      open={open}
    >
      <summary>
        <span className="public-run-activity__tool-window-icon" aria-hidden="true" />
        <span className="public-run-activity__tool-window-title">{entry.text}</span>
        <span className={`public-run-activity__tool-window-status public-run-activity__tool-window-status--${statusTone}`}>
          {entry.statusLabel}
        </span>
      </summary>
      <div className="public-run-activity__tool-window-body">
        <div className="public-run-activity__tool-console" role="group" aria-label="工具调用窗口">
          <div className="public-run-activity__tool-console-row public-run-activity__tool-console-row--command">
            <div className="public-run-activity__tool-console-label">{entry.consoleLabel || "命令行"}</div>
            <pre className="public-run-activity__tool-console-command">
              <code>{entry.commandLine ? `$ ${entry.commandLine}` : "$ tool"}</code>
            </pre>
          </div>
          <div className="public-run-activity__tool-console-row public-run-activity__tool-console-row--output">
            <div className="public-run-activity__tool-console-label">系统返回</div>
            <pre className="public-run-activity__tool-console-output">
              <code>{outputText}</code>
            </pre>
          </div>
        </div>
      </div>
    </details>
  );
}
