"use client";

import {
  BrainCircuit,
  ChevronDown,
  Database,
  FileText,
  GitBranch,
  Loader2,
  MessageSquare,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
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
  getExperimentTurnMemoryTrace,
  getSessionHistory,
  getMemoryOverview,
  getSessionMemoryFiles,
  mergeDurableMemories,
  recallMemoryPreview,
  type DurableMemoryNoteDetail,
  type ExperimentTurnMemoryTrace,
  type MemoryHeader,
  type MemoryOverview,
  type MemoryRecallPreview,
  type MemorySessionFile,
  type MemoryTraceSection,
  type ToolCall
} from "@/lib/api";
import { useAppStore } from "@/lib/store";

function compactText(value: string, limit = 220) {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (normalized.length <= limit) {
    return normalized;
  }
  return `${normalized.slice(0, limit)}...`;
}

function valueText(value: unknown) {
  if (Array.isArray(value)) {
    return value.filter(Boolean).join(" / ") || "空";
  }
  if (typeof value === "boolean") {
    return value ? "是" : "否";
  }
  return String(value ?? "").trim() || "空";
}

function jsonText(value: unknown) {
  if (value == null) {
    return "空";
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function formatBytes(value: number) {
  if (!value) {
    return "0 B";
  }
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function formatTimestamp(value: number | null) {
  if (!value) {
    return "尚未生成";
  }
  return new Date(value * 1000).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function noteTone(note: MemoryHeader) {
  if (!note.eligible_for_injection || note.status !== "active") {
    return "muted";
  }
  if (note.memory_class === "preference") {
    return "preference";
  }
  if (note.memory_type === "project") {
    return "project";
  }
  return "active";
}

function traceItemsText(sections: MemoryTraceSection[], emptyText: string) {
  const items = sections.flatMap((section) => section.items.map((item) => `${section.label}: ${item}`));
  if (!items.length) {
    return emptyText;
  }
  return items.slice(0, 5).join("\n\n");
}

function traceSectionsCount(sections: MemoryTraceSection[]) {
  return sections.reduce((sum, section) => sum + section.count, 0);
}

function TraceSectionCards({
  emptyText,
  sections,
}: {
  emptyText: string;
  sections: MemoryTraceSection[];
}) {
  if (!sections.length) {
    return (
      <article className="memory-trace-readable__empty">
        <strong>没有记录到片段</strong>
        <p>{emptyText}</p>
      </article>
    );
  }
  return (
    <>
      {sections.map((section) => (
        <article className="memory-trace-readable__section" key={section.id}>
          <span>{section.count} 条</span>
          <strong>{section.label}</strong>
          {section.items.length ? section.items.slice(0, 4).map((item, index) => (
            <p key={`${section.id}-${index}`}>{item}</p>
          )) : <p>该分区存在，但没有展开条目。</p>}
        </article>
      ))}
    </>
  );
}

type ConversationItem = {
  id: string;
  index: number;
  role: "user" | "assistant";
  content: string;
  toolCalls: ToolCall[];
  source: "history" | "live";
};

type MemoryLayer = "conversation" | "state" | "durable";
type DurableStatusFilter = "all" | "active" | "inactive" | "archived" | "deprecated";

const MEMORY_LAYERS: Array<{
  key: MemoryLayer;
  title: string;
  subtitle: string;
  icon: typeof MessageSquare;
}> = [
  {
    key: "conversation",
    title: "对话记忆",
    subtitle: "按轮次看记忆现场",
    icon: MessageSquare
  },
  {
    key: "state",
    title: "状态记忆",
    subtitle: "看 session 状态与上下文",
    icon: BrainCircuit
  },
  {
    key: "durable",
    title: "长期记忆",
    subtitle: "查长期记录与召回",
    icon: Database
  }
];

export function MemoryView() {
  const { currentSessionId, memoryInspectorTarget, messages, tokenStats, loadInspectorFile } = useAppStore();
  const [activeLayer, setActiveLayer] = useState<MemoryLayer>("conversation");
  const [query, setQuery] = useState("");
  const [overview, setOverview] = useState<MemoryOverview | null>(null);
  const [recallPreview, setRecallPreview] = useState<MemoryRecallPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [recalling, setRecalling] = useState(false);
  const [error, setError] = useState("");
  const [historyError, setHistoryError] = useState("");
  const [sessionHistory, setSessionHistory] = useState<{
    title: string;
    messages: Array<{ role: "user" | "assistant"; content: string; tool_calls?: ToolCall[] }>;
  } | null>(null);
  const [expandedMessageIds, setExpandedMessageIds] = useState<string[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState("");
  const [turnInspectingId, setTurnInspectingId] = useState("");
  const [turnRecallPreview, setTurnRecallPreview] = useState<MemoryRecallPreview | null>(null);
  const [linkedMemoryTrace, setLinkedMemoryTrace] = useState<ExperimentTurnMemoryTrace | null>(null);
  const [linkedMemoryTraceStatus, setLinkedMemoryTraceStatus] = useState("");
  const [linkedMemoryTraceLoading, setLinkedMemoryTraceLoading] = useState(false);
  const [sessionMemoryFiles, setSessionMemoryFiles] = useState<MemorySessionFile[]>([]);
  const [selectedSessionMemoryPath, setSelectedSessionMemoryPath] = useState("");
  const [sessionMemoryFilesLoading, setSessionMemoryFilesLoading] = useState(false);
  const [sessionMemoryFilesError, setSessionMemoryFilesError] = useState("");
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

  const visibleHeaders = filteredHeaders.slice(0, 18);
  const conversationItems = useMemo<ConversationItem[]>(() => {
    if (sessionHistory?.messages.length) {
      return sessionHistory.messages.map((message, index) => ({
        id: `history-${index}-${message.role}`,
        index: index + 1,
        role: message.role,
        content: message.content,
        toolCalls: message.tool_calls ?? [],
        source: "history"
      }));
    }

    return messages.map((message, index) => ({
      id: `live-${message.id || index}-${message.role}`,
      index: index + 1,
      role: message.role,
      content: message.content,
      toolCalls: message.toolCalls ?? [],
      source: "live"
    }));
  }, [messages, sessionHistory?.messages]);
  const filteredConversationItems = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) {
      return conversationItems;
    }
    return conversationItems.filter((item) =>
      `${item.role} ${item.content}`.toLowerCase().includes(normalized)
    );
  }, [conversationItems, query]);
  const session = overview?.session_memory ?? null;
  const durable = overview?.durable_memory ?? null;
  const pressure = tokenStats?.history_pressure_level ?? "暂无数据";
  const governanceAlerts = useMemo(() => {
    const headers = overview?.durable_memory.headers ?? [];
    const inactive = headers.filter((note) => note.status !== "active");
    const blocked = headers.filter((note) => !note.eligible_for_injection);
    const lowConfidence = headers.filter((note) => ["low", "weak", "低"].some((key) => note.confidence.toLowerCase().includes(key)));
    const missingSummary = headers.filter((note) => !(note.summary || note.canonical_statement || note.description).trim());
    return [
      { label: "非 active 记录", count: inactive.length, tone: inactive.length ? "warning" : "ok", hint: "可能是归档、暂停或待清理记录。" },
      { label: "禁止注入记录", count: blocked.length, tone: blocked.length ? "muted" : "ok", hint: "不会进入模型上下文，但仍可作为档案查看。" },
      { label: "低置信记录", count: lowConfidence.length, tone: lowConfidence.length ? "warning" : "ok", hint: "后续治理时优先复核。" },
      { label: "摘要缺失记录", count: missingSummary.length, tone: missingSummary.length ? "warning" : "ok", hint: "会影响检索和人工判断。" }
    ];
  }, [overview?.durable_memory.headers]);
  const selectedConversationItem = useMemo(
    () => conversationItems.find((item) => item.id === selectedConversationId) ?? null,
    [conversationItems, selectedConversationId]
  );
  const linkedTurnContext = linkedMemoryTrace?.turn_context ?? null;
  const linkedTraceHasProblem = linkedTurnContext?.status === "failed" || Boolean(linkedTurnContext?.failed_checks?.length);
  const linkedSessionSections = linkedMemoryTrace?.session_memory.model_sections.length
    ? linkedMemoryTrace.session_memory.model_sections
    : linkedMemoryTrace?.session_memory.debug_sections ?? [];
  const linkedDurableSections = linkedMemoryTrace?.durable_memory.model_sections.length
    ? linkedMemoryTrace.durable_memory.model_sections
    : linkedMemoryTrace?.durable_memory.debug_sections ?? [];
  const durableStatusStats = useMemo(() => {
    const headers = overview?.durable_memory.headers ?? [];
    return {
      active: headers.filter((note) => note.status === "active").length,
      inactive: headers.filter((note) => note.status === "inactive").length,
      archived: headers.filter((note) => note.status === "archived").length,
      deprecated: headers.filter((note) => note.status === "deprecated").length
    };
  }, [overview?.durable_memory.headers]);
  const selectedSessionMemoryFile = useMemo(
    () => sessionMemoryFiles.find((file) => file.path === selectedSessionMemoryPath) ?? sessionMemoryFiles.find((file) => file.exists) ?? null,
    [selectedSessionMemoryPath, sessionMemoryFiles]
  );
  const sessionMemoryExistingFiles = useMemo(
    () => sessionMemoryFiles.filter((file) => file.exists),
    [sessionMemoryFiles]
  );

  const loadOverview = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const payload = await getMemoryOverview(currentSessionId || undefined);
      setOverview(payload);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "记忆系统读取失败");
    } finally {
      setLoading(false);
    }
  }, [currentSessionId]);

  const loadSessionMemoryFiles = useCallback(async () => {
    if (!currentSessionId) {
      setSessionMemoryFiles([]);
      setSelectedSessionMemoryPath("");
      setSessionMemoryFilesError("");
      return;
    }
    setSessionMemoryFilesLoading(true);
    setSessionMemoryFilesError("");
    try {
      const payload = await getSessionMemoryFiles(currentSessionId);
      setSessionMemoryFiles(payload.files);
      setSelectedSessionMemoryPath((currentPath) => {
        if (currentPath && payload.files.some((file) => file.path === currentPath)) {
          return currentPath;
        }
        return payload.files.find((file) => file.id === "summary" && file.exists)?.path
          ?? payload.files.find((file) => file.exists)?.path
          ?? payload.files[0]?.path
          ?? "";
      });
    } catch (exc) {
      setSessionMemoryFiles([]);
      setSelectedSessionMemoryPath("");
      setSessionMemoryFilesError(exc instanceof Error ? exc.message : "状态记忆文件读取失败");
    } finally {
      setSessionMemoryFilesLoading(false);
    }
  }, [currentSessionId]);

  const loadConversationHistory = useCallback(async () => {
    if (!currentSessionId) {
      setSessionHistory(null);
      setHistoryError("");
      return;
    }
    setHistoryLoading(true);
    setHistoryError("");
    try {
      const payload = await getSessionHistory(currentSessionId);
      setSessionHistory({
        title: payload.title,
        messages: payload.messages
      });
    } catch (exc) {
      setSessionHistory(null);
      setHistoryError(exc instanceof Error ? exc.message : "会话历史读取失败");
    } finally {
      setHistoryLoading(false);
    }
  }, [currentSessionId]);

  async function runRecallPreview() {
    const trimmed = query.trim();
    if (!trimmed) {
      setError("先输入一句要模拟召回的问题。");
      return;
    }
    setRecalling(true);
    setError("");
    try {
      const payload = await recallMemoryPreview({
        query: trimmed,
        session_id: currentSessionId || undefined,
        limit: 6
      });
      setRecallPreview(payload);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "召回模拟失败");
    } finally {
      setRecalling(false);
    }
  }

  useEffect(() => {
    void loadOverview();
  }, [loadOverview]);

  useEffect(() => {
    if (activeLayer !== "state") {
      return;
    }
    void loadSessionMemoryFiles();
  }, [activeLayer, loadSessionMemoryFiles]);

  useEffect(() => {
    setExpandedMessageIds([]);
    setSelectedConversationId("");
    setTurnRecallPreview(null);
    void loadConversationHistory();
  }, [loadConversationHistory]);

  useEffect(() => {
    if (!memoryInspectorTarget) {
      return;
    }
    setActiveLayer(memoryInspectorTarget.layer ?? "state");
    if (!memoryInspectorTarget.runId || !memoryInspectorTarget.turnId) {
      return;
    }
    setLinkedMemoryTraceLoading(true);
    setLinkedMemoryTraceStatus("");
    void getExperimentTurnMemoryTrace(memoryInspectorTarget.runId, memoryInspectorTarget.turnId)
      .then((payload) => {
        setLinkedMemoryTrace(payload.memory_trace);
        setLinkedMemoryTraceStatus(payload.status === "available" ? "" : payload.reason);
      })
      .catch((exc) => {
        setLinkedMemoryTrace(null);
        setLinkedMemoryTraceStatus(exc instanceof Error ? exc.message : "加载测试记忆链路失败");
      })
      .finally(() => setLinkedMemoryTraceLoading(false));
  }, [memoryInspectorTarget]);

  function toggleConversationItem(messageId: string) {
    setExpandedMessageIds((prev) =>
      prev.includes(messageId)
        ? prev.filter((id) => id !== messageId)
        : [...prev, messageId]
    );
  }

  function toggleAllConversationItems() {
    if (expandedMessageIds.length === filteredConversationItems.length) {
      setExpandedMessageIds([]);
      return;
    }
    setExpandedMessageIds(filteredConversationItems.map((item) => item.id));
  }

  async function inspectConversationItem(item: ConversationItem) {
    const text = item.content.trim();
    if (!text) {
      setError("这一轮没有可分析的文本内容。");
      return;
    }
    setSelectedConversationId(item.id);
    setQuery(text);
    setTurnInspectingId(item.id);
    setError("");
    try {
      const payload = await recallMemoryPreview({
        query: text,
        session_id: currentSessionId || undefined,
        limit: 6
      });
      setTurnRecallPreview(payload);
      setRecallPreview(payload);
    } catch (exc) {
      setTurnRecallPreview(null);
      setError(exc instanceof Error ? exc.message : "这一轮记忆链路分析失败");
    } finally {
      setTurnInspectingId("");
    }
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

  async function deleteMemoryNote(filename: string, source: "reader" | "card") {
    const confirmed = window.confirm(`确认删除长期记忆「${filename}」吗？\n\n文件会移入 durable_memory/trash，并从长期记忆列表中移除。`);
    if (!confirmed) {
      return;
    }
    await runGovernanceAction(
      "删除长期记忆",
      async () => {
        await deleteDurableMemory(filename, `Deleted from durable ${source}`);
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

      <section className="memory-hero">
        <div className="memory-hero__copy">
          <span>只读安装版</span>
          <strong>把记忆拆成三层看，先定位，再治理。</strong>
          <p>
            对话记忆看单轮现场，状态记忆看 session 上下文，长期记忆查 durable memory。
            三层共用同一套后端数据，但前端不再把所有信息挤在一屏里。
          </p>
        </div>
        <div className="memory-orbit" aria-label="记忆系统链路图">
          <div className="memory-orbit__ring" />
          <div className="memory-orbit__node memory-orbit__node--session">
            <BrainCircuit size={16} />
            <span>状态记忆</span>
          </div>
          <div className="memory-orbit__node memory-orbit__node--recall">
            <Search size={16} />
            <span>召回选择</span>
          </div>
          <div className="memory-orbit__node memory-orbit__node--prompt">
            <Sparkles size={16} />
            <span>Prompt 注入</span>
          </div>
          <div className="memory-orbit__node memory-orbit__node--durable">
            <Database size={16} />
            <span>长期记忆</span>
          </div>
        </div>
      </section>

      <nav className="memory-layer-tabs" aria-label="记忆系统分层导航">
        {MEMORY_LAYERS.map((layer) => {
          const Icon = layer.icon;
          return (
            <button
              className={`memory-layer-tab ${activeLayer === layer.key ? "memory-layer-tab--active" : ""}`}
              key={layer.key}
              onClick={() => setActiveLayer(layer.key)}
              type="button"
            >
              <Icon size={18} />
              <span>{layer.title}</span>
              <small>{layer.subtitle}</small>
            </button>
          );
        })}
      </nav>

      {memoryInspectorTarget ? (
        <section className={`memory-inspector-focus ${linkedTraceHasProblem ? "memory-inspector-focus--problem" : ""}`}>
          <div className="memory-inspector-focus__signal">
            <span>{memoryInspectorTarget.source === "test-system" ? "来自测试系统" : "检查目标"}</span>
            <strong>
              {memoryInspectorTarget.turnIndex ? `Turn ${memoryInspectorTarget.turnIndex}` : "指定记忆目标"}
              {linkedTurnContext?.session_alias ? ` · ${linkedTurnContext.session_alias}` : ""}
            </strong>
            <p>
              {linkedMemoryTraceLoading
                ? "正在加载这一轮的真实 memory trace。"
                : linkedMemoryTrace
                  ? linkedMemoryTrace.summary
                  : linkedMemoryTraceStatus || memoryInspectorTarget.reason || "当前目标还没有可读的记忆链路。"}
            </p>
          </div>
          <div className="memory-inspector-focus__meta">
            <span><b>{linkedMemoryTrace?.session_memory.section_count ?? 0}</b> 状态片段</span>
            <span><b>{(linkedMemoryTrace?.durable_memory.exact_count ?? 0) + (linkedMemoryTrace?.durable_memory.relevant_count ?? 0)}</b> 长期命中</span>
            <span><b>{linkedMemoryTrace?.prompt_injection.section_count ?? 0}</b> Prompt 片段</span>
            <span><b>{linkedTurnContext?.status === "passed" ? "通过" : linkedTurnContext?.status === "failed" ? "失败" : "未知"}</b> 测试状态</span>
          </div>
          <div className="memory-inspector-focus__actions">
            <button className={activeLayer === "conversation" ? "memory-inspector-focus__active" : ""} onClick={() => setActiveLayer("conversation")} type="button">
              看对话现场
            </button>
            <button className={activeLayer === "state" ? "memory-inspector-focus__active" : ""} onClick={() => setActiveLayer("state")} type="button">
              看状态记忆
            </button>
            <button className={activeLayer === "durable" ? "memory-inspector-focus__active" : ""} onClick={() => setActiveLayer("durable")} type="button">
              看长期命中
            </button>
          </div>
        </section>
      ) : null}

      {activeLayer === "conversation" ? (
        <>
          {memoryInspectorTarget ? (
            <section className="workspace-section memory-linked-turn">
              <div className="workspace-section__head">
                <GitBranch size={18} />
                <h3>测试 Turn 真实对话链路</h3>
                {memoryInspectorTarget.turnIndex ? <span className="tag-chip">Turn {memoryInspectorTarget.turnIndex}</span> : null}
                <span className="tag-chip">{linkedMemoryTrace ? "真实 trace" : linkedMemoryTraceLoading ? "加载中" : "trace 不完整"}</span>
              </div>
              {linkedMemoryTrace ? (
                <>
                  <div className="memory-linked-turn__dialogue">
                    <article>
                      <span>用户输入</span>
                      <p>{linkedTurnContext?.user_input || memoryInspectorTarget.reason || "该 turn artifact 没有记录用户输入。"}</p>
                    </article>
                    <article>
                      <span>助手输出</span>
                      <p>{linkedTurnContext?.assistant_output || "该 turn artifact 没有记录助手输出。"}</p>
                    </article>
                  </div>
                  <div className="memory-chain-map memory-chain-map--observed">
                    <article className="memory-chain-node memory-chain-node--input">
                      <span>01</span>
                      <strong>输入进入运行链</strong>
                      <p>{compactText(linkedTurnContext?.user_input || memoryInspectorTarget.reason || "空输入", 260)}</p>
                    </article>
                    <article className="memory-chain-node memory-chain-node--session">
                      <span>02</span>
                      <strong>状态记忆参与</strong>
                      <p>{traceItemsText(linkedSessionSections, "这一轮没有状态记忆片段进入模型上下文。")}</p>
                    </article>
                    <article className="memory-chain-node memory-chain-node--durable">
                      <span>03</span>
                      <strong>长期记忆命中</strong>
                      <p>
                        {linkedMemoryTrace.durable_memory.exact_count || linkedMemoryTrace.durable_memory.relevant_count
                          ? `精确 ${linkedMemoryTrace.durable_memory.exact_count} 条，相关 ${linkedMemoryTrace.durable_memory.relevant_count} 条。`
                          : "这一轮没有长期记忆命中。"}
                      </p>
                    </article>
                    <article className="memory-chain-node memory-chain-node--prompt">
                      <span>04</span>
                      <strong>Prompt 注入结果</strong>
                      <p>{linkedMemoryTrace.prompt_injection.sections[0]?.preview || "没有记录到记忆相关 Prompt 注入片段。"}</p>
                    </article>
                  </div>
                </>
              ) : (
                <article className="workspace-record">
                  <h3>{linkedMemoryTraceLoading ? "正在读取真实链路" : "这一轮没有可用 memory trace"}</h3>
                  <p>{linkedMemoryTraceStatus || "可以回到测试系统选择带有 Memory 标记的 turn。"}</p>
                </article>
              )}
            </section>
          ) : null}

          <div className="workspace-search memory-search">
            <Search size={17} />
            <input
              aria-label="搜索对话记忆"
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索当前会话，或展开某一轮查看记忆链路"
              value={query}
            />
            <button className="action-button action-button--ghost" onClick={() => void loadConversationHistory()} type="button">
              {historyLoading ? <Loader2 className="animate-spin" size={15} /> : <RefreshCw size={15} />}
              重载对话
            </button>
          </div>

          <section className="workspace-section memory-management-panel">
            <div className="workspace-section__head">
              <MessageSquare size={18} />
              <h3>对话记忆管理</h3>
              <span className="tag-chip">{currentSessionId ? "当前会话已连接" : "未选择会话"}</span>
            </div>
            <div className="memory-management-panel__grid">
              <article>
                <span>阅读入口</span>
                <strong>当前会话原始文件</strong>
                <p>用于核对真实 messages、tool_calls、压缩上下文和会话标题。</p>
                <button
                  className="action-button action-button--ghost"
                  disabled={!currentSessionId}
                  onClick={() => currentSessionId ? void loadInspectorFile(`sessions/${currentSessionId}.json`) : undefined}
                  type="button"
                >
                  打开会话 JSON
                </button>
              </article>
              <article>
                <span>阅读控制</span>
                <strong>对话展开与召回检查</strong>
                <p>批量展开所有轮次，或单独点击某一轮查看状态记忆、长期召回和 Prompt 注入。</p>
                <div className="memory-management-panel__actions">
                  <button disabled={!filteredConversationItems.length} onClick={toggleAllConversationItems} type="button">
                    {expandedMessageIds.length === filteredConversationItems.length ? "全部收起" : "全部展开"}
                  </button>
                  <button onClick={() => void loadConversationHistory()} type="button">
                    重新读取
                  </button>
                </div>
              </article>
              <article>
                <span>当前范围</span>
                <strong>{sessionHistory?.title || currentSessionId || "没有会话"}</strong>
                <p>{conversationItems.length} 条消息 · {sessionHistory ? "来自后端历史" : "来自前端实时缓存"}</p>
              </article>
            </div>
          </section>

          <section className="workspace-section memory-dialogue">
            <div className="workspace-section__head">
              <MessageSquare size={18} />
              <h3>对话现场</h3>
              <span className="tag-chip">{filteredConversationItems.length}/{conversationItems.length} turns</span>
              <span className="tag-chip">{sessionHistory ? "后端历史" : "实时缓存"}</span>
              {sessionHistory?.title ? <span className="tag-chip">{sessionHistory.title}</span> : null}
              <button className="action-button action-button--muted" disabled={!filteredConversationItems.length} onClick={toggleAllConversationItems} type="button">
                {expandedMessageIds.length === filteredConversationItems.length ? "全部收起" : "全部展开"}
              </button>
            </div>
            {historyError ? <div className="workspace-alert">{historyError}</div> : null}
            <div className="memory-dialogue__rail">
              {filteredConversationItems.length ? filteredConversationItems.map((item) => {
                const expanded = expandedMessageIds.includes(item.id);
                return (
                  <article className={`memory-dialogue-turn memory-dialogue-turn--${item.role}`} key={item.id}>
                    <button
                      className={`memory-dialogue-turn__head ${selectedConversationId === item.id ? "memory-dialogue-turn__head--selected" : ""}`}
                      onClick={() => toggleConversationItem(item.id)}
                      type="button"
                    >
                      <span>{item.index}</span>
                      <strong>{item.role === "user" ? "用户输入" : "助手回应"}</strong>
                      <em>{compactText(item.content, 120)}</em>
                      {item.toolCalls.length ? <i>{item.toolCalls.length} tools</i> : null}
                      <ChevronDown className={expanded ? "memory-dialogue-turn__chevron--open" : ""} size={16} />
                    </button>
                    {expanded ? (
                      <div className="memory-dialogue-turn__body">
                        <pre>{item.content || "空内容"}</pre>
                        {item.toolCalls.length ? (
                          <div className="memory-dialogue-tools">
                            {item.toolCalls.map((toolCall, toolIndex) => (
                              <details key={`${item.id}-tool-${toolIndex}`}>
                                <summary>
                                  工具 {toolIndex + 1}: {toolCall.tool || "unknown"}
                                </summary>
                                <pre>{compactText(`Input:\n${toolCall.input || "空"}\n\nOutput:\n${toolCall.output || "空"}`, 1800)}</pre>
                              </details>
                            ))}
                          </div>
                        ) : null}
                        <button
                          className="action-button action-button--ghost"
                          onClick={() => void inspectConversationItem(item)}
                          type="button"
                        >
                          {turnInspectingId === item.id ? <Loader2 className="animate-spin" size={14} /> : <GitBranch size={14} />}
                          查看这一轮记忆链路
                        </button>
                      </div>
                    ) : null}
                  </article>
                );
              }) : (
                <article className="workspace-record">
                  <h3>没有可展开的对话</h3>
                  <p>当前会话还没有消息，或搜索词没有命中任何对话轮次。</p>
                </article>
              )}
            </div>
          </section>

          <section className="workspace-section memory-turn-chain">
            <div className="workspace-section__head">
              <GitBranch size={18} />
              <h3>单轮记忆链路</h3>
              <span className="tag-chip">{selectedConversationItem ? `Turn ${selectedConversationItem.index}` : "未选择"}</span>
              <span className="tag-chip">{turnRecallPreview ? "模拟链路已生成" : "等待分析"}</span>
            </div>
            {selectedConversationItem ? (
              <div className="memory-chain-map">
                <article className="memory-chain-node memory-chain-node--input">
                  <span>01</span>
                  <strong>{selectedConversationItem.role === "user" ? "用户输入" : "助手回应"}</strong>
                  <p>{compactText(selectedConversationItem.content, 260)}</p>
                </article>
                <article className="memory-chain-node memory-chain-node--session">
                  <span>02</span>
                  <strong>状态记忆</strong>
                  <p>{turnRecallPreview?.context_preview?.debug_preview || session?.debug_preview || "当前没有可展示的状态记忆。"}</p>
                </article>
                <article className="memory-chain-node memory-chain-node--durable">
                  <span>03</span>
                  <strong>长期召回</strong>
                  <p>
                    {turnRecallPreview
                      ? turnRecallPreview.selection.should_recall
                        ? `选中 ${turnRecallPreview.selected_notes.length} 条：${turnRecallPreview.selection.reason || "命中长期记忆"}`
                        : turnRecallPreview.selection.reason || "这一轮没有触发长期记忆召回。"
                      : "展开某一轮后点击“查看这一轮记忆链路”。"}
                  </p>
                </article>
                <article className="memory-chain-node memory-chain-node--prompt">
                  <span>04</span>
                  <strong>Prompt 注入</strong>
                  <p>{turnRecallPreview?.rendered_summary || "没有生成长期记忆注入片段。"}</p>
                </article>
              </div>
            ) : (
              <article className="workspace-record">
                <h3>请选择一轮对话</h3>
                <p>在“对话现场”展开某一轮，然后点击“查看这一轮记忆链路”，这里会显示输入如何经过状态记忆、长期召回和 Prompt 注入。</p>
              </article>
            )}
            {turnRecallPreview?.selected_notes.length ? (
              <div className="memory-chain-notes">
                {turnRecallPreview.selected_notes.map((note) => (
                  <article key={note.note_id || note.filename}>
                    <span>{note.memory_class}/{note.memory_type} · {note.confidence}</span>
                    <strong>{note.title || note.filename}</strong>
                    <p>{note.canonical_statement || note.summary || note.content_preview}</p>
                    <button onClick={() => void loadInspectorFile(`durable_memory/notes/${note.filename}`)} type="button">
                      打开记忆
                    </button>
                  </article>
                ))}
              </div>
            ) : null}
          </section>

          <section className="workspace-section memory-trace-compare">
            <div className="workspace-section__head">
              <GitBranch size={18} />
              <h3>真实链路 / 模拟链路对照</h3>
              <span className="tag-chip">{linkedMemoryTrace ? "真实 trace 已连接" : "等待测试系统 turn"}</span>
              {memoryInspectorTarget?.turnIndex ? <span className="tag-chip">Turn {memoryInspectorTarget.turnIndex}</span> : null}
            </div>
            {linkedMemoryTrace ? (
              <div className="memory-compare-grid">
                <article className="memory-compare-card memory-compare-card--real">
                  <span>Observed Trace</span>
                  <strong>测试系统真实链路</strong>
                  <p>{linkedMemoryTrace.summary}</p>
                  <div className="memory-compare-card__metrics">
                    <b>{linkedMemoryTrace.session_memory.section_count} 状态片段</b>
                    <b>{linkedMemoryTrace.durable_memory.exact_count + linkedMemoryTrace.durable_memory.relevant_count} 长期命中</b>
                    <b>{linkedMemoryTrace.prompt_injection.section_count} Prompt 片段</b>
                  </div>
                </article>
                <article className="memory-compare-card memory-compare-card--sim">
                  <span>Recall Preview</span>
                  <strong>当前普通会话模拟</strong>
                  <p>
                    {turnRecallPreview
                      ? turnRecallPreview.selection.should_recall
                        ? `会召回 ${turnRecallPreview.selected_notes.length} 条：${turnRecallPreview.selection.reason || "命中长期记忆"}`
                        : turnRecallPreview.selection.reason || "模拟结果不召回长期记忆。"
                      : "展开当前会话某一轮并点击“查看这一轮记忆链路”，这里会形成模拟链路。"}
                  </p>
                  <div className="memory-compare-card__metrics">
                    <b>{turnRecallPreview?.context_preview?.present ? "有状态上下文" : "状态待模拟"}</b>
                    <b>{turnRecallPreview ? `${turnRecallPreview.selected_notes.length} 长期命中` : "未模拟"}</b>
                    <b>{turnRecallPreview?.rendered_summary ? "有注入摘要" : "无注入摘要"}</b>
                  </div>
                </article>
              </div>
            ) : (
              <article className="workspace-record">
                <h3>还没有真实 memory trace</h3>
                <p>从测试系统点击某个 turn 的“记忆链路”，或从系统框架图点击“去状态记忆阅读”，这里会展示真实链路并与当前模拟链路对照。</p>
              </article>
            )}
          </section>
        </>
      ) : null}

      {activeLayer === "state" ? (
        <>
          <section className="workspace-section memory-state-workbench">
            <div className="workspace-section__head">
              <BrainCircuit size={18} />
              <h3>状态记忆文件工作台</h3>
              <span className="tag-chip">{currentSessionId || "未选择会话"}</span>
              <span className="tag-chip">{sessionMemoryFilesLoading ? "读取中" : `${sessionMemoryExistingFiles.length} 个文件`}</span>
              <button className="action-button action-button--ghost" onClick={() => void loadSessionMemoryFiles()} type="button">
                {sessionMemoryFilesLoading ? <Loader2 className="animate-spin" size={14} /> : <RefreshCw size={14} />}
                刷新文件
              </button>
            </div>
            {sessionMemoryFilesError ? <div className="workspace-alert">{sessionMemoryFilesError}</div> : null}
            <div className="memory-state-workbench__summary">
              <article>
                <span>当前目标</span>
                <strong>{session?.active_goal || "未写入"}</strong>
                <p>{session?.debug_preview || session?.preview || "还没有形成可读状态。先继续一次对话，状态文件会随运行写入。"}</p>
              </article>
              <article>
                <span>上下文压力</span>
                <strong>{pressure}</strong>
                <p>策略：{valueText(session?.context_management?.["strategy"])}</p>
              </article>
              <article>
                <span>流程 / 任务</span>
                <strong>{valueText(session?.flow_state?.status)} / {valueText(session?.task_state?.status)}</strong>
                <p>风险：{valueText(session?.risk?.flags)}</p>
              </article>
            </div>

            <div className="memory-state-file-browser">
              <aside className="memory-state-file-list" aria-label="状态记忆文件列表">
                {currentSessionId ? sessionMemoryFiles.map((file) => (
                  <button
                    className={`memory-state-file-row ${selectedSessionMemoryFile?.path === file.path ? "memory-state-file-row--active" : ""} ${!file.exists ? "memory-state-file-row--missing" : ""}`}
                    key={file.path}
                    onClick={() => setSelectedSessionMemoryPath(file.path)}
                    type="button"
                  >
                    <span>{file.exists ? file.kind : "missing"}</span>
                    <strong>{file.label}</strong>
                    <em>{file.path}</em>
                    <small>{file.exists ? `${formatBytes(file.size)} · ${formatTimestamp(file.updated_at)}` : "文件尚未生成"}</small>
                  </button>
                )) : (
                  <article className="workspace-record">
                    <h3>还没有选择会话</h3>
                    <p>状态记忆按 session_id 存在 `session-memory` 目录下，先选择一个会话后才能读取。</p>
                  </article>
                )}
              </aside>

              <article className="memory-state-file-reader">
                {sessionMemoryFilesLoading ? (
                  <div className="workspace-record">
                    <h3>正在读取状态记忆文件</h3>
                    <p>{currentSessionId || "等待会话"}</p>
                  </div>
                ) : selectedSessionMemoryFile ? (
                  <>
                    <div className="memory-state-file-reader__head">
                      <div>
                        <span>{selectedSessionMemoryFile.path}</span>
                        <strong>{selectedSessionMemoryFile.label}</strong>
                        <p>{selectedSessionMemoryFile.description}</p>
                      </div>
                      <button
                        className="action-button action-button--muted"
                        disabled={!selectedSessionMemoryFile.exists}
                        onClick={() => void loadInspectorFile(selectedSessionMemoryFile.path)}
                        type="button"
                      >
                        <FileText size={14} />
                        打开源文件
                      </button>
                    </div>
                    <div className="memory-state-file-reader__meta">
                      <b>{selectedSessionMemoryFile.exists ? "已生成" : "未生成"}</b>
                      <b>{selectedSessionMemoryFile.kind}</b>
                      <b>{formatBytes(selectedSessionMemoryFile.size)}</b>
                      <b>{formatTimestamp(selectedSessionMemoryFile.updated_at)}</b>
                    </div>
                    <pre>
                      {selectedSessionMemoryFile.exists
                        ? selectedSessionMemoryFile.preview || "文件为空。"
                        : "这个状态记忆文件还没有生成。通常需要完成一次会话运行，或触发对应的压缩 / 流程快照后才会出现。"}
                    </pre>
                  </>
                ) : (
                  <div className="workspace-record">
                    <h3>没有可阅读的状态文件</h3>
                    <p>当前会话还没有写入 session-memory 文件。</p>
                  </div>
                )}
              </article>
            </div>
          </section>

          <section className="workspace-section memory-state-runtime">
            <div className="workspace-section__head">
              <GitBranch size={18} />
              <h3>测试系统联动状态</h3>
              {memoryInspectorTarget?.turnIndex ? <span className="tag-chip">Turn {memoryInspectorTarget.turnIndex}</span> : null}
              <span className="tag-chip">{linkedMemoryTrace ? "真实 trace 已连接" : "等待测试 turn"}</span>
            </div>
            {linkedMemoryTrace ? (
              <>
                <article className="memory-state-runtime__hero">
                  <span>真实测试 turn</span>
                  <strong>第 {memoryInspectorTarget?.turnIndex ?? linkedTurnContext?.index ?? "?"} 个节点的状态记忆</strong>
                  <p>{linkedTurnContext?.user_input || memoryInspectorTarget?.reason || "这是一条从测试系统跳转过来的真实运行记录。"}</p>
                </article>
                <div className="memory-trace-readable">
                  <TraceSectionCards
                    emptyText="测试 artifact 没有记录状态记忆片段，可能这一轮没有触发 session memory 注入。"
                    sections={linkedSessionSections}
                  />
                </div>
                <div className="memory-state-reader__grid">
                  <article className="memory-state-reader__panel">
                    <span>Context Slots</span>
                    <strong>该轮上下文槽位</strong>
                    <pre>{jsonText(linkedMemoryTrace.session_memory.context_slots)}</pre>
                  </article>
                  <article className="memory-state-reader__panel">
                    <span>Flow / Task</span>
                    <strong>该轮流程与任务状态</strong>
                    <pre>{jsonText({ flow_state: linkedMemoryTrace.session_memory.flow_state, task_state: linkedMemoryTrace.session_memory.task_state })}</pre>
                  </article>
                  <article className="memory-state-reader__panel">
                    <span>Context Management</span>
                    <strong>该轮上下文选择</strong>
                    <pre>{jsonText(linkedMemoryTrace.context_management)}</pre>
                  </article>
                  <article className="memory-state-reader__panel">
                    <span>Assistant Output</span>
                    <strong>该轮最终输出</strong>
                    <pre>{linkedTurnContext?.assistant_output || "没有记录助手输出。"}</pre>
                  </article>
                </div>
              </>
            ) : (
              <article className="workspace-record">
                <h3>还没有测试链路</h3>
                <p>从测试系统点击某个 turn 的“记忆链路”后，这里会把真实运行时携带的状态片段和当前 session 文件分开展示。</p>
              </article>
            )}
          </section>

        </>
      ) : null}

      {activeLayer === "durable" ? (
        <>
          {linkedMemoryTrace ? (
            <section className="workspace-section memory-durable-focus">
              <div className="workspace-section__head">
                <Database size={18} />
                <h3>测试 Turn 长期记忆命中</h3>
                <span className="tag-chip">{linkedMemoryTrace.durable_memory.exact_count} 精确</span>
                <span className="tag-chip">{linkedMemoryTrace.durable_memory.relevant_count} 相关</span>
              </div>
              <div className="memory-trace-readable">
                <TraceSectionCards
                  emptyText="这一轮没有长期记忆片段进入模型上下文。"
                  sections={linkedDurableSections}
                />
              </div>
            </section>
          ) : null}

          <div className="workspace-search memory-search">
        <Search size={17} />
        <input
          aria-label="查询记忆"
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              void runRecallPreview();
            }
          }}
          placeholder="输入一句问题，筛选长期记忆，或模拟本轮会召回什么"
          value={query}
        />
        <button className="action-button action-button--primary" disabled={recalling} onClick={() => void runRecallPreview()} type="button">
          {recalling ? <Loader2 className="animate-spin" size={15} /> : <GitBranch size={15} />}
          召回模拟
        </button>
      </div>

      <div className="workspace-metrics-grid">
        <div className="workspace-stat">
          <Database size={18} />
          <span>长期记忆总数</span>
          <strong>{durable ? `${durable.total} 条` : "读取中"}</strong>
        </div>
        <div className="workspace-stat">
          <Database size={18} />
          <span>Active</span>
          <strong>{durable ? `${durable.active} 条` : "读取中"}</strong>
        </div>
        <div className="workspace-stat">
          <ShieldCheck size={18} />
          <span>允许注入</span>
          <strong>{durable ? `${durable.injectable} 条` : "读取中"}</strong>
        </div>
        <div className="workspace-stat">
          <Search size={18} />
          <span>当前命中</span>
          <strong>{filteredHeaders.length} 条</strong>
        </div>
      </div>

      {governanceMessage ? <div className="workspace-alert">{governanceMessage}</div> : null}

      <section className="workspace-section memory-durable-reader">
        <div className="workspace-section__head">
          <Database size={18} />
          <h3>长期记忆阅读器</h3>
          <div className="memory-status-filter">
            {([
              ["all", "全部"],
              ["active", `${durableStatusStats.active} active`],
              ["inactive", `${durableStatusStats.inactive} inactive`],
              ["archived", `${durableStatusStats.archived} archived`],
              ["deprecated", `${durableStatusStats.deprecated} deprecated`]
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
        <div className="memory-durable-reader__layout">
          <aside className="memory-durable-reader__list">
            {visibleHeaders.length ? visibleHeaders.map((note) => (
              <button
                className={`memory-durable-row ${selectedDurableFilename === note.filename ? "memory-durable-row--active" : ""}`}
                key={`reader-${note.filename}`}
                onClick={() => void inspectDurableNote(note)}
                type="button"
              >
                <span>{note.status} · {note.eligible_for_injection ? "注入" : "不注入"}</span>
                <strong>{note.title || note.filename}</strong>
                <em>{compactText(note.canonical_statement || note.summary || note.description, 110)}</em>
              </button>
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
                  <b>{selectedDurableNote.header?.status || "unknown"}</b>
                  <b>{selectedDurableNote.header?.eligible_for_injection ? "允许注入" : "不注入"}</b>
                  <b>{selectedDurableNote.header?.memory_class}/{selectedDurableNote.header?.memory_type}</b>
                </div>
                <pre>{selectedDurableNote.content_preview}</pre>
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
                    className="memory-action-button--danger"
                    disabled={Boolean(governanceBusy)}
                    onClick={() => void deleteMemoryNote(selectedDurableFilename, "reader")}
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
                <p>左侧点开任意记忆，可以在这里阅读正文、打开源文件，并切换 active / inactive。</p>
              </div>
            )}
          </article>
        </div>
      </section>

      <section className="workspace-section memory-governance-editor">
        <div className="workspace-section__head">
          <ShieldCheck size={18} />
          <h3>长期记忆治理台</h3>
          <span className="tag-chip">写入 / 停用 / 归档 / 合并</span>
          <span className="tag-chip">带审计日志</span>
        </div>
        <div className="memory-governance-editor__grid">
          <article className="memory-governance-editor__panel">
            <span>Write</span>
            <strong>写入新长期记忆</strong>
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

          <article className="memory-governance-editor__panel">
            <span>Merge</span>
            <strong>合并选中记忆</strong>
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
      </section>

      <section className="workspace-section memory-governance-preview">
        <div className="workspace-section__head">
          <ShieldCheck size={18} />
          <h3>长期记忆治理预检</h3>
          <span className="tag-chip">只读</span>
          <span className="tag-chip">不写入</span>
        </div>
        <div className="memory-governance-grid">
          {governanceAlerts.map((item) => (
            <article className={`memory-governance-card memory-governance-card--${item.tone}`} key={item.label}>
              <span>{item.label}</span>
              <strong>{item.count} 条</strong>
              <p>{item.hint}</p>
            </article>
          ))}
        </div>
      </section>

      {recallPreview ? (
        <section className="memory-recall">
          <div className="memory-recall__summary">
            <span>{recallPreview.selection.should_recall ? "会召回" : "不会召回"}</span>
            <strong>{recallPreview.selection.reason || recallPreview.intent.intent}</strong>
            <p>{recallPreview.rendered_summary || "没有生成可注入的长期记忆摘要。"}</p>
          </div>
          <div className="memory-recall__notes">
            {recallPreview.selected_notes.length ? recallPreview.selected_notes.map((note) => (
              <article key={note.note_id || note.filename}>
                <span>{note.memory_class}/{note.memory_type} · {note.confidence}</span>
                <strong>{note.title || note.filename}</strong>
                <p>{note.canonical_statement || note.summary || note.content_preview}</p>
              </article>
            )) : (
              <article>
                <span>empty</span>
                <strong>没有选中长期记忆</strong>
                <p>这不一定是问题，可能只是当前问题没有明确记忆信号。</p>
              </article>
            )}
          </div>
        </section>
      ) : null}

      <section className="workspace-section">
        <div className="workspace-section__head">
          <Database size={18} />
          <h3>长期记忆记录</h3>
          <span className="tag-chip">{filteredHeaders.length} matched</span>
        </div>
        <div className="memory-note-grid">
          {visibleHeaders.length ? visibleHeaders.map((note) => (
            <article className={`memory-note-card memory-note-card--${noteTone(note)}`} key={note.note_id || note.filename}>
              <div className="memory-note-card__meta">
                <span>{note.memory_class}/{note.memory_type}</span>
                <span>{note.status} · {note.confidence}</span>
              </div>
              <h4>{note.title || note.filename}</h4>
              <p>{compactText(note.canonical_statement || note.summary || note.description, 260)}</p>
              <div className="memory-note-card__footer">
                <span>{note.eligible_for_injection ? "允许注入" : "不注入"}</span>
                <button onClick={() => toggleMergeFilename(note.filename)} type="button">
                  {mergeFilenames.includes(note.filename) ? "取消合并" : "加入合并"}
                </button>
                <button onClick={() => void inspectDurableNote(note)} type="button">
                  阅读
                </button>
                <button onClick={() => void loadInspectorFile(`durable_memory/notes/${note.filename}`)} type="button">
                  打开
                </button>
                <button
                  disabled={Boolean(governanceBusy) || note.status === "active"}
                  onClick={() => void runGovernanceAction("激活长期记忆", () => activateDurableMemory(note.filename, "Activated from memory governance UI"))}
                  type="button"
                >
                  激活
                </button>
                <button
                  disabled={Boolean(governanceBusy) || note.status !== "active"}
                  onClick={() => void runGovernanceAction("停用长期记忆", () => disableDurableMemory(note.filename, "Disabled from memory governance UI"))}
                  type="button"
                >
                  停用
                </button>
                <button
                  disabled={Boolean(governanceBusy) || note.status === "archived"}
                  onClick={() => void runGovernanceAction("归档长期记忆", () => archiveDurableMemory(note.filename, "Archived from memory governance UI"))}
                  type="button"
                >
                  归档
                </button>
                <button
                  className="memory-action-button--danger"
                  disabled={Boolean(governanceBusy)}
                  onClick={() => void deleteMemoryNote(note.filename, "card")}
                  type="button"
                >
                  删除
                </button>
              </div>
            </article>
          )) : (
            <article className="workspace-record">
              <h3>没有匹配的长期记忆</h3>
              <p>可以换一个查询词，或先运行一次对话让记忆系统形成更多记录。</p>
            </article>
          )}
        </div>
      </section>
        </>
      ) : null}
    </div>
  );
}
