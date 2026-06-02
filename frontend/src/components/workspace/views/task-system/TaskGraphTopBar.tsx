"use client";

import { CheckCircle2, Save, Send } from "lucide-react";
import type { ReactNode } from "react";

import { TaskSystemToolbarButton } from "./TaskSystemWorkbenchUi";
import { isTaskGraphPublishedState, type TaskGraphPublishStateV2 } from "./taskGraphDraftV2";

export function TaskGraphTopBar({
  onPublish,
  onSave,
  publishState,
  saving,
  valid,
  workspaceSlot,
}: {
  onPublish: () => void;
  onSave: () => void;
  publishState: TaskGraphPublishStateV2;
  saving: string;
  valid: boolean;
  workspaceSlot?: ReactNode;
}) {
  const published = isTaskGraphPublishedState(publishState);
  return (
    <header className="task-graph-studio-topbar">
      <div className="task-graph-studio-topbar__workspace">
        {workspaceSlot}
      </div>
      <div className="task-graph-studio-topbar__actions">
        <TaskSystemToolbarButton disabled={saving === "task-graph"} onClick={onSave}>
          <Save size={15} />保存草稿
        </TaskSystemToolbarButton>
        <TaskSystemToolbarButton disabled={!valid || saving === "task-graph"} onClick={onPublish} variant="primary">
          {published ? <CheckCircle2 size={15} /> : <Send size={15} />}
          发布可运行
        </TaskSystemToolbarButton>
      </div>
    </header>
  );
}
