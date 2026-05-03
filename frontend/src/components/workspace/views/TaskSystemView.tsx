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
type TaskWorkbenchTab = "definition" | "binding" | "workflow";

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

function preferredGameWorkflowId(workflows: TaskWorkflowRecord[]) {
  return workflows.find((workflow) => workflow.workflow_id === "workflow.dev.light_web_game")?.workflow_id
    ?? workflows[0]?.workflow_id
    ?? "workflow.dev.light_web_game";
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
  return {
    task_id: "task.dev.light_web_game",
    task_title: "轻量网页小游戏开发",
    task_kind: "specific_task",
    task_family: "development",
    task_mode: "light_web_game",
    flow_id: "flow.dev.light_web_game",
    default_agent_id: "agent:0",
    participant_agent_ids: [],
    workflow_id: workflowId || "workflow.dev.light_web_game",
    workflow_file_ref: `workflow:${workflowId || "workflow.dev.light_web_game"}`,
    projection_id: projectionId,
    input_contract_id: "LightWebGameTaskInput",
    output_contract_id: "LightWebGameResult",
    task_structure: {
      runtime_lane_hint: "game_delivery",
      memory_scope_hint: "conversation_read_write",
      trigger_signals: ["小游戏", "web game", "snake", "canvas game"],
      notes: "默认由主 Agent 承接，目标是交付可运行、可操作、可验证的轻量网页小游戏。",
      workspace_target_hint: "frontend/public or standalone html file",
      delivery_expectation: "playable_web_game"
    },
    enabled: true,
    metadata: { managed_by: "task_system_console" },
    trigger_signals_text: "小游戏\nweb game\nsnake\ncanvas game",
    notes: "默认由主 Agent 承接，目标是交付可运行、可操作、可验证的轻量网页小游戏。"
  };
}

function specificTaskDraftFrom(task: TaskAssignment): SpecificTaskDraft {
  return {
    ...task,
    task_structure: task.task_structure ?? {},
    metadata: task.metadata ?? {},
    trigger_signals_text: listText((task.task_structure?.trigger_signals as string[] | undefined) ?? []),
    notes: text(task.task_structure?.notes, "")
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

export function TaskSystemView() {
  const [consoleData, setConsoleData] = useState<TaskSystemConsole | null>(null);
  const [projectionCatalog, setProjectionCatalog] = useState<SoulProjectionCatalog | null>(null);
  const [activePage, setActivePage] = useState<TaskPage>("agents");
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
  const selectedGeneralTask = taskManagement?.general_tasks.find((item) => item.profile_id === selectedGeneralId) ?? taskManagement?.general_tasks[0] ?? null;
  const selectedSpecificTask = taskManagement?.specific_tasks.find((item) => item.task_id === selectedSpecificTaskId) ?? taskManagement?.specific_tasks[0] ?? null;
  const selectedWorkflow = workflows.find((item) => item.workflow_id === (taskModeTab === "general" ? selectedGeneralTask?.default_workflow_id : selectedSpecificTask?.workflow_id)) ?? workflows[0] ?? null;
  const selectedCoordinationTask = coordinationManagement?.coordination_tasks.find((item) => item.coordination_task_id === selectedCoordinationId) ?? coordinationManagement?.coordination_tasks[0] ?? null;
  const selectedTopology = coordinationManagement?.topology_templates.find((item) => item.template_id === selectedTopologyId) ?? coordinationManagement?.topology_templates[0] ?? null;

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
    } else {
      setSpecificTaskDraft(emptySpecificTask(preferredGameWorkflowId(workflows), projections[0]?.projection_id ?? ""));
    }
  }, [selectedSpecificTask, workflows, projections]);

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
    } else {
      setCoordinationDraft(emptyCoordination(coordinationManagement?.topology_templates[0]?.template_id ?? ""));
    }
  }, [selectedCoordinationTask, coordinationManagement?.topology_templates]);

  useEffect(() => {
    if (selectedTopology) {
      setTopologyDraft(topologyDraftFrom(selectedTopology));
    } else {
      setTopologyDraft(emptyTopology());
    }
  }, [selectedTopology]);

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
        ...specificTaskDraft,
        workflow_id: workflow.workflow_id,
        workflow_file_ref: `workflow:${workflow.workflow_id}`,
        task_structure: {
          ...specificTaskDraft.task_structure,
          trigger_signals: splitList(specificTaskDraft.trigger_signals_text),
          notes: specificTaskDraft.notes
        },
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
      setNotice("workflow 已保存，并已绑定到当前任务草稿。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存 workflow 失败");
    } finally {
      setSaving("");
    }
  }

  function createSpecificTaskDraft() {
    const draft = emptySpecificTask(preferredGameWorkflowId(workflows), projections[0]?.projection_id ?? "");
    setSelectedSpecificTaskId(draft.task_id);
    setSpecificTaskDraft(draft);
    setTaskWorkbenchTab("definition");
  }

  function createWorkflowDraft() {
    setWorkflowDraft(emptyWorkflow());
    setTaskWorkbenchTab("workflow");
  }

  const taskList = taskModeTab === "general" ? taskManagement?.general_tasks ?? [] : taskManagement?.specific_tasks ?? [];
  const currentTaskId = taskModeTab === "general" ? generalDraft.profile_id : specificTaskDraft.task_id;
  const currentTaskTitle = taskModeTab === "general" ? generalDraft.title : specificTaskDraft.task_title;
  const currentTaskAgentId = taskModeTab === "general" ? generalDraft.default_agent_id : specificTaskDraft.default_agent_id;
  const currentTaskWorkflowId = taskModeTab === "general" ? generalDraft.default_workflow_id : specificTaskDraft.workflow_id;
  const currentTaskProjectionId = taskModeTab === "general" ? generalDraft.default_projection_id : specificTaskDraft.projection_id;
  const currentTaskInputContract = taskModeTab === "general" ? generalDraft.input_contract_id : specificTaskDraft.input_contract_id;
  const currentTaskOutputContract = taskModeTab === "general" ? generalDraft.output_contract_id : specificTaskDraft.output_contract_id;
  const currentTaskAgentName = allAgents.find((agent) => agent.agent_id === currentTaskAgentId)?.agent_name ?? currentTaskAgentId;
  const currentTaskProjectionTitle = projectionTitleById.get(currentTaskProjectionId) || currentTaskProjectionId || "未绑定";

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
          <p className="workspace-view__eyebrow">Task Control Plane</p>
          <h2 className="workspace-view__title">任务系统</h2>
          <p className="workspace-view__subtitle">围绕 Agent、任务、workflow 和协调拓扑建立真正可登记、可绑定、可执行的管理中枢。</p>
        </div>
      </header>

      {error ? <div className="workspace-alert workspace-alert--danger">{error}</div> : null}
      {notice ? <div className="workspace-alert">{notice}</div> : null}
      {loading ? <div className="workspace-alert"><Loader2 className="spin" size={16} /> 正在加载任务系统...</div> : null}

      <nav className="task-system-switcher" aria-label="任务系统模块">
        {[
          { key: "agents", label: "Agent 管理", icon: Bot },
          { key: "tasks", label: "任务管理", icon: Workflow },
          { key: "coordination", label: "编排管理", icon: GitBranch }
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

      {activePage === "agents" ? (
        <section className="task-system-control-grid task-system-control-grid--two task-system-control-grid--agents">
          <aside className="task-system-control-panel">
            <div className="task-system-toolbar">
              <div className="archive-search task-system-search">
                <Search size={16} />
                <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索 Agent" />
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
                    <p>{category.category_id === "worker_sub_agent" ? "可创建、编辑、删除工作子 Agent。" : "可编辑当前登记信息。"}</p>
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
              title="Agent 登记"
              description="登记接口、默认投影和任务覆盖范围，统一维护 Agent 注册表。"
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
                  <InfoBlock title="Agent ID" value={agentEditorRecord.agent_id} />
                  <InfoBlock title="接口目标" value={agentEditorRecord.interface_target} />
                  <InfoBlock title="灵魂" value={isMainAgentCategory(agentEditorCategory) ? "外部切换" : soulNameById.get(agentEditorRecord.default_soul_id) || agentEditorRecord.default_soul_id || "未指定"} />
                  <InfoBlock title="默认投影" value={isMainAgentCategory(agentEditorCategory) ? "不在任务系统内绑定" : projectionTitleById.get(agentEditorRecord.default_projection_id) || agentEditorRecord.default_projection_id || "未指定"} />
                </div>
                <div className="task-system-form-grid">
                  <label><span>Agent ID</span><input disabled={agentEditorBuiltin} value={agentDraft.agent_id} onChange={(event) => setAgentDraft((value) => ({ ...value, agent_id: event.target.value }))} /></label>
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

      {activePage === "tasks" ? (
        <section className="task-system-task-layout">
          <aside className="task-system-control-panel task-system-task-rail">
            <PanelHead
              title="任务分类"
              description="任务系统先区分通用任务与特定任务，再进入对应的配置主面。"
            />
            <nav className="task-system-switcher">
              <button className={taskModeTab === "general" ? "task-system-switcher__item task-system-switcher__item--active" : "task-system-switcher__item"} onClick={() => setTaskModeTab("general")} type="button">通用任务</button>
              <button className={taskModeTab === "specific" ? "task-system-switcher__item task-system-switcher__item--active" : "task-system-switcher__item"} onClick={() => setTaskModeTab("specific")} type="button">特定任务</button>
            </nav>

            {taskModeTab === "general" ? (
              <div className="task-system-task-rail__stack">
                <button className="task-system-select-card task-system-select-card--active" type="button">
                  <Bot size={16} />
                  <strong>{generalDraft.title}</strong>
                  <Badge value={generalDraft.enabled ? "enabled" : "disabled"} />
                  <span>主会话默认承接配置。用户不需要显式选择，它只负责定义入口默认行为。</span>
                </button>
                <div className="task-system-task-note">
                  <span>主链路</span>
                  <strong>{"主会话 -> 主 Agent -> 通用任务配置 -> 如需再分流到特定任务"}</strong>
                </div>
              </div>
            ) : (
              <div className="task-system-task-rail__stack">
                <div className="task-system-toolbar">
                  <strong className="task-system-inline-title">特定任务列表</strong>
                  <button className="action-button action-button--ghost" onClick={createSpecificTaskDraft} type="button">
                    <Plus size={14} />
                    新特定任务
                  </button>
                </div>
                <div className="task-system-flow-tabs">
                  {taskList.map((item) => {
                    const task = item as TaskAssignment;
                    const active = selectedSpecificTaskId === task.task_id;
                    return (
                      <button className={active ? "task-system-flow-tab task-system-flow-tab--active" : "task-system-flow-tab"} key={task.task_id} onClick={() => setSelectedSpecificTaskId(task.task_id)} type="button">
                        <Workflow size={14} />
                        <span>{task.task_title}</span>
                        <Badge value={task.enabled ? "enabled" : "disabled"} />
                        <small>{task.default_agent_id} / {task.workflow_id || "未绑定 workflow"}</small>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </aside>

          <main className="task-system-control-panel task-system-task-workbench">
            <PanelHead
              title={taskModeTab === "general" ? "通用任务配置" : "特定任务配置"}
              description={taskModeTab === "general" ? "通用任务是主会话默认配置，不需要用户选择；它负责默认入口、默认 workflow 与默认投影。" : "特定任务需要显式登记任务契约、承接 Agent、workflow 与投影，保证 Agent 能稳定消费。"}
              action={
                <div className="task-system-inline-actions">
                  <button className="action-button action-button--ghost" disabled={saving === "workflow"} onClick={() => void saveWorkflowOnly()} type="button">
                    {saving === "workflow" ? <Loader2 className="spin" size={14} /> : <Layers3 size={14} />}
                    保存 workflow
                  </button>
                  <button className="action-button action-button--primary" disabled={Boolean(saving) && saving !== "workflow"} onClick={() => taskModeTab === "general" ? void saveGeneralTask() : void saveSpecificTask()} type="button">
                    {saving === "general" || saving === "specific" ? <Loader2 className="spin" size={14} /> : <Save size={14} />}
                    保存任务
                  </button>
                </div>
              }
            />

            <section className="task-system-task-cover">
              <TaskSummaryCard title="任务标识" value={currentTaskId} detail={currentTaskTitle} />
              <TaskSummaryCard title="承接 Agent" value={currentTaskAgentName || "未指定"} detail={currentTaskAgentId || "未绑定"} />
              <TaskSummaryCard title="绑定 workflow" value={currentTaskWorkflowId || "未绑定"} detail="任务先定目标，再装配 workflow" />
              <TaskSummaryCard title="任务投影" value={currentTaskProjectionTitle} detail={currentTaskProjectionId || "未绑定"} />
            </section>

            <nav className="task-system-switcher task-system-switcher--three">
              <button className={taskWorkbenchTab === "definition" ? "task-system-switcher__item task-system-switcher__item--active" : "task-system-switcher__item"} onClick={() => setTaskWorkbenchTab("definition")} type="button">任务定义</button>
              <button className={taskWorkbenchTab === "binding" ? "task-system-switcher__item task-system-switcher__item--active" : "task-system-switcher__item"} onClick={() => setTaskWorkbenchTab("binding")} type="button">执行绑定</button>
              <button className={taskWorkbenchTab === "workflow" ? "task-system-switcher__item task-system-switcher__item--active" : "task-system-switcher__item"} onClick={() => setTaskWorkbenchTab("workflow")} type="button">Workflow</button>
            </nav>

            {taskWorkbenchTab === "definition" ? (
              taskModeTab === "general" ? (
                <div className="task-system-form-section">
                  <div className="task-system-callout">
                    <span>通用任务原则</span>
                    <strong>通用任务只是主会话默认承接规则，不要求用户显式选择。</strong>
                    <p>它负责把主会话稳定地接入任务系统，并为后续是否分流到特定任务提供默认入口。</p>
                  </div>
                  <div className="task-system-form-grid">
                    <label><span>Profile ID</span><input value={generalDraft.profile_id} onChange={(event) => setGeneralDraft((value) => ({ ...value, profile_id: event.target.value }))} /></label>
                    <label><span>标题</span><input value={generalDraft.title} onChange={(event) => setGeneralDraft((value) => ({ ...value, title: event.target.value }))} /></label>
                    <label className="task-system-form-grid__full"><span>对话入口策略</span><input value={generalDraft.conversation_entry_policy} onChange={(event) => setGeneralDraft((value) => ({ ...value, conversation_entry_policy: event.target.value }))} /></label>
                    <label><span>Input Contract</span><input value={generalDraft.input_contract_id} onChange={(event) => setGeneralDraft((value) => ({ ...value, input_contract_id: event.target.value }))} /></label>
                    <label><span>Output Contract</span><input value={generalDraft.output_contract_id} onChange={(event) => setGeneralDraft((value) => ({ ...value, output_contract_id: event.target.value }))} /></label>
                    <label className="task-system-checkbox"><input checked={generalDraft.enabled} onChange={(event) => setGeneralDraft((value) => ({ ...value, enabled: event.target.checked }))} type="checkbox" />启用通用任务</label>
                  </div>
                </div>
              ) : (
                <div className="task-system-form-section">
                  <div className="task-system-form-grid">
                    <label><span>Task ID</span><input value={specificTaskDraft.task_id} onChange={(event) => setSpecificTaskDraft((value) => ({ ...value, task_id: event.target.value, flow_id: `flow.${slug(event.target.value.replace(/^task\./, ""))}` }))} /></label>
                    <label><span>标题</span><input value={specificTaskDraft.task_title} onChange={(event) => setSpecificTaskDraft((value) => ({ ...value, task_title: event.target.value }))} /></label>
                    <label><span>Task Family</span><input value={specificTaskDraft.task_family} onChange={(event) => setSpecificTaskDraft((value) => ({ ...value, task_family: event.target.value }))} /></label>
                    <label><span>Task Mode</span><input value={specificTaskDraft.task_mode} onChange={(event) => setSpecificTaskDraft((value) => ({ ...value, task_mode: event.target.value }))} /></label>
                    <label className="task-system-form-grid__full"><span>触发信号</span><textarea value={specificTaskDraft.trigger_signals_text} onChange={(event) => setSpecificTaskDraft((value) => ({ ...value, trigger_signals_text: event.target.value }))} /></label>
                    <label className="task-system-form-grid__full"><span>任务备注</span><textarea value={specificTaskDraft.notes} onChange={(event) => setSpecificTaskDraft((value) => ({ ...value, notes: event.target.value }))} /></label>
                    <label className="task-system-checkbox"><input checked={specificTaskDraft.enabled} onChange={(event) => setSpecificTaskDraft((value) => ({ ...value, enabled: event.target.checked }))} type="checkbox" />启用特定任务</label>
                  </div>
                </div>
              )
            ) : null}

            {taskWorkbenchTab === "binding" ? (
              <div className="task-system-form-section">
                <div className="task-system-binding-grid">
                  <article className="task-system-binding-card">
                    <span>Prompts 装配顺序</span>
                    <strong>{"task -> workflow -> projection"}</strong>
                    <p>任务先定义目标和契约，再由 workflow 规定做法，最后用 projection 补充执行姿态。</p>
                  </article>
                  <article className="task-system-binding-card">
                    <span>稳定消费机制</span>
                    <strong>{`${currentTaskInputContract} -> ${currentTaskOutputContract}`}</strong>
                    <p>Agent 消费的是显式任务契约，而不是完全依靠模型自己去猜任务边界。</p>
                  </article>
                </div>
                <div className="task-system-form-grid">
                  <label><span>默认承接 Agent</span><select value={taskModeTab === "general" ? generalDraft.default_agent_id : specificTaskDraft.default_agent_id} onChange={(event) => taskModeTab === "general" ? setGeneralDraft((value) => ({ ...value, default_agent_id: event.target.value })) : setSpecificTaskDraft((value) => ({ ...value, default_agent_id: event.target.value }))}>{allAgents.map((agent) => <option key={agent.agent_id} value={agent.agent_id}>{agent.agent_name}</option>)}</select></label>
                  <label><span>绑定 workflow</span><select value={currentTaskWorkflowId} onChange={(event) => {
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
                        workflow_id: workflowId,
                        workflow_file_ref: workflowId ? `workflow:${workflowId}` : ""
                      }));
                    }
                    if (workflow) {
                      setWorkflowDraft(workflowDraftFrom(workflow));
                    }
                  }}>{workflows.map((workflow) => <option key={workflow.workflow_id} value={workflow.workflow_id}>{workflow.title}</option>)}</select></label>
                  <ProjectionPicker label="任务投影" projectionId={currentTaskProjectionId} projections={projections} onChange={(projectionId) => taskModeTab === "general" ? setGeneralDraft((value) => ({ ...value, default_projection_id: projectionId })) : setSpecificTaskDraft((value) => ({ ...value, projection_id: projectionId }))} />
                  <label><span>Input Contract</span><input value={currentTaskInputContract} onChange={(event) => taskModeTab === "general" ? setGeneralDraft((value) => ({ ...value, input_contract_id: event.target.value })) : setSpecificTaskDraft((value) => ({ ...value, input_contract_id: event.target.value }))} /></label>
                  <label><span>Output Contract</span><input value={currentTaskOutputContract} onChange={(event) => taskModeTab === "general" ? setGeneralDraft((value) => ({ ...value, output_contract_id: event.target.value })) : setSpecificTaskDraft((value) => ({ ...value, output_contract_id: event.target.value }))} /></label>
                  {taskModeTab === "specific" ? (
                    <label className="task-system-form-grid__full"><span>显式装载的协作 Agent</span><textarea value={listText(specificTaskDraft.participant_agent_ids)} onChange={(event) => setSpecificTaskDraft((value) => ({ ...value, participant_agent_ids: splitList(event.target.value) }))} /></label>
                  ) : null}
                </div>
              </div>
            ) : null}

            {taskWorkbenchTab === "workflow" ? (
              <div className="task-system-form-section">
                <div className="task-system-toolbar">
                  <div className="task-system-inline-copy">
                    <strong>当前 workflow</strong>
                    <span>{workflowDraft.title} / {workflowDraft.workflow_id}</span>
                  </div>
                  <button className="action-button action-button--ghost" onClick={createWorkflowDraft} type="button">
                    <Plus size={14} />
                    新 workflow
                  </button>
                </div>
                <div className="task-system-binding-grid">
                  <article className="task-system-binding-card">
                    <span>workflow 的位置</span>
                    <strong>任务资源，不是独立中心</strong>
                    <p>workflow 脱离任务没有实际管理意义，所以它在任务页内部编辑，并由任务绑定进入运行时。</p>
                  </article>
                  <article className="task-system-binding-card">
                    <span>workflow 的职责</span>
                    <strong>规定做法、边界与停机条件</strong>
                    <p>它负责步骤、可见 skills、输入输出边界与停止条件，而不是单纯堆一个总 prompts 文本。</p>
                  </article>
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
          </main>
        </section>
      ) : null}

      {activePage === "coordination" ? (
        <section className="task-system-control-grid">
          <aside className="task-system-control-panel">
            <PanelHead title="协调任务" description="登记需要多个 Agent 协同完成的任务实例。" action={<button className="action-button action-button--ghost" onClick={() => setCoordinationDraft(emptyCoordination(selectedTopologyId))} type="button"><Plus size={14} />新协调任务</button>} />
            <div className="task-system-flow-tabs">
              {(coordinationManagement?.coordination_tasks ?? []).map((task) => (
                <button className={selectedCoordinationId === task.coordination_task_id ? "task-system-flow-tab task-system-flow-tab--active" : "task-system-flow-tab"} key={task.coordination_task_id} onClick={() => setSelectedCoordinationId(task.coordination_task_id)} type="button">
                  <GitBranch size={14} />
                  <span>{task.title}</span>
                  <Badge value={task.enabled ? "enabled" : "disabled"} />
                </button>
              ))}
            </div>
          </aside>

          <main className="task-system-control-panel">
            <PanelHead title="协调任务登记" description="定义协调 Agent、参与 Agent 与收敛规则。" action={<button className="action-button action-button--primary" disabled={saving === "coordination"} onClick={() => void saveCoordination()} type="button"><Save size={14} />保存协调任务</button>} />
            <div className="task-system-form-grid">
              <label><span>Coordination ID</span><input value={coordinationDraft.coordination_task_id} onChange={(event) => setCoordinationDraft((value) => ({ ...value, coordination_task_id: event.target.value }))} /></label>
              <label><span>标题</span><input value={coordinationDraft.title} onChange={(event) => setCoordinationDraft((value) => ({ ...value, title: event.target.value }))} /></label>
              <label><span>协调模式</span><input value={coordinationDraft.coordination_mode} onChange={(event) => setCoordinationDraft((value) => ({ ...value, coordination_mode: event.target.value }))} /></label>
              <label><span>协调 Agent</span><select value={coordinationDraft.coordinator_agent_id} onChange={(event) => setCoordinationDraft((value) => ({ ...value, coordinator_agent_id: event.target.value }))}>{allAgents.map((agent) => <option key={agent.agent_id} value={agent.agent_id}>{agent.agent_name}</option>)}</select></label>
              <label><span>拓扑模板</span><select value={coordinationDraft.topology_template_id} onChange={(event) => setCoordinationDraft((value) => ({ ...value, topology_template_id: event.target.value }))}>{(coordinationManagement?.topology_templates ?? []).map((template) => <option key={template.template_id} value={template.template_id}>{template.title}</option>)}</select></label>
              <label className="task-system-form-grid__full"><span>参与 Agent</span><textarea value={coordinationDraft.participant_agent_ids_text} onChange={(event) => setCoordinationDraft((value) => ({ ...value, participant_agent_ids_text: event.target.value }))} /></label>
              <label className="task-system-form-grid__full"><span>停止条件</span><textarea value={coordinationDraft.stop_conditions_text} onChange={(event) => setCoordinationDraft((value) => ({ ...value, stop_conditions_text: event.target.value }))} /></label>
              <label className="task-system-checkbox"><input checked={coordinationDraft.enabled} onChange={(event) => setCoordinationDraft((value) => ({ ...value, enabled: event.target.checked }))} type="checkbox" />启用协调任务</label>
            </div>
          </main>

          <aside className="task-system-control-panel">
            <PanelHead title="拓扑模板" description="维护多 Agent 协作时的节点、边和交接规则。" action={<button className="action-button action-button--primary" disabled={saving === "topology"} onClick={() => void saveTopology()} type="button"><Save size={14} />保存拓扑</button>} />
            <div className="task-system-form-grid">
              <label><span>Template ID</span><input value={topologyDraft.template_id} onChange={(event) => setTopologyDraft((value) => ({ ...value, template_id: event.target.value }))} /></label>
              <label><span>标题</span><input value={topologyDraft.title} onChange={(event) => setTopologyDraft((value) => ({ ...value, title: event.target.value }))} /></label>
              <label><span>Join Policy</span><input value={topologyDraft.join_policy} onChange={(event) => setTopologyDraft((value) => ({ ...value, join_policy: event.target.value }))} /></label>
              <label><span>Failure Policy</span><input value={topologyDraft.failure_policy} onChange={(event) => setTopologyDraft((value) => ({ ...value, failure_policy: event.target.value }))} /></label>
              <label className="task-system-form-grid__full"><span>Nodes JSON</span><textarea value={topologyDraft.nodes_text} onChange={(event) => setTopologyDraft((value) => ({ ...value, nodes_text: event.target.value }))} /></label>
              <label className="task-system-form-grid__full"><span>Edges JSON</span><textarea value={topologyDraft.edges_text} onChange={(event) => setTopologyDraft((value) => ({ ...value, edges_text: event.target.value }))} /></label>
              <label className="task-system-form-grid__full"><span>Handoff Rules JSON</span><textarea value={topologyDraft.handoff_rules_text} onChange={(event) => setTopologyDraft((value) => ({ ...value, handoff_rules_text: event.target.value }))} /></label>
              <label className="task-system-checkbox"><input checked={topologyDraft.enabled} onChange={(event) => setTopologyDraft((value) => ({ ...value, enabled: event.target.checked }))} type="checkbox" />启用拓扑模板</label>
            </div>
          </aside>
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
          <span>Workflow Resource</span>
          <strong>{draft.title || "未命名 workflow"}</strong>
          <p>{draft.workflow_id || "请先定义 workflow 标识，然后把它绑定到任务。"}</p>
        </div>
        <button className="action-button action-button--ghost" onClick={onBindCurrent} type="button">
          <Workflow size={14} />
          绑定到当前任务
        </button>
      </div>

      <div className="task-system-form-grid">
        <label><span>Workflow ID</span><input value={draft.workflow_id} onChange={(event) => onChange({ ...draft, workflow_id: event.target.value })} /></label>
        <label><span>标题</span><input value={draft.title} onChange={(event) => onChange({ ...draft, title: event.target.value })} /></label>
        <label><span>Task Mode</span><input value={draft.task_mode} onChange={(event) => onChange({ ...draft, task_mode: event.target.value })} /></label>
        <label><span>Output Contract</span><input value={draft.output_contract_id} onChange={(event) => onChange({ ...draft, output_contract_id: event.target.value })} /></label>
        <label className="task-system-form-grid__full"><span>兼容投影范围</span><textarea value={draft.compatible_projection_ids_text} onChange={(event) => onChange({ ...draft, compatible_projection_ids_text: event.target.value })} /></label>
      </div>

      <div className="task-system-workflow-grid">
        <label className="task-system-workflow-card">
          <span>步骤结构</span>
          <textarea value={draft.steps_text} onChange={(event) => onChange({ ...draft, steps_text: event.target.value })} />
          <small>每行格式：`step_id | 标题`</small>
        </label>
        <label className="task-system-workflow-card">
          <span>可见 Skills</span>
          <textarea value={draft.visible_skill_ids_text} onChange={(event) => onChange({ ...draft, visible_skill_ids_text: event.target.value })} />
          <small>限制 workflow 可直接调用的能力集合。</small>
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
          <small>说明 workflow 允许消费哪些输入，哪些输入需要被拒绝或转交。</small>
        </label>
        <label className="task-system-workflow-card">
          <span>输出边界</span>
          <textarea value={draft.output_boundary} onChange={(event) => onChange({ ...draft, output_boundary: event.target.value })} />
          <small>说明 workflow 最终可以输出什么形态，防止任务越权输出。</small>
        </label>
      </div>

      <div className="task-system-form-grid">
        <label className="task-system-form-grid__full"><span>Prompt 补充</span><textarea value={draft.prompt} onChange={(event) => onChange({ ...draft, prompt: event.target.value })} /></label>
        <label className="task-system-checkbox"><input checked={draft.enabled} onChange={(event) => onChange({ ...draft, enabled: event.target.checked })} type="checkbox" />启用 workflow</label>
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
