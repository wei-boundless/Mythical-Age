import { describe, expect, it } from "vitest";

import { buildTaskGraphTemplateDraft, TASK_GRAPH_TEMPLATE_CARDS } from "./taskGraphTemplates";

describe("task graph templates", () => {
  it("generates runnable structure for every setup template", () => {
    for (const template of TASK_GRAPH_TEMPLATE_CARDS) {
      const draft = buildTaskGraphTemplateDraft({
        template_id: template.template_id,
        task_family: "test",
        selected_task_title: "测试任务",
      });

      expect(draft.nodes.length).toBeGreaterThan(0);
      expect(draft.entry_node_id).toBeTruthy();
      expect(draft.output_node_id).toBeTruthy();
      expect(Array.isArray(draft.metadata.name_registry)).toBe(true);
      expect(Array.isArray(draft.metadata.timeline_blocks)).toBe(true);
      expect(draft.nodes.some((node) => node.node_id === draft.entry_node_id)).toBe(true);
      expect(draft.nodes.some((node) => node.node_id === draft.output_node_id)).toBe(true);
      expect(draft.participant_agent_ids.length).toBeGreaterThan(0);
    }
  });

  it("generates responsibility-language fields instead of embedded prompt text", () => {
    const draft = buildTaskGraphTemplateDraft({
      template_id: "pdf_table_synthesis",
      task_family: "analysis",
    });

    for (const node of draft.nodes) {
      const metadata = node.metadata as Record<string, unknown>;
      expect(String(metadata.role_identity ?? "")).toContain("你是一名");
      expect(String(metadata.responsibility_scope ?? "")).toContain("你只负责");
      expect(String(metadata.responsibility_exclusions ?? "")).toContain("你不负责");
      expect(metadata.role_prompt).toBeUndefined();
      expect(metadata.legacy_prompt_migration).toBeUndefined();
    }
  });

  it("generates PDF and table specialist boundaries in the synthesis template", () => {
    const draft = buildTaskGraphTemplateDraft({
      template_id: "pdf_table_synthesis",
      task_family: "analysis",
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
      task_family: "analysis",
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

  it("generates a clean long-novel writing team draft with structural refs only", () => {
    const draft = buildTaskGraphTemplateDraft({
      template_id: "writing_team_long_novel",
      task_family: "writing_team_long_novel",
      loop_count: 4,
    });

    expect(draft.nodes).toHaveLength(29);
    expect(draft.edges).toHaveLength(41);
    expect(draft.entry_node_id).toBe("world_designer_a");
    expect(draft.output_node_id).toBe("memory_finalize");
    expect(draft.metadata.assembly_namespace).toBe("writing_team_long_novel");
    expect(draft.metadata.loop_policy).toMatchObject({ max_attempts: 4 });
    expect(draft.metadata.timeline_blocks).toEqual(expect.arrayContaining([
      expect.objectContaining({ block_id: "block.design", block_type: "design_graph" }),
      expect.objectContaining({ block_id: "block.creation", block_type: "creation_graph" }),
      expect.objectContaining({ block_id: "block.closing", block_type: "closing_graph" }),
    ]));
    expect(draft.metadata.name_registry).toEqual(expect.arrayContaining([
      expect.objectContaining({ object_id: "world_designer_a", display_name_zh: "世界观设计师 A" }),
      expect.objectContaining({ object_id: "memory_finalize", display_name_zh: "工作记忆收尾" }),
    ]));
    expect(draft.nodes.map((node) => node.node_id)).toEqual([
      "world_designer_a",
      "world_designer_b",
      "world_judge",
      "memory_commit_world",
      "outline_designer_a",
      "outline_designer_b",
      "outline_judge",
      "memory_commit_outline",
      "character_designer_a",
      "character_designer_b",
      "character_judge",
      "memory_commit_character",
      "chapter_plan",
      "writer_a_draft",
      "writer_b_review",
      "writer_a_revision",
      "writer_b_final_candidate",
      "novel_quality_judge",
      "world_deviation_router",
      "world_repair_a",
      "world_repair_b",
      "outline_deviation_router",
      "outline_repair_a",
      "outline_repair_b",
      "character_deviation_router",
      "character_repair_a",
      "character_repair_b",
      "memory_commit_chapter",
      "memory_finalize"
    ]);
    expect(new Set(draft.nodes.map((node) => String(node.agent_id ?? "")))).toEqual(
      new Set(["agent:writing_team_worker", "agent:writing_memory_steward"]),
    );
    expect(draft.edges.some((edge) => edge.edge_id === "edge.novel_quality_judge.writer_a_revision")).toBe(true);
    expect(draft.edges.some((edge) => edge.edge_id === "edge.novel_quality_judge.world_router")).toBe(true);
    expect(draft.edges.some((edge) => edge.edge_id === "edge.memory_commit_chapter.memory_finalize")).toBe(true);

    for (const node of draft.nodes) {
      expect(String(node.task_id ?? "")).toMatch(/^task\.writing_team\.long_novel\./);
      expect(String(node.projection_id ?? "")).toMatch(/^projection\.writing_team\.long_novel\./);
      expect(String(node.output_contract_id ?? "")).toMatch(/^contract\.writing_team\.long_novel\./);
      expect((node.metadata as Record<string, unknown>).role_prompt).toBeUndefined();
      expect((node.metadata as Record<string, unknown>).legacy_prompt_migration).toBeUndefined();
    }
  });
});
