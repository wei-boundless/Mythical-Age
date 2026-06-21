"use client";

import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, ExternalLink, FileClock, FilePenLine, GitCompare, History, ListTree, PackageOpen, RefreshCw, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useConfirmDialog } from "@/components/layout/ConfirmDialogProvider";
import {
  openFileChangeDiffInVSCode,
  rollbackFileChange,
  type FileChangeRecord,
} from "@/lib/api";
import { useAppStoreActions, useAppStoreSelector } from "@/lib/store";
import { shallowEqual } from "@/lib/store/hooks";
import {
  collectCurrentConversationTaskRunIds,
  partitionFileChangeRecords,
  textValue,
} from "./fileChangesPanelModel";

const INITIAL_REFRESH_DELAY_MS = 1200;
const FILE_CHANGE_REFRESH_LIMIT = 200;
const EMPTY_FILE_CHANGE_RECORDS: FileChangeRecord[] = [];

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

function compactFileName(path: string) {
  const normalized = path.replace(/\\/g, "/");
  const parts = normalized.split("/").filter(Boolean);
  return parts[parts.length - 1] || path || "文件";
}

function compactFolder(path: string) {
  const normalized = path.replace(/\\/g, "/");
  const parts = normalized.split("/").filter(Boolean);
  if (parts.length <= 1) return "项目根目录";
  return parts.slice(0, -1).join("/");
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

export function FileChangesPanel({ embedded = false }: { embedded?: boolean } = {}) {
  const confirm = useConfirmDialog();
  const {
    activeTurnTaskRunId,
    currentSessionId,
    messageTaskRunKey,
    records,
    sessions,
  } = useAppStoreSelector((state) => ({
    activeTurnTaskRunId: String(state.activeTurnSnapshot?.task_run_id || ""),
    currentSessionId: state.currentSessionId,
    messageTaskRunKey: taskRunKeyFromMessages(state.messages),
    records: state.currentSessionId
      ? state.fileChangeRecordsBySession[state.currentSessionId] ?? EMPTY_FILE_CHANGE_RECORDS
      : EMPTY_FILE_CHANGE_RECORDS,
    sessions: state.sessions,
  }), shallowEqual);
  const { applyFileChangeRecord, hydrateFileChangesForSession, openFileChangeDiff } = useAppStoreActions();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [actionLoading, setActionLoading] = useState("");
  const [expandedGroupKey, setExpandedGroupKey] = useState("");
  const currentSession = useMemo(
    () => sessions.find((session) => session.id === currentSessionId) ?? null,
    [currentSessionId, sessions],
  );
  const activeRecords = useMemo(() => records.filter((record) => record.status !== "rolled_back"), [records]);
  const currentConversationTaskRunIds = useMemo(
    () => collectCurrentConversationTaskRunIds({
      activeTurnSnapshot: activeTurnTaskRunId ? { task_run_id: activeTurnTaskRunId } : null,
      currentSession,
      messages: messageTaskRunKey
        ? messageTaskRunKey.split("\n").map((taskRunId) => ({ sourceTaskRunId: taskRunId }))
        : [],
    }),
    [activeTurnTaskRunId, currentSession, messageTaskRunKey],
  );
  const scopedRecords = useMemo(
    () => partitionFileChangeRecords(activeRecords, currentConversationTaskRunIds),
    [activeRecords, currentConversationTaskRunIds],
  );
  const conversationRecords = scopedRecords.conversationRecords;
  const otherTaskRecords = scopedRecords.otherTaskRecords;
  const changeGroups = useMemo(() => groupFileChanges(conversationRecords, "conversation"), [conversationRecords]);
  const modifiedGroups = changeGroups.filter((group) => group.kind === "modified");
  const artifactGroups = changeGroups.filter((group) => group.kind === "artifact");
  const otherTaskBuckets = useMemo(() => groupTaskFileChanges(otherTaskRecords), [otherTaskRecords]);
  const headline = currentSessionId
    ? conversationRecords.length
      ? `当前 ${conversationRecords.length} 条 · ${changeGroups.length} 个文件${otherTaskRecords.length ? ` · 其它 ${otherTaskRecords.length} 条` : ""}`
      : otherTaskRecords.length
        ? `当前暂无 · 其它 ${otherTaskRecords.length} 条`
        : activeRecords.length
          ? `${activeRecords.length} 条记录`
          : records.length
            ? `${records.length} 条记录`
            : "暂无变更"
    : "未选择会话";

  const refresh = useCallback(async (options: { force?: boolean } = {}) => {
    if (!currentSessionId) {
      setError("");
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      await hydrateFileChangesForSession(currentSessionId, {
        force: Boolean(options.force),
        limit: FILE_CHANGE_REFRESH_LIMIT,
      });
      setError("");
    } catch (refreshError) {
      setError(refreshError instanceof Error ? refreshError.message : "文件变更读取失败。");
    } finally {
      setLoading(false);
    }
  }, [currentSessionId, hydrateFileChangesForSession]);

  useEffect(() => {
    if (!currentSessionId) {
      void refresh();
      return undefined;
    }
    const timer = window.setTimeout(() => {
      void refresh();
    }, INITIAL_REFRESH_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [currentSessionId, refresh]);

  function handleOpenFinalDiff(group: FileChangeGroup) {
    const path = group.path;
    const baseline = groupBaselineRecord(group);
    const final = group.latest;
    openFileChangeDiff({
      record_id: final.record_id,
      baseline_record_id: baseline.record_id,
      mode: "final",
      change_count: group.records.length,
      title: path,
      subtitle: group.records.length > 1
        ? `最终对比 · ${group.records.length} 次修改`
        : `${changeStatusLabel(final)} · ${formatChangeTime(Number(final.created_at || 0))}`,
    });
    setError("");
  }

  function handleOpenSingleDiff(record: FileChangeRecord) {
    const path = displayPath(record);
    openFileChangeDiff({
      record_id: record.record_id,
      baseline_record_id: record.record_id,
      mode: "single",
      change_count: 1,
      title: path,
      subtitle: `单次 Diff · ${changeStatusLabel(record)} · ${formatChangeTime(Number(record.created_at || 0))}`,
    });
    setError("");
  }

  async function handleOpenVSCodeDiff(record: FileChangeRecord) {
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
      applyFileChangeRecord(payload.record);
      setError("");
    } catch (rollbackError) {
      setError(rollbackError instanceof Error ? rollbackError.message : "回滚失败。");
    } finally {
      setActionLoading("");
    }
  }

  function renderChangeGroup(group: FileChangeGroup) {
    const record = group.latest;
    const path = group.path;
    const fileName = compactFileName(path);
    const folder = compactFolder(path);
    const rolledBack = record.status === "rolled_back";
    const historyOpen = expandedGroupKey === group.key;
    const historyRecords = sortedRecordsByTime(group.records, "desc");
    return (
      <div className="file-change-group" key={group.key}>
        <article
          className={[
            "file-change-row",
            `file-change-row--${group.kind}`,
            historyOpen ? "file-change-row--expanded" : "",
            rolledBack ? "file-change-row--rolled-back" : "",
          ].filter(Boolean).join(" ")}
        >
          <button
            className="file-change-row__main"
            onClick={() => handleOpenFinalDiff(group)}
            title={`打开最终 Diff：${path}`}
            type="button"
          >
            <span className="file-change-row__icon">{changeStatusIcon(record)}</span>
            <span className="file-change-row__body">
              <strong title={path}>{fileName}</strong>
              <small>
                <span title={path}>{folder}</span>
                <em>
                  {group.records.length > 1
                    ? `最终对比 · ${group.records.length} 次`
                    : `${changeStatusLabel(record)} · ${formatChangeTime(Number(record.created_at || 0))}`}
                </em>
              </small>
            </span>
          </button>
          <div className="file-change-row__actions">
            <button
              aria-expanded={historyOpen}
              aria-label={`${historyOpen ? "收起" : "展开"} ${path} 的修改详情`}
              disabled={Boolean(actionLoading)}
              onClick={() => setExpandedGroupKey(historyOpen ? "" : group.key)}
              title={historyOpen ? "收起详情" : group.records.length > 1 ? "查看历史" : "查看操作"}
              type="button"
            >
              {historyOpen ? <ChevronDown size={14} /> : group.records.length > 1 ? <ChevronRight size={14} /> : <History size={14} />}
            </button>
          </div>
        </article>
        {historyOpen ? (
          <div className="file-change-history-list" aria-label={`${path} 的修改历史`}>
            <div className="file-change-history-tools">
              <span>最新记录</span>
              <button
                disabled={Boolean(actionLoading)}
                onClick={() => void handleOpenVSCodeDiff(record)}
                title="VS Code 打开最新一次 Diff"
                type="button"
              >
                <ExternalLink size={13} />
                <span>VS Code</span>
              </button>
              <button
                disabled={rolledBack || Boolean(actionLoading)}
                onClick={() => void handleRollback(record)}
                title={rolledBack ? "已回滚" : "回滚最新一次"}
                type="button"
              >
                <RotateCcw size={13} />
                <span>{rolledBack ? "已回滚" : "回滚"}</span>
              </button>
            </div>
            {historyRecords.map((historyRecord, index) => (
              <button
                className="file-change-history-row"
                key={historyRecord.record_id}
                onClick={() => handleOpenSingleDiff(historyRecord)}
                title={`打开单次 Diff：${formatChangeTime(Number(historyRecord.created_at || 0))}`}
                type="button"
              >
                <span className="file-change-history-row__icon"><History size={13} /></span>
                <span className="file-change-history-row__body">
                  <strong>第 {historyRecords.length - index} 次 · {formatChangeTime(Number(historyRecord.created_at || 0))}</strong>
                  <small>{changeStatusLabel(historyRecord)} · {historyRecord.tool_name || historyRecord.operation_id || "文件操作"}</small>
                </span>
                <GitCompare size={13} />
              </button>
            ))}
          </div>
        ) : null}
      </div>
    );
  }

  function renderGroupSection(title: string, groups: FileChangeGroup[], icon: "modified" | "artifact") {
    return (
      <section className="file-change-section" aria-label={title}>
        <header className="file-change-section__head">
          <span>{icon === "artifact" ? <PackageOpen size={14} /> : <FilePenLine size={14} />}{title}</span>
          <strong>{groups.length}</strong>
        </header>
        <div className="file-change-section__list">
          {groups.length ? groups.map((group) => renderChangeGroup(group)) : (
            <div className="file-change-section__empty">{title === "产物区" ? "暂无新增产物。" : "暂无源码修改。"}</div>
          )}
        </div>
      </section>
    );
  }

  function renderOtherTaskSection(buckets: FileChangeTaskBucket[]) {
    if (!buckets.length) return null;
    const fileCount = buckets.reduce((total, bucket) => total + bucket.groups.length, 0);
    const recordCount = buckets.reduce((total, bucket) => total + bucket.records.length, 0);
    return (
      <section className="file-change-section file-change-section--other" aria-label="其它任务">
        <header className="file-change-section__head">
          <span><ListTree size={14} />其它任务</span>
          <strong>{fileCount}</strong>
        </header>
        <div className="file-change-task-list">
          {buckets.map((bucket) => (
            <div className="file-change-task-bucket" key={bucket.key}>
              <div className="file-change-task-bucket__head" title={bucket.taskRunId}>
                <span>{bucket.title}</span>
                <strong>{bucket.records.length} 条 · {bucket.groups.length} 文件</strong>
              </div>
              <div className="file-change-section__list">
                {bucket.groups.map((group) => renderChangeGroup(group))}
              </div>
            </div>
          ))}
        </div>
        <div className="file-change-task-summary">已从当前对话主列表分离 {recordCount} 条任务变更。</div>
      </section>
    );
  }

  return (
    <section className={embedded ? "file-changes-panel file-changes-panel--embedded" : "file-changes-panel"} aria-label="文件变更">
      <header className="file-changes-panel__head">
        <div>
          {embedded ? null : <span>变更</span>}
          <strong>{headline}</strong>
        </div>
        <button aria-label="刷新文件变更" disabled={loading || !currentSessionId} onClick={() => void refresh({ force: true })} type="button">
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
        {activeRecords.length ? (
          <>
            {conversationRecords.length ? (
              <>
                {renderGroupSection("修改区", modifiedGroups, "modified")}
                {renderGroupSection("产物区", artifactGroups, "artifact")}
              </>
            ) : (
              <div className="file-changes-empty file-changes-empty--compact">
                <span className="file-changes-empty__icon">
                  <FileClock size={16} />
                </span>
                <div className="file-changes-empty__copy">
                  <strong>当前对话暂无变更</strong>
                  <span>其它任务的文件修改已在下方单独列出。</span>
                </div>
              </div>
            )}
            {renderOtherTaskSection(otherTaskBuckets)}
          </>
        ) : (
          <div className="file-changes-empty">
            <span className="file-changes-empty__icon">
              <FileClock size={16} />
            </span>
            <div className="file-changes-empty__copy">
              <strong>{loading ? "同步中" : "暂无变更"}</strong>
              <span>{currentSessionId ? "当前会话还没有文件变更记录。" : "选择会话后显示文件变更。"}</span>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

type FileChangeGroup = {
  key: string;
  kind: "artifact" | "modified";
  latest: FileChangeRecord;
  path: string;
  records: FileChangeRecord[];
};

type FileChangeTaskBucket = {
  key: string;
  groups: FileChangeGroup[];
  latestAt: number;
  records: FileChangeRecord[];
  taskRunId: string;
  title: string;
};

function sortedRecordsByTime(records: FileChangeRecord[], direction: "asc" | "desc") {
  return [...records].sort((left, right) => {
    const delta = Number(left.created_at || 0) - Number(right.created_at || 0);
    return direction === "asc" ? delta : -delta;
  });
}

function groupBaselineRecord(group: FileChangeGroup) {
  return sortedRecordsByTime(group.records, "asc")[0] ?? group.latest;
}

function groupTaskFileChanges(records: FileChangeRecord[]): FileChangeTaskBucket[] {
  const buckets = new Map<string, FileChangeRecord[]>();
  for (const record of records) {
    const taskRunId = textValue(record.task_run_id) || "未绑定任务";
    const nextRecords = buckets.get(taskRunId) ?? [];
    nextRecords.push(record);
    buckets.set(taskRunId, nextRecords);
  }

  return Array.from(buckets.entries())
    .map(([taskRunId, bucketRecords]) => {
      const sortedRecords = sortedRecordsByTime(bucketRecords, "desc");
      return {
        key: `task:${taskRunId}`,
        groups: groupFileChanges(sortedRecords, `task:${taskRunId}`),
        latestAt: Number(sortedRecords[0]?.created_at || 0),
        records: sortedRecords,
        taskRunId,
        title: compactTaskRunLabel(taskRunId),
      };
    })
    .sort((left, right) => right.latestAt - left.latestAt);
}

function compactTaskRunLabel(taskRunId: string) {
  const normalized = textValue(taskRunId);
  if (!normalized || normalized === "未绑定任务") return "未绑定任务";
  const parts = normalized.split(/[:/\\]/).filter(Boolean);
  const tail = parts.slice(-2).join(":");
  return tail ? `任务 ${tail}` : normalized;
}

function groupFileChanges(records: FileChangeRecord[], scopeKey = "default"): FileChangeGroup[] {
  const groups = new Map<string, FileChangeGroup>();
  for (const record of records) {
    const path = displayPath(record);
    const key = `${scopeKey}:${path.toLowerCase()}`;
    const group = groups.get(key);
    if (!group) {
      groups.set(key, {
        key,
        kind: isArtifactChange(record) ? "artifact" : "modified",
        latest: record,
        path,
        records: [record],
      });
      continue;
    }
    group.records.push(record);
    if (Number(record.created_at || 0) > Number(group.latest.created_at || 0)) {
      group.latest = record;
      group.kind = isArtifactChange(record) ? "artifact" : "modified";
    }
  }
  for (const group of groups.values()) {
    group.records = sortedRecordsByTime(group.records, "desc");
  }
  return Array.from(groups.values()).sort((left, right) => Number(right.latest.created_at || 0) - Number(left.latest.created_at || 0));
}

function isArtifactChange(record: FileChangeRecord) {
  const path = displayPath(record).toLowerCase();
  if (!record.before_exists && record.after_exists) return true;
  const parts = path.split("/").filter(Boolean);
  const root = parts[0] || "";
  if (["output", "outputs", "artifacts", "exports", "reports", "dist", "build", "coverage"].includes(root)) return true;
  if (parts.some((part) => ["artifacts", "screenshots", "playwright", "generated", "exports", "reports"].includes(part))) return true;
  return /\.(png|jpe?g|webp|gif|svg|pdf|docx|pptx|xlsx|zip|mp4|mov|webm)$/i.test(path);
}

function taskRunKeyFromMessages(messages: Array<{ sourceTaskRunId?: string; runtimeProgress?: Array<{ taskRunId?: string }> }>) {
  const ids = new Set<string>();
  for (const message of messages) {
    const sourceTaskRunId = textValue(message.sourceTaskRunId);
    if (sourceTaskRunId) ids.add(sourceTaskRunId);
    for (const progress of message.runtimeProgress ?? []) {
      const taskRunId = textValue(progress.taskRunId);
      if (taskRunId) ids.add(taskRunId);
    }
  }
  return Array.from(ids).sort().join("\n");
}
