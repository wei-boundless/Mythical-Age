export type TaskGraphPhaseDefinition = {
  phase_id: string;
  title: string;
  entry_node_id?: string;
  exit_node_id?: string;
  review_gate_node_id?: string;
  memory_commit_node_id?: string;
  exit_policy?: Record<string, unknown>;
  loop_policy?: Record<string, unknown>;
};

export type TaskGraphLifecyclePolicy = {
  lifecycle_id?: string;
  main_chain_mode?: string;
  maturity_model?: string[];
};

export type TaskGraphTimelinePolicy = {
  ordering?: string;
  parallel_group_policy?: string;
  phase_exit_policy?: string;
};

export type TaskGraphTimelineFrameType = "phase_frame" | "parallel_frame" | "loop_frame" | "review_gate_frame";

export type TaskGraphTimelineFrame = {
  frame_id: string;
  frame_type: TaskGraphTimelineFrameType;
  title: string;
  phase_id?: string;
  sequence_index?: number;
  timeline_group_id?: string;
  node_ids: string[];
  edge_ids: string[];
  review_gate_node_id?: string;
  loop_policy?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  source_frame_type?: string;
};

export type TaskGraphTimelineBlock = {
  block_id: string;
  block_type: string;
  title: string;
  phase_id: string;
  linked_graph_id?: string;
  entry_node_id?: string;
  exit_node_id?: string;
  handoff_contract_id?: string;
  visibility_policy?: string;
  version_ref?: string;
  detach_policy?: string;
  contract_bindings?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
};

export type TaskGraphTimelineIssue = {
  code: string;
  message: string;
  severity: "error" | "warning" | "info";
  node_id?: string;
  edge_id?: string;
  phase_id?: string;
};

export type TaskGraphLifecycleCoordinate = {
  coordinate_key: string;
  node_id: string;
  phase_id: string;
  sequence_index: number;
  legacy_timeline_group_id: string;
  main_chain: boolean;
  blocks_phase_exit: boolean;
};

export type TaskGraphTimelinePhase = {
  phase: TaskGraphPhaseDefinition;
  nodes: Array<Record<string, unknown>>;
  node_coordinates: TaskGraphLifecycleCoordinate[];
  issues: TaskGraphTimelineIssue[];
};

export const DEFAULT_PHASE_ID = "phase.unassigned";

export const DEFAULT_LIFECYCLE_POLICY: TaskGraphLifecyclePolicy = {
  lifecycle_id: "task_graph_default",
  main_chain_mode: "lifecycle_coordinates",
  maturity_model: ["draft", "mutual_review", "candidate_final", "review_passed", "committed"],
};

export const DEFAULT_TIMELINE_POLICY: TaskGraphTimelinePolicy = {
  ordering: "lifecycle_coordinate_display",
  parallel_group_policy: "explicit_edges_and_join_policy",
  phase_exit_policy: "all_blocking_nodes_complete",
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function contractBindingValue(target: Record<string, unknown>, section: string, key: string): string {
  return String(asRecord(asRecord(target.contract_bindings)[section])[key] ?? "").trim();
}

function nodeContractIdOf(node: Record<string, unknown>): string {
  return contractBindingValue(node, "execution", "node_contract_id") || String(node.node_contract_id ?? node.contract_id ?? "").trim();
}

function nodeOutputContractIdOf(node: Record<string, unknown>): string {
  return contractBindingValue(node, "schema", "output_contract_id") || String(node.output_contract_id ?? "").trim();
}

export function timelineBlockHandoffContractIdOf(block: Record<string, unknown>): string {
  return String(asRecord(asRecord(block.contract_bindings).handoff).handoff_contract_id ?? block.handoff_contract_id ?? "").trim();
}

function asRecordArray(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item)) : [];
}

function asStringArray(value: unknown) {
  return Array.isArray(value) ? value.map((item) => String(item ?? "").trim()).filter(Boolean) : [];
}

function isTimelineFrameType(value: string): value is TaskGraphTimelineFrameType {
  return ["phase_frame", "parallel_frame", "loop_frame", "review_gate_frame"].includes(value);
}

export function nodeIdOf(node: Record<string, unknown>, index = 0) {
  return String(node.node_id ?? node.id ?? `node_${index + 1}`);
}

export function nodeTitle(node: Record<string, unknown>, index = 0) {
  return String(node.title ?? node.label ?? node.task_title ?? nodeIdOf(node, index));
}

export function graphEdgeSource(edge: Record<string, unknown>) {
  return String(edge.source_node_id ?? edge.from ?? edge.source ?? "");
}

export function graphEdgeTarget(edge: Record<string, unknown>) {
  return String(edge.target_node_id ?? edge.to ?? edge.target ?? "");
}

export function nodeTimelineValue<T = unknown>(node: Record<string, unknown>, key: string, fallback: T): T {
  const metadata = asRecord(node.metadata);
  const value = node[key] ?? metadata[key];
  return (value === undefined || value === null || value === "") ? fallback : value as T;
}

export function nodePhaseId(node: Record<string, unknown>) {
  return String(nodeTimelineValue(node, "phase_id", DEFAULT_PHASE_ID));
}

export function nodeSequenceIndex(node: Record<string, unknown>) {
  const value = Number(nodeTimelineValue(node, "sequence_index", 1));
  return Number.isFinite(value) && value > 0 ? value : 1;
}

export function nodeTimelineGroupId(node: Record<string, unknown>) {
  return String(nodeTimelineValue(node, "timeline_group_id", ""));
}

export function nodeMainChain(node: Record<string, unknown>) {
  return Boolean(nodeTimelineValue(node, "main_chain", false));
}

export function nodeBlocksPhaseExit(node: Record<string, unknown>) {
  return Boolean(nodeTimelineValue(node, "blocks_phase_exit", false));
}

export function nodeReviewGatePolicy(node: Record<string, unknown>) {
  return asRecord(nodeTimelineValue(node, "review_gate_policy", {}));
}

export function nodeLoopPolicy(node: Record<string, unknown>) {
  return asRecord(nodeTimelineValue(node, "loop_policy", {}));
}

export function nodeCompletionPolicy(node: Record<string, unknown>) {
  return String(nodeTimelineValue(node, "completion_policy", ""));
}

export function coordinationLifecyclePolicy(metadata: Record<string, unknown> | undefined): TaskGraphLifecyclePolicy {
  return { ...DEFAULT_LIFECYCLE_POLICY, ...asRecord(metadata?.lifecycle_policy) };
}

export function coordinationTimelinePolicy(metadata: Record<string, unknown> | undefined): TaskGraphTimelinePolicy {
  return { ...DEFAULT_TIMELINE_POLICY, ...asRecord(metadata?.timeline_policy) };
}

export function coordinationTimelineFrames(metadata: Record<string, unknown> | undefined): TaskGraphTimelineFrame[] {
  return asRecordArray(metadata?.timeline_frames)
    .map((item, index): TaskGraphTimelineFrame => {
      const frameType = String(item.frame_type ?? item.type ?? "phase_frame");
      const normalizedType = isTimelineFrameType(frameType) ? frameType : "phase_frame";
      const frameId = String(item.frame_id ?? item.id ?? `timeline_frame_${index + 1}`).trim();
      return {
        frame_id: frameId || `timeline_frame_${index + 1}`,
        frame_type: normalizedType,
        title: String(item.title ?? item.name ?? frameId ?? `Frame ${index + 1}`).trim(),
        phase_id: String(item.phase_id ?? "").trim() || undefined,
        sequence_index: Number.isFinite(Number(item.sequence_index)) ? Number(item.sequence_index) : undefined,
        timeline_group_id: String(item.timeline_group_id ?? "").trim() || undefined,
        node_ids: asStringArray(item.node_ids),
        edge_ids: asStringArray(item.edge_ids),
        review_gate_node_id: String(item.review_gate_node_id ?? "").trim() || undefined,
        loop_policy: asRecord(item.loop_policy),
        metadata: asRecord(item.metadata),
        source_frame_type: frameType,
      };
    })
    .filter((item) => item.frame_id);
}

export function coordinationTimelineBlocks(metadata: Record<string, unknown> | undefined): TaskGraphTimelineBlock[] {
  return asRecordArray(metadata?.timeline_blocks)
    .map((item, index): TaskGraphTimelineBlock => {
      const blockId = String(item.block_id ?? item.id ?? `timeline_block_${index + 1}`).trim();
      return {
        block_id: blockId || `timeline_block_${index + 1}`,
        block_type: String(item.block_type ?? "phase_graph").trim() || "phase_graph",
        title: String(item.title ?? item.name ?? blockId ?? `图块 ${index + 1}`).trim(),
        phase_id: String(item.phase_id ?? "").trim(),
        linked_graph_id: String(item.linked_graph_id ?? item.graph_id ?? "").trim() || undefined,
        entry_node_id: String(item.entry_node_id ?? "").trim() || undefined,
        exit_node_id: String(item.exit_node_id ?? "").trim() || undefined,
        handoff_contract_id: String(item.handoff_contract_id ?? "").trim() || undefined,
        visibility_policy: String(item.visibility_policy ?? "committed_only").trim() || "committed_only",
        version_ref: String(item.version_ref ?? "").trim() || undefined,
        detach_policy: String(item.detach_policy ?? "preserve_version_anchor").trim() || "preserve_version_anchor",
        contract_bindings: asRecord(item.contract_bindings),
        metadata: asRecord(item.metadata),
      };
    })
    .filter((item) => item.block_id);
}

export function coordinationPhaseDefinitions(metadata: Record<string, unknown> | undefined, nodes: Array<Record<string, unknown>>): TaskGraphPhaseDefinition[] {
  const explicit = asRecordArray(metadata?.phase_definitions)
    .map((item): TaskGraphPhaseDefinition => ({
      phase_id: String(item.phase_id ?? "").trim(),
      title: String(item.title ?? item.phase_id ?? "").trim(),
      entry_node_id: String(item.entry_node_id ?? ""),
      exit_node_id: String(item.exit_node_id ?? ""),
      review_gate_node_id: String(item.review_gate_node_id ?? ""),
      memory_commit_node_id: String(item.memory_commit_node_id ?? ""),
      exit_policy: asRecord(item.exit_policy),
      loop_policy: asRecord(item.loop_policy),
    }))
    .filter((item) => item.phase_id);
  if (explicit.length) return explicit;

  const phaseIds = Array.from(new Set(nodes.map(nodePhaseId).filter(Boolean)));
  return (phaseIds.length ? phaseIds : [DEFAULT_PHASE_ID]).map((phaseId) => ({
    phase_id: phaseId,
    title: phaseId === DEFAULT_PHASE_ID ? "未分配阶段" : phaseId.replace(/^phase\./, ""),
  }));
}

export function buildTimelinePhases({
  nodes,
  metadata,
}: {
  nodes: Array<Record<string, unknown>>;
  metadata?: Record<string, unknown>;
}): TaskGraphTimelinePhase[] {
  const definitions = coordinationPhaseDefinitions(metadata, nodes);
  const knownPhaseIds = new Set(definitions.map((item) => item.phase_id));
  const extraPhaseIds = Array.from(new Set(nodes.map(nodePhaseId).filter((phaseId) => !knownPhaseIds.has(phaseId))));
  const phases = [
    ...definitions,
    ...extraPhaseIds.map((phaseId) => ({ phase_id: phaseId, title: phaseId.replace(/^phase\./, "") })),
  ];

  return phases.map((phase) => {
    const phaseNodes = nodes
      .filter((node) => nodePhaseId(node) === phase.phase_id)
      .sort((left, right) => nodeSequenceIndex(left) - nodeSequenceIndex(right) || nodeTitle(left).localeCompare(nodeTitle(right)));
    const nodeCoordinates = phaseNodes.map((node): TaskGraphLifecycleCoordinate => {
      const nodeId = nodeIdOf(node);
      return {
        coordinate_key: `${phase.phase_id}:${nodeId}`,
        node_id: nodeId,
        phase_id: phase.phase_id,
        sequence_index: nodeSequenceIndex(node),
        legacy_timeline_group_id: nodeTimelineGroupId(node),
        main_chain: nodeMainChain(node),
        blocks_phase_exit: nodeBlocksPhaseExit(node),
      };
    });
    return {
      phase,
      nodes: phaseNodes,
      node_coordinates: nodeCoordinates,
      issues: [],
    };
  });
}

function hasPath(edges: Array<Record<string, unknown>>, start: string, target: string) {
  if (!start || !target) return false;
  if (start === target) return true;
  const nextBySource = new Map<string, string[]>();
  for (const edge of edges) {
    const source = graphEdgeSource(edge);
    const next = graphEdgeTarget(edge);
    if (!source || !next) continue;
    nextBySource.set(source, [...(nextBySource.get(source) ?? []), next]);
  }
  const visited = new Set<string>();
  const queue = [start];
  while (queue.length) {
    const current = queue.shift() ?? "";
    if (current === target) return true;
    if (visited.has(current)) continue;
    visited.add(current);
    queue.push(...(nextBySource.get(current) ?? []).filter((nodeId) => !visited.has(nodeId)));
  }
  return false;
}

function hasLoopStopCondition(policy: Record<string, unknown>) {
  return Boolean(
    Number(policy.max_attempts ?? 0) > 0
    || Number(policy.target_units ?? 0) > 0
    || Number(policy.target_count ?? 0) > 0
    || Number(policy.target_words ?? 0) > 0
    || Number(policy.unit_count ?? 0) > 0
    || String(policy.exit_condition ?? "").trim()
    || String(policy.exit_stage_id ?? "").trim()
  );
}

export function buildTimelinePreflightIssues(
  nodes: Array<Record<string, unknown>>,
  edges: Array<Record<string, unknown>>,
  metadata?: Record<string, unknown>,
): TaskGraphTimelineIssue[] {
  const issues: TaskGraphTimelineIssue[] = [];
  const nodeIds = new Set(nodes.map((node, index) => nodeIdOf(node, index)));
  const edgeIds = new Set(edges.map((edge, index) => String(edge.edge_id ?? edge.id ?? `${graphEdgeSource(edge)}-${graphEdgeTarget(edge)}-${index}`).trim()).filter(Boolean));
  const phaseDefinitions = coordinationPhaseDefinitions(metadata, nodes);
  const timelineFrames = coordinationTimelineFrames(metadata);
  const timelineBlocks = coordinationTimelineBlocks(metadata);
  const explicitPhaseDefinitions = asRecordArray(metadata?.phase_definitions);
  const nodePhaseIds = new Set(nodes.map(nodePhaseId).filter(Boolean));

  if (!explicitPhaseDefinitions.length && nodePhaseIds.size > 0 && !nodePhaseIds.has(DEFAULT_PHASE_ID)) {
    issues.push({
      code: "timeline_phase_definitions_missing",
      message: "节点已经配置 phase_id，但图级 phase_definitions 还没有建立。",
      severity: "warning",
    });
  }

  for (const phase of phaseDefinitions) {
    const phaseNodes = nodes.filter((node) => nodePhaseId(node) === phase.phase_id);
    if (!phaseNodes.length) {
      issues.push({ code: "timeline_phase_empty", message: `阶段 ${phase.title || phase.phase_id} 没有节点。`, severity: "warning", phase_id: phase.phase_id });
    }
    if (phase.entry_node_id && !nodeIds.has(phase.entry_node_id)) {
      issues.push({ code: "timeline_phase_entry_missing", message: `阶段 ${phase.title || phase.phase_id} 的入口节点不存在。`, severity: "error", phase_id: phase.phase_id });
    }
    if (phase.exit_node_id && !nodeIds.has(phase.exit_node_id)) {
      issues.push({ code: "timeline_phase_exit_missing", message: `阶段 ${phase.title || phase.phase_id} 的出口节点不存在。`, severity: "error", phase_id: phase.phase_id });
    }
    if (phase.review_gate_node_id && !nodeIds.has(phase.review_gate_node_id)) {
      issues.push({ code: "timeline_phase_review_gate_missing", message: `阶段 ${phase.title || phase.phase_id} 的审核门节点不存在。`, severity: "error", phase_id: phase.phase_id });
    }
    if (phase.entry_node_id && phase.exit_node_id && !hasPath(edges, phase.entry_node_id, phase.exit_node_id)) {
      issues.push({ code: "timeline_phase_main_path_missing", message: `阶段 ${phase.title || phase.phase_id} 的入口到出口没有连通路径。`, severity: "warning", phase_id: phase.phase_id });
    }
    if (Object.keys(asRecord(phase.loop_policy)).length && !hasLoopStopCondition(asRecord(phase.loop_policy))) {
      issues.push({ code: "timeline_phase_loop_stop_missing", message: `阶段 ${phase.title || phase.phase_id} 的循环策略缺少停止条件。`, severity: "error", phase_id: phase.phase_id });
    }
  }

  for (const frame of timelineFrames) {
    if (frame.source_frame_type === "step_frame") {
      issues.push({
        code: "timeline_frame_step_frame_legacy",
        message: `Frame ${frame.title || frame.frame_id} 使用了已废弃的 step_frame；编辑器不再把运行 step 作为可建模结构。`,
        severity: "warning",
      });
    }
    if (!frame.node_ids.length) {
      issues.push({ code: "timeline_frame_empty", message: `时序 Frame ${frame.title || frame.frame_id} 没有包含节点。`, severity: "warning" });
    }
    for (const nodeId of frame.node_ids) {
      if (!nodeIds.has(nodeId)) {
        issues.push({ code: "timeline_frame_node_missing", message: `时序 Frame ${frame.title || frame.frame_id} 引用了不存在的节点 ${nodeId}。`, severity: "error", node_id: nodeId });
      }
    }
    for (const edgeId of frame.edge_ids) {
      if (!edgeIds.has(edgeId)) {
        issues.push({ code: "timeline_frame_edge_missing", message: `时序 Frame ${frame.title || frame.frame_id} 引用了不存在的通信边 ${edgeId}。`, severity: "warning", edge_id: edgeId });
      }
    }
    if (frame.phase_id && !phaseDefinitions.some((phase) => phase.phase_id === frame.phase_id)) {
      issues.push({ code: "timeline_frame_phase_missing", message: `时序 Frame ${frame.title || frame.frame_id} 绑定的阶段 ${frame.phase_id} 不存在。`, severity: "warning", phase_id: frame.phase_id });
    }
    if (frame.frame_type === "review_gate_frame") {
      if (!frame.review_gate_node_id) {
        issues.push({ code: "timeline_frame_review_gate_missing", message: `审核 Frame ${frame.title || frame.frame_id} 缺少审核门节点。`, severity: "error" });
      } else if (!nodeIds.has(frame.review_gate_node_id)) {
        issues.push({ code: "timeline_frame_review_gate_node_missing", message: `审核 Frame ${frame.title || frame.frame_id} 的审核门节点不存在。`, severity: "error", node_id: frame.review_gate_node_id });
      } else if (!frame.node_ids.includes(frame.review_gate_node_id)) {
        issues.push({ code: "timeline_frame_review_gate_outside", message: `审核 Frame ${frame.title || frame.frame_id} 的审核门节点不在 Frame 节点集合中。`, severity: "warning", node_id: frame.review_gate_node_id });
      }
    }
    if (frame.frame_type === "loop_frame" && !hasLoopStopCondition(asRecord(frame.loop_policy))) {
      issues.push({ code: "timeline_frame_loop_stop_missing", message: `循环 Frame ${frame.title || frame.frame_id} 缺少停止条件。`, severity: "error" });
    }
  }

  for (const block of timelineBlocks) {
    if (!block.phase_id) {
      issues.push({ code: "timeline_block_phase_missing", message: `图块 ${block.title || block.block_id} 缺少 phase_id。`, severity: "error" });
    } else if (!phaseDefinitions.some((phase) => phase.phase_id === block.phase_id)) {
      issues.push({ code: "timeline_block_phase_unknown", message: `图块 ${block.title || block.block_id} 绑定的阶段 ${block.phase_id} 不存在。`, severity: "warning", phase_id: block.phase_id });
    }
    if (!block.entry_node_id) {
      issues.push({ code: "timeline_block_entry_missing", message: `图块 ${block.title || block.block_id} 缺少 entry_node_id。`, severity: "warning", phase_id: block.phase_id });
    } else if (!nodeIds.has(block.entry_node_id)) {
      issues.push({ code: "timeline_block_entry_unknown", message: `图块 ${block.title || block.block_id} 的入口节点不存在。`, severity: "error", node_id: block.entry_node_id, phase_id: block.phase_id });
    }
    if (!block.exit_node_id) {
      issues.push({ code: "timeline_block_exit_missing", message: `图块 ${block.title || block.block_id} 缺少 exit_node_id。`, severity: "warning", phase_id: block.phase_id });
    } else if (!nodeIds.has(block.exit_node_id)) {
      issues.push({ code: "timeline_block_exit_unknown", message: `图块 ${block.title || block.block_id} 的出口节点不存在。`, severity: "error", node_id: block.exit_node_id, phase_id: block.phase_id });
    }
    if (!timelineBlockHandoffContractIdOf(block as unknown as Record<string, unknown>)) {
      issues.push({ code: "timeline_block_handoff_contract_missing", message: `图块 ${block.title || block.block_id} 缺少 handoff_contract_id。`, severity: "warning", phase_id: block.phase_id });
    }
    if (!block.linked_graph_id) {
      issues.push({ code: "timeline_block_imported_graph_missing", message: `图块 ${block.title || block.block_id} 还没有绑定 linked_graph_id，运行时只能把它视为当前图内的生命周期阶段块。`, severity: "warning", phase_id: block.phase_id });
    }
    if (!block.version_ref) {
      issues.push({ code: "timeline_block_version_anchor_missing", message: `图块 ${block.title || block.block_id} 缺少 version_ref，断开后难以追踪旧引用。`, severity: "info", phase_id: block.phase_id });
    }
    if (timelineBlocks.length > 1 && !String(block.visibility_policy ?? "").trim()) {
      issues.push({ code: "timeline_block_visibility_missing", message: `图块 ${block.title || block.block_id} 缺少 visibility_policy，多图块联合运行会丢失跨图可见性边界。`, severity: "warning", phase_id: block.phase_id });
    }
  }

  for (const edge of edges) {
    const edgeType = String(edge.edge_type ?? edge.mode ?? "");
    const metadata = asRecord(edge.metadata);
    const temporal = asRecord(metadata.temporal_semantics);
    const isTemporalEdge = edgeType === "temporal_dependency" || String(metadata.dependency_role ?? "").includes("temporal") || Object.keys(temporal).length > 0;
    if (!isTemporalEdge) continue;
    const edgeId = String(edge.edge_id ?? edge.id ?? `${graphEdgeSource(edge)}-${graphEdgeTarget(edge)}`).trim();
    for (const key of ["trigger_timing", "visibility_timing", "acknowledgement_timing", "propagation_timing", "phase_timing"]) {
      if (!String(temporal[key] ?? "").trim()) {
        issues.push({ code: `timeline_edge_${key}_missing`, message: `边 ${edgeId} 缺少 ${key}。`, severity: "warning", edge_id: edgeId });
      }
    }
  }

  for (const node of nodes) {
    const nodeId = String(node.node_id ?? "");
    const reviewPolicy = nodeReviewGatePolicy(node);
    const loopPolicy = nodeLoopPolicy(node);
    const isReviewGate = Boolean(reviewPolicy.is_review_gate) || String(node.node_type ?? "") === "review_gate";
    if (isReviewGate) {
      if (!nodeContractIdOf(node)) {
        issues.push({ code: "timeline_review_gate_contract_missing", message: "审核门节点缺少节点契约。", severity: "error", node_id: nodeId });
      }
      if (!nodeOutputContractIdOf(node)) {
        issues.push({ code: "timeline_review_gate_output_contract_missing", message: "审核门节点缺少输出契约。", severity: "error", node_id: nodeId });
      }
      if (!String(reviewPolicy.on_pass ?? "").trim()) {
        issues.push({ code: "timeline_review_gate_pass_route_missing", message: "审核门节点缺少通过路线。", severity: "warning", node_id: nodeId });
      }
      if (!String(reviewPolicy.on_fail ?? "").trim()) {
        issues.push({ code: "timeline_review_gate_fail_route_missing", message: "审核门节点缺少失败返修路线。", severity: "warning", node_id: nodeId });
      }
    }
    if (Object.keys(loopPolicy).length && !hasLoopStopCondition(loopPolicy)) {
      issues.push({ code: "timeline_node_loop_stop_missing", message: "节点循环策略缺少停止条件。", severity: "error", node_id: nodeId });
    }
    if (nodeBlocksPhaseExit(node) && ["async", "background"].includes(String(node.execution_mode ?? "")) && !nodeCompletionPolicy(node)) {
      issues.push({ code: "timeline_blocking_async_completion_missing", message: "阻塞阶段退出的异步/后台节点缺少 completion_policy。", severity: "error", node_id: nodeId });
    }
    if (["memory", "memory_resource", "memory_read", "memory_write", "memory_handoff", "memory_commit", "memory_finalize"].includes(String(node.node_type ?? ""))) {
      const phase = phaseDefinitions.find((item) => item.phase_id === nodePhaseId(node));
      if (!phase?.review_gate_node_id) {
        issues.push({ code: "timeline_memory_without_review_gate", message: "记忆节点所在阶段没有配置审核门。", severity: "warning", node_id: nodeId, phase_id: phase?.phase_id });
      }
    }
  }

  return issues;
}
