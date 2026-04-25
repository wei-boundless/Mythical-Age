"use client";

import { MessageSquare, Plus, Trash2 } from "lucide-react";

import { SoulPortrait } from "@/components/soul/SoulPortrait";
import { SoulSwitcher } from "@/components/soul/SoulSwitcher";
import { useAppStore } from "@/lib/store";

export function Sidebar() {
  const {
    sessions,
    currentSessionId,
    selectSession,
    createNewSession,
    removeSession,
    soulOptions,
    activeSoulKey,
    switchSoul
  } = useAppStore();
  const activeSoul =
    soulOptions.find((soul) => soul.key === activeSoulKey) ?? soulOptions[0] ?? null;

  return (
    <aside className="panel flex h-full flex-col gap-4 rounded-[34px] p-4">
      <section className="archive-block archive-block--ornate p-4">
        {activeSoul ? (
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

            <div className="style-panel__visual">
              <SoulPortrait soul={activeSoul} compact />
            </div>

            <p className="style-panel__intro">{activeSoul.intro}</p>
          </div>
        ) : null}
      </section>

      <section className="archive-block archive-block--ornate flex min-h-0 flex-1 flex-col p-4">
        <div className="archive-section-head mb-4 flex items-center justify-between gap-3">
          <div className="archive-section-head__copy">
            <p className="archive-section-head__eyebrow">Sessions</p>
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
                className="w-full text-left"
                onClick={() => void selectSession(session.id)}
                type="button"
              >
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
              </button>
              <button
                className="mt-3 flex items-center gap-2 text-xs text-[var(--color-danger)]"
                onClick={() => void removeSession(session.id)}
                type="button"
              >
                <Trash2 size={14} />
                删除
              </button>
            </div>
          ))}
        </div>
      </section>
    </aside>
  );
}
