export type WorkbenchThemeId = "clean-light" | "focus-dark";
export type WorkbenchDensity = "standard" | "compact";

export type WorkbenchThemeTemplate = {
  id: WorkbenchThemeId;
  label: string;
  description: string;
  mode: "light" | "dark";
  status: "built_in";
  accent: string;
  preview: {
    background: string;
    surface: string;
    text: string;
    accent: string;
  };
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
    preview: {
      background: "#f3f6f9",
      surface: "#ffffff",
      text: "#111827",
      accent: "#1d5fd3",
    },
  },
  {
    id: "focus-dark",
    label: "专注暗色",
    description: "低亮度工作模板，适合长时间运行监控和夜间使用。",
    mode: "dark",
    status: "built_in",
    accent: "#7fb2ff",
    preview: {
      background: "#0f1720",
      surface: "#17212d",
      text: "#edf4ff",
      accent: "#7fb2ff",
    },
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
}

export function setStoredWorkbenchTheme(themeId: string) {
  if (typeof window === "undefined") return;
  const resolvedTheme = resolveWorkbenchThemeId(themeId);
  window.localStorage.setItem(WORKBENCH_THEME_STORAGE_KEY, resolvedTheme);
  applyWorkbenchAppearance(resolvedTheme, getStoredWorkbenchDensity());
  window.dispatchEvent(new CustomEvent(WORKBENCH_THEME_CHANGE_EVENT, { detail: { themeId: resolvedTheme } }));
}

export function setStoredWorkbenchDensity(density: string) {
  if (typeof window === "undefined") return;
  const resolvedDensity = resolveWorkbenchDensity(density);
  window.localStorage.setItem(WORKBENCH_DENSITY_STORAGE_KEY, resolvedDensity);
  applyWorkbenchAppearance(getStoredWorkbenchTheme(), resolvedDensity);
  window.dispatchEvent(new CustomEvent(WORKBENCH_DENSITY_CHANGE_EVENT, { detail: { density: resolvedDensity } }));
}
