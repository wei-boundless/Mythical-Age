import type { TaskGraphRecord } from "@/lib/api";

import type { TaskGraphDraftV2 } from "./taskGraphDraftV2";
import { asRecord, stringListOf } from "./taskGraphDraftV2";
import type { LegacyTaskGraphStack } from "./taskGraphTypes";

export type BuildTaskGraphUpsertPayloadInput = {
  taskGraphDraft: TaskGraphDraftV2;
  legacyDrafts: LegacyTaskGraphStack;
  domain_id: string;
  task_family: string;
  task_id: string;
  publish_state: "draft" | "published";
};

function compactRecord(payload: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(payload).filter(([, value]) => value !== undefined),
  );
}

function participantAgentIdsFromNodes(nodes: Array<Record<string, unknown>>, coordinatorAgentId: string): string[] {
  return stringListOf(
    nodes
      .map((node) => String(node.agent_id ?? ""))
      .filter((agentId) => agentId && agentId !== coordinatorAgentId),
  );
}

function subtaskRefsFromNodes(nodes: Array<Record<string, unknown>>): string[] {
  return stringListOf(nodes.map((node) => String(node.task_id ?? ""))).filter((taskRef) => taskRef.startsWith("task."));
}

export function buildTaskGraphUpsertPayload({
  taskGraphDraft,
  legacyDrafts,
  domain_id,
  task_family,
  task_id,
  publish_state,
}: BuildTaskGraphUpsertPayloadInput): TaskGraphRecord {
  const { coordinationDraft, protocolDraft, topologyDraft } = legacyDrafts;
  const metadata = asRecord(taskGraphDraft.metadata);
  const coordinatorAgentId = String(taskGraphDraft.runtime_policy.coordinator_agent_id ?? "agent:0").trim() || "agent:0";
  const explicitParticipants = stringListOf(taskGraphDraft.runtime_policy.participant_agent_ids);
  const participant_agent_ids = explicitParticipants.length
    ? explicitParticipants
    : participantAgentIdsFromNodes(taskGraphDraft.nodes, coordinatorAgentId);
  const workingMemoryProfileId = String(taskGraphDraft.working_memory_policy_profile_id ?? "").trim();
  const runtime_policy = compactRecord({
    ...asRecord(taskGraphDraft.runtime_policy),
    coordinator_agent_id: coordinatorAgentId,
    participant_agent_ids,
    agent_group_id: String(taskGraphDraft.runtime_policy.agent_group_id ?? ""),
    coordination_mode: String(taskGraphDraft.runtime_policy.coordination_mode ?? "review_merge"),
    working_memory_profile_id: workingMemoryProfileId || undefined,
  });
  const context_policy = compactRecord({
    ...asRecord(taskGraphDraft.context_policy),
    shared_context_policy: String(taskGraphDraft.context_policy.shared_context_policy ?? "explicit_refs_only"),
    memory_sharing_policy: String(taskGraphDraft.context_policy.memory_sharing_policy ?? "isolated_by_default"),
  });

  return {
    graph_id: taskGraphDraft.graph_id,
    title: taskGraphDraft.title,
    domain_id,
    task_family,
    graph_kind: taskGraphDraft.graph_kind,
    entry_node_id: taskGraphDraft.entry_node_id,
    output_node_id: taskGraphDraft.output_node_id,
    nodes: taskGraphDraft.nodes,
    edges: taskGraphDraft.edges,
    graph_contract_id: taskGraphDraft.graph_contract_id,
    default_protocol_id: taskGraphDraft.default_protocol_id || protocolDraft.protocol_id,
    working_memory_policy_profile_id: workingMemoryProfileId,
    working_memory_policy: asRecord(taskGraphDraft.working_memory_policy),
    runtime_policy,
    context_policy,
    publish_state,
    enabled: publish_state === "published",
    metadata: compactRecord({
      ...metadata,
      protocol_id: taskGraphDraft.default_protocol_id || protocolDraft.protocol_id,
      topology_template_id: String(metadata.topology_template_id ?? coordinationDraft.topology_template_id ?? topologyDraft.template_id ?? ""),
      task_family,
      domain_id,
      task_id,
      handoff_policy: String(taskGraphDraft.context_policy.handoff_policy ?? coordinationDraft.handoff_policy ?? ""),
      conflict_resolution_policy: String(metadata.conflict_resolution_policy ?? coordinationDraft.conflict_resolution_policy ?? ""),
      output_merge_policy: String(metadata.output_merge_policy ?? coordinationDraft.output_merge_policy ?? ""),
      business_communication_modes: stringListOf(
        metadata.business_communication_modes ?? coordinationDraft.communication_modes ?? [],
      ),
      subtask_refs: Array.from(new Set([...(stringListOf(metadata.subtask_refs)), ...subtaskRefsFromNodes(taskGraphDraft.nodes)])),
    }),
  };
}
