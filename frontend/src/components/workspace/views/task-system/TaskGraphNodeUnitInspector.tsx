import { GitBranch } from "lucide-react";

import type { ComposableUnitSpec, UnitInterfaceSpec, UnitPortEdgeSpec } from "@/lib/api";

import { TaskGraphContractBindingInspector } from "./TaskGraphContractBindingInspector";
import { TaskGraphNodeBatchContractInspector } from "./TaskGraphNodeBatchContractInspector";
import {
  TaskGraphInspectorSection,
  TaskGraphInspectorSummary,
  TaskGraphObjectSelectField,
} from "./TaskGraphInspectorPrimitives";
import {
  TaskSystemDomainTaskSelectField,
  TaskSystemField,
  TaskSystemSelectField,
  taskSystemOptionLabel,
} from "./TaskSystemWorkbenchUi";

function stringValue(value: unknown, fallback = "") {
  const next = String(value ?? "").trim();
  return next || fallback;
}

function booleanValue(value: unknown, fallback = false) {
  return typeof value === "boolean" ? value : fallback;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function nodeIdFromUnit(unit: ComposableUnitSpec | null) {
  return stringValue(asRecord(unit?.ref).node_id);
}

function nodeTitle(node: Record<string, unknown> | null, fallback = "节点") {
  return stringValue(node?.title ?? node?.label ?? node?.task_title ?? node?.node_id, fallback);
}

function taskLabel(taskId: string, options: Array<{ value: string; label: string }>) {
  if (!taskId) return "不绑定任务";
  return options.find((item) => item.value === taskId)?.label ?? taskId;
}

export function TaskGraphNodeUnitInspector({
  agentOptions,
  contractOptions,
  domainTaskOptions,
  formatAgent,
  formatContract,
  formatProjection,
  interfaces,
  node,
  projectionOptions,
  selected,
  unitEdges,
  updateTaskGraphNode,
}: {
  agentOptions: string[];
  contractOptions: string[];
  domainTaskOptions: Array<{ value: string; label: string }>;
  formatAgent: (agentId: string) => string;
  formatContract: (contractId: string) => string;
  formatProjection: (projectionId: string) => string;
  interfaces: UnitInterfaceSpec[];
  node: Record<string, unknown>;
  projectionOptions: string[];
  selected: ComposableUnitSpec;
  unitEdges: UnitPortEdgeSpec[];
  updateTaskGraphNode: (nodeId: string, patch: Record<string, unknown>) => void;
}) {
  const nodeId = nodeIdFromUnit(selected);
  const iface = interfaces.find((item) => item.unit_id === selected.unit_id) ?? null;
  const taskId = stringValue(node.task_id ?? node.task_ref ?? node.subtask_ref);

  return (
    <>
      <TaskGraphInspectorSection icon={<GitBranch aria-hidden="true" size={15} />} title="节点" aside="时序点 / 执行位">
        <TaskGraphInspectorSummary
          overline={stringValue(node.node_type, selected.unit_type)}
          title={nodeTitle(node, selected.title || selected.unit_id)}
          caption={nodeId}
          metrics={[
            { label: "接口", value: iface?.interface_id || selected.interface_id || "未派生" },
            { label: "阶段", value: stringValue(node.phase_id ?? selected.phase_id, "未分配") },
            { label: "绑定任务", value: taskLabel(taskId, domainTaskOptions) },
            { label: "连接边", value: unitEdges.length },
          ]}
        />
      </TaskGraphInspectorSection>

      <TaskGraphInspectorSection icon={<GitBranch aria-hidden="true" size={15} />} title="身份与执行者">
        <div className="boundary-form task-graph-composer-inspector-form">
          <TaskSystemField label="中文名 / 标题" wide>
            <input onChange={(event) => updateTaskGraphNode(nodeId, { title: event.target.value, label: event.target.value })} value={nodeTitle(node, "")} />
          </TaskSystemField>
          <TaskSystemSelectField
            label="节点类型"
            onChange={(value) => updateTaskGraphNode(nodeId, { node_type: value })}
            options={["agent_role", "review_gate", "loop_frame", "memory_repository", "artifact_repository", "thread_ledger", "issue_ledger", "runtime_state_store", "manual_gate", "tool"]}
            value={stringValue(node.node_type, "agent_role")}
          />
          <TaskSystemDomainTaskSelectField
            label="运行时任务"
            onChange={(value) => updateTaskGraphNode(nodeId, { task_id: value })}
            options={domainTaskOptions}
            value={taskId}
          />
          <TaskGraphObjectSelectField
            formatOption={formatAgent}
            label="执行 Agent"
            onChange={(value) => updateTaskGraphNode(nodeId, { agent_id: value })}
            options={agentOptions}
            value={stringValue(node.agent_id)}
            wide
          />
          <TaskGraphObjectSelectField
            formatOption={formatProjection}
            label="职责 Projection"
            onChange={(value) => updateTaskGraphNode(nodeId, { projection_id: value, projection_overlay_id: value })}
            options={projectionOptions}
            value={stringValue(node.projection_id ?? node.projection_overlay_id)}
            wide
          />
        </div>
      </TaskGraphInspectorSection>

      <TaskGraphContractBindingInspector
        contractOptions={contractOptions}
        fieldKeysBySection={{
          schema: ["input_contract_id", "output_contract_id"],
          execution: ["node_contract_id", "executor_policy_ref", "toolset_ref", "skillset_ref"],
          memory: ["memory_read_policy_ref", "dynamic_memory_read_policy_ref", "memory_writeback_policy_ref"],
          artifact: ["artifact_policy.artifact_target", "artifact_policy.visibility_policy", "artifact_policy.required", "artifact_ref_policy_ref"],
          acceptance: ["review_gate_policy_ref", "human_gate_policy.mode", "human_gate_policy.blocking", "acceptance_policy_ref"],
          runtime: ["model_requirement.profile_ref", "model_requirement.provider_family", "model_requirement.min_output_tokens", "model_requirement.preferred_output_tokens", "model_requirement.capability_tags", "model_requirement.streaming_required"],
          governance: ["thread_ledger_policy_ref", "issue_ledger_policy_ref", "context_boundary_policy_ref"],
        }}
        formatContract={formatContract}
        onChange={(patch) => updateTaskGraphNode(nodeId, patch)}
        sections={["schema", "execution", "memory", "artifact", "acceptance", "runtime", "governance"]}
        target={node}
      />

      <TaskGraphNodeBatchContractInspector
        node={node}
        onChange={(patch) => updateTaskGraphNode(nodeId, patch)}
      />

      <TaskGraphInspectorSection icon={<GitBranch aria-hidden="true" size={15} />} title="时序与运行">
        <div className="boundary-form task-graph-composer-inspector-form">
          <TaskSystemField label="阶段">
            <input onChange={(event) => updateTaskGraphNode(nodeId, { phase_id: event.target.value })} value={stringValue(node.phase_id)} />
          </TaskSystemField>
          <TaskSystemField label="顺序">
            <input min={0} onChange={(event) => updateTaskGraphNode(nodeId, { sequence_index: Number(event.target.value || 0) })} type="number" value={Number(node.sequence_index ?? selected.sequence_index ?? 0)} />
          </TaskSystemField>
          <TaskSystemSelectField
            formatOption={taskSystemOptionLabel}
            label="执行模式"
            onChange={(value) => updateTaskGraphNode(nodeId, { execution_mode: value })}
            options={["sync", "async", "parallel", "background", "barrier", "manual_gate"]}
            value={stringValue(node.execution_mode, "sync")}
          />
          <TaskSystemSelectField
            formatOption={taskSystemOptionLabel}
            label="等待策略"
            onChange={(value) => updateTaskGraphNode(nodeId, { wait_policy: value })}
            options={["wait_all_upstream_completed", "wait_any_upstream_completed", "wait_required_contracts", "wait_handoff_ack", "manual_release"]}
            value={stringValue(node.wait_policy, "wait_all_upstream_completed")}
          />
          <TaskSystemSelectField
            formatOption={taskSystemOptionLabel}
            label="汇合策略"
            onChange={(value) => updateTaskGraphNode(nodeId, { join_policy: value })}
            options={["all_success", "any_success", "allow_partial_with_issues", "coordinator_decides", "fail_on_any_error"]}
            value={stringValue(node.join_policy, "all_success")}
          />
          <label className="boundary-check">
            <input checked={booleanValue(node.main_chain, true)} onChange={(event) => updateTaskGraphNode(nodeId, { main_chain: event.target.checked })} type="checkbox" />
            进入主链
          </label>
          <label className="boundary-check">
            <input checked={booleanValue(node.blocks_phase_exit, true)} onChange={(event) => updateTaskGraphNode(nodeId, { blocks_phase_exit: event.target.checked })} type="checkbox" />
            阻塞阶段出口
          </label>
        </div>
      </TaskGraphInspectorSection>

      <TaskGraphInspectorSection icon={<GitBranch aria-hidden="true" size={15} />} title="产物">
        <div className="boundary-form task-graph-composer-inspector-form">
          <TaskSystemField label="产物目标" wide>
            <input onChange={(event) => updateTaskGraphNode(nodeId, { artifact_target: event.target.value })} value={stringValue(node.artifact_target)} />
          </TaskSystemField>
        </div>
      </TaskGraphInspectorSection>
    </>
  );
}
