import type { MainAgentAssemblyMode, TaskSelectionState } from "@/lib/store/types";

type MainAgentAssemblyProfile = {
  mode: MainAgentAssemblyMode;
  label: string;
  summary: string;
  scope: string;
  agent_id: string;
  agent_profile_id: string;
  interaction_mode: string;
  runtime_assembly_hint: Record<string, unknown>;
  mode_policy: Record<string, unknown>;
  stream_policy: Record<string, unknown>;
  intent_decision?: Record<string, unknown>;
};

const INTERACTIVE_STREAM_POLICY = {
  enabled: true,
  mode: "interactive_answer",
  monitor_visibility: "visible",
  emit_content_delta: true,
  fallback_to_non_stream_on_error: true,
};

const MODE_OWNED_RUNTIME_HINT_KEYS = new Set([
  "interaction_mode",
  "runtime_mode",
  "projection_strength",
  "recipe_id",
]);

const MODE_OWNED_POLICY_KEYS = new Set([
  "interaction_mode",
  "recipe_id",
  "projection_strength",
  "mode_reason",
]);

const MODE_OWNED_INTENT_KEYS = new Set([
  "interaction_mode",
]);

export const MAIN_AGENT_ID = "agent:0";
export const MAIN_AGENT_PROFILE_ID = "main_interactive_agent";

export const MAIN_AGENT_ASSEMBLY_MODES: Record<MainAgentAssemblyMode, MainAgentAssemblyProfile> = {
  role: {
    mode: "role",
    label: "角色 / 对话",
    summary: "偏会话承接，保留主会话语气与身份。",
    scope: "主会话",
    agent_id: MAIN_AGENT_ID,
    agent_profile_id: MAIN_AGENT_PROFILE_ID,
    interaction_mode: "role_mode",
    runtime_assembly_hint: {
      interaction_mode: "role_mode",
      runtime_mode: "role",
      projection_strength: "primary",
    },
    stream_policy: INTERACTIVE_STREAM_POLICY,
    mode_policy: {
      interaction_mode: "role_mode",
      recipe_id: "runtime.recipe.role_interaction",
      projection_strength: "primary",
      mode_reason: "frontend_main_agent_profile",
    },
  },
  standard: {
    mode: "standard",
    label: "标准 / 任务",
    summary: "按一般任务工作，兼顾判断与执行。",
    scope: "主会话",
    agent_id: MAIN_AGENT_ID,
    agent_profile_id: MAIN_AGENT_PROFILE_ID,
    interaction_mode: "standard_mode",
    runtime_assembly_hint: {
      interaction_mode: "standard_mode",
      runtime_mode: "standard",
      projection_strength: "companion",
    },
    stream_policy: INTERACTIVE_STREAM_POLICY,
    mode_policy: {
      interaction_mode: "standard_mode",
      recipe_id: "runtime.recipe.standard_task",
      projection_strength: "companion",
      mode_reason: "frontend_main_agent_profile",
    },
  },
  professional: {
    mode: "professional",
    label: "专业 / 长任务",
    summary: "偏长任务、重验证、强调收尾。",
    scope: "主会话",
    agent_id: MAIN_AGENT_ID,
    agent_profile_id: MAIN_AGENT_PROFILE_ID,
    interaction_mode: "professional_mode",
    runtime_assembly_hint: {
      interaction_mode: "professional_mode",
      runtime_mode: "professional",
      projection_strength: "style_only",
    },
    stream_policy: INTERACTIVE_STREAM_POLICY,
    mode_policy: {
      interaction_mode: "professional_mode",
      recipe_id: "runtime.recipe.professional_task",
      projection_strength: "style_only",
      mode_reason: "frontend_main_agent_profile",
    },
    intent_decision: {
      interaction_mode: "professional_mode",
    },
  },
};

export function buildMainAgentTaskSelection(
  taskSelection: TaskSelectionState | Record<string, unknown> | null,
  mode: MainAgentAssemblyMode,
): Record<string, unknown> | undefined {
  const current = taskSelection ? ({ ...taskSelection } as Record<string, unknown>) : {};
  if (isTaskGraphLaunchSelection(current)) {
    return undefined;
  }
  if (hasTaskOwnedAgentAssembly(current)) {
    return hasAnyKey(current) ? current : undefined;
  }
  const profile = MAIN_AGENT_ASSEMBLY_MODES[mode] ?? MAIN_AGENT_ASSEMBLY_MODES.role;
  return {
    ...current,
    agent_id: profile.agent_id,
    agent_profile_id: profile.agent_profile_id,
    interaction_mode: profile.interaction_mode,
    runtime_interaction_mode: profile.interaction_mode,
    runtime_mode: profile.mode,
    runtime_assembly_hint: {
      ...omitModeOwnedKeys(current.runtime_assembly_hint, MODE_OWNED_RUNTIME_HINT_KEYS),
      ...profile.runtime_assembly_hint,
    },
    stream_policy: profile.stream_policy,
    mode_policy: {
      ...omitModeOwnedKeys(current.mode_policy, MODE_OWNED_POLICY_KEYS),
      ...profile.mode_policy,
    },
    intent_decision: {
      ...omitModeOwnedKeys(current.intent_decision, MODE_OWNED_INTENT_KEYS),
      ...(profile.intent_decision ?? { interaction_mode: profile.interaction_mode }),
    },
  };
}

function isTaskGraphLaunchSelection(selection: Record<string, unknown>): boolean {
  return (
    String(selection.mode || "").trim() === "coordination"
    || Boolean(String(selection.coordination_task_id || "").trim())
    || Boolean(String(selection.task_graph_id || "").trim())
    || Boolean(String(selection.selected_graph_id || "").trim())
  );
}

function hasTaskOwnedAgentAssembly(selection: Record<string, unknown>): boolean {
  if (isRecord(selection.agent_invocation) || Boolean(String(selection.agent_invocation_id || "").trim())) {
    return true;
  }
  const agentId = String(selection.agent_id || "").trim();
  const agentProfileId = String(selection.agent_profile_id || "").trim();
  return Boolean(
    agentId && agentId !== MAIN_AGENT_ID
    || agentProfileId && agentProfileId !== MAIN_AGENT_PROFILE_ID
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function omitModeOwnedKeys(value: unknown, ownedKeys: Set<string>) {
  if (!isRecord(value)) {
    return {};
  }
  return Object.fromEntries(Object.entries(value).filter(([key]) => !ownedKeys.has(key)));
}

function hasAnyKey(value: Record<string, unknown>): boolean {
  return Object.keys(value).length > 0;
}
