"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Download,
  FileCode2,
  GitBranch,
  Link2,
  Network,
  RefreshCw,
  RotateCcw,
  Save,
} from "lucide-react";

import { getAgentControlNetwork, getAgentControlNetworkSession } from "@/lib/api/agentNetwork";
import type {
  AgentControlNetworkPayload,
  RuntimeTopologyBranch,
  RuntimeTopologyEdge,
  RuntimeTopologyNode,
} from "@/lib/api/types";

type NodeKind = "domain" | "contract" | "physical" | "transport" | "ledger" | "memory" | "diagnostic" | string;
type SelectedType = "node" | "edge";

type NetworkNode = RuntimeTopologyNode & {
  id: string;
  title: string;
  subtitle: string;
  kind: NodeKind;
  branch: string;
  file: string;
  timeScope: string;
  domain: string;
  summary: string;
  x: number;
  y: number;
};

type NetworkEdge = RuntimeTopologyEdge & {
  id: string;
  source: string;
  target: string;
  label: string;
  edge_kind: string;
  status: string;
  failureRoute: string;
  forbiddenRoute: string;
};

type AnnotationStore = {
  notes: Record<string, string>;
};

const STORAGE_KEY = "agent-control-network-annotations";

const DEFAULT_BRANCHES: RuntimeTopologyBranch[] = [
  { id: "all", label: "全部网络" },
  { id: "entry", label: "入口" },
  { id: "control", label: "控制" },
  { id: "context", label: "上下文" },
  { id: "action", label: "动作" },
  { id: "transport", label: "传输" },
  { id: "ledger", label: "账本" },
  { id: "memory", label: "热账本" },
  { id: "diagnostic", label: "诊断" },
];

const KIND_LABELS: Record<string, string> = {
  contract: "契约",
  diagnostic: "诊断",
  domain: "控制域",
  ledger: "账本",
  memory: "热账本",
  physical: "物理",
  transport: "传输",
};

const STATUS_LABELS: Record<string, string> = {
  connected: "已接通",
  planned: "待标准化",
  weak: "弱连接",
};

function readAnnotations(): AnnotationStore {
  if (typeof window === "undefined") return { notes: {} };
  try {
    const parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "");
    const notes = parsed?.notes && typeof parsed.notes === "object" ? parsed.notes : {};
    return { notes };
  } catch {
    return { notes: {} };
  }
}

function writeAnnotations(store: AnnotationStore) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(store, null, 2));
}

function normalizedNode(raw: RuntimeTopologyNode, index: number): NetworkNode {
  const fallbackX = 12 + (index % 6) * 14;
  const fallbackY = 18 + Math.floor(index / 6) * 18;
  return {
    ...raw,
    id: String(raw.id || `node-${index}`),
    title: String(raw.title || raw.id || `Node ${index + 1}`),
    subtitle: String(raw.subtitle || raw.control_layer || ""),
    kind: String(raw.kind || "domain"),
    branch: String(raw.branch || "control"),
    file: String(raw.file || raw.module_path || ""),
    timeScope: String(raw.timeScope || raw.time_scope || ""),
    domain: String(raw.domain || raw.agent_domain || ""),
    summary: String(raw.summary || ""),
    x: numberInRange(raw.x, fallbackX, 4, 96),
    y: numberInRange(raw.y, fallbackY, 4, 96),
  };
}

function normalizedEdge(raw: RuntimeTopologyEdge, index: number): NetworkEdge {
  return {
    ...raw,
    id: String(raw.id || `edge-${index}`),
    source: String(raw.source || ""),
    target: String(raw.target || ""),
    label: String(raw.label || raw.signal || `Edge ${index + 1}`),
    edge_kind: String(raw.edge_kind || "runtime_connection"),
    status: String(raw.status || "connected"),
    failureRoute: String(raw.failureRoute || raw.failure_route || ""),
    forbiddenRoute: String(raw.forbiddenRoute || raw.forbidden_route || ""),
  };
}

function numberInRange(value: unknown, fallback: number, min: number, max: number) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return Math.min(max, Math.max(min, fallback));
  return Math.min(max, Math.max(min, numeric));
}

function nodeClassName(kind: NodeKind, selected: boolean) {
  return `agent-network-node agent-network-node--${kind}${selected ? " agent-network-node--selected" : ""}`;
}

function textValue(value: unknown) {
  if (value === undefined || value === null) return "";
  if (Array.isArray(value)) return value.map((item) => String(item)).filter(Boolean).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function detailRows(item: Record<string, unknown>, keys: Array<[string, string]>) {
  return keys
    .map(([label, key]) => ({ label, value: textValue(item[key]) }))
    .filter((row) => row.value.trim().length > 0);
}

function refRows(item: Record<string, unknown>, keys: Array<[string, string]>) {
  return keys.map(([label, key]) => {
    const value = textValue(item[key]);
    return { label, value: value.trim() ? value : "unscoped" };
  });
}

function prefixCoverageLabel(cacheDiagnostics: Record<string, unknown>) {
  const covered = cacheDiagnostics.current_prefix_covered;
  if (covered === true) return "covered";
  if (covered === false) return "not covered";
  return textValue(cacheDiagnostics.verdict) || "unscoped";
}

function annotationKey(type: SelectedType, id: string) {
  return `${type}:${id}`;
}

export default function AgentNetworkPage() {
  const [payload, setPayload] = useState<AgentControlNetworkPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [branch, setBranch] = useState("all");
  const [selectedId, setSelectedId] = useState("");
  const [selectedType, setSelectedType] = useState<SelectedType>("node");
  const [annotations, setAnnotations] = useState<AnnotationStore>({ notes: {} });
  const [sessionInput, setSessionInput] = useState("");

  async function loadNetwork(nextSessionId = sessionInput) {
    const normalizedSessionId = nextSessionId.trim();
    setLoading(true);
    setError("");
    try {
      const nextPayload = normalizedSessionId
        ? await getAgentControlNetworkSession(normalizedSessionId)
        : await getAgentControlNetwork();
      setPayload(nextPayload);
      setSessionInput(normalizedSessionId);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : String(loadError));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setAnnotations(readAnnotations());
    const params = new URLSearchParams(window.location.search);
    const sessionId = params.get("session_id") || params.get("session") || "";
    setSessionInput(sessionId);
    void loadNetwork(sessionId);
  }, []);

  const nodes = useMemo(
    () => (payload?.nodes || []).map((node, index) => normalizedNode(node, index)),
    [payload],
  );
  const edges = useMemo(
    () => (payload?.edges || []).map((edge, index) => normalizedEdge(edge, index)),
    [payload],
  );
  const branches = payload?.branches?.length ? payload.branches : DEFAULT_BRANCHES;
  const nodeById = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);

  useEffect(() => {
    if (!nodes.length) return;
    if (selectedType === "node" && nodeById.has(selectedId)) return;
    if (selectedType === "edge" && edges.some((edge) => edge.id === selectedId)) return;
    setSelectedType("node");
    setSelectedId(nodes[0].id);
  }, [edges, nodeById, nodes, selectedId, selectedType]);

  const visibleNodeIds = useMemo(() => {
    if (branch === "all") return new Set(nodes.map((node) => node.id));
    const direct = nodes.filter((node) => node.branch === branch).map((node) => node.id);
    const expanded = new Set(direct);
    edges.forEach((edge) => {
      if (expanded.has(edge.source)) expanded.add(edge.target);
      if (expanded.has(edge.target)) expanded.add(edge.source);
    });
    return expanded;
  }, [branch, edges, nodes]);

  const visibleNodes = nodes.filter((node) => visibleNodeIds.has(node.id));
  const visibleEdges = edges.filter((edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target));
  const selectedNode = selectedType === "node" ? nodeById.get(selectedId) ?? visibleNodes[0] ?? nodes[0] : null;
  const selectedEdge = selectedType === "edge" ? edges.find((edge) => edge.id === selectedId) ?? visibleEdges[0] ?? edges[0] : null;
  const selectedKey = annotationKey(selectedType, selectedId);
  const selectedNote = annotations.notes[selectedKey] || "";
  const runtimeEvidence = payload?.runtime_evidence || {};
  const cacheDiagnostics = runtimeEvidence.cache_diagnostics || {};
  const turnMemory = runtimeEvidence.turn_memory || {};
  const contextRecoveryPackage = runtimeEvidence.context_recovery_package || {};

  function selectNode(nodeId: string) {
    setSelectedType("node");
    setSelectedId(nodeId);
  }

  function selectEdge(edgeId: string) {
    setSelectedType("edge");
    setSelectedId(edgeId);
  }

  function updateSelectedNote(value: string) {
    const next = {
      notes: {
        ...annotations.notes,
        [selectedKey]: value,
      },
    };
    if (!value.trim()) {
      delete next.notes[selectedKey];
    }
    setAnnotations(next);
    writeAnnotations(next);
  }

  function resetAnnotations() {
    const next = { notes: {} };
    setAnnotations(next);
    writeAnnotations(next);
  }

  function exportGraph() {
    const exported = {
      generated_at: new Date().toISOString(),
      payload,
      annotations,
    };
    const blob = new Blob([JSON.stringify(exported, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "agent-runtime-network.json";
    link.click();
    URL.revokeObjectURL(url);
  }

  function submitSession(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void loadNetwork(sessionInput);
  }

  const edgeRows = selectedEdge
    ? detailRows(selectedEdge as Record<string, unknown>, [
      ["edge kind", "edge_kind"],
      ["signal", "signal"],
      ["control signal", "control_signal"],
      ["connection contract", "connection_contract_ref"],
      ["physical lane", "physical_lane"],
      ["producer", "producer_ref"],
      ["consumer", "consumer_ref"],
      ["payload identity", "payload_identity"],
      ["payload schema", "payload_schema"],
      ["authority", "authority"],
      ["lifecycle", "lifecycle"],
      ["cache expectation", "cache_expectation"],
      ["read policy", "state_read_policy"],
      ["write policy", "state_write_policy"],
      ["failure route", "failureRoute"],
      ["terminal behavior", "terminal_behavior"],
      ["forbidden route", "forbiddenRoute"],
      ["diagnostics key", "diagnostics_key"],
    ])
    : [];
  const nodeRows = selectedNode
    ? detailRows(selectedNode as Record<string, unknown>, [
      ["domain", "domain"],
      ["time scope", "timeScope"],
      ["branch", "branch"],
      ["role", "agent_role"],
      ["control layer", "control_layer"],
      ["authority", "authority"],
      ["owned signals", "owned_signals"],
      ["read policy", "state_read_policy"],
      ["write policy", "state_write_policy"],
      ["physical lanes", "physical_lane_policy"],
      ["file", "file"],
    ])
    : [];
  const cacheRefRows = refRows(cacheDiagnostics, [
    ["contract nodes", "current_context_contract_node_refs"],
    ["contract edges", "current_context_contract_edge_refs"],
    ["connection refs", "current_connection_contract_refs"],
    ["agent domains", "current_agent_domains"],
    ["cache spine", "current_cache_spine_hash"],
    ["transport hash", "current_transport_contract_hash"],
    ["first missing", "first_missing_expected_prefix_identity"],
  ]);

  return (
    <main className="agent-network-page">
      <header className="agent-network-header">
        <div>
          <span>{payload?.summary?.runtime_authority || "SingleAgentRuntimeHost"}</span>
          <h1>Agent 控制网络图谱</h1>
        </div>
        <nav aria-label="图谱操作">
          <button onClick={() => void loadNetwork()} type="button">
            <RefreshCw size={16} />
            刷新
          </button>
          <button onClick={exportGraph} type="button">
            <Download size={16} />
            导出
          </button>
          <button onClick={resetAnnotations} type="button">
            <RotateCcw size={16} />
            清空注释
          </button>
        </nav>
      </header>

      <section className="agent-network-status-strip" aria-label="运行证据">
        <div>
          <CheckCircle2 size={15} />
          <span>authority</span>
          <strong>{payload?.summary?.runtime_authority || "SingleAgentRuntimeHost"}</strong>
        </div>
        <div>
          <Network size={15} />
          <span>topology</span>
          <strong>{nodes.length} / {edges.length}</strong>
        </div>
        <div>
          <Activity size={15} />
          <span>prefix</span>
          <strong>{prefixCoverageLabel(cacheDiagnostics)}</strong>
        </div>
        <div>
          <FileCode2 size={15} />
          <span>turns</span>
          <strong>{textValue(turnMemory.turn_count ?? "unscoped")}</strong>
        </div>
      </section>

      {error ? (
        <section className="agent-network-error">
          <AlertTriangle size={16} />
          <span>{error}</span>
        </section>
      ) : null}

      <section className="agent-network-workbench">
        <aside className="agent-network-rail" aria-label="网络分支">
          <form className="agent-network-session-form" onSubmit={submitSession}>
            <label>
              <span>session id</span>
              <input
                onChange={(event) => setSessionInput(event.target.value)}
                placeholder="留空读取设计态网络"
                value={sessionInput}
              />
            </label>
            <button disabled={loading} type="submit">
              <RefreshCw size={15} />
              读取
            </button>
          </form>

          <div className="agent-network-panel-head">
            <Network size={17} />
            <div>
              <strong>网络分支</strong>
              <span>{visibleNodes.length} 个节点 / {visibleEdges.length} 条线</span>
            </div>
          </div>
          <div className="agent-network-branch-list">
            {branches.map((item) => (
              <button
                className={branch === item.id ? "agent-network-branch agent-network-branch--active" : "agent-network-branch"}
                key={item.id}
                onClick={() => setBranch(item.id)}
                type="button"
              >
                <GitBranch size={15} />
                <span>{item.label}</span>
              </button>
            ))}
          </div>

          <div className="agent-network-edge-list">
            <div className="agent-network-panel-head agent-network-panel-head--compact">
              <Link2 size={15} />
              <strong>连线</strong>
            </div>
            {visibleEdges.map((edge) => (
              <button
                className={selectedType === "edge" && selectedId === edge.id ? "agent-network-edge-row agent-network-edge-row--active" : "agent-network-edge-row"}
                key={edge.id}
                onClick={() => selectEdge(edge.id)}
                type="button"
              >
                <span>{edge.label}</span>
                <small>{edge.edge_kind} · {nodeById.get(edge.source)?.title} {"->"} {nodeById.get(edge.target)?.title}</small>
              </button>
            ))}
          </div>
        </aside>

        <section className="agent-network-canvas" aria-label="Agent 控制网络画布">
          <div className="agent-network-map">
            <svg aria-hidden className="agent-network-lines" preserveAspectRatio="none" viewBox="0 0 100 100">
              <defs>
                <marker id="agent-network-arrow" markerHeight="5" markerWidth="5" orient="auto" refX="4" refY="2.5">
                  <path d="M0,0 L5,2.5 L0,5 Z" />
                </marker>
              </defs>
              {visibleEdges.map((edge) => {
                const source = nodeById.get(edge.source);
                const target = nodeById.get(edge.target);
                if (!source || !target) return null;
                return (
                  <line
                    className={`agent-network-line agent-network-line--${edge.status}`}
                    key={edge.id}
                    markerEnd="url(#agent-network-arrow)"
                    x1={source.x}
                    x2={target.x}
                    y1={source.y}
                    y2={target.y}
                  />
                );
              })}
            </svg>
            {loading && !nodes.length ? (
              <div className="agent-network-loading">读取 runtime topology projection...</div>
            ) : null}
            {visibleNodes.map((node) => (
              <button
                aria-label={`${node.title} ${node.domain}`}
                className={nodeClassName(node.kind, selectedType === "node" && selectedId === node.id)}
                key={node.id}
                onClick={() => selectNode(node.id)}
                style={{ left: `${node.x}%`, top: `${node.y}%` }}
                title={node.title}
                type="button"
              >
                <span>{KIND_LABELS[node.kind] || node.kind}</span>
                <strong>{node.title}</strong>
                <small>{node.timeScope}</small>
              </button>
            ))}
          </div>
        </section>

        <aside className="agent-network-inspector" aria-label="检查器">
          <div className="agent-network-panel-head">
            {selectedEdge ? <Link2 size={17} /> : <FileCode2 size={17} />}
            <div>
              <strong>{selectedEdge ? "连线检查" : "节点检查"}</strong>
              <span>{selectedEdge ? STATUS_LABELS[selectedEdge.status] || selectedEdge.status : selectedNode?.domain}</span>
            </div>
          </div>

          {selectedEdge ? (
            <div className="agent-network-detail">
              <h2>{selectedEdge.label}</h2>
              <dl>
                <div><dt>source</dt><dd>{nodeById.get(selectedEdge.source)?.title}</dd></div>
                <div><dt>target</dt><dd>{nodeById.get(selectedEdge.target)?.title}</dd></div>
                {edgeRows.map((row) => (
                  <div key={row.label}><dt>{row.label}</dt><dd>{row.value}</dd></div>
                ))}
              </dl>
            </div>
          ) : selectedNode ? (
            <div className="agent-network-detail">
              <h2>{selectedNode.title}</h2>
              <p>{selectedNode.summary}</p>
              <dl>
                {nodeRows.map((row) => (
                  <div key={row.label}><dt>{row.label}</dt><dd>{row.value}</dd></div>
                ))}
              </dl>
            </div>
          ) : null}

          <div className="agent-network-runtime-grid">
            <div>
              <span>cache status</span>
              <strong>{textValue(cacheDiagnostics.verdict || cacheDiagnostics.latest_status || "unscoped")}</strong>
            </div>
            <div>
              <span>under-read</span>
              <strong>{textValue(cacheDiagnostics.latest_under_read_tokens ?? "unscoped")}</strong>
            </div>
            <div>
              <span>latest commit</span>
              <strong>{textValue(turnMemory.latest_commit_state || "unscoped")}</strong>
            </div>
            <div>
              <span>recovery package</span>
              <strong>{textValue(contextRecoveryPackage.fresh ?? contextRecoveryPackage.reason ?? "unscoped")}</strong>
            </div>
          </div>

          <div className="agent-network-contract-refs">
            <div className="agent-network-panel-head agent-network-panel-head--compact">
              <Link2 size={15} />
              <strong>缓存连接证据</strong>
            </div>
            <dl>
              {cacheRefRows.map((row) => (
                <div key={row.label}>
                  <dt>{row.label}</dt>
                  <dd>{row.value}</dd>
                </div>
              ))}
            </dl>
          </div>

          <label className="agent-network-note-box">
            <span>本地注释</span>
            <textarea
              onChange={(event) => updateSelectedNote(event.target.value)}
              placeholder="只保存当前浏览器注释，不覆盖后端 core graph。"
              value={selectedNote}
            />
          </label>

          <p className="agent-network-local-note">
            <Save size={14} />
            注释层只附着在节点或连线上，不参与 authority、status、cache verdict 或 recovery 裁决。
          </p>
        </aside>
      </section>
    </main>
  );
}
