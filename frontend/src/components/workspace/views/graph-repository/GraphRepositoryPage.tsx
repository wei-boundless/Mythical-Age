"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { BookOpen } from "lucide-react";
import {
  createGraphTaskInstance,
  getAgentSystemAgents,
  getTaskSystemOverview,
  getTaskSystemTaskGraph,
  listGraphTaskInstances,
  upsertTaskSystemTaskGraph,
  type GraphTaskInstanceSummary,
  type AgentSystemAgentRuntimeCatalog,
  type TaskGraphRecord,
  type TaskSystemOverview,
} from "@/lib/api";

import { buildTaskGraphUpsertPayload, resolveTaskGraphPublishCommit, type TaskGraphPublishCommitIntent } from "../task-system/taskGraphSaveMapper";
import type { TaskGraphDraftV2 } from "../task-system/taskGraphDraftV2";
import { GraphEditorContext } from "./contexts/GraphEditorContext";
import { GraphLibraryContext } from "./contexts/GraphLibraryContext";
import { TemplateLibraryContext } from "./contexts/TemplateLibraryContext";
import { GraphInstanceWorkspace } from "./instance/GraphInstanceWorkspace";
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

type RequestedInstancePanel = "writing" | "files" | "artifacts";
const DEFAULT_WRITING_GRAPH_ID = "graph.writing.modular_novel.master";
const DEFAULT_WRITING_INSTANCE_ID = "project.creation.writing.honghuang";

export function GraphRepositoryPage({
  requestedContext,
  requestedGraphId = "",
  requestedInstanceId = "",
  requestedPanel,
}: {
  requestedContext?: TaskGraphWorkbenchContext;
  requestedGraphId?: string;
  requestedInstanceId?: string;
  requestedPanel?: RequestedInstancePanel;
}) {
  const [activeContext, setActiveContext] = useState<TaskGraphWorkbenchContext>("editor");
  const [overview, setOverview] = useState<TaskSystemOverview | null>(null);
  const [agentCatalog, setAgentCatalog] = useState<AgentSystemAgentRuntimeCatalog | null>(null);
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
  const requestedContextRef = useRef<TaskGraphWorkbenchContext | undefined>(requestedContext);
  const requestedInstanceRef = useRef(requestedInstanceId.trim());
  const requestedPanelRef = useRef<RequestedInstancePanel | undefined>(requestedPanel);

  useEffect(() => {
    requestedGraphRef.current = requestedGraphId.trim();
    requestedContextRef.current = requestedContext;
    requestedInstanceRef.current = requestedInstanceId.trim();
    requestedPanelRef.current = requestedPanel;
    if (requestedContext) setActiveContext(requestedContext);
    if (requestedInstanceId.trim()) setSelectedInstanceId(requestedInstanceId.trim());
  }, [requestedContext, requestedGraphId, requestedInstanceId, requestedPanel]);

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
        getAgentSystemAgents().catch(() => null),
      ]);
      setOverview(nextOverview);
      setAgentCatalog(nextAgentCatalog);
      refreshTemplates();
      const requested = requestedGraphRef.current;
      if (requested) {
        const graph = nextOverview.task_graph_management?.task_graphs?.find((item) => item.graph_id === requested);
        if (graph) {
          await openGraph(graph, { silent: true });
          if (requestedContextRef.current) setActiveContext(requestedContextRef.current);
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

  const refreshInstances = useCallback(async (
    graphId = draft.graph_id,
    options: { allowMissingGraph?: boolean } = {},
  ) => {
    const normalizedGraphId = String(graphId || "").trim();
    if (!normalizedGraphId) {
      setInstances([]);
      setSelectedInstanceId("");
      return;
    }
    const graphExists = graphs.some((graph) => graph.graph_id === normalizedGraphId);
    if (!options.allowMissingGraph && !graphExists) {
      setInstances([]);
      setSelectedInstanceId("");
      return;
    }
    setInstancesLoading(true);
    try {
      const payload = await listGraphTaskInstances(normalizedGraphId);
      setInstances(payload.instances ?? []);
      const requestedInstanceId = requestedInstanceRef.current;
      setSelectedInstanceId((current) => current && payload.instances.some((item) => item.graph_task_instance_id === current)
        ? current
        : requestedInstanceId && payload.instances.some((item) => item.graph_task_instance_id === requestedInstanceId)
          ? requestedInstanceId
        : payload.instances[0]?.graph_task_instance_id || "");
    } catch {
      setInstances([]);
    } finally {
      setInstancesLoading(false);
    }
  }, [draft.graph_id, graphs]);

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
      await refreshInstances(graph.graph_id, { allowMissingGraph: true });
      setActiveContext("monitor");
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
      await refreshInstances(graphId, { allowMissingGraph: true });
      setSelectedInstanceId(result.instance.graph_task_instance_id);
      setActiveContext("monitor");
      setNotice("实例已创建。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "创建实例失败");
    } finally {
      setSaving("");
    }
  }

  function changeContext(context: TaskGraphWorkbenchContext) {
    setActiveContext(context);
    if (context === "monitor") {
      void refreshInstances();
    }
  }

  function renderWorkbenchContext() {
    const renderWorldCanvas = ({
      overlay,
      worldMode = "edit",
      worldPanel = null,
    }: {
      overlay?: "templates" | "graphs";
      worldMode?: "edit" | "monitor";
      worldPanel?: ReactNode;
    } = {}) => (
      <section className="graph-world-surface" aria-label="任务图真实画布世界">
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
          graphRunId={worldMode === "monitor" ? selectedInstance?.active_graph_run_id : undefined}
          instanceId={worldMode === "monitor" ? selectedInstance?.graph_task_instance_id : undefined}
          worldMode={worldMode}
          worldPanel={worldPanel}
        />
        {overlay === "templates" ? (
          <aside className="graph-world-library-overlay graph-world-library-overlay--templates" aria-label="模板库覆盖层">
            <TemplateLibraryContext
              onCreateDraft={createDraft}
              onDeleteTemplate={deleteTemplate}
              onDuplicateTemplate={duplicateTemplate}
              templates={templates}
            />
          </aside>
        ) : null}
        {overlay === "graphs" ? (
          <aside className="graph-world-library-overlay graph-world-library-overlay--graphs" aria-label="图定义覆盖层">
            <GraphLibraryContext
              graphs={graphs}
              loading={loading}
              onCreateInstance={(graph) => void createInstanceFromGraph(graph)}
              onDuplicateGraph={(graph) => void duplicateGraph(graph)}
              onOpenGraph={(graph) => void openGraph(graph)}
              selectedGraphId={draft.graph_id}
            />
          </aside>
        ) : null}
      </section>
    );

    if (activeContext === "templates") {
      return renderWorldCanvas({ overlay: "templates" });
    }
    if (activeContext === "graphs") {
      return renderWorldCanvas({ overlay: "graphs" });
    }
    if (activeContext === "monitor") {
      return renderWorldCanvas({
        worldMode: "monitor",
        worldPanel: (
          <GraphInstanceWorkspace
            activeGraph={activeGraph}
            extensions={workspaceExtensions}
            graphMetadata={draft.metadata}
            graphTitle={draft.title || activeGraph?.title || draft.graph_id}
            instance={selectedInstance}
            instances={instances}
            instancesLoading={instancesLoading}
            initialPanel={requestedPanelRef.current || "files"}
            onCreateInstance={() => void createInstanceFromDraft()}
          onRefreshInstances={() => void refreshInstances(draft.graph_id, { allowMissingGraph: Boolean(selectedInstance) })}
            onSelectInstance={(instance) => setSelectedInstanceId(instance.graph_task_instance_id)}
            selectedInstanceId={selectedInstanceId}
            variant="canvas"
          />
        ),
      });
    }
    return renderWorldCanvas();
  }

  const template = findGraphTemplate(String(draft.metadata?.template_id ?? ""));
  const breadcrumb: TaskGraphBreadcrumbSegment[] = [
    { label: "模板", value: template?.title || String(draft.metadata?.template_id || "自定义") },
    { label: "草稿", value: draft.title || draft.graph_id || "未命名草稿" },
    { label: "图定义", value: activeGraph?.enabled ? "已发布" : activeGraph?.publish_state || draft.publish_state || "草稿" },
    { label: "实例", value: selectedInstance?.title || selectedInstance?.graph_task_instance_id || "未选择" },
    { label: "运行", value: selectedInstance?.active_graph_run_id || "未启动" },
  ];
  const writingProjectInstanceId = (draft.graph_id === DEFAULT_WRITING_GRAPH_ID || selectedInstance?.graph_id === DEFAULT_WRITING_GRAPH_ID)
    ? selectedInstance?.graph_task_instance_id || selectedInstanceId || DEFAULT_WRITING_INSTANCE_ID
    : DEFAULT_WRITING_INSTANCE_ID;
  const writingProjectHref = `/writing-project?instance_id=${encodeURIComponent(writingProjectInstanceId)}`;

  return (
    <section className="workspace-view boundary-console graph-repository-page" aria-label="任务图系统">
      <TaskGraphWorkbenchShell
        activeContext={activeContext}
        actions={(
          <a className="graph-os-project-entry" href={writingProjectHref} title="打开写作项目">
            <BookOpen size={15} />
            <span>写作项目</span>
          </a>
        )}
        breadcrumb={breadcrumb}
        counts={{
          templates: templates.length,
          graphs: graphs.length,
          instances: instances.length,
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

