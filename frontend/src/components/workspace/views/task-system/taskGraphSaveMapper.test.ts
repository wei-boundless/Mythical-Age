import { describe, expect, it } from "vitest";

import type { TaskGraphRecord } from "@/lib/api";

import { emptyTaskGraphDraftV2, inferTaskGraphBoundaryNodes, taskGraphRecordToDraftV2 } from "./taskGraphDraftV2";
import { buildTaskGraphUpsertPayload } from "./taskGraphSaveMapper";

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

  it("builds a TaskGraph upsert payload from first-class V2 draft fields only", () => {
    const draft = {
      ...emptyTaskGraphDraftV2(),
      graph_id: "graph.test.story",
      title: "Story graph",
      domain_id: "domain.story",
      task_family: "story",
      task_id: "task.story",
      entry_node_id: "draft",
      output_node_id: "review",
      graph_contract_id: "contract.story.graph",
      working_memory_policy_profile_id: "wmprofile.story",
      working_memory_policy: {
        default_scope: "graph_scope",
        default_visibility: "handoff_only",
      },
      runtime_policy: {
        coordinator_agent_id: "agent:coordinator",
        participant_agent_ids: [],
        agent_group_id: "group.story",
        coordination_mode: "review_merge",
        human_gate_mode: "auto_continue",
        default_execution_mode: "parallel",
        max_parallel_nodes: 3,
      },
      context_policy: {
        shared_context_policy: "explicit_refs_only",
        memory_sharing_policy: "isolated_by_default",
      },
      nodes: [
        { node_id: "review", node_type: "agent", title: "Review", agent_id: "agent:reviewer", task_id: "task.review" },
        { node_id: "draft", node_type: "agent", title: "Draft", agent_id: "agent:writer", task_id: "task.draft" },
      ],
      edges: [
        { edge_id: "edge.1", source_node_id: "draft", target_node_id: "review", edge_type: "structured_handoff" },
      ],
      metadata: {
        artifact_policy: {
          enabled: true,
        },
      },
    };

    const payload = buildTaskGraphUpsertPayload({
      taskGraphDraft: draft,
      domain_id: "domain.story",
      task_family: "story",
      task_id: "task.story",
      publish_state: "published",
    });

    expect(payload.runtime_policy?.coordinator_agent_id).toBe("agent:coordinator");
    expect(payload.runtime_policy?.participant_agent_ids).toEqual(["agent:reviewer", "agent:writer"]);
    expect(payload.runtime_policy?.default_execution_mode).toBe("parallel");
    expect(payload.runtime_policy?.human_gate_mode).toBe("auto_continue");
    expect(payload.metadata?.continuation_policy).toEqual({ human_gate_mode: "auto_continue" });
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

  it("restores a V2 draft from TaskGraph first-class fields before metadata fallbacks", () => {
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
        human_gate_mode: "non_blocking",
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
    expect(draft.runtime_policy.human_gate_mode).toBe("non_blocking");
    expect(draft.context_policy.shared_context_policy).toBe("shared_task_context");
    expect(draft.working_memory_policy_profile_id).toBe("wmprofile.current");
    expect(draft.working_memory_policy.default_scope).toBe("graph_scope");
    expect(draft.metadata.runtime_policy).toBeUndefined();
    expect(draft.metadata.graph_contract_id).toBeUndefined();
    expect(draft.publish_state).toBe("published");
  });
});
