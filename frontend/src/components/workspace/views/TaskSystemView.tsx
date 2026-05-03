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
  allowed_projection_ids_text: string;
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
    task_id: "task.custom.new_task",
    task_title: "新特定任务",
    task_kind: "specific_task",
    task_family: "custom",
    task_mode: "custom_task",
    flow_id: "flow.custom.new_task",
    default_agent_id: "agent:0",
    participant_agent_ids: [],
    workflow_id: workflowId,
    workflow_file_ref: workflowId ? `workflow:${workflowId}` : "",
    projection_id: projectionId,
    input_contract_id: "TaskInput",
    output_contract_id: "TaskOutput",
    task_structure: {
      runtime_lane_hint: "",
      memory_scope_hint: "",
      trigger_signals: [],
      notes: ""
    },
    enabled: true,
    metadata: { managed_by: "task_system_console" },
    trigger_signals_text: "",
    notes: ""
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
    allowed_projection_ids: workflow.allowed_projection_ids ?? [],
    steps_text: stepsToText(workflow.steps ?? []),
    visible_skill_ids_text: listText(workflow.visible_skill_ids),
    stop_conditions_text: listText(workflow.stop_conditions),
    required_evidence_refs_text: listText(workflow.required_evidence_refs),
    allowed_projection_ids_text: listText(workflow.allowed_projection_ids)
  };
}

function emptyWorkflow(projectionId = ""): WorkflowDraft {
  return workflowDraftFrom({
    workflow_id: "workflow.custom.new_task",
    title: "新任务工作流",
    task_mode: "custom_task",
    default_projection_id: projectionId,
    allowed_projection_ids: projectionId ? [projectionId] : [],
    visible_skill_ids: [],
    steps: [
      { step_id: "understand", title: "理解任务输入" },
      { step_id: "execute", title: "执行任务步骤" },
      { step_id: "finalize", title: "形成任务输出" }
    ],
    input_boundary: "",
    output_boundary: "",
    stop_conditions: ["result_ready"],
    required_evidence_refs: [],
    output_contract_id: "TaskOutput",
    prompt: "",
    enabled: true,
    metadata: { managed_by: "task_system_console" }
  });
}

function workflowPayload(draft: WorkflowDraft): TaskWorkflowRecord {
  return {
    workflow_id: draft.workflow_id,
    title: draft.title,
    task_mode: draft.task_mode,
    default_projection_id: draft.default_projection_id,
    allowed_projection_ids: splitList(draft.allowed_projection_ids_text || draft.default_projection_id),
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
      setGeneralDraft(emptyGeneralTask(workflows[0]?.workflow_id ?? "", projections[0]?.projection_id ?? ""));
    }
  }, [selectedGeneralTask, workflows, projections]);

  useEffect(() => {
    if (selectedSpecificTask) {
      setSpecificTaskDraft(specificTaskDraftFrom(selectedSpecificTask));
    } else {
      setSpecificTaskDraft(emptySpecificTask(workflows[0]?.workflow_id ?? "", projections[0]?.projection_id ?? ""));
    }
  }, [selectedSpecificTask, workflows, projections]);

  useEffect(() => {
    if (selectedWorkflow) {
      setWorkflowDraft(workflowDraftFrom(selectedWorkflow));
    } else {
      setWorkflowDraft(emptyWorkflow(projections[0]?.projection_id ?? ""));
    }
  }, [selectedWorkflow, projections]);

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
        default_projection_id: generalDraft.default_projection_id || workflow.default_projection_id,
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
        projection_id: specificTaskDraft.projection_id || workflow.default_projection_id,
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

      <section className="task-system-hero">
        <article>
          <span>Agent Registry</span>
          <strong>{consoleData?.summary.agent_count ?? 0}</strong>
          <p>任务执行者统一登记，不再把系统和 Agent 混成一团。</p>
        </article>
        <article>
          <span>Specific Tasks</span>
          <strong>{consoleData?.summary.specific_task_count ?? 0}</strong>
          <p>特定任务通过 Agent、workflow、projection 和契约组合稳定消费。</p>
        </article>
        <article>
          <span>Workflow Resources</span>
          <strong>{consoleData?.summary.workflow_count ?? 0}</strong>
          <p>workflow 归任务系统所有，作为任务资源服务于任务绑定。</p>
        </article>
      </section>

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
        <section className="task-system-control-grid">
          <aside className="task-system-control-panel">
            <nav className="task-system-switcher">
              <button className={taskModeTab === "general" ? "task-system-switcher__item task-system-switcher__item--active" : "task-system-switcher__item"} onClick={() => setTaskModeTab("general")} type="button">通用任务</button>
              <button className={taskModeTab === "specific" ? "task-system-switcher__item task-system-switcher__item--active" : "task-system-switcher__item"} onClick={() => setTaskModeTab("specific")} type="button">特定任务</button>
            </nav>
            <div className="task-system-flow-tabs">
              {(taskModeTab === "general" ? taskManagement?.general_tasks ?? [] : taskManagement?.specific_tasks ?? []).map((item) => {
                const id = taskModeTab === "general" ? (item as GeneralTaskProfile).profile_id : (item as TaskAssignment).task_id;
                const title = taskModeTab === "general" ? (item as GeneralTaskProfile).title : (item as TaskAssignment).task_title;
                const active = taskModeTab === "general" ? selectedGeneralId === id : selectedSpecificTaskId === id;
                return (
                  <button className={active ? "task-system-flow-tab task-system-flow-tab--active" : "task-system-flow-tab"} key={id} onClick={() => taskModeTab === "general" ? setSelectedGeneralId(id) : setSelectedSpecificTaskId(id)} type="button">
                    <Workflow size={14} />
                    <span>{title}</span>
                    <Badge value={item.enabled ? "enabled" : "disabled"} />
                  </button>
                );
              })}
            </div>
          </aside>

          <main className="task-system-control-panel">
            <PanelHead
              title={taskModeTab === "general" ? "通用任务" : "特定任务"}
              description={taskModeTab === "general" ? "通用任务作为主会话默认承接配置，不要求用户显式选择。" : "特定任务登记任务契约、承接 Agent 与投影绑定，用于稳定消费。"}
              action={
                <button className="action-button action-button--primary" disabled={Boolean(saving)} onClick={() => taskModeTab === "general" ? void saveGeneralTask() : void saveSpecificTask()} type="button">
                  <Save size={14} />
                  保存任务
                </button>
              }
            />
            {taskModeTab === "general" ? (
              <div className="task-system-form-grid">
                <label><span>Profile ID</span><input value={generalDraft.profile_id} onChange={(event) => setGeneralDraft((value) => ({ ...value, profile_id: event.target.value }))} /></label>
                <label><span>标题</span><input value={generalDraft.title} onChange={(event) => setGeneralDraft((value) => ({ ...value, title: event.target.value }))} /></label>
                <label><span>默认 Agent</span><input readOnly value={generalDraft.default_agent_id} /></label>
                <ProjectionPicker label="任务投影" projectionId={generalDraft.default_projection_id} projections={projections} onChange={(projectionId) => setGeneralDraft((value) => ({ ...value, default_projection_id: projectionId }))} />
                <label><span>Input Contract</span><input value={generalDraft.input_contract_id} onChange={(event) => setGeneralDraft((value) => ({ ...value, input_contract_id: event.target.value }))} /></label>
                <label><span>Output Contract</span><input value={generalDraft.output_contract_id} onChange={(event) => setGeneralDraft((value) => ({ ...value, output_contract_id: event.target.value }))} /></label>
                <label><span>对话入口策略</span><input value={generalDraft.conversation_entry_policy} onChange={(event) => setGeneralDraft((value) => ({ ...value, conversation_entry_policy: event.target.value }))} /></label>
                <label className="task-system-checkbox"><input checked={generalDraft.enabled} onChange={(event) => setGeneralDraft((value) => ({ ...value, enabled: event.target.checked }))} type="checkbox" />启用通用任务</label>
              </div>
            ) : (
              <div className="task-system-form-grid">
                <label><span>Task ID</span><input value={specificTaskDraft.task_id} onChange={(event) => setSpecificTaskDraft((value) => ({ ...value, task_id: event.target.value, flow_id: `flow.${slug(event.target.value.replace(/^task\./, ""))}` }))} /></label>
                <label><span>标题</span><input value={specificTaskDraft.task_title} onChange={(event) => setSpecificTaskDraft((value) => ({ ...value, task_title: event.target.value }))} /></label>
                <label><span>Task Family</span><input value={specificTaskDraft.task_family} onChange={(event) => setSpecificTaskDraft((value) => ({ ...value, task_family: event.target.value }))} /></label>
                <label><span>Task Mode</span><input value={specificTaskDraft.task_mode} onChange={(event) => setSpecificTaskDraft((value) => ({ ...value, task_mode: event.target.value }))} /></label>
                <label><span>承接 Agent</span><select value={specificTaskDraft.default_agent_id} onChange={(event) => setSpecificTaskDraft((value) => ({ ...value, default_agent_id: event.target.value }))}>{allAgents.map((agent) => <option key={agent.agent_id} value={agent.agent_id}>{agent.agent_name}</option>)}</select></label>
                <ProjectionPicker label="任务投影" projectionId={specificTaskDraft.projection_id} projections={projections} onChange={(projectionId) => setSpecificTaskDraft((value) => ({ ...value, projection_id: projectionId }))} />
                <label><span>Input Contract</span><input value={specificTaskDraft.input_contract_id} onChange={(event) => setSpecificTaskDraft((value) => ({ ...value, input_contract_id: event.target.value }))} /></label>
                <label><span>Output Contract</span><input value={specificTaskDraft.output_contract_id} onChange={(event) => setSpecificTaskDraft((value) => ({ ...value, output_contract_id: event.target.value }))} /></label>
                <label className="task-system-form-grid__full"><span>触发信号</span><textarea value={specificTaskDraft.trigger_signals_text} onChange={(event) => setSpecificTaskDraft((value) => ({ ...value, trigger_signals_text: event.target.value }))} /></label>
                <label className="task-system-form-grid__full"><span>任务备注</span><textarea value={specificTaskDraft.notes} onChange={(event) => setSpecificTaskDraft((value) => ({ ...value, notes: event.target.value }))} /></label>
                <label className="task-system-checkbox"><input checked={specificTaskDraft.enabled} onChange={(event) => setSpecificTaskDraft((value) => ({ ...value, enabled: event.target.checked }))} type="checkbox" />启用特定任务</label>
              </div>
            )}
          </main>

          <aside className="task-system-control-panel">
            <PanelHead title="Workflow 资源" description="workflow 作为任务资源登记，供通用任务和特定任务绑定调用。" action={<button className="action-button action-button--ghost" onClick={() => setWorkflowDraft(emptyWorkflow(projections[0]?.projection_id ?? ""))} type="button"><Plus size={14} />新 workflow</button>} />
            <WorkflowEditor draft={workflowDraft} projections={projections} onChange={setWorkflowDraft} />
          </aside>
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

function WorkflowEditor({
  draft,
  projections,
  onChange
}: {
  draft: WorkflowDraft;
  projections: SoulProjectionCard[];
  onChange: (draft: WorkflowDraft) => void;
}) {
  return (
    <div className="task-system-form-grid">
      <label><span>Workflow ID</span><input value={draft.workflow_id} onChange={(event) => onChange({ ...draft, workflow_id: event.target.value })} /></label>
      <label><span>标题</span><input value={draft.title} onChange={(event) => onChange({ ...draft, title: event.target.value })} /></label>
      <label><span>Task Mode</span><input value={draft.task_mode} onChange={(event) => onChange({ ...draft, task_mode: event.target.value })} /></label>
      <ProjectionPicker label="默认投影" projectionId={draft.default_projection_id} projections={projections} onChange={(projectionId) => onChange({ ...draft, default_projection_id: projectionId, allowed_projection_ids_text: draft.allowed_projection_ids_text || projectionId })} />
      <label className="task-system-form-grid__full"><span>Workflow Prompt</span><textarea value={draft.prompt} onChange={(event) => onChange({ ...draft, prompt: event.target.value })} /></label>
      <label className="task-system-form-grid__full"><span>步骤</span><textarea value={draft.steps_text} onChange={(event) => onChange({ ...draft, steps_text: event.target.value })} /></label>
      <label><span>Visible Skills</span><textarea value={draft.visible_skill_ids_text} onChange={(event) => onChange({ ...draft, visible_skill_ids_text: event.target.value })} /></label>
      <label><span>Stop Conditions</span><textarea value={draft.stop_conditions_text} onChange={(event) => onChange({ ...draft, stop_conditions_text: event.target.value })} /></label>
      <label><span>Input Boundary</span><textarea value={draft.input_boundary} onChange={(event) => onChange({ ...draft, input_boundary: event.target.value })} /></label>
      <label><span>Output Boundary</span><textarea value={draft.output_boundary} onChange={(event) => onChange({ ...draft, output_boundary: event.target.value })} /></label>
      <label><span>Output Contract</span><input value={draft.output_contract_id} onChange={(event) => onChange({ ...draft, output_contract_id: event.target.value })} /></label>
      <label className="task-system-checkbox"><input checked={draft.enabled} onChange={(event) => onChange({ ...draft, enabled: event.target.checked })} type="checkbox" />启用 workflow</label>
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
