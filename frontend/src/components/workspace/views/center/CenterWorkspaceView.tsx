"use client";

import { Edit3, FileText, RefreshCw, Save, Sparkles, Workflow, X } from "lucide-react";
import { useEffect, useState } from "react";

import { ChatPanel } from "@/components/chat/ChatPanel";
import { GraphTaskWorkspace } from "@/components/workspace/views/task-graph-workbench/GraphTaskWorkspace";
import { useAppStore } from "@/lib/store";

type CenterWorkspaceLayer = "chat" | "task-graph" | "file";

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

export function CenterWorkspaceView() {
  const {
    centerWorkspaceTarget,
    clearCenterWorkspaceTarget,
  } = useAppStore();
  const [layer, setLayer] = useState<CenterWorkspaceLayer>("chat");
  const [selectedGraphId, setSelectedGraphId] = useState("");
  const [openFilePath, setOpenFilePath] = useState("");

  useEffect(() => {
    if (!centerWorkspaceTarget) {
      return;
    }
    if (centerWorkspaceTarget.layer === "task-graph") {
      setLayer("task-graph");
      if (centerWorkspaceTarget.graph_id) {
        setSelectedGraphId(centerWorkspaceTarget.graph_id);
      }
    }
    if (centerWorkspaceTarget.layer === "file") {
      setOpenFilePath(centerWorkspaceTarget.file_path);
      setLayer("file");
    }
    clearCenterWorkspaceTarget();
  }, [centerWorkspaceTarget, clearCenterWorkspaceTarget]);

  function closeFileLayer() {
    setOpenFilePath("");
    setLayer("chat");
  }

  return (
    <section className="center-workspace" aria-label="中心工作区">
      <header className="center-workspace__tabs" aria-label="中心层级切换">
        <button
          className={layer === "chat" ? "chat-page-tabs__item chat-page-tabs__item--active" : "chat-page-tabs__item"}
          onClick={() => setLayer("chat")}
          type="button"
        >
          <Sparkles size={14} />
          <span>会话层</span>
        </button>
        <button
          className={layer === "task-graph" ? "chat-page-tabs__item chat-page-tabs__item--active" : "chat-page-tabs__item"}
          onClick={() => setLayer("task-graph")}
          type="button"
        >
          <Workflow size={14} />
          <span>图任务层</span>
        </button>
        {openFilePath ? (
          <button
            className={layer === "file" ? "chat-page-tabs__item chat-page-tabs__item--active" : "chat-page-tabs__item"}
            onClick={() => setLayer("file")}
            title={openFilePath}
            type="button"
          >
            <FileText size={14} />
            <span>{compactFileName(openFilePath)}</span>
          </button>
        ) : null}
      </header>

      {layer === "chat" ? (
        <div className="center-workspace__chat">
          <ChatPanel />
        </div>
      ) : layer === "task-graph" ? (
        <div className="center-workspace__graph-layer">
          <GraphTaskWorkspace
            onSelectedGraphChange={setSelectedGraphId}
            requestedGraphId={selectedGraphId}
          />
        </div>
      ) : (
        <CenterWorkspaceFileLayer onClose={closeFileLayer} path={openFilePath} />
      )}
    </section>
  );
}
