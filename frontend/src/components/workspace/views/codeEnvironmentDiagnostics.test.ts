import { describe, expect, it } from "vitest";

import { codeEnvironmentDiagnosticsText } from "./codeEnvironmentDiagnostics";

describe("codeEnvironmentDiagnosticsText", () => {
  it("formats structured diagnostics instead of leaking object strings", () => {
    const text = codeEnvironmentDiagnosticsText([
      {
        level: "info",
        code: "pi_sidecar_optional",
        message: "Pi sidecar is disabled; professional code tasks continue through the local runtime.",
        path: null,
      },
      {
        level: "warning",
        code: "pi_cli_not_built",
        message: "Pi RPC CLI build output is missing. Build Pi before starting the sidecar.",
        path: "D:\\AI应用\\pi-main\\packages\\coding-agent\\dist\\cli.js",
      },
    ]);

    expect(text).toContain("pi_sidecar_optional");
    expect(text).toContain("Pi sidecar is disabled");
    expect(text).toContain("pi_cli_not_built");
    expect(text).toContain("D:\\AI应用\\pi-main\\packages\\coding-agent\\dist\\cli.js");
    expect(text).not.toContain("[object Object]");
  });

  it("keeps primitive and unknown diagnostic values readable", () => {
    expect(codeEnvironmentDiagnosticsText(["ready", { detail: "missing cli" }, 3])).toBe("ready；missing cli；3");
  });
});
