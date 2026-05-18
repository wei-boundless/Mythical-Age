import type { TaskGraphStandardEdgeSpec, TaskGraphStandardResourceSpec, TaskGraphStandardView } from "@/lib/api";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function edgeMemoryCollection(edge: TaskGraphStandardEdgeSpec) {
  const memory = asRecord(edge.memory);
  return String(memory.collection ?? memory.collection_id ?? memory.selector_collection ?? "").trim();
}

function resourceRepositoryId(resource: TaskGraphStandardResourceSpec) {
  return String(resource.repository_id || resource.node_id).trim();
}

export function isTaskGraphThreadLedgerResource(resource: TaskGraphStandardResourceSpec) {
  return ["thread_ledger", "progress_ledger"].includes(resource.resource_type);
}

export function isTaskGraphIssueLedgerResource(resource: TaskGraphStandardResourceSpec) {
  return resource.resource_type === "issue_ledger";
}

export function isTaskGraphRiskResource(resource: TaskGraphStandardResourceSpec) {
  return isTaskGraphThreadLedgerResource(resource) || isTaskGraphIssueLedgerResource(resource);
}

export function isTaskGraphMemoryEdge(edge: TaskGraphStandardEdgeSpec) {
  return ["memory_read", "memory_write", "memory_write_candidate", "memory_commit", "memory_handoff"].includes(edge.edge_type);
}

export function isTaskGraphArtifactEdge(edge: TaskGraphStandardEdgeSpec) {
  return ["artifact_read", "artifact_write", "artifact_context"].includes(edge.edge_type);
}

export function buildTaskGraphResourceStandardModel(standardView: TaskGraphStandardView | null) {
  if (!standardView) {
    return {
      resources: [] as TaskGraphStandardResourceSpec[],
      memoryResources: [] as TaskGraphStandardResourceSpec[],
      artifactResources: [] as TaskGraphStandardResourceSpec[],
      riskResources: [] as TaskGraphStandardResourceSpec[],
      threadLedgerResources: [] as TaskGraphStandardResourceSpec[],
      issueLedgerResources: [] as TaskGraphStandardResourceSpec[],
      memoryEdges: [] as TaskGraphStandardEdgeSpec[],
      artifactEdges: [] as TaskGraphStandardEdgeSpec[],
      memoryEdgeCountByRepository: {} as Record<string, number>,
      riskEdgeCountByRepository: {} as Record<string, number>,
      issueCount: 0,
      runtimeIsolation: null as TaskGraphStandardView["runtime_isolation"] | null,
    };
  }

  const resources = standardView.resources ?? [];
  const memoryResources = resources.filter((resource) => (
    ["memory_repository", "memory_collection", "working_memory_store", "runtime_state_store"].includes(resource.resource_type)
  ));
  const artifactResources = resources.filter((resource) => resource.resource_type === "artifact_repository");
  const riskResources = resources.filter(isTaskGraphRiskResource);
  const threadLedgerResources = resources.filter(isTaskGraphThreadLedgerResource);
  const issueLedgerResources = resources.filter(isTaskGraphIssueLedgerResource);
  const memoryEdges = (standardView.edges ?? []).filter(isTaskGraphMemoryEdge);
  const artifactEdges = (standardView.edges ?? []).filter(isTaskGraphArtifactEdge);
  const memoryEdgeCountByRepository = Object.fromEntries(
    memoryResources.map((resource) => {
      const repositoryId = resourceRepositoryId(resource);
      const edgeCount = memoryEdges.filter((edge) => {
        const memory = asRecord(edge.memory);
        const edgeRepository = String(memory.repository_id ?? memory.repository ?? "").trim();
        return edgeRepository === repositoryId || edge.source_node_id === resource.node_id || edge.target_node_id === resource.node_id;
      }).length;
      return [repositoryId, edgeCount];
    }),
  );
  const riskEdgeCountByRepository = Object.fromEntries(
    riskResources.map((resource) => {
      const repositoryId = resourceRepositoryId(resource);
      const edgeCount = memoryEdges.filter((edge) => {
        const memory = asRecord(edge.memory);
        const edgeRepository = String(memory.repository_id ?? memory.repository ?? "").trim();
        return edgeRepository === repositoryId || edge.source_node_id === resource.node_id || edge.target_node_id === resource.node_id;
      }).length;
      return [repositoryId, edgeCount];
    }),
  );

  return {
    resources,
    memoryResources,
    artifactResources,
    riskResources,
    threadLedgerResources,
    issueLedgerResources,
    memoryEdges,
    artifactEdges,
    memoryEdgeCountByRepository,
    riskEdgeCountByRepository,
    issueCount: standardView.issues.length,
    runtimeIsolation: standardView.runtime_isolation,
  };
}

export function buildTaskGraphTimelineStandardModel(standardView: TaskGraphStandardView | null) {
  if (!standardView) {
    return {
      phases: [] as Array<Record<string, unknown>>,
      temporalEdges: [] as Array<Record<string, unknown>>,
      loopFrames: [] as Array<Record<string, unknown>>,
      timelineBlocks: [] as Array<Record<string, unknown>>,
      asyncNodeCount: 0,
      phaseNodeCounts: {} as Record<string, number>,
      issueCount: 0,
      entryNodeId: "",
      outputNodeId: "",
    };
  }

  const phases = standardView.timeline?.phases ?? [];
  const temporalEdges = standardView.timeline?.temporal_edges ?? [];
  const loopFrames = standardView.timeline?.loop_frames ?? [];
  const timelineBlocks = standardView.timeline?.timeline_blocks ?? [];
  const phaseNodeCounts = Object.fromEntries(
    phases.map((phase) => {
      const phaseId = String(phase.phase_id ?? phase.id ?? "").trim();
      const nodeCount = standardView.nodes.filter((node) => String(node.phase_id ?? "").trim() === phaseId).length;
      return [phaseId, nodeCount];
    }),
  );
  const asyncNodeCount = standardView.nodes.filter((node) => {
    const runtime = asRecord(node.runtime);
    return ["async", "parallel", "background"].includes(String(runtime.execution_mode ?? "").trim());
  }).length;

  return {
    phases,
    temporalEdges,
    loopFrames,
    timelineBlocks,
    asyncNodeCount,
    phaseNodeCounts,
    issueCount: standardView.issues.length,
    entryNodeId: standardView.timeline?.entry_node_id ?? "",
    outputNodeId: standardView.timeline?.output_node_id ?? "",
  };
}

export function describeTaskGraphStandardEdge(edge: TaskGraphStandardEdgeSpec) {
  if (isTaskGraphMemoryEdge(edge)) {
    const memory = asRecord(edge.memory);
    const repositoryId = String(memory.repository_id ?? memory.repository ?? "").trim();
    const collectionId = edgeMemoryCollection(edge);
    return `${edge.edge_type} · ${repositoryId || edge.source_node_id || edge.target_node_id}${collectionId ? `.${collectionId}` : ""}`;
  }
  if (isTaskGraphArtifactEdge(edge)) {
    const artifact = asRecord(edge.artifact_context);
    return `${edge.edge_type} · ${String(artifact.context_mode ?? "artifact_context").trim()}`;
  }
  return edge.edge_type;
}
