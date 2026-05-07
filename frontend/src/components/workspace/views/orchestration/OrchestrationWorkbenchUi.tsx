"use client";

import { CheckCircle2, X } from "lucide-react";
import type { ReactNode } from "react";

export type OrchestrationOption = {
  id: string;
  value: string;
  label: string;
  description?: string;
};

export function OrchestrationBadge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "ok" | "warn" | "danger";
}) {
  return <span className={`boundary-badge boundary-badge--${tone}`}>{children}</span>;
}

export function OrchestrationToolbarButton({
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
    <button className={`boundary-button boundary-button--${variant}`} disabled={disabled} onClick={onClick} type="button">
      {children}
    </button>
  );
}

export function OrchestrationField({
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

export function OrchestrationReadinessCard({
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

export function OrchestrationSuggestionGrid({
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

export function OrchestrationOptionGrid({
  items,
  onAdd,
}: {
  items: OrchestrationOption[];
  onAdd: (item: OrchestrationOption) => void;
}) {
  if (!items.length) return null;
  return (
    <div className="boundary-chip-grid">
      {items.slice(0, 18).map((item) => (
        <button className="boundary-chip" key={item.value || item.id} onClick={() => onAdd(item)} title={item.description || item.value || item.id} type="button">
          <CheckCircle2 size={13} />
          <span>{item.label || item.value || item.id}</span>
        </button>
      ))}
    </div>
  );
}

export function OrchestrationOptionSelection({
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
  options: OrchestrationOption[];
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
  const labelByValue = new Map(optionItems.map((item) => [item.value || item.id, item.label || item.value || item.id]));

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
      <OrchestrationOptionGrid items={availableItems} onAdd={(item) => add(item.value || item.id)} />
    </div>
  );
}
