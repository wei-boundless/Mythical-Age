"use client";

import {
  AlertTriangle,
  Code2,
  FilePlus2,
  Loader2,
  PlugZap,
  RefreshCw,
  Save,
  Search,
  ShieldCheck,
  Sparkles,
  Trash2,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { type ReactNode, useEffect, useMemo, useState } from "react";

import {
  callMCPManagementTool,
  createCapabilitySystemSkill,
  deleteCapabilitySystemSkill,
  deleteMCPManagementExternalServer,
  getCapabilitySystemCatalog,
  inspectMCPManagementServer,
  previewMCPManagementTool,
  refreshCapabilitySystemCatalog,
  saveCapabilitySystemSkill,
  updateCapabilitySystemSkillPromptView,
  updateCapabilitySystemTool,
  upsertMCPManagementExternalServer,
  type CapabilityEndpoint,
  type CapabilitySystemCatalog,
  type CapabilityUnit,
  type ExternalMCPServerConfig,
  type MCPManagementCatalog,
  type MCPManagementServer,
  type MCPManagementTool,
  type OperationSkill,
  type OperationTool,
} from "@/lib/api";

type CapabilityPage = "overview" | "units" | "skills" | "tools" | "mcp";

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
  metadata: {},
};

const GROUPS: Array<{
  id: Exclude<CapabilityPage, "overview">;
  title: string;
  detail: string;
  source: string;
  action: string;
  icon: LucideIcon;
}> = [
  {
    id: "skills",
    title: "工作方法",
    detail: "管理 Skills、模型可见提示和 SKILL.md。",
    source: "方法层",
    action: "编辑方法",
    icon: Sparkles,
  },
  {
    id: "tools",
    title: "执行工具",
    detail: "维护本地工具的类型、边界、风险和备注。",
    source: "执行层",
    action: "管理工具",
    icon: Wrench,
  },
  {
    id: "mcp",
    title: "服务接入",
    detail: "本地 MCP、外部 MCP 和端点投影统一管理。",
    source: "接入层",
    action: "配置服务",
    icon: PlugZap,
  },
  {
    id: "units",
    title: "授权治理",
    detail: "查看统一能力投影、权限、健康和依赖。",
    source: "治理层",
    action: "查看治理",
    icon: ShieldCheck,
  },
];

const RISK_CLASS: Record<string, string> = {
  低: "operation-risk--low",
  中: "operation-risk--medium",
  高: "operation-risk--high",
  极高: "operation-risk--critical",
};

function jsonText(value: unknown) {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value ?? "");
  }
}

function splitLines(value: string) {
  return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
}

function parseJsonObject(value: string, label = "JSON") {
  const trimmed = value.trim();
  if (!trimmed) return {};
  const parsed = JSON.parse(trimmed);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${label} 必须是 JSON 对象`);
  }
  return parsed as Record<string, unknown>;
}

function compactList(values: string[] | undefined, fallback = "未配置") {
  return values?.length ? values.join(" / ") : fallback;
}

function defaultSkillDraft(name: string, title: string, description: string) {
  return `---
name: ${name || "new-skill"}
description: ${description || "描述这个 skill 的用途。"}
metadata:
  display_name: ${title || "新 Skill"}
  supported_modalities:
    - text
  supported_task_kinds: []
  supported_source_kinds: []
  capability_tags: []
  preferred_route: capability_authoring
  requires_operations:
    - op.read_file
    - op.write_file
    - op.edit_file
  requires_capabilities:
    - tool:read_file
    - tool:write_file
    - tool:edit_file
  activation_policy: model_visible
  context_mode: inline
  route_authority: candidate_only
---

# ${title || "新 Skill"}

${description || "描述这个 skill 如何帮助智能体完成任务。"}

## 适用场景

- 写清楚模型什么时候应该使用这个 skill。

## 执行准则

- 声明这个 skill 依赖的 operations 和 capabilities，不假设权限会自动扩大。
- 直接完成用户任务，不暴露内部路由、工具协议或调度细节。
`;
}

function skillSearchText(skill: OperationSkill) {
  return [
    skill.runtime.name,
    skill.runtime.title,
    skill.runtime.description,
    skill.runtime.preferred_route,
    skill.runtime.activation_policy,
    skill.runtime.capability_tags.join(" "),
    skill.runtime.supported_task_kinds.join(" "),
    skill.prompt_block,
  ].join(" ").toLowerCase();
}

function toolSearchText(tool: OperationTool) {
  return [
    tool.name,
    tool.display_name,
    tool.operation_id,
    tool.module,
    tool.operation_metadata.tool_type,
    tool.operation_metadata.tool_boundary,
    tool.operation_metadata.risk_level,
    tool.operation_metadata.llm_description,
    tool.operation_metadata.note,
    tool.capability_tags.join(" "),
  ].join(" ").toLowerCase();
}

function unitSearchText(unit: CapabilityUnit) {
  return [
    unit.capability_id,
    unit.kind,
    unit.title,
    unit.summary,
    unit.provider,
    unit.provider_kind,
    unit.transport,
    unit.status,
    unit.operation_ids.join(" "),
    unit.risk.join(" "),
    unit.source_ref,
  ].join(" ").toLowerCase();
}

function endpointSearchText(endpoint: CapabilityEndpoint) {
  return [
    endpoint.endpoint_id,
    endpoint.kind,
    endpoint.name,
    endpoint.title,
    endpoint.description,
    endpoint.operation_id,
    endpoint.server_name,
    endpoint.transport,
    endpoint.runtime_lane,
    endpoint.model_visibility,
    endpoint.tags.join(" "),
  ].join(" ").toLowerCase();
}

function mcpServerKey(server: Pick<MCPManagementServer, "provider_id" | "server_id">) {
  return `${server.provider_id}:${server.server_id}`;
}

function mcpServerSearchText(server: MCPManagementServer) {
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
    server.tools.map((tool) => `${tool.tool_name} ${tool.title} ${tool.operation_id}`).join(" "),
  ].join(" ").toLowerCase();
}

function mcpToolSearchText(tool: MCPManagementTool) {
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
    tool.tags.join(" "),
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
  if (!server || server.provider_kind !== "external") return EMPTY_SERVER;
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
    metadata: config.metadata && typeof config.metadata === "object" && !Array.isArray(config.metadata) ? config.metadata : {},
  };
}

function mergeMcpTools(catalog: MCPManagementCatalog | null, inspections: Record<string, MCPManagementServer>) {
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
        status: server.status,
      });
    }
  }
  return Array.from(byKey.values()).sort((left, right) => {
    return `${left.provider_kind}:${left.server_id}:${left.tool_name}`.localeCompare(`${right.provider_kind}:${right.server_id}:${right.tool_name}`);
  });
}

function FactGrid({ items, columns = 4 }: { items: Array<{ label: string; value: ReactNode }>; columns?: 2 | 3 | 4 }) {
  return (
    <div className={`operation-fact-grid operation-fact-grid--${columns}`}>
      {items.map((item) => (
        <article key={item.label}>
          <span>{item.label}</span>
          <strong>{item.value}</strong>
        </article>
      ))}
    </div>
  );
}

function Foldout({ title, note, children, open = false }: { title: string; note?: string; children: ReactNode; open?: boolean }) {
  return (
    <details className="operation-foldout" open={open}>
      <summary>
        <strong>{title}</strong>
        {note ? <span>{note}</span> : null}
      </summary>
      <div className="operation-foldout__body">{children}</div>
    </details>
  );
}

function getMcpCatalogFromCapability(catalog: CapabilitySystemCatalog | null): MCPManagementCatalog | null {
  const value = catalog?.mcp_management;
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as unknown as MCPManagementCatalog;
}

export function CapabilitySystemWorkbench() {
  const [catalog, setCatalog] = useState<CapabilitySystemCatalog | null>(null);
  const [activePage, setActivePage] = useState<CapabilityPage>("overview");
  const [query, setQuery] = useState("");
  const [selectedUnitId, setSelectedUnitId] = useState("");
  const [selectedSkillName, setSelectedSkillName] = useState("");
  const [selectedToolName, setSelectedToolName] = useState("");
  const [selectedServerKey, setSelectedServerKey] = useState("");
  const [selectedMcpToolKey, setSelectedMcpToolKey] = useState("");
  const [selectedEndpointId, setSelectedEndpointId] = useState("");
  const [skillDraft, setSkillDraft] = useState("");
  const [skillEditing, setSkillEditing] = useState(false);
  const [promptDraft, setPromptDraft] = useState({ title: "", capability: "", use_when: "", output_rule: "" });
  const [promptEditing, setPromptEditing] = useState(false);
  const [newSkill, setNewSkill] = useState({ name: "", title: "", description: "" });
  const [toolBoundaryFilter, setToolBoundaryFilter] = useState("全部边界");
  const [toolRiskFilter, setToolRiskFilter] = useState("全部风险");
  const [toolNoteDraft, setToolNoteDraft] = useState("");
  const [toolLlmDescriptionDraft, setToolLlmDescriptionDraft] = useState("");
  const [mcpInspections, setMcpInspections] = useState<Record<string, MCPManagementServer>>({});
  const [mcpDraft, setMcpDraft] = useState<ExternalMCPServerConfig>(EMPTY_SERVER);
  const [mcpArgsDraft, setMcpArgsDraft] = useState("");
  const [mcpEnvDraft, setMcpEnvDraft] = useState("{}");
  const [mcpMetadataDraft, setMcpMetadataDraft] = useState("{}");
  const [mcpTagsDraft, setMcpTagsDraft] = useState("");
  const [mcpAllowedDraft, setMcpAllowedDraft] = useState("");
  const [mcpApprovalDraft, setMcpApprovalDraft] = useState("");
  const [mcpDeniedDraft, setMcpDeniedDraft] = useState("");
  const [mcpCallArgsDraft, setMcpCallArgsDraft] = useState("{}");
  const [mcpResult, setMcpResult] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  function openCapabilityPage(page: CapabilityPage) {
    setActivePage(page);
    setQuery("");
  }

  async function loadCatalog(refresh = false) {
    setLoading(true);
    setError("");
    try {
      const payload = refresh ? await refreshCapabilitySystemCatalog() : await getCapabilitySystemCatalog();
      setCatalog(payload);
      setSelectedUnitId((current) => (payload.capability_units ?? []).some((unit) => unit.capability_id === current) ? current : payload.capability_units?.[0]?.capability_id ?? "");
      setSelectedSkillName((current) => payload.skills.some((skill) => skill.runtime.name === current) ? current : payload.skills[0]?.runtime.name ?? "");
      setSelectedToolName((current) => payload.tools.some((tool) => tool.name === current) ? current : payload.tools[0]?.name ?? "");
      const mcpCatalog = getMcpCatalogFromCapability(payload);
      setSelectedServerKey((current) => mcpCatalog?.servers.some((server) => mcpServerKey(server) === current) ? current : mcpCatalog?.servers[0] ? mcpServerKey(mcpCatalog.servers[0]) : "");
      setSelectedEndpointId((current) => (payload.capability_endpoints ?? []).some((endpoint) => endpoint.endpoint_id === current) ? current : payload.capability_endpoints?.[0]?.endpoint_id ?? "");
      if (refresh) setNotice("能力目录已刷新。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加载能力系统失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadCatalog();
  }, []);

  const normalizedQuery = query.trim().toLowerCase();
  const mcpCatalog = getMcpCatalogFromCapability(catalog);
  const allMcpTools = useMemo(() => mergeMcpTools(mcpCatalog, mcpInspections), [mcpCatalog, mcpInspections]);
  const visibleUnits = useMemo(
    () => (catalog?.capability_units ?? []).filter((unit) => !normalizedQuery || unitSearchText(unit).includes(normalizedQuery)),
    [catalog?.capability_units, normalizedQuery],
  );
  const visibleSkills = useMemo(
    () => (catalog?.skills ?? []).filter((skill) => !normalizedQuery || skillSearchText(skill).includes(normalizedQuery)),
    [catalog?.skills, normalizedQuery],
  );
  const toolBoundaryOptions = useMemo(() => ["全部边界", ...Object.keys(catalog?.summary.tool_boundaries ?? {})], [catalog?.summary.tool_boundaries]);
  const toolRiskOptions = useMemo(() => ["全部风险", ...Object.keys(catalog?.summary.tool_risks ?? {})], [catalog?.summary.tool_risks]);
  const visibleTools = useMemo(
    () => (catalog?.tools ?? []).filter((tool) => {
      const matchesQuery = !normalizedQuery || toolSearchText(tool).includes(normalizedQuery);
      const matchesBoundary = toolBoundaryFilter === "全部边界" || tool.operation_metadata.tool_boundary === toolBoundaryFilter;
      const matchesRisk = toolRiskFilter === "全部风险" || tool.operation_metadata.risk_level === toolRiskFilter;
      return matchesQuery && matchesBoundary && matchesRisk;
    }),
    [catalog?.tools, normalizedQuery, toolBoundaryFilter, toolRiskFilter],
  );
  const visibleMcpServers = useMemo(
    () => (mcpCatalog?.servers ?? []).filter((server) => !normalizedQuery || mcpServerSearchText(server).includes(normalizedQuery)),
    [mcpCatalog?.servers, normalizedQuery],
  );
  const visibleMcpTools = useMemo(
    () => allMcpTools.filter((tool) => !normalizedQuery || mcpToolSearchText(tool).includes(normalizedQuery)),
    [allMcpTools, normalizedQuery],
  );
  const visibleEndpoints = useMemo(
    () => (catalog?.capability_endpoints ?? []).filter((endpoint) => !normalizedQuery || endpointSearchText(endpoint).includes(normalizedQuery)),
    [catalog?.capability_endpoints, normalizedQuery],
  );

  const selectedUnit = (catalog?.capability_units ?? []).find((unit) => unit.capability_id === selectedUnitId) ?? visibleUnits[0] ?? null;
  const selectedSkill = (catalog?.skills ?? []).find((skill) => skill.runtime.name === selectedSkillName) ?? visibleSkills[0] ?? null;
  const selectedTool = (catalog?.tools ?? []).find((tool) => tool.name === selectedToolName) ?? visibleTools[0] ?? null;
  const selectedServer = mcpCatalog?.servers.find((server) => mcpServerKey(server) === selectedServerKey) ?? null;
  const selectedInspection = selectedServer ? mcpInspections[mcpServerKey(selectedServer)] ?? null : null;
  const effectiveServer = selectedInspection ?? selectedServer;
  const selectedMcpTool = visibleMcpTools.find((tool) => `${tool.provider_id}:${tool.server_id}:${tool.tool_name}` === selectedMcpToolKey)
    ?? visibleMcpTools.find((tool) => effectiveServer && tool.provider_id === effectiveServer.provider_id && tool.server_id === effectiveServer.server_id)
    ?? visibleMcpTools[0]
    ?? null;
  const selectedEndpoint = (catalog?.capability_endpoints ?? []).find((endpoint) => endpoint.endpoint_id === selectedEndpointId) ?? visibleEndpoints[0] ?? null;
  const isExternalServer = effectiveServer?.provider_kind === "external";
  const isNewExternal = !effectiveServer && mcpDraft.server_id.trim().length > 0;
  const selectedServerTools = allMcpTools.filter((tool) => effectiveServer && tool.provider_id === effectiveServer.provider_id && tool.server_id === effectiveServer.server_id);

  useEffect(() => {
    if (!selectedSkill || skillEditing) return;
    setSkillDraft(selectedSkill.content);
  }, [selectedSkill, skillEditing]);

  useEffect(() => {
    if (!selectedSkill || promptEditing) return;
    setPromptDraft({
      title: selectedSkill.prompt_view.title || "",
      capability: selectedSkill.prompt_view.capability || "",
      use_when: selectedSkill.prompt_view.use_when || "",
      output_rule: selectedSkill.prompt_view.output_rule || "",
    });
  }, [selectedSkill, promptEditing]);

  useEffect(() => {
    setToolNoteDraft(selectedTool?.operation_metadata.note ?? "");
    setToolLlmDescriptionDraft(selectedTool?.operation_metadata.llm_description ?? "");
  }, [selectedTool?.name, selectedTool?.operation_metadata.llm_description, selectedTool?.operation_metadata.note]);

  useEffect(() => {
    const external = externalConfigFromServer(effectiveServer);
    setMcpDraft(external);
    setMcpArgsDraft(external.args.join("\n"));
    setMcpEnvDraft(jsonText(external.env));
    setMcpMetadataDraft(jsonText(external.metadata));
    setMcpTagsDraft(external.tags.join("\n"));
    setMcpAllowedDraft(external.allowed_operations.join("\n"));
    setMcpApprovalDraft(external.requires_approval_operations.join("\n"));
    setMcpDeniedDraft(external.denied_operations.join("\n"));
    setMcpResult("");
  }, [effectiveServer]);

  async function saveSkill() {
    if (!selectedSkill) return;
    setSaving(`skill:${selectedSkill.runtime.name}`);
    setError("");
    try {
      const payload = await saveCapabilitySystemSkill(selectedSkill.runtime.name, skillDraft);
      setCatalog(payload);
      setSkillEditing(false);
      setNotice(`${selectedSkill.runtime.title || selectedSkill.runtime.name} 已保存。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存 skill 失败");
    } finally {
      setSaving("");
    }
  }

  async function saveSkillPromptView() {
    if (!selectedSkill) return;
    setSaving(`prompt:${selectedSkill.runtime.name}`);
    setError("");
    try {
      const payload = await updateCapabilitySystemSkillPromptView(selectedSkill.runtime.name, promptDraft);
      setCatalog(payload);
      setPromptEditing(false);
      setNotice(`${selectedSkill.runtime.title || selectedSkill.runtime.name} 的模型提示已保存。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存模型提示失败");
    } finally {
      setSaving("");
    }
  }

  async function createSkill() {
    if (!newSkill.name.trim() || !newSkill.title.trim() || !newSkill.description.trim()) {
      setError("请填写 skill 名称、标题和描述。");
      return;
    }
    setSaving("create-skill");
    setError("");
    try {
      const payload = await createCapabilitySystemSkill({
        ...newSkill,
        content: defaultSkillDraft(newSkill.name.trim(), newSkill.title.trim(), newSkill.description.trim()),
      });
      setCatalog(payload);
      setSelectedSkillName(newSkill.name.trim());
      setNewSkill({ name: "", title: "", description: "" });
      setSkillEditing(true);
      openCapabilityPage("skills");
      setNotice("新 skill 已创建。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "新建 skill 失败");
    } finally {
      setSaving("");
    }
  }

  async function removeSkill(skill: OperationSkill) {
    const ok = window.confirm(`确定删除「${skill.runtime.title || skill.runtime.name}」吗？这会删除对应 skill 目录。`);
    if (!ok) return;
    setSaving(`delete:${skill.runtime.name}`);
    setError("");
    try {
      const payload = await deleteCapabilitySystemSkill(skill.runtime.name);
      setCatalog(payload);
      setSelectedSkillName(payload.skills[0]?.runtime.name ?? "");
      setSkillEditing(false);
      setNotice("skill 已删除。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "删除 skill 失败");
    } finally {
      setSaving("");
    }
  }

  async function changeToolType(tool: OperationTool, toolType: string) {
    setSaving(`tool:${tool.name}`);
    setError("");
    try {
      const payload = await updateCapabilitySystemTool(tool.name, {
        tool_type: toolType,
        note: tool.operation_metadata.note,
        llm_description: tool.operation_metadata.llm_description,
      });
      setCatalog(payload);
      setNotice(`${tool.name} 已归入「${toolType}」。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存工具类型失败");
    } finally {
      setSaving("");
    }
  }

  async function saveToolNote(tool: OperationTool) {
    setSaving(`tool-note:${tool.name}`);
    setError("");
    try {
      const payload = await updateCapabilitySystemTool(tool.name, {
        tool_type: tool.operation_metadata.tool_type,
        note: toolNoteDraft,
        llm_description: toolLlmDescriptionDraft,
      });
      setCatalog(payload);
      setNotice(`${tool.name} 的管理备注已保存。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存工具备注失败");
    } finally {
      setSaving("");
    }
  }

  async function inspectSelectedMcpServer() {
    if (!effectiveServer) return;
    setLoading(true);
    setError("");
    try {
      const snapshot = await inspectMCPManagementServer(effectiveServer.provider_id, effectiveServer.server_id);
      setMcpInspections((current) => ({ ...current, [mcpServerKey(snapshot)]: snapshot }));
      setNotice(`发现完成：${snapshot.title || snapshot.server_id} / ${statusLabel(snapshot.status)}`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "发现 MCP server 失败");
    } finally {
      setLoading(false);
    }
  }

  async function saveMcpServer() {
    setSaving("mcp-server");
    setError("");
    try {
      const payload: ExternalMCPServerConfig = {
        ...mcpDraft,
        args: splitLines(mcpArgsDraft),
        env: parseJsonObject(mcpEnvDraft, "环境变量") as Record<string, string>,
        metadata: parseJsonObject(mcpMetadataDraft, "元数据"),
        tags: splitLines(mcpTagsDraft),
        allowed_operations: splitLines(mcpAllowedDraft),
        requires_approval_operations: splitLines(mcpApprovalDraft),
        denied_operations: splitLines(mcpDeniedDraft),
      };
      if (!payload.server_id.trim()) throw new Error("服务器 ID 不能为空");
      const nextMcpCatalog = await upsertMCPManagementExternalServer(payload.server_id, payload);
      const nextCatalog = await refreshCapabilitySystemCatalog();
      setCatalog({ ...nextCatalog, mcp_management: nextMcpCatalog as unknown as Record<string, unknown> });
      setSelectedServerKey(`external:${payload.server_id}`);
      setNotice("MCP 配置已保存。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存 MCP 配置失败");
    } finally {
      setSaving("");
    }
  }

  async function removeMcpServer(serverId: string) {
    setSaving("mcp-delete");
    setError("");
    try {
      const nextMcpCatalog = await deleteMCPManagementExternalServer(serverId);
      const nextCatalog = await refreshCapabilitySystemCatalog();
      setCatalog({ ...nextCatalog, mcp_management: nextMcpCatalog as unknown as Record<string, unknown> });
      setSelectedServerKey(nextMcpCatalog.servers[0] ? mcpServerKey(nextMcpCatalog.servers[0]) : "");
      setNotice("MCP 配置已删除。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "删除 MCP 配置失败");
    } finally {
      setSaving("");
    }
  }

  async function previewMcpTool(tool: MCPManagementTool) {
    setLoading(true);
    setError("");
    try {
      const payload = await previewMCPManagementTool(tool.provider_id, tool.server_id, tool.tool_name, parseJsonObject(mcpCallArgsDraft, "调用参数"));
      setMcpResult(jsonText(payload));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "权限预检失败");
    } finally {
      setLoading(false);
    }
  }

  async function callMcpTool(tool: MCPManagementTool) {
    setLoading(true);
    setError("");
    try {
      const payload = await callMCPManagementTool(tool.provider_id, tool.server_id, tool.tool_name, parseJsonObject(mcpCallArgsDraft, "调用参数"));
      setMcpResult(jsonText(payload));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "调用 MCP tool 失败");
    } finally {
      setLoading(false);
    }
  }

  function renderOverview() {
    const summary = catalog?.summary;
    const mcpSummary = mcpCatalog?.summary;
    const issues = catalog?.validation_issues ?? [];
    const cards = GROUPS.map((group) => {
      if (group.id === "skills") {
        return {
          ...group,
          value: catalog?.skills.length ?? 0,
          meta: `${summary?.model_visible_skills ?? 0} 个模型可见`,
          facts: [
            { label: "可编辑", value: "SKILL.md" },
            { label: "重点", value: "prompt 合同" },
          ],
        };
      }
      if (group.id === "tools") {
        return {
          ...group,
          value: catalog?.tools.length ?? 0,
          meta: `${summary?.tool_risks?.["高"] ?? 0} 个高风险`,
          facts: [
            { label: "边界", value: Object.keys(summary?.tool_boundaries ?? {}).length || 0 },
            { label: "类型", value: summary?.tool_types?.length ?? 0 },
          ],
        };
      }
      if (group.id === "mcp") {
        return {
          ...group,
          value: mcpSummary?.server_count ?? 0,
          meta: `${mcpSummary?.tool_count ?? 0} 个 MCP tool`,
          facts: [
            { label: "外部", value: mcpSummary?.external_server_count ?? 0 },
            { label: "端点", value: catalog?.capability_endpoints?.length ?? 0 },
          ],
        };
      }
      return {
        ...group,
        value: catalog?.capability_units?.length ?? 0,
        meta: `${summary?.validation_error_count ?? 0} 个错误`,
        facts: [
          { label: "Operations", value: summary?.operation_count ?? catalog?.operations?.length ?? 0 },
          { label: "问题", value: summary?.validation_issue_count ?? issues.length },
        ],
      };
    });
    return (
      <section className="capability-overview">
        <div className="capability-overview-bar">
          <div>
            <strong>能力群</strong>
            <span>从用途进入管理页，MCP 与端点在服务接入里统一处理。</span>
          </div>
          <div className="capability-overview-bar__stats">
            <span>{summary?.operation_count ?? catalog?.operations?.length ?? 0} operations</span>
            <span>{summary?.validation_issue_count ?? 0} issues</span>
          </div>
        </div>

        <div className="capability-group-grid">
          {cards.map((card) => {
            const Icon = card.icon;
            return (
              <button className="capability-group-card" key={card.id} onClick={() => openCapabilityPage(card.id)} type="button">
                <span className="capability-group-card__icon"><Icon size={18} /></span>
                <span className="capability-group-card__copy">
                  <span>{card.source}</span>
                  <strong>{card.title}</strong>
                  <em>{card.detail}</em>
                  <i>{card.action}</i>
                </span>
                <span className="capability-group-card__metric">
                  <strong>{card.value}</strong>
                  <em>{card.meta}</em>
                  <span>
                    {card.facts.map((fact) => `${fact.label} ${fact.value}`).join(" · ")}
                  </span>
                </span>
              </button>
            );
          })}
        </div>

        {issues.length ? <section className="capability-issue-panel">
          <div className="capability-page-head">
            <div>
              <strong>结构校验</strong>
              <span>只显示会影响能力判断的问题。</span>
            </div>
          </div>
          <div className="capability-issue-list">
            {issues.slice(0, 8).map((issue, index) => (
              <article key={`${issue.code}-${issue.subject}-${index}`}>
                <span>{issue.severity}</span>
                <strong>{issue.code}</strong>
                <p>{issue.message}</p>
              </article>
            ))}
          </div>
        </section> : null}
      </section>
    );
  }

  function renderUnits() {
    return (
      <section className="operation-layout operation-layout--units">
        <div className="operation-list">
          {visibleUnits.map((unit) => (
            <button
              className={`operation-unit-card ${selectedUnit?.capability_id === unit.capability_id ? "operation-unit-card--active" : ""}`}
              key={unit.capability_id}
              onClick={() => setSelectedUnitId(unit.capability_id)}
              type="button"
            >
              <span>{unit.kind} · {unit.provider_kind}</span>
              <strong>{unit.title || unit.capability_id}</strong>
              <p>{unit.operation_ids.join(" / ") || "未声明 operation"}</p>
            </button>
          ))}
        </div>
        <article className="operation-detail">
          {selectedUnit ? (
            <>
              <div className="operation-detail__head">
                <div>
                  <span>{selectedUnit.kind} · {selectedUnit.capability_id}</span>
                  <h3>{selectedUnit.title || selectedUnit.capability_id}</h3>
                  <p>{selectedUnit.summary || "暂无说明"}</p>
                </div>
                <div className={`operation-risk-badge ${selectedUnit.status === "active" ? "operation-risk--low" : "operation-risk--medium"}`}>
                  <ShieldCheck size={16} />
                  {selectedUnit.status || "unknown"}
                </div>
              </div>
              <FactGrid
                columns={4}
                items={[
                  { label: "Operations", value: selectedUnit.operation_ids.join(" / ") || "未声明" },
                  { label: "Provider", value: selectedUnit.provider || "未配置" },
                  { label: "Visibility", value: selectedUnit.model_visibility || selectedUnit.runtime_visibility || "未配置" },
                  { label: "Health", value: selectedUnit.health?.reason || selectedUnit.health?.status || "active" },
                ]}
              />
              <FactGrid
                columns={4}
                items={[
                  { label: "Profile", value: selectedUnit.permission_view?.profile_state ?? "unknown" },
                  { label: "Turn", value: selectedUnit.permission_view?.adoption_state ?? "not_checked" },
                  { label: "Gate", value: selectedUnit.permission_view?.gate_state ?? "not_checked" },
                  { label: "Approval", value: selectedUnit.permission_view?.approval_state ?? "not_required" },
                ]}
              />
              <Foldout title="依赖 / 风险 / 来源" note="治理视图">
                <div className="operation-inline-stack">
                  <article>
                    <strong>依赖</strong>
                    {selectedUnit.dependencies.length ? (
                      <div className="workspace-chip-row">
                        {selectedUnit.dependencies.map((dependency) => (
                          <span className="workspace-mini-chip" key={`${dependency.relation}:${dependency.to_id}`}>
                            {dependency.relation}: {dependency.to_id}
                          </span>
                        ))}
                      </div>
                    ) : <p>没有声明依赖。</p>}
                  </article>
                  <article>
                    <strong>风险标签</strong>
                    <p>{selectedUnit.risk.join(" / ") || "未标注"}</p>
                  </article>
                  <article>
                    <strong>源码来源</strong>
                    <p>{selectedUnit.source_ref || "未配置"}</p>
                  </article>
                </div>
              </Foldout>
              <Foldout title="权限与健康 JSON" note="调试">
                <div className="operation-json-stack">
                  <article><strong>权限视图</strong><pre>{jsonText(selectedUnit.permission_view)}</pre></article>
                  <article><strong>健康诊断</strong><pre>{jsonText(selectedUnit.health)}</pre></article>
                  <article><strong>展示标签</strong><pre>{jsonText(selectedUnit.display_facets)}</pre></article>
                </div>
              </Foldout>
            </>
          ) : <div className="workspace-alert">暂无能力单元。</div>}
        </article>
      </section>
    );
  }

  function renderSkills() {
    return (
      <section className="operation-layout">
        <div className="operation-list">
          <Foldout title="新建 Skill" note="最少信息">
            <div className="operation-inline-form">
              <input placeholder="name，例如 pdf-qa" value={newSkill.name} onChange={(event) => setNewSkill((prev) => ({ ...prev, name: event.target.value }))} />
              <input placeholder="中文标题" value={newSkill.title} onChange={(event) => setNewSkill((prev) => ({ ...prev, title: event.target.value }))} />
              <textarea placeholder="一句话描述能力用途" value={newSkill.description} onChange={(event) => setNewSkill((prev) => ({ ...prev, description: event.target.value }))} />
              <button className="action-button action-button--primary" disabled={saving === "create-skill"} onClick={() => void createSkill()} type="button">
                {saving === "create-skill" ? <Loader2 className="animate-spin" size={14} /> : <FilePlus2 size={14} />}
                创建
              </button>
            </div>
          </Foldout>
          {visibleSkills.map((skill) => (
            <button
              className={selectedSkill?.runtime.name === skill.runtime.name ? "operation-skill-card operation-skill-card--active" : "operation-skill-card"}
              key={skill.runtime.name}
              onClick={() => {
                setSelectedSkillName(skill.runtime.name);
                setSkillEditing(false);
              }}
              type="button"
            >
              <span>{skill.runtime.activation_policy || "skill"}</span>
              <strong>{skill.runtime.title || skill.runtime.name}</strong>
              <p>{skill.runtime.preferred_route || compactList(skill.runtime.supported_task_kinds)}</p>
            </button>
          ))}
        </div>
        <article className="operation-detail">
          {selectedSkill ? (
            <>
              <div className="operation-detail__head">
                <div>
                  <span>Skill · {selectedSkill.runtime.name}</span>
                  <h3>{selectedSkill.runtime.title || selectedSkill.runtime.name}</h3>
                  <p>{selectedSkill.runtime.description}</p>
                </div>
                <div className="operation-detail__actions">
                  <button className="action-button action-button--ghost" onClick={() => setSkillEditing((value) => !value)} type="button">
                    <Code2 size={14} />
                    {skillEditing ? "收起" : "编辑"}
                  </button>
                  {skillEditing ? (
                    <button className="action-button action-button--primary" disabled={saving === `skill:${selectedSkill.runtime.name}`} onClick={() => void saveSkill()} type="button">
                      {saving === `skill:${selectedSkill.runtime.name}` ? <Loader2 className="animate-spin" size={14} /> : <Save size={14} />}
                      保存
                    </button>
                  ) : null}
                  <button className="action-button action-button--danger" disabled={saving === `delete:${selectedSkill.runtime.name}`} onClick={() => void removeSkill(selectedSkill)} type="button">
                    <Trash2 size={14} />
                    删除
                  </button>
                </div>
              </div>
              <FactGrid
                columns={4}
                items={[
                  { label: "路径", value: selectedSkill.runtime.path },
                  { label: "路由", value: selectedSkill.runtime.preferred_route || "未配置" },
                  { label: "任务", value: compactList(selectedSkill.runtime.supported_task_kinds) },
                  { label: "上下文", value: selectedSkill.runtime.context_mode || "未配置" },
                ]}
              />
              {selectedSkill.validation_errors.length ? (
                <div className="workspace-alert workspace-alert--danger">统一契约校验未通过：{selectedSkill.validation_errors.join(" / ")}</div>
              ) : null}
              <section className="operation-inline-panel">
                <div className="operation-inline-panel__head">
                  <div><Sparkles size={16} /><strong>模型提示</strong></div>
                  <div className="operation-inline-panel__actions">
                    <button className="action-button action-button--ghost" onClick={() => setPromptEditing((value) => !value)} type="button">
                      <Code2 size={14} />
                      {promptEditing ? "预览" : "编辑"}
                    </button>
                    {promptEditing ? (
                      <button className="action-button action-button--primary" disabled={saving === `prompt:${selectedSkill.runtime.name}`} onClick={() => void saveSkillPromptView()} type="button">
                        {saving === `prompt:${selectedSkill.runtime.name}` ? <Loader2 className="animate-spin" size={14} /> : <Save size={14} />}
                        保存 Prompt
                      </button>
                    ) : null}
                  </div>
                </div>
                {promptEditing ? (
                  <div className="operation-prompt-editor">
                    <label>标题<input value={promptDraft.title} onChange={(event) => setPromptDraft((prev) => ({ ...prev, title: event.target.value }))} /></label>
                    <label>能力说明<textarea value={promptDraft.capability} onChange={(event) => setPromptDraft((prev) => ({ ...prev, capability: event.target.value }))} /></label>
                    <label>使用条件<textarea value={promptDraft.use_when} onChange={(event) => setPromptDraft((prev) => ({ ...prev, use_when: event.target.value }))} /></label>
                    <label>输出规则<textarea value={promptDraft.output_rule} onChange={(event) => setPromptDraft((prev) => ({ ...prev, output_rule: event.target.value }))} /></label>
                  </div>
                ) : <pre>{selectedSkill.prompt_block || "这个 skill 暂无模型可见提示。"}</pre>}
              </section>
              <Foldout title="SKILL.md" note="完整文件" open={skillEditing}>
                <textarea readOnly={!skillEditing} value={skillDraft} onChange={(event) => setSkillDraft(event.target.value)} />
              </Foldout>
            </>
          ) : <div className="workspace-alert">暂无 skill。</div>}
        </article>
      </section>
    );
  }

  function renderTools() {
    return (
      <section className="operation-layout operation-layout--tools">
        <div className="operation-list">
          <div className="operation-tool-filters">
            <select value={toolBoundaryFilter} onChange={(event) => setToolBoundaryFilter(event.target.value)}>
              {toolBoundaryOptions.map((option) => <option key={option} value={option}>{option}</option>)}
            </select>
            <select value={toolRiskFilter} onChange={(event) => setToolRiskFilter(event.target.value)}>
              {toolRiskOptions.map((option) => <option key={option} value={option}>{option}</option>)}
            </select>
          </div>
          {visibleTools.map((tool) => (
            <button
              className={selectedTool?.name === tool.name ? "operation-tool-card operation-tool-card--active" : "operation-tool-card"}
              key={tool.name}
              onClick={() => setSelectedToolName(tool.name)}
              type="button"
            >
              <span>{tool.operation_metadata.tool_type}</span>
              <strong>{tool.display_name || tool.name}</strong>
              <p>{tool.operation_metadata.risk_level}风险 · {tool.operation_id}</p>
            </button>
          ))}
        </div>
        <article className="operation-detail">
          {selectedTool ? (
            <>
              <div className="operation-detail__head">
                <div>
                  <span>Tool · {selectedTool.name}</span>
                  <h3>{selectedTool.display_name || selectedTool.name}</h3>
                  <p>{selectedTool.module} · {selectedTool.operation_id}</p>
                </div>
                <div className={`operation-risk-badge ${RISK_CLASS[selectedTool.operation_metadata.risk_level] ?? ""}`}>
                  <AlertTriangle size={16} />
                  {selectedTool.operation_metadata.risk_level}风险
                </div>
              </div>
              <FactGrid
                columns={4}
                items={[
                  { label: "边界", value: selectedTool.operation_metadata.tool_boundary },
                  { label: "类型", value: selectedTool.operation_metadata.tool_type },
                  { label: "可见性", value: selectedTool.runtime_visibility },
                  { label: "策略", value: selectedTool.operation_metadata.runtime_policy },
                ]}
              />
              <div className="operation-tool-control">
                <label>
                  工具类型
                  <select disabled={saving === `tool:${selectedTool.name}`} onChange={(event) => void changeToolType(selectedTool, event.target.value)} value={selectedTool.operation_metadata.tool_type}>
                    {(catalog?.tool_type_options ?? []).map((type) => <option key={type} value={type}>{type}</option>)}
                  </select>
                </label>
                <label>
                  LLM 调用描述
                  <textarea onChange={(event) => setToolLlmDescriptionDraft(event.target.value)} value={toolLlmDescriptionDraft} />
                </label>
                <label>
                  治理备注
                  <textarea onChange={(event) => setToolNoteDraft(event.target.value)} value={toolNoteDraft} />
                </label>
                <button className="action-button action-button--ghost" disabled={saving === `tool-note:${selectedTool.name}`} onClick={() => void saveToolNote(selectedTool)} type="button">
                  {saving === `tool-note:${selectedTool.name}` ? <Loader2 className="animate-spin" size={14} /> : <Save size={14} />}
                  保存备注
                </button>
              </div>
              <FactGrid
                columns={3}
                items={[
                  { label: "提示暴露", value: selectedTool.prompt_exposure_policy },
                  { label: "资源策略", value: selectedTool.resource_exposure_policy },
                  { label: "自动路由", value: selectedTool.safe_for_auto_route ? "允许" : "需显式触发" },
                ]}
              />
              <Foldout title="执行 / 解析 / 输出契约" note="调试">
                <div className="operation-json-stack">
                  <article><strong>执行契约</strong><pre>{jsonText(selectedTool.contract)}</pre></article>
                  <article><strong>解析契约</strong><pre>{jsonText(selectedTool.resolution_contract)}</pre></article>
                  <article><strong>输出契约</strong><pre>{jsonText(selectedTool.output_contract)}</pre></article>
                </div>
              </Foldout>
            </>
          ) : <div className="workspace-alert">暂无工具。</div>}
        </article>
      </section>
    );
  }

  function renderMcp() {
    return (
      <section className="capability-mcp-page">
        <div className="capability-mcp-rail">
          <div className="capability-page-head">
            <div><strong>Provider</strong><span>{mcpCatalog?.summary.server_count ?? 0} 个 server</span></div>
            <button className="action-button action-button--ghost" onClick={() => {
              setSelectedServerKey("");
              setMcpDraft(EMPTY_SERVER);
            }} type="button">新建外部</button>
          </div>
          <div className="mcp-server-list">
            {visibleMcpServers.map((server) => {
              const active = mcpServerKey(server) === selectedServerKey;
              const tone = statusTone(server.status);
              return (
                <button className={`mcp-server-row ${active ? "mcp-server-row--active" : ""}`} key={mcpServerKey(server)} onClick={() => setSelectedServerKey(mcpServerKey(server))} type="button">
                  <span className={`mcp-server-row__status mcp-status mcp-status--${tone}`} />
                  <span className="mcp-server-row__copy">
                    <strong>{server.title || server.server_id}</strong>
                    <em>{server.provider_kind} / {server.transport} / {statusLabel(server.status)}</em>
                    <small>{server.operation_ids.join(", ") || server.status_reason || "等待发现"}</small>
                  </span>
                </button>
              );
            })}
          </div>
        </div>
        <div className="capability-mcp-main">
          <section className="capability-mcp-section">
            <div className="operation-detail__head">
              <div>
                <span>{effectiveServer ? `${effectiveServer.provider_kind} · ${effectiveServer.server_id}` : "external · new"}</span>
                <h3>{effectiveServer?.title || "外部 MCP 配置"}</h3>
                <p>{effectiveServer?.description || "本地和外部 MCP 在这里统一管理，端点只作为投影展示。"}</p>
              </div>
              <div className="operation-detail__actions">
                <button className="action-button action-button--ghost" disabled={!effectiveServer || loading} onClick={() => void inspectSelectedMcpServer()} type="button">
                  {loading ? <Loader2 className="animate-spin" size={14} /> : <RefreshCw size={14} />}
                  发现
                </button>
              </div>
            </div>
            {isExternalServer || isNewExternal || !effectiveServer ? (
              <div className="mcp-form-grid capability-mcp-form">
                <label><span>服务器 ID</span><input value={mcpDraft.server_id} onChange={(event) => setMcpDraft({ ...mcpDraft, server_id: event.target.value })} /></label>
                <label><span>标题</span><input value={mcpDraft.title} onChange={(event) => setMcpDraft({ ...mcpDraft, title: event.target.value })} /></label>
                <label><span>传输方式</span><select value={mcpDraft.transport} onChange={(event) => setMcpDraft({ ...mcpDraft, transport: event.target.value })}><option value="stdio">stdio</option><option value="streamable_http">streamable_http</option></select></label>
                <label><span>作用域</span><input value={mcpDraft.scope} onChange={(event) => setMcpDraft({ ...mcpDraft, scope: event.target.value })} /></label>
                <label className="mcp-form-wide"><span>启动命令</span><input value={mcpDraft.command} onChange={(event) => setMcpDraft({ ...mcpDraft, command: event.target.value })} /></label>
                <label className="mcp-form-wide"><span>URL</span><input value={mcpDraft.url} onChange={(event) => setMcpDraft({ ...mcpDraft, url: event.target.value })} /></label>
                <label className="mcp-form-wide"><span>工作目录</span><input value={mcpDraft.cwd} onChange={(event) => setMcpDraft({ ...mcpDraft, cwd: event.target.value })} /></label>
                <label className="mcp-form-wide"><span>描述</span><textarea value={mcpDraft.description} onChange={(event) => setMcpDraft({ ...mcpDraft, description: event.target.value })} rows={3} /></label>
                <label><span>参数</span><textarea value={mcpArgsDraft} onChange={(event) => setMcpArgsDraft(event.target.value)} rows={5} /></label>
                <label><span>标签</span><textarea value={mcpTagsDraft} onChange={(event) => setMcpTagsDraft(event.target.value)} rows={5} /></label>
                <label><span>环境变量 JSON</span><textarea value={mcpEnvDraft} onChange={(event) => setMcpEnvDraft(event.target.value)} rows={5} /></label>
                <label><span>元数据 JSON</span><textarea value={mcpMetadataDraft} onChange={(event) => setMcpMetadataDraft(event.target.value)} rows={5} /></label>
                <label><span>默认允许 operation</span><textarea value={mcpAllowedDraft} onChange={(event) => setMcpAllowedDraft(event.target.value)} rows={4} /></label>
                <label><span>需要审批 operation</span><textarea value={mcpApprovalDraft} onChange={(event) => setMcpApprovalDraft(event.target.value)} rows={4} /></label>
                <label className="mcp-form-wide"><span>拒绝 operation</span><textarea value={mcpDeniedDraft} onChange={(event) => setMcpDeniedDraft(event.target.value)} rows={3} /></label>
                <div className="capability-mcp-actions">
                  {isExternalServer ? <button className="action-button action-button--danger" disabled={saving === "mcp-delete"} onClick={() => void removeMcpServer(mcpDraft.server_id)} type="button"><Trash2 size={14} />删除</button> : null}
                  <button className="action-button action-button--primary" disabled={saving === "mcp-server"} onClick={() => void saveMcpServer()} type="button">
                    {saving === "mcp-server" ? <Loader2 className="animate-spin" size={14} /> : <Save size={14} />}
                    保存
                  </button>
                </div>
              </div>
            ) : (
              <>
                <FactGrid
                  columns={4}
                  items={[
                    { label: "Provider", value: effectiveServer.provider_id },
                    { label: "Server", value: effectiveServer.server_id },
                    { label: "Transport", value: effectiveServer.transport },
                    { label: "Status", value: statusLabel(effectiveServer.status) },
                  ]}
                />
                <Foldout title="Provider 诊断" note="调试">
                  <pre>{jsonText(effectiveServer.diagnostics)}</pre>
                </Foldout>
              </>
            )}
          </section>
          <section className="capability-mcp-section">
            <div className="capability-page-head">
              <div><strong>MCP Tools</strong><span>{selectedServerTools.length || visibleMcpTools.length} 个可见 tool</span></div>
            </div>
            <div className="mcp-tool-list capability-mcp-tool-list">
              {(selectedServerTools.length ? selectedServerTools : visibleMcpTools).map((tool) => {
                const key = `${tool.provider_id}:${tool.server_id}:${tool.tool_name}`;
                return (
                  <button className={selectedMcpToolKey === key ? "mcp-tool-row mcp-tool-row--active" : "mcp-tool-row"} key={key} onClick={() => setSelectedMcpToolKey(key)} type="button">
                    <strong>{tool.title || tool.tool_name}</strong>
                    <span>{tool.provider_kind} / {tool.operation_id || "未映射 operation"}</span>
                  </button>
                );
              })}
            </div>
            {selectedMcpTool ? (
              <div className="capability-mcp-call">
                <FactGrid
                  columns={4}
                  items={[
                    { label: "Tool", value: selectedMcpTool.tool_name },
                    { label: "Operation", value: selectedMcpTool.operation_id || "未映射" },
                    { label: "Model", value: selectedMcpTool.model_visibility },
                    { label: "Status", value: statusLabel(selectedMcpTool.status || "not_inspected") },
                  ]}
                />
                <textarea value={mcpCallArgsDraft} onChange={(event) => setMcpCallArgsDraft(event.target.value)} rows={4} />
                <div className="operation-detail__actions">
                  <button className="action-button action-button--ghost" onClick={() => void previewMcpTool(selectedMcpTool)} type="button">预检</button>
                  <button className="action-button action-button--ghost" onClick={() => void callMcpTool(selectedMcpTool)} type="button">调用</button>
                </div>
                {mcpResult ? <pre className="mcp-call-result">{mcpResult}</pre> : null}
                <Foldout title="Schema / Diagnostics" note="调试">
                  <div className="operation-json-stack">
                    <article><strong>Input Schema</strong><pre>{jsonText(selectedMcpTool.input_schema)}</pre></article>
                    <article><strong>Output Schema</strong><pre>{jsonText(selectedMcpTool.output_schema)}</pre></article>
                    <article><strong>Diagnostics</strong><pre>{jsonText(selectedMcpTool.diagnostics)}</pre></article>
                  </div>
                </Foldout>
              </div>
            ) : null}
          </section>
          <section className="capability-mcp-section">
            <div className="capability-page-head">
              <div><strong>端点投影</strong><span>{visibleEndpoints.length} 个 endpoint</span></div>
            </div>
            <div className="capability-endpoint-list">
              {visibleEndpoints.map((endpoint) => (
                <button className={selectedEndpoint?.endpoint_id === endpoint.endpoint_id ? "capability-endpoint-row capability-endpoint-row--active" : "capability-endpoint-row"} key={endpoint.endpoint_id} onClick={() => setSelectedEndpointId(endpoint.endpoint_id)} type="button">
                  <strong>{endpoint.title || endpoint.name}</strong>
                  <span>{endpoint.kind} / {endpoint.operation_id}</span>
                </button>
              ))}
            </div>
            {selectedEndpoint ? (
              <Foldout title={selectedEndpoint.title || selectedEndpoint.name} note={selectedEndpoint.server_name}>
                <FactGrid
                  columns={4}
                  items={[
                    { label: "Operation", value: selectedEndpoint.operation_id },
                    { label: "Lane", value: selectedEndpoint.runtime_lane },
                    { label: "Transport", value: selectedEndpoint.transport },
                    { label: "Model", value: selectedEndpoint.model_visibility },
                  ]}
                />
                <pre>{jsonText({ input_schema: selectedEndpoint.input_schema, output_schema: selectedEndpoint.output_schema, metadata: selectedEndpoint.metadata })}</pre>
              </Foldout>
            ) : null}
          </section>
        </div>
      </section>
    );
  }

  const activePlaceholder = activePage === "mcp" ? "搜索 provider / server / tool / endpoint" :
      activePage === "tools" ? "搜索工具 / operation / 风险" :
        activePage === "skills" ? "搜索 skill / route / prompt" :
          "搜索能力单元 / operation / provider";

  return (
    <div className="workspace-view capability-system-console">
      <header className="workspace-view__header">
        <div>
          <h2 className="workspace-view__title">能力系统</h2>
          <p className="workspace-view__subtitle">按能力用途进入管理页；服务接入里统一处理本地和外部 MCP。</p>
        </div>
        <div className="workspace-view__actions">
          {activePage !== "overview" ? (
            <button className="action-button action-button--ghost" onClick={() => openCapabilityPage("overview")} type="button">
              返回总览
            </button>
          ) : null}
          <button className="action-button action-button--ghost" onClick={() => void loadCatalog(true)} type="button">
            {loading ? <Loader2 className="animate-spin" size={15} /> : <RefreshCw size={15} />}
            刷新目录
          </button>
        </div>
      </header>

      {error ? <div className="workspace-alert workspace-alert--danger">{error}</div> : null}
      {notice ? <div className="workspace-alert">{notice}</div> : null}

      {activePage !== "overview" ? (
        <nav className="operation-switcher" aria-label="能力系统分类">
          {GROUPS.map((item) => {
            const Icon = item.icon;
            return (
              <button className={activePage === item.id ? "operation-switcher__item operation-switcher__item--active" : "operation-switcher__item"} key={item.id} onClick={() => openCapabilityPage(item.id)} type="button">
                <span className="operation-switcher__icon"><Icon size={16} /></span>
                <strong>{item.title}</strong>
                <span>{item.detail}</span>
              </button>
            );
          })}
        </nav>
      ) : null}

      {activePage !== "overview" ? (
        <div className="workspace-search">
          <Search size={17} />
          <input onChange={(event) => setQuery(event.target.value)} placeholder={activePlaceholder} value={query} />
        </div>
      ) : null}

      {activePage === "overview" ? renderOverview() :
        activePage === "units" ? renderUnits() :
          activePage === "skills" ? renderSkills() :
            activePage === "tools" ? renderTools() :
              renderMcp()}
    </div>
  );
}
