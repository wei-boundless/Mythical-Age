"use client";

import { Monitor, Plug, RefreshCw } from "lucide-react";

import type { SessionProjectBinding } from "@/lib/api";

import { useVSCodeConnectionStatus } from "./useVSCodeConnectionStatus";

type VSCodeStatusPanelProps = {
  sessionId: string | null | undefined;
  projectBinding?: SessionProjectBinding | null;
};

export function VSCodeStatusPanel({ sessionId, projectBinding }: VSCodeStatusPanelProps) {
  const { status, loading, opening, error, refresh, open } = useVSCodeConnectionStatus(sessionId);
  if (!sessionId) {
    return null;
  }
  const boundRoot = String(projectBinding?.workspace_root || status?.workspace_root || "").trim();
  const activeFile = String(status?.active_file?.path || "").trim();
  const openTabs = Array.isArray(status?.open_tabs) ? status.open_tabs : [];
  const openTabCount = Number(status?.limits?.open_tabs_count || openTabs.length || 0);
  const connected = Boolean(status?.connected && !status?.stale);
  const stale = Boolean(status?.connected && status?.stale);
  const reusedProjectConnection = Boolean(status?.reused_project_connection);
  const stateClass = connected ? "connected" : stale ? "stale" : "disconnected";
  const stateLabel = connected ? (reusedProjectConnection ? "项目已连接" : "已连接") : stale ? "过期" : "未连接";
  const ageLabel = status?.age_seconds ? formatAge(status.age_seconds) : "";
  const needsReconnect = stale || !connected;
  const title = [
    `VS Code ${stateLabel}`,
    boundRoot ? `项目：${boundRoot}` : "当前会话未绑定项目",
    reusedProjectConnection ? "当前会话复用同项目 VS Code 连接" : "",
    ageLabel ? `上次同步：${ageLabel}前` : "",
    activeFile ? `当前文件：${activeFile}` : "",
    openTabCount ? `打开标签页：${openTabCount}` : "",
    ...openTabs.slice(0, 12).map((tab) => `- ${String(tab.label || fileName(String(tab.path || ""))).trim()}: ${String(tab.path || "").trim()}`),
    openTabs.length > 12 ? `- 另有 ${openTabs.length - 12} 个标签页` : "",
    error ? `错误：${error}` : "",
  ].filter(Boolean).join("\n");
  const openLabel = stale ? "重新连接 VS Code" : connected ? "打开 VS Code" : "连接 VS Code";
  const actionLabel = opening ? "连接中" : stale ? "重连" : connected ? "" : "连接";

  return (
    <div className={`vscode-status vscode-status--${stateClass}`} title={title}>
      <span className="vscode-status__state">
        <Plug size={13} />
        <span>VS Code</span>
        <strong>{stateLabel}</strong>
      </span>
      {activeFile ? (
        <span className="vscode-status__file">
          {fileName(activeFile)}
          {status?.active_file?.dirty ? "*" : ""}
        </span>
      ) : boundRoot ? (
        <span className="vscode-status__file">{folderName(boundRoot)}</span>
      ) : (
        <span className="vscode-status__file">未绑定项目</span>
      )}
      {openTabCount ? (
        <span className="vscode-status__tabs">{openTabCount} 标签</span>
      ) : null}
      <button
        aria-label={boundRoot ? openLabel : "当前会话未绑定项目"}
        className={needsReconnect ? "vscode-status__open vscode-status__open--attention" : "vscode-status__open"}
        disabled={!boundRoot || opening}
        onClick={() => void open()}
        title={boundRoot ? openLabel : "先绑定项目"}
        type="button"
      >
        <Monitor size={13} />
        {actionLabel ? <span>{actionLabel}</span> : null}
      </button>
      <button
        aria-label="刷新 VS Code 连接状态"
        disabled={loading}
        onClick={() => void refresh()}
        title="刷新 VS Code 状态"
        type="button"
      >
        <RefreshCw size={13} />
      </button>
    </div>
  );
}

function fileName(value: string) {
  const normalized = value.replace(/\\/g, "/");
  return normalized.split("/").filter(Boolean).pop() || value;
}

function folderName(value: string) {
  const normalized = value.replace(/\\/g, "/");
  return normalized.split("/").filter(Boolean).pop() || value;
}

function formatAge(seconds: number) {
  const safeSeconds = Math.max(0, Math.floor(seconds));
  if (safeSeconds < 60) return `${safeSeconds} 秒`;
  const minutes = Math.floor(safeSeconds / 60);
  if (minutes < 60) return `${minutes} 分钟`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时`;
  return `${Math.floor(hours / 24)} 天`;
}
