"use client";

import type { CSSProperties } from "react";
import { FileText, FolderTree } from "lucide-react";
import type { GraphTaskInstanceFileTree } from "@/lib/api";

type FileTreeEntry = {
  depth: number;
  kind: "file" | "folder";
  name: string;
  path: string;
};

export function GraphInstanceFileManager({
  fileTree,
  loading,
}: {
  fileTree: GraphTaskInstanceFileTree | null;
  loading: boolean;
}) {
  const entries = flattenTree(fileTree?.tree ?? null).slice(0, 80);
  return (
    <section className="graph-instance-resource-panel" aria-label="实例文件空间">
      <header>
        <div>
          <span>项目文件空间</span>
          <strong>{fileTree?.path || "项目根目录"}</strong>
        </div>
        <em>{loading ? "加载中" : `${fileTree?.total_entries ?? entries.length} 项`}</em>
      </header>
      {entries.length ? (
        <div className="graph-instance-file-list">
          {entries.map((entry) => {
            const Icon = entry.kind === "folder" ? FolderTree : FileText;
            return (
              <button
                className="graph-instance-file-row"
                key={`${entry.path}.${entry.depth}`}
                style={{ "--file-depth": entry.depth } as CSSProperties}
                type="button"
              >
                <Icon size={14} />
                <span>
                  <strong>{entry.name}</strong>
                  <small>{entry.path}</small>
                </span>
              </button>
            );
          })}
        </div>
      ) : (
        <div className="graph-instance-empty">{loading ? "正在读取文件空间..." : "这个项目还没有文件。"}</div>
      )}
      {fileTree?.truncated ? <p className="graph-instance-note">文件较多，当前只显示前 {entries.length} 项。</p> : null}
    </section>
  );
}

function flattenTree(tree: Record<string, unknown> | null, depth = 0, fallbackPath = ""): FileTreeEntry[] {
  if (!tree) return [];
  const children = Array.isArray(tree.children)
    ? tree.children
    : Array.isArray(tree.entries)
      ? tree.entries
      : [];
  const rawName = text(tree.name) || text(tree.path) || "root";
  const path = text(tree.path) || fallbackPath || rawName;
  const kind: FileTreeEntry["kind"] = text(tree.kind) === "file" || text(tree.type) === "file" || !children.length ? "file" : "folder";
  const current = depth === 0 && rawName === "root"
    ? []
    : [{ depth, kind, name: rawName, path }];
  return [
    ...current,
    ...children.flatMap((child) => flattenTree(asRecord(child), depth + 1, path)),
  ];
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function text(value: unknown) {
  return String(value ?? "").trim();
}
