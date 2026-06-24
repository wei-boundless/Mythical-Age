# Agent 上下文装配系统组架构方案

## 1. 目的

本文定义一套更稳定的 agent 上下文装配架构。目标不是让 agent 临场拼凑 prompt，而是把已经成熟的运行系统做成可声明、可接线、可审计的系统组，再由 provider 适配层决定最终物理装配结构。

核心目标：

```text
底层物理模型跟 provider 走；
系统组和能力组跟 agent/profile/task 声明走；
环境、工具权限、provider 协议和上下文封存由平台锁定；
旧 provider-visible 上下文一字不动，新内容只能追加。
```

本文同时覆盖：

1. 哪些属于核心底层架构。
2. 哪些属于上下文体系。
3. 哪些属于系统组和能力组。
4. ReAct 机制开启后应该接入哪些契约、上下文段和反馈。
5. skills、tools、environment 如何被装载和约束。
6. provider 物理结构如何适配。
7. 当前代码链路如何收束到更稳定的结构。

## 2. 官方依据和工程含义

DeepSeek 官方 Context Caching 文档说明，缓存是 provider 侧自动前缀缓存。后续请求只有在完整复用已经持久化的 cache prefix unit 时才能命中，真实命中字段是：

```text
usage.prompt_cache_hit_tokens
usage.prompt_cache_miss_tokens
```

参考：

- https://api-docs.deepseek.com/guides/kv_cache
- https://api-docs.deepseek.com/guides/multi_round_chat
- https://api-docs.deepseek.com/guides/thinking_mode
- https://api-docs.deepseek.com/api/create-chat-completion

DeepSeek 多轮对话 API 是无状态的，调用方必须把之前对话历史拼接到 `messages` 后再发起下一轮请求。因此本系统必须把“语义记忆”和“provider-visible 历史字节”分开管理：

```text
语义记忆：agent 用来理解任务和事实。
provider-visible 历史：provider 上一轮真实看过的 messages/tools/request params。
```

对于 DeepSeek V4 thinking：

```text
无 tool call 的 assistant reasoning_content 可以不进入后续上下文，传回也会被忽略。
有 tool call 的 assistant reasoning_content 必须在后续请求中传回。
```

所以 provider adapter 必须按模型协议处理 `content`、`reasoning_content`、`tool_calls`、`tool_call_id`，不能把这些字段当普通本地 metadata。

## 3. 总体理解

系统需要分成五层。

```text
L0 Provider 物理适配层
L1 核心上下文物理装配层
L2 平台系统组层
L3 Agent 能力配置层
L4 Prompt / Context 内容层
```

这五层的权力不能混在一起。

### 3.1 L0 Provider 物理适配层

这一层决定最终 provider-visible 物理结构。

它回答：

```text
这个 provider 支持自动 prefix cache 吗？
这个 model 是两段式还是三段式？
reasoning_content/tool_calls 如何回放？
tools/request params 是否进入 cache-sensitive contract？
provider 返回的 usage 如何读取？
```

当前代码对应：

- `backend/runtime/model_gateway/provider_cache_policy.py`
- `backend/runtime/model_gateway/model_request.py`
- `backend/runtime/model_gateway/provider_payload.py`
- `backend/runtime/model_gateway/lightweight_chat_model.py`

这一层不关心 agent 想不想用 ReAct，也不关心某个 skill 是否启用。它只负责 provider 协议和物理 payload。

### 3.2 L1 核心上下文物理装配层

这一层是最终 message 顺序的唯一权威。

它只做一件事：

```text
把已经选好的上下文包，按 provider policy 固定顺序拼成 provider-visible messages。
```

当前最接近这个权威的代码是：

- `backend/runtime/context_management/context_assembly.py`
- `backend/runtime/context_management/provider_visible_context_ledger.py`

目标物理包：

```text
static_prefix
context_memory
dynamic_tail
```

默认两段式：

```text
static_prefix -> context_memory
```

可选三段式：

```text
static_prefix -> context_memory -> dynamic_tail
```

注意：两段式不是没有动态控制，而是动态控制被折进当前 context stream 的尾部。如果这段内容已经发给 provider 并成功返回，下一轮为了缓存需要 provider-visible replay，但它仍然可以保持：

```text
semantic_memory_visible = false
semantic_memory_commit_policy = never_commit
provider_visible_replay_only = true
```

### 3.3 L2 平台系统组层

系统组是完整运行子系统，不是单个 prompt 片段。

例如：

```text
react_loop
task_contract_intake
context_memory
memory_governance
tool_runtime
skill_runtime
subagent_delegation
evidence_read
lifecycle_resume_steer
output_projection
recovery_closeout
memory_write_compaction
```

一个系统组开启后，必须同时接入：

```text
契约
上下文段
运行反馈
provider-visible 回放策略
投影/观测
失败处理
```

一个系统组关闭后，这些线不能半残留。

系统分类必须先于能力模板。也就是说，声明入口应该是：

```text
启用哪个系统
调整这个系统的哪些配置
系统展开哪些契约、上下文段、反馈和权限线
```

而不是让调用方直接维护一大串 `context_capability_groups`。能力组是系统解析后的编译产物，不是主配置入口。

### 3.4 L3 Agent 能力配置层

agent/profile/task 可以声明自己接哪些能力组，但不能改变底层物理模型。

当前代码已有雏形：

- `backend/runtime/context_management/context_capability_policy.py`

已有能力组包括：

```text
static_identity
runtime_contracts
action_contracts
task_contracts
tool_context
context_memory
task_state_context
evidence_context
current_dynamic_control
lifecycle_control
repair_feedback
active_skill
memory_write
```

这些能力组应该被系统组调用，而不是散落在各个 prompt 逻辑中。

### 3.5 L4 Prompt / Context 内容层

这一层只负责提供可装配内容：

```text
role prompt
runtime rule
task contract
tool guidance
skill body
read evidence
tool observation
repair feedback
memory append
```

它可以有 metadata，但不能自己决定物理排序。

当前相关代码：

- `backend/prompt_library/models.py`
- `backend/prompt_library/assembly.py`
- `backend/prompt_library/packs.py`
- `backend/prompt_library/rules.py`
- `backend/prompt_composition/source_bundle.py`
- `backend/prompt_composition/assembly_plan.py`
- `backend/prompt_composition/materializer.py`

目标是：prompt library 提供内容和能力元数据，最终物理顺序交给 L1。

## 4. 系统组和能力组的关系

系统组是大开关，能力组是接线点。系统分类是主结构，能力组只是系统落到 prompt/context 装配时的低层线路。

系统分类总表：

| 系统组 | 负责什么 | 主要开关 | 展开的能力线 |
| --- | --- | --- | --- |
| `task_contract_intake` | 是否接收和生成任务契约 | `accept_task_contract`、`request_task_run_enabled`、`contract_strictness` | `task_contracts`、`runtime_contracts`、`lifecycle_control`、`repair_feedback` |
| `react_loop` | 是否进入 reason-act-observe 工具循环 | `enabled`、`mode`、`max_tool_iterations` | `action_contracts`、`tool_context`、`lifecycle_control`、`repair_feedback`、`current_dynamic_control` |
| `tool_runtime` | 是否暴露工具和操作权限 | `enabled`、`tool_packages`、`allowed_operations`、`blocked_operations` | `tool_context`、`action_contracts`、`repair_feedback` |
| `skill_runtime` | 是否装载 skill body 和 skill 契约 | `enabled`、`skill_scope`、`denied_skills` | `active_skill`、`runtime_contracts`、`tool_context` |
| `subagent_delegation` | 是否允许调用子 agent | `enabled`、`allowed_subagent_ids`、`max_active_subagents`、`allow_nested_subagents` | `action_contracts`、`tool_context`、`lifecycle_control`、`repair_feedback` |
| `context_memory` | 是否读取和回放上下文记忆 | `enabled`、`provider_visible_replay`、`read_layers` | `context_memory`、`task_state_context` |
| `memory_governance` | 是否允许回答或结果进入记忆候选/长期记忆 | `read_enabled`、`write_candidate_enabled`、`allow_long_term_memory`、`writeback_policy` | `memory_write`、`context_memory`、`repair_feedback` |
| `evidence_read` | 是否注入当前读取证据 | `enabled`、`exact_read_evidence`、`evidence_refs_required` | `evidence_context`、`tool_context`、`repair_feedback` |
| `lifecycle_resume_steer` | pause/resume/steer/retry 的上下文连续性 | `enabled`、`steer_append_only`、`resume_replay_required` | `lifecycle_control`、`current_dynamic_control`、`context_memory` |
| `output_projection` | 投影、最终回答和收口 | `enabled`、`final_commit_required`、`activity_archive` | `runtime_contracts`、`repair_feedback` |
| `recovery_closeout` | 失败恢复和收尾控制 | `enabled`、`recovery_package_allowed`、`structured_failure_required` | `repair_feedback`、`lifecycle_control`、`context_memory` |

这个表的含义是：声明 `subagent_delegation.enabled=false` 时，不需要调用方再手动关闭 `action_contracts/tool_context/lifecycle_control` 里与子 agent 有关的细项；系统组 resolver 应该自动展开并过滤这些线。

```text
系统组 react_loop
  -> action_contracts
  -> tool_context
  -> lifecycle_control
  -> repair_feedback
  -> current_dynamic_control
  -> output_projection

系统组 context_memory
  -> context_memory
  -> task_state_context
  -> memory_write
  -> provider_visible_replay

系统组 skill_runtime
  -> active_skill
  -> runtime_contracts
  -> tool_context

系统组 evidence_read
  -> evidence_context
  -> tool_context
  -> repair_feedback
```

系统组开启后，系统应该产生一份确定的接线计划：

```json
{
  "system_group": "react_loop",
  "enabled": true,
  "capability_groups": [
    "action_contracts",
    "tool_context",
    "lifecycle_control",
    "repair_feedback",
    "current_dynamic_control"
  ],
  "context_segments": [
    "provider_protocol_history",
    "single_agent_turn_tool_call",
    "single_agent_turn_tool_observation",
    "single_agent_turn_followup_action_contract"
  ],
  "prompt_resources": [
    "runtime.rule.tool_use",
    "runtime.rule.multi_tool_scheduling",
    "environment.general.lifecycle.tool_dispatch",
    "environment.general.lifecycle.tool_observation_recovery"
  ],
  "feedback_channels": [
    "tool_result",
    "tool_denial",
    "tool_failure",
    "recovery_instruction",
    "closeout_control"
  ]
}
```

这份计划是平台产物，不是模型自己猜出来的。

## 5. ReAct 系统组设计

### 5.1 ReAct 不是一个 prompt 开关

ReAct 机制不能只写一句：

```text
你可以思考并使用工具。
```

它应该是完整系统组：

```text
reason / decide -> act / tool call -> observe -> recover or continue -> final
```

因此开启 ReAct 后必须接入以下线。

### 5.2 ReAct 开启后的契约

必须接入：

```text
runtime_contracts:
  - 当前轮如何判断任务是否需要执行。
  - 工具调用必须通过 action permit。
  - 工具失败、权限拒绝、用户 steer 如何处理。

action_contracts:
  - 当前回合可执行什么动作。
  - 何时调用工具。
  - 何时停止工具循环。
  - 何时给最终回答。

tool_context:
  - 可用工具目录。
  - 工具参数协议。
  - tool_call_id / observation 对齐规则。
  - 工具观察的压缩或持久化读取规则。

lifecycle_control:
  - task_run start / resume / pause / closeout。
  - 用户暂停后如何继续。
  - 用户 steer 后如何追加新上下文。

repair_feedback:
  - 工具失败反馈。
  - provider protocol 修复反馈。
  - prefix lock 失败或 ledger recovery 控制。
```

### 5.3 ReAct 开启后的上下文段

必须允许进入 provider-visible assembly 的段：

```text
provider_protocol_history
single_agent_turn_tool_call
single_agent_turn_tool_observation
single_agent_turn_followup_action_contract
single_agent_turn_user_steer_context
read_evidence_context
runtime_memory_context
task_state_replay_entry
```

其中有三类语义：

```text
事实上下文：用户输入、读到的证据、工具观察中被确认的事实。
协议历史：assistant tool_calls、tool messages、DeepSeek V4 reasoning_content。
动态控制：当回合 action contract、lifecycle guidance、recovery control。
```

动态控制不一定进入语义记忆，但只要它曾经 provider-visible，就必须按 provider policy 决定是否 replay-only。

### 5.4 ReAct 开启后的反馈

必须接入：

```text
tool_observation
tool_error
tool_permission_denial
missing_tool_result_recovery
followup_prompt_payload
closeout_projection
final_answer_boundary
```

这些反馈不能落到普通事实记忆里。它们应该先进入对应系统组，再由上下文装配策略决定：

```text
是否本轮可见
是否下轮 provider-visible replay
是否语义记忆可见
是否需要压缩替代
```

### 5.5 ReAct 关闭后的效果

如果 `react_loop.enabled = false`：

```text
不装载工具调用契约。
不装载工具目录。
不装载 tool observation history。
不进入 tool followup loop。
不产生 tool repair feedback。
不要求模型输出 tool_calls。
```

但不代表 context memory 关闭。agent 仍然可以做普通对话、读静态上下文、使用已封存记忆，只是没有 act/observe 循环。

## 6. 上下文和运行控制系统组设计

### 6.1 context_memory 系统组

职责：

```text
维护旧上下文封存、provider-visible replay、当前新增上下文 append、语义记忆提交。
```

接入能力组：

```text
context_memory
task_state_context
memory_write
repair_feedback
```

上下文段：

```text
context_memory_prefix
context_append
provider_protocol_history
runtime_memory_context
session_history
session_pinned_facts_context
task_plan_context
task_state_replay_entry
```

核心规则：

```text
旧 provider-visible prefix 原样 replay。
新内容只追加。
语义记忆和 provider replay 分开。
坏 ledger 结构化失败，不静默降级。
```

### 6.2 current_dynamic_control 系统组

职责：

```text
提供当前回合控制信息，而不是长期事实。
```

典型内容：

```text
当前用户输入
当前 runtime cursor
当前 action contract
当前 lifecycle guidance
当前 pending user steer
当前 recovery / closeout 控制
```

注意：

```text
动态控制不是事实记忆。
动态控制是否独立为 dynamic_tail，由 provider physical policy 决定。
如果采用两段式，它会折进 context stream 尾部，但仍可标记为 non-semantic / replay-only。
```

### 6.3 evidence_read 系统组

职责：

```text
把本轮真实读取证据交给 agent。
```

接入能力组：

```text
evidence_context
tool_context
repair_feedback
```

上下文段：

```text
read_evidence_context
evidence_index_cursor
attachment_context_index
editor_context_index
```

规则：

```text
只装载真实读取或已确认索引。
exact read evidence 可以当前轮可见。
大体量工具输出优先持久化，用 ref 或压缩包进入上下文。
```

### 6.4 lifecycle_resume_steer 系统组

职责：

```text
用户暂停、掉线、重发、steer、resume 时不丢上下文。
```

接入能力组：

```text
lifecycle_control
context_memory
current_dynamic_control
repair_feedback
```

规则：

```text
resume 不重新解释旧上下文。
steer 是新 append，不改旧 prefix。
掉线重连只恢复 sealed provider-visible history。
重发不能把旧 messages 重新 normalize。
```

当前需要收束的代码点：

- `backend/harness/loop/single_agent_turn.py`
- `_append_model_messages_without_rewriting_context(...)`
- `_single_agent_turn_followup_prompt_payload(...)`
- `_append_messages_to_accumulated_context(...)`

### 6.5 task_contract_intake 系统组

职责：

```text
控制 agent 是否可以接收、生成或请求任务契约。
```

当前代码中，`request_task_run` 的 `task_contract_seed` 已经被严格规范化。系统执行字段、环境选择、skill 选择等不能塞进任务契约；它们应该由对应系统组接线。

接入能力组：

```text
task_contracts
runtime_contracts
lifecycle_control
repair_feedback
```

开启后：

```text
允许模型提出 request_task_run。
要求 task_contract_seed 包含目标、范围、完成标准和验收证据。
把 goal_contract / plan_contract / lifecycle_contract / acceptance_contract 编译为任务上下文。
```

关闭后：

```text
不允许模型发起新 task_run。
不注入 request_task_run 契约。
不把用户普通对话误升级成任务契约。
```

重要边界：

```text
任务契约只描述任务目标、范围、计划和验收。
environment、tools、skills、subagent、memory write 不是任务契约字段，而是系统组配置。
```

### 6.6 memory_governance 系统组

职责：

```text
控制记忆读取、记忆候选、会话记忆写入和长期记忆写入。
```

这和 `context_memory` 不同：

```text
context_memory 负责读取和回放上下文。
memory_governance 负责是否允许把回答、结果或摘要提交为记忆候选。
```

接入能力组：

```text
context_memory
memory_write
repair_feedback
```

关键开关：

```text
read_enabled
write_candidate_enabled
session_memory_write_candidate_enabled
durable_memory_write_candidate_enabled
allow_long_term_memory
writeback_policy
memory_scope_hint
```

开启长期记忆写入时，也不能直接落正式长期记忆。正确形态是：

```text
主 agent 只提交 memory_write_candidate。
memory_system_agent / memory governance flow 做审核。
通过证据、冲突和必要性检查后再进入正式记忆。
```

关闭后：

```text
可以继续 provider-visible replay。
可以继续读取允许的 readonly memory scopes。
不能把当前回答或工具结果写入长期记忆候选。
```

### 6.7 subagent_delegation 系统组

职责：

```text
控制当前 agent 是否可以调用子 agent，以及子 agent 的范围、并发、结果回传和记忆边界。
```

当前代码已有默认主 agent 子 agent 策略：

```text
allowed_subagent_ids
max_subagent_runs_per_task
max_active_subagents
context_policy = summary_and_refs_only
result_policy = observation_refs_only
allow_nested_subagents = false
```

接入能力组：

```text
action_contracts
tool_context
lifecycle_control
repair_feedback
```

开启后：

```text
暴露 bounded subagent 操作或子 agent lifecycle 工具。
注入子 agent 调用契约。
只向子 agent 传 summary/ref，不把主上下文整包外泄。
子 agent 结果以 observation/ref 回到主上下文。
子 agent 不直接写主长期记忆。
```

关闭后：

```text
不暴露 spawn/send/wait/list/close subagent 工具。
不注入 subagent delegation prompt。
不允许模型把任务分派给 worker agent。
```

子 agent 系统组也不能放进通用能力模板里，因为它涉及：

```text
agent registry
tool authorization
并发预算
上下文隔离
结果投影
记忆写入边界
```

这些都是系统级控制，不是单个 prompt 能力。

## 7. Skill 系统组设计

skill 不是让 agent 自己随意拼 prompt，而是平台提供的可见能力包。

当前代码已有：

- `backend/api/orchestration_catalog.py`
- `backend/task_system/services/assembly_builder.py`
- `backend/task_system/services/assembly_support.py`
- `backend/task_system/services/bindings.py`

### 7.1 skill 装载来源

skill 来源应按以下顺序合并：

```text
environment 默认 skill scope
task / workflow 要求 skill scope
specific_task_assembly_policy.required_refs
agent 当前 action skill intent
denied_skills
```

其中 environment 和 task policy 是平台权威，agent 只能在可见 skill 里选择，不允许越过 denied 列表。

### 7.2 skill 开启后接入内容

开启某个 skill 后，必须接入：

```text
active_skill capability group
skill role/body prompt
skill input/output rule
skill required tools / operations
skill failure or closeout instruction
skill-specific context slots
```

不能只把 skill body 塞进 prompt，而忘记工具权限、输出规则、失败处理。

### 7.3 skill 关闭后

关闭后必须同时移除：

```text
skill body
skill-specific tool guidance
skill-specific output rule
skill-specific repair feedback
skill-specific context claims
```

这样 agent 不会看到一个 skill 的 prompt，却没有对应工具或输出契约。

## 8. Tool 系统组设计

tool 系统组由平台负责授权，不由 agent 自己调整。

当前代码已有操作策略合并：

- `backend/task_system/services/assembly_builder.py`
- `backend/task_system/services/assembly_support.py`
- `backend/api/orchestration_catalog.py`

### 8.1 tool 配置来源

```text
runtime recipe operation policy
registered task operation policy
specific task tool capability requirements
current turn operation policy
permission service current mode
task environment sandbox policy
```

合并后产生：

```text
allowed_operations
denied_operations
required_operations
optional_operations
approval_policy
safety_envelope
```

### 8.2 tool 开启后接入内容

```text
工具 schema / tool catalog
工具调用契约
工具权限说明
工具观察回灌协议
工具失败恢复协议
tool_call_id 对齐规则
provider tool payload
```

### 8.3 tool 关闭后

```text
不发送 tools payload。
不发送工具调用 prompt。
不发送工具观察历史。
不进入 ReAct tool loop。
```

如果 ReAct 开启但 tool group 关闭，系统必须明确降级为 no-tool ReAct 或直接拒绝该配置，不能让 agent 以为可调用工具。

## 9. Environment 系统组设计

environment 是平台已经做好的外显系统，不应该由 agent 自己临场搭配。

当前代码已有：

- `backend/api/task_system.py`
- `backend/task_system/services/assembly_builder.py`
- `backend/task_system/environments`

environment 包含：

```text
environment_prompts
sandbox_policy
file_management
resource_space
memory_space
execution_policy
risk_policy
artifact_policy
observability_policy
lifecycle_policy
default_prompt_cache_scope
```

设计原则：

```text
environment 由 session/task/graph node/platform policy 选择。
agent 可以感知自己所在环境，但不能自己修改环境。
environment 决定默认工具、sandbox、文件空间、资源空间和生命周期边界。
```

这保证“搭建 agent”不是模型自由组合，而是平台把环境、权限、工具、上下文、skills、输出系统全部串联成一个可运行 runtime。

## 10. Provider 物理模型适配

provider adapter 只允许输出物理策略，不允许接管语义系统组。

建议结构：

```json
{
  "provider": "deepseek",
  "model": "deepseek-v4-pro",
  "cache_mode": "automatic_prefix",
  "context_physical_model": "static_context",
  "context_physical_segment_order": [
    "static_prefix",
    "context_memory"
  ],
  "protocol_contract": {
    "thinking_mode": "enabled",
    "tool_call_reasoning_content": "preserve_when_tool_call",
    "multi_round_history": "caller_concatenates_messages"
  }
}
```

### 10.1 两段式

```text
static_prefix -> context_memory
```

适合作为默认生产模型。

动态控制如果本轮发送给 provider，下一轮需要按 provider-visible replay-only 进入 `context_memory`，但不进入语义记忆。

### 10.2 三段式

```text
static_prefix -> context_memory -> dynamic_tail
```

只有 provider strategy 显式声明支持时开启。

三段式下 dynamic_tail 必须永远在最后，不能让新增事实插到 dynamic_tail 后面，也不能让下一轮 stable context 插到旧 dynamic_tail 前面导致 prefix 断裂。

### 10.3 禁止事项

```text
禁止 agent 配置直接修改 provider physical model。
禁止 prompt 文本写“cache prefix”来试图影响 provider。
禁止 provider gateway 在发送前重新排序 messages。
禁止 segment_plan 反向改写 physical assembly。
```

## 11. 目标配置模型

目标配置必须保留默认值。前端 API 不应该每次传完整系统配置，而是传：

```text
default_profile_ref + sparse_overrides
```

后端 resolver 负责把默认 profile、环境策略、agent profile、task policy、provider policy 合并成完整运行配置，再编译成能力线。

### 11.1 默认 profile

默认 profile 是平台内置的完整系统配置。例如主交互 agent 可以有：

```json
{
  "profile_id": "agent_system_profile.main_interactive.default",
  "runtime_profile": {
    "agent_profile_id": "agent:main",
    "provider_strategy_ref": "provider.deepseek.v4.default",
    "environment_ref": "env.coding.vibe_workspace"
  },
  "system_groups": {
    "react_loop": {
      "enabled": true,
      "mode": "tool_calling",
      "max_tool_iterations": 8
    },
    "context_memory": {
      "enabled": true,
      "provider_visible_replay": true,
      "semantic_memory_commit": true
    },
    "skill_runtime": {
      "enabled": true,
      "skill_scope": ["skill.code_editing", "skill.source_review"],
      "denied_skills": []
    },
    "tool_runtime": {
      "enabled": true,
      "tool_packages": ["workspace_read", "workspace_write", "terminal"],
      "approval_policy": "environment_or_permission_service"
    },
    "evidence_read": {
      "enabled": true,
      "exact_read_evidence": true
    },
    "output_projection": {
      "enabled": true,
      "final_commit_required": true
    },
    "task_contract_intake": {
      "enabled": true,
      "accept_task_contract": true,
      "request_task_run_enabled": true,
      "contract_strictness": "canonical_task_contract_seed"
    },
    "subagent_delegation": {
      "enabled": true,
      "allowed_subagent_ids": [
        "agent:knowledge_searcher",
        "agent:codebase_searcher",
        "agent:memory_searcher",
        "agent:pdf_reader",
        "agent:table_analyst",
        "agent:web_researcher",
        "agent:verifier"
      ],
      "max_subagent_runs_per_task": 4,
      "max_active_subagents": 2,
      "context_policy": "summary_and_refs_only",
      "result_policy": "observation_refs_only",
      "allow_nested_subagents": false
    },
    "memory_governance": {
      "enabled": true,
      "read_enabled": true,
      "write_candidate_enabled": false,
      "allow_long_term_memory": false,
      "writeback_policy": "candidate_requires_memory_manager_review"
    }
  },
  "assembly_policy": {
    "frontend_may_override_system_groups": true,
    "agent_may_select_content_groups": false,
    "agent_may_change_environment": false,
    "agent_may_change_provider_physical_model": false
  }
}
```

这里的关键是：

```text
默认 profile 必须完整。
system_groups 是前端和配置系统的声明入口。
context_capability_groups 不是前端声明入口，而是后端编译产物。
runtime_profile 绑定 provider 和 environment。
assembly_policy 锁定 agent 权限边界。
```

### 11.2 前端 API sparse override

前端 API 可以控制系统，但只应该传差异。

例如，用户临时关闭子 agent，并允许本轮使用网页研究 skill：

```json
{
  "profile_ref": "agent_system_profile.main_interactive.default",
  "overrides": {
    "system_groups": {
      "subagent_delegation": {
        "enabled": false
      },
      "skill_runtime": {
        "skill_scope_add": ["skill.web_research"]
      }
    }
  }
}
```

后端展开后才产生完整 wiring manifest：

```json
{
  "resolved_profile_ref": "agent_system_profile.main_interactive.default",
  "system_groups": {
    "subagent_delegation": {
      "enabled": false,
      "removed_prompt_resources": ["runtime.rule.subagent_delegation"],
      "removed_tools": ["spawn_subagent", "send_subagent_message", "wait_subagent"],
      "removed_capability_groups": ["subagent_delegation"]
    }
  },
  "compiled_capability_groups": {
    "action_contracts": true,
    "tool_context": true,
    "lifecycle_control": true,
    "repair_feedback": true
  }
}
```

这个 `compiled_capability_groups` 只用于后端诊断和 prompt/context gate，不要求前端传。

### 11.3 默认与 override 的合并规则

合并规则必须固定：

```text
1. 加载 platform default profile。
2. 合并 agent runtime profile。
3. 合并 environment policy。
4. 合并 task / workflow / graph node policy。
5. 合并前端 sparse override。
6. provider adapter 最后写入 physical policy。
7. 编译 system wiring manifest。
8. 编译 context capability gates。
```

冲突处理：

```text
安全/权限类只能收紧，不能被前端放宽。
environment_ref 不能由普通前端 override 修改。
provider_physical_model 不能由前端 override 修改。
blocked_operations 优先级高于 allowed_operations。
denied_skills 优先级高于 skill_scope_add。
allow_long_term_memory 必须同时满足 task memory profile 和 memory_governance policy。
subagent allow_nested_subagents 默认 false，除非平台 profile 显式允许。
```

这样前端 API 能控制系统，但不会要求 UI 拼完整系统配置，也不会让 agent 或前端绕过平台默认边界。

## 12. 固定运行链路

目标运行链路：

```text
User request / task run
  -> Resolve environment
  -> Resolve provider physical policy
  -> Resolve system group profile
  -> Resolve agent capability profile
  -> Materialize contracts and context candidates
  -> Apply system group + capability gates
  -> Replay sealed provider-visible ledger
  -> Build current append candidates
  -> Single physical assembly
  -> Build provider request
  -> Provider call
  -> Extract provider usage
  -> Confirm provider-visible candidates
  -> Commit projection / output / memory
```

每一步的权威：

| 阶段 | 权威 | 允许做什么 | 禁止做什么 |
| --- | --- | --- | --- |
| Resolve environment | task/session/platform | 选择环境、sandbox、默认资源 | 让 agent 临场改环境 |
| Resolve provider policy | provider adapter | 决定物理模型和协议字段 | 根据 agent prompt 改物理模型 |
| Resolve system groups | runtime profile/task policy | 开关 ReAct、tools、skills、memory | 半开启子系统 |
| Capability gates | context capability policy | 过滤新候选和 prompt resources | 重排旧 ledger replay |
| Ledger replay | provider-visible ledger | 原样回放旧 provider-visible messages | 重新渲染旧 messages |
| Physical assembly | context_assembly | 唯一拼接 provider messages | 让 prompt plan 再排序 |
| Model request | model gateway | 序列化、hash、usage 诊断 | 改 message 顺序 |
| Confirm | model runtime/ledger | provider 成功后确认 candidates | provider 未成功就写 ledger |

## 13. 当前链路需要收束的点

### 13.1 context_assembly 应成为唯一物理排序权威

当前：

```text
context_assembly.py 有 physical order。
prompt_composition.assembly_plan.py 也按 source_order 做 assembly order。
compiler.py 再 materialize。
single_agent_turn.py follow-up 里还可能拆分 dynamic tail。
```

目标：

```text
prompt_composition 只提供来源和语义 metadata。
compiler 只构造 ContextAssemblyInput。
context_assembly 只调用一次并输出最终 provider-visible specs。
follow-up/resume/steer 复用同一个 physical assembly protocol。
```

### 13.2 prompt library 应接入能力组，而不是独立选择内容

目标：

```text
PromptAssemblyRequest.metadata.context_capability_profile
  -> context_capability_decision_for_prompt_resource(...)
  -> 只保留启用系统组/能力组对应的 prompt resources
```

这样可以做到：

```text
react_loop 关掉时，tool dispatch prompt 不会残留。
skill 关掉时，skill body 和 skill output rule 不会残留。
evidence_read 关掉时，read evidence contract 不会残留。
```

### 13.3 compiler 应只处理新候选，不碰旧上下文

目标：

```text
旧 provider-visible history 来自 ledger replay。
新 specs 才进入 capability gate/classifier。
物理排序只发生在 final assembly。
```

禁止：

```text
把旧 ledger replay 重新 classify。
把旧 message 重新 sanitize。
根据 source_order 把 replay 和新内容混排。
```

### 13.4 follow-up / resume / steer 必须同链路

目标：

```text
用户 steer = 新 append。
工具 observation = 新 append。
恢复控制 = 新 append 或 replay-only candidate。
暂停/掉线 = replay sealed prefix 后继续 append。
```

不能出现另一条 follow-up 专用拼接路径。

## 14. 文件级实施方案

### 阶段一：定义系统组配置模型

涉及文件：

```text
backend/runtime/context_management/context_capability_policy.py
backend/task_system/services/assembly_builder.py
backend/task_system/services/assembly_support.py
backend/prompt_library/models.py
```

交付：

```text
ContextSystemGroupProfile
ContextSystemGroupDecision
system_group -> capability_groups 映射表
system_group -> prompt_resources/context_segments/feedback_channels 映射表
```

完成标准：

```text
任意系统组开启/关闭后，可以生成结构化 wiring manifest。
manifest 明确列出契约、上下文段、反馈、tools、skills。
```

### 阶段二：把 prompt library 接到系统组

涉及文件：

```text
backend/prompt_library/assembly.py
backend/prompt_library/packs.py
backend/prompt_library/rules.py
backend/runtime/context_management/context_capability_policy.py
```

交付：

```text
PromptResource 支持 context_capability_group / system_group metadata。
PromptAssemblyService 根据 profile 过滤资源。
过滤结果写入 manifest，不改变排序。
```

完成标准：

```text
关闭 react_loop 后，tool dispatch/tool observation/recovery prompt 不进入 packet。
关闭 skill_runtime 后，active skill body 不进入 packet。
```

### 阶段三：收束物理装配权

涉及文件：

```text
backend/runtime/context_management/context_assembly.py
backend/harness/runtime/compiler.py
backend/prompt_composition/assembly_plan.py
backend/prompt_composition/materializer.py
```

交付：

```text
ContextAssemblyInput
ContextAssemblyResult
single physical assembly entry
prompt_composition assembly_order 改为 source diagnostic，不再声明 physical order
```

完成标准：

```text
provider-visible messages 的最终顺序只来自 context_assembly。
segment_plan 只能诊断，不能反向改 messages。
```

### 阶段四：统一 follow-up / resume / steer 链路

涉及文件：

```text
backend/harness/loop/single_agent_turn.py
backend/runtime/context_management/provider_visible_context_ledger.py
backend/runtime/model_gateway/model_runtime.py
```

交付：

```text
follow-up append-only protocol
steer append protocol
resume replay protocol
provider success candidate confirm protocol
```

完成标准：

```text
旧 prefix 只复制，不 rewrite。
新消息只 append。
暂停、掉线、用户 steer 不丢 provider-visible 历史。
```

### 阶段五：provider adapter 协议细化

涉及文件：

```text
backend/runtime/model_gateway/provider_cache_policy.py
backend/runtime/model_gateway/lightweight_chat_model.py
backend/runtime/model_gateway/model_request.py
backend/runtime/model_gateway/provider_payload.py
```

交付：

```text
provider physical model policy
DeepSeek V4 thinking/tool-call reasoning_content contract
tools/request params cache-sensitive contract
provider usage verifier
```

完成标准：

```text
DeepSeek hit rate 只来自 provider usage。
reasoning_content 是否保留由 provider/model/tool-call contract 决定。
prefix/hash 诊断能解释 miss 来源。
```

## 15. 结构化失败和恢复

以下情况必须结构化失败：

```text
ledger receipt 损坏
ledger schema version 不匹配
adapter contract 不一致
同 item_key / order 的 provider_visible_hash 改变
confirmed entry 缺 provider-visible message
candidate message hash mismatch
```

结构化失败不是禁用上下文，而是表示：

```text
当前旧 provider-visible prefix 不能被证明可信。
```

正确恢复：

```text
记录 recovery_required。
停止重放可疑 provider-visible bytes。
优先使用压缩包 / recovery package 替代上下文继续运行。
从恢复包之后建立新的 append checkpoint。
```

这样可以最大程度保留记忆，同时不把坏 ledger 当成稳定 prefix。

## 16. 验证标准

不以本地预测为最终命中依据。

真实缓存命中只看：

```text
provider usage.prompt_cache_hit_tokens
provider usage.prompt_cache_miss_tokens
```

合格标准：

```text
暖机后，除当前新增内容外，旧 provider-visible prefix 应稳定命中。
生产目标 provider_returned_cache_hit_rate >= 0.95。
低命中时必须能定位到具体 miss 来源。
```

低命中排查顺序：

```text
provider usage
provider payload manifest
message order/hash
ledger replay entries
current append candidates
tools hash
request params hash
reasoning_content/tool_calls contract
follow-up/resume/steer 是否改了旧 prefix
```

## 17. 禁止的设计

```text
禁止让 agent 自己决定 provider physical model。
禁止把“cache prefix”写成模型可见 prompt 语义。
禁止系统组只开契约不接内容，或只接内容不接反馈。
禁止 prompt_composition、segment_plan、provider_gateway 多头排序。
禁止旧上下文重新 sanitize、重新 render、重新 classify。
禁止把 dynamic control 当事实记忆。
禁止把 provider-visible replay-only 当长期语义记忆。
禁止关闭 ReAct 后仍残留 tool observation/followup prompt。
禁止工具权限由 prompt 文本兜底，而不是由 runtime authorization 控制。
```

## 18. 最终目标形态

最终系统应该像接线板一样工作。

```text
Provider 决定底层物理插槽。
Environment 决定运行空间、工具边界、资源边界。
System groups 决定完整子系统是否接入。
Capability groups 决定 prompt/context/feedback 的具体线。
Prompt library 提供内容。
Ledger 封存旧 provider-visible 字节。
Physical assembler 唯一拼接 messages。
Model gateway 只序列化和诊断。
Provider usage 是缓存命中的唯一真实结果。
```

这样，agent 可以被最大限度地搭建和控制：

```text
可以开启或关闭 ReAct。
可以接入或移除某组 tools。
可以接入或移除某些 skills。
可以使用已选 environment。
可以选择是否读取 memory/evidence。
可以获得投影、恢复、收口等平台系统支持。
```

但 agent 不能破坏：

```text
provider 物理模型
环境权限
旧上下文封存
provider-visible append-only
tool authorization
output commit boundary
```

这才是稳定 agent runtime 的装配模型：能力足够灵活，但底层运转机制不漂移。
