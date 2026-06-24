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
  const resourceTabs = taskGraphWorkbenchTabs.filter((item) => item.kind === "resource");
  const modeTabs = taskGraphWorkbenchTabs.filter((item) => item.kind === "mode");
  const activeMode = activeContext === "monitor" ? "monitor" : "editor";
  return (
    <div className="graph-os-context-tabs" aria-label="任务图工作台上下文">
      <nav className="graph-os-context-tabs__group graph-os-context-tabs__group--resources" aria-label="任务图资源入口">
        {resourceTabs.map((item) => (
          <TaskGraphContextTab
            active={activeContext === item.context}
            count={item.countKey ? counts[item.countKey] : null}
            item={item}
            key={item.context}
            onContextChange={onContextChange}
          />
        ))}
      </nav>
      <nav className="graph-os-context-tabs__group graph-os-context-tabs__group--modes" aria-label="任务图工作模式">
        {modeTabs.map((item) => (
          <TaskGraphContextTab
            active={activeMode === item.context}
            count={item.countKey ? counts[item.countKey] : null}
            item={item}
            key={item.context}
            onContextChange={onContextChange}
          />
        ))}
      </nav>
    </div>
  );
}

function TaskGraphContextTab({
  active,
  count,
  item,
  onContextChange,
}: {
  active: boolean;
  count: number | null;
  item: (typeof taskGraphWorkbenchTabs)[number];
  onContextChange: (context: TaskGraphWorkbenchContext) => void;
}) {
  const Icon = item.icon;
  return (
    <button
      aria-pressed={active}
      className={[
        "graph-os-context-tab",
        `graph-os-context-tab--${item.kind}`,
        active ? "graph-os-context-tab--active" : "",
      ].filter(Boolean).join(" ")}
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
}
