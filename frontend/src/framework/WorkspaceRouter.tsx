"use client";

import { useEffect, useState } from "react";

import { TaskGraphRunInteractionDock } from "@/components/workspace/views/task-system/TaskGraphRunInteractionDock";
import { useAppStore } from "@/lib/store";

import { WorkspaceRegistry } from "./WorkspaceRegistry";
import {
  isWorkspaceQueryView,
  isWorkspaceView,
  shouldShowTaskGraphRunInteractionDock,
  WORKSPACE_TONES,
} from "./workspaceViews";

export function WorkspaceRouter() {
  const {
    activeWorkspaceView,
    setWorkspaceView,
    conversationActiveEnvironment,
    clearTaskGraphMonitorRun,
    continueBoundTaskGraphRun,
    evaluateBoundTaskGraphMonitor,
    pauseBoundTaskGraphRun,
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
    if (isWorkspaceQueryView(view) && activeWorkspaceView !== view) {
      setWorkspaceView(view);
    }
  }, [activeWorkspaceView, locationSearch, setWorkspaceView]);

  useEffect(() => {
    if (!isWorkspaceView(activeWorkspaceView)) {
      setWorkspaceView("chat");
    }
  }, [activeWorkspaceView, setWorkspaceView]);

  const centerTaskEnvironmentId = String(conversationActiveEnvironment?.task_environment_id || "env.general.workspace");

  return (
    <>
      <WorkspaceRegistry centerTaskEnvironmentId={centerTaskEnvironmentId} view={activeWorkspaceView} />
      {shouldShowTaskGraphRunInteractionDock(activeWorkspaceView) ? (
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
          onPause={() => void pauseBoundTaskGraphRun()}
          onStop={() => void stopBoundTaskGraphRun()}
          open={taskGraphRunInteractionOpen}
        />
      ) : null}
    </>
  );
}
