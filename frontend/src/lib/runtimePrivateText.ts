const RUNTIME_PRIVATE_TEXT_PATTERNS = [
  /(?:^|\/)backend\/mythical-agent\/sessions\//,
  /(?:^|\/)mythical-agent\/sessions\//,
  /(?:^|\/)backend\/storage\/session_environments\//,
  /(?:^|\/)backend\/storage\/runtime_context\//,
  /(?:^|\/)backend\/storage\/runtime_state\//,
  /(?:^|\/)storage\/sessions\//,
  /(?:^|\/)storage\/session_environments\//,
  /(?:^|\/)storage\/runtime_context\//,
  /(?:^|\/)storage\/runtime_state\//,
  /(?:^|\/)runtime_context\/(?:tool[-_]results|tool-results)(?:\/|$)/,
  /(?:^|\/)runtime_state\/(?:tool[-_]results|tool-results)(?:\/|$)/,
  /(?:^|\/)runtime_state\/dynamic_context\/replacements(?:\/|$)/,
  /(?:^|\/)dynamic_context\/replacements\/replacement_[0-9a-f]{12,}\.json\b/,
  /(?:^|[\s/])replacement_[0-9a-f]{12,}\.json\b/,
  /\breplacement:[0-9a-f]{12,}\b/,
] as const;

export function looksLikeRuntimePrivateArtifactText(value: unknown) {
  const text = String(value ?? "").trim();
  if (!text) return false;
  const normalized = text.replace(/\\/g, "/").toLowerCase();
  return RUNTIME_PRIVATE_TEXT_PATTERNS.some((pattern) => pattern.test(normalized));
}
