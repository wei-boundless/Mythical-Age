import {
  buildTaskGraphMemoryModel,
  taskGraphEdgeId,
  taskGraphEdgeSource,
  taskGraphEdgeTarget,
  type TaskGraphMemorySnapshotPreview,
} from "./taskGraphMemoryMatrix";
import {
  edgePayloadContractIdOf,
  nodeExecutionContractIdOf,
  nodeInputContractIdOf,
  nodeOutputContractIdOf,
} from "./taskGraphContractBindings";

export type TaskGraphCognitionPacketKind =
  | "dispatch_context"
  | "memory_snapshot"
  | "artifact_context"
  | "revision_packet"
  | "handoff_packet";

export type TaskGraphCognitionPacket = {
  packetId: string;
  kind: TaskGraphCognitionPacketKind;
  sourceId: string;
  edgeId: string;
  title: string;
  modelVisibleLabel: string;
  usageInstruction: string;
  contractId: string;
  required: boolean;
  issues: string[];
};

export type TaskGraphCognitionOutput = {
  outputId: string;
  kind: "artifact" | "handoff" | "memory_write_candidate" | "memory_commit" | "timeline_result";
  targetId: string;
  title: string;
  contractId: string;
  visibility: string;
};

export type TaskGraphCognitionPackage = {
  nodeId: string;
  title: string;
  role: string;
  agentId: string;
  phaseId: string;
  sequenceIndex: number;
  timelineScope: string;
  executionMode: string;
  inputContractId: string;
  outputContractId: string;
  roleIdentity: string;
  responsibilityScope: string;
  responsibilityExclusions: string;
  definitionOfDone: string;
  memorySnapshot: TaskGraphMemorySnapshotPreview | null;
  inputPackets: TaskGraphCognitionPacket[];
  outputs: TaskGraphCognitionOutput[];
  downstreamNodeIds: string[];
  issues: string[];
  promptPreview: string;
};

export type TaskGraphCognitionModel = {
  packages: TaskGraphCognitionPackage[];
  packageByNodeId: Map<string, TaskGraphCognitionPackage>;
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function stringValue(value: unknown, fallback = "") {
  const next = String(value ?? "").trim();
  return next || fallback;
}

function nodeIdOf(node: Record<string, unknown>, index = 0) {
  return stringValue(node.node_id ?? node.id, `node_${index + 1}`);
}

function nodeTitle(node: Record<string, unknown>, index = 0) {
  return stringValue(node.title ?? node.label ?? node.task_title, nodeIdOf(node, index));
}

function isRepositoryNode(node: Record<string, unknown>) {
  const nodeType = stringValue(node.node_type).toLowerCase();
  const nodeId = stringValue(node.node_id).toLowerCase();
  return (
    nodeType.includes("repository")
    || nodeType === "thread_ledger"
    || nodeType === "progress_ledger"
    || nodeType === "issue_ledger"
    || nodeType === "working_memory_store"
    || nodeType === "runtime_state_store"
    || nodeId.startsWith("memory.repository")
  );
}

function edgeType(edge: Record<string, unknown>) {
  return stringValue(edge.edge_type ?? edge.mode);
}

function edgeContract(edge: Record<string, unknown>) {
  return edgePayloadContractIdOf(edge);
}

function artifactPacket(edge: Record<string, unknown>, index: number): TaskGraphCognitionPacket | null {
  const type = edgeType(edge);
  const artifactPolicy = asRecord(edge.artifact_ref_policy);
  const metadata = asRecord(edge.metadata);
  if (!type.startsWith("artifact_") && !Object.keys(artifactPolicy).length && !stringValue(metadata.context_mode).includes("artifact")) {
    return null;
  }
  const edgeId = taskGraphEdgeId(edge, index);
  const sourceId = taskGraphEdgeSource(edge);
  const label = stringValue(metadata.model_visible_label ?? artifactPolicy.target_input_key ?? metadata.context_mode, "产物上下文");
  const usageInstruction = stringValue(metadata.usage_instruction ?? artifactPolicy.usage_instruction);
  return {
    packetId: `artifact:${edgeId}`,
    kind: "artifact_context",
    sourceId,
    edgeId,
    title: label,
    modelVisibleLabel: label,
    usageInstruction,
    contractId: edgeContract(edge),
    required: artifactPolicy.required !== false,
    issues: usageInstruction ? [] : ["产物上下文缺少 usage_instruction"],
  };
}

function revisionPacket(edge: Record<string, unknown>, index: number): TaskGraphCognitionPacket | null {
  const type = edgeType(edge);
  const metadata = asRecord(edge.metadata);
  if (!["revision_request", "review_feedback", "repair_feedback", "conditional_feedback", "repair_route"].includes(type) && stringValue(metadata.verdict) !== "revise") {
    return null;
  }
  const edgeId = taskGraphEdgeId(edge, index);
  const sourceId = taskGraphEdgeSource(edge);
  const label = stringValue(metadata.model_visible_label ?? metadata.revision_label, "返修输入包");
  const usageInstruction = stringValue(metadata.usage_instruction ?? metadata.revision_instruction);
  const issues: string[] = [];
  if (!usageInstruction) issues.push("返修输入包缺少 usage_instruction");
  if (!stringValue(metadata.original_artifact_key ?? metadata.original_artifact_ref_key ?? metadata.candidate_ref_key)) {
    issues.push("返修输入包缺少原始产物引用键");
  }
  if (!stringValue(metadata.review_result_key ?? metadata.verdict_key)) {
    issues.push("返修输入包缺少审核结果键");
  }
  return {
    packetId: `revision:${edgeId}`,
    kind: "revision_packet",
    sourceId,
    edgeId,
    title: label,
    modelVisibleLabel: label,
    usageInstruction,
    contractId: edgeContract(edge),
    required: true,
    issues,
  };
}

function handoffPacket(edge: Record<string, unknown>, index: number): TaskGraphCognitionPacket | null {
  const type = edgeType(edge);
  if (type.startsWith("memory_") || type.startsWith("artifact_")) return null;
  if (revisionPacket(edge, index) || artifactPacket(edge, index)) return null;
  const handoffPolicy = asRecord(edge.working_memory_handoff_policy);
  const metadata = asRecord(edge.metadata);
  const edgeId = taskGraphEdgeId(edge, index);
  const label = stringValue(metadata.model_visible_label ?? edge.label ?? edge.title, "上游交接包");
  const usageInstruction = stringValue(metadata.usage_instruction ?? handoffPolicy.usage_instruction);
  return {
    packetId: `handoff:${edgeId}`,
    kind: "handoff_packet",
    sourceId: taskGraphEdgeSource(edge),
    edgeId,
    title: label,
    modelVisibleLabel: label,
    usageInstruction,
    contractId: edgeContract(edge),
    required: edge.ack_required !== false,
    issues: usageInstruction || edgeContract(edge) ? [] : ["交接包缺少使用说明或载荷契约"],
  };
}

function memoryPackets(snapshot: TaskGraphMemorySnapshotPreview | null): TaskGraphCognitionPacket[] {
  if (!snapshot) return [];
  return snapshot.reads.map((edge) => ({
    packetId: `memory:${edge.edgeId}`,
    kind: "memory_snapshot",
    sourceId: edge.repositoryNodeId,
    edgeId: edge.edgeId,
    title: edge.modelVisibleLabel || `${edge.repositoryId}.${edge.collectionId}`,
    modelVisibleLabel: edge.modelVisibleLabel || edge.collectionId,
    usageInstruction: edge.usageInstruction,
    contractId: "",
    required: edge.onMissing === "block",
    issues: [
      edge.usageInstruction ? "" : "MemorySnapshot 缺少 usage_instruction",
      edge.modelVisibleLabel ? "" : "MemorySnapshot 缺少 model_visible_label",
    ].filter(Boolean),
  }));
}

function nodeOutputs(
  nodeId: string,
  node: Record<string, unknown>,
  outgoingEdges: Array<Record<string, unknown>>,
  snapshot: TaskGraphMemorySnapshotPreview | null,
): TaskGraphCognitionOutput[] {
  const artifactTarget = stringValue(node.artifact_target ?? node.output_path);
  const outputs: TaskGraphCognitionOutput[] = [];
  if (artifactTarget) {
    outputs.push({
      outputId: `${nodeId}:artifact`,
      kind: "artifact",
      targetId: artifactTarget,
      title: "节点产物",
      contractId: nodeOutputContractIdOf(node),
      visibility: "artifact_ref",
    });
  }
  for (const edge of snapshot?.writeCandidates ?? []) {
    outputs.push({
      outputId: `${edge.edgeId}:candidate`,
      kind: "memory_write_candidate",
      targetId: `${edge.repositoryId}.${edge.collectionId}`,
      title: "记忆写入候选",
      contractId: "",
      visibility: edge.hasCommitPath ? "等待提交后可见" : "仅候选，不会自动污染后续节点",
    });
  }
  for (const edge of snapshot?.commits ?? []) {
    outputs.push({
      outputId: `${edge.edgeId}:commit`,
      kind: "memory_commit",
      targetId: `${edge.repositoryId}.${edge.collectionId}`,
      title: "记忆提交",
      contractId: "",
      visibility: stringValue(edge.commitVisibilityPolicy.visible_after, "next_clock"),
    });
  }
  for (const edge of outgoingEdges) {
    outputs.push({
      outputId: taskGraphEdgeId(edge),
      kind: "handoff",
      targetId: taskGraphEdgeTarget(edge),
      title: stringValue(edge.label ?? edge.title ?? edge.edge_type, "下游交接"),
      contractId: edgeContract(edge),
      visibility: stringValue(edge.result_delivery_policy, "contract_payload_and_refs"),
    });
  }
  const outputContractId = nodeOutputContractIdOf(node);
  if (outputContractId) {
    outputs.push({
      outputId: `${nodeId}:timeline_result`,
      kind: "timeline_result",
      targetId: "timeline_result_record",
      title: "时序结果记录",
      contractId: outputContractId,
      visibility: "由运行时时序坐标控制",
    });
  }
  return outputs;
}

function promptPreview(pkg: Omit<TaskGraphCognitionPackage, "promptPreview">) {
  const inputLines = pkg.inputPackets.length
    ? pkg.inputPackets.map((packet) => `- ${packet.modelVisibleLabel || packet.title}: ${packet.usageInstruction || "必须按该输入包约束执行，不得自行猜测缺失内容。"}`)
    : ["- 当前没有显式输入包；你只能依据节点任务和图级上下文执行。"];
  const outputLines = pkg.outputs.length
    ? pkg.outputs.map((output) => `- ${output.title}: ${output.targetId}${output.contractId ? `，契约 ${output.contractId}` : ""}`)
    : ["- 输出清晰结论、依据、遗留问题和下一步建议。"];
  return [
    pkg.roleIdentity || `你是一名${pkg.role || "任务协作者"}。`,
    pkg.responsibilityScope ? `你只负责${pkg.responsibilityScope.replace(/^你只负责/, "")}` : "你只负责完成当前节点明确交付给你的职责。",
    pkg.responsibilityExclusions ? `你不负责${pkg.responsibilityExclusions.replace(/^你不负责/, "")}` : "你不负责扩展未经确认的任务范围。",
    "",
    "你会收到以下输入包：",
    ...inputLines,
    "",
    "你必须产出：",
    ...outputLines,
    "",
    pkg.definitionOfDone ? `完成标准：${pkg.definitionOfDone.replace(/^你必须/, "")}` : "完成标准：输出必须能被下游节点按契约接收，并说明是否仍有阻塞问题。",
  ].join("\n");
}

export function buildTaskGraphCognitionModel({
  nodes,
  edges,
}: {
  nodes: Array<Record<string, unknown>>;
  edges: Array<Record<string, unknown>>;
}): TaskGraphCognitionModel {
  const memoryModel = buildTaskGraphMemoryModel({ nodes, edges });
  const packages = nodes
    .map((node, index) => ({ node, index, nodeId: nodeIdOf(node, index) }))
    .filter(({ node }) => !isRepositoryNode(node))
    .map(({ node, index, nodeId }) => {
      const metadata = asRecord(node.metadata);
      const incomingEdges = edges.filter((edge) => taskGraphEdgeTarget(edge) === nodeId);
      const outgoingEdges = edges.filter((edge) => taskGraphEdgeSource(edge) === nodeId);
      const snapshot = memoryModel.snapshotByNodeId.get(nodeId) ?? null;
      const edgePackets = incomingEdges.flatMap((edge, edgeIndex) => [
        artifactPacket(edge, edgeIndex),
        revisionPacket(edge, edgeIndex),
        handoffPacket(edge, edgeIndex),
      ]).filter((packet): packet is TaskGraphCognitionPacket => Boolean(packet));
      const dispatchPacket: TaskGraphCognitionPacket = {
        packetId: `dispatch:${nodeId}`,
        kind: "dispatch_context",
        sourceId: "TopologyTemporalControl",
        edgeId: "",
        title: "Dispatch Context",
        modelVisibleLabel: "运行时位置",
        usageInstruction: "你需要按当前拓扑位置、phase、step 和 iteration 处理本次执行，不要把其他运行窗口的内容混入本轮输出。",
        contractId: "",
        required: true,
        issues: [],
      };
      const basePackage = {
        nodeId,
        title: nodeTitle(node, index),
        role: stringValue(node.role ?? node.work_posture ?? node.node_type, "participant"),
        agentId: stringValue(node.agent_id),
        phaseId: stringValue(node.phase_id, "phase.unassigned"),
        sequenceIndex: Number(node.sequence_index ?? index + 1),
        timelineScope: `${stringValue(node.phase_id, "phase.unassigned")}/S${Number(node.sequence_index ?? index + 1)}`,
        executionMode: stringValue(node.execution_mode, "sync"),
        inputContractId: nodeInputContractIdOf(node) || nodeExecutionContractIdOf(node),
        outputContractId: nodeOutputContractIdOf(node),
        roleIdentity: stringValue(metadata.role_identity),
        responsibilityScope: stringValue(metadata.responsibility_scope),
        responsibilityExclusions: stringValue(metadata.responsibility_exclusions),
        definitionOfDone: stringValue(metadata.definition_of_done),
        memorySnapshot: snapshot,
        inputPackets: [dispatchPacket, ...memoryPackets(snapshot), ...edgePackets],
        outputs: nodeOutputs(nodeId, node, outgoingEdges, snapshot),
        downstreamNodeIds: outgoingEdges.map(taskGraphEdgeTarget).filter(Boolean),
        issues: [] as string[],
      };
      const issues = [
        !basePackage.roleIdentity ? "节点缺少角色身份说明" : "",
        ...basePackage.inputPackets.flatMap((packet) => packet.issues),
        basePackage.outputs.length === 0 ? "节点没有明确输出、交接或提交确认配置" : "",
      ].filter(Boolean);
      const packageWithIssues = { ...basePackage, issues };
      return {
        ...packageWithIssues,
        promptPreview: promptPreview(packageWithIssues),
      };
    });

  return {
    packages,
    packageByNodeId: new Map(packages.map((item) => [item.nodeId, item])),
  };
}
