"use client";

import { AlertTriangle, CheckCircle2, Save } from "lucide-react";
import { taskGraphPublishStateLabel, type TaskGraphPublishStateV2 } from "./taskGraphDraftV2";

export function TaskGraphIssueBar({
  dirty,
  issueCount,
  publishState,
  valid,
}: {
  dirty: boolean;
  issueCount: number;
  publishState: TaskGraphPublishStateV2;
  valid: boolean;
}) {
  const published = publishState === "published" || publishState === "run_bound";
  const healthIcon = valid ? <CheckCircle2 aria-hidden="true" size={15} /> : <AlertTriangle aria-hidden="true" size={15} />;
  return (
    <footer className="task-graph-issue-bar" aria-label="任务图状态">
      <span className={dirty ? "task-graph-issue-bar__item task-graph-issue-bar__item--warn" : "task-graph-issue-bar__item"}>
        <Save aria-hidden="true" size={14} />
        {dirty ? "拓扑未同步" : "拓扑已同步"}
      </span>
      <span className={valid ? "task-graph-issue-bar__item task-graph-issue-bar__item--ok" : "task-graph-issue-bar__item task-graph-issue-bar__item--danger"}>
        {healthIcon}
        {valid ? "图预检通过" : `待处理问题 ${issueCount}`}
      </span>
      <span className={published ? "task-graph-issue-bar__item task-graph-issue-bar__item--ok" : "task-graph-issue-bar__item"}>
        {taskGraphPublishStateLabel(publishState)}
      </span>
    </footer>
  );
}
