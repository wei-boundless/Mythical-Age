"use client";

import {
  Activity,
  Archive,
  BookOpenCheck,
  ClipboardList,
  Database,
  FileJson,
  FileText,
  Gauge,
  GitBranch,
  Layers3,
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
  getSessionMemoryFiles,
  mergeDurableMemories,
  recallMemoryPreview,
  type DurableMemoryNoteDetail,
  type MemoryHeader,
  type MemoryOverview,
  type MemoryRecallPreview,
  type MemorySessionFile,
  type MemorySessionFilesResponse,
} from "@/lib/api";
import { useAppStore } from "@/lib/store";
import type { TokenStats } from "@/lib/store/types";

type DurableStatusFilter = "all" | "active" | "inactive" | "archived" | "deprecated";
type MemoryLayer = "library" | "session" | "recall" | "governance";

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
    id: "session",
    icon: Layers3,
    title: "会话记忆",
    eyebrow: "session",
    description: "当前会话的状态快照、模型可见片段和落盘文件。"
  },
  {
    id: "recall",
    icon: BookOpenCheck,
    title: "召回预览",
    eyebrow: "recall",
    description: "按查询模拟记忆读取，检查会注入哪些长期记忆。"
  },
  {
    id: "governance",
    icon: ShieldCheck,
    title: "治理",
    eyebrow: "manage",
    description: "整理候选、写入稳定记忆，并合并重复记录。"
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

function tokenPressureLabel(value: string) {
  const labels: Record<string, string> = {
    normal: "正常",
    warning: "偏高",
    microcompact: "微压缩",
    full_compact: "完整压缩"
  };
  return labels[value] ?? (value || "正常");
}

function sessionTokenTitle(tokenStats: TokenStats | null, remainingPercent: number | null) {
  if (!tokenStats) {
    return "";
  }
  return [
    `总计 ${formatTokenCount(tokenStats.total_tokens)} tokens`,
    `消息 ${formatTokenCount(tokenStats.message_tokens)}`,
    `系统 ${formatTokenCount(tokenStats.system_tokens)}`,
    `有效历史 ${formatTokenCount(tokenStats.history_tokens)}/${formatTokenCount(tokenStats.history_budget_tokens)}`,
    remainingPercent !== null ? `余量 ${remainingPercent}%` : "",
    tokenStats.history_did_compact ? `已压缩，原始历史 ${formatTokenCount(tokenStats.raw_history_tokens)}` : "",
  ].filter(Boolean).join("；");
}

function formatFileSize(value: number) {
  if (!value) return "0 B";
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${value} B`;
}

function formatTimestamp(value: number | null) {
  if (!value) return "未生成";
  const date = new Date(value * 1000);
  if (Number.isNaN(date.getTime())) return "时间未知";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(date);
}

function compactJson(value: Record<string, unknown> | null | undefined, limit = 1400) {
  if (!value || !Object.keys(value).length) return "";
  return compactText(JSON.stringify(value, null, 2), limit);
}

function layerMetric(
  layer: MemoryLayer,
  overview: MemoryOverview | null,
  sessionFiles: MemorySessionFilesResponse | null,
  recallPreview: MemoryRecallPreview | null,
  currentSessionId: string | null
) {
  if (layer === "library") {
    const durable = overview?.durable_memory;
    return durable ? `${durable.active}/${durable.total} 启用` : "未加载";
  }
  if (layer === "session") {
    if (!currentSessionId) return "未绑定";
    return sessionFiles ? `${sessionFiles.existing_count} 个文件` : "待读取";
  }
  if (layer === "recall") {
    return recallPreview ? `${recallPreview.selected_headers.length} 条命中` : "待预览";
  }
  return overview?.durable_memory ? `${overview.durable_memory.injectable} 可注入` : "待治理";
}

export function MemoryView() {
  const confirm = useConfirmDialog();
  const { currentSessionId, loadInspectorFile, tokenStats } = useAppStore();
  const [activeLayer, setActiveLayer] = useState<MemoryLayer>("library");
  const [query, setQuery] = useState("");
  const [recallQuery, setRecallQuery] = useState("");
  const [overview, setOverview] = useState<MemoryOverview | null>(null);
  const [sessionFiles, setSessionFiles] = useState<MemorySessionFilesResponse | null>(null);
  const [selectedSessionFileId, setSelectedSessionFileId] = useState("");
  const [recallPreview, setRecallPreview] = useState<MemoryRecallPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [sessionFilesLoading, setSessionFilesLoading] = useState(false);
  const [recallLoading, setRecallLoading] = useState(false);
  const [error, setError] = useState("");
  const [governanceBusy, setGovernanceBusy] = useState("");
  const [governanceMessage, setGovernanceMessage] = useState("");
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
  const sessionInspect = recallPreview?.context_result ?? null;
  const selectedSessionFile = useMemo(
    () => sessionFiles?.files.find((file) => file.id === selectedSessionFileId) ?? null,
    [selectedSessionFileId, sessionFiles?.files]
  );

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
  const remainingPercent = tokenStats
    ? Math.max(0, Math.min(100, Math.round(Number(tokenStats.history_remaining_ratio || 0) * 100)))
    : null;
  const tokenTitle = sessionTokenTitle(tokenStats, remainingPercent);

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

  const loadSessionFiles = useCallback(async () => {
    if (!currentSessionId) {
      setSessionFiles(null);
      setSelectedSessionFileId("");
      return;
    }
    setSessionFilesLoading(true);
    setError("");
    try {
      const payload = await getSessionMemoryFiles(currentSessionId);
      setSessionFiles(payload);
      setSelectedSessionFileId((current) => {
        if (current && payload.files.some((file) => file.id === current)) return current;
        return payload.files.find((file) => file.exists)?.id ?? payload.files[0]?.id ?? "";
      });
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "会话记忆文件读取失败");
    } finally {
      setSessionFilesLoading(false);
    }
  }, [currentSessionId]);

  useEffect(() => {
    void loadOverview();
  }, [loadOverview]);

  useEffect(() => {
    void loadSessionFiles();
  }, [loadSessionFiles]);

  async function refreshAll() {
    await loadOverview();
    await loadSessionFiles();
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

  async function runRecall() {
    const trimmed = recallQuery.trim();
    if (!trimmed) {
      setError("召回预览需要输入查询内容。");
      return;
    }
    setRecallLoading(true);
    setError("");
    setGovernanceMessage("");
    try {
      const payload = await recallMemoryPreview({
        query: trimmed,
        session_id: currentSessionId || undefined,
        limit: 8
      });
      setRecallPreview(payload);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "召回预览失败");
    } finally {
      setRecallLoading(false);
    }
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

  function renderSessionFilePreview(file: MemorySessionFile | null) {
    if (sessionFilesLoading) {
      return (
        <div className="workspace-record memory-empty-state">
          <Loader2 className="spin" size={16} />
          <h3>正在读取会话记忆文件</h3>
        </div>
      );
    }
    if (!currentSessionId) {
      return (
        <div className="workspace-record memory-empty-state">
          <Layers3 size={18} />
          <h3>当前没有绑定会话</h3>
          <p>打开或创建会话后，这里会显示会话级记忆文件和模型可见片段。</p>
        </div>
      );
    }
    if (!file) {
      return (
        <div className="workspace-record memory-empty-state">
          <FileJson size={18} />
          <h3>没有会话记忆文件</h3>
          <p>该会话暂时没有生成可检查的会话级记忆文件。</p>
        </div>
      );
    }
    return (
      <>
        <div className="memory-detail-head">
          <span>{file.path}</span>
          <strong>{file.label}</strong>
          <div className="memory-durable-reader__badges">
            <b>{file.kind}</b>
            <b>{file.exists ? "已生成" : "缺失"}</b>
            <b>{formatFileSize(file.size)}</b>
            <b>{formatTimestamp(file.updated_at)}</b>
          </div>
        </div>
        <p className="memory-session-description">{file.description}</p>
        <pre className="memory-session-preview">{file.exists ? file.preview || "文件为空" : "文件尚未生成"}</pre>
        <div className="memory-durable-reader__actions">
          <button disabled={!file.exists} onClick={() => void loadInspectorFile(file.path)} type="button">
            <FileText size={13} />
            打开文件
          </button>
        </div>
      </>
    );
  }

  function renderSessionLayer() {
    const modelPreview = sessionInspect?.model_preview || sessionInspect?.preview || "";
    const debugPreview = sessionInspect?.debug_preview || compactJson(sessionInspect?.context_management);
    return (
      <section className="workspace-section memory-session-workbench">
        <div className="workspace-section__head memory-section-head">
          <Layers3 size={18} />
          <h3>会话级记忆</h3>
          <span className="memory-library-count">{currentSessionId || "未绑定会话"}</span>
          <button className="action-button action-button--ghost" disabled={!currentSessionId || sessionFilesLoading} onClick={() => void loadSessionFiles()} type="button">
            {sessionFilesLoading ? <Loader2 className="spin" size={14} /> : <RefreshCw size={14} />}
            刷新文件
          </button>
        </div>

        <div className="memory-session-summary">
          <article>
            <span>会话状态</span>
            <strong>{sessionInspect?.present ? "已构建" : "未构建"}</strong>
            <em>{sessionInspect?.storage?.memory_runtime_view ? String(sessionInspect.storage.memory_runtime_view) : "暂无 runtime view"}</em>
          </article>
          <article>
            <span>当前目标</span>
            <strong>{sessionInspect?.active_goal || "未记录"}</strong>
            <em>{compactJson(sessionInspect?.durable_matches, 160) || "无长期命中统计"}</em>
          </article>
          <article>
            <span>文件</span>
            <strong>{sessionFiles ? `${sessionFiles.existing_count}/${sessionFiles.files.length}` : "未读取"}</strong>
            <em>{sessionFiles?.root || "session-memory"}</em>
          </article>
        </div>

        <div className="memory-session-layout">
          <aside className="memory-session-file-list">
            {(sessionFiles?.files ?? []).map((file) => (
              <button
                className={selectedSessionFileId === file.id ? "memory-session-file--active" : ""}
                key={file.id}
                onClick={() => setSelectedSessionFileId(file.id)}
                type="button"
              >
                <span>{file.exists ? "已生成" : "缺失"} · {file.kind}</span>
                <strong>{file.label}</strong>
                <em>{formatFileSize(file.size)} · {formatTimestamp(file.updated_at)}</em>
              </button>
            ))}
            {!sessionFiles?.files.length ? (
              <article className="workspace-record memory-empty-state">
                <h3>没有文件清单</h3>
                <p>后端没有返回可管理的会话记忆目标。</p>
              </article>
            ) : null}
          </aside>
          <article className="memory-session-inspector">
            {renderSessionFilePreview(selectedSessionFile)}
          </article>
        </div>

        <div className="memory-session-context-grid">
          <section>
            <strong>模型可见片段</strong>
            <pre>{modelPreview || "当前会话没有可展示的模型可见记忆片段。"}</pre>
          </section>
          <section>
            <strong>调试片段</strong>
            <pre>{debugPreview || "暂无调试上下文。"}</pre>
          </section>
        </div>
      </section>
    );
  }

  function renderRecallLayer() {
    return (
      <section className="workspace-section memory-recall-workbench">
        <div className="workspace-section__head memory-section-head">
          <BookOpenCheck size={18} />
          <h3>召回预览</h3>
          <span className="memory-library-count">{currentSessionId ? `会话 ${currentSessionId}` : "仅长期记忆"}</span>
        </div>
        <div className="memory-recall-query">
          <Search size={16} />
          <input
            onChange={(event) => setRecallQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void runRecall();
            }}
            placeholder="输入任务或用户问题，预览会读取哪些记忆"
            value={recallQuery}
          />
          <button className="action-button action-button--primary" disabled={recallLoading} onClick={() => void runRecall()} type="button">
            {recallLoading ? <Loader2 className="spin" size={14} /> : <BookOpenCheck size={14} />}
            预览召回
          </button>
        </div>

        {recallPreview ? (
          <div className="memory-recall-layout">
            <aside className="memory-recall-summary">
              <article>
                <span>读取意图</span>
                <strong>{recallPreview.intent.intent}</strong>
                <em>{recallPreview.intent.read_mode} / {recallPreview.intent.write_mode}</em>
              </article>
              <article>
                <span>选择结果</span>
                <strong>{recallPreview.selection.should_recall ? "会读取" : "不读取"}</strong>
                <em>{recallPreview.selection.reason || "无原因说明"}</em>
              </article>
              <article>
                <span>置信度</span>
                <strong>{Math.round(Number(recallPreview.selection.confidence || 0) * 100)}%</strong>
                <em>{recallPreview.selection.needs_verification ? "需要校验" : "无需额外校验"}</em>
              </article>
              <section>
                <strong>渲染摘要</strong>
                <pre>{recallPreview.rendered_summary || "没有渲染摘要。"}</pre>
              </section>
            </aside>
            <div className="memory-recall-notes">
              {recallPreview.selected_notes.length ? recallPreview.selected_notes.map((note) => (
                <article className="memory-recall-note" key={`${note.note_id}-${note.filename}`}>
                  <span>{statusLabel(note.status)} · {note.memory_class}/{note.memory_type}</span>
                  <strong>{note.title || note.filename}</strong>
                  <p>{note.canonical_statement || note.summary || compactText(note.content_preview, 220)}</p>
                  <small>{note.retrieval_hints.join(" / ") || note.filename}</small>
                </article>
              )) : (
                <article className="workspace-record memory-empty-state">
                  <h3>没有命中长期记忆</h3>
                  <p>本次查询没有选择任何可注入的长期记忆。</p>
                </article>
              )}
            </div>
          </div>
        ) : (
          <article className="workspace-record memory-empty-state">
            <BookOpenCheck size={18} />
            <h3>尚未运行召回预览</h3>
            <p>输入查询后可以检查 intent、选择结果、命中记忆和最终渲染摘要。</p>
          </article>
        )}
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
            <button className="action-button action-button--primary" disabled={Boolean(governanceBusy)} onClick={() => void createMemoryFromDraft()} type="button">
              {governanceBusy === "写入长期记忆" ? <Loader2 className="spin" size={14} /> : <FileText size={14} />}
              写入长期记忆
            </button>
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
              <button className="action-button action-button--primary" disabled={Boolean(governanceBusy) || mergeFilenames.length < 2} onClick={() => void mergeSelectedMemories()} type="button">
                {governanceBusy === "合并长期记忆" ? <Loader2 className="spin" size={14} /> : <GitBranch size={14} />}
                合并选中
              </button>
              <button className="action-button action-button--ghost" disabled={!mergeFilenames.length} onClick={() => setMergeFilenames([])} type="button">
                清空选择
              </button>
            </div>
          </article>
        </div>
      </section>
    );
  }

  function renderActiveLayer() {
    if (activeLayer === "session") return renderSessionLayer();
    if (activeLayer === "recall") return renderRecallLayer();
    if (activeLayer === "governance") return renderGovernanceLayer();
    return renderLibraryLayer();
  }

  return (
    <div className="workspace-view memory-console">
      <header className="workspace-view__header">
        <div>
          <p className="workspace-view__eyebrow">记忆管理工作台</p>
          <h2 className="workspace-view__title">记忆系统</h2>
          <p className="workspace-view__subtitle">管理长期库、会话记忆、召回预览和人工治理入口。</p>
        </div>
        <div className="workspace-view__actions">
          <button className="action-button action-button--ghost" onClick={() => void refreshAll()} type="button">
            {loading || sessionFilesLoading ? <Loader2 className="spin" size={15} /> : <RefreshCw size={15} />}
            刷新
          </button>
          <button
            className="action-button action-button--muted"
            onClick={() => void loadInspectorFile("durable_memory/meta/SCHEMA.md")}
            type="button"
          >
            <FileText size={16} />
            查看 Schema
          </button>
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
            <span>上下文余量</span>
            <strong>{remainingPercent !== null ? `${remainingPercent}%` : "暂无"}</strong>
          </article>
          <article title={tokenTitle}>
            <FileText size={16} />
            <span>会话 Token</span>
            <strong>{tokenStats ? `${formatTokenCount(tokenStats.total_tokens)} · ${tokenPressureLabel(tokenStats.history_pressure_level)}` : "暂无"}</strong>
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
              <b>{layerMetric(layer.id, overview, sessionFiles, recallPreview, currentSessionId)}</b>
            </button>
          );
        })}
      </nav>

      {renderActiveLayer()}
    </div>
  );
}
