import { SplitSquareVertical } from "lucide-react";

import {
  contractBindingPathValue,
  mergeContractBindingPath,
  runtimeBatchAcceptancePolicyOf,
  runtimeMergePolicyOf,
  runtimeSplitPolicyOf,
  unitBatchContractOf,
} from "./taskGraphContractBindings";
import { TaskGraphInspectorSection } from "./TaskGraphInspectorPrimitives";
import {
  TaskSystemField,
  TaskSystemSelectField,
  taskSystemOptionLabel,
} from "./TaskSystemWorkbenchUi";

function stringValue(value: unknown, fallback = "") {
  const next = String(value ?? "").trim();
  return next || fallback;
}

function numberValue(value: unknown, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function booleanValue(value: unknown, fallback = false) {
  return typeof value === "boolean" ? value : fallback;
}

function batchCount(requestedCount: number, batchSize: number) {
  if (requestedCount <= 0 || batchSize <= 0) return 0;
  return Math.ceil(requestedCount / batchSize);
}

function fieldValue(target: Record<string, unknown>, section: string, path: string[]) {
  return contractBindingPathValue(target, section, path);
}

export function TaskGraphNodeBatchContractInspector({
  node,
  onChange,
}: {
  node: Record<string, unknown>;
  onChange: (patch: Record<string, unknown>) => void;
}) {
  const unitBatch = unitBatchContractOf(node);
  const splitPolicy = runtimeSplitPolicyOf(node);
  const acceptancePolicy = runtimeBatchAcceptancePolicyOf(node);
  const mergePolicy = runtimeMergePolicyOf(node);
  const unitKind = stringValue(unitBatch.unit_kind, "unit");
  const requestedCount = numberValue(unitBatch.requested_count);
  const rangeStart = numberValue(unitBatch.range_start, 1);
  const batchSize = numberValue(splitPolicy.batch_size);
  const executionMode = stringValue(splitPolicy.child_execution_mode, "sequential");
  const maxParallelBatches = numberValue(splitPolicy.max_parallel_batches, 2);
  const projectedBatchCount = batchCount(requestedCount, batchSize);
  const update = (section: string, path: string[], value: unknown) => {
    onChange(mergeContractBindingPath(node, section, path, value));
  };

  return (
    <TaskGraphInspectorSection icon={<SplitSquareVertical aria-hidden="true" size={15} />} title="批次契约" aside="unit_batch / split">
      <div className="task-graph-batch-contract">
        <div className="task-graph-note">
          <strong>{projectedBatchCount ? `${projectedBatchCount} 个批次` : "未形成批次计划"}</strong>
          <span>节点声明处理的工作单元数量；编译器只生成范围计划，运行、审核和提交仍由任务图契约控制。</span>
        </div>
        <div className="boundary-form task-graph-composer-inspector-form">
          <TaskSystemField label="工作单元">
            <input
              onChange={(event) => update("unit_batch", ["unit_kind"], event.target.value)}
              placeholder="item / file / record"
              value={unitKind}
            />
          </TaskSystemField>
          <TaskSystemField label="总数量">
            <input
              min={0}
              onChange={(event) => update("unit_batch", ["requested_count"], Number(event.target.value || 0))}
              type="number"
              value={numberValue(fieldValue(node, "unit_batch", ["requested_count"]))}
            />
          </TaskSystemField>
          <TaskSystemField label="起始序号">
            <input
              min={1}
              onChange={(event) => update("unit_batch", ["range_start"], Number(event.target.value || 1))}
              type="number"
              value={rangeStart}
            />
          </TaskSystemField>
          <TaskSystemSelectField
            formatOption={taskSystemOptionLabel}
            label="拆分模式"
            onChange={(value) => update("runtime", ["split_policy", "mode"], value)}
            options={["static_batch"]}
            value={stringValue(splitPolicy.mode, "static_batch")}
          />
          <TaskSystemField label="每批数量">
            <input
              min={0}
              onChange={(event) => update("runtime", ["split_policy", "batch_size"], Number(event.target.value || 0))}
              type="number"
              value={batchSize}
            />
          </TaskSystemField>
          <TaskSystemField label="最多批次">
            <input
              min={1}
              onChange={(event) => update("runtime", ["split_policy", "max_batches"], Number(event.target.value || 1))}
              type="number"
              value={numberValue(splitPolicy.max_batches, 200)}
            />
          </TaskSystemField>
          <TaskSystemSelectField
            formatOption={taskSystemOptionLabel}
            label="执行模式"
            onChange={(value) => update("runtime", ["split_policy", "child_execution_mode"], value)}
            options={["sequential", "parallel"]}
            value={executionMode}
          />
          <TaskSystemField label="并行上限">
            <input
              disabled={executionMode !== "parallel"}
              min={1}
              onChange={(event) => update("runtime", ["split_policy", "max_parallel_batches"], Number(event.target.value || 1))}
              type="number"
              value={maxParallelBatches}
            />
          </TaskSystemField>
          <TaskSystemField label="范围标签模板" wide>
            <input
              onChange={(event) => update("runtime", ["split_policy", "range_label_template"], event.target.value)}
              placeholder="{unit_kind}_{start}_{end}"
              value={stringValue(splitPolicy.range_label_template, "{unit_kind}_{start}_{end}")}
            />
          </TaskSystemField>
        </div>

        <section className="task-graph-contract-binding-section">
          <header>
            <div>
              <strong>批次验收</strong>
              <span>决定每个批次通过后是否提交，以及失败时如何返修。</span>
            </div>
            <em>runtime.batch_acceptance_policy</em>
          </header>
          <div className="boundary-form task-graph-composer-inspector-form">
            <TaskSystemSelectField
              formatOption={taskSystemOptionLabel}
              label="验收模式"
              onChange={(value) => update("runtime", ["batch_acceptance_policy", "mode"], value)}
              options={["review_then_commit", "manual_review_then_commit", "auto_commit_without_review"]}
              value={stringValue(acceptancePolicy.mode, "review_then_commit")}
            />
            <TaskSystemField label="审核节点">
              <input
                onChange={(event) => update("runtime", ["batch_acceptance_policy", "review_node_id"], event.target.value)}
                placeholder="review node id"
                value={stringValue(acceptancePolicy.review_node_id)}
              />
            </TaskSystemField>
            <TaskSystemField label="审核图模块">
              <input
                onChange={(event) => update("runtime", ["batch_acceptance_policy", "review_graph_id"], event.target.value)}
                placeholder="review graph id"
                value={stringValue(acceptancePolicy.review_graph_id)}
              />
            </TaskSystemField>
            <TaskSystemSelectField
              formatOption={taskSystemOptionLabel}
              label="返修策略"
              onChange={(value) => update("runtime", ["batch_acceptance_policy", "repair_policy"], value)}
              options={["repair_until_pass_or_manual_gate"]}
              value={stringValue(acceptancePolicy.repair_policy, "repair_until_pass_or_manual_gate")}
            />
            <TaskSystemField label="返修轮次">
              <input
                min={1}
                onChange={(event) => update("runtime", ["batch_acceptance_policy", "max_repair_rounds"], Number(event.target.value || 1))}
                type="number"
                value={numberValue(acceptancePolicy.max_repair_rounds, 3)}
              />
            </TaskSystemField>
            <TaskSystemSelectField
              formatOption={taskSystemOptionLabel}
              label="提交可见"
              onChange={(value) => update("runtime", ["batch_acceptance_policy", "commit_visibility"], value)}
              options={["next_batch_after_acceptance"]}
              value={stringValue(acceptancePolicy.commit_visibility, "next_batch_after_acceptance")}
            />
          </div>
        </section>

        <section className="task-graph-contract-binding-section">
          <header>
            <div>
              <strong>批次合并</strong>
              <span>决定全部批次提交后，如何形成下一阶段可消费的结果。</span>
            </div>
            <em>runtime.merge_policy</em>
          </header>
          <div className="boundary-form task-graph-composer-inspector-form">
            <TaskSystemSelectField
              formatOption={taskSystemOptionLabel}
              label="合并模式"
              onChange={(value) => update("runtime", ["merge_policy", "mode"], value)}
              options={["wait_all_committed", "manual_merge"]}
              value={stringValue(mergePolicy.mode, "wait_all_committed")}
            />
            <TaskSystemSelectField
              formatOption={taskSystemOptionLabel}
              label="结果排序"
              onChange={(value) => update("runtime", ["merge_policy", "result_order"], value)}
              options={["batch_sequence", "range_start"]}
              value={stringValue(mergePolicy.result_order, "batch_sequence")}
            />
            <label className="boundary-check">
              <input
                checked={booleanValue(mergePolicy.allow_partial)}
                onChange={(event) => update("runtime", ["merge_policy", "allow_partial"], event.target.checked)}
                type="checkbox"
              />
              允许部分合并
            </label>
            <label className="boundary-check">
              <input
                checked={booleanValue(mergePolicy.final_review_required, true)}
                onChange={(event) => update("runtime", ["merge_policy", "final_review_required"], event.target.checked)}
                type="checkbox"
              />
              需要最终审核
            </label>
          </div>
        </section>
      </div>
    </TaskGraphInspectorSection>
  );
}
