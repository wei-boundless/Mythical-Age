"use client";

import Editor from "@monaco-editor/react";
import { Save } from "lucide-react";

import { useAppStore } from "@/lib/store";

function labelFromPath(path: string) {
  const chunks = path.split("/");
  return chunks[chunks.length - 1] || path;
}

export function InspectorPanel() {
  const {
    editableFiles,
    inspectorPath,
    inspectorContent,
    inspectorDirty,
    loadInspectorFile,
    updateInspectorContent,
    saveInspector
  } = useAppStore();

  return (
    <aside className="panel flex h-full flex-col rounded-[34px] p-4">
      <div className="mb-4 flex items-center justify-between gap-3">
        <p className="section-kicker">Inspector</p>
        <button
          className={`action-button ${
            inspectorDirty ? "action-button--primary" : "action-button--muted"
          }`}
          onClick={() => void saveInspector()}
          type="button"
        >
          <Save size={16} />
          {inspectorDirty ? "保存修改" : "已同步"}
        </button>
      </div>

      <div className="mb-4 flex flex-wrap gap-2">
        {editableFiles.map((path) => (
          <button
            className={`rounded-full border px-3 py-2 text-xs transition ${
              path === inspectorPath
                ? "border-[var(--color-soul)] bg-[var(--color-soul-soft)] text-[var(--color-text)]"
                : "border-[var(--color-border)] bg-[var(--color-panel-soft)] text-[var(--color-text-soft)]"
            }`}
            key={path}
            onClick={() => void loadInspectorFile(path)}
            type="button"
          >
            {labelFromPath(path)}
          </button>
        ))}
      </div>

      <div className="overflow-hidden rounded-[28px] border border-[var(--color-border)]">
        <Editor
          defaultLanguage="markdown"
          height="calc(100vh - 210px)"
          onChange={(value) => updateInspectorContent(value ?? "")}
          options={{
            fontFamily: "var(--font-mono)",
            fontSize: 13,
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            wordWrap: "on"
          }}
          path={inspectorPath}
          theme="vs-dark"
          value={inspectorContent}
        />
      </div>
    </aside>
  );
}
