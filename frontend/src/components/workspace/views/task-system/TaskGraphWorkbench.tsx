"use client";

import { useState } from "react";

import { TaskGraphAgentRosterPage } from "@/components/workspace/views/task-system/TaskGraphAgentRosterPage";
import { TaskGraphBlueprintPage } from "@/components/workspace/views/task-system/TaskGraphBlueprintPage";
import { TaskGraphContractQualityPage } from "@/components/workspace/views/task-system/TaskGraphContractQualityPage";
import { TaskGraphMemoryArtifactPage } from "@/components/workspace/views/task-system/TaskGraphMemoryArtifactPage";
import { TaskGraphPublishRunPage } from "@/components/workspace/views/task-system/TaskGraphPublishRunPage";
import { TaskGraphResponsibilityPage } from "@/components/workspace/views/task-system/TaskGraphResponsibilityPage";
import { TaskGraphSetupWizard } from "@/components/workspace/views/task-system/TaskGraphSetupWizard";
import { TaskGraphTimelinePage } from "@/components/workspace/views/task-system/TaskGraphTimelinePage";
import { TaskGraphTopologyPage } from "@/components/workspace/views/task-system/TaskGraphTopologyPage";

import type { TaskGraphStudioLayerId } from "./TaskGraphLayerNav";
import { TaskGraphStudioShell } from "./TaskGraphStudioShell";
import { asRecord, isTaskGraphPublishedState, type TaskGraphPublishStateV2 } from "./taskGraphDraftV2";
import type { TaskGraphPreflightIssue } from "./taskGraphPreflight";
import type { TaskGraphWorkbenchProps } from "./taskGraphTypes";

export function TaskGraphWorkbench({
  taskGraphDraftV2,
  saveTaskGraphStack,
  sendTaskGraphToChat,
  applyTaskGraphTemplate,
  addTaskGraphTaskNode,
  addTaskGraphRoleNode,
  addTaskGraphNode,
  reverseTaskGraphEdge,
  removeTaskGraphEdge,
  addTaskGraphSuccessorNode,
  removeTaskGraphNode,
  updateTaskGraphContextPolicy,
  updateTaskGraphDraft,
  updateTaskGraphNode,
  updateTaskGraphEdge,
  updateTaskGraphMetadata,
  updateTaskGraphPublishState,
  updateTaskGraphRuntimePolicy,
  updateTaskGraphWorkingMemoryPolicy,
  activeGraphNodes,
  activeGraphEdges,
  ...rest
}: TaskGraphWorkbenchProps) {
  const [activeLayer, setActiveLayer] = useState<TaskGraphStudioLayerId>("blueprint");
  const coordinatorAgentId = String(taskGraphDraftV2.runtime_policy.coordinator_agent_id || "agent:0");
  const issueCount = rest.editorIssueCount;
  const valid = rest.editorValid;
  const publishState = taskGraphDraftV2.publish_state;
  const published = isTaskGraphPublishedState(publishState);
  const updateEditorPublishState = (nextState: TaskGraphPublishStateV2) => {
    updateTaskGraphPublishState(nextState);
  };
  const handleSaveDraft = () => {
    const nextState: TaskGraphPublishStateV2 = published ? publishState : "saved";
    updateEditorPublishState(nextState);
    void saveTaskGraphStack(undefined, nextState);
  };
  const handlePublish = () => {
    const nextState: TaskGraphPublishStateV2 = publishState === "run_bound" ? "run_bound" : "published";
    updateEditorPublishState(nextState);
    void saveTaskGraphStack(true, nextState);
  };
  const updateTaskGraph = (patch: Partial<typeof taskGraphDraftV2>) => {
    updateTaskGraphDraft(patch);
  };
  const updateRuntimePolicy = (patch: Partial<typeof taskGraphDraftV2.runtime_policy>) => {
    updateTaskGraphRuntimePolicy(patch);
  };
  const updateContextPolicy = (patch: Partial<typeof taskGraphDraftV2.context_policy>) => {
    updateTaskGraphContextPolicy(patch);
  };
  const updateWorkingMemoryPolicy = (patch: Partial<typeof taskGraphDraftV2.working_memory_policy>) => {
    updateTaskGraphWorkingMemoryPolicy(patch);
  };
  const repairPreflightIssue = (issue: TaskGraphPreflightIssue) => {
    if (
      (issue.source === "frontend.preflight.prompt_semantics" || issue.source === "frontend.preflight.projection_binding")
      && issue.scope === "node"
      && issue.target_id
    ) {
      rest.setSelectedGraphNodeId(issue.target_id);
      rest.setSelectedGraphEdgeId("");
      setActiveLayer("responsibility");
      return;
    }
    if (issue.source === "frontend.preflight.contract" && issue.scope === "edge" && issue.target_id) {
      updateTaskGraphEdge(issue.target_id, { payload_contract_id: `${issue.target_id}.payload`, contract_id: `${issue.target_id}.payload` });
      return;
    }
    if (issue.source === "frontend.preflight.memory_handoff" && issue.scope === "edge" && issue.target_id) {
      updateTaskGraphEdge(issue.target_id, {
        working_memory_handoff_policy: {
          carry_kinds: ["handoff_note", "decision"],
          carry_scopes: ["edge_scope", "artifact_scope"],
          summary_only: true,
          allow_artifact_refs: true,
        },
      });
      return;
    }
    if (issue.source === "frontend.preflight.timeline" && issue.scope === "phase" && issue.target_id) {
      const metadata = asRecord(taskGraphDraftV2.metadata);
      const phaseDefinitions = Array.isArray(metadata.phase_definitions) ? metadata.phase_definitions as Array<Record<string, unknown>> : [];
      const exists = phaseDefinitions.some((phase) => String(phase.phase_id ?? "") === issue.target_id);
      updateTaskGraphMetadata({
        phase_definitions: exists
          ? phaseDefinitions
          : [...phaseDefinitions, { phase_id: issue.target_id, title: issue.target_id.replace(/^phase\./, ""), exit_policy: { kind: "all_blocking_nodes_complete" } }],
      });
    }
  };
  const pageContent = (() => {
    if (activeLayer === "topology") {
      return (
        <TaskGraphTopologyPage
          activeGraphEdges={activeGraphEdges}
          activeGraphNodes={activeGraphNodes}
          addTaskGraphNode={addTaskGraphNode}
          addTaskGraphRoleNode={addTaskGraphRoleNode}
          addTaskGraphSuccessorNode={addTaskGraphSuccessorNode}
          addTaskGraphTaskNode={addTaskGraphTaskNode}
          handleTopologyNodeClick={rest.handleTopologyNodeClick}
          linkingFromNodeId={rest.linkingFromNodeId}
          removeTaskGraphEdge={removeTaskGraphEdge}
          removeTaskGraphNode={removeTaskGraphNode}
          reverseTaskGraphEdge={reverseTaskGraphEdge}
          selectedDomainTasks={rest.selectedDomainTasks}
          selectedGraphEdge={rest.selectedGraphEdge}
          selectedGraphEdgeId={rest.selectedGraphEdgeId}
          selectedGraphNode={rest.selectedGraphNode}
          selectedGraphNodeId={rest.selectedGraphNodeId}
          setLinkingFromNodeId={rest.setLinkingFromNodeId}
          setSelectedGraphEdgeId={rest.setSelectedGraphEdgeId}
          setSelectedGraphNodeId={rest.setSelectedGraphNodeId}
          taskGraphDraftV2={taskGraphDraftV2}
        />
      );
    }
    if (activeLayer === "blueprint") {
      if (!activeGraphNodes.length) {
        return (
          <TaskGraphSetupWizard
            domainTitle={rest.selectedDomain?.title || "当前任务域"}
            taskCount={rest.selectedDomainTasks.length}
            onApplyTemplate={(templateId, options) => {
              applyTaskGraphTemplate(templateId, options);
              setActiveLayer("topology");
            }}
          />
        );
      }
      return (
        <TaskGraphBlueprintPage
          activeGraphNodes={activeGraphNodes}
          taskGraphDraft={taskGraphDraftV2}
          updateContextPolicy={updateContextPolicy}
          updateRuntimePolicy={updateRuntimePolicy}
          updateTaskGraph={updateTaskGraph}
        />
      );
    }
    if (activeLayer === "agents") {
      return (
        <TaskGraphAgentRosterPage
          a2aCatalog={rest.a2aCatalog}
          activeGraphNodes={activeGraphNodes}
          orchestrationAgentCatalog={rest.orchestrationAgentCatalog}
          taskGraphDraft={taskGraphDraftV2}
          updateRuntimePolicy={updateRuntimePolicy}
          updateTaskGraphNode={updateTaskGraphNode}
        />
      );
    }
    if (activeLayer === "responsibility") {
      return (
        <TaskGraphResponsibilityPage
          onCreateProjectionFromPrompt={rest.onCreateProjectionFromPrompt}
          projectionCards={rest.projectionCards}
          selectedGraphEdge={rest.selectedGraphEdge ?? activeGraphEdges[0] ?? null}
          selectedGraphEdgeId={rest.selectedGraphEdgeId || String(activeGraphEdges[0]?.edge_id ?? activeGraphEdges[0]?.id ?? "")}
          selectedGraphNode={rest.selectedGraphNode}
          selectedGraphNodeId={rest.selectedGraphNodeId}
          updateTaskGraphEdge={updateTaskGraphEdge}
          updateTaskGraphNode={updateTaskGraphNode}
        />
      );
    }
    if (activeLayer === "timeline") {
      return (
        <TaskGraphTimelinePage
          activeGraphEdges={activeGraphEdges}
          activeGraphNodes={activeGraphNodes}
          taskGraphDraft={taskGraphDraftV2}
          updateTaskGraphMetadata={updateTaskGraphMetadata}
          updateTaskGraphNode={updateTaskGraphNode}
        />
      );
    }
    if (activeLayer === "memory") {
      return (
        <TaskGraphMemoryArtifactPage
          activeGraphEdges={activeGraphEdges}
          activeGraphNodes={activeGraphNodes}
          taskGraphDraft={taskGraphDraftV2}
          updateContextPolicy={updateContextPolicy}
          updateTaskGraphMetadata={updateTaskGraphMetadata}
          updateTaskGraphEdge={updateTaskGraphEdge}
          updateTaskGraphNode={updateTaskGraphNode}
          updateWorkingMemoryPolicy={updateWorkingMemoryPolicy}
        />
      );
    }
    if (activeLayer === "contracts") {
      return (
        <TaskGraphContractQualityPage
          activeGraphEdges={activeGraphEdges}
          activeGraphNodes={activeGraphNodes}
          contractSpecs={rest.contractSpecs}
          editorIssueCount={rest.editorIssueCount}
          editorValid={rest.editorValid}
          taskGraphDraft={taskGraphDraftV2}
          updateTaskGraph={updateTaskGraph}
          updateTaskGraphEdge={updateTaskGraphEdge}
          updateTaskGraphNode={updateTaskGraphNode}
        />
      );
    }
    if (activeLayer === "publish") {
      return (
        <TaskGraphPublishRunPage
          dirty={rest.taskGraphDirty}
          edges={activeGraphEdges}
          editorIssueCount={rest.editorIssueCount}
          editorValid={rest.editorValid}
          graphId={taskGraphDraftV2.graph_id}
          metadata={taskGraphDraftV2.metadata}
          nodes={activeGraphNodes}
          onPublish={handlePublish}
          onRunBound={() => updateEditorPublishState("run_bound")}
          onSave={handleSaveDraft}
          onSendToChat={() => sendTaskGraphToChat(rest.selectedTaskGraph, rest.selectedDomain)}
          onFocusIssue={(issue) => {
            if (issue.scope === "node" && issue.target_id) {
              rest.setSelectedGraphNodeId(issue.target_id);
              rest.setSelectedGraphEdgeId("");
              setActiveLayer(issue.source.includes("agent") ? "agents" : "responsibility");
              return;
            }
            if (issue.scope === "edge" && issue.target_id) {
              rest.setSelectedGraphEdgeId(issue.target_id);
              rest.setSelectedGraphNodeId("");
              setActiveLayer("responsibility");
              return;
            }
            if (issue.scope === "phase") {
              setActiveLayer("timeline");
              return;
            }
            if (issue.scope === "graph") {
              setActiveLayer(issue.source.includes("contract") ? "contracts" : "blueprint");
              return;
            }
            setActiveLayer("publish");
          }}
          onRepairIssue={repairPreflightIssue}
          publishState={publishState}
          saving={rest.saving}
        />
      );
    }
    return null;
  })();

  return (
    <TaskGraphStudioShell
      activeLayer={activeLayer}
      coordinatorAgentId={coordinatorAgentId}
      dirty={rest.taskGraphDirty}
      edgeCount={activeGraphEdges.length}
      graphId={taskGraphDraftV2.graph_id}
      issueCount={issueCount}
      nodeCount={activeGraphNodes.length}
      onLayerChange={setActiveLayer}
      onPublish={handlePublish}
      onSave={handleSaveDraft}
      onSendToChat={() => sendTaskGraphToChat(rest.selectedTaskGraph, rest.selectedDomain)}
      publishState={publishState}
      saving={rest.saving}
      title={taskGraphDraftV2.title}
      valid={valid}
    >
      {pageContent}
    </TaskGraphStudioShell>
  );
}
