"use client";

import {
  AlertTriangle,
  ArrowRight,
  Boxes,
  BrainCircuit,
  Database,
  FileText,
  GitBranch,
  Hammer,
  Loader2,
  Network,
  RefreshCw,
  Route,
  ShieldCheck,
  Sparkles,
  TerminalSquare
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  getExperimentTurnOrchestration,
  getOrchestrationCatalog,
  refreshOrchestrationCatalog,
  runOrchestrationDryRun,
  setPermissionMode,
  type OrchestrationCatalog,
  type OrchestrationNode,
  type OrchestrationSnapshot
} from "@/lib/api";
import { useAppStore } from "@/lib/store";

function emptySnapshot(sessionId: string | null): OrchestrationSnapshot {
  const nodes: OrchestrationNode[] = [
    ["input", "用户输入", "接收本轮用户请求，并绑定当前会话。"],
    ["followup", "Follow-up 仲裁", "判断是否续接已有任务、对象或 bundle item。"],
    ["planner", "任务规划", "形成 route、execution mode、tool、skill 和 worker 决策。"],
    ["execution-mode", "执行模式", "进入 single、bundle 或 explicit fanout 执行拓扑。"],
    ["context", "上下文压缩", "整理历史窗口和上下文压力。"],
    ["memory", "记忆读取", "读取状态记忆、长期记忆和上下文包。"],
    ["prompt", "Prompt 装配", "组合身份、准则、记忆、skill 和本轮提示。"],
    ["capability", "能力调度", "决定进入模型、工具或 worker 分支。"],
    ["model", "模型生成", "模型主链流式输出或发起工具调用。"],
    ["worker", "Worker / Agent", "检索、PDF、结构化数据等 worker 分支。"],
    ["tool", "工具执行", "direct tool 或模型工具调用。"],
    ["output", "输出收口", "选择最终可见答案并过滤内部协议。"],
    ["persistence", "状态写回", "写回会话、状态记忆和长期记忆抽取任务。"]
  ].map(([id, label, description], index) => ({
    id,
    label,
    description,
    index: index + 1,
    status: "idle",
    summary: "",
    source_event: ""
  }));
  return {
    source: "inferred",
    session_id: sessionId ?? "",
    execution_mode: "等待请求",
    route: "未运行",
    status: "idle",
    summary: "还没有 live 编排事件。发送一条消息，或从测试系统选择一个 turn 来复盘。",
    problem_node_id: "",
    nodes,
    edges: [],
    events: [],
    artifacts: {}
  };
}

function statusLabel(status: string) {
  if (status === "running") {
    return "运行中";
  }
  if (status === "success" || status === "passed") {
    return "已完成";
  }
  if (status === "failed") {
    return "失败";
  }
  if (status === "warning") {
    return "警告";
  }
  return "待观察";
}

function sourceLabel(source: string) {
  if (source === "live-session") {
    return "当前会话";
  }
  if (source === "test-turn") {
    return "测试 Turn";
  }
  if (source === "dry-run") {
    return "行为推演";
  }
  return "推断骨架";
}

function jsonText(value: unknown) {
  if (value == null) {
    return "";
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function nodeIcon(nodeId: string) {
  if (nodeId === "memory") {
    return <BrainCircuit size={16} />;
  }
  if (nodeId === "prompt") {
    return <Sparkles size={16} />;
  }
  if (nodeId === "worker") {
    return <Network size={16} />;
  }
  if (nodeId === "tool") {
    return <TerminalSquare size={16} />;
  }
  if (nodeId === "persistence") {
    return <Database size={16} />;
  }
  return <Route size={16} />;
}

const stageGroups = [
  {
    title: "理解",
    hint: "这句话被识别成什么任务",
    nodes: ["input", "memory-intent", "task-understanding", "followup", "planner", "continuation"]
  },
  {
    title: "策略",
    hint: "用什么上下文和行为包",
    nodes: ["execution-mode", "skill-policy", "context", "memory", "prompt"]
  },
  {
    title: "能力",
    hint: "开放哪些工具、worker 和边界",
    nodes: ["capability", "contract", "tool", "worker"]
  },
  {
    title: "收口",
    hint: "最终会怎样执行和输出",
    nodes: ["execution", "model", "output", "persistence"]
  }
];

function compactValue(value: unknown) {
  if (Array.isArray(value)) {
    return value.length ? `${value.length} 项` : "空";
  }
  if (value && typeof value === "object") {
    return `${Object.keys(value as Record<string, unknown>).length} 个字段`;
  }
  if (value === true) {
    return "是";
  }
  if (value === false) {
    return "否";
  }
  return String(value ?? "-");
}

export function ExperimentsView() {
  const {
    currentSessionId,
    orchestrationInspectorTarget,
    orchestrationSnapshot,
    highlightSystemGraph,
    loadInspectorFile,
    setMemoryInspectorTarget,
    setOrchestrationInspectorTarget,
    setOrchestrationSnapshot,
    setWorkspaceView
  } = useAppStore();
  const [activePanel, setActivePanel] = useState<"behavior" | "skills" | "contracts">("behavior");
  const [testSnapshot, setTestSnapshot] = useState<OrchestrationSnapshot | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState("input");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [dryRunMessage, setDryRunMessage] = useState("");
  const [dryRunLoading, setDryRunLoading] = useState(false);
  const [catalog, setCatalog] = useState<OrchestrationCatalog | null>(null);
  const [catalogQuery, setCatalogQuery] = useState("");
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [catalogAction, setCatalogAction] = useState("");

  const target = orchestrationInspectorTarget;
  const activeSnapshot = target?.source === "test-system"
    ? testSnapshot
    : orchestrationSnapshot;
  const snapshot = activeSnapshot ?? emptySnapshot(currentSessionId);
  const selectedNode = useMemo(
    () => snapshot.nodes.find((node) => node.id === selectedNodeId)
      ?? snapshot.nodes.find((node) => node.id === snapshot.problem_node_id)
      ?? snapshot.nodes[0],
    [selectedNodeId, snapshot.nodes, snapshot.problem_node_id]
  );
  const problemNode = snapshot.nodes.find((node) => node.id === snapshot.problem_node_id);
  const visitedCount = snapshot.nodes.filter((node) => node.status !== "idle").length;
  const branchNodes = snapshot.nodes.filter((node) => ["worker", "tool"].includes(node.id) && node.status !== "idle");
  const nodeById = useMemo(() => new Map(snapshot.nodes.map((node) => [node.id, node])), [snapshot.nodes]);
  const executionNode = nodeById.get("execution") ?? nodeById.get("model") ?? nodeById.get("worker") ?? nodeById.get("tool");
  const contextNode = nodeById.get("context") ?? nodeById.get("memory");
  const contractNode = nodeById.get("contract") ?? nodeById.get("tool");
  const skillNode = nodeById.get("skill-policy") ?? nodeById.get("capability");
  const readableRoute = `${snapshot.route || "unknown"} / ${snapshot.execution_mode || "unknown"}`;

  const loadTargetSnapshot = useCallback(async () => {
    if (!target?.runId || !target.turnId) {
      return;
    }
    setLoading(true);
    setError("");
    try {
      const payload = await getExperimentTurnOrchestration(target.runId, target.turnId, target.artifactPath);
      setTestSnapshot(payload);
      setOrchestrationSnapshot(payload);
      setSelectedNodeId(payload.problem_node_id || payload.nodes.find((node) => node.status === "failed")?.id || "input");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加载编排链路失败");
    } finally {
      setLoading(false);
    }
  }, [setOrchestrationSnapshot, target?.artifactPath, target?.runId, target?.turnId]);

  useEffect(() => {
    if (target?.source === "test-system") {
      void loadTargetSnapshot();
    }
  }, [loadTargetSnapshot, target?.source]);

  const loadCatalog = useCallback(async () => {
    setCatalogLoading(true);
    try {
      setCatalog(await getOrchestrationCatalog());
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加载编排 catalog 失败");
    } finally {
      setCatalogLoading(false);
    }
  }, []);

  async function refreshCatalog() {
    setCatalogLoading(true);
    setCatalogAction("");
    try {
      setCatalog(await refreshOrchestrationCatalog());
      setCatalogAction("Registry 已刷新，skills 与 tools catalog 已重新读取。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "刷新 catalog 失败");
    } finally {
      setCatalogLoading(false);
    }
  }

  async function changePermissionMode(mode: string) {
    setCatalogLoading(true);
    setCatalogAction("");
    try {
      await setPermissionMode(mode);
      const nextCatalog = await getOrchestrationCatalog();
      setCatalog(nextCatalog);
      setCatalogAction(`Permission mode 已切换为 ${nextCatalog.permission_mode}。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "切换 permission mode 失败");
    } finally {
      setCatalogLoading(false);
    }
  }

  useEffect(() => {
    if (activePanel !== "behavior" && !catalog) {
      void loadCatalog();
    }
  }, [activePanel, catalog, loadCatalog]);

  function locateOnSystemGraph(node: OrchestrationNode) {
    const map: Record<string, string[]> = {
      input: ["api-router"],
      followup: ["query-core"],
      planner: ["planner"],
      "execution-mode": ["query-core"],
      context: ["query-core", "memory"],
      memory: ["memory"],
      prompt: ["prompt"],
      capability: ["query-core", "tooling"],
      model: ["model"],
      worker: ["evidence"],
      tool: ["tooling"],
      output: ["query-core"],
      persistence: ["session-store", "storage"]
    };
    highlightSystemGraph({
      nodeIds: map[node.id] ?? ["query-core"],
      edgeIds: [],
      reason: node.summary || node.description,
      source: `orchestration:${node.id}`
    });
    setWorkspaceView("system-framework");
  }

  function openMemoryNode() {
    if (snapshot.source === "test-turn" && snapshot.run_id && snapshot.turn_id) {
      setMemoryInspectorTarget({
        source: "test-system",
        runId: snapshot.run_id,
        turnId: snapshot.turn_id,
        turnIndex: snapshot.turn_index,
        layer: "state",
        reason: selectedNode?.summary || "从编排系统查看状态记忆。"
      });
    } else {
      setMemoryInspectorTarget({
        source: "manual",
        layer: "state",
        reason: selectedNode?.summary || "从编排系统查看当前会话状态记忆。"
      });
    }
    setWorkspaceView("memory");
  }

  async function submitDryRun() {
    const message = dryRunMessage.trim();
    if (!message || !currentSessionId) {
      setError(currentSessionId ? "请输入要推演的用户请求。" : "需要先选择一个会话，dry-run 才能读取当前上下文。");
      return;
    }
    setDryRunLoading(true);
    setError("");
    try {
      const payload = await runOrchestrationDryRun({
        session_id: currentSessionId,
        message
      });
      setTestSnapshot(null);
      setOrchestrationInspectorTarget(null);
      setOrchestrationSnapshot(payload);
      setSelectedNodeId(payload.problem_node_id || "task-understanding");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "行为推演失败");
    } finally {
      setDryRunLoading(false);
    }
  }

  const selectedDetails = selectedNode
    ? {
        source_module: selectedNode.source_module,
        reasons: selectedNode.reasons,
        inputs: selectedNode.inputs,
        outputs: selectedNode.outputs,
        refs: selectedNode.refs
      }
    : null;
  const selectedReasonList = (selectedNode?.reasons ?? []).filter(Boolean).slice(0, 6);
  const selectedOutputPreview = selectedNode?.outputs
    ? Object.entries(selectedNode.outputs).slice(0, 6)
    : [];
  const normalizedCatalogQuery = catalogQuery.trim().toLowerCase();
  const visibleCatalogSkills = (catalog?.skills ?? []).filter((skill) => {
    if (!normalizedCatalogQuery) {
      return true;
    }
    return `${skill.runtime.name} ${skill.runtime.title} ${skill.runtime.description} ${skill.runtime.allowed_tools.join(" ")} ${skill.runtime.capability_tags.join(" ")}`
      .toLowerCase()
      .includes(normalizedCatalogQuery);
  });
  const visibleCatalogTools = (catalog?.tools ?? []).filter((tool) => {
    if (!normalizedCatalogQuery) {
      return true;
    }
    return `${tool.name} ${tool.module} ${tool.capability_tags.join(" ")} ${tool.safety_tags.join(" ")} ${tool.route_hints.join(" ")}`
      .toLowerCase()
      .includes(normalizedCatalogQuery);
  });

  return (
    <div className="workspace-view orchestration-console">
      <header className="workspace-view__header">
        <div>
          <p className="workspace-view__eyebrow">Orchestration Control Tower</p>
          <h2 className="workspace-view__title">编排系统</h2>
        </div>
        <div className="workspace-view__actions">
          <button className="action-button action-button--ghost" disabled={loading || target?.source !== "test-system"} onClick={() => void loadTargetSnapshot()} type="button">
            {loading ? <Loader2 className="animate-spin" size={15} /> : <RefreshCw size={15} />}
            刷新链路
          </button>
          <button className="action-button action-button--muted" onClick={() => setOrchestrationInspectorTarget(null)} type="button">
            看当前会话
          </button>
        </div>
      </header>

      <nav className="orchestration-tabs" aria-label="编排系统页面">
        {[
          { key: "behavior", label: "行为判读", icon: Route },
          { key: "skills", label: "Skills 管理", icon: Boxes },
          { key: "contracts", label: "契约管理", icon: ShieldCheck }
        ].map((item) => {
          const Icon = item.icon;
          return (
            <button
              className={activePanel === item.key ? "orchestration-tabs__item orchestration-tabs__item--active" : "orchestration-tabs__item"}
              key={item.key}
              onClick={() => setActivePanel(item.key as "behavior" | "skills" | "contracts")}
              type="button"
            >
              <Icon size={15} />
              {item.label}
            </button>
          );
        })}
      </nav>

      {error ? (
        <div className="workspace-alert">
          <AlertTriangle size={16} />
          <span>{error}</span>
        </div>
      ) : null}

      {activePanel === "skills" ? (
        <section className="workspace-section orchestration-management">
          <div className="workspace-section__head">
            <Boxes size={18} />
            <h3>Skills 管理</h3>
            <span className="tag-chip">{catalogLoading ? "加载中" : `${visibleCatalogSkills.length}/${catalog?.skills.length ?? 0}`}</span>
            <button className="action-button action-button--ghost" onClick={() => void refreshCatalog()} type="button">
              {catalogLoading ? <Loader2 className="animate-spin" size={14} /> : <RefreshCw size={14} />}
              刷新 Registry
            </button>
          </div>
          {catalogAction ? <div className="workspace-alert">{catalogAction}</div> : null}
          <div className="workspace-search">
            <Sparkles size={17} />
            <input onChange={(event) => setCatalogQuery(event.target.value)} placeholder="查 skill、allowed tools、能力标签或 route" value={catalogQuery} />
          </div>
          <div className="orchestration-management-grid">
            {visibleCatalogSkills.map((skill) => (
              <article className="orchestration-management-card" key={skill.runtime.name}>
                <div className="workspace-record__meta">
                  <span>{skill.runtime.preferred_route || "route"}</span>
                  <span>{skill.runtime.activation_policy}</span>
                  <span>{skill.runtime.context_mode}</span>
                </div>
                <h3>{skill.runtime.title || skill.runtime.name}</h3>
                <p>{skill.runtime.description}</p>
                <div className="workspace-chip-row">
                  {skill.runtime.allowed_tools.slice(0, 6).map((tool) => <span className="workspace-mini-chip" key={tool}>{tool}</span>)}
                </div>
                <div className="orchestration-management-card__contract">
                  <b>Prompt 可见</b>
                  <span>{skill.prompt_view.use_when || skill.prompt_view.output_rule}</span>
                </div>
                <button className="action-button action-button--muted" onClick={() => void loadInspectorFile(skill.runtime.path)} type="button">
                  打开并编辑定义
                </button>
              </article>
            ))}
          </div>
        </section>
      ) : activePanel === "contracts" ? (
        <section className="workspace-section orchestration-management">
          <div className="workspace-section__head">
            <ShieldCheck size={18} />
            <h3>契约管理</h3>
            <span className="tag-chip">permission: {catalog?.permission_mode ?? "-"}</span>
            <span className="tag-chip">contract: {catalog?.tool_contract_mode ?? "-"}</span>
            <button className="action-button action-button--ghost" onClick={() => void refreshCatalog()} type="button">
              {catalogLoading ? <Loader2 className="animate-spin" size={14} /> : <RefreshCw size={14} />}
              刷新 Registry
            </button>
          </div>
          <div className="orchestration-permission-bar">
            <div>
              <b>Permission Mode</b>
              <span>这里只切换运行权限模式；tool contract 本体保持只读，避免前端绕过安全边界。</span>
            </div>
            <select
              disabled={catalogLoading || !catalog}
              onChange={(event) => void changePermissionMode(event.target.value)}
              value={catalog?.permission_mode ?? ""}
            >
              {(catalog?.supported_permission_modes ?? []).map((mode) => (
                <option key={mode} value={mode}>{mode}</option>
              ))}
            </select>
          </div>
          {catalogAction ? <div className="workspace-alert">{catalogAction}</div> : null}
          <div className="workspace-search">
            <Hammer size={17} />
            <input onChange={(event) => setCatalogQuery(event.target.value)} placeholder="查 tool、契约字段、安全标签或 route hint" value={catalogQuery} />
          </div>
          <div className="orchestration-contract-grid">
            {visibleCatalogTools.map((tool) => (
              <article className={`orchestration-contract-card ${tool.is_destructive ? "orchestration-contract-card--danger" : ""}`} key={tool.name}>
                <div className="workspace-record__meta">
                  <span>{tool.safe_for_auto_route ? "auto-route" : "manual"}</span>
                  <span>{tool.runtime_visibility}</span>
                  <span>{tool.is_read_only ? "read-only" : "write-capable"}</span>
                </div>
                <h3>{tool.name}</h3>
                <p>{tool.module}</p>
                <div className="orchestration-contract-card__matrix">
                  <span><b>输入</b><em>{compactValue(tool.contract.required_inputs)}</em></span>
                  <span><b>绑定</b><em>{compactValue(tool.contract.required_bindings)}</em></span>
                  <span><b>缺失处理</b><em>{compactValue(tool.contract.missing_binding_behavior)}</em></span>
                  <span><b>输出</b><em>{compactValue(tool.output_contract.display_mode)}</em></span>
                </div>
                <div className="workspace-chip-row">
                  {[...tool.safety_tags, ...tool.capability_tags].slice(0, 7).map((tag) => <span className="workspace-mini-chip" key={tag}>{tag}</span>)}
                </div>
              </article>
            ))}
          </div>
        </section>
      ) : (
        <>

      <section className="workspace-section orchestration-dry-run">
        <div className="workspace-section__head">
          <BrainCircuit size={18} />
          <h3>行为逻辑 Dry-run</h3>
          <span className="tag-chip">不调用模型</span>
          <span className="tag-chip">不执行工具</span>
          <span className="tag-chip">不写记忆</span>
        </div>
        <div className="orchestration-dry-run__body">
          <textarea
            onChange={(event) => setDryRunMessage(event.target.value)}
            placeholder="输入一句用户请求，推演 Agent 会怎样理解、路由、选择 skill、读取上下文和预检工具契约..."
            value={dryRunMessage}
          />
          <button className="action-button action-button--primary" disabled={dryRunLoading || !currentSessionId} onClick={() => void submitDryRun()} type="button">
            {dryRunLoading ? <Loader2 className="animate-spin" size={15} /> : <Route size={15} />}
            开始推演
          </button>
        </div>
      </section>

      <section className={`orchestration-hero orchestration-hero--${snapshot.status}`}>
        <div className="orchestration-hero__signal">
          <span>{sourceLabel(snapshot.source)}</span>
          <strong>{problemNode ? `问题在 #${problemNode.index}：${problemNode.label}` : `这轮会走：${readableRoute}`}</strong>
          <p>{problemNode ? problemNode.summary || snapshot.summary : snapshot.summary}</p>
        </div>
        <div className="orchestration-hero__metrics">
          <span><b>{snapshot.execution_mode || "unknown"}</b> 执行模式</span>
          <span><b>{snapshot.route || "unknown"}</b> 路由</span>
          <span><b>{visitedCount}/{snapshot.nodes.length}</b> 节点经过</span>
          <span><b>{snapshot.events.length}</b> 事件</span>
        </div>
      </section>

      <section className="orchestration-brief">
        <article className="orchestration-brief__card orchestration-brief__card--primary">
          <span>行为结论</span>
          <strong>{readableRoute}</strong>
          <p>{executionNode?.summary || "等待 planner 产出执行落点。"}</p>
        </article>
        <article className="orchestration-brief__card">
          <span>上下文策略</span>
          <strong>{contextNode?.status === "skipped" ? "跳过" : contextNode?.label || "未记录"}</strong>
          <p>{contextNode?.summary || "还没有上下文选择信息。"}</p>
        </article>
        <article className="orchestration-brief__card">
          <span>能力策略</span>
          <strong>{skillNode?.summary?.split("/")[0] || skillNode?.label || "未选择"}</strong>
          <p>{skillNode?.summary || "还没有 skill / capability 信息。"}</p>
        </article>
        <article className={`orchestration-brief__card ${problemNode ? "orchestration-brief__card--alert" : ""}`}>
          <span>{problemNode ? "当前阻断" : "契约边界"}</span>
          <strong>{problemNode ? `#${problemNode.index} ${problemNode.label}` : contractNode?.status || "正常"}</strong>
          <p>{problemNode?.summary || contractNode?.summary || "没有发现明显契约阻断。"}</p>
        </article>
      </section>

      <section className="workspace-section orchestration-map">
        <div className="workspace-section__head">
          <GitBranch size={18} />
          <h3>行为路径</h3>
          {snapshot.run_id ? <span className="tag-chip">{snapshot.run_id}</span> : null}
          {snapshot.turn_index ? <span className="tag-chip">Turn {snapshot.turn_index}</span> : null}
        </div>
        <div className="orchestration-stage-grid">
          {stageGroups.map((group) => {
            const groupNodes = group.nodes.map((id) => nodeById.get(id)).filter(Boolean) as OrchestrationNode[];
            if (!groupNodes.length) {
              return null;
            }
            const activeCount = groupNodes.filter((node) => node.status !== "idle" && node.status !== "skipped").length;
            return (
              <article className="orchestration-stage" key={group.title}>
                <header>
                  <span>{group.title}</span>
                  <strong>{activeCount}/{groupNodes.length}</strong>
                  <p>{group.hint}</p>
                </header>
                <div className="orchestration-stage__nodes">
                  {groupNodes.map((node) => (
                    <button
                      className={`orchestration-node orchestration-node--${node.status} ${selectedNode?.id === node.id ? "orchestration-node--selected" : ""}`}
                      key={node.id}
                      onClick={() => setSelectedNodeId(node.id)}
                      type="button"
                    >
                      <span>#{String(node.index).padStart(2, "0")}</span>
                      <i>{nodeIcon(node.id)}</i>
                      <strong>{node.label}</strong>
                      {node.source_module ? <small>{node.source_module}</small> : null}
                      <em>{node.summary || node.description}</em>
                    </button>
                  ))}
                </div>
              </article>
            );
          })}
        </div>
        <div className="orchestration-branches">
          {branchNodes.length ? branchNodes.map((node) => (
            <button
              className={`orchestration-branch orchestration-branch--${node.status} ${selectedNode?.id === node.id ? "orchestration-branch--selected" : ""}`}
              key={node.id}
              onClick={() => setSelectedNodeId(node.id)}
              type="button"
            >
              <span>{nodeIcon(node.id)} 分支节点 #{node.index}</span>
              <strong>{node.label}</strong>
              {node.source_module ? <small>{node.source_module}</small> : null}
              <p>{node.summary || node.description}</p>
            </button>
          )) : (
            <article className="orchestration-branch orchestration-branch--idle">
              <span><TerminalSquare size={16} /> 分支节点</span>
              <strong>本轮未观测到工具或 worker 分支</strong>
              <p>如果请求触发 direct tool、模型工具调用或 evidence worker，这里会展开对应分支。</p>
            </article>
          )}
        </div>
      </section>

      <section className="orchestration-detail-grid">
        <article className="workspace-section orchestration-detail">
          <div className="workspace-section__head">
            <FileText size={18} />
            <h3>节点详情</h3>
            {selectedNode ? <span className="tag-chip">#{selectedNode.index} {selectedNode.status}</span> : null}
          </div>
          {selectedNode ? (
            <>
              <span>{selectedNode.source_event || "没有绑定单一事件"}</span>
              <strong>{selectedNode.label}</strong>
              <p>{selectedNode.description}</p>
              <pre>{selectedNode.summary || "这个节点在当前链路中还没有产生摘要。"}</pre>
              {selectedReasonList.length ? (
                <div className="orchestration-reasons">
                  {selectedReasonList.map((reason) => <span key={reason}>{reason}</span>)}
                </div>
              ) : null}
              {selectedOutputPreview.length ? (
                <div className="orchestration-kv">
                  {selectedOutputPreview.map(([key, value]) => (
                    <span key={key}>
                      <b>{key}</b>
                      <em>{compactValue(value)}</em>
                    </span>
                  ))}
                </div>
              ) : null}
              {selectedDetails ? (
                <details className="orchestration-json">
                  <summary>查看原始决策数据</summary>
                  <pre>{jsonText(selectedDetails)}</pre>
                </details>
              ) : null}
              <div className="orchestration-detail__actions">
                <button onClick={() => locateOnSystemGraph(selectedNode)} type="button">
                  <Network size={14} />
                  系统框架定位
                </button>
                {selectedNode.id === "memory" ? (
                  <button onClick={openMemoryNode} type="button">
                    <BrainCircuit size={14} />
                    查看状态记忆
                  </button>
                ) : null}
                {selectedNode.id === "tool" ? (
                  <button onClick={() => setActivePanel("contracts")} type="button">
                    <TerminalSquare size={14} />
                    查看契约管理
                  </button>
                ) : null}
                {selectedNode.id === "worker" ? (
                  <button onClick={() => setWorkspaceView("evidence")} type="button">
                    <Network size={14} />
                    查看 agent 系统
                  </button>
                ) : null}
              </div>
            </>
          ) : null}
        </article>

        <article className="workspace-section orchestration-events">
          <div className="workspace-section__head">
            <Route size={18} />
            <h3>事件时间线</h3>
            <span className="tag-chip">{snapshot.events.length} events</span>
          </div>
          <div className="orchestration-events__list">
            {snapshot.events.length ? snapshot.events.map((event) => (
              <button
                className={`orchestration-event ${selectedNode?.id === event.node_id ? "orchestration-event--active" : ""}`}
                key={`${event.index}-${event.event}`}
                onClick={() => setSelectedNodeId(event.node_id)}
                type="button"
              >
                <span>{event.index}</span>
                <strong>{event.event}</strong>
                <ArrowRight size={13} />
                <em>{event.summary}</em>
              </button>
            )) : (
              <article className="workspace-record">
                <h3>{snapshot.source === "dry-run" ? "这是无副作用行为推演" : "还没有运行事件"}</h3>
                <p>{snapshot.source === "dry-run" ? "dry-run 不产生 SSE 时间线，请在左侧节点详情里查看每个行为决策。" : "发送一条消息后，这里会出现 SSE 编排事件；也可以从测试系统选择 turn 来复盘。"}</p>
              </article>
            )}
          </div>
        </article>
      </section>
        </>
      )}
    </div>
  );
}
