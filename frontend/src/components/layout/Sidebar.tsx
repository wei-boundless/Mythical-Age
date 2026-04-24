"use client";

import { MessageSquare, Plus, Trash2 } from "lucide-react";

import { SoulPortrait } from "@/components/soul/SoulPortrait";
import { SoulSwitcher } from "@/components/soul/SoulSwitcher";
import { useAppStore } from "@/lib/store";

function preview(text: string) {
  return text.length > 72 ? `${text.slice(0, 72)}...` : text;
}

export function Sidebar() {
  const {
    sessions,
    currentSessionId,
    selectSession,
    createNewSession,
    removeSession,
    messages,
    soulOptions,
    activeSoulKey,
    switchSoul
  } = useAppStore();
  const activeSoul =
    soulOptions.find((soul) => soul.key === activeSoulKey) ?? soulOptions[0] ?? null;

  return (
    <aside className="panel flex h-full flex-col gap-4 rounded-[34px] p-4">
      <section className="archive-block p-4">
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

      <section className="archive-block flex min-h-0 flex-1 flex-col p-4">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <p className="section-kicker">Sessions</p>
            <h2 className="text-xl font-semibold tracking-[-0.04em] text-[var(--color-text)]">
              会话与消息轨迹
            </h2>
          </div>
          <button className="icon-well" onClick={() => void createNewSession()} type="button">
            <Plus size={18} />
          </button>
        </div>

        <div className="space-y-2 overflow-y-auto pr-1">
          {sessions.map((session) => (
            <div
              className={`session-card ${session.id === currentSessionId ? "session-card--active" : ""}`}
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

        <div className="mt-4 flex min-h-0 flex-1 flex-col rounded-[24px] border border-[var(--color-border)] bg-[var(--color-panel-strong)] p-3">
          <p className="section-kicker">Raw Messages</p>
          <div className="mt-3 space-y-3 overflow-y-auto pr-1">
            {messages.map((message) => (
              <div
                className="rounded-[22px] border border-[var(--color-border)] bg-[var(--color-panel-soft)] px-3 py-3"
                key={message.id}
              >
                <div className="mb-1 flex items-center justify-between text-[11px] uppercase tracking-[0.24em] text-[var(--color-text-soft)]">
                  <span>
                    {message.role === "assistant" ? activeSoul?.name ?? "助手" : "你"}
                  </span>
                  <span>{message.toolCalls.length} tools</span>
                </div>
                <p className="text-sm leading-6 text-[var(--color-text-soft)]">
                  {preview(message.content)}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>
    </aside>
  );
}
