"use client";

import { PlaySquare, RefreshCw } from "lucide-react";
import type { GraphTaskInstanceSummary, TaskGraphRecord } from "@/lib/api";

export function GraphInstanceList({
  activeGraph,
  instances,
  loading,
  onRefresh,
  onSelectInstance,
  selectedInstanceId,
  showHeader = true,
}: {
  activeGraph: TaskGraphRecord | null;
  instances: GraphTaskInstanceSummary[];
  loading: boolean;
  showHeader?: boolean;
  selectedInstanceId: string;
  onRefresh: () => void;
  onSelectInstance: (instance: GraphTaskInstanceSummary) => void;
}) {
  return (
    <section className="graph-repository-section graph-repository-section--instances" aria-label="图实例">
      {showHeader ? <header className="graph-repository-section-head">
        <div>
          <span>Graph Instances</span>
          <strong>实例</strong>
        </div>
        <p>{activeGraph ? `当前图：${activeGraph.title || activeGraph.graph_id}` : "先选择或保存一个图定义，再查看它的实例空间。"}</p>
        <button onClick={onRefresh} type="button"><RefreshCw size={14} />刷新</button>
      </header> : null}
      <div className="graph-repository-instance-list">
        {instances.length ? instances.map((instance) => {
          const active = selectedInstanceId === instance.graph_task_instance_id;
          return (
            <button
              className={active ? "graph-repository-instance-row graph-repository-instance-row--active" : "graph-repository-instance-row"}
              key={instance.graph_task_instance_id}
              onClick={() => onSelectInstance(instance)}
              type="button"
            >
              <PlaySquare size={15} />
              <span>
                <strong>{instance.title || instance.graph_task_instance_id}</strong>
                <small>{instance.graph_task_instance_id}</small>
              </span>
              <em>{instance.status || "created"}</em>
            </button>
          );
        }) : (
          <div className="graph-repository-empty">{loading ? "正在加载实例..." : "当前图还没有实例。"}</div>
        )}
      </div>
    </section>
  );
}
