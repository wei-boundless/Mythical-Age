"use client";

import { Gauge, Plus, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";

import { useAppStore } from "@/lib/store";

export function Navbar() {
  const {
    activeWorkspaceView,
    createNewSession,
    tokenStats
  } = useAppStore();
  const [mounted, setMounted] = useState(false);
  const isWorkbench = activeWorkspaceView === "task-system" || activeWorkspaceView === "orchestration";
  const workspaceLabel = mounted && isWorkbench ? "工作台" : "智能体";
  const remainingPercent = tokenStats
    ? Math.max(0, Math.min(100, Math.round(tokenStats.history_remaining_ratio * 100)))
    : null;
  const pressureLevel = tokenStats?.history_pressure_level ?? "normal";
  const contextTitle = tokenStats
    ? `有效历史上下文 ${tokenStats.history_tokens}/${tokenStats.history_budget_tokens} tokens，余量 ${remainingPercent}%`
      + (tokenStats.history_did_compact ? `；已自动压缩，原始历史 ${tokenStats.raw_history_tokens} tokens` : "")
    : "";

  useEffect(() => {
    setMounted(true);
  }, []);

  return (
    <header className={`panel navbar-shell ${isWorkbench ? "navbar-shell--work" : ""}`}>
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div className="navbar-brand flex min-w-0 items-start gap-4">
          <div className="brand-mark navbar-brand-mark">
            <Sparkles size={20} />
          </div>
          <div className="navbar-brand-copy min-w-0">
            <p className="mythic-brand-eyebrow">The Mythical Agent</p>
            <h1 className="mythic-brand-title mt-2">
              <span className="mythic-brand-title__cn">洪荒时代</span>
              <span className="mythic-brand-title__divider">—</span>
              <span className="mythic-brand-title__cn mythic-brand-title__cn--accent">
                {workspaceLabel}
              </span>
            </h1>
          </div>
        </div>

        <div className="navbar-controls flex flex-wrap items-center justify-end gap-2">
          <button
            className="action-button action-button--muted navbar-action-button"
            onClick={() => void createNewSession()}
            type="button"
          >
            <Plus size={16} />
            新会话
          </button>
          {tokenStats ? (
            <div
              className={`status-pill status-pill--context navbar-status-pill status-pill--${pressureLevel}`}
              title={contextTitle}
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
