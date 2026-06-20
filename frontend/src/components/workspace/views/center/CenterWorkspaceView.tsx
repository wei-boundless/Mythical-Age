"use client";

import { AlertTriangle, Edit3, FileText, GitCompare, Loader2, RefreshCw, Save, Sparkles, Terminal, Workflow, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ChatPanel } from "@/components/chat/ChatPanel";
import { WorkspaceModeSwitcher } from "@/components/layout/WorkspaceModeSwitcher";
import { RuntimeLogPanel, type RuntimeLogTarget } from "@/components/layout/RuntimeLogPanel";
import { getFileChangeDiff, type FileChangeDiffPayload } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { cn } from "@/ui/classNames";
import { TabButton, Tabs } from "@/ui/Tabs";

type CenterWorkspaceLayer = "chat" | "file" | "file-change-diff" | "runtime-log";
const GENERAL_TASK_ENVIRONMENT_ID = "env.general.workspace";

type FileChangeDiffPage = {
  baselineRecordId?: string;
  changeCount?: number;
  mode?: "final" | "single";
  recordId: string;
  title?: string;
  subtitle?: string;
};

function compactFileName(path: string) {
  const normalized = path.replace(/\\/g, "/");
  const parts = normalized.split("/");
  return parts[parts.length - 1] || path || "文件";
}

function runtimeLogPageKey(target: RuntimeLogTarget) {
  return `${target.scope}:${target.runId}`;
}

function fileChangeDiffPageKey(target: FileChangeDiffPage) {
  const mode = target.mode ?? "single";
  return `${mode}:${target.baselineRecordId || target.recordId}:${target.recordId}`;
}

function runtimeLogPageTitle(target: RuntimeLogTarget) {
  const title = String(target.title || "").trim();
  if (title) return title.length > 28 ? `${title.slice(0, 28)}...` : title;
  return target.scope === "turn_run" ? "TurnRun Log" : "TaskRun Log";
}

function fileChangeDiffPageTitle(target: FileChangeDiffPage) {
  const title = String(target.title || "").trim();
  if (title) {
    const label = target.mode === "final" ? `最终 ${compactFileName(title)}` : compactFileName(title);
    return label.length > 28 ? `${label.slice(0, 28)}...` : label;
  }
  return "文件 Diff";
}

function isEditableWorkspacePath(path: string, editablePrefixes: string[] = []) {
  const normalized = path.replace(/\\/g, "/").replace(/^\/+/, "");
  return editablePrefixes.some((prefix) => normalized.startsWith(prefix));
}

function CenterWorkspaceFileLayer({
  onClose,
  path,
}: {
  onClose: () => void;
  path: string;
}) {
  const {
    inspectorContent,
    inspectorDirty,
    inspectorPath,
    loadInspectorFile,
    saveInspector,
    updateInspectorContent,
    workspaceContext,
  } = useAppStore();
  const [editing, setEditing] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [saving, setSaving] = useState(false);
  const targetPath = path.trim();
  const displayPath = targetPath || inspectorPath;
  const loaded = Boolean(displayPath && inspectorPath === displayPath);
  const editable = loaded && isEditableWorkspacePath(displayPath, workspaceContext?.editable_prefixes);

  useEffect(() => {
    setEditing(false);
    if (targetPath && inspectorPath !== targetPath) {
      void loadInspectorFile(targetPath);
    }
  }, [inspectorPath, loadInspectorFile, targetPath]);

  useEffect(() => {
    if (!editable && editing) {
      setEditing(false);
    }
  }, [editable, editing]);

  async function refreshFile() {
    if (!displayPath) {
      return;
    }
    setRefreshing(true);
    try {
      await loadInspectorFile(displayPath);
    } finally {
      setRefreshing(false);
    }
  }

  async function saveFile() {
    if (!editable || !inspectorDirty) {
      return;
    }
    setSaving(true);
    try {
      await saveInspector();
      setEditing(false);
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="center-workspace__file-layer" aria-label="文件页">
      <header className="center-workspace-file__head">
        <div className="center-workspace-file__title">
          <span>{editable ? "项目文件" : "只读文件"}</span>
          <strong>{compactFileName(displayPath)}</strong>
          <small title={displayPath}>{displayPath || "未选择文件"}</small>
        </div>
        <div className="center-workspace-file__actions" aria-label="文件操作">
          <button disabled={!displayPath || refreshing} onClick={() => void refreshFile()} type="button">
            <RefreshCw size={14} />
            <span>{refreshing ? "刷新中" : "刷新"}</span>
          </button>
          {!editable ? (
            <span className="center-workspace-file__badge">只读</span>
          ) : editing ? (
            <button disabled={!inspectorDirty || saving} onClick={() => void saveFile()} type="button">
              <Save size={14} />
              <span>{saving ? "保存中" : "保存"}</span>
            </button>
          ) : (
            <button disabled={!loaded} onClick={() => setEditing(true)} type="button">
              <Edit3 size={14} />
              <span>编辑</span>
            </button>
          )}
          <button aria-label="关闭文件页" className="center-workspace-file__icon-button" onClick={onClose} title="关闭文件页" type="button">
            <X size={14} />
          </button>
        </div>
      </header>

      <div className="center-workspace-file__body" aria-busy={!loaded}>
        {!loaded ? (
          <div className="center-workspace-file__empty">正在读取文件。</div>
        ) : editing && editable ? (
          <textarea
            aria-label="文件内容编辑器"
            onChange={(event) => updateInspectorContent(event.target.value)}
            spellCheck={false}
            value={inspectorContent}
          />
        ) : (
          <pre>{inspectorContent || "文件为空。"}</pre>
        )}
      </div>
    </section>
  );
}

function lineCount(value: string) {
  if (!value) return 0;
  return value.split(/\r?\n/).length;
}

type DiffLineState = "unchanged" | "removed" | "added";

type DiffDisplayLine = {
  lineNumber: number;
  state: DiffLineState;
  text: string;
};

function splitDiffLines(value: string) {
  return value ? value.split(/\r?\n/) : [];
}

function simpleDiffLines(beforeLines: string[], afterLines: string[]) {
  const afterCounts = new Map<string, number>();
  for (const line of afterLines) {
    afterCounts.set(line, (afterCounts.get(line) || 0) + 1);
  }
  const beforeCounts = new Map<string, number>();
  for (const line of beforeLines) {
    beforeCounts.set(line, (beforeCounts.get(line) || 0) + 1);
  }
  return {
    before: beforeLines.map((text, index) => ({
      lineNumber: index + 1,
      state: afterCounts.has(text) ? "unchanged" as const : "removed" as const,
      text,
    })),
    after: afterLines.map((text, index) => ({
      lineNumber: index + 1,
      state: beforeCounts.has(text) ? "unchanged" as const : "added" as const,
      text,
    })),
  };
}

function buildLineDiff(beforeContent: string, afterContent: string) {
  const beforeLines = splitDiffLines(beforeContent);
  const afterLines = splitDiffLines(afterContent);
  if (!beforeLines.length && !afterLines.length) {
    return { before: [], after: [] };
  }

  const cellCount = beforeLines.length * afterLines.length;
  if (cellCount > 2_000_000) {
    return simpleDiffLines(beforeLines, afterLines);
  }

  const lcs = Array.from({ length: beforeLines.length + 1 }, () => new Uint32Array(afterLines.length + 1));
  for (let i = beforeLines.length - 1; i >= 0; i -= 1) {
    const currentRow = lcs[i];
    const nextRow = lcs[i + 1];
    for (let j = afterLines.length - 1; j >= 0; j -= 1) {
      currentRow[j] = beforeLines[i] === afterLines[j]
        ? nextRow[j + 1] + 1
        : Math.max(nextRow[j], currentRow[j + 1]);
    }
  }

  const before: DiffDisplayLine[] = [];
  const after: DiffDisplayLine[] = [];
  let beforeIndex = 0;
  let afterIndex = 0;
  while (beforeIndex < beforeLines.length && afterIndex < afterLines.length) {
    if (beforeLines[beforeIndex] === afterLines[afterIndex]) {
      before.push({ lineNumber: beforeIndex + 1, state: "unchanged", text: beforeLines[beforeIndex] });
      after.push({ lineNumber: afterIndex + 1, state: "unchanged", text: afterLines[afterIndex] });
      beforeIndex += 1;
      afterIndex += 1;
    } else if (lcs[beforeIndex + 1][afterIndex] >= lcs[beforeIndex][afterIndex + 1]) {
      before.push({ lineNumber: beforeIndex + 1, state: "removed", text: beforeLines[beforeIndex] });
      beforeIndex += 1;
    } else {
      after.push({ lineNumber: afterIndex + 1, state: "added", text: afterLines[afterIndex] });
      afterIndex += 1;
    }
  }
  while (beforeIndex < beforeLines.length) {
    before.push({ lineNumber: beforeIndex + 1, state: "removed", text: beforeLines[beforeIndex] });
    beforeIndex += 1;
  }
  while (afterIndex < afterLines.length) {
    after.push({ lineNumber: afterIndex + 1, state: "added", text: afterLines[afterIndex] });
    afterIndex += 1;
  }
  return { before, after };
}

function composeFinalDiffPayload({
  baseline,
  final,
}: {
  baseline: FileChangeDiffPayload;
  final: FileChangeDiffPayload;
}): FileChangeDiffPayload {
  return {
    ...final,
    before_content: baseline.before_content || "",
    before_exists: baseline.before_exists,
    before_sha256: baseline.before_sha256,
    diff_id: baseline.diff_id === final.diff_id ? final.diff_id : `${baseline.diff_id}..${final.diff_id}`,
    logical_path: final.logical_path || baseline.logical_path,
    truncated: Boolean(baseline.truncated || final.truncated),
    metadata: {
      ...(final.metadata || {}),
      baseline_record: baseline.metadata?.record,
      final_record: final.metadata?.record,
    },
  };
}

function DiffCodePane({
  emptyText,
  lines,
}: {
  emptyText: string;
  lines: DiffDisplayLine[];
}) {
  if (!lines.length) {
    return (
      <pre className="center-workspace-diff__code">
        <span className="center-workspace-diff__line center-workspace-diff__line--empty">{emptyText}</span>
      </pre>
    );
  }
  return (
    <pre className="center-workspace-diff__code">
      {lines.map((line, index) => (
        <span
          className={`center-workspace-diff__line center-workspace-diff__line--${line.state}`}
          key={`${line.lineNumber}:${line.state}:${index}`}
        >
          <span className="center-workspace-diff__line-number">{line.lineNumber}</span>
          <span className="center-workspace-diff__line-prefix">{line.state === "added" ? "+" : line.state === "removed" ? "-" : " "}</span>
          <span className="center-workspace-diff__line-text">{line.text || " "}</span>
        </span>
      ))}
    </pre>
  );
}

function CenterWorkspaceDiffLayer({
  baselineRecordId,
  changeCount,
  mode = "single",
  onClose,
  recordId,
  subtitle,
  title,
}: {
  baselineRecordId?: string;
  changeCount?: number;
  mode?: "final" | "single";
  onClose: () => void;
  recordId: string;
  subtitle?: string;
  title?: string;
}) {
  const [diff, setDiff] = useState<FileChangeDiffPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refreshDiff = useCallback(async () => {
    const targetRecordId = recordId.trim();
    const targetBaselineRecordId = String(baselineRecordId || recordId).trim() || targetRecordId;
    if (!targetRecordId) return;
    setLoading(true);
    setError("");
    try {
      const finalPayloadPromise = getFileChangeDiff(targetRecordId);
      if (mode === "final" && targetBaselineRecordId && targetBaselineRecordId !== targetRecordId) {
        const [baselinePayload, finalPayload] = await Promise.all([
          getFileChangeDiff(targetBaselineRecordId),
          finalPayloadPromise,
        ]);
        setDiff(composeFinalDiffPayload({ baseline: baselinePayload.diff, final: finalPayload.diff }));
      } else {
        const payload = await finalPayloadPromise;
        setDiff(payload.diff);
      }
    } catch (diffError) {
      setError(diffError instanceof Error ? diffError.message : "Diff 加载失败。");
    } finally {
      setLoading(false);
    }
  }, [baselineRecordId, mode, recordId]);

  useEffect(() => {
    void refreshDiff();
  }, [refreshDiff]);

  const path = diff?.logical_path || subtitle || title || recordId;
  const beforeTitle = diff?.before_exists ? "修改前" : "修改前不存在";
  const afterTitle = diff?.after_exists ? "修改后" : "修改后不存在";
  const beforeContent = diff?.before_content || "";
  const afterContent = diff?.after_content || "";
  const lineDiff = useMemo(() => buildLineDiff(beforeContent, afterContent), [afterContent, beforeContent]);

  return (
    <section className="center-workspace__diff-layer" aria-label="文件 Diff">
      <header className="center-workspace-diff__head">
        <div className="center-workspace-diff__title">
          <span><GitCompare size={14} />{mode === "final" ? "最终 Diff" : "单次 Diff"}</span>
          <strong>{compactFileName(path)}</strong>
          <small title={path}>{path}</small>
        </div>
        <div className="center-workspace-diff__actions">
          <button disabled={loading} onClick={() => void refreshDiff()} type="button">
            {loading ? <Loader2 className="spin" size={14} /> : <RefreshCw size={14} />}
            <span>{loading ? "加载中" : "刷新"}</span>
          </button>
          <button aria-label="关闭 Diff 页" className="center-workspace-file__icon-button" onClick={onClose} title="关闭 Diff 页" type="button">
            <X size={14} />
          </button>
        </div>
      </header>

      {error ? (
        <div className="center-workspace-diff__notice">
          <AlertTriangle size={15} />
          <span>{error}</span>
        </div>
      ) : null}
      {diff?.truncated ? (
        <div className="center-workspace-diff__notice">
          <AlertTriangle size={15} />
          <span>内容较长，当前只显示后端保留的快照片段。</span>
        </div>
      ) : null}

      <div className="center-workspace-diff__meta" aria-label="Diff 摘要">
        {mode === "final" ? <span>最终对比{changeCount && changeCount > 1 ? ` · ${changeCount} 次修改` : ""}</span> : <span>单次记录</span>}
        <span>{beforeTitle}: {lineCount(beforeContent)} 行</span>
        <span>{afterTitle}: {lineCount(afterContent)} 行</span>
        <span>{diff?.diff_id || recordId}</span>
      </div>

      <div className="center-workspace-diff__body" aria-busy={loading}>
        {loading && !diff ? (
          <div className="center-workspace-file__empty">
            <Loader2 className="spin" size={17} />
            正在加载 Diff。
          </div>
        ) : (
          <>
            <section className="center-workspace-diff__pane" aria-label={beforeTitle}>
              <header>
                <span>{beforeTitle}</span>
                <small>{diff?.before_sha256 ? diff.before_sha256.slice(0, 10) : "-"}</small>
              </header>
              <DiffCodePane emptyText="空文件" lines={lineDiff.before} />
            </section>
            <section className="center-workspace-diff__pane center-workspace-diff__pane--after" aria-label={afterTitle}>
              <header>
                <span>{afterTitle}</span>
                <small>{diff?.after_sha256 ? diff.after_sha256.slice(0, 10) : "-"}</small>
              </header>
              <DiffCodePane emptyText="空文件" lines={lineDiff.after} />
            </section>
          </>
        )}
      </div>
    </section>
  );
}

export function CenterWorkspaceView({
  taskEnvironmentId = GENERAL_TASK_ENVIRONMENT_ID,
}: {
  taskEnvironmentId?: string;
}) {
  const {
    centerWorkspaceTarget,
    clearCenterWorkspaceTarget,
    currentSessionId,
    inspectorDirty,
    sessionEditorContexts,
    setSessionEditorPageState,
    setWorkspaceView,
  } = useAppStore();
  const [layer, setLayer] = useState<CenterWorkspaceLayer>("chat");
  const [activeFilePath, setActiveFilePath] = useState("");
  const [openFilePaths, setOpenFilePaths] = useState<string[]>([]);
  const [activeDiffKey, setActiveDiffKey] = useState("");
  const [openDiffPages, setOpenDiffPages] = useState<FileChangeDiffPage[]>([]);
  const [activeRuntimeLogKey, setActiveRuntimeLogKey] = useState("");
  const [openRuntimeLogPages, setOpenRuntimeLogPages] = useState<RuntimeLogTarget[]>([]);
  const sessionEditorContext = currentSessionId ? sessionEditorContexts[currentSessionId] : null;

  const canSwitchActiveFile = useCallback((nextPath: string) => {
    if (!inspectorDirty || !activeFilePath || activeFilePath === nextPath) {
      return true;
    }
    return window.confirm("当前文件有未保存修改，切换文件会丢弃这些修改。继续切换吗？");
  }, [activeFilePath, inspectorDirty]);

  const openFilePage = useCallback((path: string) => {
    const nextPath = path.trim();
    if (!nextPath || !canSwitchActiveFile(nextPath)) {
      return;
    }
    const nextOpenFilePaths = openFilePaths.includes(nextPath) ? openFilePaths : [...openFilePaths, nextPath];
    setOpenFilePaths(nextOpenFilePaths);
    setActiveFilePath(nextPath);
    setLayer("file");
    setSessionEditorPageState({ activeFilePath: nextPath, openFilePaths: nextOpenFilePaths });
  }, [canSwitchActiveFile, openFilePaths, setSessionEditorPageState]);

  const closeFilePage = useCallback((path: string) => {
    const targetPath = path.trim();
    if (!targetPath) {
      return;
    }
    if (targetPath === activeFilePath && inspectorDirty && !window.confirm("当前文件有未保存修改，关闭文件页会丢弃这些修改。继续关闭吗？")) {
      return;
    }
    const targetIndex = openFilePaths.indexOf(targetPath);
    const nextOpenFilePaths = openFilePaths.filter((item) => item !== targetPath);
    const nextActiveFilePath = targetPath === activeFilePath
      ? nextOpenFilePaths[Math.min(Math.max(targetIndex, 0), nextOpenFilePaths.length - 1)] || ""
      : activeFilePath;
    setOpenFilePaths(nextOpenFilePaths);
    setActiveFilePath(nextActiveFilePath);
    if (targetPath === activeFilePath) {
      setLayer(nextActiveFilePath ? "file" : "chat");
    }
    setSessionEditorPageState({ activeFilePath: nextActiveFilePath, openFilePaths: nextOpenFilePaths });
  }, [activeFilePath, inspectorDirty, openFilePaths, setSessionEditorPageState]);

  const openRuntimeLogPage = useCallback((target: RuntimeLogTarget) => {
    const runId = String(target.runId || "").trim();
    if (!runId) return;
    const normalized: RuntimeLogTarget = {
      scope: target.scope === "turn_run" ? "turn_run" : "task_run",
      runId,
      title: String(target.title || "").trim() || undefined,
      subtitle: String(target.subtitle || "").trim() || runId,
    };
    const key = runtimeLogPageKey(normalized);
    setOpenRuntimeLogPages((pages) => {
      const existing = pages.find((page) => runtimeLogPageKey(page) === key);
      if (existing) {
        return pages.map((page) => runtimeLogPageKey(page) === key ? { ...page, ...normalized } : page);
      }
      return [...pages, normalized];
    });
    setActiveRuntimeLogKey(key);
    setLayer("runtime-log");
  }, []);

  const openFileChangeDiffPage = useCallback((target: FileChangeDiffPage) => {
    const recordId = String(target.recordId || "").trim();
    if (!recordId) return;
    const normalized: FileChangeDiffPage = {
      baselineRecordId: String(target.baselineRecordId || target.recordId || "").trim() || undefined,
      changeCount: Number.isFinite(Number(target.changeCount)) ? Number(target.changeCount) : undefined,
      mode: target.mode === "final" ? "final" : "single",
      recordId,
      title: String(target.title || "").trim() || undefined,
      subtitle: String(target.subtitle || "").trim() || recordId,
    };
    const key = fileChangeDiffPageKey(normalized);
    setOpenDiffPages((pages) => {
      const existing = pages.find((page) => fileChangeDiffPageKey(page) === key);
      if (existing) {
        return pages.map((page) => fileChangeDiffPageKey(page) === key ? { ...page, ...normalized } : page);
      }
      return [...pages, normalized];
    });
    setActiveDiffKey(key);
    setLayer("file-change-diff");
  }, []);

  const closeFileChangeDiffPage = useCallback((key: string) => {
    setOpenDiffPages((pages) => {
      const index = pages.findIndex((page) => fileChangeDiffPageKey(page) === key);
      const nextPages = pages.filter((page) => fileChangeDiffPageKey(page) !== key);
      if (key === activeDiffKey) {
        const nextPage = nextPages[Math.min(Math.max(index, 0), nextPages.length - 1)] ?? null;
        setActiveDiffKey(nextPage ? fileChangeDiffPageKey(nextPage) : "");
        setLayer(nextPage ? "file-change-diff" : activeFilePath ? "file" : activeRuntimeLogKey ? "runtime-log" : "chat");
      }
      return nextPages;
    });
  }, [activeDiffKey, activeFilePath, activeRuntimeLogKey]);

  const closeRuntimeLogPage = useCallback((key: string) => {
    setOpenRuntimeLogPages((pages) => {
      const index = pages.findIndex((page) => runtimeLogPageKey(page) === key);
      const nextPages = pages.filter((page) => runtimeLogPageKey(page) !== key);
      if (key === activeRuntimeLogKey) {
        const nextPage = nextPages[Math.min(Math.max(index, 0), nextPages.length - 1)] ?? null;
        setActiveRuntimeLogKey(nextPage ? runtimeLogPageKey(nextPage) : "");
        setLayer(nextPage ? "runtime-log" : activeFilePath ? "file" : "chat");
      }
      return nextPages;
    });
  }, [activeFilePath, activeRuntimeLogKey]);

  useEffect(() => {
    const nextOpenFilePaths = sessionEditorContext?.openFilePaths ?? [];
    const nextActiveFilePath = sessionEditorContext?.activeFilePath ?? "";
    setOpenFilePaths(nextOpenFilePaths);
    setActiveFilePath(nextActiveFilePath);
    setLayer(nextActiveFilePath ? "file" : "chat");
  }, [currentSessionId, sessionEditorContext?.activeFilePath, sessionEditorContext?.openFilePaths]);

  useEffect(() => {
    if (!centerWorkspaceTarget) {
      return;
    }
    if (centerWorkspaceTarget.layer === "file") {
      openFilePage(centerWorkspaceTarget.file_path);
    } else if (centerWorkspaceTarget.layer === "file-change-diff") {
      openFileChangeDiffPage({
        baselineRecordId: centerWorkspaceTarget.baseline_record_id,
        changeCount: centerWorkspaceTarget.change_count,
        mode: centerWorkspaceTarget.mode,
        recordId: centerWorkspaceTarget.record_id,
        title: centerWorkspaceTarget.title,
        subtitle: centerWorkspaceTarget.subtitle,
      });
    } else if (centerWorkspaceTarget.layer === "runtime-log") {
      openRuntimeLogPage({
        scope: centerWorkspaceTarget.scope,
        runId: centerWorkspaceTarget.run_id,
        title: centerWorkspaceTarget.title,
        subtitle: centerWorkspaceTarget.subtitle,
      });
    }
    clearCenterWorkspaceTarget();
  }, [centerWorkspaceTarget, clearCenterWorkspaceTarget, openFileChangeDiffPage, openFilePage, openRuntimeLogPage]);

  function closeFileLayer() {
    closeFilePage(activeFilePath);
  }

  const activeRuntimeLogPage = openRuntimeLogPages.find((page) => runtimeLogPageKey(page) === activeRuntimeLogKey) ?? null;
  const activeDiffPage = openDiffPages.find((page) => fileChangeDiffPageKey(page) === activeDiffKey) ?? null;

  return (
    <section className="center-workspace" aria-label="中心工作区">
      <header className="center-workspace__head" aria-label="主会话页面控制">
        <Tabs ariaLabel="中心层级切换">
          <TabButton
            active={layer === "chat"}
            onClick={() => setLayer("chat")}
          >
            <Sparkles size={14} />
            <span>会话层</span>
          </TabButton>
          <TabButton
            onClick={() => setWorkspaceView("creative")}
          >
            <Workflow size={14} />
            <span>图任务层</span>
          </TabButton>
          {openFilePaths.map((path) => {
            const active = layer === "file" && path === activeFilePath;
            return (
              <div
                className={cn("chat-page-tabs__item", active && "chat-page-tabs__item--active", "center-workspace-file-tab")}
                key={path}
                title={path}
              >
                <button
                  aria-current={active ? "page" : undefined}
                  className="center-workspace-file-tab__main"
                  onClick={() => {
                    if (!canSwitchActiveFile(path)) return;
                    setActiveFilePath(path);
                    setLayer("file");
                    setSessionEditorPageState({ activeFilePath: path, openFilePaths });
                  }}
                  type="button"
                >
                  <FileText size={14} />
                  <span>{compactFileName(path)}</span>
                </button>
                <button
                  aria-label={`关闭文件页 ${compactFileName(path)}`}
                  className="center-workspace-file-tab__close"
                  onClick={() => closeFilePage(path)}
                  title="关闭文件页"
                  type="button"
                >
                  <X size={13} />
                </button>
              </div>
            );
          })}
          {openRuntimeLogPages.map((target) => {
            const key = runtimeLogPageKey(target);
            const active = layer === "runtime-log" && key === activeRuntimeLogKey;
            const label = runtimeLogPageTitle(target);
            return (
              <div
                className={cn("chat-page-tabs__item", active && "chat-page-tabs__item--active", "center-workspace-file-tab")}
                key={key}
                title={target.subtitle || target.runId}
              >
                <button
                  aria-current={active ? "page" : undefined}
                  className="center-workspace-file-tab__main"
                  onClick={() => {
                    setActiveRuntimeLogKey(key);
                    setLayer("runtime-log");
                  }}
                  type="button"
                >
                  <Terminal size={14} />
                  <span>{label}</span>
                </button>
                <button
                  aria-label={`关闭日志页 ${label}`}
                  className="center-workspace-file-tab__close"
                  onClick={() => closeRuntimeLogPage(key)}
                  title="关闭日志页"
                  type="button"
                >
                  <X size={13} />
                </button>
              </div>
            );
          })}
          {openDiffPages.map((target) => {
            const key = fileChangeDiffPageKey(target);
            const active = layer === "file-change-diff" && key === activeDiffKey;
            const label = fileChangeDiffPageTitle(target);
            return (
              <div
                className={cn("chat-page-tabs__item", active && "chat-page-tabs__item--active", "center-workspace-file-tab")}
                key={key}
                title={target.subtitle || target.recordId}
              >
                <button
                  aria-current={active ? "page" : undefined}
                  className="center-workspace-file-tab__main"
                  onClick={() => {
                    setActiveDiffKey(key);
                    setLayer("file-change-diff");
                  }}
                  type="button"
                >
                  <GitCompare size={14} />
                  <span>{label}</span>
                </button>
                <button
                  aria-label={`关闭 Diff 页 ${label}`}
                  className="center-workspace-file-tab__close"
                  onClick={() => closeFileChangeDiffPage(key)}
                  title="关闭 Diff 页"
                  type="button"
                >
                  <X size={13} />
                </button>
              </div>
            );
          })}
        </Tabs>
        <WorkspaceModeSwitcher ariaLabel="切换当前会话任务环境" className="center-workspace__environment-switcher" />
      </header>

      {layer === "chat" ? (
        <div className="center-workspace__chat">
          <ChatPanel />
        </div>
      ) : layer === "file" ? (
        <CenterWorkspaceFileLayer onClose={closeFileLayer} path={activeFilePath} />
      ) : layer === "file-change-diff" && activeDiffPage ? (
        <CenterWorkspaceDiffLayer
          baselineRecordId={activeDiffPage.baselineRecordId}
          changeCount={activeDiffPage.changeCount}
          mode={activeDiffPage.mode}
          onClose={() => closeFileChangeDiffPage(fileChangeDiffPageKey(activeDiffPage))}
          recordId={activeDiffPage.recordId}
          subtitle={activeDiffPage.subtitle}
          title={activeDiffPage.title}
        />
      ) : activeRuntimeLogPage ? (
        <section className="center-workspace__runtime-log-layer" aria-label="运行日志页">
          <RuntimeLogPanel target={activeRuntimeLogPage} onClose={() => closeRuntimeLogPage(runtimeLogPageKey(activeRuntimeLogPage))} />
        </section>
      ) : (
        <div className="center-workspace-file__empty">没有打开的运行日志。</div>
      )}
    </section>
  );
}
