"use client";

import { Database, Gauge, Plus, Sparkles } from "lucide-react";

import { useAppStore } from "@/lib/store";

export function Navbar() {
  const {
    createNewSession,
    ragMode,
    toggleRagMode,
    tokenStats
  } = useAppStore();
  const remainingPercent = tokenStats
    ? Math.max(0, Math.min(100, Math.round(tokenStats.history_remaining_ratio * 100)))
    : null;
  const pressureLevel = tokenStats?.history_pressure_level ?? "normal";

  return (
    <header className="panel flex flex-col gap-5 rounded-[34px] px-5 py-5">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div className="flex min-w-0 items-start gap-4">
          <div className="brand-mark">
            <Sparkles size={20} />
          </div>
          <div className="min-w-0">
            <p className="section-kicker">Mythic Local Agent Workbench</p>
            <h1 className="mt-2 text-2xl font-semibold tracking-[-0.05em] text-[var(--color-text)]">
              河图工作台
            </h1>
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-end gap-2">
          <button
            className="action-button action-button--muted"
            onClick={() => void createNewSession()}
            type="button"
          >
            <Plus size={16} />
            新会话
          </button>
          <button
            className={`action-button ${
              ragMode ? "action-button--primary" : "action-button--muted"
            }`}
            onClick={() => void toggleRagMode()}
            type="button"
          >
            <Database size={16} />
            {ragMode ? "检索模式 开" : "检索模式 关"}
          </button>
          {tokenStats ? (
            <div
              className={`status-pill status-pill--context status-pill--${pressureLevel}`}
              title={`当前历史上下文 ${tokenStats.history_tokens}/${tokenStats.history_budget_tokens} tokens，余量 ${remainingPercent}%`}
            >
              <Gauge size={16} />
              {`上下文余量 ${remainingPercent}%`}
            </div>
          ) : null}
        </div>
      </div>
    </header>
  );
}
