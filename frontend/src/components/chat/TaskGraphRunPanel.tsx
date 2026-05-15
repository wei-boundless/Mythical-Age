"use client";

import {
  Database,
  FileText,
  Network,
  Sparkles,
} from "lucide-react";
import { useMemo, useState } from "react";

import {
  CoordinationTopologyGraph,
  type CoordinationTopologyEdge,
  type CoordinationTopologyNode,
} from "@/components/coordination/CoordinationTopologyGraph";
import {
  hasTaskGraphLiveRun,
  taskGraphRunIdFromLiveMonitor,
  taskGraphRunFromLiveMonitor,
  type RuntimeLoopTaskRunLiveMonitor,
} from "@/lib/api";

type CoordinationNode = CoordinationTopologyNode & {
  role: string;
  agentLabel: string;
  status: string;
};

type CoordinationEdge = CoordinationTopologyEdge & {
  label: string;
  status: string;
};

type CoordinationAgent = {
  key: string;
  label: string;
  role: string;
  nodeTitle: string;
  status: string;
};

type CoordinationArtifact = {
  key: string;
  label: string;
  path: string;
  kind: string;
  producedBy: string;
};

type CoordinationOutput = {
  key: string;
  label: string;
  content: string;
};

type CoordinationContractNode = {
  nodeId: string;
  title: string;
  status: string;
  contractRefs: string[];
  missingRequiredInputs: string[];
  accepted: boolean;
  artifactRefs: string[];
  taskResultRef: string;
};

type CoordinationHandoffPreview = {
  key: string;
  sourceNodeId: string;
  targetNodeId: string;
  messageType: string;
  status: string;
  contractRefs: string[];
  artifactRefs: string[];
  resultRefs: string[];
  runtimeAssemblyRef: string;
  contractManifestRef: string;
};

type CoordinationWorkingMemoryOperation = {
  key: string;
  operation: string;
  stageId: string;
  nodeId: string;
  edgeId: string;
  status: string;
  refs: string[];
  deniedReason: string;
  selectedItemPreviews: Array<{
    work_memory_id: string;
    owner_node_id: string;
    scope: string;
    visibility: string;
    kind: string;
    summary: string;
  }>;
  transactionRef: string;
  finalizationRef: string;
};

type CoordinationContractRuntime = {
  manifestRef: string;
  valid: boolean;
  issues: string[];
  readyNodes: string[];
  blockedNodes: string[];
  runningNodes: string[];
  waitingNodes: string[];
  completedNodes: string[];
  failedNodes: string[];
  nodeSummaries: CoordinationContractNode[];
  handoffs: CoordinationHandoffPreview[];
  workingMemoryOperations: CoordinationWorkingMemoryOperation[];
};

type CoordinationModel = {
  hasSignal: boolean;
  title: string;
  currentNodeId: string;
  currentAgentKey: string;
  currentHandoffKey: string;
  nodes: CoordinationNode[];
  edges: CoordinationEdge[];
  agents: CoordinationAgent[];
  artifacts: CoordinationArtifact[];
  outputs: CoordinationOutput[];
  contractRuntime: CoordinationContractRuntime;
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function stringArray(value: unknown): string[] {
  if (typeof value === "string") {
    return value.trim() ? [value.trim()] : [];
  }
  return asArray(value).map((item) => text(item)).filter(Boolean);
}

function text(value: unknown, fallback = "") {
  const next = String(value ?? "").trim();
  return next || fallback;
}

function agentLabel(profileId: string, agentId = "") {
  const labels: Record<string, string> = {
    main_interactive_agent: "主 Agent",
    world_designer: "世界观设计师",
    world_reviewer: "世界观审核员",
    outline_designer: "大纲设计师",
    outline_reviewer: "大纲审核员",
    character_designer: "人物设定师",
    chapter_planner: "章节规划师",
    chapter_draft: "章节写作者",
    chapter_writer_a: "章节写作者 A",
    chapter_writer_b: "章节写作者 B",
    chapter_reviewer: "章节审读员",
    quality_gate: "质量裁判",
    quality_gate_reviewer: "质量裁判",
    memory_commit: "资产管理员",
    memory_steward: "资产管理员",
  };
  const normalizedProfile = profileId
    .replace(/^agent:/, "")
    .replace(/^projection\.writing_team\.long_novel\./, "")
    .replace(/^task\.writing_team\.long_novel\./, "");
  const normalizedAgent = agentId
    .replace(/^agent:/, "")
    .replace(/^projection\.writing_team\.long_novel\./, "")
    .replace(/^task\.writing_team\.long_novel\./, "");
  if (labels[normalizedProfile]) {
    return labels[normalizedProfile];
  }
  if (labels[normalizedAgent]) {
    return labels[normalizedAgent];
  }
  if (profileId) {
    return profileId
      .replace(/_agent$/, "")
      .replace(/_/g, " ");
  }
  return agentId ? "协作 Agent" : "未指定 Agent";
}

function nodeTitle(nodeId: string, fallback = "") {
  const labels: Record<string, string> = {
    world_design: "世界观设计",
    world_review: "世界观审核",
    outline_design: "大纲设计",
    outline_review: "大纲审核",
    character_design: "人物设定",
    chapter_plan: "章节细纲",
    chapter_writer_a: "章节写作者 A",
    chapter_writer_b: "章节写作者 B",
    chapter_review: "章节互审",
    chapter_draft: "章节初稿",
    writer_a_draft: "作者 A 初稿",
    writer_b_review: "作者 B 审读",
    writer_a_revision: "作者 A 修订",
    writer_b_final_candidate: "作者 B 终稿候选",
    novel_quality_judge: "独立裁判通关",
    quality_gate: "质量门",
    memory_commit: "资产入库",
    project_scope: "项目规格锁定",
    batch_plan: "批次规划",
    batch_draft: "批次起草",
    sampling_review: "抽样审查",
    continuity_fast_review: "连贯性快审",
    batch_revision: "批次修订",
    editor_acceptance: "编辑验收",
    outline: "大纲",
    draft: "起草",
    review: "审查",
    revise: "修订",
    acceptance: "验收"
  };
  if (labels[nodeId]) {
    return labels[nodeId];
  }
  const longNovelMatch = nodeId.match(/(?:long_novel|long\.novel)[._-]([a-z0-9_]+)$/i);
  if (longNovelMatch?.[1] && labels[longNovelMatch[1]]) {
    return labels[longNovelMatch[1]];
  }
  const fallbackMatch = fallback.match(/(?:long_novel|long\.novel)[._-]([a-z0-9_]+)$/i);
  if (fallbackMatch?.[1] && labels[fallbackMatch[1]]) {
    return labels[fallbackMatch[1]];
  }
  if (/^(task|flow|workflow|projection|contract)[._:-]/i.test(fallback)) {
    return nodeId.replace(/_/g, " ");
  }
  return fallback || nodeId.replace(/_/g, " ");
}

function runtimeScopeLabel(scope: string) {
  const value = scope.trim();
  if (!value) {
    return "全图";
  }
  if (value === "graph") {
    return "全图";
  }
  const edgeMatch = value.match(/^edge[._:-]([a-z0-9_]+)[._:-]([a-z0-9_]+)$/i);
  if (edgeMatch?.[1] && edgeMatch?.[2]) {
    return `${nodeTitle(edgeMatch[1])} -> ${nodeTitle(edgeMatch[2])}`;
  }
  return nodeTitle(value);
}

function roleLabel(role: string) {
  const labels: Record<string, string> = {
    coordinator: "协调",
    participant: "参与",
    main_executor: "主执行",
    reviewer: "审查",
    drafter: "起草"
  };
  return labels[role] ?? role ?? "参与";
}

function statusLabel(status: string) {
  if (status === "completed" || status === "success" || status === "satisfied") {
    return "完成";
  }
  if (status === "running") {
    return "运行中";
  }
  if (status === "failed") {
    return "失败";
  }
  if (status === "blocked") {
    return "阻塞";
  }
  if (status === "waiting" || status === "waiting_for_human" || status === "human_gate") {
    return "等待确认";
  }
  if (status === "pending_retry") {
    return "等待重试";
  }
  if (status === "ready") {
    return "就绪";
  }
  return status || "待执行";
}

function compactTaskLabel(value: string) {
  const labels: Record<string, string> = {
    langgraph: "LangGraph"
  };
  return labels[value] ?? value;
}

function pushArtifact(
  bucket: CoordinationArtifact[],
  seen: Set<string>,
  path: string,
  kind: string,
  label = "",
  producedBy = "",
) {
  const normalized = path.trim();
  if (!normalized) {
    return;
  }
  const key = `${kind}:${normalized}`;
  if (seen.has(key)) {
    const existing = bucket.find((item) => item.key === key);
    if (existing && (!existing.producedBy || existing.producedBy === "未标注 Agent") && producedBy.trim()) {
      existing.producedBy = producedBy.trim();
    }
    return;
  }
  seen.add(key);
  bucket.push({
    key,
    label: label || normalized.split(/[\\/]/).pop() || normalized,
    path: normalized,
    kind,
    producedBy: producedBy.trim()
  });
}

function pushOutput(bucket: CoordinationOutput[], seen: Set<string>, label: string, content: string) {
  const normalizedLabel = label.trim();
  const normalizedContent = content.trim();
  if (!normalizedLabel || !normalizedContent) {
    return;
  }
  const key = `${normalizedLabel}:${normalizedContent.slice(0, 80)}`;
  if (seen.has(key)) {
    return;
  }
  seen.add(key);
  bucket.push({
    key,
    label: normalizedLabel,
    content: normalizedContent
  });
}

function buildContractRuntimeFromLiveState(
  runtimeState: Record<string, unknown>,
  nodes: CoordinationNode[],
  fallbackCurrentNodeId: string,
): CoordinationContractRuntime {
  const contractStatus = asRecord(runtimeState.contract_status);
  const nodeStatus = asRecord(contractStatus.node_status);
  const stageResults = asRecord(runtimeState.stage_results);
  const nodeTitleById = new Map(nodes.map((node) => [node.id, node.title]));
  const statusEntries = Object.keys(nodeStatus).length ? Object.entries(nodeStatus) : Object.entries(stageResults);
  const nodeSummaries = statusEntries
    .map(([nodeId, raw]): CoordinationContractNode => {
      const item = asRecord(raw);
      return {
        nodeId,
        title: nodeTitleById.get(nodeId) || nodeTitle(nodeId),
        status: text(item.status, "pending"),
        contractRefs: stringArray(item.contract_refs),
        missingRequiredInputs: stringArray(item.missing_required_inputs),
        accepted: item.accepted === true,
        artifactRefs: stringArray(item.artifact_refs),
        taskResultRef: text(item.task_result_ref) || text(item.final_result_ref)
      };
    })
    .sort((left, right) => {
      if (left.nodeId === fallbackCurrentNodeId) {
        return -1;
      }
      if (right.nodeId === fallbackCurrentNodeId) {
        return 1;
      }
      return left.nodeId.localeCompare(right.nodeId);
    });
  const issues = asArray(contractStatus.issues)
    .map((item) => {
      const issue = asRecord(item);
      return text(issue.message) || text(issue.issue) || text(item);
    })
    .filter(Boolean);
  const handoffs = asArray(runtimeState.handoff_packets).map((item) => asRecord(item));
  const workingMemoryOperations = asArray(runtimeState.working_memory_operations).map((item) => asRecord(item));
  return {
    manifestRef: text(runtimeState.contract_manifest_ref) || text(contractStatus.manifest_ref),
    valid: contractStatus.valid === true,
    issues,
    readyNodes: stringArray(runtimeState.ready_nodes),
    blockedNodes: stringArray(runtimeState.blocked_nodes),
    runningNodes: stringArray(runtimeState.running_nodes),
    waitingNodes: stringArray(runtimeState.waiting_nodes),
    completedNodes: stringArray(runtimeState.completed_nodes),
    failedNodes: stringArray(runtimeState.failed_nodes),
    nodeSummaries,
    handoffs: handoffs.slice(-6).map((packet, index): CoordinationHandoffPreview => ({
      key: text(packet.handoff_id) || `${text(packet.source_node_id)}->${text(packet.target_node_id)}:${index}`,
      sourceNodeId: text(packet.source_node_id),
      targetNodeId: text(packet.target_node_id),
      messageType: text(packet.message_type, "message/send"),
      status: text(packet.status, "pending"),
      contractRefs: stringArray(packet.contract_refs || packet.contract_ref || packet.edge_contract_ref),
      artifactRefs: stringArray(packet.artifact_refs),
      resultRefs: stringArray(packet.result_refs),
      runtimeAssemblyRef: text(packet.runtime_assembly_ref),
      contractManifestRef: text(packet.contract_manifest_ref),
    })),
    workingMemoryOperations: workingMemoryOperations.slice(-8).map((operation, index): CoordinationWorkingMemoryOperation => ({
      key: `${text(operation.operation)}:${text(operation.stage_id) || text(operation.edge_id) || index}`,
      operation: text(operation.operation),
      stageId: text(operation.stage_id),
      nodeId: text(operation.node_id),
      edgeId: text(operation.edge_id),
      status: text(operation.status, "completed"),
      refs: Array.from(new Set([
        ...stringArray(operation.created_working_memory_refs),
        ...stringArray(operation.selected_working_memory_refs),
        ...stringArray(operation.excluded_working_memory_refs),
        ...stringArray(operation.adopted_working_memory_refs),
        ...stringArray(operation.accepted_working_memory_refs),
        ...stringArray(operation.discarded_working_memory_refs),
        ...stringArray(operation.conflict_working_memory_refs),
      ].filter(Boolean))),
      deniedReason: text(operation.denied_reason),
      selectedItemPreviews: asArray(operation.selected_item_previews).map((item) => {
        const preview = asRecord(item);
        return {
          work_memory_id: text(preview.work_memory_id),
          owner_node_id: text(preview.owner_node_id),
          scope: text(preview.scope),
          visibility: text(preview.visibility),
          kind: text(preview.kind),
          summary: text(preview.summary),
        };
      }).filter((item) => item.work_memory_id || item.summary),
      transactionRef: text(operation.handoff_transaction_ref),
      finalizationRef: text(operation.finalization_ref),
    })),
  };
}

function buildModelFromLiveMonitor(liveMonitor: RuntimeLoopTaskRunLiveMonitor): CoordinationModel {
  const coordinationRun = asRecord(taskGraphRunFromLiveMonitor(liveMonitor));
  const coordinationSummary = asRecord(coordinationRun.coordination_run);
  const flowState = asRecord(coordinationRun.coordination_flow);
  const runtimeState = asRecord(coordinationRun.langgraph_runtime_state);
  const graphSpec = asRecord(coordinationRun.coordination_graph_spec);
  const rawNodes = asArray(graphSpec.nodes).map((item) => asRecord(item));
  const rawEdges = asArray(graphSpec.edges).map((item) => asRecord(item));
  const flowStages = asArray(flowState.stages).map((item) => asRecord(item));
  const nodeRuns = asArray(coordinationRun.node_runs).map((item) => asRecord(item));
  const handoffs = asArray(coordinationRun.handoff_envelopes).map((item) => asRecord(item));
  const mergeResult = asRecord(coordinationRun.latest_merge_result);
  const coordinationTaskRef =
    text(graphSpec.coordination_task_id)
    || text(graphSpec.graph_id)
    || text(coordinationSummary.graph_ref)
    || text(coordinationRun.graph_ref);

  const statusByNode = new Map<string, string>();
  const agentByNode = new Map<string, string>();
  const nodeRoleById = new Map<string, string>();

  for (const stage of flowStages) {
    const nodeId = text(stage.node_id) || text(stage.stage_id);
    if (!nodeId) continue;
    statusByNode.set(nodeId, text(stage.status, "pending"));
    nodeRoleById.set(nodeId, roleLabel(text(stage.role) || "participant"));
  }
  for (const nodeId of stringArray(runtimeState.ready_nodes)) statusByNode.set(nodeId, "ready");
  for (const nodeId of stringArray(runtimeState.blocked_nodes)) statusByNode.set(nodeId, "blocked");
  for (const nodeId of stringArray(runtimeState.running_nodes)) statusByNode.set(nodeId, "running");
  for (const nodeId of stringArray(runtimeState.waiting_nodes)) statusByNode.set(nodeId, "waiting_for_human");
  for (const nodeId of stringArray(runtimeState.completed_nodes)) if (statusByNode.get(nodeId) !== "running") statusByNode.set(nodeId, "completed");
  for (const nodeId of stringArray(runtimeState.failed_nodes)) statusByNode.set(nodeId, "failed");

  for (const nodeRun of nodeRuns) {
    const nodeId = text(nodeRun.node_id);
    if (!nodeId) continue;
    const diagnostics = asRecord(nodeRun.diagnostics);
    statusByNode.set(nodeId, text(diagnostics.stage_status) || text(nodeRun.status, "pending"));
    nodeRoleById.set(nodeId, roleLabel(text(nodeRun.role) || "participant"));
  }

  const graphNodes = rawNodes
    .map((node): CoordinationNode | null => {
      const id = text(node.node_id) || text(node.id);
      if (!id) return null;
      const metadata = asRecord(node.metadata);
      const agentName = agentLabel(text(metadata.projection_id), text(node.agent_id));
      agentByNode.set(id, agentName);
      return {
        id,
        title: nodeTitle(id, text(node.title) || text(node.label)),
        role: nodeRoleById.get(id) || roleLabel(text(node.role)),
        agentLabel: agentName || "待分派",
        status: statusByNode.get(id) || text(node.status, "idle"),
      };
    })
    .filter((item): item is CoordinationNode => Boolean(item));

  const stageNodes = flowStages
    .map((stage): CoordinationNode | null => {
      const nodeId = text(stage.node_id) || text(stage.stage_id);
      if (!nodeId) return null;
      return {
        id: nodeId,
        title: nodeTitle(nodeId, compactTaskLabel(text(stage.task_ref)) || text(stage.stage_id)),
        role: nodeRoleById.get(nodeId) || roleLabel(text(stage.role) || "participant"),
        agentLabel: agentByNode.get(nodeId) || "待分派",
        status: statusByNode.get(nodeId) || text(stage.status, "pending"),
      };
    })
    .filter((item): item is CoordinationNode => Boolean(item));

  const nodes = graphNodes.length ? graphNodes : stageNodes;
  const nodeIdSet = new Set(nodes.map((node) => node.id));
  const currentNodeId =
    text(flowState.current_stage_id)
    || nodes.find((node) => node.status === "running")?.id
    || stringArray(runtimeState.running_nodes)[0]
    || stringArray(runtimeState.blocked_nodes)[0]
    || "";

  const flowEdges = flowStages.slice(0, -1).map((stage, index): CoordinationEdge => ({
    id: `flow-${text(stage.node_id) || text(stage.stage_id)}-${text(flowStages[index + 1]?.node_id) || text(flowStages[index + 1]?.stage_id)}-${index}`,
    from: text(stage.node_id) || text(stage.stage_id),
    to: text(flowStages[index + 1]?.node_id) || text(flowStages[index + 1]?.stage_id),
    label: compactTaskLabel(text(flowStages[index + 1]?.task_ref)) || "阶段交接",
    status: "idle",
  }));
  const graphEdges = rawEdges
    .map((edge, index): CoordinationEdge | null => {
      const from = text(edge.from) || text(edge.source) || text(edge.from_node_id) || text(edge.source_node_id);
      const to = text(edge.to) || text(edge.target) || text(edge.to_node_id) || text(edge.target_node_id);
      if (!from || !to || (!nodeIdSet.has(from) && !nodeIdSet.has(to))) return null;
      return {
        id: text(edge.edge_id) || `${from}-${to}-${index}`,
        from,
        to,
        label: compactTaskLabel(text(edge.policy) || text(edge.label) || "交接"),
        status: "idle",
      };
    })
    .filter((item): item is CoordinationEdge => Boolean(item));
  const packetEdges = asArray(runtimeState.handoff_packets)
    .map((item, index): CoordinationEdge | null => {
      const packet = asRecord(item);
      const from = text(packet.source_node_id);
      const to = text(packet.target_node_id);
      if (!from || !to || (!nodeIdSet.has(from) && !nodeIdSet.has(to))) return null;
      return {
        id: text(packet.handoff_id) || `packet-${from}-${to}-${index}`,
        from,
        to,
        label: compactTaskLabel(text(packet.message_type) || "交接"),
        status: text(packet.status) === "accepted" ? "completed" : "running",
      };
    })
    .filter((item): item is CoordinationEdge => Boolean(item));
  const edges = (graphEdges.length ? graphEdges : flowEdges.length ? flowEdges : packetEdges).map((edge) => ({
    ...edge,
    status:
      edge.status !== "idle"
        ? edge.status
        : edge.from === currentNodeId || edge.to === currentNodeId
          ? "running"
          : statusByNode.get(edge.from) === "completed" && statusByNode.get(edge.to) === "completed"
            ? "completed"
            : "idle",
  }));

  const agents = nodes.map((node, index): CoordinationAgent => ({
    key: `live-agent:${node.id}:${index + 1}`,
    label: node.agentLabel || "待分派",
    role: node.role,
    nodeTitle: node.title,
    status: node.status,
  }));

  const artifacts: CoordinationArtifact[] = [];
  const artifactSeen = new Set<string>();
  for (const [stageId, raw] of Object.entries(asRecord(runtimeState.stage_results))) {
    const result = asRecord(raw);
    const producer = nodes.find((node) => node.id === stageId);
    for (const ref of stringArray(result.artifact_refs)) {
      pushArtifact(artifacts, artifactSeen, ref, "artifact_ref", "", producer?.agentLabel || producer?.title || stageId);
    }
    const finalResultRef = text(result.final_result_ref) || text(result.task_result_ref);
    if (finalResultRef) {
      pushArtifact(artifacts, artifactSeen, finalResultRef, "result_ref", "阶段结果", producer?.agentLabel || producer?.title || stageId);
    }
  }
  for (const item of asArray(runtimeState.artifact_refs).map((entry) => asRecord(entry))) {
    const ref = text(item.ref) || text(item.artifact_ref) || text(item.path);
    const stageId = text(item.stage_id) || text(item.node_id) || text(item.produced_by);
    const producer = nodes.find((node) => node.id === stageId);
    if (ref) {
      pushArtifact(artifacts, artifactSeen, ref, "artifact_ref", "", producer?.agentLabel || producer?.title || stageId);
    }
  }
  for (const stage of flowStages) {
    const nodeId = text(stage.node_id) || text(stage.stage_id);
    const producer = nodes.find((node) => node.id === nodeId);
    for (const ref of stringArray(stage.artifact_refs)) {
      pushArtifact(artifacts, artifactSeen, ref, "artifact_ref", "", producer?.agentLabel || producer?.title || "");
    }
    const finalResultRef = text(stage.final_result_ref);
    if (finalResultRef) {
      pushArtifact(artifacts, artifactSeen, finalResultRef, "result_ref", "阶段结果", producer?.agentLabel || producer?.title || "");
    }
  }
  for (const packet of asArray(runtimeState.handoff_packets).map((item) => asRecord(item))) {
    for (const ref of [...stringArray(packet.artifact_refs), ...stringArray(packet.result_refs)]) {
      pushArtifact(artifacts, artifactSeen, ref, "handoff_ref");
    }
  }
  if (text(mergeResult.final_result_ref)) {
    pushArtifact(artifacts, artifactSeen, text(mergeResult.final_result_ref), "merge_result", "最终结果");
  }

  const outputs: CoordinationOutput[] = [];
  const outputSeen = new Set<string>();
  if (text(mergeResult.final_result_ref)) {
    pushOutput(outputs, outputSeen, "final_result_ref", text(mergeResult.final_result_ref));
  }
  for (const [stageId, raw] of Object.entries(asRecord(runtimeState.stage_results))) {
    const result = asRecord(raw);
    const finalResultRef = text(result.final_result_ref) || text(result.task_result_ref);
    if (finalResultRef) {
      pushOutput(outputs, outputSeen, nodeTitle(stageId), finalResultRef);
    }
  }
  for (const stage of flowStages) {
    const finalResultRef = text(stage.final_result_ref);
    if (finalResultRef) {
      pushOutput(outputs, outputSeen, nodeTitle(text(stage.node_id) || text(stage.stage_id)), finalResultRef);
    }
  }

  const handoffPackets = asArray(runtimeState.handoff_packets).map((item) => asRecord(item));
  const currentHandoffKey = handoffPackets.length
    ? `${text(handoffPackets[handoffPackets.length - 1].source_node_id)}->${text(handoffPackets[handoffPackets.length - 1].target_node_id)}`
    : "";

  return {
    hasSignal: Boolean(coordinationTaskRef || nodes.length),
    title: coordinationTaskRef ? compactTaskLabel(coordinationTaskRef) : "当前没有协调任务运行",
    currentNodeId,
    currentAgentKey: currentNodeId ? `live-agent:${currentNodeId}` : "",
    currentHandoffKey,
    nodes,
    edges,
    agents,
    artifacts,
    outputs: outputs.slice(-6),
    contractRuntime: buildContractRuntimeFromLiveState(runtimeState, nodes, currentNodeId),
  };
}


export function TaskGraphRunPanel({
  liveMonitor,
  onResumeTaskGraphRun,
}: {
  liveMonitor?: RuntimeLoopTaskRunLiveMonitor | null;
  onResumeTaskGraphRun?: (taskGraphRunId: string, payload?: Record<string, unknown>) => Promise<void>;
}) {
  const model = useMemo(
    () => (liveMonitor && hasTaskGraphLiveRun(liveMonitor) ? buildModelFromLiveMonitor(liveMonitor) : buildModelFromLiveMonitor({
      authority: "orchestration.runtime_loop_live_monitor",
      task_run: {},
      latest_checkpoint: null,
      loop_state: {},
      coordination_run: null,
      has_coordination: false,
      status: "unknown",
      terminal_reason: "",
      updated_at: 0,
    })),
    [liveMonitor]
  );
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [selectedEdgeId, setSelectedEdgeId] = useState("");
  const [resuming, setResuming] = useState(false);
  const [resumeError, setResumeError] = useState("");
  const [resumeNotice, setResumeNotice] = useState("");
  const currentNode = model.nodes.find((node) => node.id === model.currentNodeId) ?? null;
  const selectedNode = model.nodes.find((node) => node.id === selectedNodeId) ?? currentNode;
  const selectedEdge = model.edges.find((edge) => edge.id === selectedEdgeId) ?? null;
  const currentAgent = model.agents.find((agent) => agent.key === model.currentAgentKey) ?? null;
  const activeLabel = currentAgent ? currentAgent.label : currentNode ? (currentNode.agentLabel || currentNode.title) : "等待分派";
  const activeStatus = currentNode ? statusLabel(currentNode.status) : "待启动";
  const runStateLabel = currentNode?.status === "failed" ? "任务图运行异常" : currentNode ? "任务图运行中" : "等待启动";
  const outputCountLabel = model.outputs.length ? `${model.outputs.length} 条输出` : "暂无输出";
  const artifactCountLabel = model.artifacts.length ? `${model.artifacts.length} 个产物` : "暂无产物";
  const contractRuntime = model.contractRuntime;
  const totalNodes = model.nodes.length;
  const runningCount = model.nodes.filter((node) => node.status === "running").length;
  const completedCount = model.nodes.filter((node) => node.status === "completed" || node.status === "success" || node.status === "satisfied").length;
  const blockedCount = model.nodes.filter((node) => node.status === "blocked" || node.status === "failed" || node.status === "waiting_for_human" || node.status === "human_gate").length;
  const progressPercent = totalNodes ? Math.round((completedCount / totalNodes) * 100) : 0;
  const compactSummary = selectedNode
    ? `${selectedNode.title} · ${statusLabel(selectedNode.status)}`
    : currentNode
      ? `${currentNode.title} · ${statusLabel(currentNode.status)}`
      : "等待启动";
  const displayWorkingMemoryOperations = selectedEdge
    ? contractRuntime.workingMemoryOperations.filter((operation) => operation.edgeId === selectedEdge.id)
    : selectedNode
      ? contractRuntime.workingMemoryOperations.filter((operation) => operation.nodeId === selectedNode.id || operation.stageId === selectedNode.id)
      : contractRuntime.workingMemoryOperations;
  const activeContractNode =
    contractRuntime.nodeSummaries.find((node) => node.nodeId === selectedNode?.id)
    ?? contractRuntime.nodeSummaries.find((node) => node.nodeId === model.currentNodeId)
    ?? contractRuntime.nodeSummaries.find((node) => node.status === "blocked")
    ?? contractRuntime.nodeSummaries[0]
    ?? null;
  const activeCoordinationPayload = asRecord(taskGraphRunFromLiveMonitor(liveMonitor));
  const activeCoordinationSummary = asRecord(activeCoordinationPayload.coordination_run);
  const activeCoordinationRunId = taskGraphRunIdFromLiveMonitor(liveMonitor) || text(activeCoordinationSummary.coordination_run_id);
  const taskRunId = text(asRecord(liveMonitor?.task_run).task_run_id);
  const waitingForHuman = Boolean(
    contractRuntime.waitingNodes.length
    || contractRuntime.nodeSummaries.some((node) => node.status === "human_gate" || node.status === "waiting_for_human")
    || model.nodes.some((node) => node.status === "waiting_for_human" || node.status === "human_gate")
  );

  async function resumeWithDecision(decision: "approve" | "retry" | "reject") {
    if (!onResumeTaskGraphRun || !activeCoordinationRunId || resuming) {
      return;
    }
    setResuming(true);
    setResumeError("");
    setResumeNotice("");
    try {
      const stageId = selectedNode?.id || activeContractNode?.nodeId || model.currentNodeId || "";
      await onResumeTaskGraphRun(activeCoordinationRunId, {
        decision,
        stage_id: stageId || undefined,
      });
      setResumeNotice(`已提交 ${decision}，运行态正在刷新。`);
    } catch (error) {
      setResumeError(error instanceof Error ? error.message : "续跑失败");
    } finally {
      setResuming(false);
    }
  }

  if (!model.hasSignal) {
    return (
      <div className="coordination-session-empty">
        <Network size={22} />
        <strong>当前还没有任务图运行</strong>
      </div>
    );
  }

  return (
    <div className="coordination-session">
      <header className="coordination-session__head">
        <div className="coordination-session__heading">
          <span>任务图监控</span>
          <h2>{model.title}</h2>
        </div>
        <div className="coordination-session__statusbar" aria-label="当前任务图运行状态">
          <article className="coordination-session__statuspill">
            <span>状态</span>
            <strong>{runStateLabel}</strong>
          </article>
          <article className="coordination-session__statuspill coordination-session__statuspill--active">
            <span>当前 Agent</span>
            <strong>{activeLabel}</strong>
          </article>
          <article className="coordination-session__statuspill">
            <span>当前节点</span>
            <strong>{currentNode ? currentNode.title : "等待节点"}</strong>
            <em>{activeStatus}</em>
          </article>
          {taskRunId ? (
            <article className="coordination-session__statuspill">
              <span>TaskRun</span>
              <strong>{taskRunId}</strong>
              <em>{activeCoordinationRunId || "无 TaskGraphRun"}</em>
            </article>
          ) : null}
        </div>
        {waitingForHuman && activeCoordinationRunId ? (
          <div className="coordination-session__statusbar" aria-label="人工门控续跑">
            <article className="coordination-session__statuspill coordination-session__statuspill--active">
              <span>人工门控</span>
              <strong>等待决策</strong>
              <em>{activeCoordinationRunId}</em>
            </article>
            <button className="chat-page-tabs__item" disabled={resuming} onClick={() => { void resumeWithDecision("approve"); }} type="button">
              通过
            </button>
            <button className="chat-page-tabs__item" disabled={resuming} onClick={() => { void resumeWithDecision("retry"); }} type="button">
              返修
            </button>
            <button className="chat-page-tabs__item" disabled={resuming} onClick={() => { void resumeWithDecision("reject"); }} type="button">
              拒绝
            </button>
            {resumeNotice ? <span className="chat-page-tabs__signal">{resumeNotice}</span> : null}
            {resumeError ? <span>{resumeError}</span> : null}
          </div>
        ) : null}
      </header>

      <section className="coordination-overview-strip" aria-label="运行总览">
        <article className="coordination-overview-card coordination-overview-card--active">
          <span>当前节点</span>
          <strong>{currentNode ? currentNode.title : "等待启动"}</strong>
          <em>{compactSummary}</em>
        </article>
        <article className="coordination-overview-card">
          <span>总节点</span>
          <strong>{totalNodes}</strong>
          <em>运行中 {runningCount} · 完成 {completedCount}</em>
        </article>
        <article className="coordination-overview-card">
          <span>进度</span>
          <strong>{progressPercent}%</strong>
          <em>阻塞 {blockedCount} · 输出 {model.outputs.length}</em>
        </article>
      </section>

      <section className="coordination-topology-shell" aria-label="任务图运行拓扑">
        <div className="coordination-topology-shell__head">
          <span>执行拓扑</span>
          <p className="coordination-topology-shell__hint">实时显示当前节点与交接状态，选中节点可查看局部运行细节</p>
        </div>
        <div className="coordination-topology-viewport">
          <CoordinationTopologyGraph
            currentHandoffKey={model.currentHandoffKey}
            currentNodeId={model.currentNodeId}
            edges={model.edges}
            emptyDescription="当前会话已经进入任务图运行态，节点与交接关系会在后续运行事件到达后显示。"
            emptyTitle="任务图运行已启动，正在等待拓扑数据"
            nodes={model.nodes}
            onSelectEdge={(edgeId) => {
              setSelectedEdgeId(edgeId);
              setSelectedNodeId("");
            }}
            onSelectNode={(nodeId) => {
              setSelectedNodeId(nodeId);
              setSelectedEdgeId("");
            }}
            selectedEdgeId={selectedEdgeId}
            selectedNodeId={selectedNode?.id || ""}
          />
        </div>
      </section>

      <section className="coordination-contract-board coordination-contract-board--memory" aria-label="工作记忆资源">
        <article className="coordination-output-card coordination-contract-card">
          <div className="coordination-output-card__head">
            <span><Database size={14} /> 工作记忆资源</span>
            <strong>{displayWorkingMemoryOperations.length ? `${displayWorkingMemoryOperations.length} 个操作` : "暂无操作"}</strong>
          </div>
          <div className="coordination-handoff-list">
            {displayWorkingMemoryOperations.length ? displayWorkingMemoryOperations.map((operation) => (
              <article className="coordination-handoff-item" key={operation.key}>
                <div>
                  <strong>{operation.operation}</strong>
                  <span>{operation.status}</span>
                </div>
                <em>{runtimeScopeLabel(operation.nodeId || operation.stageId || operation.edgeId || "graph")}</em>
                <small>{operation.refs.length ? operation.refs.join(" / ") : operation.transactionRef || operation.finalizationRef || "等待引用"}</small>
                {operation.deniedReason ? (
                  <small>拒读原因: {operation.deniedReason}</small>
                ) : null}
                {operation.selectedItemPreviews.length ? (
                  <small>
                    {operation.selectedItemPreviews
                      .slice(0, 3)
                      .map((item) => `${item.work_memory_id || "unknown"} · ${item.owner_node_id || "graph"} · ${item.scope || "node_scope"}`)
                      .join(" / ")}
                  </small>
                ) : null}
              </article>
            )) : (
              <p className="coordination-contract-empty">
                当前运行态还没有工作记忆读写、交接或收尾记录。
              </p>
            )}
          </div>
        </article>
      </section>

      <section className="coordination-output-board">
        <article className="coordination-output-card coordination-output-card--stream">
          <div className="coordination-output-card__head">
            <span><Sparkles size={14} /> 输出内容</span>
            <strong>{outputCountLabel}</strong>
          </div>
          <div className="coordination-output-list">
            {model.outputs.length ? model.outputs.map((output) => (
              <article className="coordination-output-item" key={output.key}>
                <div className="coordination-output-item__meta">
                  <strong>{output.label}</strong>
                </div>
                <pre>{output.content}</pre>
              </article>
            )) : <p>当前还没有检测到可展示的流式内容或最终输出。</p>}
          </div>
        </article>

        <article className="coordination-output-card coordination-output-card--artifacts">
          <div className="coordination-output-card__head">
            <span><FileText size={14} /> 输出产物</span>
            <strong>{artifactCountLabel}</strong>
          </div>
          <div className="coordination-output-list">
            {model.artifacts.length ? model.artifacts.slice(0, 10).map((artifact) => (
              <article className="coordination-output-item coordination-output-item--artifact" key={artifact.key}>
                <div className="coordination-output-item__meta">
                  <strong>{artifact.label}</strong>
                  <span>{artifact.kind} · {artifact.producedBy || "未标注 Agent"}</span>
                </div>
                <em>{artifact.path}</em>
              </article>
            )) : <p>当前还没有检测到文件产物或路径引用。</p>}
          </div>
        </article>
      </section>
    </div>
  );
}
