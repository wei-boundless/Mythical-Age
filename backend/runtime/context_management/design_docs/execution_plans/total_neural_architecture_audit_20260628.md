# Total Neural Architecture Audit

日期：2026-06-28  
状态：总架构审计与实施前方案，待确认后才进行代码重构。  
范围：审查 `backend/harness`、`backend/harness/graph*`、`backend/runtime/*`、`backend/orchestration/*`、`backend/permissions`、`backend/capability_system`、`backend/memory_system`、`backend/agent_system` 中的 agent 神经控制权威、旧神经结构和图系统边界。

## 1. 审计结论

本项目的正确核心不是新建 `backend/agent_runtime`，也不是把所有看起来和 agent 有关的文件都搬进 `harness`。正确框架是：

```text
backend/harness          Agent neural control system
backend/graph_system     Executable graph topology and graph run system
backend/task_system      Task/graph authoring, contracts and compiler
backend/runtime          Provider/tool/context/storage/stream infrastructure
backend/permissions      Boundary and operation policy infrastructure
backend/capability_system  Tools / MCP / Skills fact source
backend/memory_system      Long-term/session/working memory fact source
backend/agent_system       Agent identity/profile/registry fact source
```

`harness` 应成为 agent 的总神经系统：它接收请求事实、组织当前任务边界、装配上下文契约、形成当前能力面、接收模型决策、执行 admission、把工具和权限结果转成 agent 可恢复反馈、提交证据和最终输出。

`graph_system` 必须从 `harness` 中独立出来：图拓扑、图状态机、图调度、checkpoint、resume、flow packet、graph work order 属于图系统，不属于 agent prompt/runtime compiler。`harness` 只保留图节点 work order 到 agent task run 的 adapter。

`runtime/*` 不能成为第二个大脑。它应保留 provider transport、tool execution、physical context/cache、runtime storage、stream/public projection 等基础设施职责。

审计还确认：`backend/harness/runtime/tool_transport_adapter.py` 当前不存在，且不应恢复。当前工具主线应继续钉在：

```text
harness.runtime.tool_plan
-> harness.runtime.tool_call_contract
-> harness.runtime.provider_tool_schema
-> runtime.model_gateway.provider_payload
-> runtime.tool_runtime.provider_tool_call_adapter
-> runtime.tool_runtime.tool_control_plane
```

## 2. 成熟架构不变量

本方案只采用成熟 agent 架构的不变量，不复制外部目录名。

- Anthropic agent 架构经验强调 workflow 与 agent 的差异：workflow 是预设代码路径，agent 是模型根据环境反馈动态选择工具和流程。落到本项目，harness 需要保留模型决策和反馈回路，不能让旧 classifier 或 executor 二次决定目标。参考：https://www.anthropic.com/engineering/building-effective-agents
- OpenAI Agents SDK 的 primitives 是 agents、tools、handoffs、guardrails、sessions、tracing。落到本项目，agent 不是一段 prompt，而是 runtime loop、tool admission、session tracing 和 boundary feedback 的组合。参考：https://openai.github.io/openai-agents-python/
- MCP 把 capabilities 分成 tools、resources、prompts。落到本项目，Tool、MCP、Skill 必须进入统一 capability system，但不能混成同一种 prompt 文本或 provider sidecar。参考：https://modelcontextprotocol.io/specification/2025-11-25
- LangGraph persistence 区分 thread checkpoint 和 store。落到本项目，graph checkpoint、runtime event、memory hint、evidence timeline 必须分层，不能让恢复态覆盖当前 turn truth。参考：https://docs.langchain.com/oss/python/langgraph/persistence

目标权威链：

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
-> ActionPermit
-> ToolExecution
-> ObservationFeedback
-> EvidenceCommit
-> PublicProjection / OutputCommit
```

## 3. 语义模型对代码的约束

`Self / Past / Present / Future` 仍然只作为上层哲学模型和审计模型，不直接硬编码成目录或字段。

工程落地时用八层职责模型：

| 层 | 名称 | 代码权威 |
|---|---|---|
| L1 | Operating Identity | `agent_system` facts + `harness.runtime.compiler` projection |
| L2 | Task / Turn Contract | `harness.entrypoint`、`harness.loop.task_lifecycle`、`task_system` contract facts |
| L3 | Capability Surface | `capability_system` facts + `harness.runtime.tool_plan` current-turn resolution |
| L4 | Memory Hints | `memory_system.runtime_context_provider` |
| L5 | Evidence Timeline | `runtime.context_management.provider_visible_context_ledger`、`runtime.memory/*` |
| L6 | Current Runtime Boundary | `harness.runtime.dynamic_context.runtime_delta_projector`、`harness.entrypoint.current_work_boundary` |
| L7 | Action Feedback | `harness.loop.admission`、`runtime.tool_runtime.tool_control_plane` observations、protocol repair |
| L8 | Provider Transport | `runtime.model_gateway.provider_payload`、provider tools sidecar、request params |

硬规则：

- L1-L7 可投影给 agent；L8 只属于 hidden transport。
- `provider tools sidecar` 不进 stable prompt，不进 provider-visible history，不进 memory。
- 权限拒绝、工具次数耗尽、approval required、协议修复都必须成为 L7 `ActionFeedback`，不能直接让 agent 无反馈停止。
- 记忆是 hint，不是 evidence。
- graph checkpoint 是图运行状态，不是 agent 当前行动授权。

## 4. 当前真实主链

代码审计确认当前主链是：

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

因此 `harness` 已经是 agent runtime 的真实入口和控制中枢。重构目标是整理权威，不是替换主链。

## 5. 总体权威表

| 模块 | 当前职责 | 隐患 | 目标动作 |
|---|---|---|---|
| `backend/harness/entrypoint/*` | API 到 runtime branch、current work boundary、session/history 装配 | `runtime_facade.py` 同时 import graph、orchestration unit catalog、graph work order adapter | 保留为入口；移除 graph core import；删除无用 unit catalog 依赖 |
| `backend/harness/runtime/*` | assembly、packet、compiler、tool plan、tool contract、dynamic context、run monitor | `compiler.py` 投影职责过重；context 片段缺少统一用途契约 | 新增 `context_contract` shadow；逐步让投影有 authority/ttl/cache tier |
| `backend/harness/loop/*` | model action loop、admission、action permit、task executor、presentation | admission repair、tool feedback、protocol repair 语义分散 | 统一 L7 ActionFeedback；保留 agent 决策权 |
| `backend/harness/graph*` | 图运行系统完整实现 | 图拓扑和 agent neural control 混层 | 迁出到 `backend/graph_system` |
| `backend/runtime/context_management/*` | physical context、provider-visible ledger、cache plan | 如果承担 agent 语义裁决会越权 | 保留基础设施；只消费 context contract，不裁决意图 |
| `backend/runtime/model_gateway/*` | provider request/stream/sidecar/accounting | `model_response.py` 引入 commit gate，provider 层参与 commit decision | 保留 provider transport；commit decision 回收给 harness |
| `backend/runtime/tool_runtime/*` | concrete tool execution、tool observation、provider call adapter | 目前反向 import `harness.loop.action_permit`，边界不够纯 | 可接受短期 contract import；后续把 permit schema 变成稳定执行合同 |
| `backend/permissions/*` | permission policy、operation gate、approval context | 若替 agent 决定目标会越权 | 保留边界执行器；拒绝结果必须回流 L7 feedback |
| `backend/capability_system/*` | Tools / MCP / Skills registry、supply、management | 当前回合工具面和事实源容易混层 | 保留事实源；current-turn resolution 属于 harness |
| `backend/memory_system/*` | memory store、memory hint、governance | memory hint 可能被误当证据 | 保留事实源；投影时标注 requires verification |
| `backend/agent_system/*` | profile、identity、worker registry | 仍有 `orchestration.*` authority 字符串 | 保留事实源；后续 authority 改名不能混运行权威 |
| `backend/orchestration/*` | 旧 control kernel、commit gate、runtime directive、catalog、background manager | 混合了 active infra、old neural skeleton、UI catalog 和死文件 | 拆分迁移；无权威旧神经结构删除 |

## 6. 旧神经结构审计矩阵

| 文件/目录 | 证据 | 当前实际角色 | 目标归属 | 决策 |
|---|---|---|---|---|
| `backend/harness/graph_harness.py` | `runtime_facade.py` 创建 `self.graph_harness`，API 大量调用 | 图运行 facade | `backend/graph_system/facade.py` | 迁移并重命名为 `GraphSystem` |
| `backend/harness/graph/*.py` | `rg` 显示 API、task_system、health_system、tests 大量 import | 图模型、loop、checkpoint、state machine、flow packet | `backend/graph_system/*` | 整体迁出，删除旧路径 |
| `backend/harness/graph/work_order_contract.py` | 导入 `harness.loop.task_lifecycle.TaskRunContract` | graph work order 到 agent task contract adapter | `backend/harness/runtime/graph_node_contract.py` | 不进 graph core，留 harness adapter |
| `backend/runtime/output_boundary/boundary.py` | 被 `single_agent_turn`、`presentation`、`model_gateway`、`api/chat` 使用 | 混合公开文本消毒、协议泄漏检测、最终输出裁决 | 拆分 | sanitize/leak detection 留低层输出卫生；canonical final decision 迁入 harness output boundary |
| `backend/runtime/output_boundary/classifier.py` | 输出 channel/persist policy/finalization policy | 最终输出候选裁决 | `backend/harness/runtime/output_boundary/` | 迁入 harness；避免 provider 层直接 commit 裁决 |
| `backend/runtime/output_boundary/rag_finalizer.py` | `evidence/orchestrator.py`、`evidence/output_policy.py` 使用 | RAG 证据包和最终回答提示 | `evidence/*` 或 harness output boundary | 按调用拆：RAG evidence 归 evidence，final answer sanitize 依赖低层 hygiene |
| `backend/runtime/output_boundary/output_models.py` | output_boundary 内部模型 | 输出候选/commit policy 模型 | 拆分 | 公共枚举可留低层；commit policy 模型归 harness |
| `backend/runtime/outcome/*` | 只有自身和 `tests` import；`runtime/shared/__init__.py` 还重复定义 `RunOutcome` | 未接 active 主链的运行结果模型 | 删除或迁入 harness outcome | 重构阶段先选一个 canonical；未接入则删除旧包和 fossil tests |
| `backend/runtime/shared/__init__.py` 的 `RunOutcome` | 与 `runtime/outcome/models.py` 重复 | 重复结果模型 | `harness.runtime.outcome` 或 dedicated shared model | 必须消除重复权威 |
| `backend/runtime/contracts/obligation_validation.py` | 只有 test 直接 import；outcome completion 只消费 dict | 交付义务校验旧实现 | `harness.runtime.outcome.obligation_validation` 或删除 | 若新 outcome 接入则迁入；否则删除 |
| `backend/runtime/contracts/continuation_policy.py` | 定义 `TaskGraphStageContract`、从 graph metadata derive stage contracts | 图/任务阶段合同 | `task_system/compiler` + `graph_system` | 拆分迁移，不进 harness |
| `backend/runtime/contracts/continuation_inputs.py` | 绑定 stage inputs 和 artifact refs | graph continuation input binding | `graph_system` 或 `task_system/compiler` | 迁出 runtime contracts |
| `backend/runtime/tooling/capability_table.py` | `harness.runtime.tool_plan` 生成，`tool_control_plane` 消费 | current-turn capability table contract | `harness.runtime.capability_surface` 或 stable execution contract | 不留 `runtime.tooling` 旧包；先定义稳定位置 |
| `backend/runtime/tooling/capability_table_builder.py` | 旧 assembly policy builder；active import 未见 | 旧工具能力表 builder | 删除或并入 harness tool plan | 若无 active path，删除 |
| `backend/runtime/tooling/supervisor.py` | `tool_control_plane` 使用 | per-call tool supervision / operation gate bridge | `backend/runtime/tool_runtime/supervision.py` | 保留为 tool execution infra，不能搬进 harness 决策层 |
| `backend/orchestration/commit_gate.py` | `harness.output_commit_authority` 和 `runtime.model_gateway.model_response` import | 输出提交门，但混在旧 orchestration | `harness.runtime.commit_gate`，同时移除 model_gateway 直接 commit decision | 迁移，provider 层只报告 blocked response |
| `backend/orchestration/kernel.py` | ControlKernel 总是 blocked；主要给 `/orchestration/dry-run` 和 tests | 旧 control kernel skeleton | 删除或移为 dev preview | 不是 active runtime 权威 |
| `backend/orchestration/candidates.py` | candidate-only envelope，被 kernel/tests 使用 | 旧 candidate scaffold | 删除或移为 preview-only | 不进入 runtime |
| `backend/orchestration/contracts.py` | 旧 `TaskContract` 与 `task_system.contracts.TaskContract` 重名 | 旧合同模型 | 删除或改名 preview contract | 消除与 task_system 的重复命名 |
| `backend/orchestration/execution_graph.py` | 旧 `ExecutionGraph`，commit candidate 被 commit_gate 使用 | commit candidate + old directive graph | 拆分 | `CommitCandidate` 跟 commit gate 迁；ExecutionGraph 删除或进 runtime directive infra |
| `backend/orchestration/runtime_directive.py` | model_gateway、tool_runtime、permissions 真实使用 | executable runtime directive contract | `backend/runtime/shared/runtime_directive.py` | 保留但移出 orchestration |
| `backend/orchestration/execution_scheduler.py` | `memory_system.facade` 使用 `BackgroundTaskManager` | background task infra | `runtime/shared/background_tasks.py` 或 `memory_system/background_tasks.py` | 保留 infra，移出 orchestration |
| `backend/orchestration/resource_runtime_view.py` | `api/capability_system.py` 使用 | permission/capability UI projection | `capability_system/permission_projection.py` 或 `permissions` projection | 保留事实投影，移出 orchestration |
| `backend/orchestration/resource_inventory.py` | API 使用；内容仍写 `graph_harness.scheduler` | 静态架构 inventory，已过时 | design docs / inspector seed / 删除 | 不作为 runtime 代码 |
| `backend/orchestration/unit_registry.py` | `runtime_facade` 仅赋值 `self.unit_catalog`，API catalog 使用 | 被动 unit catalog | `capability_system/catalog_projection.py` 或删除 | 若 frontend 不需要，删除；不作为 runtime 权威 |
| `backend/orchestration/monitor.py` | 无 active import | 旧 runtime monitor summary | 删除或并入 `harness.runtime.run_monitor` | 当前可直接删除候选 |
| `backend/orchestration/artifact_policy_view.py` | 无 active import | 旧 artifact prompt helper | 删除候选 | 若未来需要，重写到 task/artifact contract |
| `backend/runtime/output_stream/public_contract.py` | API chat、harness projection、stream replay 使用 | public stream event taxonomy | `runtime/output_stream` 或 `harness/runtime/public_output_contract` | 保留低层 public protocol，不急搬 |

## 7. 直接清理标准

用户允许旧神经结构在审查中直接清理，但大型 runtime 重构必须先确认计划。执行时按以下标准判断：

可直接删除：

- 没有 active runtime/API/frontend import。
- 没有持久化数据迁移需求。
- 只被旧 tests 保护，且测试保护的是旧内部结构而非当前用户行为。
- 删除后不会让新旧两套权威同时存在。

迁移后删除：

- active import 存在，但职责属于目标权威层。
- 文件混合了基础设施和神经裁决，需要先拆。
- 对外 API 或 persisted field 仍暴露旧名，需要同阶段 cutover。

禁止保留：

- `harness.graph` 和 `graph_system` 两套 active graph path。
- `orchestration.ControlKernel` 作为第二个 agent control brain。
- `runtime.outcome` 和 `runtime.shared.RunOutcome` 两套结果模型。
- `runtime.tooling` 同时拥有 current-turn capability surface 和 tool execution supervision。
- `provider tools sidecar` 进入 stable prompt、memory 或 sealed provider-visible history。

## 8. 推荐目标结构

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
    capability_surface/
    dynamic_context/
    tool_plan.py
    tool_call_contract.py
    graph_node_contract.py
    output_boundary/
    outcome/
    commit_gate.py
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

backend/runtime/
  context_management/
  model_gateway/
  tool_runtime/
    supervision.py
  output_stream/
  memory/
  prompt_accounting/
  shared/
    runtime_directive.py
    background_tasks.py

backend/capability_system/
  supply.py
  catalog_projection.py
  permission_projection.py
  tools/
  mcp/
  skills/
```

## 9. Harness 优先重构路线

用户当前要求重点先重构 `harness`。推荐把“harness 第一阶段”理解为：先清出 harness 的神经边界，再收束散点，不先动前端，不直接改工具调用语义。

### Phase 0：冻结审计和工作树保护

目标：确认本文档为总审计蓝图。

动作：

- 不碰当前无关 dirty files。
- 不恢复 `tool_transport_adapter.py`。
- 不改前缀、不改前端、不改 provider payload。

完成标准：

- 本文档确认。
- 明确哪些旧神经结构可删、哪些必须迁移后删。

### Phase 1：Harness 神经边界固定

目标：让 harness 内部先有清楚插线点。

动作：

- 新增或确认 `harness.runtime.context_contract` 作为 shadow diagnostics。
- 新增目标包名 `harness.runtime.capability_surface`、`harness.runtime.output_boundary`、`harness.runtime.outcome` 的职责定义。
- 不改变 prompt/provider payload/tool behavior。

完成标准：

- 每个 agent-visible context 片段能映射到 L1-L7。
- L8 provider transport 不进入 agent history。

### Phase 2：从 harness 剥离 graph system

目标：把 harness 中最大一块非 agent-neural 权威移出。

动作：

- `harness/graph_harness.py` -> `graph_system/facade.py`。
- `harness/graph/*.py` -> `graph_system/*.py`。
- `harness/graph/work_order_contract.py` -> `harness/runtime/graph_node_contract.py`。
- API、task_system、health_system import 同阶段 cutover。

完成标准：

- active import 不再指向 `harness.graph`。
- graph core 不 import `harness.loop`。
- harness 只通过 adapter 执行 graph node agent work order。

### Phase 3：Harness 外神经散点收束

目标：把真正属于 agent 交付、输出、反馈、能力面的权威收束到 harness。

动作：

- 拆 `runtime/output_boundary`：最终输出裁决进 harness，低层 sanitizer 留 runtime/shared 或 output_stream。
- `orchestration/commit_gate.py` 迁到 harness output commit authority；同时消除 `model_gateway` 直接 commit decision。
- `runtime/tooling/capability_table.py` 归入 current capability surface 或稳定执行合同；`ToolSupervisor` 迁到 `runtime/tool_runtime/supervision.py`。
- 若接入 outcome，则将唯一 `RunOutcome` 放到 harness outcome；否则删除未接 active path 的 `runtime/outcome`。
- obligation validation 若仍需要，迁入 harness outcome；否则删除。

完成标准：

- 旧 `runtime.output_boundary` active commit decision 不再存在。
- `runtime.outcome` / `runtime.shared.RunOutcome` 不重复。
- `runtime.tooling` 旧包不再作为混合权威存在。

### Phase 4：ActionFeedback 统一

目标：权限和工具失败不再让 agent 直接断线。

动作：

- `harness.loop.admission` 的 `action_issue` 成为标准 L7 feedback node。
- `runtime.tool_runtime.tool_control_plane` 的 `denied`、`needs_approval`、`error` observation 统一投影为 agent 可理解反馈。
- 工具次数耗尽、协议修复、approval boundary 都进入同一反馈链。

完成标准：

- 可恢复失败不会 terminal。
- agent 能根据反馈选择 respond / ask_user / request_task_run / block。

### Phase 5：旧 orchestration 清理

目标：删除旧 control brain 和旧目录壳。

动作：

- 删除或迁移 `orchestration/kernel.py`、`candidates.py`、旧 `contracts.py`、旧 tests。
- `runtime_directive.py` 迁到 `runtime/shared`。
- `BackgroundTaskManager` 迁出 orchestration。
- `resource_runtime_view` 迁到 capability/permission projection。
- 删除 `monitor.py`、`artifact_policy_view.py` 等无 active import 文件。

完成标准：

- `backend/orchestration` 不再保存 agent control runtime。
- 若仍保留目录，只能保存明确的 API compatibility removal note 或迁移脚本，不能有 active neural authority。

## 10. 验证方式

不新增回归测试文件。允许验证：

```text
python -m compileall backend/harness backend/runtime backend/graph_system backend/task_system backend/api backend/health_system
rg "from harness\\.graph|harness\\.graph_harness|GraphHarness|graph_harness_config_id" backend -g "*.py"
rg "runtime\\.outcome|runtime\\.contracts\\.obligation_validation|runtime\\.tooling|orchestration\\.commit_gate" backend -g "*.py"
rg "ControlKernel|orchestration\\.contracts|orchestration\\.kernel" backend -g "*.py"
rg "provider_tools_enabled|provider_payload_sidecar_component|transport_sidecar_role" backend/harness backend/runtime -g "*.py"
```

涉及 prompt/provider payload/tool behavior 后，再做三轮 cache probe，重点看第三轮 stable prefix；涉及启动链路后，固定端口真实启动：

```text
frontend: http://127.0.0.1:3000
backend:  http://127.0.0.1:8003
```

## 11. 推荐确认项

建议确认以下执行原则后再落地：

1. `harness` 是 agent 神经系统，但不吞掉 capability/memory/permissions/provider/tool execution。
2. graph 系统从 harness 剥离，这是 harness 重构的第一刀。
3. 旧 `orchestration` 目录不能再作为第二控制脑；active infra 拆走，旧 skeleton 删除。
4. `output_boundary`、`tooling` 这类混合文件先拆权威，再迁移，不能整包机械搬。
5. `provider tools sidecar` 保持 L8 hidden transport；稳定的是 tool catalog ref 和 schema fingerprint，不是把 sidecar 塞进 stable prompt。
6. 权限系统只执行边界并反馈，不替 agent 裁决目标。

这份审计之后，真正的代码重构应从 `harness` 的边界固定和 graph 剥离开始，随后再清理外部旧神经结构。
