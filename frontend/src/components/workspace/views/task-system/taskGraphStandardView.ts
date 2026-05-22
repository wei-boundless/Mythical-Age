import type {
  ComposableUnitSpec,
  GraphModuleExpansionSpec,
  TaskGraphMemoryProtocol,
  TaskGraphMemoryProtocolCollection,
  TaskGraphMemoryProtocolEdge,
  TaskGraphMemoryProtocolRepository,
  TaskGraphStandardEdgeSpec,
  TaskGraphStandardResourceSpec,
  TaskGraphStandardView,
  UnitInterfaceSpec,
  UnitPortEdgeSpec,
} from "@/lib/api";

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

function expansionUnitId(expansion: GraphModuleExpansionSpec) {
  return String(expansion.unit_id ?? "").trim();
}

function protocolOrEmpty(standardView: TaskGraphStandardView | null): TaskGraphMemoryProtocol {
  return standardView?.memory_protocol ?? {
    repositories: [],
    collections: [],
    read_edges: [],
    write_edges: [],
    commit_edges: [],
    issues: [],
    summary: {},
  };
}

function contentRequiresCanonical(collection: TaskGraphMemoryProtocolCollection | TaskGraphMemoryProtocolEdge) {
  return asRecord(collection.content_requirement).canonical_text_required === true;
}

function contentAllowsRefsOnly(collection: TaskGraphMemoryProtocolCollection | TaskGraphMemoryProtocolEdge) {
  return asRecord(collection.content_requirement).artifact_ref_only_allowed === true;
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
      runtimeSemantics: {} as Record<string, unknown>,
    };
  }

  const phases = standardView.timeline?.phases ?? [];
  const temporalEdges = standardView.timeline?.temporal_edges ?? [];
  const loopFrames = standardView.timeline?.loop_frames ?? [];
  const timelineBlocks = standardView.timeline?.timeline_blocks ?? [];
  const runtimeSpec = asRecord(standardView.diagnostics?.runtime_spec);
  const runtimeSpecDiagnostics = asRecord(runtimeSpec.diagnostics);
  const runtimeSemantics = asRecord(standardView.timeline?.runtime_semantics ?? runtimeSpecDiagnostics.runtime_semantics);
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
    runtimeSemantics,
  };
}

export function buildTaskGraphMemoryProtocolStandardModel(standardView: TaskGraphStandardView | null) {
  const protocol = protocolOrEmpty(standardView);
  const repositories = (protocol.repositories ?? []) as TaskGraphMemoryProtocolRepository[];
  const collections = (protocol.collections ?? []) as TaskGraphMemoryProtocolCollection[];
  const readEdges = (protocol.read_edges ?? []) as TaskGraphMemoryProtocolEdge[];
  const writeEdges = (protocol.write_edges ?? []) as TaskGraphMemoryProtocolEdge[];
  const commitEdges = (protocol.commit_edges ?? []) as TaskGraphMemoryProtocolEdge[];
  const issues = protocol.issues ?? [];
  const edges = [...readEdges, ...writeEdges, ...commitEdges];
  const collectionsByRepository = new Map<string, TaskGraphMemoryProtocolCollection[]>();
  for (const collection of collections) {
    const repositoryId = String(collection.repository_id ?? "").trim();
    collectionsByRepository.set(repositoryId, [...(collectionsByRepository.get(repositoryId) ?? []), collection]);
  }
  const edgesByRepository = new Map<string, TaskGraphMemoryProtocolEdge[]>();
  for (const edge of edges) {
    const repositoryId = String(edge.repository_id ?? "").trim();
    edgesByRepository.set(repositoryId, [...(edgesByRepository.get(repositoryId) ?? []), edge]);
  }

  return {
    protocol,
    repositories,
    collections,
    readEdges,
    writeEdges,
    commitEdges,
    edges,
    issues,
    collectionsByRepository,
    edgesByRepository,
    repositoryCount: repositories.length,
    collectionCount: collections.length,
    readEdgeCount: readEdges.length,
    writeEdgeCount: writeEdges.length,
    commitEdgeCount: commitEdges.length,
    issueCount: issues.length,
    canonicalCollectionCount: collections.filter(contentRequiresCanonical).length,
    refsOnlyCollectionCount: collections.filter(contentAllowsRefsOnly).length,
    canonicalEdgeCount: edges.filter(contentRequiresCanonical).length,
    refsOnlyEdgeCount: edges.filter(contentAllowsRefsOnly).length,
    hasProtocol: Boolean(standardView?.memory_protocol),
  };
}

export function buildTaskGraphComposableStandardModel(standardView: TaskGraphStandardView | null) {
  if (!standardView) {
    return {
      units: [] as ComposableUnitSpec[],
      nodeUnits: [] as ComposableUnitSpec[],
      graphModules: [] as ComposableUnitSpec[],
      resourceUnits: [] as ComposableUnitSpec[],
      humanGateUnits: [] as ComposableUnitSpec[],
      toolUnits: [] as ComposableUnitSpec[],
      runtimeMonitorUnits: [] as ComposableUnitSpec[],
      interfaces: [] as UnitInterfaceSpec[],
      portEdges: [] as UnitPortEdgeSpec[],
      graphModuleRuntime: [] as NonNullable<TaskGraphStandardView["graph_module_runtime"]>,
      graphModuleExpansions: [] as NonNullable<TaskGraphStandardView["graph_module_expansions"]>,
      graphModuleExpansionByUnitId: new Map<string, GraphModuleExpansionSpec>(),
      interfaceByUnitId: new Map<string, UnitInterfaceSpec>(),
      portEdgesByUnitId: new Map<string, UnitPortEdgeSpec[]>(),
      expandedNodeCount: 0,
      expandedEdgeCount: 0,
      issueCount: 0,
    };
  }

  const units = standardView.units ?? [];
  const interfaces = standardView.interfaces ?? [];
  const portEdges = standardView.port_edges ?? [];
  const graphModuleRuntime = standardView.graph_module_runtime ?? [];
  const graphModuleExpansions = standardView.graph_module_expansions ?? [];
  const graphModuleExpansionByUnitId = new Map(
    graphModuleExpansions
      .map((item) => [expansionUnitId(item), item] as const)
      .filter(([unitId]) => Boolean(unitId)),
  );
  const interfaceByUnitId = new Map(interfaces.map((item) => [item.unit_id, item]));
  const portEdgesByUnitId = new Map<string, UnitPortEdgeSpec[]>();
  for (const edge of portEdges) {
    for (const unitId of [edge.source_unit_id, edge.target_unit_id]) {
      const existing = portEdgesByUnitId.get(unitId) ?? [];
      existing.push(edge);
      portEdgesByUnitId.set(unitId, existing);
    }
  }

  return {
    units,
    nodeUnits: units.filter((unit) => unit.unit_type === "node"),
    graphModules: units.filter((unit) => unit.unit_type === "graph"),
    resourceUnits: units.filter((unit) => unit.unit_type === "resource"),
    humanGateUnits: units.filter((unit) => unit.unit_type === "human_gate"),
    toolUnits: units.filter((unit) => unit.unit_type === "tool"),
    runtimeMonitorUnits: units.filter((unit) => unit.unit_type === "runtime_monitor"),
    interfaces,
    portEdges,
    graphModuleRuntime,
    graphModuleExpansions,
    graphModuleExpansionByUnitId,
    interfaceByUnitId,
    portEdgesByUnitId,
    expandedNodeCount: graphModuleExpansions.reduce((total, item) => total + (item.nodes?.length ?? 0), 0),
    expandedEdgeCount: graphModuleExpansions.reduce((total, item) => total + (item.edges?.length ?? 0), 0),
    issueCount: (standardView.issues ?? []).filter((issue) => issue.unit_id || issue.code.startsWith("port_edge_") || issue.code.startsWith("graph_module_")).length
      + graphModuleExpansions.reduce((total, item) => total + (item.issues?.length ?? 0), 0),
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
