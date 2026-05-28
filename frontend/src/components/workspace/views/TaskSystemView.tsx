"use client";

import {
  Network,
  Plus,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { contractSpecTitle } from "@/components/workspace/views/task-system/ContractLibraryPanel";
import { TaskGraphWorkbench } from "@/components/workspace/views/task-system/TaskGraphWorkbench";
import { AgentRuntimePhaseMonitorPage } from "@/components/workspace/views/task-system/AgentRuntimePhaseMonitorPage";
import { ResourceAuthorityMapPage } from "@/components/workspace/views/task-system/ResourceAuthorityMapPage";
import { TaskSystemShell } from "@/components/workspace/views/task-system/TaskSystemShell";
import { TaskContractLibraryPage } from "@/components/workspace/views/task-system/library/TaskContractLibraryPage";
import { EngagementPlanLibraryPage } from "@/components/workspace/views/task-system/library/EngagementPlanLibraryPage";
import { TaskDomainLibraryPage } from "@/components/workspace/views/task-system/library/TaskDomainLibraryPage";
import { TaskGraphLibraryPage } from "@/components/workspace/views/task-system/library/TaskGraphLibraryPage";
import { TaskOrchestrationResourceLibraryPage } from "@/components/workspace/views/task-system/library/TaskOrchestrationResourceLibraryPage";
import { TaskRuntimeLibraryPage } from "@/components/workspace/views/task-system/library/TaskRuntimeLibraryPage";
import {
  asRecord,
  emptyTaskGraphDraftV2,
  inferTaskGraphBoundaryNodes,
  taskGraphRecordToDraftV2,
  type TaskGraphDraftV2,
  type TaskGraphPublishStateV2,
} from "@/components/workspace/views/task-system/taskGraphDraftV2";
import { buildTaskGraphUpsertPayload, resolveTaskGraphPublishCommit } from "@/components/workspace/views/task-system/taskGraphSaveMapper";
import {
  clearCanonicalSelection,
  emptyTaskGraphEditorSelection,
  emptyTaskGraphStandardViewState,
  loadedTaskGraphStandardViewState,
  markTaskGraphStandardViewStale,
  selectCanonicalEdge,
  selectCanonicalNode,
  taskGraphDraftRevisionKey,
} from "@/components/workspace/views/task-system/taskGraphEditorSelection";
import {
  recommendedTaskGraphId,
  sortTaskGraphsForWorkbench,
  taskGraphEnvironmentId,
} from "@/components/workspace/views/task-system/taskGraphSelection";
import { buildTaskGraphTemplateDraft, type TaskGraphTemplateId } from "@/components/workspace/views/task-system/taskGraphTemplates";
import {
  graphEdgeId,
  graphEdgeSource,
  graphEdgeTarget,
  graphNodeTaskId,
} from "@/components/workspace/views/task-system/taskGraphTopologyUtils";
import {
  TaskGraphChromeSelect,
  TaskSystemToolbarButton as ToolbarButton,
} from "@/components/workspace/views/task-system/TaskSystemWorkbenchUi";
import {
  deleteTaskSystemDomain,
  deleteTaskSystemEnvironment,
  getArtifactRepositoryOverview,
  getFormalMemoryOverview,
  getOrchestrationAgents,
  getOrchestrationResourceInventory,
  getOrchestrationHarnessTaskRunLiveMonitor,
  listOrchestrationHarnessTaskRuns,
  getSoulProjectionCards,
  getTaskSystemTaskGraph,
  getTaskSystemTaskGraphStandardView,
  getTaskSystemNextIds,
  getTaskSystemOverview,
  getTaskSystemEngagementRuns,
  deleteTaskSystemContract,
  upsertTaskSystemContract,
  upsertTaskSystemDomain,
  upsertTaskSystemEnvironment,
  upsertTaskSystemEnvironmentGroup,
  deleteTaskSystemEngagementPlan,
  upsertTaskSystemEntryPolicy,
  upsertTaskSystemEngagementPlan,
  startTaskSystemEngagementPlan,
  syncTaskSystemEngagementRunCloseout,
  upsertTaskSystemTaskGraph,
  type ConversationEntryPolicy,
  type ContractSpec,
  type ArtifactRepositoryOverview,
  type FormalMemoryOverview,
  type OrchestrationAgentRuntimeCatalog,
  type RuntimeResourceInventory,
  type HarnessTaskRunLiveMonitor,
  type HarnessTaskRunSummary,
  type SoulProjectionCard,
  type SoulProjectionCatalog,
  type RegisteredEngagementPlan,
  type EngagementEventRecord,
  type EngagementRunRecord,
  type SpecificTaskRecord,
  type TaskDomainRecord,
  type TaskEnvironmentGroupUpsertPayload,
  type TaskEnvironmentUpsertPayload,
  type TaskGraphEdgeRecord,
  type TaskGraphNodeRecord,
  type TaskGraphRecord,
  type TaskGraphDraftTopologySpec,
  type TaskGraphStandardView,
  type TaskSystemOverview,
  type TaskWorkflowRecord,
} from "@/lib/api";
import { useConfirmDialog } from "@/components/layout/ConfirmDialogProvider";
import { useAppStore } from "@/lib/store";

type TaskLayer = "management" | "editor";
type TaskSystemLayer = "domains" | "tasks" | "graphs" | "environments" | "contracts" | "resource-authority" | "agent-runtime-phase" | "orchestration" | "runtime";
type EngagementPlanPanel = "contract";
type ContractPanel = "library" | "templates";

type DomainRecord = {
  domain_id: string;
  task_modes: string[];
  title: string;
  description: string;
  enabled: boolean;
  sort_order: number;
  metadata?: Record<string, unknown>;
  tasks: SpecificTaskRecord[];
  entry_policy: ConversationEntryPolicy | null;
};

type EnvironmentDraft = {
  environment_id: string;
  title: string;
  description: string;
  group_id: string;
  environment_kind: string;
  enabled: boolean;
  prompt_id: string;
  prompt_content: string;
  storage_namespace: string;
  file_profile_refs_text: string;
  required_repository_kinds_text: string;
  sandbox_policy_text: string;
  execution_policy_text: string;
  artifact_policy_text: string;
  risk_policy_text: string;
  metadata_text: string;
};

type TaskEnvironmentManagement = NonNullable<TaskSystemOverview["task_environment_management"]>;
type TaskEnvironmentItem = TaskEnvironmentManagement["environments"][number];

function text(value: unknown, fallback = "-") {
  if (value === null || value === undefined || value === "") return fallback;
  if (Array.isArray(value)) return value.length ? value.join(" / ") : fallback;
  return String(value);
}

function splitList(value: string) {
  return value.split(/[\n,，]/).map((item) => item.trim()).filter(Boolean);
}

function listText(value: unknown) {
  return Array.isArray(value) ? value.map((item) => String(item)).join("\n") : "";
}

function dictOf(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function recordFieldText(record: Record<string, unknown> | null | undefined, keys: string[], fallback = "-") {
  for (const key of keys) {
    const value = record?.[key];
    if (value !== null && value !== undefined && String(value).trim()) {
      return String(value);
    }
  }
  return fallback;
}

function uniqueStrings(values: Array<string | null | undefined>) {
  return Array.from(new Set(values.map((item) => String(item ?? "").trim()).filter(Boolean)));
}

function getRuntimeTaskRunId(summary: HarnessTaskRunSummary | null | undefined) {
  return recordFieldText(dictOf(summary?.task_run), ["task_run_id", "id", "run_id"], "");
}

function runtimeTaskRunGraphId(summary: HarnessTaskRunSummary | null | undefined) {
  return recordFieldText(dictOf(summary?.task_run), ["graph_id", "coordination_task_id", "task_graph_id"], "");
}

function slugFromTitle(value: string, fallback = "custom") {
  const ascii = value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_\-]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return ascii || fallback;
}

function parseJsonObject(value: string, label: string) {
  const parsed = JSON.parse(value || "{}");
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${label} 必须是 JSON 对象`);
  }
  return parsed as Record<string, unknown>;
}

function parseJsonList(value: string, label: string) {
  const parsed = JSON.parse(value || "[]");
  if (!Array.isArray(parsed)) {
    throw new Error(`${label} 必须是 JSON 数组`);
  }
  return parsed.filter((item) => item && typeof item === "object") as Array<Record<string, unknown>>;
}

function jsonError(value: string, label: string, kind: "object" | "array") {
  try {
    kind === "object" ? parseJsonObject(value, label) : parseJsonList(value, label);
    return "";
  } catch (error) {
    return error instanceof Error ? error.message : `${label} 解析失败`;
  }
}

function emptyEntryPolicy(workflowId = ""): ConversationEntryPolicy {
  return {
    profile_id: "general.conversation.default",
    entry_policy_id: "general.conversation.default",
    title: "主会话入口识别",
    default_workflow_id: workflowId,
    input_contract_id: "UserMessage",
    output_contract_id: "AssistantFinalAnswer",
    conversation_entry_policy: "user_dialogue_to_main_agent",
    enabled: true,
    metadata: { managed_by: "task_domain_console" },
  };
}

function emptyTaskDomain(index = 0): TaskDomainRecord {
  return {
    domain_id: "domain.custom",
    title: "新任务域",
    description: "",
    enabled: true,
    sort_order: 100 + index * 10,
    metadata: { managed_by: "task_domain_console" },
  };
}

function emptySpecificTaskRecord(workflowId = "", flowId = ""): SpecificTaskRecord {
  return {
    task_id: "task.dev.new_task",
    task_title: "新特定任务",
    domain_id: "domain.development",
    task_mode: "bounded_patch",
    description: "",
    input_contract_id: "WorkspaceTaskInput",
    output_contract_id: "AssistantFinalAnswer",
    acceptance_profile_id: "",
    default_flow_contract_id: flowId || "flow.dev.bounded_patch",
    default_workflow_id: workflowId || "workflow.dev.bounded_patch",
    default_projection_policy: "workflow_compatible_or_task_default",
    task_policy: {
      safety_policy: {
        safety_class: "S2_bounded",
        write_mode: "scoped",
        verification_mode: "artifact_or_trace",
      },
      task_structure: {
        execution_chain_type: "single_agent_chain",
        trigger_signals: [],
      },
    },
    enabled: true,
    metadata: { managed_by: "task_domain_console" },
  };
}

function emptyEngagementPlan(environmentId = "env.general.workspace"): RegisteredEngagementPlan {
  return {
    plan_id: "engage.custom.plan",
    title: "自定义承接计划",
    description: "",
    version: "1.0.0",
    status: "draft",
    task_environment_id: environmentId,
    assignee: { kind: "agent", agent_id: "agent:0", participant_agent_ids: [] },
    runtime_profile: { runtime_mode: "professional", runtime_mode_policy: {} },
    execution_strategy: { kind: "single_agent_task_run", startup_policy: {}, lifecycle_policy: {} },
    input_contract: {},
    output_contract: {},
    prompt_contract: { user_visible_goal: "" },
    resource_requirements: {},
    capability_requirements: {},
    memory_requirements: {},
    acceptance_policy: {},
    recovery_policy: {},
    created_at: "",
    updated_at: "",
    supersedes_plan_id: "",
    metadata: {},
  };
}

function engagementPlanJsonPayload(plan: RegisteredEngagementPlan) {
  return {
    assignee: plan.assignee ?? {},
    input_contract: plan.input_contract ?? {},
    output_contract: plan.output_contract ?? {},
    prompt_contract: plan.prompt_contract ?? {},
    resource_requirements: plan.resource_requirements ?? {},
    capability_requirements: plan.capability_requirements ?? {},
    memory_requirements: plan.memory_requirements ?? {},
    acceptance_policy: plan.acceptance_policy ?? {},
    recovery_policy: plan.recovery_policy ?? {},
    metadata: plan.metadata ?? {},
  };
}

function engagementPlanJsonText(plan: RegisteredEngagementPlan) {
  return JSON.stringify(engagementPlanJsonPayload(plan), null, 2);
}

function mergeEngagementPlanJson(plan: RegisteredEngagementPlan, jsonText: string): RegisteredEngagementPlan {
  const payload = parseJsonObject(jsonText, "承接计划契约 JSON");
  return {
    ...plan,
    assignee: dictOf(payload.assignee) as RegisteredEngagementPlan["assignee"],
    input_contract: dictOf(payload.input_contract),
    output_contract: dictOf(payload.output_contract),
    prompt_contract: dictOf(payload.prompt_contract),
    resource_requirements: dictOf(payload.resource_requirements),
    capability_requirements: dictOf(payload.capability_requirements),
    memory_requirements: dictOf(payload.memory_requirements),
    acceptance_policy: dictOf(payload.acceptance_policy),
    recovery_policy: dictOf(payload.recovery_policy),
    metadata: dictOf(payload.metadata),
  };
}

function defaultEnvironmentDraft(): EnvironmentDraft {
  return {
    environment_id: "env.custom.workspace",
    title: "自定义任务环境",
    description: "",
    group_id: "environment_group.general",
    environment_kind: "custom",
    enabled: true,
    prompt_id: "environment.custom.workspace.v1",
    prompt_content: "你处在自定义任务环境中。这个环境只声明系统资源边界、存储区域、文件访问边界和执行约束。",
    storage_namespace: "custom/workspace",
    file_profile_refs_text: "file_profile.general_workspace",
    required_repository_kinds_text: "conversation_artifacts",
    sandbox_policy_text: JSON.stringify({
      enabled: false,
      sandbox_mode: "none",
      workspace_access: "read_mostly",
      write_policy: "artifact_only",
      shell_policy: "denied",
      browser_policy: "denied",
      network_policy: "denied",
    }, null, 2),
    execution_policy_text: JSON.stringify({
      real_workspace_access: "read_only",
      write_scope_policy: "artifact_only",
      shell_execution_policy: "denied",
      browser_execution_policy: "denied",
      network_execution_policy: "denied",
    }, null, 2),
    artifact_policy_text: JSON.stringify({
      artifact_root: "file_management_projection",
      naming_policy: "contract_scoped",
      publish_policy: "commit_gate",
    }, null, 2),
    risk_policy_text: JSON.stringify({
      default_permission_mode: "environment_boundary",
      approval_required_risk_levels: [],
      auto_denied_risk_levels: ["destructive_unbounded"],
    }, null, 2),
    metadata_text: "{}",
  };
}

function environmentDraftFromItem(item: TaskEnvironmentItem | null | undefined): EnvironmentDraft {
  if (!item) return defaultEnvironmentDraft();
  const record = item.record ?? {};
  const spec = dictOf(item.spec);
  const resourceSpace = dictOf(item.resource_space ?? spec.resource_space);
  const fileManagement = dictOf(item.file_management ?? spec.file_management);
  const prompts = Array.isArray(item.environment_prompts) ? item.environment_prompts : [];
  const firstPrompt = dictOf(prompts[0]);
  return {
    environment_id: String(record.environment_id || ""),
    title: String(record.title || ""),
    description: String(record.description || ""),
    group_id: String(record.group_id || "environment_group.general"),
    environment_kind: String(record.environment_kind || "custom"),
    enabled: record.enabled !== false,
    prompt_id: String(firstPrompt.prompt_id || `environment.${String(record.environment_id || "custom").replace(/^env\./, "")}.v1`),
    prompt_content: String(firstPrompt.content || ""),
    storage_namespace: String(resourceSpace.storage_namespace || ""),
    file_profile_refs_text: listText(fileManagement.file_profile_refs),
    required_repository_kinds_text: listText(fileManagement.required_repository_kinds),
    sandbox_policy_text: JSON.stringify(item.sandbox_policy ?? spec.sandbox_policy ?? {}, null, 2),
    execution_policy_text: JSON.stringify(item.execution_policy ?? spec.execution_policy ?? {}, null, 2),
    artifact_policy_text: JSON.stringify(item.artifact_policy ?? spec.artifact_policy ?? {}, null, 2),
    risk_policy_text: JSON.stringify(item.risk_policy ?? spec.risk_policy ?? {}, null, 2),
    metadata_text: JSON.stringify(record.metadata ?? {}, null, 2),
  };
}

function environmentPayloadFromDraft(draft: EnvironmentDraft): TaskEnvironmentUpsertPayload {
  const environmentId = draft.environment_id.trim();
  return {
    environment_id: environmentId,
    title: draft.title.trim() || environmentId,
    description: draft.description.trim(),
    group_id: draft.group_id.trim() || "environment_group.general",
    environment_kind: draft.environment_kind.trim() || "custom",
    enabled: draft.enabled,
    environment_prompts: draft.prompt_content.trim()
      ? [{
          prompt_id: draft.prompt_id.trim() || `environment.${environmentId.replace(/^env\./, "")}.v1`,
          content: draft.prompt_content.trim(),
          version: "v1",
          prompt_kind: "environment",
          cache_scope: "static_environment",
        }]
      : [],
    file_management: {
      file_profile_refs: splitList(draft.file_profile_refs_text),
      required_repository_kinds: splitList(draft.required_repository_kinds_text),
      canonical_write_policy: "commit_gate_required",
    },
    resource_space: {
      storage_namespace: draft.storage_namespace.trim() || environmentId.replace(/\./g, "/"),
      storage_root_policy: "environment_scoped",
      runtime_state_root_policy: "environment_scoped_runtime_state",
      artifact_storage_policy: "environment_scoped_artifacts",
      cache_storage_policy: "environment_scoped_cache",
    },
    sandbox_policy: parseJsonObject(draft.sandbox_policy_text, "沙盒策略"),
    execution_policy: parseJsonObject(draft.execution_policy_text, "执行策略"),
    artifact_policy: parseJsonObject(draft.artifact_policy_text, "产物策略"),
    risk_policy: parseJsonObject(draft.risk_policy_text, "风险策略"),
    metadata: parseJsonObject(draft.metadata_text, "环境元数据"),
  };
}

function environmentGroupPayload(groupId: string, overview: TaskSystemOverview | null): TaskEnvironmentGroupUpsertPayload {
  const group = overview?.task_environment_management?.groups?.find((item) => item.group_id === groupId);
  return {
    group_id: groupId,
    title: group?.title || groupId.replace(/^environment_group\./, ""),
    description: group?.description || "",
    enabled: group?.enabled !== false,
  };
}

function TaskEnvironmentLibraryPage({
  draft,
  environmentItems,
  groupOptions,
  onCreate,
  onDelete,
  onSave,
  onSelectEnvironment,
  onSetDraft,
  saving,
  selectedEnvironmentId,
}: {
  draft: EnvironmentDraft;
  environmentItems: TaskEnvironmentItem[];
  groupOptions: Array<{ value: string; label: string }>;
  onCreate: () => void;
  onDelete: () => void;
  onSave: () => void;
  onSelectEnvironment: (environmentId: string) => void;
  onSetDraft: (draft: EnvironmentDraft) => void;
  saving: string;
  selectedEnvironmentId: string;
}) {
  const selectedBoundary = dictOf(environmentItems.find((item) => item.record.environment_id === selectedEnvironmentId)?.environment_boundary);
  const boundaryContract = dictOf(selectedBoundary.boundary_contract);
  const patch = (next: Partial<EnvironmentDraft>) => onSetDraft({ ...draft, ...next });
  return (
    <section className="task-library-page task-environment-library-page">
      <header className="task-library-page__head">
        <div>
          <span>Task Environment</span>
          <h3>任务环境</h3>
          <p>配置环境 prompt、存储空间、文件边界、沙盒边界和执行约束。</p>
        </div>
        <div className="boundary-actions">
          <ToolbarButton onClick={onCreate}><Plus size={15} />新环境</ToolbarButton>
          <ToolbarButton disabled={saving === "task-environment"} onClick={onSave} variant="primary">保存环境</ToolbarButton>
          <ToolbarButton disabled={!selectedEnvironmentId || saving === "task-environment-delete"} onClick={onDelete}>删除配置</ToolbarButton>
        </div>
      </header>

      <div className="task-library-layout task-library-layout--split">
        <aside className="task-library-list" aria-label="任务环境列表">
          {environmentItems.map((item) => {
            const environmentId = item.record.environment_id;
            const active = environmentId === selectedEnvironmentId;
            const storage = dictOf(item.storage_space);
            return (
              <button
                className={active ? "task-library-list__item task-library-list__item--active" : "task-library-list__item"}
                key={environmentId}
                onClick={() => onSelectEnvironment(environmentId)}
                type="button"
              >
                <strong>{item.record.title || environmentId}</strong>
                <span>{environmentId}</span>
                <small>{String(storage.environment_storage_root || storage.task_library_root || "未配置存储")}</small>
              </button>
            );
          })}
        </aside>

        <main className="task-library-detail">
          <div className="boundary-form-grid">
            <label className="boundary-field">
              <span>环境标识</span>
              <input value={draft.environment_id} onChange={(event) => patch({ environment_id: event.target.value })} />
            </label>
            <label className="boundary-field">
              <span>名称</span>
              <input value={draft.title} onChange={(event) => patch({ title: event.target.value })} />
            </label>
            <label className="boundary-field">
              <span>分组</span>
              <select value={draft.group_id} onChange={(event) => patch({ group_id: event.target.value })}>
                {groupOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
              </select>
            </label>
            <label className="boundary-field">
              <span>类型</span>
              <select value={draft.environment_kind} onChange={(event) => patch({ environment_kind: event.target.value })}>
                {["custom", "general", "development", "creation"].map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
            </label>
            <label className="boundary-field boundary-field--wide">
              <span>描述</span>
              <input value={draft.description} onChange={(event) => patch({ description: event.target.value })} />
            </label>
            <label className="boundary-field">
              <span>Prompt ID</span>
              <input value={draft.prompt_id} onChange={(event) => patch({ prompt_id: event.target.value })} />
            </label>
            <label className="boundary-field">
              <span>Storage Namespace</span>
              <input value={draft.storage_namespace} onChange={(event) => patch({ storage_namespace: event.target.value })} />
            </label>
            <label className="boundary-field boundary-field--wide">
              <span>环境 Prompt</span>
              <textarea rows={6} value={draft.prompt_content} onChange={(event) => patch({ prompt_content: event.target.value })} />
            </label>
            <label className="boundary-field">
              <span>File Profiles</span>
              <textarea rows={4} value={draft.file_profile_refs_text} onChange={(event) => patch({ file_profile_refs_text: event.target.value })} />
            </label>
            <label className="boundary-field">
              <span>Repository Kinds</span>
              <textarea rows={4} value={draft.required_repository_kinds_text} onChange={(event) => patch({ required_repository_kinds_text: event.target.value })} />
            </label>
            <label className="boundary-field">
              <span>Sandbox Policy JSON</span>
              <textarea rows={8} value={draft.sandbox_policy_text} onChange={(event) => patch({ sandbox_policy_text: event.target.value })} />
            </label>
            <label className="boundary-field">
              <span>Execution Policy JSON</span>
              <textarea rows={8} value={draft.execution_policy_text} onChange={(event) => patch({ execution_policy_text: event.target.value })} />
            </label>
            <label className="boundary-field">
              <span>Artifact Policy JSON</span>
              <textarea rows={7} value={draft.artifact_policy_text} onChange={(event) => patch({ artifact_policy_text: event.target.value })} />
            </label>
            <label className="boundary-field">
              <span>Risk Policy JSON</span>
              <textarea rows={7} value={draft.risk_policy_text} onChange={(event) => patch({ risk_policy_text: event.target.value })} />
            </label>
          </div>

          <div className="task-library-summary-grid">
            <div>
              <span>Prompt 来源</span>
              <strong>{String(boundaryContract.environment_prompts_source || "task_environment_config")}</strong>
            </div>
            <div>
              <span>工具权威</span>
              <strong>{String(boundaryContract.tool_authority || "agent_profile_only")}</strong>
            </div>
            <div>
              <span>文件边界</span>
              <strong>{String(boundaryContract.file_boundary_authority || "file_access_table")}</strong>
            </div>
          </div>
        </main>
      </div>
    </section>
  );
}

function domainTitle(family: string) {
  const labels: Record<string, string> = {
    development: "开发任务域",
    health: "健康任务域",
    writing: "写作任务域",
    general: "通用入口域",
    capability: "能力调用域",
  };
  return labels[family] ?? `${family || "未分类"} 任务域`;
}

const COORDINATION_MODE_CHOICES = ["review_merge", "pipeline", "parallel_review"];
const CONFLICT_POLICY_CHOICES = ["coordinator_review", "majority_vote"];
const MERGE_POLICY_CHOICES = ["coordinator_final_merge", "ordered_append", "section_merge"];

function contractBelongsToDomain(spec: ContractSpec, domain: DomainRecord | null) {
  if (!domain) return true;
  const metadata = dictOf(spec.metadata);
  const domainId = String(metadata.domain_id ?? "").trim();
  if (domainId) {
    return domainId === domain.domain_id;
  }
  return true;
}

function scopedContractSpecs(contractSpecs: ContractSpec[], domain: DomainRecord | null) {
  return contractSpecs.filter((spec) => contractBelongsToDomain(spec, domain));
}

function deriveTaskGraphSpec(
  coordinationTaskId: string,
  domainId: string,
  nodes: Array<Record<string, unknown>>,
  edges: Array<Record<string, unknown>>,
): TaskGraphDraftTopologySpec {
  const nodeIds = nodes
    .map((node, index) => String(node.node_id ?? node.id ?? `node_${index + 1}`).trim())
    .filter(Boolean);
  const uniqueNodeIds = new Set(nodeIds);
  const startNodeIds = nodeIds.filter((nodeId) => !edges.some((edge) => graphEdgeTarget(edge) === nodeId));
  const terminalNodeIds = nodeIds.filter((nodeId) => !edges.some((edge) => graphEdgeSource(edge) === nodeId));
  const issues: Array<Record<string, unknown>> = [];

  if (!nodes.length) {
    issues.push({
      code: "empty_task_graph",
      severity: "blocker",
      message: "任务图还没有节点，不能预检或发布。",
    });
  }

  if (uniqueNodeIds.size !== nodeIds.length) {
    issues.push({
      code: "duplicate_node_id",
      severity: "blocker",
      message: "任务图中存在重复节点 ID。",
    });
  }

  edges.forEach((edge, index) => {
    const source = graphEdgeSource(edge);
    const target = graphEdgeTarget(edge);
    if (!source || !target) {
      issues.push({
        code: "edge_endpoint_missing",
        severity: "blocker",
        message: `第 ${index + 1} 条边缺少来源或目标节点。`,
      });
      return;
    }
    if (!uniqueNodeIds.has(source) || !uniqueNodeIds.has(target)) {
      issues.push({
        code: "edge_endpoint_unknown",
        severity: "blocker",
        message: `第 ${index + 1} 条边连接了不存在的节点。`,
      });
    }
  });

  return {
    graph_id: coordinationTaskId || "graph.draft",
    coordination_task_id: coordinationTaskId,
    domain_id: domainId,
    coordinator_agent_id: "",
    agent_group_id: "",
    nodes,
    edges,
    subtask_refs: uniqueStrings(nodes.map((node) => graphNodeTaskId(node))),
    communication_modes: uniqueStrings(edges.map((edge) => String(edge.mode ?? "").trim())),
    start_node_ids: startNodeIds,
    terminal_node_ids: terminalNodeIds,
    issues,
    valid: issues.length === 0,
    diagnostics: {
      derived_from: "task_graph_draft",
      node_count: nodes.length,
      edge_count: edges.length,
    },
  };
}

function buildDomains(consolePayload: TaskSystemOverview | null): DomainRecord[] {
  const tasks = consolePayload?.task_management.specific_task_records ?? [];
  const entryPolicies = consolePayload?.task_management.entry_policies ?? [];
  const formalDomains = consolePayload?.task_management.task_domains ?? [];
  const grouped = new Map<string, SpecificTaskRecord[]>();
  for (const task of tasks) {
    const metadata = dictOf(task.metadata);
    const domainId = String(task.domain_id ?? metadata.domain_id ?? "").trim() || "domain.general";
    grouped.set(domainId, [...(grouped.get(domainId) ?? []), task]);
  }
  const baseDomains: Array<TaskDomainRecord & { metadata?: Record<string, unknown> }> = formalDomains.length
    ? formalDomains
    : Array.from(grouped.keys()).map((domainId, index) => ({
        ...emptyTaskDomain(index),
        domain_id: domainId,
        title: domainTitle(String(domainId).replace(/^domain\./, "")),
      }));
  if (!baseDomains.length) baseDomains.push({ ...emptyTaskDomain(), domain_id: "domain.general", title: "通用任务域" });
  return baseDomains
    .map((domain, index) => {
      const domainId = domain.domain_id || "domain.general";
      const items = grouped.get(domainId) ?? [];
      return {
        domain_id: domainId,
        task_modes: uniqueStrings(items.map((task) => task.task_mode)),
        title: domain.title || domainTitle(String(domainId).replace(/^domain\./, "") || "general"),
        description: domain.description || "",
        enabled: domain.enabled ?? true,
        sort_order: domain.sort_order ?? index * 10,
        metadata: domain.metadata ?? {},
        tasks: items,
        entry_policy: entryPolicies.find((item) => String(item.metadata?.domain_id ?? "").trim() === domainId) ?? entryPolicies[index] ?? entryPolicies[0] ?? null,
      };
    })
    .sort((a, b) => a.sort_order - b.sort_order || a.title.localeCompare(b.title));
}

function taskDomainId(task: SpecificTaskRecord) {
  const metadata = dictOf(task.metadata);
  return String(task.domain_id ?? metadata.domain_id ?? "").trim() || "domain.general";
}

function normalizeTaskEnvironmentId(value: unknown) {
  const raw = String(value ?? "").trim();
  if (!raw) return "";
  return raw.startsWith("env.") ? raw : "";
}

function taskEnvironmentId(task: SpecificTaskRecord) {
  const metadata = dictOf(task.metadata);
  const taskPolicy = dictOf(task.task_policy);
  return normalizeTaskEnvironmentId(
    metadata.task_environment_id
    ?? metadata.environment_id
    ?? taskPolicy.task_environment_id
    ?? taskPolicy.environment_id,
  );
}

function taskEnvironmentTitle(environmentId: string) {
  return environmentRecordTitle(environmentId) || environmentId;
}

function environmentRecordTitle(environmentId: string, overview?: TaskSystemOverview | null) {
  const record = overview?.task_environment_management?.records?.find((item) => item.environment_id === environmentId);
  if (record?.title) return record.title;
  const labels: Record<string, string> = {
    "env.creation.writing": "Creative Writing",
    "env.development.sandbox": "Development Sandbox",
    "env.development.readonly": "Development Readonly",
    "env.research.web": "Web Research",
    "env.document.processing": "Document Processing",
    "env.general.workspace": "General Workspace",
  };
  return labels[environmentId] ?? "";
}

function taskEnvironmentItem(environmentId: string, overview?: TaskSystemOverview | null) {
  return overview?.task_environment_management?.environments?.find((item) => item.record.environment_id === environmentId) ?? null;
}

function taskEnvironmentStorageLabel(environmentId: string, overview?: TaskSystemOverview | null) {
  const storage = taskEnvironmentItem(environmentId, overview)?.storage_space ?? {};
  return String(storage.environment_storage_root ?? storage.task_library_root ?? "").trim();
}

type LayerNavItem<T extends string> = {
  value: T;
  label: string;
  meta: string;
  detail: string;
};

export function TaskSystemView() {
  const confirm = useConfirmDialog();
  const {
    activeWorkspaceView,
    clearTaskSystemRuntimeNavigationTarget,
    currentSessionId,
    setOrchestrationInspectorTarget,
    setTaskGraphRunInteractionOpen,
    setTaskSelection,
    setWorkspaceView,
    taskGraphLiveMonitor,
    taskGraphMonitorBinding,
    taskSystemRuntimeNavigationTarget,
  } = useAppStore();
  const [consolePayload, setConsolePayload] = useState<TaskSystemOverview | null>(null);
  const [engagementRuns, setEngagementRuns] = useState<EngagementRunRecord[]>([]);
  const [engagementEvents, setEngagementEvents] = useState<EngagementEventRecord[]>([]);
  const [projectionCatalog, setProjectionCatalog] = useState<SoulProjectionCatalog | null>(null);
  const [orchestrationAgentCatalog, setOrchestrationAgentCatalog] = useState<OrchestrationAgentRuntimeCatalog | null>(null);
  const [loading, setLoading] = useState(true);
  const [projectionLoading, setProjectionLoading] = useState(false);
  const [saving, setSaving] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [selectedDomainId, setSelectedDomainId] = useState("");
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [selectedTaskGraphId, setSelectedTaskGraphId] = useState("");
  const [editorEnvironmentId, setEditorEnvironmentId] = useState("");
  const [selectedEnvironmentId, setSelectedEnvironmentId] = useState("");
  const [editorDomainId, setEditorDomainId] = useState("");
  const [editorTaskGraphId, setEditorTaskGraphId] = useState("");
  const [taskLayer, setTaskLayer] = useState<TaskLayer>("management");
  const [taskSystemLayer, setTaskSystemLayer] = useState<TaskSystemLayer>("domains");
  const [editingDomainName, setEditingDomainName] = useState(false);
  const [taskGraphEditorSelection, setTaskGraphEditorSelection] = useState(() => emptyTaskGraphEditorSelection());
  const [linkingFromNodeId, setLinkingFromNodeId] = useState("");
  const [engagementPlanPanel] = useState<EngagementPlanPanel>("contract");
  const [contractPanel, setContractPanel] = useState<ContractPanel>("library");
  const loadInFlightRef = useRef<Promise<void> | null>(null);

  const [entryDraft, setEntryDraft] = useState<ConversationEntryPolicy>(emptyEntryPolicy());
  const [domainDraft, setDomainDraft] = useState<TaskDomainRecord>(emptyTaskDomain());
  const [selectedEngagementPlanId, setSelectedEngagementPlanId] = useState("");
  const [engagementPlanDraft, setEngagementPlanDraft] = useState<RegisteredEngagementPlan>(() => emptyEngagementPlan());
  const [engagementPlanJsonTextState, setEngagementPlanJsonTextState] = useState(engagementPlanJsonText(emptyEngagementPlan()));
  const [environmentDraft, setEnvironmentDraft] = useState<EnvironmentDraft>(() => defaultEnvironmentDraft());
  const [taskGraphDraftV2, setTaskGraphDraftV2] = useState<TaskGraphDraftV2>(() => emptyTaskGraphDraftV2());
  const [taskGraphStandardViewState, setTaskGraphStandardViewState] = useState(() => emptyTaskGraphStandardViewState());
  const [taskGraphStandardViewLoading, setTaskGraphStandardViewLoading] = useState(false);
  const [taskGraphStandardViewError, setTaskGraphStandardViewError] = useState("");
  const [activeTaskGraphDetail, setActiveTaskGraphDetail] = useState<TaskGraphRecord | null>(null);
  const [activeTaskGraphDetailError, setActiveTaskGraphDetailError] = useState("");
  const [runtimeTaskRunId, setRuntimeTaskRunId] = useState("");
  const [runtimeTaskRuns, setRuntimeTaskRuns] = useState<HarnessTaskRunSummary[]>([]);
  const [runtimeFormalOverview, setRuntimeFormalOverview] = useState<FormalMemoryOverview | null>(null);
  const [runtimeArtifactOverview, setRuntimeArtifactOverview] = useState<ArtifactRepositoryOverview | null>(null);
  const [runtimeLiveMonitor, setRuntimeLiveMonitor] = useState<HarnessTaskRunLiveMonitor | null>(null);
  const [runtimeResourceInventory, setRuntimeResourceInventory] = useState<RuntimeResourceInventory | null>(null);
  const [runtimeLoading, setRuntimeLoading] = useState(false);
  const [runtimeError, setRuntimeError] = useState("");
  const selectedDomainIdRef = useRef("");
  const projectionCatalogLoadRef = useRef<Promise<void> | null>(null);
  const orchestrationAgentCatalogLoadRef = useRef<Promise<void> | null>(null);
  const runtimeDefaultedRef = useRef(false);

  useEffect(() => {
    selectedDomainIdRef.current = selectedDomainId;
  }, [selectedDomainId]);

  const applyOverview = useCallback((overview: TaskSystemOverview) => {
    setConsolePayload(overview);
    const nextDomains = buildDomains(overview);
    const firstDomainWithTasks = nextDomains.find((item) => item.tasks.length > 0) ?? null;
    const fallbackDomain = firstDomainWithTasks ?? nextDomains[0] ?? null;
    const preferredDomain = nextDomains.find((item) => item.domain_id === selectedDomainIdRef.current) ?? null;
    const selectedDomain = preferredDomain && (preferredDomain.tasks.length > 0 || !firstDomainWithTasks)
      ? preferredDomain
      : fallbackDomain;
    const taskGraphs = sortTaskGraphsForWorkbench(overview.task_graph_management?.task_graphs ?? []);
    const engagementPlans = overview.task_management.engagement_plans ?? [];
    setSelectedDomainId(selectedDomain?.domain_id ?? "");
    setSelectedTaskId((current) => current || selectedDomain?.tasks[0]?.task_id || overview.task_management.specific_task_records[0]?.task_id || "");
    setSelectedEngagementPlanId((current) => current && engagementPlans.some((plan) => plan.plan_id === current)
      ? current
      : engagementPlans[0]?.plan_id || "");
    setEditorDomainId((current) => current || selectedDomain?.domain_id || "");
    setSelectedTaskGraphId((current) => recommendedTaskGraphId(taskGraphs, current));
    setEditorTaskGraphId((current) => current && taskGraphs.some((graph) => graph.graph_id === current) ? current : "");
    const environmentRecords = overview.task_environment_management?.records ?? [];
    setSelectedEnvironmentId((current) => current && environmentRecords.some((item) => item.environment_id === current)
      ? current
      : environmentRecords[0]?.environment_id || "");
  }, []);

  const loadProjectionCatalog = useCallback(async () => {
    if (projectionCatalogLoadRef.current) {
      return projectionCatalogLoadRef.current;
    }
    const run = (async () => {
      setProjectionLoading(true);
      try {
        setProjectionCatalog(await getSoulProjectionCards());
      } catch {
        setProjectionCatalog((current) => current ?? null);
      } finally {
        setProjectionLoading(false);
        projectionCatalogLoadRef.current = null;
      }
    })();
    projectionCatalogLoadRef.current = run;
    return run;
  }, []);

  const loadOrchestrationAgentCatalog = useCallback(async () => {
    if (orchestrationAgentCatalogLoadRef.current) {
      return orchestrationAgentCatalogLoadRef.current;
    }
    const run = (async () => {
      try {
        setOrchestrationAgentCatalog(await getOrchestrationAgents());
      } catch {
        setOrchestrationAgentCatalog((current) => current ?? null);
      } finally {
        orchestrationAgentCatalogLoadRef.current = null;
      }
    })();
    orchestrationAgentCatalogLoadRef.current = run;
    return run;
  }, []);

  const loadEngagementRuns = useCallback(async () => {
    try {
      const payload = await getTaskSystemEngagementRuns();
      setEngagementRuns(payload.engagement_runs ?? []);
      setEngagementEvents(payload.engagement_events ?? []);
    } catch {
      setEngagementRuns((current) => current);
      setEngagementEvents((current) => current);
    }
  }, []);

  const load = useCallback(async () => {
    if (loadInFlightRef.current) {
      return loadInFlightRef.current;
    }
    const run = (async () => {
      setLoading(true);
      setError("");
      try {
        const overview = await getTaskSystemOverview();
        applyOverview(overview);
        void loadEngagementRuns();
        void loadProjectionCatalog();
        void loadOrchestrationAgentCatalog();
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : "任务系统加载失败");
      } finally {
        setLoading(false);
        loadInFlightRef.current = null;
      }
    })();
    loadInFlightRef.current = run;
    return run;
  }, [applyOverview, loadEngagementRuns, loadOrchestrationAgentCatalog, loadProjectionCatalog]);

  useEffect(() => {
    if (activeWorkspaceView !== "task-system") return;
    void load();
  }, [activeWorkspaceView, load]);

  const domains = useMemo(() => buildDomains(consolePayload), [consolePayload]);
  const visibleDomains = useMemo(() => {
    const nextDomains = domains;
    const hasSelectedDomain = nextDomains.some((item) => item.domain_id === selectedDomainId);
    if (!selectedDomainId || hasSelectedDomain || !domainDraft.domain_id) {
      return nextDomains;
    }
    return [
      ...nextDomains,
      {
        domain_id: domainDraft.domain_id,
        task_modes: [],
        title: domainDraft.title,
        description: domainDraft.description,
        enabled: domainDraft.enabled,
        sort_order: domainDraft.sort_order,
        metadata: domainDraft.metadata ?? {},
        tasks: [],
        entry_policy: null,
      },
    ].sort((a, b) => a.sort_order - b.sort_order || a.title.localeCompare(b.title));
  }, [domainDraft, domains, selectedDomainId]);
  const selectedDomain = visibleDomains.find((item) => item.domain_id === selectedDomainId) ?? visibleDomains[0] ?? null;
  const tasks = useMemo(() => consolePayload?.task_management.specific_task_records ?? [], [consolePayload]);
  const engagementPlans = useMemo(() => consolePayload?.task_management.engagement_plans ?? [], [consolePayload]);
  const selectedEngagementPlan = engagementPlans.find((item) => item.plan_id === selectedEngagementPlanId) ?? engagementPlans[0] ?? null;
  const selectedEngagementPlanRuns = useMemo(
    () => engagementRuns.filter((run) => run.plan_id === selectedEngagementPlan?.plan_id),
    [engagementRuns, selectedEngagementPlan?.plan_id],
  );
  const workflows = useMemo(() => consolePayload?.task_management.workflow_resources ?? [], [consolePayload]);
  const contractCatalog = useMemo(() => consolePayload?.task_management.contract_catalog ?? [], [consolePayload]);
  const contractManagement = useMemo(() => consolePayload?.contract_management ?? null, [consolePayload]);
  const contractSpecs = useMemo(() => contractManagement?.contract_specs ?? [], [contractManagement]);
  const selectedDomainTasks = useMemo(() => selectedDomain?.tasks ?? [], [selectedDomain]);
  const selectedTask = selectedDomainTasks.find((item) => item.task_id === selectedTaskId) ?? selectedDomainTasks[0] ?? null;
  const domainContractSpecs = useMemo(() => scopedContractSpecs(contractSpecs, selectedDomain), [contractSpecs, selectedDomain]);
  const allTaskGraphs = useMemo(
    () => sortTaskGraphsForWorkbench(consolePayload?.task_graph_management?.task_graphs ?? []),
    [consolePayload],
  );
  const a2aCatalog = useMemo(() => {
    const protocol = consolePayload?.task_graph_management?.a2a;
    if (!protocol) return null;
    const runtimeAgents = orchestrationAgentCatalog?.agents ?? [];
    const agentCards = protocol.agent_cards?.length ? protocol.agent_cards : runtimeAgents;
    return {
      ...protocol,
      agent_cards: agentCards,
    };
  }, [consolePayload, orchestrationAgentCatalog]);
  const activeDomainId = selectedDomain?.domain_id || "";
  const taskGraphs = useMemo(
    () => activeDomainId ? sortTaskGraphsForWorkbench(allTaskGraphs.filter((item) => String(item.domain_id ?? "").trim() === activeDomainId)) : [],
    [activeDomainId, allTaskGraphs],
  );
  const selectedTaskGraph = taskGraphs.find((item) => item.graph_id === selectedTaskGraphId) ?? taskGraphs[0] ?? null;
  const editorDomain = visibleDomains.find((domain) => domain.domain_id === editorDomainId) ?? visibleDomains[0] ?? null;
  const editorTaskEnvironmentOptions = useMemo(() => {
    const environmentIds = uniqueStrings([
      ...(consolePayload?.task_environment_management?.records ?? []).map((item) => item.environment_id),
      ...tasks.map((task) => taskEnvironmentId(task)),
    ]);
    return environmentIds.map((environmentId) => {
      const item = taskEnvironmentItem(environmentId, consolePayload);
      const taskCount = item?.task_library?.task_count ?? tasks.filter((task) => taskEnvironmentId(task) === environmentId).length;
      const storage = taskEnvironmentStorageLabel(environmentId, consolePayload);
      return {
        value: environmentId,
        label: `${environmentRecordTitle(environmentId, consolePayload) || environmentId}${taskCount ? ` · ${taskCount} 个任务` : ""}${storage ? ` · ${storage}` : ""}`,
      };
    });
  }, [consolePayload, tasks]);
  const engagementEnvironmentOptions = useMemo(() => (
    (consolePayload?.task_environment_management?.records ?? []).map((item) => ({
      value: item.environment_id,
      label: item.title ? `${item.title} · ${item.environment_id}` : item.environment_id,
    }))
  ), [consolePayload]);
  const environmentItems = useMemo(
    () => consolePayload?.task_environment_management?.environments ?? [],
    [consolePayload],
  );
  const selectedEnvironmentItem = useMemo(
    () => environmentItems.find((item) => item.record.environment_id === selectedEnvironmentId)
      ?? environmentItems[0]
      ?? null,
    [environmentItems, selectedEnvironmentId],
  );
  const environmentGroupOptions = useMemo(
    () => consolePayload?.task_environment_management?.groups?.map((item) => ({
      value: item.group_id,
      label: `${item.title || item.group_id} · ${item.group_id}`,
    })) ?? [],
    [consolePayload],
  );
  const activeEditorEnvironmentId = editorEnvironmentId
    || editorTaskEnvironmentOptions[0]?.value
    || "";
  const editorEnvironmentTasks = useMemo(
    () => tasks.filter((task) => taskEnvironmentId(task) === activeEditorEnvironmentId),
    [activeEditorEnvironmentId, tasks],
  );
  const editorContractSpecs = useMemo(() => scopedContractSpecs(contractSpecs, editorDomain), [contractSpecs, editorDomain]);
  const editorTaskGraphs = useMemo(
    () => activeEditorEnvironmentId
      ? sortTaskGraphsForWorkbench(allTaskGraphs.filter((item) => taskGraphEnvironmentId(item) === activeEditorEnvironmentId))
      : [],
    [activeEditorEnvironmentId, allTaskGraphs],
  );
  const editorGraphSelectOptions = useMemo(() => {
    const options = editorTaskGraphs.map((task) => ({ value: task.graph_id, label: `${task.title} · ${task.graph_id}` }));
    const draftGraphId = String(taskGraphDraftV2.graph_id || "").trim();
    const draftInEditorEnvironment = draftGraphId
      && taskGraphEnvironmentId(taskGraphDraftV2) === activeEditorEnvironmentId;
    if (draftInEditorEnvironment && !options.some((option) => option.value === draftGraphId)) {
      return [
        {
          value: draftGraphId,
          label: `${taskGraphDraftV2.title || draftGraphId}（未保存草稿）`,
        },
        ...options,
      ];
    }
    return options;
  }, [activeEditorEnvironmentId, editorTaskGraphs, taskGraphDraftV2]);
  const editorSelectedTaskGraph = editorTaskGraphs.find((item) => item.graph_id === editorTaskGraphId) ?? null;
  const activeTaskGraphSummary = taskLayer === "editor" ? editorSelectedTaskGraph : selectedTaskGraph;
  const activeTaskGraph = activeTaskGraphDetail?.graph_id === activeTaskGraphSummary?.graph_id
    ? activeTaskGraphDetail
    : activeTaskGraphSummary;
  const activeTaskGraphHasFullTopology = Boolean((activeTaskGraphDetail?.nodes?.length || activeTaskGraphDetail?.edges?.length) && activeTaskGraphDetail.graph_id === activeTaskGraphSummary?.graph_id);
  const workflowOptions = useMemo(() => uniqueStrings(workflows.map((item) => item.workflow_id)), [workflows]);
  const editorAgentGroupOptions = useMemo(
    () => uniqueStrings(editorTaskGraphs.map((item) => String(item.runtime_policy?.agent_group_id ?? item.metadata?.agent_group_id ?? ""))),
    [editorTaskGraphs],
  );
  const editorDomainTaskOptions = useMemo(
    () => editorEnvironmentTasks.map((task) => ({ value: task.task_id, label: task.task_title })),
    [editorEnvironmentTasks],
  );
  const projectionCards = useMemo(() => projectionCatalog?.cards ?? [], [projectionCatalog]);
  const domainProjectionCards = useMemo(() => projectionCards.filter((card) => {
    if (!selectedDomain) return true;
    const haystack = `${String(card.projection_id ?? "")} ${String(card.soul_id ?? "")} ${String(card.soul_name ?? "")}`.toLowerCase();
    const domainToken = selectedDomain.domain_id.replace(/^domain\./, "").toLowerCase();
    return haystack.includes(domainToken) || haystack.includes(selectedDomain.title.toLowerCase());
  }), [projectionCards, selectedDomain]);
  const activeTaskGraphId = activeTaskGraphSummary?.graph_id || "";

  useEffect(() => {
    if (activeWorkspaceView !== "task-system") return;
    if (!activeTaskGraphId) {
      setActiveTaskGraphDetail(null);
      setActiveTaskGraphDetailError("");
      return;
    }
    let cancelled = false;
    setActiveTaskGraphDetailError("");
    void getTaskSystemTaskGraph(activeTaskGraphId)
      .then((payload) => {
        if (!cancelled) setActiveTaskGraphDetail(payload);
      })
      .catch((exc) => {
        if (!cancelled) {
          setActiveTaskGraphDetail(null);
          setActiveTaskGraphDetailError(exc instanceof Error ? exc.message : "任务图详情加载失败");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [activeTaskGraphId, activeWorkspaceView]);

  const refreshTaskGraphStandardView = useCallback(async () => {
    if (!activeTaskGraphId) {
      setTaskGraphStandardViewState(emptyTaskGraphStandardViewState());
      setTaskGraphStandardViewError("");
      return;
    }
    setTaskGraphStandardViewLoading(true);
    setTaskGraphStandardViewError("");
    try {
      const payload = await getTaskSystemTaskGraphStandardView(activeTaskGraphId);
      setTaskGraphStandardViewState(loadedTaskGraphStandardViewState({
        view: payload,
        graphId: activeTaskGraphId,
        revisionKey: taskGraphDraftRevisionKey({
          graphId: taskGraphDraftV2.graph_id,
          nodes: taskGraphDraftV2.nodes ?? [],
          edges: taskGraphDraftV2.edges ?? [],
          metadata: asRecord(taskGraphDraftV2.metadata),
        }),
      }));
    } catch (exc) {
      setTaskGraphStandardViewState(emptyTaskGraphStandardViewState());
      setTaskGraphStandardViewError(exc instanceof Error ? exc.message : "标准对象视图加载失败");
    } finally {
      setTaskGraphStandardViewLoading(false);
    }
  }, [activeTaskGraphId, taskGraphDraftV2]);

  useEffect(() => {
    if (activeWorkspaceView !== "task-system") return;
    if (!activeTaskGraphId) {
      setTaskGraphStandardViewState(emptyTaskGraphStandardViewState());
      setTaskGraphStandardViewError("");
      return;
    }
    void refreshTaskGraphStandardView();
  }, [activeTaskGraphId, activeWorkspaceView, refreshTaskGraphStandardView]);
  const openOrchestrationControl = useCallback((focus?: {
    agentId?: string;
    agentProfileId?: string;
    layer?: "registry" | "groups" | "runtime" | "eligibility";
    nodeId?: string;
    reason?: string;
  }) => {
    const focusedGraphId = taskLayer === "editor"
      ? (editorTaskGraphId || taskGraphDraftV2.graph_id)
      : (selectedTaskGraphId || taskGraphDraftV2.graph_id);
    setOrchestrationInspectorTarget({
      source: "task-system",
      orchestrationLayer: focus?.layer ?? "runtime",
      agentId: focus?.agentId,
      agentProfileId: focus?.agentProfileId,
      graphId: focusedGraphId || undefined,
      nodeId: focus?.nodeId,
      reason: focus?.reason ?? "从任务系统进入编排页：配置 Agent 运行档案。",
    });
    setWorkspaceView("orchestration");
  }, [editorTaskGraphId, selectedTaskGraphId, setOrchestrationInspectorTarget, setWorkspaceView, taskGraphDraftV2.graph_id, taskLayer]);

  useEffect(() => {
    if (!selectedDomain) return;
    setDomainDraft({
      domain_id: selectedDomain.domain_id,
      title: selectedDomain.title,
      description: selectedDomain.description,
      enabled: selectedDomain.enabled,
      sort_order: selectedDomain.sort_order,
      metadata: selectedDomain.metadata ?? {},
    });
    setEntryDraft(selectedDomain.entry_policy ?? emptyEntryPolicy(workflows[0]?.workflow_id ?? ""));
  }, [selectedDomain, workflows]);

  useEffect(() => {
    if (!selectedDomain) return;
    if (!selectedDomain.tasks.some((item) => item.task_id === selectedTaskId)) {
      setSelectedTaskId(selectedDomain.tasks[0]?.task_id || "");
    }
    setDomainDraft({
      domain_id: selectedDomain.domain_id,
      title: selectedDomain.title,
      description: selectedDomain.description,
      enabled: selectedDomain.enabled,
      sort_order: selectedDomain.sort_order,
      metadata: selectedDomain.metadata ?? {},
    });
    setEntryDraft(selectedDomain.entry_policy ?? emptyEntryPolicy(workflows[0]?.workflow_id ?? ""));
  }, [selectedDomain, selectedTaskId, workflows]);

  useEffect(() => {
    if (!taskGraphs.some((item) => item.graph_id === selectedTaskGraphId)) {
      setSelectedTaskGraphId(recommendedTaskGraphId(taskGraphs));
    }
  }, [taskGraphs, selectedTaskGraphId]);

  useEffect(() => {
    if (!taskSystemRuntimeNavigationTarget) return;
    setTaskLayer("management");
    setTaskSystemLayer(taskSystemRuntimeNavigationTarget.layer);
    setRuntimeTaskRunId(taskSystemRuntimeNavigationTarget.task_run_id);
    runtimeDefaultedRef.current = true;

    const targetGraphId = String(taskSystemRuntimeNavigationTarget.graph_id ?? "").trim();
    if (targetGraphId) {
      const targetGraph = allTaskGraphs.find((item) => String(item.graph_id ?? "").trim() === targetGraphId);
      if (targetGraph?.domain_id) {
        setSelectedDomainId(String(targetGraph.domain_id));
      }
      setSelectedTaskGraphId(targetGraphId);
    }

    clearTaskSystemRuntimeNavigationTarget();
  }, [allTaskGraphs, clearTaskSystemRuntimeNavigationTarget, taskSystemRuntimeNavigationTarget]);

  useEffect(() => {
    if (!editorTaskGraphs.some((item) => item.graph_id === editorTaskGraphId)) {
      if (editorTaskGraphId && editorTaskGraphId === taskGraphDraftV2.graph_id) {
        return;
      }
      setEditorTaskGraphId(recommendedTaskGraphId(editorTaskGraphs));
    }
  }, [editorTaskGraphId, editorTaskGraphs, taskGraphDraftV2.graph_id]);

  useEffect(() => {
    if (!selectedEngagementPlan) return;
    setEngagementPlanDraft({
      ...selectedEngagementPlan,
      assignee: selectedEngagementPlan.assignee ?? { kind: "agent", agent_id: "agent:0", participant_agent_ids: [] },
      runtime_profile: selectedEngagementPlan.runtime_profile ?? { runtime_mode: "professional", runtime_mode_policy: {} },
      execution_strategy: selectedEngagementPlan.execution_strategy ?? { kind: "single_agent_task_run", startup_policy: {}, lifecycle_policy: {} },
      input_contract: selectedEngagementPlan.input_contract ?? {},
      output_contract: selectedEngagementPlan.output_contract ?? {},
      prompt_contract: selectedEngagementPlan.prompt_contract ?? {},
      resource_requirements: selectedEngagementPlan.resource_requirements ?? {},
      capability_requirements: selectedEngagementPlan.capability_requirements ?? {},
      memory_requirements: selectedEngagementPlan.memory_requirements ?? {},
      acceptance_policy: selectedEngagementPlan.acceptance_policy ?? {},
      recovery_policy: selectedEngagementPlan.recovery_policy ?? {},
      metadata: selectedEngagementPlan.metadata ?? {},
    });
    setEngagementPlanJsonTextState(engagementPlanJsonText(selectedEngagementPlan));
  }, [selectedEngagementPlan]);

  useEffect(() => {
    if (!activeTaskGraph) {
      if (taskLayer === "editor" && editorTaskGraphId && editorTaskGraphId === taskGraphDraftV2.graph_id) {
        return;
      }
      setTaskGraphDraftV2(emptyTaskGraphDraftV2());
      return;
    }
    if (!activeTaskGraphHasFullTopology && activeTaskGraph.overview_mode === "summary") {
      return;
    }
    const nextNodes = (activeTaskGraph.nodes ?? []).map(normalizeTaskGraphNode);
    const nextEdges = (activeTaskGraph.edges ?? []).map(normalizeTaskGraphEdge);
    const graphDraftV2 = taskGraphRecordToDraftV2({
      ...activeTaskGraph,
      nodes: nextNodes,
      edges: nextEdges,
    });
    setTaskGraphDraftV2(graphDraftV2);
    setSelectedGraphNodeId(String((activeTaskGraph.nodes ?? [])[0]?.node_id ?? ""));
    setSelectedGraphEdgeId("");
    setLinkingFromNodeId("");
  }, [activeTaskGraph, activeTaskGraphHasFullTopology, editorTaskGraphId, taskGraphDraftV2.graph_id, taskLayer]);

  function createDomainDraft() {
    const index = visibleDomains.length + 1;
    const draft = emptyTaskDomain(index);
    draft.domain_id = `domain.custom_${index}`;
    draft.title = `新任务域 ${index}`;
    draft.metadata = { ...(draft.metadata ?? {}), draft_identity_locked: true };
    setDomainDraft(draft);
    setSelectedDomainId(draft.domain_id);
    setSelectedTaskId("");
    setTaskLayer("management");
    setEditingDomainName(true);
    setNotice("已生成任务域草稿，请填写名称后保存。");
  }

  function normalizeTaskGraphNode(node: Record<string, unknown>, index = 0): TaskGraphNodeRecord {
    const nodeId = String(node.node_id ?? node.id ?? `node_${index + 1}`).trim();
    const title = String(node.title ?? node.label ?? node.task_title ?? nodeId).trim() || nodeId;
    return {
      ...node,
      node_id: nodeId,
      node_type: String(node.node_type ?? "agent_role"),
      title,
    };
  }

  function normalizeTaskGraphEdge(edge: Record<string, unknown>, index = 0): TaskGraphEdgeRecord {
    const source = graphEdgeSource(edge);
    const target = graphEdgeTarget(edge);
    const edgeId = String(edge.edge_id ?? edge.id ?? (source && target ? `${source}->${target}` : `edge_${index + 1}`)).trim();
    return {
      ...edge,
      edge_id: edgeId,
      source_node_id: source,
      target_node_id: target,
      edge_type: String(edge.edge_type ?? edge.mode ?? "handoff"),
    };
  }

  function syncTaskGraphTopology(nodes: Array<Record<string, unknown>>, edges: Array<Record<string, unknown>>) {
    const nextNodes = nodes.map(normalizeTaskGraphNode);
    const nextEdges = edges.map(normalizeTaskGraphEdge);
    const boundaries = inferTaskGraphBoundaryNodes(nextNodes, nextEdges);
    setTaskGraphDraftV2((current) => ({
      ...current,
      nodes: nextNodes,
      edges: nextEdges,
      entry_node_id: boundaries.entry_node_id,
      output_node_id: boundaries.output_node_id,
    }));
  }

  function addTaskGraphNode() {
    const existingNodes = taskGraphDraftV2.nodes ?? [];
    const nextIndex = existingNodes.length + 1;
    const existingTaskIds = new Set(existingNodes.map((node) => graphNodeTaskId(node)).filter(Boolean));
    const nextTask = graphContextDomainTasks.find((task) => !existingTaskIds.has(task.task_id));
    const nodeId = nextTask ? `subtask_${nextIndex}` : `agent_${nextIndex}`;
    const node = {
      node_id: nodeId,
      node_type: nextTask ? "subtask" : "agent_role",
      task_id: nextTask?.task_id ?? "",
      task_title: nextTask?.task_title ?? "",
      agent_id: "",
      role: "participant",
      label: nextTask?.task_title ?? `节点 ${nextIndex}`,
    };
    syncTaskGraphTopology([...existingNodes, node], taskGraphDraftV2.edges ?? []);
    setSelectedGraphNodeId(nodeId);
    setSelectedGraphEdgeId("");
  }

  function addTaskGraphTaskNode(task: SpecificTaskRecord, role = "participant") {
    const nodeId = `subtask_${String((taskGraphDraftV2.nodes?.length || 0) + 1)}`;
    const node = {
      node_id: nodeId,
      node_type: "subtask",
      task_id: task.task_id,
      task_title: task.task_title,
      agent_id: "",
      role,
      label: task.task_title,
      title: task.task_title,
    };
    syncTaskGraphTopology([...(taskGraphDraftV2.nodes ?? []), node], taskGraphDraftV2.edges ?? []);
    setSelectedGraphNodeId(nodeId);
    setSelectedGraphEdgeId("");
  }

  function addTaskGraphRoleNode(role: string) {
    const nextIndex = (taskGraphDraftV2.nodes?.length || 0) + 1;
    const normalizedRole = role === "memory" ? "memory_repository" : role;
    const resourceNodeTypes = new Set(["memory_repository", "artifact_repository", "thread_ledger", "progress_ledger", "issue_ledger"]);
    const resourcePrefixByRole: Record<string, string> = {
      memory_repository: "memory.repository",
      artifact_repository: "artifact.repository",
      thread_ledger: "thread.ledger",
      progress_ledger: "progress.ledger",
      issue_ledger: "issue.ledger",
    };
    const isResourceNode = resourceNodeTypes.has(normalizedRole);
    const existingNodeIds = new Set((taskGraphDraftV2.nodes ?? []).map((node) => String(node.node_id ?? "")));
    let nodeId = normalizedRole === "coordinator"
      ? `coordinator_${nextIndex}`
      : isResourceNode
        ? `${resourcePrefixByRole[normalizedRole]}.1`
        : `agent_${nextIndex}`;
    if (isResourceNode) {
      let resourceIndex = 1;
      while (existingNodeIds.has(nodeId)) {
        resourceIndex += 1;
        nodeId = `${resourcePrefixByRole[normalizedRole]}.${resourceIndex}`;
      }
    }
    const titleByRole: Record<string, string> = {
      coordinator: "协调器",
      planner: "规划节点",
      executor: "执行节点",
      reviewer: "审查节点",
      verifier: "验证节点",
      summarizer: "整理节点",
      merge: "汇总节点",
      memory: "记忆仓库",
      memory_repository: "记忆仓库",
      artifact_repository: "产物仓库",
      thread_ledger: "线程账本",
      progress_ledger: "线程账本（旧名）",
      issue_ledger: "问题台账",
      writer: "执行节点",
      acceptance: "验收节点",
      participant: "协作节点",
    };
    const resourceMetadata = normalizedRole === "memory_repository" || normalizedRole.endsWith("_ledger")
      ? {
        memory_repository: {
          repository_id: nodeId,
          schema_id: "schema.memory_record",
          collections: [{
            collection_id: "default",
            title: "默认集合",
            record_kinds: [],
            key_strategy: "stable_key",
            default_version_selector: "latest_committed_before_clock",
            required_commit_status: "committed",
          }],
        },
      }
      : normalizedRole === "artifact_repository"
        ? {
          artifact_repository: {
            repository_id: nodeId,
            schema_id: "schema.artifact_ref",
          },
        }
        : {};
    const node = {
      node_id: nodeId,
      node_type: isResourceNode ? normalizedRole : "agent_role",
      task_id: "",
      task_title: "",
      agent_id: "",
      role: isResourceNode ? "resource" : normalizedRole,
      work_posture: isResourceNode ? "resource" : normalizedRole,
      label: titleByRole[normalizedRole] ?? "协作节点",
      title: titleByRole[normalizedRole] ?? "协作节点",
      ...(isResourceNode ? {
        metadata: resourceMetadata,
        resource_lifecycle_policy: {
          versioning: "append_version",
          mutable: true,
          commit_required: normalizedRole !== "artifact_repository",
        },
      } : {}),
    };
    syncTaskGraphTopology([...(taskGraphDraftV2.nodes ?? []), node], taskGraphDraftV2.edges ?? []);
    setSelectedGraphNodeId(nodeId);
    setSelectedGraphEdgeId("");
  }

  async function applyTaskGraphTemplate(template: TaskGraphTemplateId, options: Partial<Parameters<typeof buildTaskGraphTemplateDraft>[0]> = {}) {
    const shouldReplace = !(taskGraphDraftV2.nodes?.length || taskGraphDraftV2.edges?.length)
      || await confirm({
        title: "替换当前拓扑草稿",
        body: "应用图模板会替换当前未保存的节点和边。",
        confirmLabel: "替换",
        tone: "warning",
      });
    if (!shouldReplace) return;
    const metadata = asRecord(taskGraphDraftV2.metadata);
    const communicationModes = Array.isArray(metadata.business_communication_modes) ? metadata.business_communication_modes : [];
    const mode = String(communicationModes[0] ?? "structured_handoff");
    const selectedTaskForNode = graphContextDomainTasks[0] ?? null;
    const templateDraft = buildTaskGraphTemplateDraft({
      template_id: template,
      domain_id: graphContextDomainId,
      selected_task_title: selectedTaskForNode?.task_title || "",
      communication_mode: mode,
      ...options,
    });
    const nodes = templateDraft.nodes;
    const edges = templateDraft.edges;
    syncTaskGraphTopology(nodes, edges);
    setTaskGraphDraftV2((current) => ({
      ...current,
      entry_node_id: templateDraft.entry_node_id,
      output_node_id: templateDraft.output_node_id,
      runtime_policy: {
        ...current.runtime_policy,
        coordination_mode: templateDraft.coordination_mode,
        participant_agent_ids: templateDraft.participant_agent_ids,
      },
      metadata: {
        ...asRecord(current.metadata),
        ...templateDraft.metadata,
        setup_template_id: template,
      },
    }));
    setSelectedGraphNodeId(nodes[0]?.node_id ?? "");
    setSelectedGraphEdgeId("");
    setLinkingFromNodeId("");
    setTaskLayer("editor");
  }

  function addTaskGraphSuccessorNode(fromNodeId: string) {
    const nextIndex = (taskGraphDraftV2.nodes?.length || 0) + 1;
    const nodeId = `agent_${nextIndex}`;
    const node = {
      node_id: nodeId,
      node_type: "agent_role",
      task_id: "",
      task_title: "",
      agent_id: "",
      role: "participant",
      label: `节点 ${nextIndex}`,
      title: `节点 ${nextIndex}`,
    };
    const edge = {
      edge_id: `edge_${String((taskGraphDraftV2.edges?.length || 0) + 1)}`,
      from: fromNodeId,
      to: nodeId,
      source_node_id: fromNodeId,
      target_node_id: nodeId,
      mode: "structured_handoff",
    };
    syncTaskGraphTopology([...(taskGraphDraftV2.nodes ?? []), node], [...(taskGraphDraftV2.edges ?? []), edge]);
    setSelectedGraphNodeId(nodeId);
    setSelectedGraphEdgeId("");
    setLinkingFromNodeId("");
  }

  function updateTaskGraphNode(nodeId: string, patch: Record<string, unknown>) {
    const nextNodesSnapshot = (taskGraphDraftV2.nodes ?? []).map((node) =>
      String(node.node_id ?? "") === nodeId ? { ...node, ...patch } : node,
    );
    syncTaskGraphTopology(nextNodesSnapshot, taskGraphDraftV2.edges ?? []);
  }

  function removeTaskGraphNode(nodeId: string) {
    const nextNodes = (taskGraphDraftV2.nodes ?? []).filter((node) => String(node.node_id ?? "") !== nodeId);
    const nextEdges = (taskGraphDraftV2.edges ?? []).filter(
      (edge) => graphEdgeSource(edge) !== nodeId && graphEdgeTarget(edge) !== nodeId,
    );
    syncTaskGraphTopology(nextNodes, nextEdges);
    if (selectedGraphNodeId === nodeId) setSelectedGraphNodeId("");
    if (linkingFromNodeId === nodeId) setLinkingFromNodeId("");
  }

  function handleTopologyNodeClick(nodeId: string) {
    if (linkingFromNodeId) {
      if (linkingFromNodeId !== nodeId) {
        const from = linkingFromNodeId;
        const to = nodeId;
        const exists = (taskGraphDraftV2.edges ?? []).some((edge) => graphEdgeSource(edge) === from && graphEdgeTarget(edge) === to);
        if (!exists) {
          const nextIndex = (taskGraphDraftV2.edges?.length || 0) + 1;
          const edge = {
            edge_id: `edge_${nextIndex}`,
            from,
            to,
            source_node_id: from,
            target_node_id: to,
            mode: "structured_handoff",
          };
          setSelectedGraphEdgeId(graphEdgeId(edge, nextIndex - 1));
          syncTaskGraphTopology(taskGraphDraftV2.nodes ?? [], [...(taskGraphDraftV2.edges ?? []), edge]);
        }
      }
      setLinkingFromNodeId("");
      setSelectedGraphNodeId("");
      return;
    }
    setSelectedGraphNodeId(nodeId);
    setSelectedGraphEdgeId("");
  }

  function updateTaskGraphEdge(edgeId: string, patch: Record<string, unknown>) {
    const nextEdgesSnapshot = (taskGraphDraftV2.edges ?? []).map((edge, index) =>
      graphEdgeId(edge, index) === edgeId ? { ...edge, ...patch } : edge,
    );
    syncTaskGraphTopology(taskGraphDraftV2.nodes ?? [], nextEdgesSnapshot);
  }

  function reverseTaskGraphEdge(edgeId: string) {
    const nextEdges = (taskGraphDraftV2.edges ?? []).map((edge, index) => {
      if (graphEdgeId(edge, index) !== edgeId) {
        return edge;
      }
      const from = graphEdgeSource(edge);
      const to = graphEdgeTarget(edge);
      return {
        ...edge,
        from: to,
        to: from,
        source_node_id: to,
        target_node_id: from,
      };
    });
    syncTaskGraphTopology(taskGraphDraftV2.nodes ?? [], nextEdges);
  }

  function removeTaskGraphEdge(edgeId: string) {
    const nextEdges = (taskGraphDraftV2.edges ?? []).filter((edge, index) => graphEdgeId(edge, index) !== edgeId);
    syncTaskGraphTopology(taskGraphDraftV2.nodes ?? [], nextEdges);
    if (selectedGraphEdgeId === edgeId) setSelectedGraphEdgeId("");
  }

  async function createTaskGraphDraft() {
    const draftDomain = taskLayer === "editor" ? editorDomain : selectedDomain;
    const draftDomainId = draftDomain?.domain_id || taskGraphDraftV2.domain_id || "";
    const draftEnvironmentId = activeEditorEnvironmentId;
    if (!draftDomainId) {
      setError("请先选择任务域，再创建任务图。");
      return;
    }
    if (!draftEnvironmentId) {
      setError("请先选择任务环境，再创建任务图。");
      return;
    }
    setSaving("task-graph-create");
    setError("");
    setNotice("");
    try {
      const ids = await getTaskSystemNextIds();
      const graphId = ids.graph_id;
      const nextDraft: TaskGraphDraftV2 = {
        ...emptyTaskGraphDraftV2(),
        graph_id: graphId,
        title: `${ids.display_numbers.graph} 任务图`,
        domain_id: draftDomainId,
        task_id: "",
        metadata: {
          managed_by: "task_domain_console",
          graph_source: "task_graph_editor_v2",
          draft_identity_locked: true,
          domain_id: draftDomainId,
          task_environment_id: draftEnvironmentId,
          environment_id: draftEnvironmentId,
        },
        runtime_policy: {
          ...emptyTaskGraphDraftV2().runtime_policy,
          task_environment_id: draftEnvironmentId,
          environment_id: draftEnvironmentId,
        },
        context_policy: {
          ...emptyTaskGraphDraftV2().context_policy,
          task_environment_id: draftEnvironmentId,
          environment_id: draftEnvironmentId,
        },
      };
      nextDraft.metadata = {
        ...nextDraft.metadata,
        domain_id: draftDomainId,
        task_environment_id: draftEnvironmentId,
        environment_id: draftEnvironmentId,
      };
      setEditorDomainId(draftDomainId);
      setEditorTaskGraphId(nextDraft.graph_id);
      setSelectedTaskGraphId(nextDraft.graph_id);
      setTaskLayer("editor");
      setTaskGraphDraftV2(nextDraft);
      setSelectedGraphNodeId("");
      setSelectedGraphEdgeId("");
      setLinkingFromNodeId("");
      setNotice(`已生成任务图草稿：${nextDraft.graph_id}`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "生成任务图草稿失败");
    } finally {
      setSaving("");
    }
  }

  async function duplicateTaskGraphDraft() {
    const sourceTaskGraph = taskLayer === "editor" ? editorSelectedTaskGraph : selectedTaskGraph;
    if (!sourceTaskGraph) {
      setError("当前没有可复制的任务图");
      return;
    }
    const draftDomain = taskLayer === "editor" ? editorDomain : selectedDomain;
    const sourceDraft = taskGraphRecordToDraftV2(sourceTaskGraph);
    const draftDomainId = draftDomain?.domain_id || sourceDraft.domain_id || "";
    const draftEnvironmentId = taskGraphEnvironmentId(sourceTaskGraph)
      || activeEditorEnvironmentId;
    if (!draftEnvironmentId) {
      setError("当前图没有标准任务环境，不能复制为可运行图任务。");
      return;
    }
    setSaving("task-graph-duplicate");
    setError("");
    setNotice("");
    try {
      const ids = await getTaskSystemNextIds();
      const nextGraphId = ids.graph_id;
      const nextTitle = `${sourceDraft.title || ids.display_numbers.graph} 副本`;
      const nextNodes = (sourceDraft.nodes ?? []).map(normalizeTaskGraphNode);
      const nextEdges = (sourceDraft.edges ?? []).map(normalizeTaskGraphEdge);
      const boundaries = inferTaskGraphBoundaryNodes(nextNodes, nextEdges);
      const nextDraft: TaskGraphDraftV2 = {
        ...sourceDraft,
        graph_id: nextGraphId,
        title: nextTitle,
        domain_id: draftDomainId,
        task_id: "",
        nodes: nextNodes,
        edges: nextEdges,
        entry_node_id: boundaries.entry_node_id,
        output_node_id: boundaries.output_node_id,
        publish_state: "draft",
        metadata: {
          ...asRecord(sourceDraft.metadata),
          graph_source: "task_graph_editor_v2",
          duplicated_from_graph_id: sourceDraft.graph_id,
          domain_id: draftDomainId,
          task_environment_id: draftEnvironmentId,
          environment_id: draftEnvironmentId,
          task_id: undefined,
        },
        runtime_policy: {
          ...sourceDraft.runtime_policy,
          task_environment_id: draftEnvironmentId,
          environment_id: draftEnvironmentId,
        },
        context_policy: {
          ...sourceDraft.context_policy,
          task_environment_id: draftEnvironmentId,
          environment_id: draftEnvironmentId,
        },
      };
      setEditorDomainId(draftDomainId);
      setEditorTaskGraphId(nextGraphId);
      setSelectedTaskGraphId(nextGraphId);
      setTaskLayer("editor");
      setTaskGraphDraftV2(nextDraft);
      setSelectedGraphNodeId(String((nextDraft.nodes ?? [])[0]?.node_id ?? ""));
      setSelectedGraphEdgeId("");
      setLinkingFromNodeId("");
      setNotice(`已复制任务图草稿：${nextGraphId}`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "复制任务图草稿失败");
    } finally {
      setSaving("");
    }
  }

  async function saveEntry() {
    setSaving("entry");
    setError("");
    setNotice("");
    try {
      const payload = await upsertTaskSystemEntryPolicy(entryDraft.profile_id, entryDraft);
      setConsolePayload(payload);
      setNotice("入口识别已保存。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存入口识别失败");
    } finally {
      setSaving("");
    }
  }

  async function saveDomain() {
    setSaving("domain");
    setError("");
    setNotice("");
    try {
      const isNewDraft = !domains.some((domain) => domain.domain_id === domainDraft.domain_id);
      const normalizedDomainId = domainDraft.domain_id || `domain.${slugFromTitle(domainDraft.title)}`;
      const payload = await upsertTaskSystemDomain(normalizedDomainId, {
        ...domainDraft,
        domain_id: normalizedDomainId,
        title: domainDraft.title.trim() || `${normalizedDomainId.replace(/^domain\./, "")}任务域`,
        metadata: {
          ...(domainDraft.metadata ?? {}),
        },
      });
      setConsolePayload(payload);
      setSelectedDomainId(normalizedDomainId);
      setEditingDomainName(false);
      setNotice(isNewDraft ? "新任务域已保存。" : "任务域名称已保存。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存任务域失败");
    } finally {
      setSaving("");
    }
  }

  async function deleteDomain(domain: DomainRecord) {
    const confirmed = await confirm({
      title: `删除任务域「${domain.title}」`,
      body: `这会同时删除该任务域下的 ${domain.tasks.length} 个特定任务及其装配配置。`,
      confirmLabel: "删除任务域",
    });
    if (!confirmed) return;
    setSaving("domain-delete");
    setError("");
    setNotice("");
    try {
      const payload = await deleteTaskSystemDomain(domain.domain_id);
      const nextDomains = buildDomains(payload);
      setConsolePayload(payload);
      setSelectedDomainId(nextDomains[0]?.domain_id || "");
      setSelectedTaskId(nextDomains[0]?.tasks[0]?.task_id || "");
      setSelectedTaskGraphId("");
      setEditingDomainName(false);
      setNotice("任务域及其特定任务已删除。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "删除任务域失败");
    } finally {
      setSaving("");
    }
  }

  function createEngagementPlanDraft() {
    const index = engagementPlans.length + 1;
    const environmentId = selectedEnvironmentItem?.record.environment_id || engagementEnvironmentOptions[0]?.value || "env.general.workspace";
    const plan = {
      ...emptyEngagementPlan(environmentId),
      plan_id: `engage.custom.plan_${String(index).padStart(2, "0")}`,
      title: `承接计划 ${String(index).padStart(2, "0")}`,
    };
    setSelectedEngagementPlanId(plan.plan_id);
    setEngagementPlanDraft(plan);
    setEngagementPlanJsonTextState(engagementPlanJsonText(plan));
    setTaskSystemLayer("tasks");
    setNotice("已创建承接计划草稿。");
  }

  async function saveEngagementPlanDraft() {
    const planId = engagementPlanDraft.plan_id.trim();
    if (!planId.startsWith("engage.")) {
      setError("承接计划 ID 必须以 engage. 开头。");
      return;
    }
    const jsonErrorMessage = jsonError(engagementPlanJsonTextState, "承接计划契约 JSON", "object");
    if (jsonErrorMessage) {
      setError(jsonErrorMessage);
      return;
    }
    setSaving("engagement-plan-save");
    setError("");
    setNotice("");
    try {
      const payload = await upsertTaskSystemEngagementPlan(planId, mergeEngagementPlanJson(engagementPlanDraft, engagementPlanJsonTextState));
      setConsolePayload(payload);
      setSelectedEngagementPlanId(planId);
      setNotice("承接计划已保存。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存承接计划失败");
    } finally {
      setSaving("");
    }
  }

  async function deleteEngagementPlanDraft() {
    if (!selectedEngagementPlan) return;
    const confirmed = await confirm({
      title: `删除承接计划「${selectedEngagementPlan.title}」`,
      body: "这会删除该计划的启动契约，不会删除已经产生的运行记录。",
      confirmLabel: "删除计划",
    });
    if (!confirmed) return;
    setSaving("engagement-plan-delete");
    setError("");
    setNotice("");
    try {
      const payload = await deleteTaskSystemEngagementPlan(selectedEngagementPlan.plan_id);
      const nextPlans = payload.task_management.engagement_plans ?? [];
      setConsolePayload(payload);
      setSelectedEngagementPlanId(nextPlans[0]?.plan_id || "");
      setNotice("承接计划已删除。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "删除承接计划失败");
    } finally {
      setSaving("");
    }
  }

  async function startEngagementPlanDraft() {
    if (!selectedEngagementPlan) return;
    setSaving("engagement-plan-start");
    setError("");
    setNotice("");
    try {
      const result = await startTaskSystemEngagementPlan(selectedEngagementPlan.plan_id, {
        session_id: currentSessionId || "session:engagement",
        startup_parameters: {},
      });
      const taskRun = result.task_run as { task_run_id?: string } | undefined;
      if (taskRun?.task_run_id) {
        setRuntimeTaskRunId(taskRun.task_run_id);
      }
      await loadEngagementRuns();
      setNotice(result.decision === "started" ? "承接计划已启动。" : `承接计划返回：${result.decision}`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "启动承接计划失败");
    } finally {
      setSaving("");
    }
  }

  async function syncEngagementRunCloseout(engagementRunId: string) {
    setSaving(`engagement-run-sync:${engagementRunId}`);
    setError("");
    setNotice("");
    try {
      const result = await syncTaskSystemEngagementRunCloseout(engagementRunId);
      await loadEngagementRuns();
      setNotice(result.changed ? "承接运行已同步验收结果。" : `承接运行无需同步：${result.reason || "未变化"}`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "同步承接运行失败");
    } finally {
      setSaving("");
    }
  }

  function createEnvironmentDraft() {
    const index = environmentItems.length + 1;
    const environmentId = `env.custom.workspace_${String(index).padStart(2, "0")}`;
    setSelectedEnvironmentId("");
    setEnvironmentDraft({
      ...defaultEnvironmentDraft(),
      environment_id: environmentId,
      prompt_id: `environment.custom.workspace_${String(index).padStart(2, "0")}.v1`,
      storage_namespace: `custom/workspace_${String(index).padStart(2, "0")}`,
    });
    setTaskSystemLayer("environments");
    setNotice("已创建任务环境草稿。");
  }

  async function saveEnvironmentDraft() {
    const environmentId = environmentDraft.environment_id.trim();
    if (!environmentId.startsWith("env.")) {
      setError("任务环境标识必须以 env. 开头。");
      return;
    }
    setSaving("task-environment");
    setError("");
    setNotice("");
    try {
      if (!environmentGroupOptions.some((item) => item.value === environmentDraft.group_id)) {
        await upsertTaskSystemEnvironmentGroup(
          environmentDraft.group_id,
          environmentGroupPayload(environmentDraft.group_id, consolePayload),
        );
      }
      const payload = await upsertTaskSystemEnvironment(environmentId, environmentPayloadFromDraft(environmentDraft));
      setConsolePayload(payload);
      setSelectedEnvironmentId(environmentId);
      setEditorEnvironmentId((current) => current || environmentId);
      setNotice("任务环境已保存并可被 runtime 装配。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存任务环境失败");
    } finally {
      setSaving("");
    }
  }

  async function removeSelectedEnvironment() {
    const environmentId = selectedEnvironmentItem?.record.environment_id || environmentDraft.environment_id;
    if (!environmentId) return;
    const approved = await confirm({
      title: `删除任务环境「${environmentRecordTitle(environmentId, consolePayload) || environmentId}」`,
      body: "只会删除配置文件中的自定义环境。内置默认环境不会被删除。",
      confirmLabel: "删除环境",
      tone: "warning",
    });
    if (!approved) return;
    setSaving("task-environment-delete");
    setError("");
    setNotice("");
    try {
      const payload = await deleteTaskSystemEnvironment(environmentId);
      setConsolePayload(payload);
      const nextId = payload.task_environment_management?.records?.[0]?.environment_id || "";
      setSelectedEnvironmentId(nextId);
      setEnvironmentDraft(environmentDraftFromItem(taskEnvironmentItem(nextId, payload)));
      setNotice("任务环境配置已删除。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "删除任务环境失败");
    } finally {
      setSaving("");
    }
  }

  async function saveTaskGraphStack(nextPublished?: boolean, nextEditorPublishState?: "draft" | "saved" | "preflight_passed" | "published" | "run_bound" | "archived") {
    const draftDomain = taskLayer === "editor" ? editorDomain : selectedDomain;
    const draftDomainId = draftDomain?.domain_id || taskGraphDraftV2.domain_id || "";
    const draftEnvironmentId = taskGraphEnvironmentId(taskGraphDraftV2)
      || activeEditorEnvironmentId;
    if (!draftDomainId) {
      setError("请先选择任务域，再保存任务图。");
      return;
    }
    if (!draftEnvironmentId) {
      setError("请先选择任务环境，再保存任务图。");
      return;
    }
    setSaving("task-graph");
    setError("");
    setNotice("");
    try {
      const publishIntent = nextPublished === true
        ? "publish"
        : nextEditorPublishState === "published"
          ? "publish"
        : nextEditorPublishState === "run_bound"
          ? "mark_run_bound"
          : nextEditorPublishState === "archived"
            ? "archive"
            : "save_draft";
      const publishCommit = resolveTaskGraphPublishCommit(publishIntent);
      const graphNodes = (taskGraphDraftV2.nodes ?? []).map(normalizeTaskGraphNode);
      const graphEdges = (taskGraphDraftV2.edges ?? []).map(normalizeTaskGraphEdge);
      const effectiveTaskGraphDraftV2: TaskGraphDraftV2 = {
        ...taskGraphDraftV2,
        domain_id: draftDomainId,
        task_id: "",
        nodes: graphNodes,
        edges: graphEdges,
        publish_state: publishCommit.editor_publish_state,
        metadata: {
          ...asRecord(taskGraphDraftV2.metadata),
          ...publishCommit.metadata_patch,
          domain_id: draftDomainId,
          task_environment_id: draftEnvironmentId,
          environment_id: draftEnvironmentId,
          task_id: undefined,
        },
        runtime_policy: {
          ...taskGraphDraftV2.runtime_policy,
          task_environment_id: draftEnvironmentId,
          environment_id: draftEnvironmentId,
        },
        context_policy: {
          ...taskGraphDraftV2.context_policy,
          task_environment_id: draftEnvironmentId,
          environment_id: draftEnvironmentId,
        },
      };
      const taskGraphPayload = buildTaskGraphUpsertPayload({
        taskGraphDraft: effectiveTaskGraphDraftV2,
        domain_id: draftDomainId,
        task_id: "",
        publish_state: publishCommit.backend_publish_state,
      });
      taskGraphPayload.enabled = publishCommit.enabled;
      const payload = await upsertTaskSystemTaskGraph(effectiveTaskGraphDraftV2.graph_id, taskGraphPayload);
      setTaskGraphDraftV2(effectiveTaskGraphDraftV2);
      syncTaskGraphTopology(graphNodes, graphEdges);
      setConsolePayload(payload);
      if (taskLayer === "editor") {
        setEditorTaskGraphId(effectiveTaskGraphDraftV2.graph_id);
      } else {
        setSelectedTaskGraphId(effectiveTaskGraphDraftV2.graph_id);
      }
      try {
        const refreshedStandardView = await getTaskSystemTaskGraphStandardView(effectiveTaskGraphDraftV2.graph_id);
        setTaskGraphStandardViewState(loadedTaskGraphStandardViewState({
          view: refreshedStandardView,
          graphId: effectiveTaskGraphDraftV2.graph_id,
          revisionKey: taskGraphDraftRevisionKey({
            graphId: effectiveTaskGraphDraftV2.graph_id,
            nodes: graphNodes,
            edges: graphEdges,
            metadata: asRecord(effectiveTaskGraphDraftV2.metadata),
          }),
        }));
        setTaskGraphStandardViewError("");
      } catch (viewExc) {
        setTaskGraphStandardViewState(emptyTaskGraphStandardViewState());
        setTaskGraphStandardViewError(viewExc instanceof Error ? viewExc.message : "标准对象视图刷新失败");
      }
      setNotice(nextPublished === true ? "任务图已发布。" : "任务图已保存。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存任务图失败");
    } finally {
      setSaving("");
    }
  }

  async function saveContractSpec(spec: ContractSpec) {
    setSaving("contract-spec");
    setError("");
    setNotice("");
    try {
      const activeDomain = selectedDomain;
      const payloadSpec = activeDomain
        ? {
          ...spec,
          metadata: {
            ...(spec.metadata ?? {}),
            domain_id: activeDomain.domain_id,
          },
        }
        : spec;
      const payload = await upsertTaskSystemContract(payloadSpec.contract_id, payloadSpec);
      setConsolePayload(payload);
      setNotice(`契约“${contractSpecTitle(spec)}”已保存。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存契约失败");
      throw exc;
    } finally {
      setSaving("");
    }
  }

  async function removeContractSpec(contractId: string) {
    setSaving("contract-spec");
    setError("");
    setNotice("");
    try {
      const payload = await deleteTaskSystemContract(contractId);
      setConsolePayload(payload);
      setNotice(`契约“${contractId}”已删除。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "删除契约失败");
      throw exc;
    } finally {
      setSaving("");
    }
  }

  const activeGraphNodes = taskGraphDraftV2.nodes ?? [];
  const activeGraphEdges = taskGraphDraftV2.edges ?? [];
  const taskGraphDraftRevision = taskGraphDraftRevisionKey({
    graphId: taskGraphDraftV2.graph_id,
    nodes: activeGraphNodes,
    edges: activeGraphEdges,
    metadata: asRecord(taskGraphDraftV2.metadata),
  });
  const taskGraphStandardView = taskGraphStandardViewState.view;
  const taskGraphStandardViewStale = taskGraphStandardViewState.stale;
  const selectedGraphNodeId = taskGraphEditorSelection.canonicalNodeId;
  const selectedGraphEdgeId = taskGraphEditorSelection.canonicalEdgeId;
  const setSelectedGraphNodeId = (value: string) => {
    setTaskGraphEditorSelection((current) => value ? selectCanonicalNode(current, value) : { ...current, canonicalNodeId: "" });
  };
  const setSelectedGraphEdgeId = (value: string) => {
    setTaskGraphEditorSelection((current) => value ? selectCanonicalEdge(current, value) : { ...current, canonicalEdgeId: "" });
  };
  useEffect(() => {
    setTaskGraphStandardViewState((current) => markTaskGraphStandardViewStale(current, taskGraphDraftV2.graph_id, taskGraphDraftRevision));
  }, [taskGraphDraftRevision, taskGraphDraftV2.graph_id]);
  const updateTaskGraphPublishState = (nextState: TaskGraphPublishStateV2) => {
    setTaskGraphDraftV2((current) => ({
      ...current,
      metadata: {
        ...asRecord(current.metadata),
        editor_publish_state: nextState,
      },
      publish_state: nextState,
    }));
  };
  const updateTaskGraphDraft = (patch: Partial<TaskGraphDraftV2>) => {
    setTaskGraphDraftV2((current) => {
      const metadataPatch = asRecord(patch.metadata);
      const nextNodes = patch.nodes ? patch.nodes.map(normalizeTaskGraphNode) : current.nodes;
      const nextEdges = patch.edges ? patch.edges.map(normalizeTaskGraphEdge) : current.edges;
      const boundaries = (patch.nodes || patch.edges)
        ? inferTaskGraphBoundaryNodes(nextNodes, nextEdges, {
          fallback_entry_node_id: patch.entry_node_id ?? current.entry_node_id,
          fallback_output_node_id: patch.output_node_id ?? current.output_node_id,
        })
        : null;
      return {
        ...current,
        title: patch.title ?? current.title,
        graph_kind: patch.graph_kind ?? current.graph_kind,
        entry_node_id: patch.entry_node_id ?? boundaries?.entry_node_id ?? current.entry_node_id,
        output_node_id: patch.output_node_id ?? boundaries?.output_node_id ?? current.output_node_id,
        graph_contract_id: patch.graph_contract_id ?? current.graph_contract_id,
        nodes: nextNodes,
        edges: nextEdges,
        metadata: {
          ...asRecord(current.metadata),
          ...metadataPatch,
        },
      };
    });
  };
  const updateTaskGraphMetadata = (patch: Record<string, unknown>) => {
    setTaskGraphDraftV2((current) => ({
      ...current,
      metadata: {
        ...asRecord(current.metadata),
        ...patch,
      },
    }));
  };
  useEffect(() => {
    if (taskLayer !== "editor" || !activeEditorEnvironmentId) return;
    setTaskGraphDraftV2((current) => {
      const metadata = asRecord(current.metadata);
      if (
        metadata.task_environment_id === activeEditorEnvironmentId
        && metadata.environment_id === activeEditorEnvironmentId
        && current.runtime_policy.task_environment_id === activeEditorEnvironmentId
        && current.context_policy.task_environment_id === activeEditorEnvironmentId
      ) {
        return current;
      }
      return {
        ...current,
        context_policy: {
          ...current.context_policy,
          task_environment_id: activeEditorEnvironmentId,
          environment_id: activeEditorEnvironmentId,
        },
        runtime_policy: {
          ...current.runtime_policy,
          task_environment_id: activeEditorEnvironmentId,
          environment_id: activeEditorEnvironmentId,
        },
        metadata: {
          ...metadata,
          task_environment_id: activeEditorEnvironmentId,
          environment_id: activeEditorEnvironmentId,
        },
      };
    });
  }, [activeEditorEnvironmentId, taskLayer]);
  useEffect(() => {
    if (taskSystemLayer !== "environments") return;
    setEnvironmentDraft(environmentDraftFromItem(selectedEnvironmentItem));
  }, [selectedEnvironmentItem, taskSystemLayer]);
  const updateTaskGraphRuntimePolicy = (patch: Partial<TaskGraphDraftV2["runtime_policy"]>) => {
    setTaskGraphDraftV2((current) => ({
      ...current,
      runtime_policy: {
        ...current.runtime_policy,
        ...patch,
      },
      metadata: {
        ...asRecord(current.metadata),
        runtime_policy: {
          ...asRecord(asRecord(current.metadata).runtime_policy),
          ...patch,
        },
      },
    }));
  };
  const selectedGraphNode = activeGraphNodes.find((node) => String(node.node_id ?? "") === selectedGraphNodeId) ?? null;
  const selectedGraphEdge = activeGraphEdges.find((edge, index) => graphEdgeId(edge, index) === selectedGraphEdgeId) ?? null;
  const boundTaskGraphTaskIds = new Set(activeGraphNodes.map((node) => graphNodeTaskId(node)).filter(Boolean));
  const graphContextDomain = taskLayer === "editor" ? editorDomain : selectedDomain;
  const graphContextDomainTasks = taskLayer === "editor" ? editorEnvironmentTasks : selectedDomainTasks;
  const graphContextDomainId = graphContextDomain?.domain_id || taskGraphDraftV2.domain_id || "";
  const draftGraphSpec = deriveTaskGraphSpec(
    taskGraphDraftV2.graph_id || "",
    graphContextDomainId,
    activeGraphNodes,
    activeGraphEdges,
  );
  const editorGraphSpec: TaskGraphDraftTopologySpec = {
    ...draftGraphSpec,
  };
  editorGraphSpec.valid = editorGraphSpec.issues.length === 0 && draftGraphSpec.valid;
  if (activeTaskGraphDetailError) {
    editorGraphSpec.issues = [
      ...editorGraphSpec.issues,
      {
        severity: "warning",
        code: "task_graph_detail_load_failed",
        message: activeTaskGraphDetailError,
      },
    ];
    editorGraphSpec.valid = false;
  }
  const editorIssueCount = editorGraphSpec.issues.length;
  const editorValid = editorGraphSpec.valid;
  const editorPublished = taskGraphDraftV2.publish_state === "published" || taskGraphDraftV2.publish_state === "run_bound";
  const topologyDirty = false;
  const runtimeBoundTaskRunId = String(taskGraphMonitorBinding?.task_run_id ?? "").trim();
  const runtimeRunsForSelectedGraph = useMemo(() => {
    const graphId = String(selectedTaskGraph?.graph_id ?? "").trim();
    if (!graphId) return runtimeTaskRuns;
    const matched = runtimeTaskRuns.filter((item) => runtimeTaskRunGraphId(item) === graphId);
    return matched.length ? matched : runtimeTaskRuns;
  }, [runtimeTaskRuns, selectedTaskGraph?.graph_id]);
  const selectedRuntimeSummary = runtimeTaskRuns.find((item) => getRuntimeTaskRunId(item) === runtimeTaskRunId.trim()) ?? null;
  const selectedRuntimeRunRecord = dictOf(selectedRuntimeSummary?.task_run);
  const runtimeMonitorForSelectedRun = runtimeTaskRunId.trim()
    && taskGraphLiveMonitor
    && recordFieldText(dictOf(taskGraphLiveMonitor.task_run), ["task_run_id", "id", "run_id"], "") === runtimeTaskRunId.trim()
    ? taskGraphLiveMonitor
    : runtimeLiveMonitor;
  const runtimeArtifactStatusCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const artifact of runtimeArtifactOverview?.artifacts ?? []) {
      const status = String(artifact.status || "unknown");
      counts[status] = (counts[status] ?? 0) + 1;
    }
    return counts;
  }, [runtimeArtifactOverview?.artifacts]);
  const runtimePageActive = activeWorkspaceView === "task-system" && taskLayer === "management" && taskSystemLayer === "runtime";
  const agentRuntimePhasePageActive = activeWorkspaceView === "task-system" && taskLayer === "management" && taskSystemLayer === "agent-runtime-phase";
  const resourceAuthorityPageActive = activeWorkspaceView === "task-system" && taskLayer === "management" && taskSystemLayer === "resource-authority";
  const loadRuntimeTaskRuns = useCallback(async () => {
    if (!currentSessionId) {
      setRuntimeTaskRuns([]);
      return;
    }
    try {
      const response = await listOrchestrationHarnessTaskRuns(currentSessionId);
      setRuntimeTaskRuns(response.task_runs ?? []);
    } catch (exc) {
      setRuntimeError(exc instanceof Error ? `运行实例列表加载失败：${exc.message}` : "运行实例列表加载失败");
    }
  }, [currentSessionId]);
  const loadRuntimeStores = useCallback(async () => {
    const taskRunId = runtimeTaskRunId.trim();
    setRuntimeLoading(true);
    setRuntimeError("");
    try {
      const [formal, artifacts, monitor] = await Promise.all([
        getFormalMemoryOverview({ task_run_id: taskRunId, limit: 80 }),
        getArtifactRepositoryOverview({ task_run_id: taskRunId, limit: 80 }),
        taskRunId ? getOrchestrationHarnessTaskRunLiveMonitor(taskRunId).catch(() => null) : Promise.resolve(null),
      ]);
      setRuntimeFormalOverview(formal);
      setRuntimeArtifactOverview(artifacts);
      setRuntimeLiveMonitor(monitor);
    } catch (exc) {
      setRuntimeError(exc instanceof Error ? exc.message : "运行库加载失败");
    } finally {
      setRuntimeLoading(false);
    }
  }, [runtimeTaskRunId]);
  const loadRuntimeResourceInventory = useCallback(async () => {
    try {
      setRuntimeResourceInventory(await getOrchestrationResourceInventory());
    } catch (exc) {
      setRuntimeError(exc instanceof Error ? `资源权威地图加载失败：${exc.message}` : "资源权威地图加载失败");
    }
  }, []);
  const refreshRuntimeManagement = useCallback(async () => {
    await Promise.all([
      loadRuntimeTaskRuns(),
      loadRuntimeStores(),
    ]);
  }, [loadRuntimeStores, loadRuntimeTaskRuns]);
  const refreshAgentRuntimePhaseMonitor = useCallback(async () => {
    await Promise.all([
      loadRuntimeTaskRuns(),
      loadRuntimeStores(),
    ]);
  }, [loadRuntimeStores, loadRuntimeTaskRuns]);
  const refreshResourceAuthority = useCallback(async () => {
    setRuntimeLoading(true);
    setRuntimeError("");
    try {
      await loadRuntimeResourceInventory();
    } finally {
      setRuntimeLoading(false);
    }
  }, [loadRuntimeResourceInventory]);

  useEffect(() => {
    if (!runtimePageActive && !agentRuntimePhasePageActive) return;
    void loadRuntimeTaskRuns();
  }, [agentRuntimePhasePageActive, loadRuntimeTaskRuns, runtimePageActive]);

  useEffect(() => {
    if ((!runtimePageActive && !agentRuntimePhasePageActive) || runtimeDefaultedRef.current || runtimeTaskRunId.trim()) return;
    const nextTaskRunId = runtimeBoundTaskRunId
      || getRuntimeTaskRunId(runtimeRunsForSelectedGraph[0])
      || getRuntimeTaskRunId(runtimeTaskRuns[0]);
    if (!nextTaskRunId) return;
    runtimeDefaultedRef.current = true;
    setRuntimeTaskRunId(nextTaskRunId);
  }, [agentRuntimePhasePageActive, runtimeBoundTaskRunId, runtimePageActive, runtimeRunsForSelectedGraph, runtimeTaskRunId, runtimeTaskRuns]);

  useEffect(() => {
    if (!runtimePageActive && !agentRuntimePhasePageActive) return;
    void loadRuntimeStores();
  }, [agentRuntimePhasePageActive, loadRuntimeStores, runtimePageActive]);

  useEffect(() => {
    if (!resourceAuthorityPageActive) return;
    void refreshResourceAuthority();
  }, [refreshResourceAuthority, resourceAuthorityPageActive]);

  const taskSystemLayerItems: Array<LayerNavItem<TaskSystemLayer>> = [
    {
      value: "domains",
      label: "任务域",
      meta: selectedDomain?.title || `${visibleDomains.length} 个任务域`,
      detail: "分类与入口",
    },
    {
      value: "tasks",
      label: "承接计划",
      meta: selectedEngagementPlan?.title || `${engagementPlans.length} 个计划`,
      detail: "启动契约",
    },
    {
      value: "graphs",
      label: "任务图",
      meta: `${taskGraphs.length} 张图`,
      detail: "多 Agent 流程",
    },
    {
      value: "environments",
      label: "任务环境",
      meta: selectedEnvironmentItem?.record.title || `${environmentItems.length} 个环境`,
      detail: "系统资源边界",
    },
    {
      value: "contracts",
      label: "契约库",
      meta: `${domainContractSpecs.length} 个契约`,
      detail: "输入输出边界",
    },
    {
      value: "resource-authority",
      label: "资源权威",
      meta: `${runtimeResourceInventory?.items?.length ?? 0} 层资源`,
      detail: "资源归属",
    },
    {
      value: "agent-runtime-phase",
      label: "运行阶段",
      meta: runtimeTaskRunId.trim() || "未选择 TaskRun",
      detail: "AgentRuntime",
    },
    {
      value: "orchestration",
      label: "编排资源",
      meta: `${orchestrationAgentCatalog?.agents?.length ?? 0} Agent / ${projectionCards.length} Projection`,
      detail: "Agent 与 Projection",
    },
    {
      value: "runtime",
      label: "运行管理",
      meta: activeTaskGraph?.graph_id || "未绑定运行",
      detail: "监控与产物",
    },
  ];
  const primaryTaskSystemLayerItems = taskSystemLayerItems.filter((item) => ["domains", "tasks", "graphs", "environments"].includes(item.value));
  const supportingTaskSystemLayerItems = taskSystemLayerItems.filter((item) => ["contracts", "resource-authority", "agent-runtime-phase", "orchestration", "runtime"].includes(item.value));
  const engagementPlanPanelItems: Array<LayerNavItem<EngagementPlanPanel>> = [
    {
      value: engagementPlanPanel,
      label: "契约配置",
      meta: selectedEngagementPlan ? engagementPlanDraft.plan_id : "未选择计划",
      detail: "环境、模式、策略与输入输出契约",
    },
  ];
  const contractPanelItems: Array<LayerNavItem<ContractPanel>> = [
    {
      value: "library",
      label: "契约库",
      meta: `${domainContractSpecs.length} 个契约`,
      detail: "管理可被任务图、节点和边引用的契约主数据",
    },
    {
      value: "templates",
      label: "契约模板",
      meta: "域级模板",
      detail: "模板只作为契约草案入口，按任务域隔离管理",
    },
  ];
  const domainContextSlot = (
    <div className="task-system-project-selector">
      <div>
        <span>项目</span>
        <strong>{selectedDomain?.title || "未选择任务域"}</strong>
      </div>
      <TaskGraphChromeSelect
        emptyLabel="暂无任务域"
        label="任务域"
        onChange={(domainId) => {
          const domain = visibleDomains.find((item) => item.domain_id === domainId);
          setSelectedDomainId(domainId);
          setEditorDomainId(domainId);
          setSelectedTaskId(domain?.tasks[0]?.task_id || "");
          const nextGraphs = sortTaskGraphsForWorkbench((consolePayload?.task_graph_management?.task_graphs ?? []).filter((item) => String(item.domain_id ?? "").trim() === domainId));
          setSelectedTaskGraphId(recommendedTaskGraphId(nextGraphs));
          setEditingDomainName(false);
        }}
        options={visibleDomains.map((domain) => ({ value: domain.domain_id, label: domain.title }))}
        placeholder="选择任务域"
        value={selectedDomain?.domain_id || ""}
      />
      <small>{selectedDomain?.domain_id || "未选择任务域"}</small>
      <ToolbarButton onClick={createDomainDraft}><Plus size={15} />新项目</ToolbarButton>
    </div>
  );
  const managementLayerSlot = (
    <div className="task-system-object-table" aria-label="任务系统对象目录">
      <div className="task-system-object-table__head" aria-hidden="true">
        <span>对象</span>
        <span>当前记录</span>
        <span>状态</span>
      </div>
      {[...primaryTaskSystemLayerItems, ...supportingTaskSystemLayerItems].map((item) => {
        const active = taskSystemLayer === item.value;
        const scope = primaryTaskSystemLayerItems.some((entry) => entry.value === item.value) ? "主对象" : "支撑对象";
        return (
          <button
            aria-current={active ? "page" : undefined}
            className={active ? "task-system-object-row task-system-object-row--active" : "task-system-object-row"}
            key={item.value}
            onClick={() => selectTaskSystemLayer(item.value)}
            type="button"
          >
            <strong><span className="task-system-object-row__scope">{scope}</span>{item.label}</strong>
            <span className="task-system-object-row__meta">{item.meta}</span>
            <em>{active ? "当前" : "可配置"}</em>
          </button>
        );
      })}
    </div>
  );
  function openTaskGraphEditor(graphId = selectedTaskGraph?.graph_id || "") {
    const nextDomain = selectedDomain ?? editorDomain;
    const explicitGraph = allTaskGraphs.find((item) => String(item.graph_id ?? "") === graphId) ?? null;
    const nextEnvironmentId = taskGraphEnvironmentId(explicitGraph as TaskGraphRecord)
      || taskEnvironmentId(nextDomain?.tasks[0] ?? tasks[0] ?? emptySpecificTaskRecord())
      || editorTaskEnvironmentOptions[0]?.value
      || "";
    const environmentGraphs = nextEnvironmentId
      ? sortTaskGraphsForWorkbench(allTaskGraphs.filter((item) => taskGraphEnvironmentId(item) === nextEnvironmentId))
      : [];
    const nextGraph = explicitGraph
      ?? environmentGraphs.find((item) => item.graph_id === recommendedTaskGraphId(environmentGraphs))
      ?? null;
    setEditorDomainId(nextDomain?.domain_id || "");
    setEditorEnvironmentId(nextEnvironmentId);
    setEditorTaskGraphId(nextGraph?.graph_id || "");
    setSelectedTaskGraphId(nextGraph?.graph_id || graphId || "");
    setSelectedGraphNodeId("");
    setSelectedGraphEdgeId("");
    setLinkingFromNodeId("");
    setTaskLayer("editor");
    setTaskSystemLayer("graphs");
  }

  function enterManagementLayer() {
    setTaskLayer("management");
  }

  function selectTaskSystemLayer(layer: TaskSystemLayer) {
    setTaskSystemLayer(layer);
    setTaskLayer("management");
  }

  const editorWorkspaceSlot = (
    <>
      <div className="task-graph-editor-chrome__controls">
        <TaskGraphChromeSelect
          emptyLabel={editorTaskEnvironmentOptions.length ? "选择任务环境" : "暂无任务环境"}
          label="任务环境"
          onChange={setEditorEnvironmentId}
          options={editorTaskEnvironmentOptions}
          placeholder="选择任务环境"
          value={activeEditorEnvironmentId}
        />
        <TaskGraphChromeSelect
          disabled={!editorDomain}
          emptyLabel={!editorDomain ? "先选择任务域" : editorGraphSelectOptions.length ? "选择图草稿" : "当前任务域暂无图"}
          label="图草稿"
          onChange={(nextValue) => {
            setEditorTaskGraphId(nextValue);
            setSelectedTaskGraphId(nextValue);
            setSelectedGraphNodeId("");
            setSelectedGraphEdgeId("");
            setLinkingFromNodeId("");
          }}
          options={editorGraphSelectOptions}
          placeholder="选择图草稿"
          value={editorTaskGraphId}
        />
      </div>
      <div className="task-graph-editor-chrome__status task-graph-editor-chrome__status--context">
        <span className={topologyDirty ? "boundary-status boundary-status--warn" : "boundary-status"}>{topologyDirty ? "拓扑未同步" : "拓扑已同步"}</span>
        <span className="boundary-status">{environmentRecordTitle(activeEditorEnvironmentId, consolePayload) || taskEnvironmentTitle(activeEditorEnvironmentId)}</span>
        {taskEnvironmentStorageLabel(activeEditorEnvironmentId, consolePayload) ? (
          <span className="boundary-status">{taskEnvironmentStorageLabel(activeEditorEnvironmentId, consolePayload)}</span>
        ) : null}
      </div>
      <div className="task-graph-editor-chrome__actions task-graph-editor-chrome__actions--minimal">
        <ToolbarButton onClick={() => selectTaskSystemLayer("graphs")}>返回任务图库</ToolbarButton>
        <ToolbarButton disabled={saving === "task-graph-create"} onClick={() => void createTaskGraphDraft()}><Network size={15} />新图草稿</ToolbarButton>
      </div>
    </>
  );

  const taskGraphEditorWorkbench = (
    <TaskGraphWorkbench
      addTaskGraphNode={addTaskGraphNode}
      addTaskGraphRoleNode={addTaskGraphRoleNode}
      addTaskGraphSuccessorNode={addTaskGraphSuccessorNode}
      addTaskGraphTaskNode={addTaskGraphTaskNode}
      a2aCatalog={a2aCatalog}
      agentGroupOptions={editorAgentGroupOptions}
      applyTaskGraphTemplate={applyTaskGraphTemplate}
      boundTaskGraphTaskIds={boundTaskGraphTaskIds}
      contractSpecs={editorContractSpecs}
      taskGraphs={editorTaskGraphs}
      domainTaskOptions={editorDomainTaskOptions}
      duplicateTaskGraphDraft={duplicateTaskGraphDraft}
      editorIssueCount={editorIssueCount}
      editorPublished={editorPublished}
      editorValid={editorValid}
      activeGraphEdges={activeGraphEdges}
      activeGraphNodes={activeGraphNodes}
      handleTopologyNodeClick={handleTopologyNodeClick}
      linkingFromNodeId={linkingFromNodeId}
      taskGraphEditorSelection={taskGraphEditorSelection}
      setTaskGraphEditorSelection={setTaskGraphEditorSelection}
      removeTaskGraphEdge={removeTaskGraphEdge}
      removeTaskGraphNode={removeTaskGraphNode}
      reverseTaskGraphEdge={reverseTaskGraphEdge}
      saveTaskGraphStack={saveTaskGraphStack}
      saving={saving}
      selectedTaskGraph={editorSelectedTaskGraph}
      selectedTaskGraphId={editorTaskGraphId}
      selectedDomain={editorDomain}
      selectedDomainTasks={editorEnvironmentTasks}
      selectedGraphEdge={selectedGraphEdge}
      selectedGraphEdgeId={selectedGraphEdgeId}
      selectedGraphNode={selectedGraphNode}
      selectedGraphNodeId={selectedGraphNodeId}
      setLinkingFromNodeId={setLinkingFromNodeId}
      setSelectedTaskGraphId={setEditorTaskGraphId}
      setSelectedGraphEdgeId={setSelectedGraphEdgeId}
      setSelectedGraphNodeId={setSelectedGraphNodeId}
      taskGraphDirty={topologyDirty}
      taskGraphDraftV2={taskGraphDraftV2}
      workspaceSlot={editorWorkspaceSlot}
      taskGraphStandardView={taskGraphStandardView}
      taskGraphStandardViewStale={taskGraphStandardViewStale}
      taskGraphStandardViewError={taskGraphStandardViewError}
      taskGraphStandardViewLoading={taskGraphStandardViewLoading}
      refreshTaskGraphStandardView={refreshTaskGraphStandardView}
      updateTaskGraphDraft={updateTaskGraphDraft}
      updateTaskGraphEdge={updateTaskGraphEdge}
      updateTaskGraphMetadata={updateTaskGraphMetadata}
      updateTaskGraphNode={updateTaskGraphNode}
      updateTaskGraphPublishState={updateTaskGraphPublishState}
      updateTaskGraphRuntimePolicy={updateTaskGraphRuntimePolicy}
      orchestrationAgentCatalog={orchestrationAgentCatalog}
    />
  );

  if (taskLayer === "editor") {
    return (
      <section className="workspace-view task-graph-editor-page" aria-label="任务图编辑器">
        {error ? <div className="boundary-notice boundary-notice--error">{error}</div> : null}
        {notice ? <div className="boundary-notice">{notice}</div> : null}
        {taskGraphEditorWorkbench}
      </section>
    );
  }

  return (
    <TaskSystemShell
      activeLayer={taskSystemLayer}
      error={error}
      contextSlot={domainContextSlot}
      layerSlot={managementLayerSlot}
      mode="management"
      navItems={taskSystemLayerItems}
      notice={notice}
      onBackToGraphs={() => selectTaskSystemLayer("graphs")}
      onRefresh={() => void load()}
      onSelectLayer={(layer) => {
        void load();
        selectTaskSystemLayer(layer);
      }}
      path={selectedDomain?.title || "请选择任务域"}
      title="任务系统"
    >

      <section className={`task-management-stage task-management-stage--${taskSystemLayer}`}>
          {taskSystemLayer === "domains" ? (
            <TaskDomainLibraryPage
              contractCount={domainContractSpecs.length}
              domainDraft={domainDraft}
              editingDomainName={editingDomainName}
              entryDraft={entryDraft}
              graphCount={taskGraphs.length}
              loading={loading}
              onDeleteDomain={() => selectedDomain ? void deleteDomain(selectedDomain) : undefined}
              onSaveDomain={() => void saveDomain()}
              onSaveEntry={() => void saveEntry()}
              onSelectLayer={selectTaskSystemLayer}
              onSetDomainDraft={setDomainDraft}
              onSetEditingDomainName={setEditingDomainName}
              onSetEntryDraft={setEntryDraft}
              projectionCount={domainProjectionCards.length}
              projectionLoading={projectionLoading}
              saving={saving}
              selectedDomain={selectedDomain}
              workflowOptions={workflowOptions}
            />
          ) : null}

          {taskSystemLayer === "tasks" ? (
            <EngagementPlanLibraryPage
              engagementPlanDraft={engagementPlanDraft}
              engagementPlanJsonError={jsonError(engagementPlanJsonTextState, "承接计划契约 JSON", "object")}
              engagementPlanJsonText={engagementPlanJsonTextState}
              engagementPlans={engagementPlans}
              environmentOptions={engagementEnvironmentOptions}
              onCreatePlan={createEngagementPlanDraft}
              onDeletePlan={() => void deleteEngagementPlanDraft()}
              onSavePlan={() => void saveEngagementPlanDraft()}
              onSelectPlan={setSelectedEngagementPlanId}
              onSetEngagementPlanDraft={setEngagementPlanDraft}
              onSetEngagementPlanJsonText={setEngagementPlanJsonTextState}
              onStartPlan={() => void startEngagementPlanDraft()}
              onSyncRunCloseout={(engagementRunId) => void syncEngagementRunCloseout(engagementRunId)}
              planRuns={selectedEngagementPlanRuns}
              runEvents={engagementEvents}
              saving={saving}
              selectedEngagementPlan={selectedEngagementPlan}
              selectedEngagementPlanId={selectedEngagementPlanId}
              taskDetailPanelItems={engagementPlanPanelItems}
            />
          ) : null}

          {taskSystemLayer === "contracts" ? (
            <TaskContractLibraryPage
              contractManagement={contractManagement}
              contractPanel={contractPanel}
              contractPanelItems={contractPanelItems}
              domainContractSpecs={domainContractSpecs}
              onDeleteContract={removeContractSpec}
              onOpenWorkbench={() => openTaskGraphEditor(selectedTaskGraph?.graph_id)}
              onSaveContract={saveContractSpec}
              onSelectPanel={setContractPanel}
              saving={saving}
              selectedTaskGraphId={selectedTaskGraph?.graph_id}
            />
          ) : null}

          {taskSystemLayer === "graphs" ? (
            <TaskGraphLibraryPage
              activeGraphEdges={activeGraphEdges}
              activeGraphNodes={activeGraphNodes}
              editorIssueCount={editorIssueCount}
              editorPublished={editorPublished}
              editorValid={editorValid}
              onCreateGraph={() => void createTaskGraphDraft()}
              onDuplicateGraph={() => void duplicateTaskGraphDraft()}
              onOpenWorkbench={openTaskGraphEditor}
              onSaveGraph={() => void saveTaskGraphStack(false)}
              onSelectGraph={setSelectedTaskGraphId}
              saving={saving}
              selectedDomain={selectedDomain}
              selectedTaskGraph={selectedTaskGraph}
              selectedTaskGraphId={selectedTaskGraphId}
              standardViewError={taskGraphStandardViewError}
              taskGraphDraft={taskGraphDraftV2}
              taskGraphs={taskGraphs}
            />
          ) : null}

          {taskSystemLayer === "environments" ? (
            <TaskEnvironmentLibraryPage
              draft={environmentDraft}
              environmentItems={environmentItems}
              groupOptions={environmentGroupOptions}
              onCreate={createEnvironmentDraft}
              onDelete={() => void removeSelectedEnvironment()}
              onSave={() => void saveEnvironmentDraft()}
              onSelectEnvironment={(environmentId) => {
                setSelectedEnvironmentId(environmentId);
                setEnvironmentDraft(environmentDraftFromItem(taskEnvironmentItem(environmentId, consolePayload)));
              }}
              onSetDraft={setEnvironmentDraft}
              saving={saving}
              selectedEnvironmentId={selectedEnvironmentItem?.record.environment_id || ""}
            />
          ) : null}

          {taskSystemLayer === "orchestration" ? (
            <TaskOrchestrationResourceLibraryPage
              onOpenOrchestration={openOrchestrationControl}
              onOpenWorkbench={() => openTaskGraphEditor(selectedTaskGraph?.graph_id)}
              orchestrationAgentCatalog={orchestrationAgentCatalog}
              projectionCards={projectionCards}
              selectedTaskGraphId={selectedTaskGraph?.graph_id}
            />
          ) : null}

          {taskSystemLayer === "resource-authority" ? (
            <ResourceAuthorityMapPage
              inventory={runtimeResourceInventory}
              loading={runtimeLoading}
              onRefresh={() => void refreshResourceAuthority()}
              selectedTaskGraphId={selectedTaskGraph?.graph_id}
            />
          ) : null}

          {taskSystemLayer === "agent-runtime-phase" ? (
            <AgentRuntimePhaseMonitorPage
              monitorForSelectedRun={runtimeMonitorForSelectedRun || null}
              onRefresh={() => void refreshAgentRuntimePhaseMonitor()}
              onTaskRunIdChange={(taskRunId) => {
                runtimeDefaultedRef.current = true;
                setRuntimeTaskRunId(taskRunId);
              }}
              runtimeLoading={runtimeLoading}
              runtimeRunsForSelectedGraph={runtimeRunsForSelectedGraph}
              runtimeTaskRunId={runtimeTaskRunId}
              selectedRuntimeSummary={selectedRuntimeSummary}
            />
          ) : null}

          {taskSystemLayer === "runtime" ? (
            <TaskRuntimeLibraryPage
              artifactOverview={runtimeArtifactOverview}
              artifactStatusCounts={runtimeArtifactStatusCounts}
              formalOverview={runtimeFormalOverview}
              monitorForSelectedRun={runtimeMonitorForSelectedRun || null}
              onOpenMonitor={() => setTaskGraphRunInteractionOpen(true)}
              onOpenWorkbench={() => openTaskGraphEditor(selectedTaskGraph?.graph_id)}
              onRefresh={() => void refreshRuntimeManagement()}
              onTaskRunIdChange={(taskRunId) => {
                runtimeDefaultedRef.current = true;
                setRuntimeTaskRunId(taskRunId);
              }}
              runtimeBoundTaskRunId={runtimeBoundTaskRunId}
              runtimeError={runtimeError}
              runtimeLoading={runtimeLoading}
              runtimeRunsForSelectedGraph={runtimeRunsForSelectedGraph}
              runtimeTaskRunId={runtimeTaskRunId}
              selectedDomain={selectedDomain}
              selectedRuntimeRunRecord={selectedRuntimeRunRecord}
              selectedRuntimeSummary={selectedRuntimeSummary}
              selectedTaskGraph={selectedTaskGraph}
              taskGraphDraft={taskGraphDraftV2}
            />
          ) : null}
      </section>
    </TaskSystemShell>
  );
}








