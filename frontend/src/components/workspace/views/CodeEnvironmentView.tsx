"use client";

import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, Cpu, File, Folder, FolderOpen, MonitorCog, RefreshCw, TerminalSquare } from "lucide-react";

import {
  getCodeEnvironment,
  getCodeEnvironmentWorkspaceTree,
  getPiSidecarStatus,
  runPiSidecarReadOnlyCommand,
  startPiSidecar,
  stopPiSidecar,
  type CodeEnvironmentStatus,
  type CodeEnvironmentTreeNode,
  type CodeEnvironmentWorkspaceTree,
  type PiSidecarCommandResponse,
  type PiSidecarStatus,
} from "@/lib/api";

function hostConfig() {
  const config = globalThis.__MYTHICAL_AGENT_HOST__ || (typeof window !== "undefined" ? window.mythicalAgentHost?.getConfig() : undefined);
  return {
    mode: config?.hostMode || "web",
    localRuntimeAvailable: Boolean(config?.localRuntimeAvailable),
    codeEnvironmentHostAvailable: Boolean(config?.codeEnvironmentHostAvailable),
  } as const;
}

function statusLabel(environment: CodeEnvironmentStatus | null) {
  if (!environment) return "检测中";
  if (!environment.pi.enabled) return "已关闭";
  if (environment.pi.mode === "sidecar_ready") return "环境就绪";
  if (environment.pi.mode === "error") return "环境异常";
  if (environment.pi.cli_built) return "可连接";
  return "专业模式可用";
}

function WorkspaceTreeNodeView({ node }: { node: CodeEnvironmentTreeNode }) {
  const isDirectory = node.kind === "directory";
  const [expanded, setExpanded] = useState(node.depth === 0);
  const visibleName = node.name || "project";
  const hasChildren = isDirectory && node.children.length > 0;
  return (
    <li>
      <button
        aria-expanded={hasChildren ? expanded : undefined}
        className={isDirectory ? "code-environment-tree-row code-environment-tree-row--directory" : "code-environment-tree-row"}
        onClick={() => {
          if (hasChildren) setExpanded((value) => !value);
        }}
        style={{ "--tree-depth": node.depth } as CSSProperties}
        title={node.path || visibleName}
        type="button"
      >
        {hasChildren ? (expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />) : <span className="code-environment-tree-row__spacer" />}
        {isDirectory ? (expanded ? <FolderOpen size={14} /> : <Folder size={14} />) : <File size={14} />}
        <span>{visibleName}</span>
        {node.truncated ? <small>截断</small> : null}
      </button>
      {hasChildren && expanded ? (
        <ul>
          {node.children.map((child) => (
            <WorkspaceTreeNodeView key={`${child.kind}:${child.path}`} node={child} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

export function CodeEnvironmentView({ embedded = false }: { embedded?: boolean }) {
  const [environment, setEnvironment] = useState<CodeEnvironmentStatus | null>(null);
  const [workspaceTree, setWorkspaceTree] = useState<CodeEnvironmentWorkspaceTree | null>(null);
  const [sidecar, setSidecar] = useState<PiSidecarStatus | null>(null);
  const [commandResult, setCommandResult] = useState<PiSidecarCommandResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [sidecarLoading, setSidecarLoading] = useState(false);
  const [error, setError] = useState("");
  const host = useMemo(() => hostConfig(), []);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [nextEnvironment, nextSidecar, nextWorkspaceTree] = await Promise.all([
        getCodeEnvironment(host),
        getPiSidecarStatus(),
        getCodeEnvironmentWorkspaceTree(),
      ]);
      setEnvironment(nextEnvironment);
      setSidecar(nextSidecar.status);
      setWorkspaceTree(nextWorkspaceTree);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : String(loadError));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const diagnostics = environment?.pi.diagnostics || [];
  const projectReady = Boolean(environment?.pi.enabled);
  const ready = Boolean(environment?.pi.available && environment.pi.cli_built && environment.pi.sidecar_enabled);
  const running = Boolean(sidecar?.running);

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
      void load();
    }
  }

  return (
    <section className={embedded ? "code-environment-console code-environment-console--embedded" : "code-environment-console"} aria-label="专业模式代码环境">
      <header className="code-environment-console__header">
        <div>
          <span>专业模式</span>
          <h1>{embedded ? "代码环境" : "专业模式代码环境"}</h1>
        </div>
        <button disabled={loading} onClick={() => void load()} type="button">
          <RefreshCw size={15} />
          <span>刷新</span>
        </button>
      </header>

      <div className="code-environment-status-grid">
        <article className={ready ? "code-environment-status-card code-environment-status-card--ready" : "code-environment-status-card"}>
          {projectReady ? <CheckCircle2 size={20} /> : <AlertTriangle size={20} />}
          <div>
            <span>项目模式</span>
            <strong>{projectReady ? "已启用" : statusLabel(environment)}</strong>
          </div>
        </article>
        <article className={running ? "code-environment-status-card code-environment-status-card--ready" : "code-environment-status-card"}>
          {running ? <CheckCircle2 size={20} /> : <TerminalSquare size={20} />}
          <div>
            <span>Pi Sidecar</span>
            <strong>{running ? `运行中 · ${sidecar?.pid || ""}` : environment?.pi.sidecar_enabled ? "未启动" : "诊断模式"}</strong>
          </div>
        </article>
        <article className="code-environment-status-card">
          <MonitorCog size={20} />
          <div>
            <span>Host</span>
            <strong>{host.mode === "desktop" ? "Electron 本地壳" : "Web 工作台"}</strong>
          </div>
        </article>
        <article className="code-environment-status-card">
          <Cpu size={20} />
          <div>
            <span>Node</span>
            <strong>{environment?.pi.node_version || "未检测"}</strong>
          </div>
        </article>
        <article className="code-environment-status-card">
          <TerminalSquare size={20} />
          <div>
            <span>RPC</span>
            <strong>{environment?.pi.rpc_source_available ? "源码存在" : "未发现"}</strong>
          </div>
        </article>
      </div>

      {error ? <div className="code-environment-alert code-environment-alert--error">{error}</div> : null}

      <div className="code-environment-workspace-layout">
        <section className="code-environment-panel code-environment-workspace">
          <header>
            <strong>项目文件</strong>
            <span>{workspaceTree ? `${workspaceTree.total_entries} 项` : loading ? "加载中" : "未加载"}</span>
          </header>
          {workspaceTree ? (
            <>
              <div className="code-environment-workspace__root">
                <strong>{workspaceTree.root_name}</strong>
                <span title={workspaceTree.root_path}>{workspaceTree.root_path}</span>
              </div>
              <ul className="code-environment-tree">
                <WorkspaceTreeNodeView node={workspaceTree.tree} />
              </ul>
              {workspaceTree.truncated ? <div className="code-environment-empty">文件较多，当前只显示前 {workspaceTree.max_entries} 项。</div> : null}
            </>
          ) : (
            <div className="code-environment-empty">{loading ? "正在读取项目目录。" : "未发现可显示文件。"}</div>
          )}
        </section>

        <div className="code-environment-layout">
          <section className="code-environment-panel">
            <header>
              <strong>运行边界</strong>
              <span>项目主控</span>
            </header>
            <dl className="code-environment-kv">
              <div>
                <dt>能力归属</dt>
                <dd>本项目 runtime / profile / tool / permission</dd>
              </div>
              <div>
                <dt>入口</dt>
                <dd>主页面任务入口和本页环境诊断共用专业模式后端能力</dd>
              </div>
              <div>
                <dt>Pi</dt>
                <dd>{environment?.pi.sidecar_enabled ? "可选 sidecar" : "可选依赖，当前仅诊断"}</dd>
              </div>
              <div>
                <dt>工作区策略</dt>
                <dd>{environment?.pi.workspace_root_policy || "project_root"}</dd>
              </div>
            </dl>
          </section>

          <section className="code-environment-panel">
            <header>
              <strong>Pi 环境</strong>
              <span>{loading ? "检测中" : environment?.pi.mode || "未知"}</span>
            </header>
            <dl className="code-environment-kv">
              <div>
                <dt>源码</dt>
                <dd title={environment?.pi.pi_source_root}>{environment?.pi.pi_source_root || "未检测"}</dd>
              </div>
              <div>
                <dt>CLI</dt>
                <dd title={environment?.pi.pi_cli_path}>{environment?.pi.pi_cli_path || "未检测"}</dd>
              </div>
              <div>
                <dt>工作区</dt>
                <dd title={environment?.pi.workspace_root}>{environment?.pi.workspace_root || "未检测"}</dd>
              </div>
              <div>
                <dt>配置</dt>
                <dd>{environment?.pi.sidecar_mode || "diagnostic_only"}</dd>
              </div>
              <div>
                <dt>包</dt>
                <dd>{environment?.pi.coding_agent_package_name || environment?.pi.package_name || "未检测"}</dd>
              </div>
            </dl>
          </section>

          <section className="code-environment-panel">
            <header>
              <strong>Sidecar 控制</strong>
              <span>{running ? "running" : "stopped"}</span>
            </header>
            <div className="code-environment-actions">
              <button disabled={sidecarLoading || !ready || running} onClick={() => void runSidecarAction("start")} type="button">启动</button>
              <button disabled={sidecarLoading || !running} onClick={() => void runSidecarAction("stop")} type="button">停止</button>
              <button disabled={sidecarLoading || !running} onClick={() => void runSidecarAction("get_state")} type="button">get_state</button>
              <button disabled={sidecarLoading || !running} onClick={() => void runSidecarAction("get_available_models")} type="button">models</button>
            </div>
            <dl className="code-environment-kv">
              <div>
                <dt>PID</dt>
                <dd>{sidecar?.pid || "无"}</dd>
              </div>
              <div>
                <dt>stderr</dt>
                <dd title={sidecar?.stderr_tail}>{sidecar?.stderr_tail || "无输出"}</dd>
              </div>
            </dl>
          </section>
        </div>
      </div>

      {commandResult ? (
        <section className="code-environment-panel code-environment-panel--wide">
          <header>
            <strong>只读命令结果</strong>
            <span>{commandResult.command}</span>
          </header>
          <pre className="code-environment-command-result">{JSON.stringify(commandResult, null, 2)}</pre>
        </section>
      ) : null}

      <section className="code-environment-panel code-environment-panel--wide">
        <header>
          <strong>诊断</strong>
          <span>{diagnostics.length ? `${diagnostics.length} 项` : "无阻断项"}</span>
        </header>
        {diagnostics.length ? (
          <div className="code-environment-diagnostics">
            {diagnostics.map((item) => (
              <article className={`code-environment-diagnostic code-environment-diagnostic--${item.level}`} key={`${item.code}:${item.path || item.message}`}>
                <strong>{item.code}</strong>
                <p>{item.message}</p>
                {item.path ? <span title={item.path}>{item.path}</span> : null}
              </article>
            ))}
          </div>
        ) : (
          <div className="code-environment-empty">环境检查没有发现阻断项。</div>
        )}
      </section>
    </section>
  );
}
