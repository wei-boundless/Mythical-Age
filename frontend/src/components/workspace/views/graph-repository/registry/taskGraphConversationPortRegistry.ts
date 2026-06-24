import type { GraphConversationPortBinding } from "../templates/graphTemplateTypes";

export type ConversationPortRegistration = {
  portKind: GraphConversationPortBinding["mode"];
  displayName: string;
  resolveBinding: (context: {
    graphId: string;
    instanceId?: string;
    graphRunId?: string;
    selectedNodeId?: string;
    selectedEdgeId?: string;
  }) => GraphConversationPortBinding | null;
};

export const conversationPortRegistrations: ConversationPortRegistration[] = [
  {
    portKind: "graph_assistant",
    displayName: "图助手",
    resolveBinding: ({ graphId }) => ({
      mode: "graph_assistant",
      graph_id: graphId,
      scope: { workspace_view: "graph_task" },
    }),
  },
  {
    portKind: "node_config",
    displayName: "节点配置端口",
    resolveBinding: ({ graphId, selectedNodeId }) => selectedNodeId ? ({
      mode: "node_config",
      graph_id: graphId,
      node_id: selectedNodeId,
      scope: { workspace_view: "graph_task", node_id: selectedNodeId },
    }) : null,
  },
  {
    portKind: "node_session",
    displayName: "节点运行会话",
    resolveBinding: ({ graphId, instanceId, graphRunId, selectedNodeId }) => instanceId && selectedNodeId ? ({
      mode: "node_session",
      graph_id: graphId,
      graph_task_instance_id: instanceId,
      graph_run_id: graphRunId,
      node_id: selectedNodeId,
      scope: { workspace_view: "graph_task", project_id: instanceId, node_id: selectedNodeId },
    }) : null,
  },
  {
    portKind: "edge_contract",
    displayName: "边契约端口",
    resolveBinding: ({ graphId, selectedEdgeId }) => selectedEdgeId ? ({
      mode: "edge_contract",
      graph_id: graphId,
      edge_id: selectedEdgeId,
      scope: { workspace_view: "graph_task" },
    }) : null,
  },
];

export function resolveGraphConversationPortBinding(context: Parameters<ConversationPortRegistration["resolveBinding"]>[0]) {
  if (context.instanceId && context.selectedNodeId) {
    return conversationPortRegistrations.find((item) => item.portKind === "node_session")?.resolveBinding(context) ?? null;
  }
  if (context.selectedNodeId) {
    return conversationPortRegistrations.find((item) => item.portKind === "node_config")?.resolveBinding(context) ?? null;
  }
  if (context.selectedEdgeId) {
    return conversationPortRegistrations.find((item) => item.portKind === "edge_contract")?.resolveBinding(context) ?? null;
  }
  return conversationPortRegistrations.find((item) => item.portKind === "graph_assistant")?.resolveBinding(context) ?? null;
}
