"use client";

import {
  Activity,
  AlertTriangle,
  Bug,
  CheckCircle2,
  ClipboardList,
  Database,
  FileText,
  GitBranch,
  Layers3,
  ListChecks,
  Loader2,
  MessageSquareWarning,
  PencilLine,
  Play,
  RefreshCw,
  Route,
  SearchCheck,
  TestTube2,
  Wrench,
  XCircle
} from "lucide-react";
import type { CSSProperties } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  cancelTestRun,
  getTestAgentReport,
  getTestArtifacts,
  getTestCases,
  getTestRun,
  listTestProfiles,
  listTestRuns,
  listTestTurns,
  startTestRun,
  type TestAgentFinding,
  type TestAgentReport,
  type TestArtifacts,
  type TestCaseDefinition,
  type TestCaseRegistry,
  type TestProfile,
  type TestRun,
  type TestTurn
} from "@/lib/api";
import { useAppStore } from "@/lib/store";

type TestPage = "run" | "reports" | "analysis" | "cases";
type CaseFilter = "active" | "draft" | "issues" | "legacy";

const fastProfileOrder = ["chain", "functional", "system", "scenario"];
const deepProfileOrder = ["long_core", "long_batches", "marathon"];

const layerMeta: Record<string, { title: string; subtitle: string; intent: string }> = {
  chain: {
    title: "链路级",
    subtitle: "主链冒烟",
    intent: "改动后第一时间运行，确认入口、RuntimeLoop、adapter 没有断。"
  },
  functional: {
    title: "功能级",
    subtitle: "系统合同",
    intent: "验证任务、编排、记忆、灵魂、操作、工具等单系统边界。"
  },
  system: {
    title: "系统级",
    subtitle: "跨系统装配",
    intent: "收口前运行，确认 API、门禁、产物、前端入口和主链装配。"
  },
  scenario: {
    title: "场景合同",
    subtitle: "场景基础设施",
    intent: "验证长场景目录、runner 和报告合同，不等于真实长链压测。"
  },
  long_core: {
    title: "长场景核心",
    subtitle: "真实长链",
    intent: "验证一个完整任务能持续推进、留痕、复盘。"
  },
  long_batches: {
    title: "长场景批量",
    subtitle: "批量稳定性",
    intent: "多场景批量运行，用来发现系统性退化。"
  },
  marathon: {
    title: "六十轮长跑",
    subtitle: "耐久压测",
    intent: "验证长时间运行、记忆压力和编排留痕。"
  }
};

const ownerLabels: Record<string, string> = {
  test_system: "测试系统",
  query_runtime: "入口适配",
  task_system: "任务系统",
  operation_system: "操作系统",
  memory_system: "记忆系统",
  soul_system: "灵魂系统",
  skill_system: "技能系统",
  model_system: "模型运行",
  orchestration_system: "编排系统",
  runtime: "运行时",
  legacy_query: "旧 Query",
  legacy_worker: "旧 Worker"
};

const pages: Array<{ key: TestPage; title: string; subtitle: string }> = [
  { key: "run", title: "测试运行", subtitle: "选择层级并启动验证" },
  { key: "reports", title: "测试报告", subtitle: "对话、操作流、问题节点" },
  { key: "analysis", title: "测试分析", subtitle: "沉淀诊断与后续测试" },
  { key: "cases", title: "用例管理", subtitle: "问题记录与用例规范化" }
];

const caseFilters: Array<{ key: CaseFilter; title: string; subtitle: string }> = [
  { key: "active", title: "正式用例", subtitle: "当前门禁资产" },
  { key: "draft", title: "用例草案", subtitle: "人工或 agent 待补全" },
  { key: "issues", title: "问题记录", subtitle: "对话/开发/skills 发现的问题" },
  { key: "legacy", title: "历史参考", subtitle: "迁移时查证" }
];

const issueOrigins = [
  { value: "conversation", label: "对话中发现" },
  { value: "development", label: "开发任务发现" },
  { value: "skill", label: "Skills 调试发现" },
  { value: "runtime", label: "测试运行发现" },
  { value: "manual", label: "手动记录" }
];

const systems = [
  "编排系统",
  "任务系统",
  "记忆系统",
  "测试系统",
  "操作系统",
  "灵魂系统",
  "前端工作台",
  "模型入口"
];

const runGraphNodes = [
  { id: "chain", label: "链路级", group: "快速门禁", x: 14, y: 55 },
  { id: "functional", label: "功能级", group: "快速门禁", x: 33, y: 32 },
  { id: "system", label: "系统级", group: "快速门禁", x: 52, y: 55 },
  { id: "scenario", label: "场景合同", group: "快速门禁", x: 71, y: 32 },
  { id: "long_core", label: "长场景核心", group: "实测", x: 33, y: 82 },
  { id: "long_batches", label: "长场景批量", group: "实测", x: 58, y: 82 },
  { id: "marathon", label: "六十轮长跑", group: "实测", x: 84, y: 62 }
];

const runGraphEdges = [
  ["chain", "functional", "升级"],
  ["functional", "system", "装配"],
  ["system", "scenario", "场景合同"],
  ["functional", "long_core", "核心实测"],
  ["long_core", "long_batches", "扩大"],
  ["long_batches", "marathon", "压测"]
];

const emptyIssueDraft = {
  title: "",
  origin: "conversation",
  system: "编排系统",
  severity: "medium",
  observed: "",
  expected: "",
  reproduce: "",
  relatedRun: ""
};

const emptyCaseDraft = {
  title: "",
  layer: "functional",
  system: "编排系统",
  trigger: "",
  expected: "",
  assertions: "",
  sourceIssue: ""
};

function statusLabel(status: string) {
  if (status === "running") return "运行中";
  if (status === "passed") return "通过";
  if (status === "failed") return "失败";
  if (status === "warning") return "警告";
  if (status === "cancelled") return "已取消";
  return status || "未知";
}

function statusIcon(status: string) {
  if (status === "running") return <Loader2 className="animate-spin" size={18} />;
  if (status === "passed") return <CheckCircle2 size={18} />;
  if (status === "failed") return <XCircle size={18} />;
  if (status === "warning") return <AlertTriangle size={18} />;
  return <Activity size={18} />;
}

function formatDuration(ms?: number) {
  const value = Number(ms || 0);
  if (!value) return "0s";
  if (value < 1000) return `${Math.round(value)}ms`;
  if (value < 60_000) return `${(value / 1000).toFixed(1)}s`;
  return `${Math.round(value / 60_000)}min`;
}

function ownerLabel(owner: string) {
  return ownerLabels[owner] || owner || "未归属";
}

function profileById(profiles: TestProfile[], profileId: string) {
  return profiles.find((item) => item.id === profileId || item.harness_profile === profileId);
}

function profileTitle(profiles: TestProfile[], profileId: string) {
  return profileById(profiles, profileId)?.title || layerMeta[profileId]?.title || profileId;
}

function graphPoint(id: string) {
  return runGraphNodes.find((node) => node.id === id) ?? runGraphNodes[0];
}

function issueTitle(issue: Record<string, unknown> | TestAgentFinding, index: number) {
  return String("title" in issue ? issue.title || issue.code || `问题 ${index + 1}` : `问题 ${index + 1}`);
}

function issueSummary(issue: Record<string, unknown> | TestAgentFinding) {
  if ("recommendation" in issue) {
    return issue.recommendation || issue.message || "";
  }
  return String(issue.summary || issue.reason || issue.message || "");
}

function runtimeFlowItems(turn: TestTurn | null, artifacts: TestArtifacts | null) {
  const runtime = (turn?.runtime_loop || artifacts?.runtime_loop || {}) as Record<string, unknown>;
  const tools = runtime.tools as Record<string, unknown> | undefined;
  const memory = runtime.memory as Record<string, unknown> | undefined;
  const commits = runtime.commits as Record<string, unknown> | undefined;
  const result = [
    {
      title: "理解与建模",
      detail: turn?.summary || "等待选择测试轮次。",
      state: turn ? statusLabel(turn.status) : "未选择"
    },
    {
      title: "编排决策",
      detail: turn?.problem_node_label ? `定位到 ${turn.problem_node_label}` : "未报告明确问题节点。",
      state: turn?.problem_node_id || "无节点"
    },
    {
      title: "工具与系统调用",
      detail: tools?.requested
        ? `请求 ${(tools.requested as unknown[]).length} 类工具，调用 ${String(tools.call_count ?? 0)} 次。`
        : "当前产物没有工具调用摘要。",
      state: tools?.pairing_ok === false ? "需核查" : "正常"
    },
    {
      title: "记忆与上下文",
      detail: memory
        ? `记忆提交 ${String(memory.committed ?? 0)}，状态记录 ${String(memory.state_events ?? 0)}。`
        : turn?.has_memory_trace
          ? "该轮有记忆链路，可进入记忆系统复盘。"
          : "未记录记忆链路。",
      state: turn?.has_memory_trace ? "有痕迹" : "缺失"
    },
    {
      title: "结果收口",
      detail: commits
        ? `提交 ${String(commits.total ?? 0)} 条，失败 ${String(commits.failed ?? 0)} 条。`
        : `issues ${turn?.issue_count ?? 0}`,
      state: turn ? statusLabel(turn.status) : "未完成"
    }
  ];
  return result;
}

function casesForFilter(registry: TestCaseRegistry | null, filter: CaseFilter) {
  if (!registry) return [];
  if (filter === "legacy") return registry.legacy_cases || [];
  if (filter === "active") return registry.active_cases || [];
  return [];
}

function compactId(id: string) {
  if (!id) return "no-run";
  return id.length > 14 ? `${id.slice(0, 6)}...${id.slice(-5)}` : id;
}

export function TestSystemView() {
  const { setMemoryInspectorTarget, setOrchestrationInspectorTarget, setWorkspaceView } = useAppStore();
  const [activePage, setActivePage] = useState<TestPage>("run");
  const [caseFilter, setCaseFilter] = useState<CaseFilter>("active");
  const [profiles, setProfiles] = useState<TestProfile[]>([]);
  const [registry, setRegistry] = useState<TestCaseRegistry | null>(null);
  const [agentReport, setAgentReport] = useState<TestAgentReport | null>(null);
  const [runs, setRuns] = useState<TestRun[]>([]);
  const [activeRunId, setActiveRunId] = useState("");
  const [activeRun, setActiveRun] = useState<TestRun | null>(null);
  const [artifacts, setArtifacts] = useState<TestArtifacts | null>(null);
  const [turns, setTurns] = useState<TestTurn[]>([]);
  const [selectedProfile, setSelectedProfile] = useState("chain");
  const [selectedTurnId, setSelectedTurnId] = useState("");
  const [issueDraft, setIssueDraft] = useState(emptyIssueDraft);
  const [caseDraft, setCaseDraft] = useState(emptyCaseDraft);
  const [savedIssues, setSavedIssues] = useState<typeof emptyIssueDraft[]>([]);
  const [savedCases, setSavedCases] = useState<typeof emptyCaseDraft[]>([]);
  const [analysisPrompt, setAnalysisPrompt] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const selectedRun = activeRun ?? runs[0] ?? null;
  const isRunning = selectedRun?.status === "running";
  const latestSummary = selectedRun?.summary ?? { total: 0, passed: 0, failed: 0, first_failure: "" };
  const activeCases = registry?.active_cases ?? [];
  const selectedProfileObject = profileById(profiles, selectedProfile);
  const deepProfiles = useMemo(
    () => deepProfileOrder.map((id) => profileById(profiles, id)).filter(Boolean) as TestProfile[],
    [profiles]
  );
  const failedTurns = turns.filter((turn) => turn.status === "failed" || turn.status === "warning");
  const selectedTurn = turns.find((turn) => turn.turn_id === selectedTurnId) ?? failedTurns[0] ?? turns[0] ?? null;
  const visibleCases = casesForFilter(registry, caseFilter);
  const passRate = latestSummary.total > 0 ? Math.round((latestSummary.passed / latestSummary.total) * 100) : 0;
  const issueRecords = useMemo(
    () => [
      ...savedIssues.map((item, index) => ({
        id: `draft-issue-${index}`,
        title: item.title || "未命名问题",
        origin: issueOrigins.find((origin) => origin.value === item.origin)?.label || item.origin,
        system: item.system,
        severity: item.severity,
        summary: item.observed || "尚未填写现象。",
        expected: item.expected,
        reproduce: item.reproduce,
        relatedRun: item.relatedRun
      })),
      ...(artifacts?.issues || []).map((issue, index) => ({
        id: String(issue.id || `artifact-${index}`),
        title: issueTitle(issue, index),
        origin: "测试运行发现",
        system: String(issue.system || issue.owner || selectedRun?.profile || "未知系统"),
        severity: String(issue.severity || "runtime"),
        summary: issueSummary(issue),
        expected: String(issue.expected || ""),
        reproduce: String(issue.reproduce || ""),
        relatedRun: selectedRun?.run_id || ""
      })),
      ...(agentReport?.findings || []).map((finding, index) => ({
        id: `finding-${index}`,
        title: finding.code,
        origin: "测试治理发现",
        system: finding.case_id || finding.path || "测试系统",
        severity: finding.severity,
        summary: finding.message,
        expected: finding.recommendation,
        reproduce: finding.path,
        relatedRun: ""
      }))
    ],
    [agentReport?.findings, artifacts?.issues, savedIssues, selectedRun?.profile, selectedRun?.run_id]
  );
  const operationFlow = runtimeFlowItems(selectedTurn, artifacts);
  const analysisCards = [
    {
      title: "当前诊断",
      value: latestSummary.failed ? "需要复盘" : selectedRun ? "暂无失败" : "等待测试",
      detail: latestSummary.first_failure || selectedTurn?.summary || "选择测试记录后，这里会汇总运行结论。"
    },
    {
      title: "问题节点",
      value: selectedTurn?.problem_node_label || selectedTurn?.problem_node_id || "未定位",
      detail: selectedTurn?.artifact_path || "后续测试 agent 会优先读取该节点、对话和操作流。"
    },
    {
      title: "建议补测",
      value: latestSummary.failed ? "生成复现用例" : "保持门禁",
      detail: latestSummary.failed
        ? "把失败轮次转成用例草案，再进入用例管理补全断言。"
        : "当前可以继续运行功能级或系统级扩大覆盖。"
    }
  ];

  const loadRunArtifacts = useCallback(async (runId: string) => {
    try {
      const [artifactPayload, turnPayload] = await Promise.all([
        getTestArtifacts(runId),
        listTestTurns(runId)
      ]);
      setArtifacts(artifactPayload);
      setTurns(turnPayload);
      setSelectedTurnId((current) => current || turnPayload[0]?.turn_id || "");
    } catch {
      setArtifacts(null);
      setTurns([]);
    }
  }, []);

  const selectRun = useCallback(async (run: TestRun, switchPage = true) => {
    setActiveRunId(run.run_id);
    setActiveRun(run);
    setSelectedTurnId("");
    if (run.status === "running") {
      setArtifacts(null);
      setTurns([]);
    } else {
      await loadRunArtifacts(run.run_id);
    }
    if (switchPage) {
      setActivePage("reports");
    }
  }, [loadRunArtifacts]);

  const loadAll = useCallback(async () => {
    setError("");
    try {
      const [profilePayload, casePayload, reportPayload, runPayload] = await Promise.all([
        listTestProfiles(),
        getTestCases(true),
        getTestAgentReport(),
        listTestRuns(20)
      ]);
      setProfiles(profilePayload);
      setRegistry(casePayload);
      setAgentReport(reportPayload);
      setRuns(runPayload);
      const running = runPayload.find((run) => run.status === "running");
      const latest = running ?? runPayload[0] ?? null;
      if (latest) {
        await selectRun(latest, false);
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加载测试系统失败");
    }
  }, [selectRun]);

  const refreshRun = useCallback(async (runId = activeRunId) => {
    if (!runId) {
      await loadAll();
      return;
    }
    const run = await getTestRun(runId);
    setActiveRun(run);
    const runPayload = await listTestRuns(20);
    setRuns(runPayload);
    if (run.status !== "running") {
      await loadRunArtifacts(run.run_id);
    }
  }, [activeRunId, loadAll, loadRunArtifacts]);

  async function startProfile(profileId = selectedProfile) {
    const profile = profileById(profiles, profileId);
    if (profile?.requires_confirmation && !window.confirm("该测试可能耗时较长，确认现在运行吗？")) {
      return;
    }
    setLoading(true);
    setError("");
    try {
      const run = await startTestRun(profileId);
      setActiveRunId(run.run_id);
      setActiveRun(run);
      setArtifacts(null);
      setTurns([]);
      setActivePage("run");
      setRuns(await listTestRuns(20));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "启动测试失败");
    } finally {
      setLoading(false);
    }
  }

  async function cancelActiveRun() {
    if (!activeRunId) return;
    setLoading(true);
    try {
      const run = await cancelTestRun(activeRunId);
      setActiveRun(run);
      setRuns(await listTestRuns(20));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "取消测试失败");
    } finally {
      setLoading(false);
    }
  }

  function openTurnOnOrchestration(turn: TestTurn) {
    if (!activeRunId) return;
    setOrchestrationInspectorTarget({
      source: "test-system",
      runId: activeRunId,
      turnId: turn.turn_id,
      turnIndex: turn.index,
      artifactPath: turn.artifact_path,
      reason: turn.summary || "从测试报告复盘该轮 RuntimeLoop。"
    });
    setWorkspaceView("experiments");
  }

  function openTurnOnMemory(turn: TestTurn) {
    if (!activeRunId) return;
    setMemoryInspectorTarget({
      source: "test-system",
      runId: activeRunId,
      turnId: turn.turn_id,
      turnIndex: turn.index,
      layer: "state",
      reason: turn.summary || "从测试报告查看该轮记忆链路。"
    });
    setWorkspaceView("memory");
  }

  function saveIssueDraft() {
    if (!issueDraft.title.trim() && !issueDraft.observed.trim()) return;
    setSavedIssues((items) => [{ ...issueDraft, relatedRun: issueDraft.relatedRun || selectedRun?.run_id || "" }, ...items]);
    setIssueDraft(emptyIssueDraft);
    setCaseFilter("issues");
  }

  function saveCaseDraft() {
    if (!caseDraft.title.trim() && !caseDraft.expected.trim()) return;
    setSavedCases((items) => [{ ...caseDraft }, ...items]);
    setCaseDraft(emptyCaseDraft);
    setCaseFilter("draft");
  }

  function turnFailureIntoDraft() {
    if (!selectedTurn) return;
    setCaseDraft({
      title: selectedTurn.summary || `复现 ${selectedTurn.scenario || selectedTurn.turn_id}`,
      layer: "scenario",
      system: selectedTurn.problem_node_label || "编排系统",
      trigger: selectedTurn.session_alias || selectedTurn.scenario || "",
      expected: "该轮应完成目标，并在 RuntimeLoop、记忆和报告中留下可复盘痕迹。",
      assertions: selectedTurn.issue_count ? "失败问题被定位；问题节点可追踪；复现后报告可读。" : "对话轮次通过；操作流完整；无异常问题节点。",
      sourceIssue: selectedTurn.turn_id
    });
    setActivePage("cases");
    setCaseFilter("draft");
  }

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  useEffect(() => {
    if (!activeRunId || selectedRun?.status !== "running") return;
    const timer = window.setInterval(() => {
      void refreshRun(activeRunId);
    }, 2200);
    return () => window.clearInterval(timer);
  }, [activeRunId, refreshRun, selectedRun?.status]);

  return (
    <div className="workspace-view test-system-view">
      <header className="workspace-view__header">
        <div>
          <p className="workspace-view__eyebrow">Test System</p>
          <h2 className="workspace-view__title">测试系统</h2>
        </div>
        <div className="workspace-view__actions">
          <button className="action-button action-button--ghost" onClick={() => void loadAll()} type="button">
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
            运行所选
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
        {pages.map((page) => (
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

      {activePage === "run" ? (
        <>
          <section className="test-run-hero">
            <div className="test-run-hero__copy">
              <span>Run Console</span>
              <strong>从实际开发问题出发，选择合适层级验证系统健康</strong>
              <p>
                对话里发现异常、开发任务里写了新 skills、或改动了 RuntimeLoop，都先在这里选择测试层级。
                快速门禁用于日常检查，长场景实测用于验证持久任务。
              </p>
            </div>
            <div className={`test-run-status-card test-run-status-card--${selectedRun?.status || "idle"}`}>
              <div>
                {statusIcon(selectedRun?.status || "")}
                <span>最近运行</span>
              </div>
              <strong>{selectedRun ? statusLabel(selectedRun.status) : "暂无记录"}</strong>
              <p>{selectedRun ? `${profileTitle(profiles, selectedRun.profile)} · ${compactId(selectedRun.run_id)}` : "选择下方节点开始第一次测试。"}</p>
              {isRunning ? (
                <div className="test-run-status-card__actions">
                  <button className="action-button action-button--ghost" onClick={() => setActivePage("reports")} type="button">
                    查看报告
                  </button>
                  <button className="action-button action-button--danger" disabled={loading} onClick={() => void cancelActiveRun()} type="button">
                    取消运行
                  </button>
                </div>
              ) : null}
            </div>
          </section>

          <section className="workspace-section test-run-console">
            <div className="test-run-console__panel">
              <div className="workspace-section__head">
                <Layers3 size={18} />
                <h3>测试运行图</h3>
              </div>
              <div className="test-run-selector">
                <label>
                  <span>运行目标</span>
                  <select value={selectedProfile} onChange={(event) => setSelectedProfile(event.target.value)}>
                    <optgroup label="快速门禁">
                      {fastProfileOrder.map((layer) => (
                        <option key={layer} value={layer}>{layerMeta[layer].title}</option>
                      ))}
                    </optgroup>
                    <optgroup label="长场景实测">
                      {deepProfiles.map((profile) => (
                        <option key={profile.id} value={profile.id}>{profile.title}</option>
                      ))}
                    </optgroup>
                  </select>
                </label>
                <div>
                  <strong>{profileTitle(profiles, selectedProfile)}</strong>
                  <span>{selectedProfileObject?.estimated_duration || "耗时未知"} · {layerMeta[selectedProfile]?.intent || selectedProfileObject?.description}</span>
                </div>
                <button
                  className="action-button action-button--primary"
                  disabled={loading || isRunning || !selectedProfileObject}
                  onClick={() => void startProfile(selectedProfile)}
                  type="button"
                >
                  <Play size={15} />
                  运行
                </button>
              </div>
              <div className="test-run-map">
                <svg className="test-run-map__edges" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden>
                  {runGraphEdges.map(([fromId, toId, label]) => {
                    const from = graphPoint(fromId);
                    const to = graphPoint(toId);
                    return (
                      <g key={`${fromId}-${toId}`}>
                        <line x1={from.x} x2={to.x} y1={from.y} y2={to.y} />
                        <text x={(from.x + to.x) / 2} y={(from.y + to.y) / 2 - 2}>{label}</text>
                      </g>
                    );
                  })}
                </svg>
                {runGraphNodes.map((node) => {
                  const profile = profileById(profiles, node.id);
                  const isSelected = selectedProfile === node.id;
                  const caseCount = registry?.profiles?.[node.id]?.case_count ?? activeCases.filter((item) => item.layer === node.id).length;
                  return (
                    <button
                      className={`test-run-map-node ${isSelected ? "test-run-map-node--active" : ""} ${node.group === "实测" ? "test-run-map-node--deep" : ""}`}
                      key={node.id}
                      onClick={() => setSelectedProfile(node.id)}
                      style={{ "--x": `${node.x}%`, "--y": `${node.y}%` } as CSSProperties}
                      type="button"
                    >
                      <span>{node.group}</span>
                      <strong>{profile?.title || node.label}</strong>
                      <em>{profile?.estimated_duration || layerMeta[node.id]?.subtitle || "未配置"}</em>
                      <small>{node.group === "实测" ? profile?.risk || "高耗时" : `${caseCount} 个正式用例`}</small>
                    </button>
                  );
                })}
                <div className="test-run-map__legend">
                  <span>快速门禁：日常开发</span>
                  <span>长场景实测：持久任务验证</span>
                </div>
              </div>
            </div>

            <aside className="test-run-side">
              <article>
                <span>本轮结果</span>
                <strong>{latestSummary.passed}/{latestSummary.total}</strong>
                <p>{latestSummary.failed ? latestSummary.first_failure || "存在失败项，进入报告复盘。" : "最近运行没有失败项。"}</p>
              </article>
              <article>
                <span>测试资产</span>
                <strong>{registry?.active_cases.length ?? 0}</strong>
                <p>正式用例覆盖链路级、功能级、系统级与场景合同。</p>
              </article>
              <article>
                <span>真实问题入口</span>
                <strong>{issueRecords.length}</strong>
                <p>对话、开发任务、skills 调试和运行失败都统一记录为测试问题。</p>
                <button className="action-button action-button--ghost" onClick={() => { setActivePage("cases"); setCaseFilter("issues"); }} type="button">
                  <MessageSquareWarning size={15} />
                  记录问题
                </button>
              </article>
            </aside>
          </section>
        </>
      ) : null}

      {activePage === "reports" ? (
        <section className="workspace-section test-report-layout">
          <aside className="test-report-runs">
            <div className="workspace-section__head">
              <FileText size={18} />
              <h3>测试记录</h3>
            </div>
            {runs.map((run) => (
              <button
                className={`test-run-row ${selectedRun?.run_id === run.run_id ? "test-run-row--active" : ""}`}
                key={run.run_id}
                onClick={() => void selectRun(run)}
                type="button"
              >
                <span>{statusLabel(run.status)}</span>
                <strong>{profileTitle(profiles, run.profile)}</strong>
                <em>{run.summary.passed}/{run.summary.total} · {formatDuration(run.duration_ms)}</em>
              </button>
            ))}
          </aside>

          <div className="test-report-main">
            <section className="test-report-summary">
              <div className="test-report-score" style={{ "--score": `${passRate}%` } as CSSProperties}>
                <strong>{passRate}</strong>
                <span>通过率</span>
              </div>
              <div>
                <span>{selectedRun ? compactId(selectedRun.run_id) : "no run"}</span>
                <strong>{selectedRun ? `${profileTitle(profiles, selectedRun.profile)} · ${statusLabel(selectedRun.status)}` : "还没有测试记录"}</strong>
                <p>{latestSummary.first_failure || "报告只展示人能读懂的对话、操作流程和问题节点。原始产物留给后端调试，不作为主阅读界面。"}</p>
              </div>
              <div className="test-report-summary__stats">
                <em>{latestSummary.passed} 通过</em>
                <em>{latestSummary.failed} 失败</em>
                <em>{formatDuration(selectedRun?.duration_ms)} 耗时</em>
              </div>
            </section>

            <section className="test-report-readable">
              <article className="test-conversation-panel">
                <div className="workspace-section__head">
                  <MessageSquareWarning size={18} />
                  <h3>对话与轮次</h3>
                </div>
                <div className="test-turn-list">
                  {turns.length ? turns.map((turn) => (
                    <button
                      className={`test-turn-item test-turn-item--${turn.status} ${selectedTurn?.turn_id === turn.turn_id ? "test-turn-item--active" : ""}`}
                      key={turn.turn_id}
                      onClick={() => setSelectedTurnId(turn.turn_id)}
                      type="button"
                    >
                      <span>Turn {turn.index} · {turn.session_alias || turn.scenario}</span>
                      <strong>{turn.summary || "轮次摘要为空"}</strong>
                      <em>{statusLabel(turn.status)} · issues {turn.issue_count} · {turn.has_prompt_manifest ? "Prompt 有痕迹" : "Prompt 缺失"} · {turn.has_memory_trace ? "Memory 有痕迹" : "Memory 缺失"}</em>
                    </button>
                  )) : (
                    <div className="test-empty-readable">
                      <TestTube2 size={18} />
                      <strong>暂无可读轮次</strong>
                      <span>选择已完成的测试记录后，会展示对话轮次。</span>
                    </div>
                  )}
                </div>
              </article>

              <article className="test-operation-panel">
                <div className="workspace-section__head">
                  <Route size={18} />
                  <h3>Agent 操作流程</h3>
                </div>
                <div className="test-operation-flow">
                  {operationFlow.map((item, index) => (
                    <div className="test-operation-step" key={item.title}>
                      <i>{index + 1}</i>
                      <div>
                        <span>{item.state}</span>
                        <strong>{item.title}</strong>
                        <p>{item.detail}</p>
                      </div>
                    </div>
                  ))}
                </div>
                {selectedTurn ? (
                  <div className="test-report-actions">
                    <button className="action-button action-button--primary" onClick={() => openTurnOnOrchestration(selectedTurn)} type="button">
                      <GitBranch size={15} />
                      编排复盘
                    </button>
                    <button className="action-button action-button--ghost" disabled={!selectedTurn.has_memory_trace} onClick={() => openTurnOnMemory(selectedTurn)} type="button">
                      <Database size={15} />
                      记忆链路
                    </button>
                    <button className="action-button action-button--ghost" onClick={turnFailureIntoDraft} type="button">
                      <PencilLine size={15} />
                      转用例草案
                    </button>
                  </div>
                ) : null}
              </article>
            </section>

            <section className="test-problem-panel">
              <div className="workspace-section__head">
                <Bug size={18} />
                <h3>问题节点</h3>
              </div>
              {selectedTurn || issueRecords.length ? (
                <div className="test-problem-grid">
                  <article>
                    <span>当前轮次定位</span>
                    <strong>{selectedTurn?.problem_node_label || selectedTurn?.problem_node_id || "未定位到明确节点"}</strong>
                    <p>{selectedTurn?.summary || latestSummary.first_failure || "没有失败摘要。"}</p>
                  </article>
                  {issueRecords.slice(0, 3).map((issue) => (
                    <article key={issue.id}>
                      <span>{issue.origin} · {issue.severity}</span>
                      <strong>{issue.title}</strong>
                      <p>{String(issue.summary || "")}</p>
                    </article>
                  ))}
                </div>
              ) : (
                <div className="test-empty-readable">
                  <CheckCircle2 size={18} />
                  <strong>暂无问题节点</strong>
                  <span>测试通过时这里保持安静；发现问题后再进入分析或用例管理。</span>
                </div>
              )}
            </section>
          </div>
        </section>
      ) : null}

      {activePage === "analysis" ? (
        <section className="workspace-section test-analysis-page">
          <div className="test-analysis-hero">
            <div>
              <span>Analysis Interface</span>
              <strong>给后续测试 Agent 使用的分析入口</strong>
              <p>这里先做人类可读的诊断面板和结构化分析请求。后面接子 agent 时，它应读取测试记录、问题记录、用例草案和运行痕迹来生成建议。</p>
            </div>
            <SearchCheck size={34} />
          </div>

          <div className="test-analysis-grid">
            {analysisCards.map((card) => (
              <article key={card.title}>
                <span>{card.title}</span>
                <strong>{card.value}</strong>
                <p>{card.detail}</p>
              </article>
            ))}
          </div>

          <div className="test-analysis-workbench">
            <article>
              <div className="workspace-section__head">
                <ListChecks size={18} />
                <h3>待分析材料</h3>
              </div>
              <ul>
                <li>运行记录：{selectedRun ? compactId(selectedRun.run_id) : "未选择"}</li>
                <li>对话轮次：{turns.length} 条</li>
                <li>问题记录：{issueRecords.length} 条</li>
                <li>用例草案：{savedCases.length} 条</li>
              </ul>
            </article>
            <article>
              <div className="workspace-section__head">
                <Wrench size={18} />
                <h3>分析请求草稿</h3>
              </div>
              <textarea
                onChange={(event) => setAnalysisPrompt(event.target.value)}
                placeholder="例如：请分析这次 skills 调试失败是不是操作系统工具合同的问题，并生成一个功能级复现用例。"
                value={analysisPrompt}
              />
              <div className="test-report-actions">
                <button className="action-button action-button--ghost" disabled={!analysisPrompt.trim()} type="button">
                  保存分析请求
                </button>
                <button className="action-button action-button--primary" disabled type="button">
                  后续接入测试 Agent
                </button>
              </div>
            </article>
          </div>
        </section>
      ) : null}

      {activePage === "cases" ? (
        <section className="workspace-section test-case-page">
          <div className="test-case-switcher">
            {caseFilters.map((filter) => (
              <button
                className={`test-case-status ${caseFilter === filter.key ? "test-case-status--active" : ""}`}
                key={filter.key}
                onClick={() => setCaseFilter(filter.key)}
                type="button"
              >
                <span>{filter.subtitle}</span>
                <strong>
                  {filter.key === "draft"
                    ? savedCases.length
                    : filter.key === "issues"
                      ? issueRecords.length
                      : casesForFilter(registry, filter.key).length}
                </strong>
                <small>{filter.title}</small>
              </button>
            ))}
          </div>

          {caseFilter === "issues" ? (
            <div className="test-management-grid">
              <article className="test-form-card">
                <div className="workspace-section__head">
                  <MessageSquareWarning size={18} />
                  <h3>记录真实问题</h3>
                </div>
                <label>
                  <span>问题标题</span>
                  <input value={issueDraft.title} onChange={(event) => setIssueDraft({ ...issueDraft, title: event.target.value })} placeholder="例如：skills 运行后没有触发工具结果回写" />
                </label>
                <div className="test-form-row">
                  <label>
                    <span>来源</span>
                    <select value={issueDraft.origin} onChange={(event) => setIssueDraft({ ...issueDraft, origin: event.target.value })}>
                      {issueOrigins.map((origin) => <option key={origin.value} value={origin.value}>{origin.label}</option>)}
                    </select>
                  </label>
                  <label>
                    <span>归属系统</span>
                    <select value={issueDraft.system} onChange={(event) => setIssueDraft({ ...issueDraft, system: event.target.value })}>
                      {systems.map((system) => <option key={system} value={system}>{system}</option>)}
                    </select>
                  </label>
                </div>
                <label>
                  <span>观察到的现象</span>
                  <textarea value={issueDraft.observed} onChange={(event) => setIssueDraft({ ...issueDraft, observed: event.target.value })} placeholder="写清楚你在对话、开发任务或运行里看到的问题。" />
                </label>
                <label>
                  <span>期望行为</span>
                  <textarea value={issueDraft.expected} onChange={(event) => setIssueDraft({ ...issueDraft, expected: event.target.value })} placeholder="写清楚系统本来应该怎么表现。" />
                </label>
                <label>
                  <span>复现线索</span>
                  <input value={issueDraft.reproduce} onChange={(event) => setIssueDraft({ ...issueDraft, reproduce: event.target.value })} placeholder="会话、任务、skills、运行记录或触发步骤" />
                </label>
                <button className="action-button action-button--primary" onClick={saveIssueDraft} type="button">
                  <PencilLine size={15} />
                  保存问题记录
                </button>
              </article>

              <article className="test-normalized-list">
                <div className="workspace-section__head">
                  <Bug size={18} />
                  <h3>问题池</h3>
                </div>
                {issueRecords.length ? issueRecords.map((issue) => (
                  <div className="test-normalized-item" key={issue.id}>
                    <span>{issue.origin} · {issue.system} · {issue.severity}</span>
                    <strong>{issue.title}</strong>
                    <p>{String(issue.summary || "")}</p>
                    {issue.expected ? <em>期望：{issue.expected}</em> : null}
                  </div>
                )) : (
                  <div className="test-empty-readable">
                    <CheckCircle2 size={18} />
                    <strong>还没有问题记录</strong>
                    <span>对话和开发任务里发现的异常，都可以先记在这里。</span>
                  </div>
                )}
              </article>
            </div>
          ) : null}

          {caseFilter === "draft" ? (
            <div className="test-management-grid">
              <article className="test-form-card">
                <div className="workspace-section__head">
                  <ClipboardList size={18} />
                  <h3>新增用例草案</h3>
                </div>
                <label>
                  <span>用例目标</span>
                  <input value={caseDraft.title} onChange={(event) => setCaseDraft({ ...caseDraft, title: event.target.value })} placeholder="例如：验证 skills 工具调用结果能进入 RuntimeLoop" />
                </label>
                <div className="test-form-row">
                  <label>
                    <span>测试层级</span>
                    <select value={caseDraft.layer} onChange={(event) => setCaseDraft({ ...caseDraft, layer: event.target.value })}>
                      {fastProfileOrder.map((layer) => <option key={layer} value={layer}>{layerMeta[layer].title}</option>)}
                    </select>
                  </label>
                  <label>
                    <span>归属系统</span>
                    <select value={caseDraft.system} onChange={(event) => setCaseDraft({ ...caseDraft, system: event.target.value })}>
                      {systems.map((system) => <option key={system} value={system}>{system}</option>)}
                    </select>
                  </label>
                </div>
                <label>
                  <span>触发条件</span>
                  <textarea value={caseDraft.trigger} onChange={(event) => setCaseDraft({ ...caseDraft, trigger: event.target.value })} placeholder="用户输入、任务配置、skills 内容或系统状态。" />
                </label>
                <label>
                  <span>期望行为</span>
                  <textarea value={caseDraft.expected} onChange={(event) => setCaseDraft({ ...caseDraft, expected: event.target.value })} placeholder="系统应该完成什么，并留下哪些可复盘痕迹。" />
                </label>
                <label>
                  <span>断言</span>
                  <textarea value={caseDraft.assertions} onChange={(event) => setCaseDraft({ ...caseDraft, assertions: event.target.value })} placeholder="一行一个断言，例如：工具调用成对；报告展示问题节点；记忆链路存在。" />
                </label>
                <button className="action-button action-button--primary" onClick={saveCaseDraft} type="button">
                  <PencilLine size={15} />
                  保存草案
                </button>
              </article>

              <article className="test-normalized-list">
                <div className="workspace-section__head">
                  <ListChecks size={18} />
                  <h3>用例草案池</h3>
                </div>
                {savedCases.length ? savedCases.map((item, index) => (
                  <div className="test-normalized-item" key={`${item.title}-${index}`}>
                    <span>{layerMeta[item.layer]?.title || item.layer} · {item.system}</span>
                    <strong>{item.title || "未命名用例"}</strong>
                    <p>{item.expected || "尚未填写期望行为。"}</p>
                    {item.assertions ? <em>{item.assertions}</em> : null}
                  </div>
                )) : (
                  <div className="test-empty-readable">
                    <TestTube2 size={18} />
                    <strong>还没有草案</strong>
                    <span>可以人工填写，也可以从测试报告里的失败轮次一键转入。</span>
                  </div>
                )}
              </article>
            </div>
          ) : null}

          {caseFilter === "active" || caseFilter === "legacy" ? (
            <div className="test-normalized-list test-normalized-list--wide">
              <div className="workspace-section__head">
                <ClipboardList size={18} />
                <h3>{caseFilter === "active" ? "正式用例" : "历史参考"}</h3>
              </div>
              {visibleCases.map((testCase) => (
                <div className="test-normalized-item" key={testCase.case_id}>
                  <span>{layerMeta[testCase.layer]?.title || testCase.layer} · {ownerLabel(testCase.owner_system)}</span>
                  <strong>{testCase.title}</strong>
                  <p>{testCase.description || testCase.reason || "该用例尚未补充说明。"}</p>
                  <div className="test-case-tags">
                    {testCase.profiles.map((profile) => <em key={profile}>{profileTitle(profiles, profile)}</em>)}
                    {testCase.tags.slice(0, 4).map((tag) => <em key={tag}>{tag}</em>)}
                  </div>
                  <details>
                    <summary>技术路径</summary>
                    <code>{testCase.path}</code>
                  </details>
                </div>
              ))}
              {!visibleCases.length ? (
                <div className="test-empty-readable">
                  <CheckCircle2 size={18} />
                  <strong>当前分类为空</strong>
                  <span>没有需要展示的用例。</span>
                </div>
              ) : null}
            </div>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
