# Agent 语义空间上下文设计规范

日期：2026-06-27

本文档用于约束后续上下文重构。它先定义 agent 实际收到并理解的语义空间，再约束物理拼接、缓存、工具准入和 fork 交接。目标不是机械压 token，而是把上下文组织成成熟 agent 能稳定工作的时间链。

## 1. 核心结论

当前已经修复的是物理拼接断层：

```text
global_static_prefix
-> provider_visible_context_prefix
-> current_turn_tail
```

最新实测证明旧 message hash 已经按前缀连续追加。但缓存命中仍不合格，根因不再是物理顺序，而是语义空间分配还不成熟：

- 工具契约同时以 `tool_schema_catalog`、`tool_index_stable`、provider native tools sidecar 三份形式出现。
- 旧上下文排在巨大工具/稳定前缀之后，DeepSeek 没有完整命中后半段旧上下文。
- runtime control 被作为历史字节封存后，虽然物理连续，但语义上需要明确“只读历史，不是当前授权”。
- provider 传输结构和 agent 可理解语义上下文混在一起，导致缓存和语义都变重。

因此后续重构必须先建立语义空间主链：

```text
Stable Operating Contract
-> Tool Admission Contract
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
Tool Admission Contract
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

Provider native tools、tool choice options、request params 属于 API transport。

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

### 3.2 Tool Admission Contract

Agent 可见标题：

```text
Tool Admission Contract
```

Agent 语义：

```text
你可以使用工具，但必须先判断工具是否被当前任务准入。
工具 schema 由系统在 provider transport 中绑定。
你在语义上下文中只需要理解工具用途、使用边界、关键参数概念和何时不要调用。
```

内容：

- 工具名称。
- 工具用途。
- read/write/network/side-effect 分类。
- admission 条件。
- 关键参数概念，不放完整 JSON schema。
- schema ref / catalog hash。
- 常见误用规则。

禁止内容：

- 完整 provider native tool schema。
- 每个字段的大型 schema detail。
- 和 provider sidecar 重复的 parameters JSON。
- 每轮动态筛选结果伪装成稳定工具全集。

物理位置：

```text
static_prefix -> global_static_prefix
```

Provider transport：

```text
model_request.tools
```

规则：

- message prefix 里的 tool contract 是 agent 语义索引。
- native tools sidecar 是 provider 调用结构。
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
它说明当前允许的行动、工具准入、运行状态和恢复要求。
如果这段内容以后作为历史 replay 出现，只能用于理解过去发生了什么，不能作为当前授权。
```

内容：

- current allowed action types。
- 当前 tool admission set。
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

- native tools sidecar。
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
- DeepSeek 自动缓存统计会把 sidecar 纳入 prompt/miss 预算，因此要做 admission 缩小。

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

### 5.1 当前问题

现状有三份工具表达：

```text
tool_schema_catalog message
tool_index_stable message
native tools sidecar
```

这导致：

- message prefix 过胖。
- provider sidecar 每轮增加 miss 预算。
- agent 读到的工具信息像开发数据包，不像工具准入契约。
- DeepSeek 命中旧上下文前已经被大量工具契约占据 prefix 空间。

### 5.2 目标结构

语义空间：

```text
Tool Admission Contract
```

只包含：

- tool name。
- purpose。
- read/write/side-effect。
- when to use。
- when not to use。
- key argument concepts。
- schema_ref。

Provider transport：

```text
native tools sidecar
```

只包含当前准入的可调用工具 schema。

### 5.3 Tool Admission Set

每轮不应默认发送全部工具 sidecar。应分两层：

稳定工具宇宙：

```text
tool universe / capability catalog
```

当前可调用集合：

```text
admitted native tools for this turn
```

Admission 依据：

- 用户请求类型。
- 当前任务阶段。
- runtime permission mode。
- 文件上下文是否存在。
- 是否已有 read evidence。
- 是否需要写入。
- 是否处于 recovery / follow-up tool loop。

例子：

普通问答无文件操作：

```text
admitted_tools = []
```

已知文件路径，需要读：

```text
admitted_tools = [read_file, path_exists, stat_path]
```

需要查找文件：

```text
admitted_tools = [search_files, glob_paths, list_dir]
```

需要代码修改：

```text
admitted_tools = [read_file, search_text, edit_file, batch_edit_file]
```

需要 shell 真实验证：

```text
admitted_tools = [exec_command]
```

如果当前模型需要未准入工具，应通过 action request 或下一轮 runtime boundary 扩大 admission，而不是每轮预先发送全部 schema。

## 6. 上下文分配表

| 语义层 | Agent 可见标题 | section | physical lane | 是否封存 | 缓存预期 |
|---|---|---|---|---:|---|
| 稳定运行契约 | `Operating Contract` | `static_prefix` | `global_static_prefix` | 否 | 应稳定命中 |
| 工具准入契约 | `Tool Admission Contract` | `static_prefix` | `global_static_prefix` | 否 | 应稳定命中，必须瘦 |
| provider native schema | 不进 message | sidecar | sidecar | 否 | DeepSeek 可能计入 miss，必须 admission |
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
- provider sidecar 的当前准入小集合。

不允许长期 miss：

- 旧 timeline。
- 稳定 operating contract。
- 稳定 tool admission contract。
- 大型 tool schema catalog。
- 完整 runtime projection。
- 完整重复 read result。

当前要达标，需要优先降低：

1. `tool_schema_catalog + tool_index_stable` message 体积。
2. native tools sidecar 工具数量。
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

### Phase S2：工具契约语义化瘦身

目标：

- `tool_schema_catalog` 不再包含完整 schema。
- `tool_index_stable` 不再重复 schema summary 大包。
- message prefix 中只保留 tool admission contract、schema refs、关键使用规则。

改动点：

- `backend/harness/runtime/provider_tool_schema.py`
- `backend/harness/runtime/tool_catalog_manifest.py`
- `backend/harness/runtime/compiler.py`

验收：

- `tool_schema_catalog + tool_index_stable` 从约 20K tokens 降到可控范围。
- schema hash 仍 matched。
- agent 能理解工具用途和准入边界。

### Phase S3：Native Tools Admission

目标：

- 不再每轮默认发送全部 native tools sidecar。
- 根据当前 turn 语义选择 admitted tool set。

改动点：

- `backend/harness/loop/single_agent_turn.py`
- runtime tool plan / tool admission policy。
- provider payload diagnostics。

验收：

- 普通“只回复 OK / 无工具需求”turn 的 `tool_count` 应接近 0。
- 文件任务只发送文件相关工具。
- 写入任务才发送写入工具。

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
