"use client";

import { Check, ChevronDown, Plus } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { TaskSystemToolbarButton } from "@/components/workspace/views/task-system/TaskSystemWorkbenchUi";
import {
  taskEnvironmentDisplayTitle,
  taskEnvironmentLoadSummary,
  taskEnvironmentPurpose,
  taskEnvironmentScope,
  taskEnvironmentScopeLabel,
  userVisibleEnvironmentItems,
  type EnvironmentScope,
  type TaskEnvironmentItem,
} from "./environmentPresentation";

const SCOPE_ORDER: EnvironmentScope[] = ["workspace", "builtin_template", "other"];

export function EnvironmentContextPicker({
  environmentItems,
  onCreate,
  onSelectEnvironment,
  selectedEnvironmentId,
}: {
  environmentItems: TaskEnvironmentItem[];
  onCreate: () => void;
  onSelectEnvironment: (environmentId: string) => void;
  selectedEnvironmentId: string;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const visibleItems = useMemo(
    () => userVisibleEnvironmentItems(environmentItems, selectedEnvironmentId),
    [environmentItems, selectedEnvironmentId],
  );
  const selectedItem = visibleItems.find((item) => item.record.environment_id === selectedEnvironmentId)
    ?? visibleItems[0]
    ?? null;
  const selectedScope = taskEnvironmentScope(selectedItem);

  useEffect(() => {
    if (!open) return;
    const closeOnOutside = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  const groupedItems = useMemo(() => {
    return SCOPE_ORDER.map((scope) => ({
      scope,
      items: visibleItems.filter((item) => taskEnvironmentScope(item) === scope),
    })).filter((group) => group.items.length);
  }, [visibleItems]);

  const summary = useMemo(() => {
    const counts = new Map<EnvironmentScope, number>();
    for (const item of visibleItems) {
      const scope = taskEnvironmentScope(item);
      counts.set(scope, (counts.get(scope) ?? 0) + 1);
    }
    const parts = [
      `${counts.get("workspace") ?? 0} 个我的环境`,
      `${counts.get("builtin_template") ?? 0} 个内置方案`,
    ];
    return parts.join(" / ");
  }, [visibleItems]);

  return (
    <div className="task-system-context-stack">
      <section className="task-system-project-selector task-system-project-selector--root" aria-label="当前运行环境">
        <div className="task-system-environment-picker" ref={rootRef}>
          <span>当前运行环境</span>
          <button
            aria-expanded={open}
            className="task-system-environment-trigger"
            disabled={!visibleItems.length}
            onClick={() => setOpen((current) => !current)}
            type="button"
          >
            <span className={`task-system-source-badge task-system-source-badge--${selectedScope}`}>
              {taskEnvironmentScopeLabel(selectedScope)}
            </span>
            <strong>{selectedItem ? taskEnvironmentDisplayTitle(selectedItem) : "暂无可用环境"}</strong>
            <small>{selectedItem ? taskEnvironmentPurpose(selectedItem) : summary}</small>
            <ChevronDown size={15} />
          </button>
          {open ? (
            <div className="task-system-environment-menu" role="listbox" aria-label="可用运行环境">
              {groupedItems.map((group) => (
                <section className="task-system-environment-menu__group" key={group.scope}>
                  <header>
                    <strong>{taskEnvironmentScopeLabel(group.scope)}</strong>
                    <span>{group.items.length}</span>
                  </header>
                  {group.items.map((item) => {
                    const active = item.record.environment_id === selectedEnvironmentId;
                    const scope = taskEnvironmentScope(item);
                    return (
                      <button
                        aria-selected={active}
                        className={active ? "task-system-environment-option task-system-environment-option--active" : "task-system-environment-option"}
                        key={item.record.environment_id}
                        onClick={() => {
                          onSelectEnvironment(item.record.environment_id);
                          setOpen(false);
                        }}
                        role="option"
                        type="button"
                      >
                        <span className={`task-system-source-badge task-system-source-badge--${scope}`}>
                          {taskEnvironmentScopeLabel(scope)}
                        </span>
                        <strong>{taskEnvironmentDisplayTitle(item)}</strong>
                        <small>{taskEnvironmentPurpose(item)}</small>
                        {active ? <Check size={15} /> : null}
                      </button>
                    );
                  })}
                </section>
              ))}
              {!groupedItems.length ? <div className="task-system-environment-menu__empty">暂无可用运行环境</div> : null}
            </div>
          ) : null}
        </div>
        <small>{selectedItem ? taskEnvironmentLoadSummary(selectedItem) : summary}</small>
        <TaskSystemToolbarButton onClick={onCreate}><Plus size={15} />新环境</TaskSystemToolbarButton>
      </section>
    </div>
  );
}
