import { describe, expect, it } from "vitest";

import { buildMainAgentTaskSelection, MAIN_AGENT_ID, MAIN_AGENT_PROFILE_ID } from "./mainAgentAssemblyModes";

describe("main agent assembly mode projection", () => {
  it.each([
    ["role", "role_mode", "role_interaction", "runtime.recipe.role_interaction"],
    ["standard", "standard_mode", "standard_task", "runtime.recipe.standard_task"],
    ["professional", "professional_mode", "professional_task", "runtime.recipe.professional_task"],
  ] as const)("projects %s mode onto the main interactive agent", (mode, interactionMode, runtimeLane, recipeId) => {
    const payload = buildMainAgentTaskSelection(null, mode);

    expect(payload).toMatchObject({
      agent_id: MAIN_AGENT_ID,
      agent_profile_id: MAIN_AGENT_PROFILE_ID,
      interaction_mode: interactionMode,
      runtime_interaction_mode: interactionMode,
      runtime_lane: runtimeLane,
      mode_policy: {
        interaction_mode: interactionMode,
        runtime_lane: runtimeLane,
        recipe_id: recipeId,
      },
      stream_policy: {
        enabled: true,
        mode: "interactive_answer",
        emit_content_delta: true,
      },
      runtime_assembly_hint: {
        interaction_mode: interactionMode,
        runtime_mode: runtimeLane,
      },
    });
  });

  it("does not turn professional mode into a separate execution strategy", () => {
    const professional = buildMainAgentTaskSelection(null, "professional");
    const standard = buildMainAgentTaskSelection(null, "standard");

    expect(professional?.intent_decision).toMatchObject({
      interaction_mode: "professional_mode",
    });
    expect(Object.keys(professional?.runtime_assembly_hint ?? {})).not.toContain("execution_strategy");
    expect(Object.keys(professional?.mode_policy ?? {})).not.toContain("execution_strategy");
    expect(Object.keys(professional?.intent_decision ?? {})).not.toContain("execution_strategy");
    expect(Object.keys(standard?.runtime_assembly_hint ?? {})).not.toContain("execution_strategy");
  });

  it("does not send task graph launch selection from the main chat page", () => {
    const payload = buildMainAgentTaskSelection(
      {
        coordination_task_id: "graph.story.pipeline",
        label: "故事流水线",
        mode: "coordination",
      },
      "professional",
    );

    expect(payload).toBeUndefined();
  });

  it("does not override an explicit agent invocation contract", () => {
    const invocation = { invocation_id: "agentinv:node:001", assembly_contract: { runtime_lane: "graph_node" } };
    const payload = buildMainAgentTaskSelection(
      {
        selected_task_id: "task.graph.node",
        agent_id: "agent:pdf_reader",
        agent_invocation: invocation,
      },
      "standard",
    );

    expect(payload).toEqual({
      selected_task_id: "task.graph.node",
      agent_id: "agent:pdf_reader",
      agent_invocation: invocation,
    });
  });

  it("does not override task-system owned custom agent assembly", () => {
    const taskAssembly = {
      selected_task_id: "task.review.manuscript",
      label: "审稿任务",
      mode: "single_task" as const,
      agent_id: "agent:reviewer",
      agent_profile_id: "reviewer_runtime",
      runtime_lane: "review_lane",
      runtime_interaction_mode: "review_mode",
      runtime_assembly_hint: {
        runtime_mode: "review_lane",
        projection_id: "projection.taskgraph.review",
      },
      mode_policy: {
        interaction_mode: "review_mode",
        runtime_lane: "review_lane",
        recipe_id: "runtime.recipe.review",
      },
      stream_policy: {
        enabled: false,
        mode: "task_graph_controlled",
      },
    };

    expect(buildMainAgentTaskSelection(taskAssembly, "professional")).toEqual(taskAssembly);
  });

  it("keeps task selection fields while making the mode profile authoritative", () => {
    const payload = buildMainAgentTaskSelection(
      {
        selected_task_id: "task.dev.light_web_game",
        label: "小游戏",
        runtime_lane: "old_lane",
        runtime_assembly_hint: {
          runtime_mode: "professional_task",
          task_hint: "keep",
        },
        mode_policy: {
          interaction_mode: "professional_mode",
          runtime_lane: "old_lane",
          custom: true,
        },
        intent_decision: {
          interaction_mode: "professional_mode",
          user_intent: "keep",
        },
        stream_policy: {
          enabled: false,
          mode: "batch_answer",
          emit_content_delta: false,
        },
      },
      "standard",
    );

    expect(payload).toMatchObject({
      selected_task_id: "task.dev.light_web_game",
      label: "小游戏",
      runtime_lane: "standard_task",
      stream_policy: {
        enabled: true,
        mode: "interactive_answer",
        emit_content_delta: true,
      },
      runtime_assembly_hint: {
        interaction_mode: "standard_mode",
        runtime_mode: "standard_task",
        task_hint: "keep",
      },
      mode_policy: {
        custom: true,
        interaction_mode: "standard_mode",
        runtime_lane: "standard_task",
        recipe_id: "runtime.recipe.standard_task",
      },
      intent_decision: {
        interaction_mode: "standard_mode",
        user_intent: "keep",
      },
    });
  });
});
