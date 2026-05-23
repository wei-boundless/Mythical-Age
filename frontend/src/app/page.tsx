"use client";

import { useEffect, useState, type ReactNode } from "react";
import { Database, LayoutGrid, MessageSquare, Network, Settings, Workflow } from "lucide-react";

import { AppProvider, useAppStore } from "@/lib/store";
import { lazy, Suspense } from "react";
import { CenterWorkspaceView } from "@/components/workspace/views/center/CenterWorkspaceView";
import { ConfirmDialogProvider } from "@/components/layout/ConfirmDialogProvider";
import { WorkbenchShell } from "@/components/layout/WorkbenchShell";
import { TaskGraphRunInteractionDock } from "@/components/workspace/views/task-system/TaskGraphRunInteractionDock";
import type { WorkspaceView } from "@/lib/store/types";

const CapabilitySystemView = lazy(() => import("@/components/workspace/views/CapabilitySystemView").then((module) => ({ default: module.CapabilitySystemView })));
const MemoryView = lazy(() => import("@/components/workspace/views/MemoryView").then((module) => ({ default: module.MemoryView })));
const OrchestrationView = lazy(() => import("@/components/workspace/views/OrchestrationView").then((module) => ({ default: module.OrchestrationView })));
const PlaygroundView = lazy(() => import("@/components/workspace/views/PlaygroundView").then((module) => ({ default: module.PlaygroundView })));
const SystemConfigView = lazy(() => import("@/components/workspace/views/SystemConfigView").then((module) => ({ default: module.SystemConfigView })));
const SystemFrameworkView = lazy(() => import("@/components/workspace/views/SystemFrameworkView").then((module) => ({ default: module.SystemFrameworkView })));
const TaskSystemView = lazy(() => import("@/components/workspace/views/TaskSystemView").then((module) => ({ default: module.TaskSystemView })));

function LazyView({ children }: { children: ReactNode }) {
  return (
    <Suspense fallback={<div className="boundary-empty boundary-empty--large">正在加载工作台...</div>}>
      {children}
    </Suspense>
  );
}

const WORKSPACE_QUERY_VIEWS = new Set<WorkspaceView>([
  "chat",
  "memory",
  "playground",
  "task-system",
  "orchestration",
  "capability-system",
  "system-framework",
  "system-config",
]);

const WORKSPACE_TONES = new Set(["water", "leaf", "gold", "ember", "lumen"]);

const SYSTEM_NAV_ITEMS: Array<{ view: WorkspaceView; label: string; icon: typeof MessageSquare }> = [
  { view: "chat", label: "会话", icon: MessageSquare },
  { view: "memory", label: "记忆", icon: Database },
  { view: "task-system", label: "任务", icon: Workflow },
  { view: "orchestration", label: "编排", icon: Network },
  { view: "capability-system", label: "能力", icon: LayoutGrid },
  { view: "system-config", label: "配置", icon: Settings },
];

function SystemPageShell({
  children,
  label,
}: {
  children: ReactNode;
  label: string;
}) {
  const { activeWorkspaceView, setWorkspaceView } = useAppStore();
  return (
    <main className="system-page-shell">
      <aside className="system-page-rail" aria-label="系统导航">
        <div className="system-page-rail__mark">系</div>
        <nav>
          {SYSTEM_NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const active = activeWorkspaceView === item.view;
            return (
              <button
                aria-label={item.label}
                aria-pressed={active}
                className={active ? "system-page-rail__button system-page-rail__button--active" : "system-page-rail__button"}
                key={item.view}
                onClick={() => setWorkspaceView(item.view)}
                title={item.label}
                type="button"
              >
                <Icon size={17} />
              </button>
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

function Workspace() {
  const {
    activeWorkspaceView,
    setWorkspaceView,
    clearTaskGraphMonitorRun,
    evaluateBoundTaskGraphMonitor,
    setTaskGraphRunInteractionOpen,
    submitTaskGraphMonitorDecision,
    taskGraphBoundRunMonitor,
    taskGraphMonitorActionLoading,
    taskGraphMonitorBinding,
    taskGraphMonitorDecision,
    taskGraphMonitorError,
    taskGraphMonitorLoading,
    taskGraphRunInteractionOpen,
  } = useAppStore();
  const [forcedPlayground, setForcedPlayground] = useState(false);

  useEffect(() => {
    window.localStorage.removeItem("chatVisualMode");
    delete document.documentElement.dataset.soul;
    const storedTone = window.localStorage.getItem("workspaceTone");
    if (storedTone && WORKSPACE_TONES.has(storedTone)) {
      document.documentElement.dataset.workspaceTone = storedTone;
    } else {
      delete document.documentElement.dataset.workspaceTone;
    }
    const view = new URLSearchParams(window.location.search).get("view");
    if (view && WORKSPACE_QUERY_VIEWS.has(view as WorkspaceView)) {
      setWorkspaceView(view as WorkspaceView);
      setForcedPlayground(view === "playground");
    }
  }, [setWorkspaceView]);

  useEffect(() => {
    if (
      activeWorkspaceView !== "chat"
      && activeWorkspaceView !== "memory"
      && activeWorkspaceView !== "playground"
      && activeWorkspaceView !== "task-system"
      && activeWorkspaceView !== "capability-system"
      && activeWorkspaceView !== "orchestration"
      && activeWorkspaceView !== "system-framework"
      && activeWorkspaceView !== "system-config"
    ) {
      setWorkspaceView("chat");
    }
  }, [activeWorkspaceView, setWorkspaceView]);

  function returnToWorkspace() {
    setForcedPlayground(false);
    setWorkspaceView("chat");
    const url = new URL(window.location.href);
    url.searchParams.delete("view");
    window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
  }

  const taskGraphRunInteractionDock = (
    <TaskGraphRunInteractionDock
      actionLoading={taskGraphMonitorActionLoading}
      binding={taskGraphMonitorBinding}
      decision={taskGraphMonitorDecision}
      error={taskGraphMonitorError}
      monitor={taskGraphBoundRunMonitor}
      monitorLoading={taskGraphMonitorLoading}
      onClear={clearTaskGraphMonitorRun}
      onEvaluate={() => void evaluateBoundTaskGraphMonitor()}
      onOpenChange={setTaskGraphRunInteractionOpen}
      onSubmitDecision={(decision, controlAction, resumePayload) => void submitTaskGraphMonitorDecision(decision, controlAction, resumePayload)}
      open={taskGraphRunInteractionOpen}
    />
  );

  const shouldShowTaskGraphRunInteractionDock =
    activeWorkspaceView === "chat"
    || activeWorkspaceView === "system-framework"
    || activeWorkspaceView === "orchestration"
    || activeWorkspaceView === "task-system"
    || activeWorkspaceView === "capability-system";

  let content: ReactNode;

  if (activeWorkspaceView === "system-framework") {
    content = (
      <main className="system-framework-stage min-h-screen">
        <LazyView><SystemFrameworkView /></LazyView>
      </main>
    );
  } else if (activeWorkspaceView === "orchestration") {
    content = (
      <SystemPageShell label="编排系统">
        <LazyView><OrchestrationView /></LazyView>
      </SystemPageShell>
    );
  } else if (activeWorkspaceView === "task-system") {
    content = (
      <SystemPageShell label="任务系统">
        <LazyView><TaskSystemView /></LazyView>
      </SystemPageShell>
    );
  } else if (activeWorkspaceView === "memory") {
    content = (
      <SystemPageShell label="长期记忆">
        <LazyView><MemoryView /></LazyView>
      </SystemPageShell>
    );
  } else if (activeWorkspaceView === "capability-system") {
    content = (
      <SystemPageShell label="能力系统">
        <LazyView><CapabilitySystemView /></LazyView>
      </SystemPageShell>
    );
  } else if (activeWorkspaceView === "system-config") {
    content = (
      <SystemPageShell label="配置">
        <LazyView><SystemConfigView /></LazyView>
      </SystemPageShell>
    );
  } else if (forcedPlayground || activeWorkspaceView === "playground") {
    content = <LazyView><PlaygroundView onReturnToWorkspace={returnToWorkspace} /></LazyView>;
  } else {
    content = (
      <SystemPageShell label="主会话">
        <WorkbenchShell>
          <section className="workbench-view-host workbench-view-host--chat" aria-label="主会话">
            <CenterWorkspaceView />
          </section>
        </WorkbenchShell>
      </SystemPageShell>
    );
  }

  return (
    <>
      {content}
      {shouldShowTaskGraphRunInteractionDock ? taskGraphRunInteractionDock : null}
    </>
  );
}

export default function Page() {
  return (
    <AppProvider>
      <ConfirmDialogProvider>
        <Workspace />
      </ConfirmDialogProvider>
    </AppProvider>
  );
}
