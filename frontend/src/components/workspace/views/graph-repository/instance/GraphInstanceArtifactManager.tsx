"use client";

import { Archive, FileOutput } from "lucide-react";
import type { GraphTaskInstanceArtifacts } from "@/lib/api";

export function GraphInstanceArtifactManager({
  artifacts,
  loading,
}: {
  artifacts: GraphTaskInstanceArtifacts | null;
  loading: boolean;
}) {
  const items = artifacts?.artifacts ?? [];
  return (
    <section className="graph-instance-resource-panel" aria-label="实例产物">
      <header>
        <div>
          <span>产物管理</span>
          <strong>{items.length ? `${items.length} 个产物` : "产物索引"}</strong>
        </div>
        <Archive size={15} />
      </header>
      {items.length ? (
        <div className="graph-instance-artifact-list">
          {items.map((item, index) => {
            const record = asRecord(item);
            const title = text(record.title) || text(record.path) || text(record.artifact_id) || `产物 ${index + 1}`;
            const detail = text(record.summary) || text(record.description) || text(record.path) || "实例运行产物";
            const state = text(record.status) || text(record.kind) || "artifact";
            return (
              <article className="graph-instance-artifact-row" key={`${text(record.artifact_id) || title}.${index}`}>
                <FileOutput size={15} />
                <div>
                  <strong>{title}</strong>
                  <span>{detail}</span>
                </div>
                <em>{state}</em>
              </article>
            );
          })}
        </div>
      ) : (
        <div className="graph-instance-empty">{loading ? "正在读取产物索引..." : "这个实例还没有产物。"}</div>
      )}
    </section>
  );
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function text(value: unknown) {
  return String(value ?? "").trim();
}
