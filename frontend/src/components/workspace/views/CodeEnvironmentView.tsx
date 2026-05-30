"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Cpu,
  FileCode2,
  GitBranch,
  MonitorCog,
  RefreshCw,
  ShieldCheck,
  TerminalSquare,
  Wrench,
} from "lucide-react";

import { ChatPanel } from "@/components/chat/ChatPanel";
import { WorkbenchShell } from "@/components/layout/WorkbenchShell";
import {
  getCodeEnvironment,
  getCodeEnvironmentGitStatus,
  getCodeEnvironmentWorkspaceTree,
  getPiSidecarStatus,
  runPiSidecarReadOnlyCommand,
  startPiSidecar,
  stopPiSidecar,
  type CodeEnvironmentGitStatus,
  type CodeEnvironmentStatus,
  type CodeEnvironmentWorkspaceTree,
  type PiSidecarCommandResponse,
  type PiSidecarStatus,
} from "@/lib/api";

function hostConfig() {
  const config = globalThis.__MYTHICAL_AGENT_HOST__ || (typeof window !== "undefined" ? window.mythicalAgentHost?.getConfig() : undefined);
  return {
    mode: config?.hostMode === "desktop" ? "desktop" : "web",
    localRuntimeAvailable: Boolean(config?.localRuntimeAvailable),
    codeEnvironmentHostAvailable: Boolean(config?.codeEnvironmentHostAvailable),
  } as const;
}

function environmentStatusLabel(environment: CodeEnvironmentStatus | null) {
  if (!environment) return "检测中";
  if (!environment.pi.enabled) return "未启用";
  if (environment.pi.mode === "sidecar_running") return "运行中";
  if (environment.pi.mode === "sidecar_ready") return "就绪";
  if (environment.pi.mode === "error") return "异常";
  if (environment.pi.cli_built) return "可连接";
  return "诊断";
}

function diagnosticLabel(level: string) {
  if (level === "error") return "错误";
  if (level === "warning") return "警告";
  return "信息";
}

function DevelopmentRightPanel({
  commandResult,
  environment,
  error,
  gitStatus,
  loading,
  sidecar,
  sidecarLoading,
  workspaceTree,
  onRefresh,
  onRunSidecarAction,
}: {
  commandResult: PiSidecarCommandResponse | null;
  environment: CodeEnvironmentStatus | null;
  error: string;
  gitStatus: CodeEnvironmentGitStatus | null;
  loading: boolean;
  sidecar: PiSidecarStatus | null;
  sidecarLoading: boolean;
  workspaceTree: CodeEnvironmentWorkspaceTree | null;
  onRefresh: () => void;
  onRunSidecarAction: (action: "start" | "stop" | "get_state" | "get_available_models") => void;
}) {
  const diagnostics = environment?.pi.diagnostics ?? [];
  const gitItems = gitStatus?.items ?? [];
  const running = Boolean(sidecar?.running);
  const projectReady = Boolean(environment?.pi.enabled);
  const sidecarReady = Boolean(environment?.pi.available && environment.pi.cli_built && environment.pi.sidecar_enabled);
  const projectRoot = environment?.pi.workspace_root || workspaceTree?.root_path || "未检测";

  return (
    <aside className="workbench-right-panel development-right-panel" aria-label="开发环境状态">
      <header className="workbench-panel-head workbench-panel-head--right">
        <div>
          <strong>开发状态</strong>
          <span>{environmentStatusLabel(environment)}</span>
        </div>
        <button className="workbench-icon-button" disabled={loading} onClick={onRefresh} title="刷新开发状态" type="button">
          <RefreshCw size={15} />
        </button>
      </header>

      <div className="development-right-body">
        {error ? <div className="development-alert development-alert--error">{error}</div> : null}

        <section className="development-status-grid" aria-label="开发环境摘要">
          <article className={projectReady ? "development-status-card development-status-card--ready" : "development-status-card"}>
            {projectReady ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
            <div>
              <span>项目模式</span>
              <strong>{projectReady ? "已启用" : "未启用"}</strong>
            </div>
          </article>
          <article className={running ? "development-status-card development-status-card--ready" : "development-status-card"}>
            {running ? <CheckCircle2 size={16} /> : <TerminalSquare size={16} />}
            <div>
              <span>Sidecar</span>
              <strong>{running ? `PID ${sidecar?.pid || ""}` : sidecarReady ? "待启动" : "诊断"}</strong>
            </div>
          </article>
        </section>

        <section className="development-detail-panel">
          <header>
            <MonitorCog size={15} />
            <strong>运行边界</strong>
            <span>{environment?.pi.mode || "unknown"}</span>
          </header>
          <dl>
            <div><dt>工作区</dt><dd title={projectRoot}>{projectRoot}</dd></div>
            <div><dt>Node</dt><dd>{environment?.pi.node_version || "未检测"}</dd></div>
            <div><dt>工具包</dt><dd>{environment?.pi.coding_agent_package_name || environment?.pi.package_name || "未检测"}</dd></div>
            <div><dt>项目树</dt><dd>{workspaceTree ? `${workspaceTree.total_entries} 项` : "未加载"}</dd></div>
          </dl>
        </section>

        <section className="development-detail-panel">
          <header>
            <GitBranch size={15} />
            <strong>Git</strong>
            <span>{gitStatus?.branch || "未读取"}</span>
          </header>
          {gitStatus?.available ? (
            <div className="development-git-list">
              {gitItems.length ? gitItems.slice(0, 14).map((item) => (
                <div className="development-git-row" key={`${item.status}:${item.path}`}>
                  <span>{item.status}</span>
                  <strong title={item.path}>{item.path}</strong>
                </div>
              )) : <div className="development-empty">工作树无变更。</div>}
            </div>
          ) : (
            <div className="development-empty">{gitStatus?.error || "Git 状态未加载。"}</div>
          )}
        </section>

        <section className="development-detail-panel">
          <header>
            <ShieldCheck size={15} />
            <strong>诊断</strong>
            <span>{diagnostics.length ? `${diagnostics.length} 项` : "通过"}</span>
          </header>
          <div className="development-diagnostic-list">
            {diagnostics.length ? diagnostics.map((item) => (
              <article className={`development-diagnostic development-diagnostic--${item.level}`} key={`${item.code}:${item.path || item.message}`}>
                <span>{diagnosticLabel(item.level)}</span>
                <strong>{item.code}</strong>
                <p>{item.message}</p>
                {item.path ? <small title={item.path}>{item.path}</small> : null}
              </article>
            )) : <div className="development-empty">没有阻断项。</div>}
          </div>
        </section>

        <section className="development-detail-panel">
          <header>
            <TerminalSquare size={15} />
            <strong>Sidecar</strong>
            <span>{running ? "running" : "stopped"}</span>
          </header>
          <div className="development-sidecar-actions">
            <button disabled={sidecarLoading || !sidecarReady || running} onClick={() => onRunSidecarAction("start")} type="button">启动</button>
            <button disabled={sidecarLoading || !running} onClick={() => onRunSidecarAction("stop")} type="button">停止</button>
            <button disabled={sidecarLoading || !running} onClick={() => onRunSidecarAction("get_state")} type="button">状态</button>
            <button disabled={sidecarLoading || !running} onClick={() => onRunSidecarAction("get_available_models")} type="button">模型</button>
          </div>
          <dl>
            <div><dt>CLI</dt><dd title={environment?.pi.pi_cli_path}>{environment?.pi.pi_cli_path || "未检测"}</dd></div>
            <div><dt>stderr</dt><dd title={sidecar?.stderr_tail}>{sidecar?.stderr_tail || "无输出"}</dd></div>
          </dl>
        </section>

        {commandResult ? (
          <section className="development-detail-panel">
            <header>
              <Wrench size={15} />
              <strong>只读命令</strong>
              <span>{commandResult.command}</span>
            </header>
            <pre className="development-command-result">{JSON.stringify(commandResult, null, 2)}</pre>
          </section>
        ) : null}
      </div>
    </aside>
  );
}

export function CodeEnvironmentView({ embedded = false }: { embedded?: boolean }) {
  const [environment, setEnvironment] = useState<CodeEnvironmentStatus | null>(null);
  const [workspaceTree, setWorkspaceTree] = useState<CodeEnvironmentWorkspaceTree | null>(null);
  const [gitStatus, setGitStatus] = useState<CodeEnvironmentGitStatus | null>(null);
  const [sidecar, setSidecar] = useState<PiSidecarStatus | null>(null);
  const [commandResult, setCommandResult] = useState<PiSidecarCommandResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [sidecarLoading, setSidecarLoading] = useState(false);
  const [error, setError] = useState("");
  const host = useMemo(() => hostConfig(), []);

  const loadEnvironment = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [nextEnvironment, nextSidecar, nextGitStatus, nextWorkspaceTree] = await Promise.all([
        getCodeEnvironment(host),
        getPiSidecarStatus(),
        getCodeEnvironmentGitStatus(),
        getCodeEnvironmentWorkspaceTree({ maxDepth: 4, maxEntries: 4000 }),
      ]);
      setEnvironment(nextEnvironment);
      setSidecar(nextSidecar.status);
      setGitStatus(nextGitStatus);
      setWorkspaceTree(nextWorkspaceTree);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : String(loadError));
    } finally {
      setLoading(false);
    }
  }, [host]);

  useEffect(() => {
    void loadEnvironment();
  }, [loadEnvironment]);

  async function runSidecarAction(action: "start" | "stop" | "get_state" | "get_available_models") {
    setSidecarLoading(true);
    setError("");
    try {
      if (action === "start") {
        setSidecar((await startPiSidecar()).status);
      } else if (action === "stop") {
        setSidecar((await stopPiSidecar()).status);
      } else {
        setCommandResult(await runPiSidecarReadOnlyCommand(action));
      }
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : String(actionError));
    } finally {
      setSidecarLoading(false);
      void loadEnvironment();
    }
  }

  const branchLabel = gitStatus?.branch || "未读取";
  const statusText = environmentStatusLabel(environment);

  return (
    <WorkbenchShell
      className={embedded ? "development-environment-shell development-environment-shell--embedded" : "development-environment-shell"}
      rightPanel={(
        <DevelopmentRightPanel
          commandResult={commandResult}
          environment={environment}
          error={error}
          gitStatus={gitStatus}
          loading={loading}
          onRefresh={() => void loadEnvironment()}
          onRunSidecarAction={(action) => void runSidecarAction(action)}
          sidecar={sidecar}
          sidecarLoading={sidecarLoading}
          workspaceTree={workspaceTree}
        />
      )}
      rightPanelLabel="开发状态"
    >
      <section className="workbench-view-host development-center-host" aria-label="开发任务对话">
        <div className="development-center-banner">
          <div>
            <span>开发环境</span>
            <strong>专业 Coding Agent</strong>
          </div>
          <div>
            <FileCode2 size={15} />
            <span>{branchLabel}</span>
          </div>
          <div>
            <Cpu size={15} />
            <span>{statusText}</span>
          </div>
        </div>
        <ChatPanel />
      </section>
    </WorkbenchShell>
  );
}
