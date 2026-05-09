"use client";

import {
  BrainCircuit,
  HeartPulse,
  MessageSquare,
  Network,
  Plus,
  PlugZap,
  Settings2,
  Sparkles,
  Trash2,
  Wrench,
  Workflow,
} from "lucide-react";

import { SoulPortrait } from "@/components/soul/SoulPortrait";
import { SoulSwitcher } from "@/components/soul/SoulSwitcher";
import { useAppStore } from "@/lib/store";
import type { WorkspaceView } from "@/lib/store/types";

const primaryNavItems: Array<{
  icon: typeof MessageSquare;
  label: string;
  view: WorkspaceView;
}> = [
  { icon: MessageSquare, label: "会话", view: "chat" },
  { icon: Workflow, label: "任务", view: "task-system" },
  { icon: Network, label: "编排", view: "orchestration" },
  { icon: BrainCircuit, label: "记忆", view: "memory" },
  { icon: HeartPulse, label: "健康", view: "health-system" },
  { icon: Wrench, label: "能力", view: "capability-system" },
  { icon: PlugZap, label: "MCP", view: "mcp-system" },
  { icon: Sparkles, label: "灵魂", view: "playground" },
  { icon: Settings2, label: "配置", view: "system-config" },
];

type SidebarProps = {
  compact?: boolean;
};

export function Sidebar({ compact = false }: SidebarProps) {
  const {
    sessions,
    currentSessionId,
    selectSession,
    createNewSession,
    removeSession,
    activeWorkspaceView,
    setWorkspaceView,
    soulOptions,
    activeSoulKey,
    switchSoul
  } = useAppStore();
  const activeSoul =
    soulOptions.find((soul) => soul.key === activeSoulKey) ?? soulOptions[0] ?? null;

  return (
    <aside className={`panel workspace-sidebar ${compact ? "workspace-sidebar--compact" : ""}`}>
      <nav className="archive-block archive-block--ornate workspace-sidebar__nav" aria-label="主导航">
        <div className="workspace-sidebar__nav-list">
          {primaryNavItems.map((item) => {
            const Icon = item.icon;
            const active = activeWorkspaceView === item.view;
            return (
              <button
                aria-label={item.label}
                aria-pressed={active}
                className={`workspace-sidebar__nav-item ${active ? "workspace-sidebar__nav-item--active" : ""}`}
                key={item.view}
                onClick={() => setWorkspaceView(item.view)}
                title={item.label}
                type="button"
              >
                <Icon size={16} />
                {!compact ? <span>{item.label}</span> : null}
              </button>
            );
          })}
        </div>
      </nav>

      {activeSoul ? (
        <section className="archive-block archive-block--ornate workspace-sidebar__soul">
          <div className="style-panel">
            <div className="style-panel__head">
              <div className="style-panel__meta">
                <p className="style-panel__eyebrow">当前灵魂</p>
                <h2 className="style-panel__name">{activeSoul.name}</h2>
              </div>
              <SoulSwitcher
                activeSoulKey={activeSoulKey}
                onSwitch={switchSoul}
                souls={soulOptions}
              />
            </div>

            {!compact ? (
              <>
                <div className="style-panel__visual">
                  <SoulPortrait soul={activeSoul} compact />
                </div>

                <p className="style-panel__intro">{activeSoul.intro}</p>
              </>
            ) : null}
          </div>
        </section>
      ) : null}

      <section className="archive-block archive-block--ornate workspace-sidebar__sessions">
        <div className="archive-section-head mb-4 flex items-center justify-between gap-3">
          <div className="archive-section-head__copy">
            <p className="archive-section-head__eyebrow">会话</p>
            <h2 className="archive-section-head__title">
              会话与消息轨迹
            </h2>
          </div>
          <button className="icon-well archive-icon-button" onClick={() => void createNewSession()} type="button">
            <Plus size={18} />
          </button>
        </div>

        <div className="space-y-2 overflow-y-auto pr-1">
          {sessions.map((session) => (
            <div
              className={`session-card archive-session-card ${session.id === currentSessionId ? "session-card--active" : ""}`}
              key={session.id}
            >
              <button
                className="workspace-sidebar__session-button w-full text-left"
                onClick={() => void selectSession(session.id)}
                title={compact ? `${session.title} / ${session.message_count} 条消息` : undefined}
                type="button"
              >
                {compact ? (
                  <span className="workspace-sidebar__session-dot" aria-hidden="true">
                    <MessageSquare size={15} />
                  </span>
                ) : (
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-base font-medium text-[var(--color-text)]">
                        {session.title}
                      </p>
                      <p className="mt-1 text-xs text-[var(--color-text-soft)]">
                        {session.message_count} 条消息
                      </p>
                    </div>
                    <MessageSquare className="mt-1 text-[var(--color-text-soft)]" size={16} />
                  </div>
                )}
              </button>
              {!compact ? (
                <button
                  className="mt-3 flex items-center gap-2 text-xs text-[var(--color-danger)]"
                  onClick={() => void removeSession(session.id)}
                  type="button"
                >
                  <Trash2 size={14} />
                  删除
                </button>
              ) : null}
            </div>
          ))}
        </div>
      </section>
    </aside>
  );
}
