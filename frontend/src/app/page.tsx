"use client";

import type { CSSProperties } from "react";
import { useEffect } from "react";

import { Navbar } from "@/components/layout/Navbar";
import { ResizeHandle } from "@/components/layout/ResizeHandle";
import { Sidebar } from "@/components/layout/Sidebar";
import { WorkspacePanel } from "@/components/workspace/WorkspacePanel";
import { SystemFrameworkView } from "@/components/workspace/views/SystemFrameworkView";
import { TaskGraphRunInteractionDock } from "@/components/workspace/views/task-system/TaskGraphRunInteractionDock";
import { AppProvider, useAppStore } from "@/lib/store";
import type { WorkspaceView } from "@/lib/store/types";

const WORKSPACE_QUERY_VIEWS = new Set<WorkspaceView>([
  "chat",
  "memory",
  "test-system",
  "health-system",
  "capability-system",
  "mcp-system",
  "evidence",
  "task-system",
  "orchestration",
  "system-framework",
  "experiments",
  "playground",
  "system-config"
]);

function Workspace() {
  const {
    sidebarWidth,
    setSidebarWidth,
    activeSoulKey,
    activeWorkspaceView,
    setWorkspaceView,
    soulOptions,
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
  const isBoundaryWorkspace = activeWorkspaceView === "task-system" || activeWorkspaceView === "orchestration";
  const activeSoul = soulOptions.find((soul) => soul.key === activeSoulKey) ?? soulOptions[0] ?? null;
  const soulBackgroundPath = activeSoul?.backgroundPath ?? `/souls/backgrounds/${activeSoulKey ?? "hebo"}-bg.png`;

  useEffect(() => {
    if (activeSoulKey) {
      document.documentElement.dataset.soul = activeSoulKey;
      return;
    }
    delete document.documentElement.dataset.soul;
  }, [activeSoulKey]);

  useEffect(() => {
    const view = new URLSearchParams(window.location.search).get("view");
    if (view && WORKSPACE_QUERY_VIEWS.has(view as WorkspaceView)) {
      setWorkspaceView(view as WorkspaceView);
    }
  }, [setWorkspaceView]);

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
    <main className={`workspace-shell ${isBoundaryWorkspace ? "workspace-shell--task-focus" : ""} min-h-screen px-3 py-4 md:px-6 md:py-6`}>
      <div
        aria-hidden="true"
        className="soul-background-figure"
        style={{ "--soul-background-image": `url(${soulBackgroundPath})` } as CSSProperties}
      />
      <div className={`workspace-grid mx-auto flex flex-col ${isBoundaryWorkspace ? "gap-3 max-w-[1920px]" : "gap-4 max-w-[1820px]"}`}>
        <Navbar />
        <div className={`workspace-frame ${isBoundaryWorkspace ? "workspace-frame--work" : ""} flex min-h-[calc(100vh-112px)] flex-col gap-3 xl:flex-row ${isBoundaryWorkspace ? "xl:gap-2" : "xl:gap-0"}`}>
          <div
            className={`w-full xl:shrink-0 ${isBoundaryWorkspace ? "workspace-sidebar-slot--compact" : ""}`}
            style={isBoundaryWorkspace ? undefined : { width: `min(100%, ${sidebarWidth}px)` }}
          >
            <Sidebar compact={isBoundaryWorkspace} />
          </div>
          {isBoundaryWorkspace ? null : <ResizeHandle onResize={(delta) => setSidebarWidth(Math.max(280, sidebarWidth + delta))} />}
          <WorkspacePanel />
        </div>
      </div>
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

export default function Page() {
  return (
    <AppProvider>
      <Workspace />
    </AppProvider>
  );
}
