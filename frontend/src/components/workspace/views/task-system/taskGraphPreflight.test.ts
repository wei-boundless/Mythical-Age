import { describe, expect, it } from "vitest";

import { buildTaskGraphPreflightReport } from "./taskGraphPreflight";

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

  it("merges backend runtime spec issues into the same report", () => {
    const report = buildTaskGraphPreflightReport({
      dirty: false,
      editorIssueCount: 0,
      editorValid: true,
      nodes: [{ node_id: "draft", agent_id: "agent:writer" }],
      edges: [],
      runtimeSpec: {
        valid: false,
        issues: [
          {
            code: "missing_subtask",
            message: "节点引用的特定任务不存在",
            node_id: "draft",
            severity: "error",
          },
        ],
      },
    });

    expect(report.valid).toBe(false);
    expect(report.issues.some((issue) => issue.source === "backend.runtime_spec")).toBe(true);
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

  it("warns when legacy node prompt has not been migrated to projection binding", () => {
    const report = buildTaskGraphPreflightReport({
      dirty: false,
      editorIssueCount: 0,
      editorValid: true,
      nodes: [
        {
          node_id: "review",
          agent_id: "agent.review",
          metadata: { role_prompt: "你是一名审核员。你只负责裁决是否通过。" },
        },
      ],
      edges: [],
    });

    expect(report.issues.some((issue) => issue.source === "frontend.preflight.projection_binding")).toBe(true);
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
});
