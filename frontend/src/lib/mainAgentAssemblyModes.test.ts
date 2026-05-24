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

  it("adds the professional execution strategy only for professional mode", () => {
    const professional = buildMainAgentTaskSelection(null, "professional");
    const standard = buildMainAgentTaskSelection(null, "standard");

    expect(professional?.runtime_assembly_hint).toMatchObject({
      execution_strategy: "professional_task_run",
    });
    expect(professional?.intent_decision).toMatchObject({
      execution_strategy: "professional_task_run",
    });
    expect(standard?.runtime_assembly_hint).not.toMatchObject({
      execution_strategy: "professional_task_run",
    });
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

  it("keeps task selection fields while making the mode profile authoritative", () => {
    const payload = buildMainAgentTaskSelection(
      {
        selected_task_id: "task.dev.light_web_game",
        label: "小游戏",
        runtime_lane: "old_lane",
        mode_policy: { runtime_lane: "old_lane", custom: true },
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
      mode_policy: {
        custom: true,
        interaction_mode: "standard_mode",
        runtime_lane: "standard_task",
      },
    });
  });
});
