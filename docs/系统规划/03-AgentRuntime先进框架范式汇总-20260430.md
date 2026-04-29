# AgentRuntime 先进框架范式汇总

日期：2026-04-30  
定位：本文件用于汇总当前主流 agent / workflow / durable execution 框架的核心范式，帮助洪荒时代 AgentRuntime 决定后续如何构建持久化 RuntimeLoop、ExecutionGraph、OperationGate、CommitGate 与多智能体扩展。

---

## 0. 结论先行

我们现在讨论的不是“选一个最有名的框架”，而是要识别几种成熟系统反复出现的工程范式。

当前最关键的结论：

```text
洪荒时代需要 RuntimeLoop，
但 RuntimeLoop 不能退化成旧 QueryLoop。

RuntimeLoop 应由编排系统拥有，
以 OrchestrationPlan / ExecutionGraph / RuntimeDirective 为执行真相，
通过 checkpoint / trace / result candidate 实现可恢复推进。
```

最值得优先吸收的范式：

```text
1. LangGraph：状态图 + checkpointer + interrupt/resume。
2. Temporal / DBOS：workflow 负责编排，activity/step 承担副作用。
3. OpenAI Agents SDK：Agent + Runner + Tool + Handoff + Guardrail + Session + Trace。
4. Claude Code / OpenClaw：真实产品中的 agentic loop、session transcript、tool_use/tool_result 配对、上下文压缩。
5. Google ADK / Microsoft Agent Framework：确定性 workflow agent / typed executor。
```

当前推荐方向：

```text
主路线：
  基于洪荒时代已有分层，自建任务导向的持久化工作流内核。
  这个内核不等于全自研框架，而是吸收成熟范式后形成自己的 RuntimeWorkflow。

第一阶段主要吸收：
  LangGraph 的状态图 / checkpoint / interrupt。
  Temporal / DBOS 的 workflow-step / activity 副作用边界。
  Claude Code / OpenClaw 的真实 agentic loop 与 session transcript。
  OpenAI Agents SDK 的 agent/tool/guardrail/trace 抽象。

保留选项：
  如果后面要求跨进程、跨重启、长时间运行、强恢复保证，再把 Temporal、DBOS 或 LangGraph 作为外层/底层能力接入。

不推荐：
  直接恢复旧 query loop。
  直接把 OpenAI Agents SDK / AutoGen / CrewAI 当成系统总大脑。
  为了“用框架”而打破现有任务、操作、记忆、编排、写回分层。
```

---

## 1. 我们要解决的真实问题

当前系统已经完成了从旧 `query` 大脑到分层 AgentRuntime 的拆分：

```text
QueryRuntime 不再规划。
QueryRuntime 不再执行旧 planner / direct tool / follow-up。
任务系统、操作系统、编排系统、记忆系统、上下文策略、输出边界已分包。
真实执行暂时只开放 op.model_response。
```

但成熟 AgentRuntime 还缺一层：

```text
持久化 RuntimeLoop。
```

这个 RuntimeLoop 要解决的问题不是“循环调用模型”，而是：

```text
1. 一轮任务可能包含多步模型、工具、worker、agent、记忆、写回。
2. 每一步必须有可恢复状态。
3. 工具和写回副作用不能因为重试而重复。
4. 用户审批、人类介入、中断、恢复必须是正式状态。
5. 多智能体后续扩展不能打破单 agent 主链。
```

成熟完成态应是：

```text
RuntimeSession
  -> TurnRuntime
  -> CandidateSet
  -> OrchestrationPlan
  -> ExecutionGraph
  -> RuntimeDirective
  -> OperationGate
  -> Executor
  -> ResultCandidate
  -> CommitGate
  -> Checkpoint / Trace
  -> resume / continue / stop
```

---

## 2. 范式一：LangGraph 状态图与 checkpoint 范式

官方口径参考：

- LangGraph durable execution 文档：<https://docs.langchain.com/oss/python/langgraph/durable-execution>

核心范式：

```text
StateGraph / node / edge 表示执行拓扑。
checkpointer 保存每一步状态。
thread_id 标识一次可恢复运行。
interrupt 支持 human-in-the-loop。
Command 支持从 interrupt 继续。
非确定性操作和副作用应包进 task / node。
```

官方文档强调：durable execution 的重点是保存关键进度，允许暂停后继续；使用 checkpointer 后，workflow 可以在失败或人类介入后恢复。文档还明确要求：恢复不是从同一行代码继续，而是从合适起点 replay，所以副作用和非确定性操作必须包装，避免重复执行。

适合我们的点：

```text
1. Python 原生，和当前 FastAPI / LangChain 栈接近。
2. StateGraph 很适合承载 ExecutionGraph。
3. thread_id 可以映射 RuntimeSession / TurnRuntime。
4. checkpoint 可以承载 RuntimeDirective 状态。
5. interrupt 可以映射 approval / user_input / memory_confirm。
6. durable modes 可以让我们在性能与可靠性之间分级。
```

风险：

```text
1. LangGraph 仍偏 agent graph，不是强 workflow engine。
2. 恢复需要 deterministic / idempotent 设计，否则副作用仍会重放。
3. 如果我们把太多业务状态塞进 graph state，状态 schema 会膨胀。
4. 它不能自动替我们定义 OperationGate / CommitGate。
```

对洪荒时代的借鉴方式：

```text
借：
  StateGraph / checkpointer / interrupt / resume / task 包装副作用。

不借：
  不让 LangGraph node 直接成为权限决策者。
  不让 graph state 直接写 memory / session。
  不用 LangGraph 替代 TaskSystem / OperationSystem / MemorySystem。
```

建议落地映射：

```text
LangGraph thread_id       -> RuntimeSession.id
LangGraph state           -> RuntimeCheckpointState
LangGraph node            -> ExecutionNodeRunner
LangGraph edge            -> ExecutionGraph edge
LangGraph interrupt       -> RuntimeDirective status = waiting_approval
LangGraph task            -> Executor side-effect boundary
LangGraph checkpointer    -> RuntimeCheckpointStore
```

---

## 3. 范式二：Temporal Workflow / Activity 范式

官方口径参考：

- Temporal Workflow 文档：<https://docs.temporal.io/workflows>
- Temporal Activity 文档：<https://docs.temporal.io/activities>

核心范式：

```text
Workflow 定义步骤序列。
Workflow Execution 是一次具体运行实例。
Activity 是可失败、可重试、可超时的外部动作。
Event History 记录命令和事件。
Workflow 必须满足 deterministic replay。
Activity 承担副作用。
```

Temporal 文档明确说 Workflow 可以运行多年，即使底层基础设施失败也能恢复到失败前状态继续。它还强调 Workflow 通过 Commands 和 Events 推进，并记录到 Event History；Workflow 必须遵守确定性约束。

适合我们的点：

```text
1. 最强的长任务持久化与故障恢复范式。
2. Activity 天然适合 ToolExecutor / WorkerExecutor / BoundedAgentExecutor。
3. Event History 很适合 RuntimeTrace。
4. Signal / Query / Timer 适合用户审批、外部事件、延迟任务。
5. retry / timeout / cancellation 是成熟能力。
```

风险：

```text
1. 运维复杂度高，需要 Temporal 服务和 worker。
2. 需要严格 deterministic workflow 纪律。
3. 对当前小型 FastAPI 项目而言引入成本偏大。
4. 和 LangChain / Python agent 调试体验不如 LangGraph 贴近。
```

对洪荒时代的借鉴方式：

```text
借：
  Workflow / Activity 分离。
  Event History。
  Activity idempotency。
  Signal / Query / Timer。

暂不直接引入：
  Temporal 服务端运行时。
```

建议定位：

```text
Temporal 是未来强持久化外层，不是当前第一阶段内核。
```

如果未来使用：

```text
Temporal Workflow      -> RuntimeSession / TaskRun
Temporal Activity      -> RuntimeDirective executor
Temporal Signal        -> user approval / cancel / continue
Temporal Query         -> runtime status view
Temporal Event History -> RuntimeTrace
```

---

## 4. 范式三：DBOS Workflow / Step 范式

官方口径参考：

- DBOS Workflows：<https://docs.dbos.dev/python/tutorials/workflow-tutorial>
- DBOS Workflows & Steps：<https://docs.dbos.dev/python/reference/decorators>

核心范式：

```text
@DBOS.workflow 标记持久 workflow。
@DBOS.step 标记 workflow 内的步骤。
workflow interrupted 后从最后完成 step 自动恢复。
workflow_id 可作为 idempotency key。
workflow 函数必须 deterministic。
非确定性操作和第三方 API 调用应放进 step。
```

DBOS 文档特别贴近我们的问题：它明确说 workflows 支持 durable execution，可用于 fault-tolerant background tasks、data pipelines、AI agents；workflow 被中断后从最后完成 step 恢复。它还强调 workflow ID 可作为幂等键，适合有发邮件、支付等副作用的场景。

适合我们的点：

```text
1. Python 原生，比 Temporal 运维轻。
2. workflow / step 语义和 RuntimeLoop / RuntimeDirective 很接近。
3. workflow_id 幂等语义适合防止副作用重复。
4. durable sleep / queues / concurrency 对后续后台任务有价值。
5. pydantic 参数验证可以贴近我们现有 dataclass / Pydantic 风格。
```

风险：

```text
1. 对 agent graph / multi-agent 拓扑表达不如 LangGraph 直观。
2. 生态成熟度和团队熟悉度需要进一步验证。
3. 如果只为了 checkpoint，引入 DBOS 可能会改变整个应用运行模型。
```

对洪荒时代的借鉴方式：

```text
借：
  workflow_id 作为 idempotency key。
  step outcome checkpoint。
  durable sleep。
  queue / concurrency 控制。

谨慎：
  不要一开始就把整个 AgentRuntime 改成 DBOS 应用。
```

建议定位：

```text
DBOS 是比 Temporal 轻的 durable execution 候选。
如果 LangGraph checkpoint 不能满足崩溃恢复和后台长任务，再重点评估 DBOS。
```

---

## 5. 范式四：OpenAI Agents SDK 的 Runner / Tool / Guardrail / Session 范式

官方口径参考：

- OpenAI Agents SDK Quickstart：<https://openai.github.io/openai-agents-python/quickstart/>
- OpenAI Agents SDK Runner：<https://openai.github.io/openai-agents-python/ref/run/>

核心范式：

```text
Agent 定义 name / instructions / model / tools / handoffs。
Runner.run 执行 agent。
tools 支持函数工具。
handoffs 支持 agent 间转交。
guardrails 支持输入/输出约束。
sessions 支持会话历史管理。
tracing 支持运行追踪。
```

官方 quickstart 明确提示二次 turn 有三种选择：把 `result.to_input_list()` 传回 Runner、挂 session、或使用 OpenAI server-managed continuation。它也明确区分多智能体中的两种模式：

```text
Handoffs：专家 agent 接管对话。
Agents as tools：orchestrator 保持控制，把专家作为工具调用。
```

适合我们的点：

```text
1. Agent / Tool / Guardrail / Trace 概念清楚。
2. Runner loop 可作为模型与工具互调的参考。
3. Sessions 给我们会话历史管理参考。
4. Agents as tools 很符合我们“主 agent 仍掌控”的多智能体方向。
5. Sandbox agents 对真实文件/环境隔离有参考价值。
```

风险：

```text
1. 它是 agent execution SDK，不是完整 durable workflow engine。
2. handoff 模式容易让控制权去中心化，不符合我们当前主 agent 单链优先原则。
3. 如果直接引入，可能绕过已有 TaskSystem / OperationSystem / CommitGate。
4. session 不是我们所需的全套 RuntimeCheckpoint。
```

对洪荒时代的借鉴方式：

```text
借：
  Agent as tool。
  Guardrail / tripwire。
  session abstraction。
  tracing。
  sandbox agent 能力模型。

不借：
  不让 handoff 自主接管主会话真相。
  不用 Runner 替代 OrchestrationCoordinator。
```

建议定位：

```text
OpenAI Agents SDK 是可借鉴的执行 SDK 和多 agent 模型，
但不适合作为洪荒时代的唯一持久化编排内核。
```

---

## 6. 范式五：Google ADK Workflow Agents 确定性拓扑范式

官方口径参考：

- Google ADK Workflow Agents：<https://adk.dev/agents/workflow-agents/>

核心范式：

```text
Workflow Agent 专门负责控制 sub-agents 的执行流。
Workflow Agent 不用 LLM 动态推理来决定编排。
Sequential / Loop / Parallel 是三种核心执行模式。
LLM Agent 作为被编排的子 agent。
```

官方文档明确区分：LLM Agent 用模型推理，Workflow Agent 用预定义逻辑决定执行顺序。这样执行模式更 deterministic、更 predictable。

适合我们的点：

```text
1. 非 LLM 编排器负责控制流，非常符合 Control Plane 原则。
2. Sequential / Loop / Parallel 可映射 ExecutionGraph pattern。
3. 多智能体可以先作为明确拓扑，而不是自治聊天网络。
4. 单 agent 主链可以视作 Sequential 的最小形态。
```

风险：

```text
1. ADK 生态和我们 Python LangChain 栈不完全一致。
2. 它提供的是 agent framework，不是我们当前全部系统边界。
3. 如果直接照搬 workflow agents，可能弱化我们 TaskSystem 作为多 agent 管理入口的设计。
```

对洪荒时代的借鉴方式：

```text
借：
  single / sequential / parallel / loop 四种固定拓扑。
  WorkflowAgent 不调用 LLM 来决定控制流。

不借：
  不让子 agent 共享完整 InvocationContext。
  不让 topology 扩展提前污染单 agent 主链。
```

建议落地：

```text
ExecutionGraph.pattern:
  single_agent
  sequential
  parallel_fanout
  loop_verify

当前只实现 single_agent。
后续多 agent 从 TaskSystem 入口创建 topology candidate。
```

---

## 7. 范式六：Microsoft Agent Framework Typed Executor 范式

官方口径参考：

- Microsoft Agent Framework Executors：<https://learn.microsoft.com/en-us/agent-framework/workflows/executors>

核心范式：

```text
Executor 是 workflow 中处理消息的基本单元。
Executor 接收 typed messages。
Executor 执行动作后产生 output messages 或 events。
WorkflowContext 负责 send_message / yield_output。
同一个 workflow 中可以连接多个 executor。
```

官方文档把 executor 定义为自主处理单元，能接收 typed messages、执行操作、产生 output messages 或 events。它还强调 stateful executor 如果跨运行共享，必须清理 stale state。

适合我们的点：

```text
1. 很适合定义 ExecutionNode / RuntimeDirective executor。
2. typed message 强化 Typed Contract 优先原则。
3. WorkflowContext 的 send / yield 很接近 RuntimeEventStream。
4. mutable state 清理规则提醒我们 executor 不能残留跨 turn 脏状态。
```

风险：

```text
1. 官方实现偏 .NET / C#，不能直接作为 Python 内核。
2. 它是 workflow executor 模型，不直接解决 durable checkpoint。
```

对洪荒时代的借鉴方式：

```text
借：
  Executor = typed message handler。
  WorkflowContext = RuntimeContext。
  output/event 分离。
  stateful executor reset discipline。

不借：
  不绑定 C# source generator。
```

建议落地：

```text
RuntimeDirective.input_contract -> executor typed input
ExecutorResult                 -> typed output
RuntimeEvent                   -> streamed event
ExecutorState                  -> turn-scoped only
```

---

## 8. 范式七：Claude Code / OpenClaw 产品级 Agentic Loop 范式

本地参考：

```text
D:/AI应用/claude-code-nb-main/query.ts
D:/AI应用/claude-code-nb-main/QueryEngine.ts
D:/AI应用/Claude-Code-Source-Study-main/docs/05-对话循环.md
D:/AI应用/Claude-Code-Source-Study-main/docs/06-上下文管理.md
D:/AI应用/openclaw-main/docs/concepts/agent-loop.md
D:/AI应用/openclaw-main/docs/concepts/session.md
```

核心范式：

```text
AsyncGenerator / streaming loop。
model -> tool_use -> tool_result -> model 的循环。
session transcript 保存对话和工具事件。
上下文压缩按压力梯度触发。
per-session queue 保证同一 session 串行。
权限 gate / tool contract / sandbox 保护副作用。
```

适合我们的点：

```text
1. 真实 coding agent 需要 loop，这是产品事实。
2. tool_use/tool_result API 不变量必须严格维护。
3. 上下文压缩不是摘要功能，而是运行时生存机制。
4. per-session 串行执行是避免 session race 的最低要求。
5. 子 agent 生命周期、权限、记忆范围、递归限制必须提前合同化。
```

风险：

```text
1. query loop 很容易变成总大脑。
2. 进程内 loop 不等于强 durable workflow。
3. transcript replay 不等于 step checkpoint。
4. 多 agent 如果各自 loop，会造成自治 loop 互相缠绕。
```

对洪荒时代的借鉴方式：

```text
借：
  agentic turn loop。
  streaming event。
  tool_use/tool_result 配对。
  context pressure pipeline。
  per-session queue。
  session transcript。

不借：
  不恢复旧 query 中央循环。
  不让 loop 做理解、恢复、决策、写回。
```

建议落地：

```text
QueryLoop -> 不保留为大脑。
RuntimeLoop -> 新建为编排系统拥有的执行心跳。
```

---

## 9. 范式八：AutoGen / event-driven multi-agent 范式

核心范式：

```text
Agent Runtime 管理 agent。
Agent 通过 message / topic / event 互相通信。
多 agent 可以订阅、响应、协作。
```

适合我们的点：

```text
1. 后续事件总线和多 agent 通信可参考。
2. 适合复杂协作、观察者、后台 agent。
```

风险：

```text
1. 过早引入会让系统从有中心控制变成多中心消息网。
2. 当前我们还没有完成单 agent RuntimeLoop，不宜引入 pub/sub 编排。
3. 容易违反 Candidate != Decision。
```

建议定位：

```text
后续多 agent 扩展参考，不作为当前 RuntimeLoop 第一阶段方案。
```

---

## 10. 范式九：CrewAI Flows / Crew 协作范式

核心范式：

```text
Crew 偏角色协作。
Flow 偏结构化流程。
Agent / Task / Process 表达团队协作。
```

适合我们的点：

```text
1. 多角色任务拆解有参考价值。
2. Flow 比完全自治 crew 更适合受控执行。
```

风险：

```text
1. Crew 自治协作与我们当前主 agent 统一编排方向冲突。
2. 任务系统已经承担 TaskContract，不应再引入另一套 Task 语义。
3. 对持久化 checkpoint 不是最核心优势。
```

建议定位：

```text
多 agent 产品形态参考，不作为底层持久化框架。
```

---

## 11. 范式十：Dagster / Prefect 数据工作流范式

官方参考：

- Dagster Concepts：<https://docs.dagster.io/getting-started/concepts>
- Prefect Flows：<https://docs.prefect.io/v3/concepts/flows>

核心范式：

```text
Dagster：asset / op / job / schedule / sensor / resource。
Prefect：flow / task / deployment / state。
```

适合我们的点：

```text
1. artifact lineage、asset、job、schedule 对 Evidence / Worker 有参考价值。
2. 后台批处理、数据处理、周期任务可以参考这些框架。
3. resource/config/schema 设计对 WorkerContract 有帮助。
```

风险：

```text
1. 它们更适合数据管线，不适合作为对话 agent 主循环。
2. human-in-the-loop / tool_use/tool_result / LLM streaming 不是核心优势。
3. 引入后会让 AgentRuntime 重心偏向数据平台。
```

建议定位：

```text
不用于主 RuntimeLoop。
可借鉴 Evidence artifact、Worker batch、定时任务治理。
```

---

## 12. 横向对照矩阵

| 范式 | 最强项 | 持久化能力 | 多 agent | 对我们主链适配 | 当前建议 |
| --- | --- | --- | --- | --- | --- |
| LangGraph | 状态图、checkpoint、interrupt | 中高 | 中高 | 高 | 第一候选 |
| Temporal | 强 durable workflow | 极高 | 中 | 中 | 未来外层 |
| DBOS | Python durable workflow / step | 高 | 中 | 中高 | 第二候选 |
| OpenAI Agents SDK | Agent / tool / guardrail / tracing | 中 | 高 | 中 | 借概念，不做内核 |
| Google ADK | deterministic workflow agents | 中 | 高 | 中 | 借 topology |
| Microsoft Agent Framework | typed executor / workflow context | 中 | 中 | 中 | 借 executor contract |
| Claude Code / OpenClaw | 产品级 agent loop | 中 | 中高 | 高 | 借运行细节 |
| AutoGen | event-driven multi-agent | 中 | 高 | 低中 | 后续参考 |
| CrewAI | 角色协作 / flow | 中 | 高 | 低中 | 产品形态参考 |
| Dagster / Prefect | 数据/任务工作流 | 高 | 低 | 低中 | Worker/Evidence 参考 |

---

## 13. 对洪荒时代的构建判断

### 13.1 我们需要组合范式，而不是照搬单框架

洪荒时代的系统边界已经明确：

```text
任务系统：要做什么。
操作系统：能碰什么。
灵魂系统：以什么身份和提示结构呈现。
记忆系统：带什么上下文，产生什么记忆候选。
编排系统：决定怎么做、按什么顺序做。
执行层：只按 RuntimeDirective 执行。
CommitGate：决定什么能写回。
```

没有任何单一框架能完整替代这些边界。正确做法是：

```text
先冻结洪荒时代自己的 RuntimeWorkflow 合同，
再选择成熟框架或轻量存储作为 graph / checkpoint / interrupt 的可替换承载。

框架可以承载运行机制，
但不能替代 TaskSystem / OperationSystem / MemorySystem / OrchestrationSystem / CommitGate 的系统主权。
```

### 13.2 第一阶段推荐：自有 RuntimeWorkflow 内核

第一阶段目标：

```text
实现单 agent 主链可持续推进。
支持 model -> tool_result -> model 的循环结构。
支持 RuntimeDirective checkpoint。
支持 waiting_approval / blocked / failed / completed 状态。
不开放高风险副作用。
```

推荐设计：

```text
OrchestrationSystem owns RuntimeLoop。
RuntimeLoop consumes ExecutionGraph。
ExecutionGraph node runs RuntimeDirective。
OperationGate checks every directive。
Executor returns ResultCandidate。
CommitGate decides writeback。
CheckpointStore records state after each node.
```

是否直接安装 LangGraph：

```text
不是第一原则。

第一原则是：
  我们自己的 RuntimeWorkflow 合同必须先稳定。

如果采用 LangGraph：
  只把它当 graph/checkpoint/interrupt 的实现承载。
  不把业务决策写进 LangGraph node 内部。
  不让 LangGraph 替代 TaskSystem / OperationSystem / MemorySystem / CommitGate。

如果暂不采用：
  可以先用 SQLite / JSON checkpoint 实现最小 RuntimeCheckpointStore。
  后续再把 store / runner 替换为 LangGraph / DBOS / Temporal。
```

### 13.3 第二阶段保留：DBOS / Temporal 外层 durable workflow

当出现这些需求时，再引入外层 durable workflow：

```text
任务运行跨小时 / 跨天。
进程崩溃必须无损恢复。
工具/worker/外部 API 副作用很多。
需要 durable sleep / timer / queue / signal。
需要后台 agent 与主会话分离运行。
```

选择倾向：

```text
Python-native 轻量路线：DBOS。
强工程平台路线：Temporal。
```

### 13.4 多智能体不能提前抢主线

当前多智能体原则：

```text
可单可多。
先做好单主 agent。
多智能体由 TaskSystem 作为管理总入口。
编排系统只接收 topology candidate，再生成 ExecutionGraph。
记忆系统提供隔离 memory scope。
CommitGate 统一写回。
```

因此：

```text
短期不引入 AutoGen / CrewAI 作为主控。
可以借 OpenAI Agents SDK 的 agents-as-tools 模式。
可以借 Google ADK 的 sequential / parallel / loop topology。
```

---

## 14. 固定设计原则

后续无论选哪一个框架，都必须遵守这些原则：

```text
1. Candidate 不等于 Decision。
2. RuntimeLoop 不做理解，不做授权，不做写回。
3. ExecutionGraph / RuntimeDirective 是执行真相。
4. OperationGate 是副作用前置真相。
5. CommitGate 是写回真相。
6. Memory restore 只能产候选，不能覆盖当前轮目标。
7. Tool / Worker / Agent 都必须是 typed contract。
8. 副作用节点必须有 idempotency_key。
9. checkpoint state 必须有 schema_version。
10. query 只做 adapter，不重新成为系统大脑。
```

---

## 15. 下一步研究与落地建议

### 15.1 先写自有工作流内核设计报告

建议新增：

```text
docs/系统规划/04-AgentRuntime任务导向持久化工作流设计-20260430.md
```

报告重点不是“选一个框架”，而是先冻结我们的核心合同：

```text
TaskRun
WorkflowPlan
ExecutionGraph
RuntimeDirective
RuntimeStepState
RuntimeCheckpoint
RuntimeEvent
ResultArtifact
CommitPlan
ResumePolicy
IdempotencyPolicy
```

再评估成熟范式如何映射：

```text
LangGraph -> graph / checkpoint / interrupt 承载候选
DBOS -> durable workflow / step 承载候选
Temporal -> 强 durable workflow 外层候选
OpenAI Agents SDK -> agent/tool/guardrail/trace 语义参考
Claude Code / OpenClaw -> agentic loop 和 transcript 细节参考
```

### 15.2 再设计 RuntimeLoop 合同

建议新增：

```text
backend/orchestration/runtime_loop.py
backend/orchestration/checkpoint.py
backend/orchestration/runtime_state.py
backend/orchestration/execution_graph_runner.py
```

最小状态：

```text
RuntimeCheckpointState:
  schema_version
  runtime_session_id
  turn_id
  task_contract_ref
  orchestration_plan_ref
  execution_graph_ref
  current_node_id
  directive_statuses
  result_candidate_refs
  commit_gate_status
  blocked_reason
  created_at
  updated_at
```

### 15.3 最小可执行链

先实现：

```text
single_agent_model_loop:
  input message
  model directive
  model response
  output boundary
  commit blocked
  checkpoint
```

再恢复：

```text
read-only tool directive
worker directive
approval interrupt
CommitGate session projection
durable memory candidate writeback
```

---

## 16. 本文件的最终判断

```text
Claude Code 证明了 agent 需要 loop。
LangGraph 证明了 loop 应该图状态化和 checkpoint 化。
Temporal / DBOS 证明了副作用必须从 workflow 中分离出去。
OpenAI Agents SDK 证明了 agent / tool / handoff / guardrail / trace 需要标准化。
Google ADK 证明了多 agent 拓扑应由确定性 workflow 管，而不是由 LLM 随意决定。
Microsoft Agent Framework 证明了 executor 应接收 typed message 并产出 typed output/event。

洪荒时代应该综合这些范式，但不被任何单一框架接管：

用自己的 TaskSystem 定义任务；
用自己的 OrchestrationSystem 拥有 RuntimeWorkflow；
用自己的 ExecutionGraph 表达拓扑；
用自己的 RuntimeDirective 表达执行命令；
用自己的 OperationGate 保护副作用；
用自己的 CommitGate 保护写回；
用 checkpoint/trace 保证可恢复；
再按阶段吸收 LangGraph / DBOS / Temporal 等成熟能力。
```
