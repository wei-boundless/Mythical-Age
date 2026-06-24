export type WorkbenchThemeId =
  | "clean-light"
  | "warm-paper"
  | "ocean-breeze"
  | "mineral-gray"
  | "lavender-mist"
  | "focus-dark"
  | "midnight-ocean"
  | "charcoal-ember";

export type WorkbenchFontId = "system" | "modern" | "classic" | "rounded" | "code-friendly";

export type WorkbenchDensity = "standard" | "compact";

export type WorkbenchThemeTemplate = {
  id: WorkbenchThemeId;
  label: string;
  description: string;
  mode: "light" | "dark";
  status: "built_in";
  accent: string;
  font: WorkbenchFontId;
  preview: {
    background: string;
    surface: string;
    text: string;
    accent: string;
  };
};

export type WorkbenchFontOption = {
  id: WorkbenchFontId;
  label: string;
  description: string;
  fontDisplay: string;
  fontMono: string;
  sampleSize: number;
};

export type WorkbenchDensityOption = {
  id: WorkbenchDensity;
  label: string;
  description: string;
};

export type WorkbenchColorTokenId =
  | "console-bg"
  | "console-bg-raised"
  | "console-surface"
  | "console-surface-muted"
  | "console-surface-strong"
  | "console-surface-soft"
  | "console-hover"
  | "console-selected"
  | "console-line"
  | "console-line-soft"
  | "console-line-strong"
  | "console-text"
  | "console-text-soft"
  | "console-muted"
  | "console-faint"
  | "console-accent"
  | "console-accent-hover"
  | "console-accent-soft"
  | "console-success"
  | "console-success-soft"
  | "console-warning"
  | "console-warning-soft"
  | "console-danger"
  | "console-danger-soft";

export type WorkbenchTextTokenId = Extract<
  WorkbenchColorTokenId,
  "console-text" | "console-text-soft" | "console-muted" | "console-faint"
>;

export type WorkbenchColorToken = {
  id: WorkbenchColorTokenId;
  label: string;
  description: string;
};

export type WorkbenchColorTokenGroup = {
  id: string;
  label: string;
  tokens: readonly WorkbenchColorToken[];
};

export type WorkbenchTextStyleOverride = {
  fontFamily?: string;
  fontSizePx?: number;
};

export const WORKBENCH_THEME_STORAGE_KEY = "workbenchTheme";
export const WORKBENCH_DENSITY_STORAGE_KEY = "workbenchDensity";
export const WORKBENCH_THEME_CHANGE_EVENT = "workbench-theme-change";
export const WORKBENCH_DENSITY_CHANGE_EVENT = "workbench-density-change";
export const DEFAULT_WORKBENCH_THEME_ID: WorkbenchThemeId = "clean-light";
export const DEFAULT_WORKBENCH_DENSITY: WorkbenchDensity = "standard";

export const WORKBENCH_THEME_TEMPLATES: readonly WorkbenchThemeTemplate[] = [
  {
    id: "clean-light",
    label: "清爽工作台",
    description: "高可读、低噪声的默认本地 Agent 工作台。",
    mode: "light",
    status: "built_in",
    accent: "#1d5fd3",
    font: "system",
    preview: {
      background: "#ffffff",
      surface: "#ffffff",
      text: "#111827",
      accent: "#1d5fd3",
    },
  },
  {
    id: "warm-paper",
    label: "暖纸",
    description: "暖色调浅色主题，纸张质感，适合长时间阅读。",
    mode: "light",
    status: "built_in",
    accent: "#b87c4b",
    font: "classic",
    preview: {
      background: "#faf7f0",
      surface: "#ffffff",
      text: "#2d2a24",
      accent: "#b87c4b",
    },
  },
  {
    id: "ocean-breeze",
    label: "海风",
    description: "清爽冷调浅色主题，蓝色系视觉舒适。",
    mode: "light",
    status: "built_in",
    accent: "#2a7faa",
    font: "modern",
    preview: {
      background: "#f0f5fa",
      surface: "#ffffff",
      text: "#1a2a3a",
      accent: "#2a7faa",
    },
  },
  {
    id: "mineral-gray",
    label: "矿物灰",
    description: "中性极简浅色主题，低视觉干扰。",
    mode: "light",
    status: "built_in",
    accent: "#6b7280",
    font: "system",
    preview: {
      background: "#f2f2f2",
      surface: "#ffffff",
      text: "#1f1f1f",
      accent: "#6b7280",
    },
  },
  {
    id: "lavender-mist",
    label: "薰衣草雾",
    description: "淡紫色调浅色主题，柔和舒适。",
    mode: "light",
    status: "built_in",
    accent: "#7c5cbf",
    font: "rounded",
    preview: {
      background: "#f5f0fb",
      surface: "#ffffff",
      text: "#1e1a2e",
      accent: "#7c5cbf",
    },
  },
  {
    id: "focus-dark",
    label: "专注暗色",
    description: "低亮度工作模板，适合长时间运行监控和夜间使用。",
    mode: "dark",
    status: "built_in",
    accent: "#7fb2ff",
    font: "system",
    preview: {
      background: "#0f1720",
      surface: "#17212d",
      text: "#edf4ff",
      accent: "#7fb2ff",
    },
  },
  {
    id: "midnight-ocean",
    label: "午夜海洋",
    description: "深蓝暗色主题，深邃沉浸。",
    mode: "dark",
    status: "built_in",
    accent: "#5b9bd5",
    font: "modern",
    preview: {
      background: "#0a1628",
      surface: "#111d35",
      text: "#dce8f5",
      accent: "#5b9bd5",
    },
  },
  {
    id: "charcoal-ember",
    label: "炭火星",
    description: "暖调暗色主题，炭火般温暖的低光体验。",
    mode: "dark",
    status: "built_in",
    accent: "#d4835a",
    font: "rounded",
    preview: {
      background: "#1a1410",
      surface: "#241e18",
      text: "#e8ddd0",
      accent: "#d4835a",
    },
  },
];

export const WORKBENCH_FONT_OPTIONS: readonly WorkbenchFontOption[] = [
  {
    id: "system",
    label: "系统默认",
    description: "基于系统字体的无衬线体验。",
    fontDisplay: "system-ui, -apple-system, BlinkMacSystemFont, \"Segoe UI\", \"Microsoft YaHei UI\", \"PingFang SC\", \"Noto Sans SC\", sans-serif",
    fontMono: "\"Cascadia Mono\", \"Consolas\", \"SFMono-Regular\", monospace",
    sampleSize: 15,
  },
  {
    id: "modern",
    label: "现代无衬线",
    description: "Inter 搭配 Noto Sans SC，清晰现代。",
    fontDisplay: "\"Inter\", \"Noto Sans SC\", \"Segoe UI Variable\", -apple-system, system-ui, sans-serif",
    fontMono: "\"JetBrains Mono\", \"Fira Code\", \"Cascadia Code\", \"Consolas\", monospace",
    sampleSize: 15,
  },
  {
    id: "classic",
    label: "经典衬线",
    description: "Noto Serif SC 搭配 Source Serif 4，温润的衬线阅读体验。",
    fontDisplay: "\"Noto Serif SC\", \"Source Serif 4\", \"Palatino Linotype\", \"Palatino\", Georgia, serif",
    fontMono: "\"Cascadia Mono\", \"Consolas\", \"SFMono-Regular\", monospace",
    sampleSize: 16,
  },
  {
    id: "rounded",
    label: "圆润柔和",
    description: "Nunito 搭配 Noto Sans SC，亲和友好的圆角字形。",
    fontDisplay: "\"Nunito\", \"Noto Sans SC\", \"PingFang SC\", \"Microsoft YaHei UI\", system-ui, sans-serif",
    fontMono: "\"Cascadia Mono\", \"Consolas\", \"SFMono-Regular\", monospace",
    sampleSize: 15,
  },
  {
    id: "code-friendly",
    label: "代码友好",
    description: "等宽优先，代码和正文兼顾。",
    fontDisplay: "\"SF Mono\", \"Cascadia Code\", \"JetBrains Mono\", \"Consolas\", monospace",
    fontMono: "\"SF Mono\", \"Cascadia Code\", \"JetBrains Mono\", \"Consolas\", monospace",
    sampleSize: 14,
  },
];

export const WORKBENCH_DENSITY_OPTIONS: readonly WorkbenchDensityOption[] = [
  {
    id: "standard",
    label: "标准",
    description: "默认阅读距离，列表和面板保持自然间距。",
  },
  {
    id: "compact",
    label: "紧凑",
    description: "提高列表密度，适合大量会话、文件和任务。",
  },
];

export const WORKBENCH_COLOR_TOKEN_GROUPS: readonly WorkbenchColorTokenGroup[] = [
  {
    id: "surface",
    label: "基础表面",
    tokens: [
      { id: "console-bg", label: "背景", description: "工作台底色和会话画布基色。" },
      { id: "console-bg-raised", label: "抬升背景", description: "代码块、次级区域和弱面板底色。" },
      { id: "console-surface", label: "面板", description: "卡片、输入区和主要面板底色。" },
      { id: "console-surface-muted", label: "弱面板", description: "标签、按钮和辅助块底色。" },
      { id: "console-surface-strong", label: "强面板", description: "悬停态、强调块和浮层边缘。" },
      { id: "console-surface-soft", label: "柔和面板", description: "浅层 hover 与弱分组背景。" },
    ],
  },
  {
    id: "text",
    label: "文字层级",
    tokens: [
      { id: "console-text", label: "正文", description: "主要正文、标题和高优先级信息。" },
      { id: "console-text-soft", label: "次正文", description: "较弱的正文、说明和二级内容。" },
      { id: "console-muted", label: "辅助文字", description: "提示、状态说明和元信息。" },
      { id: "console-faint", label: "弱提示", description: "最低权重的标签和占位信息。" },
    ],
  },
  {
    id: "line",
    label: "边线与选择",
    tokens: [
      { id: "console-line", label: "边线", description: "常规边框、分割线和表格线。" },
      { id: "console-line-soft", label: "弱边线", description: "浅分割、内层边框和低对比边线。" },
      { id: "console-line-strong", label: "强边线", description: "表格外框、聚焦边缘和强分割。" },
      { id: "console-hover", label: "悬停", description: "列表、按钮和可点击元素 hover 底色。" },
      { id: "console-selected", label: "选中", description: "当前项、选中态和激活行底色。" },
    ],
  },
  {
    id: "accent",
    label: "强调与状态",
    tokens: [
      { id: "console-accent", label: "强调", description: "链接、主操作、图标和当前焦点色。" },
      { id: "console-accent-hover", label: "强调悬停", description: "强调元素 hover 和高亮态。" },
      { id: "console-accent-soft", label: "强调背景", description: "强调元素的柔和底色。" },
      { id: "console-success", label: "成功", description: "成功状态、完成态和正向标识。" },
      { id: "console-success-soft", label: "成功背景", description: "成功状态的柔和底色。" },
      { id: "console-warning", label: "警告", description: "等待、注意和阈值风险。" },
      { id: "console-warning-soft", label: "警告背景", description: "警告状态的柔和底色。" },
      { id: "console-danger", label: "危险", description: "错误、失败和危险操作。" },
      { id: "console-danger-soft", label: "危险背景", description: "错误状态的柔和底色。" },
    ],
  },
];

const WORKBENCH_COLOR_TOKEN_IDS = new Set(
  WORKBENCH_COLOR_TOKEN_GROUPS.flatMap((group) => group.tokens.map((token) => token.id)),
);

export const WORKBENCH_TEXT_TOKEN_IDS: readonly WorkbenchTextTokenId[] = [
  "console-text",
  "console-text-soft",
  "console-muted",
  "console-faint",
];

const WORKBENCH_TEXT_TOKEN_ID_SET: ReadonlySet<string> = new Set(WORKBENCH_TEXT_TOKEN_IDS);

const WORKBENCH_TEXT_STYLE_CSS_VARS: Record<WorkbenchTextTokenId, { font: string; size: string }> = {
  "console-text": { font: "--console-text-font", size: "--console-text-size" },
  "console-text-soft": { font: "--console-text-soft-font", size: "--console-text-soft-size" },
  "console-muted": { font: "--console-muted-font", size: "--console-muted-size" },
  "console-faint": { font: "--console-faint-font", size: "--console-faint-size" },
};

const WORKBENCH_THEME_IDS: ReadonlySet<string> = new Set(WORKBENCH_THEME_TEMPLATES.map((theme) => theme.id));
const WORKBENCH_DENSITY_IDS: ReadonlySet<string> = new Set(WORKBENCH_DENSITY_OPTIONS.map((density) => density.id));

export function resolveWorkbenchThemeId(value: string | null | undefined): WorkbenchThemeId {
  return WORKBENCH_THEME_IDS.has(String(value || "")) ? value as WorkbenchThemeId : DEFAULT_WORKBENCH_THEME_ID;
}

export function resolveWorkbenchDensity(value: string | null | undefined): WorkbenchDensity {
  return WORKBENCH_DENSITY_IDS.has(String(value || "")) ? value as WorkbenchDensity : DEFAULT_WORKBENCH_DENSITY;
}

export function workbenchThemeById(value: string | null | undefined) {
  const themeId = resolveWorkbenchThemeId(value);
  return WORKBENCH_THEME_TEMPLATES.find((theme) => theme.id === themeId) ?? WORKBENCH_THEME_TEMPLATES[0];
}

export function getStoredWorkbenchTheme(): WorkbenchThemeId {
  if (typeof window === "undefined") return DEFAULT_WORKBENCH_THEME_ID;
  return resolveWorkbenchThemeId(window.localStorage.getItem(WORKBENCH_THEME_STORAGE_KEY));
}

export function getStoredWorkbenchDensity(): WorkbenchDensity {
  if (typeof window === "undefined") return DEFAULT_WORKBENCH_DENSITY;
  return resolveWorkbenchDensity(window.localStorage.getItem(WORKBENCH_DENSITY_STORAGE_KEY));
}

export function applyWorkbenchAppearance(
  themeId: WorkbenchThemeId = getStoredWorkbenchTheme(),
  density: WorkbenchDensity = getStoredWorkbenchDensity(),
) {
  if (typeof document === "undefined") return;
  const resolvedTheme = resolveWorkbenchThemeId(themeId);
  const resolvedDensity = resolveWorkbenchDensity(density);
  document.documentElement.dataset.workbenchTheme = resolvedTheme;
  document.documentElement.dataset.workbenchDensity = resolvedDensity;
  document.documentElement.style.colorScheme = workbenchThemeById(resolvedTheme).mode;
  // Apply only explicitly enabled user tweaks on top of the selected template.
  const customSettings = getStoredCustomSettings();
  applyAppearanceOverrides(customSettings);
}

export type SetWorkbenchThemeOptions = {
  preserveCustomColors?: boolean;
};

export function setStoredWorkbenchTheme(themeId: string, options: SetWorkbenchThemeOptions = {}) {
  if (typeof window === "undefined") return;
  const resolvedTheme = resolveWorkbenchThemeId(themeId);
  window.localStorage.setItem(WORKBENCH_THEME_STORAGE_KEY, resolvedTheme);
  if (!options.preserveCustomColors) {
    clearCustomColorOverrides();
  }
  applyWorkbenchAppearance(resolvedTheme, getStoredWorkbenchDensity());
  window.dispatchEvent(new CustomEvent(WORKBENCH_THEME_CHANGE_EVENT, { detail: { themeId: resolvedTheme } }));
}

/* ===== 自定义覆盖设置 ===== */

export type CustomAppearanceSettings = {
  fontOverride: WorkbenchFontId | null;
  fontSizeScale: number; // 0.8 ~ 1.3, 默认为 1
  customColorsEnabled: boolean;
  colorOverrides: Partial<Record<WorkbenchColorTokenId, string>>;
  textStyleOverrides: Partial<Record<WorkbenchTextTokenId, WorkbenchTextStyleOverride>>;
  bgColor: string | null;
  panelColor: string | null;
  accentSoftColor: string | null;
  bgImage: string | null;
  bgImageMeta: WorkbenchBackgroundImageMeta | null;
  chatCanvasVeil: number;
  chatSurfaceOpacity: number;
  closeoutMaxWidth: number;
  textureIntensity: number;
};

export type WorkbenchBackgroundImageMeta = {
  width: number;
  height: number;
  aspectRatio: number;
};

export const DEFAULT_CUSTOM_SETTINGS: CustomAppearanceSettings = {
  fontOverride: null,
  fontSizeScale: 1,
  customColorsEnabled: false,
  colorOverrides: {},
  textStyleOverrides: {},
  bgColor: null,
  panelColor: null,
  accentSoftColor: null,
  bgImage: null,
  bgImageMeta: null,
  chatCanvasVeil: 34,
  chatSurfaceOpacity: 72,
  closeoutMaxWidth: 1180,
  textureIntensity: 100,
};

export const WORKBENCH_CUSTOM_SETTINGS_KEY = "workbenchCustomSettings";
export const WORKBENCH_CUSTOM_SETTINGS_CHANGE_EVENT = "workbench-custom-settings-change";

function normalizeCustomAppearanceSettings(settings: Partial<CustomAppearanceSettings> = {}): CustomAppearanceSettings {
  const next = { ...DEFAULT_CUSTOM_SETTINGS, ...settings };
  const explicitColorOverrides = normalizeColorOverrides(next.colorOverrides);
  const hasExplicitColorOverrides = Object.keys(explicitColorOverrides).length > 0;
  const migratedColorOverrides = hasExplicitColorOverrides
    ? explicitColorOverrides
    : normalizeColorOverrides({
      "console-bg": next.bgColor,
      "console-surface": next.panelColor,
      "console-bg-raised": next.panelColor,
      "console-accent-soft": next.accentSoftColor,
    });
  const customColorsEnabled = next.customColorsEnabled === true && Object.keys(migratedColorOverrides).length > 0;

  return {
    fontOverride: next.fontOverride,
    fontSizeScale: Number.isFinite(next.fontSizeScale) ? Math.min(1.3, Math.max(0.8, next.fontSizeScale)) : DEFAULT_CUSTOM_SETTINGS.fontSizeScale,
    customColorsEnabled,
    colorOverrides: customColorsEnabled ? migratedColorOverrides : {},
    textStyleOverrides: normalizeTextStyleOverrides(next.textStyleOverrides),
    bgColor: customColorsEnabled ? migratedColorOverrides["console-bg"] ?? null : null,
    panelColor: customColorsEnabled ? migratedColorOverrides["console-surface"] ?? migratedColorOverrides["console-bg-raised"] ?? null : null,
    accentSoftColor: customColorsEnabled ? migratedColorOverrides["console-accent-soft"] ?? null : null,
    bgImage: typeof next.bgImage === "string" && next.bgImage.trim() ? next.bgImage : null,
    bgImageMeta: typeof next.bgImage === "string" && next.bgImage.trim() ? normalizeBackgroundImageMeta(next.bgImageMeta) : null,
    chatCanvasVeil: Number.isFinite(next.chatCanvasVeil) ? Math.min(90, Math.max(0, next.chatCanvasVeil)) : DEFAULT_CUSTOM_SETTINGS.chatCanvasVeil,
    chatSurfaceOpacity: Number.isFinite(next.chatSurfaceOpacity) ? Math.min(100, Math.max(35, next.chatSurfaceOpacity)) : DEFAULT_CUSTOM_SETTINGS.chatSurfaceOpacity,
    closeoutMaxWidth: Number.isFinite(next.closeoutMaxWidth) ? Math.min(1480, Math.max(860, next.closeoutMaxWidth)) : DEFAULT_CUSTOM_SETTINGS.closeoutMaxWidth,
    textureIntensity: Number.isFinite(next.textureIntensity) ? Math.min(100, Math.max(0, next.textureIntensity)) : DEFAULT_CUSTOM_SETTINGS.textureIntensity,
  };
}

function normalizeBackgroundImageMeta(value: unknown): WorkbenchBackgroundImageMeta | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const source = value as Record<string, unknown>;
  const width = Number(source.width);
  const height = Number(source.height);
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    return null;
  }
  const roundedWidth = Math.round(width);
  const roundedHeight = Math.round(height);
  return {
    width: roundedWidth,
    height: roundedHeight,
    aspectRatio: Number((roundedWidth / roundedHeight).toFixed(4)),
  };
}

function normalizeColorOverrides(value: unknown): Partial<Record<WorkbenchColorTokenId, string>> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {};
  }
  const normalized: Partial<Record<WorkbenchColorTokenId, string>> = {};
  Object.entries(value as Record<string, unknown>).forEach(([tokenId, color]) => {
    if (!WORKBENCH_COLOR_TOKEN_IDS.has(tokenId as WorkbenchColorTokenId)) {
      return;
    }
    const value = typeof color === "string" ? color.trim() : "";
    if (/^#[0-9a-f]{6}$/i.test(value)) {
      normalized[tokenId as WorkbenchColorTokenId] = value;
    }
  });
  return normalized;
}

function normalizeTextStyleOverrides(value: unknown): Partial<Record<WorkbenchTextTokenId, WorkbenchTextStyleOverride>> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {};
  }
  const normalized: Partial<Record<WorkbenchTextTokenId, WorkbenchTextStyleOverride>> = {};
  Object.entries(value as Record<string, unknown>).forEach(([tokenId, style]) => {
    if (!WORKBENCH_TEXT_TOKEN_ID_SET.has(tokenId)) {
      return;
    }
    if (!style || typeof style !== "object" || Array.isArray(style)) {
      return;
    }
    const source = style as Record<string, unknown>;
    const nextStyle: WorkbenchTextStyleOverride = {};
    const fontFamily = normalizeFontFamily(source.fontFamily);
    if (fontFamily) {
      nextStyle.fontFamily = fontFamily;
    }
    const fontSizePx = normalizeTextFontSize(source.fontSizePx);
    if (fontSizePx) {
      nextStyle.fontSizePx = fontSizePx;
    }
    if (nextStyle.fontFamily || nextStyle.fontSizePx) {
      normalized[tokenId as WorkbenchTextTokenId] = nextStyle;
    }
  });
  return normalized;
}

function normalizeFontFamily(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const normalized = value.trim().replace(/[;{}<>]/g, "").slice(0, 180);
  return normalized || undefined;
}

function normalizeTextFontSize(value: unknown): number | undefined {
  const size = Number(value);
  if (!Number.isFinite(size)) return undefined;
  return Math.min(32, Math.max(10, Math.round(size)));
}

type WorkbenchAppearanceWindow = Window & {
  __workbenchBackgroundObjectUrl?: {
    source: string;
    url: string;
  };
};

function imageUrlCssValue(value: string) {
  return `url(${JSON.stringify(value)})`;
}

function releaseBackgroundObjectUrl() {
  if (typeof window === "undefined") return;
  const target = window as WorkbenchAppearanceWindow;
  const current = target.__workbenchBackgroundObjectUrl;
  if (!current) return;
  URL.revokeObjectURL(current.url);
  target.__workbenchBackgroundObjectUrl = undefined;
}

function dataUrlToBlob(value: string): Blob | null {
  const commaIndex = value.indexOf(",");
  if (!value.startsWith("data:") || commaIndex < 0) {
    return null;
  }
  const header = value.slice(0, commaIndex);
  const body = value.slice(commaIndex + 1);
  const mimeType = header.match(/^data:([^;,]+)/i)?.[1] || "application/octet-stream";
  const isBase64 = /;base64/i.test(header);
  const binary = isBase64 ? window.atob(body) : decodeURIComponent(body);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return new Blob([bytes], { type: mimeType });
}

function resolveBackgroundImagePaintUrl(value: string) {
  if (typeof window === "undefined" || !value.startsWith("data:")) {
    return value;
  }
  const target = window as WorkbenchAppearanceWindow;
  const current = target.__workbenchBackgroundObjectUrl;
  if (current?.source === value) {
    return current.url;
  }
  releaseBackgroundObjectUrl();
  try {
    const blob = dataUrlToBlob(value);
    if (!blob) {
      return value;
    }
    const url = URL.createObjectURL(blob);
    target.__workbenchBackgroundObjectUrl = { source: value, url };
    return url;
  } catch {
    return value;
  }
}

export function getStoredCustomSettings(): CustomAppearanceSettings {
  if (typeof window === "undefined") return { ...DEFAULT_CUSTOM_SETTINGS };
  try {
    const raw = window.localStorage.getItem(WORKBENCH_CUSTOM_SETTINGS_KEY);
    if (!raw) return { ...DEFAULT_CUSTOM_SETTINGS };
    return normalizeCustomAppearanceSettings(JSON.parse(raw));
  } catch {
    return { ...DEFAULT_CUSTOM_SETTINGS };
  }
}

export function setStoredCustomSettings(settings: Partial<CustomAppearanceSettings>): CustomAppearanceSettings {
  const current = getStoredCustomSettings();
  const merged: Partial<CustomAppearanceSettings> = { ...current, ...settings };
  if ("bgImage" in settings && settings.bgImage !== current.bgImage && !("bgImageMeta" in settings)) {
    merged.bgImageMeta = null;
  }
  const next = normalizeCustomAppearanceSettings(merged);
  if (typeof window === "undefined") return next;
  window.localStorage.setItem(WORKBENCH_CUSTOM_SETTINGS_KEY, JSON.stringify(next));
  applyAppearanceOverrides(next);
  window.dispatchEvent(new CustomEvent(WORKBENCH_CUSTOM_SETTINGS_CHANGE_EVENT, { detail: next }));
  return next;
}

type BackgroundImageLayoutVars = {
  baseSize: string;
  basePosition: string;
  baseRepeat: string;
};

function resolveBackgroundImageLayout(hasImage: boolean): BackgroundImageLayoutVars {
  if (!hasImage) {
    return {
      baseSize: "cover",
      basePosition: "center center",
      baseRepeat: "no-repeat",
    };
  }

  return {
    baseSize: "cover",
    basePosition: "center top",
    baseRepeat: "no-repeat",
  };
}

function backgroundVeilVars(hasImage: boolean, veil: number) {
  const value = Math.round(Number.isFinite(veil) ? veil : DEFAULT_CUSTOM_SETTINGS.chatCanvasVeil);
  if (!hasImage) {
    return {
      center: `${value}%`,
      edge: `${value}%`,
      top: `${value}%`,
      bottom: `${value}%`,
    };
  }
  return {
    center: `${Math.min(76, Math.max(0, value))}%`,
    edge: `${Math.min(90, Math.max(0, value + 22))}%`,
    top: `${Math.min(84, Math.max(0, value + 12))}%`,
    bottom: `${Math.min(96, Math.max(0, value + 40))}%`,
  };
}

let backgroundImageProbeId = 0;

function probeLegacyBackgroundImageMeta(settings: CustomAppearanceSettings) {
  if (typeof window === "undefined" || !settings.bgImage || settings.bgImageMeta) {
    return;
  }
  const probeId = ++backgroundImageProbeId;
  const image = new Image();
  image.onload = () => {
    if (probeId !== backgroundImageProbeId) return;
    const width = image.naturalWidth || image.width;
    const height = image.naturalHeight || image.height;
    if (!width || !height) return;
    const current = getStoredCustomSettings();
    if (current.bgImage !== settings.bgImage || current.bgImageMeta) return;
    setStoredCustomSettings({
      bgImageMeta: {
        width,
        height,
        aspectRatio: Number((width / height).toFixed(4)),
      },
    });
  };
  image.src = settings.bgImage;
}

export function clearCustomColorOverrides(): CustomAppearanceSettings {
  if (typeof window === "undefined") return { ...DEFAULT_CUSTOM_SETTINGS };
  const next = normalizeCustomAppearanceSettings({
    ...getStoredCustomSettings(),
    customColorsEnabled: false,
    colorOverrides: {},
    bgColor: null,
    panelColor: null,
    accentSoftColor: null,
  });
  window.localStorage.setItem(WORKBENCH_CUSTOM_SETTINGS_KEY, JSON.stringify(next));
  applyAppearanceOverrides(next);
  window.dispatchEvent(new CustomEvent(WORKBENCH_CUSTOM_SETTINGS_CHANGE_EVENT, { detail: next }));
  return next;
}

export function applyAppearanceOverrides(settings: CustomAppearanceSettings) {
  if (typeof document === "undefined") return;
  const root = document.documentElement;

  // Font: theme templates provide the base face; user override wins when present.
  const themeFontId = workbenchThemeById(getStoredWorkbenchTheme()).font;
  const font = WORKBENCH_FONT_OPTIONS.find((f) => f.id === (settings.fontOverride ?? themeFontId));
  if (font) {
    root.style.setProperty("--font-display", font.fontDisplay);
    root.style.setProperty("--font-mono", font.fontMono);
    // Also set all font aliases directly to bypass any :root chain issues
    root.style.setProperty("--console-font", font.fontDisplay);
    root.style.setProperty("--console-mono", font.fontMono);
    root.style.setProperty("--workbench-font", font.fontDisplay);
    root.style.setProperty("--workbench-font-mono", font.fontMono);
    root.style.setProperty("--font-sans", font.fontDisplay);
    root.style.setProperty("--font-brand-latin", font.fontDisplay);
  }

  // Font size scale
  const scale = settings.fontSizeScale;
  const baseUi = 15;
  const basePage = 16;
  const baseBody = 17;
  root.style.setProperty("--console-font-size-ui", `${Math.round(baseUi * scale)}px`);
  root.style.setProperty("--console-font-size-page", `${Math.round(basePage * scale)}px`);
  root.style.setProperty("--console-font-size-body", `${Math.round(baseBody * scale)}px`);
  root.style.fontSize = `${Math.round(baseUi * scale)}px`;

  WORKBENCH_COLOR_TOKEN_IDS.forEach((tokenId) => {
    root.style.removeProperty(`--${tokenId}`);
  });
  Object.values(WORKBENCH_TEXT_STYLE_CSS_VARS).forEach((vars) => {
    root.style.removeProperty(vars.font);
    root.style.removeProperty(vars.size);
  });

  if (settings.customColorsEnabled) {
    Object.entries(settings.colorOverrides).forEach(([tokenId, color]) => {
      if (color && WORKBENCH_COLOR_TOKEN_IDS.has(tokenId as WorkbenchColorTokenId)) {
        root.style.setProperty(`--${tokenId}`, color);
      }
    });
  }
  Object.entries(settings.textStyleOverrides).forEach(([tokenId, style]) => {
    if (!WORKBENCH_TEXT_TOKEN_ID_SET.has(tokenId) || !style) return;
    const vars = WORKBENCH_TEXT_STYLE_CSS_VARS[tokenId as WorkbenchTextTokenId];
    if (style.fontFamily) {
      root.style.setProperty(vars.font, style.fontFamily);
    }
    if (style.fontSizePx) {
      root.style.setProperty(vars.size, `${style.fontSizePx}px`);
    }
  });

  // Background image: one layout authority computes variables; CSS decides where to paint them.
  const hasBackgroundImage = Boolean(settings.bgImage);
  const backgroundLayout = resolveBackgroundImageLayout(hasBackgroundImage);
  const backgroundVeil = backgroundVeilVars(hasBackgroundImage, settings.chatCanvasVeil);
  if (settings.bgImage) {
    root.style.setProperty("--workbench-bg-image", imageUrlCssValue(resolveBackgroundImagePaintUrl(settings.bgImage)));
  } else {
    releaseBackgroundObjectUrl();
    root.style.setProperty("--workbench-bg-image", "none");
  }
  root.style.setProperty("--workbench-bg-size", backgroundLayout.baseSize);
  root.style.setProperty("--workbench-bg-position", backgroundLayout.basePosition);
  root.style.setProperty("--workbench-bg-repeat", backgroundLayout.baseRepeat);
  root.style.setProperty("--workbench-bg-veil-center", backgroundVeil.center);
  root.style.setProperty("--workbench-bg-veil-edge", backgroundVeil.edge);
  root.style.setProperty("--workbench-bg-veil-top", backgroundVeil.top);
  root.style.setProperty("--workbench-bg-veil-bottom", backgroundVeil.bottom);
  probeLegacyBackgroundImageMeta(settings);

  root.style.setProperty("--chat-canvas-veil", `${Math.round(settings.chatCanvasVeil)}%`);
  root.style.setProperty("--chat-canvas-veil-soft", `${Math.max(0, Math.round(settings.chatCanvasVeil) - 14)}%`);
  root.style.setProperty("--chat-panel-surface-alpha", `${Math.round(settings.chatSurfaceOpacity)}%`);
  root.style.setProperty("--chat-panel-surface-alpha-soft", `${Math.max(0, Math.round(settings.chatSurfaceOpacity) - 18)}%`);
  root.style.setProperty("--workspace-bg-texture-opacity", `${Math.round(settings.textureIntensity) / 100}`);
  root.style.setProperty("--closeout-content-max", `${Math.round(settings.closeoutMaxWidth)}px`);
}

export function clearCustomOverrides() {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  window.localStorage.removeItem(WORKBENCH_CUSTOM_SETTINGS_KEY);
  // Remove inline style overrides before applying the current template defaults.
  root.style.removeProperty("--font-display");
  root.style.removeProperty("--font-mono");
  root.style.removeProperty("--console-font-size-ui");
  root.style.removeProperty("--console-font-size-page");
  root.style.removeProperty("--console-font-size-body");
  root.style.removeProperty("font-size");
  WORKBENCH_COLOR_TOKEN_IDS.forEach((tokenId) => {
    root.style.removeProperty(`--${tokenId}`);
  });
  Object.values(WORKBENCH_TEXT_STYLE_CSS_VARS).forEach((vars) => {
    root.style.removeProperty(vars.font);
    root.style.removeProperty(vars.size);
  });
  root.style.removeProperty("--workbench-bg-image");
  releaseBackgroundObjectUrl();
  root.style.removeProperty("--workbench-bg-size");
  root.style.removeProperty("--workbench-bg-position");
  root.style.removeProperty("--workbench-bg-repeat");
  root.style.removeProperty("--workbench-bg-veil-center");
  root.style.removeProperty("--workbench-bg-veil-edge");
  root.style.removeProperty("--workbench-bg-veil-top");
  root.style.removeProperty("--workbench-bg-veil-bottom");
  root.style.removeProperty("--chat-canvas-veil");
  root.style.removeProperty("--chat-canvas-veil-soft");
  root.style.removeProperty("--chat-panel-surface-alpha");
  root.style.removeProperty("--chat-panel-surface-alpha-soft");
  root.style.removeProperty("--workspace-bg-texture-opacity");
  root.style.removeProperty("--closeout-content-max");
  applyWorkbenchAppearance(getStoredWorkbenchTheme(), getStoredWorkbenchDensity());
}

export function setStoredWorkbenchDensity(density: string) {
  if (typeof window === "undefined") return;
  const resolvedDensity = resolveWorkbenchDensity(density);
  window.localStorage.setItem(WORKBENCH_DENSITY_STORAGE_KEY, resolvedDensity);
  applyWorkbenchAppearance(getStoredWorkbenchTheme(), resolvedDensity);
  window.dispatchEvent(new CustomEvent(WORKBENCH_DENSITY_CHANGE_EVENT, { detail: { density: resolvedDensity } }));
}
