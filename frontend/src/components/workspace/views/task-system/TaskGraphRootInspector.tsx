import { GitBranch, Layers3, Plus, RotateCw } from "lucide-react";

import type { TaskGraphDraftV2 } from "./taskGraphDraftV2";
import { TaskGraphContractBindingInspector } from "./TaskGraphContractBindingInspector";
import {
  TaskGraphInspectorSection,
  TaskGraphInspectorSummary,
  TaskGraphObjectSelectField,
} from "./TaskGraphInspectorPrimitives";
import {
  buildTaskGraphRuntimeLoopInputPatch,
  resolvedTaskGraphRuntimeLoopInitialInputs,
  taskGraphRuntimeLoopFrames,
  taskGraphRuntimeLoopNumber,
  taskGraphRuntimeLoopRecord,
} from "./taskGraphRuntimeLoopConfig";
import { TaskSystemField, TaskSystemSelectField } from "./TaskSystemWorkbenchUi";
import { mergeContractBindingPath } from "./taskGraphContractBindings";

function stringValue(value: unknown, fallback = "") {
  const next = String(value ?? "").trim();
  return next || fallback;
}

export function TaskGraphRootInspector({
  activeGraphNodes,
  addTimelineBlock,
  agentOptions,
  contractOptions,
  formatAgent,
  formatContract,
  graphDraft,
  graphName,
  interfaceCount,
  nodeTitle,
  portEdgeCount,
  unitsCount,
  graphModuleCount,
  updateTaskGraphDraft,
  updateTaskGraphRuntimePolicy,
}: {
  activeGraphNodes: Array<Record<string, unknown>>;
  addTimelineBlock: () => void;
  agentOptions: string[];
  contractOptions: string[];
  formatAgent: (agentId: string) => string;
  formatContract: (contractId: string) => string;
  graphDraft: TaskGraphDraftV2;
  graphName: string;
  graphModuleCount: number;
  interfaceCount: number;
  nodeTitle: (node: Record<string, unknown> | null, fallback?: string) => string;
  portEdgeCount: number;
  unitsCount: number;
  updateTaskGraphDraft: (patch: Partial<TaskGraphDraftV2>) => void;
  updateTaskGraphRuntimePolicy: (patch: Partial<TaskGraphDraftV2["runtime_policy"]>) => void;
}) {
  const nodeOptions = activeGraphNodes.map((node) => stringValue(node.node_id)).filter(Boolean);
  const formatNode = (value: string) => nodeTitle(activeGraphNodes.find((node) => stringValue(node.node_id) === value) ?? null, value);
  const loopInputs = resolvedTaskGraphRuntimeLoopInitialInputs(graphDraft);
  const loopFrames = taskGraphRuntimeLoopFrames(graphDraft);
  const unitsPerBatch = taskGraphRuntimeLoopNumber(loopInputs.units_per_batch, 1);
  const unitsPerGroup = taskGraphRuntimeLoopNumber(loopInputs.units_per_group, 1);
  const targetGroupCount = taskGraphRuntimeLoopNumber(loopInputs.target_group_count, 1);
  const unitTargetMeasure = taskGraphRuntimeLoopNumber(loopInputs.unit_target_measure, 0);
  const groupTargetMeasure = taskGraphRuntimeLoopNumber(loopInputs.group_target_measure, unitsPerGroup * unitTargetMeasure);
  const targetMeasureUnits = taskGraphRuntimeLoopNumber(loopInputs.target_measure_units, targetGroupCount * groupTargetMeasure);
  const lengthBudget = taskGraphRuntimeLoopRecord(taskGraphRuntimeLoopRecord(taskGraphRuntimeLoopRecord(graphDraft.contract_bindings).runtime).length_budget);
  const lengthBudgetRepairPolicy = taskGraphRuntimeLoopRecord(lengthBudget.repair_policy);
  const lengthBudgetAcceptancePolicy = taskGraphRuntimeLoopRecord(lengthBudget.acceptance_policy);
  const lengthBudgetEnabled = lengthBudget.enabled === true
    || taskGraphRuntimeLoopNumber(lengthBudget.target_units, 0) > 0
    || taskGraphRuntimeLoopNumber(lengthBudget.min_units, 0) > 0
    || taskGraphRuntimeLoopNumber(lengthBudget.max_units, 0) > 0;
  const updateRuntimeLoopInput = (key: string, value: unknown) => {
    updateTaskGraphDraft(buildTaskGraphRuntimeLoopInputPatch(graphDraft, key, value));
  };
  const updateLengthBudget = (path: string[], value: unknown) => {
    updateTaskGraphDraft(mergeContractBindingPath(graphDraft, "runtime", ["length_budget", ...path], value));
  };
  void formatContract;
  return (
    <>
      <TaskGraphInspectorSection icon={<GitBranch aria-hidden="true" size={15} />} title="任务图" aside={graphDraft.graph_id}>
        <TaskGraphInspectorSummary
          caption="任务图是流程结构；运行时会按节点时序点生成任务动作。"
          metrics={[
            { label: "节点/Unit", value: unitsCount },
            { label: "接口", value: interfaceCount },
            { label: "交接边", value: portEdgeCount },
            { label: "图模块", value: graphModuleCount },
          ]}
          overline="当前任务图"
          title={graphName}
        />
      </TaskGraphInspectorSection>

      <TaskGraphInspectorSection icon={<GitBranch aria-hidden="true" size={15} />} title="任务图配置">
        <div className="boundary-form task-graph-composer-inspector-form">
          <TaskSystemField label="中文名 / 标题" wide>
            <input onChange={(event) => updateTaskGraphDraft({ title: event.target.value })} value={graphDraft.title} />
          </TaskSystemField>
          <TaskGraphObjectSelectField
            formatOption={formatNode}
            label="入口节点"
            onChange={(value) => updateTaskGraphDraft({ entry_node_id: value })}
            options={nodeOptions}
            value={graphDraft.entry_node_id}
          />
          <TaskGraphObjectSelectField
            formatOption={formatNode}
            label="出口节点"
            onChange={(value) => updateTaskGraphDraft({ output_node_id: value })}
            options={nodeOptions}
            value={graphDraft.output_node_id}
          />
          <TaskGraphObjectSelectField
            formatOption={formatAgent}
            label="协调 Agent"
            onChange={(value) => updateTaskGraphRuntimePolicy({ coordinator_agent_id: value })}
            options={agentOptions}
            value={stringValue(graphDraft.runtime_policy.coordinator_agent_id, "agent:0")}
            wide
          />
          <TaskSystemSelectField
            label="协作模式"
            onChange={(value) => updateTaskGraphRuntimePolicy({ coordination_mode: value })}
            options={["review_merge", "pipeline", "parallel_review"]}
            value={stringValue(graphDraft.runtime_policy.coordination_mode, "review_merge")}
          />
        </div>
      </TaskGraphInspectorSection>

      <TaskGraphContractBindingInspector
        contractOptions={contractOptions}
        fieldKeysBySection={{
          schema: ["graph_contract_id"],
          runtime: ["model_requirement.profile_ref", "model_requirement.provider_family", "model_requirement.min_output_tokens", "model_requirement.preferred_output_tokens", "model_requirement.capability_tags", "length_budget.enabled", "length_budget.budget_scope", "length_budget.measurement_mode", "length_budget.unit_kind", "length_budget.unit_label_zh", "length_budget.target_units", "length_budget.min_units", "length_budget.max_units", "length_budget.batch_unit_count", "length_budget.repair_policy.mode", "length_budget.repair_policy.max_repair_rounds", "length_budget.acceptance_policy.require_continuity", "length_budget.acceptance_policy.require_formal_headings"],
          memory: ["memory_read_policy_ref", "dynamic_memory_read_policy_ref", "memory_writeback_policy_ref"],
          handoff: ["wait_policy", "failure_propagation_policy", "result_delivery_policy"],
          acceptance: ["human_gate_policy.mode", "human_gate_policy.blocking", "acceptance_policy_ref"],
          governance: ["thread_ledger_policy_ref", "issue_ledger_policy_ref", "context_boundary_policy_ref"],
        }}
        formatContract={formatContract}
        onChange={(patch) => updateTaskGraphDraft(patch)}
        sections={["schema", "runtime", "memory", "handoff", "acceptance", "governance"]}
        target={graphDraft}
      />

      <TaskGraphInspectorSection icon={<RotateCw aria-hidden="true" size={15} />} title="循环与批次" aside="graph runtime">
        <div className="task-graph-batch-contract">
          <div className="task-graph-note">
            <strong>{targetGroupCount || 1} 组 · 每组 {unitsPerGroup || 0} 单元 · 每批 {unitsPerBatch || 0} 单元</strong>
            <span>这些是任务图级规模参数；节点只执行当前生命周期坐标，完整循环由图级帧和路由节点推进。</span>
          </div>
          <div className="boundary-form task-graph-composer-inspector-form">
            <TaskSystemField label="目标组数">
              <input
                min={1}
                onChange={(event) => updateRuntimeLoopInput("target_group_count", Number(event.target.value || 1))}
                type="number"
                value={targetGroupCount}
              />
            </TaskSystemField>
            <TaskSystemField label="每组单元">
              <input
                min={1}
                onChange={(event) => {
                  const value = Number(event.target.value || 1);
                  updateRuntimeLoopInput("units_per_group", value);
                }}
                type="number"
                value={unitsPerGroup}
              />
            </TaskSystemField>
            <TaskSystemField label="每批单元">
              <input
                min={1}
                onChange={(event) => updateRuntimeLoopInput("units_per_batch", Number(event.target.value || 1))}
                type="number"
                value={unitsPerBatch}
              />
            </TaskSystemField>
            <TaskSystemField label="单元目标量">
              <input
                min={0}
                onChange={(event) => updateRuntimeLoopInput("unit_target_measure", Number(event.target.value || 0))}
                type="number"
                value={unitTargetMeasure}
              />
            </TaskSystemField>
            <TaskSystemField label="单组目标量">
              <input
                min={0}
                onChange={(event) => updateRuntimeLoopInput("group_target_measure", Number(event.target.value || 0))}
                type="number"
                value={groupTargetMeasure}
              />
            </TaskSystemField>
            <TaskSystemField label="总目标量">
              <input
                min={0}
                onChange={(event) => updateRuntimeLoopInput("target_measure_units", Number(event.target.value || 0))}
                type="number"
                value={targetMeasureUnits}
              />
            </TaskSystemField>
          </div>
          <div className="task-graph-note">
            <strong>{String(lengthBudget.unit_label_zh ?? "单元")} 长度预算</strong>
            <span>这里是业务契约，不是模型上限。它会进入 runtime.length_budget，并在运行时作为验收门使用。</span>
          </div>
          <div className="boundary-form task-graph-composer-inspector-form">
            <label className="boundary-check">
              <input checked={lengthBudgetEnabled} onChange={(event) => updateLengthBudget(["enabled"], event.target.checked)} type="checkbox" />
              启用长度预算验收
            </label>
            <TaskSystemSelectField
              label="预算范围"
              onChange={(value) => updateLengthBudget(["budget_scope"], value)}
              options={["graph", "group", "batch", "node"]}
              value={String(lengthBudget.budget_scope ?? "graph")}
            />
            <TaskSystemSelectField
              label="计量方式"
              onChange={(value) => updateLengthBudget(["measurement_mode"], value)}
              options={["text_units", "tokens", "hybrid"]}
              value={String(lengthBudget.measurement_mode ?? "text_units")}
            />
            <TaskSystemField label="目标长度">
              <input min={1} onChange={(event) => updateLengthBudget(["target_units"], Number(event.target.value || 0))} type="number" value={Number(lengthBudget.target_units ?? targetMeasureUnits)} />
            </TaskSystemField>
            <TaskSystemField label="最小长度">
              <input min={1} onChange={(event) => updateLengthBudget(["min_units"], Number(event.target.value || 0))} type="number" value={Number(lengthBudget.min_units ?? unitTargetMeasure)} />
            </TaskSystemField>
            <TaskSystemField label="最大长度">
              <input min={1} onChange={(event) => updateLengthBudget(["max_units"], Number(event.target.value || 0))} type="number" value={Number(lengthBudget.max_units ?? targetMeasureUnits)} />
            </TaskSystemField>
            <TaskSystemField label="单元数量">
              <input min={1} onChange={(event) => updateLengthBudget(["batch_unit_count"], Number(event.target.value || 0))} type="number" value={Number(lengthBudget.batch_unit_count ?? unitsPerBatch)} />
            </TaskSystemField>
            <TaskSystemField label="单元中文名">
              <input onChange={(event) => updateLengthBudget(["unit_label_zh"], event.target.value)} value={String(lengthBudget.unit_label_zh ?? "单元")} />
            </TaskSystemField>
          </div>
          <div className="boundary-form task-graph-composer-inspector-form">
            <TaskSystemSelectField
              label="修复策略"
              onChange={(value) => updateLengthBudget(["repair_policy", "mode"], value)}
              options={["expand_or_split", "split_first", "expand_first"]}
              value={String(lengthBudgetRepairPolicy.mode ?? "expand_or_split")}
            />
            <TaskSystemField label="最大修复轮次">
              <input min={0} onChange={(event) => updateLengthBudget(["repair_policy", "max_repair_rounds"], Number(event.target.value || 0))} type="number" value={Number(lengthBudgetRepairPolicy.max_repair_rounds ?? 2)} />
            </TaskSystemField>
            <label className="boundary-check">
              <input checked={Boolean(lengthBudgetAcceptancePolicy.require_continuity ?? true)} onChange={(event) => updateLengthBudget(["acceptance_policy", "require_continuity"], event.target.checked)} type="checkbox" />
              需要连续性
            </label>
            <label className="boundary-check">
              <input checked={Boolean(lengthBudgetAcceptancePolicy.require_formal_headings ?? true)} onChange={(event) => updateLengthBudget(["acceptance_policy", "require_formal_headings"], event.target.checked)} type="checkbox" />
              需要正式标题
            </label>
          </div>
          <div className="task-graph-composer-kv">
            {loopFrames.map((frame) => (
              <p key={stringValue(frame.frame_id)}>
                <span>{stringValue(frame.title ?? frame.frame_id, "循环帧")}</span>
                <strong>{`${stringValue(frame.entry_stage_id, "入口")} -> ${stringValue(frame.router_stage_id ?? frame.exit_stage_id, "路由")}`}</strong>
              </p>
            ))}
          </div>
        </div>
      </TaskGraphInspectorSection>

      <TaskGraphInspectorSection icon={<Plus aria-hidden="true" size={15} />} title="结构动作">
        <div className="task-graph-topology-actions task-graph-topology-actions--stacked">
          <button onClick={addTimelineBlock} type="button">
            <Layers3 aria-hidden="true" size={14} />
            <span>新增图模块来源</span>
          </button>
        </div>
        <div className="task-graph-note">
          <strong>端口边由 canonical edges 派生</strong>
          <span>新增运行边请回到 Graph Builder；metadata 覆盖边只作为迁移诊断保留。</span>
        </div>
      </TaskGraphInspectorSection>
    </>
  );
}
