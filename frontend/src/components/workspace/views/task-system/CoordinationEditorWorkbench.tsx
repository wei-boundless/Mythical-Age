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
import type { Dispatch, ReactNode, SetStateAction } from "react";

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
  return (
    <>
      <section className="boundary-inspector-block">
        <header>
          <strong>任务池</strong>
          <span>{selectedDomainTasks.length}</span>
        </header>
        <div className="boundary-task-table">
          {selectedDomainTasks.map((task) => (
            <article key={task.task_id}>
              <strong>{task.task_title}</strong>
              <span>{displayId(task.task_mode)}</span>
              <div className="coordination-editor-actions">
                <button className="boundary-chip" disabled={boundCoordinationTaskIds.has(task.task_id)} onClick={() => addCoordinationTaskNode(task, "executor")} type="button">
                  <span>{boundCoordinationTaskIds.has(task.task_id) ? "已加入" : "加入为任务节点"}</span>
                </button>
                <button className="boundary-chip" disabled={boundCoordinationTaskIds.has(task.task_id)} onClick={() => addCoordinationTaskNode(task, "reviewer")} type="button">
                  <span>加入为审查节点</span>
                </button>
              </div>
            </article>
          ))}
          {!selectedDomainTasks.length ? <div className="boundary-empty">当前任务域暂无可装配任务。</div> : null}
        </div>
      </section>

      <section className="boundary-inspector-block">
        <header>
          <strong>图模板</strong>
          <span>一键起图</span>
        </header>
        <div className="boundary-chip-grid">
          <button className="boundary-chip" onClick={() => applyCoordinationGraphTemplate("single_agent")} type="button"><span>单 Agent 执行图</span></button>
          <button className="boundary-chip" onClick={() => applyCoordinationGraphTemplate("multi_sequence")} type="button"><span>A -&gt; B 顺序协作</span></button>
          <button className="boundary-chip" onClick={() => applyCoordinationGraphTemplate("multi_parallel_merge")} type="button"><span>A || B -&gt; 汇总</span></button>
        </div>
      </section>

      <section className="boundary-inspector-block">
        <header>
          <strong>节点模板</strong>
          <span>快捷</span>
        </header>
        <div className="boundary-chip-grid">
          <button className="boundary-chip" onClick={() => addCoordinationRoleNode("coordinator")} type="button"><span>入口协调节点</span></button>
          <button className="boundary-chip" onClick={() => addCoordinationRoleNode("planner")} type="button"><span>规划节点</span></button>
          <button className="boundary-chip" onClick={() => addCoordinationRoleNode("executor")} type="button"><span>执行节点</span></button>
          <button className="boundary-chip" onClick={() => addCoordinationRoleNode("reviewer")} type="button"><span>审查节点</span></button>
          <button className="boundary-chip" onClick={() => addCoordinationRoleNode("verifier")} type="button"><span>验证节点</span></button>
          <button className="boundary-chip" onClick={() => addCoordinationRoleNode("merge")} type="button"><span>汇总节点</span></button>
          <button className="boundary-chip" onClick={addCoordinationNode} type="button"><span>空白 Agent 节点</span></button>
        </div>
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
  connectSelectedNodeTo,
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
  connectSelectedNodeTo: (targetNodeId: string) => void;
}) {
  const selectedNodeTitle = selectedGraphNode ? graphNodeLabel(selectedGraphNode, 0) : "";

  return (
    <>
      <section className="coordination-editor-canvas-shell">
        <header className="coordination-editor-canvas-head">
          <div className="boundary-identity-stack">
            <span>拓扑画布</span>
            <strong>节点与通信关系</strong>
            <small>优先在图上装配节点，再进入右侧检查器细化属性。</small>
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

          <section className="coordination-editor-assist">
            <header className="coordination-editor-assist__head">
              <div className="boundary-identity-stack">
                <span>快速操作</span>
                <strong>{linkingFromNodeId ? "等待选择目标节点" : selectedNodeTitle || "选择一个节点开始连线"}</strong>
                <small>{linkingFromNodeId ? `当前起点：${linkingFromNodeId}` : "画布下方只保留当前动作，不再堆积无关信息。"}</small>
              </div>
            </header>
            {linkingFromNodeId ? (
              <div className="boundary-empty">正在从 {linkingFromNodeId} 连线，点击图上的目标节点即可创建通信边。</div>
            ) : selectedGraphNode ? (
              <div className="boundary-chip-grid">
                {activeGraphNodes
                  .filter((node) => String(node.node_id ?? "") !== String(selectedGraphNode.node_id ?? ""))
                  .map((node) => (
                    <button className="boundary-chip" key={String(node.node_id ?? "")} onClick={() => connectSelectedNodeTo(String(node.node_id ?? ""))} type="button">
                      <span>{String(node.label ?? node.title ?? node.node_id ?? "")}</span>
                    </button>
                  ))}
                {activeGraphNodes.length <= 1 ? <div className="boundary-empty">至少需要两个节点才能建立通信。</div> : null}
              </div>
            ) : (
              <div className="boundary-empty">先在图中选中一个节点，再选择它要连接的目标节点。</div>
            )}
          </section>
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
          <div className="boundary-kv">
            <p><span>A2A Card</span><strong>{String(selectedNodeCard?.name ?? "未匹配")}</strong></p>
            <p><span>能力数</span><strong>{Array.isArray(selectedNodeCard?.skills) ? selectedNodeCard.skills.length : 0}</strong></p>
            <p><span>投影来源</span><strong>Agent 默认投影优先</strong></p>
          </div>
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
  const communicationLabel = (coordinationDraft.communication_modes ?? []).length
    ? (coordinationDraft.communication_modes ?? []).slice(0, 3).join(" / ")
    : "未设置";

  return (
    <section className="boundary-layer-stack coordination-editor-workbench">
      <div className="boundary-card boundary-card--summary">
        <header className="coordination-editor-summary-head">
          <div className="boundary-identity-stack">
            <span>{selectedDomain?.title || "任务域"} / 任务图草稿</span>
            <strong>{coordinationDraft.title || "任务图"}</strong>
            <small>{coordinationTasks.length} 个图草稿</small>
          </div>
          <div className="coordination-editor-command-groups">
            <div className="coordination-editor-command-group">
              <span>图模板与草稿</span>
              <div className="boundary-actions">
                <TaskSystemToolbarButton disabled={!selectedCoordination || saving === "coordination-duplicate"} onClick={() => { void duplicateCoordinationDraft(); }}>
                  <Plus size={15} />复制为草稿
                </TaskSystemToolbarButton>
              </div>
            </div>
            <div className="coordination-editor-command-group">
              <span>拓扑草稿</span>
              <div className="boundary-actions">
                <TaskSystemToolbarButton onClick={saveTopologyDraftIntoCoordination}>
                  <Save size={15} />保存拓扑
                </TaskSystemToolbarButton>
                <TaskSystemToolbarButton onClick={() => sendCoordinationToChat(selectedCoordination, selectedDomain)}>带入主会话</TaskSystemToolbarButton>
                <TaskSystemToolbarButton disabled={saving === "coordination"} onClick={() => { void saveCoordinationStack(false); }}>
                  <Save size={15} />保存草稿
                </TaskSystemToolbarButton>
              </div>
            </div>
          </div>
        </header>
        {coordinationTasks.length ? (
          <div className="task-system-section-switch coordination-editor-selector">
            <div className="task-system-section-switch__head">
              <span>任务图草稿</span>
              <strong>{selectedCoordination?.title || coordinationDraft.title || "未选择任务图"}</strong>
            </div>
            <div className="boundary-selector-strip boundary-selector-strip--compact">
            {coordinationTasks.map((task) => (
              <button className={task.coordination_task_id === selectedCoordinationId ? "active" : ""} key={task.coordination_task_id} onClick={() => setSelectedCoordinationId(task.coordination_task_id)} type="button">
                <strong>{task.title}</strong>
                <span>{displayId(task.coordination_mode)}</span>
              </button>
            ))}
            </div>
          </div>
        ) : <div className="boundary-empty">当前任务域暂无任务图草稿。</div>}
        <div className="coordination-editor-meta-strip">
          <article className="coordination-editor-meta-card">
            <span>协调模式</span>
            <strong>{displayId(coordinationDraft.coordination_mode)}</strong>
            <small>决定拓扑推进和汇合方式。</small>
          </article>
          <article className="coordination-editor-meta-card">
            <span>Agent 组</span>
            <strong>{coordinationDraft.agent_group_id || "未绑定"}</strong>
            <small>运行时从该组分派执行主体。</small>
          </article>
          <article className="coordination-editor-meta-card">
            <span>官方 A2A</span>
            <strong>{a2aCatalog?.transport || "JSONRPC"} · {a2aCatalog?.protocol_version || "0.3.0"}</strong>
            <small>{a2aCatalog?.protocol_locked ? "通信协议固定，图上边只配置业务语义。" : "等待后端 A2A catalog。"}</small>
          </article>
          <article className="coordination-editor-meta-card">
            <span>图规模</span>
            <strong>{activeGraphNodes.length} 节点 / {activeGraphEdges.length} 边</strong>
            <small>{editorValid ? "当前拓扑可发布运行。" : activeGraphNodes.length ? `仍有 ${editorIssueCount} 个问题待处理。` : "空图不能发布，先创建任务节点。"}</small>
          </article>
        </div>
      </div>
      <section className="boundary-card boundary-card--editor">
        <header className="boundary-editor-title">
          <strong>任务图编辑器</strong>
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
