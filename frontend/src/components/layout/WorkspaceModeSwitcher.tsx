"use client";

import { ChevronDown } from "lucide-react";

import { useAppStore } from "@/lib/store";
import type { TaskEnvironmentWorkspaceView, WorkspaceView } from "@/lib/store/types";

type WorkspaceModeItem = {
  view: WorkspaceView;
  optionLabel: string;
};

const WORKSPACE_MODE_ITEMS: WorkspaceModeItem[] = [
  { view: "chat", optionLabel: "常规环境" },
  { view: "code-environment", optionLabel: "开发环境" },
  { view: "creative", optionLabel: "写作环境" },
];

function isTaskEnvironmentModeView(view: WorkspaceView): view is TaskEnvironmentWorkspaceView {
  return view === "chat" || view === "code-environment";
}

export function WorkspaceModeSwitcher({
  ariaLabel = "任务环境切换",
  className = "",
}: {
  ariaLabel?: string;
  className?: string;
}) {
  const { activeWorkspaceView, setTaskEnvironmentWorkspaceView, setWorkspaceView } = useAppStore();
  const switchableView = WORKSPACE_MODE_ITEMS.some((item) => item.view === activeWorkspaceView)
    ? activeWorkspaceView
    : "chat";

  return (
    <label className={["workbench-mode-select", className].filter(Boolean).join(" ")} aria-label={ariaLabel}>
      <select
        value={switchableView}
        onChange={(event) => {
          const view = event.target.value as WorkspaceView;
          if (isTaskEnvironmentModeView(view)) {
            setTaskEnvironmentWorkspaceView(view);
            return;
          }
          setWorkspaceView(view);
        }}
      >
        {WORKSPACE_MODE_ITEMS.map((item) => (
          <option key={item.view} value={item.view}>{item.optionLabel}</option>
        ))}
      </select>
      <ChevronDown aria-hidden="true" size={14} />
    </label>
  );
}
