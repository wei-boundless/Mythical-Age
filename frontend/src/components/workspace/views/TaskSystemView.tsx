"use client";

import { Plus } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useConfirmDialog } from "@/components/layout/ConfirmDialogProvider";
import { contractSpecTitle } from "@/components/workspace/views/task-system/ContractLibraryPanel";
import { TaskSystemShell } from "@/components/workspace/views/task-system/TaskSystemShell";
import { TaskSystemToolbarButton as ToolbarButton, TaskGraphChromeSelect } from "@/components/workspace/views/task-system/TaskSystemWorkbenchUi";
import { TaskContractLibraryPage } from "@/components/workspace/views/task-system/library/TaskContractLibraryPage";
import { TaskDomainLibraryPage } from "@/components/workspace/views/task-system/library/TaskDomainLibraryPage";
import { TaskOrchestrationResourceLibraryPage } from "@/components/workspace/views/task-system/library/TaskOrchestrationResourceLibraryPage";
import { recommendedTaskGraphId, sortTaskGraphsForWorkbench } from "@/components/workspace/views/task-system/taskGraphSelection";
import {
  deleteTaskSystemContract,
  deleteTaskSystemDomain,
  deleteTaskSystemEnvironment,
  getOrchestrationAgents,
  getTaskSystemOverview,
  upsertTaskSystemContract,
  upsertTaskSystemDomain,
  upsertTaskSystemEntryPolicy,
  upsertTaskSystemEnvironment,
  upsertTaskSystemEnvironmentGroup,
  type ContractSpec,
  type ConversationEntryPolicy,
  type OrchestrationAgentRuntimeCatalog,
  type SpecificTaskRecord,
  type TaskDomainRecord,
  type TaskEnvironmentGroupUpsertPayload,
  type TaskEnvironmentUpsertPayload,
  type TaskSystemOverview,
} from "@/lib/api";
import { useAppStore } from "@/lib/store";

type TaskSystemLayer = "domains" | "environments" | "contracts" | "orchestration";
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

type LayerNavItem<T extends string> = {
  value: T;
  label: string;
  meta: string;
  detail: string;
};

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
  const storageNamespace = draft.storage_namespace.trim() || environmentId.replace(/^env\./, "").replace(/\./g, "/");
  const metadata = parseJsonObject(draft.metadata_text, "任务环境 metadata");
  const sandboxPolicy = parseJsonObject(draft.sandbox_policy_text, "沙盒策略");
  const executionPolicy = parseJsonObject(draft.execution_policy_text, "执行策略");
  const artifactPolicy = parseJsonObject(draft.artifact_policy_text, "产物策略");
  const riskPolicy = parseJsonObject(draft.risk_policy_text, "风险策略");
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
    resource_space: {
      storage_namespace: storageNamespace,
      environment_storage_root: `runtime/task_environments/${storageNamespace}`,
      task_library_root: `runtime/task_environments/${storageNamespace}/tasks`,
      runtime_state_root: `runtime/task_environments/${storageNamespace}/state`,
      artifact_root: `artifacts/${storageNamespace}`,
      cache_root: `runtime/task_environments/${storageNamespace}/cache`,
    },
    file_management: {
      file_profile_refs: splitList(draft.file_profile_refs_text),
      required_repository_kinds: splitList(draft.required_repository_kinds_text),
    },
    environment_prompts: draft.prompt_content.trim()
      ? [{
        prompt_id: draft.prompt_id.trim() || `environment.${environmentId.replace(/^env\./, "")}.v1`,
        title: `${draft.title.trim() || environmentId} 环境说明`,
        content: draft.prompt_content.trim(),
        enabled: true,
        priority: 10,
      }]
      : [],
    sandbox_policy: sandboxPolicy,
    execution_policy: executionPolicy,
    artifact_policy: artifactPolicy,
    risk_policy: riskPolicy,
  };
}

function environmentGroupPayload(groupId: string, overview: TaskSystemOverview | null): TaskEnvironmentGroupUpsertPayload {
  const group = overview?.task_environment_management?.groups?.find((item) => item.group_id === groupId);
  return {
    group_id: groupId,
    title: group?.title || groupId.replace(/^environment_group\./, ""),
    description: group?.description || "",
    enabled: group?.enabled ?? true,
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
    <main className="task-management-workbench task-management-workbench--full">
      <header className="task-management-titlebar">
        <div>
          <span>任务环境配置</span>
          <h3>{draft.title || "任务环境"}</h3>
          <p>任务环境只定义资源边界、文件系统、沙盒、产物区和执行策略；图编辑和运行进入主会话图工作台。</p>
        </div>
        <div className="boundary-actions">
          <ToolbarButton onClick={onCreate}><Plus size={15} />新环境</ToolbarButton>
          <ToolbarButton disabled={!selectedEnvironmentId || saving === "task-environment-delete"} onClick={onDelete}>删除环境</ToolbarButton>
          <ToolbarButton disabled={saving === "task-environment"} onClick={onSave} variant="primary">保存环境</ToolbarButton>
        </div>
      </header>

      <section className="task-system-task-cover">
        <article className="boundary-card">
          <header><strong>环境列表</strong><span>{environmentItems.length} 个</span></header>
          <div className="boundary-list boundary-list--scroll">
            {environmentItems.map((item) => {
              const id = item.record.environment_id;
              const active = id === selectedEnvironmentId;
              return (
                <button
                  className={active ? "boundary-list-row boundary-list-row--active" : "boundary-list-row"}
                  key={id}
                  onClick={() => onSelectEnvironment(id)}
                  type="button"
                >
                  <strong>{item.record.title || id}</strong>
                  <span>{id}</span>
                </button>
              );
            })}
            {!environmentItems.length ? <div className="boundary-empty">还没有任务环境配置。</div> : null}
          </div>
        </article>

        <article className="boundary-card">
          <header><strong>运行边界</strong><span>{text(boundaryContract.mode, "未声明")}</span></header>
          <div className="boundary-kv">
            <p><span>文件访问</span><strong>{recordFieldText(boundaryContract, ["file_access_mode", "file_policy"], "未声明")}</strong></p>
            <p><span>沙盒</span><strong>{recordFieldText(boundaryContract, ["sandbox_mode", "sandbox_policy"], "未声明")}</strong></p>
            <p><span>产物根</span><strong>{recordFieldText(dictOf(environmentItems.find((item) => item.record.environment_id === selectedEnvironmentId)?.storage_space), ["artifact_root"], "未声明")}</strong></p>
            <p><span>存储根</span><strong>{recordFieldText(dictOf(environmentItems.find((item) => item.record.environment_id === selectedEnvironmentId)?.storage_space), ["environment_storage_root"], "未声明")}</strong></p>
          </div>
        </article>
      </section>

      <section className="boundary-card">
        <header><strong>环境对象</strong><span>{draft.environment_id}</span></header>
        <div className="boundary-form">
          <label><span>环境 ID</span><input value={draft.environment_id} onChange={(event) => patch({ environment_id: event.target.value })} /></label>
          <label><span>显示名称</span><input value={draft.title} onChange={(event) => patch({ title: event.target.value })} /></label>
          <label><span>说明</span><textarea value={draft.description} onChange={(event) => patch({ description: event.target.value })} /></label>
          <label><span>环境分组</span>
            <select value={draft.group_id} onChange={(event) => patch({ group_id: event.target.value })}>
              {groupOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
          </label>
          <label><span>环境类型</span><input value={draft.environment_kind} onChange={(event) => patch({ environment_kind: event.target.value })} /></label>
          <label className="boundary-check">
            <input checked={draft.enabled} onChange={(event) => patch({ enabled: event.target.checked })} type="checkbox" />
            启用任务环境
          </label>
        </div>
      </section>

      <section className="boundary-card">
        <header><strong>资源与文件</strong><span>Storage / Files</span></header>
        <div className="boundary-form">
          <label><span>存储命名空间</span><input value={draft.storage_namespace} onChange={(event) => patch({ storage_namespace: event.target.value })} /></label>
          <label><span>文件 Profile</span><textarea value={draft.file_profile_refs_text} onChange={(event) => patch({ file_profile_refs_text: event.target.value })} /></label>
          <label><span>仓库类型</span><textarea value={draft.required_repository_kinds_text} onChange={(event) => patch({ required_repository_kinds_text: event.target.value })} /></label>
        </div>
      </section>

      <section className="boundary-card">
        <header><strong>策略 JSON</strong><span>Sandbox / Execution / Artifact / Risk</span></header>
        <div className="boundary-form boundary-form--json">
          <label><span>环境 Prompt ID</span><input value={draft.prompt_id} onChange={(event) => patch({ prompt_id: event.target.value })} /></label>
          <label><span>环境 Prompt</span><textarea value={draft.prompt_content} onChange={(event) => patch({ prompt_content: event.target.value })} /></label>
          <label><span>沙盒策略</span><textarea value={draft.sandbox_policy_text} onChange={(event) => patch({ sandbox_policy_text: event.target.value })} /></label>
          <label><span>执行策略</span><textarea value={draft.execution_policy_text} onChange={(event) => patch({ execution_policy_text: event.target.value })} /></label>
          <label><span>产物策略</span><textarea value={draft.artifact_policy_text} onChange={(event) => patch({ artifact_policy_text: event.target.value })} /></label>
          <label><span>风险策略</span><textarea value={draft.risk_policy_text} onChange={(event) => patch({ risk_policy_text: event.target.value })} /></label>
          <label><span>Metadata</span><textarea value={draft.metadata_text} onChange={(event) => patch({ metadata_text: event.target.value })} /></label>
        </div>
      </section>
    </main>
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

function contractBelongsToDomain(spec: ContractSpec, domain: DomainRecord | null) {
  if (!domain) return true;
  const metadata = dictOf(spec.metadata);
  const domainId = String(metadata.domain_id ?? "").trim();
  return domainId ? domainId === domain.domain_id : true;
}

function scopedContractSpecs(contractSpecs: ContractSpec[], domain: DomainRecord | null) {
  return contractSpecs.filter((spec) => contractBelongsToDomain(spec, domain));
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
  if (!baseDomains.length) {
    baseDomains.push({ ...emptyTaskDomain(), domain_id: "domain.general", title: "通用任务域" });
  }
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

export function TaskSystemView() {
  const confirm = useConfirmDialog();
  const {
    activeWorkspaceView,
    openTaskGraphWorkspace,
    setOrchestrationInspectorTarget,
    setWorkspaceView,
  } = useAppStore();
  const [consolePayload, setConsolePayload] = useState<TaskSystemOverview | null>(null);
  const [orchestrationAgentCatalog, setOrchestrationAgentCatalog] = useState<OrchestrationAgentRuntimeCatalog | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [selectedDomainId, setSelectedDomainId] = useState("");
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [selectedTaskGraphId, setSelectedTaskGraphId] = useState("");
  const [selectedEnvironmentId, setSelectedEnvironmentId] = useState("");
  const [taskSystemLayer, setTaskSystemLayer] = useState<TaskSystemLayer>("environments");
  const [editingDomainName, setEditingDomainName] = useState(false);
  const [contractPanel, setContractPanel] = useState<ContractPanel>("library");
  const [entryDraft, setEntryDraft] = useState<ConversationEntryPolicy>(emptyEntryPolicy());
  const [domainDraft, setDomainDraft] = useState<TaskDomainRecord>(emptyTaskDomain());
  const [environmentDraft, setEnvironmentDraft] = useState<EnvironmentDraft>(() => defaultEnvironmentDraft());
  const selectedDomainIdRef = useRef("");
  const loadInFlightRef = useRef<Promise<void> | null>(null);
  const orchestrationAgentCatalogLoadRef = useRef<Promise<void> | null>(null);
  const taskSystemActive = activeWorkspaceView === "task-system";

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
    const environmentRecords = overview.task_environment_management?.records ?? [];
    setSelectedDomainId(selectedDomain?.domain_id ?? "");
    setSelectedTaskId((current) => current || selectedDomain?.tasks[0]?.task_id || overview.task_management.specific_task_records[0]?.task_id || "");
    setSelectedTaskGraphId((current) => recommendedTaskGraphId(taskGraphs, current));
    setSelectedEnvironmentId((current) => current && environmentRecords.some((item) => item.environment_id === current)
      ? current
      : environmentRecords[0]?.environment_id || "");
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
  }, [applyOverview, loadOrchestrationAgentCatalog]);

  useEffect(() => {
    if (!taskSystemActive) return;
    void load();
  }, [load, taskSystemActive]);

  const domains = useMemo(() => buildDomains(consolePayload), [consolePayload]);
  const visibleDomains = useMemo(() => {
    const hasSelectedDomain = domains.some((item) => item.domain_id === selectedDomainId);
    if (!selectedDomainId || hasSelectedDomain || !domainDraft.domain_id) {
      return domains;
    }
    return [
      ...domains,
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
  const workflows = useMemo(() => consolePayload?.task_management.workflow_resources ?? [], [consolePayload]);
  const contractManagement = useMemo(() => consolePayload?.contract_management ?? null, [consolePayload]);
  const contractSpecs = useMemo(() => contractManagement?.contract_specs ?? [], [contractManagement]);
  const domainContractSpecs = useMemo(() => scopedContractSpecs(contractSpecs, selectedDomain), [contractSpecs, selectedDomain]);
  const allTaskGraphs = useMemo(
    () => sortTaskGraphsForWorkbench(consolePayload?.task_graph_management?.task_graphs ?? []),
    [consolePayload],
  );
  const taskGraphs = useMemo(
    () => selectedDomain?.domain_id ? sortTaskGraphsForWorkbench(allTaskGraphs.filter((item) => String(item.domain_id ?? "").trim() === selectedDomain.domain_id)) : [],
    [allTaskGraphs, selectedDomain?.domain_id],
  );
  const selectedTaskGraph = taskGraphs.find((item) => item.graph_id === selectedTaskGraphId) ?? taskGraphs[0] ?? allTaskGraphs[0] ?? null;
  const workflowOptions = useMemo(() => uniqueStrings(workflows.map((item) => item.workflow_id)), [workflows]);
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

  const openWorkbenchGraphId = selectedTaskGraph?.graph_id || allTaskGraphs[0]?.graph_id || "";
  const openGraphWorkbench = useCallback(() => {
    openTaskGraphWorkspace({ mode: "editor", graph_id: openWorkbenchGraphId });
  }, [openTaskGraphWorkspace, openWorkbenchGraphId]);

  const openOrchestrationControl = useCallback((focus?: {
    agentId?: string;
    agentProfileId?: string;
    layer?: "registry" | "groups" | "runtime" | "eligibility";
    nodeId?: string;
    reason?: string;
  }) => {
    setOrchestrationInspectorTarget({
      source: "task-system",
      orchestrationLayer: focus?.layer ?? "runtime",
      agentId: focus?.agentId,
      agentProfileId: focus?.agentProfileId,
      graphId: openWorkbenchGraphId || undefined,
      nodeId: focus?.nodeId,
      reason: focus?.reason ?? "从任务系统进入编排页：配置 Agent 运行档案。",
    });
    setWorkspaceView("orchestration");
  }, [openWorkbenchGraphId, setOrchestrationInspectorTarget, setWorkspaceView]);

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
    if (!selectedDomain.tasks.some((item) => item.task_id === selectedTaskId)) {
      setSelectedTaskId(selectedDomain.tasks[0]?.task_id || "");
    }
  }, [selectedDomain, selectedTaskId, workflows]);

  useEffect(() => {
    if (!taskGraphs.some((item) => item.graph_id === selectedTaskGraphId)) {
      setSelectedTaskGraphId(recommendedTaskGraphId(taskGraphs));
    }
  }, [taskGraphs, selectedTaskGraphId]);

  useEffect(() => {
    if (!selectedEnvironmentItem) return;
    setEnvironmentDraft(environmentDraftFromItem(selectedEnvironmentItem));
  }, [selectedEnvironmentItem]);

  function createDomainDraft() {
    const index = visibleDomains.length + 1;
    const draft = emptyTaskDomain(index);
    draft.domain_id = `domain.custom_${index}`;
    draft.title = `新任务域 ${index}`;
    draft.metadata = { ...(draft.metadata ?? {}), draft_identity_locked: true };
    setDomainDraft(draft);
    setSelectedDomainId(draft.domain_id);
    setSelectedTaskId("");
    setEditingDomainName(true);
    setTaskSystemLayer("domains");
    setNotice("已生成任务域草稿，请填写名称后保存。");
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

  function createEnvironmentDraft() {
    const index = environmentItems.length + 1;
    const suffix = String(index).padStart(2, "0");
    setSelectedEnvironmentId("");
    setEnvironmentDraft({
      ...defaultEnvironmentDraft(),
      environment_id: `env.custom.workspace_${suffix}`,
      prompt_id: `environment.custom.workspace_${suffix}.v1`,
      storage_namespace: `custom/workspace_${suffix}`,
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

  async function saveContractSpec(spec: ContractSpec) {
    setSaving("contract-spec");
    setError("");
    setNotice("");
    try {
      const payloadSpec = selectedDomain
        ? {
            ...spec,
            metadata: {
              ...(spec.metadata ?? {}),
              domain_id: selectedDomain.domain_id,
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

  const taskSystemLayerItems: Array<LayerNavItem<TaskSystemLayer>> = [
    {
      value: "environments",
      label: "任务环境",
      meta: selectedEnvironmentItem?.record.title || `${environmentItems.length} 个环境`,
      detail: "系统资源边界",
    },
    {
      value: "domains",
      label: "具体任务",
      meta: selectedDomain?.title || `${visibleDomains.length} 组任务`,
      detail: "环境内任务定义",
    },
    {
      value: "contracts",
      label: "契约库",
      meta: `${domainContractSpecs.length} 个契约`,
      detail: "节点与边协议",
    },
    {
      value: "orchestration",
      label: "Agent 配置",
      meta: `${orchestrationAgentCatalog?.agents?.length ?? 0} Agent / ${orchestrationAgentCatalog?.profiles?.length ?? 0} 运行档案`,
      detail: "节点装配资源",
    },
  ];
  const primaryTaskSystemLayerItems = taskSystemLayerItems.filter((item) => ["environments", "domains"].includes(item.value));
  const supportingTaskSystemLayerItems = taskSystemLayerItems.filter((item) => ["contracts", "orchestration"].includes(item.value));
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
    <div className="task-system-object-table task-system-object-table--home-switch" aria-label="任务系统主页面切换">
      <div className="task-system-object-table__head" aria-hidden="true">
        <span>任务系统主页</span>
        <span>当前记录</span>
        <span>状态</span>
      </div>
      {[...primaryTaskSystemLayerItems, ...supportingTaskSystemLayerItems].map((item) => {
        const active = taskSystemLayer === item.value;
        const scope = primaryTaskSystemLayerItems.some((entry) => entry.value === item.value) ? "主页面" : "支撑页";
        return (
          <button
            aria-current={active ? "page" : undefined}
            className={active ? "task-system-object-row task-system-object-row--active" : "task-system-object-row"}
            key={item.value}
            onClick={() => setTaskSystemLayer(item.value)}
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

  return (
    <TaskSystemShell
      activeLayer={taskSystemLayer}
      error={error}
      contextSlot={domainContextSlot}
      layerSlot={managementLayerSlot}
      navItems={taskSystemLayerItems}
      notice={notice}
      onRefresh={() => void load()}
      onSelectLayer={(layer) => {
        void load();
        setTaskSystemLayer(layer);
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
            onSelectLayer={setTaskSystemLayer}
            onSetDomainDraft={setDomainDraft}
            onSetEditingDomainName={setEditingDomainName}
            onSetEntryDraft={setEntryDraft}
            saving={saving}
            selectedDomain={selectedDomain}
            workflowOptions={workflowOptions}
          />
        ) : null}

        {taskSystemLayer === "contracts" ? (
          <TaskContractLibraryPage
            contractManagement={contractManagement}
            contractPanel={contractPanel}
            contractPanelItems={contractPanelItems}
            domainContractSpecs={domainContractSpecs}
            onDeleteContract={removeContractSpec}
            onOpenWorkbench={openGraphWorkbench}
            onSaveContract={saveContractSpec}
            onSelectPanel={setContractPanel}
            saving={saving}
            selectedTaskGraphId={openWorkbenchGraphId}
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
            onOpenWorkbench={openGraphWorkbench}
            orchestrationAgentCatalog={orchestrationAgentCatalog}
            selectedTaskGraphId={openWorkbenchGraphId}
          />
        ) : null}
      </section>
    </TaskSystemShell>
  );
}
