import type { PublicChatTimelineItem } from "@/lib/api";
import { isPublicTimelineBodyItem as isStorePublicTimelineBodyItem } from "@/lib/store/publicTimeline";

export function isPublicTimelineBodyItem(item: PublicChatTimelineItem | null | undefined) {
  return isStorePublicTimelineBodyItem(item ?? undefined);
}

export function isSemanticPublicTimelineItem(item: PublicChatTimelineItem | null | undefined) {
  if (!item) return false;
  if (isPublicTimelineBodyItem(item)) return true;
  return Boolean(
    cleanRunText(item.surface)
    || cleanRunText(item.source_authority)
    || item.collapse_after_body_feedback
    || item.covers_tool_refs,
  );
}

export function hasDisplayablePublicTimelineBody(items: PublicChatTimelineItem[] | null | undefined) {
  return (items ?? []).some((item) => {
    if (!isPublicTimelineBodyItem(item)) return false;
    const text = cleanRunText(publicTimelineBodyText(item));
    return Boolean(text && !looksLikeRawToolOutput(text));
  });
}

export function publicTimelineBodyText(item: PublicChatTimelineItem | null | undefined) {
  if (!item) return "";
  for (const candidate of [
    item.text,
    item.detail,
    item.observation,
    item.public_summary,
    item.implication,
  ]) {
    const text = cleanRunBodyText(candidate);
    if (text) return text;
  }
  return "";
}

export function looksLikeRawToolOutput(value: unknown) {
  const text = cleanRunText(value);
  if (!text) return false;
  return looksLikeToolPlaceholder(text)
    || looksLikeRawCommandText(text)
    || looksLikePersistedToolResultFailure(text)
    || looksLikeRawFileListing(text)
    || looksLikeCopiedOutput(text)
    || looksLikeJsonDiagnostics(text)
    || isInternalProtocolRawOutputText(text);
}

function cleanRunText(value: unknown) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function cleanRunBodyText(value: unknown) {
  const text = String(value ?? "")
    .replace(/\r\n?/g, "\n")
    .split("\n")
    .map((line) => line.replace(/[ \t]+$/g, ""))
    .join("\n")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  return restoreReadableBodyParagraphs(text);
}

function restoreReadableBodyParagraphs(text: string) {
  if (!text || text.includes("\n\n") || text.length < 480) {
    return text;
  }
  const sentences = text.split(/(?<=[。！？!?；;」”）】])\s+/u).map((item) => item.trim()).filter(Boolean);
  if (sentences.length < 4) {
    return text;
  }
  const paragraphs: string[] = [];
  let current = "";
  for (const sentence of sentences) {
    const next = current ? `${current} ${sentence}` : sentence;
    if (current && (current.length >= 220 || next.length > 360 || /^["“「]/.test(sentence))) {
      paragraphs.push(current);
      current = sentence;
    } else {
      current = next;
    }
  }
  if (current) {
    paragraphs.push(current);
  }
  return paragraphs.length > 1 ? paragraphs.join("\n\n") : text;
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
