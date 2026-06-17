"use client";

import { type ReactNode, useEffect, useState } from "react";

import { TaskSystemField } from "@/components/workspace/views/task-system/TaskSystemWorkbenchUi";
import { MetricCard } from "@/ui/MetricCard";

export function toJson(value: unknown) {
  return JSON.stringify(value ?? {}, null, 2);
}

export function parseJsonObject(value: string, label: string) {
  const text = String(value ?? "").trim();
  const parsed = text ? JSON.parse(text) : {};
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${label} 必须是 JSON 对象`);
  }
  return parsed as Record<string, unknown>;
}

export function splitList(value: string) {
  return value.split(/[\n,，]/).map((item) => item.trim()).filter(Boolean);
}

export function dictOf(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

export function recordFieldText(record: Record<string, unknown> | null | undefined, keys: string[], fallback = "-") {
  for (const key of keys) {
    const value = record?.[key];
    if (value !== null && value !== undefined && String(value).trim()) return String(value);
  }
  return fallback;
}

export function JsonObjectEditor({
  label,
  onChange,
  rows = 6,
  value,
}: {
  label: string;
  onChange: (value: Record<string, unknown>) => void;
  rows?: number;
  value: Record<string, unknown>;
}) {
  const [text, setText] = useState(toJson(value));
  const [error, setError] = useState("");

  useEffect(() => {
    setText(toJson(value));
    setError("");
  }, [value]);

  function update(nextText: string) {
    setText(nextText);
    try {
      onChange(parseJsonObject(nextText, label));
      setError("");
    } catch {
      setError(`${label} 不是合法 JSON，对象暂未写入草稿。`);
    }
  }

  return (
    <TaskSystemField label={label} wide>
      <div className={error ? "task-system-json-editor task-system-json-editor--invalid" : "task-system-json-editor"}>
        <textarea rows={rows} value={text} onChange={(event) => update(event.target.value)} spellCheck={false} />
        {error ? <small>{error}</small> : null}
      </div>
    </TaskSystemField>
  );
}

export function Metric({
  detail,
  label,
  tone = "neutral",
  value,
}: {
  detail?: ReactNode;
  label: string;
  tone?: "neutral" | "warn" | "ok";
  value: ReactNode;
}) {
  return (
    <MetricCard className="task-system-metric" detail={detail} label={label} toneClassName={`task-system-metric--${tone}`} value={value} />
  );
}
