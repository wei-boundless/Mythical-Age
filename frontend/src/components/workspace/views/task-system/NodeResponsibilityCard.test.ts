import { describe, expect, it } from "vitest";

import { buildNodeResponsibilityPrompt } from "./NodeResponsibilityCard";

describe("buildNodeResponsibilityPrompt", () => {
  it("builds responsibility-language prompts from card fields", () => {
    const prompt = buildNodeResponsibilityPrompt({
      role_identity: "你是一名世界观审核员。",
      responsibility_scope: "评审设定完整性和一致性。",
      responsibility_exclusions: "扩写剧情或替作者创作。",
      definition_of_done: "给出通过或返修裁决，并说明理由。",
    });

    expect(prompt).toContain("你是一名世界观审核员");
    expect(prompt).toContain("你只负责评审设定完整性和一致性");
    expect(prompt).toContain("你不负责扩写剧情或替作者创作");
    expect(prompt).toContain("你必须给出通过或返修裁决");
    expect(prompt).not.toContain("runtime 节点");
  });
});
