"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Database,
  FileCog,
  Gauge,
  KeyRound,
  Layers3,
  Loader2,
  Network,
  RotateCcw,
  Save,
  ServerCog,
  ShieldCheck,
  Settings2
} from "lucide-react";

import {
  getCapabilitySystemCatalog,
  getRuntimeConfigConsole,
  setContextBudgetPreset,
  setRuntimeConfigGroup,
  type ContextBudgetConfig,
  type ContextBudgetPreset,
  type CapabilitySystemCatalog,
  type RuntimeConfigConsole,
  type RuntimeConfigField,
  type RuntimeConfigGroup
} from "@/lib/api";

type SystemConfigGroupId = "model" | "embedding" | "retrieval" | "document" | "runtime" | "context" | "capabilities";

const CONFIG_SECTIONS: Array<{
  id: SystemConfigGroupId;
  icon: typeof Settings2;
  accent: string;
}> = [
  { id: "model", icon: ServerCog, accent: "主模型" },
  { id: "embedding", icon: Layers3, accent: "向量化" },
  { id: "retrieval", icon: Database, accent: "RAG" },
  { id: "document", icon: FileCog, accent: "解析" },
  { id: "runtime", icon: Gauge, accent: "边界" },
  { id: "context", icon: Settings2, accent: "上下文" },
  { id: "capabilities", icon: ShieldCheck, accent: "能力治理" }
];

function fieldInitialValue(field: RuntimeConfigField) {
  if (field.type === "secret") return "";
  if (field.type === "boolean") return Boolean(field.value);
  if (field.type === "number") return Number(field.value ?? 0);
  return String(field.value ?? "");
}

function buildDraft(group: RuntimeConfigGroup | null) {
  if (!group) return {};
  return Object.fromEntries(group.fields.map((field) => [field.key, fieldInitialValue(field)]));
}

function formatTokens(value: number) {
  return new Intl.NumberFormat("zh-CN").format(value);
}

function contextMetadata(group: RuntimeConfigGroup | null): ContextBudgetConfig | null {
  if (!group?.metadata) return null;
  return group.metadata as unknown as ContextBudgetConfig;
}

function fieldTone(field: RuntimeConfigField) {
  if (field.key.startsWith("fallback_")) return "备用模型";
  if (field.key.startsWith("rerank_api_") || field.key === "rerank_api_key") return "API";
  if (field.key.startsWith("rerank_local_") || ["rerank_device", "rerank_batch_size", "rerank_max_length"].includes(field.key)) return "本地";
  if (field.key.startsWith("rerank_")) return "Rerank";
  return field.source === "runtime_override" ? "运行时覆盖" : "env / 默认值";
}

export function SystemConfigView() {
  const [consoleConfig, setConsoleConfig] = useState<RuntimeConfigConsole | null>(null);
  const [capabilityCatalog, setCapabilityCatalog] = useState<CapabilitySystemCatalog | null>(null);
  const [activeGroupId, setActiveGroupId] = useState<SystemConfigGroupId>("model");
  const [draft, setDraft] = useState<Record<string, string | number | boolean>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const groups = useMemo(() => consoleConfig?.groups ?? [], [consoleConfig]);
  const activeGroup = useMemo(
    () => groups.find((group) => group.group_id === activeGroupId) ?? groups[0] ?? null,
    [activeGroupId, groups]
  );
  const budgetConfig = contextMetadata(activeGroup);
  const sectionMeta = CONFIG_SECTIONS.find((section) => section.id === activeGroupId) ?? CONFIG_SECTIONS[0];
  const overriddenCount = groups.reduce(
    (count, group) => count + group.fields.filter((field) => field.source === "runtime_override").length,
    0
  );

  const refreshConfig = useCallback(async (options: { silent?: boolean } = {}) => {
    if (!options.silent) setLoading(true);
    setError("");
    try {
      const payload = await getRuntimeConfigConsole();
      setConsoleConfig(payload);
      const nextGroup =
        payload.groups.find((group) => group.group_id === activeGroupId)
        ?? payload.groups[0]
        ?? null;
      if (nextGroup && nextGroup.group_id !== activeGroupId) {
        setActiveGroupId(nextGroup.group_id as SystemConfigGroupId);
      }
      setDraft(buildDraft(nextGroup));
      const catalog = await getCapabilitySystemCatalog();
      setCapabilityCatalog(catalog);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加载系统配置失败");
    } finally {
      if (!options.silent) setLoading(false);
    }
  }, [activeGroupId]);

  useEffect(() => {
    void refreshConfig();
  }, [refreshConfig]);

  useEffect(() => {
    setDraft(buildDraft(activeGroup));
  }, [activeGroup]);

  async function saveGroup() {
    if (!activeGroup || activeGroup.group_id === "context") return;
    setSaving(true);
    setNotice("");
    setError("");
    try {
      const payload = await setRuntimeConfigGroup(activeGroup.group_id, draft);
      setConsoleConfig(payload);
      const nextGroup = payload.groups.find((group) => group.group_id === activeGroup.group_id) ?? null;
      setDraft(buildDraft(nextGroup));
      setNotice(`已保存「${activeGroup.title}」`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存系统配置失败");
    } finally {
      setSaving(false);
    }
  }

  async function chooseBudgetPreset(preset: ContextBudgetPreset) {
    setSaving(true);
    setNotice("");
    setError("");
    try {
      await setContextBudgetPreset(preset.preset_id);
      await refreshConfig({ silent: true });
      setNotice(`已切换上下文预算：${preset.title}`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "切换上下文预算失败");
    } finally {
      setSaving(false);
    }
  }

  function renderField(field: RuntimeConfigField) {
    const value = draft[field.key] ?? fieldInitialValue(field);
    if (field.type === "select") {
      return (
        <select
          value={String(value)}
          onChange={(event) => setDraft((current) => ({ ...current, [field.key]: event.target.value }))}
        >
          {(field.options ?? []).map((option) => (
            <option key={option} value={option}>{option}</option>
          ))}
        </select>
      );
    }
    if (field.type === "boolean") {
      return (
        <button
          aria-pressed={Boolean(value)}
          className={`system-config-toggle ${value ? "system-config-toggle--on" : ""}`}
          onClick={() => setDraft((current) => ({ ...current, [field.key]: !Boolean(value) }))}
          type="button"
        >
          <span />
          {value ? "开启" : "关闭"}
        </button>
      );
    }
    return (
      <input
        type={field.type === "secret" ? "password" : field.type}
        value={String(value)}
        onChange={(event) => {
          const nextValue = field.type === "number" ? Number(event.target.value) : event.target.value;
          setDraft((current) => ({ ...current, [field.key]: nextValue }));
        }}
        placeholder={field.type === "secret" && field.configured ? "已配置；留空则保持不变" : field.label}
      />
    );
  }

  function visibleFields(group: RuntimeConfigGroup | null) {
    const fields = group?.fields ?? [];
    if (group?.group_id !== "retrieval") return fields;
    const mode = String(draft.rerank_mode ?? "disabled");
    return fields.filter((field) => {
      if (["rerank_local_model", "rerank_device", "rerank_batch_size", "rerank_max_length"].includes(field.key)) {
        return mode === "local";
      }
      if (["rerank_api_provider", "rerank_api_model", "rerank_api_base_url", "rerank_api_key"].includes(field.key)) {
        return mode === "api";
      }
      return !["rerank_enabled", "rerank_provider", "rerank_model", "rerank_base_url"].includes(field.key);
    });
  }

  function groupedFields(group: RuntimeConfigGroup | null) {
    const fields = visibleFields(group);
    if (group?.group_id === "model") {
      return [
        { title: "主模型", fields: fields.filter((field) => !field.key.startsWith("fallback_")) },
        { title: "备用模型", fields: fields.filter((field) => field.key.startsWith("fallback_")) }
      ].filter((section) => section.fields.length);
    }
    if (group?.group_id === "retrieval") {
      const mode = String(draft.rerank_mode ?? "disabled");
      return [
        { title: "检索后端", fields: fields.filter((field) => !field.key.startsWith("rerank_")) },
        { title: mode === "api" ? "Rerank API" : mode === "local" ? "本地 Rerank 模型" : "Rerank 模式", fields: fields.filter((field) => field.key.startsWith("rerank_")) }
      ].filter((section) => section.fields.length);
    }
    return [{ title: group?.title ?? "配置项", fields }];
  }

  const capabilitySummary = capabilityCatalog?.summary;
  const validationIssues = capabilityCatalog?.validation_issues ?? [];
  const mainVisibleTools = (capabilityCatalog?.tools ?? []).filter(
    (tool) => tool.runtime_visibility === "main_runtime" && tool.prompt_exposure_policy === "schema_only"
  );
  const internalTools = (capabilityCatalog?.tools ?? []).filter((tool) => tool.runtime_visibility === "agent_internal");
  const highRiskTools = (capabilityCatalog?.tools ?? []).filter((tool) => ["高", "极高"].includes(tool.operation_metadata.risk_level));

  function renderCapabilitiesPanel() {
    if (!capabilityCatalog) {
      return (
        <div className="workspace-alert">
          <Loader2 className="spin" size={16} />
          正在加载能力治理目录...
        </div>
      );
    }
    return (
      <div className="system-config-capabilities">
        <div className="system-config-capability-metrics">
          <article>
            <span>Tools</span>
            <strong>{capabilitySummary?.tool_count ?? capabilityCatalog.tools.length}</strong>
            <em>{mainVisibleTools.length} 个可进入主模型工具面</em>
          </article>
          <article>
            <span>Endpoints</span>
            <strong>{capabilitySummary?.capability_endpoint_count ?? capabilityCatalog.capability_endpoints?.length ?? 0}</strong>
            <em>当前为本地 worker 端点，后续可并入外部 MCP</em>
          </article>
          <article>
            <span>Operations</span>
            <strong>{capabilitySummary?.operation_count ?? capabilityCatalog.operations?.length ?? 0}</strong>
            <em>ResourcePolicy 授权原子</em>
          </article>
          <article>
            <span>Validation</span>
            <strong>{validationIssues.length}</strong>
            <em>{capabilitySummary?.validation_error_count ?? 0} 个错误</em>
          </article>
        </div>

        <section className="system-config-field-section">
          <div className="system-config-field-section__head">
            <strong>模型可见工具面</strong>
            <em>只有 ResourcePolicy 放行后才会注入模型。</em>
          </div>
          <div className="system-config-tool-list">
            {mainVisibleTools.map((tool) => (
              <article key={tool.name}>
                <span><Network size={14} /> {tool.name}</span>
                <strong>{tool.operation_id}</strong>
                <em>{tool.operation_metadata.tool_boundary} / {tool.operation_metadata.risk_level}</em>
              </article>
            ))}
          </div>
        </section>

        <section className="system-config-field-section">
          <div className="system-config-field-section__head">
            <strong>内部与高风险工具</strong>
            <em>不会直接进入主模型工具面，需专门 lane 或审批。</em>
          </div>
          <div className="system-config-tool-list system-config-tool-list--compact">
            {[...internalTools, ...highRiskTools.filter((tool) => !internalTools.some((item) => item.name === tool.name))].map((tool) => (
              <article key={tool.name}>
                <span><ShieldCheck size={14} /> {tool.name}</span>
                <strong>{tool.operation_id}</strong>
                <em>{tool.prompt_exposure_policy} / {tool.operation_metadata.risk_level}</em>
              </article>
            ))}
          </div>
        </section>

        <section className="system-config-field-section">
          <div className="system-config-field-section__head">
            <strong>结构校验</strong>
            <em>启动和目录刷新时应保持无 error。</em>
          </div>
          {validationIssues.length ? (
            <div className="system-config-issue-list">
              {validationIssues.slice(0, 8).map((issue, index) => (
                <article key={`${issue.code}-${issue.subject}-${index}`}>
                  <span>{issue.severity}</span>
                  <strong>{issue.code}</strong>
                  <p>{issue.message}</p>
                </article>
              ))}
            </div>
          ) : (
            <div className="workspace-alert">能力目录校验通过。</div>
          )}
        </section>
      </div>
    );
  }

  return (
    <div className="workspace-view system-config-workbench">
      <header className="workspace-view__header">
        <div>
          <p className="workspace-view__eyebrow">Runtime Config Workbench</p>
          <h2 className="workspace-view__title">系统配置</h2>
          <p className="workspace-view__subtitle">管理模型、上下文、检索、文档解析和运行限制；保存到运行时覆盖配置，`.env` 仍作为底座。</p>
        </div>
        <div className="workspace-view__actions">
          <button className="action-button" disabled={loading || saving} onClick={() => void refreshConfig()} type="button">
            {loading ? <Loader2 className="spin" size={16} /> : <RotateCcw size={16} />}
            刷新
          </button>
        </div>
      </header>

      {error ? <div className="workspace-alert workspace-alert--danger">{error}</div> : null}
      {notice ? <div className="workspace-alert">{notice}</div> : null}
      {loading ? (
        <div className="workspace-alert">
          <Loader2 className="spin" size={16} />
          正在加载系统配置...
        </div>
      ) : null}

      <section className="system-config-overview">
        <article>
          <span>Active Panel</span>
          <strong>{activeGroup?.title ?? "未加载"}</strong>
          <em>{activeGroup?.status ?? "等待配置"}</em>
        </article>
        <article>
          <span>Runtime Overrides</span>
          <strong>{overriddenCount}</strong>
          <em>当前由前端配置覆盖的字段</em>
        </article>
        <article>
          <span>Secret Policy</span>
          <strong>不回显密钥</strong>
          <em>新密钥只在保存时写入</em>
        </article>
      </section>

      <div className="system-config-layout">
        <aside className="system-config-nav">
          {CONFIG_SECTIONS.map((section) => {
            const group = groups.find((item) => item.group_id === section.id);
            const Icon = section.icon;
            return (
              <button
                className={`system-config-nav__item ${activeGroupId === section.id ? "system-config-nav__item--active" : ""}`}
                key={section.id}
                onClick={() => setActiveGroupId(section.id)}
                type="button"
              >
                <span className="system-config-nav__icon"><Icon size={17} /></span>
                <span>
                  <em>{section.accent}</em>
                  <strong>{section.id === "capabilities" ? "能力治理" : group?.title ?? section.id}</strong>
                  <small>{section.id === "capabilities" ? `${validationIssues.length} 个校验项` : group?.status ?? "未加载"}</small>
                </span>
              </button>
            );
          })}
        </aside>

        <section className="system-config-editor">
          <div className="system-config-editor__head">
            <div className="system-config-editor__mark">
              <sectionMeta.icon size={20} />
            </div>
            <div>
              <span>{sectionMeta.accent}</span>
              <strong>{activeGroup?.title ?? "配置项"}</strong>
              <p>{activeGroup?.description ?? "选择左侧配置条目进行管理。"}</p>
            </div>
          </div>

          {activeGroupId === "capabilities" ? renderCapabilitiesPanel() : activeGroup?.group_id === "context" && budgetConfig ? (
            <div className="system-config-budget-grid">
              {budgetConfig.presets.map((preset) => (
                <button
                  className={`system-config-budget ${preset.preset_id === budgetConfig.preset_id ? "system-config-budget--active" : ""}`}
                  disabled={saving}
                  key={preset.preset_id}
                  onClick={() => void chooseBudgetPreset(preset)}
                  type="button"
                >
                  <span>{preset.model_hint}</span>
                  <strong>{preset.title}</strong>
                  <em>{formatTokens(preset.available_context_tokens)} / {formatTokens(preset.context_window_tokens)} tokens</em>
                  <p>{preset.description}</p>
                </button>
              ))}
            </div>
          ) : (
            <>
              <div className="system-config-field-sections">
                {groupedFields(activeGroup).map((section) => (
                  <section className="system-config-field-section" key={section.title}>
                    <div className="system-config-field-section__head">
                      <strong>{section.title}</strong>
                      {activeGroup?.group_id === "retrieval" && section.title.includes("Rerank") ? (
                        <em>四种模式互斥，保存后只会有一种链路生效。</em>
                      ) : null}
                    </div>
                    <div className="system-config-field-grid">
                      {section.fields.map((field) => (
                        <label className="system-config-field" key={field.key}>
                          <span>
                            <strong>{field.label}</strong>
                            <em>{fieldTone(field)}</em>
                          </span>
                          {renderField(field)}
                          <small>
                            {field.type === "secret" ? <KeyRound size={13} /> : null}
                            {field.description}
                          </small>
                        </label>
                      ))}
                    </div>
                  </section>
                ))}
              </div>

              <div className="system-config-actions">
                <button
                  className="action-button action-button--primary"
                  disabled={!activeGroup || saving}
                  onClick={() => void saveGroup()}
                  type="button"
                >
                  {saving ? <Loader2 className="spin" size={16} /> : <Save size={16} />}
                  保存当前配置
                </button>
                <button
                  className="action-button"
                  disabled={!activeGroup || saving}
                  onClick={() => setDraft(buildDraft(activeGroup))}
                  type="button"
                >
                  <RotateCcw size={16} />
                  恢复当前值
                </button>
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
