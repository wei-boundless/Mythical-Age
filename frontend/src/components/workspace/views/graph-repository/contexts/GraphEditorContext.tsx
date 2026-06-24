"use client";

import type { OrchestrationAgentRuntimeCatalog } from "@/lib/api";

import type { TaskGraphDraftV2 } from "../../task-system/taskGraphDraftV2";
import { GraphCanvasEditorPage } from "../editor/GraphCanvasEditorPage";

export function GraphEditorContext({
  agentCatalog,
  dirty,
  draft,
  notice,
  onCreateInstance,
  onDraftChange,
  onDuplicate,
  onPublish,
  onSave,
  onSaveTemplate,
  saving,
}: {
  agentCatalog: OrchestrationAgentRuntimeCatalog | null;
  dirty: boolean;
  draft: TaskGraphDraftV2;
  notice: string;
  saving: string;
  onCreateInstance: () => void;
  onDraftChange: (draft: TaskGraphDraftV2) => void;
  onDuplicate: () => void;
  onPublish: () => void;
  onSave: () => void;
  onSaveTemplate: () => void;
}) {
  return (
    <section className="graph-os-editor-context" aria-label="图编辑器上下文">
      <GraphCanvasEditorPage
        agentCatalog={agentCatalog}
        dirty={dirty}
        draft={draft}
        notice={notice}
        onCreateInstance={onCreateInstance}
        onDraftChange={onDraftChange}
        onDuplicate={onDuplicate}
        onPublish={onPublish}
        onSave={onSave}
        onSaveTemplate={onSaveTemplate}
        saving={saving}
      />
    </section>
  );
}
