"use client";

import { TaskSystemField, TaskSystemSelectField, taskSystemOptionLabel } from "./TaskSystemWorkbenchUi";
import { WORKING_MEMORY_KIND_OPTIONS, WORKING_MEMORY_SCOPE_OPTIONS } from "./WorkingMemoryPolicyEditor";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function edgeTitle(edge: Record<string, unknown>) {
  return String(edge.label ?? edge.title ?? edge.edge_id ?? "交接边");
}

function listText(value: unknown) {
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean).join("\n") : "";
}

function splitList(value: string) {
  return value.split(/[\n,，]/).map((item) => item.trim()).filter(Boolean);
}

export function EdgeHandoffCard({
  selectedGraphEdge,
  selectedGraphEdgeId,
  updateTaskGraphEdge,
}: {
  selectedGraphEdge: Record<string, unknown> | null;
  selectedGraphEdgeId: string;
  updateTaskGraphEdge: (edgeId: string, patch: Record<string, unknown>) => void;
}) {
  if (!selectedGraphEdge || !selectedGraphEdgeId) {
    return (
      <article className="boundary-card">
        <header><strong>边交接</strong></header>
        <div className="task-graph-note">
          <strong>未选择交接边</strong>
          <span>请在拓扑页选择一条边，再回到本页配置交接契约与确认策略。</span>
        </div>
      </article>
    );
  }

  const handoffPolicy = asRecord(selectedGraphEdge.working_memory_handoff_policy);
  const updateHandoffPolicy = (patch: Record<string, unknown>) => {
    updateTaskGraphEdge(selectedGraphEdgeId, {
      working_memory_handoff_policy: {
        ...handoffPolicy,
        ...patch,
      },
    });
  };

  return (
    <article className="boundary-card task-graph-responsibility-card">
      <header>
        <div className="boundary-identity-stack">
          <span>边交接</span>
          <strong>{edgeTitle(selectedGraphEdge)}</strong>
        </div>
        <small>{selectedGraphEdgeId}</small>
      </header>

      <div className="task-graph-responsibility-preview">
        <p><span>等待</span><strong>{taskSystemOptionLabel(String(selectedGraphEdge.wait_policy ?? "wait_all_upstream_completed"))}</strong></p>
        <p><span>确认</span><strong>{selectedGraphEdge.ack_required === false ? "无需确认" : "需要确认"}</strong></p>
        <p><span>记忆</span><strong>{handoffPolicy.summary_only === true ? "摘要/引用" : "按策略携带"}</strong></p>
      </div>

      <div className="boundary-form">
        <TaskSystemField label="交接契约 ID">
          <input
            onChange={(event) => updateTaskGraphEdge(selectedGraphEdgeId, { payload_contract_id: event.target.value, contract_id: event.target.value })}
            value={String(selectedGraphEdge.payload_contract_id ?? selectedGraphEdge.contract_id ?? "")}
          />
        </TaskSystemField>
        <TaskSystemSelectField
          formatOption={taskSystemOptionLabel}
          label="等待策略"
          onChange={(value) => updateTaskGraphEdge(selectedGraphEdgeId, { wait_policy: value })}
          options={["wait_all_upstream_completed", "wait_any_upstream_completed", "wait_required_contracts", "wait_handoff_ack", "fire_and_continue"]}
          value={String(selectedGraphEdge.wait_policy ?? "wait_all_upstream_completed")}
        />
        <TaskSystemSelectField
          formatOption={taskSystemOptionLabel}
          label="失败传播"
          onChange={(value) => updateTaskGraphEdge(selectedGraphEdgeId, { failure_propagation_policy: value })}
          options={["fail_downstream", "isolate_failure", "allow_partial"]}
          value={String(selectedGraphEdge.failure_propagation_policy ?? "fail_downstream")}
        />
        <TaskSystemSelectField
          formatOption={taskSystemOptionLabel}
          label="结果投递"
          onChange={(value) => updateTaskGraphEdge(selectedGraphEdgeId, { result_delivery_policy: value })}
          options={["contract_payload_and_refs", "summary_and_refs", "notification_only"]}
          value={String(selectedGraphEdge.result_delivery_policy ?? "contract_payload_and_refs")}
        />
        <TaskSystemField label="携带记忆 Kind">
          <textarea
            onChange={(event) => updateHandoffPolicy({ carry_kinds: splitList(event.target.value) })}
            placeholder={WORKING_MEMORY_KIND_OPTIONS.slice(0, 3).join("\n")}
            value={listText(handoffPolicy.carry_kinds)}
          />
        </TaskSystemField>
        <TaskSystemField label="携带记忆 Scope">
          <textarea
            onChange={(event) => updateHandoffPolicy({ carry_scopes: splitList(event.target.value) })}
            placeholder={WORKING_MEMORY_SCOPE_OPTIONS.slice(0, 3).join("\n")}
            value={listText(handoffPolicy.carry_scopes)}
          />
        </TaskSystemField>
        <label className="boundary-check">
          <input
            checked={selectedGraphEdge.ack_required !== false}
            onChange={(event) => updateTaskGraphEdge(selectedGraphEdgeId, { ack_required: event.target.checked })}
            type="checkbox"
          />
          需要目标节点确认接收
        </label>
        <label className="boundary-check">
          <input
            checked={handoffPolicy.summary_only === true}
            onChange={(event) => updateHandoffPolicy({ summary_only: event.target.checked })}
            type="checkbox"
          />
          只传摘要或引用，不复制正文
        </label>
      </div>
    </article>
  );
}
