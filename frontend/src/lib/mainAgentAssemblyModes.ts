import type { MainAgentAssemblyMode, TaskSelectionState } from "@/lib/store/types";

type MainAgentAssemblyProfile = {
  mode: MainAgentAssemblyMode;
  label: string;
  summary: string;
  scope: string;
  agent_id: string;
  agent_profile_id: string;
  interaction_mode: string;
  runtime_lane: string;
  runtime_assembly_hint: Record<string, unknown>;
  mode_policy: Record<string, unknown>;
  intent_decision?: Record<string, unknown>;
};

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
    runtime_lane: "role_interaction",
    runtime_assembly_hint: {
      interaction_mode: "role_mode",
      runtime_mode: "role_interaction",
      projection_strength: "primary",
    },
    mode_policy: {
      interaction_mode: "role_mode",
      runtime_lane: "role_interaction",
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
    runtime_lane: "standard_task",
    runtime_assembly_hint: {
      interaction_mode: "standard_mode",
      runtime_mode: "standard_task",
      projection_strength: "companion",
    },
    mode_policy: {
      interaction_mode: "standard_mode",
      runtime_lane: "standard_task",
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
    runtime_lane: "professional_task",
    runtime_assembly_hint: {
      interaction_mode: "professional_mode",
      runtime_mode: "professional_task",
      execution_strategy: "professional_task_run",
      projection_strength: "style_only",
    },
    mode_policy: {
      interaction_mode: "professional_mode",
      runtime_lane: "professional_task",
      recipe_id: "runtime.recipe.professional_task",
      projection_strength: "style_only",
      mode_reason: "frontend_main_agent_profile",
    },
    intent_decision: {
      interaction_mode: "professional_mode",
      execution_strategy: "professional_task_run",
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
  if (hasExplicitAgentInvocation(current)) {
    return hasAnyKey(current) ? current : undefined;
  }
  const profile = MAIN_AGENT_ASSEMBLY_MODES[mode] ?? MAIN_AGENT_ASSEMBLY_MODES.role;
  return {
    ...current,
    agent_id: profile.agent_id,
    agent_profile_id: profile.agent_profile_id,
    interaction_mode: profile.interaction_mode,
    runtime_interaction_mode: profile.interaction_mode,
    runtime_lane: profile.runtime_lane,
    runtime_assembly_hint: {
      ...(isRecord(current.runtime_assembly_hint) ? current.runtime_assembly_hint : {}),
      ...profile.runtime_assembly_hint,
    },
    mode_policy: {
      ...(isRecord(current.mode_policy) ? current.mode_policy : {}),
      ...profile.mode_policy,
    },
    intent_decision: {
      ...(isRecord(current.intent_decision) ? current.intent_decision : {}),
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

function hasExplicitAgentInvocation(selection: Record<string, unknown>): boolean {
  return isRecord(selection.agent_invocation) || Boolean(String(selection.agent_invocation_id || "").trim());
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function hasAnyKey(value: Record<string, unknown>): boolean {
  return Object.keys(value).length > 0;
}
