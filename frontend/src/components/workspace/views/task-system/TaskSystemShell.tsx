"use client";

import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, RefreshCw } from "lucide-react";

import { TaskSystemToolbarButton as ToolbarButton } from "./TaskSystemWorkbenchUi";

export type TaskSystemShellLayer = "management" | "editor";

export type TaskSystemShellNavItem<T extends string> = {
  value: T;
  label: string;
  meta: string;
  detail?: string;
};

export function TaskSystemShell<T extends string>({
  activeLayer,
  children,
  contextSlot,
  error,
  layerSlot,
  mode,
  navItems,
  notice,
  onRefresh,
  onSelectLayer,
  onBackToGraphs,
  path,
  title,
}: {
  activeLayer: T;
  children: ReactNode;
  contextSlot?: ReactNode;
  error?: string;
  layerSlot?: ReactNode;
  mode: TaskSystemShellLayer;
  navItems: Array<TaskSystemShellNavItem<T>>;
  notice?: string;
  onRefresh: () => void;
  onSelectLayer: (layer: T) => void;
  onBackToGraphs?: () => void;
  path: string;
  title: string;
}) {
  return (
    <div className={`workspace-view boundary-console task-system-boundary task-system-boundary--${mode}`}>
      <header className={mode === "editor" ? "boundary-hero task-system-boundary__studio-hero" : "boundary-hero"}>
        <div>
          <span>{mode === "editor" ? "TaskGraph Studio" : "TaskSystem Console"}</span>
          <h2>{title}</h2>
          <p>{path}</p>
        </div>
        <div className="boundary-actions">
          {mode === "editor" && onBackToGraphs ? (
            <ToolbarButton onClick={onBackToGraphs}>返回任务图</ToolbarButton>
          ) : null}
          <ToolbarButton onClick={onRefresh}><RefreshCw size={15} />刷新</ToolbarButton>
        </div>
      </header>

      {error ? <div className="boundary-notice boundary-notice--error"><AlertTriangle size={16} />{error}</div> : null}
      {notice ? <div className="boundary-notice"><CheckCircle2 size={16} />{notice}</div> : null}

      {mode === "editor" ? (
        <section className="task-system-boundary__editor">
          {children}
        </section>
      ) : (
        <section className="task-system-boundary__management">
          {contextSlot ? (
            <section className="task-system-domain-context">
              {contextSlot}
            </section>
          ) : null}
          <nav className="task-system-object-switcher" aria-label="任务系统对象工作区">
            {layerSlot ?? (
              <>
                {navItems.map((item) => (
                <button
                  className={activeLayer === item.value ? "boundary-list-row boundary-list-row--active task-system-boundary__object-card" : "boundary-list-row task-system-boundary__object-card"}
                  key={item.value}
                  onClick={() => onSelectLayer(item.value)}
                  type="button"
                >
                  <strong>{item.label}</strong>
                  <span>{item.meta}</span>
                  {item.detail ? <small>{item.detail}</small> : null}
                </button>
                ))}
              </>
            )}
          </nav>
          <main className="boundary-main task-system-boundary__object-workspace">
            {children}
          </main>
        </section>
      )}
    </div>
  );
}
