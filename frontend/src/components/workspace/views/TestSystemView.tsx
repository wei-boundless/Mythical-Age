"use client";

import {
  Activity,
  AlertTriangle,
  Bug,
  CheckCircle2,
  FlaskConical,
  GitBranch,
  Loader2,
  Play,
  RefreshCw,
  ScrollText,
  ShieldCheck,
  XCircle
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  cancelExperimentRun,
  getExperimentArtifacts,
  getExperimentRun,
  getExperimentGraphOverlay,
  getExperimentTurnGraphOverlay,
  listExperimentProfiles,
  listExperimentRuns,
  listExperimentTurns,
  startExperimentRun,
  type ExperimentArtifacts,
  type ExperimentProfile,
  type ExperimentRun,
  type ExperimentTurn
} from "@/lib/api";
import { useAppStore } from "@/lib/store";

type IssueGraphRefs = {
  nodes?: string[];
  edges?: string[];
  reason?: string;
};

const issueTurnIdKeys = ["turn_id", "turnId", "turn", "failed_turn_id", "failedTurnId"];
const issueTurnIndexKeys = ["turn_index", "turnIndex", "index", "failed_turn", "failedTurn"];

type TestSystemPage = "control" | "monitor" | "turns" | "issues" | "artifacts";
type ArtifactView = "summary" | "report" | "issues" | "trace" | "log" | "result";

const testSystemPages: Array<{
  key: TestSystemPage;
  title: string;
  subtitle: string;
}> = [
  { key: "control", title: "测试控制台", subtitle: "选择并启动测试" },
  { key: "monitor", title: "运行监控", subtitle: "状态、日志与取消" },
  { key: "turns", title: "轮次回放", subtitle: "长场景 turn 时间线" },
  { key: "issues", title: "问题诊断", subtitle: "失败定位与跳转" },
  { key: "artifacts", title: "产物档案", subtitle: "报告、trace 与原始记录" }
];

const artifactViewLabels: Record<ArtifactView, string> = {
  summary: "摘要",
  report: "报告",
  issues: "问题 JSON",
  trace: "Trace",
  log: "日志",
  result: "运行结果"
};

const graphNodes = [
  {
    id: "smoke",
    label: "冒烟测试",
    x: 12,
    y: 52,
    text: "先确认接口、SSE 和前端事件链路"
  },
  {
    id: "stable",
    label: "稳定门禁",
    x: 31,
    y: 32,
    text: "追加 core 回归和前端构建"
  },
  {
    id: "long_core",
    label: "长场景核心",
    x: 50,
    y: 52,
    text: "三条核心长场景"
  },
  {
    id: "long_batches",
    label: "长场景批量",
    x: 69,
    y: 32,
    text: "六条中长场景"
  },
  {
    id: "marathon",
    label: "六十轮长跑",
    x: 88,
    y: 52,
    text: "60 turn 真实用户马拉松"
  },
  {
    id: "artifacts",
    label: "测试产物",
    x: 50,
    y: 82,
    text: "run_result / issues / trace / report"
  }
];

const graphEdges = [
  { from: "smoke", to: "stable", label: "通过后升级" },
  { from: "stable", to: "long_core", label: "主链稳定后长跑" },
  { from: "long_core", to: "long_batches", label: "扩大场景" },
  { from: "long_batches", to: "marathon", label: "最终压测" },
  { from: "smoke", to: "artifacts", label: "写入报告" },
  { from: "stable", to: "artifacts", label: "写入报告" },
  { from: "long_core", to: "artifacts", label: "核心长链" },
  { from: "long_batches", to: "artifacts", label: "批量长链" },
  { from: "marathon", to: "artifacts", label: "六十轮" }
];

function pointFor(id: string) {
  return graphNodes.find((node) => node.id === id) ?? graphNodes[0];
}

function statusLabel(status: string) {
  if (status === "running") {
    return "运行中";
  }
  if (status === "passed") {
    return "通过";
  }
  if (status === "failed") {
    return "失败";
  }
  if (status === "cancelled") {
    return "已取消";
  }
  return status || "未知";
}

function statusIcon(status: string) {
  if (status === "running") {
    return <Loader2 className="animate-spin" size={18} />;
  }
  if (status === "passed") {
    return <CheckCircle2 size={18} />;
  }
  if (status === "failed") {
    return <XCircle size={18} />;
  }
  return <Activity size={18} />;
}

function issueText(issue: Record<string, unknown>) {
  return [
    issue.id,
    issue.title,
    issue.summary,
    issue.command,
    issue.category
  ].map((value) => String(value ?? "")).join(" ");
}

function issueArtifactPaths(issue: Record<string, unknown>) {
  const raw = issue.artifact_paths;
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw.map((item) => String(item ?? "").replace(/\\/g, "/"));
}

function pathMentionsTurn(path: string, turn: ExperimentTurn) {
  const normalizedPath = path.replace(/\\/g, "/");
  const artifactPath = turn.artifact_path.replace(/\\/g, "/");
  return normalizedPath.includes(turn.turn_id) || normalizedPath.endsWith(artifactPath) || artifactPath.endsWith(normalizedPath);
}

function turnProblemLabel(turn: ExperimentTurn) {
  if (!turn.problem_node_id) {
    return "";
  }
  return `问题节点：${turn.problem_node_label || turn.problem_node_id}`;
}

function readIssueTurnIndex(issue: Record<string, unknown>) {
  for (const key of issueTurnIndexKeys) {
    const value = issue[key];
    if (typeof value === "number" && Number.isFinite(value)) {
      return value;
    }
    const parsed = Number.parseInt(String(value ?? ""), 10);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  const match = issueText(issue).match(/(?:first\s+failure\s+)?turn\s*=?\s*(\d+)/i);
  return match ? Number.parseInt(match[1], 10) : null;
}

export function TestSystemView() {
  const {
    highlightSystemGraph,
    setSystemGraphOverlay,
    setMemoryInspectorTarget,
    setOrchestrationInspectorTarget,
    setWorkspaceView
  } = useAppStore();
  const [activePage, setActivePage] = useState<TestSystemPage>("control");
  const [artifactView, setArtifactView] = useState<ArtifactView>("summary");
  const [selectedTurnId, setSelectedTurnId] = useState("");
  const [profiles, setProfiles] = useState<ExperimentProfile[]>([]);
  const [runs, setRuns] = useState<ExperimentRun[]>([]);
  const [turns, setTurns] = useState<ExperimentTurn[]>([]);
  const [selectedProfile, setSelectedProfile] = useState("smoke");
  const [activeRunId, setActiveRunId] = useState("");
  const [activeRun, setActiveRun] = useState<ExperimentRun | null>(null);
  const [artifacts, setArtifacts] = useState<ExperimentArtifacts | null>(null);
  const [turnDisplayMode, setTurnDisplayMode] = useState<"focus" | "all" | "failed">("focus");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const profileMap = useMemo(
    () => new Map(profiles.map((profile) => [profile.id, profile])),
    [profiles]
  );
  const selected = profileMap.get(selectedProfile);
  const isRunning = activeRun?.status === "running";
  const latestSummary = activeRun?.summary ?? runs[0]?.summary ?? {
    total: 0,
    passed: 0,
    failed: 0,
    first_failure: ""
  };
  const turnStats = useMemo(() => {
    const failed = turns.filter((turn) => turn.status === "failed").length;
    const warning = turns.filter((turn) => turn.status === "warning").length;
    const passed = turns.filter((turn) => turn.status === "passed").length;
    const promptManifest = turns.filter((turn) => turn.has_prompt_manifest).length;
    const memoryTrace = turns.filter((turn) => turn.has_memory_trace).length;
    return { failed, warning, passed, promptManifest, memoryTrace, total: turns.length };
  }, [turns]);
  const firstProblemTurn = useMemo(
    () => turns.find((turn) => turn.status === "failed" || turn.status === "warning") ?? null,
    [turns]
  );
  const visibleTurns = useMemo(() => {
    if (turnDisplayMode === "failed") {
      return turns.filter((turn) => turn.status === "failed" || turn.status === "warning");
    }
    if (turnDisplayMode === "all") {
      return turns;
    }
    const problemTurns = turns.filter((turn) => turn.status === "failed" || turn.status === "warning");
    const earlyTurns = turns.slice(0, 6);
    const lateTurns = turns.slice(-4);
    const merged = [...problemTurns, ...earlyTurns, ...lateTurns];
    return merged.filter((turn, index) => merged.findIndex((item) => item.turn_id === turn.turn_id) === index);
  }, [turnDisplayMode, turns]);
  const selectedTurn = useMemo(
    () => turns.find((turn) => turn.turn_id === selectedTurnId) ?? firstProblemTurn ?? turns[0] ?? null,
    [firstProblemTurn, selectedTurnId, turns]
  );
  const artifactContent = useMemo(() => {
    if (!artifacts) {
      return "还没有可读取的测试产物。";
    }
    if (artifactView === "summary") {
      return JSON.stringify(artifacts.summary, null, 2);
    }
    if (artifactView === "report") {
      return artifacts.report || "report.md 为空。";
    }
    if (artifactView === "issues") {
      return JSON.stringify(artifacts.issues, null, 2);
    }
    if (artifactView === "trace") {
      return artifacts.trace_tail || "trace tail 为空。";
    }
    if (artifactView === "log") {
      return activeRun?.log_tail || "runner.log 为空。";
    }
    return JSON.stringify(artifacts.run_result, null, 2);
  }, [activeRun?.log_tail, artifactView, artifacts]);

  useEffect(() => {
    let mounted = true;
    async function loadInitial() {
      try {
        const [profilePayload, runPayload] = await Promise.all([
          listExperimentProfiles(),
          listExperimentRuns(10)
        ]);
        if (!mounted) {
          return;
        }
        setProfiles(profilePayload);
        setRuns(runPayload);
        const running = runPayload.find((run) => run.status === "running");
        const latest = running ?? runPayload[0];
        if (latest) {
          setActiveRunId(latest.run_id);
          setActiveRun(latest);
          if (latest.status !== "running") {
            void loadArtifacts(latest.run_id);
            void loadTurns(latest.run_id);
          }
        }
      } catch (exc) {
        if (mounted) {
          setError(exc instanceof Error ? exc.message : "加载测试系统失败");
        }
      }
    }
    void loadInitial();
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    if (!activeRunId || activeRun?.status !== "running") {
      return;
    }
    const timer = window.setInterval(() => {
      void (async () => {
        const run = await getExperimentRun(activeRunId);
        setActiveRun(run);
        setRuns(await listExperimentRuns(10));
        if (run.status !== "running") {
          await loadArtifacts(run.run_id);
          await loadTurns(run.run_id);
        }
      })();
    }, 2200);
    return () => window.clearInterval(timer);
  }, [activeRunId, activeRun?.status]);

  async function refreshRuns() {
    const payload = await listExperimentRuns(10);
    setRuns(payload);
    return payload;
  }

  async function refreshRun(runId = activeRunId) {
    if (!runId) {
      await refreshRuns();
      return;
    }
    const run = await getExperimentRun(runId);
    setActiveRun(run);
    const payload = await refreshRuns();
    if (run.status !== "running") {
      await loadArtifacts(run.run_id);
      await loadTurns(run.run_id);
    }
    if (!payload.find((item) => item.run_id === run.run_id)) {
      setRuns([run, ...payload]);
    }
  }

  async function loadArtifacts(runId: string) {
    try {
      const payload = await getExperimentArtifacts(runId);
      setArtifacts(payload);
    } catch {
      setArtifacts(null);
    }
  }

  async function loadTurns(runId: string) {
    try {
      const payload = await listExperimentTurns(runId);
      setTurns(payload);
    } catch {
      setTurns([]);
    }
  }

  async function startProfile(profileId = selectedProfile) {
    const profile = profileMap.get(profileId);
    if (profile?.requires_confirmation) {
      const confirmed = window.confirm("长场景测试耗时较长，并会调用真实后端执行链。确认现在运行吗？");
      if (!confirmed) {
        return;
      }
    }
    setLoading(true);
    setError("");
    setArtifacts(null);
    try {
      const run = await startExperimentRun(profileId);
      setActiveRunId(run.run_id);
      setActiveRun(run);
      setTurns([]);
      setActivePage("monitor");
      await refreshRuns();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "启动测试失败");
    } finally {
      setLoading(false);
    }
  }

  async function cancelActiveRun() {
    if (!activeRunId) {
      return;
    }
    setLoading(true);
    try {
      const run = await cancelExperimentRun(activeRunId);
      setActiveRun(run);
      await refreshRuns();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "取消测试失败");
    } finally {
      setLoading(false);
    }
  }

  function selectRun(run: ExperimentRun) {
    setActiveRunId(run.run_id);
    setActiveRun(run);
    if (run.status !== "running") {
      void loadArtifacts(run.run_id);
      void loadTurns(run.run_id);
    } else {
      setArtifacts(null);
      setTurns([]);
    }
  }

  function openIssueOnSystemGraph(issue: Record<string, unknown>) {
    const refs = (issue.graph_refs ?? {}) as IssueGraphRefs;
    setSystemGraphOverlay(null);
    highlightSystemGraph({
      nodeIds: Array.isArray(refs.nodes) ? refs.nodes.map(String) : ["tests", "query-core"],
      edgeIds: Array.isArray(refs.edges) ? refs.edges.map(String) : ["tests-query"],
      reason: String(refs.reason ?? issue.summary ?? "测试问题映射到系统框架。"),
      source: String(issue.id ?? issue.title ?? activeRunId ?? "test-issue")
    });
    setWorkspaceView("system-framework");
  }

  async function openRunOnSystemGraph() {
    if (!activeRunId) {
      return;
    }
    try {
      const overlay = await getExperimentGraphOverlay(activeRunId);
      setSystemGraphOverlay(overlay);
      highlightSystemGraph(null);
      setWorkspaceView("system-framework");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加载运行链路失败");
    }
  }

  async function openTurnOnSystemGraph(turn: ExperimentTurn) {
    if (!activeRunId) {
      return;
    }
    try {
      const overlay = await getExperimentTurnGraphOverlay(activeRunId, turn.turn_id);
      setSystemGraphOverlay(overlay);
      highlightSystemGraph(null);
      setWorkspaceView("system-framework");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加载轮次链路失败");
    }
  }

  function findIssueTurn(issue: Record<string, unknown>) {
    for (const key of issueTurnIdKeys) {
      const value = String(issue[key] ?? "");
      if (!value) {
        continue;
      }
      const direct = turns.find((turn) => turn.turn_id === value);
      if (direct) {
        return direct;
      }
    }

    const paths = issueArtifactPaths(issue);
    const turnIndex = readIssueTurnIndex(issue);
    if (turnIndex !== null) {
      const byIndexAndPath = turns.find((turn) => (
        turn.index === turnIndex && (!paths.length || paths.some((path) => pathMentionsTurn(path, turn)))
      ));
      if (byIndexAndPath) {
        return byIndexAndPath;
      }
    }

    const byProblemPath = turns.find((turn) => (
      (turn.status === "failed" || turn.status === "warning")
      && paths.some((path) => pathMentionsTurn(path, turn))
    ));
    if (byProblemPath) {
      return byProblemPath;
    }

    return paths.length
      ? turns.find((turn) => paths.some((path) => pathMentionsTurn(path, turn))) ?? null
      : null;
  }

  function openIssueOnOrchestration(issue: Record<string, unknown>) {
    const turn = findIssueTurn(issue);
    if (!turn) {
      openIssueOnSystemGraph(issue);
      return;
    }
    setSelectedTurnId(turn.turn_id);
    openTurnOnOrchestration(turn);
  }

  function openTurnOnMemorySystem(turn: ExperimentTurn) {
    if (!activeRunId) {
      return;
    }
    setMemoryInspectorTarget({
      source: "test-system",
      runId: activeRunId,
      turnId: turn.turn_id,
      turnIndex: turn.index,
      layer: "state",
      reason: turn.summary || "从测试系统查看该轮记忆链路。"
    });
    setWorkspaceView("memory");
  }

  function openTurnOnOrchestration(turn: ExperimentTurn) {
    if (!activeRunId) {
      return;
    }
    setOrchestrationInspectorTarget({
      source: "test-system",
      runId: activeRunId,
      turnId: turn.turn_id,
      turnIndex: turn.index,
      artifactPath: turn.artifact_path,
      reason: turn.summary || "从测试系统复盘该轮编排链路。"
    });
    setWorkspaceView("experiments");
  }

  async function openFirstProblemTurn() {
    if (!firstProblemTurn) {
      await openRunOnSystemGraph();
      return;
    }
    openTurnOnOrchestration(firstProblemTurn);
  }

  return (
    <div className="workspace-view">
      <header className="workspace-view__header">
        <div>
          <p className="workspace-view__eyebrow">Test System</p>
          <h2 className="workspace-view__title">测试系统</h2>
        </div>
        <div className="workspace-view__actions">
          <button className="action-button action-button--ghost" onClick={() => void refreshRun()} type="button">
            <RefreshCw size={15} />
            刷新
          </button>
          <button
            className="action-button action-button--primary"
            disabled={loading || isRunning}
            onClick={() => void startProfile(selectedProfile)}
            type="button"
          >
            <Play size={15} />
            运行所选测试
          </button>
          <button
            className="action-button action-button--ghost"
            disabled={!activeRunId}
            onClick={() => void openRunOnSystemGraph()}
            type="button"
          >
            <GitBranch size={15} />
            架构定位
          </button>
        </div>
      </header>

      {error ? (
        <div className="workspace-alert">
          <AlertTriangle size={16} />
          <span>{error}</span>
        </div>
      ) : null}

      <nav className="test-system-tabs" aria-label="测试系统分页导航">
        {testSystemPages.map((page) => (
          <button
            className={`test-system-tab ${activePage === page.key ? "test-system-tab--active" : ""}`}
            key={page.key}
            onClick={() => setActivePage(page.key)}
            type="button"
          >
            <strong>{page.title}</strong>
            <span>{page.subtitle}</span>
          </button>
        ))}
      </nav>

      <div className="workspace-metrics-grid">
        <div className="workspace-stat">
          <FlaskConical size={18} />
          <span>当前方案</span>
          <strong>{selected?.title ?? selectedProfile}</strong>
        </div>
        <div className="workspace-stat">
          {statusIcon(activeRun?.status ?? "")}
          <span>最近运行</span>
          <strong>{activeRun ? statusLabel(activeRun.status) : "暂无"}</strong>
        </div>
        <div className="workspace-stat">
          <Bug size={18} />
          <span>失败数量</span>
          <strong>{latestSummary.failed}</strong>
        </div>
      </div>

      {activePage === "control" ? (
        <>
          <section className="test-control-hero">
            <div>
              <span>Experiment Control</span>
              <strong>{selected?.title ?? selectedProfile}</strong>
              <p>{selected?.description ?? "选择一个测试方案，然后从前端启动白名单测试。"}</p>
            </div>
            <div className="test-control-hero__actions">
              <button
                className="action-button action-button--primary"
                disabled={loading || isRunning}
                onClick={() => void startProfile(selectedProfile)}
                type="button"
              >
                <Play size={15} />
                运行所选测试
              </button>
              <button className="action-button action-button--ghost" disabled={!activeRunId} onClick={() => setActivePage("monitor")} type="button">
                查看运行监控
              </button>
            </div>
          </section>

          <section className="workspace-section test-map">
            <div className="workspace-section__head">
              <GitBranch size={18} />
              <h3>测试系统图</h3>
            </div>
            <div className="test-map__canvas">
              <svg aria-hidden className="test-map__edges" preserveAspectRatio="none" viewBox="0 0 100 100">
                {graphEdges.map((edge) => {
                  const from = pointFor(edge.from);
                  const to = pointFor(edge.to);
                  return (
                    <g key={`${edge.from}-${edge.to}`}>
                      <line x1={from.x} x2={to.x} y1={from.y} y2={to.y} />
                      <text x={(from.x + to.x) / 2} y={(from.y + to.y) / 2 - 2}>
                        {edge.label}
                      </text>
                    </g>
                  );
                })}
              </svg>
              {graphNodes.map((node) => {
                const isProfile = node.id !== "artifacts";
                const profile = profileMap.get(node.id);
                const selectedNode = selectedProfile === node.id;
                return (
                  <button
                    className={`test-map-node ${selectedNode ? "test-map-node--active" : ""} ${node.id.startsWith("long") || node.id === "marathon" ? "test-map-node--long" : ""}`}
                    disabled={!isProfile}
                    key={node.id}
                    onClick={() => {
                      if (isProfile) {
                        setSelectedProfile(node.id);
                      }
                    }}
                    style={{ left: `${node.x}%`, top: `${node.y}%` }}
                    type="button"
                  >
                    <span>{profile?.risk ?? "产物"}</span>
                    <strong>{profile?.title ?? node.label}</strong>
                    <em>{profile?.estimated_duration ?? node.text}</em>
                  </button>
                );
              })}
              <button
                className="test-map__long-run action-button action-button--primary"
                disabled={loading || isRunning}
                onClick={() => void startProfile("marathon")}
                type="button"
              >
                <ShieldCheck size={15} />
                直接运行六十轮
              </button>
            </div>
          </section>
        </>
      ) : null}

      {activePage === "monitor" ? (
        <section className="workspace-section">
          <div className="workspace-section__head">
            <Activity size={18} />
            <h3>运行状态</h3>
            <button className="action-button action-button--ghost" onClick={() => void refreshRun()} type="button">
              <RefreshCw size={15} />
              刷新
            </button>
          </div>
          <div className="test-run-grid">
            <article className="test-run-card">
              <div className="framework-node__kind">{activeRun?.run_id ?? "no run"}</div>
              <h4>{activeRun ? statusLabel(activeRun.status) : "还没有测试运行"}</h4>
              <p>{activeRun?.summary.first_failure || "选择测试控制台中的节点后，可以从前端启动对应测试。"}</p>
              <span>{activeRun?.output_dir ?? "output/test_runs"}</span>
              <div className="test-next-actions">
                {isRunning ? (
                  <button className="action-button action-button--ghost" disabled={loading} onClick={() => void cancelActiveRun()} type="button">
                    <XCircle size={15} />
                    取消当前测试
                  </button>
                ) : null}
                <button className="action-button action-button--ghost" disabled={!turns.length} onClick={() => setActivePage("turns")} type="button">
                  查看轮次回放
                </button>
                <button className="action-button action-button--ghost" disabled={!artifacts?.issues.length} onClick={() => setActivePage("issues")} type="button">
                  查看问题诊断
                </button>
              </div>
            </article>
            <article className="test-log-card">
              <div className="framework-node__kind">runner.log</div>
              <pre>{activeRun?.log_tail || "等待测试输出..."}</pre>
            </article>
          </div>
        </section>
      ) : null}

      {activePage === "turns" ? (
        <section className="workspace-section">
          <div className="workspace-section__head">
            <GitBranch size={18} />
            <h3>轮次链路回放</h3>
            <div className="turn-replay-filter">
              <button
                className={turnDisplayMode === "focus" ? "turn-replay-filter__active" : ""}
                onClick={() => setTurnDisplayMode("focus")}
                type="button"
              >
                异常优先
              </button>
              <button
                className={turnDisplayMode === "failed" ? "turn-replay-filter__active" : ""}
                onClick={() => setTurnDisplayMode("failed")}
                type="button"
              >
                只看异常
              </button>
              <button
                className={turnDisplayMode === "all" ? "turn-replay-filter__active" : ""}
                onClick={() => setTurnDisplayMode("all")}
                type="button"
              >
                全部
              </button>
            </div>
          </div>
          {!turns.length ? (
            <article className="workspace-record">
              <h3>当前 run 没有 turn 回放</h3>
              <p>长场景测试完成后，这里会显示 turn 热力图和轮次详情。</p>
            </article>
          ) : null}
          <div className="turn-heatline" aria-label="长场景轮次热力时间轴">
            {turns.map((turn) => (
              <button
                className={`turn-heatline__cell turn-heatline__cell--${turn.status} ${turn.has_prompt_manifest ? "turn-heatline__cell--prompt" : ""} ${turn.has_memory_trace ? "turn-heatline__cell--memory" : ""} ${selectedTurn?.turn_id === turn.turn_id ? "turn-heatline__cell--selected" : ""}`}
                key={`heat-${turn.turn_id}`}
                onClick={() => setSelectedTurnId(turn.turn_id)}
                title={`Turn ${turn.index} · ${statusLabel(turn.status)} · ${turn.has_prompt_manifest ? "Prompt 已记录" : "Prompt 缺失"} · ${turn.has_memory_trace ? "Memory 已记录" : "Memory 缺失"} · ${turn.summary}`}
                type="button"
              >
                <span>{turn.index}</span>
              </button>
            ))}
          </div>
          {selectedTurn ? (
            <article className={`test-turn-focus test-turn-focus--${selectedTurn.status}`}>
              <span>Turn {selectedTurn.index} · {selectedTurn.session_alias || selectedTurn.scenario}</span>
              <strong>{selectedTurn.summary || "没有摘要"}</strong>
              <p>{selectedTurn.has_prompt_manifest ? "Prompt 已记录" : "Prompt 缺失"} · {selectedTurn.has_memory_trace ? "Memory 已记录" : "Memory 缺失"} · issues {selectedTurn.issue_count}</p>
              {selectedTurn.problem_node_id ? (
                <div className="turn-problem-node">
                  <Bug size={14} />
                  <span>{turnProblemLabel(selectedTurn)}</span>
                </div>
              ) : null}
              <div className="test-next-actions">
                <button className="action-button action-button--primary" onClick={() => openTurnOnOrchestration(selectedTurn)} type="button">
                  编排复盘
                </button>
                <button className="action-button action-button--ghost" disabled={!selectedTurn.has_memory_trace} onClick={() => openTurnOnMemorySystem(selectedTurn)} type="button">
                  记忆链路
                </button>
                <button className="action-button action-button--ghost" onClick={() => void openTurnOnSystemGraph(selectedTurn)} type="button">
                  架构定位
                </button>
              </div>
            </article>
          ) : null}
          <div className="turn-replay-grid">
            {visibleTurns.slice(0, turnDisplayMode === "all" ? 60 : 18).map((turn) => (
              <article
                className={`turn-replay-card turn-replay-card--${turn.status}`}
                key={turn.turn_id}
              >
                <span>Turn {turn.index} · {turn.session_alias || turn.scenario}</span>
                <strong>{turn.status === "passed" ? "通过" : turn.status === "warning" ? "警告" : turn.status === "failed" ? "失败" : "未知"}</strong>
                <em>{turn.summary}</em>
                {turn.problem_node_id ? (
                  <b className="turn-replay-card__problem">{turnProblemLabel(turn)}</b>
                ) : null}
                <i>{turn.has_trace ? "trace 可用" : "trace 缺失"} · {turn.has_prompt_manifest ? "Prompt 已记录" : "Prompt 缺失"} · {turn.has_memory_trace ? "Memory 已记录" : "Memory 缺失"} · {turn.artifact_path}</i>
                <div className="turn-replay-card__actions">
                  <button onClick={() => setSelectedTurnId(turn.turn_id)} type="button">
                    选中
                  </button>
                  <button onClick={() => openTurnOnOrchestration(turn)} type="button">
                    编排复盘
                  </button>
                  <button disabled={!turn.has_memory_trace} onClick={() => openTurnOnMemorySystem(turn)} type="button">
                    记忆链路
                  </button>
                  <button onClick={() => void openTurnOnSystemGraph(turn)} type="button">
                    架构定位
                  </button>
                </div>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {activePage === "issues" ? (
        <>
          <section className="test-debug-hero">
            <div className="test-debug-hero__signal">
              <span>{activeRun?.status ? statusLabel(activeRun.status) : "等待运行"}</span>
              <strong>{firstProblemTurn ? `首个异常：Turn ${firstProblemTurn.index}` : "当前没有异常轮次"}</strong>
              <p>
                {firstProblemTurn?.summary
                  || latestSummary.first_failure
                  || "运行完成后，这里会优先显示最值得点击的调试入口。"}
              </p>
            </div>
            <div className="test-debug-hero__stats">
              <span><b>{turnStats.total}</b> turns</span>
              <span><b>{turnStats.failed}</b> failed</span>
              <span><b>{turnStats.warning}</b> warning</span>
              <span><b>{turnStats.promptManifest}</b> prompt</span>
              <span><b>{turnStats.memoryTrace}</b> memory</span>
            </div>
            <div className="test-debug-hero__actions">
              <button className="action-button action-button--primary" disabled={!activeRunId} onClick={() => void openFirstProblemTurn()} type="button">
                <GitBranch size={15} />
                复盘首个异常
              </button>
              <button className="action-button action-button--ghost" disabled={!activeRunId} onClick={() => void openRunOnSystemGraph()} type="button">
                查看架构定位
              </button>
              <button className="action-button action-button--ghost" disabled={!firstProblemTurn?.has_memory_trace} onClick={() => firstProblemTurn ? openTurnOnMemorySystem(firstProblemTurn) : undefined} type="button">
                查看异常记忆
              </button>
            </div>
          </section>

        <section className="workspace-section">
          <div className="workspace-section__head">
            <Bug size={18} />
            <h3>失败问题</h3>
          </div>
          <div className="flow-list">
            {artifacts?.issues.length ? artifacts.issues.slice(0, 8).map((issue, index) => {
              const refs = (issue.graph_refs ?? {}) as IssueGraphRefs;
              const issueTurn = findIssueTurn(issue);
              return (
              <button
                className="flow-row flow-row--button"
                key={`${issue.id ?? index}`}
                onClick={() => openIssueOnOrchestration(issue)}
                type="button"
              >
                <div className="flow-row__index">{index + 1}</div>
                <p>
                  <strong>{String(issue.title ?? issue.id ?? "issue")}</strong>
                  <br />
                  {String(issue.summary ?? "")}
                  <br />
                  <span>
                    {issueTurn
                      ? `编排复盘：Turn ${issueTurn.index} / ${issueTurn.session_alias || issueTurn.scenario}`
                      : `架构定位：${Array.isArray(refs.nodes) ? refs.nodes.join(" / ") : "tests / query-core"}`}
                  </span>
                </p>
              </button>
              );
            }) : null}
            {!artifacts?.issues.length ? (
              <div className="flow-row">
                <div className="flow-row__index">0</div>
                <p>当前 run 没有读取到失败问题。</p>
              </div>
            ) : null}
          </div>
        </section>
        </>
      ) : null}

      {activePage === "artifacts" ? (
        <section className="workspace-section test-artifacts-page">
          <div className="workspace-section__head">
            <ScrollText size={18} />
            <h3>产物档案</h3>
          </div>
          <div className="test-artifacts-layout">
            <aside className="test-artifacts-runs">
              <h4>最近运行</h4>
              {runs.length ? runs.map((run) => (
                <button
                  className={`test-run-row ${activeRunId === run.run_id ? "test-run-row--active" : ""}`}
                  key={run.run_id}
                  onClick={() => selectRun(run)}
                  type="button"
                >
                  <span>{statusLabel(run.status)}</span>
                  <strong>{run.run_id}</strong>
                  <em>{run.summary.passed}/{run.summary.total} passed · {run.summary.failed} failed</em>
                </button>
              )) : (
                <div className="flow-row">
                  <div className="flow-row__index">0</div>
                  <p>还没有可读取的测试运行。</p>
                </div>
              )}
            </aside>
            <article className="test-artifact-reader">
              <div className="turn-replay-filter">
                {(["summary", "report", "issues", "trace", "log", "result"] as ArtifactView[]).map((view) => (
                  <button
                    className={artifactView === view ? "turn-replay-filter__active" : ""}
                    key={view}
                    onClick={() => setArtifactView(view)}
                    type="button"
                  >
                    {artifactViewLabels[view]}
                  </button>
                ))}
              </div>
              <span>{activeRun?.output_dir ?? "output/test_runs"}</span>
              <pre>{artifactContent}</pre>
            </article>
          </div>
        </section>
      ) : null}
    </div>
  );
}
