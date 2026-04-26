"use client";

import { useEffect, useMemo, useState } from "react";
import { Bot, Braces, Cable, CheckCircle2, CircleOff, GitBranch, Loader2, RadioTower, Route, Save, ShieldCheck } from "lucide-react";

import {
  getAgentSystemCatalog,
  setAgentEnabled,
  updateAgentProtocolLink,
  type AgentProtocolLink,
  type AgentSystemAgent,
  type AgentSystemCatalog
} from "@/lib/api";

type LinkDraft = Pick<AgentProtocolLink, "input_contract" | "output_contract" | "handoff_policy">;
type AgentManagementMode = "topology" | "activation" | "protocol" | "handoff";

const EMPTY_AGENTS: AgentSystemAgent[] = [];
const EMPTY_LINKS: AgentProtocolLink[] = [];
const MAIN_AGENT_ID = "agent:main:conversation";

const TOPOLOGY_NODE_LAYOUT: Record<string, { x: number; y: number; size: "core" | "large" | "medium" }> = {
  [MAIN_AGENT_ID]: { x: 50, y: 50, size: "core" },
  "agent:local:worker": { x: 22, y: 28, size: "large" },
  "agent:knowledge:retrieval": { x: 78, y: 26, size: "large" },
  "agent:document:pdf": { x: 24, y: 76, size: "medium" },
  "agent:data:structured": { x: 76, y: 74, size: "medium" }
};

const AGENT_ID_LABELS: Record<string, string> = {
  [MAIN_AGENT_ID]: "主会话",
  "agent:local:worker": "执行智能体",
  "agent:knowledge:retrieval": "检索智能体",
  "agent:document:pdf": "文档智能体",
  "agent:data:structured": "结构化数据智能体"
};

const KIND_LABELS: Record<string, string> = {
  execution: "执行型",
  retrieval: "检索型",
  document: "文档型",
  data: "数据型"
};

const ROUTE_LABELS: Record<string, string> = {
  worker: "任务执行",
  retrieval: "证据检索",
  pdf: "文档解析",
  structured_data: "结构化分析"
};

const MODE_LABELS: Record<string, string> = {
  "text/plain": "文本",
  "application/json": "JSON",
  "text/markdown": "Markdown",
  "application/pdf": "PDF",
  "text/csv": "CSV"
};

const CHANNEL_LABELS: Record<string, string> = {
  "task.submitted": "任务提交",
  "task.completed": "任务完成",
  "task.failed": "任务失败",
  "worker.requested": "请求子智能体",
  "worker.evidence": "返回证据",
  "worker.artifacts": "返回产物",
  "worker.completed": "处理完成",
  "artifact.detected": "发现产物",
  "candidate.selected": "选择候选"
};

const TAG_LABELS: Record<string, string> = {
  worker: "执行",
  implementation: "实现",
  verification: "验证",
  rag: "RAG",
  retrieval: "检索",
  knowledge: "知识",
  pdf: "PDF",
  document: "文档",
  page: "页码",
  table: "表格",
  dataset: "数据集",
  analytics: "分析"
};

const AGENT_MANAGEMENT_MODES: Array<{
  id: AgentManagementMode;
  label: string;
  title: string;
  description: string;
  icon: "radio" | "shield" | "branch" | "route";
}> = [
  {
    id: "topology",
    label: "指挥拓扑",
    title: "看清主会话如何调度不同子智能体",
    description: "用一张关系图看主会话、执行、检索、文档与结构化数据智能体的协作边界。",
    icon: "radio"
  },
  {
    id: "activation",
    label: "编队启停",
    title: "控制哪些智能体可以参与运行",
    description: "管理智能体开启、停用与能力声明，适合做降级、隔离和问题复现。",
    icon: "shield"
  },
  {
    id: "protocol",
    label: "通信契约",
    title: "编辑智能体之间的输入输出协议",
    description: "显式维护 A2A-compatible 的输入契约、输出契约和移交策略。",
    icon: "branch"
  },
  {
    id: "handoff",
    label: "移交流程",
    title: "预览跨智能体的运行链路",
    description: "按执行顺序阅读启用协议，检查每一步交给谁、交什么、回什么。",
    icon: "route"
  }
];

function agentTone(agent: AgentSystemAgent) {
  if (!agent.enabled) return "muted";
  if (agent.kind === "retrieval") return "aqua";
  if (agent.kind === "document") return "gold";
  if (agent.kind === "data") return "green";
  return "steel";
}

function shortAgentName(agentId: string) {
  if (AGENT_ID_LABELS[agentId]) return AGENT_ID_LABELS[agentId];
  return agentId.replace("agent:", "").split(":").join(" / ");
}

function kindLabel(kind: string) {
  return KIND_LABELS[kind] ?? kind;
}

function routeLabel(route: string) {
  return ROUTE_LABELS[route] ?? route;
}

function formatModes(modes: string[]) {
  return modes.map((mode) => MODE_LABELS[mode] ?? mode).join(" / ");
}

function formatChannels(channels: string[]) {
  return channels.map((channel) => CHANNEL_LABELS[channel] ?? channel).join(" / ");
}

function tagLabel(tag: string) {
  return TAG_LABELS[tag] ?? tag;
}

function agentLayout(agentId: string, index: number) {
  return TOPOLOGY_NODE_LAYOUT[agentId] ?? { x: 22 + (index % 3) * 28, y: 24 + Math.floor(index / 3) * 26, size: "medium" as const };
}

function emptyDraft(link: AgentProtocolLink | null): LinkDraft {
  return {
    input_contract: link?.input_contract ?? "",
    output_contract: link?.output_contract ?? "",
    handoff_policy: link?.handoff_policy ?? ""
  };
}

function modeIcon(icon: (typeof AGENT_MANAGEMENT_MODES)[number]["icon"], size = 16) {
  if (icon === "shield") return <ShieldCheck size={size} />;
  if (icon === "branch") return <GitBranch size={size} />;
  if (icon === "route") return <Route size={size} />;
  return <RadioTower size={size} />;
}

export function EvidenceView() {
  const [catalog, setCatalog] = useState<AgentSystemCatalog | null>(null);
  const [selectedAgentId, setSelectedAgentId] = useState("agent:knowledge:retrieval");
  const [selectedLinkId, setSelectedLinkId] = useState("main-to-retrieval");
  const [activeMode, setActiveMode] = useState<AgentManagementMode>("topology");
  const [draft, setDraft] = useState<LinkDraft>(emptyDraft(null));
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError("");
      try {
        const payload = await getAgentSystemCatalog();
        if (cancelled) return;
        setCatalog(payload);
        setSelectedAgentId((current) => payload.agents.some((agent) => agent.agent_id === current) ? current : payload.agents[0]?.agent_id ?? "");
        const firstLink = payload.protocol_links.find((link) => link.link_id === "main-to-retrieval") ?? payload.protocol_links[0] ?? null;
        setSelectedLinkId(firstLink?.link_id ?? "");
        setDraft(emptyDraft(firstLink));
      } catch (exc) {
        if (!cancelled) setError(exc instanceof Error ? exc.message : "加载智能体系统失败");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const agents = useMemo(() => catalog?.agents ?? EMPTY_AGENTS, [catalog]);
  const links = useMemo(() => catalog?.protocol_links ?? EMPTY_LINKS, [catalog]);
  const selectedAgent = agents.find((agent) => agent.agent_id === selectedAgentId) ?? agents[0] ?? null;
  const selectedLink = links.find((link) => link.link_id === selectedLinkId) ?? links[0] ?? null;
  const agentById = useMemo(() => new Map(agents.map((agent) => [agent.agent_id, agent])), [agents]);
  const activeModeMeta = AGENT_MANAGEMENT_MODES.find((mode) => mode.id === activeMode) ?? AGENT_MANAGEMENT_MODES[0];
  const isAgentEnabled = (agentId: string) => agentId === MAIN_AGENT_ID || Boolean(agentById.get(agentId)?.enabled);
  const isLinkOperational = (link: AgentProtocolLink) => Boolean(link.enabled && isAgentEnabled(link.from_agent) && isAgentEnabled(link.to_agent));
  const linkStatusLabel = (link: AgentProtocolLink) => {
    if (!link.enabled) return "协议停用";
    if (!isAgentEnabled(link.from_agent) || !isAgentEnabled(link.to_agent)) return "端点停用";
    return "运行可用";
  };
  const activeLinks = links.filter((link) => isLinkOperational(link));
  const relatedLinks = selectedAgent
    ? links.filter((link) => link.from_agent === selectedAgent.agent_id || link.to_agent === selectedAgent.agent_id)
    : [];
  const selectedLinkFrom = selectedLink ? agentById.get(selectedLink.from_agent)?.name ?? "主会话" : "";
  const selectedLinkTo = selectedLink ? agentById.get(selectedLink.to_agent)?.name ?? shortAgentName(selectedLink.to_agent) : "";
  const enabledLinks = links.filter((link) => isLinkOperational(link)).length;
  const enabledAgents = agents.filter((agent) => agent.enabled).length;

  useEffect(() => {
    setDraft(emptyDraft(selectedLink));
  }, [selectedLink]);

  async function toggleAgent(agent: AgentSystemAgent) {
    setSaving(agent.agent_id);
    setNotice("");
    setError("");
    try {
      const payload = await setAgentEnabled(agent.agent_id, !agent.enabled);
      setCatalog(payload);
      setNotice(`${agent.name} 已${!agent.enabled ? "开启" : "停用"}。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "更新智能体状态失败");
    } finally {
      setSaving("");
    }
  }

  async function toggleLink(link: AgentProtocolLink) {
    setSaving(link.link_id);
    setNotice("");
    setError("");
    try {
      const payload = await updateAgentProtocolLink(link.link_id, { enabled: !link.enabled });
      setCatalog(payload);
      setNotice(`${link.label} 协议已${!link.enabled ? "开启" : "停用"}。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "更新通信协议失败");
    } finally {
      setSaving("");
    }
  }

  async function saveSelectedLink() {
    if (!selectedLink) return;
    setSaving(selectedLink.link_id);
    setNotice("");
    setError("");
    try {
      const payload = await updateAgentProtocolLink(selectedLink.link_id, draft);
      setCatalog(payload);
      setNotice(`${selectedLink.label} 的输入输出契约已保存。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存协议契约失败");
    } finally {
      setSaving("");
    }
  }

  return (
    <div className="workspace-view agent-system-console">
      <header className="workspace-view__header">
        <div>
          <p className="workspace-view__eyebrow">智能体控制面</p>
          <h2 className="workspace-view__title">智能体系统</h2>
        </div>
        <div className="workspace-view__actions">
          <div className="tag-chip">{catalog?.protocol_version ?? "a2a-compatible.v1"}</div>
        </div>
      </header>

      {loading ? (
        <div className="workspace-alert">
          <Loader2 size={16} className="spin" />
          正在读取智能体注册表与通信协议配置...
        </div>
      ) : null}
      {error ? <div className="workspace-alert workspace-alert--danger">{error}</div> : null}
      {notice ? <div className="workspace-alert">{notice}</div> : null}

      <section className="agent-system-hero">
        <div className="agent-system-hero__copy">
          <span>控制面 / {activeModeMeta.label}</span>
          <strong>{activeModeMeta.title}</strong>
          <p>
            {activeModeMeta.description}
          </p>
        </div>
        <div className="agent-system-hero__stats">
          <article>
            <b>{enabledAgents}/{agents.length || 0}</b>
            <span>智能体开启</span>
          </article>
          <article>
            <b>{enabledLinks}/{links.length || 0}</b>
            <span>协议连线</span>
          </article>
          <article>
            <b>{agents.reduce((total, agent) => total + agent.skills.length, 0)}</b>
            <span>能力声明</span>
          </article>
        </div>
      </section>

      <nav className="agent-mode-switcher" aria-label="智能体管理模式">
        {AGENT_MANAGEMENT_MODES.map((mode) => (
          <button
            className={`agent-mode-card ${activeMode === mode.id ? "agent-mode-card--active" : ""}`}
            key={mode.id}
            onClick={() => setActiveMode(mode.id)}
            type="button"
          >
            {modeIcon(mode.icon)}
            <span>{mode.label}</span>
            <strong>{mode.title}</strong>
            <em>{mode.description}</em>
          </button>
        ))}
      </nav>

      {activeMode === "topology" ? <section className="agent-system-map workspace-section">
        <div className="workspace-section__head">
          <RadioTower size={18} />
          <h3>子智能体拓扑</h3>
        </div>
        <div className="agent-system-map__canvas">
          <svg aria-hidden className="agent-system-map__links" preserveAspectRatio="none" viewBox="0 0 100 100">
            {links.map((link) => {
              const fromIndex = Math.max(0, agents.findIndex((agent) => agent.agent_id === link.from_agent));
              const toIndex = Math.max(0, agents.findIndex((agent) => agent.agent_id === link.to_agent));
              const from = agentLayout(link.from_agent, fromIndex);
              const to = agentLayout(link.to_agent, toIndex);
              const midY = (from.y + to.y) / 2;
              return (
                <path
                  className={[
                    "agent-system-map__link",
                    isLinkOperational(link) ? "" : "agent-system-map__link--disabled",
                    selectedLinkId === link.link_id ? "agent-system-map__link--selected" : ""
                  ].filter(Boolean).join(" ")}
                  d={`M ${from.x} ${from.y} C ${from.x} ${midY}, ${to.x} ${midY}, ${to.x} ${to.y}`}
                  key={link.link_id}
                />
              );
            })}
          </svg>
          <button
            className="agent-node agent-node--main agent-node--orb agent-node--core"
            style={{ left: `${TOPOLOGY_NODE_LAYOUT[MAIN_AGENT_ID].x}%`, top: `${TOPOLOGY_NODE_LAYOUT[MAIN_AGENT_ID].y}%` }}
            type="button"
          >
            <Bot size={18} />
            <span>主会话</span>
            <strong>主会话智能体</strong>
            <em>调度 / 收束 / 用户响应</em>
          </button>
          <div className="agent-node-orbit" aria-label="智能体节点">
            {agents.map((agent, index) => {
              const layout = agentLayout(agent.agent_id, index);
              const linkCount = links.filter((link) => link.from_agent === agent.agent_id || link.to_agent === agent.agent_id).length;
              return (
              <button
                className={`agent-node agent-node--orb agent-node--${layout.size} agent-node--${agentTone(agent)} ${selectedAgent?.agent_id === agent.agent_id ? "agent-node--selected" : ""}`}
                key={agent.agent_id}
                onClick={() => setSelectedAgentId(agent.agent_id)}
                style={{ left: `${layout.x}%`, top: `${layout.y}%` }}
                type="button"
              >
                {agent.enabled ? <CheckCircle2 size={16} /> : <CircleOff size={16} />}
                <span>{kindLabel(agent.kind)}</span>
                <strong>{agent.name}</strong>
                <em>{agent.worker_route ? routeLabel(agent.worker_route) : shortAgentName(agent.agent_id)}</em>
                <small>{agent.enabled ? `${linkCount} 条关联通信` : "智能体已停用"}</small>
              </button>
              );
            })}
          </div>
        </div>
        <div className="agent-topology-strip">
          {links.map((link) => {
            const from = agentById.get(link.from_agent)?.name ?? "主会话";
            const to = agentById.get(link.to_agent)?.name ?? shortAgentName(link.to_agent);
            return (
              <button
                className={[
                  "agent-topology-link",
                  selectedLinkId === link.link_id ? "agent-topology-link--active" : "",
                  isLinkOperational(link) ? "" : "agent-topology-link--blocked"
                ].filter(Boolean).join(" ")}
                key={link.link_id}
                onClick={() => setSelectedLinkId(link.link_id)}
                type="button"
              >
                <span>{linkStatusLabel(link)}</span>
                <strong>{from} → {to}</strong>
                <em>{link.label}</em>
              </button>
            );
          })}
        </div>
      </section> : null}

      {activeMode === "activation" ? <div className="agent-system-grid">
        <section className="workspace-section agent-roster">
          <div className="workspace-section__head">
            <ShieldCheck size={18} />
            <h3>智能体开关</h3>
          </div>
          <div className="agent-roster__list">
            {agents.map((agent) => (
              <article className={`agent-card agent-card--${agentTone(agent)}`} key={agent.agent_id}>
                <div>
                  <span>{shortAgentName(agent.agent_id)}</span>
                  <strong>{agent.name}</strong>
                  <p>{agent.description}</p>
                </div>
                <button
                  className={agent.enabled ? "agent-switch agent-switch--on" : "agent-switch"}
                  disabled={saving === agent.agent_id}
                  onClick={() => void toggleAgent(agent)}
                  type="button"
                >
                  {saving === agent.agent_id ? "保存中" : agent.enabled ? "开启" : "停用"}
                </button>
              </article>
            ))}
          </div>
        </section>

        <section className="workspace-section agent-detail">
          <div className="workspace-section__head">
            <Braces size={18} />
            <h3>能力卡片</h3>
          </div>
          {selectedAgent ? (
            <div className="agent-detail__body">
              <span>{selectedAgent.agent_id}</span>
              <h3>{selectedAgent.name}</h3>
              <p>{selectedAgent.description}</p>
              <div className="agent-detail__matrix">
                <small>输入格式：{formatModes(selectedAgent.default_input_modes)}</small>
                <small>输出格式：{formatModes(selectedAgent.default_output_modes)}</small>
                <small>流式返回：{selectedAgent.supports_streaming ? "支持" : "不支持"}</small>
                <small>长任务：{selectedAgent.supports_long_task ? "支持" : "普通任务"}</small>
              </div>
              <div className="workspace-chip-row">
                {selectedAgent.skills.flatMap((skill) => skill.tags).slice(0, 8).map((tag) => (
                  <span className="workspace-mini-chip" key={tag}>{tagLabel(tag)}</span>
                ))}
              </div>
              <div className="agent-related-links">
                <strong>关联通信</strong>
                {relatedLinks.length ? relatedLinks.map((link) => (
                  <button key={link.link_id} onClick={() => {
                    setSelectedLinkId(link.link_id);
                    setActiveMode("protocol");
                  }} type="button">
                    <span>{linkStatusLabel(link)}</span>
                    <em>{link.label}</em>
                  </button>
                )) : <small>当前智能体暂无协议连线。</small>}
              </div>
            </div>
          ) : (
            <p className="workspace-copy">暂无能力卡片。</p>
          )}
        </section>
      </div> : null}

      {activeMode === "protocol" ? <section className="workspace-section agent-protocol-board">
        <div className="workspace-section__head">
          <GitBranch size={18} />
          <h3>通信协议调配</h3>
        </div>
        <div className="agent-protocol-board__body">
          <div className="agent-protocol-list">
            {links.map((link) => {
              const from = agentById.get(link.from_agent)?.name ?? "主会话";
              const to = agentById.get(link.to_agent)?.name ?? shortAgentName(link.to_agent);
              return (
                <button
                  className={[
                    "agent-protocol-link",
                    selectedLinkId === link.link_id ? "agent-protocol-link--selected" : "",
                    isLinkOperational(link) ? "" : "agent-protocol-link--disabled"
                  ].filter(Boolean).join(" ")}
                  key={link.link_id}
                  onClick={() => setSelectedLinkId(link.link_id)}
                  type="button"
                >
                  <Cable size={16} />
                  <span>{linkStatusLabel(link)}</span>
                  <strong>{from} → {to}</strong>
                  <em>{link.label} · {formatChannels(link.channels)}</em>
                </button>
              );
            })}
          </div>

          {selectedLink ? (
            <div className="agent-protocol-editor">
              <div className="agent-protocol-editor__head">
                <div>
                  <span>{selectedLink.link_id}</span>
                  <h3>{selectedLink.label}</h3>
                  <p>{selectedLinkFrom} → {selectedLinkTo}</p>
                </div>
                <button
                  className={selectedLink.enabled ? "agent-switch agent-switch--on" : "agent-switch"}
                  disabled={saving === selectedLink.link_id}
                  onClick={() => void toggleLink(selectedLink)}
                  type="button"
                >
                  {saving === selectedLink.link_id ? "保存中" : linkStatusLabel(selectedLink)}
                </button>
              </div>
              {selectedLink.enabled && !isLinkOperational(selectedLink) ? (
                <div className="workspace-alert">
                  这条协议本身已开启，但连接的智能体处于停用状态，所以运行链路会被阻断。
                </div>
              ) : null}
              <label>
                输入契约
                <textarea
                  value={draft.input_contract}
                  onChange={(event) => setDraft((value) => ({ ...value, input_contract: event.target.value }))}
                />
              </label>
              <label>
                输出契约
                <textarea
                  value={draft.output_contract}
                  onChange={(event) => setDraft((value) => ({ ...value, output_contract: event.target.value }))}
                />
              </label>
              <label>
                移交策略
                <textarea
                  value={draft.handoff_policy}
                  onChange={(event) => setDraft((value) => ({ ...value, handoff_policy: event.target.value }))}
                />
              </label>
              <button className="action-button action-button--primary" disabled={saving === selectedLink.link_id} onClick={() => void saveSelectedLink()} type="button">
                <Save size={16} />
                保存协议契约
              </button>
            </div>
          ) : null}
        </div>
      </section> : null}

      {activeMode === "handoff" ? <section className="workspace-section agent-io-preview">
        <div className="workspace-section__head">
          <Route size={18} />
          <h3>输入输出流</h3>
        </div>
        {selectedLink ? (
          <div className="agent-handoff-focus">
            <span>当前选中协议</span>
            <strong>{selectedLinkFrom} → {selectedLinkTo}</strong>
            <p>{selectedLink.handoff_policy}</p>
            <button className="action-button" onClick={() => setActiveMode("protocol")} type="button">
              <Cable size={16} />
              编辑这条通信契约
            </button>
          </div>
        ) : null}
        <div className="agent-io-preview__rail">
          {activeLinks.length ? activeLinks.map((link, index) => (
            <article
              className={selectedLinkId === link.link_id ? "agent-io-preview__step--active" : ""}
              key={link.link_id}
              onClick={() => setSelectedLinkId(link.link_id)}
            >
              <span>第 {index + 1} 步</span>
              <strong>{link.label}</strong>
              <p>{link.input_contract}</p>
              <em>{link.output_contract}</em>
            </article>
          )) : <div className="workspace-alert">当前没有运行可用的智能体移交流程，请先开启对应智能体和通信协议。</div>}
        </div>
      </section> : null}
    </div>
  );
}
