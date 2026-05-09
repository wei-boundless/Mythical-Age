"use client";

import {
  GitBranch,
  GitCommitHorizontal,
  Plus,
  Rows3,
  RotateCcw,
  Save,
  SquarePen,
  Trash2,
} from "lucide-react";
import { useMemo, useState, type Dispatch, type MouseEvent, type ReactNode, type SetStateAction } from "react";

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
  buildTimelinePreflightIssues,
  coordinationPhaseDefinitions,
  coordinationTimelineFrames,
  nodeBlocksPhaseExit,
  nodeLoopPolicy,
  nodeMainChain,
  nodePhaseId,
  nodeReviewGatePolicy,
  nodeSequenceIndex,
  nodeTimelineGroupId,
  type TaskGraphTimelineFrame,
} from "@/components/workspace/views/task-system/taskGraphTimeline";
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
const MECHANISM_CONSOLE_TABS = ["timeline", "communication", "review", "loop", "memory", "artifact", "preflight", "runtime"] as const;
type MechanismConsoleTab = typeof MECHANISM_CONSOLE_TABS[number];
type MechanismDrawerType = "agent" | "contract" | "timeline" | "communication" | "review" | "loop" | "memory" | "artifact" | "preflight" | "runtime";
type MechanismTargetType = "node" | "edge" | "frame" | "graph";
type MechanismDrawerState = {
  open: boolean;
  drawer_type: MechanismDrawerType;
  target_object_type: MechanismTargetType;
  target_object_id: string;
};
const DEFAULT_MECHANISM_DRAWER: MechanismDrawerState = {
  open: false,
  drawer_type: "timeline",
  target_object_type: "graph",
  target_object_id: "",
};
const TIMELINE_FRAME_TYPES = ["phase_frame", "step_frame", "parallel_frame", "loop_frame", "review_gate_frame"] as const;
type TimelineFrameType = typeof TIMELINE_FRAME_TYPES[number];
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
const NOTIFICATION_POLICY_OPTIONS = ["event_only", "queued_summary", "queued_alert", "none"];
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
const WORKING_MEMORY_VISIBILITY_OPTIONS = ["private_to_node", "shared_in_graph", "handoff_only", "coordinator_only", "human_review_only"];
const WORKING_MEMORY_SEMANTIC_OPTIONS = ["working_fact", "draft_artifact", "reflection", "instruction", "temporal_event", "conflict", "decision", "handoff_note", "evaluation"];
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
    timeline: "时序",
    communication: "通信",
    review: "审核",
    loop: "循环",
    memory: "记忆",
    artifact: "产物",
    preflight: "预检",
    runtime: "运行",
  };
  return labels[value];
}

function mechanismConsoleTabDescription(value: MechanismConsoleTab) {
  const labels: Record<MechanismConsoleTab, string> = {
    timeline: "生命周期",
    communication: "边交接",
    review: "审核门",
    loop: "循环",
    memory: "记忆",
    artifact: "产物",
    preflight: "预检",
    runtime: "运行",
  };
  return labels[value];
}

function mechanismDrawerTitle(value: MechanismDrawerType) {
  const labels: Record<MechanismDrawerType, string> = {
    agent: "Agent 抽屉",
    contract: "投影与契约抽屉",
    timeline: "时序抽屉",
    communication: "通信抽屉",
    review: "审核抽屉",
    loop: "循环抽屉",
    memory: "记忆抽屉",
    artifact: "产物抽屉",
    preflight: "预检抽屉",
    runtime: "运行抽屉",
  };
  return labels[value];
}

function timelineFrameTypeLabel(value: TimelineFrameType) {
  const labels: Record<TimelineFrameType, string> = {
    phase_frame: "阶段框",
    step_frame: "时序点",
    parallel_frame: "并行组",
    loop_frame: "循环框",
    review_gate_frame: "审核门",
  };
  return labels[value];
}

function timelineFrameTypeOptionLabel(value: string) {
  return TIMELINE_FRAME_TYPES.includes(value as TimelineFrameType) ? timelineFrameTypeLabel(value as TimelineFrameType) : value;
}

function timelineFrameDefaultTitle(value: TimelineFrameType) {
  const labels: Record<TimelineFrameType, string> = {
    phase_frame: "新阶段",
    step_frame: "新时序点",
    parallel_frame: "新并行组",
    loop_frame: "新循环",
    review_gate_frame: "新审核门",
  };
  return labels[value];
}

function timelineFrameIdFromTitle(value: string) {
  const normalized = value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fa5]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return `frame.${normalized || "timeline"}.${Date.now().toString(36)}`;
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
  return String(edge?.contract_id ?? "").trim();
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
  applyCoordinationGraphTemplate: (template: "single_agent" | "multi_sequence" | "multi_parallel_merge") => void;
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
  coordinationDraft,
  selectedNodeId,
  selectedEdgeId,
  graphSelection,
  selectedCoordinationGraphSpec,
  onSelectNode,
  onOpenDrawer,
}: {
  activeTab: MechanismConsoleTab;
  setActiveTab: (value: MechanismConsoleTab) => void;
  nodes: Array<Record<string, unknown>>;
  edges: Array<Record<string, unknown>>;
  coordinationDraft: CoordinationDraftLike;
  selectedNodeId: string;
  selectedEdgeId: string;
  graphSelection: GraphSelection;
  selectedCoordinationGraphSpec: CoordinationGraphSpec | null;
  onSelectNode: (nodeId: string) => void;
  onOpenDrawer: (drawerType: MechanismDrawerType, targetType?: MechanismTargetType, targetId?: string) => void;
}) {
  const metadata = asRecord(coordinationDraft.metadata);
  const phases = useMemo(() => coordinationPhaseDefinitions(metadata, nodes), [metadata, nodes]);
  const frames = useMemo(() => coordinationTimelineFrames(metadata), [metadata]);
  const timelineIssues = useMemo(() => buildTimelinePreflightIssues(nodes, edges, metadata), [edges, metadata, nodes]);
  const selectedNode = nodes.find((node, index) => nodeIdOfGraphNode(node, index) === selectedNodeId) ?? null;
  const selectedNodePhaseId = selectedNode ? nodePhaseId(selectedNode) : "";
  const selectedPhase = phases.find((phase) => phase.phase_id === selectedNodePhaseId) ?? phases[0] ?? null;
  const phaseGroups = phases.map((phase) => {
    const phaseNodes = nodes.filter((node) => nodePhaseId(node) === phase.phase_id);
    const blockingNodes = phaseNodes.filter((node) => nodeBlocksPhaseExit(node));
    const parallelNodes = phaseNodes.filter((node) => String(node.execution_mode ?? "") === "parallel" || nodeTimelineGroupId(node));
    const asyncNodes = phaseNodes.filter((node) => ["async", "background"].includes(String(node.execution_mode ?? "")));
    return { phase, phaseNodes, blockingNodes, parallelNodes, asyncNodes };
  });
  const reviewNodes = nodes.filter((node) => booleanValue(nodeReviewGatePolicy(node).is_review_gate) || String(node.node_type ?? "") === "review_gate" || String(node.role ?? "") === "reviewer");
  const loopNodes = nodes.filter((node) => Object.keys(nodeLoopPolicy(node)).length > 0);
  const memoryReadNodes = nodes.filter((node) => Object.keys(asRecord(node.memory_read_policy)).length > 0);
  const memoryWriteNodes = nodes.filter((node) => Object.keys(asRecord(node.memory_writeback_policy)).length > 0);
  const artifactNodes = nodes.filter((node) => String(node.artifact_policy_id ?? node.artifact_target ?? node.output_path ?? "").trim());
  const graphIssues = selectedCoordinationGraphSpec?.issues ?? [];
  const selectedCount = graphSelection.selected_node_ids.length + graphSelection.selected_edge_ids.length + graphSelection.selected_frame_ids.length;
  const selectedFrameId = graphSelection.primary_object_type === "frame" ? graphSelection.primary_object_id : graphSelection.selected_frame_ids[0] ?? "";

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
        {activeTab === "timeline" ? (
          <section className="coordination-console-panel coordination-console-panel--timeline">
            <header>
              <div className="boundary-identity-stack">
                <span>时序控制台</span>
                <strong>{selectedPhase?.title || selectedPhase?.phase_id || "生命周期未配置"}</strong>
              </div>
              <div className="boundary-actions">
                <span className={timelineIssues.length ? "boundary-badge boundary-badge--danger" : "boundary-badge boundary-badge--ok"}>
                  {timelineIssues.length ? `${timelineIssues.length} 个时序问题` : "时序可运行"}
                </span>
                <button className="boundary-chip" onClick={() => onOpenDrawer("timeline", selectedFrameId ? "frame" : "graph", selectedFrameId)} type="button"><span>打开时序抽屉</span></button>
              </div>
            </header>
            <div className="coordination-console-timeline">
              {frames.length ? frames.map((frame) => (
                <button
                  className={selectedFrameId === frame.frame_id ? "coordination-console-phase coordination-console-phase--active" : "coordination-console-phase"}
                  key={frame.frame_id}
                  onClick={() => onOpenDrawer("timeline", "frame", frame.frame_id)}
                  type="button"
                >
                  <strong>{frame.title || frame.frame_id}</strong>
                  <span>{timelineFrameTypeLabel(frame.frame_type)} · {frame.node_ids.length} 节点 · {frame.edge_ids.length} 边</span>
                  <small>{frame.phase_id || frame.timeline_group_id || frame.frame_id}</small>
                </button>
              )) : phaseGroups.map(({ phase, phaseNodes, blockingNodes, parallelNodes, asyncNodes }) => (
                <button
                  className={phase.phase_id === selectedNodePhaseId ? "coordination-console-phase coordination-console-phase--active" : "coordination-console-phase"}
                  key={phase.phase_id}
                  onClick={() => {
                    const firstNode = phaseNodes[0];
                    if (firstNode) onSelectNode(nodeIdOfGraphNode(firstNode));
                  }}
                  type="button"
                >
                  <strong>{phase.title || phase.phase_id}</strong>
                  <span>{phaseNodes.length} 节点 · {blockingNodes.length} 阻塞 · {parallelNodes.length} 并行 · {asyncNodes.length} 异步</span>
                  <small>{phase.review_gate_node_id ? `审核门 ${phase.review_gate_node_id}` : "未绑定审核门"}</small>
                </button>
              ))}
              {!phaseGroups.length && !frames.length ? <div className="boundary-empty">还没有阶段。请在画布选择节点后创建阶段 Frame。</div> : null}
            </div>
          </section>
        ) : null}

        {activeTab === "communication" ? (
          <section className="coordination-console-panel">
            <header>
              <div className="boundary-identity-stack"><span>通信控制台</span><strong>{edges.length} 条交接边</strong></div>
              <button className="boundary-chip" onClick={() => onOpenDrawer("communication", selectedEdgeId ? "edge" : "graph", selectedEdgeId)} type="button"><span>打开通信抽屉</span></button>
            </header>
            <div className="coordination-console-grid">
              <article><span>边数量</span><strong>{edges.length}</strong><small>结构交接总数</small></article>
              <article><span>契约边</span><strong>{edges.filter((edge) => edgeContractId(edge)).length}</strong><small>已绑定交接契约</small></article>
              <article><span>隔离交接</span><strong>{edges.filter((edge) => booleanValue(asRecord(edge.working_memory_handoff_policy).summary_only)).length}</strong><small>只传摘要或引用</small></article>
            </div>
          </section>
        ) : null}

        {activeTab === "review" ? (
          <section className="coordination-console-panel">
            <header>
              <div className="boundary-identity-stack"><span>审核控制台</span><strong>{reviewNodes.length} 个审核相关节点</strong></div>
              <button className="boundary-chip" onClick={() => onOpenDrawer("review", selectedNodeId ? "node" : "graph", selectedNodeId)} type="button"><span>打开审核抽屉</span></button>
            </header>
            <div className="coordination-console-node-strip">
              {reviewNodes.slice(0, 8).map((node, index) => {
                const nodeId = nodeIdOfGraphNode(node, index);
                return <button key={nodeId} onClick={() => onSelectNode(nodeId)} type="button"><strong>{graphNodeLabel(node, index)}</strong><span>{nodeId}</span></button>;
              })}
              {!reviewNodes.length ? <div className="boundary-empty">尚未配置审核门节点。</div> : null}
            </div>
          </section>
        ) : null}

        {activeTab === "loop" ? (
          <section className="coordination-console-panel">
            <header>
              <div className="boundary-identity-stack"><span>循环控制台</span><strong>{loopNodes.length} 个循环节点</strong></div>
              <button className="boundary-chip" onClick={() => onOpenDrawer("loop", selectedNodeId ? "node" : "graph", selectedNodeId)} type="button"><span>打开循环抽屉</span></button>
            </header>
            <div className="coordination-console-grid">
              <article><span>循环节点</span><strong>{loopNodes.length}</strong><small>入口、循环体或出口</small></article>
              <article><span>回边候选</span><strong>{edges.filter((edge) => String(edge.mode ?? edge.policy ?? "").includes("loop")).length}</strong><small>循环通信边</small></article>
              <article><span>最大轮次</span><strong>{loopNodes.reduce((max, node) => Math.max(max, Number(nodeLoopPolicy(node).max_attempts ?? 0)), 0) || "-"}</strong><small>已配置上限</small></article>
            </div>
          </section>
        ) : null}

        {activeTab === "memory" ? (
          <section className="coordination-console-panel">
            <header>
              <div className="boundary-identity-stack"><span>记忆控制台</span><strong>{memoryReadNodes.length + memoryWriteNodes.length} 个读写节点</strong></div>
              <button className="boundary-chip" onClick={() => onOpenDrawer("memory", selectedNodeId ? "node" : "graph", selectedNodeId)} type="button"><span>打开记忆抽屉</span></button>
            </header>
            <div className="coordination-console-grid">
              <article><span>读取节点</span><strong>{memoryReadNodes.length}</strong><small>读取稳定或工作记忆</small></article>
              <article><span>写入节点</span><strong>{memoryWriteNodes.length}</strong><small>候选写回</small></article>
              <article><span>选择集</span><strong>{selectedCount}</strong><small>当前机制目标</small></article>
            </div>
          </section>
        ) : null}

        {activeTab === "artifact" ? (
          <section className="coordination-console-panel">
            <header>
              <div className="boundary-identity-stack"><span>产物控制台</span><strong>{artifactNodes.length} 个节点产物</strong></div>
              <button className="boundary-chip" onClick={() => onOpenDrawer("artifact", selectedNodeId ? "node" : "graph", selectedNodeId)} type="button"><span>打开产物抽屉</span></button>
            </header>
            <div className="coordination-console-grid">
              <article><span>任务根目录</span><strong>{String(asRecord(coordinationDraft.metadata).artifact_root ?? "未配置")}</strong><small>图级落盘策略</small></article>
              <article><span>产物节点</span><strong>{artifactNodes.length}</strong><small>有显式产物配置</small></article>
              <article><span>运行目录</span><strong>{String(asRecord(coordinationDraft.metadata).run_output_policy ?? "按 run 生成")}</strong><small>建议独立落盘</small></article>
            </div>
          </section>
        ) : null}

        {activeTab === "preflight" ? (
          <section className="coordination-console-panel">
            <header>
              <div className="boundary-identity-stack"><span>预检控制台</span><strong>{timelineIssues.length + graphIssues.length} 个问题</strong></div>
              <button className="boundary-chip" onClick={() => onOpenDrawer("preflight", "graph")} type="button"><span>打开预检抽屉</span></button>
            </header>
            <div className="coordination-console-issue-strip">
              {[...timelineIssues.map((issue) => String(issue.message ?? issue.code ?? "时序问题")), ...graphIssues.map((issue) => String(issue.message ?? issue.code ?? "图问题"))].slice(0, 4).map((issue, index) => (
                <span key={`${issue}-${index}`}>{issue}</span>
              ))}
              {!timelineIssues.length && !graphIssues.length ? <span>当前没有阻塞问题。</span> : null}
            </div>
          </section>
        ) : null}

        {activeTab === "runtime" ? (
          <section className="coordination-console-panel">
            <header>
              <div className="boundary-identity-stack"><span>运行控制台</span><strong>{selectedNodeId || selectedEdgeId || "未选中运行对象"}</strong></div>
              <button className="boundary-chip" onClick={() => onOpenDrawer("runtime", selectedNodeId ? "node" : "graph", selectedNodeId)} type="button"><span>打开运行抽屉</span></button>
            </header>
            <div className="coordination-console-grid">
              <article><span>发布状态</span><strong>{coordinationDraft.enabled ? "可运行" : "草稿"}</strong><small>任务图发布标记</small></article>
              <article><span>节点</span><strong>{nodes.length}</strong><small>待装配执行单元</small></article>
              <article><span>通信边</span><strong>{edges.length}</strong><small>运行交接路径</small></article>
            </div>
          </section>
        ) : null}
      </div>
    </section>
  );
}

function CoordinationMechanismDrawer({
  a2aCatalog,
  drawer,
  activeGraphNodes,
  agentCardOptions,
  coordinationDraft,
  contractSpecs,
  domainTaskOptions,
  formatAgentCard,
  formatContract,
  formatNodeOption,
  formatProjection,
  nodeIdOptions,
  phaseDefinitions,
  projectionCards,
  protocolDraft,
  setCoordinationDraft,
  setProtocolDraft,
  setTopologyDraft,
  topologyDraft,
  selectedGraphNode,
  selectedGraphEdge,
  selectedDomain,
  selectedDomainTasks,
  updateCoordinationEdge,
  updateCoordinationNode,
  onClose,
}: {
  a2aCatalog: A2ACatalogLike | null;
  drawer: MechanismDrawerState;
  activeGraphNodes: Array<Record<string, unknown>>;
  agentCardOptions: string[];
  contractSpecs: ContractSpec[];
  domainTaskOptions: Array<{ value: string; label: string }>;
  formatAgentCard: (agentId: string) => string;
  formatContract: (contractId: string) => string;
  formatNodeOption: (nodeId: string) => string;
  formatProjection: (projectionId: string) => string;
  nodeIdOptions: string[];
  phaseDefinitions: ReturnType<typeof coordinationPhaseDefinitions>;
  projectionCards: ProjectionCardLike[];
  protocolDraft: ProtocolDraftLike;
  setCoordinationDraft: Dispatch<SetStateAction<CoordinationDraftLike>>;
  setProtocolDraft: Dispatch<SetStateAction<ProtocolDraftLike>>;
  setTopologyDraft: Dispatch<SetStateAction<TopologyDraftLike>>;
  topologyDraft: TopologyDraftLike;
  selectedGraphNode: Record<string, unknown> | null;
  selectedGraphEdge: Record<string, unknown> | null;
  selectedDomain: DomainRecordLike | null;
  selectedDomainTasks: SpecificTaskRecord[];
  coordinationDraft: CoordinationDraftLike;
  updateCoordinationEdge: (edgeId: string, patch: Record<string, unknown>) => void;
  updateCoordinationNode: (nodeId: string, patch: Record<string, unknown>) => void;
  onClose: () => void;
}) {
  if (!drawer.open) return null;
  const nodeId = String(selectedGraphNode?.node_id ?? "");
  const edgeId = selectedGraphEdge ? graphEdgeId(selectedGraphEdge) : "";
  const nodeReviewPolicy = selectedGraphNode ? nodeReviewGatePolicy(selectedGraphNode) : {};
  const nodeLoopSettings = selectedGraphNode ? nodeLoopPolicy(selectedGraphNode) : {};
  const selectedNodeReadPolicy = asRecord(selectedGraphNode?.memory_read_policy);
  const selectedNodeWritePolicy = asRecord(selectedGraphNode?.memory_writeback_policy);
  const selectedNodeDynamicReadPolicy = asRecord(selectedGraphNode?.dynamic_memory_read_policy);
  const selectedNodeBackgroundPolicy = asRecord(selectedGraphNode?.background_policy);
  const selectedNodeNotificationPolicy = asRecord(selectedGraphNode?.notification_policy);
  const selectedNodeLifecyclePolicy = asRecord(selectedGraphNode?.resource_lifecycle_policy);
  const selectedEdgeWorkingMemoryPolicy = asRecord(selectedGraphEdge?.working_memory_handoff_policy);
  const coordinationMetadata = asRecord(coordinationDraft.metadata);
  const graphLifecyclePolicy = asRecord(coordinationMetadata.lifecycle_policy);
  const graphTimelinePolicy = asRecord(coordinationMetadata.timeline_policy);
  const graphMemoryPolicy = asRecord(coordinationMetadata.working_memory_policy);
  const graphArtifactPolicy = asRecord(coordinationMetadata.artifact_policy);
  const graphRuntimePolicy = asRecord(coordinationMetadata.runtime_policy);
  const graphReviewPolicy = asRecord(coordinationMetadata.review_policy);
  const graphLoopPolicy = asRecord(coordinationMetadata.loop_policy);
  const graphTimelineFrames = coordinationTimelineFrames(coordinationMetadata);
  const selectedTimelineFrame = drawer.target_object_type === "frame"
    ? graphTimelineFrames.find((frame) => frame.frame_id === drawer.target_object_id) ?? null
    : null;
  const selectedNodeArtifactPolicy = asRecord(selectedGraphNode?.artifact_policy);
  const selectedEdgeRuntimePolicy = asRecord(selectedGraphEdge?.runtime_policy);
  const graphPhaseDrafts = phaseDraftsFromMetadata(coordinationMetadata, activeGraphNodes);
  const graphPreflightIssues = buildTimelinePreflightIssues(activeGraphNodes, selectedGraphEdge ? [selectedGraphEdge] : [], coordinationMetadata);
  const selectedEdgePreview = selectedGraphEdge ? edgeA2APreview({
    catalog: a2aCatalog,
    coordinationDraft,
    edge: selectedGraphEdge,
    protocolDraft,
    sourceNode: activeGraphNodes.find((node) => String(node.node_id ?? "") === graphEdgeSource(selectedGraphEdge)) ?? null,
    targetNode: activeGraphNodes.find((node) => String(node.node_id ?? "") === graphEdgeTarget(selectedGraphEdge)) ?? null,
  }) : null;
  function updateTimelineFrame(frameId: string, patch: Partial<TaskGraphTimelineFrame>) {
    setCoordinationDraft((current) => {
      const currentMetadata = asRecord(current.metadata);
      const currentFrames = coordinationTimelineFrames(currentMetadata);
      return {
        ...current,
        metadata: {
          ...currentMetadata,
          timeline_frames: currentFrames.map((frame) => (frame.frame_id === frameId ? { ...frame, ...patch } : frame)),
        },
      };
    });
  }
  function deleteTimelineFrame(frameId: string) {
    setCoordinationDraft((current) => {
      const currentMetadata = asRecord(current.metadata);
      const currentFrames = coordinationTimelineFrames(currentMetadata);
      return {
        ...current,
        metadata: {
          ...currentMetadata,
          timeline_frames: currentFrames.filter((frame) => frame.frame_id !== frameId),
        },
      };
    });
  }
  function applyTimelineFrameToNodes(frame: TaskGraphTimelineFrame) {
    frame.node_ids.forEach((targetNodeId, index) => {
      const node = activeGraphNodes.find((item) => String(item.node_id ?? "") === targetNodeId);
      const basePatch: Record<string, unknown> = {
        phase_id: frame.phase_id || nodePhaseId(node ?? {}),
      };
      if (frame.sequence_index) basePatch.sequence_index = frame.sequence_index + index;
      if (frame.timeline_group_id) basePatch.timeline_group_id = frame.timeline_group_id;
      if (frame.frame_type === "parallel_frame") {
        basePatch.execution_mode = "parallel";
        basePatch.dispatch_group = frame.timeline_group_id || frame.frame_id;
      }
      if (frame.frame_type === "loop_frame") {
        basePatch.loop_policy = {
          ...nodeLoopPolicy(node ?? {}),
          ...asRecord(frame.loop_policy),
          loop_role: index === 0 ? "loop_entry" : index === frame.node_ids.length - 1 ? "loop_exit" : "loop_body",
        };
      }
      if (frame.frame_type === "review_gate_frame") {
        basePatch.node_type = targetNodeId === frame.review_gate_node_id ? "review_gate" : String(node?.node_type ?? "agent_role");
        basePatch.review_gate_policy = {
          ...nodeReviewGatePolicy(node ?? {}),
          is_review_gate: targetNodeId === frame.review_gate_node_id,
          on_fail: frame.node_ids[0] ?? "",
          on_pass: frame.node_ids[frame.node_ids.length - 1] ?? "",
        };
      }
      updateCoordinationNode(targetNodeId, basePatch);
    });
  }
  const targetLabel = drawer.target_object_type === "node"
    ? String((selectedGraphNode?.label ?? selectedGraphNode?.title ?? drawer.target_object_id) || "节点")
    : drawer.target_object_type === "edge"
      ? String((selectedGraphEdge?.label ?? selectedGraphEdge?.mode ?? drawer.target_object_id) || "通信边")
      : drawer.target_object_type === "frame"
        ? selectedTimelineFrame?.title || drawer.target_object_id || "Frame"
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
          <article><span>抽屉类型</span><strong>{drawer.drawer_type}</strong><small>机制分类</small></article>
        </div>

        {drawer.drawer_type === "agent" && selectedGraphNode ? (
          <section className="boundary-inspector-subblock">
            <header><strong>Agent 与任务身份</strong><span>{nodeId}</span></header>
            <TaskSystemField label="节点名称"><input value={String(selectedGraphNode.label ?? selectedGraphNode.title ?? graphNodeLabel(selectedGraphNode, 0))} onChange={(event) => updateCoordinationNode(nodeId, { label: event.target.value, title: event.target.value })} /></TaskSystemField>
            <TaskSystemDomainTaskSelectField
              label="绑定分任务"
              onChange={(value) => {
                const task = selectedDomainTasks.find((item) => item.task_id === value);
                updateCoordinationNode(nodeId, {
                  node_type: value ? "subtask" : "agent_role",
                  task_id: value,
                  task_title: task?.task_title ?? "",
                  task_family: task?.task_family ?? selectedDomain?.task_family ?? "",
                  label: task?.task_title ?? String(selectedGraphNode.label ?? ""),
                  title: task?.task_title ?? String(selectedGraphNode.title ?? selectedGraphNode.label ?? ""),
                });
              }}
              options={domainTaskOptions}
              value={graphNodeTaskId(selectedGraphNode)}
            />
            <TaskSystemSelectField
              label="工作姿态"
              onChange={(value) => updateCoordinationNode(nodeId, {
                role: value,
                work_posture: value,
                node_type: value === "memory" ? "memory" : "agent_role",
                agent_id: value === "memory" ? "builtin:memory_steward" : String(selectedGraphNode.agent_id ?? ""),
              })}
              options={["coordinator", "planner", "executor", "reviewer", "verifier", "summarizer", "merge", "memory"]}
              value={String(selectedGraphNode.work_posture ?? selectedGraphNode.role ?? "executor")}
              formatOption={taskSystemOptionLabel}
            />
            <TaskSystemSelectField label="绑定 Agent" onChange={(value) => updateCoordinationNode(nodeId, { agent_id: value })} options={agentCardOptions} value={String(selectedGraphNode.agent_id ?? "")} formatOption={formatAgentCard} />
            <TaskSystemField label="运行通道"><input value={String(selectedGraphNode.runtime_lane ?? selectedGraphNode.lane ?? "")} onChange={(event) => updateCoordinationNode(nodeId, { runtime_lane: event.target.value, lane: event.target.value })} /></TaskSystemField>
          </section>
        ) : null}

        {drawer.drawer_type === "agent" && drawer.target_object_type === "graph" ? (
          <section className="boundary-inspector-subblock">
            <header><strong>任务图基础</strong><span>图身份</span></header>
            <TaskSystemField label="任务图标题"><input value={coordinationDraft.title} onChange={(event) => setCoordinationDraft((current) => ({ ...current, title: event.target.value }))} /></TaskSystemField>
            <div className="boundary-kv coordination-inspector-kv">
              <p><span>任务图 ID</span><strong>{coordinationDraft.coordination_task_id}</strong></p>
            </div>
            <TaskSystemSelectField label="协作模式" onChange={(value) => setCoordinationDraft((current) => ({ ...current, coordination_mode: value }))} options={COORDINATION_MODE_CHOICES} value={coordinationDraft.coordination_mode} formatOption={taskSystemOptionLabel} />
            <TaskSystemField label="Agent 组"><input value={coordinationDraft.agent_group_id} onChange={(event) => setCoordinationDraft((current) => ({ ...current, agent_group_id: event.target.value }))} /></TaskSystemField>
            <TaskSystemField label="共享上下文策略"><input value={coordinationDraft.shared_context_policy} onChange={(event) => setCoordinationDraft((current) => ({ ...current, shared_context_policy: event.target.value }))} /></TaskSystemField>
            <TaskSystemField label="交接策略"><input value={coordinationDraft.handoff_policy} onChange={(event) => setCoordinationDraft((current) => ({ ...current, handoff_policy: event.target.value }))} /></TaskSystemField>
            <TaskSystemField label="停止条件" wide><textarea value={coordinationDraft.stop_conditions_text} onChange={(event) => setCoordinationDraft((current) => ({ ...current, stop_conditions_text: event.target.value }))} /></TaskSystemField>
          </section>
        ) : null}

        {drawer.drawer_type === "contract" && selectedGraphNode ? (
          <section className="boundary-inspector-subblock">
            <header><strong>节点投影与契约</strong><span>投影 / 契约</span></header>
            <TaskSystemSelectField
              label="节点投影"
              onChange={(value) => updateCoordinationNode(nodeId, { projection_id: value })}
              options={projectionOptions(projectionCards, String(selectedGraphNode.projection_id ?? ""))}
              value={String(selectedGraphNode.projection_id ?? "")}
              formatOption={formatProjection}
            />
            <TaskSystemSelectField
              label="节点契约"
              onChange={(value) => updateCoordinationNode(nodeId, { node_contract_id: value, contract_id: value })}
              options={contractOptions(contractSpecs, nodeContractId(selectedGraphNode), ["node_execution", "workflow_step", "runtime"])}
              value={nodeContractId(selectedGraphNode)}
              formatOption={formatContract}
            />
          </section>
        ) : null}

        {drawer.drawer_type === "contract" && drawer.target_object_type === "graph" ? (
          <section className="boundary-inspector-subblock">
            <header><strong>图级投影与契约概览</strong><span>图绑定</span></header>
            <div className="coordination-console-grid">
              <article><span>可用投影</span><strong>{projectionCards.length}</strong><small>节点可按阶段覆盖</small></article>
              <article><span>可用契约</span><strong>{contractSpecs.length}</strong><small>节点、边和运行契约</small></article>
              <article><span>已绑定节点</span><strong>{activeGraphNodes.filter((node) => String(node.projection_id ?? node.contract_id ?? node.node_contract_id ?? "").trim()).length}</strong><small>存在显式绑定</small></article>
            </div>
            <p>图级不再提供默认投影覆盖。运行时应以节点绑定优先，其次使用 Agent 自身投影；未绑定节点会在预检中暴露。</p>
          </section>
        ) : null}

        {drawer.drawer_type === "timeline" && selectedGraphNode ? (
          <section className="boundary-inspector-subblock">
            <header><strong>时序与调度</strong><span>时序 / 调度</span></header>
            <TaskSystemSelectField label="所属阶段" onChange={(value) => updateCoordinationNode(nodeId, { phase_id: value })} options={phaseDefinitions.map((phase) => phase.phase_id)} value={nodePhaseId(selectedGraphNode)} formatOption={(value) => phaseDefinitions.find((phase) => phase.phase_id === value)?.title || value} />
            <TaskSystemField label="时序点"><input min={1} onChange={(event) => updateCoordinationNode(nodeId, { sequence_index: Number(event.target.value || 1) })} type="number" value={nodeSequenceIndex(selectedGraphNode)} /></TaskSystemField>
            <TaskSystemField label="并行组"><input onChange={(event) => updateCoordinationNode(nodeId, { timeline_group_id: event.target.value })} placeholder="例如 chapter.review" value={nodeTimelineGroupId(selectedGraphNode)} /></TaskSystemField>
            <TaskSystemField label="完成策略"><input onChange={(event) => updateCoordinationNode(nodeId, { completion_policy: event.target.value })} placeholder="contract_output_ready" value={String(selectedGraphNode.completion_policy ?? asRecord(selectedGraphNode.metadata).completion_policy ?? "")} /></TaskSystemField>
            <TaskSystemSelectField label="执行模式" onChange={(value) => updateCoordinationNode(nodeId, { execution_mode: value })} options={NODE_EXECUTION_MODE_OPTIONS} value={String(selectedGraphNode.execution_mode ?? "sync")} formatOption={taskSystemOptionLabel} />
            <TaskSystemSelectField label="等待策略" onChange={(value) => updateCoordinationNode(nodeId, { wait_policy: value })} options={NODE_WAIT_POLICY_OPTIONS} value={String(selectedGraphNode.wait_policy ?? "wait_all_upstream_completed")} formatOption={taskSystemOptionLabel} />
            <TaskSystemSelectField label="汇合策略" onChange={(value) => updateCoordinationNode(nodeId, { join_policy: value })} options={NODE_JOIN_POLICY_OPTIONS} value={String(selectedGraphNode.join_policy ?? "all_success")} formatOption={taskSystemOptionLabel} />
            <label className="boundary-check"><input checked={nodeMainChain(selectedGraphNode)} onChange={(event) => updateCoordinationNode(nodeId, { main_chain: event.target.checked })} type="checkbox" />主链节点</label>
            <label className="boundary-check"><input checked={nodeBlocksPhaseExit(selectedGraphNode)} onChange={(event) => updateCoordinationNode(nodeId, { blocks_phase_exit: event.target.checked })} type="checkbox" />阻塞阶段退出</label>
          </section>
        ) : null}

        {drawer.drawer_type === "timeline" && drawer.target_object_type === "graph" ? (
          <section className="boundary-inspector-subblock">
            <header><strong>图级时序</strong><span>时序策略</span></header>
            <TaskSystemField label="生命周期 ID"><input value={String(graphLifecyclePolicy.lifecycle_id ?? "")} onChange={(event) => setNestedMetadataValue(setCoordinationDraft, "lifecycle_policy", { lifecycle_id: event.target.value })} /></TaskSystemField>
            <TaskSystemField label="主链模式"><input value={String(graphLifecyclePolicy.main_chain_mode ?? "phase_sequence")} onChange={(event) => setNestedMetadataValue(setCoordinationDraft, "lifecycle_policy", { main_chain_mode: event.target.value })} /></TaskSystemField>
            <TaskSystemSelectField label="排序策略" onChange={(value) => setNestedMetadataValue(setCoordinationDraft, "timeline_policy", { ordering: value })} options={["phase_then_sequence_index", "explicit_edges", "manual_sequence"]} value={String(graphTimelinePolicy.ordering ?? "phase_then_sequence_index")} formatOption={taskSystemOptionLabel} />
            <TaskSystemSelectField label="并行策略" onChange={(value) => setNestedMetadataValue(setCoordinationDraft, "timeline_policy", { parallel_group_policy: value })} options={["same_sequence_or_group", "explicit_parallel_frame", "manual_dispatch_group"]} value={String(graphTimelinePolicy.parallel_group_policy ?? "same_sequence_or_group")} formatOption={taskSystemOptionLabel} />
            <TaskSystemSelectField label="阶段出口策略" onChange={(value) => setNestedMetadataValue(setCoordinationDraft, "timeline_policy", { phase_exit_policy: value })} options={["all_blocking_nodes_complete", "review_gate_passed", "artifact_ready"]} value={String(graphTimelinePolicy.phase_exit_policy ?? "all_blocking_nodes_complete")} formatOption={taskSystemOptionLabel} />
            <div className="coordination-drawer-list">
              {graphPhaseDrafts.map((phase) => (
                <article key={phase.phase_id}>
                  <header><strong>{phase.title || phase.phase_id}</strong><span>{phase.phase_id}</span></header>
                  <TaskSystemField label="阶段标题"><input value={phase.title} onChange={(event) => setMetadataValue(setCoordinationDraft, "phase_definitions", updatePhaseDraft(graphPhaseDrafts, phase.phase_id, { title: event.target.value }))} /></TaskSystemField>
                  <TaskSystemSelectField label="入口节点" onChange={(value) => setMetadataValue(setCoordinationDraft, "phase_definitions", updatePhaseDraft(graphPhaseDrafts, phase.phase_id, { entry_node_id: value }))} options={nodeIdOptions} value={String(phase.entry_node_id ?? "")} formatOption={formatNodeOption} />
                  <TaskSystemSelectField label="出口节点" onChange={(value) => setMetadataValue(setCoordinationDraft, "phase_definitions", updatePhaseDraft(graphPhaseDrafts, phase.phase_id, { exit_node_id: value }))} options={nodeIdOptions} value={String(phase.exit_node_id ?? "")} formatOption={formatNodeOption} />
                  <TaskSystemSelectField label="审核门" onChange={(value) => setMetadataValue(setCoordinationDraft, "phase_definitions", updatePhaseDraft(graphPhaseDrafts, phase.phase_id, { review_gate_node_id: value }))} options={nodeIdOptions} value={String(phase.review_gate_node_id ?? "")} formatOption={formatNodeOption} />
                </article>
              ))}
            </div>
          </section>
        ) : null}

        {drawer.drawer_type === "timeline" && selectedTimelineFrame ? (
          <section className="boundary-inspector-subblock">
            <header><strong>时序 Frame</strong><span>{selectedTimelineFrame.frame_id}</span></header>
            <TaskSystemField label="时序框标题"><input value={selectedTimelineFrame.title} onChange={(event) => updateTimelineFrame(selectedTimelineFrame.frame_id, { title: event.target.value })} /></TaskSystemField>
            <TaskSystemSelectField label="时序框类型" onChange={(value) => updateTimelineFrame(selectedTimelineFrame.frame_id, { frame_type: value as TimelineFrameType })} options={[...TIMELINE_FRAME_TYPES]} value={selectedTimelineFrame.frame_type} formatOption={timelineFrameTypeOptionLabel} />
            <TaskSystemSelectField label="所属阶段" onChange={(value) => updateTimelineFrame(selectedTimelineFrame.frame_id, { phase_id: value || undefined })} options={["", ...phaseDefinitions.map((phase) => phase.phase_id)]} value={selectedTimelineFrame.phase_id ?? ""} formatOption={(value) => value ? phaseDefinitions.find((phase) => phase.phase_id === value)?.title || value : "不绑定阶段"} />
            <TaskSystemField label="时序点"><input min={1} onChange={(event) => updateTimelineFrame(selectedTimelineFrame.frame_id, { sequence_index: Number(event.target.value || 1) })} type="number" value={Number(selectedTimelineFrame.sequence_index ?? 1)} /></TaskSystemField>
            <TaskSystemField label="并行/批次组"><input value={selectedTimelineFrame.timeline_group_id ?? ""} onChange={(event) => updateTimelineFrame(selectedTimelineFrame.frame_id, { timeline_group_id: event.target.value || undefined })} /></TaskSystemField>
            <TaskSystemMultiSelectField label="包含节点" onChange={(value) => updateTimelineFrame(selectedTimelineFrame.frame_id, { node_ids: value })} options={nodeIdOptions.filter(Boolean)} value={selectedTimelineFrame.node_ids} wide formatOption={formatNodeOption} />
            <TaskSystemField label="包含通信边" wide><textarea value={selectedTimelineFrame.edge_ids.join("\n")} onChange={(event) => updateTimelineFrame(selectedTimelineFrame.frame_id, { edge_ids: event.target.value.split(/[\n,，]/).map((item) => item.trim()).filter(Boolean) })} /></TaskSystemField>
            <div className="coordination-inspector-actions">
              <button className="boundary-chip" onClick={() => applyTimelineFrameToNodes(selectedTimelineFrame)} type="button"><span>应用到节点</span></button>
              <button
                className="boundary-chip"
                onClick={() => {
                  if (window.confirm("确认删除这个时序 Frame 吗？节点和通信边不会被删除。")) {
                    deleteTimelineFrame(selectedTimelineFrame.frame_id);
                    onClose();
                  }
                }}
                type="button"
              >
                <span>删除 Frame</span>
              </button>
            </div>
          </section>
        ) : null}

        {drawer.drawer_type === "review" && selectedGraphNode ? (
          <section className="boundary-inspector-subblock">
            <header><strong>节点审核门</strong><span>审核门</span></header>
            <label className="boundary-check"><input checked={booleanValue(nodeReviewPolicy.is_review_gate)} onChange={(event) => updateCoordinationNode(nodeId, { review_gate_policy: { ...nodeReviewPolicy, is_review_gate: event.target.checked } })} type="checkbox" />作为阶段审核门</label>
            <TaskSystemField label="通过线"><input max={100} min={0} onChange={(event) => updateCoordinationNode(nodeId, { review_gate_policy: { ...nodeReviewPolicy, pass_score: Number(event.target.value || 0) } })} type="number" value={Number(nodeReviewPolicy.pass_score ?? 85)} /></TaskSystemField>
            <TaskSystemSelectField label="通过后" onChange={(value) => updateCoordinationNode(nodeId, { review_gate_policy: { ...nodeReviewPolicy, on_pass: value } })} options={nodeIdOptions} value={String(nodeReviewPolicy.on_pass ?? "")} formatOption={formatNodeOption} />
            <TaskSystemSelectField label="失败后" onChange={(value) => updateCoordinationNode(nodeId, { review_gate_policy: { ...nodeReviewPolicy, on_fail: value } })} options={nodeIdOptions} value={String(nodeReviewPolicy.on_fail ?? "")} formatOption={formatNodeOption} />
            <TaskSystemSelectField label="严重偏差" onChange={(value) => updateCoordinationNode(nodeId, { review_gate_policy: { ...nodeReviewPolicy, on_severe_drift: value } })} options={nodeIdOptions} value={String(nodeReviewPolicy.on_severe_drift ?? "")} formatOption={formatNodeOption} />
          </section>
        ) : null}

        {drawer.drawer_type === "review" && drawer.target_object_type === "graph" ? (
          <section className="boundary-inspector-subblock">
            <header><strong>图级审核策略</strong><span>审核策略</span></header>
            <TaskSystemSelectField label="审核模式" onChange={(value) => setNestedMetadataValue(setCoordinationDraft, "review_policy", { review_mode: value })} options={["review_gate", "dual_creator_single_judge", "stage_specific_reviewer", "manual_review"]} value={String(graphReviewPolicy.review_mode ?? "review_gate")} formatOption={taskSystemOptionLabel} />
            <TaskSystemField label="默认通过线"><input max={100} min={0} type="number" value={Number(graphReviewPolicy.default_pass_score ?? 85)} onChange={(event) => setNestedMetadataValue(setCoordinationDraft, "review_policy", { default_pass_score: Number(event.target.value || 0) })} /></TaskSystemField>
            <TaskSystemSelectField label="审核失败后" onChange={(value) => setNestedMetadataValue(setCoordinationDraft, "review_policy", { default_on_fail: value })} options={["revise_previous", "return_to_author_pair", "pause_for_human", "continue_with_warning"]} value={String(graphReviewPolicy.default_on_fail ?? "revise_previous")} formatOption={taskSystemOptionLabel} />
            <label className="boundary-check"><input checked={booleanValue(graphReviewPolicy.reviewer_memoryless, true)} onChange={(event) => setNestedMetadataValue(setCoordinationDraft, "review_policy", { reviewer_memoryless: event.target.checked })} type="checkbox" />审核员不存长期上下文，只依据输入材料仲裁</label>
            <label className="boundary-check"><input checked={booleanValue(graphReviewPolicy.require_contract_bound_reviewer, true)} onChange={(event) => setNestedMetadataValue(setCoordinationDraft, "review_policy", { require_contract_bound_reviewer: event.target.checked })} type="checkbox" />不同阶段必须使用节点绑定的审核契约</label>
          </section>
        ) : null}

        {drawer.drawer_type === "review" && selectedTimelineFrame ? (
          <section className="boundary-inspector-subblock">
            <header><strong>Frame 审核门</strong><span>{selectedTimelineFrame.frame_id}</span></header>
            <TaskSystemSelectField label="审核门节点" onChange={(value) => updateTimelineFrame(selectedTimelineFrame.frame_id, { review_gate_node_id: value || undefined })} options={nodeIdOptions} value={selectedTimelineFrame.review_gate_node_id ?? ""} formatOption={formatNodeOption} />
            <p>Frame 只记录审核边界。审核员的投影、契约、通过线与返修路线仍绑定在审核节点上，避免把节点能力混入时序结构。</p>
          </section>
        ) : null}

        {drawer.drawer_type === "loop" && selectedGraphNode ? (
          <section className="boundary-inspector-subblock">
            <header><strong>节点循环策略</strong><span>循环</span></header>
            <TaskSystemSelectField label="循环角色" onChange={(value) => updateCoordinationNode(nodeId, { loop_policy: { ...nodeLoopSettings, loop_role: value } })} options={["loop_entry", "loop_body", "loop_exit", "revision_target", "judge_gate"]} value={String(nodeLoopSettings.loop_role ?? "")} formatOption={taskSystemOptionLabel} />
            <TaskSystemField label="最大尝试"><input min={0} onChange={(event) => updateCoordinationNode(nodeId, { loop_policy: { ...nodeLoopSettings, max_attempts: Number(event.target.value || 0) } })} type="number" value={Number(nodeLoopSettings.max_attempts ?? 0)} /></TaskSystemField>
            <TaskSystemField label="退出条件"><input value={String(nodeLoopSettings.exit_condition ?? "")} onChange={(event) => updateCoordinationNode(nodeId, { loop_policy: { ...nodeLoopSettings, exit_condition: event.target.value } })} placeholder="例如 review_gate_passed" /></TaskSystemField>
            <TaskSystemSelectField label="退出后节点" onChange={(value) => updateCoordinationNode(nodeId, { loop_policy: { ...nodeLoopSettings, exit_node_id: value } })} options={nodeIdOptions} value={String(nodeLoopSettings.exit_node_id ?? "")} formatOption={formatNodeOption} />
          </section>
        ) : null}

        {drawer.drawer_type === "loop" && drawer.target_object_type === "graph" ? (
          <section className="boundary-inspector-subblock">
            <header><strong>图级循环策略</strong><span>循环策略</span></header>
            <TaskSystemField label="目标章节数"><input min={0} type="number" value={Number(graphLoopPolicy.chapter_count ?? 0)} onChange={(event) => setNestedMetadataValue(setCoordinationDraft, "loop_policy", { chapter_count: Number(event.target.value || 0) })} /></TaskSystemField>
            <TaskSystemField label="目标字数"><input min={0} type="number" value={Number(graphLoopPolicy.target_words ?? 0)} onChange={(event) => setNestedMetadataValue(setCoordinationDraft, "loop_policy", { target_words: Number(event.target.value || 0) })} /></TaskSystemField>
            <TaskSystemField label="每章目标字数"><input min={0} type="number" value={Number(graphLoopPolicy.words_per_chapter ?? 0)} onChange={(event) => setNestedMetadataValue(setCoordinationDraft, "loop_policy", { words_per_chapter: Number(event.target.value || 0) })} /></TaskSystemField>
            <TaskSystemField label="全局退出条件"><input value={String(graphLoopPolicy.exit_condition ?? "")} onChange={(event) => setNestedMetadataValue(setCoordinationDraft, "loop_policy", { exit_condition: event.target.value })} placeholder="例如 planned_work_complete" /></TaskSystemField>
          </section>
        ) : null}

        {drawer.drawer_type === "loop" && selectedTimelineFrame ? (
          <section className="boundary-inspector-subblock">
            <header><strong>Frame 循环策略</strong><span>{selectedTimelineFrame.frame_id}</span></header>
            <TaskSystemField label="最大轮次"><input min={0} type="number" value={Number(asRecord(selectedTimelineFrame.loop_policy).max_attempts ?? 0)} onChange={(event) => updateTimelineFrame(selectedTimelineFrame.frame_id, { loop_policy: { ...asRecord(selectedTimelineFrame.loop_policy), max_attempts: Number(event.target.value || 0) } })} /></TaskSystemField>
            <TaskSystemField label="退出条件"><input value={String(asRecord(selectedTimelineFrame.loop_policy).exit_condition ?? "")} onChange={(event) => updateTimelineFrame(selectedTimelineFrame.frame_id, { loop_policy: { ...asRecord(selectedTimelineFrame.loop_policy), exit_condition: event.target.value } })} /></TaskSystemField>
            <TaskSystemSelectField label="审核门节点" onChange={(value) => updateTimelineFrame(selectedTimelineFrame.frame_id, { review_gate_node_id: value || undefined })} options={nodeIdOptions} value={selectedTimelineFrame.review_gate_node_id ?? ""} formatOption={formatNodeOption} />
          </section>
        ) : null}

        {drawer.drawer_type === "memory" && selectedGraphNode ? (
          <>
            <section className="boundary-inspector-subblock">
              <header><strong>节点工作记忆读取</strong><span>读取</span></header>
              <TaskSystemMultiSelectField label="可读 Kind" onChange={(value) => updateCoordinationNode(nodeId, { memory_read_policy: updatePolicyList(selectedNodeReadPolicy, "readable_kinds", value) })} options={WORKING_MEMORY_KIND_OPTIONS} value={asStringList(selectedNodeReadPolicy.readable_kinds)} wide formatOption={taskSystemOptionLabel} />
              <TaskSystemMultiSelectField label="可读 Scope" onChange={(value) => updateCoordinationNode(nodeId, { memory_read_policy: updatePolicyList(selectedNodeReadPolicy, "readable_scopes", value) })} options={WORKING_MEMORY_SCOPE_OPTIONS} value={asStringList(selectedNodeReadPolicy.readable_scopes)} wide formatOption={taskSystemOptionLabel} />
              <TaskSystemMultiSelectField label="语义过滤" onChange={(value) => updateCoordinationNode(nodeId, { memory_read_policy: updatePolicyList(selectedNodeReadPolicy, "readable_semantics", value) })} options={WORKING_MEMORY_SEMANTIC_OPTIONS} value={asStringList(selectedNodeReadPolicy.readable_semantics)} wide formatOption={taskSystemOptionLabel} />
            </section>
            <section className="boundary-inspector-subblock">
              <header><strong>节点工作记忆写入</strong><span>写回</span></header>
              <TaskSystemMultiSelectField label="可写 Kind" onChange={(value) => updateCoordinationNode(nodeId, { memory_writeback_policy: updatePolicyList(selectedNodeWritePolicy, "writable_kinds", value) })} options={WORKING_MEMORY_KIND_OPTIONS} value={asStringList(selectedNodeWritePolicy.writable_kinds)} wide formatOption={taskSystemOptionLabel} />
              <TaskSystemMultiSelectField label="可写 Scope" onChange={(value) => updateCoordinationNode(nodeId, { memory_writeback_policy: updatePolicyList(selectedNodeWritePolicy, "writable_scopes", value) })} options={WORKING_MEMORY_SCOPE_OPTIONS} value={asStringList(selectedNodeWritePolicy.writable_scopes)} wide formatOption={taskSystemOptionLabel} />
              <TaskSystemSelectField label="默认可见性" onChange={(value) => updateCoordinationNode(nodeId, { memory_writeback_policy: { ...selectedNodeWritePolicy, default_visibility: value } })} options={WORKING_MEMORY_VISIBILITY_OPTIONS} value={String(selectedNodeWritePolicy.default_visibility ?? "private_to_node")} formatOption={taskSystemOptionLabel} />
              <label className="boundary-check"><input checked={booleanValue(selectedNodeWritePolicy.requires_coordinator_review, true)} onChange={(event) => updateCoordinationNode(nodeId, { memory_writeback_policy: { ...selectedNodeWritePolicy, requires_coordinator_review: event.target.checked } })} type="checkbox" />写入候选需要协调者采纳</label>
            </section>
            <section className="boundary-inspector-subblock">
              <header><strong>动态读取</strong><span>动态</span></header>
              <label className="boundary-check"><input checked={booleanValue(selectedNodeDynamicReadPolicy.allow_dynamic_read)} onChange={(event) => updateCoordinationNode(nodeId, { dynamic_memory_read_policy: { ...selectedNodeDynamicReadPolicy, allow_dynamic_read: event.target.checked } })} type="checkbox" />允许该节点动态读取工作记忆</label>
              <TaskSystemField label="读取次数上限"><input min={0} onChange={(event) => updateCoordinationNode(nodeId, { dynamic_memory_read_policy: { ...selectedNodeDynamicReadPolicy, max_dynamic_reads_per_node_run: Number(event.target.value || 0) } })} type="number" value={Number(selectedNodeDynamicReadPolicy.max_dynamic_reads_per_node_run ?? 0)} /></TaskSystemField>
              <label className="boundary-check"><input checked={booleanValue(selectedNodeDynamicReadPolicy.allow_temporal_expansion)} onChange={(event) => updateCoordinationNode(nodeId, { dynamic_memory_read_policy: { ...selectedNodeDynamicReadPolicy, allow_temporal_expansion: event.target.checked } })} type="checkbox" />允许读取 temporal 邻接工作记忆</label>
              <TaskSystemField label="时序扩展深度"><input min={0} onChange={(event) => updateCoordinationNode(nodeId, { dynamic_memory_read_policy: { ...selectedNodeDynamicReadPolicy, max_temporal_expansion_depth: Number(event.target.value || 0) } })} type="number" value={Number(selectedNodeDynamicReadPolicy.max_temporal_expansion_depth ?? 0)} /></TaskSystemField>
            </section>
          </>
        ) : null}

        {drawer.drawer_type === "memory" && drawer.target_object_type === "graph" ? (
          <section className="boundary-inspector-subblock">
            <header><strong>图级记忆策略</strong><span>工作记忆</span></header>
            <TaskSystemMultiSelectField label="全局可读 Kind" onChange={(value) => setNestedMetadataValue(setCoordinationDraft, "working_memory_policy", { readable_kinds: value })} options={WORKING_MEMORY_KIND_OPTIONS} value={asStringList(graphMemoryPolicy.readable_kinds)} wide formatOption={taskSystemOptionLabel} />
            <TaskSystemMultiSelectField label="全局可写 Kind" onChange={(value) => setNestedMetadataValue(setCoordinationDraft, "working_memory_policy", { writable_kinds: value })} options={WORKING_MEMORY_KIND_OPTIONS} value={asStringList(graphMemoryPolicy.writable_kinds)} wide formatOption={taskSystemOptionLabel} />
            <TaskSystemSelectField label="默认可见性" onChange={(value) => setNestedMetadataValue(setCoordinationDraft, "working_memory_policy", { default_visibility: value })} options={WORKING_MEMORY_VISIBILITY_OPTIONS} value={String(graphMemoryPolicy.default_visibility ?? "handoff_only")} formatOption={taskSystemOptionLabel} />
            <label className="boundary-check"><input checked={booleanValue(graphMemoryPolicy.require_review_before_commit, true)} onChange={(event) => setNestedMetadataValue(setCoordinationDraft, "working_memory_policy", { require_review_before_commit: event.target.checked })} type="checkbox" />长期记忆写入前需要审核</label>
          </section>
        ) : null}

        {drawer.drawer_type === "runtime" && selectedGraphNode ? (
          <section className="boundary-inspector-subblock">
            <header><strong>后台与资源生命周期</strong><span>运行时</span></header>
            <TaskSystemField label="并行分组"><input onChange={(event) => updateCoordinationNode(nodeId, { dispatch_group: event.target.value })} placeholder="例如 planning / review" value={String(selectedGraphNode.dispatch_group ?? "")} /></TaskSystemField>
            <label className="boundary-check"><input checked={booleanValue(selectedNodeBackgroundPolicy.enabled)} onChange={(event) => updateCoordinationNode(nodeId, { background_policy: { ...selectedNodeBackgroundPolicy, enabled: event.target.checked } })} type="checkbox" />允许作为后台节点运行</label>
            <label className="boundary-check"><input checked={booleanValue(selectedNodeBackgroundPolicy.blocks_downstream)} onChange={(event) => updateCoordinationNode(nodeId, { background_policy: { ...selectedNodeBackgroundPolicy, blocks_downstream: event.target.checked } })} type="checkbox" />后台完成前阻塞下游</label>
            <TaskSystemField label="后台超时秒数"><input min={0} onChange={(event) => updateCoordinationNode(nodeId, { background_policy: { ...selectedNodeBackgroundPolicy, max_runtime_seconds: Number(event.target.value || 0) } })} type="number" value={Number(selectedNodeBackgroundPolicy.max_runtime_seconds ?? 0)} /></TaskSystemField>
            <TaskSystemSelectField label="完成通知" onChange={(value) => updateCoordinationNode(nodeId, { notification_policy: { ...selectedNodeNotificationPolicy, on_completed: value } })} options={NOTIFICATION_POLICY_OPTIONS} value={String(selectedNodeNotificationPolicy.on_completed ?? "queued_summary")} formatOption={taskSystemOptionLabel} />
            <label className="boundary-check"><input checked={booleanValue(selectedNodeLifecyclePolicy.kill_on_parent_abort, true)} onChange={(event) => updateCoordinationNode(nodeId, { resource_lifecycle_policy: { ...selectedNodeLifecyclePolicy, kill_on_parent_abort: event.target.checked } })} type="checkbox" />父任务中止时终止该节点</label>
            <label className="boundary-check"><input checked={booleanValue(selectedNodeLifecyclePolicy.cleanup_on_terminal, true)} onChange={(event) => updateCoordinationNode(nodeId, { resource_lifecycle_policy: { ...selectedNodeLifecyclePolicy, cleanup_on_terminal: event.target.checked } })} type="checkbox" />终态后清理运行资源</label>
          </section>
        ) : null}

        {drawer.drawer_type === "runtime" && selectedGraphEdge ? (
          <section className="boundary-inspector-subblock">
            <header><strong>通信边运行策略</strong><span>边运行策略</span></header>
            <TaskSystemSelectField label="等待策略" onChange={(value) => updateCoordinationEdge(edgeId, { wait_policy: value })} options={["", ...NODE_WAIT_POLICY_OPTIONS]} value={String(selectedGraphEdge.wait_policy ?? "")} formatOption={(value) => value ? taskSystemOptionLabel(value) : "继承目标节点"} />
            <TaskSystemSelectField label="失败传播" onChange={(value) => updateCoordinationEdge(edgeId, { failure_propagation_policy: value })} options={EDGE_FAILURE_PROPAGATION_OPTIONS} value={String(selectedGraphEdge.failure_propagation_policy ?? "fail_downstream")} formatOption={taskSystemOptionLabel} />
            <TaskSystemField label="边超时秒数"><input min={0} type="number" value={Number(selectedEdgeRuntimePolicy.timeout_seconds ?? selectedGraphEdge.timeout_seconds ?? 0)} onChange={(event) => updateCoordinationEdge(edgeId, { runtime_policy: { ...selectedEdgeRuntimePolicy, timeout_seconds: Number(event.target.value || 0) } })} /></TaskSystemField>
            <label className="boundary-check"><input checked={booleanValue(selectedEdgeRuntimePolicy.blocks_target_start, true)} onChange={(event) => updateCoordinationEdge(edgeId, { runtime_policy: { ...selectedEdgeRuntimePolicy, blocks_target_start: event.target.checked } })} type="checkbox" />交接完成前阻塞目标节点启动</label>
          </section>
        ) : null}

        {drawer.drawer_type === "runtime" && drawer.target_object_type === "graph" ? (
          <section className="boundary-inspector-subblock">
            <header><strong>图级运行策略</strong><span>运行时</span></header>
            <TaskSystemSelectField label="默认执行模式" onChange={(value) => setNestedMetadataValue(setCoordinationDraft, "runtime_policy", { default_execution_mode: value })} options={NODE_EXECUTION_MODE_OPTIONS} value={String(graphRuntimePolicy.default_execution_mode ?? "sync")} formatOption={taskSystemOptionLabel} />
            <TaskSystemSelectField label="默认等待策略" onChange={(value) => setNestedMetadataValue(setCoordinationDraft, "runtime_policy", { default_wait_policy: value })} options={NODE_WAIT_POLICY_OPTIONS} value={String(graphRuntimePolicy.default_wait_policy ?? "wait_all_upstream_completed")} formatOption={taskSystemOptionLabel} />
            <TaskSystemField label="最大并发节点"><input min={1} type="number" value={Number(graphRuntimePolicy.max_parallel_nodes ?? 2)} onChange={(event) => setNestedMetadataValue(setCoordinationDraft, "runtime_policy", { max_parallel_nodes: Number(event.target.value || 1) })} /></TaskSystemField>
            <TaskSystemField label="节点超时秒数"><input min={0} type="number" value={Number(graphRuntimePolicy.default_timeout_seconds ?? 0)} onChange={(event) => setNestedMetadataValue(setCoordinationDraft, "runtime_policy", { default_timeout_seconds: Number(event.target.value || 0) })} /></TaskSystemField>
          </section>
        ) : null}

        {drawer.drawer_type === "communication" && selectedGraphEdge ? (
          <>
            <section className="boundary-inspector-subblock">
              <header><strong>通信与交接</strong><span>{edgeId}</span></header>
              <TaskSystemSelectField label="起点" onChange={(value) => updateCoordinationEdge(edgeId, { from: value, source_node_id: value })} options={activeGraphNodes.map((node) => String(node.node_id ?? ""))} value={graphEdgeSource(selectedGraphEdge)} formatOption={(value) => value} />
              <TaskSystemSelectField label="终点" onChange={(value) => updateCoordinationEdge(edgeId, { to: value, target_node_id: value })} options={activeGraphNodes.map((node) => String(node.node_id ?? ""))} value={graphEdgeTarget(selectedGraphEdge)} formatOption={(value) => value} />
              <TaskSystemSelectField label="通信模式" onChange={(value) => updateCoordinationEdge(edgeId, { mode: value })} options={GRAPH_EDGE_MODE_CHOICES} value={String(selectedGraphEdge.mode ?? "structured_handoff")} formatOption={taskSystemOptionLabel} />
              <TaskSystemSelectField label="交接契约" onChange={(value) => updateCoordinationEdge(edgeId, { contract_id: value, contract_refs: value ? [value] : [] })} options={contractOptions(contractSpecs, edgeContractId(selectedGraphEdge), ["edge_handoff"])} value={edgeContractId(selectedGraphEdge)} formatOption={formatContract} />
              <TaskSystemSelectField label="等待策略" onChange={(value) => updateCoordinationEdge(edgeId, { wait_policy: value })} options={["", ...NODE_WAIT_POLICY_OPTIONS]} value={String(selectedGraphEdge.wait_policy ?? "")} formatOption={(value) => value ? taskSystemOptionLabel(value) : "继承目标节点"} />
              <label className="boundary-check"><input checked={booleanValue(selectedGraphEdge.ack_required, true)} onChange={(event) => updateCoordinationEdge(edgeId, { ack_required: event.target.checked })} type="checkbox" />需要目标节点确认接收</label>
              <TaskSystemSelectField label="确认策略" onChange={(value) => updateCoordinationEdge(edgeId, { ack_policy: value })} options={["explicit_ack", "implicit_ack"]} value={String(selectedGraphEdge.ack_policy ?? "explicit_ack")} formatOption={taskSystemOptionLabel} />
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
        ) : null}

        {drawer.drawer_type === "communication" && drawer.target_object_type === "graph" ? (
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
        ) : null}

        {drawer.drawer_type === "artifact" && selectedGraphNode ? (
          <section className="boundary-inspector-subblock">
            <header><strong>节点产物策略</strong><span>节点产物</span></header>
            <TaskSystemField label="产物目标"><input value={String(selectedGraphNode.artifact_target ?? selectedGraphNode.output_path ?? "")} onChange={(event) => updateCoordinationNode(nodeId, { artifact_target: event.target.value, output_path: event.target.value })} placeholder="chapters/chapter_001_draft.md" /></TaskSystemField>
            <TaskSystemField label="产物策略 ID"><input value={String(selectedGraphNode.artifact_policy_id ?? "")} onChange={(event) => updateCoordinationNode(nodeId, { artifact_policy_id: event.target.value })} /></TaskSystemField>
            <TaskSystemField label="必需文件" wide><textarea value={asStringList(selectedNodeArtifactPolicy.required_files).join("\n")} onChange={(event) => updateCoordinationNode(nodeId, { artifact_policy: { ...selectedNodeArtifactPolicy, required_files: event.target.value.split(/[\n,，]/).map((item) => item.trim()).filter(Boolean) } })} /></TaskSystemField>
            <label className="boundary-check"><input checked={booleanValue(selectedNodeArtifactPolicy.required, true)} onChange={(event) => updateCoordinationNode(nodeId, { artifact_policy: { ...selectedNodeArtifactPolicy, required: event.target.checked } })} type="checkbox" />该节点产物为阶段出口要求</label>
          </section>
        ) : null}

        {drawer.drawer_type === "artifact" && drawer.target_object_type === "graph" ? (
          <section className="boundary-inspector-subblock">
            <header><strong>产物落盘策略</strong><span>产物</span></header>
            <TaskSystemField label="产物根目录"><input value={String(graphArtifactPolicy.artifact_root ?? graphArtifactPolicy.default_artifact_root ?? "")} onChange={(event) => setNestedMetadataValue(setCoordinationDraft, "artifact_policy", { artifact_root: event.target.value })} /></TaskSystemField>
            <TaskSystemField label="子目录模板"><input value={String(graphArtifactPolicy.subdir_template ?? "{task_slug}/{run_slug}")} onChange={(event) => setNestedMetadataValue(setCoordinationDraft, "artifact_policy", { subdir_template: event.target.value })} /></TaskSystemField>
            <TaskSystemField label="物化器"><input value={String(graphArtifactPolicy.materializer ?? "markdown_section_split")} onChange={(event) => setNestedMetadataValue(setCoordinationDraft, "artifact_policy", { materializer: event.target.value })} /></TaskSystemField>
            <label className="boundary-check"><input checked={booleanValue(graphArtifactPolicy.enabled)} onChange={(event) => setNestedMetadataValue(setCoordinationDraft, "artifact_policy", { enabled: event.target.checked })} type="checkbox" />启用图级产物落盘</label>
          </section>
        ) : null}

        {drawer.drawer_type === "preflight" ? (
          <section className="boundary-inspector-subblock">
            <header><strong>运行预检</strong><span>预检</span></header>
            <div className="coordination-console-grid">
              <article><span>节点</span><strong>{activeGraphNodes.length}</strong><small>拓扑执行单位</small></article>
              <article><span>阶段</span><strong>{phaseDefinitions.length}</strong><small>生命周期分段</small></article>
              <article><span>时序问题</span><strong>{graphPreflightIssues.length}</strong><small>错误 / 警告 / 信息</small></article>
            </div>
            <div className="coordination-drawer-list">
              {graphPreflightIssues.map((issue, index) => (
                <article key={`${issue.code}-${index}`}>
                  <header><strong>{issue.code}</strong><span>{issue.severity}</span></header>
                  <p>{issue.message}</p>
                </article>
              ))}
              {!graphPreflightIssues.length ? <div className="boundary-empty">当前图级时序预检未发现问题。</div> : null}
            </div>
          </section>
        ) : null}

        {drawer.drawer_type === "communication" && !selectedGraphEdge && drawer.target_object_type === "edge" ? (
          <div className="boundary-empty">请先在画布中选择一条通信边。</div>
        ) : null}

        {["timeline", "review", "loop"].includes(drawer.drawer_type) && !selectedTimelineFrame && drawer.target_object_type === "frame" ? (
          <div className="boundary-empty">请先在画布右侧选择一个时序 Frame。</div>
        ) : null}

        {["agent", "contract", "timeline", "review", "loop", "memory", "runtime", "artifact"].includes(drawer.drawer_type) && !selectedGraphNode && drawer.target_object_type === "node" ? (
          <div className="boundary-empty">请先在画布中选择一个节点。</div>
        ) : null}
      </div>
    </aside>
  );
}

function CoordinationCanvasPanel({
  activeGraphNodes,
  activeGraphEdges,
  coordinationDraft,
  setCoordinationDraft,
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
  updateCoordinationNode,
  selectedDomainTasks,
  selectedGraphNode,
  onOpenDrawer,
}: {
  activeGraphNodes: Array<Record<string, unknown>>;
  activeGraphEdges: Array<Record<string, unknown>>;
  coordinationDraft: CoordinationDraftLike;
  setCoordinationDraft: Dispatch<SetStateAction<CoordinationDraftLike>>;
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
  updateCoordinationNode: (nodeId: string, patch: Record<string, unknown>) => void;
  selectedDomainTasks: SpecificTaskRecord[];
  selectedGraphNode: Record<string, unknown> | null;
  onOpenDrawer: (drawerType: MechanismDrawerType, targetType?: MechanismTargetType, targetId?: string) => void;
}) {
  const [contextMenu, setContextMenu] = useState<GraphContextMenuState>({ open: false, x: 0, y: 0, target_type: "canvas", target_id: "" });
  const [frameType, setFrameType] = useState<TimelineFrameType>("phase_frame");
  const [frameTitle, setFrameTitle] = useState(timelineFrameDefaultTitle("phase_frame"));
  const [framePhaseId, setFramePhaseId] = useState("phase.frame_01");
  const [frameSequenceIndex, setFrameSequenceIndex] = useState(1);
  const [frameGroupId, setFrameGroupId] = useState("timeline.group_01");
  const [frameMaxAttempts, setFrameMaxAttempts] = useState(5);
  const metadata = asRecord(coordinationDraft.metadata);
  const phaseDefinitions = coordinationPhaseDefinitions(metadata, activeGraphNodes);
  const timelineFrames = coordinationTimelineFrames(metadata);
  const framedPhaseSummaries = phaseDefinitions.map((phase) => ({
    phase,
    nodes: activeGraphNodes.filter((node) => nodePhaseId(node) === phase.phase_id),
  })).filter((item) => item.nodes.length);
  const selectedNodeSet = new Set(graphSelection.selected_node_ids);
  const selectedFrameNodes = activeGraphNodes.filter((node) => selectedNodeSet.has(String(node.node_id ?? "")));
  const selectedFrame = graphSelection.selected_frame_ids[0]
    ? timelineFrames.find((frame) => frame.frame_id === graphSelection.selected_frame_ids[0]) ?? null
    : null;
  const frameIssues = selectedFrameNodes.length < 1 ? ["至少选择一个节点"] : [];
  const firstSelectedNodeId = String(selectedFrameNodes[0]?.node_id ?? "");
  const lastSelectedNodeId = String(selectedFrameNodes[selectedFrameNodes.length - 1]?.node_id ?? "");

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

  function applyTimelineFrameToNodesFromCanvas(frame: TaskGraphTimelineFrame) {
    frame.node_ids.forEach((targetNodeId, index) => {
      const node = activeGraphNodes.find((item) => String(item.node_id ?? "") === targetNodeId);
      const basePatch: Record<string, unknown> = {
        phase_id: frame.phase_id || nodePhaseId(node ?? {}),
      };
      if (frame.sequence_index) basePatch.sequence_index = frame.sequence_index + index;
      if (frame.timeline_group_id) basePatch.timeline_group_id = frame.timeline_group_id;
      if (frame.frame_type === "parallel_frame") {
        basePatch.execution_mode = "parallel";
        basePatch.dispatch_group = frame.timeline_group_id || frame.frame_id;
      }
      if (frame.frame_type === "loop_frame") {
        basePatch.loop_policy = {
          ...nodeLoopPolicy(node ?? {}),
          ...asRecord(frame.loop_policy),
          loop_role: index === 0 ? "loop_entry" : index === frame.node_ids.length - 1 ? "loop_exit" : "loop_body",
        };
      }
      if (frame.frame_type === "review_gate_frame") {
        basePatch.node_type = targetNodeId === frame.review_gate_node_id ? "review_gate" : String(node?.node_type ?? "agent_role");
        basePatch.review_gate_policy = {
          ...nodeReviewGatePolicy(node ?? {}),
          is_review_gate: targetNodeId === frame.review_gate_node_id,
          on_fail: frame.node_ids[0] ?? "",
          on_pass: frame.node_ids[frame.node_ids.length - 1] ?? "",
        };
      }
      updateCoordinationNode(targetNodeId, basePatch);
    });
  }

  function deleteTimelineFrameFromCanvas(frameId: string) {
    setCoordinationDraft((current) => {
      const currentMetadata = asRecord(current.metadata);
      return {
        ...current,
        metadata: {
          ...currentMetadata,
          timeline_frames: coordinationTimelineFrames(currentMetadata).filter((frame) => frame.frame_id !== frameId),
        },
      };
    });
    clearSelection();
  }

  function updateTimelineFrameFromCanvas(frameId: string, patch: Partial<TaskGraphTimelineFrame>) {
    setCoordinationDraft((current) => {
      const currentMetadata = asRecord(current.metadata);
      return {
        ...current,
        metadata: {
          ...currentMetadata,
          timeline_frames: coordinationTimelineFrames(currentMetadata).map((frame) => (frame.frame_id === frameId ? { ...frame, ...patch } : frame)),
        },
      };
    });
  }

  function addSelectionToFrame(frame: TaskGraphTimelineFrame) {
    const nextNodeIds = uniqueStrings([...frame.node_ids, ...graphSelection.selected_node_ids]);
    const nextEdgeIds = uniqueStrings([...frame.edge_ids, ...graphSelection.selected_edge_ids]);
    updateTimelineFrameFromCanvas(frame.frame_id, { node_ids: nextNodeIds, edge_ids: nextEdgeIds });
    setGraphSelection((current) => ({
      ...current,
      selected_node_ids: nextNodeIds,
      selected_edge_ids: nextEdgeIds,
      selected_frame_ids: [frame.frame_id],
      primary_object_id: frame.frame_id,
      primary_object_type: "frame",
    }));
  }

  function removeSelectionFromFrame(frame: TaskGraphTimelineFrame) {
    const removeNodeIds = new Set(graphSelection.selected_node_ids);
    const removeEdgeIds = new Set(graphSelection.selected_edge_ids);
    const nextNodeIds = frame.node_ids.filter((nodeId) => !removeNodeIds.has(nodeId));
    const nextEdgeIds = frame.edge_ids.filter((edgeId) => !removeEdgeIds.has(edgeId));
    updateTimelineFrameFromCanvas(frame.frame_id, { node_ids: nextNodeIds, edge_ids: nextEdgeIds });
    setGraphSelection((current) => ({
      ...current,
      selected_node_ids: nextNodeIds,
      selected_edge_ids: nextEdgeIds,
      selected_frame_ids: [frame.frame_id],
      primary_object_id: frame.frame_id,
      primary_object_type: "frame",
    }));
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

  function createTimelineFrame(nextFrameType = frameType, nextFrameTitle = frameTitle) {
    if (frameIssues.length) return;
    const normalizedTitle = nextFrameTitle.trim() || timelineFrameDefaultTitle(nextFrameType);
    const normalizedPhaseId = framePhaseId.trim() || `phase.${normalizedTitle || "frame"}`;
    const normalizedGroupId = frameGroupId.trim() || `${normalizedPhaseId}.group`;
    const nextFrameId = timelineFrameIdFromTitle(normalizedTitle);
    if (nextFrameType === "phase_frame") {
      const currentPhases = coordinationPhaseDefinitions(metadata, activeGraphNodes);
      const existing = currentPhases.some((phase) => phase.phase_id === normalizedPhaseId);
      const nextPhase = {
        phase_id: normalizedPhaseId,
        title: normalizedTitle || normalizedPhaseId,
        entry_node_id: firstSelectedNodeId,
        exit_node_id: lastSelectedNodeId,
        review_gate_node_id: "",
        exit_policy: { kind: "phase_nodes_complete" },
      };
      setCoordinationDraft((current) => ({
        ...current,
        metadata: {
          ...(current.metadata ?? {}),
          phase_definitions: existing
            ? currentPhases.map((phase) => phase.phase_id === normalizedPhaseId ? { ...phase, ...nextPhase } : phase)
            : [...currentPhases, nextPhase],
        },
      }));
    }
    selectedFrameNodes.forEach((node, index) => {
      const nodeId = String(node.node_id ?? "");
      const basePatch: Record<string, unknown> = {
        phase_id: normalizedPhaseId,
      };
      if (nextFrameType === "phase_frame") {
        basePatch.sequence_index = index + 1;
        basePatch.main_chain = true;
      }
      if (nextFrameType === "step_frame") {
        basePatch.sequence_index = frameSequenceIndex;
        basePatch.timeline_group_id = normalizedGroupId;
      }
      if (nextFrameType === "parallel_frame") {
        basePatch.sequence_index = frameSequenceIndex;
        basePatch.timeline_group_id = normalizedGroupId;
        basePatch.execution_mode = "parallel";
        basePatch.dispatch_group = normalizedGroupId;
      }
      if (nextFrameType === "loop_frame") {
        basePatch.sequence_index = frameSequenceIndex + index;
        basePatch.loop_policy = {
          ...nodeLoopPolicy(node),
          loop_role: index === 0 ? "loop_entry" : index === selectedFrameNodes.length - 1 ? "loop_exit" : "loop_body",
          max_attempts: frameMaxAttempts,
          exit_condition: String(nodeLoopPolicy(node).exit_condition ?? "review_gate_passed"),
        };
      }
      if (nextFrameType === "review_gate_frame") {
        basePatch.sequence_index = frameSequenceIndex + index;
        basePatch.node_type = index === selectedFrameNodes.length - 1 ? "review_gate" : String(node.node_type ?? "agent_role");
        basePatch.review_gate_policy = {
          ...nodeReviewGatePolicy(node),
          is_review_gate: index === selectedFrameNodes.length - 1,
          pass_score: Number(nodeReviewGatePolicy(node).pass_score ?? 85),
          on_pass: lastSelectedNodeId,
          on_fail: firstSelectedNodeId,
        };
      }
      updateCoordinationNode(nodeId, basePatch);
    });
    if (nextFrameType === "review_gate_frame" && lastSelectedNodeId) {
      const currentPhases = coordinationPhaseDefinitions(metadata, activeGraphNodes);
      setCoordinationDraft((current) => ({
        ...current,
        metadata: {
          ...(current.metadata ?? {}),
          phase_definitions: currentPhases.map((phase) => phase.phase_id === normalizedPhaseId
            ? { ...phase, review_gate_node_id: lastSelectedNodeId, exit_policy: { kind: "review_gate_passed", required_gate_node_id: lastSelectedNodeId } }
            : phase),
        },
      }));
    }
    const nextFrame: TaskGraphTimelineFrame = {
      frame_id: nextFrameId,
      frame_type: nextFrameType,
      title: normalizedTitle,
      phase_id: normalizedPhaseId,
      sequence_index: frameSequenceIndex,
      timeline_group_id: ["step_frame", "parallel_frame"].includes(nextFrameType) ? normalizedGroupId : undefined,
      node_ids: selectedFrameNodes.map((node) => String(node.node_id ?? "")).filter(Boolean),
      edge_ids: graphSelection.selected_edge_ids,
      review_gate_node_id: nextFrameType === "review_gate_frame" ? lastSelectedNodeId : undefined,
      loop_policy: nextFrameType === "loop_frame" ? { max_attempts: frameMaxAttempts, exit_condition: "review_gate_passed" } : undefined,
      metadata: {
        created_from: "topology_selection",
      },
    };
    setCoordinationDraft((current) => {
      const currentMetadata = asRecord(current.metadata);
      const currentFrames = coordinationTimelineFrames(currentMetadata);
      return {
        ...current,
        metadata: {
          ...currentMetadata,
          timeline_frames: [...currentFrames, nextFrame],
        },
      };
    });
    setGraphSelection({
      ...emptyGraphSelection(),
      primary_object_id: nextFrameId,
      primary_object_type: "frame",
      selected_frame_ids: [nextFrameId],
      selected_node_ids: nextFrame.node_ids,
      selected_edge_ids: nextFrame.edge_ids,
    });
    setContextMenu((current) => ({ ...current, open: false }));
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
                <span>时序框</span>
                <strong>右键选择集构建时序</strong>
              </div>
              <div className="coordination-editor-actions">
                <button className="boundary-chip" onClick={setAllFrameNodes} type="button"><span>全选节点</span></button>
                <button className="boundary-chip" onClick={clearSelection} type="button"><span>清空选择</span></button>
              </div>
            </header>
            <div className="coordination-frame-create-console">
              <TaskSystemField label="类型">
                <select value={frameType} onChange={(event) => { const nextType = event.target.value as TimelineFrameType; setFrameType(nextType); setFrameTitle(timelineFrameDefaultTitle(nextType)); }}>
                  {TIMELINE_FRAME_TYPES.map((type) => <option key={type} value={type}>{timelineFrameTypeLabel(type)}</option>)}
                </select>
              </TaskSystemField>
              <TaskSystemField label="标题"><input value={frameTitle} onChange={(event) => setFrameTitle(event.target.value)} /></TaskSystemField>
              <TaskSystemField label="阶段"><input value={framePhaseId} onChange={(event) => setFramePhaseId(event.target.value)} /></TaskSystemField>
              <TaskSystemField label="时序点"><input min={1} type="number" value={frameSequenceIndex} onChange={(event) => setFrameSequenceIndex(Number(event.target.value || 1))} /></TaskSystemField>
              <TaskSystemField label="并行组"><input value={frameGroupId} onChange={(event) => setFrameGroupId(event.target.value)} /></TaskSystemField>
              <TaskSystemField label="循环轮次"><input min={1} type="number" value={frameMaxAttempts} onChange={(event) => setFrameMaxAttempts(Number(event.target.value || 1))} /></TaskSystemField>
              <button className="boundary-chip coordination-frame-create-console__action" disabled={Boolean(frameIssues.length)} onClick={() => createTimelineFrame(frameType, frameTitle)} type="button"><span>创建 Frame</span></button>
            </div>
            <div className="coordination-frame-summary">
              <span>已选择 {selectedFrameNodes.length} 个节点</span>
              <span>{graphSelection.selected_edge_ids.length} 条边</span>
              <span>{timelineFrameTypeLabel(frameType)}</span>
              <span>{graphSelection.primary_object_type === "frame" ? "Frame 选中态" : "选择集编辑态"}</span>
              {selectedFrame ? <span>当前 Frame：{selectedFrame.title} · {selectedFrame.node_ids.length} 节点 / {selectedFrame.edge_ids.length} 边</span> : null}
              {frameIssues.map((issue) => <span className="coordination-frame-summary__warn" key={issue}>{issue}</span>)}
            </div>
            <div className="coordination-frame-overview">
              {timelineFrames.map((frame) => {
                const selectedNodeHitCount = frame.node_ids.filter((nodeId) => graphSelection.selected_node_ids.includes(nodeId)).length;
                const selectedEdgeHitCount = frame.edge_ids.filter((edgeId) => graphSelection.selected_edge_ids.includes(edgeId)).length;
                return (
                  <article
                    className={graphSelection.selected_frame_ids.includes(frame.frame_id) ? "coordination-frame-overview__item coordination-frame-overview__item--active" : "coordination-frame-overview__item"}
                    key={frame.frame_id}
                  >
                    <button onClick={() => selectFrame(frame)} type="button">
                      <strong>{frame.title || frame.frame_id}</strong>
                      <span>{timelineFrameTypeLabel(frame.frame_type)} · {frame.phase_id || frame.timeline_group_id || frame.frame_id}</span>
                      <small>{frame.node_ids.length} 节点 · {frame.edge_ids.length} 边{selectedNodeHitCount || selectedEdgeHitCount ? ` · 命中 ${selectedNodeHitCount}/${selectedEdgeHitCount}` : ""}{frame.review_gate_node_id ? ` · 审核门 ${frame.review_gate_node_id}` : ""}</small>
                    </button>
                    <div className="coordination-frame-overview__actions">
                      <button className="boundary-chip" onClick={() => { selectFrame(frame); onOpenDrawer("timeline", "frame", frame.frame_id); }} type="button"><span>配置</span></button>
                      <button className="boundary-chip" disabled={!graphSelection.selected_node_ids.length && !graphSelection.selected_edge_ids.length} onClick={() => addSelectionToFrame(frame)} type="button"><span>加入选择</span></button>
                      <button className="boundary-chip" disabled={!graphSelection.selected_node_ids.length && !graphSelection.selected_edge_ids.length} onClick={() => removeSelectionFromFrame(frame)} type="button"><span>移出选择</span></button>
                      <button className="boundary-chip" onClick={() => applyTimelineFrameToNodesFromCanvas(frame)} type="button"><span>应用</span></button>
                      {frame.frame_type === "review_gate_frame" ? <button className="boundary-chip" onClick={() => { selectFrame(frame); onOpenDrawer("review", "frame", frame.frame_id); }} type="button"><span>审核</span></button> : null}
                      {frame.frame_type === "loop_frame" ? <button className="boundary-chip" onClick={() => { selectFrame(frame); onOpenDrawer("loop", "frame", frame.frame_id); }} type="button"><span>循环</span></button> : null}
                      <button
                        className="boundary-chip"
                        onClick={() => {
                          if (window.confirm("确认删除这个时序 Frame 吗？节点和通信边不会被删除。")) {
                            deleteTimelineFrameFromCanvas(frame.frame_id);
                          }
                        }}
                        type="button"
                      >
                        <span>删除</span>
                      </button>
                    </div>
                  </article>
                );
              })}
              {!timelineFrames.length ? framedPhaseSummaries.map(({ phase, nodes }) => (
                <article className="coordination-frame-overview__item" key={phase.phase_id}>
                  <button type="button">
                    <strong>{phase.title || phase.phase_id}</strong>
                    <span>{phase.phase_id}</span>
                    <small>{nodes.length} 节点 · {phase.review_gate_node_id ? "有审核门" : "无审核门"}</small>
                  </button>
                </article>
              )) : null}
              {!timelineFrames.length && !framedPhaseSummaries.length ? <div className="boundary-empty">还没有形成时序框。勾选节点后可以创建阶段、并行组、循环或审核门。</div> : null}
            </div>
          </section>
          {contextMenu.open ? (
            <div className="coordination-context-menu" style={{ left: contextMenu.x, top: contextMenu.y }}>
              <strong>{contextMenu.target_type === "selection" ? "选择集" : contextMenu.target_type === "canvas" ? "画布" : contextMenu.target_type === "node" ? "节点" : "通信边"}</strong>
              {contextMenu.target_type === "selection" || contextMenu.target_type === "node" ? (
                <>
                  <button onClick={() => { const title = timelineFrameDefaultTitle("phase_frame"); setFrameType("phase_frame"); setFrameTitle(title); createTimelineFrame("phase_frame", title); }} type="button">构建阶段</button>
                  <button onClick={() => { const title = timelineFrameDefaultTitle("step_frame"); setFrameType("step_frame"); setFrameTitle(title); createTimelineFrame("step_frame", title); }} type="button">构建时序点</button>
                  <button onClick={() => { const title = timelineFrameDefaultTitle("parallel_frame"); setFrameType("parallel_frame"); setFrameTitle(title); createTimelineFrame("parallel_frame", title); }} type="button">构建并行组</button>
                  <button onClick={() => { const title = timelineFrameDefaultTitle("loop_frame"); setFrameType("loop_frame"); setFrameTitle(title); createTimelineFrame("loop_frame", title); }} type="button">构建循环</button>
                  <button onClick={() => { const title = timelineFrameDefaultTitle("review_gate_frame"); setFrameType("review_gate_frame"); setFrameTitle(title); createTimelineFrame("review_gate_frame", title); }} type="button">构建审核门</button>
                </>
              ) : null}
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

          <div className="coordination-inspector-actions coordination-inspector-actions--grid">
            <button className="boundary-chip" onClick={() => onOpenDrawer("agent", "node", nodeId)} type="button"><span>Agent</span></button>
            <button className="boundary-chip" onClick={() => onOpenDrawer("contract", "node", nodeId)} type="button"><span>投影契约</span></button>
            <button className="boundary-chip" onClick={() => onOpenDrawer("timeline", "node", nodeId)} type="button"><span>时序</span></button>
            <button className="boundary-chip" onClick={() => onOpenDrawer("review", "node", nodeId)} type="button"><span>审核循环</span></button>
            <button className="boundary-chip" onClick={() => onOpenDrawer("memory", "node", nodeId)} type="button"><span>记忆</span></button>
            <button className="boundary-chip" onClick={() => onOpenDrawer("runtime", "node", nodeId)} type="button"><span>运行</span></button>
            <button className="boundary-chip" onClick={() => onOpenDrawer("artifact", "node", nodeId)} type="button"><span>产物</span></button>
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
            <button className="boundary-chip" onClick={() => onOpenDrawer("runtime", "edge", edgeId)} type="button"><span>运行策略</span></button>
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
          <button className="boundary-chip" onClick={() => onOpenDrawer("timeline", "graph")} type="button"><span>时序</span></button>
          <button className="boundary-chip" onClick={() => onOpenDrawer("communication", "graph")} type="button"><span>通信</span></button>
          <button className="boundary-chip" onClick={() => onOpenDrawer("contract", "graph")} type="button"><span>投影契约</span></button>
          <button className="boundary-chip" onClick={() => onOpenDrawer("memory", "graph")} type="button"><span>记忆</span></button>
          <button className="boundary-chip" onClick={() => onOpenDrawer("artifact", "graph")} type="button"><span>产物</span></button>
          <button className="boundary-chip" onClick={() => onOpenDrawer("preflight", "graph")} type="button"><span>预检</span></button>
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
  applyCoordinationGraphTemplate: (template: "single_agent" | "multi_sequence" | "multi_parallel_merge") => void;
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
  const [activeConsoleTab, setActiveConsoleTab] = useState<MechanismConsoleTab>("timeline");
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
          coordinationDraft={coordinationDraft}
          edges={activeGraphEdges}
          graphSelection={graphSelection}
          nodes={activeGraphNodes}
          selectedCoordinationGraphSpec={selectedCoordinationGraphSpec}
          selectedEdgeId={selectedGraphEdgeId}
          selectedNodeId={selectedGraphNodeId}
          setActiveTab={setActiveConsoleTab}
          onOpenDrawer={openMechanismDrawer}
          onSelectNode={(nodeId) => {
            handleTopologyNodeClick(nodeId);
            setGraphSelection({
              ...emptyGraphSelection(),
              primary_object_id: nodeId,
              primary_object_type: "node",
              selected_node_ids: [nodeId],
            });
          }}
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
              onOpenDrawer={openMechanismDrawer}
              setCoordinationDraft={setCoordinationDraft}
              setGraphSelection={setGraphSelection}
              setLinkingFromNodeId={setLinkingFromNodeId}
              setSelectedGraphEdgeId={setSelectedGraphEdgeId}
              setSelectedGraphNodeId={setSelectedGraphNodeId}
              updateCoordinationNode={updateCoordinationNode}
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
            agentCardOptions={editorAgentCardOptions}
            contractSpecs={contractSpecs}
            coordinationDraft={coordinationDraft}
            domainTaskOptions={domainTaskOptions}
            drawer={mechanismDrawer}
            formatAgentCard={formatEditorAgentCard}
            formatContract={formatEditorContract}
            formatNodeOption={formatEditorNodeOption}
            formatProjection={formatEditorProjection}
            nodeIdOptions={editorNodeIdOptions}
            phaseDefinitions={editorPhaseDefinitions}
            projectionCards={projectionCards}
            protocolDraft={protocolDraft}
            setCoordinationDraft={setCoordinationDraft}
            setProtocolDraft={setProtocolDraft}
            setTopologyDraft={setTopologyDraft}
            topologyDraft={topologyDraft}
            selectedDomain={selectedDomain}
            selectedDomainTasks={selectedDomainTasks}
            selectedGraphEdge={selectedGraphEdge}
            selectedGraphNode={selectedGraphNode}
            updateCoordinationEdge={updateCoordinationEdge}
            updateCoordinationNode={updateCoordinationNode}
            onClose={() => setMechanismDrawer((current) => ({ ...current, open: false }))}
          />
        </div>
      </section>
    </section>
  );
}
