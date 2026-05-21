import { ExternalLink, Layers3, Network, Trash2 } from "lucide-react";

import type { ComposableUnitSpec, GraphModuleRuntimePlanSpec, TaskGraphRecord } from "@/lib/api";

import { TaskGraphContractBindingInspector } from "./TaskGraphContractBindingInspector";
import {
  TaskGraphInspectorSection,
  TaskGraphInspectorSummary,
  TaskGraphObjectSelectField,
} from "./TaskGraphInspectorPrimitives";
import { TaskSystemField, TaskSystemSelectField } from "./TaskSystemWorkbenchUi";
import { timelineBlockHandoffContractIdOf, type TaskGraphTimelineBlock } from "./taskGraphTimeline";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function stringValue(value: unknown, fallback = "") {
  const next = String(value ?? "").trim();
  return next || fallback;
}

function blockIdFromUnit(unit: ComposableUnitSpec | null) {
  return stringValue(asRecord(unit?.ref).timeline_block_id);
}

type TimelineBlockEditorProps = {
  contractOptions: string[];
  formatContract: (contractId: string) => string;
  formatGraph: (graphId: string) => string;
  graphOptions: string[];
  updateTimelineBlock: (blockId: string, patch: Record<string, unknown>) => void;
};

function TimelineBlockFields({
  formatGraph,
  graphOptions,
  selected,
  updateTimelineBlock,
}: Omit<TimelineBlockEditorProps, "contractOptions" | "formatContract"> & {
  selected: TaskGraphTimelineBlock;
}) {
  return (
    <div className="boundary-form task-graph-composer-inspector-form">
      <TaskSystemField label="中文名" wide>
        <input onChange={(event) => updateTimelineBlock(selected.block_id, { title: event.target.value })} value={selected.title} />
      </TaskSystemField>
      <TaskSystemSelectField label="图块类型" onChange={(value) => updateTimelineBlock(selected.block_id, { block_type: value })} options={["phase_graph", "design_graph", "creation_graph", "closing_graph", "review_graph"]} value={selected.block_type} />
      <TaskSystemField label="所属阶段">
        <input onChange={(event) => updateTimelineBlock(selected.block_id, { phase_id: event.target.value })} value={selected.phase_id} />
      </TaskSystemField>
      <TaskGraphObjectSelectField
        emptyLabel="不绑定图模块"
        formatOption={formatGraph}
        label="导入图模块"
        onChange={(value) => updateTimelineBlock(selected.block_id, { linked_graph_id: value })}
        options={graphOptions}
        value={selected.linked_graph_id ?? ""}
        wide
      />
      <TaskSystemSelectField label="可见性" onChange={(value) => updateTimelineBlock(selected.block_id, { visibility_policy: value })} options={["committed_only", "summary_and_refs", "manual_release", "isolated_until_commit"]} value={selected.visibility_policy ?? "committed_only"} />
      <TaskSystemField label="版本锚点">
        <input onChange={(event) => updateTimelineBlock(selected.block_id, { version_ref: event.target.value })} placeholder="v1 / draft / published" value={selected.version_ref ?? ""} />
      </TaskSystemField>
      <TaskSystemSelectField label="断开策略" onChange={(value) => updateTimelineBlock(selected.block_id, { detach_policy: value })} options={["preserve_version_anchor", "fork_as_independent_graph", "require_rehandoff_packet"]} value={selected.detach_policy ?? "preserve_version_anchor"} />
    </div>
  );
}

export function TaskGraphGraphModuleInspector({
  blocks,
  contractOptions,
  formatContract,
  formatGraph,
  graphOptions,
  onOpenGraph,
  selected,
  taskGraphs,
  updateTimelineBlock,
}: TimelineBlockEditorProps & {
  blocks: TaskGraphTimelineBlock[];
  onOpenGraph?: (graphId: string) => void;
  selected: ComposableUnitSpec;
  taskGraphs?: TaskGraphRecord[];
}) {
  const ref = asRecord(selected.ref);
  const blockId = blockIdFromUnit(selected);
  const selectedBlock = blockId ? blocks.find((item) => item.block_id === blockId) ?? null : null;
  const linkedGraphId = stringValue(ref.graph_id ?? selectedBlock?.linked_graph_id);
  const linkedGraph = linkedGraphId ? taskGraphs?.find((item) => item.graph_id === linkedGraphId) ?? null : null;
  const handoffContractId = selectedBlock ? timelineBlockHandoffContractIdOf(selectedBlock as unknown as Record<string, unknown>) : "";

  return (
    <>
      <TaskGraphInspectorSection icon={<Network aria-hidden="true" size={15} />} title="图模块边界" aside="导入图模块">
        <TaskGraphInspectorSummary
          caption={selected.unit_id}
          metrics={[
            { label: "图块", value: selectedBlock?.block_id || blockId || "未映射" },
            { label: "图模块", value: linkedGraphId || "未绑定" },
            { label: "版本", value: selectedBlock?.version_ref || stringValue(ref.version_ref, "未锚定") },
            { label: "契约", value: handoffContractId || "未声明" },
          ]}
          overline={selected.source_kind || "timeline_block"}
          title={selectedBlock?.title || selected.title || selected.unit_id}
        />
        <div className="task-graph-note">
          <strong>图模块是模块边界</strong>
          <span>这里配置导入图模块时使用的入口、版本和交接边界；模块内部节点请进入该图模块工作台编辑。</span>
        </div>
      </TaskGraphInspectorSection>

      {selectedBlock ? (
        <TaskGraphInspectorSection icon={<Layers3 aria-hidden="true" size={15} />} title="图模块边界">
          <TimelineBlockFields
            formatGraph={formatGraph}
            graphOptions={graphOptions}
            selected={selectedBlock}
            updateTimelineBlock={updateTimelineBlock}
          />
        </TaskGraphInspectorSection>
      ) : null}

      {selectedBlock ? (
        <TaskGraphContractBindingInspector
          contractOptions={contractOptions}
          fieldKeysBySection={{
            handoff: ["handoff_contract_id", "wait_policy", "failure_propagation_policy", "result_delivery_policy"],
            runtime: ["model_requirement.profile_ref", "model_requirement.provider_family", "length_budget.enabled", "length_budget.budget_scope", "length_budget.measurement_mode", "length_budget.target_units", "length_budget.min_units", "length_budget.max_units", "length_budget.batch_unit_count"],
            governance: ["context_boundary_policy_ref"],
            temporal: ["trigger_timing", "visibility_timing", "propagation_timing"],
          }}
          formatContract={formatContract}
          onChange={(patch) => updateTimelineBlock(selectedBlock.block_id, patch)}
          sections={["handoff", "runtime", "governance", "temporal"]}
          target={selectedBlock as unknown as Record<string, unknown>}
        />
      ) : null}

      <TaskGraphInspectorSection icon={<ExternalLink aria-hidden="true" size={15} />} title="图模块工作台">
        <div className="task-graph-topology-actions task-graph-topology-actions--stacked">
          <button disabled={!linkedGraphId || !linkedGraph || !onOpenGraph} onClick={() => linkedGraphId && onOpenGraph?.(linkedGraphId)} type="button">
            <ExternalLink aria-hidden="true" size={14} />
            <span>{linkedGraph ? "进入图模块工作台" : linkedGraphId ? "图模块未在当前任务域找到" : "未绑定图模块"}</span>
          </button>
        </div>
      </TaskGraphInspectorSection>
    </>
  );
}

export function TaskGraphTimelineBlockInspector({
  contractOptions,
  formatContract,
  formatGraph,
  graphOptions,
  removeTimelineBlock,
  selected,
  updateTimelineBlock,
}: TimelineBlockEditorProps & {
  removeTimelineBlock: (blockId: string) => void;
  selected: TaskGraphTimelineBlock;
}) {
  return (
    <TaskGraphInspectorSection icon={<Layers3 aria-hidden="true" size={15} />} title="图模块来源" aside="timeline_blocks">
      <TaskGraphInspectorSummary
        caption={selected.block_id}
        overline={selected.block_type}
        title={selected.title || selected.block_id}
      />
      <TimelineBlockFields
        formatGraph={formatGraph}
        graphOptions={graphOptions}
        selected={selected}
        updateTimelineBlock={updateTimelineBlock}
      />
      <TaskGraphContractBindingInspector
        contractOptions={contractOptions}
        fieldKeysBySection={{
          handoff: ["handoff_contract_id", "wait_policy", "failure_propagation_policy", "result_delivery_policy"],
          runtime: ["model_requirement.profile_ref", "model_requirement.provider_family", "length_budget.enabled", "length_budget.budget_scope", "length_budget.measurement_mode", "length_budget.target_units", "length_budget.min_units", "length_budget.max_units", "length_budget.batch_unit_count"],
          governance: ["context_boundary_policy_ref"],
          temporal: ["trigger_timing", "visibility_timing", "propagation_timing"],
        }}
        formatContract={formatContract}
        onChange={(patch) => updateTimelineBlock(selected.block_id, patch)}
        sections={["handoff", "runtime", "governance", "temporal"]}
        target={selected as unknown as Record<string, unknown>}
      />
      <button className="task-graph-inline-danger" onClick={() => removeTimelineBlock(selected.block_id)} type="button">
        <Trash2 aria-hidden="true" size={14} />
        移除图模块来源
      </button>
    </TaskGraphInspectorSection>
  );
}

export function TaskGraphModuleRuntimeInspector({ plan }: { plan: GraphModuleRuntimePlanSpec }) {
  return (
    <TaskGraphInspectorSection icon={<Network aria-hidden="true" size={15} />} title="图模块运行" aside="标准视图">
      <TaskGraphInspectorSummary
        caption={plan.plan_id}
        metrics={[
          { label: "Unit", value: plan.unit_id },
          { label: "版本", value: plan.version_ref || "未锚定" },
          { label: "交接契约", value: plan.handoff_contract_id || "未声明" },
          { label: "隔离", value: plan.isolation_policy || "isolated_per_graph_module_run" },
        ]}
        overline={plan.visibility_policy || "committed_only"}
        title={plan.linked_graph_id || plan.plan_id}
      />
      <div className="task-graph-note">
        <strong>运行边界来自图模块配置</strong>
        <span>请通过图模块的 linked_graph_id、version_ref、handoff_contract_id 和可见性策略维护这份运行计划。</span>
      </div>
    </TaskGraphInspectorSection>
  );
}
