# Pi Agent / Coding Agent 源码机制审查：AgentHarness / Session Tree / Save Point / Runtime Rebind

状态：源码审查记录  
日期：2026-07-03  
源码目录：`D:\AI应用\pi-main`

## 1. 审查目标

本报告审查 Pi 的 `packages/agent` 与 `packages/coding-agent`，重点回答：

- Pi 如何定义一次 agent turn、跨 turn session、session tree 和运行时状态；
- Pi 的 durable harness 设计解决了哪些“普通 turn 不可恢复”的问题；
- Pi 是否具备 Hermes Kanban / OpenClaw TaskFlow 那种完整持久任务环境；
- Pi 的 queue、save point、pending writes、branch summary、compaction、runtime rebind 对本项目任务函数和图任务节点有什么参考价值；
- 哪些设计可以借鉴，哪些不能误用为本项目的任务系统。

## 2. 主要审查文件

```text
D:\AI应用\pi-main\packages\agent\docs\durable-harness.md
D:\AI应用\pi-main\packages\agent\docs\agent-harness.md
D:\AI应用\pi-main\packages\agent\docs\hooks.md
D:\AI应用\pi-main\packages\agent\src\harness\agent-harness.ts
D:\AI应用\pi-main\packages\agent\src\harness\types.ts
D:\AI应用\pi-main\packages\agent\src\harness\session\session.ts
D:\AI应用\pi-main\packages\agent\src\harness\session\jsonl-storage.ts
D:\AI应用\pi-main\packages\agent\src\agent-loop.ts
D:\AI应用\pi-main\packages\agent\src\agent.ts
D:\AI应用\pi-main\packages\coding-agent\docs\session-format.md
D:\AI应用\pi-main\packages\coding-agent\docs\sessions.md
D:\AI应用\pi-main\packages\coding-agent\src\core\agent-session.ts
D:\AI应用\pi-main\packages\coding-agent\src\core\agent-session-runtime.ts
D:\AI应用\pi-main\packages\coding-agent\src\core\session-manager.ts
```

## 3. 核心结论

Pi 的成熟点不是“持久任务系统”，而是把 agent turn 的运行边界和 session 的可恢复边界拆得很清楚：

```text
Session JSONL Tree
-> AgentHarness.createTurnState()
-> immutable turn snapshot
-> runAgentLoop()
-> message_end 持久化
-> turn_end save_point
-> flush pending session writes
-> prepareNextTurn 刷新下一次 provider request
-> agent_end settled
```

它的设计核心是：

```text
session 是 durable append-only tree；
harness config 是最新运行配置；
turn snapshot 是当前 provider request 的不可变快照；
pending writes 是 busy 期间接受的 session mutation；
save point 是跨 provider request 的安全换轨点；
host runtime 负责恢复工具、模型、auth、扩展和 resource loader。
```

这对本项目非常有价值，因为我们正在定义“任务像外部工作环境，agent 是进入环境的智能执行体”。Pi 提醒我们：

- session 可以持久化对话、分支、压缩、标签、扩展状态；
- harness 可以控制一次运行中的状态一致性；
- 但 session/harness 仍不等于任务环境；
- 真正的 `TaskWorkEnvironment` 还需要 task、task run、lease、依赖、事件账本、work product、恢复策略和维护机制。

## 4. Durable Harness 文档：Pi 明确承认完全序列化 harness 不现实

`packages\agent\docs\durable-harness.md` 的判断很成熟：`AgentHarness` 自身无法完全 durable，因为很多关键依赖是 host app 注入的运行时代码：

```text
tool implementations
model/auth providers
extensions and hook handlers
resource loaders
system-prompt callbacks/modifiers
```

因此 Pi 的目标是 semi-durable harness：

```text
session = durable append-only state tree
harness = 把自己拥有的状态写入 session entries
host app = resume 时重建兼容的 live dependencies
recovery = 从 durable boundary 重启，而不是恢复 provider stream
```

这条边界非常关键。它说明成熟 agent 不会假装能把“正在流式返回的 provider request”完整恢复；它只恢复已经落到 durable log 的状态。

对本项目的裁决：

- `TaskWorkEnvironment` 可以持久化任务真相、上下文包、产物、状态、事件和 resume marker；
- 但工具实现、模型客户端、文件系统句柄、扩展进程、浏览器连接不应被硬塞进任务 snapshot；
- 恢复时必须验证这些 live dependencies 是否可重建、版本是否兼容；
- provider stream 中断默认只能标记 interrupted，不能假装原地续流。

## 5. AgentHarness 状态模型：config / snapshot / session / pending writes

`packages\agent\docs\agent-harness.md` 把 harness 状态分为四类：

```text
Harness config
Turn snapshot
Session
Pending session writes
```

源码中 `AgentHarness.createTurnState()` 对应这个设计。它每次从 persisted session 构建 context，再读取 resources、session metadata、tools、active tools、system prompt、model、thinking level、stream options，生成本 turn 的快照。

关键实现位置：

```text
packages\agent\src\harness\agent-harness.ts
createTurnState()
createContext()
createStreamFn()
createLoopConfig()
prepareNextTurn()
flushPendingSessionWrites()
handleAgentEvent()
```

成熟点在于：

- getters 读取最新 harness config；
- 当前 provider request 使用 turn snapshot；
- busy 期间 setModel / setThinking / setResources / setTools 影响未来快照，不改当前请求；
- session writes 如果发生在运行中，先进入 pending writes；
- `turn_end` 后 flush pending writes，再生成下一次快照。

这比“直接修改 agent.state.messages”成熟很多，因为它明确隔离：

```text
当前请求已经吃进去的上下文
vs
下一次请求应该看到的新上下文
```

对本项目：

- 图任务节点执行时应有 `ExecutionSnapshot`，一次 provider request 开始后不被外部 mutation 改写；
- 节点运行中接收到的状态变更、维护信号、用户 steering，应进入 `pending_episode_events` 或 `pending_context_writes`；
- 只有到 save point / episode boundary 才刷新下一次上下文包；
- 不能让任务状态的外部更新直接改掉当前模型调用的输入。

## 6. Operation Phase：结构性操作必须显式锁定

`AgentHarnessPhase` 定义为：

```ts
type AgentHarnessPhase = "idle" | "turn" | "compaction" | "branch_summary" | "retry";
```

`prompt()`、`skill()`、`promptFromTemplate()`、`compact()`、`navigateTree()` 都要求 `phase === "idle"`，并且在第一个 `await` 前同步设置 phase。

busy 期间允许：

```text
steer
followUp
nextTurn
abort
runtime config setters
```

成熟点：

- 结构性操作不并发；
- steering/follow-up 是明确的队列语义；
- abort 是运行态控制；
- compaction / tree navigation 是 structural session mutation，不混入普通 turn。

对本项目：

```text
TaskWorkEnvironment 必须有 phase：
idle
episode_running
compacting
repairing
handoff
finalizing
```

并且必须区分：

- 能进入当前 episode 的 steering；
- 只能进入下一 episode 的 nextTurn；
- 必须等待 idle 的结构性操作；
- 可以异步观察但不能改写状态的事件监听。

## 7. Save Point：Pi 最值得借鉴的 turn 内边界

`AgentHarness` 在 `turn_end` 处做三件事：

```text
1. flushPendingSessionWrites()
2. emit save_point
3. 如果 loop 还要继续，prepareNextTurn() 重新 createTurnState()
```

`packages\agent\src\agent-loop.ts` 的低层 loop 在每个 assistant response 和 tool result 结束后发出 `turn_end`，然后调用 `prepareNextTurn()`，再决定是否继续工具循环、steering 或 follow-up。

这个机制解决了一个真实问题：一个 agent run 内可能有多次 provider request。运行期间用户可能切模型、改 thinking、扩展写入 session、工具列表变更、资源刷新。如果直接改当前 request，链路会乱；如果完全忽略，又会错过下一次 provider request。

Pi 的做法是：

```text
当前 provider request 不变；
turn_end save point 后刷新下一 provider request；
agent_end 只负责收尾和 settled。
```

对本项目的任务函数设计：

- 单个 `AgentExecutionEpisode` 内也应该存在多个 `ProviderStep`；
- 每个 `ProviderStep` 结束后产生 `SavePoint`；
- save point 可以写入 task event ledger；
- save point 后才能吸收任务维护、语义图更新、memory injection、tool profile refresh；
- 未到 save point 的 provider stream 不可恢复，只能 interrupted。

## 8. Session JSONL Tree：session 是分支容器，不是任务环境

Pi 的 session 文件是 JSONL。`packages\coding-agent\docs\session-format.md` 和 `packages\agent\src\harness\session\jsonl-storage.ts` 显示，session 包含：

```text
header
message
model_change
thinking_level_change
compaction
branch_summary
custom
custom_message
label
session_info
leaf
```

每个 entry 有：

```text
id
parentId
timestamp
type
```

`leaf` entry 不是内存指针，而是持久化的当前树位置。重开 session 时，通过读取最后一个影响 leaf 的 entry 还原 active leaf。

`Session.buildContext()` 从当前 leaf 回溯到 root，然后：

- 收集路径上的消息；
- 应用最新 model / thinking level；
- 如果路径上有 compaction，则先插入 compaction summary，再保留 `firstKeptEntryId` 后的消息；
- 将 `branch_summary` 与 `custom_message` 转成 LLM 可见消息；
- `custom` entry 只用于扩展状态，不进入 LLM context。

成熟点：

- session 支持树形分支，不需要每次 fork 都复制全量历史；
- branch summary 让 agent 离开某个分支后仍保留关键上下文；
- custom entry 和 custom message 明确区分“扩展持久状态”和“模型可见上下文”；
- label/session_info 是人类导航辅助，不污染普通消息。

限制也很明确：

- session tree 是对话历史结构，不表达任务依赖；
- entry parentId 是对话分支，不是工作流 DAG；
- session 里没有 task priority、owner、lease、claim、dependency、artifact acceptance、run attempt；
- session compaction 是上下文治理，不是任务完成证据。

对本项目：

```text
ConversationSession 可以借鉴 Pi 的 JSONL/tree/leaf/branch_summary；
TaskWorkEnvironment 不应直接复用 session tree 作为任务图。
```

任务图的依赖、审查图的 tree reduce、项目语义网络的层级节点，都应属于任务/项目网络控制面，而不是聊天 session entry。

## 9. Queue 语义：steer / followUp / nextTurn 三类消息不能混

Pi 区分：

```text
steer
= 当前 assistant turn 执行完工具后、下一次 LLM 调用前注入

followUp
= agent 本来要停止时继续追加

nextTurn
= 下一次用户 prompt 前作为 aside/context 插入
```

`AgentHarness.abort()` 清掉 steer/followUp，但不清 `nextTurn`。`AgentSession` 上层也维护 `_steeringMessages`、`_followUpMessages` 和 `_pendingNextTurnMessages` 供 UI 展示。

这对本项目很重要。图任务节点和任务环境不应该只有一个“追加用户消息”入口，至少需要：

- `episode_steer`：影响当前 episode 的下一次 provider step；
- `episode_follow_up`：当前 episode 收口后继续；
- `next_episode_context`：下一次进入任务环境时作为任务上下文；
- `task_note`：写入任务环境，但不一定进入模型上下文；
- `work_product`：可消费产物，不是聊天消息。

否则用户打断、维护 agent 补图、系统注入 repair hint、上游节点回传，都容易串线。

## 10. Agent Loop 与 Tool Loop：工具失败进入 toolResult，不等于任务失败

`packages\agent\src\agent-loop.ts` 的核心结构：

```text
agent_start
turn_start
message_start / message_end for user prompt
stream assistant response
execute tool calls
message_start / message_end for toolResult
turn_end
prepareNextTurn
drain steering / followUp
agent_end
```

工具调用支持 `parallel` / `sequential`，每个工具调用有：

```text
prepareToolCallArguments
validateToolArguments
beforeToolCall hook
tool.execute(...)
tool_execution_update
afterToolCall hook
tool_execution_end
toolResult message
```

当工具不存在、参数校验失败、before hook block、工具抛错、after hook 抛错时，Pi 都把错误转换成 `toolResult` 消息，而不是让整个 process 崩掉。

成熟点：

- tool call 是模型可观察事件；
- tool result 是下一次模型调用的输入；
- hook 可以 block 或 patch result；
- 工具批次是否 terminate 由 tool result 决定；
- tool error 归入模型反馈，而不是直接变成任务失败。

对本项目：

- 单节点 agent 执行工具失败时，默认应产生 `ToolObservation` / `ToolResult` 给 agent 自我恢复；
- 只有超出契约、资源不可用、权限不满足、任务环境被抢占等情况，才升级为 `EpisodeFailed`；
- 工具调用事件应写入 run/event ledger，不能只藏在 transcript；
- 如果未来支持自动恢复 tool call，必须有 idempotent / retry-safe 元数据。

## 11. AgentSession 上层：功能完整，但边界更肥

`packages\coding-agent\src\core\agent-session.ts` 是 interactive、print、rpc 共用的上层 session 封装。它承担：

- agent state access；
- event subscription 和 session persistence；
- model/thinking 管理；
- compaction / auto-compaction；
- retry；
- bash execution；
- session switching / branching；
- extension system；
- tool registry；
- system prompt refresh；
- HTML/JSONL export。

它通过 `_handleAgentEvent()` 在 `message_end` 时写入 `SessionManager`，并在 `agent_end` 后根据最后 assistant message 决定 auto retry / compaction / continuation。

关键实现：

```text
_runAgentPrompt()
  -> agent.prompt(messages)
  -> while (_handlePostAgentRun()) agent.continue()

_handleAgentEvent()
  -> emit extension event
  -> emit UI listeners
  -> message_end 持久化 message/custom_message
  -> 记录 last assistant message

_runAutoCompaction()
  -> prepareCompaction(branch entries)
  -> extension 可提供 compaction
  -> appendCompaction()
  -> rebuild agent.state.messages
```

这说明 Pi 的 coding-agent 上层仍然是“会话产品层”，不是纯粹任务底座。它把 UI、扩展、bash、compaction、retry、tool registry 都放进 `AgentSession`，工程上可用，但不适合直接作为我们任务系统的形态。

对本项目：

- 我们应借鉴 `AgentHarness` 的边界，而不是照抄 `AgentSession` 的肥大职责；
- `TaskWorkEnvironment` 不应同时承担 UI、extension runner、tool registry、memory、graph scheduling；
- 这些能力要通过明确 service 注入和 event bus 连接；
- 任务环境只拥有任务真相、上下文包、episode、状态、产物和恢复边界。

## 12. AgentSessionRuntime：resume / fork 时重建 cwd-bound services

`packages\coding-agent\src\core\agent-session-runtime.ts` 负责运行时切换：

```text
createAgentSessionRuntime()
-> createRuntime({ cwd, agentDir, sessionManager, sessionStartEvent })
-> AgentSessionRuntime
```

在 `/new`、`/resume`、`/fork`、`importFromJsonl()` 时，它会：

```text
emit session_before_switch / session_before_fork
teardownCurrent()
  -> session_shutdown
  -> beforeSessionInvalidate
  -> session.dispose()
createRuntime(...)
apply(new session + services + diagnostics)
finishSessionReplacement()
```

这与 durable-harness 文档一致：session 是可持久状态，runtime dependencies 由 host 重新创建。

对本项目：

- `TaskWorkEnvironment.resume()` 不应只读取数据库，还要重新绑定 cwd、file system service、project network store、tool registry、model registry、memory service；
- resume 成功前必须校验环境是否匹配；
- 如果项目目录不存在、工具包缺失、模型不可用，应进入 `blocked_requires_environment_rebind`，而不是让 agent 猜。

## 13. Compaction / Branch Summary：上下文手术，不是任务真相

Pi 的 compaction entry 保存：

```text
summary
firstKeptEntryId
tokensBefore
details
fromHook
```

branch summary entry 保存：

```text
fromId
summary
details
fromHook
```

这些 entry 会参与 `buildSessionContext()`。它们的作用是让 LLM 在有限上下文里保留历史重点。

但它们不是任务结果：

- compaction summary 不能证明任务完成；
- branch summary 不能证明某条代码链路正确；
- details 可以存扩展元数据，但不是 canonical artifact store；
- summary 可以帮助恢复理解，但不能代替 work product。

对本项目：

```text
Task memory / compaction summary / semantic network summary
必须和 WorkProduct / Evidence / Artifact 分开。
```

例如项目语义网络审查：

- 文件级语义报告是 work product；
- 函数链路索引是 project network artifact；
- 节点运行中的压缩摘要只是 task context surgery；
- 三者不能合并成一个“总结”字段。

## 14. Pi 的不足：它还不是完整任务机制

Pi 缺少本项目需要的几类结构：

```text
Task object
TaskRun / ExecutionEpisode ledger
claim / lease / heartbeat / reclaim
dependency graph
work product registry
artifact acceptance gate
task-level memory space
multi-agent assignment
node-level contract snapshot
semantic network generation lifecycle
repair / maintenance 同源机制
```

Pi 的 queues 当前主要是运行态消息队列；durable-harness 文档已经提出要把 queue enqueued / consumed、operation start / finish、turn start / finish、provider/tool start / finish 做成 durable entries，但这仍是设计计划，不是完整任务系统。

因此，Pi 适合作为：

```text
turn/session durability reference
agent run lifecycle reference
context surgery reference
runtime rebind reference
```

不适合作为：

```text
task system reference
multi-agent task graph reference
project semantic network build system reference
```

## 15. 对本项目的工程借鉴清单

应借鉴：

1. `Session` 作为 append-only tree，而不是普通数组 transcript。
2. `leaf` 作为持久化当前位置，而不是内存 cursor。
3. `turn snapshot` 作为一次 provider request 的不可变输入。
4. `save point` 作为本次 run 内吸收 mutation 的唯一安全边界。
5. busy 期间的 session writes 进入 pending writes，按确定顺序 flush。
6. `custom` 与 `custom_message` 分离，区分“系统/扩展状态”和“模型可见上下文”。
7. `compaction` 与 `branch_summary` 进入 session context，但不当作任务真相。
8. resume 时由 host 重新绑定 live dependencies。
9. provider stream 不可恢复，默认 interrupted。
10. tool 自动重试必须依赖 idempotent/retry-safe 元数据。

不应借鉴或不能直接照搬：

1. 不能把 session tree 当任务图。
2. 不能把 compaction summary 当 work product。
3. 不能把上层 `AgentSession` 的肥大职责搬进 `TaskWorkEnvironment`。
4. 不能只靠 in-memory queue 支撑持久任务。
5. 不能把 extension custom entries 当 canonical task ledger。
6. 不能用普通 turn id 代替 task run id。

## 16. 对任务函数 / 神经控制层的具体启发

本项目应形成三层：

```text
ConversationSession
  保存用户交互和 agent transcript，可树状分支，可压缩，可命名。

TaskWorkEnvironment
  保存任务真相、上下文包、episode、事件账本、产物、恢复边界、依赖和状态。

Graph / Project Control System
  保存图任务算法、项目物理网络、语义网络、信号链路、维护与修复机制。
```

单 agent 的“任务函数”不应是简单函数调用，而应是：

```text
TaskContextPackage
-> AgentExecutionEpisode
-> ProviderStep*
-> ToolObservation*
-> SavePoint*
-> WorkProduct / EpisodeResult
-> TaskEventLedger
```

每个 `ProviderStep` 都应有：

```text
resolved prompt snapshot
allowed tools snapshot
memory/context snapshot
project network snapshot refs
model/thinking snapshot
input evidence refs
output message / tool calls / tool results
save point result
```

这正是 Pi 的 turn snapshot + save point 给我们的工程标准。

## 17. 结论

Pi 是本轮调研里“turn/session 生命周期”最清晰的参考之一。它没有把 agent 运行简单看成一次 `prompt()`，而是定义了：

```text
phase
snapshot
pending writes
save point
session tree
runtime rebind
compaction / branch summary
hook / extension mutation boundary
```

但它仍然不是完整任务系统。它的成熟结论应进入本项目底座设计：

```text
用 Pi 的 harness/session 边界管理 agent 运行；
用 Hermes/OpenClaw/Dify 的 task/run/event 思路管理任务真相；
用本项目的 Deep AST + Semantic Network 管理项目控制空间。
```

如果把这三层混在一起，系统会重新退化成“靠长上下文记任务”；如果把三层分开，agent 才能像执行体一样进入被系统管理的任务环境，并在项目语义网络上做可追踪、可恢复、可维护的工作。
