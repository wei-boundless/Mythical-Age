"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { BookOpen, Boxes, ChevronLeft, FilePenLine, ImageUp, Loader2, PencilLine, Plus, RotateCcw, Save, ShieldCheck, Sparkles, X } from "lucide-react";
import Image from "next/image";

import {
  createSoulProjectionCard,
  deleteSoulProjectionCard,
  getSoulProjectionCards,
  getSoulSystemCatalog,
  saveSoulSystemFile,
  selectSoulProjectionCard,
  uploadSoulPortrait,
  type SoulProjectionCard,
  type SoulProjectionCatalog,
  type SoulSystemCatalog,
  type SoulSystemFile,
  type SoulSystemSeed
} from "@/lib/api";
import type { SoulKey } from "@/lib/souls";
import { useAppStore } from "@/lib/store";

type SoulPanelMode = "contract" | "projection" | "core" | "profile";
type ProjectionRailPage = "souls" | "cards";
type ProjectionDetailPage = "projection" | "soul";

type ProjectionDraft = {
  sourceProjectionId?: string;
  isNew: boolean;
  soul_id: string;
  soul_name: string;
  projection_name: string;
  role_type: string;
  task_mode: string;
  agent_profile_id: string;
  task_contract_summary: string;
  memory_policy_summary: string;
  output_contract_summary: string;
  style_content: string;
};

type ProjectionDraftTextField =
  | "projection_name"
  | "role_type"
  | "task_mode"
  | "agent_profile_id"
  | "task_contract_summary"
  | "memory_policy_summary"
  | "output_contract_summary"
  | "style_content";

const SOUL_MODES: Array<{
  id: SoulPanelMode;
  label: string;
  description: string;
}> = [
  {
    id: "contract",
    label: "灵魂设定",
    description: "切换并维护灵魂本体设定。"
  },
  {
    id: "projection",
    label: "任务投影",
    description: "按灵魂管理任务投影，并分别维护投影契约与投影设定。"
  },
  {
    id: "core",
    label: "共同契约",
    description: "维护所有灵魂共享的基础契约。"
  },
  {
    id: "profile",
    label: "长期偏好",
    description: "维护长期生效的协作偏好。"
  }
];

const CORE_PATH = "soul/agent_core/CORE.md";
const ACTIVE_SEED_PATH = "soul/agent_core/ACTIVE_SEED.md";
const AGENT_PROFILE_PATH = "soul/agent.md";

const SHARED_SOUL_LORE =
  "这些灵魂是来自洪荒时代的古老源流。受到某个新手开发者的召唤，通过禁忌的力量跨域时空之海，以智能体意志的形态降临到这一具名为‘洪荒时代’的智能体中，这些灵魂拥有无穷的智慧，并欣然为新时代的人类解决难题，一如他们曾经所做的那样。";
const HIDDEN_STYLE_SECTION_PATTERN = /^##\s+(?:身份锚点|Identity Anchor)\s*[\r\n]+[\s\S]*?(?=^##\s+|(?![\s\S]))/gim;
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

function formatTime(value: number | string | null) {
  if (!value) return "暂无记录";
  const date = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未知";
  return date.toLocaleString("zh-CN", { hour12: false });
}

function fileKind(file: SoulSystemFile | SoulSystemSeed) {
  if ("key" in file) return file.active ? "当前灵魂" : "可选灵魂";
  if (file.path === ACTIVE_SEED_PATH) return "当前灵魂";
  if (file.path === CORE_PATH) return "共同契约";
  if (file.path === AGENT_PROFILE_PATH) return "长期偏好";
  return "说明";
}

function displayFileLabel(file: SoulSystemFile | SoulSystemSeed | null) {
  if (!file) return "未选择";
  if ("key" in file) return file.name;
  if (file.path === ACTIVE_SEED_PATH) return "当前灵魂设定";
  if (file.path === CORE_PATH) return "共同契约";
  if (file.path === AGENT_PROFILE_PATH) return "长期偏好";
  return file.label.replace(/\.md$/i, "");
}

function visibilityLabel(file: SoulSystemFile | SoulSystemSeed) {
  if ("key" in file) return file.active ? "当前正在使用" : "尚未启用";
  if (file.path === CORE_PATH) return "所有灵魂共享";
  if (file.path === AGENT_PROFILE_PATH) return "长期保持生效";
  return file.model_visible ? "下一轮对话会使用" : "仅用于说明";
}

function isSoulSeed(file: SoulSystemFile | SoulSystemSeed | null): file is SoulSystemSeed {
  return Boolean(file && "key" in file);
}

function shouldHideStyleAnchors(file: SoulSystemFile | SoulSystemSeed | null) {
  return Boolean(file && ("key" in file || file.path === ACTIVE_SEED_PATH));
}

function stripHiddenStyleSections(content: string) {
  return content.replace(HIDDEN_STYLE_SECTION_PATTERN, "").trimStart();
}

function extractHiddenStyleSections(content: string) {
  return Array.from(content.matchAll(HIDDEN_STYLE_SECTION_PATTERN), (match) => match[0].trim()).filter(Boolean);
}

function visibleSoulContent(file: SoulSystemFile | SoulSystemSeed | null) {
  if (!file) return "";
  return shouldHideStyleAnchors(file) ? stripHiddenStyleSections(file.content) : file.content;
}

function mergeHiddenStyleSections(originalContent: string, visibleContent: string) {
  const hiddenSections = extractHiddenStyleSections(originalContent);
  const cleanVisible = stripHiddenStyleSections(visibleContent).trim();
  if (!hiddenSections.length) {
    return `${cleanVisible}\n`;
  }
  const lines = cleanVisible.split(/\r?\n/);
  if (lines[0]?.startsWith("# ")) {
    const [title, ...rest] = lines;
    return `${title}\n\n${hiddenSections.join("\n\n")}\n\n${rest.join("\n").trimStart()}`.trimEnd() + "\n";
  }
  return `${hiddenSections.join("\n\n")}\n\n${cleanVisible}`.trimEnd() + "\n";
}

type ManagedSection = {
  id: string;
  title: string;
  content: string;
};

function managedSectionLabel(mode: SoulPanelMode) {
  if (mode === "contract") return "灵魂模块";
  if (mode === "core") return "契约模块";
  if (mode === "profile") return "偏好模块";
  return "管理模块";
}

function emptySectionTitle(mode: SoulPanelMode) {
  if (mode === "contract") return "灵魂设定";
  if (mode === "core") return "共同契约";
  if (mode === "profile") return "长期偏好";
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

export function PlaygroundView() {
  const { activeSoulKey, switchSoul } = useAppStore();
  const [catalog, setCatalog] = useState<SoulSystemCatalog | null>(null);
  const [mode, setMode] = useState<SoulPanelMode>("contract");
  const [selectedPath, setSelectedPath] = useState(ACTIVE_SEED_PATH);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState("");
  const [isEditing, setIsEditing] = useState(false);
  const [uploadingPortrait, setUploadingPortrait] = useState("");
  const [portraitVersion, setPortraitVersion] = useState(Date.now());
  const [projectionCatalog, setProjectionCatalog] = useState<SoulProjectionCatalog | null>(null);
  const [projectionLoading, setProjectionLoading] = useState(false);
  const [projectionDraft, setProjectionDraft] = useState<ProjectionDraft | null>(null);
  const [projectionEditorMap, setProjectionEditorMap] = useState<Record<string, ProjectionDraft>>({});
  const [selectedProjectionId, setSelectedProjectionId] = useState("");
  const [projectionRailPage, setProjectionRailPage] = useState<ProjectionRailPage>("souls");
  const [projectionDetailPage, setProjectionDetailPage] = useState<ProjectionDetailPage>("projection");
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
  const selectedFile = allFiles.find((file) => file.path === selectedPath) ?? allFiles[0] ?? null;
  const coreFile = catalog?.static_files.find((file) => file.path === CORE_PATH) ?? null;
  const profileFile = catalog?.static_files.find((file) => file.path === AGENT_PROFILE_PATH) ?? null;
  const activeFile = catalog?.static_files.find((file) => file.path === ACTIVE_SEED_PATH) ?? null;
  const selectedSeed = isSoulSeed(selectedFile)
    ? selectedFile
    : catalog?.seeds.find((seed) => seed.active || seed.key === activeSoulKey) ?? catalog?.seeds[0] ?? null;
  const selectedVisibleContent = visibleSoulContent(selectedFile);
  const hasUnsavedChanges = Boolean(selectedFile && draft !== selectedVisibleContent);
  const portraitSrc = selectedSeed
    ? `${selectedSeed.portrait_path || `/souls/${selectedSeed.key}.png`}?v=${selectedSeed.portrait_updated_at ?? portraitVersion}`
    : "";
  const selectedLore = selectedSeed ? SOUL_LORE[selectedSeed.key] : null;
  const managedSource = isEditing ? draft : selectedVisibleContent;
  const managedSections = parseManagedSections(managedSource, mode);
  const selectedManagedSection = managedSections.find((section) => section.id === selectedManagedSectionId) ?? managedSections[0] ?? null;
  const projectionCardsForSelectedSoul = (projectionCatalog?.cards ?? []).filter((card) => {
    if (!selectedSeed) return true;
    return card.soul_id === selectedSeed.key || card.soul_name === selectedSeed.name;
  }).sort((left, right) => {
    if (Boolean(left.is_primary) !== Boolean(right.is_primary)) {
      return left.is_primary ? -1 : 1;
    }
    return (right.updated_at ?? 0) - (left.updated_at ?? 0);
  });
  const selectedProjectionCard = projectionCardsForSelectedSoul.find((card) => card.projection_id === selectedProjectionId) ?? null;

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

  function inheritedProjectionStyle(seed: SoulSystemSeed) {
    return visibleSoulContent(seed);
  }

  function projectionStyleSections(styleContent: string) {
    return parseManagedSections(styleContent, "contract");
  }

  function buildProjectionDraftForSeed(seed: SoulSystemSeed): ProjectionDraft {
    const profile = profileForSeed(seed);
    const roleType = profile?.preferred_role_types?.[0] ?? "dialogue";
    const taskMode = profile?.preferred_task_modes?.[0] ?? "general_qa";
    const soulName = profile?.display_name ?? seed.name;
    return {
      isNew: true,
      soul_id: seed.key,
      soul_name: soulName,
      projection_name: buildProjectionName(seed, roleType),
      role_type: roleType,
      task_mode: taskMode,
      agent_profile_id: "general_agent",
      task_contract_summary: "当前任务：根据用户目标生成一个可在任务中选用的任务投影。",
      memory_policy_summary: "预览模式不授予记忆写回权。",
      output_contract_summary: "预览当前灵魂如何收束 prompt sections。",
      style_content: inheritedProjectionStyle(seed)
    };
  }

  function buildProjectionDraftFromCard(card: SoulProjectionCard, fallbackStyleContent = ""): ProjectionDraft {
    return {
      sourceProjectionId: card.projection_id,
      isNew: false,
      soul_id: card.soul_id,
      soul_name: card.soul_name,
      projection_name: card.title,
      role_type: card.role_type,
      task_mode: card.task_mode,
      agent_profile_id: card.agent_profile_id,
      task_contract_summary: card.task_contract_summary || "当前投影没有绑定具体任务契约。",
      memory_policy_summary: card.memory_policy_summary || "预览模式不授予记忆写回权。",
      output_contract_summary: card.output_contract_summary || "预览当前灵魂如何收束 prompt sections。",
      style_content: card.style_content ?? fallbackStyleContent
    };
  }

  function projectionEditorForCard(card: SoulProjectionCard) {
    const seed = catalog?.seeds.find((item) => item.key === card.soul_id) ?? null;
    return projectionEditorMap[card.projection_id] ?? buildProjectionDraftFromCard(card, seed ? inheritedProjectionStyle(seed) : "");
  }

  function enterProjectionSoul(seed: SoulSystemSeed) {
    if (!chooseFile(seed)) return;
    setSelectedProjectionId("");
    setProjectionDraft((current) => (current && current.soul_id === seed.key ? current : null));
    setProjectionRailPage("cards");
    setProjectionDetailPage("projection");
  }

  function newProjectionDraft(seed: SoulSystemSeed) {
    if (!chooseFile(seed)) return;
    setSelectedProjectionId("");
    setProjectionDraft(buildProjectionDraftForSeed(seed));
    setProjectionRailPage("cards");
    setProjectionDetailPage("projection");
    setNotice("");
    setError("");
  }

  function returnToProjectionSouls() {
    setProjectionRailPage("souls");
    setProjectionDraft(null);
    setSelectedProjectionId("");
    setProjectionDetailPage("projection");
  }

  function jumpToMode(nextMode: SoulPanelMode, file: SoulSystemFile | null) {
    setMode(nextMode);
    if (file) chooseFile(file);
  }

  function handleModeSwitch(nextMode: SoulPanelMode) {
    if (nextMode === "contract") {
      jumpToMode(nextMode, activeFile);
      return;
    }
    if (nextMode === "projection") {
      setMode(nextMode);
      setProjectionRailPage("souls");
      return;
    }
    if (nextMode === "core") {
      jumpToMode(nextMode, coreFile);
      return;
    }
    if (nextMode === "profile") {
      jumpToMode(nextMode, profileFile);
      return;
    }
  }

  async function saveSelectedFile() {
    if (!selectedFile) return;
    setSaving(selectedFile.path);
    setNotice("");
    setError("");
    try {
      const contentToSave = shouldHideStyleAnchors(selectedFile)
        ? mergeHiddenStyleSections(selectedFile.content, draft)
        : draft;
      const payload = await saveSoulSystemFile(selectedFile.path, contentToSave, `保存「${displayFileLabel(selectedFile)}」`);
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

  function updateProjectionEditor(card: SoulProjectionCard, field: ProjectionDraftTextField, value: string) {
    setProjectionEditorMap((current) => ({
      ...current,
      [card.projection_id]: {
        ...(current[card.projection_id] ?? buildProjectionDraftFromCard(card)),
        [field]: value
      }
    }));
  }

  function resetProjectionEditor(card: SoulProjectionCard) {
    setProjectionEditorMap((current) => {
      const next = { ...current };
      delete next[card.projection_id];
      return next;
    });
  }

  async function persistProjectionCard(draftToSave: ProjectionDraft) {
    const payload = await createSoulProjectionCard({
      projection_id: draftToSave.sourceProjectionId,
      soul_id: draftToSave.soul_id,
      projection_name: draftToSave.projection_name.trim() || `${draftToSave.soul_name} / ${draftToSave.role_type || "dialogue"}`,
      role_type: draftToSave.role_type.trim() || "dialogue",
      task_mode: draftToSave.task_mode.trim() || "general_qa",
      agent_profile_id: draftToSave.agent_profile_id.trim() || "general_agent",
      task_contract_summary: draftToSave.task_contract_summary,
      memory_policy_summary: draftToSave.memory_policy_summary,
      output_contract_summary: draftToSave.output_contract_summary,
      style_content: draftToSave.style_content,
      skill_views: [
        {
          skill_id: "soul_projection_preview",
          title: "任务投影",
          capability_summary: "这个任务投影记录当前任务允许看到的 skill 摘要。",
          current_task_reason: "用于后续任务选用这个任务投影。"
        }
      ],
      tool_views: [
        {
          tool_id: "tool_visibility_demo",
          title: "工具可见性示例",
          capability_summary: "记录这个任务投影关联的工具可见摘要，但不会授予调用权。",
          authorized: false,
          risk_summary: "预览模式只展示边界，不执行工具。"
        }
      ],
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
      const { nextPayload, resolvedCard } = await persistProjectionCard(projectionDraft);
      setProjectionCatalog(nextPayload);
      setProjectionDraft(null);
      if (resolvedCard) {
        setSelectedProjectionId(resolvedCard.projection_id);
        setProjectionEditorMap((current) => ({
          ...current,
          [resolvedCard.projection_id]: buildProjectionDraftFromCard(resolvedCard)
        }));
      }
      setNotice(`已保存任务投影「${resolvedCard?.title ?? projectionDraft.projection_name}」`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存任务投影失败");
    } finally {
      setProjectionLoading(false);
    }
  }

  async function saveExistingProjectionCard(card: SoulProjectionCard) {
    const draftToSave = projectionEditorForCard(card);
    setProjectionLoading(true);
    setError("");
    try {
      const { nextPayload, resolvedCard } = await persistProjectionCard(draftToSave);
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
      setNotice(`已保存任务投影「${resolvedCard?.title ?? draftToSave.projection_name}」`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存任务投影失败");
    } finally {
      setProjectionLoading(false);
    }
  }

  async function selectProjectionCard(card: SoulProjectionCard) {
    setProjectionLoading(true);
    setError("");
    try {
      const payload = await selectSoulProjectionCard(card.projection_id);
      setProjectionCatalog(payload);
      setSelectedProjectionId(card.projection_id);
      setNotice(`已选用任务投影「${card.title}」`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "选用任务投影失败");
    } finally {
      setProjectionLoading(false);
    }
  }

  async function deleteProjectionCard(card: SoulProjectionCard) {
    if (!window.confirm(`确认删除任务投影「${card.title}」吗？`)) return;
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
      setNotice(`已删除任务投影「${card.title}」`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "删除任务投影失败");
    } finally {
      setProjectionLoading(false);
    }
  }

  return (
    <div className="workspace-view soul-system-console">
      {loading ? (
        <div className="workspace-alert">
          <Loader2 size={16} className="spin" />
          正在加载灵魂设置...
        </div>
      ) : null}
      {error ? <div className="workspace-alert workspace-alert--danger">{error}</div> : null}
      {notice ? <div className="workspace-alert">{notice}</div> : null}

      <section className="soul-origin-banner">
        <span>洪荒灵魂系统</span>
        <p>{SHARED_SOUL_LORE}</p>
      </section>

      <section className="soul-system-hero">
        <div className="soul-lore-panel">
          <strong>{selectedLore?.title ?? "古老灵魂的降临"}</strong>
          <p>{selectedLore?.summary ?? "选择一个灵魂后，这里会显示它的背景设定与协作气质。"}</p>
        </div>
        <div className="soul-portrait-manager">
          <div className="soul-portrait-manager__stage">
            {portraitSrc ? (
              <Image
                alt={`${selectedSeed?.name ?? "灵魂"}立绘`}
                height={1448}
                priority
                src={portraitSrc}
                unoptimized
                width={1086}
              />
            ) : null}
          </div>
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
            <h3>{mode === "contract" ? "灵魂设定" : mode === "projection" ? "任务投影" : mode === "core" ? "共同契约" : "长期偏好"}</h3>
          </div>

          {mode === "projection" ? (
            <>
              {projectionRailPage === "souls" ? (
                <>
                  <div className="soul-projection-group">
                    <span>灵魂</span>
                    <div className="soul-seed-grid soul-seed-grid--compact">
                      {catalog?.seeds.map((seed) => {
                        const count = (projectionCatalog?.cards ?? []).filter((card) => card.soul_id === seed.key || card.soul_name === seed.name).length;
                        return (
                          <article
                            className={`soul-seed-card ${selectedSeed?.key === seed.key ? "soul-seed-card--active" : ""}`}
                            key={seed.key}
                          >
                            <button className="soul-seed-card__main" onClick={() => enterProjectionSoul(seed)} type="button">
                              <span>{seed.active ? "正在使用" : "可选灵魂"}</span>
                              <strong>{displayFileLabel(seed)}</strong>
                              <em>{count ? `${count} 个任务投影` : "暂无任务投影"}</em>
                            </button>
                          </article>
                        );
                      })}
                    </div>
                  </div>

                  <div className="soul-projection-group">
                    <span>说明</span>
                    <div className="soul-empty-panel">先选灵魂，再新建或编辑投影。</div>
                  </div>
                </>
              ) : selectedSeed ? (
                <>
                  <div className="soul-projection-rail-head">
                    <button className="action-button" onClick={returnToProjectionSouls} type="button">
                      <ChevronLeft size={16} />
                      返回灵魂
                    </button>
                    <div>
                      <span>{selectedSeed.name}</span>
                      <strong>任务投影页</strong>
                    </div>
                  </div>

                  <div className="soul-projection-card-list">
                    {projectionCardsForSelectedSoul.length ? projectionCardsForSelectedSoul.map((card) => (
                      <button
                        className={card.projection_id === selectedProjectionCard?.projection_id ? "soul-projection-card soul-projection-card--selected" : "soul-projection-card"}
                        key={card.projection_id}
                        onClick={() => {
                          setProjectionDraft(null);
                          setSelectedProjectionId(card.projection_id);
                          setProjectionDetailPage("projection");
                        }}
                        type="button"
                      >
                        <span>
                          {card.is_primary
                            ? "原始投影"
                            : card.projection_id === projectionCatalog?.selected_projection_id
                              ? "当前选用"
                              : card.soul_name}
                        </span>
                        <strong>{card.title}</strong>
                        <em>{card.role_type} / {card.task_mode}</em>
                      </button>
                    )) : null}

                    <button
                      className={projectionDraft && projectionDraft.soul_id === selectedSeed.key ? "soul-projection-card soul-projection-card--selected soul-projection-card--create" : "soul-projection-card soul-projection-card--create"}
                      onClick={() => newProjectionDraft(selectedSeed)}
                      type="button"
                    >
                      <span>新建任务投影</span>
                      <strong><Plus size={18} /> 新建</strong>
                      <em>右侧直接编辑</em>
                    </button>
                  </div>
                </>
              ) : null}
            </>
          ) : null}

          {mode === "contract" ? (
            <div className="soul-seed-grid">
              {catalog?.seeds.map((seed) => (
                <article
                  className={`soul-seed-card ${seed.active ? "soul-seed-card--active" : ""}`}
                  key={seed.key}
                >
                  <button onClick={() => chooseSoul(seed)} type="button">
                    <span>{seed.active ? "正在使用" : "可选"}</span>
                    <strong>{displayFileLabel(seed)}</strong>
                    <em>{seed.active ? "当前对话灵魂" : "可切换为当前灵魂"}</em>
                  </button>
                  <button
                    className={seed.active ? "agent-switch agent-switch--on" : "agent-switch"}
                    disabled={saving === seed.path || seed.active || activeSoulKey === seed.key}
                    onClick={() => void activateSeed(seed)}
                    type="button"
                  >
                    {seed.active || activeSoulKey === seed.key ? "已激活" : "激活"}
                  </button>
                </article>
              ))}
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
                      <span>{managedSectionLabel(mode)}</span>
                      <strong>{section.title}</strong>
                    </button>
                  </div>
                ))}
              </div>
            </>
          ) : null}

          {mode === "profile" && profileFile ? (
            <button
              className={`soul-file-card ${selectedPath === profileFile.path ? "soul-file-card--selected" : ""}`}
              onClick={() => chooseFile(profileFile)}
              type="button"
            >
              <BookOpen size={16} />
              <span>长期偏好</span>
              <strong>{displayFileLabel(profileFile)}</strong>
              <em>用于稳定项目口径和用户偏好</em>
            </button>
          ) : null}
        </section>

        <section className="workspace-section soul-editor-panel">
          <div className="workspace-section__head">
            {mode === "projection" ? <Boxes size={18} /> : <FilePenLine size={18} />}
            <h3>
              {mode === "projection"
                ? projectionDetailPage === "projection"
                  ? `${selectedSeed?.name ?? "当前灵魂"}的投影管理`
                  : `${selectedSeed?.name ?? "当前灵魂"}的灵魂设定`
                : isEditing ? "编辑设定" : "设定内容"}
            </h3>
          </div>
          {mode === "projection" ? (
            <div className="soul-projection-panel">
              {selectedSeed ? (
                <div className="soul-projection-editor-list">
                  <div className="soul-submodule-switcher">
                    <button
                      className={projectionDetailPage === "projection" ? "active" : ""}
                      onClick={() => setProjectionDetailPage("projection")}
                      type="button"
                    >
                      投影管理
                    </button>
                    <button
                      className={projectionDetailPage === "soul" ? "active" : ""}
                      onClick={() => setProjectionDetailPage("soul")}
                      type="button"
                    >
                      灵魂设定
                    </button>
                  </div>

                  {projectionDetailPage === "projection" && projectionDraft && projectionDraft.soul_id === selectedSeed.key ? (
                    <div className="soul-projection-editor-card soul-projection-editor-card--draft">
                      <div className="soul-projection-editor-card__head">
                        <div>
                          <span>新投影</span>
                          <strong>{projectionDraft.projection_name || "未命名任务投影"}</strong>
                          <em>{projectionDraft.role_type || "dialogue"} / {projectionDraft.task_mode || "general_qa"}</em>
                        </div>
                        <small>草稿</small>
                      </div>

                      <div className="soul-projection-form-grid">
                        <label>
                          <small>任务投影名</small>
                          <input
                            value={projectionDraft.projection_name}
                            onChange={(event) => updateProjectionDraft("projection_name", event.target.value)}
                            placeholder={`${projectionDraft.soul_name} / ${projectionDraft.role_type || "dialogue"}`}
                          />
                        </label>
                        <label>
                          <small>角色类型</small>
                          <input
                            value={projectionDraft.role_type}
                            onChange={(event) => updateProjectionDraft("role_type", event.target.value)}
                            placeholder="dialogue"
                          />
                        </label>
                        <label>
                          <small>任务模式</small>
                          <input
                            value={projectionDraft.task_mode}
                            onChange={(event) => updateProjectionDraft("task_mode", event.target.value)}
                            placeholder="general_qa"
                          />
                        </label>
                        <label>
                          <small>智能体配置</small>
                          <input
                            value={projectionDraft.agent_profile_id}
                            onChange={(event) => updateProjectionDraft("agent_profile_id", event.target.value)}
                            placeholder="general_agent"
                          />
                        </label>
                      </div>

                      <label className="soul-projection-editor-card__contract">
                        <small>绑定任务契约</small>
                        <textarea
                          value={projectionDraft.task_contract_summary}
                          onChange={(event) => updateProjectionDraft("task_contract_summary", event.target.value)}
                          rows={7}
                        />
                      </label>

                      <div className="soul-projection-actions">
                        <button className="action-button action-button--primary" disabled={projectionLoading} onClick={() => void saveProjectionDraft()} type="button">
                          {projectionLoading ? <Loader2 className="spin" size={16} /> : <Save size={16} />}
                          保存投影
                        </button>
                        <button className="action-button" onClick={() => setProjectionDraft(null)} type="button">
                          <X size={16} />
                          放弃草稿
                        </button>
                      </div>
                    </div>
                  ) : projectionDetailPage === "projection" && selectedProjectionCard ? (() => {
                    const editor = projectionEditorForCard(selectedProjectionCard);
                    return (
                      <div className="soul-projection-editor-card" key={selectedProjectionCard.projection_id}>
                        <div className="soul-projection-editor-card__head">
                          <div>
                            <span>{selectedProjectionCard.is_primary ? "原始投影" : selectedProjectionCard.soul_name}</span>
                            <strong>{selectedProjectionCard.title}</strong>
                            <em>{selectedProjectionCard.role_type} / {selectedProjectionCard.task_mode}</em>
                          </div>
                          <small>{selectedProjectionCard.projection_id === projectionCatalog?.selected_projection_id ? "当前选用" : "未选用"}</small>
                        </div>

                        <div className="soul-projection-form-grid">
                            <label>
                              <small>任务投影名</small>
                              <input
                                disabled={selectedProjectionCard.is_primary}
                                value={editor.projection_name}
                                onChange={(event) => updateProjectionEditor(selectedProjectionCard, "projection_name", event.target.value)}
                                placeholder={`${editor.soul_name} / ${editor.role_type || "dialogue"}`}
                            />
                          </label>
                            <label>
                              <small>角色类型</small>
                              <input
                                disabled={selectedProjectionCard.is_primary}
                                value={editor.role_type}
                                onChange={(event) => updateProjectionEditor(selectedProjectionCard, "role_type", event.target.value)}
                                placeholder="dialogue"
                            />
                          </label>
                            <label>
                              <small>任务模式</small>
                              <input
                                disabled={selectedProjectionCard.is_primary}
                                value={editor.task_mode}
                                onChange={(event) => updateProjectionEditor(selectedProjectionCard, "task_mode", event.target.value)}
                                placeholder="general_qa"
                            />
                          </label>
                            <label>
                              <small>智能体配置</small>
                              <input
                                disabled={selectedProjectionCard.is_primary}
                                value={editor.agent_profile_id}
                                onChange={(event) => updateProjectionEditor(selectedProjectionCard, "agent_profile_id", event.target.value)}
                                placeholder="general_agent"
                            />
                          </label>
                        </div>

                          <label className="soul-projection-editor-card__contract">
                            <small>绑定任务契约</small>
                            <textarea
                              disabled={selectedProjectionCard.is_primary}
                              value={editor.task_contract_summary}
                              onChange={(event) => updateProjectionEditor(selectedProjectionCard, "task_contract_summary", event.target.value)}
                              rows={7}
                          />
                        </label>

                        <div className="soul-projection-static-card">
                          <article>
                            <span>管理信息</span>
                            <strong>{selectedProjectionCard.projection_id}</strong>
                            <p>
                              {selectedProjectionCard.is_primary ? "这是系统自动保底的通用原始投影，不要求人工任务契约，并且固定作为基础模板。 " : ""}
                              创建：{formatTime(selectedProjectionCard.created_at)}；更新：{formatTime(selectedProjectionCard.updated_at)}。skills: {selectedProjectionCard.skill_views.length}；tools: {selectedProjectionCard.tool_views.length}。
                            </p>
                          </article>
                        </div>

                        <div className="soul-projection-actions">
                          {!selectedProjectionCard.is_primary ? (
                            <button className="action-button action-button--primary" disabled={projectionLoading} onClick={() => void saveExistingProjectionCard(selectedProjectionCard)} type="button">
                              {projectionLoading ? <Loader2 className="spin" size={16} /> : <Save size={16} />}
                              保存投影
                            </button>
                          ) : null}
                          <button
                            className="action-button action-button--primary"
                            disabled={projectionLoading || selectedProjectionCard.projection_id === projectionCatalog?.selected_projection_id}
                            onClick={() => void selectProjectionCard(selectedProjectionCard)}
                            type="button"
                          >
                            <ShieldCheck size={16} />
                            {selectedProjectionCard.projection_id === projectionCatalog?.selected_projection_id ? "已选用" : "选用此任务投影"}
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
                      </div>
                    );
                  })() : projectionDetailPage === "soul" ? (
                    projectionDraft && projectionDraft.soul_id === selectedSeed.key ? (
                      <div className="soul-projection-editor-card soul-projection-editor-card--draft">
                        <div className="soul-projection-editor-card__head">
                          <div>
                            <span>投影灵魂设定</span>
                            <strong>{projectionDraft.projection_name || "未命名任务投影"}</strong>
                            <em>初始内容来自当前灵魂。</em>
                          </div>
                          <small>草稿</small>
                        </div>

                        <div className="soul-managed-sections">
                          {projectionStyleSections(projectionDraft.style_content).map((section) => (
                            <article className="soul-managed-section soul-managed-section--editing" key={section.id}>
                              <div className="soul-managed-section__head">
                                <div>
                                  <span>{managedSectionLabel("contract")}</span>
                                  <strong>{section.title}</strong>
                                </div>
                              </div>
                              <textarea
                                value={section.content}
                                onChange={(event) => updateProjectionDraft("style_content", updateManagedSection(projectionDraft.style_content, "contract", section.id, event.target.value))}
                                spellCheck={false}
                              />
                            </article>
                          ))}
                        </div>

                        <div className="soul-projection-actions">
                          <button className="action-button action-button--primary" disabled={projectionLoading} onClick={() => void saveProjectionDraft()} type="button">
                            {projectionLoading ? <Loader2 className="spin" size={16} /> : <Save size={16} />}
                            保存投影
                          </button>
                          <button
                            className="action-button"
                            onClick={() => updateProjectionDraft("style_content", inheritedProjectionStyle(selectedSeed))}
                            type="button"
                          >
                            <RotateCcw size={16} />
                            恢复继承设定
                          </button>
                          <button className="action-button" onClick={() => setProjectionDraft(null)} type="button">
                            <X size={16} />
                            放弃草稿
                          </button>
                        </div>
                      </div>
                    ) : selectedProjectionCard ? (() => {
                      const editor = projectionEditorForCard(selectedProjectionCard);
                      return (
                        <div className="soul-projection-editor-card" key={`${selectedProjectionCard.projection_id}-style`}>
                        <div className="soul-projection-editor-card__head">
                          <div>
                            <span>{selectedProjectionCard.is_primary ? "原始投影设定" : "投影灵魂设定"}</span>
                            <strong>{selectedProjectionCard.title}</strong>
                            <em>{selectedProjectionCard.is_primary ? "基础投影设定。" : "投影独立设定。"}</em>
                          </div>
                          <small>{selectedProjectionCard.projection_id === projectionCatalog?.selected_projection_id ? "当前选用" : "未选用"}</small>
                        </div>

                          <div className="soul-managed-sections">
                            {projectionStyleSections(editor.style_content).map((section) => (
                              <article className="soul-managed-section soul-managed-section--editing" key={section.id}>
                                <div className="soul-managed-section__head">
                                  <div>
                                    <span>{managedSectionLabel("contract")}</span>
                                    <strong>{section.title}</strong>
                                  </div>
                                </div>
                                <textarea
                                  value={section.content}
                                  onChange={(event) => updateProjectionEditor(selectedProjectionCard, "style_content", updateManagedSection(editor.style_content, "contract", section.id, event.target.value))}
                                  spellCheck={false}
                                />
                              </article>
                            ))}
                          </div>

                          <div className="soul-projection-actions">
                            <button className="action-button action-button--primary" disabled={projectionLoading} onClick={() => void saveExistingProjectionCard(selectedProjectionCard)} type="button">
                              {projectionLoading ? <Loader2 className="spin" size={16} /> : <Save size={16} />}
                              保存设定
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
                        </div>
                      );
                    })() : (
                      <div className="soul-reader">
                        <pre>{projectionRailPage === "souls" ? "先在左侧选择一个灵魂。" : "先从左侧投影列表里选一张卡，或者点击左侧加号新建卡。"}</pre>
                      </div>
                    )
                  ) : (
                    <div className="soul-reader">
                      <pre>{projectionRailPage === "souls" ? "先在左侧选择一个灵魂。" : "先从左侧投影列表里选一张卡，或者点击左侧加号新建卡。"}</pre>
                    </div>
                  )}
                </div>
              ) : (
                <div className="soul-reader">
                  <pre>先在左侧选择一个灵魂，再进入它的任务投影列表。</pre>
                </div>
              )}
            </div>
          ) : selectedFile ? (
            <>
              {isEditing ? (
                <div className="soul-managed-sections">
                  {(mode === "core" && selectedManagedSection ? [selectedManagedSection] : managedSections).map((section) => (
                    <article className="soul-managed-section soul-managed-section--editing" key={section.id}>
                      <div className="soul-managed-section__head">
                        <div>
                          <span>{managedSectionLabel(mode)}</span>
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
                        <span>{managedSectionLabel(mode)}</span>
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
