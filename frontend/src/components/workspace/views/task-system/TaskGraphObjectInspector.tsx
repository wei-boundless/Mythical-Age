"use client";

import { Cable, ExternalLink, FileWarning, GitBranch, Layers3, Network, Plus, Trash2 } from "lucide-react";

import type {
  ComposableUnitSpec,
  ContractSpec,
  NestedRuntimePlanSpec,
  OrchestrationAgentRuntimeCatalog,
  SpecificTaskRecord,
  TaskGraphRecord,
  UnitInterfaceSpec,
  UnitPortEdgeSpec,
} from "@/lib/api";

import type { TaskGraphDraftV2 } from "./taskGraphDraftV2";
import { taskGraphDisplayName } from "./taskGraphNameRegistry";
import {
  removeTaskGraphOverlayPortEdge,
  taskGraphComposableOverlayMetadataPatch,
  taskGraphComposableOverlayFromMetadata,
  upsertTaskGraphOverlayPortEdge,
} from "./taskGraphModuleComposition";
import type { TaskGraphComposableSubject } from "./taskGraphComposableEditorTypes";
import type { TaskGraphWorkbenchAgentCatalog } from "./taskGraphTypes";
import { graphEdgeId } from "./taskGraphTopologyUtils";
import {
  TaskSystemDomainTaskSelectField,
  TaskSystemField,
  TaskSystemSelectField,
  taskSystemOptionLabel,
} from "./TaskSystemWorkbenchUi";
import { coordinationTimelineBlocks, type TaskGraphTimelineBlock } from "./taskGraphTimeline";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function stringValue(value: unknown, fallback = "") {
  const next = String(value ?? "").trim();
  return next || fallback;
}

function booleanValue(value: unknown, fallback = false) {
  return typeof value === "boolean" ? value : fallback;
}

function uniqueStrings(values: Array<string | null | undefined>) {
  return Array.from(new Set(values.map((item) => String(item ?? "").trim()).filter(Boolean)));
}

function splitList(value: string) {
  return value.split(/[\n,，]/).map((item) => item.trim()).filter(Boolean);
}

function listText(value: unknown) {
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean).join("\n") : "";
}

function selectedUnit(subject: TaskGraphComposableSubject, units: ComposableUnitSpec[]) {
  return subject.kind === "unit" ? units.find((unit) => unit.unit_id === subject.unit_id) ?? null : null;
}

function selectedPortEdge(subject: TaskGraphComposableSubject, portEdges: UnitPortEdgeSpec[]) {
  return subject.kind === "port_edge" ? portEdges.find((edge) => edge.edge_id === subject.edge_id) ?? null : null;
}

function selectedTimelineBlock(subject: TaskGraphComposableSubject, blocks: TaskGraphTimelineBlock[]) {
  return subject.kind === "timeline_block" ? blocks.find((block) => block.block_id === subject.block_id) ?? null : null;
}

function selectedNestedRuntime(subject: TaskGraphComposableSubject, plans: NestedRuntimePlanSpec[]) {
  return subject.kind === "nested_runtime" ? plans.find((plan) => plan.plan_id === subject.plan_id) ?? null : null;
}

function isOverlayEdge(edge: UnitPortEdgeSpec | null, overlayEdgeIds: Set<string>) {
  return Boolean(edge && (overlayEdgeIds.has(edge.edge_id) || asRecord(edge.metadata).explicit_overlay));
}

function portOptionsForUnit(unitId: string, interfaces: UnitInterfaceSpec[], direction?: "input" | "output") {
  const iface = interfaces.find((item) => item.unit_id === unitId);
  if (!iface) return [];
  const ports = direction === "input"
    ? iface.input_ports
    : direction === "output"
      ? iface.output_ports
      : [...iface.input_ports, ...iface.output_ports];
  return ports.map((port) => port.port_id).filter(Boolean);
}

function edgeSourceSummary(edge: UnitPortEdgeSpec) {
  return `${edge.source_unit_id}.${edge.source_port_id} -> ${edge.target_unit_id}.${edge.target_port_id}`;
}

function nodeIdFromUnit(unit: ComposableUnitSpec | null) {
  return stringValue(asRecord(unit?.ref).node_id);
}

function blockIdFromUnit(unit: ComposableUnitSpec | null) {
  return stringValue(asRecord(unit?.ref).timeline_block_id);
}

function graphEdgeSource(edge: Record<string, unknown>) {
  return stringValue(edge.source_node_id ?? edge.from ?? edge.source);
}

function graphEdgeTarget(edge: Record<string, unknown>) {
  return stringValue(edge.target_node_id ?? edge.to ?? edge.target);
}

function nodeTitle(node: Record<string, unknown> | null, fallback = "节点") {
  return stringValue(node?.title ?? node?.label ?? node?.task_title ?? node?.node_id, fallback);
}

function contractTitle(contract: ContractSpec) {
  return stringValue(contract.title_zh ?? contract.title_en ?? contract.contract_id, contract.contract_id);
}

function taskLabel(taskId: string, tasks: SpecificTaskRecord[], options: Array<{ value: string; label: string }>) {
  const task = tasks.find((item) => item.task_id === taskId);
  const option = options.find((item) => item.value === taskId);
  if (!taskId) return "不绑定任务";
  return task ? `${task.task_title} · ${task.task_id}` : option?.label ?? taskId;
}

function ObjectSelectField({
  emptyLabel = "未绑定",
  formatOption = (value: string) => value,
  label,
  onChange,
  options,
  value,
  wide = false,
}: {
  emptyLabel?: string;
  formatOption?: (value: string) => string;
  label: string;
  onChange: (value: string) => void;
  options: string[];
  value: string;
  wide?: boolean;
}) {
  const resolvedOptions = uniqueStrings([value, ...options]);
  return (
    <TaskSystemField label={label} wide={wide}>
      <select onChange={(event) => onChange(event.target.value)} value={value}>
        <option value="">{emptyLabel}</option>
        {resolvedOptions.map((item) => (
          <option key={item} value={item}>{formatOption(item)}</option>
        ))}
      </select>
    </TaskSystemField>
  );
}

export function TaskGraphObjectInspector({
  activeGraphEdges,
  activeGraphNodes,
  a2aCatalog,
  contractSpecs,
  domainTaskOptions,
  graphDraft,
  interfaces,
  nestedRuntime,
  onOpenGraph,
  onSelectSubject,
  orchestrationAgentCatalog,
  portEdges,
  projectionCards = [],
  selectedDomainTasks,
  selectedSubject,
  taskGraphs,
  units,
  updateTaskGraphDraft,
  updateTaskGraphEdge,
  updateTaskGraphMetadata,
  updateTaskGraphNode,
  updateTaskGraphRuntimePolicy,
}: {
  activeGraphEdges: Array<Record<string, unknown>>;
  activeGraphNodes: Array<Record<string, unknown>>;
  a2aCatalog?: TaskGraphWorkbenchAgentCatalog | null;
  contractSpecs: ContractSpec[];
  domainTaskOptions: Array<{ value: string; label: string }>;
  graphDraft: TaskGraphDraftV2;
  interfaces: UnitInterfaceSpec[];
  nestedRuntime: NestedRuntimePlanSpec[];
  onOpenGraph?: (graphId: string) => void;
  onSelectSubject: (subject: TaskGraphComposableSubject) => void;
  orchestrationAgentCatalog?: OrchestrationAgentRuntimeCatalog | null;
  portEdges: UnitPortEdgeSpec[];
  projectionCards?: Array<{ projection_id: string; title?: string; soul_name?: string; soul_id?: string }>;
  selectedDomainTasks: SpecificTaskRecord[];
  selectedSubject: TaskGraphComposableSubject;
  taskGraphs?: TaskGraphRecord[];
  units: ComposableUnitSpec[];
  updateTaskGraphDraft: (patch: Partial<TaskGraphDraftV2>) => void;
  updateTaskGraphEdge: (edgeId: string, patch: Record<string, unknown>) => void;
  updateTaskGraphMetadata: (patch: Record<string, unknown>) => void;
  updateTaskGraphNode: (nodeId: string, patch: Record<string, unknown>) => void;
  updateTaskGraphRuntimePolicy: (patch: Partial<TaskGraphDraftV2["runtime_policy"]>) => void;
}) {
  const metadata = asRecord(graphDraft.metadata);
  const overlay = taskGraphComposableOverlayFromMetadata(metadata);
  const overlayEdgeIds = new Set(overlay.port_edges.map((edge) => edge.edge_id));
  const blocks = coordinationTimelineBlocks(metadata);
  const unit = selectedUnit(selectedSubject, units);
  const portEdge = selectedPortEdge(selectedSubject, portEdges);
  const block = selectedTimelineBlock(selectedSubject, blocks);
  const nestedPlan = selectedNestedRuntime(selectedSubject, nestedRuntime);
  const unitOptions = units.map((item) => item.unit_id);
  const nodeUnitOptions = units.filter((item) => nodeIdFromUnit(item)).map((item) => item.unit_id);
  const graphName = taskGraphDisplayName(graphDraft.graph_id, undefined, metadata, graphDraft.title || graphDraft.graph_id);
  const contractOptions = contractSpecs.map((item) => item.contract_id);
  const agentOptions = uniqueStrings([
    graphDraft.runtime_policy.coordinator_agent_id,
    ...(graphDraft.runtime_policy.participant_agent_ids ?? []),
    ...activeGraphNodes.map((node) => stringValue(node.agent_id)),
    ...((orchestrationAgentCatalog?.agents ?? []).map((agent) => stringValue(agent.agent_id))),
    ...((a2aCatalog?.agent_cards ?? []).map((card) => stringValue(card.agent_id))),
  ]);
  const projectionOptions = projectionCards.map((item) => item.projection_id);
  const graphOptions = (taskGraphs ?? []).map((item) => item.graph_id);

  const formatUnit = (unitId: string) => {
    const item = units.find((candidate) => candidate.unit_id === unitId);
    if (!item) return unitId;
    const title = taskGraphDisplayName(item.unit_id, item as unknown as Record<string, unknown>, metadata, item.title || item.unit_id);
    return `${title} · ${item.unit_type}`;
  };
  const formatContract = (contractId: string) => {
    const contract = contractSpecs.find((item) => item.contract_id === contractId);
    return contract ? `${contractTitle(contract)} · ${contractId}` : contractId || "未绑定契约";
  };
  const formatAgent = (agentId: string) => {
    const agent = (orchestrationAgentCatalog?.agents ?? []).find((item) => stringValue(item.agent_id) === agentId);
    const card = (a2aCatalog?.agent_cards ?? []).find((item) => stringValue(item.agent_id) === agentId);
    if (!agentId) return "不绑定 Agent";
    const agentName = stringValue(agent?.display_name ?? agent?.agent_name);
    if (agentName) return `${agentName} · ${agentId}`;
    return card?.name ? `${String(card.name)} · ${agentId}` : agentId;
  };
  const formatProjection = (projectionId: string) => {
    const card = projectionCards.find((item) => item.projection_id === projectionId);
    if (!projectionId) return "不绑定 Projection";
    if (!card) return projectionId;
    const title = stringValue(card.title ?? card.projection_id, projectionId);
    const soul = stringValue(card.soul_name ?? card.soul_id);
    return soul ? `${title} · ${soul}` : title;
  };
  const formatGraph = (graphId: string) => {
    const graph = (taskGraphs ?? []).find((item) => item.graph_id === graphId);
    return graph ? `${graph.title || graph.graph_id} · ${graph.graph_id}` : graphId || "不绑定子任务图";
  };

  const updateTimelineBlock = (blockId: string, patch: Record<string, unknown>) => {
    updateTaskGraphMetadata({
      timeline_blocks: blocks.map((item) => (item.block_id === blockId ? { ...item, ...patch } : item)),
    });
  };

  const addTimelineBlock = () => {
    const nextIndex = blocks.length + 1;
    const blockId = `block.phase.${nextIndex}`;
    updateTaskGraphMetadata({
      timeline_blocks: [
        ...blocks,
        {
          block_id: blockId,
          block_type: nextIndex === 1 ? "design_graph" : "phase_graph",
          title: `阶段图块 ${nextIndex}`,
          phase_id: "phase.unassigned",
          linked_graph_id: "",
          entry_node_id: graphDraft.entry_node_id,
          exit_node_id: graphDraft.output_node_id,
          handoff_contract_id: `${blockId}.handoff`,
          visibility_policy: "committed_only",
          version_ref: "draft",
          detach_policy: "preserve_version_anchor",
        },
      ],
    });
    onSelectSubject({ kind: "timeline_block", block_id: blockId });
  };

  const removeTimelineBlock = (blockId: string) => {
    updateTaskGraphMetadata({ timeline_blocks: blocks.filter((item) => item.block_id !== blockId) });
    onSelectSubject({ kind: "graph", graph_id: graphDraft.graph_id });
  };

  const addOverlayPortEdge = (seed?: Partial<UnitPortEdgeSpec>) => {
    const sourceUnitId = seed?.source_unit_id ?? units[0]?.unit_id ?? "";
    const targetUnitId = seed?.target_unit_id ?? units[1]?.unit_id ?? sourceUnitId;
    const sourcePortId = seed?.source_port_id ?? portOptionsForUnit(sourceUnitId, interfaces, "output")[0] ?? "output.default";
    const targetPortId = seed?.target_port_id ?? portOptionsForUnit(targetUnitId, interfaces, "input")[0] ?? "input.default";
    const edgeId = seed?.edge_id ?? `port_edge.explicit.${overlay.port_edges.length + 1}`;
    updateTaskGraphMetadata(upsertTaskGraphOverlayPortEdge(metadata, {
      edge_id: edgeId,
      source_unit_id: sourceUnitId,
      source_port_id: sourcePortId,
      target_unit_id: targetUnitId,
      target_port_id: targetPortId,
      payload_contract_id: seed?.payload_contract_id ?? "",
      edge_type: seed?.edge_type ?? "handoff",
      temporal_semantics: {
        trigger_timing: "after_source_success",
        visibility_timing: "after_commit",
        acknowledgement_timing: "explicit_ack",
        propagation_timing: "buffer_until_commit",
        ...asRecord(seed?.temporal_semantics),
      },
      handoff: asRecord(seed?.handoff),
      metadata: { ...asRecord(seed?.metadata), explicit_overlay: true },
    }));
    onSelectSubject({ kind: "port_edge", edge_id: edgeId });
  };

  const updateOverlayPortEdge = (edge: UnitPortEdgeSpec, patch: Record<string, unknown>) => {
    const nextEdge: UnitPortEdgeSpec = {
      ...edge,
      ...patch,
      edge_id: stringValue(patch.edge_id ?? edge.edge_id),
      source_unit_id: stringValue(patch.source_unit_id ?? edge.source_unit_id),
      source_port_id: stringValue(patch.source_port_id ?? edge.source_port_id),
      target_unit_id: stringValue(patch.target_unit_id ?? edge.target_unit_id),
      target_port_id: stringValue(patch.target_port_id ?? edge.target_port_id),
      payload_contract_id: stringValue(patch.payload_contract_id ?? edge.payload_contract_id),
      edge_type: stringValue(patch.edge_type ?? edge.edge_type, "handoff"),
      temporal_semantics: asRecord(patch.temporal_semantics ?? edge.temporal_semantics),
      handoff: asRecord(patch.handoff ?? edge.handoff),
      metadata: {
        ...asRecord(edge.metadata),
        ...asRecord(patch.metadata),
        explicit_overlay: true,
      },
    };
    updateTaskGraphMetadata(taskGraphComposableOverlayMetadataPatch(metadata, {
      port_edges: overlay.port_edges.map((item) => (item.edge_id === edge.edge_id ? nextEdge : item)),
    }));
  };

  const updateOverlayPortEdgeTemporal = (edge: UnitPortEdgeSpec, patch: Record<string, unknown>) => {
    updateOverlayPortEdge(edge, {
      temporal_semantics: {
        ...asRecord(edge.temporal_semantics),
        ...patch,
      },
    });
  };

  const removeOverlayEdge = (edgeId: string) => {
    updateTaskGraphMetadata(removeTaskGraphOverlayPortEdge(metadata, edgeId));
    onSelectSubject({ kind: "graph", graph_id: graphDraft.graph_id });
  };

  const nodeForUnit = (selected: ComposableUnitSpec) => {
    const nodeId = nodeIdFromUnit(selected);
    return nodeId ? activeGraphNodes.find((node) => stringValue(node.node_id ?? node.id) === nodeId) ?? null : null;
  };

  const edgeForPortEdge = (edge: UnitPortEdgeSpec) => {
    const edgeMetadata = asRecord(edge.metadata);
    const sourceNodeId = stringValue(edgeMetadata.source_node_id);
    const targetNodeId = stringValue(edgeMetadata.target_node_id);
    return activeGraphEdges.find((item, index) => graphEdgeId(item, index) === edge.edge_id)
      ?? activeGraphEdges.find((item) => sourceNodeId && targetNodeId && graphEdgeSource(item) === sourceNodeId && graphEdgeTarget(item) === targetNodeId)
      ?? null;
  };

  const patchEdgeMetadata = (edgeId: string, edge: Record<string, unknown>, patch: Record<string, unknown>) => {
    updateTaskGraphEdge(edgeId, {
      metadata: {
        ...asRecord(edge.metadata),
        ...patch,
      },
    });
  };

  const patchEdgeTemporal = (edgeId: string, edge: Record<string, unknown>, patch: Record<string, unknown>) => {
    const currentMetadata = asRecord(edge.metadata);
    updateTaskGraphEdge(edgeId, {
      metadata: {
        ...currentMetadata,
        ...patch,
        temporal_semantics: {
          ...asRecord(currentMetadata.temporal_semantics),
          ...patch,
        },
      },
    });
  };

  const patchEdgeMemoryHandoff = (edgeId: string, edge: Record<string, unknown>, patch: Record<string, unknown>) => {
    updateTaskGraphEdge(edgeId, {
      working_memory_handoff_policy: {
        ...asRecord(edge.working_memory_handoff_policy),
        ...patch,
      },
    });
  };

  const updateLegacyEdgeEndpoint = (edge: Record<string, unknown>, edgeId: string, patch: Record<string, unknown>) => {
    const currentMetadata = asRecord(edge.metadata);
    const sourceUnitId = stringValue(patch.source_unit_id);
    const targetUnitId = stringValue(patch.target_unit_id);
    const sourceNodeId = sourceUnitId ? nodeIdFromUnit(units.find((item) => item.unit_id === sourceUnitId) ?? null) : "";
    const targetNodeId = targetUnitId ? nodeIdFromUnit(units.find((item) => item.unit_id === targetUnitId) ?? null) : "";
    updateTaskGraphEdge(edgeId, {
      ...(sourceNodeId ? { source_node_id: sourceNodeId, from: sourceNodeId } : {}),
      ...(targetNodeId ? { target_node_id: targetNodeId, to: targetNodeId } : {}),
      metadata: {
        ...currentMetadata,
        ...(patch.source_port_id ? { source_port_id: patch.source_port_id } : {}),
        ...(patch.target_port_id ? { target_port_id: patch.target_port_id } : {}),
      },
    });
  };

  const renderGraphEditor = () => (
    <>
      <section className="task-graph-composer-inspector-card">
        <header>
          <GitBranch aria-hidden="true" size={15} />
          <strong>任务图</strong>
          <span>{graphDraft.graph_id}</span>
        </header>
        <div className="task-graph-composer-selection-title">
          <span>当前任务图</span>
          <strong>{graphName}</strong>
          <small>任务图是流程结构；运行时会按节点时序点生成任务动作。</small>
        </div>
        <div className="task-graph-composer-mini-metrics">
          <p><span>节点/Unit</span><strong>{units.length}</strong></p>
          <p><span>接口</span><strong>{interfaces.length}</strong></p>
          <p><span>交接边</span><strong>{portEdges.length}</strong></p>
          <p><span>图节点</span><strong>{units.filter((item) => item.unit_type === "graph").length}</strong></p>
        </div>
      </section>

      <section className="task-graph-composer-inspector-card">
        <header>
          <GitBranch aria-hidden="true" size={15} />
          <strong>任务图配置</strong>
        </header>
        <div className="boundary-form task-graph-composer-inspector-form">
          <TaskSystemField label="中文名 / 标题" wide>
            <input onChange={(event) => updateTaskGraphDraft({ title: event.target.value })} value={graphDraft.title} />
          </TaskSystemField>
          <ObjectSelectField
            formatOption={formatContract}
            label="图级契约"
            onChange={(value) => updateTaskGraphDraft({ graph_contract_id: value })}
            options={contractOptions}
            value={graphDraft.graph_contract_id}
            wide
          />
          <ObjectSelectField
            formatOption={(value) => nodeTitle(activeGraphNodes.find((node) => stringValue(node.node_id) === value) ?? null, value)}
            label="入口节点"
            onChange={(value) => updateTaskGraphDraft({ entry_node_id: value })}
            options={activeGraphNodes.map((node) => stringValue(node.node_id)).filter(Boolean)}
            value={graphDraft.entry_node_id}
          />
          <ObjectSelectField
            formatOption={(value) => nodeTitle(activeGraphNodes.find((node) => stringValue(node.node_id) === value) ?? null, value)}
            label="出口节点"
            onChange={(value) => updateTaskGraphDraft({ output_node_id: value })}
            options={activeGraphNodes.map((node) => stringValue(node.node_id)).filter(Boolean)}
            value={graphDraft.output_node_id}
          />
          <ObjectSelectField
            formatOption={formatAgent}
            label="协调 Agent"
            onChange={(value) => updateTaskGraphRuntimePolicy({ coordinator_agent_id: value })}
            options={agentOptions}
            value={stringValue(graphDraft.runtime_policy.coordinator_agent_id, "agent:0")}
            wide
          />
          <TaskSystemSelectField
            label="协作模式"
            onChange={(value) => updateTaskGraphRuntimePolicy({ coordination_mode: value })}
            options={["review_merge", "pipeline", "parallel_review"]}
            value={stringValue(graphDraft.runtime_policy.coordination_mode, "review_merge")}
          />
        </div>
      </section>

      <section className="task-graph-composer-inspector-card">
        <header>
          <Plus aria-hidden="true" size={15} />
          <strong>结构动作</strong>
        </header>
        <div className="task-graph-topology-actions task-graph-topology-actions--stacked">
          <button onClick={addTimelineBlock} type="button">
            <Layers3 aria-hidden="true" size={14} />
            <span>新增图节点来源</span>
          </button>
          <button disabled={!units.length} onClick={() => addOverlayPortEdge()} type="button">
            <Cable aria-hidden="true" size={14} />
            <span>新增显式端口边</span>
          </button>
        </div>
      </section>
    </>
  );

  const renderNodeUnitEditor = (selected: ComposableUnitSpec, node: Record<string, unknown>) => {
    const nodeId = nodeIdFromUnit(selected);
    const iface = interfaces.find((item) => item.unit_id === selected.unit_id) ?? null;
    const unitEdges = portEdges.filter((edge) => edge.source_unit_id === selected.unit_id || edge.target_unit_id === selected.unit_id);
    const taskId = stringValue(node.task_id ?? node.task_ref ?? node.subtask_ref);
    return (
      <>
        <section className="task-graph-composer-inspector-card">
          <header>
            <GitBranch aria-hidden="true" size={15} />
            <strong>节点</strong>
            <span>时序点 / 执行位</span>
          </header>
          <div className="task-graph-composer-selection-title">
            <span>{stringValue(node.node_type, selected.unit_type)}</span>
            <strong>{nodeTitle(node, selected.title || selected.unit_id)}</strong>
            <small>{nodeId}</small>
          </div>
          <div className="task-graph-composer-kv">
            <p><span>接口</span><strong>{iface?.interface_id || selected.interface_id || "未派生"}</strong></p>
            <p><span>阶段</span><strong>{stringValue(node.phase_id ?? selected.phase_id, "未分配")}</strong></p>
            <p><span>绑定任务</span><strong>{taskLabel(taskId, selectedDomainTasks, domainTaskOptions)}</strong></p>
            <p><span>连接边</span><strong>{unitEdges.length}</strong></p>
          </div>
        </section>

        <section className="task-graph-composer-inspector-card">
          <header>
            <GitBranch aria-hidden="true" size={15} />
            <strong>节点配置</strong>
          </header>
          <div className="boundary-form task-graph-composer-inspector-form">
            <TaskSystemField label="中文名 / 标题" wide>
              <input onChange={(event) => updateTaskGraphNode(nodeId, { title: event.target.value, label: event.target.value })} value={nodeTitle(node, "")} />
            </TaskSystemField>
            <TaskSystemSelectField
              label="节点类型"
              onChange={(value) => updateTaskGraphNode(nodeId, { node_type: value })}
              options={["agent_role", "review_gate", "loop_frame", "memory_repository", "artifact_repository", "thread_ledger", "issue_ledger", "runtime_state_store", "manual_gate", "tool"]}
              value={stringValue(node.node_type, "agent_role")}
            />
            <TaskSystemDomainTaskSelectField
              label="运行时任务"
              onChange={(value) => updateTaskGraphNode(nodeId, { task_id: value })}
              options={domainTaskOptions}
              value={taskId}
            />
            <ObjectSelectField
              formatOption={formatAgent}
              label="执行 Agent"
              onChange={(value) => updateTaskGraphNode(nodeId, { agent_id: value })}
              options={agentOptions}
              value={stringValue(node.agent_id)}
              wide
            />
            <ObjectSelectField
              formatOption={formatProjection}
              label="职责 Projection"
              onChange={(value) => updateTaskGraphNode(nodeId, { projection_id: value, projection_overlay_id: value })}
              options={projectionOptions}
              value={stringValue(node.projection_id ?? node.projection_overlay_id)}
              wide
            />
            <ObjectSelectField
              formatOption={formatContract}
              label="节点契约"
              onChange={(value) => updateTaskGraphNode(nodeId, { node_contract_id: value, contract_id: value })}
              options={contractOptions}
              value={stringValue(node.node_contract_id ?? node.contract_id)}
            />
            <ObjectSelectField
              formatOption={formatContract}
              label="输入契约"
              onChange={(value) => updateTaskGraphNode(nodeId, { input_contract_id: value })}
              options={contractOptions}
              value={stringValue(node.input_contract_id)}
            />
            <ObjectSelectField
              formatOption={formatContract}
              label="输出契约"
              onChange={(value) => updateTaskGraphNode(nodeId, { output_contract_id: value })}
              options={contractOptions}
              value={stringValue(node.output_contract_id)}
            />
            <TaskSystemField label="阶段">
              <input onChange={(event) => updateTaskGraphNode(nodeId, { phase_id: event.target.value })} value={stringValue(node.phase_id)} />
            </TaskSystemField>
            <TaskSystemField label="顺序">
              <input min={0} onChange={(event) => updateTaskGraphNode(nodeId, { sequence_index: Number(event.target.value || 0) })} type="number" value={Number(node.sequence_index ?? selected.sequence_index ?? 0)} />
            </TaskSystemField>
            <TaskSystemSelectField
              formatOption={taskSystemOptionLabel}
              label="执行模式"
              onChange={(value) => updateTaskGraphNode(nodeId, { execution_mode: value })}
              options={["sync", "async", "parallel", "background", "barrier", "manual_gate"]}
              value={stringValue(node.execution_mode, "sync")}
            />
            <TaskSystemSelectField
              formatOption={taskSystemOptionLabel}
              label="等待策略"
              onChange={(value) => updateTaskGraphNode(nodeId, { wait_policy: value })}
              options={["wait_all_upstream_completed", "wait_any_upstream_completed", "wait_required_contracts", "wait_handoff_ack", "manual_release"]}
              value={stringValue(node.wait_policy, "wait_all_upstream_completed")}
            />
            <TaskSystemSelectField
              formatOption={taskSystemOptionLabel}
              label="汇合策略"
              onChange={(value) => updateTaskGraphNode(nodeId, { join_policy: value })}
              options={["all_success", "any_success", "allow_partial_with_issues", "coordinator_decides", "fail_on_any_error"]}
              value={stringValue(node.join_policy, "all_success")}
            />
            <TaskSystemField label="产物目标" wide>
              <input onChange={(event) => updateTaskGraphNode(nodeId, { artifact_target: event.target.value })} value={stringValue(node.artifact_target)} />
            </TaskSystemField>
            <label className="boundary-check">
              <input checked={booleanValue(node.main_chain, true)} onChange={(event) => updateTaskGraphNode(nodeId, { main_chain: event.target.checked })} type="checkbox" />
              进入主链
            </label>
            <label className="boundary-check">
              <input checked={booleanValue(node.blocks_phase_exit, true)} onChange={(event) => updateTaskGraphNode(nodeId, { blocks_phase_exit: event.target.checked })} type="checkbox" />
              阻塞阶段出口
            </label>
          </div>
        </section>
      </>
    );
  };

  const renderGraphUnitEditor = (selected: ComposableUnitSpec) => {
    const ref = asRecord(selected.ref);
    const blockId = blockIdFromUnit(selected);
    const selectedBlock = blockId ? blocks.find((item) => item.block_id === blockId) ?? null : null;
    const linkedGraphId = stringValue(ref.graph_id ?? selectedBlock?.linked_graph_id);
    const linkedGraph = linkedGraphId ? taskGraphs?.find((item) => item.graph_id === linkedGraphId) ?? null : null;
    return (
      <>
        <section className="task-graph-composer-inspector-card">
          <header>
            <Network aria-hidden="true" size={15} />
            <strong>图节点</strong>
            <span>GraphUnit</span>
          </header>
          <div className="task-graph-composer-selection-title">
            <span>{selected.source_kind || "timeline_block"}</span>
            <strong>{selectedBlock?.title || selected.title || selected.unit_id}</strong>
            <small>{selected.unit_id}</small>
          </div>
          <div className="task-graph-composer-kv">
            <p><span>图块</span><strong>{selectedBlock?.block_id || blockId || "未映射"}</strong></p>
            <p><span>子任务图</span><strong>{linkedGraphId || "未绑定"}</strong></p>
            <p><span>版本</span><strong>{selectedBlock?.version_ref || stringValue(ref.version_ref, "未锚定")}</strong></p>
            <p><span>契约</span><strong>{selectedBlock?.handoff_contract_id || "未声明"}</strong></p>
          </div>
          <div className="task-graph-note">
            <strong>图节点不展开子图内部</strong>
            <span>这里配置父任务图看到的子图入口、版本和交接边界；子图内部节点需要进入子图工作台后编辑。</span>
          </div>
        </section>

        {selectedBlock ? (
          <section className="task-graph-composer-inspector-card">
            <header>
              <Layers3 aria-hidden="true" size={15} />
              <strong>图节点边界</strong>
            </header>
            <div className="boundary-form task-graph-composer-inspector-form">
              <TaskSystemField label="中文名" wide>
                <input onChange={(event) => updateTimelineBlock(selectedBlock.block_id, { title: event.target.value })} value={selectedBlock.title} />
              </TaskSystemField>
              <TaskSystemSelectField label="图块类型" onChange={(value) => updateTimelineBlock(selectedBlock.block_id, { block_type: value })} options={["phase_graph", "design_graph", "creation_graph", "closing_graph", "review_graph"]} value={selectedBlock.block_type} />
              <TaskSystemField label="所属阶段">
                <input onChange={(event) => updateTimelineBlock(selectedBlock.block_id, { phase_id: event.target.value })} value={selectedBlock.phase_id} />
              </TaskSystemField>
              <ObjectSelectField
                emptyLabel="不绑定子任务图"
                formatOption={formatGraph}
                label="子任务图"
                onChange={(value) => updateTimelineBlock(selectedBlock.block_id, { linked_graph_id: value })}
                options={graphOptions}
                value={selectedBlock.linked_graph_id ?? ""}
                wide
              />
              <ObjectSelectField
                formatOption={formatContract}
                label="交接契约"
                onChange={(value) => updateTimelineBlock(selectedBlock.block_id, { handoff_contract_id: value })}
                options={contractOptions}
                value={selectedBlock.handoff_contract_id ?? ""}
                wide
              />
              <TaskSystemSelectField label="可见性" onChange={(value) => updateTimelineBlock(selectedBlock.block_id, { visibility_policy: value })} options={["committed_only", "summary_and_refs", "manual_release", "isolated_until_commit"]} value={selectedBlock.visibility_policy ?? "committed_only"} />
              <TaskSystemField label="版本锚点">
                <input onChange={(event) => updateTimelineBlock(selectedBlock.block_id, { version_ref: event.target.value })} placeholder="v1 / draft / published" value={selectedBlock.version_ref ?? ""} />
              </TaskSystemField>
              <TaskSystemSelectField label="断开策略" onChange={(value) => updateTimelineBlock(selectedBlock.block_id, { detach_policy: value })} options={["preserve_version_anchor", "fork_as_independent_graph", "require_rehandoff_packet"]} value={selectedBlock.detach_policy ?? "preserve_version_anchor"} />
            </div>
          </section>
        ) : null}

        <section className="task-graph-composer-inspector-card">
          <header>
            <ExternalLink aria-hidden="true" size={15} />
            <strong>子图工作台</strong>
          </header>
          <div className="task-graph-topology-actions task-graph-topology-actions--stacked">
            <button disabled={!linkedGraphId || !linkedGraph || !onOpenGraph} onClick={() => linkedGraphId && onOpenGraph?.(linkedGraphId)} type="button">
              <ExternalLink aria-hidden="true" size={14} />
              <span>{linkedGraph ? "进入子图工作台" : linkedGraphId ? "子图未在当前任务域找到" : "未绑定子任务图"}</span>
            </button>
          </div>
        </section>
      </>
    );
  };

  const renderUnitEditor = (selected: ComposableUnitSpec) => {
    if (selected.unit_type === "graph") return renderGraphUnitEditor(selected);
    const mappedNode = nodeForUnit(selected);
    if (mappedNode) return renderNodeUnitEditor(selected, mappedNode);
    return (
      <section className="task-graph-composer-inspector-card">
        <header>
          <GitBranch aria-hidden="true" size={15} />
          <strong>Unit</strong>
          <span>{selected.source_kind || "standard view"}</span>
        </header>
        <div className="task-graph-composer-selection-title">
          <span>{selected.unit_type}</span>
          <strong>{selected.title || selected.unit_id}</strong>
          <small>{selected.unit_id}</small>
        </div>
        <div className="task-graph-note">
          <strong>该 Unit 未映射到可编辑节点</strong>
          <span>资源、工具或覆盖层 Unit 的完整表单将在 Interface / Port 覆盖层阶段开放；当前先通过原始节点或图节点编辑入口配置。</span>
        </div>
      </section>
    );
  };

  const renderOverlayPortEdgeEditor = (edge: UnitPortEdgeSpec) => {
    const sourcePorts = portOptionsForUnit(edge.source_unit_id, interfaces, "output");
    const targetPorts = portOptionsForUnit(edge.target_unit_id, interfaces, "input");
    return (
      <section className="task-graph-composer-inspector-card">
        <header>
          <Cable aria-hidden="true" size={15} />
          <strong>显式端口边</strong>
          <span>覆盖层</span>
        </header>
        <div className="task-graph-composer-selection-title">
          <span>{edge.edge_type || "handoff"}</span>
          <strong>{edge.edge_id || "未命名端口边"}</strong>
          <small>{edgeSourceSummary(edge)}</small>
        </div>
        <div className="boundary-form task-graph-composer-inspector-form">
          <TaskSystemField label="边 ID" wide>
            <input onChange={(event) => updateOverlayPortEdge(edge, { edge_id: event.target.value })} value={edge.edge_id} />
          </TaskSystemField>
          <ObjectSelectField formatOption={formatUnit} label="源单元" onChange={(value) => updateOverlayPortEdge(edge, { source_unit_id: value, source_port_id: portOptionsForUnit(value, interfaces, "output")[0] ?? "output.default" })} options={unitOptions} value={edge.source_unit_id} />
          <TaskSystemSelectField label="源端口" onChange={(value) => updateOverlayPortEdge(edge, { source_port_id: value })} options={sourcePorts} value={edge.source_port_id} />
          <ObjectSelectField formatOption={formatUnit} label="目标单元" onChange={(value) => updateOverlayPortEdge(edge, { target_unit_id: value, target_port_id: portOptionsForUnit(value, interfaces, "input")[0] ?? "input.default" })} options={unitOptions} value={edge.target_unit_id} />
          <TaskSystemSelectField label="目标端口" onChange={(value) => updateOverlayPortEdge(edge, { target_port_id: value })} options={targetPorts} value={edge.target_port_id} />
          <ObjectSelectField formatOption={formatContract} label="载荷契约" onChange={(value) => updateOverlayPortEdge(edge, { payload_contract_id: value })} options={contractOptions} value={edge.payload_contract_id ?? ""} wide />
          <TaskSystemSelectField label="边类型" onChange={(value) => updateOverlayPortEdge(edge, { edge_type: value })} options={["handoff", "memory_handoff", "artifact_context", "temporal_dependency"]} value={edge.edge_type ?? "handoff"} />
          <TaskSystemSelectField label="触发时机" onChange={(value) => updateOverlayPortEdgeTemporal(edge, { trigger_timing: value })} options={["after_source_success", "after_source_commit", "manual_release", "phase_gate_passed"]} value={stringValue(asRecord(edge.temporal_semantics).trigger_timing, "after_source_success")} />
          <TaskSystemSelectField label="可见时机" onChange={(value) => updateOverlayPortEdgeTemporal(edge, { visibility_timing: value })} options={["after_commit", "after_ack", "same_clock", "next_clock"]} value={stringValue(asRecord(edge.temporal_semantics).visibility_timing, "after_commit")} />
          <TaskSystemSelectField label="确认时机" onChange={(value) => updateOverlayPortEdgeTemporal(edge, { acknowledgement_timing: value })} options={["explicit_ack", "implicit_ack", "manual_ack", "none"]} value={stringValue(asRecord(edge.temporal_semantics).acknowledgement_timing, "explicit_ack")} />
          <TaskSystemSelectField label="传播策略" onChange={(value) => updateOverlayPortEdgeTemporal(edge, { propagation_timing: value })} options={["buffer_until_commit", "immediate_refs_only", "manual_release", "block_until_ack"]} value={stringValue(asRecord(edge.temporal_semantics).propagation_timing, "buffer_until_commit")} />
          <button className="task-graph-inline-danger" onClick={() => removeOverlayEdge(edge.edge_id)} type="button">
            <Trash2 aria-hidden="true" size={14} />
            移除覆盖边
          </button>
        </div>
      </section>
    );
  };

  const renderLegacyPortEdgeEditor = (edge: UnitPortEdgeSpec, originalEdge: Record<string, unknown>) => {
    const edgeId = graphEdgeId(originalEdge);
    const edgeMetadata = asRecord(originalEdge.metadata);
    const temporal = asRecord(edgeMetadata.temporal_semantics);
    const handoff = asRecord(originalEdge.working_memory_handoff_policy);
    const sourcePorts = portOptionsForUnit(edge.source_unit_id, interfaces, "output");
    const targetPorts = portOptionsForUnit(edge.target_unit_id, interfaces, "input");
    return (
      <>
        <section className="task-graph-composer-inspector-card">
          <header>
            <Cable aria-hidden="true" size={15} />
            <strong>交接边</strong>
            <span>edges[]</span>
          </header>
          <div className="task-graph-composer-selection-title">
            <span>{stringValue(originalEdge.edge_type ?? originalEdge.mode, "structured_handoff")}</span>
            <strong>{edgeId}</strong>
            <small>{edgeSourceSummary(edge)}</small>
          </div>
          <div className="task-graph-note">
            <strong>边是交接协议，不是执行端</strong>
            <span>这里配置上游节点输出如何成为下游节点合法输入；任务动作仍由节点激活产生。</span>
          </div>
        </section>

        <section className="task-graph-composer-inspector-card">
          <header>
            <Cable aria-hidden="true" size={15} />
            <strong>交接配置</strong>
          </header>
          <div className="boundary-form task-graph-composer-inspector-form">
            <ObjectSelectField formatOption={formatUnit} label="源节点" onChange={(value) => updateLegacyEdgeEndpoint(originalEdge, edgeId, { source_unit_id: value })} options={nodeUnitOptions} value={edge.source_unit_id} />
            <TaskSystemSelectField label="源端口" onChange={(value) => updateLegacyEdgeEndpoint(originalEdge, edgeId, { source_port_id: value })} options={sourcePorts} value={edge.source_port_id} />
            <ObjectSelectField formatOption={formatUnit} label="目标节点" onChange={(value) => updateLegacyEdgeEndpoint(originalEdge, edgeId, { target_unit_id: value })} options={nodeUnitOptions} value={edge.target_unit_id} />
            <TaskSystemSelectField label="目标端口" onChange={(value) => updateLegacyEdgeEndpoint(originalEdge, edgeId, { target_port_id: value })} options={targetPorts} value={edge.target_port_id} />
            <ObjectSelectField formatOption={formatContract} label="载荷契约" onChange={(value) => updateTaskGraphEdge(edgeId, { payload_contract_id: value, contract_id: value })} options={contractOptions} value={stringValue(originalEdge.payload_contract_id ?? originalEdge.contract_id ?? edge.payload_contract_id)} wide />
            <TaskSystemSelectField
              formatOption={taskSystemOptionLabel}
              label="边类型"
              onChange={(value) => updateTaskGraphEdge(edgeId, { edge_type: value, mode: value })}
              options={["structured_handoff", "control_flow", "memory_read", "memory_write_candidate", "memory_commit", "artifact_context", "revision_request", "temporal_dependency"]}
              value={stringValue(originalEdge.edge_type ?? originalEdge.mode, "structured_handoff")}
            />
            <TaskSystemSelectField
              formatOption={taskSystemOptionLabel}
              label="等待策略"
              onChange={(value) => updateTaskGraphEdge(edgeId, { wait_policy: value })}
              options={["wait_all_upstream_completed", "wait_any_upstream_completed", "wait_required_contracts", "wait_handoff_ack", "fire_and_continue"]}
              value={stringValue(originalEdge.wait_policy, "wait_all_upstream_completed")}
            />
            <TaskSystemSelectField
              formatOption={taskSystemOptionLabel}
              label="确认策略"
              onChange={(value) => updateTaskGraphEdge(edgeId, { ack_policy: value })}
              options={["explicit_ack", "implicit_ack", "manual_ack", "none"]}
              value={stringValue(originalEdge.ack_policy, "explicit_ack")}
            />
            <TaskSystemSelectField
              formatOption={taskSystemOptionLabel}
              label="失败传播"
              onChange={(value) => updateTaskGraphEdge(edgeId, { failure_propagation_policy: value })}
              options={["fail_downstream", "isolate_failure", "allow_partial"]}
              value={stringValue(originalEdge.failure_propagation_policy, "fail_downstream")}
            />
            <TaskSystemSelectField
              formatOption={taskSystemOptionLabel}
              label="结果投递"
              onChange={(value) => updateTaskGraphEdge(edgeId, { result_delivery_policy: value })}
              options={["contract_payload_and_refs", "summary_and_refs", "notification_only"]}
              value={stringValue(originalEdge.result_delivery_policy, "contract_payload_and_refs")}
            />
            <label className="boundary-check">
              <input checked={booleanValue(originalEdge.ack_required, true)} onChange={(event) => updateTaskGraphEdge(edgeId, { ack_required: event.target.checked })} type="checkbox" />
              需要目标节点确认接收
            </label>
            <TaskSystemField label="模型可见标签" wide>
              <input onChange={(event) => patchEdgeMetadata(edgeId, originalEdge, { model_visible_label: event.target.value })} value={stringValue(edgeMetadata.model_visible_label)} />
            </TaskSystemField>
            <TaskSystemField label="Prompt 使用说明" wide>
              <textarea onChange={(event) => patchEdgeMetadata(edgeId, originalEdge, { usage_instruction: event.target.value })} value={stringValue(edgeMetadata.usage_instruction)} />
            </TaskSystemField>
          </div>
        </section>

        <section className="task-graph-composer-inspector-card">
          <header>
            <Layers3 aria-hidden="true" size={15} />
            <strong>边时序与记忆交接</strong>
          </header>
          <div className="boundary-form task-graph-composer-inspector-form">
            <TaskSystemSelectField label="触发时机" onChange={(value) => patchEdgeTemporal(edgeId, originalEdge, { trigger_timing: value })} options={["after_source_success", "after_required_contracts", "manual_release", "phase_entry", "phase_exit"]} value={stringValue(temporal.trigger_timing ?? edgeMetadata.trigger_timing, "after_source_success")} />
            <TaskSystemSelectField label="可见时机" onChange={(value) => patchEdgeTemporal(edgeId, originalEdge, { visibility_timing: value })} options={["same_clock", "next_clock", "after_commit", "next_iteration", "manual_release"]} value={stringValue(temporal.visibility_timing ?? edgeMetadata.visibility_timing, "after_commit")} />
            <TaskSystemSelectField label="确认时机" onChange={(value) => patchEdgeTemporal(edgeId, originalEdge, { acknowledgement_timing: value })} options={["no_ack", "explicit_ack", "ack_before_downstream", "ack_before_phase_exit"]} value={stringValue(temporal.acknowledgement_timing ?? edgeMetadata.acknowledgement_timing, "explicit_ack")} />
            <TaskSystemSelectField label="传播策略" onChange={(value) => patchEdgeTemporal(edgeId, originalEdge, { propagation_timing: value })} options={["immediate", "buffer_until_commit", "summary_only", "refs_only", "blocked_on_failure"]} value={stringValue(temporal.propagation_timing ?? edgeMetadata.propagation_timing, "buffer_until_commit")} />
            <TaskSystemField label="携带记忆 Kind">
              <textarea onChange={(event) => patchEdgeMemoryHandoff(edgeId, originalEdge, { carry_kinds: splitList(event.target.value) })} value={listText(handoff.carry_kinds)} />
            </TaskSystemField>
            <TaskSystemField label="携带记忆 Scope">
              <textarea onChange={(event) => patchEdgeMemoryHandoff(edgeId, originalEdge, { carry_scopes: splitList(event.target.value) })} value={listText(handoff.carry_scopes)} />
            </TaskSystemField>
            <label className="boundary-check">
              <input checked={handoff.summary_only === true} onChange={(event) => patchEdgeMemoryHandoff(edgeId, originalEdge, { summary_only: event.target.checked })} type="checkbox" />
              只传摘要或引用，不复制正文
            </label>
          </div>
        </section>

        <section className="task-graph-composer-inspector-card">
          <header>
            <Plus aria-hidden="true" size={15} />
            <strong>端口化</strong>
          </header>
          <div className="task-graph-note">
            <strong>升级为显式端口边</strong>
            <span>显式边会写入 metadata.composable_graph.port_edges，可以连接图节点、普通节点和资源 Unit 的端口。</span>
          </div>
          <button
            className="task-graph-composer-subtle-action"
            onClick={() => addOverlayPortEdge({
              ...edge,
              payload_contract_id: stringValue(originalEdge.payload_contract_id ?? originalEdge.contract_id ?? edge.payload_contract_id),
              edge_type: stringValue(originalEdge.edge_type ?? originalEdge.mode ?? edge.edge_type, "handoff"),
              handoff: {
                ...asRecord(edge.handoff),
                wait_policy: originalEdge.wait_policy,
                ack_policy: originalEdge.ack_policy,
                ack_required: originalEdge.ack_required,
                failure_propagation_policy: originalEdge.failure_propagation_policy,
                result_delivery_policy: originalEdge.result_delivery_policy,
              },
              metadata: {
                ...asRecord(edge.metadata),
                upgraded_from_edge_id: edgeId,
              },
            })}
            type="button"
          >
            升级为显式端口边
          </button>
        </section>
      </>
    );
  };

  const renderPortEdgeEditor = (edge: UnitPortEdgeSpec) => {
    if (isOverlayEdge(edge, overlayEdgeIds)) return renderOverlayPortEdgeEditor(edge);
    const originalEdge = edgeForPortEdge(edge);
    if (originalEdge) return renderLegacyPortEdgeEditor(edge, originalEdge);
    return (
      <section className="task-graph-composer-inspector-card">
        <header>
          <Cable aria-hidden="true" size={15} />
          <strong>交接边</strong>
          <span>未映射</span>
        </header>
        <div className="task-graph-composer-selection-title">
          <span>{edge.edge_type || "handoff"}</span>
          <strong>{edge.edge_id}</strong>
          <small>{edgeSourceSummary(edge)}</small>
        </div>
        <div className="task-graph-note">
          <strong>未找到可写回的原始边</strong>
          <span>可以升级为显式端口边，让配置写入可组合覆盖层。</span>
        </div>
        <button className="task-graph-composer-subtle-action" onClick={() => addOverlayPortEdge(edge)} type="button">升级为显式端口边</button>
      </section>
    );
  };

  const renderBlockEditor = (selected: TaskGraphTimelineBlock) => (
    <section className="task-graph-composer-inspector-card">
      <header>
        <Layers3 aria-hidden="true" size={15} />
        <strong>图节点来源</strong>
        <span>timeline_blocks</span>
      </header>
      <div className="task-graph-composer-selection-title">
        <span>{selected.block_type}</span>
        <strong>{selected.title || selected.block_id}</strong>
        <small>{selected.block_id}</small>
      </div>
      <div className="boundary-form task-graph-composer-inspector-form">
        <TaskSystemField label="中文名" wide>
          <input onChange={(event) => updateTimelineBlock(selected.block_id, { title: event.target.value })} value={selected.title} />
        </TaskSystemField>
        <TaskSystemSelectField label="图块类型" onChange={(value) => updateTimelineBlock(selected.block_id, { block_type: value })} options={["phase_graph", "design_graph", "creation_graph", "closing_graph", "review_graph"]} value={selected.block_type} />
        <TaskSystemField label="所属阶段">
          <input onChange={(event) => updateTimelineBlock(selected.block_id, { phase_id: event.target.value })} value={selected.phase_id} />
        </TaskSystemField>
        <ObjectSelectField emptyLabel="不绑定子任务图" formatOption={formatGraph} label="子任务图" onChange={(value) => updateTimelineBlock(selected.block_id, { linked_graph_id: value })} options={graphOptions} value={selected.linked_graph_id ?? ""} wide />
        <ObjectSelectField formatOption={formatContract} label="交接契约" onChange={(value) => updateTimelineBlock(selected.block_id, { handoff_contract_id: value })} options={contractOptions} value={selected.handoff_contract_id ?? ""} wide />
        <TaskSystemSelectField label="可见性" onChange={(value) => updateTimelineBlock(selected.block_id, { visibility_policy: value })} options={["committed_only", "summary_and_refs", "manual_release", "isolated_until_commit"]} value={selected.visibility_policy ?? "committed_only"} />
        <TaskSystemField label="版本锚点">
          <input onChange={(event) => updateTimelineBlock(selected.block_id, { version_ref: event.target.value })} placeholder="v1 / draft / published" value={selected.version_ref ?? ""} />
        </TaskSystemField>
        <TaskSystemSelectField label="断开策略" onChange={(value) => updateTimelineBlock(selected.block_id, { detach_policy: value })} options={["preserve_version_anchor", "fork_as_independent_graph", "require_rehandoff_packet"]} value={selected.detach_policy ?? "preserve_version_anchor"} />
        <button className="task-graph-inline-danger" onClick={() => removeTimelineBlock(selected.block_id)} type="button">
          <Trash2 aria-hidden="true" size={14} />
          移除图节点来源
        </button>
      </div>
    </section>
  );

  const renderNestedRuntime = (plan: NestedRuntimePlanSpec) => (
    <section className="task-graph-composer-inspector-card">
      <header>
        <Network aria-hidden="true" size={15} />
        <strong>嵌套运行</strong>
        <span>标准视图</span>
      </header>
      <div className="task-graph-composer-selection-title">
        <span>{plan.visibility_policy || "committed_only"}</span>
        <strong>{plan.linked_graph_id || plan.plan_id}</strong>
        <small>{plan.plan_id}</small>
      </div>
      <div className="task-graph-composer-kv">
        <p><span>Unit</span><strong>{plan.unit_id}</strong></p>
        <p><span>版本</span><strong>{plan.version_ref || "未锚定"}</strong></p>
        <p><span>交接契约</span><strong>{plan.handoff_contract_id || "未声明"}</strong></p>
        <p><span>隔离</span><strong>{plan.isolation_policy || "isolated_per_nested_run"}</strong></p>
      </div>
      <div className="task-graph-note">
        <strong>运行边界来自图节点配置</strong>
        <span>请通过图节点的 linked_graph_id、version_ref、handoff_contract_id 和可见性策略维护这份运行计划。</span>
      </div>
    </section>
  );

  const renderIssue = () => selectedSubject.kind === "issue" ? (
    <section className="task-graph-composer-inspector-card">
      <header>
        <FileWarning aria-hidden="true" size={15} />
        <strong>诊断问题</strong>
        <span>{selectedSubject.issue.severity}</span>
      </header>
      <div className="task-graph-composer-selection-title">
        <span>{selectedSubject.issue.scope}{selectedSubject.issue.target_id ? `:${selectedSubject.issue.target_id}` : ""}</span>
        <strong>{selectedSubject.issue.title}</strong>
        <small>{selectedSubject.issue.source}</small>
      </div>
      <div className="task-graph-note task-graph-note--danger">
        <strong>处理说明</strong>
        <span>{selectedSubject.issue.detail}</span>
      </div>
    </section>
  ) : null;

  return (
    <aside className="task-graph-composer-inspector" aria-label="对象编辑台">
      {selectedSubject.kind === "graph" ? renderGraphEditor() : null}
      {unit ? renderUnitEditor(unit) : null}
      {portEdge ? renderPortEdgeEditor(portEdge) : null}
      {block ? renderBlockEditor(block) : null}
      {nestedPlan ? renderNestedRuntime(nestedPlan) : null}
      {renderIssue()}
      {selectedSubject.kind === "interface" || selectedSubject.kind === "port" ? (
        <section className="task-graph-composer-inspector-card">
          <header>
            <Cable aria-hidden="true" size={15} />
            <strong>接口端口</strong>
            <span>只读预览</span>
          </header>
          <div className="task-graph-note">
            <strong>接口覆盖层将在下一阶段开放</strong>
            <span>当前先通过节点契约、图节点交接契约和显式端口边维护接口语义。</span>
          </div>
        </section>
      ) : null}
      <section className="task-graph-composer-inspector-card">
        <header>
          <Cable aria-hidden="true" size={15} />
          <strong>覆盖层状态</strong>
          <span>metadata.composable_graph</span>
        </header>
        <div className="task-graph-composer-kv">
          <p><span>Unit 覆盖</span><strong>{overlay.units.length}</strong></p>
          <p><span>Interface 覆盖</span><strong>{overlay.interfaces.length}</strong></p>
          <p><span>PortEdge 覆盖</span><strong>{overlay.port_edges.length}</strong></p>
          <p><span>Nested 覆盖</span><strong>{overlay.nested_runtime.length}</strong></p>
        </div>
        {overlay.units.length || overlay.interfaces.length || overlay.nested_runtime.length ? (
          <button
            className="task-graph-composer-subtle-action"
            onClick={() => updateTaskGraphMetadata(taskGraphComposableOverlayMetadataPatch(metadata, overlay))}
            type="button"
          >
            重新规范化覆盖层
          </button>
        ) : null}
      </section>
    </aside>
  );
}
