import { describe, expect, it } from "vitest";

import { formatRuntimeSupportOption, runtimeOptionIsUnsupported, runtimeSupportFor } from "./taskGraphRuntimeSupport";

describe("taskGraphRuntimeSupport", () => {
  it("classifies edge handoff policies by runtime support", () => {
    expect(runtimeSupportFor("wait_policy", "wait_handoff_ack")).toBe("supported");
    expect(runtimeSupportFor("wait_policy", "wait_all_upstream_completed")).toBe("partial");
    expect(runtimeSupportFor("wait_policy", "manual_release")).toBe("unsupported");
    expect(runtimeOptionIsUnsupported("wait_policy", "manual_release")).toBe(true);
  });

  it("matches temporal support labels exposed by the runtime compiler", () => {
    expect(runtimeSupportFor("trigger_timing", "after_source_success")).toBe("supported");
    expect(runtimeSupportFor("visibility_timing", "same_clock")).toBe("partial");
    expect(runtimeSupportFor("acknowledgement_timing", "ack_before_phase_exit")).toBe("partial");
    expect(runtimeSupportFor("dependency_gate", "handoff_ack")).toBe("supported");
    expect(runtimeSupportFor("phase_timing", "revision_return")).toBe("partial");
  });

  it("adds a human-readable support suffix to select options", () => {
    expect(formatRuntimeSupportOption("wait_policy")("wait_handoff_ack")).toContain("运行支持");
    expect(formatRuntimeSupportOption("wait_policy")("fire_and_continue")).toContain("未支持");
  });
});
