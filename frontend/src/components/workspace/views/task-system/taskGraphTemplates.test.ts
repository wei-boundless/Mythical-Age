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
      expect(draft.nodes.some((node) => node.node_id === draft.entry_node_id)).toBe(true);
      expect(draft.nodes.some((node) => node.node_id === draft.output_node_id)).toBe(true);
      expect(draft.participant_agent_ids.length).toBeGreaterThan(0);
    }
  });

  it("generates responsibility-language prompts instead of field descriptions", () => {
    const draft = buildTaskGraphTemplateDraft({
      template_id: "pdf_table_synthesis",
      task_family: "analysis",
    });

    for (const node of draft.nodes) {
      const metadata = node.metadata as Record<string, unknown>;
      const prompt = String(metadata.role_prompt ?? "");
      expect(prompt).toContain("你是一名");
      expect(prompt).toContain("你只负责");
      expect(prompt).toContain("你不负责");
      expect(prompt).not.toContain("这是 runtime 节点");
      expect(prompt).not.toContain("根据任务图执行");
    }
  });

  it("generates PDF and table specialist boundaries in the synthesis template", () => {
    const draft = buildTaskGraphTemplateDraft({
      template_id: "pdf_table_synthesis",
      task_family: "analysis",
    });

    expect(draft.nodes.map((node) => node.agent_id)).toEqual([
      "agent.pdf_analyst",
      "agent.table_analyst",
      "agent.synthesizer",
    ]);
    expect(draft.edges).toHaveLength(2);
    expect(draft.coordination_mode).toBe("parallel_review");
  });

  it("applies setup parameters to prompts, metadata, loops, and specialist bindings", () => {
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
    expect(String((draft.nodes[0].metadata as Record<string, unknown>).role_prompt)).toContain("当前任务意图：形成投资决策简报");
    expect((draft.nodes[0].metadata as Record<string, unknown>).agent_binding_source).toBe("template_parameter");
  });
});
