# 上下文标准化与物理拼接优化总计划

日期：2026-06-26
状态：执行中。2026-06-27 已完成第一轮标准化落地：typed context pipeline 基础层、工具 transcript 统一 kind、compiler 主链收口、baseline refs 稳定前缀化、`read_file` 重复读取准入第一版。本文档整合此前两份文档：

- `backend/runtime/context_management/context_pipeline_standardization_refactor_plan.md`
- `docs/context_physical_splicing_model.md`

语义空间约束文档：

- `backend/runtime/context_management/agent_semantic_space_context_design_20260627.md`

后续工具契约瘦身、native tools admission、runtime control 封存优化必须先满足该语义空间规范，再处理 token 和 provider cache 细节。

执行顺序锁定为：

```text
先标准化上下文流水线
-> 再优化物理拼接、缓存命中、工具记忆、read_file、fork
```

## 0.1 2026-06-27 实施记录

本轮实施遵守“旧上下文不可以动一个字”的硬约束：所有已经 provider success 并进入 ledger 的旧 entry 仍只能由 ledger 按 provider-visible bytes 原样 replay。新命名、新语义标题、新 kind 只作用于当前轮新增 candidates、current append、dynamic tail cursor 和后续封存 entry。

已落地代码：

| 文件 | 动作 | 结果 |
|---|---|---|
| `backend/runtime/context_management/context_candidates.py` | 新增 | 定义 `ContextCandidate`、`ContextPolicyDecision`、`PhysicalContextSegment`、`ContextCommitCandidate`，并提供 message spec -> candidate shadow trace |
| `backend/runtime/context_management/context_candidate_registry.py` | 新增 | 定义 contributor registry，后续 source/projector 只能产 candidate，不直接塞 provider message |
| `backend/runtime/context_management/context_pipeline.py` | 新增 | 承接 capability filter、provider-visible ledger、physical plan 三段裁决，并输出统一 diagnostics |
| `backend/runtime/context_management/tool_transcript.py` | 新增 | 定义 `tool_transcript_delta` 为当前工具结果唯一语义 kind；旧 kind 只作为 historical replay detector |
| `backend/harness/runtime/compiler.py` | 重构 | 删除 compiler 内部 capability/ledger/physical helper，改由 `context_pipeline` 统一执行 |
| `backend/harness/loop/single_agent_turn.py` | 重构 | 当前 role=`tool` follow-up message 生成 `tool_transcript_delta`，旧工具观察 kind 不再作为新 spec 输出 |
| `backend/harness/runtime/compiler.py` | 重构 | observation follow-up 工具结果生成 `tool_transcript_delta`，metadata 只保留 `source_route` 诊断 |
| `backend/harness/runtime/assembly.py` | 清理 | capability/system group 的 context segment 清单改为 `tool_transcript_delta` |
| `backend/runtime/context_management/context_segment_policy.py` | 清理 | `runtime_baseline_refs` 归入 `static_prefix`；`runtime_memory_context/read_evidence_context` 不再被强制 volatile |
| `backend/runtime/prompt_accounting/cache_planner.py` | 清理 | replay token 诊断改按 `single_agent_turn_tool_call + tool_transcript_delta` |
| `backend/harness/runtime/dynamic_context/task_state_projector.py` | 清理 | dynamic cursor 中 `recent_tool_observations` 改为 `recent_tool_result_refs`，只保留 ref/status，不重复 transcript |
| `backend/runtime/tool_runtime/read_admission.py` | 新增 | 标准化 `read_file` admission：基于 file evidence scope、read range、mtime/hash、exact artifact/visible exact 判断 `allow_read` / `reuse_unchanged` |
| `backend/runtime/tool_runtime/native_tools.py` | 接入 | 本地 `read_file` 先 stat 再 admission；重复且未变化的 exact range 返回小型 ref delta，不重发全文；gateway 路径在证据足够时同样可短路复用 |
| `backend/runtime/memory/tool_observation_ledger.py` | 语义升级 | `read_file_reuse` 不再按新文件文本处理，而是分类为 `freshness_confirmation` + `prior_file_window_reference` |
| `backend/runtime/memory/evidence_delta_summary.py` | 语义升级 | 工具证据摘要透传 `semantic_delta`、`includes_file_text=false`、prior evidence refs |
| `backend/harness/runtime/compiler.py` | 语义命名 | 工具动态 append 的 agent-facing 标题由 `Tool result delta` 改为 `Current turn tool result` |
| `backend/runtime/context_management/context_candidates.py` | 类型化 | `ContextCommitCandidate` 补齐 ledger scope/item/provider/hash/lane/fork anchor 相关身份，并提供 provider payload segment -> typed candidate normalizer |
| `backend/runtime/model_gateway/model_runtime.py` | 收口 | provider success confirm path 不再拼裸 dict，改为从 provider payload segment 生成 `ContextCommitCandidate` |
| `backend/runtime/context_management/provider_visible_context_ledger.py` | 收口 | `confirm_provider_visible_context_entries` 只接受 `ContextCommitCandidate`，裸 dict 调用直接拒绝 |

当前主链变为：

```text
compiler source specs
-> context_pipeline.apply_context_capability_profile_to_specs
-> prompt source/assembly materialization
-> context_pipeline.build_context_pipeline
   -> specs_with_context_compaction_generation
   -> apply_provider_visible_context_ledger_to_specs
   -> apply_physical_context_plan_to_specs
-> slot/load/segment plan
-> provider payload
```

权威边界变化：

- compiler 只负责 turn packet orchestration，不再持有 provider-visible ledger 和 physical lane 的本地实现。
- `context_pipeline` 是当前上下文生命周期裁决入口。
- `context_segment_policy` 仍是 section/cache/sealable/semantic commit class 的唯一策略权威。
- `provider_visible_context_ledger` 仍是旧上下文和 fork inherited prefix 的唯一 replay authority。
- `physical_context_plan` 仍是 physical lane/cache spine 的唯一排序权威。

工具上下文现状：

```text
assistant tool call -> single_agent_turn_tool_call
tool result/current observation -> tool_transcript_delta
provider success -> ledger sealed tool transcript
next turn -> provider_visible_tool_transcript_replay
```

旧 kind：

```text
single_agent_turn_tool_observation
tool_observations
```

只允许出现在：

- `tool_transcript.py` 的 historical detector 常量。
- 本计划文档的历史风险说明。
- 已经封存的 ledger entry 原字节 replay metadata/历史记录中。

不允许再出现在：

- policy/capability/slot/render 决策表。
- compiler 新 spec 生成。
- assembly capability segment 清单。
- cache planner replay kind 集合。
- dynamic tail cursor 字段名。

已执行验证：

```powershell
python -m compileall backend/runtime/context_management backend/harness/runtime/compiler.py backend/harness/loop/single_agent_turn.py backend/harness/runtime/assembly.py backend/prompt_composition backend/runtime/prompt_accounting/cache_planner.py
python -m compileall backend/harness/runtime/dynamic_context/task_state_projector.py backend/runtime/context_management backend/harness/runtime/compiler.py backend/harness/loop/single_agent_turn.py
python backend/scripts/probe_deepseek_physical_dynamic_tail_cache.py --help
python backend/scripts/probe_deepseek_physical_dynamic_tail_cache.py --stable-lines 900 --context-chars 1400 --tail-chars 700
rg -n "single_agent_turn_tool_observation|tool_observations|recent_tool_observations" backend/harness backend/runtime backend/prompt_composition
rg -n "_apply_provider_visible_context_ledger_to_specs|_apply_physical_context_plan_to_specs|_apply_context_capability_profile_to_source_specs" backend/harness/runtime/compiler.py backend/runtime/context_management
python -m compileall backend/runtime/tool_runtime/read_admission.py backend/runtime/tool_runtime/native_tools.py backend/runtime/memory/file_state_authority.py backend/runtime/tool_runtime/tool_result_envelope.py
```

临时真实逻辑探针：

```text
seed FileStateAuthorityStore with read range 1-900, exact_artifact_ref, visible_exact, mtime_ns=123
same path/range with current mtime_ns=123 -> reuse_unchanged, no text field in tool_result
same path/range with current mtime_ns=456 -> allow_read, reason=file_freshness_changed

NativeReadFileTool physical path:
first read sample.py:1-5 -> status=ok, kind=text_file, visible text emitted
commit first file_state_events into FileStateAuthorityStore
second read sample.py:1-5 -> status=ok, kind=read_file_reuse, status=reuse_unchanged, no text field in tool_result, exact_artifact_ref preserved

Semantic dynamic lift:
second read sample.py:1-5 -> semantic_delta.change_state=unchanged, semantic_delta.current_observation.includes_file_text=false
ToolObservationRecord result_boundary.fact_status=unchanged_reused_window_evidence
ToolObservationRecord result_boundary.usable_as=[freshness_confirmation, prior_file_window_reference]

Typed provider-visible commit:
ContextCommitCandidate.from_provider_payload_segment(valid segment) -> ContextCommitCandidate
confirm_provider_visible_context_entries([typed candidate]) -> status=ok, confirmed_count=1, anchor_update_count=1
confirm_provider_visible_context_entries([candidate.to_dict()]) -> TypeError typed_only

Fork read evidence inheritance:
parent session file_state contains sample.py:1-5 exact read evidence
fork_session(parent -> child) -> child file_evidence_scope materialized from parent snapshot
child read admission sample.py:1-5 with same hash/mtime -> reuse_unchanged
child reuse tool_result has no text field
stale parent read range -> fork materialization skips stale range -> child read admission allow_read/no_prior_file_state
```

验证结果：

- 语法编译通过。
- cache probe 脚本可正常加载；此前发现的 `cache_planner -> context_management.__init__ -> session_compaction -> prompt_accounting` 循环导入已修复。
- 非 live 物理探针报告写入 `storage/runtime_state/prompt_cache_live_tests/deepseek_dynamic_tail_physical_probe_20260627_010241_e36d4f.json`。
- fork/read 继承切片后复跑非 live 物理探针，报告写入 `storage/runtime_state/prompt_cache_live_tests/deepseek_dynamic_tail_physical_probe_20260627_011135_30fe67.json`；结果仍为无 dynamic tail 的 message prefix 稳定、带 dynamic tail 的 strict full physical prefix 不稳定。
- 真实 DeepSeek live tail 探针写入 `storage/runtime_state/prompt_cache_live_tests/deepseek_dynamic_tail_physical_probe_20260627_011855_9f01f7.json`：tail 场景三轮 hit rate 为 `0.0 -> 0.6894 -> 0.9133`，说明 provider 能复用稳定共同前缀，但动态尾和本轮新增 append 预算会把总 hit rate 压到 95% 以下。
- 真实 DeepSeek live no-tail 对照写入 `storage/runtime_state/prompt_cache_live_tests/deepseek_no_tail_live_probe_20260627_012004.json`：无动态尾 append-only 三轮 hit rate 为 `0.9941 -> 0.9949 -> 0.9623`，说明常态稳定前缀链路已经过 95%，低命中的主要风险不是旧上下文字节被改写，而是 current append / dynamic tail token 预算。
- 真实 DeepSeek sealed tool transcript 对照写入 `storage/runtime_state/prompt_cache_live_tests/deepseek_tool_transcript_live_probe_20260627_012243.json`：thinking disabled 下三轮 hit rate 为 `0.9904 -> 0.9627 -> 0.9644`，说明 assistant tool call + tool result 作为已封存 transcript 进入 provider-visible history 时不会天然破坏缓存。
- DeepSeek thinking enabled 对手工构造的历史 assistant/tool transcript 要求回传 `reasoning_content`，因此 tool transcript 物理缓存探针使用 thinking disabled；项目真实链路若使用 thinking enabled，需要 provider adapter 层保证 reasoning history 的序列化契约稳定。
- `backend/scripts/probe_deepseek_physical_dynamic_tail_cache.py` 已增加 `--live-scenario tail|no_tail|both`，后续可以用同一个脚本复现 tail/no-tail live 对照。
- 非 live 探针显示：无 dynamic tail 场景 message prefix 维持严格前缀；带 replaceable dynamic tail 场景 previous messages 不是 current prefix，说明真实链路仍要继续防止 dynamic tail 占据 append 点。
- 旧工具 kind active 主链已清空；剩余命中仅为计划文档和 `tool_transcript.py` historical detector。
- compiler 旧 capability/ledger/physical helper 已删除。
- `skill_candidates` 未在 active backend prompt/runtime 路径中恢复。
- `read_file` admission 第一版已落地：重复读取只有在单个 active exact read window 覆盖目标窗口、freshness 未漂移、且有 exact artifact 或 visible exact 证据时才返回 `reuse_unchanged`；返回内容是当前 tool call 配对的小型 semantic delta，不包含旧全文。
- 动态语义已升级：重复 read 的意义不是“又得到一条旧观察”，而是“旧 exact evidence 仍有效、本轮没有新文本、后续可引用 prior evidence 或在范围/文件变化时重新读取”。
- provider success typed commit 已接入：`model_runtime` 只生成 `ContextCommitCandidate`，ledger confirm 只接受 typed candidate，避免裸 dict 字段继续作为封存主契约。
- fork snapshot 已补齐工具/read/replacement 继承锚：`fork_point_tool_context_anchor`、`fork_point_read_evidence_state_ref`、`fork_point_content_replacement_state_ref` 进入 `forked_from`，compiler/context pipeline diagnostics 可见这些锚。
- fork child 会在创建时把 parent session 的 file evidence snapshot 物化到 child session scope；后续 `read_file` admission 读取 child scope 即可复用 fork 点前未变化的 exact read window，不需要重新把旧全文放进动态尾。
- cache planner 已增加 expected miss budget 诊断：把低于 95% 的预测 miss 拆成 `current_context_append`、`dynamic_or_never_replay_tail`、`provider_transport_sidecar`、`uncategorized_non_prefix_payload`。前两类是正常新增/当前轮尾部成本，最后一类必须按 cache pollution 审查。

仍未完成：

- `read_file` 部分覆盖的 gap-only 读取尚未落地；当前第一版对“多个旧窗口拼接覆盖”或“部分缺口”保持 `allow_read`，避免制造组合文本断层。
- fork anchor 已补齐显式字段与 child file_state 物化；还需要做真实 provider fork 首轮缓存命中验证，并把 transport/tool/read drift 诊断接入最终验收报告。
- 内部字段 `agent_visible_runtime_projection` 仍作为 runtime delta projector 的输入对象名存在，但 projector 输出已经是 cursor，不是完整 dynamic tail；后续可做命名清理。
- 尚未做真实 no-tool follow-up、same follow-up、tool follow-up、fork child 的 provider cache 命中实测；需要 `probe_deepseek_physical_dynamic_tail_cache.py --live` 或真实前后端/模型链路。

原因很简单：如果不先统一“信息从哪里来、如何归一、谁能裁决、谁能渲染、谁能封存”，直接改物理拼接只会继续在 `compiler.py`、dynamic context、prompt composition、policy、ledger 之间补洞，缓存和 fork 仍然会被旧链路拉断。

## 1. 目标

本计划要把当前上下文系统升级为一条成熟 agent runtime 工作链：

```text
ContextSources
-> ContextNormalizer
-> ContextCandidateRegistry
-> ContextPolicyEngine
-> ContextAssembler
-> PhysicalContextPlanner
-> ProviderVisibleLedger
-> PromptRenderer / ProviderPayload
-> ContextDiagnostics
```

最终目标：

- 常态 follow-up 的缓存命中接近 95% 以上。
- 只有当前用户新增内容、当前轮 context append、当前轮 dynamic tail miss cache。
- 旧上下文只能从 provider-visible ledger 原字节 replay，不能动一个字。
- 新增上下文只能 append once，然后在 provider success 后封存。
- 工具历史统一为 `tool_transcript`，物理上分 sealed prefix 和 current delta。
- `read_file` 从“提示模型少读”升级为系统 admission 契约。
- fork child 继承 cache spine、tool transcript、read evidence、content replacement state 和 transport contract anchor。
- Agent 可见 prompt 使用语义标题，不暴露 `static_prefix`、`dynamic_tail`、`cache_spine` 这类开发标签。

## 2. 当前问题

当前系统不是缺少零件，而是决策权分散。

| 位置 | 当前职责 | 问题 | 目标 |
|---|---|---|---|
| `backend/harness/runtime/dynamic_context/manager.py` | 汇总 runtime/session/task/editor/attachment/tool projection | 同时做观察、投影、cache impact、section report | 降级为 source collector / projector |
| `backend/harness/runtime/compiler.py` | 生成 model messages、套 capability、ledger、physical plan、slot plan | 直接生成上下文 message specs，并散落多层策略 | 收缩为 turn packet orchestrator |
| `backend/runtime/context_management/context_segment_policy.py` | section/cache/sealable policy | route kind 与 semantic kind 混用 | 成为唯一 semantic policy authority |
| `backend/runtime/context_management/context_capability_policy.py` | capability group/slot policy | 仍按旧 kind 判断能力组 | 只按 semantic slot 决策 |
| `backend/runtime/context_management/physical_context_plan.py` | 五段 physical lane | 方向正确，但应只消费 policy decision | 保留为唯一 physical lane authority |
| `backend/runtime/context_management/provider_visible_context_ledger.py` | confirmed-entry ledger/fork inheritance | 方向正确，但 commit candidate 需要类型化 | 保留为唯一 sealed prefix authority |
| `backend/prompt_composition/*` | slot/layer/source kind 映射 | 重复判断 layer/dynamic tier | 降级为渲染和 tracing |
| `backend/runtime/prompt_accounting/cache_planner.py` | cache coverage 诊断 | 依赖 kind 列表 | 改按 physical lane / commit class 诊断 |
| `backend/harness/runtime/dynamic_context/tool_result_projector.py` | 工具结果投影/read evidence policy | 有成熟方向，但仍像提示建议 | 拆出 tool transcript 与 read admission |
| `backend/runtime/memory/file_state_authority.py` | file range/coverage/freshness | 可作为 read admission 事实源 | 接入 admission |

核心故障模式：

- 同一段上下文的 section、cache、capability、physical lane、agent-visible title 会被多个模块重复推断。
- `single_agent_turn_tool_observation` 和 `tool_observations` 这类 route name 被当成语义。
- `runtime_memory_context`、`read_evidence_context`、index cursor 等上下文有时被错误当成 volatile tail。
- 旧上下文可能从 session history 或 dynamic projection 重渲染，破坏 provider prefix。
- dynamic tail 曾被塞入完整 capability/tool/runtime projection，直接拉低缓存命中。

### 2.1 当前源码权威链

旧文档中的当前主链必须保留在总计划里，因为它是后续删除旧链路时的对照基线：

```text
RuntimeCompiler
-> message specs
-> context capability filter
-> provider visible context ledger
-> physical context plan
-> prompt slot/load/segment plan
-> provider payload
```

当前源码锚点：

| 责任 | 文件 | 关键入口 |
|---|---|---|
| 生成模型消息 specs | `backend/harness/runtime/compiler.py` | `_model_messages_and_segment_plan` |
| 过滤上下文能力组 | `backend/harness/runtime/compiler.py` | `_apply_context_capability_profile_to_source_specs` |
| 旧上下文 replay 与本轮 append 候选生成 | `backend/runtime/context_management/provider_visible_context_ledger.py` | `assemble_provider_visible_context_specs` |
| provider 成功后封存 append 候选 | `backend/runtime/context_management/provider_visible_context_ledger.py` | `confirm_provider_visible_context_entries` |
| 语义 section 分类 | `backend/runtime/context_management/context_segment_policy.py` | `context_segment_policy_for_spec` |
| 物理 lane 排序 | `backend/runtime/context_management/physical_context_plan.py` | `annotate_specs_with_physical_context_plan` |
| 物理 lane 决策 | `backend/runtime/context_management/physical_context_plan.py` | `physical_lane_for_spec` |

裁决：

- 标准化完成前，以上链路是事实上的 provider-visible 拼接主链。
- 标准化完成后，`ContextPipeline` 接管主链入口，但 ledger 和 physical plan 仍是核心权威。
- 旧的 session history、dynamic projection、工具 observation、skill candidate 不能绕过主链自行拼接 provider-visible history。

### 2.2 已清理内容

旧文档中的已清理项仍然是回归禁区，必须写进主计划。

`skill_candidates` 动态链已经被判定为不允许恢复：

- 可选 skill 清单的权威是 stable `capability_directory`。
- `skill_candidates` 会把候选 skill 全量渲染成动态 system message，拉低普通 turn 缓存命中。
- `active_skills` 可以保留，但只能表示当前轮已激活 skill 正文，不能变成候选清单。

`dynamic_projection` 已从完整运行投影收束为 cursor：

- 允许保留 invocation kind、allowed action types、plan mode、task_run allowed、tool count、stable tool index ref、permission scope、action schema refs。
- 不允许重新放回完整 `agent_visible_runtime_projection`、完整工具边界、完整执行边界、完整决策合同。

### 2.3 旧文档继承的 P0 清理项

这些不是“后续可选优化”，而是标准化前后都必须消除的主链风险。

| P0 项 | 当前风险 | 目标处理 |
|---|---|---|
| `runtime_memory_context` 策略冲突 | `compiler.py` 把它作为 session stable context spec，但 `context_segment_policy.py` 仍可能强制降成 volatile | 从 volatile override 移除，作为 `context_append -> provider success -> ledger seal -> next turn prefix replay` |
| `read_evidence_context` 策略冲突 | evidence refs/file facts 可能每轮重复 current tail，不能封存 | 与 `read_evidence_injection` 分离；前者 append/seal，后者 dynamic-only |
| index cursor 二次裁决 | `evidence_index_cursor`、`attachment_context_index`、`editor_context_index` 可能一边当上下文、一边永远 volatile | durable refs/facts 可 append/seal；UI/editor 瞬时状态进 dynamic tail 或 historical-only archive |
| `runtime_baseline_refs` section 矛盾 | 元数据像 session prefix，但 kind 列表可能当 memory context | 明确归入 `static_prefix` 或稳定 baseline ref section，不能每轮 append |
| 工具观察双路径名污染 | `single_agent_turn_tool_observation` 与 `tool_observations` 被分别列举，制造两种工具观察语义 | 统一为 `tool_transcript_delta`；旧路径只保留为 `source_route` |

P0 删除原则：

- 不能用兼容 mapping 继续支持旧 semantic kind。
- 不能让旧 kind 继续参与 policy/capability/slot/render 决策。
- 不能让 cache planner 继续按 route kind 判断 append/replay，而要按 semantic slot / commit class / physical lane 判断。

## 3. 成熟 Agent 对照结论

### Codex

参考源码：

- `D:\AI应用\openai-codex\codex-rs\protocol\src\models.rs`
- `D:\AI应用\openai-codex\codex-rs\core\src\context_manager\history.rs`
- `D:\AI应用\openai-codex\codex-rs\core\src\client.rs`

关键锚点：

- `protocol/src/models.rs:672`：工具结果是 `FunctionCallOutput { call_id, output }`。
- `protocol/src/models.rs:789` / `protocol/src/models.rs:820`：`FunctionCall` 与 `FunctionCallOutput` 均携带 `call_id`。
- `core/src/context_manager/history.rs:99` / `:119` / `:366`：history 追加、for prompt normalize、call/output 配对不变量。
- `core/src/client.rs:1013` / `:1087`：增量请求必须验证严格前缀，并使用 `previous_response_id`。

可借鉴机制：

- 工具调用和工具结果用 provider `call_id` 配对。
- history normalize 保证 call/output 成对。
- 增量请求必须验证当前 input 是上次 input 加新增 items 的严格前缀，满足时才用 `previous_response_id`。

本项目裁决：

- 工具 transcript identity 必须是 `tool_call_id` / `tool_use_id`。
- runtime route 只能是 `source_route` metadata。
- provider-visible old context 必须由 ledger 保障 prefix 连续性。

### Claude Code

参考源码：

- `D:\AI应用\claude-code-nb-main\utils\messages.ts`
- `D:\AI应用\claude-code-nb-main\services\api\claude.ts`
- `D:\AI应用\claude-code-nb-main\tools\AgentTool\forkSubagent.ts`
- `D:\AI应用\claude-code-nb-main\utils\toolResultStorage.ts`
- `D:\AI应用\claude-code-nb-main\tools\FileReadTool\FileReadTool.ts`

关键锚点：

- `utils/messages.ts:5133` / `:5303` / `:5306` / `:5437`：`ensureToolResultPairing`、缺失/孤儿 tool_result 检测、严格模式拒绝污染式修复。
- `services/api/claude.ts:3078` / `:3164`：cache marker 数量控制，以及只给缓存前缀内 tool_result 加 cache reference。
- `tools/AgentTool/forkSubagent.ts:98` / `:142`：fork child 生成 byte-identical API prefix，并为每个 `tool_use_id` 生成一致 placeholder tool_result。
- `utils/forkedAgent.ts:390`、`utils/toolResultStorage.ts`：fork 继承 content replacement state。
- `tools/FileReadTool/FileReadTool.ts:525`、`tools/FileReadTool/prompt.ts:8`：同路径同范围未变化时返回 unchanged stub，不重复全文。

可借鉴机制：

- `tool_use_id/tool_result` 是协议配对，不是普通文本。
- cache marker 受控，缓存前缀内 tool result 可引用 cache reference。
- fork child 构造 byte-identical prefix，并继承 content replacement state。
- `read_file` 对未变化的同一路径/范围返回 unchanged stub，不重复发送全文。

本项目裁决：

- fork 必须继承 cache spine、tool transcript prefix hash、content replacement decisions。
- 重复 read 未变化窗口只返回小型 reuse/unchanged delta，并与本轮 tool call id 配对。

### Hermes

参考源码：

- `D:\AI应用\hermes\hermes-agent-main\acp_adapter\session.py`
- `D:\AI应用\hermes\hermes-agent-main\acp_adapter\server.py`
- `D:\AI应用\hermes\hermes-agent-main\acp_adapter\events.py`

关键锚点：

- `acp_adapter/session.py:426` / `:472` / `:518`：持久化时原子 replace messages，恢复时读取 conversation history。
- `acp_adapter/server.py:970` / `:995`：历史 replay 用稳定 provider tool call id，并维护 active tool calls 配对。
- `acp_adapter/events.py:128`：同名并发工具用 FIFO 队列配对。

可借鉴机制：

- UI/ACP history replay 与 provider conversation history 分离。
- session 持久化用原子 replace，避免恢复时 tool call/result 断裂。
- 同名并发工具用稳定 id 或 FIFO 队列配对。

本项目裁决：

- UI timeline、progress observation、runtime diagnostics 不得进入 provider-visible transcript。
- 工具记忆必须由 provider transcript 与本地 evidence refs 双轨管理。

## 4. 统一目标模型

### 4.1 标准化流水线

| 层 | 允许做什么 | 禁止做什么 |
|---|---|---|
| `ContextSources` | 读取 session、task、tool、file、editor、attachment、memory 原始事实 | 判断 section/cache/lane/封存 |
| `ContextNormalizer` | 生成 canonical kind、semantic slot、source ref、content hash、freshness、range coverage | 渲染 prompt、排序 provider messages |
| `ContextCandidateRegistry` | 注册可插拔 contributor，收集 typed candidates | 插件直接塞 model message |
| `ContextPolicyEngine` | 一次性决定 section、capability、cache role、sealable、validity scope | 按 runtime route 重复定义语义 |
| `ContextAssembler` | 按 semantic slot 和 policy decision 编排 logical packet | 再次改变生命周期 |
| `PhysicalContextPlanner` | 唯一决定 physical lane、cache spine、prefix hash | 从旧 metadata 猜 lane |
| `ProviderVisibleLedger` | replay confirmed entries，provider success 后 commit append candidates | provider 成功前视为封存 |
| `PromptRenderer / ProviderPayload` | 渲染已裁决 segments | 根据 kind 重新分类上下文 |
| `ContextDiagnostics` | 输出 trace、hash、lane、seal status、污染检查 | 改变运行行为 |

硬不变量：

```text
gatherer 不决定 physical lane。
renderer 不决定 lifecycle。
ledger 是旧上下文唯一来源。
sealed old context 是不可变 provider-visible bytes，不是可重新渲染的语义对象。
dynamic tail 只表示 current-turn cursor。
runtime route name 不能成为 agent-visible semantic kind。
```

### 4.2 旧上下文不可变原则

旧上下文一旦被 provider success 确认并进入 ledger，就进入不可变状态。后续系统只能读取并按 ledger 记录的 provider-visible bytes 原样 replay，不能对旧 entry 做任何“修复式”或“优化式”处理。

严格禁止：

- 改旧 entry 的一个字、一个标点、一个换行或一个标题。
- 对旧上下文重新摘要、重新渲染、重新排序、重新分段。
- 给旧 entry 补字段后再生成新的 provider-visible 内容。
- 因为新的 agent-visible 标题规范而改写旧 entry 标题。
- 把旧 session history、dynamic projection、tool observation 重新拼成“等价”的历史上下文。
- 将旧 sealed tool result 重新压缩、替换、加前缀、换 source_ref 后 replay。

允许做的事只有：

- 校验旧 entry 的 hash、adapter contract、ledger index、previous entry hash。
- 按 ledger entry order 原样 replay confirmed bytes。
- 如果发现旧 entry hash drift 或缺失，进入 explicit recovery，不静默修复。
- 对当前轮新增内容使用新标准生成 candidate、policy、physical segment。
- 当前轮 provider success 后，把新增内容作为新的 immutable ledger entry 封存。

这条原则高于拼接优化。所谓“优化上下文拼接”只允许优化新上下文进入链路的方式，不能回头改已经封存的旧上下文。

### 4.3 数据对象

`ContextCandidate` 是 source/contributor 的唯一输出，不是 message。

| 字段 | 含义 |
|---|---|
| `candidate_id` | 稳定候选 id |
| `canonical_kind` | 语义 kind，例如 `tool_transcript_delta` |
| `semantic_slot` | 语义槽，例如 `tool_transcript` |
| `semantic_title` | agent-visible 标题 |
| `source_route` | runtime 来源路径，只用于诊断 |
| `source_ref` | 本地源引用 |
| `identity` | provider/tool/file/memory 稳定身份 |
| `payload` | 小型 model-visible payload |
| `content_ref` | 大内容 artifact/ref/rehydration 指针 |
| `content_hash` | provider-visible 内容 hash |
| `freshness` | hash/mtime/range/editor buffer 状态 |
| `provider_visibility` | `provider_visible` / `runtime_only` / `diagnostic_only` |
| `render_contract` | renderer schema，不含策略判断 |

`ContextPolicyDecision` 是唯一生命周期裁决。

| 字段 | 含义 |
|---|---|
| `section` | `static_prefix` / `context_memory_prefix` / `context_append` / `dynamic_tail` |
| `semantic_commit_class` | 封存语义 |
| `cache_policy` | cache scope、cache role、prefix tier |
| `capability_group` | capability policy group |
| `sealable` | 是否 provider success 后封存 |
| `validity_scope` | `session` / `task` / `turn` / `historical_only` |
| `stability_hash` | 策略输入 hash |
| `failure_policy` | hash drift、missing pair、stale read 等处理 |

`PhysicalContextSegment` 是唯一物理拼接对象。

| 字段 | 含义 |
|---|---|
| `physical_lane` | 物理 lane |
| `order_key` | 稳定排序 |
| `cache_spine_member` | 是否属于 provider cache spine |
| `provider_visible_hash` | provider message hash |
| `cache_spine_hash` | 截止当前段的 prefix hash |
| `ledger_entry_ref` | replay 来源或待 commit 目标 |
| `tail_break_reason` | tail 段破坏同请求 prefix 的原因 |

`ContextCommitCandidate` 是 provider success 后交给 ledger 的 typed candidate。

| 字段 | 含义 |
|---|---|
| `provider_message` | 已发送给 provider 的原始 message |
| `provider_visible_hash` | message hash |
| `adapter_contract` | provider serialization contract |
| `scope` | session/task/fork child scope |
| `semantic_commit_class` | 封存语义 |
| `source_ref` | source candidate ref |
| `physical_lane_before_commit` | 本轮通常是 `current_turn_tail` |
| `compaction_generation` | 压缩代际 |
| `fork_anchor_delta` | fork 继承附加锚点 |

## 5. 物理拼接模型

标准化完成后，物理拼接只允许按以下模型执行。

语义 section：

```text
static_prefix
context_memory_prefix
context_append
dynamic_tail
```

物理 lane：

```text
transport_contract
global_static_prefix
provider_visible_context_prefix
current_turn_tail
never_replay_tail
```

缓存 spine：

```text
global_static_prefix + provider_visible_context_prefix
```

Provider request 必须满足：

```text
transport_contract
-> global_static_prefix
-> provider_visible_context_prefix by ledger entry order
-> current_turn_tail
-> never_replay_tail
```

不允许：

- tail 后再出现 cache spine segment。
- context append 插入 static prefix 中间。
- dynamic tail 插入旧上下文中间。
- 用 active、historical-only、tool transcript、runtime replay-only 等语义标签拆分物理位置。

### 5.1 语义 Section 细则

`static_prefix` 是稳定协议、环境、工具、能力目录、输出契约。它不是会话记忆，不进入 provider-visible ledger，直接位于物理稳定前缀。

允许内容：

- global system / agent / environment / personality / lifecycle stable prompt。
- `turn_stable` / `task_stable` 中的 control capabilities、environment summary、capability directory、output contract。
- `tool_schema_catalog`、`tool_index_stable`、`action_schema_static`。
- `file_evidence_policy_stable`、read tool agent guidance。
- `artifact_scope_stable`、runtime baseline refs。

禁止：

- 混入当前 turn 状态。
- 每轮重排 capability directory、tool schema、tool index。
- 把候选 skill 全量卡片放进动态尾。

`context_memory_prefix` 是 provider success 后确认的旧上下文。它来自 ledger confirmed entries，下一轮按 ledger entry index 原字节 replay。

允许内容：

- previous user request / user constraints。
- sealed runtime memory context。
- sealed read evidence refs / file facts。
- sealed tool transcript / provider protocol history。
- task state replay entry。

禁止：

- 从 session history 重新渲染历史。
- 对旧 entry 改标题、换格式、重新摘要。
- 因语义可见性不同拆分物理 lane，打乱 ledger 原始顺序。

`context_append` 是本轮新增、需要模型看见、且 provider success 后要封存的上下文。它本轮位于 `current_turn_tail`，下轮才从 ledger replay 回 prefix。

允许内容：

- current user request。
- current selected memory。
- current read evidence refs / file facts。
- current tool transcript delta。
- user steering context append。
- task state replay entry。

禁止：

- 把 `context_append` 当作 dynamic tail。
- 下一轮仍重复作为 current tail。
- 用 `session_history_entry` 替代 ledger replay。

`dynamic_tail` 只服务当前 turn，是控制量、临时指令、当前运行边界。它永不封存，不参与 cache spine。

允许内容：

- 小型 `dynamic_projection` cursor。
- 当前触发的 lifecycle runtime guidance。
- 当前轮已激活 skill 正文。
- 当前 exact read evidence injection。
- 当前 UI/editor buffer delta。
- 当前恢复指令或运行信号。

禁止内容：

- 完整 capability directory。
- `skill_candidates`。
- 完整 tool schema 或 tool list。
- 完整 `agent_visible_runtime_projection`。
- 已经在 ledger 里的旧 user/tool/evidence/memory。
- 可封存的 `runtime_memory_context`、`read_evidence_context`。
- 重新包装后的旧 session history。

### 5.2 Physical Lane 细则

`global_static_prefix`

- 来源：`static_prefix`。
- 参与 cache spine。
- 作用：稳定系统/环境/工具/能力/输出契约。
- 污染风险：当前 turn 状态进入 stable payload；tool schema/order 每轮变化；capability directory 无意义重排。

`provider_visible_context_prefix`

- 来源：全部已确认的 `context_memory_prefix` provider-visible ledger entries。
- 参与 cache spine。
- 作用：按 ledger entry index 线性回放旧 user/memory/tool/evidence/runtime replay-only 字节，保持 provider prefix 连续。
- 污染风险：从 session history 重渲染同一历史；按 semantic visibility 拆分物理位置；把本轮 current append 提前塞入 prefix。
- 硬规则：语义差异只写入 `semantic_visibility`、`semantic_commit_class`、`validity_scope` 等 metadata，不改变物理拼接方式。
- fork 继承、压缩前 byte replay、已过语义有效期但仍需 prefix continuity 的 entry 都仍在这条 lane 内按 entry index 插线。

`current_turn_tail`

- 来源：`context_append`。
- 不参与同请求 cache spine。
- 作用：本轮新增、需要模型看见、provider success 后封存。
- 硬规则：它是上下文，不是动态控制尾；下一轮必须从 ledger replay 回 prefix。

`never_replay_tail`

- 来源：`dynamic_tail`。
- 不参与 cache spine。
- 作用：当前轮控制和临时信息。
- 硬规则：永远不 replay、永远不封存；越大越拉低 `cached_tokens / prompt_tokens`。

## 6. 上下文分配总表

| 内容 | section | physical lane | 是否封存 | 更新规则 |
|---|---|---|---:|---|
| global system / agent prompt / environment prompt | `static_prefix` | `global_static_prefix` | 否 | 版本化稳定 |
| capability directory | `static_prefix` | `global_static_prefix` | 否 | 可选 skills/tools 清单权威 |
| tool schema catalog / tool index | `static_prefix` | `global_static_prefix` | 否 | schema/order 变更即 transport drift |
| output contract / action schema | `static_prefix` | `global_static_prefix` | 否 | 稳定契约 |
| file evidence policy / read guidance | `static_prefix` | `global_static_prefix` | 否 | 稳定策略，不放当前 read |
| runtime baseline refs | `static_prefix` | `global_static_prefix` | 否 | 稳定 refs，不重复 append |
| previous user/memory/tool/evidence context | `context_memory_prefix` | `provider_visible_context_prefix` | 已封存 | 只能 ledger replay |
| fork/compaction inherited historical replay | `context_memory_prefix` | `provider_visible_context_prefix` | 已封存 | 只保 prefix continuity，语义标记为 historical-only |
| current user request | `context_append` | `current_turn_tail` | 是 | provider success 后封存 |
| current selected memory | `context_append` | `current_turn_tail` | 是 | 下轮 prefix replay |
| read evidence refs / file facts | `context_append` | `current_turn_tail` | 是 | refs/facts 封存 |
| current tool transcript delta | `context_append` | `current_turn_tail` | 是 | call/result delta 只追加一次 |
| current exact read text | `dynamic_tail` | `never_replay_tail` | 否 | 只服务当前轮 |
| editor cursor / current runtime signal / lifecycle trigger | `dynamic_tail` | `never_replay_tail` | 否 | 每轮可变，必须小 |
| active skill body | `dynamic_tail` | `never_replay_tail` | 否 | 只表示当前轮已激活 skill |
| progress event / UI timeline / diagnostics | 不进 provider-visible context | 不进 provider payload | 否 | 只进入 UI/trace |

Agent 可见标题必须是语义标题：

| 内部用途 | Agent 可见标题 |
|---|---|
| stable runtime contract | `Turn operating contract` |
| current user input | `Current user request` |
| memory context | `Selected memory context` |
| sealed tool transcript | `Tool conversation history` |
| current tool delta | `New tool result context` |
| runtime cursor | `Current runtime control` |
| exact read evidence | `Task current exact read evidence` |
| active skill body | `Active skill instructions` |

禁止在 model-visible title/preamble 中出现：

- `static prefix`
- `dynamic tail`
- `cache spine`
- `volatile runtime`
- `stable boundary`

## 7. 工具上下文记忆

工具历史只有一个语义对象：

```text
sealed tool transcript prefix
-> current tool transcript delta
-> provider success
-> next-turn sealed replay
```

统一字段：

| 字段 | 要求 |
|---|---|
| `tool_call_id` / `tool_use_id` | provider 协议配对主键 |
| `tool_name` | 诊断辅助 |
| `source_route` | 来源路径，只做诊断 |
| `event_index` | 稳定时序 |
| `provider_visible_hash` | 封存和 replay 校验 |
| `replacement_ref` | 大结果替换/压缩/ref 决策 |

重构裁决：

- 新语义 kind 使用 `tool_transcript_delta`。
- `single_agent_turn_tool_observation`、`tool_observations` 删除语义身份，只能作为 `source_route`。
- call/result 不成对时进入 explicit recovery，不合成无身份 prompt 文本。
- UI progress 和 runtime observation 不得替代 provider transcript。

不允许：

- 同一工具结果同时放入 sealed prefix 和 current delta。
- 因为来自不同 runtime 路径就生成两个 agent 可见观察块。
- 对已封存工具结果重新摘要、重新排序、重新加标题再 replay。

## 8. `read_file` Admission 契约

读取策略必须同时优化两层：

1. Agent 侧：知道什么时候读、读多少、什么时候复用。
2. 系统侧：只追加增量，旧内容从 sealed transcript / evidence refs / artifact ref 复用。

系统侧决策顺序：

| 顺序 | 判断 | 输出 |
|---:|---|---|
| 1 | path 是否规范化且在允许范围 | `reject`，返回可修复原因 |
| 2 | 目标 range 是否被 active exact read window 覆盖 | 未变化则 `reuse_unchanged` |
| 3 | 目标 range 是否只有部分缺口 | `execute_range`，只读缺口或推荐窗口 |
| 4 | 文件 hash/mtime 是否变化或缺失 | `execute_range`，读取当前需要范围 |
| 5 | 旧 exact text 是否被 artifact/ref 替换 | `rehydrate_ref` |
| 6 | 返回内容是否超预算 | exact text 入 artifact/ref，prompt 只放 refs 和必要窗口 |

必须满足：

- 不静默吞工具调用；复用也要返回与本轮 `tool_call_id` 配对的结构化 tool result。
- `reuse_unchanged` 只追加小型 ref delta，不重复发送全文。
- freshness 由 `content_sha256`、`mtime_ns`、range coverage、write/edit events、editor buffer state 共同判断。
- `read_evidence_context` 保存 refs/facts/coverage，可封存。
- `read_evidence_injection` 保存当前 exact text，只能进 `never_replay_tail`。
- fork child 继承 sealed transcript、read evidence refs、content replacement decision、file state anchor。

已落地的第一版系统准入：

| 条件 | 行为 |
|---|---|
| 没有 `file_evidence_scope`、没有 file state store、没有先前 file state | `allow_read` |
| file state 是 `unread/stale/changed/missing` | `allow_read` |
| 本地文件 `mtime_ns` 与 file state / read range 不一致 | `allow_read` |
| 目标窗口没有被单个 active exact read range 覆盖 | `allow_read` |
| 目标窗口被 active exact read range 覆盖，且 freshness 未漂移 | `reuse_unchanged` |
| 复用窗口缺少 `exact_artifact_ref` 且不是 `visible_exact` | `allow_read` |

`reuse_unchanged` 的 provider-visible 结果只允许包含：

- 当前 tool call 的结构化结果身份。
- `path/start_line/end_line/line_count/total_lines`。
- `reused_observation_ref`、`exact_artifact_ref`、`reusable_result_ref`。
- `content_sha256`、`mtime_ns`、`text_sha256`。
- `semantic_delta`：说明 `change_state=unchanged`、旧 exact evidence 仍有效、本次 observation 不包含文件文本。
- 一句面向 agent 的语义说明：可继续使用 prior evidence；只有换范围、文件变化或必须重新可见 exact text 时才再次读取。

不允许在 `reuse_unchanged` 中携带旧文件全文，也不允许把多个旧窗口临时拼成新文本；这种情况先 `allow_read`，后续由 gap-only read 专门处理。

动态语义规则：

| 动态结果 | 必须表达的语义 | 禁止表达成 |
|---|---|---|
| 新工具结果 | 本轮新增了什么事实、状态或失败 | 只有 `tool_result_delta` / route 名 |
| 重复 read 未变化 | 旧 exact evidence 仍有效，本轮没有新文件文本 | 再次输出旧观察文本 |
| 文件变化 / stale | 哪些旧 range 失效，需要重新读什么范围 | 把旧 range 当 current fact |
| 缺口读取 | 新增覆盖了哪个 gap，旧覆盖仍在哪里有效 | 把已覆盖窗口重新拼接成新全文 |
| rehydration | 本轮精确文本是从哪个 artifact/ref 恢复出来 | 把 artifact ref 当作普通历史摘要 |

`read_file` 增量必须分四类，不允许混放：

| 内容 | 目标位置 | 生命周期 |
|---|---|---|
| 本轮 exact read text / line window | `tool_transcript_delta`，必要时 `read_evidence_injection` | 本轮新增，provider 成功后封存 transcript |
| path/range/hash/mtime/artifact refs/coverage | `read_evidence_context` | 本轮 append，成功后 prefix replay |
| 未变化重复读取结果 | 小型 `tool_transcript_delta` 或 `read_evidence_reuse` ref | 不重发全文，只记录复用事实 |
| 临时编辑器 buffer delta | `current_editor_evidence_delta` / dynamic tail | 只表示当前 UI/editor 状态，不替代 sealed file fact |

读取相关上下文分配：

| 内容 | 进入哪一段 | physical lane | 是否封存 | 说明 |
|---|---|---|---:|---|
| read tool schema / 参数说明 | `static_prefix` | `global_static_prefix` | 否 | 稳定工具定义 |
| read tool agent guidance | `static_prefix` | `global_static_prefix` | 否 | 何时读、何时复用、何时 narrow |
| file evidence policy stable | `static_prefix` | `global_static_prefix` | 否 | admission 原则、path boundary、rehydration 优先级 |
| 本轮 read_file tool call | `context_append` | `current_turn_tail` | 是 | provider tool protocol transcript 新增 call |
| 本轮 read_file exact text / line window | `tool_transcript_delta` | `current_turn_tail` | 是 | 原始 tool result，成功后 sealed transcript |
| 本轮必须即时可见的 exact evidence | `read_evidence_injection` | `never_replay_tail` | 否 | 只服务当前轮 |
| path/range/hash/mtime/coverage/ref | `read_evidence_context` | `current_turn_tail` | 是 | 当前新增 evidence identity，成功后 prefix replay |
| 已封存 read_file exact result | `context_memory_prefix` | `provider_visible_context_prefix` | 已封存 | 只能 ledger 原字节 replay，不能重渲染；语义可标记 historical-only |
| 已封存 read evidence refs | `context_memory_prefix` | `provider_visible_context_prefix` | 已封存 | 供 agent 判断可复用窗口和 freshness |
| 未变化重复读取 | `tool_transcript_delta` 或 `read_evidence_reuse` | `current_turn_tail` | 是 | 小型 ref/stub，不含旧全文 |
| 缺口范围读取 | `tool_transcript_delta` + `read_evidence_context` | `current_turn_tail` | 是 | 只追加新 window，不重复旧 window |
| artifact / reusable result ref | `read_evidence_context` | `current_turn_tail` 后封存为 prefix | 是 | 大结果复用入口 |
| rehydrated exact text | `tool_transcript_delta` 或 current exact injection | `current_turn_tail` / `never_replay_tail` | 视用途 | 只有本轮必须精确可见才注入 |
| editor buffer delta | `dynamic_tail` | `never_replay_tail` | 否 | 当前 UI/editor 状态，不替代磁盘 read |
| stale / changed marker | `read_evidence_context` 或 tool result delta | `current_turn_tail` | 是 | 使旧窗口失效，要求后续读当前范围 |

增量提交规则：

```text
read_file exact text
-> current tool_transcript_delta
-> provider success
-> sealed tool transcript replay

read_file identity facts
-> current read_evidence_context
-> provider success
-> sealed read_evidence_context replay

unchanged repeated read
-> current tiny reuse delta
-> provider success
-> sealed reuse fact
```

不允许：

- 把 sealed read 全文重新放进 `read_evidence_injection`。
- 把旧 read 全文包装成新的 dynamic projection。
- 因为 agent 再次请求同一路径同 range，就生成第二份 identical exact text。
- 用 search preview、locator snippet 或 editor index 替代 exact read window 去做编辑。
- 文件已变化后继续把旧 sealed read 当作当前事实。

普通 follow-up 中，重复读取未变化文件的 provider-visible 变化应该只有当前用户新输入、一个很小的 unchanged/ref delta、必要的当前控制 tail。不应该变化 stable prefix、tool schema/index、已封存旧 read transcript、已封存 read evidence context、已封存 artifact/ref identity。

Agent 可见 read guidance 应是语义说明，不是开发说明：

```text
你可以读取工作区文件来获得当前事实。
读取前先判断当前上下文里是否已经有可用的文件窗口。
如果目标行范围已经被未过期的 read_file 结果覆盖，直接引用该结果，不要重复读取。
如果你只需要文件的一小段，请读取目标行附近的窗口，不要为了小范围读取整文件。
如果已有窗口被省略但提供了 rehydration_ref、reusable_result_ref 或 exact_artifact_ref，优先恢复该结果。
只有在文件可能已变化、目标行不在已有窗口、hash/mtime 缺失、或当前任务确实需要新内容时，才再次调用 read_file。
编辑前必须确认你使用的是当前文件内容；如果写入或编辑后还要继续判断，请以新的 hash/mtime 为准。
```

## 9. Ledger 与 Fork

### 9.1 封存边界

`provider_visible_context_ledger` 只能在 provider 成功后确认 append candidate。

```text
build candidates
-> policy decision
-> physical plan
-> provider request
-> provider success
-> confirm_provider_visible_context_entries
-> next request replay confirmed entries
```

失败请求可以写 provider request commit record，但不能确认 provider-visible replay entry。

### 9.2 Ledger Entry 身份

必须包含：

- provider-visible message content hash。
- canonical kind。
- semantic commit class。
- source_ref。
- adapter contract。
- provider/model。
- compaction generation。
- previous entry hash。

不允许用本地 session id + turn id 代替 provider-visible hash。

### 9.3 Fork Anchor

fork child 必须继承 confirmed cache spine，不是重新拼 session。

anchor 必须包含：

| 字段 | 说明 |
|---|---|
| `parent_scope` | 父 ledger scope |
| `fork_point_ledger_anchor` | confirmed ledger anchor |
| `terminal_entry_index` | 截止继承的最后 entry |
| `cache_spine_hash` | 父请求 cache spine hash |
| `transport_contract_hash` | provider/model/tool schema/params hash |
| `tool_transcript_prefix_hash` | 工具 transcript prefix hash |
| `content_replacement_state_ref` | 大工具结果替换决策 |
| `read_evidence_state_ref` | read refs、coverage、freshness |
| `compaction_generation` | 压缩代际 |

child 首轮：

```text
child global_static_prefix
-> inherited parent confirmed ledger entries up to anchor
-> child current_turn_tail
-> child never_replay_tail
```

如果 transport contract、tool schema、model params 与 fork point 不一致，记录 lineage reset，不解释成普通缓存低命中。

2026-06-27 已落地的 fork 继承模型：

```text
parent provider success anchor
-> forked_from.fork_point_provider_visible_ledger_anchor
-> child request ledger replay parent confirmed entries by anchor

parent latest provider_request_context_commit
-> forked_from.fork_point_provider_request_commit_id
-> forked_from.fork_point_tool_context_anchor
-> forked_from.fork_point_transport_contract_hash

parent session file_evidence_scope snapshot
-> forked_from.fork_point_read_evidence_state_ref
-> FileStateAuthorityStore.materialize_snapshot_scope(child session scope)
-> child read_file admission uses child scope and returns reuse_unchanged when range/hash/mtime match

parent content replacement refs
-> forked_from.fork_point_content_replacement_state_ref
-> diagnostics only; provider-visible old text remains ledger replay only
```

这个模型的关键不变量：

- fork 不重新渲染 parent session history。
- fork 不把 parent old read text 塞进 child dynamic tail。
- child file_state 是 fork 点的 read evidence 状态副本，后续 child 写入/读取只在 child scope 增量推进。
- provider-visible sealed prefix 仍只由 parent ledger anchor 原字节 replay。
- 如果 child 后续文件 freshness 变化，`read_file` admission 必须重新读取当前缺口，而不是继续复用 fork 点证据。

## 10. Transport Contract

`transport_contract` 不属于 message lane，但会影响 provider cache。

必须稳定：

- provider。
- model。
- temperature / max tokens / thinking mode / response format。
- tool schema。
- tool order。
- cache key 或 provider cache namespace。
- provider adapter contract。
- message serialization contract。

即使 message prefix 完全一致，只要 transport contract drift，缓存也可能失效。

## 11. 分阶段执行

### Phase 0：冻结合并计划

目标：确认本文档是唯一执行蓝图。

完成条件：

- 用户确认计划。
- 旧物理拼接文档只作为历史参考，不再独立指导实施。
- 列出所有旧 kind、旧 helper、旧 mapping 的删除清单。

禁止：

- 未确认前直接改 runtime 主链。

### Phase A1：建立标准化数据模型

目标：先把上下文变成 typed candidate，而不是直接拼 message。

影响文件：

- 新增 `backend/runtime/context_management/context_candidates.py`
- 新增 `backend/runtime/context_management/context_candidate_registry.py`
- 新增 `backend/runtime/context_management/context_pipeline.py`
- 更新 `backend/runtime/context_management/__init__.py`

完成条件：

- `ContextCandidate`、`ContextPolicyDecision`、`PhysicalContextSegment`、`ContextCommitCandidate` 类型存在。
- contributor 只能返回 candidate，不能返回 message。
- shadow trace 可记录 candidate -> policy -> lane，但不进入 provider payload。

禁止：

- shadow path 成为长期兼容路径。
- registry 做 section/lane 决策。

### Phase A2：Source/Projector 改成 Candidate 输出

目标：把信息获取、投影、生命周期决策拆开。

影响文件：

- `backend/harness/runtime/dynamic_context/manager.py`
- `backend/harness/runtime/dynamic_context/tool_result_projector.py`
- `backend/harness/runtime/dynamic_context/read_evidence_projector.py`
- `backend/runtime/memory/file_state_authority.py`

完成条件：

- tool、read evidence、editor index、attachment index、runtime memory 都能输出 canonical candidates。
- `cache_impact` 只保留为诊断或被 policy decision 替代。
- `tool_transcript_delta` 成为当前工具结果唯一语义 kind。

禁止：

- projector 指定 `physical_prefix_lane`。
- route name 作为 agent-visible title。

### Phase A3：PolicyEngine 单一裁决

目标：section、cache、capability、sealable 只裁决一次。

影响文件：

- `context_segment_policy.py`
- `context_capability_policy.py`
- `prompt_composition/runtime_slot_plan.py`
- `prompt_composition/assembly_plan.py`
- `prompt_composition/tracing.py`
- `runtime/prompt_accounting/cache_planner.py`

完成条件：

- `runtime_memory_context`、`read_evidence_context`、durable index refs 不再错误降为 volatile。
- `read_evidence_context` 与 `read_evidence_injection` 明确分离。
- `runtime_baseline_refs` 归入稳定 prefix。
- `single_agent_turn_tool_observation`、`tool_observations` 不再出现在 policy/capability/slot/render 决策表。

禁止：

- 为旧 kind 保留兼容 mapping。
- renderer/prompt composition 根据 kind 重新决定 dynamic tier。

### Phase A4：Compiler 切到统一 Pipeline

目标：`compiler.py` 从主决策者变为 orchestrator。

影响文件：

- `backend/harness/runtime/compiler.py`
- `backend/harness/runtime/packet_assembler.py`
- `backend/harness/loop/model_action_protocol.py`

完成条件：

- `_model_messages_and_segment_plan` 调用 context pipeline。
- `_apply_context_capability_profile_to_source_specs`、`_apply_provider_visible_context_ledger_to_specs`、`_apply_physical_context_plan_to_specs` 迁移到 pipeline 或删除。
- `_read_evidence_context_message_specs`、`_tool_observation_context_message_specs` 删除或变为 candidate adapter。
- agent-visible title 全部来自 semantic title。

禁止：

- old specs path 和 new candidates path 双主链。
- pipeline 失败时回退旧拼接器。

### Phase B1：物理拼接与 Cache Spine 优化

目标：标准化完成后，收紧 provider-visible 物理顺序。

影响文件：

- `backend/runtime/context_management/physical_context_plan.py`
- `backend/runtime/model_gateway/provider_payload.py`
- `backend/runtime/prompt_accounting/provider_payload_boundary.py`
- `backend/runtime/prompt_accounting/cache_planner.py`

完成条件：

- provider payload 只消费 `PhysicalContextSegment`。
- cache spine hash 只由 `global_static_prefix + provider_visible_context_prefix` 生成。
- `current_turn_tail` 和 `never_replay_tail` 不被计入同请求 cache spine。
- tail pollution diagnostics 能列出污染 kind/source_ref。

禁止：

- provider payload 从旧 section/cache_role 推断 lane。

### Phase B2：工具 Transcript 与 Read Admission

目标：工具记忆和文件读取进入系统契约。

影响文件：

- 新增 `backend/runtime/context_management/tool_transcript.py`
- 新增 `backend/runtime/tool_runtime/read_admission.py`
- `backend/runtime/tool_runtime/native_tools.py`
- `backend/runtime/tool_runtime/tool_result_envelope.py`
- `backend/harness/runtime/dynamic_context/tool_result_projector.py`
- `backend/runtime/memory/file_state_authority.py`

完成条件：

- tool call/result pairing 由 `tool_call_id` 校验。
- 重复 read 未变化同 range 返回 `reuse_unchanged` / `read_evidence_reuse` 小 delta。
- 缺口 range 只读缺口。
- stale/changed/missing hash 才重新读取当前所需范围。
- 大工具结果 replacement/ref 决策可被 fork 继承。

禁止：

- 静默吞工具调用。
- 复用旧 read 时重发全文。
- editor 当前 buffer 替代 sealed disk read。

### Phase B3：Ledger / Fork / Commit 类型化

目标：旧上下文和 fork 继承完全走 confirmed ledger。

影响文件：

- `provider_visible_context_ledger.py`
- `runtime/model_gateway/model_runtime.py`
- fork/session handoff 相关模块

完成条件：

- provider success 后唯一 commit 入口是 typed `ContextCommitCandidate`。
- failed provider request 不确认 ledger entry。
- fork child 按 anchor 继承 parent confirmed entries。
- transport contract drift 记录为 lineage reset。

禁止：

- child 从 parent session history 重渲染 old context。
- fork 忽略 content replacement state 或 read evidence refs。

### Phase B4：删除旧链路与验收

目标：删除所有不符合主链的旧逻辑。

完成条件：

- `skill_candidates` 不再进入 runtime prompt。
- `single_agent_turn_tool_observation` / `tool_observations` 只允许作为 `source_route` 常量或迁移文档文本。
- dynamic tail 不包含完整 tool list、capability directory、agent runtime projection、已封存旧上下文。
- 普通 follow-up 缓存命中目标：`cached_tokens / prompt_tokens >= 0.95`。
- same follow-up 后续 turn 确认上一轮 append 已封存并 replay。
- tool follow-up 确认 `tool_transcript_delta` 下一轮只从 sealed replay 出现。
- fork 首轮确认 inherited prefix、tool transcript prefix、read evidence refs、transport contract 连续。

禁止：

- 新增回归测试文件保护旧路径。
- 通过 mock、硬编码、跳过断言伪造通过。

### 11.1 旧文档执行顺序并入

旧物理拼接文档中的直接执行顺序并入本计划，作为 Phase A3 到 Phase B4 的具体落点：

1. 修正 `context_segment_policy.py` 中 `runtime_memory_context` 和 `read_evidence_context` 的 volatile override。
2. 审查 `evidence_index_cursor`、`attachment_context_index`、`editor_context_index`，按 durable refs 与 current UI state 拆分。
3. 将 `runtime_baseline_refs` 明确归入稳定 prefix。
4. 将 `single_agent_turn_tool_observation` 和 `tool_observations` 收束为 `tool_transcript_delta`，旧字段只保留在 `source_route` metadata。
5. 跑一次正常 no-tool follow-up 缓存实测，目标 95% 以上。
6. 跑一次 same follow-up 后续 turn，确认上一轮 append 已封存并 replay。
7. 跑一次 tool follow-up，确认上一轮 `tool_transcript_delta` 下一轮只从 sealed replay 出现。
8. 跑一次 fork child 首轮，确认 inherited prefix、tool transcript prefix 和 cache spine 连续。
9. 将 provider usage、physical plan、ledger entry count、dynamic tail kinds 写入报告。

## 12. 文件级清单

| 文件 | 动作 | 完成标准 |
|---|---|---|
| `backend/runtime/context_management/context_candidates.py` | 新增 | typed candidate/decision/segment/commit dataclasses |
| `backend/runtime/context_management/context_candidate_registry.py` | 新增 | contributor contract，只产 candidate |
| `backend/runtime/context_management/context_pipeline.py` | 新增 | 单入口 build context packet |
| `backend/runtime/context_management/tool_transcript.py` | 新增 | call/result pairing、delta/replay normalizer |
| `backend/runtime/tool_runtime/read_admission.py` | 新增 | read_file admission decision |
| `backend/harness/runtime/dynamic_context/manager.py` | 收束 | 只输出 source facts/candidates |
| `backend/harness/runtime/dynamic_context/tool_result_projector.py` | 收束 | read/tool projection 输出 canonical candidates |
| `backend/harness/runtime/compiler.py` | 主链改造 | 调用 context pipeline，删除旧 message-spec helper |
| `backend/runtime/context_management/context_segment_policy.py` | 清理 | 删除旧 route kind 语义映射 |
| `backend/runtime/context_management/context_capability_policy.py` | 清理 | 删除旧 route kind capability 映射 |
| `backend/runtime/context_management/physical_context_plan.py` | 保留并收口 | 只消费 policy decision |
| `backend/runtime/context_management/provider_visible_context_ledger.py` | 保留并类型化 | replay/confirm 只接受 typed commit candidate |
| `backend/prompt_composition/runtime_slot_plan.py` | 降权 | 不再猜 layer/dynamic tier |
| `backend/prompt_composition/assembly_plan.py` | 降权 | 消费已裁决 metadata |
| `backend/prompt_composition/tracing.py` | 降权 | 只做 trace，不做 fallback semantic mapping |
| `backend/runtime/prompt_accounting/cache_planner.py` | 改诊断依据 | 按 physical lane/cache spine/commit class 诊断 |
| `backend/runtime/model_gateway/model_runtime.py` | 接 typed commit | provider success 后确认 ledger |
| `backend/runtime/model_gateway/provider_payload.py` | 渲染收口 | 不从旧 section 推断 cache boundary |

## 13. 验证

遵守项目约束：不新增回归测试文件，不通过 mock 或硬编码制造通过。

静态检查：

```powershell
rg -n "skill_candidates|single_agent_turn_tool_observation|tool_observations" backend
rg -n "agent_visible_runtime_projection|available_tools|tool_schema_catalog" backend/harness backend/runtime
rg -n "physical_prefix_lane|context_cache_section|semantic_slot" backend/runtime backend/harness
```

物理顺序验收：

```text
global_static_prefix
-> provider_visible_context_prefix by ledger entry order
-> current_turn_tail
-> never_replay_tail
```

普通 follow-up 缓存验收：

```text
cached_tokens / prompt_tokens >= 0.95
```

允许 miss：

- 当前用户新增输入。
- 当前轮新增 context append。
- 当前轮 dynamic tail cursor。
- 当前 exact evidence injection。
- 小型 read evidence reuse / unchanged delta。

诊断口径：

- `target_warm_cache_read_rate_expected_miss_tokens` 是本轮预计不能命中的 token。
- `target_warm_cache_read_rate_expected_miss_families` 必须能解释 miss 来自 current append、dynamic tail、transport sidecar 还是未归类 payload。
- `uncategorized_non_prefix_payload` 大于 0 时，优先按旧上下文重渲染、动态尾污染、stable context 位置错误排查。
- current append 如果过大导致低于 95%，这不是旧上下文断层，但要检查是否本该在上一轮 provider success 后已经 sealed replay。
- dynamic tail 如果过大导致低于 95%，需要压缩 cursor 或把 durable facts 移到 append/seal，不能把动态尾伪装成稳定前缀。

不允许 miss：

- stable prompt。
- tool schema / tool index。
- capability directory。
- 已经 provider success 的 user/tool/evidence/memory context。
- sealed old context 的任何重渲染版本。

fork 验收：

- inherited ledger entries 按 parent anchor replay。
- child 继承 fork point cache spine hash。
- transport contract 与 fork point 一致。
- child 新增内容只追加在 inherited prefix 后。
- 如果 provider cache hit 为 0，先检查 transport contract drift 和 inherited prefix drift。

dynamic tail 污染检查：

- `capability_directory`
- `skill_candidates`
- 完整 `available_tools`
- 完整 `tool_schema_catalog`
- 完整 `agent_visible_runtime_projection`
- `session_history_entry`
- 已封存 ledger replay 的旧 user/tool/evidence 内容
- 已封存工具 transcript 或上一轮 `tool_transcript_delta`
- 同一路径同一 range 且未变化的旧 `read_file` 全文
- `runtime_memory_context`
- `read_evidence_context`

出现任意一项，都视为 cache pollution bug。

动态尾预算门槛：

- 常态 no-tool follow-up 中，`dynamic_or_never_replay_tail` 应小于总 prompt token 的 5%。
- 如果 `current_context_append + dynamic_or_never_replay_tail` 超过 5%，实际 hit rate 低于 95 是预期预算结果，不应误判为旧上下文断层；但必须继续压缩 current append 和 dynamic tail。
- 如果 `uncategorized_non_prefix_payload` 大于 0，优先审查是否有 durable facts 被误放入 dynamic tail，或已 sealed context 被重新渲染。
- `read_evidence_injection` 只能携带本轮必须精确可见的 exact evidence；历史 read refs 必须进入 `read_evidence_context` 并在 provider success 后 sealed。
- `incremental_context_cursor` 只能说明当前 invocation 的新事件 refs、runtime control refs、read evidence packet id，不得携带完整 tool result、完整 file text、完整 session history 或完整 task state。

Prompt packet 检查：

```powershell
python backend/scripts/inspect_runtime_prompt_packet.py <packet-or-taskrun-ref>
```

缓存物理探针：

```powershell
python backend/scripts/probe_deepseek_physical_dynamic_tail_cache.py --stable-lines 900 --context-chars 1400 --tail-chars 700
```

真实链路验证：

- 正常 no-tool follow-up：确认 stable prefix、ledger replay、current tail、dynamic tail 分布。
- same follow-up 后续 turn：确认上一轮 append 进入 sealed prefix，不重复 current tail。
- tool follow-up：确认 tool call/result 成对，current delta 下一轮只 replay。
- repeated `read_file`：同 path/range/hash 未变时只返回 ref delta。
- fork：确认 child inherited prefix hash 和 parent anchor 一致。

涉及前后端联调时，固定端口：

- 前端：`http://127.0.0.1:3000`
- 后端：`http://127.0.0.1:8003`

## 14. Cutover 规则

允许短期 shadow trace，但不允许长期双主链。

- shadow pipeline 只能写 diagnostics，不能 feed provider。
- 当某类 candidate 完成切换后，旧 helper 必须在同 phase 删除。
- 旧 route kind 不能作为 compatibility mapping 保留，只能转成 `source_route`。
- provider payload 不允许在 pipeline 失败时回退旧拼接。
- 如果切换后发现缺字段，应修 candidate contract，不恢复旧 message spec。
- rollback 只允许回到上一个 phase 的代码状态，不允许把旧链路作为 runtime fallback 合并进目标架构。

## 15. 不允许回退的旧链路

以下链路不允许恢复：

- `session_history_entry` 作为 provider-visible 历史拼接。
- `skill_candidates` 作为常态 dynamic system message。
- `single_agent_turn_tool_observation` / `tool_observations` 作为两个 agent 可见工具观察语义。
- 完整 `agent_visible_runtime_projection` 作为 dynamic tail。
- 用本地 session history 重渲染旧 provider-visible messages。
- 用兼容 fallback 保留旧 context assembly 主链。
- 用测试硬编码、mock、跳过断言伪造缓存命中。

核心不变量：

```text
先标准化数据和权威链。
再优化物理拼接。
旧上下文只能 ledger 原字节 replay，不能动一个字。
新增上下文只能 append then seal。
工具历史只能 call-id paired transcript。
动态尾只能 current-turn cursor。
fork 必须继承 cache spine。
```
