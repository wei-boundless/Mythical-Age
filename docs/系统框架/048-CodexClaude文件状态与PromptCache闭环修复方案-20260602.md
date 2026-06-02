# Codex/Claude Code 文件状态与 Prompt Cache 闭环修复方案

日期：2026-06-02

## 1. 问题定义

近期长任务出现两类重复故障：

- agent 反复读取、搜索同一批代码，任务推进慢，prompt token 消耗偏高。
- prompt cache 命中受 volatile observation 增长影响，长任务中缓存前缀不够稳定。

严格判断：这不是单纯模型智力不足。当前系统给 coding agent 的工具契约、文件状态和工具结果生命周期不成熟，导致模型必须在大量重复日志和不稳定观察里重新推断任务事实。

正确终态：

- 工具契约符合成熟 coding agent 的自然工作方式。
- 读文件、搜索、写文件、验证产生的事实进入任务状态，而不是只作为近期日志重复投喂。
- 大工具结果有稳定替换和持久化机制，后续轮次回传字节稳定，保护 prompt cache 前缀。
- 重复工具调用保护按语义识别，而不是只比较参数 JSON。
- 不靠关键词路由或 prompt 警告解决结构性问题。

## 2. 外部源码对照

### 2.1 Codex

参考源码：

- `D:\AI应用\openai-codex\codex-rs\core\src\context_manager\history.rs`
- `D:\AI应用\openai-codex\codex-rs\core\src\context_manager\normalize.rs`
- `D:\AI应用\openai-codex\codex-rs\core\src\compact.rs`
- `D:\AI应用\openai-codex\codex-rs\core\src\thread_rollout_truncation.rs`
- `D:\AI应用\openai-codex\codex-rs\core\src\tools\router.rs`
- `D:\AI应用\openai-codex\codex-rs\core\src\tools\parallel.rs`
- `D:\AI应用\openai-codex\codex-rs\core\src\context\turn_aborted.rs`

关键事实：

- `ContextManager.for_prompt()` 在送 API 前统一 normalize history。
- normalize 层保证 tool call 和 tool output 成对；缺失 output 会补 `aborted`，孤儿 output 会删除。
- 中断会写入模型可见的 `<turn_aborted>` 上下文，而不是只在 UI 或内部状态展示。
- Codex 的 tool router 是 registry、dispatch、permission、model-visible spec 暴露，不是关键词语义路由。模型仍然决定是否调用工具。
- 并发和取消由 tool runtime 管理；只读或可并发工具并行，非并发工具串行，取消返回明确 aborted tool output。

可借鉴的不变量：

- API history 入口必须有统一 normalize。
- 工具生命周期必须成对、可恢复、可中断。
- 中断和恢复状态必须成为模型可见事实。
- tool router 只做执行和权限边界，不替模型做语义决策。

### 2.2 Claude Code

参考源码：

- `D:\AI应用\claude-code-nb-main\utils\toolResultStorage.ts`
- `D:\AI应用\claude-code-nb-main\utils\fileStateCache.ts`
- `D:\AI应用\claude-code-nb-main\tools\FileReadTool\FileReadTool.ts`
- `D:\AI应用\claude-code-nb-main\utils\conversationRecovery.ts`
- `D:\AI应用\claude-code-nb-main\services\compact\microCompact.ts`
- `D:\AI应用\claude-code-nb-main\utils\collapseReadSearch.ts`

关键事实：

- `FileReadTool` 的 `offset` 是行号，`limit` 是行数；输出是带行号的文本。
- `FileStateCache` 记录 path、content、timestamp、offset、limit、partial view，并做路径归一化和 LRU 限制。
- 重复读取未变化文件时可以返回 `file_unchanged` stub，而不是重新塞全文。
- 大工具结果持久化到 session 文件，只给模型稳定 preview。
- 内容替换决策按 `tool_use_id` 冻结；同一工具结果后续轮次复用字节完全一致的 projection，以保护 prompt cache。
- resume 会过滤 unresolved tool use、孤儿 thinking、空 assistant 消息，并只在结构合法时注入 continuation。

可借鉴的不变量：

- 文件状态是 runtime 事实，不是 prompt 文案。
- read/search UI 折叠和 API prompt 压缩是两件事，不能混用。
- 大 observation 应该稳定外部化，不能每轮重新生成不同 preview。
- 子 agent 或 fork 要复制必要状态，不能污染父线程。

## 3. 当前项目断点

### 3.1 `read_file` 仍是字符偏移

当前文件：

- `backend/capability_system/tools/tool_units/read_file_tool.py`
- `backend/runtime/tool_runtime/native_tools.py`
- `backend/runtime/memory/tool_observation_ledger.py`
- `backend/harness/runtime/dynamic_context/tool_result_projector.py`
- `backend/harness/runtime/dynamic_context/task_state_projector.py`

问题：

- `read_file.offset` 语义是字符偏移，不符合 coding agent 的行级阅读习惯。
- prompt 虽然提醒 `offset/end_offset/next_offset`，但模型自然会把 offset 当行号，导致重复读错窗口。
- dynamic context 和测试仍以 `offset/end_offset/next_offset` 为主，旧契约已经渗透进状态投影。

目标：

- 主链路改为 `start_line` 和 `line_count`。
- 工具输出使用 `start_line/end_line/next_start_line/total_lines/returned_lines/has_more`。
- 返回文本带行号，便于模型引用和后续编辑定位。
- 字符 offset 字段从主契约删除，不再作为 prompt 可见语义。

### 3.2 `search_text.roots` 不能表达具体文件

当前文件：

- `backend/capability_system/tools/tool_units/search_files_tool.py`
- `backend/runtime/tool_runtime/native_tools.py`

问题：

- `roots` 表示目录根，但模型会把具体文件路径传入 roots。
- 没有 `paths` 字段表达“只在这些文件里搜”。
- 错误参数会产生失败或误搜，模型随后继续搜索，形成循环。

目标：

- `search_text` 增加 `paths` 字段。
- 当 paths 指向文件时，只在这些文件中搜索。
- 当 roots 传入具体文件时，runtime 不沉默失败，返回结构化修复提示，要求改用 paths。

### 3.3 重复工具调用保护是参数级，不是语义级

当前文件：

- `backend/harness/loop/task_executor.py`

问题：

- duplicate guard 主要比较 `tool_name + normalized args`。
- 只能拦截完全相同窗口，拦不住同一文件错误窗口、同一搜索意图坏参数、同一失败工具反复重试。

目标：

- 对 read_file 使用 path + line range + file fingerprint 做语义 key。
- 对 search_text 使用 query + roots + paths + glob 做语义 key。
- 对连续失败的同类工具参数，返回模型可见 correction observation。
- guard 不替模型决定任务目标，只给出事实和纠偏边界。

### 3.4 ToolObservationLedger 只有观察账本，没有文件状态账本

当前文件：

- `backend/runtime/memory/tool_observation_ledger.py`

已有能力：

- 能分类 read/write/verification。
- 能提取 observed_paths、matched_paths、artifact_refs。
- 能生成 read_file content_range guidance。

缺口：

- 没有聚合“文件 X 已读取哪些行、是否读完整、是否未变化”的强事实。
- 没有把 write/edit 后的文件变更和后续读取状态关联。
- 没有 `file_unchanged` 这种稳定结果类型。

目标：

- 新增文件状态投影能力，作为 ToolObservationLedger 的派生摘要。
- 文件状态包含 path、last_observation_ref、read_ranges、coverage、total_lines、content_hash、status。
- task_state 中显式展示 `file_state`，让 agent 不需要在日志里回忆读过什么。

### 3.5 Prompt cache 保护不完整

当前文件：

- `backend/runtime_objects/tool_result_storage.py`
- `backend/harness/runtime/dynamic_context/tool_result_projector.py`
- `backend/harness/runtime/context_budget_policy.py`

已有能力：

- `ToolResultStore` 能将大字段持久化成 preview。
- `ToolResultProjector` 已用 `ReplacementStore.get_or_put()` 做 projection 缓存。

缺口：

- `read_file` 本身没有未变化 stub，重复读取仍可能生成大文本。
- observation budget 仍给了过多 volatile 空间。
- task_state 没有足够强的文件事实，导致模型继续依赖 latest_observations。

目标：

- 稳定 preview 保留，但降低 volatile observation 膨胀。
- 把文件事实前移到 task_state；latest_observations 只保留近期少量动作。
- prompt cache 优化不靠隐藏旧记录，而靠稳定、短、事实化的投影。

## 4. 目标权力链

目标链路：

```text
ModelTurnDecision
-> ActionPermit
-> ToolRuntime
-> ToolResultEnvelope
-> ToolObservationLedger
-> FileStateProjection
-> DynamicContextProjection
-> Next ModelTurnDecision
```

职责边界：

- ModelTurnDecision：模型决定下一步动作或回答。
- ActionPermit：只做权限和可执行性，不重写用户意图。
- ToolRuntime：执行工具，输出结构化 envelope。
- ToolObservationLedger：记录工具事实，不做任务语义裁决。
- FileStateProjection：把文件读写事实聚合成模型可读状态。
- DynamicContextProjection：装配稳定事实和少量近期观察，保护 cache。

禁止事项：

- 禁止用关键词路由替模型决定工具。
- 禁止让 UI 折叠替代 API prompt 压缩。
- 禁止保留字符 offset 作为 read_file 主语义。
- 禁止把重复读文件问题只写成 prompt 警告。
- 禁止 observation preview 无限制扩张。

## 5. 实施计划

### Phase 1：文档与测试契约更新

目标：

- 将 read_file 主语义锁定为行级。
- 将 search_text 文件路径搜索锁定为 paths。
- 更新测试，删除旧字符 offset 断言。

文件：

- `backend/tests/workspace_file_tools_regression.py`
- `backend/tests/sandbox_tool_runtime_regression.py`
- `backend/tests/file_gateway_tool_runtime_regression.py`
- `backend/tests/tool_observation_ledger_regression.py`
- `backend/tests/dynamic_prompt_context_projection_test.py`
- `backend/tests/task_environment_registry_regression.py`

完成标准：

- 测试不再要求 `offset/end_offset/next_offset`。
- 测试明确要求 `start_line/end_line/next_start_line`。

### Phase 2：read_file 行级工具契约

目标：

- capability tool 和 native runtime tool 同步改为行级读取。
- 输出带行号。
- 结构化 payload 给出 line window。

文件：

- `backend/capability_system/tools/tool_units/read_file_tool.py`
- `backend/runtime/tool_runtime/native_tools.py`
- `backend/capability_system/tools/native_tool_catalog.py`

完成标准：

- `read_file(path)` 返回完整或默认窗口的带行号文本。
- `read_file(path, start_line=10, line_count=20)` 返回第 10 行起的 20 行。
- payload 包含 `start_line/end_line/next_start_line/total_lines/returned_lines/has_more`。
- schema 不再向模型暴露字符 offset。

### Phase 3：search_text paths 支持与结构化纠错

目标：

- `search_text` 支持 `paths`。
- roots 传文件时返回明确 repair instruction。
- native runtime 和 capability tool 行为一致。

文件：

- `backend/capability_system/tools/tool_units/search_files_tool.py`
- `backend/runtime/tool_runtime/native_tools.py`

完成标准：

- `search_text(query, paths=["backend/app.py"])` 只搜指定文件。
- `search_text(query, roots=["backend/app.py"])` 返回“roots 必须是目录，文件请放 paths”的结构化错误。

### Phase 4：文件状态投影与语义重复保护

目标：

- ToolObservationLedger 提供行级 content_range metadata。
- task executor 基于 tool observation records 派生 file_state。
- task executor duplicate guard 读取 tool call fingerprint 和 tool result metadata。
- 重复窗口、重复未变化读取、重复坏参数返回模型可见 correction observation。

文件：

- `backend/runtime/memory/tool_observation_ledger.py`
- `backend/harness/loop/task_executor.py`
- `backend/harness/runtime/dynamic_context/task_state_projector.py`

完成标准：

- task_state 中出现 `file_state`。
- 同文件同 line window 重复读取会被 guard 拦截。
- 同 search_text query + paths/roots/glob 重复失败会被 guard 拦截。

### Phase 5：Prompt cache 稳定性收敛

目标：

- 降低 volatile observation 预算。
- latest_observations 保留少量最近动作，文件事实进入 task_state。
- 保留现有 ReplacementStore/ToolResultStore，但确保文件读取不靠大文本重复投影。

文件：

- `backend/harness/runtime/context_budget_policy.py`
- `backend/harness/runtime/dynamic_context/tool_result_projector.py`
- `backend/harness/runtime/dynamic_context/observation_projector.py`

完成标准：

- 长任务中重复 read_file 不再反复注入全文。
- tool result projection 对同一 source_id 字节稳定。
- prompt cache 统计中 cached/input 比例应随多轮任务稳定提升。

## 6. 验证矩阵

静态/单元测试：

```powershell
python -m pytest backend/tests/workspace_file_tools_regression.py -q
python -m pytest backend/tests/sandbox_tool_runtime_regression.py -q
python -m pytest backend/tests/file_gateway_tool_runtime_regression.py -q
python -m pytest backend/tests/tool_observation_ledger_regression.py -q
python -m pytest backend/tests/tool_result_projection_regression.py -q
python -m pytest backend/tests/dynamic_prompt_context_projection_test.py -q
```

集成检查：

- 使用 `backend/scripts/inspect_runtime_prompt_packet.py` 检查 prompt packet。
- 使用真实长任务检查：
  - read_file 是否按行号调用。
  - task_state 是否显示已读文件状态。
  - latest_observations 是否没有重复全文。
  - token usage 中 prompt input 是否下降。
  - cached/input 比例是否随连续调用提升。

## 7. 复核

### 7.1 是否有遗漏

- 已覆盖工具契约、runtime tool、observation ledger、dynamic context、prompt cache budget、测试。
- 图像生成旁路不在本方案范围内，避免与用户指定的能力系统重修冲突。
- 权限系统不作为本方案主轴；工具权限仍由现有 ActionPermit/ToolControlPlane 负责。

### 7.2 是否有矛盾

- 不保留字符 offset 主语义，与“删除旧无用链路”一致。
- 保留 `ToolResultStore` 和 `ReplacementStore` 不是保留旧噪声，因为它们承担成熟 agent 所需的稳定替换职责。
- duplicate guard 不替模型做任务决策，只对已发生的工具事实做纠偏。
- file_state 是观察事实投影，不是新的语义路由层。

### 7.3 实施风险

- read_file 字段变更会影响旧测试和少量调用点，必须同步更新。
- 如果某些外部调用仍传 `offset`，应返回结构化错误，而不是隐式兼容。
- payload 字段迁移会影响 dynamic context projection，必须同阶段更新。

### 7.4 通过条件

本方案没有未决架构问题，可以进入实施。实施顺序必须按 Phase 1 到 Phase 5 推进，不能先改 prompt 文案绕过工具契约和文件状态问题。

## 8. 实施记录

实施日期：2026-06-02

已完成：

- `read_file` 主契约已从字符窗口切换为行窗口：`start_line`、`line_count`。
- native runtime 和 capability tool 均输出带行号文本，并在结构化 payload 中提供 `start_line`、`end_line`、`next_start_line`、`total_lines`、`returned_lines`、`content_sha256`。
- `search_text` 已新增 `paths`，并对把文件路径放进 `roots` 的调用返回明确修复提示。
- `ToolObservationLedger`、`ToolResultProjector`、`TaskStateProjector` 已迁移到行级 `content_range`。
- task execution projection 已新增 `file_state`，展示文件已读取行段、覆盖率、hash、最后 observation，并在写入/编辑后标记 `modified_after_read`。
- duplicate guard 已支持：
  - 同一只读成功调用重复时拦截。
  - 同一只读失败调用重复时拦截，并要求修改参数、换工具或报告阻塞。
- task execution prompt 已删除旧 `offset/end_offset/next_offset/limit` 指导，改为 `start_line/end_line/next_start_line/line_count`。
- context budget 已降低 volatile observation 权重和 tool result preview 上限，把文件事实前移到 `task_state.file_state`。

明确不做：

- 不兼容旧 `read_file(offset, limit)`。旧字段由 validator 返回修复提示，不静默映射到新字段。
- 不改图像生成旁路。
- 不把 UI 折叠当成 prompt cache 优化；本次只处理 API prompt 装配和工具事实投影。

验证结果：

```powershell
python -m py_compile backend\capability_system\tools\tool_units\read_file_tool.py backend\capability_system\tools\tool_units\search_files_tool.py backend\runtime\tool_runtime\native_tools.py backend\runtime\memory\tool_observation_ledger.py backend\harness\loop\task_executor.py backend\harness\runtime\dynamic_context\tool_result_projector.py backend\harness\runtime\dynamic_context\task_state_projector.py backend\harness\runtime\dynamic_context\execution_state_projector.py backend\harness\runtime\context_budget_policy.py
python -m pytest backend/tests/workspace_file_tools_regression.py backend/tests/sandbox_tool_runtime_regression.py backend/tests/file_gateway_tool_runtime_regression.py backend/tests/tool_observation_ledger_regression.py backend/tests/tool_result_projection_regression.py backend/tests/dynamic_prompt_context_projection_test.py backend/tests/task_environment_registry_regression.py -q
python -m pytest backend/tests/harness_runtime_facade_regression.py::test_single_agent_turn_read_only_tool_executes_through_control_plane_and_followup_answers backend/tests/harness_runtime_facade_regression.py::test_task_executor_guards_duplicate_read_only_tool_call_without_rerunning_tool -q
```

通过结果：

- 聚焦回归：`104 passed`
- 关键 harness 单测：`2 passed`

补充复核：

- 残留扫描未发现 `read_file` 主链路仍暴露旧 `offset/limit`。命中项仅包括：本方案的问题描述、事件日志自身的 event offset、权限系统的 `max_result_size_chars`、以及一个专门断言旧 `offset=0` 不被静默兼容的测试。
- `TOOLS_REGISTRY.json` 已复核：`search_text.optional_inputs` 为 `roots/paths/glob/max_results`，`read_file.optional_inputs` 为 `start_line/line_count`，`list_dir` 与 `web_search` 未误挂 `paths`。
- 完整 `backend/tests/harness_runtime_facade_regression.py -q` 当前结果为 `104 passed, 3 failed`。失败项是当前工作树中既有的权限门控、全局监控、active work 控制工具可见性问题：
  - `test_single_agent_turn_side_effect_tool_is_blocked_before_runtime_dispatch`
  - `test_global_live_monitor_groups_running_completed_and_failed_runs`
  - `test_single_agent_turn_does_not_control_active_work_without_native_action`
- 这 3 个失败不在本方案的 read/search/file_state/prompt-cache 改动链路内，不能作为本次方案回滚理由；应在对应权限/监控/active-work 改动中单独收口。

剩余风险：

- 当前工作树存在与本方案无关的权限、监控、active work 改动；全量 `harness_runtime_facade_regression.py` 仍有非本方案失败项，需要在对应改动中单独收口。
- `file_state` 目前是执行投影派生事实，还不是独立持久 file-state cache；它已满足本次 prompt 装配和重复阅读纠偏，但如果后续要做 Claude Code 式 `file_unchanged` stub，需要新增独立文件状态缓存。
