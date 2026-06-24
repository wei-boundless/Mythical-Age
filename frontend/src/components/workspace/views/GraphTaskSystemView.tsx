"use client";

import { useEffect, useState } from "react";

import { GraphRepositoryPage } from "@/components/workspace/views/graph-repository/GraphRepositoryPage";
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
    <section className="graph-task-system-page" aria-label="任务图系统">
      <GraphRepositoryPage requestedGraphId={requestedGraphId} />
    </section>
  );
}
