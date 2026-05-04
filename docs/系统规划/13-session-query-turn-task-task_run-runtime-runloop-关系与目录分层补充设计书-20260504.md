# session、query、turn、task、task_run、runtime、runloop 关系与目录分层补充设计书

日期：2026-05-04

## 一、文档定位

本文是对第二阶段蓝图的补充说明。

它重点回答两个问题：

1. `session / query / turn / task / task_run / runtime / runloop` 这七层关系到底该怎么定义
2. 后端目录应该按什么系统边界和层级整理，才能避免继续跨层粘连

本文建立在以下材料之上：

- [03-编排系统详细设计书-20260504.md](/d:/AI应用/langchain-agent/docs/系统规划/03-编排系统详细设计书-20260504.md)
- [07-源码现状与重构映射蓝图-20260504.md](/d:/AI应用/langchain-agent/docs/系统规划/07-源码现状与重构映射蓝图-20260504.md)
- [10-任务系统-编排系统-runtime-先进架构对照结论-20260504.md](/d:/AI应用/langchain-agent/docs/系统规划/10-任务系统-编排系统-runtime-先进架构对照结论-20260504.md)
- [12-第二阶段编排系统正式建模与runtime切换实施蓝图-20260504.md](/d:/AI应用/langchain-agent/docs/系统规划/12-第二阶段编排系统正式建模与runtime切换实施蓝图-20260504.md)

## 二、先给结论

最核心的结论只有三条：

1. `runloop` 不是整个 `runtime`，而是 `runtime` 里的 durable execution loop
2. `runloop` 不应该绑定 raw query，而应该绑定一次正式执行实例 `task_run`
3. 你当前代码的问题不是“TaskRunLoop 这个方向错了”，而是 `query / turn / task` 三层还没彻底拆开

因此，后续正式关系应当稳定为：

```text
session
  -> turn
  -> task
  -> task_run
  -> runloop
```

而不是：

```text
query
  -> runloop
```

`query` 只适合作为 API 入口动作名，不适合作为 durable execution 的正式持久化 owner。

## 三、七层概念的正式定义

## 3.1 Session

`session` 是会话连续体。

它回答：

`这是哪一条持续对话/持续工作上下文`

它负责承载：

- 历史消息连续性
- 用户长期上下文
- 会话级记忆
- 多次 turn 之间的连续状态

它不是：

- 单次任务
- 单次执行循环

## 3.2 Query

`query` 是一次外部入口动作。

它回答：

`这次外部 API/SDK 传进来的请求是什么`

它更像：

- SDK 调用入口
- CLI 一次发起动作
- 对话系统的一次输入包

它不是 durable owner。

## 3.3 Turn

`turn` 是一次会话轮次。

它回答：

`这次 session 里的第几轮输入/交互`

它通常包含：

- 用户输入
- 本轮临时上下文
- 本轮路由判断

它比 `query` 更稳定，因为一个 `query` 在系统内部最终会落成某个 `turn`。

## 3.4 Task

`task` 是被任务系统正式识别后的执行目标。

它回答：

`系统认为这次到底要做什么`

它应该具备：

- task family
- task mode
- template/workflow/projection/contract 绑定

它不是 API 输入动作，而是系统内部正式对象。

## 3.5 TaskRun

`task_run` 是某个 task 的一次具体执行实例。

它回答：

`这个 task 这一次是怎么跑的`

它应该承载：

- 执行中的状态
- checkpoint
- resume
- approval wait
- execution receipt
- event trace

因此：

`task_run` 才是 runloop 的正确绑定对象

不是：

- raw query
- session 本身
- task 静态定义本体

## 3.6 Runtime

`runtime` 是执行环境总称。

它负责：

- model executor
- tool executor
- permission / gate
- context runtime view
- checkpoint / resume
- trace / commit / finalization

它是环境层，不是任务定义层。

## 3.7 RunLoop

`runloop` 是 runtime 中的循环执行器。

它负责：

- 当前轮执行推进
- 工具结果回来后如何继续
- checkpoint 何时写入
- approval 何时暂停
- terminal condition 何时触发

所以更准确的定义是：

`runloop = runtime 内部面向 task_run 的 durable execution loop`

## 四、为什么 runloop 应该绑定 task_run，而不是 query

## 4.1 query 只表示入口，不表示可恢复执行实例

一个 query 能表达的只是：

- 用户说了什么
- 外部调用传了什么参数

但它天然不表达：

- 当前执行到第几步
- 是否进入 approval wait
- 哪个 checkpoint 可以恢复
- 是否已经生成 tool receipt

这些才是 runloop 真正要管理的东西。

## 4.2 task_run 才拥有 durable execution 所需字段

从你当前代码看，`TaskRun` 和 `RuntimeCheckpoint` 已经天然符合这个角色：

- [backend/orchestration/runtime_loop/models.py](/d:/AI应用/langchain-agent/backend/orchestration/runtime_loop/models.py:30)
- [backend/orchestration/runtime_loop/checkpoint.py](/d:/AI应用/langchain-agent/backend/orchestration/runtime_loop/checkpoint.py:13)

它们承载的是：

- `task_run_id`
- `session_id`
- `task_id`
- `runtime_lane`
- `latest_checkpoint_ref`
- `event_offset`
- `loop_state`

这已经不是 query 语义，而是标准 execution instance 语义。

## 4.3 外部成熟系统也是“入口动作”和“持久化 owner”分离

参考：

- Claude Code SDK Overview  
  https://docs.anthropic.com/en/docs/claude-code/sdk
- Claude Code Session Management  
  https://docs.claude.com/en/docs/claude-code/sdk/sdk-sessions
- LangGraph Persistence  
  https://docs.langchain.com/oss/python/langgraph/persistence
- LangGraph Durable Execution  
  https://docs.langchain.com/oss/python/langgraph/durable-execution

这些资料共同指向一个事实：

- 对外入口可以叫 `query`
- 但持久化与恢复是围绕 `session / thread / run / checkpoint`
- 不是围绕“query 字符串本身”

因此你看到 Claude Code SDK 暴露 `query()`，不等于：

`内部 durable loop 的 canonical owner 就应该是 query`

更准确的理解是：

- `query()` 是进入系统的方法名
- `session` 是连续对话 owner
- `run` 或 `execution instance` 才是执行恢复 owner

## 五、你当前实现里的真实问题

你当前不是“TaskRunLoop 这个方向错了”，而是下面这个问题：

`task_id 目前经常还是 turn/query 风格，导致 task_run 看起来像 query_run`

证据：

- [backend/query/runtime.py](/d:/AI应用/langchain-agent/backend/query/runtime.py:112) 会生成  
  `task_id = f"turn:{request.session_id}:{...}"`

这说明当前真实链路是：

```text
session
  -> query request
  -> turn-like task_id
  -> task_run
  -> runloop
```

所以不自然感来自这里：

`task` 这层现在还没完全成为正式任务对象，而是被 turn 临时占位了`

正确修法不是把 `TaskRunLoop` 改成 `QueryRunLoop`，而是把这三层彻底拆开：

- `turn_id`
- `task_id`
- `task_run_id`

## 六、建议的正式 ID 关系

建议统一为：

- `session_id`
- `turn_id`
- `task_id`
- `task_run_id`

它们的关系建议是：

### 6.1 session_id

表示会话连续体。

例：

```text
session:36c0b973...
```

### 6.2 turn_id

表示本次轮次。

例：

```text
turn:session:36c0b973...:17
```

### 6.3 task_id

表示正式任务对象。

对于通用任务：

```text
task.chat.general_response
```

对于具体登记任务：

```text
task.dev.light_web_game
```

对于 turn 生成的即时任务实例：

```text
taskinst:turn:...:general_response
```

### 6.4 task_run_id

表示某次执行实例。

例：

```text
taskrun:session:...:taskinst:...:a1b2c3d4
```

这样之后：

- 一个 session 有多个 turn
- 一个 turn 可能命中一个或多个 task
- 一个 task 可以有多次 task_run
- runloop 只绑定 task_run

## 七、目录分层的正式建议

后端目录不应该继续按“历史名词 + 局部实现”自然生长，而应按正式系统边界收口。

建议最终按五层看：

## 7.1 Interface Layer

目录建议：

- `backend/api`
- `backend/runtime/app_runtime.py`

职责：

- HTTP/streaming/CLI entry
- 参数校验
- session 接入

不应承担：

- 正式任务装配
- 正式编排装配

## 7.2 Control Plane Layer

目录建议：

- `backend/query`
- `backend/tasks`

职责：

- query 入口适配
- turn 归口
- task 识别
- task registry / workflow / bindings

注意：

`query` 应被解释为 interface-to-control adapter，不应再被看成 runtime 本体。

## 7.3 Orchestration Layer

目录建议：

- `backend/orchestration`

职责：

- body profile
- task body orchestration
- runtime spec
- stage projection
- runtime directives

这里应成为：

`TaskExecutionAssembly` 之后的唯一正式 owner

## 7.4 Runtime Execution Layer

目录建议：

- `backend/orchestration/runtime_loop`
- `backend/execution`
- `backend/output_boundary`

职责：

- execute
- checkpoint
- resume
- observation
- finalization

注意：

`runtime_loop` 是编排系统下的执行子层，不是独立业务系统。

## 7.5 Supply Systems Layer

目录建议：

- `backend/soul`
- `backend/memory_system`
- `backend/operations`
- `backend/health_system`

职责：

- 给编排系统提供输入材料

这些系统不应绕过编排系统直接决定 runtime 结构。

## 八、目录治理原则

后续整理目录时，统一遵守以下规则。

## 8.1 每个正式系统只能有一个 public boundary

例如：

- 任务系统 public boundary 在 `backend/tasks`
- 编排系统 public boundary 在 `backend/orchestration`
- 记忆系统 public boundary 在 `backend/memory_system`

不要再出现：

- `memory` 和 `memory_system` 长期双主边界
- `health-system` 和 `health_system` 双目录并行
- `runtime-loop` 既像数据目录又像系统目录

当前已落实到源码的结论：

- `backend/memory_system` 是记忆系统唯一正式入口
- `backend/structured_memory` 是其内部实现层
- 原 `backend/memory` 已被吸收并删除

## 8.2 包目录和持久化目录必须分离

代码包应该是：

- `backend/orchestration/runtime_loop`

持久化数据目录应该是：

- `storage/runtime_state/`

但命名上建议后续进一步区分：

- 代码包：`runtime_loop`
- 数据目录：`runtime_state` 或 `runtime_store`

否则视觉上太像两个并列系统。

## 8.3 compat 文件不能藏在正式系统根目录长期常驻

例如：

- `backend/soul/task_runtime_compat.py`

这种文件如果过渡期保留，应该明确放进：

- `compat/`
- `adapters/legacy/`

而不是看起来像正式系统能力。

## 8.4 __init__.py 不应继续导出跨层残留对象

例如任务系统不该继续正式导出：

- `TaskPromptContract`
- `ProjectionRequirement`
- `build_task_runtime_contract`

因为这些都不是任务系统完成态下的正式边界。

## 九、后续目录重构建议

建议按以下顺序推进。

## 9.1 先清 public export

优先收口：

- `backend/tasks/__init__.py`
- `backend/soul/__init__.py`

目标：

- 谁是正式对象，谁就留
- compat 对象从 public export 移除

## 9.2 再切主入口

优先改：

- `backend/runtime/agent_chain.py`
- `backend/query/runtime.py`

目标：

- 不再直接依赖 `tasks.contract_builder`

## 9.3 再清 compat bridge

优先处理：

- `backend/soul/task_runtime_compat.py`
- `/tasks/runtime-contract`

## 9.4 最后整理目录命名

例如后续统一：

- `health-system` -> 删除或吸收进 `health_system`
- `session-memory` -> 吸收进 `memory_system` 或改成纯数据目录
- `runtime-loop` 数据目录 -> 改为更明确的 runtime state store 命名

## 十、最终推荐关系图

最终建议稳定为：

```text
Interface
  api / app_runtime

Control Plane
  query -> turn -> task

Orchestration
  task_execution_assembly
    -> task_body_orchestration
    -> agent_runtime_spec

Runtime
  task_run
    -> runloop
    -> checkpoint/resume/finalize

Supply Systems
  soul / memory_system / operations / health_system
```

对应持久化 owner：

```text
session 持续化会话
turn 记录轮次
task 记录正式任务对象
task_run 记录执行实例
runloop 驱动 task_run 的可恢复执行
```

这条线一旦立住，你后面的第二阶段实现就不会再在 `query`、`task`、`runtime` 之间来回打架。

