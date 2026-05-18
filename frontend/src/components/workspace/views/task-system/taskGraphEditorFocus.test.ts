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

  it("routes artifact diagnostics to the resource artifact facet", () => {
    const focus = focusForPreflightIssue(issue({
      source: "frontend.preflight.artifact",
      scope: "node",
      target_id: "node.writer",
    }));

    expect(focus).toMatchObject({
      layer: "memory",
      facet: "artifact_context",
      node_id: "node.writer",
    });
  });

  it("routes ledger diagnostics to the risk governance layer", () => {
    const focus = focusForPreflightIssue(issue({
      source: "frontend.preflight.risk_ledger",
      scope: "node",
      target_id: "thread.ledger.1",
    }));

    expect(focus).toMatchObject({
      layer: "risk",
      facet: "ledgers",
      node_id: "thread.ledger.1",
      repository_id: "thread.ledger.1",
    });
  });

  it("routes manual execution diagnostics to node assembly", () => {
    const focus = focusForPreflightIssue(issue({
      source: "frontend.preflight.human_gate",
      scope: "node",
      target_id: "node.review",
    }));

    expect(focus).toMatchObject({
      layer: "agents",
      facet: "manual_execution",
      node_id: "node.review",
    });
  });

  it("routes graph-level human interaction diagnostics to blueprint", () => {
    const focus = focusForPreflightIssue(issue({
      source: "frontend.preflight.human_gate",
      scope: "runtime",
      target_id: "",
    }));

    expect(focus).toMatchObject({
      layer: "blueprint",
      facet: "human_interaction",
    });
  });
});
