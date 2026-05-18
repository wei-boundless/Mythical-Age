export type TaskGraphMemoryOperation = "read" | "write_candidate" | "commit";

export type TaskGraphMemoryCollectionView = {
  columnId: string;
  repositoryNodeId: string;
  repositoryId: string;
  repositoryTitle: string;
  collectionId: string;
  title: string;
  schemaId: string;
  recordKinds: string[];
  keyStrategy: string;
  defaultVersionSelector: string;
  requiredCommitStatus: string;
  synthetic: boolean;
};

export type TaskGraphMemoryRepositoryView = {
  nodeId: string;
  repositoryId: string;
  title: string;
  schemaId: string;
  lifecyclePolicy: Record<string, unknown>;
  collections: TaskGraphMemoryCollectionView[];
  synthetic: boolean;
  node?: Record<string, unknown>;
};

export type TaskGraphMemoryEdgeView = {
  edgeId: string;
  edgeType: string;
  operation: TaskGraphMemoryOperation;
  sourceNodeId: string;
  targetNodeId: string;
  taskNodeId: string;
  repositoryNodeId: string;
  repositoryId: string;
  collectionId: string;
  columnId: string;
  selector: Record<string, unknown>;
  versionSelector: string;
  onMissing: string;
  modelVisibleLabel: string;
  usageInstruction: string;
  commitVisibilityPolicy: Record<string, unknown>;
  hasCommitPath: boolean;
  edge: Record<string, unknown>;
};

export type TaskGraphMemoryMatrixCell = {
  rowNodeId: string;
  columnId: string;
  repositoryNodeId: string;
  repositoryId: string;
  collectionId: string;
  operations: TaskGraphMemoryOperation[];
  label: string;
  readEdge?: TaskGraphMemoryEdgeView;
  writeCandidateEdge?: TaskGraphMemoryEdgeView;
  commitEdge?: TaskGraphMemoryEdgeView;
  edges: TaskGraphMemoryEdgeView[];
};

export type TaskGraphMemoryMatrixRow = {
  nodeId: string;
  title: string;
  phaseId: string;
  node: Record<string, unknown>;
  cells: TaskGraphMemoryMatrixCell[];
};

export type TaskGraphMemorySnapshotPreview = {
  nodeId: string;
  title: string;
  reads: TaskGraphMemoryEdgeView[];
  writeCandidates: TaskGraphMemoryEdgeView[];
  commits: TaskGraphMemoryEdgeView[];
  handoffs: Array<Record<string, unknown>>;
  issues: string[];
};

export type TaskGraphMemoryModel = {
  repositories: TaskGraphMemoryRepositoryView[];
  columns: TaskGraphMemoryCollectionView[];
  taskNodes: Array<Record<string, unknown>>;
  memoryEdges: TaskGraphMemoryEdgeView[];
  matrixRows: TaskGraphMemoryMatrixRow[];
  snapshots: TaskGraphMemorySnapshotPreview[];
  snapshotByNodeId: Map<string, TaskGraphMemorySnapshotPreview>;
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function asRecordArray(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    : [];
}

function stringValue(value: unknown, fallback = "") {
  const next = String(value ?? "").trim();
  return next || fallback;
}

function stringArray(value: unknown): string[] {
  if (typeof value === "string") {
    return value.split(/[\n,，]/).map((item) => item.trim()).filter(Boolean);
  }
  if (!Array.isArray(value)) return [];
  return value.map((item) => stringValue(item)).filter(Boolean);
}

function nodeIdOf(node: Record<string, unknown>, index = 0) {
  return stringValue(node.node_id ?? node.id, `node_${index + 1}`);
}

function nodeTitle(node: Record<string, unknown>, index = 0) {
  return stringValue(node.title ?? node.label ?? node.task_title, nodeIdOf(node, index));
}

export function taskGraphEdgeId(edge: Record<string, unknown>, index = 0) {
  const source = taskGraphEdgeSource(edge);
  const target = taskGraphEdgeTarget(edge);
  return stringValue(edge.edge_id ?? edge.id, `${source || "source"}_${target || "target"}_${index + 1}`);
}

export function taskGraphEdgeSource(edge: Record<string, unknown>) {
  return stringValue(edge.source_node_id ?? edge.from ?? edge.source);
}

export function taskGraphEdgeTarget(edge: Record<string, unknown>) {
  return stringValue(edge.target_node_id ?? edge.to ?? edge.target);
}

function sanitizeId(value: string) {
  return value.replace(/[^a-zA-Z0-9_.:-]+/g, "_").replace(/^_+|_+$/g, "") || "item";
}

export function taskGraphMemoryColumnId(repositoryId: string, collectionId: string) {
  return `${repositoryId}::${collectionId || "default"}`;
}

function isMemoryRepositoryNode(node: Record<string, unknown>) {
  const nodeType = stringValue(node.node_type).toLowerCase();
  const nodeId = stringValue(node.node_id).toLowerCase();
  const workPosture = stringValue(node.work_posture).toLowerCase();
  if (nodeType === "artifact_repository") return false;
  return (
    nodeType === "memory_repository"
    || nodeType === "working_memory_store"
    || nodeType === "runtime_state_store"
    || nodeType === "thread_ledger"
    || nodeType === "progress_ledger"
    || nodeType === "issue_ledger"
    || (nodeType.includes("repository") && !nodeType.includes("artifact"))
    || (workPosture === "resource" && nodeId.startsWith("memory."))
    || nodeId.startsWith("memory.repository")
  );
}

function isTaskNode(node: Record<string, unknown>) {
  return !isMemoryRepositoryNode(node) && stringValue(node.node_type) !== "memory_collection";
}

function collectionViews(
  repositoryNodeId: string,
  repositoryId: string,
  repositoryTitle: string,
  schemaId: string,
  metadata: Record<string, unknown>,
  synthetic: boolean,
): TaskGraphMemoryCollectionView[] {
  const repositoryConfig = asRecord(metadata.memory_repository);
  const rawCollections = Array.isArray(repositoryConfig.collections)
    ? repositoryConfig.collections
    : Array.isArray(metadata.collections)
      ? metadata.collections
      : [];
  const records = rawCollections.length ? rawCollections : ["default"];
  return records.map((item, index) => {
    const record = typeof item === "string" ? { collection_id: item, title: item } : asRecord(item);
    const collectionId = stringValue(record.collection_id ?? record.id ?? record.name, index === 0 ? "default" : `collection_${index + 1}`);
    return {
      columnId: taskGraphMemoryColumnId(repositoryId, collectionId),
      repositoryNodeId,
      repositoryId,
      repositoryTitle,
      collectionId,
      title: stringValue(record.title ?? record.label, collectionId),
      schemaId: stringValue(record.schema_ref ?? record.schema_id, schemaId),
      recordKinds: stringArray(record.record_kinds ?? record.kinds),
      keyStrategy: stringValue(record.key_strategy, "stable_key"),
      defaultVersionSelector: stringValue(record.default_version_selector, "latest_committed_before_clock"),
      requiredCommitStatus: stringValue(record.required_commit_status, "committed"),
      synthetic,
    };
  });
}

function repositoryFromNode(node: Record<string, unknown>, index: number): TaskGraphMemoryRepositoryView {
  const nodeId = nodeIdOf(node, index);
  const metadata = asRecord(node.metadata);
  const repositoryConfig = asRecord(metadata.memory_repository);
  const repositoryId = stringValue(repositoryConfig.repository_id ?? metadata.repository_id, nodeId);
  const schemaId = stringValue(repositoryConfig.schema_id ?? metadata.schema_id, "schema.memory_record");
  const title = stringValue(repositoryConfig.title ?? node.title ?? node.label, repositoryId);
  return {
    nodeId,
    repositoryId,
    title,
    schemaId,
    lifecyclePolicy: asRecord(node.resource_lifecycle_policy),
    collections: collectionViews(nodeId, repositoryId, title, schemaId, metadata, false),
    synthetic: false,
    node,
  };
}

function syntheticRepository(repositoryId: string, collectionId = "default"): TaskGraphMemoryRepositoryView {
  const nodeId = repositoryId;
  const title = repositoryId;
  return {
    nodeId,
    repositoryId,
    title,
    schemaId: "schema.memory_record",
    lifecyclePolicy: {},
    collections: [{
      columnId: taskGraphMemoryColumnId(repositoryId, collectionId || "default"),
      repositoryNodeId: nodeId,
      repositoryId,
      repositoryTitle: title,
      collectionId: collectionId || "default",
      title: collectionId || "default",
      schemaId: "schema.memory_record",
      recordKinds: [],
      keyStrategy: "stable_key",
      defaultVersionSelector: "latest_committed_before_clock",
      requiredCommitStatus: "committed",
      synthetic: true,
    }],
    synthetic: true,
  };
}

function memoryOperation(edge: Record<string, unknown>): TaskGraphMemoryOperation | "" {
  const edgeType = stringValue(edge.edge_type ?? edge.mode);
  if (edgeType === "memory_read") return "read";
  if (edgeType === "memory_write_candidate" || edgeType === "memory_write") return "write_candidate";
  if (edgeType === "memory_commit") return "commit";
  return "";
}

function repositoryLookup(repositories: TaskGraphMemoryRepositoryView[]) {
  const byAnyId = new Map<string, TaskGraphMemoryRepositoryView>();
  for (const repository of repositories) {
    byAnyId.set(repository.nodeId, repository);
    byAnyId.set(repository.repositoryId, repository);
  }
  return byAnyId;
}

function columnLookup(columns: TaskGraphMemoryCollectionView[]) {
  const byKey = new Map<string, TaskGraphMemoryCollectionView>();
  for (const column of columns) {
    byKey.set(column.columnId, column);
    byKey.set(`${column.repositoryNodeId}::${column.collectionId}`, column);
    byKey.set(`${column.repositoryId}::${column.collectionId}`, column);
  }
  return byKey;
}

function repositoryIdFromEdge(edge: Record<string, unknown>, operation: TaskGraphMemoryOperation, repositoriesById: Map<string, TaskGraphMemoryRepositoryView>) {
  const metadata = asRecord(edge.metadata);
  const source = taskGraphEdgeSource(edge);
  const target = taskGraphEdgeTarget(edge);
  const connectedRepositoryId = operation === "read" ? source : target;
  const connectedRepository = repositoriesById.get(connectedRepositoryId);
  return connectedRepository?.repositoryId || connectedRepository?.nodeId || stringValue(metadata.repository ?? metadata.repository_id);
}

function firstCollectionForRepository(repository: TaskGraphMemoryRepositoryView | undefined, requestedCollectionId: string) {
  if (!repository) return requestedCollectionId || "default";
  if (requestedCollectionId && repository.collections.some((item) => item.collectionId === requestedCollectionId)) {
    return requestedCollectionId;
  }
  return requestedCollectionId || repository.collections[0]?.collectionId || "default";
}

function versionSelectorLabel(value: unknown) {
  if (typeof value === "string") return stringValue(value);
  const record = asRecord(value);
  return stringValue(record.mode ?? record.strategy ?? record.version_id, "latest_committed_before_clock");
}

function buildReachable(edges: Array<Record<string, unknown>>) {
  const nextBySource = new Map<string, string[]>();
  for (const edge of edges) {
    const source = taskGraphEdgeSource(edge);
    const target = taskGraphEdgeTarget(edge);
    if (!source || !target) continue;
    nextBySource.set(source, [...(nextBySource.get(source) ?? []), target]);
  }
  return (start: string, target: string) => {
    if (!start || !target) return false;
    if (start === target) return true;
    const queue = [start];
    const visited = new Set<string>();
    while (queue.length) {
      const current = queue.shift() ?? "";
      if (current === target) return true;
      if (visited.has(current)) continue;
      visited.add(current);
      queue.push(...(nextBySource.get(current) ?? []).filter((nodeId) => !visited.has(nodeId)));
    }
    return false;
  };
}

function buildMemoryEdge(
  edge: Record<string, unknown>,
  index: number,
  repositoriesById: Map<string, TaskGraphMemoryRepositoryView>,
  columnsByKey: Map<string, TaskGraphMemoryCollectionView>,
): TaskGraphMemoryEdgeView | null {
  const operation = memoryOperation(edge);
  if (!operation) return null;
  const edgeId = taskGraphEdgeId(edge, index);
  const sourceNodeId = taskGraphEdgeSource(edge);
  const targetNodeId = taskGraphEdgeTarget(edge);
  const metadata = asRecord(edge.metadata);
  const selector = asRecord(metadata.selector);
  const requestedRepositoryId = repositoryIdFromEdge(edge, operation, repositoriesById);
  const repository = repositoriesById.get(requestedRepositoryId);
  if (!requestedRepositoryId || !repository) return null;
  const requestedCollectionId = stringValue(selector.collection ?? metadata.collection);
  const collectionId = firstCollectionForRepository(repository, requestedCollectionId);
  const column = columnsByKey.get(`${repository.repositoryId}::${collectionId}`)
    ?? columnsByKey.get(`${repository.nodeId}::${collectionId}`)
    ?? repository.collections[0];
  if (!column) return null;
  const versionSelector = versionSelectorLabel(metadata.version_selector ?? selector.version_selector ?? column.defaultVersionSelector);
  const taskNodeId = operation === "read" ? targetNodeId : sourceNodeId;
  return {
    edgeId,
    edgeType: stringValue(edge.edge_type ?? edge.mode),
    operation,
    sourceNodeId,
    targetNodeId,
    taskNodeId,
    repositoryNodeId: repository.nodeId,
    repositoryId: repository.repositoryId,
    collectionId: column.collectionId,
    columnId: column.columnId,
    selector: {
      ...selector,
      collection: stringValue(selector.collection ?? metadata.collection, column.collectionId),
    },
    versionSelector,
    onMissing: stringValue(metadata.on_missing, operation === "read" ? "block" : "warn"),
    modelVisibleLabel: stringValue(metadata.model_visible_label ?? metadata.visible_label ?? selector.model_visible_label),
    usageInstruction: stringValue(metadata.usage_instruction ?? metadata.instructions ?? selector.usage_instruction),
    commitVisibilityPolicy: asRecord(metadata.commit_visibility_policy ?? metadata.visibility_policy ?? edge.commit_visibility_policy),
    hasCommitPath: false,
    edge,
  };
}

function operationLabel(operations: TaskGraphMemoryOperation[]) {
  if (operations.includes("read") && operations.includes("write_candidate")) return "读 / 写候选";
  if (operations.includes("commit")) return operations.includes("read") ? "读 / 提交" : "提交";
  if (operations.includes("read")) return "读取";
  if (operations.includes("write_candidate")) return "写候选";
  return "禁止";
}

function buildCell(
  rowNodeId: string,
  column: TaskGraphMemoryCollectionView,
  memoryEdges: TaskGraphMemoryEdgeView[],
): TaskGraphMemoryMatrixCell {
  const edges = memoryEdges.filter((edge) => edge.taskNodeId === rowNodeId && edge.columnId === column.columnId);
  const operations = Array.from(new Set(edges.map((edge) => edge.operation)));
  return {
    rowNodeId,
    columnId: column.columnId,
    repositoryNodeId: column.repositoryNodeId,
    repositoryId: column.repositoryId,
    collectionId: column.collectionId,
    operations,
    label: operationLabel(operations),
    readEdge: edges.find((edge) => edge.operation === "read"),
    writeCandidateEdge: edges.find((edge) => edge.operation === "write_candidate"),
    commitEdge: edges.find((edge) => edge.operation === "commit"),
    edges,
  };
}

function handoffEdgesForNode(nodeId: string, edges: Array<Record<string, unknown>>) {
  return edges.filter((edge) => {
    const edgeType = stringValue(edge.edge_type ?? edge.mode);
    if (edgeType.startsWith("memory_")) return false;
    return taskGraphEdgeTarget(edge) === nodeId && Object.keys(asRecord(edge.working_memory_handoff_policy)).length > 0;
  });
}

function snapshotForNode(
  node: Record<string, unknown>,
  index: number,
  memoryEdges: TaskGraphMemoryEdgeView[],
  allEdges: Array<Record<string, unknown>>,
): TaskGraphMemorySnapshotPreview {
  const nodeId = nodeIdOf(node, index);
  const reads = memoryEdges.filter((edge) => edge.taskNodeId === nodeId && edge.operation === "read");
  const writeCandidates = memoryEdges.filter((edge) => edge.taskNodeId === nodeId && edge.operation === "write_candidate");
  const commits = memoryEdges.filter((edge) => edge.taskNodeId === nodeId && edge.operation === "commit");
  const issues: string[] = [];
  for (const edge of reads) {
    if (!Object.keys(edge.selector).length || !stringValue(edge.selector.collection)) {
      issues.push(`${edge.edgeId} 缺少 selector.collection`);
    }
    if (!edge.usageInstruction) {
      issues.push(`${edge.edgeId} 缺少 usage_instruction`);
    }
  }
  for (const edge of writeCandidates) {
    if (!edge.hasCommitPath) {
      issues.push(`${edge.edgeId} 写入候选没有可达 memory_commit 路径`);
    }
  }
  for (const edge of commits) {
    if (!Object.keys(edge.commitVisibilityPolicy).length) {
      issues.push(`${edge.edgeId} 提交边缺少 commit_visibility_policy`);
    }
  }
  return {
    nodeId,
    title: nodeTitle(node, index),
    reads,
    writeCandidates,
    commits,
    handoffs: handoffEdgesForNode(nodeId, allEdges),
    issues,
  };
}

export function buildTaskGraphMemoryModel({
  nodes,
  edges,
}: {
  nodes: Array<Record<string, unknown>>;
  edges: Array<Record<string, unknown>>;
}): TaskGraphMemoryModel {
  const repositoriesByNode = nodes
    .map((node, index) => ({ node, index }))
    .filter(({ node }) => isMemoryRepositoryNode(node))
    .map(({ node, index }) => repositoryFromNode(node, index));
  const repositoryById = repositoryLookup(repositoriesByNode);

  const syntheticById = new Map<string, TaskGraphMemoryRepositoryView>();
  for (const edge of edges) {
    const operation = memoryOperation(edge);
    if (!operation) continue;
    const metadata = asRecord(edge.metadata);
    const selector = asRecord(metadata.selector);
    const requestedRepositoryId = repositoryIdFromEdge(edge, operation, repositoryById);
    if (!requestedRepositoryId || repositoryById.has(requestedRepositoryId) || syntheticById.has(requestedRepositoryId)) {
      continue;
    }
    syntheticById.set(requestedRepositoryId, syntheticRepository(requestedRepositoryId, stringValue(selector.collection ?? metadata.collection, "default")));
  }

  const repositories = [...repositoriesByNode, ...syntheticById.values()];
  const repositoriesById = repositoryLookup(repositories);
  const columns = repositories.flatMap((repository) => repository.collections);
  const columnsByKey = columnLookup(columns);
  const reachable = buildReachable(edges);
  const memoryEdges = edges
    .map((edge, index) => buildMemoryEdge(edge, index, repositoriesById, columnsByKey))
    .filter((edge): edge is TaskGraphMemoryEdgeView => Boolean(edge));

  const commitEdges = memoryEdges.filter((edge) => edge.operation === "commit");
  const memoryEdgesWithCommitPath = memoryEdges.map((edge) => {
    if (edge.operation !== "write_candidate") return edge;
    const hasCommitPath = commitEdges.some((commitEdge) => (
      commitEdge.repositoryId === edge.repositoryId
      && commitEdge.collectionId === edge.collectionId
      && reachable(edge.taskNodeId, commitEdge.taskNodeId)
    ));
    return { ...edge, hasCommitPath };
  });

  const taskNodes = nodes.filter(isTaskNode);
  const matrixRows = taskNodes.map((node, index) => {
    const nodeId = nodeIdOf(node, index);
    return {
      nodeId,
      title: nodeTitle(node, index),
      phaseId: stringValue(node.phase_id, "phase.unassigned"),
      node,
      cells: columns.map((column) => buildCell(nodeId, column, memoryEdgesWithCommitPath)),
    };
  });
  const snapshots = taskNodes.map((node, index) => snapshotForNode(node, index, memoryEdgesWithCommitPath, edges));
  const snapshotByNodeId = new Map(snapshots.map((snapshot) => [snapshot.nodeId, snapshot]));

  return {
    repositories,
    columns,
    taskNodes,
    memoryEdges: memoryEdgesWithCommitPath,
    matrixRows,
    snapshots,
    snapshotByNodeId,
  };
}

export function createMemoryEdgeDraft({
  operation,
  repositoryNodeId,
  repositoryId,
  collectionId,
  taskNodeId,
}: {
  operation: TaskGraphMemoryOperation;
  repositoryNodeId: string;
  repositoryId: string;
  collectionId: string;
  taskNodeId: string;
}): Record<string, unknown> {
  const edgeType = operation === "write_candidate" ? "memory_write_candidate" : operation === "commit" ? "memory_commit" : "memory_read";
  const source = operation === "read" ? repositoryNodeId : taskNodeId;
  const target = operation === "read" ? taskNodeId : repositoryNodeId;
  return {
    edge_id: `edge.${edgeType}.${sanitizeId(taskNodeId)}.${sanitizeId(repositoryId)}.${sanitizeId(collectionId)}`,
    source_node_id: source,
    target_node_id: target,
    from: source,
    to: target,
    edge_type: edgeType,
    payload_contract_id: `${edgeType}.payload`,
    metadata: {
      repository: repositoryId,
      collection: collectionId,
      selector: {
        collection: collectionId,
        status_filter: operation === "read" ? ["committed"] : [],
        limit: operation === "read" ? 50 : 0,
      },
      version_selector: operation === "read" ? { mode: "latest_committed_before_clock" } : { mode: "current_clock_acknowledgement" },
      on_missing: operation === "read" ? "block" : "warn",
      model_visible_label: operation === "read" ? collectionId : "",
      usage_instruction: operation === "read" ? "你必须按这个输入包的约束完成当前节点任务，不得把缺失信息自行补写成事实。" : "",
      commit_visibility_policy: operation === "commit" ? { required_status: "committed", visible_after: "next_clock" } : {},
    },
  };
}

export function memoryCellOperationValue(cell: TaskGraphMemoryMatrixCell) {
  if (cell.operations.includes("commit")) return "commit";
  if (cell.operations.includes("read") && cell.operations.includes("write_candidate")) return "read_write_candidate";
  if (cell.operations.includes("read")) return "read";
  if (cell.operations.includes("write_candidate")) return "write_candidate";
  return "forbidden";
}
