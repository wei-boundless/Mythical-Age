"use client";

import { GitBranch, Link2, Plus, Save, Trash2, Unlink2 } from "lucide-react";

import {
  TaskSystemToolbarButton,
} from "@/components/workspace/views/task-system/TaskSystemWorkbenchUi";
import { dictOf, parseJsonObject, splitList } from "@/components/workspace/views/task-system/managementPrimitives";
import type {
  TaskAssignmentUpsertPayload,
  TaskEnvironmentGroupUpsertPayload,
  TaskEnvironmentKindTemplate,
  TaskEnvironmentUpsertPayload,
  TaskSystemOverview,
} from "@/lib/api";

import {
  EnvironmentGraphInventoryPage,
  EnvironmentLoadoutPage,
  EnvironmentPromptPage,
  EnvironmentTaskInventoryPage,
  EnvironmentTypePage,
} from "./EnvironmentPages";
import {
  taskEnvironmentDisplayTitle,
  taskEnvironmentPurpose,
  taskEnvironmentScope,
  taskEnvironmentScopeLabel,
  type EnvironmentScope,
} from "./environmentPresentation";

export type EnvironmentSubpage = "types" | "loadout" | "prompts" | "tasks" | "graphs";

export type EnvironmentDraft = {
  environment_id: string;
  title: string;
  description: string;
  group_id: string;
  environment_kind: string;
  enabled: boolean;
  prompt_id: string;
  prompt_content: string;
  storage_namespace: string;
  workspace_policy: string;
  project_file_policy: string;
  material_mount_policy: string;
  external_service_policy: string;
  browser_environment_policy: string;
  mcp_environment_policy: string;
  file_profile_refs_text: string;
  required_repository_kinds_text: string;
  environment_memory_refs_text: string;
  project_knowledge_refs_text: string;
  shared_context_refs_text: string;
  retrieval_index_refs_text: string;
  file_management_text: string;
  resource_space_text: string;
  memory_space_text: string;
  sandbox_policy_text: string;
  execution_policy_text: string;
  artifact_policy_text: string;
  risk_policy_text: string;
  observability_policy_text: string;
  lifecycle_policy_text: string;
  metadata_text: string;
  spec_metadata_text: string;
};

export type TaskEnvironmentManagement = NonNullable<TaskSystemOverview["task_environment_management"]>;
export type TaskEnvironmentItem = TaskEnvironmentManagement["environments"][number];

type EnvironmentBinding = {
  task_environment_id?: string;
  environment_label?: string;
} | null | undefined;

function listText(value: unknown) {
  return Array.isArray(value) ? value.map((item) => String(item)).join("\n") : "";
}

function recordFieldString(record: Record<string, unknown> | null | undefined, key: string, fallback = "") {
  const value = record?.[key];
  if (value === null || value === undefined || Array.isArray(value) || typeof value === "object") return fallback;
  return String(value || fallback);
}

export function defaultEnvironmentDraft(): EnvironmentDraft {
  return {
    environment_id: "env.custom.workspace",
    title: "自定义任务环境",
    description: "",
    group_id: "environment_group.general",
    environment_kind: "custom",
    enabled: true,
    prompt_id: "environment.custom.workspace",
    prompt_content: [
      "你正在一个自定义任务环境中执行任务。",
      "你只能使用当前环境装载的文件 Profile、仓库资源、记忆、知识库、检索索引和产物空间。",
      "当任务需要超出环境边界的资源或权限时，你必须停止并说明缺少的资源或权限。",
    ].join("\n"),
    storage_namespace: "custom/workspace",
    workspace_policy: "read_mostly",
    project_file_policy: "read_only",
    material_mount_policy: "none",
    external_service_policy: "none",
    browser_environment_policy: "none",
    mcp_environment_policy: "none",
    file_profile_refs_text: "file_profile.general_workspace",
    required_repository_kinds_text: "conversation_artifacts",
    environment_memory_refs_text: "",
    project_knowledge_refs_text: "",
    shared_context_refs_text: "",
    retrieval_index_refs_text: "",
    file_management_text: JSON.stringify({
      canonical_write_policy: "commit_gate_required",
      artifact_projection_policy: "file_profile_projection",
      memory_projection_policy: "file_profile_projection",
      constraints: {},
    }, null, 2),
    resource_space_text: JSON.stringify({
      storage_root_policy: "environment_scoped",
      runtime_state_root_policy: "environment_scoped_runtime_state",
      artifact_storage_policy: "environment_scoped_artifacts",
      cache_storage_policy: "environment_scoped_cache",
      managed_file_environment_policy: "file_management_required",
      artifact_root_policy: "file_management_projection",
    }, null, 2),
    memory_space_text: JSON.stringify({
      read_policy: "file_profile_projection",
      write_policy: "file_profile_projection",
      projection_policy: "from_file_management",
    }, null, 2),
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
    observability_policy_text: "{}",
    lifecycle_policy_text: "{}",
    metadata_text: "{}",
    spec_metadata_text: "{}",
  };
}

export function environmentDraftFromItem(item: TaskEnvironmentItem | null | undefined): EnvironmentDraft {
  if (!item) return defaultEnvironmentDraft();
  const record = item.record ?? {};
  const spec = dictOf(item.spec);
  const resourceSpace = dictOf(item.resource_space ?? spec.resource_space);
  const fileManagement = dictOf(item.file_management ?? spec.file_management);
  const memorySpace = dictOf(item.memory_space ?? spec.memory_space);
  const prompts = Array.isArray(item.environment_prompts) ? item.environment_prompts : [];
  const firstPrompt = dictOf(prompts[0]);
  return {
    environment_id: String(record.environment_id || ""),
    title: taskEnvironmentDisplayTitle(item),
    description: taskEnvironmentPurpose(item),
    group_id: String(record.group_id || "environment_group.general"),
    environment_kind: String(record.environment_kind || "custom"),
    enabled: record.enabled !== false,
    prompt_id: String(firstPrompt.prompt_id || `environment.${String(record.environment_id || "custom").replace(/^env\./, "")}`),
    prompt_content: String(firstPrompt.content || ""),
    storage_namespace: String(resourceSpace.storage_namespace || ""),
    workspace_policy: recordFieldString(resourceSpace, "workspace_policy"),
    project_file_policy: recordFieldString(resourceSpace, "project_file_policy"),
    material_mount_policy: recordFieldString(resourceSpace, "material_mount_policy"),
    external_service_policy: recordFieldString(resourceSpace, "external_service_policy"),
    browser_environment_policy: recordFieldString(resourceSpace, "browser_environment_policy"),
    mcp_environment_policy: recordFieldString(resourceSpace, "mcp_environment_policy"),
    file_profile_refs_text: listText(fileManagement.file_profile_refs),
    required_repository_kinds_text: listText(fileManagement.required_repository_kinds),
    environment_memory_refs_text: listText(memorySpace.environment_memory_refs),
    project_knowledge_refs_text: listText(memorySpace.project_knowledge_refs),
    shared_context_refs_text: listText(memorySpace.shared_context_refs),
    retrieval_index_refs_text: listText(memorySpace.retrieval_index_refs),
    file_management_text: JSON.stringify(fileManagement, null, 2),
    resource_space_text: JSON.stringify(resourceSpace, null, 2),
    memory_space_text: JSON.stringify(memorySpace, null, 2),
    sandbox_policy_text: JSON.stringify(item.sandbox_policy ?? spec.sandbox_policy ?? {}, null, 2),
    execution_policy_text: JSON.stringify(item.execution_policy ?? spec.execution_policy ?? {}, null, 2),
    artifact_policy_text: JSON.stringify(item.artifact_policy ?? spec.artifact_policy ?? {}, null, 2),
    risk_policy_text: JSON.stringify(item.risk_policy ?? spec.risk_policy ?? {}, null, 2),
    observability_policy_text: JSON.stringify(item.observability_policy ?? spec.observability_policy ?? {}, null, 2),
    lifecycle_policy_text: JSON.stringify(item.lifecycle_policy ?? spec.lifecycle_policy ?? {}, null, 2),
    metadata_text: JSON.stringify(record.metadata ?? {}, null, 2),
    spec_metadata_text: JSON.stringify(spec.metadata ?? {}, null, 2),
  };
}

export function environmentPayloadFromDraft(draft: EnvironmentDraft): TaskEnvironmentUpsertPayload {
  const environmentId = draft.environment_id.trim();
  const storageNamespace = draft.storage_namespace.trim() || environmentId.replace(/^env\./, "").replace(/\./g, "/");
  const metadata = parseJsonObject(draft.metadata_text, "任务环境 metadata");
  const specMetadata = parseJsonObject(draft.spec_metadata_text, "任务环境 spec metadata");
  const fileManagementBase = parseJsonObject(draft.file_management_text, "文件资源装载策略");
  const resourceSpaceBase = parseJsonObject(draft.resource_space_text, "资源空间策略");
  const memorySpaceBase = parseJsonObject(draft.memory_space_text, "记忆资源装载策略");
  const sandboxPolicy = parseJsonObject(draft.sandbox_policy_text, "沙盒策略");
  const executionPolicy = parseJsonObject(draft.execution_policy_text, "执行策略");
  const artifactPolicy = parseJsonObject(draft.artifact_policy_text, "产物策略");
  const riskPolicy = parseJsonObject(draft.risk_policy_text, "风险策略");
  const observabilityPolicy = parseJsonObject(draft.observability_policy_text, "观测策略");
  const lifecyclePolicy = parseJsonObject(draft.lifecycle_policy_text, "生命周期策略");
  const resourceSpace = {
    ...resourceSpaceBase,
    storage_namespace: storageNamespace,
    ...(draft.workspace_policy.trim() ? { workspace_policy: draft.workspace_policy.trim() } : {}),
    ...(draft.project_file_policy.trim() ? { project_file_policy: draft.project_file_policy.trim() } : {}),
    ...(draft.material_mount_policy.trim() ? { material_mount_policy: draft.material_mount_policy.trim() } : {}),
    ...(draft.external_service_policy.trim() ? { external_service_policy: draft.external_service_policy.trim() } : {}),
    ...(draft.browser_environment_policy.trim() ? { browser_environment_policy: draft.browser_environment_policy.trim() } : {}),
    ...(draft.mcp_environment_policy.trim() ? { mcp_environment_policy: draft.mcp_environment_policy.trim() } : {}),
  };
  const fileManagement = {
    ...fileManagementBase,
    file_profile_refs: splitList(draft.file_profile_refs_text),
    required_repository_kinds: splitList(draft.required_repository_kinds_text),
  };
  const memorySpace = {
    ...memorySpaceBase,
    environment_memory_refs: splitList(draft.environment_memory_refs_text),
    project_knowledge_refs: splitList(draft.project_knowledge_refs_text),
    shared_context_refs: splitList(draft.shared_context_refs_text),
    retrieval_index_refs: splitList(draft.retrieval_index_refs_text),
  };
  return {
    record: {
      environment_id: environmentId,
      title: draft.title.trim() || environmentId,
      description: draft.description.trim(),
      group_id: draft.group_id.trim() || "environment_group.general",
      environment_kind: draft.environment_kind.trim() || "custom",
      enabled: draft.enabled,
      owner: "user",
      default_visibility: "workspace",
      metadata,
    },
    spec: {
      spec_id: `envspec.${environmentId}.configured`,
      environment_id: environmentId,
      environment_prompts: draft.prompt_content.trim()
        ? [{
          prompt_id: draft.prompt_id.trim() || `environment.${environmentId.replace(/^env\./, "")}`,
          content: draft.prompt_content.trim(),
          version: "v1",
          prompt_kind: "environment",
          cache_scope: "static_environment",
        }]
        : [],
      file_management: fileManagement,
      resource_space: resourceSpace,
      memory_space: memorySpace,
      sandbox_policy: sandboxPolicy,
      execution_policy: executionPolicy,
      artifact_policy: artifactPolicy,
      risk_policy: riskPolicy,
      observability_policy: observabilityPolicy,
      lifecycle_policy: lifecyclePolicy,
      metadata: specMetadata,
    },
  };
}

export function environmentGroupPayload(groupId: string, overview: TaskSystemOverview | null): TaskEnvironmentGroupUpsertPayload {
  const group = overview?.task_environment_management?.groups?.find((item) => item.group_id === groupId);
  return {
    group_id: groupId,
    title: group?.title || groupId.replace(/^environment_group\./, ""),
    description: group?.description || "",
    enabled: group?.enabled ?? true,
  };
}

export function taskAssignmentPayloadFromRecord(record: Record<string, unknown>, taskEnvironmentId: string): TaskAssignmentUpsertPayload {
  const taskId = String(record.task_id || "");
  return {
    task_id: taskId,
    task_title: String(record.task_title || record.title || taskId),
    task_kind: String(record.task_kind || "specific_task"),
    flow_id: String(record.flow_id || ""),
    domain_id: String(record.domain_id || ""),
    task_environment_id: taskEnvironmentId,
    default_agent_id: String(record.default_agent_id || "agent:0"),
    participant_agent_ids: Array.isArray(record.participant_agent_ids) ? record.participant_agent_ids.map((item) => String(item)) : [],
    workflow_id: String(record.workflow_id || ""),
    workflow_file_ref: String(record.workflow_file_ref || ""),
    input_contract_id: String(record.input_contract_id || ""),
    output_contract_id: String(record.output_contract_id || ""),
    safety_policy: dictOf(record.safety_policy),
    task_structure: dictOf(record.task_structure),
    enabled: record.enabled !== false,
    metadata: dictOf(record.metadata),
  };
}

export function TaskEnvironmentManagementWorkbench({
  activePage,
  chatTaskEnvironmentBinding,
  draft,
  environmentItems,
  groupOptions,
  kindTemplates,
  onAssignTaskEnvironment,
  onBindEnvironment,
  onClearEnvironmentBinding,
  onCreate,
  onDelete,
  onDeleteKindTemplate,
  onSave,
  onSaveKindTemplate,
  onSetDraft,
  onSelectGraph,
  saving,
  selectedEnvironmentId,
  selectedGraphId,
  taskSystemOverview,
}: {
  activePage: EnvironmentSubpage;
  chatTaskEnvironmentBinding: EnvironmentBinding;
  draft: EnvironmentDraft;
  environmentItems: TaskEnvironmentItem[];
  groupOptions: Array<{ value: string; label: string }>;
  kindTemplates: TaskEnvironmentKindTemplate[];
  onAssignTaskEnvironment: (record: Record<string, unknown>, environmentId: string) => Promise<void>;
  onBindEnvironment: (environmentId: string, environmentLabel: string) => void;
  onClearEnvironmentBinding: () => void;
  onCreate: () => void;
  onDelete: () => void;
  onDeleteKindTemplate: (kindId: string) => Promise<void>;
  onSave: () => void;
  onSaveKindTemplate: (template: TaskEnvironmentKindTemplate) => Promise<void>;
  onSetDraft: (draft: EnvironmentDraft) => void;
  onSelectGraph: (graphId: string) => void;
  saving: string;
  selectedEnvironmentId: string;
  selectedGraphId: string;
  taskSystemOverview: TaskSystemOverview | null;
}) {
  const selectedItem = environmentItems.find((item) => item.record.environment_id === selectedEnvironmentId);
  const selectedEnvironmentLabel = selectedItem ? taskEnvironmentDisplayTitle(selectedItem) : draft.title || selectedEnvironmentId;
  const boundToSelected = Boolean(selectedEnvironmentId && chatTaskEnvironmentBinding?.task_environment_id === selectedEnvironmentId);
  const selectedScope: EnvironmentScope = taskEnvironmentScope(selectedItem);
  const selectedProtected = Boolean(selectedItem && selectedScope !== "workspace" && draft.environment_id === selectedEnvironmentId);

  return (
    <main className="task-management-workbench task-system-management-workbench">
      <header className="task-management-titlebar task-system-workbench-titlebar">
        <div>
          <span>环境管理</span>
          <h3>{selectedEnvironmentLabel || "任务环境"}</h3>
          <p>{selectedItem ? taskEnvironmentPurpose(selectedItem) : "配置 Agent 可加载的资料、记忆、产物空间和执行边界。"}</p>
          <div className="task-system-title-meta-row">
            <span className={`task-system-source-badge task-system-source-badge--${selectedScope}`}>
              {taskEnvironmentScopeLabel(selectedScope)}
            </span>
            <small>{selectedProtected ? "查看方案；新建我的环境后再保存" : "可编辑配置"}</small>
          </div>
        </div>
        <div className="boundary-actions">
          <TaskSystemToolbarButton onClick={onCreate}><Plus size={15} />新环境</TaskSystemToolbarButton>
          <TaskSystemToolbarButton
            disabled={!selectedEnvironmentId}
            onClick={() => onBindEnvironment(selectedEnvironmentId, selectedEnvironmentLabel)}
            variant={boundToSelected ? "primary" : "ghost"}
          >
            <Link2 size={15} />{boundToSelected ? "已绑定主会话" : "绑定主会话"}
          </TaskSystemToolbarButton>
          {chatTaskEnvironmentBinding ? (
            <TaskSystemToolbarButton onClick={onClearEnvironmentBinding}><Unlink2 size={15} />解除绑定</TaskSystemToolbarButton>
          ) : null}
          <TaskSystemToolbarButton disabled={!selectedEnvironmentId || selectedScope !== "workspace" || saving === "task-environment-delete"} onClick={onDelete}><Trash2 size={15} />删除</TaskSystemToolbarButton>
          <TaskSystemToolbarButton disabled={selectedProtected || saving === "task-environment"} onClick={onSave} variant="primary"><Save size={15} />保存环境</TaskSystemToolbarButton>
        </div>
      </header>

      {activePage === "types" ? (
        <EnvironmentTypePage
          draft={draft}
          groupOptions={groupOptions}
          kindTemplates={kindTemplates}
          onDeleteKindTemplate={onDeleteKindTemplate}
          onSaveKindTemplate={onSaveKindTemplate}
          onSetDraft={onSetDraft}
        />
      ) : null}
      {activePage === "loadout" ? <EnvironmentLoadoutPage draft={draft} onSetDraft={onSetDraft} selectedItem={selectedItem} /> : null}
      {activePage === "prompts" ? <EnvironmentPromptPage draft={draft} onSetDraft={onSetDraft} selectedItem={selectedItem} /> : null}
      {activePage === "tasks" ? (
        <EnvironmentTaskInventoryPage
          environmentItems={environmentItems}
          onAssignTaskEnvironment={onAssignTaskEnvironment}
          selectedEnvironmentId={selectedEnvironmentId}
          taskSystemOverview={taskSystemOverview}
        />
      ) : null}
      {activePage === "graphs" ? (
        <EnvironmentGraphInventoryPage
          onSelectGraph={onSelectGraph}
          selectedGraphId={selectedGraphId}
          taskSystemOverview={taskSystemOverview}
        />
      ) : null}
    </main>
  );
}
