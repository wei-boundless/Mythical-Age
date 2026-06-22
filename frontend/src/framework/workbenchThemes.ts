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
    fontDisplay: "\"Microsoft YaHei UI\", \"Microsoft YaHei\", \"PingFang SC\", \"Noto Sans CJK SC\", system-ui, sans-serif",
    fontMono: "\"Cascadia Mono\", \"Consolas\", \"SFMono-Regular\", monospace",
    sampleSize: 15,
  },
  {
    id: "modern",
    label: "现代无衬线",
    description: "更现代的无衬线字体，清晰锐利。",
    fontDisplay: "\"Inter\", \"Segoe UI Variable\", \"SF Pro Text\", -apple-system, system-ui, sans-serif",
    fontMono: "\"JetBrains Mono\", \"Fira Code\", \"Cascadia Code\", \"Consolas\", monospace",
    sampleSize: 15,
  },
  {
    id: "classic",
    label: "经典衬线",
    description: "暖调衬线感，适合阅读密集型内容。",
    fontDisplay: "\"Iowan Old Style\", \"Palatino Linotype\", \"Palatino\", \"Noto Serif CJK SC\", \"Source Han Serif SC\", Georgia, serif",
    fontMono: "\"Cascadia Mono\", \"Consolas\", \"SFMono-Regular\", monospace",
    sampleSize: 16,
  },
  {
    id: "rounded",
    label: "圆润柔和",
    description: "圆角字形，亲和友好。",
    fontDisplay: "\"Nunito\", \"Quicksand\", \"Microsoft YaHei UI\", \"PingFang SC\", system-ui, sans-serif",
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
  // Re-apply custom overrides after theme change
  const customSettings = getStoredCustomSettings();
  applyAppearanceOverrides(customSettings);
}

export function setStoredWorkbenchTheme(themeId: string) {
  if (typeof window === "undefined") return;
  const resolvedTheme = resolveWorkbenchThemeId(themeId);
  window.localStorage.setItem(WORKBENCH_THEME_STORAGE_KEY, resolvedTheme);
  applyWorkbenchAppearance(resolvedTheme, getStoredWorkbenchDensity());
  window.dispatchEvent(new CustomEvent(WORKBENCH_THEME_CHANGE_EVENT, { detail: { themeId: resolvedTheme } }));
}

/* ===== 自定义覆盖设置 ===== */

export type CustomAppearanceSettings = {
  fontOverride: WorkbenchFontId | null;
  fontSizeScale: number; // 0.8 ~ 1.3, 默认为 1
  bgColor: string | null;
  panelColor: string | null;
  accentSoftColor: string | null;
  bgImage: string | null;
};

export const DEFAULT_CUSTOM_SETTINGS: CustomAppearanceSettings = {
  fontOverride: null,
  fontSizeScale: 1,
  bgColor: null,
  panelColor: null,
  accentSoftColor: null,
  bgImage: null,
};

export const WORKBENCH_CUSTOM_SETTINGS_KEY = "workbenchCustomSettings";
export const WORKBENCH_CUSTOM_SETTINGS_CHANGE_EVENT = "workbench-custom-settings-change";

export function getStoredCustomSettings(): CustomAppearanceSettings {
  if (typeof window === "undefined") return { ...DEFAULT_CUSTOM_SETTINGS };
  try {
    const raw = window.localStorage.getItem(WORKBENCH_CUSTOM_SETTINGS_KEY);
    if (!raw) return { ...DEFAULT_CUSTOM_SETTINGS };
    return { ...DEFAULT_CUSTOM_SETTINGS, ...JSON.parse(raw) };
  } catch {
    return { ...DEFAULT_CUSTOM_SETTINGS };
  }
}

export function setStoredCustomSettings(settings: Partial<CustomAppearanceSettings>) {
  if (typeof window === "undefined") return;
  const current = getStoredCustomSettings();
  const next = { ...current, ...settings };
  window.localStorage.setItem(WORKBENCH_CUSTOM_SETTINGS_KEY, JSON.stringify(next));
  applyAppearanceOverrides(next);
  window.dispatchEvent(new CustomEvent(WORKBENCH_CUSTOM_SETTINGS_CHANGE_EVENT, { detail: next }));
}

export function applyAppearanceOverrides(settings: CustomAppearanceSettings) {
  if (typeof document === "undefined") return;
  const root = document.documentElement;

  // Font
  const font = WORKBENCH_FONT_OPTIONS.find((f) => f.id === settings.fontOverride);
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

  // Background color override
  if (settings.bgColor) {
    root.style.setProperty("--console-bg", settings.bgColor);
  }

  // Panel/surface color override
  if (settings.panelColor) {
    root.style.setProperty("--console-surface", settings.panelColor);
    root.style.setProperty("--console-bg-raised", settings.panelColor);
  }

  // Accent soft color override (highlight/emphasis background)
  if (settings.accentSoftColor) {
    root.style.setProperty("--console-accent-soft", settings.accentSoftColor);
  }

  // Background image
  if (settings.bgImage) {
    root.style.setProperty("--workbench-bg-image", `url("${settings.bgImage}")`);
  } else {
    root.style.setProperty("--workbench-bg-image", "none");
  }
}

export function clearCustomOverrides() {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  // Re-apply theme base
  const themeId = getStoredWorkbenchTheme();
  applyWorkbenchAppearance(themeId, getStoredWorkbenchDensity());
  // Remove inline style overrides
  root.style.removeProperty("--font-display");
  root.style.removeProperty("--font-mono");
  root.style.removeProperty("--console-font-size-ui");
  root.style.removeProperty("--console-font-size-page");
  root.style.removeProperty("--console-font-size-body");
  root.style.removeProperty("font-size");
  root.style.removeProperty("--console-bg");
  root.style.removeProperty("--console-surface");
  root.style.removeProperty("--console-bg-raised");
  root.style.removeProperty("--console-accent-soft");
  root.style.removeProperty("--workbench-bg-image");
  // Reset stored custom
  window.localStorage.removeItem(WORKBENCH_CUSTOM_SETTINGS_KEY);
}

export function setStoredWorkbenchDensity(density: string) {
  if (typeof window === "undefined") return;
  const resolvedDensity = resolveWorkbenchDensity(density);
  window.localStorage.setItem(WORKBENCH_DENSITY_STORAGE_KEY, resolvedDensity);
  applyWorkbenchAppearance(getStoredWorkbenchTheme(), resolvedDensity);
  window.dispatchEvent(new CustomEvent(WORKBENCH_DENSITY_CHANGE_EVENT, { detail: { density: resolvedDensity } }));
}
