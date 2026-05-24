"use client";

import { TerminalSquare } from "lucide-react";

import type { ToolCall } from "@/lib/api";

export function ThoughtChain({ toolCalls }: { toolCalls: ToolCall[] }) {
  if (!toolCalls.length) {
    return null;
  }

  return (
    <details className="archive-detail-card archive-detail-card--thought runtime-tool-detail mb-3">
      <summary className="archive-detail-card__summary runtime-tool-detail__summary">
        <TerminalSquare size={16} />
        工具 I/O 详情 {toolCalls.length} 次
      </summary>
      <div className="runtime-tool-detail__list">
        {toolCalls.map((toolCall, index) => (
          <div
            className="archive-detail-card__item runtime-tool-detail__item"
            key={`${toolCall.tool}-${index}`}
          >
            <div className="runtime-tool-detail__tool">
              {toolCall.tool}
            </div>
            <div className="runtime-tool-detail__io-list">
              {toolCall.input ? (
                <div className="archive-detail-card__io runtime-tool-detail__io">
                  <div className="archive-detail-card__io-label runtime-tool-detail__io-label">输入</div>
                  <pre className="mono whitespace-pre-wrap">{toolCall.input}</pre>
                </div>
              ) : null}
              {toolCall.output ? (
                <div className="archive-detail-card__io runtime-tool-detail__io">
                  <div className="archive-detail-card__io-label runtime-tool-detail__io-label">输出</div>
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
