import { request, sessionScopeQuery } from "./shared";
import type {
  CapabilitySystemAgentCatalog,
  ContractSpecUpsertPayload,
  ConversationEntryPolicyUpsertPayload,
  EngagementPlanDetailResponse,
  EngagementPlanListResponse,
  EngagementPlanUpsertPayload,
  EngagementRunCloseoutSyncResult,
  EngagementRunDetailResponse,
  EngagementRunListResponse,
  EngagementStartPayload,
  EngagementStartResult,
  ProjectFilePayload,
  ProjectFileTreePayload,
  ProjectInstance,
  ProjectLibraryPayload,
  ProjectLifecycleActionsPayload,
  ProjectLifecyclePreviewPayload,
  ProjectLifecycleRunPayload,
  ProjectRepositoriesPayload,
  SessionScope,
  SessionSummary,
  TaskAssignmentUpsertPayload,
  TaskDomainUpsertPayload,
  TaskEnvironmentCatalog,
  TaskEnvironmentGroupUpsertPayload,
  TaskEnvironmentKindTemplate,
  TaskEnvironmentKindTemplateUpsertPayload,
  TaskEnvironmentSessionResolvePayload,
  TaskEnvironmentSessionResolveResponse,
  TaskEnvironmentTasksPayload,
  TaskEnvironmentUpsertPayload,
  TaskExecutionPolicyUpsertPayload,
  TaskFlowContractBindingUpsertPayload,
  TaskGraphContractPreview,
  TaskGraphRecord,
  TaskGraphStandardView,
  TaskGraphStandardViewUpsertPayload,
  TaskGraphUpsertPayload,
  TaskNodeConfigurationUpsertPayload,
  TaskSystemNextIds,
  TaskSystemOverview,
  TaskWorkflowCatalog,
  TaskWorkflowUpsertPayload,
} from "./types";

export async function getCapabilitySystemAgents() {
  return request<CapabilitySystemAgentCatalog>("/capability-system/agents");
}

export async function getTaskWorkflows() {
  return request<TaskWorkflowCatalog>("/tasks/workflows");
}

export async function upsertTaskWorkflow(workflowId: string, payload: TaskWorkflowUpsertPayload) {
  return request<TaskSystemOverview>(`/tasks/workflows/${encodeURIComponent(workflowId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function getTaskSystemOverview() {
  return request<TaskSystemOverview>("/tasks/overview");
}

export async function upsertTaskSystemContract(contractId: string, payload: ContractSpecUpsertPayload) {
  return request<TaskSystemOverview>(`/tasks/contracts/${encodeURIComponent(contractId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function deleteTaskSystemContract(contractId: string) {
  return request<TaskSystemOverview>(`/tasks/contracts/${encodeURIComponent(contractId)}`, {
    method: "DELETE"
  });
}

export async function compileTaskSystemTaskGraphContract(graphId: string) {
  return request<TaskGraphContractPreview>(
    `/tasks/task-graph-contracts/task-graphs/${encodeURIComponent(graphId)}/compile`
  );
}

export async function getTaskSystemTaskGraph(graphId: string) {
  return request<TaskGraphRecord>(`/tasks/task-graphs/${encodeURIComponent(graphId)}`);
}

export async function getTaskSystemTaskGraphStandardView(graphId: string) {
  return request<TaskGraphStandardView>(
    `/tasks/task-graphs/${encodeURIComponent(graphId)}/standard-view`
  );
}

export async function upsertTaskSystemTaskGraphStandardView(graphId: string, payload: TaskGraphStandardViewUpsertPayload) {
  return request<TaskGraphStandardView>(`/tasks/task-graphs/${encodeURIComponent(graphId)}/standard-view`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function getTaskSystemNextIds() {
  return request<TaskSystemNextIds>("/tasks/next-ids");
}

export async function upsertTaskSystemEntryPolicy(profileId: string, payload: ConversationEntryPolicyUpsertPayload) {
  return request<TaskSystemOverview>(`/tasks/entry-policies/${encodeURIComponent(profileId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function upsertTaskSystemDomain(domainId: string, payload: TaskDomainUpsertPayload) {
  return request<TaskSystemOverview>(`/tasks/domains/${encodeURIComponent(domainId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function deleteTaskSystemDomain(domainId: string) {
  return request<TaskSystemOverview>(`/tasks/domains/${encodeURIComponent(domainId)}`, {
    method: "DELETE"
  });
}

export async function getTaskSystemEngagementPlans() {
  return request<EngagementPlanListResponse>("/tasks/engagement-plans");
}

export async function getTaskSystemEngagementPlan(planId: string) {
  return request<EngagementPlanDetailResponse>(`/tasks/engagement-plans/${encodeURIComponent(planId)}`);
}

export async function upsertTaskSystemEngagementPlan(planId: string, payload: EngagementPlanUpsertPayload) {
  return request<TaskSystemOverview>(`/tasks/engagement-plans/${encodeURIComponent(planId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function deleteTaskSystemEngagementPlan(planId: string) {
  return request<TaskSystemOverview>(`/tasks/engagement-plans/${encodeURIComponent(planId)}`, {
    method: "DELETE"
  });
}

export async function startTaskSystemEngagementPlan(planId: string, payload: EngagementStartPayload = {}) {
  return request<EngagementStartResult>(`/tasks/engagement-plans/${encodeURIComponent(planId)}/start`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function getTaskSystemEngagementRuns() {
  return request<EngagementRunListResponse>("/tasks/engagement-runs");
}

export async function getTaskSystemEngagementRun(engagementRunId: string) {
  return request<EngagementRunDetailResponse>(`/tasks/engagement-runs/${encodeURIComponent(engagementRunId)}`);
}

export async function syncTaskSystemEngagementRunCloseout(engagementRunId: string) {
  return request<EngagementRunCloseoutSyncResult>(`/tasks/engagement-runs/${encodeURIComponent(engagementRunId)}/sync-closeout`, {
    method: "POST"
  });
}

export async function upsertTaskSystemFlowContractBinding(taskId: string, payload: TaskFlowContractBindingUpsertPayload) {
  return request<TaskSystemOverview>(`/tasks/flow-contract-bindings/${encodeURIComponent(taskId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function upsertTaskSystemExecutionPolicy(taskId: string, payload: TaskExecutionPolicyUpsertPayload) {
  return request<TaskSystemOverview>(`/tasks/execution-policies/${encodeURIComponent(taskId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function upsertTaskSystemTaskAssignment(taskId: string, payload: TaskAssignmentUpsertPayload) {
  return request<TaskSystemOverview>(`/tasks/task-assignments/${encodeURIComponent(taskId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function deleteTaskSystemTaskAssignment(taskId: string) {
  return request<TaskSystemOverview>(`/tasks/task-assignments/${encodeURIComponent(taskId)}`, {
    method: "DELETE"
  });
}

export async function getTaskSystemEnvironmentProjects(environmentId: string) {
  return request<{
    authority: string;
    environment_id: string;
    projects: ProjectInstance[];
    summary: Record<string, number>;
  }>(`/tasks/environments/${encodeURIComponent(environmentId)}/projects`);
}

export async function listTaskEnvironmentSessions(environmentId: string, scope?: Partial<SessionScope>) {
  const params = sessionScopeQuery({
    workspace_view: scope?.workspace_view ?? "task_environment",
    task_environment_id: environmentId,
    project_id: scope?.project_id,
  });
  return request<{ authority: string; scope: SessionScope; sessions: SessionSummary[] }>(
    `/task-environments/${encodeURIComponent(environmentId)}/sessions?${params.toString()}`
  );
}

export async function resolveTaskEnvironmentSession(
  environmentId: string,
  payload: TaskEnvironmentSessionResolvePayload
) {
  return request<TaskEnvironmentSessionResolveResponse>(
    `/task-environments/${encodeURIComponent(environmentId)}/sessions/resolve`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}

export async function getTaskSystemEnvironmentTasks(environmentId: string) {
  return request<TaskEnvironmentTasksPayload>(`/tasks/environments/${encodeURIComponent(environmentId)}/tasks`);
}

export async function getTaskEnvironmentCatalog() {
  return request<TaskEnvironmentCatalog>("/tasks/environments/catalog");
}

export async function getTaskSystemProject(projectId: string) {
  return request<ProjectLibraryPayload>(`/tasks/projects/${encodeURIComponent(projectId)}`);
}

export async function getTaskSystemProjectRepositories(projectId: string) {
  return request<ProjectRepositoriesPayload>(`/tasks/projects/${encodeURIComponent(projectId)}/repositories`);
}

export async function getTaskSystemProjectLifecycleActions(projectId: string) {
  return request<ProjectLifecycleActionsPayload>(`/tasks/projects/${encodeURIComponent(projectId)}/lifecycle-actions`);
}

export async function getTaskSystemProjectRepositoryTree(
  projectId: string,
  repositoryId: string,
  options: { path?: string; maxDepth?: number; maxEntries?: number } = {}
) {
  const params = new URLSearchParams();
  if (options.path) params.set("path", options.path);
  if (options.maxDepth) params.set("max_depth", String(options.maxDepth));
  if (options.maxEntries) params.set("max_entries", String(options.maxEntries));
  const query = params.toString();
  return request<ProjectFileTreePayload>(
    `/tasks/projects/${encodeURIComponent(projectId)}/repositories/${encodeURIComponent(repositoryId)}/tree${query ? `?${query}` : ""}`
  );
}

export async function getTaskSystemProjectRepositoryFile(projectId: string, repositoryId: string, path: string) {
  const params = new URLSearchParams({ path });
  return request<ProjectFilePayload>(
    `/tasks/projects/${encodeURIComponent(projectId)}/repositories/${encodeURIComponent(repositoryId)}/files?${params.toString()}`
  );
}

export async function previewTaskSystemProjectLifecycle(projectId: string, action: string) {
  return request<ProjectLifecyclePreviewPayload>(
    `/tasks/projects/${encodeURIComponent(projectId)}/lifecycle-preview/${encodeURIComponent(action)}`
  );
}

export async function startTaskSystemProjectLifecycleRun(projectId: string, payload: { action: string; execute?: boolean; metadata?: Record<string, unknown> }) {
  return request<ProjectLifecycleRunPayload>(`/tasks/projects/${encodeURIComponent(projectId)}/lifecycle-runs`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function upsertTaskSystemEnvironmentGroup(groupId: string, payload: TaskEnvironmentGroupUpsertPayload) {
  return request<TaskSystemOverview>(`/tasks/environment-groups/${encodeURIComponent(groupId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function getTaskSystemEnvironmentKindTemplates() {
  return request<{ authority: string; kind_templates: TaskEnvironmentKindTemplate[]; summary: Record<string, number> }>("/tasks/environment-kind-templates");
}

export async function upsertTaskSystemEnvironmentKindTemplate(kindId: string, payload: TaskEnvironmentKindTemplateUpsertPayload) {
  return request<TaskSystemOverview>(`/tasks/environment-kind-templates/${encodeURIComponent(kindId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function deleteTaskSystemEnvironmentKindTemplate(kindId: string) {
  return request<TaskSystemOverview>(`/tasks/environment-kind-templates/${encodeURIComponent(kindId)}`, {
    method: "DELETE"
  });
}

export async function upsertTaskSystemEnvironment(environmentId: string, payload: TaskEnvironmentUpsertPayload) {
  return request<TaskSystemOverview>(`/tasks/environments/${encodeURIComponent(environmentId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function deleteTaskSystemEnvironment(environmentId: string) {
  return request<TaskSystemOverview>(`/tasks/environments/${encodeURIComponent(environmentId)}`, {
    method: "DELETE"
  });
}

export async function getTaskSystemNodeConfigurations() {
  return request<NonNullable<TaskSystemOverview["node_configuration_management"]>>("/tasks/node-configurations");
}

export async function upsertTaskSystemNodeConfiguration(nodeConfigId: string, payload: TaskNodeConfigurationUpsertPayload) {
  return request<TaskSystemOverview>(`/tasks/node-configurations/${encodeURIComponent(nodeConfigId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function deleteTaskSystemNodeConfiguration(nodeConfigId: string) {
  return request<TaskSystemOverview>(`/tasks/node-configurations/${encodeURIComponent(nodeConfigId)}`, {
    method: "DELETE"
  });
}

export async function previewTaskSystemNodeConfigurationRuntime(nodeConfigId: string, payload: { environment_id?: string; graph_id?: string } = {}) {
  return request<Record<string, unknown>>(`/tasks/node-configurations/${encodeURIComponent(nodeConfigId)}/runtime-preview`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function upsertTaskSystemTaskGraph(graphId: string, payload: TaskGraphUpsertPayload) {
  return request<TaskSystemOverview>(`/tasks/task-graphs/${encodeURIComponent(graphId)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}
