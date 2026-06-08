"use client";

import { ChevronDown } from "lucide-react";

import { useAppStore } from "@/lib/store";
import { taskEnvironmentDisplayName } from "@/lib/taskEnvironmentDisplay";
import type { TaskEnvironmentCatalog } from "@/lib/api";

type TaskEnvironmentOption = TaskEnvironmentCatalog["environments"][number];

function taskEnvironmentTitle(item: TaskEnvironmentOption) {
  const environmentId = taskEnvironmentId(item);
  return taskEnvironmentDisplayName(environmentId, String(item.record?.title || "").trim());
}

function taskEnvironmentId(item: TaskEnvironmentOption) {
  return String(item.record?.environment_id || "").trim();
}

function isVisibleTaskEnvironment(item: TaskEnvironmentOption) {
  if (item.record?.enabled === false) return false;
  return String(item.management_scope || item.record?.management_scope || "").trim() !== "system_internal";
}

export function WorkspaceModeSwitcher({
  ariaLabel = "任务环境切换",
  className = "",
}: {
  ariaLabel?: string;
  className?: string;
}) {
  const {
    conversationActiveEnvironment,
    setActiveTaskEnvironment,
    taskEnvironmentCatalog,
    taskEnvironmentCatalogError,
    taskEnvironmentCatalogLoading,
  } = useAppStore();
  const environments = (taskEnvironmentCatalog?.environments ?? []).filter(isVisibleTaskEnvironment);
  const activeEnvironmentId = String(conversationActiveEnvironment?.task_environment_id || "").trim();
  const switchableValue = activeEnvironmentId || "env.general.workspace";
  const disabled = taskEnvironmentCatalogLoading || environments.length === 0;
  const hasSwitchableValue = environments.some((item) => taskEnvironmentId(item) === switchableValue);

  return (
    <label
      className={["workbench-mode-select", className].filter(Boolean).join(" ")}
      aria-label={ariaLabel}
      title={taskEnvironmentCatalogError || ariaLabel}
    >
      <select
        disabled={disabled}
        value={switchableValue}
        onChange={(event) => {
          const value = event.target.value.trim();
          if (value.startsWith("env.")) void setActiveTaskEnvironment(value, { source: "workspace-mode" });
        }}
      >
        {!environments.length ? (
          <option value={switchableValue}>{taskEnvironmentCatalogLoading ? "正在读取环境" : "无可用任务环境"}</option>
        ) : null}
        {environments.length && !hasSwitchableValue ? (
          <option value={switchableValue}>
            {taskEnvironmentDisplayName(
              switchableValue,
              conversationActiveEnvironment?.environment_label || switchableValue,
            )}
          </option>
        ) : null}
        {environments.map((item) => (
          <option key={taskEnvironmentId(item)} value={taskEnvironmentId(item)}>
            {taskEnvironmentTitle(item)}
          </option>
        ))}
      </select>
      <ChevronDown aria-hidden="true" size={14} />
    </label>
  );
}
