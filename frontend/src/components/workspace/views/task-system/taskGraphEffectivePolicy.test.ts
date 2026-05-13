import { describe, expect, it } from "vitest";

import { resolveTaskGraphEffectivePolicy } from "./taskGraphEffectivePolicy";

describe("taskGraphEffectivePolicy", () => {
  it("prefers node explicit configuration over graph defaults and profile defaults", () => {
    const result = resolveTaskGraphEffectivePolicy({
      key: "agent_id",
      node: { agent_id: "agent.node" },
      graph: { agent_id: "agent.graph" },
      agentProfile: { agent_id: "agent.profile" },
      systemDefault: "agent.system",
    });

    expect(result.value).toBe("agent.node");
    expect(result.source).toBe("node_explicit");
  });

  it("falls back through edge, phase, graph, role preset, profile, and system default", () => {
    expect(resolveTaskGraphEffectivePolicy({
      key: "wait_policy",
      edge: { wait_policy: "wait_handoff_ack" },
      phase: { wait_policy: "wait_all_upstream_completed" },
      graph: { wait_policy: "fire_and_continue" },
    }).source).toBe("edge_explicit");

    expect(resolveTaskGraphEffectivePolicy({
      key: "wait_policy",
      phase: { wait_policy: "wait_all_upstream_completed" },
      graph: { wait_policy: "fire_and_continue" },
    }).source).toBe("phase_explicit");

    expect(resolveTaskGraphEffectivePolicy({
      key: "wait_policy",
      graph: { wait_policy: "fire_and_continue" },
      agentRolePreset: { wait_policy: "manual_release" },
    }).source).toBe("graph_default");

    expect(resolveTaskGraphEffectivePolicy({
      key: "execution_mode",
      agentRolePreset: { execution_mode: "parallel" },
      agentProfile: { execution_mode: "sync" },
    }).source).toBe("agent_role_preset");

    expect(resolveTaskGraphEffectivePolicy({
      key: "execution_mode",
      agentProfile: { execution_mode: "background" },
      systemDefault: "sync",
    }).source).toBe("agent_profile_default");

    expect(resolveTaskGraphEffectivePolicy({
      key: "execution_mode",
      systemDefault: "sync",
    }).source).toBe("system_default");
  });

  it("reads nested metadata values for prompt semantics", () => {
    const result = resolveTaskGraphEffectivePolicy({
      key: "role_prompt",
      node: {
        metadata: {
          role_prompt: "你是一名审核员。你只负责裁决是否通过。",
        },
      },
      systemDefault: "未配置",
    });

    expect(result.value).toContain("你是一名审核员");
    expect(result.source).toBe("node_explicit");
  });
});
