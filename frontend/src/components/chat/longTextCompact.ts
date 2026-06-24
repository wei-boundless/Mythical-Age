export type LongTextCompactionMode = "compact" | "expanded";
export type LongTextDraftIntent = "type" | "paste" | "collapse" | "expand" | "restore";

export type LongTextCompactionProfile = {
  threshold: number;
  previewLimit: number;
  minPreviewLimit: number;
  emptyPreview: string;
};

export type LongTextCompactionModel = {
  visibleLength: number;
  shouldCompact: boolean;
  preview: string;
  metricLabel: string;
  title: string;
};

export const LONG_TEXT_COMPACTION_PROFILES = {
  composer: {
    threshold: 256,
    previewLimit: 168,
    minPreviewLimit: 72,
    emptyPreview: "长文本输入",
  },
  userMessage: {
    threshold: 256,
    previewLimit: 108,
    minPreviewLimit: 56,
    emptyPreview: "长文本消息",
  },
} satisfies Record<string, LongTextCompactionProfile>;

export function createLongTextCompactionModel(
  content: string,
  profile: LongTextCompactionProfile = LONG_TEXT_COMPACTION_PROFILES.composer,
): LongTextCompactionModel {
  const normalized = normalizePreviewText(content);
  const visibleLength = visibleCodePointLength(content);
  const shouldCompact = visibleLength > profile.threshold;
  const preview = shouldCompact
    ? compactPreviewPrefix(normalized, profile)
    : normalized;
  const metricLabel = formatLongTextMetric(visibleLength);
  return {
    visibleLength,
    shouldCompact,
    preview,
    metricLabel,
    title: shouldCompact ? `超过 ${profile.threshold} 字，${metricLabel}` : metricLabel,
  };
}

export function resolveLongTextCompactionMode({
  content,
  currentMode,
  intent,
  profile = LONG_TEXT_COMPACTION_PROFILES.composer,
}: {
  content: string;
  currentMode: LongTextCompactionMode;
  intent: LongTextDraftIntent;
  profile?: LongTextCompactionProfile;
}): LongTextCompactionMode {
  const shouldCompact = createLongTextCompactionModel(content, profile).shouldCompact;
  if (!shouldCompact) {
    return "expanded";
  }
  if (intent === "paste" || intent === "collapse") {
    return "compact";
  }
  if (intent === "expand" || intent === "restore") {
    return "expanded";
  }
  return currentMode === "compact" ? "compact" : "expanded";
}

function visibleCodePointLength(content: string) {
  return Array.from(content.trim()).length;
}

function formatLongTextMetric(visibleLength: number) {
  return `${visibleLength} 字`;
}

function compactPreviewPrefix(normalizedContent: string, profile: LongTextCompactionProfile) {
  const characters = Array.from(normalizedContent);
  if (!characters.length) {
    return profile.emptyPreview;
  }
  if (characters.length <= profile.previewLimit) {
    return normalizedContent;
  }
  const cutIndex = readableCutIndex(characters, profile.previewLimit, profile.minPreviewLimit);
  const prefix = characters.slice(0, cutIndex).join("").replace(/[\s,.;:!?，。；：！？、]+$/u, "").trim();
  return `${prefix || profile.emptyPreview}...`;
}

function readableCutIndex(characters: string[], previewLimit: number, minPreviewLimit: number) {
  const hardLimit = Math.max(minPreviewLimit, Math.min(previewLimit, characters.length));
  const softFloor = Math.min(Math.max(minPreviewLimit, Math.floor(hardLimit * 0.72)), hardLimit);
  for (let index = hardLimit - 1; index >= softFloor; index -= 1) {
    if (/[\s,.;:!?，。；：！？、]/u.test(characters[index] ?? "")) {
      return index + 1;
    }
  }
  return hardLimit;
}

function normalizePreviewText(content: string) {
  let result = "";
  let previousWasWhitespace = false;
  for (const character of content.trim()) {
    if (/\s/u.test(character)) {
      if (result && !previousWasWhitespace) {
        result += " ";
      }
      previousWasWhitespace = true;
      continue;
    }
    result += character;
    previousWasWhitespace = false;
  }
  return result.trim();
}
