import type { TaskGraphEdgeRecord } from "@/lib/api";

export type TaskGraphEdgeRelationRegistration = {
  relation: string;
  displayName: string;
  description: string;
  visual: {
    tone: "handoff" | "approval" | "loop" | "memory" | "artifact" | "external";
    animated?: boolean;
  };
  backendMapping: {
    edgeTypes: string[];
  };
  defaultEdgePatch: Partial<TaskGraphEdgeRecord>;
};

export const taskGraphEdgeRelationRegistrations: TaskGraphEdgeRelationRegistration[] = [
  {
    relation: "structured_handoff",
    displayName: "结构交接",
    description: "上游完成后把结构化 payload 交给下游节点。",
    visual: { tone: "handoff" },
    backendMapping: { edgeTypes: ["structured_handoff", "brief_handoff", "plan_handoff", "writing_handoff"] },
    defaultEdgePatch: {
      edge_type: "structured_handoff",
      ack_required: true,
      wait_policy: "source_completed",
      result_delivery_policy: "payload_ref",
    },
  },
  {
    relation: "quality_gate",
    displayName: "质量门",
    description: "下游需要给出裁决，允许、返修或阻断后续节点。",
    visual: { tone: "approval" },
    backendMapping: { edgeTypes: ["quality_gate", "review_handoff", "human_decision", "approved_handoff"] },
    defaultEdgePatch: {
      edge_type: "quality_gate",
      ack_required: true,
      wait_policy: "source_completed",
      failure_propagation_policy: "block_downstream",
    },
  },
  {
    relation: "revision_loop",
    displayName: "返修回路",
    description: "人工或审核节点要求返修时回到明确连接的上游节点。",
    visual: { tone: "loop", animated: true },
    backendMapping: { edgeTypes: ["revision_loop"] },
    defaultEdgePatch: {
      edge_type: "revision_loop",
      ack_required: true,
      wait_policy: "decision_required",
      metadata: {
        loop: true,
      },
    },
  },
  {
    relation: "memory_context",
    displayName: "记忆上下文",
    description: "资源节点向 agent 提供显式上下文引用，不授予隐式控制权。",
    visual: { tone: "memory" },
    backendMapping: { edgeTypes: ["memory_context"] },
    defaultEdgePatch: {
      edge_type: "memory_context",
      ack_required: false,
      context_filter_policy: {
        scope: "explicit_refs_only",
      },
    },
  },
  {
    relation: "artifact_write",
    displayName: "产物写入",
    description: "节点把输出写入显式产物或文件角色。",
    visual: { tone: "artifact" },
    backendMapping: { edgeTypes: ["artifact_write", "publish_handoff"] },
    defaultEdgePatch: {
      edge_type: "artifact_write",
      ack_required: true,
      result_delivery_policy: "artifact_ref",
    },
  },
];

export function taskGraphEdgeRelationForEdge(edge: Pick<TaskGraphEdgeRecord, "edge_type" | "metadata">) {
  const tone = String(edge.metadata?.visual_tone ?? "").trim();
  const byTone = tone ? taskGraphEdgeRelationRegistrations.find((item) => item.visual.tone === tone || item.relation === tone) : null;
  if (byTone) return byTone;
  return taskGraphEdgeRelationRegistrations.find((item) => item.backendMapping.edgeTypes.includes(String(edge.edge_type || "")))
    ?? taskGraphEdgeRelationRegistrations[0];
}

export function createEdgeFromRelation(
  registration: TaskGraphEdgeRelationRegistration,
  sourceNodeId: string,
  targetNodeId: string,
  index: number,
): TaskGraphEdgeRecord {
  return {
    edge_id: `edge.${registration.relation}_${String(index + 1).padStart(2, "0")}`,
    source_node_id: sourceNodeId,
    target_node_id: targetNodeId,
    edge_type: registration.defaultEdgePatch.edge_type || registration.relation,
    ...registration.defaultEdgePatch,
    metadata: {
      ...(registration.defaultEdgePatch.metadata ?? {}),
      visual_tone: registration.visual.tone,
    },
  };
}
