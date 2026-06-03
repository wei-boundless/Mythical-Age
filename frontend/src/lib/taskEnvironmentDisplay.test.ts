import { describe, expect, it } from "vitest";

import { taskEnvironmentDisplayName } from "./taskEnvironmentDisplay";

describe("taskEnvironmentDisplayName", () => {
  it("uses Chinese labels for built-in task environments", () => {
    expect(taskEnvironmentDisplayName("env.coding.vibe_workspace", "Vibe Coding Workspace")).toBe("Vibe 编码工作区");
    expect(taskEnvironmentDisplayName("env.creation.writing", "Creative Writing")).toBe("创意写作");
    expect(taskEnvironmentDisplayName("env.development.sandbox", "Development Sandbox")).toBe("开发沙盒");
    expect(taskEnvironmentDisplayName("env.general.workspace", "General Workspace")).toBe("通用工作区");
  });

  it("keeps custom registry labels when there is no known mapping", () => {
    expect(taskEnvironmentDisplayName("env.custom.workspace", "自定义环境")).toBe("自定义环境");
  });
});
