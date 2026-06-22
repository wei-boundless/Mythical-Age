"use client";

import dynamic from "next/dynamic";
import { AlertTriangle, Code2, ExternalLink, FileText, GitCompare, Loader2, PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen, Plus, RefreshCw, Save, Sparkles, Terminal, Workflow, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { ChatPanel } from "@/components/chat/ChatPanel";
import { RuntimeLogPanel, type RuntimeLogTarget } from "@/components/layout/RuntimeLogPanel";
import { useWorkbenchShellControls } from "@/components/layout/WorkbenchShell";
import { getFileChangeDiff, openManagedFileInVSCode, type FileChangeDiffPayload } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { cn } from "@/ui/classNames";
import { TabButton, Tabs } from "@/ui/Tabs";

type CenterWorkspaceLayer = "chat" | "resource-launcher" | "file" | "file-change-diff" | "runtime-log";
type CenterWorkspaceAuxLayer = Exclude<CenterWorkspaceLayer, "chat" | "resource-launcher">;
const GENERAL_TASK_ENVIRONMENT_ID = "env.general.workspace";
const CENTER_PAGE_WIDTH_STORAGE_KEY = "center-workspace:right-page-width";
const CENTER_PAGE_DEFAULT_WIDTH = 680;
const CENTER_PAGE_MIN_WIDTH = 320;
const CENTER_PAGE_MAX_WIDTH = 1280;
const CENTER_CHAT_MIN_VISIBLE_WIDTH = 72;
const CENTER_SPLIT_RESIZER_WIDTH = 16;
const CENTER_DIFF_SPLIT_DEFAULT_PERCENT = 50;
const CENTER_DIFF_SPLIT_MIN_PERCENT = 28;
const CENTER_DIFF_SPLIT_MAX_PERCENT = 72;
const MonacoEditor = dynamic(() => import("@monaco-editor/react"), {
  ssr: false,
  loading: () => <div className="center-workspace-file__empty">编辑器载入中。</div>,
});

type FileChangeDiffPage = {
  baselineRecordId?: string;
  changeCount?: number;
  mode?: "final" | "single";
  recordId: string;
  title?: string;
  subtitle?: string;
};

type FileReaderMode = "preview" | "source";
type DiffViewMode = "split" | "before" | "after";

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

function isLegacyInternalEditablePath(path: string) {
  const normalized = path.replace(/\\/g, "/").replace(/^\/+/, "");
  return [
    "durable_memory/",
    "session-memory/",
    "sessions/",
    "knowledge/",
    "capability_system/skills/builtin/",
  ].some((prefix) => normalized.startsWith(prefix));
}

function languageIdForPath(path: string) {
  const normalized = path.toLowerCase();
  const extension = normalized.includes(".") ? normalized.slice(normalized.lastIndexOf(".") + 1) : "";
  switch (extension) {
    case "ts":
      return "typescript";
    case "tsx":
      return "typescriptreact";
    case "js":
      return "javascript";
    case "jsx":
      return "javascriptreact";
    case "py":
      return "python";
    case "json":
      return "json";
    case "md":
      return "markdown";
    case "css":
      return "css";
    case "html":
      return "html";
    case "yaml":
    case "yml":
      return "yaml";
    default:
      return extension || "plaintext";
  }
}

function CenterWorkspaceFileLayer({
  onClose,
  path,
}: {
  onClose: () => void;
  path: string;
}) {
  const {
    currentSessionId,
    inspectorContent,
    inspectorContentSha256,
    inspectorDirty,
    inspectorLastChangeRecordId,
    inspectorPath,
    inspectorTarget,
    loadInspectorFile,
    openFileChangeDiff,
    saveInspector,
    updateInspectorContent,
  } = useAppStore();
  const [refreshing, setRefreshing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [openingVSCode, setOpeningVSCode] = useState(false);
  const [actionError, setActionError] = useState("");
  const [readerMode, setReaderMode] = useState<FileReaderMode>("preview");
  const targetPath = path.trim();
  const displayPath = targetPath || inspectorPath;
  const loaded = Boolean(displayPath && inspectorPath === displayPath);
  const editable = loaded && (Boolean(inspectorTarget) || isLegacyInternalEditablePath(displayPath));
  const statusLabel = inspectorDirty ? "未保存" : editable ? "可编辑" : "只读";
  const canOpenInVSCode = Boolean(loaded && inspectorTarget && currentSessionId);
  const canOpenDiff = Boolean(loaded && inspectorLastChangeRecordId);
  const language = languageIdForPath(displayPath);
  const markdownFile = language === "markdown";
  const previewActive = loaded && markdownFile && readerMode === "preview";

  useEffect(() => {
    setActionError("");
    if (targetPath && inspectorPath !== targetPath) {
      void loadInspectorFile(targetPath);
    }
  }, [inspectorPath, loadInspectorFile, targetPath]);

  useEffect(() => {
    setReaderMode(languageIdForPath(displayPath) === "markdown" ? "preview" : "source");
  }, [displayPath]);

  async function refreshFile() {
    if (!displayPath) {
      return;
    }
    setRefreshing(true);
    setActionError("");
    try {
      await loadInspectorFile(displayPath);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "文件刷新失败。");
    } finally {
      setRefreshing(false);
    }
  }

  async function saveFile() {
    if (!editable || !inspectorDirty) {
      return;
    }
    setSaving(true);
    setActionError("");
    try {
      await saveInspector();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "文件保存失败。");
    } finally {
      setSaving(false);
    }
  }

  function openLatestDiff() {
    if (!inspectorLastChangeRecordId) {
      return;
    }
    openFileChangeDiff({
      record_id: inspectorLastChangeRecordId,
      baseline_record_id: inspectorLastChangeRecordId,
      mode: "single",
      change_count: 1,
      title: displayPath,
      subtitle: "刚刚保存的文件变更",
    });
  }

  async function openInVSCode() {
    if (!inspectorTarget || !currentSessionId) {
      setActionError("当前文件没有可打开的 VS Code 连接目标。");
      return;
    }
    setOpeningVSCode(true);
    setActionError("");
    try {
      await openManagedFileInVSCode(inspectorTarget, currentSessionId);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "无法在 VS Code 打开文件。");
    } finally {
      setOpeningVSCode(false);
    }
  }

  return (
    <section className="center-workspace__file-layer" aria-label="文件页">
      <header className="center-workspace-file__head">
        <div className="center-workspace-file__title">
          <span>{inspectorTarget ? "项目文件" : "内部资料"}</span>
          <strong>{compactFileName(displayPath)}</strong>
          <small title={displayPath}>{displayPath || "未选择文件"}</small>
        </div>
        <div className="center-workspace-file__actions" aria-label="文件操作">
          <span className={cn("center-workspace-file__badge", inspectorDirty && "center-workspace-file__badge--dirty")}>
            {statusLabel}
          </span>
          <button disabled={!displayPath || refreshing} onClick={() => void refreshFile()} type="button">
            <RefreshCw size={14} />
            <span>{refreshing ? "刷新中" : "刷新"}</span>
          </button>
          {markdownFile ? (
            <button onClick={() => setReaderMode(previewActive ? "source" : "preview")} type="button">
              {previewActive ? <Code2 size={14} /> : <FileText size={14} />}
              <span>{previewActive ? "源码" : "预览"}</span>
            </button>
          ) : null}
          <button disabled={!canOpenInVSCode || openingVSCode} onClick={() => void openInVSCode()} type="button">
            <ExternalLink size={14} />
            <span>{openingVSCode ? "打开中" : "VS Code"}</span>
          </button>
          <button disabled={!canOpenDiff} onClick={openLatestDiff} type="button">
            <GitCompare size={14} />
            <span>Diff</span>
          </button>
          <button disabled={!editable || !inspectorDirty || saving} onClick={() => void saveFile()} type="button">
            <Save size={14} />
            <span>{saving ? "保存中" : "保存"}</span>
          </button>
          <button aria-label="关闭文件页" className="center-workspace-file__icon-button" onClick={onClose} title="关闭文件页" type="button">
            <X size={14} />
          </button>
        </div>
      </header>

      <div className="center-workspace-file__meta" aria-label="文件状态">
        <span>{language}</span>
        {markdownFile ? <span>{previewActive ? "阅读视图" : "源码视图"}</span> : null}
        <span>{lineCount(inspectorContent)} 行</span>
        {inspectorContentSha256 ? <span title={inspectorContentSha256}>sha256:{inspectorContentSha256.slice(0, 8)}</span> : null}
      </div>
      {actionError ? (
        <div className="center-workspace-file__notice" role="alert">
          <AlertTriangle size={14} />
          <span>{actionError}</span>
        </div>
      ) : null}
      <div className="center-workspace-file__body" aria-busy={!loaded}>
        {!loaded ? (
          <div className="center-workspace-file__empty">正在读取文件。</div>
        ) : previewActive ? (
          <article className="center-workspace-file__reader markdown">
            {inspectorContent.trim() ? (
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {inspectorContent}
              </ReactMarkdown>
            ) : (
              <div className="center-workspace-file__empty">
                <FileText size={18} />
                <span>这个 Markdown 文件暂无内容。</span>
              </div>
            )}
          </article>
        ) : (
          <div className="center-workspace-file__editor">
            <MonacoEditor
              height="100%"
              language={language}
              onChange={(value) => {
                if (editable) {
                  updateInspectorContent(value ?? "");
                }
              }}
              options={{
                automaticLayout: true,
                contextmenu: true,
                fontFamily: "\"Cascadia Code\", \"SFMono-Regular\", Consolas, monospace",
                fontSize: 14,
                lineHeight: 22,
                minimap: { enabled: false },
                padding: { top: 14, bottom: 14 },
                readOnly: !editable,
                renderLineHighlight: "line",
                scrollBeyondLastLine: false,
                smoothScrolling: true,
                wordWrap: "on",
              }}
              theme="vs"
              value={inspectorContent || ""}
            />
          </div>
        )}
      </div>
    </section>
  );
}

function lineCount(value: string) {
  if (!value) return 0;
  return value.split(/\r?\n/).length;
}

function clampDiffSplitPercent(value: number) {
  if (!Number.isFinite(value)) {
    return CENTER_DIFF_SPLIT_DEFAULT_PERCENT;
  }
  return Math.min(Math.max(Math.round(value), CENTER_DIFF_SPLIT_MIN_PERCENT), CENTER_DIFF_SPLIT_MAX_PERCENT);
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
  const [viewMode, setViewMode] = useState<DiffViewMode>("split");
  const [splitPercent, setSplitPercent] = useState(CENTER_DIFF_SPLIT_DEFAULT_PERCENT);
  const [resizingDiff, setResizingDiff] = useState(false);
  const diffBodyRef = useRef<HTMLDivElement | null>(null);
  const diffResizeRef = useRef({
    pointerId: -1,
    startPercent: CENTER_DIFF_SPLIT_DEFAULT_PERCENT,
    startX: 0,
    width: 0,
  });

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
  const splitActive = viewMode === "split";
  const showBeforePane = viewMode !== "after";
  const showAfterPane = viewMode !== "before";

  function startDiffResize(event: ReactPointerEvent<HTMLDivElement>) {
    if (!splitActive) {
      return;
    }
    const bodyWidth = diffBodyRef.current?.getBoundingClientRect().width ?? 0;
    if (bodyWidth <= 0) {
      return;
    }
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    diffResizeRef.current = {
      pointerId: event.pointerId,
      startPercent: splitPercent,
      startX: event.clientX,
      width: bodyWidth,
    };
    setResizingDiff(true);
  }

  function resizeDiffWithPointer(event: ReactPointerEvent<HTMLDivElement>) {
    const drag = diffResizeRef.current;
    if (!resizingDiff || drag.pointerId !== event.pointerId || drag.width <= 0) {
      return;
    }
    const deltaPercent = ((event.clientX - drag.startX) / drag.width) * 100;
    setSplitPercent(clampDiffSplitPercent(drag.startPercent + deltaPercent));
  }

  function stopDiffResize(event: ReactPointerEvent<HTMLDivElement>) {
    const drag = diffResizeRef.current;
    if (drag.pointerId !== event.pointerId) {
      return;
    }
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    diffResizeRef.current.pointerId = -1;
    setResizingDiff(false);
  }

  function resizeDiffWithKeyboard(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (!splitActive) {
      return;
    }
    const step = event.shiftKey ? 8 : 4;
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      setSplitPercent((value) => clampDiffSplitPercent(value - step));
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      setSplitPercent((value) => clampDiffSplitPercent(value + step));
    } else if (event.key === "Home") {
      event.preventDefault();
      setSplitPercent(CENTER_DIFF_SPLIT_MIN_PERCENT);
    } else if (event.key === "End") {
      event.preventDefault();
      setSplitPercent(CENTER_DIFF_SPLIT_MAX_PERCENT);
    }
  }

  return (
    <section className="center-workspace__diff-layer" aria-label="文件 Diff">
      <header className="center-workspace-diff__head">
        <div className="center-workspace-diff__title">
          <span><GitCompare size={14} />{mode === "final" ? "最终 Diff" : "单次 Diff"}</span>
          <strong>{compactFileName(path)}</strong>
          <small title={path}>{path}</small>
        </div>
        <div className="center-workspace-diff__actions">
          <div className="center-workspace-diff__view-switch" aria-label="Diff 视图">
            <button aria-pressed={viewMode === "split"} onClick={() => setViewMode("split")} type="button">双栏</button>
            <button aria-pressed={viewMode === "before"} onClick={() => setViewMode("before")} type="button">修改前</button>
            <button aria-pressed={viewMode === "after"} onClick={() => setViewMode("after")} type="button">修改后</button>
          </div>
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
      </div>

      <div
        className={cn(
          "center-workspace-diff__body",
          `center-workspace-diff__body--${viewMode}`,
          resizingDiff && "center-workspace-diff__body--resizing",
        )}
        aria-busy={loading}
        ref={diffBodyRef}
        style={{ "--center-diff-before-width": `${splitPercent}%` } as CSSProperties}
      >
        {loading && !diff ? (
          <div className="center-workspace-file__empty">
            <Loader2 className="spin" size={17} />
            正在加载 Diff。
          </div>
        ) : (
          <>
            {showBeforePane ? (
              <section className="center-workspace-diff__pane center-workspace-diff__pane--before" aria-label={beforeTitle}>
                <header>
                  <span>{beforeTitle}</span>
                </header>
                <DiffCodePane emptyText="空文件" lines={lineDiff.before} />
              </section>
            ) : null}
            {splitActive ? (
              <div
                aria-label="调整 Diff 双栏宽度"
                aria-orientation="vertical"
                aria-valuemax={CENTER_DIFF_SPLIT_MAX_PERCENT}
                aria-valuemin={CENTER_DIFF_SPLIT_MIN_PERCENT}
                aria-valuenow={splitPercent}
                className="center-workspace-diff__split-resizer"
                onKeyDown={resizeDiffWithKeyboard}
                onPointerCancel={stopDiffResize}
                onPointerDown={startDiffResize}
                onPointerMove={resizeDiffWithPointer}
                onPointerUp={stopDiffResize}
                role="separator"
                tabIndex={0}
                title="拖动调整修改前/修改后宽度"
              />
            ) : null}
            {showAfterPane ? (
              <section className="center-workspace-diff__pane center-workspace-diff__pane--after" aria-label={afterTitle}>
                <header>
                  <span>{afterTitle}</span>
                </header>
                <DiffCodePane emptyText="空文件" lines={lineDiff.after} />
              </section>
            ) : null}
          </>
        )}
      </div>
    </section>
  );
}

function CenterWorkspaceResourceLauncherPanel({
  onSelectFile,
}: {
  onSelectFile: () => Promise<void>;
}) {
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState("");

  async function selectFile() {
    if (opening) {
      return;
    }
    setOpening(true);
    setError("");
    try {
      await onSelectFile();
    } catch (selectError) {
      setError(selectError instanceof Error ? selectError.message : "无法打开文件。");
    } finally {
      setOpening(false);
    }
  }

  return (
    <section className="center-workspace__file-open-layer" aria-label="打开文件">
      <div className="center-file-open">
        <button
          className="center-file-open__command"
          disabled={opening}
          onClick={selectFile}
          type="button"
        >
          <span className="center-file-open__command-main">
            <span className="center-file-open__command-icon">
              <FileText size={17} />
            </span>
            <span>
              <strong>打开文件</strong>
              <small>从系统选择器选择文件</small>
            </span>
          </span>
          {opening ? <Loader2 className="center-file-open__spinner" size={16} /> : <ExternalLink size={16} />}
        </button>
        {error ? (
          <p className="center-file-open__error">
            <AlertTriangle size={14} />
            <span>{error}</span>
          </p>
        ) : null}
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
    selectWorkspaceFile,
    sessionEditorContexts,
    setSessionEditorPageState,
    setWorkspaceView,
  } = useAppStore();
  const shellControls = useWorkbenchShellControls();
  const [layer, setLayer] = useState<CenterWorkspaceLayer>("chat");
  const [pageLayerOpen, setPageLayerOpen] = useState(false);
  const [activeResourcePageId, setActiveResourcePageId] = useState("");
  const [openResourcePageIds, setOpenResourcePageIds] = useState<string[]>([]);
  const [activeFilePath, setActiveFilePath] = useState("");
  const [openFilePaths, setOpenFilePaths] = useState<string[]>([]);
  const [activeDiffKey, setActiveDiffKey] = useState("");
  const [openDiffPages, setOpenDiffPages] = useState<FileChangeDiffPage[]>([]);
  const [activeRuntimeLogKey, setActiveRuntimeLogKey] = useState("");
  const [openRuntimeLogPages, setOpenRuntimeLogPages] = useState<RuntimeLogTarget[]>([]);
  const [pageWidth, setPageWidth] = useState(() => {
    if (typeof window === "undefined") {
      return CENTER_PAGE_DEFAULT_WIDTH;
    }
    const storedWidth = Number(window.localStorage.getItem(CENTER_PAGE_WIDTH_STORAGE_KEY));
    if (!Number.isFinite(storedWidth)) {
      return CENTER_PAGE_DEFAULT_WIDTH;
    }
    return Math.min(Math.max(Math.round(storedWidth), CENTER_PAGE_MIN_WIDTH), CENTER_PAGE_MAX_WIDTH);
  });
  const [resizingPage, setResizingPage] = useState(false);
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const pageLayerRef = useRef<HTMLElement | null>(null);
  const pageResizeRef = useRef({ startWidth: CENTER_PAGE_DEFAULT_WIDTH, startX: 0 });
  const sessionEditorContext = currentSessionId ? sessionEditorContexts[currentSessionId] : null;

  const clampPageWidth = useCallback((nextWidth: number) => {
    const bodyWidth = bodyRef.current?.getBoundingClientRect().width ?? 0;
    const maxWidth = bodyWidth > 0
      ? Math.max(
          CENTER_PAGE_MIN_WIDTH,
          Math.min(
            CENTER_PAGE_MAX_WIDTH,
            Math.floor(bodyWidth - CENTER_CHAT_MIN_VISIBLE_WIDTH - CENTER_SPLIT_RESIZER_WIDTH),
          ),
        )
      : CENTER_PAGE_MAX_WIDTH;
    const minWidth = Math.min(CENTER_PAGE_MIN_WIDTH, maxWidth);
    return Math.min(Math.max(Math.round(nextWidth), minWidth), maxWidth);
  }, []);

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
    setPageLayerOpen(true);
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
      const nextLayer: CenterWorkspaceLayer = nextActiveFilePath
        ? "file"
        : activeDiffKey
          ? "file-change-diff"
          : activeRuntimeLogKey
            ? "runtime-log"
            : "chat";
      setLayer(nextLayer);
      if (nextLayer === "chat") {
        setPageLayerOpen(false);
      }
    }
    setSessionEditorPageState({ activeFilePath: nextActiveFilePath, openFilePaths: nextOpenFilePaths });
  }, [activeDiffKey, activeFilePath, activeRuntimeLogKey, inspectorDirty, openFilePaths, setSessionEditorPageState]);

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
    setPageLayerOpen(true);
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
    setPageLayerOpen(true);
  }, []);

  const closeFileChangeDiffPage = useCallback((key: string) => {
    setOpenDiffPages((pages) => {
      const index = pages.findIndex((page) => fileChangeDiffPageKey(page) === key);
      const nextPages = pages.filter((page) => fileChangeDiffPageKey(page) !== key);
      if (key === activeDiffKey) {
        const nextPage = nextPages[Math.min(Math.max(index, 0), nextPages.length - 1)] ?? null;
        const nextLayer: CenterWorkspaceLayer = nextPage ? "file-change-diff" : activeFilePath ? "file" : activeRuntimeLogKey ? "runtime-log" : "chat";
        setActiveDiffKey(nextPage ? fileChangeDiffPageKey(nextPage) : "");
        setLayer(nextLayer);
        if (nextLayer === "chat") {
          setPageLayerOpen(false);
        }
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
        const nextLayer: CenterWorkspaceLayer = nextPage ? "runtime-log" : activeDiffKey ? "file-change-diff" : activeFilePath ? "file" : "chat";
        setActiveRuntimeLogKey(nextPage ? runtimeLogPageKey(nextPage) : "");
        setLayer(nextLayer);
        if (nextLayer === "chat") {
          setPageLayerOpen(false);
        }
      }
      return nextPages;
    });
  }, [activeDiffKey, activeFilePath, activeRuntimeLogKey]);

  const closeResourcePage = useCallback((pageId: string) => {
    const targetPageId = pageId.trim();
    if (!targetPageId) {
      return;
    }
    setOpenResourcePageIds((pages) => {
      const index = pages.indexOf(targetPageId);
      const nextPages = pages.filter((item) => item !== targetPageId);
      if (targetPageId === activeResourcePageId) {
        const nextResourcePageId = nextPages[Math.min(Math.max(index, 0), nextPages.length - 1)] || "";
        setActiveResourcePageId(nextResourcePageId);
        if (nextResourcePageId) {
          setLayer("resource-launcher");
          setPageLayerOpen(true);
        } else if (activeFilePath) {
          setLayer("file");
          setPageLayerOpen(true);
        } else if (activeDiffKey) {
          setLayer("file-change-diff");
          setPageLayerOpen(true);
        } else if (activeRuntimeLogKey) {
          setLayer("runtime-log");
          setPageLayerOpen(true);
        } else {
          setLayer("chat");
          setPageLayerOpen(false);
        }
      }
      return nextPages;
    });
  }, [activeDiffKey, activeFilePath, activeResourcePageId, activeRuntimeLogKey]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(CENTER_PAGE_WIDTH_STORAGE_KEY, String(pageWidth));
  }, [pageWidth]);

  useEffect(() => {
    if (!pageLayerOpen) {
      return;
    }
    const syncPageWidth = () => {
      setPageWidth((currentWidth) => clampPageWidth(currentWidth));
    };
    syncPageWidth();
    const animationFrame = window.requestAnimationFrame(syncPageWidth);
    const body = bodyRef.current;
    if (!body || typeof ResizeObserver === "undefined") {
      return () => window.cancelAnimationFrame(animationFrame);
    }
    const observer = new ResizeObserver(syncPageWidth);
    observer.observe(body);
    window.addEventListener("resize", syncPageWidth);
    return () => {
      window.cancelAnimationFrame(animationFrame);
      window.removeEventListener("resize", syncPageWidth);
      observer.disconnect();
    };
  }, [clampPageWidth, pageLayerOpen]);

  function startPageResize(event: ReactPointerEvent<HTMLDivElement>) {
    if (!pageLayerOpen) {
      return;
    }
    event.preventDefault();
    const renderedWidth = pageLayerRef.current?.getBoundingClientRect().width;
    const startWidth = typeof renderedWidth === "number" && Number.isFinite(renderedWidth) && renderedWidth > 0
      ? clampPageWidth(renderedWidth)
      : clampPageWidth(pageWidth);
    setPageWidth(startWidth);
    pageResizeRef.current = {
      startWidth,
      startX: event.clientX,
    };
    setResizingPage(true);

    function handlePointerMove(moveEvent: PointerEvent) {
      const deltaX = moveEvent.clientX - pageResizeRef.current.startX;
      setPageWidth(clampPageWidth(pageResizeRef.current.startWidth - deltaX));
    }

    function stopResize() {
      setResizingPage(false);
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", stopResize);
      window.removeEventListener("pointercancel", stopResize);
    }

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", stopResize);
    window.addEventListener("pointercancel", stopResize);
  }

  function resizePageWithKeyboard(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (!pageLayerOpen) {
      return;
    }
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      setPageWidth((currentWidth) => clampPageWidth(currentWidth + 40));
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      setPageWidth((currentWidth) => clampPageWidth(currentWidth - 40));
    } else if (event.key === "Home") {
      event.preventDefault();
      setPageWidth(clampPageWidth(CENTER_PAGE_MAX_WIDTH));
    } else if (event.key === "End") {
      event.preventDefault();
      setPageWidth(clampPageWidth(CENTER_PAGE_MIN_WIDTH));
    }
  }

  useEffect(() => {
    const nextOpenFilePaths = sessionEditorContext?.openFilePaths ?? [];
    const nextActiveFilePath = sessionEditorContext?.activeFilePath ?? "";
    setOpenFilePaths(nextOpenFilePaths);
    setActiveFilePath(nextActiveFilePath);
    setLayer(nextActiveFilePath ? "file" : "chat");
    setPageLayerOpen(Boolean(nextActiveFilePath));
    setActiveResourcePageId("");
    setOpenResourcePageIds([]);
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
  const activeAuxLayer: CenterWorkspaceAuxLayer | null =
    layer === "file" && activeFilePath
      ? "file"
      : layer === "file-change-diff" && activeDiffPage
        ? "file-change-diff"
        : layer === "runtime-log" && activeRuntimeLogPage
          ? "runtime-log"
          : layer === "resource-launcher"
            ? null
            : activeFilePath
              ? "file"
              : activeDiffPage
                ? "file-change-diff"
                : activeRuntimeLogPage
                  ? "runtime-log"
                  : null;
  const activeAuxLabel = layer === "resource-launcher" || !activeAuxLayer
    ? "新建文件"
    : activeAuxLayer === "file"
    ? compactFileName(activeFilePath)
    : activeAuxLayer === "file-change-diff" && activeDiffPage
      ? fileChangeDiffPageTitle(activeDiffPage)
      : activeAuxLayer === "runtime-log" && activeRuntimeLogPage
        ? runtimeLogPageTitle(activeRuntimeLogPage)
        : "文件";
  const openPanelCount = openResourcePageIds.length + openFilePaths.length + openRuntimeLogPages.length + openDiffPages.length;

  function renderAuxPanel() {
    if (activeAuxLayer === "file") {
      return <CenterWorkspaceFileLayer onClose={closeFileLayer} path={activeFilePath} />;
    }
    if (activeAuxLayer === "file-change-diff" && activeDiffPage) {
      return (
        <CenterWorkspaceDiffLayer
          baselineRecordId={activeDiffPage.baselineRecordId}
          changeCount={activeDiffPage.changeCount}
          mode={activeDiffPage.mode}
          onClose={() => closeFileChangeDiffPage(fileChangeDiffPageKey(activeDiffPage))}
          recordId={activeDiffPage.recordId}
          subtitle={activeDiffPage.subtitle}
          title={activeDiffPage.title}
        />
      );
    }
    if (activeAuxLayer === "runtime-log" && activeRuntimeLogPage) {
      return (
        <section className="center-workspace__runtime-log-layer" aria-label="运行日志页">
          <RuntimeLogPanel target={activeRuntimeLogPage} onClose={() => closeRuntimeLogPage(runtimeLogPageKey(activeRuntimeLogPage))} />
        </section>
      );
    }
    return (
      <CenterWorkspaceResourceLauncherPanel
        onSelectFile={async () => {
          const selectedPath = await selectWorkspaceFile();
          if (selectedPath) {
            if (activeResourcePageId) {
              setOpenResourcePageIds((pages) => pages.filter((pageId) => pageId !== activeResourcePageId));
              setActiveResourcePageId("");
            }
            openFilePage(selectedPath);
          }
        }}
      />
    );
  }

  function openFileNavigator() {
    const pageId = `file-page:${Date.now().toString(36)}:${Math.random().toString(36).slice(2, 8)}`;
    setOpenResourcePageIds((pages) => [...pages, pageId]);
    setActiveResourcePageId(pageId);
    setLayer("resource-launcher");
    setPageLayerOpen(true);
  }

  function renderOpenObjectTabs() {
    if (!openPanelCount) {
      return null;
    }
    return (
      <>
        {openResourcePageIds.map((pageId) => {
          const active = layer === "resource-launcher" && pageId === activeResourcePageId;
          return (
            <div
              className={cn("chat-page-tabs__item", active && "chat-page-tabs__item--active", "center-workspace-file-tab")}
              key={pageId}
              title="新建文件"
            >
              <button
                aria-current={active ? "page" : undefined}
                className="center-workspace-file-tab__main"
                onClick={() => {
                  setActiveResourcePageId(pageId);
                  setLayer("resource-launcher");
                  setPageLayerOpen(true);
                }}
                type="button"
              >
                <FileText size={14} />
                <span>新建文件</span>
              </button>
              <button
                aria-label="关闭新建文件页"
                className="center-workspace-file-tab__close"
                onClick={() => closeResourcePage(pageId)}
                title="关闭新建文件页"
                type="button"
              >
                <X size={13} />
              </button>
            </div>
          );
        })}
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
                  setPageLayerOpen(true);
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
                  setPageLayerOpen(true);
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
                  setPageLayerOpen(true);
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
      </>
    );
  }

  const workspaceStyle = {
    "--center-chat-reveal-width": `${CENTER_CHAT_MIN_VISIBLE_WIDTH}px`,
    "--center-page-width": `${pageWidth}px`,
    "--center-split-resizer-width": `${CENTER_SPLIT_RESIZER_WIDTH}px`,
  } as CSSProperties;

  return (
    <section
      className={cn("center-workspace", pageLayerOpen && "center-workspace--page-open", resizingPage && "center-workspace--resizing")}
      aria-label="中心工作区"
      style={workspaceStyle}
    >
      <header className="center-workspace__head" aria-label="主会话页面控制">
        <div className="center-workspace__tool-row">
          <div className="center-workspace__main-side" aria-label="主页面">
            <div className="center-workspace__panel-actions" aria-label="左侧布局">
              {shellControls ? (
                <button
                  aria-label={shellControls.leftCollapsed ? "展开左侧项目栏" : "收起左侧项目栏"}
                  className="center-workspace__panel-button"
                  onClick={shellControls.toggleLeftPanel}
                  title={shellControls.leftCollapsed ? "展开左侧项目栏" : "收起左侧项目栏"}
                  type="button"
                >
                  {shellControls.leftCollapsed ? <PanelLeftOpen size={15} /> : <PanelLeftClose size={15} />}
                </button>
              ) : null}
            </div>

            <Tabs ariaLabel="主页面切换" className="center-workspace__primary-tabs">
              <TabButton
                active={!pageLayerOpen || layer === "chat"}
                className="center-workspace__tool-button"
                onClick={() => {
                  setLayer("chat");
                  setPageLayerOpen(false);
                }}
              >
                <Sparkles size={14} />
                <span>会话页</span>
              </TabButton>
              <TabButton
                className="center-workspace__tool-button"
                onClick={() => setWorkspaceView("creative")}
              >
                <Workflow size={14} />
                <span>图任务</span>
              </TabButton>
            </Tabs>
          </div>

          <div className="center-workspace__object-side" aria-label="文件页面">
            <Tabs ariaLabel="文件页面切换" className="center-workspace__object-tabs">
              {renderOpenObjectTabs()}
              <TabButton
                active={false}
                aria-label="打开文件"
                className="center-workspace__tool-button center-workspace__tool-button--icon center-workspace__add-file-tab"
                onClick={openFileNavigator}
                title="打开文件"
              >
                <Plus size={15} />
              </TabButton>
            </Tabs>

            <div className="center-workspace__tool-row-actions" aria-label="右侧布局">
              {shellControls ? (
                <button
                  aria-label={shellControls.rightCollapsed ? "展开右侧辅助栏" : "收起右侧辅助栏"}
                  className="center-workspace__panel-button"
                  onClick={shellControls.toggleRightPanel}
                  title={shellControls.rightCollapsed ? "展开右侧辅助栏" : "收起右侧辅助栏"}
                  type="button"
                >
                  {shellControls.rightCollapsed ? <PanelRightOpen size={15} /> : <PanelRightClose size={15} />}
                </button>
              ) : null}
            </div>
          </div>
        </div>
      </header>

      <div className="center-workspace__body" ref={bodyRef}>
        <div className="center-workspace__chat center-workspace__chat--base">
          <ChatPanel />
        </div>
        {pageLayerOpen ? (
          <div
            aria-label="调整会话页和文件页宽度"
            aria-orientation="vertical"
            aria-valuemax={CENTER_PAGE_MAX_WIDTH}
            aria-valuemin={CENTER_PAGE_MIN_WIDTH}
            aria-valuenow={pageWidth}
            className="center-workspace__split-resizer"
            onKeyDown={resizePageWithKeyboard}
            onPointerDown={startPageResize}
            role="separator"
            tabIndex={0}
            title="拖动调整文件页宽度"
          />
        ) : null}
        {pageLayerOpen ? (
          <section className="center-workspace__page-layer" aria-label={activeAuxLabel} ref={pageLayerRef}>
            {renderAuxPanel()}
          </section>
        ) : null}
      </div>
    </section>
  );
}
