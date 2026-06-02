"use client";

import type { ReactNode } from "react";

import { TaskGraphIssueBar } from "./TaskGraphIssueBar";
import { TaskGraphLayerNav, type TaskGraphStudioLayerId } from "./TaskGraphLayerNav";
import { TaskGraphTopBar } from "./TaskGraphTopBar";
import type { TaskGraphPublishStateV2 } from "./taskGraphDraftV2";

export function TaskGraphStudioShell({
  activeLayer,
  children,
  dirty,
  issueCount,
  onLayerChange,
  onPublish,
  onSave,
  publishState,
  saving,
  valid,
  workspaceSlot,
}: {
  activeLayer: TaskGraphStudioLayerId;
  children: ReactNode;
  dirty: boolean;
  issueCount: number;
  onLayerChange: (layer: TaskGraphStudioLayerId) => void;
  onPublish: () => void;
  onSave: () => void;
  publishState: TaskGraphPublishStateV2;
  saving: string;
  valid: boolean;
  workspaceSlot?: ReactNode;
}) {
  return (
    <section className="task-graph-studio-shell" aria-label="多 Agent 持续任务编排平台">
      <TaskGraphTopBar
        onPublish={onPublish}
        onSave={onSave}
        publishState={publishState}
        saving={saving}
        valid={valid}
        workspaceSlot={workspaceSlot}
      />
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
