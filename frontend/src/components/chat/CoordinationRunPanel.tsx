"use client";

import {
  ArrowRight,
  CheckCircle2,
  FileText,
  GitBranch,
  MessagesSquare,
  Network,
  Radio,
  Sparkles,
  Users,
  Workflow
} from "lucide-react";
import { useMemo } from "react";

import type { OrchestrationEvent, OrchestrationSnapshot } from "@/lib/api";

type CoordinationNode = {
  id: string;
  title: string;
  role: string;
  agentLabel: string;
  status: string;
};

type CoordinationEdge = {
  id: string;
  from: string;
  to: string;
  label: string;
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

type CoordinationEventCard = {
  index: number;
  title: string;
  summary: string;
};

type CoordinationModel = {
  hasSignal: boolean;
  title: string;
  taskLabel: string;
  protocolLabel: string;
  engineLabel: string;
  currentNodeId: string;
  nodes: CoordinationNode[];
  edges: CoordinationEdge[];
  agents: CoordinationAgent[];
  artifacts: CoordinationArtifact[];
  outputs: CoordinationOutput[];
  events: CoordinationEventCard[];
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
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

function agentLabel(profileId: string, agentId = "") {
  const labels: Record<string, string> = {
    main_interactive_agent: "主 Agent",
    longform_plot_agent: "情节规划 Agent",
    longform_drafting_agent: "创作起草 Agent",
    longform_review_agent: "审查 Agent",
    longform_continuity_agent: "连贯性 Agent",
    longform_editor_agent: "编辑验收 Agent"
  };
  if (labels[profileId]) {
    return labels[profileId];
  }
  if (profileId) {
    return profileId
      .replace(/^longform_/, "")
      .replace(/_agent$/, "")
      .replace(/_/g, " ");
  }
  return agentId ? "协作 Agent" : "未指定 Agent";
}

function nodeTitle(nodeId: string, fallback = "") {
  const labels: Record<string, string> = {
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
  if (status === "completed" || status === "success") {
    return "完成";
  }
  if (status === "running") {
    return "运行中";
  }
  if (status === "failed") {
    return "失败";
  }
  return status || "待执行";
}

function statusClass(status: string) {
  if (status === "completed" || status === "success") {
    return "is-complete";
  }
  if (status === "running") {
    return "is-running";
  }
  if (status === "failed") {
    return "is-failed";
  }
  return "is-idle";
}

function compactTaskLabel(value: string) {
  const labels: Record<string, string> = {
    "coord.writing.chapter_pipeline": "写作域：长篇章节协调任务",
    "protocol.writing.chapter_pipeline": "章节交接协议",
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

function buildModel(snapshot: OrchestrationSnapshot | null): CoordinationModel {
  const events = snapshot?.events ?? [];
  const coordinationTaskRef = firstString(events, ["coordination_task_ref", "coordination_task_id"]);
  const protocolRef = firstString(events, ["communication_protocol_ref", "communication_protocol_id", "task_communication_protocol_ref"]);
  const engine = firstString(events, ["coordination_engine"]);
  const rawNodes = findArray(events, ["graph_nodes", "nodes"]);
  const rawEdges = findArray(events, ["graph_edges", "edges"]);
  const agentRuns = collectAgentRuns(events);
  const statusByNode = new Map<string, string>();
  const agentByNode = new Map<string, string>();
  const artifacts: CoordinationArtifact[] = [];
  const outputs: CoordinationOutput[] = [];
  const artifactSeen = new Set<string>();
  const outputSeen = new Set<string>();

  for (const run of agentRuns) {
    const diagnostics = asRecord(run.diagnostics);
    const nodeId = text(diagnostics.node_id);
    if (!nodeId) {
      continue;
    }
    statusByNode.set(nodeId, text(run.status, "running"));
    agentByNode.set(nodeId, agentLabel(text(run.agent_profile_id), text(run.agent_id)));
  }

  const nodes = rawNodes
    .map((item): CoordinationNode | null => {
      const node = asRecord(item);
      const id = text(node.node_id) || text(node.id);
      if (!id) {
        return null;
      }
      return {
        id,
        title: nodeTitle(id, text(node.title) || text(node.label)),
        role: roleLabel(text(node.role)),
        agentLabel: agentByNode.get(id) || agentLabel(text(node.agent_profile_id), text(node.agent_id)),
        status: statusByNode.get(id) || text(node.status, "idle")
      };
    })
    .filter((item): item is CoordinationNode => Boolean(item));

  const fallbackNodes = agentRuns
    .map((run): CoordinationNode | null => {
      const diagnostics = asRecord(run.diagnostics);
      const id = text(diagnostics.node_id);
      if (!id || nodes.some((node) => node.id === id)) {
        return null;
      }
      return {
        id,
        title: nodeTitle(id),
        role: roleLabel(text(run.role)),
        agentLabel: agentLabel(text(run.agent_profile_id), text(run.agent_id)),
        status: text(run.status, "running")
      };
    })
    .filter((item): item is CoordinationNode => Boolean(item));

  const allNodes = nodes.length ? nodes : fallbackNodes;
  const currentNodeId =
    allNodes.find((node) => node.status === "running")?.id ||
    text(events[events.length - 1]?.node_id) ||
    "";
  const nodeIdSet = new Set(allNodes.map((node) => node.id));
  const edges = rawEdges
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
        label: compactTaskLabel(text(edge.policy) || text(edge.label) || "交接")
      };
    })
    .filter((item): item is CoordinationEdge => Boolean(item));

  const agents = agentRuns.map((run, index): CoordinationAgent => {
    const diagnostics = asRecord(run.diagnostics);
    const nodeId = text(diagnostics.node_id);
    return {
      key: text(run.agent_run_id) || `${text(run.agent_profile_id)}-${index}`,
      label: agentLabel(text(run.agent_profile_id), text(run.agent_id)),
      role: roleLabel(text(run.role)),
      nodeTitle: nodeId ? nodeTitle(nodeId) : "协调入口",
      status: text(run.status, "running")
    };
  });

  const coordinationEvents = events
    .filter((event) => {
      const name = `${event.event} ${event.summary}`.toLowerCase();
      if (name.includes("coordination") || name.includes("agent_run") || name.includes("handoff")) {
        return true;
      }
      let matched = false;
      walk(event.data, (record) => {
        if (matched) {
          return;
        }
        const value = `${text(record.coordination_task_ref)} ${text(record.coordination_run_ref)} ${text(record.spawn_mode)} ${text(record.event_type)}`;
        matched = value.includes("coordination") || value.includes("agent_run_created");
      });
      return matched;
    })
    .slice(-12)
    .map((event) => ({
      index: event.index,
      title: event.summary || event.event,
      summary: event.event
    }));

  const snapshotArtifacts = snapshot?.artifacts ?? {};
  for (const [key, value] of Object.entries(snapshotArtifacts)) {
    const path = text(value);
    if (path) {
      pushArtifact(artifacts, artifactSeen, path, "artifact", key);
    }
  }

  for (const event of events) {
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

  return {
    hasSignal: Boolean(coordinationTaskRef || protocolRef || engine || allNodes.length || agents.length),
    title: coordinationTaskRef ? compactTaskLabel(coordinationTaskRef) : "当前没有协调任务运行",
    taskLabel: coordinationTaskRef ? compactTaskLabel(coordinationTaskRef) : "未触发协调任务",
    protocolLabel: protocolRef ? compactTaskLabel(protocolRef) : "未发现通信协议",
    engineLabel: engine ? compactTaskLabel(engine) : "运行中未声明",
    currentNodeId,
    nodes: allNodes,
    edges,
    agents,
    artifacts,
    outputs: outputs.slice(-6),
    events: coordinationEvents
  };
}

export function hasCoordinationSignal(snapshot: OrchestrationSnapshot | null) {
  return buildModel(snapshot).hasSignal;
}

export function CoordinationRunPanel({
  mode,
  snapshot
}: {
  mode: "flow" | "communication";
  snapshot: OrchestrationSnapshot | null;
}) {
  const model = useMemo(() => buildModel(snapshot), [snapshot]);
  const completedCount = model.nodes.filter((node) => node.status === "completed" || node.status === "success").length;
  const currentNode = model.nodes.find((node) => node.id === model.currentNodeId) ?? null;

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
        <div>
          <span>{mode === "flow" ? "协调流程" : "多 Agent 通信"}</span>
          <h2>{model.title}</h2>
        </div>
        <div className="coordination-session__metrics">
          <span><Workflow size={14} />{model.nodes.length} 个流程节点</span>
          <span><Users size={14} />{model.agents.length} 个 Agent</span>
          <span><CheckCircle2 size={14} />{completedCount} 个已完成</span>
        </div>
      </header>

      <section className="coordination-status-strip">
        <article>
          <span>当前执行</span>
          <strong>{currentNode ? currentNode.title : "等待分派"}</strong>
          <em>{currentNode ? (currentNode.agentLabel || currentNode.role) : "尚未进入执行节点"}</em>
        </article>
        <article>
          <span>成果输出</span>
          <strong>{model.artifacts.length} 项</strong>
          <em>{model.outputs.length ? `${model.outputs.length} 条结果摘要` : "等待产物写出"}</em>
        </article>
        <article>
          <span>信息流</span>
          <strong>{model.events.length} 条</strong>
          <em>显示最近协调轨迹</em>
        </article>
      </section>

      {mode === "flow" ? (
        <>
          <section className="coordination-session__contract">
            <article><span>协调任务</span><strong>{model.taskLabel}</strong></article>
            <article><span>通信协议</span><strong>{model.protocolLabel}</strong></article>
            <article><span>执行引擎</span><strong>{model.engineLabel}</strong></article>
          </section>
          <section className="coordination-flow-graph" aria-label="协调任务流程图">
            {model.nodes.map((node, index) => (
              <div className="coordination-flow-graph__step" key={node.id}>
                <article className={`coordination-flow-node ${statusClass(node.status)} ${node.id === model.currentNodeId ? "is-current" : ""}`}>
                  <div className="coordination-flow-node__icon"><GitBranch size={16} /></div>
                  <strong>{node.title}</strong>
                  <span>{node.agentLabel || node.role}</span>
                  <em>{statusLabel(node.status)}</em>
                </article>
                {index < model.nodes.length - 1 ? <ArrowRight className="coordination-flow-graph__arrow" size={18} /> : null}
              </div>
            ))}
          </section>
          <section className="coordination-event-strip">
            {model.events.length ? model.events.map((event) => (
              <article key={`${event.index}-${event.summary}`}>
                <span>#{event.index}</span>
                <strong>{event.title}</strong>
                <em>{event.summary}</em>
              </article>
            )) : <p>暂无协调事件明细。</p>}
          </section>
        </>
      ) : (
        <>
          <section className="coordination-agent-lanes">
            {model.agents.map((agent) => (
              <article className={`coordination-agent-lane ${statusClass(agent.status)}`} key={agent.key}>
                <div><Radio size={15} /><strong>{agent.label}</strong></div>
                <span>{agent.role}</span>
                <em>{agent.nodeTitle}</em>
                <small>{statusLabel(agent.status)}</small>
              </article>
            ))}
          </section>
          <section className="coordination-communication-map" aria-label="Agent 通信链路">
            {model.edges.length ? model.edges.map((edge) => (
              <article key={edge.id}>
                <span>{nodeTitle(edge.from)}</span>
                <ArrowRight size={16} />
                <span>{nodeTitle(edge.to)}</span>
                <em><MessagesSquare size={14} />{edge.label}</em>
              </article>
            )) : <p>运行时已经创建协调 Agent，但还没有记录可展示的节点交接边。</p>}
          </section>
        </>
      )}

      <section className="coordination-output-board">
        <article className="coordination-output-card">
          <div className="coordination-output-card__head">
            <span><FileText size={14} /> 输出文件</span>
            <strong>{model.artifacts.length ? `${model.artifacts.length} 项` : "暂无"}</strong>
          </div>
          <div className="coordination-output-list">
            {model.artifacts.length ? model.artifacts.slice(0, 8).map((artifact) => (
              <article key={artifact.key}>
                <strong>{artifact.label}</strong>
                <span>{artifact.kind}</span>
                <em>{artifact.path}</em>
              </article>
            )) : <p>当前还没有检测到文件产物或路径引用。</p>}
          </div>
        </article>

        <article className="coordination-output-card">
          <div className="coordination-output-card__head">
            <span><Sparkles size={14} /> 输出内容</span>
            <strong>{model.outputs.length ? `${model.outputs.length} 条` : "暂无"}</strong>
          </div>
          <div className="coordination-output-list">
            {model.outputs.length ? model.outputs.map((output) => (
              <article key={output.key}>
                <strong>{output.label}</strong>
                <pre>{output.content}</pre>
              </article>
            )) : <p>当前还没有检测到可展示的最终输出。</p>}
          </div>
        </article>
      </section>
    </div>
  );
}
