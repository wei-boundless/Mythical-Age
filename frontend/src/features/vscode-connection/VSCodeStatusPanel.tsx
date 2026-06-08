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
  const connected = Boolean(status?.connected && !status?.stale);
  const stale = Boolean(status?.connected && status?.stale);
  const reusedProjectConnection = Boolean(status?.reused_project_connection);
  const stateClass = connected ? "connected" : stale ? "stale" : "disconnected";
  const stateLabel = connected ? (reusedProjectConnection ? "项目已连接" : "已连接") : stale ? "过期" : "未连接";
  const title = [
    `VS Code ${stateLabel}`,
    boundRoot ? `项目：${boundRoot}` : "当前会话未绑定项目",
    reusedProjectConnection ? "当前会话复用同项目 VS Code 连接" : "",
    activeFile ? `当前文件：${activeFile}` : "",
    error ? `错误：${error}` : "",
  ].filter(Boolean).join("\n");

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
      <button
        aria-label="打开当前会话绑定项目的 VS Code 窗口"
        disabled={!boundRoot || opening}
        onClick={() => void open()}
        title={boundRoot ? "打开 VS Code" : "先绑定项目"}
        type="button"
      >
        <Monitor size={13} />
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
