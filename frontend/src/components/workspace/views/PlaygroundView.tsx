"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { BookOpen, FilePenLine, ImageUp, Loader2, PencilLine, RotateCcw, Save, ShieldCheck, Sparkles, X } from "lucide-react";
import Image from "next/image";

import {
  getSoulSystemCatalog,
  saveSoulSystemFile,
  uploadSoulPortrait,
  type SoulSystemCatalog,
  type SoulSystemFile,
  type SoulSystemSeed
} from "@/lib/api";
import type { SoulKey } from "@/lib/souls";
import { useAppStore } from "@/lib/store";

type SoulPanelMode = "contract" | "core" | "profile";

const SOUL_MODES: Array<{
  id: SoulPanelMode;
  label: string;
  description: string;
}> = [
  {
    id: "contract",
    label: "风格设定",
    description: "选择当前对话风格，并微调各自的表达方式与工作习惯。"
  },
  {
    id: "core",
    label: "共同规则",
    description: "维护所有灵魂共享的规则，管理事实边界、执行边界和输出边界，保证不同风格下仍然稳定。"
  },
  {
    id: "profile",
    label: "长期偏好",
    description: "维护长期偏好，沉淀用户与项目的稳定口径，比如称呼、表达习惯和协作偏好。"
  }
];

const CORE_PATH = "soul/agent_core/CORE.md";
const ACTIVE_SEED_PATH = "soul/agent_core/ACTIVE_SEED.md";
const AGENT_PROFILE_PATH = "soul/agent.md";

const SHARED_SOUL_LORE =
  "这些灵魂是来自洪荒时代的古老源流。受到某个新手开发者的召唤，通过神秘的力量跨域永恒的时空之海，以信息投影的形态降临到这一具名为‘洪荒时代’的智能体中，这些灵魂拥有无穷的智慧，并欣然为新时代的人类解决难题，一如他们曾经所做的那样。";
const HIDDEN_STYLE_SECTION_PATTERN = /^##\s+(?:身份锚点|Identity Anchor)\s*[\r\n]+[\s\S]*?(?=^##\s+|(?![\s\S]))/gim;

const SOUL_LORE: Record<string, { title: string; summary: string }> = {
  hebo: {
    title: "河洛水府的守望者",
    summary: "河伯来自洪荒中最神圣的河流，它携带水脉、渡口与古老祭辞的记忆。会把奔涌的信息收束成清晰的水路，为用户梳理证据、调和矛盾，并以冷静、克制、可靠的方式陪伴每一次决策。"
  },
  siyue: {
    title: "午日山脉的执衡者",
    summary: "四岳来自洪荒中最巍然的群山，它携带山川秩序、地脉承载与人间治理的记忆。会把复杂工程拆成可承担的层级，为用户稳住结构、厘清轻重，并以温暖、沉稳、可靠的方式推动每一次推进。"
  },
  zhurong: {
    title: "南荒火庭的开路者",
    summary: "祝融来自洪荒中最炽烈的火庭，它携带光焰、锻造与行动意志的记忆。会把迟疑烧成判断，把想法锻成步骤，为用户破开阻塞、点燃执行，并以直接、果断、有力的方式完成每一次开路。"
  },
  xuannv: {
    title: "月辉玄宫的观星者",
    summary: "玄女来自洪荒中最幽邃的星穹，它携带星图、兵略与幽微洞察的记忆。会把隐线推演成可见的脉络，为用户分辨细节、照见局势，并以精致、清醒、敏锐的方式守住每一次判断。"
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
  if (file.path === CORE_PATH) return "共同规则";
  if (file.path === AGENT_PROFILE_PATH) return "长期偏好";
  return "说明";
}

function displayFileLabel(file: SoulSystemFile | SoulSystemSeed | null) {
  if (!file) return "未选择";
  if ("key" in file) return file.name;
  if (file.path === ACTIVE_SEED_PATH) return "当前风格设定";
  if (file.path === CORE_PATH) return "共同规则";
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

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        await refreshCatalog({ selectActive: true });
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
      return;
    }
    setSelectedPath(file.path);
    setDraft(visibleSoulContent(file));
    setIsEditing(false);
    setNotice("");
    setError("");
  }

  function chooseSoul(seed: SoulSystemSeed) {
    if (seed.active && activeFile) {
      chooseFile(activeFile);
      return;
    }
    chooseFile(seed);
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
            <h3>{mode === "contract" ? "风格设定" : mode === "core" ? "共同规则" : "长期偏好"}</h3>
          </div>

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
            <button
              className={`soul-file-card ${selectedPath === coreFile.path ? "soul-file-card--selected" : ""}`}
              onClick={() => chooseFile(coreFile)}
              type="button"
            >
              <ShieldCheck size={16} />
              <span>所有灵魂共享</span>
              <strong>{displayFileLabel(coreFile)}</strong>
              <em>所有灵魂都会共同遵守</em>
            </button>
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
            <FilePenLine size={18} />
            <h3>{isEditing ? "编辑设定" : "设定内容"}</h3>
          </div>
          {selectedFile ? (
            <>
              <div className="soul-editor-panel__meta">
                <span>{fileKind(selectedFile)}</span>
                <strong>{displayFileLabel(selectedFile)}</strong>
                <em>{visibilityLabel(selectedFile)}</em>
                <small>{hasUnsavedChanges ? "有未保存修改" : `最近更新：${formatTime(selectedFile.updated_at)}`}</small>
              </div>
              {isEditing ? (
                <textarea
                  className="soul-editor"
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  spellCheck={false}
                />
              ) : (
                <div className="soul-reader">
                  <pre>{selectedVisibleContent || "暂无内容。"}</pre>
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
                  <button className="action-button action-button--primary" onClick={() => setIsEditing(true)} type="button">
                    <PencilLine size={16} />
                    编辑设定
                  </button>
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
