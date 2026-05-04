"use client";

import {
  Bot,
  Boxes,
  GitBranch,
  Layers3,
  Loader2,
  Plus,
  Save,
  Search,
  ShieldCheck,
  Sparkles,
  UserCog,
  Workflow
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  deleteTaskSystemAgent,
  getNextWorkerAgentId,
  getSoulProjectionCards,
  getTaskSystemNextIds,
  getTaskSystemOverview,
  upsertTaskSystemAgent,
  upsertTaskSystemAssignment,
  upsertTaskSystemCoordinationTask,
  upsertTaskSystemGeneralProfile,
  upsertTaskSystemTopologyTemplate,
  upsertTaskWorkflow,
  type CoordinationTask,
  type GeneralTaskProfile,
  type SoulProjectionCard,
  type SoulProjectionCatalog,
  type TaskAssignment,
  type TaskSystemAgentUpsertPayload,
  type TaskSystemOverview,
  type TaskWorkflowRecord,
  type TopologyTemplate
} from "@/lib/api";

type TaskPage = "agents" | "tasks" | "coordination";
type TaskModeTab = "general" | "specific";
type TaskWorkbenchTab = "definition" | "adoption" | "method" | "safety" | "assembly";

type AgentCategory = {
  category_id: string;
  title: string;
  editable: boolean;
  agents: AgentRecord[];
};

type AgentRecord = {
  agent_id: string;
  agent_name: string;
  agent_category: string;
  interface_target: string;
  description: string;
  enabled: boolean;
  editable: boolean;
  builtin: boolean;
  default_soul_id: string;
  default_projection_id: string;
  task_scope: string[];
  metadata?: Record<string, unknown>;
};

type TaskSystemTaskManagement = {
  general_tasks: GeneralTaskProfile[];
  specific_tasks: TaskAssignment[];
  workflow_resources: TaskWorkflowRecord[];
};

type TaskSystemCoordinationManagement = {
  coordination_tasks: CoordinationTask[];
  topology_templates: TopologyTemplate[];
};

type TaskSystemConsole = TaskSystemOverview & {
  agent_management: {
    categories: AgentCategory[];
  };
  task_management: TaskSystemTaskManagement;
  coordination_management: TaskSystemCoordinationManagement;
};

type AgentDraft = {
  agent_id: string;
  agent_name: string;
  agent_category: string;
  interface_target: string;
  description: string;
  enabled: boolean;
  editable: boolean;
  default_soul_id: string;
  default_projection_id: string;
  task_scope_text: string;
};

type SpecificTaskDraft = TaskAssignment & {
  trigger_signals_text: string;
  notes: string;
  safety_write_roots_text: string;
  safety_forbidden_paths_text: string;
};

type WorkflowDraft = TaskWorkflowRecord & {
  steps_text: string;
  visible_skill_ids_text: string;
  stop_conditions_text: string;
  required_evidence_refs_text: string;
  compatible_projection_ids_text: string;
};

type CoordinationDraft = CoordinationTask & {
  participant_agent_ids_text: string;
  stop_conditions_text: string;
};

type TopologyDraft = TopologyTemplate & {
  nodes_text: string;
  edges_text: string;
  handoff_rules_text: string;
};

const CATEGORY_ICONS = {
  main_agent: Bot,
  system_management_agent: ShieldCheck,
  worker_sub_agent: Boxes
} as const;

const CATEGORY_TITLES = {
  main_agent: "主 Agent",
  system_management_agent: "系统管理 Agent",
  worker_sub_agent: "工作子 Agent"
} as const;

const SAFETY_CLASS_OPTIONS = [
  { value: "S0_readonly", label: "S0 只读" },
  { value: "S1_bounded_artifact_write", label: "S1 受限产物写入" },
  { value: "S2_bounded_patch", label: "S2 受限补丁" },
  { value: "S3_execution_guarded", label: "S3 受控执行" }
] as const;

const WRITE_MODE_OPTIONS = [
  { value: "none", label: "只读" },
  { value: "bounded_create", label: "限定创建" },
  { value: "scoped_patch", label: "限定补丁" },
  { value: "guarded_execution", label: "受控执行" }
] as const;

const TASK_MODE_OPTIONS = [
  { value: "bounded_patch", label: "受限补丁", family: "development" },
  { value: "light_web_game", label: "轻量网页小游戏", family: "development" },
  { value: "arcade_game_bundle", label: "复合网页小游戏包", family: "development" },
  { value: "short_story", label: "短篇小说协作写作", family: "writing" }
] as const;

const TASK_FAMILY_OPTIONS = [
  { value: "development", label: "开发任务" },
  { value: "writing", label: "写作任务" },
  { value: "health", label: "健康治理" }
] as const;

function text(value: unknown, fallback = "-") {
  if (Array.isArray(value)) return value.length ? value.join(" / ") : fallback;
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

function listText(value: unknown) {
  return Array.isArray(value) ? value.map((item) => String(item)).join("\n") : "";
}

function splitList(value: string) {
  return value.split(/[\n,，]/).map((item) => item.trim()).filter(Boolean);
}

function slug(value: string) {
  return value.trim().toLowerCase().replace(/[^a-z0-9_:-]+/g, "_").replace(/^_+|_+$/g, "");
}

function jsonText(value: unknown) {
  return JSON.stringify(value ?? [], null, 2);
}

function parseJsonList(value: string) {
  try {
    const parsed = JSON.parse(value || "[]");
    return Array.isArray(parsed) ? parsed.filter((item) => typeof item === "object" && item !== null) as Array<Record<string, unknown>> : [];
  } catch {
    return [];
  }
}

function parseSteps(value: string) {
  return value
    .split(/\r?\n/)
    .map((line, index) => {
      const raw = line.trim();
      if (!raw) return null;
      const [stepId, title] = raw.split("|").map((part) => part.trim());
      return { step_id: stepId || `step_${index + 1}`, title: title || stepId || `步骤 ${index + 1}` };
    })
    .filter(Boolean) as Array<Record<string, unknown>>;
}

function labelTaskMode(mode: string) {
  const normalized = mode.trim().toLowerCase();
  if (!normalized) return "未定义模式";
  const option = TASK_MODE_OPTIONS.find((item) => item.value === normalized);
  if (option) return option.label;
  if (normalized === "bounded_patch") return "受限补丁";
  if (normalized === "light_web_game") return "轻量网页小游戏";
  if (normalized === "arcade_game_bundle") return "复合网页小游戏包";
  return mode;
}

function labelTaskFamily(family: string) {
  return TASK_FAMILY_OPTIONS.find((item) => item.value === family)?.label ?? family ?? "未分组";
}

function displayNumberFromId(value: string, label: string) {
  const suffix = String(value || "").split(".").pop() ?? "";
  if (/^\d+$/.test(suffix)) {
    return `${label}-${Number(suffix).toString().padStart(3, "0")}`;
  }
  return value ? "系统预置" : "未生成";
}

function labelExecutionMode(mode: string) {
  if (mode === "single_agent") return "单 Agent";
  if (mode === "coordination_candidate") return "协作候选";
  if (mode === "subagent_allowed") return "可派生子 Agent";
  return mode || "未定义";
}

function labelWorkflowTitle(workflows: TaskWorkflowRecord[], workflowId: string) {
  return workflows.find((workflow) => workflow.workflow_id === workflowId)?.title ?? "未绑定流程";
}

function maskSystemValue(value: string, fallback = "系统已管理") {
  return value && value.trim() ? fallback : "未设置";
}

function normalizeSafetyPolicy(policy: Record<string, unknown> | null | undefined) {
  const source = policy ?? {};
  return {
    safety_class: text(source.safety_class, "S0_readonly"),
    write_mode: text(source.write_mode, "none"),
    write_roots: Array.isArray(source.write_roots) ? source.write_roots.map((item) => String(item)).filter(Boolean) : [],
    forbidden_paths: Array.isArray(source.forbidden_paths) ? source.forbidden_paths.map((item) => String(item)).filter(Boolean) : [],
    verification_mode: text(source.verification_mode, "final_answer_only")
  };
}

function formatSafetySummary(policy: Record<string, unknown>) {
  const normalized = normalizeSafetyPolicy(policy);
  const rootLabel = normalized.write_roots.length ? `${normalized.write_roots.length} 个写入根` : "未限定写入根";
  return `${normalized.safety_class} / ${normalized.write_mode} / ${rootLabel}`;
}

function stepsToText(steps: Array<Record<string, unknown>>) {
  return steps.map((step) => `${text(step.step_id, "")} | ${text(step.title, "")}`).join("\n");
}

function badgeClass(value: unknown) {
  const normalized = String(value || "").toLowerCase();
  if (["enabled", "true"].includes(normalized)) return "task-system-badge task-system-badge--ok";
  if (["disabled", "false"].includes(normalized)) return "task-system-badge task-system-badge--danger";
  return "task-system-badge task-system-badge--warn";
}

function Badge({ value }: { value: unknown }) {
  return <span className={badgeClass(value)}>{text(value)}</span>;
}

function emptyAgentDraft(agentId = "agent:6"): AgentDraft {
  return {
    agent_id: agentId,
    agent_name: "新工作子Agent",
    agent_category: "worker_sub_agent",
    interface_target: "worker_task_console",
    description: "",
    enabled: true,
    editable: true,
    default_soul_id: "",
    default_projection_id: "",
    task_scope_text: ""
  };
}

function agentDraftFrom(agent: AgentRecord): AgentDraft {
  return {
    agent_id: agent.agent_id,
    agent_name: agent.agent_name,
    agent_category: agent.agent_category,
    interface_target: agent.interface_target,
    description: agent.description,
    enabled: agent.enabled,
    editable: agent.editable,
    default_soul_id: agent.default_soul_id,
    default_projection_id: agent.default_projection_id,
    task_scope_text: listText(agent.task_scope)
  };
}

function isMainAgentCategory(category: string) {
  return category === "main_agent";
}

function preferredGeneralWorkflowId(workflows: TaskWorkflowRecord[]) {
  return workflows.find((workflow) => workflow.workflow_id === "workflow.general.main_conversation")?.workflow_id
    ?? workflows[0]?.workflow_id
    ?? "";
}

function preferredSpecificWorkflowId(workflows: TaskWorkflowRecord[]) {
  return workflows.find((workflow) => workflow.workflow_id === "workflow.dev.bounded_patch")?.workflow_id
    ?? workflows.find((workflow) => workflow.workflow_id === "workflow.dev.light_web_game")?.workflow_id
    ?? workflows[0]?.workflow_id
    ?? "workflow.dev.bounded_patch";
}

function emptyGeneralTask(workflowId = "", projectionId = ""): GeneralTaskProfile {
  return {
    profile_id: "general.conversation.default",
    title: "主会话通用任务",
    default_agent_id: "agent:0",
    default_workflow_id: workflowId,
    default_projection_id: projectionId,
    input_contract_id: "UserMessage",
    output_contract_id: "AssistantFinalAnswer",
    conversation_entry_policy: "user_dialogue_to_main_agent",
    enabled: true,
    metadata: { managed_by: "task_system_console" }
  };
}

function emptySpecificTask(workflowId = "", projectionId = ""): SpecificTaskDraft {
  const resolvedWorkflowId = workflowId || "workflow.dev.bounded_patch";
  const workflowMode = resolvedWorkflowId.includes("light_web_game")
    ? "light_web_game"
    : resolvedWorkflowId.includes("arcade_game_bundle")
      ? "arcade_game_bundle"
      : "bounded_patch";
  const safetyPolicy = workflowMode === "light_web_game"
    ? {
        safety_class: "S1_bounded_artifact_write",
        write_mode: "bounded_create",
        write_roots: ["frontend/public/games"],
        forbidden_paths: ["backend", "storage", ".env", ".env.local", ".git"],
        verification_mode: "artifact_refs_required"
      }
    : {
        safety_class: "S2_bounded_patch",
        write_mode: "scoped_patch",
        write_roots: [],
        forbidden_paths: [".env", ".env.local", "storage", "node_modules", ".git"],
        verification_mode: "artifact_or_edit_proof"
      };
  return {
    task_id: "task.dev.new_task",
    task_title: "新特定任务",
    task_kind: "specific_task",
    task_family: "development",
    task_mode: workflowMode,
    flow_id: `flow.dev.${workflowMode}`,
    default_agent_id: "agent:0",
    participant_agent_ids: [],
    workflow_id: resolvedWorkflowId,
    workflow_file_ref: `workflow:${resolvedWorkflowId}`,
    projection_id: projectionId,
    input_contract_id: workflowMode === "light_web_game" ? "LightWebGameTaskInput" : "WorkspacePatchTaskInput",
    output_contract_id: workflowMode === "light_web_game" ? "LightWebGameResult" : "AssistantFinalAnswer",
    safety_policy: safetyPolicy,
    task_structure: {
      runtime_lane_hint: workflowMode === "light_web_game" ? "game_delivery" : "workspace_patch",
      memory_scope_hint: "conversation_read_write",
      trigger_signals: workflowMode === "light_web_game" ? ["小游戏", "web game", "snake", "canvas game"] : ["修复", "补丁", "patch", "修改代码"],
      notes: workflowMode === "light_web_game"
        ? "默认由主 Agent 承接，目标是交付可运行、可操作、可验证的轻量网页小游戏。"
        : "默认由主 Agent 承接，目标是在明确边界内完成结构清晰、可验证的代码补丁。",
      workspace_target_hint: workflowMode === "light_web_game" ? "frontend/public or standalone html file" : "explicit target root required",
      delivery_expectation: workflowMode === "light_web_game" ? "playable_web_game" : "scoped_workspace_patch"
    },
    enabled: true,
    metadata: { managed_by: "task_system_console" },
    trigger_signals_text: workflowMode === "light_web_game" ? "小游戏\nweb game\nsnake\ncanvas game" : "修复\n补丁\npatch\n修改代码",
    notes: workflowMode === "light_web_game"
      ? "默认由主 Agent 承接，目标是交付可运行、可操作、可验证的轻量网页小游戏。"
      : "默认由主 Agent 承接，目标是在明确边界内完成结构清晰、可验证的代码补丁。",
    safety_write_roots_text: listText(safetyPolicy.write_roots),
    safety_forbidden_paths_text: listText(safetyPolicy.forbidden_paths)
  };
}

function specificTaskDraftFrom(task: TaskAssignment): SpecificTaskDraft {
  const safetyPolicy = normalizeSafetyPolicy(task.safety_policy ?? {});
  return {
    ...task,
    safety_policy: safetyPolicy,
    task_structure: task.task_structure ?? {},
    metadata: task.metadata ?? {},
    trigger_signals_text: listText((task.task_structure?.trigger_signals as string[] | undefined) ?? []),
    notes: text(task.task_structure?.notes, ""),
    safety_write_roots_text: listText(safetyPolicy.write_roots),
    safety_forbidden_paths_text: listText(safetyPolicy.forbidden_paths)
  };
}

function workflowDraftFrom(workflow: TaskWorkflowRecord): WorkflowDraft {
  return {
    ...workflow,
    metadata: workflow.metadata ?? {},
    steps: workflow.steps ?? [],
    visible_skill_ids: workflow.visible_skill_ids ?? [],
    stop_conditions: workflow.stop_conditions ?? [],
    required_evidence_refs: workflow.required_evidence_refs ?? [],
    steps_text: stepsToText(workflow.steps ?? []),
    visible_skill_ids_text: listText(workflow.visible_skill_ids),
    stop_conditions_text: listText(workflow.stop_conditions),
    required_evidence_refs_text: listText(workflow.required_evidence_refs),
    compatible_projection_ids_text: listText(workflow.compatible_projection_ids)
  };
}

function emptyWorkflow(): WorkflowDraft {
  return workflowDraftFrom({
    workflow_id: "workflow.dev.light_web_game",
    title: "轻量网页小游戏工作流",
    task_mode: "light_web_game",
    compatible_projection_ids: [],
    visible_skill_ids: ["skill.implementation", "skill.review"],
    steps: [
      { step_id: "clarify_game_goal", title: "收束玩法目标与交互边界" },
      { step_id: "inspect_workspace", title: "检查工作区与落点文件" },
      { step_id: "design_runtime_shape", title: "定义状态、循环与渲染结构" },
      { step_id: "build_game_artifact", title: "实现游戏文件与交互逻辑" },
      { step_id: "verify_playability", title: "验证可启动、可操作、可结束" },
      { step_id: "finalize_report", title: "输出真实结果与限制" }
    ],
    input_boundary: "Game goal, explicit workspace target, optional style hints, optional asset refs.",
    output_boundary: "Playable web game artifact refs plus validation state and known limitations.",
    stop_conditions: ["game_artifact_created", "playability_checked", "result_reported"],
    required_evidence_refs: ["workspace_path", "artifact_refs"],
    output_contract_id: "LightWebGameResult",
    prompt: "优先交付轻量、可运行、可验证的网页小游戏。先收束玩法，再决定结构；如果无法完整验证，必须明确说明未验证部分。",
    enabled: true,
    metadata: { managed_by: "task_system_console", task_resource: "light_web_game" }
  });
}

function emptyWorkflowWithId(workflowId: string): WorkflowDraft {
  return workflowDraftFrom({
    ...workflowPayload(emptyWorkflow()),
    workflow_id: workflowId,
    title: "新执行流程",
    task_mode: "bounded_patch",
    metadata: { managed_by: "task_system_console", display_number: displayNumberFromId(workflowId, "流程") }
  });
}

function workflowPayload(draft: WorkflowDraft): TaskWorkflowRecord {
  return {
    workflow_id: draft.workflow_id,
    title: draft.title,
    task_mode: draft.task_mode,
    compatible_projection_ids: splitList(draft.compatible_projection_ids_text),
    visible_skill_ids: splitList(draft.visible_skill_ids_text),
    steps: parseSteps(draft.steps_text),
    input_boundary: draft.input_boundary,
    output_boundary: draft.output_boundary,
    stop_conditions: splitList(draft.stop_conditions_text),
    required_evidence_refs: splitList(draft.required_evidence_refs_text),
    output_contract_id: draft.output_contract_id,
    prompt: draft.prompt,
    enabled: draft.enabled,
    metadata: { ...(draft.metadata ?? {}), managed_by: "task_system_console" }
  };
}

function coordinationDraftFrom(task: CoordinationTask): CoordinationDraft {
  return {
    ...task,
    metadata: task.metadata ?? {},
    participant_agent_ids_text: listText(task.participant_agent_ids),
    stop_conditions_text: listText(task.stop_conditions)
  };
}

function emptyCoordination(topologyId = ""): CoordinationDraft {
  return {
    coordination_task_id: "coord.custom.new_task",
    title: "新协调任务",
    coordination_mode: "review_merge",
    coordinator_agent_id: "agent:0",
    participant_agent_ids: [],
    participant_agent_ids_text: "",
    topology_template_id: topologyId,
    shared_context_policy: "explicit_refs_only",
    memory_sharing_policy: "isolated_by_default",
    handoff_policy: "filtered_handoff",
    conflict_resolution_policy: "coordinator_review",
    output_merge_policy: "coordinator_final_merge",
    stop_conditions: ["coordinator_final_merge"],
    stop_conditions_text: "coordinator_final_merge",
    enabled: false,
    metadata: { managed_by: "task_system_console" }
  };
}

function emptyCoordinationWithId(coordinationTaskId: string, topologyId = ""): CoordinationDraft {
  return {
    ...emptyCoordination(topologyId),
    coordination_task_id: coordinationTaskId,
    metadata: {
      managed_by: "task_system_console",
      display_number: displayNumberFromId(coordinationTaskId, "协作")
    }
  };
}

function topologyDraftFrom(template: TopologyTemplate): TopologyDraft {
  return {
    ...template,
    nodes_text: jsonText(template.nodes),
    edges_text: jsonText(template.edges),
    handoff_rules_text: jsonText(template.handoff_rules)
  };
}

function emptyTopology(): TopologyDraft {
  return topologyDraftFrom({
    template_id: "topology.custom.new_coordination",
    title: "新拓扑模板",
    nodes: [{ node_id: "coordinator", agent_id: "agent:0", lane: "final_integration" }],
    edges: [],
    handoff_rules: [],
    join_policy: "explicit_join",
    failure_policy: "fail_closed",
    terminal_policy: "coordinator_terminal",
    enabled: false
  });
}

function emptyTopologyWithId(templateId: string): TopologyDraft {
  return {
    ...emptyTopology(),
    template_id: templateId,
  };
}

export function TaskSystemView() {
  const [consoleData, setConsoleData] = useState<TaskSystemConsole | null>(null);
  const [projectionCatalog, setProjectionCatalog] = useState<SoulProjectionCatalog | null>(null);
  const [activePage, setActivePage] = useState<TaskPage>("tasks");
  const [taskModeTab, setTaskModeTab] = useState<TaskModeTab>("specific");
  const [taskWorkbenchTab, setTaskWorkbenchTab] = useState<TaskWorkbenchTab>("definition");
  const [selectedCategoryId, setSelectedCategoryId] = useState("main_agent");
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [selectedGeneralId, setSelectedGeneralId] = useState("");
  const [selectedSpecificTaskId, setSelectedSpecificTaskId] = useState("");
  const [selectedCoordinationId, setSelectedCoordinationId] = useState("");
  const [selectedTopologyId, setSelectedTopologyId] = useState("");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [agentDraft, setAgentDraft] = useState<AgentDraft>(emptyAgentDraft());
  const [generalDraft, setGeneralDraft] = useState<GeneralTaskProfile>(emptyGeneralTask());
  const [specificTaskDraft, setSpecificTaskDraft] = useState<SpecificTaskDraft>(emptySpecificTask());
  const [workflowDraft, setWorkflowDraft] = useState<WorkflowDraft>(emptyWorkflow());
  const [coordinationDraft, setCoordinationDraft] = useState<CoordinationDraft>(emptyCoordination());
  const [topologyDraft, setTopologyDraft] = useState<TopologyDraft>(emptyTopology());

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [overview, projections] = await Promise.all([
        getTaskSystemOverview(),
        getSoulProjectionCards()
      ]);
      const payload = overview as TaskSystemConsole;
      setConsoleData(payload);
      setProjectionCatalog(projections);
      const firstCategory = payload.agent_management.categories[0];
      const firstAgent = firstCategory?.agents[0];
      setSelectedCategoryId((current) => current || firstCategory?.category_id || "main_agent");
      setSelectedAgentId((current) => current || firstAgent?.agent_id || "");
      setSelectedGeneralId((current) => current || payload.task_management.general_tasks[0]?.profile_id || "");
      setSelectedSpecificTaskId((current) => current || payload.task_management.specific_tasks[0]?.task_id || "");
      setSelectedCoordinationId((current) => current || payload.coordination_management.coordination_tasks[0]?.coordination_task_id || "");
      setSelectedTopologyId((current) => current || payload.coordination_management.topology_templates[0]?.template_id || "");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "任务系统加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const projections = useMemo(() => projectionCatalog?.cards ?? [], [projectionCatalog]);
  const soulNameById = useMemo(
    () => new Map(projections.map((projection) => [projection.soul_id, projection.soul_name || projection.soul_id])),
    [projections]
  );
  const projectionTitleById = useMemo(
    () => new Map(projections.map((projection) => [projection.projection_id, projection.title || projection.projection_id])),
    [projections]
  );
  const categories = useMemo(() => consoleData?.agent_management.categories ?? [], [consoleData]);
  const taskManagement = consoleData?.task_management;
  const coordinationManagement = consoleData?.coordination_management;
  const workflows = useMemo(() => taskManagement?.workflow_resources ?? [], [taskManagement]);
  const currentCategory = categories.find((item) => item.category_id === selectedCategoryId) ?? categories[0] ?? null;
  const allAgents = categories.flatMap((item) => item.agents);
  const filteredCategories = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return categories;
    return categories
      .map((category) => ({
        ...category,
        agents: category.agents.filter((agent) =>
          [agent.agent_id, agent.agent_name, agent.interface_target, agent.description].join(" ").toLowerCase().includes(normalized)
        )
      }))
      .filter((category) => category.agents.length);
  }, [categories, query]);

  const selectedAgent = allAgents.find((agent) => agent.agent_id === selectedAgentId) ?? null;
  const isDraftWorkerAgent =
    !selectedAgent &&
    selectedCategoryId === "worker_sub_agent" &&
    Boolean(selectedAgentId) &&
    agentDraft.agent_id === selectedAgentId;
  const agentEditorRecord = selectedAgent ?? (isDraftWorkerAgent ? agentDraft : null);
  const agentEditorBuiltin = Boolean(selectedAgent?.builtin);
  const agentEditorCategory = selectedAgent?.agent_category ?? agentDraft.agent_category;
  const agentEditorTaskScopeSummary = selectedAgent
    ? selectedAgent.task_scope.length ? selectedAgent.task_scope.join(" / ") : "未定义"
    : agentDraft.task_scope_text || "未定义";
  const selectedGeneralTask = taskManagement?.general_tasks.find((item) => item.profile_id === selectedGeneralId) ?? taskManagement?.general_tasks[0] ?? null;
  const selectedSpecificTask = taskManagement?.specific_tasks.find((item) => item.task_id === selectedSpecificTaskId)
    ?? (selectedSpecificTaskId ? null : taskManagement?.specific_tasks[0] ?? null);
  const selectedWorkflow = workflows.find((item) => item.workflow_id === (taskModeTab === "general" ? selectedGeneralTask?.default_workflow_id : selectedSpecificTask?.workflow_id)) ?? workflows[0] ?? null;
  const selectedCoordinationTask = coordinationManagement?.coordination_tasks.find((item) => item.coordination_task_id === selectedCoordinationId)
    ?? (selectedCoordinationId ? null : coordinationManagement?.coordination_tasks[0] ?? null);
  const selectedTopology = coordinationManagement?.topology_templates.find((item) => item.template_id === selectedTopologyId)
    ?? (selectedTopologyId ? null : coordinationManagement?.topology_templates[0] ?? null);
  const isSpecificTaskDraft = !selectedSpecificTask && Boolean(selectedSpecificTaskId) && specificTaskDraft.task_id === selectedSpecificTaskId;
  const isCoordinationDraft = !selectedCoordinationTask && Boolean(selectedCoordinationId) && coordinationDraft.coordination_task_id === selectedCoordinationId;
  const isTopologyDraft = !selectedTopology && Boolean(selectedTopologyId) && topologyDraft.template_id === selectedTopologyId;

  useEffect(() => {
    if (selectedAgent) {
      setAgentDraft(agentDraftFrom(selectedAgent));
    }
  }, [selectedAgent]);

  useEffect(() => {
    if (selectedGeneralTask) {
      setGeneralDraft(selectedGeneralTask);
    } else {
      setGeneralDraft(emptyGeneralTask(preferredGeneralWorkflowId(workflows), projections[0]?.projection_id ?? ""));
    }
  }, [selectedGeneralTask, workflows, projections]);

  useEffect(() => {
    if (selectedSpecificTask) {
      setSpecificTaskDraft(specificTaskDraftFrom(selectedSpecificTask));
    } else if (!isSpecificTaskDraft) {
      setSpecificTaskDraft(emptySpecificTask(preferredSpecificWorkflowId(workflows), projections[0]?.projection_id ?? ""));
    }
  }, [isSpecificTaskDraft, selectedSpecificTask, workflows, projections]);

  useEffect(() => {
    if (selectedWorkflow) {
      setWorkflowDraft(workflowDraftFrom(selectedWorkflow));
    } else {
      setWorkflowDraft(emptyWorkflow());
    }
  }, [selectedWorkflow]);

  useEffect(() => {
    if (selectedCoordinationTask) {
      setCoordinationDraft(coordinationDraftFrom(selectedCoordinationTask));
    } else if (!isCoordinationDraft) {
      setCoordinationDraft(emptyCoordination(coordinationManagement?.topology_templates[0]?.template_id ?? ""));
    }
  }, [coordinationManagement?.topology_templates, isCoordinationDraft, selectedCoordinationTask]);

  useEffect(() => {
    if (selectedTopology) {
      setTopologyDraft(topologyDraftFrom(selectedTopology));
    } else if (!isTopologyDraft) {
      setTopologyDraft(emptyTopology());
    }
  }, [isTopologyDraft, selectedTopology]);

  useEffect(() => {
    setTaskWorkbenchTab("definition");
  }, [taskModeTab]);

  async function saveWorkflowAndRefresh() {
    const payload = workflowPayload(workflowDraft);
    const next = await upsertTaskWorkflow(payload.workflow_id, payload);
    const nextWorkflow = next.task_management?.workflow_resources?.find((item) => item.workflow_id === payload.workflow_id) ?? payload;
    setWorkflowDraft(workflowDraftFrom(nextWorkflow));
    setConsoleData(next as TaskSystemConsole);
    return payload;
  }

  async function saveAgent() {
    setSaving("agent");
    setError("");
    try {
      const mainAgent = isMainAgentCategory(agentDraft.agent_category);
      const payload: TaskSystemAgentUpsertPayload = {
        agent_id: agentDraft.agent_id,
        agent_name: agentDraft.agent_name,
        agent_category: agentDraft.agent_category,
        interface_target: agentDraft.interface_target,
        description: agentDraft.description,
        enabled: agentDraft.enabled,
        editable: selectedAgent?.builtin ? true : agentDraft.editable,
        default_soul_id: mainAgent ? "" : agentDraft.default_soul_id,
        default_projection_id: mainAgent ? "" : agentDraft.default_projection_id,
        task_scope: splitList(agentDraft.task_scope_text),
        metadata: { managed_by: "task_system_console" }
      };
      const next = await upsertTaskSystemAgent(agentDraft.agent_id, payload);
      setConsoleData(next as TaskSystemConsole);
      setSelectedCategoryId(agentDraft.agent_category);
      setSelectedAgentId(agentDraft.agent_id);
      setNotice("Agent 已保存。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存 Agent 失败");
    } finally {
      setSaving("");
    }
  }

  async function removeAgent() {
    if (!selectedAgent || selectedAgent.builtin) return;
    setSaving("agent-delete");
    setError("");
    try {
      const next = await deleteTaskSystemAgent(selectedAgent.agent_id);
      const payload = next as TaskSystemConsole;
      setConsoleData(payload);
      const workerCategory = payload.agent_management.categories.find((item) => item.category_id === "worker_sub_agent");
      setSelectedCategoryId("worker_sub_agent");
      setSelectedAgentId(workerCategory?.agents[0]?.agent_id ?? "");
      setNotice("工作子 Agent 已删除。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "删除 Agent 失败");
    } finally {
      setSaving("");
    }
  }

  async function createWorkerAgentDraft() {
    setSaving("agent-create");
    setError("");
    try {
      const nextId = await getNextWorkerAgentId();
      const draft = emptyAgentDraft(nextId.agent_id);
      setAgentDraft(draft);
      setSelectedCategoryId("worker_sub_agent");
      setSelectedAgentId(draft.agent_id);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "创建 Agent 草稿失败");
    } finally {
      setSaving("");
    }
  }

  async function saveGeneralTask() {
    setSaving("general");
    setError("");
    try {
      const workflow = await saveWorkflowAndRefresh();
      const next = await upsertTaskSystemGeneralProfile(generalDraft.profile_id, {
        ...generalDraft,
        default_workflow_id: workflow.workflow_id,
        metadata: { ...(generalDraft.metadata ?? {}), managed_by: "task_system_console" }
      });
      setConsoleData(next as TaskSystemConsole);
      setSelectedGeneralId(generalDraft.profile_id);
      setNotice("通用任务已保存。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存通用任务失败");
    } finally {
      setSaving("");
    }
  }

  async function saveSpecificTask() {
    setSaving("specific");
    setError("");
    try {
      const workflow = await saveWorkflowAndRefresh();
      const next = await upsertTaskSystemAssignment(specificTaskDraft.task_id, {
        task_id: specificTaskDraft.task_id,
        task_title: specificTaskDraft.task_title,
        task_kind: specificTaskDraft.task_kind,
        task_family: specificTaskDraft.task_family,
        task_mode: specificTaskDraft.task_mode,
        flow_id: specificTaskDraft.flow_id,
        default_agent_id: specificTaskDraft.default_agent_id,
        participant_agent_ids: specificTaskDraft.participant_agent_ids,
        workflow_id: workflow.workflow_id,
        workflow_file_ref: `workflow:${workflow.workflow_id}`,
        projection_id: specificTaskDraft.projection_id,
        input_contract_id: specificTaskDraft.input_contract_id,
        output_contract_id: specificTaskDraft.output_contract_id,
        safety_policy: {
          ...normalizeSafetyPolicy(specificTaskDraft.safety_policy),
          write_roots: splitList(specificTaskDraft.safety_write_roots_text),
          forbidden_paths: splitList(specificTaskDraft.safety_forbidden_paths_text)
        },
        task_structure: {
          ...specificTaskDraft.task_structure,
          trigger_signals: splitList(specificTaskDraft.trigger_signals_text),
          notes: specificTaskDraft.notes
        },
        enabled: specificTaskDraft.enabled,
        metadata: { ...(specificTaskDraft.metadata ?? {}), managed_by: "task_system_console" }
      });
      setConsoleData(next as TaskSystemConsole);
      setSelectedSpecificTaskId(specificTaskDraft.task_id);
      setNotice("特定任务已保存。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存特定任务失败");
    } finally {
      setSaving("");
    }
  }

  async function saveWorkflowOnly() {
    setSaving("workflow");
    setError("");
    try {
      const workflow = await saveWorkflowAndRefresh();
      if (taskModeTab === "general") {
        setGeneralDraft((value) => ({
          ...value,
          default_workflow_id: workflow.workflow_id
        }));
      } else {
        setSpecificTaskDraft((value) => ({
          ...value,
          workflow_id: workflow.workflow_id,
          workflow_file_ref: `workflow:${workflow.workflow_id}`
        }));
      }
      setNotice("执行流程已保存，并已绑定到当前任务草稿。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存执行流程失败");
    } finally {
      setSaving("");
    }
  }

  async function createSpecificTaskDraft() {
    setSaving("task-create");
    setError("");
    try {
      const nextIds = await getTaskSystemNextIds();
      const workflowId = preferredSpecificWorkflowId(workflows);
      const workflow = workflows.find((item) => item.workflow_id === workflowId);
      const workflowMode = workflow?.task_mode || "bounded_patch";
      const workflowFamily = TASK_MODE_OPTIONS.find((item) => item.value === workflowMode)?.family || "development";
      const draft = emptySpecificTask(workflowId, projections[0]?.projection_id ?? "");
      const nextDraft: SpecificTaskDraft = {
        ...draft,
        task_id: nextIds.task_id,
        flow_id: nextIds.flow_id,
        workflow_id: workflowId,
        workflow_file_ref: workflowId ? `workflow:${workflowId}` : "",
        task_mode: workflowMode,
        task_family: workflowFamily,
        metadata: {
          ...(draft.metadata ?? {}),
          managed_by: "task_system_console",
          display_number: nextIds.display_numbers.task,
          flow_display_number: nextIds.display_numbers.flow
        }
      };
      setSelectedSpecificTaskId(nextDraft.task_id);
      setSpecificTaskDraft(nextDraft);
      setTaskWorkbenchTab("definition");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "创建任务草稿失败");
    } finally {
      setSaving("");
    }
  }

  async function createWorkflowDraft() {
    setSaving("workflow-create");
    setError("");
    try {
      const nextIds = await getTaskSystemNextIds();
      setWorkflowDraft(emptyWorkflowWithId(nextIds.workflow_id));
      setTaskWorkbenchTab("method");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "创建执行流程草稿失败");
    } finally {
      setSaving("");
    }
  }

  async function createCoordinationTaskDraft() {
    setSaving("coordination-create");
    setError("");
    try {
      const nextIds = await getTaskSystemNextIds();
      const draft = emptyCoordinationWithId(nextIds.coordination_task_id, selectedTopologyId || coordinationManagement?.topology_templates[0]?.template_id || "");
      setSelectedCoordinationId(draft.coordination_task_id);
      setCoordinationDraft(draft);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "创建协调任务草稿失败");
    } finally {
      setSaving("");
    }
  }

  async function createTopologyDraft() {
    setSaving("topology-create");
    setError("");
    try {
      const nextIds = await getTaskSystemNextIds();
      const draft = emptyTopologyWithId(nextIds.topology_template_id);
      setSelectedTopologyId(draft.template_id);
      setTopologyDraft(draft);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "创建拓扑模板草稿失败");
    } finally {
      setSaving("");
    }
  }

  const taskList = taskModeTab === "general" ? taskManagement?.general_tasks ?? [] : taskManagement?.specific_tasks ?? [];
  const currentTaskId = taskModeTab === "general" ? generalDraft.profile_id : specificTaskDraft.task_id;
  const currentTaskTitle = taskModeTab === "general" ? generalDraft.title : specificTaskDraft.task_title;
  const currentTaskAgentId = taskModeTab === "general" ? generalDraft.default_agent_id : specificTaskDraft.default_agent_id;
  const currentTaskWorkflowId = taskModeTab === "general" ? generalDraft.default_workflow_id : specificTaskDraft.workflow_id;
  const currentTaskProjectionId = taskModeTab === "general" ? generalDraft.default_projection_id : specificTaskDraft.projection_id;
  const currentTaskInputContract = taskModeTab === "general" ? generalDraft.input_contract_id : specificTaskDraft.input_contract_id;
  const currentTaskOutputContract = taskModeTab === "general" ? generalDraft.output_contract_id : specificTaskDraft.output_contract_id;
  const currentTaskFlowId = taskModeTab === "general"
    ? text(generalDraft.metadata?.flow_id, "flow.general.main_conversation")
    : specificTaskDraft.flow_id;
  const currentTaskAgentName = allAgents.find((agent) => agent.agent_id === currentTaskAgentId)?.agent_name ?? currentTaskAgentId;
  const currentTaskProjectionTitle = projectionTitleById.get(currentTaskProjectionId) || currentTaskProjectionId || "未绑定";
  const currentWorkflowTitle = workflows.find((workflow) => workflow.workflow_id === currentTaskWorkflowId)?.title ?? (currentTaskWorkflowId || "未绑定");
  const specificTaskStructure = specificTaskDraft.task_structure ?? {};
  const currentAdoptionMode = taskModeTab === "general"
    ? "main_session_default"
    : text(specificTaskStructure.adoption_mode, specificTaskDraft.participant_agent_ids.length ? "coordination_candidate" : "adopt_existing");
  const currentAllowWorkerSpawn = taskModeTab === "general"
    ? false
    : Boolean(specificTaskStructure.allow_worker_agent_spawn);
  const currentAgentAdoptionPlanRef = taskModeTab === "general"
    ? text(generalDraft.metadata?.agent_adoption_plan_ref, `plan.${generalDraft.profile_id || "general.main"}`)
    : text(specificTaskStructure.agent_adoption_plan_ref, `plan.${specificTaskDraft.task_id || "task.pending"}`);
  const currentMemoryRequestProfileRef = taskModeTab === "general"
    ? text(generalDraft.metadata?.memory_request_profile_ref, "memory.general.main_session")
    : text(specificTaskStructure.memory_request_profile_ref, `memory.${specificTaskDraft.task_id || "task.pending"}`);
  const currentMemoryLayers = taskModeTab === "general"
    ? ["session_context", "conversation_short_term"]
    : Array.isArray(specificTaskStructure.memory_layer_refs)
      ? specificTaskStructure.memory_layer_refs.map((item) => String(item)).filter(Boolean)
      : [];
  const currentMemoryTopics = taskModeTab === "general"
    ? []
    : Array.isArray(specificTaskStructure.memory_topic_hints)
      ? specificTaskStructure.memory_topic_hints.map((item) => String(item)).filter(Boolean)
      : [];
  const currentRuntimeLane = taskModeTab === "general"
    ? text(generalDraft.metadata?.runtime_lane_hint, "main_conversation")
    : text(specificTaskStructure.runtime_lane_hint, "default_lane");
  const currentExecutionMode = taskModeTab === "general"
    ? "single_agent"
    : currentAdoptionMode === "coordination_candidate" || specificTaskDraft.participant_agent_ids.length
      ? "coordination_candidate"
      : currentAllowWorkerSpawn
        ? "subagent_allowed"
        : "single_agent";
  const currentSafetySummary = taskModeTab === "general"
    ? "S0_readonly / none / 主会话默认只读"
    : formatSafetySummary(specificTaskDraft.safety_policy ?? {});
  const currentExecutionLabel = currentExecutionMode === "coordination_candidate"
    ? "协调候选"
    : currentExecutionMode === "subagent_allowed"
      ? "允许子 Agent"
      : "单 Agent";
  const currentAssemblyReadiness = [
    { label: "任务对象", ready: Boolean(currentTaskId) },
    { label: "执行主体", ready: Boolean(currentTaskAgentId) },
    { label: "执行流程", ready: Boolean(currentTaskWorkflowId) },
    { label: "表达风格", ready: Boolean(currentTaskProjectionId) },
    { label: "流程契约", ready: Boolean(currentTaskFlowId) },
    { label: "执行计划", ready: Boolean(currentAgentAdoptionPlanRef) },
    { label: "记忆请求", ready: Boolean(currentMemoryRequestProfileRef) },
    { label: "安全包络", ready: Boolean(currentSafetySummary) }
  ];
  const currentAssemblyMissing = currentAssemblyReadiness
    .filter((item) => !item.ready)
    .map((item) => item.label);
  const currentAssemblyActionHints = [
    !currentTaskAgentId ? "先绑定默认承接 Agent，避免 runtime 临场猜执行主体。" : "",
    !currentTaskWorkflowId ? "补齐执行流程，让任务方法留在正式资源里，而不是靠临场自由发挥。" : "",
    !currentTaskProjectionId ? "补齐任务投影，让执行姿态和表达边界有正式落点。" : "",
    !currentTaskFlowId ? "补齐 flow contract，让 runtime 按正式任务契约推进状态。" : "",
    taskModeTab === "specific" && !currentAllowWorkerSpawn && currentExecutionMode !== "coordination_candidate"
      ? "当前任务会按单 Agent 执行；如果确实需要分工，再显式开放 adoption plan。"
      : "",
    taskModeTab === "specific" && currentExecutionMode === "coordination_candidate"
      ? "当前已经具备协调候选结构，下一步重点检查参与主体、拓扑模板和合并策略。"
      : ""
  ].filter(Boolean).slice(0, 3);
  const selectedCoordinationParticipantNames = coordinationDraft.participant_agent_ids_text
    ? splitList(coordinationDraft.participant_agent_ids_text).map((agentId) => allAgents.find((agent) => agent.agent_id === agentId)?.agent_name || agentId)
    : [];
  const selectedTopologyNodeCount = Array.isArray(selectedTopology?.nodes) ? selectedTopology?.nodes.length : 0;
  const selectedTopologyEdgeCount = Array.isArray(selectedTopology?.edges) ? selectedTopology?.edges.length : 0;

  async function saveCoordination() {
    setSaving("coordination");
    setError("");
    try {
      const next = await upsertTaskSystemCoordinationTask(coordinationDraft.coordination_task_id, {
        ...coordinationDraft,
        participant_agent_ids: splitList(coordinationDraft.participant_agent_ids_text),
        stop_conditions: splitList(coordinationDraft.stop_conditions_text),
        metadata: { ...(coordinationDraft.metadata ?? {}), managed_by: "task_system_console" }
      });
      setConsoleData(next as TaskSystemConsole);
      setSelectedCoordinationId(coordinationDraft.coordination_task_id);
      setNotice("协调任务已保存。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存协调任务失败");
    } finally {
      setSaving("");
    }
  }

  async function saveTopology() {
    setSaving("topology");
    setError("");
    try {
      const next = await upsertTaskSystemTopologyTemplate(topologyDraft.template_id, {
        template_id: topologyDraft.template_id,
        title: topologyDraft.title,
        nodes: parseJsonList(topologyDraft.nodes_text),
        edges: parseJsonList(topologyDraft.edges_text),
        handoff_rules: parseJsonList(topologyDraft.handoff_rules_text),
        join_policy: topologyDraft.join_policy,
        failure_policy: topologyDraft.failure_policy,
        terminal_policy: topologyDraft.terminal_policy,
        enabled: topologyDraft.enabled
      });
      setConsoleData(next as TaskSystemConsole);
      setSelectedTopologyId(topologyDraft.template_id);
      setNotice("拓扑模板已保存。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存拓扑模板失败");
    } finally {
      setSaving("");
    }
  }

  return (
    <div className="workspace-view task-system-view">
      <header className="workspace-view__header">
        <div>
          <p className="workspace-view__eyebrow">任务执行装配工作台</p>
          <h2 className="workspace-view__title">任务系统</h2>
          <p className="workspace-view__subtitle">围绕任务管理、执行采用、方法边界与协调结构建立正式装配入口。</p>
        </div>
      </header>

      {error ? <div className="workspace-alert workspace-alert--danger">{error}</div> : null}
      {notice ? <div className="workspace-alert">{notice}</div> : null}
      {loading ? <div className="workspace-alert"><Loader2 className="spin" size={16} /> 正在加载任务系统...</div> : null}

      <nav className="task-system-switcher" aria-label="任务系统模块">
        {[
          { key: "tasks", label: "任务管理", icon: Workflow },
          { key: "coordination", label: "协调任务", icon: GitBranch },
          { key: "agents", label: "Agent 资源", icon: Bot }
        ].map((item) => {
          const Icon = item.icon;
          return (
            <button
              className={activePage === item.key ? "task-system-switcher__item task-system-switcher__item--active" : "task-system-switcher__item"}
              key={item.key}
              onClick={() => setActivePage(item.key as TaskPage)}
              type="button"
            >
              <Icon size={15} />
              {item.label}
            </button>
          );
        })}
      </nav>

      {activePage === "tasks" ? (
        <section className="task-management-stage">
          <aside className="task-management-directory">
            <div className="task-management-directory__head">
              <span>任务目录</span>
              <strong>任务管理</strong>
            </div>

            <nav className="task-management-mode-switch" aria-label="任务类型">
              <button className={taskModeTab === "specific" ? "task-management-mode-switch__item task-management-mode-switch__item--active" : "task-management-mode-switch__item"} onClick={() => setTaskModeTab("specific")} type="button">
                特定任务
                <span>{taskManagement?.specific_tasks.length ?? 0}</span>
              </button>
              <button className={taskModeTab === "general" ? "task-management-mode-switch__item task-management-mode-switch__item--active" : "task-management-mode-switch__item"} onClick={() => setTaskModeTab("general")} type="button">
                通用任务
                <span>{taskManagement?.general_tasks.length ?? 0}</span>
              </button>
            </nav>

            {taskModeTab === "general" ? (
              <div className="task-system-task-rail__stack">
                <button className="task-system-select-card task-system-select-card--active" type="button">
                  <Bot size={16} />
                  <strong>{generalDraft.title}</strong>
                  <Badge value={generalDraft.enabled ? "enabled" : "disabled"} />
                  <span>主会话默认承接配置</span>
                </button>
                <div className="task-system-task-note">
                  <span>默认承接链路</span>
                  <strong>{"主会话 -> 通用任务 -> 主 Agent -> 如需再进入特定任务"}</strong>
                </div>
              </div>
            ) : (
              <div className="task-system-task-rail__stack">
                <div className="task-system-toolbar">
                  <strong className="task-system-inline-title">特定任务列表</strong>
                  <button className="action-button action-button--ghost" disabled={saving === "task-create"} onClick={() => void createSpecificTaskDraft()} type="button">
                    {saving === "task-create" ? <Loader2 className="spin" size={14} /> : <Plus size={14} />}
                    新任务
                  </button>
                </div>
                <div className="task-system-flow-tabs">
                  {taskList.map((item) => {
                    const task = item as TaskAssignment;
                    const active = selectedSpecificTaskId === task.task_id;
                    const taskAgentName = allAgents.find((agent) => agent.agent_id === task.default_agent_id)?.agent_name ?? task.default_agent_id;
                    const taskWorkflowTitle = workflows.find((workflow) => workflow.workflow_id === task.workflow_id)?.title
                      ?? task.workflow_id
                      ?? "未绑定执行流程";
                    return (
                      <button className={active ? "task-system-flow-tab task-system-flow-tab--active" : "task-system-flow-tab"} key={task.task_id} onClick={() => setSelectedSpecificTaskId(task.task_id)} type="button">
                        <Workflow size={14} />
                        <span>{task.task_title}</span>
                        <Badge value={task.enabled ? "enabled" : "disabled"} />
                        <small>{String(task.metadata?.display_number || displayNumberFromId(task.task_id, "任务"))} · {labelTaskMode(text(task.task_mode, ""))} · {taskAgentName || "未绑定执行主体"} · {taskWorkflowTitle} · {text(task.safety_policy?.safety_class, "S0_readonly")}</small>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </aside>

          <main className="task-management-workbench">
            <header className="task-management-titlebar">
              <div>
                <span>{taskModeTab === "general" ? "通用任务" : "特定任务"}</span>
                <h3>{currentTaskTitle || "未命名任务"}</h3>
                <p>{taskModeTab === "general" ? "主会话默认承接任务" : labelExecutionMode(currentExecutionMode)}</p>
              </div>
              <div className="task-system-inline-actions">
                <button className="action-button action-button--ghost" disabled={saving === "workflow"} onClick={() => void saveWorkflowOnly()} type="button">
                  {saving === "workflow" ? <Loader2 className="spin" size={14} /> : <Layers3 size={14} />}
                  保存流程
                </button>
                <button className="action-button action-button--primary" disabled={Boolean(saving) && saving !== "workflow"} onClick={() => taskModeTab === "general" ? void saveGeneralTask() : void saveSpecificTask()} type="button">
                  {saving === "general" || saving === "specific" ? <Loader2 className="spin" size={14} /> : <Save size={14} />}
                  保存任务
                </button>
              </div>
            </header>

            <div className="task-management-status-row">
              <TaskSummaryCard title="执行主体" value={currentTaskAgentName || "未指定"} detail={taskModeTab === "general" ? "主会话默认承接" : "负责执行该任务"} />
              <TaskSummaryCard title="执行流程" value={currentWorkflowTitle} detail={taskModeTab === "general" ? "系统流程已绑定" : "当前任务采用的标准流程"} />
              <TaskSummaryCard title="表达风格" value={currentTaskProjectionTitle} detail={currentTaskProjectionId ? "已指定风格与输出姿态" : "暂未指定"} />
              <TaskSummaryCard title="任务编号" value={taskModeTab === "general" ? "通用任务" : String(specificTaskDraft.metadata?.display_number || displayNumberFromId(specificTaskDraft.task_id, "任务"))} detail={taskModeTab === "general" ? "主会话默认入口" : labelTaskFamily(specificTaskDraft.task_family)} />
            </div>

            <nav className="task-management-subnav" aria-label="任务管理子页面">
              {[
                { key: "definition", label: "任务定义", meta: "目标 / 信号" },
                { key: "adoption", label: "执行采用", meta: "执行主体 / 输入输出" },
                { key: "method", label: "方法边界", meta: "执行流程" },
                { key: "safety", label: "安全治理", meta: "权限包络" },
                { key: "assembly", label: "装配预览", meta: "运行前检查" }
              ].map((item) => (
                <button
                  className={taskWorkbenchTab === item.key ? "task-management-subnav__item task-management-subnav__item--active" : "task-management-subnav__item"}
                  key={item.key}
                  onClick={() => setTaskWorkbenchTab(item.key as TaskWorkbenchTab)}
                  type="button"
                >
                  <strong>{item.label}</strong>
                  <span>{item.meta}</span>
                </button>
              ))}
            </nav>

            {taskWorkbenchTab === "definition" ? (
              taskModeTab === "general" ? (
                <div className="task-system-form-section">
                  <div className="task-system-form-grid">
                    <label><span>任务名称</span><input value={generalDraft.title} onChange={(event) => setGeneralDraft((value) => ({ ...value, title: event.target.value }))} /></label>
                    <label><span>启用状态</span><input value={generalDraft.enabled ? "已启用" : "未启用"} readOnly /></label>
                    <label><span>任务编号</span><input value="通用任务" readOnly /></label>
                    <label className="task-system-form-grid__full"><span>对话入口策略</span><input value={generalDraft.conversation_entry_policy} onChange={(event) => setGeneralDraft((value) => ({ ...value, conversation_entry_policy: event.target.value }))} /></label>
                    <label><span>用户输入</span><input value={maskSystemValue(generalDraft.input_contract_id, "普通用户消息")} readOnly /></label>
                    <label><span>系统输出</span><input value={maskSystemValue(generalDraft.output_contract_id, "标准回复结果")} readOnly /></label>
                    <label className="task-system-checkbox"><input checked={generalDraft.enabled} onChange={(event) => setGeneralDraft((value) => ({ ...value, enabled: event.target.checked }))} type="checkbox" />启用通用任务</label>
                  </div>
                </div>
              ) : (
                <div className="task-system-form-section">
                  <div className="task-system-form-grid">
                    <label><span>任务名称</span><input value={specificTaskDraft.task_title} onChange={(event) => setSpecificTaskDraft((value) => ({ ...value, task_title: event.target.value }))} /></label>
                    <label><span>任务类型</span><select value={specificTaskDraft.task_mode} onChange={(event) => {
                      const taskMode = event.target.value;
                      const option = TASK_MODE_OPTIONS.find((item) => item.value === taskMode);
                      setSpecificTaskDraft((value) => ({
                        ...value,
                        task_mode: taskMode,
                        task_family: option?.family ?? value.task_family
                      }));
                    }}>{TASK_MODE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
                    <label><span>任务分组</span><select value={specificTaskDraft.task_family} onChange={(event) => setSpecificTaskDraft((value) => ({ ...value, task_family: event.target.value }))}>{TASK_FAMILY_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
                    <label><span>任务编号</span><input value={String(specificTaskDraft.metadata?.display_number || displayNumberFromId(specificTaskDraft.task_id, "任务"))} readOnly /></label>
                    <label className="task-system-form-grid__full"><span>触发信号</span><textarea value={specificTaskDraft.trigger_signals_text} onChange={(event) => setSpecificTaskDraft((value) => ({ ...value, trigger_signals_text: event.target.value }))} /></label>
                    <label className="task-system-form-grid__full"><span>任务备注</span><textarea value={specificTaskDraft.notes} onChange={(event) => setSpecificTaskDraft((value) => ({ ...value, notes: event.target.value }))} /></label>
                    <label className="task-system-checkbox"><input checked={specificTaskDraft.enabled} onChange={(event) => setSpecificTaskDraft((value) => ({ ...value, enabled: event.target.checked }))} type="checkbox" />启用特定任务</label>
                  </div>
                </div>
              )
            ) : null}

            {taskWorkbenchTab === "adoption" ? (
              <div className="task-system-form-section">
                <div className="task-system-form-grid">
                  <label><span>默认执行主体</span><select value={taskModeTab === "general" ? generalDraft.default_agent_id : specificTaskDraft.default_agent_id} onChange={(event) => taskModeTab === "general" ? setGeneralDraft((value) => ({ ...value, default_agent_id: event.target.value })) : setSpecificTaskDraft((value) => ({ ...value, default_agent_id: event.target.value }))}>{allAgents.map((agent) => <option key={agent.agent_id} value={agent.agent_id}>{agent.agent_name}</option>)}</select></label>
                  <label><span>绑定执行流程</span><select value={currentTaskWorkflowId} onChange={(event) => {
                    const workflowId = event.target.value;
                    const workflow = workflows.find((item) => item.workflow_id === workflowId);
                    if (taskModeTab === "general") {
                      setGeneralDraft((value) => ({
                        ...value,
                        default_workflow_id: workflowId
                      }));
                    } else {
                      setSpecificTaskDraft((value) => ({
                        ...value,
                        task_mode: workflow?.task_mode || value.task_mode,
                        task_family: workflow?.task_mode
                          ? (TASK_MODE_OPTIONS.find((item) => item.value === workflow.task_mode)?.family ?? value.task_family)
                          : value.task_family,
                        workflow_id: workflowId,
                        workflow_file_ref: workflowId ? `workflow:${workflowId}` : ""
                      }));
                    }
                    if (workflow) {
                      setWorkflowDraft(workflowDraftFrom(workflow));
                    }
                  }}>{workflows.map((workflow) => <option key={workflow.workflow_id} value={workflow.workflow_id}>{workflow.title}</option>)}</select></label>
                  <ProjectionPicker label="输出风格" projectionId={currentTaskProjectionId} projections={projections} onChange={(projectionId) => taskModeTab === "general" ? setGeneralDraft((value) => ({ ...value, default_projection_id: projectionId })) : setSpecificTaskDraft((value) => ({ ...value, projection_id: projectionId }))} />
                  <label><span>输入内容</span><input value={maskSystemValue(currentTaskInputContract, "按当前任务要求读取")} readOnly /></label>
                  <label><span>输出结果</span><input value={maskSystemValue(currentTaskOutputContract, "按当前任务结果输出")} readOnly /></label>
                  {taskModeTab === "specific" ? (
                    <>
                      <label><span>执行方式</span><input value={labelExecutionMode(currentExecutionMode)} readOnly /></label>
                      <label><span>记忆调用</span><input value={maskSystemValue(currentMemoryRequestProfileRef, "系统自动管理")} readOnly /></label>
                      <label className="task-system-form-grid__full"><span>协作执行主体</span><textarea value={listText(specificTaskDraft.participant_agent_ids)} onChange={(event) => setSpecificTaskDraft((value) => ({ ...value, participant_agent_ids: splitList(event.target.value) }))} /></label>
                      <label><span>执行通道</span><input value={text(specificTaskStructure.runtime_lane_hint, "") || "系统自动安排"} onChange={(event) => setSpecificTaskDraft((value) => ({ ...value, task_structure: { ...(value.task_structure ?? {}), runtime_lane_hint: event.target.value } }))} /></label>
                      <label className="task-system-checkbox"><input checked={currentAllowWorkerSpawn} onChange={(event) => setSpecificTaskDraft((value) => ({ ...value, task_structure: { ...(value.task_structure ?? {}), allow_worker_agent_spawn: event.target.checked } }))} type="checkbox" />允许系统自动增加工作子 Agent</label>
                    </>
                  ) : null}
                </div>
              </div>
            ) : null}

            {taskWorkbenchTab === "method" ? (
              <div className="task-system-form-section">
                <div className="task-management-section-toolbar">
                  <div className="task-system-inline-copy">
                    <strong>当前执行流程</strong>
                    <span>{workflowDraft.title || "未命名流程"}</span>
                  </div>
                  <button className="action-button action-button--ghost" disabled={saving === "workflow-create"} onClick={() => void createWorkflowDraft()} type="button">
                    {saving === "workflow-create" ? <Loader2 className="spin" size={14} /> : <Plus size={14} />}
                    新执行流程
                  </button>
                </div>
                <WorkflowWorkbench draft={workflowDraft} onChange={setWorkflowDraft} onBindCurrent={() => {
                  if (taskModeTab === "general") {
                    setGeneralDraft((value) => ({
                      ...value,
                      default_workflow_id: workflowDraft.workflow_id
                    }));
                  } else {
                    setSpecificTaskDraft((value) => ({
                      ...value,
                      workflow_id: workflowDraft.workflow_id,
                      workflow_file_ref: workflowDraft.workflow_id ? `workflow:${workflowDraft.workflow_id}` : ""
                    }));
                  }
                }} />
              </div>
            ) : null}

            {taskWorkbenchTab === "safety" ? (
              taskModeTab === "general" ? (
                <div className="task-system-form-section">
                  <div className="task-system-callout">
                    <span>通用任务安全</span>
                    <strong>主会话通用任务默认维持只读入口，不在这里放开写权限。</strong>
                    <p>真正需要执行写入、补丁或产物生成的请求，应该分流到特定任务，再由特定任务声明自己的安全边界。</p>
                  </div>
                </div>
              ) : (
                <div className="task-system-form-section">
                  <div className="task-system-form-grid">
                    <label>
                      <span>安全等级</span>
                      <select
                        value={text((specificTaskDraft.safety_policy ?? {}).safety_class, "S0_readonly")}
                        onChange={(event) => setSpecificTaskDraft((value) => ({
                          ...value,
                          safety_policy: { ...(value.safety_policy ?? {}), safety_class: event.target.value }
                        }))}
                      >
                        {SAFETY_CLASS_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                      </select>
                    </label>
                    <label>
                      <span>写入模式</span>
                      <select
                        value={text((specificTaskDraft.safety_policy ?? {}).write_mode, "none")}
                        onChange={(event) => setSpecificTaskDraft((value) => ({
                          ...value,
                          safety_policy: { ...(value.safety_policy ?? {}), write_mode: event.target.value }
                        }))}
                      >
                        {WRITE_MODE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                      </select>
                    </label>
                    <label>
                      <span>验证模式</span>
                      <input
                        value={text((specificTaskDraft.safety_policy ?? {}).verification_mode, "")}
                        onChange={(event) => setSpecificTaskDraft((value) => ({
                          ...value,
                          safety_policy: { ...(value.safety_policy ?? {}), verification_mode: event.target.value }
                        }))}
                      />
                    </label>
                    <label className="task-system-form-grid__full">
                      <span>允许写入根目录</span>
                      <textarea
                        value={specificTaskDraft.safety_write_roots_text}
                        onChange={(event) => setSpecificTaskDraft((value) => ({ ...value, safety_write_roots_text: event.target.value }))}
                      />
                    </label>
                    <label className="task-system-form-grid__full">
                      <span>禁止路径</span>
                      <textarea
                        value={specificTaskDraft.safety_forbidden_paths_text}
                        onChange={(event) => setSpecificTaskDraft((value) => ({ ...value, safety_forbidden_paths_text: event.target.value }))}
                      />
                    </label>
                  </div>
                </div>
              )
            ) : null}

            {taskWorkbenchTab === "assembly" ? (
              <div className="task-system-form-section task-system-assembly-page">
                <div className="task-system-assembly-hero">
                  <div>
                    <span>装配总览</span>
                    <strong>{currentTaskTitle || "未命名任务"}{" -> "}{currentExecutionMode}</strong>
                    <p>{currentAssemblyMissing.length ? `待补齐：${currentAssemblyMissing.join(" / ")}` : `当前任务已具备 ${currentExecutionLabel} 所需的基础登记信息。`}</p>
                  </div>
                  <div className="task-system-status-strip">
                    {currentAssemblyReadiness.map((item) => (
                      <span className={item.ready ? "task-system-status-pill task-system-status-pill--ready" : "task-system-status-pill task-system-status-pill--pending"} key={item.label}>
                        {item.label} · {item.ready ? "就绪" : "待补齐"}
                      </span>
                    ))}
                  </div>
                </div>

                <div className="task-system-assembly-stack task-system-assembly-stack--wide">
                  <TaskSummaryCard title="执行主体" value={currentTaskAgentName || "未指定"} detail={currentTaskAgentId || "未绑定"} />
                  <TaskSummaryCard title="执行流程" value={currentWorkflowTitle} detail="系统已绑定" />
                  <TaskSummaryCard title="表达风格" value={currentTaskProjectionTitle} detail={currentTaskProjectionId ? "已指定" : "未绑定"} />
                  <TaskSummaryCard title="输入输出" value="系统已装配" detail="当前任务的输入输出由系统管理" />
                </div>

                <div className="task-system-info-grid">
                  <InfoBlock title="执行主体编号" value={currentTaskAgentId || "未绑定"} />
                  <InfoBlock title="流程编号" value={displayNumberFromId(currentTaskWorkflowId, "流程")} />
                  <InfoBlock title="表达风格" value={currentTaskProjectionTitle} />
                  <InfoBlock title="任务编号" value={taskModeTab === "general" ? "通用任务" : displayNumberFromId(currentTaskId, "任务")} />
                  <InfoBlock title="执行计划" value={maskSystemValue(currentAgentAdoptionPlanRef)} />
                  <InfoBlock title="记忆请求" value={maskSystemValue(currentMemoryRequestProfileRef)} />
                  <InfoBlock title="执行通道" value={currentRuntimeLane} />
                  <InfoBlock title="执行方式" value={labelExecutionMode(currentExecutionMode)} />
                </div>

                <div className="task-system-binding-grid">
                  <article className="task-system-binding-card">
                    <span>执行采用计划</span>
                    <strong>{maskSystemValue(currentAgentAdoptionPlanRef, "系统已生成")}</strong>
                    <p>执行方式：{labelExecutionMode(currentExecutionMode)}；工作子 Agent：{currentAllowWorkerSpawn ? "允许自动增加" : "不自动增加"}。</p>
                  </article>
                  <article className="task-system-binding-card">
                    <span>记忆调用策略</span>
                    <strong>{maskSystemValue(currentMemoryRequestProfileRef, "系统已生成")}</strong>
                    <p>memory layers：{currentMemoryLayers.length ? currentMemoryLayers.join(" / ") : "未显式声明"}；topics：{currentMemoryTopics.length ? currentMemoryTopics.join(" / ") : "未补充主题提示"}。</p>
                  </article>
                  <article className="task-system-binding-card">
                    <span>安全包络</span>
                    <strong>{currentSafetySummary}</strong>
                    <p>执行通道：{currentRuntimeLane}；输出结果：系统自动管理。</p>
                  </article>
                  <article className="task-system-binding-card">
                    <span>输入输出边界</span>
                    <strong>系统已装配</strong>
                    <p>输入、输出和流程约束已经由当前任务自动收束，普通使用者无需手动处理内部契约。</p>
                  </article>
                </div>

                <div className="task-system-callout">
                  <span>下一步建议</span>
                  <strong>{currentAssemblyActionHints[0] || "当前页面已具备继续验收的基础形态，可转向运行实测。"}</strong>
                  <div className="task-system-next-steps">
                    {currentAssemblyActionHints.length ? currentAssemblyActionHints.map((hint) => (
                      <p key={hint}>{hint}</p>
                    )) : <p>下一步可以进入小游戏单 Agent 实测或小说协作多 Agent 实测，检查前端预览、API 装配和 runtime trace 是否一致。</p>}
                  </div>
                </div>
              </div>
            ) : null}
          </main>
        </section>
      ) : null}

      {activePage === "coordination" ? (
        <section className="task-system-control-grid">
          <aside className="task-system-control-panel">
            <PanelHead title="协调任务" description="登记需要多个 Agent 协同完成的任务实例。" action={<button className="action-button action-button--ghost" disabled={saving === "coordination-create"} onClick={() => void createCoordinationTaskDraft()} type="button">{saving === "coordination-create" ? <Loader2 className="spin" size={14} /> : <Plus size={14} />}新协调任务</button>} />
            <div className="task-system-flow-tabs">
              {(coordinationManagement?.coordination_tasks ?? []).map((task) => (
                <button className={selectedCoordinationId === task.coordination_task_id ? "task-system-flow-tab task-system-flow-tab--active" : "task-system-flow-tab"} key={task.coordination_task_id} onClick={() => setSelectedCoordinationId(task.coordination_task_id)} type="button">
                  <GitBranch size={14} />
                  <span>{task.title}</span>
                  <Badge value={task.enabled ? "enabled" : "disabled"} />
                  <small>{String(task.metadata?.display_number || displayNumberFromId(task.coordination_task_id, "协作"))} / {task.coordination_mode} / {displayNumberFromId(task.topology_template_id, "拓扑")}</small>
                </button>
              ))}
            </div>
          </aside>

          <main className="task-system-control-panel">
            <PanelHead title="协调任务管理" description="定义主协调者、参与主体、拓扑模板、通信与交接、冲突收敛和终止条件。" action={<button className="action-button action-button--primary" disabled={saving === "coordination"} onClick={() => void saveCoordination()} type="button"><Save size={14} />保存协调任务</button>} />
            <div className="task-system-binding-grid">
              <article className="task-system-binding-card">
                <span>协调主体</span>
                <strong>{allAgents.find((agent) => agent.agent_id === coordinationDraft.coordinator_agent_id)?.agent_name || coordinationDraft.coordinator_agent_id || "未指定"}</strong>
                <p>主协调者负责读取任务拓扑、按需触发参与主体、汇总交接结果，并形成最终合并结果。</p>
              </article>
              <article className="task-system-binding-card">
                <span>拓扑与协议</span>
                <strong>{coordinationDraft.topology_template_id || "未绑定拓扑"}</strong>
                <p>当前收敛策略：{coordinationDraft.output_merge_policy || "未定义"}；handoff：{coordinationDraft.handoff_policy || "未定义"}。</p>
              </article>
            </div>
            <div className="task-system-form-grid">
              <label><span>协作编号</span><input value={String(coordinationDraft.metadata?.display_number || displayNumberFromId(coordinationDraft.coordination_task_id, "协作"))} readOnly /></label>
              <label><span>标题</span><input value={coordinationDraft.title} onChange={(event) => setCoordinationDraft((value) => ({ ...value, title: event.target.value }))} /></label>
              <label><span>协调模式</span><input value={coordinationDraft.coordination_mode} onChange={(event) => setCoordinationDraft((value) => ({ ...value, coordination_mode: event.target.value }))} /></label>
              <label><span>协调 Agent</span><select value={coordinationDraft.coordinator_agent_id} onChange={(event) => setCoordinationDraft((value) => ({ ...value, coordinator_agent_id: event.target.value }))}>{allAgents.map((agent) => <option key={agent.agent_id} value={agent.agent_id}>{agent.agent_name}</option>)}</select></label>
              <label><span>拓扑模板</span><select value={coordinationDraft.topology_template_id} onChange={(event) => setCoordinationDraft((value) => ({ ...value, topology_template_id: event.target.value }))}>{(coordinationManagement?.topology_templates ?? []).map((template) => <option key={template.template_id} value={template.template_id}>{template.title}</option>)}</select></label>
              <label><span>上下文共享策略</span><input value={coordinationDraft.shared_context_policy} onChange={(event) => setCoordinationDraft((value) => ({ ...value, shared_context_policy: event.target.value }))} /></label>
              <label><span>记忆共享策略</span><input value={coordinationDraft.memory_sharing_policy} onChange={(event) => setCoordinationDraft((value) => ({ ...value, memory_sharing_policy: event.target.value }))} /></label>
              <label><span>交接策略</span><input value={coordinationDraft.handoff_policy} onChange={(event) => setCoordinationDraft((value) => ({ ...value, handoff_policy: event.target.value }))} /></label>
              <label><span>冲突收敛策略</span><input value={coordinationDraft.conflict_resolution_policy} onChange={(event) => setCoordinationDraft((value) => ({ ...value, conflict_resolution_policy: event.target.value }))} /></label>
              <label><span>合并策略</span><input value={coordinationDraft.output_merge_policy} onChange={(event) => setCoordinationDraft((value) => ({ ...value, output_merge_policy: event.target.value }))} /></label>
              <label className="task-system-form-grid__full"><span>参与 Agent</span><textarea value={coordinationDraft.participant_agent_ids_text} onChange={(event) => setCoordinationDraft((value) => ({ ...value, participant_agent_ids_text: event.target.value }))} /></label>
              <label className="task-system-form-grid__full"><span>停止条件</span><textarea value={coordinationDraft.stop_conditions_text} onChange={(event) => setCoordinationDraft((value) => ({ ...value, stop_conditions_text: event.target.value }))} /></label>
              <label className="task-system-checkbox"><input checked={coordinationDraft.enabled} onChange={(event) => setCoordinationDraft((value) => ({ ...value, enabled: event.target.checked }))} type="checkbox" />启用协调任务</label>
            </div>
          </main>

          <aside className="task-system-control-panel task-system-assembly-panel">
            <PanelHead title="协调运行预览" description="这里先展示协调运行将如何进入运行链路：谁做主协调者，谁做参与主体，采用什么拓扑、交接和收敛策略。" action={<div className="task-system-inline-actions"><button className="action-button action-button--ghost" disabled={saving === "topology-create"} onClick={() => void createTopologyDraft()} type="button">{saving === "topology-create" ? <Loader2 className="spin" size={14} /> : <Plus size={14} />}新拓扑模板</button><button className="action-button action-button--primary" disabled={saving === "topology"} onClick={() => void saveTopology()} type="button"><Save size={14} />保存拓扑</button></div>} />
            <div className="task-system-assembly-stack">
              <TaskSummaryCard title="主协调者" value={allAgents.find((agent) => agent.agent_id === coordinationDraft.coordinator_agent_id)?.agent_name || "未指定"} detail={coordinationDraft.coordinator_agent_id || "未绑定"} />
              <TaskSummaryCard title="参与主体" value={String(selectedCoordinationParticipantNames.length || 0)} detail={selectedCoordinationParticipantNames.length ? selectedCoordinationParticipantNames.join(" / ") : "未绑定参与主体"} />
              <TaskSummaryCard title="拓扑模板" value={selectedTopology?.title || topologyDraft.title || "未绑定"} detail={displayNumberFromId(coordinationDraft.topology_template_id || topologyDraft.template_id, "拓扑")} />
              <TaskSummaryCard title="合并策略" value={coordinationDraft.output_merge_policy || "未定义"} detail={coordinationDraft.conflict_resolution_policy || "未定义收敛策略"} />
            </div>
            <div className="task-system-binding-grid task-system-binding-grid--single">
              <article className="task-system-binding-card">
                <span>CoordinationRun 装配</span>
                <strong>{coordinationDraft.coordination_mode || "未定义模式"}</strong>
                <p>上下文共享：{coordinationDraft.shared_context_policy || "未定义"}；记忆共享：{coordinationDraft.memory_sharing_policy || "未定义"}。</p>
              </article>
              <article className="task-system-binding-card">
                <span>拓扑预览</span>
                <strong>{selectedTopologyNodeCount} 个节点 / {selectedTopologyEdgeCount} 条连接</strong>
                <p>汇合策略：{topologyDraft.join_policy || "未定义"}；失败策略：{topologyDraft.failure_policy || "未定义"}；终止策略：{topologyDraft.terminal_policy || "未定义"}。</p>
              </article>
            </div>
            <div className="task-system-form-grid">
              <label><span>拓扑编号</span><input value={displayNumberFromId(topologyDraft.template_id, "拓扑")} readOnly /></label>
              <label><span>标题</span><input value={topologyDraft.title} onChange={(event) => setTopologyDraft((value) => ({ ...value, title: event.target.value }))} /></label>
              <label><span>汇合策略</span><input value={topologyDraft.join_policy} onChange={(event) => setTopologyDraft((value) => ({ ...value, join_policy: event.target.value }))} /></label>
              <label><span>失败策略</span><input value={topologyDraft.failure_policy} onChange={(event) => setTopologyDraft((value) => ({ ...value, failure_policy: event.target.value }))} /></label>
              <label><span>终止策略</span><input value={topologyDraft.terminal_policy} onChange={(event) => setTopologyDraft((value) => ({ ...value, terminal_policy: event.target.value }))} /></label>
              <label className="task-system-form-grid__full"><span>节点结构</span><textarea value={topologyDraft.nodes_text} onChange={(event) => setTopologyDraft((value) => ({ ...value, nodes_text: event.target.value }))} /></label>
              <label className="task-system-form-grid__full"><span>连接结构</span><textarea value={topologyDraft.edges_text} onChange={(event) => setTopologyDraft((value) => ({ ...value, edges_text: event.target.value }))} /></label>
              <label className="task-system-form-grid__full"><span>交接规则</span><textarea value={topologyDraft.handoff_rules_text} onChange={(event) => setTopologyDraft((value) => ({ ...value, handoff_rules_text: event.target.value }))} /></label>
              <label className="task-system-checkbox"><input checked={topologyDraft.enabled} onChange={(event) => setTopologyDraft((value) => ({ ...value, enabled: event.target.checked }))} type="checkbox" />启用拓扑模板</label>
            </div>
          </aside>
        </section>
      ) : null}

      {activePage === "agents" ? (
        <section className="task-system-control-grid task-system-control-grid--two task-system-control-grid--agents">
          <aside className="task-system-control-panel">
            <PanelHead title="Agent 资源" description="任务系统把 Agent 视为可采用的执行资源库，而不是系统本体。这里重点看任务范围、接口目标和是否适合作为执行主体。" />
            <div className="task-system-toolbar">
              <div className="task-system-search">
                <Search size={16} />
                <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索 Agent 资源" />
              </div>
              {selectedCategoryId === "worker_sub_agent" ? (
                <button
                  className="action-button action-button--ghost"
                  disabled={saving === "agent-create"}
                  onClick={() => void createWorkerAgentDraft()}
                  type="button"
                >
                  {saving === "agent-create" ? <Loader2 className="spin" size={14} /> : <Plus size={14} />}
                  新工作子Agent
                </button>
              ) : null}
            </div>
            <div className="task-system-agent-type-guide">
              {filteredCategories.map((category) => {
                const Icon = CATEGORY_ICONS[category.category_id as keyof typeof CATEGORY_ICONS] ?? UserCog;
                const active = selectedCategoryId === category.category_id;
                return (
                  <button
                    className={active ? "task-system-agent-type-guide__item task-system-agent-type-guide__item--active" : "task-system-agent-type-guide__item"}
                    key={category.category_id}
                    onClick={() => {
                      setSelectedCategoryId(category.category_id);
                      setSelectedAgentId(category.agents[0]?.agent_id ?? "");
                    }}
                    type="button"
                  >
                    <Icon size={16} />
                    <strong>{category.title}</strong>
                    <p>{category.category_id === "main_agent" ? "主会话默认执行主体。" : category.category_id === "system_management_agent" ? "系统治理和特定任务辅助主体。" : "可被任务授权动态采用或生成的工作子 Agent。"}</p>
                  </button>
                );
              })}
            </div>
            <AgentCategoryRail
              category={filteredCategories.find((item) => item.category_id === selectedCategoryId) ?? null}
              selectedAgentId={selectedAgentId}
              onSelect={setSelectedAgentId}
            />
          </aside>

          <main className="task-system-control-panel">
            <PanelHead
              title="Agent 资源详情"
              description="围绕任务采用场景维护 Agent 的接口、默认投影和任务覆盖范围。"
              action={agentEditorRecord ? (
                <div className="task-system-inline-actions">
                  {selectedAgent && !selectedAgent.builtin ? (
                    <button className="action-button action-button--ghost" disabled={saving === "agent-delete"} onClick={() => void removeAgent()} type="button">
                      {saving === "agent-delete" ? <Loader2 className="spin" size={14} /> : <Sparkles size={14} />}
                      删除 Agent
                    </button>
                  ) : null}
                  <button className="action-button action-button--primary" disabled={saving === "agent"} onClick={() => void saveAgent()} type="button">
                    {saving === "agent" ? <Loader2 className="spin" size={14} /> : <Save size={14} />}
                    保存 Agent
                  </button>
                </div>
              ) : null}
            />
            {agentEditorRecord ? (
              <>
                <div className="task-system-editor-head">
                  <span><UserCog size={18} /></span>
                  <div>
                    <em>{CATEGORY_TITLES[agentEditorCategory as keyof typeof CATEGORY_TITLES] ?? agentEditorCategory}</em>
                    <strong>{agentEditorRecord.agent_name}</strong>
                    <p>{agentEditorRecord.description || "当前 Agent 暂无补充说明。"}</p>
                  </div>
                </div>
                <div className="task-system-info-grid">
                  <InfoBlock title="执行主体编号" value={agentEditorRecord.agent_id} />
                  <InfoBlock title="接口目标" value={agentEditorRecord.interface_target} />
                  <InfoBlock title="任务范围" value={agentEditorTaskScopeSummary} />
                  <InfoBlock title="资源角色" value={selectedCategoryId === "main_agent" ? "默认承接主体" : selectedCategoryId === "system_management_agent" ? "系统协作主体" : "worker blueprint 候选"} />
                </div>
                <div className="task-system-binding-grid">
                  <article className="task-system-binding-card">
                    <span>协作适配</span>
                    <strong>{selectedCategoryId === "main_agent" ? "适合主执行与主协调" : selectedCategoryId === "system_management_agent" ? "适合参与主体或治理节点" : "适合作为工作子 Agent 蓝图"}</strong>
                    <p>任务系统不在这里直接执行 Agent，而是维护这些执行主体何时可被采用、以什么接口进入运行链路。</p>
                  </article>
                  <article className="task-system-binding-card">
                    <span>投影策略</span>
                    <strong>{isMainAgentCategory(agentEditorCategory) ? "主会话外部切换" : projectionTitleById.get(agentEditorRecord.default_projection_id) || agentEditorRecord.default_projection_id || "未指定"}</strong>
                    <p>{isMainAgentCategory(agentEditorCategory) ? "主 Agent 的灵魂和投影由主会话切换链路治理，这里不再在任务系统内硬绑定。" : `灵魂：${soulNameById.get(agentEditorRecord.default_soul_id) || agentEditorRecord.default_soul_id || "未指定"}`}</p>
                  </article>
                </div>
                <div className="task-system-form-grid">
                  <label><span>执行主体编号</span><input disabled={agentEditorBuiltin} value={agentDraft.agent_id} onChange={(event) => setAgentDraft((value) => ({ ...value, agent_id: event.target.value }))} /></label>
                  <label><span>名称</span><input value={agentDraft.agent_name} onChange={(event) => setAgentDraft((value) => ({ ...value, agent_name: event.target.value }))} /></label>
                  <label><span>类别</span><select disabled={agentEditorBuiltin} value={agentDraft.agent_category} onChange={(event) => setAgentDraft((value) => ({ ...value, agent_category: event.target.value }))}><option value="main_agent">主 Agent</option><option value="system_management_agent">系统管理 Agent</option><option value="worker_sub_agent">工作子 Agent</option></select></label>
                  <label><span>接口目标</span><input value={agentDraft.interface_target} onChange={(event) => setAgentDraft((value) => ({ ...value, interface_target: event.target.value }))} /></label>
                  <label className="task-system-form-grid__full"><span>职责说明</span><textarea value={agentDraft.description} onChange={(event) => setAgentDraft((value) => ({ ...value, description: event.target.value }))} /></label>
                  {!isMainAgentCategory(agentDraft.agent_category) ? (
                    <ProjectionPicker label="默认投影" projectionId={agentDraft.default_projection_id} projections={projections} onChange={(projectionId) => setAgentDraft((value) => ({ ...value, default_projection_id: projectionId, default_soul_id: String(projections.find((projection) => projection.projection_id === projectionId)?.soul_id || "") }))} />
                  ) : (
                    <div className="task-system-form-grid__full task-system-empty">主 Agent 的灵魂与投影由主会话外部切换链路管理，这里不再绑定。</div>
                  )}
                  <label className="task-system-form-grid__full"><span>任务覆盖范围</span><textarea value={agentDraft.task_scope_text} onChange={(event) => setAgentDraft((value) => ({ ...value, task_scope_text: event.target.value }))} /></label>
                  <label className="task-system-checkbox"><input checked={agentDraft.enabled} onChange={(event) => setAgentDraft((value) => ({ ...value, enabled: event.target.checked }))} type="checkbox" />启用 Agent</label>
                </div>
              </>
            ) : (
              <div className="task-system-empty">当前类别暂无 Agent。</div>
            )}
          </main>
        </section>
      ) : null}
    </div>
  );
}

function PanelHead({
  title,
  description,
  action
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="task-system-section-head">
      <div>
        <h3>{title}</h3>
        {description ? <p>{description}</p> : null}
      </div>
      {action}
    </div>
  );
}

function InfoBlock({ title, value }: { title: string; value: string }) {
  return (
    <article className="task-system-info-block">
      <span>{title}</span>
      <strong>{value}</strong>
    </article>
  );
}

function AgentCategoryRail({
  category,
  selectedAgentId,
  onSelect
}: {
  category: AgentCategory | null;
  selectedAgentId: string;
  onSelect: (agentId: string) => void;
}) {
  if (!category) {
    return <div className="task-system-empty">没有可展示的 Agent 类别。</div>;
  }
  return (
    <section className="task-system-agent-group">
      <div className="task-system-agent-group__head">
        <strong>{category.title}</strong>
        <span>{category.agents.length}</span>
      </div>
      <div className="task-system-agent-card-grid">
        {category.agents.map((agent) => {
          const Icon = CATEGORY_ICONS[agent.agent_category as keyof typeof CATEGORY_ICONS] ?? UserCog;
          return (
            <button className={selectedAgentId === agent.agent_id ? "task-system-agent-card task-system-agent-card--active" : "task-system-agent-card"} key={agent.agent_id} onClick={() => onSelect(agent.agent_id)} type="button">
              <div className="task-system-agent-card__head">
                <div>
                  <h4>{agent.agent_name}</h4>
                  <p>{agent.agent_id}</p>
                </div>
                <Icon size={17} />
              </div>
              <div className="task-system-agent-card__flows">
                接口 {text(agent.interface_target)}<br />
                任务范围 {agent.task_scope.length ? agent.task_scope.join(" / ") : "未定义"}
              </div>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function TaskSummaryCard({
  title,
  value,
  detail
}: {
  title: string;
  value: string;
  detail: string;
}) {
  return (
    <article className="task-system-summary-card">
      <span>{title}</span>
      <strong>{value || "未指定"}</strong>
      <p>{detail || "未补充说明"}</p>
    </article>
  );
}

function WorkflowWorkbench({
  draft,
  onChange,
  onBindCurrent
}: {
  draft: WorkflowDraft;
  onChange: (draft: WorkflowDraft) => void;
  onBindCurrent: () => void;
}) {
  return (
    <div className="task-system-workflow-workbench">
      <div className="task-system-workflow-hero">
        <div>
          <span>执行流程</span>
          <strong>{draft.title || "未命名执行流程"}</strong>
          <p>{String(draft.metadata?.display_number || displayNumberFromId(draft.workflow_id, "流程"))}</p>
        </div>
        <button className="action-button action-button--ghost" onClick={onBindCurrent} type="button">
          <Workflow size={14} />
          绑定到当前任务
        </button>
      </div>

      <div className="task-system-form-grid">
        <label><span>流程名称</span><input value={draft.title} onChange={(event) => onChange({ ...draft, title: event.target.value })} /></label>
        <label><span>适用任务类型</span><select value={draft.task_mode} onChange={(event) => onChange({ ...draft, task_mode: event.target.value })}>{TASK_MODE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
        <label><span>流程编号</span><input value={String(draft.metadata?.display_number || displayNumberFromId(draft.workflow_id, "流程"))} readOnly /></label>
        <label><span>结果输出</span><input value={maskSystemValue(draft.output_contract_id, "系统结果输出")} readOnly /></label>
        <label className="task-system-form-grid__full"><span>兼容风格范围</span><textarea value={draft.compatible_projection_ids_text} onChange={(event) => onChange({ ...draft, compatible_projection_ids_text: event.target.value })} /></label>
      </div>

      <div className="task-system-workflow-grid">
        <label className="task-system-workflow-card">
          <span>步骤结构</span>
          <textarea value={draft.steps_text} onChange={(event) => onChange({ ...draft, steps_text: event.target.value })} />
          <small>每行填写一个步骤，格式为“步骤编号 | 步骤名称”。</small>
        </label>
        <label className="task-system-workflow-card">
          <span>可见 Skills</span>
          <textarea value={draft.visible_skill_ids_text} onChange={(event) => onChange({ ...draft, visible_skill_ids_text: event.target.value })} />
          <small>限制执行流程可直接调用的能力集合。</small>
        </label>
        <label className="task-system-workflow-card">
          <span>停止条件</span>
          <textarea value={draft.stop_conditions_text} onChange={(event) => onChange({ ...draft, stop_conditions_text: event.target.value })} />
          <small>显式定义执行终点，避免模型无限外推。</small>
        </label>
        <label className="task-system-workflow-card">
          <span>证据引用</span>
          <textarea value={draft.required_evidence_refs_text} onChange={(event) => onChange({ ...draft, required_evidence_refs_text: event.target.value })} />
          <small>要求任务在输出前引用或核对的证据资源。</small>
        </label>
        <label className="task-system-workflow-card">
          <span>输入边界</span>
          <textarea value={draft.input_boundary} onChange={(event) => onChange({ ...draft, input_boundary: event.target.value })} />
          <small>说明执行流程允许消费哪些输入，哪些输入需要被拒绝或转交。</small>
        </label>
        <label className="task-system-workflow-card">
          <span>输出边界</span>
          <textarea value={draft.output_boundary} onChange={(event) => onChange({ ...draft, output_boundary: event.target.value })} />
          <small>说明执行流程最终可以输出什么形态，防止任务越权输出。</small>
        </label>
      </div>

      <div className="task-system-form-grid">
        <label className="task-system-form-grid__full"><span>Prompt 补充</span><textarea value={draft.prompt} onChange={(event) => onChange({ ...draft, prompt: event.target.value })} /></label>
        <label className="task-system-checkbox"><input checked={draft.enabled} onChange={(event) => onChange({ ...draft, enabled: event.target.checked })} type="checkbox" />启用执行流程</label>
      </div>
    </div>
  );
}

function ProjectionPicker({
  label,
  projectionId,
  projections,
  onChange,
  disabled = false
}: {
  label: string;
  projectionId: string;
  projections: SoulProjectionCard[];
  onChange: (projectionId: string) => void;
  disabled?: boolean;
}) {
  const selectedSoulId = String(projections.find((projection) => projection.projection_id === projectionId)?.soul_id || "");
  const soulOptions = Array.from(new Map(projections.map((projection) => [projection.soul_id, projection.soul_name || projection.soul_id])).entries()).filter(([soulId]) => soulId);
  const activeSoulId = selectedSoulId || soulOptions[0]?.[0] || "";
  const scopedProjections = projections.filter((projection) => projection.soul_id === activeSoulId);
  return (
    <>
      <label><span>{label} / 灵魂</span><select disabled={disabled} value={activeSoulId} onChange={(event) => onChange(projections.find((projection) => projection.soul_id === event.target.value)?.projection_id || "")}><option value="">未指定</option>{soulOptions.map(([soulId, soulName]) => <option key={soulId} value={soulId}>{soulName}</option>)}</select></label>
      <label><span>{label} / 投影</span><select disabled={disabled} value={projectionId} onChange={(event) => onChange(event.target.value)}><option value="">未指定</option>{scopedProjections.map((projection) => <option key={projection.projection_id} value={projection.projection_id}>{projection.title || projection.projection_id}</option>)}</select></label>
    </>
  );
}
