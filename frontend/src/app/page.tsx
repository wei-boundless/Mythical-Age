"use client";

import { useEffect, useState, type ReactNode } from "react";
import { LayoutGrid, MessageSquare, Network, Settings, Workflow } from "lucide-react";

import { AppProvider, useAppStore } from "@/lib/store";
import { CapabilitySystemView } from "@/components/workspace/views/CapabilitySystemView";
import { CenterWorkspaceView } from "@/components/workspace/views/center/CenterWorkspaceView";
import { OrchestrationView } from "@/components/workspace/views/OrchestrationView";
import { PlaygroundView } from "@/components/workspace/views/PlaygroundView";
import { SystemFrameworkView } from "@/components/workspace/views/SystemFrameworkView";
import { SystemConfigView } from "@/components/workspace/views/SystemConfigView";
import { TaskSystemView } from "@/components/workspace/views/TaskSystemView";
import { WorkbenchShell } from "@/components/layout/WorkbenchShell";
import { TaskGraphRunInteractionDock } from "@/components/workspace/views/task-system/TaskGraphRunInteractionDock";
import type { WorkspaceView } from "@/lib/store/types";

const WORKSPACE_QUERY_VIEWS = new Set<WorkspaceView>([
  "chat",
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

  if (activeWorkspaceView === "system-framework") {
    return (
      <main className="system-framework-stage min-h-screen">
        <SystemFrameworkView />
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
      </main>
    );
  }

  if (activeWorkspaceView === "orchestration") {
    return (
      <SystemPageShell label="编排系统">
        <OrchestrationView />
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
      </SystemPageShell>
    );
  }

  if (activeWorkspaceView === "task-system") {
    return (
      <SystemPageShell label="任务系统">
        <TaskSystemView />
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
      </SystemPageShell>
    );
  }

  if (activeWorkspaceView === "capability-system") {
    return (
      <SystemPageShell label="能力系统">
        <CapabilitySystemView />
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
      </SystemPageShell>
    );
  }

  if (activeWorkspaceView === "system-config") {
    return (
      <SystemPageShell label="配置">
        <SystemConfigView />
      </SystemPageShell>
    );
  }

  if (forcedPlayground || activeWorkspaceView === "playground") {
    return <PlaygroundView onReturnToWorkspace={returnToWorkspace} />;
  }

  return (
    <SystemPageShell label="主会话">
      <WorkbenchShell>
        <section className="workbench-view-host workbench-view-host--chat" aria-label="主会话">
          <CenterWorkspaceView />
        </section>
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
      </WorkbenchShell>
    </SystemPageShell>
  );
}

export default function Page() {
  return (
    <AppProvider>
      <Workspace />
    </AppProvider>
  );
}
