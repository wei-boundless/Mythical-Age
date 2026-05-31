"use client";

import { useEffect, useMemo, useState } from "react";
import { Database, FileStack, Plus } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import {
  getArtifactRepositoryOverview,
  getFormalMemoryOverview,
  type ArtifactRepositoryOverview,
  type FormalMemoryOverview,
  type TaskGraphStandardView,
} from "@/lib/api";

import {
  buildTaskGraphMemoryProtocolStandardModel,
  buildTaskGraphResourceStandardModel,
  describeTaskGraphStandardEdge,
} from "./taskGraphStandardView";
import { TaskSystemField, TaskSystemSelectField, taskSystemOptionLabel } from "./TaskSystemWorkbenchUi";
import type { TaskGraphDraftV2 } from "./taskGraphDraftV2";
import type { TaskGraphEditorFocus } from "./taskGraphEditorFocus";
import {
  buildTaskGraphMemoryModel,
  createMemoryEdgeDraft,
  memoryCellOperationValue,
  taskGraphMemoryColumnId,
  taskGraphEdgeId,
  taskGraphEdgeSource,
  taskGraphEdgeTarget,
  type TaskGraphMemoryMatrixCell,
  type TaskGraphMemoryOperation,
  type TaskGraphMemoryRepositoryView,
} from "./taskGraphMemoryMatrix";

type MemoryFacet = "protocol" | "repositories" | "matrix" | "selector" | "snapshot" | "artifact_context" | "formal_store" | "artifact_store";
type MatrixOperationValue = "forbidden" | "read" | "write_candidate" | "read_write_candidate" | "commit";
type ResourceTemplate = {
  kind: string;
  title: string;
  idPrefix: string;
  icon: LucideIcon;
  defaultPolicy: Record<string, unknown>;
};

const RESOURCE_NODE_TEMPLATES: ResourceTemplate[] = [
  {
    kind: "memory_repository",
    title: "记忆仓库",
    idPrefix: "memory.repository",
    icon: Database,
    defaultPolicy: { versioning: "append_version", mutable: true, commit_required: true },
  },
  {
    kind: "artifact_repository",
    title: "产物仓库",
    idPrefix: "artifact.repository",
    icon: FileStack,
    defaultPolicy: { versioning: "append_version", mutable: true },
  },
];

const MATRIX_OPERATION_OPTIONS: MatrixOperationValue[] = ["forbidden", "read", "write_candidate", "read_write_candidate", "commit"];

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function defaultContentRequirement() {
  return {
    canonical_text_required: true,
    artifact_ref_only_allowed: false,
  };
}

function booleanText(value: unknown) {
  return value === true ? "是" : "否";
}

function splitList(value: string) {
  return value.split(/[\n,，]/).map((item) => item.trim()).filter(Boolean);
}

function listText(value: unknown) {
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean).join("\n") : "";
}

function compactRecord(payload: Record<string, unknown>) {
  return Object.fromEntries(
    Object.entries(payload).filter(([, value]) => value !== "" && value !== null && value !== undefined && !(Array.isArray(value) && value.length === 0)),
  );
}

function repositoryCollectionsFromNode(node?: Record<string, unknown>) {
  const metadata = asRecord(node?.metadata);
  const memoryRepository = asRecord(metadata.memory_repository);
  const rawCollections = Array.isArray(memoryRepository.collections)
    ? memoryRepository.collections
    : Array.isArray(metadata.collections)
      ? metadata.collections
      : [];
  return (rawCollections.length ? rawCollections : ["default"]).map((item, index) => {
    if (typeof item === "string") {
      return {
        collection_id: item,
        title: item,
        record_kinds: [],
        key_strategy: "stable_key",
        default_version_selector: "latest_committed_before_clock",
        required_commit_status: "committed",
        content_requirement: defaultContentRequirement(),
      };
    }
    const record = asRecord(item);
    return {
      collection_id: String(record.collection_id ?? record.id ?? `collection_${index + 1}`),
      title: String(record.title ?? record.collection_id ?? record.id ?? `collection_${index + 1}`),
      record_kinds: Array.isArray(record.record_kinds) ? record.record_kinds : [],
      key_strategy: String(record.key_strategy ?? "stable_key"),
      schema_ref: String(record.schema_ref ?? record.schema_id ?? ""),
      default_version_selector: String(record.default_version_selector ?? "latest_committed_before_clock"),
      required_commit_status: String(record.required_commit_status ?? "committed"),
      content_requirement: {
        ...defaultContentRequirement(),
        ...asRecord(record.content_requirement),
      },
    };
  });
}

function edgeMatchesCell(edge: Record<string, unknown>, cell: TaskGraphMemoryMatrixCell, index: number) {
  const edgeId = taskGraphEdgeId(edge, index);
  return cell.edges.some((item) => item.edgeId === edgeId);
}

function desiredOperations(value: MatrixOperationValue): TaskGraphMemoryOperation[] {
  if (value === "read") return ["read"];
  if (value === "write_candidate") return ["write_candidate"];
  if (value === "read_write_candidate") return ["read", "write_candidate"];
  if (value === "commit") return ["commit"];
  return [];
}

function operationLabel(value: MatrixOperationValue) {
  const labels: Record<MatrixOperationValue, string> = {
    forbidden: "禁止",
    read: "读取",
    write_candidate: "写候选",
    read_write_candidate: "读 + 写候选",
    commit: "提交",
  };
  return labels[value];
}

function semanticParameterPatchFromMemoryPatch(patch: Record<string, unknown>) {
  const selector = asRecord(patch.selector);
  const visibility = asRecord(patch.commit_visibility_policy);
  return compactRecord({
    repository_id: patch.repository_id ?? patch.repository,
    collection_id: patch.collection_id ?? patch.collection ?? selector.collection,
    record_key: patch.record_key ?? selector.record_key,
    record_kind: patch.record_kind ?? selector.record_kind,
    record_keys: selector.record_keys,
    record_kinds: selector.record_kinds,
    limit: selector.limit,
    on_missing: patch.on_missing,
    source_output_key: patch.source_output_key,
    candidate_ref_key: patch.candidate_ref_key,
    approval_source_node_id: patch.approval_source_node_id,
    verdict_key: patch.verdict_key,
    required_verdict: patch.required_verdict,
    model_visible_label: patch.model_visible_label,
    usage_instruction: patch.usage_instruction,
    version_selector: patch.version_selector,
    visible_after: visibility.visible_after,
  });
}

function artifactContextEdges(edges: Array<Record<string, unknown>>) {
  return edges.filter((edge) => {
    const edgeType = String(edge.edge_type ?? edge.mode ?? "");
    const metadata = asRecord(edge.metadata);
    return edgeType.startsWith("artifact_") || Object.keys(asRecord(edge.artifact_ref_policy)).length > 0 || String(metadata.context_mode ?? "").includes("artifact");
  });
}

export function TaskGraphMemoryArtifactPage({
  activeGraphNodes,
  activeGraphEdges,
  taskGraphDraft,
  updateTaskGraphDraft,
  updateTaskGraphEdge,
  updateTaskGraphNode,
  editorFocus,
  onEditorFocus,
  standardView,
  standardViewLoading,
}: {
  activeGraphNodes: Array<Record<string, unknown>>;
  activeGraphEdges: Array<Record<string, unknown>>;
  taskGraphDraft: TaskGraphDraftV2;
  updateTaskGraphDraft: (patch: Partial<TaskGraphDraftV2>) => void;
  updateTaskGraphEdge: (edgeId: string, patch: Record<string, unknown>) => void;
  updateTaskGraphNode: (nodeId: string, patch: Record<string, unknown>) => void;
  editorFocus?: TaskGraphEditorFocus;
  onEditorFocus?: (focus: Partial<TaskGraphEditorFocus> & { layer?: TaskGraphEditorFocus["layer"] }) => void;
  standardView: TaskGraphStandardView | null;
  standardViewLoading?: boolean;
}) {
  const [facet, setFacet] = useState<MemoryFacet>("protocol");
  const memoryModel = useMemo(
    () => buildTaskGraphMemoryModel({ nodes: activeGraphNodes, edges: activeGraphEdges }),
    [activeGraphNodes, activeGraphEdges],
  );
  const standardResourceModel = useMemo(() => buildTaskGraphResourceStandardModel(standardView), [standardView]);
  const standardProtocolModel = useMemo(() => buildTaskGraphMemoryProtocolStandardModel(standardView), [standardView]);
  const firstRepositoryId = memoryModel.repositories[0]?.nodeId ?? "";
  const firstMemoryEdgeId = memoryModel.memoryEdges[0]?.edgeId ?? "";
  const firstSnapshotNodeId = memoryModel.snapshots[0]?.nodeId ?? "";
  const [selectedRepositoryNodeId, setSelectedRepositoryNodeId] = useState(firstRepositoryId);
  const [selectedMemoryEdgeId, setSelectedMemoryEdgeId] = useState(firstMemoryEdgeId);
  const [selectedSnapshotNodeId, setSelectedSnapshotNodeId] = useState(firstSnapshotNodeId);
  const [selectedCellKey, setSelectedCellKey] = useState("");
  const [managementTaskRunId, setManagementTaskRunId] = useState("");
  const [formalOverview, setFormalOverview] = useState<FormalMemoryOverview | null>(null);
  const [artifactOverview, setArtifactOverview] = useState<ArtifactRepositoryOverview | null>(null);
  const [managementLoading, setManagementLoading] = useState(false);
  const [managementError, setManagementError] = useState("");
  const selectedRepository = memoryModel.repositories.find((repository) => repository.nodeId === selectedRepositoryNodeId)
    ?? memoryModel.repositories[0]
    ?? null;
  const selectedMemoryEdge = memoryModel.memoryEdges.find((edge) => edge.edgeId === selectedMemoryEdgeId)
    ?? memoryModel.memoryEdges[0]
    ?? null;
  const selectedSnapshot = memoryModel.snapshotByNodeId.get(selectedSnapshotNodeId)
    ?? memoryModel.snapshots[0]
    ?? null;
  const selectedCell = memoryModel.matrixRows
    .flatMap((row) => row.cells.map((cell) => ({ row, cell })))
    .find((item) => `${item.row.nodeId}:${item.cell.columnId}` === selectedCellKey)
    ?? null;

  useEffect(() => {
    if (selectedRepositoryNodeId || !firstRepositoryId) return;
    setSelectedRepositoryNodeId(firstRepositoryId);
  }, [firstRepositoryId, selectedRepositoryNodeId]);

  useEffect(() => {
    if (selectedMemoryEdgeId || !firstMemoryEdgeId) return;
    setSelectedMemoryEdgeId(firstMemoryEdgeId);
  }, [firstMemoryEdgeId, selectedMemoryEdgeId]);

  useEffect(() => {
    if (selectedSnapshotNodeId || !firstSnapshotNodeId) return;
    setSelectedSnapshotNodeId(firstSnapshotNodeId);
  }, [firstSnapshotNodeId, selectedSnapshotNodeId]);

  useEffect(() => {
    if (editorFocus?.layer !== "memory") return;
    const focusFacet = String(editorFocus.facet ?? "");
    if (["protocol", "repositories", "matrix", "selector", "snapshot", "artifact_context", "formal_store", "artifact_store"].includes(focusFacet)) {
      setFacet(focusFacet as MemoryFacet);
    }
    if (editorFocus.repository_id) {
      const focusedRepository = memoryModel.repositories.find((repository) => (
        repository.nodeId === editorFocus.repository_id || repository.repositoryId === editorFocus.repository_id
      ));
      setSelectedRepositoryNodeId(focusedRepository?.nodeId ?? editorFocus.repository_id);
    }
    if (editorFocus.edge_id) {
      setSelectedMemoryEdgeId(editorFocus.edge_id);
    }
    if (editorFocus.node_id) {
      setSelectedSnapshotNodeId(editorFocus.node_id);
    }
    if (editorFocus.node_id && editorFocus.repository_id && editorFocus.collection_id) {
      const focusedRepository = memoryModel.repositories.find((repository) => (
        repository.nodeId === editorFocus.repository_id || repository.repositoryId === editorFocus.repository_id
      ));
      setSelectedCellKey(`${editorFocus.node_id}:${taskGraphMemoryColumnId(focusedRepository?.repositoryId ?? editorFocus.repository_id, editorFocus.collection_id)}`);
    }
  }, [
    editorFocus?.collection_id,
    editorFocus?.edge_id,
    editorFocus?.facet,
    editorFocus?.layer,
    editorFocus?.node_id,
    editorFocus?.repository_id,
    memoryModel.repositories,
  ]);

  useEffect(() => {
    if (facet !== "formal_store" && facet !== "artifact_store") return;
    let cancelled = false;
    setManagementLoading(true);
    setManagementError("");
    const repositoryId = selectedRepository?.repositoryId ?? "";
    const payload = {
      task_run_id: managementTaskRunId,
      repository_id: repositoryId,
      limit: 250,
    };
    const load = facet === "formal_store" ? getFormalMemoryOverview(payload) : getArtifactRepositoryOverview(payload);
    void load
      .then((overview) => {
        if (cancelled) return;
        if (facet === "formal_store") {
          setFormalOverview(overview as FormalMemoryOverview);
        } else {
          setArtifactOverview(overview as ArtifactRepositoryOverview);
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) setManagementError(error instanceof Error ? error.message : String(error));
      })
      .finally(() => {
        if (!cancelled) setManagementLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [facet, managementTaskRunId, selectedRepository?.repositoryId]);

  const createResourceNode = (template: ResourceTemplate) => {
    const existingIds = new Set(activeGraphNodes.map((node) => String(node.node_id ?? "")));
    let index = 1;
    let nodeId = `${template.idPrefix}.${index}`;
    while (existingIds.has(nodeId)) {
      index += 1;
      nodeId = `${template.idPrefix}.${index}`;
    }
    const memoryMetadata = template.kind === "memory_repository" || template.kind.endsWith("_ledger")
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
            content_requirement: defaultContentRequirement(),
          }],
        },
      }
      : {};
    updateTaskGraphDraft({
      nodes: [
        ...(taskGraphDraft.nodes ?? []),
        {
          node_id: nodeId,
          node_type: template.kind,
          title: template.title,
          work_posture: "resource",
          resource_lifecycle_policy: template.defaultPolicy,
          metadata: memoryMetadata,
        },
      ],
    });
    setSelectedRepositoryNodeId(nodeId);
    onEditorFocus?.({ layer: "memory", facet: "repositories", node_id: nodeId, repository_id: nodeId });
  };

  const updateRepositoryNode = (repository: TaskGraphMemoryRepositoryView, patch: Record<string, unknown>) => {
    if (repository.synthetic) return;
    updateTaskGraphNode(repository.nodeId, patch);
  };

  const updateRepositoryMetadata = (repository: TaskGraphMemoryRepositoryView, patch: Record<string, unknown>) => {
    if (repository.synthetic || !repository.node) return;
    const currentMetadata = asRecord(repository.node.metadata);
    const currentMemoryRepository = asRecord(currentMetadata.memory_repository);
    updateTaskGraphNode(repository.nodeId, {
      metadata: {
        ...currentMetadata,
        memory_repository: {
          ...currentMemoryRepository,
          ...patch,
        },
      },
    });
  };

  const updateRepositoryCollection = (repository: TaskGraphMemoryRepositoryView, collectionId: string, patch: Record<string, unknown>) => {
    if (repository.synthetic || !repository.node) return;
    const currentMetadata = asRecord(repository.node.metadata);
    const currentMemoryRepository = asRecord(currentMetadata.memory_repository);
    const collections = repositoryCollectionsFromNode(repository.node);
    const nextCollections = collections.map((collection) => (
      String(collection.collection_id) === collectionId ? { ...collection, ...patch } : collection
    ));
    updateTaskGraphNode(repository.nodeId, {
      metadata: {
        ...currentMetadata,
        memory_repository: {
          ...currentMemoryRepository,
          repository_id: String(currentMemoryRepository.repository_id ?? repository.repositoryId),
          schema_id: String(currentMemoryRepository.schema_id ?? repository.schemaId),
          collections: nextCollections,
        },
      },
    });
  };

  const addRepositoryCollection = (repository: TaskGraphMemoryRepositoryView) => {
    if (repository.synthetic || !repository.node) return;
    const currentMetadata = asRecord(repository.node.metadata);
    const currentMemoryRepository = asRecord(currentMetadata.memory_repository);
    const collections = repositoryCollectionsFromNode(repository.node);
    const nextId = `collection_${collections.length + 1}`;
    updateTaskGraphNode(repository.nodeId, {
      metadata: {
        ...currentMetadata,
        memory_repository: {
          ...currentMemoryRepository,
          repository_id: String(currentMemoryRepository.repository_id ?? repository.repositoryId),
          schema_id: String(currentMemoryRepository.schema_id ?? repository.schemaId),
          collections: [
            ...collections,
            {
              collection_id: nextId,
              title: nextId,
              record_kinds: [],
              key_strategy: "stable_key",
              default_version_selector: "latest_committed_before_clock",
              required_commit_status: "committed",
              content_requirement: defaultContentRequirement(),
            },
          ],
        },
      },
    });
  };

  const setCellOperation = (cell: TaskGraphMemoryMatrixCell, value: MatrixOperationValue) => {
    const desired = desiredOperations(value);
    const existingByOperation = new Map(cell.edges.map((edge) => [edge.operation, edge.edge]));
    const nextEdges = (taskGraphDraft.edges ?? []).filter((edge, index) => !edgeMatchesCell(edge, cell, index));
    const created = desired.map((operation) => existingByOperation.get(operation) ?? createMemoryEdgeDraft({
      operation,
      repositoryNodeId: cell.repositoryNodeId,
      repositoryId: cell.repositoryId,
      collectionId: cell.collectionId,
      taskNodeId: cell.rowNodeId,
    }));
    updateTaskGraphDraft({ edges: [...nextEdges, ...created] as TaskGraphDraftV2["edges"] });
  };

  const patchSelectedMemoryEdgeMetadata = (patch: Record<string, unknown>) => {
    if (!selectedMemoryEdge) return;
    const edgeMetadata = asRecord(selectedMemoryEdge.edge.metadata);
    const semanticParameters = compactRecord({
      ...asRecord(edgeMetadata.semantic_parameters),
      ...semanticParameterPatchFromMemoryPatch(patch),
    });
    updateTaskGraphEdge(selectedMemoryEdge.edgeId, {
      metadata: { ...edgeMetadata, ...patch, semantic_parameters: semanticParameters },
    });
  };

  const artifactEdges = artifactContextEdges(activeGraphEdges);

  return (
    <section className="task-graph-studio-page">
      <header className="task-graph-studio-page__head">
        <span>图工作台</span>
        <strong>资源流</strong>
        <small>用仓库节点、读写边、selector 和提交可见性决定节点实际能读到什么、能写入什么。</small>
      </header>

      <section className="task-graph-facet-switch" aria-label="资源流配置分面">
        {[
          ["protocol", "协议视图", "repository / collection / edge"],
          ["repositories", "仓库结构", "repository / collection"],
          ["matrix", "读写矩阵", "node x collection"],
          ["selector", "Selector 配置", "read / version / visibility"],
          ["snapshot", "Snapshot 预览", "node input preview"],
          ["artifact_context", "产物上下文", "artifact packet"],
          ["formal_store", "记忆库管理", "run records / logs"],
          ["artifact_store", "产物库管理", "run artifacts"],
        ].map(([id, title, desc]) => (
          <button className={facet === id ? "active" : ""} key={id} onClick={() => setFacet(id as MemoryFacet)} type="button">
            <strong>{title}</strong>
            <span>{desc}</span>
          </button>
        ))}
      </section>

      <section className="task-graph-standard-board" aria-label="资源标准对象摘要">
        <article className="boundary-card task-graph-standard-card">
          <header><strong>标准资源对象</strong><span>{standardViewLoading ? "编译中" : `${standardResourceModel.resources.length} resources`}</span></header>
          <div className="task-graph-mini-kv">
            <p><span>记忆仓库</span><strong>{standardResourceModel.memoryResources.length}</strong></p>
            <p><span>产物仓库</span><strong>{standardResourceModel.artifactResources.length}</strong></p>
            <p><span>记忆边</span><strong>{standardResourceModel.memoryEdges.length}</strong></p>
            <p><span>产物边</span><strong>{standardResourceModel.artifactEdges.length}</strong></p>
          </div>
          <div className="task-graph-note">
            <strong>资源页以标准对象视图校对当前配置</strong>
            <span>前端矩阵和 selector 只是编辑手段；后端编译出的 resource / edge / isolation 才是 runtime 最终消费的结构。</span>
          </div>
        </article>
        <article className="boundary-card task-graph-standard-card">
          <header><strong>运行隔离</strong><span>{standardResourceModel.runtimeIsolation?.task_run_scope_policy ?? "isolated_per_task_run"}</span></header>
          <div className="task-graph-mini-kv">
            <p><span>记忆隔离库</span><strong>{standardResourceModel.runtimeIsolation?.memory_repositories.length ?? 0}</strong></p>
            <p><span>产物隔离库</span><strong>{standardResourceModel.runtimeIsolation?.artifact_repositories.length ?? 0}</strong></p>
            <p><span>状态库</span><strong>{standardResourceModel.runtimeIsolation?.runtime_state_stores.length ?? 0}</strong></p>
            <p><span>诊断问题</span><strong>{standardResourceModel.issueCount}</strong></p>
          </div>
        </article>
        <article className="boundary-card task-graph-standard-card">
          <header><strong>Memory Protocol</strong><span>{standardProtocolModel.hasProtocol ? "standard view" : "未载入"}</span></header>
          <div className="task-graph-mini-kv">
            <p><span>仓库</span><strong>{standardProtocolModel.repositoryCount}</strong></p>
            <p><span>集合</span><strong>{standardProtocolModel.collectionCount}</strong></p>
            <p><span>读取边</span><strong>{standardProtocolModel.readEdgeCount}</strong></p>
            <p><span>写入边</span><strong>{standardProtocolModel.writeEdgeCount}</strong></p>
            <p><span>提交边</span><strong>{standardProtocolModel.commitEdgeCount}</strong></p>
            <p><span>协议问题</span><strong>{standardProtocolModel.issueCount}</strong></p>
          </div>
        </article>
      </section>

      {facet === "protocol" ? (
        <section className="task-graph-memory-workbench">
          <aside className="boundary-card task-graph-memory-sidebar">
            <header><strong>协议仓库</strong><span>{standardProtocolModel.repositoryCount} repositories</span></header>
            <div className="task-graph-mini-kv">
              <p><span>canonical</span><strong>{standardProtocolModel.canonicalCollectionCount}</strong></p>
              <p><span>refs-only</span><strong>{standardProtocolModel.refsOnlyCollectionCount}</strong></p>
              <p><span>canonical edges</span><strong>{standardProtocolModel.canonicalEdgeCount}</strong></p>
              <p><span>refs-only edges</span><strong>{standardProtocolModel.refsOnlyEdgeCount}</strong></p>
            </div>
            <div className="task-graph-cognition-list">
              {standardProtocolModel.repositories.map((repository) => {
                const repositoryId = String(repository.repository_id ?? repository.repository_node_id ?? "");
                return (
                  <button
                    className={selectedRepositoryNodeId === String(repository.repository_node_id ?? repositoryId) ? "task-graph-memory-list-button task-graph-memory-list-button--active" : "task-graph-memory-list-button"}
                    key={repositoryId}
                    onClick={() => {
                      setSelectedRepositoryNodeId(String(repository.repository_node_id ?? repositoryId));
                      onEditorFocus?.({ layer: "memory", facet: "protocol", repository_id: repositoryId, node_id: String(repository.repository_node_id ?? "") });
                    }}
                    type="button"
                  >
                    <strong>{String(repository.title ?? repositoryId)}</strong>
                    <span>{repositoryId}</span>
                    <em>{standardProtocolModel.collectionsByRepository.get(repositoryId)?.length ?? 0} collections / {standardProtocolModel.edgesByRepository.get(repositoryId)?.length ?? 0} edges</em>
                  </button>
                );
              })}
              {!standardProtocolModel.repositories.length ? (
                <div className="task-graph-note">
                  <strong>没有协议仓库</strong>
                  <span>保存并刷新标准视图后，后端会输出规范化 memory protocol。</span>
                </div>
              ) : null}
            </div>
          </aside>

          <article className="boundary-card task-graph-memory-detail">
            <header><strong>Collection 协议</strong><span>{standardProtocolModel.collectionCount} collections</span></header>
            <div className="task-graph-node-policy-list">
              {standardProtocolModel.collections.map((collection) => {
                const requirement = asRecord(collection.content_requirement);
                return (
                  <article className="task-graph-node-policy-row task-graph-node-policy-row--wide" key={`${collection.repository_id}.${collection.collection_id}`}>
                    <div className="task-graph-node-policy-row__identity">
                      <strong>{String(collection.title ?? collection.collection_id)}</strong>
                      <span>{collection.repository_id}.{collection.collection_id}</span>
                    </div>
                    <div className="task-graph-mini-kv">
                      <p><span>schema</span><strong>{String(collection.schema_id ?? "未设置")}</strong></p>
                      <p><span>canonical</span><strong>{booleanText(requirement.canonical_text_required)}</strong></p>
                      <p><span>refs-only</span><strong>{booleanText(requirement.artifact_ref_only_allowed)}</strong></p>
                      <p><span>record kinds</span><strong>{(collection.record_kinds ?? []).length}</strong></p>
                    </div>
                    <small>{(collection.record_kinds ?? []).join(" / ") || "未声明 record kind"}</small>
                  </article>
                );
              })}
              {!standardProtocolModel.collections.length ? (
                <div className="task-graph-note">
                  <strong>没有 collection specs</strong>
                  <span>在仓库结构中声明 collection_specs 或 metadata.memory_repository.collections。</span>
                </div>
              ) : null}
            </div>
          </article>

          <article className="boundary-card task-graph-memory-detail">
            <header><strong>协议边与问题</strong><span>{standardProtocolModel.edges.length} edges / {standardProtocolModel.issueCount} issues</span></header>
            <div className="task-graph-cognition-section">
              <header><strong>Read / Write / Commit</strong><span>后端规范化结果</span></header>
              <div className="task-graph-cognition-list">
                {standardProtocolModel.edges.slice(0, 80).map((edge) => {
                  const requirement = asRecord(edge.content_requirement);
                  return (
                    <button
                      className={selectedMemoryEdgeId === edge.edge_id ? "task-graph-memory-list-button task-graph-memory-list-button--active" : "task-graph-memory-list-button"}
                      key={edge.edge_id}
                      onClick={() => {
                        setSelectedMemoryEdgeId(edge.edge_id);
                        setFacet("selector");
                        onEditorFocus?.({ layer: "memory", facet: "selector", edge_id: edge.edge_id, repository_id: edge.repository_id, collection_id: edge.collection_id });
                      }}
                      type="button"
                    >
                      <strong>{edge.operation} · {edge.repository_id}.{edge.collection_id}</strong>
                      <span>{String(edge.source_node_id ?? "")} {"->"} {String(edge.target_node_id ?? "")}</span>
                      <em>{booleanText(requirement.canonical_text_required)} canonical / {booleanText(requirement.artifact_ref_only_allowed)} refs-only</em>
                    </button>
                  );
                })}
              </div>
            </div>
            <div className="task-graph-cognition-section">
              <header><strong>协议问题</strong><span>{standardProtocolModel.issueCount} 条</span></header>
              <div className="task-graph-cognition-list">
                {standardProtocolModel.issues.map((issue, index) => (
                  <article className={String(issue.severity ?? "error") === "error" ? "task-graph-cognition-item task-graph-cognition-item--warn" : "task-graph-cognition-item"} key={`${String(issue.code ?? "issue")}-${index}`}>
                    <div><strong>{String(issue.code ?? "memory_protocol_issue")}</strong><span>{String(issue.severity ?? "error")}</span></div>
                    <p>{String(issue.message ?? "后端协议返回了未命名问题。")}</p>
                    <em>{String(issue.edge_id ?? issue.node_id ?? "graph")}</em>
                  </article>
                ))}
                {!standardProtocolModel.issues.length ? (
                  <div className="task-graph-note">
                    <strong>没有协议问题</strong>
                    <span>当前标准视图没有发现 repository / collection / read / write / commit 层面的阻塞问题。</span>
                  </div>
                ) : null}
              </div>
            </div>
          </article>
        </section>
      ) : null}

      {facet === "repositories" ? (
        <section className="task-graph-memory-workbench">
          <aside className="boundary-card task-graph-memory-sidebar">
            <header><strong>资源节点</strong><span>{memoryModel.repositories.length} 个记忆仓库</span></header>
            <div className="task-graph-resource-create">
              {RESOURCE_NODE_TEMPLATES.map((template) => {
                const Icon = template.icon;
                return (
                  <button key={template.kind} onClick={() => createResourceNode(template)} type="button">
                    <Icon aria-hidden="true" size={15} />
                    <span>新增{template.title}</span>
                    <Plus aria-hidden="true" size={14} />
                  </button>
                );
              })}
            </div>
            <div className="task-graph-cognition-list">
              {memoryModel.repositories.map((repository) => (
                <button
                  className={selectedRepository?.nodeId === repository.nodeId ? "task-graph-memory-list-button task-graph-memory-list-button--active" : "task-graph-memory-list-button"}
                  key={repository.nodeId}
                  onClick={() => {
                    setSelectedRepositoryNodeId(repository.nodeId);
                    onEditorFocus?.({ layer: "memory", facet: "repositories", node_id: repository.nodeId, repository_id: repository.nodeId });
                  }}
                  type="button"
                >
                  <strong>{repository.title}</strong>
                  <span>{repository.repositoryId}</span>
                  <em>{repository.collections.length} collections{repository.synthetic ? " · virtual" : ""}</em>
                </button>
              ))}
              {!memoryModel.repositories.length ? (
                <div className="task-graph-note">
                  <strong>还没有记忆仓库</strong>
                  <span>新增 memory_repository 后，再通过矩阵给节点配置 read / write candidate / commit 边。</span>
                </div>
              ) : null}
              {standardResourceModel.memoryResources.length ? (
                <div className="task-graph-note">
                  <strong>标准对象中的仓库</strong>
                  <span>{standardResourceModel.memoryResources.slice(0, 3).map((resource) => `${resource.title}(${resource.repository_id || resource.node_id})`).join(" / ")}</span>
                </div>
              ) : null}
            </div>
          </aside>

          <article className="boundary-card task-graph-memory-detail">
            <header><strong>仓库结构</strong><span>{selectedRepository?.synthetic ? "来自边声明的虚拟仓库" : "图内资源节点"}</span></header>
            {selectedRepository ? (
              <div className="boundary-form">
                <TaskSystemField label="节点 ID">
                  <input disabled value={selectedRepository.nodeId} />
                </TaskSystemField>
                <TaskSystemField label="仓库标题">
                  <input
                    disabled={selectedRepository.synthetic}
                    onChange={(event) => updateRepositoryNode(selectedRepository, { title: event.target.value })}
                    value={String(selectedRepository.node?.title ?? selectedRepository.title)}
                  />
                </TaskSystemField>
                <TaskSystemField label="Repository ID">
                  <input
                    disabled={selectedRepository.synthetic}
                    onChange={(event) => updateRepositoryMetadata(selectedRepository, { repository_id: event.target.value })}
                    value={selectedRepository.repositoryId}
                  />
                </TaskSystemField>
                <TaskSystemField label="Schema ID">
                  <input
                    disabled={selectedRepository.synthetic}
                    onChange={(event) => updateRepositoryMetadata(selectedRepository, { schema_id: event.target.value })}
                    value={selectedRepository.schemaId}
                  />
                </TaskSystemField>
                <TaskSystemSelectField
                  label="版本策略"
                  onChange={(value) => updateRepositoryNode(selectedRepository, {
                    resource_lifecycle_policy: {
                      ...asRecord(selectedRepository.node?.resource_lifecycle_policy),
                      versioning: value,
                    },
                  })}
                  options={["append_version", "replace_latest", "immutable_once_committed", "manual_release"]}
                  value={String(selectedRepository.lifecyclePolicy.versioning ?? "append_version")}
                />
                <TaskSystemSelectField
                  label="提交要求"
                  onChange={(value) => updateRepositoryNode(selectedRepository, {
                    resource_lifecycle_policy: {
                      ...asRecord(selectedRepository.node?.resource_lifecycle_policy),
                      commit_required: value === "commit_required",
                    },
                  })}
                  options={["commit_required", "candidate_visible"]}
                  value={selectedRepository.lifecyclePolicy.commit_required === false ? "candidate_visible" : "commit_required"}
                />
              </div>
            ) : (
              <div className="task-graph-note">
                <strong>请选择仓库</strong>
                <span>仓库结构定义 collection、record kind、key strategy 和默认版本选择器。</span>
              </div>
            )}
          </article>

          <article className="boundary-card task-graph-memory-detail">
            <header>
              <strong>Collection</strong>
              {selectedRepository && !selectedRepository.synthetic ? <button className="boundary-chip" onClick={() => addRepositoryCollection(selectedRepository)} type="button"><span>新增集合</span></button> : null}
            </header>
            <div className="task-graph-node-policy-list">
              {(selectedRepository ? (selectedRepository.synthetic ? selectedRepository.collections.map((collection) => ({
                collection_id: collection.collectionId,
                title: collection.title,
                record_kinds: collection.recordKinds,
                key_strategy: collection.keyStrategy,
                schema_ref: collection.schemaId,
                default_version_selector: collection.defaultVersionSelector,
                required_commit_status: collection.requiredCommitStatus,
                content_requirement: defaultContentRequirement(),
              })) : repositoryCollectionsFromNode(selectedRepository.node)) : []).map((collection) => {
                const collectionId = String(collection.collection_id);
                return (
                  <article className="task-graph-node-policy-row task-graph-node-policy-row--wide" key={collectionId}>
                    <div className="task-graph-node-policy-row__identity">
                      <strong>{String(collection.title)}</strong>
                      <span>{collectionId}</span>
                    </div>
                    <TaskSystemField label="Collection ID">
                      <input
                        disabled={selectedRepository?.synthetic}
                        onChange={(event) => selectedRepository && updateRepositoryCollection(selectedRepository, collectionId, { collection_id: event.target.value })}
                        value={collectionId}
                      />
                    </TaskSystemField>
                    <TaskSystemField label="标题">
                      <input
                        disabled={selectedRepository?.synthetic}
                        onChange={(event) => selectedRepository && updateRepositoryCollection(selectedRepository, collectionId, { title: event.target.value })}
                        value={String(collection.title ?? "")}
                      />
                    </TaskSystemField>
                    <TaskSystemField label="Record Kinds">
                      <textarea
                        disabled={selectedRepository?.synthetic}
                        onChange={(event) => selectedRepository && updateRepositoryCollection(selectedRepository, collectionId, { record_kinds: splitList(event.target.value) })}
                        value={listText(collection.record_kinds)}
                      />
                    </TaskSystemField>
                    <TaskSystemSelectField
                      label="Key 策略"
                      onChange={(value) => selectedRepository && updateRepositoryCollection(selectedRepository, collectionId, { key_strategy: value })}
                      options={["stable_key", "append_only_id", "scope_key", "manual_key"]}
                      value={String(collection.key_strategy ?? "stable_key")}
                    />
                    <TaskSystemSelectField
                      label="默认版本"
                      onChange={(value) => selectedRepository && updateRepositoryCollection(selectedRepository, collectionId, { default_version_selector: value })}
                      options={["latest_committed_before_clock", "latest_committed_before_scope", "pinned_version", "manual_snapshot"]}
                      value={String(collection.default_version_selector ?? "latest_committed_before_clock")}
                    />
                    <TaskSystemSelectField
                      label="Canonical Text"
                      onChange={(value) => selectedRepository && updateRepositoryCollection(selectedRepository, collectionId, {
                        content_requirement: {
                          ...asRecord(collection.content_requirement),
                          canonical_text_required: value === "required",
                          artifact_ref_only_allowed: value === "refs_only",
                        },
                      })}
                      options={["required", "not_required", "refs_only"]}
                      value={
                        asRecord(collection.content_requirement).artifact_ref_only_allowed === true
                          ? "refs_only"
                          : asRecord(collection.content_requirement).canonical_text_required === false
                            ? "not_required"
                            : "required"
                      }
                    />
                    <TaskSystemField label="内容要求">
                      <textarea
                        disabled
                        value={`canonical_text_required=${booleanText(asRecord(collection.content_requirement).canonical_text_required !== false)}\nartifact_ref_only_allowed=${booleanText(asRecord(collection.content_requirement).artifact_ref_only_allowed === true)}`}
                      />
                    </TaskSystemField>
                  </article>
                );
              })}
            </div>
          </article>
        </section>
      ) : null}

      {facet === "matrix" ? (
        <section className="boundary-card task-graph-memory-matrix-card">
          <header><strong>节点 × 仓库 Collection 读写矩阵</strong><span>格子状态来自真实 memory edge，不保存第二份 UI 状态</span></header>
          {memoryModel.columns.length ? (
            <div className="task-graph-memory-matrix task-graph-memory-matrix--node">
              <div className="task-graph-memory-matrix__head">节点 / Collection</div>
              {memoryModel.columns.map((column) => (
                <div className="task-graph-memory-matrix__head" key={column.columnId}>
                  <strong>{column.repositoryTitle}</strong>
                  <span>{column.collectionId}</span>
                </div>
              ))}
              {memoryModel.matrixRows.map((row) => (
                <div className="task-graph-memory-matrix__row" key={row.nodeId}>
                  <strong title={row.nodeId}>{row.title}<span>{row.phaseId}</span></strong>
                  {row.cells.map((cell) => {
                    const cellKey = `${row.nodeId}:${cell.columnId}`;
                    const value = memoryCellOperationValue(cell) as MatrixOperationValue;
                    return (
                      <div className={value === "forbidden" ? "task-graph-memory-matrix__cell task-graph-memory-matrix__cell--muted" : "task-graph-memory-matrix__cell task-graph-memory-matrix__cell--active"} key={cellKey}>
                        <select
                          onChange={(event) => {
                            setSelectedCellKey(cellKey);
                            setCellOperation(cell, event.target.value as MatrixOperationValue);
                            onEditorFocus?.({
                              layer: "memory",
                              facet: "matrix",
                              node_id: row.nodeId,
                              repository_id: cell.repositoryId,
                              collection_id: cell.collectionId,
                            });
                          }}
                          onFocus={() => {
                            setSelectedCellKey(cellKey);
                            onEditorFocus?.({
                              layer: "memory",
                              facet: "matrix",
                              node_id: row.nodeId,
                              repository_id: cell.repositoryId,
                              collection_id: cell.collectionId,
                            });
                          }}
                          value={value}
                        >
                          {MATRIX_OPERATION_OPTIONS.map((option) => (
                            <option key={option} value={option}>{operationLabel(option)}</option>
                          ))}
                        </select>
                      </div>
                    );
                  })}
                </div>
              ))}
            </div>
          ) : (
            <div className="task-graph-note">
              <strong>没有可配置的记忆 collection</strong>
              <span>先新增 memory_repository 资源节点，或在记忆边 metadata 中声明 repository / collection。</span>
            </div>
          )}
          {selectedCell ? (
            <aside className="task-graph-memory-cell-inspector">
              <div>
                <strong>{selectedCell.row.title}</strong>
                <span>{selectedCell.cell.repositoryId}.{selectedCell.cell.collectionId}</span>
              </div>
              <div className="task-graph-mini-kv">
                <p><span>读取</span><strong>{selectedCell.cell.readEdge ? "已配置" : "无"}</strong></p>
                <p><span>写候选</span><strong>{selectedCell.cell.writeCandidateEdge ? "已配置" : "无"}</strong></p>
                <p><span>提交</span><strong>{selectedCell.cell.commitEdge ? "已配置" : "无"}</strong></p>
                <p><span>边数</span><strong>{selectedCell.cell.edges.length}</strong></p>
              </div>
              <div className="boundary-actions">
                {selectedCell.cell.edges[0] ? (
                  <button
                    className="boundary-chip"
                    onClick={() => {
                      const edge = selectedCell.cell.edges[0];
                      setSelectedMemoryEdgeId(edge.edgeId);
                      setFacet("selector");
                      onEditorFocus?.({
                        layer: "memory",
                        facet: "selector",
                        node_id: selectedCell.row.nodeId,
                        edge_id: edge.edgeId,
                        repository_id: edge.repositoryId,
                        collection_id: edge.collectionId,
                      });
                    }}
                    type="button"
                  >
                    <span>打开 Selector</span>
                  </button>
                ) : null}
                <button
                  className="boundary-chip"
                  onClick={() => {
                    setSelectedSnapshotNodeId(selectedCell.row.nodeId);
                    setFacet("snapshot");
                    onEditorFocus?.({
                      layer: "memory",
                      facet: "snapshot",
                      node_id: selectedCell.row.nodeId,
                      repository_id: selectedCell.cell.repositoryId,
                      collection_id: selectedCell.cell.collectionId,
                    });
                  }}
                  type="button"
                >
                  <span>查看节点 Snapshot</span>
                </button>
              </div>
              <small>已有边：{selectedCell.cell.edges.map((edge) => `${edge.operation}:${edge.edgeId}`).join(" / ") || "无"}</small>
            </aside>
          ) : null}
          {standardResourceModel.memoryEdges.length ? (
            <div className="task-graph-standard-list">
              {standardResourceModel.memoryEdges.slice(0, 6).map((edge) => (
                <article className="task-graph-standard-list__item" key={edge.edge_id}>
                  <strong>{describeTaskGraphStandardEdge(edge)}</strong>
                  <span>{`${edge.source_node_id} -> ${edge.target_node_id}`}</span>
                </article>
              ))}
            </div>
          ) : null}
        </section>
      ) : null}

      {facet === "selector" ? (
        <section className="task-graph-memory-workbench">
          <aside className="boundary-card task-graph-memory-sidebar">
            <header><strong>记忆边</strong><span>{memoryModel.memoryEdges.length} 条</span></header>
            <div className="task-graph-cognition-list">
              {memoryModel.memoryEdges.map((edge) => (
                <button
                  className={selectedMemoryEdge?.edgeId === edge.edgeId ? "task-graph-memory-list-button task-graph-memory-list-button--active" : "task-graph-memory-list-button"}
                  key={edge.edgeId}
                  onClick={() => {
                    setSelectedMemoryEdgeId(edge.edgeId);
                    onEditorFocus?.({
                      layer: "memory",
                      facet: "selector",
                      node_id: edge.taskNodeId,
                      edge_id: edge.edgeId,
                      repository_id: edge.repositoryId,
                      collection_id: edge.collectionId,
                    });
                  }}
                  type="button"
                >
                  <strong>{taskSystemOptionLabel(edge.edgeType)}</strong>
                  <span>{edge.taskNodeId} / {edge.repositoryId}.{edge.collectionId}</span>
                  <em>{edge.edgeId}</em>
                </button>
              ))}
            </div>
          </aside>

          <article className="boundary-card task-graph-memory-detail">
            <header><strong>Selector / Version / Visibility</strong><span>定向读取，不走模糊 RAG 主路径</span></header>
            {selectedMemoryEdge ? (
              <div className="boundary-form">
                <TaskSystemField label="边 ID">
                  <input disabled value={selectedMemoryEdge.edgeId} />
                </TaskSystemField>
                <TaskSystemSelectField
                  label="边类型"
                  onChange={(value) => updateTaskGraphEdge(selectedMemoryEdge.edgeId, { edge_type: value })}
                  options={["memory_read", "memory_write_candidate", "memory_commit", "memory_handoff"]}
                  value={selectedMemoryEdge.edgeType}
                />
                <TaskSystemField label="Repository">
                  <input onChange={(event) => patchSelectedMemoryEdgeMetadata({ repository: event.target.value })} value={selectedMemoryEdge.repositoryId} />
                </TaskSystemField>
                <TaskSystemField label="Collection">
                  <input onChange={(event) => patchSelectedMemoryEdgeMetadata({ collection: event.target.value, selector: { ...selectedMemoryEdge.selector, collection: event.target.value } })} value={selectedMemoryEdge.collectionId} />
                </TaskSystemField>
                <TaskSystemField label="Record Key">
                  <input
                    onChange={(event) => patchSelectedMemoryEdgeMetadata({ record_key: event.target.value, selector: { ...selectedMemoryEdge.selector, record_key: event.target.value } })}
                    placeholder="world_bible.current / volume.001.plan"
                    value={String(selectedMemoryEdge.selector.record_key ?? selectedMemoryEdge.resolvedMetadata.record_key ?? "")}
                  />
                </TaskSystemField>
                <TaskSystemField label="Record Kind">
                  <input
                    onChange={(event) => patchSelectedMemoryEdgeMetadata({ record_kind: event.target.value, selector: { ...selectedMemoryEdge.selector, record_kind: event.target.value } })}
                    placeholder="world_bible / chapter_outline / chapter_fact"
                    value={String(selectedMemoryEdge.selector.record_kind ?? selectedMemoryEdge.resolvedMetadata.record_kind ?? "")}
                  />
                </TaskSystemField>
                <TaskSystemField label="Record Kinds">
                  <textarea
                    onChange={(event) => patchSelectedMemoryEdgeMetadata({ selector: { ...selectedMemoryEdge.selector, record_kinds: splitList(event.target.value) } })}
                    value={listText(selectedMemoryEdge.selector.record_kinds)}
                  />
                </TaskSystemField>
                <TaskSystemField label="Record Keys">
                  <textarea
                    onChange={(event) => patchSelectedMemoryEdgeMetadata({ selector: { ...selectedMemoryEdge.selector, record_keys: splitList(event.target.value) } })}
                    value={listText(selectedMemoryEdge.selector.record_keys)}
                  />
                </TaskSystemField>
                {selectedMemoryEdge.operation === "write_candidate" ? (
                  <TaskSystemField label="Source Output Key">
                    <input
                      onChange={(event) => patchSelectedMemoryEdgeMetadata({ source_output_key: event.target.value })}
                      placeholder="approved_world / chapter_outline / canonical_fact"
                      value={String(selectedMemoryEdge.resolvedMetadata.source_output_key ?? "")}
                    />
                  </TaskSystemField>
                ) : null}
                {selectedMemoryEdge.operation === "commit" ? (
                  <>
                    <TaskSystemField label="Candidate Ref Key">
                      <input
                        onChange={(event) => patchSelectedMemoryEdgeMetadata({ candidate_ref_key: event.target.value })}
                        placeholder="reviewed_candidate_ref / candidate_version_id"
                        value={String(selectedMemoryEdge.resolvedMetadata.candidate_ref_key ?? "")}
                      />
                    </TaskSystemField>
                    <TaskSystemField label="Verdict Key">
                      <input
                        onChange={(event) => patchSelectedMemoryEdgeMetadata({ verdict_key: event.target.value })}
                        placeholder="verdict / review_result.verdict"
                        value={String(selectedMemoryEdge.resolvedMetadata.verdict_key ?? "")}
                      />
                    </TaskSystemField>
                    <TaskSystemField label="Required Verdict">
                      <input
                        onChange={(event) => patchSelectedMemoryEdgeMetadata({ required_verdict: event.target.value })}
                        placeholder="pass / approved"
                        value={String(selectedMemoryEdge.resolvedMetadata.required_verdict ?? "")}
                      />
                    </TaskSystemField>
                  </>
                ) : null}
                <TaskSystemSelectField
                  label="版本选择"
                  onChange={(value) => patchSelectedMemoryEdgeMetadata({ version_selector: value })}
                  options={["latest_committed_before_clock", "latest_committed_before_scope", "pinned_version", "by_commit_acknowledgement", "manual_snapshot"]}
                  value={selectedMemoryEdge.versionSelector}
                />
                <TaskSystemSelectField
                  label="缺失处理"
                  onChange={(value) => patchSelectedMemoryEdgeMetadata({ on_missing: value })}
                  options={["block", "warn", "skip"]}
                  value={selectedMemoryEdge.onMissing}
                />
                <TaskSystemField label="模型可见名称">
                  <input
                    onChange={(event) => patchSelectedMemoryEdgeMetadata({ model_visible_label: event.target.value })}
                    value={selectedMemoryEdge.modelVisibleLabel}
                  />
                </TaskSystemField>
                <TaskSystemField label="Prompt 使用说明" wide>
                  <textarea
                    onChange={(event) => patchSelectedMemoryEdgeMetadata({ usage_instruction: event.target.value })}
                    placeholder="你必须把这些记录作为硬约束；若与上游交接冲突，优先报告冲突而不是自行改写事实。"
                    value={selectedMemoryEdge.usageInstruction}
                  />
                </TaskSystemField>
                <TaskSystemSelectField
                  label="提交可见性"
                  onChange={(value) => patchSelectedMemoryEdgeMetadata({ commit_visibility_policy: { ...selectedMemoryEdge.commitVisibilityPolicy, visible_after: value } })}
                  options={["next_clock", "same_scope_next_node", "next_iteration", "manual_release"]}
                  value={String(selectedMemoryEdge.commitVisibilityPolicy.visible_after ?? "next_clock")}
                />
              </div>
            ) : (
              <div className="task-graph-note">
                <strong>没有记忆边</strong>
                <span>在读写矩阵里配置真实记忆边后，这里会显示 selector、版本选择和提交可见性配置。</span>
              </div>
            )}
          </article>
        </section>
      ) : null}

      {facet === "snapshot" ? (
        <section className="task-graph-memory-workbench">
          <aside className="boundary-card task-graph-memory-sidebar">
            <header><strong>节点 Snapshot</strong><span>运行前输入预览</span></header>
            <div className="task-graph-cognition-list">
              {memoryModel.snapshots.map((snapshot) => (
                <button
                  className={selectedSnapshot?.nodeId === snapshot.nodeId ? "task-graph-memory-list-button task-graph-memory-list-button--active" : "task-graph-memory-list-button"}
                  key={snapshot.nodeId}
                  onClick={() => {
                    setSelectedSnapshotNodeId(snapshot.nodeId);
                    onEditorFocus?.({ layer: "memory", facet: "snapshot", node_id: snapshot.nodeId });
                  }}
                  type="button"
                >
                  <strong>{snapshot.title}</strong>
                  <span>{snapshot.nodeId}</span>
                  <em>{snapshot.reads.length} read / {snapshot.writeCandidates.length} candidate / {snapshot.commits.length} commit</em>
                </button>
              ))}
            </div>
          </aside>

          <article className="boundary-card task-graph-memory-detail">
            <header><strong>MemorySnapshot 预览</strong><span>{selectedSnapshot?.nodeId || "未选择"}</span></header>
            {selectedSnapshot ? (
              <>
                <div className="task-graph-mini-kv">
                  <p><span>读取</span><strong>{selectedSnapshot.reads.length}</strong></p>
                  <p><span>写候选</span><strong>{selectedSnapshot.writeCandidates.length}</strong></p>
                  <p><span>提交</span><strong>{selectedSnapshot.commits.length}</strong></p>
                  <p><span>交接</span><strong>{selectedSnapshot.handoffs.length}</strong></p>
                  <p><span>风险</span><strong>{selectedSnapshot.issues.length}</strong></p>
                  <p><span>节点</span><strong>{selectedSnapshot.title}</strong></p>
                </div>
                <div className="task-graph-cognition-section">
                  <header><strong>节点会读到</strong><span>repository.collection / version_selector</span></header>
                  <div className="task-graph-cognition-list">
                    {selectedSnapshot.reads.map((edge) => (
                      <article className="task-graph-cognition-item" key={edge.edgeId}>
                        <div><strong>{edge.modelVisibleLabel || edge.collectionId}</strong><span>{edge.repositoryId}.{edge.collectionId}</span></div>
                        <p>{edge.usageInstruction || "缺少使用说明"}</p>
                        <em>{edge.edgeId} / {edge.versionSelector}</em>
                      </article>
                    ))}
                    {!selectedSnapshot.reads.length ? <div className="task-graph-note"><strong>没有记忆读取</strong><span>该节点不会收到 MemorySnapshot 里的仓库记录。</span></div> : null}
                  </div>
                </div>
                <div className="task-graph-cognition-section">
                  <header><strong>节点会写入</strong><span>候选与提交分离</span></header>
                  <div className="task-graph-cognition-list">
                    {[...selectedSnapshot.writeCandidates, ...selectedSnapshot.commits].map((edge) => (
                      <article className={edge.operation === "write_candidate" && !edge.hasCommitPath ? "task-graph-cognition-item task-graph-cognition-item--warn" : "task-graph-cognition-item"} key={edge.edgeId}>
                        <div><strong>{taskSystemOptionLabel(edge.edgeType)}</strong><span>{edge.repositoryId}.{edge.collectionId}</span></div>
                        <p>{edge.operation === "write_candidate" ? (edge.hasCommitPath ? "候选有可达提交路径。" : "候选没有可达提交路径。") : "提交后按提交可见性策略控制后续节点可读范围。"}</p>
                        <em>{edge.operation}</em>
                      </article>
                    ))}
                    {!selectedSnapshot.writeCandidates.length && !selectedSnapshot.commits.length ? <div className="task-graph-note"><strong>没有记忆写入</strong><span>该节点不会更新仓库。</span></div> : null}
                  </div>
                </div>
                {selectedSnapshot.issues.length ? (
                  <div className="task-graph-note task-graph-note--danger">
                    <strong>Snapshot 配置风险</strong>
                    <span>{selectedSnapshot.issues.join(" / ")}</span>
                  </div>
                ) : null}
              </>
            ) : (
              <div className="task-graph-note">
                <strong>没有可预览节点</strong>
                <span>添加任务节点后，可以预览该节点运行时会收到的 MemorySnapshot。</span>
              </div>
            )}
          </article>
        </section>
      ) : null}

      {facet === "formal_store" ? (
        <section className="task-graph-memory-workbench">
          <aside className="boundary-card task-graph-memory-sidebar">
            <header><strong>正式记忆库运行数据</strong><span>按 task_run_id 隔离</span></header>
            <div className="boundary-form">
              <TaskSystemField label="Task Run ID">
                <input
                  onChange={(event) => setManagementTaskRunId(event.target.value)}
                  placeholder="taskrun:..."
                  value={managementTaskRunId}
                />
              </TaskSystemField>
            </div>
            <div className="task-graph-cognition-list">
              {memoryModel.repositories.map((repository) => (
                <button
                  className={selectedRepository?.nodeId === repository.nodeId ? "task-graph-memory-list-button task-graph-memory-list-button--active" : "task-graph-memory-list-button"}
                  key={repository.nodeId}
                  onClick={() => setSelectedRepositoryNodeId(repository.nodeId)}
                  type="button"
                >
                  <strong>{repository.title}</strong>
                  <span>{repository.repositoryId}</span>
                  <em>{repository.collections.length} collections</em>
                </button>
              ))}
            </div>
          </aside>
          <article className="boundary-card task-graph-memory-detail">
            <header><strong>记忆版本与读取日志</strong><span>{selectedRepository?.repositoryId || "全部仓库"}</span></header>
            <div className="task-graph-mini-kv">
              <p><span>task_run_id</span><strong>{managementTaskRunId || "未过滤"}</strong></p>
              <p><span>仓库</span><strong>{formalOverview?.repository_count ?? 0}</strong></p>
              <p><span>记录</span><strong>{formalOverview?.record_count ?? 0}</strong></p>
              <p><span>版本</span><strong>{formalOverview?.version_count ?? 0}</strong></p>
              <p><span>读取日志</span><strong>{formalOverview?.read_log_count ?? 0}</strong></p>
            </div>
            {managementLoading ? <div className="task-graph-note"><strong>加载中</strong><span>正在读取正式记忆库管理视图。</span></div> : null}
            {managementError ? <div className="task-graph-note task-graph-note--danger"><strong>加载失败</strong><span>{managementError}</span></div> : null}
            <div className="task-graph-cognition-section">
              <header><strong>记录版本</strong><span>逻辑仓库 / 有效仓库 / 写入节点</span></header>
              <div className="task-graph-cognition-list">
                {(formalOverview?.versions ?? []).slice(0, 80).map((version) => (
                  <article className="task-graph-cognition-item" key={version.version_id}>
                    <div><strong>{version.record_key}</strong><span>{version.logical_repository_id}.{version.collection_id}</span></div>
                    <p>{version.summary || version.canonical_text || "无摘要"}</p>
                    <em>{version.task_run_id || "无 task_run_id"} / {version.effective_repository_id} / {version.status}</em>
                  </article>
                ))}
                {formalOverview && !formalOverview.versions.length ? (
                  <div className="task-graph-note"><strong>没有记录</strong><span>当前过滤条件下没有正式记忆版本。</span></div>
                ) : null}
              </div>
            </div>
            <div className="task-graph-cognition-section">
              <header><strong>读取日志</strong><span>节点实际读到了哪些版本</span></header>
              <div className="task-graph-cognition-list">
                {(formalOverview?.read_logs ?? []).slice(0, 60).map((log) => (
                  <article className="task-graph-cognition-item" key={log.read_log_id}>
                    <div><strong>{log.collection_id}</strong><span>{log.logical_repository_id}</span></div>
                    <p>{log.selected_version_ids.length ? log.selected_version_ids.join(" / ") : "未选中记录"}</p>
                    <em>{log.task_run_id || "无 task_run_id"} / {log.node_run_id} / {log.edge_id}</em>
                  </article>
                ))}
              </div>
            </div>
          </article>
        </section>
      ) : null}

      {facet === "artifact_store" ? (
        <section className="task-graph-memory-workbench">
          <aside className="boundary-card task-graph-memory-sidebar">
            <header><strong>产物库运行数据</strong><span>落盘产物索引</span></header>
            <div className="boundary-form">
              <TaskSystemField label="Task Run ID">
                <input
                  onChange={(event) => setManagementTaskRunId(event.target.value)}
                  placeholder="taskrun:..."
                  value={managementTaskRunId}
                />
              </TaskSystemField>
            </div>
            <div className="task-graph-note">
              <strong>产物库隔离</strong>
              <span>默认只显示当前 task_run_id 作用域内登记的产物；被拒绝产物会以 rejected 状态保留在索引里。</span>
            </div>
          </aside>
          <article className="boundary-card task-graph-memory-detail">
            <header><strong>产物记录</strong><span>{artifactOverview?.artifact_count ?? 0} artifacts</span></header>
            <div className="task-graph-mini-kv">
              <p><span>task_run_id</span><strong>{managementTaskRunId || "未过滤"}</strong></p>
              <p><span>仓库</span><strong>{artifactOverview?.repository_count ?? 0}</strong></p>
              <p><span>产物</span><strong>{artifactOverview?.artifact_count ?? 0}</strong></p>
            </div>
            {managementLoading ? <div className="task-graph-note"><strong>加载中</strong><span>正在读取产物库管理视图。</span></div> : null}
            {managementError ? <div className="task-graph-note task-graph-note--danger"><strong>加载失败</strong><span>{managementError}</span></div> : null}
            <div className="task-graph-cognition-list">
              {(artifactOverview?.artifacts ?? []).slice(0, 120).map((artifact) => (
                <article className="task-graph-cognition-item" key={artifact.artifact_id}>
                  <div><strong>{artifact.path}</strong><span>{artifact.logical_repository_id}.{artifact.collection_id}</span></div>
                  <p>{artifact.artifact_ref}</p>
                  <em>{artifact.task_run_id || "无 task_run_id"} / {artifact.stage_id || "无 stage"} / {artifact.status}</em>
                </article>
              ))}
              {artifactOverview && !artifactOverview.artifacts.length ? (
                <div className="task-graph-note"><strong>没有产物索引</strong><span>当前过滤条件下没有登记的产物。</span></div>
              ) : null}
            </div>
          </article>
        </section>
      ) : null}

      {facet === "artifact_context" ? (
        <>
          <section className="task-graph-form-grid">
            <article className="boundary-card task-graph-layer-explainer">
              <header><strong>资源配置边界</strong><span>不再使用旧图级 work memory / artifact 策略面板</span></header>
              <div className="task-graph-note">
                <strong>记忆如何读写，由 memory_* 边决定</strong>
                <span>仓库节点负责 repository / collection 结构，memory_read / memory_write_candidate / memory_commit 边负责 selector、写入目标和可见性。图级 working memory 不再作为主流程配置入口。</span>
              </div>
              <div className="task-graph-note">
                <strong>产物如何进入上下文，由 artifact_* 边决定</strong>
                <span>产物仓库节点负责逻辑仓库，artifact_context 边负责 source output、target input、展开模式和 usage instruction。图级 artifact policy 不再作为主要配置来源。</span>
              </div>
            </article>
            <article className="boundary-card task-graph-layer-explainer">
              <header><strong>ArtifactContextPacket</strong></header>
              <div className="task-graph-mini-kv">
                <p><span>产物边</span><strong>{artifactEdges.length}</strong></p>
                <p><span>记忆边</span><strong>{memoryModel.memoryEdges.length}</strong></p>
                <p><span>仓库列</span><strong>{memoryModel.columns.length}</strong></p>
                <p><span>运行隔离</span><strong>{standardResourceModel.runtimeIsolation?.task_run_scope_policy ?? "isolated_per_task_run"}</strong></p>
                <p><span>记忆仓库</span><strong>{standardResourceModel.memoryResources.length}</strong></p>
              </div>
              <div className="task-graph-note">
                <strong>产物和记忆都通过 packet 进入节点</strong>
                <span>产物上下文由 artifact_* 边决定引用与展开；记忆上下文由 memory_* 边决定 selector、版本选择与提交可见性。</span>
              </div>
            </article>
          </section>

          <section className="boundary-card">
            <header><strong>产物上下文边</strong><span>{artifactEdges.length} 条</span></header>
            <div className="task-graph-node-policy-list">
              {(artifactEdges.length ? artifactEdges : activeGraphEdges).map((edge, index) => {
                const edgeId = taskGraphEdgeId(edge, index);
                const artifactPolicy = asRecord(edge.artifact_ref_policy);
                const edgeMetadata = asRecord(edge.metadata);
                return (
                  <article className="task-graph-node-policy-row task-graph-node-policy-row--wide" key={edgeId}>
                    <div className="task-graph-node-policy-row__identity">
                      <strong>{taskGraphEdgeSource(edge)} {"->"} {taskGraphEdgeTarget(edge)}</strong>
                      <span>{edgeId}</span>
                    </div>
                    <TaskSystemSelectField
                      label="上下文模式"
                      onChange={(value) => updateTaskGraphEdge(edgeId, { metadata: { ...edgeMetadata, context_mode: value } })}
                      options={["refs_only", "summary_and_refs", "expand_text_for_model", "notification_only"]}
                      value={String(edgeMetadata.context_mode ?? artifactPolicy.context_mode ?? "refs_only")}
                    />
                    <TaskSystemField label="Source Output Key">
                      <input
                        onChange={(event) => updateTaskGraphEdge(edgeId, { artifact_ref_policy: { ...artifactPolicy, source_output_key: event.target.value } })}
                        placeholder="contract.output:artifact_refs"
                        value={String(artifactPolicy.source_output_key ?? "")}
                      />
                    </TaskSystemField>
                    <TaskSystemField label="Target Input Key">
                      <input
                        onChange={(event) => updateTaskGraphEdge(edgeId, { artifact_ref_policy: { ...artifactPolicy, target_input_key: event.target.value } })}
                        placeholder="candidate_ref"
                        value={String(artifactPolicy.target_input_key ?? "")}
                      />
                    </TaskSystemField>
                    <TaskSystemField label="Prompt 使用说明">
                      <textarea
                        onChange={(event) => updateTaskGraphEdge(edgeId, { metadata: { ...edgeMetadata, usage_instruction: event.target.value } })}
                        value={String(edgeMetadata.usage_instruction ?? artifactPolicy.usage_instruction ?? "")}
                      />
                    </TaskSystemField>
                    <TaskSystemField label="展开上限">
                      <input
                        min={0}
                        onChange={(event) => updateTaskGraphEdge(edgeId, { artifact_ref_policy: { ...artifactPolicy, max_chars: Number(event.target.value || 0) } })}
                        type="number"
                        value={Number(artifactPolicy.max_chars ?? 0)}
                      />
                    </TaskSystemField>
                  </article>
                );
              })}
            </div>
          </section>
        </>
      ) : null}
    </section>
  );
}
