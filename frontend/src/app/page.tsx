"use client";

import { useEffect, useState, type ReactNode } from "react";
import { BookOpen, Database, HeartPulse, LayoutGrid, MessageSquare, Network, Settings, Sparkles, Workflow } from "lucide-react";

import { AppProvider, useAppStore } from "@/lib/store";
import { lazy, Suspense } from "react";
import { CenterWorkspaceView } from "@/components/workspace/views/center/CenterWorkspaceView";
import { ConfirmDialogProvider } from "@/components/layout/ConfirmDialogProvider";
import { WorkbenchShell } from "@/components/layout/WorkbenchShell";
import { TaskGraphRunInteractionDock } from "@/components/workspace/views/task-system/TaskGraphRunInteractionDock";
import type { WorkspaceView } from "@/lib/store/types";

const CapabilitySystemView = lazy(() => import("@/components/workspace/views/CapabilitySystemView").then((module) => ({ default: module.CapabilitySystemView })));
const HealthSystemView = lazy(() => import("@/components/workspace/views/HealthSystemView").then((module) => ({ default: module.HealthSystemView })));
const MemoryView = lazy(() => import("@/components/workspace/views/MemoryView").then((module) => ({ default: module.MemoryView })));
const OrchestrationView = lazy(() => import("@/components/workspace/views/OrchestrationView").then((module) => ({ default: module.OrchestrationView })));
const PlaygroundView = lazy(() => import("@/components/workspace/views/PlaygroundView").then((module) => ({ default: module.PlaygroundView })));
const SoulSystemView = lazy(() => import("@/components/workspace/views/PlaygroundView").then((module) => ({ default: module.PlaygroundView })));
const SystemConfigView = lazy(() => import("@/components/workspace/views/SystemConfigView").then((module) => ({ default: module.SystemConfigView })));
const TaskSystemView = lazy(() => import("@/components/workspace/views/TaskSystemView").then((module) => ({ default: module.TaskSystemView })));
const CodeEnvironmentView = lazy(() => import("@/components/workspace/views/CodeEnvironmentView").then((module) => ({ default: module.CodeEnvironmentView })));
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
  "playground",
  "task-system",
  "orchestration",
  "code-environment",
  "capability-system",
  "soul-system",
  "system-config",
]);

const WORKSPACE_TONES = new Set(["water", "leaf", "gold", "ember", "lumen"]);

const SYSTEM_NAV_ITEMS: Array<{ view: WorkspaceView; label: string; icon: typeof MessageSquare }> = [
  { view: "chat", label: "会话", icon: MessageSquare },
  { view: "creative", label: "创作", icon: BookOpen },
  { view: "memory", label: "记忆", icon: Database },
  { view: "task-system", label: "任务", icon: Workflow },
  { view: "orchestration", label: "编排", icon: Network },
  { view: "capability-system", label: "能力", icon: LayoutGrid },
  { view: "health-system", label: "健康", icon: HeartPulse },
  { view: "soul-system", label: "灵魂", icon: Sparkles },
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
    continueBoundTaskGraphRun,
    evaluateBoundTaskGraphMonitor,
    setTaskGraphRunInteractionOpen,
    taskGraphBoundRunMonitor,
    taskGraphMonitorActionLoading,
    taskGraphMonitorBinding,
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
      && activeWorkspaceView !== "creative"
      && activeWorkspaceView !== "playground"
      && activeWorkspaceView !== "task-system"
      && activeWorkspaceView !== "health-system"
      && activeWorkspaceView !== "capability-system"
      && activeWorkspaceView !== "soul-system"
      && activeWorkspaceView !== "orchestration"
      && activeWorkspaceView !== "code-environment"
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
      error={taskGraphMonitorError}
      monitor={taskGraphBoundRunMonitor}
      monitorLoading={taskGraphMonitorLoading}
      onClear={clearTaskGraphMonitorRun}
      onContinue={() => void continueBoundTaskGraphRun()}
      onEvaluate={() => void evaluateBoundTaskGraphMonitor()}
      onOpenChange={setTaskGraphRunInteractionOpen}
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
    || activeWorkspaceView === "capability-system"
    || activeWorkspaceView === "soul-system";

  let content: ReactNode;

  if (activeWorkspaceView === "orchestration") {
    content = (
      <SystemPageShell label="编排系统" view="orchestration">
        <LazyView><OrchestrationView /></LazyView>
      </SystemPageShell>
    );
  } else if (activeWorkspaceView === "creative") {
    content = (
      <SystemPageShell label="创作环境" view="creative">
        <LazyView><CreativeEnvironmentView /></LazyView>
      </SystemPageShell>
    );
  } else if (activeWorkspaceView === "task-system") {
    content = (
      <SystemPageShell label="任务系统" view="task-system">
        <LazyView><TaskSystemView /></LazyView>
      </SystemPageShell>
    );
  } else if (activeWorkspaceView === "code-environment") {
    content = (
      <SystemPageShell label="代码环境" view="code-environment">
        <LazyView><CodeEnvironmentView /></LazyView>
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
  } else if (activeWorkspaceView === "soul-system") {
    content = (
      <SystemPageShell label="灵魂系统" view="soul-system">
        <LazyView><SoulSystemView embedded onReturnToWorkspace={returnToWorkspace} /></LazyView>
      </SystemPageShell>
    );
  } else if (activeWorkspaceView === "system-config") {
    content = (
      <SystemPageShell label="配置" view="system-config">
        <LazyView><SystemConfigView /></LazyView>
      </SystemPageShell>
    );
  } else if (forcedPlayground || activeWorkspaceView === "playground") {
    content = <LazyView><PlaygroundView onReturnToWorkspace={returnToWorkspace} /></LazyView>;
  } else {
    content = (
      <SystemPageShell label="主会话" view="chat">
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
