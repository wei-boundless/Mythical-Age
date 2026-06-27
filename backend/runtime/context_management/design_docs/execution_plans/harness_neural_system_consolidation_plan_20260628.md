# Harness Neural System Consolidation Plan

日期：2026-06-28  
状态：架构审查与实施方案，待确认后实施。  
范围：把 agent 神经控制体系收束到 `backend/harness`，把可执行图结构独立到 `backend/graph_system`，并明确 `runtime/*`、`task_system`、`capability_system`、`memory_system` 的连接边界。

## 1. 结论先行

本项目当前不缺一个新的“大脑目录”，缺的是清晰的权威分工。正确方案是：

```text
backend/harness       agent 神经控制系统
backend/graph_system  独立图执行系统
backend/task_system   任务/图/合同的作者系统和编译系统
backend/runtime       provider、tool、context、storage、observability 等基础设施
backend/capability_system  Tools / MCP / Skills 能力事实源
backend/memory_system      长期记忆、工作记忆和 memory hint 事实源
```

`harness` 不应吞掉整个后端。它只收束 agent 决策所需的神经控制链：请求事实、当前任务边界、上下文契约、能力面、工具契约、权限反馈、执行循环、证据提交和运行监控。

`graph_system` 不应继续挂在 `harness.graph` 下。它是图拓扑和图运行系统：配置快照、节点/边协议、状态机、调度、checkpoint、resume、flow packet、work order、graph monitor 都应该归它所有。

## 2. 成熟架构参照

本方案只借鉴成熟系统的不变量，不复制外部框架目录。

- Anthropic 将 workflows 和 agents 区分开：workflow 是预定义代码路径，agent 是模型动态决定工具和流程；同时建议保持简单、可组合、透明，并让 agent 从环境反馈中继续推进。参考：[Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)。
- OpenAI Agents SDK 的核心原语是 agents、tools / handoffs、guardrails、sessions、tracing，并把 agent loop、tool invocation、结果回传和持续运行视为 runtime 职责。参考：[OpenAI Agents SDK](https://openai.github.io/openai-agents-python/)。
- LangGraph 将 thread-scoped checkpoint 与 cross-thread store 区分开，说明图状态恢复和长期记忆不是同一层。参考：[LangGraph persistence](https://langchain-ai.github.io/langgraph/concepts/persistence/)。
- MCP 将 server features 分成 resources、prompts、tools，说明上下文来源、工作流模板和可执行动作必须分层。参考：[MCP specification](https://modelcontextprotocol.io/specification/2025-06-18)。

落到本项目的原则：

- agent loop、tool invocation、feedback 和 session/run tracing 属于 harness 神经控制。
- 图拓扑、图 checkpoint、图调度属于 graph_system，不属于 agent prompt/runtime compiler。
- Tools / MCP / Skills 是 capability facts，不能直接混进 provider transport 或 prompt 文本。
- Provider sidecar 是隐藏传输绑定，不是 agent memory，也不是 stable prompt。

## 3. 当前项目审查

### 3.1 真实主链

当前 agent runtime 主链已经存在，不能另建 `backend/agent_runtime` 覆盖它：

```text
harness.entrypoint.runtime_facade.astream
-> harness.runtime.assembly.assemble_runtime
-> harness.runtime.packet_assembler.build_*_packet_context
-> harness.runtime.compiler.compile_*_packet
-> harness.runtime.dynamic_context.DynamicContextManager
-> runtime.context_management.build_context_pipeline
-> runtime.model_gateway.ModelRuntime.*messages*_with_tools
-> harness.loop.single_agent_turn / task_executor
-> harness.loop.admission + action_permit
-> runtime.tool_runtime.RuntimeToolControlPlane.invoke
-> tool observation / evidence / provider-visible ledger commit
```

这说明 `harness` 已经是 agent runtime 的真实控制入口；需要做的是整理权威和边界，而不是新建一套并行 runtime。

### 3.2 图系统扩散事实

`backend/harness/graph*` 当前已经形成完整图子系统：

| 当前文件 | 当前事实 |
|---|---|
| `backend/harness/graph_harness.py` | 图运行 facade，聚合 runtime、loop、resume、runner、work order executor、background supervisor |
| `backend/harness/graph/models.py` | GraphHarnessConfig、GraphRun、GraphLoopState、GraphNodeWorkOrder、NodeResultEnvelope |
| `backend/harness/graph/runtime.py` | 创建 graph run、root task run、runtime envelope |
| `backend/harness/graph/loop.py` | 图状态推进、ready dispatch、accept result、checkpoint |
| `backend/harness/graph/state_machine.py` | 图状态分类和 readiness |
| `backend/harness/graph/context_materializer.py` | 图节点 work order / execution slot materialization |
| `backend/harness/graph/work_order_executor.py` | 通过 harness callback 执行 agent 节点并生成 NodeResultEnvelope |
| `backend/harness/graph/work_order_contract.py` | GraphNodeWorkOrder -> harness TaskRunContract adapter |

`rg` 审查显示 `harness.graph` / `GraphHarness` / `graph_harness_config_id` 已经扩散到：

- `backend/api/orchestration.py`
- `backend/api/task_system.py`
- `backend/task_system/compiler/*`
- `backend/task_system/repositories/graph_harness_config_repository.py`
- `backend/task_system/graph_instances/*`
- `backend/health_system/*`
- `backend/harness/runtime/run_monitor/*`
- `backend/sessions/__init__.py`
- 多个历史 regression 文件

结论：图系统独立不能只移动目录，必须做 import cutover、authority cutover、字段 cutover 和 API/front-end 协议 cutover。

### 3.3 现有正确基础

| 模块 | 应保留的权威 |
|---|---|
| `harness.runtime.assembly` | runtime facts assembly |
| `harness.runtime.packet_assembler` | RuntimePacketContext / action surface / evidence scope |
| `harness.runtime.compiler` | agent-visible packet compiler public entry |
| `harness.runtime.tool_plan` | current-turn model-visible / dispatchable tool plan |
| `harness.runtime.tool_call_contract` | agent-visible action/tool contract + hidden transport policy |
| `runtime.context_management.context_pipeline` | physical context plan、cache、provider-visible ledger |
| `runtime.model_gateway.provider_payload` | provider transport manifest、sidecar、cache boundary |
| `runtime.tool_runtime.tool_control_plane` | action permit、tool execution、observation |
| `capability_system.supply` | Tool / MCP / Skill capability facts |
| `memory_system.runtime_context_provider` | memory hints selection and projection |

### 3.4 当前结构风险

| 风险 | 证据 | 处理方向 |
|---|---|---|
| 图系统混在 harness 内 | `backend/harness/graph*` 同时拥有图模型、loop、checkpoint、resume | 独立为 `backend/graph_system` |
| agent prompt 编译器承担过多投影细节 | `compiler.py` 内同时有 runtime boundary、graph node projection、provider protocol、memory、tool catalog 等投影函数 | 不拆大文件优先，先加 context_contract 诊断，再逐步收口投影权威 |
| capability facts 和当前工具面混层 | `capability_system.supply` 与 `harness.runtime.tool_plan` 都涉及能力可见性 | capability_system 只做事实源，harness.runtime.tool_plan 做当前回合解析 |
| provider sidecar 容易污染 cache 语义 | `provider_payload.py` 独立计算 tools/options/params segment | 保持 L8 hidden transport，禁止进入 agent-visible / sealed history |
| 权限拒绝和可恢复反馈不完全统一 | `tool_control_plane.invoke`、`single_agent_turn`、`task_executor` 均有失败/修复分支 | 统一为 ActionFeedback |
| 旧命名继续扩散 | `GraphHarnessConfig`、`graph_harness_config_id`、`harness.graph_*` authority | graph_system cutover 时统一更名 |

### 3.5 Harness 外神经散点

除 `backend/harness/graph*` 之外，当前还有一批散落在 `harness` 外、但实际在做 agent 神经控制的文件。它们不应该长期留在 `runtime/*` 或 `orchestration/*` 根下，因为这些名字会让后续维护者误以为它们是通用基础设施。

| 当前位置 | 当前事实角色 | 目标归属 | 处理决策 |
|---|---|---|---|
| `backend/runtime/output_boundary/*` | 最终输出裁决、协议泄漏检测、canonical answer 决策 | `backend/harness/runtime/output_boundary/` | 收束进 harness；这是 agent 输出门，不是底层 runtime |
| `backend/runtime/outcome/*` | 基于 evidence / verification / obligation 生成 RunOutcome、resume 建议 | `backend/harness/runtime/outcome/` | 收束进 harness；它决定 agent run 的交付状态 |
| `backend/runtime/contracts/obligation_validation.py` | 校验 required reads/writes/verification/subagent lifecycle/protocol leak | `backend/harness/runtime/obligations.py` 或 `backend/harness/runtime/outcome/obligation_validation.py` | 收束进 harness；这是交付义务裁决 |
| `backend/runtime/contracts/continuation_inputs.py`、`continuation_policy.py` | continuation / stage contract / auto-continue policy | `backend/harness/continuation/` 或 graph_system 编译侧 | 拆分：graph stage contract 归 graph_system/task_system，agent continuation policy 归 harness |
| `backend/runtime/tooling/capability_table.py`、`capability_table_builder.py` | 当前工具能力表、可见/可调度能力、过滤原因 | `backend/harness/runtime/capability_surface/` 或 `backend/harness/runtime/tool_capability.py` | 收束进 harness；它是 current-turn action surface |
| `backend/runtime/tooling/supervisor.py` | 工具运行监督/调度相关能力 | 先审计后决定，可能并入 `harness/runtime/tool_scheduling.py` 或保留在 `runtime/tool_runtime` | 不能盲搬，需看它是否执行工具还是只决定工具面 |
| `backend/orchestration/commit_gate.py` | user/session/task/result commit gate，当前由 runtime facade import | `backend/harness/runtime/commit_gate.py` 或并入 `output_commit_authority.py` | 收束进 harness；它是输出/写入提交权威的一部分 |
| `backend/orchestration/candidates.py`、`contracts.py`、`execution_graph.py`、`kernel.py`、`execution_scheduler.py` | 旧 orchestration kernel / candidate / unit graph / scheduler | 按 active usage 审计：可用部分迁入 harness 或 graph_system，无权威部分删除 | 不保留旧 orchestration 壳 |
| `backend/orchestration/unit_registry.py` | base unit catalog，目前 runtime facade 仍导入 | `harness/runtime/unit_catalog.py` 或删除后由 capability/task contract 替代 | 需确认是否仍是 active 主链 |
| `backend/orchestration/runtime_directive.py`、`monitor.py`、`resource_runtime_view.py`、`resource_inventory.py` | runtime directive / monitor / resource view | 按语义拆到 harness run_monitor、runtime resource infra 或 graph_system | 不整体搬，逐个归权威 |
| `backend/runtime/output_stream/public_contract.py` | assistant public feedback / runtime commit event family | `backend/harness/loop/public_output_contract.py` 或 `harness/runtime/run_monitor` | 如果只定义 agent 对外事件合同，应收束进 harness；如果是 SSE 基础协议则保留 runtime |

明确不迁入 harness 的外部系统：

| 目录 | 不迁原因 |
|---|---|
| `backend/permissions/*` | 权限基础设施和 operation gate 是边界执行器；harness 调用它，但不吞掉它 |
| `backend/agent_system/*` | agent registry / profile / identity 是 agent fact source；harness 读取它，不把 registry 混入 runtime loop |
| `backend/capability_system/*` | Tools / MCP / Skills 是能力事实源；current-turn 解析进 harness，事实源不搬 |
| `backend/memory_system/*` | 长期记忆、工作记忆、memory hint 是事实源；harness 只消费投影 |
| `backend/runtime/model_gateway/*` | provider transport / sidecar / accounting 属于 provider 层 |
| `backend/runtime/context_management/*` | physical context/cache/provider-visible ledger 属于上下文物理层 |
| `backend/runtime/tool_runtime/*` | tool execution control plane 和 concrete execution 属于工具执行层 |

## 4. 目标权威链

### 4.1 Agent 神经控制链

```text
RequestFacts
-> CurrentWorkBoundary
-> RuntimeAssembly
-> RuntimePacketContext
-> AgentContextContract
-> ContextPhysicalPlan
-> ProviderTransportBinding
-> ModelDecision
-> ActionAdmission
-> ToolExecution
-> ObservationFeedback
-> EvidenceCommit
-> RunMonitorProjection
```

每层只做自己的事：

| 层 | 允许 | 禁止 |
|---|---|---|
| RequestFacts | 捕获输入、附件、session、editor context | 改写用户目标 |
| CurrentWorkBoundary | 判定当前 turn 是否接续/控制已有工作 | 生成 prompt 或执行工具 |
| RuntimeAssembly | 汇总 profile、environment、operation authorization、capability facts | 编译 model messages |
| RuntimePacketContext | 形成 action surface、tool plan、evidence scope、packet refs | 决定 provider sidecar |
| AgentContextContract | 标注上下文片段用途、authority、visibility、ttl、cache tier | 改写语义内容 |
| ContextPhysicalPlan | stable / append / dynamic tail 的物理排序和 cache spine | 决定 agent 行动 |
| ProviderTransportBinding | messages/tools/params 绑定、transport hash、provider accounting | 进入 agent memory |
| ModelDecision | agent 选择 respond/tool/task/ask/block | 自授权限 |
| ActionAdmission | 校验工具、权限、边界、审批 | 替 agent 换目标 |
| ToolExecution | 执行已允许动作并产出 observation | 静默吞失败 |
| ObservationFeedback | 把拒绝/失败/观察转成 agent 可恢复反馈 | 伪造成功 |
| EvidenceCommit | provider success 后封存可 replay 证据 | 改写已封存字节 |

### 4.2 图系统链

```text
TaskGraphDefinition
-> GraphConfigCompiler
-> ExecutableGraphConfig
-> GraphSystem.start_run
-> GraphRunEnvelope
-> GraphLoopState
-> GraphNodeWorkOrder
-> HarnessGraphNodeAdapter
-> Agent TaskRun
-> NodeResultEnvelope
-> GraphTransitionProcessor
-> GraphCheckpoint
-> GraphRunMonitor
```

图系统只负责图，不负责 agent prompt / tool / permission 的语义裁决。harness 只通过 adapter 执行 graph node agent work order，不重新计算图 edge state。

## 5. Harness 神经系统收束分集

目标不是把所有文件搬进一个巨型目录，而是把 `harness` 内部按权威分集，形成稳定插线点。

### 5.1 入口与当前工作边界

保留：

```text
backend/harness/entrypoint/
backend/harness/current_work_receipt.py
backend/harness/continuation/
backend/harness/runtime/request_facts.py
backend/harness/runtime/active_turn.py
```

职责：

- 捕获 request facts。
- 判定当前 turn 和已有 task / active work / recovery 的关系。
- 只产生边界 receipt，不直接生成 agent prompt。

### 5.2 Runtime assembly 与 packet

保留：

```text
backend/harness/runtime/assembly.py
backend/harness/runtime/packet_assembler.py
backend/harness/runtime/packet_context.py
backend/harness/runtime/invocation_packet.py
backend/harness/runtime/dynamic_context/
```

职责：

- 汇总 profile、environment、authorization、capability supply、memory hints、file evidence scope。
- 生成 RuntimePacketContext。
- 不直接决定 provider transport。

### 5.3 Context contract 与 prompt projection

新增：

```text
backend/harness/runtime/context_contract/
  __init__.py
  nodes.py
  authority_rules.py
  manifest.py
  diagnostics.py
  inspection_payload.py
```

职责：

- 第一阶段仅 shadow diagnostics，不改变 prompt、provider payload 或工具行为。
- 标注每个 context fragment 的 authority、visibility、ttl、cache tier、agent_use_contract。
- 检查 stable/volatile 污染、provider transport 泄漏、重复权威。

保留：

```text
backend/harness/runtime/compiler.py
backend/harness/runtime/projection/
backend/harness/runtime/prompt_segment_plan.py
```

原则：

- `compiler.py` 仍是 public compiler entry。
- 不因为文件大强拆。
- 后续只把已经稳定的投影权威逐步移入更清晰的 projection/context_contract 文件。

### 5.4 Capability 与 action contract

保留并收口：

```text
backend/harness/runtime/tool_plan.py
backend/harness/runtime/tool_call_contract.py
backend/harness/runtime/tool_catalog_manifest.py
backend/harness/runtime/action_schema_manifest.py
backend/harness/runtime/operation_projection.py
```

职责：

- `tool_plan` 决定当前回合 visible / dispatchable tools。
- `tool_call_contract` 决定 agent-facing action/tool contract 和 hidden provider transport policy。
- provider sidecar 只由同一 stable capability/tool catalog ref 派生，不进入 prompt history。

### 5.5 Decision loop、admission 与 feedback

保留并统一：

```text
backend/harness/loop/model_action_protocol.py
backend/harness/loop/model_action_runtime.py
backend/harness/loop/single_agent_turn.py
backend/harness/loop/task_executor.py
backend/harness/loop/admission.py
backend/harness/loop/action_permit.py
backend/harness/loop/observations.py
backend/harness/loop/presentation.py
```

目标：

- admission failure、tool denial、needs_approval、tool limit、protocol repair 都成为 ActionFeedback。
- 只在不可恢复系统错误、用户取消、明确 terminal contract 时终止。

### 5.6 Evidence、output commit 与 monitor

保留：

```text
backend/harness/runtime/output_commit_authority.py
backend/harness/runtime/output_boundary/       # target from runtime/output_boundary
backend/harness/runtime/outcome/               # target from runtime/outcome
backend/harness/runtime/commit_gate.py         # target from orchestration/commit_gate.py
backend/harness/runtime/session_timeline.py
backend/harness/runtime/run_monitor/
backend/runtime/context_management/provider_visible_context_ledger.py
backend/runtime/memory/*
```

职责：

- harness 负责 commit request 和 run monitor projection。
- harness 负责最终输出边界、canonical answer、commit gate 和 RunOutcome。
- runtime context/memory 层负责实际 ledger / state / evidence store。
- Memory hint 不能替代 evidence。

### 5.7 Graph node adapter

新增或迁移到：

```text
backend/harness/runtime/graph_node_contract.py
backend/harness/runtime/graph_node_execution.py
```

职责：

- `GraphNodeWorkOrder -> TaskRunContract`。
- 注入 graph_slot、node contract、expected result contract。
- 调用已有 `execute_task_run`。
- 返回 executor_result 给 graph_system。

禁止：

- graph_system import `harness.loop`。
- harness 重新计算 graph readiness 或 edge state。

### 5.8 外部神经文件收束口

新增目标包：

```text
backend/harness/runtime/output_boundary/
backend/harness/runtime/outcome/
backend/harness/runtime/capability_surface/
backend/harness/runtime/obligations.py
backend/harness/runtime/commit_gate.py
```

收束原则：

- 只迁入“决定 agent 如何交付、继续、反馈、展示、使用能力”的文件。
- 不迁入 provider transport、tool concrete execution、permission operation gate、memory store、capability registry。
- 迁入后必须改 authority 字符串，不能继续写 `runtime.output_boundary.*`、`runtime.outcome.*`、`orchestration.runtime_commit_gate` 这种旧权威名。
- 如果某个旧文件同时包含可保留基础设施和神经控制，先拆再迁，不整体搬。

## 6. Graph System 独立方案

### 6.1 目标目录

第一阶段平移为主，不先拆成过多子包：

```text
backend/graph_system/
  __init__.py
  facade.py
  models.py
  language.py
  edge_contracts.py
  flow_edges.py
  flow_packet.py
  scheduler_view.py
  state_machine.py
  readiness_evaluator.py
  transition_processor.py
  runtime.py
  loop.py
  resume.py
  runner.py
  background_supervisor.py
  lifecycle_manager.py
  context_materializer.py
  memory_context.py
  output_policy.py
  runtime_objects.py
  checkpoint_store.py
  langgraph_checkpoint_store.py
  model_overrides.py
  supervisor.py
  work_order_executor.py
```

### 6.2 命名 cutover

| 当前名 | 目标名 |
|---|---|
| `GraphHarness` | `GraphSystem` |
| `GraphHarnessConfig` | `ExecutableGraphConfig` |
| `GraphHarnessConfigRepository` | `ExecutableGraphConfigRepository` |
| `graph_harness_config_id` | `graph_config_id` |
| `graph_harness_configs.json` | `graph_configs.json` |
| `harness.graph_*` authority | `graph_system.*` authority |

决策：对外 API 字段采用 `graph_config_id`。内部模型采用 `ExecutableGraphConfig`，因为它表达“task graph 已编译成可运行配置”。

### 6.3 迁移规则

- 不保留长期 `harness.graph` re-export。
- 如果需要旧数据迁移，写一次性 migration 脚本，不在 runtime 里长期双读。
- 每个阶段结束时 active import 只能指向一个路径。
- 删除旧文件和旧测试保护同一阶段完成；不留旧链路作为兼容兜底。

## 7. 分阶段实施计划

### Phase 0：冻结方案和工作树保护

目标：确认本方案后再动 runtime / graph / tool / prompt 代码。

动作：

- 确认本文档作为总实施蓝图。
- 不触碰当前无关 dirty files，尤其是 frontend 文件。
- 明确 `Self / Past / Present / Future` 只是哲学模型，不作为本轮字段/类名落地。

完成标准：

- 方案确认。
- 没有运行代码改动。

### Phase 1：Graph system 内部包迁移

目标：把 `backend/harness/graph*` 平移到 `backend/graph_system`，行为不变。

文件动作：

- `backend/harness/graph_harness.py` -> `backend/graph_system/facade.py`
- `backend/harness/graph/*.py` -> `backend/graph_system/*.py`
- `GraphHarness` -> `GraphSystem`
- 更新 imports：
  - `backend/api/*`
  - `backend/task_system/*`
  - `backend/health_system/*`
  - `backend/harness/runtime/run_monitor/*`
  - `backend/sessions/__init__.py`

完成标准：

- `rg "from harness\\.graph|harness\\.graph_harness|GraphHarness" backend -g "*.py"` 只剩计划文档或迁移脚本。
- 图 start / dispatch / accept result / resume / monitor 行为不变。
- 删除 `backend/harness/graph/` 和 `backend/harness/graph_harness.py`。

### Phase 2：Graph node adapter 切断

目标：graph core 不再 import harness loop。

文件动作：

- `backend/harness/graph/work_order_contract.py` 逻辑迁入 `backend/harness/runtime/graph_node_contract.py`。
- 若需要执行端口，新增 `backend/harness/runtime/graph_node_execution.py`。
- `backend/graph_system/work_order_executor.py` 通过 callback/port 请求 agent execution。

完成标准：

- `backend/graph_system` 不 import `harness.loop`、`harness.runtime.compiler`、`harness.runtime.tool_plan`。
- harness 可以 import `graph_system` public models / facade。

### Phase 3：Graph authority 与字段 cutover

目标：去掉旧 `harness.graph*` 身份污染。

文件动作：

- `GraphHarnessConfig` -> `ExecutableGraphConfig`
- `graph_harness_config_from_dict` -> `executable_graph_config_from_dict`
- `GraphHarnessConfigRepository` -> `ExecutableGraphConfigRepository`
- `graph_harness_config_id` -> `graph_config_id`
- 存储文件从 `graph_harness_configs.json` 迁到 `graph_configs.json`
- authority 从 `harness.graph_*` 改到 `graph_system.*`

完成标准：

- 新运行对象不再写出 `harness.graph_*` authority。
- 不长期输出新旧两套字段。
- 旧字段只在 migration 或历史数据说明里出现。

### Phase 4：Harness context-contract shadow

目标：把神经系统的上下文权威做成可诊断 manifest，不改 prompt。

文件动作：

- 新增 `backend/harness/runtime/context_contract/*`
- 在 `backend/harness/runtime/compiler.py` 的 diagnostics 中挂 shadow manifest。
- 不改变 `model_messages`、provider payload、tool behavior。

完成标准：

- 每个 packet 可看到 context fragment 的 authority / visibility / ttl / cache tier。
- 能诊断 provider sidecar 是否泄漏、current-only 是否进入 stable、重复语义是否存在。

### Phase 5：Harness 外神经散点收束

目标：把外部散落的 agent 输出、交付、能力面、继续策略和 commit gate 收束到 harness。

文件动作：

- `backend/runtime/output_boundary/*` -> `backend/harness/runtime/output_boundary/*`
- `backend/runtime/outcome/*` -> `backend/harness/runtime/outcome/*`
- `backend/runtime/contracts/obligation_validation.py` -> `backend/harness/runtime/outcome/obligation_validation.py` 或 `backend/harness/runtime/obligations.py`
- `backend/runtime/tooling/capability_table.py`、`capability_table_builder.py` -> `backend/harness/runtime/capability_surface/`
- `backend/orchestration/commit_gate.py` -> `backend/harness/runtime/commit_gate.py` 或合并进 `output_commit_authority.py`
- `backend/runtime/contracts/continuation_*` 按语义拆分到 `harness/continuation`、`graph_system` 或 `task_system/compiler`
- `backend/orchestration/*` 逐个审计：active 神经控制迁入 harness，图拓扑迁入 graph_system，事实/资源基础设施留 runtime 或删除

完成标准：

- `rg "runtime\\.output_boundary|runtime\\.outcome|runtime\\.tooling|orchestration\\.runtime_commit_gate" backend -g "*.py"` 不再命中 active runtime import。
- 新 authority 归 `harness.runtime.*`，旧 authority 只在 migration / historical docs 中出现。
- `permissions`、`agent_system`、`capability_system`、`memory_system` 不被误搬。

### Phase 6：Capability / tool contract 标准化

目标：统一 capability facts、current tool plan、agent action contract、hidden provider transport。

文件动作：

- `capability_system.supply` 保持事实源。
- `harness.runtime.tool_plan` 成为当前回合工具面唯一解析者。
- `harness.runtime.tool_call_contract` 只输出 agent-visible contract 和 hidden transport policy。
- `runtime.model_gateway.provider_payload` 只做 transport binding/hash，不重新解释工具语义。

完成标准：

- Provider tools sidecar 不影响 stable agent context。
- tool catalog ref、tool plan ref、provider payload manifest 可追踪到同一能力源。

### Phase 7：ActionFeedback 统一

目标：权限、工具、协议、预算失败统一变成 agent 可恢复反馈。

文件动作：

- `harness/loop/admission.py`
- `harness/loop/action_permit.py`
- `harness/loop/single_agent_turn.py`
- `harness/loop/task_executor.py`
- `runtime/tool_runtime/tool_control_plane.py`
- `harness/runtime/dynamic_context/tool_result_projector.py`
- `harness/runtime/dynamic_context/observation_projector.py`

完成标准：

- 权限拒绝不直接让 agent 消失。
- 工具次数耗尽生成可理解反馈。
- protocol repair 进入 feedback，不散落在 closeout 文案里。

### Phase 8：清理旧链路和产品化 inspector

目标：删除无权威旧逻辑，提供可解释视图。

文件动作：

- 删除已迁出的 `harness.graph` 旧路径。
- 删除无权威旧字段、旧 repository、旧测试文件。
- 后续单独方案处理 frontend semantic inspector。

完成标准：

- `rg` 找不到 active 旧链路。
- 前后端固定端口真实启动后，graph task、agent task、tool loop、run monitor 可用。

## 8. 文件级执行清单

### 8.1 新增

- `backend/graph_system/__init__.py`
- `backend/graph_system/facade.py`
- `backend/graph_system/*.py`
- `backend/harness/runtime/graph_node_contract.py`
- `backend/harness/runtime/graph_node_execution.py`（如执行端口需要）
- `backend/harness/runtime/context_contract/__init__.py`
- `backend/harness/runtime/context_contract/nodes.py`
- `backend/harness/runtime/context_contract/authority_rules.py`
- `backend/harness/runtime/context_contract/manifest.py`
- `backend/harness/runtime/context_contract/diagnostics.py`
- `backend/harness/runtime/context_contract/inspection_payload.py`
- `backend/harness/runtime/output_boundary/__init__.py`
- `backend/harness/runtime/outcome/__init__.py`
- `backend/harness/runtime/capability_surface/__init__.py`
- `backend/harness/runtime/obligations.py`
- `backend/harness/runtime/commit_gate.py`

### 8.2 移动 / 重命名

- `backend/harness/graph_harness.py`
- `backend/harness/graph/*`
- `backend/task_system/repositories/graph_harness_config_repository.py`
- `backend/task_system/compiler/graph_harness_config_publisher.py`
- `backend/runtime/output_boundary/*`
- `backend/runtime/outcome/*`
- `backend/runtime/tooling/capability_table.py`
- `backend/runtime/tooling/capability_table_builder.py`
- `backend/runtime/contracts/obligation_validation.py`
- `backend/orchestration/commit_gate.py`

### 8.3 更新 imports / 调用点

- `backend/harness/entrypoint/runtime_facade.py`
- `backend/harness/__init__.py`
- `backend/api/orchestration.py`
- `backend/api/task_system.py`
- `backend/api/graph_task_instances.py`
- `backend/task_system/compiler/*`
- `backend/task_system/graphs/*`
- `backend/task_system/graph_instances/*`
- `backend/task_system/engagement/*`
- `backend/health_system/*`
- `backend/harness/runtime/run_monitor/*`
- `backend/runtime/memory/state_index.py`
- `backend/sessions/__init__.py`
- import `runtime.output_boundary` / `runtime.outcome` / `runtime.tooling`
- import `orchestration.commit_gate`

### 8.4 不碰或仅按专门计划处理

- 前端页面：只在 Phase 4 API 字段 cutover 后按固定端口实测，不在本方案第一阶段随手改 UI。
- `runtime.context_management`：保持 physical/cache/ledger 权威，不迁进 harness。
- `runtime.model_gateway`：保持 provider transport 权威，不迁进 harness。
- `capability_system`：保持能力事实源，不迁进 harness。
- `memory_system`：保持记忆事实源，不迁进 harness。
- `permissions`：保持 permission / operation gate 基础设施，不迁进 harness。
- `agent_system`：保持 agent identity/profile registry，不迁进 harness；harness 只消费 profile。

## 9. 验证矩阵

不新增回归测试文件。允许的验证方式：

| 阶段 | 验证 |
|---|---|
| Graph 包迁移 | `python -m compileall backend/graph_system backend/harness backend/task_system backend/api backend/health_system` |
| Import cutover | `rg "from harness\\.graph|harness\\.graph_harness|GraphHarness" backend -g "*.py"` |
| 字段 cutover | `rg "graph_harness_config_id|harness\\.graph_" backend -g "*.py"`，只允许 migration / historical docs |
| 外部神经散点 | `rg "runtime\\.output_boundary|runtime\\.outcome|runtime\\.tooling|orchestration\\.runtime_commit_gate" backend -g "*.py"` |
| Prompt/context shadow | 对 touched modules compileall；不跑 cache probe，除非 prompt/provider payload 变更 |
| Provider payload | 三轮 cache probe，重点看第三轮 stable prefix |
| 运行链路 | 固定端口 `127.0.0.1:8003` 后端、`127.0.0.1:3000` 前端真实启动 |
| Graph runtime | start graph、dispatch ready、accept node result、resume、human gate、monitor |
| Agent runtime | single turn、task execution、tool call、permission denial feedback、final output |

## 10. 删除规则

以下内容不允许以兼容为理由长期保留：

- `backend/harness/graph/`
- `backend/harness/graph_harness.py`
- `GraphHarness*` 类型名
- `graph_harness_config_id` 对外协议字段
- `harness.graph_*` 新写入 authority
- 同时决定工具可见性的旧分支
- 直接 terminal 的可恢复 permission/tool-limit 分支
- `runtime.output_boundary`、`runtime.outcome`、`runtime.tooling.capability_table` 的 active import
- `orchestration.runtime_commit_gate` 的 active authority

允许短暂存在的只有：

- 一次性 migration 脚本。
- 同一阶段内尚未完成 cutover 的临时 import。
- 明确删除条件和验证命令写在 phase checklist 里的过渡文件。

## 11. 最终目标结构

```text
backend/harness/
  entrypoint/
  continuation/
  loop/
  runtime/
    assembly.py
    packet_assembler.py
    compiler.py
    context_contract/
    dynamic_context/
    tool_plan.py
    tool_call_contract.py
    graph_node_contract.py
    run_monitor/

backend/graph_system/
  facade.py
  models.py
  runtime.py
  loop.py
  state_machine.py
  transition_processor.py
  context_materializer.py
  work_order_executor.py
  checkpoint_store.py
  resume.py
  runner.py
  ...

backend/runtime/
  context_management/
  model_gateway/
  tool_runtime/
  memory/
  prompt_accounting/
  shared/

backend/task_system/
  compiler/
  graphs/
  repositories/
  graph_instances/

backend/capability_system/
backend/memory_system/
```

这套结构的核心不是目录名，而是单向权威：

```text
task_system 编译任务和图
graph_system 推进图
harness 执行 agent 决策和反馈
runtime 执行底层 provider/tool/context/storage
capability_system 和 memory_system 提供事实
```

## 12. 推荐执行决策

建议确认后按以下顺序执行：

```text
1. 先做 graph_system 包迁移，减少 harness 内最大混层。
2. 再拆 graph_node adapter，切断 graph core 对 harness loop 的依赖。
3. 再做 graph authority / 字段 cutover。
4. 再做 harness context_contract shadow diagnostics。
5. 再收束 harness 外神经散点：output_boundary、outcome、capability_table、obligation、commit_gate。
6. 再统一 capability/tool contract 和 ActionFeedback。
```

这条路线先清结构，再修语义，再修反馈。它不会用哲学模型替代代码事实，也不会把现有可靠拼接和工具体系随手推翻。
