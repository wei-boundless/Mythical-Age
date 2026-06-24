"use client";

import { CheckCircle2, ChevronDown, Circle, CircleDashed, ListChecks, PlayCircle, TriangleAlert } from "lucide-react";
import React, { useMemo, useState } from "react";

import type { PublicTodoItem } from "@/lib/api";
import type { ProjectionRenderBlock, TodoPlanProjectionBlock } from "@/lib/projection/chronological";
import type { Message } from "@/lib/store/types";

type SessionTodoPanelProps = {
  active?: boolean;
  messages: Message[];
};

type TodoStatusTone = "active" | "blocked" | "done" | "pending";

type TodoPanelSnapshot = {
  activeItem: PublicTodoItem | null;
  block: TodoPlanProjectionBlock | null;
  completed: number;
  items: PublicTodoItem[];
  percent: number;
  tone: TodoStatusTone;
  total: number;
};

export function SessionTodoPanel({ active = false, messages }: SessionTodoPanelProps) {
  const [collapsed, setCollapsed] = useState(false);
  const snapshot = useMemo(() => latestTodoSnapshotFromMessages(messages), [messages]);
  const hasItems = snapshot.total > 0;

  if (!active || !hasItems) {
    return null;
  }

  const activeText = cleanText(snapshot.activeItem?.active_form || snapshot.activeItem?.content);
  const headline = hasItems
    ? activeText || (snapshot.tone === "done" ? "全部步骤已完成" : "等待下一步")
    : "任务清单同步中";
  const progressText = hasItems ? `${snapshot.completed}/${snapshot.total}` : "0/0";

  return (
    <aside className="session-todo-panel-shell" aria-label="当前任务清单">
      <section
        className={`session-todo-panel session-todo-panel--${snapshot.tone}${collapsed ? " session-todo-panel--collapsed" : ""}`}
        data-completion-ready={snapshot.block?.completionReady === true ? "true" : "false"}
      >
        <button
          aria-expanded={!collapsed}
          className="session-todo-panel__header"
          onClick={() => setCollapsed((value) => !value)}
          type="button"
        >
          <span className="session-todo-panel__icon" aria-hidden="true">
            <ListChecks size={16} />
          </span>
          <span className="session-todo-panel__title">
            <strong>任务清单</strong>
            <span>{headline}</span>
          </span>
          <span className="session-todo-panel__progress-text">{progressText}</span>
          <ChevronDown className="session-todo-panel__chevron" size={16} aria-hidden="true" />
        </button>

        <div className="session-todo-panel__progress" aria-hidden="true">
          <span style={{ width: `${snapshot.percent}%` }} />
        </div>

        {!collapsed ? (
          <div className="session-todo-panel__body">
            <ol className="session-todo-panel__list">
              {snapshot.items.map((item, index) => (
                <TodoPanelItem
                  activeItemId={snapshot.block?.activeItemId ?? ""}
                  item={item}
                  itemIndex={index}
                  key={cleanText(item.todo_id) || `${snapshot.block?.id || "todo"}:${index}`}
                />
              ))}
            </ol>
          </div>
        ) : null}
      </section>
    </aside>
  );
}

function TodoPanelItem({
  activeItemId,
  item,
  itemIndex,
}: {
  activeItemId: string;
  item: PublicTodoItem;
  itemIndex: number;
}) {
  const status = normalizedTodoStatus(item);
  const active = cleanText(item.todo_id) === cleanText(activeItemId) || status === "in_progress";
  const tone = todoStatusTone(status, active);
  const label = active ? cleanText(item.active_form || item.content) : cleanText(item.content);
  const note = cleanText(item.notes);

  return (
    <li className={`session-todo-panel__item session-todo-panel__item--${tone}`} data-todo-status={status || "pending"}>
      <span className="session-todo-panel__item-index">{itemIndex + 1}</span>
      <span className="session-todo-panel__item-icon" aria-hidden="true">
        {todoStatusIcon(tone)}
      </span>
      <span className="session-todo-panel__item-main">
        <span className="session-todo-panel__item-title">{label}</span>
        {note ? <span className="session-todo-panel__item-note">{note}</span> : null}
      </span>
      <span className="session-todo-panel__item-status">{todoStatusLabel(status, active)}</span>
    </li>
  );
}

function latestTodoSnapshotFromMessages(messages: Message[]): TodoPanelSnapshot {
  const block = latestTodoPlanFromMessages(messages);
  const items: PublicTodoItem[] = (block?.items ?? []).filter((item: PublicTodoItem) => cleanText(item.content));
  const completed = items.filter((item) => normalizedTodoStatus(item) === "completed").length;
  const activeItem = block
    ? items.find((item) => cleanText(item.todo_id) === cleanText(block.activeItemId)) ?? items.find((item) => normalizedTodoStatus(item) === "in_progress") ?? null
    : null;
  const blocked = items.some((item) => normalizedTodoStatus(item) === "blocked");
  const total = items.length;
  const percent = total ? Math.round((completed / total) * 100) : 0;
  return {
    activeItem,
    block,
    completed,
    items,
    percent,
    tone: blocked ? "blocked" : activeItem ? "active" : total && completed === total ? "done" : "pending",
    total,
  };
}

function latestTodoPlanFromMessages(messages: Message[]): TodoPlanProjectionBlock | null {
  let latestBlock: TodoPlanProjectionBlock | null = null;
  let latestMessageIndex = -1;
  messages.forEach((message, messageIndex) => {
    const blocks = todoPlanBlocks(message.projectionView?.blocks ?? []);
    for (const block of blocks) {
      if (!block.items?.some((item) => cleanText(item.content))) {
        continue;
      }
      if (
        !latestBlock
        || messageIndex > latestMessageIndex
        || (messageIndex === latestMessageIndex && block.offset >= latestBlock.offset)
      ) {
        latestBlock = block;
        latestMessageIndex = messageIndex;
      }
    }
  });
  return latestBlock;
}

function todoPlanBlocks(blocks: ProjectionRenderBlock[]): TodoPlanProjectionBlock[] {
  const result: TodoPlanProjectionBlock[] = [];
  for (const block of blocks) {
    if (block.kind === "todo_plan") {
      result.push(block);
      continue;
    }
    if (block.kind === "activity_archive") {
      result.push(...todoPlanBlocks(block.blocks));
    }
  }
  return result;
}

function normalizedTodoStatus(item: PublicTodoItem) {
  return cleanText(item.status).toLowerCase();
}

function todoStatusTone(status: string, active: boolean): TodoStatusTone {
  if (status === "completed") return "done";
  if (status === "blocked") return "blocked";
  if (active || status === "in_progress") return "active";
  return "pending";
}

function todoStatusIcon(tone: TodoStatusTone) {
  if (tone === "done") return <CheckCircle2 size={14} />;
  if (tone === "active") return <PlayCircle size={14} />;
  if (tone === "blocked") return <TriangleAlert size={14} />;
  if (tone === "pending") return <CircleDashed size={14} />;
  return <Circle size={14} />;
}

function todoStatusLabel(status: string, active: boolean) {
  if (status === "completed") return "完成";
  if (status === "blocked") return "阻塞";
  if (active || status === "in_progress") return "进行中";
  return "待处理";
}

function cleanText(value: unknown) {
  return String(value ?? "").trim();
}
