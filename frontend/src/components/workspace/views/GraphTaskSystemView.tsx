"use client";

import { useEffect, useState } from "react";

import { GraphRepositoryPage } from "@/components/workspace/views/graph-repository/GraphRepositoryPage";
import { useAppStore } from "@/lib/store";
import type { TaskGraphWorkspaceTarget } from "@/lib/store/types";

type RequestedGraphWorkspace = {
  context?: "editor" | "monitor";
  graphId: string;
  instanceId: string;
  panel?: "writing" | "files" | "artifacts";
};

function targetFromLocationSearch(search: string): RequestedGraphWorkspace | null {
  const params = new URLSearchParams(search);
  const graphId = String(params.get("graph_id") || params.get("graphId") || "").trim();
  const instanceId = String(params.get("instance_id") || params.get("instanceId") || "").trim();
  const panel = String(params.get("panel") || "").trim();
  const context = String(params.get("context") || params.get("mode") || "").trim();
  if (!graphId && !instanceId && !panel && !context) return null;
  return {
    context: context === "monitor" ? "monitor" : context === "editor" ? "editor" : instanceId || panel ? "monitor" : undefined,
    graphId,
    instanceId,
    panel: panel === "writing" || panel === "files" || panel === "artifacts" ? panel : undefined,
  };
}

function targetFromWorkspaceTarget(target: TaskGraphWorkspaceTarget | null): RequestedGraphWorkspace | null {
  if (!target) return null;
  return {
    context: target.mode === "editor" ? "editor" : target.mode === "monitor" ? "monitor" : undefined,
    graphId: String(target.graph_id || "").trim(),
    instanceId: String(target.task_instance_id || "").trim(),
  };
}

export function GraphTaskSystemView() {
  const { clearTaskGraphWorkspaceTarget, taskGraphWorkspaceTarget } = useAppStore();
  const [requestedWorkspace, setRequestedWorkspace] = useState<RequestedGraphWorkspace>({
    graphId: "",
    instanceId: "",
  });

  useEffect(() => {
    const nextTarget = targetFromWorkspaceTarget(taskGraphWorkspaceTarget);
    if (!nextTarget) return;
    setRequestedWorkspace(nextTarget);
    clearTaskGraphWorkspaceTarget();
  }, [clearTaskGraphWorkspaceTarget, taskGraphWorkspaceTarget]);

  useEffect(() => {
    function syncLocationTarget() {
      const nextTarget = targetFromLocationSearch(window.location.search);
      if (nextTarget) setRequestedWorkspace(nextTarget);
    }
    syncLocationTarget();
    window.addEventListener("popstate", syncLocationTarget);
    return () => window.removeEventListener("popstate", syncLocationTarget);
  }, []);

  return (
    <section className="graph-task-system-page" aria-label="任务图系统">
      <GraphRepositoryPage
        requestedContext={requestedWorkspace.context}
        requestedGraphId={requestedWorkspace.graphId}
        requestedInstanceId={requestedWorkspace.instanceId}
        requestedPanel={requestedWorkspace.panel}
      />
    </section>
  );
}
