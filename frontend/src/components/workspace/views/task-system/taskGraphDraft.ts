import type { TaskCommunicationProtocol, TaskGraphRecord, TopologyTemplate } from "@/lib/api";

import { inferTaskGraphBoundaryNodes } from "./taskGraphDraftV2";
import type { LegacyTaskGraphStack, TaskGraphDraft, TaskGraphEdge, TaskGraphKind, TaskGraphNode } from "./taskGraphTypes";

function inferTaskGraphKind(nodes: TaskGraphNode[]) {
  if (nodes.some((node) => String(node.node_type ?? "") === "input") && nodes.some((node) => String(node.node_type ?? "") === "output")) {
    return "single_agent" as TaskGraphKind;
  }
  return nodes.length <= 1 ? "single_agent" : "multi_agent";
}

export function buildTaskGraphDraft({
  coordinationDraft,
  topologyDraft,
  protocolDraft,
}: LegacyTaskGraphStack): TaskGraphDraft {
  const nodes = (topologyDraft.nodes ?? []) as TaskGraphNode[];
  const edges = (topologyDraft.edges ?? []) as TaskGraphEdge[];
  const boundaries = inferTaskGraphBoundaryNodes(nodes, edges);

  return {
    graph_id: coordinationDraft.graph_id || topologyDraft.template_id || "graph.draft",
    task_id: String(coordinationDraft.metadata?.task_id ?? ""),
    domain_id: coordinationDraft.domain_id || String(topologyDraft.metadata?.domain_id ?? ""),
    graph_kind: inferTaskGraphKind(nodes),
    title: coordinationDraft.title || topologyDraft.title || "任务图",
    coordination_task_id: coordinationDraft.coordination_task_id || coordinationDraft.graph_id || topologyDraft.template_id || "graph.draft",
    topology_template_id: topologyDraft.template_id,
    protocol_id: protocolDraft.protocol_id,
    entry_node_id: boundaries.entry_node_id,
    output_node_id: boundaries.output_node_id,
    agent_group_id: coordinationDraft.agent_group_id || "",
    coordination_mode: coordinationDraft.coordination_mode,
    nodes,
    edges,
    communication_modes: coordinationDraft.communication_modes ?? [],
    publish_state: coordinationDraft.enabled && topologyDraft.enabled && protocolDraft.enabled ? "published" : "draft",
    metadata: {
      ...(coordinationDraft.metadata ?? {}),
      topology_title: topologyDraft.title,
      protocol_title: protocolDraft.title,
    },
  };
}

export function taskGraphRecordToDraft(
  graph: TaskGraphRecord,
  topologyDraft: LegacyTaskGraphStack["topologyDraft"],
  protocolDraft: LegacyTaskGraphStack["protocolDraft"],
): TaskGraphDraft {
  const nodes = (graph.nodes ?? []) as TaskGraphNode[];
  const edges = (graph.edges ?? []) as TaskGraphEdge[];
  const boundaries = inferTaskGraphBoundaryNodes(nodes, edges, {
    fallback_entry_node_id: graph.entry_node_id,
    fallback_output_node_id: graph.output_node_id,
  });

  return {
    graph_id: graph.graph_id,
    task_id: String(graph.metadata?.task_id ?? ""),
    domain_id: graph.domain_id || String(topologyDraft.metadata?.domain_id ?? ""),
    graph_kind: graph.graph_kind ?? inferTaskGraphKind(nodes),
    title: graph.title || topologyDraft.title || "任务图",
    coordination_task_id: graph.graph_id,
    topology_template_id: String(graph.metadata?.topology_template_id ?? topologyDraft.template_id ?? ""),
    protocol_id: graph.default_protocol_id || String(graph.metadata?.protocol_id ?? protocolDraft.protocol_id ?? ""),
    entry_node_id: boundaries.entry_node_id,
    output_node_id: boundaries.output_node_id,
    agent_group_id: String(graph.runtime_policy?.agent_group_id ?? graph.metadata?.agent_group_id ?? ""),
    coordination_mode: String(graph.runtime_policy?.coordination_mode ?? graph.metadata?.coordination_mode ?? "review_merge"),
    nodes,
    edges,
    communication_modes: Array.isArray(graph.metadata?.business_communication_modes)
      ? (graph.metadata?.business_communication_modes as string[])
      : [],
    publish_state: graph.publish_state === "archived" ? "draft" : (graph.publish_state ?? (graph.enabled ? "published" : "draft")),
    metadata: {
      ...(graph.metadata ?? {}),
      topology_title: topologyDraft.title,
      protocol_title: protocolDraft.title,
    },
  };
}

export function taskGraphToLegacyDrafts(
  graphDraft: TaskGraphDraft,
  legacyDrafts: LegacyTaskGraphStack,
): LegacyTaskGraphStack {
  const nextCoordinationDraft: LegacyTaskGraphStack["coordinationDraft"] = {
    ...legacyDrafts.coordinationDraft,
    coordination_task_id: graphDraft.coordination_task_id,
    title: graphDraft.title,
    topology_template_id: graphDraft.topology_template_id,
    protocol_id: graphDraft.protocol_id,
    domain_id: graphDraft.domain_id,
    agent_group_id: graphDraft.agent_group_id,
    coordination_mode: graphDraft.coordination_mode,
    graph_nodes: graphDraft.nodes,
    graph_edges: graphDraft.edges,
    communication_modes: graphDraft.communication_modes,
    enabled: graphDraft.publish_state === "published",
    metadata: {
      ...(legacyDrafts.coordinationDraft.metadata ?? {}),
      ...(graphDraft.metadata ?? {}),
    },
  } as LegacyTaskGraphStack["coordinationDraft"] & { protocol_id?: string };

  const nextTopologyDraft: LegacyTaskGraphStack["topologyDraft"] = {
    ...legacyDrafts.topologyDraft,
    template_id: graphDraft.topology_template_id,
    title: String(graphDraft.metadata.topology_title ?? legacyDrafts.topologyDraft.title ?? graphDraft.title),
    nodes: graphDraft.nodes,
    edges: graphDraft.edges,
    nodes_text: JSON.stringify(graphDraft.nodes, null, 2),
    edges_text: JSON.stringify(graphDraft.edges, null, 2),
    enabled: graphDraft.publish_state === "published",
    metadata: {
      ...(legacyDrafts.topologyDraft.metadata ?? {}),
      domain_id: graphDraft.domain_id,
    },
  };

  const nextProtocolDraft: LegacyTaskGraphStack["protocolDraft"] = {
    ...legacyDrafts.protocolDraft,
    protocol_id: graphDraft.protocol_id,
    title: String(graphDraft.metadata.protocol_title ?? legacyDrafts.protocolDraft.title ?? `${graphDraft.title} 协议`),
    enabled: graphDraft.publish_state === "published",
    metadata: {
      ...(legacyDrafts.protocolDraft.metadata ?? {}),
      domain_id: graphDraft.domain_id,
    },
  };

  return {
    coordinationDraft: nextCoordinationDraft,
    topologyDraft: nextTopologyDraft,
    protocolDraft: nextProtocolDraft,
  };
}

export function syncTaskGraphPublishState(
  graphDraft: TaskGraphDraft,
  enabled: boolean,
): TaskGraphDraft {
  return {
    ...graphDraft,
    publish_state: enabled ? "published" : "draft",
  };
}

export function syncTaskGraphNodes(
  graphDraft: TaskGraphDraft,
  nodes: TaskGraphNode[],
  edges: TaskGraphEdge[],
): TaskGraphDraft {
  const boundaries = inferTaskGraphBoundaryNodes(nodes, edges, {
    fallback_entry_node_id: graphDraft.entry_node_id,
    fallback_output_node_id: graphDraft.output_node_id,
  });
  return {
    ...graphDraft,
    nodes,
    edges,
    graph_kind: inferTaskGraphKind(nodes),
    entry_node_id: boundaries.entry_node_id,
    output_node_id: boundaries.output_node_id,
  };
}
