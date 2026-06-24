"use client";

import { GitBranch, MessageSquare, UserCheck } from "lucide-react";
import type {
  GraphTaskInstanceHumanControls,
  GraphTaskInstanceSummary,
  SessionSummary,
} from "@/lib/api";

export function GraphInstanceNodeSessions({
  humanControls,
  instance,
  nodeSessions,
  onOpenSession,
}: {
  humanControls: GraphTaskInstanceHumanControls | null;
  instance: GraphTaskInstanceSummary;
  nodeSessions: SessionSummary[];
  onOpenSession: (session: SessionSummary) => void;
}) {
  const pendingControls = humanControls?.pending ?? [];
  return (
    <aside className="graph-instance-session-panel" aria-label="节点会话与人工控制">
      <header>
        <div>
          <span>Agent 节点会话</span>
          <strong>{instance.title || instance.graph_task_instance_id}</strong>
        </div>
        <MessageSquare size={16} />
      </header>
      <section className="graph-instance-session-group">
        <div className="graph-instance-session-group__title">
          <GitBranch size={14} />
          <strong>节点会话</strong>
          <em>{nodeSessions.length}</em>
        </div>
        {nodeSessions.length ? (
          <div className="graph-instance-session-list">
            {nodeSessions.map((session) => (
              <article className="graph-instance-session-row" key={session.id}>
                <MessageSquare size={14} />
                <span>
                  <strong>{session.title || session.id}</strong>
                  <small>{sessionSubtitle(session)}</small>
                </span>
                <button onClick={() => onOpenSession(session)} type="button">投影</button>
              </article>
            ))}
          </div>
        ) : (
          <div className="graph-instance-empty graph-instance-empty--compact">暂无节点会话。</div>
        )}
      </section>
      <section className="graph-instance-session-group">
        <div className="graph-instance-session-group__title">
          <UserCheck size={14} />
          <strong>人工控制</strong>
          <em>{pendingControls.length}</em>
        </div>
        {pendingControls.length ? (
          <div className="graph-instance-control-list">
            {pendingControls.map((control) => (
              <article className="graph-instance-control-row" key={control.control_id}>
                <strong>{control.source_node_id} → {control.target_node_id}</strong>
                <span>{control.reason || "等待人工确认边交接。"}</span>
              </article>
            ))}
          </div>
        ) : (
          <div className="graph-instance-empty graph-instance-empty--compact">没有待处理的人工决策。</div>
        )}
      </section>
    </aside>
  );
}

function sessionSubtitle(session: SessionSummary) {
  const binding = session.task_binding;
  const graphRunId = binding?.graph_run_id ? `run: ${binding.graph_run_id}` : "";
  const projectId = binding?.project_id ? `project: ${binding.project_id}` : "";
  return [session.id, graphRunId, projectId].filter(Boolean).join(" / ");
}
