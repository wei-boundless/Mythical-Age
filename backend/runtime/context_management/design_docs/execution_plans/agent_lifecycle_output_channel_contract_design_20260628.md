# Agent 生命周期与输出通道契约系统化设计书

## 0. 文档状态

状态：设计基准，Phase 1-7 已完成首轮代码落地，本文同时作为后续维护的生命周期与上下文插线合同。

2026-06-28 落地记录：

- 已将普通初始回答与动作阶段输出区分为 `phase + output channel contract`。
- 已修正工具观察、运行恢复、active steer、closeout、admission repair 等动作阶段提示，回答用户时走 `respond.final_answer / ask_user.user_question / block.blocking_reason`。
- 已把 action phase 的 provider native tool 调用接入 `tool_choice=required`；provider native tool 参数不兼容时降级到 JSON action object，不降级到 raw assistant text。
- 已将 follow-up context rebase 的 sealed history/current append 策略迁到 `backend/runtime/context_management/followup_context_rebase.py`，主 loop 保留 provider message/spec 编排。
- 已修正 `turn_operating_contract` capability group 错线：contract slot 现在归入 `TURN_STATE_CONTROL`，不再误归入 `ACTION_CONTRACTS`。
- 已新增 `backend/runtime/context_management/context_segment_registry.py`，集中声明 context segment kind 的 semantic slot、source kind、content source、capability、layer 与 dynamic tier 默认值。
- 已将 `context_segment_policy.py` 的 kind 集合与内置 policy defaults 改为 registry 派生；`message_specs.py`、`slot_policy.py`、`context_capability_policy.py` 不再维护各自完整 kind 决策表。
- 已修正 recovery 文案中“自然回应或 respond.final_answer”的双通道暗示，动作阶段统一要求通过 `respond.final_answer / ask_user.user_question / block.blocking_reason` 承载用户正文。

本文解决的问题不是“是否允许 Markdown”，而是重新定义 agent 生命周期、系统反应链路、模型输出通道和提示词权威之间的关系。

核心结论：

- Markdown 是用户可见正文格式，不是协议问题。
- 真正需要系统化的是：一段模型输出在当前生命周期阶段里是否具有语义动作身份。
- 普通初始聊天可以直接自然回答。
- 一旦进入工具观察后、运行恢复、admission repair、closeout 或 task execution，模型正在做动作决策；此时自然回答仍然允许，但必须通过 `respond.final_answer` 或 provider `respond` control tool 承载。
- Provider native tools 只是动作传输方式，不是允许 raw assistant text 的许可。
- 系统的“神经反应”应当是事件驱动的控制反馈链路，而不是分散 prompt 文案互相拉扯。

正式架构命名应使用 `turn lifecycle`、`runtime control signal`、`output channel contract`、`model action request`、`output commit boundary`。`神经反应` 只作为产品/工程讨论中的比喻，指系统从事件到反馈再到下一次模型决策的反应链。

## 1. 问题定义

当前故障表面上是 agent 在 `tool_loop` 里直接吐 Markdown，触发 `single_agent_turn_direct_visible_text_not_allowed`，随后 recovery provider 调用失败，前端没有得到正常回答。

更深层问题是生命周期和输出通道没有形成统一权威：

- Prompt 有的地方说“可以直接回答”。
- Tool/control 阶段的 repair prompt 又说“用 `respond.final_answer`”。
- `native_tools` 存在时，调用层曾把输出契约降级成 `action_transport_required=false`。
- Parser 又按 `direct_visible_text_stream_allowed=false` 拦截 raw text。
- 前端只能看到失败终态，却看不到 agent 的真实语义回答。

这不是一个前端展示问题，也不是模型“不听话”的问题，而是系统没有明确回答：

1. 当前 turn 处在哪个生命周期阶段？
2. 这个阶段模型是在普通回答，还是在选择下一步动作？
3. 如果模型要自然语言回答，正文应该走 raw assistant text、JSON action object，还是 provider control tool？
4. 系统收到失败、工具观察、用户 steer 后，应该如何把反馈注入下一次模型决策？

正确终态：

```text
TurnPhase
-> OutputChannelContract
-> ModelVisiblePromptContract
-> ProviderTransport
-> ModelActionParser
-> ActionAdmission
-> Execution/Recovery
-> OutputCommitBoundary
-> PublicProjection
```

每一层只拥有自己的权威，不用 prompt、parser、provider tools、commit gate 各自猜测。

## 2. 当前源码依据

### 2.1 主循环和动作解析

关键文件：

- `backend/harness/loop/single_agent_turn.py`
  - `run_single_agent_turn(...)` 是普通 turn 的主模型循环。
  - `_invoke_single_turn_model_with_stream_events(...)` 负责按输出契约调用 provider。
  - `_single_agent_action_request_from_response(...)` 负责把模型响应解析为 `ModelActionRequest` 或协议错误。
  - `_tool_followup_action_contract_messages(...)` 已经表达“工具观察后必须选择动作”。
  - `_agent_authored_closeout_messages(...)` 此前出现过“直接写自然语言最终回应”的冲突文案，已改为动作阶段 carrier 表达。
- `backend/harness/loop/model_action_protocol.py`
  - `ModelActionRequest` 是模型语义动作的结构化承载。
- `backend/harness/loop/admission.py`
  - admission 层判断动作是否允许执行。

判断：

`single_agent_turn.py` 是生命周期主控。它应显式告诉下游当前是 `initial_decision`、`tool_followup_decision`、`runtime_recovery_decision`、`closeout_decision` 还是 `final_commit`，而不是让输出契约从 allowed actions 反推阶段。

### 2.2 Runtime 合同和提示词投影

关键文件：

- `backend/harness/runtime/compiler.py`
  - `_model_decision_contract_payload(...)` 投影模型动作面。
  - `task_execution_action_schema(...)` 描述动作字段。
- `backend/harness/runtime/turn_operating_contract.py`
  - `turn_action_request_contract_payload(...)` 描述 turn action request。
  - `turn_output_contract_payload(...)` 描述输出提交合同。
- `backend/harness/runtime/tool_call_contract.py`
  - `ToolCallContract` 决定普通工具和控制动作的 provider/tool/action-object 提交方式。
- `backend/harness/runtime/control_action_schema.py`
  - `provider_control_action_bindings(...)` 暴露 `respond / ask_user / block / request_task_run / active_work_control` 等 provider control tools。

判断：

这些模块已经有正确素材，但此前表达不统一。`compiler` 和 `turn_operating_contract` 里曾有“assistant message 是动作形式之一”“natural_response_or_turn_action”之类描述，容易和 tool/control 阶段的 `respond.final_answer` 契约打架；当前已按 phase 拆分。

### 2.3 Prompt library

关键文件：

- `backend/prompt_library/agent_prompts.py`
  - `MAIN_INTERACTIVE_SINGLE_AGENT_TURN_PROMPT` 说“如果可以直接回答，就给出回答”，适合初始普通 turn。
  - `MAIN_INTERACTIVE_OBSERVATION_FOLLOWUP_PROMPT` 此前说“如果观察已经足够，直接给用户回答”，在 tool observation follow-up 场景容易误导为 raw text；当前已改为选择 `respond` 并写入 `final_answer`。
- `backend/prompt_library/rules.py`
  - `RUNTIME_SYSTEM_CALL_PROTOCOL_RULE` 已经要求“需要提交动作时，必须使用本轮允许的动作形式”。
  - `RUNTIME_OUTPUT_BOUNDARY_RULE` 已经定义 `final_answer / user_question / blocking_reason` 是用户可见正文来源。

判断：

全局“可以直接回答”不是错误；错误是没有把这句话限定在普通初始入口。观察后、恢复和 closeout 阶段要改成“可以自然回答，但通过 `respond.final_answer` 承载”。

### 2.4 补充审查结论

本轮代码审查进一步确认：系统当前的问题不是单点 parser 严格，而是有多个层同时在定义“本次模型输出是什么”。

1. `backend/harness/loop/single_agent_turn.py`
   - `SingleAgentOutputChannelContract` 已存在，并已补充显式 `phase` 字段。
   - 初始调用、active turn steer、tool follow-up、runtime recovery、closeout 都通过调用点传递 phase-aware output contract。
   - 后续仍需避免维护者从 `allowed_action_types` 或 native tools 反推动作阶段。
2. `backend/prompt_library/agent_prompts.py`
   - `MAIN_INTERACTIVE_OBSERVATION_FOLLOWUP_PROMPT` 已删除“如果观察已经足够，直接给用户可复核的回答或结果”。
   - 工具观察后阶段改为 `respond.final_answer` carrier，避免诱导 raw assistant text。
3. `backend/harness/runtime/compiler.py`
   - `_model_decision_contract_payload(...)` 已区分 ordinary initial answer 和 action phase。
   - `assistant_text_allowed_when_no_action=True` 只在普通初始入口成立；动作阶段 natural response carrier 是 `respond.final_answer`。
4. `backend/harness/runtime/turn_operating_contract.py`
   - `turn_output_contract_payload(...)` 已从 `natural_response_or_turn_action` 改为阶段化表达。
   - 普通入口允许 natural response；动作阶段 natural response 的 carrier 是 `respond.final_answer`。
5. `backend/runtime/tool_runtime/tool_call_policy.py`
   - `ToolCallBindingOptions` 已支持 `tool_choice`。
   - `build_round_tool_call_options(...)` 已接收 `tool_choice`，动作阶段可传入 `required`。
6. `backend/runtime/model_gateway/lightweight_chat_model.py`
   - provider payload 已能透传 `tool_choice`。
   - 说明 transport 能力具备，缺的是 output channel contract 到 provider tool binding policy 的连接线。
7. `backend/harness/runtime/projection/projector.py` 与 `frontend/src/lib/store/events.ts`
   - runtime protocol terminal 已开始投影为 hidden trace。
   - `failed/error/blocked` 的 `turn_completed` 已释放 active turn gate。
   - 这条线方向正确，但只能解决展示和下一 turn 卡住，不能替代后端生命周期契约修复。

审查裁决：

- 不是拦不拦 Markdown，而是当前阶段是否允许 raw assistant text 直接获得用户正文身份。
- 不是前端要不要显示失败，而是 runtime protocol failure 是否应进入用户主视图。
- 不是模型“不听话”，而是 prompt、compiler contract、provider transport、parser contract 没有共用一个生命周期 phase。
- 后续修复必须让 `OutputChannelContract` 成为 phase、raw text、action requirement、provider transport、parser、commit gate 的唯一连接权威。

### 2.5 冗杂结构与 Context Segment 插线审计

本轮补充审查覆盖 context segment 从 source spec 到 provider payload、follow-up、ledger commit 的真实线路。结论是：主线大体接通；follow-up context rebase 的 sealed/current append 策略已迁出主 loop，但 provider message/spec 编排仍在 `single_agent_turn.py`，后续可继续收束。

当前已接通的主线：

```text
compiler source specs
-> context capability filter
-> prompt source/assembly materialization
-> context_pipeline
   -> provider_visible_context_ledger
   -> physical_context_plan
-> runtime slot/load/segment plan
-> provider payload
```

源码锚点：

- `backend/harness/runtime/compiler.py`
  - `_model_messages_and_segment_plan(...)` 生成 source specs，调用 capability filter、`build_context_pipeline(...)`，再生成 slot/load/segment plan。
- `backend/runtime/context_management/context_pipeline.py`
  - `build_context_pipeline(...)` 是 capability、ledger、physical 三段上下文流水线入口。
  - `apply_provider_visible_context_ledger_to_specs(...)` 负责旧 provider-visible prefix replay 与当前 append candidate。
  - `apply_physical_context_plan_to_specs(...)` 负责物理 lane 和 cache spine。
- `backend/runtime/context_management/context_segment_policy.py`
  - `context_segment_policy_for_spec(...)` 是 section/cache/sealable/semantic commit class 的策略权威。
- `backend/runtime/context_management/physical_context_plan.py`
  - `annotate_specs_with_physical_context_plan(...)` 和 `physical_lane_for_spec(...)` 是 physical lane 排序权威。
- `backend/runtime/context_management/provider_visible_context_ledger.py`
  - `provider_visible_context_append_candidate_spec(...)` 生成 provider success 后可封存的 candidate。
  - replay spec 会带 `provider_visible_payload_authority=runtime.context_management.provider_visible_context_ledger.replay`。
- `backend/runtime/context_management/context_candidates.py`
  - `ContextCommitCandidate.from_provider_payload_segment(...)` 只接受 `provider_visible_context_ledger_commit_stage=provider_success_required`，并拒绝 dynamic tail/current runtime control。
- `backend/harness/loop/single_agent_turn.py`
  - `_single_agent_turn_followup_prompt_payload(...)` 对 follow-up 消息重建 specs、补 provider payload hash、生成 physical plan、生成 segment plan。
  - `_single_agent_turn_append_only_followup_message_specs(...)` 负责把旧 segment 与当前 provider message 对齐。
  - `_sealed_followup_base_context_policy(...)` 把已发给 provider 的历史 message rebase 成 sealed provider-visible history。
  - `_current_followup_append_context_policy(...)` 把当前工具轮 transcript 标记为 current append，等待 provider success 后进入 ledger。
  - `_split_append_only_context_and_dynamic_tail(...)` 按 segment plan 将 accumulated context 与 dynamic tail 拆开。

连线矩阵：

| 线 | Producer | Transport | Consumer | 状态 | 风险 |
|---|---|---|---|---|---|
| 初始 source spec -> segment plan | `compiler._model_messages_and_segment_plan` | message specs + `segment_plan` | provider invocation | 已接通 | capability filter 入口在 compiler 与 pipeline 间有双入口形态 |
| context section/cache policy | `context_segment_policy_for_spec` | `context_segment_policy_metadata` | ledger、physical plan、slot policy | 已接通 | kind/slot/group 映射仍散落在多个表 |
| provider-visible replay | `provider_visible_context_ledger` | replay spec + provider-visible hash | context pipeline / provider payload | 已接通 | 旧 ledger byte replay 必须原样保留，不能用新语义重写 |
| current append -> ledger commit | `provider_visible_context_append_candidate_spec` | `provider_visible_context_ledger_commit_stage=provider_success_required` | `ContextCommitCandidate.from_provider_payload_segment` | 已接通 | 必须继续拒绝 dynamic tail/current control |
| follow-up sealed prefix | `followup_context_rebase.sealed_followup_base_context_policy` | rebased metadata + segment plan | follow-up provider request | 已接通 | rebase 策略已迁出主 loop；provider message/spec 编排仍由 loop 调用 |
| follow-up current tool transcript | `followup_context_rebase.current_followup_append_context_policy` | current append metadata | ledger candidate after provider success | 已接通 | append/seal 策略权威已收束到 context_management |
| dynamic tail 防封存 | `context_segment_policy` + `physical_context_plan` + follow-up detector | `DYNAMIC_TAIL` / `never_replay_tail` | ledger candidate filter | 已接通 | 部分 fallback 仍靠 prompt 内容字符串识别 control tail |
| frontend/main view failure | projector + store reducer | hidden trace + gate release | frontend store | 已接通方向正确 | 只能处理展示和 gate，不能替代后端 contract 修复 |

冗杂结构判断：

1. `context_segment_policy.py` 是必须保留的策略权威。
   - 它应继续拥有 section、cache scope/role、prefix tier、commit policy、replay policy、semantic commit class。
2. `physical_context_plan.py` 是必须保留的物理拼接权威。
   - 它只消费 policy decision，不重新发明语义。
3. `provider_visible_context_ledger.py` 是必须保留的 sealed prefix/replay 权威。
   - 旧 provider-visible bytes 只能由 ledger replay，不能被 compiler 或 loop 重渲染。
4. `slot_policy.py` 当前有过多 kind/source/layer/dynamic tier 映射。
   - 目标是降级为 prompt rendering/tracing policy，只消费 `context_segment_policy_metadata` 和少量 source kind，不再重新决定 section/cache/semantic slot。
5. `context_capability_policy.py` 当前按 kind、semantic slot、contract slot 都能分组。
   - 目标是优先按 `context_capability_group` 或 `context_semantic_slot` 决策，减少 kind 表同步。
6. `message_specs.py` 的 `message_spec_content_source(...)` 是诊断来源，不应成为路由权威。
   - 新 kind 需要能从 registry/policy 元数据派生 content source，避免每拆一个 segment 都改一张表。
7. `single_agent_turn.py` 中 follow-up context rebase 是最大拥挤点。
   - 它保留 execution loop 权威，但 follow-up segment rebase、sealed history/current append/dynamic tail classification 应迁到 `runtime.context_management` 的专门模块。

当前清理边界：

- `turn_stable` 在 active backend policy/capability/slot 代码中已基本退出；后续不应恢复。
- `single_agent_turn_tool_observation` / `tool_observations` 只允许作为 historical detector 或迁移文档文本，不允许回到新 spec、policy、capability、slot、render 决策表。
- `skill_candidates` 不允许恢复为常态 dynamic system message。
- 内容字符串识别 control tail 只能作为迁移期诊断，目标是所有 runtime control tail 都必须带 `_runtime_context_segment_*` tag。

目标上下文插线：

```text
ContextSource
-> ContextSegmentPolicy
-> ContextCapabilityPolicy
-> ProviderVisibleLedger
-> PhysicalContextPlan
-> PromptSlot/SegmentPlan
-> ProviderPayload
-> ProviderSuccessCommit
-> LedgerReplayNextTurn
```

Follow-up 特殊线：

```text
ExistingProviderVisibleMessages
-> FollowupContextRebase
   -> sealed_history_prefix
   -> current_append_candidates
   -> current_dynamic_tail
-> PhysicalContextPlan
-> SegmentPlanPrefixLock
-> ProviderPayload
```

其中 `FollowupContextRebase` 应是独立组件，不应继续散落在 single-agent loop 里。

## 3. 目标概念模型

### 3.1 Agent 生命周期

Agent 生命周期不是任务生命周期，也不是工具生命周期。它是一个 turn 内的语义决策闭环：

```text
ReceiveUserInput
-> BindTurn
-> CompileRuntimePacket
-> InitialModelDecision
-> ParseModelOutput
-> AdmitAction
-> ExecuteAction
-> ObserveResult
-> FollowupModelDecision
-> RecoverOrCloseout
-> CommitOutput
-> CompleteTurn
```

其中 `FollowupModelDecision` 可以循环多次，直到进入 `CommitOutput`、`AskUser`、`Block`、`RequestTaskRun`、`Pause/Stop` 或失败恢复耗尽。

### 3.2 系统神经反应

“神经反应”在本文中定义为系统对运行事件的标准反射链：

```text
Runtime Event
-> Control Signal
-> Model Visible Feedback
-> Output Channel Contract
-> Next Model Decision
-> Action Admission
-> Execution or Commit
```

例子：

| 事件 | 系统反应 | 模型下一步 |
|---|---|---|
| 工具返回观察 | 生成 observation feedback | 选择 `respond / tool_call / ask_user / block / request_task_run` |
| 动作协议错误 | 生成 protocol violation control signal | 修正同一语义动作，不改写用户目标 |
| admission 拒绝 | 生成 admission repair feedback | 修正动作字段、权限、范围或改选合法动作 |
| 工具预算耗尽 | 生成 closeout control signal | 只选 `respond / ask_user / block` |
| provider 调用失败 | 记录模型失败事实 | 不把协议失败伪装成断线，不在前端展示成用户可操作失败 |

系统反应不能替 agent 做语义裁决；它只能提供事实、边界、错误和可选动作。

### 3.3 运行通畅原则

目标不是为了限制 agent，而是让 agent 的每次表达都能被系统正确承接。

成熟 agent 的运行通畅来自分层明确：

- 初始普通回答要顺畅：模型可以直接给 Markdown 正文，commit gate 直接提交。
- 进入运行闭环后要可执行：模型每次输出都必须有动作身份，否则系统不知道是回答、继续工具、询问、阻塞还是申请任务资源。
- 自然语言回答仍然允许：动作阶段不是禁止回答，而是要求把回答放进 `respond.final_answer`。
- 系统不能越权替 agent 包装答案：parser 不应把 raw text 自动包成 `final_answer` 并提交；可以给 recovery，让模型重新确认同一语义动作。
- 前端不能用隐藏失败代替后端修复：前端只负责区分断线、runtime trace 和用户可见阻塞，后端必须修正生命周期合同。
- provider native tools 是 transport，不是语义许可：有 native tools 只说明动作可以通过 provider tool selection 传输，不说明 raw assistant text 可以成为最终答案。

因此，限制 raw assistant text 的唯一理由是：当前 phase 要求一个可执行、可恢复、可提交的语义动作。普通初始问答不应被动作协议拖慢；动作阶段也不应因为裸文本而失去执行身份。

## 4. 生命周期阶段表

| 阶段 | 触发来源 | 模型职责 | raw assistant text | 正确回答载体 |
|---|---|---|---:|---|
| `initial_decision` | 用户新 turn 第一次模型调用 | 判断是否普通回答、工具观察、询问、阻塞或申请资源 | 允许 | 普通回答可 raw text；动作走 provider tool 或 JSON action |
| `initial_action_parse` | 初始响应解析 | 把模型输出归一为正文或动作 | 取决于上一阶段契约 | raw text 只能作为普通最终回答 |
| `tool_followup_decision` | 工具观察返回 | 基于观察决定下一步 | 不允许 | `respond.final_answer` 或 provider `respond` tool |
| `runtime_recovery_decision` | 协议错误、动作未执行、输出通道错误 | 修复动作 | 不允许 | 修正后的 action |
| `admission_repair_decision` | admission 拦截 | 修正权限、范围、动作字段 | 不允许 | 修正后的 action |
| `active_turn_steer_decision` | 运行中用户 steer | 判断如何接入当前工作 | 不允许 | control action |
| `closeout_decision` | 工具预算、恢复耗尽、连续失败、停止要求 | 做最终可见裁决 | 不允许 | `respond / ask_user / block` |
| `task_execution_decision` | 持续任务执行 turn | 推进任务、验证、收口 | 不允许 | action |
| `output_commit` | 已有可提交正文或动作结果 | 校验并提交用户可见内容 | 不适用 | `final_answer / user_question / blocking_reason / public_feedback` |

关键规则：

- 不能用 `allowed_action_types` 判断是不是动作阶段。
- `allowed_action_types` 只是动作集合，不是生命周期状态。
- 是否动作阶段必须由调用点显式给出：`initial_decision`、`tool_followup_decision`、`runtime_recovery_decision`、`closeout_decision` 等。

## 5. Output Channel Contract

### 5.1 定义

`OutputChannelContract` 是当前模型调用的输出通道合同，回答三个问题：

1. 当前阶段是否允许 raw assistant text 直接成为用户正文？
2. 当前阶段是否必须提交动作？
3. 如果必须提交动作，动作载体是 provider native tool，还是 JSON action object？

建议结构：

```json
{
  "phase": "tool_followup_decision",
  "raw_assistant_text_allowed": false,
  "action_required": true,
  "visible_body_source": "model_action_user_field",
  "preferred_action_transport": "provider_control_tool",
  "fallback_action_transport": "json_action_object",
  "allowed_action_types": ["respond", "ask_user", "block", "tool_call"],
  "natural_response_carrier": "respond.final_answer"
}
```

### 5.2 通道规则

| 合同字段 | 归属层 | 含义 |
|---|---|---|
| `phase` | execution loop | 当前模型调用的生命周期阶段 |
| `raw_assistant_text_allowed` | output channel | raw text 是否可以直接进入最终正文 |
| `action_required` | output channel | 是否必须形成一个语义动作 |
| `preferred_action_transport` | transport | 优先动作载体 |
| `fallback_action_transport` | transport | provider tool 不可用时的载体 |
| `visible_body_source` | output boundary | 用户正文从哪里来 |
| `natural_response_carrier` | prompt/parser | 自然语言回答放在哪个字段 |

### 5.3 Native tools 的正确语义

Provider native tools 只表示：

```text
模型可以通过 provider tool selection 提交动作。
```

它不表示：

```text
模型可以不提交动作，直接写 raw assistant 正文。
```

因此：

- `native_tools` 存在时，不能自动把 `action_required` 降为 false。
- tool/control 阶段如果 provider 支持，应要求模型选择一个 native action tool。
- 如果 provider 不支持 required tool choice，则 prompt 和 parser 仍要按动作阶段验收；raw text 只能触发 recovery，不应直接发布。

## 6. Prompt 权威分层

| Prompt 来源 | 允许表达 | 不允许表达 |
|---|---|---|
| main interactive role prompt | 初始 turn 如何理解用户、何时可直接回答 | tool follow-up 阶段的字段协议 |
| observation follow-up prompt | 观察是事实输入，必须重新裁决下一步 | “直接给用户回答”这种 raw text 暗示 |
| system call protocol rule | 需要动作时必须使用当前动作形式 | 具体阶段是否允许 raw text |
| output boundary rule | 用户可见正文边界、不能泄露内部协议 | 动作选择策略 |
| action schema / provider control schema | 字段类型、required fields、provider tool 参数 | agent 角色、任务策略、领域判断 |
| repair / recovery prompt | 本次动作哪里不合法、如何修正 | 重写用户目标或引入第二套生命周期 |
| closeout prompt | 基于停止事实选择 `respond/ask_user/block` | 允许动作外自然正文 |

核心治理规则：

- 普通初始入口可以说“如果可以直接回答，就直接回答”。
- 所有 observation / recovery / closeout / task execution prompt 必须说“如果可以回答，使用 `respond.final_answer`”。
- 任何 prompt 不得同时说“直接写自然语言最终回应”又说“不要输出动作对象之外的正文”。
- 提示词不负责兜底 parser；parser 不负责修正提示词；二者都必须服从 `OutputChannelContract`。

### 6.1 生命周期提示词对齐矩阵

生命周期提示词分两类：

- 静态 work role prompt：来自 `backend/prompt_library/agent_prompts.py`，定义 agent 在某种 invocation 中的身份、责任和判断标准。
- 运行时 lifecycle prompt：由 `backend/harness/loop/single_agent_turn.py` 或 active steering/admission/recovery 逻辑按当前事件追加，定义本次阶段事实、可选动作、输出载体和修复要求。

| 生命周期阶段 | invocation / 触发 | 静态 work role prompt | 运行时 lifecycle prompt | 输出通道 | 当前问题 | 修正要求 |
|---|---|---|---|---|---|---|
| `initial_decision` | `single_agent_turn` 初始模型调用 | `MAIN_INTERACTIVE_SINGLE_AGENT_TURN_PROMPT` | `compiler._model_decision_contract_payload(...)`、`turn_operating_contract_payload(...)`、当前 turn operating contract | raw text 可作为普通最终回答；动作走 provider tool 或 JSON action | 已修正：raw text allowed 只在普通入口暴露 | 动作阶段不得继承 ordinary initial assistant message |
| `tool_followup_decision` | 工具观察后，含 `tool_observation_followup` packet 或 single-turn follow-up | `MAIN_INTERACTIVE_OBSERVATION_FOLLOWUP_PROMPT` | `_tool_followup_action_contract_messages(...)` | 必须 action；回答走 `respond.final_answer` | 已修正：work role prompt 不再说动作外直接回答 | 观察足够时选择 `respond`，把自然回答写入 `final_answer` |
| `runtime_recovery_decision` | parser/protocol/output channel/admission 前置错误后的恢复 | 继承当前 turn 原 work role，不新建角色 | `_runtime_control_signal_recovery_messages(...)` | 必须 action；保留原语义意图，修正动作字段或载体 | recovery prompt 已基本正确，但 phase 没进入统一 output contract | recovery 调用必须传 `phase=runtime_recovery_decision` 和 action contract |
| `admission_repair_decision` | `AdmissionDecision` 拒绝模型动作 | 继承当前 turn 原 work role | `SINGLE_AGENT_ADMISSION_REPAIR_PROMPT` + `_single_agent_admission_repair_messages(...)` | 必须 JSON/action；不能 raw 回答 | repair 调用当前用 `require_json_action=True`，但没有统一 `OutputChannelContract.phase` | 改为 action phase contract，提示词说明“修正动作，不重写用户目标” |
| `active_turn_steer_decision` | active turn 中用户补充 | 继承当前 turn 原 work role | `active_turn_steering._queued_user_steer_model_message(...)` | 必须重新决策动作；raw text 不直接发布 | steer prompt 说明“吸收补充要求”，但未显式说输出载体 | 追加 output channel contract：继续工具、respond、ask_user、block、task control 都必须通过动作 |
| `closeout_decision` | 工具预算、恢复耗尽、停止、连续失败 | 继承当前 turn 原 work role | `_agent_authored_closeout_messages(...)` | 只允许 `respond / ask_user / block` | 已修正为动作承载，但文档要锁定不能回退 | 保持“自然回复必须通过动作承载”；不得恢复动作外正文 |
| `task_execution_decision` | `task_execution` 持续任务执行 | `MAIN_INTERACTIVE_TASK_EXECUTION_PROMPT` | task execution packet 的 action schema、task contract、turn operating contract、tool observation follow-up | 必须 action；回答走 `respond.final_answer` | prompt 说“最终回复”，但没有显式绑定 `respond.final_answer` | 增补 task execution action contract：回复、询问、阻塞都必须在动作字段内 |
| `output_commit` | 已有 action 或允许 raw text 的 ordinary answer | 无模型 prompt | output boundary / commit gate | 只消费 `final_answer / user_question / blocking_reason / public_feedback`；ordinary initial raw text 例外 | commit gate 不应读 runtime prompt 或协议错误 | commit gate 只能消费 output contract 认可的正文来源 |

提示词接线原则：

1. 静态 work role prompt 只描述身份、任务、边界和判断标准，不直接决定本次输出通道。
2. 运行时 lifecycle prompt 必须携带当前 `phase`、`allowed_action_types`、`OutputChannelContract` 和用户可见字段载体。
3. 静态 prompt 中“直接回答”只能在普通初始入口成立；一旦进入观察后、恢复、admission repair、active steer、closeout 或 task execution，必须改写为 `respond.final_answer`。
4. lifecycle prompt 不允许通过开发说明写成“这是某个 runtime 节点”；必须面向 agent 说明“你现在是谁、收到什么事实、要做什么裁决、输出放在哪里、不能做什么”。
5. `compiler._model_decision_contract_payload(...)` 和 `turn_output_contract_payload(...)` 必须按 phase 生成模型可见合同，不能再发一个跨阶段通用的 `natural_response_or_turn_action`。
6. 若 provider control tools 可用，运行时 prompt 应说“选择对应 control action/tool”；若不可用，才说“提交同等结构化 action object”。两者都不能允许动作外 raw Markdown。

必须立即修正的 prompt 对齐项：

- `MAIN_INTERACTIVE_OBSERVATION_FOLLOWUP_PROMPT`：删除“直接给用户回答或结果”，改为“选择 `respond`，将回答写入 `final_answer`”。
- `_model_decision_contract_payload(...)`：把 `assistant_response_form=assistant_message` 改成 phase-aware 表达，只允许 ordinary initial answer 使用 raw assistant message。
- `turn_output_contract_payload(...)`：把 `format=natural_response_or_turn_action` 改成 `ordinary_initial_response_or_action`，并补 `action_phase_natural_response_carrier=respond.final_answer`。
- `MAIN_INTERACTIVE_TASK_EXECUTION_PROMPT`：补一句“收口、询问或阻塞必须通过本轮允许动作承载，对用户正文写入对应字段”。
- active steer lifecycle prompt：补一句“吸收 steer 后只能提交本阶段允许动作，不要把动作外正文当作最终答复”。

## 7. 系统反应的固定流

### 7.1 初始普通回答

```text
User input
-> compile packet
-> phase=initial_decision
-> raw_assistant_text_allowed=true
-> model writes Markdown answer
-> output boundary sanitizes
-> commit final answer
```

这里不需要强制 JSON，也不需要 provider `respond` tool。

### 7.2 初始工具调用

```text
User input
-> phase=initial_decision
-> model selects tool_call
-> parser builds ModelActionRequest
-> admission
-> tool execution
-> observation feedback
-> phase=tool_followup_decision
```

### 7.3 工具观察后收口

```text
Tool observation
-> model-visible observation feedback
-> phase=tool_followup_decision
-> action_required=true
-> model selects respond tool or JSON {"action_type":"respond","final_answer":"..."}
-> parser validates action identity
-> output commit consumes final_answer
-> frontend displays final answer
```

### 7.4 协议错误恢复

```text
Parser detects raw text in action phase
-> runtime_control_signal(model_protocol_violation)
-> phase=runtime_recovery_decision
-> action_required=true
-> model fixes same semantic intent as respond.final_answer
-> parser validates
-> commit
```

Recovery 的目标是保留模型原本语义意图，不是让系统吞掉失败或前端隐藏失败。

### 7.5 Closeout

```text
Tool budget exhausted / recovery exhausted / stop boundary
-> closeout control signal
-> phase=closeout_decision
-> allowed actions = respond / ask_user / block
-> model chooses one
-> output commit or blocked/ask_user terminal
```

## 8. Commit Gate 与前端展示边界

Commit gate 只接受已经过 output boundary 判定的用户可见内容：

- `respond.final_answer`
- `ask_user.user_question`
- `block.blocking_reason`
- 明确的 public progress feedback
- 系统级可解释 terminal closeout summary

Commit gate 不接受：

- tool lifecycle event
- runtime control signal 原文
- provider protocol error
- action object 字段名
- raw assistant text in action phase
- repair prompt 内容

前端展示规则：

- 非断线的 runtime 协议失败不应展示成“连接失败”。
- `turn_completed(status=failed)` 如果只是 runtime trace failure，应释放 active turn gate，但主视图不展示为断线错误。
- 用户可见失败只来自 agent 通过 `block.blocking_reason` 或系统明确可解释的模型服务失败摘要。

## 9. 实施计划

### Phase 1：锁定阶段枚举和输出通道合同

目标：

- 新增或集中定义 `ModelInvocationPhase`。
- 每个模型调用点显式传 phase。
- `SingleAgentOutputChannelContract` 增加 phase/action transport 语义，或以旁路 diagnostics 携带。

涉及文件：

- `backend/harness/loop/single_agent_turn.py`
- `backend/harness/runtime/turn_operating_contract.py`
- `backend/harness/runtime/compiler.py`

完成标准：

- 初始调用允许 raw assistant text。
- tool follow-up、recovery、closeout、admission repair 显式 `action_required=true`。
- 不能再由 `native_tools` 覆盖 action requirement。

### Phase 2：统一提示词权威

目标：

- 修改 observation follow-up 和 closeout 文案。
- `model_decision_contract` 不再把 `assistant_message` 描述成动作阶段的可选形式。
- `turn_output_contract_payload` 区分普通自然回答和动作阶段 respond。

涉及文件：

- `backend/prompt_library/agent_prompts.py`
- `backend/prompt_library/rules.py`
- `backend/harness/runtime/compiler.py`
- `backend/harness/runtime/turn_operating_contract.py`
- `backend/harness/loop/single_agent_turn.py`

完成标准：

- 搜索“直接写自然语言最终回应”“直接给用户回答”等文案时，只有普通初始入口允许此表达。
- observation/recovery/closeout/task execution 都明确要求 `respond.final_answer`。

### Phase 3：修正 native tool transport

目标：

- `native_tools` 不再把 `action_transport_required` 降为 false。
- action phase 有 provider control tools 时，优先走 provider tool selection。
- provider 不支持 required tool choice 时，parser 仍按 action phase 验收，不允许 raw text commit。

涉及文件：

- `backend/harness/loop/single_agent_turn.py`
- `backend/runtime/tool_runtime/tool_call_policy.py`
- `backend/runtime/model_gateway/model_runtime.py`
- `backend/runtime/model_gateway/lightweight_chat_model.py`

完成标准：

- 最新失败中的矛盾合同不再出现：
  - `action_transport_required=false`
  - `direct_visible_text_stream_allowed=false`
- tool/control phase 的 raw Markdown 不进入 commit gate。

### Phase 4：Parser 和 recovery 对齐

目标：

- `_single_agent_action_request_from_response(...)` 接收完整 output contract。
- `allow_model_tool_calls=True` 不再重写 channel contract 为非动作阶段。
- raw text in action phase 产生可恢复协议错误，并明确要求 `respond.final_answer`。

涉及文件：

- `backend/harness/loop/single_agent_turn.py`
- `backend/runtime/model_gateway/model_response_protocol.py`

完成标准：

- recovery prompt 保留原意图，只修正传输形态。
- 如果模型已经写出可用自然回答，下一轮 recovery 能让它进入 `final_answer`，而不是丢失。

### Phase 5：Projection 和 frontend 展示收束

目标：

- 非断线 runtime 协议失败只作为 trace，不作为主视图失败。
- active turn gate 在 failed/error/blocked terminal 时释放。
- 用户可见区域只显示 output commit 边界认可的内容。

涉及文件：

- `backend/harness/runtime/projection/projector.py`
- `frontend/src/lib/store/events.ts`

完成标准：

- provider/service 真失败有摘要。
- 协议失败/recovery 失败不伪装成断线。
- 下一 turn 不再因为 active turn 未释放而沉默。

### Phase 6：Commit gate 与端到端切换验收

目标：

- output commit boundary 只消费 `final_answer / user_question / blocking_reason / public_feedback`。
- raw assistant text 只有在 `phase=initial_decision` 且 `raw_assistant_text_allowed=true` 时才能成为最终正文。
- action phase 的用户可见内容只能来自动作字段或 provider control tool 参数。

涉及文件：

- `backend/harness/loop/single_agent_turn.py`
- `backend/harness/runtime/turn_operating_contract.py`
- `backend/harness/runtime/projection/projector.py`
- `frontend/src/lib/store/events.ts`

完成标准：

- 普通问答路径不被强制 JSON 化。
- 工具后回答路径稳定走 `respond.final_answer`。
- recovery 后能保留模型原本语义意图，但必须重新形成动作身份。
- 前端只显示 commit gate 认可的用户正文，不把 protocol terminal 当作断线失败。

切换规则：

- 本机制不保留旧 raw-text action phase 兼容通道。
- 如 provider 不支持 required tool choice，降级为 JSON action object，不降级为 raw assistant text。
- 如果 action phase 连续无法形成动作，进入 agent-authored closeout，由 agent 在 `respond / ask_user / block` 中选择，而不是由系统自动发布上一条裸文本。

### Phase 7：Context segment 插线收束与冗余结构清理

目标：

- 把 context segment 的 section/cache/seal/physical lane/action phase 插线收束成单向权威链。
- 清理不再有独立权威的 kind 映射、旧 route kind、内容字符串 fallback。
- 将 follow-up context rebase 从 `single_agent_turn.py` 迁出，避免 execution loop 同时做上下文策略。

涉及文件：

- `backend/runtime/context_management/context_segment_policy.py`
- `backend/runtime/context_management/context_capability_policy.py`
- `backend/runtime/context_management/physical_context_plan.py`
- `backend/runtime/context_management/provider_visible_context_ledger.py`
- `backend/prompt_composition/slot_policy.py`
- `backend/prompt_composition/message_specs.py`
- `backend/harness/runtime/compiler.py`
- `backend/harness/loop/single_agent_turn.py`

建议新增或收束：

- `backend/runtime/context_management/followup_context_rebase.py`
  - 当前输入：base segment、当前 provider message、原 metadata、是否当前工具轮。
  - 当前输出：sealed replay 或 current append 的 rebased context policy。
  - 后续可扩展输入：base segment plan、当前 provider messages、tool iteration、packet id。
  - 权威：只负责 follow-up 上下文 rebase，不负责模型动作决策。
- `backend/runtime/context_management/context_segment_registry.py`
  - 收敛 kind -> semantic slot / content source / capability group / source kind 的重复表。
  - `context_segment_policy.py` 保留策略推导，registry 只提供默认声明，不覆盖显式 metadata。

清理顺序：

1. 先把 `single_agent_turn.py` 中 `_sealed_followup_base_context_policy`、`_current_followup_append_context_policy` 的策略逻辑迁入 `followup_context_rebase.py`。
2. 保留 `_single_agent_turn_append_only_followup_message_specs` 在主 loop，直到 provider message/spec 编排也有独立模块承接；避免把 execution loop 与 provider payload 编排一次性拆开造成新断线。
3. 保留 `single_agent_turn.py` 作为调用者，只传入 phase、messages、base segment plan、provider-visible ledger scope。
4. 将 `slot_policy.py` 的重复 kind/layer/dynamic tier 表改为消费 context policy/registry 输出；不能再重新决定 section/cache。
5. 将 `context_capability_policy.py` 优先改为按 `context_capability_group`、`context_contract_slot`、`context_semantic_slot` 决策，kind 表只保留过渡入口或由 registry 生成。
6. 将 `message_specs.py` 的 content source 判断改为优先读取 metadata/registry，未注册时只作为诊断 fallback。
7. 删除 active path 中旧 route kind 和内容字符串识别 control tail 的 fallback；调用点必须写入 `_runtime_context_segment_kind/source_ref/metadata` tag。

已落地结果：

- `followup_context_rebase.py` 已承接 sealed follow-up base、current follow-up append、provider-visible replay kind 判断；`single_agent_turn.py` 只保留 provider message/spec 对齐与执行循环编排。
- `context_segment_registry.py` 已成为 kind 默认声明权威，集中维护 semantic slot、source kind、content source、capability group、prompt layer 与 dynamic tier。
- `context_segment_policy.py` 的 `STATIC_PREFIX_KINDS`、`MEMORY_CONTEXT_KINDS`、`APPEND_ONLY_CONTEXT_KINDS`、`CURRENT_CONTROL_TAIL_KINDS` 均由 registry 派生；内置 policy defaults 也从 registry 安装。
- `message_specs.py` 的 content source 只做 registry 查询和诊断 fallback，不再手写完整 kind 路由表。
- `slot_policy.py` 的 kind -> source kind/layer/dynamic tier 改为 registry defaults；保留的本地表只承担 source-kind 排序、tiered layer 和 load phase 顺序。
- `context_capability_policy.py` 的 kind capability 改为 registry 查询；本地仅保留 semantic slot、contract slot、prompt resource 的 capability 规则。
- active backend 路径中 `turn_stable`、`skill_candidates`、`single_agent_turn_tool_observation`、`tool_observations` 未恢复为新决策 kind；旧工具观察 route 只保留在 historical detector 或迁移文档边界。
- recovery 文案中动作阶段的自然回答 carrier 已统一为 `respond.final_answer`，不再表达“自然回应或 action carrier”这种双通道。

完成标准：

- `context_segment_policy_for_spec(...)` 是 section/cache/seal/replay 的唯一策略入口。
- `physical_context_plan.py` 是 physical lane/cache spine 的唯一排序入口。
- `provider_visible_context_ledger.py` 是 sealed prefix replay 和 provider success commit 的唯一入口。
- `single_agent_turn.py` 不再内联维护 follow-up context policy，只负责 execution loop 和模型调用。
- `slot_policy.py`、`context_capability_policy.py`、`message_specs.py` 不再各自维护互相不同步的完整 kind 决策表。
- `rg -n "turn_stable|skill_candidates|single_agent_turn_tool_observation|tool_observations" backend/harness backend/runtime backend/prompt_composition` 只允许命中历史 detector、迁移文档或明确注释的旧 ledger replay 边界。
- 所有 follow-up provider payload 都能通过 segment plan hash 校验；dynamic tail 不进入 ledger commit candidate。

## 10. 验证矩阵

| 场景 | 期望 |
|---|---|
| 普通问答，不用工具 | raw Markdown 直接显示 |
| 初始轮决定调用工具 | 工具动作执行，工具前反馈可选但不伪装结果 |
| 工具后模型要回答 | 通过 `respond.final_answer` 提交，用户看到 Markdown |
| 工具后模型裸写 Markdown | parser 触发 recovery，不 commit raw text |
| recovery 后模型修正为 respond | commit `final_answer` |
| closeout 阶段 | 只允许 `respond / ask_user / block` |
| provider native tools 可用 | 选择 provider control/tool action，不降级 raw text |
| provider native tools 不可用 | 使用 JSON action object |
| provider 服务失败 | 显示模型服务失败摘要，不当成断线 |
| runtime 协议失败 | 前端释放 turn gate，不在主视图展示断线失败 |

2026-06-28 验证记录：

- `python -m py_compile` 已覆盖生命周期、prompt、provider schema、context registry/policy、prompt composition、provider payload、cache planner/serializer 等本轮相关 Python 文件。
- `git diff --check` 通过，仅有既有 CRLF 替换提示。
- registry 声明完整性检查通过：`context_segment_kind_declarations()` 共 83 个 kind，重复 kind 为 0。
- 关键词检查结果：`turn_stable`、`skill_candidates`、`single_agent_turn_tool_observation`、`tool_observations` 只命中文档或 `tool_transcript.py` historical detector；未回到 active policy/capability/slot/render 表。
- 固定端口栈已重启并通过健康检查：前端 `http://127.0.0.1:3000/` 200，后端 `http://127.0.0.1:8003/health` 200，`/api/capability-system/catalog` 200。
- 启动日志无新增导入错误；后端仅有既有 `jieba/pkg_resources` deprecation warning。

## 11. 禁止事项

- 不允许用前端隐藏来替代后端生命周期修复。
- 不允许在 action phase 放开 raw assistant text 作为最终正文。
- 不允许把 `native_tools` 当作 `action_required=false` 的理由。
- 不允许让 prompt 同时表达“直接自然回答”和“动作对象外不能有正文”。
- 不允许 parser 猜测用户意图或自动把 raw text 包成 `final_answer` 后提交；可以 recovery，但语义动作必须由模型重新确认。
- 不允许 task/tool/recovery/closeout 形成第二套模型生命周期。

## 12. 文件级检查清单

### `backend/harness/loop/single_agent_turn.py`

- 增加显式 invocation phase。
- 初始调用保留 raw text 通道。
- tool follow-up / recovery / active turn steer / closeout / admission repair 全部传 action contract。
- native tools 不覆盖 action contract。
- closeout prompt 改为 respond/ask_user/block 动作承载。

### `backend/harness/runtime/compiler.py`

- `_model_decision_contract_payload(...)` 区分 ordinary initial answer 和 action phase。
- 删除或改写 `assistant_response_form=assistant_message` 对动作阶段的误导。
- model-visible payload 增加 output channel phase hints。

### `backend/harness/runtime/turn_operating_contract.py`

- `turn_output_contract_payload(...)` 不再笼统写 `natural_response_or_turn_action`。
- 明确 `raw_text_is_not_a_control_action`。
- 明确 action phase 的 natural response carrier 是 `respond.final_answer`。

### `backend/prompt_library/agent_prompts.py`

- `MAIN_INTERACTIVE_SINGLE_AGENT_TURN_PROMPT` 保留普通直接回答语义。
- `MAIN_INTERACTIVE_OBSERVATION_FOLLOWUP_PROMPT` 改成“观察足够时选择 respond，并把自然回答写入 final_answer”。

### `backend/prompt_library/rules.py`

- 保持 system call protocol 和 output boundary 分层。
- 不把字段协议写入决策规则。
- 不把动作选择写入输出规则。

### `backend/runtime/tool_runtime/tool_call_policy.py`

- 支持 action phase 的 required provider tool choice 策略。
- 多工具普通观察和单控制动作分开表达。

### `backend/runtime/model_gateway/*`

- provider payload 正确携带 `tool_choice` / strict tool schema。
- 不支持 required tool choice 的 provider 返回可诊断事实，而不是静默降级。

### `frontend/src/lib/store/events.ts`

- terminal failed/error/blocked 释放 active turn gate。
- 不把 runtime trace failure 当成断线。

## 13. 设计裁决

本项目应采用“turn lifecycle owns phase，output channel owns transport，model owns semantic decision”的架构。

具体裁决：

- 生命周期阶段由 `single_agent_turn` 调用点显式定义。
- 动作集合由 packet/action surface 定义。
- 动作传输由 tool call contract 和 output channel contract 定义。
- 用户可见正文由 output commit boundary 定义。
- Prompt 只解释当前阶段 agent 应如何理解和选择，不拥有最终协议权威。

这能保证运行通畅，而不是为了限制而限制：普通回答仍然自然；需要运行时接管的阶段则有明确动作身份，系统才能继续执行、恢复、收口和展示。
