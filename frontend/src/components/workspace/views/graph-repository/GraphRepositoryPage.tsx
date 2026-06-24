"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  createGraphTaskInstance,
  getOrchestrationAgents,
  getTaskSystemOverview,
  getTaskSystemTaskGraph,
  listGraphTaskInstances,
  upsertTaskSystemTaskGraph,
  type GraphTaskInstanceSummary,
  type OrchestrationAgentRuntimeCatalog,
  type TaskGraphRecord,
  type TaskSystemOverview,
} from "@/lib/api";

import { buildTaskGraphUpsertPayload, resolveTaskGraphPublishCommit, type TaskGraphPublishCommitIntent } from "../task-system/taskGraphSaveMapper";
import type { TaskGraphDraftV2 } from "../task-system/taskGraphDraftV2";
import { GraphEditorContext } from "./contexts/GraphEditorContext";
import { GraphLibraryContext } from "./contexts/GraphLibraryContext";
import { InstanceWorkspaceContext } from "./contexts/InstanceWorkspaceContext";
import { RuntimeProjectionContext } from "./contexts/RuntimeProjectionContext";
import { TemplateLibraryContext } from "./contexts/TemplateLibraryContext";
import {
  deleteUserGraphTemplate,
  findGraphTemplate,
  listGraphTemplates,
  upsertUserGraphTemplate,
} from "./registry/taskGraphTemplateRegistry";
import { graphWorkspaceExtensionsForTemplate } from "./registry/taskGraphInstanceWorkspaceRegistry";
import { builtInGraphTemplates } from "./templates/builtInGraphTemplates";
import {
  createDraftFromGraph,
  createDraftFromTemplate,
  graphTemplateFromDraft,
  type GraphInstanceWorkspaceExtension,
  type GraphTemplateRecord,
} from "./templates/graphTemplateTypes";
import { TaskGraphWorkbenchShell } from "./workbench/TaskGraphWorkbenchShell";
import type { TaskGraphBreadcrumbSegment, TaskGraphWorkbenchContext } from "./workbench/taskGraphWorkbenchState";

function initialDraft() {
  return createDraftFromTemplate(builtInGraphTemplates[0], {
    title: `${builtInGraphTemplates[0].title} 草稿`,
  });
}

export function GraphRepositoryPage({ requestedGraphId = "" }: { requestedGraphId?: string }) {
  const [activeContext, setActiveContext] = useState<TaskGraphWorkbenchContext>("editor");
  const [overview, setOverview] = useState<TaskSystemOverview | null>(null);
  const [agentCatalog, setAgentCatalog] = useState<OrchestrationAgentRuntimeCatalog | null>(null);
  const [templates, setTemplates] = useState<GraphTemplateRecord[]>(() => listGraphTemplates());
  const [draft, setDraft] = useState<TaskGraphDraftV2>(() => initialDraft());
  const [dirty, setDirty] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [instances, setInstances] = useState<GraphTaskInstanceSummary[]>([]);
  const [instancesLoading, setInstancesLoading] = useState(false);
  const [selectedInstanceId, setSelectedInstanceId] = useState("");
  const requestedGraphRef = useRef(requestedGraphId.trim());

  useEffect(() => {
    requestedGraphRef.current = requestedGraphId.trim();
  }, [requestedGraphId]);

  const graphs = useMemo(
    () => overview?.task_graph_management?.task_graphs ?? [],
    [overview],
  );
  const activeGraph = graphs.find((graph) => graph.graph_id === draft.graph_id) ?? null;
  const selectedInstance = instances.find((instance) => instance.graph_task_instance_id === selectedInstanceId) ?? instances[0] ?? null;
  const workspaceExtensions = useMemo(() => {
    const metadataExtensions = Array.isArray(draft.metadata?.workspace_extensions)
      ? draft.metadata.workspace_extensions as GraphInstanceWorkspaceExtension[]
      : null;
    if (metadataExtensions?.length) return metadataExtensions;
    const template = findGraphTemplate(String(draft.metadata?.template_id ?? ""));
    return graphWorkspaceExtensionsForTemplate(template);
  }, [draft.metadata]);

  const refreshTemplates = useCallback(() => {
    setTemplates(listGraphTemplates());
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [nextOverview, nextAgentCatalog] = await Promise.all([
        getTaskSystemOverview(),
        getOrchestrationAgents().catch(() => null),
      ]);
      setOverview(nextOverview);
      setAgentCatalog(nextAgentCatalog);
      refreshTemplates();
      const requested = requestedGraphRef.current;
      if (requested) {
        const graph = nextOverview.task_graph_management?.task_graphs?.find((item) => item.graph_id === requested);
        if (graph) {
          await openGraph(graph, { silent: true });
        }
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "任务图系统加载失败");
    } finally {
      setLoading(false);
    }
  }, [refreshTemplates]);

  useEffect(() => {
    void load();
  }, [load]);

  const refreshInstances = useCallback(async (graphId = draft.graph_id) => {
    const normalizedGraphId = String(graphId || "").trim();
    if (!normalizedGraphId) {
      setInstances([]);
      return;
    }
    setInstancesLoading(true);
    try {
      const payload = await listGraphTaskInstances(normalizedGraphId);
      setInstances(payload.instances ?? []);
      setSelectedInstanceId((current) => current && payload.instances.some((item) => item.graph_task_instance_id === current)
        ? current
        : payload.instances[0]?.graph_task_instance_id || "");
    } catch {
      setInstances([]);
    } finally {
      setInstancesLoading(false);
    }
  }, [draft.graph_id]);

  useEffect(() => {
    void refreshInstances(draft.graph_id);
  }, [draft.graph_id, refreshInstances]);

  function updateDraft(nextDraft: TaskGraphDraftV2) {
    setDraft(nextDraft);
    setDirty(true);
  }

  function createDraft(template: GraphTemplateRecord) {
    setDraft(createDraftFromTemplate(template, { title: `${template.title} 草稿` }));
    setDirty(true);
    setNotice(`已从模板「${template.title}」创建可编辑图草稿。`);
    setActiveContext("editor");
  }

  async function openGraph(graph: TaskGraphRecord, options: { silent?: boolean } = {}) {
    setSaving("open");
    setError("");
    try {
      const detail = await getTaskSystemTaskGraph(graph.graph_id).catch(() => graph);
      setDraft(createDraftFromGraph(detail));
      setDirty(false);
      setNotice(options.silent ? "" : `已打开图「${detail.title || detail.graph_id}」。`);
      setActiveContext("editor");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "打开图定义失败");
    } finally {
      setSaving("");
    }
  }

  async function duplicateGraph(graph: TaskGraphRecord) {
    setSaving("duplicate");
    setError("");
    try {
      const detail = await getTaskSystemTaskGraph(graph.graph_id).catch(() => graph);
      setDraft(createDraftFromGraph(detail, { duplicate: true }));
      setDirty(true);
      setNotice("已生产图副本，请检查后保存。");
      setActiveContext("editor");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "生产副本失败");
    } finally {
      setSaving("");
    }
  }

  function duplicateCurrentDraft() {
    setDraft((current) => ({
      ...current,
      graph_id: `${current.graph_id}.copy.${Date.now().toString(36)}`,
      title: `${current.title || current.graph_id} 副本`,
      publish_state: "draft",
      metadata: {
        ...(current.metadata ?? {}),
        editor_publish_state: "draft",
        duplicated_from: current.graph_id,
      },
    }));
    setDirty(true);
    setNotice("已从当前草稿生产副本。");
  }

  async function persistDraft(intent: TaskGraphPublishCommitIntent): Promise<string | null> {
    const graphId = String(draft.graph_id || "").trim();
    const domainId = String(draft.domain_id || draft.metadata?.domain_id || "domain.general").trim();
    if (!graphId) {
      setError("图 ID 为空，不能保存。");
      return null;
    }
    setSaving(intent === "publish" ? "publish" : "save");
    setError("");
    setNotice("");
    try {
      const publishCommit = resolveTaskGraphPublishCommit(intent);
      const effectiveDraft: TaskGraphDraftV2 = {
        ...draft,
        domain_id: domainId,
        publish_state: publishCommit.editor_publish_state,
        metadata: {
          ...(draft.metadata ?? {}),
          ...publishCommit.metadata_patch,
          domain_id: domainId,
        },
      };
      const payload = buildTaskGraphUpsertPayload({
        taskGraphDraft: effectiveDraft,
        domain_id: domainId,
        task_id: "",
        publish_state: publishCommit.backend_publish_state,
      });
      payload.enabled = publishCommit.enabled;
      const nextOverview = await upsertTaskSystemTaskGraph(graphId, payload);
      setOverview(nextOverview);
      setDraft(effectiveDraft);
      setDirty(false);
      setNotice(intent === "publish" ? "图已发布，可以创建实例。" : "图草稿已保存。");
      return graphId;
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存图失败");
      return null;
    } finally {
      setSaving("");
    }
  }

  async function saveDraft() {
    await persistDraft("save_draft");
  }

  async function publishDraft() {
    await persistDraft("publish");
  }

  function saveCurrentDraftAsTemplate() {
    const title = typeof window !== "undefined"
      ? window.prompt("模板名称", `${draft.title || "自定义图"} 模板`)
      : `${draft.title || "自定义图"} 模板`;
    if (!title) return;
    const template = graphTemplateFromDraft(draft, {
      templateId: `user.template.${Date.now().toString(36)}`,
      title,
      description: "由图编辑器另存的用户模板。",
      category: "custom",
    });
    upsertUserGraphTemplate(template);
    refreshTemplates();
    setNotice(`已保存用户模板「${title}」。`);
  }

  function duplicateTemplate(template: GraphTemplateRecord) {
    const nextTemplate: GraphTemplateRecord = {
      ...template,
      template_id: `user.template.${Date.now().toString(36)}`,
      title: `${template.title} 副本`,
      source: "user",
      readonly: false,
      metadata: {
        ...(template.metadata ?? {}),
        copied_from_template_id: template.template_id,
      },
    };
    upsertUserGraphTemplate(nextTemplate);
    refreshTemplates();
    setNotice(`已复制模板「${template.title}」。`);
  }

  function deleteTemplate(template: GraphTemplateRecord) {
    if (template.readonly) return;
    deleteUserGraphTemplate(template.template_id);
    refreshTemplates();
    setNotice(`已删除用户模板「${template.title}」。`);
  }

  async function createInstanceFromGraph(graph: TaskGraphRecord) {
    setSaving("instance");
    setError("");
    try {
      const detail = await getTaskSystemTaskGraph(graph.graph_id).catch(() => graph);
      const result = await createGraphTaskInstance(graph.graph_id, {
        title: `${detail.title || detail.graph_id} 实例`,
        metadata: { created_from: "graph_repository" },
      });
      setDraft(createDraftFromGraph(detail));
      setDirty(false);
      setSelectedInstanceId(result.instance.graph_task_instance_id);
      await refreshInstances(graph.graph_id);
      setActiveContext("instances");
      setNotice("实例已创建。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "创建实例失败，请确认图已发布。");
    } finally {
      setSaving("");
    }
  }

  async function createInstanceFromDraft() {
    const graphId = await persistDraft("publish");
    if (!graphId) return;
    const title = `${draft.title || graphId} 实例`;
    setSaving("instance");
    try {
      const result = await createGraphTaskInstance(graphId, {
        title,
        metadata: { created_from: "graph_repository_editor" },
      });
      await refreshInstances(graphId);
      setSelectedInstanceId(result.instance.graph_task_instance_id);
      setActiveContext("instances");
      setNotice("实例已创建。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "创建实例失败");
    } finally {
      setSaving("");
    }
  }

  function changeContext(context: TaskGraphWorkbenchContext) {
    setActiveContext(context);
    if (context === "instances" || context === "runtime") {
      void refreshInstances();
    }
  }

  function renderWorkbenchContext() {
    if (activeContext === "templates") {
      return (
        <TemplateLibraryContext
          onCreateDraft={createDraft}
          onDeleteTemplate={deleteTemplate}
          onDuplicateTemplate={duplicateTemplate}
          templates={templates}
        />
      );
    }
    if (activeContext === "graphs") {
      return (
        <GraphLibraryContext
          graphs={graphs}
          loading={loading}
          onCreateInstance={(graph) => void createInstanceFromGraph(graph)}
          onDuplicateGraph={(graph) => void duplicateGraph(graph)}
          onOpenGraph={(graph) => void openGraph(graph)}
          selectedGraphId={draft.graph_id}
        />
      );
    }
    if (activeContext === "instances") {
      return (
        <InstanceWorkspaceContext
          activeGraph={activeGraph}
          extensions={workspaceExtensions}
          instances={instances}
          instancesLoading={instancesLoading}
          onRefreshInstances={() => void refreshInstances()}
          onSelectInstance={(instance) => setSelectedInstanceId(instance.graph_task_instance_id)}
          selectedInstance={selectedInstance}
          selectedInstanceId={selectedInstanceId}
        />
      );
    }
    if (activeContext === "runtime") {
      return (
        <RuntimeProjectionContext
          instancesCount={instances.length}
          selectedInstance={selectedInstance}
        />
      );
    }
    return (
      <GraphEditorContext
        agentCatalog={agentCatalog}
        dirty={dirty}
        draft={draft}
        notice={notice}
        onCreateInstance={() => void createInstanceFromDraft()}
        onDraftChange={updateDraft}
        onDuplicate={duplicateCurrentDraft}
        onPublish={() => void publishDraft()}
        onSave={() => void saveDraft()}
        onSaveTemplate={saveCurrentDraftAsTemplate}
        saving={saving}
      />
    );
  }

  const template = findGraphTemplate(String(draft.metadata?.template_id ?? ""));
  const activeRunCount = instances.filter((instance) => instance.active_graph_run_id).length;
  const breadcrumb: TaskGraphBreadcrumbSegment[] = [
    { label: "模板", value: template?.title || String(draft.metadata?.template_id || "自定义") },
    { label: "草稿", value: draft.title || draft.graph_id || "未命名草稿" },
    { label: "图定义", value: activeGraph?.enabled ? "已发布" : activeGraph?.publish_state || draft.publish_state || "草稿" },
    { label: "实例", value: selectedInstance?.title || selectedInstance?.graph_task_instance_id || "未选择" },
    { label: "运行", value: selectedInstance?.active_graph_run_id || "未启动" },
  ];

  return (
    <section className="workspace-view boundary-console graph-repository-page" aria-label="任务图系统">
      <TaskGraphWorkbenchShell
        activeContext={activeContext}
        breadcrumb={breadcrumb}
        counts={{
          templates: templates.length,
          graphs: graphs.length,
          instances: instances.length,
          runs: activeRunCount,
        }}
        dirty={dirty}
        error={error}
        notice={notice}
        onContextChange={changeContext}
        onRefresh={() => void load()}
        saving={saving}
        title={draft.title || draft.graph_id}
      >
        {renderWorkbenchContext()}
      </TaskGraphWorkbenchShell>
    </section>
  );
}
