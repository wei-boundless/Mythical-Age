"use client";

import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  ClipboardList,
  FileJson,
  Layers3,
  ListChecks,
  Loader2,
  Plus,
  RefreshCw,
  Save,
  Search,
  ShieldCheck,
  UserCog,
  Workflow
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  getProjectionTemplates,
  getSkillWorkflows,
  getTaskSystemOverview,
  upsertTaskSystemAgent,
  upsertTaskSystemAssignment,
  upsertTaskSystemGeneralProfile,
  type AgentTaskCarryingProfile,
  type AgentTaskConnectionProfile,
  type GeneralTaskProfile,
  type GeneralTaskProfileUpsertPayload,
  type ProjectionTemplateCatalog,
  type SkillWorkflowCatalog,
  type TaskAssignment,
  type TaskAssignmentUpsertPayload,
  type TaskSystemAgentUpsertPayload,
  type TaskSystemOverview
} from "@/lib/api";

type TaskPage = "general" | "specific" | "agents" | "diagnostics";

type AgentDraft = {
  agent_id: string;
  display_name: string;
  owner_system: string;
  profile_type: string;
  lifecycle_state: string;
  default_soul_id: string;
  default_projection_template_id: string;
};

const EMPTY_ROWS: Array<Record<string, unknown>> = [];
const EMPTY_PROFILES: AgentTaskConnectionProfile[] = [];
const EMPTY_CARRYING: AgentTaskCarryingProfile[] = [];
const AGENT_TYPE_OPTIONS = [
  { value: "main_agent", label: "主 Agent", description: "对话入口、通用任务、分派与最终整合。" },
  { value: "system_management_agent", label: "系统管理 Agent", description: "承接系统治理、诊断、维护类特定任务。" },
  { value: "worker_sub_agent", label: "工作子 Agent", description: "承接检索、加工、生成等具体工作任务。" }
];

function text(value: unknown, fallback = "-") {
  if (Array.isArray(value)) return value.length ? value.join(" / ") : fallback;
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

function slug(value: string) {
  return value.trim().toLowerCase().replace(/[^a-z0-9_:-]+/g, "_").replace(/^_+|_+$/g, "");
}

function asList(value: unknown): string[] {
  if (Array.isArray(value)) return value.map((item) => String(item)).filter(Boolean);
  if (!value) return [];
  return [String(value)];
}

function agentTypeLabel(value: unknown) {
  const normalized = String(value || "");
  return AGENT_TYPE_OPTIONS.find((item) => item.value === normalized)?.label ?? (normalized || "-");
}

function badgeClass(value: unknown) {
  const normalized = String(value || "").toLowerCase();
  if (["valid", "enabled", "ready", "system_builtin", "true"].includes(normalized)) return "task-system-badge task-system-badge--ok";
  if (["invalid", "disabled", "blocked", "missing", "false"].includes(normalized)) return "task-system-badge task-system-badge--danger";
  if (["unbound", "unchecked", "draft"].includes(normalized)) return "task-system-badge task-system-badge--warn";
  return "task-system-badge";
}

function Badge({ value }: { value: unknown }) {
  return <span className={badgeClass(value)}>{text(value)}</span>;
}

function emptyAgentDraft(): AgentDraft {
  return {
    agent_id: "agent:task:new_agent",
    display_name: "新任务 Agent",
    owner_system: "task_system",
    profile_type: "worker_sub_agent",
    lifecycle_state: "enabled",
    default_soul_id: "",
    default_projection_template_id: ""
  };
}

function agentDraftFrom(agent: Record<string, unknown>): AgentDraft {
  return {
    agent_id: text(agent.agent_id, "agent:task:new_agent"),
    display_name: text(agent.display_name, ""),
    owner_system: text(agent.owner_system, "task_system"),
    profile_type: text(agent.profile_type, "worker_sub_agent"),
    lifecycle_state: text(agent.lifecycle_state, "enabled"),
    default_soul_id: text(agent.default_soul_id, ""),
    default_projection_template_id: text(agent.default_projection_template_id, "")
  };
}

function emptyGeneralProfile(workflowId = "", projectionId = ""): GeneralTaskProfile {
  return {
    profile_id: "general.conversation.default",
    title: "通用对话任务",
    default_agent_id: "agent:main",
    default_workflow_id: workflowId,
    default_projection_template_id: projectionId,
    input_contract_id: "UserMessage",
    output_contract_id: "AssistantFinalAnswer",
    conversation_entry_policy: "user_dialogue_to_main_agent",
    enabled: true,
    metadata: { managed_by: "task_system_console" }
  };
}

function emptyAssignment(workflowId = "", projectionId = ""): TaskAssignment {
  return {
    task_id: "task.custom.new_task",
    task_title: "新特定任务",
    task_kind: "specific_task",
    task_family: "custom",
    task_mode: "custom_task",
    flow_id: "flow.custom.new_task",
    default_agent_id: "agent:main",
    participant_agent_ids: [],
    workflow_id: workflowId,
    workflow_file_ref: workflowId ? `workflow:${workflowId}` : "",
    projection_template_id: projectionId,
    input_contract_id: "TaskInput",
    output_contract_id: "TaskOutput",
    task_structure: {
      runtime_lane_hint: "",
      memory_scope_hint: "",
      structure_mode: "single_agent_default"
    },
    enabled: true,
    metadata: { managed_by: "task_system_console" }
  };
}

export function TaskSystemView() {
  const [overview, setOverview] = useState<TaskSystemOverview | null>(null);
  const [workflows, setWorkflows] = useState<SkillWorkflowCatalog | null>(null);
  const [projections, setProjections] = useState<ProjectionTemplateCatalog | null>(null);
  const [activePage, setActivePage] = useState<TaskPage>("general");
  const [selectedGeneralId, setSelectedGeneralId] = useState("");
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [generalDraft, setGeneralDraft] = useState<GeneralTaskProfile>(emptyGeneralProfile());
  const [assignmentDraft, setAssignmentDraft] = useState<TaskAssignment>(emptyAssignment());
  const [agentDraft, setAgentDraft] = useState<AgentDraft>(emptyAgentDraft());
  const [query, setQuery] = useState("");
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null);
  const [saving, setSaving] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [taskPayload, workflowPayload, projectionPayload] = await Promise.all([
        getTaskSystemOverview(),
        getSkillWorkflows(),
        getProjectionTemplates()
      ]);
      setOverview(taskPayload);
      setWorkflows(workflowPayload);
      setProjections(projectionPayload);
      setSelectedGeneralId((current) => current || taskPayload.general_task_profiles?.[0]?.profile_id || "");
      setSelectedTaskId((current) => current || taskPayload.task_assignments?.[0]?.task_id || "");
      setSelectedAgentId((current) => current || String(taskPayload.agents[0]?.agent_id || ""));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "任务系统加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const agents = overview?.agents ?? EMPTY_ROWS;
  const generalProfiles = overview?.general_task_profiles ?? [];
  const assignments = overview?.task_assignments ?? [];
  const bindings = overview?.bindings ?? EMPTY_ROWS;
  const connectionProfiles = overview?.agent_task_connections?.profiles ?? EMPTY_PROFILES;
  const carryingProfiles = overview?.agent_carrying_profiles?.profiles ?? EMPTY_CARRYING;
  const diagnosticIssues = overview?.connection_diagnostics?.issues ?? [];
  const workflowRows = workflows?.workflows ?? EMPTY_ROWS;
  const projectionRows = projections?.templates ?? EMPTY_ROWS;

  const workflowById = useMemo(() => new Map(workflowRows.map((item) => [String(item.workflow_id), item])), [workflowRows]);
  const agentById = useMemo(() => new Map(agents.map((item) => [String(item.agent_id), item])), [agents]);
  const selectedGeneral = generalProfiles.find((item) => item.profile_id === selectedGeneralId) ?? generalProfiles[0] ?? null;
  const selectedAssignment = assignments.find((item) => item.task_id === selectedTaskId) ?? assignments[0] ?? null;
  const selectedAgent = agents.find((item) => item.agent_id === selectedAgentId) ?? null;
  const selectedCarrying = carryingProfiles.find((item) => item.agent_id === selectedAgentId) ?? null;
  const selectedConnection = connectionProfiles.find((item) => item.agent_id === selectedAgentId) ?? null;
  const selectedGeneralWorkflow = workflowById.get(generalDraft.default_workflow_id) ?? null;
  const selectedAssignmentWorkflow = workflowById.get(assignmentDraft.workflow_id) ?? null;
  const selectedAssignmentBinding = bindings.find((item) => item.flow_id === assignmentDraft.flow_id) ?? {};

  const mainAgents = agents.filter((agent) => agent.profile_type === "main_agent");
  const systemAgents = agents.filter((agent) => agent.profile_type === "system_management_agent");
  const workerAgents = agents.filter((agent) => agent.profile_type === "worker_sub_agent");
  const workflowRefCount = new Set([
    ...generalProfiles.map((item) => item.default_workflow_id).filter(Boolean),
    ...assignments.map((item) => item.workflow_id).filter(Boolean)
  ]).size;

  useEffect(() => {
    setGeneralDraft(selectedGeneral ?? emptyGeneralProfile(text(workflowRows[0]?.workflow_id, ""), text(projectionRows[0]?.template_id, "")));
  }, [selectedGeneral, workflowRows, projectionRows]);

  useEffect(() => {
    setAssignmentDraft(selectedAssignment ?? emptyAssignment(text(workflowRows[0]?.workflow_id, ""), text(projectionRows[0]?.template_id, "")));
  }, [selectedAssignment, workflowRows, projectionRows]);

  useEffect(() => {
    if (selectedAgent) setAgentDraft(agentDraftFrom(selectedAgent));
  }, [selectedAgent]);

  async function saveGeneralProfile() {
    setSaving("general");
    setError("");
    setNotice("");
    const payload: GeneralTaskProfileUpsertPayload = {
      ...generalDraft,
      default_agent_id: "agent:main",
      metadata: { ...(generalDraft.metadata ?? {}), managed_by: "task_system_console" }
    };
    try {
      const next = await upsertTaskSystemGeneralProfile(payload.profile_id, payload);
      setOverview(next);
      setSelectedGeneralId(payload.profile_id);
      setNotice(`${payload.title || payload.profile_id} 已保存。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存通用任务失败");
    } finally {
      setSaving("");
    }
  }

  async function saveAssignment() {
    setSaving("assignment");
    setError("");
    setNotice("");
    const payload: TaskAssignmentUpsertPayload = {
      ...assignmentDraft,
      workflow_file_ref: assignmentDraft.workflow_id ? `workflow:${assignmentDraft.workflow_id}` : "",
      metadata: { ...(assignmentDraft.metadata ?? {}), managed_by: "task_system_console" }
    };
    try {
      const next = await upsertTaskSystemAssignment(payload.task_id, payload);
      setOverview(next);
      setSelectedTaskId(payload.task_id);
      setNotice(`${payload.task_title || payload.task_id} 已保存。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存特定任务失败");
    } finally {
      setSaving("");
    }
  }

  async function saveAgent() {
    setSaving("agent");
    setError("");
    setNotice("");
    const payload: TaskSystemAgentUpsertPayload = {
      ...agentDraft,
      governance_status: "task_managed",
      metadata: { managed_by: "task_system_console" }
    };
    try {
      const next = await upsertTaskSystemAgent(agentDraft.agent_id, payload);
      setOverview(next);
      setSelectedAgentId(agentDraft.agent_id);
      setNotice(`${agentDraft.display_name || agentDraft.agent_id} 已保存。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存 Agent 失败");
    } finally {
      setSaving("");
    }
  }

  function setAssignmentWorkflow(workflowId: string) {
    const workflow = workflowById.get(workflowId);
    setAssignmentDraft((value) => ({
      ...value,
      workflow_id: workflowId,
      workflow_file_ref: workflowId ? `workflow:${workflowId}` : "",
      task_mode: workflow ? text(workflow.task_mode, value.task_mode) : value.task_mode,
      output_contract_id: workflow ? text(workflow.output_contract_id, value.output_contract_id) : value.output_contract_id
    }));
  }

  function toggleParticipant(agentId: string) {
    setAssignmentDraft((value) => {
      const current = new Set(value.participant_agent_ids);
      if (current.has(agentId)) current.delete(agentId);
      else current.add(agentId);
      current.delete(value.default_agent_id);
      return { ...value, participant_agent_ids: Array.from(current) };
    });
  }

  return (
    <div className="workspace-view task-system-view">
      <header className="workspace-view__header">
        <div>
          <p className="workspace-view__eyebrow">Task Assignment Hub</p>
          <h2 className="workspace-view__title">任务系统中枢</h2>
          <p className="workspace-view__subtitle">管理通用任务、特定任务、Agent 承载关系，以及 Task 到 Agent 到 Workflow 的分配。Workflow 本体仍归操作系统。</p>
        </div>
        <div className="workspace-view__actions">
          <button className="action-button" disabled={loading} onClick={() => void load()} type="button">
            {loading ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
            刷新
          </button>
        </div>
      </header>

      {error ? <div className="workspace-alert workspace-alert--danger"><AlertTriangle size={16} /> {error}</div> : null}
      {notice ? <div className="workspace-alert">{notice}</div> : null}
      {loading ? <div className="workspace-alert"><Loader2 className="spin" size={16} /> 正在加载任务系统中枢...</div> : null}

      <section className="task-system-hero task-system-hero--wide">
        <article><span>Agent</span><strong>{overview?.summary.agent_count ?? "-"}</strong><p>主 Agent、系统管理 Agent、工作子 Agent 的组织身份。</p></article>
        <article><span>通用任务</span><strong>{generalProfiles.length || "-"}</strong><p>用户通过对话交给主 Agent 的默认任务入口。</p></article>
        <article><span>特定任务</span><strong>{assignments.length || "-"}</strong><p>明确登记、可复用、可分配的任务结构。</p></article>
        <article><span>Workflow 引用</span><strong>{workflowRefCount || "-"}</strong><p>只读引用操作系统中的 Workflow 本体。</p></article>
      </section>

      <nav className="task-system-switcher task-system-switcher--four" aria-label="任务系统模块">
        {[
          { key: "general", label: "通用任务", icon: ClipboardList },
          { key: "specific", label: "特定任务", icon: Workflow },
          { key: "agents", label: "Agent 管理", icon: Bot },
          { key: "diagnostics", label: "连接诊断", icon: ShieldCheck }
        ].map((item) => {
          const Icon = item.icon;
          return (
            <button className={activePage === item.key ? "task-system-switcher__item task-system-switcher__item--active" : "task-system-switcher__item"} key={item.key} onClick={() => setActivePage(item.key as TaskPage)} type="button">
              <Icon size={15} />
              {item.label}
            </button>
          );
        })}
      </nav>

      {activePage === "general" ? (
        <section className="task-system-control-grid task-system-control-grid--two">
          <aside className="task-system-control-panel">
            <div className="task-system-section-head">
              <div><h3>通用任务入口</h3><p>通用任务默认由主 Agent 接住，不配置子 Agent。</p></div>
            </div>
            <div className="task-system-card-list">
              {generalProfiles.map((profile) => (
                <button className={generalDraft.profile_id === profile.profile_id ? "task-system-select-card task-system-select-card--active" : "task-system-select-card"} key={profile.profile_id} onClick={() => setSelectedGeneralId(profile.profile_id)} type="button">
                  <ClipboardList size={17} />
                  <strong>{profile.title}</strong>
                  <span>{profile.profile_id}</span>
                  <Badge value={profile.enabled ? "enabled" : "disabled"} />
                </button>
              ))}
            </div>
          </aside>

          <main className="task-system-control-panel">
            <div className="task-system-section-head">
              <div><h3>通用任务配置</h3><p>这里只配置主 Agent 如何承接用户对话任务，以及引用哪个 Workflow。</p></div>
              <button className="action-button action-button--primary" disabled={saving === "general"} onClick={() => void saveGeneralProfile()} type="button">
                {saving === "general" ? <Loader2 className="spin" size={14} /> : <Save size={14} />}
                保存通用任务
              </button>
            </div>
            <div className="task-system-form-grid">
              <label><span>Profile ID</span><input value={generalDraft.profile_id} onChange={(event) => setGeneralDraft((value) => ({ ...value, profile_id: event.target.value }))} /></label>
              <label><span>标题</span><input value={generalDraft.title} onChange={(event) => setGeneralDraft((value) => ({ ...value, title: event.target.value }))} /></label>
              <label><span>默认 Agent</span><input readOnly value="agent:main" /></label>
              <label>
                <span>默认 Workflow</span>
                <select value={generalDraft.default_workflow_id} onChange={(event) => setGeneralDraft((value) => ({ ...value, default_workflow_id: event.target.value }))}>
                  <option value="">未指定</option>
                  {workflowRows.map((workflow) => <option key={String(workflow.workflow_id)} value={String(workflow.workflow_id)}>{text(workflow.title, text(workflow.workflow_id))}</option>)}
                </select>
              </label>
              <label><span>Input Contract</span><input value={generalDraft.input_contract_id} onChange={(event) => setGeneralDraft((value) => ({ ...value, input_contract_id: event.target.value }))} /></label>
              <label><span>Output Contract</span><input value={generalDraft.output_contract_id} onChange={(event) => setGeneralDraft((value) => ({ ...value, output_contract_id: event.target.value }))} /></label>
              <label>
                <span>默认 Projection</span>
                <select value={generalDraft.default_projection_template_id} onChange={(event) => setGeneralDraft((value) => ({ ...value, default_projection_template_id: event.target.value }))}>
                  <option value="">未指定</option>
                  {projectionRows.map((projection) => <option key={String(projection.template_id)} value={String(projection.template_id)}>{text(projection.title, text(projection.template_id))}</option>)}
                </select>
              </label>
              <label className="task-system-checkbox"><input type="checkbox" checked={generalDraft.enabled} onChange={(event) => setGeneralDraft((value) => ({ ...value, enabled: event.target.checked }))} />启用通用任务入口</label>
            </div>
            <WorkflowSummary workflow={selectedGeneralWorkflow} />
          </main>
        </section>
      ) : null}

      {activePage === "specific" ? (
        <section className="task-system-control-grid">
          <aside className="task-system-control-panel">
            <div className="task-system-section-head">
              <div><h3>特定任务</h3><p>默认主 Agent 承接，也可以配置参与 Agent。</p></div>
              <button className="action-button action-button--ghost" onClick={() => {
                const draft = emptyAssignment(text(workflowRows[0]?.workflow_id, ""), text(projectionRows[0]?.template_id, ""));
                setAssignmentDraft(draft);
                setSelectedTaskId(draft.task_id);
              }} type="button">
                <Plus size={14} />
                新任务
              </button>
            </div>
            <label className="workspace-search">
              <Search size={16} />
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索任务、family、mode" />
            </label>
            <div className="task-system-card-list">
              {assignments.filter((item) => !query || JSON.stringify(item).toLowerCase().includes(query.toLowerCase())).map((task) => (
                <button className={assignmentDraft.task_id === task.task_id ? "task-system-select-card task-system-select-card--active" : "task-system-select-card"} key={task.task_id} onClick={() => setSelectedTaskId(task.task_id)} type="button">
                  <Workflow size={17} />
                  <strong>{task.task_title}</strong>
                  <span>{task.task_family} / {task.task_mode}</span>
                  <Badge value={task.enabled ? "enabled" : "disabled"} />
                </button>
              ))}
            </div>
          </aside>

          <main className="task-system-control-panel">
            <div className="task-system-section-head">
              <div><h3>任务分配</h3><p>任务系统只保存分配关系；Workflow 步骤与 Skill 组成在操作系统编辑。</p></div>
              <button className="action-button action-button--primary" disabled={saving === "assignment"} onClick={() => void saveAssignment()} type="button">
                {saving === "assignment" ? <Loader2 className="spin" size={14} /> : <Save size={14} />}
                保存特定任务
              </button>
            </div>
            <div className="task-system-form-grid">
              <label><span>Task ID</span><input value={assignmentDraft.task_id} onChange={(event) => setAssignmentDraft((value) => ({ ...value, task_id: event.target.value, flow_id: `flow.${slug(event.target.value.replace(/^task\./, ""))}` }))} /></label>
              <label><span>任务标题</span><input value={assignmentDraft.task_title} onChange={(event) => setAssignmentDraft((value) => ({ ...value, task_title: event.target.value }))} /></label>
              <label><span>Task Family</span><input value={assignmentDraft.task_family} onChange={(event) => setAssignmentDraft((value) => ({ ...value, task_family: event.target.value }))} /></label>
              <label><span>Task Mode</span><input value={assignmentDraft.task_mode} onChange={(event) => setAssignmentDraft((value) => ({ ...value, task_mode: event.target.value }))} /></label>
              <label><span>Flow ID</span><input value={assignmentDraft.flow_id} onChange={(event) => setAssignmentDraft((value) => ({ ...value, flow_id: event.target.value }))} /></label>
              <label>
                <span>引用 Workflow</span>
                <select value={assignmentDraft.workflow_id} onChange={(event) => setAssignmentWorkflow(event.target.value)}>
                  <option value="">未指定</option>
                  {workflowRows.map((workflow) => <option key={String(workflow.workflow_id)} value={String(workflow.workflow_id)}>{text(workflow.title, text(workflow.workflow_id))}</option>)}
                </select>
              </label>
              <label>
                <span>默认承接 Agent</span>
                <select value={assignmentDraft.default_agent_id} onChange={(event) => setAssignmentDraft((value) => ({ ...value, default_agent_id: event.target.value, participant_agent_ids: value.participant_agent_ids.filter((item) => item !== event.target.value) }))}>
                  {agents.map((agent) => <option key={String(agent.agent_id)} value={String(agent.agent_id)}>{text(agent.display_name, text(agent.agent_id))}</option>)}
                </select>
              </label>
              <label>
                <span>Projection</span>
                <select value={assignmentDraft.projection_template_id} onChange={(event) => setAssignmentDraft((value) => ({ ...value, projection_template_id: event.target.value }))}>
                  <option value="">未指定</option>
                  {projectionRows.map((projection) => <option key={String(projection.template_id)} value={String(projection.template_id)}>{text(projection.title, text(projection.template_id))}</option>)}
                </select>
              </label>
              <label><span>Input Contract</span><input value={assignmentDraft.input_contract_id} onChange={(event) => setAssignmentDraft((value) => ({ ...value, input_contract_id: event.target.value }))} /></label>
              <label><span>Output Contract</span><input value={assignmentDraft.output_contract_id} onChange={(event) => setAssignmentDraft((value) => ({ ...value, output_contract_id: event.target.value }))} /></label>
              <label className="task-system-checkbox"><input type="checkbox" checked={assignmentDraft.enabled} onChange={(event) => setAssignmentDraft((value) => ({ ...value, enabled: event.target.checked }))} />启用这个特定任务</label>
            </div>
            <div className="task-system-participant-grid">
              <div className="task-system-section-head"><div><h3>参与 Agent</h3><p>默认 Agent 之外，可配置系统管理 Agent 或工作子 Agent 参与任务结构。</p></div></div>
              <div className="task-system-chip-grid">
                {agents.filter((agent) => agent.agent_id !== assignmentDraft.default_agent_id).map((agent) => (
                  <button className={assignmentDraft.participant_agent_ids.includes(String(agent.agent_id)) ? "task-system-agent-chip task-system-agent-chip--active" : "task-system-agent-chip"} key={String(agent.agent_id)} onClick={() => toggleParticipant(String(agent.agent_id))} type="button">
                    <Bot size={14} />
                    <span>{text(agent.display_name, text(agent.agent_id))}</span>
                    <small>{agentTypeLabel(agent.profile_type)}</small>
                  </button>
                ))}
              </div>
            </div>
          </main>

          <aside className="task-system-control-panel">
            <WorkflowSummary workflow={selectedAssignmentWorkflow} />
            <div className="task-system-diagnostics">
              <DiagnosticRow label="Binding" value={text(selectedAssignmentBinding.validation_state, "unchecked")} ok={selectedAssignmentBinding.validation_state === "valid"} />
              <DiagnosticRow label="Workflow 引用" value={assignmentDraft.workflow_id || "missing"} ok={Boolean(assignmentDraft.workflow_id)} />
              <DiagnosticRow label="默认 Agent" value={assignmentDraft.default_agent_id || "missing"} ok={Boolean(agentById.get(assignmentDraft.default_agent_id))} />
              <DiagnosticRow label="编排授权" value="待编排系统确认" ok={false} />
            </div>
          </aside>
        </section>
      ) : null}

      {activePage === "agents" ? (
        <section className="task-system-control-grid task-system-control-grid--two">
          <aside className="task-system-control-panel">
            <div className="task-system-section-head">
              <div><h3>Agent 卡片</h3><p>点击卡片进入 Agent 编辑，管理组织身份和任务承载。</p></div>
              <button className="action-button action-button--ghost" onClick={() => {
                const draft = emptyAgentDraft();
                setAgentDraft(draft);
                setSelectedAgentId(draft.agent_id);
              }} type="button">
                <Plus size={14} />
                新 Agent
              </button>
            </div>
            <AgentCardGroup title="主 Agent" agents={mainAgents} carryingProfiles={carryingProfiles} selectedAgentId={selectedAgentId} onSelect={setSelectedAgentId} />
            <AgentCardGroup title="系统管理 Agent" agents={systemAgents} carryingProfiles={carryingProfiles} selectedAgentId={selectedAgentId} onSelect={setSelectedAgentId} />
            <AgentCardGroup title="工作子 Agent" agents={workerAgents} carryingProfiles={carryingProfiles} selectedAgentId={selectedAgentId} onSelect={setSelectedAgentId} />
          </aside>

          <main className="task-system-control-panel">
            <div className="task-system-section-head">
              <div><h3>Agent 编辑</h3><p>这里只编辑组织身份和任务承载视图；运行权限在编排系统。</p></div>
              <button className="action-button action-button--primary" disabled={saving === "agent"} onClick={() => void saveAgent()} type="button">
                {saving === "agent" ? <Loader2 className="spin" size={14} /> : <Save size={14} />}
                保存 Agent
              </button>
            </div>
            <div className="task-system-form-grid">
              <label><span>Agent ID</span><input value={agentDraft.agent_id} onChange={(event) => setAgentDraft((value) => ({ ...value, agent_id: event.target.value }))} /></label>
              <label><span>显示名称</span><input value={agentDraft.display_name} onChange={(event) => setAgentDraft((value) => ({ ...value, display_name: event.target.value }))} /></label>
              <label><span>Owner System</span><input value={agentDraft.owner_system} onChange={(event) => setAgentDraft((value) => ({ ...value, owner_system: event.target.value }))} /></label>
              <label>
                <span>Agent 分类</span>
                <select value={agentDraft.profile_type} onChange={(event) => setAgentDraft((value) => ({ ...value, profile_type: event.target.value }))}>
                  {AGENT_TYPE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
              </label>
              <label>
                <span>Lifecycle</span>
                <select value={agentDraft.lifecycle_state} onChange={(event) => setAgentDraft((value) => ({ ...value, lifecycle_state: event.target.value }))}>
                  <option value="enabled">enabled</option>
                  <option value="draft">draft</option>
                  <option value="disabled">disabled</option>
                </select>
              </label>
              <label><span>Soul ID</span><input value={agentDraft.default_soul_id} onChange={(event) => setAgentDraft((value) => ({ ...value, default_soul_id: event.target.value }))} /></label>
              <label>
                <span>默认 Projection</span>
                <select value={agentDraft.default_projection_template_id} onChange={(event) => setAgentDraft((value) => ({ ...value, default_projection_template_id: event.target.value }))}>
                  <option value="">未指定</option>
                  {projectionRows.map((projection) => <option key={String(projection.template_id)} value={String(projection.template_id)}>{text(projection.title, text(projection.template_id))}</option>)}
                </select>
              </label>
            </div>
            <section className="task-system-reference">
              <h3>任务承载</h3>
              <article><ClipboardList size={16} /><p><strong>通用任务</strong>{text(selectedCarrying?.carried_general_task_refs, "未承载")}</p></article>
              <article><Workflow size={16} /><p><strong>特定任务</strong>{text(selectedCarrying?.carried_specific_task_refs, "未承载")}</p></article>
              <article><Layers3 size={16} /><p><strong>Workflow 引用</strong>{text(selectedCarrying?.workflow_refs, "未绑定")}</p></article>
              <article><ShieldCheck size={16} /><p><strong>连接状态</strong>{text(selectedCarrying?.validation_state, "unbound")}</p></article>
            </section>
          </main>
        </section>
      ) : null}

      {activePage === "diagnostics" ? (
        <section className="task-system-control-grid task-system-control-grid--two">
          <main className="task-system-control-panel">
            <div className="task-system-section-head"><div><h3>连接诊断</h3><p>这里检查分配关系是否成立，不代表编排授权已经通过。</p></div></div>
            <div className="task-system-card-list">
              {diagnosticIssues.length ? diagnosticIssues.map((issue, index) => (
                <article className="task-system-diagnostic-card" key={`${issue.object_id}-${issue.reason}-${index}`}>
                  <AlertTriangle size={16} />
                  <div>
                    <strong>{issue.object_id}</strong>
                    <span>{issue.object_type} · {issue.field}</span>
                    <p>{issue.reason}{issue.value ? `：${issue.value}` : ""}</p>
                  </div>
                  <Badge value={issue.severity} />
                </article>
              )) : <div className="task-system-empty">当前没有连接诊断问题。</div>}
            </div>
          </main>
          <aside className="task-system-control-panel">
            <div className="task-system-diagnostics">
              <DiagnosticRow label="无效 Agent 承载" value={overview?.agent_carrying_profiles?.summary.invalid_profile_count ?? 0} ok={(overview?.agent_carrying_profiles?.summary.invalid_profile_count ?? 0) === 0} />
              <DiagnosticRow label="无绑定 Agent" value={overview?.agent_carrying_profiles?.summary.unbound_profile_count ?? 0} ok={false} />
              <DiagnosticRow label="Invalid Binding" value={overview?.summary.invalid_binding_count ?? 0} ok={(overview?.summary.invalid_binding_count ?? 0) === 0} />
              <DiagnosticRow label="编排授权" value="由编排系统最终裁决" ok={false} />
            </div>
            <button className="action-button action-button--ghost" onClick={() => setDetail({ overview: overview?.summary, diagnostics: overview?.connection_diagnostics, selectedConnection })} type="button">
              <FileJson size={14} />
              查看诊断 JSON
            </button>
            {detail ? <pre className="task-system-json">{JSON.stringify(detail, null, 2)}</pre> : null}
          </aside>
        </section>
      ) : null}
    </div>
  );
}

function WorkflowSummary({ workflow }: { workflow: Record<string, unknown> | null }) {
  const steps = asList(workflow?.steps).length ? asList(workflow?.steps) : [];
  const rawSteps = Array.isArray(workflow?.steps) ? workflow?.steps as Array<Record<string, unknown>> : [];
  return (
    <section className="task-system-reference">
      <h3>Workflow 只读摘要</h3>
      {workflow ? (
        <>
          <article><Workflow size={16} /><p><strong>{text(workflow.title, text(workflow.workflow_id))}</strong>{text(workflow.workflow_id)}</p></article>
          <article><ClipboardList size={16} /><p><strong>Skills</strong>{text(workflow.visible_skill_ids, "未声明")}</p></article>
          <article><ListChecks size={16} /><p><strong>Steps</strong>{rawSteps.length ? rawSteps.map((item) => text(item.title, text(item.step_id))).join(" / ") : text(steps, "未声明")}</p></article>
          <article><ShieldCheck size={16} /><p><strong>Output</strong>{text(workflow.output_contract_id, text(workflow.output_boundary, "未声明"))}</p></article>
        </>
      ) : (
        <div className="task-system-empty">尚未选择 Workflow。Workflow 本体请在操作系统维护。</div>
      )}
    </section>
  );
}

function AgentCardGroup({
  title,
  agents,
  carryingProfiles,
  selectedAgentId,
  onSelect
}: {
  title: string;
  agents: Array<Record<string, unknown>>;
  carryingProfiles: AgentTaskCarryingProfile[];
  selectedAgentId: string;
  onSelect: (agentId: string) => void;
}) {
  return (
    <section className="task-system-agent-group">
      <div className="task-system-agent-group__head">
        <strong>{title}</strong>
        <span>{agents.length}</span>
      </div>
      <div className="task-system-agent-card-grid">
        {agents.map((agent) => {
          const agentId = String(agent.agent_id);
          const carrying = carryingProfiles.find((item) => item.agent_id === agentId);
          return (
            <button className={selectedAgentId === agentId ? "task-system-agent-card task-system-agent-card--active" : "task-system-agent-card"} key={agentId} onClick={() => onSelect(agentId)} type="button">
              <div className="task-system-agent-card__head">
                <div>
                  <div><Bot size={15} /><Badge value={carrying?.validation_state ?? "unbound"} /></div>
                  <h4>{text(agent.display_name, agentId)}</h4>
                  <p>{agentId}</p>
                </div>
                <UserCog size={17} />
              </div>
              <div className="task-system-agent-card__flows">
                {agentTypeLabel(agent.profile_type)} · {text(agent.owner_system)}
                <br />
                任务 {Number(carrying?.carried_general_task_refs.length ?? 0) + Number(carrying?.carried_specific_task_refs.length ?? 0)} / Workflow {carrying?.workflow_refs.length ?? 0}
              </div>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function DiagnosticRow({ label, value, ok }: { label: string; value: unknown; ok: boolean }) {
  return (
    <div className="task-system-diagnostic-row">
      <span>{label}</span>
      <strong className={ok ? "task-system-diagnostic-row--ok" : "task-system-diagnostic-row--warn"}>
        {ok ? <CheckCircle2 size={14} /> : <ShieldCheck size={14} />}
        {text(value)}
      </strong>
    </div>
  );
}
