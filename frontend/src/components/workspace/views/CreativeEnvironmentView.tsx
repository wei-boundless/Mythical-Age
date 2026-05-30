"use client";

import { useEffect, useMemo, useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  FileText,
  FolderOpen,
  GitBranch,
  LibraryBig,
  MessageSquare,
  PenLine,
  Plus,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";

import { WorkbenchShell } from "@/components/layout/WorkbenchShell";
import { WorkspaceModeSwitcher } from "@/components/layout/WorkspaceModeSwitcher";
import { CenterWorkspaceView } from "@/components/workspace/views/center/CenterWorkspaceView";
import {
  getCodeEnvironment,
  getCodeEnvironmentGitStatus,
  getCodeEnvironmentWorkspaceTree,
  type CodeEnvironmentGitStatus,
  type CodeEnvironmentStatus,
  type CodeEnvironmentWorkspaceTree,
} from "@/lib/api";
import { useAppStore } from "@/lib/store";

type CreativeItem = {
  id: string;
  title: string;
  kind: string;
  status: "draft" | "approved" | "review" | "locked";
  words?: number;
  path?: string;
};

type CreativeSection = {
  id: string;
  title: string;
  summary: string;
  items: CreativeItem[];
};

const CREATIVE_SECTIONS: CreativeSection[] = [
  {
    id: "brief",
    title: "作品总览",
    summary: "项目目标、题材、字数与当前运行",
    items: [
      { id: "project_seed", title: "项目简介", kind: "启动资料", status: "approved", path: "durable_memory/index/MEMORY.md" },
      { id: "run_plan", title: "创作计划", kind: "目标与节奏", status: "draft" },
    ],
  },
  {
    id: "bible",
    title: "设定资料",
    summary: "世界观、角色、势力、地点",
    items: [
      { id: "world_bible", title: "世界观资料库", kind: "世界观", status: "review" },
      { id: "character_bible", title: "角色资料库", kind: "角色", status: "draft" },
      { id: "faction_bible", title: "势力与地点", kind: "资料", status: "draft" },
    ],
  },
  {
    id: "outline",
    title: "大纲结构",
    summary: "主线、卷纲、章节规划",
    items: [
      { id: "master_outline", title: "总纲", kind: "大纲", status: "draft" },
      { id: "volume_001", title: "第一卷卷纲", kind: "卷纲", status: "draft" },
    ],
  },
  {
    id: "chapters",
    title: "章节稿件",
    summary: "正文、审稿、返修",
    items: [
      { id: "chapter_001", title: "第 1 章", kind: "正文", status: "draft", words: 2000 },
      { id: "chapter_002", title: "第 2 章", kind: "正文", status: "draft", words: 2000 },
      { id: "chapter_review", title: "章节审核意见", kind: "审核", status: "review" },
    ],
  },
];

function statusLabel(status: CreativeItem["status"]) {
  if (status === "approved") return "已通过";
  if (status === "review") return "待审核";
  if (status === "locked") return "已锁定";
  return "草稿";
}

function formatSessionTime(timestamp: number) {
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

function CreativeLeftPanel({
  selectedItemId,
  onSelectItem,
}: {
  selectedItemId: string;
  onSelectItem: (item: CreativeItem) => void;
}) {
  const { createNewSession, currentSessionId, sessions, selectSession } = useAppStore();
  const [openSections, setOpenSections] = useState<Record<string, boolean>>({
    brief: true,
    bible: true,
    outline: true,
    chapters: true,
    sessions: false,
  });
  const visibleSessions = [...sessions].sort((a, b) => b.updated_at - a.updated_at).slice(0, 10);

  function toggle(sectionId: string) {
    setOpenSections((current) => ({ ...current, [sectionId]: !current[sectionId] }));
  }

  return (
    <aside className="workbench-resource-panel creative-workspace-left" aria-label="创作任务环境">
      <header className="workbench-panel-head">
        <div>
          <strong>任务环境</strong>
          <span>环境集合</span>
        </div>
        <WorkspaceModeSwitcher />
      </header>

      <section className="creative-project-card">
        <span>当前作品</span>
        <strong>洪荒时代</strong>
        <small>长篇连载 · 目标 100 万字 · 每章 2000 字</small>
      </section>

      <div className="creative-section-list">
        {CREATIVE_SECTIONS.map((section) => (
          <section className="creative-section" key={section.id}>
            <button className="creative-section__head" onClick={() => toggle(section.id)} type="button">
              {openSections[section.id] ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              <div>
                <strong>{section.title}</strong>
                <span>{section.summary}</span>
              </div>
              <em>{section.items.length}</em>
            </button>
            {openSections[section.id] ? (
              <div className="creative-file-list">
                {section.items.map((item) => (
                  <button
                    className={selectedItemId === item.id ? "creative-file-row creative-file-row--active" : "creative-file-row"}
                    key={item.id}
                    onClick={() => onSelectItem(item)}
                    type="button"
                  >
                    <FileText size={14} />
                    <span>{item.title}</span>
                    <small>{statusLabel(item.status)}</small>
                  </button>
                ))}
              </div>
            ) : null}
          </section>
        ))}
      </div>

      <section className="creative-section creative-session-compact">
        <button className="creative-section__head" onClick={() => toggle("sessions")} type="button">
          {openSections.sessions ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <div>
            <strong>会话</strong>
            <span>通用折叠管理</span>
          </div>
          <Plus size={14} onClick={(event) => {
            event.stopPropagation();
            void createNewSession();
          }} />
        </button>
        {openSections.sessions ? (
          <div className="creative-session-list">
            {visibleSessions.map((session) => (
              <button
                className={session.id === currentSessionId ? "creative-session-row creative-session-row--active" : "creative-session-row"}
                key={session.id}
                onClick={() => void selectSession(session.id)}
                type="button"
              >
                <MessageSquare size={13} />
                <span>{session.title || "未命名会话"}</span>
                <small>{formatSessionTime(session.updated_at)}</small>
              </button>
            ))}
          </div>
        ) : null}
      </section>
    </aside>
  );
}

function CreativeRightPanel({
  environment,
  gitStatus,
  loading,
  selectedItem,
  workspaceTree,
  onRefresh,
}: {
  environment: CodeEnvironmentStatus | null;
  gitStatus: CodeEnvironmentGitStatus | null;
  loading: boolean;
  selectedItem: CreativeItem;
  workspaceTree: CodeEnvironmentWorkspaceTree | null;
  onRefresh: () => void;
}) {
  const changeItems = gitStatus?.items ?? [];
  const projectRoot = environment?.pi.workspace_root || workspaceTree?.root_path || "未检测";

  return (
    <aside className="workbench-right-panel creative-workspace-right" aria-label="创作详情">
      <header className="workbench-panel-head workbench-panel-head--right">
        <div>
          <strong>作品详情</strong>
          <span>{selectedItem.title}</span>
        </div>
        <button className="workbench-icon-button" disabled={loading} onClick={onRefresh} type="button">
          <RefreshCw size={15} />
        </button>
      </header>

      <div className="creative-right-body">
        <section className="creative-detail-card creative-detail-card--selected">
          <header>
            <FileText size={15} />
            <strong>{selectedItem.title}</strong>
            <em>{statusLabel(selectedItem.status)}</em>
          </header>
          <dl>
            <div><dt>类型</dt><dd>{selectedItem.kind}</dd></div>
            <div><dt>目标</dt><dd>{selectedItem.words ? `${selectedItem.words} 字` : "随图任务生成"}</dd></div>
            <div><dt>编辑</dt><dd>{selectedItem.path ? "可打开源文档" : "等待产物生成"}</dd></div>
          </dl>
          <div className="creative-detail-actions">
            <button type="button"><PenLine size={14} />编辑</button>
            <button type="button"><CheckCircle2 size={14} />标记审核</button>
          </div>
        </section>

        <section className="creative-detail-card">
          <header>
            <ShieldCheck size={15} />
            <strong>创作沙盒</strong>
            <em>{environment?.pi.enabled ? "已配置" : "诊断"}</em>
          </header>
          <dl>
            <div><dt>环境</dt><dd>env.creation.writing</dd></div>
            <div><dt>项目根</dt><dd title={projectRoot}>{projectRoot}</dd></div>
            <div><dt>写入策略</dt><dd>作品文件与图产物隔离</dd></div>
          </dl>
        </section>

        <section className="creative-detail-card">
          <header>
            <GitBranch size={15} />
            <strong>Git 管理树</strong>
            <em>{gitStatus?.branch || "未读取"}</em>
          </header>
          {gitStatus?.available ? (
            <div className="creative-git-list">
              {changeItems.length ? changeItems.slice(0, 12).map((item) => (
                <div className="creative-git-row" key={`${item.status}:${item.path}`}>
                  <span>{item.status}</span>
                  <strong title={item.path}>{item.path}</strong>
                </div>
              )) : <div className="creative-empty">当前工作树无变更。</div>}
            </div>
          ) : (
            <div className="creative-empty">{gitStatus?.error || "Git 状态未加载。"}</div>
          )}
        </section>

        <section className="creative-detail-card">
          <header>
            <FolderOpen size={15} />
            <strong>项目树</strong>
            <em>{workspaceTree ? `${workspaceTree.total_entries} 项` : "未加载"}</em>
          </header>
          <div className="creative-tree-summary">
            {(workspaceTree?.tree.children ?? []).slice(0, 8).map((node) => (
              <span key={`${node.kind}:${node.path}`}>{node.name}</span>
            ))}
          </div>
        </section>
      </div>
    </aside>
  );
}

export function CreativeEnvironmentView() {
  const { loadInspectorFile } = useAppStore();
  const [selectedItemId, setSelectedItemId] = useState("project_seed");
  const [environment, setEnvironment] = useState<CodeEnvironmentStatus | null>(null);
  const [workspaceTree, setWorkspaceTree] = useState<CodeEnvironmentWorkspaceTree | null>(null);
  const [gitStatus, setGitStatus] = useState<CodeEnvironmentGitStatus | null>(null);
  const [loading, setLoading] = useState(false);

  const selectedItem = useMemo(() => {
    return CREATIVE_SECTIONS.flatMap((section) => section.items).find((item) => item.id === selectedItemId)
      ?? CREATIVE_SECTIONS[0].items[0];
  }, [selectedItemId]);

  async function loadEnvironment() {
    setLoading(true);
    try {
      const [nextEnvironment, nextTree, nextGitStatus] = await Promise.all([
        getCodeEnvironment(),
        getCodeEnvironmentWorkspaceTree({ maxDepth: 4, maxEntries: 2000 }),
        getCodeEnvironmentGitStatus(),
      ]);
      setEnvironment(nextEnvironment);
      setWorkspaceTree(nextTree);
      setGitStatus(nextGitStatus);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadEnvironment();
  }, []);

  function selectItem(item: CreativeItem) {
    setSelectedItemId(item.id);
    if (item.path) {
      void loadInspectorFile(item.path).catch(() => undefined);
    }
  }

  return (
    <WorkbenchShell
      className="creative-environment-shell"
      leftPanel={<CreativeLeftPanel selectedItemId={selectedItemId} onSelectItem={selectItem} />}
      leftPanelLabel="创作任务环境"
      rightPanel={(
        <CreativeRightPanel
          environment={environment}
          gitStatus={gitStatus}
          loading={loading}
          onRefresh={() => void loadEnvironment()}
          selectedItem={selectedItem}
          workspaceTree={workspaceTree}
        />
      )}
      rightPanelLabel="作品详情"
    >
      <section className="workbench-view-host creative-center-host" aria-label="创作会话">
        <div className="creative-center-banner">
          <div>
            <span>创作环境</span>
            <strong>围绕作品文件推进任务</strong>
          </div>
          <div>
            <LibraryBig size={15} />
            <span>{selectedItem.title}</span>
          </div>
        </div>
        <CenterWorkspaceView />
      </section>
    </WorkbenchShell>
  );
}
