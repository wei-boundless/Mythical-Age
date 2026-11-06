# Harness Runtime Spine Authority Index

创建日期：2026-06-30

状态：当前重构主索引。本文用于约束后续计划和实现：先复用 `harness` 已有运行脊柱，再做只读投影、清洗旧链路和前端展示，不新增第二套 runtime owner。

2026-06-30 Phase 5 更新：普通 single-agent turn recovery 双权威已清理。`select_session_continuation` 只保留 task recovery boundary、recent outcome 和 diagnostics 价值；普通 turn 的模型可见恢复段只由 `runtime.turn_memory.build_turn_memory_recovery_context` 产出。

2026-06-30 Phase 5 命名收口：task recovery/control 显式动作面统一为 `resume_task_recovery`，payload 统一为 `task_recovery_resume`；旧 `resume_recoverable_work` 不再作为模型动作、回执 operation key、parser 字段或测试契约存在。

## 1. 核心裁决

本项目已经存在单 agent runtime 主脊柱，不应再新造 `AgentControlNetwork` 这类 runtime owner。

`/agent-network` 后续应表达为：

```text
harness runtime spine
-> runtime topology projection
-> read-only API payload
-> frontend inspector
```

它只能读取和展示真实运行结构，不能决定 intent、不能授权工具、不能组 prompt、不能写 TurnMemory、不能提交输出。

## 2. 术语边界

| 术语 | 正式含义 | 禁止误用 |
| --- | --- | --- |
| `SingleAgentRuntimeHost` | 单 agent runtime 服务宿主，持有 stores/gates/services | 不能被新的 projection 或展示层替换 |
| `AgentRuntimeServices` | loop/executor 的显式 service table | 不能绕过它回调 facade 去决定 agent 意图 |
| `RuntimeGateway` | `RuntimeEventLog` 之上的 typed control fact gateway | 不决定 intent、不授权、不执行、不组包、不提交 |
| `RuntimeEventLog` | runtime event 和 control signal 的记录/回放底座 | 不是模型记忆，不替代 TurnMemory |
| `TurnMemoryStore` | turn 间热账本，记录 Present/Future 未封存状态 | 不写 sealed history，不和 continuation recovery 双权威 |
| `turn` | 当前用户输入、模型裁决、动作授权、task 接入和输出提交的唯一节拍 | 不能被 task execution 或 continuation record 绕过 |
| `task` / `task_run` | 由某个 turn 申请或重新接入的跨 turn 持久工作资源 | 不能脱离 turn 自行解释用户意图，不能成为第二条对话主链 |
| `SystemWiringManifest` | 已解析 runtime profile / operation authorization / environment policy 的能力编译投影 | 不能被旧 `context_policy/memory_policy` 在下游重新裁决 |
| `ContextCapabilityProfile` | `SystemWiringManifest.compiled.context_capability_profile` 的执行用 profile | 只执行显式 enabled/disabled groups，不读取旧 policy bridge |
| `ProviderCacheBus` | provider cache 日志和前缀健康展示入口 | 不能用总 hit rate 替代 prefix coverage |
| `PrefixStateRecord` | prefix continuity / generation / reset 热状态账本 | 不能再从 baseline/stability 双文件读取 previous state |
| `ProviderMessageReplayContract` | provider message byte-preservation 契约，覆盖 physical prefix frame replay 与 provider protocol replay | 不能作为权限 bypass 或旧上下文兼容入口 |
| `runtime topology projection` | 只读诊断投影，供 API/frontend inspector 使用 | 不能成为新执行框架 |

`AgentControlNetwork` 只允许作为页面/产品层标签或诊断图名称；工程实现应优先沿用已有 `harness.runtime.context_contract.inspection_payload` / diagnostics 体系，必要时新增的也只能是 read-only projection module。

## 3. 当前主脊柱

```text
HarnessRuntimeFacade
-> assemble_runtime
-> select_session_continuation(diagnostics/task recovery boundary) + build_turn_memory_recovery_context
-> build_turn_input_facts
-> decide_current_work_boundary
-> run_single_agent_turn
-> _start_turn_runtime + TurnMemoryStore.create_or_get_turn
-> RuntimeCompiler.compile_single_agent_turn_packet
-> RuntimeGateway.publish_evidence_projection
-> ModelRuntime
-> model_action_request_from_payload
-> decide_model_action_lifecycle
-> AdmissionDecision
-> ActionPermit
-> RuntimeToolControlPlane.invoke
-> tool observations / runtime control signals
-> OutputCommitAuthority
-> TurnMemoryStore commit/final refs
-> RuntimeEventLog / RuntimeStateIndex / frontend stream replay
```

## 4. Authority 表

| 文件/模块 | 当前职责 | 权力层级 | 后续动作 |
| --- | --- | --- | --- |
| `backend/harness/entrypoint/runtime_facade.py` | API adapter，装配 runtime，选择分支，调用 single-agent loop | observe / dispatch | 已移除普通 turn 恢复的旧 `recoverable_work` 写入；continuation 只做 task recovery boundary/recent outcome/diagnostics |
| `backend/harness/runtime/single_agent_host.py` | 持有 event log、gateway、ledger、stores、tool control plane、operation gate、TurnMemory、monitor | runtime spine owner | 保留为唯一服务宿主 |
| `backend/harness/runtime/services.py` | 显式传递 loop/executor 所需服务 | service table | 保留，禁止新增隐式 service locator |
| `backend/harness/runtime/request_facts.py` | 记录用户输入和候选事实，不判断意图 | observe | 已移除旧 `recoverable_work_candidate`，保留 active work/recent outcome facts |
| `backend/harness/runtime/packet_assembler.py` | 生成 packet context、action surface、tool plan、file evidence projection | assemble | 已移除旧 continuation 派生的 `resume_task_recovery` 普通 turn 动作面 |
| `backend/harness/runtime/compiler.py` | 构造模型 packet、prompt composition、dynamic/runtime projection | assemble / present-to-model | 已删除 `recoverable_work` 模型可见投影，只投影 `turn_memory_recovery` |
| `backend/harness/runtime/runtime_gateway.py` | 发布、观察、消费 runtime control facts | record / drain | 保留为 control fact gateway，不升级为 runtime owner |
| `backend/harness/loop/single_agent_turn.py` | turn 执行循环、工具批次、runtime control signal、最终提交调用 | execute / recover boundary | 保留主循环，继续通过 admission/permit/control plane 执行 |
| `backend/harness/loop/model_action_protocol.py` | 解析模型动作合同 | normalize | `resume_task_recovery` 只服务 task recovery/control，不作为普通 turn 恢复入口 |
| `backend/harness/loop/admission.py` | 判定模型动作是否准入 | authorize | 保留为动作准入层 |
| `backend/harness/loop/action_permit.py` | 生成并校验工具执行 permit | authorize | 保留为工具权限身份 |
| `backend/harness/loop/execution_kernel.py` | 连接 admission、permit、tool invocation identity、lifecycle events | authorize / record | 保留，不绕过 permit |
| `backend/runtime/tool_runtime/tool_control_plane.py` | 真实工具执行控制面 | execute | 保留为工具执行入口 |
| `backend/harness/runtime/output_commit_authority.py` | 清洗 final text、commit gate、commit event | commit | 保留为唯一 assistant final commit authority |
| `backend/runtime/turn_memory/*` | 热账本、checkpoint、recovery decision、session projection | record / recover | 保留为普通 turn 间恢复唯一权威 |

## 5. 关键连线矩阵

| line id | producer -> consumer | payload identity | authority | 状态 |
| --- | --- | --- | --- | --- |
| `facade-to-host` | `HarnessRuntimeFacade` -> `SingleAgentRuntimeHost` | runtime host instance | `harness.entrypoint.runtime_facade` | connected |
| `host-to-services` | `SingleAgentRuntimeHost` -> `AgentRuntimeServices.from_runtime_host` | host-owned stores/gates | `harness.runtime.services` | connected |
| `request-to-facts` | API request -> `TurnInputFacts` | `session_id` + `turn_id` | `harness.runtime.turn_input_facts` | connected |
| `facts-to-boundary` | `TurnInputFacts` -> current work boundary decision | turn facts | `harness.entrypoint.current_work_boundary` | connected |
| `facade-to-loop` | `_run_single_agent_turn` -> `run_single_agent_turn` | `turn_id` + `turn_run_id` | `harness.loop.single_agent_turn` | connected |
| `turn-start-to-memory` | `_start_turn_runtime` -> `TurnMemoryStore.create_or_get_turn` | `session_id` + `turn_id` | `runtime.turn_memory` | connected |
| `compiler-to-packet` | `RuntimeCompiler` -> `RuntimeInvocationPacket` | `packet_id` | `harness.runtime.compiler` | connected |
| `packet-to-gateway-evidence` | packet context -> `RuntimeGateway.publish_evidence_projection` | `runtime_invocation_packet_ref` | `harness.runtime.runtime_gateway` | connected |
| `model-to-action` | provider/model response -> `ModelActionRequest` | `request_id` + `turn_id` | `harness.loop.model_action_request` | connected |
| `action-to-admission` | `ModelActionRequest` -> `AdmissionDecision` | `action_request_ref` | `harness.loop.admission` | connected |
| `admission-to-permit` | `AdmissionDecision` -> `ActionPermit` | `permit_id` + `action_request_ref` | `harness.loop.action_permit` | connected |
| `permit-to-tool-control` | `ActionPermit` -> `RuntimeToolControlPlane.invoke` | `invocation_id` + `tool_call_id` | `runtime.tool_runtime.tool_control_plane` | connected |
| `control-signal-to-gateway` | turn runtime control boundary -> `RuntimeGateway.publish/mark_observed` | `runtime_control_signal_ref` | `harness.loop.single_agent_turn.runtime_control_boundary` | connected |
| `final-to-commit` | final answer -> `OutputCommitAuthority.commit_async` | `run_id` + `turn_id` | `harness.runtime.output_commit_authority` | connected |
| `commit-to-turn-memory` | commit result -> `TurnMemoryStore.record_commit_result` | `session_id` + `turn_id` | `runtime.turn_memory` | connected |
| `turn-memory-to-recovery` | `TurnMemoryStore` -> `build_turn_memory_recovery_context` | latest recoverable turn | `runtime.turn_memory.recovery_context` | connected |

## 6. 当前风险

### P1. 普通 turn recovery 双权威已收口

2026-06-30 已完成代码清理：

- `runtime_facade.py` 不再把非终态 continuation record 放入 `session_context["recoverable_work"]`。
- `request_facts.py` 不再保存 `recoverable_work_candidate`。
- `packet_assembler.py` 不再根据旧 continuation record 开放 `resume_task_recovery` 普通 turn 动作。
- `compiler.py` 不再投影 `recoverable_work` runtime delta，也不再把 `recovery_boundary_receipt` 暴露为普通 turn 模型可见动态段。
- agent contract feedback 的模型可见动作要求只接受 `next_action_requirements`；旧 `required_action_protocol` 不再作为兼容输入。

当前裁决：普通 turn 恢复只看 `TurnMemoryRecoveryContext`；旧 continuation record 降级为 task recovery boundary、recent outcome 或 diagnostics。

### P1. `/agent-network` 静态图是假权威

2026-06-30 Phase 1/2 已处理：前端页面已改为读取只读 runtime topology projection，不再内置 core graph 静态权威。用户补充已降级为 annotation layer，不能覆盖 core edge/status/authority。

### P1. 缓存健康不能看总命中率

缓存判断必须以 expected prefix coverage、under-read tokens、first missing expected prefix identity 为准。`77.19%` 总 hit rate 只能做背景指标，不能证明前缀稳定命中。

2026-06-30 更新：`prompt_cache_baselines.jsonl` / `prompt_stability.jsonl` 已退出 active write/read path；`prefix_state.jsonl` 是 previous/continuity/reset 权威，`provider_cache_bus.jsonl` 是 provider 实测缓存展示权威。

2026-06-30 继续更新：`cache_baseline.py` 已从 active code 删除；`PrefixStateReporter` 直接计算 continuity、generation、changed_tiers 和 provider prefix seal。previous resolver 遇到 latest invalidated state 时返回 `previous_state=None` 并保留 generation，不会跨 reset 继续连接更早 active state。

2026-06-30 再更新：`stability_report.py` / `stability_models.py` 已从 active code 移除；当前只保留 `PrefixStateDiffReporter` / `PrefixStateDiffReport` 作为 `PrefixStateReporter` 的 diff helper，不再使用 `PromptStability*` 命名表现第二状态账本。

2026-06-30 继续清理：`PrefixStateRecord` 的 provider prefix continuity 不再读取旧 `diagnostics.baseline.provider_prefix_seal`；`provider_lane.py` 删除显式 `legacy_unscoped` alias，未知 lane 统一归入 canonical `unscoped`。

2026-06-30 prefix state 内部收口：`memory_segment_hash` 不再用文本包含关系猜 memory 段；只接受标准化 segment identity，并通过 `agent_domain=ContextMemoryDomain` 防止 task state 被混入 memory state。

2026-06-30 prefix state memory 身份继续收口：`memory_segment_hash` 不再接受 `authority_class`、`content_source` 或 `authority=memory_system.*` 作为未知段进入 memory hash 的资格。memory 身份只来自显式 memory kind、registry `CONTEXT_MEMORY` capability、`agent_domain=ContextMemoryDomain` + selected memory slot，或 `semantic_commit_class=selected_memory_context`。

2026-06-30 provider lane 收束：`provider_lane_from_accounting_context()` 不再根据 `source/call_kind/request_id` 字符串猜 lane，只读取显式 `accounting_context.provider_lane` 或 `prompt_manifest.provider_lane`，接口也不再接受 `call_kind`。`context_pipeline.provider_lane_from_model_selection()` 不再构造伪 accounting context，只读取 `model_selection.provider_lane`。Utility 和 semantic compaction 已写入显式 lane；未接入的调用保持 `unscoped` 并进入后续显式接线清单。

2026-06-30 provider lane 下游继续收口：`model_runtime` 中 `unplanned_model_call` anomaly severity 不再通过 `source` 或 stream `call_kind` 判断 agent runtime 形态，只由显式 provider lane 决定。

2026-06-30 context usage meter 收口：`ContextUsageMeter` 不再通过 `request_id` / `packet_ref` 的 `modelreq:rtpacket` 字符串形状识别 agent runtime token observation，也不再用 `cache_metric_scope` 作为身份。上下文压力候选记录只接受显式 provider lane。

2026-06-30 provider-visible turn 身份收口：`ProviderVisibleContextLedger` 的成功确认由 `model_runtime.py` 显式传入 `accounting_context.turn_id`，ledger entry 和 provider success anchor 记录 `confirmed_turn_id` / `turn_id`。session cutoff 截断不再解析 `modelreq:rtpacket:*` request id，旧 request id 只保留为 provider request 审计字段。

2026-06-30 prefix identity replay 生命周期收口：`context_prefix_identity` 不再根据 `kind.startswith("physical_prefix_frame_")`、`source_kind` 或 `content_source` 猜测 confirmed frame replay。生命周期只接受 `provider_message_replay_contract` 的显式 replay 契约；`provider_protocol_replay` 与 `confirmed_frame_replay` 分开表达，但两者都保持 expected read。

2026-06-30 semantic visibility 收口：`physical_context_plan` 和 `provider_visible_context_ledger` 不再通过 `semantic_commit_class.startswith("provider_visible_replay_only")` 推断 historical-only。历史可见性只读 `semantic_visibility`、`provider_visible_replay_only`、`context_memory_visible=false` 或 `historical_only_on_replay` 等显式字段。

2026-06-30 provider message replay 契约收口：`context_pipeline.sealed_provider_visible_replay_spec()`、`physical_context_assembler._current_append_specs()` 与 `context_segment_policy` 的 replay section 分类不再各自拼 `provider_visible_payload_authority/context_replay_policy/provider_visible_history_status` 条件，统一委托 `provider_message_replay_contract`。capability filter、section 分类、assembler current append 分流、compiler sanitizer 和 materializer byte-preserve 使用同一个 replay 判定 owner。

2026-06-30 provider protocol replay explicit-only：`provider_message_replay_contract` 不再把 `content_source=runtime.provider_protocol_replay` 当作 byte-preserve replay 授权。`content_source` 只描述来源；provider protocol replay 必须由 `provider_protocol_replay=True`、`context_replay_policy=provider_protocol_replay`、`provider_visible_history_status=provider_protocol_replay` 或 `provider_message_replay_authority=runtime.provider_protocol.replay` 这类显式契约字段声明。

2026-06-30 继续更新：`PromptSegmentPlan -> ProviderPayloadSegment -> CachePlanRecord -> PrefixCacheHealth -> ProviderCacheBusRecord` 已打通 `context_contract_node_ref`、`context_contract_edge_refs`、`agent_domain`、`connection_contract_ref`、`control_signal` 身份链。缓存 under-read 的 first missing identity 可以回到 ContextContract node 和具体 connection edge，而不是停在 hash/segment id。

### P2. ContextCapability 旧 policy bridge 已移除

2026-06-30 更新：`context_capability_policy.build_context_capability_profile()` 不再读取旧 `context_policy` / `memory_policy` / `prompt_policy` 并翻译成 disabled groups。能力裁决只来自显式 `ContextCapabilityProfile`，主入口由 `harness.runtime.assembly` 编译 `system_wiring_manifest.compiled.context_capability_profile`；`context_capability_policy` 只执行该 profile，不再拥有第二个 policy 决策入口。

### P2. ContextContract heuristic 已从主链路移除

2026-06-30 更新：`authority_rules.py` 已改为 ContextContract 标准字段适配器，只消费 `context_segment_registry`、`context_segment_policy`、physical lane 和 prefix identity。它不再通过 kind/cache_role 字符串包含关系猜控制域；缺失 `agent_domain/control_signal/connection_contract_ref` 时只写 diagnostics。`ContextContractNode` 与 `context_contract_inspection` 已移除 `semantic_kind/semantic_layer/semantic_time`，主分组改为 `agent_domain/control_layer/time_scope/physical_lane/connection_contract_ref`。

2026-06-30 继续更新：`ContextContractManifest.edges` 已从单一顺序边扩展为 `agent_visible_order`、`physical_lane_projection`、`provider_payload_binding`、`cache_health_binding` 四类标准连接契约。每条边必须带 `edge_id`、payload identity/schema、authority、transport/store、consumer、failure route、cache expectation、connection contract、physical lane 和 control signal；缺失时进入 diagnostics。

2026-06-30 source_kind 控制旁路收口：`authority_rules.py` 不再通过 `declaration.source_kind` 映射 `agent_domain`；`prompt_composition.slot_policy` 不再维护 `source_kind -> layer/dynamic_tier/authority_class` 旁路表。`source_kind` 只保留为来源身份和诊断统计，控制域来自 explicit metadata、registry capability、provider transport lane、四段 section 和 registry 声明。

2026-06-30 section 裁决收口：`context_segment_policy.py` 不再通过 `prompt_assembly_dynamic_tier/dynamic_tier` 或 `cache_role=session_stable/cacheable_prefix` 反推 `context_cache_section`。四段物理归属只接受 explicit metadata、registry/defaults、declared kind 集合和调用方 `default_section`；registry 中所有 context segment kind 已补齐显式 section。

2026-06-30 dynamic metadata validation 收口：`harness.runtime.compiler` 不再通过 `kind.startswith("dynamic")` 判断段是否需要 dynamic context report。动态段校验只读 `cache_role=volatile` 或 `context_segment_policy_for_spec(...).section == dynamic_tail`；sealed replay 例外统一委托 `provider_message_replay_contract`。

2026-06-30 task contract intake 收口：versioned compact task start intent 名称退出 active code 和 agent-facing guidance，统一为无版本后缀的 `compact_task_start_intent`。`task_contract_seed`、`goal_contract`、`plan_contract`、`environment_contract`、`user_visible_goal`、`task_run_goal` 旧输入不再被系统迁移为 `task_run_contract_seed`；只能作为 validation error / repair diagnostic。`task_lifecycle` 和 `task_contract_manifest` 不再生成旧 seed 到 Work Mode 的自动投影。

2026-06-30 runtime identity 命名收口：dynamic context replacement 不再使用 `observation_projector.v3`、`tool_result_projector.v3` 或 `projector_version` 表达投影身份，统一改为稳定 `projector_id`。provider-visible ledger entry hash salt 不再携带 `_v3` 后缀，避免把历史版本号暴露成运行时身份。

2026-06-30 runtime identity 继续收口：自有主链路中的 `.v1` / `_v1` 后缀已从 chat live protocol、assistant stream frame identity、context recovery package、runtime cache manifest、file observation/read evidence/read file window、run monitor、public read-file window projection 和 DeepSeek provider-visible adapter contract 中移除。`deepseek_v4` 保留为模型族事实，不作为本项目运行契约版本。

2026-06-30 runtime identity 字段继续收口：`contract_version` 退出 task/file evidence 合同输出，统一为 `contract_id`。稳定 schema 身份字段统一为 `frame_schema_id`、`package_schema_id`、`manifest_schema_id`、`projection_schema_id`；runtime spine 的落盘结构修订统一为 `record_schema_revision` 或 `ledger_schema_revision`。普通 single-agent 主链路不再输出 `schema_version` 作为身份字段，graph/project/personality 等外围模型暂不纳入本轮清洗。

2026-06-30 runtime projection 裁剪收口：`session_runtime_timeline` 的 live projection 上限由 `_bounded_projection_frames()` 单点执行。裁剪按最近 `projection_roots` 选择，并在预算内携带同 tool lifecycle closure；旧全量根帧预选会绕过 frame limit，已删除未使用的 lifecycle closure 选择 helper。

2026-06-30 runtime interruption 命名收口：`semantic_terminal` 退出 active diagnostics 和 public replay 判断，改为 `agent_decision_terminal`。recoverable orphaned run 表达为 `recoverable=true + agent_decision_terminal=false`，`stream_replay.ensure_terminal_reconciliation_event()` 不再为这类运行时中断补 public `turn_completed`。`semantic_actions` 改为 `allowed_action_types`，`semantic_decision_owner` 改为 `decision_owner`。

2026-06-30 runtime control role 命名收口：single-agent follow-up 段元数据不再生成 `runtime_control_semantic_role`，统一为 `runtime_control_role`；prompt accounting serializer 不再写入无 active producer 的 `semantic_role` metadata。task graph 外围模型的 `semantic_role` 暂不纳入单 agent runtime spine 清理。

2026-06-30 context memory visibility 命名收口：`semantic_memory_visible` / `semantic_memory_commit_policy` 已退出 active runtime metadata。运行时动态尾部使用 `context_memory_visible=false` / `context_memory_commit_policy=never_commit`；physical frame replay 只使用 `memory_commit_policy` 表达 replay-only 提交策略。

2026-06-30 tool transport 收口：provider-native 工具调用失败后自动转 JSON action object 的执行层 fallback 已删除。工具 transport 只由 `ToolCallContract.ordinary_tool_submission` 决定，`action_object_tool_fallback_enabled/tool_fallback_enabled` 旧开关不再被读取。

2026-06-30 provider-visible cursor 收口：`last_provider_success_anchor` / `last_success_anchor_id` 旧别名已删除，当前 provider-visible 游标只读写 active anchor 字段。

2026-06-30 recovery action surface 收口：`resume_task_recovery` 不再出现在 turn action request 的缺省可见动作集合中；它只由 task recovery/control 的显式 allowed action surface 开放。

2026-06-30 recovery receipt 投影收口：普通 single-agent turn compiler 不再读取 `session_context["recovery_boundary_receipt"]`，也不再把 `recovery_boundary_receipt` 写入 `single_turn_dynamic_refs`。continuation recovery receipt 只作为 task recovery/control 的内部边界凭据存在，不能成为普通 turn 的第二恢复 prompt 权威。

2026-06-30 compression budget 收口：`CompressionBudgetPlanner._is_hard_required()` 不再读取 `authority_class`，也不再把 `cache_role=session_stable` 单独当作硬保留条件。硬保留只来自显式 `compression_role=preserve`、expected-read 物理前缀 lane、registry/context capability 的 `contract/control/feedback` member、以及显式 contract/recovery slot。

2026-06-30 prompt segment authority_class 降级：`CanonicalPromptSerializer._authority_class()` 不再根据 `kind`、`role=user`、`compression_role` 字符串猜测 contract/user/runtime/evidence 类别；只接受上游显式标准枚举，否则为 `unknown`。`context_prefix_identity` 不再把 `authority_class` 写入 origin authority，`context_commit_record` 的 tool transcript 投影也不再把 `authority_class=append_only_tool_transcript_delta` 当作识别入口。

2026-06-30 authority_class active code 退场：`authority_class` 已从 prompt composition slot/load plan、context segment registry、prompt accounting segment model/serializer/cache diagnostics、harness compiler/context producers/follow-up specs、memory maintenance prompt specs 和 ContextContract refs 中移除。active Python 代码不再生成、读取、转发或展示该旧类别字段；历史文档中只保留问题记录。

2026-06-30 fragment materialization source 收口：`prompt_composition.fragments` 不再通过 `content_source.startswith("runtime.")` 或 `content_source=runtime.provider_protocol_replay` 决定使用 message spec / fallback model message。是否 byte-preserve 统一读取 `provider_message_replay_contract.provider_message_byte_preservation_required()`；`content_source` 只保留来源描述。

2026-06-30 ContextCapability prompt resource 收口：`context_capability_policy` 的 prompt rule 能力归属只读显式 `context_capability_group`、内置 rule kind 精确目录、category/subtype 和 `environment_guidance_slot`。未知 `rule_kind` 不再因为包含 `tool/permission/subagent` 或 `coding.` 前缀获得特权能力组；contract slot 也不再通过 `tool` 子串或 `tool_` kind 前缀映射 `TOOL_CONTEXT`，只读显式 slot 目录、semantic slot 目录或 registry capability。

2026-06-30 prompt assembly stable gate 收口：`prompt_library.assembly` 不再把 `prompt_ref.startswith("system.foundation.")` 或 `prompt_ref.startswith("runtime.")` 当作 capability gate bypass。稳定必入资源只由资源自身显式 metadata 表达：`builtin_runtime_prompt=True`，或 `category=system/subtype=foundation/source_type=builtin_system_foundation_prompt`。

2026-06-30 prompt rule diagnostics 收口：`prompt_library.rules` 的 coverage 不再通过 `rule_kind.startswith("system.foundation")` 判断 foundation prompt。`PromptSection.metadata` 透传资源 `source_type`，foundation coverage 只接受 `category=system/subtype=foundation/source_type=builtin_system_foundation_prompt`。

2026-06-30 system wiring prompt gate 收口：`harness.runtime.assembly` 不再把 `prompt_ref.startswith("runtime.")` 当作 diagnostic-only gate bypass。`system_wiring_manifest.compiled.prompt_resource_gates` 必须忠实记录系统组声明的 prompt resource；运行时协议/规则身份只由 prompt resource 的 `category`、`builtin_runtime_prompt`、`prompt_rule.rule_kind` 和显式 system group 连接表达。

2026-06-30 prefix/provider-visible identity source label 收口：`context_prefix_identity`、`provider_visible_context_ledger`、`serializer`、`provider_payload` 和 `context_contract.authority_rules` 不再把 `content_source/source_kind/context_source_kind` 转译为 origin authority 或 provider-visible item key。prefix identity 与 provider-visible ledger identity 只接受显式 origin authority、显式 semantic source、source_ref/kind fallback 和 prefix identity 传递；来源标签只保留为来源描述/审计。

### P2. Provider message replay 旧旁路已收口

2026-06-30 已删除 `runtime.shared.protected_context`。byte-preserve 判断由 `runtime.context_management.provider_message_replay_contract` 统一提供，只有 `physical_prefix_frame_replay` 和 `provider_protocol_replay` 两类 contract 能要求 compiler/materializer 保留原始 provider message bytes。capability filter 和 sanitizer diagnostics 不再使用 `bypassed_for_protected_old_context` / `current_turn_exact_old_context`。

## 7. 文档索引关系

| 文档 | 用途 | 当前裁决 |
| --- | --- | --- |
| `harness_runtime_spine_authority_index_20260630.md` | 当前 harness 主脊柱和权力索引 | 主索引 |
| `agent_control_network_architecture_cleanup_plan_20260630.md` | 大清洗分阶段计划 | 需按本文修订措辞 |
| `agent_control_network_backend_plan_20260630.md` | `/agent-network` 后端只读投影计划 | 需按本文修订为 inspection facade |
| `turn_heartbeat_hot_journal_rewrite_recover_steer_authority_plan_20260629.md` | TurnMemory 热账本设计依据 | 保留为 TurnMemory 细节来源 |
| `context_prefix_authority_unification_refactor_plan_20260629.md` | prefix identity 和缓存权威设计 | 保留为缓存前缀来源 |
| `cache_prefix_hit_audit_report_20260629.md` | 最新缓存命中问题分析 | 保留为 cache 诊断证据 |
| `cache_prefix_identity_format_audit_report_20260629.md` | prefix 格式与成熟 agent 对比 | 保留为 prefix 命名来源 |
| `semantic_space/*` | 语义空间研究和提示词设计 | 作为参考，不覆盖 harness runtime spine |

## 8. 后续实施切片

1. 文档修订：把所有新运行中枢表述改为 `runtime topology projection / inspection facade`。
2. 后端投影：优先扩展现有 context contract inspection/diagnostics；只有无法容纳 session evidence 时再新增只读 projection module。
3. 前端接线：`/agent-network` 读取后端 payload；本地补充降级为 annotation。
4. 恢复清洗：已完成普通 turn `recoverable_work` 模型可见恢复权威移除，只保留 TurnMemory recovery。
5. 缓存清洗：UI/cache health 只读 ProviderCacheBus + PrefixCacheHealth verdict，不再用总 hit rate；prefix previous/reset 只读写 PrefixState。

## 9. 验收不变量

```text
没有第二 runtime owner
没有第二 tool authorization path
没有第二 assistant final commit path
没有第二普通 turn recovery authority
没有前端自造 core graph authority
没有总 hit rate 伪装 prefix health
没有 baseline/stability 双文件伪装 prefix state authority
没有 authority_class active Python 字段或旧类别链路
没有 prompt/ref/rule/slot 字符串形状伪装 context capability 或 prompt gate authority
没有 content_source/source_kind/context_source_kind 伪装 prefix origin authority 或 provider-visible item identity
没有 schema_version/.vN/_vN/new/native 分支命名进入自有 runtime spine 主链路；落盘结构修订使用 *_schema_revision，稳定身份使用 *_id
没有 semantic_kind/semantic_layer/semantic_time 或泛化 semantic root 命名进入 runtime topology / session projection control contract
没有 semantic_terminal/semantic_actions/semantic_decision_owner 作为 runtime recovery、action surface 或 interruption signal 控制字段
```

文档和代码实现如果与这些不变量冲突，应先改计划，不继续实施。
