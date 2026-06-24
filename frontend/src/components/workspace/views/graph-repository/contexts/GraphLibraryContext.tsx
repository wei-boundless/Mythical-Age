"use client";

import { Copy, GitFork, PlayCircle } from "lucide-react";
import type { TaskGraphRecord } from "@/lib/api";

import { GraphLibrary } from "../GraphLibrary";

export function GraphLibraryContext({
  graphs,
  loading,
  onCreateInstance,
  onDuplicateGraph,
  onOpenGraph,
  selectedGraphId,
}: {
  graphs: TaskGraphRecord[];
  loading: boolean;
  selectedGraphId: string;
  onOpenGraph: (graph: TaskGraphRecord) => void;
  onDuplicateGraph: (graph: TaskGraphRecord) => void;
  onCreateInstance: (graph: TaskGraphRecord) => void;
}) {
  const selectedGraph = graphs.find((graph) => graph.graph_id === selectedGraphId) ?? graphs[0] ?? null;
  const publishedCount = graphs.filter((graph) => graph.enabled || graph.publish_state === "published").length;
  return (
    <section className="graph-os-library-context" aria-label="图定义上下文">
      <aside className="graph-os-context-rail">
        <header>
          <span>Definition Context</span>
          <strong>图定义管理</strong>
        </header>
        <div className="graph-os-fact-list">
          <p><GitFork size={14} /><span>图定义</span><strong>{graphs.length}</strong></p>
          <p><PlayCircle size={14} /><span>已发布</span><strong>{publishedCount}</strong></p>
          <p><Copy size={14} /><span>编辑入口</span><strong>画布</strong></p>
        </div>
        <p className="graph-os-context-note">图库只管理图定义和版本动作。节点、边、契约和提示词细节进入编辑器处理。</p>
      </aside>
      <div className="graph-os-context-main">
        <GraphLibrary
          graphs={graphs}
          loading={loading}
          onCreateInstance={onCreateInstance}
          onDuplicateGraph={onDuplicateGraph}
          onOpenGraph={onOpenGraph}
        />
      </div>
      <aside className="graph-os-context-inspector">
        <header>
          <span>Definition Preview</span>
          <strong>{selectedGraph?.title || selectedGraph?.graph_id || "未选择图"}</strong>
        </header>
        {selectedGraph ? (
          <div className="graph-os-inspector-stack">
            <p><span>图 ID</span><strong>{selectedGraph.graph_id}</strong></p>
            <p><span>状态</span><strong>{selectedGraph.enabled ? "已发布" : selectedGraph.publish_state || "草稿"}</strong></p>
            <p><span>节点</span><strong>{selectedGraph.node_count ?? selectedGraph.nodes?.length ?? 0}</strong></p>
            <p><span>边</span><strong>{selectedGraph.edge_count ?? selectedGraph.edges?.length ?? 0}</strong></p>
            <p><span>入口</span><strong>{selectedGraph.entry_node_id || "未设置"}</strong></p>
          </div>
        ) : (
          <div className="graph-repository-compact-empty">还没有已保存图定义。</div>
        )}
      </aside>
    </section>
  );
}
