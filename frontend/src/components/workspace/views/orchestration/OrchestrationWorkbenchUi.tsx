"use client";

import { CheckCircle2 } from "lucide-react";
import type { ReactNode } from "react";

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
