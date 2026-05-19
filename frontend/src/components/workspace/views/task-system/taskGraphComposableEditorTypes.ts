import type { TaskGraphPreflightIssue } from "./taskGraphPreflight";

export type TaskGraphComposableSubject =
  | { kind: "graph"; graph_id: string }
  | { kind: "unit"; unit_id: string }
  | { kind: "interface"; interface_id: string; unit_id?: string }
  | { kind: "port"; interface_id: string; unit_id: string; port_id: string; direction: string }
  | { kind: "port_edge"; edge_id: string }
  | { kind: "timeline_block"; block_id: string }
  | { kind: "nested_runtime"; plan_id: string; unit_id?: string }
  | { kind: "issue"; issue: TaskGraphPreflightIssue };

export function taskGraphComposableSubjectKey(subject: TaskGraphComposableSubject) {
  if (subject.kind === "graph") return `graph:${subject.graph_id}`;
  if (subject.kind === "unit") return `unit:${subject.unit_id}`;
  if (subject.kind === "interface") return `interface:${subject.interface_id}`;
  if (subject.kind === "port") return `port:${subject.interface_id}:${subject.direction}:${subject.port_id}`;
  if (subject.kind === "port_edge") return `port_edge:${subject.edge_id}`;
  if (subject.kind === "timeline_block") return `timeline_block:${subject.block_id}`;
  if (subject.kind === "nested_runtime") return `nested_runtime:${subject.plan_id}`;
  return `issue:${subject.issue.issue_id}`;
}

export function taskGraphComposableSubjectFacet(subject: TaskGraphComposableSubject) {
  if (subject.kind === "port_edge") return "connections";
  if (subject.kind === "interface" || subject.kind === "port") return "interfaces";
  if (subject.kind === "nested_runtime") return "nested_runtime";
  if (subject.kind === "timeline_block") return "stitching";
  return "units";
}

