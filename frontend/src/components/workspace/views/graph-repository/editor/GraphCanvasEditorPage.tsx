"use client";

import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  FileText,
  Gauge,
  LayoutDashboard,
  MessageSquare,
  PanelBottom,
  PanelLeft,
  PanelRight,
  Settings2,
} from "lucide-react";
import type { OrchestrationAgentRuntimeCatalog, TaskGraphEdgeRecord, TaskGraphNodeRecord } from "@/lib/api";

import { inferTaskGraphBoundaryNodes, type TaskGraphDraftV2 } from "../../task-system/taskGraphDraftV2";
import { createEdgeFromRelation, taskGraphEdgeRelationRegistrations } from "../registry/taskGraphEdgeRelationRegistry";
import { createNodeFromRegistration, type TaskGraphNodeRegistration } from "../registry/taskGraphNodeRegistry";
import type { AgentWorldRegistration, ResourceWorldRegistration } from "../registry/taskGraphWorldRegistries";
import { TaskGraphInfiniteCanvas } from "../canvas/TaskGraphInfiniteCanvas";
import { autoSpreadGraphLayout } from "../canvas/taskGraphCanvasLayout";
import { graphCanvasMetadataPatch } from "../canvas/taskGraphCanvasSaveMapper";
import { draftEditorLayout, type GraphEditorLayout } from "../templates/graphTemplateTypes";
import { GraphTaskEditorToolbar } from "./GraphTaskEditorToolbar";
import { GraphTaskPropertyPanel } from "./GraphTaskPropertyPanel";
import { GraphTaskStatusBar } from "./GraphTaskStatusBar";
import { GraphTaskToolPanel } from "./GraphTaskToolPanel";
import { NodeConversationDock } from "./NodeConversationDock";

type GraphEditorViewMode = "balanced" | "canvas" | "config" | "conversation";
type GraphInspectorTab = "object" | "files" | "runtime" | "validation";
type GraphBottomTab = "conversation" | "problems" | "run";

type GraphDiagnostic = {
  severity: "error" | "warning" | "info";
  title: string;
  detail: string;
};

export function GraphCanvasEditorPage({
  agentCatalog,
  dirty,
  draft,
  graphRunId,
  instanceId,
  notice,
  onCreateInstance,
  onDraftChange,
  onDuplicate,
  onPublish,
  onSave,
  onSaveTemplate,
  saving,
  worldMode = "edit",
  worldPanel = null,
}: {
  agentCatalog: OrchestrationAgentRuntimeCatalog | null;
  dirty: boolean;
  draft: TaskGraphDraftV2;
  notice: string;
  saving: string;
  instanceId?: string;
  graphRunId?: string;
  onDraftChange: (draft: TaskGraphDraftV2) => void;
  onSave: () => void;
  onPublish: () => void;
  onDuplicate: () => void;
  onSaveTemplate: () => void;
  onCreateInstance: () => void;
  worldMode?: "edit" | "monitor";
  worldPanel?: ReactNode;
}) {
  const [selectedNodeId, setSelectedNodeId] = useState(draft.ui_state.selected_node_id || "");
  const [selectedEdgeId, setSelectedEdgeId] = useState(draft.ui_state.selected_edge_id || "");
  const [viewMode, setViewMode] = useState<GraphEditorViewMode>("balanced");
  const [inspectorTab, setInspectorTab] = useState<GraphInspectorTab>("object");
  const [bottomTab, setBottomTab] = useState<GraphBottomTab>("conversation");
  const layout = useMemo(() => draftEditorLayout(draft), [draft]);
  const diagnostics = useMemo(() => buildGraphDiagnostics(draft, layout), [draft, layout]);
  const isMonitorMode = worldMode === "monitor";

  useEffect(() => {
    setSelectedNodeId(draft.ui_state.selected_node_id || "");
    setSelectedEdgeId(draft.ui_state.selected_edge_id || "");
  }, [draft.graph_id, draft.ui_state.selected_edge_id, draft.ui_state.selected_node_id]);

  function commitTopology(nextNodes: TaskGraphNodeRecord[], nextEdges: TaskGraphEdgeRecord[], nextLayout = layout) {
    const boundaries = inferTaskGraphBoundaryNodes(nextNodes, nextEdges, {
      fallback_entry_node_id: draft.entry_node_id,
      fallback_output_node_id: draft.output_node_id,
    });
    const metadataPatch = graphCanvasMetadataPatch(nextLayout, nextNodes, nextEdges);
    onDraftChange({
      ...draft,
      nodes: nextNodes,
      edges: nextEdges,
      entry_node_id: boundaries.entry_node_id,
      output_node_id: boundaries.output_node_id,
      metadata: {
        ...(draft.metadata ?? {}),
        ...metadataPatch,
      },
      ui_state: {
        ...draft.ui_state,
        selected_node_id: selectedNodeId,
        selected_edge_id: selectedEdgeId,
        active_layer: "graph",
      },
    });
  }

  function commitLayout(nextLayout: GraphEditorLayout) {
    commitTopology(draft.nodes, draft.edges, nextLayout);
  }

  function addNode(registration: TaskGraphNodeRegistration) {
    const node = createNodeFromRegistration(registration, draft.nodes.length);
    const nextLayout = {
      ...layout,
      node_positions: {
        ...layout.node_positions,
        [node.node_id]: { x: 80 + draft.nodes.length * 34, y: 80 + draft.nodes.length * 28 },
      },
    };
    setSelectedNodeId(node.node_id);
    setSelectedEdgeId("");
    commitTopology([...draft.nodes, node], draft.edges, nextLayout);
  }

  function addAgent(agent: AgentWorldRegistration) {
    const nodeId = `node.${agent.agent_id.replace(/[^a-zA-Z0-9_.-]+/g, "_")}.${draft.nodes.length + 1}`;
    const node: TaskGraphNodeRecord = {
      node_id: nodeId,
      node_type: "agent",
      title: agent.displayName,
      role: agent.category,
      execution_mode: "sync",
      ...agent.defaultNodePatch,
      metadata: {
        ...(agent.defaultNodePatch.metadata ?? {}),
        visual_tone: agent.visual.tone,
        agent_world_ref: agent.agent_id,
        summary: agent.description || "来自 Agent 世界库的节点。",
      },
    };
    const nextLayout = {
      ...layout,
      node_positions: {
        ...layout.node_positions,
        [node.node_id]: { x: 120 + draft.nodes.length * 42, y: 180 + draft.nodes.length * 24 },
      },
    };
    setSelectedNodeId(node.node_id);
    setSelectedEdgeId("");
    commitTopology([...draft.nodes, node], draft.edges, nextLayout);
  }

  function addResource(resource: ResourceWorldRegistration) {
    const nodeId = `node.${resource.resource_id.replace(/[^a-zA-Z0-9_.-]+/g, "_")}.${draft.nodes.length + 1}`;
    const node: TaskGraphNodeRecord = {
      node_id: nodeId,
      node_type: resource.defaultNodePatch?.node_type || "artifact",
      title: resource.displayName,
      role: resource.kind,
      execution_mode: "sync",
      ...(resource.defaultNodePatch ?? {}),
      metadata: {
        ...(resource.defaultNodePatch?.metadata ?? {}),
        visual_tone: resource.visual.tone === "file" ? "artifact" : resource.visual.tone,
        resource_world_ref: resource.resource_id,
        summary: resource.description || "来自资源世界的可编排对象。",
      },
    };
    const nextLayout = {
      ...layout,
      node_positions: {
        ...layout.node_positions,
        [node.node_id]: { x: -220, y: 170 + draft.nodes.length * 54 },
      },
    };
    setSelectedNodeId(node.node_id);
    setSelectedEdgeId("");
    commitTopology([...draft.nodes, node], draft.edges, nextLayout);
  }

  function updateNode(nodeId: string, patch: Partial<TaskGraphNodeRecord>) {
    commitTopology(draft.nodes.map((node) => node.node_id === nodeId ? { ...node, ...patch } : node), draft.edges);
  }

  function updateEdge(edgeId: string, patch: Partial<TaskGraphEdgeRecord>) {
    commitTopology(draft.nodes, draft.edges.map((edge) => edge.edge_id === edgeId ? { ...edge, ...patch } : edge));
  }

  function updateEdges(nextEdges: TaskGraphEdgeRecord[]) {
    commitTopology(draft.nodes, nextEdges);
  }

  function autoLayout() {
    commitLayout(autoSpreadGraphLayout(draft.nodes, layout));
  }

  function addExplicitEdgeFromSelection() {
    if (!selectedNodeId) return;
    const target = draft.nodes.find((node) => node.node_id !== selectedNodeId);
    if (!target) return;
    const relation = taskGraphEdgeRelationRegistrations[0];
    const edge = createEdgeFromRelation(relation, selectedNodeId, target.node_id, draft.edges.length);
    setSelectedEdgeId(edge.edge_id);
    setSelectedNodeId("");
    setInspectorTab("object");
    commitTopology(draft.nodes, [...draft.edges, edge]);
  }

  return (
    <section className={`graph-repository-editor graph-repository-editor--${viewMode} graph-repository-editor--world-${worldMode}`} aria-label="任务图画布编辑器">
      <main className="graph-repository-canvas-region">
        <TaskGraphInfiniteCanvas
          editable={!isMonitorMode}
          edges={draft.edges}
          layout={layout}
          nodes={draft.nodes}
          onEdgesChange={updateEdges}
          onLayoutChange={commitLayout}
          onSelectionChange={(selection) => {
            setSelectedNodeId(selection.nodeId || "");
            setSelectedEdgeId(selection.edgeId || "");
            if (selection.nodeId || selection.edgeId) {
              setInspectorTab("object");
            }
          }}
          selectedEdgeId={selectedEdgeId}
          selectedNodeId={selectedNodeId}
        />
      </main>
      <div className="graph-editor-frame">
        {!isMonitorMode ? (
          <div className="graph-editor-top-dock">
            <GraphTaskEditorToolbar
              graphTitle={draft.title}
              onAutoLayout={autoLayout}
              onCreateInstance={onCreateInstance}
              onDuplicate={onDuplicate}
              onPublish={onPublish}
              onSave={onSave}
              onSaveTemplate={onSaveTemplate}
              saving={saving}
            />
            <GraphEditorViewModeSwitch value={viewMode} onChange={setViewMode} />
          </div>
        ) : null}

        {!isMonitorMode ? (
          <aside className="graph-editor-left-dock" aria-label="图世界对象库">
            <header className="graph-editor-dock-head">
              <div>
                <span>对象装配</span>
                <strong>节点、Agent 与资源</strong>
              </div>
              <PanelLeft size={15} />
            </header>
            <GraphTaskToolPanel
              agentCatalog={agentCatalog}
              onAddAgent={addAgent}
              onAddNode={addNode}
              onAddResource={addResource}
            />
          </aside>
        ) : null}

        <div className={isMonitorMode ? "graph-editor-canvas-brief graph-editor-canvas-brief--monitor" : "graph-editor-canvas-brief"} aria-label="画布关系说明">
          <div>
            <span>{isMonitorMode ? "监控态" : "自由坐标世界"}</span>
            <strong>{isMonitorMode ? "已封装任务图项目在同一张画布上运行" : "关系只来自显式节点、边和契约"}</strong>
          </div>
          {!isMonitorMode ? (
            <button disabled={!selectedNodeId || draft.nodes.length < 2} onClick={addExplicitEdgeFromSelection} type="button">
              添加显式边
            </button>
          ) : null}
        </div>

        {!isMonitorMode ? (
          <aside className="graph-editor-right-dock" aria-label="图对象检查器">
            <GraphEditorInspectorDock
              activeTab={inspectorTab}
              diagnostics={diagnostics}
              draft={draft}
              edges={draft.edges}
              graphId={draft.graph_id}
              layout={layout}
              nodes={draft.nodes}
              onEdgeChange={updateEdge}
              onGraphChange={(patch) => onDraftChange({ ...draft, ...patch })}
              onLayoutChange={commitLayout}
              onNodeChange={updateNode}
              onTabChange={setInspectorTab}
              selectedEdgeId={selectedEdgeId}
              selectedNodeId={selectedNodeId}
              title={draft.title}
            />
          </aside>
        ) : null}

        {!isMonitorMode ? (
          <section className="graph-editor-bottom-dock" aria-label="节点会话与运行信息">
            <GraphEditorBottomDock
              activeTab={bottomTab}
              diagnostics={diagnostics}
              draft={draft}
              graphRunId={graphRunId}
              instanceId={instanceId}
              onTabChange={setBottomTab}
              selectedEdgeId={selectedEdgeId}
              selectedNodeId={selectedNodeId}
            />
          </section>
        ) : null}

        {!isMonitorMode ? (
          <footer className="graph-editor-status-dock">
            <GraphTaskStatusBar dirty={dirty} draft={draft} notice={notice} />
          </footer>
        ) : null}
        {worldPanel ? (
          <aside className="graph-world-plugin-panel" aria-label="任务图世界插件面板">
            {worldPanel}
          </aside>
        ) : null}
      </div>
    </section>
  );
}

function GraphEditorViewModeSwitch({
  onChange,
  value,
}: {
  value: GraphEditorViewMode;
  onChange: (value: GraphEditorViewMode) => void;
}) {
  const options: Array<{ icon: typeof LayoutDashboard; label: string; value: GraphEditorViewMode }> = [
    { icon: LayoutDashboard, label: "均衡", value: "balanced" },
    { icon: Bot, label: "画布", value: "canvas" },
    { icon: Settings2, label: "配置", value: "config" },
    { icon: MessageSquare, label: "会话", value: "conversation" },
  ];
  return (
    <nav className="graph-editor-view-switch" aria-label="编辑器视图模式">
      {options.map((option) => {
        const Icon = option.icon;
        return (
          <button
            className={option.value === value ? "graph-editor-view-switch__item graph-editor-view-switch__item--active" : "graph-editor-view-switch__item"}
            key={option.value}
            onClick={() => onChange(option.value)}
            type="button"
          >
            <Icon size={14} />
            <span>{option.label}</span>
          </button>
        );
      })}
    </nav>
  );
}

function GraphEditorInspectorDock({
  activeTab,
  diagnostics,
  draft,
  edges,
  graphId,
  layout,
  nodes,
  onEdgeChange,
  onGraphChange,
  onLayoutChange,
  onNodeChange,
  onTabChange,
  selectedEdgeId,
  selectedNodeId,
  title,
}: {
  activeTab: GraphInspectorTab;
  diagnostics: GraphDiagnostic[];
  draft: TaskGraphDraftV2;
  edges: TaskGraphEdgeRecord[];
  graphId: string;
  layout: GraphEditorLayout;
  nodes: TaskGraphNodeRecord[];
  selectedNodeId: string;
  selectedEdgeId: string;
  title: string;
  onGraphChange: (patch: { title?: string }) => void;
  onNodeChange: (nodeId: string, patch: Partial<TaskGraphNodeRecord>) => void;
  onEdgeChange: (edgeId: string, patch: Partial<TaskGraphEdgeRecord>) => void;
  onLayoutChange: (layout: GraphEditorLayout) => void;
  onTabChange: (tab: GraphInspectorTab) => void;
}) {
  const selectedNode = nodes.find((node) => node.node_id === selectedNodeId) ?? null;
  const selectedEdge = edges.find((edge) => edge.edge_id === selectedEdgeId) ?? null;
  const objectTitle = selectedNode?.title || selectedNode?.node_id || selectedEdge?.edge_id || title || graphId;
  const tabs: Array<{ icon: typeof Settings2; label: string; value: GraphInspectorTab }> = [
    { icon: Settings2, label: selectedNode ? "节点" : selectedEdge ? "边" : "图", value: "object" },
    { icon: FileText, label: "文件角色", value: "files" },
    { icon: Gauge, label: "运行策略", value: "runtime" },
    { icon: CheckCircle2, label: "预检", value: "validation" },
  ];
  return (
    <div className="graph-editor-inspector">
      <header className="graph-editor-dock-head">
        <div>
          <span>检查器</span>
          <strong>{objectTitle}</strong>
        </div>
        <PanelRight size={15} />
      </header>
      <nav className="graph-editor-tab-strip" aria-label="检查器标签">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          return (
            <button
              className={activeTab === tab.value ? "graph-editor-tab graph-editor-tab--active" : "graph-editor-tab"}
              key={tab.value}
              onClick={() => onTabChange(tab.value)}
              type="button"
            >
              <Icon size={13} />
              <span>{tab.label}</span>
            </button>
          );
        })}
      </nav>
      <div className="graph-editor-inspector-body">
        {activeTab === "object" ? (
          <GraphTaskPropertyPanel
            edges={edges}
            graphId={graphId}
            layout={layout}
            nodes={nodes}
            onEdgeChange={onEdgeChange}
            onGraphChange={onGraphChange}
            onLayoutChange={onLayoutChange}
            onNodeChange={onNodeChange}
            selectedEdgeId={selectedEdgeId}
            selectedNodeId={selectedNodeId}
            title={title}
          />
        ) : null}
        {activeTab === "files" ? <GraphEditorFileRolesPanel draft={draft} /> : null}
        {activeTab === "runtime" ? <GraphEditorRuntimePolicyPanel draft={draft} /> : null}
        {activeTab === "validation" ? <GraphEditorDiagnosticsPanel diagnostics={diagnostics} /> : null}
      </div>
    </div>
  );
}

function GraphEditorBottomDock({
  activeTab,
  diagnostics,
  draft,
  graphRunId,
  instanceId,
  onTabChange,
  selectedEdgeId,
  selectedNodeId,
}: {
  activeTab: GraphBottomTab;
  diagnostics: GraphDiagnostic[];
  draft: TaskGraphDraftV2;
  instanceId?: string;
  graphRunId?: string;
  selectedNodeId: string;
  selectedEdgeId: string;
  onTabChange: (tab: GraphBottomTab) => void;
}) {
  const tabs: Array<{ icon: typeof MessageSquare; label: string; value: GraphBottomTab }> = [
    { icon: MessageSquare, label: "会话端口", value: "conversation" },
    { icon: AlertTriangle, label: "问题", value: "problems" },
    { icon: PanelBottom, label: "运行预览", value: "run" },
  ];
  return (
    <div className="graph-editor-bottom">
      <nav className="graph-editor-tab-strip graph-editor-tab-strip--bottom" aria-label="底部面板标签">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          const count = tab.value === "problems" ? diagnostics.length : 0;
          return (
            <button
              className={activeTab === tab.value ? "graph-editor-tab graph-editor-tab--active" : "graph-editor-tab"}
              key={tab.value}
              onClick={() => onTabChange(tab.value)}
              type="button"
            >
              <Icon size={13} />
              <span>{tab.label}</span>
              {count ? <em>{count}</em> : null}
            </button>
          );
        })}
      </nav>
      <div className="graph-editor-bottom-body">
        {activeTab === "conversation" ? (
          <NodeConversationDock
            edges={draft.edges}
            graphId={draft.graph_id}
            graphRunId={graphRunId}
            instanceId={instanceId}
            nodes={draft.nodes}
            selectedEdgeId={selectedEdgeId}
            selectedNodeId={selectedNodeId}
          />
        ) : null}
        {activeTab === "problems" ? <GraphEditorDiagnosticsPanel diagnostics={diagnostics} compact /> : null}
        {activeTab === "run" ? <GraphEditorRunPreview draft={draft} graphRunId={graphRunId} instanceId={instanceId} /> : null}
      </div>
    </div>
  );
}

function GraphEditorFileRolesPanel({ draft }: { draft: TaskGraphDraftV2 }) {
  const extensions = Array.isArray(draft.metadata?.workspace_extensions)
    ? draft.metadata.workspace_extensions as Array<Record<string, unknown>>
    : [];
  return (
    <section className="graph-editor-info-panel">
      <GraphEditorInfoList
        items={[
          { label: "实例文件空间", value: "随实例创建" },
          { label: "产物索引", value: "随运行累积" },
          { label: "工作台插件", value: extensions.length ? `${extensions.length} 个` : "使用模板默认配置" },
        ]}
      />
      <p>文件和产物属于监控态项目空间。模板只定义默认角色，用户可以在项目监控里查看、打开和投影。</p>
    </section>
  );
}

function GraphEditorRuntimePolicyPanel({ draft }: { draft: TaskGraphDraftV2 }) {
  const syncNodes = draft.nodes.filter((node) => (node.execution_mode || "sync") === "sync").length;
  const asyncNodes = draft.nodes.length - syncNodes;
  return (
    <section className="graph-editor-info-panel">
      <GraphEditorInfoList
        items={[
          { label: "发布状态", value: draft.publish_state === "published" || draft.publish_state === "run_bound" ? "可创建实例" : "草稿" },
          { label: "同步节点", value: String(syncNodes) },
          { label: "异步节点", value: String(asyncNodes) },
          { label: "入口节点", value: draft.entry_node_id || "按边关系推断" },
          { label: "输出节点", value: draft.output_node_id || "按边关系推断" },
        ]}
      />
      <p>运行顺序由显式边和节点契约决定。坐标只帮助用户组织世界，不参与调度判断。</p>
    </section>
  );
}

function GraphEditorDiagnosticsPanel({
  compact = false,
  diagnostics,
}: {
  compact?: boolean;
  diagnostics: GraphDiagnostic[];
}) {
  if (!diagnostics.length) {
    return (
      <section className="graph-editor-port-panel graph-editor-port-panel--empty">
        <div className="graph-editor-port-panel__header">
          <span><CheckCircle2 size={14} />预检</span>
          <strong>结构预检通过</strong>
        </div>
        <div className="graph-node-port-dock__facts graph-editor-port-panel__facts">
          <span>
            <em>错误</em>
            <strong>0</strong>
          </span>
          <span>
            <em>警告</em>
            <strong>0</strong>
          </span>
          <span>
            <em>状态</em>
            <strong>可继续</strong>
          </span>
        </div>
      </section>
    );
  }
  return (
    <section className={compact ? "graph-editor-port-panel graph-editor-diagnostics graph-editor-diagnostics--compact" : "graph-editor-port-panel graph-editor-diagnostics"}>
      <div className="graph-editor-port-panel__header">
        <span><AlertTriangle size={14} />预检</span>
        <strong>{diagnostics.length} 个问题</strong>
      </div>
      <div className="graph-editor-diagnostics__list">
        {diagnostics.map((item, index) => (
          <article className={`graph-editor-diagnostic graph-editor-diagnostic--${item.severity}`} key={`${item.severity}.${item.title}.${index}`}>
            <AlertTriangle size={14} />
            <div>
              <strong>{item.title}</strong>
              <span>{item.detail}</span>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function GraphEditorRunPreview({
  draft,
  graphRunId,
  instanceId,
}: {
  draft: TaskGraphDraftV2;
  instanceId?: string;
  graphRunId?: string;
}) {
  const publishReady = draft.publish_state === "published" || draft.publish_state === "run_bound";
  return (
    <section className="graph-editor-port-panel graph-editor-run-preview">
      <div className="graph-editor-port-panel__header">
        <span><PanelBottom size={14} />运行预览</span>
        <strong>{publishReady ? "可创建实例" : "需发布"}</strong>
      </div>
      <div className="graph-node-port-dock__facts graph-editor-port-panel__facts">
        {[
          { label: "实例", value: instanceId || "未连接实例" },
          { label: "运行", value: graphRunId || "未启动" },
          { label: "节点", value: `${draft.nodes.length} 个` },
          { label: "关系", value: `${draft.edges.length} 条` },
          { label: "状态", value: publishReady ? "可运行" : "草稿" },
        ].map((item) => (
          <span key={item.label} title={item.value}>
            <em>{item.label}</em>
            <strong>{item.value}</strong>
          </span>
        ))}
      </div>
    </section>
  );
}

function GraphEditorInfoList({ items }: { items: Array<{ label: string; value: string }> }) {
  return (
    <div className="graph-editor-info-list">
      {items.map((item) => (
        <p key={item.label}>
          <span>{item.label}</span>
          <strong>{item.value}</strong>
        </p>
      ))}
    </div>
  );
}

function buildGraphDiagnostics(draft: TaskGraphDraftV2, layout: GraphEditorLayout): GraphDiagnostic[] {
  const diagnostics: GraphDiagnostic[] = [];
  const nodeIds = new Set(draft.nodes.map((node) => node.node_id));
  if (!draft.nodes.length) {
    diagnostics.push({ severity: "error", title: "还没有节点", detail: "至少需要一个节点才能保存成可运行图。" });
  }
  if (draft.nodes.length > 1 && !draft.edges.length) {
    diagnostics.push({ severity: "warning", title: "节点之间没有显式关系", detail: "多节点图需要用边定义交接关系，坐标不会产生隐式编排。" });
  }
  for (const edge of draft.edges) {
    if (!nodeIds.has(edge.source_node_id) || !nodeIds.has(edge.target_node_id)) {
      diagnostics.push({ severity: "error", title: "边连接了不存在的节点", detail: edge.edge_id });
    }
  }
  const connectedNodeIds = new Set<string>();
  for (const edge of draft.edges) {
    connectedNodeIds.add(edge.source_node_id);
    connectedNodeIds.add(edge.target_node_id);
  }
  const isolatedNodes = draft.nodes.filter((node) => draft.nodes.length > 1 && !connectedNodeIds.has(node.node_id));
  if (isolatedNodes.length) {
    diagnostics.push({
      severity: "warning",
      title: "存在孤立节点",
      detail: isolatedNodes.slice(0, 3).map((node) => node.title || node.node_id).join("、"),
    });
  }
  const promptlessAgents = draft.nodes.filter((node) => {
    const prompt = asRecord(asRecord(node.contract_bindings).prompt).role_prompt;
    return node.node_type === "agent" && !String(prompt ?? "").trim();
  });
  if (promptlessAgents.length) {
    diagnostics.push({
      severity: "warning",
      title: "Agent 节点缺少角色说明",
      detail: promptlessAgents.slice(0, 3).map((node) => node.title || node.node_id).join("、"),
    });
  }
  if (!layout.home_node_id && draft.nodes.length) {
    diagnostics.push({ severity: "info", title: "未设置 home 坐标锚点", detail: "建议把主 agent 设为打开画布时的默认视角。" });
  }
  return diagnostics;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
