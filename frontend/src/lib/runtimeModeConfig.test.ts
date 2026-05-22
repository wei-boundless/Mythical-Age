import { describe, expect, it } from "vitest";

import {
  deriveAllowedRuntimeLanes,
  manualRuntimeLanes,
  normalizeRuntimeModesWithLanes,
  runtimeModeCatalogFrom,
} from "./runtimeModeConfig";

describe("runtime mode config", () => {
  it("keeps the catalog fixed to the four supported modes", () => {
    const catalog = runtimeModeCatalogFrom([
      { mode: "role", label: "角色模式覆盖" },
      { mode: "custom.saved", label: "不应出现" },
    ]);

    expect(catalog.map((mode) => mode.mode)).toEqual(["role", "standard", "professional", "custom"]);
    expect(catalog.find((mode) => mode.mode === "role")?.label).toBe("角色模式覆盖");
  });

  it("only preserves manual runtime lanes when custom mode is enabled", () => {
    expect(deriveAllowedRuntimeLanes(["role"], ["readonly_exploration"])).toEqual(["role_interaction"]);
    expect(deriveAllowedRuntimeLanes(["role", "custom"], ["readonly_exploration"])).toEqual([
      "role_interaction",
      "readonly_exploration",
    ]);
    expect(manualRuntimeLanes(["role_interaction", "readonly_exploration"], ["role"])).toEqual([]);
    expect(manualRuntimeLanes(["role_interaction", "readonly_exploration"], ["role", "custom"])).toEqual([
      "readonly_exploration",
    ]);
  });

  it("derives system modes from lanes and falls back to custom for manual lanes", () => {
    expect(normalizeRuntimeModesWithLanes([], ["role_interaction", "professional_task"])).toEqual([
      "role",
      "professional",
    ]);
    expect(normalizeRuntimeModesWithLanes([], ["role_interaction", "readonly_exploration"])).toEqual([
      "role",
      "custom",
    ]);
    expect(normalizeRuntimeModesWithLanes([], ["readonly_exploration"])).toEqual(["custom"]);
  });
});
