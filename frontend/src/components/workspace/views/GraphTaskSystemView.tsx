"use client";

import { useEffect, useState } from "react";

import { GraphTaskWorkspace } from "@/components/workspace/views/task-graph-workbench/GraphTaskWorkspace";
import { useAppStore } from "@/lib/store";

export function GraphTaskSystemView() {
  const { clearTaskGraphWorkspaceTarget, taskGraphWorkspaceTarget } = useAppStore();
  const [requestedGraphId, setRequestedGraphId] = useState("");
  const [requestedMode, setRequestedMode] = useState<"instances" | "editor">("instances");

  useEffect(() => {
    if (!taskGraphWorkspaceTarget) return;
    setRequestedGraphId(String(taskGraphWorkspaceTarget.graph_id || "").trim());
    setRequestedMode(taskGraphWorkspaceTarget.mode === "editor" ? "editor" : "instances");
    clearTaskGraphWorkspaceTarget();
  }, [clearTaskGraphWorkspaceTarget, taskGraphWorkspaceTarget]);

  return (
    <section className="graph-task-system-page" aria-label="图任务系统">
      <GraphTaskWorkspace
        initialMode={requestedMode}
        requestedGraphId={requestedGraphId}
      />
    </section>
  );
}
