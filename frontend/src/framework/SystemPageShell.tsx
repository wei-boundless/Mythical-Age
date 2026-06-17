"use client";

import type { ReactNode } from "react";

import { useAppStore } from "@/lib/store";
import type { WorkspaceView } from "@/lib/store/types";
import { cn } from "@/ui/classNames";
import { IconButton } from "@/ui/IconButton";

import { SYSTEM_NAV_ITEMS, TASK_ENVIRONMENT_VIEWS } from "./workspaceViews";

export function SystemPageShell({
  children,
  label,
  view,
}: {
  children: ReactNode;
  label: string;
  view: WorkspaceView;
}) {
  const { activeWorkspaceView, setWorkspaceView } = useAppStore();
  return (
    <main className={`system-page-shell system-page-shell--${view}`}>
      <aside className="system-page-rail" aria-label="系统导航">
        <div className="system-page-rail__mark">系</div>
        <nav>
          {SYSTEM_NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const active = item.view === "chat"
              ? TASK_ENVIRONMENT_VIEWS.has(activeWorkspaceView)
              : activeWorkspaceView === item.view;
            return (
              <IconButton
                aria-pressed={active}
                className={cn("system-page-rail__button", active && "system-page-rail__button--active")}
                key={item.view}
                label={item.label}
                onClick={() => setWorkspaceView(item.view)}
              >
                <Icon size={17} />
              </IconButton>
            );
          })}
        </nav>
      </aside>
      <section className="system-page-content" aria-label={label}>
        {children}
      </section>
    </main>
  );
}
