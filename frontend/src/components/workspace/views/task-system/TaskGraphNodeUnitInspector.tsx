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
  interfaces,
  node,
  selected,
  unitEdges,
  updateTaskGraphNode,
}: {
  agentOptions: string[];
  contractOptions: string[];
  domainTaskOptions: Array<{ value: string; label: string }>;
  formatAgent: (agentId: string) => string;
  formatContract: (contractId: string) => string;
  interfaces: UnitInterfaceSpec[];
  node: Record<string, unknown>;
  selected: ComposableUnitSpec;
  unitEdges: UnitPortEdgeSpec[];
  updateTaskGraphNode: (nodeId: string, patch: Record<string, unknown>) => void;
}) {
  const nodeId = nodeIdFromUnit(selected);
  const iface = interfaces.find((item) => item.unit_id === selected.unit_id) ?? null;
  const taskId = stringValue(node.task_id ?? node.task_ref ?? node.subtask_ref);

  return (
    <>
      <TaskGraphInspectorSection icon={<GitBranch aria-hidden="true" size={15} />} title="节点" aside="canonical node">
        <TaskGraphInspectorSummary
          overline={stringValue(node.node_type, selected.unit_type)}
          title={nodeTitle(node, selected.title || selected.unit_id)}
          caption={nodeId}
          metrics={[
            { label: "接口", value: iface?.interface_id || selected.interface_id || "未派生" },
            { label: "生命周期", value: stringValue(node.phase_id ?? selected.phase_id, "未分配") },
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
          runtime: ["model_requirement.profile_ref", "model_requirement.provider_family", "model_requirement.min_output_tokens", "model_requirement.preferred_output_tokens", "model_requirement.capability_tags", "model_requirement.streaming_required", "length_budget.enabled", "length_budget.budget_scope", "length_budget.measurement_mode", "length_budget.unit_kind", "length_budget.unit_label_zh", "length_budget.target_units", "length_budget.min_units", "length_budget.max_units", "length_budget.batch_unit_count", "length_budget.repair_policy.mode", "length_budget.repair_policy.max_repair_rounds", "length_budget.acceptance_policy.require_continuity", "length_budget.acceptance_policy.require_formal_headings"],
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

      <TaskGraphInspectorSection icon={<GitBranch aria-hidden="true" size={15} />} title="运行策略">
        <div className="task-graph-note">
          <strong>运行依赖由边决定</strong>
          <span>生命周期坐标只用于展示和诊断；需要顺序、并发汇合或阻塞关系时，请配置显式边、等待策略或汇合策略。</span>
        </div>
        <div className="boundary-form task-graph-composer-inspector-form">
          <TaskSystemField label="生命周期坐标">
            <input onChange={(event) => updateTaskGraphNode(nodeId, { phase_id: event.target.value })} value={stringValue(node.phase_id)} />
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
