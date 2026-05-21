"use client";

import {
  Activity,
  CheckCircle2,
  ClipboardCheck,
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
  callMCPManagementTool,
  deleteMCPManagementExternalServer,
  getMCPManagementCatalog,
  inspectMCPManagementServer,
  previewMCPManagementTool,
  upsertMCPManagementExternalServer,
  type ExternalMCPServerConfig,
  type MCPManagementCatalog,
  type MCPManagementServer,
  type MCPManagementTool
} from "@/lib/api";

type MCPPanel = "providers" | "tools" | "policy";

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

function serverKey(server: Pick<MCPManagementServer, "provider_id" | "server_id">) {
  return `${server.provider_id}:${server.server_id}`;
}

function serverSearchText(server: MCPManagementServer) {
  return [
    server.provider_id,
    server.provider_kind,
    server.server_id,
    server.title,
    server.description,
    server.transport,
    server.status,
    server.status_reason,
    server.operation_ids.join(" "),
    server.tools.map((tool) => `${tool.tool_name} ${tool.title} ${tool.operation_id}`).join(" ")
  ].join(" ").toLowerCase();
}

function toolSearchText(tool: MCPManagementTool) {
  return [
    tool.provider_id,
    tool.provider_kind,
    tool.server_id,
    tool.tool_name,
    tool.title,
    tool.description,
    tool.operation_id,
    tool.model_visibility,
    tool.status,
    tool.transport,
    tool.tags.join(" ")
  ].join(" ").toLowerCase();
}

function statusLabel(status: string) {
  const value = status || "not_inspected";
  if (value === "active") return "可用";
  if (value === "connected") return "已连接";
  if (value === "disabled") return "停用";
  if (value === "unsupported" || value === "not_supported") return "未支持";
  if (value === "failed") return "失败";
  if (value === "not_inspected") return "未发现";
  return value;
}

function statusTone(status: string) {
  if (status === "active" || status === "connected") return "ok";
  if (status === "failed" || status === "unsupported" || status === "not_supported") return "bad";
  if (status === "disabled") return "muted";
  return "wait";
}

function externalConfigFromServer(server: MCPManagementServer | null): ExternalMCPServerConfig {
  if (!server || server.provider_kind !== "external") {
    return EMPTY_SERVER;
  }
  const config = (server.diagnostics.external_config ?? {}) as Partial<ExternalMCPServerConfig>;
  return {
    ...EMPTY_SERVER,
    ...config,
    server_id: String(config.server_id || server.server_id),
    title: String(config.title || server.title || server.server_id),
    description: String(config.description || server.description || ""),
    transport: String(config.transport || server.transport || "stdio"),
    enabled: Boolean(config.enabled ?? server.enabled),
    args: Array.isArray(config.args) ? config.args.map(String) : [],
    env: config.env && typeof config.env === "object" && !Array.isArray(config.env) ? config.env as Record<string, string> : {},
    tags: Array.isArray(config.tags) ? config.tags.map(String) : [],
    allowed_operations: Array.isArray(config.allowed_operations) ? config.allowed_operations.map(String) : [],
    requires_approval_operations: Array.isArray(config.requires_approval_operations) ? config.requires_approval_operations.map(String) : [],
    denied_operations: Array.isArray(config.denied_operations) ? config.denied_operations.map(String) : [],
    metadata: config.metadata && typeof config.metadata === "object" && !Array.isArray(config.metadata) ? config.metadata : {}
  };
}

function mergeTools(catalog: MCPManagementCatalog | null, inspections: Record<string, MCPManagementServer>) {
  const byKey = new Map<string, MCPManagementTool>();
  for (const tool of catalog?.tools ?? []) {
    byKey.set(`${tool.provider_id}:${tool.server_id}:${tool.tool_name}`, tool);
  }
  for (const server of Object.values(inspections)) {
    for (const tool of server.tools ?? []) {
      byKey.set(`${tool.provider_id}:${tool.server_id}:${tool.tool_name}`, {
        ...tool,
        provider_kind: server.provider_kind,
        transport: server.transport,
        status: server.status
      });
    }
  }
  return Array.from(byKey.values()).sort((left, right) => {
    return `${left.provider_kind}:${left.server_id}:${left.tool_name}`.localeCompare(`${right.provider_kind}:${right.server_id}:${right.tool_name}`);
  });
}

export function MCPSystemView() {
  const [catalog, setCatalog] = useState<MCPManagementCatalog | null>(null);
  const [inspections, setInspections] = useState<Record<string, MCPManagementServer>>({});
  const [activePanel, setActivePanel] = useState<MCPPanel>("providers");
  const [selectedKey, setSelectedKey] = useState("");
  const [draft, setDraft] = useState(EMPTY_SERVER);
  const [argsDraft, setArgsDraft] = useState("");
  const [envDraft, setEnvDraft] = useState("{}");
  const [metadataDraft, setMetadataDraft] = useState("{}");
  const [tagsDraft, setTagsDraft] = useState("");
  const [allowedDraft, setAllowedDraft] = useState("");
  const [approvalDraft, setApprovalDraft] = useState("");
  const [deniedDraft, setDeniedDraft] = useState("");
  const [query, setQuery] = useState("");
  const [callArgsDraft, setCallArgsDraft] = useState("{}");
  const [toolResult, setToolResult] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  async function loadCatalog(message = "") {
    setLoading(true);
    setError("");
    try {
      const payload = await getMCPManagementCatalog();
      setCatalog(payload);
      setSelectedKey((current) => {
        if (payload.servers.some((item) => serverKey(item) === current)) {
          return current;
        }
        return payload.servers[0] ? serverKey(payload.servers[0]) : "";
      });
      if (message) {
        setNotice(message);
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加载 MCP 管理目录失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadCatalog();
  }, []);

  const selectedServer = useMemo(
    () => catalog?.servers.find((item) => serverKey(item) === selectedKey) ?? null,
    [catalog?.servers, selectedKey]
  );
  const selectedInspection = selectedServer ? inspections[serverKey(selectedServer)] ?? null : null;
  const effectiveSelectedServer = selectedInspection ?? selectedServer;
  const isExternal = effectiveSelectedServer?.provider_kind === "external";
  const isNewExternal = !effectiveSelectedServer && draft.server_id.trim().length > 0;

  useEffect(() => {
    const external = externalConfigFromServer(effectiveSelectedServer);
    setDraft(external);
    setArgsDraft(external.args.join("\n"));
    setEnvDraft(jsonText(external.env));
    setMetadataDraft(jsonText(external.metadata));
    setTagsDraft(external.tags.join("\n"));
    setAllowedDraft(external.allowed_operations.join("\n"));
    setApprovalDraft(external.requires_approval_operations.join("\n"));
    setDeniedDraft(external.denied_operations.join("\n"));
    setToolResult("");
  }, [effectiveSelectedServer]);

  const normalizedQuery = query.trim().toLowerCase();
  const visibleServers = useMemo(
    () => (catalog?.servers ?? []).filter((server) => !normalizedQuery || serverSearchText(server).includes(normalizedQuery)),
    [catalog?.servers, normalizedQuery]
  );
  const allTools = useMemo(() => mergeTools(catalog, inspections), [catalog, inspections]);
  const visibleTools = useMemo(
    () => allTools.filter((tool) => !normalizedQuery || toolSearchText(tool).includes(normalizedQuery)),
    [allTools, normalizedQuery]
  );
  const selectedTools = useMemo(
    () => allTools.filter((tool) => !effectiveSelectedServer || (tool.provider_id === effectiveSelectedServer.provider_id && tool.server_id === effectiveSelectedServer.server_id)),
    [allTools, effectiveSelectedServer]
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
        tags: parseLines(tagsDraft),
        allowed_operations: parseLines(allowedDraft),
        requires_approval_operations: parseLines(approvalDraft),
        denied_operations: parseLines(deniedDraft)
      };
      if (!payload.server_id.trim()) {
        throw new Error("服务器 ID 不能为空");
      }
      await upsertMCPManagementExternalServer(payload.server_id, payload);
      await loadCatalog("MCP 配置已保存。");
      setSelectedKey(`external:${payload.server_id}`);
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
      await deleteMCPManagementExternalServer(serverId);
      setInspections((current) => {
        const next = { ...current };
        delete next[`external:${serverId}`];
        return next;
      });
      await loadCatalog("MCP 配置已删除。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "删除 MCP 配置失败");
    } finally {
      setSaving(false);
    }
  }

  async function inspectSelected() {
    if (!effectiveSelectedServer) {
      return;
    }
    setLoading(true);
    setError("");
    try {
      const snapshot = await inspectMCPManagementServer(effectiveSelectedServer.provider_id, effectiveSelectedServer.server_id);
      setInspections((current) => ({ ...current, [serverKey(snapshot)]: snapshot }));
      setNotice(`发现完成：${snapshot.title || snapshot.server_id} / ${statusLabel(snapshot.status)}`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "发现 MCP server 失败");
    } finally {
      setLoading(false);
    }
  }

  async function previewTool(tool: MCPManagementTool) {
    setLoading(true);
    setError("");
    try {
      const payload = await previewMCPManagementTool(tool.provider_id, tool.server_id, tool.tool_name, parseJsonObject(callArgsDraft));
      setToolResult(jsonText(payload));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "权限预检失败");
    } finally {
      setLoading(false);
    }
  }

  async function callTool(tool: MCPManagementTool) {
    setLoading(true);
    setError("");
    try {
      const payload = await callMCPManagementTool(tool.provider_id, tool.server_id, tool.tool_name, parseJsonObject(callArgsDraft));
      setToolResult(jsonText(payload));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "调用 MCP tool 失败");
    } finally {
      setLoading(false);
    }
  }

  const panels: Array<{ id: MCPPanel; label: string; icon: typeof Server }> = [
    { id: "providers", label: "Provider", icon: Server },
    { id: "tools", label: "工具", icon: PlugZap },
    { id: "policy", label: "权限", icon: ShieldCheck }
  ];

  return (
    <div className="workspace-view mcp-system-console">
      <header className="workspace-view__header">
        <div>
          <p className="workspace-view__eyebrow">统一 MCP 管理面</p>
          <h2 className="workspace-view__title">MCP 能力端点</h2>
          <p className="workspace-view__subtitle">本地 MCP 和外部 MCP 作为同一类 provider 管理；目录加载不主动连接外部服务，发现和调用必须显式触发。</p>
        </div>
        <div className="workspace-view__actions">
          <button className="action-button action-button--muted" onClick={() => void loadCatalog("MCP 管理目录已刷新。")} type="button">
            {loading ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
            刷新
          </button>
          <button className="action-button" onClick={inspectSelected} disabled={!effectiveSelectedServer || loading} type="button">
            <Activity size={16} />
            发现
          </button>
        </div>
      </header>

      {error ? <div className="workspace-alert workspace-alert--danger">{error}</div> : null}
      {notice ? <div className="workspace-alert">{notice}</div> : null}

      <div className="workspace-metrics-grid">
        <div className="workspace-stat"><span>Provider</span><strong>{catalog?.summary.provider_count ?? 0}</strong></div>
        <div className="workspace-stat"><span>本地端点</span><strong>{catalog?.summary.local_server_count ?? 0}</strong></div>
        <div className="workspace-stat"><span>外部端点</span><strong>{catalog?.summary.external_server_count ?? 0}</strong></div>
        <div className="workspace-stat"><span>可见工具</span><strong>{allTools.length}</strong></div>
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
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索 provider / server / tool" />
          </div>
          <button
            className="action-button action-button--muted"
            onClick={() => {
              setSelectedKey("");
              setDraft(EMPTY_SERVER);
              setActivePanel("providers");
            }}
            type="button"
          >
            <Server size={16} />
            新建外部 MCP
          </button>
        </aside>

        <section className="mcp-system-main">
          {activePanel === "providers" ? (
            <div className="mcp-system-grid">
              <section className="workspace-section">
                <div className="workspace-section__head">
                  <div><h3>Provider 列表</h3><p>本地端点只读管理；外部端点可配置、手动发现、手动调用。</p></div>
                </div>
                <div className="mcp-server-list">
                  {visibleServers.map((server) => {
                    const active = serverKey(server) === selectedKey;
                    const tone = statusTone(server.status);
                    return (
                      <button className={`mcp-server-row ${active ? "mcp-server-row--active" : ""}`} key={serverKey(server)} onClick={() => setSelectedKey(serverKey(server))} type="button">
                        <span className={`mcp-server-row__status mcp-status mcp-status--${tone}`}>
                          {tone === "ok" ? <CheckCircle2 size={16} /> : <XCircle size={16} />}
                        </span>
                        <span className="mcp-server-row__copy">
                          <strong>{server.title || server.server_id}</strong>
                          <em>{server.provider_kind} / {server.transport} / {statusLabel(server.status)}</em>
                          <small>{server.operation_ids.join(", ") || server.status_reason || "等待发现"}</small>
                        </span>
                      </button>
                    );
                  })}
                </div>
              </section>

              <section className="workspace-section">
                <div className="workspace-section__head">
                  <div><h3>{isExternal || isNewExternal || !effectiveSelectedServer ? "外部 MCP 配置" : "本地 MCP 端点"}</h3><p>配置不是授权事实；真实调用仍要经过 OperationGate。</p></div>
                </div>
                {isExternal || isNewExternal || !effectiveSelectedServer ? (
                  <>
                    <div className="mcp-form-grid">
                      <label><span>服务器 ID</span><input value={draft.server_id} onChange={(event) => setDraft({ ...draft, server_id: event.target.value })} /></label>
                      <label><span>标题</span><input value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} /></label>
                      <label><span>传输方式</span><select value={draft.transport} onChange={(event) => setDraft({ ...draft, transport: event.target.value })}><option value="stdio">stdio</option><option value="streamable_http">streamable_http</option></select></label>
                      <label><span>作用域</span><input value={draft.scope} onChange={(event) => setDraft({ ...draft, scope: event.target.value })} /></label>
                      <label className="mcp-form-wide"><span>启动命令</span><input value={draft.command} onChange={(event) => setDraft({ ...draft, command: event.target.value })} placeholder="python / npx / node" /></label>
                      <label className="mcp-form-wide"><span>URL</span><input value={draft.url} onChange={(event) => setDraft({ ...draft, url: event.target.value })} placeholder="streamable HTTP 当前只展示为 unsupported" /></label>
                      <label className="mcp-form-wide"><span>工作目录</span><input value={draft.cwd} onChange={(event) => setDraft({ ...draft, cwd: event.target.value })} /></label>
                      <label className="mcp-form-wide"><span>描述</span><textarea value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} rows={3} /></label>
                      <label><span>参数，每行一个</span><textarea value={argsDraft} onChange={(event) => setArgsDraft(event.target.value)} rows={6} /></label>
                      <label><span>标签，每行一个</span><textarea value={tagsDraft} onChange={(event) => setTagsDraft(event.target.value)} rows={6} /></label>
                      <label><span>环境变量 JSON</span><textarea value={envDraft} onChange={(event) => setEnvDraft(event.target.value)} rows={6} /></label>
                      <label><span>元数据 JSON</span><textarea value={metadataDraft} onChange={(event) => setMetadataDraft(event.target.value)} rows={6} /></label>
                      <label><span>默认允许 operation</span><textarea value={allowedDraft} onChange={(event) => setAllowedDraft(event.target.value)} rows={4} /></label>
                      <label><span>需要审批 operation</span><textarea value={approvalDraft} onChange={(event) => setApprovalDraft(event.target.value)} rows={4} /></label>
                      <label className="mcp-form-wide"><span>拒绝 operation</span><textarea value={deniedDraft} onChange={(event) => setDeniedDraft(event.target.value)} rows={3} /></label>
                    </div>
                    <div className="workspace-view__actions">
                      {isExternal ? <button className="action-button action-button--danger" onClick={() => void removeServer(draft.server_id)} type="button"><Trash2 size={16} />删除</button> : null}
                      <button className="action-button" onClick={() => void saveServer()} disabled={saving} type="button">
                        {saving ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
                        保存
                      </button>
                    </div>
                  </>
                ) : (
                  <div className="mcp-inspection-summary">
                    <div><span>provider</span><strong>{effectiveSelectedServer.provider_id}</strong></div>
                    <div><span>server</span><strong>{effectiveSelectedServer.server_id}</strong></div>
                    <div><span>transport</span><strong>{effectiveSelectedServer.transport}</strong></div>
                    <div><span>status</span><strong>{statusLabel(effectiveSelectedServer.status)}</strong></div>
                    <pre>{jsonText(effectiveSelectedServer.diagnostics)}</pre>
                  </div>
                )}
              </section>
            </div>
          ) : null}

          {activePanel === "tools" ? (
            <section className="workspace-section">
              <div className="workspace-section__head">
                <div><h3>统一工具列表</h3><p>本地和外部 MCP tool 都映射到 operation；外部工具只有手动发现后才出现 schema。</p></div>
              </div>
              <div className="mcp-tool-list">
                {visibleTools.map((tool) => (
                  <article className="workspace-record mcp-tool-row" key={`${tool.provider_id}:${tool.server_id}:${tool.tool_name}`}>
                    <div className="workspace-record__meta">
                      <h4>{tool.title || tool.tool_name}</h4>
                      <p>{tool.description || "无描述"}</p>
                    </div>
                    <div className="workspace-chip-row">
                      <span className="workspace-mini-chip">{tool.provider_kind}</span>
                      <span className="workspace-mini-chip">{tool.transport || "in_process"}</span>
                      <span className="workspace-mini-chip">{statusLabel(tool.status || "not_inspected")}</span>
                      <span className="workspace-mini-chip">{tool.model_visibility}</span>
                    </div>
                    <dl className="mcp-tool-facts">
                      <div><dt>operation</dt><dd>{tool.operation_id}</dd></div>
                      <div><dt>server</dt><dd>{tool.server_id}</dd></div>
                      <div><dt>tool</dt><dd>{tool.tool_name}</dd></div>
                    </dl>
                    <div className="mcp-tool-actions">
                      <textarea value={callArgsDraft} onChange={(event) => setCallArgsDraft(event.target.value)} rows={3} />
                      <button className="action-button action-button--muted" onClick={() => void previewTool(tool)} type="button"><ClipboardCheck size={16} />预检</button>
                      <button className="action-button action-button--muted" onClick={() => void callTool(tool)} type="button"><PlugZap size={16} />调用</button>
                    </div>
                  </article>
                ))}
              </div>
              {toolResult ? <pre className="mcp-call-result">{toolResult}</pre> : null}
            </section>
          ) : null}

          {activePanel === "policy" ? (
            <section className="workspace-section">
              <div className="workspace-section__head">
                <div><h3>权限视图</h3><p>这里展示的是管理面预检材料，不替代运行时 turn 内的 ResourcePolicy。</p></div>
              </div>
              <div className="mcp-policy-table">
                {selectedTools.map((tool) => (
                  <div className="mcp-policy-row" key={`${tool.provider_id}:${tool.server_id}:${tool.tool_name}`}>
                    <span>{tool.title || tool.tool_name}</span>
                    <strong>{tool.operation_id}</strong>
                    <em>{tool.provider_kind} / {tool.model_visibility}</em>
                  </div>
                ))}
                {!selectedTools.length ? <div className="workspace-alert">当前端点还没有可展示工具；外部 MCP 请先手动发现。</div> : null}
              </div>
              <pre className="mcp-call-result">{jsonText(effectiveSelectedServer ?? catalog)}</pre>
            </section>
          ) : null}
        </section>
      </div>
    </div>
  );
}
