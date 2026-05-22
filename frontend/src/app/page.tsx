"use client";

import { useEffect, useState } from "react";

import { AppProvider, useAppStore } from "@/lib/store";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { CapabilitySystemView } from "@/components/workspace/views/CapabilitySystemView";
import { PlaygroundView } from "@/components/workspace/views/PlaygroundView";
import { SystemFrameworkView } from "@/components/workspace/views/SystemFrameworkView";
import { TaskSystemView } from "@/components/workspace/views/TaskSystemView";
import { TaskMonitorDock } from "@/components/layout/TaskMonitorDock";
import { Sidebar } from "@/components/layout/Sidebar";
import { TaskGraphRunInteractionDock } from "@/components/workspace/views/task-system/TaskGraphRunInteractionDock";
import type { WorkspaceView } from "@/lib/store/types";

const WORKSPACE_QUERY_VIEWS = new Set<WorkspaceView>([
  "chat",
  "playground",
  "task-system",
  "capability-system",
  "system-framework",
]);

function isTaskLayerView(view: WorkspaceView) {
  return view === "task-system" || view === "capability-system";
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
  const [mounted, setMounted] = useState(false);
  const [forcedPlayground, setForcedPlayground] = useState(false);

  const mainView: WorkspaceView = isTaskLayerView(activeWorkspaceView)
    ? "task-system"
    : activeWorkspaceView === "playground"
      ? "playground"
      : "chat";

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    const view = new URLSearchParams(window.location.search).get("view");
    if (view && WORKSPACE_QUERY_VIEWS.has(view as WorkspaceView)) {
      setWorkspaceView(view as WorkspaceView);
      setForcedPlayground(view === "playground");
    }
  }, [setWorkspaceView]);

  if (!mounted) {
    return <main className="app-boot-stage" aria-label="正在启动" />;
  }

  useEffect(() => {
    if (
      activeWorkspaceView !== "chat"
      && activeWorkspaceView !== "playground"
      && !isTaskLayerView(activeWorkspaceView)
      && activeWorkspaceView !== "system-framework"
    ) {
      setWorkspaceView("chat");
    }
  }, [activeWorkspaceView, setWorkspaceView]);

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
      <PlaygroundView />
    ) : (
      <main className="practical-workspace">
        <Sidebar />
        <section className="practical-main" aria-label="主工作区">
          <section className="practical-content">
            {activeWorkspaceView === "capability-system" ? (
              <CapabilitySystemView />
            ) : mainView === "task-system" ? (
              <TaskSystemView />
            ) : (
              <ChatPanel />
            )}
          </section>
        </section>
        <TaskMonitorDock />
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
