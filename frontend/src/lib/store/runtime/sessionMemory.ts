import type { WorkbenchSessionRef } from "@/lib/api";

import type { SessionPoolKey, SessionRef } from "../types";
import { CHAT_STREAM_DISPLAY_ENABLED_KEY, LAST_ACTIVE_SESSION_REF_KEY, MAIN_CHAT_POOL_KEY, THINKING_PROJECTION_ENABLED_KEY } from "./constants";
import { sessionPoolKeyForScope } from "./sessionModels";
import { errorDetailMessage } from "./text";

export function storageGet(key: string) {
  try {
    if (typeof window === "undefined") {
      return "";
    }
    return String(window.localStorage?.getItem(key) || "").trim();
  } catch {
    return "";
  }
}

export function storageSet(key: string, value: string) {
  try {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage?.setItem(key, value);
  } catch {
    // Local storage is only an interface memory hint; runtime behavior must not depend on it.
  }
}

export function storageRemove(key: string) {
  try {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage?.removeItem(key);
  } catch {
    // Local storage is only an interface memory hint; runtime behavior must not depend on it.
  }
}

export function readRememberedChatStreamDisplayEnabled() {
  const raw = storageGet(CHAT_STREAM_DISPLAY_ENABLED_KEY).toLowerCase();
  if (["1", "true", "enabled", "on"].includes(raw)) return true;
  if (["0", "false", "disabled", "off"].includes(raw)) return false;
  return null;
}

export function rememberChatStreamDisplayEnabled(enabled: boolean) {
  storageSet(CHAT_STREAM_DISPLAY_ENABLED_KEY, enabled ? "1" : "0");
}

export function readRememberedThinkingProjectionEnabled() {
  const raw = storageGet(THINKING_PROJECTION_ENABLED_KEY).toLowerCase();
  if (["1", "true", "enabled", "on"].includes(raw)) return true;
  if (["0", "false", "disabled", "off"].includes(raw)) return false;
  return null;
}

export function rememberThinkingProjectionEnabled(enabled: boolean) {
  storageSet(THINKING_PROJECTION_ENABLED_KEY, enabled ? "1" : "0");
}

export function sessionRefFromStoredValue(raw: unknown): SessionRef | null {
  if (typeof raw === "string") {
    const sessionId = raw.trim();
    return sessionId ? { sessionId, poolKey: MAIN_CHAT_POOL_KEY } : null;
  }
  if (!raw || typeof raw !== "object") {
    return null;
  }
  const parsed = raw as Partial<SessionRef> & WorkbenchSessionRef;
  const sessionId = String(parsed.sessionId || parsed.session_id || "").trim();
  if (!sessionId) {
    return null;
  }
  const scope = parsed.scope && typeof parsed.scope === "object" ? parsed.scope : undefined;
  const poolKey = parsed.poolKey ?? (parsed.pool_key as SessionPoolKey | undefined) ?? sessionPoolKeyForScope(scope);
  const updatedAt = Number(parsed.updatedAt ?? parsed.updated_at ?? 0);
  return {
    sessionId,
    ...(scope ? { scope } : {}),
    poolKey,
    ...(Number.isFinite(updatedAt) && updatedAt > 0 ? { updatedAt } : {}),
  };
}

export function readRememberedSessionRef(): SessionRef | null {
  const raw = storageGet(LAST_ACTIVE_SESSION_REF_KEY);
  if (!raw) {
    return null;
  }
  try {
    return sessionRefFromStoredValue(JSON.parse(raw));
  } catch {
    return sessionRefFromStoredValue(raw);
  }
}

export function rememberSessionRef(ref: SessionRef) {
  const sessionId = String(ref.sessionId || "").trim();
  if (!sessionId) {
    return;
  }
  const scope = ref.scope && Object.keys(ref.scope).length ? ref.scope : undefined;
  storageSet(LAST_ACTIVE_SESSION_REF_KEY, JSON.stringify({
    sessionId,
    ...(scope ? { scope } : {}),
    poolKey: ref.poolKey ?? sessionPoolKeyForScope(scope),
    updatedAt: Number.isFinite(ref.updatedAt) && Number(ref.updatedAt) > 0 ? Number(ref.updatedAt) : Date.now() / 1000,
  }));
}

export function clearRememberedSessionRef(sessionId?: string) {
  const expected = String(sessionId || "").trim();
  if (!expected) {
    storageRemove(LAST_ACTIVE_SESSION_REF_KEY);
    return;
  }
  const remembered = readRememberedSessionRef();
  if (remembered?.sessionId === expected) {
    storageRemove(LAST_ACTIVE_SESSION_REF_KEY);
  }
}

export function shouldClearRememberedSessionAfterError(error: unknown) {
  const message = errorDetailMessage(error).toLowerCase();
  return message.includes("unknown session_id")
    || message.includes("invalid session_id")
    || message.includes("session scope mismatch");
}

export function isProjectDirectorySelectionCancelled(error: unknown) {
  return /^project directory selection cancelled$/i.test(errorDetailMessage(error));
}
