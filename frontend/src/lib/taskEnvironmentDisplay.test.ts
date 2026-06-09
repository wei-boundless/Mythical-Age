import { describe, expect, it } from "vitest";

import { taskEnvironmentDisplayName } from "./taskEnvironmentDisplay";

describe("taskEnvironmentDisplayName", () => {
  it("prefers the registry label over built-in fallback labels", () => {
    expect(taskEnvironmentDisplayName("env.coding.vibe_workspace", "Registry Coding Name")).toBe("Registry Coding Name");
    expect(taskEnvironmentDisplayName("env.office.file_search", "Registry Office Name")).toBe("Registry Office Name");
    expect(taskEnvironmentDisplayName("env.general.workspace", "Registry General Name")).toBe("Registry General Name");
  });

  it("uses Chinese fallback labels for built-in task environments when the registry label is missing", () => {
    expect(taskEnvironmentDisplayName("env.coding.vibe_workspace")).toBe("Vibe 编码工作区");
    expect(taskEnvironmentDisplayName("env.office.file_search")).toBe("轻量办公文件检索");
    expect(taskEnvironmentDisplayName("env.general.workspace")).toBe("通用工作区");
  });

  it("keeps custom registry labels when there is no known mapping", () => {
    expect(taskEnvironmentDisplayName("env.custom.workspace", "自定义环境")).toBe("自定义环境");
  });
});
