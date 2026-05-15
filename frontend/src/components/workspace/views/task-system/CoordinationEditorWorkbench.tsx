"use client";

import {
  GitBranch,
  GitCommitHorizontal,
  RotateCcw,
  SquarePen,
  Trash2,
} from "lucide-react";
import { useState, type Dispatch, type MouseEvent, type ReactNode, type SetStateAction } from "react";

import {
  CoordinationTopologyGraph,
  type CoordinationTopologyEdge,
  type CoordinationTopologyFrame,
  type CoordinationTopologyNode,
} from "@/components/coordination/CoordinationTopologyGraph";
import { contractSpecTitle } from "@/components/workspace/views/task-system/ContractLibraryPanel";
import {
  TaskSystemDomainTaskSelectField,
  TaskSystemField,
  TaskSystemMultiSelectField,
  taskSystemDisplayLabel,
  taskSystemOptionLabel,
  TaskSystemSelectField,
  TaskSystemToolbarButton,
} from "@/components/workspace/views/task-system/TaskSystemWorkbenchUi";
import {
  coordinationPhaseDefinitions,
  coordinationTimelineFrames,
  nodeLoopPolicy,
  nodePhaseId,
  nodeReviewGatePolicy,
  type TaskGraphTimelineFrame,
} from "@/components/workspace/views/task-system/taskGraphTimeline";
import type { TaskGraphTemplateId } from "@/components/workspace/views/task-system/taskGraphTemplates";
import type {
  ConversationEntryPolicy,
  ContractSpec,
  CoordinationGraphSpec,
  SpecificTaskRecord,
  TaskGraphRecord,
  TaskSystemOverview,
  TaskDomainRecord,
  TaskCommunicationProtocol,
  TopologyTemplate,
} from "@/lib/api";

type DomainRecordLike = TaskDomainRecord & {
  task_modes: string[];
  tasks: SpecificTaskRecord[];
  entry_policy: ConversationEntryPolicy | null;
};

type CoordinationDraftLike = {
  coordination_task_id: string;
  title: string;
  coordination_mode: string;
  coordinator_agent_id: string;
  task_family?: string;
  domain_id?: string;
  agent_group_id?: string;
  participant_agent_ids: string[];
  topology_template_id: string;
  shared_context_policy: string;
  memory_sharing_policy: string;
  handoff_policy: string;
  conflict_resolution_policy: string;
  output_merge_policy: string;
  stop_conditions: string[];
  subtask_refs: string[];
  graph_nodes: Array<Record<string, unknown>>;
  graph_edges: Array<Record<string, unknown>>;
  communication_modes: string[];
  enabled: boolean;
  metadata?: Record<string, unknown>;
  stop_conditions_text: string;
};

type TopologyDraftLike = TopologyTemplate & {
  nodes_text: string;
  edges_text: string;
  handoff_rules_text: string;
};

type ProtocolDraftLike = TaskCommunicationProtocol & {
  message_types_text: string;
  payload_contracts_text: string;
  signal_rules_text: string;
  handoff_rules_text: string;
};
type PhaseDraft = {
  phase_id: string;
  title: string;
  entry_node_id?: string;
  exit_node_id?: string;
  review_gate_node_id?: string;
  memory_commit_node_id?: string;
  exit_policy?: Record<string, unknown>;
  loop_policy?: Record<string, unknown>;
};

type A2ACatalogLike = NonNullable<TaskSystemOverview["coordination_management"]["a2a"]>;
type ProjectionCardLike = { projection_id: string; title?: string; soul_name?: string; soul_id?: string };

const COORDINATION_MODE_CHOICES = ["review_merge", "pipeline", "parallel_review"];
const GRAPH_EDGE_MODE_CHOICES = ["structured_handoff", "review_feedback", "draft_request", "audit_request", "merge_signal"];
const NODE_EXECUTION_MODE_OPTIONS = ["sync", "async", "parallel", "background", "barrier", "manual_gate"];
const NODE_WAIT_POLICY_OPTIONS = ["wait_all_upstream_completed", "wait_any_upstream_completed", "wait_required_contracts", "wait_handoff_ack", "fire_and_continue", "manual_release"];
const NODE_JOIN_POLICY_OPTIONS = ["all_success", "any_success", "quorum", "coordinator_decides", "allow_partial_with_issues", "fail_on_any_error"];
const MECHANISM_CONSOLE_TABS = ["communication"] as const;
type MechanismConsoleTab = typeof MECHANISM_CONSOLE_TABS[number];
type MechanismDrawerType = "communication";
type MechanismTargetType = "edge" | "graph";
type MechanismDrawerState = {
  open: boolean;
  drawer_type: MechanismDrawerType;
  target_object_type: MechanismTargetType;
  target_object_id: string;
};
const DEFAULT_MECHANISM_DRAWER: MechanismDrawerState = {
  open: false,
  drawer_type: "communication",
  target_object_type: "graph",
  target_object_id: "",
};
type GraphSelection = {
  primary_object_id: string;
  primary_object_type: "node" | "edge" | "frame" | "";
  selected_node_ids: string[];
  selected_edge_ids: string[];
  selected_frame_ids: string[];
};
type GraphContextMenuState = {
  open: boolean;
  x: number;
  y: number;
  target_type: "canvas" | "node" | "edge" | "selection";
  target_id: string;
};
const EDGE_FAILURE_PROPAGATION_OPTIONS = ["fail_downstream", "isolate_failure", "coordinator_decides", "allow_partial"];
const EDGE_RESULT_DELIVERY_OPTIONS = ["contract_payload_and_refs", "refs_only", "summary_and_refs", "notification_only"];
const WORKING_MEMORY_KIND_OPTIONS = [
  "task_goal",
  "plan_fragment",
  "decision_record",
  "intermediate_result",
  "review_note",
  "conflict_flag",
  "handoff_context",
  "artifact_ref",
  "promotion_candidate",
  "genre_rule",
  "character_profile",
  "relationship_delta",
  "timeline_event",
  "progression_goal",
  "progression_check",
  "revised_chapter",
  "final_chapter",
  "revision_note",
  "style_note",
  "candidate_innovation",
  "accepted_innovation",
  "memory_candidate",
  "chapter_draft",
  "character_state_delta",
  "world_bible_delta",
];
const WORKING_MEMORY_SCOPE_OPTIONS = ["node_scope", "graph_scope", "task_scope", "edge_scope", "artifact_scope"];
const EDGE_MODE_TO_A2A_MESSAGE_TYPE: Record<string, string> = {
  structured_handoff: "message/send",
  review_feedback: "message/send",
  draft_request: "message/send",
  audit_request: "message/stream",
  merge_signal: "task/status",
};
const DEFAULT_A2A_PART_TYPES = ["text", "data", "file"];

function toPrettyJson(value: unknown) {
  return JSON.stringify(value, null, 2);
}

function a2aMessageTypeForEdge(edge: Record<string, unknown> | null, catalog: A2ACatalogLike | null) {
  const edgeMode = String(edge?.mode ?? "structured_handoff");
  const mapped = EDGE_MODE_TO_A2A_MESSAGE_TYPE[edgeMode] || "message/send";
  if (catalog?.message_types?.includes(mapped)) return mapped;
  return catalog?.message_types?.[0] || mapped;
}

function agentCardForNode(node: Record<string, unknown> | null, catalog: A2ACatalogLike | null) {
  const agentId = String(node?.agent_id ?? "").trim();
  if (!agentId || !catalog?.agent_cards?.length) return null;
  return catalog.agent_cards.find((card) => String(card.agent_id ?? "").trim() === agentId) ?? null;
}

function edgeA2APreview({
  edge,
  sourceNode,
  targetNode,
  protocolDraft,
  coordinationDraft,
  catalog,
}: {
  edge: Record<string, unknown> | null;
  sourceNode: Record<string, unknown> | null;
  targetNode: Record<string, unknown> | null;
  protocolDraft: ProtocolDraftLike;
  coordinationDraft: CoordinationDraftLike;
  catalog: A2ACatalogLike | null;
}) {
  if (!edge) return null;
  const messageType = a2aMessageTypeForEdge(edge, catalog);
  const payloadContracts = protocolDraft.payload_contracts_text
    .split(/[\n,，]/)
    .map((item) => item.trim())
    .filter(Boolean);
  return {
    protocol_version: catalog?.protocol_version || "0.3.0",
    transport: catalog?.transport || "JSONRPC",
    source_agent_id: String(sourceNode?.agent_id ?? ""),
    target_agent_id: String(targetNode?.agent_id ?? ""),
    source_node_id: String(sourceNode?.node_id ?? ""),
    target_node_id: String(targetNode?.node_id ?? ""),
    source_task_id: graphNodeTaskId(sourceNode ?? {}),
    target_task_id: graphNodeTaskId(targetNode ?? {}),
    edge_mode: String(edge.mode ?? "structured_handoff"),
    message_type: messageType,
    part_types: catalog?.part_types?.length ? catalog.part_types : DEFAULT_A2A_PART_TYPES,
    payload_contracts: payloadContracts,
    ack_policy: protocolDraft.ack_policy,
    timeout_policy: protocolDraft.timeout_policy,
    error_signal_policy: protocolDraft.error_signal_policy,
    shared_context_policy: coordinationDraft.shared_context_policy,
    handoff_policy: coordinationDraft.handoff_policy,
  };
}

function text(value: unknown, fallback = "-") {
  if (value === null || value === undefined || value === "") return fallback;
  if (Array.isArray(value)) return value.length ? value.join(" / ") : fallback;
  return String(value);
}

function mechanismConsoleTabLabel(value: MechanismConsoleTab) {
  const labels: Record<MechanismConsoleTab, string> = {
    communication: "通信",
  };
  return labels[value];
}

function mechanismConsoleTabDescription(value: MechanismConsoleTab) {
  const labels: Record<MechanismConsoleTab, string> = {
    communication: "边交接",
  };
  return labels[value];
}

function mechanismDrawerTitle(value: MechanismDrawerType) {
  const labels: Record<MechanismDrawerType, string> = {
    communication: "通信抽屉",
  };
  return labels[value];
}

function emptyGraphSelection(): GraphSelection {
  return {
    primary_object_id: "",
    primary_object_type: "",
    selected_node_ids: [],
    selected_edge_ids: [],
    selected_frame_ids: [],
  };
}

function toggleString(values: string[], value: string) {
  return values.includes(value) ? values.filter((item) => item !== value) : [...values, value];
}

function uniqueStrings(values: Array<string | null | undefined>) {
  return Array.from(new Set(values.map((item) => String(item ?? "").trim()).filter(Boolean)));
}

function displayId(value: unknown, fallback = "未配置") {
  const raw = String(value ?? "").trim();
  if (!raw) return fallback;
  const registeredLabel = taskSystemDisplayLabel(raw, fallback);
  if (registeredLabel !== raw) return registeredLabel;
  const labels: Record<string, string> = {
    bounded_patch: "受限补丁",
    review_merge: "审查汇总",
    pipeline: "流水推进",
    parallel_review: "并行审查",
    sync: "同步阻塞",
    async: "异步派发",
    parallel: "并行批次",
    background: "后台节点",
    barrier: "汇合节点",
    manual_gate: "人工门控",
    wait_all_upstream_completed: "等待全部上游完成",
    wait_any_upstream_completed: "等待任一上游完成",
    wait_required_contracts: "等待必需契约",
    wait_handoff_ack: "等待交接确认",
    fire_and_continue: "发出后继续",
    manual_release: "人工释放",
    all_success: "全部成功",
    any_success: "任一成功",
    quorum: "法定数量",
    coordinator_decides: "协调者裁决",
    allow_partial_with_issues: "允许带问题部分通过",
    fail_on_any_error: "任一失败即失败",
    fail_downstream: "失败传递到下游",
    isolate_failure: "隔离失败",
    allow_partial: "允许部分结果",
    contract_payload_and_refs: "契约载荷与引用",
    refs_only: "仅引用",
    summary_and_refs: "摘要与引用",
    notification_only: "仅通知",
  };
  return labels[raw] ? `${labels[raw]} · ${raw}` : taskSystemDisplayLabel(raw, fallback);
}

function roleLabel(value: unknown, fallback = "待分派") {
  const raw = String(value ?? "").trim();
  if (!raw) return fallback;
  const labels: Record<string, string> = {
    coordinator: "协调节点",
    participant: "协作节点",
    planner: "规划节点",
    executor: "执行节点",
    reviewer: "审查节点",
    verifier: "验证节点",
    summarizer: "整理节点",
    merge: "汇总节点",
    memory: "工作记忆",
    writer: "写作节点",
    acceptance: "验收节点",
    input: "输入节点",
    output: "输出节点",
    agent_role: "Agent 节点",
    subtask: "分任务节点",
    review_gate: "审核门",
  };
  return labels[raw] ?? raw;
}

function contractOptions(specs: ContractSpec[], current: string, kinds: string[]) {
  const allowed = kinds.length ? specs.filter((item) => kinds.includes(item.contract_kind)) : specs;
  return uniqueStrings([current, ...allowed.map((item) => item.contract_id)]);
}

function contractOptionLabel(specs: ContractSpec[]) {
  return (contractId: string) => {
    if (!contractId) return "不覆盖";
    const spec = specs.find((item) => item.contract_id === contractId);
    return spec ? `${contractSpecTitle(spec)} · ${contractId}` : contractId;
  };
}

function projectionOptions(cards: ProjectionCardLike[], current: string) {
  return uniqueStrings(["", current, ...cards.map((item) => String(item.projection_id ?? "")).filter(Boolean)]);
}

function projectionOptionLabel(cards: ProjectionCardLike[]) {
  return (projectionId: string) => {
    const value = String(projectionId || "").trim();
    if (!value) return "不绑定节点投影";
    const card = cards.find((item) => String(item.projection_id ?? "") === value);
    const owner = String(card?.soul_name || card?.soul_id || "").trim();
    return card?.title ? `${card.title}${owner ? ` · ${owner}` : ""} · ${value}` : value;
  };
}

function asStringList(value: unknown) {
  return Array.isArray(value) ? value.map((item) => String(item ?? "").trim()).filter(Boolean) : [];
}

function asRecord(value: unknown) {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function booleanValue(value: unknown, fallback = false) {
  if (typeof value === "boolean") return value;
  if (value === undefined || value === null || value === "") return fallback;
  return String(value).toLowerCase() === "true";
}

function updatePolicyList(
  base: Record<string, unknown>,
  key: string,
  value: string[],
) {
  return {
    ...base,
    [key]: value,
  };
}

function setMetadataValue(
  setter: Dispatch<SetStateAction<CoordinationDraftLike>>,
  key: string,
  value: unknown,
) {
  setter((current) => ({
    ...current,
    metadata: {
      ...asRecord(current.metadata),
      [key]: value,
    },
  }));
}

function setNestedMetadataValue(
  setter: Dispatch<SetStateAction<CoordinationDraftLike>>,
  key: string,
  patch: Record<string, unknown>,
) {
  setter((current) => {
    const metadata = asRecord(current.metadata);
    return {
      ...current,
      metadata: {
        ...metadata,
        [key]: {
          ...asRecord(metadata[key]),
          ...patch,
        },
      },
    };
  });
}

function phaseDraftsFromMetadata(metadata: Record<string, unknown>, nodes: Array<Record<string, unknown>>) {
  return coordinationPhaseDefinitions(metadata, nodes).map((phase): PhaseDraft => ({
    ...phase,
    exit_policy: asRecord(phase.exit_policy),
    loop_policy: asRecord(phase.loop_policy),
  }));
}

function updatePhaseDraft(
  phases: PhaseDraft[],
  phaseId: string,
  patch: Partial<PhaseDraft>,
) {
  return phases.map((phase) => (phase.phase_id === phaseId ? { ...phase, ...patch } : phase));
}

function nodeContractId(node: Record<string, unknown> | null) {
  return String(node?.node_contract_id ?? node?.contract_id ?? "").trim();
}

function edgeContractId(edge: Record<string, unknown> | null) {
  return String(edge?.payload_contract_id ?? edge?.contract_id ?? "").trim();
}

export function graphNodeLabel(node: Record<string, unknown>, index: number) {
  return text(node.label || node.task_title || node.title || roleLabel(node.role || node.agent_id, ""), `节点 ${index + 1}`);
}

export function graphNodeTaskId(node: Record<string, unknown>) {
  return String(node.task_id ?? node.subtask_ref ?? "").trim();
}

export function graphEdgeSource(edge: Record<string, unknown>) {
  return String(edge.from ?? edge.source_node_id ?? edge.source ?? "").trim();
}

export function graphEdgeTarget(edge: Record<string, unknown>) {
  return String(edge.to ?? edge.target_node_id ?? edge.target ?? "").trim();
}

export function graphEdgeId(edge: Record<string, unknown>, index = 0) {
  return String(edge.edge_id ?? edge.id ?? `${graphEdgeSource(edge)}-${graphEdgeTarget(edge)}-${index}`).trim();
}

function nodeIdOfGraphNode(node: Record<string, unknown>, index = 0) {
  return String(node.node_id ?? node.id ?? `node_${index + 1}`).trim();
}

function taskTitleById(taskId: string, tasks: SpecificTaskRecord[]) {
  const task = tasks.find((item) => item.task_id === taskId);
  return task?.task_title || displayId(taskId);
}

export function coordinationSubtaskRefs(draft: CoordinationDraftLike) {
  return uniqueStrings([
    ...((draft.graph_nodes ?? []).map((node) => graphNodeTaskId(node))),
  ]);
}

function CoordinationGraph({
  nodes,
  edges,
  frames,
  messages,
  tasks = [],
  selectedNodeId = "",
  selectedEdgeId = "",
  selection,
  linkingFromNodeId = "",
  renderNodeTools,
  renderEdgeTools,
  onSelectNode,
  onSelectEdge,
  onSelectFrame,
  onBoxSelect,
  onNodeContextMenu,
  onEdgeContextMenu,
  onCanvasContextMenu,
}: {
  nodes: Array<Record<string, unknown>>;
  edges: Array<Record<string, unknown>>;
  frames: TaskGraphTimelineFrame[];
  messages: string[];
  tasks?: SpecificTaskRecord[];
  selectedNodeId?: string;
  selectedEdgeId?: string;
  selection?: GraphSelection;
  linkingFromNodeId?: string;
  renderNodeTools?: (node: Record<string, unknown>, nodeId: string) => ReactNode;
  renderEdgeTools?: (edge: Record<string, unknown>, edgeId: string) => ReactNode;
  onSelectNode?: (nodeId: string, event?: MouseEvent<SVGGElement>) => void;
  onSelectEdge?: (edgeId: string, event?: MouseEvent<SVGPathElement>) => void;
  onSelectFrame?: (frameId: string, event?: MouseEvent<SVGGElement>) => void;
  onBoxSelect?: (selection: { nodeIds: string[]; edgeIds: string[] }) => void;
  onNodeContextMenu?: (nodeId: string, event: MouseEvent<SVGGElement>) => void;
  onEdgeContextMenu?: (edgeId: string, event: MouseEvent<SVGPathElement>) => void;
  onCanvasContextMenu?: (event: MouseEvent<SVGSVGElement>) => void;
}) {
  const safeNodes = nodes;
  const ids = safeNodes.map((node, index) => text(node.node_id || node.id || node.role || node.agent_id, `node_${index + 1}`));
  const resolvedEdges = edges.length
    ? edges
    : ids.length > 1
      ? ids.slice(1).map((id) => ({ from: ids[0], to: id, policy: "handoff" }))
      : [];
  const graphNodes = safeNodes.map((node, index): CoordinationTopologyNode => {
    const taskId = graphNodeTaskId(node);
    const nodeId = text(node.node_id || node.id, ids[index]);
    return {
      id: nodeId,
      title: taskId ? taskTitleById(taskId, tasks) : graphNodeLabel(node, index),
      agentLabel: String(node.node_type ?? "") === "memory" ? "工作记忆" : text(node.agent_id || roleLabel(node.role || node.node_type, ""), "待分派"),
      role: roleLabel(node.role || node.agent_category || node.node_type, "协作节点"),
      nodeKind: text(node.node_type || node.role, "agent"),
      status: nodeId === selectedNodeId ? "running" : "idle",
    };
  });
  const graphEdges = resolvedEdges
    .map((edge, index): CoordinationTopologyEdge | null => {
      const edgeRecord = edge as Record<string, unknown>;
      const from = graphEdgeSource(edge);
      const to = graphEdgeTarget(edge);
      if (!from || !to) return null;
      const edgeId = graphEdgeId(edge, index);
      return {
        id: edgeId,
        from,
        to,
        label: text(edgeRecord.mode || edgeRecord.policy || edgeRecord.label, "handoff"),
        status: edgeId === selectedEdgeId ? "running" : "idle",
      };
    })
    .filter((edge): edge is CoordinationTopologyEdge => Boolean(edge));
  const graphFrames = frames.map((frame): CoordinationTopologyFrame => ({
    id: frame.frame_id,
    title: frame.title || frame.frame_id,
    frameType: frame.frame_type,
    nodeIds: frame.node_ids,
    edgeIds: frame.edge_ids,
  }));

  return (
    <div className="boundary-graph boundary-graph--topology">
      <div className="boundary-graph__legend">
        {messages.length ? messages.slice(0, 6).map((item) => <span key={item}>{item}</span>) : <span>structured_handoff</span>}
      </div>
      <div className="coordination-topology-viewport coordination-topology-viewport--builder">
        <CoordinationTopologyGraph
          currentNodeId={selectedNodeId}
          edges={graphEdges}
          emptyDescription="先从左侧添加 Agent 节点，或在任务管理台加载一个任务图草案。连线需要点击上方“图上连线”后再选择目标节点。"
          emptyTitle="空画布"
          frames={graphFrames}
          linkingFromNodeId={linkingFromNodeId}
          nodes={graphNodes}
          onSelectEdge={onSelectEdge}
          onSelectFrame={onSelectFrame}
          onSelectNode={onSelectNode}
          onBoxSelect={onBoxSelect}
          onConnectNode={linkingFromNodeId ? onSelectNode : undefined}
          onNodeContextMenu={onNodeContextMenu}
          onEdgeContextMenu={onEdgeContextMenu}
          onCanvasContextMenu={onCanvasContextMenu}
          renderNodeTools={renderNodeTools ? (node) => {
            const rawNode = safeNodes.find((item) => String(item.node_id ?? item.id ?? "") === node.id) ?? {};
            return renderNodeTools(rawNode, node.id);
          } : undefined}
          renderEdgeTools={renderEdgeTools ? (edge) => {
            const rawEdge = resolvedEdges.find((item, index) => graphEdgeId(item as Record<string, unknown>, index) === edge.id) as Record<string, unknown> | undefined;
            return renderEdgeTools(rawEdge ?? {}, edge.id);
          } : undefined}
          selectedEdgeId={selectedEdgeId}
          selectedEdgeIds={selection?.selected_edge_ids ?? []}
          selectedFrameIds={selection?.selected_frame_ids ?? []}
          selectedNodeId={selectedNodeId}
          selectedNodeIds={selection?.selected_node_ids ?? []}
        />
      </div>
    </div>
  );
}

function CoordinationTaskPoolPanel({
  selectedDomainTasks,
  boundCoordinationTaskIds,
  addCoordinationTaskNode,
  addCoordinationRoleNode,
  addCoordinationNode,
  applyCoordinationGraphTemplate,
}: {
  selectedDomainTasks: SpecificTaskRecord[];
  boundCoordinationTaskIds: Set<string>;
  addCoordinationTaskNode: (task: SpecificTaskRecord, role?: string) => void;
  addCoordinationRoleNode: (role: string) => void;
  addCoordinationNode: () => void;
  applyCoordinationGraphTemplate: (template: TaskGraphTemplateId) => void;
}) {
  const [activePanel, setActivePanel] = useState<"nodes" | "templates" | "reuse">("nodes");
  return (
    <>
      <section className="boundary-inspector-block coordination-editor-toolbox">
        <header>
          <strong>构造面板</strong>
          <span>{activePanel === "nodes" ? "节点" : activePanel === "templates" ? "模板" : "复用"}</span>
        </header>
        <div className="coordination-editor-panel-tabs" role="tablist" aria-label="任务图构造面板">
          {[
            { value: "nodes", label: "节点" },
            { value: "templates", label: "模板" },
            { value: "reuse", label: "复用" },
          ].map((item) => (
            <button
              aria-selected={activePanel === item.value}
              className={activePanel === item.value ? "active" : ""}
              key={item.value}
              onClick={() => setActivePanel(item.value as "nodes" | "templates" | "reuse")}
              role="tab"
              type="button"
            >
              {item.label}
            </button>
          ))}
        </div>

        {activePanel === "nodes" ? (
          <div className="boundary-chip-grid">
            <button className="boundary-chip" onClick={() => addCoordinationRoleNode("coordinator")} type="button"><span>协调节点</span></button>
            <button className="boundary-chip" onClick={() => addCoordinationRoleNode("planner")} type="button"><span>规划节点</span></button>
            <button className="boundary-chip" onClick={() => addCoordinationRoleNode("executor")} type="button"><span>执行节点</span></button>
            <button className="boundary-chip" onClick={() => addCoordinationRoleNode("reviewer")} type="button"><span>审查节点</span></button>
            <button className="boundary-chip" onClick={() => addCoordinationRoleNode("verifier")} type="button"><span>验证节点</span></button>
            <button className="boundary-chip" onClick={() => addCoordinationRoleNode("merge")} type="button"><span>汇总节点</span></button>
            <button className="boundary-chip" onClick={() => addCoordinationRoleNode("memory")} type="button"><span>记忆节点</span></button>
            <button className="boundary-chip" onClick={addCoordinationNode} type="button"><span>空白 Agent 节点</span></button>
          </div>
        ) : null}

        {activePanel === "templates" ? (
          <div className="boundary-chip-grid">
            <button className="boundary-chip" onClick={() => applyCoordinationGraphTemplate("single_agent")} type="button"><span>单 Agent 执行图</span></button>
            <button className="boundary-chip" onClick={() => applyCoordinationGraphTemplate("multi_sequence")} type="button"><span>顺序协作图</span></button>
            <button className="boundary-chip" onClick={() => applyCoordinationGraphTemplate("multi_parallel_merge")} type="button"><span>并行汇总图</span></button>
          </div>
        ) : null}

        {activePanel === "reuse" ? (
          <div className="boundary-task-table coordination-reuse-list">
            {selectedDomainTasks.map((task) => (
              <article key={task.task_id}>
                <strong>{task.task_title}</strong>
                <span>{taskSystemOptionLabel(task.task_mode)}</span>
                <div className="coordination-editor-actions">
                  <button className="boundary-chip" disabled={boundCoordinationTaskIds.has(task.task_id)} onClick={() => addCoordinationTaskNode(task, "executor")} type="button">
                    <span>{boundCoordinationTaskIds.has(task.task_id) ? "已在图中" : "作为执行节点"}</span>
                  </button>
                  <button className="boundary-chip" disabled={boundCoordinationTaskIds.has(task.task_id)} onClick={() => addCoordinationTaskNode(task, "reviewer")} type="button">
                    <span>作为审查节点</span>
                  </button>
                </div>
              </article>
            ))}
            {!selectedDomainTasks.length ? <div className="boundary-empty">当前任务域暂无可复用任务。</div> : null}
          </div>
        ) : null}
      </section>
    </>
  );
}

function CoordinationMechanismConsole({
  activeTab,
  setActiveTab,
  nodes,
  edges,
  selectedEdgeId,
  onOpenDrawer,
}: {
  activeTab: MechanismConsoleTab;
  setActiveTab: (value: MechanismConsoleTab) => void;
  nodes: Array<Record<string, unknown>>;
  edges: Array<Record<string, unknown>>;
  selectedEdgeId: string;
  onOpenDrawer: (drawerType: MechanismDrawerType, targetType?: MechanismTargetType, targetId?: string) => void;
}) {
  return (
    <section className="coordination-mechanism-console" aria-label="任务图机制控制台">
      <nav className="coordination-mechanism-console__tabs" aria-label="机制控制台标签">
        {MECHANISM_CONSOLE_TABS.map((tab) => (
          <button
            className={activeTab === tab ? "coordination-mechanism-tab coordination-mechanism-tab--active" : "coordination-mechanism-tab"}
            key={tab}
            onClick={() => setActiveTab(tab)}
            type="button"
          >
            <strong>{mechanismConsoleTabLabel(tab)}</strong>
            <span>{mechanismConsoleTabDescription(tab)}</span>
          </button>
        ))}
      </nav>

      <div className="coordination-mechanism-console__body">
        <section className="coordination-console-panel">
          <header>
            <div className="boundary-identity-stack"><span>通信控制台</span><strong>{edges.length} 条交接边</strong></div>
            <button className="boundary-chip" onClick={() => onOpenDrawer("communication", selectedEdgeId ? "edge" : "graph", selectedEdgeId)} type="button"><span>打开通信抽屉</span></button>
          </header>
          <div className="coordination-console-grid">
            <article><span>边数量</span><strong>{edges.length}</strong><small>结构交接总数</small></article>
            <article><span>契约边</span><strong>{edges.filter((edge) => edgeContractId(edge)).length}</strong><small>已绑定交接契约</small></article>
            <article><span>隔离交接</span><strong>{edges.filter((edge) => booleanValue(asRecord(edge.working_memory_handoff_policy).summary_only)).length}</strong><small>只传摘要或引用</small></article>
            <article><span>节点数量</span><strong>{nodes.length}</strong><small>当前拓扑节点</small></article>
          </div>
        </section>
      </div>
    </section>
  );
}

function CoordinationMechanismDrawer({
  a2aCatalog,
  drawer,
  activeGraphNodes,
  coordinationDraft,
  protocolDraft,
  selectedGraphEdge,
  setProtocolDraft,
  updateCoordinationEdge,
  onClose,
}: {
  a2aCatalog: A2ACatalogLike | null;
  drawer: MechanismDrawerState;
  activeGraphNodes: Array<Record<string, unknown>>;
  coordinationDraft: CoordinationDraftLike;
  protocolDraft: ProtocolDraftLike;
  selectedGraphEdge: Record<string, unknown> | null;
  setProtocolDraft: Dispatch<SetStateAction<ProtocolDraftLike>>;
  updateCoordinationEdge: (edgeId: string, patch: Record<string, unknown>) => void;
  onClose: () => void;
}) {
  if (!drawer.open) return null;
  const edgeId = selectedGraphEdge ? graphEdgeId(selectedGraphEdge) : "";
  const selectedEdgeWorkingMemoryPolicy = asRecord(selectedGraphEdge?.working_memory_handoff_policy);
  const selectedEdgePreview = selectedGraphEdge ? edgeA2APreview({
    catalog: a2aCatalog,
    coordinationDraft,
    edge: selectedGraphEdge,
    protocolDraft,
    sourceNode: activeGraphNodes.find((node) => String(node.node_id ?? "") === graphEdgeSource(selectedGraphEdge)) ?? null,
    targetNode: activeGraphNodes.find((node) => String(node.node_id ?? "") === graphEdgeTarget(selectedGraphEdge)) ?? null,
  }) : null;
  const targetLabel = selectedGraphEdge
    ? String((selectedGraphEdge.label ?? selectedGraphEdge.mode ?? edgeId) || "通信边")
    : "整张任务图";

  return (
    <aside className="coordination-mechanism-drawer" aria-label={mechanismDrawerTitle(drawer.drawer_type)}>
      <header>
        <div className="boundary-identity-stack">
          <span>{targetLabel}</span>
          <strong>{mechanismDrawerTitle(drawer.drawer_type)}</strong>
        </div>
        <button className="boundary-chip" onClick={onClose} type="button"><span>关闭</span></button>
      </header>
      <div className="coordination-mechanism-drawer__body">
        <div className="coordination-console-grid">
          <article><span>目标类型</span><strong>{drawer.target_object_type}</strong><small>配置作用域</small></article>
          <article><span>目标 ID</span><strong>{drawer.target_object_id || "graph"}</strong><small>机制绑定对象</small></article>
          <article><span>抽屉类型</span><strong>{drawer.drawer_type}</strong><small>拓扑层仅保留通信</small></article>
        </div>

        {selectedGraphEdge ? (
          <>
            <section className="boundary-inspector-subblock">
              <header><strong>通信交接</strong><span>边策略</span></header>
              <TaskSystemSelectField label="通信模式" onChange={(value) => updateCoordinationEdge(edgeId, { mode: value })} options={GRAPH_EDGE_MODE_CHOICES} value={String(selectedGraphEdge.mode ?? "structured_handoff")} formatOption={taskSystemOptionLabel} />
              <TaskSystemField label="载荷契约"><input value={String(selectedGraphEdge.payload_contract_id ?? selectedGraphEdge.contract_id ?? "")} onChange={(event) => updateCoordinationEdge(edgeId, { payload_contract_id: event.target.value, contract_id: event.target.value })} /></TaskSystemField>
              <TaskSystemSelectField label="等待策略" onChange={(value) => updateCoordinationEdge(edgeId, { wait_policy: value })} options={NODE_WAIT_POLICY_OPTIONS} value={String(selectedGraphEdge.wait_policy ?? "wait_all_upstream_completed")} formatOption={taskSystemOptionLabel} />
              <TaskSystemSelectField label="确认策略" onChange={(value) => updateCoordinationEdge(edgeId, { ack_policy: value })} options={["explicit_ack", "implicit_ack"]} value={String(selectedGraphEdge.ack_policy ?? "explicit_ack")} formatOption={taskSystemOptionLabel} />
              <label className="boundary-check"><input checked={booleanValue(selectedGraphEdge.ack_required, true)} onChange={(event) => updateCoordinationEdge(edgeId, { ack_required: event.target.checked })} type="checkbox" />需要目标节点确认接收</label>
              <TaskSystemSelectField label="失败传播" onChange={(value) => updateCoordinationEdge(edgeId, { failure_propagation_policy: value })} options={EDGE_FAILURE_PROPAGATION_OPTIONS} value={String(selectedGraphEdge.failure_propagation_policy ?? "fail_downstream")} formatOption={taskSystemOptionLabel} />
              <TaskSystemSelectField label="结果投递" onChange={(value) => updateCoordinationEdge(edgeId, { result_delivery_policy: value })} options={EDGE_RESULT_DELIVERY_OPTIONS} value={String(selectedGraphEdge.result_delivery_policy ?? "contract_payload_and_refs")} formatOption={taskSystemOptionLabel} />
            </section>
            <section className="boundary-inspector-subblock">
              <header><strong>工作记忆交接</strong><span>边交接</span></header>
              <TaskSystemMultiSelectField label="携带 Kind" onChange={(value) => updateCoordinationEdge(edgeId, { working_memory_handoff_policy: updatePolicyList(selectedEdgeWorkingMemoryPolicy, "carry_kinds", value) })} options={WORKING_MEMORY_KIND_OPTIONS} value={asStringList(selectedEdgeWorkingMemoryPolicy.carry_kinds)} wide formatOption={taskSystemOptionLabel} />
              <TaskSystemMultiSelectField label="携带 Scope" onChange={(value) => updateCoordinationEdge(edgeId, { working_memory_handoff_policy: updatePolicyList(selectedEdgeWorkingMemoryPolicy, "carry_scopes", value) })} options={WORKING_MEMORY_SCOPE_OPTIONS} value={asStringList(selectedEdgeWorkingMemoryPolicy.carry_scopes)} wide formatOption={taskSystemOptionLabel} />
              <TaskSystemField label="显式 refs" wide><textarea onChange={(event) => updateCoordinationEdge(edgeId, { working_memory_handoff_policy: { ...selectedEdgeWorkingMemoryPolicy, working_memory_refs: event.target.value.split(/[\n,，]/).map((item) => item.trim()).filter(Boolean) } })} value={asStringList(selectedEdgeWorkingMemoryPolicy.working_memory_refs).join("\n")} /></TaskSystemField>
              <label className="boundary-check"><input checked={booleanValue(selectedEdgeWorkingMemoryPolicy.summary_only)} onChange={(event) => updateCoordinationEdge(edgeId, { working_memory_handoff_policy: { ...selectedEdgeWorkingMemoryPolicy, summary_only: event.target.checked } })} type="checkbox" />只传摘要，不复制正文</label>
              <label className="boundary-check"><input checked={booleanValue(selectedEdgeWorkingMemoryPolicy.allow_artifact_refs, true)} onChange={(event) => updateCoordinationEdge(edgeId, { working_memory_handoff_policy: { ...selectedEdgeWorkingMemoryPolicy, allow_artifact_refs: event.target.checked } })} type="checkbox" />允许携带 artifact refs</label>
            </section>
            {selectedEdgePreview ? <TaskSystemField label="A2A 消息预览" wide><textarea readOnly value={toPrettyJson(selectedEdgePreview)} /></TaskSystemField> : null}
          </>
        ) : (
          <section className="boundary-inspector-subblock">
            <header><strong>图级通信协议</strong><span>A2A / 交接</span></header>
            <TaskSystemField label="协议标题"><input value={protocolDraft.title} onChange={(event) => setProtocolDraft((current) => ({ ...current, title: event.target.value }))} /></TaskSystemField>
            <TaskSystemMultiSelectField label="消息类型" onChange={(value) => setProtocolDraft((current) => ({ ...current, message_types: value, message_types_text: value.join("\n") }))} options={a2aCatalog?.message_types ?? ["message/send", "message/stream", "task/status"]} value={asStringList(protocolDraft.message_types)} wide formatOption={taskSystemOptionLabel} />
            <TaskSystemField label="载荷契约" wide><textarea value={protocolDraft.payload_contracts_text} onChange={(event) => setProtocolDraft((current) => ({ ...current, payload_contracts_text: event.target.value, payload_contracts: event.target.value.split(/[\n,，]/).map((item) => item.trim()).filter(Boolean) }))} /></TaskSystemField>
            <TaskSystemField label="确认策略"><input value={protocolDraft.ack_policy} onChange={(event) => setProtocolDraft((current) => ({ ...current, ack_policy: event.target.value }))} /></TaskSystemField>
            <TaskSystemField label="超时策略"><input value={protocolDraft.timeout_policy} onChange={(event) => setProtocolDraft((current) => ({ ...current, timeout_policy: event.target.value }))} /></TaskSystemField>
            <TaskSystemField label="错误信号策略"><input value={protocolDraft.error_signal_policy} onChange={(event) => setProtocolDraft((current) => ({ ...current, error_signal_policy: event.target.value }))} /></TaskSystemField>
            <TaskSystemField label="交接规则" wide><textarea value={protocolDraft.handoff_rules_text} onChange={(event) => setProtocolDraft((current) => ({ ...current, handoff_rules_text: event.target.value, handoff_rules: event.target.value.split(/[\n,，]/).map((item) => item.trim()).filter(Boolean) }))} /></TaskSystemField>
          </section>
        )}
      </div>
    </aside>
  );
}
function CoordinationCanvasPanel({
  activeGraphNodes,
  activeGraphEdges,
  coordinationDraft,
  linkingFromNodeId,
  setLinkingFromNodeId,
  selectedGraphNodeId,
  selectedGraphEdgeId,
  setSelectedGraphEdgeId,
  setSelectedGraphNodeId,
  graphSelection,
  setGraphSelection,
  addCoordinationEdge,
  handleTopologyNodeClick,
  reverseCoordinationEdge,
  cycleCoordinationEdgeMode,
  removeCoordinationEdge,
  addCoordinationSuccessorNode,
  cycleCoordinationNodeRole,
  removeCoordinationNode,
  selectedDomainTasks,
  selectedGraphNode,
}: {
  activeGraphNodes: Array<Record<string, unknown>>;
  activeGraphEdges: Array<Record<string, unknown>>;
  coordinationDraft: CoordinationDraftLike;
  linkingFromNodeId: string;
  setLinkingFromNodeId: (value: string) => void;
  selectedGraphNodeId: string;
  selectedGraphEdgeId: string;
  setSelectedGraphEdgeId: (value: string) => void;
  setSelectedGraphNodeId: (value: string) => void;
  graphSelection: GraphSelection;
  setGraphSelection: Dispatch<SetStateAction<GraphSelection>>;
  addCoordinationEdge: () => void;
  handleTopologyNodeClick: (nodeId: string) => void;
  reverseCoordinationEdge: (edgeId: string) => void;
  cycleCoordinationEdgeMode: (edgeId: string, currentMode: string) => void;
  removeCoordinationEdge: (edgeId: string) => void;
  addCoordinationSuccessorNode: (nodeId: string) => void;
  cycleCoordinationNodeRole: (nodeId: string, currentRole: string) => void;
  removeCoordinationNode: (nodeId: string) => void;
  selectedDomainTasks: SpecificTaskRecord[];
  selectedGraphNode: Record<string, unknown> | null;
}) {
  const [contextMenu, setContextMenu] = useState<GraphContextMenuState>({ open: false, x: 0, y: 0, target_type: "canvas", target_id: "" });
  const metadata = asRecord(coordinationDraft.metadata);
  const timelineFrames = coordinationTimelineFrames(metadata);

  function ensureNodeInSelection(nodeId: string) {
    setGraphSelection((current) => current.selected_node_ids.includes(nodeId)
      ? current
      : {
        ...current,
        primary_object_id: nodeId,
        primary_object_type: "node",
        selected_node_ids: [...current.selected_node_ids, nodeId],
      });
  }

  function ensureEdgeInSelection(edgeId: string) {
    setGraphSelection((current) => current.selected_edge_ids.includes(edgeId)
      ? current
      : {
        ...current,
        primary_object_id: edgeId,
        primary_object_type: "edge",
        selected_edge_ids: [...current.selected_edge_ids, edgeId],
      });
  }

  function selectNode(nodeId: string, additive = false) {
    setGraphSelection((current) => additive
      ? {
        ...current,
        primary_object_id: nodeId,
        primary_object_type: "node",
        selected_node_ids: toggleString(current.selected_node_ids, nodeId),
      }
      : {
        ...emptyGraphSelection(),
        primary_object_id: nodeId,
        primary_object_type: "node",
        selected_node_ids: [nodeId],
      });
  }

  function selectEdge(edgeId: string, additive = false) {
    setGraphSelection((current) => additive
      ? {
        ...current,
        primary_object_id: edgeId,
        primary_object_type: "edge",
        selected_edge_ids: toggleString(current.selected_edge_ids, edgeId),
      }
      : {
        ...emptyGraphSelection(),
        primary_object_id: edgeId,
        primary_object_type: "edge",
        selected_edge_ids: [edgeId],
      });
  }

  function selectFrame(frame: TaskGraphTimelineFrame) {
    setGraphSelection({
      ...emptyGraphSelection(),
      primary_object_id: frame.frame_id,
      primary_object_type: "frame",
      selected_frame_ids: [frame.frame_id],
      selected_node_ids: frame.node_ids,
      selected_edge_ids: frame.edge_ids,
    });
    setSelectedGraphNodeId("");
    setSelectedGraphEdgeId("");
    setContextMenu((current) => ({ ...current, open: false }));
  }

  function clearSelection() {
    setGraphSelection(emptyGraphSelection());
    setContextMenu((current) => ({ ...current, open: false }));
  }

  function setAllFrameNodes() {
    setGraphSelection({
      ...emptyGraphSelection(),
      primary_object_type: "node",
      selected_node_ids: activeGraphNodes.map((node) => String(node.node_id ?? "")).filter(Boolean),
      selected_edge_ids: activeGraphEdges.map((edge, index) => graphEdgeId(edge, index)).filter(Boolean),
      primary_object_id: String(activeGraphNodes[0]?.node_id ?? ""),
    });
  }

  function openContextMenu(targetType: GraphContextMenuState["target_type"], targetId: string, event: MouseEvent) {
    setContextMenu({
      open: true,
      x: event.clientX,
      y: event.clientY,
      target_type: targetType,
      target_id: targetId,
    });
  }

  return (
    <>
      <section className="coordination-editor-canvas-shell">
        <header className="coordination-editor-canvas-head">
          <div className="boundary-identity-stack">
            <span>任务图画布</span>
            <strong>{selectedGraphNode ? graphNodeLabel(selectedGraphNode, 0) : "节点与通信关系"}</strong>
          </div>
          <div className="coordination-editor-toolbar">
            <button className="boundary-chip" disabled={activeGraphNodes.length < 2} onClick={addCoordinationEdge} type="button">
              <GitBranch size={14} />
              <span>添加通信边</span>
            </button>
            <button
              className={linkingFromNodeId ? "boundary-chip boundary-chip--active" : "boundary-chip"}
              disabled={!activeGraphNodes.length}
              onClick={() => {
                setLinkingFromNodeId(selectedGraphNodeId || String(activeGraphNodes[0]?.node_id ?? ""));
                setSelectedGraphEdgeId("");
              }}
              type="button"
            >
              <span>{linkingFromNodeId ? "选择目标节点" : "进入连线模式"}</span>
            </button>
            {linkingFromNodeId ? (
              <button className="boundary-chip" onClick={() => setLinkingFromNodeId("")} type="button">
                <span>取消连线</span>
              </button>
            ) : null}
          </div>
        </header>

        <div className="coordination-editor-canvas-stage">
          <div className="coordination-editor-canvas-main">
            <CoordinationGraph
              edges={activeGraphEdges}
              frames={timelineFrames}
              messages={coordinationDraft.communication_modes ?? []}
              linkingFromNodeId={linkingFromNodeId}
              nodes={activeGraphNodes}
              onCanvasContextMenu={(event) => openContextMenu(graphSelection.selected_node_ids.length || graphSelection.selected_edge_ids.length ? "selection" : "canvas", "", event)}
              onEdgeContextMenu={(edgeId, event) => {
                if (!graphSelection.selected_edge_ids.includes(edgeId)) {
                  ensureEdgeInSelection(edgeId);
                }
                openContextMenu(graphSelection.selected_node_ids.length || graphSelection.selected_edge_ids.length > 1 ? "selection" : "edge", edgeId, event);
              }}
              onNodeContextMenu={(nodeId, event) => {
                if (!graphSelection.selected_node_ids.includes(nodeId)) {
                  ensureNodeInSelection(nodeId);
                }
                openContextMenu(graphSelection.selected_node_ids.length > 1 || graphSelection.selected_edge_ids.length ? "selection" : "node", nodeId, event);
              }}
              onSelectEdge={(edgeId, event) => {
                setSelectedGraphEdgeId(edgeId);
                setSelectedGraphNodeId("");
                setLinkingFromNodeId("");
                selectEdge(edgeId, Boolean(event?.shiftKey));
              }}
              onSelectNode={(nodeId, event) => {
                handleTopologyNodeClick(nodeId);
                selectNode(nodeId, Boolean(event?.shiftKey));
              }}
              onSelectFrame={(frameId) => {
                const frame = timelineFrames.find((item) => item.frame_id === frameId);
                if (frame) selectFrame(frame);
              }}
              onBoxSelect={({ nodeIds, edgeIds }) => {
                setGraphSelection({
                  ...emptyGraphSelection(),
                  primary_object_id: nodeIds[0] ?? edgeIds[0] ?? "",
                  primary_object_type: nodeIds.length ? "node" : edgeIds.length ? "edge" : "",
                  selected_node_ids: nodeIds,
                  selected_edge_ids: edgeIds,
                });
                setSelectedGraphNodeId(nodeIds[0] ?? "");
                setSelectedGraphEdgeId(nodeIds.length ? "" : edgeIds[0] ?? "");
              }}
              renderEdgeTools={(edge, edgeId) => {
                const mode = String(edge.mode ?? edge.policy ?? "structured_handoff");
                return (
                  <>
                    <button onClick={(event) => {
                      event.stopPropagation();
                      reverseCoordinationEdge(edgeId);
                    }} title="反转方向" type="button">
                      <RotateCcw size={13} />
                    </button>
                    <button onClick={(event) => {
                      event.stopPropagation();
                      cycleCoordinationEdgeMode(edgeId, mode);
                    }} title="切换通信模式" type="button">
                      <SquarePen size={13} />
                    </button>
                    <button onClick={(event) => {
                      event.stopPropagation();
                      if (window.confirm("确认删除这条通信边吗？")) {
                        removeCoordinationEdge(edgeId);
                      }
                    }} title="删除通信" type="button">
                      <Trash2 size={13} />
                    </button>
                  </>
                );
              }}
              renderNodeTools={(node, nodeId) => {
                const role = String(node.role ?? "participant");
                return (
                  <>
                    <button onClick={(event) => {
                      event.stopPropagation();
                      addCoordinationSuccessorNode(nodeId);
                    }} title="添加后继节点" type="button">
                      <GitCommitHorizontal size={13} />
                    </button>
                    <button onClick={(event) => {
                      event.stopPropagation();
                      cycleCoordinationNodeRole(nodeId, role);
                    }} title="切换节点角色" type="button">
                      <SquarePen size={13} />
                    </button>
                    {role !== "coordinator" ? (
                      <button onClick={(event) => {
                        event.stopPropagation();
                        if (window.confirm("确认删除这个节点吗？")) {
                          removeCoordinationNode(nodeId);
                        }
                      }} title="删除节点" type="button">
                        <Trash2 size={13} />
                      </button>
                    ) : null}
                  </>
                );
              }}
              selectedEdgeId={selectedGraphEdgeId}
              selectedNodeId={selectedGraphNodeId}
              selection={graphSelection}
              tasks={selectedDomainTasks}
            />
          </div>
          <section className="coordination-editor-assist coordination-editor-assist--compact">
            <header className="coordination-editor-assist__head">
              <div className="boundary-identity-stack">
                <span>结构选择</span>
                <strong>节点与通信边</strong>
              </div>
              <div className="coordination-editor-actions">
                <button className="boundary-chip" onClick={setAllFrameNodes} type="button"><span>全选节点</span></button>
                <button className="boundary-chip" onClick={clearSelection} type="button"><span>清空选择</span></button>
              </div>
            </header>
            <div className="coordination-console-grid">
              <article><span>选中节点</span><strong>{graphSelection.selected_node_ids.length}</strong><small>当前结构选择集</small></article>
              <article><span>选中通信</span><strong>{graphSelection.selected_edge_ids.length}</strong><small>当前边选择集</small></article>
              <article><span>图内节点</span><strong>{activeGraphNodes.length}</strong><small>可编排执行单元</small></article>
            </div>
            <div className="coordination-frame-summary">
              <span>{graphSelection.primary_object_type === "node" ? "节点选中态" : graphSelection.primary_object_type === "edge" ? "通信选中态" : "画布编辑态"}</span>
              <span>{linkingFromNodeId ? `正在从 ${linkingFromNodeId} 连线` : "未进入连线模式"}</span>
            </div>
          </section>
          {contextMenu.open ? (
            <div className="coordination-context-menu" style={{ left: contextMenu.x, top: contextMenu.y }}>
              <strong>{contextMenu.target_type === "selection" ? "选择集" : contextMenu.target_type === "canvas" ? "画布" : contextMenu.target_type === "node" ? "节点" : "通信边"}</strong>
              {contextMenu.target_type === "canvas" ? (
                <>
                  <button onClick={setAllFrameNodes} type="button">选择全部节点</button>
                  <button onClick={addCoordinationEdge} type="button">添加通信边</button>
                </>
              ) : null}
              <button onClick={clearSelection} type="button">清空选择</button>
              <button onClick={() => setContextMenu((current) => ({ ...current, open: false }))} type="button">关闭</button>
            </div>
          ) : null}
        </div>
      </section>
    </>
  );
}

function CoordinationInspectorPanel({
  selectedGraphNode,
  selectedGraphEdge,
  coordinationDraft,
  protocolDraft,
  setCoordinationPublished,
  editorPublished,
  topologyDraft,
  removeCoordinationNode,
  activeGraphNodes,
  reverseCoordinationEdge,
  removeCoordinationEdge,
  selectedCoordinationGraphSpec,
  a2aCatalog,
  contractSpecs,
  projectionCards,
  onOpenDrawer,
}: {
  selectedGraphNode: Record<string, unknown> | null;
  selectedGraphEdge: Record<string, unknown> | null;
  coordinationDraft: CoordinationDraftLike;
  protocolDraft: ProtocolDraftLike;
  setCoordinationPublished: (enabled: boolean) => void;
  editorPublished: boolean;
  topologyDraft: TopologyDraftLike;
  removeCoordinationNode: (nodeId: string) => void;
  activeGraphNodes: Array<Record<string, unknown>>;
  reverseCoordinationEdge: (edgeId: string) => void;
  removeCoordinationEdge: (edgeId: string) => void;
  selectedCoordinationGraphSpec: CoordinationGraphSpec | null;
  a2aCatalog: A2ACatalogLike | null;
  contractSpecs: ContractSpec[];
  projectionCards: ProjectionCardLike[];
  onOpenDrawer: (drawerType: MechanismDrawerType, targetType?: MechanismTargetType, targetId?: string) => void;
}) {
  const phaseDefinitions = coordinationPhaseDefinitions(asRecord(coordinationDraft.metadata), activeGraphNodes);
  const formatContract = contractOptionLabel(contractSpecs);
  const formatProjection = projectionOptionLabel(projectionCards);
  const graphIssues = selectedCoordinationGraphSpec?.issues ?? [];

  if (selectedGraphNode) {
    const nodeId = String(selectedGraphNode.node_id ?? "");
    const nodeTitle = String(selectedGraphNode.label ?? selectedGraphNode.title ?? graphNodeLabel(selectedGraphNode, 0));
    const nodeCard = agentCardForNode(selectedGraphNode, a2aCatalog);
    const reviewPolicy = nodeReviewGatePolicy(selectedGraphNode);
    const loopPolicy = nodeLoopPolicy(selectedGraphNode);
    const readPolicy = asRecord(selectedGraphNode.memory_read_policy);
    const writePolicy = asRecord(selectedGraphNode.memory_writeback_policy);
    const readKindCount = asStringList(readPolicy.readable_kinds).length;
    const writeKindCount = asStringList(writePolicy.writable_kinds).length;

    return (
      <>
        <section className="boundary-inspector-block coordination-inspector-object">
          <header>
            <div className="boundary-identity-stack">
              <span>节点</span>
              <strong>{nodeTitle}</strong>
            </div>
            <span>{nodeId || "未命名"}</span>
          </header>

          <div className="coordination-inspector-summary">
            <article><span>Agent</span><strong>{String(selectedGraphNode.agent_id ?? "未绑定")}</strong></article>
            <article><span>阶段</span><strong>{nodePhaseId(selectedGraphNode) || "未分配"}</strong></article>
            <article><span>执行</span><strong>{displayId(selectedGraphNode.execution_mode ?? "sync")}</strong></article>
          </div>

          <div className="boundary-kv coordination-inspector-kv">
            <p><span>分任务</span><strong>{graphNodeTaskId(selectedGraphNode) || "未绑定"}</strong></p>
            <p><span>工作姿态</span><strong>{displayId(selectedGraphNode.work_posture ?? selectedGraphNode.role ?? "executor")}</strong></p>
            <p><span>投影</span><strong>{formatProjection(String(selectedGraphNode.projection_id ?? ""))}</strong></p>
            <p><span>契约</span><strong>{formatContract(nodeContractId(selectedGraphNode))}</strong></p>
            <p><span>A2A 卡片</span><strong>{String(nodeCard?.name ?? "未匹配")}</strong></p>
          </div>

          <div className="coordination-inspector-summary coordination-inspector-summary--compact">
            <article><span>审核门</span><strong>{booleanValue(reviewPolicy.is_review_gate) ? "启用" : "未启用"}</strong></article>
            <article><span>循环</span><strong>{Object.keys(loopPolicy).length ? `${Number(loopPolicy.max_attempts ?? 0) || "已配置"}` : "未配置"}</strong></article>
            <article><span>记忆</span><strong>{readKindCount} 读 / {writeKindCount} 写</strong></article>
          </div>

          {String(selectedGraphNode.role ?? "") !== "coordinator" ? (
            <div className="coordination-inspector-danger-zone">
              <TaskSystemToolbarButton onClick={() => {
                if (window.confirm("确认删除这个节点吗？")) {
                  removeCoordinationNode(nodeId);
                }
              }}><Trash2 size={14} />删除节点</TaskSystemToolbarButton>
            </div>
          ) : null}
        </section>

        {graphIssues.length ? <CoordinationInspectorIssues issues={graphIssues} /> : null}
      </>
    );
  }

  if (selectedGraphEdge) {
    const edgeId = graphEdgeId(selectedGraphEdge);
    const sourceNode = activeGraphNodes.find((node) => String(node.node_id ?? "") === graphEdgeSource(selectedGraphEdge)) ?? null;
    const targetNode = activeGraphNodes.find((node) => String(node.node_id ?? "") === graphEdgeTarget(selectedGraphEdge)) ?? null;
    const edgeMemoryPolicy = asRecord(selectedGraphEdge.working_memory_handoff_policy);
    const edgePreview = edgeA2APreview({
      catalog: a2aCatalog,
      coordinationDraft,
      edge: selectedGraphEdge,
      protocolDraft,
      sourceNode,
      targetNode,
    });

    return (
      <>
        <section className="boundary-inspector-block coordination-inspector-object">
          <header>
            <div className="boundary-identity-stack">
              <span>通信边</span>
              <strong>{edgeId}</strong>
            </div>
            <span>{displayId(selectedGraphEdge.mode ?? "structured_handoff")}</span>
          </header>

          <div className="coordination-inspector-summary">
            <article><span>起点</span><strong>{graphEdgeSource(selectedGraphEdge) || "未绑定"}</strong></article>
            <article><span>终点</span><strong>{graphEdgeTarget(selectedGraphEdge) || "未绑定"}</strong></article>
            <article><span>契约</span><strong>{formatContract(edgeContractId(selectedGraphEdge))}</strong></article>
          </div>

          <div className="boundary-kv coordination-inspector-kv">
            <p><span>等待策略</span><strong>{displayId(selectedGraphEdge.wait_policy ?? "继承目标节点")}</strong></p>
            <p><span>确认</span><strong>{booleanValue(selectedGraphEdge.ack_required, true) ? displayId(selectedGraphEdge.ack_policy ?? "explicit_ack") : "无需确认"}</strong></p>
            <p><span>失败传播</span><strong>{displayId(selectedGraphEdge.failure_propagation_policy ?? "fail_downstream")}</strong></p>
            <p><span>A2A 类型</span><strong>{edgePreview?.message_type ?? "未生成"}</strong></p>
            <p><span>记忆交接</span><strong>{booleanValue(edgeMemoryPolicy.summary_only) ? "摘要/引用" : "按策略携带"}</strong></p>
          </div>

          <div className="coordination-inspector-actions coordination-inspector-actions--grid">
            <button className="boundary-chip" onClick={() => onOpenDrawer("communication", "edge", edgeId)} type="button"><span>通信交接</span></button>
            <button className="boundary-chip" onClick={() => onOpenDrawer("communication", "edge", edgeId)} type="button"><span>A2A 预览</span></button>
          </div>

          <div className="coordination-inspector-danger-zone">
            <TaskSystemToolbarButton onClick={() => reverseCoordinationEdge(edgeId)}><RotateCcw size={14} />反转方向</TaskSystemToolbarButton>
            <TaskSystemToolbarButton onClick={() => {
              if (window.confirm("确认删除这条通信边吗？")) {
                removeCoordinationEdge(edgeId);
              }
            }}><Trash2 size={14} />删除通信</TaskSystemToolbarButton>
          </div>
        </section>

        {graphIssues.length ? <CoordinationInspectorIssues issues={graphIssues} /> : null}
      </>
    );
  }

  return (
    <>
      <section className="boundary-inspector-block coordination-inspector-object">
        <header>
          <div className="boundary-identity-stack">
            <span>任务图</span>
            <strong>{coordinationDraft.title || "未命名任务图"}</strong>
          </div>
          <span>{editorPublished ? "已发布" : "草稿"}</span>
        </header>

        <div className="coordination-inspector-summary">
          <article><span>节点</span><strong>{activeGraphNodes.length}</strong></article>
          <article><span>阶段</span><strong>{phaseDefinitions.length}</strong></article>
          <article><span>问题</span><strong>{graphIssues.length}</strong></article>
        </div>

        <div className="boundary-kv coordination-inspector-kv">
          <p><span>模式</span><strong>{displayId(coordinationDraft.coordination_mode)}</strong></p>
          <p><span>Agent 组</span><strong>{coordinationDraft.agent_group_id || "未绑定"}</strong></p>
          <p><span>A2A</span><strong>{a2aCatalog?.protocol_version || "0.3.0"} / {a2aCatalog?.transport || "JSONRPC"}</strong></p>
          <p><span>拓扑策略</span><strong>{topologyDraft.join_policy} / {topologyDraft.failure_policy}</strong></p>
        </div>

        <div className="coordination-inspector-actions coordination-inspector-actions--grid">
          <button className="boundary-chip" onClick={() => onOpenDrawer("communication", "graph")} type="button"><span>通信</span></button>
        </div>

        <label className="boundary-check coordination-inspector-publish">
          <input checked={editorPublished} onChange={(event) => setCoordinationPublished(event.target.checked)} type="checkbox" />
          发布为可运行任务图
        </label>
      </section>

      {graphIssues.length ? <CoordinationInspectorIssues issues={graphIssues} /> : null}
    </>
  );
}

function CoordinationInspectorIssues({ issues }: { issues: NonNullable<CoordinationGraphSpec["issues"]> }) {
  return (
    <section className="boundary-inspector-block boundary-inspector-block--warn">
      <header><strong>图校验</strong><span>{issues.length}</span></header>
      {issues.map((issue, index) => (
        <p key={`${String(issue.code ?? "issue")}-${index}`}>{String(issue.message ?? issue.code ?? "校验问题")}</p>
      ))}
    </section>
  );
}
export function CoordinationEditorWorkbench({
  selectedDomain,
  selectedCoordinationId,
  setSelectedCoordinationId,
  coordinationDraft,
  saving,
  applyCoordinationGraphTemplate,
  duplicateCoordinationDraft,
  sendCoordinationToChat,
  saveCoordinationStack,
  editorValid,
  editorIssueCount,
  editorPublished,
  topologyDirty,
  activeGraphNodes,
  activeGraphEdges,
  selectedDomainTasks,
  boundCoordinationTaskIds,
  addCoordinationTaskNode,
  addCoordinationRoleNode,
  addCoordinationNode,
  addCoordinationEdge,
  linkingFromNodeId,
  setLinkingFromNodeId,
  selectedGraphNodeId,
  selectedGraphEdgeId,
  setSelectedGraphEdgeId,
  setSelectedGraphNodeId,
  handleTopologyNodeClick,
  reverseCoordinationEdge,
  cycleCoordinationEdgeMode,
  removeCoordinationEdge,
  addCoordinationSuccessorNode,
  cycleCoordinationNodeRole,
  removeCoordinationNode,
  selectedGraphNode,
  selectedGraphEdge,
  setCoordinationDraft,
  agentGroupOptions,
  setCoordinationPublished,
  topologyDraft,
  setTopologyDraft,
  protocolDraft,
  setProtocolDraft,
  domainTaskOptions,
  updateCoordinationNode,
  updateCoordinationEdge,
  selectedCoordinationGraphSpec,
  a2aCatalog,
  contractSpecs,
  projectionCards = [],
}: {
  selectedDomain: DomainRecordLike | null;
  selectedCoordinationId: string;
  setSelectedCoordinationId: (value: string) => void;
  coordinationDraft: CoordinationDraftLike;
  saving: string;
  applyCoordinationGraphTemplate: (template: TaskGraphTemplateId) => void;
  duplicateCoordinationDraft: () => Promise<void>;
  sendCoordinationToChat: (task: TaskGraphRecord | null, domain: DomainRecordLike | null) => void;
  saveCoordinationStack: (nextPublished?: boolean) => Promise<void>;
  editorValid: boolean;
  editorIssueCount: number;
  editorPublished: boolean;
  topologyDirty: boolean;
  activeGraphNodes: Array<Record<string, unknown>>;
  activeGraphEdges: Array<Record<string, unknown>>;
  selectedDomainTasks: SpecificTaskRecord[];
  boundCoordinationTaskIds: Set<string>;
  addCoordinationTaskNode: (task: SpecificTaskRecord, role?: string) => void;
  addCoordinationRoleNode: (role: string) => void;
  addCoordinationNode: () => void;
  addCoordinationEdge: () => void;
  linkingFromNodeId: string;
  setLinkingFromNodeId: (value: string) => void;
  selectedGraphNodeId: string;
  selectedGraphEdgeId: string;
  setSelectedGraphEdgeId: (value: string) => void;
  setSelectedGraphNodeId: (value: string) => void;
  handleTopologyNodeClick: (nodeId: string) => void;
  reverseCoordinationEdge: (edgeId: string) => void;
  cycleCoordinationEdgeMode: (edgeId: string, currentMode: string) => void;
  removeCoordinationEdge: (edgeId: string) => void;
  addCoordinationSuccessorNode: (nodeId: string) => void;
  cycleCoordinationNodeRole: (nodeId: string, currentRole: string) => void;
  removeCoordinationNode: (nodeId: string) => void;
  selectedGraphNode: Record<string, unknown> | null;
  selectedGraphEdge: Record<string, unknown> | null;
  setCoordinationDraft: Dispatch<SetStateAction<CoordinationDraftLike>>;
  agentGroupOptions: string[];
  setCoordinationPublished: (enabled: boolean) => void;
  topologyDraft: TopologyDraftLike;
  setTopologyDraft: Dispatch<SetStateAction<TopologyDraftLike>>;
  protocolDraft: ProtocolDraftLike;
  setProtocolDraft: Dispatch<SetStateAction<ProtocolDraftLike>>;
  domainTaskOptions: Array<{ value: string; label: string }>;
  updateCoordinationNode: (nodeId: string, patch: Record<string, unknown>) => void;
  updateCoordinationEdge: (edgeId: string, patch: Record<string, unknown>) => void;
  selectedCoordinationGraphSpec: CoordinationGraphSpec | null;
  a2aCatalog: A2ACatalogLike | null;
  contractSpecs: ContractSpec[];
  projectionCards?: ProjectionCardLike[];
}) {
  const [graphSelection, setGraphSelection] = useState<GraphSelection>(emptyGraphSelection());
  const [activeConsoleTab, setActiveConsoleTab] = useState<MechanismConsoleTab>("communication");
  const [mechanismDrawer, setMechanismDrawer] = useState<MechanismDrawerState>(DEFAULT_MECHANISM_DRAWER);
  const editorPhaseDefinitions = coordinationPhaseDefinitions(asRecord(coordinationDraft.metadata), activeGraphNodes);
  const editorAgentCardOptions = uniqueStrings([
    String(selectedGraphNode?.agent_id ?? ""),
    ...((a2aCatalog?.agent_cards ?? []).map((card) => String(card.agent_id ?? "")).filter(Boolean)),
  ]);
  const formatEditorAgentCard = (agentId: string) => {
    const card = (a2aCatalog?.agent_cards ?? []).find((item) => String(item.agent_id ?? "") === agentId);
    if (!agentId) return "不绑定";
    return card?.name ? `${String(card.name)} · ${agentId}` : agentId;
  };
  const formatEditorContract = contractOptionLabel(contractSpecs);
  const formatEditorProjection = projectionOptionLabel(projectionCards);
  const editorNodeIdOptions = ["", ...activeGraphNodes.map((node) => String(node.node_id ?? "")).filter(Boolean)];
  const formatEditorNodeOption = (nodeId: string) => {
    if (!nodeId) return "不绑定";
    const node = activeGraphNodes.find((item) => String(item.node_id ?? "") === nodeId);
    return node ? `${String(node.title ?? node.label ?? node.node_id)} · ${nodeId}` : nodeId;
  };

  function openMechanismDrawer(drawerType: MechanismDrawerType, targetType: MechanismTargetType = "graph", targetId = "") {
    setMechanismDrawer({
      open: true,
      drawer_type: drawerType,
      target_object_type: targetType,
      target_object_id: targetId,
    });
  }

  return (
    <section className="boundary-layer-stack coordination-editor-workbench">
      <section className="boundary-card boundary-card--editor">
        <CoordinationMechanismConsole
          activeTab={activeConsoleTab}
          edges={activeGraphEdges}
          nodes={activeGraphNodes}
          selectedEdgeId={selectedGraphEdgeId}
          setActiveTab={setActiveConsoleTab}
          onOpenDrawer={openMechanismDrawer}
        />

        <div className={mechanismDrawer.open ? "coordination-editor-layout coordination-editor-layout--drawer-open" : "coordination-editor-layout"}>
          <aside className="coordination-editor-sidebar">
            <CoordinationTaskPoolPanel
              addCoordinationNode={addCoordinationNode}
              addCoordinationRoleNode={addCoordinationRoleNode}
              addCoordinationTaskNode={addCoordinationTaskNode}
              applyCoordinationGraphTemplate={applyCoordinationGraphTemplate}
              boundCoordinationTaskIds={boundCoordinationTaskIds}
              selectedDomainTasks={selectedDomainTasks}
            />
          </aside>

          <div className="coordination-editor-canvas">
            <CoordinationCanvasPanel
              activeGraphEdges={activeGraphEdges}
              activeGraphNodes={activeGraphNodes}
              addCoordinationEdge={addCoordinationEdge}
              addCoordinationSuccessorNode={addCoordinationSuccessorNode}
              coordinationDraft={coordinationDraft}
              cycleCoordinationEdgeMode={cycleCoordinationEdgeMode}
              cycleCoordinationNodeRole={cycleCoordinationNodeRole}
              handleTopologyNodeClick={handleTopologyNodeClick}
              linkingFromNodeId={linkingFromNodeId}
              removeCoordinationEdge={removeCoordinationEdge}
              removeCoordinationNode={removeCoordinationNode}
              reverseCoordinationEdge={reverseCoordinationEdge}
              selectedDomainTasks={selectedDomainTasks}
              selectedGraphEdgeId={selectedGraphEdgeId}
              selectedGraphNode={selectedGraphNode}
              selectedGraphNodeId={selectedGraphNodeId}
              graphSelection={graphSelection}
              setGraphSelection={setGraphSelection}
              setLinkingFromNodeId={setLinkingFromNodeId}
              setSelectedGraphEdgeId={setSelectedGraphEdgeId}
              setSelectedGraphNodeId={setSelectedGraphNodeId}
            />
          </div>

          <aside className="coordination-editor-inspector">
            <CoordinationInspectorPanel
              activeGraphNodes={activeGraphNodes}
              coordinationDraft={coordinationDraft}
              editorPublished={editorPublished}
              protocolDraft={protocolDraft}
              removeCoordinationEdge={removeCoordinationEdge}
              removeCoordinationNode={removeCoordinationNode}
              reverseCoordinationEdge={reverseCoordinationEdge}
              selectedCoordinationGraphSpec={selectedCoordinationGraphSpec}
              selectedGraphEdge={selectedGraphEdge}
              selectedGraphNode={selectedGraphNode}
              setCoordinationPublished={setCoordinationPublished}
              topologyDraft={topologyDraft}
              a2aCatalog={a2aCatalog}
              contractSpecs={contractSpecs}
              projectionCards={projectionCards}
              onOpenDrawer={openMechanismDrawer}
            />
          </aside>

          <CoordinationMechanismDrawer
            a2aCatalog={a2aCatalog}
            activeGraphNodes={activeGraphNodes}
            coordinationDraft={coordinationDraft}
            drawer={mechanismDrawer}
            protocolDraft={protocolDraft}
            setProtocolDraft={setProtocolDraft}
            selectedGraphEdge={selectedGraphEdge}
            updateCoordinationEdge={updateCoordinationEdge}
            onClose={() => setMechanismDrawer((current) => ({ ...current, open: false }))}
          />
        </div>
      </section>
    </section>
  );
}
