"use client";

import React, { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { isPublicTimelineBodyItem, looksLikeRawToolOutput, publicTimelineBodyText } from "@/components/chat/agentRunProjection";
import type { PublicChatTimelineItem, PublicTodoItem, SingleAgentTaskProjection, SingleAgentTaskProjectionActivity } from "@/lib/api";
import { cleanPublicTimelineText, normalizePublicTimelineItems } from "@/lib/store/publicTimeline";

type PublicTimelineActivityProps = {
  items?: PublicChatTimelineItem[] | null;
  taskProjections?: SingleAgentTaskProjection[] | null;
};

type PublicTimelineActivityTone = "running" | "done" | "waiting" | "stopped" | "soft_error";

type ActivityEntry = {
  collapsed?: boolean;
  detail?: string;
  id: string;
  kind: "body" | "status" | "stopped" | "todo" | "tool";
  text: string;
  toolWindow?: ToolWindowProjection;
  todo?: TodoProjection;
};

type PublicTimelineActivityView = {
  entries: ActivityEntry[];
  tone: PublicTimelineActivityTone;
};

type TodoProjection = {
  activeText: string;
  detail: string;
  hidden: number;
  items: Array<{
    content: string;
    id: string;
    status: string;
  }>;
  title: string;
};

type ToolWindowProjection = {
  meta: string[];
  sections: Array<{
    label: string;
    text: string;
  }>;
};

export function PublicTimelineActivity({ items, taskProjections }: PublicTimelineActivityProps) {
  const view = publicTimelineActivityView(items, taskProjections);
  if (!view) {
    return null;
  }

  return (
    <div className={`public-run-activity public-run-activity--${view.tone}`} aria-label="处理进展">
      {view.entries.map((entry) => (
        entry.kind === "todo"
          ? entry.todo ? <TodoBlock key={entry.id || entry.text} todo={entry.todo} /> : null
        : entry.kind === "body"
          ? <BodyLine key={entry.id || entry.text} text={entry.text} />
        : entry.kind === "tool"
          ? <ToolWindow entry={entry} key={entry.id || entry.text} />
        : <ActivityLine kind={entry.kind} key={entry.id || entry.text} text={entry.text} />
      ))}
    </div>
  );
}

export function publicTimelineHasDisplayableActivity(
  items: PublicChatTimelineItem[] | null | undefined,
  taskProjections?: SingleAgentTaskProjection[] | null,
) {
  return Boolean(publicTimelineActivityView(items, taskProjections));
}

function publicTimelineActivityView(
  items: PublicChatTimelineItem[] | null | undefined,
  taskProjections?: SingleAgentTaskProjection[] | null,
): PublicTimelineActivityView | null {
  const normalizedItems = normalizePublicTimelineItems(items ?? []);
  const projectionEntries = taskProjectionActivityEntries(taskProjections ?? []);
  const entries = [...projectionEntries, ...activityEntries(normalizedItems)];
  if (!entries.length) {
    return null;
  }
  return {
    entries,
    tone: taskProjectionTone(taskProjections ?? []) || publicTimelineTone(normalizedItems),
  };
}

function taskProjectionActivityEntries(projections: SingleAgentTaskProjection[]): ActivityEntry[] {
  const entries: ActivityEntry[] = [];
  for (const projection of projections) {
    const projectionId = cleanPublicTimelineText(projection.projection_id || projection.task_run_id);
    const todo = taskProjectionTodo(projection);
    if (todo) {
      entries.push({
        id: `${projectionId}:todo`,
        kind: "todo",
        text: todo.activeText || todo.title,
        todo,
      });
    }
    const currentAction = taskProjectionCurrentAction(projection);
    if (currentAction) {
      entries.push(currentAction);
    }
    for (const activity of projection.activities ?? []) {
      const entry = taskProjectionActivityEntry(activity, projectionId);
      if (entry) {
        entries.push(entry);
      }
    }
    const finalAnswer = cleanPublicTimelineText(projection.final_answer);
    if (finalAnswer) {
      entries.push({
        id: `${projectionId}:final`,
        kind: "body",
        text: finalAnswer,
      });
    }
  }
  return dedupeActivityEntries(entries);
}

function taskProjectionTodo(projection: SingleAgentTaskProjection): TodoProjection | null {
  const todo = projection.todo;
  if (!todo?.items?.length) {
    return null;
  }
  return todoProjectionFromItems(todo.items, cleanPublicTimelineText(todo.active_item_id), Boolean(todo.completion_ready));
}

function taskProjectionCurrentAction(projection: SingleAgentTaskProjection): ActivityEntry | null {
  const action = projection.current_action && typeof projection.current_action === "object" && !Array.isArray(projection.current_action)
    ? projection.current_action as Record<string, unknown>
    : {};
  const title = cleanPublicTimelineText(action.title || action.detail || projection.user_visible_goal);
  if (!title) {
    return null;
  }
  const state = cleanPublicTimelineText(action.state || projection.status).toLowerCase();
  return {
    id: `${cleanPublicTimelineText(projection.projection_id || projection.task_run_id)}:current-action`,
    kind: ["failed", "error", "blocked"].includes(state) ? "stopped" : "status",
    text: shortText(title, 220),
  };
}

function taskProjectionActivityEntry(activity: SingleAgentTaskProjectionActivity, projectionId: string): ActivityEntry | null {
  const text = cleanPublicTimelineText(activity.title || activity.detail);
  if (!text) {
    return null;
  }
  const state = cleanPublicTimelineText(activity.state).toLowerCase();
  const kind = cleanPublicTimelineText(activity.kind).toLowerCase();
  return {
    id: cleanPublicTimelineText(activity.activity_id) || `${projectionId}:activity:${kind}:${text}`,
    kind: kind === "final" ? "body" : ["failed", "error", "blocked"].includes(state) || kind === "error" ? "stopped" : "status",
    text: shortText(text, 220),
  };
}

function dedupeActivityEntries(entries: ActivityEntry[]) {
  const seen = new Set<string>();
  const result: ActivityEntry[] = [];
  for (const entry of entries) {
    const key = entry.id || `${entry.kind}:${entry.text}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    result.push(entry);
  }
  return result;
}

function activityEntries(items: PublicChatTimelineItem[]): ActivityEntry[] {
  const entries: ActivityEntry[] = [];
  const latestBodyIndex = latestModelBodyIndex(items);
  for (const [index, item] of items.entries()) {
    if (kindOf(item) === "todo_plan") {
      const todo = todoProjectionFromTimelineItem(item);
      if (todo) {
        entries.push({
          id: String(item.item_id ?? "") || `todo:${index}`,
          kind: "todo",
          text: todo.activeText || todo.title,
          todo,
        });
      }
      continue;
    }
    const kind = activityLineKind(item);
    if (!kind) {
      continue;
    }
    const text = publicText(item);
    if (!text) {
      continue;
    }
    const detail = kind === "tool" ? toolDetailText(item, text) : "";
    entries.push({
      collapsed: kind === "tool" ? shouldCollapseToolWindow(item, index, latestBodyIndex) : undefined,
      detail,
      id: String(item.item_id ?? "") || `${kind}:${index}:${text}`,
      kind,
      text: kind === "body" ? text : shortText(text, kind === "tool" ? 180 : 220),
      toolWindow: kind === "tool" ? toolWindowProjection(item, detail) : undefined,
    });
  }
  return entries;
}

function activityLineKind(item: PublicChatTimelineItem): ActivityEntry["kind"] | "" {
  if (isPublicTimelineBodyItem(item)) return "body";
  const kind = kindOf(item);
  const surface = cleanPublicTimelineText(item.surface);
  if (kind === "blocked") return "stopped";
  if (surface === "tool_window" || ["work_action", "tool_activity"].includes(kind)) return "tool";
  if (surface === "status" || ["artifact", "status_update", "verification"].includes(kind)) return "status";
  return "";
}

function shouldCollapseToolWindow(item: PublicChatTimelineItem, index: number, latestBodyIndex: number) {
  const state = cleanPublicTimelineText(item.state).toLowerCase();
  const running = ["", "running", "working", "partial"].includes(state) || item.stream_state === "streaming";
  const failed = ["error", "failed", "blocked", "missing"].includes(state);
  if (running || failed) return false;
  if (latestBodyIndex > index) return true;
  if (typeof item.collapsed === "boolean") return item.collapsed;
  return Boolean(item.collapse_after_body_feedback);
}

function latestModelBodyIndex(items: PublicChatTimelineItem[]) {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    if (isPublicTimelineBodyItem(items[index])) {
      return index;
    }
  }
  return -1;
}

function todoProjectionFromTimelineItem(item: PublicChatTimelineItem): TodoProjection | null {
  const todos = Array.isArray(item.todo_items) ? item.todo_items : [];
  if (!todos.length) {
    return null;
  }
  return todoProjectionFromItems(todos, String(item.active_item_id ?? ""), Boolean(item.completion_ready));
}

function todoProjectionFromItems(todos: PublicTodoItem[], activeItemId: string, completionReady: boolean): TodoProjection {
  const completed = todos.filter((item) => String(item.status ?? "") === "completed").length;
  const active = todos.find((item) => String(item.todo_id ?? "") === activeItemId)
    ?? todos.find((item) => String(item.status ?? "") === "in_progress")
    ?? null;
  const pending = todos.filter((item) => String(item.status ?? "") === "pending").slice(0, 2);
  const visibleTodos = [
    ...(active ? [active] : []),
    ...pending,
  ].filter((item, index, list) =>
    list.findIndex((candidate) => String(candidate.todo_id ?? candidate.content ?? "") === String(item.todo_id ?? item.content ?? "")) === index
  ).slice(0, 4);
  return {
    activeText: active ? `当前：${shortText(active.active_form || active.content, 140)}` : "",
    detail: `${completed}/${todos.length} 已完成`,
    hidden: Math.max(0, todos.length - visibleTodos.length),
    items: visibleTodos.map((item) => ({
      content: shortText(String(item.status ?? "") === "in_progress" ? item.active_form || item.content : item.content, 120),
      id: String(item.todo_id ?? item.content ?? ""),
      status: String(item.status ?? "pending"),
    })),
    title: completionReady ? "处理清单已完成" : "处理清单",
  };
}

function publicTimelineTone(items: PublicChatTimelineItem[]): PublicTimelineActivityTone {
  const state = items.map((item) => String(item.state ?? "").trim().toLowerCase()).reverse().find(Boolean) ?? "";
  if (["error", "failed", "blocked", "missing"].includes(state)) return "soft_error";
  if (["waiting", "queued", "paused"].includes(state)) return "waiting";
  if (["completed", "complete", "done", "ready", "passed", "success"].includes(state)) return "done";
  return "running";
}

function taskProjectionTone(projections: SingleAgentTaskProjection[]): PublicTimelineActivityTone | "" {
  const status = projections.map((projection) => cleanPublicTimelineText(projection.status).toLowerCase()).reverse().find(Boolean) ?? "";
  if (!status) return "";
  if (["failed", "error", "blocked", "missing"].includes(status)) return "soft_error";
  if (["waiting", "waiting_user", "waiting_approval", "queued", "paused"].includes(status)) return "waiting";
  if (["completed", "complete", "done", "success"].includes(status)) return "done";
  if (["stopped", "cancelled", "canceled", "aborted"].includes(status)) return "stopped";
  return "running";
}

function publicText(item: PublicChatTimelineItem) {
  const candidates = isPublicTimelineBodyItem(item) ? [
    publicTimelineBodyText(item),
  ] : [
    item.public_summary,
    item.title,
    item.subject_label,
    item.detail,
    item.observation,
    item.text,
    item.path,
    item.href,
  ];
  for (const candidate of candidates) {
    const text = cleanPublicTimelineText(candidate);
    if (text && !looksLikeRawToolOutput(text)) {
      return text;
    }
  }
  return "";
}

function toolDetailText(item: PublicChatTimelineItem, summary: string) {
  const candidates = [item.observation, item.detail, item.recovery_hint, item.path, item.href];
  for (const candidate of candidates) {
    const text = cleanPublicTimelineText(candidate);
    if (text && text !== summary && !looksLikeRawToolOutput(text)) {
      return shortText(text, 260);
    }
  }
  return "";
}

function toolWindowProjection(item: PublicChatTimelineItem, fallbackDetail: string): ToolWindowProjection | undefined {
  const raw = item.tool_window;
  const rawSections = Array.isArray(raw?.sections) ? raw.sections : [];
  const sections = rawSections
    .map((section) => ({
      label: shortText(cleanPublicTimelineText(section?.label), 36),
      text: shortText(cleanPublicTimelineText(section?.text), 260),
    }))
    .filter((section) => section.label && section.text)
    .slice(0, 4);
  if (!sections.length && fallbackDetail) {
    sections.push({ label: "结果", text: shortText(fallbackDetail, 260) });
  }
  const meta = [
    raw?.tool_label,
    raw?.status,
    raw?.target,
  ].map((value) => shortText(cleanPublicTimelineText(value), 90)).filter(Boolean).slice(0, 3);
  if (!sections.length && !meta.length) {
    return undefined;
  }
  return { meta, sections };
}

function kindOf(item: PublicChatTimelineItem | null | undefined) {
  return String(item?.kind ?? "").trim();
}

function shortText(value: unknown, limit: number) {
  const text = String(value ?? "").trim();
  if (!text) return "";
  return text.length > limit ? `${text.slice(0, Math.max(1, limit - 1))}...` : text;
}

function ActivityLine({
  kind,
  text,
}: {
  kind: "status" | "stopped";
  text: string;
}) {
  return (
    <div className={`public-run-activity__line public-run-activity__line--${kind}`}>
      <p>{text}</p>
    </div>
  );
}

function BodyLine({ text }: { text: string }) {
  return (
    <div className="public-run-activity__body markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>
        {text}
      </ReactMarkdown>
    </div>
  );
}

function ToolWindow({ entry }: { entry: ActivityEntry }) {
  const defaultOpen = !entry.collapsed;
  const [open, setOpen] = useState(defaultOpen);

  useEffect(() => {
    setOpen(defaultOpen);
  }, [entry.id, defaultOpen]);

  return (
    <details
      className="public-run-activity__tool-window"
      onToggle={(event) => setOpen(event.currentTarget.open)}
      open={open}
    >
      <summary>{entry.text}</summary>
      {entry.toolWindow ? (
        <div className="public-run-activity__tool-window-body">
          {entry.toolWindow.meta.length ? (
            <div className="public-run-activity__tool-meta">
              {entry.toolWindow.meta.map((item) => <span key={item}>{item}</span>)}
            </div>
          ) : null}
          {entry.toolWindow.sections.length ? (
            <dl className="public-run-activity__tool-snapshot">
              {entry.toolWindow.sections.map((section) => (
                <div key={`${section.label}:${section.text}`}>
                  <dt>{section.label}</dt>
                  <dd>{section.text}</dd>
                </div>
              ))}
            </dl>
          ) : null}
        </div>
      ) : entry.detail ? (
        <div className="public-run-activity__tool-window-body">
          <p>{entry.detail}</p>
        </div>
      ) : null}
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
