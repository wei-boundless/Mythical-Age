import type { TaskGraphEdgeRecord, TaskGraphNodeRecord } from "@/lib/api";

import type { GraphEditorLayout } from "../templates/graphTemplateTypes";
import { normalizeGraphEditorLayout } from "../templates/graphTemplateTypes";

export function graphCanvasMetadataPatch(
  layout: GraphEditorLayout,
  nodes: TaskGraphNodeRecord[],
  edges: TaskGraphEdgeRecord[],
) {
  return {
    editor_layout: normalizeGraphEditorLayout(layout, {
      graph_id: "graph.canvas",
      title: "Graph Canvas",
      graph_kind: "multi_agent",
      entry_node_id: nodes[0]?.node_id || "",
      output_node_id: nodes[nodes.length - 1]?.node_id || "",
      nodes,
      edges,
      publish_state: "draft",
      enabled: false,
    }),
    graph_world_contract: {
      coordinate_authority: "layout_only",
      relation_authority: "explicit_nodes_edges_and_contracts",
      coordinate_never_implies_control: true,
    },
  };
}
