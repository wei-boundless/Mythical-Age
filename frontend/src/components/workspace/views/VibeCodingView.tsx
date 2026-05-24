"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Cpu, MonitorCog, RefreshCw, TerminalSquare } from "lucide-react";

import {
  getPiSidecarStatus,
  getVibeCodingEnvironment,
  runPiSidecarReadOnlyCommand,
  startPiSidecar,
  stopPiSidecar,
  type PiSidecarCommandResponse,
  type PiSidecarStatus,
  type VibeCodingEnvironmentStatus,
} from "@/lib/api";

function hostConfig() {
  const config = globalThis.__MYTHICAL_AGENT_HOST__ || (typeof window !== "undefined" ? window.mythicalAgentHost?.getConfig() : undefined);
  return {
    mode: config?.hostMode || "web",
    localRuntimeAvailable: Boolean(config?.localRuntimeAvailable),
    vibeCodingHostAvailable: Boolean(config?.vibeCodingHostAvailable),
  } as const;
}

function statusLabel(environment: VibeCodingEnvironmentStatus | null) {
  if (!environment) return "检测中";
  if (!environment.pi.enabled) return "已关闭";
  if (environment.pi.mode === "sidecar_ready") return "环境就绪";
  if (environment.pi.mode === "error") return "环境异常";
  if (environment.pi.cli_built) return "可连接";
  return "项目模式可用";
}

export function VibeCodingView({ embedded = false }: { embedded?: boolean }) {
  const [environment, setEnvironment] = useState<VibeCodingEnvironmentStatus | null>(null);
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
      const [nextEnvironment, nextSidecar] = await Promise.all([
        getVibeCodingEnvironment(host),
        getPiSidecarStatus(),
      ]);
      setEnvironment(nextEnvironment);
      setSidecar(nextSidecar.status);
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
    <section className={embedded ? "vibe-coding-console vibe-coding-console--embedded" : "vibe-coding-console"} aria-label="Vibe Coding 环境">
      <header className="vibe-coding-console__header">
        <div>
          <span>本地增强</span>
          <h1>{embedded ? "Coding 环境" : "Vibe Coding 环境"}</h1>
        </div>
        <button disabled={loading} onClick={() => void load()} type="button">
          <RefreshCw size={15} />
          <span>刷新</span>
        </button>
      </header>

      <div className="vibe-coding-status-grid">
        <article className={ready ? "vibe-coding-status-card vibe-coding-status-card--ready" : "vibe-coding-status-card"}>
          {projectReady ? <CheckCircle2 size={20} /> : <AlertTriangle size={20} />}
          <div>
            <span>项目模式</span>
            <strong>{projectReady ? "已启用" : statusLabel(environment)}</strong>
          </div>
        </article>
        <article className={running ? "vibe-coding-status-card vibe-coding-status-card--ready" : "vibe-coding-status-card"}>
          {running ? <CheckCircle2 size={20} /> : <TerminalSquare size={20} />}
          <div>
            <span>Pi Sidecar</span>
            <strong>{running ? `运行中 · ${sidecar?.pid || ""}` : environment?.pi.sidecar_enabled ? "未启动" : "诊断模式"}</strong>
          </div>
        </article>
        <article className="vibe-coding-status-card">
          <MonitorCog size={20} />
          <div>
            <span>Host</span>
            <strong>{host.mode === "desktop" ? "Electron 本地壳" : "Web 工作台"}</strong>
          </div>
        </article>
        <article className="vibe-coding-status-card">
          <Cpu size={20} />
          <div>
            <span>Node</span>
            <strong>{environment?.pi.node_version || "未检测"}</strong>
          </div>
        </article>
        <article className="vibe-coding-status-card">
          <TerminalSquare size={20} />
          <div>
            <span>RPC</span>
            <strong>{environment?.pi.rpc_source_available ? "源码存在" : "未发现"}</strong>
          </div>
        </article>
      </div>

      {error ? <div className="vibe-coding-alert vibe-coding-alert--error">{error}</div> : null}

      <div className="vibe-coding-layout">
        <section className="vibe-coding-panel">
          <header>
            <strong>运行边界</strong>
            <span>项目主控</span>
          </header>
          <dl className="vibe-coding-kv">
            <div>
              <dt>能力归属</dt>
              <dd>本项目 runtime / profile / tool / permission</dd>
            </div>
            <div>
              <dt>入口</dt>
              <dd>主页面任务入口和本页环境诊断共用同一后端能力</dd>
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

        <section className="vibe-coding-panel">
          <header>
            <strong>Pi 环境</strong>
            <span>{loading ? "检测中" : environment?.pi.mode || "未知"}</span>
          </header>
          <dl className="vibe-coding-kv">
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

        <section className="vibe-coding-panel">
          <header>
            <strong>Sidecar 控制</strong>
            <span>{running ? "running" : "stopped"}</span>
          </header>
          <div className="vibe-coding-actions">
            <button disabled={sidecarLoading || !ready || running} onClick={() => void runSidecarAction("start")} type="button">启动</button>
            <button disabled={sidecarLoading || !running} onClick={() => void runSidecarAction("stop")} type="button">停止</button>
            <button disabled={sidecarLoading || !running} onClick={() => void runSidecarAction("get_state")} type="button">get_state</button>
            <button disabled={sidecarLoading || !running} onClick={() => void runSidecarAction("get_available_models")} type="button">models</button>
          </div>
          <dl className="vibe-coding-kv">
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

      {commandResult ? (
        <section className="vibe-coding-panel vibe-coding-panel--wide">
          <header>
            <strong>只读命令结果</strong>
            <span>{commandResult.command}</span>
          </header>
          <pre className="vibe-coding-command-result">{JSON.stringify(commandResult, null, 2)}</pre>
        </section>
      ) : null}

      <section className="vibe-coding-panel vibe-coding-panel--wide">
        <header>
          <strong>诊断</strong>
          <span>{diagnostics.length ? `${diagnostics.length} 项` : "无阻断项"}</span>
        </header>
        {diagnostics.length ? (
          <div className="vibe-coding-diagnostics">
            {diagnostics.map((item) => (
              <article className={`vibe-coding-diagnostic vibe-coding-diagnostic--${item.level}`} key={`${item.code}:${item.path || item.message}`}>
                <strong>{item.code}</strong>
                <p>{item.message}</p>
                {item.path ? <span title={item.path}>{item.path}</span> : null}
              </article>
            ))}
          </div>
        ) : (
          <div className="vibe-coding-empty">环境检查没有发现阻断项。</div>
        )}
      </section>
    </section>
  );
}
