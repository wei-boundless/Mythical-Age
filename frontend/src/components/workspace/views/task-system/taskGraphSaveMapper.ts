import type { TaskGraphEdgeRecord, TaskGraphNodeRecord, TaskGraphRecord } from "@/lib/api";

import type { TaskGraphDraftV2 } from "./taskGraphDraftV2";
import { asRecord, stringListOf } from "./taskGraphDraftV2";

export type TaskGraphPublishCommitIntent = "save_draft" | "publish" | "mark_run_bound" | "archive";

export type TaskGraphPublishCommit = {
  editor_publish_state: TaskGraphDraftV2["publish_state"];
  backend_publish_state: "draft" | "published";
  enabled: boolean;
  metadata_patch: Record<string, unknown>;
};

export type BuildTaskGraphUpsertPayloadInput = {
  taskGraphDraft: TaskGraphDraftV2;
  domain_id: string;
  task_id: string;
  publish_state: "draft" | "published";
};

function compactRecord(payload: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(payload).filter(([, value]) => {
      if (value === undefined || value === null || value === "") return false;
      if (Array.isArray(value) && value.length === 0) return false;
      if (typeof value === "object" && !Array.isArray(value) && Object.keys(value as Record<string, unknown>).length === 0) return false;
      return true;
    }),
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

function communicationModesFromEdges(edges: Array<Record<string, unknown>>): string[] {
  return stringListOf(edges.map((edge) => String(edge.mode ?? edge.edge_type ?? "")));
}

export function resolveTaskGraphPublishCommit(intent: TaskGraphPublishCommitIntent): TaskGraphPublishCommit {
  if (intent === "publish") {
    return {
      editor_publish_state: "published",
      backend_publish_state: "published",
      enabled: true,
      metadata_patch: { editor_publish_state: "published" },
    };
  }
  if (intent === "mark_run_bound") {
    return {
      editor_publish_state: "run_bound",
      backend_publish_state: "published",
      enabled: true,
      metadata_patch: { editor_publish_state: "run_bound" },
    };
  }
  if (intent === "archive") {
    return {
      editor_publish_state: "archived",
      backend_publish_state: "draft",
      enabled: false,
      metadata_patch: { editor_publish_state: "archived" },
    };
  }
  return {
    editor_publish_state: "saved",
    backend_publish_state: "draft",
    enabled: false,
    metadata_patch: { editor_publish_state: "saved" },
  };
}

export function buildTaskGraphUpsertPayload({
  taskGraphDraft,
  domain_id,
  task_id,
  publish_state,
}: BuildTaskGraphUpsertPayloadInput): TaskGraphRecord {
  const metadata = asRecord(taskGraphDraft.metadata);
  const taskEnvironmentId = String(
    metadata.task_environment_id
    ?? metadata.environment_id
    ?? taskGraphDraft.runtime_policy.task_environment_id
    ?? taskGraphDraft.runtime_policy.environment_id
    ?? taskGraphDraft.context_policy.task_environment_id
    ?? taskGraphDraft.context_policy.environment_id
    ?? "",
  ).trim();
  const coordinatorAgentId = String(taskGraphDraft.runtime_policy.coordinator_agent_id ?? "agent:0").trim() || "agent:0";
  const explicitParticipants = stringListOf(taskGraphDraft.runtime_policy.participant_agent_ids);
  const draftNodes = taskGraphDraft.nodes.map(normalizeNodeContractBindings);
  const draftEdges = taskGraphDraft.edges.map(normalizeEdgeContractBindings);
  const participant_agent_ids = explicitParticipants.length
    ? explicitParticipants
    : participantAgentIdsFromNodes(draftNodes, coordinatorAgentId);
  const workingMemoryProfileId = String(taskGraphDraft.working_memory_policy_profile_id ?? "").trim();
  const runtime_policy = compactRecord({
    ...asRecord(taskGraphDraft.runtime_policy),
    task_environment_id: taskEnvironmentId || undefined,
    environment_id: taskEnvironmentId || undefined,
    coordinator_agent_id: coordinatorAgentId,
    participant_agent_ids,
    agent_group_id: String(taskGraphDraft.runtime_policy.agent_group_id ?? ""),
    coordination_mode: String(taskGraphDraft.runtime_policy.coordination_mode ?? "review_merge"),
    human_gate_mode: String(taskGraphDraft.runtime_policy.human_gate_mode ?? "manual_required"),
    working_memory_profile_id: workingMemoryProfileId || undefined,
  });
  const continuationPolicy = {
    ...asRecord(metadata.continuation_policy),
    human_gate_mode: String(taskGraphDraft.runtime_policy.human_gate_mode ?? "manual_required"),
  };
  const context_policy = compactRecord({
    ...asRecord(taskGraphDraft.context_policy),
    task_environment_id: taskEnvironmentId || undefined,
    environment_id: taskEnvironmentId || undefined,
    shared_context_policy: String(taskGraphDraft.context_policy.shared_context_policy ?? "explicit_refs_only"),
    memory_sharing_policy: String(taskGraphDraft.context_policy.memory_sharing_policy ?? "isolated_by_default"),
  });
  const graphContractBindings = normalizeGraphContractBindings(taskGraphDraft);
  const nodes = draftNodes;
  const edges = draftEdges;

  return {
    graph_id: taskGraphDraft.graph_id,
    title: taskGraphDraft.title,
    domain_id,
    graph_kind: taskGraphDraft.graph_kind,
    entry_node_id: taskGraphDraft.entry_node_id,
    output_node_id: taskGraphDraft.output_node_id,
    nodes,
    edges,
    graph_contract_id: taskGraphDraft.graph_contract_id,
    contract_bindings: graphContractBindings,
    default_protocol_id: taskGraphDraft.default_protocol_id,
    working_memory_policy_profile_id: workingMemoryProfileId,
    working_memory_policy: asRecord(taskGraphDraft.working_memory_policy),
    runtime_policy,
    context_policy,
    publish_state,
    enabled: publish_state === "published",
    metadata: compactRecord({
      ...metadata,
      protocol_id: taskGraphDraft.default_protocol_id || String(metadata.protocol_id ?? ""),
      topology_template_id: String(metadata.topology_template_id ?? ""),
      task_environment_id: taskEnvironmentId || undefined,
      environment_id: taskEnvironmentId || undefined,
      domain_id,
      ...(task_id ? { task_id } : {}),
      handoff_policy: String(taskGraphDraft.context_policy.handoff_policy ?? metadata.handoff_policy ?? ""),
      conflict_resolution_policy: String(metadata.conflict_resolution_policy ?? ""),
      output_merge_policy: String(metadata.output_merge_policy ?? ""),
      continuation_policy: continuationPolicy,
      business_communication_modes: stringListOf(
        metadata.business_communication_modes ?? communicationModesFromEdges(edges),
      ),
      subtask_refs: Array.from(new Set([...(stringListOf(metadata.subtask_refs)), ...subtaskRefsFromNodes(nodes)])),
    }),
  };
}

function mergeSection(bindings: Record<string, unknown>, section: string, patch: Record<string, unknown>): Record<string, unknown> {
  const current = asRecord(bindings[section]);
  const next = compactRecord({ ...patch, ...current });
  return compactRecord({ ...bindings, [section]: next });
}

function normalizeGraphContractBindings(taskGraphDraft: TaskGraphDraftV2): Record<string, unknown> {
  let bindings = asRecord(taskGraphDraft.contract_bindings);
  const currentRuntime = asRecord(bindings.runtime);
  bindings = mergeSection(bindings, "schema", {
    graph_contract_id: taskGraphDraft.graph_contract_id || undefined,
  });
  bindings = mergeSection(bindings, "runtime", {
    length_budget: asRecord(currentRuntime.length_budget),
    runtime_policy: asRecord(taskGraphDraft.runtime_policy),
    working_memory_policy_profile_id: taskGraphDraft.working_memory_policy_profile_id || undefined,
  });
  bindings = mergeSection(bindings, "memory", {
    working_memory_policy: asRecord(taskGraphDraft.working_memory_policy),
  });
  bindings = mergeSection(bindings, "handoff", {
    context_policy: asRecord(taskGraphDraft.context_policy),
  });
  return bindings;
}

function normalizeNodeContractBindings(node: TaskGraphNodeRecord): TaskGraphNodeRecord {
  let bindings = asRecord(node.contract_bindings);
  const currentRuntime = asRecord(bindings.runtime);
  bindings = mergeSection(bindings, "schema", {
    input_contract_id: String(node.input_contract_id ?? "").trim() || undefined,
    output_contract_id: String(node.output_contract_id ?? "").trim() || undefined,
  });
  bindings = mergeSection(bindings, "execution", {
    node_contract_id: String(node.node_contract_id ?? node.contract_id ?? "").trim() || undefined,
    executor_policy: asRecord(node.executor_policy),
  });
  bindings = mergeSection(bindings, "artifact", {
    artifact_policy: asRecord(node.artifact_policy),
    stream_policy: asRecord(node.stream_policy),
  });
  bindings = mergeSection(bindings, "memory", {
    memory_read_policy: asRecord(node.memory_read_policy),
    dynamic_memory_read_policy: asRecord(node.dynamic_memory_read_policy),
    memory_writeback_policy: asRecord(node.memory_writeback_policy),
  });
  bindings = mergeSection(bindings, "acceptance", {
    review_gate_policy: asRecord(node.review_gate_policy),
    human_gate_policy: asRecord(node.human_gate_policy),
  });
  bindings = mergeSection(bindings, "runtime", {
    length_budget: asRecord(currentRuntime.length_budget),
    execution_mode: String(node.execution_mode ?? "").trim() || undefined,
    wait_policy: String(node.wait_policy ?? "").trim() || undefined,
    join_policy: String(node.join_policy ?? "").trim() || undefined,
    background_policy: asRecord(node.background_policy),
    notification_policy: asRecord(node.notification_policy),
    failure_policy: asRecord(node.failure_policy),
  });
  return { ...node, contract_bindings: bindings };
}

function normalizeEdgeContractBindings(edge: TaskGraphEdgeRecord): TaskGraphEdgeRecord {
  let bindings = asRecord(edge.contract_bindings);
  bindings = mergeSection(bindings, "schema", {
    payload_contract_id: String(edge.payload_contract_id ?? edge.contract_id ?? "").trim() || undefined,
  });
  bindings = mergeSection(bindings, "handoff", {
    ack_policy: String(edge.ack_policy ?? "").trim() || undefined,
    timeout_policy: String(edge.timeout_policy ?? "").trim() || undefined,
    wait_policy: String(edge.wait_policy ?? "").trim() || undefined,
    ack_required: edge.ack_required,
    failure_propagation_policy: String(edge.failure_propagation_policy ?? "").trim() || undefined,
    result_delivery_policy: String(edge.result_delivery_policy ?? "").trim() || undefined,
    context_filter_policy: asRecord(edge.context_filter_policy),
    failure_policy: asRecord(edge.failure_policy),
  });
  bindings = mergeSection(bindings, "memory", {
    working_memory_handoff_policy: asRecord(edge.working_memory_handoff_policy),
  });
  bindings = mergeSection(bindings, "artifact", {
    artifact_ref_policy: asRecord(edge.artifact_ref_policy),
  });
  bindings = mergeSection(bindings, "temporal", asRecord(asRecord(edge.metadata).temporal_semantics));
  return { ...edge, contract_bindings: bindings };
}
