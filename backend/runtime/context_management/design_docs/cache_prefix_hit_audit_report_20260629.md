# Cache Prefix Hit Audit Report - 2026-06-29

## 结论

本次审查结论：当前前缀缓存链路确实存在结构性问题。问题不是简单的“命中率 77.19% 还可以”，而是 provider 对我们声明的物理前缀没有完整读取，三次最新请求全部是 `provider_under_read`。

正确验收标准应是：

- `cache_status == hit`
- `provider_under_read_tokens == 0`
- `provider_cache_read_required_coverage_status == physical_spine_estimated_covered`
- 本地 physical spine 和 provider 实际缓存读取一致

当前最新用户 turn 的三次 provider 请求均未达标：

| request | prompt_tokens | cached_tokens | hit_rate | cache_status | provider_under_read_tokens | coverage | local break |
| --- | ---: | ---: | ---: | --- | ---: | --- | --- |
| initial | 119138 | 36608 | 30.73% | provider_under_read | 74019 | physical_spine_estimated_partial | no_local_physical_break |
| tool-followup-1 | 47280 | 36608 | 77.43% | provider_under_read | 2956 | physical_spine_estimated_partial | no_local_physical_break |
| tool-followup-2 | 51738 | 39936 | 77.19% | provider_under_read | 436 | physical_spine_estimated_partial | no_local_physical_break |

关键矛盾是：本地报告 `no_local_physical_break`，但 provider 实际少读缓存。这说明我们本地的 physical spine 判定过宽，或者前缀字节/顺序/边界与 provider 看到的真实请求不一致。

## 成熟 Agent 的前缀缓存规则

### Codex

本地参考：`D:\AI应用\openai-codex\codex-rs`

Codex 的核心要求是：缓存 key 稳定，且前一次请求的完整 prefix 必须作为下一次请求的 prefix 原样复用。

证据：

- `codex-rs/core/src/client.rs` 中 `prompt_cache_key()` 默认使用 thread id，并允许 review session 设置稳定 override。
- `codex-rs/core/tests/suite/prompt_caching.rs` 明确断言：`prompt_cache_key should not change across overrides`。
- 同一测试还断言：`The entire prefix from the first request should be identical and reused as the prefix of the second request`。
- `codex-rs/core/src/context_manager/history_tests.rs` 验证裁剪 user turns 时保留 session prefix，环境、AGENTS、skills、subagent 通知等 prefix 项不能被误删。
- `codex-rs/core/src/state/auto_compact_window.rs` 使用 server-observed input tokens 作为 prefill baseline，说明成熟系统不会只信本地估算。

Codex 标准可以概括为：

```text
stable prompt_cache_key
+ byte-identical previous request prefix
+ append-only new tail
+ server-observed usage correction
```

### Claude Code

本地参考：

- `D:\AI应用\Claude-Code-Source-Study-main\docs\07-Prompt-Cache.md`
- `D:\AI应用\Claude-Code-Source-Study-main\docs\04-System-Prompt-工程.md`
- `D:\AI应用\claude-code-nb-main\utils\forkedAgent.ts`
- `D:\AI应用\claude-code-nb-main\cli\print.ts`

Claude Code 的核心要求是：prefix 必须字节级一致。多一个空格、JSON 字段顺序变化、cache scope 变化，都可能使缓存失效。

成熟做法：

- 用 `SYSTEM_PROMPT_DYNAMIC_BOUNDARY` 把 system prompt 分成静态段和动态段。
- boundary 前的核心静态内容可用 global cache。
- boundary 后的用户/session 动态内容不进入 global cache。
- 消息历史只放一个消息级 cache breakpoint。
- fork/side question 使用 `CacheSafeParams`，必须保持 system prompt、tools、model、messages prefix、thinking config 一致。
- 不随意修改 `maxOutputTokens`，因为它可能改变 thinking budget，从而使 cache key 变化。

Claude Code 标准可以概括为：

```text
static prefix before dynamic boundary
+ one cache breakpoint
+ dynamic content after boundary
+ fork uses identical cache-safe params
```

### Hermes

本地参考：`D:\AI应用\hermes\hermes-agent-main`

Hermes 的规则非常直接：

- `AGENTS.md` 写明：Prompt Caching Must Not Break。
- 禁止 mid-conversation 改 past context、toolsets、memory、system prompt。
- slash commands 如果会改变 system prompt state，默认 deferred invalidation，下个 session 生效；立即生效必须显式 `--now`。
- `tools/memory_tool.py` 使用 frozen snapshot：磁盘 memory 可实时写入，但 system prompt 中的 memory 快照在 session 内冻结。
- `/reload-mcp` 明确提示会 invalid provider prompt cache。
- skills reload 不写 system prompt，而是排到下一次 user message，以保持缓存。
- `agent/prompt_caching.py` 使用固定 `system_and_3` 策略：system prompt + 最近 3 条非 system 消息，最多 4 个 cache_control breakpoints。

Hermes 标准可以概括为：

```text
system prompt snapshot frozen for session
+ memory/tool/skill changes deferred or appended
+ cache invalidation must be explicit
+ dynamic updates do not rewrite prefix
```

## 我们当前的具体 Prefix

审计对象：

- session: `session-2f8b0999b3174934`
- user-visible latest turn: `turn:session-2f8b0999b3174934:5`
- run: `turnrun:strun:9cf9747f62ca4192ba41d3d3d698bc4c`
- terminal physical frame: `physframe:55c2086897eb1c85`
- relevant provider requests:
  - `modelreq:rtpacket:turn:session-2f8b0999b3174934:5:single_agent_turn:1:1`
  - `modelreq:rtpacket:turn:session-2f8b0999b3174934:5:single_agent_turn:1:tool-followup:1`
  - `modelreq:rtpacket:turn:session-2f8b0999b3174934:5:single_agent_turn:1:tool-followup:2`

### Terminal Physical Frame Spine

下面是用户最新 turn 的 terminal physical frame `physframe:55c2086897eb1c85` 中进入 physical spine 的具体段。注意 ordinal 15 以后已经混入当前请求、当前工具回合和历史 replay。

| ordinal | segment_id | kind | role | lane | cache_role | boundary | bytes | source |
| ---: | --- | --- | --- | --- | --- | --- | ---: | --- |
| 1 | ppseg:1:tools:c25b42776ead5cba | native_tool_binding_schema | tool_schema | provider_tool_schema_prefix | session_stable | included | 34862 | model_request.tools |
| 4 | ppseg:4:messages:cda2864ef2d0f720 | global_static | system | global_static_prefix | cacheable_prefix | included | 19225 | runtime.pack.single_agent_turn |
| 5 | ppseg:5:messages:9a26fe2799e7d303 | tool_index_stable | system | global_static_prefix | session_stable | included | 88616 | agent_visible_tool_contract |
| 6 | ppseg:6:messages:95c8e54a7be9c235 | task_environment_context | system | global_static_prefix | session_stable | included | 999 | env.coding.vibe_workspace |
| 7 | ppseg:7:messages:687fc200974b3c29 | capability_catalog | system | global_static_prefix | session_stable | included | 5406 | capability_catalog |
| 8 | ppseg:8:messages:9edd17dab80637ce | project_instructions_stable | system | global_static_prefix | session_stable | included | 8615 | project.instructions.scoped |
| 9 | ppseg:9:messages:8da2bc635196b39b | file_evidence_policy_stable | system | global_static_prefix | session_stable | included | 1297 | file_evidence_policy_stable |
| 10 | ppseg:10:messages:b8b3e39363d9cb90 | personality_stable | system | global_static_prefix | session_stable | included | 1492 | personality.default.mythical_age |
| 11 | ppseg:11:messages:0a09fe400d841db5 | environment_stable | system | global_static_prefix | session_stable | included | 10204 | runtime/environment/coding rules |
| 12 | ppseg:12:messages:bf8c0b602b78cb30 | environment_guidance_stable | system | global_static_prefix | session_stable | included | 6492 | environment guidance |
| 13 | ppseg:13:messages:3a5e739af4d16950 | agent_stable | system | global_static_prefix | session_stable | included | 2377 | agent.main_interactive_agent |
| 14 | ppseg:14:messages:d4b28d4a77ed6a54 | runtime_baseline_refs | system | global_static_prefix | session_stable | included | 435 | runtime_baseline_refs |
| 15 | ppseg:15:messages:b8dfc2dd1425f9ca | current_turn_user_context | user | provider_visible_context_prefix | session_stable | included | 318 | single_agent_turn_current_request |
| 16 | ppseg:16:messages:be14ddc542d054a6 | single_agent_turn_tool_call | assistant | provider_visible_context_prefix | session_stable | included | 1565 | search_files/list_dir/web_search tool call |
| 17 | ppseg:17:messages:3bbeffe2bef7798d | tool_transcript_delta | tool | provider_visible_context_prefix | session_stable | included | 269 | search_files result |
| 18 | ppseg:18:messages:304169e414575813 | tool_transcript_delta | tool | provider_visible_context_prefix | session_stable | included | 119 | list_dir result |
| 19 | ppseg:19:messages:ccfc8ff0057baa57 | tool_transcript_delta | tool | provider_visible_context_prefix | session_stable | included | 180 | web_search result |
| 20 | ppseg:20:messages:ee1cbf6bcfe3c211 | physical_prefix_frame_context_replay | system | provider_visible_context_prefix | session_stable | included | 444 | runtime_memory_context |
| 21 | ppseg:21:messages:5f479516ff3ed975 | physical_prefix_frame_user_message_replay | user | provider_visible_context_prefix | session_stable | included | 298 | single_agent_turn_current_request |
| 22 | ppseg:22:messages:c13f0cb3ffce3b2e | physical_prefix_frame_user_context_replay | user | provider_visible_context_prefix | session_stable | included | 336 | single_agent_turn_current_request |
| 23 | ppseg:23:messages:02be8d6a3b2b63ac | physical_prefix_frame_context_replay | system | provider_visible_context_prefix | session_stable | included | 7603 | evidence_index_cursor |
| 24 | ppseg:24:messages:f19faa94b7d64b07 | physical_prefix_frame_context_replay | system | provider_visible_context_prefix | session_stable | included | 761 | read_evidence_context:d282749944f859f2 |
| 25 | ppseg:25:messages:01bef3117ca6aa7e | physical_prefix_frame_context_replay | system | provider_visible_context_prefix | session_stable | included | 757 | read_evidence_context:17eb8bc9c5f64a71 |
| 26 | ppseg:26:messages:6e1ee379889c3f1b | physical_prefix_frame_context_replay | system | provider_visible_context_prefix | session_stable | included | 754 | read_evidence_context:e8aaf8feed6ef476 |
| 27 | ppseg:27:messages:0d3030f375b78f5d | physical_prefix_frame_context_replay | system | provider_visible_context_prefix | session_stable | included | 756 | read_evidence_context:704f12dfebe16c8d |
| 28 | ppseg:28:messages:c9924d99866c017a | physical_prefix_frame_context_replay | system | provider_visible_context_prefix | session_stable | included | 760 | read_evidence_context:1fd32cc6b34327ba |
| 29 | ppseg:29:messages:d2a288e0a65871a1 | physical_prefix_frame_context_replay | system | provider_visible_context_prefix | session_stable | included | 767 | read_evidence_context:7deab0dd6f831915 |
| 30 | ppseg:30:messages:989272024d37745b | physical_prefix_frame_context_replay | system | provider_visible_context_prefix | session_stable | included | 763 | read_evidence_context:f2ca6d71ad9de27e |
| 31 | ppseg:31:messages:21efd305d3664ef5 | physical_prefix_frame_context_replay | system | provider_visible_context_prefix | session_stable | included | 765 | read_evidence_context:b6d4f33f9a5c586e |
| 32 | ppseg:32:messages:43c0718d8d57cb6c | physical_prefix_frame_context_replay | system | provider_visible_context_prefix | session_stable | included | 757 | read_evidence_context:95fde574cb74fbf9 |
| 33 | ppseg:33:messages:ddf2afd8b92685e0 | physical_prefix_frame_context_replay | system | provider_visible_context_prefix | session_stable | included | 765 | read_evidence_context:11ccdd53fd784c9f |
| 34 | ppseg:34:messages:12ec5ef074bae377 | physical_prefix_frame_context_replay | system | provider_visible_context_prefix | session_stable | included | 764 | read_evidence_context:9b6deaa2e5378676 |
| 35 | ppseg:35:messages:b953a28e62d49ded | physical_prefix_frame_context_replay | system | provider_visible_context_prefix | session_stable | included | 771 | read_evidence_context:c6134980f45ca08a |

同一 frame 中还有两个 current tool round 段被排除在 spine 外：

| ordinal | segment_id | kind | role | boundary | bytes | source |
| ---: | --- | --- | --- | --- | ---: | --- |
| 36 | ppseg:36:messages:fa28afaa5d4fa063 | single_agent_turn_tool_call | assistant | excluded | 6118 | read_file tool call |
| 37 | ppseg:37:messages:4d7d0d5de0137ba3 | tool_transcript_delta | tool | excluded | 11809 | read_file result |

这说明系统已经有“当前 tail 不进 spine”的意识，但前一轮 current append 被 promote 后进入下一次 spine 的顺序和身份不稳定。

### Prefix Changed Sections

`tool-followup-2` 的 `prompt_stability` 明确显示 physical spine changed，且 changed section count 为 20。最关键的是从 ordinal 14 开始，当前段和上一帧同位置段发生错位：

| ordinal | change | current kind | current source | previous kind | previous source |
| ---: | --- | --- | --- | --- | --- |
| 14 | changed | single_agent_turn_tool_call | search_files/list_dir/web_search | physical_prefix_frame_context_replay | runtime_memory_context |
| 15 | changed | tool_transcript_delta | search_files result | physical_prefix_frame_user_message_replay | single_agent_turn_current_request |
| 16 | changed | tool_transcript_delta | list_dir result | physical_prefix_frame_user_context_replay | single_agent_turn_current_request |
| 17 | changed | tool_transcript_delta | web_search result | physical_prefix_frame_context_replay | evidence_index_cursor |
| 18 | changed | physical_prefix_frame_context_replay | runtime_memory_context | physical_prefix_frame_context_replay | read_evidence_context:d282749944f859f2 |
| 19 | changed | physical_prefix_frame_user_message_replay | single_agent_turn_current_request | physical_prefix_frame_context_replay | read_evidence_context:17eb8bc9c5f64a71 |
| 20 | changed | physical_prefix_frame_user_context_replay | single_agent_turn_current_request | physical_prefix_frame_context_replay | read_evidence_context:e8aaf8feed6ef476 |
| 21 | changed | physical_prefix_frame_context_replay | evidence_index_cursor | physical_prefix_frame_context_replay | read_evidence_context:704f12dfebe16c8d |
| 22 | changed | physical_prefix_frame_context_replay | read_evidence_context:d282749944f859f2 | physical_prefix_frame_context_replay | read_evidence_context:1fd32cc6b34327ba |
| 23 | changed | physical_prefix_frame_context_replay | read_evidence_context:17eb8bc9c5f64a71 | physical_prefix_frame_context_replay | read_evidence_context:7deab0dd6f831915 |
| 24 | changed | physical_prefix_frame_context_replay | read_evidence_context:e8aaf8feed6ef476 | physical_prefix_frame_context_replay | read_evidence_context:f2ca6d71ad9de27e |
| 25 | changed | physical_prefix_frame_context_replay | read_evidence_context:704f12dfebe16c8d | physical_prefix_frame_context_replay | read_evidence_context:b6d4f33f9a5c586e |
| 26 | changed | physical_prefix_frame_context_replay | read_evidence_context:1fd32cc6b34327ba | physical_prefix_frame_context_replay | read_evidence_context:95fde574cb74fbf9 |
| 27 | changed | physical_prefix_frame_context_replay | read_evidence_context:7deab0dd6f831915 | physical_prefix_frame_context_replay | read_evidence_context:11ccdd53fd784c9f |
| 28 | changed | physical_prefix_frame_context_replay | read_evidence_context:f2ca6d71ad9de27e | physical_prefix_frame_context_replay | read_evidence_context:9b6deaa2e5378676 |
| 29 | changed | physical_prefix_frame_context_replay | read_evidence_context:b6d4f33f9a5c586e | physical_prefix_frame_context_replay | read_evidence_context:c6134980f45ca08a |
| 30 | added | physical_prefix_frame_context_replay | read_evidence_context:95fde574cb74fbf9 | none | none |
| 31 | added | physical_prefix_frame_context_replay | read_evidence_context:11ccdd53fd784c9f | none | none |
| 32 | added | physical_prefix_frame_context_replay | read_evidence_context:9b6deaa2e5378676 | none | none |
| 33 | added | physical_prefix_frame_context_replay | read_evidence_context:c6134980f45ca08a | none | none |

这不是“追加几个新段”的理想形态，而是同一 ordinal 上发生了段身份替换。成熟 agent 的 prefix 要求是前缀字节序列相同后再追加 tail，这里已经破坏了“相同前缀”。

## 代码链路分析

### 1. 初始 spec 对 current user context 的定义是正确的

文件：`backend/harness/runtime/compiler.py`

`current_turn_user_context` 在初始 spec 中被标记为：

```text
cache_scope = none
cache_role = volatile
context_cache_section = context_append
context_replay_policy = current_append_commit_on_provider_success_then_next_physical_prefix_frame
stability_rule = current request must not count as already cached prefix
```

这说明最初设计知道“当前请求不是已缓存前缀”。

### 2. provider-visible ledger 允许 current append 在 provider success 后封存

文件：`backend/runtime/context_management/provider_visible_context_ledger.py`

`assemble_provider_visible_context_specs()` 会把 context append candidate 记录成 provider-visible append candidate。它的设计目标是去重并等待 provider success 后确认。

这个机制本身可以成立，但必须满足两个条件：

- 当前请求内不能把 current append 算作已缓存 prefix。
- 下一次请求只能在已确认 prefix 后 append，不能替换历史 frame 中的任意 ordinal。

### 3. physical context assembler 采用 splice rule

文件：`backend/runtime/context_management/physical_context_assembler.py`

当前 splice rule 是：

```text
static_prefix -> confirmed old frame -> current append -> dynamic tail
```

这个方向是成熟的。但账本显示 current append 与 replay 发生了 ordinal 抢位，导致 provider 看到的 prefix 不再是 byte-identical old frame。

### 4. provider payload 的 physical spine 判定过宽

文件：`backend/runtime/model_gateway/provider_payload.py`

`_physical_cache_spine_segments()` 逻辑是按 ordinal 扫描：

```text
non_token_family_selector: skip
blocker: stop
included: append to spine
tools/messages but not included: stop
else: stop
```

同时 `_is_physical_cache_spine_message_segment()` 只要求：

```text
transport_location == messages
boundary_participation == included
physical_prefix_lane in {global_static_prefix, provider_visible_context_prefix}
```

这导致只要 current append 或工具 transcript 被标成 `provider_visible_context_prefix + included`，它就会进入 physical spine。这个判定没有再次核验“它是否已经是上一次 provider 成功确认过的 immutable byte prefix”。

### 5. cache planner 只做总量覆盖估算

文件：`backend/runtime/prompt_accounting/cache_planner.py`

当存在 physical cache spine 时，coverage 使用 total-only estimate：

```text
physical_spine_estimated_covered = cached_tokens >= physical_spine_estimated_tokens
status = physical_spine_estimated_covered ? covered : partial
```

这能发现 under-read，但不能定位字节级断点。当前输出已经显示 `physical_spine_estimated_partial`，但上层仍容易被 `77.19%` 的总命中率误导。

### 6. provider cache ledger 已经记录 under-read，但需要提升为失败标准

文件：`backend/runtime/prompt_accounting/provider_cache_ledger.py`

`_ledger_cache_status()` 已经会把 `provider_under_read_tokens > 0` 标为 `provider_under_read`。这说明账本层有正确信号，只是产品/诊断口径必须把它提升为 P1，而不是当作可接受 hit ratio。

## 根因判断

### P1: Prefix Authority 不统一

当前系统里至少有三层都在影响“什么算前缀”：

- compiler/context policy 决定 spec 的 cache role 和 section。
- provider-visible ledger 决定 current append 是否可封存。
- physical prefix frame ledger/provider payload 决定哪些段进入 provider physical spine。

这些层的目标没有完全统一，导致一个段可以先是 `volatile/current append`，之后被 seal 成 `session_stable`，再被 provider payload 当作 physical spine。这个转换本身不是错误，但必须由同一个前缀权威保证 append-only 和 ordinal 稳定。当前证据显示没有保证住。

### P1: Current append 和 replay 段发生顺序错位

`tool-followup-2` 的 changed sections 表显示：ordinal 14 原本是 `runtime_memory_context` replay，当前变成了工具调用；后续 evidence replay 全体后移/替换。这是 provider prefix cache 的硬伤。

成熟标准要求：

```text
previous_prefix_bytes == current_request_prefix_bytes[0:len(previous_prefix_bytes)]
```

当前更像：

```text
static_prefix + newly promoted current append + old replay remainder
```

而不是：

```text
static_prefix + exact confirmed old frame + new append tail
```

### P1: 命中统计口径容易误导

`77.19%` 是总 prompt token 中 cached token 的比例，不代表“必须命中的 prefix 命中了”。在 prefix caching 中，第一优先级是前缀覆盖：

```text
expected physical spine provider-scaled tokens = 40372
provider cached_tokens = 39936
under_read = 436
status = provider_under_read
```

所以 `77.19%` 不是通过，只是“有部分缓存被读到”。只要 under_read 不为 0，就代表前缀没完全命中。

### P2: 工具 schema 和 tool index 过大，但不是本次直接 blocker

本次 tool schema blocker tokens 是 0，说明工具 schema 没被本地识别为断点。但当前 prefix 中：

- native tool schema: 34862 bytes
- tool index stable: 88616 bytes

这两个段很大，必须严格稳定。成熟 agent 通常把工具集变化视为显式 cache invalidation。Hermes 的 `/reload-mcp` 就会提示 invalid provider prompt cache。

## 修复建议

### 1. 建立单一 Cache Prefix Authority

建议新增或明确一个单一权威，职责是：

```text
confirmed_provider_prefix = exact bytes/messages confirmed by provider success
current_append = provider-visible but not yet expected cache read
dynamic_tail = never cache, never replay
```

只有这个权威可以决定：

- 哪些段进入 physical spine。
- 哪些段只是 current append。
- provider success 后如何晋升。
- 晋升后的段在下一次请求中如何保持 byte-identical order。

### 2. 修改 physical spine 入选条件

不要只按 `boundary_participation=included` 和 lane 判断。建议 physical spine 必须满足：

```text
global_static_prefix:
  allowed if byte-stable and cache-sensitive params stable

provider_visible_context_prefix:
  allowed only if provider_visible_payload_authority == physical_prefix_frame.replay
  or segment belongs to exact confirmed physical frame

current_append:
  never counted as expected cache read in the same request
```

换句话说：current append 可以发送给 provider，但不能被 local planner 计入“本次必须命中的前缀”。

### 3. 保证 frame replay 后追加，不替换 ordinal

当前 changed sections 显示 current tool call 顶掉了 runtime memory context 的 ordinal。修复目标应是：

```text
static prefix
+ exact old physical frame replay, same order, same bytes, same roles
+ current append, new ordinals only
+ dynamic tail
```

不能出现：

```text
same ordinal: old replay segment -> current tool segment
```

### 4. 把 provider_under_read 升级为健康失败

UI/API/诊断报告中不要只显示 hit ratio。需要优先显示：

- prefix coverage: covered/partial/miss
- under_read_tokens
- first changed prefix ordinal
- changed kind/source
- whether local physical break matched provider result

验收口径：

```text
provider_under_read_tokens == 0 才算 prefix hit
```

### 5. 工具/能力表变更要显式 invalidation

工具 schema、tool index、MCP reload、能力 catalog 变化必须被显式标记为 cache invalidation，而不是静默进入同一个 session prefix。可参考 Hermes：

- 默认延迟到下一 session。
- 立即生效需要显式确认。
- 更新信息作为下一条 user message 或 tail，不重写 system prefix。

## 建议实施顺序

1. 先修 reporting：把 `provider_under_read` 在前端/日志中标成失败，不再用 77% 总命中率掩盖 prefix miss。
2. 再修 prefix authority：让 `provider_payload.py` 只把 confirmed physical frame replay 计入 provider-visible context spine。
3. 再修 current append promotion：保证 provider success 后晋升只追加到下一帧末尾，不改变旧 frame ordinal。
4. 最后清理旧链路：删除或收紧所有能把 volatile/current append 静默改成 session_stable included spine 的旧兼容路径。

## 需要继续验证的点

- `physframe:7165225a9f2516cd` 是后续 memory maintenance 请求生成的 frame，不属于用户可见最新 turn 的 terminal frame。它同样使用了不同 lineage，应单独审查 background memory maintenance 是否污染主 session prefix。
- memory maintenance 目前有 JSON parse failure：`Expecting value: line 1 column 1 (char 0)`。这不是本次 prefix under-read 的直接原因，但会影响后续记忆质量和上下文稳定性。
- 需要在真实启动后复测同一 session 的下一轮请求，确认修复后 `provider_under_read_tokens` 为 0。

## 最终判断

你的判断是对的：这不是单个缓存参数没调好，而是前缀权力链路没有统一。成熟 agent 的标准是“稳定前缀由一个权威维护，动态内容只能追加到 tail 或下一轮确认后按 byte-identical 顺序进入 prefix”。我们现在的链路中，compiler、provider-visible ledger、physical frame ledger、provider payload 和 cache accounting 都在各自解释 prefix，导致本地认为没断，provider 实际 under-read。

修复时不应该继续堆补丁，而应把 `confirmed prefix / current append / dynamic tail` 三条 lane 的权威边界重新收紧。
