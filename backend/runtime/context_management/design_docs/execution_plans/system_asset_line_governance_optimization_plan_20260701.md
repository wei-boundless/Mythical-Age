# System Asset Line 与 Harness Control Spine 长期治理优化方案

创建日期：2026-07-01  
状态：上下文主线治理已收尾。2026-07-01 已落地第一片只读线路声明与拓扑投影接线；已落地 Phase 2 第一片 ActivationController 输入线状态治理；已落地 Phase 3 第一片 ContextCandidateGateway 输入闸门收束；已落地 Phase 4 第一片 ControlOutputLine 运行凭证接线；已落地 Phase 4A 第一片 TaskExecutor 后台 runner 契约接线；已落地 Phase 4A 第二片 task_execution 动作面契约收束；已落地 Phase 4A 第三片 active work continue 不再调度 task_executor；已落地 Phase 5 第一片 topology edge status 结构诊断；已落地 Phase 5 第二片 diagnostic issue link 定位投影；已落地 Phase 5 第三片 line governance issue canonical refs；已落地 Phase 6 上下文主线旧链路/旧术语收口。`task_executor` 终局删除、task recovery resume turn-bound 迁移和 `runtime_facade` 进一步薄化已移出当前上下文治理收尾，保留为独立任务机制专项  
范围：SystemAssetLine、ContextLineState、ActivationController、ContextCandidateGateway、ControlOutputLine、Harness Runtime Spine、Agent Control Network、上下文中枢与控制器双端模型

## 1. 目的

本方案承接 `physical_context_line_processing_architecture_plan_20260701.md` 的四段物理模型，但站在更高一层治理整个 agent runtime 的信息线路。

2026-07-01 整合更新：本文已吸收 harness 控制系统审查结论。长期治理不是另造一个新中枢，而是把系统资产线路治理层接到现有 `harness runtime spine` 上：

```text
SystemAssetLine / ContextLineState
-> ContextCandidateGateway / PhysicalContextAssembler
-> RuntimePacketContext
-> ModelTurnDecision
-> AdmissionDecision / ActionPermit
-> RuntimeToolControlPlane
-> RuntimeGateway / OutputCommitAuthority / Projection
```

因此，本文是后续长期治理的总权威文档；harness 控制系统审查内容已作为本文的控制输出端和运行脊柱专项章节整合，不再维护第二份并行口径。

2026-07-01 第一片实施记录：

```text
新增 runtime.context_management.system_asset_lines
-> SystemAssetLine / ContextLineState / ContextInputEnvelope / ControlOutputLine / HarnessControlSpineLine

control_action_schema
-> control_output_line_declarations()

runtime_topology_projection
-> line_governance.system_asset_lines
-> line_governance.control_output_lines
-> line_governance.harness_control_spine_lines
```

本片只建立只读声明、诊断和投影，不改变四段物理拼接、不改变 action admission、不改变 tool execution、不改变 task_executor 调度。

2026-07-01 Phase 2 第一片实施记录：

```text
新增 runtime.context_management.system_line_controller
-> ContextActivationInputs / ContextLineActivationResult
-> activate_context_message_specs()
-> build_context_line_state_inventory()

context_pipeline.apply_context_capability_profile_to_specs
-> 委托 SystemLineController 计算 ContextLineState
-> enabled line 才返回给 message_specs
-> disabled / unavailable / blocked line 进入 diagnostics
-> provider message byte-preservation replay contract 保持 enabled，避免破坏 confirmed replay

runtime_topology_projection.line_governance
-> 增加 context_line_states 静态库存
-> diagnostics 检查 ContextLineState 库存和重复 line_id
```

本片仍不改变四段物理拼接顺序，不改变 provider-visible append ledger，不改变 provider success frame 晋升规则，不改变 harness 控制输出端执行语义。

2026-07-01 Phase 3 第一片实施记录：

```text
新增 runtime.context_management.context_candidate_gateway
-> build_context_candidate_gateway()
-> materialize_context_input_envelopes()
-> ContextCandidateGatewayResult

context_pipeline
-> build_context_pipeline() 默认先经过 ContextCandidateGateway
-> apply_context_capability_profile_to_specs() 降级为只读 wrapper，不再拥有独立过滤权威

harness.runtime.compiler / single_agent_turn follow-up
-> 显式调用 ContextCandidateGateway
-> 再进入 build_context_pipeline(apply_capability_profile_stage=False)

context_contract.manifest
-> refs 读取 context_line_id / system_asset_line_id / context_input_envelope_ref
-> diagnostics 要求 agent-visible 节点携带 line/envelope identity
```

本片把 producer 到 PhysicalContextInputs 的入口收束到命名网关，但暂不一次性重写所有 producer；producer 全面返回 envelope 或 envelope refs 仍属于 Phase 3 后续片。

2026-07-01 Phase 3 第二片实施记录：

```text
ContextCandidateGateway
-> annotate_context_candidate_specs()
-> 为所有入口 specs 统一写入 context_candidate_ref / source_identity / content_identity
-> candidate diagnostics 检查 candidate/source/content identity 完整性

ContextMessageProducerRegistry
-> producer 出口写入 context_message_producer_id / producer_order / producer_item_index
-> 只声明来源，不决定 activation，不决定四段位置

SystemLineController
-> ContextInputEnvelope.source_identity/content_identity 优先读取 candidate identity
-> line_state 仍只由 SystemLineController 计算

context_contract.manifest
-> refs 投影 context_candidate_ref / producer_id / candidate source/content identity
```

本片裁决：producer 不直接产出 `ContextInputEnvelope`，因为 `ContextInputEnvelope` 内含 `ContextLineState`；`ContextLineState` 的唯一权威是 `SystemLineController`。producer 只产出 candidate identity/ref，`ContextCandidateGateway` 将候选交给 activation，再 materialize 成 `ContextInputEnvelope`。

2026-07-01 Phase 3 第三片实施记录：

```text
PhysicalContextInputs.to_diagnostics()
-> segment_lineage.static_prefix_specs
-> segment_lineage.old_context_replay_specs
-> segment_lineage.current_append_specs
-> segment_lineage.current_tail_specs
-> 每段列出 candidate_ref / producer_id / line_id / envelope_ref / frame_segment_id

PhysicalContextAssembler diagnostics
-> physical_segment_lineage.static_prefix
-> physical_segment_lineage.confirmed_old_context_replay
-> physical_segment_lineage.current_append
-> physical_segment_lineage.current_tail
-> physical_segment_lineage.never_replay_tail

context_contract.diagnostics
-> 当前候选上下文必须有 candidate / line / envelope identity
-> confirmed replay 上下文允许以 physical_prefix_frame_id + physical_prefix_frame_segment_id 作为合法上游身份
```

本片裁决：`ContextCandidateGateway` 负责本轮候选输入；`PhysicalPrefixFrame` 负责 confirmed old context replay。旧上下文回放不能伪装成新 candidate，也不能缺失 frame 身份进入 agent-visible context。

2026-07-01 Phase 4 第一片实施记录：

```text
control_action_schema
-> control_output_line_id()
-> control_output_line_binding()
-> provider native control action metadata 携带 control_output_line_ref

admission / action_permit / execution_kernel
-> AdmissionDecision.control_output_line_ref
-> ActionPermit.control_output_line_ref
-> ActionLifecycleDecision.control_output_line_ref
-> denied / invalid action 保留原始 action_type，不替换成其他动作

tool_control_plane / output_commit_authority
-> ToolObservation.execution_receipt 写回 action_permit_ref / control_output_line_ref
-> OutputCommitAuthority checked / terminal payload 保留 request refs
-> single_agent_turn respond / ask_user / block final commit 携带 action lifecycle refs

runtime_topology_projection.line_governance
-> HarnessControlSpineLine.control_output_line_ref
-> diagnostics 检查 ControlOutputLine line_id / permit / executor / observation / terminal policy
-> diagnostics 检查 HarnessControlSpineLine 是否接到已声明 ControlOutputLine
```

本片裁决：`ControlOutputLine` 是控制端静态线声明；`AdmissionDecision` 只绑定或拒绝模型动作，不改写目标；`ActionPermit` 是运行凭证；tool observation 与 final commit 只回写 refs/receipt，不生成 provider context，不让 public projection 反向污染上下文中枢。

2026-07-01 Phase 4A 第一片实施记录：

```text
新增 harness.runtime.harness_spine_contract
-> task_executor_runner_contract()
-> task_executor_runner_contract_inventory()
-> contract_id = harness_spine.task_executor_background_runner

TaskExecutorController
-> schedule / recover_scheduled 的 schedule_result 写入 harness_spine_contract
-> task_run_executor_scheduled event 写入 harness_spine_contract
-> step_summary_recorded event 写入 harness_spine_contract
-> TaskRun.diagnostics 写入 harness_spine_contract

TaskRunControlGateway
-> resume / approval resume / launch-gate resume 输出写入 harness_spine_contract
-> scheduler unavailable / schedule rejected / schedule accepted 都保留同一 contract

runtime_topology_projection.line_governance
-> harness_runtime_spine_contracts
-> diagnostics 检查 runner_role / default_model_entrypoint / execution_entrypoint / controller / gateway / packet / migration_target / forbidden_routes
```

本片裁决：`task_executor` 当前只被声明为 `durable_task_background_runner`，不是普通会话默认模型入口。普通用户 turn 的默认模型入口仍是 `harness.loop.single_agent_turn`；`TaskRun` 是系统提供的持久状态和环境，不是第二条对话主链。

2026-07-01 Phase 4A 第二片实施记录：

```text
harness.runtime.harness_spine_contract
-> TASK_EXECUTOR_BASE_ACTION_TYPES
-> TASK_EXECUTOR_CONDITIONAL_ACTION_TYPES
-> TASK_EXECUTOR_FORBIDDEN_ORDINARY_ACTION_TYPES
-> task_executor_runner_contract 投影 action surface / action schema / base / conditional / forbidden action types

packet_assembler._task_execution_model_action_surface
-> 从 harness spine contract 读取 task_execution 基础动作面
-> contract_ref = harness_spine.task_executor_background_runner.action_surface
-> source_authority = harness.runtime.harness_spine_contract

compiler.task_execution_action_schema
-> 默认动作面读取 TASK_EXECUTOR_BASE_ACTION_TYPES
-> request_task_run / active_work_control / resume_task_recovery 若进入 task_execution schema，直接暴露结构错误

runtime_topology_projection.line_governance diagnostics
-> 检查 harness runtime spine contract 是否声明 action surface / action schema / base actions / forbidden ordinary actions
-> 检查 task_execution 允许动作与 forbidden ordinary actions 不重叠
```

本片裁决：`task_execution` 动作面不再由 `packet_assembler` 与 `compiler` 各自硬编码；它们共同消费 `harness_spine.task_executor_background_runner` 契约。该片仍不改变 `task_executor` 的执行策略，只把“哪些线能进入 task_execution，哪些普通 turn 控制线绝不能进入 task_execution”接到同一权威源上。

2026-07-01 Phase 4A 第三片实施记录：

```text
active_work_control action surface
-> 移除 continue_active_work / answer_then_continue_active_work
-> 保留 pause_active_work / stop_active_work / append_instruction_to_active_work / answer_about_active_work

harness.loop.active_work
-> active_work_action_is_allowed 不再接受 continue_active_work / answer_then_continue_active_work
-> instruction / answer 规范化到 appended_instruction / response

runtime_facade current work control
-> 删除 _apply_continue_active_work
-> append_instruction_to_active_work 只写入当前工作补充，不再 resume/schedule task_executor
-> 当前 work continue 由 single_agent_turn 在本轮普通动作面继续选择 tool_call/respond/ask_user/block

TaskExecutorController
-> 拒绝 conversation_continue / conversation_instruction / active_work_control scheduler
-> 断言 conversation continue 必须进入 single_agent_turn

prompt_library / turn_operating_contract
-> task 是持久状态、环境、游标和验收边界
-> turn 是 agent 行动心脏
-> 用户要求继续当前工作时，不使用 active_work_control 调度另一个执行器
```

本片裁决：`active_work_control` 是控制端，不是续跑心脏；“继续当前工作”必须回到当前 `single_agent_turn` 的普通行动面。`TaskRun` 只为 turn 提供持久上下文、任务状态、环境和验收边界，不能反向拥有一条脱离 turn 的模型循环。

2026-07-01 Phase 5 第一片实施记录：

```text
context_contract.diagnostics.diagnose_runtime_topology_projection
-> missing_edge_status 进入结构 issue
-> diagnostics.missing_status_edges 暴露缺 status 的边
-> non_connected_edges 继续记录显式非 connected 边

frontend /agent-network
-> RuntimeTopologyEdgeStatus 增加 missing_status / disconnected / broken
-> normalizedEdge 不再把缺失 status 默认成 connected
-> status strip 显示 diagnostics issue_count / line_governance issue_count
-> missing_status / disconnected / broken 边使用异常样式
```

本片裁决：拓扑图只呈现后端声明的边状态；缺少 status 的边本身就是结构问题，不能在前端被默认成已接通。Phase 5 后续继续把 line governance 的 issue 定位、缺 owner / 缺 activation / 缺 terminal policy 等诊断投到图上，而不是让 UI 自行猜测。

2026-07-01 Phase 5 第二片实施记录：

```text
context_contract.diagnostics.diagnose_runtime_topology_projection
-> diagnostics.diagnostic_issue_links
-> 每个 issue 归一化为 issue_id / severity / subject_type / affected_edge_id / affected_node_id
-> 标记 line_domain / broken_segment / authority / details

frontend /agent-network
-> RuntimeTopologyDiagnosticIssueLink 类型声明
-> 检查器显示结构诊断清单
-> issue 带 affected_edge_id / affected_node_id 时点击选择对应连线或节点
```

本片裁决：断线定位由后端 diagnostics 产出，前端只渲染和跳转 canonical refs，不根据文案、数组顺序或展示标题猜测断点。该片仍属于只读诊断投影，不改变 runtime 决策、不改变四段物理拼接、不改变工具/任务执行。

2026-07-01 Phase 5 第三片实施记录：

```text
context_contract.diagnostics.diagnostic_issue_links
-> affected_line_id
-> affected_action_type
-> affected_contract_id
-> line_inventory_ref
-> governance_ref

frontend /agent-network
-> RuntimeTopologyDiagnosticIssueLink 声明治理库存定位字段
-> 结构诊断行显示 governance_ref
```

本片裁决：line governance 的问题必须定位到治理库存中的 canonical ref，例如 `line_governance.control_output_lines:control_output_line:respond` 或 `line_governance.harness_runtime_spine_contracts:harness_spine.task_executor_background_runner`。前端不从 issue 文案反推库存对象，只显示后端 diagnostics 给出的 refs。

2026-07-01 Phase 6 上下文主线收尾实施记录：

```text
context_segment_policy
-> 未声明 context kind 不再默认 CONTEXT_APPEND
-> 返回 undeclared_context_segment 隔离策略
-> commit_policy = never_commit
-> replay_policy = undeclared_context_segment_blocked
-> SystemLineController 继续在 materialize 前阻止未声明 kind 进入 ContextInputEnvelope

context_segment_registry
-> runtime_control_signal_tail content_source 接到 harness.loop.single_agent_turn.runtime_control_boundary
-> interrupt / runtime control signal 的 producer identity 不再停在泛化 dynamic_context_fragment

design_docs index / semantic_space README
-> 旧 semantic_space 文档标为历史参考
-> 当前术语收束到 SystemAssetLine / ContextLineState / ContextInputEnvelope / PhysicalContextInputs / ControlOutputLine
-> session memory / working memory 只能表示摘要源或事实源，不能替代 confirmed old provider context
```

本片裁决：新增系统上下文资产必须先声明线，未声明 kind 不能靠 default section 或 stream fallback 进入当前 append。runtime control signal 是当前 turn 的控制/修复反馈动态尾；它可以成为下一轮可读事实，但不会伪装成 confirmed old context。

这次已修复的问题是：

```text
候选上下文
-> PhysicalContextInputs
-> 唯一四段物理插线
-> provider payload
```

长期要解决的问题是：

```text
所有系统资产如何声明自己的线
每轮哪些线开启
哪些线进入 agent 可读上下文中枢
agent 的模型决策如何反向控制系统
输出、投影、记忆、任务、工具、权限、恢复如何不串线
```

核心目标：

```text
系统资产都有静态线路声明
每轮是否启用由动态 activation 控制
上下文中枢只接收已启用的信息输入线
控制器只接收模型决策后的输出控制线
插线前可以处理数据，插线后只能诊断/记录/呈现
旧主链路清理，不保留长期 v1/v2 双跑
harness runtime spine 保留为唯一运行主脊柱
task_executor 不再扩展成第二条模型心智主链
```

## 2. 问题定义

### 2.1 当前已解决的局部断线

新会话上下文丢失的直接断线点已经修复：

```text
provider-visible append ledger skipped
-> 不再导致 physical assembly skipped

follow-up 私有四段拼接
-> 已删除，改走统一 context pipeline

runtime_memory_context
-> 不再作为 CONTEXT_MEMORY_PREFIX old context
-> 改为 CONTEXT_APPEND current hint

physical_context_plan
-> 不再推断 lane
-> 只读 assembler 写入的 lane/index
```

### 2.2 仍未治理的更高层问题

当前系统仍缺一套统一的系统资产线路治理层：

| 问题 | 当前表现 | 长期风险 |
| --- | --- | --- |
| 系统资产没有统一线路声明 | `context_segment_registry.py` 已声明很多 kind，但还不是完整 SystemAssetLine | 新资产要在多个地方补 metadata / producer / consumer / activation |
| activation 分散 | capability profile、dynamic context、prompt wiring、task state、frontend projection 各自开关 | 资产可能先进入 message_specs，再被下游隐藏，层级反了 |
| 上下文输入端和控制输出端没有同一治理模型 | context pipeline 管输入，control action schema 管输出，但两端没有统一线表 | agent 读取的信息和 agent 反向控制系统的动作难以闭环追踪 |
| 诊断拓扑仍偏展示 | agent-control-network 已能展示节点/边，但还不是主控制契约 | 图上看得到线，不等于 runtime 只能按这些线运行 |
| 旧文档和旧命名仍会误导 | `memory prefix`、`session memory`、`provider-visible ledger` 历史语义混杂 | 维护者可能再次把摘要、旧上下文、前端投影串在一起 |
| harness 控制输出端仍有历史重型执行线 | `single_agent_turn` 是主 turn loop，但 `task_executor` 仍保留独立模型循环和 `task_execution` packet | 长期可能形成第二条 agent 心智主链 |
| facade 聚合过厚 | `runtime_facade.py` 同时处理 runtime assembly、恢复、active work、task scheduling、output commit glue | 入口层可能逐步变成隐性控制器 |

### 2.3 正确系统属性

一个成熟 agent runtime 至少要满足：

```text
RequestFacts
-> BoundaryPolicy
-> ContextCandidates
-> ModelTurnDecision
-> ActionPermit
-> RuntimeStartPacket
-> ExecutionLoop
```

落到本项目，更具体是：

```text
系统事实输入端：系统收集信息，形成 agent 可读上下文中枢
模型决策中端：agent 基于中枢信息作出语义决策
控制输出端：agent 决策转成系统可执行控制线
执行观察尾端：系统执行、记录、投影、封存，再成为下一轮事实输入
```

上下文是 agent 读取系统收集信息的中枢；控制器是 agent 反向输出信息控制系统的另一端。二者必须相连，但不能混层。

## 3. 来源依据

### 3.1 本地代码依据

| 文件 | 当前角色 | 提炼出的治理原则 |
| --- | --- | --- |
| `backend/runtime/context_management/context_segment_registry.py` | kind -> section / semantic_slot / capability 的声明表 | 可升级为 SystemAssetLine 的来源之一，但字段还不够完整 |
| `backend/runtime/context_management/context_segment_policy.py` | 根据 kind / metadata 生成上下文策略 | policy 只能解释声明，不能成为隐式补线 fallback |
| `backend/runtime/context_management/context_pipeline.py` | context candidates -> PhysicalContextInputs -> assembler -> diagnostics | 上下文输入端已经有可收束主链 |
| `backend/runtime/context_management/physical_context_assembler.py` | 唯一四段物理插线 authority | 插线权威必须单一，其他层只能给输入或读诊断 |
| `backend/runtime/context_management/physical_context_plan.py` | 只读 lane/hash diagnostics | 插线后不能再做物理决策 |
| `backend/harness/runtime/control_action_schema.py` | 模型控制动作 tool schema | 控制输出端需要像上下文输入端一样拥有线路声明和 admission |
| `backend/harness/current_work_receipt.py` | active work control receipt gate | active work 控制必须由 receipt 凭证开放，不能由下游状态猜测 |
| `backend/harness/recovery_receipt.py` | task recovery receipt gate | task recovery 必须由 enforced receipt 和 route 凭证开放 |
| `backend/harness/runtime/packet_context.py` | runtime packet 中心容器 | action surface、tool plan、operation availability 是插线后的运行包，不能由下游二次改线 |
| `backend/harness/loop/model_action_protocol.py` | 模型动作归一化 | parser 只归一化模型表达，不授权、不执行 |
| `backend/harness/loop/admission.py` | action admission | 动作准入是控制输出端的授权层 |
| `backend/harness/loop/action_permit.py` | action permit identity | permit 是工具执行和控制动作进入执行面的凭证 |
| `backend/runtime/tool_runtime/tool_control_plane.py` | 工具执行控制面 | 工具执行权收束于 control plane，executor 不应绕过 |
| `backend/harness/runtime/runtime_gateway.py` | runtime control fact gateway | gateway 记录和 drain facts，不决定 intent、不授权、不提交 |
| `backend/harness/runtime/output_commit_authority.py` | assistant final commit gate | final answer 必须经过统一提交权威 |
| `backend/harness/loop/task_executor.py` | 历史重型 task execution loop | 当前仍是第二模型循环风险源，需专项治理 |
| `backend/harness/runtime/context_contract/inspection_payload.py` | agent control network 节点/边投影 | 可成为治理可视化，不应只是 UI 图 |
| `backend/harness/runtime/compiler.py` | 当前 packet 编译与多种投影聚合点 | 长期应瘦身，调用已决策结果，不直接拥有多套语义投影 |
| `frontend/src/lib/store/runtime.ts` | public projection / stream state / interrupt handling | 前端只能保存 public projection，不产生 provider/model context |

### 3.2 本地计划依据

| 文档 | 已确立原则 |
| --- | --- |
| `physical_context_line_processing_architecture_plan_20260701.md` | 四段物理模型、唯一 assembler、ledger 不排序、plan 只诊断 |
| `prompt_system_architecture_refactor_plan_20260701.md` | Agent Visible Context Projection 是 agent 可读语义边界；prompt 必须按角色/职责/边界写 |
| `harness_neural_system_consolidation_plan_20260628.md` | harness 是 agent 神经控制系统；context 是输入中枢，action/admission/execution 是控制输出链 |
| `agent_control_network_architecture_cleanup_plan_20260630.md` | runtime topology 必须反映真实权威线，不只是展示线 |
| `harness_runtime_spine_authority_index_20260630.md` | harness runtime spine 是唯一运行主干；projection 不能成为 runtime owner |
| `task_as_turn_overlay_architecture_review_20260628.md` | `TaskRun` 是持久工作资源，普通 turn 仍是模型决策与工具执行单位 |
| `interruptible_runtime_control_plan.md` | interrupt / runtime control signal 应作为事实和控制边界处理，不能让系统替模型重写语义 |

### 3.3 成熟架构不变量

本方案只借成熟 agent 架构的不变量，不复制外部目录：

```text
事实收集和语义决策分开
恢复候选和当前决策分开
上下文输入和控制输出分开
权限准入在执行前
输出提交有 canonical gate
投影是展示，不是运行事实源
长短期记忆是事实源，不是 provider old context 的替代品
```

## 4. 总线路处理模型

### 4.1 双端模型

```text
事实输入端
SystemAsset
-> SystemAssetLine
-> ContextLineState
-> ContextCandidateGateway
-> PhysicalContextInputs
-> PhysicalContextAssembler
-> ProviderPayload

模型决策中端
ProviderResponse
-> ModelTurnDecision

控制输出端
ModelTurnDecision
-> ControlOutputLine
-> ActionPermit
-> Executor
-> ObservationFeedback
-> Commit / Projection / Memory
```

### 4.2 中枢与控制器

| 端 | 含义 | 权威 | 禁止 |
| --- | --- | --- | --- |
| 上下文中枢 | agent 读取系统收集的信息 | ContextCandidateGateway + PhysicalContextAssembler | 直接执行动作、授权工具、恢复旧运行 |
| 控制器 | agent 输出控制系统的动作 | ControlOutputLine + ActionPermit | 改写上下文历史、伪造 provider success、把展示投影当事实 |
| 执行尾端 | 工具、任务、文件、provider、memory 的实际执行与记录 | executor / ledger / store owner | 重新解释用户意图 |
| 展示端 | 前端 public projection、诊断拓扑、运行状态 | frontend store / inspection payload | 生成 provider/model context |

### 4.3 Harness runtime spine 是控制输出端的主实现

长期治理层不能绕过已有 harness 主脊柱。当前主脊柱为：

```text
runtime_facade.astream
-> assemble_runtime
-> current_work_boundary / receipt
-> RuntimePacketContext
-> model_action_protocol
-> admission
-> ActionPermit
-> RuntimeToolControlPlane
-> observation / runtime signal / output commit / projection
```

证据：

| 线 | 当前证据 | 治理含义 |
| --- | --- | --- |
| request -> facade | `backend/harness/entrypoint/runtime_facade.py:457` | facade 是入口 adapter，不应升级为全能控制器 |
| facade -> ordinary turn | `backend/harness/entrypoint/runtime_facade.py:879` | `single_agent_turn` 是普通 turn 主执行 loop |
| active work receipt | `backend/harness/current_work_receipt.py:37`, `backend/harness/current_work_receipt.py:88` | active work control 必须由 receipt 开线 |
| recovery receipt | `backend/harness/recovery_receipt.py:37`, `backend/harness/recovery_receipt.py:86` | task recovery 必须由 enforced receipt 开线 |
| packet context | `backend/harness/runtime/packet_assembler.py:20`, `backend/harness/runtime/packet_context.py:45` | 插线后的 action surface / tool plan / operation availability 只读消费 |
| model action -> admission | `backend/harness/loop/model_action_protocol.py:100`, `backend/harness/loop/admission.py:46` | 模型表达和授权分层 |
| permit -> tool control plane | `backend/harness/loop/action_permit.py:12`, `backend/runtime/tool_runtime/tool_control_plane.py:136` | 工具执行必须经 permit 和 control plane |
| runtime facts -> gateway | `backend/harness/runtime/runtime_gateway.py:24`, `backend/harness/runtime/runtime_gateway.py:269` | facts 可记录/消费，不能替代决策 |
| final candidate -> commit | `backend/harness/runtime/output_commit_authority.py:65`, `backend/harness/runtime/output_commit_authority.py:214` | assistant final 必须经统一 commit gate |

### 4.4 Harness 已接稳资产

这些资产应纳入长期治理的保留名单：

| 资产 | 当前价值 | 长期治理定位 |
| --- | --- | --- |
| `CurrentWorkBoundaryReceipt` | 把 active work control 从状态猜测变成凭证校验 | ControlOutputLine 的运行前置凭证 |
| `RecoveryReceipt` | 把 task recovery 从模糊历史恢复变成 enforced receipt + route | task recovery 控制线的边界凭证 |
| `RuntimePacketContext` | 集中 action surface、tool plan、operation availability | 插线后运行包 |
| `ModelActionProtocol + Admission + ActionPermit` | 分离模型表达、协议归一化、动作授权 | 控制输出端核心权威链 |
| `RuntimeToolControlPlane` | permit validation、tool plan membership、operation gate、supervisor、executor dispatch | 工具执行唯一控制面 |
| `RuntimeGateway` | 记录和 drain runtime facts | 事实 gateway，不是决策器 |
| `OutputCommitAuthority` | 统一 assistant final commit | 输出提交唯一闸门 |
| `TaskRunControlGateway` | pause/stop/resume 等 task 控制入口 | task 控制系统入口 |

### 4.5 Harness 当前结构张力

当前最大风险不是工具授权或输出提交旁路，而是历史 task 执行线仍像第二条模型运行脊柱：

```text
single_agent_turn 是主 turn loop
task_executor 仍拥有独立 task model loop
```

证据：

| 风险线 | 当前证据 | 长期治理动作 |
| --- | --- | --- |
| task executor 解析 task execution action | `backend/harness/loop/task_executor.py:1470` | 不再扩展普通 task-bound 语义 |
| task executor 编译 task execution packet | `backend/harness/loop/task_executor.py:1751` | 收束 `task_execution` packet 的用途 |
| task executor 独立调用模型 | `backend/harness/loop/task_executor.py:4285` | 普通 task-bound 工作迁回 `single_agent_turn + task overlay` |
| active work continue 调度 executor | `backend/harness/entrypoint/runtime_facade.py:2178`, `backend/harness/entrypoint/runtime_facade.py:2212` | 长期改为重新进入 task-bound ordinary turn |
| task executor controller schedule | `backend/harness/loop/task_executor_controller.py:25` | schedule 权力与 overlay 目标对齐 |

治理裁决：

```text
保留 harness runtime spine
保留 receipt / admission / permit / tool control plane / gateway / commit authority
冻结 task_executor 的新增语义能力
先薄化 facade，再裁定 task overlay 切换
把 ordinary task-bound work 收束到 single_agent_turn
把 task_executor 降级或删除为后续专项工程
```

## 5. 核心数据模型

### 5.1 SystemAssetLine

静态声明。每个系统资产都必须有线，即使默认不开启。

```text
line_id
asset_id
asset_owner
asset_kind
producer_ref
transport_or_store
consumer_domain
physical_segment
semantic_slot
capability_group
capability_slot
identity_key
lifecycle
sealability
provider_visibility
activation_policy_ref
terminal_policy
schema_revision
deprecation_state
```

规则：

```text
SystemAssetLine 是静态资产声明
不能根据本轮状态临时发明
不能在下游 fallback 中补默认 physical_segment
新增系统资产必须先声明线，再接入 producer
```

### 5.2 ContextLineState

动态状态。每轮判断一条线是否进入上下文中枢。

```text
line_id
invocation_id
session_id
task_run_id
status = enabled | disabled | unavailable | blocked | diagnostic_only
activation_authority
disabled_reason
source_ref
payload_ref
freshness
budget_class
diagnostics
```

规则：

```text
enabled 才能进入 ContextCandidateGateway
diagnostic_only 只能进入 inspection/report
blocked 必须说明阻塞原因，不能静默降级为 disabled
unavailable 表示事实源不可用，不等于用户不需要
```

### 5.3 ContextInputEnvelope

从系统资产到上下文中枢的输入包。

```text
line_state
context_spec
source_identity
content_identity
visibility_contract
seal_contract
```

它负责把 asset line 和 message spec 绑定起来，避免 message spec 成为无来源的自由文本。

### 5.4 ControlOutputLine

agent 反向控制系统的输出线。

```text
line_id
action_type
model_decision_ref
authority
permit_policy_ref
executor_ref
observation_contract
public_projection_policy
commit_policy
terminal_policy
failure_feedback_policy
schema_revision
```

规则：

```text
control action 必须先经过 ActionPermit
ActionPermit 不允许替 agent 换目标
executor 不允许静默吞失败
ObservationFeedback 必须能回到下一轮上下文中枢
```

### 5.5 HarnessControlSpineLine

不是新增第二套数据模型，而是 `ControlOutputLine` 在 harness 主脊柱上的具体落点。

```text
control_line_id
action_type
control_output_line_ref
model_action_ref
packet_context_ref
receipt_ref
admission_ref
permit_ref
tool_plan_ref
tool_invocation_ref
runtime_gateway_ref
commit_ref
projection_ref
terminal_policy
```

规则：

```text
普通工具和控制动作都必须能追踪到 packet context / admission / permit
active_work_control 必须追踪到 CurrentWorkBoundaryReceipt
resume_task_recovery 必须追踪到 RecoveryReceipt
final response 必须追踪到 OutputCommitAuthority
runtime facts 必须追踪到 RuntimeGateway，不得反向决定 intent
```

### 5.6 SystemLineController

治理控制器，不直接拼 prompt，不直接执行工具。

职责：

```text
读取 SystemAssetLine
计算 ContextLineState
产出 enabled ContextInputEnvelope
产出 diagnostic line report
把 ModelTurnDecision 映射到 ControlOutputLine
把执行结果归还给对应 owner
```

禁止：

```text
重排 PhysicalContextInputs
改写用户意图
直接调用 provider
绕过 ActionPermit 执行工具
把 frontend projection 写成 memory/provider context
```

## 6. 固定执行流

### 6.1 上下文输入端

```text
1. Asset owners register SystemAssetLine
   input: asset definition
   output: static line declaration
   authority: asset owner + SystemLineRegistry
   forbidden: produce message_specs

2. ActivationController evaluates line state
   input: SystemAssetLine + invocation facts + profile + permissions + task/session state
   output: ContextLineState
   authority: SystemLineController
   forbidden: physical splice, provider payload serialization

3. ContextCandidateGateway materializes enabled lines
   input: enabled ContextLineState + producer payload refs
   output: ContextInputEnvelope / message_specs
   authority: context gateway
   forbidden: decide model action

4. ContextPipeline classifies physical inputs
   input: message_specs
   output: PhysicalContextInputs(draft/final)
   authority: runtime.context_management.context_pipeline
   forbidden: skip physical assembly because ledger skipped

5. PhysicalContextAssembler splices four segments
   input: PhysicalContextInputs(final)
   output: provider message_specs with lane/index
   authority: runtime.context_management.physical_context_assembler
   forbidden: action permit, semantic task decision

6. PhysicalContextPlan diagnoses
   input: assembled message_specs
   output: cache spine hash / blocked_segments / stable-after-tail violations
   authority: runtime.context_management.physical_context_plan
   forbidden: infer missing lane, rewrite order
```

### 6.2 控制输出端

```text
1. ModelTurnDecision emits control action
   input: provider response
   output: respond / ask_user / block / request_task_run / active_work_control / resume_task_recovery / pause_for_user_steer
   authority: model decision contract
   forbidden: self-authorize execution

2. ControlOutputLine validates shape
   input: model action payload
   output: typed control output line
   authority: harness.runtime.control_action_schema
   forbidden: replace action with fallback goal

3. ActionPermit authorizes
   input: control output line + permissions + current work boundary
   output: allowed / denied / needs_confirmation
   authority: admission / permission boundary
   forbidden: execute denied action

4. Executor performs side effect
   input: permitted action
   output: observation / failure / terminal state
   authority: executor owner
   forbidden: hide failure as success

5. ObservationFeedback records and projects
   input: executor observation
   output: public projection + diagnostic + next-turn context candidate if needed
   authority: output/ledger owner
   forbidden: generate provider old context without provider success
```

### 6.3 Harness 控制输出端固定流

```text
1. RuntimePacketContext exposes action surface
   input: receipts + tool plan + operation availability
   output: allowed action surface
   authority: packet_assembler / compiler
   forbidden: 下游二次开放 action

2. ModelTurnDecision emits action
   input: runtime packet
   output: respond / ask_user / block / request_task_run / active_work_control / resume_task_recovery / tool_call
   authority: model action contract
   forbidden: 自授权、自执行

3. ModelActionProtocol normalizes
   input: provider payload
   output: typed action request
   authority: model_action_protocol
   forbidden: 改写目标

4. Admission authorizes
   input: action request + packet availability + policy
   output: AdmissionDecision
   authority: admission
   forbidden: denied action 变替代 action

5. ActionPermit binds execution
   input: allowed admission
   output: permit identity
   authority: action_permit
   forbidden: 执行工具

6. RuntimeToolControlPlane executes tools
   input: permit + tool request + tool plan
   output: ToolObservation / lifecycle event
   authority: runtime.tool_runtime.tool_control_plane
   forbidden: 绕过 permit / operation gate

7. RuntimeGateway records facts
   input: runtime control facts / observations
   output: observed / consumed facts
   authority: runtime_gateway
   forbidden: 决定 intent / commit final

8. OutputCommitAuthority commits final
   input: final candidate
   output: committed / skipped / failed final
   authority: output_commit_authority
   forbidden: 接收旧流 terminal text 直通
```

## 7. 四段物理算法与语义架构

四段算法保持不变，治理层只决定线能否进入四段输入包。

| 物理段 | 输入来源 | 语义 | 是否静态 | 是否可动态启用 | 晋升/终止 |
| --- | --- | --- | --- | --- | --- |
| `static_prefix_specs` | stable contracts、prompt role、tool/action schema、environment stable facts | 本轮稳定契约 | 是 | 可通过 activation 开关选择是否挂载 | 不由 provider success 晋升 |
| `old_context_replay_specs` | physical prefix frame confirmed replay | 已确认 provider 历史 | 否，内容稳定 | 只由 confirmed frame 决定 | provider success 是唯一晋升入口 |
| `current_append_specs` | current user、memory hints、tool transcript、evidence refs、session emphasis | 本轮新增事实/提示 | 否 | 是 | provider success 后可进入 future frame |
| `current_tail_specs` | dynamic control、active lease、recovery feedback、frontend-visible repair facts | 当前控制/反馈/不封存状态 | 否 | 是 | 本轮结束即过期或转 observation |

关键边界：

```text
runtime_memory_context 是 current append hint
session memory / working memory 是事实源或摘要源，不是 old provider context
frontend projection 是 public display state，不是 provider context
task recovery 是任务资源恢复，不是 turn history 替代品
dynamic tail 不能晋升 confirmed old context
```

## 8. 模块优化方案

### Phase 0: 线路盘点与命名冻结

状态：第一片已落地只读基础。当前已能从 `context_segment_registry` 派生 SystemAssetLine inventory，并随 runtime topology projection 暴露。

目标：

```text
冻结 active 主链路命名，列出所有系统资产和当前 producer
```

文件：

```text
backend/runtime/context_management/context_segment_registry.py
backend/harness/runtime/context_message_producers.py
backend/harness/runtime/compiler.py
backend/harness/runtime/context_contract/inspection_payload.py
backend/harness/runtime/control_action_schema.py
frontend/src/lib/store/runtime.ts
```

动作：

```text
导出当前 ContextSegmentKindDeclaration 清单
导出当前 control action 清单
导出 frontend public projection 状态清单
标记每条线的 owner / producer / consumer / current physical segment
标记缺 owner、缺 activation、缺 terminal policy 的线
```

完成条件：

```text
形成 SystemAssetLine inventory
每条 active context kind 都能追溯到 owner
每个 control action 都能追溯到 permit/executor/observation
旧命名只允许出现在历史文档，不作为新代码字段
```

### Phase 1: 引入 SystemAssetLine 静态声明

状态：第一片已落地基础数据模型和只读派生。后续仍需把新增 context kind 的声明要求收紧为接入规则。

目标：

```text
把 context_segment_registry 从 kind policy 表升级为系统资产线路声明的输入源
```

文件：

```text
backend/runtime/context_management/context_segment_registry.py
backend/runtime/context_management/context_segment_policy.py
backend/runtime/context_management/system_asset_lines.py
backend/harness/runtime/context_contract/inspection_payload.py
```

动作：

```text
新增 SystemAssetLine dataclass
从 ContextSegmentKindDeclaration 生成 SystemAssetLine draft
补齐 producer_ref / transport_or_store / consumer_domain / terminal_policy / schema_revision
context_segment_policy 只消费声明，不再猜测未声明 kind
inspection payload 显示 line_id 和 owner
```

完成条件：

```text
新增 context kind 必须有 SystemAssetLine
未声明 kind 进入结构诊断，不进入 provider payload
SystemAssetLine 可被 agent-control-network 读取
```

### Phase 2: 引入 ActivationController

状态：第一片已落地。`system_line_controller.py` 已成为输入端 activation 的统一控制器；`context_pipeline.apply_context_capability_profile_to_specs()` 已委托该控制器计算 `ContextLineState`，并只把 enabled specs 交给后续 message_specs / PhysicalContextInputs。后续仍需在 Phase 3 把各 producer 的返回值升级为完整 `ContextInputEnvelope`，避免 producer 长期直接产出自由 message spec。

目标：

```text
所有系统资产先判断是否通线，再进入 message_specs
```

文件：

```text
backend/runtime/context_management/system_line_controller.py
backend/runtime/context_management/context_pipeline.py
backend/harness/runtime/context_message_producers.py
backend/harness/runtime/compiler.py
backend/prompt_library/wiring.py
backend/agent_system/profiles/runtime_profile_models.py
```

动作：

```text
新增 ContextLineState
定义 enabled / disabled / unavailable / blocked / diagnostic_only
把 capability profile、prompt profile、task/session state、permissions 统一转成 activation inputs
producer 只 materialize enabled line
disabled/unavailable/blocked 进入 diagnostics，不进入 message_specs
```

完成条件：

```text
不存在先插入 message_specs 再下游过滤 disabled 资产
每个 disabled line 都有 disabled_reason
blocked line 不会静默降级成普通缺省
```

### Phase 3: 收束 ContextCandidateGateway

状态：第三片已落地。已新增 `context_candidate_gateway.py`，并将 `context_pipeline`、compiler prompt assembly、tool follow-up 私有路径统一改为先经过 `ContextCandidateGateway`，再进入四段物理输入；`context_contract.manifest` 已投影 `context_candidate_ref`、`context_message_producer_id`、`context_line_id`、`system_asset_line_id`、`context_input_envelope_ref`。producer 出口现在声明 candidate identity/ref，`ContextInputEnvelope` 仍由 gateway + `SystemLineController` materialize，避免 producer 越权生成 line_state。`PhysicalContextInputs` 和 assembler diagnostics 已能列出每个物理段里的 candidate / line / envelope / frame replay lineage。

目标：

```text
producer 不直接发散成自由 message spec，而是产出绑定 line_state 的 ContextInputEnvelope
```

文件：

```text
backend/harness/runtime/context_message_producers.py
backend/harness/runtime/dynamic_context/*
backend/memory_system/runtime_context_provider.py
backend/runtime/context_management/context_pipeline.py
```

动作：

```text
新增 ContextInputEnvelope
producer 返回 envelope 或 envelope refs
context_pipeline 只接收 envelope materialized specs
memory、evidence、tool transcript、task state 都必须带 line_id/source_identity/content_identity
```

完成条件：

```text
message spec 都能追溯 line_id
runtime_memory_context / evidence / tool transcript 不再靠 kind 字符串找来源
下一轮 replay 能追溯到 provider success frame，不靠摘要替代
```

### Phase 4: 建立 ControlOutputLine 控制端

状态：第一片已落地。`control_action_schema` 已能为 respond / ask_user / block / request_task_run / active_work_control / resume_task_recovery / pause_for_user_steer 生成稳定 `control_output_line:{action}`；`AdmissionDecision`、`ActionPermit`、`ActionLifecycleDecision`、工具 observation receipt、final commit refs 和 agent-control-network line governance 均已携带控制线引用。后续仍需继续审查 interrupt / runtime control signal 的 observation 回流，以及 `resume_task_recovery` 的 RecoveryReceipt 路由是否在所有入口都能形成同源 refs。

目标：

```text
agent 输出控制系统的动作也纳入线路治理
```

文件：

```text
backend/harness/runtime/control_action_schema.py
backend/harness/loop/admission.py
backend/runtime/tool_runtime/tool_control_plane.py
backend/harness/loop/single_agent_turn.py
backend/harness/loop/task_executor.py
backend/harness/current_work_receipt.py
backend/harness/recovery_receipt.py
backend/harness/runtime/packet_context.py
backend/harness/runtime/runtime_gateway.py
backend/harness/runtime/output_commit_authority.py
backend/harness/runtime/task_run_control_gateway.py
backend/runtime/output_stream/public_contract.py
```

动作：

```text
新增 ControlOutputLine 声明
control action schema 输出 typed line
admission 只做 permit，不改目标
executor observation 必须回写 observation contract
public projection 只消费 observation/public event，不产生 provider context
active_work_control 只能由 CurrentWorkBoundaryReceipt 开线
resume_task_recovery 只能由 RecoveryReceipt 开线
final response 只能由 OutputCommitAuthority 提交
```

完成条件：

```text
respond / ask_user / block / request_task_run / active_work_control / resume_task_recovery / pause_for_user_steer 都有 line declaration
denied action 不会变成替代 action
tool failure / permission denial / interrupt 都有下一轮可读 ObservationFeedback
```

### Phase 4A: Harness runtime spine 专项治理

状态：第三片已落地。已新增 `harness_spine.task_executor_background_runner` 运行脊柱契约；已收束 task_execution 动作面；已切断 `active_work continue -> schedule task_executor` 旧线。当前剩余风险集中在 `task_executor` 终局删除/降级、`task recovery resume` 是否也迁成 turn-bound recovery，以及 `runtime_facade` 进一步薄化。

目标：

```text
把 harness 已有成熟控制脊柱纳入长期治理，并收束 task_executor 第二模型循环风险
```

文件：

```text
backend/harness/entrypoint/runtime_facade.py
backend/harness/runtime/compiler.py
backend/harness/runtime/packet_assembler.py
backend/harness/loop/single_agent_turn.py
backend/harness/loop/task_executor.py
backend/harness/loop/task_executor_controller.py
backend/harness/runtime/task_run_control_gateway.py
```

动作：

```text
冻结 harness runtime spine 作为唯一运行主干
薄化 runtime_facade，把 active work control / task recovery dispatch 提取为明确 coordinator
审查 compile_task_execution_packet 的真实消费者
把普通 task-bound work 迁向 single_agent_turn + task overlay
task_executor 暂停新增普通语义能力，只保留已命名边界内的后台 runner 能力
active work continue 长期从 schedule task executor 改为 start/resume task-bound ordinary turn
```

完成条件：

```text
TaskRun 是持久工作资源，不是第二条对话主链
single_agent_turn 是默认模型执行入口
task_executor 不再独立解释当前用户输入
task_execution packet 不再作为普通 task-bound work 默认入口
TaskRunControlGateway 继续作为 task pause/stop/resume 控制入口
active work continue 不再通过 TaskRunControlGateway schedule task_executor
```

实施前待确认：

```text
1. 是否正式采用 TaskRun = 持久工作资源，single_agent_turn = 默认模型执行入口。
2. task_executor 的终局是删除，还是保留为严格受限的后台 runner。
3. task recovery resume 是否也从 schedule task_executor 迁向 task-bound ordinary recovery turn。
```

### Phase 5: Agent Control Network 从展示升级为治理诊断

状态：第三片已落地并完成本次收尾验收。后端 diagnostics 产出 missing edge status、diagnostic issue links 和 line governance canonical refs；前端只消费后端 refs，不再根据文案、数组顺序或缺省值猜测断点。

目标：

```text
拓扑图直接反映真实 active authority line
```

文件：

```text
backend/harness/runtime/context_contract/inspection_payload.py
backend/harness/runtime/context_contract/manifest.py
backend/harness/runtime/context_contract/diagnostics.py
backend/api/agent_control_network.py
frontend/src/components/workspace/views/agent-control-network/*
```

动作：

```text
节点读取 SystemAssetLine / ControlOutputLine
边读取 producer -> gateway -> assembler -> provider / decision -> permit -> executor -> observation
缺 owner、缺 activation、缺 terminal policy、缺 lane/index 都作为结构诊断显示
UI 不允许把缺线边画成正常连接
```

完成条件：

```text
agent-control-network 能回答：哪条线断了、断在输入端还是输出端、属于哪个 authority
诊断不再靠 downstream fallback 推断
```

### Phase 6: 清理旧链路和旧语义

状态：上下文主线已完成。当前已清理未声明 context kind 的 append 兜底、补准 runtime control signal tail 的 producer identity，并将旧 semantic_space 文档标为历史参考。`task_executor` 终局删除/降级、`task recovery resume` turn-bound 迁移、`runtime_facade` 围绕任务机制的进一步薄化不再计入本文收尾，单独进入任务机制专项。

目标：

```text
删除被新治理层替代的旁路和误导命名
```

文件：

```text
backend/harness/runtime/compiler.py
backend/harness/runtime/environment_prompt_controller.py
backend/prompt_composition/runtime_fragments.py
backend/runtime/context_management/design_docs/semantic_space/*
docs/context_physical_splicing_model.md
docs/context_physical_prefix_source_audit_report.md
```

动作：

```text
清理 compiler 内部重复投影
PromptSet / AgentRuntimeProfile 成为 prompt wiring 主入口
旧文档标注 archived 或更新术语
禁止 session memory / memory prefix / provider old context 混用
未声明 context kind 不允许 default append
runtime control signal observation 必须保留 producer / signal / observed refs
```

完成条件：

```text
active code 不再有第二套 prompt/context/control 决策入口
旧文档不会被误认为当前架构说明
新开发只需查 SystemAssetLine / ControlOutputLine / PhysicalContextInputs
新增 context kind 必须先经过 ContextSegmentKindDeclaration / SystemAssetLine
interrupt / runtime control signal 能作为 runtime_control_signal_tail 被下一轮读取，且不进入 confirmed old context
```

## 9. 文件级执行清单

| 文件 | 当前角色 | 动作 |
| --- | --- | --- |
| `backend/runtime/context_management/system_asset_lines.py` | 新文件 | 定义 SystemAssetLine、ContextLineState、ContextInputEnvelope |
| `backend/runtime/context_management/system_line_controller.py` | 新文件 | 统一 activation 和 diagnostics |
| `backend/runtime/context_management/context_segment_registry.py` | kind 声明 | 作为 SystemAssetLine draft 来源，补 owner/terminal/schema |
| `backend/runtime/context_management/context_segment_policy.py` | policy 解释 | 消费声明，不做未声明 fallback |
| `backend/runtime/context_management/context_pipeline.py` | 上下文主线 | 接入 ContextInputEnvelope，保持四段算法不变 |
| `backend/harness/runtime/context_message_producers.py` | producer 汇聚 | producer 返回 envelope，不直接自由写 message_specs |
| `backend/harness/runtime/compiler.py` | packet 编译聚合 | 瘦身为消费已决策 packet parts |
| `backend/harness/runtime/control_action_schema.py` | 控制 action schema | 增加 ControlOutputLine 声明 |
| `backend/harness/loop/admission.py` | action permit | 保持准入权威，不改写目标 |
| `backend/runtime/tool_runtime/tool_control_plane.py` | 工具执行 | observation 按 contract 回流 |
| `backend/harness/current_work_receipt.py` | active work receipt gate | 纳入 ControlOutputLine 前置凭证 |
| `backend/harness/recovery_receipt.py` | task recovery receipt gate | 纳入 resume_task_recovery 前置凭证 |
| `backend/harness/runtime/packet_context.py` | runtime packet 中心容器 | 承载 action surface / tool plan / operation availability |
| `backend/harness/runtime/packet_assembler.py` | action surface / operation availability owner | 禁止下游二次开放 action |
| `backend/harness/runtime/runtime_gateway.py` | runtime fact gateway | 保持事实记录和 drain，不升级为决策器 |
| `backend/harness/runtime/output_commit_authority.py` | final commit gate | 所有 assistant final 统一提交 |
| `backend/harness/runtime/task_run_control_gateway.py` | task 控制 gateway | pause/stop/resume 统一入口 |
| `backend/harness/entrypoint/runtime_facade.py` | 厚入口与 dispatch hub | 长期薄化为 adapter / dispatch coordinator |
| `backend/harness/loop/task_executor.py` | 历史重型 task execution loop | 收束第二模型循环，普通 task-bound work 迁回 single turn overlay |
| `backend/harness/loop/task_executor_controller.py` | executor schedule/recover | schedule 权力与 task overlay 目标对齐 |
| `backend/harness/runtime/context_contract/*` | 拓扑/诊断 | 读取真实 line declarations |
| `frontend/src/lib/store/runtime.ts` | public projection | 继续只保留 public projection，不产生 agent/provider context |

## 10. 迁移与切换规则

```text
不新增长期 v2 双跑
不在旧链路上包新壳
每个 phase 做 clean cutover
旧字段只可短期 read-only diagnostic，必须写 removal condition
如果新治理层无法解释某条线，应该显式报 structural gap
回滚方式是 revert 当前 phase，不是在 runtime 内长期保留旧路径
```

切换顺序：

```text
先声明 SystemAssetLine
再接 ActivationController
再改 producer envelope
再改 control output line
最后清理旧文档/旧字段/旧投影
```

## 11. 验证方案

不新增回归测试文件。验证方式以代码审查、结构探针、编译和固定端口真实运行为主。

### 11.1 静态探针

```text
rg "SystemAssetLine" backend/runtime/context_management
rg "ContextLineState" backend/runtime/context_management backend/harness
rg "ControlOutputLine" backend/harness/runtime
rg "physical_lane_for_spec" backend/runtime backend/harness --glob '!**/design_docs/**'
rg "runtime_memory_context.*CONTEXT_MEMORY_PREFIX" backend/runtime/context_management
rg "session memory.*provider_visible_context_prefix" backend docs
python -c "from runtime.context_management.context_segment_policy import context_segment_policy_for_spec; p=context_segment_policy_for_spec({'kind':'definitely_new_unregistered_kind'}); print(p.section, p.commit_policy, p.replay_policy)"
rg "compile_task_execution_packet|TaskExecutionModelActionRequest|_invoke_task_model_action" backend/harness
rg "resume_task_recovery|active_work_control" backend/harness
```

### 11.2 结构探针

输入资产：

```text
static prompt
current user
runtime memory hint
tool transcript
read evidence
dynamic recovery feedback
frontend public projection snapshot
```

期望：

```text
每个资产有 SystemAssetLine
每轮有 ContextLineState
只有 enabled line 进入 ContextInputEnvelope
frontend projection 不进入 ContextInputEnvelope
PhysicalContextInputs 四段稳定
ControlOutputLine 能追踪 permit/executor/observation
HarnessControlSpineLine 能追踪 packet/admission/permit/gateway/commit
task_executor 不再新增普通 task-bound 语义入口
```

### 11.3 真实运行验证

固定端口：

```text
frontend: http://127.0.0.1:3000
backend:  http://127.0.0.1:8003
api:      http://127.0.0.1:8003/api
```

场景：

```text
新会话第一轮
连续多轮会话
tool call + follow-up
用户中途 steer
前端断线/重连
task recovery
permission denial
provider success 后下一轮 replay
active work continue
task-bound ordinary turn
```

检查：

```text
agent-control-network 能定位每条线
上下文中枢和控制器两端都有 line id
旧上下文来自 physical prefix frame，不来自 memory summary
public projection 不污染 provider context
denied/failed action 以 ObservationFeedback 回流
assistant final 只从 OutputCommitAuthority 出口提交
RuntimeGateway 事实不会替代模型决策
```

## 12. 禁止事项

```text
不允许系统资产没有线路声明
不允许先插线再过滤 disabled 资产
不允许在插线后重排或重分段
不允许让 summary/session memory/working memory 替代 confirmed old provider context
不允许 frontend projection 生成 provider/model context
不允许 control action 绕过 ActionPermit
不允许 ActionPermit 替 agent 换目标
不允许 executor 静默吞失败
不允许 task_executor 扩展成第二条普通模型主链
不允许 active work continue 永久绑定 executor schedule
不允许 RuntimeGateway 升级成 intent 决策器
不允许旧 flow terminal text 绕过 OutputCommitAuthority
不允许旧主链路以兼容名义长期保留
不允许把开发说明写给 agent 当 prompt
不允许用测试文件伪造治理完成
```

## 13. 预期结果

完成后，系统应具备这些性质：

```text
1. 每个系统资产都有静态线。
2. 每轮是否通线由 ContextLineState 明确控制。
3. 上下文中枢只接收 enabled 输入线。
4. 四段物理算法仍只有一套。
5. agent 输出控制系统也有 ControlOutputLine。
6. permission / admission / executor / observation 全链可追踪。
7. agent-control-network 能定位真实断线点。
8. frontend projection、memory hint、provider old context 不再混淆。
9. compiler 从多权威聚合点逐步瘦身为 packet 编译层。
10. 新资产接入只需声明线和 producer，不需要改多个下游排序分支。
11. harness runtime spine 保持唯一运行主脊柱。
12. task_executor 不再作为普通 task-bound 工作的第二模型循环。
13. active work / task recovery / final commit 都能追踪到各自凭证和权威出口。
```

## 14. 审阅重点

实施前需要确认：

```text
1. 是否接受 SystemAssetLine 作为所有系统资产的静态线路声明。
2. 是否接受 ContextLineState 作为每轮 activation 的唯一动态开关。
3. 是否接受 ControlOutputLine 把 agent 输出控制端也纳入线路治理。
4. 是否接受 ContextCandidateGateway 作为 producer 到 PhysicalContextInputs 的唯一入口。
5. 是否接受 agent-control-network 从展示拓扑升级为结构诊断拓扑。
6. 是否接受 compiler 长期瘦身，不再直接拥有多套 context/prompt/control 投影权威。
7. 是否接受旧文档/旧字段只保留为 archived/read-only diagnostic，不作为兼容主路径。
8. 是否接受 harness runtime spine 是长期治理控制输出端的主实现。
9. 是否接受 `TaskRun = 持久工作资源，single_agent_turn = 默认模型执行入口`。
10. 是否接受 `task_executor` 冻结新增普通语义能力，并进入降级或删除专项治理。
11. 是否接受 task recovery resume 继续从 executor schedule 迁向 task-bound ordinary recovery turn。
```

## 15. 2026-07-01 当前切片收尾验收

### 15.1 收口裁决

本次收尾关闭的是“线路治理、诊断投影、active work continue 切线”切片。当前切片已经把系统资产输入线、动态 activation、候选上下文入口、控制输出线、harness runtime spine 契约和 agent-control-network 诊断投影接到同一治理模型，并把 active work continue 从 detached task_executor schedule 迁回 turn-bound ordinary action。

明确不在本次收尾中执行的内容：

```text
不删除 task_executor
不薄化 runtime_facade
不迁移 task recovery resume
不把 Phase 6 旧链路清理伪装成本次完成
```

这些内容属于后续高风险专项，因为它们会跨图节点、TaskRun、恢复入口、后台 worker 和输出提交边界，必须单独审查和确认。

### 15.2 已接通的核心线路

| 线路 | 当前接线 | 收尾状态 |
| --- | --- | --- |
| 系统资产静态线 | `SystemAssetLine` inventory -> `line_governance.system_asset_lines` | 已接通 |
| 每轮动态开关 | `SystemLineController` -> `ContextLineState` -> enabled specs | 已接通 |
| 候选上下文入口 | producer spec -> `ContextCandidateGateway` -> `ContextInputEnvelope` | 已接通 |
| 四段物理模型 | `PhysicalContextInputs` -> 唯一 assembler -> provider payload diagnostics | 已保持单权威 |
| 控制输出线 | `ControlOutputLine` -> `AdmissionDecision` -> `ActionPermit` -> observation/final commit refs | 已接通 |
| harness 控制脊柱 | `HarnessControlSpineLine` -> `ControlOutputLine` ref | 已接通 |
| task executor 定位 | `harness_spine.task_executor_background_runner` | 已冻结为后台 runner |
| active work continue | 当前 `single_agent_turn` 普通动作面；`active_work_control` 不再提供 continue 动作 | 已切断旧调度线 |
| 结构断线诊断 | diagnostics issue -> affected edge/node/line/action/contract/governance ref | 已接通 |
| 前端治理投影 | `/agent-network` 读取后端 status 与 refs | 已接通 |
| 未声明 context kind | `context_segment_policy_for_spec` -> `undeclared_context_segment` -> `SystemLineController` blocked | 已收口 |
| runtime control signal 回流 | `single_agent_turn.runtime_control_boundary` -> `RuntimeGateway.publish/mark_observed` -> `runtime_control_signal_tail` | 已接通 |
| 旧语义文档 | `design_docs/README.md` + `semantic_space/README.md` 标明历史参考与当前术语 | 已归档 |

### 15.3 固定端口验收记录

固定节点保持项目约定：

```text
frontend: http://127.0.0.1:3000
backend:  http://127.0.0.1:8003
api:      http://127.0.0.1:8003/api
```

`GET http://127.0.0.1:8003/api/agent-control-network` 当前验收结果：

```text
nodes = 23
edges = 28
system_asset_line_count = 84
context_line_state_count = 84
control_output_line_count = 7
harness_control_spine_line_count = 7
harness_runtime_spine_contract_count = 1
system_asset_issue_count = 0
diagnostic_issue_count = 0
diagnostic_issue_link_count = 0
missing_status_edge_count = 0
non_connected_edge_count = 0
undeclared_context_kind_policy = dynamic_tail / never_commit / undeclared_context_segment_blocked
active_work_control_executor_ref = harness.entrypoint.runtime_facade.current_work_control
```

### 15.4 后续专项入口

后续如果继续推进长期治理，入口不是在当前切片里继续加补丁，而是单独拆成这些计划：

```text
1. task_executor 终局专项：删除、降级或保留为严格后台 runner。
2. task recovery resume 迁移专项：从 executor schedule 迁向 task-bound ordinary recovery turn。
3. runtime_facade 任务机制薄化专项：把任务入口层从厚 dispatch hub 收束为 adapter/coordinator。
```
