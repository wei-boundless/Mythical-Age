# Backend Harness Semantic Architecture Refactor Plan

日期：2026-06-28  
状态：计划书，待确认后实施。  
本版替换上一版 `backend/agent_runtime` 方案。上一版过度按目标包名推结构，不够贴近当前代码事实；本版以真实调用链、真实权威归属和语义空间原则为准。

## 1. 设计校准

本项目不是因为文件大而需要拆，也不是为了得到一个更漂亮的新目录而重构。真正要解决的是：agent 每回合看到的语义空间、可调用能力、权限反馈、证据记忆和 provider transport 之间的权威边界必须清楚。

用户描述可以有偏差，但以下原则不变：

- agent 是当前行动决策者。
- 系统负责组织语义空间、执行边界、证据、工具和传输，不替 agent 改写目标。
- 权限层可以拒绝越界执行，但必须把拒绝变成 agent 可理解的反馈。
- provider tools sidecar 是传输层，不是 agent 记忆，不应进入 provider-visible history。
- 稳定语义必须稳定，当前边界必须当前有效，不能为了缓存命中删除 agent 必须理解的信息。
- 代码结构按语义权威和插线点整理，不按文件体积机械拆分。

## 2. 当前事实链

从代码实际路径看，现有核心不是空白，也不适合另起一个 `agent_runtime` 包压过去。真实链路如下：

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

关键文件事实：

| 文件 | 当前事实角色 |
|---|---|
| `backend/harness/entrypoint/runtime_facade.py` | 请求入口、session/history 装配、runtime branch 选择、当前工作边界决策入口 |
| `backend/harness/runtime/assembly.py` | profile、environment、operation authorization、tool availability 的 runtime assembly |
| `backend/harness/runtime/packet_assembler.py` | packet context、action surface、tool plan、file evidence scope 的聚合层 |
| `backend/harness/runtime/compiler.py` | agent-visible prompt packet 的主编译器，当前语义投影中心 |
| `backend/harness/runtime/dynamic_context/manager.py` | runtime delta、history、task state、observation、file evidence 的动态上下文聚合 |
| `backend/runtime/context_management/context_pipeline.py` | context capability filter、provider-visible ledger、physical/cache plan |
| `backend/harness/runtime/tool_call_contract.py` | agent-visible tool contract 与 hidden provider transport policy 的分离点 |
| `backend/harness/runtime/tool_plan.py` | 当前回合 RuntimeToolPlan，按 operation authorization 过滤 model-visible/dispatchable tools |
| `backend/capability_system/supply.py` | Tools / MCP / Skills 的能力供给包雏形 |
| `backend/runtime/model_gateway/provider_payload.py` | provider payload segment、sidecar、transport contract、cache boundary |
| `backend/runtime/model_gateway/model_runtime.py` | provider 调用、prompt accounting、provider-visible context success commit |
| `backend/runtime/tool_runtime/tool_control_plane.py` | action permit、capability membership、OperationGate/ToolSupervisor、tool execution、observation |
| `backend/memory_system/runtime_context_provider.py` | runtime memory context 选择和投影 |
| `backend/harness/graph_harness.py` | 当前图运行 facade，聚合 graph runtime、loop、resume、runner、work order execution |
| `backend/harness/graph/*` | 当前可执行图子系统：图配置、状态机、调度、checkpoint、flow packet、work order、图监控 |
| `backend/harness/graph/work_order_contract.py` | GraphNodeWorkOrder 到 harness TaskRunContract 的 agent 执行 adapter |

结论：`harness` 已经是 agent 回合的语义中枢和调度中枢；`runtime/*` 不是新的大脑，而是 context 物理层、model provider 传输层、tool execution 层、shared ledger 层。`capability_system` 和 `memory_system` 是外部事实/能力供给系统，通过 harness 接入。当前 `backend/harness/graph*` 已经形成独立图子系统，应从 harness 中切出为 `backend/graph_system`；`harness` 只保留图节点 agent work order 的执行 adapter。

## 3. 目标权威链

目标不是新建旧壳，而是把现有链路钉成单向权威：

```text
RequestFacts
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
```

每层只允许做自己的事：

| 层 | 允许 | 禁止 |
|---|---|---|
| RequestFacts | 捕获用户输入、附件、session、editor context | 改写用户目标、选择工具 |
| RuntimeAssembly | 汇总 profile、environment、operation authorization、tool inventory | 生成 agent prompt、执行工具 |
| RuntimePacketContext | 形成 action surface、tool plan、evidence scope、packet refs | provider transport/cache 决策 |
| AgentContextContract | 标注每个上下文片段的用途、权威、可见性、生命周期和缓存层级 | 执行工具、决定 provider sidecar |
| ContextPhysicalPlan | stable/append/dynamic tail 排序、ledger replay、cache spine | 改写语义含义 |
| ProviderTransportBinding | messages/tools/params 绑定、transport hash、provider accounting | 进入 agent memory、裁决用户目标 |
| ModelDecision | agent 选择下一步 respond/tool/task/ask/block | 自授权限 |
| ActionAdmission | 校验行动、权限、工具成员关系、审批要求 | 替 agent 换目标 |
| ToolExecution | 执行允许的工具并产出 observation | 静默吞掉失败 |
| ObservationFeedback | 把失败、拒绝、工具结果转成下一轮可消费反馈 | 伪造执行成功 |
| EvidenceCommit | provider success 后封存可 replay 证据 | 修改已封存历史字节 |

## 4. 目标结构

本版不推荐创建 `backend/agent_runtime` 作为新核心。更贴近事实的结构是：

```text
backend/harness/
  entrypoint/              # request/session boundary
  loop/                    # model decision loop, admission, task executor
  runtime/
    assembly.py            # runtime facts assembly authority
    packet_assembler.py    # packet context authority
    compiler.py            # public packet compiler entry
    context_contract/      # new: context fragment use contracts and diagnostics
      __init__.py
      nodes.py
      authority_rules.py
      manifest.py
      diagnostics.py
      inspection_payload.py
    dynamic_context/       # current projectors, gradually aligned to context contract nodes
    tool_call_contract.py  # existing action/tool contract authority
    tool_plan.py           # current-turn tool plan authority
    graph_node_contract.py # target: graph work-order -> agent TaskRunContract adapter

backend/graph_system/      # target: executable graph topology, state machine, loop, checkpoint, work orders
  facade.py                # GraphSystem facade, called by harness/API
  models.py                # ExecutableGraphConfig, GraphRun, GraphLoopState, work orders, results
  runtime.py               # graph run start/envelope assembly
  loop.py                  # graph state progression and checkpointed dispatch
  context_materializer.py  # graph node work-order materialization
  work_order_executor.py   # graph node execution via harness callback port

backend/runtime/
  context_management/      # physical context/cache/provider-visible ledger
  model_gateway/           # provider transport, sidecar, accounting
  tool_runtime/            # tool control plane and concrete tool execution
  memory/                  # runtime memory stores and file evidence stores

backend/capability_system/ # capability registry/supply facts: tools, MCP, skills
backend/memory_system/     # long-term/session memory supply facts
```

新增 `harness.runtime.context_contract` 的目的不是拆大文件，而是把“每段上下文应该如何被 agent / runtime / provider 使用”做成可检查契约：

- 新增一类 agent 需要理解的信息，先声明 `ContextContractNode` 和 `agent_use_contract`。
- 新增一类外部能力，先进入 `capability_system` fact/source，再由 `harness.runtime.tool_plan` 或 capability surface 投影。
- 新增一类当前边界，先进入 runtime boundary/current feedback node，不写进 sealed history。
- 新增一类 provider 参数，进入 `runtime.model_gateway.provider_payload`，不进入 agent-visible prompt。

## 5. 上下文契约模型

建议在 `harness.runtime.context_contract.nodes` 中定义内部 shadow 模型。第一阶段只诊断，不改变 prompt：

```text
ContextContractNode
  node_id
  layer
  kind
  authority
  source_ref
  scope
  ttl
  visibility
  cache_tier
  agent_use_contract
  commit_policy
  replay_policy
  content_ref
  diagnostics

ContextContractManifest
  packet_id
  invocation_kind
  nodes
  edges
  agent_visible_order
  hidden_transport_refs
  physical_context_refs
  diagnostics
```

语义层级采用事实化命名：

| 层 | 名称 | 当前主要来源 |
|---|---|---|
| L1 | Operating Identity | prompt pack、project instructions、profile |
| L2 | Task / Turn Contract | runtime branch、task contract、turn input facts |
| L3 | Capability Surface | `tool_plan`、`tool_call_contract`、`capability_system.supply` |
| L4 | Memory Hints | `memory_system.runtime_context_provider` |
| L5 | Evidence Timeline | provider-visible ledger、file evidence、tool observations |
| L6 | Current Runtime Boundary | runtime delta、operation permission summary、current work receipt |
| L7 | Action Feedback | admission failure、tool denial、tool observation、protocol repair |
| L8 | Provider Transport | provider tools sidecar、tool options、response format、provider params |

硬规则：

- L1-L7 可投影给 agent；L8 不进入 agent-visible history。
- L5 append/sealed；L6/L7 current 或 append feedback；L8 current provider request。
- 没有 `agent_use_contract` 的 agent-visible 语义不能进入 prompt。
- `provider_tools_enabled`、sidecar schema、tool options 只能作为 hidden transport/control，不作为记忆。

## 6. 现有重复权威和整理方向

### 6.1 能力事实源 vs 当前工具计划

当前事实：

- `capability_system.supply` 已能输出 Tool / Skill / MCP refs。
- `harness.runtime.tool_plan` 实际决定本轮 visible/dispatchable tools。
- `harness.runtime.tool_call_contract` 决定 provider tool selection vs action object。
- `runtime.model_gateway.provider_payload` 再验证 provider tools 是否匹配 stable tool index。

目标：

- `capability_system` 只做能力事实源。
- `harness.runtime.tool_plan` 做当前回合能力解析和授权过滤。
- `tool_call_contract` 做 agent-facing action/tool 契约和 hidden transport policy。
- `provider_payload` 只做传输绑定验证和 hash，不重新决定能力语义。

### 6.2 语义投影 vs 物理拼接

当前事实：

- `compiler.py` 生成 message specs。
- `_model_messages_and_segment_plan` 先走 prompt source/materialize，再交给 `context_pipeline`。
- `context_pipeline` 负责 provider-visible ledger 和 physical context plan。

目标：

- `compiler.py` 仍是 public compiler entry。
- `harness.runtime.context_contract` 负责给 message spec 标准化上下文用途契约和诊断。
- `runtime.context_management` 保持物理/cache/ledger authority，不承担 agent 语义裁决。

### 6.3 权限拒绝 vs agent feedback

当前事实：

- `tool_control_plane.invoke` 已产生 denied/needs_approval/error observation。
- `single_agent_turn` 和 `task_executor` 有协议修复、工具次数、closeout 分支。
- 部分失败仍可能表现为运行中断或 final closeout，而不是统一的 agent 可恢复反馈。

目标：

- 所有 admission failure、tool denial、needs_approval、tool limit、protocol repair 统一进入 L7 `ActionFeedback`。
- 如果还在 agent 可继续决策范围内，不直接终止 agent。
- 只有 provider/runtime 不可用、用户取消、无法恢复的系统错误才 terminal。

### 6.4 Memory hint vs Evidence

当前事实：

- memory provider 输出 `memory_system.runtime_memory_context`。
- file evidence 和 provider-visible ledger 在 runtime/context path 中封存。

目标：

- memory 是 hint，不是 evidence。
- 文件事实和工具结果必须来自 L5 evidence timeline。
- memory projection 必须声明“可参考/需验证”，不能替代读取或工具观察。

## 7. Phase Plan

### Phase 0：文档纠偏和冻结错误方向

目标：停止按 `backend/agent_runtime` 新核心推进，同时避免把上层“语义空间”概念直接当代码包名。

动作：

- 本文档成为代码结构重构准绳。
- 不创建 `backend/agent_runtime` 作为核心包。
- 新增上下文用途契约优先落到 `backend/harness/runtime/context_contract`。
- 图结构和图运行系统按 `graph_system_independence_plan_20260628.md` 从 `backend/harness/graph*` 独立为 `backend/graph_system`。

完成标准：

- 设计文档与实际链路一致。
- 后续实施前确认本计划。

### Phase 1：Shadow Context Contract，不改运行行为

目标：先从现有 packet/message_specs 生成上下文契约报告。

影响文件：

- 新增 `backend/harness/runtime/context_contract/nodes.py`
- 新增 `backend/harness/runtime/context_contract/authority_rules.py`
- 新增 `backend/harness/runtime/context_contract/manifest.py`
- 新增 `backend/harness/runtime/context_contract/diagnostics.py`
- 轻接入 `backend/harness/runtime/compiler.py` 或 `_model_messages_and_segment_plan` diagnostics

完成标准：

- 不改变 model messages。
- 不改变 provider payload。
- 每个 packet diagnostics 可看到 L1-L8 分层、authority、visibility、cache tier。

### Phase 2：能力系统标准化接线

目标：统一 `capability_system.supply`、`tool_plan`、`tool_call_contract`、provider sidecar 的权威边界。

影响文件：

- `backend/capability_system/supply.py`
- `backend/harness/runtime/tool_plan.py`
- `backend/harness/runtime/tool_call_contract.py`
- `backend/runtime/model_gateway/provider_payload.py`

完成标准：

- Capability facts 只来自 capability_system。
- Current-turn dispatchability 只来自 RuntimeToolPlan。
- Provider sidecar 只验证同一 stable tool catalog ref，不进入 agent memory。
- sidecar 造成的 hash/cache 变化能被 diagnostics 清楚解释。

### Phase 3：ActionFeedback 统一

目标：把拒绝、审批、工具失败、协议修复、工具次数耗尽统一为 agent 可消费反馈。

影响文件：

- `backend/harness/loop/single_agent_turn.py`
- `backend/harness/loop/task_executor.py`
- `backend/runtime/tool_runtime/tool_control_plane.py`
- `backend/harness/runtime/dynamic_context/tool_result_projector.py`
- `backend/harness/runtime/dynamic_context/observation_projector.py`

完成标准：

- 权限拒绝不直接让 agent 消失。
- tool limit 产生明确反馈：发生了什么、还能做什么、是否需要问用户。
- protocol repair 作为 L7 feedback，而不是散落的特殊 closeout 文案。

### Phase 4：AgentContextContract 接管语义标注

目标：让 message specs 的语义层级、ttl、visibility、cache tier 由统一模型派生。

影响文件：

- `backend/harness/runtime/compiler.py`
- `backend/harness/runtime/dynamic_context/manager.py`
- `backend/harness/runtime/dynamic_context/runtime_delta_projector.py`
- `backend/harness/runtime/incremental_context_frame.py`
- `backend/runtime/context_management/context_segment_policy.py`

完成标准：

- `context_segment_policy` 只负责物理/cache 策略。
- agent-visible 内容都有明确 `agent_use_contract`。
- current runtime boundary 不会 replay 成当前授权。
- 第三轮 cache stable prefix 不退化。

### Phase 5：Inspector 和缓存诊断产品化

目标：前端和 probe 能看到语义空间，而不是只看 prompt 文本。

影响文件：

- `backend/harness/runtime/context_contract/diagnostics.py`
- `backend/runtime/model_gateway/provider_payload.py`
- `backend/runtime/prompt_accounting/*`
- 前端 inspector 页面后续单独计划

完成标准：

- 能定位 stable miss 是语义漂移、transport hash 变化，还是 provider 回读波动。
- 能看到 L8 sidecar 和 L1-L7 prompt 的边界。

### Phase 6：旧逻辑清理

目标：只删除没有权威的旧链路，不为了“目录好看”删除有效事实层。

删除条件：

- 新上下文契约诊断覆盖旧字段作用。
- 没有 active import 依赖旧内部函数。
- provider payload、tool behavior、permission feedback、第三轮 cache 均不退化。

## 8. 禁止事项

- 禁止因为 `compiler.py` 大就机械拆。
- 禁止新建 `backend/agent_runtime` 作为新的大脑套壳。
- 禁止旧文件和新文件同时决定同一语义。
- 禁止把 `runtime.context_management` 升级成 agent 语义裁决层；它是物理/cache/ledger 层。
- 禁止把 provider tools sidecar 放进 stable agent context。
- 禁止把 permission 写成 agent 的上级目标裁决者。
- 禁止用兼容兜底保留旧执行链，除非有明确删除条件。

## 9. 验证策略

不新增回归测试文件。允许验证：

- `python -m compileall` 针对 touched modules。
- `rg` 检查权威重复、旧计划残留、provider sidecar 泄漏。
- 对 prompt/provider 改动运行三轮 cache probe，重点看第三轮。
- 涉及启动链路时按固定端口真实启动前后端。

## 10. 推荐执行决策

推荐确认以下方向后再实施：

```text
1. 不创建 backend/agent_runtime 作为核心包。
2. harness 保持 agent 语义中枢和调度中枢。
3. 新增 backend/harness/runtime/context_contract 作为上下文用途契约和诊断层。
4. 新增 backend/graph_system 作为可执行图结构、图状态机、图调度、checkpoint、work order 的独立系统。
5. harness/runtime/graph_node_contract 只做 GraphNodeWorkOrder 到 agent TaskRunContract 的 adapter。
6. runtime/context_management 保持物理上下文、cache、provider-visible ledger。
7. runtime/model_gateway 保持 provider transport 和 sidecar authority。
8. capability_system 保持能力事实源；harness.runtime.tool_plan 做当前回合能力解析。
9. 第一阶段只做 shadow context-contract diagnostics，不改变 prompt 和 provider payload。
```

这样重塑的是架构权威，不是目录表演。后续真正落地时，每一次新增能力都应该先问：它是 agent 需要理解的语义、当前回合边界、长期事实、可执行能力、provider 传输参数，还是执行后的证据。答案决定插线点。
