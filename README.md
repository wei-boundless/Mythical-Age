# Mythical Age —— 通用 AI Agent 平台

Mythical Age 是我个人学习 AI Agent 架构的**实战编码项目**。通过边写边学（vibe coding）的方式，从零搭建一套完整的 Agent 基础设施——涵盖多 Agent 身份与调度、任务图编排、图运行时引擎、多层记忆治理、结构化提示词体系、能力目录、上下文预算管理、RAG 知识检索、权限控制、运行时监控、证据管理、断线恢复和前端可视化工作台。

这个项目承载了我对 Agent 系统架构的探索与理解：如何设计 Agent 的身份与调度体系、如何构建可恢复的任务图执行引擎、如何用五层记忆架构管理短期到长期的上下文、如何用结构化提示词替代硬编码逻辑……每一个模块都是反复思考、迭代和打磨出来的。

项目名称 "Mythical Age"（洪荒时代）——寓意 Agent 技术仍处在早期混沌探索阶段，充满了可能性和想象力。

## 技术栈

| 层级 | 技术选型 |
|------|----------|
| **后端框架** | FastAPI + Uvicorn（Python 3.11+） |
| **前端框架** | Next.js 14 + React 18 + TypeScript + Tailwind CSS |
| **Agent 图执行** | 自研图运行时引擎（GraphSystem） |
| **RAG 检索** | LlamaIndex + BM25 混合检索 |
| **文档解析** | Docling + pdfplumber + RapidOCR |
| **协议标准** | MCP（Model Context Protocol）+ A2A（Agent-to-Agent） |
| **权限控制** | 自研 OperationGate RBAC/ABAC |
| **数据库** | SQLAlchemy + SQLite（可替换） |
| **桌面端** | Electron |
| **编辑器** | Monaco Editor（内嵌代码编辑） |
| **可视化** | @xyflow/react（任务图可视化）+ dagre |
| **分词** | tiktoken + jieba |
| **可观测性** | LangSmith Tracing |

## 固定服务节点

| 服务 | 地址 |
|------|------|
| 前端 Next.js | `http://127.0.0.1:3000` |
| 后端 FastAPI | `http://127.0.0.1:8003` |
| 前端 API Base | `http://127.0.0.1:8003/api` |

---

## 核心模块及功能

### 1. Agent 系统（`backend/agent_system/`）

Agent 系统是整个平台的"演员管理体系"，负责定义、注册、装配和供给 Agent。

**核心能力：**
- **Agent 身份与描述**（`identity.py`、`models/agent_models.py`）：定义 Agent 的唯一标识、别名、生命周期记录。
- **Model Profile**（`models/model_profile_models.py`）：描述 Agent 的模型偏好（提供商、模型名、参数），支持按需解析和 Provider 目录。
- **运行时 Profile**（`profiles/runtime_profile_models.py`、`profiles/runtime_profile_registry.py`）：描述 Agent 的模型偏好、记忆作用域、输出边界、Prompt 结构等运行时契约。
- **Body Profile**（`profiles/body_models.py`、`profiles/body_registry.py`）：将 Agent 解耦为"身体"——即模型、记忆、输出等可替换组件。
- **Agent 组与注册**（`groups/`、`registry/`）：按域或任务类型组织 Agent，支持 Worker Agent 蓝图和工厂模式按需创建。
- **A2A 协议**（`a2a/`）：支持 Agent 间互操作（Agent-to-Agent SDK）。
- **运行时装配**（`assembly/runtime_spec_models.py`）：将 Profile 与 Task 绑定，生成可执行的 `AgentRuntimeSpec`。

### 2. 任务系统（`backend/task_system/`）

任务系统是平台的核心编排层，负责将用户意图转化为可执行、可追踪、可恢复的结构化任务。

**核心能力：**
- **任务契约**（`contracts/`）：`TaskContract` 定义任务的输入、输出、产物要求、验收规则、失败策略、人审闸门和上下文可见性策略。支持写作类契约家族（`writing_contract_families.py`）和意图匹配契约（`match_contracts.py`）。
- **任务图**（`graphs/`）：用 `TaskGraphDefinition` 描述节点（`TaskGraphNodeDefinition`）和有向边（`TaskGraphEdgeDefinition`），支持语义关系预设（`semantic_relations.py`）、可组合图视图（`composable_graph_models.py`）和标准视图（`task_graph_standard_models.py`）。
- **拆分与合并**（`planning/`）：`StaticSplitPlan` 将大任务拆为子任务，`BatchMergePolicy` 控制合并策略，支持批量生命周期管理。
- **Task Flow**（`registry/flow_models.py`、`flow_registry.py`）：将 Agent 与任务绑定，定义通信协议、执行策略和记忆请求 Profile。
- **Workflow**（`registry/workflow_models.py`、`registry/workflow_registry.py`）：管理预定义的工作流模板。
- **编译器与装配**（`compiler/`、`assembly/`）：将声明式任务定义编译为可执行指令。
- **编辑器与写作图**（`editor/`、`writing_graphs/`）：面向写作场景的专用任务图编辑支持。
- **存储**（`storage/`、`repositories/`）：任务实例的持久化与仓储模式。
- **运行时语义**（`runtime_semantics/`）：定义任务在运行时的语义约束。

### 3. 图运行时系统（`backend/graph_system/`）

图运行时系统是平台最核心的执行引擎，支撑所有 Agent 的图级运行。

**核心能力：**
- **图循环引擎**（`loop.py`，~190KB）：整个 Agent 图执行的核心循环——从接收输入、构建上下文、调用模型、执行工具、处理观察、到输出反馈的完整 turn 生命周期。
- **上下文物化器**（`context_materializer.py`，~123KB）：将结构化上下文、记忆、文件证据、Prompt 片段物化为模型可接受的输入格式。
- **工作订单执行器**（`work_order_executor.py`，~107KB）：接收图节点工作订单并驱动执行，管理执行槽位。
- **Facade**（`facade.py`）：Graph System 的统一入口，协调所有子组件。
- **状态机**（`state_machine.py`）：`GraphStateMachine` 管理图节点状态转换，提供状态快照。
- **运行器**（`runner.py`）：`GraphRunRunner` 负责图运行的起始、暂停、恢复和终止。
- **调度器视图**（`scheduler_view.py`）：构建图调度的可观测视图。
- **模型覆盖**（`model_overrides.py`）：支持按图/节点覆盖模型参数。
- **Checkpoint 存储**（`checkpoint_store.py`、`langgraph_checkpoint_store.py`）：图的断点持久化，支持 LangGraph 兼容存储。
- **Flow Packet 与边**（`flow_packet.py`、`flow_edges.py`）：定义节点间数据流的数据包结构和边构建。
- **恢复服务**（`resume.py`）：从断点恢复图执行。
- **监督与生命周期**（`supervisor.py`、`background_supervisor.py`、`lifecycle_manager.py`）：图运行状态的监督与生命周期管理。

### 4. 运行时系统（`backend/runtime/`）

Runtime 是 Agent 的实际运行环境，负责模型调用、工具执行、上下文管理和执行记录。

**核心能力：**
- **模型网关**（`model_gateway/`）：`ModelRuntime`（~116KB）封装 LLM 调用，支持流式响应、请求重试、协议清洗。`ModelResponseRuntimeExecutor` 处理模型响应，`LightweightChatModel` 提供轻量聊天模型封装，`ModelResponseProtocol` 定义响应协议。
- **工具运行时**（`tool_runtime/`）：`ToolRuntimeExecutor`（~93KB）执行工具调用，`ToolControlPlane`（~92KB）管理工具控制面，`NativeTools`（~200KB）实现大量本地工具。`ToolResultEnvelope` 包装结果，`ToolRepetitionGuard` 防重复调用，`ToolCallIntent` 描述调用意图。
- **上下文管理**（`context_management/`）：管理 Agent 运行时的上下文装配和生命周期——候选管理、提交记录、管线处理、片段策略、物理上下文计划和 Provider 可见上下文账本（~63KB）。
- **执行记录**（`shared/execution_record.py`）：`ExecutionReceipt` 记录每次执行的回执，支持回放策略（`ReplayPolicy`）和幂等令牌。
- **状态索引**（`memory/state_index.py`）：`RuntimeStateIndex` 维护运行时的键值状态快照。
- **文件变更信号**（`file_change_signals.py`、`file_changes.py`）：追踪沙盒文件变化并通知 Agent。
- **输出流**（`output_stream/`）：SSE 流式输出与缓冲管理。
- **可观测性**（`observability/`）：LangSmith 追踪集成。
- **缓存管理**（`cache_manager.py`）：多级缓存策略。
- **存储策略**（`storage_policy.py`）：管理运行时的文件存储与保留策略。

### 5. 运行时宿主（`backend/harness/`）

Harness 是系统的**运行时支撑框架**，将 Agent、Task、Runtime、Memory 和所有子系统在实际运行中串联起来。它远不止是"接线层"，而是一个完整的运行时宿主。

**核心子模块：**

| 子模块 | 关键文件 | 职责 |
|--------|----------|------|
| `runtime/` | 60+ 文件 | 运行时宿主核心——`SingleAgentHost`（~36KB）管理单 Agent 运行生命周期；`Assembly`（~93KB）运行时装配；`Compiler`（~394KB）上下文编译；工具目录清单（~24KB）、任务契约清单（~43KB）、增量上下文帧（~22KB）、沙箱产物（~8KB）、会话时间线（~43KB）等 |
| `loop/` | 27 个文件 | Turn 执行循环——`SingleAgentTurn`（~458KB）单 Agent turn 完整处理；`TaskExecutor`（~461KB）任务执行器；`TaskLifecycle`（~76KB）任务生命周期管理；`ExecutionKernel`（~33KB）执行内核；`ModelActionProtocol`（~56KB）模型动作协议处理 |
| `entrypoint/` | 5 个文件 | 运行时入口——`RuntimeFacade`（~175KB）运行时门面，统一对外接口；`CurrentWorkBoundary` 当前工作边界 |
| `agent_control/` | 3 个文件 | Agent 控制——`Controller`（~32KB）Agent 运行控制，管理暂停/恢复/停止 |
| `continuation/` | 5 个文件 | 断线后的上下文恢复 |
| `routing/` | 待定 | 路由与分发 |

### 6. 记忆系统（`backend/memory_system/`）

记忆系统采用**五层架构**，从会话级短时记忆到持久化长期记忆逐级递进，并用候选契约确保不会覆盖当前轮次事实。

| 层级 | 核心模块 | 职责 |
|------|----------|------|
| 会话记忆 | `conversation_memory.py` | 从会话提取对话摘要、用户请求、关键决策 |
| 状态记忆 | `state_memory.py` | 保存任务流程的上下文快照（目标、绑定、结果引用） |
| 工作记忆 | `working_memory_service.py` + `working_memory_store.py` | 图节点级工作项，带策略管控的生命周期 |
| 正式记忆 | `formal_memory_service.py` + `formal_memory_store.py` | 已审核/已接受的正式任务记忆，带版本管理 |
| 持久记忆 | `durable.py` | 基于文件的长期笔记，AI 驱动的召回选择器 |

**核心组件：**
- **MemoryFacade**（`facade.py`，~16KB）：系统统一入口，构造并串联所有子组件。
- **MemoryBundleService**（`bundle_service.py`，~23KB）：跨层上下文打包编排，为每次 Agent turn 提供精选记忆上下文。
- **DurableMemoryGovernanceService**（`governance_service.py`，~30KB）：长期记忆治理——命名空间脏标记、笔记 CRUD、合并、回收站、审计日志。
- **MemoryMaintenanceCoordinator**（`maintenance.py`，~85KB）：记忆维护 Agent，在合适时机触发记忆整理、去重和清理。
- **RuntimeContextProvider**（`runtime_context_provider.py`，~33KB）：为 Agent turn 提供运行时记忆上下文。
- **RuntimeSupply**（`runtime_supply.py`，~25KB）：记忆的运行时供给管线。
- **ForegroundContinuityStateStore**（`continuity.py`）：前台状态持久化，支撑暂停后继续。
- **RuntimeFactBridge**（`runtime_fact_bridge.py`）：运行时事实与记忆之间的桥接。

**安全设计：** 所有记忆数据以 `MemoryContextCandidate` 包装，强制校验 authority 字段；候选记忆不能覆盖当前轮次事实；消息去重和内容过滤避免记忆污染。

### 7. 提示词体系（`backend/prompt_library/` + `backend/prompt_composition/` + `backend/prompting/`）

提示词体系将 Prompt 从代码中分离为可管理、可迁移的结构化资产，分为三个协作层：

**Prompt Library（`prompt_library/`）——提示词存储层：**
- **Agent Prompts**（`agent_prompts.py`）：按角色和职责组织的 Agent 级提示词。
- **System Prompts**（`system_prompts.py`）：系统级的框架提示词。
- **Environment & Lifecycle Prompts**（`environment_lifecycle_prompts.py`，~46KB）：环境描述、生命周期阶段和状态转换的提示词。
- **Tool Prompts**（`tool_prompts.py`，~20KB）：工具的使用说明和契约。
- **Personality Prompts**（`personality_prompts.py`）：Agent 人格描述。
- **Rules**（`rules.py`，~58KB）：各类规则提示词——编码规则、调试纪律、验证规则等。
- **Worker Prompts**（`worker_prompts.py`，~20KB）：Worker Agent 的提示词模板。
- **Utility Prompts**（`utility_prompts.py`）：功能性 Prompt（MCP、RAG、修复等）。
- **Registry**（`registry.py`）：提示词注册与索引。
- **Assembly**（`assembly.py`，~28KB）：将各层提示词按上下文装配为完整的 Prompt 上下文。
- **Packs**（`packs.py`）：预定义的提示词包。

**Prompt Composition（`prompt_composition/`）——提示词组合层：**
- 管理上下文的组装计划、片段、源绑定、渲染器、运行时槽位。
- 将来自多个源的 Prompt 片段组合为完整的 Provider 载荷。

**Prompting（`prompting/`）——提示词引擎层：**
- Prompt 构建器（`builder.py`）、缓存（`prompt_cache.py`）、策略原型（`strategy_prototypes.py`）、专业 Profile（`professional_profiles.py`）。

### 8. 能力系统（`backend/capability_system/`）

能力系统管理与暴露 Agent 可用的全部操作能力，包括工具、Skills 和 MCP 集成。

**核心能力：**
- **目录投影**（`catalog_projection.py`，~39KB）：将能力目录投影为 Agent 可见的格式，支持按分组、标签过滤。
- **Skill 系统**（`skills/`）：将复杂操作封装为 Skill——一种带触发条件、操作边界和输出协议的能力卡片。
- **MCP 集成**（`mcp/`）：Model Context Protocol 的本地实现，支持工具发现、调用和资源映射。
- **工具系统**（`tools/`）：本地工具的定义、注册和执行。
- **Capabilities**（`capabilities/`）：能力的结构化描述和索引。
- **Unit 投影**（`unit_projection.py`）：能力单元的结构化投影。
- **资源清单**（`resource_inventory.py`）：构建运行时资源视图。
- **权限投影**（`permission_projection.py`）：将权限策略投影到能力边界。
- **验证**（`validation.py`，~12KB）：能力声明的合法性校验。

### 9. 上下文系统（`backend/context_system/`）

上下文系统管理 Prompt 上下文预算、压缩和组装，确保在模型 token 窗口内最大化有效信息密度。

**核心能力：**
- **预算管理**（`budget/`）：按优先级分配 token 预算，控制各部分上下文的大小。
- **上下文压缩**（`compaction/`）：当上下文接近预算上限时，智能压缩历史消息和冗余内容。
- **打包**（`packaging/`）：将结构化上下文组装为模型可接受的格式。
- **策略**（`policy/`）：定义不同场景下的上下文选择策略。
- **投影**（`projection/`）：将内部状态投影为模型可见的上下文片段。
- **当前 Turn**（`current_turn/`）：管理当前 turn 的上下文状态，含 `TurnBinding`。
- **解析器**（`resolution/`）：上下文引用解析。

### 10. 知识系统 / RAG（`backend/knowledge_system/`）

知识系统提供基于检索增强生成（RAG）的知识问答能力。

**核心能力：**
- **文档转换**（`conversion/`）：基于 Docling 的多格式文档解析，支持 PDF、DOCX 等，生成标准化的 Markdown 块。
- **文档摄取**（`ingestion/`）：分块策略（`ChunkPlan`）、清洗管线、索引单元构建。
- **索引检索**（`indexing/`）：LlamaIndex 检索后端 + BM25 关键词检索混合检索。
- **服务**（`services/`）：知识检索服务封装。
- **大模型证据**（`evidence/`）：知识证据的管理。

### 11. 权限系统（`backend/permissions/`）

基于自研 OperationGate 的 RBAC/ABAC 权限控制，管理 Agent 操作的安全边界。

**核心能力：**
- **OperationGate**（`operation_gate.py`，~15KB）：操作审批管线，决定每个操作是否被允许。
- **Operation Packages**（`operation_packages.py`，~10KB）：操作包定义与分组。
- **Operations**（`operations.py`，~29KB）：全量操作定义。
- **Runtime Policy Builder**（`runtime_policy_builder.py`，~22KB）：运行时策略构建，根据当前上下文动态生成策略。
- **Resource Policy**（`resource_policy.py`、`resource_policy_builder.py`）：资源访问策略定义与构建。
- **Decision Pipeline**（`decision_pipeline.py`）：决策管线，串联审批逻辑。
- **Tool Scope**（`tool_scope.py`）：工具范围的权限映射。

### 12. 证据系统（`backend/evidence/`）

证据系统管理 Agent 在执行过程中收集的多模态证据，是 Agent 产物验收和事实核查的基础设施。旧版 README 未提及此模块。

**核心能力：**
- **Agent 证据包**（`agent_evidence_packet.py`，~26KB）：将 Agent 收集的证据打包为结构化数据包。
- **OCR 与 PDF 处理**（`image_ocr_worker.py`、`pdf_worker.py`）：图片文字识别和 PDF 文档解析。
- **结构化数据处理**（`structured_data_worker.py`）：CSV/Excel 等表格数据提取与物化。
- **检索 Worker**（`retrieval_worker.py`）：证据检索服务。
- **编排器**（`orchestrator.py`）：多路证据收集的编排。
- **图/投影/存储**（`graph.py`、`projection.py`、`store.py`）：证据的图结构、投影和持久化。

### 13. 断线恢复系统（`backend/continuation/` + `backend/harness/continuation/`）

断线恢复系统负责在 Agent 运行中断后收集候选上下文、决策恢复策略并恢复执行。旧版 README 未提及此模块。

**核心能力：**
- **Candidate Collector**（`candidate_collector.py`，~20KB）：收集断线时的上下文候选。
- **决策引擎**（`decision.py`）：决定恢复策略（重试、继续、终止）。
- **Profile Registry**（`profile_registry.py`）：恢复 Profile 的注册。
- 与 `harness/continuation/` 协作，提供运行时层面的上下文恢复能力。

### 14. 会话系统（`backend/sessions/`）

管理用户会话的完整生命周期，包括会话创建、恢复、过期和持久化。

- 单文件实现（`__init__.py`，~65KB），完整包含会话模型、存储、序列化、异常处理。

### 15. API 层（`backend/api/`）

FastAPI 驱动的 REST API，覆盖平台全部功能。

| 路由模块 | 功能 |
|----------|------|
| `chat.py`（~138KB） | 核心对话接口，SSE 流式输出 |
| `chat_live.py` | 实时聊天 WebSocket 支持 |
| `sessions.py` | 会话 CRUD 和生命周期管理 |
| `task_system.py`（~91KB） | 任务定义、创建、执行和状态查询 |
| `orchestration.py` | 编排系统的 API 暴露 |
| `orchestration_catalog.py` | 编排能力目录查询 |
| `orchestration_harness.py` | 运行时宿主编排 API |
| `graph_task_instances.py` | 图任务实例管理 |
| `memory.py` | 记忆查询、写入和治理触发 |
| `files.py` / `file_management.py` | 工作区文件操作 |
| `runtime_monitor.py` | 运行时监控数据 |
| `runtime_logs.py` / `runtime_trace.py` | 日志和追踪 |
| `health_system.py` | 健康检查 |
| `tokens.py` | Token 使用统计 |
| `capability_system.py` | 能力目录 API |
| `code_environment.py` | 代码环境管理 |
| `vscode.py` | VSCode 连接集成 |
| `workbench.py` | 工作台数据 |
| `project_workspaces.py` | 项目工作区管理 |
| `mcp_system.py` | MCP 系统接口 |
| `config_api.py` | 系统配置 |
| `image_assets.py` | 图片资产管理 |
| `chat_attachments.py` | 聊天附件处理 |
| `file_changes.py` | 文件变更通知 |
| `deps.py` | API 依赖注入 |

### 16. 前端工作台（`frontend/`）

基于 Next.js 14 和 React 18 的单页应用，提供 Agent 交互的全功能可视化界面。

**核心能力：**
- **Agent 对话界面**（`components/chat/`）：支持 Markdown 渲染（react-markdown + remark-gfm）、SSE 流式响应、附件上传。
- **任务图可视化**（`components/workspace/`）：基于 @xyflow/react 和 dagre 的任务图渲染与交互编辑。
- **代码编辑器**：集成 Monaco Editor（@monaco-editor/react），支持文件编辑和差异对比。
- **工作台**（`features/`）：按功能分层的卡片式布局，含 Health 和 VSCode Connection 模块。
- **通用 UI 组件库**（`ui/`）：Button、Dialog、Panel、Tabs、StatusBadge、ActionBar、MetricCard 等。
- **页面结构**（`app/`）：Adventure Island、Writing Desk、Writing Project 三个主要页面入口。
- **Electron 桌面端**（`electron/`）：支持独立桌面窗口运行（main.cjs + preload.cjs）。
- **API 代理**（`app/api/`）：前端 Next.js 路由代理到后端。

### 17. 产物系统（`backend/artifact_system/`）

管理 Agent 执行过程中产生的产物（文件、图片、结构化数据等）的存储、治理、命名空间策略和材料化回执。

### 18. 引导与 CLI（`backend/bootstrap/`、`backend/cli/`）

- **Bootstrap**：应用启动时的资源初始化、数据库迁移、注册表预热。
- **Settings**（`settings.py`，~44KB）：全局配置项，支持环境变量和配置文件。

### 19. 其他模块

| 模块 | 路径 | 职责 |
|------|------|------|
| **产物系统** | `backend/artifact_system/` | Agent 产物的管理、存储、治理、命名空间策略 |
| **文件管理** | `backend/file_management/` | 工作区文件访问控制、网关、解析器、默认 Profile |
| **代码环境** | `backend/code_environment/` | 代码执行沙箱（PiSystem 环境）|
| **项目工作区** | `backend/project_workspaces/` | 项目工作区管理 |
| **请求意图** | `backend/request_intent/` | 用户请求意图识别 |
| **模态索引** | `backend/modality_index/` | 模态信息索引 |
| **健康检查** | `backend/health_system/` | 系统健康监控 |
| **可观测性** | `backend/observability/` | LangSmith 追踪集成 |
| **集成** | `backend/integrations/` | 外部服务连接器（VSCode） |

---

## 项目特色

1. **从零搭建 Agent 架构**：整个项目不是基于现成框架的封装，而是从 Agent 身份定义、任务契约、图执行引擎到运行时宿主，一步步构建出来的完整体系。
2. **自研图执行引擎**：自己实现的图运行时引擎（`graph_system/`），包含状态机、调度器、上下文物化器和工作流恢复能力，而不是简单的 LangGraph 封装调用。
3. **五层记忆体系**：从会话级短时记忆到持久化长期记忆的完整架构——这是学习过程中最启发思考的部分之一。
4. **结构化提示词管理**：将 Prompt 从代码中抽离为可管理、可迁移的结构化资产（Library + Composition + Engine 三层）。
5. **完整的运行时宿主**：`harness/` 不止是接线层，而是拥有编译器、turn 循环、任务执行器、会话生命周期的完整运行时基础设施。
6. **操作审批管线**：每次工具调用和模型响应都经过权限审批——学到了如何给 Agent 自主权设置边界。
7. **多模态证据管理**：内置 OCR、PDF 解析、结构化数据采集——Agent 产物的可追溯性设计。
8. **协议对齐**：内嵌 MCP（模型上下文协议）和 A2A（Agent-to-Agent）支持，了解 Agent 互联的标准做法。
9. **前端可视化**：任务图可视化、Monaco 代码编辑、SSE 流式对话、Electron 桌面端——前端与 Agent 后端的完整交互闭环。
10. **断线恢复**：两级恢复机制，确保 Agent 任务在网络波动时不丢失——这是生产环境必须处理但容易被忽略的能力。

> 这个项目还会继续演进。如果你在阅读中发现问题或有改进想法，欢迎交流 🚀

## 快速开始

```bash
# 1. 安装 Python 依赖
pip install -r requirements.txt

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 API Key 等配置

# 3. 安装前端依赖
cd frontend
npm install

# 4. 启动后端（端口 8003）
cd backend
python run_uvicorn.py

# 5. 启动前端（端口 3000）
cd frontend
npm run dev
```

访问 `http://127.0.0.1:3000` 即可进入前端工作台。

## 目录结构

```
langchain-agent/
├── backend/                    # 后端 Python 包
│   ├── agent_system/           # Agent 身份、Profile、组、注册、A2A
│   ├── api/                    # FastAPI 路由（25+ 路由模块）
│   ├── artifact_system/        # 产物管理与治理
│   ├── bootstrap/              # 启动引导、配置、生命周期
│   ├── capability_system/      # 能力目录、MCP、Skills、工具注册
│   ├── cli/                    # 命令行工具
│   ├── code_environment/       # 代码执行沙箱环境
│   ├── context_system/         # 上下文预算/压缩/组装/绑定
│   ├── continuation/           # 断线恢复候选收集与决策
│   ├── core/                   # 核心工具函数
│   ├── evidence/               # 多模态证据管理（OCR/PDF/结构化）
│   ├── file_management/        # 文件访问控制与网关
│   ├── graph_system/           # 图运行时引擎（核心执行层）
│   ├── harness/                # 运行时宿主框架
│   │   ├── agent_control/      # Agent 运行控制
│   │   ├── continuation/       # 上下文恢复
│   │   ├── entrypoint/         # 运行时入口与门面
│   │   ├── loop/               # Turn 循环与任务执行
│   │   ├── routing/            # 路由分发
│   │   └── runtime/            # 运行时宿主核心
│   ├── health_system/          # 健康检查
│   ├── integrations/           # 外部集成（VSCode）
│   ├── knowledge_system/       # RAG 知识检索（文档解析/索引/检索）
│   ├── memory_system/          # 五层记忆体系（会话→持久）
│   ├── modality_index/         # 模态信息索引
│   ├── observability/          # LangSmith 追踪与可观测性
│   ├── permissions/            # 操作审批与权限控制
│   ├── project_workspaces/     # 项目工作区管理
│   ├── prompt_composition/     # 提示词组合层
│   ├── prompt_library/         # 结构化提示词存储库
│   ├── prompting/              # 提示词引擎
│   ├── request_intent/         # 请求意图识别
│   ├── runtime/                # 运行时环境
│   │   ├── context_management/ # 上下文生命周期管理
│   │   ├── model_gateway/      # LLM 模型网关
│   │   ├── output_stream/      # SSE 流式输出
│   │   ├── tool_runtime/       # 工具执行运行时
│   │   ├── memory/             # 运行时状态索引
│   │   ├── shared/             # 共享执行记录、事件、动作请求
│   │   └── trace/              # 运行时追踪
│   ├── runtime_objects/        # 运行时对象
│   ├── sessions/               # 会话管理与持久化
│   ├── storage/                # 底层存储
│   ├── task_system/            # 任务编排核心（契约/图/规划/流程）
│   └── tests/                  # 测试
├── frontend/                   # Next.js 前端
│   ├── electron/               # Electron 桌面端
│   ├── src/
│   │   ├── app/                # Next.js App Router
│   │   ├── components/         # 通用组件（chat/workspace/layout）
│   │   ├── features/           # 功能模块
│   │   ├── lib/                # 工具库
│   │   ├── types/              # 类型定义
│   │   ├── ui/                 # UI 组件库
│   │   └── styles/             # 样式文件
│   └── public/                 # 静态资源
├── apps/                       # 应用模板
├── docs/                       # 设计文档（不公开）
├── scripts/                    # 运行和部署脚本
├── extensions/                 # 扩展
├── AGENTS.md                   # 项目协作规则
├── requirements.txt            # Python 依赖
└── README.md                   # 本文件
```

## 开发约定

详见项目根目录的 `AGENTS.md`，主要内容包括：

- **固定本地节点不可随意变更**（前端 `3000`、后端 `8003`）。
- **修改前三读**：读相关代码、读调用链、读测试和约定。
- **跨核心模块前先写计划**：涉及 runtime/workflow/prompt/state/memory/API/数据库/3 个以上核心模块的改动，必须先写计划书。
- **Agent Prompt 准则**：Prompt 必须面向 Agent 编写（角色、职责、边界、输入、输出、裁决标准），不写开发说明。
- **禁止伪造测试结果**：禁止降级断言、mock 核心逻辑、删除失败用例、硬编码输出。
- **真实运行验证**：涉及运行链路、前后端联调、SSE、监控、Electron 的修改，必须用 CLI 真实启动实测，不靠静态检查。
## 前端展示
<img width="1915" height="918" alt="image" src="https://github.com/user-attachments/assets/fd9bc795-bfcb-414e-83b8-a2c4231ecc31" />
<img width="1911" height="870" alt="image" src="https://github.com/user-attachments/assets/c1cf8f87-64a9-46a8-95c2-a1aaf0c98b2a" />
## License

内部项目，暂未开放外部许可。
