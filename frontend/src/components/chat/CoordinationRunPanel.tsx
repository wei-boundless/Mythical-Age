"use client";

import {
  GitBranch,
  FileText,
  Network,
  PackageCheck,
  Sparkles,
} from "lucide-react";
import { useMemo, useState } from "react";

import {
  CoordinationTopologyGraph,
  type CoordinationTopologyEdge,
  type CoordinationTopologyNode,
} from "@/components/coordination/CoordinationTopologyGraph";
import type { OrchestrationEvent, OrchestrationSnapshot } from "@/lib/api";

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
};

type CoordinationOutput = {
  key: string;
  label: string;
  content: string;
};

type CoordinationStage = {
  stageId: string;
  nodeId: string;
  taskRef: string;
  status: string;
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

function walk(value: unknown, visitor: (record: Record<string, unknown>) => void, depth = 0) {
  if (depth > 7) {
    return;
  }
  if (Array.isArray(value)) {
    for (const item of value) {
      walk(item, visitor, depth + 1);
    }
    return;
  }
  const record = asRecord(value);
  if (!Object.keys(record).length) {
    return;
  }
  visitor(record);
  for (const item of Object.values(record)) {
    if (item && typeof item === "object") {
      walk(item, visitor, depth + 1);
    }
  }
}

function firstString(events: OrchestrationEvent[], keys: string[]) {
  for (const event of events) {
    let found = "";
    walk(event.data, (record) => {
      if (found) {
        return;
      }
      for (const key of keys) {
        const value = text(record[key]);
        if (value) {
          found = value;
          return;
        }
      }
    });
    if (found) {
      return found;
    }
  }
  return "";
}

function findArray(events: OrchestrationEvent[], keys: string[]) {
  let found: unknown[] = [];
  for (const event of events) {
    walk(event.data, (record) => {
      if (found.length) {
        return;
      }
      for (const key of keys) {
        const value = asArray(record[key]);
        if (value.length) {
          found = value;
          return;
        }
      }
    });
    if (found.length) {
      return found;
    }
  }
  return found;
}

function findRecord(events: OrchestrationEvent[], keys: string[]) {
  let found: Record<string, unknown> = {};
  for (const event of events) {
    walk(event.data, (record) => {
      if (Object.keys(found).length) {
        return;
      }
      for (const key of keys) {
        const value = asRecord(record[key]);
        if (Object.keys(value).length) {
          found = value;
          return;
        }
      }
    });
    if (Object.keys(found).length) {
      return found;
    }
  }
  return found;
}

function collectAgentRuns(events: OrchestrationEvent[]) {
  const byId = new Map<string, Record<string, unknown>>();
  for (const event of events) {
    walk(event.data, (record) => {
      const id = text(record.agent_run_id);
      if (!id) {
        return;
      }
      const spawnMode = text(record.spawn_mode);
      const coordinationRef = text(record.coordination_run_ref);
      const role = text(record.role);
      if (spawnMode.includes("coordination") || coordinationRef || role === "coordinator") {
        byId.set(id, record);
      }
    });
  }
  return Array.from(byId.values());
}

function collectCoordinationStages(events: OrchestrationEvent[]) {
  const flow = findRecord(events, ["coordination_flow"]);
  const stages = asArray(flow.stages)
    .map((item) => asRecord(item))
    .map((item): CoordinationStage | null => {
      const nodeId = text(item.node_id) || text(item.stage_id);
      const stageId = text(item.stage_id) || nodeId;
      if (!nodeId && !stageId) {
        return null;
      }
      return {
        stageId,
        nodeId,
        taskRef: text(item.task_ref),
        status: text(item.status, "pending")
      };
    })
    .filter((item): item is CoordinationStage => Boolean(item));
  return {
    flow,
    stages
  };
}

function collectCoordinationNodeRuns(events: OrchestrationEvent[]) {
  const byId = new Map<string, Record<string, unknown>>();
  for (const event of events) {
    walk(event.data, (record) => {
      const nodeRunId = text(record.node_run_id);
      const nodeId = text(record.node_id);
      const coordinationRunId = text(record.coordination_run_id);
      if (!nodeRunId && !nodeId) {
        return;
      }
      if (!coordinationRunId && !nodeId) {
        return;
      }
      byId.set(nodeRunId || nodeId, record);
    });
  }
  return Array.from(byId.values());
}

function collectHandoffs(events: OrchestrationEvent[]) {
  const byId = new Map<string, Record<string, unknown>>();
  for (const event of events) {
    walk(event.data, (record) => {
      const handoff = asRecord(record.handoff_envelope);
      const sourceAgentRunRef = text(handoff.source_agent_run_ref) || text(record.source_agent_run_ref);
      const targetAgentRunRef = text(handoff.target_agent_run_ref) || text(record.target_agent_run_ref);
      const id = text(handoff.handoff_id) || text(record.handoff_id) || (sourceAgentRunRef && targetAgentRunRef ? `${sourceAgentRunRef}->${targetAgentRunRef}` : "");
      if (!id || !sourceAgentRunRef || !targetAgentRunRef) {
        return;
      }
      byId.set(id, Object.keys(handoff).length ? handoff : record);
    });
  }
  return Array.from(byId.values());
}

function collectHandoffPackets(events: OrchestrationEvent[]) {
  const byId = new Map<string, Record<string, unknown>>();
  for (const event of events) {
    walk(event.data, (record) => {
      const packets = asArray(record.handoff_packets).map((item) => asRecord(item));
      for (const packet of packets) {
        const sourceNodeId = text(packet.source_node_id);
        const targetNodeId = text(packet.target_node_id);
        const a2aTrace = asRecord(packet.a2a_trace);
        const key =
          text(packet.handoff_id)
          || (sourceNodeId && targetNodeId ? `${sourceNodeId}->${targetNodeId}:${text(packet.edge_contract_ref) || text(a2aTrace.message_type)}` : "");
        if (!key) {
          continue;
        }
        byId.set(key, packet);
      }
    });
  }
  return Array.from(byId.entries()).map(([key, packet]): CoordinationHandoffPreview => {
    const a2aTrace = asRecord(packet.a2a_trace);
    return {
      key,
      sourceNodeId: text(packet.source_node_id),
      targetNodeId: text(packet.target_node_id),
      messageType: text(packet.message_type) || text(a2aTrace.message_type, "message/send"),
      status: text(packet.status, "pending"),
      contractRefs: stringArray(packet.contract_refs || packet.contract_ref || packet.edge_contract_ref),
      artifactRefs: stringArray(packet.artifact_refs),
      resultRefs: stringArray(packet.result_refs),
      runtimeAssemblyRef: text(packet.runtime_assembly_ref),
      contractManifestRef: text(packet.contract_manifest_ref)
    };
  });
}

function agentLabel(profileId: string, agentId = "") {
  const labels: Record<string, string> = {
    main_interactive_agent: "主 Agent",
  };
  if (labels[profileId]) {
    return labels[profileId];
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
  return fallback || nodeId.replace(/_/g, " ");
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

function pushArtifact(bucket: CoordinationArtifact[], seen: Set<string>, path: string, kind: string, label = "") {
  const normalized = path.trim();
  if (!normalized || seen.has(`${kind}:${normalized}`)) {
    return;
  }
  seen.add(`${kind}:${normalized}`);
  bucket.push({
    key: `${kind}:${normalized}`,
    label: label || normalized.split(/[\\/]/).pop() || normalized,
    path: normalized,
    kind
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

function buildContractRuntime(
  events: OrchestrationEvent[],
  nodes: CoordinationNode[],
  fallbackCurrentNodeId: string,
): CoordinationContractRuntime {
  const runtimeState = findRecord(events, ["langgraph_runtime_state"]);
  const contractStatus = asRecord(runtimeState.contract_status);
  const nodeStatus = asRecord(contractStatus.node_status);
  const issues = asArray(contractStatus.issues)
    .map((item) => {
      const issue = asRecord(item);
      return text(issue.message) || text(issue.issue) || text(item);
    })
    .filter(Boolean);
  const nodeTitleById = new Map(nodes.map((node) => [node.id, node.title]));
  const nodeSummaries = Object.entries(nodeStatus)
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
        taskResultRef: text(item.task_result_ref)
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
  return {
    manifestRef: text(runtimeState.contract_manifest_ref) || text(contractStatus.manifest_ref),
    valid: contractStatus.valid === true || runtimeState.valid === true,
    issues,
    readyNodes: stringArray(runtimeState.ready_nodes),
    blockedNodes: stringArray(runtimeState.blocked_nodes),
    runningNodes: stringArray(runtimeState.running_nodes),
    waitingNodes: stringArray(runtimeState.waiting_nodes),
    completedNodes: stringArray(runtimeState.completed_nodes),
    failedNodes: stringArray(runtimeState.failed_nodes),
    nodeSummaries,
    handoffs: collectHandoffPackets(events).slice(-6)
  };
}

function buildModel(snapshot: OrchestrationSnapshot | null): CoordinationModel {
  const events = snapshot?.events ?? [];
  const coordinationTaskRef = firstString(events, ["coordination_task_ref", "coordination_task_id"]);
  const rawNodes = findArray(events, ["graph_nodes", "nodes"]);
  const rawEdges = findArray(events, ["graph_edges", "edges"]);
  const agentRuns = collectAgentRuns(events);
  const nodeRuns = collectCoordinationNodeRuns(events);
  const handoffs = collectHandoffs(events);
  const runtimeState = findRecord(events, ["langgraph_runtime_state"]);
  const { flow: flowState, stages: flowStages } = collectCoordinationStages(events);
  const statusByNode = new Map<string, string>();
  const agentByNode = new Map<string, string>();
  const nodeRoleById = new Map<string, string>();
  const runningAgentByNode = new Map<string, string>();
  const nodeIdByAgentRunId = new Map<string, string>();
  const currentEdgeKeyCandidates = new Set<string>();
  const artifacts: CoordinationArtifact[] = [];
  const outputs: CoordinationOutput[] = [];
  const artifactSeen = new Set<string>();
  const outputSeen = new Set<string>();
  let streamingContent = "";
  let currentAgentKey = "";
  let currentHandoffKey = "";
  const stageById = new Map(flowStages.map((stage) => [stage.stageId, stage]));
  const stageByNodeId = new Map(flowStages.map((stage) => [stage.nodeId, stage]));
  const flowCurrentNodeId = text(
    flowStages.find((stage) => stage.status === "running")?.nodeId
      || stageById.get(text(flowState.current_stage_id))?.nodeId
  );

  for (const stage of flowStages) {
    if (!statusByNode.has(stage.nodeId) || stage.status === "running") {
      statusByNode.set(stage.nodeId, stage.status);
    }
  }

  for (const nodeId of stringArray(runtimeState.ready_nodes)) {
    if (!statusByNode.has(nodeId)) {
      statusByNode.set(nodeId, "ready");
    }
  }
  for (const nodeId of stringArray(runtimeState.blocked_nodes)) {
    statusByNode.set(nodeId, "blocked");
  }
  for (const nodeId of stringArray(runtimeState.running_nodes)) {
    statusByNode.set(nodeId, "running");
  }
  for (const nodeId of stringArray(runtimeState.waiting_nodes)) {
    statusByNode.set(nodeId, "waiting_for_human");
  }
  for (const nodeId of stringArray(runtimeState.completed_nodes)) {
    if (statusByNode.get(nodeId) !== "running") {
      statusByNode.set(nodeId, "completed");
    }
  }
  for (const nodeId of stringArray(runtimeState.failed_nodes)) {
    statusByNode.set(nodeId, "failed");
  }

  const contractStatus = asRecord(runtimeState.contract_status);
  const contractNodeStatus = asRecord(contractStatus.node_status);
  for (const [nodeId, raw] of Object.entries(contractNodeStatus)) {
    const contractNode = asRecord(raw);
    const contractState = text(contractNode.status);
    if (contractState === "satisfied") {
      if (statusByNode.get(nodeId) !== "running") {
        statusByNode.set(nodeId, "completed");
      }
    } else if (contractState === "failed" || contractState === "blocked") {
      statusByNode.set(nodeId, contractState);
    } else if (contractState === "human_gate") {
      statusByNode.set(nodeId, "waiting_for_human");
    } else if (contractState === "pending_retry") {
      statusByNode.set(nodeId, "ready");
    }
  }

  for (const run of nodeRuns) {
    const nodeId = text(run.node_id);
    if (!nodeId) {
      continue;
    }
    const diagnostics = asRecord(run.diagnostics);
    statusByNode.set(nodeId, text(diagnostics.stage_status) || text(run.status, "idle"));
    nodeRoleById.set(nodeId, roleLabel(text(run.role)));
    const assignedAgentRunRef = text(run.assigned_agent_run_ref);
    if (assignedAgentRunRef) {
      nodeIdByAgentRunId.set(assignedAgentRunRef, nodeId);
    }
  }

  for (const run of agentRuns) {
    const diagnostics = asRecord(run.diagnostics);
    const nodeId = text(diagnostics.node_id) || text(diagnostics.stage_id) || text(run.node_id);
    if (!nodeId) {
      continue;
    }
    const agentRunId = text(run.agent_run_id);
    const agentName = agentLabel(text(run.agent_profile_id), text(run.agent_id));
    const runStatus = text(run.status, "running");
    if (agentRunId) {
      nodeIdByAgentRunId.set(agentRunId, nodeId);
    }
    if (!statusByNode.has(nodeId) || runStatus === "running") {
      statusByNode.set(nodeId, runStatus);
    }
    if (!agentByNode.has(nodeId) || runStatus === "running") {
      agentByNode.set(nodeId, agentName);
    }
    if (runStatus === "running") {
      runningAgentByNode.set(nodeId, agentName);
      currentAgentKey = agentRunId;
    }
  }

  const stageNodes = flowStages.map((stage): CoordinationNode => ({
    id: stage.nodeId,
    title: nodeTitle(stage.nodeId, compactTaskLabel(stage.taskRef) || stage.stageId),
    role: nodeRoleById.get(stage.nodeId) || roleLabel("participant"),
    agentLabel: runningAgentByNode.get(stage.nodeId) || agentByNode.get(stage.nodeId) || "待分派",
    status: statusByNode.get(stage.nodeId) || stage.status
  }));

  const graphNodes = rawNodes
    .map((item): CoordinationNode | null => {
      const node = asRecord(item);
      const id = text(node.node_id) || text(node.id);
      if (!id) {
        return null;
      }
      return {
        id,
        title: nodeTitle(id, text(node.title) || text(node.label)),
        role: nodeRoleById.get(id) || roleLabel(text(node.role)),
        agentLabel: runningAgentByNode.get(id) || agentByNode.get(id) || agentLabel(text(node.agent_profile_id), text(node.agent_id)),
        status: statusByNode.get(id) || text(node.status, "idle")
      };
    })
    .filter((item): item is CoordinationNode => Boolean(item));

  const fallbackNodes = agentRuns
    .map((run): CoordinationNode | null => {
      const diagnostics = asRecord(run.diagnostics);
      const id = text(diagnostics.node_id);
      if (!id || graphNodes.some((node) => node.id === id) || stageNodes.some((node) => node.id === id)) {
        return null;
      }
      return {
        id,
        title: nodeTitle(id),
        role: nodeRoleById.get(id) || roleLabel(text(run.role)),
        agentLabel: runningAgentByNode.get(id) || agentLabel(text(run.agent_profile_id), text(run.agent_id)),
        status: text(run.status, "running")
      };
    })
    .filter((item): item is CoordinationNode => Boolean(item));

  const allNodes =
    stageNodes.length
      ? stageNodes
      : graphNodes.length
        ? graphNodes
        : fallbackNodes;
  const currentNodeId =
    flowCurrentNodeId ||
    allNodes.find((node) => node.status === "running")?.id ||
    stringArray(runtimeState.running_nodes)[0] ||
    stringArray(runtimeState.blocked_nodes)[0] ||
    text(events[events.length - 1]?.node_id) ||
    "";
  if (!currentAgentKey && currentNodeId) {
    const currentNodeAgent = agentRuns.find((run) => {
      const diagnostics = asRecord(run.diagnostics);
      return (text(diagnostics.node_id) || text(diagnostics.stage_id) || text(run.node_id)) === currentNodeId;
    });
    currentAgentKey = text(currentNodeAgent?.agent_run_id);
  }
  const nodeIdSet = new Set(allNodes.map((node) => node.id));
  const flowEdges = flowStages.slice(0, -1).map((stage, index): CoordinationEdge => {
    const nextStage = flowStages[index + 1];
    return {
      id: `flow-${stage.nodeId}-${nextStage.nodeId}-${index}`,
      from: stage.nodeId,
      to: nextStage.nodeId,
      label: compactTaskLabel(nextStage.taskRef) || "阶段交接",
      status: "idle"
    };
  });
  const graphEdges = rawEdges
    .map((item, index): CoordinationEdge | null => {
      const edge = asRecord(item);
      const from = text(edge.from) || text(edge.source) || text(edge.from_node_id) || text(edge.source_node_id);
      const to = text(edge.to) || text(edge.target) || text(edge.to_node_id) || text(edge.target_node_id);
      if (!from || !to || (!nodeIdSet.has(from) && !nodeIdSet.has(to))) {
        return null;
      }
      return {
        id: text(edge.edge_id) || `${from}-${to}-${index}`,
        from,
        to,
        label: compactTaskLabel(text(edge.policy) || text(edge.label) || "交接"),
        status: "idle"
      };
    })
    .filter((item): item is CoordinationEdge => Boolean(item));
  const handoffEdges = handoffs
    .map((handoff, index): CoordinationEdge | null => {
      const sourceAgentRunRef = text(handoff.source_agent_run_ref);
      const targetAgentRunRef = text(handoff.target_agent_run_ref);
      const from = nodeIdByAgentRunId.get(sourceAgentRunRef) || "";
      const to = nodeIdByAgentRunId.get(targetAgentRunRef) || "";
      if (!from || !to || (!nodeIdSet.has(from) && !nodeIdSet.has(to))) {
        return null;
      }
      const key = `${from}->${to}`;
      currentHandoffKey = key;
      currentEdgeKeyCandidates.add(key);
      return {
        id: text(handoff.handoff_id) || `handoff-${from}-${to}-${index}`,
        from,
        to,
        label: compactTaskLabel(text(handoff.message_type) || text(asRecord(handoff.diagnostics).handoff_policy) || "交接"),
        status: text(handoff.ack_state) === "accepted" ? "completed" : "running"
      };
    })
    .filter((item): item is CoordinationEdge => Boolean(item));

  const baseEdges =
    graphEdges.length
      ? graphEdges
      : flowEdges.length
        ? flowEdges
        : handoffEdges;
  const edgeByKey = new Map<string, CoordinationEdge>();
  const mergedEdges = [...baseEdges, ...handoffEdges];
  for (const edge of mergedEdges) {
    const key = `${edge.from}->${edge.to}`;
    const existing = edgeByKey.get(key);
    if (!existing || edge.status === "running" || (existing.status === "idle" && edge.status === "completed")) {
      edgeByKey.set(key, edge);
    }
  }
  const edges = Array.from(edgeByKey.values()).map((edge) => {
    const key = `${edge.from}->${edge.to}`;
    const current = currentEdgeKeyCandidates.has(key)
      || (edge.from === currentNodeId || edge.to === currentNodeId);
    return {
      ...edge,
      status:
        edge.status !== "idle"
          ? edge.status
          : current
            ? "running"
            : statusByNode.get(edge.from) === "completed" && statusByNode.get(edge.to) === "completed"
              ? "completed"
              : "idle"
    };
  });

  const agents = agentRuns.map((run, index): CoordinationAgent => {
    const diagnostics = asRecord(run.diagnostics);
    const nodeId = text(diagnostics.node_id) || text(diagnostics.stage_id) || text(run.node_id);
    return {
      key: text(run.agent_run_id) || `${text(run.agent_profile_id)}-${index}`,
      label: agentLabel(text(run.agent_profile_id), text(run.agent_id)),
      role: roleLabel(text(run.role)),
      nodeTitle: nodeId ? nodeTitle(nodeId, stageByNodeId.get(nodeId)?.taskRef ? compactTaskLabel(stageByNodeId.get(nodeId)?.taskRef || "") : "") : "协调入口",
      status: text(run.status, "running")
    };
  });

  const snapshotArtifacts = snapshot?.artifacts ?? {};
  for (const [key, value] of Object.entries(snapshotArtifacts)) {
    const path = text(value);
    if (path) {
      pushArtifact(artifacts, artifactSeen, path, "artifact", key);
    }
  }

  for (const event of events) {
    if (event.event === "token") {
      const fragment = text(asRecord(event.data).content);
      if (fragment) {
        streamingContent += fragment;
      }
    }
    walk(event.data, (record) => {
      const explicitWorkspacePath = text(record.explicit_workspace_path);
      const artifactPath = text(record.artifact_path);
      const targetPath = text(record.target_path);
      const traceUrl = text(record.trace_url);
      const genericPath = text(record.path);
      const executorRef = text(record.executor_ref);

      if (explicitWorkspacePath) {
        pushArtifact(artifacts, artifactSeen, explicitWorkspacePath, executorRef || "write_file");
      }
      if (artifactPath) {
        pushArtifact(artifacts, artifactSeen, artifactPath, "artifact");
      }
      if (targetPath) {
        pushArtifact(artifacts, artifactSeen, targetPath, executorRef || "write_target");
      }
      if (traceUrl) {
        pushArtifact(artifacts, artifactSeen, traceUrl, "trace", "运行轨迹");
      }
      if (genericPath && /[\\/]|\.md$|\.json$|\.txt$|\.log$|\.html$|\.css$|\.js$/i.test(genericPath)) {
        pushArtifact(artifacts, artifactSeen, genericPath, "path");
      }

      const finalOutputs = asRecord(record.final_outputs);
      for (const [key, value] of Object.entries(finalOutputs)) {
        if (typeof value === "string") {
          pushOutput(outputs, outputSeen, key, value);
        }
      }

      const outputRefs = asArray(record.output_refs).map((item) => text(item)).filter(Boolean);
      outputRefs.forEach((ref, index) => pushArtifact(artifacts, artifactSeen, ref, "output_ref", `输出引用 ${index + 1}`));

      const resultRefs = asArray(record.result_refs).map((item) => text(item)).filter(Boolean);
      resultRefs.forEach((ref, index) => pushArtifact(artifacts, artifactSeen, ref, "result_ref", `结果引用 ${index + 1}`));

      if (typeof record.final_answer === "string") {
        pushOutput(outputs, outputSeen, "final_answer", record.final_answer);
      }
      if (typeof record.content === "string" && (text(record.answer_channel) || text(record.answer_source))) {
        pushOutput(outputs, outputSeen, text(record.answer_channel) || "answer", record.content);
      }
    });
  }

  if (streamingContent.trim()) {
    pushOutput(outputs, outputSeen, "流式内容", streamingContent);
  }

  return {
    hasSignal: Boolean(coordinationTaskRef || allNodes.length || agents.length),
    title: coordinationTaskRef ? compactTaskLabel(coordinationTaskRef) : "当前没有协调任务运行",
    currentNodeId,
    currentAgentKey,
    currentHandoffKey,
    nodes: allNodes,
    edges,
    agents,
    artifacts,
    outputs: outputs.slice(-6),
    contractRuntime: buildContractRuntime(events, allNodes, currentNodeId)
  };
}

export function hasCoordinationSignal(snapshot: OrchestrationSnapshot | null) {
  return buildModel(snapshot).hasSignal;
}

export function CoordinationRunPanel({
  snapshot
}: {
  snapshot: OrchestrationSnapshot | null;
}) {
  const model = useMemo(() => buildModel(snapshot), [snapshot]);
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [selectedEdgeId, setSelectedEdgeId] = useState("");
  const currentNode = model.nodes.find((node) => node.id === model.currentNodeId) ?? null;
  const selectedNode = model.nodes.find((node) => node.id === selectedNodeId) ?? currentNode;
  const selectedEdge = model.edges.find((edge) => edge.id === selectedEdgeId) ?? null;
  const currentAgent = model.agents.find((agent) => agent.key === model.currentAgentKey) ?? null;
  const activeLabel = currentAgent ? currentAgent.label : currentNode ? (currentNode.agentLabel || currentNode.title) : "等待分派";
  const activeStatus = currentNode ? statusLabel(currentNode.status) : "待启动";
  const runStateLabel = currentNode?.status === "failed" ? "协调异常" : currentNode ? "协调运行中" : "等待启动";
  const outputCountLabel = model.outputs.length ? `${model.outputs.length} 条输出` : "暂无输出";
  const artifactCountLabel = model.artifacts.length ? `${model.artifacts.length} 个产物` : "暂无产物";
  const contractRuntime = model.contractRuntime;
  const contractStatusLabel = contractRuntime.manifestRef
    ? contractRuntime.valid ? "Manifest 有效" : "Manifest 有问题"
    : "未接入契约";
  const displayHandoffs = selectedEdge
    ? contractRuntime.handoffs.filter((handoff) => handoff.sourceNodeId === selectedEdge.from && handoff.targetNodeId === selectedEdge.to)
    : selectedNode
      ? contractRuntime.handoffs.filter((handoff) => handoff.sourceNodeId === selectedNode.id || handoff.targetNodeId === selectedNode.id)
      : contractRuntime.handoffs;
  const activeContractNode =
    contractRuntime.nodeSummaries.find((node) => node.nodeId === selectedNode?.id)
    ?? contractRuntime.nodeSummaries.find((node) => node.nodeId === model.currentNodeId)
    ?? contractRuntime.nodeSummaries.find((node) => node.status === "blocked")
    ?? contractRuntime.nodeSummaries[0]
    ?? null;
  const contractNodeList = activeContractNode
    ? [activeContractNode, ...contractRuntime.nodeSummaries.filter((node) => node.nodeId !== activeContractNode.nodeId)].slice(0, 8)
    : contractRuntime.nodeSummaries.slice(0, 8);

  if (!model.hasSignal) {
    return (
      <div className="coordination-session-empty">
        <Network size={22} />
        <strong>当前还没有协调任务</strong>
      </div>
    );
  }

  return (
    <div className="coordination-session">
      <header className="coordination-session__head">
        <div className="coordination-session__heading">
          <span>协调监控</span>
          <h2>{model.title}</h2>
        </div>
        <div className="coordination-session__statusbar" aria-label="当前协调状态">
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
        </div>
      </header>

      <section className="coordination-topology-shell" aria-label="协调任务拓扑">
        <div className="coordination-topology-shell__head">
          <span>执行拓扑</span>
          <p className="coordination-topology-shell__hint">球点代表 Agent，发光节点表示当前正在工作</p>
        </div>
        <div className="coordination-topology-viewport">
          <CoordinationTopologyGraph
            currentHandoffKey={model.currentHandoffKey}
            currentNodeId={model.currentNodeId}
            edges={model.edges}
            emptyDescription="当前会话已经进入协调态，节点与交接关系会在后续运行事件到达后显示。"
            emptyTitle="协调任务已启动，正在等待拓扑数据"
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

      <section className="coordination-contract-board" aria-label="契约运行状态">
        <article className="coordination-output-card coordination-contract-card">
          <div className="coordination-output-card__head">
            <span><PackageCheck size={14} /> 契约运行状态</span>
            <strong>{contractStatusLabel}</strong>
          </div>
          <div className="coordination-contract-summary">
            <div>
              <span>契约清单</span>
              <strong>{contractRuntime.manifestRef || "等待编译快照"}</strong>
            </div>
            <div>
              <span>就绪</span>
              <strong>{contractRuntime.readyNodes.length}</strong>
            </div>
            <div>
              <span>阻塞</span>
              <strong>{contractRuntime.blockedNodes.length}</strong>
            </div>
            <div>
              <span>等待</span>
              <strong>{contractRuntime.waitingNodes.length}</strong>
            </div>
            <div>
              <span>完成</span>
              <strong>{contractRuntime.completedNodes.length}</strong>
            </div>
            <div>
              <span>失败</span>
              <strong>{contractRuntime.failedNodes.length}</strong>
            </div>
          </div>
          <div className="coordination-contract-node-list">
            {contractNodeList.length ? contractNodeList.map((node) => (
              <article className={`coordination-contract-node coordination-contract-node--${node.status}`} key={node.nodeId}>
                <div>
                  <strong>{node.title}</strong>
                  <span>{statusLabel(node.status)}</span>
                </div>
                <em>{node.contractRefs.length ? node.contractRefs.join(" / ") : "未绑定节点契约"}</em>
                {node.missingRequiredInputs.length ? (
                  <p>缺失输入：{node.missingRequiredInputs.join("、")}</p>
                ) : null}
              </article>
            )) : <p className="coordination-contract-empty">当前运行事件里还没有契约状态。</p>}
          </div>
          {contractRuntime.issues.length ? (
            <div className="coordination-contract-issues">
              {contractRuntime.issues.slice(0, 4).map((issue) => <span key={issue}>{issue}</span>)}
            </div>
          ) : null}
        </article>

        <article className="coordination-output-card coordination-contract-card">
          <div className="coordination-output-card__head">
            <span><GitBranch size={14} /> A2A 交接</span>
            <strong>{displayHandoffs.length ? `${displayHandoffs.length} 个交接包` : "暂无交接"}</strong>
          </div>
          <div className="coordination-handoff-list">
            {displayHandoffs.length ? displayHandoffs.map((handoff) => (
              <article className="coordination-handoff-item" key={handoff.key}>
                <div>
                  <strong>{handoff.sourceNodeId || "上游"} {"->"} {handoff.targetNodeId || "下游"}</strong>
                  <span>{handoff.messageType}</span>
                </div>
                <em>{handoff.contractRefs.length ? handoff.contractRefs.join(" / ") : "默认交接契约"}</em>
                <small>{handoff.runtimeAssemblyRef || handoff.contractManifestRef || "等待运行引用"}</small>
              </article>
            )) : (
              <p className="coordination-contract-empty">
                {activeContractNode ? `${activeContractNode.title} 还没有产生下游交接。` : "节点完成后会显示最新 A2A 交接包。"}
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
                  <span>{artifact.kind}</span>
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
