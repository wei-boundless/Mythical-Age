"use client";

import type { ReactNode } from "react";

function uniqueStrings(values: Array<string | null | undefined>) {
  return Array.from(new Set(values.map((item) => String(item ?? "").trim()).filter(Boolean)));
}

export function taskSystemOptionLabel(value: string) {
  const labels: Record<string, string> = {
    coordinator: "协调者",
    participant: "协作节点",
    reviewer: "审查节点",
    writer: "写作节点",
    planner: "规划节点",
    executor: "执行节点",
    verifier: "验证节点",
    summarizer: "整理节点",
    merge: "汇总节点",
    acceptance: "验收节点",
    review_merge: "审查汇总",
    pipeline: "流水推进",
    parallel_review: "并行审查",
    structured_handoff: "结构化交接",
    review_feedback: "审查反馈",
    draft_request: "起草请求",
    audit_request: "审计请求",
    merge_signal: "合并信号",
    explicit_join: "显式汇合",
    coordinator_join: "协调汇合",
    sequential_join: "顺序汇合",
    fail_closed: "失败即关闭",
    retry_once: "失败重试一次",
    coordinator_decides: "协调者裁定",
    coordinator_terminal: "协调者终止",
    all_nodes_complete: "全节点完成",
    manual_close: "手动关闭",
    explicit_ack: "显式确认",
    implicit_ack: "隐式确认",
    escalate_to_coordinator: "升级给协调者",
    raise_to_coordinator: "上报协调者",
    return_to_sender: "退回发送方",
    halt_chain: "中止链路",
    task_goal: "任务目标",
    plan_fragment: "计划片段",
    decision_record: "决策记录",
    intermediate_result: "中间结果",
    review_note: "审查意见",
    conflict_flag: "冲突标记",
    handoff_context: "交接上下文",
    artifact_ref: "产物引用",
    promotion_candidate: "晋升候选",
    chapter_draft: "章节草稿",
    character_state_delta: "人物状态变化",
    world_state_delta: "世界状态变化",
    continuity_conflict: "连续性冲突",
    node_scope: "节点范围",
    graph_scope: "图范围",
    task_scope: "任务范围",
    edge_scope: "边范围",
    artifact_scope: "产物范围",
    private_to_node: "节点私有",
    shared_in_graph: "图内共享",
    handoff_only: "仅交接",
    coordinator_only: "仅协调者",
    human_review_only: "仅人工审查",
    working_fact: "工作事实",
    draft_artifact: "草稿产物",
    reflection: "反思",
    instruction: "指令",
    temporal_event: "时间事件",
    conflict: "冲突",
    decision: "决策",
    handoff_note: "交接说明",
    evaluation: "评估",
  };
  return labels[value] ?? value;
}

export function TaskSystemField({
  label,
  children,
  wide = false,
}: {
  label: string;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <label className={wide ? "boundary-field boundary-field--wide" : "boundary-field"}>
      <span>{label}</span>
      {children}
    </label>
  );
}

export function TaskSystemToolbarButton({
  children,
  onClick,
  disabled,
  variant = "ghost",
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: "ghost" | "primary";
}) {
  return (
    <button className={`boundary-button boundary-button--${variant}`} disabled={disabled} onClick={onClick} type="button">
      {children}
    </button>
  );
}

export function TaskSystemSelectField({
  label,
  value,
  options,
  onChange,
  wide = false,
  formatOption = taskSystemOptionLabel,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
  wide?: boolean;
  formatOption?: (value: string) => string;
}) {
  const resolvedOptions = uniqueStrings([value, ...options]);
  return (
    <TaskSystemField label={label} wide={wide}>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {resolvedOptions.map((item) => (
          <option key={item} value={item}>{formatOption(item)}</option>
        ))}
      </select>
    </TaskSystemField>
  );
}

export function TaskSystemDomainTaskSelectField({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: Array<{ value: string; label: string }>;
  onChange: (value: string) => void;
}) {
  const resolvedOptions = value && !options.some((item) => item.value === value)
    ? [{ value, label: value }, ...options]
    : options;
  return (
    <TaskSystemField label={label}>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">不绑定</option>
        {resolvedOptions.map((item) => (
          <option key={item.value} value={item.value}>{item.label}</option>
        ))}
      </select>
    </TaskSystemField>
  );
}

export function TaskSystemMultiSelectField({
  label,
  value,
  options,
  onChange,
  wide = false,
  formatOption = taskSystemOptionLabel,
}: {
  label: string;
  value: string[];
  options: string[];
  onChange: (value: string[]) => void;
  wide?: boolean;
  formatOption?: (value: string) => string;
}) {
  const selected = new Set(value ?? []);
  return (
    <TaskSystemField label={label} wide={wide}>
      <div className="boundary-choice-grid">
        {uniqueStrings([...options, ...(value ?? [])]).map((item) => (
          <button
            className={selected.has(item) ? "boundary-choice boundary-choice--active" : "boundary-choice"}
            key={item}
            onClick={() => {
              const next = selected.has(item)
                ? (value ?? []).filter((current) => current !== item)
                : [...(value ?? []), item];
              onChange(next);
            }}
            type="button"
          >
            {formatOption(item)}
          </button>
        ))}
      </div>
    </TaskSystemField>
  );
}
