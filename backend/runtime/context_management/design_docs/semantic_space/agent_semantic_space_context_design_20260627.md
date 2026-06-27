# Agent 语义空间上下文设计规范

日期：2026-06-27

本文档用于约束后续上下文重构。它先定义 agent 实际收到并理解的语义空间，再约束物理拼接、缓存、工具能力、执行许可和 fork 交接。目标不是机械压 token，而是把上下文组织成成熟 agent 能稳定工作的时间链。

## 1. 核心结论

当前已经修复的是物理拼接断层：

```text
global_static_prefix
-> provider_visible_context_prefix
-> current_turn_tail
```

最新实测证明旧 message hash 已经按前缀连续追加。但缓存命中仍不合格，根因不再是物理顺序，而是语义空间分配还不成熟：

- 工具契约同时以 `tool_schema_catalog`、`tool_index_stable`、provider sidecar 三份形式出现。
- 旧上下文排在巨大工具/稳定前缀之后，DeepSeek 没有完整命中后半段旧上下文。
- runtime control 被作为历史字节封存后，虽然物理连续，但语义上需要明确“只读历史，不是当前授权”。
- provider 传输结构和 agent 可理解语义上下文混在一起，导致缓存和语义都变重。

因此后续重构必须先建立语义空间主链：

```text
Stable Operating Contract
-> Tool Capability Surface
-> Sealed Conversation Timeline
-> Current Turn Delta
-> Current Runtime Boundary
-> Provider Transport Contract
```

其中前五层是 agent 语义空间，第六层是 provider API 传输结构，不是 agent 历史上下文。

## 2. 成熟 Agent 原则

### 2.1 语义优先于开发字段

Agent 不应该看到这些开发式标签作为主要含义：

```text
dynamic_tail
context_append
runtime node
cache lane
fixed_context_package
```

Agent 应该看到的是可执行语义：

```text
Operating Contract
Tool Capability Surface
Sealed Conversation Timeline
Current User Request
Current New Evidence
Current Runtime Boundary
```

开发字段只用于编排和诊断，不能替代语义前缀。

### 2.2 旧上下文字节不可变

所有已经 provider success 并进入 ledger 的旧上下文：

- 不改一个字。
- 不重新摘要。
- 不重排。
- 不换标题。
- 不从 session history 重新渲染。

旧上下文只能按 provider-visible ledger entry index 线性 replay。新策略只能影响未来新增 entry。

### 2.3 语义可变不等于物理可变

同一物理段内的处理方式必须一致。

```text
provider_visible_context_prefix
```

里面可以有不同语义：

- active memory
- historical-only replay
- tool transcript
- runtime replay-only record
- fork inherited parent context

但它们都按同一条 ledger 时间线插线。语义差异只写入 metadata 和 agent-visible preamble，不改变物理位置。

### 2.4 Provider 传输契约不是上下文记忆

Provider tool sidecar、tool choice options、request params 属于 API transport。

它们可以参与 transport contract hash 和 provider payload manifest，但不应该作为大段 agent 记忆重复进入 message prefix。

## 3. 六层语义空间

### 3.1 Stable Operating Contract

Agent 可见标题：

```text
Operating Contract
```

Agent 语义：

```text
你是当前任务的执行 agent。
以下规则长期有效，除非后续明确更新。
你需要遵守身份、任务边界、输出格式、权限和项目协作要求。
```

内容：

- agent identity / role。
- 项目固定规则。
- 输出契约。
- 权限边界。
- 文件、工具、运行安全原则。
- 稳定的读文件策略和 evidence policy。

物理位置：

```text
static_prefix -> global_static_prefix
```

更新规则：

- 只在项目规则、agent profile、工具体系版本变化时更新。
- 不得混入当前用户请求、当前 turn id、当前 runtime 状态。

缓存目标：

- 应稳定命中。
- 体积应克制，不能把工具 full schema、运行快照或 session facts 放进来。

### 3.2 Tool Capability Surface

Agent 可见标题：

```text
Tool Capability Surface
```

Agent 语义：

```text
以下是当前执行环境可提供给你的工具能力索引。
你负责根据任务语义选择是否请求工具。
系统只在你提交结构化 tool_call 后校验工具名、参数、权限、文件证据新鲜度和副作用边界，并执行、拒绝或返回观察。
如果同一语义动作需要一组工具请求，你可以使用 tool_calls[]；它仍然属于一个 tool_call action，不代表多轮反馈或多个控制动作。
```

内容：

- 工具名称。
- 工具用途。
- read/write/network/side-effect 分类。
- 使用边界、权限入口和常见误用。
- 关键参数概念，不放完整 JSON schema。
- schema ref / catalog hash。
- 常见误用规则。

禁止内容：

- 完整 provider native tool schema。
- 每个字段的大型 schema detail。
- 和 provider sidecar 重复的 parameters JSON。
- 每轮动态绑定结果伪装成稳定工具全集。

物理位置：

```text
static_prefix -> global_static_prefix
```

Provider transport：

```text
model_request.tools
```

规则：

- message prefix 里的 tool capability surface 是 agent 语义索引。
- provider sidecar 是 provider 调用结构。
- 两者用同一 schema ref 对齐，但不能都承载完整 schema。

### 3.3 Sealed Conversation Timeline

Agent 可见标题：

```text
Sealed Conversation Timeline
```

Agent 语义：

```text
以下内容是之前已经发生过的上下文。
它用于理解历史、用户约束、工具结果和已确认事实。
它不是本轮新增指令。
如果其中包含过去的运行边界，只能视为历史记录，不能当作当前授权。
```

内容：

- previous user requests。
- assistant/tool protocol transcript。
- sealed read evidence refs。
- sealed tool observations。
- sealed memory facts。
- provider-visible runtime replay-only record。
- fork inherited parent entries。

物理位置：

```text
context_memory_prefix -> provider_visible_context_prefix
```

更新规则：

- 只从 provider-visible ledger confirmed entries 回放。
- 按 entry index 排序。
- 旧 entry 不重写。

Agent 时序规则：

- 越靠后越新。
- 本轮最新控制边界优先于旧历史边界。
- 旧 user request 是历史目标，不覆盖本轮用户请求。
- 旧 tool result 是已发生事实，不重复作为本轮新观察。

Fork 规则：

- child 首轮继承 parent fork anchor 之前的 confirmed entries。
- parent entries 不复制改写；child 后续新增 entries 写入 child scope。
- fork 语义继承和 provider prefix 继承必须以同一 ledger anchor 为准。

### 3.4 Current Turn Delta

Agent 可见标题：

```text
Current Turn Delta
```

Agent 语义：

```text
以下是本轮刚新增的用户请求、工具结果或任务事实。
这些内容优先于旧历史。
如果 provider 成功接受本轮请求，它们会作为历史在下一轮只读 replay。
```

内容：

- current user request。
- 本轮用户补充 steer。
- 本轮新增 read evidence refs。
- 本轮 tool call / tool result delta。
- 本轮新增 memory facts。
- 当前任务状态新增量。

物理位置：

```text
context_append -> current_turn_tail
```

更新规则：

- 本轮可见。
- provider success 后封存。
- 下一轮从 ledger replay 到 `provider_visible_context_prefix`。
- 不得在下一轮继续作为 current tail 重复出现。

缓存规则：

- 同请求不要求命中。
- 它是正常 miss 的主要来源。
- 体积目标应小，normal follow-up 最好低于 500-1000 tokens。

### 3.5 Current Runtime Boundary

Agent 可见标题：

```text
Current Runtime Boundary
```

Agent 语义：

```text
以下边界只对本轮有效。
它说明当前可用动作、工具能力边界、执行权限状态和恢复要求。
如果这段内容以后作为历史 replay 出现，只能用于理解过去发生了什么，不能作为当前授权。
```

内容：

- current allowed action types。
- 当前 tool capability surface refs。
- 当前 action permit / execution boundary refs。
- 当前 recovery instruction。
- 当前 active skill instruction。
- 当前 exact editor/UI state。
- 本轮 lifecycle trigger。

物理位置：

优先：

```text
dynamic_tail -> never_replay_tail
```

如果为了 provider prefix continuity 必须封存，应转化为 replay-only historical record：

```text
context_append -> current_turn_tail
provider success
-> context_memory_prefix -> provider_visible_context_prefix
```

但必须带 agent-visible 过期说明：

```text
这段运行控制上下文只在原始请求有效。
后续 replay 时只表示历史，不代表当前授权。
```

优化方向：

- 不应长期封存完整 runtime projection。
- 应拆成小型 historical runtime fact，例如“上一轮允许工具调用并完成 OK”。
- 当前最新 runtime boundary 应始终在消息流后方，且 agent 可明确识别为本轮有效。

### 3.6 Provider Transport Contract

Agent 可见标题：

```text
不进入 agent-visible message prefix
```

内容：

- provider sidecar。
- tool_call_options。
- provider params。
- response_format。
- model / thinking / user id 等 cache-sensitive params。

物理位置：

```text
provider payload sidecar
```

规则：

- 它是 provider API 结构，不是会话记忆。
- 可以 hash 和审计。
- 不能以大段自然语言或 JSON schema 重复放进 message prefix。
- DeepSeek 自动缓存统计会把 sidecar 纳入 prompt/miss 预算，因此 sidecar 必须按当前请求显式绑定且最小化。

### 3.7 Current Tool Binding Sidecar

`provider tool sidecar` 的语义不是稳定工具前缀，而是本轮 provider 传输绑定：

```text
本轮允许模型调用哪些工具；
本轮工具调用必须遵守什么结构化 schema；
本轮是否允许 parallel tool calls；
本轮 tool_choice 是什么。
```

它是 runtime-private transport adapter 的附属物，而不是 `Tool Capability Surface`。agent 可见层只出现一套语义动作：`tool_call`。

因此它的语义应标记为：

```text
current_turn_tool_binding_sidecar
never_replay
current_turn_only
not_message_prefix_cacheable
```

硬规则：

- 普通无工具 turn 不发送 provider sidecar。
- 只有明确 transport 模式或 agent 已声明工具需求后需要绑定的工具才进入 sidecar。
- sidecar 不进入 sealed timeline。
- sidecar 不作为 stable transport prefix 预期命中。
- sidecar 的 schema hash 可用于验证，但不能用“稳定 hash”推断 DeepSeek 一定会缓存其后的全部 message prefix。
- message 中的 `Tool Capability Surface` 只提供工具用途、能力边界、关键参数概念和 schema refs，不重复完整 schema。
- 不允许用末端 `return []` 伪装关闭链路；是否绑定 sidecar 必须来自隐藏 `tool_transport_policy`。

当前已确认的问题：

```text
provider wire body:
tools sidecar -> messages stable prefix -> old context -> current tail

local cache model:
messages stable prefix -> old context
tools sidecar is excluded from message prefix
```

这会让本地 prefix 账本和 DeepSeek 实际前缀缓存模型错位。优化方向不是把 sidecar 继续稳定化，而是把它移出 agent 语义空间，作为隐藏 adapter 的按需传输线。

2026-06-27 已落地的语义裁决：

| 项 | 旧逻辑 | 新逻辑 |
|---|---|---|
| sidecar 身份 | 稳定工具传输契约的一部分 | `current_turn_tool_binding_sidecar` |
| sidecar 生命周期 | 每轮默认携带全量工具 schema，或在末端硬编码 `[]` 假装关闭 | `tool_transport_policy` 默认 `json_action`；只有 profile/runtime/model 明确切到 `provider_native` 时才绑定 provider sidecar |
| sidecar 校验 | 必须 exact match 全量 `tool_index_stable` | 如果某个 transport 边界显式绑定 provider sidecar，它只能是稳定工具目录的合法子集，且每个 schema_ref 一致 |
| message 工具前缀 | `tool_schema_catalog` 带完整 provider schema，`tool_index_stable` 带详细字段 schema | 删除 `tool_schema_catalog` message；由 `Tool Capability Surface` / `tool_index_stable` 单段承载工具名、用途、关键字段名、使用边界、schema_ref |
| 普通 turn | 系统预先替 agent 选择工具 sidecar | agent 只看到 `tool_call` action；runtime 根据隐藏 transport policy 选择 JSON action 或 provider sidecar |

当前代码权威：

| 权责 | 文件 | 说明 |
|---|---|---|
| agent 工具决策 | `backend/harness/loop/model_action_protocol.py` | agent 通过 `action_type=tool_call` 和 `tool_call={tool_name,args}` 自主声明工具需求 |
| hidden transport policy | `backend/harness/runtime/assembly.py` | 解析 profile/runtime/model 的 `tool_transport_policy`，默认 `json_action`，provider sidecar 只在明确选择时开启 |
| provider sidecar adapter | `backend/harness/runtime/tool_transport_adapter.py` | 根据隐藏 policy 把当前可见工具绑定成 provider sidecar；不生成 agent-visible catalog message |
| single-agent transport wiring | `backend/harness/loop/single_agent_turn.py` | 从 packet diagnostics 读取 hidden policy，按 policy 挂载或关闭 `model_request.tools`，不再写死空数组 |
| provider schema 生成 | provider payload / shared canonical schema | 完整 schema 只服务 provider native binding；稳定 message 前缀只放 schema_ref |
| 稳定工具目录 | `backend/harness/runtime/tool_catalog_manifest.py` | `model_visible_catalog` 不再输出完整 `input_schema_summary`，只输出 schema_ref 与瘦身后的工具能力 contract |
| sidecar drift 诊断 | `backend/runtime/model_gateway/provider_payload.py` | `native_tool_binding_schema` 验证 actual sidecar 是 stable tool catalog 的合法子集 |

实测证据：

```text
session-58c9b0dcc40e4e5c
显式 no-tool turn 后：
request 17: 47247 prompt / 43776 cached / hit_rate 0.9265 / miss 3471
request 19: 48981 prompt / 43776 cached / hit_rate 0.8937 / miss 5205
segment map: tool_segments=[]
```

这证明 provider sidecar 是实际 cache break 贡献项。第 15 轮同类请求在携带 sidecar 时约为：

```text
prompt_tokens=50579
cached_tokens=40832
hit_rate=0.8073
native_tool_binding_schema≈3974 tokens
```

因此 sidecar 不能继续伪装成稳定前缀；它必须是 `Provider Transport Contract` 下的 current-turn tool binding。

边界修正：

```text
系统不得根据当前用户文本替 agent 判断“该读、该写、该查、该继续执行”。
系统只能提供工具语义索引、执行 agent 已声明的 tool_call、按权限/安全边界拒绝或返回观察。
```

因此本项目的工具链不能包含系统语义分类器。工具相关职责应拆分为：

- `Tool Capability Surface`：稳定告诉 agent 当前执行环境有哪些工具能力。
- `Action Permit`：agent 提交结构化 action 后，系统按权限、安全、副作用和运行状态执行或拒绝。
- `Read Evidence Reuse Contract`：`read_file` 收到具体读取请求后，系统只判断既有 exact evidence 是否仍覆盖且新鲜；可复用则返回小型 unchanged observation，不重复全文。
- `Current Tool Binding Sidecar`：provider transport 需要时绑定当前请求的结构化 schema；它不是会话记忆，也不是系统语义分类器。

## 4. 时序模型

每轮按以下逻辑变化：

```text
T0 stable contract
T0 sealed timeline
T1 current user delta
T1 current runtime boundary
provider success
T1 current delta -> sealed timeline entry
T2 current user delta
T2 current runtime boundary
```

核心规则：

- `sealed timeline` 是 append-only 历史。
- `current delta` 是本轮新增。
- `current runtime boundary` 是本轮有效控制。
- 旧 runtime boundary replay 后只能作为 historical context。
- 如果同一语义在旧 timeline 和 current delta 同时出现，以 current delta 为本轮新增事实。

Agent 时序前缀应显式表达：

```text
以下是历史，只读。
以下是本轮新增，优先处理。
以下是当前运行边界，只在本轮有效。
```

## 5. 工具语义和工具传输的分离

### 5.1 已修正的旧问题

旧链路曾经有三份工具表达：

```text
tool_schema_catalog message
tool_index_stable message
provider sidecar
```

这会导致：

- message prefix 过胖。
- provider sidecar 每轮增加 miss 预算。
- agent 读到的工具信息像开发数据包，不像工具能力索引。
- DeepSeek 命中旧上下文前已经被大量工具契约占据 prefix 空间。

当前主链已删除 `tool_schema_catalog` message。agent 可见工具语义只由 `Tool Capability Surface` / `tool_index_stable` 承载；provider sidecar 只作为当前请求 transport 绑定。

### 5.2 目标结构

语义空间：

```text
Tool Capability Surface
```

只包含：

- tool name。
- purpose。
- read/write/side-effect。
- when to use。
- when not to use。
- key argument concepts。
- schema_ref。
- tool_contract_summary。

Provider transport：

```text
current tool binding sidecar
```

只包含当前 provider 请求显式绑定的可调用工具 schema。它不是会话记忆，不进入 message prefix，不作为稳定缓存前缀。

### 5.3 Tool Choice 与 Action Permit

系统不得根据用户文本替 agent 选择工具。成熟链路应分四层：

- `Tool Capability Surface`：稳定展示当前执行环境可用工具能力。
- `Model Action`：agent 根据任务语义自主提交 `tool_call` 或其它 action。
- `Action Permit`：系统只校验已提交 action 的工具名、参数、权限、副作用和运行边界。
- `Tool Observation`：执行、拒绝或复用证据后返回观察，供 agent 继续判断。

稳定工具能力：

```text
tool universe / capability catalog
```

当前工具执行请求：

```text
agent_declared_tool_call
```

如果 agent 请求的工具当前不可执行，系统返回 action permit denial / tool observation，而不是替 agent 改成另一个工具或另一个任务计划。

## 6. 上下文分配表

| 语义层 | Agent 可见标题 | section | physical lane | 是否封存 | 缓存预期 |
|---|---|---|---|---:|---|
| 稳定运行契约 | `Operating Contract` | `static_prefix` | `global_static_prefix` | 否 | 应稳定命中 |
| 工具能力表 | `Tool Capability Surface` | `static_prefix` | `global_static_prefix` | 否 | 应稳定命中，必须瘦 |
| provider native schema | 不进 message | sidecar | sidecar | 否 | Current Tool Binding，DeepSeek 可能计入 miss，必须按当前请求绑定 |
| 已封存历史 | `Sealed Conversation Timeline` | `context_memory_prefix` | `provider_visible_context_prefix` | 已封存 | 应稳定命中 |
| 本轮用户请求 | `Current User Request` | `context_append` | `current_turn_tail` | 成功后封存 | 本轮 miss |
| 本轮工具结果 | `Current New Evidence` | `context_append` | `current_turn_tail` | 成功后封存 | 本轮 miss |
| 当前运行边界 | `Current Runtime Boundary` | `dynamic_tail` 或 replay-only append | `never_replay_tail` 或 `current_turn_tail` | 默认不封存 | 本轮 miss |
| UI/diagnostics/progress | 不进 provider context | none | none | 否 | 不计入 |

## 7. Prefix 设计规则

Agent-visible prefix 必须是语义说明，不是开发标签。

正确：

```text
Sealed Conversation Timeline
以下内容是已经发生过的历史。它只用于理解上下文和已确认事实。
其中旧运行控制只代表当时状态，不代表本轮授权。
```

错误：

```text
context_memory_prefix
provider_visible_replay_only
dynamic_tail replay
```

正确：

```text
Current Runtime Boundary
以下边界只对本轮有效。你只能基于这里列出的当前可用动作和工具执行。
```

错误：

```text
这是 runtime 节点。
根据任务图执行。
```

## 8. 缓存目标

常态 follow-up 的目标：

```text
cached_tokens / prompt_tokens >= 0.95
```

允许 miss：

- current user delta。
- current tool result delta。
- minimal runtime boundary。
- provider sidecar 的当前请求绑定小集合。

不允许长期 miss：

- 旧 timeline。
- 稳定 operating contract。
- 稳定 tool capability surface。
- 大型 tool schema catalog。
- 完整 runtime projection。
- 完整重复 read result。

当前要达标，需要优先降低：

1. `Tool Capability Surface` message 体积。
2. provider sidecar 工具数量。
3. runtime control 封存体积。
4. memory maintenance current delta 体积和调度位置。

## 9. 实施顺序

### Phase S1：语义标题和分层统一

目标：

- 所有 agent-visible context 均使用语义标题。
- 不再把 `dynamic_tail`、`context_append`、`fixed_context_package` 等开发标签作为模型可见主语义。

改动点：

- prompt materializer。
- runtime payload spec title。
- context segment policy metadata 到 agent-visible preamble 的投影。

验收：

- provider messages 中出现 `Operating Contract`、`Sealed Conversation Timeline`、`Current Turn Delta`、`Current Runtime Boundary` 等语义标题。
- 不出现开发标签作为 agent 主标题。

### Phase S2：工具能力表单源化

目标：

- 删除 `tool_schema_catalog` message。
- `tool_index_stable` / `Tool Capability Surface` 不重复 schema summary 大包。
- message prefix 中只保留工具能力、schema refs、关键使用规则。

改动点：

- `backend/harness/runtime/tool_catalog_manifest.py`
- `backend/harness/runtime/compiler.py`

验收：

- `Tool Capability Surface` 从约 15K tokens 降到可控范围。
- schema hash 仍 matched。
- agent 能理解工具用途和执行边界。

### Phase S3：Provider Tool Transport Boundary

目标：

- 不再每轮默认发送全部 provider sidecar。
- single-agent turn 默认走 `json_action`，agent 使用结构化 `tool_call` action 自主声明工具需求。
- 如果某个运行模式显式需要 `provider_native` transport，只能绑定当前可见工具集合，不能由系统根据用户文本推断工具选择。
- 将 provider sidecar 诊断为 `current_turn_tool_binding_sidecar`，不再作为 stable transport prefix 组件预期命中。

改动点：

- `backend/harness/loop/single_agent_turn.py`
- runtime tool plan / transport sidecar policy。
- provider payload diagnostics。
- `backend/harness/loop/model_action_protocol.py` 解析 `tool_call` / `tool_calls[]`，并为每个工具调用生成稳定 `tool_call_id`。
- `backend/harness/runtime/compiler.py` 的反馈契约明确批量工具调用只需要批次级公开说明，观察返回后按语义变化汇总反馈。
- `backend/prompt_library/rules.py` 的固定工具契约已统一为：`action_type=tool_call`，单工具用 `tool_call`，同一判断目标内的一组工具用 `tool_calls[]`；静态规则不再说持续任务不能批量工具 action。
- runtime control / contract feedback 的 agent 可见文本必须写成行动语义：发生了什么、你现在可采取什么动作、是否需要自然回应、工具是否还能继续；不得把“系统反馈角色”“用户正文通道”“事实边界”等开发分类写给 agent。
- 系统发给 agent 的纠错反馈属于 `current_turn_tail` 的行动校正段：它只能说明上一轮动作为何未被接受、当前允许动作、是否还能调用工具、用户可见回应应放在哪些字段；不能替 agent 选择计划、改写用户目标或暴露 provider/native/sidecar/transport 等隐藏适配器语言。
- 合同反馈投影统一使用 `next_action_requirements`：允许动作、工具是否可用、是否只能提交一个动作、可写的用户可见字段。旧 `required_action_protocol` 只允许作为历史恢复包的内部读取 fallback，不能作为新 prompt 投影字段。

验收：

- 普通“只回复 OK / 无工具需求”turn 的 `tool_count` 应接近 0。
- agent 仍可通过 JSON `tool_call` action 请求任何当前工具目录允许的工具；单个工具用 `tool_call`，同一语义动作内的一组工具用 `tool_calls[]`。
- 不存在系统按用户语义强行收窄或放大 agent 工具调度空间的逻辑。
- `public_progress_note` 描述这批工具共同要查证的公开事实，不逐工具列名；观察返回后由 agent 按是否形成新的公开结论、风险、阻塞、验收状态或下一步来反馈。
- 所有恢复/修复/拒绝反馈都只提供 agent 可执行的行动语义，不用开发侧分类词替代角色、任务、输入、输出和下一步。

### Phase S4：Runtime Control 历史化

目标：

- 当前 runtime boundary 可见但短。
- 历史 replay 中的 runtime control 只保留小型事实或过期说明。

改动点：

- `backend/harness/runtime/compiler.py`
- dynamic context projector。
- provider-visible replay-only runtime tail metadata。

验收：

- `dynamic_projection` 不再每轮以 1K+ 体积封存。
- 旧 replay 中 runtime control 不会被 agent 当成本轮授权。

### Phase S5：Memory Maintenance 隔离

目标：

- memory maintenance 不抢占 normal turn cache warm path。
- 大型 maintenance delta 不进入交互链缓存统计。

改动点：

- memory maintenance scheduler。
- cache scope。
- prompt accounting metric scope。

验收：

- normal turn 缓存诊断不被 maintenance records 混淆。
- maintenance 使用独立 cache scope 或延后调度。

## 9.1 运行期收口/恢复提示的物理归属

2026-06-27 追加修复：`closeout`、`recovery`、`followup action contract`、`admission repair` 都不是旧上下文，也不是可封存记忆。它们的语义是：

```text
Current Runtime Boundary
本轮执行反馈和下一步行动边界。
它只帮助 agent 基于当前事实重新选择动作、收口、询问或说明阻塞。
它不代表用户新请求，不进入 sealed timeline，不成为 fork anchor。
```

工程规则：

- 这些消息出生时必须带内部 segment tag，例如 `runtime_control_signal_tail` 或 `single_agent_turn_followup_action_contract`。
- 内部 tag 只给分段器和 ledger gate 使用，不能进入 provider message payload。
- 分段器优先读内部 tag；中文提示词内容只能作为读取旧请求或异常路径的兜底识别。
- policy 固定为 `dynamic_tail + never_commit + current_dynamic_tail_only`。
- provider-visible ledger 只封存 user/current append/tool transcript 等 provider 成功确认的新上下文，不封存 closeout/recovery/action-contract 尾巴。

为什么这样设计：

- closeout/recovery 是“当前轮如何继续/如何停止”的行动反馈，不是历史事实本体。
- 如果它被封存，下一轮会把旧的当前边界误读为新边界，fork 也会继承错误授权。
- 如果它插在 sealed context 中，DeepSeek 的 prefix cache 会在旧 tail 与新 turn append 之间断开，导致本该稳定命中的上下文前缀变成部分命中。
- 内部 tag 通道可以让工程分段稳定，而不会把 `source_ref`、`context_cache_section` 等内部字段发给大模型。

## 9.2 自然回应与结构化动作的传输边界

2026-06-27 追加修复：`supports_json_action_protocol` 只表示 agent 可以使用结构化动作，不表示本轮必须使用 JSON action。此前链路把“可用动作集合里包含 respond/tool_call/ask_user”误判为“必须输出结构化动作”，导致普通自然回答被当成协议错误，再触发 `runtime-control-recovery` 或 `agent-closeout`。这是系统在传输层过度控制 agent 表达，不是 agent 本身的问题。

目标语义：

```text
自然回应：agent 直接写给用户看的回答；没有结构化动作时，它就是本轮普通回应。
结构化动作：agent 明确请求工具、任务生命周期、运行控制、等待用户或阻塞状态时使用。
```

工程规则：

- `supports_json_action_protocol=true`：agent 可选择结构化动作。
- `requires_json_action_protocol=true`：只能来自显式运行边界，不能由工具可见性或 allowed action 自动推出。
- 普通 single turn 默认 `natural_response_or_structured_action`：自然正文进入 final answer 候选；显式 JSON/native action 进入 action permit。
- 工具 follow-up 的行动合同只说明“继续工具或改变运行状态时使用结构化动作”；已经足够回答时，agent 可以直接自然收口。
- closeout 的职责是让 agent 根据当前停止事实给用户收口判断；它可以是自然正文，只有需要等待用户或阻塞状态时才需要结构化动作。
- parser 只识别传输形状：明确 JSON action / provider-native tool call / 普通文本。它不能根据自然语言内容替 agent 判断“其实想调用工具”或“其实想 respond”。
- 流式响应结束时，如果 provider chunk 聚合对象存在但 `content` 为空，而 `raw_content` 已经接到可见文本，必须把 `raw_content` 作为最终响应内容交给 commit gate；不能误触发 `single_agent_turn_empty_response` closeout。

本次实测：

```text
session-67d85fabe4c34b03
4 轮普通 no-tool turn 均直接返回 OK。
provider calls: agent_runtime=4, closeout=0, repair=0
第 3/4 轮 normal turn provider cache hit rate: 95.15%
ledger: closeout/recovery/action-contract 未封存。
```

剩余优化不再是拼接断层，而是动态尾体积：

- `dynamic_projection` 约 762 tokens。
- `lifecycle_runtime_guidance` 约 360 tokens。
- `current_turn_user_context` 约 72 tokens。
- 后台 `memory_maintenance_current_delta` 可单独拉低总体统计，但不应混入 normal turn 命中率判断。

## 10. 最终验收

静态验收：

```powershell
rg -n "dynamic_tail|context_append|fixed_context_package" backend/runtime backend/harness
rg -n "tool_schema_catalog|tool_index_stable|native_tool_binding_schema" backend
```

真实运行验收：

```powershell
python -m backend.cli.main --api-base http://127.0.0.1:8003/api send "缓存验证：请只回复 OK，不要调用工具。"
python backend/scripts/diagnose_deepseek_prompt_cache.py --session-id <session> --provider deepseek --full-ledger --json
```

必须证明：

- 旧上下文 message hash 是下一轮前缀。
- `provider_visible_context_prefix` 全部进入可命中范围。
- `tool_count` 对无工具 turn 显著下降。
- current tail 只包含本轮新增。
- DeepSeek post-warm hit rate 接近或超过 95%。
