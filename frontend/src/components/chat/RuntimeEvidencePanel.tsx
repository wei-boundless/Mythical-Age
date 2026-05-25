"use client";

import { ChevronRight, TerminalSquare } from "lucide-react";

import type { ToolCall } from "@/lib/api";

function shortText(value: string, limit = 1200) {
  const normalized = value.trim();
  return normalized.length > limit ? `${normalized.slice(0, limit - 1)}...` : normalized;
}

export function RuntimeEvidencePanel({ toolCalls }: { toolCalls: ToolCall[] }) {
  if (!toolCalls.length) {
    return null;
  }

  return (
    <details className="runtime-evidence-panel">
      <summary className="runtime-evidence-panel__summary">
        <ChevronRight size={13} className="runtime-evidence-panel__chevron" />
        <TerminalSquare size={13} />
        <span>执行证据</span>
        <strong>{toolCalls.length} 次工具调用</strong>
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
