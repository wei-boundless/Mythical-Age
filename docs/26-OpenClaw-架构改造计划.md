# OpenClaw 架构改造计划

> 目标：基于 `docs/` 中总结的 Claude Code 设计思想，逐步把当前项目从“能力已具备但运行时耦合偏高”的状态，演进为“分层清晰、可扩展、可审计、可并发”的 Agent 应用框架。

## 1. 现状判断

当前项目已经具备比较强的 Agent 产品雏形：

- 后端已有聊天主链路、RAG、技能、工具、结构化记忆、上下文压缩、多模态文件处理。
- 前端已有工作台 UI、SSE 流式聊天、会话管理、文件检查器。
- 测试覆盖了 memory、tool registry、RAG、pdf、structured-data 等关键方向。

但从架构层看，当前主要问题不是“缺功能”，而是“核心运行时边界不够清晰”：

1. `backend/graph/agent.py` 承担了过多职责：
   - query understanding
   - skill/tool 路由
   - RAG 检索
   - memory prefetch
   - system prompt 组装
   - LangChain agent 构建
   - SSE 事件翻译
   - compound query 编排

2. 工具系统存在“双注册源”：
   - `backend/tools/__init__.py` 负责实例化
   - `backend/tools/tool_registry.py` 负责元数据注册
   - 两者容易漂移，后续新增工具时维护成本会升高

3. 前端状态管理偏“巨型 Provider”：
   - `frontend/src/lib/store.tsx` 同时承载数据、异步流程、UI 状态、会话切换、副作用
   - 业务逻辑和 React 生命周期耦合较深，后续扩展会越来越难

4. 设置、权限、错误恢复仍偏“局部实现”：
   - `backend/config.py` 以环境变量为主，缺少清晰的多层配置模型
   - 工具安全主要依赖工具自身实现和 `safe_for_auto_route`
   - API 调用与降级、重试、熔断还没有形成统一策略层

5. 运行时缺少明确的“任务层 / 子 Agent 层”：
   - 现在 compound query 仍是串行拆分执行
   - 还没有独立任务抽象、后台任务、子 Agent 上下文隔离

结论：当前项目适合做“运行时架构收敛”，不适合继续在现有中心化主控上叠加更多能力。

---

## 2. 目标架构

建议将项目逐步收敛成下面 6 层：

```text
backend/
  bootstrap/           # 启动、初始化、配置装配
  runtime/             # AppState / QueryRuntime / EventBus / TaskRuntime
  query/               # 单轮对话主循环、消息组装、流式事件
  tools/               # 单一来源工具定义、权限、实例化
  agents/              # 主 Agent / 子 Agent / AgentDefinition / AgentContext
  memory/              # durable/session/relevant/context-compaction
  retrieval/           # RAG router / index / rerank / source adapters
  api/                 # 纯 HTTP / SSE 适配层
```

对应的设计思想来自 `docs` 中几条最重要的原则：

- `03-状态管理.md`：极简 Store，桥接 UI 与非 UI 运行时
- `05-对话循环.md`：把 query loop 作为独立核心
- `06-上下文管理.md`：上下文预算、压缩、恢复要成为显式模块
- `09-工具系统设计.md`：工具需要单一来源注册和安全默认值
- `12-Agent-系统.md`：Agent 定义与 Agent 运行时解耦，支持上下文隔离
- `14-任务系统.md`：任务是并发执行和后台化的基础设施
- `16-权限系统.md`：权限是统一决策管线，不应散落在工具细节里
- `17-Settings-系统.md`：配置需要多层来源和热更新思维
- `20-API调用与错误恢复.md`：错误恢复应成为公共基础设施
- `23-Memory系统.md`：记忆必须分层，而不是一次性拼 prompt

---

## 3. 总体改造原则

1. 先抽运行时边界，再搬业务代码。
2. 先建立单一来源注册表，再做功能扩展。
3. 先保证兼容现有 API 和前端，再逐步替换内部实现。
4. 先把“可观察性”做出来，再做并发和子 Agent。
5. 所有迁移优先保留你现有的“文件优先、可审计、可解释”产品特性。

---

## 4. 分阶段改造路线

## Phase 0：建立基线与护栏

目标：开始重构前，先把关键行为固定住。

### 任务

- 整理当前关键回归测试，分成以下测试包：
  - chat-stream
  - memory-layering
  - tool-routing
  - rag-retrieval
  - skill-loading
  - pdf/structured-data
- 增加一组“黑盒主链路快照测试”：
  - 一条纯聊天
  - 一条工具直达
  - 一条 RAG 问答
  - 一条 session memory 压缩
  - 一条 durable memory 提取
- 为 SSE 事件建立稳定契约文档：
  - `token`
  - `tool_start`
  - `tool_end`
  - `retrieval`
  - `context_management`
  - `memory_context`
  - `done`
  - `error`

### 输出物

- 回归测试矩阵
- SSE 事件契约文档
- 一份当前架构依赖图

### 验收标准

- 关键测试可在重构期间持续复跑
- 前端不因内部重构而改动 API 协议

---

## Phase 1：拆分启动层、设置层、运行时容器

目标：把 `app.py + config.py + agent_manager.initialize()` 这条启动链路拆成清晰层次。

### 当前映射

- 入口：`backend/app.py`
- 配置：`backend/config.py`
- 初始化：`backend/graph/agent.py`

### 改造动作

- 新建 `backend/bootstrap/`：
  - `settings.py`
  - `init_runtime.py`
  - `lifespan.py`
- 把配置拆成三类：
  - static settings：模型、embedding、目录、超时
  - runtime settings：rag mode、feature flags、调试开关
  - policy settings：工具权限、危险能力开关、provider 限制
- 引入统一的 `AppRuntime` 容器，负责持有：
  - session manager
  - tool registry
  - skill registry
  - memory services
  - retrieval services
  - query runtime

### 参考 docs 思路

- `01-项目全景.md`
- `17-Settings-系统.md`

### 目标收益

- 初始化过程不再散落在 `lifespan` 和 `AgentManager`
- 后续子系统可独立测试与替换

---

## Phase 2：把 query loop 从 AgentManager 中抽出来

目标：建立真正的“对话主循环”模块。

### 当前问题

`backend/graph/agent.py` 同时负责：

- 请求前分析
- 路由决策
- prompt 组装
- LangChain agent 调用
- 输出流转译
- compound query 编排

这是后续扩展的最大瓶颈。

### 改造动作

- 新建 `backend/query/`：
  - `query_runtime.py`
  - `query_loop.py`
  - `message_builder.py`
  - `event_stream.py`
  - `route_planner.py`
- 把一轮请求拆成标准阶段：
  1. load session context
  2. understand intent
  3. resolve route
  4. prefetch memory / retrieval
  5. build prompt
  6. run model / run tool
  7. normalize events
  8. persist turn
  9. schedule post-turn tasks
- `api/chat.py` 只做 HTTP/SSE 适配，不再参与业务编排。

### 参考 docs 思路

- `05-对话循环.md`
- `20-API调用与错误恢复.md`

### 目标收益

- query loop 可单测
- 后续接入子 Agent、后台任务、fallback model 更容易
- `api` 层彻底变薄

---

## Phase 3：统一工具系统为单一来源注册表

目标：把工具元数据、权限属性、实例化逻辑统一起来。

### 当前问题

- `backend/tools/__init__.py` 是实例注册表
- `backend/tools/tool_registry.py` 是元数据注册表
- 一旦新增工具，很容易漏改其中一处

### 改造动作

- 每个工具改为“定义 + 工厂”模式，例如：
  - `name`
  - `description`
  - `capability_tags`
  - `supported_modalities`
  - `safe_for_auto_route`
  - `is_read_only`
  - `is_destructive`
  - `is_concurrency_safe`
  - `build(base_dir) -> BaseTool`
- 用 `build_tool_definition()` 风格统一生成工具定义对象。
- `get_all_tools()` 改成从单一注册表派生，而不是手写列表。
- `TOOLS_REGISTRY.json` 改成构建产物，不再作为另一套事实源。
- 为工具增加统一的分类维度：
  - read
  - write
  - network
  - shell
  - compute
  - dangerous

### 参考 docs 思路

- `09-工具系统设计.md`
- `25-架构模式总结.md`

### 目标收益

- 工具注册不会漂移
- 权限系统能直接消费统一元数据
- 自动路由更稳定

---

## Phase 4：正式建立权限管线

目标：从“工具内部自我保护”升级为“统一权限决策”。

### 当前问题

- 现在主要依赖：
  - `safe_for_auto_route`
  - skill 的 `allowed_tools`
  - 工具本身的局部黑名单
- 但缺少统一的 ask / allow / deny 决策层

### 改造动作

- 新建 `backend/permissions/`：
  - `models.py`
  - `policy.py`
  - `matcher.py`
  - `decision_pipeline.py`
- 引入最小可用权限模式：
  - `default`
  - `plan`
  - `accept_edits`
  - `bypass`
- 为工具调用统一走一条决策链：
  1. route eligibility
  2. skill restriction
  3. policy deny/allow
  4. tool local validation
  5. final permission decision
- 首先只拦截高风险工具：
  - `terminal`
  - `python_repl`
  - 未来的写文件工具
  - 外网抓取工具

### 参考 docs 思路

- `16-权限系统.md`

### 目标收益

- 安全边界清晰
- 未来做“自动执行模式”不会失控
- 可以把不同能力开放给不同 Agent / 不同工作模式

---

## Phase 5：把 memory/context 系统收敛成显式分层

目标：你已经有很好的记忆模块，但需要统一成一个明确的 memory architecture。

### 当前优势

- `structured_memory/` 已经很接近成熟设计
- `context_management/` 已经有 budget / compaction / package
- `graph/prompt_builder.py` 也已有 layered context 注入思路

### 当前问题

- memory 相关逻辑分布在：
  - `structured_memory/`
  - `context_management/`
  - `graph/memory_bridge.py`
  - `graph/long_term_context.py`
  - `graph/prompt_builder.py`
- 概念上是完整的，模块边界上仍偏分散

### 改造动作

- 新建 `backend/memory/` 聚合层：
  - `durable/`
  - `session/`
  - `context/`
  - `retrieval/`
  - `bridge.py`
- 明确四层记忆：
  1. constitution/profile
  2. durable memory
  3. session working memory
  4. relevant memory injection
- 把 `ContextPackage` 作为标准中间产物，所有 prompt 组装都围绕它。
- 让“压缩后上下文”成为 query runtime 的标准步骤，而不是 memory bridge 的内部细节。

### 参考 docs 思路

- `06-上下文管理.md`
- `23-Memory系统.md`

### 目标收益

- 记忆架构更容易解释和扩展
- 后续支持 agent scope / team scope / project scope 更自然

---

## Phase 6：前端改成极简 Store + 运行时桥接

目标：避免 `AppProvider` 继续膨胀。

### 当前问题

`frontend/src/lib/store.tsx` 既像 store，又像 controller，又像 side-effect manager。

### 改造动作

- 拆成三层：
  - `store/core.ts`：极简 store，只有 `getState/setState/subscribe`
  - `store/runtime.ts`：会话切换、SSE 消费、文件保存等副作用
  - `store/hooks.ts`：React 订阅桥接
- UI 组件只消费 selector，不直接管理聊天协议。
- 把 SSE 事件处理改成标准 reducer：
  - token append
  - tool start/end
  - retrieval attach
  - done finalize
  - error recover

### 参考 docs 思路

- `03-状态管理.md`

### 目标收益

- 前端状态更稳定
- 更容易做 inspector、trace view、task panel
- 后续如果增加子 Agent 面板，不会继续堆进一个 Provider

---

## Phase 7：引入任务系统与子 Agent 能力

目标：把现在的 compound query 串行执行，升级成显式任务与可并发 Agent。

### 当前问题

- `split_compound_query()` 已存在，但执行仍在单主循环内串行进行
- 没有任务状态模型
- 没有子 Agent 的上下文隔离

### 改造动作

- 新建 `backend/tasks/`：
  - `models.py`
  - `registry.py`
  - `coordinator.py`
  - `output_store.py`
- 先实现两种任务：
  - `local_query_task`
  - `local_tool_task`
- 再实现两种子 Agent：
  - `explorer`
  - `worker`
- 主 Agent 只做编排时，可切换到 coordinator 模式：
  - 负责分解任务
  - 分派子 Agent
  - 汇总结果

### 参考 docs 思路

- `12-Agent-系统.md`
- `13-内置Agent设计模式.md`
- `14-任务系统.md`

### 目标收益

- 复杂任务时上下文不再膨胀
- 能真正支撑“调研-执行-验证”三段式协作
- 为将来的插件 Agent / team agent 打基础

---

## Phase 8：统一错误恢复、降级与观测

目标：把网络失败、模型失败、工具失败统一纳入恢复机制。

### 改造动作

- 新建 `backend/services/model_runtime.py`：
  - provider adapter
  - retry policy
  - fallback model
  - timeout / cancellation
  - structured error mapping
- 为流式调用增加统一错误事件：
  - retrying
  - degraded
  - provider_switched
  - failed
- 增加 query trace：
  - route decision
  - tool resolution
  - retrieval summary
  - memory injection summary
  - token / latency / tool count

### 参考 docs 思路

- `20-API调用与错误恢复.md`

### 目标收益

- 更容易定位线上问题
- 用户能理解“为什么慢 / 为什么降级 / 为什么失败”

---

## 5. 推荐实施顺序

建议按下面顺序推进，不要并行大面积改：

1. Phase 0
2. Phase 1
3. Phase 2
4. Phase 3
5. Phase 5
6. Phase 6
7. Phase 4
8. Phase 8
9. Phase 7

原因：

- `query loop` 和 `tool registry` 是最核心的结构性瓶颈，应优先处理。
- `memory` 已经相对成熟，适合在运行时边界稳定后再收拢。
- `permissions` 应在工具元数据统一后再做，不然会重复返工。
- `tasks/sub-agents` 必须最后做，否则会把当前耦合问题放大。

---

## 6. 建议的目录迁移草案

### 后端

```text
backend/
  api/
  bootstrap/
  runtime/
  query/
  agents/
  tasks/
  tools/
    definitions/
    runtime/
  memory/
    durable/
    session/
    context/
  retrieval/
  permissions/
  providers/
```

### 前端

```text
frontend/src/
  app/
  components/
  lib/
    api/
    store/
    runtime/
    selectors/
```

---

## 7. 每阶段验收指标

### 架构指标

- `AgentManager` 被拆解后，不再承担超过 3 个一级职责
- 工具定义存在单一事实源
- API 层不再包含核心业务决策
- 前端组件不直接持有复杂异步流程

### 产品指标

- 原有三栏工作台交互不倒退
- 现有技能仍可热更新
- memory/RAG/工具链路都能保持可审计
- 新架构下能输出更完整的 trace

### 工程指标

- 回归测试稳定通过
- 每次重构以小 PR 方式推进
- 迁移期间不破坏现有数据目录格式

---

## 8. 我对你项目的最终判断

你的项目不需要推倒重来。

更准确的策略是：

- 保留当前产品方向：
  - 文件优先
  - 记忆可读
  - 技能可编辑
  - 运行过程可审计
- 重构当前运行时骨架：
  - 从 `单主控大对象`
  - 变成 `bootstrap + query runtime + tool registry + memory layer + task runtime`

这条路线的收益最大，也最符合 `docs/` 里的设计精神。

---

## 9. 第一批最值得动手的文件

如果要从现在立刻开始，我建议第一批只动这些位置：

- `backend/app.py`
- `backend/config.py`
- `backend/graph/agent.py`
- `backend/api/chat.py`
- `backend/tools/__init__.py`
- `backend/tools/tool_registry.py`
- `frontend/src/lib/store.tsx`

第一批目标不是“功能升级”，而是先把主干抽出来。

---

## 10. 当前落地状态（2026-04-20）

本计划对应的主链重构已经落地到可运行状态，当前基线如下：

- 主运行时已切到 `bootstrap -> AppRuntime -> QueryRuntime -> Memory/Tools/Retrieval/API`。
- `backend/graph/` 兼容目录已完成迁移并删除，旧主控与旧桥接层不再存在于仓库主路径中。
- memory / prompt / session / retrieval / query / runtime 的回归与实验测试已改为直接验证 `backend/memory`、`backend/query`、`backend/runtime`、`backend/retrieval` 新模块。
- `backend/runtime/model_runtime.py` 已具备统一的超时、重试、错误映射和流式包装能力。
- `backend/permissions/` 已形成显式的 policy + decision pipeline。
- `backend/tasks/` 已形成显式任务记录与任务协调器，支持 query/tool 任务记录。
- 前端状态已拆为 `store core + runtime + hooks + reducer`，不再由单个 Provider 承担全部副作用。

当前剩余说明：

- 部分更深层的“多子 agent 并发运行时”仍是后续增强项，不再阻断当前架构收口。
- 文档前文对 `backend/graph/*` 的引用保留为“改造前问题与迁移背景”说明，不代表当前代码仍依赖这些路径。

当前验证基线：

- 后端：`python -m pytest -q`
- 前端单测：`npm run test`
- 前端构建：`npm run build`
- 前端静态检查：`npm run lint`

当前验证结果：

- 后端：`66 passed`
- 前端单测：`4 passed`
- 前端构建：通过
- 前端静态检查：通过

只有在上述命令继续保持通过时，才允许再做后续增强，而不能回退到旧主控继续堆功能。
