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
