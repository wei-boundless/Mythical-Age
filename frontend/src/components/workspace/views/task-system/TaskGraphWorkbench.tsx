"use client";

import { CoordinationEditorWorkbench } from "@/components/workspace/views/task-system/CoordinationEditorWorkbench";

import type { TaskGraphWorkbenchProps } from "./taskGraphTypes";

export function TaskGraphWorkbench({
  legacyDrafts,
  taskGraphDraft,
  saveTaskGraphStack,
  duplicateTaskGraphDraft,
  sendTaskGraphToChat,
  applyTaskGraphTemplate,
  addTaskGraphTaskNode,
  addTaskGraphRoleNode,
  addTaskGraphNode,
  addTaskGraphEdge,
  reverseTaskGraphEdge,
  cycleTaskGraphEdgeMode,
  removeTaskGraphEdge,
  addTaskGraphSuccessorNode,
  cycleTaskGraphNodeRole,
  removeTaskGraphNode,
  updateTaskGraphNode,
  updateTaskGraphEdge,
  setTaskGraphPublished,
  selectedTaskGraphSpec,
  activeGraphNodes,
  activeGraphEdges,
  ...rest
}: TaskGraphWorkbenchProps) {
  return (
    <CoordinationEditorWorkbench
      {...rest}
      activeGraphNodes={activeGraphNodes}
      activeGraphEdges={activeGraphEdges}
      coordinationDraft={legacyDrafts.coordinationDraft as never}
      topologyDraft={legacyDrafts.topologyDraft}
      protocolDraft={legacyDrafts.protocolDraft}
      setCoordinationDraft={rest.setCoordinationDraft as never}
      setTopologyDraft={rest.setTopologyDraft}
      setProtocolDraft={rest.setProtocolDraft}
      selectedCoordinationGraphSpec={selectedTaskGraphSpec}
      saveCoordinationStack={saveTaskGraphStack}
      duplicateCoordinationDraft={duplicateTaskGraphDraft}
      sendCoordinationToChat={sendTaskGraphToChat}
      applyCoordinationGraphTemplate={applyTaskGraphTemplate}
      addCoordinationTaskNode={addTaskGraphTaskNode}
      addCoordinationRoleNode={addTaskGraphRoleNode}
      addCoordinationNode={addTaskGraphNode}
      addCoordinationEdge={addTaskGraphEdge}
      reverseCoordinationEdge={reverseTaskGraphEdge}
      cycleCoordinationEdgeMode={cycleTaskGraphEdgeMode}
      removeCoordinationEdge={removeTaskGraphEdge}
      addCoordinationSuccessorNode={addTaskGraphSuccessorNode}
      cycleCoordinationNodeRole={cycleTaskGraphNodeRole}
      removeCoordinationNode={removeTaskGraphNode}
      updateCoordinationNode={updateTaskGraphNode}
      updateCoordinationEdge={updateTaskGraphEdge}
      setCoordinationPublished={setTaskGraphPublished}
      editorPublished={taskGraphDraft.publish_state === "published"}
      topologyDirty={rest.taskGraphDirty}
      selectedCoordinationId={rest.selectedTaskGraphId}
      setSelectedCoordinationId={rest.setSelectedTaskGraphId}
    />
  );
}
