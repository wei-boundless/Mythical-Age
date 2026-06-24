"use client";

import type { ReactNode } from "react";
import { RefreshCw } from "lucide-react";

import { TaskGraphBreadcrumb } from "./TaskGraphBreadcrumb";
import { TaskGraphContextTabs } from "./TaskGraphContextTabs";
import type {
  TaskGraphBreadcrumbSegment,
  TaskGraphWorkbenchContext,
  TaskGraphWorkbenchCounts,
} from "./taskGraphWorkbenchState";

export function TaskGraphWorkbenchShell({
  activeContext,
  breadcrumb,
  children,
  counts,
  dirty,
  error,
  notice,
  onContextChange,
  onRefresh,
  saving,
  title,
}: {
  activeContext: TaskGraphWorkbenchContext;
  breadcrumb: TaskGraphBreadcrumbSegment[];
  children: ReactNode;
  counts: TaskGraphWorkbenchCounts;
  dirty: boolean;
  error: string;
  notice: string;
  saving: string;
  title: string;
  onContextChange: (context: TaskGraphWorkbenchContext) => void;
  onRefresh: () => void;
}) {
  return (
    <section className="graph-os-shell" aria-label="任务图操作系统工作台">
      <header className="graph-os-topbar">
        <div className="graph-os-title">
          <span>任务图系统</span>
          <strong>{title || "未命名图任务"}</strong>
        </div>
        <TaskGraphContextTabs activeContext={activeContext} counts={counts} onContextChange={onContextChange} />
        <button className="graph-os-refresh" disabled={saving === "load"} onClick={onRefresh} title="刷新任务图系统" type="button">
          <RefreshCw size={15} />
          <span>刷新</span>
        </button>
      </header>
      <div className="graph-os-meta">
        <TaskGraphBreadcrumb segments={breadcrumb} />
        <div className="graph-os-state-strip" aria-live="polite">
          <span>{dirty ? "草稿有未保存改动" : "当前图已同步"}</span>
          {saving ? <strong>{savingLabel(saving)}</strong> : null}
          {notice ? <strong>{notice}</strong> : null}
        </div>
      </div>
      {error ? <p className="graph-os-error">{error}</p> : null}
      <main className={`graph-os-context-host graph-os-context-host--${activeContext}`}>
        {children}
      </main>
    </section>
  );
}

function savingLabel(saving: string) {
  if (saving === "save") return "保存中";
  if (saving === "publish") return "发布中";
  if (saving === "duplicate") return "复制中";
  if (saving === "instance") return "创建实例中";
  if (saving === "open") return "打开中";
  if (saving === "load") return "加载中";
  return saving;
}
