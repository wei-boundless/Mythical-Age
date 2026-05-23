import { Cable, Layers3, Trash2 } from "lucide-react";

import type { UnitInterfaceSpec, UnitPortEdgeSpec } from "@/lib/api";

import { TaskGraphContractBindingInspector } from "./TaskGraphContractBindingInspector";
import {
  TaskGraphInspectorSection,
  TaskGraphInspectorSummary,
  TaskGraphObjectSelectField,
} from "./TaskGraphInspectorPrimitives";
import {
  TaskSystemField,
  TaskSystemSelectField,
  taskSystemOptionLabel,
} from "./TaskSystemWorkbenchUi";
import {
  formatRuntimeSupportOption,
  runtimeOptionIsUnsupported,
} from "./taskGraphRuntimeSupport";
import { graphEdgeId } from "./taskGraphTopologyUtils";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function stringValue(value: unknown, fallback = "") {
  const next = String(value ?? "").trim();
  return next || fallback;
}

function booleanValue(value: unknown, fallback = false) {
  return typeof value === "boolean" ? value : fallback;
}

function splitList(value: string) {
  return value.split(/[\n,，]/).map((item) => item.trim()).filter(Boolean);
}

function listText(value: unknown) {
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean).join("\n") : "";
}

function SupportedSelectField({
  field,
  label,
  onChange,
  options,
  value,
}: {
  field: string;
  label: string;
  onChange: (value: string) => void;
  options: string[];
  value: string;
}) {
  const resolvedOptions = Array.from(new Set([value, ...options].map((item) => String(item ?? "").trim()).filter(Boolean)));
  return (
    <TaskSystemField label={label}>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {resolvedOptions.map((item) => {
          return (
            <option disabled={runtimeOptionIsUnsupported(field, item) && item !== value} key={item} value={item}>
              {formatRuntimeSupportOption(field)(item)}
            </option>
          );
        })}
      </select>
    </TaskSystemField>
  );
}

function SupportMatrixNote() {
  return (
    <div className="task-graph-note">
      <strong>运行支持矩阵</strong>
      <span>“运行支持”会进入 scheduler；“预览”会保存但只部分兑现；“未支持”不会作为已生效运行策略。</span>
    </div>
  );
}

function portOptionsForUnit(unitId: string, interfaces: UnitInterfaceSpec[], direction?: "input" | "output") {
  const iface = interfaces.find((item) => item.unit_id === unitId);
  if (!iface) return [];
  const ports = direction === "input"
    ? iface.input_ports
    : direction === "output"
      ? iface.output_ports
      : [...iface.input_ports, ...iface.output_ports];
  return ports.map((port) => port.port_id).filter(Boolean);
}

function edgeSourceSummary(edge: UnitPortEdgeSpec) {
  return `${edge.source_unit_id}.${edge.source_port_id} -> ${edge.target_unit_id}.${edge.target_port_id}`;
}

type SharedEdgeProps = {
  contractOptions: string[];
  formatContract: (contractId: string) => string;
  formatUnit: (unitId: string) => string;
  interfaces: UnitInterfaceSpec[];
  nodeUnitOptions: string[];
  unitOptions: string[];
};

export function TaskGraphPortEdgeInspector({
  edge,
  isOverlay,
  originalEdge,
  removeOverlayEdge,
  updateLegacyEdgeEndpoint,
  updateTaskGraphEdge,
  ...shared
}: SharedEdgeProps & {
  edge: UnitPortEdgeSpec;
  isOverlay: boolean;
  originalEdge: Record<string, unknown> | null;
  removeOverlayEdge: (edgeId: string) => void;
  updateLegacyEdgeEndpoint: (edge: Record<string, unknown>, edgeId: string, patch: Record<string, unknown>) => void;
  updateTaskGraphEdge: (edgeId: string, patch: Record<string, unknown>) => void;
}) {
  if (isOverlay) {
    return (
      <OverlayPortEdgeInspector
        edge={edge}
        removeOverlayEdge={removeOverlayEdge}
        {...shared}
      />
    );
  }
  if (originalEdge) {
    return (
      <LegacyPortEdgeInspector
        edge={edge}
        originalEdge={originalEdge}
        updateLegacyEdgeEndpoint={updateLegacyEdgeEndpoint}
        updateTaskGraphEdge={updateTaskGraphEdge}
        {...shared}
      />
    );
  }
  return (
    <TaskGraphInspectorSection icon={<Cable aria-hidden="true" size={15} />} title="交接边" aside="未映射">
      <TaskGraphInspectorSummary
        overline={edge.edge_type || "handoff"}
        title={edge.edge_id}
        caption={edgeSourceSummary(edge)}
      />
      <div className="task-graph-note">
        <strong>未找到可写回的原始边</strong>
        <span>这条端口边来自标准视图或覆盖层诊断。需要运行时生效时，请回到拓扑编辑创建规范边。</span>
      </div>
    </TaskGraphInspectorSection>
  );
}

function OverlayPortEdgeInspector({
  contractOptions,
  edge,
  formatContract,
  formatUnit,
  removeOverlayEdge,
}: SharedEdgeProps & {
  edge: UnitPortEdgeSpec;
  removeOverlayEdge: (edgeId: string) => void;
}) {
  return (
    <TaskGraphInspectorSection icon={<Cable aria-hidden="true" size={15} />} title="metadata 覆盖端口边" aside="诊断覆盖层">
      <TaskGraphInspectorSummary
        overline={edge.edge_type || "handoff"}
        title={edge.edge_id || "未命名端口边"}
        caption={edgeSourceSummary(edge)}
        metrics={[
          { label: "源", value: formatUnit(edge.source_unit_id) },
          { label: "目标", value: formatUnit(edge.target_unit_id) },
          { label: "契约", value: edge.payload_contract_id ? formatContract(edge.payload_contract_id) : "未声明" },
          { label: "候选契约", value: contractOptions.length },
        ]}
      />
      <div className="task-graph-note">
        <strong>覆盖边只读</strong>
        <span>它会进入标准视图诊断，但不是规范运行边。需要运行时生效时，请在拓扑编辑中创建或修改规范边。</span>
      </div>
      <button className="task-graph-inline-danger" onClick={() => removeOverlayEdge(edge.edge_id)} type="button">
        <Trash2 aria-hidden="true" size={14} />
        移除覆盖边
      </button>
    </TaskGraphInspectorSection>
  );
}

function LegacyPortEdgeInspector({
  edge,
  formatContract,
  formatUnit,
  interfaces,
  contractOptions,
  nodeUnitOptions,
  originalEdge,
  updateLegacyEdgeEndpoint,
  updateTaskGraphEdge,
}: SharedEdgeProps & {
  edge: UnitPortEdgeSpec;
  originalEdge: Record<string, unknown>;
  updateLegacyEdgeEndpoint: (edge: Record<string, unknown>, edgeId: string, patch: Record<string, unknown>) => void;
  updateTaskGraphEdge: (edgeId: string, patch: Record<string, unknown>) => void;
}) {
  const edgeId = graphEdgeId(originalEdge);
  const edgeMetadata = asRecord(originalEdge.metadata);
  const temporal = asRecord(edgeMetadata.temporal_semantics);
  const handoff = asRecord(originalEdge.working_memory_handoff_policy);
  const sourcePorts = portOptionsForUnit(edge.source_unit_id, interfaces, "output");
  const targetPorts = portOptionsForUnit(edge.target_unit_id, interfaces, "input");

  const patchEdgeMetadata = (patch: Record<string, unknown>) => {
    updateTaskGraphEdge(edgeId, {
      metadata: {
        ...asRecord(originalEdge.metadata),
        ...patch,
      },
    });
  };
  const patchEdgeTemporal = (patch: Record<string, unknown>) => {
    const currentMetadata = asRecord(originalEdge.metadata);
    updateTaskGraphEdge(edgeId, {
      metadata: {
        ...currentMetadata,
        ...patch,
        temporal_semantics: {
          ...asRecord(currentMetadata.temporal_semantics),
          ...patch,
        },
      },
    });
  };
  const patchEdgeMemoryHandoff = (patch: Record<string, unknown>) => {
    updateTaskGraphEdge(edgeId, {
      working_memory_handoff_policy: {
        ...asRecord(originalEdge.working_memory_handoff_policy),
        ...patch,
      },
    });
  };

  return (
    <>
      <TaskGraphInspectorSection icon={<Cable aria-hidden="true" size={15} />} title="交接边" aside="edges[]">
        <TaskGraphInspectorSummary
          overline={stringValue(originalEdge.edge_type ?? originalEdge.mode, "structured_handoff")}
          title={edgeId}
          caption={edgeSourceSummary(edge)}
        />
        <div className="task-graph-note">
          <strong>边是交接协议，不是执行端</strong>
          <span>这里配置上游节点输出如何成为下游节点合法输入；任务动作仍由节点激活产生。</span>
        </div>
      </TaskGraphInspectorSection>

      <TaskGraphInspectorSection icon={<Cable aria-hidden="true" size={15} />} title="端口映射">
        <div className="boundary-form task-graph-composer-inspector-form">
          <TaskGraphObjectSelectField formatOption={formatUnit} label="源节点" onChange={(value) => updateLegacyEdgeEndpoint(originalEdge, edgeId, { source_unit_id: value })} options={nodeUnitOptions} value={edge.source_unit_id} />
          <TaskSystemSelectField label="源端口" onChange={(value) => updateLegacyEdgeEndpoint(originalEdge, edgeId, { source_port_id: value })} options={sourcePorts} value={edge.source_port_id} />
          <TaskGraphObjectSelectField formatOption={formatUnit} label="目标节点" onChange={(value) => updateLegacyEdgeEndpoint(originalEdge, edgeId, { target_unit_id: value })} options={nodeUnitOptions} value={edge.target_unit_id} />
          <TaskSystemSelectField label="目标端口" onChange={(value) => updateLegacyEdgeEndpoint(originalEdge, edgeId, { target_port_id: value })} options={targetPorts} value={edge.target_port_id} />
        </div>
      </TaskGraphInspectorSection>

      <TaskGraphContractBindingInspector
        contractOptions={contractOptions}
        fieldKeysBySection={{
          schema: ["payload_contract_id"],
          handoff: ["ack_policy", "ack_required", "wait_policy", "failure_propagation_policy", "result_delivery_policy"],
          memory: ["working_memory_handoff_policy.carry_kinds", "working_memory_handoff_policy.carry_scopes"],
          artifact: ["artifact_ref_policy_ref"],
          temporal: ["trigger_timing", "visibility_timing", "acknowledgement_timing", "propagation_timing"],
          governance: ["context_boundary_policy_ref"],
        }}
        formatContract={formatContract}
        onChange={(patch) => updateTaskGraphEdge(edgeId, patch)}
        sections={["schema", "handoff", "memory", "artifact", "temporal", "governance"]}
        target={originalEdge}
      />

      <TaskGraphInspectorSection icon={<Cable aria-hidden="true" size={15} />} title="交接策略">
        <div className="boundary-form task-graph-composer-inspector-form">
          <TaskSystemSelectField
            formatOption={taskSystemOptionLabel}
            label="边类型"
            onChange={(value) => updateTaskGraphEdge(edgeId, { edge_type: value, mode: value })}
            options={["structured_handoff", "control_flow", "memory_read", "memory_write_candidate", "memory_commit", "artifact_context", "revision_request", "temporal_dependency"]}
            value={stringValue(originalEdge.edge_type ?? originalEdge.mode, "structured_handoff")}
          />
          <TaskSystemSelectField
            formatOption={formatRuntimeSupportOption("wait_policy")}
            isOptionDisabled={(value) => runtimeOptionIsUnsupported("wait_policy", value)}
            label="等待策略"
            onChange={(value) => updateTaskGraphEdge(edgeId, { wait_policy: value })}
            options={["wait_all_upstream_completed", "wait_any_upstream_completed", "wait_required_contracts", "wait_handoff_ack", "fire_and_continue"]}
            value={stringValue(originalEdge.wait_policy, "wait_all_upstream_completed")}
          />
          <TaskSystemSelectField
            formatOption={formatRuntimeSupportOption("ack_policy")}
            label="确认策略"
            onChange={(value) => updateTaskGraphEdge(edgeId, { ack_policy: value })}
            options={["explicit_ack", "implicit_ack", "manual_ack", "none"]}
            value={stringValue(originalEdge.ack_policy, "explicit_ack")}
          />
          <TaskSystemSelectField
            formatOption={formatRuntimeSupportOption("failure_propagation_policy")}
            label="失败传播"
            onChange={(value) => updateTaskGraphEdge(edgeId, { failure_propagation_policy: value })}
            options={["fail_downstream", "isolate_failure", "allow_partial", "coordinator_decides"]}
            value={stringValue(originalEdge.failure_propagation_policy, "fail_downstream")}
          />
          <TaskSystemSelectField
            formatOption={formatRuntimeSupportOption("result_delivery_policy")}
            label="结果投递"
            onChange={(value) => updateTaskGraphEdge(edgeId, { result_delivery_policy: value })}
            options={["contract_payload_and_refs", "summary_and_refs", "notification_only"]}
            value={stringValue(originalEdge.result_delivery_policy, "contract_payload_and_refs")}
          />
          <label className="boundary-check">
            <input checked={booleanValue(originalEdge.ack_required, true)} onChange={(event) => updateTaskGraphEdge(edgeId, { ack_required: event.target.checked })} type="checkbox" />
            需要目标节点确认接收
          </label>
          <TaskSystemField label="模型可见标签" wide>
            <input onChange={(event) => patchEdgeMetadata({ model_visible_label: event.target.value })} value={stringValue(edgeMetadata.model_visible_label)} />
          </TaskSystemField>
          <TaskSystemField label="Prompt 使用说明" wide>
            <textarea onChange={(event) => patchEdgeMetadata({ usage_instruction: event.target.value })} value={stringValue(edgeMetadata.usage_instruction)} />
          </TaskSystemField>
        </div>
      </TaskGraphInspectorSection>

      <TaskGraphInspectorSection icon={<Layers3 aria-hidden="true" size={15} />} title="边时序与记忆交接">
        <div className="boundary-form task-graph-composer-inspector-form">
          <SupportMatrixNote />
          <SupportedSelectField field="trigger_timing" label="触发时机" onChange={(value) => patchEdgeTemporal({ trigger_timing: value })} options={["after_source_success", "after_required_contracts", "manual_release", "phase_entry", "phase_exit"]} value={stringValue(temporal.trigger_timing ?? edgeMetadata.trigger_timing, "after_source_success")} />
          <SupportedSelectField field="visibility_timing" label="可见时机" onChange={(value) => patchEdgeTemporal({ visibility_timing: value })} options={["same_clock", "next_clock", "after_commit", "next_iteration", "manual_release"]} value={stringValue(temporal.visibility_timing ?? edgeMetadata.visibility_timing, "after_commit")} />
          <SupportedSelectField field="acknowledgement_timing" label="确认时机" onChange={(value) => patchEdgeTemporal({ acknowledgement_timing: value })} options={["no_ack", "explicit_ack", "ack_before_downstream", "ack_before_phase_exit"]} value={stringValue(temporal.acknowledgement_timing ?? edgeMetadata.acknowledgement_timing, "explicit_ack")} />
          <SupportedSelectField field="propagation_timing" label="传播策略" onChange={(value) => patchEdgeTemporal({ propagation_timing: value })} options={["immediate", "buffer_until_commit", "summary_only", "refs_only", "blocked_on_failure"]} value={stringValue(temporal.propagation_timing ?? edgeMetadata.propagation_timing, "buffer_until_commit")} />
          <TaskSystemField label="携带记忆 Kind">
            <textarea onChange={(event) => patchEdgeMemoryHandoff({ carry_kinds: splitList(event.target.value) })} value={listText(handoff.carry_kinds)} />
          </TaskSystemField>
          <TaskSystemField label="携带记忆 Scope">
            <textarea onChange={(event) => patchEdgeMemoryHandoff({ carry_scopes: splitList(event.target.value) })} value={listText(handoff.carry_scopes)} />
          </TaskSystemField>
          <label className="boundary-check">
            <input checked={handoff.summary_only === true} onChange={(event) => patchEdgeMemoryHandoff({ summary_only: event.target.checked })} type="checkbox" />
            只传摘要或引用，不复制正文
          </label>
        </div>
      </TaskGraphInspectorSection>

      <TaskGraphInspectorSection icon={<Cable aria-hidden="true" size={15} />} title="端口映射诊断">
        <div className="task-graph-note">
          <strong>端口边由 canonical edge 派生</strong>
          <span>这里不再新增 metadata 覆盖边；需要运行时生效的连接应在拓扑编辑中创建或修改规范边。</span>
        </div>
      </TaskGraphInspectorSection>
    </>
  );
}
