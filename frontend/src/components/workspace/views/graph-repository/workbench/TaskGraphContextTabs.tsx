"use client";

import type { TaskGraphWorkbenchContext, TaskGraphWorkbenchCounts } from "./taskGraphWorkbenchState";
import { taskGraphWorkbenchTabs } from "./taskGraphWorkbenchState";

export function TaskGraphContextTabs({
  activeContext,
  counts,
  onContextChange,
}: {
  activeContext: TaskGraphWorkbenchContext;
  counts: TaskGraphWorkbenchCounts;
  onContextChange: (context: TaskGraphWorkbenchContext) => void;
}) {
  return (
    <nav className="graph-os-context-tabs" aria-label="任务图工作台上下文">
      {taskGraphWorkbenchTabs.map((item) => {
        const Icon = item.icon;
        const active = activeContext === item.context;
        const count = item.countKey ? counts[item.countKey] : null;
        return (
          <button
            aria-pressed={active}
            className={active ? "graph-os-context-tab graph-os-context-tab--active" : "graph-os-context-tab"}
            key={item.context}
            onClick={() => onContextChange(item.context)}
            type="button"
          >
            <Icon size={16} />
            <span>
              <strong>{item.label}</strong>
              <small>{item.detail}</small>
            </span>
            {count !== null ? <em>{count}</em> : null}
          </button>
        );
      })}
    </nav>
  );
}
