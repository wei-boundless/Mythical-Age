"use client";

import { AlertTriangle, Loader2, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";

import {
  buildTaskSystemTaskGraphExecutionPackage,
  type ContractManifest,
  type TaskGraphExecutionPackage,
  type TaskGraphRuntimeSpec,
} from "@/lib/api";

import { TaskGraphAgentRosterPage } from "@/components/workspace/views/task-system/TaskGraphAgentRosterPage";
import { TaskGraphBlueprintPage } from "@/components/workspace/views/task-system/TaskGraphBlueprintPage";
import { TaskGraphContractQualityPage } from "@/components/workspace/views/task-system/TaskGraphContractQualityPage";
import { TaskGraphMemoryArtifactPage } from "@/components/workspace/views/task-system/TaskGraphMemoryArtifactPage";
import { TaskGraphModuleCompositionPage } from "@/components/workspace/views/task-system/TaskGraphModuleCompositionPage";
import { TaskGraphPublishRunPage } from "@/components/workspace/views/task-system/TaskGraphPublishRunPage";
import { TaskGraphResponsibilityPage } from "@/components/workspace/views/task-system/TaskGraphResponsibilityPage";
import { TaskGraphRiskGovernancePage } from "@/components/workspace/views/task-system/TaskGraphRiskGovernancePage";
import { TaskGraphSetupWizard } from "@/components/workspace/views/task-system/TaskGraphSetupWizard";
import { TaskGraphTimelinePage } from "@/components/workspace/views/task-system/TaskGraphTimelinePage";
import { TaskGraphTopologyPage } from "@/components/workspace/views/task-system/TaskGraphTopologyPage";

import type { TaskGraphStudioLayerId } from "./TaskGraphLayerNav";
import { TaskGraphStudioShell } from "./TaskGraphStudioShell";
import { asRecord, isTaskGraphPublishedState, type TaskGraphPublishStateV2 } from "./taskGraphDraftV2";
import { clearCanonicalSelection, selectionFromFocus } from "./taskGraphEditorSelection";
import {
  focusForPreflightIssue,
  mergeTaskGraphEditorFocus,
  type TaskGraphEditorFocus,
} from "./taskGraphEditorFocus";
import { createMemoryEdgeDraft, taskGraphEdgeId } from "./taskGraphMemoryMatrix";
import { mergeContractBindingSection } from "./taskGraphContractBindings";
import type { TaskGraphPreflightIssue } from "./taskGraphPreflight";
import type { TaskGraphWorkbenchProps } from "./taskGraphTypes";

export function TaskGraphWorkbench({
  taskGraphDraftV2,
  saveTaskGraphStack,
  applyTaskGraphTemplate,
  addTaskGraphTaskNode,
  addTaskGraphRoleNode,
  addTaskGraphNode,
  reverseTaskGraphEdge,
  removeTaskGraphEdge,
  addTaskGraphSuccessorNode,
  removeTaskGraphNode,
  updateTaskGraphDraft,
  updateTaskGraphNode,
  updateTaskGraphEdge,
  updateTaskGraphMetadata,
  updateTaskGraphPublishState,
  updateTaskGraphRuntimePolicy,
  activeGraphNodes,
  activeGraphEdges,
  workspaceSlot,
  ...rest
}: TaskGraphWorkbenchProps) {
  const [editorFocus, setEditorFocus] = useState<TaskGraphEditorFocus>(() => ({ layer: activeGraphNodes.length ? "topology" : "blueprint" }));
  const [executionPackage, setExecutionPackage] = useState<TaskGraphExecutionPackage | null>(null);
  const [executionPackageError, setExecutionPackageError] = useState("");
  const [executionPackageLoading, setExecutionPackageLoading] = useState(false);
  const [showTemplateChooser, setShowTemplateChooser] = useState(false);
  const selectedTaskGraphId = rest.selectedTaskGraphId;
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
  const updateRuntimePolicy = (patch: Partial<typeof taskGraphDraftV2.runtime_policy>) => {
    updateTaskGraphRuntimePolicy(patch);
  };
  const compileExecutionPackage = async () => {
    if (!taskGraphDraftV2.graph_id) return;
    if (rest.taskGraphDirty || taskGraphStandardViewStale) {
      setExecutionPackage(null);
      setExecutionPackageError("当前草稿或标准视图已过期，请先保存并刷新标准视图后再编译执行包。");
      return;
    }
    setExecutionPackageLoading(true);
    setExecutionPackageError("");
    try {
      setExecutionPackage(await buildTaskSystemTaskGraphExecutionPackage(taskGraphDraftV2.graph_id));
    } catch (error) {
      setExecutionPackage(null);
      setExecutionPackageError(error instanceof Error ? error.message : "执行包编译失败");
    } finally {
      setExecutionPackageLoading(false);
    }
  };
  const applyEditorFocus = (nextFocus: Partial<TaskGraphEditorFocus> & { layer?: TaskGraphStudioLayerId }) => {
    setEditorFocus((current) => mergeTaskGraphEditorFocus(current, nextFocus));
    rest.setTaskGraphEditorSelection((current) => selectionFromFocus(current, nextFocus));
  };
  const setActiveLayer = (layer: TaskGraphStudioLayerId) => {
    applyEditorFocus({ layer, facet: undefined, issue_id: undefined });
  };
  const openGraphInStudio = (graphId: string) => {
    const target = rest.taskGraphs.find((graph) => graph.graph_id === graphId);
    if (!target) return;
    rest.setSelectedTaskGraphId(target.graph_id);
    rest.setTaskGraphEditorSelection(clearCanonicalSelection);
    setEditorFocus({ layer: "topology", facet: "graph" });
  };
  const focusPreflightIssue = (issue: TaskGraphPreflightIssue) => {
    applyEditorFocus(focusForPreflightIssue(issue));
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

  useEffect(() => {
    if (!selectedTaskGraphId || taskGraphStandardViewLoading) return;
    if (taskGraphStandardView?.graph?.graph_id === selectedTaskGraphId) return;
    void refreshTaskGraphStandardView();
  }, [
    refreshTaskGraphStandardView,
    selectedTaskGraphId,
    taskGraphStandardView,
    taskGraphStandardViewLoading,
  ]);

  const standardViewBanner = (
    <section className="task-graph-standard-status" aria-label="标准对象状态">
      <div className="task-graph-standard-status__identity">
        <span>标准对象视图</span>
        <strong>
          {taskGraphStandardViewLoading
            ? "正在编译图对象视图"
            : taskGraphStandardView
              ? taskGraphStandardViewStale ? "标准对象视图已过期" : "节点 / 边 / 资源 / 时序已对齐"
              : "尚未载入标准对象视图"}
        </strong>
        <small>
          {taskGraphStandardViewStale
            ? "当前标准对象视图来自旧草稿；请保存并刷新后再用于发布、预检或执行包编译。"
            : taskGraphStandardView
            ? `graph=${String(taskGraphStandardView.graph.graph_id ?? taskGraphDraftV2.graph_id)} · ${taskGraphStandardView.nodes.length} nodes · ${taskGraphStandardView.edges.length} edges · ${taskGraphStandardView.resources.length} resources`
            : "标准对象视图用于解释和校验当前草稿；可运行结构仍以 nodes / edges 草稿为唯一写入源。"}
        </small>
      </div>
      <div className="task-graph-standard-status__actions">
        {taskGraphStandardViewError ? (
          <div className="task-graph-standard-status__error">
            <AlertTriangle aria-hidden="true" size={14} />
            <span>{taskGraphStandardViewError}</span>
          </div>
        ) : null}
        <button
          className="task-graph-standard-status__refresh"
          disabled={taskGraphStandardViewLoading || !selectedTaskGraphId}
          onClick={() => { void refreshTaskGraphStandardView(); }}
          type="button"
        >
          {taskGraphStandardViewLoading ? <Loader2 aria-hidden="true" size={15} /> : <RefreshCw aria-hidden="true" size={15} />}
          <span>刷新标准视图</span>
        </button>
      </div>
    </section>
  );
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
          editorFocus={editorFocus}
          linkingFromNodeId={rest.linkingFromNodeId}
          onEditorFocus={applyEditorFocus}
          onOpenMemoryLayer={() => applyEditorFocus({ layer: "memory", facet: "repositories" })}
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
      return (
        <TaskGraphBlueprintPage
          activeGraphNodes={activeGraphNodes}
          onOpenTemplateChooser={() => setShowTemplateChooser(true)}
          taskGraphDraft={taskGraphDraftV2}
          updateRuntimePolicy={updateRuntimePolicy}
          updateTaskGraph={updateTaskGraph}
        />
      );
    }
    if (activeLayer === "modules") {
      return (
        <TaskGraphModuleCompositionPage
          activeGraphEdges={activeGraphEdges}
          activeGraphNodes={activeGraphNodes}
          a2aCatalog={rest.a2aCatalog}
          contractSpecs={rest.contractSpecs}
          dirty={rest.taskGraphDirty}
          domainTaskOptions={rest.domainTaskOptions}
          editorFocus={editorFocus}
          editorIssueCount={rest.editorIssueCount}
          editorValid={rest.editorValid}
          onEditorFocus={applyEditorFocus}
          onOpenGraph={openGraphInStudio}
          orchestrationAgentCatalog={rest.orchestrationAgentCatalog}
          standardView={rest.taskGraphStandardView}
          standardViewStale={taskGraphStandardViewStale}
          standardViewLoading={rest.taskGraphStandardViewLoading}
          taskGraphDraft={taskGraphDraftV2}
          taskGraphs={rest.taskGraphs}
          updateTaskGraphDraft={updateTaskGraph}
          updateTaskGraphEdge={updateTaskGraphEdge}
          updateTaskGraphMetadata={updateTaskGraphMetadata}
          updateTaskGraphNode={updateTaskGraphNode}
          updateTaskGraphRuntimePolicy={updateRuntimePolicy}
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
          activeGraphEdges={activeGraphEdges}
          activeGraphNodes={activeGraphNodes}
          selectedGraphEdge={rest.selectedGraphEdge}
          selectedGraphEdgeId={rest.selectedGraphEdgeId}
          selectedGraphNode={rest.selectedGraphNode}
          selectedGraphNodeId={rest.selectedGraphNodeId}
          standardView={rest.taskGraphStandardView}
          editorFocus={editorFocus}
          onEditorFocus={applyEditorFocus}
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
          editorFocus={editorFocus}
          standardView={rest.taskGraphStandardView}
          standardViewLoading={rest.taskGraphStandardViewLoading}
          taskGraphDraft={taskGraphDraftV2}
          updateTaskGraphMetadata={updateTaskGraphMetadata}
          updateTaskGraphEdge={updateTaskGraphEdge}
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
          editorFocus={editorFocus}
          onEditorFocus={applyEditorFocus}
          standardView={rest.taskGraphStandardView}
          standardViewLoading={rest.taskGraphStandardViewLoading}
          updateTaskGraphDraft={updateTaskGraph}
          updateTaskGraphEdge={updateTaskGraphEdge}
          updateTaskGraphNode={updateTaskGraphNode}
        />
      );
    }
    if (activeLayer === "risk") {
      return (
        <TaskGraphRiskGovernancePage
          activeGraphEdges={activeGraphEdges}
          activeGraphNodes={activeGraphNodes}
          taskGraphDraft={taskGraphDraftV2}
          editorFocus={editorFocus}
          onEditorFocus={applyEditorFocus}
          standardView={rest.taskGraphStandardView}
          standardViewLoading={rest.taskGraphStandardViewLoading}
          updateTaskGraphDraft={updateTaskGraph}
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
          editorFocus={editorFocus}
          onEditorFocus={applyEditorFocus}
          taskGraphDraft={taskGraphDraftV2}
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
          sharedContractManifest={executionPackage?.contract_manifest as ContractManifest | null}
          sharedExecutionPackage={executionPackage}
          sharedRuntimeSpec={executionPackage?.runtime_spec as TaskGraphRuntimeSpec | null}
          sharedRuntimeSpecError={executionPackageError}
          onSharedExecutionPackageChange={setExecutionPackage}
          onSharedRuntimeSpecErrorChange={setExecutionPackageError}
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
      editorFocus={editorFocus}
      executionPackage={executionPackage}
      executionPackageError={executionPackageError}
      executionPackageLoading={executionPackageLoading}
      graphId={taskGraphDraftV2.graph_id}
      issueCount={issueCount}
      nodeCount={activeGraphNodes.length}
      onCompileExecutionPackage={() => { void compileExecutionPackage(); }}
      onLayerChange={setActiveLayer}
      onPublish={handlePublish}
      onSave={handleSaveDraft}
      publishState={publishState}
      saving={rest.saving}
      title={taskGraphDraftV2.title}
      valid={valid}
      workspaceSlot={workspaceSlot}
    >
      {standardViewBanner}
      {pageContent}
    </TaskGraphStudioShell>
  );
}
