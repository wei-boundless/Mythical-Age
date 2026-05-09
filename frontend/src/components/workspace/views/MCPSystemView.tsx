"use client";

import {
  Activity,
  CheckCircle2,
  Loader2,
  PlugZap,
  RefreshCw,
  Save,
  Server,
  ShieldCheck,
  Trash2,
  XCircle
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  callMCPSystemTool,
  deleteMCPSystemServer,
  getMCPSystemCatalog,
  inspectMCPSystemServer,
  upsertMCPSystemServer,
  type ExternalMCPCatalog,
  type ExternalMCPServerConfig,
  type ExternalMCPSnapshot
} from "@/lib/api";

type MCPPanel = "servers" | "discovery" | "tool-pool" | "policy";

const EMPTY_SERVER: ExternalMCPServerConfig = {
  server_id: "",
  title: "",
  description: "",
  transport: "stdio",
  enabled: true,
  command: "",
  args: [],
  env: {},
  cwd: "",
  url: "",
  scope: "project",
  tags: [],
  allowed_operations: [],
  requires_approval_operations: [],
  denied_operations: [],
  metadata: {}
};

function jsonText(value: unknown) {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value ?? "");
  }
}

function parseLines(value: string) {
  return value.split("\n").map((item) => item.trim()).filter(Boolean);
}

function parseJsonObject(value: string, fallback: Record<string, unknown> = {}) {
  const trimmed = value.trim();
  if (!trimmed) {
    return fallback;
  }
  const parsed = JSON.parse(trimmed);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("必须是 JSON 对象");
  }
  return parsed as Record<string, unknown>;
}

function serverSearchText(server: ExternalMCPServerConfig) {
  return [server.server_id, server.title, server.description, server.transport, server.scope, server.tags.join(" ")].join(" ").toLowerCase();
}

function snapshotFor(catalog: ExternalMCPCatalog | null, serverId: string): ExternalMCPSnapshot | null {
  return catalog?.snapshots.find((item) => item.server_id === serverId) ?? null;
}

export function MCPSystemView() {
  const [catalog, setCatalog] = useState<ExternalMCPCatalog | null>(null);
  const [activePanel, setActivePanel] = useState<MCPPanel>("servers");
  const [selectedServerId, setSelectedServerId] = useState("");
  const [draft, setDraft] = useState(EMPTY_SERVER);
  const [argsDraft, setArgsDraft] = useState("");
  const [envDraft, setEnvDraft] = useState("{}");
  const [metadataDraft, setMetadataDraft] = useState("{}");
  const [tagsDraft, setTagsDraft] = useState("");
  const [query, setQuery] = useState("");
  const [callArgsDraft, setCallArgsDraft] = useState("{}");
  const [callResult, setCallResult] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  async function loadCatalog(message = "") {
    setLoading(true);
    setError("");
    try {
      const payload = await getMCPSystemCatalog();
      setCatalog(payload);
      setSelectedServerId((current) => payload.servers.some((item) => item.server_id === current) ? current : payload.servers[0]?.server_id ?? "");
      if (message) {
        setNotice(message);
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加载 MCP 系统失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadCatalog();
  }, []);

  const selectedServer = useMemo(
    () => catalog?.servers.find((item) => item.server_id === selectedServerId) ?? null,
    [catalog?.servers, selectedServerId]
  );
  const selectedSnapshot = useMemo(
    () => snapshotFor(catalog, selectedServerId),
    [catalog, selectedServerId]
  );

  useEffect(() => {
    const server = selectedServer ?? EMPTY_SERVER;
    setDraft(server);
    setArgsDraft(server.args.join("\n"));
    setEnvDraft(jsonText(server.env));
    setMetadataDraft(jsonText(server.metadata));
    setTagsDraft(server.tags.join("\n"));
    setCallResult("");
  }, [selectedServer]);

  const normalizedQuery = query.trim().toLowerCase();
  const visibleServers = useMemo(
    () => (catalog?.servers ?? []).filter((server) => !normalizedQuery || serverSearchText(server).includes(normalizedQuery)),
    [catalog?.servers, normalizedQuery]
  );
  const visibleTools = useMemo(
    () => (catalog?.tool_pool ?? []).filter((tool) => {
      const text = [
        tool.name,
        tool.display_name,
        tool.entry_kind,
        tool.route_family,
        tool.model_visibility,
        tool.server_id,
        tool.tool_name,
        tool.description
      ].join(" ").toLowerCase();
      return !normalizedQuery || text.includes(normalizedQuery);
    }),
    [catalog?.tool_pool, normalizedQuery]
  );

  async function saveServer() {
    setSaving(true);
    setError("");
    try {
      const payload: ExternalMCPServerConfig = {
        ...draft,
        args: parseLines(argsDraft),
        env: parseJsonObject(envDraft) as Record<string, string>,
        metadata: parseJsonObject(metadataDraft),
        tags: parseLines(tagsDraft)
      };
      const saved = await upsertMCPSystemServer(payload.server_id, payload);
      setCatalog(saved);
      setSelectedServerId(payload.server_id);
      setNotice("外部 MCP 配置已保存。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存 MCP 配置失败");
    } finally {
      setSaving(false);
    }
  }

  async function removeServer(serverId: string) {
    setSaving(true);
    setError("");
    try {
      const payload = await deleteMCPSystemServer(serverId);
      setCatalog(payload);
      setNotice("外部 MCP 已删除。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "删除 MCP 配置失败");
    } finally {
      setSaving(false);
    }
  }

  async function inspectSelected() {
    if (!selectedServerId) {
      return;
    }
    setLoading(true);
    setError("");
    try {
      const snapshot = await inspectMCPSystemServer(selectedServerId);
      setNotice(`发现完成：${snapshot.status}`);
      await loadCatalog();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "发现 MCP server 失败");
    } finally {
      setLoading(false);
    }
  }

  async function callTool(serverId: string, toolName: string) {
    setLoading(true);
    setError("");
    try {
      const payload = await callMCPSystemTool(serverId, toolName, parseJsonObject(callArgsDraft));
      setCallResult(jsonText(payload));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "调用 MCP tool 失败");
    } finally {
      setLoading(false);
    }
  }

  const panels: Array<{ id: MCPPanel; label: string; icon: typeof Server }> = [
    { id: "servers", label: "服务器", icon: Server },
    { id: "discovery", label: "发现结果", icon: Activity },
    { id: "tool-pool", label: "工具池", icon: PlugZap },
    { id: "policy", label: "权限", icon: ShieldCheck }
  ];

  return (
    <div className="workspace-view mcp-system-console">
      <header className="workspace-view__header">
        <div>
          <p className="workspace-view__eyebrow">外部 MCP 控制面</p>
          <h2 className="workspace-view__title">MCP 管理</h2>
          <p className="workspace-view__subtitle">单独管理外部 MCP 服务器的配置、协议发现、统一工具池和执行权限预检。</p>
        </div>
        <div className="workspace-view__actions">
          <button className="action-button action-button--muted" onClick={() => void loadCatalog("MCP 目录已刷新。")} type="button">
            {loading ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
            刷新
          </button>
          <button className="action-button" onClick={inspectSelected} disabled={!selectedServerId || loading} type="button">
            <Activity size={16} />
            发现
          </button>
        </div>
      </header>

      {error ? <div className="workspace-alert workspace-alert--danger">{error}</div> : null}
      {notice ? <div className="workspace-alert">{notice}</div> : null}

      <div className="workspace-metrics-grid">
        <div className="workspace-stat"><span>服务器</span><strong>{catalog?.summary.server_count ?? 0}</strong></div>
        <div className="workspace-stat"><span>已连接</span><strong>{catalog?.summary.connected_server_count ?? 0}</strong></div>
        <div className="workspace-stat"><span>工具</span><strong>{catalog?.summary.tool_count ?? 0}</strong></div>
        <div className="workspace-stat"><span>资源</span><strong>{catalog?.summary.resource_count ?? 0}</strong></div>
      </div>

      <div className="mcp-system-layout">
        <aside className="mcp-system-nav">
          {panels.map((panel) => {
            const Icon = panel.icon;
            return (
              <button
                className={`mcp-system-nav__item ${activePanel === panel.id ? "mcp-system-nav__item--active" : ""}`}
                key={panel.id}
                onClick={() => setActivePanel(panel.id)}
                type="button"
              >
                <Icon size={17} />
                <span>{panel.label}</span>
              </button>
            );
          })}
          <div className="workspace-search">
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索 MCP 服务器 / 工具" />
          </div>
        </aside>

        <section className="mcp-system-main">
          {activePanel === "servers" ? (
            <div className="mcp-system-grid">
              <section className="workspace-section">
                <div className="workspace-section__head">
                  <div><h3>外部 MCP 列表</h3><p>配置进入统一 MCP 管理面的服务器。</p></div>
                  <button className="action-button action-button--muted" onClick={() => { setSelectedServerId(""); setDraft(EMPTY_SERVER); }} type="button">新建</button>
                </div>
                <div className="mcp-server-list">
                  {visibleServers.map((server) => {
                    const snapshot = snapshotFor(catalog, server.server_id);
                    const active = selectedServerId === server.server_id;
                    return (
                      <button className={`mcp-server-row ${active ? "mcp-server-row--active" : ""}`} key={server.server_id} onClick={() => setSelectedServerId(server.server_id)} type="button">
                        <span className="mcp-server-row__status">
                          {snapshot?.status === "connected" ? <CheckCircle2 size={16} /> : <XCircle size={16} />}
                        </span>
                        <span className="mcp-server-row__copy">
                          <strong>{server.title || server.server_id}</strong>
                          <em>{server.server_id} / {server.transport}</em>
                        </span>
                      </button>
                    );
                  })}
                </div>
              </section>

              <section className="workspace-section">
                <div className="workspace-section__head">
                  <div><h3>连接配置</h3><p>stdio 服务器会用标准 MCP 客户端实际握手发现。</p></div>
                </div>
                <div className="mcp-form-grid">
                  <label><span>服务器 ID</span><input value={draft.server_id} onChange={(event) => setDraft({ ...draft, server_id: event.target.value })} /></label>
                  <label><span>标题</span><input value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} /></label>
                  <label><span>传输方式</span><select value={draft.transport} onChange={(event) => setDraft({ ...draft, transport: event.target.value })}><option value="stdio">stdio</option><option value="streamable_http">streamable_http</option></select></label>
                  <label><span>作用域</span><input value={draft.scope} onChange={(event) => setDraft({ ...draft, scope: event.target.value })} /></label>
                  <label className="mcp-form-wide"><span>启动命令</span><input value={draft.command} onChange={(event) => setDraft({ ...draft, command: event.target.value })} placeholder="python / npx / node" /></label>
                  <label className="mcp-form-wide"><span>URL</span><input value={draft.url} onChange={(event) => setDraft({ ...draft, url: event.target.value })} placeholder="streamable HTTP 预留" /></label>
                  <label className="mcp-form-wide"><span>工作目录</span><input value={draft.cwd} onChange={(event) => setDraft({ ...draft, cwd: event.target.value })} /></label>
                  <label className="mcp-form-wide"><span>描述</span><textarea value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} rows={3} /></label>
                  <label><span>参数，每行一个</span><textarea value={argsDraft} onChange={(event) => setArgsDraft(event.target.value)} rows={7} /></label>
                  <label><span>标签，每行一个</span><textarea value={tagsDraft} onChange={(event) => setTagsDraft(event.target.value)} rows={7} /></label>
                  <label><span>环境变量 JSON</span><textarea value={envDraft} onChange={(event) => setEnvDraft(event.target.value)} rows={7} /></label>
                  <label><span>元数据 JSON</span><textarea value={metadataDraft} onChange={(event) => setMetadataDraft(event.target.value)} rows={7} /></label>
                </div>
                <div className="workspace-view__actions">
                  {selectedServerId ? <button className="action-button action-button--danger" onClick={() => void removeServer(selectedServerId)} type="button"><Trash2 size={16} />删除</button> : null}
                  <button className="action-button" onClick={() => void saveServer()} disabled={saving} type="button">
                    {saving ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
                    保存
                  </button>
                </div>
              </section>
            </div>
          ) : null}

          {activePanel === "discovery" ? (
            <section className="workspace-section">
              <div className="workspace-section__head">
                <div><h3>协议发现快照</h3><p>展示工具、资源、提示词和 skill:// 资源。</p></div>
              </div>
              {selectedSnapshot ? (
                <div className="mcp-discovery-grid">
                  <article><h4>工具</h4><pre>{jsonText(selectedSnapshot.tools)}</pre></article>
                  <article><h4>资源</h4><pre>{jsonText(selectedSnapshot.resources)}</pre></article>
                  <article><h4>提示词</h4><pre>{jsonText(selectedSnapshot.prompts)}</pre></article>
                  <article><h4>能力</h4><pre>{jsonText(selectedSnapshot.capabilities)}</pre></article>
                </div>
              ) : <div className="workspace-alert">请选择一个 MCP server。</div>}
            </section>
          ) : null}

          {activePanel === "tool-pool" ? (
            <section className="workspace-section">
              <div className="workspace-section__head">
                <div><h3>统一工具池视图</h3><p>外部 MCP tool 会进入统一工具池，但模型可见性与运行时调用分开治理。</p></div>
              </div>
              <div className="mcp-tool-list">
                {visibleTools.map((tool) => (
                  <article className="workspace-record" key={tool.entry_id || tool.name}>
                    <div className="workspace-record__meta">
                      <h4>{tool.display_name || tool.name}</h4>
                      <p>{tool.description || "无描述"}</p>
                    </div>
                    <div className="workspace-chip-row">
                      <span className="workspace-mini-chip">{tool.entry_kind}</span>
                      <span className="workspace-mini-chip">{tool.route_family}</span>
                      <span className="workspace-mini-chip">{tool.runtime_exposure}</span>
                      <span className="workspace-mini-chip">{tool.model_visibility}</span>
                      <span className="workspace-mini-chip">{tool.authorized ? "authorized" : "blocked"}</span>
                    </div>
                    <dl className="mcp-tool-facts">
                      <div><dt>entry_id</dt><dd>{tool.entry_id}</dd></div>
                      <div><dt>server</dt><dd>{tool.server_id}</dd></div>
                      <div><dt>tool</dt><dd>{tool.tool_name}</dd></div>
                      <div><dt>candidate</dt><dd>{tool.candidate_visibility}</dd></div>
                    </dl>
                    <textarea value={callArgsDraft} onChange={(event) => setCallArgsDraft(event.target.value)} rows={3} />
                    <button className="action-button action-button--muted" onClick={() => void callTool(tool.server_id, tool.tool_name)} type="button">实测调用</button>
                  </article>
                ))}
              </div>
              {callResult ? <pre className="mcp-call-result">{callResult}</pre> : null}
            </section>
          ) : null}

          {activePanel === "policy" ? (
            <section className="workspace-section">
              <div className="workspace-section__head">
                <div><h3>权限预检</h3><p>外部 MCP tool 会动态生成 operation descriptor，并进入 OperationGate deny-first 管线。</p></div>
              </div>
              <pre className="mcp-call-result">{jsonText(catalog?.tool_pool.map((tool) => ({
                entry_id: tool.entry_id,
                entry_kind: tool.entry_kind,
                name: tool.name,
                operation_id: String(tool.operation?.operation_id ?? ""),
                model_visibility: tool.model_visibility,
                runtime_exposure: tool.runtime_exposure,
                authorized: tool.authorized,
                gate: tool.authorization,
                operation: tool.operation
              })) ?? [])}</pre>
            </section>
          ) : null}
        </section>
      </div>
    </div>
  );
}
