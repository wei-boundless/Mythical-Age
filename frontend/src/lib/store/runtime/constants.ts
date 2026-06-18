import type { ActiveTurnState, PermissionMode, SessionPoolKey } from "../types";

export const MAX_LIVE_RUNTIME_PROGRESS_ENTRIES = 24;
export const MAIN_CHAT_POOL_KEY: SessionPoolKey = "main-chat";
export const GRAPH_TASK_WORKSPACE_VIEW = "graph_task";
export const GENERAL_TASK_ENVIRONMENT_ID = "env.general.workspace";
export const CODING_TASK_ENVIRONMENT_ID = "env.coding.vibe_workspace";
export const DEFAULT_PERMISSION_MODE: PermissionMode = "full_access";
export const DEFAULT_INSPECTOR_PATH = "durable_memory/index/MEMORY.md";
export const SESSION_RUNTIME_PROJECTION_DELAY_MS = 1600;
export const SESSION_TOKEN_STATS_DELAY_MS = 5000;
export const FRONTEND_EDITOR_CONTEXT_TEXT_LIMIT = 12000;
export const TOKEN_STATS_MONITOR_REFRESH_INTERVAL_MS = 10_000;
export const LAST_ACTIVE_TASK_ENVIRONMENT_KEY = "agentWorkbench.lastActiveTaskEnvironment";
export const LAST_ACTIVE_SESSION_REF_KEY = "agentWorkbench.lastActiveSessionRef";
export const CHAT_STREAM_DISPLAY_ENABLED_KEY = "agentWorkbench.chatStreamDisplayEnabled";
export const GRAPH_ONLY_TASK_ENVIRONMENT_IDS = new Set<string>();
export const CODE_TASK_ENVIRONMENT_IDS = new Set([CODING_TASK_ENVIRONMENT_ID]);
export const ACTIVE_TURN_STATES = new Set<ActiveTurnState | string>([
  "starting",
  "model_turn",
  "running_task",
  "waiting_executor",
  "waiting_user",
  "waiting_approval",
  "waiting_safe_boundary",
  "interrupting",
  "terminal",
]);
