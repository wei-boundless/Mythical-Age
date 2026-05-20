import type { TaskGraphStandardView } from "@/lib/api";

import { buildTimelinePreflightIssues } from "./taskGraphTimeline";
import { buildTaskGraphCognitionModel } from "./taskGraphCognitionView";
import { buildTaskGraphMemoryModel } from "./taskGraphMemoryMatrix";

export type TaskGraphPreflightSeverity = "error" | "warning" | "info";

export type TaskGraphPreflightScope = "graph" | "node" | "edge" | "phase" | "runtime" | "unit" | "interface" | "port_edge";

export type TaskGraphPreflightIssue = {
  issue_id: string;
  severity: TaskGraphPreflightSeverity;
  scope: TaskGraphPreflightScope;
  target_id: string;
  title: string;
  detail: string;
  source: string;
};

export type TaskGraphPreflightReport = {
  valid: boolean;
  issue_count: number;
  error_count: number;
  warning_count: number;
  info_count: number;
  issues: TaskGraphPreflightIssue[];
};

export type BuildTaskGraphPreflightReportInput = {
  nodes: Array<Record<string, unknown>>;
  edges: Array<Record<string, unknown>>;
  dirty: boolean;
  editorValid: boolean;
  editorIssueCount: number;
  metadata?: Record<string, unknown>;
  runtimeSpec?: {
    valid?: boolean;
    issues?: Array<Record<string, unknown>>;
    diagnostics?: Record<string, unknown>;
  } | null;
  standardView?: Pick<TaskGraphStandardView, "issues" | "units" | "interfaces" | "port_edges" | "nested_runtime"> | null;
};

function stringValue(value: unknown) {
  return String(value ?? "").trim();
}

function edgeSource(edge: Record<string, unknown>) {
  return stringValue(edge.source_node_id ?? edge.from ?? edge.source);
}

function edgeTarget(edge: Record<string, unknown>) {
  return stringValue(edge.target_node_id ?? edge.to ?? edge.target);
}

function recordValue(value: unknown) {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function contractBindingValue(target: Record<string, unknown>, section: string, key: string) {
  return stringValue(recordValue(recordValue(target.contract_bindings)[section])[key]);
}

function edgePayloadContractId(edge: Record<string, unknown>) {
  return contractBindingValue(edge, "schema", "payload_contract_id") || stringValue(edge.payload_contract_id ?? edge.contract_id);
}

function stringArrayValue(value: unknown): string[] {
  if (typeof value === "string") {
    return value.split(/[\n,，]/).map((item) => item.trim()).filter(Boolean);
  }
  return Array.isArray(value) ? value.map((item) => stringValue(item)).filter(Boolean) : [];
}

function nodeIdValue(node: Record<string, unknown>, index = 0) {
  return stringValue(node.node_id ?? node.id ?? `node_${index + 1}`);
}

function isMemoryRepositoryNode(node: Record<string, unknown>) {
  const nodeType = stringValue(node.node_type).toLowerCase();
  const nodeId = stringValue(node.node_id ?? node.id).toLowerCase();
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
  );
}

function memoryRepositorySpecs(nodes: Array<Record<string, unknown>>) {
  return nodes
    .map((node, index) => ({ node, index }))
    .filter(({ node }) => isMemoryRepositoryNode(node))
    .map(({ node, index }) => {
      const metadata = recordValue(node.metadata);
      const repositoryConfig = recordValue(metadata.memory_repository);
      const nodeId = nodeIdValue(node, index);
      const repositoryId = stringValue(repositoryConfig.repository_id ?? metadata.repository_id) || nodeId;
      const rawCollections = Array.isArray(repositoryConfig.collections)
        ? repositoryConfig.collections
        : Array.isArray(metadata.collections)
          ? metadata.collections
          : [];
      const collections = rawCollections
        .map((item, itemIndex) => {
          if (typeof item === "string") return { collection_id: item, record_kinds: [] };
          const record = recordValue(item);
          return {
            collection_id: stringValue(record.collection_id ?? record.id ?? record.name) || `collection_${itemIndex + 1}`,
            record_kinds: stringArrayValue(record.record_kinds ?? record.kinds),
          };
        })
        .filter((item) => item.collection_id);
      return { nodeId, repositoryId, collections, hasDeclaredCollections: rawCollections.length > 0 };
    });
}

function pushIssue(
  issues: TaskGraphPreflightIssue[],
  issue: Omit<TaskGraphPreflightIssue, "issue_id"> & { issue_id?: string },
) {
  const issueId = issue.issue_id || `${issue.scope}:${issue.target_id || "graph"}:${issue.title}`;
  issues.push({
    issue_id: issueId,
    severity: issue.severity,
    scope: issue.scope,
    target_id: issue.target_id,
    title: issue.title,
    detail: issue.detail,
    source: issue.source,
  });
}

export function buildTaskGraphPreflightReport({
  nodes,
  edges,
  dirty,
  editorValid,
  editorIssueCount,
  metadata,
  runtimeSpec,
  standardView,
}: BuildTaskGraphPreflightReportInput): TaskGraphPreflightReport {
  const issues: TaskGraphPreflightIssue[] = [];
  const nodeIds = nodes.map((node, index) => stringValue(node.node_id ?? node.id ?? `node_${index + 1}`));
  const nodeIdSet = new Set(nodeIds.filter(Boolean));
  const continuationPolicy = recordValue(metadata?.continuation_policy);
  const humanGateMode = stringValue(continuationPolicy.human_gate_mode);
  const nameRegistry = Array.isArray(metadata?.name_registry)
    ? metadata.name_registry.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    : [];
  const registeredNames = new Set(nameRegistry.map((item) => stringValue(item.object_id ?? item.id)).filter(Boolean));

  if (!nodes.length) {
    pushIssue(issues, {
      severity: "error",
      scope: "graph",
      target_id: "",
      title: "任务图没有节点",
      detail: "至少需要一个执行节点或协调节点。",
      source: "frontend.preflight.structure",
    });
  }

  if (nodes.length > 1 && !edges.length) {
    pushIssue(issues, {
      severity: "error",
      scope: "graph",
      target_id: "",
      title: "多节点任务图没有交接边",
      detail: "多 Agent 持续任务需要明确节点之间如何交接。",
      source: "frontend.preflight.structure",
    });
  }

  if (dirty) {
    pushIssue(issues, {
      severity: "warning",
      scope: "graph",
      target_id: "",
      title: "拓扑存在未同步改动",
      detail: "保存或发布前应先同步当前拓扑草稿。",
      source: "frontend.preflight.editor_state",
    });
  }

  if (!editorValid) {
    pushIssue(issues, {
      severity: "error",
      scope: "graph",
      target_id: "",
      title: "旧图结构校验未通过",
      detail: `旧编辑器校验报告仍有 ${editorIssueCount} 个问题。`,
      source: "legacy.editor_graph_spec",
    });
  }

  const seenNodeIds = new Set<string>();
  nodes.forEach((node, index) => {
    const nodeId = nodeIds[index] || `node_${index + 1}`;
    const explicitZhName = stringValue(node.display_name_zh ?? recordValue(node.metadata).display_name_zh ?? node.title ?? node.label);
    if (!registeredNames.has(nodeId) && !explicitZhName) {
      pushIssue(issues, {
        severity: "warning",
        scope: "node",
        target_id: nodeId,
        title: "节点缺少中文名注册",
        detail: "图上显示名应来自 metadata.name_registry 或节点显式中文名，避免不同页面显示不一致。",
        source: "frontend.preflight.name_registry",
      });
    }
    if (seenNodeIds.has(nodeId)) {
      pushIssue(issues, {
        severity: "error",
        scope: "node",
        target_id: nodeId,
        title: "节点 ID 重复",
        detail: "节点 ID 必须唯一，否则运行追踪和交接边无法稳定定位。",
        source: "frontend.preflight.node_identity",
      });
    }
    seenNodeIds.add(nodeId);

    const role = stringValue(node.role ?? node.work_posture ?? node.node_type);
    const agentId = stringValue(node.agent_id);
    const executionMode = stringValue(node.execution_mode || "sync");
    const humanGatePolicy = recordValue(node.human_gate_policy);
    if (!agentId && role !== "memory" && role !== "manual_gate") {
      pushIssue(issues, {
        severity: "warning",
        scope: "node",
        target_id: nodeId,
        title: "节点未绑定 Agent",
        detail: "未绑定 Agent 的节点会在运行装配时回退到图级协调者或默认策略。",
        source: "frontend.preflight.agent_binding",
      });
    }

    const metadata = node.metadata && typeof node.metadata === "object" && !Array.isArray(node.metadata)
      ? node.metadata as Record<string, unknown>
      : {};
    const projectionId = stringValue(node.projection_id ?? node.projection_overlay_id);
    const legacyMigration = metadata.legacy_prompt_migration && typeof metadata.legacy_prompt_migration === "object" && !Array.isArray(metadata.legacy_prompt_migration)
      ? metadata.legacy_prompt_migration as Record<string, unknown>
      : {};
    const legacyFieldNames = Array.isArray(legacyMigration.legacy_field_names)
      ? legacyMigration.legacy_field_names.map((value) => stringValue(value)).filter(Boolean)
      : [];
    const migrationStatus = stringValue(legacyMigration.migration_status);
    if (!projectionId && legacyFieldNames.length > 0) {
      pushIssue(issues, {
        severity: "warning",
        scope: "node",
        target_id: nodeId,
        title: "节点职责尚未绑定投影",
        detail: "该节点已有旧职责字段待迁移，但尚未迁移为投影系统中的 Projection。",
        source: "frontend.preflight.projection_binding",
      });
    }
    if (!projectionId && legacyFieldNames.length === 0 && agentId) {
      pushIssue(issues, {
        severity: "info",
        scope: "node",
        target_id: nodeId,
        title: "节点未绑定投影",
        detail: "建议绑定投影系统中的 Projection，让节点职责和 Prompt Manifest 可追踪。",
        source: "frontend.preflight.prompt_semantics",
      });
    }

    const artifactPolicy = node.artifact_policy && typeof node.artifact_policy === "object" && !Array.isArray(node.artifact_policy)
      ? node.artifact_policy as Record<string, unknown>
      : {};
    if (artifactPolicy.required === true && !stringValue(node.artifact_target ?? node.output_path)) {
      pushIssue(issues, {
        severity: "warning",
        scope: "node",
        target_id: nodeId,
        title: "必需产物没有目标路径",
        detail: "必需产物需要明确落盘路径或产物目标。",
        source: "frontend.preflight.artifact",
      });
    }
    if (executionMode === "manual_gate" && !Object.keys(humanGatePolicy).length) {
      pushIssue(issues, {
        severity: "error",
        scope: "node",
        target_id: nodeId,
        title: "人工门控缺少策略",
        detail: "manual_gate 节点必须配置 human_gate_policy，明确触发条件和是否阻塞。",
        source: "frontend.preflight.human_gate",
      });
    }

    const reviewGatePolicy = recordValue(node.review_gate_policy);
    const isReviewGate = reviewGatePolicy.is_review_gate === true || stringValue(node.node_type) === "review_gate";
    if (isReviewGate && !stringValue(reviewGatePolicy.verdict_contract_id ?? node.output_contract_id)) {
      pushIssue(issues, {
        severity: "warning",
        scope: "node",
        target_id: nodeId,
        title: "审核门缺少裁决契约",
        detail: "审核门应明确 verdict contract 或输出契约，让运行时和下游节点能区分通过、驳回、返修和阻断。",
        source: "frontend.preflight.review_gate_contract",
      });
    }
  });

  if (nodes.some((node) => stringValue(node.execution_mode) === "manual_gate") && !humanGateMode) {
    pushIssue(issues, {
      severity: "warning",
      scope: "runtime",
      target_id: "",
      title: "人工接管缺少图级策略",
      detail: "请在任务蓝图的全局策略中配置人工接管策略，避免运行时隐式等待人工处理。",
      source: "frontend.preflight.human_gate",
    });
  }

  edges.forEach((edge, index) => {
    const edgeId = stringValue(edge.edge_id ?? edge.id ?? `edge_${index + 1}`);
    const source = edgeSource(edge);
    const target = edgeTarget(edge);
    if (!source || !target) {
      pushIssue(issues, {
        severity: "error",
        scope: "edge",
        target_id: edgeId,
        title: "交接边缺少端点",
        detail: "边必须同时指定起点和终点。",
        source: "frontend.preflight.edge_endpoint",
      });
      return;
    }
    if (!nodeIdSet.has(source) || !nodeIdSet.has(target)) {
      pushIssue(issues, {
        severity: "error",
        scope: "edge",
        target_id: edgeId,
        title: "交接边引用了不存在的节点",
        detail: `${source} -> ${target} 中至少一个节点不存在。`,
        source: "frontend.preflight.edge_endpoint",
      });
    }
    if (!edgePayloadContractId(edge)) {
      pushIssue(issues, {
        severity: "info",
        scope: "edge",
        target_id: edgeId,
        title: "交接边未绑定载荷契约",
        detail: "建议为 Agent 间交接配置 payload contract，方便预检和运行追踪。",
        source: "frontend.preflight.contract",
      });
    }
    const memoryHandoffPolicy = edge.working_memory_handoff_policy && typeof edge.working_memory_handoff_policy === "object" && !Array.isArray(edge.working_memory_handoff_policy)
      ? edge.working_memory_handoff_policy as Record<string, unknown>
      : {};
    const hasMemoryHandoffPolicy = Object.keys(memoryHandoffPolicy).length > 0;
    const hasCarryShape = Array.isArray(memoryHandoffPolicy.carry_kinds)
      || Array.isArray(memoryHandoffPolicy.carry_scopes)
      || Array.isArray(memoryHandoffPolicy.working_memory_refs)
      || memoryHandoffPolicy.summary_only === true;
    if (hasMemoryHandoffPolicy && !hasCarryShape) {
      pushIssue(issues, {
        severity: "warning",
        scope: "edge",
        target_id: edgeId,
        title: "工作记忆交接策略不完整",
        detail: "边级工作记忆交接应说明携带的 Kind、Scope、引用，或明确只传摘要。",
        source: "frontend.preflight.memory_handoff",
      });
    }

    const edgeType = stringValue(edge.edge_type ?? edge.mode);
    const metadata = recordValue(edge.metadata);
    const isRevisionEdge = ["revision_request", "review_feedback", "repair_feedback", "conditional_feedback", "repair_route"].includes(edgeType)
      || stringValue(metadata.verdict) === "revise";
    if (isRevisionEdge && !stringValue(metadata.original_artifact_key ?? metadata.original_artifact_ref_key ?? metadata.candidate_ref_key)) {
      pushIssue(issues, {
        severity: "warning",
        scope: "edge",
        target_id: edgeId,
        title: "返修边缺少原稿引用",
        detail: "返修交接必须告诉目标节点本轮要修改哪份原始产物，不能让节点从文件列表或 latest 结果里猜。",
        source: "frontend.preflight.revision_packet",
      });
    }
    if (isRevisionEdge && !stringValue(metadata.review_result_key ?? metadata.verdict_key)) {
      pushIssue(issues, {
        severity: "warning",
        scope: "edge",
        target_id: edgeId,
        title: "返修边缺少审核结果引用",
        detail: "返修交接必须携带审核裁决、问题清单或审核结果引用，否则出稿节点无法知道退稿原因。",
        source: "frontend.preflight.revision_packet",
      });
    }
  });

  const memoryModel = buildTaskGraphMemoryModel({ nodes, edges });
  const repositorySpecs = memoryRepositorySpecs(nodes);
  const repositoryByAnyId = new Map<string, ReturnType<typeof memoryRepositorySpecs>[number]>();
  repositorySpecs.forEach((repository) => {
    repositoryByAnyId.set(repository.nodeId, repository);
    repositoryByAnyId.set(repository.repositoryId, repository);
    if (!repository.hasDeclaredCollections) {
      pushIssue(issues, {
        severity: "warning",
        scope: "node",
        target_id: repository.nodeId,
        title: "记忆仓库没有显式 Collection",
        detail: `${repository.repositoryId} 会退回 default collection。正式记忆库应显式声明分区、schema 和 record_kind。`,
        source: "frontend.preflight.memory_repository",
      });
    }
  });
  memoryModel.columns.forEach((column) => {
    if (column.synthetic) {
      pushIssue(issues, {
        severity: "warning",
        scope: "graph",
        target_id: column.repositoryId,
        title: "记忆边声明了未建仓库",
        detail: `${column.repositoryId}.${column.collectionId} 来自边 metadata，但图中没有对应 memory_repository 节点。建议补成资源节点，避免运行装配时语义不清。`,
        source: "frontend.preflight.memory_repository",
      });
    }
    if (!stringValue(column.schemaId) || column.schemaId === "schema.memory_record") {
      pushIssue(issues, {
        severity: "info",
        scope: "graph",
        target_id: column.repositoryId,
        title: "记忆 Collection 使用默认 Schema",
        detail: `${column.repositoryId}.${column.collectionId} 未显式绑定 schema_id / schema_ref。通用仓库可以发布，但精确读写建议补 schema。`,
        source: "frontend.preflight.memory_repository",
      });
    }
  });
  memoryModel.memoryEdges.forEach((memoryEdge) => {
    const metadata = recordValue(memoryEdge.edge.metadata);
    const selector = recordValue(metadata.selector);
    const explicitCollection = stringValue(selector.collection ?? metadata.collection);
    const explicitRepository = stringValue(metadata.repository ?? metadata.repository_id ?? memoryEdge.repositoryId);
    const repository = repositoryByAnyId.get(explicitRepository) ?? repositoryByAnyId.get(memoryEdge.repositoryNodeId);
    if (!repository) {
      pushIssue(issues, {
        severity: "error",
        scope: "edge",
        target_id: memoryEdge.edgeId,
        title: "记忆边引用了不存在的仓库",
        detail: `${memoryEdge.edgeId} 指向 ${explicitRepository || memoryEdge.repositoryId}，但图中没有对应 memory_repository 资源节点。`,
        source: "frontend.preflight.memory_repository",
      });
    } else if (explicitCollection && !repository.collections.some((collection) => collection.collection_id === explicitCollection)) {
      pushIssue(issues, {
        severity: "error",
        scope: "edge",
        target_id: memoryEdge.edgeId,
        title: "记忆边引用了不存在的 Collection",
        detail: `${repository.repositoryId}.${explicitCollection} 没有在仓库节点中声明。请先在记忆页创建 collection，再连接读写边。`,
        source: "frontend.preflight.memory_repository",
      });
    }
    if (memoryEdge.operation === "read" && !explicitCollection) {
      pushIssue(issues, {
        severity: "error",
        scope: "edge",
        target_id: memoryEdge.edgeId,
        title: "记忆读取缺少 Selector",
        detail: "memory_read 边必须显式配置 selector.collection，读取路径不能依赖模糊仓库搜索。",
        source: "frontend.preflight.memory_selector",
      });
    }
    if (memoryEdge.operation === "read" && !stringValue(selector.record_key ?? metadata.record_key) && !stringArrayValue(selector.record_keys ?? metadata.record_keys).length && !stringValue(selector.record_kind ?? metadata.record_kind) && !stringArrayValue(selector.record_kinds ?? metadata.record_kinds).length) {
      pushIssue(issues, {
        severity: "warning",
        scope: "edge",
        target_id: memoryEdge.edgeId,
        title: "记忆读取缺少 Record Selector",
        detail: "memory_read 应至少配置 record_key / record_keys 或 record_kind / record_kinds，避免读取整个 collection 后让 Agent 自己筛选。",
        source: "frontend.preflight.memory_selector",
      });
    }
    if (memoryEdge.operation === "read" && !memoryEdge.usageInstruction) {
      pushIssue(issues, {
        severity: "warning",
        scope: "edge",
        target_id: memoryEdge.edgeId,
        title: "记忆读取缺少使用说明",
        detail: "memory_read 边应说明这份 MemorySnapshot 在 prompt 中如何称呼、如何使用、是否作为硬约束。",
        source: "frontend.preflight.memory_selector",
      });
    }
    if (memoryEdge.operation === "write_candidate" && !memoryEdge.hasCommitPath) {
      pushIssue(issues, {
        severity: "warning",
        scope: "edge",
        target_id: memoryEdge.edgeId,
        title: "写入候选缺少提交路径",
        detail: "memory_write_candidate 只产生候选，不会自动对后续节点可见；需要可达的 memory_commit 边或明确这是候选-only 路径。",
        source: "frontend.preflight.memory_commit_path",
      });
    }
    if (memoryEdge.operation === "write_candidate" && !stringValue(metadata.source_output_key) && !stringValue(selector.source_output_key)) {
      pushIssue(issues, {
        severity: "error",
        scope: "edge",
        target_id: memoryEdge.edgeId,
        title: "候选写入缺少输出来源",
        detail: "memory_write_candidate 应配置 source_output_key，运行时才能把节点输出中的确定字段写入正式记忆记录。",
        source: "frontend.preflight.memory_write_contract",
      });
    }
    if (memoryEdge.operation === "write_candidate" && !stringValue(metadata.record_key ?? selector.record_key) && !stringValue(metadata.record_kind ?? selector.record_kind) && !stringArrayValue(metadata.record_kinds ?? selector.record_kinds).length) {
      pushIssue(issues, {
        severity: "error",
        scope: "edge",
        target_id: memoryEdge.edgeId,
        title: "候选写入缺少 Record 标识",
        detail: "memory_write_candidate 应配置 record_key 和 record_kind。否则同一 collection 中无法稳定维护当前记录和版本历史。",
        source: "frontend.preflight.memory_write_contract",
      });
    }
    if (memoryEdge.operation === "commit" && !Object.keys(memoryEdge.commitVisibilityPolicy).length) {
      pushIssue(issues, {
        severity: "warning",
        scope: "edge",
        target_id: memoryEdge.edgeId,
        title: "记忆提交缺少可见性策略",
        detail: "memory_commit 边应配置 commit_visibility_policy，说明提交状态和从哪个 clock/scope 起对后续节点可见。",
        source: "frontend.preflight.memory_commit_visibility",
      });
    }
    if (memoryEdge.operation === "commit" && !stringValue(metadata.candidate_ref_key) && !stringValue(metadata.record_key ?? selector.record_key)) {
      pushIssue(issues, {
        severity: "error",
        scope: "edge",
        target_id: memoryEdge.edgeId,
        title: "记忆提交缺少候选引用",
        detail: "memory_commit 应配置 candidate_ref_key 或明确 record_key，避免提交节点不知道要提交哪个候选版本。",
        source: "frontend.preflight.memory_commit_contract",
      });
    }
    if (memoryEdge.operation === "commit" && !stringValue(metadata.verdict_key) && !stringValue(metadata.required_verdict)) {
      pushIssue(issues, {
        severity: "info",
        scope: "edge",
        target_id: memoryEdge.edgeId,
        title: "记忆提交缺少审核裁决字段",
        detail: "建议配置 verdict_key / required_verdict，让正式提交依赖明确审核结果，而不是默认提交。",
        source: "frontend.preflight.memory_commit_contract",
      });
    }
  });

  const cognitionModel = buildTaskGraphCognitionModel({ nodes, edges });
  cognitionModel.packages.forEach((nodePackage) => {
    nodePackage.inputPackets.forEach((packet) => {
      if (packet.kind !== "dispatch_context" && !packet.usageInstruction) {
        pushIssue(issues, {
          severity: "warning",
          scope: packet.edgeId ? "edge" : "node",
          target_id: packet.edgeId || nodePackage.nodeId,
          title: "输入包缺少 Prompt 使用说明",
          detail: `${nodePackage.title} 收到的 ${packet.title} 没有 usage_instruction，Agent 可能不知道该把它当硬约束、参考资料还是返修依据。`,
          source: "frontend.preflight.cognition_packet",
        });
      }
    });
  });

  buildTimelinePreflightIssues(nodes, edges, metadata).forEach((issue, index) => {
    const severity = issue.severity === "warning" ? "warning" : issue.severity === "info" ? "info" : "error";
    pushIssue(issues, {
      issue_id: `timeline:${issue.code}:${issue.node_id ?? issue.edge_id ?? issue.phase_id ?? index}`,
      severity,
      scope: issue.edge_id ? "edge" : issue.node_id ? "node" : issue.phase_id ? "phase" : "graph",
      target_id: stringValue(issue.edge_id ?? issue.node_id ?? issue.phase_id),
      title: issue.code,
      detail: issue.message,
      source: "frontend.preflight.timeline",
    });
  });

  (runtimeSpec?.issues ?? []).forEach((issue, index) => {
    const severity = stringValue(issue.severity) === "warning" ? "warning" : stringValue(issue.severity) === "info" ? "info" : "error";
    const code = stringValue(issue.code);
    const isSchedulerSupportIssue = code.startsWith("scheduler_policy_");
    pushIssue(issues, {
      issue_id: `runtime:${code || index}:${stringValue(issue.edge_id ?? issue.node_id)}`,
      severity,
      scope: stringValue(issue.edge_id) ? "edge" : stringValue(issue.node_id) ? "node" : isSchedulerSupportIssue ? "graph" : "runtime",
      target_id: stringValue(issue.edge_id ?? issue.node_id),
      title: code || "运行规范问题",
      detail: stringValue(issue.message) || "后端 runtime spec 返回了未命名问题。",
      source: isSchedulerSupportIssue ? "backend.scheduler_support" : "backend.runtime_spec",
    });
  });

  (standardView?.issues ?? [])
    .filter((issue) => {
      const source = stringValue(issue.source);
      const code = stringValue(issue.code);
      return source === "task_system.composable_graph_issue" || code.startsWith("port_edge_") || code.startsWith("nested_graph_") || code.startsWith("graph_unit_") || code.startsWith("unit_interface_");
    })
    .forEach((issue, index) => {
      const code = stringValue(issue.code);
      const severity = stringValue(issue.severity) === "error"
        ? "error"
        : stringValue(issue.severity) === "info"
          ? "info"
          : "warning";
      const edgeId = stringValue(issue.edge_id);
      const unitId = stringValue(issue.unit_id);
      pushIssue(issues, {
        issue_id: `composable:${code || index}:${edgeId || unitId || "graph"}`,
        severity,
        scope: edgeId ? "port_edge" : unitId ? "unit" : "graph",
        target_id: edgeId || unitId,
        title: code || "可组合图问题",
        detail: stringValue(issue.message) || "后端可组合图标准视图返回了未命名问题。",
        source: "backend.composable_graph",
      });
    });

  const errorCount = issues.filter((issue) => issue.severity === "error").length;
  const warningCount = issues.filter((issue) => issue.severity === "warning").length;
  const infoCount = issues.filter((issue) => issue.severity === "info").length;

  return {
    valid: errorCount === 0,
    issue_count: issues.length,
    error_count: errorCount,
    warning_count: warningCount,
    info_count: infoCount,
    issues,
  };
}
