"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { GraphTaskInstanceWorkbench } from "@/components/workspace/views/task-graph-workbench/GraphTaskInstanceWorkbench";
import { TaskGraphWorkbench } from "@/components/workspace/views/task-system/TaskGraphWorkbench";
import {
  asRecord,
  emptyTaskGraphDraftV2,
  inferTaskGraphBoundaryNodes,
  taskGraphRecordToDraftV2,
  type TaskGraphDraftV2,
  type TaskGraphPublishStateV2,
} from "@/components/workspace/views/task-system/taskGraphDraftV2";
import {
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
import { normalizeTaskGraphSemanticRelationPresets } from "@/components/workspace/views/task-system/taskGraphSemanticRelations";
import {
  graphEdgeId,
  graphEdgeSource,
  graphEdgeTarget,
  graphNodeTaskId,
} from "@/components/workspace/views/task-system/taskGraphTopologyUtils";
import { TaskGraphChromeSelect } from "@/components/workspace/views/task-system/TaskSystemWorkbenchUi";
import { taskEnvironmentDisplayName } from "@/lib/taskEnvironmentDisplay";
import { buildTaskGraphUpsertPayload, resolveTaskGraphPublishCommit } from "@/components/workspace/views/task-system/taskGraphSaveMapper";
import {
  getOrchestrationAgents,
  getTaskSystemOverview,
  getTaskSystemTaskGraph,
  getTaskSystemTaskGraphStandardView,
  upsertTaskSystemTaskGraph,
  type ContractSpec,
  type OrchestrationAgentRuntimeCatalog,
  type SpecificTaskRecord,
  type TaskDomainRecord,
  type TaskGraphDraftTopologySpec,
  type TaskGraphEdgeRecord,
  type TaskGraphNodeRecord,
  type TaskGraphRecord,
  type TaskSystemOverview,
} from "@/lib/api";

type DomainRecord = {
  domain_id: string;
  task_modes: string[];
  title: string;
  description: string;
  enabled: boolean;
  sort_order: number;
  metadata?: Record<string, unknown>;
  tasks: SpecificTaskRecord[];
  entry_policy: TaskSystemOverview["task_management"]["entry_policies"][number] | null;
};

type GraphTaskWorkspaceMode = "instances" | "editor";
type GraphTaskWorkspaceSurface = "combined" | "operations" | "configuration";

function workspaceModeForSurface(surface: GraphTaskWorkspaceSurface, initialMode: GraphTaskWorkspaceMode): GraphTaskWorkspaceMode {
  if (surface === "operations") return "instances";
  if (surface === "configuration") return "editor";
  return initialMode;
}

function dictOf(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function uniqueStrings(values: Array<string | null | undefined>) {
  return Array.from(new Set(values.map((item) => String(item ?? "").trim()).filter(Boolean)));
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

function normalizeTaskEnvironmentId(value: unknown) {
  const raw = String(value ?? "").trim();
  if (!raw) return "";
  return raw.startsWith("env.") ? raw : "";
}

function withoutGraphEnvironmentFields(payload: Record<string, unknown>) {
  const next = { ...payload };
  delete next.task_environment_id;
  delete next.environment_id;
  return next;
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
  if (record?.title) return taskEnvironmentDisplayName(environmentId, record.title);
  return taskEnvironmentDisplayName(environmentId);
}

function taskEnvironmentItem(environmentId: string, overview?: TaskSystemOverview | null) {
  return overview?.task_environment_management?.environments?.find((item) => item.record.environment_id === environmentId) ?? null;
}

function taskEnvironmentStorageLabel(environmentId: string, overview?: TaskSystemOverview | null) {
  const storage = taskEnvironmentItem(environmentId, overview)?.storage_space ?? {};
  return String(storage.environment_storage_root ?? storage.task_library_root ?? "").trim();
}

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
  graphId: string,
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
    graph_id: graphId || "graph.draft",
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

export function GraphTaskWorkspace({
  initialMode = "instances",
  requestedGraphId = "",
  onSelectedGraphChange,
  surface = "combined",
}: {
  initialMode?: GraphTaskWorkspaceMode;
  requestedGraphId?: string;
  onSelectedGraphChange?: (graphId: string) => void;
  surface?: GraphTaskWorkspaceSurface;
}) {
  const [consolePayload, setConsolePayload] = useState<TaskSystemOverview | null>(null);
  const [orchestrationAgentCatalog, setOrchestrationAgentCatalog] = useState<OrchestrationAgentRuntimeCatalog | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [workspaceMode, setWorkspaceMode] = useState<GraphTaskWorkspaceMode>(() => workspaceModeForSurface(surface, initialMode));
  const [editorEnvironmentId, setEditorEnvironmentId] = useState("");
  const [editorDomainId, setEditorDomainId] = useState("");
  const [editorTaskGraphId, setEditorTaskGraphId] = useState("");
  const [taskGraphEditorSelection, setTaskGraphEditorSelection] = useState(() => emptyTaskGraphEditorSelection());
  const [linkingFromNodeId, setLinkingFromNodeId] = useState("");
  const [taskGraphDraftV2, setTaskGraphDraftV2] = useState<TaskGraphDraftV2>(() => emptyTaskGraphDraftV2());
  const [taskGraphStandardViewState, setTaskGraphStandardViewState] = useState(() => emptyTaskGraphStandardViewState());
  const [taskGraphStandardViewLoading, setTaskGraphStandardViewLoading] = useState(false);
  const [taskGraphStandardViewError, setTaskGraphStandardViewError] = useState("");
  const [activeTaskGraphDetail, setActiveTaskGraphDetail] = useState<TaskGraphRecord | null>(null);
  const [activeTaskGraphDetailError, setActiveTaskGraphDetailError] = useState("");
  const requestedGraphIdRef = useRef("");
  const loadInFlightRef = useRef<Promise<void> | null>(null);
  const orchestrationAgentCatalogLoadRef = useRef<Promise<void> | null>(null);

  useEffect(() => {
    requestedGraphIdRef.current = requestedGraphId.trim();
  }, [requestedGraphId]);

  useEffect(() => {
    setWorkspaceMode(workspaceModeForSurface(surface, initialMode));
  }, [initialMode, surface]);

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

  const scopedTaskGraphs = useCallback((graphs: TaskGraphRecord[]) => {
    return graphs;
  }, []);

  const applyOverview = useCallback((overview: TaskSystemOverview) => {
    setConsolePayload(overview);
    const domains = buildDomains(overview);
    const allGraphs = sortTaskGraphsForWorkbench(overview.task_graph_management?.task_graphs ?? []);
    const selectableGraphs = scopedTaskGraphs(allGraphs);
    const requested = requestedGraphIdRef.current;
    const requestedGraph = requested ? selectableGraphs.find((graph) => graph.graph_id === requested) ?? null : null;
    const recommendedGraph = requestedGraph ?? selectableGraphs[0] ?? null;
    const recommendedDomain = domains.find((domain) => domain.domain_id === recommendedGraph?.domain_id)
      ?? domains.find((domain) => domain.tasks.length > 0)
      ?? domains[0]
      ?? null;
    setEditorDomainId((current) => recommendedDomain?.domain_id || current || "");
    setEditorEnvironmentId((current) => current || overview.task_environment_management?.records?.[0]?.environment_id || "");
    setEditorTaskGraphId((current) => {
      if (requestedGraph) return requestedGraph.graph_id;
      if (current && selectableGraphs.some((graph) => graph.graph_id === current)) return current;
      return recommendedTaskGraphId(selectableGraphs);
    });
  }, [scopedTaskGraphs]);

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
        setError(exc instanceof Error ? exc.message : "图任务工作台加载失败");
      } finally {
        setLoading(false);
        loadInFlightRef.current = null;
      }
    })();
    loadInFlightRef.current = run;
    return run;
  }, [applyOverview, loadOrchestrationAgentCatalog]);

  useEffect(() => {
    void load();
  }, [load]);

  const domains = useMemo(() => buildDomains(consolePayload), [consolePayload]);
  const tasks = useMemo(() => consolePayload?.task_management.specific_task_records ?? [], [consolePayload]);
  const contractManagement = useMemo(() => consolePayload?.contract_management ?? null, [consolePayload]);
  const contractSpecs = useMemo(() => contractManagement?.contract_specs ?? [], [contractManagement]);
  const allTaskGraphs = useMemo(
    () => sortTaskGraphsForWorkbench(consolePayload?.task_graph_management?.task_graphs ?? []),
    [consolePayload],
  );
  const availableTaskGraphs = useMemo(() => scopedTaskGraphs(allTaskGraphs), [allTaskGraphs, scopedTaskGraphs]);
  const semanticRelationPresets = useMemo(
    () => normalizeTaskGraphSemanticRelationPresets(consolePayload?.task_graph_management?.semantic_relations),
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
  const editorDomain = domains.find((domain) => domain.domain_id === editorDomainId)
    ?? domains.find((domain) => domain.domain_id === taskGraphDraftV2.domain_id)
    ?? domains[0]
    ?? null;
  const editorTaskEnvironmentOptions = useMemo(() => {
    const environmentIds = uniqueStrings([
      ...(consolePayload?.task_environment_management?.records ?? []).map((item) => item.environment_id),
      ...tasks.map((task) => taskEnvironmentId(task)),
      ...allTaskGraphs.map((graph) => taskGraphEnvironmentId(graph)),
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
  }, [allTaskGraphs, consolePayload, tasks]);
  const activeEditorEnvironmentId = editorEnvironmentId
    || editorTaskEnvironmentOptions[0]?.value
    || "";
  const editorEnvironmentTasks = useMemo(
    () => tasks.filter((task) => taskEnvironmentId(task) === activeEditorEnvironmentId),
    [activeEditorEnvironmentId, tasks],
  );
  const editorContractSpecs = useMemo(() => scopedContractSpecs(contractSpecs, editorDomain), [contractSpecs, editorDomain]);
  const editorTaskGraphs = useMemo(
    () => availableTaskGraphs,
    [availableTaskGraphs],
  );
  const editorGraphSelectOptions = useMemo(() => {
    const options = editorTaskGraphs.map((task) => ({ value: task.graph_id, label: `${task.title} · ${task.graph_id}` }));
    const draftGraphId = String(taskGraphDraftV2.graph_id || "").trim();
    if (draftGraphId && !options.some((option) => option.value === draftGraphId)) {
      return [
        {
          value: draftGraphId,
          label: `${taskGraphDraftV2.title || draftGraphId}（未保存草稿）`,
        },
        ...options,
      ];
    }
    return options;
  }, [editorTaskGraphs, taskGraphDraftV2]);
  const editorSelectedTaskGraph = editorTaskGraphs.find((item) => item.graph_id === editorTaskGraphId)
    ?? editorTaskGraphs[0]
    ?? null;
  const activeTaskGraphId = editorTaskGraphId || editorSelectedTaskGraph?.graph_id || "";
  const activeTaskGraph = activeTaskGraphDetail?.graph_id === activeTaskGraphId
    ? activeTaskGraphDetail
    : editorSelectedTaskGraph;
  const activeTaskGraphHasFullTopology = Boolean((activeTaskGraphDetail?.nodes?.length || activeTaskGraphDetail?.edges?.length) && activeTaskGraphDetail.graph_id === activeTaskGraphId);
  const editorAgentGroupOptions = useMemo(
    () => uniqueStrings(editorTaskGraphs.map((item) => String(item.runtime_policy?.agent_group_id ?? item.metadata?.agent_group_id ?? ""))),
    [editorTaskGraphs],
  );
  const editorDomainTaskOptions = useMemo(
    () => editorEnvironmentTasks.map((task) => ({ value: task.task_id, label: task.task_title })),
    [editorEnvironmentTasks],
  );
  useEffect(() => {
    const nextRequestedGraphId = requestedGraphId.trim();
    if (!nextRequestedGraphId || !availableTaskGraphs.length) return;
    const target = availableTaskGraphs.find((graph) => graph.graph_id === nextRequestedGraphId);
    if (!target) return;
    setEditorTaskGraphId(target.graph_id);
    setEditorDomainId(target.domain_id || "");
    setEditorEnvironmentId(taskGraphEnvironmentId(target));
  }, [availableTaskGraphs, requestedGraphId]);

  useEffect(() => {
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
  }, [activeTaskGraphId]);

  const activeGraphNodes = taskGraphDraftV2.nodes ?? [];
  const activeGraphEdges = taskGraphDraftV2.edges ?? [];
  const taskGraphDraftRevision = taskGraphDraftRevisionKey({
    graphId: taskGraphDraftV2.graph_id,
    nodes: activeGraphNodes,
    edges: activeGraphEdges,
    metadata: asRecord(taskGraphDraftV2.metadata),
  });
  const taskGraphDraftRevisionRef = useRef(taskGraphDraftRevision);
  taskGraphDraftRevisionRef.current = taskGraphDraftRevision;

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
        revisionKey: taskGraphDraftRevisionRef.current,
      }));
    } catch (exc) {
      setTaskGraphStandardViewState(emptyTaskGraphStandardViewState());
      setTaskGraphStandardViewError(exc instanceof Error ? exc.message : "标准对象视图加载失败");
    } finally {
      setTaskGraphStandardViewLoading(false);
    }
  }, [activeTaskGraphId]);

  useEffect(() => {
    if (!activeTaskGraphId) {
      setTaskGraphStandardViewState(emptyTaskGraphStandardViewState());
      setTaskGraphStandardViewError("");
      return;
    }
    if (taskGraphDraftV2.graph_id !== activeTaskGraphId) return;
    void refreshTaskGraphStandardView();
  }, [activeTaskGraphId, refreshTaskGraphStandardView, taskGraphDraftV2.graph_id]);

  useEffect(() => {
    if (!editorTaskGraphs.some((item) => item.graph_id === editorTaskGraphId)) {
      if (editorTaskGraphId && editorTaskGraphId === taskGraphDraftV2.graph_id) {
        return;
      }
      setEditorTaskGraphId(recommendedTaskGraphId(editorTaskGraphs));
    }
  }, [editorTaskGraphId, editorTaskGraphs, taskGraphDraftV2.graph_id]);

  useEffect(() => {
    if (!activeTaskGraph) {
      if (editorTaskGraphId && editorTaskGraphId === taskGraphDraftV2.graph_id) {
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
    setEditorDomainId(graphDraftV2.domain_id || activeTaskGraph.domain_id || "");
    setEditorEnvironmentId(taskGraphEnvironmentId(graphDraftV2) || taskGraphEnvironmentId(activeTaskGraph));
    setSelectedGraphNodeId(String((activeTaskGraph.nodes ?? [])[0]?.node_id ?? ""));
    setSelectedGraphEdgeId("");
    setLinkingFromNodeId("");
    onSelectedGraphChange?.(graphDraftV2.graph_id);
  }, [activeTaskGraph, activeTaskGraphHasFullTopology, editorTaskGraphId, onSelectedGraphChange, taskGraphDraftV2.graph_id]);

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
    const nextTask = editorEnvironmentTasks.find((task) => !existingTaskIds.has(task.task_id));
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

  async function saveTaskGraphStack(nextPublished?: boolean, nextEditorPublishState?: TaskGraphPublishStateV2) {
    const draftDomainId = editorDomain?.domain_id || taskGraphDraftV2.domain_id || "";
    if (!draftDomainId) {
      setError("请先选择任务域，再保存任务图。");
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
          ...withoutGraphEnvironmentFields(asRecord(taskGraphDraftV2.metadata)),
          ...publishCommit.metadata_patch,
          domain_id: draftDomainId,
          task_id: undefined,
        },
        runtime_policy: withoutGraphEnvironmentFields(taskGraphDraftV2.runtime_policy) as TaskGraphDraftV2["runtime_policy"],
        context_policy: withoutGraphEnvironmentFields(taskGraphDraftV2.context_policy) as TaskGraphDraftV2["context_policy"],
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
      setEditorTaskGraphId(effectiveTaskGraphDraftV2.graph_id);
      onSelectedGraphChange?.(effectiveTaskGraphDraftV2.graph_id);
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
      setNotice(nextPublished === true ? "任务图已发布，可以在本工作台直接创建运行。" : "任务图草稿已保存。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存任务图失败");
    } finally {
      setSaving("");
    }
  }

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
  const graphContextDomainId = editorDomain?.domain_id || taskGraphDraftV2.domain_id || "";
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
  const topologyDirty = false;
  const setGraphWorkbenchSelectedGraphId = (graphId: string) => {
    const target = availableTaskGraphs.find((graph) => graph.graph_id === graphId);
    setEditorTaskGraphId(graphId);
    if (target) {
      setEditorDomainId(target.domain_id || "");
      setEditorEnvironmentId(taskGraphEnvironmentId(target));
    }
    setSelectedGraphNodeId("");
    setSelectedGraphEdgeId("");
    setLinkingFromNodeId("");
    onSelectedGraphChange?.(graphId);
  };
  const editorWorkspaceSlot = (
    <>
      <div className="task-graph-editor-chrome__controls">
        <TaskGraphChromeSelect
          disabled={!editorDomain}
          emptyLabel={!editorDomain ? "先选择任务域" : editorGraphSelectOptions.length ? "选择图草稿" : "任务系统暂无图定义"}
          label="图定义"
          onChange={setGraphWorkbenchSelectedGraphId}
          options={editorGraphSelectOptions}
          placeholder="选择具体任务"
          value={editorTaskGraphId}
        />
      </div>
    </>
  );

  if (loading && !consolePayload) {
    return (
      <section className="task-graph-editor-page task-graph-editor-page--embedded" aria-label="图任务工作区">
        <div className="boundary-empty boundary-empty--large">正在加载图任务配置。</div>
      </section>
    );
  }

  return (
    <section className="task-graph-editor-page task-graph-editor-page--embedded graph-task-workspace-shell" aria-label="图任务工作区">
      {surface === "combined" ? (
        <nav className="graph-task-workspace-mode-switch" aria-label="图任务工作区层级">
          <button
            aria-current={workspaceMode === "instances" ? "page" : undefined}
            className={workspaceMode === "instances" ? "graph-task-workspace-mode-card graph-task-workspace-mode-card--active" : "graph-task-workspace-mode-card"}
            onClick={() => setWorkspaceMode("instances")}
            type="button"
          >
            <strong>实例项目</strong>
            <span>运行、监控、节点会话、文件产物</span>
          </button>
          <button
            aria-current={workspaceMode === "editor" ? "page" : undefined}
            className={workspaceMode === "editor" ? "graph-task-workspace-mode-card graph-task-workspace-mode-card--active" : "graph-task-workspace-mode-card"}
            onClick={() => setWorkspaceMode("editor")}
            type="button"
          >
            <strong>图定义编辑</strong>
            <span>拓扑、节点、边契约、发布校验</span>
          </button>
        </nav>
      ) : null}
      {error ? <div className="boundary-notice boundary-notice--error">{error}</div> : null}
      {notice ? <div className="boundary-notice">{notice}</div> : null}
      {workspaceMode === "instances" ? (
        <GraphTaskInstanceWorkbench
          graphTasks={editorTaskGraphs}
          onOpenEditor={() => setWorkspaceMode("editor")}
          onSelectedGraphChange={setGraphWorkbenchSelectedGraphId}
          selectedGraphId={activeTaskGraphId}
          showEditorAction={surface === "combined"}
        />
      ) : (
        <TaskGraphWorkbench
          addTaskGraphNode={addTaskGraphNode}
          addTaskGraphRoleNode={addTaskGraphRoleNode}
          addTaskGraphSuccessorNode={addTaskGraphSuccessorNode}
          addTaskGraphTaskNode={addTaskGraphTaskNode}
          a2aCatalog={a2aCatalog}
          agentGroupOptions={editorAgentGroupOptions}
          boundTaskGraphTaskIds={boundTaskGraphTaskIds}
          contractSpecs={editorContractSpecs}
          taskGraphs={editorTaskGraphs}
          domainTaskOptions={editorDomainTaskOptions}
          editorIssueCount={editorIssueCount}
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
          setSelectedTaskGraphId={setGraphWorkbenchSelectedGraphId}
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
          semanticRelationPresets={semanticRelationPresets}
        />
      )}
    </section>
  );
}
