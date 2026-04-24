export type SoulKey = "hebo" | "siyue" | "zhurong" | "xuannv";

export type SoulSummary = {
  key: SoulKey;
  name: string;
  purpose: string;
  bestAt: string[];
  path: string;
  portraitPath: string;
  color: string;
  glow: string;
  intro: string;
};

export const ACTIVE_SOUL_PATH = "context_profile/agent_core/ACTIVE_SEED.md";

export const SOUL_SEED_PATHS: Record<SoulKey, string> = {
  hebo: "context_profile/agent_core/seeds/hebo.md",
  siyue: "context_profile/agent_core/seeds/siyue.md",
  zhurong: "context_profile/agent_core/seeds/zhurong.md",
  xuannv: "context_profile/agent_core/seeds/xuannv.md"
};

const SOUL_NAME_TO_KEY: Record<string, SoulKey> = {
  河伯: "hebo",
  四岳: "siyue",
  祝融: "zhurong",
  玄女: "xuannv"
};

const SOUL_COLORS: Record<SoulKey, { color: string; glow: string; intro: string }> = {
  hebo: {
    color: "#1da1f2",
    glow: "rgba(29, 161, 242, 0.34)",
    intro: "河伯更偏冷静、清澈、克制，语气会更稳，表达更收束。"
  },
  siyue: {
    color: "#c6a15b",
    glow: "rgba(198, 161, 91, 0.32)",
    intro: "四岳更偏稳重、沉着、讲秩序，表达会更有结构感和分寸感。"
  },
  zhurong: {
    color: "#ff5a36",
    glow: "rgba(255, 90, 54, 0.32)",
    intro: "祝融更偏直接、果断、利落，语气会更有推进感和行动感。"
  },
  xuannv: {
    color: "#f2f5f3",
    glow: "rgba(242, 245, 243, 0.34)",
    intro: "玄女更偏细致、敏锐、安静，表达会更注重辨析和层次。"
  }
};

export function parseSoulSeed(path: string, content: string): SoulSummary {
  const name = extractSectionValue(content, "Seed Name") || inferNameFromPath(path);
  const key = inferSoulKey(path, name);
  return {
    key,
    name,
    purpose: extractSectionValue(content, "Seed Purpose"),
    bestAt: extractBulletSection(content, "Best At"),
    path,
    portraitPath: `/souls/${key}.png`,
    color: SOUL_COLORS[key].color,
    glow: SOUL_COLORS[key].glow,
    intro: SOUL_COLORS[key].intro
  };
}

export function inferSoulKey(path: string, name?: string): SoulKey {
  const lowered = path.toLowerCase();
  if (lowered.includes("hebo")) return "hebo";
  if (lowered.includes("siyue")) return "siyue";
  if (lowered.includes("zhurong")) return "zhurong";
  if (lowered.includes("xuannv")) return "xuannv";
  return SOUL_NAME_TO_KEY[String(name || "").trim()] || "hebo";
}

function inferNameFromPath(path: string): string {
  const key = inferSoulKey(path);
  const pair = Object.entries(SOUL_NAME_TO_KEY).find(([, value]) => value === key);
  return pair?.[0] || "河伯";
}

function extractSectionValue(content: string, heading: string): string {
  const match = content.match(new RegExp(`## ${escapeRegExp(heading)}\\s+([\\s\\S]*?)(?:\\n## |$)`));
  if (!match) {
    return "";
  }
  return match[1]
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .find((line) => !line.startsWith("-")) || "";
}

function extractBulletSection(content: string, heading: string): string[] {
  const match = content.match(new RegExp(`## ${escapeRegExp(heading)}\\s+([\\s\\S]*?)(?:\\n## |$)`));
  if (!match) {
    return [];
  }
  return match[1]
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.startsWith("-"))
    .map((line) => line.replace(/^-+\s*/, "").trim())
    .filter(Boolean);
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
