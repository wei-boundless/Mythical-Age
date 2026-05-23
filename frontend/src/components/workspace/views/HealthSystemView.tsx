"use client";

import {
  Activity,
  AlertTriangle,
  Bug,
  CheckCircle2,
  Clock3,
  ClipboardList,
  FilePlus2,
  GitBranch,
  HeartPulse,
  Layers3,
  ListChecks,
  Loader2,
  Pencil,
  Play,
  RefreshCw,
  Save,
  Search,
  Route,
  Trash2,
  ShieldCheck,
  Stethoscope,
  TestTube2,
  XCircle
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { HealthAgentDock } from "@/components/health/HealthAgentDock";
import { HealthTraceTimeline } from "@/components/health/HealthTraceTimeline";
import { useConfirmDialog } from "@/components/layout/ConfirmDialogProvider";
import {
  cancelTestRun,
  createHealthIssue,
  createHealthManagementCommand,
  createManagedTestCase,
  deleteManagedTestCase,
  getHarnessMap,
  getHealthAgentRunTraceReport,
  getHealthSystemOverview,
  getHealthWorkbenchOverview,
  getTestAgentReport,
  getTestArtifacts,
  getTestCases,
  getTestCaseTemplates,
  getTestRun,
  listLongScenarios,
  listTestProfiles,
  listTestRuns,
  promoteFailedTurnsToRegressionSamples,
  refreshRegressionSampleVerdict,
  rerunRegressionSample,
  startTestRun,
  type HarnessMap,
  type HarnessMapCase,
  type TestCaseTemplate,
  type HealthAgentRun,
  type HealthIssue,
  type HealthSystemOverview,
  type HealthTraceReport,
  type HealthWorkbenchDiagnosisItem,
  type HealthWorkbenchFailureChain,
  type HealthWorkbenchInboxItem,
  type HealthWorkbenchOverview,
  type HealthWorkbenchRecoveryItem,
  type LongScenarioCatalog,
  type LongScenarioDefinition,
  type TestAgentReport,
  type TestArtifacts,
  type TestCaseRegistry,
  type TestProfile,
  type TestRun,
  type RegressionSample,
  type VerificationRun,
} from "@/lib/api";

type HealthPage = "overview" | "issues" | "verify" | "time";
type ProblemReportTab = "details" | "analysis" | "chain" | "closure";
type TokenChartMode = "daily" | "six_hour";
type ProblemKind = "system" | "test";
type ScenarioCategory = string;
type ScenarioCategoryFilter = string;
type ScenarioEditMode = "create" | "manage";
type ScenarioTurnDraft = {
  turn_id: string;
  user: string;
  expected: string;
  assistant_hint: string;
};

const fastProfileOrder = ["chain", "functional", "system"];
const deepProfileOrder = ["long_core", "long_batches", "marathon"];
const defaultLongScenarioProfile = "long_core";
const defaultScenarioCategory = "连续推进";
const scenarioEditPageSize = 10;
const scenarioLibraryPageSize = 8;

const scenarioCategories: Array<{ key: ScenarioCategoryFilter; title: string; subtitle: string }> = [
  { key: "all", title: "全部", subtitle: "所有长场景" },
  { key: "连续推进", title: "连续推进", subtitle: "多轮任务不断链" },
  { key: "记忆恢复", title: "记忆恢复", subtitle: "状态、偏好、上下文" },
  { key: "工具操作", title: "工具操作", subtitle: "执行、文件、外部能力" },
  { key: "异常恢复", title: "异常恢复", subtitle: "失败后继续推进" },
  { key: "耐久压测", title: "耐久压测", subtitle: "长跑与批量" }
];

const layerMeta: Record<string, { title: string; subtitle: string; intent: string }> = {
  chain: { title: "链路级", subtitle: "主链冒烟", intent: "改动后第一时间运行，确认入口、运行时链路和适配层没有断。" },
  functional: { title: "功能级", subtitle: "系统合同", intent: "验证任务、编排、记忆、灵魂、操作、工具等单系统边界。" },
  system: { title: "系统级", subtitle: "跨系统装配", intent: "收口前运行，确认 API、门禁、产物、前端入口和主链装配。" },
  scenario: { title: "场景合同", subtitle: "场景基础设施", intent: "验证长场景目录、runner 和报告合同。" },
  long_core: { title: "长场景核心", subtitle: "真实长链", intent: "验证一个完整任务能持续推进、留痕、复盘。" },
  long_batches: { title: "长场景批量", subtitle: "批量稳定性", intent: "多场景批量运行，用来发现系统性退化。" },
  marathon: { title: "六十轮长跑", subtitle: "耐久压测", intent: "验证长时间运行、记忆压力和编排留痕。" }
};

const ownerLabels: Record<string, string> = {
  test_system: "测试系统",
  query_runtime: "入口适配",
  task_system: "任务系统",
  capability_system: "能力系统",
  memory_system: "记忆系统",
  soul_system: "灵魂系统",
  skill_system: "技能系统",
  model_system: "模型运行",
  orchestration_system: "编排系统",
  runtime: "运行时",
  runtime_loop: "运行链路",
  prompt: "提示上下文",
  memory: "记忆系统",
  operation: "能力系统",
  soul: "灵魂系统",
};

const pages: Array<{ key: HealthPage; title: string; subtitle: string; icon: typeof HeartPulse }> = [
  { key: "overview", title: "总览", subtitle: "状态、验证、问题", icon: HeartPulse },
  { key: "verify", title: "验证中心", subtitle: "运行与复盘", icon: TestTube2 },
  { key: "issues", title: "问题报告", subtitle: "分类与链路", icon: ListChecks },
  { key: "time", title: "时间统计", subtitle: "耗时与 token", icon: Clock3 }
];

const problemReportTabs: Array<{ key: ProblemReportTab; title: string; subtitle: string }> = [
  { key: "details", title: "问题详情", subtitle: "对象、分层、证据" },
  { key: "analysis", title: "问题分析", subtitle: "哪里、为什么、怎么处理" },
  { key: "chain", title: "链路追踪", subtitle: "节点关系与事件" },
  { key: "closure", title: "验证闭环", subtitle: "复跑与结论" }
];

function text(value: unknown, fallback = "-") {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }
  if (Array.isArray(value)) {
    return value.length ? value.join(" / ") : fallback;
  }
  return String(value);
}

function compactId(value: string) {
  if (!value) {
    return "-";
  }
  return value.length > 30 ? `${value.slice(0, 14)}...${value.slice(-10)}` : value;
}

function draftSlug(value: string) {
  const slug = value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fa5]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 42);
  return slug || "health_asset";
}

function isLongScenarioProfile(profile: string) {
  return deepProfileOrder.includes(profile);
}

function isLongScenarioTemplate(template: TestCaseTemplate) {
  return template.layer === "scenario" || template.profiles.some(isLongScenarioProfile);
}

function isLongScenarioCase(testCase: HarnessMapCase) {
  return testCase.status === "active"
    && (
      testCase.profiles.some(isLongScenarioProfile)
      || testCase.tags.includes("long_scenario")
      || (Array.isArray(testCase.scenario_turns) && testCase.scenario_turns.length > 0)
    );
}

function scenarioCategoryLabel(category: ScenarioCategoryFilter) {
  if (category === "all") return "全部";
  return scenarioCategories.find((item) => item.key === category)?.title || category || "未分类";
}

function pageCount(total: number, pageSize: number) {
  return Math.max(1, Math.ceil(total / pageSize));
}

function pageSlice<T>(items: T[], page: number, pageSize: number) {
  return items.slice(page * pageSize, page * pageSize + pageSize);
}

function pageRangeLabel(total: number, page: number, pageSize: number) {
  if (total <= 0) return "0 / 0";
  return `${page * pageSize + 1}-${Math.min(total, (page + 1) * pageSize)} / ${total}`;
}

function scenarioCategoryOf(testCase: HarnessMapCase): ScenarioCategory {
  const tagged = testCase.tags
    .map((tag) => tag.match(/^scenario_category:(.+)$/)?.[1])
    .find(Boolean);
  if (tagged) {
    return tagged;
  }
  const textBlob = `${testCase.title} ${testCase.problem_statement} ${testCase.behavior_under_test} ${testCase.tags.join(" ")} ${testCase.profiles.join(" ")}`.toLowerCase();
  if (textBlob.includes("marathon") || textBlob.includes("耐久") || textBlob.includes("长跑") || textBlob.includes("批量")) return "耐久压测";
  if (textBlob.includes("memory") || textBlob.includes("记忆") || textBlob.includes("状态") || textBlob.includes("上下文")) return "记忆恢复";
  if (textBlob.includes("tool") || textBlob.includes("operation") || textBlob.includes("工具") || textBlob.includes("执行") || textBlob.includes("文件")) return "工具操作";
  if (textBlob.includes("recover") || textBlob.includes("fallback") || textBlob.includes("异常") || textBlob.includes("失败") || textBlob.includes("恢复")) return "异常恢复";
  if (textBlob.includes("long") || textBlob.includes("多轮") || textBlob.includes("持续") || textBlob.includes("推进")) return "连续推进";
  return "未分类";
}

function primaryScenarioProfile(testCase: HarnessMapCase) {
  return testCase.profiles.find(isLongScenarioProfile) || testCase.profiles[0] || defaultLongScenarioProfile;
}

function emptyScenarioTurn(index = 1): ScenarioTurnDraft {
  return {
    turn_id: `turn-${index}`,
    user: "",
    expected: "",
    assistant_hint: ""
  };
}

function scenarioTurnsOf(testCase: HarnessMapCase): ScenarioTurnDraft[] {
  const turns = Array.isArray(testCase.scenario_turns) ? testCase.scenario_turns : [];
  if (turns.length) {
    return turns.map((turn, index) => ({
      turn_id: turn.turn_id || `turn-${index + 1}`,
      user: turn.user || "",
      expected: turn.expected || "",
      assistant_hint: turn.assistant_hint || ""
    }));
  }
  return [
    {
      turn_id: "turn-1",
      user: testCase.behavior_under_test || testCase.title,
      expected: testCase.pass_criteria[0] || "",
      assistant_hint: ""
    }
  ];
}

function categoryFromRealScenario(category: string): ScenarioCategory {
  if (category === "acceptance") return "连续推进";
  if (category === "followup") return "工具操作";
  if (category === "memory") return "记忆恢复";
  if (category === "safety") return "异常恢复";
  if (category === "stress") return "耐久压测";
  return category || "未分类";
}

function sourceScenarioId(testCase: HarnessMapCase) {
  return String(testCase.traceability?.source_scenario_id || "").trim();
}

function longScenarioToCase(scenario: LongScenarioDefinition): HarnessMapCase {
  const category = categoryFromRealScenario(scenario.category);
  const profileRefs = scenario.profile_refs.length ? scenario.profile_refs : [defaultLongScenarioProfile];
  const primaryCriterion = scenario.assertions[0] || "真实长情景运行应按轮次输出证据、断言和报告。";
  return {
    case_id: `long-scenario:${scenario.scenario_id}`,
    title: scenario.title,
    layer: "scenario",
    path: "backend/tests/system_eval/long_scenarios.py",
    owner_system: "test_system",
    runner: "harness",
    status: "active",
    profiles: profileRefs,
    description: scenario.goal,
    assertions: scenario.assertions,
    tags: [
      "long_scenario",
      "test_system_catalog",
      `scenario_category:${category}`,
      ...scenario.coverage.map((item) => `coverage:${item}`)
    ],
    replaces: [],
    reason: "test_system_long_scenario",
    feature_id: "feature:test_system",
    feature_title: "测试系统",
    feature_boundary: "真实长情景测试目录，由测试系统 runner 执行并产出多轮证据。",
    behavior_under_test: scenario.goal,
    problem_statement: scenario.failure_modes[0] || "防止多轮对话执行中断、上下文错绑或证据缺失。",
    pass_criteria: [primaryCriterion, ...scenario.assertions.slice(1)],
    scenario_turns: scenario.turns.map((turn) => ({
      turn_id: turn.turn_id,
      user: turn.speaker === "operator" ? `系统准备：${turn.content || turn.action}` : turn.content,
      expected: turn.checks.join(" / ") || primaryCriterion,
      assistant_hint: `${turn.session || "main"}${turn.action ? ` · ${turn.action}` : ""}`,
      speaker: turn.speaker,
      session: turn.session,
      checks: turn.checks
    })),
    issue_refs: [],
    case_draft_refs: [],
    governance_findings: [],
    traceability: {
      test_file: "backend/tests/system_eval/long_scenarios.py",
      harness_ref: `long_runner:${scenario.scenario_id}`,
      profile_refs: profileRefs,
      scenario_sets: scenario.scenario_sets,
      source_scenario_id: scenario.scenario_id,
      runner_source: scenario.runner_source,
      status: "active",
      owner_system: "test_system",
    },
  };
}

function statusLabel(status: string) {
  if (status === "triage_ready") return "待分析";
  if (status === "running") return "运行中";
  if (status === "passed") return "通过";
  if (status === "failed") return "失败";
  if (status === "warning") return "警告";
  if (status === "cancelled") return "已取消";
  if (status === "completed") return "完成";
  if (status === "blocked") return "阻断";
  if (status === "rejected") return "已拒绝";
  if (status === "stale") return "状态失效";
  if (status === "active") return "正式";
  if (status === "candidate") return "未启用";
  return status || "未知";
}

function severityLabel(severity: string) {
  const value = severity.toLowerCase();
  if (value.includes("critical")) return "严重";
  if (value.includes("high")) return "高";
  if (value.includes("medium")) return "中";
  if (value.includes("low")) return "低";
  return severity || "未定级";
}

function laneLabel(lane: string) {
  if (lane === "health_issue_read") return "健康问题只读";
  if (lane === "codex_smoke_test") return "冒烟验证";
  return lane ? "健康分析链路" : "未绑定";
}

function terminalLabel(reason: string) {
  if (!reason) return "等待结果";
  if (reason === "completed") return "已完成";
  if (reason === "running") return "运行中";
  if (reason === "not_executed_sample") return "样例记录";
  return reason;
}

function statusIcon(status: string) {
  if (status === "running") return <Loader2 className="animate-spin" size={18} />;
  if (["passed", "completed", "resolved"].includes(status)) return <CheckCircle2 size={18} />;
  if (["failed", "blocked"].includes(status)) return <XCircle size={18} />;
  if (status === "warning") return <AlertTriangle size={18} />;
  return <Activity size={18} />;
}

function statusTone(value: string) {
  const normalized = value.toLowerCase();
  if (["completed", "passed", "resolved", "closed", "ready", "active"].some((item) => normalized.includes(item))) {
    return "health-pill--success";
  }
  if (["failed", "blocked", "danger", "critical", "rejected", "stale"].some((item) => normalized.includes(item))) {
    return "health-pill--danger";
  }
  if (["warning", "triage", "running", "sample", "candidate"].some((item) => normalized.includes(item))) {
    return "health-pill--warning";
  }
  return "";
}

function priorityTone(value: string) {
  const normalized = value.toLowerCase();
  if (["critical", "high"].includes(normalized)) return "health-pill--danger";
  if (["medium", "warning"].includes(normalized)) return "health-pill--warning";
  if (["low", "safe"].includes(normalized)) return "health-pill--success";
  return statusTone(value);
}

function riskLabel(value: string) {
  if (value === "needs_governance") return "需治理";
  if (value === "has_open_issue") return "有开放问题";
  if (value === "has_candidates") return "有未启用资源";
  if (value === "healthy") return "健康";
  return value || "未知";
}

function riskTone(value: string) {
  if (value === "needs_governance" || value === "has_open_issue") return "health-pill--danger";
  if (value === "has_candidates") return "health-pill--warning";
  if (value === "healthy") return "health-pill--success";
  return "";
}

function formatDuration(ms?: number) {
  const value = Number(ms || 0);
  if (!value) return "0s";
  if (value < 1000) return `${Math.round(value)}ms`;
  if (value < 60_000) return `${(value / 1000).toFixed(1)}s`;
  return `${Math.round(value / 60_000)}min`;
}

function verificationRunId(run: VerificationRun | null | undefined) {
  return run?.source_run_ref || run?.verification_run_id || "";
}

function verificationProfile(run: VerificationRun | null | undefined) {
  return run?.profile_id || "";
}

function numberValue(value: unknown) {
  const next = Number(value ?? 0);
  return Number.isFinite(next) ? next : 0;
}

function tokenBuckets(value: unknown) {
  return Array.isArray(value)
    ? value.map((item) => item as Record<string, unknown>)
    : [];
}

function compactNumber(value: number) {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(value >= 10_000 ? 0 : 1)}k`;
  return String(Math.round(value));
}

function traceResultText(report: HealthTraceReport | null) {
  const result = report?.result;
  if (!result) return "";
  return text(result.summary || result.content || result.result, "");
}

function profileById(profiles: TestProfile[], profileId: string) {
  return profiles.find((item) => item.id === profileId || item.harness_profile === profileId);
}

function profileTitle(profiles: TestProfile[], profileId: string) {
  return profileById(profiles, profileId)?.title || layerMeta[profileId]?.title || profileId;
}

function ownerLabel(owner: string) {
  if (owner.includes("/") || owner.includes("\\") || owner.endsWith(".py") || owner.endsWith(".ts")) {
    return "测试治理";
  }
  return ownerLabels[owner] || owner || "未归属";
}

function evidenceStateLabel(value: string) {
  if (value === "packet") return "证据包";
  if (value === "linked") return "已绑定";
  if (value === "missing") return "缺证据";
  return value || "未知";
}

function recoveryKindLabel(value: string) {
  if (value === "checkpoint") return "Runtime checkpoint";
  if (value === "coordination_checkpoint") return "Coordination checkpoint";
  if (value === "task_graph_node_resume_candidate") return "节点恢复候选";
  if (value === "tool_result_boundary") return "工具副作用边界";
  return value || "恢复候选";
}

function riskCopy(value: string) {
  if (value === "low") return "低风险";
  if (value === "medium") return "中风险";
  if (value === "high") return "高风险";
  return value || "未知风险";
}

function issueProblemKind(issue: HealthIssue): ProblemKind {
  const metadataKind = String(issue.metadata?.problem_kind || "");
  if (metadataKind === "system" || metadataKind === "test") return metadataKind;
  const source = issue.source.toLowerCase();
  const owner = issue.owner_system.toLowerCase();
  if (
    owner === "test_system"
    || source.includes("test")
    || source.includes("harness")
    || source.includes("verification")
    || String(issue.metadata?.subject_type || "").includes("verification")
  ) {
    return "test";
  }
  if (["runtime_loop", "runtime", "orchestration_system", "task_system", "capability_system", "memory_system", "soul_system", "prompt", "context"].includes(owner)) {
    return "system";
  }
  return "system";
}

function problemKindLabel(kind: ProblemKind) {
  if (kind === "system") return "系统问题";
  return "测试问题";
}

function issueLayerLabel(issue: HealthIssue) {
  return problemKindLabel(issueProblemKind(issue));
}

function issueLayerTone(issue: HealthIssue) {
  const kind = issueProblemKind(issue);
  if (kind === "system") return "danger";
  return "warning";
}

function inboxProblemKind(item: HealthWorkbenchInboxItem): ProblemKind {
  if (item.subject_type === "verification_run") return "test";
  if (item.subject_type === "health_issue" && String(item.metadata?.owner_system || "").includes("test")) return "test";
  return "system";
}

function problemIntakeLabel(kind: ProblemKind) {
  if (kind === "system") return "主对话监督";
  if (kind === "test") return "测试报告语义分析";
  return "用户反馈";
}

function problemAgentBrief(kind: ProblemKind) {
  if (kind === "system") {
    return "健康子 Agent 监督主对话异常，收集对话引用、运行链路、提示和记忆证据，再生成系统问题报告。";
  }
  return "健康子 Agent 读取测试生成的报告，结合测试本身目标、失败现象和生成结果语义，自主分析是否是真问题。";
}

function issueTitle(issue: Record<string, unknown>, index: number) {
  return String(issue.title || issue.code || `问题 ${index + 1}`);
}

function issueSummary(issue: Record<string, unknown>) {
  return String(issue.summary || issue.reason || issue.message || issue.recommendation || "");
}

function sampleVerificationStatus(sample: RegressionSample | Record<string, unknown>) {
  const verification = (sample as RegressionSample).verification as RegressionSample["verification"] | undefined;
  return verification?.status || String((sample as Record<string, unknown>).verification_status || "not_run");
}

function sampleRerunCommand(sample: RegressionSample | Record<string, unknown>) {
  const direct = (sample as RegressionSample).rerun_command;
  if (Array.isArray(direct) && direct.length) {
    return direct.join(" ");
  }
  const contract = (sample as RegressionSample).contract;
  if (contract?.rerun_args?.length) {
    return contract.rerun_args.join(" ");
  }
  return "";
}

export function HealthSystemView() {
  const confirm = useConfirmDialog();
  const [activePage, setActivePage] = useState<HealthPage>("overview");
  const [problemReportTab, setProblemReportTab] = useState<ProblemReportTab>("analysis");
  const [tokenChartMode, setTokenChartMode] = useState<TokenChartMode>("daily");
  const [overview, setOverview] = useState<HealthSystemOverview | null>(null);
  const [workbench, setWorkbench] = useState<HealthWorkbenchOverview | null>(null);
  const [profiles, setProfiles] = useState<TestProfile[]>([]);
  const [registry, setRegistry] = useState<TestCaseRegistry | null>(null);
  const [harnessMap, setHarnessMap] = useState<HarnessMap | null>(null);
  const [longScenarioCatalog, setLongScenarioCatalog] = useState<LongScenarioCatalog | null>(null);
  const [caseTemplates, setCaseTemplates] = useState<TestCaseTemplate[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState("template.runtime_chain");
  const [caseDraft, setCaseDraft] = useState({
    feature: "",
    problem: "",
    expected: "",
    example: "",
    category: defaultScenarioCategory,
    turns: [emptyScenarioTurn()]
  });
  const [agentReport, setAgentReport] = useState<TestAgentReport | null>(null);
  const [testRuns, setTestRuns] = useState<TestRun[]>([]);
  const [activeTestRunId, setActiveTestRunId] = useState("");
  const [activeTestRun, setActiveTestRun] = useState<TestRun | null>(null);
  const [selectedInboxItemId, setSelectedInboxItemId] = useState("");
  const [selectedScenarioCaseId, setSelectedScenarioCaseId] = useState("");
  const [selectedScenarioTurnIndex, setSelectedScenarioTurnIndex] = useState(0);
  const [scenarioCategoryFilter, setScenarioCategoryFilter] = useState<ScenarioCategoryFilter>("all");
  const [scenarioSourceFilter, setScenarioSourceFilter] = useState("all");
  const [scenarioQuery, setScenarioQuery] = useState("");
  const [scenarioEditMode, setScenarioEditMode] = useState<ScenarioEditMode>("create");
  const [scenarioEditorOpen, setScenarioEditorOpen] = useState(false);
  const [scenarioEditPage, setScenarioEditPage] = useState(0);
  const [scenarioLibraryPage, setScenarioLibraryPage] = useState(0);
  const [newScenarioTurnText, setNewScenarioTurnText] = useState("");
  const [selectedScenarioProfile, setSelectedScenarioProfile] = useState(defaultLongScenarioProfile);
  const [configuredScenarioIdsByProfile, setConfiguredScenarioIdsByProfile] = useState<Record<string, string[]>>({});
  const [removedScenarioCaseIds, setRemovedScenarioCaseIds] = useState<string[]>([]);
  const [artifacts, setArtifacts] = useState<TestArtifacts | null>(null);
  const [selectedProfile, setSelectedProfile] = useState("chain");
  const [selectedIssueId, setSelectedIssueId] = useState("");
  const [selectedHealthRunId, setSelectedHealthRunId] = useState("");
  const [traceReport, setTraceReport] = useState<HealthTraceReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [runningIssueId, setRunningIssueId] = useState("");
  const [error, setError] = useState("");
  const [sampleActionMessage, setSampleActionMessage] = useState("");
  const [notice, setNotice] = useState("");

  const selectedTestRun = activeTestRun ?? testRuns[0] ?? null;
  const testSummary = selectedTestRun?.summary ?? { total: 0, passed: 0, failed: 0, first_failure: "" };
  const passRate = testSummary.total > 0 ? Math.round((testSummary.passed / testSummary.total) * 100) : 0;
  const selectedProfileObject = profileById(profiles, selectedProfile);
  const issueRecords = useMemo(
    () => [
      ...(artifacts?.issues || []).map((issue, index) => ({
        id: String(issue.id || `artifact-${index}`),
        title: issueTitle(issue, index),
        origin: "测试运行发现",
        system: String(issue.system || issue.owner || selectedTestRun?.profile || "未知系统"),
        severity: String(issue.severity || "runtime"),
        summary: issueSummary(issue),
        relatedRun: selectedTestRun?.run_id || ""
      })),
      ...(agentReport?.findings || []).map((finding, index) => ({
        id: `finding-${index}`,
        title: finding.code,
        origin: "测试治理发现",
        system: finding.case_id || finding.path || "测试系统",
        severity: finding.severity,
        summary: finding.message,
        relatedRun: ""
      }))
    ],
    [agentReport?.findings, artifacts?.issues, selectedTestRun?.profile, selectedTestRun?.run_id]
  );

  const selectedIssue = useMemo(
    () => overview?.issues.find((issue) => issue.issue_id === selectedIssueId) ?? overview?.issues[0] ?? null,
    [overview, selectedIssueId]
  );
  const selectedHealthRun = useMemo(
    () => overview?.agent_runs.find((run) => run.run_id === selectedHealthRunId)
      ?? overview?.agent_runs.find((run) => run.issue_id === selectedIssue?.issue_id)
      ?? overview?.agent_runs[0]
      ?? null,
    [overview, selectedHealthRunId, selectedIssue?.issue_id]
  );
  const healthRunsForIssue = useMemo(
    () => overview?.agent_runs.filter((run) => !selectedIssue || run.issue_id === selectedIssue.issue_id) ?? [],
    [overview, selectedIssue]
  );
  const selectedInboxItem = useMemo(
    () => workbench?.inbox_items.find((item) => item.item_id === selectedInboxItemId) ?? workbench?.inbox_items[0] ?? null,
    [selectedInboxItemId, workbench]
  );

  const loadTraceReport = useCallback(async (runId: string) => {
    if (!runId) {
      setTraceReport(null);
      return;
    }
    try {
      const report = await getHealthAgentRunTraceReport(runId);
      setTraceReport(report);
    } catch (traceError) {
      setTraceReport(null);
      setNotice(traceError instanceof Error ? traceError.message : "当前运行暂无证据报告");
    }
  }, []);

  const loadRunArtifacts = useCallback(async (runId: string) => {
    try {
      const artifactPayload = await getTestArtifacts(runId);
      setArtifacts(artifactPayload);
    } catch {
      setArtifacts(null);
    }
  }, []);

  const selectTestRun = useCallback(async (run: TestRun, switchPage = true) => {
    setActiveTestRunId(run.run_id);
    setActiveTestRun(run);
    if (run.status === "running") {
      setArtifacts(null);
    } else {
      await loadRunArtifacts(run.run_id);
    }
    if (switchPage) {
      setActivePage("issues");
    }
  }, [loadRunArtifacts]);

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [healthPayload, workbenchPayload, profilePayload, casePayload, harnessPayload, longScenarioPayload, templatePayload, reportPayload, runPayload] = await Promise.all([
        getHealthSystemOverview(),
        getHealthWorkbenchOverview(),
        listTestProfiles(),
        getTestCases(),
        getHarnessMap(),
        listLongScenarios(),
        getTestCaseTemplates(),
        getTestAgentReport(),
        listTestRuns(20)
      ]);
      setOverview(healthPayload);
      setWorkbench(workbenchPayload);
      setProfiles(profilePayload);
      setRegistry(casePayload);
      setHarnessMap(harnessPayload);
      setLongScenarioCatalog(longScenarioPayload);
      setCaseTemplates(templatePayload.templates);
      setAgentReport(reportPayload);
      setTestRuns(runPayload);
      setSelectedIssueId((current) => current || healthPayload.issues[0]?.issue_id || "");
      setSelectedInboxItemId((current) => current || workbenchPayload.inbox_items[0]?.item_id || "");
      setSelectedHealthRunId((current) => current || healthPayload.agent_runs[0]?.run_id || "");
      const running = runPayload.find((run) => run.status === "running");
      const latest = running ?? runPayload[0] ?? null;
      if (latest) {
        await selectTestRun(latest, false);
      }
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "健康系统数据加载失败");
    } finally {
      setLoading(false);
    }
  }, [selectTestRun]);

  const refreshTestRun = useCallback(async (runId = activeTestRunId) => {
    if (!runId) {
      await loadAll();
      return;
    }
    const run = await getTestRun(runId);
    setActiveTestRun(run);
    setTestRuns(await listTestRuns(20));
    if (run.status !== "running") {
      await loadRunArtifacts(run.run_id);
    }
  }, [activeTestRunId, loadAll, loadRunArtifacts]);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  useEffect(() => {
    if (selectedHealthRun?.run_id) {
      void loadTraceReport(selectedHealthRun.run_id);
    }
  }, [loadTraceReport, selectedHealthRun?.run_id]);

  useEffect(() => {
    const longTemplate = caseTemplates.find(isLongScenarioTemplate);
    if (longTemplate && !caseTemplates.some((template) => template.template_id === selectedTemplateId && isLongScenarioTemplate(template))) {
      setSelectedTemplateId(longTemplate.template_id);
    }
  }, [caseTemplates, selectedTemplateId]);

  useEffect(() => {
    if (!activeTestRunId || selectedTestRun?.status !== "running") return;
    const timer = window.setInterval(() => {
      void refreshTestRun(activeTestRunId);
    }, 2200);
    return () => window.clearInterval(timer);
  }, [activeTestRunId, refreshTestRun, selectedTestRun?.status]);

  async function startProfile(profileId = selectedProfile) {
    const profile = profileById(profiles, profileId);
    if (profile?.requires_confirmation && !await confirm({
      title: "启动长耗时验证",
      body: "该测试可能耗时较长，运行期间会持续占用验证资源。",
      confirmLabel: "开始运行",
      tone: "warning",
    })) {
      return;
    }
    const scenarioIds = isLongScenarioProfile(profileId) ? runnableScenarioIdsForProfile(profileId) : [];
    if (isLongScenarioProfile(profileId) && !scenarioIds.length) {
      setNotice("请先从情景库链接至少一个可运行情景。");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const run = await startTestRun(profileId, scenarioIds);
      setActiveTestRunId(run.run_id);
      setActiveTestRun(run);
      setArtifacts(null);
      setActivePage("verify");
      setTestRuns(await listTestRuns(20));
      setNotice("验证运行已启动；如果失败，会进入问题报告复盘。");
    } catch (startError) {
      setError(startError instanceof Error ? startError.message : "启动测试失败");
    } finally {
      setLoading(false);
    }
  }

  async function rerunSample(sampleId: string) {
    if (!sampleId) return;
    setLoading(true);
    setError("");
    setSampleActionMessage("");
    try {
      const payload = await rerunRegressionSample(sampleId);
      setSampleActionMessage(`已启动样本复跑：${payload.run.run_id || sampleId}`);
      const [nextWorkbench, nextRuns, nextMap] = await Promise.all([
        getHealthWorkbenchOverview(),
        listTestRuns(20),
        getHarnessMap(),
      ]);
      setWorkbench(nextWorkbench);
      setTestRuns(nextRuns);
      setHarnessMap(nextMap);
      if (payload.run?.run_id) {
        await selectTestRun(payload.run, false);
      }
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "样本复跑启动失败");
    } finally {
      setLoading(false);
    }
  }

  async function refreshSampleVerdict(sampleId: string) {
    if (!sampleId) return;
    setLoading(true);
    setError("");
    setSampleActionMessage("");
    try {
      const payload = await refreshRegressionSampleVerdict(sampleId);
      setSampleActionMessage(`样本裁决已刷新：${statusLabel(String(payload.verdict.status || ""))}`);
      const [nextWorkbench, nextMap] = await Promise.all([
        getHealthWorkbenchOverview(),
        getHarnessMap(),
      ]);
      setWorkbench(nextWorkbench);
      setHarnessMap(nextMap);
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "样本裁决刷新失败");
    } finally {
      setLoading(false);
    }
  }

  async function promoteActiveRunFailures() {
    if (!activeTestRunId) return;
    setLoading(true);
    setError("");
    setSampleActionMessage("");
    try {
      const payload = await promoteFailedTurnsToRegressionSamples(activeTestRunId);
      setSampleActionMessage(`已沉淀失败样本 ${payload.summary.promoted_count || 0} 个`);
      const [nextWorkbench, nextMap] = await Promise.all([
        getHealthWorkbenchOverview(),
        getHarnessMap(),
      ]);
      setWorkbench(nextWorkbench);
      setHarnessMap(nextMap);
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "失败样本沉淀失败");
    } finally {
      setLoading(false);
    }
  }

  async function cancelActiveTestRun() {
    if (!activeTestRunId) return;
    setLoading(true);
    try {
      const run = await cancelTestRun(activeTestRunId);
      setActiveTestRun(run);
      setTestRuns(await listTestRuns(20));
    } catch (cancelError) {
      setError(cancelError instanceof Error ? cancelError.message : "取消测试失败");
    } finally {
      setLoading(false);
    }
  }

  async function runHealthAgent(issue: HealthIssue | null = selectedIssue) {
    if (!issue) {
      setNotice("请先选择一个健康问题。");
      return;
    }
    setRunningIssueId(issue.issue_id);
    setError("");
    setNotice("");
    try {
      const payload = await createHealthManagementCommand({
        command_type: "analyze_trace",
        initiator_type: "user",
        source: "health_system_native_workbench",
        target_scope: "health_issue",
        target_ref: issue.issue_id,
        health_action: "issue_triage"
      });
      const runResult = (payload.run_result ?? {}) as Record<string, unknown>;
      const run = runResult.health_agent_run as HealthAgentRun | undefined;
      setNotice(`健康子 Agent 已返回：${payload.receipt.status}`);
      const [nextOverview, nextWorkbench] = await Promise.all([getHealthSystemOverview(), getHealthWorkbenchOverview()]);
      setOverview(nextOverview);
      setWorkbench(nextWorkbench);
      if (run?.run_id) {
        setSelectedHealthRunId(run.run_id);
        await loadTraceReport(run.run_id);
      }
      setActivePage("issues");
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : "健康子 Agent 分析失败");
    } finally {
      setRunningIssueId("");
    }
  }

  function selectIssue(issue: HealthIssue) {
    setSelectedIssueId(issue.issue_id);
    const nextRun = overview?.agent_runs.find((run) => run.issue_id === issue.issue_id);
    if (nextRun) {
      setSelectedHealthRunId(nextRun.run_id);
    }
  }

  function openInboxItem(item: HealthWorkbenchInboxItem | null) {
    if (!item) return;
    setSelectedInboxItemId(item.item_id);
    if (item.subject_type === "health_issue") {
      const issue = overview?.issues.find((candidate) => candidate.issue_id === item.subject_id);
      if (issue) {
        selectIssue(issue);
      }
      setActivePage("issues");
      return;
    }
    if (item.subject_type === "verification_run") {
      const run = (workbench?.recent_runs || []).find((candidate) =>
        verificationRunId(candidate) === item.subject_id || candidate.verification_run_id === item.subject_id
      );
      if (run) {
        const sourceRun = verificationRunId(run);
        const matchedTestRun = testRuns.find((candidate) => candidate.run_id === sourceRun);
        if (matchedTestRun) {
          void selectTestRun(matchedTestRun, false);
        }
        setProblemReportTab("analysis");
        setNotice("已选中验证失败线索。健康子 Agent 应结合测试报告、测试目标和生成结果语义先做问题判断。");
      } else {
        setProblemReportTab("analysis");
        setActivePage("issues");
      }
    }
  }

  async function registerInboxItemAsIssue(item: HealthWorkbenchInboxItem | null) {
    if (!item) return;
    if (item.subject_type === "health_issue") {
      openInboxItem(item);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const problemKind = inboxProblemKind(item);
      const createdIssue = await createHealthIssue({
        title: item.title || item.subject_title || "待处理健康问题",
        owner_system: problemKind === "test" ? "test_system" : String(item.metadata?.owner_system || item.metadata?.profile || item.subject_type || "runtime_loop"),
        severity: item.severity || "medium",
        status: "triage_ready",
        source: problemKind === "test" ? "health_workbench.test_report_semantic" : "health_workbench.main_conversation_monitor",
        runtime_trace_refs: item.subject_type === "verification_run" ? [item.subject_id] : [],
        metadata: {
          problem_kind: problemKind,
          inbox_item_id: item.item_id,
          inbox_item_type: item.item_type,
          subject_type: item.subject_type,
          subject_id: item.subject_id,
          subject_title: item.subject_title,
          reason: item.reason,
          evidence_state: item.evidence_state,
          ...item.metadata
        }
      });
      const [nextOverview, nextWorkbench] = await Promise.all([getHealthSystemOverview(), getHealthWorkbenchOverview()]);
      setOverview(nextOverview);
      setWorkbench(nextWorkbench);
      setSelectedIssueId(createdIssue.issue_id);
      setSelectedInboxItemId(`inbox:issue:${createdIssue.issue_id}`);
      setProblemReportTab("details");
      setActivePage("issues");
      setNotice("已登记为健康问题，可以继续分析并补齐链路证据。");
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : "登记健康问题失败");
    } finally {
      setLoading(false);
    }
  }

  function explainSelectedHealthRun() {
    if (!selectedHealthRun) {
      setNotice("请先选择一条健康运行记录。");
      return;
    }
    setActivePage("issues");
    void loadTraceReport(selectedHealthRun.run_id);
  }

  function openSelectedTechnicalReport() {
    if (!selectedHealthRun && !selectedIssue) {
      setNotice("请先选择健康问题或运行记录。");
      return;
    }
    setActivePage("issues");
    if (selectedHealthRun?.run_id) {
      void loadTraceReport(selectedHealthRun.run_id);
    }
  }

  function resetScenarioDraft() {
    const nextProfile = isLongScenarioProfile(selectedProfile) ? selectedProfile : defaultLongScenarioProfile;
    setScenarioEditMode("create");
    setScenarioEditorOpen(true);
    setSelectedScenarioProfile(nextProfile);
    setSelectedProfile(nextProfile);
    setSelectedScenarioTurnIndex(0);
    setScenarioEditPage(0);
    setScenarioLibraryPage(0);
    setCaseDraft({
      feature: "",
      problem: "",
      expected: "",
      example: "",
      category: defaultScenarioCategory,
      turns: []
    });
  }

  function loadScenarioIntoDraft(testCase: HarnessMapCase, mode: ScenarioEditMode, turnIndex = 0, openEditor = true) {
    setSelectedScenarioCaseId(testCase.case_id);
    setScenarioEditMode(mode);
    setScenarioEditorOpen(openEditor);
    setSelectedScenarioProfile(primaryScenarioProfile(testCase));
    const sourceTemplateId = String(testCase.traceability?.source_template_id || "");
    if (sourceTemplateId) {
      setSelectedTemplateId(sourceTemplateId);
    }
    setCaseDraft({
      feature: testCase.title.replace(/\s*情景$/, ""),
      problem: testCase.problem_statement,
      expected: testCase.pass_criteria.filter((criterion) => !criterion.includes("返回码为 0")).join("\n"),
      example: "",
      category: scenarioCategoryOf(testCase),
      turns: scenarioTurnsOf(testCase)
    });
    setSelectedScenarioTurnIndex(turnIndex);
    setScenarioEditPage(Math.floor(turnIndex / scenarioEditPageSize));
    setNewScenarioTurnText("");
  }

  function insertScenarioTurnAt(insertAt: number) {
    const content = newScenarioTurnText.trim();
    if (!content) {
      setNotice("请先填写要新增的对话。");
      return;
    }
    setCaseDraft((current) => {
      const normalizedInsertAt = Math.max(0, Math.min(insertAt, current.turns.length));
      const nextTurns = [...current.turns];
      nextTurns.splice(normalizedInsertAt, 0, {
        ...emptyScenarioTurn(normalizedInsertAt + 1),
        user: content,
      });
      setSelectedScenarioTurnIndex(normalizedInsertAt);
      setNewScenarioTurnText("");
      return { ...current, turns: nextTurns };
    });
  }

  function insertScenarioTurnAfterCurrent() {
    insertScenarioTurnAt(caseDraft.turns.length ? selectedScenarioTurnIndex + 1 : 0);
  }

  function deleteScenarioTurnAt(turnIndex: number) {
    setCaseDraft((current) => {
      if (!current.turns[turnIndex]) return current;
      const nextTurns = current.turns.filter((_, index) => index !== turnIndex);
      const nextSelectedIndex = Math.max(0, Math.min(turnIndex, nextTurns.length - 1));
      setSelectedScenarioTurnIndex(nextSelectedIndex);
      return { ...current, turns: nextTurns };
    });
  }

  function updateScenarioTurnAt(turnIndex: number, value: string) {
    setCaseDraft((current) => {
      if (!current.turns[turnIndex]) return current;
      return {
        ...current,
        turns: current.turns.map((turn, index) => (
          index === turnIndex ? { ...turn, user: value } : turn
        ))
      };
    });
  }

  function goScenarioDialoguePage(page: number) {
    const normalizedPage = Math.max(0, Math.min(page, scenarioEditPageCount - 1));
    const firstIndexOnPage = normalizedPage * scenarioEditPageSize;
    setScenarioEditPage(normalizedPage);
    setSelectedScenarioTurnIndex((current) => {
      if (!caseDraft.turns.length) return 0;
      if (current >= firstIndexOnPage && current < firstIndexOnPage + scenarioEditPageSize) {
        return current;
      }
      return Math.min(firstIndexOnPage, caseDraft.turns.length - 1);
    });
  }

  async function createManagedCaseFromForm(mode: ScenarioEditMode = scenarioEditMode) {
    const longTemplates = caseTemplates.filter(isLongScenarioTemplate);
    const template = longTemplates.find((item) => item.template_id === selectedTemplateId) ?? longTemplates[0] ?? caseTemplates.find((item) => item.template_id === selectedTemplateId);
    const feature = caseDraft.feature.trim() || template?.title || "未命名长场景";
    const problem = caseDraft.problem.trim() || "需要防止长场景执行偏离用户目标";
    const expected = caseDraft.expected.trim() || (template?.pass_criteria || []).join("\n") || "长场景能持续推进、留痕，并给出可复盘结果";
    const example = caseDraft.example.trim();
    const scenarioTurns = caseDraft.turns
      .map((turn, index) => ({
        turn_id: turn.turn_id || `turn-${index + 1}`,
        user: turn.user.trim(),
        expected: turn.expected.trim(),
        assistant_hint: turn.assistant_hint.trim()
      }))
      .filter((turn) => turn.user || turn.expected || turn.assistant_hint);
    if (!scenarioTurns.length) {
      setNotice("长情景至少需要一条对话。");
      return;
    }
    const title = `${feature} 情景`;
    const ownerSystem = template?.owner_system || "test_system";
    setLoading(true);
    setError("");
    try {
      const replacingManagedCase = mode === "manage" && selectedScenarioCase?.reason === "front_managed_case";
      const savedCase = await createManagedTestCase({
        case_id: replacingManagedCase ? selectedScenarioCaseId : undefined,
        title,
        layer: "scenario",
        path: `backend/tests/generated/${draftSlug(feature)}_scenario.py`,
        owner_system: ownerSystem,
        runner: template?.runner || "pytest",
        status: "active",
        profiles: [selectedScenarioProfile],
        description: `多轮对话情景：${feature}`,
        problem_statement: problem,
        pass_criteria: [expected, example].filter(Boolean),
        scenario_turns: scenarioTurns,
        assertions: template?.assertions || [],
        tags: Array.from(new Set([...(template?.tags || []), "long_scenario", "scenario_management", `scenario_category:${caseDraft.category}`])),
        source_template_id: template?.template_id || ""
      });
      const [nextMap, nextWorkbench] = await Promise.all([getHarnessMap(), getHealthWorkbenchOverview()]);
      setHarnessMap(nextMap);
      setWorkbench(nextWorkbench);
      setSelectedScenarioCaseId(savedCase.case_id);
      setSelectedProfile(primaryScenarioProfile(savedCase));
      setSelectedInboxItemId((current) => current || nextWorkbench.inbox_items[0]?.item_id || "");
      setScenarioEditorOpen(false);
      setNotice(replacingManagedCase ? "长场景情景已保存。" : "长场景情景已进入管理，并归入验证中心。");
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : "保存长场景情景失败");
    } finally {
      setLoading(false);
    }
  }

  async function removeManagedCase(caseId: string) {
    if (!await confirm({
      title: "删除管理中的长情景",
      body: "该长情景会从验证中心移除。",
      confirmLabel: "删除情景",
    })) {
      return;
    }
    setLoading(true);
    setError("");
    try {
      await deleteManagedTestCase(caseId);
      const [nextMap, nextWorkbench] = await Promise.all([getHarnessMap(), getHealthWorkbenchOverview()]);
      setHarnessMap(nextMap);
      setWorkbench(nextWorkbench);
      setSelectedInboxItemId((current) => nextWorkbench.inbox_items.some((item) => item.item_id === current) ? current : nextWorkbench.inbox_items[0]?.item_id || "");
      if (selectedScenarioCaseId === caseId) {
        setSelectedScenarioCaseId("");
        setScenarioEditorOpen(false);
      }
      setNotice("长场景情景已移除。");
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "移除长场景情景失败");
    } finally {
      setLoading(false);
    }
  }

  async function removeScenarioFromLibrary(testCase: HarnessMapCase) {
    if (testCase.reason === "front_managed_case") {
      void removeManagedCase(testCase.case_id);
      return;
    }
    if (!await confirm({
      title: "移除系统情景",
      body: "该系统情景会从当前情景库移除，不会删除源定义。",
      confirmLabel: "移除情景",
      tone: "warning",
    })) {
      return;
    }
    setRemovedScenarioCaseIds((current) => (
      current.includes(testCase.case_id) ? current : [...current, testCase.case_id]
    ));
    setConfiguredScenarioIdsByProfile((current) => {
      const next = { ...current };
      for (const [profileId, ids] of Object.entries(next)) {
        next[profileId] = ids.filter((caseId) => caseId !== testCase.case_id);
      }
      return next;
    });
    if (selectedScenarioCaseId === testCase.case_id) {
      setSelectedScenarioCaseId("");
      setScenarioEditorOpen(false);
    }
    setNotice("系统情景已从当前情景库移除。");
  }

  function selectVerifyProfile(profileId: string) {
    setSelectedProfile(profileId);
    if (isLongScenarioProfile(profileId)) {
      setSelectedScenarioProfile(profileId);
      const firstMatchingScenario = longScenarioCases.find((testCase) => testCase.profiles.includes(profileId));
      if (firstMatchingScenario) {
        loadScenarioIntoDraft(firstMatchingScenario, "manage", 0, true);
      }
    }
  }

  function selectScenarioCase(testCase: HarnessMapCase) {
    const profile = primaryScenarioProfile(testCase);
    setSelectedScenarioCaseId(testCase.case_id);
    setSelectedScenarioProfile(profile);
    setSelectedProfile(profile);
    loadScenarioIntoDraft(testCase, "manage", 0, true);
  }

  function selectScenarioEntryCase(testCase: HarnessMapCase) {
    setSelectedScenarioCaseId(testCase.case_id);
    setSelectedScenarioProfile(primaryScenarioProfile(testCase));
  }

  const healthSummary = overview?.summary ?? {};
  const openIssues = Number(healthSummary.open_issue_count ?? 0);
  const highRiskIssues = overview?.issues.filter((issue) => ["high", "critical"].includes(issue.severity.toLowerCase())).length ?? 0;
  const runtimeProblems = traceReport?.problem_events.length ?? 0;
  const longScenarioTemplates = useMemo(
    () => caseTemplates.filter(isLongScenarioTemplate),
    [caseTemplates]
  );
  const selectedTemplate = useMemo(
    () => longScenarioTemplates.find((template) => template.template_id === selectedTemplateId) ?? longScenarioTemplates[0] ?? caseTemplates[0] ?? null,
    [caseTemplates, longScenarioTemplates, selectedTemplateId]
  );
  const longScenarioCases = useMemo(
    () => [
      ...(longScenarioCatalog?.scenarios ?? []).map(longScenarioToCase),
      ...(harnessMap?.cases ?? []).filter(isLongScenarioCase),
    ].filter((testCase) => !removedScenarioCaseIds.includes(testCase.case_id)),
    [harnessMap?.cases, longScenarioCatalog?.scenarios, removedScenarioCaseIds]
  );
  const longScenarioCaseById = useMemo(
    () => new Map(longScenarioCases.map((testCase) => [testCase.case_id, testCase])),
    [longScenarioCases]
  );
  function defaultScenarioIdsForProfile(profileId: string) {
    const profileCases = longScenarioCases.filter((testCase) => testCase.profiles.includes(profileId));
    const cases = profileCases.length ? profileCases : longScenarioCases;
    return cases.map((testCase) => testCase.case_id);
  }
  function configuredScenarioIdsForProfile(profileId: string) {
    return configuredScenarioIdsByProfile[profileId] ?? defaultScenarioIdsForProfile(profileId);
  }
  function configuredScenarioCasesForProfile(profileId: string) {
    return configuredScenarioIdsForProfile(profileId)
      .map((caseId) => longScenarioCaseById.get(caseId))
      .filter(Boolean) as HarnessMapCase[];
  }
  function runnableScenarioIdsForProfile(profileId: string) {
    return Array.from(new Set(
      configuredScenarioCasesForProfile(profileId)
        .map(sourceScenarioId)
        .filter(Boolean)
    ));
  }
  function openScenarioRunConfig(profileId: string) {
    setSelectedScenarioProfile(profileId);
    setScenarioEditorOpen(true);
    setConfiguredScenarioIdsByProfile((current) => (
      current[profileId] ? current : { ...current, [profileId]: defaultScenarioIdsForProfile(profileId) }
    ));
  }
  function toggleScenarioForProfile(profileId: string, caseId: string) {
    setConfiguredScenarioIdsByProfile((current) => {
      const currentIds = current[profileId] ?? defaultScenarioIdsForProfile(profileId);
      const nextIds = currentIds.includes(caseId)
        ? currentIds.filter((item) => item !== caseId)
        : [...currentIds, caseId];
      return { ...current, [profileId]: nextIds };
    });
  }
  const scenarioCategoryOptions = useMemo(() => {
    const values = new Set<string>();
    for (const testCase of longScenarioCases) {
      values.add(scenarioCategoryOf(testCase));
    }
    if (caseDraft.category.trim()) {
      values.add(caseDraft.category.trim());
    }
    return ["all", ...Array.from(values).filter(Boolean).sort((left, right) => left.localeCompare(right, "zh-Hans-CN"))];
  }, [caseDraft.category, longScenarioCases]);
  const scenarioLibraryCategories = useMemo(() => scenarioCategoryOptions.filter((category) => category !== "all"), [scenarioCategoryOptions]);
  const scenarioCategoryCounts = useMemo(() => {
    const counts = new Map<ScenarioCategoryFilter, number>([["all", longScenarioCases.length]]);
    for (const testCase of longScenarioCases) {
      const category = scenarioCategoryOf(testCase);
      counts.set(category, (counts.get(category) ?? 0) + 1);
    }
    return counts;
  }, [longScenarioCases]);
  const filteredScenarioCases = useMemo(() => {
    const query = scenarioQuery.trim().toLowerCase();
    return longScenarioCases.filter((testCase) => {
      const sourceMatches = scenarioSourceFilter === "all"
        || (scenarioSourceFilter === "managed" && testCase.reason === "front_managed_case")
        || (scenarioSourceFilter === "builtin" && testCase.reason !== "front_managed_case");
      const categoryMatches = scenarioCategoryFilter === "all" || scenarioCategoryOf(testCase) === scenarioCategoryFilter;
      const queryMatches = !query || `${testCase.title} ${testCase.problem_statement} ${testCase.behavior_under_test} ${testCase.pass_criteria.join(" ")} ${testCase.tags.join(" ")}`.toLowerCase().includes(query);
      return sourceMatches && categoryMatches && queryMatches;
    });
  }, [longScenarioCases, scenarioCategoryFilter, scenarioQuery, scenarioSourceFilter]);
  const selectedScenarioCase = useMemo(
    () => filteredScenarioCases.find((testCase) => testCase.case_id === selectedScenarioCaseId)
      ?? longScenarioCases.find((testCase) => testCase.case_id === selectedScenarioCaseId)
      ?? filteredScenarioCases[0]
      ?? longScenarioCases[0]
      ?? null,
    [filteredScenarioCases, longScenarioCases, selectedScenarioCaseId]
  );
  const selectedScenarioScriptTurns = selectedScenarioCase ? scenarioTurnsOf(selectedScenarioCase) : [];
  const scenarioEditPageCount = pageCount(caseDraft.turns.length, scenarioEditPageSize);
  const scenarioLibraryPageCount = pageCount(filteredScenarioCases.length, scenarioLibraryPageSize);
  const pagedScenarioEditTurns = pageSlice(caseDraft.turns, scenarioEditPage, scenarioEditPageSize);
  const pagedScenarioCases = pageSlice(filteredScenarioCases, scenarioLibraryPage, scenarioLibraryPageSize);
  const isLongScenarioMode = isLongScenarioProfile(selectedProfile);
  useEffect(() => {
    if (scenarioEditMode === "manage" && selectedScenarioCase) {
      setSelectedScenarioProfile(primaryScenarioProfile(selectedScenarioCase));
    }
  }, [scenarioEditMode, selectedScenarioCase]);
  useEffect(() => {
    setScenarioLibraryPage(0);
  }, [scenarioCategoryFilter, scenarioQuery, scenarioSourceFilter]);
  useEffect(() => {
    if (selectedScenarioTurnIndex >= caseDraft.turns.length) {
      setSelectedScenarioTurnIndex(Math.max(0, caseDraft.turns.length - 1));
    }
  }, [caseDraft.turns.length, selectedScenarioTurnIndex]);
  useEffect(() => {
    setScenarioEditPage((current) => Math.min(current, scenarioEditPageCount - 1));
  }, [scenarioEditPageCount]);
  useEffect(() => {
    setScenarioLibraryPage((current) => Math.min(current, scenarioLibraryPageCount - 1));
  }, [scenarioLibraryPageCount]);
  useEffect(() => {
    const nextPage = Math.floor(selectedScenarioTurnIndex / scenarioEditPageSize);
    if (nextPage !== scenarioEditPage) {
      setScenarioEditPage(nextPage);
    }
  }, [scenarioEditPage, selectedScenarioTurnIndex]);
  const workbenchSummary = workbench?.summary ?? {};
  const latestProfile = selectedTestRun ? profileTitle(profiles, selectedTestRun.profile) : "未运行";
  const latency = workbench?.efficiency?.latency ?? {};
  const tokenHealth = workbench?.efficiency?.tokens ?? {};
  const dailyTokenBuckets = tokenBuckets(tokenHealth.daily);
  const sixHourTokenBuckets = tokenBuckets(tokenHealth.six_hour);
  const activeTokenBuckets = tokenChartMode === "daily" ? dailyTokenBuckets : sixHourTokenBuckets;
  const maxActiveTokenBucket = Math.max(1, ...activeTokenBuckets.map((bucket) => numberValue(bucket.tokens)));
  const tokenChartTitle = tokenChartMode === "daily" ? "最近 7 天" : "最近 24 小时";
  const tokenChartBucketLabel = tokenChartMode === "daily" ? "日期" : "6 小时窗口";
  const tokenChartTicks = [1, 0.75, 0.5, 0.25, 0].map((ratio) => Math.round(maxActiveTokenBucket * ratio));
  const tokenLinePoints = activeTokenBuckets.map((bucket, index, buckets) => {
    const x = buckets.length <= 1 ? 50 : (index / (buckets.length - 1)) * 100;
    const value = numberValue(bucket.tokens);
    const y = 92 - (value / maxActiveTokenBucket) * 76;
    return { bucket, value, x, y };
  });
  const tokenLinePolyline = tokenLinePoints.map((point) => `${point.x},${point.y}`).join(" ");
  const tokenLineArea = tokenLinePoints.length
    ? `0,92 ${tokenLinePolyline} 100,92`
    : "";
  const efficiencySignals = workbench?.efficiency?.signals ?? [];
  const failedRunCount = numberValue(workbenchSummary.failed_run_count);
  const slowRunCount = numberValue(workbenchSummary.slow_run_count);
  const evidenceGapCount = numberValue(workbenchSummary.evidence_gap_count);
  const diagnosisInbox = (workbench?.diagnosis_inbox ?? []) as HealthWorkbenchDiagnosisItem[];
  const recoveryInbox = (workbench?.recovery_inbox ?? []) as HealthWorkbenchRecoveryItem[];
  const failureChains = (workbench?.failure_chains ?? []) as HealthWorkbenchFailureChain[];
  const evidencePackets = workbench?.evidence_packets ?? [];
  const regressionSamples = (workbench?.test_governance?.regression_samples ?? harnessMap?.regression_samples ?? []) as RegressionSample[];
  const regressionSampleInbox = (workbench?.regression_sample_inbox ?? []) as Array<Record<string, unknown>>;
  const scenarioContracts = workbench?.test_governance?.scenario_contracts ?? harnessMap?.scenario_contracts ?? [];
  const primaryRegressionSample = regressionSamples[0] ?? null;
  const primaryDiagnosis = diagnosisInbox[0] ?? null;
  const primaryRecovery = recoveryInbox[0] ?? null;
  const primaryFailureChain = failureChains[0] ?? null;
  const healthScore = Math.max(0, Math.min(100, 100 - openIssues * 14 - highRiskIssues * 20 - failedRunCount * 16 - slowRunCount * 8 - evidenceGapCount * 6));
  const healthState = healthScore >= 85 ? "健康" : healthScore >= 65 ? "需关注" : "需处理";
  const healthTone = healthScore >= 85 ? "success" : healthScore >= 65 ? "warning" : "danger";
  const deepProfiles = deepProfileOrder.map((id) => profileById(profiles, id)).filter(Boolean) as TestProfile[];
  const longRunProfiles = deepProfiles.length
    ? deepProfiles
    : [{ id: defaultLongScenarioProfile, title: "长场景核心", description: "运行长情景测试。", estimated_duration: "耗时未知", harness_profile: defaultLongScenarioProfile } as TestProfile];
  const selectedProblemNodes = selectedIssue ? (overview?.problem_nodes ?? []).filter((node) => node.issue_id === selectedIssue.issue_id) : [];
  const selectedPrimaryNode = selectedProblemNodes[0] ?? null;
  const selectedIssueKind = selectedIssue ? issueProblemKind(selectedIssue) : "system";
  const selectedIssueIntakeLabel = problemIntakeLabel(selectedIssueKind);
  const selectedIssueAgentBrief = problemAgentBrief(selectedIssueKind);
  const selectedIssueEvidenceCount = selectedIssue
    ? [
      selectedIssue.conversation_ref,
      ...(selectedIssue.runtime_trace_refs ?? []),
      ...(selectedIssue.prompt_manifest_refs ?? []),
      ...(selectedIssue.memory_refs ?? []),
      ...(selectedIssue.assertion_refs ?? [])
    ].filter(Boolean).length
    : 0;
  const selectedAnalysisText = traceResultText(traceReport);
  const issueGroups = useMemo(() => {
    const groups = new Map<string, HealthIssue[]>();
    for (const issue of overview?.issues ?? []) {
      const layer = issueLayerLabel(issue);
      groups.set(layer, [...(groups.get(layer) ?? []), issue]);
    }
    return ["系统问题", "测试问题"]
      .map((layer) => ({ layer, issues: groups.get(layer) ?? [] }))
      .filter((group) => group.issues.length);
  }, [overview?.issues]);
  const selectedRelatedCases = useMemo(() => {
    if (!selectedIssue) return [];
    const issueId = selectedIssue.issue_id;
    const issueTitleText = selectedIssue.title.toLowerCase();
    return (harnessMap?.cases ?? []).filter((testCase) => {
      const refs = testCase.issue_refs ?? [];
      const linkedByIssue = refs.some((ref) => String(ref.issue_id || "") === issueId);
      const linkedByOwner = testCase.owner_system === selectedIssue.owner_system;
      const textBlob = `${testCase.title} ${testCase.problem_statement} ${testCase.behavior_under_test}`.toLowerCase();
      return linkedByIssue || linkedByOwner || (!!issueTitleText && textBlob.includes(issueTitleText));
    }).slice(0, 4);
  }, [harnessMap?.cases, selectedIssue]);
  const selectedIssueWhere = selectedPrimaryNode
    ? `${ownerLabel(selectedPrimaryNode.system)} / ${selectedPrimaryNode.stage}`
    : selectedIssue
      ? ownerLabel(selectedIssue.owner_system)
      : "等待选择";
  const selectedIssueWhy = selectedPrimaryNode?.diagnosis || selectedAnalysisText || "当前证据还不足，需要先运行健康子 Agent 或补齐链路证据。";
  const selectedIssueNextAction = selectedPrimaryNode?.suggested_action || (
    selectedIssueKind === "test"
      ? "先完成测试报告语义分析，再回到验证中心复跑确认"
      : selectedRelatedCases.length
        ? "复跑相关验证资源并确认系统问题是否复现"
        : "先补齐主对话、运行链路和上下文证据"
  );
  const selectedTraceEventCount = numberValue(traceReport?.event_count);
  const selectedProblemEventCount = traceReport?.problem_events?.length ?? 0;

  return (
    <div className="workspace-view health-system-view">
      <header className="workspace-view__header">
        <div>
          <p className="workspace-view__eyebrow">健康工作台</p>
          <h2 className="workspace-view__title">健康系统</h2>
          <p className="workspace-view__subtitle">围绕问题定位、验证运行和效率消耗维护系统健康；验证中心保留现有测试体系，情景管理只服务长场景。</p>
        </div>
        <div className="workspace-view__actions">
          <button className="action-button action-button--ghost" disabled={loading} onClick={() => void loadAll()} type="button">
            <RefreshCw size={15} />
            刷新
          </button>
        </div>
      </header>

      {error ? (
        <div className="workspace-alert workspace-alert--danger">
          <AlertTriangle size={16} />
          <span>{error}</span>
        </div>
      ) : null}
      {notice ? (
        <div className="workspace-alert">
          <ShieldCheck size={16} />
          <span>{notice}</span>
        </div>
      ) : null}

      <nav className="health-system-tabs health-system-tabs--merged" aria-label="健康系统分页导航">
        {pages.map((page) => {
          const Icon = page.icon;
          return (
            <button
              className={`health-system-tab ${activePage === page.key ? "health-system-tab--active" : ""}`}
              key={page.key}
              onClick={() => setActivePage(page.key)}
              type="button"
            >
              <Icon size={17} />
              <span>{page.title}</span>
              <em>{page.subtitle}</em>
            </button>
          );
        })}
      </nav>

      {activePage === "overview" ? (
        <div className="health-overview">
          <section className={`health-status-panel health-status-panel--${healthTone}`}>
            <div className="health-status-panel__main">
              <span>系统健康状态</span>
              <strong>{healthState}</strong>
              <p>{healthScore} / 100 · {openIssues ? `${openIssues} 个开放问题待处理` : "没有开放问题"}{failedRunCount ? `，${failedRunCount} 次验证失败` : ""}{slowRunCount ? `，${slowRunCount} 条慢链路` : ""}</p>
            </div>
            <div className="health-status-panel__signals">
              <Metric label="开放问题" value={openIssues} tone={openIssues ? "warning" : "success"} />
              <Metric label="高风险" value={highRiskIssues} tone={highRiskIssues ? "danger" : "success"} />
              <Metric label="验证失败" value={failedRunCount} tone={failedRunCount ? "danger" : "success"} />
              <Metric label="证据缺口" value={evidenceGapCount} tone={evidenceGapCount ? "warning" : "success"} />
              <Metric label="慢链路" value={slowRunCount} tone={slowRunCount ? "warning" : "success"} />
            </div>
          </section>
          <section className="health-command-strip health-command-strip--overview">
            <article>
              <span>验证中心</span>
              <strong>{latestProfile}</strong>
              <p>{selectedTestRun ? `${statusLabel(selectedTestRun.status)} · ${testSummary.passed}/${testSummary.total} · ${formatDuration(selectedTestRun.duration_ms)}` : "还没有测试记录。"}</p>
              <button className="action-button action-button--ghost" onClick={() => setActivePage("verify")} type="button">
                <Play size={15} />
                进入验证运行
              </button>
            </article>
            <article>
              <span>最近问题</span>
              <strong>{selectedIssue?.title || "暂无问题"}</strong>
              <p>{selectedIssue ? `${ownerLabel(selectedIssue.owner_system)} · ${statusLabel(selectedIssue.status)}` : "对话、测试和开发异常会沉淀到这里。"}</p>
              <button className="action-button action-button--ghost" onClick={() => setActivePage("issues")} type="button">
                <Bug size={15} />
                打开问题
              </button>
            </article>
            <article>
              <span>问题报告</span>
              <strong>{selectedHealthRun ? statusLabel(selectedHealthRun.status) : "等待分析"}</strong>
              <p>{selectedHealthRun ? `${laneLabel(selectedHealthRun.runtime_lane)} · ${runtimeProblems} 个异常点` : "点击问题后查看报告，报告内包含链路节点和证据。"}</p>
              <button className="action-button action-button--primary" onClick={() => setActivePage("issues")} type="button">
                <GitBranch size={15} />
                查看问题报告
              </button>
            </article>
          </section>
          <section className="health-workbench-runtime">
            <article className="health-workbench-runtime__panel">
              <div className="health-panel-head">
                <div>
                  <span>诊断 inbox</span>
                  <h3>健康 Agent 应先回答什么</h3>
                </div>
                <Stethoscope size={16} />
              </div>
              <div className="health-diagnosis-stack">
                {diagnosisInbox.slice(0, 4).map((item) => (
                  <section className="health-diagnosis-card" key={item.diagnosis_id}>
                    <div>
                      <span className={`health-pill ${priorityTone(item.priority)}`}>{evidenceStateLabel(item.evidence_state)}</span>
                      <strong>{item.title}</strong>
                    </div>
                    <p>{item.question}</p>
                    <em>{item.recommended_agent_role} · {compactId(item.subject_id)}</em>
                  </section>
                ))}
                {!diagnosisInbox.length ? (
                  <div className="health-empty-state">
                    <CheckCircle2 size={18} />
                    <span>当前没有待诊断对象。</span>
                  </div>
                ) : null}
              </div>
            </article>

            <article className="health-workbench-runtime__panel health-workbench-runtime__panel--chain">
              <div className="health-panel-head">
                <div>
                  <span>失败链路</span>
                  <h3>{primaryFailureChain?.title || "最近失败的关键路径"}</h3>
                </div>
                <Route size={16} />
              </div>
              {primaryFailureChain ? (
                <div className="health-failure-chain">
                  <p>{primaryFailureChain.root_cause_candidate || "已定位到失败链路，等待健康 Agent 形成根因裁决。"}</p>
                  <div className="health-failure-chain__refs">
                    <span>task {compactId(primaryFailureChain.last_task_run_id)}</span>
                    <span>runtime {compactId(primaryFailureChain.last_checkpoint_ref)}</span>
                    <span>coord {compactId(primaryFailureChain.last_coordination_checkpoint_ref)}</span>
                  </div>
                  <ol>
                    {primaryFailureChain.steps.slice(0, 5).map((step) => (
                      <li key={step.step_id || `${step.step_type}-${step.source_ref}`}>
                        <strong>{step.title || step.step_type}</strong>
                        <p>{step.summary || step.source_ref || "该步骤只有引用，等待展开证据。"}</p>
                      </li>
                    ))}
                  </ol>
                </div>
              ) : (
                <div className="health-empty-state">
                  <CheckCircle2 size={18} />
                  <span>没有失败链路需要复盘。</span>
                </div>
              )}
            </article>

            <article className="health-workbench-runtime__panel">
              <div className="health-panel-head">
                <div>
                  <span>恢复候选</span>
                  <h3>只给 runtime control 的安全入口</h3>
                </div>
                <ShieldCheck size={16} />
              </div>
              <div className="health-recovery-stack">
                {recoveryInbox.slice(0, 4).map((item) => (
                  <section className="health-recovery-card" key={item.recovery_id}>
                    <span className={`health-pill ${item.safe_to_resume ? "health-pill--success" : priorityTone(item.side_effect_replay_risk)}`}>
                      {item.safe_to_resume ? "可候选恢复" : riskCopy(item.side_effect_replay_risk)}
                    </span>
                    <strong>{recoveryKindLabel(item.handle_kind)}</strong>
                    <p>{compactId(item.handle_ref)}</p>
                    <em>{item.recommended_action}</em>
                  </section>
                ))}
                {!recoveryInbox.length ? (
                  <div className="health-empty-state">
                    <CheckCircle2 size={18} />
                    <span>当前没有恢复候选。</span>
                  </div>
                ) : null}
              </div>
            </article>
          </section>
          <section className="health-evidence-packet-strip">
            <article>
              <span>Evidence Packet</span>
              <strong>{evidencePackets.length}</strong>
              <p>{evidencePackets[0]?.summary || "健康系统默认展示有用证据包，不再让用户先读整包 raw trace。"}</p>
            </article>
            <article>
              <span>诊断队列</span>
              <strong>{diagnosisInbox.length}</strong>
              <p>{primaryDiagnosis ? `${primaryDiagnosis.recommended_agent_role} · ${primaryDiagnosis.question}` : "没有待处理诊断。"}</p>
            </article>
            <article>
              <span>恢复队列</span>
              <strong>{recoveryInbox.length}</strong>
              <p>{primaryRecovery ? `${recoveryKindLabel(primaryRecovery.handle_kind)} · ${riskCopy(primaryRecovery.side_effect_replay_risk)}` : "恢复动作仍由 RuntimeLoop / TaskGraph runtime 执行。"}</p>
            </article>
          </section>
          <section className="health-regression-sample-board">
            <article className="health-regression-sample-board__hero">
              <div>
                <span>失败样本库</span>
                <strong>{regressionSamples.length}</strong>
                <p>{primaryRegressionSample?.failure_summary || "真实失败 turn 会沉淀为 RegressionSample，再进入契约复跑，而不是靠人工翻 raw artifact。"}</p>
              </div>
              <div className="health-regression-sample-board__stats">
                <span>{scenarioContracts.length} 个场景契约</span>
                <span>{numberValue(workbenchSummary.pending_regression_verification_count)} 个待复跑</span>
              </div>
              <div className="health-regression-sample-board__actions">
                <button
                  className="action-button action-button--ghost"
                  disabled={loading || !activeTestRunId || selectedTestRun?.status === "running"}
                  onClick={() => void promoteActiveRunFailures()}
                  type="button"
                >
                  <FilePlus2 size={14} />
                  沉淀当前失败
                </button>
                {sampleActionMessage ? <em>{sampleActionMessage}</em> : null}
              </div>
            </article>
            <div className="health-regression-sample-list">
              {(regressionSampleInbox.length ? regressionSampleInbox : regressionSamples).slice(0, 4).map((item) => {
                const sample = item as RegressionSample & Record<string, unknown>;
                const sampleId = String(sample.sample_id || "");
                const verificationStatus = sampleVerificationStatus(sample);
                return (
                  <article className="health-regression-sample-card" key={sampleId || `${sample.scenario_id}-${sample.source_turn_id}`}>
                    <div>
                      <span className={`health-pill ${statusTone(verificationStatus)}`}>{statusLabel(verificationStatus)}</span>
                      <strong>{String(sample.title || sample.failure_summary || "未命名失败样本")}</strong>
                    </div>
                    <p>{String(sample.failure_summary || sample.recommended_action || "等待从真实失败中提取断言和证据。")}</p>
                    <em>{compactId(String(sample.scenario_id || ""))} · {compactId(String(sample.source_turn_id || sample.turn_id || ""))}</em>
                    {sampleRerunCommand(sample) ? (
                      <code>{sampleRerunCommand(sample)}</code>
                    ) : null}
                    <div className="health-regression-sample-card__actions">
                      <button
                        className="action-button action-button--primary"
                        disabled={loading || !sampleId}
                        onClick={() => void rerunSample(sampleId)}
                        type="button"
                      >
                        <Play size={13} />
                        复跑
                      </button>
                      <button
                        className="action-button action-button--ghost"
                        disabled={loading || !sampleId}
                        onClick={() => void refreshSampleVerdict(sampleId)}
                        type="button"
                      >
                        <RefreshCw size={13} />
                        刷新裁决
                      </button>
                    </div>
                  </article>
                );
              })}
              {!regressionSamples.length && !regressionSampleInbox.length ? (
                <div className="health-empty-state">
                  <CheckCircle2 size={18} />
                  <span>还没有失败样本，失败 turn 可从验证运行中沉淀。</span>
                </div>
              ) : null}
            </div>
          </section>
        </div>
      ) : null}

      {activePage === "verify" ? (
        <section className={`health-verify-layout ${isLongScenarioMode ? "health-verify-layout--scenario" : ""}`}>
          <div className="health-run-console">
            <div className="health-panel-head">
              <div>
                <span>{isLongScenarioMode ? "长情景测试" : "验证运行"}</span>
                <h3>{isLongScenarioMode ? "长情景工作台" : "运行验证"}</h3>
              </div>
              <Layers3 size={18} />
            </div>
            {!isLongScenarioMode ? (
              <>
                <section className="health-long-card-board">
                  <div className="health-long-card-board__head">
                    <div>
                      <span>长情景运行</span>
                    </div>
                    <em>{longScenarioCases.length} 个情景可配置</em>
                  </div>
                  <div className="health-long-card-grid">
                    {longRunProfiles.map((profile) => {
                      const profileId = profile.id || profile.harness_profile || defaultLongScenarioProfile;
                      const profileCases = longScenarioCases.filter((testCase) => testCase.profiles.includes(profileId));
                      const configuredCases = configuredScenarioCasesForProfile(profileId);
                      const configuredTurnCount = configuredCases.reduce((total, testCase) => total + scenarioTurnsOf(testCase).length, 0);
                      const runnableCount = runnableScenarioIdsForProfile(profileId).length;
                      const selected = selectedScenarioProfile === profileId;
                      return (
                        <article className={`health-long-run-card ${selected ? "health-long-run-card--active" : ""}`} key={profileId}>
                          <div>
                            <span>长情景</span>
                            <strong>{profile.title || profileTitle(profiles, profileId)}</strong>
                            <p>{configuredCases.length ? `已链接 ${configuredCases.length} 个情景 · ${configuredTurnCount} 条对话` : "从情景库链接要运行的情景。"}</p>
                            <em>{profile.estimated_duration || layerMeta[profileId]?.subtitle || "耗时未知"} · {runnableCount} 个可运行情景 · {profileCases.length || longScenarioCases.length} 个可选</em>
                          </div>
                          <div className="health-long-run-card__actions">
                            <button
                              className="action-button action-button--primary"
                              disabled={loading || selectedTestRun?.status === "running"}
                              onClick={() => {
                                setSelectedScenarioProfile(profileId);
                                void startProfile(profileId);
                              }}
                              type="button"
                            >
                              <Play size={14} />
                              运行
                            </button>
                            <button
                              className="action-button action-button--ghost"
                              onClick={() => {
                                openScenarioRunConfig(profileId);
                              }}
                              type="button"
                            >
                              <Pencil size={14} />
                              配置
                            </button>
                          </div>
                        </article>
                      );
                    })}
                  </div>
                  {scenarioEditorOpen ? (() => {
                    const configuredCases = configuredScenarioCasesForProfile(selectedScenarioProfile);
                    const configuredIds = new Set(configuredCases.map((testCase) => testCase.case_id));
                    const runnableCount = runnableScenarioIdsForProfile(selectedScenarioProfile).length;
                    return (
                      <div className="health-inline-scenario-config health-scenario-link-config">
                        <div className="health-panel-head">
                          <div>
                            <span>配置运行情景集合</span>
                            <h3>{profileTitle(profiles, selectedScenarioProfile)}</h3>
                            <p>从情景库链接多个情景，运行时按这个集合执行。</p>
                          </div>
                          <button className="action-button action-button--ghost" onClick={() => setScenarioEditorOpen(false)} type="button">
                            关闭配置
                          </button>
                        </div>
                        <label className="health-scenario-select health-scenario-link-config__profile">
                          <span>运行入口</span>
                          <select value={selectedScenarioProfile} onChange={(event) => openScenarioRunConfig(event.target.value)}>
                            {longRunProfiles.map((profile) => {
                              const profileId = profile.id || profile.harness_profile || defaultLongScenarioProfile;
                              return <option key={profileId} value={profileId}>{profile.title || profileTitle(profiles, profileId)}</option>;
                            })}
                          </select>
                        </label>
                        <div className="health-scenario-link-grid">
                          <section className="health-scenario-link-panel">
                            <div>
                              <span>已链接情景</span>
                              <strong>{configuredCases.length} 个情景 · {runnableCount} 个可运行</strong>
                            </div>
                            <div className="health-scenario-link-list">
                              {configuredCases.map((testCase) => (
                                <article key={testCase.case_id}>
                                  <div>
                                    <span>{scenarioCategoryLabel(scenarioCategoryOf(testCase))} · {scenarioTurnsOf(testCase).length} 条对话</span>
                                    <strong>{testCase.title}</strong>
                                    <p>{testCase.problem_statement || testCase.behavior_under_test}</p>
                                  </div>
                                  <button className="health-turn-delete-button" onClick={() => toggleScenarioForProfile(selectedScenarioProfile, testCase.case_id)} type="button">
                                    移除
                                  </button>
                                </article>
                              ))}
                              {!configuredCases.length ? (
                                <div className="health-empty-state">
                                  <FilePlus2 size={18} />
                                  <span>还没有链接情景，从右侧添加。</span>
                                </div>
                              ) : null}
                            </div>
                          </section>
                          <section className="health-scenario-link-panel">
                            <div>
                              <span>情景库</span>
                              <strong>{longScenarioCases.length} 个可选情景</strong>
                            </div>
                            <div className="health-scenario-link-list">
                              {longScenarioCases.map((testCase) => {
                                const linked = configuredIds.has(testCase.case_id);
                                return (
                                  <article className={linked ? "health-scenario-link-row--active" : ""} key={testCase.case_id}>
                                    <div>
                                      <span>{scenarioCategoryLabel(scenarioCategoryOf(testCase))} · {scenarioTurnsOf(testCase).length} 条对话</span>
                                      <strong>{testCase.title}</strong>
                                      <p>{testCase.problem_statement || testCase.behavior_under_test}</p>
                                    </div>
                                    <button className={linked ? "health-turn-delete-button" : "action-button action-button--ghost"} onClick={() => toggleScenarioForProfile(selectedScenarioProfile, testCase.case_id)} type="button">
                                      {linked ? "移除" : "添加"}
                                    </button>
                                  </article>
                                );
                              })}
                            </div>
                          </section>
                        </div>
                      </div>
                    );
                  })() : null}
                </section>
                <div className="health-scenario-entry">
                  <div>
                    <span>情景库</span>
                    <strong>进入情景库管理情景和对话</strong>
                    <p>情景库里负责新增、删除、分类和对话编辑；上面的卡片只负责运行和快速配置。</p>
                  </div>
                  <div className="health-scenario-entry__actions">
                    <button className="action-button action-button--ghost" onClick={() => selectVerifyProfile(selectedScenarioProfile || defaultLongScenarioProfile)} type="button">
                      <Pencil size={14} />
                      进入情景库
                    </button>
                    <button className="action-button action-button--ghost" onClick={resetScenarioDraft} type="button">
                      <FilePlus2 size={14} />
                      新建情景
                    </button>
                  </div>
                </div>
                <div className="health-profile-board">
                  {fastProfileOrder.map((profileId) => {
                    const profile = profileById(profiles, profileId);
                    const meta = layerMeta[profileId];
                    const selected = selectedProfile === profileId;
                    const caseCount = isLongScenarioProfile(profileId)
                      ? longScenarioCases.filter((testCase) => testCase.profiles.includes(profileId)).length
                      : registry?.profiles?.[profileId]?.case_count ?? 0;
                    return (
                      <button
                        className={`health-profile-card ${selected ? "health-profile-card--active" : ""}`}
                        key={profileId}
                        onClick={() => selectVerifyProfile(profileId)}
                        type="button"
                      >
                        <span>系统门禁</span>
                        <strong>{profile?.title || meta?.title || profileId}</strong>
                        <p>{profile?.description || meta?.intent || "未配置说明。"}</p>
                        <em>{profile?.estimated_duration || meta?.subtitle || "耗时未知"} · {caseCount} 个用例</em>
                      </button>
                    );
                  })}
                </div>
                <div className="health-run-actionbar">
                  <div>
                    <strong>{profileTitle(profiles, selectedProfile)}</strong>
                    <p>{selectedProfileObject?.estimated_duration || layerMeta[selectedProfile]?.subtitle || "耗时未知"} · {layerMeta[selectedProfile]?.intent || selectedProfileObject?.description}</p>
                  </div>
                  <button className="action-button action-button--primary" disabled={loading || selectedTestRun?.status === "running" || !selectedProfileObject} onClick={() => void startProfile(selectedProfile)} type="button">
                    <Play size={15} />
                    运行验证
                  </button>
                </div>
              </>
            ) : (
              <div className="health-scenario-command">
                <div className="health-scenario-command__title">
                  <span>情景库管理</span>
                  <strong>管理情景与多轮对话</strong>
                  <p>{selectedScenarioCase ? `当前选中：${selectedScenarioCase.title} · ${selectedScenarioScriptTurns.length} 条对话` : "从左侧选择情景，右侧直接管理情景信息和对话。"}</p>
                </div>
                <div className="health-scenario-command__actions">
                  <button className="action-button action-button--ghost" onClick={() => selectVerifyProfile("chain")} type="button">
                    返回快速验证
                  </button>
                </div>
              </div>
            )}
          </div>

          {!isLongScenarioMode ? (
          <aside className="health-run-side">
            <article className={`health-run-status-card health-run-status-card--${selectedTestRun?.status || "idle"}`}>
              <div>
                {statusIcon(selectedTestRun?.status || "")}
                <span>最近运行</span>
              </div>
              <strong>{selectedTestRun ? statusLabel(selectedTestRun.status) : "暂无记录"}</strong>
              <p>{selectedTestRun ? `${profileTitle(profiles, selectedTestRun.profile)} · 当前验证记录` : "选择验证层级后开始第一次运行。"}</p>
              {selectedTestRun?.status === "running" ? (
                <button className="action-button action-button--danger" disabled={loading} onClick={() => void cancelActiveTestRun()} type="button">
                  取消运行
                </button>
              ) : (
                <button className="action-button action-button--ghost" disabled={!selectedTestRun} onClick={() => setActivePage("issues")} type="button">
                  问题报告
                </button>
              )}
            </article>
            <article>
              <span>本轮结果</span>
              <strong>{testSummary.passed}/{testSummary.total}</strong>
              <p>{testSummary.failed ? testSummary.first_failure || "存在失败项，会进入问题报告复盘。" : "最近运行没有失败项。"}</p>
            </article>
            <article>
              <span>问题入口</span>
              <strong>{issueRecords.length}</strong>
              <p>测试失败、治理发现和开发异常都会进入问题处理视角。</p>
              <button className="action-button action-button--ghost" onClick={() => setActivePage("issues")} type="button">
                <Bug size={15} />
                打开问题处理
              </button>
            </article>
          </aside>
          ) : null}

          {isLongScenarioMode ? (
          <section className="health-scenario-manager">
            <aside className="health-scenario-library">
              <div className="health-panel-head">
                <div>
                  <span>长场景情景库</span>
                  <h3>{longScenarioCases.length} 个可管理情景</h3>
                </div>
                <button className="action-button action-button--ghost" onClick={resetScenarioDraft} type="button">
                  <FilePlus2 size={15} />
                  新增
                </button>
              </div>
              <label className="health-scenario-search">
                <Search size={14} />
                <input value={scenarioQuery} onChange={(event) => setScenarioQuery(event.target.value)} placeholder="搜索名称、风险、标准" />
              </label>
              <label className="health-scenario-select">
                <span>分类</span>
                <select value={scenarioCategoryFilter} onChange={(event) => setScenarioCategoryFilter(event.target.value)}>
                  {scenarioCategoryOptions.map((category) => (
                    <option key={category} value={category}>
                      {scenarioCategoryLabel(category)} ({scenarioCategoryCounts.get(category) ?? 0})
                    </option>
                  ))}
                </select>
              </label>
              <label className="health-scenario-select">
                <span>来源</span>
                <select value={scenarioSourceFilter} onChange={(event) => setScenarioSourceFilter(event.target.value)}>
                  <option value="all">全部来源</option>
                  <option value="builtin">系统情景</option>
                  <option value="managed">管理中的情景</option>
                </select>
              </label>
              <div className="health-scenario-page-head">
                <span>情景 {pageRangeLabel(filteredScenarioCases.length, scenarioLibraryPage, scenarioLibraryPageSize)}</span>
                <div>
                  <button disabled={scenarioLibraryPage <= 0} onClick={() => setScenarioLibraryPage((current) => Math.max(0, current - 1))} type="button">上一页</button>
                  <button disabled={scenarioLibraryPage >= scenarioLibraryPageCount - 1} onClick={() => setScenarioLibraryPage((current) => Math.min(scenarioLibraryPageCount - 1, current + 1))} type="button">下一页</button>
                </div>
              </div>
              <div className="health-scenario-list">
                {pagedScenarioCases.map((testCase) => (
                  <article
                    className={selectedScenarioCase?.case_id === testCase.case_id ? "health-scenario-row--active" : ""}
                    key={testCase.case_id}
                  >
                    <button className="health-scenario-row-main" onClick={() => selectScenarioCase(testCase)} type="button">
                      <span>{scenarioCategoryLabel(scenarioCategoryOf(testCase))} · {scenarioTurnsOf(testCase).length} 条对话 · {testCase.reason === "front_managed_case" ? "管理中" : "系统情景"}</span>
                      <strong>{testCase.title}</strong>
                      <p>{testCase.problem_statement || testCase.behavior_under_test}</p>
                    </button>
                  </article>
                ))}
                {!filteredScenarioCases.length ? (
                  <div className="health-empty-state">
                    <CheckCircle2 size={18} />
                    <span>没有匹配的长场景情景。</span>
                  </div>
                ) : null}
              </div>
            </aside>

            <div className="health-scenario-workspace health-scenario-workspace--library">
              {scenarioEditorOpen || selectedScenarioCase ? (
                <section className="health-scenario-console">
                  <header className="health-scenario-console-head">
                    <div>
                      <span>
                        {scenarioEditMode === "create"
                          ? "新建情景"
                          : `${scenarioCategoryLabel(caseDraft.category || (selectedScenarioCase ? scenarioCategoryOf(selectedScenarioCase) : ""))} · ${selectedScenarioCase?.reason === "front_managed_case" ? "管理中" : "系统情景"}`}
                      </span>
                      <h3>{caseDraft.feature || selectedScenarioCase?.title || "未命名长情景"}</h3>
                      <p>
                        {scenarioEditMode === "create"
                          ? "先写清情景名、分类和多轮对话，再保存到情景库。"
                          : selectedScenarioCase?.behavior_under_test || "当前情景会作为长情景测试的运行输入。"}
                      </p>
                    </div>
                    <div className="health-scenario-console-actions">
                      <button className="action-button action-button--ghost" onClick={resetScenarioDraft} type="button">
                        <FilePlus2 size={14} />
                        新增情景
                      </button>
                      <button className="action-button action-button--primary" disabled={loading} onClick={() => void createManagedCaseFromForm(scenarioEditMode)} type="button">
                        <Save size={14} />
                        {scenarioEditMode === "create" ? "保存新情景" : selectedScenarioCase?.reason === "front_managed_case" ? "保存情景" : "保存为管理情景"}
                      </button>
                      {selectedScenarioCase ? (
                        <button className="action-button action-button--danger" disabled={loading} onClick={() => removeScenarioFromLibrary(selectedScenarioCase)} type="button">
                          <Trash2 size={14} />
                          删除情景
                        </button>
                      ) : null}
                    </div>
                  </header>

                  <section className="health-scenario-form-panel">
                    <div className="health-scenario-identity">
                      <label>
                        <span>情景名</span>
                        <input value={caseDraft.feature} onChange={(event) => setCaseDraft((current) => ({ ...current, feature: event.target.value }))} placeholder="例如：多轮任务中断后继续推进" />
                      </label>
                      <label>
                        <span>分类</span>
                        <input
                          list="health-scenario-category-options"
                          value={caseDraft.category}
                          onChange={(event) => setCaseDraft((current) => ({ ...current, category: event.target.value }))}
                          placeholder="例如：记忆恢复"
                        />
                        <datalist id="health-scenario-category-options">
                          {scenarioLibraryCategories.map((category) => (
                            <option key={category} value={category} />
                          ))}
                        </datalist>
                      </label>
                      <label className="health-case-form__wide">
                        <span>要防止的偏离</span>
                        <textarea value={caseDraft.problem} onChange={(event) => setCaseDraft((current) => ({ ...current, problem: event.target.value }))} placeholder="这个长情景要防止什么断链、遗忘、误操作或恢复失败。" />
                      </label>
                    </div>

                    <details className="health-scenario-advanced">
                      <summary>运行标准与模板绑定</summary>
                      <div className="health-case-form health-case-form--scenario health-case-form--compact">
                        <label className="health-case-form__wide">
                          <span>全局通过标准</span>
                          <textarea value={caseDraft.expected} onChange={(event) => setCaseDraft((current) => ({ ...current, expected: event.target.value }))} placeholder="整段多轮对话最终怎样算通过。" />
                        </label>
                        <label className="health-case-form__wide">
                          <span>失败样例/备注</span>
                          <textarea value={caseDraft.example} onChange={(event) => setCaseDraft((current) => ({ ...current, example: event.target.value }))} placeholder="可选：这段多轮对话常见失败表现。" />
                        </label>
                        <label>
                          <span>模板</span>
                          <select value={selectedTemplate?.template_id || ""} onChange={(event) => setSelectedTemplateId(event.target.value)}>
                            {(longScenarioTemplates.length ? longScenarioTemplates : caseTemplates).map((template) => (
                              <option key={template.template_id} value={template.template_id}>{template.title}</option>
                            ))}
                          </select>
                        </label>
                      </div>
                    </details>
                  </section>

                  <section className="health-scenario-dialogue-board">
                    <div className="health-panel-head">
                      <div>
                        <span>多轮对话</span>
                        <h3>{caseDraft.turns.length ? `${caseDraft.turns.length} 条对话，当前第 ${selectedScenarioTurnIndex + 1} 条` : "先新增第一条对话"}</h3>
                      </div>
                      <FilePlus2 size={16} />
                    </div>
                    <div className="health-dialogue-split">
                      <div className="health-dialogue-list-pane">
                        <div className="health-scenario-page-head health-scenario-page-head--compact">
                          <span>对话 {pageRangeLabel(caseDraft.turns.length, scenarioEditPage, scenarioEditPageSize)}</span>
                          <div>
                            <button disabled={scenarioEditPage <= 0} onClick={() => goScenarioDialoguePage(scenarioEditPage - 1)} type="button">上一页</button>
                            <button disabled={scenarioEditPage >= scenarioEditPageCount - 1} onClick={() => goScenarioDialoguePage(scenarioEditPage + 1)} type="button">下一页</button>
                          </div>
                        </div>
                        {pagedScenarioEditTurns.map((turn, index) => {
                          const absoluteIndex = scenarioEditPage * scenarioEditPageSize + index;
                          return (
                            <button
                              className={`health-scenario-turn-preview ${selectedScenarioTurnIndex === absoluteIndex ? "health-scenario-turn-preview--active" : ""}`}
                              key={`${turn.turn_id}-${absoluteIndex}`}
                              onClick={() => setSelectedScenarioTurnIndex(absoluteIndex)}
                              type="button"
                            >
                              <span>第 {absoluteIndex + 1} 条对话</span>
                              <strong>{turn.user || "未填写情景提问"}</strong>
                            </button>
                          );
                        })}
                        {!caseDraft.turns.length ? (
                          <div className="health-empty-state">
                            <FilePlus2 size={18} />
                            <span>这个情景还没有对话。</span>
                          </div>
                        ) : null}
                      </div>

                      <div className="health-dialogue-edit-pane">
                        {caseDraft.turns[selectedScenarioTurnIndex] ? (
                          <div className="health-inline-dialogue-manager">
                            <div className="health-panel-head">
                              <div>
                                <span>当前对话</span>
                                <h3>第 {selectedScenarioTurnIndex + 1} 条</h3>
                              </div>
                              <button className="action-button action-button--danger" onClick={() => deleteScenarioTurnAt(selectedScenarioTurnIndex)} type="button">
                                <Trash2 size={14} />
                                删除
                              </button>
                            </div>
                            <label className="health-inline-dialogue-editor">
                              <span>情景提问</span>
                              <textarea
                                value={caseDraft.turns[selectedScenarioTurnIndex].user}
                                onChange={(event) => updateScenarioTurnAt(selectedScenarioTurnIndex, event.target.value)}
                                placeholder="输入这一轮用户会怎么提问"
                              />
                            </label>
                            <div className="health-scenario-insert-box">
                              <label>
                                <span>新增对话</span>
                                <textarea
                                  value={newScenarioTurnText}
                                  onChange={(event) => setNewScenarioTurnText(event.target.value)}
                                  placeholder="输入新对话，添加到当前对话后"
                                />
                              </label>
                              <div className="health-dialogue-insert-actions">
                                <button className="action-button action-button--ghost" onClick={insertScenarioTurnAfterCurrent} type="button">
                                  <FilePlus2 size={14} />
                                  添加到当前后
                                </button>
                                <button className="action-button action-button--primary" disabled={loading} onClick={() => void createManagedCaseFromForm(scenarioEditMode)} type="button">
                                  <Save size={14} />
                                  保存情景
                                </button>
                              </div>
                            </div>
                          </div>
                        ) : (
                          <div className="health-inline-dialogue-manager">
                            <div className="health-panel-head">
                              <div>
                                <span>当前对话</span>
                                <h3>还没有可编辑对话</h3>
                              </div>
                            </div>
                            <div className="health-scenario-insert-box">
                              <label>
                                <span>新增第一条对话</span>
                                <textarea
                                  value={newScenarioTurnText}
                                  onChange={(event) => setNewScenarioTurnText(event.target.value)}
                                  placeholder="输入第一轮用户提问"
                                />
                              </label>
                              <div className="health-dialogue-insert-actions">
                                <button className="action-button action-button--primary" onClick={insertScenarioTurnAfterCurrent} type="button">
                                  <FilePlus2 size={14} />
                                  添加第一条对话
                                </button>
                              </div>
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  </section>
                </section>
              ) : (
                <div className="health-empty-state">
                  <CheckCircle2 size={18} />
                  <span>选择左侧情景，或新建一个长情景。</span>
                </div>
              )}
            </div>
          </section>
          ) : null}
        </section>
      ) : null}

      {activePage === "issues" ? (
        <section className="health-problem-board">
          <aside className="health-problem-inbox" aria-label="问题列表">
            <div className="health-panel-head">
              <div>
                <span>问题中心</span>
                <h3>按问题类型处理</h3>
              </div>
              <ListChecks size={16} />
            </div>
            {workbench?.inbox_items.length ? (
              <section className="health-problem-group health-problem-group--workbench">
                <header>
                  <span>工作台待处理</span>
                  <em>{workbench.inbox_items.length}</em>
                </header>
                <div className="health-inbox-list">
                  {workbench.inbox_items.slice(0, 6).map((item) => {
                    const kind = inboxProblemKind(item);
                    return (
                      <article
                        className={`health-inbox-item ${selectedInboxItem?.item_id === item.item_id ? "health-inbox-item--active" : ""}`}
                        key={item.item_id}
                      >
                        <button onClick={() => openInboxItem(item)} type="button">
                          <span className={`health-pill health-pill--${kind === "system" ? "danger" : item.evidence_state === "missing" ? "warning" : "success"}`}>
                            {problemKindLabel(kind)}
                          </span>
                          <strong>{item.title}</strong>
                          <em>{problemIntakeLabel(kind)} · {item.reason}</em>
                        </button>
                        {item.subject_type !== "health_issue" ? (
                          <button className="health-inbox-action" disabled={loading} onClick={() => void registerInboxItemAsIssue(item)} type="button">
                            先登记为{problemKindLabel(kind)}
                          </button>
                        ) : null}
                      </article>
                    );
                  })}
                </div>
              </section>
            ) : null}
            {issueGroups.length ? issueGroups.map((group) => (
              <section className="health-problem-group" key={group.layer}>
                <header>
                  <span>{group.layer}</span>
                  <em>{group.issues.length}</em>
                </header>
                {group.issues.map((issue) => (
                  <button
                    className={`health-problem-row ${selectedIssue?.issue_id === issue.issue_id ? "health-problem-row--active" : ""}`}
                    key={issue.issue_id}
                    onClick={() => selectIssue(issue)}
                    type="button"
                  >
                    <span className={`health-pill health-pill--${issueLayerTone(issue)}`}>{severityLabel(issue.severity)}</span>
                    <strong>{issue.title}</strong>
                    <p>{problemIntakeLabel(issueProblemKind(issue))} · {ownerLabel(issue.owner_system)} · {statusLabel(issue.status)}</p>
                  </button>
                ))}
              </section>
            )) : (
              <div className="health-empty-state">
                <CheckCircle2 size={18} />
                <span>当前没有开放问题。</span>
              </div>
            )}
          </aside>

          <main className="health-problem-report">
            <section className="health-problem-report__header">
              <div>
                <span>{selectedIssue ? issueLayerLabel(selectedIssue) : "问题报告"}</span>
                <h3>{selectedIssue?.title || "请选择一个问题"}</h3>
                <p>{selectedIssue ? `${selectedIssueIntakeLabel} · ${ownerLabel(selectedIssue.owner_system)} · ${severityLabel(selectedIssue.severity)} · ${statusLabel(selectedIssue.status)}` : "选择左侧问题后，这里会显示定位、原因、链路和处理建议。"}</p>
              </div>
              <button
                className="action-button action-button--primary"
                disabled={!selectedIssue || !!runningIssueId}
                onClick={() => void runHealthAgent()}
                type="button"
              >
                <Stethoscope size={15} />
                {runningIssueId ? "分析中" : "生成问题报告"}
              </button>
            </section>

            <nav className="health-report-tabs" aria-label="问题报告视图">
              {problemReportTabs.map((tab) => (
                <button
                  className={problemReportTab === tab.key ? "health-report-tab--active" : ""}
                  key={tab.key}
                  onClick={() => setProblemReportTab(tab.key)}
                  type="button"
                >
                  <strong>{tab.title}</strong>
                  <span>{tab.subtitle}</span>
                </button>
              ))}
            </nav>

            <section className="health-problem-report__body">
              {problemReportTab === "details" ? (
                <div className="health-report-section">
                  <section className="health-report-kv-grid">
                    <article>
                      <span>问题分类</span>
                      <strong>{selectedIssue ? issueLayerLabel(selectedIssue) : "未选择"}</strong>
                    </article>
                    <article>
                      <span>收集方式</span>
                      <strong>{selectedIssue ? selectedIssueIntakeLabel : "未选择"}</strong>
                    </article>
                    <article>
                      <span>责任系统</span>
                      <strong>{selectedIssue ? ownerLabel(selectedIssue.owner_system) : "未归属"}</strong>
                    </article>
                    <article>
                      <span>处理状态</span>
                      <strong>{selectedIssue ? statusLabel(selectedIssue.status) : "未知"}</strong>
                    </article>
                    <article>
                      <span>证据数量</span>
                      <strong>{selectedIssueEvidenceCount}</strong>
                    </article>
                  </section>
                  <section className="health-report-card health-report-card--diagnosis">
                    <div className="health-panel-head">
                      <div>
                        <span>{selectedIssue ? issueLayerLabel(selectedIssue) : "问题机制"}</span>
                        <h3>{selectedIssueKind === "test" ? "测试问题先分析语义，再进入验证闭环" : "系统问题来自主对话监督"}</h3>
                      </div>
                      <Stethoscope size={16} />
                    </div>
                    <p className="health-copy">{selectedIssueAgentBrief}</p>
                  </section>
                  <section className="health-report-card">
                    <div className="health-panel-head">
                      <div>
                        <span>证据状态</span>
                        <h3>这个问题现在靠什么定位</h3>
                      </div>
                      <ClipboardList size={16} />
                    </div>
                    <div className="health-report-evidence-row">
                      <em>{selectedIssue?.conversation_ref ? "对话已绑定" : "对话缺失"}</em>
                      <em>{selectedIssue?.runtime_trace_refs?.length ? "运行链路已绑定" : "运行链路缺失"}</em>
                      <em>{selectedIssue?.prompt_manifest_refs?.length ? "提示证据已绑定" : "提示证据缺失"}</em>
                      <em>{selectedIssue?.memory_refs?.length ? "记忆证据已绑定" : "记忆证据缺失"}</em>
                    </div>
                  </section>
                  <section className="health-report-card">
                    <div className="health-panel-head">
                      <div>
                        <span>关联验证资源</span>
                        <h3>这个问题由哪些验证资源守住</h3>
                      </div>
                      <TestTube2 size={16} />
                    </div>
                    <div className="health-linked-case-list">
                      {selectedRelatedCases.length ? selectedRelatedCases.map((testCase) => (
                        <article key={testCase.case_id}>
                          <strong>{testCase.title}</strong>
                          <p>{testCase.path || "验证资源暂未生成测试文件"}</p>
                          <em>{testCase.runner} · {testCase.profiles.join(" / ") || "未绑定 profile"}</em>
                        </article>
                      )) : (
                        <div className="health-empty-state">还没有直接关联的验证资源。问题分析清楚后，到验证中心补充可复跑资源。</div>
                      )}
                    </div>
                  </section>
                </div>
              ) : null}

              {problemReportTab === "analysis" ? (
                <div className="health-report-section">
                  <section className="health-problem-answer-grid">
                    <article>
                      <span>哪里出了问题</span>
                      <strong>{selectedIssueWhere}</strong>
                      <p>{selectedPrimaryNode ? `定位置信度 ${Math.round(selectedPrimaryNode.confidence * 100)}%，绑定 ${selectedPrimaryNode.evidence_refs.length} 条证据。` : "还没有稳定问题节点，先看链路证据是否完整。"}</p>
                    </article>
                    <article>
                      <span>为什么出问题</span>
                      <strong>{selectedPrimaryNode?.diagnosis ? "已有节点诊断" : selectedAnalysisText ? "已有分析输出" : "解释不足"}</strong>
                      <p>{selectedIssueKind === "test" && !selectedAnalysisText ? "需要让健康子 Agent 读取测试报告、测试目标和生成结果语义，先判断是产品异常、测试设计问题，还是生成结果偏差。" : selectedIssueWhy}</p>
                    </article>
                    <article>
                      <span>下一步怎么处理</span>
                      <strong>{selectedIssue ? selectedIssueNextAction : "先选择问题"}</strong>
                      <p>{selectedIssue ? (selectedIssueKind === "system" ? "系统问题先补齐主对话监督证据，再决定是否需要复跑验证。" : "测试问题先完成语义判断，再把确认的问题沉淀成验证资源。") : "左侧选择问题后再执行分析。"}</p>
                    </article>
                    <article>
                      <span>耗时证据</span>
                      <strong>{selectedTestRun ? formatDuration(selectedTestRun.duration_ms) : "暂无验证耗时"}</strong>
                      <p>{Number(latency.slow_run_count ?? 0) ? `最近有 ${Number(latency.slow_run_count ?? 0)} 条慢链路，需要作为效率问题追踪。` : "当前没有慢链路告警。"}</p>
                    </article>
                  </section>
                  <section className="health-report-card health-report-card--diagnosis">
                    <div className="health-panel-head">
                      <div>
                        <span>问题报告摘要</span>
                      </div>
                      <Bug size={16} />
                    </div>
                    <div className="health-diagnosis-readable">
                      <article>
                        <strong>定位</strong>
                        <p>{selectedIssueWhere}</p>
                      </article>
                      <article>
                        <strong>证据</strong>
                        <p>{selectedTraceEventCount ? `${selectedTraceEventCount} 个链路事件，${selectedProblemEventCount} 个优先排查节点。` : `${selectedIssueEvidenceCount} 条登记证据，尚未形成完整链路报告。`}</p>
                      </article>
                      <article>
                        <strong>验证资源</strong>
                        <p>{selectedIssueKind === "test" ? (selectedRelatedCases.length ? `已关联 ${selectedRelatedCases.length} 个 harness 用例，需确认测试语义是否正确。` : "先判断测试报告语义，再回验证中心决定是否补资源。") : (selectedRelatedCases.length ? `已关联 ${selectedRelatedCases.length} 个 harness 用例，可用于复跑确认。` : "系统问题定位稳定后，再回验证中心补资源。")}</p>
                      </article>
                    </div>
                  </section>
                  <section className="health-report-card">
                    <div className="health-panel-head">
                      <div>
                        <span>分析记录</span>
                        <h3>健康子 Agent 输出</h3>
                      </div>
                      <Stethoscope size={16} />
                    </div>
                    <div className="health-run-list health-run-list--compact">
                      {healthRunsForIssue.map((run, index) => (
                        <button
                          className={selectedHealthRun?.run_id === run.run_id ? "health-run-row--active" : ""}
                          key={run.run_id}
                          onClick={() => setSelectedHealthRunId(run.run_id)}
                          type="button"
                        >
                          <span className={`health-pill ${statusTone(run.status)}`}>{statusLabel(run.status)}</span>
                          <strong>问题分析 {index + 1}</strong>
                          <em>{laneLabel(run.runtime_lane)} · {terminalLabel(run.terminal_reason)}</em>
                        </button>
                      ))}
                      {!healthRunsForIssue.length ? <div className="health-empty-state">还没有分析记录。</div> : null}
                    </div>
                  </section>
                </div>
              ) : null}

              {problemReportTab === "chain" ? (
                <section className="health-report-card health-report-card--chain">
                  <div className="health-panel-head">
                    <div>
                      <span>链路追踪</span>
                      <h3>问题节点关系与支撑事件</h3>
                    </div>
                    <Route size={16} />
                  </div>
                  <HealthTraceTimeline report={traceReport} selectedRunId={selectedHealthRun?.run_id ?? ""} />
                </section>
              ) : null}

              {problemReportTab === "closure" ? (
                <div className="health-report-section">
                  <section className="health-report-kv-grid">
                    <article>
                      <span>最近验证</span>
                      <strong>{selectedTestRun ? statusLabel(selectedTestRun.status) : "未运行"}</strong>
                    </article>
                    <article>
                      <span>通过情况</span>
                      <strong>{testSummary.passed}/{testSummary.total}</strong>
                    </article>
                    <article>
                      <span>失败项</span>
                      <strong>{testSummary.failed}</strong>
                    </article>
                    <article>
                      <span>验证耗时</span>
                      <strong>{formatDuration(selectedTestRun?.duration_ms)}</strong>
                    </article>
                  </section>
                  <section className="health-report-card">
                    <div className="health-panel-head">
                      <div>
                        <span>验证闭环建议</span>
                        <h3>{selectedIssueKind === "test" ? "先确认测试问题，再沉淀资源" : "系统问题确认后再补验证资源"}</h3>
                      </div>
                      <TestTube2 size={16} />
                    </div>
                    <div className="health-closure-list">
                      <article>
                        <strong>{selectedIssueKind === "test" ? "分析测试报告语义" : "复核主对话异常"}</strong>
                        <p>{selectedIssueKind === "test" ? (testSummary.first_failure || "读取测试报告、测试目标和生成结果，判断失败是否代表真实系统退化。") : "确认主对话异常、运行链路、提示上下文和记忆证据能互相印证。"}</p>
                      </article>
                      <article>
                        <strong>{selectedRelatedCases.length ? "复跑关联验证" : "回验证中心补资源"}</strong>
                        <p>{selectedRelatedCases[0]?.path || "只有在问题原因和通过标准明确后，才进入验证中心生成可复跑资源。"}</p>
                      </article>
                      <article>
                        <strong>关闭标准</strong>
                        <p>问题报告有定位、有原因、有链路证据，并且验证计划通过后再关闭。</p>
                      </article>
                    </div>
                  </section>
                </div>
              ) : null}
            </section>
          </main>
        </section>
      ) : null}

      {activePage === "time" ? (
        <section className="health-time-dashboard">
          <section className="health-command-strip">
            <article>
              <span>平均验证耗时</span>
              <strong>{formatDuration(Number(latency.average_duration_ms ?? 0))}</strong>
              <p>按最近验证运行计算，用来发现验证链路是否变慢。</p>
            </article>
            <article>
              <span>最长验证耗时</span>
              <strong>{formatDuration(Number(latency.max_duration_ms ?? 0))}</strong>
              <p>慢链路阈值：{formatDuration(Number(latency.slow_threshold_ms ?? 0))}。</p>
            </article>
            <article>
              <span>Token 总消耗</span>
              <strong>{numberValue(tokenHealth.total_tokens).toLocaleString()}</strong>
              <p>读取运行时 token accounting；统计口径：每天与每 6 小时。</p>
            </article>
          </section>

          <section className="health-system-grid">
            <article className="health-system-card">
              <div className="health-panel-head">
                <div>
                  <span>慢链路信号</span>
                  <h3>需要纳入健康维护的耗时问题</h3>
                </div>
                <Clock3 size={16} />
              </div>
              <div className="health-case-list">
                {efficiencySignals.length ? efficiencySignals.map((signal, index) => (
                  <article className="health-case-item" key={String(signal.signal_id || index)}>
                    <span>{String(signal.signal_type || "latency")}</span>
                    <strong>{String(signal.title || "耗时偏高")}</strong>
                    <p>{String(signal.detail || "该链路耗时超过阈值，需要进入问题分析。")}</p>
                  </article>
                )) : (
                  <div className="health-empty-state">
                    <CheckCircle2 size={18} />
                    <span>当前没有慢链路告警。</span>
                  </div>
                )}
              </div>
            </article>

            <article className="health-system-card health-token-summary">
              <div className="health-panel-head">
                <div>
                  <span>Token 统计模块</span>
                  <h3>当前聚合口径</h3>
                </div>
                <Activity size={16} />
              </div>
              <div className="health-asset-stats">
                <Metric label="总消耗" value={numberValue(tokenHealth.total_tokens).toLocaleString()} />
                <Metric label="记录数" value={numberValue(tokenHealth.record_count ?? tokenHealth.session_count)} />
                <Metric label="日桶数" value={dailyTokenBuckets.length} />
                <Metric label="6 小时桶数" value={sixHourTokenBuckets.length} />
              </div>
              <p className="health-token-note">{String(tokenHealth.note || "读取运行时 token accounting。")}</p>
            </article>
          </section>

          <section className="health-token-chart-panel">
            <div className="health-panel-head">
              <div>
                <span>Token 消耗折线图</span>
                <h3>{tokenChartTitle}</h3>
              </div>
              <Activity size={16} />
            </div>
            <div className="health-token-switch" role="tablist" aria-label="Token 消耗统计口径">
              <button
                aria-selected={tokenChartMode === "daily"}
                className={tokenChartMode === "daily" ? "health-token-switch__item--active" : ""}
                onClick={() => setTokenChartMode("daily")}
                role="tab"
                type="button"
              >
                每日
              </button>
              <button
                aria-selected={tokenChartMode === "six_hour"}
                className={tokenChartMode === "six_hour" ? "health-token-switch__item--active" : ""}
                onClick={() => setTokenChartMode("six_hour")}
                role="tab"
                type="button"
              >
                每 6 小时
              </button>
            </div>

            <div className="health-token-line-chart" aria-label="Token 消耗折线图">
              <div className="health-token-y-axis" aria-hidden="true">
                {tokenChartTicks.map((tick, index) => <span key={`${tick}-${index}`}>{compactNumber(tick)}</span>)}
              </div>
              <div className="health-token-line-plot">
                <div className="health-token-grid-lines" aria-hidden="true">
                  {tokenChartTicks.map((tick, index) => <i key={`${tick}-${index}`} />)}
                </div>
                <svg className="health-token-line-svg" viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label={`${tokenChartTitle} token 消耗趋势`}>
                  {tokenLineArea ? <polygon className="health-token-line-area" points={tokenLineArea} /> : null}
                  {tokenLinePolyline ? <polyline className="health-token-line-path" points={tokenLinePolyline} /> : null}
                </svg>
                <div className="health-token-line-values">
                  {tokenLinePoints.map((point, index) => (
                    <span key={`${String(point.bucket.bucket)}-value-${index}`} style={{ left: `${point.x}%`, top: `${point.y}%` }}>
                      {compactNumber(point.value)}
                    </span>
                  ))}
                </div>
                <div className="health-token-x-axis">
                  {activeTokenBuckets.map((bucket) => (
                    <span key={String(bucket.bucket)}>{String(bucket.bucket)}</span>
                  ))}
                </div>
              </div>
            </div>

            <details className="health-token-detail-table">
              <summary>查看数据明细</summary>
              <div className="health-token-table" role="table" aria-label="Token 消耗数据明细">
                <div className="health-token-table__head" role="row">
                  <span role="columnheader">{tokenChartBucketLabel}</span>
                  <span role="columnheader">消耗</span>
                  <span role="columnheader">记录</span>
                </div>
                {activeTokenBuckets.map((bucket) => {
                  const tokens = numberValue(bucket.tokens);
                  const records = numberValue(bucket.records ?? bucket.sessions);
                  return (
                    <div className="health-token-table__row" key={String(bucket.bucket)} role="row">
                      <span>{String(bucket.bucket)}</span>
                      <div className="health-token-table__bar">
                        <i style={{ width: `${Math.max(3, (tokens / maxActiveTokenBucket) * 100)}%` }} />
                        <strong>{tokens.toLocaleString()}</strong>
                      </div>
                      <em>{records}</em>
                    </div>
                  );
                })}
              </div>
            </details>
            <p className="health-token-note">{String(tokenHealth.note || "读取运行时 token accounting。")}</p>
          </section>
        </section>
      ) : null}

      <HealthAgentDock
        onExplainRun={explainSelectedHealthRun}
        onOpenReport={openSelectedTechnicalReport}
        running={!!runningIssueId}
        selectedIssue={selectedIssue}
        selectedRun={selectedHealthRun}
      />
    </div>
  );
}

function Metric({
  label,
  value,
  tone = ""
}: {
  label: string;
  value: unknown;
  tone?: "danger" | "warning" | "success" | "";
}) {
  return (
    <article className={`health-metric ${tone ? `health-metric--${tone}` : ""}`}>
      <span>{label}</span>
      <strong>{text(value, "0")}</strong>
    </article>
  );
}
