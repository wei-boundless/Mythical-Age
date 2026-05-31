"use client";

import { useState } from "react";

import type { TaskGraphContractPreview } from "@/lib/api";

import { TaskGraphPublishRunPage } from "@/components/workspace/views/task-system/TaskGraphPublishRunPage";
import { TaskGraphSetupWizard } from "@/components/workspace/views/task-system/TaskGraphSetupWizard";
import { TaskGraphTopologyPage } from "@/components/workspace/views/task-system/TaskGraphTopologyPage";
import { TaskGraphValidationWorkbench } from "@/components/workspace/views/task-system/TaskGraphValidationWorkbench";

import type { TaskGraphStudioLayerId } from "./TaskGraphLayerNav";
import { TaskGraphStudioShell } from "./TaskGraphStudioShell";
import { asRecord, isTaskGraphPublishedState, type TaskGraphPublishStateV2 } from "./taskGraphDraftV2";
import { selectionFromFocus } from "./taskGraphEditorSelection";
import {
  focusForPreflightIssue,
  mergeTaskGraphEditorFocus,
  type TaskGraphEditorFocus,
} from "./taskGraphEditorFocus";
import { createMemoryEdgeDraft, taskGraphEdgeId } from "./taskGraphMemoryMatrix";
import { mergeContractBindingSection } from "./taskGraphContractBindings";
import { buildTaskGraphPreflightReport, type TaskGraphPreflightIssue } from "./taskGraphPreflight";
import type { TaskGraphWorkbenchProps } from "./taskGraphTypes";

export function TaskGraphWorkbench({
  taskGraphDraftV2,
  saveTaskGraphStack,
  applyTaskGraphTemplate,
  addTaskGraphTaskNode,
  reverseTaskGraphEdge,
  removeTaskGraphEdge,
  addTaskGraphSuccessorNode,
  removeTaskGraphNode,
  updateTaskGraphDraft,
  updateTaskGraphNode,
  updateTaskGraphEdge,
  updateTaskGraphMetadata,
  updateTaskGraphPublishState,
  activeGraphNodes,
  activeGraphEdges,
  workspaceSlot,
  ...rest
}: TaskGraphWorkbenchProps) {
  const [editorFocus, setEditorFocus] = useState<TaskGraphEditorFocus>(() => ({ layer: activeGraphNodes.length ? "topology" : "blueprint" }));
  const [graphContract, setGraphContract] = useState<TaskGraphContractPreview | null>(null);
  const [graphContractError, setGraphContractError] = useState("");
  const [showTemplateChooser, setShowTemplateChooser] = useState(false);
  const taskGraphStandardView = rest.taskGraphStandardView;
  const taskGraphStandardViewLoading = rest.taskGraphStandardViewLoading;
  const taskGraphStandardViewError = rest.taskGraphStandardViewError;
  const taskGraphStandardViewStale = rest.taskGraphStandardViewStale;
  const refreshTaskGraphStandardView = rest.refreshTaskGraphStandardView;
  const activeLayer = editorFocus.layer;
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
  const applyEditorFocus = (nextFocus: Partial<TaskGraphEditorFocus> & { layer?: TaskGraphStudioLayerId }) => {
    setEditorFocus((current) => mergeTaskGraphEditorFocus(current, nextFocus));
    rest.setTaskGraphEditorSelection((current) => selectionFromFocus(current, nextFocus));
  };
  const setActiveLayer = (layer: TaskGraphStudioLayerId) => {
    applyEditorFocus({ layer, facet: undefined, issue_id: undefined });
  };
  const focusPreflightIssue = (issue: TaskGraphPreflightIssue) => {
    const issueFocus = focusForPreflightIssue(issue);
    applyEditorFocus({
      ...issueFocus,
      layer: issue.scope === "node" || issue.scope === "edge" ? "topology" : issueFocus.layer,
    });
  };
  const edgeById = (edgeId: string) => activeGraphEdges.find((edge, index) => taskGraphEdgeId(edge, index) === edgeId) ?? null;
  const repairMemorySelector = (edgeId: string) => {
    const edge = edgeById(edgeId);
    if (!edge) return;
    const metadata = asRecord(edge.metadata);
    const selector = asRecord(metadata.selector);
    const collection = String(selector.collection ?? metadata.collection ?? "default").trim() || "default";
    updateTaskGraphEdge(edgeId, {
      metadata: {
        ...metadata,
        collection,
        selector: {
          ...selector,
          collection,
          status_filter: Array.isArray(selector.status_filter) ? selector.status_filter : ["committed"],
          limit: Number(selector.limit ?? 50),
        },
        model_visible_label: String(metadata.model_visible_label ?? collection),
        usage_instruction: String(metadata.usage_instruction ?? "你必须按这个输入包的约束完成当前节点任务，不得把缺失信息自行补写成事实。"),
      },
    });
  };
  const repairMemoryCommitPath = (edgeId: string) => {
    const edge = edgeById(edgeId);
    if (!edge) return;
    const metadata = asRecord(edge.metadata);
    const repositoryId = String(metadata.repository ?? metadata.repository_id ?? edge.target_node_id ?? edge.to ?? "").trim();
    const collectionId = String(asRecord(metadata.selector).collection ?? metadata.collection ?? "default").trim() || "default";
    const repositoryNodeId = String(edge.target_node_id ?? edge.to ?? repositoryId).trim();
    const taskNodeId = String(edge.source_node_id ?? edge.from ?? "").trim();
    if (!repositoryNodeId || !taskNodeId) return;
    const nextEdge = createMemoryEdgeDraft({
      operation: "commit",
      repositoryNodeId,
      repositoryId: repositoryId || repositoryNodeId,
      collectionId,
      taskNodeId,
    });
    const nextEdgeId = String(nextEdge.edge_id ?? "");
    if (activeGraphEdges.some((item, index) => taskGraphEdgeId(item, index) === nextEdgeId)) return;
    updateTaskGraph({ edges: [...(taskGraphDraftV2.edges ?? []), nextEdge] as typeof taskGraphDraftV2.edges });
  };
  const repairRevisionPacket = (edgeId: string) => {
    const edge = edgeById(edgeId);
    if (!edge) return;
    const metadata = asRecord(edge.metadata);
    updateTaskGraphEdge(edgeId, {
      metadata: {
        ...metadata,
        original_artifact_key: String(metadata.original_artifact_key ?? metadata.original_artifact_ref_key ?? metadata.candidate_ref_key ?? "candidate_ref"),
        review_result_key: String(metadata.review_result_key ?? metadata.verdict_key ?? "review_result"),
        usage_instruction: String(metadata.usage_instruction ?? "你必须依据审核结果修改被退回的原始产物，只处理审核指出的问题，不要自行替换任务目标。"),
      },
    });
  };
  const repairPreflightIssue = (issue: TaskGraphPreflightIssue) => {
    if (
      issue.source === "frontend.preflight.prompt_semantics"
      && issue.scope === "node"
      && issue.target_id
    ) {
      focusPreflightIssue(issue);
      return;
    }
    if (issue.source === "frontend.preflight.contract" && issue.scope === "edge" && issue.target_id) {
      const edge = edgeById(issue.target_id);
      updateTaskGraphEdge(issue.target_id, mergeContractBindingSection(edge ?? {}, "schema", { payload_contract_id: `${issue.target_id}.payload` }));
      focusPreflightIssue(issue);
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
      focusPreflightIssue(issue);
      return;
    }
    if (issue.source === "frontend.preflight.memory_selector" && issue.scope === "edge" && issue.target_id) {
      repairMemorySelector(issue.target_id);
      focusPreflightIssue(issue);
      return;
    }
    if (issue.source === "frontend.preflight.memory_commit_path" && issue.scope === "edge" && issue.target_id) {
      repairMemoryCommitPath(issue.target_id);
      focusPreflightIssue(issue);
      return;
    }
    if (issue.source === "frontend.preflight.memory_commit_visibility" && issue.scope === "edge" && issue.target_id) {
      const edge = edgeById(issue.target_id);
      const metadata = asRecord(edge?.metadata);
      updateTaskGraphEdge(issue.target_id, {
        metadata: {
          ...metadata,
          commit_visibility_policy: {
            ...asRecord(metadata.commit_visibility_policy ?? metadata.visibility_policy),
            required_status: "committed",
            visible_after: "next_clock",
          },
        },
      });
      focusPreflightIssue(issue);
      return;
    }
    if (issue.source === "frontend.preflight.revision_packet" && issue.scope === "edge" && issue.target_id) {
      repairRevisionPacket(issue.target_id);
      focusPreflightIssue(issue);
      return;
    }
    if (issue.source === "frontend.preflight.cognition_packet" && issue.scope === "edge" && issue.target_id) {
      const edge = edgeById(issue.target_id);
      const metadata = asRecord(edge?.metadata);
      updateTaskGraphEdge(issue.target_id, {
        metadata: {
          ...metadata,
          usage_instruction: String(metadata.usage_instruction ?? "你必须说明这份输入包在本轮任务中的用途，并按它约束输出。"),
        },
      });
      focusPreflightIssue(issue);
      return;
    }
    if (issue.source === "frontend.preflight.artifact" && issue.scope === "node" && issue.target_id) {
      updateTaskGraphNode(issue.target_id, {
        artifact_target: `${issue.target_id}.artifact`,
        artifact_policy: {
          required: true,
          lifecycle: "staging_until_commit",
        },
      });
      focusPreflightIssue(issue);
      return;
    }
    if (issue.source === "frontend.preflight.human_gate" && issue.scope === "node" && issue.target_id) {
      updateTaskGraphNode(issue.target_id, {
        human_gate_policy: {
          mode: "manual_required",
          blocking: true,
          work_order_schema: "node_standard_input_output",
        },
      });
      focusPreflightIssue(issue);
      return;
    }
    if (issue.source === "frontend.preflight.human_gate" && (issue.scope === "graph" || issue.scope === "runtime")) {
      const metadata = asRecord(taskGraphDraftV2.metadata);
      const continuationPolicy = asRecord(metadata.continuation_policy);
      updateTaskGraphMetadata({
        continuation_policy: {
          ...continuationPolicy,
          human_gate_mode: "manual_required",
          interaction_surface: "task_graph_run_dock",
        },
      });
      focusPreflightIssue(issue);
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
      focusPreflightIssue(issue);
    }
  };

  const preflightReport = buildTaskGraphPreflightReport({
    dirty: rest.taskGraphDirty,
    editorIssueCount: rest.editorIssueCount,
    editorValid: rest.editorValid,
    edges: activeGraphEdges,
    graphContract,
    metadata: taskGraphDraftV2.metadata,
    nodes: activeGraphNodes,
    standardView: taskGraphStandardView,
  });
  const pageContent = (() => {
    if (!activeGraphNodes.length || showTemplateChooser) {
      return (
        <TaskGraphSetupWizard
          domainTitle={rest.selectedDomain?.title || "当前任务域"}
          existingGraphSummary={activeGraphNodes.length ? {
            edgeCount: activeGraphEdges.length,
            nodeCount: activeGraphNodes.length,
            title: taskGraphDraftV2.title,
          } : undefined}
          onCancel={activeGraphNodes.length ? () => setShowTemplateChooser(false) : undefined}
          taskCount={rest.selectedDomainTasks.length}
          onApplyTemplate={(templateId, options) => {
            applyTaskGraphTemplate(templateId, options);
            setShowTemplateChooser(false);
            setActiveLayer("topology");
          }}
        />
      );
    }
    if (activeLayer === "topology") {
      return (
        <TaskGraphTopologyPage
          activeGraphEdges={activeGraphEdges}
          activeGraphNodes={activeGraphNodes}
          addTaskGraphSuccessorNode={addTaskGraphSuccessorNode}
          addTaskGraphTaskNode={addTaskGraphTaskNode}
          applyTaskGraphTemplate={applyTaskGraphTemplate}
          contractSpecs={rest.contractSpecs}
          handleTopologyNodeClick={rest.handleTopologyNodeClick}
          editorFocus={editorFocus}
          linkingFromNodeId={rest.linkingFromNodeId}
          onEditorFocus={applyEditorFocus}
          removeTaskGraphEdge={removeTaskGraphEdge}
          removeTaskGraphNode={removeTaskGraphNode}
          reverseTaskGraphEdge={reverseTaskGraphEdge}
          selectedDomainTasks={rest.selectedDomainTasks}
          selectedGraphEdge={rest.selectedGraphEdge}
          selectedGraphEdgeId={rest.selectedGraphEdgeId}
          selectedGraphNode={rest.selectedGraphNode}
          selectedGraphNodeId={rest.selectedGraphNodeId}
          semanticRelationPresets={rest.semanticRelationPresets}
          setLinkingFromNodeId={rest.setLinkingFromNodeId}
          setSelectedGraphEdgeId={rest.setSelectedGraphEdgeId}
          setSelectedGraphNodeId={rest.setSelectedGraphNodeId}
          taskGraphDraftV2={taskGraphDraftV2}
          updateTaskGraphDraft={updateTaskGraph}
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
          standardView={rest.taskGraphStandardView}
          standardViewStale={taskGraphStandardViewStale}
          onPublish={handlePublish}
          onRunBound={() => updateEditorPublishState("run_bound")}
          onSave={handleSaveDraft}
          onFocusIssue={focusPreflightIssue}
          onRepairIssue={repairPreflightIssue}
          publishState={publishState}
          saving={rest.saving}
          sharedGraphContract={graphContract}
          sharedGraphContractError={graphContractError}
          onSharedGraphContractChange={setGraphContract}
          onSharedGraphContractErrorChange={setGraphContractError}
        />
      );
    }
    return (
      <TaskGraphValidationWorkbench
        activeGraphEdges={activeGraphEdges}
        activeGraphNodes={activeGraphNodes}
        onFocusIssue={focusPreflightIssue}
        onRefreshStandardView={() => { void refreshTaskGraphStandardView(); }}
        onRepairIssue={repairPreflightIssue}
        preflightReport={preflightReport}
        standardView={taskGraphStandardView}
        standardViewError={taskGraphStandardViewError}
        standardViewLoading={taskGraphStandardViewLoading}
        standardViewStale={taskGraphStandardViewStale}
      />
    );
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
      publishState={publishState}
      saving={rest.saving}
      title={taskGraphDraftV2.title}
      valid={valid}
      workspaceSlot={workspaceSlot}
    >
      {pageContent}
    </TaskGraphStudioShell>
  );
}
