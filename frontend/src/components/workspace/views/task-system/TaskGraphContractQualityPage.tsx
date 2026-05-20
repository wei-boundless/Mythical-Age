"use client";

import { useMemo } from "react";
import type { ContractSpec } from "@/lib/api";

import type { TaskGraphDraftV2 } from "./taskGraphDraftV2";
import type { TaskGraphEditorFocus } from "./taskGraphEditorFocus";
import { buildTaskGraphCognitionModel } from "./taskGraphCognitionView";
import {
  edgePayloadContractIdOf,
  graphContractIdOf,
  nodeExecutionContractIdOf,
  nodeInputContractIdOf,
  nodeOutputContractIdOf,
} from "./taskGraphContractBindings";

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
  taskGraphDraft,
}: {
  activeGraphEdges: Array<Record<string, unknown>>;
  activeGraphNodes: Array<Record<string, unknown>>;
  contractSpecs: ContractSpec[];
  editorIssueCount: number;
  editorValid: boolean;
  editorFocus?: TaskGraphEditorFocus;
  onEditorFocus?: (focus: Partial<TaskGraphEditorFocus> & { layer?: TaskGraphEditorFocus["layer"] }) => void;
  taskGraphDraft: TaskGraphDraftV2;
}) {
  const contractIds = new Set(contractSpecs.map((item) => item.contract_id));
  const cognitionModel = useMemo(
    () => buildTaskGraphCognitionModel({ nodes: activeGraphNodes, edges: activeGraphEdges }),
    [activeGraphNodes, activeGraphEdges],
  );
  const formatContract = (contractId: string) => {
    const contract = contractSpecs.find((item) => item.contract_id === contractId);
    return contract ? `${contractTitle(contract)} · ${contractId}` : contractId || "未绑定";
  };
  const graphContractId = graphContractIdOf(taskGraphDraft);
  const nodeContractRows = activeGraphNodes.map((node, index) => {
    const nodeId = String(node.node_id ?? node.id ?? `node_${index + 1}`);
    return {
      node,
      nodeId,
      executionContractId: nodeExecutionContractIdOf(node),
      inputContractId: nodeInputContractIdOf(node),
      outputContractId: nodeOutputContractIdOf(node),
    };
  });
  const edgeContractRows = activeGraphEdges.map((edge, index) => {
    const edgeId = String(edge.edge_id ?? edge.id ?? `edge_${index + 1}`);
    return {
      edge,
      edgeId,
      payloadContractId: edgePayloadContractIdOf(edge),
    };
  });
  const missingContractCount = [
    graphContractId,
    ...nodeContractRows.flatMap((row) => [row.executionContractId, row.inputContractId, row.outputContractId]),
    ...edgeContractRows.map((row) => row.payloadContractId),
  ].filter((contractId) => !contractId).length;
  const unknownContractCount = [
    graphContractId,
    ...nodeContractRows.flatMap((row) => [row.executionContractId, row.inputContractId, row.outputContractId]),
    ...edgeContractRows.map((row) => row.payloadContractId),
  ].filter((contractId) => contractId && !contractIds.has(contractId)).length;

  return (
    <section className="task-graph-studio-page">
      <header className="task-graph-studio-page__head">
        <span>图工作台</span>
        <strong>契约质量总览</strong>
        <small>这里检查 contract_bindings 是否覆盖图、节点和边；具体编辑进入图工作台对象编辑台。</small>
      </header>

      <section className="task-graph-form-grid">
        <article className="boundary-card">
          <header><strong>图级契约</strong><span>contract_bindings.schema</span></header>
          <div className="task-graph-contract-flow-cell">
            <span>图契约</span>
            <strong>{formatContract(graphContractId)}</strong>
          </div>
          <div className="task-graph-note">
            <strong>编辑入口</strong>
            <span>打开图工作台，选中图对象，在右侧对象编辑台配置 Schema / Runtime / Governance。</span>
          </div>
          <div className="boundary-actions">
            <button className="boundary-chip" onClick={() => onEditorFocus?.({ layer: "modules", facet: "units" })} type="button">
              <span>编辑图对象契约</span>
            </button>
          </div>
        </article>

        <article className="boundary-card">
          <header><strong>质量门状态</strong></header>
          <div className="task-graph-mini-kv">
            <p><span>预检</span><strong>{editorValid ? "通过" : "待处理"}</strong></p>
            <p><span>问题</span><strong>{editorIssueCount}</strong></p>
            <p><span>契约库</span><strong>{contractSpecs.length}</strong></p>
            <p><span>缺失绑定</span><strong>{missingContractCount}</strong></p>
            <p><span>库外引用</span><strong>{unknownContractCount}</strong></p>
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
        <header><strong>节点契约</strong><span>选中节点后在对象编辑台修改</span></header>
        <div className="task-graph-node-policy-list">
          {nodeContractRows.map(({ executionContractId, inputContractId, node, nodeId, outputContractId }) => (
            <article className="task-graph-node-policy-row" key={nodeId}>
              <div className="task-graph-node-policy-row__identity">
                <strong>{nodeTitle(node)}</strong>
                <span>{nodeId}</span>
              </div>
              <div className="task-graph-contract-flow-cell">
                <span>执行契约</span>
                <strong>{formatContract(executionContractId)}</strong>
              </div>
              <div className="task-graph-contract-flow-cell">
                <span>输入契约</span>
                <strong>{formatContract(inputContractId)}</strong>
              </div>
              <div className="task-graph-contract-flow-cell">
                <span>输出契约</span>
                <strong>{formatContract(outputContractId)}</strong>
              </div>
              <button className="boundary-chip" onClick={() => onEditorFocus?.({ layer: "modules", facet: "units", node_id: nodeId })} type="button">
                <span>编辑节点契约</span>
              </button>
            </article>
          ))}
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
        <header><strong>边载荷契约</strong><span>选中边后在对象编辑台修改</span></header>
        <div className="task-graph-node-policy-list">
          {edgeContractRows.map(({ edge, edgeId, payloadContractId }) => (
            <article className="task-graph-node-policy-row" key={edgeId}>
              <div className="task-graph-node-policy-row__identity">
                <strong>{edgeSource(edge)} {"->"} {edgeTarget(edge)}</strong>
                <span>{edgeId}</span>
              </div>
              <div className="task-graph-contract-flow-cell">
                <span>载荷契约</span>
                <strong>{formatContract(payloadContractId)}</strong>
              </div>
              <button className="boundary-chip" onClick={() => onEditorFocus?.({ layer: "modules", facet: "connections", edge_id: edgeId })} type="button">
                <span>编辑边契约</span>
              </button>
            </article>
          ))}
        </div>
      </section>
    </section>
  );
}
