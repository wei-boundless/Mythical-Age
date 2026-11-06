# 语义时空上下文结构与提示词投影设计书

日期：2026-06-30  
状态：设计文档，供审阅；本文不直接改运行代码。  
范围：单 agent 上下文拼接、语义时空结构、物理段映射、ContextContractNode 标准化、agent-visible prompt 文案。

## 1. 核心结论

本项目不需要再新增一套上下文物理段，也不需要把 `volatile`、`stable`、`cacheable_prefix` 这类工程词写给模型看。当前已经有足够稳定的物理骨架：

```text
global_static_prefix
-> provider_visible_context_prefix
-> current_turn_tail
-> never_replay_tail
```

优化方向应当是：把这四段物理模型上方的语义空间和时序空间标准化，让每一段上下文在进入 provider request 前先成为一个清楚的语义契约节点，再由物理段负责缓存和 replay。

目标结构：

```text
Semantic Space-Time Contract
-> ContextContractNode
-> Agent-visible semantic prompt projection
-> PhysicalContextPlan lanes
-> ProviderPayloadManifest / provider bytes
```

正式命名建议：

```text
Agent Semantic Space-Time Structure
```

不要把“心跳”“神经”等比喻写进正式代码或 prompt。turn 可以称为 `turn cadence` 或 `turn boundary`，TurnMemory 可以称为 `turn hot ledger`，但正式接口仍以 `TurnMemory`、`ContextContractNode`、`PhysicalContextPlan` 为准。

## 2. 现有代码事实

### 2.1 已有物理段权威

文件：

```text
backend/runtime/context_management/physical_context_plan.py
```

当前物理 lane：

| 物理 lane | 语义用途 | cache spine |
| --- | --- | --- |
| `global_static_prefix` | 长期稳定契约、项目规则、能力索引、工具行动原则 | 是 |
| `provider_visible_context_prefix` | provider success 后已确认、按账本 replay 的旧上下文 | 是 |
| `current_turn_tail` | 本轮新增用户请求、工具结果、证据、上下文 append | 否，本轮是 write candidate |
| `never_replay_tail` | 当前运行边界、恢复反馈、行动合同、当前 turn 状态 | 否，永不 replay |

缓存权威来自物理 lane 和 provider-visible bytes，不来自模型可见段标题。

### 2.2 已有语义段注册表

文件：

```text
backend/runtime/context_management/context_segment_registry.py
backend/runtime/context_management/context_segment_policy.py
```

当前已经注册了这些重要 kind / semantic slot：

| kind / slot | 现有归属 | 目标语义 |
| --- | --- | --- |
| `agent_stable` / `project_instructions_stable` | `static_prefix` | Operating Contract |
| `tool_index_stable` / `capability_catalog` | `static_prefix` | Capability Surface |
| `runtime_memory_context` | `context_memory_prefix` | Selected Memory Hints / Sealed Timeline |
| `provider_protocol_history` | `context_append` | Provider protocol history, success 后进入历史 |
| `current_turn_user_context` | `context_append` | Current User Delta |
| `tool_transcript_delta` | `context_append` | Current Tool / Evidence Delta |
| `read_evidence_context` | `context_append` | Evidence Delta |
| `turn_state_guidance` | `dynamic_tail` | Current Runtime Boundary |
| `turn_attention_index` | `dynamic_tail` | Feedback / Attention Cursor |
| `turn_operating_contract` | `dynamic_tail` | Current turn action contract |
| `runtime_control_signal_tail` | `dynamic_tail` | Recovery / control feedback |

这说明“语义槽位”已经存在。后续不应该绕开 registry 再造散装 prompt 拼接。

### 2.3 已有 Context Contract shadow model

文件：

```text
backend/harness/runtime/context_contract/nodes.py
backend/harness/runtime/context_contract/authority_rules.py
backend/harness/runtime/context_contract/manifest.py
backend/harness/runtime/context_contract/diagnostics.py
```

已经存在 `ContextContractNode`：

```text
semantic_kind
semantic_layer
semantic_time
authority
ttl
visibility
agent_use_contract
commit_policy
replay_policy
cache_tier
```

这是正确方向。当前主要问题是 `authority_rules.py` 仍主要靠 kind 字符串启发式分类，后续应改为从 `context_segment_registry`、`context_segment_policy`、message spec metadata 和 prompt resource metadata 读取显式契约。

### 2.4 TurnMemory 是 turn 间热账本

文件：

```text
backend/runtime/turn_memory/turn_memory_models.py
```

TurnMemory 当前记录：

```text
provider_request_refs
provider_payload_manifest_refs
physical_prefix_frame_id
current_append_hash
assistant_draft_ref
assistant_final_ref
tool_rounds
pending_action_ref
commit_state
recovery_state
```

它的正式定位：

```text
TurnMemory = 当前 turn 与相邻 turn 之间的热账本
```

它不替代 `PhysicalPrefixFrameLedger`，也不修改 confirmed old context。它只保存尚未完全晋升为 confirmed prefix frame 的即时事实、句柄、草稿、工具轮、commit / recovery 状态。

## 3. 目标语义时间模型

语义时间不是物理段名。它描述 agent 如何理解上下文所处的时间域。

| 语义时间 | 中文名 | agent 应理解为 | 典型内容 | 生命周期 |
| --- | --- | --- | --- | --- |
| `Self` | 自我域 | 我是谁、长期遵守什么、通常如何行动 | identity、长期规则、稳定行动原则、稳定能力索引 | stable |
| `Past` | 历史域 | 已经发生、已经观察、已经封存的事实 | sealed timeline、tool observations、旧用户请求、已确认证据 | append-only replay |
| `Present` | 当前域 | 本轮真实发生了什么、本轮边界是什么 | 最新用户输入、当前工具结果、当前权限、当前恢复反馈 | current turn |
| `Future` | 行动域 | 下一步可以怎样推进，但不替 agent 决策 | 可用能力、行动空间、恢复路径、询问/阻塞条件 | current action horizon |
| `HiddenTransport` | 隐藏传输域 | provider API 绑定，不是 agent 记忆 | tools sidecar、tool_choice、response_format、request params | current provider request only |

关键规则：

- `Self` 不能混入当前 turn id、当前工具结果、当前错误。
- `Past` 只能 replay 已发生事实，不能把旧 runtime boundary 当成本轮授权。
- `Present` 只能描述本轮事实和当前边界，不能变成长期身份。
- `Future` 只提供可行动空间，不能替 agent 选择具体动作。
- `HiddenTransport` 不进入 agent-visible message prefix，不写入 sealed history。

## 4. 目标语义空间层级

沿用既有 `L1-L8` 方向，但把每层职责锁清楚：

| 层 | 名称 | 语义时间 | agent-visible | 权威 |
| --- | --- | --- | --- | --- |
| L1 | Operating Contract | Self | 是 | prompt library / project instructions / agent profile |
| L2 | Task Contract | Present / Self-task | 是 | task contract / runtime request facts |
| L3 | Capability Surface | Self / Future | 是 | capability registry / tool catalog manifest |
| L4 | Memory Hints | Past | 是，但必须声明需验证 | memory system |
| L5 | Sealed Evidence Timeline | Past | 是 | provider-visible ledger / physical prefix frame |
| L6 | Current Runtime Boundary | Present | 是 | runtime delta projector / turn operating contract |
| L7 | Feedback and Action Horizon | Present / Future | 是 | admission / tool loop / recovery / TurnMemory projection |
| L8 | Provider Transport Contract | HiddenTransport | 否 | provider payload adapter |

L1-L7 可以投影为 agent prompt。L8 只能投影到 provider request sidecar / request params / manifest。

## 5. 标准语义段列表

模型可见的主段标题只保留少数稳定语义前缀：

```text
Operating Contract
Capability Surface
Sealed Conversation Timeline
Selected Memory Hints
Current Task and User Delta
Current Runtime Boundary
Feedback and Recovery Cursor
Action Horizon
```

隐藏传输层只在 manifest / diagnostics 中存在：

```text
Provider Transport Contract
```

不要再把下面这些内部词作为 agent-visible 主标题：

```text
dynamic_tail
context_append
context_memory_prefix
fixed_context_package
cacheable_prefix
volatile
session_stable
provider_visible_replay_only
current_append_pending_provider_success
```

## 6. 语义段到物理段映射

| Agent-visible 段 | 语义时间 | 物理 lane | cache 行为 | commit / replay | 代码权威 |
| --- | --- | --- | --- | --- | --- |
| Operating Contract | Self | `global_static_prefix` | expected read | static，不进 memory ledger | prompt library / compiler |
| Capability Surface | Self / Future | `global_static_prefix` | expected read | static，不进 memory ledger | capability registry / tool catalog |
| Sealed Conversation Timeline | Past | `provider_visible_context_prefix` | expected read | replay confirmed frame | provider-visible ledger / physical prefix frame |
| Selected Memory Hints | Past | `provider_visible_context_prefix` 或 `current_turn_tail` | 已确认后 expected read，本轮新增 miss | seal on provider success | memory system / context policy |
| Current Task and User Delta | Present | `current_turn_tail` | current miss / write candidate | success 后 seal | request facts / context append |
| Current Runtime Boundary | Present | `never_replay_tail` | excluded | never replay | runtime delta / turn contract |
| Feedback and Recovery Cursor | Present / Future | `never_replay_tail` | excluded | never replay，除非转为历史事实 | admission / recovery / TurnMemory |
| Action Horizon | Future | `never_replay_tail` | excluded | never replay | action surface / runtime boundary |
| Provider Transport Contract | HiddenTransport | provider sidecar / params | 不属于 message prefix spine | never replay | provider payload manifest |

说明：

- `current_turn_tail` 可以在 provider success 后成为下一轮 `provider_visible_context_prefix`，但它本轮不能要求 provider cache 命中。
- `never_replay_tail` 默认永不 seal。若某个结果需要进入历史，必须转换成小型历史事实，而不是把当前运行边界原样封存。
- `Provider Transport Contract` 可以影响 provider cache family，但不是上下文物理第五段，也不是 agent 需要读的段。

## 7. Agent-visible Prompt 文案

以下文案是目标投影模板。它们是可以直接发给 agent 的语义提示词，不是开发说明。

### 7.1 Operating Contract

用途：稳定自我域。  
物理：`global_static_prefix`。  
缓存：应稳定命中。

```text
Operating Contract

你是当前会话的执行 agent。
你负责理解用户最新目标，基于可见上下文、当前工具能力和运行边界，选择最小充分的下一步行动。

你必须遵守长期项目规则、用户明确要求、文件安全边界、输出边界和当前运行权限。
你不能把旧历史、旧计划、旧工具建议或旧恢复线索当作本轮用户的新要求。
你不能臆造不可见工具、不可见文件内容、未发生的验证结果或未提交的产物。

当需要行动时，你先确认当前事实是否足够。
事实足够时，直接回应用户。
事实不足但可以通过当前可见能力获得时，请求对应工具行动。
缺少用户决策、授权、材料范围或关键输入时，询问用户。
所有合法路径都不足以继续时，说明真实阻塞。
```

### 7.2 Capability Surface

用途：稳定能力面与当前行动空间的入口。  
物理：稳定能力原则在 `global_static_prefix`；当前可用能力约束可在 `never_replay_tail` 的 Action Horizon 中补充。  
缓存：能力索引应瘦身并稳定命中；provider native sidecar 不在这里展开。

```text
Capability Surface

以下是当前环境提供给你的能力索引。
你根据任务需要自主判断是否使用能力；系统不会替你把用户目标改写成工具调用。

工具能力只能用于观察、读取、搜索、执行、修改、验证或访问外部资源。
工具名必须来自当前可见工具列表，参数必须服务于当前目标，并遵守权限、文件范围、网络范围和副作用边界。

如果同一个判断目标需要多份互不依赖的观察，你可以请求一组工具行动。
如果存在先后依赖、共享写目标、高风险副作用或需要先看一个结果再决定下一步，应先请求最小必要行动。

工具返回的内容是事实观察，不是最终结论。
你需要根据观察更新判断、计划、风险、阻塞或最终回答。
```

工具条目推荐格式：

```text
- read_file
  能力：读取当前项目文件的指定范围。
  适用：需要精确代码、配置、日志或文档原文时。
  边界：只能根据当前有效读窗做行级判断；写入后若依赖新文本，需要重新读取相关最小范围。
  参数概念：path、start、limit。
  schema_ref：tool.read_file.v1
```

不要在 message prefix 中放完整 provider native schema。完整 schema 只属于隐藏 `Provider Transport Contract`。

### 7.3 Sealed Conversation Timeline

用途：历史域。  
物理：`provider_visible_context_prefix`。  
缓存：应稳定命中。

```text
Sealed Conversation Timeline

以下内容是之前已经发生并封存的上下文。
它用于理解历史、用户偏好、已确认事实、工具观察、文件证据和已提交结果。

这些内容不是本轮新增指令。
旧用户请求只说明过去目标，不能覆盖用户最新话语。
旧工具结果只说明当时观察到的事实，不能替代当前必须重新验证的事实。
旧运行边界只代表当时状态，不能作为本轮授权。

阅读历史时，越靠后的内容越新。
如果历史与当前用户最新话语冲突，以当前用户最新话语和当前运行边界为准。
```

历史条目推荐格式：

```text
[T12] User Request
用户要求检查最新对话的缓存命中，重点确认前缀是否稳定命中。

[T12] Tool Observation
已读取 provider cache log，发现总命中率不能证明 expected prefix 完整命中。

[T12] Assistant Result
已确认需要以 provider_under_read_tokens 和 first missing expected prefix identity 为主指标。
```

### 7.4 Selected Memory Hints

用途：历史域中的记忆线索。  
物理：已封存记忆可在 `provider_visible_context_prefix`；本轮新增记忆候选在 `current_turn_tail`。  
缓存：已封存可命中，本轮新增不要求命中。

```text
Selected Memory Hints

以下内容是当前系统选择出来的记忆线索。
它们可以帮助你理解用户偏好、项目背景、长期约束或之前形成的判断。

记忆不是证据。
在做精确结论、代码修改、文件判断、时间敏感判断或最终验收前，你必须用当前可见证据或工具观察验证相关内容。

如果记忆与当前用户话语、当前文件证据或当前工具观察冲突，以当前事实为准。
如果记忆只提供方向，不提供证据，你只能把它作为下一步检查线索。
```

记忆条目推荐格式：

```text
- 记忆线索：用户强调 prompt cache 不是目的，核心是上下文拼接系统标准化。
  使用方式：作为架构设计偏好和审查重点。
  证据要求：涉及现有代码状态时必须重新读取代码或日志确认。
```

### 7.5 Current Task and User Delta

用途：当前域，本轮新增事实。  
物理：`current_turn_tail`。  
缓存：本轮 miss，provider success 后可成为下一轮历史。

```text
Current Task and User Delta

以下是本轮最新用户请求、补充要求、附件、编辑器上下文或新增任务事实。
这些内容优先于旧历史和旧计划。

你需要先判断用户现在真正要求什么，再决定是回答、检查、写计划、调用工具、询问用户还是说明阻塞。
如果本轮用户要求只是在调整计划，不要直接实施代码。
如果本轮用户要求开始执行，并且已有确认计划，可以按计划推进。

本段内容如果被 provider 成功接受，会在后续回合作为历史 replay。
但在本轮，它仍然是当前新增内容，不能期待 provider prefix cache 命中。
```

本轮输入推荐格式：

```text
User Request
用户要求优化语义时空结构，并写成文档；文档需要列出具体结构、具体语义和可直接给 agent 的提示词内容。

Current Scope
本轮只写设计文档，不实施运行链路改动。
```

### 7.6 Current Runtime Boundary

用途：当前域，本轮有效边界。  
物理：`never_replay_tail`。  
缓存：不进入 cache spine，不 replay。

```text
Current Runtime Boundary

以下边界只对本轮有效。
它说明当前可用动作、工具权限、写入范围、运行状态、预算、恢复状态和输出要求。

你只能基于这里列出的当前边界提交行动。
如果旧历史里出现不同的工具权限、运行状态或恢复要求，旧内容只代表过去，不代表本轮授权。

如果当前边界允许自然回应，你可以直接给用户可见回答。
如果当前边界要求结构化行动，你必须按当前动作合同提交。
如果当前边界显示权限不足、等待用户、审批中、资源不可用或状态不一致，你需要说明如何继续，而不是绕过边界。
```

边界条目推荐格式：

```text
Allowed Actions
- respond
- tool_call
- ask_user
- block

Current Permission Boundary
- 可以读取项目文件。
- 可以新增设计文档。
- 不要修改运行代码。
- 不要新增测试文件。

Current Output Boundary
- 本轮交付一份设计文档路径和简短摘要。
```

### 7.7 Feedback and Recovery Cursor

用途：当前域与行动域之间的反馈游标。  
物理：`never_replay_tail`。  
缓存：不进入 cache spine，不 replay。  
TurnMemory：可提供 pending / recovery / commit 句柄，但不能替代 confirmed history。

```text
Feedback and Recovery Cursor

以下内容说明上一动作或当前运行状态刚刚发生了什么。
你需要把它当作本轮事实反馈，用来修正下一步行动。

如果反馈说明某个动作失败，不要原样重复失败动作。
你需要改变参数、路径、范围、工具、计划，或者说明真实阻塞。

如果反馈说明已有草稿、工具结果、pending commit、frame promotion 或 recovery handle，你只能按当前边界继续处理这些句柄。
你不能从 UI 文本、旧 terminal 输出或旧可见前缀猜测未提交事实。
```

反馈条目推荐格式：

```text
Last Action Feedback
- 动作：写入设计文档。
- 状态：成功。
- 可继续：可以进行静态自检并向用户汇报。

Recovery Handle
- 来源：TurnMemory。
- 状态：commit_pending。
- 合法下一步：只重试 commit，不重跑模型。
```

### 7.8 Action Horizon

用途：行动域。  
物理：`never_replay_tail`。  
缓存：不进入 cache spine，不 replay。

```text
Action Horizon

以下是你当前可以选择的下一步行动空间。
它只提供可选路径，不替你做决定。

你需要选择一个最小充分行动。
如果当前事实足以完成用户请求，直接回应。
如果需要更多事实，选择最小必要工具行动。
如果需要用户裁决，提出一个清楚问题。
如果当前无法合法推进，说明阻塞和继续条件。

不要因为存在工具就调用工具。
不要因为存在旧计划就忽略用户最新调整。
不要为了绕过边界把同一意图换成等价动作。
```

行动项推荐格式：

```text
Available Next Actions
- respond：当文档已经写完并自检通过。
- tool_call：当需要读取代码、检查文档、运行静态命令。
- ask_user：当架构方向存在会改变实施路径的未决选择。
- block：当缺少必要权限、文件或运行状态不可恢复。
```

### 7.9 Provider Transport Contract

用途：隐藏传输域。  
agent-visible：禁止。  
物理：provider sidecar / request params。  
缓存：只由 manifest 诊断，不作为 message prefix 语义段。

```text
Provider Transport Contract is hidden.
Do not project provider tools sidecar, tool_choice, response_format, request params, cache key, thinking config, or provider adapter details into agent-visible memory.
```

工程规则：

- 完整 provider native tool schema 只在 provider request sidecar 中绑定。
- message prefix 的 `Capability Surface` 只写工具用途、边界、关键参数概念和 `schema_ref`。
- provider sidecar 变化可以影响 provider cache family，但不应污染 agent 语义空间。
- L8 节点必须 `visibility=provider_transport`、`semantic_time=HiddenTransport`、`commit_policy=never_commit`、`replay_policy=never_replay`。

## 8. Agent-visible Prompt 拼接骨架

目标拼接顺序：

```text
Operating Contract
Capability Surface
Sealed Conversation Timeline
Selected Memory Hints
Current Task and User Delta
Current Runtime Boundary
Feedback and Recovery Cursor
Action Horizon
```

对应物理顺序：

```text
global_static_prefix:
  Operating Contract
  Capability Surface stable principles

provider_visible_context_prefix:
  Sealed Conversation Timeline
  Selected Memory Hints confirmed replay

current_turn_tail:
  Current Task and User Delta
  Current tool/evidence/memory append

never_replay_tail:
  Current Runtime Boundary
  Feedback and Recovery Cursor
  Action Horizon
```

注意：agent-visible 顺序是语义阅读顺序；provider payload 的最终字节顺序仍由 `PhysicalContextPlan` 和 `ProviderPayloadManifest` 决定。

## 9. ContextContractNode 标准化

目标不是新建第二套 contract，而是把现有 shadow model 变成运行时一致的结构事实。

标准节点字段：

```text
node_id
semantic_kind
semantic_layer
semantic_time
authority
source_ref
scope
ttl
visibility
agent_use_contract
commit_policy
replay_policy
cache_tier
content_mode
refs
supersedes
diagnostics
```

目标枚举：

```text
semantic_kind:
  operating_contract
  task_contract
  capability_surface
  memory_hint
  sealed_evidence
  current_user_delta
  runtime_boundary
  feedback_cursor
  action_horizon
  provider_transport

semantic_time:
  Self
  Past
  Present
  Future
  HiddenTransport

visibility:
  agent_visible
  runtime_hidden
  provider_transport

ttl:
  stable
  append_only
  current_turn
  current_provider_request

commit_policy:
  never_commit
  append_once
  seal_on_provider_success

replay_policy:
  replay_as_history
  current_only
  never_replay

cache_tier:
  provider_global
  session
  append-only
  volatile
  hidden
```

必须满足的不变量：

- agent-visible 节点必须有 `agent_use_contract`。
- L8 节点不能 agent-visible。
- `Present` / `Future` 节点不能进入 stable cache tier。
- `current_provider_request` 节点必须 `never_commit`。
- `runtime_boundary` replay 后只能是历史事实，不能保持当前授权语义。
- `provider_transport` 不能写入 provider-visible ledger。

## 10. 权威链路

目标权威链：

```text
RequestFacts
-> ContextSegmentRegistry / ContextSegmentPolicy
-> ContextContractManifest
-> Prompt Projection
-> PhysicalContextPlan
-> ProviderPayloadManifest
-> Provider request bytes
-> Provider success
-> ProviderVisibleLedger / PhysicalPrefixFrameLedger
-> TurnMemory handoff/recovery if not fully committed
```

各层职责：

| 层 | 可以做 | 禁止做 |
| --- | --- | --- |
| RequestFacts | 捕获用户输入、附件、编辑器事实 | 改写用户目标 |
| ContextSegmentRegistry | 声明 kind 的默认 section / slot / source | 决定 provider bytes 顺序 |
| ContextSegmentPolicy | 决定 section、slot rank、commit/replay policy | 生成 agent prompt 长文 |
| ContextContractManifest | 标准化语义层、时间、可见性、用途 | 重新排序 confirmed history |
| Prompt Projection | 把节点投影为 agent 可理解文案 | 暴露 provider sidecar / 内部 cache label |
| PhysicalContextPlan | 分配四段 physical lane | 重新解释任务语义 |
| ProviderPayloadManifest | 记录 provider serialized bytes、transport、cache boundary | 从旧 metadata 猜语义权威 |
| Ledger / Frame | 封存 provider success 后的历史 | 修改已 confirmed old context |
| TurnMemory | 保存 turn 间即时状态、恢复句柄 | 替代 confirmed prefix frame |

## 11. 与缓存机制的关系

语义时空结构不是为了“装饰 prompt”，而是为了让稳定内容自然形成稳定 provider prefix。

缓存判断规则：

```text
expected read:
  global_static_prefix
  provider_visible_context_prefix confirmed replay

normal miss:
  current_turn_tail
  never_replay_tail
  hidden provider transport delta
```

健康判断优先级：

```text
1. expected prefix 是否完整命中
2. provider_under_read_tokens 是否为 0
3. first_missing_expected_prefix_identity 是否为空
4. 总 hit_rate 只作为辅助指标
```

这意味着：即使命中率显示 77.19%，只要 expected prefix 没有完整命中，仍然是缓存前缀链路问题。

## 12. 优化实施建议

本文是设计文档。后续如果开始实现，建议分阶段执行。

### Phase 1：显式语义路由表

目标：替换 `authority_rules.py` 中主要靠字符串启发式的分类。

涉及：

```text
backend/harness/runtime/context_contract/authority_rules.py
backend/runtime/context_management/context_segment_registry.py
backend/runtime/context_management/context_segment_policy.py
```

动作：

- 为 context kind 增加或派生显式 `semantic_kind`、`semantic_layer`、`semantic_time`、`visibility`。
- `authority_rules.py` 优先读显式字段，缺失时才诊断为 `semantic_contract_missing`。
- 不新增 agent-visible 内部标签。

### Phase 2：Prompt Projection 模板化

目标：把本文第 7 节的段落变成统一投影模板。

涉及：

```text
backend/harness/runtime/compiler.py
backend/prompt_library/rules.py
backend/prompt_library/packs.py
```

动作：

- prompt library 继续管理稳定规则。
- compiler 只负责把 ContextContractNode 按模板投影。
- 各段 title 使用本文标准段名。
- 移除 `dynamic_tail`、`context_append` 等开发字段作为模型可见主标题的路径。

### Phase 3：Present / Future 拆分

目标：动态尾不再是一个不可诊断大文本块。

涉及：

```text
backend/harness/runtime/dynamic_context
backend/harness/runtime/turn_operating_contract.py
backend/runtime/turn_memory/turn_memory_projector.py
```

动作：

- runtime boundary 只描述当前事实和权限。
- feedback cursor 只描述上一动作反馈和恢复句柄。
- action horizon 只描述可选下一步行动空间。
- 三者都在 `never_replay_tail`，但成为不同 ContextContractNode。

### Phase 4：History replay 历史语义封口

目标：已封存历史不再被误读为当前授权。

涉及：

```text
backend/runtime/context_management/provider_visible_context_ledger.py
backend/runtime/context_management/physical_prefix_frame_ledger.py
backend/runtime/context_management/physical_context_assembler.py
```

动作：

- replayed runtime boundary 若必须保留，只投影为 historical note。
- confirmed old context 不重排、不重写、不重新摘要。
- `provider_visible_context_prefix` 中的每条历史都有历史用途说明或 metadata。

### Phase 5：语义 Inspector 与缓存诊断对齐

目标：前端能看到语义时空结构，不只看 token 数。

涉及：

```text
backend/harness/runtime/context_contract/inspection_payload.py
backend/runtime/prompt_accounting/provider_cache_bus.py
frontend/src/components/chat/ChatPanel.tsx
```

动作：

- 展示 L1-L8、Self/Past/Present/Future/HiddenTransport。
- 展示物理 lane、cache expectation、commit/replay policy。
- 展示 first missing expected prefix identity。
- hit rate 放在辅助位置，不作为健康主结论。

## 13. 验证方式

不新增测试文件。后续实施后使用静态审查、编译检查和真实运行验证。

静态审查：

```powershell
rg -n "dynamic_tail|context_append|context_memory_prefix|volatile|cacheable_prefix" backend/harness backend/runtime -g "!**/design_docs/**"
rg -n "semantic_time|semantic_layer|agent_use_contract|provider_transport" backend/harness/runtime/context_contract backend/runtime/context_management
rg -n "Provider Transport Contract|Operating Contract|Action Horizon" backend
```

编译检查：

```powershell
python -m py_compile backend/harness/runtime/context_contract/nodes.py backend/harness/runtime/context_contract/authority_rules.py backend/harness/runtime/context_contract/manifest.py backend/harness/runtime/context_contract/diagnostics.py backend/runtime/context_management/context_segment_registry.py backend/runtime/context_management/context_segment_policy.py backend/runtime/context_management/physical_context_plan.py
```

真实运行验收：

```text
固定后端：http://127.0.0.1:8003
固定前端：http://127.0.0.1:3000
```

验收点：

- provider messages 中 agent-visible 段名是语义标题，不是内部 lane 名。
- L8 provider transport 不进入 message prefix。
- `global_static_prefix` 和 `provider_visible_context_prefix` 是 expected read。
- `current_turn_tail` 和 `never_replay_tail` 不被算作本轮 expected cache read。
- 第三轮起 expected prefix 完整命中，`provider_under_read_tokens == 0`。

## 14. 禁止反模式

- 为了缓存命中删除 agent 必须理解的当前边界。
- 把 `volatile`、`session_stable`、`cacheable_prefix` 写成 agent-visible 前缀。
- 把 provider native tools sidecar 复制进 message prefix。
- 把旧 runtime boundary replay 成当前授权。
- 把 memory hint 当作 evidence。
- 在 compiler、policy、provider payload、ledger、frontend 多处重复定义缓存健康口径。
- 保留旧 prompt 拼接链作为“兼容兜底”。
- 在旧壳上再包一层新语义模型，导致两套权威并行。

## 15. 推荐裁决

本项目应以现有四段式物理模型为缓存和 replay 的唯一物理权威，以 `ContextContractNode` 作为语义时空标准化节点，以本文的 8 个 agent-visible 段作为提示词投影规范。

最终结构：

```text
Self:
  Operating Contract
  Capability Surface stable principles

Past:
  Sealed Conversation Timeline
  Selected Memory Hints

Present:
  Current Task and User Delta
  Current Runtime Boundary
  Feedback and Recovery Cursor

Future:
  Capability Surface current availability
  Action Horizon

HiddenTransport:
  Provider Transport Contract
```

对应物理：

```text
Self -> global_static_prefix
Past -> provider_visible_context_prefix
Present append -> current_turn_tail
Present boundary / Future horizon -> never_replay_tail
HiddenTransport -> provider sidecar / request params
```

这样可以同时满足三件事：

- agent 读到的是清楚的任务语义和行动边界。
- provider 看到的是稳定、可复算的物理 prefix。
- 工程诊断能定位每个上下文片段的语义时间、物理 lane、缓存预期、commit/replay 策略和权威来源。
