export type AssistantContentMetadata = {
  answerCanonicalState?: unknown;
  answerChannel?: unknown;
  answerPersistPolicy?: unknown;
  answerSource?: unknown;
  answerLeakFlags?: unknown;
};

type VisibilityOptions = {
  defaultVisible?: boolean;
};

const CANONICAL_TEXT_STATES = new Set(["stable_answer", "stable_feedback", "tool_summary", "needs_user", "blocked"]);
const IMAGE_TEXT_STATES = new Set(["complete", "stable_answer"]);
const NON_PUBLIC_STATES = new Set(["missing_answer", "progress_only", "unstable_answer"]);
const NON_PUBLIC_POLICIES = new Set(["do_not_persist", "persist_debug_only"]);
const CONTROL_CHANNELS = new Set([
  "active_work_control",
  "missing_answer",
  "opening_judgment",
  "orchestration_fail_closed",
  "runtime_control",
  "task_control",
]);
const SYSTEM_CONTROL_SOURCES = new Set([
  "harness.single_agent_turn.protocol_error",
  "harness.single_agent_turn.tool_loop",
]);

export function shouldDisplayAssistantContent(
  metadata: AssistantContentMetadata,
  options: VisibilityOptions = {},
) {
  const defaultVisible = options.defaultVisible ?? true;
  if (isSystemControlAssistantContent(metadata)) {
    return false;
  }
  if (isCanonicalAssistantContent(metadata) || isImageAssistantContent(metadata)) {
    return true;
  }
  if (isNonPublicAssistantContent(metadata)) {
    return false;
  }
  return defaultVisible;
}

export function shouldDisplayAssistantStreamContent(metadata: AssistantContentMetadata) {
  if (isSystemControlAssistantContent(metadata)) {
    return false;
  }
  if (isNonPublicAssistantContent(metadata)) {
    return false;
  }
  if (isCanonicalAssistantContent(metadata) || isImageAssistantContent(metadata)) {
    return true;
  }
  return true;
}

export function isCanonicalAssistantContent(metadata: AssistantContentMetadata) {
  const policy = normalized(metadata.answerPersistPolicy);
  const state = normalized(metadata.answerCanonicalState);
  return policy === "persist_canonical" && CANONICAL_TEXT_STATES.has(state);
}

export function isImageAssistantContent(metadata: AssistantContentMetadata) {
  const channel = normalized(metadata.answerChannel);
  const policy = normalized(metadata.answerPersistPolicy);
  const state = normalized(metadata.answerCanonicalState);
  return channel === "image" && policy === "store" && IMAGE_TEXT_STATES.has(state);
}

export function isNonPublicAssistantContent(metadata: AssistantContentMetadata) {
  const channel = normalized(metadata.answerChannel);
  const policy = normalized(metadata.answerPersistPolicy);
  const state = normalized(metadata.answerCanonicalState);
  const source = normalized(metadata.answerSource);
  if (SYSTEM_CONTROL_SOURCES.has(source)) {
    return true;
  }
  if (NON_PUBLIC_POLICIES.has(policy) || NON_PUBLIC_STATES.has(state)) {
    return true;
  }
  if (CONTROL_CHANNELS.has(channel)) {
    return true;
  }
  if (policy && policy !== "persist_canonical") {
    return true;
  }
  if (state && !CANONICAL_TEXT_STATES.has(state)) {
    return true;
  }
  const leakFlags = normalizedList(metadata.answerLeakFlags);
  return leakFlags.some((flag) => flag.includes("protocol")) && !CANONICAL_TEXT_STATES.has(state);
}

function isSystemControlAssistantContent(metadata: AssistantContentMetadata) {
  const source = normalized(metadata.answerSource);
  return SYSTEM_CONTROL_SOURCES.has(source);
}

export function normalizedAnswerLeakFlags(value: unknown) {
  return normalizedList(value);
}

function normalized(value: unknown) {
  return String(value ?? "").trim().toLowerCase();
}

function normalizedList(value: unknown) {
  if (Array.isArray(value)) {
    return value.map((item) => normalized(item)).filter(Boolean);
  }
  const text = normalized(value);
  return text ? [text] : [];
}
