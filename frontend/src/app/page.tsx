"use client";

import { useEffect, useState } from "react";

import { AppProvider, useAppStore } from "@/lib/store";
import { CapabilitySystemView } from "@/components/workspace/views/CapabilitySystemView";
import { CenterWorkspaceView } from "@/components/workspace/views/center/CenterWorkspaceView";
import { OrchestrationView } from "@/components/workspace/views/OrchestrationView";
import { PlaygroundView } from "@/components/workspace/views/PlaygroundView";
import { SystemFrameworkView } from "@/components/workspace/views/SystemFrameworkView";
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
]);

const WORKSPACE_TONES = new Set(["water", "leaf", "gold", "ember", "lumen"]);

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

  return (
    forcedPlayground || activeWorkspaceView === "playground" ? (
      <PlaygroundView onReturnToWorkspace={returnToWorkspace} />
    ) : (
      <WorkbenchShell>
        {activeWorkspaceView === "capability-system" ? (
          <section className="workbench-view-host" aria-label="能力系统">
            <CapabilitySystemView />
          </section>
        ) : activeWorkspaceView === "orchestration" ? (
          <section className="workbench-view-host" aria-label="编排系统">
            <OrchestrationView />
          </section>
        ) : activeWorkspaceView === "task-system" ? (
          <section className="workbench-view-host" aria-label="图任务层">
            <TaskSystemView />
          </section>
        ) : (
          <section className="workbench-view-host workbench-view-host--chat" aria-label="主会话">
            <CenterWorkspaceView />
          </section>
        )}
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
    )
  );
}

export default function Page() {
  return (
    <AppProvider>
      <Workspace />
    </AppProvider>
  );
}
