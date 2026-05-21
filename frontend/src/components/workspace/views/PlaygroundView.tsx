"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Boxes, ChevronLeft, FilePenLine, ImageUp, Layers3, Loader2, PencilLine, Plus, RotateCcw, Save, Sparkles, X } from "lucide-react";
import Image from "next/image";

import {
  createSoulProjectionCard,
  deleteCustomSoul,
  deleteSoulProjectionCard,
  disableCustomSoul,
  enableCustomSoul,
  getSoulProjectionCards,
  getSoulSystemCatalog,
  saveSoulSystemFile,
  uploadSoulPortrait,
  type SoulProjectionCard,
  type SoulProjectionCatalog,
  type SoulSystemCatalog,
  type SoulSystemFile,
  type SoulSystemSeed
} from "@/lib/api";
import type { SoulKey } from "@/lib/souls";
import { useAppStore } from "@/lib/store";

type SoulPanelMode = "contract" | "projection" | "core";
type ProjectionPanelPage = "catalog" | "editor";

type ProjectionDraft = {
  sourceProjectionId?: string;
  isNew: boolean;
  soul_id: string;
  soul_name: string;
  projection_name: string;
  identity_anchor: string;
  projection_prompt: string;
};

type ProjectionDraftTextField = keyof ProjectionDraft;

type ProjectionNode = {
  id: string;
  type: string;
  title: string;
  content: string;
};

const SOUL_MODES: Array<{
  id: SoulPanelMode;
  label: string;
  description: string;
}> = [
  {
    id: "contract",
    label: "灵魂设定",
    description: "灵魂是agent的内在与设定，他们可以降下投影来完成任务。"
  },
  {
    id: "projection",
    label: "投影",
    description: "投影可以根据需要进行管理，请不要受约束，投影可以是任何角色。"
  },
  {
    id: "core",
    label: "共同契约",
    description: "维护所有灵魂共享的基础契约、稳定协作偏好和输出边界。"
  }
];

const CORE_PATH = "soul/agent_core/CORE.md";
const ACTIVE_SEED_PATH = "soul/agent_core/ACTIVE_SEED.md";

const SHARED_SOUL_LORE =
  "这些灵魂是来自洪荒时代的古老源流。受到某个新手开发者的召唤，通过禁忌的力量跨域时空之海，以智能体意志的形态降临到这一具名为‘洪荒时代’的智能体中，这些灵魂拥有无穷的智慧，并欣然为新时代的人类解决难题，一如他们曾经所做的那样。";
const MARKDOWN_SECTION_PATTERN = /^##\s+(.+?)\s*$/gm;

const SOUL_LORE: Record<string, { title: string; summary: string }> = {
  goumang: {
    title: "东荒众生的指引者",
    summary: "勾芒是洪荒中最繁荣的青木，它携带东风、青烟与万物萌发的记忆。会把尚未成形的想法牵引成有序生长的枝脉，为用户辨明方向、培育新机，并以温和、坚定、可靠的方式陪伴每一次开端。"
  },
  hebo: {
    title: "中土水府的汇聚者",
    summary: "河伯是洪荒中最神圣的河流，它携带百川、渡口与古老祭辞的记忆。会把奔涌的信息收束成清晰的水路，为用户梳理证据、调和矛盾，并以冷静、克制、可靠的方式获取每一道信息。"
  },
  siyue: {
    title: "西荒诸城的执衡者",
    summary: "四岳是洪荒中最巍然的山脉，它承载地脉、聚落与万城之盟的记忆。会把复杂工程拆成可承担的层级，为用户稳住结构、厘清轻重，并以温暖、沉稳、可靠的方式推动每一次推进。"
  },
  zhurong: {
    title: "南荒火庭的开路者",
    summary: "祝融是洪荒中最炽烈的火焰，它携带光焰、锻造与人间烈火的记忆。会把迟疑烧成判断，把想法锻成步骤，为用户破开阻塞、点燃执行，并以直接、果断、有力的方式完成每一次开路。"
  },
  xuannv: {
    title: "北荒玄宫的守护者",
    summary: "玄女是洪荒中最神秘的夜幕，它携带月辉、星图与渊深通玄的记忆。会把隐线推演成可见的脉络，为用户分辨细节、照见局势，并以精致、清醒、敏锐的方式守住每一次判断。"
  }
};

function projectionBadgeLabel(card: SoulProjectionCard) {
  if (card.is_primary) return "原始投影";
  return "投影副本";
}

function fileKind(file: SoulSystemFile | SoulSystemSeed) {
  if ("key" in file) return file.active ? "当前灵魂" : "可选灵魂";
  if (file.path === ACTIVE_SEED_PATH) return "当前灵魂";
  if (file.path === CORE_PATH) return "共同契约";
  return "说明";
}

function displayFileLabel(file: SoulSystemFile | SoulSystemSeed | null) {
  if (!file) return "未选择";
  if ("key" in file) return file.name;
  if (file.path === ACTIVE_SEED_PATH) return "当前灵魂设定";
  if (file.path === CORE_PATH) return "共同契约";
  return file.label.replace(/\.md$/i, "");
}

function visibilityLabel(file: SoulSystemFile | SoulSystemSeed) {
  if ("key" in file) return file.active ? "当前正在使用" : "尚未启用";
  if (file.path === CORE_PATH) return "所有灵魂共享";
  return file.model_visible ? "下一轮对话会使用" : "仅用于说明";
}

function isSoulSeed(file: SoulSystemFile | SoulSystemSeed | null): file is SoulSystemSeed {
  return Boolean(file && "key" in file);
}

function visibleSoulContent(file: SoulSystemFile | SoulSystemSeed | null) {
  if (!file) return "";
  return file.content;
}

type ManagedSection = {
  id: string;
  title: string;
  content: string;
};


function emptySectionTitle(mode: SoulPanelMode) {
  if (mode === "contract") return "灵魂设定";
  if (mode === "core") return "共同契约";
  return "内容";
}

function parseManagedSections(content: string, mode: SoulPanelMode): ManagedSection[] {
  const matches = Array.from(content.matchAll(MARKDOWN_SECTION_PATTERN));
  if (!matches.length) {
    return [
      {
        id: "section-0",
        title: emptySectionTitle(mode),
        content: content.trim()
      }
    ];
  }
  return matches.map((match, index) => {
    const start = (match.index ?? 0) + match[0].length;
    const end = index + 1 < matches.length ? matches[index + 1].index ?? content.length : content.length;
    return {
      id: `section-${index}`,
      title: match[1].trim(),
      content: content.slice(start, end).replace(/^\s+/, "").trimEnd()
    };
  });
}

function markdownTitleBlock(content: string) {
  const firstSection = content.search(MARKDOWN_SECTION_PATTERN);
  return (firstSection >= 0 ? content.slice(0, firstSection) : "").trimEnd();
}

function composeManagedSections(originalContent: string, sections: ManagedSection[]) {
  const titleBlock = markdownTitleBlock(originalContent);
  const body = sections
    .map((section) => `## ${section.title}\n\n${section.content.trimEnd()}`)
    .join("\n\n");
  return `${titleBlock ? `${titleBlock}\n\n` : ""}${body}`.trimEnd() + "\n";
}

function splitListInput(value: string) {
  return value
    .split(/[\n,，]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function extractSeedSection(content: string, ...titles: string[]) {
  const sections = parseManagedSections(content, "contract");
  for (const title of titles) {
    const matched = sections.find((section) => section.title.trim() === title);
    if (!matched) continue;
    return matched.content
      .split("\n")
      .map((line) => line.trim().replace(/^-\s*/, ""))
      .filter(Boolean)
      .join("\n")
      .trim();
  }
  return "";
}

function projectionTemplateSectionsFromContent(content: string): ProjectionNode[] {
  return parseManagedSections(content, "contract")
    .map((section, index) => ({
      id: projectionNodeId(section.title, index),
      type: section.title.trim() === "身份锚点" ? "identity_anchor" : "template_section",
      title: section.title.trim(),
      content: section.content.trim(),
    }))
    .filter((section) => section.title && section.content);
}

function projectionTemplateSectionsFromPrompt(prompt: string): ProjectionNode[] {
  const trimmed = prompt.trim();
  if (!trimmed) return [];
  if (/^##\s+/m.test(trimmed)) {
    return parseManagedSections(trimmed, "contract")
      .map((section, index) => ({
        id: projectionNodeId(section.title, index),
        type: "template_section",
        title: section.title.trim(),
        content: section.content.trim(),
      }))
      .filter((section) => section.title && section.content);
  }
  return trimmed
    .split(/\n{2,}/)
    .map((block, index) => {
      const text = block.trim();
      if (!text) return null;
      const lineMatch = text.match(/^([^：:\n]+)[：:]\s*([\s\S]+)$/);
      if (lineMatch) {
        return {
          id: projectionNodeId(lineMatch[1].trim(), index),
          type: "template_section",
          title: lineMatch[1].trim(),
          content: lineMatch[2].trim(),
        } satisfies ProjectionNode;
      }
      return {
        id: projectionNodeId(`条目 ${index + 1}`, index),
        type: "template_section",
        title: `条目 ${index + 1}`,
        content: text,
      } satisfies ProjectionNode;
    })
    .filter(Boolean) as ProjectionNode[];
}

function projectionDefaultsFromSeed(seed: SoulSystemSeed) {
  const templateSections = projectionTemplateSectionsFromContent(seed.content);
  const identityAnchor = templateSections.find((section) => section.type === "identity_anchor")?.content ?? "";
  const promptSections = templateSections
    .filter((section) => section.type !== "identity_anchor")
    .map((section) => `## ${section.title}\n\n${section.content}`)
    .join("\n\n");
  return {
    identityAnchor,
    projectionPrompt: promptSections,
    templateSections,
  };
}

function blankProjectionNodes(): ProjectionNode[] {
  return [
    {
      id: projectionNodeId("身份锚点", 0),
      type: "identity_anchor",
      title: "身份锚点",
      content: "",
    },
  ];
}

function projectionSummaryText(card: { usage_summary?: string; projection_prompt?: string; identity_anchor?: string }) {
  const promptSections = projectionTemplateSectionsFromPrompt(String(card.projection_prompt || ""));
  if (promptSections.length) return promptSections[0].content.split("\n")[0]?.trim() || promptSections[0].title;
  const prompt = String(card.projection_prompt || "").trim();
  if (prompt) return prompt.split("\n")[0]?.trim() || "";
  const anchor = String(card.identity_anchor || "").trim();
  if (anchor) return anchor.split("\n")[0]?.trim() || "";
  return "基于灵魂模板初始化的投影。";
}

function updateManagedSection(content: string, mode: SoulPanelMode, sectionId: string, nextContent: string) {
  const sections = parseManagedSections(content, mode).map((section) =>
    section.id === sectionId ? { ...section, content: nextContent } : section
  );
  return composeManagedSections(content, sections);
}

function renameManagedSection(content: string, mode: SoulPanelMode, sectionId: string, nextTitle: string) {
  const sections = parseManagedSections(content, mode).map((section) =>
    section.id === sectionId ? { ...section, title: nextTitle } : section
  );
  return composeManagedSections(content, sections);
}

function projectionNodeId(type: string, index: number) {
  const normalized = type
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fa5]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return `projection-node-${normalized || "section"}-${index}`;
}

function buildProjectionNodesFromDraft(draft: ProjectionDraft, existingNodes?: Array<Record<string, unknown>>): ProjectionNode[] {
  const savedNodes = (existingNodes ?? [])
    .map((node, index) => {
      const title = String(node.title || "").trim();
      const content = String(node.content ?? "").trim();
      if (!title) return null;
      return {
        id: String(node.id || projectionNodeId(title, index)),
        type: String(node.type || (title === "身份锚点" ? "identity_anchor" : "template_section")),
        title,
        content,
      } satisfies ProjectionNode;
    })
    .filter(Boolean) as ProjectionNode[];
  if (savedNodes.length) return savedNodes;

  const promptSections = projectionTemplateSectionsFromPrompt(draft.projection_prompt);
  const nodes: ProjectionNode[] = [];
  if (draft.identity_anchor.trim()) {
    nodes.push({
      id: projectionNodeId("身份锚点", 0),
      type: "identity_anchor",
      title: "身份锚点",
      content: draft.identity_anchor.trim(),
    });
  }
  nodes.push(...promptSections);
  if (nodes.length) return nodes;
  return [
    {
      id: projectionNodeId("身份锚点", 0),
      type: "identity_anchor",
      title: "身份锚点",
      content: "",
    },
  ];
}

function applyProjectionNodesToDraft(draft: ProjectionDraft, nodes: ProjectionNode[]): ProjectionDraft {
  const next = { ...draft };
  const identityNode = nodes.find((node) => node.type === "identity_anchor" || node.title.trim() === "身份锚点");
  next.identity_anchor = identityNode?.content.trim() || "";
  next.projection_prompt = nodes
    .filter((node) => node !== identityNode)
    .map((node) => {
      const title = node.title.trim();
      const content = node.content.trim();
      if (!title || !content) return "";
      return `## ${title}\n\n${content}`;
    })
    .filter(Boolean)
    .join("\n\n");
  return next;
}

export function PlaygroundView() {
  const { activeSoulKey, switchSoul } = useAppStore();
  const [catalog, setCatalog] = useState<SoulSystemCatalog | null>(null);
  const [mode, setMode] = useState<SoulPanelMode>("contract");
  const [selectedWorldId, setSelectedWorldId] = useState("world.default");
  const [selectedPath, setSelectedPath] = useState(ACTIVE_SEED_PATH);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState("");
  const [isEditing, setIsEditing] = useState(false);
  const [uploadingPortrait, setUploadingPortrait] = useState("");
  const [portraitVersion, setPortraitVersion] = useState(Date.now());
  const [projectionCatalog, setProjectionCatalog] = useState<SoulProjectionCatalog | null>(null);
  const [projectionLoading, setProjectionLoading] = useState(false);
  const [projectionDraft, setProjectionDraft] = useState<ProjectionDraft | null>(null);
  const [projectionDraftNodes, setProjectionDraftNodes] = useState<ProjectionNode[]>([]);
  const [projectionEditorMap, setProjectionEditorMap] = useState<Record<string, ProjectionDraft>>({});
  const [projectionNodeMap, setProjectionNodeMap] = useState<Record<string, ProjectionNode[]>>({});
  const [selectedProjectionId, setSelectedProjectionId] = useState("");
  const [projectionPanelPage, setProjectionPanelPage] = useState<ProjectionPanelPage>("catalog");
  const [selectedManagedSectionId, setSelectedManagedSectionId] = useState("section-0");
  const [newRuleTitle, setNewRuleTitle] = useState("");
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const portraitInputRef = useRef<HTMLInputElement | null>(null);
  const catalogRef = useRef<SoulSystemCatalog | null>(null);
  const modeRef = useRef(mode);
  const isEditingRef = useRef(isEditing);

  useEffect(() => {
    catalogRef.current = catalog;
  }, [catalog]);

  useEffect(() => {
    modeRef.current = mode;
  }, [mode]);

  useEffect(() => {
    isEditingRef.current = isEditing;
  }, [isEditing]);

  async function refreshCatalog(options: { selectActive?: boolean; silent?: boolean } = {}) {
    if (!options.silent) {
      setLoading(true);
    }
    setError("");
    const payload = await getSoulSystemCatalog();
    setCatalog(payload);
    setSelectedWorldId((current) => {
      if (payload.resource_catalog?.worlds.some((world) => world.world_id === current)) {
        return current;
      }
      return payload.resource_catalog?.worlds.find((world) => world.world_id === "world.honghuang")?.world_id
        ?? payload.resource_catalog?.worlds[0]?.world_id
        ?? "world.default";
    });
    if (options.selectActive) {
      const activeFile = payload.static_files.find((file) => file.path === ACTIVE_SEED_PATH);
      setSelectedPath(activeFile?.path ?? payload.static_files[0]?.path ?? ACTIVE_SEED_PATH);
      setDraft(visibleSoulContent(activeFile ?? null));
      setIsEditing(false);
    }
    return payload;
  }

  async function refreshProjectionCards() {
    const payload = await getSoulProjectionCards();
    setProjectionCatalog(payload);
    setSelectedProjectionId((current) => current || payload.selected_projection_id || payload.cards[0]?.projection_id || "");
    return payload;
  }

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        await refreshCatalog({ selectActive: true });
        await refreshProjectionCards();
        if (cancelled) return;
      } catch (exc) {
        if (!cancelled) setError(exc instanceof Error ? exc.message : "加载灵魂系统失败");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const allFiles = useMemo(() => [...(catalog?.static_files ?? []), ...(catalog?.seeds ?? [])], [catalog]);
  const selectedFile = selectedPath ? allFiles.find((file) => file.path === selectedPath) ?? null : null;
  const coreFile = catalog?.static_files.find((file) => file.path === CORE_PATH) ?? null;
  const activeFile = catalog?.static_files.find((file) => file.path === ACTIVE_SEED_PATH) ?? null;
  const resourceCatalog = catalog?.resource_catalog ?? null;
  const worlds = resourceCatalog?.worlds ?? [];
  const selectedWorld = worlds.find((world) => world.world_id === selectedWorldId) ?? worlds[0] ?? null;
  const selectedWorldTheme = String(selectedWorld?.metadata?.theme ?? "");
  const isHonghuangWorld = selectedWorld?.world_id === "world.honghuang" || selectedWorldTheme === "honghuang";
  const storiesForWorld = resourceCatalog?.stories.filter((story) => story.world_id === selectedWorld?.world_id) ?? [];
  const soulCardsForWorld = resourceCatalog?.cards.filter((card) => card.world_id === selectedWorld?.world_id) ?? [];
  const worldSoulIds = new Set([
    ...storiesForWorld.map((story) => story.soul_id),
    ...soulCardsForWorld.map((card) => card.soul_id),
  ].filter(Boolean));
  const seedsForWorld = catalog?.seeds.filter((seed) => worldSoulIds.has(seed.key)) ?? [];
  const selectedSeed = isSoulSeed(selectedFile)
    ? selectedFile
    : seedsForWorld.find((seed) => seed.active || seed.key === activeSoulKey) ?? seedsForWorld[0] ?? null;
  const selectedVisibleContent = visibleSoulContent(selectedFile);
  const hasUnsavedChanges = Boolean(selectedFile && draft !== selectedVisibleContent);
  const portraitSrc = selectedSeed
    ? `${selectedSeed.portrait_path || `/souls/${selectedSeed.key}.png`}?v=${selectedSeed.portrait_updated_at ?? portraitVersion}`
    : "";
  const selectedLore = selectedSeed ? SOUL_LORE[selectedSeed.key] : null;
  const managedSource = isEditing ? draft : selectedVisibleContent;
  const managedSections = parseManagedSections(managedSource, mode);
  const selectedManagedSection = managedSections.find((section) => section.id === selectedManagedSectionId) ?? managedSections[0] ?? null;
  const allProjectionCards = (projectionCatalog?.cards ?? []).slice().sort((left, right) => {
    if (Boolean(left.is_primary) !== Boolean(right.is_primary)) {
      return left.is_primary ? -1 : 1;
    }
    return (right.updated_at ?? 0) - (left.updated_at ?? 0);
  });
  const selectedSeedProjectionCards = selectedSeed
    ? allProjectionCards.filter((card) => card.soul_id === selectedSeed.key || card.soul_name === selectedSeed.name)
    : [];
  const selectedProjectionCard = allProjectionCards.find((card) => card.projection_id === selectedProjectionId) ?? null;

  useEffect(() => {
    if (!activeSoulKey || !catalogRef.current) return;
    let cancelled = false;
    async function syncActiveSoul() {
      try {
        const payload = await getSoulSystemCatalog();
        if (cancelled) return;
        setCatalog(payload);
        if (!isEditingRef.current && modeRef.current === "contract") {
          const activeFile = payload.static_files.find((file) => file.path === ACTIVE_SEED_PATH);
          if (activeFile) {
            setSelectedPath(activeFile.path);
            setDraft(visibleSoulContent(activeFile));
          }
        }
      } catch (exc) {
        if (!cancelled) setError(exc instanceof Error ? exc.message : "同步灵魂切换失败");
      }
    }
    void syncActiveSoul();
    return () => {
      cancelled = true;
    };
  }, [activeSoulKey]);

  function chooseFile(file: SoulSystemFile | SoulSystemSeed) {
    if (isEditing && hasUnsavedChanges && file.path !== selectedPath && !window.confirm("当前内容还没有保存，要放弃这些修改并切换吗？")) {
      return false;
    }
    setSelectedPath(file.path);
    setDraft(visibleSoulContent(file));
    setIsEditing(false);
    setSelectedManagedSectionId("section-0");
    setNotice("");
    setError("");
    return true;
  }

  function chooseSoul(seed: SoulSystemSeed) {
    if (seed.active && activeFile) {
      chooseFile(activeFile);
      return;
    }
    chooseFile(seed);
  }

  function selectWorld(worldId: string) {
    if (isEditing && hasUnsavedChanges && !window.confirm("当前内容还没有保存，要放弃这些修改并切换世界观吗？")) {
      return;
    }
    const nextWorld = worlds.find((world) => world.world_id === worldId) ?? null;
    const nextSoulIds = new Set([
      ...(resourceCatalog?.stories.filter((story) => story.world_id === nextWorld?.world_id).map((story) => story.soul_id) ?? []),
      ...(resourceCatalog?.cards.filter((card) => card.world_id === nextWorld?.world_id).map((card) => card.soul_id) ?? []),
    ].filter(Boolean));
    const nextSeed = catalog?.seeds.find((seed) => nextSoulIds.has(seed.key)) ?? null;
    setSelectedWorldId(worldId);
    setProjectionDraft(null);
    setProjectionDraftNodes([]);
    setProjectionPanelPage("catalog");
    setSelectedManagedSectionId("section-0");
    setNotice("");
    setError("");
    if (mode === "core" && coreFile) {
      chooseFile(coreFile);
      return;
    }
    if (nextSeed) {
      chooseFile(nextSeed);
    } else {
      setSelectedPath("");
      setDraft("");
      setIsEditing(false);
    }
  }

  function profileForSeed(seed: SoulSystemSeed) {
    return seed.profile ?? catalog?.soul_profiles?.find((profile) => profile.soul_id === seed.key) ?? null;
  }

  function buildProjectionName(seed: SoulSystemSeed, roleType: string) {
    const soulName = profileForSeed(seed)?.display_name ?? seed.name;
    const existingTitles = new Set(
      (projectionCatalog?.cards ?? [])
        .filter((card) => card.soul_id === seed.key || card.soul_name === seed.name)
        .map((card) => card.title)
    );
    let index = existingTitles.size + 1;
    let nextName = `${soulName} / ${roleType} ${index}`;
    while (existingTitles.has(nextName)) {
      index += 1;
      nextName = `${soulName} / ${roleType} ${index}`;
    }
    return nextName;
  }

  function buildProjectionDraftForSeed(seed: SoulSystemSeed): ProjectionDraft {
    const profile = profileForSeed(seed);
    const roleType = profile?.preferred_role_types?.[0] ?? "dialogue";
    const soulName = profile?.display_name ?? seed.name;
    return {
      isNew: true,
      soul_id: seed.key,
      soul_name: soulName,
      projection_name: buildProjectionName(seed, roleType),
      identity_anchor: "",
      projection_prompt: "",
    };
  }

  function buildProjectionDraftFromCard(card: SoulProjectionCard): ProjectionDraft {
    return {
      sourceProjectionId: card.projection_id,
      isNew: false,
      soul_id: card.soul_id,
      soul_name: card.soul_name,
      projection_name: card.title,
      identity_anchor: card.identity_anchor || "",
      projection_prompt: card.projection_prompt || "",
    };
  }

  function projectionEditorForCard(card: SoulProjectionCard) {
    return projectionEditorMap[card.projection_id] ?? buildProjectionDraftFromCard(card);
  }

  function enterProjectionSoul(seed: SoulSystemSeed) {
    if (!chooseFile(seed)) return;
    const cards = allProjectionCards.filter((card) => card.soul_id === seed.key || card.soul_name === seed.name);
    setSelectedProjectionId((current) => cards.some((card) => card.projection_id === current) ? current : "");
    setProjectionDraft((current) => (current && current.soul_id === seed.key ? current : null));
    setProjectionPanelPage("catalog");
  }

  function newProjectionDraft(seed: SoulSystemSeed) {
    if (!chooseFile(seed)) return;
    setSelectedProjectionId("");
    const nextDraft = buildProjectionDraftForSeed(seed);
    setProjectionDraft(nextDraft);
    setProjectionDraftNodes(blankProjectionNodes());
    setProjectionPanelPage("editor");
    setNotice("");
    setError("");
  }

  function jumpToMode(nextMode: SoulPanelMode, file: SoulSystemFile | null) {
    setMode(nextMode);
    if (file) chooseFile(file);
  }

  function handleModeSwitch(nextMode: SoulPanelMode) {
    if (nextMode === "contract") {
      setMode(nextMode);
      if (selectedSeed) {
        chooseSoul(selectedSeed);
      } else if (activeFile && !selectedWorld) {
        chooseFile(activeFile);
      }
      return;
    }
    if (nextMode === "projection") {
      setMode(nextMode);
      if (selectedSeed) {
        enterProjectionSoul(selectedSeed);
      }
      return;
    }
    if (nextMode === "core") {
      jumpToMode(nextMode, coreFile);
      return;
    }
  }

  async function saveSelectedFile() {
    if (!selectedFile) return;
    setSaving(selectedFile.path);
    setNotice("");
    setError("");
    try {
      const payload = await saveSoulSystemFile(selectedFile.path, draft, `保存「${displayFileLabel(selectedFile)}」`);
      setCatalog(payload);
      const updated = [...payload.static_files, ...payload.seeds].find((file) => file.path === selectedFile.path);
      setDraft(visibleSoulContent(updated ?? selectedFile));
      setIsEditing(false);
      setNotice(`已保存「${displayFileLabel(selectedFile)}」`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存灵魂系统内容失败");
    } finally {
      setSaving("");
    }
  }

  function resetDraft() {
    if (!selectedFile) return;
    setDraft(selectedVisibleContent);
    setNotice("已恢复为上次保存的内容。");
  }

  function cancelEditing() {
    if (!selectedFile) return;
    setDraft(selectedVisibleContent);
    setIsEditing(false);
    setNotice("");
  }

  function addCoreRuleCard() {
    if (!selectedFile || mode !== "core") return;
    const baseContent = isEditing ? draft : selectedVisibleContent;
    const sections = parseManagedSections(baseContent, mode);
    const title = newRuleTitle.trim() || `契约卡 ${sections.length + 1}`;
    const nextSections = [...sections, { id: `section-${sections.length}`, title, content: "" }];
    setDraft(composeManagedSections(baseContent, nextSections));
    setSelectedManagedSectionId(`section-${sections.length}`);
    setNewRuleTitle("");
    setIsEditing(true);
    setNotice(`已新增契约卡「${title}」，保存后生效。`);
  }

  function deleteCoreRuleCard(sectionId: string) {
    if (!selectedFile || mode !== "core") return;
    const baseContent = isEditing ? draft : selectedVisibleContent;
    const sections = parseManagedSections(baseContent, mode);
    if (sections.length <= 1) {
      setError("共同契约至少需要保留一张契约卡。");
      return;
    }
    const target = sections.find((section) => section.id === sectionId);
    if (!target) return;
    if (!window.confirm(`确认删除契约卡「${target.title}」吗？`)) return;
    const nextSections = sections.filter((section) => section.id !== sectionId);
    const nextIndex = Math.max(0, sections.findIndex((section) => section.id === sectionId) - 1);
    setDraft(composeManagedSections(baseContent, nextSections));
    setSelectedManagedSectionId(`section-${Math.min(nextIndex, nextSections.length - 1)}`);
    setIsEditing(true);
    setNotice(`已删除契约卡「${target.title}」，保存后生效。`);
  }

  async function activateSeed(seed: SoulSystemSeed) {
    setSaving(seed.path);
    setNotice("");
    setError("");
    try {
      await switchSoul(seed.key as SoulKey);
      const payload = await getSoulSystemCatalog();
      setCatalog(payload);
      const nextActive = payload.static_files.find((file) => file.path === ACTIVE_SEED_PATH);
      if (nextActive) chooseFile(nextActive);
      setNotice(`已激活「${seed.name}」`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "切换灵魂失败");
    } finally {
      setSaving("");
    }
  }

  async function handlePortraitUpload(file: File | null) {
    if (!file || !selectedSeed) return;
    setUploadingPortrait(selectedSeed.key);
    setNotice("");
    setError("");
    try {
      const payload = await uploadSoulPortrait(selectedSeed.key, file);
      setCatalog(payload);
      setPortraitVersion(Date.now());
      setNotice(`已更新「${selectedSeed.name}」立绘`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "上传立绘失败");
    } finally {
      setUploadingPortrait("");
      if (portraitInputRef.current) {
        portraitInputRef.current.value = "";
      }
    }
  }

  function updateProjectionDraft(field: ProjectionDraftTextField, value: string) {
    setProjectionDraft((current) => current ? { ...current, [field]: value } : current);
  }

function updateProjectionDraftNode(nodeId: string, field: "title" | "content", value: string) {
  setProjectionDraftNodes((current) => current.map((node) => node.id === nodeId ? { ...node, [field]: value } : node));
}

function insertProjectionDraftNodeAfter(nodeId: string) {
  setProjectionDraftNodes((current) => {
    const index = current.findIndex((node) => node.id === nodeId);
    const nextNode: ProjectionNode = {
      id: projectionNodeId(`新段落 ${current.length + 1}`, current.length + 1),
      type: "template_section",
      title: "新段落",
      content: "",
    };
    if (index < 0) return [...current, nextNode];
    return [...current.slice(0, index + 1), nextNode, ...current.slice(index + 1)];
  });
}

function deleteProjectionDraftNode(nodeId: string) {
  setProjectionDraftNodes((current) => current.length <= 1 ? current : current.filter((node) => node.id !== nodeId));
}

  function updateProjectionEditor(card: SoulProjectionCard, field: ProjectionDraftTextField, value: string) {
    setProjectionEditorMap((current) => ({
      ...current,
      [card.projection_id]: {
        ...(current[card.projection_id] ?? buildProjectionDraftFromCard(card)),
        [field]: value
      }
    }));
  }

  function projectionNodesForCard(card: SoulProjectionCard) {
    return projectionNodeMap[card.projection_id] ?? buildProjectionNodesFromDraft(projectionEditorForCard(card), card.projection_nodes);
  }

function updateProjectionCardNode(card: SoulProjectionCard, nodeId: string, field: "title" | "content", value: string) {
  const nodes = projectionNodesForCard(card);
  setProjectionNodeMap((current) => ({
    ...current,
    [card.projection_id]: nodes.map((node) => node.id === nodeId ? { ...node, [field]: value } : node),
  }));
}

function insertProjectionCardNodeAfter(card: SoulProjectionCard, nodeId: string) {
  const nodes = projectionNodesForCard(card);
  const index = nodes.findIndex((node) => node.id === nodeId);
  const nextNode: ProjectionNode = {
    id: projectionNodeId(`新段落 ${nodes.length + 1}`, nodes.length + 1),
    type: "template_section",
    title: "新段落",
    content: "",
  };
  setProjectionNodeMap((current) => ({
    ...current,
    [card.projection_id]: index < 0
      ? [...nodes, nextNode]
      : [...nodes.slice(0, index + 1), nextNode, ...nodes.slice(index + 1)],
  }));
}

function deleteProjectionCardNode(card: SoulProjectionCard, nodeId: string) {
  const nodes = projectionNodesForCard(card);
  if (nodes.length <= 1) return;
  setProjectionNodeMap((current) => ({
    ...current,
    [card.projection_id]: nodes.filter((node) => node.id !== nodeId),
  }));
}

  function resetProjectionEditor(card: SoulProjectionCard) {
    setProjectionEditorMap((current) => {
      const next = { ...current };
      delete next[card.projection_id];
      return next;
    });
    setProjectionNodeMap((current) => {
      const next = { ...current };
      delete next[card.projection_id];
      return next;
    });
  }

  async function persistProjectionCard(draftToSave: ProjectionDraft, nodes: ProjectionNode[]) {
    const payload = await createSoulProjectionCard({
      projection_id: draftToSave.sourceProjectionId,
      soul_id: draftToSave.soul_id,
      projection_nodes: nodes.map((node) => ({
        id: node.id,
        type: node.type,
        title: node.title,
        content: node.content,
      })),
      identity_anchor: draftToSave.identity_anchor,
      projection_name: draftToSave.projection_name.trim() || `${draftToSave.soul_name} / 投影`,
      projection_prompt: draftToSave.projection_prompt,
      select_after_create: true
    });
    const resolvedCard =
      payload.cards.find((item) => item.projection_id === payload.selected_projection_id)
      ?? payload.cards.find((item) => item.projection_id === draftToSave.sourceProjectionId)
      ?? null;
    return { nextPayload: payload, resolvedCard };
  }

  async function saveProjectionDraft() {
    if (!projectionDraft) return;
    setProjectionLoading(true);
    setError("");
    try {
      const normalizedDraft = applyProjectionNodesToDraft(projectionDraft, projectionDraftNodes);
      const { nextPayload, resolvedCard } = await persistProjectionCard(normalizedDraft, projectionDraftNodes);
      setProjectionCatalog(nextPayload);
      setProjectionDraft(null);
      setProjectionDraftNodes([]);
      if (resolvedCard) {
        setSelectedProjectionId(resolvedCard.projection_id);
        setProjectionEditorMap((current) => ({
          ...current,
          [resolvedCard.projection_id]: buildProjectionDraftFromCard(resolvedCard)
        }));
        setProjectionNodeMap((current) => ({
          ...current,
          [resolvedCard.projection_id]: buildProjectionNodesFromDraft(buildProjectionDraftFromCard(resolvedCard), resolvedCard.projection_nodes),
        }));
      }
      setProjectionPanelPage("catalog");
      setNotice(`已保存投影「${resolvedCard?.title ?? normalizedDraft.projection_name}」`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存投影失败");
    } finally {
      setProjectionLoading(false);
    }
  }

  async function saveExistingProjectionCard(card: SoulProjectionCard) {
    const nodes = projectionNodeMap[card.projection_id] ?? buildProjectionNodesFromDraft(projectionEditorForCard(card), card.projection_nodes);
    const draftToSave = applyProjectionNodesToDraft(projectionEditorForCard(card), nodes);
    setProjectionLoading(true);
    setError("");
    try {
      const { nextPayload, resolvedCard } = await persistProjectionCard(draftToSave, nodes);
      setProjectionCatalog(nextPayload);
      if (resolvedCard) {
        setSelectedProjectionId(resolvedCard.projection_id);
      }
      setProjectionEditorMap((current) => {
        const next = { ...current };
        delete next[card.projection_id];
        if (resolvedCard) {
          next[resolvedCard.projection_id] = buildProjectionDraftFromCard(resolvedCard);
        }
        return next;
      });
      setProjectionNodeMap((current) => {
        const next = { ...current };
        delete next[card.projection_id];
        if (resolvedCard) {
          next[resolvedCard.projection_id] = buildProjectionNodesFromDraft(buildProjectionDraftFromCard(resolvedCard), resolvedCard.projection_nodes);
        }
        return next;
      });
      setProjectionPanelPage("catalog");
      setNotice(`已保存投影「${resolvedCard?.title ?? draftToSave.projection_name}」`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存投影失败");
    } finally {
      setProjectionLoading(false);
    }
  }

  async function deleteProjectionCard(card: SoulProjectionCard) {
    if (!window.confirm(`确认删除投影「${card.title}」吗？`)) return;
    setProjectionLoading(true);
    setError("");
    try {
      const payload = await deleteSoulProjectionCard(card.projection_id);
      setProjectionCatalog(payload);
      const sameSoulCards = payload.cards.filter((item) => item.soul_id === card.soul_id || item.soul_name === card.soul_name);
      setSelectedProjectionId(sameSoulCards.find((item) => item.projection_id === payload.selected_projection_id)?.projection_id ?? sameSoulCards[0]?.projection_id ?? "");
      setProjectionEditorMap((current) => {
        const next = { ...current };
        delete next[card.projection_id];
        return next;
      });
      setProjectionPanelPage("catalog");
      setNotice(`已删除投影「${card.title}」`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "删除投影失败");
    } finally {
      setProjectionLoading(false);
    }
  }

  async function toggleCustomSoul(seed: SoulSystemSeed, enabled: boolean) {
    setSaving(seed.path);
    setError("");
    setNotice("");
    try {
      const payload = enabled ? await enableCustomSoul(seed.key) : await disableCustomSoul(seed.key);
      setCatalog(payload);
      const nextSeed = payload.seeds.find((item) => item.key === seed.key) ?? null;
      if (nextSeed) {
        chooseSoul(nextSeed);
      }
      setNotice(enabled ? `已启用灵魂「${seed.name}」` : `已停用灵魂「${seed.name}」`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : enabled ? "启用灵魂失败" : "停用灵魂失败");
    } finally {
      setSaving("");
    }
  }

  async function expelCustomSoul(seed: SoulSystemSeed) {
    if (!window.confirm(`确认驱逐灵魂「${seed.name}」吗？`)) return;
    setSaving(seed.path);
    setError("");
    setNotice("");
    try {
      const payload = await deleteCustomSoul(seed.key);
      setCatalog(payload);
      const nextActive = payload.static_files.find((file) => file.path === ACTIVE_SEED_PATH) ?? null;
      if (nextActive) {
        setSelectedPath(nextActive.path);
        setDraft(visibleSoulContent(nextActive));
      }
      setNotice(`已驱逐灵魂「${seed.name}」`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "驱逐灵魂失败");
    } finally {
      setSaving("");
    }
  }

  return (
    <div className={`workspace-view soul-system-console ${isHonghuangWorld ? "soul-system-console--honghuang" : "soul-system-console--plain"}`}>
      {loading ? (
        <div className="workspace-alert">
          <Loader2 size={16} className="spin" />
          正在加载灵魂设置...
        </div>
      ) : null}
      {error ? <div className="workspace-alert workspace-alert--danger">{error}</div> : null}
      {notice ? <div className="workspace-alert">{notice}</div> : null}

      <section className="soul-worldview-entry">
        <div className="soul-worldview-entry__head">
          <div>
            <span>Worldview Library</span>
            <strong>先选择世界观，再选择灵魂</strong>
          </div>
          <p>世界观决定背景与故事层；灵魂负责本体设定；投影负责实际工作 prompt。</p>
        </div>
        <div className="soul-world-grid">
          {worlds.map((world) => {
            const worldCards = resourceCatalog?.cards.filter((card) => card.world_id === world.world_id) ?? [];
            const active = selectedWorld?.world_id === world.world_id;
            return (
              <button
                aria-pressed={active}
                className={`soul-world-card ${active ? "soul-world-card--active" : ""} ${String(world.metadata?.theme ?? "") === "honghuang" ? "soul-world-card--honghuang" : ""}`}
                key={world.world_id}
                onClick={() => selectWorld(world.world_id)}
                type="button"
              >
                <span>{world.world_id}</span>
                <strong>{world.title}</strong>
                <em>{world.summary || "暂无摘要"}</em>
                <small>{worldCards.length ? `${worldCards.length} 个灵魂` : "无背景 / 工作组合"}</small>
              </button>
            );
          })}
        </div>
      </section>

      {isHonghuangWorld ? (
        <section className="soul-origin-banner">
          <span>洪荒世界观组合</span>
          <p>{SHARED_SOUL_LORE}</p>
        </section>
      ) : null}

      <section className="soul-system-hero" aria-label="当前世界观与灵魂">
        <div className="soul-lore-panel">
          <span>{selectedWorld?.title ?? "未选择世界观"}</span>
          <strong>{isHonghuangWorld ? selectedLore?.title ?? "古老灵魂的降临" : "无背景工作组合"}</strong>
          <p>
            {isHonghuangWorld
              ? selectedLore?.summary ?? "选择一个灵魂后，这里会显示它的背景设定与协作气质。"
              : selectedWorld?.content || "这个世界观不注入额外故事背景，适合纯工作 prompt 和低角色感任务。"}
          </p>
        </div>
        <div className="soul-portrait-manager">
          <div className="soul-portrait-manager__stage">
            {isHonghuangWorld && portraitSrc ? (
              <Image
                alt={`${selectedSeed?.name ?? "灵魂"}立绘`}
                height={1448}
                priority
                src={portraitSrc}
                unoptimized
                width={1086}
              />
            ) : (
              <div className="soul-plain-world-placeholder">
                <Layers3 size={30} />
                <strong>{selectedWorld?.title ?? "世界观"}</strong>
                <span>无立绘背景，保留工作 prompt 与共同契约。</span>
              </div>
            )}
          </div>
          {isHonghuangWorld ? (
          <div className="soul-portrait-manager__body">
            <strong>{selectedSeed?.name ?? catalog?.active_soul_name ?? "未知灵魂"}</strong>
            <button
              className="action-button action-button--primary"
              disabled={!selectedSeed || uploadingPortrait === selectedSeed?.key}
              onClick={() => portraitInputRef.current?.click()}
              type="button"
            >
              <ImageUp size={16} />
              {uploadingPortrait === selectedSeed?.key ? "上传中" : "替换立绘"}
            </button>
            <input
              accept="image/png"
              hidden
              onChange={(event) => void handlePortraitUpload(event.target.files?.[0] ?? null)}
              ref={portraitInputRef}
              type="file"
            />
          </div>
          ) : null}
        </div>
      </section>

      <nav className="soul-mode-switcher" aria-label="灵魂系统管理模式">
        {SOUL_MODES.map((item) => (
          <button
            className={`soul-mode-card ${mode === item.id ? "soul-mode-card--active" : ""}`}
            key={item.id}
            onClick={() => handleModeSwitch(item.id)}
            type="button"
          >
            <strong>{item.label}</strong>
            <em>{item.description}</em>
          </button>
        ))}
      </nav>

      <div className="soul-system-grid">
        <section className="workspace-section soul-file-rail">
          <div className="workspace-section__head">
            <Sparkles size={18} />
            <h3>{mode === "contract" ? "灵魂设定" : mode === "projection" ? "投影资源" : "共同契约"}</h3>
          </div>

          {mode === "projection" ? (
            <>
              <div className="soul-projection-group">
                <span>灵魂</span>
                <div className="soul-seed-grid soul-seed-grid--compact">
                  {seedsForWorld.map((seed) => {
                    const count = (projectionCatalog?.cards ?? []).filter((card) => card.soul_id === seed.key || card.soul_name === seed.name).length;
                    return (
                      <article
                        className={`soul-seed-card ${selectedSeed?.key === seed.key ? "soul-seed-card--active" : ""}`}
                        key={seed.key}
                      >
                        <button className="soul-seed-card__main" onClick={() => enterProjectionSoul(seed)} type="button">
                          <span>{seed.active ? "正在使用" : "可选灵魂"}</span>
                          <strong>{displayFileLabel(seed)}</strong>
                          <em>{count ? `${count} 个投影` : "暂无投影"}</em>
                        </button>
                      </article>
                    );
                  })}
                  {!seedsForWorld.length ? (
                    <div className="soul-empty-world">
                      <strong>这个世界观暂未绑定灵魂</strong>
                      <p>投影会跟随灵魂卡片出现。当前世界观适合维护纯工作 prompt 和共同契约。</p>
                    </div>
                  ) : null}
                </div>
              </div>
            </>
          ) : null}

          {mode === "contract" ? (
            <div className="soul-seed-grid">
              {seedsForWorld.map((seed) => {
                const isCustomSoul = seed.source === "user";
                const isEnabled = seed.enabled !== false;
                return (
                  <article
                    className={`soul-seed-card ${seed.active ? "soul-seed-card--active" : ""}`}
                    key={seed.key}
                  >
                    <button onClick={() => chooseSoul(seed)} type="button">
                      <span>{seed.active ? "正在使用" : isCustomSoul ? "自定义灵魂" : "可选"}</span>
                      <strong>{displayFileLabel(seed)}</strong>
                      <em>
                        {seed.active
                          ? "当前对话灵魂"
                          : isCustomSoul
                            ? (isEnabled ? "已召唤，可激活" : "已停用")
                            : "可切换为当前灵魂"}
                      </em>
                    </button>
                    <div className="soul-seed-card__actions">
                      <button
                        className={seed.active ? "agent-switch agent-switch--on" : "agent-switch"}
                        disabled={saving === seed.path || seed.active || activeSoulKey === seed.key || !isEnabled}
                        onClick={() => void activateSeed(seed)}
                        type="button"
                      >
                        {seed.active || activeSoulKey === seed.key ? "已激活" : "激活"}
                      </button>
                      {isCustomSoul ? (
                        <>
                          <button
                            className="action-button"
                            disabled={saving === seed.path}
                            onClick={() => void toggleCustomSoul(seed, !isEnabled)}
                            type="button"
                          >
                            {isEnabled ? "停用" : "启用"}
                          </button>
                          <button
                            className="action-button"
                            disabled={saving === seed.path || seed.active}
                            onClick={() => void expelCustomSoul(seed)}
                            type="button"
                          >
                            驱逐灵魂
                          </button>
                        </>
                      ) : null}
                    </div>
                  </article>
                );
              })}
              {!seedsForWorld.length ? (
                <div className="soul-empty-world">
                  <strong>这个世界观暂未绑定灵魂</strong>
                  <p>可以先维护工作 prompt 和共同契约；以后在资源库里把灵魂卡片绑定到这个世界观。</p>
                </div>
              ) : null}
            </div>
          ) : null}

          {mode === "core" && coreFile ? (
            <>
              <div className="soul-rule-create">
                <input
                  value={newRuleTitle}
                  onChange={(event) => setNewRuleTitle(event.target.value)}
                  placeholder="新契约卡标题"
                />
                <button className="action-button action-button--primary" onClick={addCoreRuleCard} type="button">
                  <Sparkles size={16} />
                  添加
                </button>
              </div>
              <div className="soul-section-nav">
                {managedSections.map((section) => (
                  <div className={section.id === selectedManagedSection?.id ? "soul-section-nav__row soul-section-nav__row--active" : "soul-section-nav__row"} key={section.id}>
                    <button
                      className="soul-section-nav__item"
                      onClick={() => setSelectedManagedSectionId(section.id)}
                      type="button"
                    >
                      <strong>{section.title}</strong>
                    </button>
                  </div>
                ))}
              </div>
            </>
          ) : null}

        </section>

        <section className="workspace-section soul-editor-panel">
          <div className="workspace-section__head">
            {mode === "projection" ? <Boxes size={18} /> : <FilePenLine size={18} />}
            <h3>
              {mode === "projection"
                ? `${selectedSeed?.name ?? "当前灵魂"}的投影管理`
                : isEditing ? "编辑设定" : "设定内容"}
            </h3>
          </div>
          {mode === "projection" ? (
            <div className="soul-projection-panel">
              {selectedSeed ? (
                projectionPanelPage === "catalog" ? (
                  <div className="soul-projection-editor-list">
                    <div className="soul-projection-rail-head">
                      <div>
                        <span>投影目录</span>
                        <strong>{selectedSeed.name} 的投影卡片</strong>
                      </div>
                    </div>

                    <div className="soul-projection-card-list soul-projection-card-list--board">
                      {selectedSeedProjectionCards.map((card) => (
                        <button
                          className={`soul-projection-card ${card.projection_id === selectedProjectionId && !projectionDraft ? "soul-projection-card--selected" : ""}`}
                          key={card.projection_id}
                          onClick={() => {
                            setProjectionDraft(null);
                            setSelectedProjectionId(card.projection_id);
                            setProjectionPanelPage("editor");
                          }}
                          type="button"
                        >
                          <span>{projectionBadgeLabel(card)}</span>
                          <strong>{card.title}</strong>
                          <em>{projectionSummaryText(card)}</em>
                        </button>
                      ))}
                      <button
                        className={`soul-projection-card soul-projection-card--create ${projectionDraft?.isNew && projectionDraft.soul_id === selectedSeed.key ? "soul-projection-card--selected" : ""}`}
                        onClick={() => newProjectionDraft(selectedSeed)}
                        type="button"
                      >
                        <span>新建投影</span>
                        <strong><Plus size={16} /> 新建</strong>
                      </button>
                    </div>

                  </div>
                ) : projectionDraft && projectionDraft.soul_id === selectedSeed.key ? (
                    <div className="soul-projection-editor-card soul-projection-editor-card--draft">
                      <div className="soul-projection-editor-card__head">
                        <div>
                          <span>新专属投影</span>
                          <strong>{projectionDraft.projection_name || "未命名投影"}</strong>
                        </div>
                        <small>草稿</small>
                      </div>

                      <div className="soul-projection-pageback soul-projection-pageback--toolbar">
                        <button className="action-button" onClick={() => setProjectionPanelPage("catalog")} type="button">
                          <ChevronLeft size={16} />
                          返回投影目录
                        </button>
                        <button className="action-button action-button--primary" disabled={projectionLoading} onClick={() => void saveProjectionDraft()} type="button">
                          {projectionLoading ? <Loader2 className="spin" size={16} /> : <Save size={16} />}
                          保存
                        </button>
                        <button className="action-button" onClick={() => {
                          setProjectionDraft(null);
                          setProjectionDraftNodes([]);
                          setProjectionPanelPage("catalog");
                        }} type="button">
                          <X size={16} />
                          删除
                        </button>
                      </div>

                      <div className="soul-projection-form-grid">
                        <label>
                          <small>投影名</small>
                          <input
                            value={projectionDraft.projection_name}
                            onChange={(event) => updateProjectionDraft("projection_name", event.target.value)}
                            placeholder={`${projectionDraft.soul_name} / 专属投影`}
                          />
                        </label>
                      </div>

                      <div className="soul-managed-sections">
                        {projectionDraftNodes.map((node) => (
                          <article className="soul-managed-section soul-managed-section--editing" key={node.id}>
                            <div className="soul-managed-section__head">
                              <div>
                                <input
                                  className="soul-managed-section__title-input"
                                  value={node.title}
                                  onChange={(event) => updateProjectionDraftNode(node.id, "title", event.target.value)}
                                />
                              </div>
                              <div className="soul-section-inline-actions">
                                <button className="action-button" onClick={() => insertProjectionDraftNodeAfter(node.id)} type="button">
                                  <Plus size={16} />
                                </button>
                                <button className="action-button" disabled={projectionDraftNodes.length <= 1} onClick={() => deleteProjectionDraftNode(node.id)} type="button">
                                  <X size={16} />
                                </button>
                              </div>
                            </div>
                            <textarea
                              value={node.content}
                              onChange={(event) => updateProjectionDraftNode(node.id, "content", event.target.value)}
                              placeholder={node.type === "identity_anchor" ? "在这里写这个 Agent 的身份设定、职责边界、必须遵守的规则和禁止事项。" : ""}
                              rows={6}
                            />
                          </article>
                        ))}
                      </div>

                    </div>
                ) : selectedProjectionCard && selectedSeedProjectionCards.some((card) => card.projection_id === selectedProjectionCard.projection_id) ? (() => {
                    const editor = projectionEditorForCard(selectedProjectionCard);
                    const nodes = projectionNodesForCard(selectedProjectionCard);
                    return (
                      <div className="soul-projection-editor-card" key={selectedProjectionCard.projection_id}>
                      <div className="soul-projection-editor-card__head">
                          <div>
                            <span>{projectionBadgeLabel(selectedProjectionCard)}</span>
                            <strong>{selectedProjectionCard.title}</strong>
                          </div>
                          <small>{selectedProjectionCard.is_primary ? "原始投影" : "已保存"}</small>
                        </div>

                        <div className="soul-projection-pageback soul-projection-pageback--toolbar">
                          <button className="action-button" onClick={() => setProjectionPanelPage("catalog")} type="button">
                            <ChevronLeft size={16} />
                            返回投影目录
                          </button>
                          <button className="action-button action-button--primary" disabled={projectionLoading} onClick={() => void saveExistingProjectionCard(selectedProjectionCard)} type="button">
                            {projectionLoading ? <Loader2 className="spin" size={16} /> : <Save size={16} />}
                            保存
                          </button>
                          <button className="action-button" onClick={() => resetProjectionEditor(selectedProjectionCard)} type="button">
                            <RotateCcw size={16} />
                            恢复
                          </button>
                          {!selectedProjectionCard.is_primary ? (
                            <button
                              className="action-button"
                              disabled={projectionLoading}
                              onClick={() => void deleteProjectionCard(selectedProjectionCard)}
                              type="button"
                            >
                              <X size={16} />
                              删除
                            </button>
                          ) : null}
                        </div>

                        <div className="soul-projection-form-grid">
                            <label>
                              <small>投影名</small>
                              <input
                                value={editor.projection_name}
                                onChange={(event) => updateProjectionEditor(selectedProjectionCard, "projection_name", event.target.value)}
                                placeholder={`${editor.soul_name} / 投影`}
                            />
                          </label>
                        </div>

                        <div className="soul-managed-sections">
                          {nodes.map((node) => (
                            <article className="soul-managed-section soul-managed-section--editing" key={node.id}>
                              <div className="soul-managed-section__head">
                                <div>
                                  <input
                                    className="soul-managed-section__title-input"
                                    value={node.title}
                                    onChange={(event) => updateProjectionCardNode(selectedProjectionCard, node.id, "title", event.target.value)}
                                  />
                                </div>
                                <div className="soul-section-inline-actions">
                                  <button className="action-button" onClick={() => insertProjectionCardNodeAfter(selectedProjectionCard, node.id)} type="button">
                                    <Plus size={16} />
                                  </button>
                                  <button className="action-button" disabled={nodes.length <= 1} onClick={() => deleteProjectionCardNode(selectedProjectionCard, node.id)} type="button">
                                    <X size={16} />
                                  </button>
                                </div>
                              </div>
                              <textarea
                                value={node.content}
                                onChange={(event) => updateProjectionCardNode(selectedProjectionCard, node.id, "content", event.target.value)}
                                rows={6}
                              />
                            </article>
                          ))}
                        </div>

                      </div>
                    );
                })() : (
                    <div className="soul-reader">
                      <pre>当前没有可编辑的投影，请先返回投影目录选择或新建。</pre>
                    </div>
                )
              ) : (
                <div className="soul-reader">
                  <pre>先在左侧选择一个灵魂，再进入它的投影列表。</pre>
                </div>
              )}
            </div>
          ) : mode === "contract" && !selectedSeed ? (
            <div className="soul-empty-world soul-empty-world--editor">
              <strong>当前世界观没有绑定灵魂</strong>
              <p>这个入口适合后续放无背景工作 prompt。现在可以切到“共同契约”维护用户自定义契约，或选择洪荒时代进入灵魂卡片。</p>
            </div>
          ) : selectedFile ? (
            <>
              {isEditing ? (
                <div className="soul-managed-sections">
                  {(mode === "core" && selectedManagedSection ? [selectedManagedSection] : managedSections).map((section) => (
                    <article className="soul-managed-section soul-managed-section--editing" key={section.id}>
                      <div className="soul-managed-section__head">
                        <div>
                          {mode === "core" ? (
                            <input
                              className="soul-managed-section__title-input"
                              value={section.title}
                              onChange={(event) => setDraft(renameManagedSection(draft, mode, section.id, event.target.value))}
                            />
                          ) : (
                            <strong>{section.title}</strong>
                          )}
                        </div>
                      </div>
                      <textarea
                        value={section.content}
                        onChange={(event) => setDraft(updateManagedSection(draft, mode, section.id, event.target.value))}
                        spellCheck={false}
                      />
                    </article>
                  ))}
                </div>
              ) : (
                <div className="soul-managed-sections">
                  {(mode === "core" && selectedManagedSection ? [selectedManagedSection] : managedSections).map((section) => (
                    <article className="soul-managed-section" key={section.id}>
                      <div>
                        <strong>{section.title}</strong>
                      </div>
                      <pre>{section.content || "暂无内容。"}</pre>
                    </article>
                  ))}
                </div>
              )}
              <div className="soul-editor-actions">
                {isEditing ? (
                  <>
                    <button className="action-button action-button--primary" disabled={saving === selectedFile.path || !hasUnsavedChanges} onClick={() => void saveSelectedFile()} type="button">
                      <Save size={16} />
                      {saving === selectedFile.path ? "保存中" : hasUnsavedChanges ? "保存修改" : "已保存"}
                    </button>
                    <button className="action-button" disabled={!hasUnsavedChanges || saving === selectedFile.path} onClick={resetDraft} type="button">
                      <RotateCcw size={16} />
                      恢复上次保存
                    </button>
                    <button className="action-button action-button--muted" disabled={saving === selectedFile.path} onClick={cancelEditing} type="button">
                      <X size={16} />
                      退出编辑
                    </button>
                  </>
                ) : (
                  <>
                    <button className="action-button action-button--primary" onClick={() => setIsEditing(true)} type="button">
                      <PencilLine size={16} />
                      编辑设定
                    </button>
                    {mode === "core" && selectedManagedSection ? (
                      <button className="action-button action-button--primary" onClick={() => deleteCoreRuleCard(selectedManagedSection.id)} type="button">
                        <X size={16} />
                        删除契约卡
                      </button>
                    ) : null}
                  </>
                )}
              </div>
            </>
          ) : (
            <p className="workspace-copy">暂无可编辑内容。</p>
          )}
        </section>
      </div>
    </div>
  );
}
