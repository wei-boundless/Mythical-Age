# 单 Agent 持久任务工作环境底座整合计划

状态：设计计划，待审阅后实施  
日期：2026-07-03  
前置文档：`14_graph_task_spacetime_runtime_architecture_plan.md`

## 1. 核心修正

“任务函数”只能作为类比，不能作为架构本体。

更准确的裁决是：

```text
Task = Persistent Managed Work Environment
任务 = 持久化的受管理工作环境
```

任务不应该被压扁成函数形式。任务更像人在公司里负责的一项工作：

- 公司提供岗位、流程、资料、工具、权限、档案、审查和交接制度。
- 人在这个环境里工作，理解目标，判断局势，使用工具，产出结果。
- 工作可以中断、继续、转交、复盘、归档。
- 管理系统负责记录和协调，但不替人思考，不压制人的判断。

对应到本项目：

```text
Task System        = 工作管理系统
TaskRun            = 一项持久工作记录
Task Environment   = 任务工作环境
Task Memory Space  = 任务专属记忆与档案空间
Task Context       = 当前工作所需的上下文包
Agent Runtime      = agent 进入环境后的执行系统
Execution Episode  = agent 在任务环境中的一次工作片段
Work Product       = agent 的工作产物
```

第 14 号文档里“agent 执行像函数”的说法应降级为局部类比：

```text
单次 Execution Episode 可以像函数调用一样被追踪。
但 Task 本身不是函数，而是持久工作环境。
```

## 2. 正确目标

目标不是把任务做成固定函数接口，而是建立一个能长期支撑 agent 工作的任务环境底座：

```text
用户或图任务提出工作目标
-> 系统创建持久任务环境
-> 系统提供上下文、资源、工具、记忆、状态和验收边界
-> agent 进入环境工作
-> agent 产出 work product
-> 系统记录、索引、审计、恢复和继续
```

这个底座必须允许：

- agent 随时中断；
- 后续 agent 或同一 agent 继续；
- 任务拥有独立存储；
- 任务拥有独立记忆；
- 任务拥有任务级上下文索引；
- 任务拥有状态、检查点、产物、决策记录；
- 系统可以做外部强管理；
- agent 的语义判断和行动权不被系统替代。

### 2.1 普通 turn 与任务的硬分界

必须先敲定：

```text
普通 turn = 当前交互节拍
任务 = 持久工作环境
```

二者不是按“难不难”“步骤多不多”“是否用了工具”区分。

普通 turn 也可以很复杂，也可以读文件、调用工具、修改代码、验证结果。只要它仍然服务于当前用户输入，并且可以在当前交互节拍内完成、解释或收口，它就仍是普通 turn。

任务的意义在于建立一个独立工作环境。它不是更复杂的 turn，而是有自己的身份、生命周期、存储、记忆、产物、检查点、恢复和验收边界。

| 维度 | 普通 turn | 任务 |
| --- | --- | --- |
| 核心身份 | `turn_id` / `turn_run_id` | `task_run_id` / `task_environment_id` |
| 本质 | 当前用户输入的一次交互节拍 | 可持续推进的一项工作 |
| 生命周期 | 随本轮请求开始，随本轮回复或中断收口 | created / active / paused / waiting / completed / failed / archived |
| 上下文 | 会话历史、当前用户输入、动态尾、必要工具观察 | TaskContextPackage、任务记忆、任务文件、任务产物、检查点 |
| 存储 | 主要进入 session / turn memory / runtime event | 独立 task storage / task memory / artifact scope / task timeline |
| agent 角色 | 回应当前用户请求的 agent | 进入任务环境工作的 agent |
| 输出 | 用户可见回复、工具观察、当前 turn 的提交 | WorkProduct、任务状态更新、continuation hint、验收声明 |
| 恢复 | 恢复中断 turn 的交互状态 | 恢复一项工作的目标、进度、证据、产物和下一步 |
| 系统管理 | 控制本轮动作、权限、工具、输出提交 | 管理任务环境、资源、记忆、检查点、监控、交接和验收 |
| 结束条件 | 本轮可以给出回答、问题、阻塞或完成说明 | 工作目标达成、任务被暂停/取消/归档，或等待外部输入 |

### 2.2 什么时候必须进入任务

只有满足下面任一条件，任务才有架构意义：

1. 工作需要跨 turn 保留独立目标、范围、计划或验收标准。
2. 工作需要中断后继续，而继续时不能依赖完整旧对话回放。
3. 工作需要独立存储产物、证据、决策记录或检查点。
4. 工作需要独立任务记忆，避免把稳定事实反复塞进普通上下文。
5. 工作会产生可被后续节点、后续任务或维护系统消费的 WorkProduct。
6. 工作需要外部强管理：暂停、恢复、监控、审批、交接、归档。
7. 图任务节点需要一个可恢复、可审计、可维护的执行环境。
8. 多个 agent 或多次 episode 要围绕同一目标接力工作。

这些条件的共同点是：

```text
任务需要独立工作环境。
```

### 2.3 什么不应该进入任务

以下情况不应自动创建任务：

- 只是问题比较难；
- 只是回答比较长；
- 只是需要使用工具；
- 只是需要读几个文件；
- 只是有多个步骤，但当前 turn 可以完成；
- 只是 agent 想记录一个临时 todo；
- 只是用户让 agent “继续想想”，但没有独立工作目标；
- 只是系统为了方便调度而想把普通交互包装成任务。

如果当前 turn 能完成，就应该在当前 turn 完成。

如果当前 turn 无法完成，但缺少任务目标、范围、下一步、验收或持久化理由，agent 应该 `ask_user`，而不是让系统猜一个任务。

### 2.4 任务启动裁决

任务启动必须满足两个条件：

```text
agent 明确判断需要持久工作环境
系统能够建立足够清晰的任务边界
```

agent 负责判断：

- 当前工作是否需要独立环境；
- 任务目标是什么；
- 工作范围是什么；
- 最小下一步是什么；
- 什么算完成；
- 哪些信息不足，需要问用户。

系统负责承接：

- 分配 `task_run_id`；
- 创建 `TaskWorkEnvironment`；
- 建立存储、记忆、artifact、checkpoint 和 monitor scope；
- 把任务环境投影给后续 agent；
- 校验契约字段是否足够，不替 agent 补猜。

禁止：

- 系统根据关键词自动把普通 turn 升级成任务；
- 系统用 `open_work` 兜底不完整任务；
- 系统把复杂工具调用伪装成任务；
- 系统把任务环境当作压制 agent 行动的权限牢笼。

## 3. 当前源码审查

### 3.1 已有单 agent 主脊柱

当前主执行脊柱仍然是：

```text
backend/harness/entrypoint/runtime_facade.py
  HarnessRuntimeFacade
  _run_single_agent_turn()

backend/harness/runtime/single_agent_host.py
  SingleAgentRuntimeHost

backend/harness/runtime/services.py
  AgentRuntimeServices

backend/harness/loop/single_agent_turn.py
  run_single_agent_turn()

backend/harness/runtime/compiler.py
  compile_single_agent_turn_packet()
  compile_task_execution_packet()

backend/harness/runtime/output_commit_authority.py
  OutputCommitAuthority
```

已有权威链：

```text
request facts
-> current work boundary
-> RuntimeCompiler packet
-> model action protocol
-> admission
-> action permit
-> tool control plane
-> output commit authority
-> TurnMemory / RuntimeEventLog / monitor projection
```

这个链路负责 agent 的实际执行，不应被任务系统重造。

### 3.2 当前任务系统断裂点

当前存在三类混在一起的路径：

```text
普通 turn
-> run_single_agent_turn()

旧 TaskRun executor
-> harness.loop.task_executor.execute_task_run()
-> 独立 task executor loop

图节点执行
-> GraphNodeWorkOrderExecutor
-> execute_graph_agent_work_order_callback
-> _create_graph_node_task_run()
-> task_executor.execute_task_run()
```

问题不是“缺少函数接口”，而是任务工作环境没有成为清晰底座：

- `TaskRun` 更像执行器记录，还没有稳定表达为持久工作环境。
- 任务记忆、任务存储、任务上下文、任务状态、任务产物、任务恢复之间没有形成统一工作空间。
- `task_executor.execute_task_run()` 容易变成第二套模型执行权威。
- 图节点通过创建 `TaskRun` 再进入旧 executor，说明图节点需要的是任务环境承载，而不是专用执行分支。
- `request_task_run` 当前被切断为只记录控制信号，说明旧生命周期不适合直接接回。

## 4. 成熟架构参考

本设计只借成熟系统的不变量。

LangGraph 可借鉴：

- 图状态和 checkpoint 分离。
- checkpoint 服务恢复和 time travel。
- store 可承载跨 thread 的长期数据。
- 节点执行返回结果，图运行器负责状态推进。

参考：

- https://docs.langchain.com/oss/python/langgraph/persistence

Temporal 可借鉴：

- Workflow Definition 和 Workflow Execution 分离。
- Event History 是执行发生事实。
- Activity 结果进入历史，恢复时不能重做副作用。

参考：

- https://docs.temporal.io/workflows

落到本项目：

- 任务环境是持久工作空间。
- agent 执行是进入工作空间的一次 episode。
- event log / checkpoint / memory / artifact store 共同支撑恢复。
- 系统管理工作环境，不替代 agent 判断。

## 5. 目标架构

### 5.1 三层结构

```text
Task Management Layer
  管理任务身份、目标、契约、生命周期、权限、验收、恢复、监控。

Task Work Environment Layer
  管理任务上下文、任务记忆、任务文件、任务产物、任务状态、检查点、工作日志。

Agent Execution Layer
  agent 进入任务环境后进行语义判断、工具行动和 work product 产出。
```

三层关系：

```text
TaskRun
-> TaskWorkEnvironment
-> AgentExecutionEpisode
-> WorkProduct
-> TaskState / TaskMemory / TaskArtifacts / TaskTimeline
```

### 5.2 核心模型

建议新增或重塑以下概念。

```text
TaskWorkEnvironment
  environment_id
  task_run_id
  owner_session_id
  work_scope
  storage_scope
  memory_scope
  artifact_scope
  tool_scope
  permission_scope
  context_policy
  checkpoint_policy
  acceptance_policy
  authority
```

职责：

- 定义任务工作环境的边界；
- 说明任务能看什么、存什么、改什么、继续什么；
- 不执行模型；
- 不替 agent 判断下一步。

```text
TaskContextPackage
  package_id
  task_run_id
  stable_context_refs
  current_state_refs
  memory_refs
  artifact_refs
  file_refs
  graph_packet_refs
  user_steer_refs
  acceptance_refs
```

职责：

- 给 agent 当前 episode 提供上下文；
- 区分稳定内容和当前动态内容；
- 支撑恢复时重新装配；
- 避免把所有历史都反复塞进模型。

```text
TaskMemorySpace
  task_run_id
  long_lived_notes
  decisions
  unresolved_questions
  work_products
  recovery_hints
  semantic_index_refs
```

职责：

- 记录任务级记忆；
- 独立于普通对话记忆；
- 允许 agent 在继续任务时快速恢复工作状态；
- 不把变化很小的事实反复写入动态尾部。

```text
AgentExecutionEpisode
  episode_id
  task_run_id
  agent_id
  agent_profile_id
  invocation_kind
  started_at
  ended_at
  input_context_package_ref
  action_trace_refs
  output_work_product_refs
  terminal_status
  continuation_hint
```

职责：

- 表达 agent 在任务环境中的一次工作片段；
- 可以中断、失败、继续、重放；
- 这里可以类比一次函数调用，但它不是 Task 本身。

```text
WorkProduct
  product_id
  task_run_id
  episode_id
  product_kind
  summary
  structured_payload
  artifact_refs
  memory_candidates
  acceptance_claims
  downstream_refs
```

职责：

- 表达 agent 的实际产物；
- 可以被图任务、用户、后续任务或维护系统消费。

## 6. 系统强管理与 agent 自主性的边界

系统可以强管理：

- 生命周期；
- 存储位置；
- 记忆归档；
- 工具权限；
- 上下文预算；
- 检查点；
- 产物格式；
- 验收标准；
- 中断恢复；
- 审计和监控。

系统不能越权：

- 不替 agent 做语义判断；
- 不根据自然语言暗猜任务模式；
- 不用兜底逻辑覆盖 agent 的合法表达；
- 不把契约写成开发说明；
- 不把 agent 降级成模板填空器；
- 不让图算法替代 agent 的判断。

成熟标准应是：

```text
系统像公司提供工作制度和资源。
agent 像员工或专家，在制度内判断、行动、交付。
```

## 7. 运行流程

### 7.1 创建任务环境

```text
request_task_run / graph node / explicit task config
-> TaskRunResourceAllocator
-> TaskRun
-> TaskWorkEnvironment
-> storage scope / memory scope / artifact scope
-> initial TaskContextPackage
```

### 7.2 agent 进入任务环境

```text
TaskWorkEnvironment
-> build TaskContextPackage
-> assemble RuntimeInvocationPacket
-> run_single_agent_turn compatible execution
-> AgentExecutionEpisode
```

### 7.3 产出与回写

```text
agent output
-> WorkProduct
-> TaskTimeline event
-> TaskMemorySpace update
-> Artifact store
-> TaskState update
-> acceptance / monitor projection
```

### 7.4 中断与继续

```text
interruption
-> episode terminal state
-> continuation_hint
-> checkpoint
-> task context package rebuild
-> next episode continues
```

继续任务时，agent 不应重新读全部历史。系统应提供：

- 当前目标；
- 当前状态；
- 最近 work product；
- 未解决问题；
- 必须看的证据；
- 可复用记忆；
- 文件或图节点指针；
- 下一步建议或恢复提示。

## 8. 与图任务的关系

图任务不是直接调用一个“函数”，而是让某个图节点拥有一个任务工作环境：

```text
GraphNodeWorkOrder
-> TaskWorkEnvironment(caller_kind=graph_node)
-> AgentExecutionEpisode
-> WorkProduct
-> NodeResultEnvelope
-> GraphLoop.accept_node_result()
```

好处：

- 图节点可以中断和恢复；
- 图节点可以拥有自己的任务记忆；
- 图节点产物可以进入项目语义网络；
- 图任务只管理调度和状态推进，不压制 agent 判断；
- 后续维护 agent 可以继续同一个任务环境，而不是重新猜上下文。

## 9. 与记忆架构的关系

任务记忆应独立于普通对话记忆，但可以被引用。

推荐分层：

```text
Session Memory
  用户会话里的偏好、近期对话、当前交互状态。

Task Memory
  某个任务的目标、决策、产物、未解问题、恢复提示。

Project / Domain Memory
  项目级长期语义网络、文件索引、架构知识、跨任务事实。
```

写入原则：

- 稳定事实写入任务记忆，不反复塞进动态尾部；
- 当前变化状态放 TaskContextPackage 的 current state；
- 大文件证据保存为 artifact / evidence ref；
- 语义总结保存为 work product；
- 只有真正影响后续判断的内容进入长期 memory；
- 每次 episode 结束必须写 continuation hint。

## 10. 模块改造方向

### 10.1 新增模块

```text
backend/harness/runtime/task_work_environment_models.py
backend/harness/runtime/task_work_environment_service.py
backend/harness/runtime/task_context_package_builder.py
backend/harness/runtime/task_execution_episode.py
backend/harness/runtime/task_work_product.py
```

### 10.2 改造模块

```text
backend/harness/entrypoint/runtime_facade.py
```

目标：

- `request_task_run` 创建 `TaskWorkEnvironment`；
- `execute_task_run` 进入任务环境运行一个 episode；
- `execute_graph_agent_work_order` 创建或恢复图节点任务环境。

```text
backend/harness/loop/task_executor.py
```

目标：

- 降级为任务生命周期、暂停、恢复、审批、lease、monitor helper；
- 不再作为第二模型执行主循环。

```text
backend/harness/runtime/compiler.py
```

目标：

- 继续负责 packet 编译；
- 输入从散乱 task state 改为 `TaskContextPackage`；
- `invocation_kind` 控制上下文投影，不决定第二套执行系统。

```text
backend/graph_system/work_order_executor.py
```

目标：

- 把图节点执行结果从 `WorkProduct` 后处理为 `NodeResultEnvelope`；
- 不直接依赖旧 TaskRun executor。

## 11. 实施阶段

### Phase 1：模型和只读投影

新增 `TaskWorkEnvironment`、`TaskContextPackage`、`AgentExecutionEpisode`、`WorkProduct` 模型。

完成标准：

- 现有 TaskRun / GraphNodeWorkOrder 能投影成任务环境视图；
- 不改变当前运行行为。

### Phase 2：任务环境创建

恢复 `request_task_run` 的资源分配，但只创建任务环境，不立即执行普通工具。

完成标准：

- `request_task_run` 不再只返回 cut receipt；
- runtime 不猜模式；
- TaskRun 拥有 storage / memory / artifact scope。

### Phase 3：任务上下文包

用 `TaskContextPackage` 替代散乱 task execution context。

完成标准：

- 稳定上下文、当前状态、记忆、产物、文件证据、用户 steer 分层清楚；
- 恢复时能重建最小可用上下文。

### Phase 4：agent episode 执行

让 TaskRun 继续执行时进入任务环境，并复用 single-agent 主脊柱。

完成标准：

- 没有第二模型执行 loop；
- 工具准入仍走 admission / permit / tool control plane；
- 输出仍走统一提交和 work product 记录。

### Phase 5：图节点接入任务环境

GraphNodeWorkOrder 创建或恢复任务环境，再启动 episode。

完成标准：

- 图节点可中断和恢复；
- 图节点有任务记忆和 work product；
- NodeResultEnvelope 从 work product 生成。

### Phase 6：清理旧执行权威

清理：

```text
task_executor.py 中的直接模型循环
TaskExecutorServices 中的模型执行职责
旧 entry_reason / todo-as-primary-mode 投影
execute_graph_agent_work_order_callback 的专用语义
散乱 task state 上下文拼接
```

## 12. 验收不变量

```text
任务是持久工作环境，不是函数形式。
Execution Episode 可以类比函数调用，但不能替代任务本体。
系统强管理任务环境，不强行替 agent 判断。
任务拥有独立存储、记忆、上下文、产物、检查点和监控。
agent 可以中断和继续。
没有第二 single-agent model loop。
没有第二 tool authorization path。
没有第二 assistant output commit path。
没有 task_system 直接执行模型。
没有 graph_system 直接执行模型。
没有把节点契约写成开发说明。
```

## 13. 验证计划

按项目规则，不新增回归测试文件。

静态检查：

```powershell
rg -n "model_runtime|call_model_invoker|compile_task_execution_packet|TaskExecutorServices|execute_graph_agent_work_order_callback|request_task_run" backend/harness backend/graph_system backend/task_system
python -m compileall backend/harness backend/graph_system backend/task_system
```

真实运行验证：

```text
1. 固定后端 127.0.0.1:8003。
2. request_task_run 能创建 TaskRun + TaskWorkEnvironment。
3. TaskRun 能中断后继续，继续时能看到 task memory / context package / continuation hint。
4. GraphNodeWorkOrder 能使用任务环境执行，并生成 WorkProduct 和 NodeResultEnvelope。
5. monitor 能看到任务环境、episode、产物、记忆和检查点。
6. 没有旧 task executor 模型循环被调用。
```

## 14. 总裁决

任务系统的核心不是把 agent 包成函数，而是为 agent 提供一个持久、可管理、可恢复的工作环境。

推荐方向：

```text
TaskRun 是持久工作记录。
TaskWorkEnvironment 是任务工作空间。
TaskContextPackage 是当前工作上下文。
TaskMemorySpace 是任务级记忆。
AgentExecutionEpisode 是 agent 的一次工作片段。
WorkProduct 是 agent 的产出。
Harness Runtime 是 agent 执行底座。
GraphLoop / TaskRun lifecycle 是外部管理系统。
```

这个设计允许系统像公司一样做强管理：保存档案、安排流程、分配资源、做验收和恢复；同时保留 agent 作为智能工作者的判断力和行动力。
