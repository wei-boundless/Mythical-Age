import { describe, expect, it } from "vitest";

import type { TaskGraphContractPreview } from "@/lib/api";

import { buildTaskGraphPreflightReport } from "./taskGraphPreflight";

function graphContractPreview(
  patch: Pick<TaskGraphContractPreview, "valid" | "issues"> & Partial<TaskGraphContractPreview>,
): TaskGraphContractPreview {
  return {
    authority: "test.task_graph_contract_preview",
    contract_id: "contract.graph.test",
    graph_id: "graph.test",
    title: "测试图契约",
    graph_harness_config: {
      authority: "harness.graph_harness_config",
      config_id: "ghcfg:test",
      graph_id: "graph.test",
      graph_title: "测试图契约",
      publish_version: "published",
      content_hash: "hash",
      status: "published",
      task_environment_id: "",
      root_task_ref: "",
      control: {},
      nodes: [],
      edges: [],
      loop_frames: [],
      resources: {},
      memory: {},
      artifacts: {},
      permissions: {},
      tools: {},
      agents: {},
      contracts: {},
      composition_sources: [],
      diagnostics: {},
      authority_map: {},
      source_refs: {},
    },
    scheduler_view: {
      authority: "harness.graph.scheduler_view",
      config_id: "ghcfg:test",
      config_hash: "hash",
      dependency_edges: [],
      executable_node_ids: [],
      start_node_ids: [],
      terminal_node_ids: [],
      diagnostics: {},
    },
    composition_sources: [],
    split_plans: [],
    object_trace_index: [],
    summary: {},
    ...patch,
  };
}

describe("TaskGraph preflight", () => {
  it("blocks a multi-node graph without handoff edges", () => {
    const report = buildTaskGraphPreflightReport({
      dirty: false,
      editorIssueCount: 0,
      editorValid: true,
      nodes: [
        { node_id: "draft", agent_id: "agent:writer" },
        { node_id: "review", agent_id: "agent:reviewer" },
      ],
      edges: [],
    });

    expect(report.valid).toBe(false);
    expect(report.error_count).toBe(1);
    expect(report.issues[0]?.title).toBe("多节点任务图没有交接边");
  });

  it("reports invalid edge endpoints and missing payload contracts separately", () => {
    const report = buildTaskGraphPreflightReport({
      dirty: false,
      editorIssueCount: 0,
      editorValid: true,
      nodes: [{ node_id: "draft", agent_id: "agent:writer" }],
      edges: [
        { edge_id: "bad_edge", source_node_id: "draft", target_node_id: "missing" },
      ],
    });

    expect(report.valid).toBe(false);
    expect(report.issues.map((issue) => issue.title)).toContain("交接边引用了不存在的节点");
    expect(report.issues.map((issue) => issue.title)).toContain("交接边未绑定载荷契约");
  });

  it("merges backend graph contract issues into the same report", () => {
    const report = buildTaskGraphPreflightReport({
      dirty: false,
      editorIssueCount: 0,
      editorValid: true,
      nodes: [{ node_id: "draft", agent_id: "agent:writer" }],
      edges: [],
      graphContract: graphContractPreview({
        valid: false,
        issues: [
          {
            code: "missing_subtask",
            message: "节点引用的特定任务不存在",
            node_id: "draft",
            severity: "error",
          },
        ],
      }),
    });

    expect(report.valid).toBe(false);
    expect(report.issues.some((issue) => issue.source === "backend.graph_contract")).toBe(true);
  });

  it("merges backend composable graph issues into the publish preflight report", () => {
    const report = buildTaskGraphPreflightReport({
      dirty: false,
      editorIssueCount: 0,
      editorValid: true,
      nodes: [{ node_id: "draft", agent_id: "agent:writer" }],
      edges: [],
      standardView: {
        issues: [
          {
            code: "graph_module_handoff_contract_missing",
            message: "图模块运行缺少交接契约",
            severity: "warning",
            unit_id: "unit.graph.block.design",
            source: "task_system.composable_graph_issue",
          },
          {
            code: "port_edge_target_port_missing",
            message: "端口边的目标端口不存在",
            severity: "error",
            edge_id: "edge.design.creation",
            source: "task_system.composable_graph_issue",
          },
        ],
      },
    });

    expect(report.valid).toBe(false);
    expect(report.issues.some((issue) => issue.source === "backend.composable_graph" && issue.scope === "unit")).toBe(true);
    expect(report.issues.some((issue) => issue.source === "backend.composable_graph" && issue.scope === "port_edge" && issue.severity === "error")).toBe(true);
  });

  it("routes graph module expansion issues to graph module diagnostics", () => {
    const report = buildTaskGraphPreflightReport({
      dirty: false,
      editorIssueCount: 0,
      editorValid: true,
      nodes: [{ node_id: "graph_module.block.design", node_type: "graph_module" }],
      edges: [],
      standardView: {
        issues: [
          {
            code: "graph_module_linked_graph_not_found",
            message: "导入图模块不存在",
            severity: "error",
            unit_id: "unit.graph.block.design",
            source: "task_system.graph_module_expansion",
          },
        ],
        graph_module_expansions: [
          {
            plan_id: "graph_module_runtime.block.design",
            runtime_node_id: "graph_module.block.design",
            unit_id: "unit.graph.block.design",
            linked_graph_id: "graph.missing",
            scope_prefix: "graph_module.block.design::",
            issues: [
              {
                code: "graph_module_linked_graph_not_found",
                message: "导入图模块不存在",
                severity: "error",
                unit_id: "unit.graph.block.design",
              },
            ],
          },
        ],
      },
    });

    const expansionIssues = report.issues.filter((issue) => issue.source === "backend.graph_module_expansion");
    expect(report.valid).toBe(false);
    expect(expansionIssues).toHaveLength(1);
    expect(expansionIssues[0]?.scope).toBe("graph_module");
    expect(expansionIssues[0]?.target_id).toBe("unit.graph.block.design");
  });

  it("warns when nodes have no Chinese name registry or explicit display name", () => {
    const report = buildTaskGraphPreflightReport({
      dirty: false,
      editorIssueCount: 0,
      editorValid: true,
      nodes: [{ node_id: "node.raw", node_type: "agent_role", title: "", agent_id: "agent:test" }],
      edges: [],
      metadata: {},
    });

    expect(report.issues.some((issue) => issue.source === "frontend.preflight.name_registry")).toBe(true);
  });

  it("labels scheduler support issues separately from generic runtime issues", () => {
    const report = buildTaskGraphPreflightReport({
      dirty: false,
      editorIssueCount: 0,
      editorValid: true,
      nodes: [{ node_id: "review", agent_id: "agent:reviewer" }],
      edges: [],
      graphContract: graphContractPreview({
        valid: true,
        issues: [
          {
            code: "scheduler_policy_unsupported",
            message: "join_policy 当前调度器尚未实现。",
            node_id: "review",
            severity: "warning",
          },
        ],
      }),
    });

    const issue = report.issues.find((item) => item.title === "scheduler_policy_unsupported");
    expect(issue?.source).toBe("backend.scheduler_support");
    expect(issue?.scope).toBe("node");
    expect(report.valid).toBe(true);
  });

  it("warns when an edge memory handoff policy has no carry shape", () => {
    const report = buildTaskGraphPreflightReport({
      dirty: false,
      editorIssueCount: 0,
      editorValid: true,
      nodes: [
        { node_id: "a", agent_id: "agent.a" },
        { node_id: "b", agent_id: "agent.b" },
      ],
      edges: [
        {
          edge_id: "edge.a.b",
          source_node_id: "a",
          target_node_id: "b",
          payload_contract_id: "contract.payload",
          working_memory_handoff_policy: { mode: "carry_selected" },
        },
      ],
    });

    expect(report.issues.some((issue) => issue.source === "frontend.preflight.memory_handoff")).toBe(true);
  });

  it("includes timeline lifecycle issues in the unified report", () => {
    const report = buildTaskGraphPreflightReport({
      dirty: false,
      editorIssueCount: 0,
      editorValid: true,
      metadata: {
        phase_definitions: [
          {
            phase_id: "phase.review",
            title: "审核",
            loop_policy: { mode: "repair_loop" },
          },
        ],
      },
      nodes: [
        { node_id: "review", agent_id: "agent.review", phase_id: "phase.review" },
      ],
      edges: [],
    });

    expect(report.issues.some((issue) => issue.source === "frontend.preflight.timeline")).toBe(true);
    expect(report.issues.some((issue) => issue.scope === "phase" && issue.target_id === "phase.review")).toBe(true);
  });

  it("warns when legacy node prompt has not been consolidated into role prompt", () => {
    const report = buildTaskGraphPreflightReport({
      dirty: false,
      editorIssueCount: 0,
      editorValid: true,
      nodes: [
        {
          node_id: "review",
          agent_id: "agent.review",
          metadata: {
            legacy_prompt_migration: {
              legacy_field_names: ["role_identity", "responsibility_scope", "definition_of_done"],
              migration_status: "pending_role_prompt",
            },
          },
        },
      ],
      edges: [],
    });

    expect(report.issues.some((issue) => issue.source === "frontend.preflight.prompt_semantics")).toBe(true);
  });

  it("does not block publishing on warnings and info issues", () => {
    const report = buildTaskGraphPreflightReport({
      dirty: false,
      editorIssueCount: 0,
      editorValid: true,
      nodes: [
        { node_id: "a", agent_id: "agent.a" },
        { node_id: "b", agent_id: "" },
      ],
      edges: [
        {
          edge_id: "edge.a.b",
          source_node_id: "a",
          target_node_id: "b",
          payload_contract_id: "contract.payload",
          working_memory_handoff_policy: { mode: "carry_selected" },
        },
      ],
    });

    expect(report.error_count).toBe(0);
    expect(report.warning_count).toBeGreaterThan(0);
    expect(report.valid).toBe(true);
  });

  it("blocks memory reads without an explicit selector collection", () => {
    const report = buildTaskGraphPreflightReport({
      dirty: false,
      editorIssueCount: 0,
      editorValid: true,
      nodes: [
        {
          node_id: "memory.project",
          node_type: "memory_repository",
          metadata: { memory_repository: { repository_id: "memory.project", collections: ["requirements"] } },
        },
        { node_id: "draft", agent_id: "agent.draft" },
      ],
      edges: [
        {
          edge_id: "edge.memory.draft",
          source_node_id: "memory.project",
          target_node_id: "draft",
          edge_type: "memory_read",
          payload_contract_id: "contract.memory.read",
          metadata: { repository: "memory.project" },
        },
      ],
    });

    expect(report.valid).toBe(false);
    expect(report.issues.some((issue) => issue.source === "frontend.preflight.memory_selector" && issue.severity === "error")).toBe(true);
  });

  it("warns when a write candidate has no reachable commit path", () => {
    const report = buildTaskGraphPreflightReport({
      dirty: false,
      editorIssueCount: 0,
      editorValid: true,
      nodes: [
        {
          node_id: "memory.project",
          node_type: "memory_repository",
          metadata: { memory_repository: { repository_id: "memory.project", collections: ["facts"] } },
        },
        { node_id: "worker", agent_id: "agent.worker" },
      ],
      edges: [
        {
          edge_id: "edge.worker.memory",
          source_node_id: "worker",
          target_node_id: "memory.project",
          edge_type: "memory_write_candidate",
          payload_contract_id: "contract.memory.write_candidate",
          metadata: {
            repository: "memory.project",
            collection: "facts",
            record_key: "fact.current",
            record_kind: "fact",
            source_output_key: "approved_fact",
          },
        },
      ],
    });

    expect(report.valid).toBe(true);
    expect(report.issues.some((issue) => issue.source === "frontend.preflight.memory_commit_path")).toBe(true);
  });

  it("blocks memory edges that point at an undeclared repository collection", () => {
    const report = buildTaskGraphPreflightReport({
      dirty: false,
      editorIssueCount: 0,
      editorValid: true,
      nodes: [
        {
          node_id: "memory.project",
          node_type: "memory_repository",
          metadata: { memory_repository: { repository_id: "memory.project", collections: ["world"] } },
        },
        { node_id: "writer", agent_id: "agent.writer" },
      ],
      edges: [
        {
          edge_id: "edge.memory.writer.characters",
          source_node_id: "memory.project",
          target_node_id: "writer",
          edge_type: "memory_read",
          payload_contract_id: "contract.memory.read",
          metadata: {
            repository: "memory.project",
            collection: "characters",
            selector: { collection: "characters", record_key: "character.current", status_filter: ["committed"] },
            usage_instruction: "按人物定稿写作。",
          },
        },
      ],
    });

    expect(report.valid).toBe(false);
    expect(report.issues.some((issue) => issue.title === "记忆边引用了不存在的 Collection")).toBe(true);
  });

  it("diagnoses formal memory write and commit contracts", () => {
    const report = buildTaskGraphPreflightReport({
      dirty: false,
      editorIssueCount: 0,
      editorValid: true,
      nodes: [
        {
          node_id: "memory.project",
          node_type: "memory_repository",
          metadata: { memory_repository: { repository_id: "memory.project", collections: ["world"] } },
        },
        { node_id: "author", agent_id: "agent.author" },
        { node_id: "review", agent_id: "agent.review" },
      ],
      edges: [
        {
          edge_id: "edge.author.memory",
          source_node_id: "author",
          target_node_id: "memory.project",
          edge_type: "memory_write_candidate",
          payload_contract_id: "contract.memory.write",
          metadata: { repository: "memory.project", collection: "world" },
        },
        {
          edge_id: "edge.author.review",
          source_node_id: "author",
          target_node_id: "review",
          payload_contract_id: "contract.handoff",
        },
        {
          edge_id: "edge.review.memory",
          source_node_id: "review",
          target_node_id: "memory.project",
          edge_type: "memory_commit",
          payload_contract_id: "contract.memory.commit",
          metadata: {
            repository: "memory.project",
            collection: "world",
            commit_visibility_policy: { visible_after: "next_clock" },
          },
        },
      ],
    });

    expect(report.issues.some((issue) => issue.source === "frontend.preflight.memory_write_contract")).toBe(true);
    expect(report.issues.some((issue) => issue.source === "frontend.preflight.memory_commit_contract")).toBe(true);
  });

  it("surfaces backend memory protocol issues in preflight", () => {
    const report = buildTaskGraphPreflightReport({
      dirty: false,
      editorIssueCount: 0,
      editorValid: true,
      nodes: [{ node_id: "writer", agent_id: "agent.writer" }],
      edges: [],
      standardView: {
        issues: [],
        units: [],
        interfaces: [],
        port_edges: [],
        graph_module_runtime: [],
        graph_module_expansions: [],
        memory_protocol: {
          repositories: [],
          collections: [],
          read_edges: [],
          write_edges: [],
          commit_edges: [],
          issues: [
            {
              code: "memory_protocol_collection_missing",
              message: "记忆边缺少 collection，无法解析正式记忆地址。",
              severity: "error",
              edge_id: "edge.memory.read",
            },
          ],
        },
      },
    });

    expect(report.valid).toBe(false);
    expect(report.issues.some((issue) => (
      issue.source === "backend.memory_protocol"
      && issue.scope === "edge"
      && issue.target_id === "edge.memory.read"
      && issue.title === "memory_protocol_collection_missing"
    ))).toBe(true);
  });

  it("warns when revision routes do not carry original artifact and review result references", () => {
    const report = buildTaskGraphPreflightReport({
      dirty: false,
      editorIssueCount: 0,
      editorValid: true,
      nodes: [
        { node_id: "draft", agent_id: "agent.draft" },
        { node_id: "review", agent_id: "agent.review" },
      ],
      edges: [
        {
          edge_id: "edge.review.draft",
          source_node_id: "review",
          target_node_id: "draft",
          edge_type: "revision_request",
          payload_contract_id: "contract.revision",
          metadata: { usage_instruction: "按审核结果返修。" },
        },
      ],
    });

    expect(report.issues.filter((issue) => issue.source === "frontend.preflight.revision_packet")).toHaveLength(2);
  });

  it("blocks invalid batch contract ranges before publishing", () => {
    const report = buildTaskGraphPreflightReport({
      dirty: false,
      editorIssueCount: 0,
      editorValid: true,
      nodes: [
        {
          node_id: "batch.worker",
          agent_id: "agent.worker",
          contract_bindings: {
            unit_batch: { unit_kind: "record", requested_count: 0 },
            runtime: { split_policy: { mode: "static_batch", batch_size: 0 } },
          },
        },
      ],
      edges: [],
    });

    expect(report.valid).toBe(false);
    expect(report.issues.filter((issue) => issue.source === "frontend.preflight.batch_contract" && issue.severity === "error")).toHaveLength(2);
  });

  it("warns for risky batch acceptance and merge policies without blocking", () => {
    const report = buildTaskGraphPreflightReport({
      dirty: false,
      editorIssueCount: 0,
      editorValid: true,
      nodes: [
        {
          node_id: "batch.worker",
          agent_id: "agent.worker",
          contract_bindings: {
            unit_batch: { unit_kind: "file", requested_count: 4 },
            runtime: {
              split_policy: { mode: "static_batch", batch_size: 10 },
              batch_acceptance_policy: { mode: "auto_commit_without_review" },
              merge_policy: { mode: "wait_all_committed", final_review_required: false },
            },
          },
        },
      ],
      edges: [],
    });

    expect(report.valid).toBe(true);
    expect(report.issues.some((issue) => issue.title === "每批数量大于总数量" && issue.severity === "info")).toBe(true);
    expect(report.issues.some((issue) => issue.title === "批次配置为无审核提交" && issue.severity === "warning")).toBe(true);
    expect(report.issues.some((issue) => issue.title === "批次合并关闭最终审核" && issue.severity === "warning")).toBe(true);
  });

  it("validates parallel batch execution policy before publishing", () => {
    const report = buildTaskGraphPreflightReport({
      dirty: false,
      editorIssueCount: 0,
      editorValid: true,
      nodes: [
        {
          node_id: "batch.worker",
          agent_id: "agent.worker",
          contract_bindings: {
            unit_batch: { unit_kind: "record", requested_count: 8 },
            runtime: {
              split_policy: {
                mode: "static_batch",
                batch_size: 2,
                child_execution_mode: "parallel",
                max_parallel_batches: 3,
              },
              batch_acceptance_policy: { mode: "review_then_commit" },
              merge_policy: { mode: "wait_all_committed" },
            },
          },
        },
      ],
      edges: [],
    });

    expect(report.valid).toBe(true);
    expect(report.issues.filter((issue) => issue.source === "frontend.preflight.batch_contract" && issue.severity === "error")).toHaveLength(0);
  });

  it("blocks parallel batch auto commit because it bypasses review before merge", () => {
    const report = buildTaskGraphPreflightReport({
      dirty: false,
      editorIssueCount: 0,
      editorValid: true,
      nodes: [
        {
          node_id: "batch.worker",
          agent_id: "agent.worker",
          contract_bindings: {
            unit_batch: { unit_kind: "record", requested_count: 8 },
            runtime: {
              split_policy: { mode: "static_batch", batch_size: 2, child_execution_mode: "parallel" },
              batch_acceptance_policy: { mode: "auto_commit_without_review" },
              merge_policy: { mode: "wait_all_committed" },
            },
          },
        },
      ],
      edges: [],
    });

    expect(report.valid).toBe(false);
    expect(report.issues.some((issue) => issue.title === "并行批次不能无审核提交" && issue.severity === "error")).toBe(true);
    expect(report.issues.some((issue) => issue.title === "并行批次使用默认上限" && issue.severity === "info")).toBe(true);
  });
});
