"use client";

import { AlertTriangle, CheckCircle2, FileClock, GitCompare, RefreshCw, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useConfirmDialog } from "@/components/layout/ConfirmDialogProvider";
import {
  listFileChanges,
  openFileChangeDiffInVSCode,
  rollbackFileChange,
  type FileChangeRecord,
} from "@/lib/api";
import { sessionSummaryIsRunning } from "@/lib/sessionTaskPresentation";
import { useAppStore } from "@/lib/store";

function formatChangeTime(timestamp: number) {
  if (!Number.isFinite(timestamp) || timestamp <= 0) return "无时间";
  const date = new Date(timestamp > 1_000_000_000_000 ? timestamp : timestamp * 1000);
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function displayPath(record: FileChangeRecord) {
  const logical = String(record.logical_path || "").replace(/\\/g, "/").trim();
  if (logical) return logical;
  return String(record.absolute_path || record.record_id || "").replace(/\\/g, "/");
}

function changeStatusLabel(record: FileChangeRecord) {
  if (record.status === "rolled_back") return "已回滚";
  if (!record.after_exists) return "已删除";
  if (!record.before_exists) return "新增";
  return "已修改";
}

function changeStatusIcon(record: FileChangeRecord) {
  if (record.status === "rolled_back") return <CheckCircle2 size={14} />;
  return <FileClock size={14} />;
}

export function FileChangesPanel() {
  const confirm = useConfirmDialog();
  const { activeStreamSessionIds, currentSessionId, sessions } = useAppStore();
  const [records, setRecords] = useState<FileChangeRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [actionLoading, setActionLoading] = useState("");
  const currentSession = useMemo(
    () => sessions.find((session) => session.id === currentSessionId) ?? null,
    [currentSessionId, sessions],
  );
  const sessionActive = Boolean(
    currentSessionId
    && (activeStreamSessionIds.includes(currentSessionId) || (currentSession && sessionSummaryIsRunning(currentSession))),
  );
  const activeRecords = records.filter((record) => record.status !== "rolled_back");
  const headline = currentSessionId
    ? activeRecords.length
      ? `${activeRecords.length} 个待确认`
      : records.length
        ? `${records.length} 条记录`
        : "暂无变更"
    : "未选择会话";

  const refresh = useCallback(async () => {
    if (!currentSessionId) {
      setRecords([]);
      setError("");
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const payload = await listFileChanges({ sessionId: currentSessionId, limit: 40 });
      const nextRecords = Array.isArray(payload.records) ? payload.records : [];
      setRecords(nextRecords);
      setError("");
    } catch (refreshError) {
      setError(refreshError instanceof Error ? refreshError.message : "文件变更读取失败。");
    } finally {
      setLoading(false);
    }
  }, [currentSessionId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!currentSessionId || !sessionActive) return;
    const timer = window.setInterval(() => {
      void refresh();
    }, 5000);
    return () => window.clearInterval(timer);
  }, [currentSessionId, refresh, sessionActive]);

  async function handleOpenDiff(record: FileChangeRecord) {
    if (!currentSessionId) {
      setError("选择会话后才能打开 VS Code Diff。");
      return;
    }
    setActionLoading(`diff:${record.record_id}`);
    try {
      await openFileChangeDiffInVSCode(currentSessionId, record.record_id);
      setError("");
    } catch (openError) {
      setError(openError instanceof Error ? openError.message : "无法在 VS Code 打开 Diff。");
    } finally {
      setActionLoading("");
    }
  }

  async function handleRollback(record: FileChangeRecord) {
    const approved = await confirm({
      title: "回滚文件变更",
      body: `将恢复 ${displayPath(record)} 到本次修改之前的内容。`,
      confirmLabel: "回滚",
      tone: "warning",
    });
    if (!approved) return;
    setActionLoading(`rollback:${record.record_id}`);
    try {
      const payload = await rollbackFileChange(record.record_id);
      setRecords((current) => current.map((item) => item.record_id === record.record_id ? payload.record : item));
      setError("");
    } catch (rollbackError) {
      setError(rollbackError instanceof Error ? rollbackError.message : "回滚失败。");
    } finally {
      setActionLoading("");
    }
  }

  return (
    <section className="file-changes-panel" aria-label="文件变更">
      <header className="file-changes-panel__head">
        <div>
          <span>变更</span>
          <strong>{headline}</strong>
        </div>
        <button aria-label="刷新文件变更" disabled={loading || !currentSessionId} onClick={() => void refresh()} type="button">
          <RefreshCw className={loading ? "spin" : ""} size={15} />
        </button>
      </header>

      {error ? (
        <div className="file-changes-panel__notice">
          <AlertTriangle size={15} />
          <span>{error}</span>
        </div>
      ) : null}

      <div className="file-changes-list">
        {records.length ? records.map((record) => {
          const path = displayPath(record);
          const rolledBack = record.status === "rolled_back";
          return (
            <article
              className={[
                "file-change-row",
                rolledBack ? "file-change-row--rolled-back" : "",
              ].filter(Boolean).join(" ")}
              key={record.record_id}
            >
              <span className="file-change-row__icon">{changeStatusIcon(record)}</span>
              <div className="file-change-row__body">
                <strong title={path}>{path}</strong>
                <small>{changeStatusLabel(record)} · {formatChangeTime(Number(record.created_at || 0))}</small>
              </div>
              <div className="file-change-row__actions">
                <button
                  aria-label={`打开 ${path} 的 diff`}
                  disabled={Boolean(actionLoading)}
                  onClick={() => void handleOpenDiff(record)}
                  title="打开 Diff"
                  type="button"
                >
                  <GitCompare size={14} />
                </button>
                <button
                  aria-label={`回滚 ${path}`}
                  disabled={rolledBack || Boolean(actionLoading)}
                  onClick={() => void handleRollback(record)}
                  title={rolledBack ? "已回滚" : "回滚"}
                  type="button"
                >
                  <RotateCcw size={14} />
                </button>
              </div>
            </article>
          );
        }) : (
          <div className="file-changes-empty">
            <FileClock size={17} />
            <strong>{loading ? "同步中" : "暂无变更"}</strong>
            <span>{currentSessionId ? "当前会话还没有文件变更记录。" : "选择会话后显示文件变更。"}</span>
          </div>
        )}
      </div>
    </section>
  );
}
