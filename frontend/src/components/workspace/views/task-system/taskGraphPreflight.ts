import { buildTimelinePreflightIssues } from "./taskGraphTimeline";

export type TaskGraphPreflightSeverity = "error" | "warning" | "info";

export type TaskGraphPreflightScope = "graph" | "node" | "edge" | "phase" | "runtime";

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
}: BuildTaskGraphPreflightReportInput): TaskGraphPreflightReport {
  const issues: TaskGraphPreflightIssue[] = [];
  const nodeIds = nodes.map((node, index) => stringValue(node.node_id ?? node.id ?? `node_${index + 1}`));
  const nodeIdSet = new Set(nodeIds.filter(Boolean));
  const continuationPolicy = recordValue(metadata?.continuation_policy);
  const humanGateMode = stringValue(continuationPolicy.human_gate_mode);

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
    if (!stringValue(edge.payload_contract_id ?? edge.contract_id)) {
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
