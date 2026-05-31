"use client";

import { ArrowRightLeft, BrainCircuit, FileCheck2, GitBranch, MousePointer2, Plus, Trash2 } from "lucide-react";

import { TaskGraphContractBindingInspector } from "./TaskGraphContractBindingInspector";
import { TaskGraphInspectorSection, TaskGraphObjectSelectField } from "./TaskGraphInspectorPrimitives";
import { mergeContractBindingSection } from "./taskGraphContractBindings";
import { graphEdgeSource, graphEdgeTarget } from "./taskGraphDraftV2";
import {
  semanticEdgePatchForRelation,
} from "./TaskGraphEditorActions";
import {
  FALLBACK_TASK_GRAPH_SEMANTIC_RELATIONS,
  taskGraphSemanticParametersFromEdge,
  taskGraphSemanticRelationIdFromEdge,
  taskGraphSemanticRelationLabel,
  taskGraphSemanticRelationPresetById,
  type TaskGraphSemanticRelationId,
  type TaskGraphSemanticRelationPreset,
} from "./taskGraphSemanticRelations";
import { taskGraphDisplayName } from "./taskGraphNameRegistry";
import {
  TaskSystemField,
  TaskSystemSelectField,
  taskSystemOptionLabel,
} from "./TaskSystemWorkbenchUi";

const NODE_ROLE_OPTIONS = ["writer", "reviewer", "repairer", "planner", "executor", "coordinator", "manual_gate", "participant", "resource"];
const SEMANTIC_FIELD_LABELS: Record<string, string> = {
  approval_source_node_id: "审核来源",
  artifact_type: "产物类型",
  carry_fields: "携带字段",
  collection_id: "Collection",
  commit_target: "提交目标",
  human_gate_role: "人工门控角色",
  limit: "读取上限",
  max_revision_attempts: "返修上限",
  model_visible_label: "输入包名称",
  on_missing: "缺失策略",
  quality_bar: "质量标准",
  record_kind: "Record Kind",
  record_key: "Record Key",
  repository_id: "仓库 ID",
  required_verdict: "要求裁决",
  source_output_key: "输出来源",
  usage_instruction: "使用说明",
  verdict_key: "裁决字段",
};

const PRIMARY_SEMANTIC_FIELDS = new Set(["repository_id", "collection_id", "record_key", "usage_instruction"]);

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function stringValue(value: unknown, fallback = "") {
  const next = String(value ?? "").trim();
  return next || fallback;
}

function isResourceNode(node: Record<string, unknown> | null) {
  const nodeType = String(node?.node_type ?? "");
  const role = String(node?.role ?? node?.work_posture ?? "");
  return role === "resource" || ["memory_repository", "artifact_repository", "thread_ledger", "progress_ledger", "issue_ledger"].includes(nodeType);
}

function nodePrompt(node: Record<string, unknown>) {
  const metadata = asRecord(node.metadata);
  return stringValue(node.role_prompt ?? metadata.role_prompt)
    || [
      metadata.role_identity,
      metadata.responsibility_scope,
      metadata.responsibility_exclusions,
      metadata.definition_of_done,
    ].map((item) => stringValue(item)).filter(Boolean).join("\n");
}

function selectedEdgeTitle(edge: Record<string, unknown> | null) {
  if (!edge) return "未选择";
  const source = graphEdgeSource(edge);
  const target = graphEdgeTarget(edge);
  return source && target ? `${source} -> ${target}` : stringValue(edge.edge_id ?? edge.id, "边");
}

function edgeKind(edge: Record<string, unknown> | null) {
  const edgeType = stringValue(edge?.edge_type ?? edge?.mode);
  if (edgeType.startsWith("memory_")) return "memory";
  if (["review_feedback", "revision_request", "repair_feedback", "conditional_feedback", "repair_route"].includes(edgeType)) return "revision";
  if (edgeType.startsWith("artifact_") || Object.keys(asRecord(edge?.artifact_ref_policy)).length > 0) return "artifact";
  return "handoff";
}

function semanticMetadataPatch(edge: Record<string, unknown>, patch: Record<string, unknown>) {
  const metadata = asRecord(edge.metadata);
  return {
    metadata: {
      ...metadata,
      semantic_parameters: {
        ...asRecord(metadata.semantic_parameters),
        ...patch,
      },
    },
  };
}

function metadataPatch(edge: Record<string, unknown>, patch: Record<string, unknown>) {
  return {
    metadata: {
      ...asRecord(edge.metadata),
      ...patch,
    },
  };
}

function semanticUsageInstructionPatch(edge: Record<string, unknown>, value: string) {
  const metadata = asRecord(edge.metadata);
  const relationId = taskGraphSemanticRelationIdFromEdge(edge);
  if (!relationId) return metadataPatch(edge, { usage_instruction: value });
  return {
    metadata: {
      ...metadata,
      usage_instruction: value,
      semantic_parameters: {
        ...asRecord(metadata.semantic_parameters),
        usage_instruction: value,
      },
    },
  };
}

function semanticFieldLabel(field: string) {
  return SEMANTIC_FIELD_LABELS[field] ?? field;
}

export function TaskGraphSmartInspector({
  contractOptions,
  disabled,
  formatContract,
  graphMetadata,
  onAddSuccessor,
  onApplyRelation,
  onRemoveEdge,
  onRemoveNode,
  onReverseEdge,
  onSetLinkingFrom,
  onUpdateEdge,
  onUpdateNode,
  semanticRelationPresets,
  selectedEdge,
  selectedEdgeId,
  selectedNode,
  selectedNodeId,
}: {
  contractOptions: string[];
  disabled: boolean;
  formatContract: (contractId: string) => string;
  graphMetadata: Record<string, unknown>;
  onAddSuccessor: (nodeId: string) => void;
  onApplyRelation: (relationId: TaskGraphSemanticRelationId) => void;
  onRemoveEdge: (edgeId: string) => void;
  onRemoveNode: (nodeId: string) => void;
  onReverseEdge: (edgeId: string) => void;
  onSetLinkingFrom: (nodeId: string) => void;
  onUpdateEdge: (edgeId: string, patch: Record<string, unknown>) => void;
  onUpdateNode: (nodeId: string, patch: Record<string, unknown>) => void;
  semanticRelationPresets: TaskGraphSemanticRelationPreset[];
  selectedEdge: Record<string, unknown> | null;
  selectedEdgeId: string;
  selectedNode: Record<string, unknown> | null;
  selectedNodeId: string;
}) {
  if (!selectedNode && !selectedEdge) {
    return (
      <aside className="task-graph-smart-inspector" aria-label="任务图对象配置">
        <TaskGraphInspectorSection icon={<MousePointer2 aria-hidden="true" size={15} />} title="对象配置" aside="等待选择">
          <div className="task-graph-empty-inspector">
            <strong>选择节点或边</strong>
            <span>节点配置 Prompt、输入输出、资源和执行者；边配置语义关系、契约和必要参数。</span>
          </div>
        </TaskGraphInspectorSection>
      </aside>
    );
  }

  if (selectedNode) {
    const metadata = asRecord(selectedNode.metadata);
    const repositoryConfig = asRecord(metadata.memory_repository);
    const artifactRepositoryConfig = asRecord(metadata.artifact_repository);
    const nodeTitle = taskGraphDisplayName(
      selectedNodeId,
      selectedNode,
      graphMetadata,
      stringValue(selectedNode.title ?? selectedNode.label ?? selectedNode.node_id, "节点"),
    );
    const resource = isResourceNode(selectedNode);
    const updateMetadata = (patch: Record<string, unknown>) => onUpdateNode(selectedNodeId, { metadata: { ...metadata, ...patch } });
    return (
      <aside className="task-graph-smart-inspector" aria-label="节点配置">
        <TaskGraphInspectorSection icon={<MousePointer2 aria-hidden="true" size={15} />} title="节点配置" aside={resource ? "资源节点" : "执行节点"}>
          <div className="task-graph-smart-summary">
            <span>{selectedNodeId}</span>
            <strong>{nodeTitle}</strong>
          </div>
          <div className="boundary-form task-graph-smart-form">
            <TaskSystemField label="节点名称" wide>
              <input disabled={disabled} onChange={(event) => onUpdateNode(selectedNodeId, { title: event.target.value, label: event.target.value })} value={stringValue(selectedNode.title ?? selectedNode.label)} />
            </TaskSystemField>
            {!resource ? (
              <>
                <TaskSystemSelectField
                  formatOption={taskSystemOptionLabel}
                  label="角色"
                  onChange={(value) => onUpdateNode(selectedNodeId, { role: value, work_posture: value })}
                  options={NODE_ROLE_OPTIONS}
                  value={stringValue(selectedNode.role ?? selectedNode.work_posture, "participant")}
                />
                <TaskSystemField label="Agent" wide>
                  <input disabled={disabled} onChange={(event) => onUpdateNode(selectedNodeId, { agent_id: event.target.value })} placeholder="agent.writer / agent.reviewer" value={stringValue(selectedNode.agent_id)} />
                </TaskSystemField>
                <TaskSystemField label="角色 Prompt" wide>
                  <textarea disabled={disabled} onChange={(event) => onUpdateNode(selectedNodeId, { role_prompt: event.target.value })} rows={7} value={nodePrompt(selectedNode)} />
                </TaskSystemField>
                <TaskGraphObjectSelectField
                  emptyLabel="未绑定输入契约"
                  formatOption={formatContract}
                  label="输入契约"
                  onChange={(value) => onUpdateNode(selectedNodeId, { input_contract_id: value, ...mergeContractBindingSection(selectedNode, "schema", { input_contract_id: value }) })}
                  options={contractOptions}
                  value={stringValue(selectedNode.input_contract_id)}
                />
                <TaskGraphObjectSelectField
                  emptyLabel="未绑定输出契约"
                  formatOption={formatContract}
                  label="输出契约"
                  onChange={(value) => onUpdateNode(selectedNodeId, { output_contract_id: value, ...mergeContractBindingSection(selectedNode, "schema", { output_contract_id: value }) })}
                  options={contractOptions}
                  value={stringValue(selectedNode.output_contract_id)}
                />
                <TaskSystemField label="产物目标" wide>
                  <input disabled={disabled} onChange={(event) => onUpdateNode(selectedNodeId, { artifact_target: event.target.value, output_path: event.target.value })} placeholder="chapter_draft / review_result" value={stringValue(selectedNode.artifact_target ?? selectedNode.output_path)} />
                </TaskSystemField>
              </>
            ) : null}
            {resource && stringValue(selectedNode.node_type) === "memory_repository" ? (
              <>
                <TaskSystemField label="仓库 ID" wide>
                  <input disabled={disabled} onChange={(event) => updateMetadata({ memory_repository: { ...repositoryConfig, repository_id: event.target.value } })} value={stringValue(repositoryConfig.repository_id, selectedNodeId)} />
                </TaskSystemField>
                <TaskSystemField label="默认 Collection" wide>
                  <input
                    disabled={disabled}
                    onChange={(event) => {
                      const collections = Array.isArray(repositoryConfig.collections) ? repositoryConfig.collections : [];
                      const first = asRecord(collections[0]);
                      updateMetadata({
                        memory_repository: {
                          ...repositoryConfig,
                          collections: [{ ...first, collection_id: event.target.value, title: event.target.value || first.title || "默认集合" }, ...collections.slice(1)],
                        },
                      });
                    }}
                    value={stringValue(asRecord(Array.isArray(repositoryConfig.collections) ? repositoryConfig.collections[0] : {}).collection_id, "default")}
                  />
                </TaskSystemField>
              </>
            ) : null}
            {resource && stringValue(selectedNode.node_type) === "artifact_repository" ? (
              <TaskSystemField label="产物仓库 ID" wide>
                <input disabled={disabled} onChange={(event) => updateMetadata({ artifact_repository: { ...artifactRepositoryConfig, repository_id: event.target.value } })} value={stringValue(artifactRepositoryConfig.repository_id, selectedNodeId)} />
              </TaskSystemField>
            ) : null}
          </div>
          <div className="task-graph-smart-actions">
            <button disabled={disabled} onClick={() => onSetLinkingFrom(selectedNodeId)} type="button"><GitBranch size={14} />设为关系起点</button>
            <button disabled={disabled} onClick={() => onAddSuccessor(selectedNodeId)} type="button"><Plus size={14} />添加后继</button>
            <button disabled={disabled} onClick={() => onRemoveNode(selectedNodeId)} type="button"><Trash2 size={14} />删除</button>
          </div>
        </TaskGraphInspectorSection>
        {!resource ? (
          <details className="task-graph-smart-advanced">
            <summary>高级策略与契约绑定</summary>
            <TaskGraphContractBindingInspector
              contractOptions={contractOptions}
              fieldKeysBySection={{
                schema: ["input_contract_id", "output_contract_id"],
                execution: ["node_contract_id", "executor_policy_ref", "toolset_ref", "skillset_ref"],
                memory: ["memory_read_policy_ref", "dynamic_memory_read_policy_ref", "memory_writeback_policy_ref"],
                output: ["output_policy_ref", "primary_content_key", "artifact_materialization_policy.target_repository_id", "artifact_materialization_policy.target_collection_id", "artifact_materialization_policy.required"],
                acceptance: ["review_gate_policy_ref", "human_gate_policy.mode", "human_gate_policy.blocking", "acceptance_policy_ref"],
                runtime: ["model_requirement.profile_ref", "model_requirement.provider_family", "model_requirement.preferred_output_tokens", "model_requirement.capability_tags"],
                governance: ["thread_ledger_policy_ref", "issue_ledger_policy_ref", "context_boundary_policy_ref"],
              }}
              formatContract={formatContract}
              onChange={(patch) => onUpdateNode(selectedNodeId, patch)}
              sections={["schema", "execution", "memory", "output", "acceptance", "runtime", "governance"]}
              target={selectedNode}
            />
          </details>
        ) : null}
      </aside>
    );
  }

  const edge = selectedEdge;
  if (!edge) return null;
  const relationPresets = semanticRelationPresets.length ? semanticRelationPresets : FALLBACK_TASK_GRAPH_SEMANTIC_RELATIONS;
  const relationId = taskGraphSemanticRelationIdFromEdge(edge);
  const semanticParameters = taskGraphSemanticParametersFromEdge(edge);
  const relationOptions = Array.from(new Set([
    ...relationPresets.map((item) => item.relation_id),
    relationId,
  ].filter(Boolean))) as TaskGraphSemanticRelationId[];
  const relationPreset = taskGraphSemanticRelationPresetById(relationId, relationPresets);
  const detailFields = (relationPreset?.configurable_fields ?? []).filter((field) => !PRIMARY_SEMANTIC_FIELDS.has(field));
  const kind = edgeKind(edge);
  return (
    <aside className="task-graph-smart-inspector" aria-label="边配置">
      <TaskGraphInspectorSection icon={<FileCheck2 aria-hidden="true" size={15} />} title="边配置" aside={kind}>
        <div className="task-graph-smart-summary">
          <span>{selectedEdgeId}</span>
          <strong>{selectedEdgeTitle(edge)}</strong>
        </div>
        <div className="boundary-form task-graph-smart-form">
          <TaskSystemSelectField
            formatOption={(value) => taskGraphSemanticRelationLabel(value, relationPresets)}
            label="语义关系"
            onChange={(value) => onApplyRelation(value as TaskGraphSemanticRelationId)}
            options={relationOptions}
            value={relationId}
            wide
          />
          <TaskGraphObjectSelectField
            emptyLabel="未绑定载荷契约"
            formatOption={formatContract}
            label="载荷契约"
            onChange={(value) => onUpdateEdge(selectedEdgeId, { payload_contract_id: value, ...mergeContractBindingSection(edge, "schema", { payload_contract_id: value }) })}
            options={contractOptions}
            value={stringValue(edge.payload_contract_id)}
            wide
          />
          <TaskSystemField label="使用说明" wide>
            <textarea disabled={disabled} onChange={(event) => onUpdateEdge(selectedEdgeId, semanticUsageInstructionPatch(edge, event.target.value))} rows={4} value={stringValue(asRecord(edge.metadata).usage_instruction ?? semanticParameters.usage_instruction)} />
          </TaskSystemField>
          {kind === "memory" ? (
            <>
              <TaskSystemField label="仓库 ID" wide>
                <input disabled={disabled} onChange={(event) => onUpdateEdge(selectedEdgeId, semanticMetadataPatch(edge, { repository_id: event.target.value }))} value={stringValue(semanticParameters.repository_id ?? semanticParameters.repository)} />
              </TaskSystemField>
              <TaskSystemField label="Collection">
                <input disabled={disabled} onChange={(event) => onUpdateEdge(selectedEdgeId, semanticMetadataPatch(edge, { collection_id: event.target.value }))} value={stringValue(semanticParameters.collection_id ?? semanticParameters.collection, "default")} />
              </TaskSystemField>
              <TaskSystemField label="Record Key">
                <input disabled={disabled} onChange={(event) => onUpdateEdge(selectedEdgeId, semanticMetadataPatch(edge, { record_key: event.target.value }))} value={stringValue(semanticParameters.record_key)} />
              </TaskSystemField>
            </>
          ) : null}
          {kind === "revision" ? (
            <>
              <TaskSystemField label="原稿引用">
                <input disabled={disabled} onChange={(event) => onUpdateEdge(selectedEdgeId, metadataPatch(edge, { original_artifact_key: event.target.value }))} value={stringValue(asRecord(edge.metadata).original_artifact_key ?? semanticParameters.original_artifact_key)} />
              </TaskSystemField>
              <TaskSystemField label="审核结果">
                <input disabled={disabled} onChange={(event) => onUpdateEdge(selectedEdgeId, metadataPatch(edge, { review_result_key: event.target.value }))} value={stringValue(asRecord(edge.metadata).review_result_key ?? semanticParameters.review_result_key)} />
              </TaskSystemField>
            </>
          ) : null}
          {detailFields.map((field) => (
            <TaskSystemField key={field} label={semanticFieldLabel(field)} wide={["carry_fields", "quality_bar"].includes(field)}>
              <input
                disabled={disabled}
                onChange={(event) => onUpdateEdge(selectedEdgeId, semanticMetadataPatch(edge, { [field]: event.target.value }))}
                type={["limit", "max_revision_attempts"].includes(field) ? "number" : "text"}
                value={stringValue(semanticParameters[field])}
              />
            </TaskSystemField>
          ))}
        </div>
        <div className="task-graph-smart-actions">
          <button disabled={disabled} onClick={() => onUpdateEdge(selectedEdgeId, semanticEdgePatchForRelation(edge, "writing.draft_to_review", relationPresets))} type="button"><GitBranch size={14} />设为审核</button>
          <button disabled={disabled} onClick={() => onReverseEdge(selectedEdgeId)} type="button"><ArrowRightLeft size={14} />反转</button>
          <button disabled={disabled} onClick={() => onRemoveEdge(selectedEdgeId)} type="button"><Trash2 size={14} />删除</button>
        </div>
      </TaskGraphInspectorSection>
      <details className="task-graph-smart-advanced">
        <summary>高级交接策略</summary>
        <TaskGraphContractBindingInspector
          contractOptions={contractOptions}
          fieldKeysBySection={{
            schema: ["payload_contract_id"],
            handoff: ["handoff_contract_id", "ack_policy", "ack_required", "wait_policy", "failure_propagation_policy", "result_delivery_policy"],
            memory: ["working_memory_handoff_policy.carry_kinds", "working_memory_handoff_policy.carry_scopes"],
            artifact: ["artifact_ref_policy_ref"],
            temporal: ["trigger_timing", "visibility_timing", "acknowledgement_timing", "propagation_timing"],
            governance: ["context_boundary_policy_ref"],
          }}
          formatContract={formatContract}
          onChange={(patch) => onUpdateEdge(selectedEdgeId, patch)}
          sections={["schema", "handoff", "memory", "artifact", "temporal", "governance"]}
          target={edge}
        />
      </details>
    </aside>
  );
}
