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
  legacyDrafts,
  taskGraphDraft,
  taskGraphDraftV2,
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
  setCoordinationDraft,
  setTopologyDraft,
  setProtocolDraft,
  selectedTaskGraphSpec,
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
    setCoordinationDraft((current) => ({
      ...current,
      metadata: {
        ...asRecord(current.metadata),
        editor_publish_state: nextState,
      },
    }));
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
    setCoordinationDraft((current) => {
      const metadata = asRecord(current.metadata);
      return {
        ...current,
        title: patch.title ?? current.title,
        graph_kind: patch.graph_kind ?? current.graph_kind,
        metadata: {
          ...metadata,
          entry_node_id: patch.entry_node_id ?? metadata.entry_node_id,
          output_node_id: patch.output_node_id ?? metadata.output_node_id,
          graph_contract_id: patch.graph_contract_id ?? metadata.graph_contract_id,
        },
      };
    });
  };
  const updateTaskGraphMetadata = (patch: Record<string, unknown>) => {
    setCoordinationDraft((current) => ({
      ...current,
      metadata: {
        ...asRecord(current.metadata),
        ...patch,
      },
    }));
  };
  const updateRuntimePolicy = (patch: Partial<typeof taskGraphDraftV2.runtime_policy>) => {
    setCoordinationDraft((current) => {
      const metadata = asRecord(current.metadata);
      return {
        ...current,
        coordinator_agent_id: patch.coordinator_agent_id ?? current.coordinator_agent_id,
        participant_agent_ids: patch.participant_agent_ids ?? current.participant_agent_ids,
        agent_group_id: patch.agent_group_id ?? current.agent_group_id,
        coordination_mode: patch.coordination_mode ?? current.coordination_mode,
        metadata: {
          ...metadata,
          runtime_policy: {
            ...asRecord(metadata.runtime_policy),
            ...patch,
          },
        },
      };
    });
  };
  const updateContextPolicy = (patch: Partial<typeof taskGraphDraftV2.context_policy>) => {
    setCoordinationDraft((current) => {
      const metadata = asRecord(current.metadata);
      return {
        ...current,
        shared_context_policy: patch.shared_context_policy ?? current.shared_context_policy,
        memory_sharing_policy: patch.memory_sharing_policy ?? current.memory_sharing_policy,
        handoff_policy: String(patch.handoff_policy ?? current.handoff_policy),
        metadata: {
          ...metadata,
          context_policy: {
            ...asRecord(metadata.context_policy),
            ...patch,
          },
        },
      };
    });
  };
  const updateWorkingMemoryPolicy = (patch: Partial<typeof taskGraphDraftV2.working_memory_policy>) => {
    setCoordinationDraft((current) => {
      const metadata = asRecord(current.metadata);
      return {
        ...current,
        metadata: {
          ...metadata,
          working_memory_policy: {
            ...asRecord(metadata.working_memory_policy),
            ...patch,
          },
        },
      };
    });
  };
  const repairPreflightIssue = (issue: TaskGraphPreflightIssue) => {
    if (
      (issue.source === "frontend.preflight.prompt_semantics" || issue.source === "frontend.preflight.projection_binding")
      && issue.scope === "node"
      && issue.target_id
    ) {
      const node = activeGraphNodes.find((item) => String(item.node_id ?? "") === issue.target_id);
      const title = String(node?.title ?? node?.label ?? issue.target_id);
      const role = String(node?.role ?? node?.work_posture ?? "执行者");
      const metadata = asRecord(node?.metadata);
      updateTaskGraphNode(issue.target_id, {
        metadata: {
          ...metadata,
          role_identity: metadata.role_identity || `你是一名${title}。`,
          responsibility_scope: metadata.responsibility_scope || `你只负责以“${role}”身份完成当前节点被分配的任务。`,
          responsibility_exclusions: metadata.responsibility_exclusions || "你不负责改变任务图结构，也不负责替其他节点完成职责。",
          definition_of_done: metadata.definition_of_done || "你必须输出可交接的结果、依据和仍需后续节点处理的问题。",
        },
      });
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
          {...rest}
          activeGraphEdges={activeGraphEdges}
          activeGraphNodes={activeGraphNodes}
          addTaskGraphEdge={addTaskGraphEdge}
          addTaskGraphNode={addTaskGraphNode}
          addTaskGraphRoleNode={addTaskGraphRoleNode}
          addTaskGraphSuccessorNode={addTaskGraphSuccessorNode}
          addTaskGraphTaskNode={addTaskGraphTaskNode}
          applyTaskGraphTemplate={applyTaskGraphTemplate}
          cycleTaskGraphEdgeMode={cycleTaskGraphEdgeMode}
          cycleTaskGraphNodeRole={cycleTaskGraphNodeRole}
          duplicateTaskGraphDraft={duplicateTaskGraphDraft}
          legacyDrafts={legacyDrafts}
          removeTaskGraphEdge={removeTaskGraphEdge}
          removeTaskGraphNode={removeTaskGraphNode}
          reverseTaskGraphEdge={reverseTaskGraphEdge}
          saveTaskGraphStack={saveTaskGraphStack}
          selectedTaskGraphSpec={selectedTaskGraphSpec}
          sendTaskGraphToChat={sendTaskGraphToChat}
          setCoordinationDraft={setCoordinationDraft}
          setProtocolDraft={setProtocolDraft}
          setTaskGraphPublished={setTaskGraphPublished}
          setTopologyDraft={setTopologyDraft}
          taskGraphDirty={rest.taskGraphDirty}
          taskGraphDraft={taskGraphDraft}
          updateTaskGraphEdge={updateTaskGraphEdge}
          updateTaskGraphNode={updateTaskGraphNode}
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
