"use client";

import { Archive, FileOutput } from "lucide-react";
import type { GraphTaskInstanceArtifacts } from "@/lib/api";

import {
  categoryForArtifact,
  resolveArtifactWorkspaceProfile,
  type ArtifactWorkspaceCategory,
} from "../registry/taskGraphArtifactWorkspaceRegistry";

export function GraphInstanceArtifactManager({
  artifacts,
  loading,
  profileInput,
}: {
  artifacts: GraphTaskInstanceArtifacts | null;
  loading: boolean;
  profileInput?: {
    graphId?: string;
    metadata?: Record<string, unknown>;
    title?: string;
  };
}) {
  const items = artifacts?.artifacts ?? [];
  const profile = resolveArtifactWorkspaceProfile(profileInput ?? {});
  const groupedItems = groupArtifactsByCategory(items, profile.categories);
  return (
    <section className="graph-instance-resource-panel graph-instance-artifact-workspace" aria-label="任务环境产物工作区">
      <header>
        <div>
          <span>{profile.title}</span>
          <strong>{items.length ? `${items.length} 个产物` : "产物索引"}</strong>
          <small>{profile.subtitle}</small>
        </div>
        <Archive size={15} />
      </header>
      {items.length ? (
        <div className="graph-instance-artifact-categories">
          {groupedItems.map(({ category, categoryItems }) => (
            <section className="graph-instance-artifact-category" key={category.category_id}>
              <header>
                <div>
                  <strong>{category.title}</strong>
                  <span>{category.detail}</span>
                </div>
                <em>{categoryItems.length}</em>
              </header>
              {categoryItems.length ? (
                <div className="graph-instance-artifact-list">
                  {categoryItems.map((item, index) => {
                    const record = asRecord(item);
                    const title = text(record.title) || text(record.path) || text(record.artifact_id) || `${category.title} ${index + 1}`;
                    const detail = text(record.summary) || text(record.description) || text(record.path) || "项目运行产物";
                    const state = text(record.status) || text(record.kind) || category.category_id;
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
                <div className="graph-instance-empty graph-instance-empty--compact">暂无{category.title}。</div>
              )}
            </section>
          ))}
        </div>
      ) : (
        <div className="graph-instance-artifact-categories">
          {profile.categories.map((category) => (
            <section className="graph-instance-artifact-category" key={category.category_id}>
              <header>
                <div>
                  <strong>{category.title}</strong>
                  <span>{category.detail}</span>
                </div>
                <em>0</em>
              </header>
              <div className="graph-instance-empty graph-instance-empty--compact">
                {loading ? "正在读取产物索引..." : `暂无${category.title}。`}
              </div>
            </section>
          ))}
        </div>
      )}
    </section>
  );
}

function groupArtifactsByCategory(
  items: Array<Record<string, unknown>>,
  categories: ArtifactWorkspaceCategory[],
) {
  const byCategory = new Map(categories.map((category) => [category.category_id, [] as Array<Record<string, unknown>>]));
  const profile = {
    kind: "general" as const,
    title: "",
    subtitle: "",
    categories,
  };
  for (const item of items) {
    const category = categoryForArtifact(asRecord(item), profile);
    const bucket = byCategory.get(category.category_id) ?? [];
    bucket.push(item);
    byCategory.set(category.category_id, bucket);
  }
  return categories.map((category) => ({
    category,
    categoryItems: byCategory.get(category.category_id) ?? [],
  }));
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function text(value: unknown) {
  return String(value ?? "").trim();
}
