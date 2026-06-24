"use client";

import type { ReactNode } from "react";
import type { OrchestrationAgentRuntimeCatalog } from "@/lib/api";

import type { TaskGraphDraftV2 } from "../../task-system/taskGraphDraftV2";
import { GraphCanvasEditorPage } from "../editor/GraphCanvasEditorPage";

export function GraphEditorContext({
  agentCatalog,
  dirty,
  draft,
  graphRunId,
  instanceId,
  notice,
  onCreateInstance,
  onDraftChange,
  onDuplicate,
  onPublish,
  onSave,
  onSaveTemplate,
  saving,
  worldMode = "edit",
  worldPanel = null,
}: {
  agentCatalog: OrchestrationAgentRuntimeCatalog | null;
  dirty: boolean;
  draft: TaskGraphDraftV2;
  graphRunId?: string;
  instanceId?: string;
  notice: string;
  saving: string;
  onCreateInstance: () => void;
  onDraftChange: (draft: TaskGraphDraftV2) => void;
  onDuplicate: () => void;
  onPublish: () => void;
  onSave: () => void;
  onSaveTemplate: () => void;
  worldMode?: "edit" | "monitor";
  worldPanel?: ReactNode;
}) {
  return (
    <section className="graph-os-editor-context" aria-label="图编辑器上下文">
      <GraphCanvasEditorPage
        agentCatalog={agentCatalog}
        dirty={dirty}
        draft={draft}
        graphRunId={graphRunId}
        instanceId={instanceId}
        notice={notice}
        onCreateInstance={onCreateInstance}
        onDraftChange={onDraftChange}
        onDuplicate={onDuplicate}
        onPublish={onPublish}
        onSave={onSave}
        onSaveTemplate={onSaveTemplate}
        saving={saving}
        worldMode={worldMode}
        worldPanel={worldPanel}
      />
    </section>
  );
}
