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
  const fallbackLayerSlot = (
    <div className="task-system-object-table" aria-label="任务系统对象目录">
      <div className="task-system-object-table__head" aria-hidden="true">
        <span>对象</span>
        <span>记录</span>
        <span>说明</span>
        <span>状态</span>
      </div>
      {navItems.map((item) => (
        <button
          aria-current={activeLayer === item.value ? "page" : undefined}
          className={activeLayer === item.value ? "task-system-object-row task-system-object-row--active" : "task-system-object-row"}
          key={item.value}
          onClick={() => onSelectLayer(item.value)}
          type="button"
        >
          <strong>{item.label}</strong>
          <span className="task-system-object-row__meta">{item.meta}</span>
          <small>{item.detail}</small>
          <em>{activeLayer === item.value ? "当前" : "可配置"}</em>
        </button>
      ))}
    </div>
  );

  return (
    <div className={`workspace-view boundary-console task-system-boundary task-system-boundary--${mode}`}>
      <header className={mode === "editor" ? "task-system-database-header task-system-database-header--editor" : "task-system-database-header"}>
        <div>
          <span>{mode === "editor" ? "任务图编辑器" : "任务系统"}</span>
          <h2>{title}</h2>
          <p>{path}</p>
        </div>
        <div className="task-system-database-header__actions">
          {mode === "editor" && onBackToGraphs ? (
            <ToolbarButton onClick={onBackToGraphs}>返回任务图库</ToolbarButton>
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
        <section className="task-system-database-layout">
          <aside className="task-system-database-sidebar" aria-label="任务系统数据库导航">
            {contextSlot ? (
              <section className="task-system-domain-context">
                {contextSlot}
              </section>
            ) : null}
            <nav className="task-system-object-switcher" aria-label="任务系统对象工作区">
              {layerSlot ?? fallbackLayerSlot}
            </nav>
          </aside>
          <main className="task-system-database-workspace">
            {children}
          </main>
        </section>
      )}
    </div>
  );
}
