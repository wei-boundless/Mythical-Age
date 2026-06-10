import { isInternalActiveWorkControlText } from "@/lib/internalControlText";

export function looksLikeRawToolOutput(value: unknown) {
  const raw = String(value ?? "");
  const text = cleanRunText(raw);
  if (!text) return false;
  return looksLikeLineNumberedFilePreview(raw)
    || looksLikeToolPlaceholder(text)
    || looksLikeRawCommandText(text)
    || looksLikePersistedToolResultFailure(text)
    || looksLikeRawFileListing(text)
    || looksLikeCopiedOutput(text)
    || looksLikeJsonDiagnostics(text)
    || isInternalActiveWorkControlText(text)
    || isInternalProtocolRawOutputText(text);
}

function cleanRunText(value: unknown) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function looksLikeToolPlaceholder(value: string) {
  return /^(?:tool|function|assistant to=|model_action|runtime_event)[:\s_]/i.test(value)
    || /\b(?:tool_call|tool_result|RuntimeInvocationPacket|task_run_id|event_id|answer_source)\b/i.test(value)
    || /\b(?:harness|backend|runtime|query|agent_system|capability_system|health_system|task_system)(?:\.[A-Za-z0-9_-]+){2,}\b/i.test(value);
}

function looksLikeRawCommandText(value: string) {
  return /\b(?:Exit code|Wall time|Output):/i.test(value)
    || /\b(?:Get-Content|Get-ChildItem|Select-Object|Stop-Process|Start-Process|python -m|npm run|npx )\b/i.test(value)
    || /\b(?:not allowlisted read-only|read-only validator|unsupported read-only)\b/i.test(value);
}

function looksLikePersistedToolResultFailure(value: string) {
  return /Read persisted tool result failed|persisted tool result read failed/i.test(value)
    || /(?:runtime_context|runtime[-_ ]context)[\\/]+tool-results/i.test(value)
    || /tool-results[\\/]+session[-_A-Za-z0-9]+/i.test(value);
}

function looksLikeRawFileListing(value: string) {
  return /\bfile\s+[^\s]+\s+\d+\s+bytes\b/i.test(value)
    || /\b\d+\s+bytes\s+(?:file|directory|dir)\b/i.test(value);
}

function looksLikeLineNumberedFilePreview(value: string) {
  const raw = String(value ?? "").replace(/\r\n?/g, "\n");
  if (/(?:^|\n)\s*\d{1,6}\s*\|\s+/.test(raw)) {
    return true;
  }
  return /^\d{1,6}\s*\|\s+/.test(cleanRunText(raw));
}

function looksLikeCopiedOutput(value: string) {
  return /\bCopied:\s+\S+/i.test(value);
}

function looksLikeJsonDiagnostics(value: string) {
  const text = value.trim();
  if (!((text.startsWith("{") && text.endsWith("}")) || (text.startsWith("[") && text.endsWith("]")))) {
    return false;
  }
  return /\b(?:authority|diagnostics|matched_version_count|candidate_version_count|result_envelope|structured_payload)\b/i.test(text);
}

function isInternalProtocolRawOutputText(value: string) {
  if (value.trim().toLowerCase() === "assistant_message") {
    return true;
  }
  return /(?:agent_turn_terminal|runtime_invocation_packet_compiled|task_execution_packet_compiled|step_summary_recorded)/i.test(value);
}
