"use client";

import { AlertTriangle, FileText, GitBranch, Link2, Package, Plus, Save, ShieldCheck, Trash2, Unlink2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  TaskSystemField,
  TaskSystemToolbarButton,
} from "@/components/workspace/views/task-system/TaskSystemWorkbenchUi";
import type {
  TaskAssignmentUpsertPayload,
  TaskEnvironmentGroupUpsertPayload,
  TaskEnvironmentKindTemplate,
  TaskEnvironmentUpsertPayload,
  TaskSystemOverview,
} from "@/lib/api";

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
    if (value !== null && value !== undefined && String(value).trim()) return String(value);
  }
  return fallback;
}

function recordFieldString(record: Record<string, unknown> | null | undefined, key: string, fallback = "") {
  const value = record?.[key];
  if (value === null || value === undefined || Array.isArray(value) || typeof value === "object") return fallback;
  return String(value || fallback);
}

function parseJsonObject(value: string, label: string) {
  const parsed = JSON.parse(value || "{}");
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${label} 必须是 JSON 对象`);
  }
  return parsed as Record<string, unknown>;
}

export function defaultEnvironmentDraft(): EnvironmentDraft {
  return {
    environment_id: "env.custom.workspace",
    title: "自定义任务环境",
    description: "",
    group_id: "environment_group.general",
    environment_kind: "custom",
    enabled: true,
    prompt_id: "environment.custom.workspace.v1",
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
    title: String(record.title || ""),
    description: String(record.description || ""),
    group_id: String(record.group_id || "environment_group.general"),
    environment_kind: String(record.environment_kind || "custom"),
    enabled: record.enabled !== false,
    prompt_id: String(firstPrompt.prompt_id || `environment.${String(record.environment_id || "custom").replace(/^env\./, "")}.v1`),
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
          prompt_id: draft.prompt_id.trim() || `environment.${environmentId.replace(/^env\./, "")}.v1`,
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

function badPromptPhrases(content: string) {
  return [
    "这是 runtime 节点",
    "这是runtime节点",
    "根据任务图执行",
    "这个节点用于",
    "runtime packet",
    "runtime_packet",
  ].filter((phrase) => content.includes(phrase));
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
  saving,
  selectedEnvironmentId,
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
  saving: string;
  selectedEnvironmentId: string;
  taskSystemOverview: TaskSystemOverview | null;
}) {
  const selectedItem = environmentItems.find((item) => item.record.environment_id === selectedEnvironmentId);
  const selectedEnvironmentLabel = selectedItem?.record.title || draft.title || selectedEnvironmentId;
  const boundToSelected = Boolean(selectedEnvironmentId && chatTaskEnvironmentBinding?.task_environment_id === selectedEnvironmentId);

  return (
    <main className="task-management-workbench task-system-management-workbench">
      <header className="task-management-titlebar task-system-workbench-titlebar">
        <div>
          <span>环境管理</span>
          <h3>{selectedEnvironmentLabel || "任务环境"}</h3>
          <p>任务环境负责给 agent 装载 Prompt、文件 Profile、记忆、知识、检索索引、存储空间和执行边界。</p>
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
          <TaskSystemToolbarButton disabled={!selectedEnvironmentId || saving === "task-environment-delete"} onClick={onDelete}><Trash2 size={15} />删除</TaskSystemToolbarButton>
          <TaskSystemToolbarButton disabled={saving === "task-environment"} onClick={onSave} variant="primary"><Save size={15} />保存环境</TaskSystemToolbarButton>
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
          selectedEnvironmentId={selectedEnvironmentId}
          taskSystemOverview={taskSystemOverview}
        />
      ) : null}
    </main>
  );
}

function EnvironmentTypePage({
  draft,
  groupOptions,
  kindTemplates,
  onDeleteKindTemplate,
  onSaveKindTemplate,
  onSetDraft,
}: {
  draft: EnvironmentDraft;
  groupOptions: Array<{ value: string; label: string }>;
  kindTemplates: TaskEnvironmentKindTemplate[];
  onDeleteKindTemplate: (kindId: string) => Promise<void>;
  onSaveKindTemplate: (template: TaskEnvironmentKindTemplate) => Promise<void>;
  onSetDraft: (draft: EnvironmentDraft) => void;
}) {
  const currentTemplate = kindTemplates.find((item) => item.kind_id === draft.environment_kind) ?? kindTemplates[0];
  const [kindDraft, setKindDraft] = useState<TaskEnvironmentKindTemplate>(() => currentTemplate ?? {
    kind_id: "custom",
    title: "Custom",
    description: "",
    group_id: draft.group_id,
    allowed_resource_refs: [],
    allowed_task_graph_kinds: [],
    enabled: true,
  });
  const [error, setError] = useState("");

  useEffect(() => {
    if (currentTemplate) setKindDraft(currentTemplate);
  }, [currentTemplate]);

  async function saveKindTemplate() {
    setError("");
    try {
      if (!kindDraft.kind_id.trim()) throw new Error("环境类型 kind_id 不能为空。");
      await onSaveKindTemplate({
        ...kindDraft,
        allowed_resource_refs: kindDraft.allowed_resource_refs ?? [],
        allowed_task_graph_kinds: kindDraft.allowed_task_graph_kinds ?? [],
      });
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "环境类型保存失败");
    }
  }

  return (
    <section className="task-system-two-column">
      <aside className="task-system-filter-rail">
        <header><strong>环境类型</strong><span>{kindTemplates.length} templates</span></header>
        <div className="task-system-list-stack">
          {kindTemplates.map((template) => (
            <button
              className={template.kind_id === kindDraft.kind_id ? "task-system-list-button task-system-list-button--active" : "task-system-list-button"}
              key={template.kind_id}
              onClick={() => {
                setKindDraft(template);
                onSetDraft({ ...draft, environment_kind: template.kind_id, group_id: template.group_id || draft.group_id });
              }}
              type="button"
            >
              <strong>{template.title || template.kind_id}</strong>
              <span>{template.kind_id}</span>
            </button>
          ))}
        </div>
      </aside>
      <section className="task-system-detail-inspector task-system-detail-inspector--flat">
        <header className="task-system-inspector-head">
          <div><span>Environment Kind</span><strong>{kindDraft.title || kindDraft.kind_id}</strong><small>{kindDraft.kind_id}</small></div>
        </header>
        {error ? <div className="boundary-notice boundary-notice--error"><AlertTriangle size={16} />{error}</div> : null}
        <section className="task-system-inspector-section">
          <header><ShieldCheck size={15} /><strong>类型模板</strong><span>默认资源和策略边界</span></header>
          <div className="boundary-form">
            <TaskSystemField label="Kind ID"><input value={kindDraft.kind_id} onChange={(event) => setKindDraft({ ...kindDraft, kind_id: event.target.value })} /></TaskSystemField>
            <TaskSystemField label="名称"><input value={kindDraft.title} onChange={(event) => setKindDraft({ ...kindDraft, title: event.target.value })} /></TaskSystemField>
            <TaskSystemField label="分组">
              <select value={kindDraft.group_id || ""} onChange={(event) => setKindDraft({ ...kindDraft, group_id: event.target.value })}>
                <option value="">不绑定分组</option>
                {groupOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
              </select>
            </TaskSystemField>
            <TaskSystemField label="Prompt cache scope"><input value={kindDraft.default_prompt_cache_scope || "static_environment"} onChange={(event) => setKindDraft({ ...kindDraft, default_prompt_cache_scope: event.target.value })} /></TaskSystemField>
            <label className="boundary-check"><input checked={kindDraft.enabled !== false} onChange={(event) => setKindDraft({ ...kindDraft, enabled: event.target.checked })} type="checkbox" />启用类型模板</label>
            <TaskSystemField label="说明" wide><textarea value={kindDraft.description || ""} onChange={(event) => setKindDraft({ ...kindDraft, description: event.target.value })} /></TaskSystemField>
            <TaskSystemField label="允许资源引用" wide><textarea value={(kindDraft.allowed_resource_refs ?? []).join("\n")} onChange={(event) => setKindDraft({ ...kindDraft, allowed_resource_refs: splitList(event.target.value) })} /></TaskSystemField>
            <TaskSystemField label="允许任务图类型" wide><textarea value={(kindDraft.allowed_task_graph_kinds ?? []).join("\n")} onChange={(event) => setKindDraft({ ...kindDraft, allowed_task_graph_kinds: splitList(event.target.value) })} /></TaskSystemField>
            <JsonTextarea label="默认沙盒策略" value={kindDraft.default_sandbox_policy ?? {}} onChange={(default_sandbox_policy) => setKindDraft({ ...kindDraft, default_sandbox_policy })} />
            <JsonTextarea label="默认执行策略" value={kindDraft.default_execution_policy ?? {}} onChange={(default_execution_policy) => setKindDraft({ ...kindDraft, default_execution_policy })} />
            <JsonTextarea label="默认风险策略" value={kindDraft.default_risk_policy ?? {}} onChange={(default_risk_policy) => setKindDraft({ ...kindDraft, default_risk_policy })} />
          </div>
          <div className="boundary-actions">
            <TaskSystemToolbarButton onClick={() => void onDeleteKindTemplate(kindDraft.kind_id)}><Trash2 size={14} />删除类型</TaskSystemToolbarButton>
            <TaskSystemToolbarButton onClick={() => void saveKindTemplate()} variant="primary"><Save size={14} />保存类型</TaskSystemToolbarButton>
          </div>
        </section>
      </section>
    </section>
  );
}

function EnvironmentLoadoutPage({
  draft,
  onSetDraft,
  selectedItem,
}: {
  draft: EnvironmentDraft;
  onSetDraft: (draft: EnvironmentDraft) => void;
  selectedItem: TaskEnvironmentItem | undefined;
}) {
  const selectedStorageSpace = dictOf(selectedItem?.storage_space);
  const selectedSandboxPolicy = dictOf(selectedItem?.sandbox_policy);
  const selectedExecutionPolicy = dictOf(selectedItem?.execution_policy);
  const selectedRiskPolicy = dictOf(selectedItem?.risk_policy);
  const selectedArtifactPolicy = dictOf(selectedItem?.artifact_policy);
  const selectedFileManagement = dictOf(selectedItem?.file_management);
  const selectedTaskLibrary = dictOf(selectedItem?.task_library);
  const fileAccessTables = Array.isArray(selectedItem?.file_access_tables) ? selectedItem.file_access_tables : [];
  const patch = (next: Partial<EnvironmentDraft>) => onSetDraft({ ...draft, ...next });
  const fileProfileRefs = Array.isArray(selectedFileManagement.file_profile_refs)
    ? selectedFileManagement.file_profile_refs.length
    : splitList(draft.file_profile_refs_text).length;
  const repositoryKindCount = Array.isArray(selectedFileManagement.required_repository_kinds)
    ? selectedFileManagement.required_repository_kinds.length
    : splitList(draft.required_repository_kinds_text).length;
  const memoryLoadCount = splitList(draft.environment_memory_refs_text).length
    + splitList(draft.project_knowledge_refs_text).length
    + splitList(draft.shared_context_refs_text).length
    + splitList(draft.retrieval_index_refs_text).length;
  const promptLoadCount = draft.prompt_content.trim() ? 1 : 0;

  return (
    <div className="task-system-inspector-stack">
      <section className="task-system-metric-grid">
        <article className="task-system-metric"><span>文件 Profile</span><strong>{fileProfileRefs}</strong><small>{repositoryKindCount} repository kinds</small></article>
        <article className="task-system-metric"><span>记忆与检索</span><strong>{memoryLoadCount}</strong><small>memory / knowledge / retrieval</small></article>
        <article className="task-system-metric"><span>环境 Prompt</span><strong>{promptLoadCount}</strong><small>{promptLoadCount ? "将进入 agent 可见上下文" : "未配置"}</small></article>
        <article className="task-system-metric"><span>存储命名空间</span><strong>{recordFieldText(selectedStorageSpace, ["storage_namespace"], draft.storage_namespace || "未声明")}</strong><small>{recordFieldText(selectedStorageSpace, ["environment_storage_root"], "未声明存储根")}</small></article>
      </section>
      <section className="task-system-inspector-section">
        <header><Package size={15} /><strong>Agent 运行资源装载</strong><span>文件、仓库、记忆、知识、检索、存储空间</span></header>
        <div className="boundary-form task-environment-loadout-form">
          <TaskSystemField label="环境 ID"><input value={draft.environment_id} onChange={(event) => patch({ environment_id: event.target.value })} /></TaskSystemField>
          <TaskSystemField label="显示名称"><input value={draft.title} onChange={(event) => patch({ title: event.target.value })} /></TaskSystemField>
          <TaskSystemField label="环境分组"><input value={draft.group_id} onChange={(event) => patch({ group_id: event.target.value })} /></TaskSystemField>
          <TaskSystemField label="环境类型"><input value={draft.environment_kind} onChange={(event) => patch({ environment_kind: event.target.value })} /></TaskSystemField>
          <TaskSystemField label="存储命名空间"><input value={draft.storage_namespace} onChange={(event) => patch({ storage_namespace: event.target.value })} /></TaskSystemField>
          <label className="boundary-check"><input checked={draft.enabled} onChange={(event) => patch({ enabled: event.target.checked })} type="checkbox" />启用任务环境</label>
          <TaskSystemField label="说明" wide><textarea value={draft.description} onChange={(event) => patch({ description: event.target.value })} /></TaskSystemField>
          <TaskSystemField label="文件 Profile refs" wide><textarea value={draft.file_profile_refs_text} onChange={(event) => patch({ file_profile_refs_text: event.target.value })} /></TaskSystemField>
          <TaskSystemField label="仓库类型 refs" wide><textarea value={draft.required_repository_kinds_text} onChange={(event) => patch({ required_repository_kinds_text: event.target.value })} /></TaskSystemField>
          <TaskSystemField label="环境记忆 refs" wide><textarea value={draft.environment_memory_refs_text} onChange={(event) => patch({ environment_memory_refs_text: event.target.value })} /></TaskSystemField>
          <TaskSystemField label="项目知识 refs" wide><textarea value={draft.project_knowledge_refs_text} onChange={(event) => patch({ project_knowledge_refs_text: event.target.value })} /></TaskSystemField>
          <TaskSystemField label="共享上下文 refs" wide><textarea value={draft.shared_context_refs_text} onChange={(event) => patch({ shared_context_refs_text: event.target.value })} /></TaskSystemField>
          <TaskSystemField label="检索索引 refs" wide><textarea value={draft.retrieval_index_refs_text} onChange={(event) => patch({ retrieval_index_refs_text: event.target.value })} /></TaskSystemField>
        </div>
      </section>
      <section className="task-system-inspector-section">
        <header><ShieldCheck size={15} /><strong>策略 JSON</strong><span>资源、沙盒、执行、风险和生命周期</span></header>
        <div className="task-environment-policy-strip">
          <article><span>Shell</span><strong>{recordFieldText(selectedExecutionPolicy, ["shell_execution_policy"], recordFieldText(selectedSandboxPolicy, ["shell_policy"], "未声明"))}</strong></article>
          <article><span>Browser</span><strong>{recordFieldText(selectedExecutionPolicy, ["browser_execution_policy"], recordFieldText(selectedSandboxPolicy, ["browser_policy"], "未声明"))}</strong></article>
          <article><span>Network</span><strong>{recordFieldText(selectedExecutionPolicy, ["network_execution_policy"], recordFieldText(selectedSandboxPolicy, ["network_policy"], "未声明"))}</strong></article>
          <article><span>Permission</span><strong>{recordFieldText(selectedRiskPolicy, ["default_permission_mode"], "未声明")}</strong></article>
          <article><span>Artifact</span><strong>{recordFieldText(selectedArtifactPolicy, ["publish_policy"], "未声明")}</strong></article>
        </div>
        <div className="boundary-form boundary-form--json">
          <TaskSystemField label="文件资源装载策略" wide><textarea value={draft.file_management_text} onChange={(event) => patch({ file_management_text: event.target.value })} /></TaskSystemField>
          <TaskSystemField label="资源空间策略" wide><textarea value={draft.resource_space_text} onChange={(event) => patch({ resource_space_text: event.target.value })} /></TaskSystemField>
          <TaskSystemField label="记忆资源装载策略" wide><textarea value={draft.memory_space_text} onChange={(event) => patch({ memory_space_text: event.target.value })} /></TaskSystemField>
          <TaskSystemField label="沙盒策略" wide><textarea value={draft.sandbox_policy_text} onChange={(event) => patch({ sandbox_policy_text: event.target.value })} /></TaskSystemField>
          <TaskSystemField label="执行策略" wide><textarea value={draft.execution_policy_text} onChange={(event) => patch({ execution_policy_text: event.target.value })} /></TaskSystemField>
          <TaskSystemField label="产物策略" wide><textarea value={draft.artifact_policy_text} onChange={(event) => patch({ artifact_policy_text: event.target.value })} /></TaskSystemField>
          <TaskSystemField label="风险策略" wide><textarea value={draft.risk_policy_text} onChange={(event) => patch({ risk_policy_text: event.target.value })} /></TaskSystemField>
          <TaskSystemField label="观测策略" wide><textarea value={draft.observability_policy_text} onChange={(event) => patch({ observability_policy_text: event.target.value })} /></TaskSystemField>
          <TaskSystemField label="生命周期策略" wide><textarea value={draft.lifecycle_policy_text} onChange={(event) => patch({ lifecycle_policy_text: event.target.value })} /></TaskSystemField>
          <TaskSystemField label="Record metadata" wide><textarea value={draft.metadata_text} onChange={(event) => patch({ metadata_text: event.target.value })} /></TaskSystemField>
          <TaskSystemField label="Spec metadata" wide><textarea value={draft.spec_metadata_text} onChange={(event) => patch({ spec_metadata_text: event.target.value })} /></TaskSystemField>
        </div>
        <div className="task-system-usage-list">
          {fileAccessTables.slice(0, 5).map((table, index) => (
            <article className="task-system-usage-row" key={`${String(table.profile_id ?? "")}-${index}`}>
              <strong>{String(table.profile_id ?? "file profile")}</strong>
              <span>{String(table.authority ?? "")}</span>
            </article>
          ))}
        </div>
        <div className="boundary-empty">环境内任务数：{String(selectedTaskLibrary.task_count ?? 0)}</div>
      </section>
    </div>
  );
}

function EnvironmentPromptPage({
  draft,
  onSetDraft,
  selectedItem,
}: {
  draft: EnvironmentDraft;
  onSetDraft: (draft: EnvironmentDraft) => void;
  selectedItem: TaskEnvironmentItem | undefined;
}) {
  const patch = (next: Partial<EnvironmentDraft>) => onSetDraft({ ...draft, ...next });
  const badPhrases = badPromptPhrases(draft.prompt_content);
  const prompts = Array.isArray(selectedItem?.environment_prompts) ? selectedItem.environment_prompts : [];
  return (
    <section className="task-system-two-column">
      <section className="task-system-detail-inspector task-system-detail-inspector--flat">
        <header className="task-system-inspector-head">
          <div><span>Environment Prompt</span><strong>{draft.prompt_id || "未命名 Prompt"}</strong><small>{badPhrases.length ? `${badPhrases.length} 个表达需要修正` : "agent 可见说明"}</small></div>
        </header>
        {badPhrases.length ? <div className="boundary-notice boundary-notice--error"><AlertTriangle size={16} />环境 Prompt 含开发说明表达：{badPhrases.join("、")}</div> : null}
        <section className="task-system-inspector-section">
          <header><FileText size={15} /><strong>Prompt 编辑</strong><span>必须写成 agent 能直接执行的环境说明</span></header>
          <div className="boundary-form">
            <TaskSystemField label="Prompt ID"><input value={draft.prompt_id} onChange={(event) => patch({ prompt_id: event.target.value })} /></TaskSystemField>
            <TaskSystemField label="Prompt 内容" wide><textarea className="task-system-role-prompt" value={draft.prompt_content} onChange={(event) => patch({ prompt_content: event.target.value })} /></TaskSystemField>
          </div>
        </section>
      </section>
      <aside className="task-system-filter-rail">
        <header><strong>Agent 可见预览</strong><span>{prompts.length || (draft.prompt_content.trim() ? 1 : 0)} prompts</span></header>
        <pre className="task-system-runtime-preview">{draft.prompt_content.trim() || "当前环境没有 prompt，agent 无法从环境配置感知资源边界。"}</pre>
        <div className="task-system-usage-list">
          {prompts.map((prompt, index) => (
            <article className="task-system-usage-row" key={`${String(prompt.prompt_id ?? "")}-${index}`}>
              <strong>{String(prompt.prompt_id ?? "prompt")}</strong>
              <span>{String(prompt.cache_scope ?? prompt.prompt_kind ?? "")}</span>
            </article>
          ))}
        </div>
      </aside>
    </section>
  );
}

function EnvironmentTaskInventoryPage({
  environmentItems,
  onAssignTaskEnvironment,
  selectedEnvironmentId,
  taskSystemOverview,
}: {
  environmentItems: TaskEnvironmentItem[];
  onAssignTaskEnvironment: (record: Record<string, unknown>, environmentId: string) => Promise<void>;
  selectedEnvironmentId: string;
  taskSystemOverview: TaskSystemOverview | null;
}) {
  const inventory = taskSystemOverview?.environment_task_inventory?.items ?? [];
  const assignmentById = new Map((taskSystemOverview?.task_management.task_assignments ?? []).map((item) => [String(item.task_id ?? ""), item]));
  const [draftEnvByTask, setDraftEnvByTask] = useState<Record<string, string>>({});
  const rows = inventory.filter((item) => String(item.environment_id || "") === selectedEnvironmentId || !String(item.environment_id || ""));
  const envOptions = environmentItems.map((item) => ({ value: item.record.environment_id, label: item.record.title || item.record.environment_id }));

  return (
    <section className="task-system-detail-inspector task-system-detail-inspector--flat">
      <header className="task-system-inspector-head">
        <div><span>Environment Tasks</span><strong>环境内任务</strong><small>{rows.length} tasks in scope</small></div>
      </header>
      <div className="task-system-catalog-table task-system-catalog-table--full">
        <header className="task-system-table-head">
          <span>任务</span>
          <span>Flow</span>
          <span>输入/输出契约</span>
          <span>环境归属</span>
          <span>操作</span>
        </header>
        <div className="task-system-table-body">
          {rows.map((row) => {
            const taskId = String(row.task_id ?? "");
            const assignment = assignmentById.get(taskId) ?? row;
            const nextEnv = draftEnvByTask[taskId] ?? String(row.environment_id ?? "");
            return (
              <article className="task-system-table-row task-system-table-row--static" key={taskId}>
                <strong>{String(row.task_title || taskId)}<small>{taskId}</small></strong>
                <span>{String(row.flow_id || "-")}</span>
                <span>{String(row.input_contract_id || "-")} / {String(row.output_contract_id || "-")}</span>
                <span>
                  <select value={nextEnv} onChange={(event) => setDraftEnvByTask({ ...draftEnvByTask, [taskId]: event.target.value })}>
                    <option value="">未归属</option>
                    {envOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                  </select>
                </span>
                <em><TaskSystemToolbarButton onClick={() => void onAssignTaskEnvironment(assignment, nextEnv)}><Save size={14} />保存归属</TaskSystemToolbarButton></em>
              </article>
            );
          })}
          {!rows.length ? <div className="boundary-empty">当前环境没有任务，且没有未归属任务可绑定。</div> : null}
        </div>
      </div>
    </section>
  );
}

function EnvironmentGraphInventoryPage({
  selectedEnvironmentId,
  taskSystemOverview,
}: {
  selectedEnvironmentId: string;
  taskSystemOverview: TaskSystemOverview | null;
}) {
  const rows = taskSystemOverview?.environment_graph_inventory?.items?.filter((item) => String(item.environment_id || "") === selectedEnvironmentId) ?? [];
  return (
    <section className="task-system-detail-inspector task-system-detail-inspector--flat">
      <header className="task-system-inspector-head">
        <div><span>Environment Graphs</span><strong>环境任务图</strong><small>{rows.length} graphs</small></div>
      </header>
      <div className="task-system-catalog-table task-system-catalog-table--full">
        <header className="task-system-table-head">
          <span>任务图</span>
          <span>类型</span>
          <span>入口/出口</span>
          <span>节点/边</span>
          <span>发布态</span>
        </header>
        <div className="task-system-table-body">
          {rows.map((row) => (
            <article className="task-system-table-row task-system-table-row--static" key={String(row.graph_id ?? "")}>
              <strong>{String(row.title || row.graph_id)}<small>{String(row.graph_id ?? "")}</small></strong>
              <span>{String(row.graph_kind || "-")}</span>
              <span>{String(row.entry_node_id || "-")} / {String(row.output_node_id || "-")}</span>
              <span>{String(row.node_count ?? 0)} / {String(row.edge_count ?? 0)}</span>
              <em className="task-system-status">{String(row.publish_state || "-")}</em>
            </article>
          ))}
          {!rows.length ? <div className="boundary-empty">当前环境没有绑定任务图。任务图拓扑请在主任务图工作台编辑。</div> : null}
        </div>
      </div>
    </section>
  );
}

function JsonTextarea({
  label,
  onChange,
  value,
}: {
  label: string;
  onChange: (value: Record<string, unknown>) => void;
  value: Record<string, unknown>;
}) {
  const [text, setText] = useState(JSON.stringify(value, null, 2));
  const [error, setError] = useState("");
  useEffect(() => {
    setText(JSON.stringify(value, null, 2));
    setError("");
  }, [value]);
  return (
    <TaskSystemField label={label} wide>
      <div className={error ? "task-system-json-editor task-system-json-editor--invalid" : "task-system-json-editor"}>
        <textarea
          value={text}
          onChange={(event) => {
            const next = event.target.value;
            setText(next);
            try {
              onChange(parseJsonObject(next, label));
              setError("");
            } catch {
              setError(`${label} 不是合法 JSON。`);
            }
          }}
          spellCheck={false}
        />
        {error ? <small>{error}</small> : null}
      </div>
    </TaskSystemField>
  );
}

