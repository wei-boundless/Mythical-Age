"use client";

import {
  Activity,
  Database,
  FileText,
  Gauge,
  GitBranch,
  ListChecks,
  Loader2,
  RefreshCw,
  Search,
  ShieldCheck,
  Trash2
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  activateDurableMemory,
  archiveDurableMemory,
  createDurableMemory,
  deleteDurableMemory,
  disableDurableMemory,
  getDurableMemoryNote,
  getMemoryOverview,
  mergeDurableMemories,
  type DurableMemoryNoteDetail,
  type MemoryHeader,
  type MemoryOverview,
} from "@/lib/api";
import { useConfirmDialog } from "@/components/layout/ConfirmDialogProvider";
import { useAppStore } from "@/lib/store";
import type { TokenStats } from "@/lib/store/types";

function compactText(value: string, limit = 220) {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (normalized.length <= limit) {
    return normalized;
  }
  return `${normalized.slice(0, limit)}...`;
}

const FRONTMATTER_FIELD_PATTERN = /^(note_id|memory_type|memory_class|title|description|status|confidence|created_at|updated_at|retrieval_hints|eligible_for_injection|canonical_statement|summary|source_kind|source_ref|source_message_excerpt|merged_from|invalidation_reason|deprecated_by):/i;
const SEMANTIC_HEADING_PATTERN = /^#{1,3}\s*(正文|语义正文|memory|canonical|canonical statement|stable statement|长期记忆)\s*$/i;

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

type DurableStatusFilter = "all" | "active" | "inactive" | "archived" | "deprecated";

export function MemoryView() {
  const confirm = useConfirmDialog();
  const { currentSessionId, loadInspectorFile, tokenStats } = useAppStore();
  const [query, setQuery] = useState("");
  const [overview, setOverview] = useState<MemoryOverview | null>(null);
  const [loading, setLoading] = useState(false);
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

  const visibleHeaders = filteredHeaders;
  const durable = overview?.durable_memory ?? null;
  const selectedSemanticText = semanticMemoryText(selectedDurableNote?.header, selectedDurableNote);
  const durableStatusStats = useMemo(() => {
    const headers = overview?.durable_memory.headers ?? [];
    return {
      active: headers.filter((note) => note.status === "active").length,
      inactive: headers.filter((note) => note.status === "inactive").length,
      archived: headers.filter((note) => note.status === "archived").length,
      deprecated: headers.filter((note) => note.status === "deprecated").length
    };
  }, [overview?.durable_memory.headers]);
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

  useEffect(() => {
    void loadOverview();
  }, [loadOverview]);

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

  function scrollToMemoryPanel(panelId: string) {
    document.getElementById(panelId)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function reviewCandidateMemories() {
    setDurableStatusFilter("inactive");
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
      setGovernanceMessage("已把当前记忆填入整理区，确认稳定表述后可写入新长期记忆。");
    } else {
      setGovernanceMessage("请选择一条长期记忆，再进入整理。");
    }
    scrollToMemoryPanel("memory-create-panel");
  }

  function openMergeWorkflow() {
    if (selectedDurableFilename && !mergeFilenames.includes(selectedDurableFilename)) {
      setMergeFilenames((prev) => [...prev, selectedDurableFilename]);
      setGovernanceMessage("已把当前记忆加入合并队列，请再选择至少一条相关记忆。");
    }
    scrollToMemoryPanel("memory-merge-panel");
  }

  async function deleteSelectedMemory() {
    if (!selectedDurableFilename) {
      setError("请先选择一条长期记忆，再执行删除。");
      return;
    }
    await deleteMemoryNote(selectedDurableFilename);
  }

  return (
    <div className="workspace-view memory-console">
      <header className="workspace-view__header">
        <div>
          <p className="workspace-view__eyebrow">Memory System</p>
          <h2 className="workspace-view__title">记忆系统</h2>
        </div>
        <div className="workspace-view__actions">
          <button className="action-button action-button--ghost" onClick={() => void loadOverview()} type="button">
            {loading ? <Loader2 className="animate-spin" size={15} /> : <RefreshCw size={15} />}
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

      {error ? <div className="workspace-alert">{error}</div> : null}

      <div className="workspace-search memory-search">
        <Search size={17} />
        <input
          aria-label="查询记忆"
          onChange={(event) => setQuery(event.target.value)}
          placeholder="按标题、正文、类型或检索提示筛选长期记忆"
          value={query}
        />
      </div>

      {governanceMessage ? <div className="workspace-alert">{governanceMessage}</div> : null}

      <div className="workspace-metrics-grid">
        <div className="workspace-stat" title={currentSessionId || ""}>
          <Activity size={18} />
          <span>当前会话</span>
          <strong>{currentSessionId ? currentSessionId : "未绑定会话"}</strong>
        </div>
        <div className="workspace-stat" title={tokenTitle}>
          <Gauge size={18} />
          <span>上下文余量</span>
          <strong>{remainingPercent !== null ? `${remainingPercent}%` : "暂无数据"}</strong>
        </div>
        <div className="workspace-stat" title={tokenTitle}>
          <FileText size={18} />
          <span>会话 Token</span>
          <strong>{tokenStats ? `${formatTokenCount(tokenStats.total_tokens)} tokens · ${tokenPressureLabel(tokenStats.history_pressure_level)}` : "暂无数据"}</strong>
        </div>
      </div>

      <section className="workspace-section memory-durable-reader">
        <div className="workspace-section__head">
          <Database size={18} />
          <h3>长期记忆库</h3>
          <span className="memory-library-count">
            {durable ? `${filteredHeaders.length}/${durable.total} 条` : "读取中"}
            {durable ? ` · ${durable.injectable} 条可注入` : ""}
          </span>
          <div className="memory-status-filter">
            {([
              ["all", "全部"],
              ["active", `${durableStatusStats.active} 已启用`],
              ["inactive", `${durableStatusStats.inactive} 候选`],
              ["archived", `${durableStatusStats.archived} 归档`],
              ["deprecated", `${durableStatusStats.deprecated} 已合并`]
            ] as Array<[DurableStatusFilter, string]>).map(([key, label]) => (
              <button
                className={durableStatusFilter === key ? "memory-status-filter__active" : ""}
                key={key}
                onClick={() => setDurableStatusFilter(key)}
                type="button"
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        {mergeFilenames.length ? (
          <div className="memory-selection-bar">
            <span>已选 {mergeFilenames.length} 条用于合并</span>
            <button onClick={() => scrollToMemoryPanel("memory-merge-panel")} type="button">
              <GitBranch size={13} />
              进入合并
            </button>
            <button onClick={() => setMergeFilenames([])} type="button">清空选择</button>
          </div>
        ) : null}
        <div className="memory-durable-reader__layout">
          <aside className="memory-durable-reader__list">
            {visibleHeaders.length ? visibleHeaders.map((note) => (
              <div
                className={`memory-durable-row ${selectedDurableFilename === note.filename ? "memory-durable-row--active" : ""}`}
                key={`reader-${note.filename}`}
              >
                <button onClick={() => void inspectDurableNote(note)} type="button">
                  <span>{statusLabel(note.status)} · {note.eligible_for_injection ? "允许注入" : "不注入"}</span>
                  <strong>{note.title || note.filename}</strong>
                  <em>{compactText(semanticMemoryText(note), 128) || "暂无语义正文"}</em>
                </button>
                <label>
                  <input
                    checked={mergeFilenames.includes(note.filename)}
                    onChange={() => toggleMergeFilename(note.filename)}
                    type="checkbox"
                  />
                  加入合并
                </label>
              </div>
            )) : (
              <article className="workspace-record">
                <h3>没有可读的长期记忆</h3>
                <p>换一个搜索词，或新写入一条长期记忆。</p>
              </article>
            )}
          </aside>
          <article className="memory-durable-reader__detail">
            {durableNoteLoading ? (
              <div className="workspace-record">
                <h3>正在读取长期记忆</h3>
                <p>{selectedDurableFilename}</p>
              </div>
            ) : selectedDurableNote ? (
              <>
                <span>{selectedDurableNote.path}</span>
                <strong>{selectedDurableNote.header?.title || selectedDurableFilename}</strong>
                <div className="memory-durable-reader__badges">
                  <b>{statusLabel(selectedDurableNote.header?.status || "unknown")}</b>
                  <b>{selectedDurableNote.header?.eligible_for_injection ? "允许注入" : "不注入"}</b>
                  <b>{selectedDurableNote.header?.memory_class}/{selectedDurableNote.header?.memory_type}</b>
                </div>
                <section className="memory-semantic-body">
                  <div>
                    <ListChecks size={15} />
                    <h4>语义正文</h4>
                  </div>
                  <p>{selectedSemanticText || "这条记忆没有可展示的稳定语义正文，请打开源文件检查结构。"}</p>
                  {selectedDurableNote.header?.retrieval_hints.length ? (
                    <small>检索提示：{selectedDurableNote.header.retrieval_hints.join(" / ")}</small>
                  ) : null}
                </section>
                <details className="memory-raw-preview">
                  <summary>源文件预览 / 调试</summary>
                  <pre>{selectedDurableNote.content_preview}</pre>
                </details>
                <div className="memory-durable-reader__actions">
                  <button onClick={() => void loadInspectorFile(selectedDurableNote.path)} type="button">打开源文件</button>
                  <button
                    disabled={Boolean(governanceBusy) || selectedDurableNote.header?.status === "active"}
                    onClick={() => void runGovernanceAction("激活长期记忆", () => activateDurableMemory(selectedDurableFilename, "Activated from durable reader"))}
                    type="button"
                  >
                    激活
                  </button>
                  <button
                    disabled={Boolean(governanceBusy) || selectedDurableNote.header?.status !== "active"}
                    onClick={() => void runGovernanceAction("停用长期记忆", () => disableDurableMemory(selectedDurableFilename, "Disabled from durable reader"))}
                    type="button"
                  >
                    停用
                  </button>
                  <button
                    disabled={Boolean(governanceBusy) || selectedDurableNote.header?.status === "archived"}
                    onClick={() => void runGovernanceAction("归档长期记忆", () => archiveDurableMemory(selectedDurableFilename, "Archived from durable reader"))}
                    type="button"
                  >
                    归档
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
            ) : (
              <div className="workspace-record">
                <h3>选择一条长期记忆</h3>
                <p>左侧点开任意记忆，可以阅读正文、打开源文件，并执行启停、归档或删除。</p>
              </div>
            )}
          </article>
        </div>
      </section>

      <details className="workspace-section memory-governance-editor">
        <summary className="memory-governance-editor__summary">
          <ShieldCheck size={18} />
          <span>长期记忆管理</span>
        </summary>
        <div className="memory-governance-shortcuts">
          <button onClick={reviewCandidateMemories} type="button">候选</button>
          <button onClick={organizeSelectedMemory} type="button">整理</button>
          <button onClick={openMergeWorkflow} type="button">合并</button>
          <button onClick={() => void deleteSelectedMemory()} type="button">删除</button>
        </div>
        <div className="memory-governance-editor__scroll">
          <div className="memory-governance-editor__grid">
            <article className="memory-governance-editor__panel" id="memory-create-panel">
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
                {governanceBusy === "写入长期记忆" ? <Loader2 className="animate-spin" size={14} /> : <FileText size={14} />}
                写入长期记忆
              </button>
            </article>

            <article className="memory-governance-editor__panel" id="memory-merge-panel">
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
                  {governanceBusy === "合并长期记忆" ? <Loader2 className="animate-spin" size={14} /> : <GitBranch size={14} />}
                  合并选中
                </button>
                <button className="action-button action-button--ghost" disabled={!mergeFilenames.length} onClick={() => setMergeFilenames([])} type="button">
                  清空选择
                </button>
              </div>
            </article>
          </div>
        </div>
      </details>

    </div>
  );
}
