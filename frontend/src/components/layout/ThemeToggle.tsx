"use client";

import { Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import {
  WORKBENCH_THEME_STORAGE_KEY,
  WORKBENCH_THEME_TEMPLATES,
  applyWorkbenchAppearance,
  getStoredWorkbenchTheme,
  setStoredWorkbenchTheme,
  type WorkbenchThemeId,
} from "@/framework/workbenchThemes";

export function ThemeToggle() {
  const [mounted, setMounted] = useState(false);
  const [themeId, setThemeId] = useState<WorkbenchThemeId>("clean-light");

  useEffect(() => {
    setThemeId(getStoredWorkbenchTheme());
    setMounted(true);
  }, []);

  function toggle() {
    const currentTheme = getStoredWorkbenchTheme();
    // Cycle through available themes: find next light or dark
    const templates = WORKBENCH_THEME_TEMPLATES;
    const currentMode = templates.find((t) => t.id === currentTheme)?.mode ?? "light";
    // Find a theme of opposite mode
    const opposite = templates.find((t) => t.mode !== currentMode);
    const next = opposite?.id ?? (currentMode === "light" ? "focus-dark" as WorkbenchThemeId : "clean-light" as WorkbenchThemeId);
    setStoredWorkbenchTheme(next);
    setThemeId(next);
  }

  const isDark = WORKBENCH_THEME_TEMPLATES.find((t) => t.id === themeId)?.mode === "dark";

  if (!mounted) {
    return <span className="theme-toggle theme-toggle--hidden" aria-hidden />;
  }

  return (
    <button
      className="theme-toggle"
      onClick={toggle}
      aria-label={isDark ? "切换浅色模式" : "切换深色模式"}
      title={isDark ? "切换浅色模式" : "切换深色模式"}
      type="button"
    >
      {isDark ? <Sun size={14} /> : <Moon size={14} />}
    </button>
  );
}
