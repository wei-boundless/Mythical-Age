"use client";

import { CoordinationEditorWorkbench } from "@/components/workspace/views/task-system/CoordinationEditorWorkbench";

import { isTaskGraphPublishedState } from "./taskGraphDraftV2";
import type { TaskGraphWorkbenchProps } from "./taskGraphTypes";

export type TaskGraphTopologyPageProps = Pick<
  TaskGraphWorkbenchProps,
  | "activeGraphEdges"
  | "activeGraphNodes"
  | "addTaskGraphEdge"
  | "addTaskGraphNode"
  | "addTaskGraphRoleNode"
  | "addTaskGraphSuccessorNode"
  | "addTaskGraphTaskNode"
  | "applyTaskGraphTemplate"
  | "cycleTaskGraphEdgeMode"
  | "cycleTaskGraphNodeRole"
  | "duplicateTaskGraphDraft"
  | "legacyDrafts"
  | "removeTaskGraphEdge"
  | "removeTaskGraphNode"
  | "reverseTaskGraphEdge"
  | "saveTaskGraphStack"
  | "selectedTaskGraphSpec"
  | "sendTaskGraphToChat"
  | "setCoordinationDraft"
  | "setProtocolDraft"
  | "setTaskGraphPublished"
  | "setTopologyDraft"
  | "taskGraphDirty"
  | "taskGraphDraft"
  | "updateTaskGraphEdge"
  | "updateTaskGraphNode"
> & Omit<
  TaskGraphWorkbenchProps,
  | "activeGraphEdges"
  | "activeGraphNodes"
  | "addTaskGraphEdge"
  | "addTaskGraphNode"
  | "addTaskGraphRoleNode"
  | "addTaskGraphSuccessorNode"
  | "addTaskGraphTaskNode"
  | "applyTaskGraphTemplate"
  | "cycleTaskGraphEdgeMode"
  | "cycleTaskGraphNodeRole"
  | "duplicateTaskGraphDraft"
  | "legacyDrafts"
  | "removeTaskGraphEdge"
  | "removeTaskGraphNode"
  | "reverseTaskGraphEdge"
  | "saveTaskGraphStack"
  | "selectedTaskGraphSpec"
  | "sendTaskGraphToChat"
  | "setCoordinationDraft"
  | "setProtocolDraft"
  | "setTaskGraphPublished"
  | "setTopologyDraft"
  | "taskGraphDirty"
  | "taskGraphDraft"
  | "taskGraphDraftV2"
  | "updateTaskGraphEdge"
  | "updateTaskGraphNode"
>;

export function TaskGraphTopologyPage(props: TaskGraphTopologyPageProps) {
  const {
    activeGraphEdges,
    activeGraphNodes,
    addTaskGraphEdge,
    addTaskGraphNode,
    addTaskGraphRoleNode,
    addTaskGraphSuccessorNode,
    addTaskGraphTaskNode,
    applyTaskGraphTemplate,
    cycleTaskGraphEdgeMode,
    cycleTaskGraphNodeRole,
    duplicateTaskGraphDraft,
    legacyDrafts,
    removeTaskGraphEdge,
    removeTaskGraphNode,
    reverseTaskGraphEdge,
    saveTaskGraphStack,
    selectedTaskGraphSpec,
    sendTaskGraphToChat,
    setCoordinationDraft,
    setProtocolDraft,
    setTaskGraphPublished,
    setTopologyDraft,
    taskGraphDirty,
    taskGraphDraft,
    updateTaskGraphEdge,
    updateTaskGraphNode,
    ...rest
  } = props;
  const published = isTaskGraphPublishedState(taskGraphDraft.publish_state);

  return (
    <CoordinationEditorWorkbench
      {...rest}
      activeGraphNodes={activeGraphNodes}
      activeGraphEdges={activeGraphEdges}
      coordinationDraft={legacyDrafts.coordinationDraft as never}
      topologyDraft={legacyDrafts.topologyDraft}
      protocolDraft={legacyDrafts.protocolDraft}
      setCoordinationDraft={setCoordinationDraft as never}
      setTopologyDraft={setTopologyDraft}
      setProtocolDraft={setProtocolDraft}
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
      editorPublished={published}
      topologyDirty={taskGraphDirty}
      selectedCoordinationId={rest.selectedTaskGraphId}
      setSelectedCoordinationId={rest.setSelectedTaskGraphId}
    />
  );
}
