"use client";

import { Boxes, Cable, FileWarning, GitBranch, Layers3, Network } from "lucide-react";

import type { ComposableUnitSpec, GraphModuleExpansionPlanSpec, GraphModuleExpansionSpec, TaskGraphStandardView, UnitPortEdgeSpec } from "@/lib/api";

import type { TaskGraphDraftV2 } from "./taskGraphDraftV2";
import { taskGraphDisplayName } from "./taskGraphNameRegistry";
import type { TaskGraphModuleFacet } from "./taskGraphModuleComposition";
import { TASK_GRAPH_MODULE_FACET_ITEMS } from "./taskGraphModuleComposition";
import type { TaskGraphComposableSubject } from "./taskGraphComposableEditorTypes";
import { taskGraphComposableSubjectKey } from "./taskGraphComposableEditorTypes";
import type { TaskGraphPreflightIssue } from "./taskGraphPreflight";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function unitTypeLabel(type: string) {
  const labels: Record<string, string> = {
    node: "执行单元",
    graph: "图模块",
    resource: "资源单元",
    human_gate: "人工门控",
    tool: "工具单元",
    runtime_monitor: "运行监控",
  };
  return labels[type] ?? (type || "单元");
}

function unitTypeCounts(units: ComposableUnitSpec[]) {
  return units.reduce<Record<string, number>>((counts, unit) => {
    const type = unit.unit_type || "node";
    counts[type] = (counts[type] ?? 0) + 1;
    return counts;
  }, {});
}

function firstIssueForTarget(issues: TaskGraphPreflightIssue[], targetId: string) {
  return issues.find((issue) => issue.target_id === targetId);
}

function unitTitle(unit: ComposableUnitSpec, metadata: Record<string, unknown>) {
  return taskGraphDisplayName(unit.unit_id, unit as unknown as Record<string, unknown>, metadata, unit.title || unit.unit_id);
}

function edgeTitle(edge: UnitPortEdgeSpec) {
  return String(edge.payload_contract_id ?? edge.edge_type ?? edge.edge_id).trim() || edge.edge_id;
}

function edgeSummary(edge: UnitPortEdgeSpec) {
  return `${edge.source_unit_id}.${edge.source_port_id} -> ${edge.target_unit_id}.${edge.target_port_id}`;
}

function unitIcon(unitType: string) {
  if (unitType === "graph") return Network;
  if (unitType === "resource") return Boxes;
  return GitBranch;
}

function expansionTitle(expansion: GraphModuleExpansionSpec | null | undefined, fallback = "导入图模块") {
  const graph = asRecord(expansion?.imported_graph);
  return String(graph.title ?? expansion?.linked_graph_id ?? fallback).trim() || fallback;
}

export function TaskGraphGraphLayerRail({
  activeFacet,
  graphModuleExpansions,
  graphDraft,
  issues,
  graphModuleExpansionPlans,
  onOpenGraph,
  onFacetChange,
  onSelectSubject,
  portEdges,
  selectedSubject,
  standardView,
  standardViewLoading,
  units,
}: {
  activeFacet: TaskGraphModuleFacet;
  graphModuleExpansions: GraphModuleExpansionSpec[];
  graphDraft: TaskGraphDraftV2;
  issues: TaskGraphPreflightIssue[];
  graphModuleExpansionPlans: GraphModuleExpansionPlanSpec[];
  onOpenGraph?: (graphId: string) => void;
  onFacetChange: (facet: TaskGraphModuleFacet) => void;
  onSelectSubject: (subject: TaskGraphComposableSubject) => void;
  portEdges: UnitPortEdgeSpec[];
  selectedSubject: TaskGraphComposableSubject;
  standardView: TaskGraphStandardView | null;
  standardViewLoading?: boolean;
  units: ComposableUnitSpec[];
}) {
  const metadata = asRecord(graphDraft.metadata);
  const subjectKey = taskGraphComposableSubjectKey(selectedSubject);
  const counts = unitTypeCounts(units);
  const graphName = taskGraphDisplayName(graphDraft.graph_id, standardView?.graph, metadata, graphDraft.title || graphDraft.graph_id);
  const graphSubject: TaskGraphComposableSubject = { kind: "graph", graph_id: graphDraft.graph_id };
  const graphActive = subjectKey === taskGraphComposableSubjectKey(graphSubject);
  const graphIssueCount = issues.filter((issue) => issue.scope === "graph" || !issue.target_id).length;
  const visibleIssues = issues.slice(0, 6);
  const expansionByUnitId = new Map(graphModuleExpansions.map((item) => [item.unit_id, item]));

  return (
    <aside className="task-graph-composer-rail" aria-label="标准视图诊断">
      <section className="task-graph-composer-panel task-graph-composer-panel--identity">
        <header>
          <GitBranch aria-hidden="true" size={15} />
          <strong>当前图</strong>
        </header>
        <button
          className={graphActive ? "task-graph-composer-tree-card task-graph-composer-tree-card--active" : "task-graph-composer-tree-card"}
          onClick={() => onSelectSubject(graphSubject)}
          type="button"
        >
          <span>标准视图边界</span>
          <strong>{graphName}</strong>
          <small>{graphDraft.graph_id}</small>
          <em>{standardViewLoading ? "编译中" : `${units.length} 标准单元 / ${portEdges.length} 派生端口边`}</em>
        </button>
        <div className="task-graph-composer-mini-metrics">
          <p><span>图模块</span><strong>{counts.graph ?? 0}</strong></p>
          <p><span>资源</span><strong>{counts.resource ?? 0}</strong></p>
          <p><span>展开计划</span><strong>{graphModuleExpansionPlans.length}</strong></p>
          <p><span>问题</span><strong>{issues.length}</strong></p>
        </div>
        {graphIssueCount ? (
          <div className="task-graph-composer-inline-note">
            <FileWarning aria-hidden="true" size={14} />
            <span>{graphIssueCount} 个图级诊断等待处理</span>
          </div>
        ) : null}
      </section>

      <section className="task-graph-composer-panel">
        <header>
          <Layers3 aria-hidden="true" size={15} />
          <strong>诊断分面</strong>
        </header>
        <div className="task-graph-composer-facet-grid">
          {TASK_GRAPH_MODULE_FACET_ITEMS.map((facet) => (
            <button
              className={activeFacet === facet.id ? "active" : ""}
              key={facet.id}
              onClick={() => onFacetChange(facet.id)}
              type="button"
            >
              <strong>{facet.title}</strong>
              <span>{facet.desc}</span>
            </button>
          ))}
        </div>
      </section>

      <section className="task-graph-composer-panel">
        <header>
          <GitBranch aria-hidden="true" size={15} />
          <strong>节点树</strong>
        </header>
        <div className="task-graph-composer-object-list">
          {units.map((unit) => {
            const subject: TaskGraphComposableSubject = { kind: "unit", unit_id: unit.unit_id };
            const active = subjectKey === taskGraphComposableSubjectKey(subject);
            const issue = firstIssueForTarget(issues, unit.unit_id);
            const Icon = unitIcon(unit.unit_type);
            return (
              <button className={active ? "active" : ""} key={unit.unit_id} onClick={() => onSelectSubject(subject)} type="button">
                <Icon aria-hidden="true" size={14} />
                <span>
                  <strong>{unitTitle(unit, metadata)}</strong>
                  <small>{unitTypeLabel(unit.unit_type)} / {unit.phase_id || "phase.unassigned"}</small>
                </span>
                {issue ? <em>{issue.severity}</em> : null}
              </button>
            );
          })}
          {!units.length ? <div className="task-graph-composer-empty">标准视图尚未生成节点对象。</div> : null}
        </div>
      </section>

      <section className="task-graph-composer-panel">
        <header>
          <Cable aria-hidden="true" size={15} />
          <strong>交接边</strong>
        </header>
        <div className="task-graph-composer-object-list">
          {portEdges.map((edge) => {
            const subject: TaskGraphComposableSubject = { kind: "port_edge", edge_id: edge.edge_id };
            const active = subjectKey === taskGraphComposableSubjectKey(subject);
            const issue = firstIssueForTarget(issues, edge.edge_id);
            return (
              <button className={active ? "active" : ""} key={edge.edge_id} onClick={() => onSelectSubject(subject)} type="button">
                <Cable aria-hidden="true" size={14} />
                <span>
                  <strong>{edgeTitle(edge)}</strong>
                  <small>{edgeSummary(edge)}</small>
                </span>
                {issue ? <em>{issue.severity}</em> : null}
              </button>
            );
          })}
          {!portEdges.length ? <div className="task-graph-composer-empty">当前标准视图还没有派生端口边。</div> : null}
        </div>
      </section>

      <section className="task-graph-composer-panel">
        <header>
          <Network aria-hidden="true" size={15} />
          <strong>导入图模块</strong>
        </header>
        <div className="task-graph-composer-object-list">
          {units.filter((unit) => unit.unit_type === "graph").map((unit) => {
            const expansion = expansionByUnitId.get(unit.unit_id);
            const subject: TaskGraphComposableSubject = { kind: "graph_module_expansion", unit_id: unit.unit_id, plan_id: expansion?.plan_id };
            const active = subjectKey === taskGraphComposableSubjectKey(subject)
              || (selectedSubject.kind === "graph_module_expansion_node" && selectedSubject.unit_id === unit.unit_id)
              || (selectedSubject.kind === "graph_module_expansion_edge" && selectedSubject.unit_id === unit.unit_id);
            const linkedGraphId = String(asRecord(unit.ref).graph_id ?? expansion?.linked_graph_id ?? "").trim();
            const issue = firstIssueForTarget(issues, unit.unit_id);
            return (
              <button
                className={active ? "active" : ""}
                key={unit.unit_id}
                onClick={() => onSelectSubject(subject)}
                type="button"
              >
                <Network aria-hidden="true" size={14} />
                <span>
                  <strong>{expansionTitle(expansion, unit.title || unit.unit_id)}</strong>
                  <small>{linkedGraphId || "未绑定 linked_graph_id"} / {(expansion?.nodes?.length ?? 0)} 节点</small>
                </span>
                {issue ? <em>{issue.severity}</em> : expansion?.issues?.length ? <em>issue</em> : null}
              </button>
            );
          })}
          {!units.some((unit) => unit.unit_type === "graph") ? <div className="task-graph-composer-empty">canonical 图模块节点绑定 linked_graph_id 后会形成导入图模块诊断。</div> : null}
        </div>
      </section>

      <section className="task-graph-composer-panel">
        <header>
          <Boxes aria-hidden="true" size={15} />
          <strong>单元分类</strong>
        </header>
        <div className="task-graph-composer-type-list">
          {Object.entries(counts).map(([type, count]) => (
            <button key={type} onClick={() => onFacetChange("units")} type="button">
              <span>{unitTypeLabel(type)}</span>
              <strong>{count}</strong>
            </button>
          ))}
          {!Object.keys(counts).length ? <div className="task-graph-composer-empty">标准视图尚未生成可组合单元。</div> : null}
        </div>
      </section>

      <section className="task-graph-composer-panel">
        <header>
          <Network aria-hidden="true" size={15} />
          <strong>模块工作台</strong>
        </header>
        <div className="task-graph-composer-object-list">
          {units.filter((unit) => unit.unit_type === "graph").map((unit) => {
            const subject: TaskGraphComposableSubject = { kind: "unit", unit_id: unit.unit_id };
            const active = subjectKey === taskGraphComposableSubjectKey(subject);
            const linkedGraphId = String(asRecord(unit.ref).graph_id ?? "").trim();
            return (
              <button
                className={active ? "active" : ""}
                key={unit.unit_id}
                onClick={() => {
                  if (active && linkedGraphId && onOpenGraph) {
                    onOpenGraph(linkedGraphId);
                    return;
                  }
                  onSelectSubject(subject);
                }}
                type="button"
              >
                <Network aria-hidden="true" size={14} />
                <span>
                  <strong>{unit.title || unit.unit_id}</strong>
                  <small>{linkedGraphId ? `${linkedGraphId} · 再点进入` : "未绑定 linked_graph_id"}</small>
                </span>
              </button>
            );
          })}
          {!units.some((unit) => unit.unit_type === "graph") ? (
            <div className="task-graph-composer-empty">阶段图块绑定 linked_graph_id 后会派生导入图模块。</div>
          ) : null}
        </div>
      </section>

      <section className="task-graph-composer-panel">
        <header>
          <Cable aria-hidden="true" size={15} />
          <strong>诊断定位</strong>
        </header>
        <div className="task-graph-composer-object-list">
          {visibleIssues.map((issue) => {
            const subject: TaskGraphComposableSubject = { kind: "issue", issue };
            const active = subjectKey === taskGraphComposableSubjectKey(subject);
            return (
              <button className={active ? "active" : ""} key={issue.issue_id} onClick={() => onSelectSubject(subject)} type="button">
                <FileWarning aria-hidden="true" size={14} />
                <span>
                  <strong>{issue.title}</strong>
                  <small>{issue.scope}{issue.target_id ? `:${issue.target_id}` : ""}</small>
                </span>
                <em>{issue.severity}</em>
              </button>
            );
          })}
          {!visibleIssues.length ? <div className="task-graph-composer-empty">当前没有可组合图诊断。</div> : null}
        </div>
      </section>
    </aside>
  );
}
