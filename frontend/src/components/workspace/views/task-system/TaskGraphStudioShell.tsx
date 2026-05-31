"use client";

import type { ReactNode } from "react";

import { TaskGraphIssueBar } from "./TaskGraphIssueBar";
import { TaskGraphLayerNav, type TaskGraphStudioLayerId } from "./TaskGraphLayerNav";
import { TaskGraphTopBar } from "./TaskGraphTopBar";
import type { TaskGraphPublishStateV2 } from "./taskGraphDraftV2";

export function TaskGraphStudioShell({
  activeLayer,
  children,
  coordinatorAgentId,
  dirty,
  edgeCount,
  graphId,
  issueCount,
  nodeCount,
  onLayerChange,
  onPublish,
  onSave,
  publishState,
  saving,
  title,
  valid,
  workspaceSlot,
}: {
  activeLayer: TaskGraphStudioLayerId;
  children: ReactNode;
  coordinatorAgentId: string;
  dirty: boolean;
  edgeCount: number;
  graphId: string;
  issueCount: number;
  nodeCount: number;
  onLayerChange: (layer: TaskGraphStudioLayerId) => void;
  onPublish: () => void;
  onSave: () => void;
  publishState: TaskGraphPublishStateV2;
  saving: string;
  title: string;
  valid: boolean;
  workspaceSlot?: ReactNode;
}) {
  return (
    <section className={workspaceSlot ? "task-graph-studio-shell task-graph-studio-shell--with-workspace" : "task-graph-studio-shell"} aria-label="多 Agent 持续任务编排平台">
      <TaskGraphTopBar
        coordinatorAgentId={coordinatorAgentId}
        edgeCount={edgeCount}
        graphId={graphId}
        issueCount={issueCount}
        nodeCount={nodeCount}
        onPublish={onPublish}
        onSave={onSave}
        publishState={publishState}
        saving={saving}
        title={title}
        valid={valid}
      />
      {workspaceSlot ? (
        <section className="task-graph-studio-workspace-strip" aria-label="任务图工作集">
          {workspaceSlot}
        </section>
      ) : null}
      <div className="task-graph-studio-shell__body">
        <TaskGraphLayerNav activeLayer={activeLayer} onChange={onLayerChange} />
        <main className="task-graph-studio-shell__page">
          {children}
        </main>
      </div>
      <TaskGraphIssueBar dirty={dirty} issueCount={issueCount} publishState={publishState} valid={valid} />
    </section>
  );
}
