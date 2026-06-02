"use client";

import { ChevronRight, TerminalSquare } from "lucide-react";

import type { ToolCall } from "@/lib/api";

function shortText(value: string, limit = 1200) {
  const normalized = value.trim();
  return normalized.length > limit ? `${normalized.slice(0, limit - 1)}...` : normalized;
}

function compactText(value: string, limit = 180) {
  const normalized = value.replace(/\s+/g, " ").trim();
  return normalized.length > limit ? `${normalized.slice(0, limit - 1)}...` : normalized;
}

function parsedInput(input: string): Record<string, unknown> {
  try {
    const payload = JSON.parse(input);
    return payload && typeof payload === "object" && !Array.isArray(payload) ? payload as Record<string, unknown> : {};
  } catch {
    return {};
  }
}

function firstString(...values: unknown[]) {
  for (const value of values) {
    const text = typeof value === "string" ? value.trim() : "";
    if (text) return text;
  }
  return "";
}

function toolTraceLabel(toolCall: ToolCall) {
  const input = parsedInput(toolCall.input || "");
  const args = input.args && typeof input.args === "object" && !Array.isArray(input.args)
    ? input.args as Record<string, unknown>
    : input;
  const command = firstString(
    args.command,
    args.cmd,
    args.script,
    args.query,
    args.path,
    args.file_path,
    args.pattern,
  );
  if (command) {
    return compactText(command);
  }
  if (toolCall.input.trim() && !toolCall.input.trim().startsWith("{")) {
    return compactText(toolCall.input);
  }
  return compactText(toolCall.tool || "tool");
}

export function RuntimeEvidencePanel({ toolCalls }: { toolCalls: ToolCall[] }) {
  if (!toolCalls.length) {
    return null;
  }
  const latest = toolCalls[toolCalls.length - 1];
  const traceLabel = toolTraceLabel(latest);

  return (
    <details className="runtime-evidence-panel">
      <summary className="runtime-evidence-panel__summary">
        <ChevronRight size={13} className="runtime-evidence-panel__chevron" />
        <TerminalSquare size={13} />
        <span>工具细节</span>
        <code>{traceLabel}</code>
        {toolCalls.length > 1 ? <strong>{toolCalls.length} calls</strong> : null}
      </summary>
      <div className="runtime-evidence-panel__list">
        {toolCalls.map((toolCall, index) => (
          <article className="runtime-evidence-panel__item" key={`${toolCall.tool}-${index}`}>
            <div className="runtime-evidence-panel__tool">
              <TerminalSquare size={12} />
              <strong>{toolCall.tool}</strong>
            </div>
            <div className="runtime-evidence-panel__io-list">
              {toolCall.input ? (
                <section className="runtime-evidence-panel__io">
                  <span className="runtime-evidence-panel__io-label">输入</span>
                  <pre className="mono whitespace-pre-wrap">{shortText(toolCall.input)}</pre>
                </section>
              ) : null}
              {toolCall.output ? (
                <section className="runtime-evidence-panel__io">
                  <span className="runtime-evidence-panel__io-label">输出</span>
                  <pre className="mono whitespace-pre-wrap">{shortText(toolCall.output)}</pre>
                </section>
              ) : null}
            </div>
          </article>
        ))}
      </div>
    </details>
  );
}
