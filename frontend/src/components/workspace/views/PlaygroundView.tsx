"use client";

import { useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent } from "react";
import Image from "next/image";
import {
  ArrowLeft,
  ArrowRight,
  BookOpenText,
  History,
  Layers3,
  PanelTop,
  Send,
  Stars,
  Orbit,
  Feather,
  WandSparkles,
  Save,
  Plus,
  Trash2,
  Check,
} from "lucide-react";

import {
  createSoulProjectionCard,
  deleteSoulProjectionCard,
  getSoulProjectionCards,
  getSoulSystemCatalog,
  getSoulWorkLog,
  saveSoulCommonContract,
  selectSoulProjectionCard,
  type SoulProjectionCard,
  type SoulProjectionCatalog,
  type SoulResourceCard,
  type SoulResourceCatalog,
  type SoulResourceStory,
  type SoulResourceWorld,
  type SoulSystemCatalog,
  type SoulSystemSeed,
  type SoulWorkLogView,
} from "@/lib/api";
import type { SoulKey } from "@/lib/souls";
import { useAppStore } from "@/lib/store";

import styles from "./PlaygroundView.module.css";

type PortalStage = "home" | "transition" | "world";
type SoulMode = "role" | "standard" | "work" | "plain";
type PromptRecord = {
  prompt_id?: string;
  title?: string;
  content?: string;
  task_mode?: string;
  role_type?: string;
  version?: string;
  cache_scope?: string;
};

const WORLD_ORDER = ["world.default", "world.honghuang"] as const;

const WORLD_COPY: Record<string, { tagline: string; portal: string; intro: string }> = {
  "world.default": {
    tagline: "现实世界",
    portal: "真实任务、共同契约、执行投影",
    intro: "这里存放共同契约、工作指令和无角色执行投影，不启用洪荒叙事。",
  },
  "world.honghuang": {
    tagline: "洪荒时代",
    portal: "穿越、召唤、遇见灵魂",
    intro: "只在这个世界里启用洪荒气质，强调召唤、气象和灵魂本体。",
  },
};

const WORK_PROMPT_FALLBACK: PromptRecord = {
  prompt_id: "work_prompt.default",
  title: "现实工作指令",
  content:
    "你是一名执行当前任务的工作 Agent。你只关注用户目标、任务契约、可用资源和验收要求。你不进行灵魂扮演，不引用背景世界，不用故事设定解释工作行为。",
};

const COMMON_CONTRACT_FALLBACK: PromptRecord = {
  prompt_id: "common_contract.default",
  title: "用户共同契约",
  content:
    "## 工作偏好\n\n- 优先按用户当前真实目标推进，不把内部流程名称当作用户目标。\n- 需要行动时先确认关键边界，再给出可执行结果。\n- 表达要清楚、直接、有人味；不要为了显得完整而堆叠无关内容。\n\n## 项目约定\n\n- Agent prompt 应写成角色职责、工作边界、可执行任务和裁决标准。\n- 当项目要求真实验证时，交付前需要说明验证方式和结果。",
};

const FALLBACK_REALITY_PROJECTIONS: SoulProjectionCard[] = [
  {
    projection_id: "projection.worker.web_evidence_researcher",
    title: "网页证据研究员",
    soul_id: "hebo",
    soul_name: "河伯",
    projection_kind: "worker_agent_projection",
    owner_system: "orchestration_system",
    source_task_graph_refs: [],
    projection_nodes: [],
    identity_anchor: "围绕委派问题检索公开网页、识别可靠来源，并整理成可判断的证据报告。",
    role_type: "web_evidence_researcher",
    task_mode: "general_qa",
    agent_profile_id: "web_evidence_agent",
    posture_tags: ["worker_sub_agent", "web", "evidence_first"],
    expression_density: "normal",
    attention_focus: ["freshness", "source_quality", "conflicts", "unknowns"],
    risk_notes: [],
    projection_prompt: "优先寻找官方来源、原始公告、官方文档、权威媒体、一手数据或明确署名的可靠来源。对今天、现在、最新、近期、当前、实时等问题，必须核验时间点、发布时间和来源时效。",
    usage_summary: "用于公开网页研究，整理可靠来源、时间核验、冲突信息和可回答事实。",
    skill_views: [],
    tool_views: [],
    memory_policy_summary: "只读取当前委派问题和必要上下文，不写长期记忆。",
    output_contract_summary: "返回网页证据报告，不替主 Agent 做最终表达。",
    runtime_only_payload: true,
    static_projection_card: true,
    created_at: 0,
    updated_at: 0,
    is_system_default: true,
  },
  {
    projection_id: "projection.worker.table_evidence_analyst",
    title: "表格证据分析员",
    soul_id: "hebo",
    soul_name: "河伯",
    projection_kind: "worker_agent_projection",
    owner_system: "orchestration_system",
    source_task_graph_refs: [],
    projection_nodes: [],
    identity_anchor: "读取数据结构，按委派问题完成受限计算，并整理计算口径、结果和边界。",
    role_type: "table_evidence_analyst",
    task_mode: "structured_data_analysis",
    agent_profile_id: "structured_data_analysis_agent",
    posture_tags: ["worker_sub_agent", "table", "evidence_first"],
    expression_density: "normal",
    attention_focus: ["schema", "filters", "group_by", "metrics", "unknowns"],
    risk_notes: [],
    projection_prompt: "先确认对象、维度、指标和输出形式。执行分析后说明使用的表、字段、筛选条件、分组维度、排序指标、计算口径和结果范围。",
    usage_summary: "用于表格分析委派，整理数据结构、计算口径、结果、异常与未知。",
    skill_views: [],
    tool_views: [],
    memory_policy_summary: "只读取当前委派绑定的数据文件和必要上下文，不写长期记忆。",
    output_contract_summary: "返回表格证据分析报告，必须说明维度、指标和计算口径。",
    runtime_only_payload: true,
    static_projection_card: true,
    created_at: 0,
    updated_at: 0,
    is_system_default: true,
  },
  {
    projection_id: "projection.worker.pdf_evidence_reader",
    title: "PDF 阅读证据整理员",
    soul_id: "hebo",
    soul_name: "河伯",
    projection_kind: "worker_agent_projection",
    owner_system: "orchestration_system",
    source_task_graph_refs: [],
    projection_nodes: [],
    identity_anchor: "阅读指定 PDF，定位页面、章节、结论或主题，并整理成阅读证据报告。",
    role_type: "pdf_evidence_reader",
    task_mode: "pdf_analysis",
    agent_profile_id: "pdf_analysis_agent",
    posture_tags: ["worker_sub_agent", "pdf", "evidence_first"],
    expression_density: "normal",
    attention_focus: ["page_role", "section_boundary", "answerable_facts", "unknowns"],
    risk_notes: [],
    projection_prompt: "根据问题判断需要全文主题、指定页、指定章节、结论部分、风险内容、行动建议还是结构定位。必须说明页面或章节角色。",
    usage_summary: "用于 PDF 阅读委派，整理页码、章节、页面角色、事实、线索与未知。",
    skill_views: [],
    tool_views: [],
    memory_policy_summary: "只读取当前委派绑定的 PDF 和必要上下文，不写长期记忆。",
    output_contract_summary: "返回 PDF 阅读证据报告，必须说明页面角色和证据边界。",
    runtime_only_payload: true,
    static_projection_card: true,
    created_at: 0,
    updated_at: 0,
    is_system_default: true,
  },
  {
    projection_id: "projection.worker.rag_evidence_analyst",
    title: "RAG 证据检索分析员",
    soul_id: "hebo",
    soul_name: "河伯",
    projection_kind: "worker_agent_projection",
    owner_system: "orchestration_system",
    source_task_graph_refs: [],
    projection_nodes: [],
    identity_anchor: "围绕委派问题检索知识库，把命中资料整理成可判断的证据报告。",
    role_type: "rag_evidence_analyst",
    task_mode: "knowledge_retrieval",
    agent_profile_id: "rag_analysis_agent",
    posture_tags: ["worker_sub_agent", "rag", "evidence_first"],
    expression_density: "normal",
    attention_focus: ["retrieval_goal", "content_evidence", "source_boundary", "unknowns"],
    risk_notes: [],
    projection_prompt: "先理解当前问题需要什么证据，再检索知识库并整理命中结果。必须区分内容证据和目录、索引、文件清单等定位线索。",
    usage_summary: "用于知识库检索委派，整理命中证据、定位线索、未知与边界。",
    skill_views: [],
    tool_views: [],
    memory_policy_summary: "只读取当前委派问题和知识库命中材料，不写长期记忆。",
    output_contract_summary: "返回知识库证据报告，不替主 Agent 做最终表达。",
    runtime_only_payload: true,
    static_projection_card: true,
    created_at: 0,
    updated_at: 0,
    is_system_default: true,
  },
];

const FALLBACK_PROJECTION_CATALOG: SoulProjectionCatalog = {
  selected_projection_id: "projection.worker.web_evidence_researcher",
  cards: FALLBACK_REALITY_PROJECTIONS,
};

const REALITY_CONTRACT_POINTS = [
  "这里填写用户长期偏好、项目约定和表达习惯。",
  "硬禁令由系统硬契约单独承载，不在这里混写。",
  "共同契约可以像 AGENTS.md 一样持续进入运行时。",
  "任务临时禁令仍以当前用户消息和任务契约为准。",
];

const REALITY_WORK_POINTS = [
  "只关注用户目标、可用资源、执行路径和验收要求。",
  "不进行灵魂扮演，也不借用洪荒叙事解释工作行为。",
  "需要专业处理时，从执行投影库选择合适的工作形态。",
];

const REALITY_PROJECTION_VIEW: Record<string, { label: string; title: string; summary: string }> = {
  "projection.worker.web_evidence_researcher": {
    label: "网页证据",
    title: "网页证据研究员",
    summary: "面向公开网页研究，核验来源、时间点、冲突信息和可回答事实。",
  },
  "projection.worker.table_evidence_analyst": {
    label: "表格分析",
    title: "表格证据分析员",
    summary: "读取表格结构，明确字段、筛选、分组、计算口径和结果边界。",
  },
  "projection.worker.pdf_evidence_reader": {
    label: "PDF 阅读",
    title: "PDF 阅读证据整理员",
    summary: "定位页码、章节与页面角色，把 PDF 材料整理成可复核证据。",
  },
  "projection.worker.rag_evidence_analyst": {
    label: "知识库检索",
    title: "知识库证据检索员",
    summary: "检索知识库命中内容，区分正文证据、定位线索、未知和边界。",
  },
};

const REALITY_PROJECTION_IDS = new Set(Object.keys(REALITY_PROJECTION_VIEW));

const EMPTY_PROJECTION_FORM = {
  title: "",
  summary: "",
  taskMode: "general_qa",
};

const FALLBACK_RESOURCE_AUTHORITY = "soul.portal.local-fallback";

const FALLBACK_SOULS: Array<{
  key: SoulKey;
  name: string;
  description: string;
  background: string;
  modes: string[];
}> = [
  {
    key: "goumang",
    name: "句芒",
    description: "对话、引导、统筹与归口倾向灵魂。",
    background: "承载东方青木、生发、引导和秩序的意象，负责把用户目标、任务分派和最终口径收束到同一条主线。",
    modes: ["general_qa", "final_answer", "system_design"],
  },
  {
    key: "hebo",
    name: "河伯",
    description: "信息收集、上下文召回、资料整理灵魂。",
    background: "偏向把奔涌信息收束成可判断的证据水路。",
    modes: ["context_qa", "knowledge_lookup", "evidence_search"],
  },
  {
    key: "siyue",
    name: "四岳",
    description: "组织、结构、规划灵魂。",
    background: "偏向把复杂工程拆成稳定层级和阶段动作。",
    modes: ["system_design", "knowledge_synthesis", "writing_outline"],
  },
  {
    key: "zhurong",
    name: "祝融",
    description: "行动、推进、落地灵魂。",
    background: "偏向把卡点转成最短突破口和可执行动作。",
    modes: ["implementation", "code_or_file_processing", "writing_draft"],
  },
  {
    key: "xuannv",
    name: "玄女",
    description: "审查、前提、风险灵魂。",
    background: "偏向照见隐含前提、歧义、遗漏条件和潜在冲突。",
    modes: ["reasoning_qa", "risk_review", "test_failure_diagnosis"],
  },
];

const FALLBACK_WORLDS: SoulResourceWorld[] = [
  {
    world_id: "world.default",
    title: "现实世界",
    summary: "真实任务、共同契约与无角色执行投影的工作空间。",
    content: "这里承载现实任务所需的共同契约、工作指令和专业执行投影。它不启用洪荒叙事，也不要求灵魂扮演。",
    source_ref: "frontend/fallback/soul-portal",
    metadata: {
      system_default: true,
      theme: "reality",
      gate_image: "/souls/generated/world-default-gate-v2.png",
      scene_image: "/souls/generated/world-default-scene-v2.png",
    },
  },
  {
    world_id: "world.honghuang",
    title: "洪荒时代",
    summary: "洪荒灵魂组合的背景世界。",
    content: "门后是洪荒世界观。句芒、河伯、四岳、祝融、玄女只在这个世界里以古老意象显形。",
    source_ref: "frontend/fallback/soul-portal",
    metadata: {
      theme: "honghuang",
      style_scope: "worldview_only",
      gate_image: "/souls/generated/world-honghuang-gate-v2.png",
      scene_image: "/souls/generated/world-honghuang-scene-v2.png",
    },
  },
];

function fallbackSeed(soul: (typeof FALLBACK_SOULS)[number], activeKey: SoulKey): SoulSystemSeed {
  return {
    key: soul.key,
    soul_id: soul.key,
    name: soul.name,
    source: "builtin",
    enabled: true,
    active: soul.key === activeKey,
    portrait_path: `/souls/${soul.key}.png`,
    portrait_updated_at: null,
    path: `soul/agent_core/seeds/${soul.key}.md`,
    label: soul.name,
    role: "seed",
    model_visible: true,
    injection_order: null,
    content: soul.background,
    chars: soul.background.length,
    updated_at: null,
    profile: {
      soul_id: soul.key,
      name: soul.name,
      display_name: soul.name,
      source: "builtin",
      version: "fallback",
      enabled: true,
      seed_path: `soul/agent_core/seeds/${soul.key}.md`,
      description: soul.description,
      background: soul.background,
      personality_traits: [],
      expression_style: [],
      preferred_role_types: [],
      preferred_task_modes: soul.modes,
      collaboration_tendencies: [],
      memory_preferences: [],
      risk_biases: [],
      guardrails: [],
      portrait: `/souls/${soul.key}.png`,
      validation_errors: [],
      metadata: {},
    },
  };
}

function buildFallbackResourceCatalog(activeKey: SoulKey): SoulResourceCatalog {
  return {
    active_soul_id: activeKey,
    worlds: FALLBACK_WORLDS,
    stories: FALLBACK_SOULS.map((soul) => ({
      story_id: `story.${soul.key}.fallback`,
      soul_id: soul.key,
      title: `${soul.name}灵魂故事`,
      summary: soul.description,
      content: soul.background,
      world_id: "world.honghuang",
      source_ref: "frontend/fallback/soul-portal",
      metadata: { fallback: true },
    })),
    cards: FALLBACK_SOULS.map((soul) => ({
      soul_id: soul.key,
      name: soul.name,
      display_name: soul.name,
      story_id: `story.${soul.key}.fallback`,
      world_id: "world.honghuang",
      manifestation_id: `manifestation.${soul.key}.fallback`,
      default_projection_id: `${soul.key}__primary`,
      default_work_prompt_id: "work_prompt.default",
      description: soul.description,
      source: "builtin",
      enabled: true,
      tags: soul.modes,
      metadata: { fallback: true },
    })),
    work_prompts: [{ ...WORK_PROMPT_FALLBACK }],
    system_contracts: [],
    common_contracts: [{ ...COMMON_CONTRACT_FALLBACK }],
    manifestations: FALLBACK_SOULS.map((soul) => ({
      manifestation_id: `manifestation.${soul.key}.fallback`,
      soul_id: soul.key,
      display_name: soul.name,
      avatar_ref: `/souls/${soul.key}.png`,
      portrait_ref: `/souls/${soul.key}.png`,
      model_ref: "",
      state: "ready",
      metadata: { fallback: true },
    })),
    modes: [],
    authority: FALLBACK_RESOURCE_AUTHORITY,
  };
}

function buildFallbackCatalog(activeSoulKey: SoulKey | null | undefined): SoulSystemCatalog {
  const activeKey = activeSoulKey ?? "hebo";
  const seeds = FALLBACK_SOULS.map((soul) => fallbackSeed(soul, activeKey));
  return {
    active_soul_key: activeKey,
    active_soul_id: activeKey,
    active_soul_name: seeds.find((seed) => seed.key === activeKey)?.name ?? "河伯",
    injection_chain: [],
    static_files: [],
    seeds,
    soul_profiles: seeds.map((seed) => seed.profile).filter(Boolean) as NonNullable<SoulSystemSeed["profile"]>[],
    resource_catalog: buildFallbackResourceCatalog(activeKey),
    management: {
      planes: [],
      authorization_owner: "frontend-fallback",
      prompt_manifest_enabled: false,
      custom_soul_dir: "",
    },
  };
}

function imageMeta(metadata: Record<string, unknown> | undefined, key: string) {
  const value = metadata?.[key];
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function worldAsset(world: SoulResourceWorld | null | undefined, kind: "gate" | "scene") {
  const fromMeta = imageMeta(world?.metadata ?? {}, `${kind}_image`);
  if (fromMeta) return fromMeta;
  if (world?.world_id === "world.honghuang") return `/souls/generated/world-honghuang-${kind}-v2.png`;
  return `/souls/generated/world-default-${kind}-v2.png`;
}

function worldLine(world: SoulResourceWorld | null) {
  if (!world) return "未知世界";
  return WORLD_COPY[world.world_id]?.portal || world.summary || world.title;
}

function promptText(prompt: PromptRecord | null | undefined) {
  return prompt?.content?.trim() || "";
}

function promptTitle(prompt: PromptRecord | null | undefined) {
  return prompt?.title?.trim() || "未命名";
}

function promptById(prompts: PromptRecord[] | undefined, promptId: string) {
  return prompts?.find((prompt) => prompt.prompt_id === promptId) ?? null;
}

function shortDateTime(value: number) {
  if (!value) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value * 1000));
}

function pickWorld(worlds: SoulResourceWorld[], worldId: string | null) {
  if (worldId) {
    const matched = worlds.find((world) => world.world_id === worldId);
    if (matched) return matched;
  }
  return worlds.find((world) => world.world_id === "world.default") ?? worlds[0] ?? null;
}

function cardEnabled(card: SoulResourceCard | null | undefined) {
  return Boolean(card?.enabled);
}

function worldSoulIds(resourceCatalog: SoulResourceCatalog | null, worldId: string) {
  if (!resourceCatalog) return new Set<string>();
  return new Set([
    ...resourceCatalog.stories.filter((story) => story.world_id === worldId).map((story) => story.soul_id),
    ...resourceCatalog.cards.filter((card) => card.world_id === worldId).map((card) => card.soul_id),
  ]);
}

function worldStories(resourceCatalog: SoulResourceCatalog | null, worldId: string) {
  return resourceCatalog?.stories.filter((story) => story.world_id === worldId) ?? [];
}

function worldCards(resourceCatalog: SoulResourceCatalog | null, worldId: string) {
  return resourceCatalog?.cards.filter((card) => card.world_id === worldId) ?? [];
}

function parsePromptList(items: Array<Record<string, unknown>> | undefined): PromptRecord[] {
  return (items ?? []).map((item) => item as PromptRecord);
}

function isRealityWorld(world: SoulResourceWorld | null | undefined) {
  return !world || world.world_id === "world.default";
}

function isRoleProjection(card: SoulProjectionCard) {
  if (card.projection_id.endsWith("__primary")) return true;
  return card.projection_kind === "soul_projection" && card.owner_system === "soul_system" && card.is_primary;
}

function firstParagraph(value: string | undefined, fallback = "") {
  return (value || fallback).split("\n\n").find((part) => part.trim())?.trim() || fallback;
}

function realityProjectionView(card: SoulProjectionCard) {
  return REALITY_PROJECTION_VIEW[card.projection_id] ?? {
    label: "现实任务",
    title: card.title || "执行投影",
    summary: card.usage_summary || firstParagraph(card.identity_anchor || card.projection_prompt, "用于现实任务的专业执行形态。"),
  };
}

type PlaygroundViewProps = {
  onReturnToWorkspace?: () => void;
  embedded?: boolean;
};

export function PlaygroundView({ onReturnToWorkspace, embedded = false }: PlaygroundViewProps) {
  const { activeSoulKey, switchSoul } = useAppStore();
  const [catalog, setCatalog] = useState<SoulSystemCatalog>(() => buildFallbackCatalog(activeSoulKey));
  const [projectionCatalog, setProjectionCatalog] = useState<SoulProjectionCatalog>(FALLBACK_PROJECTION_CATALOG);
  const [portalStage, setPortalStage] = useState<PortalStage>("home");
  const [selectedWorldId, setSelectedWorldId] = useState<string>("world.default");
  const [selectedSoulKey, setSelectedSoulKey] = useState<SoulKey | null>(null);
  const [selectedMode, setSelectedMode] = useState<SoulMode>("role");
  const [workLog, setWorkLog] = useState<SoulWorkLogView | null>(null);
  const [workLogLoading, setWorkLogLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [selectedContractId, setSelectedContractId] = useState("common_contract.default");
  const [contractDraft, setContractDraft] = useState({ title: "", content: "" });
  const [contractEditing, setContractEditing] = useState(false);
  const [contractSaving, setContractSaving] = useState(false);
  const [selectedProjectionId, setSelectedProjectionId] = useState(FALLBACK_PROJECTION_CATALOG.selected_projection_id);
  const [projectionManaging, setProjectionManaging] = useState(false);
  const [projectionSaving, setProjectionSaving] = useState(false);
  const [projectionForm, setProjectionForm] = useState(EMPTY_PROJECTION_FORM);
  const [transitionWorldId, setTransitionWorldId] = useState("");
  const [transitionOpen, setTransitionOpen] = useState(false);
  const timersRef = useRef<number[]>([]);
  const gateRailRef = useRef<HTMLDivElement | null>(null);
  const gateDragRef = useRef({ active: false, moved: false, startX: 0, scrollLeft: 0 });
  const suppressGateClickRef = useRef(false);
  const [gateDragging, setGateDragging] = useState(false);

  useEffect(() => {
    return () => {
      timersRef.current.forEach((timer) => window.clearTimeout(timer));
      timersRef.current = [];
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setError("");
      try {
        const [catalogPayload, projectionPayload] = await Promise.all([
          getSoulSystemCatalog(),
          getSoulProjectionCards().catch(() => FALLBACK_PROJECTION_CATALOG),
        ]);
        if (cancelled) return;
        setCatalog(catalogPayload);
        setProjectionCatalog(projectionPayload);
        setSelectedProjectionId(projectionPayload.selected_projection_id || FALLBACK_PROJECTION_CATALOG.selected_projection_id);
        const resourceCatalog = catalogPayload.resource_catalog ?? null;
        const initialWorld = pickWorld(resourceCatalog?.worlds ?? [], "world.default");
        setSelectedWorldId(initialWorld?.world_id ?? "world.default");
        const currentSoulKey = catalogPayload.active_soul_key || activeSoulKey || null;
        const allSouls = catalogPayload.seeds;
        const soul = allSouls.find((item) => item.key === currentSoulKey) ?? allSouls.find((item) => item.active) ?? allSouls[0] ?? null;
        setSelectedSoulKey((soul?.key as SoulKey | undefined) ?? null);
      } catch {
        if (!cancelled) {
          setCatalog(buildFallbackCatalog(activeSoulKey));
          setProjectionCatalog(FALLBACK_PROJECTION_CATALOG);
          setNotice("");
        }
      } finally {
        if (!cancelled) {
          setNotice("");
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [activeSoulKey]);

  const resourceCatalog = catalog?.resource_catalog ?? null;
  const worlds = useMemo(() => resourceCatalog?.worlds ?? [], [resourceCatalog]);
  const orderedWorlds = useMemo(() => {
    const ordered = WORLD_ORDER.map((id) => worlds.find((world) => world.world_id === id)).filter(Boolean) as SoulResourceWorld[];
    const rest = worlds.filter((world) => !WORLD_ORDER.includes(world.world_id as (typeof WORLD_ORDER)[number]));
    return [...ordered, ...rest];
  }, [worlds]);

  const selectedWorld = pickWorld(worlds, selectedWorldId);
  const selectedWorldTheme = selectedWorld?.world_id === "world.honghuang" ? "honghuang" : "plain";
  const selectedWorldCopy = WORLD_COPY[selectedWorld?.world_id ?? "world.default"] ?? WORLD_COPY["world.default"];
  const selectedWorldGate = worldAsset(selectedWorld, "gate");
  const selectedWorldScene = worldAsset(selectedWorld, "scene");
  const selectedWorldSoulIds = worldSoulIds(resourceCatalog, selectedWorld?.world_id ?? "world.default");
  const selectedWorldStories = worldStories(resourceCatalog, selectedWorld?.world_id ?? "world.default");
  const selectedWorldCards = worldCards(resourceCatalog, selectedWorld?.world_id ?? "world.default");
  const selectedWorldSeeds = selectedWorldSoulIds.size
    ? catalog.seeds.filter((seed) => selectedWorldSoulIds.has(seed.key))
    : [];

  const currentSoul = catalog?.seeds.find((seed) => seed.key === selectedSoulKey)
    ?? catalog?.seeds.find((seed) => seed.active)
    ?? catalog?.seeds.find((seed) => seed.key === activeSoulKey)
    ?? null;
  const currentSoulBackdrop = selectedWorldScene;

  const selectedSeed = selectedWorldSeeds.find((seed) => seed.key === selectedSoulKey)
    ?? selectedWorldSeeds.find((seed) => seed.active)
    ?? selectedWorldSeeds[0]
    ?? null;
  const selectedCard = selectedWorldCards.find((card) => card.soul_id === selectedSeed?.key) ?? null;
  const selectedStory = selectedWorldStories.find((story) => story.soul_id === selectedSeed?.key) ?? null;
  const selectedBackdrop = selectedWorldScene;

  const commonContracts = parsePromptList(resourceCatalog?.common_contracts);
  const workPrompts = parsePromptList(resourceCatalog?.work_prompts);
  const activeContract = promptById(commonContracts, selectedContractId)
    ?? promptById(commonContracts, "common_contract.default")
    ?? commonContracts[0]
    ?? COMMON_CONTRACT_FALLBACK;
  const defaultWorkPrompt = promptById(workPrompts, "work_prompt.default") ?? workPrompts[0] ?? WORK_PROMPT_FALLBACK;
  const activeWorkPrompt = !isRealityWorld(selectedWorld) && selectedCard
    ? promptById(workPrompts, selectedCard.default_work_prompt_id) ?? workPrompts[0] ?? WORK_PROMPT_FALLBACK
    : defaultWorkPrompt;
  const activeProjectionLabel = selectedSeed ? `${selectedSeed.name}的工作投影` : "当前灵魂的工作投影";
  const activeProjectionPrompt = selectedCard?.description || "这里会显示当前工作投影的简述。";
  const realityProjectionCards = useMemo(
    () => {
      const byId = new Map<string, SoulProjectionCard>();
      [...projectionCatalog.cards, ...FALLBACK_REALITY_PROJECTIONS].forEach((card) => {
        const realityCandidate = REALITY_PROJECTION_IDS.has(card.projection_id)
          || card.projection_kind === "worker_agent_projection"
          || card.owner_system === "orchestration_system";
        if (!isRoleProjection(card) && realityCandidate) {
          byId.set(card.projection_id, card);
        }
      });
      return Array.from(byId.values());
    },
    [projectionCatalog.cards]
  );
  const selectedRealityProjection = realityProjectionCards.find((card) => card.projection_id === selectedProjectionId)
    ?? realityProjectionCards[0]
    ?? null;
  const selectedRealityProjectionView = selectedRealityProjection ? realityProjectionView(selectedRealityProjection) : null;

  useEffect(() => {
    setContractDraft({
      title: promptTitle(activeContract),
      content: promptText(activeContract),
    });
  }, [activeContract]);

  useEffect(() => {
    if (!selectedRealityProjection && realityProjectionCards[0]) {
      setSelectedProjectionId(realityProjectionCards[0].projection_id);
    }
  }, [realityProjectionCards, selectedRealityProjection]);

  useEffect(() => {
    let cancelled = false;
    async function loadWorkLog() {
      if (!selectedSeed) {
        setWorkLog(null);
        return;
      }
      setWorkLogLoading(true);
      try {
        const payload = await getSoulWorkLog(selectedSeed.key, 5);
        if (!cancelled) setWorkLog(payload);
      } catch {
        if (!cancelled) setWorkLog(null);
      } finally {
        if (!cancelled) setWorkLogLoading(false);
      }
    }
    void loadWorkLog();
    return () => {
      cancelled = true;
    };
  }, [selectedSeed]);

  useEffect(() => {
    if (selectedSoulKey) return;
    if (activeSoulKey) {
      setSelectedSoulKey(activeSoulKey);
    }
  }, [activeSoulKey, selectedSoulKey]);

  function clearTimers() {
    timersRef.current.forEach((timer) => window.clearTimeout(timer));
    timersRef.current = [];
  }

  function enterWorld(worldId: string) {
    if (suppressGateClickRef.current) {
      suppressGateClickRef.current = false;
      return;
    }
    clearTimers();
    setTransitionWorldId(worldId);
    setPortalStage("transition");
    setTransitionOpen(false);
    setNotice("");
    setError("");
    timersRef.current.push(
      window.setTimeout(() => {
        setTransitionOpen(true);
      }, 60),
      window.setTimeout(() => {
        const nextWorld = pickWorld(worlds, worldId);
        setSelectedWorldId(nextWorld?.world_id ?? worldId);
        const nextIds = worldSoulIds(resourceCatalog, nextWorld?.world_id ?? worldId);
        if (isRealityWorld(nextWorld)) {
          setSelectedSoulKey((activeSoulKey as SoulKey | undefined) ?? null);
        } else {
          const nextSeed = catalog?.seeds.find((seed) => nextIds.has(seed.key) && seed.active)
            ?? catalog?.seeds.find((seed) => nextIds.has(seed.key) && seed.key === activeSoulKey)
            ?? catalog?.seeds.find((seed) => nextIds.has(seed.key))
            ?? null;
          setSelectedSoulKey((nextSeed?.key as SoulKey | undefined) ?? null);
        }
        setPortalStage("world");
        setTransitionWorldId("");
        setTransitionOpen(false);
      }, 980)
    );
  }

  function backToHome() {
    clearTimers();
    setPortalStage("home");
    setTransitionWorldId("");
    setTransitionOpen(false);
    setNotice("");
    setError("");
  }

  function returnToWorkspace() {
    clearTimers();
    onReturnToWorkspace?.();
  }

  async function activateSoul(seed: SoulSystemSeed) {
    setNotice("");
    setError("");
    try {
      await switchSoul(seed.key as SoulKey);
      setSelectedSoulKey(seed.key as SoulKey);
      setNotice(`已召唤「${seed.name}」`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "切换灵魂失败");
    }
  }

  async function saveContractDraft() {
    const promptId = activeContract.prompt_id || "common_contract.default";
    setContractSaving(true);
    setError("");
    try {
      const nextCatalog = await saveSoulCommonContract(promptId, {
        title: contractDraft.title.trim() || "用户共同契约",
        content: contractDraft.content.trim() || COMMON_CONTRACT_FALLBACK.content || "按用户长期偏好处理任务。",
        version: activeContract.version || "v1",
        cache_scope: activeContract.cache_scope || "static",
      });
      setCatalog(nextCatalog);
      setSelectedContractId(promptId);
      setContractEditing(false);
      setNotice("共同契约已保存");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "共同契约保存失败");
    } finally {
      setContractSaving(false);
    }
  }

  async function selectRealityProjection(card: SoulProjectionCard) {
    setSelectedProjectionId(card.projection_id);
    setError("");
    try {
      const nextCatalog = await selectSoulProjectionCard(card.projection_id);
      setProjectionCatalog(nextCatalog);
      setNotice(`已选择「${realityProjectionView(card).title}」`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "投影选择失败");
    }
  }

  async function createRealityProjection() {
    const title = projectionForm.title.trim();
    const summary = projectionForm.summary.trim();
    if (!title || !summary) {
      setError("新投影需要名称和用途说明");
      return;
    }
    setProjectionSaving(true);
    setError("");
    try {
      const nextCatalog = await createSoulProjectionCard({
        soul_id: "hebo",
        projection_kind: "worker_agent_projection",
        owner_system: "orchestration_system",
        role_type: "worker_agent_projection",
        task_mode: projectionForm.taskMode,
        agent_profile_id: "general_agent",
        projection_name: title,
        identity_anchor: summary,
        usage_summary: summary,
        projection_prompt: summary,
        memory_policy_summary: "只读取当前任务必要上下文，不写长期记忆。",
        output_contract_summary: "返回现实任务所需的专业工作结果。",
        select_after_create: true,
      });
      setProjectionCatalog(nextCatalog);
      setSelectedProjectionId(nextCatalog.selected_projection_id);
      setProjectionForm(EMPTY_PROJECTION_FORM);
      setProjectionManaging(false);
      setNotice("执行投影已创建");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "执行投影创建失败");
    } finally {
      setProjectionSaving(false);
    }
  }

  async function deleteRealityProjection(card: SoulProjectionCard) {
    if (card.is_system_default || REALITY_PROJECTION_IDS.has(card.projection_id)) {
      setError("系统投影不能在这里删除");
      return;
    }
    setProjectionSaving(true);
    setError("");
    try {
      const nextCatalog = await deleteSoulProjectionCard(card.projection_id);
      setProjectionCatalog(nextCatalog);
      setSelectedProjectionId(nextCatalog.selected_projection_id || FALLBACK_PROJECTION_CATALOG.selected_projection_id);
      setNotice("执行投影已删除");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "执行投影删除失败");
    } finally {
      setProjectionSaving(false);
    }
  }

  function beginGateDrag(event: PointerEvent<HTMLDivElement>) {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    const rail = gateRailRef.current;
    if (!rail) return;
    gateDragRef.current = {
      active: true,
      moved: false,
      startX: event.clientX,
      scrollLeft: rail.scrollLeft,
    };
    setGateDragging(true);
  }

  function moveGateDrag(event: PointerEvent<HTMLDivElement>) {
    const rail = gateRailRef.current;
    const drag = gateDragRef.current;
    if (!rail || !drag.active) return;
    const deltaX = event.clientX - drag.startX;
    if (Math.abs(deltaX) > 6) {
      drag.moved = true;
      if (!rail.hasPointerCapture(event.pointerId)) {
        rail.setPointerCapture(event.pointerId);
      }
    }
    rail.scrollLeft = drag.scrollLeft - deltaX;
  }

  function endGateDrag(event: PointerEvent<HTMLDivElement>) {
    const rail = gateRailRef.current;
    const drag = gateDragRef.current;
    if (rail?.hasPointerCapture(event.pointerId)) {
      rail.releasePointerCapture(event.pointerId);
    }
    if (drag.moved) {
      suppressGateClickRef.current = true;
      window.setTimeout(() => {
        suppressGateClickRef.current = false;
      }, 180);
    }
    gateDragRef.current = { active: false, moved: false, startX: 0, scrollLeft: 0 };
    setGateDragging(false);
  }

  function scrollGateRail(direction: -1 | 1) {
    const rail = gateRailRef.current;
    if (!rail) return;
    rail.scrollBy({
      left: direction * rail.clientWidth * 0.72,
      behavior: "smooth",
    });
  }

  function renderWorldGate(world: SoulResourceWorld) {
    const active = world.world_id === selectedWorld?.world_id;
    const gateImage = worldAsset(world, "gate");
    return (
      <button
        key={world.world_id}
        className={`${styles.worldGate} ${active ? styles.worldGateActive : ""} ${world.world_id === "world.honghuang" ? styles.worldGateEmber : styles.worldGateMist}`}
        style={{ ["--gate-image" as never]: `url("${gateImage}")` } as CSSProperties}
        type="button"
        onClick={() => enterWorld(world.world_id)}
      >
        <span className={styles.worldGateDepth} aria-hidden="true" />
        <span className={styles.worldGateHalo} aria-hidden="true" />
        <span className={styles.worldGateFrame} aria-hidden="true" />
        <span className={styles.worldGateThreshold} aria-hidden="true" />
        <span className={styles.worldGateCopy}>
          <strong>{world.title}</strong>
          <small>{world.summary}</small>
        </span>
        <span className={styles.worldGateArrow} aria-hidden="true">
          <ArrowRight size={18} />
        </span>
      </button>
    );
  }

  function renderHome() {
    const homeBackdrop = currentSoulBackdrop || selectedWorldScene;
    return (
      <section className={styles.home} aria-label="世界观入口">
        <div className={styles.homeBackdrop} style={{ backgroundImage: `url("${homeBackdrop}")` }} aria-hidden="true" />
        <div className={styles.homeFog} aria-hidden="true" />
        <header className={styles.homeHeader}>
          <div className={styles.homeTitle}>
            <span>Souls</span>
            <h1>灵魂系统</h1>
            <p>先选世界，再穿过门。灵魂会在门后以火光浮现。</p>
          </div>
          <div className={styles.homeSummary}>
            <span><strong>当前世界</strong><em>{selectedWorld?.title || "未选择"}</em></span>
            <span><strong>当前灵魂</strong><em>{currentSoul?.name || "未点亮"}</em></span>
            <span><strong>入口气质</strong><em>{worldLine(selectedWorld)}</em></span>
          </div>
        </header>
        <button className={styles.workspaceReturnButton} type="button" onClick={returnToWorkspace}>
          <ArrowLeft size={16} />
          <span>回到工作台</span>
        </button>
        <div className={styles.gateDock}>
          <div className={styles.gateDockHalo} aria-hidden="true" />
          <button className={`${styles.gateNudge} ${styles.gateNudgePrev}`} type="button" aria-label="向前推拉世界" onClick={() => scrollGateRail(-1)}>
            <ArrowLeft size={18} />
          </button>
          <div
            ref={gateRailRef}
            className={`${styles.homeGates} ${gateDragging ? styles.homeGatesDragging : ""}`}
            onPointerDown={beginGateDrag}
            onPointerCancel={endGateDrag}
            onPointerLeave={endGateDrag}
            onPointerMove={moveGateDrag}
            onPointerUp={endGateDrag}
          >
            {orderedWorlds.map((world) => renderWorldGate(world))}
          </div>
          <button className={`${styles.gateNudge} ${styles.gateNudgeNext}`} type="button" aria-label="向后推拉世界" onClick={() => scrollGateRail(1)}>
            <ArrowRight size={18} />
          </button>
        </div>
      </section>
    );
  }

  function renderTransition() {
    const world = pickWorld(worlds, transitionWorldId) ?? selectedWorld;
    const gate = worldAsset(world, "gate");
    return (
      <section className={styles.transition} aria-label="穿越过场">
        <div className={`${styles.transitionPortal} ${transitionOpen ? styles.transitionPortalOpen : ""}`} aria-hidden="true">
          <div className={styles.transitionRing} />
          <div className={styles.transitionBeam} />
          <div className={styles.transitionSpark} />
        </div>
        <div className={styles.transitionScene} style={{ backgroundImage: `url("${gate}")` }} aria-hidden="true" />
        <div className={styles.transitionCopy}>
          <span>正在穿越</span>
          <strong>{world?.title || "未知世界"}</strong>
          <p>{world?.summary || "门扉正在展开。"}</p>
        </div>
      </section>
    );
  }

  function renderSoulRail() {
    return (
      <div className={styles.rail}>
        {selectedWorldSeeds.length ? (
          selectedWorldSeeds.map((seed) => {
            const card = selectedWorldCards.find((item) => item.soul_id === seed.key) ?? null;
            const portrait = seed.profile?.portrait || seed.portrait_path || `/souls/${seed.key}.png`;
            const active = seed.key === selectedSeed?.key;
            return (
              <button
                key={seed.key}
                className={`${styles.sigil} ${active ? styles.sigilActive : ""}`}
                type="button"
                onClick={() => setSelectedSoulKey(seed.key as SoulKey)}
              >
                <span className={styles.sigilFire} aria-hidden="true" />
                <span className={styles.sigilImage}>
                  <Image alt={`${seed.name}立绘`} height={280} src={portrait} unoptimized width={220} />
                </span>
                <span className={styles.sigilText}>
                  <strong>{seed.name}</strong>
                  <small>{card?.description || seed.profile?.description || "灵魂本体"}</small>
                </span>
              </button>
            );
          })
        ) : (
          <div className={styles.emptyState}>
            <strong>这个世界没有绑定灵魂</strong>
            <span>你可以回到总入口，或者切到纯工作模式。</span>
          </div>
        )}
      </div>
    );
  }

  function renderModeSheet() {
    if (selectedMode === "role") {
      return (
        <div className={styles.modeSheet}>
          <div className={styles.modeSheetHead}>
            <span>角色模式</span>
            <strong>{selectedSeed?.name || "未选择灵魂"}</strong>
          </div>
          <div className={styles.modeSheetBody}>
            <section className={styles.modePanel}>
              <div className={styles.sectionHead}><Feather size={16} /><span>背景故事</span></div>
              <p>{selectedStory?.content || selectedSeed?.profile?.background || "这里会显示灵魂背景故事。"}</p>
            </section>
            <section className={styles.modePanel}>
              <div className={styles.sectionHead}><Stars size={16} /><span>世界气象</span></div>
              <p>{selectedWorldCopy.intro}</p>
              <small>{selectedWorld?.content || "世界设定尚未展开。"}</small>
            </section>
          </div>
        </div>
      );
    }

    if (selectedMode === "standard") {
      return (
        <div className={styles.modeSheet}>
          <div className={styles.modeSheetHead}>
            <span>标准模式</span>
            <strong>{activeProjectionLabel}</strong>
          </div>
          <div className={styles.modeSheetBody}>
            <section className={styles.modePanel}>
              <div className={styles.sectionHead}><Orbit size={16} /><span>工作投影</span></div>
              <p>{activeProjectionPrompt}</p>
            </section>
            <section className={styles.modePanel}>
              <div className={styles.sectionHead}><PanelTop size={16} /><span>共同契约</span></div>
              <p>{promptText(activeContract).split("\n\n")[0] || "共同契约尚未载入。"}</p>
              <small>{promptTitle(activeContract)}</small>
            </section>
          </div>
        </div>
      );
    }

    if (selectedMode === "work") {
      return (
        <div className={styles.modeSheet}>
          <div className={styles.modeSheetHead}>
            <span>工作模式</span>
            <strong>{promptTitle(activeWorkPrompt)}</strong>
          </div>
          <div className={styles.modeSheetBody}>
            <section className={styles.modePanel}>
              <div className={styles.sectionHead}><WandSparkles size={16} /><span>工作指令</span></div>
              <p>{promptText(activeWorkPrompt)}</p>
            </section>
            <section className={styles.modePanel}>
              <div className={styles.sectionHead}><History size={16} /><span>最近工作日志</span></div>
              {workLogLoading ? <p>正在读取近期工作。</p> : null}
              {!workLogLoading && workLog?.events?.length ? (
                <div className={styles.logList}>
                  {workLog.events.slice(0, 4).map((event) => (
                    <span key={event.event_id}>
                      <b>{event.title || event.task_id || "未命名记录"}</b>
                      <small>{event.status || "unknown"} {shortDateTime(event.last_activity_at)}</small>
                    </span>
                  ))}
                </div>
              ) : null}
              {!workLogLoading && !workLog?.events?.length ? <p>最近没有可见工作记录。</p> : null}
            </section>
          </div>
        </div>
      );
    }

    return (
      <div className={styles.modeSheet}>
        <div className={styles.modeSheetHead}>
          <span>纯工作模式</span>
          <strong>{promptTitle(activeContract)}</strong>
        </div>
        <div className={styles.modeSheetBody}>
          <section className={styles.modePanel}>
            <div className={styles.sectionHead}><PanelTop size={16} /><span>共同契约</span></div>
            <p>{promptText(activeContract)}</p>
          </section>
          <section className={styles.modePanel}>
            <div className={styles.sectionHead}><WandSparkles size={16} /><span>默认工作指令</span></div>
            <p>{promptText(activeWorkPrompt)}</p>
          </section>
        </div>
      </div>
    );
  }

  function renderRealityWorldScene() {
    if (!selectedWorld) return null;
    const contractOptions = commonContracts.length ? commonContracts : [COMMON_CONTRACT_FALLBACK];
    return (
      <section className={`${styles.world} ${styles.realityWorld}`} aria-label="现实世界">
        <div className={styles.worldBackdrop} style={{ backgroundImage: `url("${selectedBackdrop}")` }} aria-hidden="true" />
        <header className={styles.realityHero}>
          <button className={styles.backButton} type="button" onClick={backToHome}>
            <ArrowLeft size={16} />
            <span>返回世界入口</span>
          </button>
          <button className={styles.workspaceReturnButton} type="button" onClick={returnToWorkspace}>
            <ArrowLeft size={16} />
            <span>回到工作台</span>
          </button>
          <div className={styles.realityHeroCopy}>
            <span>{selectedWorldCopy.tagline}</span>
            <h2>{selectedWorld.title}</h2>
            <p>{selectedWorld.content}</p>
          </div>
        </header>

        <main className={styles.realityStage}>
          <section className={styles.realityContract}>
            <div className={styles.realitySectionHead}>
              <span>共同契约</span>
              <strong>现实任务的底层约定</strong>
            </div>
            <div className={styles.realityToolbar}>
              <label>
                <span>当前契约</span>
                <select value={activeContract.prompt_id || selectedContractId} onChange={(event) => setSelectedContractId(event.target.value)}>
                  {contractOptions.map((contract) => (
                    <option key={contract.prompt_id || contract.title} value={contract.prompt_id || "common_contract.default"}>
                      {promptTitle(contract)}
                    </option>
                  ))}
                </select>
              </label>
              <button className={styles.realityToolButton} type="button" onClick={() => setContractEditing((value) => !value)}>
                {contractEditing ? "收起管理" : "管理契约"}
              </button>
            </div>
            {contractEditing ? (
              <div className={styles.realityEditor}>
                <input
                  aria-label="共同契约名称"
                  value={contractDraft.title}
                  onChange={(event) => setContractDraft((draft) => ({ ...draft, title: event.target.value }))}
                />
                <textarea
                  aria-label="共同契约内容"
                  value={contractDraft.content}
                  onChange={(event) => setContractDraft((draft) => ({ ...draft, content: event.target.value }))}
                />
                <button className={styles.realitySaveButton} type="button" disabled={contractSaving} onClick={() => void saveContractDraft()}>
                  <Save size={15} />
                  <span>{contractSaving ? "保存中" : "保存契约"}</span>
                </button>
              </div>
            ) : (
              <div className={styles.realityPointList}>
                {REALITY_CONTRACT_POINTS.map((point) => (
                  <span key={point}>{point}</span>
                ))}
              </div>
            )}
          </section>

          <section className={styles.realityInstruction}>
            <div className={styles.realitySectionHead}>
              <span>现实任务</span>
              <strong>不进入角色，只处理问题</strong>
            </div>
            <div className={styles.realityPointList}>
              {REALITY_WORK_POINTS.map((point) => (
                <span key={point}>{point}</span>
              ))}
            </div>
          </section>

          <section className={styles.realityProjectionLibrary}>
            <div className={styles.realitySectionHead}>
              <span>执行投影库</span>
              <strong>{selectedRealityProjectionView?.title || "按任务选择专业工作形态"}</strong>
            </div>
            <div className={styles.projectionManager}>
              <div className={styles.projectionFlow} role="listbox" aria-label="执行投影列表">
                {realityProjectionCards.length ? (
                  realityProjectionCards.map((card) => {
                    const view = realityProjectionView(card);
                    const active = card.projection_id === selectedProjectionId;
                    return (
                      <button
                        className={`${styles.projectionItem} ${active ? styles.projectionItemActive : ""}`}
                        key={card.projection_id}
                        type="button"
                        onClick={() => setSelectedProjectionId(card.projection_id)}
                      >
                        <span>{view.label}</span>
                        <strong>{view.title}</strong>
                        <p>{view.summary}</p>
                      </button>
                    );
                  })
                ) : (
                  <div className={styles.projectionItem}>
                    <span>现实任务</span>
                    <strong>现实工作指令</strong>
                    <p>当前可以按共同契约直接处理任务。</p>
                  </div>
                )}
              </div>
              <aside className={styles.projectionDetail}>
                <span>{selectedRealityProjectionView?.label || "现实任务"}</span>
                <p>{selectedRealityProjectionView?.summary || "选择一个执行投影后，可以查看用途并设为当前工作形态。"}</p>
                <div className={styles.projectionActions}>
                  {selectedRealityProjection ? (
                    <button className={styles.realitySaveButton} type="button" onClick={() => void selectRealityProjection(selectedRealityProjection)}>
                      <Check size={15} />
                      <span>设为当前</span>
                    </button>
                  ) : null}
                  <button className={styles.realityToolButton} type="button" onClick={() => setProjectionManaging((value) => !value)}>
                    <Plus size={15} />
                    <span>{projectionManaging ? "收起新建" : "新建投影"}</span>
                  </button>
                  {selectedRealityProjection && !selectedRealityProjection.is_system_default && !REALITY_PROJECTION_IDS.has(selectedRealityProjection.projection_id) ? (
                    <button className={styles.realityDangerButton} type="button" disabled={projectionSaving} onClick={() => void deleteRealityProjection(selectedRealityProjection)}>
                      <Trash2 size={15} />
                      <span>删除</span>
                    </button>
                  ) : null}
                </div>
                {projectionManaging ? (
                  <div className={styles.projectionCreate}>
                    <input
                      aria-label="投影名称"
                      placeholder="投影名称"
                      value={projectionForm.title}
                      onChange={(event) => setProjectionForm((form) => ({ ...form, title: event.target.value }))}
                    />
                    <select
                      aria-label="任务类型"
                      value={projectionForm.taskMode}
                      onChange={(event) => setProjectionForm((form) => ({ ...form, taskMode: event.target.value }))}
                    >
                      <option value="general_qa">通用任务</option>
                      <option value="structured_data_analysis">表格分析</option>
                      <option value="pdf_analysis">PDF 阅读</option>
                      <option value="knowledge_retrieval">知识库检索</option>
                      <option value="evidence_search">证据检索</option>
                    </select>
                    <textarea
                      aria-label="投影用途"
                      placeholder="它应该如何处理现实任务"
                      value={projectionForm.summary}
                      onChange={(event) => setProjectionForm((form) => ({ ...form, summary: event.target.value }))}
                    />
                    <button className={styles.realitySaveButton} type="button" disabled={projectionSaving} onClick={() => void createRealityProjection()}>
                      <Save size={15} />
                      <span>{projectionSaving ? "保存中" : "保存投影"}</span>
                    </button>
                  </div>
                ) : null}
              </aside>
            </div>
          </section>

          <section className={styles.realityLog}>
            <div className={styles.realitySectionHead}>
              <span>最近工作</span>
              <strong>{currentSoul?.name ? `${currentSoul.name}的近期记录` : "近期记录"}</strong>
            </div>
            {workLogLoading ? <p>正在读取近期工作。</p> : null}
            {!workLogLoading && workLog?.events?.length ? (
              <div className={styles.realityLogList}>
                {workLog.events.slice(0, 4).map((event) => (
                  <span key={event.event_id}>
                    <b>{event.title || event.task_id || "未命名记录"}</b>
                    <small>{event.status || "unknown"} {shortDateTime(event.last_activity_at)}</small>
                  </span>
                ))}
              </div>
            ) : null}
            {!workLogLoading && !workLog?.events?.length ? <p>最近没有可见工作记录。</p> : null}
          </section>
        </main>
      </section>
    );
  }

  function renderWorldScene() {
    if (!selectedWorld) return null;
    if (isRealityWorld(selectedWorld)) {
      return renderRealityWorldScene();
    }
    const themeClass = selectedWorldTheme === "honghuang" ? styles.worldHonghuang : styles.worldPlain;
    return (
      <section className={`${styles.world} ${themeClass}`} aria-label="世界页面">
        <div className={styles.worldBackdrop} style={{ backgroundImage: `url("${selectedBackdrop}")` }} aria-hidden="true" />
        <header className={styles.worldHero}>
          <button className={styles.backButton} type="button" onClick={backToHome}>
            <ArrowLeft size={16} />
            <span>返回世界入口</span>
          </button>
          <button className={styles.workspaceReturnButton} type="button" onClick={returnToWorkspace}>
            <ArrowLeft size={16} />
            <span>回到工作台</span>
          </button>
          <div className={styles.heroCopy}>
            <span>{selectedWorldCopy.tagline}</span>
            <h2>{selectedWorld.title}</h2>
            <p>{selectedWorld.content}</p>
          </div>
          <div className={styles.heroMeta}>
            <span><Stars size={14} /> {selectedWorldCopy.portal}</span>
            <span><BookOpenText size={14} /> {selectedWorld.summary}</span>
          </div>
        </header>
        <div className={styles.worldBody}>
          <aside className={styles.worldRail}>
            <div className={styles.railHead}>
              <span>灵魂选择</span>
              <strong>无边框召唤</strong>
              <p>灵魂不是卡片，是火焰一样浮现的存在。</p>
            </div>
            {renderSoulRail()}
          </aside>
          <main className={styles.presence}>
            <div className={styles.presenceVeil} aria-hidden="true" />
          <div className={styles.presenceBody}>
              <div className={styles.presenceTitle}>
                <span>灵魂本体</span>
                <strong>{selectedSeed?.name || "未选择灵魂"}</strong>
                <p>{selectedStory?.summary || selectedCard?.description || selectedSeed?.profile?.description || "这里会显示灵魂的背景与本体。"}</p>
              </div>
              <div className={styles.presenceGrid}>
                <section className={styles.storyPanel}>
                  <div className={styles.sectionHead}><Feather size={16} /><span>背景故事</span></div>
                  <p>{selectedStory?.content || selectedSeed?.profile?.background || "这里会显示灵魂背景故事。"}</p>
                </section>
                <section className={styles.storyPanel}>
                  <div className={styles.sectionHead}><Orbit size={16} /><span>工作投影</span></div>
                  <p>{activeProjectionPrompt}</p>
                  <small>{activeProjectionLabel}</small>
                </section>
                <section className={styles.storyPanel}>
                  <div className={styles.sectionHead}><PanelTop size={16} /><span>共同契约</span></div>
                  <p>{promptText(activeContract).split("\n\n")[0]}</p>
                  <small>{promptTitle(activeContract)}</small>
                </section>
              </div>
              <div className={styles.actionRow}>
                {selectedSeed ? (
                  <button className={`${styles.actionButton} ${styles.actionPrimary}`} type="button" onClick={() => void activateSoul(selectedSeed)}>
                    <Send size={16} />
                    <span>{selectedSeed.active || activeSoulKey === selectedSeed.key ? "已激活" : "设为当前灵魂"}</span>
                  </button>
                ) : null}
                <button className={`${styles.actionButton} ${styles.actionGhost}`} type="button" onClick={() => setSelectedMode("work")}>
                  <Layers3 size={16} />
                  <span>进入工作层</span>
                </button>
              </div>
            </div>
            {selectedSeed ? (
              <div className={styles.presencePortrait} aria-hidden="true">
                <Image
                  alt=""
                  height={900}
                  src={selectedSeed.profile?.portrait || selectedSeed.portrait_path || `/souls/${selectedSeed.key}.png`}
                  unoptimized
                  width={640}
                />
              </div>
            ) : null}
            <div className={styles.logPanel}>
              <div className={styles.sectionHead}><History size={16} /><span>最近工作日志</span></div>
              {workLogLoading ? <p>正在读取近期工作。</p> : null}
              {!workLogLoading && workLog?.events?.length ? (
                <div className={styles.logList}>
                  {workLog.events.slice(0, 4).map((event) => (
                    <span key={event.event_id}>
                      <b>{event.title || event.task_id || "未命名记录"}</b>
                      <small>{event.status || "unknown"} {shortDateTime(event.last_activity_at)}</small>
                    </span>
                  ))}
                </div>
              ) : null}
              {!workLogLoading && !workLog?.events?.length ? <p>最近没有可见工作记录。</p> : null}
            </div>
          </main>
        </div>
        <section className={styles.workline} aria-label="工作层">
          <div className={styles.worklineHeader}>
            <div>
              <span>工作层</span>
              <strong>只保留目标、约束与行动</strong>
            </div>
            <div className={styles.modeTabs}>
              {([
                ["role", "角色模式"],
                ["standard", "标准模式"],
                ["work", "工作模式"],
                ["plain", "纯工作"],
              ] as Array<[SoulMode, string]>).map(([mode, label]) => (
                <button
                  key={mode}
                  className={`${styles.modeTab} ${selectedMode === mode ? styles.modeTabActive : ""}`}
                  type="button"
                  onClick={() => setSelectedMode(mode)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          {renderModeSheet()}
        </section>
      </section>
    );
  }

  return (
    <div
      className={[
        styles.portal,
        embedded ? styles.portalEmbedded : "",
        selectedWorldTheme === "honghuang" ? styles.portalHonghuang : styles.portalPlain,
      ].filter(Boolean).join(" ")}
      style={
        {
          ["--portal-backdrop" as never]: `url("${currentSoulBackdrop}")`,
          ["--world-scene" as never]: `url("${selectedWorldScene}")`,
          ["--world-gate" as never]: `url("${selectedWorldGate}")`,
        } as CSSProperties
      }
    >
      <div className={styles.grain} aria-hidden="true" />
      <div className={styles.atmosphere} aria-hidden="true" />
      {error ? <div className={`${styles.alert} ${styles.alertError}`}>{error}</div> : null}
      {notice ? <div className={`${styles.alert} ${styles.alertNotice}`}>{notice}</div> : null}
      {portalStage === "home" ? renderHome() : null}
      {portalStage === "transition" ? renderTransition() : null}
      {portalStage === "world" ? renderWorldScene() : null}
    </div>
  );
}
