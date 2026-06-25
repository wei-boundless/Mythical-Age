
# Mythical Age —— 通用 AI Agent 平台

Mythical Age 是一个面向工程实战的 **通用 AI Agent 开发与运行平台**。它不止是一个聊天前端或 API 封装，而是一套完整的 Agent 基础设施：从多 Agent 身份与调度、任务图编排、多层记忆治理、提示词体系、能力目录、上下文预算管理，到 RAG 知识检索、权限控制、运行时监控和前端可视化工作台，覆盖了生产级 Agent 系统的核心需求。

项目名称 "Mythical Age"（洪荒）寓意 Agent 平台的宏大愿景——构建通用、可演进的 AI Agent 基础设施，而非局限于特定领域的工具封装。

## 技术栈

| 层级 | 技术选型 |
|------|----------|
| **后端框架** | FastAPI + Uvicorn（Python 3.11+） |
| **前端框架** | Next.js 14 + React 18 + TypeScript + Tailwind CSS |
| **Agent 工作流** | LangGraph（图编排与 checkpoint） |
| **RAG 检索** | LlamaIndex + Qdrant + FAISS + BM25 |
| **向量嵌入** | OpenAI Embeddings |
| **文档解析** | Docling + pdfplumber + RapidOCR |
| **协议标准** | MCP（Model Context Protocol）+ A2A SDK（Agent-to-Agent） |
| **权限控制** | Casbin RBAC/ABAC |
| **数据库** | SQLAlchemy + SQLite（可替换） |
| **桌面端** | Electron |
| **编辑器** | Monaco Editor（内嵌代码编辑） |
| **可视化** | @xyflow/react（任务图可视化）+ dagre |
| **分词** | tiktoken + jieba |

## 固定服务节点

| 服务 | 地址 |
|------|------|
| 前端 Next.js | `http://127.0.0.1:3000` |
| 后端 FastAPI | `http://127.0.0.1:8003` |
| 前端 API Base | `http://127.0.0.1:8003/api` |

---

# 核心模块及功能

## 1. Agent 系统（`backend/agent_system/`）

Agent 系统是整个平台的"演员管理体系"，负责定义、注册、装配和供给 Agent。

**核心能力：**
- **Agent 身份与描述**（`identity.py`、`models/agent_models.py`）：定义 Agent 的唯一标识、别名、生命周期记录。
- **运行时 Profile**（`profiles/runtime_profile_models.py`、`profiles/runtime_profile_registry.py`）：描述 Agent 的模型偏好、记忆作用域、输出边界、Prompt 结构等运行时契约。
- **Body Profile**（`profiles/body_models.py`）：将 Agent 解耦为"身体"——即模型、记忆、输出等可替换组件。
- **Agent 组与注册**（`groups/`、`registry/`）：按域或任务类型组织 Agent，支持 Worker Agent 蓝图和工厂模式按需创建。
- **A2A 协议**（`a2a/`）：支持 Agent 间互操作。
- **运行时装配**（`assembly/runtime_spec_models.py`）：将 Profile 与 Task 绑定，生成可执行的 `AgentRuntimeSpec`。

## 2. 任务系统（`backend/task_system/`）

任务系统是平台的核心编排层，负责将用户意图转化为可执行、可追踪、可恢复的结构化任务。

**核心能力：**
- **任务契约**（`contracts/`）：`TaskContract` 定义任务的输入、输出、产物要求、验收规则、失败策略、人审闸门和上下文可见性策略。支持写作类契约家族（`writing_contract_families.py`）。
- **任务图**（`graphs/`）：用 `TaskGraphDefinition` 描述节点（`TaskGraphNodeDefinition`）和有向边（`TaskGraphEdgeDefinition`），支持语义关系预设（`semantic_relations.py`）和可组合图视图（`composable_graph_models.py`）。
- **拆分与合并**（`planning/`）：`StaticSplitPlan` 将大任务拆为子任务，`BatchMergePolicy` 控制合并策略，支持批量生命周期管理。
- **Task Flow**（`registry/flow_models.py`、`flow_registry.py`）：将 Agent 与任务绑定，定义通信协议、执行策略和记忆请求 Profile。
- **Workflow**（`registry/workflow_models.py`、`registry/workflow_registry.py`）：管理预定义的工作流模板。
- **编译器与装配**（`compiler/`、`assembly/`）：将声明式任务定义编译为可执行指令。
- **编辑器与写作图**（`editor/`、`writing_graphs/`）：面向写作场景的专用任务图编辑支持。
- **存储**（`storage/`、`repositories/`）：任务实例的持久化与仓储模式。

## 3. Runtime（`backend/runtime/`）

Runtime 是 Agent 的实际运行环境，负责模型调用、工具执行、状态管理和执行记录。

**核心能力：**
- **模型网关**（`model_gateway/`）：`ModelRuntime` 封装 LLM 调用，`ModelResponseRuntimeExecutor` 处理模型响应，`RuntimeConversationAgent` 管理对话级 Agent 运行。
- **工具运行时**（`tool_runtime/`）：`ToolRuntimeExecutor` 执行工具调用，`ToolCallIntent` 描述调用意图，`ToolResultEnvelope` 包装结果，`ToolRepetitionGuard` 防重复调用。
- **执行记录**（`shared/execution_record.py`）：`ExecutionReceipt` 记录每次执行的回执，`OperationExecutionRecord` 追踪操作执行，支持回放策略（`ReplayPolicy`）和幂等令牌。
- **状态索引**（`memory/state_index.py`）：`RuntimeStateIndex` 维护运行时的键值状态快照。
- **上下文管理**（`context_management/`）：管理 Agent 运行时的上下文装配和生命周期。
- **文件变更信号**（`file_change_signals.py`、`file_changes.py`）：追踪沙盒文件变化并通知 Agent。
- **存储策略**（`storage_policy.py`）：管理运行时的文件存储与保留策略。
- **环境**（`environment/`）：环境描述、解析和边界定义。
- **输出流**（`output_stream/`）：SSE 流式输出与缓冲管理。
- **可观测性**（`observability/`）：运行时事件、日志、追踪。

## 4. 编排系统（`backend/orchestration/`）

编排系统是 Agent 操作的安全网关和调度中枢。每一次工具调用、每一次模型响应写入，都经过编排的审批管线。

**核心能力：**
- **ControlKernel**（`kernel.py`）：控制内核，接收候选操作并决定执行或拒绝，是 Agent 自主权的边界。
- **执行调度器**（`execution_scheduler.py`）：`BackgroundTaskManager` 管理后台任务队列，`resolve_execution_dispatch` 决定操作的分发策略。
- **执行图**（`execution_graph.py`）：`ExecutionGraph` 和 `ExecutionNode` 表示操作间的依赖关系，`CommitCandidate` 表示待提交的候选操作。
- **提交闸门**（`commit_gate.py`）：`RuntimeCommitGateDecision` 决定消息和产物是否可提交到长期存储，区分用户消息、助手消息、任务运行最终提交等场景。
- **资源管理**（`resource_inventory.py`、`resource_runtime_view.py`）：构建资源清单和运行时视图，`ResourcePolicy` 控制资源访问边界。
- **Unit 注册**（`unit_registry.py`）：`UnitCatalog` 管理可编排的能力单元。

## 5. Harness（`backend/harness/`）

Harness 是系统的"接线层"，将 Agent、Task、Runtime 和 Memory 在实际运行中串联起来。

**核心能力：**
- **GraphHarness**（`graph_harness.py`）：任务图的实际执行引擎，负责按图结构调度节点、处理边条件和管理图的运行时状态。
- **SingleAgentRuntimeHost**（`runtime/`）：单 Agent 运行宿主，管理 turn 级生命周期——从接收用户输入、装配上下文、调用模型、执行工具到输出反馈。
- **AgentRuntimeServices**（`runtime/`）：运行时服务的聚合入口，提供 Agent 运行所需的全部基础设施。
- **入口点**（`entrypoint/`）：提供不同的启动和调用路径。
- **CurrentWorkReceipt**（`current_work_receipt.py`）：表示当前活跃工作的回执，支撑暂停/恢复/继续控制。
- **RecoveryReceipt**（`recovery_receipt.py`）：断线恢复的上下文回执。
- **Loop**（`loop/`）：Agent turn 循环的控制逻辑。

## 6. 记忆系统（`backend/memory_system/`）

记忆系统采用**五层架构**，从会话级短时记忆到持久化长期记忆逐级递进，并用候选契约确保不会覆盖当前轮次事实。

| 层级 | 核心模块 | 职责 |
|------|----------|------|
| 会话记忆 | `conversation_memory.py` | 从会话提取对话摘要、用户请求、关键决策 |
| 状态记忆 | `state_memory.py` | 保存任务流程的上下文快照（目标、绑定、结果引用） |
| 工作记忆 | `working_memory_service.py` | 图节点级工作项，带策略管控的生命周期 |
| 正式记忆 | `formal_memory_service.py` | 已审核/已接受的正式任务记忆，带版本管理 |
| 持久记忆 | `durable.py` | 基于文件的长期笔记，AI 驱动的召回选择器 |

**核心组件：**
- **MemoryFacade**（`facade.py`）：系统统一入口，构造并串联所有子组件。
- **MemoryBundleService**（`bundle_service.py`）：跨层上下文打包编排，为每次 Agent turn 提供精选记忆上下文。
- **DurableMemoryGovernanceService**（`governance_service.py`）：长期记忆治理——命名空间脏标记、笔记 CRUD、合并、回收站、审计日志。
- **MemoryMaintenanceCoordinator**（`maintenance.py`）：记忆维护 Agent，在合适时机触发记忆整理、去重和清理。
- **ForegroundContinuityStateStore**（`continuity.py`）：前台状态持久化，支撑暂停后继续。
- **SessionEmphasisStore**（`session_emphasis.py`）：用户强调偏好管理。
- **RuntimeContextProvider**（`runtime_context_provider.py`）：为 Agent turn 提供运行时记忆上下文。

**安全设计：** 所有记忆数据以 `MemoryContextCandidate` 包装，强制校验 authority 字段；候选记忆不能覆盖当前轮次事实；消息去重和内容过滤避免记忆污染。

## 7. 提示词体系（`backend/prompt_library/`）

提示词体系将 Prompt 从代码中分离为可管理、可迁移的结构化资产。

**核心能力：**
- **Agent Prompts**（`agent_prompts.py`）：按角色和职责组织的 Agent 级提示词。
- **System Prompts**（`system_prompts.py`）：系统级的框架提示词。
- **Environment & Lifecycle Prompts**（`environment_lifecycle_prompts.py`）：环境描述、生命周期阶段和状态转换的提示词。
- **Tool Prompts**（`tool_prompts.py`）：工具的使用说明和契约。
- **Personality Prompts**（`personality_prompts.py`）：Agent 人格描述。
- **Rules**（`rules.py`）：各类规则提示词——编码规则、调试纪律、验证规则等。
- **Worker Prompts**（`worker_prompts.py`）：Worker Agent 的提示词模板。
- **Assembly**（`assembly.py`）：将各层提示词按上下文装配为完整的 Prompt 上下文。
- **Packs**（`packs.py`）：预定义的提示词包。
- **Registry**（`registry.py`）：提示词注册与索引。
- **Migrations**（`migrations.py`）：提示词的版本迁移。

## 8. 能力系统（`backend/capability_system/`）

能力系统管理与暴露 Agent 可用的全部操作能力，包括工具、Skills 和 MCP 集成。

**核心能力：**
- **目录投影**（`catalog_projection.py`）：将能力目录投影为 Agent 可见的格式，支持按分组、标签过滤。
- **Skill 系统**（`skills/`）：将复杂操作封装为 Skill——一种带触发条件、操作边界和输出协议的能力卡片。
- **MCP 集成**（`mcp/`）：Model Context Protocol 的本地实现，支持工具发现、调用和资源映射。
- **工具系统**（`tools/`）：本地工具的定义、注册和执行。
- **Capabilities**（`capabilities/`）：能力的结构化描述和索引。
- **验证**（`validation.py`）：能力声明的合法性校验。

## 9. 上下文系统（`backend/context_system/`）

上下文系统管理 Prompt 上下文预算、压缩和组装，确保在模型 token 窗口内最大化有效信息密度。

**核心能力：**
- **预算管理**（`budget/`）：按优先级分配 token 预算，控制各部分上下文的大小。
- **上下文压缩**（`compaction/`）：当上下文接近预算上限时，智能压缩历史消息和冗余内容。
- **打包**（`packaging/`）：将结构化上下文组装为模型可接受的格式。
- **策略**（`policy/`）：定义不同场景下的上下文选择策略。
- **投影**（`projection/`）：将内部状态投影为模型可见的上下文片段。
- **当前 Turn**（`current_turn/`）：管理当前 turn 的上下文状态。

## 10. 知识系统 / RAG（`backend/knowledge_system/`）

知识系统提供基于检索增强生成（RAG）的知识问答能力。

**核心能力：**
- 基于 LlamaIndex 的文档索引和检索管线。
- Qdrant 向量数据库 + FAISS 内存索引，支持语义检索。
- BM25 关键词检索作为混合检索的补充。
- Docling 多格式文档解析（PDF、DOCX 等）。
- 支持 jieba 中文分词和自定义 embedding。

## 11. API 层（`backend/api/`）

FastAPI 驱动的 REST API，覆盖平台全部功能。

| 路由模块 | 功能 |
|----------|------|
| `chat.py`（138KB） | 核心对话接口，SSE 流式输出 |
| `chat_live.py` | 实时聊天 WebSocket 支持 |
| `sessions.py` | 会话 CRUD 和生命周期管理 |
| `task_system.py`（91KB） | 任务定义、创建、执行和状态查询 |
| `orchestration.py` | 编排系统的 API 暴露 |
| `orchestration_catalog.py` | 编排能力目录查询 |
| `memory.py` | 记忆查询、写入和治理触发 |
| `files.py` / `file_management.py` | 工作区文件操作 |
| `runtime_monitor.py` | 运行时监控数据 |
| `runtime_logs.py` / `runtime_trace.py` | 日志和追踪 |
| `health_system.py` | 健康检查 |
| `graph_task_instances.py` | 图任务实例管理 |
| `tokens.py` | Token 使用统计 |
| `capability_system.py` | 能力目录 API |
| `code_environment.py` | 代码环境管理 |
| `vscode.py` | VSCode 连接集成 |
| `workbench.py` | 工作台数据 |
| `project_workspaces.py` | 项目工作区管理 |
| `mcp_system.py` | MCP 系统接口 |
| `config_api.py` | 系统配置 |

## 12. 前端工作台（`frontend/`）

基于 Next.js 14 和 React 18 的单页应用，提供 Agent 交互的全功能可视化界面。

**核心能力：**
- **Agent 对话界面**：支持 Markdown 渲染（react-markdown + remark-gfm）、SSE 流式响应、附件上传。
- **任务图可视化**：基于 @xyflow/react 和 dagre 的任务图渲染与交互编辑。
- **代码编辑器**：集成 Monaco Editor，支持文件编辑和差异对比。
- **工作台**（`features/`）：按功能分层的卡片式布局，不同层级独立页面，清爽不混杂。
- **Electron 桌面端**（`electron/`）：支持独立桌面窗口运行。
- **API 代理**（`app/api/`）：前端 Next.js 路由代理到后端。

## 13. 权限系统（`backend/permissions/`）

基于 Casbin 的 RBAC/ABAC 权限控制，管理 Agent 操作的安全边界。

**核心能力：**
- `OperationGate`：操作审批管线，决定每个操作是否被允许。
- `ResourcePolicy`：定义不同资源的访问策略。
- `RuntimeApprovalContext`：运行时的审批上下文。
- `ApprovalToken`：审批令牌机制。
- `DenialTrackingState`：拒绝追踪和冷却。

## 14. 会话系统（`backend/sessions/`）

管理用户会话的完整生命周期，包括会话创建、恢复、过期和持久化。

## 15. 引导与 CLI（`backend/bootstrap/`、`backend/cli/`）

- **Bootstrap**：应用启动时的资源初始化、数据库迁移、注册表预热。
- **CLI**：命令行工具入口。

## 16. 集成与可观测性（`backend/integrations/`、`backend/observability/`）

- **集成**：外部服务连接器。
- **可观测性**：事件追踪、日志聚合、性能监控。

---

# 项目特色

1. **Agent 优先架构**：所有设计围绕"Agent 应该如何被描述、调度、约束和观察"展开，而非将 Agent 视为一个简单的 API 调用者。
2. **多层记忆治理**：从会话到持久记忆的五层体系，配合候选契约和 Authority 溯源，确保记忆不会污染当前事实判断。
3. **任务图编排**：用图结构表达复杂任务流，支持可组合图、语义关系、拆分合并和批量生命周期。
4. **结构化 Prompt 管理**：将提示词从代码中抽离为版本化、可迁移的结构化资产，支持分层装配。
5. **操作审批管线**：每次工具调用和模型响应写入都经过编排系统的审批闸门，确保 Agent 自主权有清晰边界。
6. **协议标准对齐**：内置 MCP（工具发现与调用）和 A2A（Agent 间互操作）支持。
7. **前端可视化工作台**：任务图可视化编辑、Monaco 代码编辑、SSE 流式对话，提供完整的工程化交互体验。

# 快速开始

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

# 目录结构

```
langchain-agent/
├── backend/                  # 后端 Python 包
│   ├── agent_system/         # Agent 身份、Profile、组、注册
│   ├── api/                  # FastAPI 路由（30+ 模块）
│   ├── artifact_system/      # 产物管理
│   ├── bootstrap/            # 启动引导
│   ├── capability_system/    # 能力目录、MCP、Skills
│   ├── cli/                  # 命令行工具
│   ├── code_environment/     # 代码执行环境
│   ├── context_system/       # 上下文预算/压缩/组装
│   ├── continuation/         # 断线恢复
│   ├── core/                 # 核心工具
│   ├── evidence/             # 证据管理
│   ├── file_management/      # 文件管理
│   ├── harness/              # 运行时接线层
│   ├── health_system/        # 健康检查
│   ├── integrations/         # 外部集成
│   ├── knowledge_system/     # RAG 知识检索
│   ├── memory_system/        # 五层记忆体系
│   ├── modality_index/       # 模态索引
│   ├── observability/        # 可观测性
│   ├── orchestration/        # 编排调度
│   ├── permissions/          # 权限控制
│   ├── project_workspaces/   # 项目工作区
│   ├── prompt_composition/   # Prompt 组合
│   ├── prompt_library/       # 结构化提示词库
│   ├── prompting/            # 提示词引擎
│   ├── request_intent/       # 请求意图识别
│   ├── runtime/              # 运行时环境
│   ├── runtime_objects/      # 运行时对象
│   ├── sessions/             # 会话管理
│   ├── task_system/          # 任务编排核心
│   └── tests/                # 测试
├── frontend/                 # Next.js 前端
│   ├── electron/             # Electron 桌面端
│   ├── src/
│   │   ├── app/              # Next.js App Router
│   │   ├── components/       # 通用组件
│   │   ├── features/         # 功能模块
│   │   ├── framework/        # 框架层
│   │   ├── lib/              # 工具库
│   │   ├── types/            # 类型定义
│   │   └── ui/               # UI 组件
│   └── public/               # 静态资源
├── docs/                     # 设计文档与架构记录
│   ├── 系统架构/              # 70+ 篇计划书与审查记录
│   ├── 设计原则/
│   ├── 系统规划/
│   ├── 接口文档/
│   ├── maintenance/
│   └── reviews/
├── scripts/                  # 运行和部署脚本
├── extensions/               # 扩展
├── apps/                     # 应用模板
├── AGENTS.md                 # 项目协作规则
├── requirements.txt          # Python 依赖
└── README.md                 # 本文件
```

# 开发约定

详见项目根目录的 `AGENTS.md`，主要内容包括：

- 固定本地节点不可随意变更（3000/8003）。
- 修改前三读：读相关代码、读调用链、读测试和约定。
- 跨核心模块、runtime/workflow/prompt/state/memory/API 改动前先写计划书。
- Agent 的 Prompt 必须面向 Agent 编写，不要写开发说明。
- 禁止降级断言、mock 核心逻辑、跳过测试。
- 用真实 CLI 启动做实测验，不靠静态检查猜测。

# License

内部项目，暂未开放外部许可。
