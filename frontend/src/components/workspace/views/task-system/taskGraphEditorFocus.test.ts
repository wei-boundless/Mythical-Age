import { describe, expect, it } from "vitest";

import { focusForPreflightIssue, focusTargetLabel } from "./taskGraphEditorFocus";
import type { TaskGraphPreflightIssue } from "./taskGraphPreflight";

function issue(patch: Partial<TaskGraphPreflightIssue>): TaskGraphPreflightIssue {
  return {
    issue_id: "issue.test",
    severity: "warning",
    scope: "edge",
    target_id: "edge.memory.read",
    title: "test",
    detail: "test",
    source: "frontend.preflight.memory_selector",
    ...patch,
  };
}

describe("TaskGraph editor focus", () => {
  it("routes memory selector diagnostics to the memory selector facet", () => {
    const focus = focusForPreflightIssue(issue({}));

    expect(focus).toMatchObject({
      layer: "memory",
      facet: "selector",
      edge_id: "edge.memory.read",
      issue_id: "issue.test",
    });
    expect(focusTargetLabel(focus)).toContain("memory / selector");
  });

  it("routes cognition packet diagnostics to the responsibility page with edge focus", () => {
    const focus = focusForPreflightIssue(issue({
      source: "frontend.preflight.cognition_packet",
      target_id: "edge.handoff",
    }));

    expect(focus).toMatchObject({
      layer: "responsibility",
      facet: "cognition",
      edge_id: "edge.handoff",
    });
  });

  it("routes revision diagnostics to the timeline revision facet", () => {
    const focus = focusForPreflightIssue(issue({
      source: "frontend.preflight.revision_packet",
      target_id: "edge.review.draft",
    }));

    expect(focus).toMatchObject({
      layer: "timeline",
      facet: "revision",
      edge_id: "edge.review.draft",
    });
  });
});
