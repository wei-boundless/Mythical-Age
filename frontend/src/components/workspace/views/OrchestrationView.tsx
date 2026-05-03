"use client";

import {
  AlertTriangle,
  CheckCircle2,
  Gauge,
  GitBranch,
  KeyRound,
  Loader2,
  RefreshCw,
  Save,
  Search,
  ShieldCheck,
  SlidersHorizontal
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import {
  getOrchestrationAgents,
  updateOrchestrationAgentRuntimeProfile,
  type OrchestrationAgentRuntimeCatalog,
  type OrchestrationAgentRuntimeProfile
} from "@/lib/api";

type RuntimeDraft = OrchestrationAgentRuntimeProfile & {
  allowed_task_modes_text: string;
  allowed_runtime_lanes_text: string;
  allowed_operations_text: string;
  blocked_operations_text: string;
  allowed_memory_scopes_text: string;
  allowed_context_sections_text: string;
  output_contracts_text: string;
};

const EMPTY_PROFILE: RuntimeDraft = {
  agent_profile_id: "",
  agent_id: "",
  allowed_task_modes: [],
  allowed_runtime_lanes: [],
  allowed_operations: ["op.model_response"],
  blocked_operations: [],
  allowed_memory_scopes: [],
  allowed_context_sections: [],
  output_contracts: [],
  approval_policy: "default",
  trace_policy: "runtime_event_log",
  lifecycle_policy: "orchestration_managed",
  metadata: { managed_by: "orchestration_console" },
  allowed_task_modes_text: "",
  allowed_runtime_lanes_text: "",
  allowed_operations_text: "op.model_response",
  blocked_operations_text: "",
  allowed_memory_scopes_text: "",
  allowed_context_sections_text: "",
  output_contracts_text: ""
};

const AGENT_TYPE_LABELS: Record<string, string> = {
  main_agent: "主 Agent",
  system_management_agent: "系统管理 Agent",
  worker_sub_agent: "工作子 Agent"
};

function text(value: unknown, fallback = "-") {
  if (value === null || value === undefined || value === "") return fallback;
  if (Array.isArray(value)) return value.length ? value.join(" / ") : fallback;
  return String(value);
}

function splitList(value: string) {
  return value.split(/[\n,，]/).map((item) => item.trim()).filter(Boolean);
}

function listText(value: unknown) {
  return Array.isArray(value) ? value.map((item) => String(item)).join("\n") : "";
}

function badgeClass(value: unknown) {
  const normalized = String(value || "").toLowerCase();
  if (["valid", "enabled", "system_builtin", "ok", "ready"].includes(normalized)) return "task-system-badge task-system-badge--ok";
  if (["missing", "disabled", "blocked", "invalid", "failed"].includes(normalized)) return "task-system-badge task-system-badge--danger";
  if (["draft", "unbound", "warning"].includes(normalized)) return "task-system-badge task-system-badge--warn";
  return "task-system-badge";
}

function Badge({ value }: { value: unknown }) {
  return <span className={badgeClass(value)}>{text(value)}</span>;
}

function draftFrom(agentId: string, profile?: Partial<OrchestrationAgentRuntimeProfile>): RuntimeDraft {
  const merged = { ...EMPTY_PROFILE, ...profile, agent_id: agentId };
  return {
    ...merged,
    agent_profile_id: text(merged.agent_profile_id, `${agentId.replace(/[:]/g, "_")}_runtime`),
    allowed_task_modes: merged.allowed_task_modes ?? [],
    allowed_runtime_lanes: merged.allowed_runtime_lanes ?? [],
    allowed_operations: merged.allowed_operations?.length ? merged.allowed_operations : ["op.model_response"],
    blocked_operations: merged.blocked_operations ?? [],
    allowed_memory_scopes: merged.allowed_memory_scopes ?? [],
    allowed_context_sections: merged.allowed_context_sections ?? [],
    output_contracts: merged.output_contracts ?? [],
    approval_policy: text(merged.approval_policy, "default"),
    trace_policy: text(merged.trace_policy, "runtime_event_log"),
    lifecycle_policy: text(merged.lifecycle_policy, "orchestration_managed"),
    metadata: merged.metadata ?? { managed_by: "orchestration_console" },
    allowed_task_modes_text: listText(merged.allowed_task_modes),
    allowed_runtime_lanes_text: listText(merged.allowed_runtime_lanes),
    allowed_operations_text: listText(merged.allowed_operations?.length ? merged.allowed_operations : ["op.model_response"]),
    blocked_operations_text: listText(merged.blocked_operations),
    allowed_memory_scopes_text: listText(merged.allowed_memory_scopes),
    allowed_context_sections_text: listText(merged.allowed_context_sections),
    output_contracts_text: listText(merged.output_contracts)
  };
}

function payloadFromDraft(draft: RuntimeDraft) {
  return {
    agent_profile_id: draft.agent_profile_id,
    allowed_task_modes: splitList(draft.allowed_task_modes_text),
    allowed_runtime_lanes: splitList(draft.allowed_runtime_lanes_text),
    allowed_operations: Array.from(new Set(["op.model_response", ...splitList(draft.allowed_operations_text)])),
    blocked_operations: splitList(draft.blocked_operations_text),
    allowed_memory_scopes: splitList(draft.allowed_memory_scopes_text),
    allowed_context_sections: splitList(draft.allowed_context_sections_text),
    output_contracts: splitList(draft.output_contracts_text),
    approval_policy: draft.approval_policy,
    trace_policy: draft.trace_policy,
    lifecycle_policy: draft.lifecycle_policy,
    metadata: { ...(draft.metadata ?? {}), managed_by: "orchestration_console" }
  };
}

function agentSearchText(agent: Record<string, unknown>) {
  return [
    agent.agent_id,
    agent.display_name,
    agent.owner_system,
    agent.profile_type,
    agent.lifecycle_state,
    JSON.stringify(agent.runtime_profile ?? {})
  ].join(" ").toLowerCase();
}

export function OrchestrationView() {
  const [catalog, setCatalog] = useState<OrchestrationAgentRuntimeCatalog | null>(null);
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [draft, setDraft] = useState<RuntimeDraft>(EMPTY_PROFILE);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const payload = await getOrchestrationAgents();
      setCatalog(payload);
      setSelectedAgentId((current) => current || String(payload.agents[0]?.agent_id || ""));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "权限系统加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const agents = useMemo(() => catalog?.agents ?? [], [catalog?.agents]);
  const selectedAgent = agents.find((agent) => String(agent.agent_id) === selectedAgentId) ?? agents[0] ?? null;
  const selectedProfile = (selectedAgent?.runtime_profile ?? {}) as Partial<OrchestrationAgentRuntimeProfile>;
  const normalizedQuery = query.trim().toLowerCase();
  const visibleAgents = useMemo(
    () => agents.filter((agent) => !normalizedQuery || agentSearchText(agent).includes(normalizedQuery)),
    [agents, normalizedQuery]
  );
  const operationOptions = useMemo(
    () => (catalog?.options.operations ?? []).map((operation) => String(operation.operation_id || "")).filter(Boolean),
    [catalog?.options.operations]
  );

  useEffect(() => {
    if (!selectedAgent) return;
    setDraft(draftFrom(String(selectedAgent.agent_id), selectedProfile));
  }, [selectedAgentId, selectedAgent]); // eslint-disable-line react-hooks/exhaustive-deps

  async function saveProfile() {
    if (!selectedAgent) return;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const payload = await updateOrchestrationAgentRuntimeProfile(String(selectedAgent.agent_id), payloadFromDraft(draft));
      setCatalog(payload);
      setNotice(`${text(selectedAgent.display_name, String(selectedAgent.agent_id || ""))} 的 runtime profile 已保存。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存 runtime profile 失败");
    } finally {
      setSaving(false);
    }
  }

  function appendLine(field: keyof RuntimeDraft, value: string) {
    if (!value) return;
    setDraft((current) => {
      const oldValue = String(current[field] || "");
      const next = Array.from(new Set([...splitList(oldValue), value])).join("\n");
      return { ...current, [field]: next };
    });
  }

  const profileMissing = Boolean(selectedAgent && !selectedProfile.agent_profile_id);
  const blockedOps = splitList(draft.blocked_operations_text);
  const allowedOps = splitList(draft.allowed_operations_text);
  const overlapOps = allowedOps.filter((operation) => blockedOps.includes(operation));

  return (
    <div className="workspace-view task-system-view orchestration-runtime-view">
      <div className="workspace-view__header">
        <div>
          <p className="workspace-view__eyebrow">Runtime Permission</p>
          <h2 className="workspace-view__title">权限系统</h2>
          <p className="workspace-view__subtitle">任务系统负责任务、workflow 和投影绑定；权限系统只决定 Agent 在 runtime 中拥有哪些操作、上下文、记忆与输出边界。</p>
        </div>
        <div className="workspace-view__actions">
          <button className="ghost-button" onClick={() => void load()} type="button">
            <RefreshCw size={16} />刷新
          </button>
        </div>
      </div>

      {error ? <div className="notice-banner notice-banner--error">{error}</div> : null}
      {notice ? <div className="notice-banner">{notice}</div> : null}

      <section className="task-system-hero task-system-hero--wide">
        <article>
          <span>Agent 名册</span>
          <strong>{text(catalog?.summary.agent_count, "0")}</strong>
          <p>来自任务系统登记，只在编排层读取。</p>
        </article>
        <article>
          <span>Runtime Profile</span>
          <strong>{text(catalog?.summary.runtime_profile_count, "0")}</strong>
          <p>由权限系统管理，运行时采用。</p>
        </article>
        <article>
          <span>缺失 Profile</span>
          <strong>{text(catalog?.summary.profile_missing_count, "0")}</strong>
          <p>缺失时只能走最小模型响应能力。</p>
        </article>
        <article>
          <span>可授权操作</span>
          <strong>{operationOptions.length}</strong>
          <p>来自 Operation Registry 的运行操作集合。</p>
        </article>
      </section>

      <section className="task-system-layout">
        <div className="task-system-workbench">
          <div className="task-system-toolbar">
            <div className="task-system-section-head">
              <div>
                <h3>Agent Runtime 列表</h3>
                <p>点击 Agent 后编辑 runtime 权限，不在这里改变任务归属和多 Agent 拓扑。</p>
              </div>
            </div>
            <div className="archive-search task-system-search">
              <Search size={16} />
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索 agent / owner / profile / workflow" />
            </div>
          </div>

          {loading ? (
            <div className="task-system-empty"><Loader2 className="animate-spin" size={18} /> 正在加载编排控制台</div>
          ) : (
            <div className="task-system-agent-card-grid">
              {visibleAgents.map((agent) => {
                const runtimeProfile = (agent.runtime_profile ?? {}) as Partial<OrchestrationAgentRuntimeProfile>;
                const active = String(agent.agent_id) === selectedAgentId;
                const type = String(agent.profile_type || "");
                return (
                  <button
                    className={`task-system-agent-card ${active ? "task-system-agent-card--active" : ""}`}
                    key={String(agent.agent_id)}
                    onClick={() => setSelectedAgentId(String(agent.agent_id || ""))}
                    type="button"
                  >
                    <div className="task-system-agent-card__head">
                      <div>
                        <div>
                          <Badge value={AGENT_TYPE_LABELS[type] ?? type} />
                          <Badge value={agent.lifecycle_state} />
                        </div>
                        <h4>{text(agent.display_name, String(agent.agent_id || ""))}</h4>
                        <p>{text(agent.agent_id)} · {text(agent.owner_system)}</p>
                      </div>
                      {runtimeProfile.agent_profile_id ? <ShieldCheck size={18} /> : <AlertTriangle size={18} />}
                    </div>
                    <div className="task-system-agent-card__flows">
                      <b>{text(runtimeProfile.agent_profile_id, "runtime profile missing")}</b>
                      <span>{text(runtimeProfile.allowed_runtime_lanes, "未配置 runtime lane")}</span>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <aside className="task-system-inspector">
          {selectedAgent ? (
            <>
              <div className="task-system-editor-head">
                <span><ShieldCheck size={20} /></span>
                <div>
                  <em>Runtime Profile</em>
                  <strong>{text(selectedAgent.display_name, String(selectedAgent.agent_id || ""))}</strong>
                  <p>这里不负责任务 workflow 和投影选择，只定义这个 Agent 的内部运行边界。</p>
                </div>
              </div>

              <div className="task-system-info-grid">
                <div className="task-system-info-block">
                  <span><Gauge size={14} />状态</span>
                  <strong>{profileMissing ? "profile missing" : "profile ready"}</strong>
                </div>
                <div className="task-system-info-block">
                  <span><KeyRound size={14} />操作</span>
                  <strong>{allowedOps.length}</strong>
                </div>
                <div className="task-system-info-block">
                  <span><ShieldCheck size={14} />阻断</span>
                  <strong>{blockedOps.length}</strong>
                </div>
              </div>

              {overlapOps.length ? (
                <div className="task-system-diagnostic-card">
                  <AlertTriangle size={18} />
                  <div>
                    <strong>权限冲突</strong>
                    <p>{overlapOps.join(" / ")} 同时出现在允许和阻断列表中，runtime 会按阻断优先。</p>
                  </div>
                </div>
              ) : (
                <div className="task-system-diagnostic-row task-system-diagnostic-row--ok">
                  <strong><CheckCircle2 size={16} />权限集合无直接冲突</strong>
                </div>
              )}

              <div className="task-system-form-section">
                <div className="task-system-form-grid">
                  <label>
                    <span>Profile ID</span>
                    <input value={draft.agent_profile_id} onChange={(event) => setDraft((value) => ({ ...value, agent_profile_id: event.target.value }))} />
                  </label>
                  <label>
                    <span>审批策略</span>
                    <select value={draft.approval_policy} onChange={(event) => setDraft((value) => ({ ...value, approval_policy: event.target.value }))}>
                      {(catalog?.options.approval_policies ?? ["default"]).map((policy) => <option key={policy} value={policy}>{policy}</option>)}
                    </select>
                  </label>
                  <label>
                    <span>Trace 策略</span>
                    <select value={draft.trace_policy} onChange={(event) => setDraft((value) => ({ ...value, trace_policy: event.target.value }))}>
                      {(catalog?.options.trace_policies ?? ["runtime_event_log"]).map((policy) => <option key={policy} value={policy}>{policy}</option>)}
                    </select>
                  </label>
                  <label>
                    <span>生命周期策略</span>
                    <input value={draft.lifecycle_policy} onChange={(event) => setDraft((value) => ({ ...value, lifecycle_policy: event.target.value }))} />
                  </label>
                </div>
              </div>

              <RuntimeTextarea title="Task Modes" icon={<SlidersHorizontal size={16} />} value={draft.allowed_task_modes_text} onChange={(value) => setDraft((draftValue) => ({ ...draftValue, allowed_task_modes_text: value }))} suggestions={catalog?.options.task_modes ?? []} onAdd={(value) => appendLine("allowed_task_modes_text", value)} />
              <RuntimeTextarea title="Runtime Lanes" icon={<GitBranch size={16} />} value={draft.allowed_runtime_lanes_text} onChange={(value) => setDraft((draftValue) => ({ ...draftValue, allowed_runtime_lanes_text: value }))} suggestions={catalog?.options.runtime_lanes ?? []} onAdd={(value) => appendLine("allowed_runtime_lanes_text", value)} />
              <RuntimeTextarea title="Allowed Operations" icon={<KeyRound size={16} />} value={draft.allowed_operations_text} onChange={(value) => setDraft((draftValue) => ({ ...draftValue, allowed_operations_text: value }))} suggestions={operationOptions} onAdd={(value) => appendLine("allowed_operations_text", value)} />
              <RuntimeTextarea title="Blocked Operations" icon={<ShieldCheck size={16} />} value={draft.blocked_operations_text} onChange={(value) => setDraft((draftValue) => ({ ...draftValue, blocked_operations_text: value }))} suggestions={operationOptions} onAdd={(value) => appendLine("blocked_operations_text", value)} />
              <RuntimeTextarea title="Memory / Context / Output" icon={<Gauge size={16} />} value={[draft.allowed_memory_scopes_text, "---context---", draft.allowed_context_sections_text, "---output---", draft.output_contracts_text].join("\n")} onChange={(value) => {
                const [memory = "", context = "", output = ""] = value.split(/---context---|---output---/);
                setDraft((draftValue) => ({
                  ...draftValue,
                  allowed_memory_scopes_text: memory.trim(),
                  allowed_context_sections_text: context.trim(),
                  output_contracts_text: output.trim()
                }));
              }} suggestions={[...(catalog?.options.memory_scopes ?? []), ...(catalog?.options.context_sections ?? []), ...(catalog?.options.output_contracts ?? [])]} onAdd={() => undefined} />

              <div className="task-system-actions">
                <button className="primary-button" disabled={saving} onClick={() => void saveProfile()} type="button">
                  {saving ? <Loader2 className="animate-spin" size={16} /> : <Save size={16} />}
                  保存 Runtime Profile
                </button>
              </div>
            </>
          ) : (
            <div className="task-system-empty">还没有可编排的 Agent。</div>
          )}
        </aside>
      </section>
    </div>
  );
}

function RuntimeTextarea({
  title,
  icon,
  value,
  onChange,
  suggestions,
  onAdd
}: {
  title: string;
  icon: ReactNode;
  value: string;
  onChange: (value: string) => void;
  suggestions: string[];
  onAdd: (value: string) => void;
}) {
  return (
    <div className="task-system-form-section">
      <div className="task-system-section-head">
        <h3>{icon}{title}</h3>
      </div>
      <div className="task-system-form-grid task-system-form-grid--wide">
        <label className="task-system-form-grid__full">
          <span>每行一个条目</span>
          <textarea value={value} onChange={(event) => onChange(event.target.value)} />
        </label>
      </div>
      {suggestions.length ? (
        <div className="task-system-chip-grid">
          {suggestions.slice(0, 18).map((item) => (
            <button className="task-system-agent-chip" key={item} onClick={() => onAdd(item)} type="button">
              <CheckCircle2 size={14} />
              <span>{item}</span>
              <small>加入配置</small>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
