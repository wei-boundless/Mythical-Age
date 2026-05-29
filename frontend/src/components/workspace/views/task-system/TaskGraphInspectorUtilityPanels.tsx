import { Cable, FileWarning, GitBranch, Network } from "lucide-react";

import type { ComposableUnitSpec, GraphModuleExpansionSpec } from "@/lib/api";

import {
  TaskGraphInspectorSection,
  TaskGraphInspectorSummary,
} from "./TaskGraphInspectorPrimitives";
import type { TaskGraphComposableGraphOverlay } from "./taskGraphModuleComposition";
import type { TaskGraphComposableSubject } from "./taskGraphComposableEditorTypes";

export function TaskGraphUnmappedUnitPanel({ selected }: { selected: ComposableUnitSpec }) {
  return (
    <TaskGraphInspectorSection icon={<GitBranch aria-hidden="true" size={15} />} title="Unit" aside={selected.source_kind || "standard view"}>
      <TaskGraphInspectorSummary
        caption={selected.unit_id}
        overline={selected.unit_type}
        title={selected.title || selected.unit_id}
      />
      <div className="task-graph-note">
        <strong>该 Unit 未映射到可编辑节点</strong>
        <span>资源、工具或覆盖层 Unit 的完整表单将在 Interface / Port 覆盖层阶段开放；当前先通过原始节点或图模块编辑入口配置。</span>
      </div>
    </TaskGraphInspectorSection>
  );
}

export function TaskGraphInterfacePlaceholderPanel({ selectedSubject }: { selectedSubject: TaskGraphComposableSubject }) {
  if (selectedSubject.kind !== "interface" && selectedSubject.kind !== "port") return null;
  return (
    <TaskGraphInspectorSection icon={<Cable aria-hidden="true" size={15} />} title="接口端口" aside="只读预览">
      <div className="task-graph-note">
        <strong>接口覆盖层将在下一阶段开放</strong>
        <span>当前先通过 canonical 边、节点契约和图模块交接契约维护接口语义；标准视图端口边只做诊断投影。</span>
      </div>
    </TaskGraphInspectorSection>
  );
}

export function TaskGraphIssueInspector({ selectedSubject }: { selectedSubject: TaskGraphComposableSubject }) {
  if (selectedSubject.kind !== "issue") return null;
  return (
    <TaskGraphInspectorSection icon={<FileWarning aria-hidden="true" size={15} />} title="诊断问题" aside={selectedSubject.issue.severity}>
      <TaskGraphInspectorSummary
        caption={selectedSubject.issue.source}
        overline={`${selectedSubject.issue.scope}${selectedSubject.issue.target_id ? `:${selectedSubject.issue.target_id}` : ""}`}
        title={selectedSubject.issue.title}
      />
      <div className="task-graph-note task-graph-note--danger">
        <strong>处理说明</strong>
        <span>{selectedSubject.issue.detail}</span>
      </div>
    </TaskGraphInspectorSection>
  );
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function stringValue(value: unknown, fallback = "") {
  const next = String(value ?? "").trim();
  return next || fallback;
}

function expansionTitle(expansion: GraphModuleExpansionSpec) {
  const importedGraph = asRecord(expansion.imported_graph);
  return stringValue(importedGraph.title ?? expansion.linked_graph_id ?? expansion.unit_id, "导入图模块");
}

export function TaskGraphModuleExpansionInspector({
  expansion,
  onOpenGraph,
  selectedSubject,
}: {
  expansion: GraphModuleExpansionSpec | null;
  onOpenGraph?: (graphId: string) => void;
  selectedSubject: TaskGraphComposableSubject;
}) {
  if (
    selectedSubject.kind !== "graph_module_expansion"
    && selectedSubject.kind !== "graph_module_expansion_node"
    && selectedSubject.kind !== "graph_module_expansion_edge"
  ) {
    return null;
  }
  if (!expansion) {
    return (
      <TaskGraphInspectorSection icon={<Network aria-hidden="true" size={15} />} title="导入图模块" aside="未解析">
        <div className="task-graph-note task-graph-note--danger">
          <strong>没有找到模块拓扑</strong>
          <span>请确认 linked_graph_id 指向已保存的任务图，并刷新标准视图。</span>
        </div>
      </TaskGraphInspectorSection>
    );
  }

  const selectedNode = selectedSubject.kind === "graph_module_expansion_node"
    ? expansion.nodes?.find((node) => stringValue(node.scoped_node_id ?? node.node_id) === selectedSubject.scoped_node_id) ?? null
    : null;
  const selectedEdge = selectedSubject.kind === "graph_module_expansion_edge"
    ? expansion.edges?.find((edge) => stringValue(edge.scoped_edge_id ?? edge.edge_id) === selectedSubject.scoped_edge_id) ?? null
    : null;

  return (
    <>
      <TaskGraphInspectorSection icon={<Network aria-hidden="true" size={15} />} title="导入图模块" aside={expansion.linked_graph_id || "图模块"}>
        <TaskGraphInspectorSummary
          caption={expansion.plan_id || expansion.unit_id}
          metrics={[
            { label: "内部节点", value: expansion.nodes?.length ?? 0 },
            { label: "内部边", value: expansion.edges?.length ?? 0 },
            { label: "资源", value: expansion.resources?.length ?? 0 },
            { label: "诊断", value: expansion.issues?.length ?? 0 },
          ]}
          overline="编译期展开"
          title={expansionTitle(expansion)}
        />
        <div className="task-graph-note">
          <strong>模块内部拓扑只读</strong>
          <span>这里展示发布时会内联展开的节点、边和资源；修改内部结构需要进入该图模块自己的工作台。</span>
        </div>
        <div className="task-graph-topology-actions task-graph-topology-actions--stacked">
          <button disabled={!expansion.linked_graph_id || !onOpenGraph} onClick={() => expansion.linked_graph_id && onOpenGraph?.(expansion.linked_graph_id)} type="button">
            <Network aria-hidden="true" size={14} />
            <span>{expansion.linked_graph_id ? "进入图模块工作台" : "未绑定图模块"}</span>
          </button>
        </div>
      </TaskGraphInspectorSection>

      {selectedNode ? (
        <TaskGraphInspectorSection icon={<GitBranch aria-hidden="true" size={15} />} title="模块内部节点" aside={stringValue(selectedNode.node_type, "node")}>
          <TaskGraphInspectorSummary
            caption={stringValue(selectedNode.scoped_node_id ?? selectedNode.node_id)}
            metrics={[
              { label: "原始 ID", value: stringValue(selectedNode.node_id, "-") },
              { label: "阶段", value: stringValue(selectedNode.phase_id, "未分配") },
              { label: "旧坐标", value: stringValue(selectedNode.sequence_index, "0") },
              { label: "运行策略", value: stringValue(selectedNode.execution_mode, "sync") },
            ]}
            overline="只读拓扑"
            title={stringValue(selectedNode.title ?? selectedNode.node_id, "内部节点")}
          />
        </TaskGraphInspectorSection>
      ) : null}

      {selectedEdge ? (
        <TaskGraphInspectorSection icon={<Cable aria-hidden="true" size={15} />} title="模块内部边" aside={stringValue(selectedEdge.edge_type, "edge")}>
          <TaskGraphInspectorSummary
            caption={stringValue(selectedEdge.scoped_edge_id ?? selectedEdge.edge_id)}
            metrics={[
              { label: "原始 ID", value: stringValue(selectedEdge.edge_id, "-") },
              { label: "来源", value: stringValue(selectedEdge.source_node_id, "-") },
              { label: "目标", value: stringValue(selectedEdge.target_node_id, "-") },
              { label: "契约", value: stringValue(selectedEdge.payload_contract_id, "未声明") },
            ]}
            overline="只读拓扑"
            title={`${stringValue(selectedEdge.source_node_id, "?")} -> ${stringValue(selectedEdge.target_node_id, "?")}`}
          />
        </TaskGraphInspectorSection>
      ) : null}

      {expansion.issues?.length ? (
        <TaskGraphInspectorSection icon={<FileWarning aria-hidden="true" size={15} />} title="模块诊断" aside={`${expansion.issues.length}`}>
          <div className="task-graph-composer-object-list">
            {expansion.issues.map((issue, index) => (
              <div className="task-graph-composer-readonly-row" key={`${stringValue(issue.code, "issue")}:${index}`}>
                <strong>{stringValue(issue.code, "graph_module_issue")}</strong>
                <span>{stringValue(issue.message, "导入图模块解析异常。")}</span>
              </div>
            ))}
          </div>
        </TaskGraphInspectorSection>
      ) : null}
    </>
  );
}

export function TaskGraphOverlayStatusPanel({
  onNormalizeOverlay,
  overlay,
}: {
  onNormalizeOverlay: () => void;
  overlay: TaskGraphComposableGraphOverlay;
}) {
  return (
    <TaskGraphInspectorSection icon={<Cable aria-hidden="true" size={15} />} title="覆盖层状态" aside="metadata.composable_graph">
      <div className="task-graph-composer-kv">
        <p><span>Unit 覆盖</span><strong>{overlay.units.length}</strong></p>
        <p><span>Interface 覆盖</span><strong>{overlay.interfaces.length}</strong></p>
        <p><span>PortEdge 覆盖</span><strong>{overlay.port_edges.length}</strong></p>
        <p><span>图模块展开覆盖</span><strong>{overlay.graph_module_expansion.length}</strong></p>
      </div>
      {overlay.units.length || overlay.interfaces.length || overlay.graph_module_expansion.length ? (
        <button className="task-graph-composer-subtle-action" onClick={onNormalizeOverlay} type="button">
          重新规范化覆盖层
        </button>
      ) : null}
    </TaskGraphInspectorSection>
  );
}
