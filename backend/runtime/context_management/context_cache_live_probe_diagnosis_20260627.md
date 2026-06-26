# Context Cache Live Probe Diagnosis - 2026-06-27

## 测试入口

本次覆盖了两条真实入口：

1. HTTP chat API: `POST /api/chat/runs`
2. Backend CLI: `backend/cli/main.py send`

CLI 口不是独立 runtime。`backend/cli/client.py` 的 `AgentCliClient.stream_chat()` 仍然调用 `POST /chat/runs`，然后轮询 `/chat/runs/{stream_run_id}/events/replay`。因此 CLI 与前端/API 共用同一条上下文主链：

```text
CLI / API
-> /api/chat/runs
-> HarnessRuntimeFacade.prepare_chat_run_request_for_schedule
-> HarnessRuntimeFacade.astream
-> run_single_agent_turn
-> model_runtime
-> prompt_accounting / provider_visible_context_ledger
```

CLI 的额外差异是默认注入 `stream_policy.source = backend.cli.chat_stream_default`。实测中该字段稳定，不是本次低命中的主因。

## 实测结果

### API normal turn

Session: `session-47e0b043741941a9`

| turn | run | prompt_tokens | cached_tokens | hit_rate |
| --- | --- | ---: | ---: | ---: |
| 1 | `turnrun:strun:d96d6ccd79c84b3dbb300e8ae90004ae` | 38222 | 0 | 0.0000 |
| 2 | `turnrun:strun:680f6d0c28904baba32681fec21d067f` | 38417 | 25984 | 0.6764 |
| 3 | `turnrun:strun:cd6d009cdb82404d9b49456a09a0823e` | 38610 | 31744 | 0.8222 |

### CLI normal turn

Session: `session-6b4b106ea88b4398`

| turn | run | prompt_tokens | cached_tokens | hit_rate |
| --- | --- | ---: | ---: | ---: |
| 1 | `turnrun:strun:4519b50bd47741308482f13b06067bfc` | 38236 | 0 | 0.0000 |
| 2 | `turnrun:strun:97d92fc8c60b4c7ba18787798a7f2086` | 38440 | 25984 | 0.6760 |
| 3 | `turnrun:strun:00adb8d35b554d9e95aa4fb4c4780ede` | 38642 | 31744 | 0.8215 |
| 4 | `turnrun:strun:62c6e65dcff94af3bd614c43021802d3` | 38842 | 31744 | 0.8173 |
| 5 | `turnrun:strun:ed35115f02914b86a712946c8526cbc5` | 39041 | 31744 | 0.8131 |

结论：CLI 与 API 的曲线基本一致，低命中不是 CLI 口造成的。命中在第三轮后稳定卡在约 `31,744` cached tokens，而不是继续升到 95%。

### Fork child

Parent: `session-6b4b106ea88b4398`

Child: `session-7328a739c2bb4483`

Child 首轮语义继承成功，模型能确认父会话关键词 `CLI基准`。但物理缓存仍低：

| run | prompt_tokens | cached_tokens | hit_rate |
| --- | ---: | ---: | ---: |
| `turnrun:strun:2dc388cda6b843f9bcb9e6643671bfdf` | 39463 | 31616 | 0.8012 |

Fork record 保存了 parent provider-visible anchor、cache spine、transport hash、read evidence scope 和 child read evidence scope；但 child 的 provider-visible ledger 文件只物化了 child 当前 turn entries，没有把 parent entries 直接 materialize 成 child ledger spine。语义继承可用，物理缓存继承还不够稳。

## 对照探针

高 token 合成 no-tail 探针：

```text
stable-lines=1800, live-scenario=no_tail
prompt_tokens: 42202 -> 42957 -> 43712
cached_tokens: 14976 -> 42112 -> 42880
hit_rate: 0.3549 -> 0.9803 -> 0.9810
```

这证明 DeepSeek 本身可以在 42K+ prompt 下达到 98% 命中。真实 runtime 卡在 31,744 不是 provider 固定上限，而是本项目物理拼接/transport contract 存在断点。

## 根因判断

### 1. 稳定前缀过胖

CLI 第五轮 segment 分布：

| ordinal | kind | tokens | role |
| ---: | --- | ---: | --- |
| 2 | `global_static` | 6782 | stable |
| 3 | `tool_schema_catalog` | 5045 | stable |
| 4 | `tool_index_stable` | 15209 | stable |
| 5 | `turn_stable` | 6683 | stable |
| 6-11 | file/personality/env/lifecycle/agent/baseline | 4258 | stable |
| 12-17 | provider-visible replay/current user | ~1248 | append/sealed replay |
| 18-19 | dynamic tail | 1259 | volatile |

仅 `tool_schema_catalog + tool_index_stable` 就约 `20254` tokens。真实 prompt 在 38K-39K，想达到 95%，未命中预算必须小于约 2K；但现在 dynamic tail 约 1.25K，provider sidecar 约 3.97K，稳定消息本身又巨大，预算天然超标。

### 2. 工具 sidecar 与稳定 tool catalog 指纹不一致

`native_tool_binding_schema` 每轮被标记：

```text
sidecar_drift_status = drifted
native_tool_binding_reason = provider_tools_do_not_match_tool_catalog_manifest
```

工具名称完全一致，实际 mismatch 是 schema ref：

| tool | stable catalog ref | actual provider ref |
| --- | --- | --- |
| `git_branch_list` | `sha256:2f7b99fe18` | `sha256:fcb141e753` |
| `git_diff` | `sha256:2cf5615fdf` | `sha256:4b1918470d` |
| `git_log` | `sha256:22f9f20e24` | `sha256:2355f69343` |
| `git_show` | `sha256:9b6cc51232` | `sha256:a69b5ea9c7` |
| `git_status` | `sha256:eac0a9d621` | `sha256:ea327cf3dd` |
| `list_dir` | `sha256:3915c90188` | `sha256:f7bd0297ac` |

这说明稳定 tool index 的 `input_schema_ref` 与真正发送给 provider 的 tool schema 不是同一套 canonicalization。系统虽然把工具 sidecar 放进 transport contract，但又判定它未验证/漂移，缓存边界在工具契约处不成熟。

### 3. Planner 能解释 miss，但目标不合格

典型第五轮诊断：

```text
provider_hit = 0.8131
target_warm_cache_read_rate_status = provider_below_target
target_warm_cache_read_rate_expected_miss_tokens = 5438
expected miss families:
  current_context_append ~= 205
  dynamic_or_never_replay_tail = 1259
  provider_transport_sidecar = 3974
uncategorized_miss_tokens = 0
first_uncovered_stable_segment = lifecycle_stable#9
```

`uncategorized=0` 表示账本分类没有乱；真正问题是目标结构本身把过多内容放进不可稳定命中的物理区，且工具 sidecar 没有被验证为 matched。

### 4. Memory maintenance 插入了额外低命中模型调用

CLI 第四轮后自动触发：

```text
memory-maintenance:session-6b4b106ea88b4398:8
prompt_tokens = 38018
cached_tokens = 25856
hit_rate = 0.6801
```

Fork child 后也触发：

```text
memory-maintenance:session-7328a739c2bb4483:12
prompt_tokens = 39448
cached_tokens = 0
hit_rate = 0
```

维护调用不一定污染主会话语义，但它消耗缓存/成本，并且使用不同 transport contract。它应当隔离 cache scope 或延后，不应夹在 normal turn 验证链里。

## 修复判断

当前缓存不合格，不能解释为“正常新增内容导致”。成熟 agent 的常态 turn 应满足：

```text
稳定系统/工具/历史前缀字节不变
本轮新增只追加在尾部
动态 tail 明确不可缓存且很小
工具 schema 以单一 canonical source 生成
fork child 继承 parent sealed context anchor，并有可验证物理 cache scope
```

本项目当前缺口：

1. `tool_catalog_manifest.input_schema_ref` 和 `provider_tool_bindings_for_available_tools()` 的 schema canonicalization 不统一。
2. prompt 同时放入巨大 `tool_schema_catalog`、巨大 `tool_index_stable` 和 native tools sidecar，形成三份工具契约表达。
3. dynamic tail 不是主因，但 1.25K 对 95% 目标已经偏大。
4. fork 语义继承成功，但 child provider-visible ledger 没有直接物化 parent sealed entries，物理 cache inheritance 不完整。
5. memory maintenance 使用同一 session 语境即时插入低命中调用，应隔离或调度到非交互 cache scope。

## 建议主链升级

优先级 1：工具契约单源化

- 抽出唯一 `canonical_provider_tool_schema_ref(tool)`。
- `build_tool_catalog_manifest()` 和 `provider_tool_bindings_for_available_tools()` 必须使用同一 canonical schema。
- `native_tool_binding_schema.sidecar_drift_status` 必须在 normal turn 中变成 `matched`。
- 如果 provider tools 与 stable catalog 不匹配，应 fail diagnostic，不应静默继续以 `drifted` 运行。

优先级 2：瘦身工具稳定前缀

- native tools sidecar 是 provider 工具调用的权威 schema。
- prompt 里的 `tool_schema_catalog` 只保留工具语义、分组、admission contract、schema refs 和 catalog hash。
- 删除重复的大 JSON schema 文本，不再让 `tool_index_stable` 承担 15K+ token。
- 目标是把 normal turn prompt 从 38K 降到 22K-28K 区间，或至少让可缓存稳定前缀在 provider 实际可读范围内完整覆盖。

优先级 3：动态尾预算收紧

- `dynamic_projection` 约 1104 tokens，`lifecycle_runtime_guidance` 约 155 tokens。
- 正常 follow-up 的动态尾目标应低于 500-800 tokens。
- durable facts 必须封存进 sealed replay，不留在 current tail。

优先级 4：fork 物理继承

- fork child 创建时应 materialize parent sealed provider-visible ledger entries，或建立 child -> parent anchor projection，使 compiler 明确复用 parent cache scope。
- child 首轮不应只靠 transcript 语义继承；应能证明 provider payload prefix 与 parent fork point anchor 对齐。

优先级 5：维护调用隔离

- memory maintenance 不应抢占 normal turn 的 cache warm path。
- 给 maintenance 使用独立 `cache_scope=model_maintenance:{session}` 或后台低优先级策略，避免污染交互链诊断和成本。

## 2026-06-27 修复实施记录：工具 schema canonical 单源化

本次已完成优先级 1 的第一刀修复：稳定 tool catalog、provider native tool binding、provider payload drift 诊断改为共用同一套 provider-visible input schema/ref 口径。

### 改动文件

| 文件 | 改动 |
| --- | --- |
| `backend/runtime/shared/tool_schema_canonical.py` | 新增唯一 provider tool input schema canonical/ref 权威。负责 `input_schema`/`parameters`、contract fallback、空 required、schema object 稳定化和短 ref 计算。 |
| `backend/harness/runtime/tool_catalog_manifest.py` | `input_schema_summary` 与 `input_schema_ref` 改为基于 provider-visible canonical schema，不再 hash 原始 `input_schema`。删除旧 `_short_hash()` 残留。 |
| `backend/harness/runtime/provider_tool_schema.py` | provider native binding 改为直接使用共享 canonical schema，不再本地构造 `_provider_input_schema()` fallback。 |
| `backend/runtime/model_gateway/lightweight_chat_model.py` | provider transport `function.parameters` 改为使用共享 canonical schema，删除本地 `_tool_parameters_schema()` 及其重复 helper。 |

## 2026-06-27 修复实施记录：插线式物理上下文模型

本次按“同一物理段同一处理方式”的要求修正了 provider-visible replay 的物理模型。

旧模型把 `context_memory_prefix` 再拆成：

```text
active_context_prefix
byte_replay_archive_prefix
```

这会让 active、historical-only、tool transcript、runtime replay-only 等语义差异影响物理位置。即使排序函数尝试按 ledger index 修正，它仍然是双 lane 补救，不是成熟 agent 需要的 append-only prefix ledger。

当前模型改为：

```text
global_static_prefix
provider_visible_context_prefix
current_turn_tail
never_replay_tail
```

规则：

- `context_memory_prefix` 的 confirmed ledger replay 全部进入 `provider_visible_context_prefix`。
- replay 顺序只由 `provider_visible_context_ledger_entry_index` 决定。
- active、historical-only、fork inherited、tool transcript、runtime replay-only 只写入 `semantic_visibility`、`semantic_commit_class`、`validity_scope` 等 metadata。
- `context_append` 仍然在本轮 `current_turn_tail`，provider success 后下一轮才进入 `provider_visible_context_prefix`。
- 旧 ledger 文件不改字节；旧 entry 的 `ledger_lane` 字段只作为历史存储字段，不再决定回放物理位置。

### 改动文件

| 文件 | 改动 |
| --- | --- |
| `backend/runtime/context_management/physical_context_plan.py` | 新增统一 `provider_visible_context_prefix`；删除 active/archive 物理分流；`dynamic_tail` 不再直接进入 prefix。 |
| `backend/runtime/context_management/provider_visible_context_ledger.py` | 新确认 entry 写入统一 lane；ledger replay 投影为统一 lane，不继承旧 `ledger_lane`。 |
| `backend/runtime/model_gateway/provider_payload.py` | cache-spine 诊断和结构前缀识别只认 `global_static_prefix + provider_visible_context_prefix`。 |
| `backend/harness/runtime/compiler.py` | manifest 的 tail 后稳定段检查同步为统一 lane。 |
| `backend/runtime/context_management/context_pipeline_standardization_refactor_plan.md` | 物理模型、分配表、读取策略和验收标准改为插线式模型。 |

### 实测结果

继续 DeepSeek CLI 会话：

```text
session-58c9b0dcc40e4e5c
```

发起两轮真实 follow-up：

```text
turn 13: 插线式物理上下文验证第7轮
turn 15: 插线式物理上下文验证第8轮
```

两轮模型均真实返回 `OK`。

最新 segment map：

| request | lane_order | lane_counts | stable_after_tail | ledger index |
| --- | --- | --- | ---: | --- |
| `...:13:single_agent_turn:1:1` | `global_static_prefix -> provider_visible_context_prefix -> current_turn_tail` | `10 / 19 / 3` | 0 | sorted |
| `...:15:single_agent_turn:1:1` | `global_static_prefix -> provider_visible_context_prefix -> current_turn_tail` | `10 / 22 / 3` | 0 | sorted |

message content hash 前缀比对：

```json
{"r13_len":32,"r15_len":35,"common_prefix":32,"r13_is_prefix_of_r15":true}
```

结论：物理拼接断层已经修复。第 13 轮完整 message 序列成为第 15 轮前缀，证明旧上下文交接是稳定 append-only 的。

### 剩余不合格项

DeepSeek provider 返回的真实缓存命中仍约为 80%：

| request | prompt_tokens | cached_tokens | hit_rate |
| --- | ---: | ---: | ---: |
| `...:13:single_agent_turn:1:1` | 48845 | 39296 | 0.8045 |
| `...:15:single_agent_turn:1:1` | 50579 | 40832 | 0.8073 |

这说明当前低命中不再是 message 顺序断层，而是剩余不可缓存预算过大：

- `native_tool_binding_schema` provider sidecar 约 3974 tokens，虽然 schema hash 已 matched，但 DeepSeek 自动缓存统计仍把它算入 prompt miss 预算。
- normal turn 仍有约 5755 tokens volatile tail / current tail。
- memory maintenance 会产生更大的 `memory_maintenance_current_delta`，最新约 5182 tokens。
- `dynamic_projection`、`lifecycle_runtime_guidance` 已作为 replay-only 被封存，但诊断仍会把它们识别为“语义来源动态”，需要继续把内容拆成稳定事实 + 小型 current delta。

下一阶段目标不再是修物理顺序，而是把不可缓存尾部和 provider sidecar 预算压到 5% 以内。
| `backend/runtime/model_gateway/provider_payload.py` | drift 比对侧改为使用共享 `canonical_provider_schema_ref()`，不再使用本地 `_short_schema_ref()`。 |

### 局部 schema ref 对照

对原先 6 个漂移工具重新做稳定目录 ref 与 provider transport ref 对照：

| tool | fixed stable ref | fixed provider ref | status |
| --- | --- | --- | --- |
| `git_branch_list` | `sha256:fcb141e753` | `sha256:fcb141e753` | OK |
| `git_diff` | `sha256:4b1918470d` | `sha256:4b1918470d` | OK |
| `git_log` | `sha256:2355f69343` | `sha256:2355f69343` | OK |
| `git_show` | `sha256:a69b5ea9c7` | `sha256:a69b5ea9c7` | OK |
| `git_status` | `sha256:ea327cf3dd` | `sha256:ea327cf3dd` | OK |
| `list_dir` | `sha256:f7bd0297ac` | `sha256:f7bd0297ac` | OK |

`mismatch_count = 0`。

### 真实 CLI turn 验证

验证入口：`backend.cli.main send`，固定后端 `http://127.0.0.1:8003/api`。

Session: `session-39a238607722437d`

| turn | run | prompt_tokens | cached_tokens | hit_rate | native_tool_binding_schema |
| --- | --- | ---: | ---: | ---: | --- |
| 1 | `turnrun:strun:42426eeb8f0e4e6ead60fc714fe390ca` | 38222 | 0 | 0.0000 | `matched` |
| 2 | `turnrun:strun:d0e4d855d8ee44668bb536e3d5545a97` | 38406 | 25984 | 0.6766 | `matched` |
| 3 | `turnrun:strun:c4515827716746248180fe9be307e66a` | 38591 | 31744 | 0.8226 | `matched` |

三轮 `native_tool_binding_schema` 均为：

```text
native_tool_binding_decision = validated_against_tool_catalog_manifest
sidecar_drift_status = matched
transport_contract_role = stable_provider_tool_schema
content_hash = sha256:db8f5d141c0dfd9bba15406db28aeda5d64cf03f926ad8d2f52f020eee4341c1
predicted_tokens = 3974
```

结论：

1. 工具 schema drift 断点已修复，provider tools 不再被标记为 `provider_tools_do_not_match_tool_catalog_manifest`。
2. 常态缓存仍未达 95%。第三轮仍只有 `0.8226`，说明剩余主因不是 schema ref mismatch，而是稳定前缀过胖、native tools sidecar 仍占约 3974 tokens 且不可作为 message prefix 命中、动态尾约 1247 tokens，以及稳定段在 provider 可读范围内未完整覆盖。
3. 下一步应进入优先级 2：瘦身工具稳定前缀，删除 prompt 中重复的大 schema 表达，只保留语义目录、admission contract、schema refs 与 catalog hash；provider sidecar 继续作为真实工具调用权威。

## 2026-06-27 追加判断：为什么稳定前缀没有全命中

用户要求先处理“应该命中的必须命中”，再考虑瘦身。补跑同一 CLI session 后确认：

Session: `session-39a238607722437d`

| normal turn | prompt_tokens | cached_tokens | hit_rate | first_uncovered_stable_segment |
| ---: | ---: | ---: | ---: | --- |
| 1 | 38222 | 0 | 0.0000 | `global_static#2` |
| 2 | 38406 | 25984 | 0.6766 | `turn_stable#5` |
| 3 | 38591 | 31744 | 0.8226 | `lifecycle_stable#9` |
| 4 | 38776 | 31744 | 0.8187 | `lifecycle_stable#9` |
| 5 | 38961 | 31744 | 0.8148 | `lifecycle_stable#9` |

中间触发过一次 `memory-maintenance:session-39a238607722437d:8`，该维护调用 transport hash 与 normal turn 不同，命中 `25856/37918 = 0.6819`。normal turn 的 transport hash 保持：

```text
sha256:dc8b16b728dee9ad77f2478857f4af01cfe300435296f55b644f60bda7f8a896
```

### 已排除：稳定段字节漂移

三轮及后续 normal turn 中：

- `native_tool_binding_schema.sidecar_drift_status = matched`
- `global_static` 到 `runtime_baseline_refs` 的 `content_hash` 稳定。
- provider transport message common prefix 正常增长：

```text
turn1 -> turn2: common_message_count = 12
turn2 -> turn3: common_message_count = 13
turn3 -> turn4: common_message_count = 14
```

这说明旧上下文封存/重放在 message hash 层面成立，不是旧上下文字节被改写。

### 真正断点：never_replay_tail 让上一轮完整输入不是下一轮输入前缀

当前 single agent turn 的物理消息顺序是：

```text
cache_spine
-> current_turn_user_context
-> dynamic_projection
-> lifecycle_runtime_guidance
```

其中：

- `current_turn_user_context` 本轮在 `current_turn_tail`，provider success 后下一轮变成 replay。
- `dynamic_projection` 是 `never_replay_tail`，每轮变化，不会封存重放。
- `lifecycle_runtime_guidance` 也在 `never_replay_tail`，虽然本次内容 hash 稳定，但物理上仍位于当前用户消息之后，且不作为历史 replay。

因此两轮真实请求不是：

```text
turn1 = stable + user1
turn2 = stable + user1 + user2
```

而是：

```text
turn1 = stable + user1 + dynamic1 + lifecycle_tail
turn2 = stable + user1 + user2 + dynamic2 + lifecycle_tail
```

在 `user1` 之后，上一轮是 `dynamic1`，下一轮是 `user2`。也就是说，上一轮完整 provider input 并不是下一轮 provider input 的前缀。DeepSeek 自动缓存可以命中一部分重叠前缀，但不会保证把我们逻辑上定义的完整 stable spine 都作为可读 cache unit。

DeepSeek 官方 Context Caching 规则与这个现象一致：

- 后续请求必须完整匹配一个已经持久化的 cache prefix unit 才能命中。
- cache 是自动/best-effort，不保证 100% 命中。
- 旧公告也明确只考虑从第 0 token 开始的相同 prefix，64 tokens 为存储单位。

参考：

- `https://api-docs.deepseek.com/guides/kv_cache`
- `https://api-docs.deepseek.com/news/news0802`

### 修复判断

要先让“应该命中的稳定前缀”命中，不能先只做 token 瘦身。必须先修正 DeepSeek automatic prefix cache 的物理链：

1. `never_replay_tail` 不能继续作为普通 normal turn 的 provider-visible 后缀破坏 request-boundary cache unit。
2. `lifecycle_runtime_guidance` 若内容稳定，应升级进稳定前缀；若选择条件动态，则必须变成短小的当前用户执行约束或不进入 provider-visible prompt。
3. `dynamic_projection` 必须拆分：
   - 可封存的 durable runtime facts 进 `context_append`，下一轮 replay。
   - 当前轮控制 cursor 不计入希望命中的 cache spine，且不能放在会阻断 request-boundary cache 的位置。
4. prompt accounting 需要新增一个 provider-aware 指标：`request_boundary_cacheable_prefix`。当前的 `logical_stable_prefix` 对 DeepSeek automatic cache 来说过于乐观。

只有这条物理链修正后，再做工具 schema/catalog 瘦身，95% 目标才有工程意义。否则即使瘦身，仍会出现“逻辑稳定、provider 只命中一部分”的断层。
