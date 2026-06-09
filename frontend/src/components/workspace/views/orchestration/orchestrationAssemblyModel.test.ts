import { describe, expect, it } from "vitest";

import type { ToolPackageDefinition } from "@/lib/api";

import {
  agentDirectorySection,
  effectiveAllowedOperations,
  groupDraftFrom,
  groupPayloadFromDraft,
  normalizeSubagentPolicy,
  runtimeDraftFrom,
} from "./orchestrationAssemblyModel";

function toolPackage(partial: Partial<ToolPackageDefinition>): ToolPackageDefinition {
  return {
    package_id: partial.package_id ?? "pkg.files",
    title: partial.title ?? "文件工具",
    description: partial.description ?? "",
    category: partial.category ?? "file",
    operation_ids: partial.operation_ids ?? ["op.read_file", "op.write_file"],
    risk_level: partial.risk_level ?? "medium",
    managed: partial.managed ?? true,
    default_enabled: partial.default_enabled ?? false,
    tags: partial.tags ?? [],
    metadata: partial.metadata,
  };
}

describe("orchestration assembly model", () => {
  it("separates builtin specialist agents from builtin system agents", () => {
    expect(agentDirectorySection({ agent_category: "builtin_agent", metadata: { role: "worker_specialist" } })).toBe("builtin_specialist_agent");
    expect(agentDirectorySection({ agent_category: "builtin_agent", metadata: { role: "memory_management" } })).toBe("builtin_system_agent");
    expect(agentDirectorySection({ agent_category: "custom_agent" })).toBe("custom_agent");
  });

  it("normalizes subagent policy so enabled requires explicit targets", () => {
    expect(normalizeSubagentPolicy({ enabled: true, allowed_subagent_ids: [] }).enabled).toBe(false);
    expect(normalizeSubagentPolicy({ enabled: true, allowed_subagent_ids: ["agent:worker"] }).enabled).toBe(true);
  });

  it("builds runtime draft defaults from agent id and strips stale model base_url", () => {
    const draft = runtimeDraftFrom("agent:test", {
      model_profile: {
        provider: "deepseek",
        model: "deepseek-chat",
        base_url: "legacy",
      } as never,
    });

    expect(draft.agent_profile_id).toBe("agent_test_runtime");
    expect(draft.allowed_operations).toEqual(["op.model_response"]);
    expect(draft.model_profile?.provider).toBe("deepseek");
    expect("base_url" in (draft.model_profile ?? {})).toBe(false);
  });

  it("derives effective operations from selected tool packages and blocks exclusions", () => {
    const operations = effectiveAllowedOperations({
      allowed_tool_packages: [{
        package_id: "pkg.files",
        enabled: true,
        include_operations: [],
        exclude_operations: ["op.write_file"],
      }],
      extra_allowed_operations: ["op.shell"],
      blocked_operations: ["op.shell"],
    }, [toolPackage({ package_id: "pkg.files", operation_ids: ["op.read_file", "op.write_file"] })]);

    expect(operations).toEqual(["op.model_response", "op.read_file"]);
  });

  it("keeps group member text as the editable representation", () => {
    const draft = groupDraftFrom({
      group_id: "group.custom.review",
      title: "审查组",
      group_kind: "review_team",
      coordinator_agent_id: "agent:reviewer",
      member_agent_ids: ["agent:a", "agent:b", "agent:a"],
      description: "",
      lifecycle_state: "enabled",
    });

    expect(draft.member_agent_ids_text).toBe("agent:a\nagent:b");
    expect(groupPayloadFromDraft({ ...draft, member_agent_ids_text: "agent:a\nagent:c" }).member_agent_ids).toEqual(["agent:a", "agent:c"]);
  });
});
