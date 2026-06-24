"use client";

import type { TaskGraphBreadcrumbSegment } from "./taskGraphWorkbenchState";

export function TaskGraphBreadcrumb({ segments }: { segments: TaskGraphBreadcrumbSegment[] }) {
  return (
    <ol className="graph-os-breadcrumb" aria-label="任务图对象链路">
      {segments.map((segment) => (
        <li key={`${segment.label}:${segment.value}`}>
          <span>{segment.label}</span>
          <strong>{segment.value}</strong>
        </li>
      ))}
    </ol>
  );
}
