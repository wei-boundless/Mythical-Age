import type { TaskGraphEdgeRecord, TaskGraphNodeRecord, TaskGraphRecord } from "@/lib/api";

import type { LegacyTaskGraphStack } from "./taskGraphTypes";

export type TaskGraphPublishStateV2 = "draft" | "saved" | "preflight_passed" | "published" | "run_bound" | "archived";

export type TaskGraphRuntimePolicyDraftV2 = Record<string, unknown> & {
  coordinator_agent_id: string;
  participant_agent_ids: string[];
  agent_group_id: string;
  coordination_mode: string;
};

export type TaskGraphContextPolicyDraftV2 = Record<string, unknown> & {
  shared_context_policy: string;
  memory_sharing_policy: string;
};

export type TaskGraphWorkingMemoryPolicyDraftV2 = Record<string, unknown>;

export type TaskGraphMetadataDraftV2 = Record<string, unknown>;

export type TaskGraphEditorUiState = {
  selected_node_id: string;
  selected_edge_id: string;
  active_layer: string;
};

export type TaskGraphDraftV2 = {
  graph_id: string;
  title: string;
  domain_id: string;
  task_family: string;
  task_id: string;
  graph_kind: "single_agent" | "multi_agent" | "coordination";
  entry_node_id: string;
  output_node_id: string;
  nodes: TaskGraphNodeRecord[];
  edges: TaskGraphEdgeRecord[];
  graph_contract_id: string;
  default_protocol_id: string;
  runtime_policy: TaskGraphRuntimePolicyDraftV2;
  context_policy: TaskGraphContextPolicyDraftV2;
  working_memory_policy_profile_id: string;
  working_memory_policy: TaskGraphWorkingMemoryPolicyDraftV2;
  publish_state: TaskGraphPublishStateV2;
  metadata: TaskGraphMetadataDraftV2;
  ui_state: TaskGraphEditorUiState;
};

export type TaskGraphBoundaryNodes = {
  entry_node_id: string;
  output_node_id: string;
};

type BoundaryNodeLike = Record<string, unknown> & {
  node_id?: string;
  id?: string;
  node_type?: string;
};

type BoundaryEdgeLike = Record<string, unknown> & {
  from?: string;
  to?: string;
  source_node_id?: string;
  target_node_id?: string;
  source?: string;
  target?: string;
};

export function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

export function stringListOf(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return Array.from(new Set(value.map((item) => String(item ?? "").trim()).filter(Boolean)));
}

export function graphNodeId(node: BoundaryNodeLike, index = 0): string {
  return String(node.node_id ?? node.id ?? `node_${index + 1}`).trim();
}

export function graphEdgeSource(edge: BoundaryEdgeLike): string {
  return String(edge.source_node_id ?? edge.from ?? edge.source ?? "").trim();
}

export function graphEdgeTarget(edge: BoundaryEdgeLike): string {
  return String(edge.target_node_id ?? edge.to ?? edge.target ?? "").trim();
}

export function inferTaskGraphBoundaryNodes(
  nodes: BoundaryNodeLike[],
  edges: BoundaryEdgeLike[],
  options?: {
    fallback_entry_node_id?: string;
    fallback_output_node_id?: string;
  },
): TaskGraphBoundaryNodes {
  const normalizedNodes = nodes
    .map((node, index) => ({ ...node, node_id: graphNodeId(node, index) }))
    .filter((node) => node.node_id);
  const nodeIds = new Set(normalizedNodes.map((node) => String(node.node_id)));
  const normalizedEdges = edges
    .map((edge) => ({
      source: graphEdgeSource(edge),
      target: graphEdgeTarget(edge),
    }))
    .filter((edge) => edge.source && edge.target && nodeIds.has(edge.source) && nodeIds.has(edge.target));
  const sourceIds = new Set(normalizedEdges.map((edge) => edge.source));
  const targetIds = new Set(normalizedEdges.map((edge) => edge.target));
  const explicitInputId = normalizedNodes.find((node) => String(node.node_type ?? "") === "input")?.node_id ?? "";
  const explicitOutputId = normalizedNodes.find((node) => String(node.node_type ?? "") === "output")?.node_id ?? "";
  const fallbackEntryId = String(options?.fallback_entry_node_id ?? "").trim();
  const fallbackOutputId = String(options?.fallback_output_node_id ?? "").trim();
  const validFallbackEntryId = fallbackEntryId && nodeIds.has(fallbackEntryId) ? fallbackEntryId : "";
  const validFallbackOutputId = fallbackOutputId && nodeIds.has(fallbackOutputId) ? fallbackOutputId : "";
  const inferredEntryId = normalizedNodes.find((node) => !targetIds.has(String(node.node_id)))?.node_id ?? normalizedNodes[0]?.node_id ?? "";
  const inferredOutputId = normalizedNodes.find((node) => !sourceIds.has(String(node.node_id)))?.node_id ?? normalizedNodes.slice(-1)[0]?.node_id ?? "";

  return {
    entry_node_id: String(explicitInputId || validFallbackEntryId || inferredEntryId || ""),
    output_node_id: String(explicitOutputId || validFallbackOutputId || inferredOutputId || ""),
  };
}

export function normalizeTaskGraphPublishState(state: unknown, enabled = false): TaskGraphPublishStateV2 {
  const value = String(state ?? "").trim();
  if (value === "published" || value === "run_bound" || value === "preflight_passed" || value === "saved" || value === "archived") {
    return value;
  }
  return enabled ? "published" : "draft";
}

export function isTaskGraphPublishedState(state: unknown): boolean {
  const normalized = normalizeTaskGraphPublishState(state);
  return normalized === "published" || normalized === "run_bound";
}

export function taskGraphPublishStateLabel(state: unknown): string {
  const normalized = normalizeTaskGraphPublishState(state);
  if (normalized === "saved") return "已保存";
  if (normalized === "preflight_passed") return "预检通过";
  if (normalized === "published") return "已发布";
  if (normalized === "run_bound") return "已绑定运行";
  if (normalized === "archived") return "已归档";
  return "草稿";
}

export function taskGraphRecordToDraftV2(graph: TaskGraphRecord): TaskGraphDraftV2 {
  const metadata = asRecord(graph.metadata);
  const {
    entry_node_id: _legacyEntryNodeId,
    output_node_id: _legacyOutputNodeId,
    graph_contract_id: _legacyGraphContractId,
    runtime_policy: _legacyRuntimePolicy,
    context_policy: _legacyContextPolicy,
    working_memory_policy: _legacyWorkingMemoryPolicy,
    working_memory_policy_profile_id: _legacyWorkingMemoryProfileId,
    ...metadataRemainder
  } = metadata;
  const runtimeMetadata = asRecord(metadata.runtime_policy);
  const contextMetadata = asRecord(metadata.context_policy);
  const workingMemoryMetadata = asRecord(metadata.working_memory_policy);
  const runtimePolicy = {
    ...runtimeMetadata,
    ...asRecord(graph.runtime_policy),
  };
  const contextPolicy = {
    ...contextMetadata,
    ...asRecord(graph.context_policy),
  };
  const workingMemoryPolicy = {
    ...workingMemoryMetadata,
    ...asRecord(graph.working_memory_policy),
  };
  const boundaries = inferTaskGraphBoundaryNodes(graph.nodes ?? [], graph.edges ?? [], {
    fallback_entry_node_id: graph.entry_node_id,
    fallback_output_node_id: graph.output_node_id,
  });

  return {
    graph_id: graph.graph_id,
    title: graph.title || graph.graph_id || "任务图",
    domain_id: graph.domain_id || String(metadata.domain_id ?? ""),
    task_family: graph.task_family || String(metadata.task_family ?? ""),
    task_id: String(metadata.task_id ?? ""),
    graph_kind: graph.graph_kind ?? "multi_agent",
    entry_node_id: boundaries.entry_node_id,
    output_node_id: boundaries.output_node_id,
    nodes: graph.nodes ?? [],
    edges: graph.edges ?? [],
    graph_contract_id: graph.graph_contract_id ?? "",
    default_protocol_id: graph.default_protocol_id ?? String(metadata.protocol_id ?? ""),
    runtime_policy: {
      ...runtimePolicy,
      coordinator_agent_id: String(runtimePolicy.coordinator_agent_id ?? metadata.coordinator_agent_id ?? "agent:0") || "agent:0",
      participant_agent_ids: stringListOf(runtimePolicy.participant_agent_ids ?? metadata.participant_agent_ids),
      agent_group_id: String(runtimePolicy.agent_group_id ?? metadata.agent_group_id ?? ""),
      coordination_mode: String(runtimePolicy.coordination_mode ?? metadata.coordination_mode ?? "review_merge"),
    },
    context_policy: {
      ...contextPolicy,
      shared_context_policy: String(contextPolicy.shared_context_policy ?? "explicit_refs_only"),
      memory_sharing_policy: String(contextPolicy.memory_sharing_policy ?? "isolated_by_default"),
    },
    working_memory_policy_profile_id: String(
      graph.working_memory_policy_profile_id
      ?? runtimePolicy.working_memory_profile_id
      ?? metadata.working_memory_policy_profile_id
      ?? "",
    ),
    working_memory_policy: workingMemoryPolicy,
    publish_state: normalizeTaskGraphPublishState(metadata.editor_publish_state ?? graph.publish_state, graph.enabled),
    metadata: metadataRemainder,
    ui_state: {
      selected_node_id: boundaries.entry_node_id,
      selected_edge_id: "",
      active_layer: "blueprint",
    },
  };
}

export function legacyStackToTaskGraphDraftV2({
  coordinationDraft,
  topologyDraft,
  protocolDraft,
}: LegacyTaskGraphStack): TaskGraphDraftV2 {
  const metadata = asRecord(coordinationDraft.metadata);
  const runtimeMetadata = asRecord(metadata.runtime_policy);
  const contextMetadata = asRecord(metadata.context_policy);
  const nodes = (topologyDraft.nodes?.length ? topologyDraft.nodes : coordinationDraft.graph_nodes ?? []) as TaskGraphNodeRecord[];
  const edges = (topologyDraft.edges?.length ? topologyDraft.edges : coordinationDraft.graph_edges ?? []) as TaskGraphEdgeRecord[];
  const boundaries = inferTaskGraphBoundaryNodes(nodes, edges, {
    fallback_entry_node_id: String(metadata.entry_node_id ?? ""),
    fallback_output_node_id: String(metadata.output_node_id ?? ""),
  });
  const {
    entry_node_id: _legacyEntryNodeId,
    output_node_id: _legacyOutputNodeId,
    graph_contract_id: _legacyGraphContractId,
    runtime_policy: _legacyRuntimePolicy,
    context_policy: _legacyContextPolicy,
    working_memory_policy: _legacyWorkingMemoryPolicy,
    working_memory_policy_profile_id: _legacyWorkingMemoryProfileId,
    ...metadataRemainder
  } = metadata;

  return {
    graph_id: coordinationDraft.graph_id || coordinationDraft.coordination_task_id || topologyDraft.template_id || "graph.draft",
    title: coordinationDraft.title || topologyDraft.title || "任务图",
    domain_id: coordinationDraft.domain_id || String(topologyDraft.metadata?.domain_id ?? metadata.domain_id ?? ""),
    task_family: coordinationDraft.task_family || String(metadata.task_family ?? topologyDraft.metadata?.task_family ?? ""),
    task_id: String(metadata.task_id ?? topologyDraft.metadata?.task_id ?? ""),
    graph_kind: coordinationDraft.graph_kind ?? (nodes.length <= 1 ? "single_agent" : "multi_agent"),
    entry_node_id: boundaries.entry_node_id,
    output_node_id: boundaries.output_node_id,
    nodes,
    edges,
    graph_contract_id: String(metadata.graph_contract_id ?? ""),
    default_protocol_id: coordinationDraft.protocol_id || protocolDraft.protocol_id || String(metadata.protocol_id ?? ""),
    runtime_policy: {
      ...runtimeMetadata,
      coordinator_agent_id: String(runtimeMetadata.coordinator_agent_id ?? coordinationDraft.coordinator_agent_id ?? "agent:0") || "agent:0",
      participant_agent_ids: stringListOf(runtimeMetadata.participant_agent_ids ?? coordinationDraft.participant_agent_ids),
      agent_group_id: String(runtimeMetadata.agent_group_id ?? coordinationDraft.agent_group_id ?? ""),
      coordination_mode: String(runtimeMetadata.coordination_mode ?? coordinationDraft.coordination_mode ?? "review_merge"),
    },
    context_policy: {
      ...contextMetadata,
      shared_context_policy: String(contextMetadata.shared_context_policy ?? coordinationDraft.shared_context_policy ?? "explicit_refs_only"),
      memory_sharing_policy: String(contextMetadata.memory_sharing_policy ?? coordinationDraft.memory_sharing_policy ?? "isolated_by_default"),
      handoff_policy: String(contextMetadata.handoff_policy ?? coordinationDraft.handoff_policy ?? "filtered_handoff"),
    },
    working_memory_policy_profile_id: String(metadata.working_memory_policy_profile_id ?? runtimeMetadata.working_memory_profile_id ?? ""),
    working_memory_policy: asRecord(metadata.working_memory_policy),
    publish_state: normalizeTaskGraphPublishState(metadata.editor_publish_state, coordinationDraft.enabled && topologyDraft.enabled && protocolDraft.enabled),
    metadata: {
      ...metadataRemainder,
      topology_template_id: coordinationDraft.topology_template_id || topologyDraft.template_id,
      protocol_id: protocolDraft.protocol_id,
    },
    ui_state: {
      selected_node_id: boundaries.entry_node_id,
      selected_edge_id: "",
      active_layer: "blueprint",
    },
  };
}
