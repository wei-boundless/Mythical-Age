# 提示词系统架构第二阶段优化计划书

状态：已批准实施，核心上下文/搜索工具阶段已落地  
日期：2026-07-01  
范围：`prompt_library`、`prompt_composition`、`context_system`、`runtime.context_management`、`harness.runtime.compiler`、`runtime.tool_runtime`、`capability_system.tools`、`capability_system.capabilities.codebase_search`  
前置基础：承接 `prompt_system_architecture_refactor_plan_20260701.md` 已完成的第一轮结构落地  
原则：不加 V2，不保留旧链路并行；先收敛权威，再改模型；先删除旧决策，再整理命名。

## 0. 执行摘要

第一轮提示词体系重构已经完成核心方向：

- `AgentRuntimeProfile.prompt_set_refs/prompt_bindings` 已进入前后端配置链路。
- `PromptWiringPlan` 已成为本次 invocation prompt 接线的主入口。
- `PromptMountPlan` 已降级为环境挂载事实和旧诊断摘要。
- agent-visible projection 已从 compiler 中拆出。
- `prompt_composition.runtime_fragments` 已回到 fragment 渲染职责。
- `single_agent_turn`、`task_execution`、`tool_observation_followup` 已消费 `prompt_wiring_plan`。

本计划不是推倒重来，而是第二阶段优化：解决第一轮落地后仍存在的结构性风险。

当前需要优化的核心问题：

1. `PromptSet.extends` 只有全局 `seen` 去重，没有显式继承环路诊断。
2. `PromptResource` 通用模型承载了 task graph 专用字段，资源身份模型过宽。
3. `prompt_composition.slot_policy` 直接依赖 `runtime.context_management`，层级方向不干净。
4. `Slot` 概念在多个阶段重复命名，维护者难以判断每层责任。
5. 环境 18 槽提示词质量高，但正文集中在一个 Python 大字典里，审阅、版本和扩展成本高。
6. prompt `version` 已进入 metadata，但没有和内容 hash、运行实例、manifest 形成强审计链。
7. compiler 和旧诊断链路仍需要继续清理，避免旧权威通过旁路复活。
8. 本地查找工具链弱于成熟 coding agent：读文件链路已较完整，但搜索命令存在双实现、文本化解析、默认输出不利于定位、`codebase_search` 依赖弱底层搜索的问题。

正确终态不是减少功能，而是把提示词系统变成一条可追踪、可审计、单向流动的权威链。

本次执行记录（2026-07-01）：

- 已修复 `PromptSet.extends` 环路诊断：继承链出现 `A -> B -> C -> A` 时写入 `rejected_prompt_sets`，不再被全局 `seen` 静默吞掉。
- 已按“第四段只保留当前系统路标”的标准收缩 `DYNAMIC_TAIL`：`bound_task_runtime_context`、`task_goal_context`、`task_plan_context`、`task_todo_context`、`volatile_task_state`、`graph_node_runtime_context`、`user_steering_consumption_tail`、`session_history_tail_context`、`recovery_context_package`、`recent_work_outcome`、`evidence_delta_summary`、`evidence_semantic_summary`、`read_coverage_projection`、`execution_action_evidence` 已改为 `CONTEXT_APPEND`。
- 已在 producer/compiler 源头接线：上述可延续事实进入第三段 current append，并带 `semantic_slot`、`context_origin_ref`、`append_only_context_item_key`、`append_only_content_hash` 和 provider-success commit 策略。
- 已按最新严格裁决将 `read_evidence_injection` 与 `current_editor_evidence_delta` 从第四段拔出，改接到第三段 `CONTEXT_APPEND`：它们是 current evidence fact，不是系统路标；fact slot 以 path/range/event 为稳定锚点，content hash 只作为版本，避免同一文件窗口未变化时反复注入。
- 已保留第四段 current control：`active_execution_lease`、`evidence_acquisition_horizon`、`turn_state_guidance`、`turn_operating_contract`、`runtime_control_signal_tail`、`graph_node_completion_prefix`、partial stream recovery、answer contract、reasoning projection、active skill body 等仍为 `never_replay_tail` 或 request-local 控制。
- 已统一第四段默认策略：`DYNAMIC_TAIL` 默认 `context_commit_policy=never_commit`、`context_replay_policy=current_dynamic_tail_only`、`context_identity_policy=current_invocation_only`，避免诊断上出现“动态尾却按新 append 物化”或“路标被稳定复用”的语义冲突。
- 已完成 ContextSegment 声明/策略下沉：`context_system.segments.declarations`、`context_system.segments.policy`、`context_system.segments.metadata` 成为唯一源头，`runtime.context_management` 不再保留重复实现文件。
- 已删除旧 runtime 侧 `context_segment_registry.py`、`context_segment_policy.py`、`provider_message_replay_contract.py`，并把 runtime、harness、prompt_composition、prompt_accounting 调用方改为直接消费 `context_system.segments`。
- 已明确读文件优化原则：文件未变时可以复用/重建 exact read artifact；若 exact body 不可见或 artifact 不可恢复，工具应允许 fresh read，不应以“已读过”为理由拒绝合法读取。
- 已升级搜索主链路：`WorkspaceSearchService` 成为路径关键词、内容搜索和 glob 搜索的结构化底层权威；`python_symbol_search` 作为独立 AST 符号层进入 `codebase_search`；`SearchFilesTool` / `SearchTextTool` / `GlobPathsTool` / native workspace search / `codebase_search.providers` 只做 adapter 或 orchestrator，不再复制工作区搜索算法或解析人类可读搜索文本。
- `WorkspaceSearchService.glob_paths()` 已按成熟搜索工具标准优先使用 `rg --files --glob` 风格能力，保留 Python glob 作为 fallback，并在 `search_meta.backend` 中区分 `ripgrep_files` / `python_glob_fallback`。
- 已按 agent 使用需求优化搜索算法：`rg` 保留为高召回底层 primitive；多关键词自然语言查询进入文档级 AND 交叉召回 + BM25-lite 排序 + 最短关键词窗口定位；自然语言词组会生成 `workspace_search_service` 这类复合路径候选；路径搜索增加短语、compact identifier、stem、basename term 分域评分和长标识符降噪。
- 已修复搜索失败语义：Windows 下 `rg` 因不可读目录返回非 0 时，先解析 partial stdout，再按 structured Python fallback / keyword cross fallback 恢复；负结果必须带 `searched_roots`、backend、truncated/has_more，不再把 backend 异常误报成“没有证据”。
- 已建立 `codebase_search` 多层合流：path layer 产出 direct path candidates，symbol layer 产出 AST `symbol_match`，text layer 产出 literal / keyword-cross hits，glob layer 产出候选文件集合；ranker 只负责证据排序和去重，不把任一层伪装成万能搜索。
- 已补齐 `codebase_search` findings 的直接读窗：每条 finding 输出 `recommended_read_window`，同时 `code_structure_map` 保持 `read_request`；搜索 snippet 仍只作为 locator evidence，编辑/裁决前必须 `read_file`。
- 已修正 environment guidance 资源审计身份：54 个 guidance asset 生成的 `PromptResource` 均带 `owner_kind=environment` 与 `owner_ref=<environment_id>`，不再只把环境身份藏在 metadata 中。
- 已补充 PromptResource 内容审计基础：`PromptResource.to_dict()` 输出 `content_hash` 与 `version_label`，使 manifest/diagnostics 能追踪人工版本标签和真实内容哈希。
- 已执行 `python -m py_compile` 覆盖本次修改的 prompt wiring、context policy/registry/capability、context producers/compiler/manager、native tools 文件。

目标执行链：

```text
PromptResourceDefinition
-> PromptSetResolver
-> RuntimePromptWiringPlan
-> PromptAssemblyService
-> PromptSourceBundle
-> PromptMaterialPlan
-> ContextSegmentPolicy
-> RuntimeLoadPlan
-> PromptCompositionManifest
-> RenderResult
```

## 1. 成熟架构标准

成熟 agent runtime 的核心不是把所有规则写进 prompt，而是明确区分：

- 请求事实采集
- 边界和权限策略
- 上下文候选
- 模型当前轮裁决
- 动作许可
- runtime packet 装配
- 执行和观察
- 输出收口

本项目已有的目标链路可对齐为：

```text
RequestFacts
-> BoundaryPolicy
-> ContextCandidates
-> ModelTurnDecision
-> ActionPermit
-> RuntimeStartPacket
-> ExecutionLoop
```

提示词系统在这条链中只负责三类事情：

- 稳定契约：给 agent 当前可执行的身份、职责、边界、输出合同。
- 可见上下文：把真实 runtime/context/task/tool 事实投影为 agent 能理解的上下文。
- 物理装配：把已裁决的 prompt/context 变成 provider 可接收的 message/cache 结构。

外部参考中可借鉴的工程原则：

- LangGraph 强调 durable execution、state、human-in-the-loop、streaming 和 tracing。它说明成熟 agent 系统应有明确状态和可追踪执行，而不是依赖 prompt 隐式恢复。
- OpenAI prompt caching 和 Anthropic prompt caching 都强调稳定 prefix 与动态 tail 的物理边界。它支持本项目已有 `prefix_tier/cache_role/load_phase` 方向，但也要求 cache 语义由清晰策略层统一治理。

本项目不应照搬外部框架命名，但应吸收这些不变量：

- state 归 state，prompt 归 prompt，runtime 归 runtime。
- restore 不能替代 decide。
- prompt cache 是物理装配属性，不是业务语义判断。
- 可见 prompt 不能暴露内部开发说明和 runtime 控制字段。
- 每个 prompt 段落必须能追溯来源、owner、内容 hash 和本次选择原因。

参考资料：

- LangGraph overview: https://docs.langchain.com/oss/python/langgraph/overview
- OpenAI prompt caching: https://developers.openai.com/api/docs/guides/prompt-caching
- Anthropic prompt caching: https://platform.claude.com/docs/en/build-with-claude/prompt-caching

### 1.1 Claude Code / Codex 源码对照：current-only context 是否存在

本次补充只检查一个问题：成熟 agent 是否存在“每回合变化、模型可见、下一轮不作为旧上下文回放”的上下文结构。

结论：

- Claude Code 有明确等价物，但不叫 `dynamic_tail`，也不是一个大尾巴桶。
- Codex 没有采用大文本 `dynamic_tail` 形态，但有 per-turn request metadata、turn-scoped runtime state 和 compaction replacement history；它把需要确定回放的内容写入可重建历史，把只服务请求调度的状态留在 request/header/runtime 侧。
- 本项目 `DYNAMIC_TAIL -> never_replay_tail` 的物理方向是成熟的；需要优化的是动态尾承载内容过宽，应拆成第三段 current context 和第四段 never replay control。

Claude Code 证据：

- `D:/AI应用/claude-code-nb-main/query.ts` 中每轮先取 `getMessagesAfterCompactBoundary(messages)` 作为 `messagesForQuery`，说明模型输入是历史的投影视图，而不是完整 UI 历史。
- 同文件在调用模型前执行 `appendSystemContext(systemPrompt, systemContext)` 和 `prependUserContext(messagesForQuery, userContext)`；`userContext/systemContext` 是每次 API request 临时拼入的上下文，不直接写回历史数组。
- compact 后通过 `compact_boundary`、`preservedSegment` 和 `buildPostCompactMessages()` 形成新的投影视图，旧上下文不会因为 UI/REPL 还保留全量历史而被自动复活。

Codex 证据：

- `D:/AI应用/openai-codex/codex-rs/core/src/session/turn.rs` 每轮从 `clone_history().for_prompt(...)` 生成模型输入。
- `D:/AI应用/openai-codex/codex-rs/core/src/session/mod.rs` 的 `record_context_updates_and_set_reference_context_item()` 会把模型可见的稳定 initial context 或 diff 写入 history，并持久化 `TurnContextItem` 作为 resume/diff baseline。
- `D:/AI应用/openai-codex/codex-rs/core/src/compact.rs` compaction 会生成 `replacement_history`，resume 时从 replacement checkpoint 重建，而不是把压缩前的旧消息直接恢复给模型。
- `turn_metadata_header` 这类每轮请求元数据走 request header，不作为 conversation item 回放。

为什么 Codex 没有大文本动态尾：

- 大文本动态尾会让 resume、fork、compact 后的模型输入难以确定：同一会话恢复时无法判断该尾巴是历史事实、当前控制，还是上一次请求的临时调度状态。
- prompt cache 要求稳定 prefix；如果大量变化内容夹在可回放上下文之后，下一轮的可缓存前缀会被频繁截断。
- 工具调用协议要求 tool_use/tool_result 成对、顺序稳定；把临时控制和工具结果混在一个动态文本尾里，会增加 orphan tool result 和 replay 错位风险。

本项目应借鉴的不变量：

- 第三段 `current_turn_tail`：本轮新增、模型可见、provider success 后可确认进下一轮旧上下文的当前事实。
- 第四段 `never_replay_tail`：只服务当前 request 的运行边界、动作许可、恢复指令、当前 exact 注入；永不 seal，永不 replay。
- 大段动态尾必须收缩；能成为下一轮事实的内容进第三段，不能成为事实的控制态留第四段或改为 runtime side-channel。

### 1.2 Claude Code / Codex 源码对照：成熟 agent 的本地查找工具形态

本次补充只检查本地查找和读取证据的分工，不展开其它工具系统。

结论：

- Claude Code 采用专门的 `Glob` / `Grep` 查找工具，底层统一使用 ripgrep，工具契约明确区分“找路径”“找内容”“读精确文件”。
- Codex 当前核心本地文件查找主要依赖 `exec_command` / shell，由 agent 使用 `rg`、`rg --files`、`find` 等成熟命令；Codex 的 `tool_search` 是 deferred tool metadata 检索，不是本地代码库 grep。
- 本项目不应把弱语义搜索包装成成熟 code search。正确方向是：底层查找原语像 Claude Code 一样强而确定，上层 `codebase_search` 只负责多轮查询规划、证据切片和排序。

Claude Code 证据：

- `D:/AI应用/claude-code-nb-main/tools/GlobTool/GlobTool.ts` 的 `Glob` 是只读、并发安全、permission-aware 的专用工具，返回 `filenames`、`numFiles`、`durationMs`、`truncated`。
- `D:/AI应用/claude-code-nb-main/utils/glob.ts` 用 `rg --files --glob ... --sort=modified` 做文件枚举，并用 ignore patterns 和 plugin cache 排除规则降低噪声。
- `D:/AI应用/claude-code-nb-main/tools/GrepTool/GrepTool.ts` 的 `Grep` 默认 `output_mode=files_with_matches`，只有需要时才返回 content；它支持 `glob`、`type`、`content/context/-A/-B/-C`、`head_limit`、`offset`、`multiline`、`case insensitive`。
- `Grep` 的 content 输出会先分页再相对路径化，避免大结果污染上下文；`--max-columns 500` 用来抑制 minified/base64 噪声。
- `D:/AI应用/claude-code-nb-main/utils/ripgrep.ts` 区分无匹配、usage error、超时、权限/二进制不可用和部分结果；超时且无结果会抛错，不把“搜索没完成”误报成“没有结果”。
- `D:/AI应用/claude-code-nb-main/tools/GrepTool/prompt.ts` 明确要求使用专用 `Grep` 而不是 Bash 里的 `grep/rg`，并提示 open-ended 多轮搜索应交给 Agent tool。

Codex 证据：

- `D:/AI应用/openai-codex/codex-rs/core/src/tools/spec_plan.rs` 注册的核心本地执行工具是 `exec_command` / `write_stdin` / `apply_patch` 等，没有类似 Claude Code 的内建 `Grep` / `Glob` 本地搜索工具。
- `D:/AI应用/openai-codex/codex-rs/core/src/tools/handlers/shell_spec.rs` 的 `exec_command` 暴露通用 shell 命令能力；本地代码搜索通常由 agent 使用 `rg` 等命令完成。
- `D:/AI应用/openai-codex/codex-rs/core/src/tools/handlers/tool_search_spec.rs` 的 `tool_search` 描述是 deferred tool metadata BM25 检索，不用于搜索工作区文件内容。

工程裁决：

- 本项目应借鉴 Claude Code 的专用本地搜索工具形态，因为我们的 agent 需要稳定的路径、行号、候选读窗和 evidence refs，而不是让模型每次自己解析 shell 输出。
- 同时保留 Codex 式 `terminal` 弹性：当专用工具不足以表达复杂检查时，agent 可以使用 shell / `rg`，但这应是补充路径，不是主搜索能力的替代。
- `search_text` 的默认输出应偏向“候选文件 / 候选窗口”，而不是默认吐大量内容；精确代码判断和编辑前必须继续通过 `read_file` 建立 exact evidence。

## 2. 当前代码源报告

### 2.1 PromptResource 模型过宽

位置：

- `backend/prompt_library/models.py`
- `backend/prompt_library/registry.py`

事实：

- `PromptResource` 直接包含 `workflow_id`、`task_id`、`graph_id`、`node_id`、`stage_id`、`phase_id`、`step_id`、`step_kind`。
- `workflow_id/task_id/node_id` 当前用于 task graph prompt upsert 和排序。
- `phase_id/step_id/step_kind` 在 active prompt library 代码中基本只做序列化保留。

判断：

通用 prompt resource 不应该为某个专用 owner 域永久携带大量空字段。task graph 信息应变成 owner-scoped origin，而不是所有资源的顶层字段。

### 2.2 PromptSet 继承缺少环路诊断

位置：

- `backend/prompt_library/wiring.py`

事实：

`_collect_prompt_set()` 只使用全局 `seen`：

```python
if not ref or ref in seen:
    return
seen.add(ref)
...
for parent_ref in prompt_set.extends:
    _collect_prompt_set(...)
```

判断：

这能防止无限递归，但不能报告 `A -> B -> C -> A` 这种非法继承图。当前风险不是必然丢失所有内容，而是非法 topology 被当作普通去重静默处理，后续维护者无法从 diagnostics 中发现问题。

### 2.3 Composition 依赖 runtime context policy

位置：

- `backend/prompt_composition/slot_policy.py`
- `backend/runtime/context_management/context_segment_policy.py`
- `backend/runtime/context_management/context_segment_registry.py`

事实：

`prompt_composition.slot_policy` 直接 import runtime context policy 和 registry。

判断：

composition 层应该是物理 prompt/message 装配层，它可以消费 context segment policy，但不应该依赖 runtime 执行层路径。context segment 声明和策略应下沉到 `context_system`，由 composition 和 runtime 共同消费。

### 2.4 Slot 概念命名堆叠

位置：

- `backend/prompt_library/models.py`
- `backend/prompt_composition/models.py`
- `backend/prompt_composition/assembly_plan.py`
- `backend/prompt_composition/runtime_slot_plan.py`

事实：

当前存在：

```text
PromptSetSlot
RuntimePromptWiringSlot
PromptAssemblySlot
PromptCompositionSlot
RuntimePromptSlot
```

判断：

这些结构确实承载不同阶段的信息，但都叫 Slot 会掩盖真实职责。第二阶段应先固化每一层输入输出，再改名或合并，禁止只做表面重命名。

### 2.5 环境提示词集中在 Python 大字典

位置：

- `backend/prompt_library/environment_guidance_prompts.py`

事实：

- 18 个环境 guidance slot 结构清晰。
- coding、office、general 三套内容都在 `_PROMPTS_BY_ENVIRONMENT_AND_SLOT` 中。
- 文件约 617 行，正文审阅、版本 diff、单环境扩展都不够轻。

判断：

18 slot 设计应保留；存储方式应从 Python 常量正文迁到资源文件，Python 只保留 slot registry、loader 和校验。

### 2.6 Prompt version 未形成强审计链

位置：

- `backend/prompt_library/assembly.py`
- `backend/prompt_library/descriptor_resolver.py`
- `backend/prompt_composition/source_bundle.py`
- `backend/prompt_composition/renderer.py`

事实：

- `resource.version` 已进入 descriptor 和 assembly metadata。
- composition 中已有 `content_hash`、`model_message_hash`、render mismatch diagnostics。
- 但 `PromptResource.version` 与内容 hash 没有强绑定，也没有明确记录哪个 runtime invocation 使用了哪个 prompt resource hash。

判断：

后续应以内容 hash 为真实版本权威，人工 `version` 只作为可读标签。manifest 必须能追踪 prompt source、owner、version、content_hash 和选择原因。

### 2.7 Dynamic tail 过宽，需要收缩到第三段 current context

位置：

- `backend/runtime/context_management/context_segment_registry.py`
- `backend/runtime/context_management/context_segment_policy.py`
- `backend/runtime/context_management/physical_context_assembler.py`
- `backend/runtime/context_management/physical_context_plan.py`

事实：

- 四段物理 lane 已经存在：`global_static_prefix -> provider_visible_context_prefix -> current_turn_tail -> never_replay_tail`。
- `CONTEXT_APPEND` 会进入第三段 `current_turn_tail`；本轮不计入 expected cache read，provider success 后才可确认进下一轮 replay prefix。
- `DYNAMIC_TAIL` 会进入第四段 `never_replay_tail`；它当前用于 39 类上下文，覆盖 task state、evidence、runtime control、recovery、reasoning projection 等多种语义。
- `context_prefix_identity.py` 已把第三段生命周期标为 `current_append_pending_provider_success`，把第四段标为 `dynamic_tail_never_replay`。

判断：

当前问题不是“动态尾是否存在”，而是 `DYNAMIC_TAIL` 同时承载了两类完全不同的东西：

- 当前事实：本轮新增，但下一轮仍应被 agent 准确看见，或 provider success 后应成为旧上下文 replay 的候选。
- 当前控制：只约束当前 request 的行动、恢复、权限、输出边界，下一轮必须重新裁决或直接过期。

第一类不应该长期留在 `never_replay_tail`。它们应收缩到第三段 `current_turn_tail`，以 `CONTEXT_APPEND` 进入当前上下文，并在 provider success 后由 append ledger / physical frame 决定是否成为下一轮 confirmed old context。

第四段控制尾的准入必须更严格：它不是“变化频繁的上下文”，而是“不适合留在旧上下文里的当前系统状态路标”。只有当内容是当前租约、权限、恢复指令、动作 horizon、输出合同、reasoning/skill/request-local runtime flag，并且下一轮必须由 runtime 重新裁决时，才允许进入 `DYNAMIC_TAIL`。如果内容是任务事实、证据事实、读过什么、计划/todo 状态、最近工作结果，哪怕每回合都可能变化，也应作为第三段事实候选，通过 ref/hash/ledger 去重，而不是放进第四段过期。

应收缩到第三段 `current_turn_tail` 的内容：

| 当前 kind | 目标归宿 | 裁决 |
|---|---|---|
| `task_goal_context` | `CONTEXT_APPEND` / `current_turn_tail` | 任务目标是当前任务事实，不是一次性运行控制；应可在下一轮继续作为 task state replay。 |
| `task_plan_context` | `CONTEXT_APPEND` / `current_turn_tail` | 计划是持续任务状态，应按版本更新和确认，不应每轮作为不可回放尾巴重发。 |
| `task_todo_context` | `CONTEXT_APPEND` / `current_turn_tail` | todo 是可延续工作状态；本轮新增或更新后，provider success 再确认进下一轮。 |
| `bound_task_runtime_context` | 拆分后事实部分进 `current_turn_tail` | task/run 绑定事实应可回放；其中 lease、权限、执行窗口仍留第四段。 |
| `volatile_task_state` | 拆分后稳定事实进 `current_turn_tail` | 名称里的 volatile 不能掩盖其内部可能包含可延续 task facts；临时 flag 才留第四段。 |
| `turn_attention_index` | 拆分后裁决 | 若只重复指向 goal/plan/todo/evidence 的当前注意力路标，可留第四段并每轮重算；若承载唯一事实，必须把事实拆到第三段，第四段只保留路标。 |
| `session_history_tail_context` | 合并到 `session_history` / `CONTEXT_APPEND` | 已有 `session_history` current append 语义；不应同时保留一个 dynamic duplicate。 |
| `recovery_context_package` | 拆分后事实摘要进 `current_turn_tail` | 恢复指令留第四段；已发生的失败事实、最近输出事实可成为第三段当前事实。 |
| `recent_work_outcome` | `CONTEXT_APPEND` / `current_turn_tail` | 最近工作结果是下一轮需要知道的事实，不应在当前尾巴过期。 |
| `evidence_delta_summary` | `CONTEXT_APPEND` / `current_turn_tail` | evidence 的语义摘要和 refs 应可延续；原始 exact 注入另行处理。 |
| `evidence_semantic_summary` | `CONTEXT_APPEND` / `current_turn_tail` | 语义证据摘要属于当前事实，不是运行控制。 |
| `read_coverage_projection` | `CONTEXT_APPEND` / `current_turn_tail` | read coverage 是回答和后续行动都需要的证据覆盖事实，应以 refs/coverage matrix 进入第三段。 |
| `execution_action_evidence` | `CONTEXT_APPEND` / `current_turn_tail` | 已执行动作和对应证据是可验证事实，应进入当前 append。 |
| `current_editor_evidence_delta` | `CONTEXT_APPEND` / `current_turn_tail` | 当前编辑器 exact delta 是 evidence fact；用 path/event/range 做 fact slot，文本 hash 做版本，未变化不重复注入。 |
| `read_evidence_injection` | `CONTEXT_APPEND` / `current_turn_tail` | 当前 exact read window / read-required window 是 evidence fact；用 path/range/window_type 做 fact slot，内容 hash 做版本，变化时 supersede。 |
| `user_steering_consumption_tail` | 合并到 user steer current append | 用户 steer 的可见内容已有 `user_steering_context_append`；消费状态若需模型知道，应成为第三段事实，否则只留 runtime ledger。 |
| `graph_node_runtime_context` | 拆分后 node identity/facts 进 `current_turn_tail` | 节点身份、输入资产、裁决要求是当前任务事实；节点 lease、completion prefix、执行许可留第四段。 |

应继续留在第四段 `never_replay_tail` 的内容：

| 当前 kind | 裁决 |
|---|---|
| `active_execution_lease` | 当前执行租约，只约束本轮，不能 replay。 |
| `task_runtime_boundary_dynamic` | 当前 runtime 边界，下一轮应重新计算。 |
| `graph_node_completion_prefix` | completion prefix 是当前输出形态控制，不能成为旧上下文。 |
| `evidence_acquisition_horizon` | 当前行动 horizon，可由第三段 evidence/task facts 重新生成，不应直接 replay。 |
| `incremental_context_cursor` | 当前读取/增量游标是运行控制，不是历史事实。 |
| `active_skills` | full skill body 不应盲目 seal；只可把 active skill refs/已调用技能事实进入第三段，正文走 skill resource 或 compact attachment。 |
| `dynamic_projection` | 泛化动态桶应拆除；具体内容分别归第三段事实或第四段控制。 |
| `volatile_runtime_state` | runtime volatile flag 留第四段或 side-channel，不进入旧上下文。 |
| `semantic_compaction_request` | compact 请求是当前操作，不是模型历史事实。 |
| `accumulated_context_boundary` | 边界控制应进入 compact/assembly metadata，不作为可回放文本。 |
| `turn_state_guidance` | 当前轮状态引导是控制合同，下一轮重新裁决。 |
| `turn_operating_contract` | 当前 turn 行动合同，只服务本轮。 |
| `runtime_control_signal_tail` | runtime 控制信号只约束当前 request。 |
| `single_agent_turn_followup_action_contract` | follow-up 行动合同只服务本次 follow-up。 |
| `single_agent_turn_followup_message` | follow-up runtime message 是当前调度，不作为旧上下文。 |
| `partial_stream_recovery_instruction` | partial stream 恢复指令只在当前恢复请求有效。 |
| `partial_stream_recovery_visible_prefix` | visible prefix 是恢复现场，不可作为下一轮事实 replay。 |
| `provider_visible_ledger_recovery_checkpoint` | ledger 恢复 checkpoint 应走 ledger/diagnostics，不作为模型旧上下文。 |
| `answer_evidence_alignment_contract` | 当前回答约束合同，下一轮需要重新生成。 |
| `answer_alignment_feedback` | 当前反馈控制；若转成事实，应进入 `recent_work_outcome`。 |
| `reasoning_trace_projection` | reasoning projection 不应成为模型可回放旧上下文；必要时只做 diagnostics。 |
| `provider_reasoning_projection` | provider reasoning 投影不进第三段；必要时走 provider side-channel 或 diagnostics。 |

收缩规则：

- 第三段只接收“当前事实候选”：内容可 hash、可解释来源、可在 provider success 后确认，且下一轮看见它不会误导 agent。
- 第四段只接收“当前控制候选”：租约、权限、恢复、动作 horizon、输出合同、reasoning/skill/request-local runtime flags。
- 原始大文本和 skill body 不应因为“当前有用”就进入第三段；bounded exact read/editor windows 只有带稳定 path/range/event fact slot、content hash 和 supersession 策略时，才允许作为 current evidence fact 进入第三段。
- 若一个 kind 同时包含事实和控制，必须拆分 producer，不允许继续用一个 `dynamic_context_fragment` 混装。
- 改接线必须改在 producer / policy 源头：能延续的事实线从 `DYNAMIC_TAIL / never_replay_tail` 拔掉，接到 `CONTEXT_APPEND / current_turn_tail`；当前控制线继续留在第四段。禁止在 physical assembler 里把第四段文本整体搬到第三段，因为那会绕开语义审查、provider success 确认和 fact slot 去重。
- 每条线改接前必须做语义空间审查：先判断它是事实、控制、exact body、locator、coverage、recovery 还是 reasoning projection，再按成熟 agent 的上下文设计原则落位。不能因为名称里有 `context`、`state` 或 `tail` 就想当然迁移。

### 2.8 第三段 current context 不能变成重复记忆入口

位置：

- `backend/runtime/context_management/provider_visible_append_ledger.py`
- `backend/runtime/context_management/physical_prefix_frame_ledger.py`
- `backend/runtime/context_management/context_candidates.py`
- `backend/runtime/context_management/context_pipeline.py`
- `backend/harness/runtime/compiler.py`
- `backend/harness/runtime/incremental_context_frame.py`

事实：

- 当前 `provider_visible_append_ledger.py` 已经有 provider-visible append candidate 的 `item_key`、`provider_visible_hash` 和 confirmed entry 去重。
- 这套账本能防止同一个 provider-visible message 重复提交，但它仍以“消息候选”为中心，不足以表达“同一语义事实的小幅变化是否值得再次写入当前上下文 / 记忆”。
- 如果把 task state、todo、evidence summary 从第四段迁入第三段后仍按整段文本每轮 append，第三段会变成新的噪声源：微小变动反复进入 confirmed old context，压低缓存命中，压缩质量下降，也会让 agent 误以为状态发生了很多重要变化。

判断：

第三段不应该是“准记忆文本队列”，而应该是“本轮事实变更候选区”。成熟 agent 的不变量不是“每轮把当前事实都塞进去”，而是：

- 当前事实必须先归一到稳定事实槽位。
- 只有语义变化超过阈值，或产生新的证据 / 决策 / 用户约束，才生成 current append candidate。
- 同一事实槽位的小改动应更新最新 snapshot 或 delta，不应反复追加相同含义文本。
- 旧事实被新事实替代时，应有 `supersedes` / `replaces` 关系，不能让旧版本和新版本并列污染上下文。

目标记忆架构：

```text
producer raw projection
-> semantic fact normalizer
-> fact slot ledger
-> change classifier
-> current_turn_tail candidate
-> provider success
-> confirmed physical prefix frame
-> compaction / long memory summary
```

核心数据结构：

| 层 | 职责 | 不允许 |
|---|---|---|
| `current_turn_tail` | 只承载本轮需要模型看见的事实变化候选 | 不直接等同长期记忆 |
| `fact_slot_ledger` | 按 semantic slot/entity/source 记录最新事实 hash、版本、supersedes | 不保存大段原始文本 |
| `change_classifier` | 判断变化是 no-op、minor refresh、meaningful delta、replacement、new fact | 不按整段文本 hash 机械追加 |
| `confirmed_prefix_frame` | provider success 后确认模型实际看见过的事实 | 不确认失败请求中的候选事实 |
| `compaction_memory` | 将多个 confirmed delta 合并成稳定摘要 | 不保留每一轮微小重复 delta |

第三段写入规则：

| 变化类型 | 第三段行为 | 记忆行为 |
|---|---|---|
| `no_op` | 不写入 | 不更新 |
| `minor_refresh` | 一般不写入，只更新 ledger 的 seen_at / source coverage | 不生成新记忆 |
| `meaningful_delta` | 写入简短 delta，带 slot、source、hash | provider success 后可确认 |
| `replacement` | 写入“新事实替代旧事实”的最小说明，带 `supersedes` | 旧事实在 replay/compact 中被折叠 |
| `new_fact` | 写入事实摘要和证据 refs | provider success 后进入 confirmed frame |
| `ephemeral_control` | 不进第三段 | 留第四段或 side-channel |

事实槽位建议：

| slot | key 规则 | 变化阈值 |
|---|---|---|
| `task.goal` | `session_id + task_id + goal_id` | 用户目标、验收标准、范围变化才写入 |
| `task.plan` | `session_id + task_id + plan_version` 或 stable plan id | 步骤语义变化、顺序变化、阻塞变化才写入 |
| `task.todo` | `session_id + task_id + todo_id` | 状态迁移、负责人/对象/截止条件变化才写入；仅时间戳不写入 |
| `evidence.summary` | `source_ref + evidence_kind` | 结论、覆盖范围、关键 ref 变化才写入 |
| `read.coverage` | `artifact_ref + coverage_kind` | 覆盖集合变化才写入；重复读取不写入 |
| `recent.outcome` | `turn_id / action_id / deliverable_ref` | 新产物、新裁决、新失败事实才写入 |
| `user.steer` | `steer_id + contract_scope` | 用户约束变化才写入；消费标记走 runtime ledger |

成熟方案应采用“snapshot + delta + supersession”，而不是“每轮 append 当前状态全文”：

- Snapshot：每个事实槽位有当前权威值。
- Delta：只有语义变化进入第三段。
- Supersession：新事实替代旧事实时，旧事实被折叠，不再和新事实并列 replay。
- Confirmation：只有 provider success 后，第三段候选才允许进入 confirmed frame。
- Compaction：多个 confirmed delta 最终合并为稳定摘要，保留 refs 和版本，不保留重复轮次文本。

### 2.9 Read / evidence 去重不能把“文件未变”误判成“模型仍看得见”

本节针对一个真实工程故障：文件内容没有变化，但 agent 当前确实需要重新读取；如果系统反复返回“unchanged / 已读过”，而上一次内容已经被 compact、snip、预算裁剪或未进入当前物理上下文，agent 会被卡住。

Claude Code 证据：

- `D:/AI应用/claude-code-nb-main/tools/FileReadTool/FileReadTool.ts` 的 `Read` dedup 只在 `readFileState` 命中、读取 range 完全一致、磁盘 mtime 未变时返回 `file_unchanged` stub。
- `file_unchanged` 的文案不是拒绝，而是明确说：此前 `Read` tool_result 中的内容仍然 current，去引用此前内容。
- `D:/AI应用/claude-code-nb-main/utils/queryHelpers.ts` 的 `extractReadFilesFromMessages()` 会从 transcript 里提取真实 `Read` 结果来恢复 `readFileState`，并且跳过 `file_unchanged` stub，避免 stub 覆盖真实内容。
- `D:/AI应用/claude-code-nb-main/services/compact/compact.ts` 在 compact 时先保存 `readFileState`，然后清空它，再只把有限数量最近文件作为 post-compact attachments 恢复。也就是说 compact 后不会盲目相信所有旧读数仍在模型上下文里。
- `D:/AI应用/claude-code-nb-main/cli/print.ts` 有 `seed_read_state`：当客户端知道某次 Read 后来被 snip 移出上下文，transcript 提取不到时，可以补种 read state；补种前还检查磁盘 mtime，若文件已变则跳过补种，强制 fresh Read。
- `D:/AI应用/claude-code-nb-main/utils/fileStateCache.ts` 有 `isPartialView`：自动注入的 CLAUDE.md / MEMORY.md 若和磁盘原文不同，只能用于 diff / dedup，不能授权 Edit/Write。Edit/Write 必须要求真实 Read。

Codex 证据：

- Codex 没有 Claude Code 这种 `file_unchanged` Read-tool stub。文件内容通常通过 shell / unified exec 输出进入模型；需要再次读取时，工具会再次返回输出。
- Codex 的优化主要在 transport / history 层：`D:/AI应用/openai-codex/codex-rs/core/src/client.rs` 只有当新 request 的非 input 字段不变，且 input 是上一次 input + server output 的严格扩展时，才发送 incremental input delta。
- 因此 Codex 优化的是“不要重复传输已经稳定的请求前缀”，不是在 tool 层对 agent 说“你不能重新看这个文件”。

工程判断：

第三段的 evidence/read 去重必须区分三件事：

- 文件未变：磁盘内容相对某个 source hash / mtime 没变。
- 事实未变：语义摘要、coverage、结论没变。
- 模型仍看得见：对应内容或可替代摘要确实存在于本轮 provider payload 的 confirmed prefix / current append 中。

只有第三件也成立时，才允许返回 unchanged reference。否则“文件未变”只能阻止重复写长期记忆，不能阻止工具重新给模型必要内容。

目标规则：

| 情况 | 系统行为 |
|---|---|
| 文件未变，且同 range 的完整内容仍在当前模型可见上下文 | 可以返回 `unchanged_ref` / `already_visible_ref`，并指向可见 anchor |
| 文件未变，但内容已被 compact / snip / eviction 移出当前模型可见上下文 | 必须重新注入 full content、targeted excerpt，或明确生成 evidence restore attachment |
| 文件未变，但上次只是 partial/truncated view | 不允许返回 unchanged；需要按目标 range fresh read |
| 文件未变，但 agent 正准备 edit/write | 必须有 full-read state；partial view、summary、semantic memory 都不能授权写入 |
| 文件变化很小 | 不重复写 memory；给模型最小 diff / changed snippet |
| 语义事实未变，但 agent 请求 exact content | 不写第三段记忆，但工具可以返回 exact content 到当前第四段或 current read attachment |

必须新增的可见性契约：

```text
read_evidence_entry:
  source_ref
  range
  content_hash
  mtime
  body_visibility: visible | summarized | compacted_out | snipped_out | evicted | partial
  visible_anchor:
    physical_frame_id
    message_id
    physical_lane
    compaction_generation
  edit_authority: full_read | partial_view | summary_only | none
```

第三段只保存 `source_ref + range + content_hash + coverage + semantic summary`。原始 exact content 不因为“文件没变”写进长期记忆；但 read 工具 / evidence restore 必须能在 `body_visibility != visible` 时重新提供 exact content。

### 2.10 本地搜索工具链不够成熟

用户判断“读文件没问题，但查找命令似乎不太行”基本属实。当前不是一个简单 prompt 说明问题，而是搜索工具链的工程权威不够集中。

位置：

- `backend/capability_system/tools/tool_units/search_files_tool.py`
- `backend/capability_system/tools/tool_units/file_system_tools.py`
- `backend/runtime/tool_runtime/native_tools.py`
- `backend/capability_system/tools/native_tool_catalog.py`
- `backend/capability_system/tools/registries/TOOLS_REGISTRY.json`
- `backend/capability_system/capabilities/codebase_search/providers.py`
- `backend/capability_system/capabilities/codebase_search/runtime.py`
- `backend/capability_system/capabilities/codebase_search/query_planner.py`
- `backend/capability_system/capabilities/codebase_search/ranker.py`
- `backend/capability_system/capabilities/codebase_search/file_slicer.py`

事实：

- `search_files/search_text/glob_paths` 在 capability tool layer 和 native runtime layer 各有一套实现。两套逻辑相似但不完全等价，搜索语义和结构化输出容易漂移。
- `NativeSearchTextTool` 已经能输出结构化 `tool_result.kind=text_search`、`matches`、`recommended_read_windows`、`matched_paths`，方向是对的。
- `capability_system.tools.tool_units.SearchTextTool` 仍主要返回 `path:line:column:text` 文本；`context` 参数没有形成同等的推荐读窗输出。
- `codebase_search.providers.CodebaseSearchProviders` 直接调用 `SearchFilesTool._arun()` / `SearchTextTool._arun()`，再用 `_parse_path_results()` / `_parse_text_hits()` 解析人类可读文本。这会把上层 specialist 建在脆弱字符串格式上。
- `CodebaseSearchCapability` 本身做了 query planning、glob、text hits、slice、rank、evidence_refs，但它的 evidence 质量受底层搜索输出限制。
- `WorkspaceFileService.DEFAULT_SEARCH_ROOTS` 默认是 `docs/backend/frontend/knowledge`，默认不搜项目根目录；这能降噪，但会让根目录文件、配置文件或 AGENTS/README 类入口漏检，必须通过 clear diagnostics 指引 agent 追加 `roots=["."]` 或直接读已知路径。
- `search_files` 的路径搜索是 Python `os.walk` + substring / fnmatch，带 25k path / 5s 交互预算；它适合轻量路径关键词，但不等价于成熟 `rg --files` path index。
- 当前 prompt 已经正确说明：已知路径直接 `read_file`；未知位置按 `search_files/glob_paths/search_text` 定位；搜索结果不能替代 exact read evidence。问题主要在工具输出质量和权威实现上，不是 prompt 原则缺失。

判断：

读文件链路当前比搜索链路成熟：`read_file` 已有窗口、mtime、content hash、artifact、reuse decision、edit authority 等概念；搜索链路还没有同级别的 `search_result_ref`、`candidate_read_windows`、`negative finding`、`query strategy` 和稳定结构化 payload。

成熟搜索工具应当提供的是“下一步读哪里”的证据定位闭环，而不是只给几行文本：

```text
search intent
-> query plan
-> path candidates / text hits / symbol hits
-> ranked evidence locations
-> recommended read windows
-> exact read_file
-> current evidence coverage
-> answer / edit decision
```

必须避免的错误方向：

- 不要把 `codebase_search` 做成模糊语义搜索替代 `search_text`；它应该是组合式搜索 orchestrator。
- 不要让上层解析人类可读文本结果；工具 runtime 应提供稳定结构化 payload。
- 不要把搜索片段当作可编辑证据；搜索结果只产生 locator facts 和 candidate windows。
- 不要因为搜索命中重复而写入第三段记忆；只有 read/verification 后形成的 evidence summary 或 coverage delta 才可进入第三段。

## 3. 目标权威边界

### 3.1 prompt_library

职责：

- 定义 prompt resource、prompt pack、prompt set。
- 解析 PromptSet 继承。
- 管理 owner、scope、contract priority、conflict policy。
- 输出 RuntimePromptWiringPlan。

禁止：

- 不做 runtime context 物理分段。
- 不决定 provider payload 形态。
- 不做 agent-visible runtime 语义清洗。
- 不通过 fallback 静默修复非法继承图。

### 3.2 context_system

职责：

- 承载 context segment declaration。
- 承载 context segment policy。
- 定义 section、semantic slot、cache role、prefix tier、dynamic tier、load phase 的共享语义。

禁止：

- 不拼 provider payload。
- 不决定 prompt ref 是否注入。
- 不根据旧 runtime 状态重写用户目标。

### 3.3 prompt_composition

职责：

- 消费已经确定的 prompt/context message specs。
- 生成 source bundle、assembly plan、materialized packet、runtime load plan、composition manifest、render result。
- 验证 hash 和 projection 覆盖。

禁止：

- 不拥有 agent-visible 业务语义清洗。
- 不从 runtime 执行层 import 决策权威。
- 不决定 environment guidance 是否应该挂载。

### 3.4 runtime.context_management

职责：

- 消费 context segment policy。
- 执行 physical context assembly、provider-visible ledger、replay、seal、append/tail 管理。
- 执行第三段 current context 与第四段 never replay control 的最终物理分流。

禁止：

- 不作为 prompt composition 的基础依赖层。
- 不反向定义 prompt slot 语义。
- 不把 memory summary 或旧 replay 升级成当前用户意图。
- 不把 current control 当作可确认旧上下文封存。
- 不把 current facts 永久滞留在 `never_replay_tail`。

### 3.5 harness.runtime.compiler

职责：

- 编译 runtime packet。
- 调用 wiring、projection、composition、context pipeline。
- 记录 manifest 和 diagnostics。

禁止：

- 不内联 prompt ref 选择逻辑。
- 不内联 agent-visible sanitizer。
- 不保留旧 PromptMountPlan 的最终选择权。

### 3.6 capability_system.tools / runtime.tool_runtime

职责：

- 定义本地工具 schema、权限、runtime envelope 和结构化 tool result。
- 为 `search_files/search_text/glob_paths` 提供唯一搜索算法权威。
- 把搜索结果投影为 candidate paths、candidate read windows、negative findings 和 diagnostics。
- 保持搜索与读取分工：搜索定位，`read_file` 建立 exact evidence。

禁止：

- 不让 capability layer 和 native runtime layer 各自复制搜索算法。
- 不让上层 specialist 解析人类可读搜索文本作为主数据源。
- 不把搜索 snippet 升级为可编辑证据。
- 不把 incomplete / truncated / timeout 的负结果表达为确定不存在。

## 4. 目标数据模型

### 4.1 PromptResourceDefinition

目标：

保留通用字段：

```text
prompt_id
resource_id
category
subtype
resource_type
title
content
owner_layer
owner_kind
owner_ref
allowed_invocation_kinds
allowed_agent_refs
allowed_environment_refs
status
tags
priority
cache_scope
model_visible
contract_priority
conflict_policy
scope
source_ref
version
content_hash
enabled
metadata
origin
```

新增或明确：

- `content_hash`: 由 content 计算，作为真实内容审计标识。
- `origin`: 结构化来源，不同 owner 域可以放不同 payload。

task graph 来源示例：

```json
{
  "origin_kind": "task_graph_node_role_prompt",
  "workflow_id": "workflow.xxx",
  "task_id": "task.xxx",
  "graph_id": "graph.xxx",
  "node_id": "node.xxx",
  "stage_id": "node.xxx"
}
```

删除目标：

- 从顶层删除 `workflow_id/task_id/graph_id/node_id/stage_id/phase_id/step_id/step_kind`。
- 不保留旧字段作为长期兼容；迁移切换完成后 active code 不再读取这些字段。

### 4.2 PromptSetResolver

输入：

```text
registry
prompt_set_refs
agent_profile_id
environment_id
invocation_kind
```

输出：

```text
resolved_sets
rejected_sets
inheritance_graph
cycles
diagnostics
```

规则：

- 使用 `current_chain` 检测环路。
- 环路不是普通 warning，应进入 rejected diagnostics。
- 同一 prompt set 多路径引用时可以去重，但必须保留路径信息。
- parent 在 child 之前进入 resolved order。
- missing parent 必须明确记录，不允许静默跳过。

### 4.3 ContextSegmentPolicy 共享层

目标路径：

```text
backend/context_system/segments/declarations.py
backend/context_system/segments/policy.py
backend/context_system/segments/metadata.py
```

迁移后依赖方向：

```text
prompt_composition.slot_policy
runtime.context_management.*
        |
        v
context_system.segments.policy
```

禁止方向：

```text
prompt_composition -> runtime.context_management.context_segment_policy
```

### 4.4 Slot 命名目标

命名应体现阶段，不继续全叫 Slot。

建议改名：

```text
PromptSetSlot            -> PromptBindingSlot
RuntimePromptWiringSlot  -> PromptWiringBinding
PromptAssemblySlot       -> PromptMaterialSegment
PromptCompositionSlot    -> PromptManifestBinding
RuntimePromptSlot        -> RuntimeLoadSegment
```

是否合并：

- Phase 4 先改名和固定输入输出。
- 只有确认两个结构字段和生命周期完全重合时，才合并。
- 不为了减少类数量牺牲 traceability。

### 4.5 Environment Guidance 资源文件

目标目录：

```text
backend/prompt_library/prompt_assets/environment_guidance/
  coding/
    context_intake.md
    request_judgment.md
    ...
  office/
    context_intake.md
    request_judgment.md
    ...
  general/
    context_intake.md
    request_judgment.md
    ...
```

Python 保留：

- `ENVIRONMENT_GUIDANCE_PROMPT_SLOTS`
- environment id 到 prefix 的映射
- prompt id 生成
- loader
- 完整性校验

规则：

- 每个环境必须覆盖全部 18 slot，除非显式声明不支持。
- 文件正文必须是 agent 可直接执行的角色/工作提示，不允许写开发说明。
- loader 缺文件时失败或诊断，不自动生成空 prompt。

### 4.6 SearchResult 结构化模型

搜索工具输出应有稳定模型，不让上层解析展示文本。

建议模型：

```text
SearchQueryReceipt:
  query_ref
  search_kind: path_keyword | glob | text | symbol | codebase
  query
  roots
  paths
  glob
  case_sensitive
  output_mode
  search_engine: ripgrep | python_fallback | ast | lsp | composite

SearchMatch:
  path
  line
  column
  end_line
  text_preview
  match_kind: path | text | symbol | definition | reference | config | doc
  match_hash

SearchResult:
  receipt
  matches
  matched_paths
  recommended_read_windows
  negative_finding
  searched_roots
  omitted_roots
  truncated
  incomplete_reason
  diagnostics
```

规则：

- `text_preview` 是定位线索，不是 exact evidence。
- `recommended_read_windows` 才是下一步 `read_file` 的输入建议。
- `negative_finding` 必须携带 searched scope 和 completeness；不完整搜索不能生成确定否定结论。
- `SearchResult` 可以进入第三段的只有 locator / window / coverage 事实；不能直接进入 edit authority。

## 5. 分阶段实施计划

### Phase 1: PromptSetResolver 与继承环路治理

目标：

- 新增 `PromptSetResolver`。
- 替换 `wiring.py` 中 `_collect_prompt_set()`。
- 显式输出继承图、路径、环路和缺失 parent。

涉及文件：

- `backend/prompt_library/prompt_set_resolver.py`
- `backend/prompt_library/wiring.py`
- `backend/prompt_library/models.py`

完成标准：

- `A -> B -> C -> A` 被 diagnostics 明确报告。
- 多路径重复引用不会重复注入，但 diagnostics 保留来源路径。
- `RuntimePromptWiringPlan.diagnostics` 能看到 resolver 报告。
- 旧 `_collect_prompt_set()` 删除。

验证：

- 阅读 `wiring.py` 调用链确认新 resolver 是唯一入口。
- `rg "_collect_prompt_set|seen: set\\[str\\]" backend/prompt_library` 不再命中旧继承解析。
- `python -m py_compile` 覆盖新增和修改文件。

### Phase 2: PromptResource 通用模型瘦身

目标：

- 引入 `origin` 结构字段。
- task graph 专用字段迁入 `origin` 或 `metadata.task_graph`。
- 删除顶层 task graph 专用字段。

涉及文件：

- `backend/prompt_library/models.py`
- `backend/prompt_library/registry.py`
- `backend/prompt_library/descriptor_resolver.py`
- `backend/prompt_library/assembly.py`

完成标准：

- `PromptResource` 顶层不再携带 graph/workflow/step 专用字段。
- task graph role prompt 仍能生成稳定 resource id 和 source_ref。
- 排序不依赖 `workflow_id/task_id` 顶层字段，改用 `origin` 或 `resource_id`。
- descriptor 和 assembly metadata 可以追踪 origin。

验证：

- `rg "workflow_id|task_id|graph_id|node_id|stage_id|phase_id|step_id|step_kind" backend/prompt_library` 只允许出现在 origin 迁移、task graph upsert 或文档中。
- `python -m py_compile` 覆盖相关文件。

切换规则：

- 不做长期双字段兼容。
- 如需一次性读取旧存储 JSON，迁移函数只在 load 时转换为新结构，不把旧字段再写回。

### Phase 3: ContextSegmentPolicy 下沉到 context_system

目标：

- 把 context segment 声明和 policy 从 runtime 执行层迁到 `context_system/segments`。
- composition 和 runtime 都消费共享 policy。
- runtime 保留 physical context、ledger、replay、seal 的执行职责。

涉及文件：

- `backend/context_system/segments/declarations.py`
- `backend/context_system/segments/policy.py`
- `backend/context_system/segments/metadata.py`
- `backend/prompt_composition/slot_policy.py`
- `backend/runtime/context_management/context_segment_registry.py`
- `backend/runtime/context_management/context_segment_policy.py`
- `backend/runtime/context_management/context_candidates.py`
- `backend/runtime/context_management/context_pipeline.py`
- `backend/runtime/context_management/physical_context_assembler.py`

完成标准：

- `prompt_composition.slot_policy` 不再 import `runtime.context_management.context_segment_policy`。
- runtime context modules 从 `context_system.segments` import 声明和 policy。
- 旧 runtime policy 文件如需保留，只能作为薄 re-export 过渡；本阶段结束后删除或降为兼容入口并设定删除点。

验证：

- `rg "from runtime.context_management.context_segment_policy" backend/prompt_composition backend/context_system` 无命中。
- `rg "from \\.context_segment_policy|context_segment_policy_for_spec" backend/runtime/context_management` 只指向共享 policy 或清晰 wrapper。
- `python -m py_compile` 覆盖 composition、context_system、runtime context 相关文件。

### Phase 3A: Dynamic tail 收缩到第三段 current context

目标：

- 保留 `never_replay_tail`，但将其从“大动态尾桶”收缩为纯 current control lane。
- 将可延续当前事实迁入 `CONTEXT_APPEND -> current_turn_tail`。
- 删除或拆分泛化 `dynamic_context_fragment`，让 producer 明确产出 current fact 或 current control。

涉及文件：

- `backend/runtime/context_management/context_segment_registry.py`
- `backend/runtime/context_management/context_segment_policy.py`
- `backend/runtime/context_management/context_candidates.py`
- `backend/runtime/context_management/context_candidate_gateway.py`
- `backend/runtime/context_management/context_pipeline.py`
- `backend/runtime/context_management/physical_context_assembler.py`
- `backend/harness/runtime/compiler.py`
- `backend/harness/runtime/context_message_producers.py`
- `backend/harness/runtime/dynamic_context/**`

迁移裁决：

- `task_goal_context`、`task_plan_context`、`task_todo_context`、`recent_work_outcome`、evidence summary / coverage / action evidence 类进入第三段 `current_turn_tail`。
- lease、runtime boundary、action contract、partial stream recovery、answer contract、exact read injection、reasoning projection 类继续留第四段 `never_replay_tail` 或改为 side-channel。
- 混合 kind 必须拆 producer：事实部分进入第三段，控制部分留第四段。

完成标准：

- `DYNAMIC_TAIL` 中不再包含 task state facts、recent work facts、evidence semantic facts 这三类可延续事实。
- 第三段新增 current fact entries 均有 `context_contract_ref` 或稳定 source identity、content hash、semantic slot。
- 第三段 entries 在本轮仍不参与 expected cache read；provider success 后才允许由 append ledger / physical frame 确认。
- 第四段 entries 的 `context_commit_policy` 均为 `never_commit`，且 diagnostics 能解释其过期条件。
- `dynamic_projection` 保持 request-local control 或继续拆分；`volatile_task_state` 已收缩为 `task_state_cursor` 第三段事实，不再作为 `DYNAMIC_TAIL` 主线模型可见输入。

验证：

- 人工检查 `context_segment_registry.py`：可延续 facts 不再声明为 `DYNAMIC_TAIL`。
- `assemble_physical_context_spine()` diagnostics 中，task/evidence/recent work facts 出现在 `physical_segment_lineage.current_append` 或 `current_tail`，不出现在 `never_replay_tail`。
- 三轮普通对话的诊断能区分 `current_turn_tail` 正常 miss 和 `never_replay_tail` excluded，不把第三段计入本轮 expected cache read。
- provider 失败时第三段 current append 不晋升；provider success 后才进入下一轮 confirmed frame。

### Phase 3B: 第三段 current facts 去重、归一和记忆晋升

目标：

- 防止第三段从 dynamic tail 噪声变成 append memory 噪声。
- 建立 semantic fact slot ledger，使 current facts 先归一、判定变化，再进入 `current_turn_tail`。
- 用 `snapshot + delta + supersession` 替代“每轮 append 当前状态全文”。

涉及文件：

- `backend/runtime/context_management/provider_visible_append_ledger.py`
- `backend/runtime/context_management/physical_prefix_frame_ledger.py`
- `backend/runtime/context_management/context_candidates.py`
- `backend/runtime/context_management/context_candidate_gateway.py`
- `backend/runtime/context_management/context_pipeline.py`
- `backend/harness/runtime/compiler.py`
- `backend/harness/runtime/incremental_context_frame.py`
- `backend/harness/runtime/context_contract/nodes.py`
- `backend/harness/runtime/dynamic_context/**`

设计裁决：

- 新增或明确 `fact_slot_key`：由 `semantic_slot + entity_ref + source_ref + scope` 组成，不能只用整段 provider message hash。
- 新增 `change_class`：`no_op`、`minor_refresh`、`meaningful_delta`、`replacement`、`new_fact`、`ephemeral_control`。
- 第三段只接受 `meaningful_delta`、`replacement`、`new_fact`。
- `no_op` 不写入第三段；`minor_refresh` 只更新 ledger metadata，例如 `seen_at`、coverage ref，不生成模型可见新文本。
- `replacement` 必须携带 `supersedes`，使 replay / compact 能折叠旧事实。
- task/todo/plan/evidence/read coverage/recent outcome/user steer 都必须按事实槽位输出最小 delta，不允许每轮输出完整状态大段文本。
- evidence/read 类去重必须额外检查 `body_visibility`：只有 exact content 或等价可用摘要仍在本轮 provider payload 中可见时，才允许返回 unchanged/visible ref。
- 如果 source hash/mtime 未变但 `body_visibility` 是 `compacted_out`、`snipped_out`、`evicted`、`partial` 或未知，read/evidence producer 必须提供 fresh content、targeted excerpt 或 restore attachment，不能返回“已经读过”的拒绝式结果。
- edit/write 授权只能来自 `edit_authority=full_read`；第三段 semantic summary、partial view、coverage fact 都不能替代真实 Read。

完成标准：

- 同一个 task goal / todo / evidence summary 在内容语义未变时，连续三轮不会生成新的 `current_turn_tail` provider-visible append candidate。
- todo 仅状态从 `in_progress` 到 `completed` 这类语义迁移会写入 delta；更新时间、观察时间、重复 projection 不写入。
- evidence 只在 coverage 集合、关键结论或 source refs 变化时写入；重复 read 不写入第三段。
- read/evidence unchanged 优化不会阻止模型重新获得当前不可见的 exact content。
- confirmed old context 中不会同时长期保留同一 fact slot 的多个未折叠版本。
- diagnostics 能展示每个被过滤候选的 `fact_slot_key`、`change_class` 和过滤原因。
- diagnostics 能展示 read/evidence 条目的 `body_visibility`、`visible_anchor`、`edit_authority`，以及 fresh-read fallback 是否触发。

验证：

- 人工读取 candidate diagnostics，确认 filtered entries 有明确 no-op/minor-refresh 原因。
- 对三轮同任务无实质变化的 packet 编译结果做物理段检查：第三段不重复出现相同 task/todo/evidence facts。
- 对一次 todo 状态变化和一次 evidence 新 ref 变化做物理段检查：只出现最小 delta，不出现完整状态重放。
- 对 provider 失败路径检查：fact slot ledger 不把失败请求中的 candidate 标为 confirmed。
- 对“文件未变但上次 Read 已被 compact/snip/evict”的场景做物理段检查：系统必须重新注入 exact content 或 targeted excerpt，而不是返回 unchanged ref。
- 对“文件未变且上次 full Read 仍在当前 payload 可见”的场景做物理段检查：系统可以返回 unchanged ref，但必须带可追踪 visible anchor。

### Phase 3C: 搜索工具能力升级与 evidence 定位闭环

目标：

- 把本地查找工具升级到成熟 coding agent 标准：稳定、快速、结构化、可分页、可定位读窗。
- 收敛 `search_files/search_text/glob_paths` 的权威实现，避免 capability layer 和 native runtime layer 双实现漂移。
- 让 `codebase_search` 建在结构化 search result 上，而不是解析人类可读文本。
- 明确搜索结果只产生 locator facts / candidate windows；exact evidence 仍由 `read_file` 建立。

涉及文件：

- `backend/capability_system/tools/tool_units/search_files_tool.py`
- `backend/capability_system/tools/tool_units/file_system_tools.py`
- `backend/capability_system/tools/tool_units/python_ast_tools.py`
- `backend/capability_system/tools/native_tool_catalog.py`
- `backend/capability_system/tools/registries/TOOLS_REGISTRY.json`
- `backend/runtime/tool_runtime/native_tools.py`
- `backend/runtime/shared/file_observation_policy.py`
- `backend/runtime/tool_runtime/tool_result_envelope.py`
- `backend/runtime/tool_runtime/tool_definition.py`
- `backend/capability_system/capabilities/codebase_search/providers.py`
- `backend/capability_system/capabilities/codebase_search/runtime.py`
- `backend/capability_system/capabilities/codebase_search/models.py`
- `backend/capability_system/capabilities/codebase_search/query_planner.py`
- `backend/capability_system/capabilities/codebase_search/ranker.py`
- `backend/capability_system/capabilities/codebase_search/file_slicer.py`
- `backend/prompt_library/tool_prompts.py`
- `backend/prompt_library/io_capability_prompts.py`
- `backend/prompt_library/rules.py`

设计裁决：

- 不允许用一个搜索机制包打天下。成熟 agent 的本地检索应是多层体系：路径层、符号层、正文层、glob/文件集合层、历史层分别拥有自己的原语和失败语义，最后由 `codebase_search` 合流。
- `search_text` 底层必须以 ripgrep 为主实现；fallback 只用于 rg 不可用或受限场景，并且 diagnostics 必须说明 fallback / incomplete。
- `search_text` 默认输出策略应接近 Claude Code：默认偏 `files_with_matches` 或紧凑 matches，只有显式需要时才返回 content/context。
- `search_text` 必须支持并结构化表达：`query`、`regex/literal`、`case_sensitive`、`glob`、`type`、`roots`、`paths`、`output_mode`、`context`、`head_limit`、`offset`、`truncated/incomplete`。
- `glob_paths` 应优先走 `rg --files --glob` 风格能力，返回按可解释排序后的路径、`truncated` 和搜索边界；Python walk 只能作为 fallback。
- `search_files` 应重新定位为“路径关键词搜索”，可内部复用 file index / `rg --files` 输出，而不是和 `glob_paths` 重叠成弱通配符工具。
- 新增或统一 `SearchResult` 结构：`query_ref`、`search_kind`、`searched_roots`、`matches`、`matched_paths`、`recommended_read_windows`、`negative_finding`、`truncated`、`incomplete_reason`、`search_engine`。
- `CodebaseSearchProviders` 不再解析工具文本输出，改为消费结构化 payload 或共享搜索 service。
- `codebase_search` 只负责多轮 query plan、path/text/symbol 合流、rank、slice、evidence refs；不拥有底层文件遍历权威。
- `python_symbol_search` / AST 工具应作为 `symbol_search` 能力进入 codebase search 的候选源，专门服务定义、类、函数、引用定位；不能用纯文本 grep 冒充所有 symbol search。
- 搜索命中进入第三段时只允许作为 locator fact：`source_path + line + query + result_hash + recommended_window`。只有 read/verification 后的 evidence summary / coverage delta 才能成为第三段可确认事实。
- 搜索 negative result 也应结构化：说明 searched roots、filters、engine、是否 truncated / timeout。负结果不能在 incomplete 时被当成“项目里不存在”。

多层打分机制：

- path layer 只回答“路径/文件名像不像目标”：短语路径命中、compact identifier 命中、stem 精确命中、basename term 命中加分；泛词如 `context/service/tool` 权重很低；长 snake_case / identifier 查询必须满足更严格的 compact 或 basename 约束，防止 `same_fact_slot...` 退化成一堆泛 `fact` 文件。
- symbol layer 只回答“代码符号是否命中”：基于 Python 官方 `ast` 的 `python_symbol_search` 输出 class/function/method/import/variable；exact name / qualname 高分，substring 较低；命中以 `symbol_match` 进入 evidence，不靠正文 grep 冒充定义定位。
- text layer 只回答“内容是否共同承载这些概念”：先用 `rg` 做高召回 literal/regex；短语无命中时，多关键词查询进入文档级 AND 交叉召回，再用 BM25-lite、行内多词覆盖和最短关键词窗口定位排序。它适合概念检索，不替代 symbol layer。
- orchestrator layer 负责合流：`codebase_search` 汇总 path / symbol / text / glob / git history 候选，按 `symbol_match > path_match > definition > call_site > config > text > test/doc` 的工程证据优先级排序，并按用户意图提升 test/doc，未请求时降低 test/doc。
- 分数只表达证据强度，不能表达 edit authority；同分或分数饱和时用 tie-breaker 处理工程偏好，例如复合路径文件名命中优先、source path 优先、generated/cache 路径降权。

目标工具分层：

```text
WorkspaceSearchService
-> path_index / rg --files
-> text_search / rg
-> symbol_search / AST or language server
-> search_result_normalizer
-> candidate_read_window_builder
-> tool_result_envelope
-> codebase_search orchestrator
```

完成标准：

- active runtime 中 `search_files/search_text/glob_paths` 只有一个权威 service；另一层只做 adapter，不复制搜索算法。
- `search_text` 的 structured payload 总是包含 `matches`、`matched_paths`、`recommended_read_windows`、`searched_roots`、`truncated/incomplete`。
- `SearchTextTool` 和 `NativeSearchTextTool` 输出语义一致；上层不再依赖解析 `path:line:column:text` 文本。
- `CodebaseSearchProviders` 不再调用 `_parse_path_results()` / `_parse_text_hits()` 解析人类文本。
- 搜索默认不会把大段 content 注入上下文；大内容必须通过 read window 或显式 content mode。
- `roots=["."]`、默认 roots、省略项目根目录、fallback search、timeout / incomplete 都有模型可见且简短的修复提示。
- `codebase_search` 的 findings 能稳定给出 `file:start_line-end_line`、`evidence_kind`、`reason`、`recommended_read_window`。
- 搜索结果不会授权 edit/write；edit/write 仍要求 exact read evidence。

验证：

- 人工检查 `native_tools.py` 与 `tool_units/search_files_tool.py`：搜索算法不再双份维护。
- 人工检查一次路径关键词搜索、一次 glob 搜索、一次内容搜索、一次单文件 paths 搜索、一次无结果搜索的 tool envelope，确认 structured payload 完整。
- 人工检查 `codebase_search.providers`：不再解析文本行，改为消费结构化结果。
- 人工检查模型可见 prompt：说明搜索用于定位，read_file 用于 exact evidence；不出现开发说明式语言。
- 对“搜索命中但未读文件”的场景做物理段检查：第三段只出现 locator/candidate window，不出现可编辑证据。
- 对“搜索结果 truncated/incomplete”的场景做人工检查：最终回答不能把负结果说成确定不存在。

### Phase 4: Slot 模型命名和职责收敛

目标：

- 按阶段重新命名 slot 数据结构。
- 删除旧类名或旧导出。
- 固化每个阶段的输入输出。

涉及文件：

- `backend/prompt_library/models.py`
- `backend/prompt_library/wiring.py`
- `backend/prompt_library/__init__.py`
- `backend/prompt_composition/models.py`
- `backend/prompt_composition/assembly_plan.py`
- `backend/prompt_composition/runtime_slot_plan.py`
- `backend/prompt_composition/manifest.py`
- `backend/prompt_composition/__init__.py`

完成标准：

- 代码中不再出现多个职责不同但都叫 `*Slot` 的 active 类名。
- 每个新类 docstring 或字段命名能说明它所在阶段。
- runtime manifest 仍能追踪 material segment、load segment、manifest binding。

验证：

- `rg "PromptSetSlot|RuntimePromptWiringSlot|PromptAssemblySlot|PromptCompositionSlot|RuntimePromptSlot" backend` 不再命中 active code。
- `python -m py_compile` 覆盖 prompt_library 和 prompt_composition。

注意：

- 如果前端或存储 JSON 仍出现 `"slot"` 字段，它是数据字段，不等于类名问题；可保留字段名，避免无意义 schema churn。

### Phase 5: Environment Guidance 资源化

目标：

- 把三套环境 18 slot 正文从 Python 大字典迁入 Markdown 文件。
- Python loader 负责生成 `PromptResource`。
- 每个 prompt 文件可独立审阅、diff 和 hash。

涉及文件：

- `backend/prompt_library/environment_guidance_prompts.py`
- `backend/prompt_library/prompt_assets/environment_guidance/**`
- `backend/prompt_library/registry.py`

完成标准：

- `environment_guidance_prompts.py` 不再包含大段正文。
- loader 检查每个环境 18 slot 完整性。
- 生成的 prompt id、title、owner、version、allowed_environment_refs 与现有保持一致，除非计划明确调整。
- content hash 可以直接对文件正文计算。

验证：

- `rg "_PROMPTS_BY_ENVIRONMENT_AND_SLOT" backend/prompt_library` 不再命中 active code。
- `python -m py_compile backend/prompt_library/environment_guidance_prompts.py`。
- 人工抽查 coding/office/general 各至少一个 slot，确认正文仍是写给 agent 的可执行提示。

### Phase 6: Prompt 内容审计和 Manifest 版本链

目标：

- 为 `PromptResource` 增加内容 hash。
- 在 wiring、assembly、composition manifest 中记录 prompt source 审计信息。
- 人工 `version` 降级为可读标签，真实运行审计以 content hash 为准。

涉及文件：

- `backend/prompt_library/models.py`
- `backend/prompt_library/descriptor_resolver.py`
- `backend/prompt_library/assembly.py`
- `backend/prompt_composition/source_bundle.py`
- `backend/prompt_composition/manifest.py`
- `backend/prompt_composition/renderer.py`
- `backend/harness/runtime/compiler.py`

Manifest 必须能回答：

```text
本次 invocation 挂载了哪些 prompt?
每个 prompt 来自哪个 owner?
是哪个 PromptSet/WiringPlan 选择的?
人工 version 是什么?
content_hash 是什么?
最终进入 provider message 的 hash 是否一致?
```

完成标准：

- prompt section fingerprint 包含 `prompt_ref/source_ref/version/content_hash/owner/scope`。
- render mismatch diagnostics 能关联回 prompt source。
- 同一 prompt 内容变更后，即使人工 version 未更新，hash 也会变化。

验证：

- 编译一次 `single_agent_turn` packet，人工检查 manifest 中 prompt audit 字段完整。
- 编译一次 `task_execution` packet，确认 task prompt contract 与 resource prompt hash 均可区分。
- `python -m py_compile` 覆盖相关文件。

### Phase 7: Compiler 与旧链路清理

目标：

- 删除 compiler 中残留的 prompt ref 选择、旧 mount 主权威、临时 sanitizer、旧诊断旁路。
- 确保 compiler 只协调，不重新决定 prompt。

涉及文件：

- `backend/harness/runtime/compiler.py`
- `backend/harness/runtime/environment_prompt_controller.py`
- `backend/harness/runtime/context_message_producers.py`
- `backend/harness/runtime/agent_visible_projection/**`
- `backend/prompt_composition/runtime_fragments.py`

完成标准：

- compiler 不再手工拼 agent/environment/personality prompt refs。
- compiler 不再做 agent-visible 语义字段清洗。
- `PromptMountPlan` 若仍存在，只能作为纯输入事实或旧诊断 DTO，不能拥有最终 prompt selection authority。
- `runtime_fragments.py` 只渲染已经投影好的 payload，不替换业务语义。

验证：

- `rg "environment_guidance_prompt_defaults|_agent_visible_runtime_projection|PromptMountPlan" backend/harness/runtime backend/prompt_composition` 检查旧主权威是否退出。
- 编译三条主入口：`single_agent_turn`、`task_execution`、`tool_observation_followup`。
- 人工检查 model-visible prompt 不出现内部 `turn_id`、`runtime_context`、`authority`、`contract_ref`，除项目指令原文场景外。

## 6. 固定切换规则

### 6.1 不允许长期兼容双链路

每个阶段只能保留短过渡 wrapper，并必须满足：

- wrapper 不拥有决策权。
- wrapper diagnostics 标注迁移来源。
- wrapper 有明确删除阶段。
- wrapper 不向模型正文投影。

### 6.2 旧字段迁移规则

旧 JSON 读取：

- 可在 load 时转换旧字段到新结构。
- 转换后写回新结构。
- 不再同时写旧字段和新字段。

旧代码引用：

- active code 不允许继续读取旧字段。
- 旧字段只允许存在于 migration 函数、历史文档或一次性导入工具中。

### 6.3 Prompt 正文迁移规则

迁移正文到 Markdown 文件时：

- 不改写提示词语义。
- 只做必要的首尾空白规范化。
- 不把开发说明写入 prompt。
- 不合并不同 slot。
- 不降低 18 slot 覆盖。

### 6.4 Context policy 迁移规则

迁移到 `context_system` 时：

- 先移动 declaration 和 pure policy。
- 再改 import。
- 最后清理 runtime 原文件。
- 不能在 composition 里重新实现 section/cache 推断。

## 7. 文件级执行清单

新增：

```text
backend/prompt_library/prompt_set_resolver.py
backend/context_system/segments/__init__.py
backend/context_system/segments/declarations.py
backend/context_system/segments/policy.py
backend/context_system/segments/metadata.py
backend/prompt_library/prompt_assets/environment_guidance/coding/*.md
backend/prompt_library/prompt_assets/environment_guidance/office/*.md
backend/prompt_library/prompt_assets/environment_guidance/general/*.md
backend/prompt_library/resource_audit.py
backend/capability_system/tools/workspace_search_service.py
backend/capability_system/tools/search_result_models.py
```

重点修改：

```text
backend/prompt_library/models.py
backend/prompt_library/registry.py
backend/prompt_library/wiring.py
backend/prompt_library/descriptor_resolver.py
backend/prompt_library/assembly.py
backend/prompt_library/environment_guidance_prompts.py
backend/prompt_library/__init__.py
backend/prompt_composition/models.py
backend/prompt_composition/slot_policy.py
backend/prompt_composition/assembly_plan.py
backend/prompt_composition/runtime_slot_plan.py
backend/prompt_composition/source_bundle.py
backend/prompt_composition/manifest.py
backend/prompt_composition/renderer.py
backend/prompt_composition/__init__.py
backend/runtime/context_management/context_segment_registry.py
backend/runtime/context_management/context_segment_policy.py
backend/runtime/context_management/context_candidates.py
backend/runtime/context_management/context_candidate_gateway.py
backend/runtime/context_management/context_pipeline.py
backend/runtime/context_management/physical_context_assembler.py
backend/runtime/tool_runtime/native_tools.py
backend/runtime/shared/file_observation_policy.py
backend/runtime/tool_runtime/tool_result_envelope.py
backend/capability_system/tools/tool_units/search_files_tool.py
backend/capability_system/tools/tool_units/file_system_tools.py
backend/capability_system/tools/tool_units/python_ast_tools.py
backend/capability_system/tools/native_tool_catalog.py
backend/capability_system/tools/registries/TOOLS_REGISTRY.json
backend/capability_system/capabilities/codebase_search/*
backend/harness/runtime/compiler.py
backend/harness/runtime/environment_prompt_controller.py
backend/harness/runtime/context_message_producers.py
backend/harness/runtime/dynamic_context/*
backend/harness/runtime/agent_visible_projection/*
```

删除或降权候选：

```text
backend/prompt_library/wiring.py::_collect_prompt_set
PromptResource 顶层 workflow/task/graph/node/stage/phase/step 字段
PromptMountPlan 的最终 prompt 选择权
prompt_composition.runtime_fragments 中的业务语义 sanitizer
runtime.context_management.context_segment_policy 作为 composition 依赖入口
DYNAMIC_TAIL 中 task/evidence/recent-work facts 的 never_replay 主线身份
dynamic_projection / volatile_task_state 等宽泛动态桶
search_files/search_text/glob_paths 的双份搜索算法实现
codebase_search.providers 中解析人类可读搜索文本的 `_parse_path_results` / `_parse_text_hits` 主线依赖
```

## 8. 验证策略

遵守项目规则：不新增回归测试文件，不用 mock、硬编码、降低断言、跳过测试制造通过。

验证方式：

1. 静态阅读调用链，确认每阶段唯一入口。
2. `rg` 搜旧字段、旧类名、旧 import、旧函数名。
3. `python -m py_compile` 覆盖新增和修改 Python 文件。
4. 真实编译三条 runtime packet：
   - `single_agent_turn`
   - `task_execution`
   - `tool_observation_followup`
5. 人工检查 manifest：
   - prompt refs 完整。
   - owner/scope/version/content_hash 完整。
   - wiring selection reason 可追踪。
   - render hash 和 prompt source 可关联。
6. 人工检查 physical context diagnostics：
   - task/evidence/recent-work facts 出现在 `current_turn_tail`。
   - lease/recovery/action contract/exact injection 出现在 `never_replay_tail`。
   - 第三段不被计入本轮 expected cache read。
   - provider 失败不会晋升第三段 current append。
7. 人工检查搜索工具输出：
   - `search_files/search_text/glob_paths` 都有结构化 payload、搜索边界、truncated/incomplete 标记。
   - `search_text` 有 `recommended_read_windows`，且搜索片段不被标记为 exact editable evidence。
   - `codebase_search` findings 来自结构化搜索结果和 read/slice 证据，不再解析人类文本输出。
   - negative finding 必须区分 complete no-match 与 timeout/truncated/incomplete。
8. 人工检查模型可见正文：
   - 不出现内部 runtime 控制字段。
   - 不出现开发说明式 prompt。
   - 环境 guidance 仍然描述身份、职责、边界、判断标准、失败处理。
9. 如触及前后端启动链路，必须按固定端口真实启动：
   - 前端：`http://127.0.0.1:3000`
   - 后端：`http://127.0.0.1:8003`

## 9. 风险与控制

### 风险 1：为减少模型数量而破坏 traceability

控制：

- Phase 4 先改名，再评估合并。
- 只有生命周期、字段和诊断完全重合的结构才允许合并。
- 不以“少一个类”为目标牺牲 manifest 可追踪性。

### 风险 2：Context policy 迁移时产生双权威

控制：

- `context_system.segments` 是唯一声明和 pure policy owner。
- runtime 原 `context_segment_*` / replay contract 文件已删除，不保留 re-export 兼容入口。
- composition 不允许实现自己的 section/cache fallback。

### 风险 3：PromptResource 字段迁移破坏旧存储

控制：

- load migration 读取旧字段并转为 `origin`。
- 写回只写新结构。
- active code 不继续读取旧字段。

### 风险 4：环境 prompt 资源化时误改正文

控制：

- 第一轮只迁移文件，不重写内容。
- 每个文件独立 hash。
- 人工抽查三环境关键 slot。

### 风险 5：Prompt version 审计变成形式字段

控制：

- runtime 审计以 `content_hash` 为准。
- `version` 只作为 human-readable label。
- manifest 必须记录 hash，render mismatch 必须能回溯 source prompt。

### 风险 6：旧 PromptMountPlan 或 compiler 旁路复活

控制：

- Phase 7 明确删除或降权。
- compiler 只协调，不拥有 prompt selection。
- `rg` 检查旧主权威名称和旧选择字段。

### 风险 7：把 current control 错误收缩成 current facts

控制：

- Phase 3A 必须按“事实可延续 / 控制本轮有效”裁决，不按 kind 名称粗暴迁移。
- 第三段 current facts 必须有 source identity、content hash 和 provider success 后的确认规则。
- Phase 3B 必须把第三段视为 fact delta candidate lane，而不是 memory append queue；小幅刷新不能生成新的模型可见记忆。
- 同一 fact slot 的 replacement 必须声明 `supersedes`，并在 replay / compact 时折叠旧版本。
- 第四段 current control 必须保持 `never_commit`，不能因为内容稳定就自动封存。
- exact read/editor text 只有作为 content-versioned current evidence fact 才能进入第三段，必须带稳定 path/range/event fact slot、content hash、provider-success commit 与 supersession 策略；skill body、reasoning projection 仍不作为事实记忆进入第三段。

### 风险 8：把搜索工具升级成新的上下文污染源

控制：

- 搜索结果默认只产生 locator fact 和 candidate read window，不直接产生 edit authority。
- `search_text` content mode 必须分页、限制行宽，并明确 truncated/incomplete 状态。
- `codebase_search` 不能用搜索 snippet 直接下最终代码结论；行级判断和编辑前必须读 exact window。
- negative finding 只有在完整搜索完成时才允许表达为确定没有；timeout、fallback、truncated 只能表达为搜索不充分。
- 搜索工具双实现必须收敛到共享 service；adapter 不允许各自复制排序、过滤、fallback 和格式化规则。

## 10. 不做事项

- 不引入 `v2` 命名。
- 不保留新旧 PromptResource 字段双写。
- 不保留新旧 PromptSet 解析双入口。
- 不把 context policy 复制到 composition。
- 不削弱 18 个 environment guidance slot。
- 不把 prompt 内容改成开发说明。
- 不把搜索 snippet 当作 exact read evidence 或 edit authority。
- 不把 `codebase_search` 做成模糊语义搜索替代确定性 `search_text/read_file` 链路。
- 不新增回归测试文件。
- 不用 mock、硬编码、跳过测试或降低断言制造通过。
- 不随机切换项目固定端口。

## 11. 推荐实施顺序

推荐顺序：

```text
Phase 1 -> Phase 3 -> Phase 3A -> Phase 3B -> Phase 3C -> Phase 6 -> Phase 2 -> Phase 5 -> Phase 4 -> Phase 7
```

理由：

- Phase 1 先解决继承环路和 wiring 入口问题，风险小、收益直接。
- Phase 3 提前拆掉 composition 对 runtime 的反向依赖，是后续结构清理的基础。
- Phase 3A 在共享 policy 稳定后收缩 dynamic tail，避免把错误 section 继续带进 prompt/content 审计。
- Phase 3B 紧接 Phase 3A，防止迁入第三段的事实被当作每轮重复记忆写入。
- Phase 3C 紧接记忆 / evidence 规则之后做搜索工具升级，因为搜索结果必须先按 locator fact 和 candidate window 接入第三段，而不能绕开 evidence 规则。
- Phase 6 建立 hash 审计后，再迁移正文和模型字段更安全。
- Phase 2 和 Phase 5 是结构清理，适合在审计链稳定后做。
- Phase 4 改名影响面大，应在数据和策略边界稳定后执行。
- Phase 7 最后清旧链路，避免实施中间态误删仍在使用的路径。

## 12. 执行后裁决回执

本轮实施后的裁决状态：

1. `PromptResource` 顶层 task graph 字段已一次性迁入 `origin`，写出不再双写旧字段。
2. `context_segment_policy.py` / `context_segment_registry.py` / `provider_message_replay_contract.py` 的 runtime 旧入口已删除；active 代码直接消费 `context_system.segments`，不保留 re-export wrapper。
3. Slot 类名已按阶段职责重命名，active backend 不再出现旧 Slot 类名。
4. 环境 guidance 已文件化，第一阶段只迁移存储，不重写正文。
5. prompt `version` 已降级为 human-readable label，真实审计版本以 `content_hash` / `version_label` / manifest source audit 为准。
6. `PromptMountPlan` 的旧选择权威已删除，保留的是环境 prompt inventory / diagnostics 输入事实。
7. Phase 3A 的 dynamic tail 收缩表已按严格控制原则锁定：task/evidence/recent-work facts 进第三段；`read_evidence_injection` 与 `current_editor_evidence_delta` 也进第三段 current evidence fact；lease/recovery/action/reasoning/skill/request-local runtime 路标继续留第四段或 side-channel。
8. Phase 3B 已锁定为第三段的记忆晋升规则：按 fact slot 归一，same slot + same content hash 为 no-op，meaningful delta/replacement/new fact 才进入第三段并在 provider success 后确认。
9. Phase 3C 已锁定为搜索工具升级方向：共享 `WorkspaceSearchService` 为路径关键词、文本和 glob 搜索算法权威，`SearchFilesTool` / `SearchTextTool` / `GlobPathsTool` / native workspace search / `codebase_search` 只做 adapter 或 orchestrator，不再复制搜索算法或解析人类可读搜索文本。
