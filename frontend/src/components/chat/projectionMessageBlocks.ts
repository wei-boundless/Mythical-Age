import { publicTimelineHasDisplayableActivity } from "@/components/chat/PublicTimelineActivity";
import { isInternalControlProtocolText } from "@/lib/internalControlText";
import type { ProjectionRenderBlock } from "@/lib/projection/chronological";

export type ProjectionMessageBlock =
  | { kind: "body"; key: string; offset: number; text: string }
  | { kind: "activity"; key: string; offset: number; blocks: ProjectionRenderBlock[] };

export function orderedProjectionMessageBlocksFromView(
  blocks: ProjectionRenderBlock[],
  {
    fallbackBodyText,
    hasBody,
  }: {
    fallbackBodyText: string;
    hasBody: boolean;
  },
): ProjectionMessageBlock[] {
  const entries: ProjectionMessageBlock[] = [];
  const keyCounts = new Map<string, number>();
  const nextEntryKey = (rawKey: string) => {
    const baseKey = cleanText(rawKey) || `projection-entry:${entries.length}`;
    const count = keyCounts.get(baseKey) ?? 0;
    keyCounts.set(baseKey, count + 1);
    return count ? `${baseKey}:duplicate-${count}` : baseKey;
  };
  for (const block of blocks) {
    if (block.kind === "body_segment") {
      if (!block.text || isInternalControlProtocolText(block.text)) continue;
      entries.push({
        kind: "body",
        key: nextEntryKey(`body:${block.id || block.firstOffset}`),
        offset: Number.isFinite(Number(block.firstOffset)) ? Number(block.firstOffset) : Number.MAX_SAFE_INTEGER,
        text: block.text,
      });
      continue;
    }
    if (!publicTimelineHasDisplayableActivity([block])) continue;
    entries.push({
      kind: "activity",
      key: nextEntryKey(`activity:${activityBlockId(block) || blockOffset(block)}`),
      offset: blockOffset(block),
      blocks: [block],
    });
  }
  if (!entries.some((entry) => entry.kind === "body") && hasBody && fallbackBodyText.trim()) {
    entries.push({
      kind: "body",
      key: nextEntryKey("body:projection-body"),
      offset: Number.MAX_SAFE_INTEGER,
      text: fallbackBodyText,
    });
  }
  const sorted = entries.sort((left, right) => {
    if (left.offset !== right.offset) return left.offset - right.offset;
    return left.key.localeCompare(right.key);
  });
  const grouped: ProjectionMessageBlock[] = [];
  for (const entry of sorted) {
    const previous = grouped[grouped.length - 1];
    if (entry.kind === "activity" && previous?.kind === "activity") {
      previous.blocks.push(...entry.blocks);
      continue;
    }
    grouped.push(entry);
  }
  return grouped;
}

function activityBlockId(block: ProjectionRenderBlock) {
  return block.id;
}

function blockOffset(block: ProjectionRenderBlock) {
  if (block.kind === "body_segment") return block.firstOffset;
  if (block.kind === "tool_event") return block.firstOffset;
  if (block.kind === "todo_plan") return block.offset;
  if (block.kind === "log_entry") return Number.MAX_SAFE_INTEGER;
  return Number.MAX_SAFE_INTEGER;
}

function cleanText(value: unknown) {
  return String(value ?? "").trim();
}
