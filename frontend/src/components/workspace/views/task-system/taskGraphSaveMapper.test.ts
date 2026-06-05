import { describe, expect, it } from "vitest";

import type { TaskGraphRecord } from "@/lib/api";

import { emptyTaskGraphDraftV2, inferTaskGraphBoundaryNodes, taskGraphRecordToDraftV2 } from "./taskGraphDraftV2";
import { buildTaskGraphUpsertPayload, resolveTaskGraphPublishCommit } from "./taskGraphSaveMapper";

describe("TaskGraphDraftV2 mapping", () => {
  it("resolves publish commit intent in one place", () => {
    expect(resolveTaskGraphPublishCommit("save_draft")).toMatchObject({
      editor_publish_state: "saved",
      backend_publish_state: "draft",
      enabled: false,
    });
    expect(resolveTaskGraphPublishCommit("publish")).toMatchObject({
      editor_publish_state: "published",
      backend_publish_state: "published",
      enabled: true,
    });
    expect(resolveTaskGraphPublishCommit("mark_run_bound")).toMatchObject({
      editor_publish_state: "run_bound",
      backend_publish_state: "published",
      enabled: true,
    });
    expect(resolveTaskGraphPublishCommit("archive")).toMatchObject({
      editor_publish_state: "archived",
      backend_publish_state: "draft",
      enabled: false,
    });
  });

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
      task_id: "task.story",
      entry_node_id: "draft",
      output_node_id: "review",
      contract_bindings: {
        schema: { graph_contract_id: "contract.story.graph" },
      },
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
    expect((payload.contract_bindings as Record<string, Record<string, unknown>> | undefined)?.schema).toEqual({ graph_contract_id: "contract.story.graph" });
    expect((payload.contract_bindings as Record<string, Record<string, unknown>> | undefined)?.memory).toEqual({
      working_memory_policy: {
        default_scope: "graph_scope",
        default_visibility: "handoff_only",
      },
    });
    expect(payload.entry_node_id).toBe("draft");
    expect(payload.output_node_id).toBe("review");
    expect(payload.metadata?.runtime_policy).toBeUndefined();
    expect(payload.metadata?.working_memory_policy).toBeUndefined();
    expect(payload.metadata?.graph_contract_id).toBeUndefined();
    expect(payload.metadata?.task_family).toBeUndefined();
    expect((payload as Record<string, unknown>).task_family).toBeUndefined();
    expect(payload.metadata?.artifact_policy).toEqual({ enabled: true });
    expect(payload.metadata?.subtask_refs).toEqual(["task.review", "task.draft"]);
    expect(payload.enabled).toBe(true);
  });

  it("projects canonical contract_bindings into the backend DTO fields", () => {
    const draft = {
      ...emptyTaskGraphDraftV2(),
      graph_id: "graph.test.contracts",
      title: "Contract graph",
      contract_bindings: {
        schema: { graph_contract_id: "contract.graph" },
      },
      nodes: [
        {
          node_id: "draft",
          node_type: "agent",
          title: "Draft",
          contract_bindings: {
            schema: {
              input_contract_id: "contract.input",
              output_contract_id: "contract.output",
            },
            execution: { node_contract_id: "contract.executor" },
          },
          memory_read_policy: { readable_scopes: ["baseline"] },
          artifact_policy: { target: "draft.md" },
        },
      ],
      edges: [
        {
          edge_id: "edge.1",
          source_node_id: "draft",
          target_node_id: "draft",
          edge_type: "handoff",
          contract_bindings: {
            schema: { payload_contract_id: "contract.payload" },
          },
          ack_required: true,
          ack_policy: "explicit_ack",
          metadata: { temporal_semantics: { visibility_timing: "after_commit" } },
        },
      ],
    };

    const payload = buildTaskGraphUpsertPayload({
      taskGraphDraft: draft,
      domain_id: "",
      task_id: "",
      publish_state: "draft",
    });

    expect(payload.graph_contract_id).toBe("contract.graph");
    expect(payload.nodes[0]?.input_contract_id).toBe("contract.input");
    expect(payload.nodes[0]?.output_contract_id).toBe("contract.output");
    expect(payload.nodes[0]?.node_contract_id).toBe("contract.executor");
    expect(payload.edges[0]?.payload_contract_id).toBe("contract.payload");
    expect((payload.nodes[0]?.contract_bindings as Record<string, Record<string, unknown>> | undefined)?.schema).toEqual({
      input_contract_id: "contract.input",
      output_contract_id: "contract.output",
    });
    expect((payload.nodes[0]?.contract_bindings as Record<string, Record<string, unknown>> | undefined)?.execution).toEqual({
      node_contract_id: "contract.executor",
    });
    expect((payload.nodes[0]?.contract_bindings as Record<string, Record<string, unknown>> | undefined)?.memory).toEqual({
      memory_read_policy: { readable_scopes: ["baseline"] },
    });
    expect((payload.edges[0]?.contract_bindings as Record<string, Record<string, unknown>> | undefined)?.schema).toEqual({
      payload_contract_id: "contract.payload",
    });
    expect((payload.edges[0]?.contract_bindings as Record<string, Record<string, unknown>> | undefined)?.handoff).toMatchObject({
      ack_required: true,
      ack_policy: "explicit_ack",
    });
    expect((payload.edges[0]?.contract_bindings as Record<string, Record<string, unknown>> | undefined)?.temporal).toEqual({
      visibility_timing: "after_commit",
    });
  });

  it("keeps node configuration references first-class instead of saving metadata fallbacks", () => {
    const draft = {
      ...emptyTaskGraphDraftV2(),
      graph_id: "graph.test.node-config",
      title: "Node config graph",
      nodes: [
        {
          node_id: "draft",
          node_type: "agent",
          title: "Draft",
          node_config_id: "nodecfg.story.writer",
          node_config_overrides: { role_prompt_patch: "只写大纲。" },
          metadata: {
            node_config_id: "nodecfg.stale.writer",
            node_config_overrides: { role_prompt_patch: "stale" },
            note: "kept",
          },
        },
      ],
      edges: [],
    };

    const payload = buildTaskGraphUpsertPayload({
      taskGraphDraft: draft,
      domain_id: "",
      task_id: "",
      publish_state: "draft",
    });

    expect(payload.nodes[0]?.node_config_id).toBe("nodecfg.story.writer");
    expect(payload.nodes[0]?.node_config_overrides).toEqual({ role_prompt_patch: "只写大纲。" });
    expect(payload.nodes[0]?.metadata).toEqual({ note: "kept" });
  });

  it("ignores stale flat contract fields when contract_bindings are present", () => {
    const draft = {
      ...emptyTaskGraphDraftV2(),
      graph_id: "graph.test.contract-authority",
      title: "Contract authority graph",
      graph_contract_id: "contract.stale.graph",
      contract_bindings: {
        schema: { graph_contract_id: "contract.binding.graph" },
      },
      nodes: [
        {
          node_id: "draft",
          node_type: "agent",
          title: "Draft",
          input_contract_id: "contract.stale.input",
          output_contract_id: "contract.stale.output",
          node_contract_id: "contract.stale.executor",
          contract_bindings: {
            schema: {
              input_contract_id: "contract.binding.input",
              output_contract_id: "contract.binding.output",
            },
            execution: { node_contract_id: "contract.binding.executor" },
          },
        },
      ],
      edges: [
        {
          edge_id: "edge.1",
          source_node_id: "draft",
          target_node_id: "draft",
          edge_type: "handoff",
          payload_contract_id: "contract.stale.payload",
          contract_bindings: {
            schema: { payload_contract_id: "contract.binding.payload" },
          },
        },
      ],
    };

    const payload = buildTaskGraphUpsertPayload({
      taskGraphDraft: draft,
      domain_id: "",
      task_id: "",
      publish_state: "draft",
    });

    expect((payload.contract_bindings as Record<string, Record<string, unknown>> | undefined)?.schema).toEqual({
      graph_contract_id: "contract.binding.graph",
    });
    expect((payload.nodes[0]?.contract_bindings as Record<string, Record<string, unknown>> | undefined)?.schema).toEqual({
      input_contract_id: "contract.binding.input",
      output_contract_id: "contract.binding.output",
    });
    expect((payload.nodes[0]?.contract_bindings as Record<string, Record<string, unknown>> | undefined)?.execution).toEqual({
      node_contract_id: "contract.binding.executor",
    });
    expect((payload.edges[0]?.contract_bindings as Record<string, Record<string, unknown>> | undefined)?.schema).toEqual({
      payload_contract_id: "contract.binding.payload",
    });
  });

  it("restores a V2 draft from TaskGraph first-class fields before stale metadata copies", () => {
    const graph: TaskGraphRecord = {
      graph_id: "graph.restore",
      title: "Restore graph",
      domain_id: "domain.current",
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
      contract_bindings: {
        schema: { graph_contract_id: "contract.restore" },
      },
      metadata: {
        task_id: "task.restore",
        coordinator_agent_id: "agent:stale",
        runtime_policy: {
          coordinator_agent_id: "agent:stale_runtime",
        },
        working_memory_policy: {
          default_scope: "stale_scope",
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
    expect((draft.contract_bindings.schema as Record<string, unknown> | undefined)).toEqual({ graph_contract_id: "contract.restore" });
  });
});
