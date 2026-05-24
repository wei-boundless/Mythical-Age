import { describe, expect, it } from "vitest";

import { buildTaskGraphTemplateDraft, TASK_GRAPH_TEMPLATE_CARDS } from "./taskGraphTemplates";
import { buildTaskGraphPreflightReport } from "./taskGraphPreflight";

describe("task graph templates", () => {
  it("generates runnable structure for every setup template", () => {
    for (const template of TASK_GRAPH_TEMPLATE_CARDS) {
      const draft = buildTaskGraphTemplateDraft({
        template_id: template.template_id,
        domain_id: "domain.test",
        selected_task_title: "测试任务",
      });

      expect(draft.nodes.length).toBeGreaterThan(0);
      expect(draft.entry_node_id).toBeTruthy();
      expect(draft.output_node_id).toBeTruthy();
      expect(Array.isArray(draft.metadata.name_registry)).toBe(true);
      expect(Array.isArray(draft.metadata.timeline_blocks)).toBe(true);
      expect((draft.metadata.editor_foundation as Record<string, unknown>).authority).toBe("task_graph.editor_foundation");
      expect(draft.nodes.some((node) => node.node_id === draft.entry_node_id)).toBe(true);
      expect(draft.nodes.some((node) => node.node_id === draft.output_node_id)).toBe(true);
      expect(draft.participant_agent_ids.length).toBeGreaterThan(0);
    }
  });

  it("generates responsibility-language fields instead of embedded prompt text", () => {
    const draft = buildTaskGraphTemplateDraft({
      template_id: "pdf_table_synthesis",
      domain_id: "domain.analysis",
    });

    for (const node of draft.nodes) {
      const metadata = node.metadata as Record<string, unknown>;
      expect(String(metadata.role_identity ?? "")).toContain("你是一名");
      expect(String(metadata.responsibility_scope ?? "")).toContain("你只负责");
      expect(String(metadata.responsibility_exclusions ?? "")).toContain("你不负责");
      expect(metadata.role_prompt).toBeUndefined();
      expect(metadata.legacy_prompt_migration).toBeUndefined();
      expect(metadata.domain_id).toBe("domain.analysis");
      expect(node.task_family).toBeUndefined();
    }
  });

  it("generates PDF and table specialist boundaries in the synthesis template", () => {
    const draft = buildTaskGraphTemplateDraft({
      template_id: "pdf_table_synthesis",
      domain_id: "domain.analysis",
    });

    expect(draft.nodes.map((node) => node.agent_id)).toEqual([
      "agent:pdf_reader",
      "agent:table_analyst",
      "agent.synthesizer",
    ]);
    expect(draft.edges).toHaveLength(2);
    expect(draft.coordination_mode).toBe("parallel_review");
  });

  it("applies setup parameters to metadata, loops, and specialist bindings", () => {
    const draft = buildTaskGraphTemplateDraft({
      template_id: "pdf_table_synthesis",
      domain_id: "domain.analysis",
      task_intent: "形成投资决策简报",
      input_material_type: "pdf_and_table",
      artifact_type: "decision_brief",
      review_strength: "strict",
      loop_count: 5,
      require_human_confirmation: true,
      agent_bindings: {
        pdf_analyst: "agent.custom_pdf",
        table_analyst: "agent.custom_table",
      },
    });

    expect(draft.nodes.map((node) => node.agent_id)).toContain("agent.custom_pdf");
    expect(draft.nodes.map((node) => node.agent_id)).toContain("agent.custom_table");
    expect(draft.metadata.template_parameters).toMatchObject({
      task_intent: "形成投资决策简报",
      input_material_type: "pdf_and_table",
      artifact_type: "decision_brief",
      review_strength: "strict",
      loop_count: 5,
      require_human_confirmation: true,
    });
    expect(draft.metadata.loop_policy).toMatchObject({ max_attempts: 5 });
    expect(draft.metadata.review_policy).toMatchObject({ strength: "strict", require_human_confirmation: true });
    expect((draft.nodes[0].metadata as Record<string, unknown>).template_prompt_context).toContain("当前任务意图：形成投资决策简报");
    expect((draft.nodes[0].metadata as Record<string, unknown>).agent_binding_source).toBe("template_parameter");
  });

  it("builds long project cycles on explicit repositories and review-approved memory commits", () => {
    const draft = buildTaskGraphTemplateDraft({
      template_id: "long_project_cycle",
      domain_id: "domain.project",
      selected_task_title: "长期项目",
    });

    const nodeTypesById = new Map(draft.nodes.map((node) => [node.node_id, String(node.node_type ?? "")]));
    expect(nodeTypesById.get("agent.memory")).toBe("memory_commit");
    expect(Array.from(nodeTypesById.values())).not.toContain("memory_resource");
    expect(nodeTypesById.get("memory.baseline")).toBe("memory_repository");
    expect(nodeTypesById.get("memory.mutable")).toBe("memory_repository");
    expect(nodeTypesById.get("memory.issue_ledger")).toBe("issue_ledger");
    expect(nodeTypesById.get("memory.artifact_index")).toBe("memory_repository");

    const memoryReads = draft.edges.filter((edge) => edge.edge_type === "memory_read");
    expect(memoryReads.map((edge) => edge.target_node_id)).toEqual(expect.arrayContaining(["agent.planner", "agent.executor", "agent.reviewer"]));

    const writeCandidateEdges = draft.edges.filter((edge) => edge.edge_type === "memory_write_candidate");
    expect(writeCandidateEdges.length).toBeGreaterThanOrEqual(3);
    for (const edge of writeCandidateEdges) {
      const metadata = edge.metadata as Record<string, unknown>;
      expect(metadata.source_output_key).toBeTruthy();
      expect(metadata.record_key).toBeTruthy();
      expect(metadata.record_kind).toBeTruthy();
    }

    const commitEdges = draft.edges.filter((edge) => edge.edge_type === "memory_commit");
    expect(commitEdges.length).toBeGreaterThanOrEqual(3);
    for (const edge of commitEdges) {
      const metadata = edge.metadata as Record<string, unknown>;
      expect(metadata.approval_source_node_id).toBe("agent.reviewer");
      expect(metadata.commit_visibility_policy).toMatchObject({ visible_after: "next_clock" });
    }

    const reviewer = draft.nodes.find((node) => node.node_id === "agent.reviewer");
    const memorySteward = draft.nodes.find((node) => node.node_id === "agent.memory");
    expect(reviewer?.memory_writeback_policy).toMatchObject({ writable_kinds: ["review_issue_record"] });
    expect(memorySteward?.memory_writeback_policy).toMatchObject({ writable_kinds: ["memory_commit_record"] });
  });

  it("preflights generated long project cycles without publish-blocking errors", () => {
    const draft = buildTaskGraphTemplateDraft({
      template_id: "long_project_cycle",
      domain_id: "domain.project",
      selected_task_title: "长期项目",
    });

    const report = buildTaskGraphPreflightReport({
      nodes: draft.nodes,
      edges: draft.edges,
      metadata: draft.metadata,
      dirty: false,
      editorValid: true,
      editorIssueCount: 0,
    });

    expect(report.valid).toBe(true);
    expect(report.error_count).toBe(0);
    expect(report.issues.some((issue) => issue.title === "节点未绑定 Agent" && issue.target_id.startsWith("memory."))).toBe(false);
    expect(report.issues.some((issue) => issue.title === "记忆提交缺少审核裁决字段")).toBe(false);
    expect(report.issues.some((issue) => issue.title === "写入候选缺少提交路径")).toBe(false);
    expect(report.issues.some((issue) => issue.title === "timeline_block_imported_graph_missing")).toBe(false);
  });

});

