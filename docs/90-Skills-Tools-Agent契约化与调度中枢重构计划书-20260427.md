# Skills、Tools、Agent 契约化与调度中枢重构计划书

日期：2026-04-27

## 一、问题定义

当前系统已经具备比较完整的能力组件：`skills` 提供能力说明，`tools` 提供实际执行动作，`agent / worker` 提供可委派执行单元，`context_management` 提供会话、状态、记忆与证据上下文。但调度链路里仍有大量启发式判断，尤其集中在：

- `understanding/task_understanding.py`：通过规则判断 PDF、表格、RAG、本地搜索、联网搜索、天气、金价等意图。
- `query/planner.py` 与 `query/runtime.py`：在已有理解结果基础上继续决定 route、worker、tool、active skill。
- `query/runtime_tools.py`：根据 route、execution posture、skill scope 和 tool contract 决定是否直接调用工具。
- `query/output_classifier.py`：通过文本正则判断输出是进度、工具结果、答案候选还是兜底结果。

这些启发式短期有效，但长期会形成“隐藏调度脑”：模型以为自己在理解任务，后端也在理解任务，两边可能互相覆盖。正确目标不是删除所有规则，而是重新划分职责：

- `大模型` 负责理解用户意图、选择能力、生成执行计划。
- `skills / tools / agents` 负责提供标准化、模型可见且后端可校验的能力契约。
- `调度中枢` 负责计划校验、权限裁决、执行编排和回滚，而不是靠规则猜测用户意图。
- `上下文管理` 负责提供状态、记忆、证据、文件句柄和 token 预算，不直接替代调度决策。

## 二、当前代码依据

### 2.0 当前运行架构复盘

当前后端实际执行链路不是一个独立的 `orchestration` 主链，而是由 `QueryRuntime` 串联多个系统：

```text
api/chat
  -> QueryRuntime._execution_events()
  -> RuntimeContextState 读取 session authoritative context
  -> QueryPlanner.build_plan()
     -> understanding / memory_intent / continuation / bundle / skill / capability dispatch
  -> orchestration.adapters.build_orchestration_plan()
     -> 将 legacy QueryPlan 投影成 OrchestrationPlan
  -> orchestration.runtime_adapter.build_runtime_control()
     -> plan_only 只观测，primary 只做 execution 顺序接管
  -> RuntimeToolBridge / worker / model 主链执行
  -> memory_context / prompt_manifest / output_boundary / persistence
  -> orchestration.diff 复盘计划与实际执行
```

这意味着现在的真实架构有四个事实：

- `QueryRuntime` 仍是事实上的总线，理解、记忆、上下文、工具、worker、输出收口都在这里汇合。
- `QueryPlanner` 仍是事实上的任务仲裁器，里面同时包含理解结果、续接恢复、bundle/fanout、skill、tool、worker 和搜索权限过滤。
- `orchestration` 已经有 `OrchestrationPlan / runtime_adapter / diff / behavior_trace`，但主要是对 legacy `QueryPlan` 的投影、可视化和最小 primary 接管。
- `capabilities` 已经开始成为操作系统的资源事实源，能描述 skills、tools、agents、绑定关系和 search policy，但还没有成为 runtime 编排的强输入。

因此，本计划后续不能把“编排层重构”理解成只新增一个 planner。真正要做的是把 `QueryRuntime` 中散落的跨系统决策，逐步收敛为一个 canonical control plane。

### 2.0.1 编排层的新位置

新的编排层必须位于四类系统之间：

```text
理解层 ----------\
记忆系统 ---------\
上下文管理 --------> OrchestrationPlan -> RuntimeControl -> 执行链
操作系统 ---------/
测试系统 <-------- trace / diff / report
```

各系统职责边界如下：

| 系统 | 现在已有职责 | 编排重构后的输出 | 不能做的事 |
| --- | --- | --- | --- |
| 理解层 | 识别 route、task_kind、source_kind、tool candidates | `IntentFrame` 候选 | 直接决定最终 tool/agent |
| 记忆系统 | session memory、durable memory、状态槽、投影写回 | `MemoryPolicy` 与状态候选 | 用历史状态覆盖当前轮目标 |
| 上下文管理 | compact、prompt 片段、相关记忆、检索证据、预算 | `ContextPolicy` | 决定执行路径 |
| 操作系统 | skills、tools、agents、绑定、启停、权限资源 | `ResourcePolicy` | 绕过 validator 打开执行资源 |
| 编排层 | 目前主要投影 legacy plan | canonical `OrchestrationPlan` | 绕过权限系统直接执行 |
| 测试系统 | 回放 trace、报告 diff、定位节点 | 验证 `OrchestrationPlan` 与 actual trace | 反向影响运行时决策 |

编排层的核心价值不是“多一个模块”，而是给一次用户请求提供唯一、可解释、可验证、可回滚的行为计划。

### 2.1 Skills 现状

相关文件：

- `backend/skill_system/contracts.py`
- `backend/skill_system/registry.py`
- `backend/tools/skills_scanner.py`
- `backend/SKILLS_REGISTRY.json`
- `backend/SKILLS_SNAPSHOT.md`

当前已有 `SkillRuntimeContract`、`SkillPromptContract`、`SkillContract`。其中 `SkillRuntimeContract` 已包含：

- `allowed_tools`
- `supported_modalities`
- `supported_task_kinds`
- `supported_source_kinds`
- `capability_tags`
- `preferred_route`
- `activation_policy`
- `context_mode`
- `route_authority`

这说明 skills 已经接近“能力契约”，但还缺少三个关键能力：

- 面向编排中枢的结构化导出，不只是 `render_prompt_block()`。
- 与 tool / agent 的绑定一致性校验。
- 前端编辑后对注册表、模型可见 prompt、调度可见契约的统一刷新机制。

### 2.2 Tools 现状

相关文件：

- `backend/tools/definitions.py`
- `backend/tools/contracts.py`
- `backend/tools/runtime.py`
- `backend/tools/tool_registry.py`
- `backend/TOOLS_REGISTRY.json`
- `backend/api/operations.py`

当前 `ToolDefinition` 已经包含较完整的契约：

- `ToolExecutionContract`
- `ToolResolutionContract`
- `ToolOutputContract`
- `ToolProjectionContract`
- `runtime_visibility`
- `prompt_exposure_policy`
- `resource_exposure_policy`
- `safe_for_auto_route`
- `is_read_only`
- `is_destructive`
- `is_concurrency_safe`

这说明 tools 已经具备“后端执行契约”，但还需要补齐：

- 搜索来源分类：RAG、本地文件、联网、文档、结构化数据、系统执行。
- 与搜索权限 UI 的映射。
- 与 skill 的授权关系。
- 与 agent / worker 的归属关系。
- 给编排中枢和模型可见 prompt 的安全摘要，而不是完整暴露后端实现。

### 2.3 Agent / Worker 现状

相关文件：

- `backend/agents/a2a_cards.py`
- `backend/api/agents.py`
- `backend/query/worker_models.py`
- `backend/query/pdf_worker.py`
- `backend/query/retrieval_worker.py`
- `backend/query/structured_data_worker.py`
- `backend/query/evidence_orchestrator.py`

当前系统已经有 A2A-compatible agent card，并通过 MCP profile 持有工具：

- `agent:knowledge:retrieval` 持有 `search_knowledge`
- `agent:document:pdf` 持有 `pdf_analysis`、`analyze_multimodal_file`
- `agent:data:structured` 持有 `structured_data_analysis`

这正好支持目标方向：主 agent 不需要直接负责所有工具，专用能力应下沉到子 agent。问题是当前 agent 工具归属仍更像“展示配置”，还没有成为统一调度约束。

### 2.4 Prompt 与上下文现状

相关文件：

- `backend/query/prompt_builder.py`
- `backend/query/long_term_context.py`
- `backend/query/runtime_context_state.py`
- `backend/query/prompt_manifest.py`
- `backend/query/models.py`

`prompt_builder.py` 当前会注入：

- `SKILLS_SNAPSHOT.md`
- 灵魂/长期上下文
- 会话情境
- active skill
- 当前相关长期记忆

这说明模型已经能看到部分能力摘要，但尚未看到一个完整、结构化、可规划的 `Capability Manifest`。后续调度不应该只依赖自然语言 snapshot，而应该读取结构化能力清单：

- 可用 skills
- 可用 tools
- 可用 agents
- 本轮搜索权限
- 当前上下文状态
- 缺失绑定
- 风险与确认要求

## 三、设计原则

### 3.1 先契约化，再重构调度

第一阶段不重写调度中枢。先把能力资源整理成单一事实源，否则后续编排中枢会面对不稳定的能力目录。

### 3.2 模型自由调度，后端硬边界校验

模型可以自由选择 skill、tool、agent，但后端必须校验：

- 搜索权限是否允许。
- skill 是否允许该 tool。
- tool 是否归属该 agent。
- tool contract 是否满足。
- 是否缺少 `active_pdf`、`active_dataset`、文件路径或 URL。
- 高风险工具是否需要人工确认。

### 3.3 Skill 不等于 Tool

Skill 是“能力意图层”，Tool 是“执行资源层”。Skill 负责说明模型什么时候使用某类能力，Tool 负责执行具体动作。

### 3.4 Agent 是工具归属与执行边界

Agent / worker 不是 UI 分类，而是执行责任边界。PDF tool 应归文档智能体，结构化数据 tool 应归结构化数据智能体，RAG tool 应归检索智能体。主 agent 只负责理解、收束、用户响应和少量主运行时工具。

### 3.5 上下文管理只提供状态，不替调度决策

上下文管理提供：

- 当前会话历史
- 状态记忆
- 长期记忆
- 文件句柄
- active PDF / active dataset
- 检索证据
- token 预算

但是否使用某个能力，应由编排中枢生成计划，再由调度层校验。

### 3.6 操作系统是执行层行为与资源管理系统

前端不再把 `agent系统` 作为独立孤立模块维护。Agent / worker 本质上属于执行层资源与行为边界，应拆分后并入 `操作系统`。

操作系统的定位调整为：

- 管理 `skills`：模型可见能力说明、能力意图、允许工具、推荐 agent。
- 管理 `tools`：执行资源、搜索来源、风险边界、输入输出契约。
- 管理 `agents / workers`：执行单元、工具归属、启停状态、委派边界。
- 管理 `protocols`：agent 之间的输入输出契约、handoff 策略、通信链路。
- 管理 `bindings`：skill -> tool、agent -> tool、agent -> agent 的关系图。

也就是说，操作系统不是“工具页”，而是整个智能体执行层的资源与行为控制面。测试系统负责验证，记忆系统负责状态，编排系统负责运行计划，而操作系统负责定义“有哪些能力、谁能用、谁执行、边界是什么”。

## 四、目标架构

### 4.1 能力契约层

新增统一能力契约视图：

```text
CapabilityManifest
  ├─ skills: SkillCapability[]
  ├─ tools: ToolCapability[]
  ├─ agents: AgentCapability[]
  ├─ bindings:
  │   ├─ skill_to_tools
  │   ├─ agent_to_tools
  │   └─ agent_to_agents
  ├─ search_sources
  ├─ context_state
  └─ policy
```

该 manifest 是编排中枢、前端操作系统、测试系统、trace 系统共同读取的能力事实源。

### 4.2 Skills 契约

目标字段：

```json
{
  "name": "pdf-reading",
  "title": "PDF 阅读",
  "description": "读取 PDF、页码、章节与引用证据。",
  "model_visible_prompt": "...",
  "allowed_tools": ["pdf_analysis", "analyze_multimodal_file"],
  "preferred_agents": ["agent:document:pdf"],
  "source_kinds": ["document", "pdf"],
  "task_kinds": ["document_qa", "summarization"],
  "activation_policy": "model_visible",
  "route_authority": "candidate_only",
  "risk_policy": "normal",
  "validation_errors": []
}
```

Skill 的重点不是执行，而是告诉模型：

- 这个能力解决什么问题。
- 什么时候应该考虑使用。
- 它允许哪些工具。
- 它偏向哪个 agent。
- 它的输出应该如何被最终回答使用。

### 4.3 Tools 契约

目标字段：

```json
{
  "name": "web_search",
  "source_class": "web",
  "execution_boundary": "external_network",
  "runtime_visibility": "main_runtime",
  "prompt_exposure_policy": "schema_only",
  "required_inputs": ["query"],
  "required_bindings": [],
  "risk_level": "medium",
  "safe_for_auto_route": true,
  "owner_agents": ["agent:main:conversation"],
  "allowed_search_policy": ["web"],
  "output_contract": {
    "display_mode": "summary_text",
    "persistence_policy": "persist_canonical"
  }
}
```

Tool 的重点是：

- 类型与来源清楚。
- 输入要求清楚。
- 风险清楚。
- 是否允许自动路由清楚。
- 归属 agent 清楚。
- 输出如何进入上下文清楚。

### 4.4 Agent 契约

目标字段：

```json
{
  "agent_id": "agent:document:pdf",
  "name": "文档智能体",
  "worker_route": "pdf",
  "owned_tools": ["pdf_analysis", "analyze_multimodal_file"],
  "accepted_task_kinds": ["document_qa", "pdf_page_lookup"],
  "input_contract": "用户问题 + PDF 句柄/路径 + 页码/章节约束",
  "output_contract": "规范化文档答案 + 页码引用 + 降级原因",
  "handoff_policy": "文档智能体负责证据定位，主 agent 只负责收束用户答案。",
  "enabled": true
}
```

Agent 的重点是：

- 它负责什么任务。
- 它拥有哪些工具。
- 它接受什么输入。
- 它返回什么输出。
- 它和其他 agent 如何通信。

### 4.5 调度中枢目标形态

第二阶段调度中枢不再被理解为“新增一个模型 Planner”。它的目标是把理解层、记忆系统、上下文管理和操作系统提交的候选信息，收束成唯一的 `OrchestrationPlan`，再交给 runtime control 执行。

```text
Chat Request + search_policy
  ↓
理解层输出 IntentFrame 候选
  ↓
记忆系统输出 MemoryPolicy 与状态候选
  ↓
上下文管理输出 ContextPolicy 与可恢复句柄
  ↓
操作系统输出 ResourcePolicy 所需的 CapabilityManifest / BindingGraph
  ↓
OrchestrationCoordinator 生成 canonical OrchestrationPlan
  ↓
PlanValidator 校验权限 / 契约 / 风险 / 绑定 / 状态隔离
  ↓
RuntimeControl 生成 ExecutionDirective
  ↓
QueryRuntime / RuntimeToolBridge / Worker 执行
  ↓
AnswerFinalizer 收束答案，ContextManager 写入允许写入的状态
```

这一层的边界必须非常硬：

- 理解层可以判断“看起来像 PDF 问答”，但不能直接指定 `pdf_analysis` 一定执行。
- 记忆系统可以恢复上轮文件、目标、偏好，但不能用旧状态覆盖本轮用户目标。
- 上下文管理可以装配 prompt、预算和证据句柄，但不能决定最终 route。
- 操作系统可以提供 skill / tool / agent 的事实源，但不能绕过 validator 打开权限。
- 编排层负责仲裁本轮计划，但执行仍必须通过 `RuntimeToolBridge`、worker 和权限系统。

### 4.6 前端工作台目标形态

工作台中的前端模块应收敛为更清楚的职责：

- `编排系统`：展示编排计划、validator decision、runtime control、executor trace、运行链路和调度结果。
- `测试系统`：运行冒烟、稳定门禁、长场景测试，回放编排 / tool / agent trace。
- `操作系统`：统一管理执行层资源与行为，包括 skills、tools、agents、workers、通信协议和绑定关系。
- `记忆系统`：管理对话记忆、状态记忆、长期记忆，以及上下文注入结果。

当前 `agent系统` 前端应拆开并入 `操作系统`：

- Agent 启停并入操作系统的 `执行单元` 页。
- Agent 拓扑并入操作系统的 `资源拓扑` 页。
- Agent 通信协议并入操作系统的 `通信契约` 页。
- Agent handoff 流程并入操作系统的 `执行关系` 或 `绑定关系` 页。

完成后，右侧工作台不再单列 `agent系统`，避免用户在“工具归属、子 agent、skills 授权、通信协议”之间来回跳转。

## 五、第一阶段：Skills / Tools / Agent 契约化

### 5.1 阶段目标

在不大改运行链路的前提下，完成统一能力事实源，让前端和后端都能清楚显示：

- 每个 skill 能调用哪些 tools。
- 每个 tool 归属哪个 agent。
- 每个 agent 持有哪些 tools。
- 每个 tool 属于 RAG、本地文件、联网、文档、结构化数据还是系统执行。
- 每个 tool 的风险、权限和上下文依赖。

### 5.2 数据模型改造

新增或强化：

- `backend/capabilities/models.py`
- `backend/capabilities/manifest.py`
- `backend/capabilities/validation.py`
- `backend/capabilities/search_policy.py`

建议模型：

- `SearchSourcePolicy`
- `CapabilityManifest`
- `SkillCapability`
- `ToolCapability`
- `AgentCapability`
- `CapabilityBindingGraph`
- `CapabilityValidationIssue`

### 5.3 后端文件级任务

#### `backend/skill_system/contracts.py`

补充：

- `preferred_agents`
- `source_classes`
- `model_visible_level`
- `orchestration_notes`
- `risk_policy`

完成标准：

- skill registry 中每个 skill 都能导出编排中枢可读结构。
- 不破坏现有 `render_prompt_block()`。

#### `backend/tools/contracts.py`

补充：

- `ToolSourceClass`
- `ToolExecutionBoundary`
- `ToolRiskLevel`
- `ToolSearchPolicyBinding`

完成标准：

- 每个 tool 都能明确归类到搜索来源或执行来源。
- `search_knowledge` 属于 RAG。
- `search_files`、`search_text`、`read_file` 属于本地文件。
- `web_search`、`fetch_url` 属于联网。
- `pdf_analysis` 属于文档 agent 内部工具。
- `terminal`、`python_repl` 属于系统执行高风险工具。

#### `backend/agents/a2a_cards.py`

补充：

- agent owned tools 的强类型导出。
- accepted task kinds。
- owned source classes。

完成标准：

- agent card 不只是展示资料，而是能力归属契约的一部分。

#### `backend/api/operations.py`

重构：

- 从临时 `_operation_tool_metadata()` 迁移到 `CapabilityManifest`。
- `/operations/catalog` 返回统一 manifest。
- 绑定管理继续支持 skill allowed_tools 编辑。

完成标准：

- 前端操作系统不再自己推断关系，只读取 manifest。

### 5.4 前端任务

相关文件：

- `frontend/src/components/workspace/views/OperationsView.tsx`
- `frontend/src/components/workspace/views/EvidenceView.tsx`
- `frontend/src/components/layout/RightRail.tsx`
- `frontend/src/components/workspace/WorkspacePanel.tsx`
- `frontend/src/lib/store/types.ts`
- `frontend/src/lib/api.ts`
- `frontend/src/app/globals.css`

改造目标：

- 操作系统分成五个核心页：
- `能力契约`：总览 skill/tool/agent 的统一能力关系。
- `工具管理`：管理 tool 类型、风险、来源、归属和执行契约。
- `Skills 管理`：管理模型可见能力、allowed_tools、推荐 agent。
- `执行单元`：承接原 agent 系统的启停、能力卡片、worker route、owned tools。
- `通信契约`：承接原 agent 系统的协议连线、输入输出契约和 handoff 策略。
- `绑定关系`：管理 skill -> tool、agent -> tool、agent -> agent 的关系图。

迁移要求：

- `EvidenceView.tsx` 中可复用的 agent 拓扑、启停、协议编辑逻辑迁入 `OperationsView.tsx` 或拆成 `operations/` 子组件。
- `RightRail.tsx` 中移除独立 `agent系统` 入口，保留 `操作系统` 作为统一执行层管理入口。
- `WorkspacePanel.tsx` 和 `WorkspaceView` 类型移除或兼容旧 `evidence` view，避免旧入口悬空。
- 后端 `/api/agents/*` 可以保留为操作系统内部 API，也可以在后续收敛进 `/api/operations/*`；第一阶段不强制删除，避免影响现有功能。

搜索权限按钮在后续对话框旁边实现，但它读取的底层来源分类应来自同一个 manifest。

## 六、第二阶段：正式编排中枢重构

### 6.1 阶段目标

将当前散落在 `QueryPlanner`、`QueryRuntime`、能力派发、上下文恢复、工具可见性和输出收口中的跨系统决策，逐步迁移到正式编排中枢。模型可以参与理解和候选计划生成，但不能成为唯一事实源；最终运行依据必须是经过 validator 校验的 canonical `OrchestrationPlan`。

第二阶段的核心不是“让模型自由调用一切”，而是：

- 让模型在可见契约内理解用户目标。
- 让能力系统提供可执行资源边界。
- 让记忆和上下文只提交候选与约束。
- 让编排中枢统一仲裁本轮计划。
- 让 runtime 只消费通过校验的 directive。

### 6.2 新增核心模型

优先扩展现有编排层，而不是在 `backend/query` 下再建一套并行 planner：

- `backend/orchestration/models.py`
- `backend/orchestration/adapters.py`
- `backend/orchestration/runtime_adapter.py`
- `backend/orchestration/directives.py`（如模型过大再拆分）
- `backend/orchestration/validation.py`

核心 schema：

```json
{
  "intent_frame": {
    "user_goal": "...",
    "task_kind": "document_qa",
    "source_needs": ["local_files", "pdf"],
    "freshness_required": false,
    "needs_tool": true,
    "needs_agent": true
  },
  "memory_policy": {
    "use_session_state": true,
    "use_durable_memory": false,
    "restored_candidates": ["active_pdf"],
    "writeback_scope": ["state_memory"]
  },
  "context_policy": {
    "required_handles": ["active_pdf"],
    "evidence_budget": "normal",
    "prompt_sections": ["soul", "skill", "state", "evidence"]
  },
  "resource_policy": {
    "allowed_sources": ["local_files"],
    "allowed_skills": ["pdf-reading"],
    "allowed_agents": ["agent:document:pdf"],
    "allowed_tools": ["pdf_analysis"]
  },
  "execution_directives": [
    {
      "step_id": "step_1",
      "action": "delegate_agent",
      "skill": "pdf-reading",
      "agent_id": "agent:document:pdf",
      "tool": "pdf_analysis",
      "inputs": {
        "query": "...",
        "use_active_pdf": true
      }
    }
  ],
  "answer_policy": {
    "require_citations": true,
    "hide_internal_protocol": true
  }
}
```

字段定位：

- `IntentFrame`：表达本轮用户目标、任务类型、风险信号和来源需求。
- `MemoryPolicy`：说明哪些记忆可读、哪些状态可恢复、哪些结果允许写回。
- `ContextPolicy`：说明 prompt 装配、证据预算、文件/数据句柄和压缩策略。
- `ResourcePolicy`：说明本轮允许使用的 skill、tool、agent、worker 与来源权限。
- `ExecutionDirective`：说明执行步骤、执行归属、输入摘要、共享通道和失败降级。
- `AnswerPolicy`：说明答案引用、内部协议隐藏、fallback 和最终输出边界。

### 6.3 PlanValidator 职责

PlanValidator 是硬边界，不允许任何模型计划、前端编辑或旧链路恢复绕过：

- 当前搜索权限是否允许该来源。
- skill 是否允许 tool。
- agent 是否持有 tool。
- tool contract 是否满足。
- 是否需要 active binding。
- 高风险工具是否需要用户确认。
- worker 是否开启。
- 输出是否允许进入长期记忆。
- 恢复的状态是否与本轮用户目标冲突。
- 子 agent / worker 的状态写入是否显式声明共享通道。
- `ExecutionDirective` 是否仍会通过 `RuntimeToolBridge` 的工具可见性过滤。

### 6.4 迁移策略

采用三段式：

#### Plan-only Mode

正式编排中枢生成计划，但旧链路继续执行。测试系统记录：

- 旧链路 route
- 编排 intent
- 编排 directive
- 实际执行
- 差异原因

#### Guarded Primary Scope

低风险任务开始消费编排 directive，但不新增 `assisted` 模式名，避免形成第三套语义。运行时仍使用 `primary`，只是通过 allowlist 限定可接管范围：

- RAG
- 本地文件搜索
- PDF 分析
- 结构化数据分析

高风险任务继续旧链路或人工确认：

- terminal
- python_repl
- 写入/索引类工具

#### Primary Mode

正式编排中枢成为主调度中枢，启发式降级为：

- fallback
- validator
- safety guard
- legacy debug baseline

## 七、与上下文管理的关系

### 7.1 ContextFrame

上下文管理输出给编排中枢的不是完整 prompt，也不是最终 route，而是结构化 ContextFrame / ContextPolicy：

```json
{
  "session_id": "...",
  "active_goal": "...",
  "active_pdf": "...",
  "active_dataset": null,
  "available_file_handles": [],
  "recent_dialogue_summary": "...",
  "durable_memory_hits": [],
  "retrieval_evidence": [],
  "token_budget": {
    "pressure": "normal"
  }
}
```

### 7.2 上下文管理不得直接做的事

- 不直接决定最终 route。
- 不把旧状态当作当前任务真相。
- 不在没有编排请求时自动注入大量材料。
- 不把工具原始输出直接变成最终答案。

### 7.3 上下文管理必须做的事

- 提供可验证状态。
- 提供缺失绑定信息。
- 提供候选证据。
- 保存工具执行后的 canonical summary。
- 记录每一步进入 prompt 的来源。

## 八、固定执行流

第一阶段完成后的执行流：

```text
Operations API / CapabilityManifest
  ↓
前端操作系统展示与管理绑定关系
  ↓
旧 QueryPlanner / Runtime 继续执行
  ↓
RuntimeToolBridge 使用增强后的 skill scope 和 tool contract 校验
```

第二阶段完成后的执行流：

```text
Chat Request + SearchPolicy
  ↓
IntentFrame candidate
  ↓
MemoryPolicy candidate
  ↓
ContextPolicy candidate
  ↓
CapabilityManifest / BindingGraph
  ↓
OrchestrationCoordinator
  ↓
PlanValidator
  ↓
RuntimeControl / ExecutionDirective
  ↓
Tool / Agent / Worker
  ↓
ContextManager 写入状态与 trace
  ↓
AnswerFinalizer
```

## 九、实施阶段与完成标准

### Phase 1：能力契约层落地

目标：

- 建立 `backend/capabilities`。
- 统一导出 skill/tool/agent manifest。
- 操作系统读取 manifest。
- 前端 agent 系统拆分并入操作系统。

完成标准：

- `GET /api/operations/catalog` 可返回完整 manifest。
- 每个 tool 都有来源分类、风险、归属 agent。
- 每个 skill 都能显示 allowed_tools。
- PDF tools 不归主 agent。
- 右侧工作台不再单列 `agent系统`，agent 启停、拓扑、通信协议都能在操作系统中完成。
- 回归测试覆盖 manifest 一致性。

### Phase 2：搜索来源权限接入

目标：

- 对话框旁边支持 RAG、本地文件、联网搜索权限。
- chat request 增加 `search_policy`。
- Tool / Skill / Agent 校验读取该权限。

完成标准：

- 关闭联网时，`web_search` 和 `fetch_url` 不会被编排中枢或旧链路调用。
- 关闭本地文件时，`search_files`、`search_text`、`read_file` 不会自动调用。
- 关闭 RAG 时，`search_knowledge` 不参与召回。

### Phase 3：正式编排中枢契约

目标：

- 新增正式编排中枢 schema。
- 输出 `IntentFrame / MemoryPolicy / ContextPolicy / ResourcePolicy / ExecutionDirective / AnswerPolicy`。
- 第一小步只生成 plan 事件和可视化，不切换主执行链。

完成标准：

- 测试系统可看到每轮编排中枢计划。
- 编排系统能解释每一步选择的 skill/tool/agent。
- runtime 仍由旧链路执行，但正式 directive 已可被 validator 读取。

### Phase 4：低风险能力切到正式编排中枢

目标：

- 在 `primary` 模式下只让 allowlist 内低风险能力读取正式 directive。
- RAG、本地搜索、PDF、结构化数据优先读取正式 directive。
- PlanValidator 拦截非法计划。

完成标准：

- 长场景测试通过。
- 文件处理警告下降。
- trace 能解释每一步为何选择该 skill/tool/agent。

### Phase 5：Primary 接管条件加固与报告闭环

目标：

- 不急于删除旧链路，先把 `primary` 接管条件变严。
- 对正式契约完整性、validator、allowlist、legacy execution 对齐做 fail-closed 校验。
- 把 RuntimeControl 的 fallback 原因、字段 mismatch、接管状态写入前端和长场景报告。

完成标准：

- 缺少 `IntentFrame / MemoryPolicy / ContextPolicy / ResourcePolicy / ExecutionDirective / AnswerPolicy / Validation / Executions` 任一核心字段时，必须回退旧链路。
- directive 与 legacy execution 的 `route / execution_kind / tool / worker_route / skill` 不一致时，必须回退旧链路。
- 前端能直接显示 `contract_blockers / allowlist_blockers / execution_mismatches`。
- 长场景报告能聚合 `runtime_control_source_counts / runtime_control_warning_counts / runtime_control_fallback_turns`。
- core 长场景无非预期 runtime fallback。

### Phase 6：低风险执行入口选择

目标：

- 把低风险 `primary` 从“只重排 legacy execution”推进到“能明确选择执行入口”。
- 初始只做入口计划、资格诊断和预检结论，不直接创建新执行对象。
- 为后续 `PrimaryExecutionAdapter` 做双轨对照准备。

子阶段拆分：

- Phase 6A：入口计划可观测化，只输出 `execution_entries`。
- Phase 6B：入口计划进入长场景报告聚合。
- Phase 6C：入口来源统计复核，修正实时工具来源识别。
- Phase 6D：落地 `primary_entry_selection_enabled` 预览开关。
- Phase 6E：开启入口选择预览跑 core 长场景，验证行为不漂移。
- Phase 6F：为每个入口增加接管资格诊断。
- Phase 6G：增加 `entry_selection` 接管预检结论。
- Phase 6H：增加 `PrimaryExecutionAdapter` 只读双轨预览。
- Phase 6I：小范围低风险入口实际接管，仅限 `general / rag / local_files`。
- Phase 6J：暂停执行。原本用于评估 `document / data` 受控接管，但当前不再作为进入 Phase 7 的前置条件；`document / data` 继续保持阻断与 legacy fallback。

完成标准：

- `RuntimeControl.diagnostics.execution_entries` 能列出每个执行入口的：
  - `entry_kind`
  - `source`
  - `tool`
  - `worker_route`
  - `agent_id`
  - `strategy`
- `primary_entry_selection_enabled` 默认关闭，开启后只进入 preview，不改变执行行为。
- 每个 entry 都能给出 `eligible_for_primary_entry / eligibility_reason / eligibility_blockers`。
- `entry_selection` 能输出 `disabled / ready / blocked / no_entries`。
- 长场景报告能聚合 `entry_sources / entry_strategy / entry_eligible / entry_blockers / entry_selection`。
- 联网、系统执行和高风险工具必须继续被标为不可接管。
- 默认配置下 `primary_entry_selection_enabled=false` 且 `primary_entry_takeover_enabled=false`。
- Phase 6I 完成后，`general / rag / local_files` 可在双开关开启时进入 `orchestration_primary_entry`；`document / data / web / system_execution` 继续阻断。Phase 7 不以扩大接管范围为前提，而以旧启发式权力审计和 readiness gate 为前提。

### Phase 7：调度中枢主切换

目标：

- 在 Phase 5 和 Phase 6 的诊断、预检、报告都稳定后，再让正式编排中枢成为主调度。
- 启发式逐步降级为 fallback、安全检查、兼容层和异常恢复，而不是继续作为隐藏调度脑。

子阶段拆分：

- Phase 7A：旧启发式权力审计与 Readiness Gate。只做审计、诊断和报告，不删除旧链路，不扩大接管范围。
- Phase 7B：理解层降级为 `IntentFrame` 候选生成。`task_understanding.py` 继续保留规则，但不再拥有最终 route/tool/worker 决策权。
- Phase 7C：编排中枢生成可执行 `ExecutionDirective`。低风险入口可由正式 directive 选择执行对象，但必须继续通过 `RuntimeToolBridge`、search policy、tool contract 和 agent binding。
- Phase 7D：旧链路降级为 fallback/debug baseline。只有当 Phase 7A-7C 的 readiness、长场景和回滚验证都稳定后，才允许清理旧的重复调度分支。

完成标准：

- Phase 7A 必须先列出旧启发式仍拥有最终决策权的位置，包括 `QueryPlanner`、`task_understanding`、`RuntimeToolBridge`、`output_classifier`、记忆恢复和上下文绑定。
- Phase 7A 必须输出 `phase7_readiness` 诊断，说明本轮是否满足主切换条件，以及不满足时的 blocker。
- 默认配置必须继续保持 `primary_entry_selection_enabled=false` 且 `primary_entry_takeover_enabled=false`，除非测试环境显式开启。
- 不得在 Phase 7A 删除 `QueryPlanner`、`task_understanding.py`、`output_classifier.py` 或旧执行 fallback。
- 低风险入口可以由 `PrimaryExecutionAdapter` 生成或选择执行对象，并与 legacy 结果双轨对照。
- `understanding/task_understanding.py` 的规则从“最终决策”退到 `IntentFrame` 候选生成。
- `output_classifier.py` 从“理解答案”降级为输出边界、fallback 检查和协议清洗。
- 编排系统前端能显示编排计划、validator decision、runtime control、executor trace 和最终执行差异。
- 长场景测试、冒烟测试、稳定门禁均能解释主调度路径与 fallback 原因。

## 十、验证矩阵

| 场景 | 期望 |
| --- | --- |
| 用户问知识库问题，RAG 开启 | 编排计划选择 RAG skill / search_knowledge |
| 用户问知识库问题，RAG 关闭 | 编排计划不得调用 search_knowledge，应说明当前未开启 |
| 用户问本地文件 | 编排计划选择本地文件 skill / search_files 或 read_file |
| 用户问最新信息，联网关闭 | 编排计划不得调用 web_search，应提示权限限制 |
| 用户问 PDF 页码 | 编排计划选择文档智能体 / pdf_analysis |
| 用户问表格统计 | 编排计划选择结构化数据智能体 / structured_data_analysis |
| 用户要求执行命令 | validator 识别高风险，需要确认或拒绝 |
| 子 agent 停用 | 编排计划可提出委派，但 validator 阻断 |
| tool 不在 skill allowed_tools | validator 阻断并给出原因 |
| 缺少 active_pdf | validator 要求澄清或提供文件 |

## 十一、风险与回滚

### 风险

- 编排候选可能引用不存在的 tool、agent、skill 或状态句柄。
- 模型可能绕过权限，直接要求工具执行。
- 旧启发式和新编排中枢在过渡期可能冲突。
- Prompt 太长，能力 manifest 可能挤占上下文。
- 前端编辑 skill 绑定后，注册表刷新不及时。
- 记忆恢复可能把旧会话状态误当作当前轮目标。
- 子 agent / worker 的执行结果可能越权写入主线程状态。

### 控制

- 所有编排候选输出必须过 schema 校验。
- 所有 tool 调用必须过 PlanValidator。
- 第一阶段只做契约，不改主调度路径。
- 第二阶段先 `plan_only`，再 `primary` allowlist，最后扩大 `primary` 覆盖范围。
- 保留 runtime config：`orchestration_mode = legacy | plan_only | primary`。
- `primary` 必须同时受 allowlist、search_policy、tool contract 和 agent binding 限制。

### 回滚

- `legacy`：完全使用旧链路。
- `plan_only`：新编排中枢只产出 plan 事件，不执行。
- `primary`：正式编排中枢主路径，但可通过 allowlist 限定低风险范围。

任何阶段出现长场景测试大面积退化，可立即切回 `legacy` 或 `plan_only`。

## 十二、文件级执行清单

### 新增

- `backend/capabilities/models.py`
- `backend/capabilities/manifest.py`
- `backend/capabilities/validation.py`
- `backend/capabilities/search_policy.py`
- `backend/orchestration/directives.py`（如现有 `models.py` 继续膨胀再拆出）
- `backend/orchestration/validation.py`

### 修改

- `backend/skill_system/contracts.py`
- `backend/skill_system/registry.py`
- `backend/tools/contracts.py`
- `backend/tools/definitions.py`
- `backend/tools/runtime.py`
- `backend/agents/a2a_cards.py`
- `backend/api/operations.py`
- `backend/query/models.py`
- `backend/query/prompt_builder.py`
- `backend/query/runtime.py`
- `backend/query/runtime_tools.py`
- `backend/query/planner.py`
- `backend/understanding/task_understanding.py`
- `backend/orchestration/models.py`
- `backend/orchestration/adapters.py`
- `backend/orchestration/runtime_adapter.py`
- `backend/orchestration/diff.py`
- `frontend/src/components/workspace/views/OperationsView.tsx`
- `frontend/src/components/workspace/views/EvidenceView.tsx`
- `frontend/src/components/layout/RightRail.tsx`
- `frontend/src/components/workspace/WorkspacePanel.tsx`
- `frontend/src/lib/store/types.ts`
- `frontend/src/components/chat/ChatInput.tsx` 或当前实际输入框组件
- `frontend/src/lib/api.ts`

### 测试

- `backend/tests/operation_system_api_regression.py`
- `backend/tests/skill_contract_regression.py`
- 新增 `backend/tests/capability_manifest_regression.py`
- 新增 `backend/tests/search_policy_regression.py`
- 新增或扩展 `backend/tests/orchestration/test_orchestration_directive.py`

## 十三、当前推进建议

截至 2026-04-27，Phase 1 到 Phase 4 已经完成基础闭环，Phase 5 已完成 primary 接管加固与报告闭环，Phase 6 已推进到 6I：入口计划、资格诊断、接管预检、只读双轨预览和小范围低风险实际接管都已可观测。后续不要再把“调度中枢主切换”放在 Phase 5；主切换已经后移为 Phase 7，必须等 Phase 6 的低风险入口实际接管稳定后再做。

下一步执行顺序：

1. 不执行 Phase 6J；`document / data` 暂不纳入实际接管。
2. 进入 Phase 7A：旧启发式权力审计与 Readiness Gate，只做准备和可观测，不做主切换。
3. Phase 7A 开始前必须保留 `primary_entry_takeover_enabled=false` 作为默认值。
4. 冒烟、稳定门禁、长场景报告必须继续显示 `primary_takeover`、fallback、mismatch 和新增 `phase7_readiness`。
5. 只有 Phase 7A 明确列出 blocker 并验证 readiness 稳定后，才进入 Phase 7B/7C 的实际主切换推进。

当前进展：

- 后端正式编排契约骨架已落地到 `backend/orchestration/models.py` 与 `backend/orchestration/adapters.py`。
- `orchestration_plan` 现在会携带 `intent_frame / memory_policy / context_policy / resource_policy / execution_directives / answer_policy / validation`。
- `plan_only` 不改变运行行为；`primary` 如果遇到 blocked validation，会 fail-closed 回 legacy。
- Phase 3B 已把正式编排契约接入编排系统前端，“行为判读”可以直接阅读本轮目标、记忆策略、上下文策略、资源权限、执行指令和校验结果。
- Phase 4A 已定义低风险 `primary` allowlist：仅 `rag / local_files / document / data / general` 可进入 primary 控制范围；`web` 与系统执行工具会自动 fallback legacy。
- Phase 4B 已把 primary fallback 原因做成前端中文可读：validation blocked、allowlist blocked、execution mismatch 都会在 RuntimeControl 卡片里解释。
- Phase 5 前置评估已完成：低风险 primary 接管稳定，少量联网 fallback 属于 allowlist 预期阻断；长期记忆召回失败暂时从编排主线剥离。
- Phase 5A 已加固 primary 接管条件：正式契约缺 `intent_frame / memory_policy / context_policy / resource_policy / execution_directives / answer_policy / validation / executions` 等核心字段时，必须回退旧链路，并在前端显示“正式编排契约不完整”。
- Phase 5B 已增加 directive 与 legacy execution 的字段级一致性校验：`route / execution_kind / tool / worker_route / skill` 任一非空冲突都会回退旧链路，并在诊断里列出具体 mismatch。
- Phase 5C 已把 RuntimeControl mismatch 接入编排系统前端：`contract_blockers / allowlist_blockers / execution_mismatches` 都能在正式编排契约卡片里直接阅读。
- Phase 5D 已把 RuntimeControl 诊断接入长场景报告：`run_result.json` 会聚合 `runtime_control_source_counts / runtime_control_warning_counts / runtime_control_fallback_turns`，`report.md` 会新增 `Runtime Control` 区块，并区分预期 allowlist fallback 与需要修复的字段/契约 fallback。
- Phase 5E 已复核长场景 core：`total=3 passed=3 failed=0`；`研究问答到文档跟读` 和 `工作偏好写入与跨会话回忆` 均无 runtime fallback，`运营数据与实时信息切换` 只有 2 个预期联网 allowlist fallback。
- Phase 6A 已把低风险执行入口选择做成 `RuntimeControl.diagnostics.execution_entries`：当前策略为 `reuse_legacy_execution`，先可观测化入口计划，不创建新执行对象。
- Phase 6B 已将入口计划写入长场景报告聚合：报告会展示 `runtime_entry_kind_counts` 与 `runtime_entry_source_counts`。
- Phase 6C 已复核长场景 core：`total=3 passed=3 failed=0`；入口统计稳定，实时专用工具 `get_weather / get_gold_price` 已正确归入 `web`，运营场景的 2 个 fallback 可解释为预期联网阻断。
- Phase 6D 已落地 `primary_entry_selection_enabled` runtime 开关：默认关闭，开启后仅把 RuntimeControl entry strategy 标为 `primary_entry_selection_preview`，不改变执行路径。
- Phase 6E 已在测试环境开启 `primary_entry_selection_enabled` 跑 core 长场景：`total=3 passed=3 failed=0`，报告中所有 entry strategy 均切为 `primary_entry_selection_preview`，行为未漂移。
- Phase 6F 已新增 `execution_entry` 低风险接管资格诊断：每个入口都会标记 `eligible_for_primary_entry / eligibility_reason / eligibility_blockers`，长场景报告新增 `entry_eligible / entry_blockers`；core 长场景 `total=3 passed=3 failed=0`，联网入口继续被标为不可接管。
- Phase 6G 已新增入口接管预检结论 `entry_selection`：默认关闭时为 `disabled`；开启 `primary_entry_selection_enabled` 后，低风险入口显示 `ready`，联网入口显示 `blocked`；两次 core 长场景均为 `total=3 passed=3 failed=0`。
- Phase 6H 已新增 `PrimaryExecutionAdapter` 只读预览：`RuntimeControl.diagnostics.primary_execution_preview` 会输出 `disabled / ready / blocked / mismatch`，长场景报告新增 `primary_preview / primary_preview_mismatches`；默认与开启预览两次 core 长场景均为 `total=3 passed=3 failed=0`。
- Phase 6I 已新增 `primary_entry_takeover_enabled` 小范围实际接管开关：仅 `general / rag / local_files` 且 `primary_execution_preview.ready` 时会进入 `orchestration_primary_entry`；默认与开启接管两次 core 长场景均为 `total=3 passed=3 failed=0`。
- 下一步不再推进 Phase 6J，直接进入 Phase 7A 前置准备。Phase 7A 只做旧启发式权力审计、readiness 诊断和报告闭环；必须继续受 validation、allowlist、field mismatch、entry eligibility、entry selection、primary preview、primary takeover 和一键回退保护。
- Phase 7A 已开始落地 `phase7_readiness` 诊断：默认状态为 `disabled`，低风险 takeover ready 路径可显示 `ready`，`document / data / web / system_execution` 继续显示 blocker；长场景报告和编排系统前端均已接入该诊断。
- Phase 7A core 长场景观察已完成：`total=3 passed=3 failed=0`；默认配置下 readiness 全部为 `disabled`，运营场景明确暴露 `data / document / web` blocker，说明下一步应先设计 Phase 7B 的理解层降级细则，而不是扩大 takeover。
- Phase 7B 已完成理解层候选化第一步：`task-understanding` 在编排计划中标为 `candidate`，`diagnostics.intent_candidates / intent_authority` 会说明理解层只提交候选、canonical owner 是 `orchestration.intent_frame`、旧 `QueryPlanner` 仍执行；core 长场景 `total=3 passed=3 failed=0`，`phase7_intent candidate_projected` 已进入报告。
- Phase 7C 已完成 `ExecutionDirective` 可执行契约预览：`primary_execution_preview.executable_contract` 会显示 `preview_only / runnable=false / required_gates / execution_specs`；默认 core 长场景 `total=3 passed=3 failed=0`，开启入口选择预览后低风险场景显示 `phase7_execution preview_ready`，运营场景的 web 入口继续 blocked。
- Phase 7D 已完成旧链路降级清单与删除门禁：`phase7_readiness.legacy_decommission` 会显示 protected modules、blockers 和 `delete_allowed=false`；core 长场景 `total=3 passed=3 failed=0`，所有场景均为 `phase7_decommission not_ready`，说明旧链路仍受保护，不允许直接删除。
