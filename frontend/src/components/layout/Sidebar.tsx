"use client";

import {
  MessageSquare,
  Plus,
  Trash2,
  Workflow,
} from "lucide-react";

import { useAppStore } from "@/lib/store";
import type { WorkspaceView } from "@/lib/store/types";

const primaryNavItems: Array<{
  icon: typeof MessageSquare;
  label: string;
  description: string;
  view: WorkspaceView;
}> = [
  { icon: MessageSquare, label: "主会话", description: "对话与任务入口", view: "chat" },
  { icon: Workflow, label: "图任务层", description: "任务图编辑与运行", view: "task-system" },
];

export function Sidebar() {
  const {
    sessions,
    currentSessionId,
    selectSession,
    createNewSession,
    removeSession,
    activeWorkspaceView,
    setWorkspaceView,
  } = useAppStore();

  return (
    <aside className="practical-sidebar" aria-label="工作区导航">
      <div className="practical-sidebar__brand">
        <strong>Marvis</strong>
        <span>Agent Workspace</span>
      </div>

      <nav className="practical-sidebar__nav" aria-label="主导航">
        <div className="practical-sidebar__nav-list">
          {primaryNavItems.map((item) => {
            const Icon = item.icon;
            const active = activeWorkspaceView === item.view;
            return (
              <button
                aria-pressed={active}
                className={active ? "practical-sidebar__nav-item practical-sidebar__nav-item--active" : "practical-sidebar__nav-item"}
                key={item.view}
                onClick={() => setWorkspaceView(item.view)}
                type="button"
              >
                <Icon size={16} />
                <span>
                  <strong>{item.label}</strong>
                  <small>{item.description}</small>
                </span>
              </button>
            );
          })}
        </div>
      </nav>

      <section className="practical-sidebar__sessions">
        <div className="practical-sidebar__section-head">
          <div>
            <span>本地知识库</span>
            <strong>会话</strong>
          </div>
          <button className="practical-icon-button" aria-label="新会话" onClick={() => void createNewSession()} type="button">
            <Plus size={18} />
          </button>
        </div>

        <div className="practical-session-list">
          {sessions.map((session) => (
            <div
              className={session.id === currentSessionId ? "practical-session practical-session--active" : "practical-session"}
              key={session.id}
            >
              <button
                className="practical-session__main"
                onClick={() => void selectSession(session.id)}
                type="button"
              >
                <span>{session.title}</span>
                <small>{session.message_count} 条消息</small>
              </button>
              <button
                className="practical-session__delete"
                aria-label={`删除 ${session.title}`}
                onClick={() => void removeSession(session.id)}
                type="button"
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>
      </section>

      <div className="practical-sidebar__account">
        <span>Yolo</span>
      </div>
    </aside>
  );
}
