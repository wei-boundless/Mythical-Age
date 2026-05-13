"use client";

import { TaskSystemField, TaskSystemSelectField, taskSystemOptionLabel } from "./TaskSystemWorkbenchUi";

export const WORKING_MEMORY_KIND_OPTIONS = [
  "working_fact",
  "draft_artifact",
  "reflection",
  "instruction",
  "temporal_event",
  "conflict",
  "decision",
  "handoff_note",
  "evaluation",
];

export const WORKING_MEMORY_SCOPE_OPTIONS = ["node_scope", "graph_scope", "task_scope", "edge_scope", "artifact_scope"];
export const WORKING_MEMORY_VISIBILITY_OPTIONS = ["private_to_node", "shared_in_graph", "handoff_only", "coordinator_only", "human_review_only"];

function listText(value: unknown): string {
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean).join("\n") : "";
}

function splitList(value: string) {
  return value.split(/[\n,，]/).map((item) => item.trim()).filter(Boolean);
}

export function WorkingMemoryPolicyEditor({
  policy,
  sharedContextPolicy,
  memorySharingPolicy,
  onPolicyChange,
  onSharedContextPolicyChange,
  onMemorySharingPolicyChange,
}: {
  policy: Record<string, unknown>;
  sharedContextPolicy: string;
  memorySharingPolicy: string;
  onPolicyChange: (patch: Record<string, unknown>) => void;
  onSharedContextPolicyChange: (value: string) => void;
  onMemorySharingPolicyChange: (value: string) => void;
}) {
  return (
    <article className="boundary-card">
      <header>
        <strong>上下文与工作记忆</strong>
        <span>图级默认</span>
      </header>
      <div className="task-graph-policy-summary">
        <p><span>默认范围</span><strong>{String(policy.default_scope ?? "graph_scope")}</strong></p>
        <p><span>默认可见性</span><strong>{String(policy.default_visibility ?? "handoff_only")}</strong></p>
        <p><span>动态读取</span><strong>{policy.allow_dynamic_read === true ? "允许" : "关闭"}</strong></p>
      </div>
      <div className="boundary-form">
        <TaskSystemField label="共享上下文策略">
          <input onChange={(event) => onSharedContextPolicyChange(event.target.value)} value={sharedContextPolicy} />
        </TaskSystemField>
        <TaskSystemField label="记忆共享策略">
          <input onChange={(event) => onMemorySharingPolicyChange(event.target.value)} value={memorySharingPolicy} />
        </TaskSystemField>
        <TaskSystemSelectField
          formatOption={taskSystemOptionLabel}
          label="默认范围"
          onChange={(value) => onPolicyChange({ default_scope: value })}
          options={WORKING_MEMORY_SCOPE_OPTIONS}
          value={String(policy.default_scope ?? "graph_scope")}
        />
        <TaskSystemSelectField
          formatOption={taskSystemOptionLabel}
          label="默认可见性"
          onChange={(value) => onPolicyChange({ default_visibility: value })}
          options={WORKING_MEMORY_VISIBILITY_OPTIONS}
          value={String(policy.default_visibility ?? "handoff_only")}
        />
        <TaskSystemField label="可读记忆 Kind">
          <textarea
            onChange={(event) => onPolicyChange({ readable_kinds: splitList(event.target.value) })}
            placeholder={"working_fact\ndecision\nhandoff_note"}
            value={listText(policy.readable_kinds)}
          />
        </TaskSystemField>
        <TaskSystemField label="可写记忆 Kind">
          <textarea
            onChange={(event) => onPolicyChange({ writable_kinds: splitList(event.target.value) })}
            placeholder={"decision\nevaluation\nhandoff_note"}
            value={listText(policy.writable_kinds)}
          />
        </TaskSystemField>
        <label className="boundary-check">
          <input
            checked={policy.allow_dynamic_read === true}
            onChange={(event) => onPolicyChange({ allow_dynamic_read: event.target.checked })}
            type="checkbox"
          />
          允许节点在运行时动态读取工作记忆
        </label>
        <label className="boundary-check">
          <input
            checked={policy.requires_coordinator_review !== false}
            onChange={(event) => onPolicyChange({ requires_coordinator_review: event.target.checked })}
            type="checkbox"
          />
          写回候选需要协调者采纳
        </label>
      </div>
    </article>
  );
}
