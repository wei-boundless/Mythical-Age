"use client";

import { Edit3, FileText, RefreshCw, Save, Sparkles, Terminal, Workflow, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { ChatPanel } from "@/components/chat/ChatPanel";
import { WorkspaceModeSwitcher } from "@/components/layout/WorkspaceModeSwitcher";
import { RuntimeLogPanel, type RuntimeLogTarget } from "@/components/layout/RuntimeLogPanel";
import { useAppStore } from "@/lib/store";
import { cn } from "@/ui/classNames";
import { TabButton, Tabs } from "@/ui/Tabs";

type CenterWorkspaceLayer = "chat" | "file" | "runtime-log";
const GENERAL_TASK_ENVIRONMENT_ID = "env.general.workspace";

function compactFileName(path: string) {
  const normalized = path.replace(/\\/g, "/");
  const parts = normalized.split("/");
  return parts[parts.length - 1] || path || "文件";
}

function runtimeLogPageKey(target: RuntimeLogTarget) {
  return `${target.scope}:${target.runId}`;
}

function runtimeLogPageTitle(target: RuntimeLogTarget) {
  const title = String(target.title || "").trim();
  if (title) return title.length > 28 ? `${title.slice(0, 28)}...` : title;
  return target.scope === "turn_run" ? "TurnRun Log" : "TaskRun Log";
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
    } else if (centerWorkspaceTarget.layer === "runtime-log") {
      openRuntimeLogPage({
        scope: centerWorkspaceTarget.scope,
        runId: centerWorkspaceTarget.run_id,
        title: centerWorkspaceTarget.title,
        subtitle: centerWorkspaceTarget.subtitle,
      });
    }
    clearCenterWorkspaceTarget();
  }, [centerWorkspaceTarget, clearCenterWorkspaceTarget, openFilePage, openRuntimeLogPage]);

  function closeFileLayer() {
    closeFilePage(activeFilePath);
  }

  const activeRuntimeLogPage = openRuntimeLogPages.find((page) => runtimeLogPageKey(page) === activeRuntimeLogKey) ?? null;

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
        </Tabs>
        <WorkspaceModeSwitcher ariaLabel="切换当前会话任务环境" className="center-workspace__environment-switcher" />
      </header>

      {layer === "chat" ? (
        <div className="center-workspace__chat">
          <ChatPanel />
        </div>
      ) : layer === "file" ? (
        <CenterWorkspaceFileLayer onClose={closeFileLayer} path={activeFilePath} />
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
