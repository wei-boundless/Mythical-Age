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

  const activeMode = SOUL_MODES.find((item) => item.id === mode) ?? SOUL_MODES[0];
  const stageTitle = isHonghuangWorld
    ? selectedLore?.title ?? "古老灵魂的降临"
    : "无背景工作场";
  const stageSummary = isHonghuangWorld
    ? selectedLore?.summary ?? "选择一个灵魂后，这里会显示它的背景设定与协作气质。"
    : selectedWorld?.content || selectedWorld?.summary || "这个世界观不注入额外故事背景，适合纯工作 prompt 和低角色感任务。";
  const selectedSeedLabel = selectedSeed?.name ?? catalog?.active_soul_name ?? "未选择灵魂";
  const selectedLayerLabel = mode === "core" ? "共同契约" : mode === "projection" ? "工作投影" : "灵魂本体";

  function renderSoulRoster() {
    if (!seedsForWorld.length) {
      return (
        <div className="soul-empty-state">
          <strong>这个世界观暂未绑定灵魂</strong>
          <p>这里会保留纯工作 prompt 与共同契约。以后在资源库绑定灵魂后，会从这个入口进入对应灵魂。</p>
        </div>
      );
    }

    return (
      <div className="soul-lineage" aria-label="灵魂列表">
        {seedsForWorld.map((seed) => {
          const isCustomSoul = seed.source === "user";
          const isEnabled = seed.enabled !== false;
          const projectionCount = (projectionCatalog?.cards ?? []).filter((card) => card.soul_id === seed.key || card.soul_name === seed.name).length;
          const active = selectedSeed?.key === seed.key || seed.active;
          return (
            <div className={`soul-lineage__row ${active ? "soul-lineage__row--active" : ""}`} key={seed.key}>
              <button
                className="soul-lineage__main"
                onClick={() => mode === "projection" ? enterProjectionSoul(seed) : chooseSoul(seed)}
                type="button"
              >
                <span>{seed.active ? "正在使用" : isCustomSoul ? "自定义灵魂" : "可选灵魂"}</span>
                <strong>{displayFileLabel(seed)}</strong>
                <em>
                  {mode === "projection"
                    ? projectionCount ? `${projectionCount} 个投影` : "暂无投影"
                    : seed.active
                      ? "当前对话灵魂"
                      : isCustomSoul
                        ? (isEnabled ? "已召唤，可激活" : "已停用")
                        : "可切换为当前灵魂"}
                </em>
              </button>
              {mode === "contract" ? (
                <div className="soul-lineage__tools">
                  <button
                    className={seed.active ? "soul-action soul-action--ghost soul-action--on" : "soul-action soul-action--ghost"}
                    disabled={saving === seed.path || seed.active || activeSoulKey === seed.key || !isEnabled}
                    onClick={() => void activateSeed(seed)}
                    type="button"
                  >
                    {seed.active || activeSoulKey === seed.key ? "已激活" : "激活"}
                  </button>
                  {isCustomSoul ? (
                    <>
                      <button
                        className="soul-action soul-action--ghost"
                        disabled={saving === seed.path}
                        onClick={() => void toggleCustomSoul(seed, !isEnabled)}
                        type="button"
                      >
                        {isEnabled ? "停用" : "启用"}
                      </button>
                      <button
                        className="soul-action soul-action--ghost"
                        disabled={saving === seed.path || seed.active}
                        onClick={() => void expelCustomSoul(seed)}
                        type="button"
                      >
                        驱逐
                      </button>
                    </>
                  ) : null}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    );
  }

  function renderCoreIndex() {
    if (!coreFile) {
      return (
        <div className="soul-empty-state">
          <strong>没有找到共同契约</strong>
          <p>共同契约文件缺失，暂时无法编辑用户自定义 prompt。</p>
        </div>
      );
    }

    return (
      <>
        <div className="soul-contract-create">
          <input
            value={newRuleTitle}
            onChange={(event) => setNewRuleTitle(event.target.value)}
            placeholder="新契约标题"
          />
          <button className="soul-action soul-action--primary" onClick={addCoreRuleCard} type="button">
            <Plus size={16} />
            添加
          </button>
        </div>
        <div className="soul-contract-index" aria-label="共同契约目录">
          {managedSections.map((section) => (
            <button
              className={`soul-contract-item ${section.id === selectedManagedSection?.id ? "soul-contract-item--active" : ""}`}
              key={section.id}
              onClick={() => setSelectedManagedSectionId(section.id)}
              type="button"
            >
              <span>契约</span>
              <strong>{section.title}</strong>
            </button>
          ))}
        </div>
      </>
    );
  }

  function renderManagedSurface() {
    if (mode === "contract" && !selectedSeed) {
      return (
        <div className="soul-empty-state soul-empty-state--large">
          <strong>当前世界观没有绑定灵魂</strong>
          <p>这个入口适合纯工作模式。你可以切到共同契约维护用户定制 prompt，或选择洪荒时代进入灵魂名单。</p>
        </div>
      );
    }

    if (!selectedFile) {
      return (
        <div className="soul-empty-state soul-empty-state--large">
          <strong>暂无可编辑内容</strong>
          <p>先从世界观和灵魂列表中选择一个目标。</p>
        </div>
      );
    }

    const sectionsToRender = mode === "core" && selectedManagedSection ? [selectedManagedSection] : managedSections;

    return (
      <>
        <div className="soul-writing-stack">
          {sectionsToRender.map((section) => (
            <article className={`soul-writing-block ${isEditing ? "soul-writing-block--editing" : ""}`} key={section.id}>
              <div className="soul-writing-block__head">
                {isEditing && mode === "core" ? (
                  <input
                    className="soul-title-input"
                    value={section.title}
                    onChange={(event) => setDraft(renameManagedSection(draft, mode, section.id, event.target.value))}
                  />
                ) : (
                  <strong>{section.title}</strong>
                )}
              </div>
              {isEditing ? (
                <textarea
                  value={section.content}
                  onChange={(event) => setDraft(updateManagedSection(draft, mode, section.id, event.target.value))}
                  spellCheck={false}
                />
              ) : (
                <pre>{section.content || "暂无内容。"}</pre>
              )}
            </article>
          ))}
        </div>
        <div className="soul-editor-actions">
          {isEditing ? (
            <>
              <button className="soul-action soul-action--primary" disabled={saving === selectedFile.path || !hasUnsavedChanges} onClick={() => void saveSelectedFile()} type="button">
                <Save size={16} />
                {saving === selectedFile.path ? "保存中" : hasUnsavedChanges ? "保存修改" : "已保存"}
              </button>
              <button className="soul-action soul-action--ghost" disabled={!hasUnsavedChanges || saving === selectedFile.path} onClick={resetDraft} type="button">
                <RotateCcw size={16} />
                恢复
              </button>
              <button className="soul-action soul-action--ghost" disabled={saving === selectedFile.path} onClick={cancelEditing} type="button">
                <X size={16} />
                退出
              </button>
            </>
          ) : (
            <>
              <button className="soul-action soul-action--primary" onClick={() => setIsEditing(true)} type="button">
                <PencilLine size={16} />
                编辑设定
              </button>
              {mode === "core" && selectedManagedSection ? (
                <button className="soul-action soul-action--danger" onClick={() => deleteCoreRuleCard(selectedManagedSection.id)} type="button">
                  <X size={16} />
                  删除契约
                </button>
              ) : null}
            </>
          )}
        </div>
      </>
    );
  }

  function renderProjectionSurface() {
    if (!selectedSeed) {
      return (
        <div className="soul-empty-state soul-empty-state--large">
          <strong>先选择一个灵魂</strong>
          <p>投影是灵魂在工作时使用的 prompt。选择灵魂后，可以进入它的投影目录。</p>
        </div>
      );
    }

    if (projectionPanelPage === "catalog") {
      return (
        <div className="soul-projection-library">
          <div className="soul-projection-library__head">
            <div>
              <span>Projection Library</span>
              <strong>{selectedSeed.name} 的工作投影</strong>
            </div>
            <button className="soul-action soul-action--primary" onClick={() => newProjectionDraft(selectedSeed)} type="button">
              <Plus size={16} />
              新建投影
            </button>
          </div>
          <div className="soul-projection-stream">
            {selectedSeedProjectionCards.map((card) => (
              <button
                className={`soul-projection-entry ${card.projection_id === selectedProjectionId && !projectionDraft ? "soul-projection-entry--active" : ""}`}
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
            {!selectedSeedProjectionCards.length ? (
              <button className="soul-projection-entry soul-projection-entry--create" onClick={() => newProjectionDraft(selectedSeed)} type="button">
                <span>空目录</span>
                <strong>创建第一个投影</strong>
                <em>为这个灵魂建立实际工作 prompt。</em>
              </button>
            ) : null}
          </div>
        </div>
      );
    }

    if (projectionDraft && projectionDraft.soul_id === selectedSeed.key) {
      return (
        <div className="soul-projection-editor">
          <div className="soul-projection-editor__head">
            <div>
              <span>新专属投影</span>
              <strong>{projectionDraft.projection_name || "未命名投影"}</strong>
            </div>
            <small>草稿</small>
          </div>
          <div className="soul-projection-editor__toolbar">
            <button className="soul-action soul-action--ghost" onClick={() => setProjectionPanelPage("catalog")} type="button">
              <ChevronLeft size={16} />
              返回目录
            </button>
            <button className="soul-action soul-action--primary" disabled={projectionLoading} onClick={() => void saveProjectionDraft()} type="button">
              {projectionLoading ? <Loader2 className="spin" size={16} /> : <Save size={16} />}
              保存
            </button>
            <button className="soul-action soul-action--ghost" onClick={() => {
              setProjectionDraft(null);
              setProjectionDraftNodes([]);
              setProjectionPanelPage("catalog");
            }} type="button">
              <X size={16} />
              放弃
            </button>
          </div>
          <label className="soul-projection-form">
            <span>投影名</span>
            <input
              value={projectionDraft.projection_name}
              onChange={(event) => updateProjectionDraft("projection_name", event.target.value)}
              placeholder={`${projectionDraft.soul_name} / 专属投影`}
            />
          </label>
          <div className="soul-node-stack">
            {projectionDraftNodes.map((node) => (
              <article className="soul-node-editor" key={node.id}>
                <div className="soul-node-editor__head">
                  <input
                    value={node.title}
                    onChange={(event) => updateProjectionDraftNode(node.id, "title", event.target.value)}
                  />
                  <div className="soul-inline-tools">
                    <button className="soul-icon-button" onClick={() => insertProjectionDraftNodeAfter(node.id)} type="button" aria-label="添加段落">
                      <Plus size={16} />
                    </button>
                    <button className="soul-icon-button" disabled={projectionDraftNodes.length <= 1} onClick={() => deleteProjectionDraftNode(node.id)} type="button" aria-label="删除段落">
                      <X size={16} />
                    </button>
                  </div>
                </div>
                <textarea
                  value={node.content}
                  onChange={(event) => updateProjectionDraftNode(node.id, "content", event.target.value)}
                  placeholder={node.type === "identity_anchor" ? "写清楚这个 Agent 的身份设定、职责边界、必须遵守的规则和禁止事项。" : ""}
                  rows={6}
                />
              </article>
            ))}
          </div>
        </div>
      );
    }

    if (selectedProjectionCard && selectedSeedProjectionCards.some((card) => card.projection_id === selectedProjectionCard.projection_id)) {
      const editor = projectionEditorForCard(selectedProjectionCard);
      const nodes = projectionNodesForCard(selectedProjectionCard);
      return (
        <div className="soul-projection-editor" key={selectedProjectionCard.projection_id}>
          <div className="soul-projection-editor__head">
            <div>
              <span>{projectionBadgeLabel(selectedProjectionCard)}</span>
              <strong>{selectedProjectionCard.title}</strong>
            </div>
            <small>{selectedProjectionCard.is_primary ? "原始投影" : "已保存"}</small>
          </div>
          <div className="soul-projection-editor__toolbar">
            <button className="soul-action soul-action--ghost" onClick={() => setProjectionPanelPage("catalog")} type="button">
              <ChevronLeft size={16} />
              返回目录
            </button>
            <button className="soul-action soul-action--primary" disabled={projectionLoading} onClick={() => void saveExistingProjectionCard(selectedProjectionCard)} type="button">
              {projectionLoading ? <Loader2 className="spin" size={16} /> : <Save size={16} />}
              保存
            </button>
            <button className="soul-action soul-action--ghost" onClick={() => resetProjectionEditor(selectedProjectionCard)} type="button">
              <RotateCcw size={16} />
              恢复
            </button>
            {!selectedProjectionCard.is_primary ? (
              <button className="soul-action soul-action--danger" disabled={projectionLoading} onClick={() => void deleteProjectionCard(selectedProjectionCard)} type="button">
                <X size={16} />
                删除
              </button>
            ) : null}
          </div>
          <label className="soul-projection-form">
            <span>投影名</span>
            <input
              value={editor.projection_name}
              onChange={(event) => updateProjectionEditor(selectedProjectionCard, "projection_name", event.target.value)}
              placeholder={`${editor.soul_name} / 投影`}
            />
          </label>
          <div className="soul-node-stack">
            {nodes.map((node) => (
              <article className="soul-node-editor" key={node.id}>
                <div className="soul-node-editor__head">
                  <input
                    value={node.title}
                    onChange={(event) => updateProjectionCardNode(selectedProjectionCard, node.id, "title", event.target.value)}
                  />
                  <div className="soul-inline-tools">
                    <button className="soul-icon-button" onClick={() => insertProjectionCardNodeAfter(selectedProjectionCard, node.id)} type="button" aria-label="添加段落">
                      <Plus size={16} />
                    </button>
                    <button className="soul-icon-button" disabled={nodes.length <= 1} onClick={() => deleteProjectionCardNode(selectedProjectionCard, node.id)} type="button" aria-label="删除段落">
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
    }

    return (
      <div className="soul-empty-state soul-empty-state--large">
        <strong>当前没有可编辑的投影</strong>
        <p>返回投影目录选择一个投影，或新建一个工作投影。</p>
      </div>
    );
  }

  return (
    <div className={`workspace-view soul-studio ${isHonghuangWorld ? "soul-studio--honghuang" : "soul-studio--plain"}`}>
      <div className="soul-studio__ambient" aria-hidden="true" />
      <div className="soul-studio__alerts">
        {loading ? (
          <div className="soul-notice">
            <Loader2 size={16} className="spin" />
            正在加载灵魂系统...
          </div>
        ) : null}
        {error ? <div className="soul-notice soul-notice--danger">{error}</div> : null}
        {notice ? <div className="soul-notice">{notice}</div> : null}
      </div>

      <section className="soul-studio__worldfield" aria-label="世界观选择">
        <div className="soul-worldfield__intro">
          <span>Soul Studio</span>
          <h2>世界观先打开，灵魂再降临</h2>
          <p>第一层决定故事背景，第二层决定灵魂本体，第三层才进入实际工作 prompt。纯工作场不会注入额外身份。</p>
        </div>
        <div className="soul-worldfield__path">
          {worlds.map((world, index) => {
            const active = selectedWorld?.world_id === world.world_id;
            const worldCards = resourceCatalog?.cards.filter((card) => card.world_id === world.world_id) ?? [];
            const honghuang = String(world.metadata?.theme ?? "") === "honghuang";
            return (
              <button
                aria-pressed={active}
                className={`soul-world-node ${active ? "soul-world-node--active" : ""} ${honghuang ? "soul-world-node--honghuang" : ""}`}
                key={world.world_id}
                onClick={() => selectWorld(world.world_id)}
                type="button"
              >
                <span>{String(index + 1).padStart(2, "0")}</span>
                <strong>{world.title}</strong>
                <em>{world.summary || "无额外世界观注入"}</em>
                <small>{worldCards.length ? `${worldCards.length} 个灵魂` : "纯工作场"}</small>
              </button>
            );
          })}
          {!worlds.length ? (
            <div className="soul-empty-state">
              <strong>世界观库为空</strong>
              <p>灵魂系统需要先加载世界观目录。</p>
            </div>
          ) : null}
        </div>
      </section>

      <section className="soul-studio__stage" aria-label="当前世界与灵魂舞台">
        <div className="soul-stage__script">
          <span>{selectedWorld?.title ?? "未选择世界观"}</span>
          <h2>{isHonghuangWorld ? selectedSeedLabel : "纯工作模式"}</h2>
          <strong>{stageTitle}</strong>
          <p>{stageSummary}</p>
          {isHonghuangWorld ? (
            <blockquote>{SHARED_SOUL_LORE}</blockquote>
          ) : (
            <div className="soul-stage__plain-note">
              <Layers3 size={18} />
              不加载故事背景与灵魂身份，只保留工作 prompt、共同契约和必要上下文。
            </div>
          )}
          <div className="soul-stage__signals" aria-label="当前层级">
            <span><small>世界层</small><b>{selectedWorld?.title ?? "未选择"}</b></span>
            <span><small>灵魂层</small><b>{selectedSeed?.name ?? "无绑定"}</b></span>
            <span><small>工作层</small><b>{selectedLayerLabel}</b></span>
          </div>
        </div>
        <div className="soul-stage__visual">
          <div className="soul-stage__aurora" aria-hidden="true" />
          <div className="soul-stage__portrait">
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
              <div className="soul-stage__empty-visual">
                <Layers3 size={32} />
                <strong>{selectedWorld?.title ?? "世界观"}</strong>
                <span>无背景，无灵魂，专注工作。</span>
              </div>
            )}
          </div>
          <div className="soul-stage__caption">
            <span>{selectedSeed ? visibilityLabel(selectedSeed) : "工作场"}</span>
            <strong>{selectedSeed?.name ?? "无绑定灵魂"}</strong>
            {isHonghuangWorld ? (
              <>
                <button
                  className="soul-action soul-action--primary"
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
              </>
            ) : null}
          </div>
        </div>
      </section>

      <section className="soul-studio__workbench" aria-label="灵魂工作层">
        <div className="soul-workbench__header">
          <div>
            <span>Work Projection</span>
            <h3>{activeMode.label}</h3>
            <p>{activeMode.description}</p>
          </div>
          <nav className="soul-mode-ribbon" aria-label="灵魂系统模式">
            {SOUL_MODES.map((item) => (
              <button
                className={`soul-mode-choice ${mode === item.id ? "soul-mode-choice--active" : ""}`}
                key={item.id}
                onClick={() => handleModeSwitch(item.id)}
                type="button"
              >
                <span>{item.label}</span>
              </button>
            ))}
          </nav>
        </div>

        <div className="soul-workbench__body">
          <aside className="soul-workbench__rail" aria-label="当前层级目录">
            <div className="soul-rail-head">
              <Sparkles size={18} />
              <div>
                <span>{mode === "core" ? "Shared Contract" : mode === "projection" ? "Soul Projection" : "Soul Body"}</span>
                <strong>{mode === "core" ? "共同契约目录" : mode === "projection" ? "选择投影所属灵魂" : "选择灵魂本体"}</strong>
              </div>
            </div>
            {mode === "core" ? renderCoreIndex() : renderSoulRoster()}
          </aside>

          <main className="soul-workbench__editor" aria-label="当前编辑区">
            <div className="soul-editor-head">
              <div className="soul-editor-head__icon">
                {mode === "projection" ? <Boxes size={19} /> : <FilePenLine size={19} />}
              </div>
              <div>
                <span>{mode === "projection" ? "投影管理" : isEditing ? "正在编辑" : "设定阅读"}</span>
                <strong>
                  {mode === "projection"
                    ? `${selectedSeed?.name ?? "当前灵魂"}的工作投影`
                    : displayFileLabel(selectedFile)}
                </strong>
              </div>
            </div>
            {mode === "projection" ? renderProjectionSurface() : renderManagedSurface()}
          </main>
        </div>
      </section>
    </div>
  );
}