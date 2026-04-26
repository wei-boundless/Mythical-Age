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
import { useState } from "react";

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
    label: "对话执行核心",
    source: "query/runtime.py",
    kind: "主执行链",
    icon: Workflow,
    x: 53,
    y: 50,
    cluster: [
      { label: "流式执行", source: "astream", relation: "进入", dx: -7, dy: -18 },
      { label: "执行事件", source: "_execution_events", relation: "展开", dx: 7, dy: -18 },
      { label: "结果组装", source: "AnswerAssembler", relation: "收束", dx: -7, dy: 14 },
      { label: "输出边界", source: "RuntimeOutputPolicy", relation: "过滤", dx: 7, dy: 14 }
    ]
  },
  {
    id: "planner",
    label: "任务理解与规划",
    source: "query/planner.py",
    kind: "意图分流",
    icon: GitBranch,
    x: 56,
    y: 11,
    cluster: [
      { label: "follow-up 解析", source: "followup_resolver.py", relation: "承接", dx: -8, dy: -9 },
      { label: "能力派发", source: "capability_dispatch.py", relation: "选择", dx: 8, dy: -9 },
      { label: "子任务规划", source: "subtask_planner.py", relation: "拆分", dx: -8, dy: 13 },
      { label: "任务记录", source: "tasks/coordinator.py", relation: "记录", dx: 8, dy: 13 }
    ]
  },
  {
    id: "prompt",
    label: "提示词组装",
    source: "query/prompt_builder.py",
    kind: "上下文合成",
    icon: FileText,
    x: 31,
    y: 12,
    cluster: [
      { label: "当前身份", source: "soul/agent_core/ACTIVE_SEED.md", relation: "注入", dx: -8, dy: -10 },
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
    label: "工具与技能运行",
    source: "tools/runtime.py",
    kind: "能力入口",
    view: "capabilities",
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
    to: "planner",
    label: "分析任务",
    route: "request",
    detail: "对话执行核心把用户消息交给规划层，识别 follow-up、能力派发、显式子任务和任务状态。"
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
    id: "prompt-memory",
    from: "prompt",
    to: "memory",
    label: "读取上下文",
    route: "context",
    bidirectional: true,
    detail: "提示词组装需要记忆门面提供上下文包、长期记忆块和会话压缩结果；这些材料会进入模型输入。"
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
    id: "query-tools",
    from: "query-core",
    to: "tooling",
    label: "调用能力",
    route: "capability",
    bidirectional: true,
    detail: "执行核心通过工具桥接层进入工具与技能运行系统；权限服务和工具契约闸门会约束工具能否被调用。"
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
    detail: "模型运行时产生的事件会被 QueryRuntime 整理后经聊天接口转成 SSE，前端实时接收 token、工具状态和最终结果。"
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
    detail: "运行时装配中心监听 durable_memory、session-memory、knowledge、skills 等路径变化，刷新注册表或重建索引。"
  },
  {
    id: "tests-query",
    from: "tests",
    to: "query-core",
    label: "回归压测",
    route: "evidence",
    detail: "测试与观测系统围绕 QueryRuntime 验证长场景、工具续写、状态漂移、检索和记忆稳定性。"
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

export function SystemFrameworkView() {
  const { setWorkspaceView } = useAppStore();
  const [selectedEdgeId, setSelectedEdgeId] = useState(graphEdges[0].id);
  const selectedEdge = graphEdges.find((edge) => edge.id === selectedEdgeId) ?? graphEdges[0];

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

      <div className="project-network">
        <header className="project-network__header">
          <div>
            <p>后端代码地图</p>
            <h1>项目运行关系全图</h1>
          </div>
          <div className={`project-network__edge-card project-network__edge-card--${selectedEdge.route}`}>
            <span>{selectedEdge.label}</span>
            <strong>
              {selectedEdge.bidirectional ? "双向交互" : "单向流转"} · {selectedEdge.route === "storage" ? "持久化链路" : "运行链路"}
            </strong>
            <p>{selectedEdge.detail}</p>
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
              const labelPoint = midpoint(edge);
              return (
                <g
                  className={`graph-edge graph-edge--${edge.route} ${selected ? "graph-edge--selected" : ""}`}
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
                    onClick={() => setSelectedEdgeId(edge.id)}
                    x1={from.x}
                    x2={to.x}
                    y1={from.y}
                    y2={to.y}
                  />
                  <text
                    className="graph-edge__label"
                    onClick={() => setSelectedEdgeId(edge.id)}
                    x={labelPoint.x}
                    y={labelPoint.y}
                  >
                    {edge.label}
                  </text>
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
            return (
              <article
                className={`network-node network-node--${node.id}`}
                key={node.id}
                style={{ left: `${node.x}%`, top: `${node.y}%` }}
              >
                <button
                  className="network-node__head"
                  disabled={!node.view}
                  onClick={() => node.view ? setWorkspaceView(node.view) : undefined}
                  type="button"
                >
                  <span className="network-node__icon">
                    <Icon size={15} />
                  </span>
                  <span>
                    <small>{node.kind}</small>
                    <strong>{node.label}</strong>
                    <em>{node.source}</em>
                  </span>
                </button>
              </article>
            );
          })}
          {graphNodes.flatMap((node) =>
            node.cluster.map((child) => (
              <article
                className={`network-subnode network-subnode--${node.id}`}
                key={`${node.id}-${child.label}`}
                style={{ left: `${clampPoint(node.x + child.dx)}%`, top: `${clampPoint(node.y + child.dy)}%` }}
              >
                <span>{child.relation}</span>
                <strong>{child.label}</strong>
                <em>{child.source}</em>
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
          <span className="legend-route legend-route--capability">工具与技能链路</span>
          <span className="legend-route legend-route--identity">身份与提示词链路</span>
          <span className="legend-route legend-route--evidence">证据与测试链路</span>
          <span className="legend-route legend-route--storage">文件与索引链路</span>
        </footer>
      </div>
    </div>
  );
}
