import type { ReactNode } from "react";

import { TaskSystemField } from "./TaskSystemWorkbenchUi";

function uniqueStrings(values: Array<string | null | undefined>) {
  return Array.from(new Set(values.map((item) => String(item ?? "").trim()).filter(Boolean)));
}

export function TaskGraphInspectorSection({
  children,
  icon,
  title,
  aside,
}: {
  children: ReactNode;
  icon?: ReactNode;
  title: string;
  aside?: ReactNode;
}) {
  return (
    <section className="task-graph-composer-inspector-card">
      <header>
        {icon}
        <strong>{title}</strong>
        {aside ? <span>{aside}</span> : null}
      </header>
      {children}
    </section>
  );
}

export function TaskGraphInspectorSummary({
  caption,
  metrics,
  overline,
  title,
}: {
  caption: string;
  metrics?: Array<{ label: string; value: ReactNode }>;
  overline: string;
  title: string;
}) {
  return (
    <>
      <div className="task-graph-composer-selection-title">
        <span>{overline}</span>
        <strong>{title}</strong>
        <small>{caption}</small>
      </div>
      {metrics?.length ? (
        <div className="task-graph-composer-kv">
          {metrics.map((item) => (
            <p key={item.label}><span>{item.label}</span><strong>{item.value}</strong></p>
          ))}
        </div>
      ) : null}
    </>
  );
}

export function TaskGraphObjectSelectField({
  emptyLabel = "未绑定",
  formatOption = (value: string) => value,
  label,
  onChange,
  options,
  value,
  wide = false,
}: {
  emptyLabel?: string;
  formatOption?: (value: string) => string;
  label: string;
  onChange: (value: string) => void;
  options: string[];
  value: string;
  wide?: boolean;
}) {
  const resolvedOptions = uniqueStrings([value, ...options]);
  return (
    <TaskSystemField label={label} wide={wide}>
      <select onChange={(event) => onChange(event.target.value)} value={value}>
        <option value="">{emptyLabel}</option>
        {resolvedOptions.map((item) => (
          <option key={item} value={item}>{formatOption(item)}</option>
        ))}
      </select>
    </TaskSystemField>
  );
}
