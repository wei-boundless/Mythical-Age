"use client";

import {
  AlertTriangle,
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
  finalizeWorkingMemoryTaskRun,
  getDurableMemoryNote,
  getExperimentTurnMemoryTrace,
  getSessionHistory,
  getMemoryOverview,
  getTaskDurableMemoryOverview,
  getWorkingMemoryItem,
  getWorkingMemoryOverview,
  getSessionMemoryFiles,
  governWorkingMemoryItem,
  markTaskDurableGlobalCandidate,
  mergeDurableMemories,
  promoteTaskDurableToGlobal,
  promoteWorkingMemoryToTaskDurable,
  recallMemoryPreview,
  type DurableMemoryNoteDetail,
  type ExperimentTurnMemoryTrace,
  type MemoryHeader,
  type MemoryOverview,
  type MemoryRecallPreview,
  type MemorySessionFile,
  type MemoryTraceSection,
  type TaskDurableMemoryOverview,
  type ToolCall,
  type WorkingMemoryItem,
  type WorkingMemoryItemDetail,
  type WorkingMemoryFinalizationResult,
  type WorkingMemoryOverview,
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

function formatIsoTimestamp(value: string) {
  if (!value) {
    return "未记录";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString("zh-CN", {
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

type MemoryLayer = "conversation" | "state" | "working" | "task-durable" | "durable";
type DurableStatusFilter = "all" | "active" | "inactive" | "archived" | "deprecated";
type WorkingStatusFilter = "all" | "draft" | "proposed" | "accepted" | "conflicted" | "archived" | "promoted" | "discarded";

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
    key: "working",
    title: "工作记忆",
    subtitle: "看任务图节点的工作状态池",
    icon: GitBranch
  },
  {
    key: "task-durable",
    title: "任务长期记忆",
    subtitle: "按任务命名空间沉淀资产",
    icon: Database
  },
  {
    key: "durable",
    title: "全局长期记忆",
    subtitle: "治理跨任务稳定记录",
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
  const [linkedMemoryTrace, setLinkedMemoryTrace] = useState<ExperimentTurnMemoryTrace | null>(null);
  const [linkedMemoryTraceStatus, setLinkedMemoryTraceStatus] = useState("");
  const [linkedMemoryTraceLoading, setLinkedMemoryTraceLoading] = useState(false);
  const [sessionMemoryFiles, setSessionMemoryFiles] = useState<MemorySessionFile[]>([]);
  const [selectedSessionMemoryPath, setSelectedSessionMemoryPath] = useState("");
  const [sessionMemoryFilesLoading, setSessionMemoryFilesLoading] = useState(false);
  const [sessionMemoryFilesError, setSessionMemoryFilesError] = useState("");
  const [workingMemory, setWorkingMemory] = useState<WorkingMemoryOverview | null>(null);
  const [workingMemoryLoading, setWorkingMemoryLoading] = useState(false);
  const [workingMemoryError, setWorkingMemoryError] = useState("");
  const [workingStatusFilter, setWorkingStatusFilter] = useState<WorkingStatusFilter>("all");
  const [workingKindFilter, setWorkingKindFilter] = useState("");
  const [workingTaskRunFilter, setWorkingTaskRunFilter] = useState("");
  const [selectedWorkingMemoryId, setSelectedWorkingMemoryId] = useState("");
  const [selectedWorkingMemoryDetail, setSelectedWorkingMemoryDetail] = useState<WorkingMemoryItemDetail | null>(null);
  const [workingMemoryDetailLoading, setWorkingMemoryDetailLoading] = useState(false);
  const [workingMemoryFinalizing, setWorkingMemoryFinalizing] = useState(false);
  const [workingMemoryFinalization, setWorkingMemoryFinalization] = useState<WorkingMemoryFinalizationResult | null>(null);
  const [workingMemoryPromoting, setWorkingMemoryPromoting] = useState(false);
  const [taskDurableMemory, setTaskDurableMemory] = useState<TaskDurableMemoryOverview | null>(null);
  const [taskDurableMemoryLoading, setTaskDurableMemoryLoading] = useState(false);
  const [taskDurableMemoryError, setTaskDurableMemoryError] = useState("");
  const [taskDurableMemoryBusy, setTaskDurableMemoryBusy] = useState("");
  const [workingMemoryGovernanceBusy, setWorkingMemoryGovernanceBusy] = useState("");
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

  const workingMemorySource = workingMemory ?? overview?.working_memory ?? null;
  const taskDurableMemorySource = taskDurableMemory ?? overview?.task_durable_memory ?? null;
  const workingKindOptions = useMemo(
    () => Object.keys(workingMemorySource?.by_kind ?? {}).filter(Boolean).sort(),
    [workingMemorySource?.by_kind]
  );
  const workingTaskRunOptions = useMemo(
    () => workingMemorySource?.active_run_ids ?? [],
    [workingMemorySource?.active_run_ids]
  );
  const filteredWorkingItems = useMemo(() => {
    const items = workingMemorySource?.items ?? [];
    const normalized = query.trim().toLowerCase();
    return items.filter((item) => {
      if (workingStatusFilter !== "all" && item.status !== workingStatusFilter) {
        return false;
      }
      if (workingKindFilter && item.kind !== workingKindFilter) {
        return false;
      }
      if (workingTaskRunFilter && item.task_run_id !== workingTaskRunFilter) {
        return false;
      }
      if (!normalized) {
        return true;
      }
      return [
        item.title,
        item.summary,
        item.kind,
        item.memory_semantics,
        item.status,
        item.visibility,
        item.task_run_id,
        item.graph_id,
        item.owner_node_id,
        item.node_run_id,
        item.writer_agent_id,
        item.payload_preview,
        item.tags.join(" ")
      ].join(" ").toLowerCase().includes(normalized);
    });
  }, [query, workingKindFilter, workingMemorySource?.items, workingStatusFilter, workingTaskRunFilter]);

  const visibleHeaders = filteredHeaders.slice(0, 18);
  const visibleWorkingItems = filteredWorkingItems.slice(0, 80);
  const visibleTaskDurableItems = (taskDurableMemorySource?.items ?? []).slice(0, 80);
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
  const workingStatusStats = useMemo(() => {
    const stats = workingMemorySource?.by_status ?? {};
    return {
      draft: stats.draft ?? 0,
      proposed: stats.proposed ?? 0,
      accepted: stats.accepted ?? 0,
      conflicted: stats.conflicted ?? 0,
      archived: stats.archived ?? 0,
      promoted: stats.promoted ?? 0,
      discarded: stats.discarded ?? 0
    };
  }, [workingMemorySource?.by_status]);
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

  const loadWorkingMemory = useCallback(async () => {
    setWorkingMemoryLoading(true);
    setWorkingMemoryError("");
    try {
      const payload = await getWorkingMemoryOverview({
        task_run_id: workingTaskRunFilter || undefined,
        status: workingStatusFilter === "all" ? undefined : workingStatusFilter,
        kind: workingKindFilter || undefined,
        query: query.trim() || undefined,
        limit: 220
      });
      setWorkingMemory(payload);
    } catch (exc) {
      setWorkingMemoryError(exc instanceof Error ? exc.message : "工作记忆读取失败");
    } finally {
      setWorkingMemoryLoading(false);
    }
  }, [query, workingKindFilter, workingStatusFilter, workingTaskRunFilter]);

  const loadTaskDurableMemory = useCallback(async () => {
    setTaskDurableMemoryLoading(true);
    setTaskDurableMemoryError("");
    try {
      const payload = await getTaskDurableMemoryOverview({
        query: query.trim() || undefined,
        limit: 220
      });
      setTaskDurableMemory(payload);
    } catch (exc) {
      setTaskDurableMemoryError(exc instanceof Error ? exc.message : "任务长期记忆读取失败");
    } finally {
      setTaskDurableMemoryLoading(false);
    }
  }, [query]);

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
    if (activeLayer !== "working") {
      return;
    }
    void loadWorkingMemory();
  }, [activeLayer, loadWorkingMemory]);

  useEffect(() => {
    if (activeLayer !== "task-durable") {
      return;
    }
    void loadTaskDurableMemory();
  }, [activeLayer, loadTaskDurableMemory]);

  useEffect(() => {
    setExpandedMessageIds([]);
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

  async function inspectWorkingItem(item: WorkingMemoryItem) {
    setSelectedWorkingMemoryId(item.work_memory_id);
    setWorkingMemoryDetailLoading(true);
    setWorkingMemoryError("");
    try {
      const payload = await getWorkingMemoryItem(item.work_memory_id);
      setSelectedWorkingMemoryDetail(payload);
    } catch (exc) {
      setSelectedWorkingMemoryDetail(null);
      setWorkingMemoryError(exc instanceof Error ? exc.message : "工作记忆明细读取失败");
    } finally {
      setWorkingMemoryDetailLoading(false);
    }
  }

  async function finalizeSelectedWorkingRun() {
    const taskRunId = workingTaskRunFilter || selectedWorkingMemoryDetail?.item.task_run_id || visibleWorkingItems[0]?.task_run_id || "";
    if (!taskRunId) {
      setWorkingMemoryError("请先选择一个 task_run，再执行工作记忆收束。");
      return;
    }
    const confirmed = window.confirm(
      `确认收束工作记忆运行「${taskRunId}」吗？\n\n这只会归档/废弃 Working Memory 内部条目，并生成待晋升候选；不会自动写入长期记忆。`
    );
    if (!confirmed) {
      return;
    }
    setWorkingMemoryFinalizing(true);
    setWorkingMemoryError("");
    try {
      const payload = await finalizeWorkingMemoryTaskRun(taskRunId, {
        actor_id: "memory_governance_ui",
        terminal_reason: "manual_finalize_from_memory_view",
        policy: {
          discard_unaccepted_candidates: true,
          mark_conflicts_for_health_review: true
        }
      });
      setWorkingMemoryFinalization(payload.result);
      await loadWorkingMemory();
      if (selectedWorkingMemoryId) {
        try {
          const detail = await getWorkingMemoryItem(selectedWorkingMemoryId);
          setSelectedWorkingMemoryDetail(detail);
        } catch {
          setSelectedWorkingMemoryDetail(null);
        }
      }
    } catch (exc) {
      setWorkingMemoryError(exc instanceof Error ? exc.message : "工作记忆收束失败");
    } finally {
      setWorkingMemoryFinalizing(false);
    }
  }

  function canPromoteWorkingItem(item: WorkingMemoryItem) {
    return (
      ["candidate", "needs_review", "approved"].includes(item.promotion_state)
      || item.kind === "promotion_candidate"
    ) && item.promotion_state !== "promoted_to_task_durable";
  }

  async function promoteSelectedWorkingItem() {
    const detail = selectedWorkingMemoryDetail;
    if (!detail) {
      setWorkingMemoryError("请先选择一条待晋升的工作记忆。");
      return;
    }
    if (!canPromoteWorkingItem(detail.item)) {
      setWorkingMemoryError("这条工作记忆不是任务长期记忆晋升候选。");
      return;
    }
    const confirmed = window.confirm(
      `确认将工作记忆「${detail.item.title || detail.item.summary || detail.item.work_memory_id}」晋升为任务长期记忆吗？\n\n这会写入独立的任务长期记忆库，不会污染全局长期记忆；如需进入全局长期记忆，后续需要二次治理。`
    );
    if (!confirmed) {
      return;
    }
    setWorkingMemoryPromoting(true);
    setWorkingMemoryError("");
    setGovernanceMessage("");
    try {
      const canonical = detail.item.summary || detail.item.payload_preview || detail.item.work_memory_id;
      const payload = await promoteWorkingMemoryToTaskDurable(detail.item.work_memory_id, {
        title: detail.item.title || detail.item.summary || `工作记忆晋升：${detail.item.kind}`,
        canonical_statement: canonical,
        summary: detail.item.summary || canonical,
        task_id: detail.item.task_id,
        graph_id: detail.item.graph_id,
        memory_type: "project",
        memory_class: "work",
        retrieval_hints: [
          detail.item.task_id,
          detail.item.graph_id,
          detail.item.owner_node_id,
          detail.item.kind,
          detail.item.memory_semantics
        ].filter(Boolean),
        confidence: "medium",
        actor_id: "memory_governance_ui",
        reason: "Manual promotion from working memory detail"
      });
      setGovernanceMessage(`工作记忆已晋升为任务长期记忆：${payload.task_memory.task_memory_id}`);
      await loadWorkingMemory();
      await loadTaskDurableMemory();
      await loadOverview();
      const refreshed = await getWorkingMemoryItem(detail.item.work_memory_id);
      setSelectedWorkingMemoryDetail(refreshed);
    } catch (exc) {
      setWorkingMemoryError(exc instanceof Error ? exc.message : "工作记忆晋升失败");
    } finally {
      setWorkingMemoryPromoting(false);
    }
  }

  async function markTaskMemoryAsGlobalCandidate(taskMemoryId: string) {
    setTaskDurableMemoryBusy(taskMemoryId);
    setTaskDurableMemoryError("");
    try {
      await markTaskDurableGlobalCandidate(taskMemoryId, {
        actor_id: "memory_governance_ui",
        reason: "Manual candidate mark from task durable memory view"
      });
      await loadTaskDurableMemory();
      await loadOverview();
    } catch (exc) {
      setTaskDurableMemoryError(exc instanceof Error ? exc.message : "全局候选标记失败");
    } finally {
      setTaskDurableMemoryBusy("");
    }
  }

  async function promoteTaskMemoryToGlobal(item: { task_memory_id: string; title: string; canonical_statement: string; summary: string }) {
    const confirmed = window.confirm(
      `确认将任务长期记忆「${item.title || item.task_memory_id}」晋升为全局长期记忆吗？\n\n这会进入主 Agent / 用户 / 系统级长期记忆，并可能影响其他任务。只有跨任务稳定规则才应该执行。`
    );
    if (!confirmed) {
      return;
    }
    setTaskDurableMemoryBusy(item.task_memory_id);
    setTaskDurableMemoryError("");
    try {
      await promoteTaskDurableToGlobal(item.task_memory_id, {
        title: item.title,
        canonical_statement: item.canonical_statement || item.summary,
        summary: item.summary,
        global_kind: "cross_task_policy",
        actor_id: "memory_governance_ui",
        reason: "Manual global promotion from task durable memory view"
      });
      await loadTaskDurableMemory();
      await loadOverview();
    } catch (exc) {
      setTaskDurableMemoryError(exc instanceof Error ? exc.message : "全局长期记忆晋升失败");
    } finally {
      setTaskDurableMemoryBusy("");
    }
  }

  async function runWorkingMemoryGovernance(action: "accept" | "discard" | "conflict") {
    const detail = selectedWorkingMemoryDetail;
    if (!detail) {
      setWorkingMemoryError("请先选择一条工作记忆。");
      return;
    }
    const labels = {
      accept: "采纳",
      discard: "废弃",
      conflict: "标记冲突"
    };
    const confirmed = window.confirm(
      `确认${labels[action]}工作记忆「${detail.item.title || detail.item.summary || detail.item.work_memory_id}」吗？\n\n这个动作只改变 Working Memory 生命周期，不会写入长期记忆。`
    );
    if (!confirmed) {
      return;
    }
    setWorkingMemoryGovernanceBusy(action);
    setWorkingMemoryError("");
    setGovernanceMessage("");
    try {
      await governWorkingMemoryItem(detail.item.work_memory_id, action, {
        actor_id: "memory_governance_ui",
        reason: `Manual working memory ${action} from memory view`,
        metadata: {
          source: "MemoryView"
        }
      });
      setGovernanceMessage(`工作记忆已${labels[action]}。`);
      await loadWorkingMemory();
      const refreshed = await getWorkingMemoryItem(detail.item.work_memory_id);
      setSelectedWorkingMemoryDetail(refreshed);
    } catch (exc) {
      setWorkingMemoryError(exc instanceof Error ? exc.message : `工作记忆${labels[action]}失败`);
    } finally {
      setWorkingMemoryGovernanceBusy("");
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
            对话记忆看单轮现场，状态记忆看 session 上下文，工作记忆看任务图节点的生产状态，
            长期记忆查 durable memory。四层分开浏览，避免草稿、状态和稳定知识互相污染。
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
            <span>上下文装配</span>
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
              {memoryInspectorTarget.turnIndex ? `第 ${memoryInspectorTarget.turnIndex} 轮` : "指定记忆目标"}
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
            <span><b>{linkedMemoryTrace?.prompt_injection.section_count ?? 0}</b> 装配片段</span>
            <span><b>{linkedTurnContext?.status === "passed" ? "通过" : linkedTurnContext?.status === "failed" ? "失败" : "未知"}</b> 测试状态</span>
          </div>
          <div className="memory-inspector-focus__actions">
            <button className={activeLayer === "conversation" ? "memory-inspector-focus__active" : ""} onClick={() => setActiveLayer("conversation")} type="button">
              看对话现场
            </button>
            <button className={activeLayer === "state" ? "memory-inspector-focus__active" : ""} onClick={() => setActiveLayer("state")} type="button">
              看状态记忆
            </button>
            <button className={activeLayer === "working" ? "memory-inspector-focus__active" : ""} onClick={() => setActiveLayer("working")} type="button">
              看工作记忆
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
            <section className="workspace-section memory-management-panel">
              <div className="workspace-section__head">
                <GitBranch size={18} />
                <h3>测试轮次对话定位</h3>
                {memoryInspectorTarget.turnIndex ? <span className="tag-chip">第 {memoryInspectorTarget.turnIndex} 轮</span> : null}
                <span className="tag-chip">{linkedMemoryTrace ? "已连接" : linkedMemoryTraceLoading ? "加载中" : "未命中"}</span>
              </div>
              {linkedMemoryTrace ? (
                <div className="memory-management-panel__grid">
                  <article>
                    <span>用户输入</span>
                    <strong>{linkedTurnContext?.session_alias || "测试系统跳转"}</strong>
                    <p>{compactText(linkedTurnContext?.user_input || memoryInspectorTarget.reason || "该轮测试记录没有用户输入。", 260)}</p>
                  </article>
                  <article>
                    <span>助手输出</span>
                    <strong>{linkedTurnContext?.status === "passed" ? "测试通过" : linkedTurnContext?.status === "failed" ? "测试失败" : "状态未知"}</strong>
                    <p>{compactText(linkedTurnContext?.assistant_output || "该轮测试记录没有助手输出。", 260)}</p>
                  </article>
                  <article>
                    <span>记忆摘要</span>
                    <strong>{linkedMemoryTrace.summary || "暂无摘要"}</strong>
                    <p>{traceItemsText(linkedSessionSections, "这一轮没有状态记忆片段进入模型上下文。")}</p>
                  </article>
                </div>
              ) : (
                <article className="workspace-record">
                  <h3>{linkedMemoryTraceLoading ? "正在读取测试轮次" : "这一轮没有可用记忆链路"}</h3>
                  <p>{linkedMemoryTraceStatus || "可以回到测试系统选择带有记忆标记的轮次。"}</p>
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
                <p>用于核对真实对话、工具调用、压缩上下文和会话标题。</p>
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
                <p>批量展开所有轮次，或单独点击某一轮查看状态记忆、长期召回和上下文装配。</p>
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
              <span className="tag-chip">{filteredConversationItems.length}/{conversationItems.length} 轮</span>
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
                      className="memory-dialogue-turn__head"
                      onClick={() => toggleConversationItem(item.id)}
                      type="button"
                    >
                      <span>{item.index}</span>
                      <strong>{item.role === "user" ? "用户输入" : "助手回应"}</strong>
                      <em>{compactText(item.content, 120)}</em>
                      {item.toolCalls.length ? <i>{item.toolCalls.length} 个工具</i> : null}
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
                                  工具 {toolIndex + 1}: {toolCall.tool || "未知工具"}
                                </summary>
                                <pre>{compactText(`输入：\n${toolCall.input || "空"}\n\n输出：\n${toolCall.output || "空"}`, 1800)}</pre>
                              </details>
                            ))}
                          </div>
                        ) : null}
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

        </>
      ) : null}

      {activeLayer === "working" ? (
        <>
          <div className="workspace-search memory-search">
            <Search size={17} />
            <input
              aria-label="搜索工作记忆"
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  void loadWorkingMemory();
                }
              }}
              placeholder="搜索 task_run、节点、Agent、kind、摘要或 payload"
              value={query}
            />
            <button className="action-button action-button--ghost" onClick={() => void loadWorkingMemory()} type="button">
              {workingMemoryLoading ? <Loader2 className="animate-spin" size={15} /> : <RefreshCw size={15} />}
              刷新工作记忆
            </button>
          </div>

          {workingMemoryError ? <div className="workspace-alert">{workingMemoryError}</div> : null}

          <section className="workspace-section memory-working-console">
            <div className="workspace-section__head">
              <GitBranch size={18} />
              <h3>工作记忆总览</h3>
              <span className="tag-chip">{workingMemorySource ? `${workingMemorySource.total} 条` : "待读取"}</span>
              <span className="tag-chip">{workingMemorySource?.read_logs.length ?? 0} read logs</span>
              <span className="tag-chip">{workingMemorySource?.handoff_transactions.length ?? 0} handoff</span>
            </div>
            <div className="memory-working-metrics">
              <article>
                <span>已采纳</span>
                <strong>{workingStatusStats.accepted}</strong>
                <p>可进入下游 required context 的工作事实。</p>
              </article>
              <article>
                <span>候选 / 草稿</span>
                <strong>{workingStatusStats.proposed + workingStatusStats.draft}</strong>
                <p>仍需 RunLoop、协调者或人工 gate 裁定。</p>
              </article>
              <article>
                <span>冲突</span>
                <strong>{workingMemorySource?.conflict_items.length ?? 0}</strong>
                <p>默认不应直接进入下游上下文。</p>
              </article>
              <article>
                <span>待晋升</span>
                <strong>{workingMemorySource?.promotion_candidates.length ?? 0}</strong>
                <p>只能经治理进入长期记忆或产物库。</p>
              </article>
            </div>
          </section>

          <section className="workspace-section memory-working-console">
            <div className="workspace-section__head">
              <ShieldCheck size={18} />
              <h3>浏览过滤</h3>
              <span className="tag-chip">{filteredWorkingItems.length} matched</span>
            </div>
            <div className="memory-working-filters">
              <label>
                <span>任务运行</span>
                <select onChange={(event) => setWorkingTaskRunFilter(event.target.value)} value={workingTaskRunFilter}>
                  <option value="">全部 task_run</option>
                  {workingTaskRunOptions.map((runId) => (
                    <option key={runId} value={runId}>{runId}</option>
                  ))}
                </select>
              </label>
              <label>
                <span>状态</span>
                <select onChange={(event) => setWorkingStatusFilter(event.target.value as WorkingStatusFilter)} value={workingStatusFilter}>
                  <option value="all">全部状态</option>
                  <option value="draft">draft ({workingStatusStats.draft})</option>
                  <option value="proposed">proposed ({workingStatusStats.proposed})</option>
                  <option value="accepted">accepted ({workingStatusStats.accepted})</option>
                  <option value="conflicted">conflicted ({workingStatusStats.conflicted})</option>
                  <option value="archived">archived ({workingStatusStats.archived})</option>
                  <option value="promoted">promoted ({workingStatusStats.promoted})</option>
                  <option value="discarded">discarded ({workingStatusStats.discarded})</option>
                </select>
              </label>
              <label>
                <span>Kind</span>
                <select onChange={(event) => setWorkingKindFilter(event.target.value)} value={workingKindFilter}>
                  <option value="">全部 kind</option>
                  {workingKindOptions.map((kind) => (
                    <option key={kind} value={kind}>{kind} ({workingMemorySource?.by_kind[kind] ?? 0})</option>
                  ))}
                </select>
              </label>
            </div>
          </section>

          <section className="workspace-section memory-working-console">
            <div className="workspace-section__head">
              <ShieldCheck size={18} />
              <h3>任务运行收束</h3>
              <span className="tag-chip">Working Memory only</span>
              <span className="tag-chip">不自动写长期记忆</span>
              <button
                className="action-button action-button--primary"
                disabled={workingMemoryFinalizing || !(workingTaskRunFilter || selectedWorkingMemoryDetail?.item.task_run_id || visibleWorkingItems[0]?.task_run_id)}
                onClick={() => void finalizeSelectedWorkingRun()}
                type="button"
              >
                {workingMemoryFinalizing ? <Loader2 className="animate-spin" size={14} /> : <ShieldCheck size={14} />}
                收束当前 task_run
              </button>
            </div>
            <div className="memory-working-finalizer">
              <article>
                <span>当前目标</span>
                <strong>{workingTaskRunFilter || selectedWorkingMemoryDetail?.item.task_run_id || visibleWorkingItems[0]?.task_run_id || "未选择 task_run"}</strong>
                <p>收束会把未采纳候选废弃、已采纳工作事实归档、冲突保留为审查候选、晋升项标为 needs_review。</p>
              </article>
              {workingMemoryFinalization ? (
                <article className="memory-working-finalizer__report">
                  <span>最近收束报告</span>
                  <strong>{workingMemoryFinalization.finalized_count} 条已处理</strong>
                  <p>
                    归档 {workingMemoryFinalization.archived_count} · 废弃 {workingMemoryFinalization.discarded_count} ·
                    待晋升 {workingMemoryFinalization.promotion_candidate_count} · 产物候选 {workingMemoryFinalization.artifact_candidate_count} ·
                    冲突 {workingMemoryFinalization.unresolved_conflict_count}
                  </p>
                  <small>{workingMemoryFinalization.archive_report_path}</small>
                </article>
              ) : (
                <article>
                  <span>最近收束报告</span>
                  <strong>尚未执行</strong>
                  <p>完成一次收束后，这里会显示分流统计和报告路径。</p>
                </article>
              )}
            </div>
          </section>

          <section className="workspace-section memory-working-console">
            <div className="workspace-section__head">
              <GitBranch size={18} />
              <h3>任务图节点工作记忆</h3>
              <span className="tag-chip">owner_node 归属</span>
              <span className="tag-chip">Agent 仅审计</span>
            </div>
            <div className="memory-working-layout">
              <aside className="memory-working-list" aria-label="工作记忆条目列表">
                {workingMemoryLoading ? (
                  <article className="workspace-record">
                    <h3>正在读取工作记忆</h3>
                    <p>从后端 WorkingMemoryStore 加载任务运行状态。</p>
                  </article>
                ) : visibleWorkingItems.length ? visibleWorkingItems.map((item) => (
                  <button
                    className={`memory-working-row memory-working-row--${item.status} ${selectedWorkingMemoryId === item.work_memory_id ? "memory-working-row--active" : ""}`}
                    key={item.work_memory_id}
                    onClick={() => void inspectWorkingItem(item)}
                    type="button"
                  >
                    <span>{item.status} · {item.kind}</span>
                    <strong>{item.title || item.summary || item.work_memory_id}</strong>
                    <em>{compactText(item.summary || item.payload_preview || "没有摘要", 130)}</em>
                    <small>{item.owner_node_id || "unknown-node"} / {item.node_run_id || "no-run"} / {item.writer_agent_id || "no-agent"}</small>
                  </button>
                )) : (
                  <article className="workspace-record">
                    <h3>没有工作记忆条目</h3>
                    <p>当前过滤条件没有命中。运行任务图或提交工作记忆候选后，这里会出现节点归属的工作状态。</p>
                  </article>
                )}
              </aside>

              <article className="memory-working-detail">
                {workingMemoryDetailLoading ? (
                  <div className="workspace-record">
                    <h3>正在读取工作记忆明细</h3>
                    <p>{selectedWorkingMemoryId}</p>
                  </div>
                ) : selectedWorkingMemoryDetail ? (
                  <>
                    <span>{selectedWorkingMemoryDetail.item.task_run_id}</span>
                    <strong>{selectedWorkingMemoryDetail.item.title || selectedWorkingMemoryDetail.item.work_memory_id}</strong>
                    <div className="memory-working-badges">
                      <b>{selectedWorkingMemoryDetail.item.status}</b>
                      <b>{selectedWorkingMemoryDetail.item.visibility}</b>
                      <b>{selectedWorkingMemoryDetail.item.scope}</b>
                      <b>{selectedWorkingMemoryDetail.item.memory_semantics}</b>
                      <b>v{selectedWorkingMemoryDetail.item.version}</b>
                    </div>
                    <div className="memory-working-kv">
                      <span>归属节点</span>
                      <strong>{selectedWorkingMemoryDetail.item.owner_node_id || "未指定"}</strong>
                      <span>节点运行</span>
                      <strong>{selectedWorkingMemoryDetail.item.node_run_id || "未指定"}</strong>
                      <span>尝试</span>
                      <strong>{selectedWorkingMemoryDetail.item.run_attempt_id || "未指定"}</strong>
                      <span>写入 Agent</span>
                      <strong>{selectedWorkingMemoryDetail.item.writer_agent_id || "未指定"}</strong>
                      <span>晋升状态</span>
                      <strong>{selectedWorkingMemoryDetail.item.promotion_state}</strong>
                      <span>创建时间</span>
                      <strong>{formatIsoTimestamp(selectedWorkingMemoryDetail.item.created_at)}</strong>
                    </div>
                    <div className="memory-working-detail__actions">
                      <button
                        className="action-button action-button--muted"
                        disabled={Boolean(workingMemoryGovernanceBusy) || selectedWorkingMemoryDetail.item.status === "accepted"}
                        onClick={() => void runWorkingMemoryGovernance("accept")}
                        type="button"
                      >
                        {workingMemoryGovernanceBusy === "accept" ? <Loader2 className="animate-spin" size={14} /> : <ShieldCheck size={14} />}
                        采纳
                      </button>
                      <button
                        className="action-button action-button--muted"
                        disabled={Boolean(workingMemoryGovernanceBusy) || selectedWorkingMemoryDetail.item.status === "conflicted"}
                        onClick={() => void runWorkingMemoryGovernance("conflict")}
                        type="button"
                      >
                        {workingMemoryGovernanceBusy === "conflict" ? <Loader2 className="animate-spin" size={14} /> : <AlertTriangle size={14} />}
                        标冲突
                      </button>
                      <button
                        className="action-button action-button--ghost"
                        disabled={Boolean(workingMemoryGovernanceBusy) || selectedWorkingMemoryDetail.item.status === "discarded"}
                        onClick={() => void runWorkingMemoryGovernance("discard")}
                        type="button"
                      >
                        {workingMemoryGovernanceBusy === "discard" ? <Loader2 className="animate-spin" size={14} /> : <Trash2 size={14} />}
                        废弃
                      </button>
                      <button
                        className="action-button action-button--primary"
                        disabled={workingMemoryPromoting || Boolean(workingMemoryGovernanceBusy) || !canPromoteWorkingItem(selectedWorkingMemoryDetail.item)}
                        onClick={() => void promoteSelectedWorkingItem()}
                        type="button"
                      >
                        {workingMemoryPromoting ? <Loader2 className="animate-spin" size={14} /> : <ShieldCheck size={14} />}
                        晋升任务长期记忆
                      </button>
                      {selectedWorkingMemoryDetail.item.promotion_state === "promoted_to_task_durable" ? (
                        <span>这条工作记忆已经进入任务长期记忆库。</span>
                      ) : (
                        <span>只有 candidate / needs_review / approved 或 promotion_candidate 可以人工晋升。</span>
                      )}
                    </div>
                    <pre>{selectedWorkingMemoryDetail.item.payload_preview || selectedWorkingMemoryDetail.item.summary || "没有 payload。"}</pre>
                    <div className="memory-working-trace-grid">
                      <article>
                        <span>动态读取</span>
                        <strong>{selectedWorkingMemoryDetail.read_logs.length} 条</strong>
                        <p>{selectedWorkingMemoryDetail.read_logs[0]?.reader_agent_id || "没有读取日志"}</p>
                      </article>
                      <article>
                        <span>时间关系</span>
                        <strong>{selectedWorkingMemoryDetail.temporal_edges.length} 条</strong>
                        <p>{selectedWorkingMemoryDetail.temporal_edges[0]?.relation || "没有 temporal edge"}</p>
                      </article>
                      <article>
                        <span>交接事务</span>
                        <strong>{selectedWorkingMemoryDetail.handoff_transactions.length} 条</strong>
                        <p>{selectedWorkingMemoryDetail.handoff_transactions[0]?.transaction_status || "没有 handoff transaction"}</p>
                      </article>
                    </div>
                  </>
                ) : (
                  <div className="workspace-record">
                    <h3>选择一条工作记忆</h3>
                    <p>左侧条目会显示任务图节点归属、节点运行实例、写入 Agent 和候选治理状态。</p>
                  </div>
                )}
              </article>
            </div>
          </section>

          <section className="workspace-section memory-working-console">
            <div className="workspace-section__head">
              <AlertTriangle size={18} />
              <h3>治理队列</h3>
              <span className="tag-chip">只读检查</span>
            </div>
            <div className="memory-working-queues">
              <article>
                <span>冲突项</span>
                <strong>{workingMemorySource?.conflict_items.length ?? 0}</strong>
                <p>{workingMemorySource?.conflict_items[0]?.summary || "当前没有冲突工作记忆。"}</p>
              </article>
              <article>
                <span>待晋升项</span>
                <strong>{workingMemorySource?.promotion_candidates.length ?? 0}</strong>
                <p>{workingMemorySource?.promotion_candidates[0]?.summary || "当前没有待晋升任务长期记忆候选。"}</p>
              </article>
              <article>
                <span>归档 / 废弃</span>
                <strong>{workingMemorySource?.archived_items.length ?? 0}</strong>
                <p>任务收束阶段应统一归档、晋升或废弃，不能自动混入全局长期记忆。</p>
              </article>
            </div>
          </section>
        </>
      ) : null}

      {activeLayer === "task-durable" ? (
        <>
          <section className="workspace-section memory-working-console">
            <div className="workspace-section__head">
              <Database size={18} />
              <h3>任务长期记忆库</h3>
              <span className="tag-chip">{taskDurableMemoryLoading ? "读取中" : `${taskDurableMemorySource?.total ?? 0} 条`}</span>
              <button className="action-button action-button--ghost" onClick={() => void loadTaskDurableMemory()} type="button">
                <RefreshCw size={14} />
                刷新
              </button>
            </div>
            {taskDurableMemoryError ? <div className="workspace-alert workspace-alert--danger">{taskDurableMemoryError}</div> : null}
            <div className="workspace-metrics-grid">
              <div className="workspace-stat">
                <Database size={18} />
                <span>命名空间</span>
                <strong>{taskDurableMemorySource?.namespace_count ?? 0}</strong>
              </div>
              <div className="workspace-stat">
                <ShieldCheck size={18} />
                <span>Active</span>
                <strong>{taskDurableMemorySource?.by_status.active ?? 0}</strong>
              </div>
              <div className="workspace-stat">
                <GitBranch size={18} />
                <span>类型</span>
                <strong>{Object.keys(taskDurableMemorySource?.by_kind ?? {}).length}</strong>
              </div>
              <div className="workspace-stat">
                <Sparkles size={18} />
                <span>全局候选</span>
                <strong>{taskDurableMemorySource?.global_promotion_candidates.length ?? 0}</strong>
              </div>
            </div>
          </section>

          <section className="workspace-section memory-durable-reader">
            <div className="workspace-section__head">
              <GitBranch size={18} />
              <h3>按任务命名空间阅读</h3>
              <span className="tag-chip">Working 到 Task Durable 到 Global Durable</span>
            </div>
            <div className="memory-durable-reader__layout">
              <aside className="memory-durable-reader__list">
                {(taskDurableMemorySource?.namespaces ?? []).length ? (taskDurableMemorySource?.namespaces ?? []).map((namespace) => (
                  <article className="memory-durable-row" key={namespace.namespace_id}>
                    <span>{namespace.item_count} 条 · {formatIsoTimestamp(namespace.updated_at)}</span>
                    <strong>{namespace.namespace_id}</strong>
                    <em>{[namespace.task_family, namespace.domain_id, namespace.task_id, namespace.graph_id, namespace.project_id, namespace.artifact_namespace].filter(Boolean).join(" / ") || "未标注任务域"}</em>
                  </article>
                )) : (
                  <article className="workspace-record">
                    <h3>还没有任务长期记忆命名空间</h3>
                    <p>从工作记忆候选执行“晋升任务长期记忆”后，这里会出现按任务/图隔离的记录。</p>
                  </article>
                )}
              </aside>
              <article className="memory-durable-reader__detail">
                {visibleTaskDurableItems.length ? visibleTaskDurableItems.map((item) => (
                  <div className="workspace-record" key={item.task_memory_id}>
                    <span>{item.namespace_id} · {item.status} · {item.memory_class}/{item.memory_type}</span>
                    <h3>{item.title || item.task_memory_id}</h3>
                    <p>{item.canonical_statement || item.summary}</p>
                    <p>来源工作记忆：{item.source_work_memory_ids.join(" / ") || "未记录"}</p>
                    <div className="memory-durable-reader__actions">
                      <button
                        disabled={taskDurableMemoryBusy === item.task_memory_id || item.global_promotion_state === "candidate"}
                        onClick={() => void markTaskMemoryAsGlobalCandidate(item.task_memory_id)}
                        type="button"
                      >
                        提交全局候选
                      </button>
                      <button
                        disabled={taskDurableMemoryBusy === item.task_memory_id || item.global_promotion_state !== "candidate"}
                        onClick={() => void promoteTaskMemoryToGlobal(item)}
                        type="button"
                      >
                        晋升全局长期记忆
                      </button>
                    </div>
                  </div>
                )) : (
                  <div className="workspace-record">
                    <h3>没有可读任务长期记忆</h3>
                    <p>这层只保存任务资产，不等同于全局长期记忆。</p>
                  </div>
                )}
              </article>
            </div>
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
