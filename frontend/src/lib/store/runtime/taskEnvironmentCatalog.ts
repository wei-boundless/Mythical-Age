import { taskEnvironmentDisplayName } from "@/lib/taskEnvironmentDisplay";

import type { StoreState } from "../types";

type TaskEnvironmentCatalogItem = NonNullable<StoreState["taskEnvironmentCatalog"]>["environments"][number];

export function taskEnvironmentIdOf(item: TaskEnvironmentCatalogItem | null | undefined) {
  const record = (item?.record ?? {}) as Record<string, unknown>;
  return String(record.environment_id || "").trim();
}

export function taskEnvironmentLabelOf(item: TaskEnvironmentCatalogItem | null | undefined) {
  const record = (item?.record ?? {}) as Record<string, unknown>;
  const environmentId = String(record.environment_id || "").trim();
  return taskEnvironmentDisplayName(environmentId, String(record.title || "").trim());
}

export function isCatalogEnvironmentVisible(item: TaskEnvironmentCatalogItem) {
  const record = (item.record ?? {}) as Record<string, unknown>;
  if (record.enabled === false) {
    return false;
  }
  return String(item.management_scope || record.management_scope || "").trim() !== "system_internal";
}
