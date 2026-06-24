"use client";

import { useMemo, useState } from "react";

import type { TaskGraphDraftV2 } from "../../task-system/taskGraphDraftV2";
import { draftEditorLayout, type GraphEditorLayout } from "../templates/graphTemplateTypes";

export function useTaskGraphCanvasState(draft: TaskGraphDraftV2) {
  const initialLayout = useMemo(() => draftEditorLayout(draft), [draft]);
  const [layout, setLayout] = useState<GraphEditorLayout>(initialLayout);

  return {
    layout,
    resetLayout: () => setLayout(initialLayout),
    setLayout,
  };
}
