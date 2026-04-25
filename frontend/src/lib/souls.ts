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
    color: "#1da1f2",
    glow: "rgba(29, 161, 242, 0.34)",
    intro: "河伯更偏冷静、克制，语气会更稳，表达更收束。"
  },
  siyue: {
    color: "#c6a15b",
    glow: "rgba(198, 161, 91, 0.32)",
    intro: "四岳更偏稳重、沉着，表达会更有结构感和分寸感。"
  },
  zhurong: {
    color: "#ff5a36",
    glow: "rgba(255, 90, 54, 0.32)",
    intro: "祝融更偏直接、果断，语气会更有激情和行动感。"
  },
  xuannv: {
    color: "#f2f5f3",
    glow: "rgba(242, 245, 243, 0.34)",
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
  const section = extractSectionBlock(content, "Identity Anchor");
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

function extractSectionBlock(content: string, heading: string): string {
  const match = content.match(new RegExp(`## ${escapeRegExp(heading)}\\s+([\\s\\S]*?)(?:\\n## |$)`));
  return match?.[1] ?? "";
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
