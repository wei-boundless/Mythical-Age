# 成熟 Agent 源码调研总汇总：Turn / Session / TaskWorkEnvironment / TaskRun 边界裁决

状态：源码审查汇总  
日期：2026-07-03  
审查目录：`backend\runtime\context_management\design_docs\execution_plans\hierarchical_ast_project_graph\agent_source_audits`

## 1. 汇总目标

本汇总基于本目录 01-09 份源码审查报告，目标是为本项目的“单 Agent 持久任务工作环境”和“图任务时空运行体系”确定成熟工程标准。

本次调研关注的不是“哪个 agent 更强”，而是成熟 agent 如何区分：

```text
Turn
Session / Conversation
Runtime Run
Task / TaskWorkEnvironment
TaskRun / ExecutionEpisode
BackgroundJob
WorkProduct / Artifact
```

这些概念如果混在一起，本项目的任务系统会退化成“长上下文 + 提示词记任务”。成熟做法必须是：agent 作为智能执行体进入由系统持久化管理的工作环境，系统负责状态、证据、产物、依赖、恢复和审计。

## 2. 审查报告索引

```text
01_openai_codex_turn_task_mechanism_audit.md
02_claude_code_nb_turn_task_mechanism_audit.md
03_opencode_dev_turn_task_mechanism_audit.md
04_opencode_main_turn_task_mechanism_audit.md
05_openclaw_turn_task_flow_runtime_mechanism_audit.md
06_dify_workflow_conversation_run_mechanism_audit.md
07_dify_agent_agenton_run_snapshot_mechanism_audit.md
08_hermes_agent_gateway_kanban_task_environment_mechanism_audit.md
09_pi_agent_harness_session_runtime_mechanism_audit.md
```

## 3. 总裁决

成熟 agent 普遍不会把“任务”压扁成一次模型调用。可见的成熟边界是：

```text
Turn = 当前交互节拍或一次 agent loop 片段
Session / Conversation = 跨 turn 的会话和上下文容器
Runtime Run = 一次可观测执行过程
TaskWorkEnvironment = 可持久化、可恢复、可分配、可审计的工作环境
TaskRun / ExecutionEpisode = agent 进入任务环境的一次运行尝试
BackgroundJob = 运行态异步 job，不等于任务环境
WorkProduct / Artifact = 可消费产物和证据，不等于聊天消息
```

本项目应采用的方向：

```text
ConversationSession 负责对话连续性；
AgentHarness 负责单次 agent 执行一致性；
TaskWorkEnvironment 负责任务真相；
GraphRuntime 负责复杂任务调度；
Project Semantic Network 负责项目理解、定位、链路和神经控制；
WorkProduct Store 负责产物、证据和审查报告。
```

## 4. 各成熟系统的核心机制结论

| 系统 | 成熟机制 | 不应误解 |
| --- | --- | --- |
| OpenAI Codex | 长生命周期 session + per-turn task runner + 多 agent thread/session tree + mailbox | `SessionTask` 是异步 turn runner，不是持久任务环境 |
| Claude Code NB | `QueryEngine` 管一段对话，`submitMessage` 启动 turn，后台 `Task` 有 id/status/output file/offset | background task 更像子任务运行输出，不是完整 task work environment |
| opencode-dev | session/message/tool state/background job/busy-cancel 控制比较清楚 | session 和 background job 不是任务真相层 |
| opencode-main | Go 版本 tool loop 和 child task session 提供早期模式 | 缺少 task lifecycle、checkpoint 和 work product |
| OpenClaw | `TaskRecord` / `TaskFlowRecord` / SQLite `task_runs` / flow state/wait/child/retry/cancel | 它更接近工作流任务控制面，不是普通聊天 session |
| Dify Workflow | Conversation/Message 与 WorkflowRun/NodeExecution/GraphRuntimeState 区分清楚 | workflow run 是流程执行对象，不是单 agent 对话 |
| Dify Agent / Agenton | RunRecord + event stream + CompositorSessionSnapshot + resource_context | live resources 不序列化，snapshot 只恢复可序列化状态 |
| Hermes | Gateway session 与 Kanban tasks/task_runs/task_events/claim/heartbeat/artifacts 分离 | `run_conversation()` 的 task_id 主要是 turn/resource isolation，不是用户任务 |
| Pi | JSONL session tree + turn snapshot + pending writes + save point + runtime rebind | Pi 强在 turn/session durability，还不是完整任务环境 |

## 5. 成熟架构共同点

### 5.1 Turn 不拥有任务真相

Codex、Hermes、Pi、Dify 都说明：turn 只是一次执行节拍。它可以产生消息、工具调用、产物或状态更新，但不能成为任务真相本身。

本项目中：

```text
turn_id != task_id
provider_request_id != task_run_id
tool_call_id != artifact_id
conversation_id != task_work_environment_id
```

### 5.2 Session 是上下文容器，不是任务系统

Pi 的 JSONL tree、Codex 的 session、Hermes gateway session、Dify conversation 都用于保存交互连续性、上下文、路由或 resume 信息。

它们可以关联任务，但不能替代任务：

```text
session 可以保存 transcript；
task 必须保存 goal、status、owner、dependencies、runs、events、artifacts、recovery。
```

### 5.3 Runtime run 必须可观测

成熟系统都有事件流或运行记录：

```text
agent_start / turn_start / message_start / message_end / tool_start / tool_end / turn_end / agent_end
workflow_run / node_execution
task_runs / task_events
RunRecord / RunEvent
```

本项目的 `AgentExecutionEpisode` 必须有 event ledger。不能只保存最后一段回答。

### 5.4 恢复必须从 durable boundary 开始

Pi 明确指出 provider stream 不可恢复；Dify Agenton 也把 live resource 和 session snapshot 分开；Hermes 对 app-server session 有 retire/recreate；OpenClaw 使用数据库恢复 flow state。

本项目应固定：

```text
Provider stream interrupted -> mark interrupted
Tool call unfinished -> 不自动重试，除非工具声明 idempotent/retry-safe
Compaction unfinished -> 可在无最终 entry 时重跑
Task episode unfinished -> 从最近 save point / checkpoint 恢复或标记中断
```

### 5.5 WorkProduct 必须独立于聊天消息

Hermes Kanban 的 `complete_task(summary, metadata, artifacts)`、OpenClaw 的 task flow state、Dify 的 workflow node execution 和 artifacts 都说明：可消费产物不能只是一段 assistant message。

本项目项目语义网络尤其需要：

```text
根目录人类报告
层级语义报告
文件级审查报告
语义坐标索引
链路信号索引
断点/修复报告
证据引用
generation 发布记录
```

这些都应进入 WorkProduct / Artifact Store，而不是塞进 session transcript。

## 6. 本项目目标模型

### 6.1 ConversationSession

职责：

- 保存用户与 agent 的交互历史；
- 支持分支、压缩、命名、导出；
- 保存可见上下文和人类导航信息；
- 可以引用任务或任务产物。

不能承担：

- 不拥有任务状态；
- 不调度图任务；
- 不决定 work product 是否有效；
- 不作为项目语义网络的 source of truth。

### 6.2 AgentHarness

职责：

- 构造一次 agent execution 的 prompt/context/tool/model snapshot；
- 执行 provider/tool loop；
- 产生事件；
- 管理 save point、abort、steer、follow-up；
- 把可持久事件交给上层。

不能承担：

- 不保存任务真相；
- 不直接管理项目网络 generation；
- 不自行决定任务依赖；
- 不把提示词当任务数据库。

### 6.3 TaskWorkEnvironment

职责：

- 保存任务目标、契约、状态、owner、lease、优先级；
- 保存 `AgentExecutionEpisode`；
- 保存 task event ledger；
- 保存依赖和阻塞；
- 管理恢复、重试、handoff、repair；
- 绑定 WorkProduct / Evidence。

这是本项目需要补强的核心。

### 6.4 GraphRuntime

职责：

- 以算法调度任务节点；
- 把节点视为 agent execution body；
- 支持 tree_reduce、loop_iteration、dynamic expansion、fanout/fanin；
- 保存图运行状态和节点结果；
- 不承载具体项目网络设施。

### 6.5 Project Semantic Network

职责：

- 基于物理网络建立语义叠加；
- 管理层级节点、文件模块、函数/class/参数/调用链；
- 给 agent 提供深度定位、链路归纳和神经控制路径；
- 由项目网络管理系统维护，而非图任务系统维护。

## 7. 对“任务函数”的工程定义

用户提出的“任务函数”不是把任务改成代码函数，而是指：任务需要一个外部环境，agent 像函数执行体一样接收输入、产生输出，但系统负责上下文、状态和产物。

成熟定义应为：

```text
TaskContextPackage
  输入：任务契约、当前状态、必要资源、语义网络坐标、证据 refs、允许工具

AgentExecutionEpisode
  执行：agent 根据 context package 运行，可包含多个 provider step 和 tool step

SavePoint
  边界：每个可恢复安全点，吸收 pending mutation

EpisodeResult
  输出：结构化结果、work product refs、状态变更 proposal、失败原因

TaskReducer
  归并：把 episode result 写回 TaskWorkEnvironment
```

这比“task = prompt + response”成熟得多，也能接住图任务、多 agent 审查、项目语义网络维护和中断恢复。

## 8. 对深度项目网络的意义

用户的目标是强化 agent 的架构意识、复用意识、定位能力和链路归纳能力。成熟 agent 调研给出的结论是：仅靠模型上下文不够，必须有外部结构。

本项目三层网络应这样落位：

```text
物理层
  git / file tree / deep AST / symbol / call / import / route

语义层
  系统/目录/文件/模块/function 的职责、意图、风险、依赖说明

神经控制层
  agent 如何顺着物理路径和语义路标定位、审查、修改、验证、维护
```

成熟系统没有直接给出“项目语义网络”成品，但它们给出了运行边界标准：

- 物理事实必须由系统抽取；
- 语义判断必须由 agent 在证据约束下产生；
- 产物必须独立保存；
- 任务必须有 episode/run 记录；
- 恢复必须从 durable boundary 开始；
- 维护要用事件和 generation，而不是靠记忆反复插入。

## 9. 对后续架构优化的硬约束

1. 禁止把 `conversation/session` 当任务表。
2. 禁止把 `turn_id` 当 `task_id`。
3. 禁止把 assistant 最终回答当 work product 唯一来源。
4. 禁止把 compaction summary 当任务事实。
5. 禁止把工具调用事件只留在 transcript。
6. 禁止恢复 provider stream；只能恢复 durable boundary。
7. 禁止工具无幂等声明自动重试。
8. 禁止图任务系统管理项目网络设施；图任务只调度任务。
9. 禁止项目语义网络脱离物理 AST/file/git 骨架。
10. 禁止让 agent 自由铺语义网；agent 必须沿物理层铺语义层。

## 10. 推荐目标架构

```text
User Turn
  -> ConversationSession
  -> Task Router / TaskWorkEnvironment
  -> TaskContextPackage Builder
  -> AgentHarness
  -> AgentExecutionEpisode
  -> ProviderStep / ToolStep / SavePoint
  -> EpisodeResult
  -> TaskReducer
  -> WorkProduct Store
  -> Project Semantic Network Store
  -> GraphRuntime fanin / next node
```

其中：

- `ConversationSession` 可以保存用户看到的交互；
- `TaskWorkEnvironment` 保存任务真相；
- `AgentHarness` 不知道图任务业务，只执行 episode；
- `GraphRuntime` 不知道项目网络细节，只调度节点；
- `Project Semantic Network Store` 保存物理+语义+神经控制图；
- `WorkProduct Store` 保存人类报告、机器索引和证据。

## 11. 最小实施闭环

建议下一步不是继续加 prompt，而是把底座边界先打稳：

1. 定义 `TaskWorkEnvironment` / `AgentExecutionEpisode` / `WorkProduct` 数据模型。
2. 把 graph node 的执行落到 `AgentExecutionEpisode`，不要让节点直接等同一次 prompt。
3. 增加 episode event ledger：provider step、tool step、save point、artifact emitted、state proposal。
4. 将审查图产物写入 WorkProduct Store：根报告、层级报告、文件报告、语义坐标、链路信号。
5. 将项目语义网络从 task system 搬到项目网络管理系统/Store。
6. 将 graph_system 保持为图任务算法母体：tree_reduce、loop_iteration、dynamic expansion。
7. 建立 resume 策略：unfinished episode 默认 interrupted；可从 save point 继续。
8. 建立 repair/maintenance 同源机制：断点检测后创建维护任务，不靠手工补文件。

## 12. 最终结论

本轮源码调研的关键收获是：

```text
成熟 agent 的核心不是“更会说”，而是边界更清楚。
```

Codex、Hermes、Pi、Dify、OpenClaw 等系统都在不同层面证明：

- turn 只是执行节拍；
- session 只是连续性容器；
- run 是可观测执行；
- task 是系统管理的工作环境；
- work product 是独立产物；
- 恢复只能从持久边界开始；
- agent 的智能应被环境承载，而不是被环境替代。

对本项目而言，正确路线是：

```text
用 Pi/Codex 的 turn/session 边界控制单 agent；
用 Hermes/OpenClaw/Dify 的 task/run/event 思路控制任务；
用 Deep AST + Project Semantic Network 控制项目理解；
用 GraphRuntime 调度复杂任务；
用 WorkProduct Store 固化审查和索引产物。
```

这套结构才能支撑用户提出的“让 agent 像顺着网络路径行动一样理解、定位、审查、修改和维护项目”。
