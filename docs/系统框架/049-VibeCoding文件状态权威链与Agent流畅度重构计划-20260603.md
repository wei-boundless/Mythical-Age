# Vibe Coding 文件状态权威链与 Agent 流畅度重构计划

日期：2026-06-03

状态：计划书，待用户审阅确认后实施。

## 0. 结论先行

本项目 vibe coding 不流畅的根因不是“文件夹没有整理好”，而是文件、工具结果、产物、任务状态、上下文投影没有形成一条稳定的运行时权威链。

当前项目已经有 `file_management`、`artifact_system`、`state_index`、`ToolObservationLedger`、`DynamicContextProjection`、`ToolResultStore` 等能力，但它们还没有被收敛成每轮模型调用前的单一事实入口。结果是 agent 在长任务中反复搜索、重复读取、依赖 volatile observations 回忆状态，prompt cache 前缀不稳定，产物引用也容易在多个投影层重复提取。

目标不是给 prompt 加更多提醒，而是把成熟 coding agent 的不变量落成结构：

```text
ModelTurnDecision
-> ActionAdmission
-> ToolResultEnvelope
-> FileStateAuthority
-> ArtifactAuthority
-> TaskRuntimeState
-> StableDynamicContext
-> Next ModelTurnDecision
```

这条链条必须成为后续所有 read/search/edit/write/shell/artifact/verification 行为的统一运行路径。任何旧的旁路、重复抽取、临时兜底、只靠 prompt 警告的逻辑都应删除或收敛。

## 1. 成熟 Agent 对照结论

### 1.1 Codex 可借鉴的不变量

本地参考源码：

```text
D:\AI应用\openai-codex\codex-rs\core\src\context_manager\history.rs
D:\AI应用\openai-codex\codex-rs\core\src\context_manager\normalize.rs
D:\AI应用\openai-codex\codex-rs\core\src\tools\router.rs
```

Codex 的关键不是“会读文件”，而是：

- `ContextManager.for_prompt()` 是送模型前的统一入口。
- history normalize 保证 tool call 和 tool output 成对；缺失 output 补 `aborted`，孤儿 output 删除。
- tool router 从 turn context 编译 model-visible specs 和 dispatch registry，模型决定调用，系统负责权限和执行。
- tool invocation 绑定 session、turn、call id、payload、cancellation token，不依赖某个长期任务对象才有工具能力。

本项目必须借鉴的工程不变量：

- 模型调用前必须有统一 protocol sanitation。
- accepted action 必须最终产生 observation、error、canceled 或 aborted output。
- 工具调用的 request id / call id 是恢复、去重、替换和投影的幂等键。
- tool router / control plane 不做语义任务判断，只做能力暴露、权限、执行和结果记录。

### 1.2 Claude Code 可借鉴的不变量

本地参考源码：

```text
D:\AI应用\claude-code-nb-main\utils\fileStateCache.ts
D:\AI应用\claude-code-nb-main\utils\toolResultStorage.ts
D:\AI应用\claude-code-nb-main\utils\conversationRecovery.ts
D:\AI应用\claude-code-nb-main\utils\collapseReadSearch.ts
```

Claude Code 的关键不是“目录里有 CLAUDE.md”，而是：

- 文件状态是 runtime 事实，不是提示词说明。
- `FileStateCache` 记录路径归一化后的文件内容、timestamp、读取窗口、partial view，并有 LRU 和大小限制。
- 大工具结果按 tool use id 持久化，后续投影复用稳定 preview。
- resume 会过滤 unresolved tool use、孤儿 thinking、空 assistant message，只有结构合法时才继续。
- read/search 的 UI 折叠和 API prompt 压缩是两件事，不能用 UI 折叠代替模型上下文治理。
- subagent 是隔离上下文的新 invocation，父线程只接收摘要和 refs，不能被子线程原始日志污染。

本项目必须借鉴的工程不变量：

- 文件读写事实要进入 task-local file state。
- 重复读取未变化文件应返回稳定事实或 short stub，而不是再次塞入全文。
- 大 observation 必须稳定外部化，不能每轮生成不同 preview。
- 子 agent / fork 必须复制必要状态，但不能共享会污染父线程的 volatile 记录。

## 2. 当前项目问题链

### 2.1 已有能力

当前项目已经具备下列基础：

- `backend/file_management/*`：repository、access rule、logical path、operation receipt、commit gate。
- `backend/artifact_system/*`：artifact repository、materialization、governance。
- `backend/runtime/memory/state_index.py`：task run、turn run、agent run、project runtime status、session live view。
- `backend/runtime/memory/tool_observation_ledger.py`：工具观察分类、observed paths、matched paths、artifact refs、read file content range guidance。
- `backend/runtime/tool_runtime/tool_result_envelope.py`：现有 `ToolResultEnvelope`，已经是工具结果结构化封装主类型。
- `backend/runtime_objects/tool_result_storage.py`：大工具结果持久化和 preview replacement。
- `backend/harness/runtime/dynamic_context/*`：latest observations、task state、file_state 投影雏形、replacement store。
- `backend/runtime/tool_runtime/native_tools.py`：read_file 已进入 `start_line` / `line_count` 行级契约。
- `backend/harness/loop/task_executor.py`：duplicate tool call guard、artifact publish/resolve、task lifecycle closeout。

这些能力不是问题，问题在于它们的权威边界没有收敛。

### 2.2 命名与主类型约束

当前代码已经存在 `ToolResultEnvelope`，因此本计划不新增平行的 `ToolProtocolEnvelope` 类型。后续所有“工具协议 envelope”工作都必须落到：

- 扩展和规范现有 `ToolResultEnvelope`。
- 规范 `ToolObservation.result_envelope` 的写入形态。
- 让 `ToolControlPlane`、`ToolExecutor`、`native_tools`、subagent control 都输出同一个 `ToolResultEnvelope` contract。

如果另建 `ToolProtocolEnvelope`，会形成新的双主链，违反本计划的权威收敛目标。

### 2.3 当前断点

#### 断点 A：文件管理不是文件操作主入口

`file_management` 有成熟的 repository 和 receipt 模型，但实际 coding agent 工具链的 read/search/write/edit 主要由 `native_tools`、`tool_executor`、`ToolObservationLedger` 和 dynamic context 投影串联。`FileGateway` 更像某些任务环境的能力模块，不是所有文件操作的权威事实入口。

后果：

- 文件权限、文件状态、文件 receipt、产物 refs 分散。
- agent 读写后，下一轮模型不一定看到稳定的“已读/已改/需重读”事实。
- 写入和 artifact materialization 可能在多个层自己拼 refs。

#### 断点 B：ToolObservationLedger 仍偏观察账本，不是 FileStateAuthority

`ToolObservationLedger` 能记录 read/search/write 事实，但 file state 还没有成为强模型可见状态。

缺口：

- 没有按 task_run 聚合文件读取覆盖范围。
- 没有基于 content hash / mtime 的 unchanged 判断。
- 没有 write/edit 后让旧 read range 失效或标记 stale。
- 没有把 search matches 与 file read coverage 关联成“下一步应读哪些文件/哪些行”的事实。

#### 断点 C：tool protocol sanitation 不够集中

Codex 把 call/output 成对 normalize 做成 `for_prompt()` 的入口不变量。本项目现在有 `provider_tool_call_adapter`、`compiler`、`task_executor`、`tool_control_plane` 等多处处理 tool call、tool result、observation、duplicate、aborted。

后果：

- 半截 action、aborted、orphan output、resume continuation 的规则容易分散。
- 不同入口可能生成不同形态的 observation。
- prompt 投影层还要补救上游协议不干净的问题。

#### 断点 D：artifact refs 多头抽取

`artifact_refs` 在以下文件均有抽取或去重逻辑：

```text
backend/harness/loop/task_executor.py
backend/harness/runtime/single_agent_host.py
backend/harness/runtime/monitoring/projector.py
backend/harness/runtime/dynamic_context/tool_result_projector.py
backend/harness/runtime/dynamic_context/observation_projector.py
```

后果：

- 产物权威不唯一。
- 前端监控、最终回答、下一轮上下文可能看到不同 refs。
- artifact 是否真实存在、是否发布、是否满足合同，需要多个层重复检查。

#### 断点 E：dynamic context 仍承载过多 volatile facts

`ToolResultStore` 和 `ReplacementStore` 已经存在，但如果 task_state 不够强，模型仍会依赖 `latest_observations` 回忆文件读写和产物状态。

后果：

- latest observations 越堆越大。
- prompt cache 前缀不稳定。
- 模型反复读同一批文件，因为“已读过什么”的事实不够短、不够稳定、不够权威。

### 2.4 本计划不纳入图调度改造

图系统是固定入口，本计划不改变 graph 调度、graph work order、graph loop 或 graph node 执行语义。涉及 graph 的地方只保留一个边界要求：如果固定入口已经产出 artifact refs，ArtifactAuthority 需要能读取和展示这些 refs，但不接管图调度。

## 3. 目标权威链

目标链条必须固定为：

```text
User Input
-> Runtime Assembly
-> ModelTurnDecision
-> ActionAdmission
-> ToolControlPlane
-> ToolResultEnvelope
-> ToolObservationLedger
-> FileStateAuthority
-> ArtifactAuthority
-> TaskRuntimeState
-> StableDynamicContext
-> Model Next Turn
-> OutputBoundary
```

### 3.1 Runtime Assembly

职责：

- 汇总当前 session、task_run、permission、tool specs、file scope、artifact scope、memory view。
- 不做语义任务判断。
- 不根据关键词选择任务模式。
- 输出本轮 invocation packet。

输入：

- 用户消息。
- session active turn。
- task_run / agent_run / turn_run。
- file state。
- artifact state。
- permission snapshot。
- context budget policy。

输出：

- model-visible runtime packet。
- prompt manifest。
- stable context refs。

禁止：

- 直接从 old observations 拼接长期事实。
- 绕过 FileStateAuthority 或 ArtifactAuthority。

### 3.2 ModelTurnDecision

职责：

- 模型决定直接回答、读文件、搜索、编辑、执行 shell、请求任务、请求用户、验证或收尾。

禁止：

- 系统根据关键词替模型决定要读哪个文件、是否开 TaskRun、是否进入专业模式。

### 3.3 ActionAdmission

职责：

- 校验 action type。
- 校验 tool 是否在本轮 runtime 暴露。
- 校验权限、sandbox、side effect policy。
- 给 accepted action 分配稳定 action id / request id。

输出：

- accepted action request。
- denied / blocked observation。
- permission request。

禁止：

- 重写用户意图。
- 把弱信号升级成任务语义裁决。

### 3.4 ToolControlPlane

职责：

- 统一执行工具。
- 统一 cancellation / aborted。
- 统一 tool result envelope。
- 统一 pre/post hooks。
- 统一 file/artifact policy 注入。

输出：

- `ToolResultEnvelope`。

禁止：

- TaskExecutor 私自成为工具权限终裁。
- native tool 直接绕过 envelope 写 observation。

### 3.5 ToolResultEnvelope Contract

这是新链条的核心协议对象。当前代码已有 `ToolResultEnvelope`，本计划要求扩展和规范它，而不是新增平行 envelope。每个工具调用必须形成如下事实：

```text
envelope_id
tool_call_id
action_request_id
caller_kind
caller_ref
tool_name
normalized_args
status: ok|error|denied|needs_approval|needs_contract|aborted|canceled
structured_result
text_preview
observed_paths
matched_paths
written_paths
artifact_refs
file_state_events
artifact_state_events
verification_events
operation_gate
execution_receipt
diagnostics
```

要求：

- accepted action 不能无结果消失。
- error / denied / needs_approval / aborted 也是结果。
- 大文本通过 replacement/persistence 外部化。
- envelope 是后续 ledger、state、artifact 的唯一输入。
- `ToolObservation.result_envelope` 必须保存规范后的 envelope dict。
- `ToolResultEnvelope.envelope_id` 不能作为幂等主键；幂等主键应是 `caller_ref + action_request_id + tool_call_id`。

### 3.6 FileStateAuthority

职责：

- 维护 task_run 级文件状态。
- 聚合 read/search/write/edit/stat/path_exists。
- 记录文件是否已读、读了哪些行、是否完整、是否 stale、是否 unchanged。
- 给下一轮模型提供短、稳定、可行动的 file state。

建议数据结构：

```text
TaskFileState
- task_run_id
- path
- normalized_path
- last_observation_ref
- last_tool_call_id
- content_hash
- mtime
- total_lines
- read_ranges: [{start_line, end_line, observation_ref, content_hash}]
- search_hits: [{query, line, preview, observation_ref}]
- write_events: [{operation, observation_ref, content_hash_before, content_hash_after}]
- status: unread|partial|complete|stale|missing|unchanged
- next_suggested_reads: [{start_line, line_count, reason}]
```

模型可见投影必须短：

```text
file_state:
- path
- status
- read_coverage
- total_lines
- last_changed_by
- next_suggested_read
- evidence_refs
```

禁止：

- 把全文塞入 file_state。
- 让 latest_observations 继续承担文件记忆。
- write/edit 后继续把旧 read state 当 current。

### 3.7 ArtifactAuthority

职责：

- 统一 artifact refs 的注册、校验、发布、可用性解析。
- 把工具、固定入口已产出的 graph artifact refs、contract materialization 产生的 artifact refs 收敛到同一个展示和解析出口；不改变 graph 调度。

建议数据结构：

```text
TaskArtifactState
- task_run_id
- artifact_id
- path
- logical_path
- repository_id
- kind
- source_tool_call_id
- source_observation_ref
- materialization_receipt_id
- exists
- verification_status
- lifecycle_status: candidate|published|required|verified|rejected
```

模型可见投影：

```text
artifact_state:
- required_artifacts
- produced_artifacts
- missing_required_artifacts
- verified_artifacts
- refs
```

禁止：

- 多个 projector 自己从 payload 里重复抽 artifact_refs。
- 最终回答引用未验证存在的 artifact。
- contract artifact 和 tool artifact 走两条不可汇合的链路。

### 3.8 TaskRuntimeState

职责：

- 统一 task lifecycle、file_state、artifact_state、verification_state、active work、recoverable errors。
- 作为 dynamic context 的稳定事实源。

要求：

- restore 只提供候选事实，不能覆盖当前 turn 的 action decision。
- task-local truth 不泄漏成 main-thread truth，除非通过 explicit summary/ref。
- long task resume 必须先读取 TaskRuntimeState，而不是扫旧 observation。

### 3.9 StableDynamicContext

职责：

- 编译模型可见上下文。
- 将稳定事实放在 task_state / execution_state。
- 将 volatile observation 控制为短窗口。
- 通过 replacement store 保护大工具结果 preview 字节稳定。

目标结构：

```text
stable_context:
- task_contract
- permission_snapshot
- tool_specs
- file_state
- artifact_state
- verification_state
- active_work
- compacted_work_history

volatile_context:
- latest_observations: last N only
- latest_user_steering
- latest_errors
```

禁止：

- 用 UI 折叠替代 API prompt 压缩。
- 每轮重新生成不同 preview。
- 为了“兼容旧链路”继续保留同一事实的多个投影出口。

## 4. 分阶段实施计划

### Phase 1：协议入口与现状测试锁定

目标：

- 先锁定真实行为，不急着大改。
- 明确当前 read/search/write/artifact/dynamic context 的断点。
- 建立失败测试，防止后续用 prompt 或 mock 糊过去。

修改文件：

```text
backend/tests/workspace_file_tools_regression.py
backend/tests/sandbox_tool_runtime_regression.py
backend/tests/tool_observation_ledger_regression.py
backend/tests/dynamic_prompt_context_projection_test.py
backend/tests/runtime_artifact_scope_regression.py
backend/tests/harness_runtime_facade_regression.py
```

新增测试点：

- read_file 使用 `start_line/line_count`，返回行号、`next_start_line`、`has_more`。
- repeated read 同一路径同一窗口不会再次进入大 observation。
- write/edit 后旧 read range 标记 stale。
- artifact_refs 只从 authority 投影一次。
- aborted/denied/error 工具调用都有结构化 observation。
- dynamic context 中 file_state 优先于 latest_observations。

完成标准：

- 测试能真实复现当前不流畅链路。
- 不允许删除失败用例。
- 不允许通过降低断言、mock 掉核心逻辑来制造通过。

### Phase 2：ToolResultEnvelope 统一化

目标：

- 所有工具结果先归一到统一 envelope，再进入 ledger/state/projection。
- 让 accepted action 必有结果，结果状态可为 ok/error/denied/needs_approval/aborted/canceled。
- 不新增平行 envelope 类型，统一扩展现有 `ToolResultEnvelope`。

修改文件：

```text
backend/runtime/tool_runtime/tool_result_envelope.py
backend/runtime/tool_runtime/tool_observation.py
backend/runtime/tool_runtime/tool_control_plane.py
backend/runtime/tool_runtime/tool_executor.py
backend/runtime/tool_runtime/native_tools.py
backend/runtime/tool_runtime/provider_tool_call_adapter.py
backend/harness/loop/task_executor.py
backend/harness/loop/single_agent_turn.py
```

设计要求：

- 扩展和规范现有 `ToolResultEnvelope` 数据模型。
- envelope 必须携带 `tool_call_id`、`action_request_id`、`normalized_args`。
- envelope 必须携带 `caller_kind`、`caller_ref`，与 `ToolInvocationRequest` 对齐。
- denied/error/aborted 不能只作为自然语言文本。
- duplicate guard 输出也必须是 envelope-compatible observation。
- single turn 和 task run 走同一种 tool result contract。
- `ToolObservationStatus` 增加或映射 `aborted`、`canceled`，不能把中断全部压成普通 error。

删除项：

- 删除只在局部 payload 里拼 observation 的临时分支。
- 删除没有 `ToolResultEnvelope` 的 artifact_refs 旁路抽取。

完成标准：

- 工具执行后统一通过 envelope 进入 observation ledger。
- resume / retry / duplicate 能按 tool_call_id / action_request_id 幂等。

### Phase 3：FileStateAuthority 落地

目标：

- 建立 task_run 级文件状态权威。
- 让模型每轮看到“读过什么、哪些 stale、下一步该读哪里”的短事实。

新增或修改文件：

```text
backend/runtime/memory/file_state_authority.py
backend/runtime/memory/tool_observation_ledger.py
backend/harness/runtime/dynamic_context/execution_state_projector.py
backend/harness/runtime/dynamic_context/task_state_projector.py
backend/harness/runtime/dynamic_context/manager.py
backend/runtime/shared/models.py
backend/runtime/memory/state_index.py
```

设计要求：

- 从 `ToolResultEnvelope` 派生 file_state_events。
- read_file 成功后记录 read range、total_lines、content_hash。
- search_text 成功后记录 matched paths 和 hit previews。
- write/edit/apply_patch 后标记相关文件旧 read ranges stale。
- stat/path_exists 更新 missing/exists。
- repeated unchanged read 返回稳定短结果，不能再次注入全文。

模型可见格式：

```text
file_state:
- path: backend/runtime/tool_runtime/native_tools.py
  status: partial
  read_coverage: 209:405
  total_lines: 1400
  next_suggested_read: 406:606
  evidence_refs: [...]
```

删除项：

- 删除依赖 latest_observations 推断 read coverage 的逻辑。
- 删除旧 offset/end_offset/next_offset 的模型可见主契约残留。

完成标准：

- 同一 task_run 下一轮模型无需翻旧 observation 即可知道文件读取状态。
- write/edit 后 file_state 明确 stale。
- 文件状态投影短、稳定、可测试。

### Phase 4：ArtifactAuthority 收敛

目标：

- artifact refs 只由一个权威层注册、校验、发布和投影。
- 工具产物和 final answer artifact 统一进入 TaskArtifactState。
- 图系统是固定入口，本阶段不改 graph 调度或 work order 执行语义；只允许读取固定入口已经产出的 graph artifact refs，并映射到 ArtifactAuthority 的展示/解析层。

新增或修改文件：

```text
backend/artifact_system/artifact_repository_service.py
backend/artifact_system/artifact_repository_store.py
backend/harness/runtime/artifact_scope.py
backend/harness/runtime/sandbox_execution_scope.py
backend/harness/loop/task_executor.py
backend/harness/runtime/single_agent_host.py
backend/harness/runtime/monitoring/projector.py
backend/harness/runtime/dynamic_context/tool_result_projector.py
backend/harness/runtime/dynamic_context/observation_projector.py
backend/harness/runtime/dynamic_context/task_state_projector.py
```

设计要求：

- 新增或收敛 `TaskArtifactState`。
- artifact refs 从 envelope 进入 authority。
- 固定入口 graph refs 只作为外部输入映射，不由 ArtifactAuthority 反向调度 graph。
- authority 负责 dedupe、exists check、materialization receipt、verification status。
- monitoring、single_agent_host、dynamic_context 只读取 authority 投影，不再各自扫描 event payload。

删除项：

- 删除多处 `_artifact_refs_from_payload` / `_dedupe_artifact_refs` 的重复主链逻辑。
- 删除未验证 artifact 直接进入最终回答的路径。

完成标准：

- 给定 task_run_id，可以从一个权威 API 得到全部 artifact refs 和状态。
- required artifact 缺失时 closeout 阻断。
- 已发布 artifact 可被前端、下一轮 context、最终回答一致引用。

### Phase 5：DynamicContext 稳定化与 Prompt Cache 闭环

目标：

- 把 file_state、artifact_state、verification_state 放入稳定 task_state。
- latest_observations 只保留近期动作，不再承载长期事实。
- 大工具结果 replacement 决策稳定复用。

修改文件：

```text
backend/harness/runtime/dynamic_context/manager.py
backend/harness/runtime/dynamic_context/replacement_store.py
backend/harness/runtime/dynamic_context/tool_result_projector.py
backend/harness/runtime/dynamic_context/observation_projector.py
backend/harness/runtime/dynamic_context/task_state_projector.py
backend/harness/runtime/context_budget_policy.py
backend/runtime_objects/tool_result_storage.py
backend/runtime/prompt_accounting/*
```

设计要求：

- stable section 包含 task_state.file_state / artifact_state。
- volatile observation 限制数量和字符预算。
- 同一 tool_call_id 的 replacement projection 必须字节稳定。
- prompt manifest 记录 stable/volatile 分段和 token 预算。
- prompt cache 保护以稳定事实投影为主，不靠隐藏 observation。

删除项：

- 删除无边界扩大 latest_observations 的逻辑。
- 删除每轮重新生成大 preview 的逻辑。

完成标准：

- 长任务多轮后 prompt 中稳定前缀不被 observation 增长破坏。
- 模型仍能看到必要事实，但不需要重复读文件。

### Phase 6：Tool Protocol Sanitation 与 Resume

目标：

- 学 Codex/Claude Code，把 tool protocol 合法性做成模型调用入口不变量。

新增或修改文件：

```text
backend/harness/runtime/protocol_sanitizer.py
backend/harness/runtime/compiler.py
backend/harness/runtime/invocation_packet.py
backend/harness/runtime/dynamic_context/history_projector.py
backend/harness/loop/task_executor.py
backend/runtime/tool_runtime/provider_tool_call_adapter.py
backend/runtime/memory/state_index.py
```

设计要求：

- 缺失 tool result 的 accepted action 生成 aborted observation。
- orphan tool result 不进入模型 prompt。
- interrupted turn 注入模型可见 continuation fact。
- resume 前清理 incomplete action context。
- tool_call_id/action_request_id 是恢复幂等键。

删除项：

- 删除各模块自行补 orphan/aborted 的散落逻辑。
- 删除恢复时凭自然语言 continuation 猜测任务状态的路径。

完成标准：

- 中断、恢复、取消、失败工具调用都能进入下一轮模型可见事实。
- 不会出现模型看到 tool call 但看不到 tool output 的非法上下文。

### Phase 7：FileManagement Gateway 主链路收敛

目标：

- 让 file_management 从“可用模块”升级为文件边界和 receipt 权威。

修改文件：

```text
backend/file_management/gateway.py
backend/file_management/access_table.py
backend/file_management/metadata_store.py
backend/runtime/tool_runtime/native_tools.py
backend/runtime/tool_runtime/tool_executor.py
backend/runtime/tool_runtime/tool_control_plane.py
backend/task_system/environments/*
backend/api/task_system.py
```

设计要求：

- read/search/write/edit 的 logical path 归一化统一走 file_management 规则。
- 写入、编辑、commit gate、review receipt 进入 FileOperationReceipt。
- sandbox / artifact / canonical repository 的边界由 repository spec 决定。
- 普通 workspace read 可以保持轻量，但仍要产生 file state event。

删除项：

- 删除 native_tools 内部重复路径安全判断中与 gateway 冲突的主逻辑。
- 删除以“兼容旧路径”为理由保留的双重 repository 决策。

完成标准：

- file access decision、file operation receipt、file state event 能按同一 logical path 对齐。
- 真实 workspace 写入、sandbox 写入、artifact 写入不再混淆。

### Phase 8：前端监控与用户可见流畅度

目标：

- 用户看到的进展和 agent 内部权威状态一致。
- 不再展示散乱 raw observation 作为主要进度。

修改文件：

```text
frontend/src/components/chat/PublicRunActivity.tsx
frontend/src/lib/runtime-monitor/controller.ts
frontend/src/lib/store/runtime.ts
frontend/src/lib/api.ts
backend/harness/runtime/progress_presenter.py
backend/harness/runtime/public_chat_timeline.py
backend/harness/runtime/monitoring/projector.py
backend/api/orchestration_harness.py
```

设计要求：

- 前端展示 file state 摘要：已读、已改、待验证。
- 前端展示 artifact state 摘要：候选、已发布、缺失、已验证。
- public timeline 不泄漏内部 task id / hidden reasoning。
- SSE 只展示权威状态更新，不从 raw logs 推断。

完成标准：

- 用户能看到 agent 为什么不重复读、接下来读哪里、产物在哪。
- 前端监控和最终回答引用同一 artifact authority。

## 5. 固定执行流

实施后主链必须固定为：

```text
1. 用户输入进入 QueryRuntime。
2. Runtime Assembly 读取 session/task/file/artifact 权威状态。
3. Compiler 生成 invocation packet。
4. Model 产生 action request。
5. Admission 校验 action。
6. ToolControlPlane 执行工具并产出 ToolResultEnvelope。
7. ToolObservationLedger 记录 observation。
8. FileStateAuthority 消费 file_state_events。
9. ArtifactAuthority 消费 artifact_refs / materialization receipts。
10. TaskRuntimeState 更新 task lifecycle / active work / verification。
11. DynamicContext 编译稳定 task_state 和短 latest_observations。
12. 下一轮 Model 基于稳定事实继续。
13. OutputBoundary 根据 artifact/verification/task state 收口。
```

不允许的执行流：

```text
tool result -> dynamic_context 直接扫 payload -> artifact_refs
tool result -> latest_observations 长期保存文件事实
write_file -> final answer 直接说已完成但没有 receipt/ref
resume -> old messages 直接回灌模型但未做 protocol sanitation
TaskExecutor -> 私自决定工具权限终裁
prompt -> 要求模型不要重复读，但 runtime 没有 file_state
```

## 6. 迁移与删除规则

### 6.1 Shadow 阶段

允许短期同时计算旧投影和新 authority，但：

- 新 authority 必须写入 diagnostics。
- 测试必须断言新旧一致。
- shadow 只允许用于验证，不允许作为长期兼容分支。

### 6.2 Cutover 阶段

满足以下条件后切换主链：

- file_state 覆盖 read/search/write/edit/path_exists。
- artifact_state 覆盖 tool artifact、final answer artifact，以及固定入口已产出的 graph artifact refs 展示映射。
- dynamic context 读取新 authority。
- monitoring 读取新 authority。
- 所有相关回归通过。

### 6.3 删除阶段

切换后删除：

- 多处重复 `_artifact_refs_from_payload` 主链逻辑。
- 旧 offset/read window 残留。
- latest_observations 推断长期文件状态的逻辑。
- 无 envelope 的工具观察旁路。
- 只为兼容旧行为保留的重复状态结构。

### 6.4 回滚规则

如果切换后出现严重问题：

- 可临时恢复旧 projector 读取路径。
- 不允许恢复旧 offset 契约。
- 不允许恢复无 envelope 工具结果。
- 不允许保留双主链超过一个修复周期。

## 7. 验证矩阵

### 7.1 后端单元与回归

必须覆盖：

```text
python -m pytest backend/tests/workspace_file_tools_regression.py -q
python -m pytest backend/tests/sandbox_tool_runtime_regression.py -q
python -m pytest backend/tests/file_gateway_tool_runtime_regression.py -q
python -m pytest backend/tests/runtime_tool_control_plane_regression.py -q
python -m pytest backend/tests/tool_observation_ledger_regression.py -q
python -m pytest backend/tests/dynamic_prompt_context_projection_test.py -q
python -m pytest backend/tests/dynamic_context_replacement_store_regression.py -q
python -m pytest backend/tests/runtime_artifact_scope_regression.py -q
python -m pytest backend/tests/artifact_repository_scope_regression.py -q
python -m pytest backend/tests/harness_runtime_facade_regression.py -q
python -m pytest backend/tests/runtime_monitor_projection_test.py -q
python -m pytest backend/tests/runtime_progress_presenter_regression.py -q
python -m pytest backend/tests/deepseek_prompt_cache_diagnostics_test.py -q
```

新增测试：

```text
backend/tests/file_state_authority_regression.py
backend/tests/artifact_authority_regression.py
backend/tests/tool_protocol_sanitizer_regression.py
backend/tests/vibe_coding_runtime_context_regression.py
```

### 7.2 集成验证

必须真实启动固定端口：

```text
前端：http://127.0.0.1:3000
后端：http://127.0.0.1:8003
API：http://127.0.0.1:8003/api
```

验证场景：

- 普通 coding 问题：agent 先搜索再读文件，下一轮不重复读已读窗口。
- 修改文件任务：读文件、编辑、运行测试、file_state stale/refresh 正确。
- 产物任务：生成 artifact，前端、final answer、下一轮 context 看到同一 ref。
- 中断恢复：中断后继续，模型看到 aborted/continuation fact。
- 长任务多轮：latest_observations 不膨胀，prompt cache diagnostics 稳定。

### 7.3 前端验证

必须检查：

- `PublicRunActivity` 不展示重复噪声。
- runtime monitor 与 task detail 的 artifact refs 一致。
- SSE 断线恢复后状态不串台。
- file state / artifact state 作为用户可理解进展展示。

## 8. 风险控制

### 风险 A：把 FileStateAuthority 做成另一个日志层

控制：

- file_state 只能保存短事实，不保存全文。
- 全文只通过 tool result replacement / artifact / file read 工具再访问。

### 风险 B：ArtifactAuthority 变成重复包装

控制：

- monitoring、dynamic_context、single_agent_host 必须删除重复 artifact 扫描主逻辑。
- artifact authority 是唯一主出口。

### 风险 C：过度迁移导致工具不可用

控制：

- 先 envelope shadow，再 file_state/artifact_state cutover。
- 每阶段都有测试和真实启动验证。

### 风险 D：为了兼容旧测试保留旧链路

控制：

- 旧测试如果验证旧结构，应更新为验证真实行为。
- 不允许降低断言。
- 不允许 mock 掉工具执行、文件写入、artifact existence。

### 风险 E：把开发说明写进 agent prompt

控制：

- prompt 只写给 agent 的角色、职责、边界、输入、输出和裁决标准。
- 不写“这是 runtime 节点”“根据任务图执行某节点”这类开发说明。

## 9. 文件级执行清单

### 核心工具协议

```text
backend/runtime/tool_runtime/tool_observation.py
backend/runtime/tool_runtime/tool_control_plane.py
backend/runtime/tool_runtime/tool_executor.py
backend/runtime/tool_runtime/native_tools.py
backend/runtime/tool_runtime/provider_tool_call_adapter.py
backend/harness/loop/task_executor.py
backend/harness/loop/single_agent_turn.py
```

### 文件状态权威

```text
backend/runtime/memory/file_state_authority.py
backend/runtime/memory/tool_observation_ledger.py
backend/runtime/memory/state_index.py
backend/runtime/shared/models.py
backend/harness/runtime/dynamic_context/execution_state_projector.py
backend/harness/runtime/dynamic_context/task_state_projector.py
backend/harness/runtime/dynamic_context/manager.py
```

### 产物权威

```text
backend/artifact_system/artifact_repository_service.py
backend/artifact_system/artifact_repository_store.py
backend/harness/runtime/artifact_scope.py
backend/harness/runtime/sandbox_execution_scope.py
backend/harness/runtime/single_agent_host.py
backend/harness/runtime/monitoring/projector.py
```

说明：graph 是固定入口，本计划不修改 `backend/harness/graph/work_order_executor.py` 的调度或执行语义；ArtifactAuthority 只读取固定入口已产生的 graph artifact refs 作为外部输入。

### 动态上下文与 cache

```text
backend/harness/runtime/dynamic_context/replacement_store.py
backend/harness/runtime/dynamic_context/tool_result_projector.py
backend/harness/runtime/dynamic_context/observation_projector.py
backend/harness/runtime/context_budget_policy.py
backend/runtime_objects/tool_result_storage.py
backend/runtime/prompt_accounting/*
```

### 文件管理主链

```text
backend/file_management/gateway.py
backend/file_management/access_table.py
backend/file_management/metadata_store.py
backend/file_management/default_profiles.py
backend/task_system/environments/*
```

### 前端与监控

```text
frontend/src/components/chat/PublicRunActivity.tsx
frontend/src/lib/runtime-monitor/controller.ts
frontend/src/lib/store/runtime.ts
frontend/src/lib/api.ts
backend/harness/runtime/progress_presenter.py
backend/harness/runtime/public_chat_timeline.py
backend/api/orchestration_harness.py
```

## 10. 最终验收标准

本计划完成后，vibe coding 应达到以下行为标准：

- agent 不再反复读取同一文件窗口。
- agent 能清楚知道哪些文件已读、哪些文件变更后需要重读。
- 产物生成后有统一 ref、存在性、验证状态和前端展示。
- 中断、失败、取消工具调用不会污染下一轮上下文。
- prompt cache 不被不断增长的 raw observations 破坏。
- task resume 不依赖扫描旧日志猜测状态。
- 前端用户看到的是清晰进展，不是内部事件噪声。
- 旧旁路和重复逻辑被删除，不以兼容为理由长期保留。

## 11. 实施前必须确认的问题

实施范围较大，触及 runtime、tool calling、state、artifact、dynamic context、前端监控。按项目规则，实施前需要用户确认：

1. 是否同意将 `FileStateAuthority` 和 `ArtifactAuthority` 作为新主链权威，而不是继续在现有 projector 中做局部补丁。
2. 是否同意切换后删除旧 artifact refs 多头抽取和旧 observation 推断文件状态逻辑。
3. 是否同意实施时按 Phase 1 到 Phase 8 一次性推进，不只停在某一个局部修复阶段。
