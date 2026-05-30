"use client";

import { CheckCircle2, Save, Send } from "lucide-react";

import { TaskSystemToolbarButton } from "./TaskSystemWorkbenchUi";
import { isTaskGraphPublishedState, taskGraphPublishStateLabel, type TaskGraphPublishStateV2 } from "./taskGraphDraftV2";

export function TaskGraphTopBar({
  coordinatorAgentId,
  graphId,
  issueCount,
  nodeCount,
  edgeCount,
  onPublish,
  onSave,
  publishState,
  saving,
  title,
  valid,
}: {
  coordinatorAgentId: string;
  graphId: string;
  issueCount: number;
  nodeCount: number;
  edgeCount: number;
  onPublish: () => void;
  onSave: () => void;
  publishState: TaskGraphPublishStateV2;
  saving: string;
  title: string;
  valid: boolean;
}) {
  const published = isTaskGraphPublishedState(publishState);
  return (
    <header className="task-graph-studio-topbar">
      <div className="task-graph-studio-topbar__identity">
        <span>主会话 · 图任务工作台</span>
        <strong>{title || graphId || "未命名任务图"}</strong>
        <small>{graphId || "graph.draft"} · 协调者 {coordinatorAgentId || "agent:0"}</small>
      </div>
      <div className="task-graph-studio-topbar__metrics" aria-label="任务图摘要">
        <article>
          <span>节点</span>
          <strong>{nodeCount}</strong>
        </article>
        <article>
          <span>边</span>
          <strong>{edgeCount}</strong>
        </article>
        <article>
          <span>问题</span>
          <strong>{issueCount}</strong>
        </article>
        <article>
          <span>状态</span>
          <strong>{published ? taskGraphPublishStateLabel(publishState) : valid ? "可发布" : taskGraphPublishStateLabel(publishState)}</strong>
        </article>
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
