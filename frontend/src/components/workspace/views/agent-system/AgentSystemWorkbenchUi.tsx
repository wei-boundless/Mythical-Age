"use client";

import { CheckCircle2, X } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/ui/Button";
import { Field } from "@/ui/Field";
import { StatusBadge } from "@/ui/StatusBadge";
import { taskSystemDisplayLabel } from "@/components/workspace/views/task-system/TaskSystemWorkbenchUi";

export type AgentSystemOption = {
  id: string;
  value: string;
  label: string;
  description?: string;
  category?: string;
  requestable?: boolean;
  system_only?: boolean;
  deprecated?: boolean;
  replacement_lane_id?: string;
  metadata?: Record<string, unknown>;
};

export function AgentSystemBadge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "ok" | "warn" | "danger";
}) {
  return <StatusBadge tone={tone}>{children}</StatusBadge>;
}

export function AgentSystemToolbarButton({
  children,
  disabled,
  onClick,
  variant = "ghost",
}: {
  children: ReactNode;
  disabled?: boolean;
  onClick?: () => void;
  variant?: "ghost" | "primary" | "danger";
}) {
  return (
    <Button chrome="boundary" disabled={disabled} onClick={onClick} variant={variant}>
      {children}
    </Button>
  );
}

export function AgentSystemField({
  label,
  children,
  wide = false,
}: {
  label: string;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <Field label={label} wide={wide}>
      {children}
    </Field>
  );
}

export function AgentSystemReadinessCard({
  label,
  value,
  ready,
}: {
  label: string;
  value: string;
  ready: boolean;
}) {
  return (
    <article className={ready ? "boundary-readiness boundary-readiness--ready" : "boundary-readiness"}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{ready ? "已配置" : "待配置"}</small>
    </article>
  );
}

export function AgentSystemSuggestionGrid({
  items,
  onAdd,
  renderLabel,
}: {
  items: string[];
  onAdd: (item: string) => void;
  renderLabel?: (item: string) => string;
}) {
  if (!items.length) return null;
  return (
    <div className="boundary-chip-grid">
      {items.slice(0, 18).map((item) => (
        <button className="boundary-chip" key={item} onClick={() => onAdd(item)} type="button">
          <CheckCircle2 size={13} />
          <span>{renderLabel ? renderLabel(item) : item}</span>
        </button>
      ))}
    </div>
  );
}

export function AgentSystemOptionGrid({
  items,
  onAdd,
}: {
  items: AgentSystemOption[];
  onAdd: (item: AgentSystemOption) => void;
}) {
  if (!items.length) return null;
  return (
    <div className="boundary-chip-grid">
      {items.slice(0, 18).map((item) => (
        <button className="boundary-chip" key={item.value || item.id} onClick={() => onAdd(item)} title={item.description || item.value || item.id} type="button">
          <CheckCircle2 size={13} />
          <span>{item.category ? `${item.category} · ` : ""}{item.label || taskSystemDisplayLabel(item.value || item.id)}</span>
        </button>
      ))}
    </div>
  );
}

export function AgentSystemOptionSelection({
  label,
  selectedValues,
  options,
  fallbackOptions = [],
  onChange,
  displayId,
  emptyText = "未选择",
}: {
  label: string;
  selectedValues: string[];
  options: AgentSystemOption[];
  fallbackOptions?: string[];
  onChange: (values: string[]) => void;
  displayId: (value: unknown, fallback?: string) => string;
  emptyText?: string;
}) {
  const selected = Array.from(new Set(selectedValues.map((item) => String(item || "").trim()).filter(Boolean)));
  const optionItems = options.length
    ? options
    : fallbackOptions.map((item) => ({ id: item, value: item, label: displayId(item) }));
  const selectedSet = new Set(selected);
  const availableItems = optionItems.filter((item) => !selectedSet.has(item.value || item.id));
  const labelByValue = new Map(optionItems.map((item) => [item.value || item.id, item.label || taskSystemDisplayLabel(item.value || item.id)]));

  function add(value: string) {
    if (!value) return;
    onChange(Array.from(new Set([...selected, value])));
  }

  function remove(value: string) {
    onChange(selected.filter((item) => item !== value));
  }

  return (
    <div className="boundary-option-selection">
      <div className="boundary-option-selection__head">
        <span>{label}</span>
        <small>{selected.length} 项</small>
      </div>
      <div className="boundary-selected-token-list">
        {selected.length ? selected.map((value) => (
          <button className="boundary-selected-token" key={value} onClick={() => remove(value)} title={`移除 ${labelByValue.get(value) || displayId(value)}`} type="button">
            <span>{labelByValue.get(value) || displayId(value)}</span>
            <X size={13} />
          </button>
        )) : <span className="boundary-selected-token-list__empty">{emptyText}</span>}
      </div>
      <AgentSystemOptionGrid items={availableItems} onAdd={(item) => add(item.value || item.id)} />
    </div>
  );
}


