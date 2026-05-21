import { Cable, Layers3, Plus, Trash2 } from "lucide-react";

import type { UnitInterfaceSpec, UnitPortEdgeSpec } from "@/lib/api";

import { TaskGraphContractBindingInspector } from "./TaskGraphContractBindingInspector";
import { edgePayloadContractIdOf } from "./taskGraphContractBindings";
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
  addOverlayPortEdge,
  edge,
  isOverlay,
  originalEdge,
  removeOverlayEdge,
  updateLegacyEdgeEndpoint,
  updateOverlayPortEdge,
  updateOverlayPortEdgeTemporal,
  updateTaskGraphEdge,
  ...shared
}: SharedEdgeProps & {
  addOverlayPortEdge: (seed?: Partial<UnitPortEdgeSpec>) => void;
  edge: UnitPortEdgeSpec;
  isOverlay: boolean;
  originalEdge: Record<string, unknown> | null;
  removeOverlayEdge: (edgeId: string) => void;
  updateLegacyEdgeEndpoint: (edge: Record<string, unknown>, edgeId: string, patch: Record<string, unknown>) => void;
  updateOverlayPortEdge: (edge: UnitPortEdgeSpec, patch: Record<string, unknown>) => void;
  updateOverlayPortEdgeTemporal: (edge: UnitPortEdgeSpec, patch: Record<string, unknown>) => void;
  updateTaskGraphEdge: (edgeId: string, patch: Record<string, unknown>) => void;
}) {
  if (isOverlay) {
    return (
      <OverlayPortEdgeInspector
        edge={edge}
        removeOverlayEdge={removeOverlayEdge}
        updateOverlayPortEdge={updateOverlayPortEdge}
        updateOverlayPortEdgeTemporal={updateOverlayPortEdgeTemporal}
        {...shared}
      />
    );
  }
  if (originalEdge) {
    return (
      <LegacyPortEdgeInspector
        addOverlayPortEdge={addOverlayPortEdge}
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
        <span>可以升级为显式端口边，让配置写入可组合覆盖层。</span>
      </div>
      <button className="task-graph-composer-subtle-action" onClick={() => addOverlayPortEdge(edge)} type="button">升级为显式端口边</button>
    </TaskGraphInspectorSection>
  );
}

function OverlayPortEdgeInspector({
  edge,
  formatContract,
  formatUnit,
  interfaces,
  contractOptions,
  removeOverlayEdge,
  unitOptions,
  updateOverlayPortEdge,
  updateOverlayPortEdgeTemporal,
}: SharedEdgeProps & {
  edge: UnitPortEdgeSpec;
  removeOverlayEdge: (edgeId: string) => void;
  updateOverlayPortEdge: (edge: UnitPortEdgeSpec, patch: Record<string, unknown>) => void;
  updateOverlayPortEdgeTemporal: (edge: UnitPortEdgeSpec, patch: Record<string, unknown>) => void;
}) {
  const sourcePorts = portOptionsForUnit(edge.source_unit_id, interfaces, "output");
  const targetPorts = portOptionsForUnit(edge.target_unit_id, interfaces, "input");
  return (
    <TaskGraphInspectorSection icon={<Cable aria-hidden="true" size={15} />} title="显式端口边" aside="覆盖层">
      <TaskGraphInspectorSummary
        overline={edge.edge_type || "handoff"}
        title={edge.edge_id || "未命名端口边"}
        caption={edgeSourceSummary(edge)}
      />
      <div className="boundary-form task-graph-composer-inspector-form">
        <TaskSystemField label="边 ID" wide>
          <input onChange={(event) => updateOverlayPortEdge(edge, { edge_id: event.target.value })} value={edge.edge_id} />
        </TaskSystemField>
        <TaskGraphObjectSelectField formatOption={formatUnit} label="源单元" onChange={(value) => updateOverlayPortEdge(edge, { source_unit_id: value, source_port_id: portOptionsForUnit(value, interfaces, "output")[0] ?? "output.default" })} options={unitOptions} value={edge.source_unit_id} />
        <TaskSystemSelectField label="源端口" onChange={(value) => updateOverlayPortEdge(edge, { source_port_id: value })} options={sourcePorts} value={edge.source_port_id} />
        <TaskGraphObjectSelectField formatOption={formatUnit} label="目标单元" onChange={(value) => updateOverlayPortEdge(edge, { target_unit_id: value, target_port_id: portOptionsForUnit(value, interfaces, "input")[0] ?? "input.default" })} options={unitOptions} value={edge.target_unit_id} />
        <TaskSystemSelectField label="目标端口" onChange={(value) => updateOverlayPortEdge(edge, { target_port_id: value })} options={targetPorts} value={edge.target_port_id} />
        <TaskGraphObjectSelectField formatOption={formatContract} label="载荷契约" onChange={(value) => updateOverlayPortEdge(edge, { payload_contract_id: value })} options={contractOptions} value={edge.payload_contract_id ?? ""} wide />
        <TaskSystemSelectField label="边类型" onChange={(value) => updateOverlayPortEdge(edge, { edge_type: value })} options={["handoff", "memory_handoff", "artifact_context", "temporal_dependency"]} value={edge.edge_type ?? "handoff"} />
        <SupportMatrixNote />
        <SupportedSelectField field="trigger_timing" label="触发时机" onChange={(value) => updateOverlayPortEdgeTemporal(edge, { trigger_timing: value })} options={["after_source_success", "after_source_commit", "manual_release", "phase_gate_passed"]} value={stringValue(asRecord(edge.temporal_semantics).trigger_timing, "after_source_success")} />
        <SupportedSelectField field="visibility_timing" label="可见时机" onChange={(value) => updateOverlayPortEdgeTemporal(edge, { visibility_timing: value })} options={["after_commit", "after_ack", "same_clock", "next_clock"]} value={stringValue(asRecord(edge.temporal_semantics).visibility_timing, "after_commit")} />
        <SupportedSelectField field="acknowledgement_timing" label="确认时机" onChange={(value) => updateOverlayPortEdgeTemporal(edge, { acknowledgement_timing: value })} options={["explicit_ack", "implicit_ack", "manual_ack", "none"]} value={stringValue(asRecord(edge.temporal_semantics).acknowledgement_timing, "explicit_ack")} />
        <SupportedSelectField field="propagation_timing" label="传播策略" onChange={(value) => updateOverlayPortEdgeTemporal(edge, { propagation_timing: value })} options={["buffer_until_commit", "immediate_refs_only", "manual_release", "block_until_ack"]} value={stringValue(asRecord(edge.temporal_semantics).propagation_timing, "buffer_until_commit")} />
        <button className="task-graph-inline-danger" onClick={() => removeOverlayEdge(edge.edge_id)} type="button">
          <Trash2 aria-hidden="true" size={14} />
          移除覆盖边
        </button>
      </div>
    </TaskGraphInspectorSection>
  );
}

function LegacyPortEdgeInspector({
  addOverlayPortEdge,
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
  addOverlayPortEdge: (seed?: Partial<UnitPortEdgeSpec>) => void;
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
  const payloadContractId = edgePayloadContractIdOf({
    ...originalEdge,
    payload_contract_id: stringValue(originalEdge.payload_contract_id ?? edge.payload_contract_id),
  });

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

      <TaskGraphInspectorSection icon={<Plus aria-hidden="true" size={15} />} title="端口化">
        <div className="task-graph-note">
          <strong>升级为显式端口边</strong>
          <span>显式边会写入 metadata.composable_graph.port_edges，可以连接图模块、普通节点和资源 Unit 的端口。</span>
        </div>
        <button
          className="task-graph-composer-subtle-action"
          onClick={() => addOverlayPortEdge({
            ...edge,
            payload_contract_id: payloadContractId,
            edge_type: stringValue(originalEdge.edge_type ?? originalEdge.mode ?? edge.edge_type, "handoff"),
            handoff: {
              ...asRecord(edge.handoff),
              wait_policy: originalEdge.wait_policy,
              ack_policy: originalEdge.ack_policy,
              ack_required: originalEdge.ack_required,
              failure_propagation_policy: originalEdge.failure_propagation_policy,
              result_delivery_policy: originalEdge.result_delivery_policy,
            },
            metadata: {
              ...asRecord(edge.metadata),
              upgraded_from_edge_id: edgeId,
            },
          })}
          type="button"
        >
          升级为显式端口边
        </button>
      </TaskGraphInspectorSection>
    </>
  );
}
