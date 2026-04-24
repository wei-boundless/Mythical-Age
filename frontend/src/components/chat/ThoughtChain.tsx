"use client";

import { TerminalSquare } from "lucide-react";

import type { ToolCall } from "@/lib/api";

export function ThoughtChain({ toolCalls }: { toolCalls: ToolCall[] }) {
  if (!toolCalls.length) {
    return null;
  }

  return (
    <details className="mb-4 rounded-[26px] border border-[var(--color-border)] bg-[var(--color-panel-soft)] p-4">
      <summary className="flex cursor-pointer list-none items-center gap-2 text-sm font-medium text-[var(--color-accent)]">
        <TerminalSquare size={16} />
        工具调用 {toolCalls.length} 次
      </summary>
      <div className="mt-3 space-y-3">
        {toolCalls.map((toolCall, index) => (
          <div
            className="rounded-[20px] bg-[var(--color-panel-strong)] p-3"
            key={`${toolCall.tool}-${index}`}
          >
            <div className="mb-2 text-sm font-medium text-[var(--color-text)]">
              {toolCall.tool}
            </div>
            <div className="space-y-2 text-xs">
              {toolCall.input ? (
                <div className="rounded-[18px] bg-[rgba(10,15,19,0.38)] p-3">
                  <div className="mb-1 font-medium text-[var(--color-text-soft)]">Input</div>
                  <pre className="mono whitespace-pre-wrap">{toolCall.input}</pre>
                </div>
              ) : null}
              {toolCall.output ? (
                <div className="rounded-[18px] bg-[rgba(10,15,19,0.38)] p-3">
                  <div className="mb-1 font-medium text-[var(--color-text-soft)]">Output</div>
                  <pre className="mono whitespace-pre-wrap">{toolCall.output}</pre>
                </div>
              ) : null}
            </div>
          </div>
        ))}
      </div>
    </details>
  );
}
