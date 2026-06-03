"use client";

import { useEffect, useState, type ReactNode } from "react";
import { Database, HeartPulse, LayoutGrid, MessageSquare, Network, Settings, Workflow } from "lucide-react";

import { AppProvider, useAppStore } from "@/lib/store";
import { lazy, Suspense } from "react";
import { CenterWorkspaceView } from "@/components/workspace/views/center/CenterWorkspaceView";
import { ConfirmDialogProvider } from "@/components/layout/ConfirmDialogProvider";
import { CodeEnvironmentView } from "@/components/workspace/views/CodeEnvironmentView";
import { WorkbenchShell } from "@/components/layout/WorkbenchShell";
import { TaskGraphRunInteractionDock } from "@/components/workspace/views/task-system/TaskGraphRunInteractionDock";
import type { WorkspaceView } from "@/lib/store/types";

const CapabilitySystemView = lazy(() => import("@/components/workspace/views/CapabilitySystemView").then((module) => ({ default: module.CapabilitySystemView })));
const HealthSystemView = lazy(() => import("@/components/workspace/views/HealthSystemView").then((module) => ({ default: module.HealthSystemView })));
const MemoryView = lazy(() => import("@/components/workspace/views/MemoryView").then((module) => ({ default: module.MemoryView })));
const OrchestrationView = lazy(() => import("@/components/workspace/views/OrchestrationView").then((module) => ({ default: module.OrchestrationView })));
const SystemConfigView = lazy(() => import("@/components/workspace/views/SystemConfigView").then((module) => ({ default: module.SystemConfigView })));
const TaskSystemView = lazy(() => import("@/components/workspace/views/TaskSystemView").then((module) => ({ default: module.TaskSystemView })));
const CreativeEnvironmentView = lazy(() => import("@/components/workspace/views/CreativeEnvironmentView").then((module) => ({ default: module.CreativeEnvironmentView })));

function LazyView({ children }: { children: ReactNode }) {
  return (
    <Suspense fallback={<div className="boundary-empty boundary-empty--large">正在加载工作台...</div>}>
      {children}
    </Suspense>
  );
}

const WORKSPACE_QUERY_VIEWS = new Set<WorkspaceView>([
  "chat",
  "creative",
  "memory",
  "health-system",
  "task-system",
  "orchestration",
  "code-environment",
  "capability-system",
  "system-config",
]);

const WORKSPACE_TONES = new Set(["water", "leaf", "gold", "ember", "lumen"]);
const TASK_ENVIRONMENT_VIEWS = new Set<WorkspaceView>(["chat", "code-environment"]);

const SYSTEM_NAV_ITEMS: Array<{ view: WorkspaceView; label: string; icon: typeof MessageSquare }> = [
  { view: "chat", label: "工作台", icon: MessageSquare },
  { view: "memory", label: "记忆", icon: Database },
  { view: "task-system", label: "任务", icon: Workflow },
  { view: "orchestration", label: "编排", icon: Network },
  { view: "capability-system", label: "能力", icon: LayoutGrid },
  { view: "health-system", label: "健康", icon: HeartPulse },
  { view: "system-config", label: "配置", icon: Settings },
];

function SystemPageShell({
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
    conversationActiveEnvironment,
    clearTaskGraphMonitorRun,
    continueBoundTaskGraphRun,
    evaluateBoundTaskGraphMonitor,
    setTaskGraphRunInteractionOpen,
    stopBoundTaskGraphRun,
    taskGraphBoundRunMonitor,
    taskGraphMonitorActionLoading,
    taskGraphMonitorBinding,
    taskGraphMonitorError,
    taskGraphMonitorLoading,
    taskGraphRunInteractionOpen,
  } = useAppStore();
  const [locationSearch, setLocationSearch] = useState("");

  useEffect(() => {
    const storedTone = window.localStorage.getItem("workspaceTone");
    if (storedTone && WORKSPACE_TONES.has(storedTone)) {
      document.documentElement.dataset.workspaceTone = storedTone;
    } else {
      delete document.documentElement.dataset.workspaceTone;
    }
  }, [setWorkspaceView]);

  useEffect(() => {
    function syncLocationSearch() {
      setLocationSearch(window.location.search);
    }
    syncLocationSearch();
    window.addEventListener("popstate", syncLocationSearch);
    window.addEventListener("focus", syncLocationSearch);
    const timer = window.setInterval(syncLocationSearch, 500);
    return () => {
      window.removeEventListener("popstate", syncLocationSearch);
      window.removeEventListener("focus", syncLocationSearch);
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    const currentSearch = typeof window === "undefined" ? locationSearch : window.location.search;
    const view = new URLSearchParams(currentSearch).get("view");
    if (view && WORKSPACE_QUERY_VIEWS.has(view as WorkspaceView) && activeWorkspaceView !== view) {
      setWorkspaceView(view as WorkspaceView);
    }
  }, [activeWorkspaceView, locationSearch, setWorkspaceView]);

  useEffect(() => {
    if (
      activeWorkspaceView !== "chat"
      && activeWorkspaceView !== "memory"
      && activeWorkspaceView !== "creative"
      && activeWorkspaceView !== "task-system"
      && activeWorkspaceView !== "health-system"
      && activeWorkspaceView !== "capability-system"
      && activeWorkspaceView !== "orchestration"
      && activeWorkspaceView !== "code-environment"
      && activeWorkspaceView !== "system-config"
    ) {
      setWorkspaceView("chat");
    }
  }, [activeWorkspaceView, setWorkspaceView]);

  const taskGraphRunInteractionDock = (
    <TaskGraphRunInteractionDock
      actionLoading={taskGraphMonitorActionLoading}
      binding={taskGraphMonitorBinding}
      error={taskGraphMonitorError}
      monitor={taskGraphBoundRunMonitor}
      monitorLoading={taskGraphMonitorLoading}
      onClear={clearTaskGraphMonitorRun}
      onContinue={() => void continueBoundTaskGraphRun()}
      onEvaluate={() => void evaluateBoundTaskGraphMonitor()}
      onOpenChange={setTaskGraphRunInteractionOpen}
      onStop={() => void stopBoundTaskGraphRun()}
      open={taskGraphRunInteractionOpen}
    />
  );

  const shouldShowTaskGraphRunInteractionDock =
    activeWorkspaceView === "chat"
    || activeWorkspaceView === "creative"
    || activeWorkspaceView === "orchestration"
    || activeWorkspaceView === "task-system"
    || activeWorkspaceView === "health-system"
    || activeWorkspaceView === "code-environment"
    || activeWorkspaceView === "capability-system";

  let content: ReactNode;

  if (activeWorkspaceView === "orchestration") {
    content = (
      <SystemPageShell label="编排系统" view="orchestration">
        <LazyView><OrchestrationView /></LazyView>
      </SystemPageShell>
    );
  } else if (activeWorkspaceView === "creative") {
    content = (
      <SystemPageShell label="写作环境" view="creative">
        <LazyView><CreativeEnvironmentView /></LazyView>
      </SystemPageShell>
    );
  } else if (activeWorkspaceView === "task-system") {
    content = (
      <SystemPageShell label="任务系统" view="task-system">
        <LazyView><TaskSystemView /></LazyView>
      </SystemPageShell>
    );
  } else if (activeWorkspaceView === "health-system") {
    content = (
      <SystemPageShell label="健康系统" view="health-system">
        <LazyView><HealthSystemView /></LazyView>
      </SystemPageShell>
    );
  } else if (activeWorkspaceView === "memory") {
    content = (
      <SystemPageShell label="长期记忆" view="memory">
        <LazyView><MemoryView /></LazyView>
      </SystemPageShell>
    );
  } else if (activeWorkspaceView === "capability-system") {
    content = (
      <SystemPageShell label="能力系统" view="capability-system">
        <LazyView><CapabilitySystemView /></LazyView>
      </SystemPageShell>
    );
  } else if (activeWorkspaceView === "system-config") {
    content = (
      <SystemPageShell label="配置" view="system-config">
        <LazyView><SystemConfigView /></LazyView>
      </SystemPageShell>
    );
  } else if (activeWorkspaceView === "code-environment" || activeWorkspaceView === "chat") {
    const centerTaskEnvironmentId = String(conversationActiveEnvironment?.task_environment_id || "env.general.workspace");
    content = (
      <SystemPageShell label={activeWorkspaceView === "code-environment" ? "代码环境" : "主会话"} view={activeWorkspaceView}>
        <WorkbenchShell hideMainToolbar>
          <section className="workbench-view-host workbench-view-host--chat" aria-label="主会话">
            <CenterWorkspaceView taskEnvironmentId={centerTaskEnvironmentId} />
            {activeWorkspaceView === "code-environment" ? <CodeEnvironmentView /> : null}
          </section>
        </WorkbenchShell>
      </SystemPageShell>
    );
  } else {
    content = null;
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
