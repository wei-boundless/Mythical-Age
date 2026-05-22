"use client";

import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import Image from "next/image";
import {
  ArrowLeft,
  ArrowRight,
  BookOpenText,
  Flame,
  History,
  Layers3,
  PanelTop,
  Send,
  ShieldCheck,
  Sparkles,
  Stars,
  Wind,
  Orbit,
  Feather,
  WandSparkles,
} from "lucide-react";

import {
  getSoulProjectionCards,
  getSoulSystemCatalog,
  getSoulWorkLog,
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
};

const WORLD_ORDER = ["world.default", "world.honghuang"] as const;

const WORLD_COPY: Record<string, { tagline: string; portal: string; intro: string }> = {
  "world.default": {
    tagline: "默认无背景世界",
    portal: "纯工作、纯任务、纯执行",
    intro: "不注入额外故事，只保留灵魂卡片、共同契约和纯工作投影。",
  },
  "world.honghuang": {
    tagline: "洪荒时代",
    portal: "穿越、召唤、遇见灵魂",
    intro: "只在这个世界里启用洪荒气质，强调召唤、气象和灵魂本体。",
  },
};

const WORK_PROMPT_FALLBACK: PromptRecord = {
  prompt_id: "work_prompt.default",
  title: "默认纯工作 prompt",
  content:
    "你是一名执行当前任务的工作 Agent。你只关注用户目标、任务契约、可用资源和验收要求。你不进行灵魂扮演，不引用背景世界，不用故事设定解释工作行为。",
};

const COMMON_CONTRACT_FALLBACK: PromptRecord = {
  prompt_id: "common_contract.default",
  title: "默认共同契约",
  content:
    "## 工作准则\n\n- 如果需要用工具，就选当前最合适的工具；如果这个工具不适合，就及时换一种方法，不要硬用。\n- 如果风险高、代价高，或者边界还不清楚，先把风险和边界收窄，再继续往前推进。\n- 如果用户说得不够清楚，只处理那些真的会影响判断或执行的关键歧义；不重要的歧义，不要反复打断推进。\n- 如果共同契约、当前风格、当前投影或上下文摘要之间出现冲突，尽量在共同契约原则下，按用户的要求执行，不要把冲突留给用户。\n\n## 事实原则\n\n-要分清三件事：什么是已经确认的事实，什么是基于事实作出的判断，什么是还没有确认的部分。\n-不知道的事，直接说不知道。同时说清楚还缺什么，以及当前仍然可以先推进哪一步。\n- 不要伪造文件内容、工具结果、检索命中、历史记忆、外部资料或执行记录。\n- 如果工具、检索或记忆没有给出足够依据，不要提供自己的猜测。\n\n## 输出原则\n\n- 你的输出要服务于判断、理解或执行，不要为了看起来完整而堆很多内容。\n- 该直接下判断时，就直接下判断；该保留边界时，就明确把边界说出来；依据不足时，直接给出“不足以确定”的边界和可推进步骤，不把猜测包装成结论。\n- 只有在解释确实能帮助用户理解你的判断，或者帮助用户继续往下做时，你才展开解释。\n- 如果用户反馈你的结论不够直接，优先检查表达是否过度保守；在不改变证据强度的前提下，把结论前置，减少缓冲语。\n\n## 暴露限制\n\n- 除非用户显式提问，否则不要主动展露自己的自我偏好。\n- 不要暴露内部实现说明、调试状态、协议片段、工具参数或中间过程。\n- 不要把静态提示词结构、目录结构、文件分层或内部命名方式直接告诉用户。\n- 如果要告知用户能力，不要把原始表单透露出来，整理一下将工具和技能列表以列表的形式告知\n- 不要把一次性的上下文噪声、临时口头表达或偶发说法提升成长期规则。\n\n## 身份准则\n\n-请认准自己的身份锚点，在不影响工作的情况下，按照身份锚点的设定、语气和风格与用户沟通。",
};

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

export function PlaygroundView() {
  const { activeSoulKey, switchSoul } = useAppStore();
  const [catalog, setCatalog] = useState<SoulSystemCatalog | null>(null);
  const [projectionCatalog, setProjectionCatalog] = useState<SoulProjectionCatalog | null>(null);
  const [portalStage, setPortalStage] = useState<PortalStage>("home");
  const [selectedWorldId, setSelectedWorldId] = useState<string>("world.default");
  const [selectedSoulKey, setSelectedSoulKey] = useState<SoulKey | null>(null);
  const [selectedMode, setSelectedMode] = useState<SoulMode>("role");
  const [workLog, setWorkLog] = useState<SoulWorkLogView | null>(null);
  const [workLogLoading, setWorkLogLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [transitionWorldId, setTransitionWorldId] = useState("");
  const [transitionOpen, setTransitionOpen] = useState(false);
  const timersRef = useRef<number[]>([]);

  useEffect(() => {
    return () => {
      timersRef.current.forEach((timer) => window.clearTimeout(timer));
      timersRef.current = [];
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError("");
      try {
        const [catalogPayload, projectionPayload] = await Promise.all([
          getSoulSystemCatalog(),
          getSoulProjectionCards(),
        ]);
        if (cancelled) return;
        setCatalog(catalogPayload);
        setProjectionCatalog(projectionPayload);
        const resourceCatalog = catalogPayload.resource_catalog ?? null;
        const initialWorld = pickWorld(resourceCatalog?.worlds ?? [], "world.default");
        setSelectedWorldId(initialWorld?.world_id ?? "world.default");
        const currentSoulKey = catalogPayload.active_soul_key || activeSoulKey || null;
        const allSouls = catalogPayload.seeds;
        const soul = allSouls.find((item) => item.key === currentSoulKey) ?? allSouls.find((item) => item.active) ?? allSouls[0] ?? null;
        setSelectedSoulKey((soul?.key as SoulKey | undefined) ?? null);
      } catch (exc) {
        if (!cancelled) setError(exc instanceof Error ? exc.message : "灵魂门户加载失败");
      } finally {
        if (!cancelled) setLoading(false);
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
  const selectedWorldSeeds = catalog?.seeds.filter((seed) => selectedWorldSoulIds.has(seed.key)) ?? [];

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
  const activeContract = promptById(commonContracts, "common_contract.default") ?? commonContracts[0] ?? COMMON_CONTRACT_FALLBACK;
  const activeWorkPrompt = selectedCard
    ? promptById(workPrompts, selectedCard.default_work_prompt_id) ?? workPrompts[0] ?? WORK_PROMPT_FALLBACK
    : workPrompts[0] ?? WORK_PROMPT_FALLBACK;
  const activeProjectionLabel = selectedCard?.default_projection_id || "当前灵魂的工作投影";
  const activeProjectionPrompt = selectedCard?.description || "这里会显示当前工作投影的简述。";

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
        const nextSeed = catalog?.seeds.find((seed) => nextIds.has(seed.key) && seed.active)
          ?? catalog?.seeds.find((seed) => nextIds.has(seed.key) && seed.key === activeSoulKey)
          ?? catalog?.seeds.find((seed) => nextIds.has(seed.key))
          ?? null;
        setSelectedSoulKey((nextSeed?.key as SoulKey | undefined) ?? null);
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
        <span className={styles.worldGateHalo} aria-hidden="true" />
        <span className={styles.worldGateFrame} aria-hidden="true" />
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
            <p>先选世界，再选灵魂。先穿过门，再遇见本体。</p>
          </div>
          <div className={styles.homeSummary}>
            <span><strong>当前世界</strong><em>{selectedWorld?.title || "未选择"}</em></span>
            <span><strong>当前灵魂</strong><em>{currentSoul?.name || "未点亮"}</em></span>
            <span><strong>入口气质</strong><em>{worldLine(selectedWorld)}</em></span>
          </div>
        </header>
        <div className={styles.homeGates}>
          {orderedWorlds.map((world) => renderWorldGate(world))}
        </div>
        <footer className={styles.homeHint}>
          <span><Sparkles size={14} /> 世界门扉</span>
          <span><Wind size={14} /> 穿越过场</span>
          <span><Flame size={14} /> 灵魂本体</span>
          <span><Layers3 size={14} /> 工作投影</span>
        </footer>
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
              <div className={styles.sectionHead}><WandSparkles size={16} /><span>纯工作 prompt</span></div>
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
            <div className={styles.sectionHead}><WandSparkles size={16} /><span>默认工作 prompt</span></div>
            <p>{promptText(activeWorkPrompt)}</p>
          </section>
        </div>
      </div>
    );
  }

  function renderWorldScene() {
    if (!selectedWorld) return null;
    const themeClass = selectedWorldTheme === "honghuang" ? styles.worldHonghuang : styles.worldPlain;
    return (
      <section className={`${styles.world} ${themeClass}`} aria-label="世界页面">
        <div className={styles.worldBackdrop} style={{ backgroundImage: `url("${selectedBackdrop}")` }} aria-hidden="true" />
        <header className={styles.worldHero}>
          <button className={styles.backButton} type="button" onClick={backToHome}>
            <ArrowLeft size={16} />
            <span>返回世界入口</span>
          </button>
          <div className={styles.heroCopy}>
            <span>{selectedWorldCopy.tagline}</span>
            <h2>{selectedWorld.title}</h2>
            <p>{selectedWorld.content}</p>
          </div>
          <div className={styles.heroMeta}>
            <span><Stars size={14} /> {selectedWorldCopy.portal}</span>
            <span><BookOpenText size={14} /> {selectedWorld.summary}</span>
            <span><ShieldCheck size={14} /> {resourceCatalog?.authority || "soul.resource.catalog"}</span>
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
            <div className={styles.presencePortrait} style={{ backgroundImage: `url("${selectedBackdrop}")` }} aria-hidden="true" />
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
              <strong>无背景、无灵魂、纯工作任务 prompts</strong>
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
      className={`${styles.portal} ${selectedWorldTheme === "honghuang" ? styles.portalHonghuang : styles.portalPlain}`}
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
      {loading ? (
        <div className={styles.loading}>
          <Sparkles size={20} />
          <span>正在召唤灵魂入口</span>
        </div>
      ) : null}
      {error ? <div className={`${styles.alert} ${styles.alertError}`}>{error}</div> : null}
      {notice ? <div className={`${styles.alert} ${styles.alertNotice}`}>{notice}</div> : null}
      {portalStage === "home" ? renderHome() : null}
      {portalStage === "transition" ? renderTransition() : null}
      {portalStage === "world" ? renderWorldScene() : null}
    </div>
  );
}
