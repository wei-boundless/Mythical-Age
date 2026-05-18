"use client";

import { useMemo } from "react";
import type { ContractSpec } from "@/lib/api";

import { TaskGraphEdgeStandardPage } from "./TaskGraphEdgeStandardPage";
import { TaskSystemField } from "./TaskSystemWorkbenchUi";
import type { TaskGraphDraftV2 } from "./taskGraphDraftV2";
import type { TaskGraphEditorFocus } from "./taskGraphEditorFocus";
import { buildTaskGraphCognitionModel } from "./taskGraphCognitionView";

function contractTitle(contract: ContractSpec) {
  return String(contract.contract_id);
}

function nodeTitle(node: Record<string, unknown>) {
  return String(node.title ?? node.label ?? node.node_id ?? "节点");
}

function edgeSource(edge: Record<string, unknown>) {
  return String(edge.source_node_id ?? edge.from ?? edge.source ?? "");
}

function edgeTarget(edge: Record<string, unknown>) {
  return String(edge.target_node_id ?? edge.to ?? edge.target ?? "");
}

export function TaskGraphContractQualityPage({
  activeGraphEdges,
  activeGraphNodes,
  contractSpecs,
  editorIssueCount,
  editorValid,
  editorFocus,
  onEditorFocus,
  selectedGraphEdge,
  selectedGraphEdgeId,
  standardView,
  taskGraphDraft,
  updateTaskGraph,
  updateTaskGraphEdge,
  updateTaskGraphNode,
}: {
  activeGraphEdges: Array<Record<string, unknown>>;
  activeGraphNodes: Array<Record<string, unknown>>;
  contractSpecs: ContractSpec[];
  editorIssueCount: number;
  editorValid: boolean;
  editorFocus?: TaskGraphEditorFocus;
  onEditorFocus?: (focus: Partial<TaskGraphEditorFocus> & { layer?: TaskGraphEditorFocus["layer"] }) => void;
  selectedGraphEdge: Record<string, unknown> | null;
  selectedGraphEdgeId: string;
  standardView: import("@/lib/api").TaskGraphStandardView | null;
  taskGraphDraft: TaskGraphDraftV2;
  updateTaskGraph: (patch: Partial<TaskGraphDraftV2>) => void;
  updateTaskGraphEdge: (edgeId: string, patch: Record<string, unknown>) => void;
  updateTaskGraphNode: (nodeId: string, patch: Record<string, unknown>) => void;
}) {
  const graphContractId = String(taskGraphDraft.graph_contract_id ?? "");
  const contractIds = contractSpecs.map((item) => item.contract_id);
  const cognitionModel = useMemo(
    () => buildTaskGraphCognitionModel({ nodes: activeGraphNodes, edges: activeGraphEdges }),
    [activeGraphNodes, activeGraphEdges],
  );

  if (editorFocus?.facet === "edge_standard") {
    return (
      <section className="task-graph-studio-page">
        <header className="task-graph-studio-page__head">
          <span>TaskGraph Studio</span>
          <strong>边标准对象</strong>
          <small>边页负责载荷契约、交接语义和 memory / artifact / revision / temporal 的边级配置。</small>
        </header>
        <TaskGraphEdgeStandardPage
          activeGraphEdges={activeGraphEdges}
          editorFocus={editorFocus}
          selectedGraphEdge={selectedGraphEdge}
          selectedGraphEdgeId={selectedGraphEdgeId}
          standardView={standardView}
          updateTaskGraphEdge={updateTaskGraphEdge}
        />
      </section>
    );
  }

  const contractOptions = (...currentIds: string[]) => {
    const current = currentIds.map((item) => String(item ?? "").trim()).filter(Boolean);
    return Array.from(new Set([...current, ...contractIds]));
  };

  const formatContract = (contractId: string) => {
    const contract = contractSpecs.find((item) => item.contract_id === contractId);
    return contract ? `${contractTitle(contract)} · ${contractId}` : contractId || "未绑定";
  };

  return (
    <section className="task-graph-studio-page">
      <header className="task-graph-studio-page__head">
        <span>TaskGraph Studio</span>
        <strong>契约与质量门</strong>
        <small>统一管理图契约、节点输入输出、边载荷契约和预检质量状态。</small>
      </header>

      <section className="task-graph-form-grid">
        <article className="boundary-card">
          <header><strong>图级契约</strong></header>
          <div className="boundary-form">
            <TaskSystemField label="图契约 ID">
              <select
                onChange={(event) => updateTaskGraph({ graph_contract_id: event.target.value })}
                value={graphContractId}
              >
                <option value="">未绑定</option>
                {contractOptions(graphContractId).map((contractId) => (
                  <option key={contractId} value={contractId}>{formatContract(contractId)}</option>
                ))}
              </select>
            </TaskSystemField>
          </div>
          <div className="task-graph-note">
            <strong>保存落点</strong>
            <span>图契约保存时会进入 TaskGraph 一等字段，节点和边契约分别写入节点与边。</span>
          </div>
        </article>

        <article className="boundary-card">
          <header><strong>质量门状态</strong></header>
          <div className="task-graph-mini-kv">
            <p><span>预检</span><strong>{editorValid ? "通过" : "待处理"}</strong></p>
            <p><span>问题</span><strong>{editorIssueCount}</strong></p>
            <p><span>契约库</span><strong>{contractSpecs.length}</strong></p>
          </div>
          {editorFocus?.issue_id ? (
            <div className="task-graph-note">
              <strong>来自发布诊断</strong>
              <span>{editorFocus.issue_id} / {editorFocus.facet || "quality_gate"}</span>
            </div>
          ) : null}
        </article>
      </section>

      <section className="boundary-card">
        <header><strong>节点契约</strong></header>
        <div className="task-graph-node-policy-list">
          {activeGraphNodes.map((node, index) => {
            const nodeId = String(node.node_id ?? "");
            return (
              <article className="task-graph-node-policy-row" key={nodeId || `node_${index}`}>
                <div className="task-graph-node-policy-row__identity">
                  <strong>{nodeTitle(node)}</strong>
                  <span>{nodeId}</span>
                </div>
                <TaskSystemField label="节点契约">
                  <select
                    onChange={(event) => updateTaskGraphNode(nodeId, { node_contract_id: event.target.value, contract_id: event.target.value })}
                    value={String(node.node_contract_id ?? node.contract_id ?? "")}
                  >
                    <option value="">未绑定</option>
                    {contractOptions(String(node.node_contract_id ?? node.contract_id ?? "")).map((contractId) => (
                      <option key={contractId} value={contractId}>{formatContract(contractId)}</option>
                    ))}
                  </select>
                </TaskSystemField>
                <TaskSystemField label="输入契约">
                  <select
                    onChange={(event) => updateTaskGraphNode(nodeId, { input_contract_id: event.target.value })}
                    value={String(node.input_contract_id ?? "")}
                  >
                    <option value="">未绑定</option>
                    {contractOptions(String(node.input_contract_id ?? "")).map((contractId) => (
                      <option key={contractId} value={contractId}>{formatContract(contractId)}</option>
                    ))}
                  </select>
                </TaskSystemField>
                <TaskSystemField label="输出契约">
                  <select
                    onChange={(event) => updateTaskGraphNode(nodeId, { output_contract_id: event.target.value })}
                    value={String(node.output_contract_id ?? "")}
                  >
                    <option value="">未绑定</option>
                    {contractOptions(String(node.output_contract_id ?? "")).map((contractId) => (
                      <option key={contractId} value={contractId}>{formatContract(contractId)}</option>
                    ))}
                  </select>
                </TaskSystemField>
              </article>
            );
          })}
        </div>
      </section>

      <section className="boundary-card">
        <header><strong>契约进入执行包</strong><span>检查输入、输出、交接和提交可见性的配套关系</span></header>
        <div className="task-graph-node-policy-list">
          {cognitionModel.packages.map((nodePackage) => (
            <article className="task-graph-node-policy-row" key={nodePackage.nodeId}>
              <div className="task-graph-node-policy-row__identity">
                <strong>{nodePackage.title}</strong>
                <span>{nodePackage.nodeId}</span>
              </div>
              <div className="task-graph-contract-flow-cell">
                <span>输入契约</span>
                <strong>{nodePackage.inputContractId || "未绑定"}</strong>
              </div>
              <div className="task-graph-contract-flow-cell">
                <span>输出契约</span>
                <strong>{nodePackage.outputContractId || "未绑定"}</strong>
              </div>
              <div className="task-graph-contract-flow-cell">
                <span>输入包</span>
                <strong>{nodePackage.inputPackets.length}</strong>
              </div>
              <div className="task-graph-contract-flow-cell">
                <span>输出交接</span>
                <strong>{nodePackage.outputs.length}</strong>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="boundary-card">
        <header><strong>边载荷契约</strong></header>
        <div className="task-graph-node-policy-list">
          {activeGraphEdges.map((edge, index) => {
            const edgeId = String(edge.edge_id ?? edge.id ?? `edge_${index + 1}`);
            return (
              <article className="task-graph-node-policy-row" key={edgeId}>
                <div className="task-graph-node-policy-row__identity">
                  <strong>{edgeSource(edge)} {"->"} {edgeTarget(edge)}</strong>
                  <span>{edgeId}</span>
                </div>
                <TaskSystemField label="载荷契约">
                  <select
                    onChange={(event) => updateTaskGraphEdge(edgeId, { payload_contract_id: event.target.value, contract_id: event.target.value })}
                    value={String(edge.payload_contract_id ?? edge.contract_id ?? "")}
                  >
                    <option value="">未绑定</option>
                    {contractOptions(String(edge.payload_contract_id ?? edge.contract_id ?? "")).map((contractId) => (
                      <option key={contractId} value={contractId}>{formatContract(contractId)}</option>
                    ))}
                  </select>
                </TaskSystemField>
              </article>
            );
          })}
        </div>
        <div className="boundary-actions">
          <button
            className="boundary-chip"
            disabled={!selectedGraphEdgeId}
            onClick={() => selectedGraphEdgeId && onEditorFocus?.({ layer: "contracts", facet: "edge_standard", edge_id: selectedGraphEdgeId })}
            type="button"
          >
            <span>打开边对象页</span>
          </button>
        </div>
      </section>
    </section>
  );
}
