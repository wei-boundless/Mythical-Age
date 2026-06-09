"use client";

import { useEffect, useState } from "react";

import { GraphTaskWorkspace } from "@/components/workspace/views/task-graph-workbench/GraphTaskWorkspace";
import { useAppStore } from "@/lib/store";

export function GraphTaskSystemView() {
  const { clearTaskGraphWorkspaceTarget, taskGraphWorkspaceTarget } = useAppStore();
  const [requestedGraphId, setRequestedGraphId] = useState("");

  useEffect(() => {
    if (!taskGraphWorkspaceTarget) return;
    setRequestedGraphId(String(taskGraphWorkspaceTarget.graph_id || "").trim());
    clearTaskGraphWorkspaceTarget();
  }, [clearTaskGraphWorkspaceTarget, taskGraphWorkspaceTarget]);

  return (
    <section className="graph-task-system-page" aria-label="图任务系统">
      <GraphTaskWorkspace
        requestedGraphId={requestedGraphId}
        surface="operations"
      />
    </section>
  );
}
