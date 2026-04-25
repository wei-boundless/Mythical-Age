export type SoulKey = "hebo" | "siyue" | "zhurong" | "xuannv";

export type SoulSummary = {
  key: SoulKey;
  name: string;
  path: string;
  portraitPath: string;
  color: string;
  glow: string;
  intro: string;
};

export const ACTIVE_SOUL_PATH = "soul/agent_core/ACTIVE_SEED.md";

export const SOUL_SEED_PATHS: Record<SoulKey, string> = {
  hebo: "soul/agent_core/seeds/hebo.md",
  siyue: "soul/agent_core/seeds/siyue.md",
  zhurong: "soul/agent_core/seeds/zhurong.md",
  xuannv: "soul/agent_core/seeds/xuannv.md"
};

const SOUL_NAME_TO_KEY: Record<string, SoulKey> = {
  河伯: "hebo",
  四岳: "siyue",
  祝融: "zhurong",
  玄女: "xuannv"
};

const SOUL_COLORS: Record<SoulKey, { color: string; glow: string; intro: string }> = {
  hebo: {
    color: "#32b6ff",
    glow: "rgba(50, 182, 255, 0.38)",
    intro: "河伯更偏冷静、克制，语气会更稳，表达更收束。"
  },
  siyue: {
    color: "#c9b46b",
    glow: "rgba(201, 180, 107, 0.34)",
    intro: "四岳更偏稳重、沉着，表达会更有结构感和分寸感。"
  },
  zhurong: {
    color: "#ff4b2f",
    glow: "rgba(255, 75, 47, 0.4)",
    intro: "祝融更偏直接、果断，语气会更有激情和行动感。"
  },
  xuannv: {
    color: "#eef5f1",
    glow: "rgba(238, 245, 241, 0.38)",
    intro: "玄女更偏细致、敏锐，表达会更注重辨析和层次。"
  }
};

export function parseSoulSeed(path: string, content: string): SoulSummary {
  const name = extractIdentityName(content) || inferNameFromPath(path);
  const key = inferSoulKey(path, name);
  return {
    key,
    name,
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

function extractIdentityName(content: string): string {
  const section = extractSectionBlock(content, ["身份锚点", "Identity Anchor"]);
  if (!section) {
    return "";
  }
  const lines = section
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.startsWith("-"));
  for (const line of lines) {
    const match = line.match(/[“"]([^”"]+)[”"]/);
    if (match?.[1]) {
      return match[1].trim();
    }
  }
  return "";
}

function extractSectionBlock(content: string, headings: string | string[]): string {
  const candidates = Array.isArray(headings) ? headings : [headings];
  for (const heading of candidates) {
    const match = content.match(new RegExp(`## ${escapeRegExp(heading)}\\s+([\\s\\S]*?)(?:\\n## |$)`));
    if (match?.[1]) {
      return match[1];
    }
  }
  return "";
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
