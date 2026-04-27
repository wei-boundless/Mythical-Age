import type { OrchestrationEdge, OrchestrationNode, OrchestrationSnapshot, RetrievalResult, ToolCall } from "@/lib/api";

import type { Message, StoreState } from "./types";
import {
  looksLikeSkillDocument,
  looksLikeSkillDocumentPrefix,
  makeId,
  sanitizeToolCall
} from "./utils";

export type StreamSession = {
  assistantId: string;
  hiddenToolCallInFlight: boolean;
};

type StreamTransition = {
  state: StoreState;
  session: StreamSession;
};

const ORCHESTRATION_NODES: Array<{ id: string; label: string; description: string }> = [
  { id: "input", label: "用户输入", description: "接收本轮用户请求，并绑定当前会话。" },
  { id: "followup", label: "Follow-up 仲裁", description: "判断是否续接已有任务、对象或 bundle item。" },
  { id: "planner", label: "任务规划", description: "形成 route、execution mode、tool、skill 和 worker 决策。" },
  { id: "execution-mode", label: "执行模式", description: "进入 single、bundle 或 explicit fanout 执行拓扑。" },
  { id: "context", label: "上下文压缩", description: "整理历史窗口和上下文压力。" },
  { id: "memory", label: "记忆读取", description: "读取状态记忆、长期记忆和上下文包。" },
  { id: "prompt", label: "Prompt 装配", description: "组合身份、准则、记忆、skill 和本轮提示。" },
  { id: "capability", label: "能力调度", description: "决定进入模型、工具或 worker 分支。" },
  { id: "model", label: "模型生成", description: "模型主链流式输出或发起工具调用。" },
  { id: "worker", label: "Worker / Agent", description: "检索、PDF、结构化数据等 worker 分支。" },
  { id: "tool", label: "工具执行", description: "direct tool 或模型工具调用。" },
  { id: "output", label: "输出收口", description: "选择最终可见答案并过滤内部协议。" },
  { id: "persistence", label: "状态写回", description: "写回会话、状态记忆和长期记忆抽取任务。" }
];

const ORCHESTRATION_EDGES: Array<{ id: string; from: string; to: string; label: string }> = [
  { id: "input-followup", from: "input", to: "followup", label: "提交请求" },
  { id: "followup-planner", from: "followup", to: "planner", label: "进入规划" },
  { id: "planner-execution", from: "planner", to: "execution-mode", label: "确定拓扑" },
  { id: "execution-context", from: "execution-mode", to: "context", label: "创建上下文" },
  { id: "context-memory", from: "context", to: "memory", label: "读取记忆" },
  { id: "memory-prompt", from: "memory", to: "prompt", label: "注入上下文" },
  { id: "prompt-capability", from: "prompt", to: "capability", label: "交给调度" },
  { id: "capability-model", from: "capability", to: "model", label: "模型主链" },
  { id: "capability-worker", from: "capability", to: "worker", label: "worker 分支" },
  { id: "capability-tool", from: "capability", to: "tool", label: "工具分支" },
  { id: "model-output", from: "model", to: "output", label: "候选答案" },
  { id: "worker-output", from: "worker", to: "output", label: "worker 结果" },
  { id: "tool-output", from: "tool", to: "output", label: "工具结果" },
  { id: "output-persistence", from: "output", to: "persistence", label: "落盘写回" }
];

function makeOrchestrationSnapshot(state: StoreState, userContent: string): OrchestrationSnapshot {
  const nodes = ORCHESTRATION_NODES.map((node, index): OrchestrationNode => ({
    ...node,
    index: index + 1,
    status: node.id === "input" ? "success" : "idle",
    summary: node.id === "input" ? userContent.trim() : "",
    source_event: node.id === "input" ? "user_message" : ""
  }));
  return {
    source: "live-session",
    session_id: state.currentSessionId ?? "",
    execution_mode: "running",
    route: "pending",
    status: "running",
    summary: "当前请求正在进入编排链路。",
    problem_node_id: "",
    nodes,
    edges: deriveOrchestrationEdges(nodes),
    events: []
  };
}

function deriveOrchestrationEdges(nodes: OrchestrationNode[]): OrchestrationEdge[] {
  const statusById = new Map(nodes.map((node) => [node.id, node.status]));
  return ORCHESTRATION_EDGES.map((edge) => {
    const from = statusById.get(edge.from) ?? "idle";
    const to = statusById.get(edge.to) ?? "idle";
    const status = from === "failed" || to === "failed"
      ? "failed"
      : from === "warning" || to === "warning"
        ? "warning"
        : from !== "idle" && to !== "idle"
          ? "success"
          : "idle";
    return { ...edge, status, summary: edge.label };
  });
}

function normalizeSnapshotEdges(snapshot: OrchestrationSnapshot): OrchestrationSnapshot {
  return {
    ...snapshot,
    edges: snapshot.edges?.length ? snapshot.edges : deriveOrchestrationEdges(snapshot.nodes)
  };
}

function eventNodeId(event: string) {
  if (event === "orchestration_plan") {
    return "execution-mode";
  }
  if (event === "orchestration_diff") {
    return "output";
  }
  if (event === "orchestration_runtime_control") {
    return "execution-mode";
  }
  if (event === "behavior_trace") {
    return "task-understanding";
  }
  if (event === "context_management") {
    return "context";
  }
  if (event === "memory_context") {
    return "memory";
  }
  if (event === "prompt_manifest") {
    return "prompt";
  }
  if (event.startsWith("worker") || event === "retrieval") {
    return "worker";
  }
  if (event.startsWith("tool")) {
    return "tool";
  }
  if (event === "token" || event === "debug") {
    return "model";
  }
  if (event === "done" || event === "error") {
    return "output";
  }
  return "capability";
}

function resolveSnapshotNodeId(snapshot: OrchestrationSnapshot, event: string) {
  const preferred = eventNodeId(event);
  if (snapshot.nodes.some((node) => node.id === preferred)) {
    return preferred;
  }
  const fallbackByEvent: Record<string, string> = {
    context_management: "context",
    memory_context: "context",
    prompt_manifest: "prompt",
    token: "execution",
    debug: "execution",
    done: "output",
    error: "output",
    tool_start: "contract",
    tool_end: "contract",
    worker_start: "capability",
    worker_end: "execution"
  };
  const fallback = fallbackByEvent[event] ?? "capability";
  if (snapshot.nodes.some((node) => node.id === fallback)) {
    return fallback;
  }
  return snapshot.nodes[0]?.id ?? preferred;
}

function eventSummary(event: string, data: Record<string, unknown>) {
  if (event === "orchestration_plan") {
    const plan = (data.plan ?? {}) as Record<string, unknown>;
    const topology = (plan.topology ?? {}) as Record<string, unknown>;
    return `${String(plan.mode ?? "primary")} plan: ${String(topology.mode ?? "unknown")} / ${String(topology.route ?? "unknown")} / ${String(topology.execution_kind ?? "unknown")}`;
  }
  if (event === "orchestration_runtime_control") {
    const warnings = Array.isArray(data.warnings) ? data.warnings.map((item) => String(item)) : [];
    const reason = warnings.map(runtimeControlWarningLabel).filter(Boolean)[0];
    if (reason) {
      return `运行控制：已 fail-closed，原因是${reason}`;
    }
    if (data.primary_active) {
      return `运行控制：directive 已接管 ${String(data.execution_mode ?? "unknown")}。`;
    }
    return `运行控制：${String(data.source ?? "orchestration_blocked")} / ${String(data.execution_mode ?? "unknown")}`;
  }
  if (event === "orchestration_diff") {
    const diff = (data.diff ?? {}) as Record<string, unknown>;
    return `plan diff: ${String(diff.status ?? "unknown")} / ${String(diff.summary ?? "")}`;
  }
  if (event === "behavior_trace") {
    const snapshot = (data.snapshot ?? {}) as Record<string, unknown>;
    return String(snapshot.summary ?? "行为决策 trace 已生成。");
  }
  if (event === "done") {
    return String(data.answer_source ?? data.content ?? "完成输出").slice(0, 220);
  }
  if (event === "error") {
    return String(data.error ?? "执行失败");
  }
  if (event === "prompt_manifest") {
    const manifest = (data.prompt_manifest ?? {}) as Record<string, unknown>;
    return `${String(manifest.total_sections ?? 0)} sections / ${String(manifest.total_chars ?? 0)} chars`;
  }
  if (event.startsWith("worker")) {
    return String(data.worker ?? data.task_status ?? "worker");
  }
  if (event.startsWith("tool")) {
    return String(data.tool ?? "tool");
  }
  if (event === "memory_context") {
    return "状态记忆与长期记忆上下文已读取。";
  }
  if (event === "context_management") {
    return "上下文窗口已整理。";
  }
  return event;
}

function runtimeControlWarningLabel(warning: string) {
  if (warning === "validation_blocked") {
    return "编排校验未通过";
  }
  if (warning === "contract_incomplete") {
    return "正式编排契约不完整";
  }
  if (warning === "execution_directive_missing") {
    return "缺少执行指令";
  }
  if (warning === "execution_candidate_missing") {
    return "执行指令无法匹配候选执行";
  }
  return warning;
}

function updateOrchestrationSnapshot(
  snapshot: OrchestrationSnapshot | null,
  event: string,
  data: Record<string, unknown>
): OrchestrationSnapshot | null {
  if (!snapshot) {
    return snapshot;
  }
  if (event === "behavior_trace") {
    const nextSnapshot = data.snapshot as OrchestrationSnapshot | undefined;
    if (!nextSnapshot?.nodes?.length) {
      return snapshot;
    }
    return {
      ...normalizeSnapshotEdges(nextSnapshot),
      status: "running",
      events: [
        ...snapshot.events,
        {
          index: snapshot.events.length + 1,
          event,
          node_id: nextSnapshot.problem_node_id || "task-understanding",
          summary: String(nextSnapshot.summary || "行为决策 trace 已生成。"),
          data
        }
      ]
    };
  }
  const nodeId = resolveSnapshotNodeId(snapshot, event);
  const summary = eventSummary(event, data);
  const events = [
    ...snapshot.events,
    {
      index: snapshot.events.length + 1,
      event,
      node_id: nodeId,
      summary,
      data
    }
  ];
  const autoVisited = new Set<string>(["followup", "planner", "execution-mode", "capability"]);
  if (["context_management", "memory_context", "prompt_manifest", "worker_start", "tool_start", "token", "done"].includes(event)) {
    autoVisited.add("followup");
    autoVisited.add("planner");
    autoVisited.add("execution-mode");
    autoVisited.add("capability");
  }
  const nodes = snapshot.nodes.map((node) => {
    if (event === "error" && node.id === nodeId) {
      return { ...node, status: "failed" as const, summary, source_event: event };
    }
    if (node.id === "persistence" && event === "done") {
      return { ...node, status: "success" as const, summary: "会话与运行状态等待后处理写回。", source_event: event };
    }
    if (node.id === nodeId || autoVisited.has(node.id)) {
      return {
        ...node,
        status: "success" as const,
        summary: node.id === nodeId ? summary : node.summary || "已进入该编排阶段。",
        source_event: node.id === nodeId ? event : node.source_event
      };
    }
    return node;
  });
  const promptManifest = (data.prompt_manifest ?? {}) as Record<string, unknown>;
  const plan = (data.plan ?? {}) as Record<string, unknown>;
  const topology = (plan.topology ?? {}) as Record<string, unknown>;
  const executionMode = String(data.execution_mode ?? topology.mode ?? snapshot.execution_mode);
  const route = String(data.route ?? topology.route ?? snapshot.route);
  const nextNodes = nodes.map((node) => node.id === "prompt" && event === "prompt_manifest"
    ? { ...node, summary: `${String(promptManifest.total_sections ?? 0)} sections / ${String(promptManifest.total_chars ?? 0)} chars` }
    : node);
  return {
    ...snapshot,
    execution_mode: executionMode === "undefined" ? snapshot.execution_mode : executionMode,
    route: route === "undefined" ? snapshot.route : route,
    status: event === "error" ? "failed" : event === "done" ? "success" : "running",
    summary: event === "done"
      ? `编排完成：${String(data.answer_source ?? "done")}`
      : event === "error"
        ? `编排失败：${String(data.error ?? "unknown")}`
        : `最近事件：${event}`,
    problem_node_id: event === "error" ? nodeId : snapshot.problem_node_id,
    nodes: nextNodes,
    edges: snapshot.edges?.length ? snapshot.edges : deriveOrchestrationEdges(nextNodes),
    events
  };
}

function patchAssistant(
  state: StoreState,
  assistantId: string,
  updater: (message: Message) => Message
): StoreState {
  return {
    ...state,
    messages: state.messages.map((message) =>
      message.id === assistantId ? updater(message) : message
    )
  };
}

export function startStreamingTurn(state: StoreState, userContent: string): StreamTransition {
  const userMessage: Message = {
    id: makeId(),
    role: "user",
    content: userContent.trim(),
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

  return {
    state: {
      ...state,
      isStreaming: true,
      messages: [...state.messages, userMessage, assistantMessage],
      orchestrationSnapshot: makeOrchestrationSnapshot(state, userContent)
    },
    session: {
      assistantId: assistantMessage.id,
      hiddenToolCallInFlight: false
    }
  };
}

export function reduceStreamEvent(
  state: StoreState,
  session: StreamSession,
  event: string,
  data: Record<string, unknown>
): StreamTransition {
  const withOrchestration = updateOrchestrationSnapshot(state.orchestrationSnapshot, event, data);
  const stateWithOrchestration = withOrchestration === state.orchestrationSnapshot
    ? state
    : { ...state, orchestrationSnapshot: withOrchestration };

  if (event === "retrieval") {
    return {
      state: patchAssistant(stateWithOrchestration, session.assistantId, (message) => ({
        ...message,
        retrievals: (data.results as RetrievalResult[]) ?? []
      })),
      session
    };
  }

  if (event === "token") {
    return {
      state: patchAssistant(stateWithOrchestration, session.assistantId, (message) => {
        const nextContent = `${message.content}${String(data.content ?? "")}`;
        if (
          (!message.content.trim() && looksLikeSkillDocumentPrefix(nextContent)) ||
          looksLikeSkillDocument(nextContent)
        ) {
          return message;
        }
        return { ...message, content: nextContent };
      }),
      session
    };
  }

  if (event === "tool_start") {
    const rawToolCall: ToolCall = {
      tool: String(data.tool ?? "tool"),
      input: String(data.input ?? ""),
      output: ""
    };
    const toolCall = sanitizeToolCall(rawToolCall);
    const hiddenToolCallInFlight = !toolCall;
    if (!toolCall) {
      return {
        state: stateWithOrchestration,
        session: { ...session, hiddenToolCallInFlight }
      };
    }
    return {
      state: patchAssistant(stateWithOrchestration, session.assistantId, (message) => ({
        ...message,
        toolCalls: [...message.toolCalls, toolCall]
      })),
      session: { ...session, hiddenToolCallInFlight }
    };
  }

  if (event === "tool_end") {
    if (session.hiddenToolCallInFlight) {
      return {
        state: stateWithOrchestration,
        session: { ...session, hiddenToolCallInFlight: false }
      };
    }
    return {
      state: patchAssistant(stateWithOrchestration, session.assistantId, (message) => ({
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
      })),
      session
    };
  }

  if (event === "done") {
    return {
      state: patchAssistant(stateWithOrchestration, session.assistantId, (message) =>
        message.content
          ? message
          : {
              ...message,
              content: String(data.content ?? "")
            }
      ),
      session
    };
  }

  if (event === "error") {
    return {
      state: patchAssistant(stateWithOrchestration, session.assistantId, (message) => ({
        ...message,
        content: message.content || `Request failed: ${String(data.error ?? "unknown error")}`
      })),
      session
    };
  }

  return { state: stateWithOrchestration, session };
}
