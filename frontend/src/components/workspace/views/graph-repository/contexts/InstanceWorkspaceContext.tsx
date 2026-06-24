"use client";

import { PlayCircle, RefreshCw } from "lucide-react";
import type { GraphTaskInstanceSummary, TaskGraphRecord } from "@/lib/api";

import { GraphInstanceList } from "../GraphInstanceList";
import { GraphInstanceWorkspace } from "../instance/GraphInstanceWorkspace";
import type { GraphInstanceWorkspaceExtension } from "../templates/graphTemplateTypes";

export function InstanceWorkspaceContext({
  activeGraph,
  extensions,
  instances,
  instancesLoading,
  onRefreshInstances,
  onSelectInstance,
  selectedInstance,
  selectedInstanceId,
}: {
  activeGraph: TaskGraphRecord | null;
  instances: GraphTaskInstanceSummary[];
  instancesLoading: boolean;
  selectedInstance: GraphTaskInstanceSummary | null;
  selectedInstanceId: string;
  extensions: GraphInstanceWorkspaceExtension[];
  onRefreshInstances: () => void;
  onSelectInstance: (instance: GraphTaskInstanceSummary) => void;
}) {
  return (
    <section className="graph-os-instance-context" aria-label="实例工作台上下文">
      <aside className="graph-os-instance-sidebar">
        <header>
          <div>
            <span>实例上下文</span>
            <strong>{activeGraph ? activeGraph.title || activeGraph.graph_id : "未选择图"}</strong>
          </div>
          <button onClick={onRefreshInstances} title="刷新实例" type="button">
            <RefreshCw size={14} />
          </button>
        </header>
        <GraphInstanceList
          activeGraph={activeGraph}
          instances={instances}
          loading={instancesLoading}
          onRefresh={onRefreshInstances}
          onSelectInstance={onSelectInstance}
          selectedInstanceId={selectedInstanceId}
          showHeader={false}
        />
      </aside>
      <div className="graph-os-instance-main">
        {selectedInstance ? (
          <GraphInstanceWorkspace extensions={extensions} instance={selectedInstance} />
        ) : (
          <section className="graph-os-empty-context">
            <PlayCircle size={24} />
            <strong>还没有可打开的实例</strong>
            <p>从已发布图创建实例后，这里会显示文件、产物、节点会话和运行监控。</p>
          </section>
        )}
      </div>
    </section>
  );
}
