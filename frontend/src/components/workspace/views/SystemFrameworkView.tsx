"use client";

import type { LucideIcon } from "lucide-react";
import {
  Archive,
  Boxes,
  BrainCircuit,
  Cpu,
  Database,
  FileSearch,
  FileText,
  GitBranch,
  MessageSquare,
  Network,
  Radio,
  ShieldCheck,
  Sparkles,
  TestTube2,
  Workflow
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  getExperimentTurnMemoryTrace,
  getExperimentTurnPromptManifest,
  type ExperimentTurnMemoryTrace,
  type PromptManifest
} from "@/lib/api";
import { useAppStore } from "@/lib/store";
import type { WorkspaceView } from "@/lib/store/types";

type GraphNode = {
  id: string;
  label: string;
  source: string;
  kind: string;
  view?: WorkspaceView;
  icon: LucideIcon;
  x: number;
  y: number;
  cluster: Array<{
    label: string;
    source: string;
    relation: string;
    dx: number;
    dy: number;
  }>;
};

type GraphEdge = {
  id: string;
  from: string;
  to: string;
  label: string;
  detail: string;
  route: "request" | "context" | "capability" | "identity" | "evidence" | "storage";
  bidirectional?: boolean;
  labelShift?: {
    x: number;
    y: number;
  };
};

const graphNodes: GraphNode[] = [
  {
    id: "app-entry",
    label: "后端应用入口",
    source: "backend/app.py",
    kind: "启动边界",
    icon: Network,
    x: 7,
    y: 50,
    cluster: [
      { label: "生命周期", source: "runtime_lifespan", relation: "启动", dx: -3, dy: -13 },
      { label: "路由挂载", source: "include_router", relation: "挂载", dx: -2, dy: 13 }
    ]
  },
  {
    id: "api-router",
    label: "接口路由层",
    source: "backend/api/*",
    kind: "请求边界",
    icon: Radio,
    x: 18,
    y: 50,
    cluster: [
      { label: "聊天流接口", source: "api/chat.py", relation: "流式", dx: -5, dy: -13 },
      { label: "会话接口", source: "api/sessions.py", relation: "会话", dx: -5, dy: 13 },
      { label: "文件接口", source: "api/files.py", relation: "文件", dx: 6, dy: -8 },
      { label: "任务接口", source: "api/tasks.py", relation: "任务", dx: 6, dy: 8 }
    ]
  },
  {
    id: "runtime-guard",
    label: "运行时守卫",
    source: "api/deps.py",
    kind: "依赖入口",
    icon: ShieldCheck,
    x: 29,
    y: 50,
    cluster: [
      { label: "就绪检查", source: "require_ready", relation: "校验", dx: -3, dy: -13 },
      { label: "会话校验", source: "validate_session_id", relation: "校验", dx: -4, dy: 13 }
    ]
  },
  {
    id: "runtime-root",
    label: "运行时装配中心",
    source: "runtime/app_runtime.py",
    kind: "组合根",
    icon: Boxes,
    x: 40,
    y: 50,
    cluster: [
      { label: "配置服务", source: "AppSettingsService", relation: "装配", dx: -6, dy: -14 },
      { label: "模型服务", source: "ModelRuntime", relation: "装配", dx: 6, dy: -14 },
      { label: "权限服务", source: "PermissionService", relation: "装配", dx: -6, dy: 10 },
      { label: "索引刷新", source: "refresh_indexes", relation: "刷新", dx: 3, dy: 10 }
    ]
  },
  {
    id: "query-core",
    label: "对话执行引擎",
    source: "query/runtime.py",
    kind: "运行时执行层",
    icon: Workflow,
    x: 49,
    y: 50,
    cluster: [
      { label: "流式执行", source: "astream", relation: "进入", dx: -7, dy: -17 },
      { label: "执行事件", source: "_execution_events", relation: "展开", dx: 7, dy: -17 },
      { label: "结果组装", source: "AnswerAssembler", relation: "收束", dx: -7, dy: 14 },
      { label: "输出边界", source: "RuntimeOutputPolicy", relation: "过滤", dx: 7, dy: 14 }
    ]
  },
  {
    id: "orchestration-control",
    label: "编排控制面",
    source: "backend/orchestration/*",
    kind: "行为计划中枢",
    view: "experiments",
    icon: ShieldCheck,
    x: 62,
    y: 50,
    cluster: [
      { label: "行为计划", source: "models.py", relation: "定义", dx: -8, dy: -16 },
      { label: "计划生成", source: "planner.py", relation: "生成", dx: 8, dy: -16 },
      { label: "运行接管", source: "runtime_adapter.py", relation: "接管", dx: -8, dy: 16 },
      { label: "计划偏移", source: "diff.py", relation: "校验", dx: 8, dy: 16 }
    ]
  },
  {
    id: "planner",
    label: "兼容查询规划器",
    source: "query/planner.py",
    kind: "兼容计划源",
    icon: GitBranch,
    x: 58,
    y: 14,
    cluster: [
      { label: "查询计划", source: "QueryPlanner", relation: "产出", dx: -8, dy: -10 },
      { label: "续接判断", source: "followup_resolver.py", relation: "候选", dx: 8, dy: -10 },
      { label: "能力派发", source: "capability_dispatch.py", relation: "候选", dx: -8, dy: 13 },
      { label: "绑定恢复", source: "binding_resolver.py", relation: "候选", dx: 8, dy: 13 }
    ]
  },
  {
    id: "prompt",
    label: "上下文装配",
    source: "query/prompt_builder.py",
    kind: "上下文合成",
    icon: FileText,
    x: 31,
    y: 12,
    cluster: [
      { label: "当前灵魂", source: "soul/agent_core/ACTIVE_SEED.md", relation: "装配", dx: -8, dy: -10 },
      { label: "核心准则", source: "soul/agent_core/CORE.md", relation: "追加", dx: 8, dy: -10 },
      { label: "技能提示", source: "SkillDefinition", relation: "拼接", dx: -8, dy: 13 },
      { label: "记忆上下文", source: "context_package", relation: "拼接", dx: 8, dy: 13 }
    ]
  },
  {
    id: "memory",
    label: "记忆门面",
    source: "memory/facade.py",
    kind: "记忆入口",
    view: "memory",
    icon: BrainCircuit,
    x: 34,
    y: 81,
    cluster: [
      { label: "消息适配", source: "MemoryMessageAdapter", relation: "转换", dx: -9, dy: -11 },
      { label: "会话记忆", source: "SessionMemoryLayer", relation: "短期", dx: 9, dy: -11 },
      { label: "长期记忆", source: "DurableMemoryLayer", relation: "长期", dx: -9, dy: 11 },
      { label: "上下文包", source: "MemoryContextLayer", relation: "组装", dx: 9, dy: 11 }
    ]
  },
  {
    id: "retrieval",
    label: "检索服务",
    source: "retrieval/service.py",
    kind: "索引召回",
    icon: FileSearch,
    x: 68,
    y: 84,
    cluster: [
      { label: "旧版路由", source: "RAG/router.py", relation: "兼容", dx: -9, dy: -11 },
      { label: "新版索引", source: "retrieval_core", relation: "召回", dx: 9, dy: -11 },
      { label: "知识集合", source: "knowledge", relation: "读取", dx: -9, dy: 11 },
      { label: "记忆集合", source: "indexes_v2", relation: "读取", dx: 9, dy: 11 }
    ]
  },
  {
    id: "evidence",
    label: "证据编排",
    source: "query/evidence_orchestrator.py",
    kind: "材料执行",
    icon: FileSearch,
    x: 70,
    y: 50,
    cluster: [
      { label: "检索工人", source: "retrieval_worker.py", relation: "检索", dx: -8, dy: -12 },
      { label: "PDF 工人", source: "pdf_worker.py", relation: "文档", dx: 8, dy: -12 },
      { label: "表格工人", source: "structured_data_worker.py", relation: "结构化", dx: -8, dy: 19 },
      { label: "证据图谱", source: "evidence_graph.py", relation: "绑定", dx: 8, dy: 19 }
    ]
  },
  {
    id: "tooling",
    label: "操作系统",
    source: "tools/runtime.py",
    kind: "能力入口",
    view: "operations",
    icon: Cpu,
    x: 82,
    y: 11,
    cluster: [
      { label: "工具注册", source: "TOOLS_REGISTRY.json", relation: "发现", dx: -8, dy: -9 },
      { label: "技能注册", source: "SkillRegistry", relation: "发现", dx: 8, dy: -9 },
      { label: "调用闸门", source: "ToolContractGate", relation: "约束", dx: -8, dy: 13 },
      { label: "工具桥接", source: "RuntimeToolBridge", relation: "执行", dx: 8, dy: 13 }
    ]
  },
  {
    id: "model",
    label: "模型流式输出",
    source: "runtime/model_runtime.py",
    kind: "模型边界",
    icon: Sparkles,
    x: 91,
    y: 50,
    cluster: [
      { label: "提供商适配", source: "RuntimeConversationAgent", relation: "适配", dx: -5, dy: -13 },
      { label: "流式响应", source: "astream_conversation", relation: "生成", dx: 5, dy: -13 },
      { label: "工具续写", source: "reasoning_content", relation: "续写", dx: -5, dy: 13 },
      { label: "SSE 回传", source: "StreamingResponse", relation: "回传", dx: 5, dy: 13 }
    ]
  },
  {
    id: "session-store",
    label: "会话存储",
    source: "runtime/session_store.py",
    kind: "状态落盘",
    icon: Archive,
    x: 12,
    y: 83,
    cluster: [
      { label: "当前会话", source: "sessions/*.json", relation: "读写", dx: -7, dy: -10 },
      { label: "历史归档", source: "sessions/archive", relation: "归档", dx: 7, dy: -10 },
      { label: "消息追加", source: "append_messages", relation: "写入", dx: -7, dy: 10 },
      { label: "标题维护", source: "post_turn_tasks", relation: "更新", dx: 7, dy: 10 }
    ]
  },
  {
    id: "storage",
    label: "项目持久层",
    source: "backend/storage",
    kind: "文件资产",
    icon: Database,
    x: 50,
    y: 93,
    cluster: [
      { label: "长期记忆库", source: "durable_memory", relation: "保存", dx: -12, dy: -7 },
      { label: "会话记忆库", source: "session-memory", relation: "保存", dx: 0, dy: -12 },
      { label: "知识索引库", source: "storage/indexes_v2", relation: "索引", dx: 12, dy: -7 },
      { label: "运行轨迹", source: "output/local_traces", relation: "观测", dx: 0, dy: 11 }
    ]
  },
  {
    id: "tests",
    label: "测试与观测",
    source: "backend/tests",
    kind: "质量闭环",
    icon: TestTube2,
    x: 92,
    y: 82,
    cluster: [
      { label: "回归测试", source: "tests/*_regression.py", relation: "验证", dx: -8, dy: -10 },
      { label: "长场景测试", source: "output/test_runs", relation: "压测", dx: 8, dy: -10 },
      { label: "运行追踪", source: "observability", relation: "记录", dx: -8, dy: 10 },
      { label: "问题报告", source: "docs", relation: "沉淀", dx: 8, dy: 10 }
    ]
  }
];

const graphEdges: GraphEdge[] = [
  {
    id: "app-api",
    from: "app-entry",
    to: "api-router",
    label: "挂载接口",
    route: "request",
    detail: "应用入口在 FastAPI 中挂载聊天、会话、文件、配置、任务等接口；后续所有请求先进入这个边界。"
  },
  {
    id: "api-guard",
    from: "api-router",
    to: "runtime-guard",
    label: "取得运行时",
    route: "request",
    detail: "接口层通过依赖函数取得已经初始化的运行时，并在进入执行链前校验会话编号与运行时状态。"
  },
  {
    id: "guard-root",
    from: "runtime-guard",
    to: "runtime-root",
    label: "就绪校验",
    route: "request",
    detail: "运行时守卫不会执行业务逻辑，只确认组合根已经完成装配，随后把请求交给对应服务。"
  },
  {
    id: "root-query",
    from: "runtime-root",
    to: "query-core",
    label: "注入执行依赖",
    route: "request",
    detail: "运行时装配中心创建并注入会话、记忆、检索、工具、权限、模型和任务协调器，QueryRuntime 才能执行完整一轮对话。"
  },
  {
    id: "query-planner",
    from: "query-core",
    to: "orchestration-control",
    label: "请求行为计划",
    route: "request",
    detail: "对话执行引擎在本轮执行前请求编排控制面生成行为计划；兼容模式会跳过计划事件，影子模式只观测，主控模式会尝试按计划接管执行顺序。"
  },
  {
    id: "orchestration-planner",
    from: "orchestration-control",
    to: "planner",
    label: "兼容旧计划",
    route: "request",
    bidirectional: true,
    labelShift: { x: -2, y: -3 },
    detail: "编排控制面不会删除旧查询规划器，而是把旧计划结果作为兼容输入，用它生成可追踪的行为计划，并保留回退边界。"
  },
  {
    id: "orchestration-runtime",
    from: "orchestration-control",
    to: "query-core",
    label: "主控 / 回退",
    route: "request",
    bidirectional: true,
    labelShift: { x: 0, y: 4 },
    detail: "运行控制在主控模式下按行为计划匹配并排序执行分支；如果分支无法对齐，会自动退回旧执行顺序。"
  },
  {
    id: "query-prompt",
    from: "query-core",
    to: "prompt",
    label: "组装系统提示",
    route: "identity",
    detail: "执行核心根据当前会话、记忆召回、技能暴露和灵魂提示词组装本轮系统提示。"
  },
  {
    id: "orchestration-prompt",
    from: "orchestration-control",
    to: "prompt",
    label: "上下文策略",
    route: "identity",
    labelShift: { x: -2, y: 1 },
    detail: "编排控制面把上下文来源、片段顺序和装配策略纳入计划与偏移分析，前端可以分析本轮系统上下文从哪里组合而来。"
  },
  {
    id: "prompt-memory",
    from: "prompt",
    to: "memory",
    label: "读取上下文",
    route: "context",
    bidirectional: true,
    detail: "提示词组装需要记忆门面提供上下文包、长期记忆块和会话压缩结果；这些材料会进入模型输入。"
  },
  {
    id: "orchestration-memory",
    from: "orchestration-control",
    to: "memory",
    label: "上下文策略",
    route: "context",
    bidirectional: true,
    labelShift: { x: -2, y: 3 },
    detail: "行为计划会记录上下文策略、记忆召回、状态记忆和上下文装配信号；测试系统可以把记忆链路和编排节点对齐查看。"
  },
  {
    id: "query-memory",
    from: "query-core",
    to: "memory",
    label: "召回与写回",
    route: "context",
    bidirectional: true,
    detail: "执行核心在轮次中调用记忆门面做长期记忆召回、会话状态投影，以及回合结束后的记忆写回。"
  },
  {
    id: "orchestration-tools",
    from: "orchestration-control",
    to: "tooling",
    label: "契约预检",
    route: "capability",
    bidirectional: true,
    detail: "编排控制面读取技能、工具、权限模式和调用契约，先把可用能力、阻断原因和契约拒绝变成计划节点，再交给执行层。"
  },
  {
    id: "query-tools",
    from: "query-core",
    to: "tooling",
    label: "调用能力",
    route: "capability",
    bidirectional: true,
    detail: "执行核心通过工具桥接层进入操作系统；权限服务和工具契约闸门会约束工具能否被调用。"
  },
  {
    id: "orchestration-evidence",
    from: "orchestration-control",
    to: "evidence",
    label: "子Agent拓扑",
    route: "evidence",
    bidirectional: true,
    labelShift: { x: 0, y: -4 },
    detail: "编排控制面把 retrieval、PDF、表格和 fanout/bundle 分支收敛成 execution topology；actual worker 输出会在 orchestration_diff 中与计划分支对比。"
  },
  {
    id: "query-evidence",
    from: "query-core",
    to: "evidence",
    label: "生成证据任务",
    route: "evidence",
    bidirectional: true,
    detail: "当规划结果需要检索、PDF、表格或证据绑定时，执行核心把材料任务交给证据编排层流式执行。"
  },
  {
    id: "evidence-retrieval",
    from: "evidence",
    to: "retrieval",
    label: "检索材料",
    route: "evidence",
    bidirectional: true,
    detail: "证据编排层通过检索工人访问检索服务，拿到知识库、会话记忆和长期记忆索引中的候选材料。"
  },
  {
    id: "query-model",
    from: "query-core",
    to: "model",
    label: "请求模型生成",
    route: "request",
    bidirectional: true,
    detail: "执行核心把组装后的消息发送给模型运行时，并接收 token、工具调用、续写和最终 done 事件。"
  },
  {
    id: "api-model",
    from: "model",
    to: "api-router",
    label: "流式回传",
    route: "request",
    detail: "模型运行时产生的事件会被对话执行引擎整理后经聊天接口转成事件流，前端实时接收生成片段、工具状态和最终结果。"
  },
  {
    id: "query-session",
    from: "query-core",
    to: "session-store",
    label: "读写会话",
    route: "storage",
    bidirectional: true,
    detail: "执行核心在轮次开始读取历史，在收到用户消息、工具片段和最终回答后写回会话文件。"
  },
  {
    id: "memory-storage",
    from: "memory",
    to: "storage",
    label: "记忆落盘",
    route: "storage",
    bidirectional: true,
    detail: "记忆门面把会话记忆和长期记忆写入文件资产，并在需要时读取已有记忆构建上下文。"
  },
  {
    id: "retrieval-storage",
    from: "retrieval",
    to: "storage",
    label: "索引读写",
    route: "storage",
    bidirectional: true,
    detail: "检索服务读取知识、会话记忆和长期记忆集合；当源文件变化或记忆保存后，会重建对应索引。"
  },
  {
    id: "runtime-storage",
    from: "runtime-root",
    to: "storage",
    label: "刷新索引",
    route: "storage",
    detail: "运行时装配中心监听长期记忆、状态记忆、知识库、技能库等变化，刷新注册表或重建索引。"
  },
  {
    id: "tests-query",
    from: "tests",
    to: "orchestration-control",
    label: "计划回放",
    route: "evidence",
    bidirectional: true,
    detail: "测试与观测系统现在优先读取事件流或测试产物中的行为计划与偏移记录，用问题节点、分支偏移和上下文/记忆链路复盘真实运行过程。"
  },
  {
    id: "tests-query-runtime",
    from: "tests",
    to: "query-core",
    label: "执行回归",
    route: "evidence",
    labelShift: { x: -2, y: 3 },
    detail: "测试仍会围绕对话执行引擎验证长场景、工具续写、状态漂移、检索和记忆稳定性；这是兼容模式与主控模式都必须通过的执行基线。"
  },
  {
    id: "tests-storage",
    from: "tests",
    to: "storage",
    label: "产物沉淀",
    route: "storage",
    bidirectional: true,
    detail: "测试运行会读取会话、索引和 trace，也会把报告、问题清单和长场景产物写入 output 与 docs。"
  }
];

function pointFor(nodeId: string) {
  const node = graphNodes.find((item) => item.id === nodeId) ?? graphNodes[0];
  return { x: node.x, y: node.y };
}

function clampPoint(value: number) {
  return Math.max(3, Math.min(97, value));
}

function midpoint(edge: GraphEdge) {
  const from = pointFor(edge.from);
  const to = pointFor(edge.to);
  return {
    x: clampPoint((from.x + to.x) / 2 + (edge.labelShift?.x ?? 0)),
    y: clampPoint((from.y + to.y) / 2 + (edge.labelShift?.y ?? 0))
  };
}

function overlayStatusLabel(status: string) {
  if (status === "failed") {
    return "失败";
  }
  if (status === "warning") {
    return "警告";
  }
  if (status === "passed") {
    return "通过";
  }
  return "未知";
}

function overlayProblemLabel(status: string) {
  return status === "failed" || status === "warning" ? "问题" : "经过";
}

function promptLayerLabel(layer: string) {
  if (layer === "static") {
    return "静态层";
  }
  if (layer === "session") {
    return "会话层";
  }
  if (layer === "turn") {
    return "当前轮层";
  }
  return layer || "未分层";
}

function promptLayerTone(layer: string) {
  if (layer === "static") {
    return "身份与规则";
  }
  if (layer === "session") {
    return "会话现场";
  }
  if (layer === "turn") {
    return "本轮输入";
  }
  return "其他来源";
}

function compactValue(value: unknown) {
  if (Array.isArray(value)) {
    return value.filter(Boolean).join(" / ") || "空";
  }
  if (typeof value === "boolean") {
    return value ? "是" : "否";
  }
  return String(value ?? "").trim() || "空";
}

export function SystemFrameworkView() {
  const {
    setWorkspaceView,
    systemGraphHighlight,
    highlightSystemGraph,
    systemGraphOverlay,
    setSystemGraphOverlay,
    setMemoryInspectorTarget
  } = useAppStore();
  const [selectedEdgeId, setSelectedEdgeId] = useState(graphEdges[0].id);
  const [selectedOverlayItem, setSelectedOverlayItem] = useState<{ kind: "node" | "edge"; id: string } | null>(null);
  const [promptManifest, setPromptManifest] = useState<PromptManifest | null>(null);
  const [promptManifestStatus, setPromptManifestStatus] = useState("");
  const [promptPanelOpen, setPromptPanelOpen] = useState(false);
  const [memoryTrace, setMemoryTrace] = useState<ExperimentTurnMemoryTrace | null>(null);
  const [memoryTraceStatus, setMemoryTraceStatus] = useState("");
  const [memoryPanelOpen, setMemoryPanelOpen] = useState(false);
  const selectedEdge = graphEdges.find((edge) => edge.id === selectedEdgeId) ?? graphEdges[0];
  const promptManifestAvailable = Boolean(promptManifest || systemGraphOverlay?.prompt_manifest_id);
  const memoryTraceAvailable = Boolean(memoryTrace?.has_memory_signal || systemGraphOverlay?.artifacts?.memory_trace);
  const highlightedNodeIds = new Set(systemGraphHighlight?.nodeIds ?? []);
  const highlightedEdgeIds = new Set(systemGraphHighlight?.edgeIds ?? []);
  const overlayNodes = useMemo(
    () => new Map((systemGraphOverlay?.nodes ?? []).map((node) => [node.id, node])),
    [systemGraphOverlay]
  );
  const overlayEdges = useMemo(
    () => new Map((systemGraphOverlay?.edges ?? []).map((edge) => [edge.id, edge])),
    [systemGraphOverlay]
  );
  const selectedOverlay =
    selectedOverlayItem?.kind === "node"
      ? overlayNodes.get(selectedOverlayItem.id)
      : selectedOverlayItem?.kind === "edge"
        ? overlayEdges.get(selectedOverlayItem.id)
        : overlayEdges.get(selectedEdgeId);
  const overlayNodePath = (systemGraphOverlay?.nodes ?? [])
    .slice(0, 8)
    .map((node) => node.label || node.id);
  const overlayHotspots = [
    ...(systemGraphOverlay?.nodes ?? []),
    ...(systemGraphOverlay?.edges ?? [])
  ].filter((item) => item.status === "failed" || item.status === "warning");
  const overlayArtifacts = Object.entries(systemGraphOverlay?.artifacts ?? {}).slice(0, 4);
  const overlayNodeOrder = useMemo(
    () => new Map((systemGraphOverlay?.nodes ?? []).map((node, index) => [node.id, index + 1])),
    [systemGraphOverlay]
  );
  const overlayEdgeOrder = useMemo(() => {
    const items = new Map<string, string>();
    for (const edge of graphEdges) {
      const fromIndex = overlayNodeOrder.get(edge.from);
      const toIndex = overlayNodeOrder.get(edge.to);
      if (fromIndex && toIndex) {
        items.set(edge.id, `${fromIndex}→${toIndex}`);
      }
    }
    return items;
  }, [overlayNodeOrder]);
  const selectedProblemPosition =
    selectedOverlayItem?.kind === "node"
      ? overlayNodeOrder.get(selectedOverlayItem.id)
      : selectedOverlayItem?.kind === "edge"
        ? overlayEdgeOrder.get(selectedOverlayItem.id)
        : selectedOverlay ? overlayEdgeOrder.get(selectedOverlay.id) ?? overlayNodeOrder.get(selectedOverlay.id) : undefined;
  const firstProblem = overlayHotspots[0];
  const firstProblemPosition = firstProblem
    ? overlayNodeOrder.get(firstProblem.id) ?? overlayEdgeOrder.get(firstProblem.id)
    : undefined;
  const promptSectionsByLayer = useMemo(() => {
    const grouped = new Map<string, PromptManifest["sections"]>();
    for (const section of promptManifest?.sections ?? []) {
      const bucket = grouped.get(section.layer) ?? [];
      bucket.push(section);
      grouped.set(section.layer, bucket);
    }
    return grouped;
  }, [promptManifest]);
  const promptLayerStats = useMemo(
    () => ["static", "session", "turn"].map((layer) => {
      const sections = promptSectionsByLayer.get(layer) ?? [];
      return {
        layer,
        count: sections.length,
        chars: sections.reduce((total, section) => total + section.chars, 0),
      };
    }),
    [promptSectionsByLayer]
  );

  useEffect(() => {
    let cancelled = false;
    setPromptManifest(null);
    setPromptManifestStatus("");
    setPromptPanelOpen(false);
    setMemoryTrace(null);
    setMemoryTraceStatus("");
    setMemoryPanelOpen(false);
    if (!systemGraphOverlay?.run_id || !systemGraphOverlay.turn_id) {
      return () => {
        cancelled = true;
      };
    }
    void (async () => {
      try {
        const payload = await getExperimentTurnPromptManifest(systemGraphOverlay.run_id, systemGraphOverlay.turn_id ?? "");
        if (cancelled) {
          return;
        }
        setPromptManifest(payload.prompt_manifest);
        setPromptManifestStatus(payload.status === "available" ? "" : payload.reason);
      } catch (exc) {
        if (!cancelled) {
          setPromptManifestStatus(exc instanceof Error ? exc.message : "加载上下文来源失败");
        }
      }
      try {
        const payload = await getExperimentTurnMemoryTrace(systemGraphOverlay.run_id, systemGraphOverlay.turn_id ?? "");
        if (cancelled) {
          return;
        }
        setMemoryTrace(payload.memory_trace);
        setMemoryTraceStatus(payload.status === "available" ? "" : payload.reason);
      } catch (exc) {
        if (!cancelled) {
          setMemoryTraceStatus(exc instanceof Error ? exc.message : "加载 Memory Trace 失败");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [systemGraphOverlay?.run_id, systemGraphOverlay?.turn_id]);

  return (
    <div className="system-framework-visual system-framework-visual--graph">
      <button
        className="system-framework-chat-switch"
        onClick={() => setWorkspaceView("chat")}
        type="button"
      >
        <MessageSquare size={16} />
        <span>会话</span>
      </button>

      <div className={`project-network ${systemGraphOverlay ? "project-network--overlay-active" : ""}`}>
        <header className="project-network__header">
          <div>
            <p>后端代码地图</p>
            <h1>项目运行与编排控制全图</h1>
            {systemGraphOverlay ? (
              <div className="project-network__overlay-ribbon">
                <span>{overlayStatusLabel(systemGraphOverlay.status)}</span>
                <strong>{systemGraphOverlay.turn_id ?? systemGraphOverlay.run_id}</strong>
                <em>{systemGraphOverlay.summary}</em>
              </div>
            ) : null}
          </div>
          <div className={`project-network__edge-card project-network__edge-card--${selectedEdge.route}`}>
            <span>{selectedEdge.label}</span>
            <strong>
              {selectedEdge.bidirectional ? "双向交互" : "单向流转"} · {selectedEdge.route === "storage" ? "持久化链路" : "运行链路"}
            </strong>
            <p>{selectedEdge.detail}</p>
            {systemGraphHighlight ? (
              <div className="project-network__debug-focus">
                <small>测试定位：{systemGraphHighlight.source}</small>
                <p>{systemGraphHighlight.reason}</p>
                <button onClick={() => highlightSystemGraph(null)} type="button">清除定位</button>
              </div>
            ) : null}
            {systemGraphOverlay ? (
              <div className={`project-network__debug-focus project-network__debug-focus--${systemGraphOverlay.status}`}>
                <small>
                  {systemGraphOverlay.mode === "observed" ? "观测链路" : "推断链路"}：
                  {systemGraphOverlay.turn_id ?? systemGraphOverlay.run_id}
                </small>
                <strong className="project-network__selected-title">
                  {selectedOverlay?.label ?? "当前运行路径"}
                  {selectedOverlay ? ` · ${overlayStatusLabel(selectedOverlay.status)}` : ""}
                </strong>
                {(selectedProblemPosition || firstProblemPosition) ? (
                  <div className="project-network__problem-position">
                    {selectedProblemPosition
                      ? `当前选中：${typeof selectedProblemPosition === "number" ? `第 ${selectedProblemPosition} 个节点` : `第 ${selectedProblemPosition} 段链路`}`
                      : `首个异常：${typeof firstProblemPosition === "number" ? `第 ${firstProblemPosition} 个节点` : `第 ${firstProblemPosition} 段链路`}`}
                  </div>
                ) : null}
                <p>{selectedOverlay?.reason ?? systemGraphOverlay.summary}</p>
                {selectedOverlay?.events?.length ? (
                  <div className="project-network__event-tags">
                    {selectedOverlay.events.slice(0, 4).map((event) => (
                      <span key={event}>{event}</span>
                    ))}
                  </div>
                ) : null}
                {overlayNodePath.length ? (
                  <div className="project-network__path-strip">
                    {overlayNodePath.map((label, index) => (
                      <span key={`${label}-${index}`}>{label}</span>
                    ))}
                  </div>
                ) : null}
                {overlayHotspots.length ? (
                  <div className="project-network__hotspots">
                    <small>异常焦点</small>
                    {overlayHotspots.slice(0, 4).map((item) => (
                      <button
                        key={item.id}
                        onClick={() => {
                          if (overlayNodes.has(item.id)) {
                            setSelectedOverlayItem({ kind: "node", id: item.id });
                          } else {
                            setSelectedEdgeId(item.id);
                            setSelectedOverlayItem({ kind: "edge", id: item.id });
                          }
                        }}
                        type="button"
                      >
                        {overlayNodeOrder.get(item.id)
                          ? `第 ${overlayNodeOrder.get(item.id)} 节点 · ${item.label}`
                          : overlayEdgeOrder.get(item.id)
                            ? `第 ${overlayEdgeOrder.get(item.id)} 段 · ${item.label}`
                            : item.label}
                      </button>
                    ))}
                  </div>
                ) : null}
                {overlayArtifacts.length ? (
                  <div className="project-network__artifacts">
                    {overlayArtifacts.map(([key, value]) => (
                      <span key={key}>{key}: {value}</span>
                    ))}
                  </div>
                ) : null}
                <div className="project-network__prompt-entry">
                  <button
                    disabled={!systemGraphOverlay.turn_id}
                    onClick={() => setPromptPanelOpen((value) => !value)}
                    type="button"
                  >
                    {promptManifest ? "查看上下文来源" : "上下文来源暂不可用"}
                  </button>
                  {promptManifest ? (
                    <span>已记录 · {promptManifest.total_sections} 个来源 · {promptManifest.total_chars} 字</span>
                  ) : (
                    <span>{promptManifestStatus || "旧测试产物没有记录上下文来源。"}</span>
                  )}
                </div>
                {promptPanelOpen && promptManifest ? (
                  <div className="prompt-manifest-panel">
                    <header>
                      <small>上下文来源</small>
                      <strong>本轮装配记录</strong>
                      <span>{promptManifest.debug_policy === "preview_only" ? "默认只展示来源摘要，不显示完整内容。" : "当前仅展示可读摘要。"}</span>
                    </header>
                    <div className="prompt-manifest-flow" aria-label="上下文三层装配摘要">
                      {promptLayerStats.map((stat, index) => (
                        <div className={`prompt-manifest-flow__node prompt-manifest-flow__node--${stat.layer}`} key={stat.layer}>
                          <b>{index + 1}</b>
                          <strong>{promptLayerLabel(stat.layer)}</strong>
                          <span>{promptLayerTone(stat.layer)}</span>
                          <em>{stat.count} 来源 · {stat.chars} 字</em>
                        </div>
                      ))}
                    </div>
                    {["static", "session", "turn"].map((layer) => {
                      const sections = promptSectionsByLayer.get(layer) ?? [];
                      if (!sections.length) {
                        return null;
                      }
                      return (
                        <section className={`prompt-manifest-layer prompt-manifest-layer--${layer}`} key={layer}>
                          <h4>{promptLayerLabel(layer)}</h4>
                          {sections.map((section) => (
                            <article className="prompt-manifest-section" key={section.id}>
                              <div>
                                <strong>{section.order}. {section.title}</strong>
                                <span>第 {section.order} 段 · {section.chars} 字</span>
                              </div>
                              <p>{section.preview || "暂无摘要"}</p>
                            </article>
                          ))}
                        </section>
                      );
                    })}
                  </div>
                ) : null}
                <div className="project-network__memory-entry">
                  <button
                    disabled={!systemGraphOverlay.turn_id}
                    onClick={() => setMemoryPanelOpen((value) => !value)}
                    type="button"
                  >
                    {memoryTraceAvailable ? "查看本轮记忆链路" : "记忆链路暂不可用"}
                  </button>
                  {memoryTrace ? (
                    <span>{memoryTrace.summary}</span>
                  ) : (
                    <span>{memoryTraceStatus || "旧测试产物没有记录可解析的记忆链路。"}</span>
                  )}
                  <button
                    disabled={!systemGraphOverlay.run_id || !systemGraphOverlay.turn_id}
                    onClick={() => {
                      setMemoryInspectorTarget({
                        source: "system-framework",
                        runId: systemGraphOverlay.run_id,
                        turnId: systemGraphOverlay.turn_id ?? undefined,
                        layer: "state",
                        reason: systemGraphOverlay.summary
                      });
                      setWorkspaceView("memory");
                    }}
                    type="button"
                  >
                    去状态记忆阅读
                  </button>
                </div>
                {memoryPanelOpen && memoryTrace ? (
                  <div className="memory-trace-panel">
                    <header>
                      <small>Memory Trace</small>
                      <strong>{memoryTrace.turn_id || systemGraphOverlay.turn_id}</strong>
                      <span>{memoryTrace.context_management.pressure_level} · {memoryTrace.context_management.strategy}</span>
                    </header>
                    <div className="memory-trace-flow">
                      <article>
                        <b>1</b>
                        <strong>状态记忆</strong>
                        <span>{memoryTrace.session_memory.section_count} 段上下文</span>
                      </article>
                      <article>
                        <b>2</b>
                        <strong>长期召回</strong>
                        <span>精确 {memoryTrace.durable_memory.exact_count} 条 · 相关 {memoryTrace.durable_memory.relevant_count} 条</span>
                      </article>
                      <article>
                        <b>3</b>
                        <strong>上下文装配</strong>
                        <span>{memoryTrace.prompt_injection.section_count} 段 · {memoryTrace.prompt_injection.total_chars} 字</span>
                      </article>
                    </div>
                    <div className="memory-trace-grid">
                      <section>
                        <h4>模型可见状态</h4>
                        {(memoryTrace.session_memory.model_sections.length ? memoryTrace.session_memory.model_sections : memoryTrace.session_memory.debug_sections).slice(0, 4).map((section) => (
                          <div className="memory-trace-section" key={section.id}>
                            <strong>{section.label} · {section.count}</strong>
                            {section.items.slice(0, 3).map((item, index) => <p key={`${section.id}-${index}`}>{item}</p>)}
                          </div>
                        ))}
                        {!memoryTrace.session_memory.model_sections.length && !memoryTrace.session_memory.debug_sections.length ? <p>没有状态记忆片段进入本轮上下文。</p> : null}
                      </section>
                      <section>
                        <h4>长期记忆</h4>
                        {memoryTrace.durable_memory.model_sections.slice(0, 4).map((section) => (
                          <div className="memory-trace-section" key={section.id}>
                            <strong>{section.label} · {section.count}</strong>
                            {section.items.slice(0, 3).map((item, index) => <p key={`${section.id}-${index}`}>{item}</p>)}
                          </div>
                        ))}
                        {!memoryTrace.durable_memory.model_sections.length ? <p>没有长期记忆进入模型可见上下文。</p> : null}
                      </section>
                    </div>
                    {Object.keys(memoryTrace.session_memory.context_slots).length ? (
                      <div className="memory-trace-slots">
                        {Object.entries(memoryTrace.session_memory.context_slots).slice(0, 8).map(([key, value]) => (
                          <span key={key}><b>{key}</b>{compactValue(value)}</span>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ) : null}
                <button onClick={() => setWorkspaceView("test-system")} type="button">返回测试系统</button>
                <button onClick={() => setSystemGraphOverlay(null)} type="button">清除链路</button>
              </div>
            ) : null}
          </div>
        </header>

        <section className="project-network__canvas">
          <svg aria-hidden className="project-network__edges" preserveAspectRatio="none" viewBox="0 0 100 100">
            <defs>
              <marker id="graph-arrow" markerHeight="6" markerWidth="8" orient="auto" refX="7" refY="3">
                <path d="M0,0 L8,3 L0,6 Z" />
              </marker>
            </defs>
            {graphEdges.map((edge) => {
              const from = pointFor(edge.from);
              const to = pointFor(edge.to);
              const selected = selectedEdge.id === edge.id;
              const highlighted = highlightedEdgeIds.has(edge.id);
              const overlay = overlayEdges.get(edge.id);
              const muted = Boolean(systemGraphOverlay && !overlay);
              const labelPoint = midpoint(edge);
              const edgeOrder = overlayEdgeOrder.get(edge.id);
              const edgeProblem = overlay && (overlay.status === "failed" || overlay.status === "warning");
              return (
                <g
                  className={`graph-edge graph-edge--${edge.route} ${selected ? "graph-edge--selected" : ""} ${highlighted ? "graph-edge--highlighted" : ""} ${overlay ? `graph-edge--overlay graph-edge--overlay-${overlay.status}` : ""} ${muted ? "graph-edge--muted" : ""}`}
                  key={edge.id}
                >
                  <line
                    className="graph-edge__visible"
                    markerEnd="url(#graph-arrow)"
                    x1={from.x}
                    x2={to.x}
                    y1={from.y}
                    y2={to.y}
                  />
                  <line
                    className="graph-edge__hit"
                    onClick={() => {
                      setSelectedEdgeId(edge.id);
                      setSelectedOverlayItem(overlay ? { kind: "edge", id: edge.id } : null);
                    }}
                    x1={from.x}
                    x2={to.x}
                    y1={from.y}
                    y2={to.y}
                  />
                  <text
                    className="graph-edge__label"
                    onClick={() => {
                      setSelectedEdgeId(edge.id);
                      setSelectedOverlayItem(overlay ? { kind: "edge", id: edge.id } : null);
                    }}
                    x={labelPoint.x}
                    y={labelPoint.y}
                  >
                    {edge.label}
                  </text>
                  {edgeProblem && edgeOrder ? (
                    <text
                      className="graph-edge__problem-label"
                      onClick={() => {
                        setSelectedEdgeId(edge.id);
                        setSelectedOverlayItem({ kind: "edge", id: edge.id });
                      }}
                      x={labelPoint.x}
                      y={clampPoint(labelPoint.y + 2.2)}
                    >
                      问题链路 {edgeOrder}
                    </text>
                  ) : null}
                </g>
              );
            })}
            {graphNodes.flatMap((node) =>
              node.cluster.map((child) => {
                const x2 = clampPoint(node.x + child.dx);
                const y2 = clampPoint(node.y + child.dy);
                return (
                  <line
                    className="graph-local-edge"
                    key={`${node.id}-${child.label}-edge`}
                    x1={node.x}
                    x2={x2}
                    y1={node.y}
                    y2={y2}
                  />
                );
              })
            )}
          </svg>

          {graphNodes.map((node) => {
            const Icon = node.icon;
            const highlighted = highlightedNodeIds.has(node.id);
            const overlay = overlayNodes.get(node.id);
            const overlayIndex = overlayNodeOrder.get(node.id);
            const muted = Boolean(systemGraphOverlay && !overlay);
            const promptNodeHasManifest = node.id === "prompt" && promptManifestAvailable;
            const memoryNodeHasTrace = node.id === "memory" && memoryTraceAvailable;
            return (
              <article
                className={`network-node network-node--${node.id} ${highlighted ? "network-node--highlighted" : ""} ${overlay ? `network-node--overlay network-node--overlay-${overlay.status}` : ""} ${promptNodeHasManifest ? "network-node--prompt-manifest" : ""} ${memoryNodeHasTrace ? "network-node--memory-trace" : ""} ${muted ? "network-node--muted" : ""}`}
                key={node.id}
                style={{ left: `${node.x}%`, top: `${node.y}%` }}
              >
                {overlayIndex ? <span className="network-node__overlay-index">{overlayIndex}</span> : null}
                {promptNodeHasManifest ? <span className="network-node__prompt-badge">上下文已记录</span> : null}
                {memoryNodeHasTrace ? <span className="network-node__memory-badge">记忆已记录</span> : null}
                <button
                  className="network-node__head"
                  disabled={!node.view && !overlay}
                  onClick={() => {
                    if (overlay) {
                      setSelectedOverlayItem({ kind: "node", id: node.id });
                      return;
                    }
                    if (node.view) {
                      setWorkspaceView(node.view);
                    }
                  }}
                  type="button"
                >
                  <span className="network-node__icon">
                    <Icon size={15} />
                  </span>
                  <span>
                    <small>{node.kind}</small>
                    <strong>{node.label}</strong>
                    <em>{node.view ? "可进入管理页" : "运行节点"}</em>
                    {overlay ? (
                      <b>
                        {overlayProblemLabel(overlay.status)}
                        {overlayIndex ? `节点 ${overlayIndex}` : ""}
                        {" · "}
                        {overlayStatusLabel(overlay.status)}
                      </b>
                    ) : null}
                    {node.id === "prompt" && systemGraphOverlay?.turn_id ? (
                      <b>{promptManifestAvailable ? "来源装配可分析" : "来源装配缺失"}</b>
                    ) : null}
                    {node.id === "memory" && systemGraphOverlay?.turn_id ? (
                      <b>{memoryTraceAvailable ? "记忆链路可分析" : "记忆链路缺失"}</b>
                    ) : null}
                  </span>
                </button>
              </article>
            );
          })}
          {graphNodes.flatMap((node) =>
            node.cluster.map((child) => (
              <article
                className={`network-subnode network-subnode--${node.id} ${systemGraphOverlay && !overlayNodes.has(node.id) ? "network-subnode--muted" : ""}`}
                key={`${node.id}-${child.label}`}
                style={{ left: `${clampPoint(node.x + child.dx)}%`, top: `${clampPoint(node.y + child.dy)}%` }}
              >
                <span>{child.relation}</span>
                <strong>{child.label}</strong>
                <em>子能力</em>
              </article>
            ))
          )}
          {graphNodes.flatMap((node) =>
            node.cluster.map((child) => (
              <div
                className="network-local-relation"
                key={`${node.id}-${child.label}-relation`}
                style={{
                  left: `${clampPoint(node.x + child.dx / 2)}%`,
                  top: `${clampPoint(node.y + child.dy / 2)}%`
                }}
              >
                {child.relation} · {child.label}
              </div>
            ))
          )}
        </section>

        <footer className="project-network__legend">
          <span className="legend-route legend-route--request">请求与流式链路</span>
          <span className="legend-route legend-route--context">上下文与记忆链路</span>
          <span className="legend-route legend-route--capability">操作系统链路</span>
          <span className="legend-route legend-route--identity">身份与提示词链路</span>
          <span className="legend-route legend-route--evidence">证据与测试链路</span>
          <span className="legend-route legend-route--storage">文件与索引链路</span>
        </footer>
      </div>
    </div>
  );
}
