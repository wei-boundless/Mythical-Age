"use client";

import type { Dispatch, SetStateAction } from "react";
import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Eye,
  FileText,
  FolderTree,
  Maximize2,
  MessageSquare,
  Minimize2,
  PencilLine,
  Save,
  Search,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type {
  HumanEdgeControlView,
  HumanEdgeDecisionKind,
  SessionSummary,
  WritingChapterAction,
} from "@/lib/api";

type FileTreeNode = {
  children: FileTreeNode[];
  kind: "directory" | "file" | string;
  name: string;
  path: string;
};

type FileEditorMode = "edit" | "preview";
type AssetTab = "library" | "artifacts";

type NodeRuntimeCard = {
  artifactCount: number;
  detail: string;
  nodeId: string;
  scopeLabel: string;
  session: SessionSummary | null;
  status: string;
  title: string;
  updatedAt: unknown;
};

type WritingChapterDeskProps = {
  action: string;
  artifactSearch: string;
  artifacts: Array<Record<string, unknown>>;
  assetTab: AssetTab;
  chapterFiles: FileTreeNode[];
  chapterActions: WritingChapterAction[];
  decisionHistory: Array<Record<string, unknown>>;
  fileContent: string;
  fileEditorMode: FileEditorMode;
  fileSearch: string;
  filteredArtifacts: Array<Record<string, unknown>>;
  flatFiles: FileTreeNode[];
  focusMode: boolean;
  newFileContent: string;
  newFilePath: string;
  nextChapterFile: FileTreeNode | null;
  nodeCards: NodeRuntimeCard[];
  previousChapterFile: FileTreeNode | null;
  selectedFileName: string;
  selectedFilePath: string;
  selectedHumanControl: HumanEdgeControlView | null;
  selectedNode: NodeRuntimeCard | null;
  visibleChapterFiles: FileTreeNode[];
  loadFile: (path: string) => Promise<void>;
  openChapterAction: (action: WritingChapterAction) => void;
  openSession: (session: SessionSummary | null) => Promise<void>;
  saveSelectedFile: () => Promise<void>;
  setArtifactSearch: Dispatch<SetStateAction<string>>;
  setAssetTab: Dispatch<SetStateAction<AssetTab>>;
  setFileContent: Dispatch<SetStateAction<string>>;
  setFileEditorMode: Dispatch<SetStateAction<FileEditorMode>>;
  setFileSearch: Dispatch<SetStateAction<string>>;
  setFocusMode: Dispatch<SetStateAction<boolean>>;
  setNewFileContent: Dispatch<SetStateAction<string>>;
  setNewFilePath: Dispatch<SetStateAction<string>>;
  setSelectedNodeId: Dispatch<SetStateAction<string>>;
  writeNewFile: () => Promise<void>;
};

const FILE_PATH_TEMPLATES = [
  { label: "任务简报", path: "input/brief.md" },
  { label: "世界观", path: "world/world.md" },
  { label: "角色表", path: "characters/characters.md" },
  { label: "大纲", path: "outline/outline.md" },
  { label: "正文 001", path: "chapters/chapter-001.md" },
  { label: "审校记录", path: "review/review-notes.md" },
] as const;

function classNames(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

function stringValue(value: unknown, fallback = "") {
  const text = String(value ?? "").trim();
  return text || fallback;
}

function numberValue(value: unknown, fallback = 0) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
}

function timestampValue(value: unknown) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) return 0;
  return numeric > 10_000_000_000 ? numeric : numeric * 1000;
}

function timestampLabel(value: unknown) {
  const numeric = timestampValue(value);
  if (!numeric) return "-";
  return new Date(numeric).toLocaleString("zh-CN", {
    hour12: false,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function statusLabel(value: unknown) {
  const status = stringValue(value, "idle").toLowerCase();
  const labels: Record<string, string> = {
    idle: "未启动",
    created: "已创建",
    pending: "等待中",
    queued: "排队中",
    ready: "就绪",
    running: "运行中",
    dispatching: "派发中",
    blocked: "阻塞",
    paused: "已暂停",
    failed: "失败",
    error: "错误",
    completed: "已完成",
    done: "已完成",
    success: "成功",
    stopped: "已停止",
  };
  return labels[status] ?? status;
}

function controlTitle(control: HumanEdgeControlView) {
  return `${control.source_node_id || "上游"} -> ${control.target_node_id || "下游"}`;
}

function writingDecisionLabel(decision: HumanEdgeDecisionKind) {
  if (decision === "pass") return "通过本章";
  if (decision === "revise") return "退稿给写手";
  return "采用我的改写稿";
}

export function WritingChapterDesk({
  action,
  artifactSearch,
  artifacts,
  assetTab,
  chapterFiles,
  chapterActions,
  decisionHistory,
  fileContent,
  fileEditorMode,
  fileSearch,
  filteredArtifacts,
  flatFiles,
  focusMode,
  newFileContent,
  newFilePath,
  nextChapterFile,
  nodeCards,
  previousChapterFile,
  selectedFileName,
  selectedFilePath,
  selectedHumanControl,
  selectedNode,
  visibleChapterFiles,
  loadFile,
  openChapterAction,
  openSession,
  saveSelectedFile,
  setArtifactSearch,
  setAssetTab,
  setFileContent,
  setFileEditorMode,
  setFileSearch,
  setFocusMode,
  setNewFileContent,
  setNewFilePath,
  setSelectedNodeId,
  writeNewFile,
}: WritingChapterDeskProps) {
  const visibleActions: Array<WritingChapterAction & { fallback?: boolean }> = chapterActions.length
    ? chapterActions
    : (["pass", "revise", "replace"] as HumanEdgeDecisionKind[]).map((decision) => ({
        action: decision === "pass" ? "approve" : decision === "revise" ? "request_revision" : "replace_with_user_text",
        control_id: "",
        decision,
        edge_id: "",
        enabled: false,
        fallback: true,
        label: writingDecisionLabel(decision),
      }));

  return (
    <div className={classNames("graph-foreground-session-screen", focusMode && "graph-foreground-session-screen--focus")}>
      <aside className="graph-foreground-chapter-rail" aria-label="章节文件">
        <header>
          <div>
            <span>章节</span>
            <strong>{chapterFiles.length || flatFiles.length} 个文件</strong>
          </div>
          <FileText size={15} />
        </header>
        <label className="graph-foreground-search">
          <Search size={14} />
          <input onChange={(event) => setFileSearch(event.target.value)} placeholder="搜索章节或文件" value={fileSearch} />
        </label>
        <div className="graph-foreground-chapter-list">
          {visibleChapterFiles.map((file) => (
            <button
              className={selectedFilePath === file.path ? "graph-foreground-chapter-row graph-foreground-chapter-row--active" : "graph-foreground-chapter-row"}
              key={file.path}
              onClick={() => void loadFile(file.path)}
              type="button"
            >
              <strong>{file.name}</strong>
              <small>{file.path}</small>
            </button>
          ))}
          {!chapterFiles.length && !flatFiles.length ? <div className="boundary-empty">正式库还没有可查看文件。</div> : null}
          {(chapterFiles.length || flatFiles.length) && !visibleChapterFiles.length ? <div className="boundary-empty">没有匹配的章节或文件。</div> : null}
        </div>
      </aside>

      <section className="graph-foreground-assets graph-foreground-assets--session" aria-label="写作生产区">
        <header>
          <div>
            <span>写作台</span>
            <strong>{assetTab === "library" ? "正文阅读" : "产物来源"}</strong>
          </div>
          <div className="graph-foreground-asset-tabs" role="tablist" aria-label="项目资产页签">
            <button aria-selected={assetTab === "library"} className={assetTab === "library" ? "graph-foreground-asset-tabs__active" : undefined} onClick={() => setAssetTab("library")} type="button">
              <BookOpen size={13} />
              正文
            </button>
            <button aria-selected={assetTab === "artifacts"} className={assetTab === "artifacts" ? "graph-foreground-asset-tabs__active" : undefined} onClick={() => setAssetTab("artifacts")} type="button">
              <FolderTree size={13} />
              产物来源
            </button>
          </div>
        </header>
        {assetTab === "library" ? (
          <div className="graph-foreground-library__body graph-foreground-library__body--session">
            <article className="graph-foreground-library__editor graph-foreground-reader-stage">
              <div className="graph-foreground-reader-head">
                <div>
                  <span>正文阅读</span>
                  <strong>{selectedFileName || "选择章节开始阅读"}</strong>
                  <small>{selectedFilePath || "从左侧章节列表打开项目文件"}</small>
                </div>
                <div className="graph-foreground-reader-nav" aria-label="章节切换">
                  <button disabled={!previousChapterFile} onClick={() => previousChapterFile && void loadFile(previousChapterFile.path)} type="button">
                    <ChevronLeft size={14} />
                    <span>上一章</span>
                  </button>
                  <button disabled={!nextChapterFile} onClick={() => nextChapterFile && void loadFile(nextChapterFile.path)} type="button">
                    <span>下一章</span>
                    <ChevronRight size={14} />
                  </button>
                  <button aria-pressed={focusMode} onClick={() => setFocusMode((current) => !current)} type="button">
                    {focusMode ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
                    <span>{focusMode ? "退出专注" : "专注阅读"}</span>
                  </button>
                </div>
              </div>

              <div className="graph-foreground-reader-tools">
                <div className="graph-foreground-mode-switch" role="group" aria-label="文件显示模式">
                  <button aria-pressed={fileEditorMode === "preview"} className={fileEditorMode === "preview" ? "graph-foreground-mode-switch__active" : undefined} onClick={() => setFileEditorMode("preview")} type="button">
                    <Eye size={13} />
                    阅读
                  </button>
                  <button aria-pressed={fileEditorMode === "edit"} className={fileEditorMode === "edit" ? "graph-foreground-mode-switch__active" : undefined} onClick={() => setFileEditorMode("edit")} type="button">
                    <PencilLine size={13} />
                    编辑
                  </button>
                </div>
                <button disabled={!selectedFilePath.trim() || action === "save-file"} onClick={() => void saveSelectedFile()} type="button">
                  <Save size={14} />
                  <span>{action === "save-file" ? "保存中" : "保存文件"}</span>
                </button>
              </div>

              <div className="graph-foreground-chapter-actions graph-foreground-chapter-actions--sticky" aria-label="章节审核动作">
                <div>
                  <span>章节审核</span>
                  <strong>{selectedHumanControl ? controlTitle(selectedHumanControl) : "当前无可处理边"}</strong>
                </div>
                <div>
                  {visibleActions.map((chapterAction) => {
                    const kind = chapterAction.decision;
                    const enabled = Boolean(chapterAction.enabled && chapterAction.control_id);
                    return (
                      <button disabled={!enabled || action === "human-edge-decision"} key={`${chapterAction.control_id || "fallback"}:${kind}`} onClick={() => openChapterAction(chapterAction)} type="button">
                        {kind === "replace" ? <PencilLine size={13} /> : kind === "revise" ? <AlertTriangle size={13} /> : <CheckCircle2 size={13} />}
                        <span>{chapterAction.label || writingDecisionLabel(kind)}</span>
                      </button>
                    );
                  })}
                </div>
              </div>

              {fileEditorMode === "edit" ? (
                <textarea className="graph-foreground-file-editor-textarea" onChange={(event) => setFileContent(event.target.value)} placeholder="选择文件后编辑内容" value={fileContent} />
              ) : (
                <div className="graph-foreground-file-preview graph-foreground-file-preview--reader markdown">
                  {fileContent.trim() ? (
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {fileContent}
                    </ReactMarkdown>
                  ) : (
                    <div className="graph-foreground-reader-empty">
                      <FileText size={22} />
                      <strong>选择一章开始阅读</strong>
                      <span>左侧会列出正式库里的章节或文件。</span>
                    </div>
                  )}
                </div>
              )}
            </article>

            <div className="graph-foreground-library__writer">
              <label>
                <span>写入正式库</span>
                <input onChange={(event) => setNewFilePath(event.target.value)} placeholder="input/brief.md" value={newFilePath} />
              </label>
              <div className="graph-foreground-template-grid">
                {FILE_PATH_TEMPLATES.map((template) => (
                  <button className={newFilePath === template.path ? "graph-foreground-template-grid__active" : undefined} key={template.path} onClick={() => setNewFilePath(template.path)} type="button">
                    <strong>{template.label}</strong>
                    <small>{template.path}</small>
                  </button>
                ))}
              </div>
              <textarea onChange={(event) => setNewFileContent(event.target.value)} placeholder="输入要写入项目正式库的内容" value={newFileContent} />
              <button disabled={!newFilePath.trim() || action === "write-file"} onClick={() => void writeNewFile()} type="button">
                <FileText size={14} />
                <span>{action === "write-file" ? "写入中" : "写入正式库"}</span>
              </button>
            </div>
          </div>
        ) : (
          <div className="graph-foreground-artifacts-pane">
            <label className="graph-foreground-search">
              <Search size={14} />
              <input onChange={(event) => setArtifactSearch(event.target.value)} placeholder="搜索产物来源" value={artifactSearch} />
            </label>
            <div className="graph-foreground-artifact-list">
              {filteredArtifacts.slice(0, 80).map((artifact) => {
                const path = stringValue(artifact.path);
                return (
                  <button disabled={!path} key={stringValue(artifact.artifact_id, path)} onClick={() => path && void loadFile(path)} type="button">
                    <strong>{stringValue(artifact.name, path || "未命名产物")}</strong>
                    <small>{path || "没有文件路径"}</small>
                    <span>{numberValue(artifact.size)} bytes · {timestampLabel(artifact.updated_at)}</span>
                  </button>
                );
              })}
              {!artifacts.length ? <div className="boundary-empty">写作节点产生的文件会出现在这里。</div> : null}
              {artifacts.length && !filteredArtifacts.length ? <div className="boundary-empty">没有匹配的产物来源。</div> : null}
            </div>
          </div>
        )}
      </section>

      <aside className="graph-foreground-session-side" aria-label="节点会话和产物">
        <section className="graph-foreground-panel graph-foreground-session-card">
          <header>
            <div>
              <span>节点会话</span>
              <strong>{selectedNode?.title || "选择节点"}</strong>
            </div>
            <MessageSquare size={15} />
          </header>
          <div className="graph-foreground-node-list">
            {nodeCards.map((node) => (
              <button
                aria-current={selectedNode?.nodeId === node.nodeId ? "true" : undefined}
                className={classNames("graph-foreground-node-list-row", selectedNode?.nodeId === node.nodeId && "graph-foreground-node-list-row--active")}
                key={node.nodeId}
                onClick={() => setSelectedNodeId(node.nodeId)}
                type="button"
              >
                <span>{statusLabel(node.status)}</span>
                <strong>{node.title}</strong>
                <small>{node.session ? `${node.session.message_count ?? 0} 条消息` : "暂无会话"}</small>
              </button>
            ))}
            {!nodeCards.length ? <div className="boundary-empty">暂无节点会话。</div> : null}
          </div>
          <button disabled={!selectedNode?.session} onClick={() => void openSession(selectedNode?.session ?? null)} type="button">
            <MessageSquare size={14} />
            <span>{selectedNode?.session ? "打开节点会话" : "暂无节点会话"}</span>
          </button>
        </section>

        <section className="graph-foreground-panel graph-foreground-session-card">
          <header>
            <div>
              <span>产物来源</span>
              <strong>{artifacts.length} 个文件</strong>
            </div>
            <FolderTree size={15} />
          </header>
          <div className="graph-foreground-artifact-list graph-foreground-artifact-list--side">
            {filteredArtifacts.slice(0, 30).map((artifact) => {
              const path = stringValue(artifact.path);
              return (
                <button disabled={!path} key={stringValue(artifact.artifact_id, path)} onClick={() => path && void loadFile(path)} type="button">
                  <strong>{stringValue(artifact.name, path || "未命名产物")}</strong>
                  <small>{path || "没有文件路径"}</small>
                </button>
              );
            })}
            {!artifacts.length ? <div className="boundary-empty">写作节点产物会出现在这里。</div> : null}
          </div>
        </section>
        <section className="graph-foreground-panel graph-foreground-session-card">
          <header>
            <div>
              <span>审核记录</span>
              <strong>{decisionHistory.length} 条记录</strong>
            </div>
            <FolderTree size={15} />
          </header>
          <div className="graph-foreground-human-history">
            {decisionHistory.slice(0, 12).map((item) => (
              <article key={stringValue(item.decision_id, `${item.edge_id}-${item.created_at}`)}>
                <strong>{stringValue(item.decision, "decision")} · {stringValue(item.edge_id, "edge")}</strong>
                <span>{stringValue(item.status, "submitted")} · {timestampLabel(item.updated_at ?? item.created_at)}</span>
              </article>
            ))}
            {!decisionHistory.length ? <div className="boundary-empty">章节审核记录会显示在这里。</div> : null}
          </div>
        </section>
      </aside>
    </div>
  );
}
