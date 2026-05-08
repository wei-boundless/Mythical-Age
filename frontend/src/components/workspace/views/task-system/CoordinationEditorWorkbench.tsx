"use client";

import {
  GitBranch,
  GitCommitHorizontal,
  Plus,
  RotateCcw,
  Save,
  SquarePen,
  Trash2,
} from "lucide-react";
import { useState, type Dispatch, type ReactNode, type SetStateAction } from "react";

import {
  CoordinationTopologyGraph,
  type CoordinationTopologyEdge,
  type CoordinationTopologyNode,
} from "@/components/coordination/CoordinationTopologyGraph";
import { contractSpecTitle } from "@/components/workspace/views/task-system/ContractLibraryPanel";
import {
  TaskSystemDomainTaskSelectField,
  TaskSystemField,
  TaskSystemMultiSelectField,
  taskSystemOptionLabel,
  TaskSystemSelectField,
  TaskSystemToolbarButton,
} from "@/components/workspace/views/task-system/TaskSystemWorkbenchUi";
import type {
  ConversationEntryPolicy,
  ContractSpec,
  CoordinationGraphSpec,
  CoordinationTask,
  SpecificTaskRecord,
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

type CoordinationDraftLike = CoordinationTask & {
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

type A2ACatalogLike = NonNullable<TaskSystemOverview["coordination_management"]["a2a"]>;

const COORDINATION_MODE_CHOICES = ["review_merge", "pipeline", "parallel_review"];
const GRAPH_EDGE_MODE_CHOICES = ["structured_handoff", "review_feedback", "draft_request", "audit_request", "merge_signal"];
const NODE_EXECUTION_MODE_OPTIONS = ["sync", "async", "parallel", "background", "barrier", "manual_gate"];
const NODE_WAIT_POLICY_OPTIONS = ["wait_all_upstream_completed", "wait_any_upstream_completed", "wait_required_contracts", "wait_handoff_ack", "fire_and_continue", "manual_release"];
const NODE_JOIN_POLICY_OPTIONS = ["all_success", "any_success", "quorum", "coordinator_decides", "allow_partial_with_issues", "fail_on_any_error"];
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
  "chapter_draft",
  "character_state_delta",
  "world_state_delta",
  "continuity_conflict",
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

function uniqueStrings(values: Array<string | null | undefined>) {
  return Array.from(new Set(values.map((item) => String(item ?? "").trim()).filter(Boolean)));
}

function displayId(value: unknown, fallback = "未配置") {
  const raw = String(value ?? "").trim();
  if (!raw) return fallback;
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
  return labels[raw] ? `${labels[raw]} · ${raw}` : raw;
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

function nodeContractId(node: Record<string, unknown> | null) {
  return String(node?.node_contract_id ?? node?.contract_id ?? "").trim();
}

function edgeContractId(edge: Record<string, unknown> | null) {
  return String(edge?.contract_id ?? "").trim();
}

export function graphNodeLabel(node: Record<string, unknown>, index: number) {
  return text(node.label || node.task_title || node.role || node.agent_id, `节点 ${index + 1}`);
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

function taskTitleById(taskId: string, tasks: SpecificTaskRecord[]) {
  const task = tasks.find((item) => item.task_id === taskId);
  return task?.task_title || displayId(taskId);
}

export function coordinationSubtaskRefs(draft: CoordinationTask | CoordinationDraftLike) {
  return uniqueStrings([
    ...((draft.graph_nodes ?? []).map((node) => graphNodeTaskId(node))),
  ]);
}

function CoordinationGraph({
  nodes,
  edges,
  messages,
  tasks = [],
  selectedNodeId = "",
  selectedEdgeId = "",
  linkingFromNodeId = "",
  renderNodeTools,
  renderEdgeTools,
  onSelectNode,
  onSelectEdge,
}: {
  nodes: Array<Record<string, unknown>>;
  edges: Array<Record<string, unknown>>;
  messages: string[];
  tasks?: SpecificTaskRecord[];
  selectedNodeId?: string;
  selectedEdgeId?: string;
  linkingFromNodeId?: string;
  renderNodeTools?: (node: Record<string, unknown>, nodeId: string) => ReactNode;
  renderEdgeTools?: (edge: Record<string, unknown>, edgeId: string) => ReactNode;
  onSelectNode?: (nodeId: string) => void;
  onSelectEdge?: (edgeId: string) => void;
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
      agentLabel: text(node.agent_id || node.role || node.node_type, "待分派"),
      role: text(node.role || node.agent_category || node.node_type, "participant"),
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

  return (
    <div className="boundary-graph boundary-graph--topology">
      <div className="boundary-graph__legend">
        {messages.length ? messages.slice(0, 6).map((item) => <span key={item}>{item}</span>) : <span>structured_handoff</span>}
      </div>
      <div className="coordination-topology-viewport coordination-topology-viewport--builder">
        <CoordinationTopologyGraph
          currentNodeId={selectedNodeId}
          edges={graphEdges}
          emptyDescription="添加节点后，这里会同步展示任务图的运行拓扑。"
          emptyTitle="还没有拓扑节点"
          linkingFromNodeId={linkingFromNodeId}
          nodes={graphNodes}
          onSelectEdge={onSelectEdge}
          onSelectNode={onSelectNode}
          onConnectNode={linkingFromNodeId ? onSelectNode : undefined}
          renderNodeTools={renderNodeTools ? (node) => {
            const rawNode = safeNodes.find((item) => String(item.node_id ?? item.id ?? "") === node.id) ?? {};
            return renderNodeTools(rawNode, node.id);
          } : undefined}
          renderEdgeTools={renderEdgeTools ? (edge) => {
            const rawEdge = resolvedEdges.find((item, index) => graphEdgeId(item as Record<string, unknown>, index) === edge.id) as Record<string, unknown> | undefined;
            return renderEdgeTools(rawEdge ?? {}, edge.id);
          } : undefined}
          selectedEdgeId={selectedEdgeId}
          selectedNodeId={selectedNodeId}
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
                <span>{displayId(task.task_mode)}</span>
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
  return (
    <>
      <section className="coordination-editor-canvas-shell">
        <header className="coordination-editor-canvas-head">
          <div className="boundary-identity-stack">
            <span>拓扑画布</span>
            <strong>{selectedGraphNode ? graphNodeLabel(selectedGraphNode, 0) : "节点与通信关系"}</strong>
          </div>
          <div className="coordination-editor-toolbar">
            <button className="boundary-chip" disabled={activeGraphNodes.length < 2} onClick={addCoordinationEdge} type="button">
              <GitBranch size={14} />
              <span>默认通信</span>
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
              <span>{linkingFromNodeId ? "选择目标节点" : "图上连线"}</span>
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
              messages={coordinationDraft.communication_modes ?? []}
              linkingFromNodeId={linkingFromNodeId}
              nodes={activeGraphNodes}
              onSelectEdge={(edgeId) => {
                setSelectedGraphEdgeId(edgeId);
                setSelectedGraphNodeId("");
                setLinkingFromNodeId("");
              }}
              onSelectNode={handleTopologyNodeClick}
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
              tasks={selectedDomainTasks}
            />
          </div>
        </div>
      </section>
    </>
  );
}

function CoordinationInspectorPanel({
  selectedGraphNode,
  selectedGraphEdge,
  coordinationDraft,
  setCoordinationDraft,
  agentGroupOptions,
  setCoordinationPublished,
  editorPublished,
  topologyDraft,
  setTopologyDraft,
  protocolDraft,
  setProtocolDraft,
  domainTaskOptions,
  selectedDomainTasks,
  selectedDomain,
  updateCoordinationNode,
  removeCoordinationNode,
  activeGraphNodes,
  updateCoordinationEdge,
  reverseCoordinationEdge,
  removeCoordinationEdge,
  selectedCoordinationGraphSpec,
  a2aCatalog,
  contractSpecs,
}: {
  selectedGraphNode: Record<string, unknown> | null;
  selectedGraphEdge: Record<string, unknown> | null;
  coordinationDraft: CoordinationDraftLike;
  setCoordinationDraft: Dispatch<SetStateAction<CoordinationDraftLike>>;
  agentGroupOptions: string[];
  setCoordinationPublished: (enabled: boolean) => void;
  editorPublished: boolean;
  topologyDraft: TopologyDraftLike;
  setTopologyDraft: Dispatch<SetStateAction<TopologyDraftLike>>;
  protocolDraft: ProtocolDraftLike;
  setProtocolDraft: Dispatch<SetStateAction<ProtocolDraftLike>>;
  domainTaskOptions: Array<{ value: string; label: string }>;
  selectedDomainTasks: SpecificTaskRecord[];
  selectedDomain: DomainRecordLike | null;
  updateCoordinationNode: (nodeId: string, patch: Record<string, unknown>) => void;
  removeCoordinationNode: (nodeId: string) => void;
  activeGraphNodes: Array<Record<string, unknown>>;
  updateCoordinationEdge: (edgeId: string, patch: Record<string, unknown>) => void;
  reverseCoordinationEdge: (edgeId: string) => void;
  removeCoordinationEdge: (edgeId: string) => void;
  selectedCoordinationGraphSpec: CoordinationGraphSpec | null;
  a2aCatalog: A2ACatalogLike | null;
  contractSpecs: ContractSpec[];
}) {
  const selectedEdgeSourceId = graphEdgeSource(selectedGraphEdge ?? {});
  const selectedEdgeTargetId = graphEdgeTarget(selectedGraphEdge ?? {});
  const selectedEdgeSourceNode = activeGraphNodes.find((node) => String(node.node_id ?? "") === selectedEdgeSourceId) ?? null;
  const selectedEdgeTargetNode = activeGraphNodes.find((node) => String(node.node_id ?? "") === selectedEdgeTargetId) ?? null;
  const selectedEdgePreview = edgeA2APreview({
    catalog: a2aCatalog,
    coordinationDraft,
    edge: selectedGraphEdge,
    protocolDraft,
    sourceNode: selectedEdgeSourceNode,
    targetNode: selectedEdgeTargetNode,
  });
  const selectedNodeCard = agentCardForNode(selectedGraphNode, a2aCatalog);
  const agentCardOptions = uniqueStrings([
    String(selectedGraphNode?.agent_id ?? ""),
    ...((a2aCatalog?.agent_cards ?? []).map((card) => String(card.agent_id ?? "")).filter(Boolean)),
  ]);
  const formatAgentCard = (agentId: string) => {
    const card = (a2aCatalog?.agent_cards ?? []).find((item) => String(item.agent_id ?? "") === agentId);
    if (!agentId) return "不绑定";
    return card?.name ? `${String(card.name)} · ${agentId}` : agentId;
  };
  const formatContract = contractOptionLabel(contractSpecs);
  const selectedNodeReadPolicy = asRecord(selectedGraphNode?.memory_read_policy);
  const selectedNodeWritePolicy = asRecord(selectedGraphNode?.memory_writeback_policy);
  const selectedNodeDynamicReadPolicy = asRecord(selectedGraphNode?.dynamic_memory_read_policy);
  const selectedNodeBackgroundPolicy = asRecord(selectedGraphNode?.background_policy);
  const selectedNodeNotificationPolicy = asRecord(selectedGraphNode?.notification_policy);
  const selectedNodeLifecyclePolicy = asRecord(selectedGraphNode?.resource_lifecycle_policy);
  const selectedEdgeWorkingMemoryPolicy = asRecord(selectedGraphEdge?.working_memory_handoff_policy);

  return (
    <>
      {!selectedGraphNode && !selectedGraphEdge ? (
        <>
          <section className="boundary-inspector-block">
            <header><strong>任务图</strong></header>
            <TaskSystemField label="标题"><input value={coordinationDraft.title} onChange={(event) => setCoordinationDraft((value) => ({ ...value, title: event.target.value }))} /></TaskSystemField>
            <TaskSystemSelectField label="协调模式" onChange={(value) => setCoordinationDraft((current) => ({ ...current, coordination_mode: value }))} options={COORDINATION_MODE_CHOICES} value={coordinationDraft.coordination_mode} formatOption={taskSystemOptionLabel} />
            <TaskSystemSelectField label="Agent 组" onChange={(value) => setCoordinationDraft((current) => ({ ...current, agent_group_id: value }))} options={agentGroupOptions} value={coordinationDraft.agent_group_id || ""} formatOption={(value) => value} />
            <label className="boundary-check">
              <input checked={editorPublished} onChange={(event) => setCoordinationPublished(event.target.checked)} type="checkbox" />
              发布为可运行任务图
            </label>
          </section>

          <section className="boundary-inspector-block">
            <header><strong>拓扑策略</strong></header>
            <TaskSystemField label="拓扑标题"><input value={topologyDraft.title} onChange={(event) => setTopologyDraft((value) => ({ ...value, title: event.target.value }))} /></TaskSystemField>
            <TaskSystemSelectField label="汇合策略" onChange={(value) => setTopologyDraft((current) => ({ ...current, join_policy: value }))} options={["explicit_join", "coordinator_join", "sequential_join"]} value={topologyDraft.join_policy} formatOption={taskSystemOptionLabel} />
            <TaskSystemSelectField label="失败策略" onChange={(value) => setTopologyDraft((current) => ({ ...current, failure_policy: value }))} options={["fail_closed", "retry_once", "coordinator_decides"]} value={topologyDraft.failure_policy} formatOption={taskSystemOptionLabel} />
            <TaskSystemSelectField label="终止策略" onChange={(value) => setTopologyDraft((current) => ({ ...current, terminal_policy: value }))} options={["coordinator_terminal", "all_nodes_complete", "manual_close"]} value={topologyDraft.terminal_policy} formatOption={taskSystemOptionLabel} />
          </section>

          <section className="boundary-inspector-block">
            <header>
              <strong>官方 A2A 通信层</strong>
              <span>{a2aCatalog?.protocol_locked ? "已锁定" : "未加载"}</span>
            </header>
            <div className="boundary-kv">
              <p><span>协议版本</span><strong>{a2aCatalog?.protocol_version || "0.3.0"}</strong></p>
              <p><span>传输</span><strong>{a2aCatalog?.transport || "JSONRPC"}</strong></p>
              <p><span>Agent Card</span><strong>{a2aCatalog?.agent_cards?.length ?? 0}</strong></p>
              <p><span>消息类型</span><strong>{(a2aCatalog?.message_types ?? ["message/send"]).join(" / ")}</strong></p>
              <p><span>Part 类型</span><strong>{(a2aCatalog?.part_types ?? DEFAULT_A2A_PART_TYPES).join(" / ")}</strong></p>
            </div>
            <TaskSystemField label="映射标题"><input value={protocolDraft.title} onChange={(event) => setProtocolDraft((value) => ({ ...value, title: event.target.value }))} /></TaskSystemField>
            <TaskSystemSelectField label="确认策略" onChange={(value) => setProtocolDraft((current) => ({ ...current, ack_policy: value }))} options={["explicit_ack", "implicit_ack"]} value={protocolDraft.ack_policy} formatOption={taskSystemOptionLabel} />
            <TaskSystemSelectField label="超时策略" onChange={(value) => setProtocolDraft((current) => ({ ...current, timeout_policy: value }))} options={["fail_closed", "retry_once", "escalate_to_coordinator"]} value={protocolDraft.timeout_policy} formatOption={taskSystemOptionLabel} />
            <TaskSystemSelectField label="错误信号" onChange={(value) => setProtocolDraft((current) => ({ ...current, error_signal_policy: value }))} options={["raise_to_coordinator", "return_to_sender", "halt_chain"]} value={protocolDraft.error_signal_policy} formatOption={taskSystemOptionLabel} />
          </section>

          <details className="boundary-system-fields">
            <summary>系统字段</summary>
            <div className="boundary-form">
              <TaskSystemField label="停止条件" wide><textarea value={coordinationDraft.stop_conditions_text} onChange={(event) => setCoordinationDraft((value) => ({ ...value, stop_conditions_text: event.target.value }))} /></TaskSystemField>
              <TaskSystemMultiSelectField label="通信模式" onChange={(value) => setCoordinationDraft((current) => ({ ...current, communication_modes: value }))} options={GRAPH_EDGE_MODE_CHOICES} value={coordinationDraft.communication_modes ?? []} wide formatOption={taskSystemOptionLabel} />
              <TaskSystemField label="拓扑 ID"><input value={topologyDraft.template_id} onChange={(event) => setTopologyDraft((value) => ({ ...value, template_id: event.target.value }))} /></TaskSystemField>
              <TaskSystemField label="协议 ID"><input value={protocolDraft.protocol_id} onChange={(event) => setProtocolDraft((value) => ({ ...value, protocol_id: event.target.value }))} /></TaskSystemField>
            </div>
          </details>
        </>
      ) : null}

      {selectedGraphNode ? (
        <section className="boundary-inspector-block">
          <header><strong>节点检查器</strong></header>
          <TaskSystemField label="节点名称"><input value={String(selectedGraphNode.label ?? selectedGraphNode.title ?? graphNodeLabel(selectedGraphNode, 0))} onChange={(event) => updateCoordinationNode(String(selectedGraphNode.node_id ?? ""), { label: event.target.value, title: event.target.value })} /></TaskSystemField>
          <TaskSystemDomainTaskSelectField
            label="绑定分任务"
            onChange={(value) => {
              const task = selectedDomainTasks.find((item) => item.task_id === value);
              updateCoordinationNode(String(selectedGraphNode.node_id ?? ""), {
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
          <TaskSystemSelectField label="工作姿态" onChange={(value) => updateCoordinationNode(String(selectedGraphNode.node_id ?? ""), { role: value, work_posture: value })} options={["coordinator", "planner", "executor", "reviewer", "verifier", "summarizer", "merge"]} value={String(selectedGraphNode.work_posture ?? selectedGraphNode.role ?? "executor")} formatOption={taskSystemOptionLabel} />
          <TaskSystemSelectField label="绑定 Agent" onChange={(value) => updateCoordinationNode(String(selectedGraphNode.node_id ?? ""), { agent_id: value })} options={agentCardOptions} value={String(selectedGraphNode.agent_id ?? "")} formatOption={formatAgentCard} />
          <TaskSystemSelectField
            label="节点契约"
            onChange={(value) => updateCoordinationNode(String(selectedGraphNode.node_id ?? ""), { node_contract_id: value, contract_id: value })}
            options={contractOptions(contractSpecs, nodeContractId(selectedGraphNode), ["node_execution", "workflow_step", "runtime"])}
            value={nodeContractId(selectedGraphNode)}
            formatOption={formatContract}
          />
          <TaskSystemField label="Runtime Lane"><input value={String(selectedGraphNode.runtime_lane ?? selectedGraphNode.lane ?? "")} onChange={(event) => updateCoordinationNode(String(selectedGraphNode.node_id ?? ""), { runtime_lane: event.target.value, lane: event.target.value })} /></TaskSystemField>
          <section className="boundary-inspector-subblock">
            <header><strong>Agent 调度</strong><span>Sync / Async</span></header>
            <TaskSystemSelectField
              label="执行模式"
              onChange={(value) => updateCoordinationNode(String(selectedGraphNode.node_id ?? ""), { execution_mode: value })}
              options={NODE_EXECUTION_MODE_OPTIONS}
              value={String(selectedGraphNode.execution_mode ?? "sync")}
              formatOption={taskSystemOptionLabel}
            />
            <TaskSystemField label="并行分组">
              <input
                onChange={(event) => updateCoordinationNode(String(selectedGraphNode.node_id ?? ""), { dispatch_group: event.target.value })}
                placeholder="例如 planning / review"
                value={String(selectedGraphNode.dispatch_group ?? "")}
              />
            </TaskSystemField>
            <TaskSystemSelectField
              label="等待策略"
              onChange={(value) => updateCoordinationNode(String(selectedGraphNode.node_id ?? ""), { wait_policy: value })}
              options={NODE_WAIT_POLICY_OPTIONS}
              value={String(selectedGraphNode.wait_policy ?? "wait_all_upstream_completed")}
              formatOption={taskSystemOptionLabel}
            />
            <TaskSystemSelectField
              label="汇合策略"
              onChange={(value) => updateCoordinationNode(String(selectedGraphNode.node_id ?? ""), { join_policy: value })}
              options={NODE_JOIN_POLICY_OPTIONS}
              value={String(selectedGraphNode.join_policy ?? "all_success")}
              formatOption={taskSystemOptionLabel}
            />
            <label className="boundary-check">
              <input
                checked={booleanValue(selectedNodeBackgroundPolicy.enabled)}
                onChange={(event) => updateCoordinationNode(String(selectedGraphNode.node_id ?? ""), {
                  background_policy: {
                    ...selectedNodeBackgroundPolicy,
                    enabled: event.target.checked,
                  },
                })}
                type="checkbox"
              />
              允许作为后台节点运行
            </label>
            <label className="boundary-check">
              <input
                checked={booleanValue(selectedNodeBackgroundPolicy.blocks_downstream)}
                onChange={(event) => updateCoordinationNode(String(selectedGraphNode.node_id ?? ""), {
                  background_policy: {
                    ...selectedNodeBackgroundPolicy,
                    blocks_downstream: event.target.checked,
                  },
                })}
                type="checkbox"
              />
              后台完成前阻塞下游
            </label>
            <TaskSystemField label="后台超时秒数">
              <input
                min={0}
                onChange={(event) => updateCoordinationNode(String(selectedGraphNode.node_id ?? ""), {
                  background_policy: {
                    ...selectedNodeBackgroundPolicy,
                    max_runtime_seconds: Number(event.target.value || 0),
                  },
                })}
                type="number"
                value={Number(selectedNodeBackgroundPolicy.max_runtime_seconds ?? 0)}
              />
            </TaskSystemField>
            <TaskSystemSelectField
              label="完成通知"
              onChange={(value) => updateCoordinationNode(String(selectedGraphNode.node_id ?? ""), {
                notification_policy: {
                  ...selectedNodeNotificationPolicy,
                  on_completed: value,
                },
              })}
              options={NOTIFICATION_POLICY_OPTIONS}
              value={String(selectedNodeNotificationPolicy.on_completed ?? "queued_summary")}
              formatOption={taskSystemOptionLabel}
            />
            <label className="boundary-check">
              <input
                checked={booleanValue(selectedNodeLifecyclePolicy.kill_on_parent_abort, true)}
                onChange={(event) => updateCoordinationNode(String(selectedGraphNode.node_id ?? ""), {
                  resource_lifecycle_policy: {
                    ...selectedNodeLifecyclePolicy,
                    kill_on_parent_abort: event.target.checked,
                  },
                })}
                type="checkbox"
              />
              父任务中止时终止该节点
            </label>
            <label className="boundary-check">
              <input
                checked={booleanValue(selectedNodeLifecyclePolicy.cleanup_on_terminal, true)}
                onChange={(event) => updateCoordinationNode(String(selectedGraphNode.node_id ?? ""), {
                  resource_lifecycle_policy: {
                    ...selectedNodeLifecyclePolicy,
                    cleanup_on_terminal: event.target.checked,
                  },
                })}
                type="checkbox"
              />
              终态后清理运行资源
            </label>
          </section>
          <div className="boundary-kv">
            <p><span>A2A Card</span><strong>{String(selectedNodeCard?.name ?? "未匹配")}</strong></p>
            <p><span>能力数</span><strong>{Array.isArray(selectedNodeCard?.skills) ? selectedNodeCard.skills.length : 0}</strong></p>
            <p><span>投影来源</span><strong>Agent 默认投影优先</strong></p>
          </div>
          <section className="boundary-inspector-subblock">
            <header><strong>节点工作记忆读取</strong><span>RunLoop 选择切片</span></header>
            <TaskSystemMultiSelectField
              label="可读 Kind"
              onChange={(value) => updateCoordinationNode(String(selectedGraphNode.node_id ?? ""), {
                memory_read_policy: updatePolicyList(selectedNodeReadPolicy, "readable_kinds", value),
              })}
              options={WORKING_MEMORY_KIND_OPTIONS}
              value={asStringList(selectedNodeReadPolicy.readable_kinds)}
              wide
              formatOption={taskSystemOptionLabel}
            />
            <TaskSystemMultiSelectField
              label="可读 Scope"
              onChange={(value) => updateCoordinationNode(String(selectedGraphNode.node_id ?? ""), {
                memory_read_policy: updatePolicyList(selectedNodeReadPolicy, "readable_scopes", value),
              })}
              options={WORKING_MEMORY_SCOPE_OPTIONS}
              value={asStringList(selectedNodeReadPolicy.readable_scopes)}
              wide
              formatOption={taskSystemOptionLabel}
            />
            <TaskSystemMultiSelectField
              label="语义过滤"
              onChange={(value) => updateCoordinationNode(String(selectedGraphNode.node_id ?? ""), {
                memory_read_policy: updatePolicyList(selectedNodeReadPolicy, "readable_semantics", value),
              })}
              options={WORKING_MEMORY_SEMANTIC_OPTIONS}
              value={asStringList(selectedNodeReadPolicy.readable_semantics)}
              wide
              formatOption={taskSystemOptionLabel}
            />
          </section>
          <section className="boundary-inspector-subblock">
            <header><strong>节点工作记忆写入</strong><span>候选写回</span></header>
            <TaskSystemMultiSelectField
              label="可写 Kind"
              onChange={(value) => updateCoordinationNode(String(selectedGraphNode.node_id ?? ""), {
                memory_writeback_policy: updatePolicyList(selectedNodeWritePolicy, "writable_kinds", value),
              })}
              options={WORKING_MEMORY_KIND_OPTIONS}
              value={asStringList(selectedNodeWritePolicy.writable_kinds)}
              wide
              formatOption={taskSystemOptionLabel}
            />
            <TaskSystemMultiSelectField
              label="可写 Scope"
              onChange={(value) => updateCoordinationNode(String(selectedGraphNode.node_id ?? ""), {
                memory_writeback_policy: updatePolicyList(selectedNodeWritePolicy, "writable_scopes", value),
              })}
              options={WORKING_MEMORY_SCOPE_OPTIONS}
              value={asStringList(selectedNodeWritePolicy.writable_scopes)}
              wide
              formatOption={taskSystemOptionLabel}
            />
            <TaskSystemSelectField
              label="默认可见性"
              onChange={(value) => updateCoordinationNode(String(selectedGraphNode.node_id ?? ""), {
                memory_writeback_policy: {
                  ...selectedNodeWritePolicy,
                  default_visibility: value,
                },
              })}
              options={WORKING_MEMORY_VISIBILITY_OPTIONS}
              value={String(selectedNodeWritePolicy.default_visibility ?? "private_to_node")}
              formatOption={taskSystemOptionLabel}
            />
            <label className="boundary-check">
              <input
                checked={booleanValue(selectedNodeWritePolicy.requires_coordinator_review, true)}
                onChange={(event) => updateCoordinationNode(String(selectedGraphNode.node_id ?? ""), {
                  memory_writeback_policy: {
                    ...selectedNodeWritePolicy,
                    requires_coordinator_review: event.target.checked,
                  },
                })}
                type="checkbox"
              />
              写入候选需要协调者采纳
            </label>
          </section>
          <section className="boundary-inspector-subblock">
            <header><strong>动态读取</strong><span>子 Agent 申请</span></header>
            <label className="boundary-check">
              <input
                checked={booleanValue(selectedNodeDynamicReadPolicy.allow_dynamic_read)}
                onChange={(event) => updateCoordinationNode(String(selectedGraphNode.node_id ?? ""), {
                  dynamic_memory_read_policy: {
                    ...selectedNodeDynamicReadPolicy,
                    allow_dynamic_read: event.target.checked,
                  },
                })}
                type="checkbox"
              />
              允许该节点动态读取工作记忆
            </label>
            <TaskSystemField label="读取次数上限">
              <input
                min={0}
                onChange={(event) => updateCoordinationNode(String(selectedGraphNode.node_id ?? ""), {
                  dynamic_memory_read_policy: {
                    ...selectedNodeDynamicReadPolicy,
                    max_dynamic_reads_per_node_run: Number(event.target.value || 0),
                  },
                })}
                type="number"
                value={Number(selectedNodeDynamicReadPolicy.max_dynamic_reads_per_node_run ?? 0)}
              />
            </TaskSystemField>
            <label className="boundary-check">
              <input
                checked={booleanValue(selectedNodeDynamicReadPolicy.allow_temporal_expansion)}
                onChange={(event) => updateCoordinationNode(String(selectedGraphNode.node_id ?? ""), {
                  dynamic_memory_read_policy: {
                    ...selectedNodeDynamicReadPolicy,
                    allow_temporal_expansion: event.target.checked,
                  },
                })}
                type="checkbox"
              />
              允许读取 temporal 邻接工作记忆
            </label>
            <TaskSystemField label="Temporal 扩展深度">
              <input
                min={0}
                onChange={(event) => updateCoordinationNode(String(selectedGraphNode.node_id ?? ""), {
                  dynamic_memory_read_policy: {
                    ...selectedNodeDynamicReadPolicy,
                    max_temporal_expansion_depth: Number(event.target.value || 0),
                  },
                })}
                type="number"
                value={Number(selectedNodeDynamicReadPolicy.max_temporal_expansion_depth ?? 0)}
              />
            </TaskSystemField>
          </section>
          {String(selectedGraphNode.role ?? "") !== "coordinator" ? (
            <TaskSystemToolbarButton onClick={() => {
              if (window.confirm("确认删除这个节点吗？")) {
                removeCoordinationNode(String(selectedGraphNode.node_id ?? ""));
              }
            }}><Trash2 size={14} />删除节点</TaskSystemToolbarButton>
          ) : null}
        </section>
      ) : null}

      {selectedGraphEdge ? (
        <section className="boundary-inspector-block">
          <header><strong>通信检查器</strong></header>
          <TaskSystemSelectField label="起点" onChange={(value) => updateCoordinationEdge(graphEdgeId(selectedGraphEdge), { from: value, source_node_id: value })} options={activeGraphNodes.map((node) => String(node.node_id ?? ""))} value={graphEdgeSource(selectedGraphEdge)} formatOption={(value) => value} />
          <TaskSystemSelectField label="终点" onChange={(value) => updateCoordinationEdge(graphEdgeId(selectedGraphEdge), { to: value, target_node_id: value })} options={activeGraphNodes.map((node) => String(node.node_id ?? ""))} value={graphEdgeTarget(selectedGraphEdge)} formatOption={(value) => value} />
          <TaskSystemSelectField label="通信模式" onChange={(value) => updateCoordinationEdge(graphEdgeId(selectedGraphEdge), { mode: value })} options={GRAPH_EDGE_MODE_CHOICES} value={String(selectedGraphEdge.mode ?? "structured_handoff")} formatOption={taskSystemOptionLabel} />
          <TaskSystemSelectField
            label="交接契约"
            onChange={(value) => updateCoordinationEdge(graphEdgeId(selectedGraphEdge), { contract_id: value, contract_refs: value ? [value] : [] })}
            options={contractOptions(contractSpecs, edgeContractId(selectedGraphEdge), ["edge_handoff"])}
            value={edgeContractId(selectedGraphEdge)}
            formatOption={formatContract}
          />
          <section className="boundary-inspector-subblock">
            <header><strong>调度边策略</strong><span>Wait / Ack</span></header>
            <TaskSystemSelectField
              label="等待策略"
              onChange={(value) => updateCoordinationEdge(graphEdgeId(selectedGraphEdge), { wait_policy: value })}
              options={["", ...NODE_WAIT_POLICY_OPTIONS]}
              value={String(selectedGraphEdge.wait_policy ?? "")}
              formatOption={(value) => value ? taskSystemOptionLabel(value) : "继承目标节点"}
            />
            <label className="boundary-check">
              <input
                checked={booleanValue(selectedGraphEdge.ack_required, true)}
                onChange={(event) => updateCoordinationEdge(graphEdgeId(selectedGraphEdge), { ack_required: event.target.checked })}
                type="checkbox"
              />
              需要目标节点确认接收
            </label>
            <TaskSystemSelectField
              label="确认策略"
              onChange={(value) => updateCoordinationEdge(graphEdgeId(selectedGraphEdge), { ack_policy: value })}
              options={["explicit_ack", "implicit_ack"]}
              value={String(selectedGraphEdge.ack_policy ?? "explicit_ack")}
              formatOption={taskSystemOptionLabel}
            />
            <TaskSystemSelectField
              label="失败传播"
              onChange={(value) => updateCoordinationEdge(graphEdgeId(selectedGraphEdge), { failure_propagation_policy: value })}
              options={EDGE_FAILURE_PROPAGATION_OPTIONS}
              value={String(selectedGraphEdge.failure_propagation_policy ?? "fail_downstream")}
              formatOption={taskSystemOptionLabel}
            />
            <TaskSystemSelectField
              label="结果投递"
              onChange={(value) => updateCoordinationEdge(graphEdgeId(selectedGraphEdge), { result_delivery_policy: value })}
              options={EDGE_RESULT_DELIVERY_OPTIONS}
              value={String(selectedGraphEdge.result_delivery_policy ?? "contract_payload_and_refs")}
              formatOption={taskSystemOptionLabel}
            />
          </section>
          <section className="boundary-inspector-subblock">
            <header><strong>工作记忆交接</strong><span>Edge Handoff</span></header>
            <TaskSystemMultiSelectField
              label="携带 Kind"
              onChange={(value) => updateCoordinationEdge(graphEdgeId(selectedGraphEdge), {
                working_memory_handoff_policy: updatePolicyList(selectedEdgeWorkingMemoryPolicy, "carry_kinds", value),
              })}
              options={WORKING_MEMORY_KIND_OPTIONS}
              value={asStringList(selectedEdgeWorkingMemoryPolicy.carry_kinds)}
              wide
              formatOption={taskSystemOptionLabel}
            />
            <TaskSystemMultiSelectField
              label="携带 Scope"
              onChange={(value) => updateCoordinationEdge(graphEdgeId(selectedGraphEdge), {
                working_memory_handoff_policy: updatePolicyList(selectedEdgeWorkingMemoryPolicy, "carry_scopes", value),
              })}
              options={WORKING_MEMORY_SCOPE_OPTIONS}
              value={asStringList(selectedEdgeWorkingMemoryPolicy.carry_scopes)}
              wide
              formatOption={taskSystemOptionLabel}
            />
            <TaskSystemField label="显式 refs" wide>
              <textarea
                onChange={(event) => updateCoordinationEdge(graphEdgeId(selectedGraphEdge), {
                  working_memory_handoff_policy: {
                    ...selectedEdgeWorkingMemoryPolicy,
                    working_memory_refs: event.target.value.split(/[\n,，]/).map((item) => item.trim()).filter(Boolean),
                  },
                })}
                value={asStringList(selectedEdgeWorkingMemoryPolicy.working_memory_refs).join("\n")}
              />
            </TaskSystemField>
            <label className="boundary-check">
              <input
                checked={booleanValue(selectedEdgeWorkingMemoryPolicy.summary_only)}
                onChange={(event) => updateCoordinationEdge(graphEdgeId(selectedGraphEdge), {
                  working_memory_handoff_policy: {
                    ...selectedEdgeWorkingMemoryPolicy,
                    summary_only: event.target.checked,
                  },
                })}
                type="checkbox"
              />
              只传摘要，不复制正文
            </label>
            <label className="boundary-check">
              <input
                checked={booleanValue(selectedEdgeWorkingMemoryPolicy.allow_artifact_refs, true)}
                onChange={(event) => updateCoordinationEdge(graphEdgeId(selectedGraphEdge), {
                  working_memory_handoff_policy: {
                    ...selectedEdgeWorkingMemoryPolicy,
                    allow_artifact_refs: event.target.checked,
                  },
                })}
                type="checkbox"
              />
              允许携带 artifact refs
            </label>
          </section>
          {selectedEdgePreview ? (
            <>
              <div className="boundary-kv">
                <p><span>A2A 类型</span><strong>{selectedEdgePreview.message_type}</strong></p>
                <p><span>传输</span><strong>{selectedEdgePreview.transport}</strong></p>
                <p><span>源 Agent</span><strong>{selectedEdgePreview.source_agent_id || "未绑定"}</strong></p>
                <p><span>目标 Agent</span><strong>{selectedEdgePreview.target_agent_id || "未绑定"}</strong></p>
                <p><span>Part</span><strong>{selectedEdgePreview.part_types.join(" / ")}</strong></p>
                <p><span>契约</span><strong>{selectedEdgePreview.payload_contracts.length ? selectedEdgePreview.payload_contracts.join(" / ") : "未配置"}</strong></p>
              </div>
              <TaskSystemField label="A2A Message 预览" wide>
                <textarea readOnly value={toPrettyJson(selectedEdgePreview)} />
              </TaskSystemField>
            </>
          ) : null}
          <TaskSystemToolbarButton onClick={() => reverseCoordinationEdge(graphEdgeId(selectedGraphEdge))}><RotateCcw size={14} />反转方向</TaskSystemToolbarButton>
          <TaskSystemToolbarButton onClick={() => {
            if (window.confirm("确认删除这条通信边吗？")) {
              removeCoordinationEdge(graphEdgeId(selectedGraphEdge));
            }
          }}><Trash2 size={14} />删除通信</TaskSystemToolbarButton>
        </section>
      ) : null}

      {selectedCoordinationGraphSpec?.issues?.length ? (
        <section className="boundary-inspector-block boundary-inspector-block--warn">
          <header><strong>图校验</strong></header>
          {selectedCoordinationGraphSpec.issues.map((issue, index) => (
            <p key={`${String(issue.code ?? "issue")}-${index}`}>{String(issue.message ?? issue.code ?? "校验问题")}</p>
          ))}
        </section>
      ) : null}
    </>
  );
}

export function CoordinationEditorWorkbench({
  selectedDomain,
  coordinationTasks,
  selectedCoordinationId,
  setSelectedCoordinationId,
  coordinationDraft,
  selectedCoordination,
  saving,
  applyCoordinationGraphTemplate,
  duplicateCoordinationDraft,
  sendCoordinationToChat,
  saveTopologyDraftIntoCoordination,
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
  connectSelectedNodeTo,
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
}: {
  selectedDomain: DomainRecordLike | null;
  coordinationTasks: CoordinationTask[];
  selectedCoordinationId: string;
  setSelectedCoordinationId: (value: string) => void;
  coordinationDraft: CoordinationDraftLike;
  selectedCoordination: CoordinationTask | null;
  saving: string;
  applyCoordinationGraphTemplate: (template: "single_agent" | "multi_sequence" | "multi_parallel_merge") => void;
  duplicateCoordinationDraft: () => Promise<void>;
  sendCoordinationToChat: (task: CoordinationTask | null, domain: DomainRecordLike | null) => void;
  saveTopologyDraftIntoCoordination: () => void;
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
  connectSelectedNodeTo: (targetNodeId: string) => void;
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
}) {
  return (
    <section className="boundary-layer-stack coordination-editor-workbench">
      <section className="boundary-card boundary-card--editor">
        <header className="boundary-editor-title">
          <div className="boundary-identity-stack">
            <span>{selectedDomain?.title || "任务域"}</span>
            <strong>{coordinationDraft.title || "任务图"}</strong>
          </div>
          <div className="boundary-graph-status">
            <span className={topologyDirty ? "boundary-status boundary-status--warn" : "boundary-status"}>
              {topologyDirty ? "拓扑未保存" : "拓扑已同步"}
            </span>
            <span className={editorValid ? "boundary-status boundary-status--ok" : "boundary-status boundary-status--danger"}>
              {editorValid ? "图校验通过" : `图校验未通过 ${editorIssueCount}`}
            </span>
            <span className={editorPublished ? "boundary-status boundary-status--ok" : "boundary-status"}>
              {editorPublished ? "已发布" : "草稿"}
            </span>
            <span>{activeGraphNodes.length} 个节点</span>
            <span>{activeGraphEdges.length} 条通信边</span>
            <TaskSystemToolbarButton disabled={!selectedCoordination || saving === "coordination-duplicate"} onClick={() => { void duplicateCoordinationDraft(); }}>
              <Plus size={15} />复制
            </TaskSystemToolbarButton>
            <TaskSystemToolbarButton onClick={saveTopologyDraftIntoCoordination}>
              <Save size={15} />同步拓扑
            </TaskSystemToolbarButton>
            <TaskSystemToolbarButton disabled={saving === "coordination"} onClick={() => { void saveCoordinationStack(false); }}>
              <Save size={15} />保存
            </TaskSystemToolbarButton>
            <TaskSystemToolbarButton onClick={() => sendCoordinationToChat(selectedCoordination, selectedDomain)}>带入会话</TaskSystemToolbarButton>
          </div>
        </header>

        <div className="coordination-editor-layout">
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
              connectSelectedNodeTo={connectSelectedNodeTo}
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
              setLinkingFromNodeId={setLinkingFromNodeId}
              setSelectedGraphEdgeId={setSelectedGraphEdgeId}
              setSelectedGraphNodeId={setSelectedGraphNodeId}
            />
          </div>

          <aside className="coordination-editor-inspector">
            <CoordinationInspectorPanel
              activeGraphNodes={activeGraphNodes}
              agentGroupOptions={agentGroupOptions}
              coordinationDraft={coordinationDraft}
              domainTaskOptions={domainTaskOptions}
              editorPublished={editorPublished}
              protocolDraft={protocolDraft}
              removeCoordinationEdge={removeCoordinationEdge}
              removeCoordinationNode={removeCoordinationNode}
              reverseCoordinationEdge={reverseCoordinationEdge}
              selectedCoordinationGraphSpec={selectedCoordinationGraphSpec}
              selectedDomain={selectedDomain}
              selectedDomainTasks={selectedDomainTasks}
              selectedGraphEdge={selectedGraphEdge}
              selectedGraphNode={selectedGraphNode}
              setCoordinationDraft={setCoordinationDraft}
              setCoordinationPublished={setCoordinationPublished}
              setProtocolDraft={setProtocolDraft}
              setTopologyDraft={setTopologyDraft}
              topologyDraft={topologyDraft}
              updateCoordinationEdge={updateCoordinationEdge}
              updateCoordinationNode={updateCoordinationNode}
              a2aCatalog={a2aCatalog}
              contractSpecs={contractSpecs}
            />
          </aside>
        </div>
      </section>
    </section>
  );
}
