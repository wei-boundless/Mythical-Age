"use client";

import { Edit3, FileText, RefreshCw, Save, Sparkles, Workflow, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { ChatPanel } from "@/components/chat/ChatPanel";
import { WorkspaceModeSwitcher } from "@/components/layout/WorkspaceModeSwitcher";
import { useAppStore } from "@/lib/store";

type CenterWorkspaceLayer = "chat" | "file";
const GENERAL_TASK_ENVIRONMENT_ID = "env.general.workspace";

function compactFileName(path: string) {
  const normalized = path.replace(/\\/g, "/");
  const parts = normalized.split("/");
  return parts[parts.length - 1] || path || "文件";
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
    }
    clearCenterWorkspaceTarget();
  }, [centerWorkspaceTarget, clearCenterWorkspaceTarget, openFilePage]);

  function closeFileLayer() {
    closeFilePage(activeFilePath);
  }

  return (
    <section className="center-workspace" aria-label="中心工作区">
      <header className="center-workspace__head" aria-label="主会话页面控制">
        <nav className="center-workspace__tabs" aria-label="中心层级切换">
          <button
            className={layer === "chat" ? "chat-page-tabs__item chat-page-tabs__item--active" : "chat-page-tabs__item"}
            onClick={() => setLayer("chat")}
            type="button"
          >
            <Sparkles size={14} />
            <span>会话层</span>
          </button>
          <button
            className="chat-page-tabs__item"
            onClick={() => setWorkspaceView("creative")}
            type="button"
          >
            <Workflow size={14} />
            <span>图任务层</span>
          </button>
          {openFilePaths.map((path) => {
            const active = layer === "file" && path === activeFilePath;
            return (
              <div
                className={active ? "chat-page-tabs__item chat-page-tabs__item--active center-workspace-file-tab" : "chat-page-tabs__item center-workspace-file-tab"}
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
        </nav>
        <WorkspaceModeSwitcher ariaLabel="切换当前会话任务环境" className="center-workspace__environment-switcher" />
      </header>

      {layer === "chat" ? (
        <div className="center-workspace__chat">
          <ChatPanel />
        </div>
      ) : (
        <CenterWorkspaceFileLayer onClose={closeFileLayer} path={activeFilePath} />
      )}
    </section>
  );
}
