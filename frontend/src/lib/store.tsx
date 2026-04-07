"use client";

import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import {
  compressSession,
  createSession,
  deleteSession,
  getRagMode,
  getSessionHistory,
  getSessionTokens,
  listSessions,
  listSkills,
  loadFile,
  renameSession,
  saveFile,
  setRagMode,
  streamChat,
  type RetrievalResult,
  type SessionSummary,
  type ToolCall
} from "@/lib/api";

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  toolCalls: ToolCall[];
  retrievals: RetrievalResult[];
};

function appendMessageContent(base: string, extra: string) {
  if (!extra.trim()) {
    return base;
  }
  if (!base.trim()) {
    return extra;
  }
  return `${base}\n\n${extra}`;
}

function isInternalSkillRead(toolCall: ToolCall) {
  const toolName = (toolCall.tool || "").toLowerCase();
  const io = `${toolCall.input ?? ""}\n${toolCall.output ?? ""}`.toLowerCase();
  return (
    toolName === "read_file" &&
    io.includes("skills/") &&
    io.includes("/skill.md")
  );
}

function looksLikeSkillDocument(text: string) {
  const normalized = (text || "").trim();
  if (!normalized) {
    return false;
  }
  const lowered = normalized.toLowerCase();
  const hasSkillFrontmatter =
    (normalized.startsWith("---") || lowered.startsWith("name:")) &&
    lowered.includes("metadata:") &&
    lowered.includes("description:");
  const hasSkillSections =
    lowered.includes("display_name:") &&
    (
      lowered.includes("## execution steps") ||
      lowered.includes("## output format") ||
      lowered.includes("鐩爣") ||
      lowered.includes("鎵ц姝ラ") ||
      lowered.includes("杈撳嚭鏍煎紡") ||
      lowered.includes("鏁呴殰鎺掓煡") ||
      lowered.includes("鏌ヨ绛栫暐")
    );
  return hasSkillFrontmatter || hasSkillSections;
}

function looksLikeSkillDocumentPrefix(text: string) {
  const normalized = (text || "").trim();
  if (!normalized) {
    return false;
  }
  const lowered = normalized.toLowerCase();
  return (
    lowered.startsWith("name:") ||
    lowered.startsWith("---") ||
    (lowered.includes("metadata:") && lowered.includes("description:"))
  );
}

function sanitizeToolCall(toolCall: ToolCall): ToolCall | null {
  if (isInternalSkillRead(toolCall)) {
    return null;
  }

  const input = String(toolCall.input ?? "");
  const output = String(toolCall.output ?? "");
  const inputIsSkill = looksLikeSkillDocument(input);
  const outputIsSkill = looksLikeSkillDocument(output);

  if ((inputIsSkill && !output.trim()) || (inputIsSkill && outputIsSkill)) {
    return null;
  }

  return {
    ...toolCall,
    input: inputIsSkill ? "[internal skill instructions hidden]" : input,
    output: outputIsSkill ? "[internal skill instructions hidden]" : output
  };
}

type TokenStats = {
  system_tokens: number;
  message_tokens: number;
  total_tokens: number;
};

type AppStore = {
  sessions: SessionSummary[];
  currentSessionId: string | null;
  messages: Message[];
  isStreaming: boolean;
  ragMode: boolean;
  skills: Array<{ name: string; title: string; description: string; path: string }>;
  editableFiles: string[];
  inspectorPath: string;
  inspectorContent: string;
  inspectorDirty: boolean;
  sidebarWidth: number;
  inspectorWidth: number;
  tokenStats: TokenStats | null;
  createNewSession: () => Promise<void>;
  selectSession: (sessionId: string) => Promise<void>;
  sendMessage: (value: string) => Promise<void>;
  toggleRagMode: () => Promise<void>;
  renameCurrentSession: (title: string) => Promise<void>;
  removeSession: (sessionId: string) => Promise<void>;
  loadInspectorFile: (path: string) => Promise<void>;
  updateInspectorContent: (value: string) => void;
  saveInspector: () => Promise<void>;
  compressCurrentSession: () => Promise<void>;
  setSidebarWidth: (width: number) => void;
  setInspectorWidth: (width: number) => void;
};

const FIXED_FILES = [
  "workspace/SOUL.md",
  "workspace/IDENTITY.md",
  "workspace/USER.md",
  "workspace/AGENTS.md",
  "durable_memory/MEMORY.md",
  "SKILLS_SNAPSHOT.md"
];

const StoreContext = createContext<AppStore | null>(null);

function makeId() {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function toUiMessages(history: Awaited<ReturnType<typeof getSessionHistory>>["messages"]) {
  const normalized = history
    .map<Message | null>((message) => {
      const toolCalls = (message.tool_calls ?? [])
        .map(sanitizeToolCall)
        .filter((toolCall): toolCall is ToolCall => Boolean(toolCall));
      const content = message.content ?? "";
      if (
        message.role === "assistant" &&
        looksLikeSkillDocument(content) &&
        toolCalls.length === 0
      ) {
        return null;
      }
      if (
        message.role === "assistant" &&
        !content.trim() &&
        toolCalls.length === 0
      ) {
        return null;
      }
      return {
        id: makeId(),
        role: message.role,
        content,
        toolCalls,
        retrievals: []
      };
    })
    .filter(Boolean) as Message[];

  const merged: Message[] = [];
  for (const message of normalized) {
    const previous = merged[merged.length - 1];
    if (message.role === "assistant" && previous?.role === "assistant") {
      previous.content = appendMessageContent(previous.content, message.content);
      previous.toolCalls = [...previous.toolCalls, ...message.toolCalls];
      previous.retrievals = [...previous.retrievals, ...message.retrievals];
      continue;
    }
    merged.push(message);
  }
  return merged;
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [ragMode, setRagModeState] = useState(false);
  const [skills, setSkills] = useState<
    Array<{ name: string; title: string; description: string; path: string }>
  >([]);
  const [inspectorPath, setInspectorPath] = useState("durable_memory/MEMORY.md");
  const [inspectorContent, setInspectorContent] = useState("");
  const [inspectorDirty, setInspectorDirty] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(308);
  const [inspectorWidth, setInspectorWidth] = useState(360);
  const [tokenStats, setTokenStats] = useState<TokenStats | null>(null);
  const createSessionPromiseRef = useRef<Promise<string> | null>(null);
  const currentSessionIdRef = useRef<string | null>(null);
  const sessionDetailsRequestRef = useRef(0);
  const sessionRefreshTimersRef = useRef<number[]>([]);

  const editableFiles = useMemo(
    () => [...FIXED_FILES, ...skills.map((skill) => skill.path)],
    [skills]
  );

  async function refreshSessions() {
    setSessions(await listSessions());
  }

  async function refreshSkills() {
    setSkills(await listSkills());
  }

  function scheduleSessionRefreshes(delays: number[] = [1500, 4000]) {
    if (typeof window === "undefined") {
      return;
    }

    for (const timer of sessionRefreshTimersRef.current) {
      window.clearTimeout(timer);
    }

    sessionRefreshTimersRef.current = delays.map((delay) =>
      window.setTimeout(() => {
        void refreshSessions();
      }, delay)
    );
  }

  async function refreshSessionDetails(sessionId: string) {
    const requestId = ++sessionDetailsRequestRef.current;
    const [history, tokens] = await Promise.all([
      getSessionHistory(sessionId),
      getSessionTokens(sessionId)
    ]);
    if (currentSessionIdRef.current !== sessionId || sessionDetailsRequestRef.current !== requestId) {
      return;
    }
    setMessages(toUiMessages(history.messages));
    setTokenStats(tokens);
  }

  async function createNewSession() {
    const sessionId = await createFreshSession();
    setCurrentSessionId(sessionId);
    currentSessionIdRef.current = sessionId;
    setMessages([]);
    setTokenStats(null);
    await refreshSessions();
  }

  async function selectSession(sessionId: string) {
    setCurrentSessionId(sessionId);
    currentSessionIdRef.current = sessionId;
    await refreshSessionDetails(sessionId);
  }

  async function ensureSession() {
    if (currentSessionIdRef.current) {
      return currentSessionIdRef.current;
    }
    return createFreshSession();
  }

  async function createFreshSession() {
    if (createSessionPromiseRef.current) {
      return createSessionPromiseRef.current;
    }

    const pending = (async () => {
      const created = await createSession();
      setSessions((prev) => {
        const withoutCreated = prev.filter((session) => session.id !== created.id);
        return [created, ...withoutCreated];
      });
      setCurrentSessionId(created.id);
      currentSessionIdRef.current = created.id;
      setMessages([]);
      setTokenStats(null);
      return created.id;
    })();

    createSessionPromiseRef.current = pending;
    try {
      return await pending;
    } finally {
      createSessionPromiseRef.current = null;
    }
  }

  async function sendMessage(value: string) {
    if (!value.trim() || isStreaming) {
      return;
    }

    const sessionId = await ensureSession();
    const userMessage: Message = {
      id: makeId(),
      role: "user",
      content: value.trim(),
      toolCalls: [],
      retrievals: []
    };
    const assistantMessage: Message = {
      id: makeId(),
      role: "assistant",
      content: "",
      toolCalls: [],
      retrievals: []
    };

    setMessages((prev) => [...prev, userMessage, assistantMessage]);
    setIsStreaming(true);

    let activeAssistantId = assistantMessage.id;
    let hiddenToolCallInFlight = false;

    const patchAssistant = (updater: (message: Message) => Message) => {
      setMessages((prev) =>
        prev.map((message) => (message.id === activeAssistantId ? updater(message) : message))
      );
    };

    try {
      await streamChat(
        { message: value.trim(), session_id: sessionId },
        {
          onEvent(event, data) {
            if (event === "retrieval") {
              patchAssistant((message) => ({
                ...message,
                retrievals: (data.results as RetrievalResult[]) ?? []
              }));
              return;
            }

            if (event === "token") {
              patchAssistant((message) => {
                const nextContent = `${message.content}${String(data.content ?? "")}`;
                if (
                  (!message.content.trim() && looksLikeSkillDocumentPrefix(nextContent)) ||
                  looksLikeSkillDocument(nextContent)
                ) {
                  return message;
                }
                return {
                  ...message,
                  content: nextContent
                };
              });
              return;
            }

            if (event === "tool_start") {
              const rawToolCall = {
                tool: String(data.tool ?? "tool"),
                input: String(data.input ?? ""),
                output: ""
              };
              const isInternalRead = isInternalSkillRead(rawToolCall);
              const toolCall = sanitizeToolCall(rawToolCall);
              hiddenToolCallInFlight = isInternalRead || !toolCall;
              if (hiddenToolCallInFlight) {
                return;
              }
              patchAssistant((message) => ({
                ...message,
                toolCalls: [
                  ...message.toolCalls,
                  ...(toolCall ? [toolCall] : [])
                ]
              }));
              return;
            }

            if (event === "tool_end") {
              if (hiddenToolCallInFlight) {
                hiddenToolCallInFlight = false;
                return;
              }
              patchAssistant((message) => ({
                ...message,
                toolCalls: message.toolCalls.flatMap((toolCall, index, list) => {
                  if (index !== list.length - 1) {
                    return [toolCall];
                  }
                  const sanitized = sanitizeToolCall({
                    ...toolCall,
                    output: String(data.output ?? "")
                  });
                  return sanitized ? [sanitized] : [];
                })
              }));
              return;
            }

            if (event === "new_response") {
              return;
            }

            if (event === "done") {
              const finalContent = String(data.content ?? "");
              patchAssistant((message) =>
                message.content
                  ? message
                  : {
                      ...message,
                      content: finalContent
                    }
              );
              return;
            }

            if (event === "title") {
              void refreshSessions();
              return;
            }

            if (event === "error") {
              patchAssistant((message) => ({
                ...message,
                content:
                  message.content || `Request failed: ${String(data.error ?? "unknown error")}`
              }));
            }
          }
        }
      );
    } finally {
      setIsStreaming(false);
      if (currentSessionIdRef.current === sessionId) {
        await refreshSessionDetails(sessionId);
      }
      await refreshSessions();
      scheduleSessionRefreshes();
    }
  }

  async function toggleRagMode() {
    const next = !ragMode;
    setRagModeState(next);
    try {
      await setRagMode(next);
    } catch (error) {
      setRagModeState(!next);
      throw error;
    }
  }

  async function renameCurrentSession(title: string) {
    if (!currentSessionId || !title.trim()) {
      return;
    }
    await renameSession(currentSessionId, title.trim());
    await refreshSessions();
  }

  async function removeSession(sessionId: string) {
    await deleteSession(sessionId);
    await refreshSessions();
    if (currentSessionId === sessionId) {
      const nextSessions = await listSessions();
      setSessions(nextSessions);
      if (nextSessions.length) {
        setCurrentSessionId(nextSessions[0].id);
        currentSessionIdRef.current = nextSessions[0].id;
        await refreshSessionDetails(nextSessions[0].id);
      } else {
        setCurrentSessionId(null);
        currentSessionIdRef.current = null;
        setMessages([]);
        setTokenStats(null);
      }
    }
  }

  async function loadInspectorFile(path: string) {
    setInspectorPath(path);
    const file = await loadFile(path);
    setInspectorContent(file.content);
    setInspectorDirty(false);
  }

  function updateInspectorContent(value: string) {
    setInspectorContent(value);
    setInspectorDirty(true);
  }

  async function saveInspector() {
    await saveFile(inspectorPath, inspectorContent);
    setInspectorDirty(false);
    await refreshSkills();
  }

  async function compressCurrentSession() {
    if (!currentSessionId) {
      return;
    }
    await compressSession(currentSessionId);
    await refreshSessionDetails(currentSessionId);
    await refreshSessions();
  }

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      const [initialSessions, rag, initialSkills] = await Promise.all([
        listSessions(),
        getRagMode(),
        listSkills()
      ]);

      if (cancelled) {
        return;
      }

      setSessions(initialSessions);
      setRagModeState(rag.enabled);
      setSkills(initialSkills);

      if (!currentSessionIdRef.current && initialSessions.length) {
        setCurrentSessionId(initialSessions[0].id);
        currentSessionIdRef.current = initialSessions[0].id;
        await refreshSessionDetails(initialSessions[0].id);
      } else if (!currentSessionIdRef.current) {
        await createFreshSession();
      }

      const file = await loadFile("durable_memory/MEMORY.md");
      if (cancelled) {
        return;
      }
      setInspectorPath(file.path);
      setInspectorContent(file.content);
    })();

    return () => {
      cancelled = true;
      for (const timer of sessionRefreshTimersRef.current) {
        window.clearTimeout(timer);
      }
      sessionRefreshTimersRef.current = [];
    };
  }, []);

  useEffect(() => {
    currentSessionIdRef.current = currentSessionId;
  }, [currentSessionId]);

  const value: AppStore = {
    sessions,
    currentSessionId,
    messages,
    isStreaming,
    ragMode,
    skills,
    editableFiles,
    inspectorPath,
    inspectorContent,
    inspectorDirty,
    sidebarWidth,
    inspectorWidth,
    tokenStats,
    createNewSession,
    selectSession,
    sendMessage,
    toggleRagMode,
    renameCurrentSession,
    removeSession,
    loadInspectorFile,
    updateInspectorContent,
    saveInspector,
    compressCurrentSession,
    setSidebarWidth,
    setInspectorWidth
  };

  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>;
}

export function useAppStore() {
  const value = useContext(StoreContext);
  if (!value) {
    throw new Error("useAppStore must be used inside AppProvider");
  }
  return value;
}
