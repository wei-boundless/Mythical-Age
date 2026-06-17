import { request } from "./shared";
import type {
  ContextBudgetConfig,
  ImageAssetConfig,
  ModelProviderConfig,
  RuntimeConfigConsole,
} from "./types";

export async function getPermissionMode() {
  return request<{ mode: string; supported_modes: string[] }>("/config/permission-mode");
}

export async function setPermissionMode(mode: string) {
  return request<{ mode: string; supported_modes: string[] }>("/config/permission-mode", {
    method: "PUT",
    body: JSON.stringify({ mode })
  });
}

export async function getContextBudgetConfig() {
  return request<ContextBudgetConfig>("/config/context-budget");
}

export async function setContextBudgetPreset(presetId: string) {
  return request<ContextBudgetConfig>("/config/context-budget", {
    method: "PUT",
    body: JSON.stringify({ preset_id: presetId })
  });
}

export async function getModelProviderConfig() {
  return request<ModelProviderConfig>("/config/model-provider");
}

export async function getImageAssetConfig() {
  return request<ImageAssetConfig>("/image-assets/config");
}

export async function setModelProviderConfig(payload: {
  provider: string;
  model: string;
  base_url: string;
  api_key?: string;
}) {
  return request<ModelProviderConfig>("/config/model-provider", {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function getRuntimeConfigConsole() {
  return request<RuntimeConfigConsole>("/config/runtime-console");
}

export async function setRuntimeConfigGroup(groupId: string, values: Record<string, string | number | boolean>) {
  return request<RuntimeConfigConsole>("/config/runtime-console", {
    method: "PUT",
    body: JSON.stringify({ group_id: groupId, values })
  });
}
