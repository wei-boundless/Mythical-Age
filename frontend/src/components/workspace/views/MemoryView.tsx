"use client";

import {
  Activity,
  Archive,
  BookOpenCheck,
  ClipboardList,
  Database,
  FileText,
  Gauge,
  GitBranch,
  Loader2,
  RefreshCw,
  Search,
  ShieldCheck,
  Trash2,
  type LucideIcon
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useConfirmDialog } from "@/components/layout/ConfirmDialogProvider";
import {
  activateDurableMemory,
  archiveDurableMemory,
  createDurableMemory,
  deleteDurableMemory,
  disableDurableMemory,
  getDurableMemoryNote,
  getMemoryOverview,
  getProjectInstructionManagement,
  mergeDurableMemories,
  saveProjectInstructionSource,
  type DurableMemoryNoteDetail,
  type MemoryHeader,
  type MemoryOverview,
  type ProjectInstructionManagement,
} from "@/lib/api";
import { useAppStore } from "@/lib/store";
import type { TokenStats } from "@/lib/store/types";
import { Button } from "@/ui/Button";

type DurableStatusFilter = "all" | "active" | "inactive" | "archived" | "deprecated";
type MemoryLayer = "library" | "governance" | "project-rules";

const FRONTMATTER_FIELD_PATTERN = /^(note_id|memory_type|memory_class|title|description|status|confidence|created_at|updated_at|retrieval_hints|eligible_for_injection|canonical_statement|summary|source_kind|source_ref|source_message_excerpt|merged_from|invalidation_reason|deprecated_by):/i;
const SEMANTIC_HEADING_PATTERN = /^#{1,3}\s*(正文|语义正文|memory|canonical|canonical statement|stable statement|长期记忆)\s*$/i;

const MEMORY_LAYER_DEFS: Array<{
  id: MemoryLayer;
  icon: LucideIcon;
  title: string;
  eyebrow: string;
  description: string;
}> = [
  {
    id: "library",
    icon: Database,
    title: "长期库",
    eyebrow: "durable",
    description: "环境与全局长期记忆的读取、筛选和单条检查。"
  },
  {
    id: "governance",
    icon: ShieldCheck,
    title: "治理",
    eyebrow: "manage",
    description: "整理候选、写入稳定记忆，并合并重复记录。"
  },
  {
    id: "project-rules",
    icon: FileText,
    title: "项目规则源",
    eyebrow: "prompt",
    description: "管理 AGENTS.md 稳定项目指令源，与长期记忆分离。"
  }
];

function compactText(value: string, limit = 220) {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (normalized.length <= limit) {
    return normalized;
  }
  return `${normalized.slice(0, limit)}...`;
}

function extractSemanticBodyFromPreview(raw: string) {
  const withoutFrontmatter = raw.replace(/^---[\s\S]*?---\s*/, "");
  const lines = withoutFrontmatter
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !FRONTMATTER_FIELD_PATTERN.test(line));

  const headingIndex = lines.findIndex((line) => SEMANTIC_HEADING_PATTERN.test(line));
  const semanticLines = headingIndex >= 0 ? lines.slice(headingIndex + 1) : lines;
  return compactText(semanticLines.join("\n").replace(/\n{3,}/g, "\n\n"), 900);
}

function semanticMemoryText(header?: MemoryHeader | null, detail?: DurableMemoryNoteDetail | null) {
  const semantic = [
    header?.canonical_statement,
    header?.summary,
    header?.description,
    detail?.header?.canonical_statement,
    detail?.header?.summary,
    detail?.header?.description
  ].find((value) => value?.trim());
  if (semantic) {
    return semantic.trim();
  }
  return detail?.content_preview ? extractSemanticBodyFromPreview(detail.content_preview) : "";
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    active: "已启用",
    inactive: "候选",
    archived: "已归档",
    deprecated: "已合并/废弃"
  };
  return labels[status] ?? status;
}

function statusTone(status: string) {
  if (status === "active") return "active";
  if (status === "inactive") return "candidate";
  if (status === "archived") return "archived";
  if (status === "deprecated") return "deprecated";
  return "neutral";
}

function formatTokenCount(value: unknown) {
  const number = Math.max(0, Math.round(Number(value || 0)));
  if (number >= 1_000_000) return `${(number / 1_000_000).toFixed(2)}M`;
  if (number >= 1_000) return `${(number / 1_000).toFixed(1)}K`;
  return String(number);
}

function percentFromRatio(value: unknown) {
  return Math.max(0, Math.min(100, Math.round(Number(value || 0) * 100)));
}

function currentContextTokenCount(tokenStats: TokenStats) {
  const rawCurrent = tokenStats.context_meter?.current_context_tokens;
  const current = Number(rawCurrent);
  if (rawCurrent !== undefined && rawCurrent !== null && Number.isFinite(current)) {
    return current;
  }
  return Number(tokenStats.total_tokens || 0);
}

function compactionThresholdTokenCount(tokenStats: TokenStats) {
  const rawThreshold = tokenStats.context_meter?.replacement_threshold_tokens;
  const threshold = Number(rawThreshold);
  if (rawThreshold !== undefined && rawThreshold !== null && Number.isFinite(threshold)) {
    return Math.max(0, threshold);
  }
  return 0;
}

function contextThresholdUsageRatio(tokenStats: TokenStats) {
  const thresholdTokens = compactionThresholdTokenCount(tokenStats);
  if (thresholdTokens <= 0) {
    return 0;
  }
  return currentContextTokenCount(tokenStats) / thresholdTokens;
}

function sessionContextMeterTitle(tokenStats: TokenStats | null, usagePercent: number | null) {
  if (!tokenStats) {
    return "";
  }
  const currentTokens = currentContextTokenCount(tokenStats);
  const thresholdTokens = compactionThresholdTokenCount(tokenStats);
  const contextWindowTokens = Number(tokenStats.context_meter?.context_window_tokens || 0);
  const remainingTokens = Math.max(0, thresholdTokens - currentTokens);
  return [
    `当前上下文 ${formatTokenCount(currentTokens)} tokens`,
    thresholdTokens > 0 ? `自动压缩阈值 ${formatTokenCount(thresholdTokens)} tokens` : "",
    thresholdTokens > 0 && usagePercent !== null ? `阈值占比 ${usagePercent}%` : "",
    contextWindowTokens > 0 ? `模型窗口 ${formatTokenCount(contextWindowTokens)} tokens` : "",
    thresholdTokens > 0 ? `距自动压缩还剩 ${formatTokenCount(remainingTokens)} tokens` : "",
  ].filter(Boolean).join("；");
}

function compactJson(value: Record<string, unknown> | null | undefined, limit = 1400) {
  if (!value || !Object.keys(value).length) return "";
  return compactText(JSON.stringify(value, null, 2), limit);
}

function layerMetric(
  layer: MemoryLayer,
  overview: MemoryOverview | null,
  projectInstructions: ProjectInstructionManagement | null,
) {
  if (layer === "project-rules") {
    if (!projectInstructions) return "未加载";
    const loaded = projectInstructions.sources.filter((source) => source.loaded).length;
    return `${loaded}/${projectInstructions.sources.length} 装载`;
  }
  if (layer === "library") {
    const durable = overview?.durable_memory;
    return durable ? `${durable.active}/${durable.total} 启用` : "未加载";
  }
  return overview?.durable_memory ? `${overview.durable_memory.injectable} 可注入` : "待治理";
}

export function MemoryView() {
  const confirm = useConfirmDialog();
  const { currentSessionId, loadInspectorFile, tokenStats } = useAppStore();
  const [activeLayer, setActiveLayer] = useState<MemoryLayer>("library");
  const [query, setQuery] = useState("");
  const [overview, setOverview] = useState<MemoryOverview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [governanceBusy, setGovernanceBusy] = useState("");
  const [governanceMessage, setGovernanceMessage] = useState("");
  const [projectInstructions, setProjectInstructions] = useState<ProjectInstructionManagement | null>(null);
  const [projectInstructionDraft, setProjectInstructionDraft] = useState("");
  const [projectInstructionBusy, setProjectInstructionBusy] = useState("");
  const [mergeFilenames, setMergeFilenames] = useState<string[]>([]);
  const [durableStatusFilter, setDurableStatusFilter] = useState<DurableStatusFilter>("all");
  const [selectedDurableNote, setSelectedDurableNote] = useState<DurableMemoryNoteDetail | null>(null);
  const [selectedDurableFilename, setSelectedDurableFilename] = useState("");
  const [durableNoteLoading, setDurableNoteLoading] = useState(false);
  const [newMemory, setNewMemory] = useState({
    title: "",
    canonical: "",
    summary: "",
    hints: "",
    memoryType: "project",
    memoryClass: "work",
    confidence: "medium"
  });
  const [mergeDraft, setMergeDraft] = useState({
    title: "",
    canonical: "",
    summary: "",
    reason: ""
  });

  const durable = overview?.durable_memory ?? null;
  const projectInstructionSource = projectInstructions?.sources[0] ?? null;
  const projectInstructionDirty = projectInstructionSource
    ? projectInstructionDraft !== projectInstructionSource.content
    : Boolean(projectInstructionDraft.trim());

  const durableStatusStats = useMemo(() => {
    const headers = overview?.durable_memory.headers ?? [];
    return {
      active: headers.filter((note) => note.status === "active").length,
      inactive: headers.filter((note) => note.status === "inactive").length,
      archived: headers.filter((note) => note.status === "archived").length,
      deprecated: headers.filter((note) => note.status === "deprecated").length
    };
  }, [overview?.durable_memory.headers]);

  const filteredHeaders = useMemo(() => {
    const headers = overview?.durable_memory.headers ?? [];
    const normalized = query.trim().toLowerCase();
    const statusFiltered = durableStatusFilter === "all"
      ? headers
      : headers.filter((note) => note.status === durableStatusFilter);
    if (!normalized) {
      return statusFiltered;
    }
    return statusFiltered.filter((note) =>
      [
        note.title,
        note.description,
        note.summary,
        note.canonical_statement,
        note.filename,
        note.memory_type,
        note.memory_class,
        note.retrieval_hints.join(" ")
      ].join(" ").toLowerCase().includes(normalized)
    );
  }, [durableStatusFilter, overview?.durable_memory.headers, query]);

  const selectedSemanticText = semanticMemoryText(selectedDurableNote?.header, selectedDurableNote);
  const usagePercent = tokenStats ? percentFromRatio(contextThresholdUsageRatio(tokenStats)) : null;
  const tokenTitle = sessionContextMeterTitle(tokenStats, usagePercent);
  const thresholdTokens = tokenStats ? compactionThresholdTokenCount(tokenStats) : 0;

  const loadOverview = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const payload = await getMemoryOverview();
      setOverview(payload);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "记忆系统读取失败");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadProjectInstructions = useCallback(async () => {
    setProjectInstructionBusy((current) => current || "读取项目规则源");
    setError("");
    try {
      const payload = await getProjectInstructionManagement();
      setProjectInstructions(payload);
      setProjectInstructionDraft(payload.sources[0]?.content ?? "");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "项目规则源读取失败");
    } finally {
      setProjectInstructionBusy("");
    }
  }, []);

  useEffect(() => {
    void loadOverview();
  }, [loadOverview]);

  useEffect(() => {
    void loadProjectInstructions();
  }, [loadProjectInstructions]);

  async function refreshAll() {
    await Promise.all([loadOverview(), loadProjectInstructions()]);
  }

  async function runGovernanceAction(label: string, action: () => Promise<unknown>, options?: { refreshSelected?: boolean }) {
    setGovernanceBusy(label);
    setGovernanceMessage("");
    setError("");
    try {
      await action();
      setGovernanceMessage(`${label} 已完成。`);
      await loadOverview();
      if (options?.refreshSelected !== false && selectedDurableFilename) {
        const payload = await getDurableMemoryNote(selectedDurableFilename);
        setSelectedDurableNote(payload);
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : `${label} 失败`);
    } finally {
      setGovernanceBusy("");
    }
  }

  async function inspectDurableNote(note: MemoryHeader) {
    setSelectedDurableFilename(note.filename);
    setDurableNoteLoading(true);
    setError("");
    try {
      const payload = await getDurableMemoryNote(note.filename);
      setSelectedDurableNote(payload);
    } catch (exc) {
      setSelectedDurableNote(null);
      setError(exc instanceof Error ? exc.message : "长期记忆读取失败");
    } finally {
      setDurableNoteLoading(false);
    }
  }

  async function createMemoryFromDraft() {
    const title = newMemory.title.trim();
    const canonical = newMemory.canonical.trim();
    if (!title || !canonical) {
      setError("写入长期记忆需要标题和稳定表述。");
      return;
    }
    await runGovernanceAction("写入长期记忆", async () => {
      await createDurableMemory({
        title,
        canonical_statement: canonical,
        summary: newMemory.summary.trim() || canonical,
        memory_type: newMemory.memoryType,
        memory_class: newMemory.memoryClass,
        confidence: newMemory.confidence,
        source_kind: "manual",
        source_message_excerpt: canonical,
        retrieval_hints: newMemory.hints.split(/[,\n，]/).map((item) => item.trim()).filter(Boolean)
      });
      setNewMemory({
        title: "",
        canonical: "",
        summary: "",
        hints: "",
        memoryType: "project",
        memoryClass: "work",
        confidence: "medium"
      });
    });
  }

  async function mergeSelectedMemories() {
    if (mergeFilenames.length < 2) {
      setError("合并长期记忆至少需要选择两条记录。");
      return;
    }
    if (!mergeDraft.title.trim() || !mergeDraft.canonical.trim()) {
      setError("合并需要填写新记忆标题和稳定表述。");
      return;
    }
    await runGovernanceAction("合并长期记忆", async () => {
      await mergeDurableMemories({
        filenames: mergeFilenames,
        title: mergeDraft.title.trim(),
        canonical_statement: mergeDraft.canonical.trim(),
        summary: mergeDraft.summary.trim() || mergeDraft.canonical.trim(),
        reason: mergeDraft.reason.trim() || "Manual merge from memory governance UI"
      });
      setMergeFilenames([]);
      setMergeDraft({ title: "", canonical: "", summary: "", reason: "" });
    });
  }

  async function deleteMemoryNote(filename: string) {
    const confirmed = await confirm({
      title: `删除长期记忆「${filename}」`,
      body: "文件会移入 durable_memory/trash，并从长期记忆列表中移除。",
      confirmLabel: "删除记忆",
    });
    if (!confirmed) {
      return;
    }
    await runGovernanceAction(
      "删除长期记忆",
      async () => {
        await deleteDurableMemory(filename, "Deleted from durable memory manager");
        setMergeFilenames((prev) => prev.filter((item) => item !== filename));
        if (selectedDurableFilename === filename) {
          setSelectedDurableFilename("");
          setSelectedDurableNote(null);
        }
      },
      { refreshSelected: selectedDurableFilename !== filename }
    );
  }

  function toggleMergeFilename(filename: string) {
    setMergeFilenames((prev) =>
      prev.includes(filename)
        ? prev.filter((item) => item !== filename)
        : [...prev, filename]
    );
  }

  function reviewCandidateMemories() {
    setDurableStatusFilter("inactive");
    setActiveLayer("library");
    setGovernanceMessage("已切到候选记忆，只显示待整理、待确认的长期记忆。");
  }

  function organizeSelectedMemory() {
    if (selectedDurableNote?.header) {
      const header = selectedDurableNote.header;
      setNewMemory({
        title: header.title || "",
        canonical: semanticMemoryText(header, selectedDurableNote),
        summary: header.summary || "",
        hints: header.retrieval_hints.join("，"),
        memoryType: header.memory_type || "project",
        memoryClass: header.memory_class || "work",
        confidence: header.confidence || "medium"
      });
      setGovernanceMessage("已把当前记忆填入整理区。");
    } else {
      setGovernanceMessage("请选择一条长期记忆，再进入整理。");
    }
    setActiveLayer("governance");
  }

  function addSelectedToMerge() {
    if (!selectedDurableFilename) {
      setError("请先选择一条长期记忆，再加入合并队列。");
      return;
    }
    setMergeFilenames((prev) => (
      prev.includes(selectedDurableFilename) ? prev : [...prev, selectedDurableFilename]
    ));
    setActiveLayer("governance");
  }

  async function deleteSelectedMemory() {
    if (!selectedDurableFilename) {
      setError("请先选择一条长期记忆，再执行删除。");
      return;
    }
    await deleteMemoryNote(selectedDurableFilename);
  }

  async function saveProjectRules() {
    const path = projectInstructionSource?.path || "AGENTS.md";
    setProjectInstructionBusy("保存项目规则源");
    setError("");
    setGovernanceMessage("");
    try {
      const payload = await saveProjectInstructionSource(path, projectInstructionDraft);
      setProjectInstructions(payload);
      setProjectInstructionDraft(payload.sources[0]?.content ?? "");
      setGovernanceMessage("项目规则源已保存；下一次 prompt 组装会读取最新内容。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "项目规则源保存失败");
    } finally {
      setProjectInstructionBusy("");
    }
  }

  function renderStatusFilter() {
    return (
      <div className="memory-status-filter" role="list" aria-label="长期记忆状态筛选">
        {([
          ["all", "全部"],
          ["active", `${durableStatusStats.active} 已启用`],
          ["inactive", `${durableStatusStats.inactive} 候选`],
          ["archived", `${durableStatusStats.archived} 归档`],
          ["deprecated", `${durableStatusStats.deprecated} 已合并`]
        ] as Array<[DurableStatusFilter, string]>).map(([key, label]) => (
          <button
            aria-pressed={durableStatusFilter === key}
            className={durableStatusFilter === key ? "memory-status-filter__active" : ""}
            key={key}
            onClick={() => setDurableStatusFilter(key)}
            type="button"
          >
            {label}
          </button>
        ))}
      </div>
    );
  }

  function renderDurableDetail() {
    if (durableNoteLoading) {
      return (
        <div className="workspace-record memory-empty-state">
          <Loader2 className="spin" size={16} />
          <h3>正在读取长期记忆</h3>
          <p>{selectedDurableFilename}</p>
        </div>
      );
    }
    if (!selectedDurableNote) {
      return (
        <div className="workspace-record memory-empty-state">
          <ClipboardList size={18} />
          <h3>选择一条长期记忆</h3>
          <p>左侧点开任意记忆，可以检查正文、打开源文件，并执行启停、归档或删除。</p>
        </div>
      );
    }

    const header = selectedDurableNote.header;
    return (
      <>
        <div className="memory-detail-head">
          <span>{selectedDurableNote.path}</span>
          <strong>{header?.title || selectedDurableFilename}</strong>
          <div className="memory-durable-reader__badges">
            <b className={`memory-status-pill memory-status-pill--${statusTone(header?.status || "")}`}>
              {statusLabel(header?.status || "unknown")}
            </b>
            <b>{header?.eligible_for_injection ? "允许注入" : "不注入"}</b>
            <b>{header?.memory_class}/{header?.memory_type}</b>
            <b>{header?.confidence || "confidence unknown"}</b>
          </div>
        </div>

        <section className="memory-semantic-body">
          <div>
            <BookOpenCheck size={15} />
            <h4>稳定语义</h4>
          </div>
          <p>{selectedSemanticText || "这条记忆没有可展示的稳定语义正文，请打开源文件检查结构。"}</p>
          {header?.retrieval_hints.length ? (
            <small>检索提示：{header.retrieval_hints.join(" / ")}</small>
          ) : null}
        </section>

        <div className="memory-detail-facts">
          <article>
            <span>Note ID</span>
            <strong>{header?.note_id || "未声明"}</strong>
          </article>
          <article>
            <span>更新时间</span>
            <strong>{header?.updated_at || "未知"}</strong>
          </article>
        </div>

        <details className="memory-raw-preview">
          <summary>源文件预览 / 调试</summary>
          <pre>{selectedDurableNote.content_preview}</pre>
        </details>

        <div className="memory-durable-reader__actions">
          <button onClick={() => void loadInspectorFile(selectedDurableNote.path)} type="button">
            <FileText size={13} />
            打开源文件
          </button>
          <button
            disabled={Boolean(governanceBusy) || header?.status === "active"}
            onClick={() => void runGovernanceAction("激活长期记忆", () => activateDurableMemory(selectedDurableFilename, "Activated from durable reader"))}
            type="button"
          >
            激活
          </button>
          <button
            disabled={Boolean(governanceBusy) || header?.status !== "active"}
            onClick={() => void runGovernanceAction("停用长期记忆", () => disableDurableMemory(selectedDurableFilename, "Disabled from durable reader"))}
            type="button"
          >
            停用
          </button>
          <button
            disabled={Boolean(governanceBusy) || header?.status === "archived"}
            onClick={() => void runGovernanceAction("归档长期记忆", () => archiveDurableMemory(selectedDurableFilename, "Archived from durable reader"))}
            type="button"
          >
            <Archive size={13} />
            归档
          </button>
          <button disabled={Boolean(governanceBusy)} onClick={organizeSelectedMemory} type="button">
            整理
          </button>
          <button disabled={Boolean(governanceBusy)} onClick={addSelectedToMerge} type="button">
            <GitBranch size={13} />
            加入合并
          </button>
          <button
            className="memory-action-button--danger"
            disabled={Boolean(governanceBusy)}
            onClick={() => void deleteMemoryNote(selectedDurableFilename)}
            type="button"
          >
            <Trash2 size={13} />
            删除
          </button>
        </div>
      </>
    );
  }

  function renderLibraryLayer() {
    return (
      <section className="workspace-section memory-durable-reader">
        <div className="workspace-section__head memory-section-head">
          <Database size={18} />
          <h3>长期记忆库</h3>
          <span className="memory-library-count">
            {durable ? `${filteredHeaders.length}/${durable.total} 条` : "读取中"}
            {durable ? ` · ${durable.injectable} 条可注入` : ""}
          </span>
          {renderStatusFilter()}
        </div>

        {mergeFilenames.length ? (
          <div className="memory-selection-bar">
            <span>已选 {mergeFilenames.length} 条用于合并</span>
            <button onClick={() => setActiveLayer("governance")} type="button">
              <GitBranch size={13} />
              进入治理
            </button>
            <button onClick={() => setMergeFilenames([])} type="button">清空选择</button>
          </div>
        ) : null}

        <div className="memory-durable-reader__layout">
          <aside className="memory-durable-reader__list">
            {filteredHeaders.length ? filteredHeaders.map((note) => {
              const selected = selectedDurableFilename === note.filename;
              return (
                <div className={`memory-durable-row ${selected ? "memory-durable-row--active" : ""}`} key={`reader-${note.filename}`}>
                  <button onClick={() => void inspectDurableNote(note)} type="button">
                    <span>
                      <b className={`memory-status-dot memory-status-dot--${statusTone(note.status)}`} />
                      {statusLabel(note.status)} · {note.eligible_for_injection ? "可注入" : "不注入"} · {note.memory_class}/{note.memory_type}
                    </span>
                    <strong>{note.title || note.filename}</strong>
                    <em>{compactText(semanticMemoryText(note), 128) || "暂无语义正文"}</em>
                  </button>
                  <label>
                    <input
                      checked={mergeFilenames.includes(note.filename)}
                      onChange={() => toggleMergeFilename(note.filename)}
                      type="checkbox"
                    />
                    合并
                  </label>
                </div>
              );
            }) : (
              <article className="workspace-record memory-empty-state">
                <Search size={18} />
                <h3>没有匹配的长期记忆</h3>
                <p>换一个搜索词，或在治理页写入新的稳定记忆。</p>
              </article>
            )}
          </aside>
          <article className="memory-durable-reader__detail">
            {renderDurableDetail()}
          </article>
        </div>
      </section>
    );
  }

  function renderGovernanceLayer() {
    return (
      <section className="workspace-section memory-governance-workbench">
        <div className="workspace-section__head memory-section-head">
          <ShieldCheck size={18} />
          <h3>长期记忆治理</h3>
          <span className="memory-library-count">{selectedDurableFilename || "未选中记忆"}</span>
          <div className="memory-governance-actions">
            <button onClick={reviewCandidateMemories} type="button">候选</button>
            <button onClick={organizeSelectedMemory} type="button">整理当前</button>
            <button onClick={addSelectedToMerge} type="button">加入合并</button>
            <button onClick={() => void deleteSelectedMemory()} type="button">删除当前</button>
          </div>
        </div>

        <div className="memory-governance-status">
          <article>
            <span>合并队列</span>
            <strong>{mergeFilenames.length} 条</strong>
            <em>{mergeFilenames.join(" / ") || "暂无选择"}</em>
          </article>
          <article>
            <span>可注入</span>
            <strong>{durable?.injectable ?? 0}</strong>
            <em>active 且 eligible_for_injection</em>
          </article>
          <article>
            <span>维护运行态</span>
            <strong>{durable?.maintenance_runtime ? "已连接" : "未读取"}</strong>
            <em>{compactJson(durable?.maintenance_runtime, 180) || "暂无运行态摘要"}</em>
          </article>
        </div>

        <div className="memory-governance-editor__grid">
          <article className="memory-governance-editor__panel">
            <span>整理候选</span>
            <strong>新增长期记忆</strong>
            <p className="memory-governance-hint">候选内容需要整理成一句稳定、可复用的事实或偏好，再写入长期记忆。</p>
            <input
              onChange={(event) => setNewMemory((prev) => ({ ...prev, title: event.target.value }))}
              placeholder="标题，例如：复杂任务先给结论"
              value={newMemory.title}
            />
            <textarea
              onChange={(event) => setNewMemory((prev) => ({ ...prev, canonical: event.target.value }))}
              placeholder="稳定表述，会进入 canonical_statement"
              value={newMemory.canonical}
            />
            <input
              onChange={(event) => setNewMemory((prev) => ({ ...prev, summary: event.target.value }))}
              placeholder="摘要，可留空"
              value={newMemory.summary}
            />
            <input
              onChange={(event) => setNewMemory((prev) => ({ ...prev, hints: event.target.value }))}
              placeholder="检索提示词，用逗号分隔"
              value={newMemory.hints}
            />
            <div className="memory-governance-editor__row">
              <select onChange={(event) => setNewMemory((prev) => ({ ...prev, memoryType: event.target.value }))} value={newMemory.memoryType}>
                <option value="project">project</option>
                <option value="user">user</option>
                <option value="feedback">feedback</option>
                <option value="reference">reference</option>
              </select>
              <select onChange={(event) => setNewMemory((prev) => ({ ...prev, memoryClass: event.target.value }))} value={newMemory.memoryClass}>
                <option value="work">work</option>
                <option value="preference">preference</option>
              </select>
              <select onChange={(event) => setNewMemory((prev) => ({ ...prev, confidence: event.target.value }))} value={newMemory.confidence}>
                <option value="medium">medium</option>
                <option value="high">high</option>
                <option value="low">low</option>
              </select>
            </div>
            <Button chrome="action" disabled={Boolean(governanceBusy)} onClick={() => void createMemoryFromDraft()} variant="primary">
              {governanceBusy === "写入长期记忆" ? <Loader2 className="spin" size={14} /> : <FileText size={14} />}
              写入长期记忆
            </Button>
          </article>

          <article className="memory-governance-editor__panel">
            <span>合并治理</span>
            <strong>合并为新记忆</strong>
            <p className="memory-governance-hint">合并会创建一条新的稳定记忆，并废弃旧记录；这里不是把正文简单拼接。</p>
            <p>已选择 {mergeFilenames.length} 条：{mergeFilenames.join(" / ") || "暂无"}</p>
            <input
              onChange={(event) => setMergeDraft((prev) => ({ ...prev, title: event.target.value }))}
              placeholder="合并后的新标题"
              value={mergeDraft.title}
            />
            <textarea
              onChange={(event) => setMergeDraft((prev) => ({ ...prev, canonical: event.target.value }))}
              placeholder="合并后的稳定表述"
              value={mergeDraft.canonical}
            />
            <input
              onChange={(event) => setMergeDraft((prev) => ({ ...prev, summary: event.target.value }))}
              placeholder="合并摘要，可留空"
              value={mergeDraft.summary}
            />
            <input
              onChange={(event) => setMergeDraft((prev) => ({ ...prev, reason: event.target.value }))}
              placeholder="合并原因，会写入旧记忆 invalidation_reason"
              value={mergeDraft.reason}
            />
            <div className="memory-governance-editor__row">
              <Button chrome="action" disabled={Boolean(governanceBusy) || mergeFilenames.length < 2} onClick={() => void mergeSelectedMemories()} variant="primary">
                {governanceBusy === "合并长期记忆" ? <Loader2 className="spin" size={14} /> : <GitBranch size={14} />}
                合并选中
              </Button>
              <Button chrome="action" disabled={!mergeFilenames.length} onClick={() => setMergeFilenames([])} variant="ghost">
                清空选择
              </Button>
            </div>
          </article>
        </div>
      </section>
    );
  }

  function renderProjectRulesLayer() {
    const source = projectInstructionSource;
    const modelVisibility = projectInstructions?.model_visibility;
    return (
      <section className="workspace-section memory-project-rules">
        <div className="workspace-section__head memory-section-head">
          <FileText size={18} />
          <h3>项目规则源</h3>
          <span className="memory-library-count">
            {source ? source.path : "AGENTS.md"}
            {projectInstructionDirty ? " · 未保存" : ""}
          </span>
          <div className="memory-governance-actions">
            <button disabled={Boolean(projectInstructionBusy)} onClick={() => void loadProjectInstructions()} type="button">
              {projectInstructionBusy === "读取项目规则源" ? <Loader2 className="spin" size={13} /> : <RefreshCw size={13} />}
              刷新
            </button>
            <button
              disabled={Boolean(projectInstructionBusy) || !projectInstructionDirty}
              onClick={() => void saveProjectRules()}
              type="button"
            >
              {projectInstructionBusy === "保存项目规则源" ? <Loader2 className="spin" size={13} /> : <FileText size={13} />}
              保存
            </button>
          </div>
        </div>

        <div className="memory-project-rules__status memory-governance-status">
          <article>
            <span>模型 slot</span>
            <strong>{modelVisibility?.slot || "project_instructions_stable"}</strong>
            <em>{modelVisibility?.cache_role || "session_stable"} / {modelVisibility?.compression_role || "preserve"}</em>
          </article>
          <article>
            <span>模型可见</span>
            <strong>{modelVisibility?.sent_to_model ? "已装载" : "未装载"}</strong>
            <em>{projectInstructions?.bundle.source_hash || "暂无 source hash"}</em>
          </article>
          <article>
            <span>记忆写入</span>
            <strong>{modelVisibility?.memory_write_policy || "disabled"}</strong>
            <em>{projectInstructions?.memory_relation.semantic_memory_write || "disabled"} semantic write</em>
          </article>
        </div>

        <div className="memory-project-rules__layout">
          <aside className="memory-project-rules__sources">
            {(projectInstructions?.sources.length ? projectInstructions.sources : [{
              path: "AGENTS.md",
              absolute_path: "",
              scope_root: "",
              source_kind: "project_instruction_file",
              exists: false,
              loaded: false,
              editable: true,
              content: "",
              content_hash: "",
              mtime_ns: 0,
              size_bytes: 0,
            }]).map((item) => (
              <article className="memory-project-source-row" key={item.path}>
                <span>{item.source_kind}</span>
                <strong>{item.path}</strong>
                <em>{item.loaded ? "runtime 已装载" : item.exists ? "文件存在但未装载" : "文件不存在"}</em>
                <small>{item.content_hash || "空内容不会进入 project_instructions_stable"}</small>
              </article>
            ))}
          </aside>

          <article className="memory-project-rules__editor">
            <div className="memory-detail-head">
              <span>{source?.absolute_path || projectInstructions?.project_root || "项目根目录"}</span>
              <strong>{source?.path || "AGENTS.md"}</strong>
              <div className="memory-durable-reader__badges">
                <b>{source?.exists ? "文件存在" : "待创建"}</b>
                <b>{source?.loaded ? "模型可见" : "未进入模型"}</b>
                <b>非长期记忆</b>
              </div>
            </div>

            <textarea
              aria-label="AGENTS.md 项目规则"
              className="memory-project-rules__textarea"
              onChange={(event) => setProjectInstructionDraft(event.target.value)}
              placeholder="在这里维护 AGENTS.md 项目规则。"
              spellCheck={false}
              value={projectInstructionDraft}
            />

            <div className="memory-durable-reader__actions">
              <button
                disabled={Boolean(projectInstructionBusy) || !projectInstructionDirty}
                onClick={() => void saveProjectRules()}
                type="button"
              >
                {projectInstructionBusy === "保存项目规则源" ? <Loader2 className="spin" size={13} /> : <FileText size={13} />}
                保存项目规则源
              </button>
              <button disabled={!source?.path} onClick={() => void loadInspectorFile(source?.path || "AGENTS.md")} type="button">
                <FileText size={13} />
                打开源文件
              </button>
              <button
                disabled={!projectInstructionDirty}
                onClick={() => setProjectInstructionDraft(source?.content ?? "")}
                type="button"
              >
                撤销未保存
              </button>
            </div>

            <details className="memory-raw-preview">
              <summary>权威链路</summary>
              <pre>{JSON.stringify({
                loader: projectInstructions?.runtime_loader,
                model_visibility: projectInstructions?.model_visibility,
                memory_relation: projectInstructions?.memory_relation,
                bundle: projectInstructions?.bundle,
              }, null, 2)}</pre>
            </details>
          </article>
        </div>
      </section>
    );
  }

  function renderActiveLayer() {
    if (activeLayer === "project-rules") return renderProjectRulesLayer();
    if (activeLayer === "governance") return renderGovernanceLayer();
    return renderLibraryLayer();
  }

  return (
    <div className="workspace-view memory-console">
      <header className="workspace-view__header">
        <div>
          <p className="workspace-view__eyebrow">记忆管理工作台</p>
          <h2 className="workspace-view__title">记忆系统</h2>
          <p className="workspace-view__subtitle">管理长期库和人工治理入口。</p>
        </div>
        <div className="workspace-view__actions">
          <Button chrome="action" onClick={() => void refreshAll()} variant="ghost">
            {loading ? <Loader2 className="spin" size={15} /> : <RefreshCw size={15} />}
            刷新
          </Button>
          <Button
            chrome="action"
            onClick={() => void loadInspectorFile("durable_memory/meta/SCHEMA.md")}
            variant="muted"
          >
            <FileText size={16} />
            查看 Schema
          </Button>
        </div>
      </header>

      {error ? <div className="workspace-alert workspace-alert--danger">{error}</div> : null}
      {governanceMessage ? <div className="workspace-alert">{governanceMessage}</div> : null}

      <section className="memory-command-strip">
        <div className="workspace-search memory-search">
          <Search size={17} />
          <input
            aria-label="查询长期记忆"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="筛选长期记忆：标题、正文、类型或检索提示"
            value={query}
          />
        </div>
        <div className="memory-runtime-stats">
          <article title={currentSessionId || ""}>
            <Activity size={16} />
            <span>当前会话</span>
            <strong>{currentSessionId ? currentSessionId : "未绑定"}</strong>
          </article>
          <article title={tokenTitle}>
            <Gauge size={16} />
            <span>当前上下文</span>
            <strong>{tokenStats ? formatTokenCount(currentContextTokenCount(tokenStats)) : "暂无"}</strong>
          </article>
          <article title={tokenTitle}>
            <FileText size={16} />
            <span>自动压缩阈值</span>
            <strong>{thresholdTokens > 0 ? formatTokenCount(thresholdTokens) : "暂无"}</strong>
          </article>
          <article title={tokenTitle}>
            <Activity size={16} />
            <span>阈值占比</span>
            <strong>{usagePercent !== null ? `${usagePercent}%` : "暂无"}</strong>
          </article>
        </div>
      </section>

      <nav className="memory-layer-nav" aria-label="记忆层级管理">
        {MEMORY_LAYER_DEFS.map((layer) => {
          const Icon = layer.icon;
          return (
            <button
              className={`memory-layer-card ${activeLayer === layer.id ? "memory-layer-card--active" : ""}`}
              key={layer.id}
              onClick={() => setActiveLayer(layer.id)}
              type="button"
            >
              <span className="memory-layer-card__icon"><Icon size={17} /></span>
              <span>
                <em>{layer.eyebrow}</em>
                <strong>{layer.title}</strong>
                <small>{layer.description}</small>
              </span>
              <b>{layerMetric(layer.id, overview, projectInstructions)}</b>
            </button>
          );
        })}
      </nav>

      {renderActiveLayer()}
    </div>
  );
}
