"use client";

import { useEffect, useState, type CSSProperties, type PointerEvent, type ReactNode } from "react";
import { AlertTriangle, CheckCircle2, RefreshCw } from "lucide-react";

import { Notice } from "@/ui/Notice";

import { TaskSystemToolbarButton as ToolbarButton } from "./TaskSystemWorkbenchUi";

export type TaskSystemShellNavItem<T extends string> = {
  value: T;
  label: string;
  meta: string;
  detail?: string;
};

const TASK_SYSTEM_SIDEBAR_WIDTH_KEY = "taskSystemShell.sidebarWidth";

function clampSidebarWidth(value: number) {
  return Math.min(560, Math.max(260, value));
}

export function TaskSystemShell<T extends string>({
  activeLayer,
  children,
  contextSlot,
  error,
  layerSlot,
  navItems,
  notice,
  onRefresh,
  onSelectLayer,
  path,
  title,
}: {
  activeLayer: T;
  children: ReactNode;
  contextSlot?: ReactNode;
  error?: string;
  layerSlot?: ReactNode;
  navItems: Array<TaskSystemShellNavItem<T>>;
  notice?: string;
  onRefresh: () => void;
  onSelectLayer: (layer: T) => void;
  path: string;
  title: string;
}) {
  const [sidebarWidth, setSidebarWidth] = useState(320);

  useEffect(() => {
    const storedWidth = Number(window.localStorage.getItem(TASK_SYSTEM_SIDEBAR_WIDTH_KEY));
    if (Number.isFinite(storedWidth) && storedWidth > 0) {
      setSidebarWidth(clampSidebarWidth(storedWidth));
    }
  }, []);

  useEffect(() => {
    window.localStorage.setItem(TASK_SYSTEM_SIDEBAR_WIDTH_KEY, String(sidebarWidth));
  }, [sidebarWidth]);

  function startSidebarResize(event: PointerEvent<HTMLDivElement>) {
    event.preventDefault();
    const handle = event.currentTarget;
    const pointerId = event.pointerId;
    const startX = event.clientX;
    const startWidth = sidebarWidth;
    handle.setPointerCapture(pointerId);
    const move = (moveEvent: globalThis.PointerEvent) => {
      setSidebarWidth(clampSidebarWidth(startWidth + moveEvent.clientX - startX));
    };
    const up = () => {
      handle.releasePointerCapture(pointerId);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

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
    <div className="workspace-view boundary-console task-system-boundary task-system-boundary--management">
      <header className="task-system-database-header">
        <div>
          <span>任务系统</span>
          <h2>{title}</h2>
          <p>{path}</p>
        </div>
        <div className="task-system-database-header__actions">
          <ToolbarButton onClick={onRefresh}><RefreshCw size={15} />刷新</ToolbarButton>
        </div>
      </header>

      {error ? <Notice icon={<AlertTriangle size={16} />} tone="error">{error}</Notice> : null}
      {notice ? <Notice icon={<CheckCircle2 size={16} />}>{notice}</Notice> : null}

      <section
        className="task-system-database-layout task-system-database-layout--resizable"
        style={{ "--task-system-sidebar-width": `${sidebarWidth}px` } as CSSProperties}
      >
        <aside className="task-system-database-sidebar" aria-label="任务系统数据库导航">
            <header className="task-system-workspace-head">
              <div>
                <strong>任务系统</strong>
                <span>对象导航</span>
              </div>
            </header>
            {contextSlot ? (
              <section className="task-system-domain-context">
                {contextSlot}
              </section>
            ) : null}
            <nav className="task-system-object-switcher" aria-label="任务系统对象导航">
              {layerSlot ?? fallbackLayerSlot}
            </nav>
          </aside>
          <div
            aria-label="调整任务系统左侧栏宽度"
            className="task-system-sidebar-resize-handle"
            onPointerDown={startSidebarResize}
            role="separator"
          />
          <main className="task-system-database-workspace">
            {children}
          </main>
      </section>
    </div>
  );
}
