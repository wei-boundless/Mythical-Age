"use client";

import { useCallback, useEffect, useMemo, useState, type ChangeEvent, type CSSProperties } from "react";
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
  WORKBENCH_COLOR_TOKEN_GROUPS,
  WORKBENCH_DENSITY_CHANGE_EVENT,
  WORKBENCH_DENSITY_OPTIONS,
  WORKBENCH_FONT_OPTIONS,
  WORKBENCH_TEXT_TOKEN_IDS,
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
  type WorkbenchBackgroundImageMeta,
  type WorkbenchColorTokenId,
  type WorkbenchDensity,
  type WorkbenchFontId,
  type WorkbenchTextTokenId,
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

const TEXT_TOKEN_ID_SET: ReadonlySet<string> = new Set(WORKBENCH_TEXT_TOKEN_IDS);
const CUSTOM_TEXT_FONT_VALUE = "__custom_font__";
const CUSTOM_TEXT_FONT_FAMILY = '"Microsoft YaHei UI", "PingFang SC", "Noto Sans SC", sans-serif';

const TEXT_SIZE_OPTIONS = [
  { value: "", label: "跟随全局" },
  { value: "12", label: "12 px" },
  { value: "13", label: "13 px" },
  { value: "14", label: "14 px" },
  { value: "15", label: "15 px" },
  { value: "16", label: "16 px" },
  { value: "17", label: "17 px" },
  { value: "18", label: "18 px" },
  { value: "20", label: "20 px" },
  { value: "22", label: "22 px" },
  { value: "24", label: "24 px" },
  { value: "28", label: "28 px" },
  { value: "32", label: "32 px" },
] as const;

const BACKGROUND_IMAGE_MAX_STORED_CHARS = 2_800_000;
const BACKGROUND_IMAGE_MAX_EDGE = 2560;
const BACKGROUND_IMAGE_QUALITY_STEPS = [0.86, 0.78, 0.68, 0.58] as const;
const BACKGROUND_IMAGE_OUTPUT_TYPES = ["image/webp", "image/jpeg"] as const;

function isRuntimeConfigGroupId(value: SystemConfigGroupId) {
  return RUNTIME_CONFIG_GROUP_IDS.has(value);
}

function isTextTokenId(tokenId: WorkbenchColorTokenId): tokenId is WorkbenchTextTokenId {
  return TEXT_TOKEN_ID_SET.has(tokenId);
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

function enabledLabel(enabled: boolean) {
  return enabled ? "已开启" : "跟随主题";
}

function colorOverrideSummary(count: number) {
  if (count <= 0) return "全部使用当前主题";
  return `已自定义 ${count} 项`;
}

function appearancePercent(value: number) {
  return `${Math.round(value)}%`;
}

function formatBytes(bytes: number) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 KB";
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function storedImageSizeLabel(dataUrl: string) {
  return formatBytes(Math.round(dataUrl.length * 0.75));
}

function backgroundImageMetaFromDimensions(width: number, height: number): WorkbenchBackgroundImageMeta {
  const roundedWidth = Math.max(1, Math.round(width));
  const roundedHeight = Math.max(1, Math.round(height));
  return {
    width: roundedWidth,
    height: roundedHeight,
    aspectRatio: Number((roundedWidth / roundedHeight).toFixed(4)),
  };
}

function backgroundImageDetailLabel(settings: CustomAppearanceSettings) {
  const sizeLabel = settings.bgImage ? storedImageSizeLabel(settings.bgImage) : "0 KB";
  if (!settings.bgImageMeta) return sizeLabel;
  return `${settings.bgImageMeta.width} x ${settings.bgImageMeta.height} / ${sizeLabel}`;
}

function readFileAsDataUrl(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("读取图片失败，请重新选择。"));
    reader.onload = () => {
      const result = reader.result;
      if (typeof result !== "string") {
        reject(new Error("读取图片失败，请重新选择。"));
        return;
      }
      resolve(result);
    };
    reader.readAsDataURL(file);
  });
}

function loadImageFromObjectUrl(objectUrl: string) {
  return new Promise<HTMLImageElement>((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("无法解析这张图片，请换一张 PNG、JPG 或 WebP。"));
    image.src = objectUrl;
  });
}

async function readBackgroundImageMeta(file: File) {
  const objectUrl = URL.createObjectURL(file);
  try {
    const image = await loadImageFromObjectUrl(objectUrl);
    const width = image.naturalWidth || image.width;
    const height = image.naturalHeight || image.height;
    if (!width || !height) {
      throw new Error("无法读取图片尺寸，请换一张图片。");
    }
    return backgroundImageMetaFromDimensions(width, height);
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}

async function compressBackgroundImage(file: File) {
  const objectUrl = URL.createObjectURL(file);
  try {
    const image = await loadImageFromObjectUrl(objectUrl);
    const width = image.naturalWidth || image.width;
    const height = image.naturalHeight || image.height;
    if (!width || !height) {
      throw new Error("无法读取图片尺寸，请换一张图片。");
    }

    const scale = Math.min(1, BACKGROUND_IMAGE_MAX_EDGE / Math.max(width, height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(width * scale));
    canvas.height = Math.max(1, Math.round(height * scale));
    const context = canvas.getContext("2d");
    if (!context) {
      throw new Error("浏览器无法处理这张背景图片。");
    }
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, 0, canvas.width, canvas.height);

    const candidates: string[] = [];
    BACKGROUND_IMAGE_OUTPUT_TYPES.forEach((mimeType) => {
      BACKGROUND_IMAGE_QUALITY_STEPS.forEach((quality) => {
        const dataUrl = canvas.toDataURL(mimeType, quality);
        if (dataUrl.startsWith(`data:${mimeType}`)) {
          candidates.push(dataUrl);
        }
      });
    });
    candidates.sort((a, b) => a.length - b.length);
    return {
      dataUrl: candidates.find((candidate) => candidate.length <= BACKGROUND_IMAGE_MAX_STORED_CHARS) ?? candidates[0] ?? "",
      meta: backgroundImageMetaFromDimensions(canvas.width, canvas.height),
    };
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}

async function prepareWorkbenchBackgroundImage(file: File) {
  if (!file.type.startsWith("image/")) {
    throw new Error("请选择图片文件。");
  }

  const meta = await readBackgroundImageMeta(file);
  const rawDataUrl = await readFileAsDataUrl(file);
  if (rawDataUrl.length <= BACKGROUND_IMAGE_MAX_STORED_CHARS) {
    return { compressed: false, dataUrl: rawDataUrl, meta };
  }

  if (file.type === "image/svg+xml") {
    throw new Error(`这张 SVG 太大，当前约 ${formatBytes(file.size)}。请换一张更小的背景图。`);
  }

  const compressed = await compressBackgroundImage(file);
  if (!compressed.dataUrl || compressed.dataUrl.length > BACKGROUND_IMAGE_MAX_STORED_CHARS) {
    throw new Error(`这张图片压缩后仍然过大，当前约 ${formatBytes(file.size)}。请换一张更小的背景图。`);
  }
  return { compressed: true, dataUrl: compressed.dataUrl, meta: compressed.meta };
}

function textFontPresetValue(fontFamily: string | undefined) {
  if (!fontFamily) return "";
  return WORKBENCH_FONT_OPTIONS.find((font) => font.fontDisplay === fontFamily)?.id ?? CUSTOM_TEXT_FONT_VALUE;
}

export function SystemConfigView() {
  const [consoleConfig, setConsoleConfig] = useState<RuntimeConfigConsole | null>(null);
  const [capabilityCatalog, setCapabilityCatalog] = useState<CapabilitySystemCatalog | null>(null);
  const [activeGroupId, setActiveGroupId] = useState<SystemConfigGroupId>("appearance");
  const [activeThemeId, setActiveThemeId] = useState<WorkbenchThemeId>(DEFAULT_WORKBENCH_THEME_ID);
  const [activeDensity, setActiveDensity] = useState<WorkbenchDensity>(DEFAULT_WORKBENCH_DENSITY);
  const [customSettings, setCustomSettings] = useState<CustomAppearanceSettings>(DEFAULT_CUSTOM_SETTINGS);
  const [resolvedColorTokens, setResolvedColorTokens] = useState<Partial<Record<WorkbenchColorTokenId, string>>>({});
  const [draft, setDraft] = useState<Record<string, string | number | boolean>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [backgroundImageBusy, setBackgroundImageBusy] = useState(false);
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

  useEffect(() => {
    if (typeof window === "undefined") return;
    const tokenIds = WORKBENCH_COLOR_TOKEN_GROUPS.flatMap((group) => group.tokens.map((token) => token.id));
    const readResolvedColors = () => {
      const computed = window.getComputedStyle(document.documentElement);
      setResolvedColorTokens(Object.fromEntries(tokenIds.map((tokenId) => [
        tokenId,
        colorInputValue(computed.getPropertyValue(`--${tokenId}`)),
      ])) as Partial<Record<WorkbenchColorTokenId, string>>);
    };
    const frame = window.requestAnimationFrame(readResolvedColors);
    return () => window.cancelAnimationFrame(frame);
  }, [activeThemeId, customSettings]);

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
  const activeTheme = WORKBENCH_THEME_TEMPLATES.find((theme) => theme.id === activeThemeId) ?? WORKBENCH_THEME_TEMPLATES[0];
  const activeThemeLabel = activeTheme.label;
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
    setCustomSettings(getStoredCustomSettings());
    setActiveThemeId(themeId);
    setNotice(`已切换主题：${WORKBENCH_THEME_TEMPLATES.find((theme) => theme.id === themeId)?.label ?? themeId}，已使用模板默认颜色`);
    setError("");
  }

  function chooseDensity(density: WorkbenchDensity) {
    setStoredWorkbenchDensity(density);
    setActiveDensity(density);
    setNotice(`已切换布局密度：${WORKBENCH_DENSITY_OPTIONS.find((item) => item.id === density)?.label ?? density}`);
    setError("");
  }

  function handleFontChange(fontId: WorkbenchFontId) {
    setCustomSettings(setStoredCustomSettings({ fontOverride: fontId }));
  }

  function handleFontSizeChange(scale: number) {
    setCustomSettings(setStoredCustomSettings({ fontSizeScale: scale }));
  }

  function handleColorTokenChange(tokenId: WorkbenchColorTokenId, color: string) {
    const current = getStoredCustomSettings();
    const colorOverrides = { ...current.colorOverrides };
    if (color) {
      colorOverrides[tokenId] = color;
    } else {
      delete colorOverrides[tokenId];
    }
    setCustomSettings(setStoredCustomSettings({
      colorOverrides,
      customColorsEnabled: Object.keys(colorOverrides).length > 0,
    }));
  }

  function handleTextStyleChange(
    tokenId: WorkbenchTextTokenId,
    patch: { fontFamily?: string | null; fontSizePx?: number | null },
  ) {
    const current = getStoredCustomSettings();
    const textStyleOverrides = { ...current.textStyleOverrides };
    const nextStyle = { ...(textStyleOverrides[tokenId] ?? {}) };

    if ("fontFamily" in patch) {
      const fontFamily = patch.fontFamily?.trim() ?? "";
      if (fontFamily) {
        nextStyle.fontFamily = fontFamily;
      } else {
        delete nextStyle.fontFamily;
      }
    }
    if ("fontSizePx" in patch) {
      const fontSizePx = Number(patch.fontSizePx);
      if (Number.isFinite(fontSizePx) && fontSizePx > 0) {
        nextStyle.fontSizePx = fontSizePx;
      } else {
        delete nextStyle.fontSizePx;
      }
    }

    if (nextStyle.fontFamily || nextStyle.fontSizePx) {
      textStyleOverrides[tokenId] = nextStyle;
    } else {
      delete textStyleOverrides[tokenId];
    }
    setCustomSettings(setStoredCustomSettings({ textStyleOverrides }));
  }

  function handleTextFontPresetChange(tokenId: WorkbenchTextTokenId, presetId: string) {
    if (!presetId) {
      handleTextStyleChange(tokenId, { fontFamily: null });
      return;
    }
    if (presetId === CUSTOM_TEXT_FONT_VALUE) {
      const currentFont = getStoredCustomSettings().textStyleOverrides[tokenId]?.fontFamily;
      handleTextStyleChange(tokenId, {
        fontFamily: currentFont && textFontPresetValue(currentFont) === CUSTOM_TEXT_FONT_VALUE
          ? currentFont
          : CUSTOM_TEXT_FONT_FAMILY,
      });
      return;
    }
    const preset = WORKBENCH_FONT_OPTIONS.find((font) => font.id === presetId);
    if (preset) {
      handleTextStyleChange(tokenId, { fontFamily: preset.fontDisplay });
    }
  }

  function handleTextLevelReset(tokenId: WorkbenchTextTokenId) {
    const current = getStoredCustomSettings();
    const colorOverrides = { ...current.colorOverrides };
    const textStyleOverrides = { ...current.textStyleOverrides };
    delete colorOverrides[tokenId];
    delete textStyleOverrides[tokenId];
    setCustomSettings(setStoredCustomSettings({
      colorOverrides,
      customColorsEnabled: Object.keys(colorOverrides).length > 0,
      textStyleOverrides,
    }));
  }

  async function handleBgImageUpload(event: ChangeEvent<HTMLInputElement>) {
    const input = event.currentTarget;
    const file = event.target.files?.[0];
    input.value = "";
    if (!file) return;
    setBackgroundImageBusy(true);
    setError("");
    setNotice("");
    try {
      const prepared = await prepareWorkbenchBackgroundImage(file);
      const current = getStoredCustomSettings();
      const next = setStoredCustomSettings({
        bgImage: prepared.dataUrl,
        bgImageMeta: prepared.meta,
        chatCanvasVeil: current.bgImage ? current.chatCanvasVeil : Math.min(current.chatCanvasVeil, 24),
      });
      setCustomSettings(next);
      setNotice(prepared.compressed
        ? `已压缩并应用背景图片，${prepared.meta.width} x ${prepared.meta.height}，存储大小约 ${storedImageSizeLabel(prepared.dataUrl)}。`
        : `已应用背景图片，${prepared.meta.width} x ${prepared.meta.height}，存储大小约 ${storedImageSizeLabel(prepared.dataUrl)}。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "应用背景图片失败。");
    } finally {
      setBackgroundImageBusy(false);
    }
  }

  function handleRemoveBgImage() {
    setError("");
    setNotice("");
    setCustomSettings(setStoredCustomSettings({ bgImage: null, bgImageMeta: null }));
    setNotice("已移除背景图片。");
  }

  function handleAppearanceNumberChange(patch: Partial<Pick<CustomAppearanceSettings, "chatCanvasVeil" | "chatSurfaceOpacity" | "closeoutMaxWidth" | "textureIntensity">>) {
    setCustomSettings(setStoredCustomSettings(patch));
  }

  function handleResetCustom() {
    clearCustomOverrides();
    const fresh = getStoredCustomSettings();
    setCustomSettings(fresh);
    setNotice("已重置所有自定义覆盖");
  }

  function defaultTextSizePx(tokenId: WorkbenchTextTokenId) {
    if (tokenId === "console-text") return currentBodyFontSize;
    if (tokenId === "console-text-soft") return currentUiFontSize;
    if (tokenId === "console-muted") return Math.max(10, currentUiFontSize - 2);
    return Math.max(10, currentUiFontSize - 3);
  }

  function renderTextTypographyGroup(group: (typeof WORKBENCH_COLOR_TOKEN_GROUPS)[number]) {
    return (
      <details className="system-config-token-group system-config-token-group--type" key={group.id} open>
        <summary>{group.label}</summary>
        <div className="system-config-type-list">
          {group.tokens.map((token) => {
            if (!isTextTokenId(token.id)) return null;
            const textTokenId = token.id;
            const overrideColor = customSettings.colorOverrides[textTokenId] ?? "";
            const resolvedColor = resolvedColorTokens[textTokenId] || "#ffffff";
            const value = colorInputValue(overrideColor || resolvedColor);
            const textStyle = customSettings.textStyleOverrides[textTokenId] ?? {};
            const fontPreset = textFontPresetValue(textStyle.fontFamily);
            const defaultSize = defaultTextSizePx(textTokenId);
            const hasOverride = Boolean(overrideColor || textStyle.fontFamily || textStyle.fontSizePx);
            return (
              <article className="system-config-type-row" key={textTokenId}>
                <div
                  className="system-config-type-row__sample"
                  style={{
                    "--type-sample-color": value,
                    "--type-sample-font": textStyle.fontFamily ?? currentFont.fontDisplay,
                    "--type-sample-size": `${textStyle.fontSizePx ?? defaultSize}px`,
                  } as CSSProperties}
                >
                  文
                </div>
                <div className="system-config-type-row__copy">
                  <strong>{token.label}</strong>
                  <small>{token.description}</small>
                  <em>{hasOverride ? "已自定义" : "跟随当前主题"}</em>
                </div>
                <div className="system-config-type-row__controls">
                  <label>
                    <span>颜色</span>
                    <input
                      aria-label={`${token.label}颜色`}
                      type="color"
                      value={value}
                      onChange={(event) => handleColorTokenChange(textTokenId, event.target.value)}
                    />
                  </label>
                  <label>
                    <span>字号</span>
                    <select
                      aria-label={`${token.label}字号`}
                      value={textStyle.fontSizePx ? String(textStyle.fontSizePx) : ""}
                      onChange={(event) => handleTextStyleChange(textTokenId, {
                        fontSizePx: event.target.value ? Number(event.target.value) : null,
                      })}
                    >
                      {TEXT_SIZE_OPTIONS.map((option) => (
                        <option key={option.value || "default"} value={option.value}>{option.label}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>精确字号</span>
                    <input
                      aria-label={`${token.label}精确字号`}
                      inputMode="numeric"
                      min="10"
                      max="32"
                      step="1"
                      type="number"
                      value={textStyle.fontSizePx ?? ""}
                      placeholder={`${defaultSize}`}
                      onChange={(event) => handleTextStyleChange(textTokenId, {
                        fontSizePx: event.target.value ? Number(event.target.value) : null,
                      })}
                    />
                  </label>
                  <label className="system-config-type-row__font">
                    <span>字体样式</span>
                    <select
                      aria-label={`${token.label}字体样式`}
                      value={fontPreset}
                      onChange={(event) => handleTextFontPresetChange(textTokenId, event.target.value)}
                    >
                      <option value="">跟随全局</option>
                      {WORKBENCH_FONT_OPTIONS.map((font) => (
                        <option key={font.id} value={font.id}>{font.label}</option>
                      ))}
                      <option value={CUSTOM_TEXT_FONT_VALUE}>自定义字体</option>
                    </select>
                  </label>
                  {fontPreset === CUSTOM_TEXT_FONT_VALUE ? (
                    <label className="system-config-type-row__custom-font">
                      <span>字体名称</span>
                      <input
                        aria-label={`${token.label}字体名称`}
                        type="text"
                        value={textStyle.fontFamily ?? ""}
                        placeholder="Microsoft YaHei UI"
                        onChange={(event) => handleTextStyleChange(textTokenId, { fontFamily: event.target.value })}
                      />
                    </label>
                  ) : null}
                  {hasOverride ? (
                    <button
                      className="system-config-type-row__reset"
                      onClick={() => handleTextLevelReset(textTokenId)}
                      type="button"
                    >
                      重置
                    </button>
                  ) : null}
                </div>
              </article>
            );
          })}
        </div>
      </details>
    );
  }

  const currentFontId = customSettings.fontOverride ?? activeTheme.font;
  const currentFont = WORKBENCH_FONT_OPTIONS.find((f) => f.id === currentFontId) ?? WORKBENCH_FONT_OPTIONS[0];
  const currentScale = customSettings.fontSizeScale;
  const currentUiFontSize = Math.round(15 * currentScale);
  const currentPageFontSize = Math.round(16 * currentScale);
  const currentBodyFontSize = Math.round(17 * currentScale);
  const fontSourceLabel = customSettings.fontOverride ? "手动覆盖" : "模板默认";
  const activeColorOverrideCount = Object.keys(customSettings.colorOverrides).length;
  const activeTypographyOverrideCount = Object.keys(customSettings.textStyleOverrides).length;
  const themeToneLabel = activeTheme.mode === "dark" ? "深色界面" : "浅色界面";
  const colorModeLabel = colorOverrideSummary(activeColorOverrideCount);
  const backgroundModeLabel = customSettings.bgImage ? "自定义图片" : "主题背景";
  const backgroundDetailLabel = customSettings.bgImage ? `已上传 / ${backgroundImageDetailLabel(customSettings)}` : "使用当前主题的背景质感";

  function renderAppearancePanel() {
    return (
      <div className="system-config-appearance">
        <section className="system-config-field-section system-config-live-preview-section">
          <div className="system-config-field-section__head">
            <strong>当前生效配置</strong>
            <em>只展示当前外观效果和用户可调整项，不显示内部实现信息。</em>
          </div>
          <div
            className="system-config-appearance-preview"
            style={{
              "--appearance-preview-font": currentFont.fontDisplay,
              "--appearance-preview-mono": currentFont.fontMono,
              "--appearance-preview-body-size": `${currentBodyFontSize}px`,
            } as CSSProperties}
          >
            <div className="system-config-appearance-preview__canvas">
              <article className="system-config-appearance-preview__message" aria-label="Markdown 收口预览">
                <header>
                  <span>Markdown 收口预览</span>
                  <h3>一、完成概览</h3>
                  <p>已经修复消息投影与收口排版，正文、表格、代码块和文件引用会统一跟随当前主题。</p>
                </header>
                <p>
                  关键改动集中在 <code>AssistantMessage.tsx</code> 与 <code>05-system-pages.css</code>，文件引用会保持清晰可点，长文本不会再挤压正文宽度。
                </p>
                <ul>
                  <li>正文使用当前字体与正文字号。</li>
                  <li>辅助信息保持低干扰，但仍具备可读对比度。</li>
                  <li>表格与代码块宽度跟随收口阅读区。</li>
                </ul>
                <pre><code>{`const preview = {
  status: "ready",
  layout: "responsive"
};`}</code></pre>
                <div className="system-config-appearance-preview__table">
                  <table>
                    <thead>
                      <tr>
                        <th>区域</th>
                        <th>效果</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        <td>正文</td>
                        <td>跟随字体与字号</td>
                      </tr>
                      <tr>
                        <td>代码</td>
                        <td>保持等宽与换行</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </article>
            </div>
            <dl className="system-config-appearance-preview__meta">
              <div>
                <dt>主题</dt>
                <dd>{activeTheme.label}<span>{themeToneLabel}</span></dd>
              </div>
              <div>
                <dt>字体</dt>
                <dd>{currentFont.label}<span>{fontSourceLabel}</span></dd>
              </div>
              <div>
                <dt>字号</dt>
                <dd>{Math.round(currentScale * 100)}%<span>UI {currentUiFontSize}px / 页面 {currentPageFontSize}px / 正文 {currentBodyFontSize}px</span></dd>
              </div>
              <div>
                <dt>颜色</dt>
                <dd>{colorModeLabel}<span>{enabledLabel(customSettings.customColorsEnabled)}</span></dd>
              </div>
              <div>
                <dt>背景</dt>
                <dd>{backgroundModeLabel}<span>{backgroundDetailLabel}</span></dd>
              </div>
              <div>
                <dt>画布</dt>
                <dd>遮罩 {appearancePercent(customSettings.chatCanvasVeil)}<span>质感 {appearancePercent(customSettings.textureIntensity)} / 面层 {appearancePercent(customSettings.chatSurfaceOpacity)}</span></dd>
              </div>
              <div>
                <dt>收口</dt>
                <dd>{Math.round(customSettings.closeoutMaxWidth)}px<span>最大阅读宽度</span></dd>
              </div>
            </dl>
          </div>
        </section>

        {/* ===== 主题模板 ===== */}
        <section className="system-config-field-section">
          <div className="system-config-field-section__head">
            <strong>主题模板</strong>
            <em>每个模板是一套我们调好的完整颜色；切换模板会回到模板默认色。</em>
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
              const active = currentFontId === font.id;
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

        {/* ===== 主题变量 ===== */}
        <section className="system-config-field-section">
          <div className="system-config-field-section__head">
            <strong>颜色与文字层级</strong>
            <em>{activeColorOverrideCount || activeTypographyOverrideCount ? `已自定义颜色 ${activeColorOverrideCount} 项，文字样式 ${activeTypographyOverrideCount} 项；单项重置后回到当前主题。` : "当前全部跟随主题；任意修改都会保存为自定义外观。"}</em>
          </div>
          <div className="system-config-token-groups">
            {WORKBENCH_COLOR_TOKEN_GROUPS.map((group) => {
              if (group.id === "text") {
                return renderTextTypographyGroup(group);
              }
              return (
                <details className="system-config-token-group" key={group.id} open>
                  <summary>{group.label}</summary>
                  <div className="system-config-token-grid">
                    {group.tokens.map((token) => {
                      const overrideColor = customSettings.colorOverrides[token.id] ?? "";
                      const resolvedColor = resolvedColorTokens[token.id] || "#ffffff";
                      const value = colorInputValue(overrideColor || resolvedColor);
                      return (
                        <label className="system-config-token-picker" key={token.id}>
                          <span
                            className="system-config-token-picker__swatch"
                            style={{ background: value }}
                          />
                          <span className="system-config-token-picker__copy">
                            <strong>{token.label}</strong>
                            <small>{token.description}</small>
                            <em>{overrideColor ? "已自定义" : "跟随当前主题"}</em>
                          </span>
                          <input
                            aria-label={`${token.label}颜色`}
                            type="color"
                            value={value}
                            onChange={(event) => handleColorTokenChange(token.id, event.target.value)}
                          />
                          {overrideColor ? (
                            <button
                              className="system-config-color-reset"
                              onClick={() => handleColorTokenChange(token.id, "")}
                              type="button"
                              title="恢复主题默认"
                            >
                              ✕
                            </button>
                          ) : null}
                        </label>
                      );
                    })}
                  </div>
                </details>
              );
            })}
          </div>
        </section>

        {/* ===== 会话画布 ===== */}
        <section className="system-config-field-section">
          <div className="system-config-field-section__head">
            <strong>会话画布参数</strong>
            <em>控制会话页背景、正文面层和收口阅读宽度。</em>
          </div>
          <div className="system-config-appearance-controls">
            <label>
              <span>背景遮罩强度</span>
              <input
                type="range"
                min="0"
                max="90"
                step="1"
                value={customSettings.chatCanvasVeil}
                onChange={(event) => handleAppearanceNumberChange({ chatCanvasVeil: Number(event.target.value) })}
              />
              <output>{Math.round(customSettings.chatCanvasVeil)}%</output>
            </label>
            <label>
              <span>纹理强度</span>
              <input
                type="range"
                min="0"
                max="100"
                step="1"
                value={customSettings.textureIntensity}
                onChange={(event) => handleAppearanceNumberChange({ textureIntensity: Number(event.target.value) })}
              />
              <output>{Math.round(customSettings.textureIntensity)}%</output>
            </label>
            <label>
              <span>会话面层透明度</span>
              <input
                type="range"
                min="35"
                max="100"
                step="1"
                value={customSettings.chatSurfaceOpacity}
                onChange={(event) => handleAppearanceNumberChange({ chatSurfaceOpacity: Number(event.target.value) })}
              />
              <output>{Math.round(customSettings.chatSurfaceOpacity)}%</output>
            </label>
            <label>
              <span>收口最大宽度</span>
              <input
                type="range"
                min="860"
                max="1480"
                step="20"
                value={customSettings.closeoutMaxWidth}
                onChange={(event) => handleAppearanceNumberChange({ closeoutMaxWidth: Number(event.target.value) })}
              />
              <output>{Math.round(customSettings.closeoutMaxWidth)}px</output>
            </label>
          </div>
        </section>

        {/* ===== 背景图片 ===== */}
        <section className="system-config-field-section">
          <div className="system-config-field-section__head">
            <strong>背景图片</strong>
            <em>只显示当前背景状态；画布效果以上方预览为准。</em>
          </div>
          <div className="system-config-bg-image-upload">
            <div className={`system-config-bg-status ${customSettings.bgImage ? "system-config-bg-status--active" : ""}`}>
              <span className="system-config-bg-status__thumb" aria-hidden="true">
                {customSettings.bgImage ? <img src={customSettings.bgImage} alt="" /> : <ImageIcon size={16} />}
              </span>
              <span className="system-config-bg-status__copy">
                <strong>{customSettings.bgImage ? "已上传背景图片" : "未设置背景图片"}</strong>
                <small>
                  {customSettings.bgImage
                    ? `已应用到会话画布 / ${backgroundImageDetailLabel(customSettings)} / 自动适配`
                    : "上传后会应用到会话画布背景。"}
                </small>
              </span>
              <div className="system-config-bg-status__actions">
                <label className="system-config-bg-image-action">
                  <input
                    disabled={backgroundImageBusy}
                    type="file"
                    accept="image/png,image/jpeg,image/gif,image/webp,image/svg+xml"
                    onChange={handleBgImageUpload}
                  />
                  <span>{customSettings.bgImage ? "更换" : backgroundImageBusy ? "处理中" : "选择图片"}</span>
                </label>
                {customSettings.bgImage ? (
                  <button disabled={backgroundImageBusy} onClick={handleRemoveBgImage} type="button" className="system-config-bg-image-remove">
                    移除
                  </button>
                ) : null}
              </div>
            </div>
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
          <p className="workspace-view__subtitle">管理模型、上下文、检索、文档解析、运行限制和界面外观。</p>
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
        <MetricCard detail="已保存的自定义配置项" detailAs="em" label="已改设置" value={overriddenCount} />
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

function colorInputValue(value: string | null | undefined) {
  const trimmed = String(value ?? "").trim();
  if (/^#[0-9a-f]{6}$/i.test(trimmed)) {
    return trimmed;
  }
  const rgb = trimmed.match(/^rgba?\((\d{1,3}),\s*(\d{1,3}),\s*(\d{1,3})/i);
  if (!rgb) {
    return "#ffffff";
  }
  return `#${[rgb[1], rgb[2], rgb[3]]
    .map((channel) => Math.max(0, Math.min(255, Number(channel))).toString(16).padStart(2, "0"))
    .join("")}`;
}
