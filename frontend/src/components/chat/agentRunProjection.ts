import { isInternalControlProtocolText } from "@/lib/internalControlText";

export function looksLikeRawToolOutput(value: unknown) {
  return isInternalControlProtocolText(value) || looksLikeLineNumberedToolOutput(value);
}

function looksLikeLineNumberedToolOutput(value: unknown) {
  const text = String(value ?? "").trim();
  if (!text) {
    return false;
  }
  const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  return lines.length > 0 && lines.every((line) => /^\d+\s*[|│]\s+/.test(line));
}
