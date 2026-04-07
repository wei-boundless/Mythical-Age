"use client";

import { Database } from "lucide-react";

import type { RetrievalResult } from "@/lib/api";

type RetrievalWithCollection = RetrievalResult & { collection?: string };

export function RetrievalCard({ results }: { results: RetrievalResult[] }) {
  if (!results.length) {
    return null;
  }

  const typedResults = results as RetrievalWithCollection[];
  const collections = Array.from(new Set(typedResults.map((item) => item.collection).filter(Boolean)));
  const summaryLabel =
    collections.length === 1
      ? `检索到 ${results.length} 条 ${collections[0]} 片段`
      : `检索到 ${results.length} 条 RAG 片段`;

  return (
    <details className="mb-4 rounded-3xl border border-[rgba(15,139,141,0.18)] bg-[rgba(15,139,141,0.08)] p-4">
      <summary className="flex cursor-pointer list-none items-center gap-2 text-sm font-medium text-ocean">
        <Database size={16} />
        {summaryLabel}
      </summary>
      <div className="mt-3 space-y-3">
        {typedResults.map((item, index) => (
          <div className="rounded-2xl bg-white/70 p-3" key={`${item.source}-${index}`}>
            <div className="mb-1 flex items-center justify-between text-xs text-[var(--color-ink-soft)]">
              <span>{item.source}</span>
              <span>{item.score.toFixed(3)}</span>
            </div>
            <p className="text-sm leading-6 text-[var(--color-ink)]">{item.text}</p>
          </div>
        ))}
      </div>
    </details>
  );
}
