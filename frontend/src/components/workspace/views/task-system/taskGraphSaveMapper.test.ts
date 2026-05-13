import { describe, expect, it } from "vitest";

import type { TaskGraphRecord } from "@/lib/api";

import { inferTaskGraphBoundaryNodes, legacyStackToTaskGraphDraftV2, taskGraphRecordToDraftV2 } from "./taskGraphDraftV2";
import { buildTaskGraphUpsertPayload } from "./taskGraphSaveMapper";
import type { LegacyTaskGraphStack } from "./taskGraphTypes";

describe("TaskGraphDraftV2 mapping", () => {
  it("infers graph boundaries from topology semantics instead of array order", () => {
    const boundaries = inferTaskGraphBoundaryNodes(
      [
        { node_id: "middle", node_type: "agent" },
        { node_id: "out", node_type: "output" },
        { node_id: "in", node_type: "input" },
      ],
      [
        { source_node_id: "in", target_node_id: "middle" },
        { source_node_id: "middle", target_node_id: "out" },
      ],
    );

    expect(boundaries).toEqual({
      entry_node_id: "in",
      output_node_id: "out",
    });
  });

  it("builds a TaskGraph upsert payload with first-class runtime, context, and working-memory policies", () => {
    const legacyDrafts = {
      coordinationDraft: {
        graph_id: "graph.test.story",
        coordination_task_id: "graph.test.story",
        title: "Story graph",
        graph_kind: "multi_agent",
        domain_id: "domain.story",
        task_family: "story",
        coordinator_agent_id: "agent:coordinator",
        agent_group_id: "group.story",
        coordination_mode: "review_merge",
        topology_template_id: "topology.story",
        protocol_id: "protocol.story",
        shared_context_policy: "explicit_refs_only",
        memory_sharing_policy: "isolated_by_default",
        handoff_policy: "filtered_handoff",
        conflict_resolution_policy: "coordinator_review",
        output_merge_policy: "coordinator_final_merge",
        stop_conditions: [],
        subtask_refs: [],
        graph_nodes: [
          { node_id: "review", node_type: "agent", title: "Review", agent_id: "agent:reviewer", task_id: "task.review" },
          { node_id: "draft", node_type: "agent", title: "Draft", agent_id: "agent:writer", task_id: "task.draft" },
        ],
        graph_edges: [
          { edge_id: "edge.1", source_node_id: "draft", target_node_id: "review", mode: "structured_handoff" },
        ],
        communication_modes: ["structured_handoff"],
        enabled: false,
        participant_agent_ids: [],
        metadata: {
          runtime_policy: {
            default_execution_mode: "parallel",
            max_parallel_nodes: 3,
          },
          working_memory_policy_profile_id: "wmprofile.story",
          working_memory_policy: {
            default_scope: "graph_scope",
            default_visibility: "handoff_only",
          },
          graph_contract_id: "contract.story.graph",
          artifact_policy: {
            enabled: true,
          },
        },
        stop_conditions_text: "",
      },
      topologyDraft: {
        template_id: "topology.story",
        title: "Story topology",
        nodes: [],
        edges: [],
        handoff_rules: [],
        join_policy: "explicit_join",
        failure_policy: "fail_closed",
        terminal_policy: "coordinator_terminal",
        enabled: false,
        metadata: {},
        nodes_text: "[]",
        edges_text: "[]",
        handoff_rules_text: "[]",
      },
      protocolDraft: {
        protocol_id: "protocol.story",
        title: "Story protocol",
        message_types: ["message/send"],
        payload_contracts: [],
        signal_rules: [],
        handoff_rules: [],
        ack_policy: "explicit_ack",
        timeout_policy: "fail_closed",
        error_signal_policy: "raise_to_coordinator",
        enabled: false,
        metadata: {},
        message_types_text: "",
        payload_contracts_text: "",
        signal_rules_text: "",
        handoff_rules_text: "",
      },
    } satisfies LegacyTaskGraphStack;

    const payload = buildTaskGraphUpsertPayload({
      taskGraphDraft: legacyStackToTaskGraphDraftV2(legacyDrafts),
      legacyDrafts,
      domain_id: "domain.story",
      task_family: "story",
      task_id: "task.story",
      publish_state: "published",
    });

    expect(payload.runtime_policy?.coordinator_agent_id).toBe("agent:coordinator");
    expect(payload.runtime_policy?.participant_agent_ids).toEqual(["agent:reviewer", "agent:writer"]);
    expect(payload.runtime_policy?.default_execution_mode).toBe("parallel");
    expect(payload.runtime_policy?.working_memory_profile_id).toBe("wmprofile.story");
    expect(payload.context_policy?.shared_context_policy).toBe("explicit_refs_only");
    expect(payload.working_memory_policy_profile_id).toBe("wmprofile.story");
    expect(payload.working_memory_policy?.default_scope).toBe("graph_scope");
    expect(payload.graph_contract_id).toBe("contract.story.graph");
    expect(payload.entry_node_id).toBe("draft");
    expect(payload.output_node_id).toBe("review");
    expect(payload.metadata?.runtime_policy).toBeUndefined();
    expect(payload.metadata?.working_memory_policy).toBeUndefined();
    expect(payload.metadata?.graph_contract_id).toBeUndefined();
    expect(payload.metadata?.artifact_policy).toEqual({ enabled: true });
    expect(payload.metadata?.subtask_refs).toEqual(["task.review", "task.draft"]);
    expect(payload.enabled).toBe(true);
  });

  it("adapts the legacy editor stack into a V2 draft for Studio pages", () => {
    const legacyDrafts = {
      coordinationDraft: {
        graph_id: "graph.editor",
        coordination_task_id: "graph.editor",
        title: "Editor graph",
        graph_kind: "multi_agent",
        domain_id: "domain.editor",
        task_family: "editor",
        coordinator_agent_id: "agent:coordinator",
        agent_group_id: "group.editor",
        coordination_mode: "pipeline",
        topology_template_id: "topology.editor",
        protocol_id: "protocol.editor",
        shared_context_policy: "explicit_refs_only",
        memory_sharing_policy: "isolated_by_default",
        handoff_policy: "filtered_handoff",
        conflict_resolution_policy: "coordinator_review",
        output_merge_policy: "coordinator_final_merge",
        stop_conditions: [],
        subtask_refs: [],
        graph_nodes: [],
        graph_edges: [],
        communication_modes: ["structured_handoff"],
        enabled: false,
        participant_agent_ids: ["agent:writer"],
        metadata: {
          entry_node_id: "start",
          output_node_id: "done",
          runtime_policy: {
            default_execution_mode: "async",
          },
          context_policy: {
            shared_context_policy: "shared_task_context",
          },
          working_memory_policy_profile_id: "wmprofile.editor",
          working_memory_policy: {
            default_scope: "task_scope",
          },
          graph_contract_id: "contract.editor.graph",
          artifact_policy: {
            enabled: true,
            materializer: "json_artifact_bundle",
          },
        },
        stop_conditions_text: "",
      },
      topologyDraft: {
        template_id: "topology.editor",
        title: "Editor topology",
        nodes: [
          { node_id: "start", node_type: "agent", title: "Start", agent_id: "agent:planner" },
          { node_id: "done", node_type: "agent", title: "Done", agent_id: "agent:writer" },
        ],
        edges: [
          { edge_id: "edge.1", source_node_id: "start", target_node_id: "done", mode: "structured_handoff" },
        ],
        handoff_rules: [],
        join_policy: "explicit_join",
        failure_policy: "fail_closed",
        terminal_policy: "coordinator_terminal",
        enabled: false,
        metadata: {},
        nodes_text: "[]",
        edges_text: "[]",
        handoff_rules_text: "[]",
      },
      protocolDraft: {
        protocol_id: "protocol.editor",
        title: "Editor protocol",
        message_types: ["message/send"],
        payload_contracts: [],
        signal_rules: [],
        handoff_rules: [],
        ack_policy: "explicit_ack",
        timeout_policy: "fail_closed",
        error_signal_policy: "raise_to_coordinator",
        enabled: false,
        metadata: {},
        message_types_text: "",
        payload_contracts_text: "",
        signal_rules_text: "",
        handoff_rules_text: "",
      },
    } satisfies LegacyTaskGraphStack;

    const draft = legacyStackToTaskGraphDraftV2(legacyDrafts);

    expect(draft.graph_id).toBe("graph.editor");
    expect(draft.entry_node_id).toBe("start");
    expect(draft.output_node_id).toBe("done");
    expect(draft.runtime_policy.coordinator_agent_id).toBe("agent:coordinator");
    expect(draft.runtime_policy.default_execution_mode).toBe("async");
    expect(draft.context_policy.shared_context_policy).toBe("shared_task_context");
    expect(draft.context_policy.memory_sharing_policy).toBe("isolated_by_default");
    expect(draft.working_memory_policy_profile_id).toBe("wmprofile.editor");
    expect(draft.working_memory_policy.default_scope).toBe("task_scope");
    expect(draft.graph_contract_id).toBe("contract.editor.graph");
    expect(draft.metadata.artifact_policy).toEqual({ enabled: true, materializer: "json_artifact_bundle" });
  });

  it("prefers edited topology nodes and edges over stale coordination mirrors when saving", () => {
    const legacyDrafts = {
      coordinationDraft: {
        graph_id: "graph.stale",
        coordination_task_id: "graph.stale",
        title: "Stale graph",
        graph_kind: "multi_agent",
        domain_id: "domain.stale",
        task_family: "stale",
        coordinator_agent_id: "agent:coordinator",
        agent_group_id: "",
        coordination_mode: "pipeline",
        topology_template_id: "topology.stale",
        protocol_id: "protocol.stale",
        shared_context_policy: "explicit_refs_only",
        memory_sharing_policy: "isolated_by_default",
        handoff_policy: "filtered_handoff",
        conflict_resolution_policy: "coordinator_review",
        output_merge_policy: "coordinator_final_merge",
        stop_conditions: [],
        subtask_refs: [],
        graph_nodes: [
          { node_id: "agent_1", title: "Old", agent_id: "agent:old" },
        ],
        graph_edges: [
          { edge_id: "edge_1", source_node_id: "agent_1", target_node_id: "agent_2", payload_contract_id: "contract.old" },
        ],
        communication_modes: ["structured_handoff"],
        enabled: false,
        participant_agent_ids: [],
        metadata: {},
        stop_conditions_text: "",
      },
      topologyDraft: {
        template_id: "topology.stale",
        title: "Stale topology",
        nodes: [
          { node_id: "agent_1", title: "New", agent_id: "agent:new" },
          { node_id: "agent_2", title: "Reviewer", agent_id: "agent:reviewer" },
        ],
        edges: [
          { edge_id: "edge_1", source_node_id: "agent_1", target_node_id: "agent_2", payload_contract_id: "contract.new" },
        ],
        handoff_rules: [],
        join_policy: "explicit_join",
        failure_policy: "fail_closed",
        terminal_policy: "coordinator_terminal",
        enabled: false,
        metadata: {},
        nodes_text: "[]",
        edges_text: "[]",
        handoff_rules_text: "[]",
      },
      protocolDraft: {
        protocol_id: "protocol.stale",
        title: "Stale protocol",
        message_types: ["message/send"],
        payload_contracts: [],
        signal_rules: [],
        handoff_rules: [],
        ack_policy: "explicit_ack",
        timeout_policy: "fail_closed",
        error_signal_policy: "raise_to_coordinator",
        enabled: false,
        metadata: {},
        message_types_text: "",
        payload_contracts_text: "",
        signal_rules_text: "",
        handoff_rules_text: "",
      },
    } satisfies LegacyTaskGraphStack;

    const payload = buildTaskGraphUpsertPayload({
      taskGraphDraft: legacyStackToTaskGraphDraftV2(legacyDrafts),
      legacyDrafts,
      domain_id: "domain.stale",
      task_family: "stale",
      task_id: "task.stale",
      publish_state: "draft",
    });

    expect(payload.nodes?.map((node) => node.agent_id)).toEqual(["agent:new", "agent:reviewer"]);
    expect(payload.edges?.[0]?.payload_contract_id).toBe("contract.new");
  });

  it("restores a V2 draft from TaskGraph first-class fields before legacy metadata", () => {
    const graph: TaskGraphRecord = {
      graph_id: "graph.restore",
      title: "Restore graph",
      domain_id: "domain.current",
      task_family: "current",
      graph_kind: "multi_agent",
      entry_node_id: "draft",
      output_node_id: "review",
      nodes: [
        { node_id: "draft", node_type: "agent", title: "Draft", agent_id: "agent:writer" },
        { node_id: "review", node_type: "agent", title: "Review", agent_id: "agent:reviewer" },
      ],
      edges: [
        { edge_id: "edge.1", source_node_id: "draft", target_node_id: "review", edge_type: "handoff" },
      ],
      working_memory_policy_profile_id: "wmprofile.current",
      working_memory_policy: {
        default_scope: "graph_scope",
      },
      runtime_policy: {
        coordinator_agent_id: "agent:current",
        participant_agent_ids: ["agent:writer", "agent:reviewer"],
        agent_group_id: "group.current",
        coordination_mode: "parallel_review",
      },
      context_policy: {
        shared_context_policy: "shared_task_context",
        memory_sharing_policy: "graph_scoped",
      },
      publish_state: "published",
      enabled: true,
      metadata: {
        task_id: "task.restore",
        coordinator_agent_id: "agent:legacy",
        runtime_policy: {
          coordinator_agent_id: "agent:legacy_runtime",
        },
        working_memory_policy: {
          default_scope: "legacy_scope",
        },
      },
    };

    const draft = taskGraphRecordToDraftV2(graph);

    expect(draft.runtime_policy.coordinator_agent_id).toBe("agent:current");
    expect(draft.runtime_policy.participant_agent_ids).toEqual(["agent:writer", "agent:reviewer"]);
    expect(draft.context_policy.shared_context_policy).toBe("shared_task_context");
    expect(draft.working_memory_policy_profile_id).toBe("wmprofile.current");
    expect(draft.working_memory_policy.default_scope).toBe("graph_scope");
    expect(draft.metadata.runtime_policy).toBeUndefined();
    expect(draft.metadata.graph_contract_id).toBeUndefined();
    expect(draft.publish_state).toBe("published");
  });
});
