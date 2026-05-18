"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, GitBranch, ListChecks, Plus, ShieldAlert } from "lucide-react";

import type { TaskGraphStandardView } from "@/lib/api";

import { buildTaskGraphResourceStandardModel } from "./taskGraphStandardView";
import type { TaskGraphDraftV2 } from "./taskGraphDraftV2";
import type { TaskGraphEditorFocus } from "./taskGraphEditorFocus";
import { taskGraphEdgeId, taskGraphEdgeSource, taskGraphEdgeTarget } from "./taskGraphMemoryMatrix";
import { TaskSystemField, taskSystemOptionLabel } from "./TaskSystemWorkbenchUi";

type RiskFacet = "ledgers" | "handoff" | "boundaries";

type LedgerTemplate = {
  kind: "thread_ledger" | "issue_ledger";
  title: string;
  idPrefix: string;
  description: string;
  collections: Array<{ collection_id: string; title: string; record_kinds: string[] }>;
};

const LEDGER_TEMPLATES: LedgerTemplate[] = [
  {
    kind: "thread_ledger",
    title: "线程账本",
    idPrefix: "thread.ledger",
    description: "记录持续任务的当前位置、恢复锚点、延期项和跨阶段交接状态。",
    collections: [
      { collection_id: "threads", title: "线程状态", record_kinds: ["thread_state", "resume_anchor", "handoff_checkpoint"] },
      { collection_id: "decisions", title: "决策记录", record_kinds: ["decision", "invalidation", "continuation_note"] },
    ],
  },
  {
    kind: "issue_ledger",
    title: "问题台账",
    idPrefix: "issue.ledger",
    description: "记录阻断项、缺陷、修复裁决和审核闭环，不承载正文上下文。",
    collections: [
      { collection_id: "issues", title: "问题项", record_kinds: ["blocker", "defect", "risk"] },
      { collection_id: "resolutions", title: "处理结论", record_kinds: ["fix", "review_verdict", "waiver"] },
    ],
  },
];

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function nodeIdOf(node: Record<string, unknown>, index = 0) {
  return String(node.node_id ?? node.id ?? `node_${index + 1}`).trim();
}

function nodeTitle(node: Record<string, unknown>, index = 0) {
  return String(node.title ?? node.label ?? node.task_title ?? nodeIdOf(node, index)).trim();
}

function nodeTypeOf(node: Record<string, unknown>) {
  return String(node.node_type ?? "").trim();
}

function isThreadLedgerType(nodeType: string) {
  return nodeType === "thread_ledger" || nodeType === "progress_ledger";
}

function isRiskLedgerNode(node: Record<string, unknown>) {
  const nodeType = nodeTypeOf(node);
  return isThreadLedgerType(nodeType) || nodeType === "issue_ledger";
}

function ledgerKindLabel(nodeType: string) {
  if (nodeType === "issue_ledger") return "问题台账";
  if (nodeType === "progress_ledger") return "线程账本（旧名）";
  return "线程账本";
}

function repositoryCollections(node: Record<string, unknown>) {
  const metadata = asRecord(node.metadata);
  const repository = asRecord(metadata.memory_repository);
  const collections = Array.isArray(repository.collections) ? repository.collections : Array.isArray(metadata.collections) ? metadata.collections : [];
  return collections.length ? collections : ["default"];
}

function edgeTouchesNode(edge: Record<string, unknown>, nodeId: string) {
  return taskGraphEdgeSource(edge) === nodeId || taskGraphEdgeTarget(edge) === nodeId;
}

function isMemoryEdge(edge: Record<string, unknown>) {
  return String(edge.edge_type ?? edge.mode ?? "").startsWith("memory_");
}

function isRiskRelevantIssue(issue: { code?: string; message?: string; source?: string }) {
  const text = `${issue.code ?? ""} ${issue.message ?? ""} ${issue.source ?? ""}`.toLowerCase();
  return ["ledger", "risk", "issue", "thread", "memory", "context", "commit", "selector", "handoff"].some((token) => text.includes(token));
}

export function TaskGraphRiskGovernancePage({
  activeGraphEdges,
  activeGraphNodes,
  taskGraphDraft,
  updateTaskGraphDraft,
  editorFocus,
  onEditorFocus,
  standardView,
  standardViewLoading,
}: {
  activeGraphNodes: Array<Record<string, unknown>>;
  activeGraphEdges: Array<Record<string, unknown>>;
  taskGraphDraft: TaskGraphDraftV2;
  updateTaskGraphDraft: (patch: Partial<TaskGraphDraftV2>) => void;
  editorFocus?: TaskGraphEditorFocus;
  onEditorFocus?: (focus: Partial<TaskGraphEditorFocus> & { layer?: TaskGraphEditorFocus["layer"] }) => void;
  standardView: TaskGraphStandardView | null;
  standardViewLoading?: boolean;
}) {
  const [facet, setFacet] = useState<RiskFacet>("ledgers");
  const ledgerNodes = useMemo(() => activeGraphNodes.filter(isRiskLedgerNode), [activeGraphNodes]);
  const firstLedgerId = ledgerNodes[0] ? nodeIdOf(ledgerNodes[0]) : "";
  const [selectedLedgerNodeId, setSelectedLedgerNodeId] = useState(firstLedgerId);
  const selectedLedger = ledgerNodes.find((node) => nodeIdOf(node) === selectedLedgerNodeId) ?? ledgerNodes[0] ?? null;
  const selectedLedgerId = selectedLedger ? nodeIdOf(selectedLedger) : "";
  const standardResourceModel = useMemo(() => buildTaskGraphResourceStandardModel(standardView), [standardView]);
  const riskIssues = (standardView?.issues ?? []).filter(isRiskRelevantIssue);
  const memoryEdges = activeGraphEdges.filter(isMemoryEdge);
  const selectedLedgerEdges = selectedLedgerId ? memoryEdges.filter((edge) => edgeTouchesNode(edge, selectedLedgerId)) : [];
  const boundaryRisks = [
    {
      title: "上下文污染",
      state: memoryEdges.some((edge) => !String(asRecord(edge.metadata).usage_instruction ?? "").trim()) ? "需补充" : "已约束",
      detail: "读取边必须声明使用说明，避免节点把参考资料当成事实或把候选写入当成已提交记录。",
    },
    {
      title: "提交可见性",
      state: memoryEdges.some((edge) => String(edge.edge_type ?? edge.mode ?? "") === "memory_commit" && !Object.keys(asRecord(asRecord(edge.metadata).commit_visibility_policy)).length) ? "需补充" : "已约束",
      detail: "提交边需要说明从哪个 clock 或作用域起对后续节点可见，防止未来信息泄漏。",
    },
    {
      title: "续接锚点",
      state: standardResourceModel.threadLedgerResources.length ? "已建账本" : "缺少账本",
      detail: "长任务需要线程账本记录当前位置、暂停原因、恢复输入和失效条件。",
    },
  ];

  useEffect(() => {
    if (selectedLedgerNodeId || !firstLedgerId) return;
    setSelectedLedgerNodeId(firstLedgerId);
  }, [firstLedgerId, selectedLedgerNodeId]);

  useEffect(() => {
    if (editorFocus?.layer !== "risk") return;
    const nextFacet = String(editorFocus.facet ?? "");
    if (["ledgers", "handoff", "boundaries"].includes(nextFacet)) {
      setFacet(nextFacet as RiskFacet);
    }
    if (editorFocus.repository_id || editorFocus.node_id) {
      setSelectedLedgerNodeId(String(editorFocus.repository_id ?? editorFocus.node_id ?? ""));
    }
  }, [editorFocus?.facet, editorFocus?.layer, editorFocus?.node_id, editorFocus?.repository_id]);

  const createLedgerNode = (template: LedgerTemplate) => {
    const existingIds = new Set(activeGraphNodes.map((node) => String(node.node_id ?? "")));
    let index = 1;
    let nodeId = `${template.idPrefix}.${index}`;
    while (existingIds.has(nodeId)) {
      index += 1;
      nodeId = `${template.idPrefix}.${index}`;
    }
    updateTaskGraphDraft({
      nodes: [
        ...(taskGraphDraft.nodes ?? []),
        {
          node_id: nodeId,
          node_type: template.kind,
          title: template.title,
          role: "resource",
          work_posture: "resource",
          resource_lifecycle_policy: { versioning: "append_version", mutable: true, commit_required: true },
          metadata: {
            memory_repository: {
              repository_id: nodeId,
              schema_id: "schema.risk_ledger_record",
              collections: template.collections.map((collection) => ({
                ...collection,
                key_strategy: "stable_key",
                default_version_selector: "latest_committed_before_clock",
                required_commit_status: "committed",
              })),
            },
            governance_role: template.kind,
          },
        },
      ],
    });
    setSelectedLedgerNodeId(nodeId);
    onEditorFocus?.({ layer: "risk", facet: "ledgers", node_id: nodeId, repository_id: nodeId });
  };

  return (
    <section className="task-graph-studio-page">
      <header className="task-graph-studio-page__head">
        <span>TaskGraph Studio</span>
        <strong>风险治理</strong>
        <small>用线程账本、问题台账和边界检查管理长任务续接、节点交接和上下文污染风险。</small>
      </header>

      <section className="task-graph-facet-switch" aria-label="风险治理分面">
        {[
          ["ledgers", "治理账本", "thread / issue"],
          ["handoff", "交接续接", "handoff / resume"],
          ["boundaries", "边界风险", "context / commit"],
        ].map(([id, title, desc]) => (
          <button className={facet === id ? "active" : ""} key={id} onClick={() => setFacet(id as RiskFacet)} type="button">
            <strong>{title}</strong>
            <span>{desc}</span>
          </button>
        ))}
      </section>

      <section className="task-graph-standard-board" aria-label="风险标准对象摘要">
        <article className="boundary-card task-graph-standard-card">
          <header><strong>治理资源对象</strong><span>{standardViewLoading ? "编译中" : `${standardResourceModel.riskResources.length} ledgers`}</span></header>
          <div className="task-graph-mini-kv">
            <p><span>线程账本</span><strong>{standardResourceModel.threadLedgerResources.length}</strong></p>
            <p><span>问题台账</span><strong>{standardResourceModel.issueLedgerResources.length}</strong></p>
            <p><span>相关记忆边</span><strong>{Object.values(standardResourceModel.riskEdgeCountByRepository).reduce((sum, count) => sum + count, 0)}</strong></p>
            <p><span>风险诊断</span><strong>{riskIssues.length}</strong></p>
          </div>
        </article>
        <article className="boundary-card task-graph-standard-card">
          <header><strong>边界状态</strong><span>通用风险逻辑</span></header>
          <div className="task-graph-standard-list">
            {boundaryRisks.map((risk) => (
              <article className="task-graph-standard-list__item" key={risk.title}>
                <strong>{risk.title}</strong>
                <span>{risk.detail}</span>
                <em>{risk.state}</em>
              </article>
            ))}
          </div>
        </article>
      </section>

      {facet === "ledgers" ? (
        <section className="task-graph-cognition-workbench">
          <aside className="task-graph-cognition-workbench__nav boundary-card">
            <header><strong>账本节点</strong><span>{ledgerNodes.length} 个</span></header>
            <div className="task-graph-cognition-list">
              {ledgerNodes.map((node, index) => {
                const nodeId = nodeIdOf(node, index);
                const nodeType = nodeTypeOf(node);
                return (
                  <button
                    className={selectedLedgerId === nodeId ? "task-graph-memory-list-button task-graph-memory-list-button--active" : "task-graph-memory-list-button"}
                    key={nodeId}
                    onClick={() => {
                      setSelectedLedgerNodeId(nodeId);
                      onEditorFocus?.({ layer: "risk", facet: "ledgers", node_id: nodeId, repository_id: nodeId });
                    }}
                    type="button"
                  >
                    <strong>{nodeTitle(node, index)}</strong>
                    <span>{nodeId}</span>
                    <em>{ledgerKindLabel(nodeType)}</em>
                  </button>
                );
              })}
              {!ledgerNodes.length ? <div className="task-graph-note"><strong>尚未建立治理账本</strong><span>创建线程账本和问题台账后，长任务续接和问题闭环才有标准记录位置。</span></div> : null}
            </div>
          </aside>
          <div className="task-graph-cognition-workbench__main">
            <section className="task-graph-form-grid">
              {LEDGER_TEMPLATES.map((template) => (
                <article className="boundary-card task-graph-layer-explainer" key={template.kind}>
                  <header><strong>{template.title}</strong><span>{template.kind}</span></header>
                  <div className="task-graph-note">
                    <strong>{template.description}</strong>
                    <span>{template.collections.map((collection) => collection.title).join(" / ")}</span>
                  </div>
                  <button className="boundary-button boundary-button--primary" onClick={() => createLedgerNode(template)} type="button">
                    <Plus aria-hidden="true" size={15} />
                    <span>创建{template.title}</span>
                  </button>
                </article>
              ))}
            </section>
            <article className="boundary-card">
              <header><strong>账本细节</strong><span>{selectedLedgerId || "未选择"}</span></header>
              {selectedLedger ? (
                <>
                  <div className="task-graph-mini-kv">
                    <p><span>类型</span><strong>{ledgerKindLabel(nodeTypeOf(selectedLedger))}</strong></p>
                    <p><span>集合</span><strong>{repositoryCollections(selectedLedger).length}</strong></p>
                    <p><span>关联边</span><strong>{selectedLedgerEdges.length}</strong></p>
                    <p><span>节点 ID</span><strong>{selectedLedgerId}</strong></p>
                  </div>
                  <div className="task-graph-standard-list">
                    {repositoryCollections(selectedLedger).map((collection, index) => {
                      const record = typeof collection === "string" ? { collection_id: collection, title: collection } : asRecord(collection);
                      return (
                        <article className="task-graph-standard-list__item" key={String(record.collection_id ?? index)}>
                          <strong>{String(record.title ?? record.collection_id ?? `collection_${index + 1}`)}</strong>
                          <span>{Array.isArray(record.record_kinds) ? record.record_kinds.join(" / ") : "未声明 record_kinds"}</span>
                          <em>{String(record.collection_id ?? "default")}</em>
                        </article>
                      );
                    })}
                  </div>
                </>
              ) : (
                <div className="task-graph-note"><strong>没有选中的账本</strong><span>先创建或选择一个治理账本。</span></div>
              )}
            </article>
          </div>
          <aside className="task-graph-cognition-workbench__aside">
            <article className="boundary-card">
              <header><strong>账本契约</strong><span>通用逻辑</span></header>
              <div className="task-graph-note">
                <strong>线程账本只记录进程状态</strong>
                <span>它不替代基准库和动态记忆库，只负责告诉运行系统当前线程如何恢复、哪些记录已经失效、哪些节点需要接续。</span>
              </div>
              <div className="task-graph-note">
                <strong>问题台账只记录风险闭环</strong>
                <span>问题台账承载 blocker、defect、fix、waiver 和 review verdict，避免把风险管理混进正文上下文。</span>
              </div>
            </article>
          </aside>
        </section>
      ) : null}

      {facet === "handoff" ? (
        <section className="boundary-card">
          <header><strong>账本交接边</strong><span>{selectedLedgerEdges.length} 条</span></header>
          <div className="task-graph-standard-list">
            {selectedLedgerEdges.map((edge, index) => (
              <article className="task-graph-standard-list__item" key={taskGraphEdgeId(edge, index)}>
                <strong>{taskSystemOptionLabel(String(edge.edge_type ?? edge.mode ?? "handoff"))}</strong>
                <span>{taskGraphEdgeSource(edge)} {"->"} {taskGraphEdgeTarget(edge)}</span>
                <em>{taskGraphEdgeId(edge, index)}</em>
              </article>
            ))}
            {!selectedLedgerEdges.length ? <div className="task-graph-note"><strong>没有账本交接边</strong><span>为写入候选、提交或恢复读取建立 memory_* 边后，这里会显示交接路径。</span></div> : null}
          </div>
        </section>
      ) : null}

      {facet === "boundaries" ? (
        <section className="task-graph-form-grid">
          <article className="boundary-card task-graph-layer-explainer">
            <header><ShieldAlert aria-hidden="true" size={16} /><strong>边界风险</strong><span>{boundaryRisks.length} 类</span></header>
            <div className="task-graph-standard-list">
              {boundaryRisks.map((risk) => (
                <article className="task-graph-standard-list__item" key={risk.title}>
                  <strong>{risk.title}</strong>
                  <span>{risk.detail}</span>
                  <em>{risk.state}</em>
                </article>
              ))}
            </div>
          </article>
          <article className="boundary-card task-graph-layer-explainer">
            <header><AlertTriangle aria-hidden="true" size={16} /><strong>标准视图诊断</strong><span>{riskIssues.length} 条</span></header>
            <div className="task-graph-standard-list">
              {riskIssues.slice(0, 20).map((issue, index) => (
                <article className="task-graph-standard-list__item" key={`${issue.code}:${issue.node_id}:${issue.edge_id}:${index}`}>
                  <strong>{issue.code}</strong>
                  <span>{issue.message}</span>
                  <em>{issue.severity}</em>
                </article>
              ))}
              {!riskIssues.length ? <div className="task-graph-note"><strong>暂无风险诊断</strong><span>标准对象视图没有返回账本、记忆或上下文边界相关问题。</span></div> : null}
            </div>
          </article>
          <article className="boundary-card task-graph-layer-explainer">
            <header><GitBranch aria-hidden="true" size={16} /><strong>检查准则</strong><span>运行前</span></header>
            <TaskSystemField label="线程续接需要">
              <input readOnly value="resume_anchor / continuation_note / invalidation" />
            </TaskSystemField>
            <TaskSystemField label="问题闭环需要">
              <input readOnly value="blocker / fix / review_verdict / waiver" />
            </TaskSystemField>
            <TaskSystemField label="上下文防污染需要">
              <input readOnly value="selector / usage_instruction / commit_visibility_policy" />
            </TaskSystemField>
          </article>
          <article className="boundary-card task-graph-layer-explainer">
            <header><ListChecks aria-hidden="true" size={16} /><strong>治理边界</strong><span>不写正文</span></header>
            <div className="task-graph-note">
              <strong>风险治理层不替代资源流</strong>
              <span>资源流决定节点能读写什么；风险治理决定哪些持续线程、问题和边界条件必须被追踪。</span>
            </div>
          </article>
        </section>
      ) : null}
    </section>
  );
}
