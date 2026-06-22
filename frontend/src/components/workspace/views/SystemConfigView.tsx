"use client";

import { useCallback, useEffect, useMemo, useState, type CSSProperties } from "react";
import {
  Check,
  ChevronDown,
  Database,
  FileCog,
  FileText,
  Gauge,
  Image as ImageIcon,
  KeyRound,
  Layers3,
  Loader2,
  Network,
  RotateCcw,
  Save,
  ServerCog,
  ShieldCheck,
  Paperclip,
  Settings2
} from "lucide-react";

import {
  DEFAULT_CUSTOM_SETTINGS,
  DEFAULT_WORKBENCH_DENSITY,
  DEFAULT_WORKBENCH_THEME_ID,
  WORKBENCH_CUSTOM_SETTINGS_CHANGE_EVENT,
  WORKBENCH_DENSITY_CHANGE_EVENT,
  WORKBENCH_DENSITY_OPTIONS,
  WORKBENCH_FONT_OPTIONS,
  WORKBENCH_THEME_CHANGE_EVENT,
  WORKBENCH_THEME_TEMPLATES,
  clearCustomOverrides,
  getStoredCustomSettings,
  getStoredWorkbenchDensity,
  getStoredWorkbenchTheme,
  setStoredCustomSettings,
  setStoredWorkbenchDensity,
  setStoredWorkbenchTheme,
  type CustomAppearanceSettings,
  type WorkbenchDensity,
  type WorkbenchFontId,
  type WorkbenchThemeId,
} from "@/framework/workbenchThemes";
import {
  getCapabilitySystemCatalog,
  getRuntimeConfigConsole,
  setContextBudgetPreset,
  setRuntimeConfigGroup,
  type ContextBudgetConfig,
  type ContextBudgetPreset,
  type CapabilitySystemCatalog,
  type ModelProviderCatalog,
  type ModelProviderOption,
  type RuntimeConfigConsole,
  type RuntimeConfigField,
  type RuntimeConfigGroup
} from "@/lib/api";
import { ActionBar } from "@/ui/ActionBar";
import { Button } from "@/ui/Button";
import { MetricCard } from "@/ui/MetricCard";
import { Toggle } from "@/ui/Toggle";

type SystemConfigGroupId =
  | "appearance"
  | "model"
  | "embedding"
  | "retrieval"
  | "document"
  | "runtime"
  | "image_assets"
  | "attachments"
  | "image_ocr"
  | "context"
  | "capabilities";

const CONFIG_SECTIONS: Array<{
  id: SystemConfigGroupId;
  icon: typeof Settings2;
  accent: string;
}> = [
  { id: "appearance", icon: Settings2, accent: "界面" },
  { id: "model", icon: ServerCog, accent: "主模型" },
  { id: "embedding", icon: Layers3, accent: "向量化" },
  { id: "retrieval", icon: Database, accent: "RAG" },
  { id: "document", icon: FileCog, accent: "解析" },
  { id: "runtime", icon: Gauge, accent: "边界" },
  { id: "image_assets", icon: ImageIcon, accent: "生图" },
  { id: "attachments", icon: Paperclip, accent: "附件" },
  { id: "image_ocr", icon: FileText, accent: "OCR" },
  { id: "context", icon: Settings2, accent: "上下文" },
  { id: "capabilities", icon: ShieldCheck, accent: "能力治理" }
];

const RUNTIME_CONFIG_GROUP_IDS: ReadonlySet<string> = new Set(
  CONFIG_SECTIONS
    .map((section) => section.id)
    .filter((id) => id !== "appearance" && id !== "capabilities")
);

function isRuntimeConfigGroupId(value: SystemConfigGroupId) {
  return RUNTIME_CONFIG_GROUP_IDS.has(value);
}

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

function modelProviderCatalog(group: RuntimeConfigGroup | null): ModelProviderCatalog | null {
  const catalog = group?.metadata?.provider_catalog;
  if (!catalog || typeof catalog !== "object" || Array.isArray(catalog)) return null;
  const payload = catalog as Partial<ModelProviderCatalog>;
  if (!payload.providers || typeof payload.providers !== "object") return null;
  return payload as ModelProviderCatalog;
}

function fieldTone(field: RuntimeConfigField) {
  if (field.key.startsWith("fallback_")) return "备用模型";
  if (field.key.startsWith("rerank_api_") || field.key === "rerank_api_key") return "API";
  if (field.key.startsWith("rerank_local_") || ["rerank_device", "rerank_batch_size", "rerank_max_length"].includes(field.key)) return "本地";
  if (field.key.startsWith("rerank_")) return "Rerank";
  return field.source === "runtime_override" ? "运行时覆盖" : "env / 默认值";
}

function groupDescription(group: RuntimeConfigGroup | null) {
  if (group?.group_id === "model") {
    return "控制系统默认模型、接入端点、密钥和备用模型；Agent 可以在 Agent 管理系统中覆盖模型运行档案。";
  }
  return group?.description ?? "选择左侧配置条目进行管理。";
}

function fieldDescription(group: RuntimeConfigGroup | null, field: RuntimeConfigField) {
  if (group?.group_id !== "model") return field.description;
  if (field.key === "base_url") return "供应商 API 接入地址；Agent 不单独配置这个地址。";
  if (field.key === "api_key") return "留空保存会保留已有密钥；Agent 只会引用这份主模型密钥。";
  return field.description
    .replace("provider", "服务商")
    .replace("Provider endpoint；多数供应商先通过 OpenAI-compatible 适配。", "供应商 API 接入地址；Agent 不单独配置这个地址。")
    .replace(/对应凭据引用\s+provider:[^。]+。?/g, "Agent 只会引用这份主模型密钥。");
}

export function SystemConfigView() {
  const [consoleConfig, setConsoleConfig] = useState<RuntimeConfigConsole | null>(null);
  const [capabilityCatalog, setCapabilityCatalog] = useState<CapabilitySystemCatalog | null>(null);
  const [activeGroupId, setActiveGroupId] = useState<SystemConfigGroupId>("appearance");
  const [activeThemeId, setActiveThemeId] = useState<WorkbenchThemeId>(DEFAULT_WORKBENCH_THEME_ID);
  const [activeDensity, setActiveDensity] = useState<WorkbenchDensity>(DEFAULT_WORKBENCH_DENSITY);
  const [customSettings, setCustomSettings] = useState<CustomAppearanceSettings>(DEFAULT_CUSTOM_SETTINGS);
  const [draft, setDraft] = useState<Record<string, string | number | boolean>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [providerMenuOpen, setProviderMenuOpen] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const groups = useMemo(() => consoleConfig?.groups ?? [], [consoleConfig]);
  const activeGroup = useMemo(
    () => isRuntimeConfigGroupId(activeGroupId) ? groups.find((group) => group.group_id === activeGroupId) ?? groups[0] ?? null : null,
    [activeGroupId, groups]
  );
  const budgetConfig = contextMetadata(activeGroup);
  const providerCatalog = activeGroupId === "model" ? modelProviderCatalog(activeGroup) : null;
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
      const nextGroup = isRuntimeConfigGroupId(activeGroupId)
        ? payload.groups.find((group) => group.group_id === activeGroupId) ?? payload.groups[0] ?? null
        : null;
      if (isRuntimeConfigGroupId(activeGroupId) && nextGroup && nextGroup.group_id !== activeGroupId) {
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
    setProviderMenuOpen(false);
  }, [activeGroup]);

  useEffect(() => {
    function syncAppearance() {
      setActiveThemeId(getStoredWorkbenchTheme());
      setActiveDensity(getStoredWorkbenchDensity());
      setCustomSettings(getStoredCustomSettings());
    }
    syncAppearance();
    window.addEventListener(WORKBENCH_THEME_CHANGE_EVENT, syncAppearance);
    window.addEventListener(WORKBENCH_DENSITY_CHANGE_EVENT, syncAppearance);
    window.addEventListener(WORKBENCH_CUSTOM_SETTINGS_CHANGE_EVENT, syncAppearance);
    window.addEventListener("storage", syncAppearance);
    return () => {
      window.removeEventListener(WORKBENCH_THEME_CHANGE_EVENT, syncAppearance);
      window.removeEventListener(WORKBENCH_DENSITY_CHANGE_EVENT, syncAppearance);
      window.removeEventListener(WORKBENCH_CUSTOM_SETTINGS_CHANGE_EVENT, syncAppearance);
      window.removeEventListener("storage", syncAppearance);
    };
  }, []);

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
        <Toggle
          activeClassName="system-config-toggle--on"
          checked={Boolean(value)}
          className="system-config-toggle"
          onCheckedChange={(checked) => setDraft((current) => ({ ...current, [field.key]: checked }))}
        >
          <span />
          {value ? "开启" : "关闭"}
        </Toggle>
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
  const activeThemeLabel = WORKBENCH_THEME_TEMPLATES.find((theme) => theme.id === activeThemeId)?.label ?? "清爽工作台";
  const activeDensityLabel = WORKBENCH_DENSITY_OPTIONS.find((density) => density.id === activeDensity)?.label ?? "标准";
  const activePanelTitle = activeGroupId === "appearance"
    ? "外观与布局"
    : activeGroupId === "capabilities"
      ? "能力治理"
      : activeGroup?.title ?? "配置项";
  const activePanelStatus = activeGroupId === "appearance"
    ? `${activeThemeLabel} / ${activeDensityLabel}`
    : activeGroupId === "capabilities"
      ? `${validationIssues.length} 个校验项`
      : activeGroup?.status ?? "等待配置";
  const activePanelDescription = activeGroupId === "appearance"
    ? "统一主题、字体清晰度、布局密度和基础面板偏好。"
    : activeGroupId === "capabilities"
      ? "治理工具、能力可见性和高风险操作授权。"
      : groupDescription(activeGroup);

  function applyProviderPreset(provider: string, option: ModelProviderOption) {
    setDraft((current) => ({
      ...current,
      provider,
      model: option.default_model || current.model || "",
      base_url: option.default_base_url || current.base_url || "",
      api_key: "",
    }));
  }

  function renderModelProviderPanel(catalog: ModelProviderCatalog | null) {
    if (!catalog) return null;
    const providers = Object.values(catalog.providers ?? {});
    const selectedProvider = String(draft.provider || catalog.default_provider || "deepseek");
    const selected = catalog.providers?.[selectedProvider];
    const credentialReady = Boolean(selected?.credential_configured || selectedProvider === "ollama");
    const selectedLabel = selected?.display_name || selectedProvider;
    const selectedModel = String(draft.model || selected?.default_model || catalog.default_model || "未配置");
    return (
      <section className="system-config-field-section">
        <div className="system-config-field-section__head">
          <strong>供应商预设</strong>
          <em>选择系统默认供应商；详细端点和密钥在下方字段中编辑。</em>
        </div>
        <div className="system-config-provider-panel system-config-provider-panel--compact">
          <div
            className="system-config-provider-select"
            onBlur={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
                setProviderMenuOpen(false);
              }
            }}
          >
            <span>供应商</span>
            <button
              aria-expanded={providerMenuOpen}
              aria-haspopup="listbox"
              className="system-config-provider-trigger"
              onClick={() => setProviderMenuOpen((current) => !current)}
              type="button"
            >
              <strong>{selectedLabel}</strong>
              <em>{selectedModel}</em>
              <ChevronDown size={15} />
            </button>
            {providerMenuOpen ? (
              <div className="system-config-provider-menu" role="listbox">
                {providers.map((provider) => {
                  const active = selectedProvider === provider.provider;
                  return (
                    <button
                      aria-selected={active}
                      className={`system-config-provider-option ${active ? "system-config-provider-option--active" : ""}`}
                      key={provider.provider}
                      onClick={() => {
                        applyProviderPreset(provider.provider, provider);
                        setProviderMenuOpen(false);
                      }}
                      role="option"
                      type="button"
                    >
                      <span>
                        <strong>{provider.display_name || provider.provider}</strong>
                        <em>{provider.default_model}</em>
                      </span>
                      {active ? <Check size={15} /> : null}
                    </button>
                  );
                })}
              </div>
            ) : null}
          </div>
          <div className="system-config-provider-summary">
            <MetricCard detail={selectedModel} detailAs="em" label="当前选择" value={selectedLabel} />
            <MetricCard
              detail={selectedProvider === "ollama" ? "本地模型无需远程密钥" : credentialReady ? "当前供应商已具备调用条件" : "在下方密钥字段保存后生效"}
              detailAs="em"
              label="凭据状态"
              value={credentialReady ? "可用" : "待配置"}
            />
          </div>
        </div>
      </section>
    );
  }

  function chooseTheme(themeId: WorkbenchThemeId) {
    setStoredWorkbenchTheme(themeId);
    setActiveThemeId(themeId);
    setNotice(`已切换主题：${WORKBENCH_THEME_TEMPLATES.find((theme) => theme.id === themeId)?.label ?? themeId}`);
    setError("");
  }

  function chooseDensity(density: WorkbenchDensity) {
    setStoredWorkbenchDensity(density);
    setActiveDensity(density);
    setNotice(`已切换布局密度：${WORKBENCH_DENSITY_OPTIONS.find((item) => item.id === density)?.label ?? density}`);
    setError("");
  }

  function handleFontChange(fontId: WorkbenchFontId) {
    setCustomSettings((prev) => ({ ...prev, fontOverride: fontId }));
    setStoredCustomSettings({ fontOverride: fontId });
  }

  function handleFontSizeChange(scale: number) {
    setCustomSettings((prev) => ({ ...prev, fontSizeScale: scale }));
    setStoredCustomSettings({ fontSizeScale: scale });
  }

  function handleBgColorChange(color: string) {
    setCustomSettings((prev) => ({ ...prev, bgColor: color || null }));
    setStoredCustomSettings({ bgColor: color || null });
  }

  function handlePanelColorChange(color: string) {
    setCustomSettings((prev) => ({ ...prev, panelColor: color || null }));
    setStoredCustomSettings({ panelColor: color || null });
  }

  function handleAccentSoftColorChange(color: string) {
    setCustomSettings((prev) => ({ ...prev, accentSoftColor: color || null }));
    setStoredCustomSettings({ accentSoftColor: color || null });
  }

  function handleBgImageUpload(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => {
      const dataUrl = e.target?.result as string;
      setCustomSettings((prev) => ({ ...prev, bgImage: dataUrl }));
      setStoredCustomSettings({ bgImage: dataUrl });
    };
    reader.readAsDataURL(file);
  }

  function handleRemoveBgImage() {
    setCustomSettings((prev) => ({ ...prev, bgImage: null }));
    setStoredCustomSettings({ bgImage: null });
  }

  function handleResetCustom() {
    clearCustomOverrides();
    const fresh = getStoredCustomSettings();
    setCustomSettings(fresh);
    setNotice("已重置所有自定义覆盖");
  }

  const currentFont = WORKBENCH_FONT_OPTIONS.find((f) => f.id === (customSettings.fontOverride ?? "system"))!;
  const currentScale = customSettings.fontSizeScale;

  function renderAppearancePanel() {
    return (
      <div className="system-config-appearance">
        {/* ===== 主题模板 ===== */}
        <section className="system-config-field-section">
          <div className="system-config-field-section__head">
            <strong>主题模板</strong>
            <em>选择预置配色方案，自定义覆盖会在切换主题后继续生效。</em>
          </div>
          <div className="system-config-theme-grid">
            {WORKBENCH_THEME_TEMPLATES.map((theme) => {
              const active = activeThemeId === theme.id;
              return (
                <button
                  aria-pressed={active}
                  className={`system-config-theme-card ${active ? "system-config-theme-card--active" : ""}`}
                  key={theme.id}
                  onClick={() => chooseTheme(theme.id)}
                  type="button"
                >
                  <span
                    className="system-config-theme-card__preview"
                    style={{
                      "--theme-preview-accent": theme.preview.accent,
                      "--theme-preview-bg": theme.preview.background,
                      "--theme-preview-surface": theme.preview.surface,
                      "--theme-preview-text": theme.preview.text,
                    } as CSSProperties}
                  >
                    <i />
                    <i />
                    <i />
                  </span>
                  <span className="system-config-theme-card__body">
                    <strong>{theme.label}</strong>
                    <small>{theme.description}</small>
                  </span>
                  <em>{active ? "当前" : "可切换"}</em>
                </button>
              );
            })}
          </div>
        </section>

        {/* ===== 字体选择 ===== */}
        <section className="system-config-field-section">
          <div className="system-config-field-section__head">
            <strong>字体选择</strong>
            <em>选择显示字体，即时预览效果。</em>
          </div>
          <div className="system-config-font-grid">
            {WORKBENCH_FONT_OPTIONS.map((font) => {
              const active = (customSettings.fontOverride ?? "system") === font.id;
              return (
                <button
                  aria-pressed={active}
                  className={`system-config-font-card ${active ? "system-config-font-card--active" : ""}`}
                  key={font.id}
                  onClick={() => handleFontChange(font.id)}
                  type="button"
                >
                  <strong style={{ fontFamily: font.fontDisplay }}>{font.label}</strong>
                  <small>{font.description}</small>
                  <span style={{ fontFamily: font.fontMono }}>等宽样例：code style</span>
                  <em>{active ? "当前" : "应用"}</em>
                </button>
              );
            })}
          </div>
        </section>

        {/* ===== 字体大小 ===== */}
        <section className="system-config-field-section">
          <div className="system-config-field-section__head">
            <strong>字体大小</strong>
            <em>调整整体缩放比例。当前：{Math.round(currentScale * 100)}%</em>
          </div>
          <div className="system-config-font-size-slider">
            <span>小</span>
            <input
              type="range"
              min="0.8"
              max="1.3"
              step="0.05"
              value={currentScale}
              onChange={(e) => handleFontSizeChange(parseFloat(e.target.value))}
            />
            <span>大</span>
            <output>{Math.round(currentScale * 100)}%</output>
          </div>
        </section>

        {/* ===== 布局密度 ===== */}
        <section className="system-config-field-section">
          <div className="system-config-field-section__head">
            <strong>基本界面布局</strong>
            <em>控制列表密度和面板间距，保持所有页面同一标准。</em>
          </div>
          <div className="system-config-density-grid">
            {WORKBENCH_DENSITY_OPTIONS.map((density) => {
              const active = activeDensity === density.id;
              return (
                <button
                  aria-pressed={active}
                  className={`system-config-density-card ${active ? "system-config-density-card--active" : ""}`}
                  key={density.id}
                  onClick={() => chooseDensity(density.id)}
                  type="button"
                >
                  <span>
                    <strong>{density.label}</strong>
                    <small>{density.description}</small>
                  </span>
                  <em>{active ? "当前" : "应用"}</em>
                </button>
              );
            })}
          </div>
        </section>

        {/* ===== 自定义颜色 ===== */}
        <section className="system-config-field-section">
          <div className="system-config-field-section__head">
            <strong>自定义颜色覆盖</strong>
            <em>单独调整背景色和面板色，留空则使用当前主题色值。</em>
          </div>
          <div className="system-config-color-grid">
            <label className="system-config-color-picker">
              <span>背景颜色</span>
              <input
                type="color"
                value={customSettings.bgColor ?? "#ffffff"}
                onChange={(e) => handleBgColorChange(e.target.value)}
              />
              {customSettings.bgColor ? (
                <button
                  className="system-config-color-reset"
                  onClick={() => handleBgColorChange("")}
                  type="button"
                  title="恢复主题默认"
                >
                  ✕
                </button>
              ) : null}
              <em>{customSettings.bgColor ?? "使用主题默认"}</em>
            </label>
            <label className="system-config-color-picker">
              <span>面板颜色</span>
              <input
                type="color"
                value={customSettings.panelColor ?? "#ffffff"}
                onChange={(e) => handlePanelColorChange(e.target.value)}
              />
              {customSettings.panelColor ? (
                <button
                  className="system-config-color-reset"
                  onClick={() => handlePanelColorChange("")}
                  type="button"
                  title="恢复主题默认"
                >
                  ✕
                </button>
              ) : null}
              <em>{customSettings.panelColor ?? "使用主题默认"}</em>
            </label>
            <label className="system-config-color-picker">
              <span>强调背景色</span>
              <input
                type="color"
                value={customSettings.accentSoftColor ?? "#eaf3ff"}
                onChange={(e) => handleAccentSoftColorChange(e.target.value)}
              />
              {customSettings.accentSoftColor ? (
                <button
                  className="system-config-color-reset"
                  onClick={() => handleAccentSoftColorChange("")}
                  type="button"
                  title="恢复主题默认"
                >
                  ✕
                </button>
              ) : null}
              <em>{customSettings.accentSoftColor ?? "使用主题默认"}</em>
            </label>
          </div>
        </section>

        {/* ===== 背景图片 ===== */}
        <section className="system-config-field-section">
          <div className="system-config-field-section__head">
            <strong>背景图片</strong>
            <em>上传图片作为工作台背景，图片会自适应覆盖整个背景区域。</em>
          </div>
          <div className="system-config-bg-image-upload">
            {customSettings.bgImage ? (
              <div className="system-config-bg-image-preview">
                <img src={customSettings.bgImage} alt="背景预览" />
                <button onClick={handleRemoveBgImage} type="button" className="system-config-bg-image-remove">
                  移除背景图片
                </button>
              </div>
            ) : (
              <label className="system-config-bg-image-input">
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/gif,image/webp,image/svg+xml"
                  onChange={handleBgImageUpload}
                />
                <span>点击选择图片</span>
              </label>
            )}
          </div>
        </section>

        {/* ===== 重置 ===== */}
        <div className="system-config-appearance-actions">
          <button
            className="system-config-appearance-reset"
            onClick={handleResetCustom}
            type="button"
          >
            重置所有自定义覆盖
          </button>
        </div>
      </div>
    );
  }

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
          <MetricCard
            detail={`${mainVisibleTools.length} 个可进入主模型工具面`}
            detailAs="em"
            label="工具"
            value={capabilitySummary?.tool_count ?? capabilityCatalog.tools.length}
          />
          <MetricCard
            detail="当前为本地 worker 端点，后续可并入外部 MCP"
            detailAs="em"
            label="端点"
            value={capabilitySummary?.capability_endpoint_count ?? capabilityCatalog.capability_endpoints?.length ?? 0}
          />
          <MetricCard
            detail="ResourcePolicy 授权原子"
            detailAs="em"
            label="操作"
            value={capabilitySummary?.operation_count ?? capabilityCatalog.operations?.length ?? 0}
          />
          <MetricCard
            detail={`${capabilitySummary?.validation_error_count ?? 0} 个错误`}
            detailAs="em"
            label="校验"
            value={validationIssues.length}
          />
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
          <p className="workspace-view__eyebrow">运行配置工作台</p>
          <h2 className="workspace-view__title">系统配置</h2>
          <p className="workspace-view__subtitle">管理模型、上下文、检索、文档解析和运行限制；保存到运行时覆盖配置，`.env` 仍作为底座。</p>
        </div>
        <ActionBar className="workspace-view__actions">
          <Button chrome="action" disabled={loading || saving} onClick={() => void refreshConfig()}>
            {loading ? <Loader2 className="spin" size={16} /> : <RotateCcw size={16} />}
            刷新
          </Button>
        </ActionBar>
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
        <MetricCard detail={activePanelStatus} detailAs="em" label="当前面板" value={activePanelTitle} />
        <MetricCard detail="当前由前端配置覆盖的字段" detailAs="em" label="运行时覆盖" value={overriddenCount} />
        <MetricCard detail="新密钥只在保存时写入" detailAs="em" label="密钥策略" value="不回显密钥" />
      </section>

      <div className="system-config-layout">
        <aside className="system-config-nav">
          {CONFIG_SECTIONS.map((section) => {
            const group = groups.find((item) => item.group_id === section.id);
            const Icon = section.icon;
            const sectionTitle = section.id === "appearance"
              ? "外观与布局"
              : section.id === "capabilities"
                ? "能力治理"
                : group?.title ?? section.id;
            const sectionStatus = section.id === "appearance"
              ? `${activeThemeLabel} / ${activeDensityLabel}`
              : section.id === "capabilities"
                ? `${validationIssues.length} 个校验项`
                : group?.status ?? "未加载";
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
                  <strong>{sectionTitle}</strong>
                  <small>{sectionStatus}</small>
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
              <strong>{activePanelTitle}</strong>
              <p>{activePanelDescription}</p>
            </div>
          </div>

          {activeGroupId === "appearance" ? renderAppearancePanel() : activeGroupId === "capabilities" ? renderCapabilitiesPanel() : activeGroup?.group_id === "context" && budgetConfig ? (
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
                {activeGroup?.group_id === "model" ? renderModelProviderPanel(providerCatalog) : null}
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
                            {fieldDescription(activeGroup, field)}
                          </small>
                        </label>
                      ))}
                    </div>
                  </section>
                ))}
              </div>

              <ActionBar className="system-config-actions">
                <Button
                  chrome="action"
                  disabled={!activeGroup || saving}
                  onClick={() => void saveGroup()}
                  variant="primary"
                >
                  {saving ? <Loader2 className="spin" size={16} /> : <Save size={16} />}
                  保存当前配置
                </Button>
                <Button
                  chrome="action"
                  disabled={!activeGroup || saving}
                  onClick={() => setDraft(buildDraft(activeGroup))}
                >
                  <RotateCcw size={16} />
                  恢复当前值
                </Button>
              </ActionBar>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
