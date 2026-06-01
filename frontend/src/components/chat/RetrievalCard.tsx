"use client";

import { Database } from "lucide-react";

import type { RetrievalResult } from "@/lib/api";

type RetrievalWithCollection = RetrievalResult & { collection?: string };

export function RetrievalCard({ results }: { results: RetrievalResult[] }) {
  if (!results.length) {
    return null;
  }

  const typedResults = results as RetrievalWithCollection[];
  const collections = Array.from(
    new Set(typedResults.map((item) => item.collection).filter(Boolean))
  );
  const summaryLabel =
    collections.length === 1
      ? `检索到 ${results.length} 条 ${collections[0]} 片段`
      : `检索到 ${results.length} 条 RAG 片段`;

  return (
    <details className="archive-detail-card archive-detail-card--retrieval mb-4 rounded-[26px] p-4">
      <summary className="archive-detail-card__summary flex cursor-pointer list-none items-center gap-2 text-sm font-medium text-[var(--color-accent-primary)]">
        <Database size={16} />
        {summaryLabel}
      </summary>
      <div className="mt-3 space-y-3">
        {typedResults.map((item, index) => (
          <div
            className="archive-detail-card__item rounded-[20px] p-3"
            key={`${item.source}-${index}`}
          >
            <div className="archive-detail-card__meta mb-1 flex items-center justify-between text-xs text-[var(--color-text-soft)]">
              <span>{item.source}</span>
              <span>{item.score.toFixed(3)}</span>
            </div>
            <p className="text-sm leading-6 text-[var(--color-text)]">{item.text}</p>
          </div>
        ))}
      </div>
    </details>
  );
}
