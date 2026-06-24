"use client";

import type { TaskGraphDraftV2 } from "../../task-system/taskGraphDraftV2";

export function GraphTaskStatusBar({
  dirty,
  draft,
  notice,
}: {
  dirty: boolean;
  draft: TaskGraphDraftV2;
  notice: string;
}) {
  return (
    <footer className="graph-repository-status-bar">
      <span>{draft.nodes.length} 节点</span>
      <span>{draft.edges.length} 边</span>
      <span>{draft.publish_state === "published" || draft.publish_state === "run_bound" ? "已发布" : "草稿"}</span>
      <span>{dirty ? "有未保存改动" : "已同步到当前草稿"}</span>
      {notice ? <strong>{notice}</strong> : null}
    </footer>
  );
}
