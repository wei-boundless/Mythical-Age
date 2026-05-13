"use client";

import { TaskSystemField, TaskSystemSelectField, taskSystemOptionLabel } from "./TaskSystemWorkbenchUi";

export function ArtifactPolicyEditor({
  policy,
  onPolicyChange,
}: {
  policy: Record<string, unknown>;
  onPolicyChange: (patch: Record<string, unknown>) => void;
}) {
  return (
    <article className="boundary-card">
      <header>
        <strong>图级产物策略</strong>
        <span>{policy.enabled === true ? "已启用" : "未启用"}</span>
      </header>
      <div className="task-graph-policy-summary">
        <p><span>根目录</span><strong>{String(policy.artifact_root ?? "未配置")}</strong></p>
        <p><span>物化器</span><strong>{String(policy.materializer ?? "markdown_section_split")}</strong></p>
        <p><span>晋升</span><strong>{String(policy.promotion_policy ?? "manual_review")}</strong></p>
      </div>
      <div className="boundary-form">
        <TaskSystemField label="产物根目录">
          <input
            onChange={(event) => onPolicyChange({ artifact_root: event.target.value })}
            placeholder="output/task-graphs/{graph_id}"
            value={String(policy.artifact_root ?? "")}
          />
        </TaskSystemField>
        <TaskSystemField label="子目录模板">
          <input
            onChange={(event) => onPolicyChange({ subdir_template: event.target.value })}
            placeholder="{task_slug}/{run_slug}"
            value={String(policy.subdir_template ?? "{task_slug}/{run_slug}")}
          />
        </TaskSystemField>
        <TaskSystemSelectField
          formatOption={taskSystemOptionLabel}
          label="物化器"
          onChange={(value) => onPolicyChange({ materializer: value })}
          options={["markdown_section_split", "json_artifact_bundle", "table_dataset_export", "file_reference_only"]}
          value={String(policy.materializer ?? "markdown_section_split")}
        />
        <TaskSystemSelectField
          formatOption={taskSystemOptionLabel}
          label="晋升规则"
          onChange={(value) => onPolicyChange({ promotion_policy: value })}
          options={["manual_review", "review_gate_passed", "coordinator_approved", "never_auto_promote"]}
          value={String(policy.promotion_policy ?? "manual_review")}
        />
        <label className="boundary-check">
          <input
            checked={policy.enabled === true}
            onChange={(event) => onPolicyChange({ enabled: event.target.checked })}
            type="checkbox"
          />
          启用图级产物落盘
        </label>
        <label className="boundary-check">
          <input
            checked={policy.require_artifact_manifest === true}
            onChange={(event) => onPolicyChange({ require_artifact_manifest: event.target.checked })}
            type="checkbox"
          />
          要求运行结束生成产物清单
        </label>
      </div>
    </article>
  );
}
