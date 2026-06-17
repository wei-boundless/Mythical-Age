"use client";

import React from "react";

import type { ActivityEntry } from "./PublicTimelineActivity";

export function TodoPlan({ entry }: { entry: ActivityEntry }) {
  const items = entry.todoItems ?? [];
  const completed = items.filter((item) => cleanText(item.status).toLowerCase() === "completed").length;
  const active = items.find((item) => cleanText(item.todo_id) === entry.activeItemId)
    ?? items.find((item) => cleanText(item.status).toLowerCase() === "in_progress");
  const activeText = active ? cleanText(active.active_form || active.content) : "";
  const summary = activeText
    ? `${completed}/${items.length} 已完成，正在：${activeText}`
    : `${completed}/${items.length} 已完成`;
  return (
    <div
      className="public-run-activity__todo-block"
      data-activity-id={entry.id}
      data-activity-kind={entry.kind}
      data-completion-ready={entry.completionReady === true ? "true" : "false"}
    >
      <div className="public-run-activity__todo-head">
        <p><span>{entry.text || "任务清单"}</span></p>
        <small>{summary}</small>
      </div>
      <div className="public-run-activity__todo-list">
        {items.map((item, index) => {
          const status = cleanText(item.status).toLowerCase();
          const completedItem = status === "completed";
          const activeItem = cleanText(item.todo_id) === entry.activeItemId || status === "in_progress";
          const label = activeItem ? cleanText(item.active_form || item.content) : cleanText(item.content);
          const note = cleanText(item.notes);
          return (
            <div
              className={`public-run-activity__todo${completedItem ? " public-run-activity__todo--completed" : ""}`}
              data-todo-status={status || "pending"}
              key={cleanText(item.todo_id) || `${entry.id}:${index}`}
            >
              <b>{String(index + 1)}</b>
              <span>{note ? `${label} - ${note}` : label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function cleanText(value: unknown) {
  return String(value ?? "").trim();
}
