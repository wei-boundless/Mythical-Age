"use client";

import { Copy, Edit3, PlayCircle } from "lucide-react";
import type { TaskGraphRecord } from "@/lib/api";

export function GraphLibrary({
  graphs,
  loading,
  onCreateInstance,
  onDuplicateGraph,
  onOpenGraph,
  showHeader = true,
}: {
  graphs: TaskGraphRecord[];
  loading: boolean;
  showHeader?: boolean;
  onOpenGraph: (graph: TaskGraphRecord) => void;
  onDuplicateGraph: (graph: TaskGraphRecord) => void;
  onCreateInstance: (graph: TaskGraphRecord) => void;
}) {
  return (
    <section className="graph-repository-section" aria-label="图定义">
      {showHeader ? <header className="graph-repository-section-head">
        <div>
          <span>Task Graph Definitions</span>
          <strong>图定义</strong>
        </div>
        <p>这里管理已保存的任务图定义。节点细节回到画布编辑，不在定义列表里混合展开。</p>
      </header> : null}
      <div className="graph-repository-graph-table">
        <header>
          <span>图定义</span>
          <span>状态</span>
          <span>规模</span>
          <span>操作</span>
        </header>
        {graphs.length ? graphs.map((graph) => (
          <article className="graph-repository-graph-row" key={graph.graph_id}>
            <button onClick={() => onOpenGraph(graph)} type="button">
              <strong>{graph.title || graph.graph_id}</strong>
              <small>{graph.graph_id}</small>
            </button>
            <em className={graph.enabled ? "graph-repository-state graph-repository-state--published" : "graph-repository-state"}>
              {graph.enabled ? "已发布" : graph.publish_state || "草稿"}
            </em>
            <span>{graph.node_count ?? graph.nodes?.length ?? 0} 节点 / {graph.edge_count ?? graph.edges?.length ?? 0} 边</span>
            <nav>
              <button onClick={() => onOpenGraph(graph)} title="打开编辑器" type="button"><Edit3 size={14} /></button>
              <button onClick={() => onDuplicateGraph(graph)} title="生产副本" type="button"><Copy size={14} /></button>
              <button onClick={() => onCreateInstance(graph)} title="创建实例" type="button"><PlayCircle size={14} /></button>
            </nav>
          </article>
        )) : (
          <div className="graph-repository-empty">{loading ? "正在加载图定义..." : "还没有图定义，可以先从模板库创建一个草稿。"}</div>
        )}
      </div>
    </section>
  );
}
