"use client";

import { ChevronDown } from "lucide-react";

import { useAppStore } from "@/lib/store";
import type { TaskEnvironmentWorkspaceView } from "@/lib/store/types";

type WorkspaceModeItem = {
  view: TaskEnvironmentWorkspaceView;
  optionLabel: string;
};

const WORKSPACE_MODE_ITEMS: WorkspaceModeItem[] = [
  { view: "chat", optionLabel: "常规环境" },
  { view: "code-environment", optionLabel: "开发环境" },
  { view: "creative", optionLabel: "写作环境" },
];

export function WorkspaceModeSwitcher({
  ariaLabel = "任务环境切换",
  className = "",
}: {
  ariaLabel?: string;
  className?: string;
}) {
  const { activeWorkspaceView, setTaskEnvironmentWorkspaceView } = useAppStore();
  const switchableView = WORKSPACE_MODE_ITEMS.some((item) => item.view === activeWorkspaceView)
    ? activeWorkspaceView as TaskEnvironmentWorkspaceView
    : "chat";

  return (
    <label className={["workbench-mode-select", className].filter(Boolean).join(" ")} aria-label={ariaLabel}>
      <select
        value={switchableView}
        onChange={(event) => setTaskEnvironmentWorkspaceView(event.target.value as TaskEnvironmentWorkspaceView)}
      >
        {WORKSPACE_MODE_ITEMS.map((item) => (
          <option key={item.view} value={item.view}>{item.optionLabel}</option>
        ))}
      </select>
      <ChevronDown aria-hidden="true" size={14} />
    </label>
  );
}
