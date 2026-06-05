"use client";

import React from "react";

import type { PublicChatTimelineItem } from "@/lib/api";
import {
  hasAgentRunProjection,
  hasProjectedPublicRunActivity,
  projectAgentRun,
  type AgentRunCommandOutput,
  type AgentRunProjection,
  type TodoProjection,
} from "@/components/chat/agentRunProjection";

type PublicRunActivityProps = {
  assistantContent?: string;
  items?: PublicChatTimelineItem[];
  projection?: AgentRunProjection;
};

export function hasPublicRunActivity(
  items: PublicChatTimelineItem[],
  assistantContent = "",
) {
  return hasProjectedPublicRunActivity(items, assistantContent);
}

export function PublicRunActivity({
  assistantContent = "",
  items = [],
  projection,
}: PublicRunActivityProps) {
  const view = projection ?? projectAgentRun(items, assistantContent);
  if (!hasAgentRunProjection(view)) {
    return null;
  }

  return (
    <div className={`public-run-activity public-run-activity--${view.tone}`} aria-label="处理进展">
      {view.stopped ? (
        <ActivityLine kind="stopped" text={view.stopped} />
      ) : (
        <>
          {view.liveAction ? <ActivityLine kind="action" text={view.liveAction} /> : null}
          {view.feedback ? <ActivityLine kind="feedback" text={view.feedback} /> : null}
          {view.commandOutput ? <CommandOutputPanel output={view.commandOutput} /> : null}
          {view.todo ? <TodoBlock todo={view.todo} /> : null}
          {view.closeout ? <ActivityLine kind="closeout" label="收尾总结" text={view.closeout} /> : null}
        </>
      )}
    </div>
  );
}

function ActivityLine({
  kind,
  label = "",
  text,
}: {
  kind: "action" | "closeout" | "feedback" | "stopped";
  label?: string;
  text: string;
}) {
  return (
    <div className={`public-run-activity__line public-run-activity__line--${kind}`}>
      {label ? <span className="public-run-activity__label">{label}</span> : null}
      <p>{text}</p>
    </div>
  );
}

function CommandOutputPanel({ output }: { output: AgentRunCommandOutput }) {
  return (
    <details className="public-run-activity__command-output" key={output.key}>
      <summary>Ran command</summary>
      <div className="public-run-activity__command-shell">
        <span>{output.label}</span>
        <pre>{output.content}</pre>
      </div>
    </details>
  );
}

function TodoBlock({ todo }: { todo: TodoProjection }) {
  return (
    <div className="public-run-activity__todo-block">
      <div className="public-run-activity__todo-head">
        <p>{todo.title}</p>
        {todo.activeText ? <small>{todo.activeText}</small> : null}
        {todo.detail ? <small>{todo.detail}</small> : null}
      </div>
      {todo.items.length ? (
        <span className="public-run-activity__todo-list">
          {todo.items.map((item) => (
            <span className={`public-run-activity__todo public-run-activity__todo--${item.status}`} key={item.id || item.content}>
              <b aria-hidden="true">{item.status === "completed" ? "✓" : item.status === "in_progress" ? "●" : "○"}</b>
              <span>{item.content}</span>
            </span>
          ))}
          {todo.hidden ? <em>还有 {todo.hidden} 项</em> : null}
        </span>
      ) : null}
    </div>
  );
}
