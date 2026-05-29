import { describe, expect, it } from "vitest";

import {
  normalizeDefaultRuntimeMode,
  normalizeRuntimeModes,
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

  it("normalizes runtime modes without deriving execution channels", () => {
    const catalog = runtimeModeCatalogFrom([]);

    expect(normalizeRuntimeModes(["role", "professional"], catalog)).toEqual(["role", "professional"]);
    expect(normalizeRuntimeModes(["readonly_exploration"], catalog)).toEqual(["custom"]);
    expect(normalizeRuntimeModes([], catalog)).toEqual(["custom"]);
  });

  it("keeps custom mode from taking the executable default", () => {
    expect(normalizeDefaultRuntimeMode("custom", ["standard", "custom"])).toBe("standard");
    expect(normalizeDefaultRuntimeMode("", ["role", "professional", "custom"])).toBe("role");
    expect(normalizeDefaultRuntimeMode("custom", ["custom"])).toBe("custom");
  });
});
