# Read File Chain Audit And Modification Plan

日期：2026-06-15

状态：实施前方案。本文只审查链路并给出修改方案，不改运行代码。

## 0. 结论先行

当前卡住和重复读的根因不是模型“不听话”，也不是单纯上下文窗口不够，而是本项目把 `read_file` 的代码证据同时接进了三条互相矛盾的链路：

```text
链路 A：read_file -> file_state_event -> FileStateAuthorityStore
链路 B：read_file -> ToolResultStore/content_replacements -> read_persisted_tool_result -> file_state_event
链路 C：provider_protocol replay -> 3K preview/rehydration note -> prompt rule -> 模型自行恢复或少读
```

这三条链路分别在不同层判断“这段代码是否已读过、是否还当前有效、是否可恢复、是否不该重复读”。结果是：

- observe 层的 `read_file` 返回了 `content_omitted` stub。
- record 层把这个 stub 记成 active read window。
- assemble 层把原始代码按通用工具输出预算压成 preview。
- retrieve 层的 `read_persisted_tool_result` 又试图把历史输出升级成当前文件证据。
- prompt 层继续提示模型“不要重复读，先恢复 omitted bytes”。

成熟 agent 的做法不是这样。Claude Code、OpenAI Codex、Pi coding-agent、opencode 的共同点是：

- search 只定位候选，不替代 read evidence。
- read 是代码证据观察，不走通用工具输出压缩主链。
- read 可以截断或窗口化，但必须有 read-specific continuation 或 exact artifact。
- repeated read stub 只在 earlier exact read 仍可见，或 exact artifact 可恢复时成立。
- edit 的最终许可来自当前文件守卫，不来自历史工具输出恢复器。

因此本项目目标必须改成唯一主链：

```text
read_file exact bytes
  -> ReadObservationArtifactStore
  -> FileStateAuthorityStore exact_artifact_ref
  -> context assembly 注入 exact evidence 或要求当前 read_file
  -> edit_file 执行当前磁盘与 old_text 守卫
```

必须删除的旧主链：

```text
read_file
  -> ToolResultStore content_replacements
  -> read_persisted_tool_result
  -> file_state_event rehydrate_omitted_read_file
```

注意：这里的删除不是在旧链路末端加拒绝分支，也不是保留两套链路互相兜底。旧链路要从生成、投影、提示、测试四个入口同时移除。

## 1. 审查范围

本次审查覆盖以下层级：

- 本地工具执行：`backend/runtime/tool_runtime/native_tools.py`
- 工具结果 envelope：`backend/runtime/tool_runtime/tool_result_envelope.py`
- 文件状态权威：`backend/runtime/memory/file_state_authority.py`
- 文件状态提交：`backend/runtime/memory/file_state_store.py`
- 通用工具输出存储：`backend/runtime_objects/tool_result_storage.py`
- 动态上下文投影：`backend/harness/runtime/dynamic_context/tool_result_projector.py`
- 任务状态投影：`backend/harness/runtime/dynamic_context/task_state_projector.py`
- provider protocol replay：`backend/harness/runtime/compiler.py`
- context budget：`backend/harness/runtime/context_budget_policy.py`
- bound task prompt：`backend/harness/runtime/bound_task_context.py`
- prompt library：`backend/prompt_library/rules.py`、`backend/prompt_library/tool_prompts.py`
- capability catalog：`backend/capability_system/tools/native_tool_catalog.py`、`backend/capability_system/tools/registries/TOOLS_REGISTRY.json`
- 回归测试：`backend/tests/read_file_authority_chain_regression.py`、`backend/tests/tool_result_projection_regression.py`、`backend/tests/dynamic_prompt_context_projection_test.py`

不在本阶段实施代码。根据项目规则，runtime、context assembly、tool calling、state、prompt 的结构性修改必须先完成方案审阅。

## 2. 成熟 Agent 对照结果

### 2.1 Claude Code

本地源码：`D:\AI应用\claude-code-nb-main`

关键证据：

- `tools/FileReadTool/FileReadTool.ts:340-342`：Read 工具 `maxResultSizeChars: Infinity`，明确不走通用 tool result 持久化。
- `tools/FileReadTool/prompt.ts:7-8`：重复读 stub 的前提是 earlier Read tool_result 仍在当前 conversation 中有效。
- `tools/FileReadTool/FileReadTool.ts:523-525`：代码注释说明 earlier Read tool_result still in context，因此重复输出完整内容浪费 token。
- `utils/toolResultStorage.ts:59-63`、`:816`：`Infinity` 是 hard opt-out，Read 不进入通用持久化。
- `services/compact/compact.ts:1399-1405`、`:1606-1608`：compact 后重新注入真实文件内容，不把 preserved tail 里的 dedup stub 当真实内容。
- `tools/FileEditTool/FileEditTool.ts:275-280`、`:442-454`、`:520-524`：edit 前要读，写入前检查当前文件状态，写入后更新 read state。

可借鉴标准：

- Read 是独立预算和独立状态，不是 generic tool output。
- Read stub 的合法前提是 exact read 仍可见或被 compact 后真实注入。
- edit guard 独立检查当前磁盘，不由 rehydration 工具授权。

本项目偏差：

- 本项目复制了“文件未变化可以省略”的形式，却没有保留 Claude 的前提：早先真实 read result 仍在 context，且 Read 不被 generic persistence 压缩。

### 2.2 OpenAI Codex

本地源码：`D:\AI应用\openai-codex`

关键证据：

- `codex-rs/file-search/src/lib.rs:105-112`：文件搜索是 candidate discovery，带 ignore 语义，不替代读取事实。
- `codex-rs/file-search/src/lib.rs:276-283`：搜索截断显式提示 total/shown。
- `codex-rs/core/src/unified_exec/mod.rs:68-70`：unified exec raw 上限约 1MiB，不是几 KB 隐式压缩。
- `codex-rs/core/src/unified_exec/head_tail_buffer.rs:4-17`：大输出保留 head/tail，并记录 omitted bytes。
- `codex-rs/core/src/tools/context.rs:312-318`：raw_output 与 truncation policy 分离。
- `codex-rs/core/templates/compact/prompt.md`：compaction 是显式 handoff summary。

可借鉴标准：

- raw observation 与模型可见 truncation 是两件事。
- 截断必须显式，且要保留 raw 或可追踪 omitted 元数据。
- compaction 是显式交接，不是静默让旧 preview 继续当事实。

本项目偏差：

- provider protocol replay 对工具结果最多 `3000` 字符的 preview 被 prompt 误导成可恢复证据入口。
- raw read evidence 没有专门 artifact，只剩 generic persisted result 或 previous observation ref。

### 2.3 Pi coding-agent

本地源码：`D:\AI应用\pi-main\packages\coding-agent`

关键证据：

- `src/core/tools/read.ts:215`：read 截断后用 `offset/limit` 继续读。
- `src/core/tools/read.ts:301-317`、`:302-324`：截断时生成下一段 offset。
- `src/core/tools/truncate.ts:4-12`：截断按 line/byte limit，并避免返回部分行。

可借鉴标准：

- Read 可以限制，但限制属于 read tool 自身。
- 截断后必须告诉模型下一步如何继续读。

本项目偏差：

- 大 read 被 generic projection 压缩后，模型拿到的是 `read_persisted_tool_result` 恢复指令，而不是 read-specific continuation。

### 2.4 opencode

本地源码：`D:\AI应用\opencode-main`

关键证据：

- `internal/llm/tools/view.go:38-67`：View 工具窗口化读取，支持 offset/limit。
- `internal/llm/tools/view.go:172-187`：如果还有更多行，明确返回 continuation 提示。
- `internal/llm/tools/edit.go:267-280`、`:386-400`：edit 前必须 View/read，写入前检查 mtime，并要求 current disk 中 old_string 唯一。
- `internal/llm/tools/grep.go:78-80`、`:145-173`：搜索截断显式要求 refine search。

可借鉴标准：

- 搜索、读取、编辑三权分离。
- edit 最终检查当前磁盘与 old string，不把历史输出恢复当授权。

本项目偏差：

- `read_persisted_tool_result` 同时承担 retrieve 和当前 read evidence authorize，越权。

## 3. 当前链路实审

### 3.1 read_file observe 层

位置：`backend/runtime/tool_runtime/native_tools.py`

当前路径：

```text
NativeReadFileTool._call_sync
  -> build_read_file_window_result
  -> _unchanged_previous_read_window
  -> 命中后 tool_result.update(unchanged)
  -> text 替换为 _file_unchanged_read_stub
```

证据：

- `native_tools.py:334`：`NativeReadFileTool._call_sync`
- `native_tools.py:351-363`：真实读取后调用 `_unchanged_previous_read_window`
- `native_tools.py:363-381`：命中后把真实 text 替换为 stub，并写入 `content_omitted`、`previous_observation_ref`、`reusable_result_ref`
- `native_tools.py:418-445`：gateway 分支也有同样逻辑
- `native_tools.py:871-918`：`_unchanged_previous_read_window` 只检查 path/range/hash/mtime/stale，不确认旧 content 是否仍 exact 可见或可恢复
- `native_tools.py:920-935`：`_file_unchanged_read_stub`

越权点：

- observe 层在没有确认 exact content 可见或 artifact 可恢复时，决定“可以不给真实内容”。
- 它把“文件未变”误当成“模型仍能看到内容”。

目标：

- `read_file` 只负责观察当前文件并生成 exact artifact。
- 是否把内容省略给模型，属于 context assembly 的预算决策。
- 是否允许 edit，属于 `edit_file` 的当前文件守卫。

### 3.2 envelope 与 file state record 层

位置：

- `backend/runtime/tool_runtime/tool_result_envelope.py`
- `backend/runtime/tool_runtime/tool_executor.py`
- `backend/runtime/memory/file_state_store.py`
- `backend/runtime/memory/file_state_authority.py`

当前路径：

```text
read_file structured payload
  -> infer_file_state_events
  -> tool_executor._commit_file_state_events
  -> FileStateAuthorityStore.apply_events_scope
  -> FileStateAuthority active read range
```

证据：

- `tool_result_envelope.py:273`：`infer_file_state_events`
- `tool_result_envelope.py:296-311`：`file_unchanged`、`content_omitted`、`previous_observation_ref`、`reusable_result_ref` 进入 file_state_event
- `tool_executor.py:1423-1465`：提交 envelope file_state_events
- `file_state_store.py:32-78`：提交事件并持久化
- `file_state_authority.py:10-23`：`FileReadRange` 只有 `content_omitted`、`reusable_result_ref` 等弱字段，没有 exact artifact ref
- `file_state_authority.py:202-246`：read event 被记录进状态
- `file_state_authority.py:465-468`：active range 只按 stale/range 判断，不排除 omitted
- `file_state_authority.py:389-414`、`:461-462`：`coverage.complete` 表示行覆盖，不表示 exact content 可见

越权点：

- record 层把 omitted stub 和 exact read window 放在同一类 active range 里。
- `coverage.complete` 被下游读成“可以复用”，但它只证明行范围覆盖，不证明 exact bytes 可见。

目标：

- file state 必须区分 line coverage、visible exact coverage、artifact-restorable exact coverage。
- `content_omitted` 不能成为 `do_not_repeat` 或 edit evidence。
- read range 必须有 `exact_artifact_ref` 才能参与 exact reuse。

### 3.3 generic persisted output retrieve 层

位置：

- `backend/runtime_objects/tool_result_storage.py`
- `backend/runtime/tool_runtime/native_tools.py`

当前路径：

```text
ToolResultStore.apply_budget
  -> content_replacements
  -> read_persisted_tool_result
  -> _rehydrated_read_file_evidence
  -> file_state_event rehydrate_omitted_read_file
```

证据：

- `tool_result_storage.py:60`：`ToolResultStore`
- `tool_result_storage.py:66`：`apply_budget`
- `tool_result_storage.py:184`：`read_persisted_tool_result`
- `native_tools.py:478`：`NativeReadPersistedToolResultTool`
- `native_tools.py:520-553`：恢复 generic persisted output 后调用 `_rehydrated_read_file_evidence`
- `native_tools.py:601-765`：`_rehydrated_read_file_evidence` 混合恢复历史 bytes 与当前 read evidence 验证
- `native_tools.py:781-782`：生成 `read_intent=rehydrate_omitted_read_file`

越权点：

- generic persisted output store 被升级成 read evidence store。
- retrieve 工具又在判断当前文件证据是否有效。
- 这让历史输出恢复工具变成第二个 file evidence authority。

目标：

- `ToolResultStore` 只服务非 read_file 的通用大输出。
- `read_persisted_tool_result` 不处理 read_file code evidence，不写 read file_state_event。
- read_file exact bytes 的恢复由 `ReadObservationArtifactStore` 负责，但它也只 retrieve，不 authorize edit。

### 3.4 dynamic context assemble 层

位置：

- `backend/harness/runtime/dynamic_context/tool_result_projector.py`
- `backend/harness/runtime/dynamic_context/task_state_projector.py`
- `backend/harness/runtime/bound_task_context.py`

当前路径：

```text
tool_result_projector
  -> 对任何大 text 调 ToolResultStore.apply_budget
  -> read_file 也生成 content_replacements
  -> rehydration_plan 指向 read_persisted_tool_result

task_state_projector
  -> 从 content_omitted/reusable_result_ref 推导 rehydrate decision
  -> 输出 do_not_repeat_read_ranges

bound_task_context
  -> prompt 提示 rehydrate omitted tool_result bytes
```

证据：

- `tool_result_projector.py:80-139`：构建投影
- `tool_result_projector.py:87-101`：对 `.text` 应用 `ToolResultStore.apply_budget`
- `tool_result_projector.py:365-433`：为 read_file replacement 构建 `read_persisted_tool_result` capability
- `tool_result_projector.py:452-499`：对 read_file with replacements 标记 `rehydration_preference=read_persisted_tool_result_for_omitted_read_file`
- `task_state_projector.py:563-593`：投影 `read_windows_available`
- `task_state_projector.py:625-627`：`_file_reusable_result_ref` 会从 `reusable_result_ref`、`previous_observation_ref`、`observation_ref` 任意取 ref
- `task_state_projector.py:1242-1271`：只要 `content_omitted` 或有 reusable ref 就产生 rehydrate decision
- `task_state_projector.py:1288-1300`：把 omitted segment 投成 current evidence
- `task_state_projector.py:1306-1317`：用 previous/ref 要求恢复 omitted bytes
- `bound_task_context.py:402`：仍提示 rehydrate omitted tool_result bytes

越权点：

- assemble 层把 read code evidence 当 generic output 压缩。
- task state 把 weak ref 解释为可恢复 exact evidence。
- prompt 继续引导模型沿旧链路走。

目标：

- `read_file` 不进入 generic `content_replacements`。
- context assembly 负责注入 exact read artifact 或明确要求重新读。
- `do_not_repeat_read_ranges` 只针对 exact visible/restorable evidence。

### 3.5 provider protocol replay 层

位置：

- `backend/harness/runtime/context_budget_policy.py`
- `backend/harness/runtime/compiler.py`

当前路径：

```text
provider_protocol_history
  -> _project_provider_protocol_messages
  -> provider_protocol_tool_result_preview_chars <= 3000
  -> _with_provider_protocol_rehydration_note
  -> prompt warning: read_file use file_evidence_decisions to rehydrate omitted bytes
```

证据：

- `context_budget_policy.py:207-227`：`provider_protocol_tool_result_preview_chars` 最多 3000
- `compiler.py:86-87`：warning 仍写 read_file 使用 file_evidence_decisions 复用、恢复 omitted bytes
- `compiler.py:2854-2888`：provider protocol replay 按 message/char budget 裁剪
- `compiler.py:2888-2934`：tool result content 被 `ToolResultStore.apply_budget` 和 rehydration note 处理
- `compiler.py:3013-3018`：默认 preview 上限为 3000

越权点：

- provider replay 是协议连续性，不应该是 code truth。
- 低上下文压力下仍被固定 3K preview 压缩，和 850K 总窗口无关。

目标：

- provider replay 只保留协议连续性。
- read evidence 由 read artifact injection 阶段负责。
- 当前 edit target 在低压力下保持 exact visible。

### 3.6 prompt 与工具说明层

位置：

- `backend/prompt_library/rules.py`
- `backend/prompt_library/tool_prompts.py`

证据：

- `rules.py:63-66`：provider 历史出现 rehydration_plan/read_persisted_tool_result 就恢复；read_file 窗口被省略但有 plan，先恢复不要重复读。
- `tool_prompts.py:84-87`：`read_persisted_tool_result` 恢复 read_file 且 file_state 表明未变时，可作为读窗精确证据复用。

越权点：

- prompt 把 generic output retrieval 说成 read evidence retrieval。
- prompt 引导模型沿已经应删除的链路执行。

目标：

- prompt 只表达 agent 可执行职责，不写开发节点说明。
- `read_persisted_tool_result` 的说明限定为 non-read generic output。
- read_file evidence 规则改成：有 exact visible 或 exact artifact injection 才复用，否则 read current target window。

## 4. 为什么会重复读

重复读的完整因果链如下：

```text
1. 模型调用 read_file。
2. read_file 真实读取了文件。
3. tool_result_projector 或 provider replay 把真实内容压成 preview / persisted output。
4. file_state 仍记录这个范围被读过，有 observation_ref / previous_observation_ref。
5. 下次模型再读同范围。
6. _unchanged_previous_read_window 发现路径、范围、hash、mtime 没变。
7. 它没有检查 earlier exact content 是否仍可见，也没有检查 exact artifact 是否存在。
8. read_file 返回 content_omitted stub，而不是当前真实内容。
9. envelope 把 stub 再写进 file_state。
10. task_state_projector 输出不要重复读、先 rehydrate。
11. read_persisted_tool_result 对 read_file 来源又可能拒绝或只能恢复 generic preview。
12. 模型无法获得 exact old_text，edit_file 也无法满足当前读窗守卫。
13. 模型只能继续 read_file，于是重复进入第 6 步。
```

所以根因是“省略决策没有 exact artifact 前提”，不是“模型不知道不要重复读”。用 prompt 再强调“不要重复读”会加重问题，因为当前系统给模型的可用动作本来就只有读或走坏的 rehydration 链。

## 5. Authority Map

目标权力链：

```text
observe:
  read_file 观察当前磁盘窗口，生成 exact read artifact

record:
  FileStateAuthorityStore 记录 path/range/hash/mtime/exact_artifact_ref/stale

retrieve:
  ReadObservationArtifactStore 恢复历史 exact read bytes
  ToolResultStore 只恢复 non-read generic output

assemble:
  context compiler 根据当前任务和压力注入 exact read evidence 或请求 read_file

decide:
  模型基于 visible exact evidence 决定下一步工具调用或编辑

authorize:
  edit_file 检查当前磁盘、active exact read window、old_text 唯一性

execute:
  native tool 执行读取或写入

recover:
  缺 exact evidence 时返回明确 current read request

present:
  UI/monitor 只展示证据状态，不改写证据权威
```

| 文件/模块 | 当前职责 | 隐藏决策或越权 | 目标层 | 动作 | 证据 |
| --- | --- | --- | --- | --- | --- |
| `native_tools.py` `NativeReadFileTool` | 读取文件并返回结果 | 未确认 exact 可见/可恢复就返回省略 stub | observe | 写 exact artifact；stub 只在 exact artifact 存在且可注入时允许 | `native_tools.py:351-381`, `:871-918` |
| `native_tools.py` `_rehydrated_read_file_evidence` | 从 persisted result 恢复 read_file 并验证当前证据 | retrieve 工具越权 authorize 当前 file evidence | retrieve/authorize 分离 | 删除 read_file 分支；不写 read file_state_event | `native_tools.py:601-765`, `:781-782` |
| `tool_result_envelope.py` | 从 tool_result 推导 file event | 把 `content_omitted` stub 推成 active read event | normalize/record | read event 必须带 exact_artifact_ref 或标为 non-exact | `tool_result_envelope.py:296-311` |
| `file_state_authority.py` | 记录读窗与覆盖 | omitted range 可参与 active/current coverage | record | 拆 line coverage 与 exact coverage | `file_state_authority.py:389-468` |
| `tool_result_storage.py` | 通用工具输出存储 | 被当成 read observation artifact store | retrieve | 限定 non-read generic output | `tool_result_storage.py:60-225` |
| `tool_result_projector.py` | 动态投影工具结果 | read_file 进入 generic `apply_budget` 和 `read_persisted_tool_result` plan | assemble | read_file 走 read artifact policy，不生成 generic replacement | `tool_result_projector.py:80-139`, `:365-499` |
| `task_state_projector.py` | 输出 file_evidence_decisions | `previous_observation_ref` 被当可恢复 result ref | assemble | 只有 exact_artifact_ref 才能 rehydrate/do_not_repeat | `task_state_projector.py:625-627`, `:1242-1317` |
| `compiler.py` | provider protocol replay | 3K tool preview 被误当 code truth 入口 | assemble/present | provider replay 只做协议连续性，read evidence 单独注入 | `compiler.py:86-87`, `:2888-2934` |
| `bound_task_context.py` | prompt context policy | 提示 rehydrate omitted tool_result bytes | present/assemble | 改为 exact read artifact 或 current read | `bound_task_context.py:402` |
| `rules.py`、`tool_prompts.py` | 工具与行为规则 | 引导 read_file 走 generic rehydration | prompt | 删除 read_file persisted guidance | `rules.py:63-66`, `tool_prompts.py:84-87` |
| 旧测试 | 保护旧行为 | 断言 read_file 产生 generic replacements | validation | 删除或重写为目标行为测试 | `read_file_authority_chain_regression.py`, `tool_result_projection_regression.py` |

## 6. 必删旧链路

### 6.1 删除 read_file 的 generic content replacement

删除目标：

```text
read_file result.text
  -> ToolResultStore.apply_budget
  -> content_replacements
  -> rehydration_plan capability=read_persisted_tool_result
```

原因：

- 这条链把代码证据当普通长文本处理。
- 它没有 read range、hash、mtime、visible exact 的完整语义。
- 它和 FileStateAuthorityStore 并行持有“证据是否可用”的判断。

替代：

```text
read_file exact text
  -> ReadObservationArtifactStore
  -> FileStateAuthorityStore.exact_artifact_ref
  -> context assembly exact injection/read request
```

### 6.2 删除 read_persisted_tool_result 的 read_file current evidence 权力

删除目标：

```text
read_persisted_tool_result
  -> _rehydrated_read_file_evidence
  -> current file evidence decision
  -> file_state_event rehydrate_omitted_read_file
```

原因：

- retrieve 历史 bytes 不等于当前文件可编辑。
- 当前 edit 许可应该只由 `edit_file` 当前磁盘守卫和 FileStateAuthorityStore 决定。
- 保留该分支会形成两条证据链。

替代：

- `ReadObservationArtifactStore` 可按 `observation_ref` 或 `artifact_ref` 恢复当时 exact bytes。
- `edit_file` 仍必须读取当前磁盘并检查 active exact read window。

### 6.3 删除 prompt 中 read_file rehydrate 指令

删除目标：

- “read_file 窗口被省略但有 rehydration_plan，先恢复不要重复读”
- “read_persisted_tool_result 恢复 read_file 后可作为精确读窗证据”

原因：

- prompt 正在把模型导向旧链路。
- 当前问题不是模型需要更多提示，而是提示引用了错误的 authority。

替代：

- “如果 exact read window 可见或已由 context assembly 注入，可复用。”
- “如果 exact evidence 不存在、过期或目标行未覆盖，调用 read_file 读取当前目标窗口。”

### 6.4 删除保护旧链路的测试

删除或重写：

- `test_native_read_file_omits_unchanged_window`
- `test_native_read_file_session_scope_omits_unchanged_window`
- `test_native_read_file_omits_subwindow_covered_by_larger_current_read`
- `test_read_persisted_tool_result_rehydrates_read_file_as_current_evidence`
- `test_read_persisted_tool_result_rejects_stale_read_file_evidence`
- `test_tool_result_projector_marks_oversized_read_file_preview_as_partial_code_window`

原因：

- 这些测试保护的是旧内部结构，不是目标行为。
- 特别是“reject stale read_file persisted output”这种测试会诱导下游继续防御已删除链路。

替代测试见第 10 节。

## 7. 目标数据模型

### 7.1 新增 ReadObservationArtifactStore

建议文件：

```text
backend/runtime_objects/read_observation_artifacts.py
```

职责：

- 保存 `read_file` 每次真实读取产生的 exact bytes。
- 建立 `artifact_ref`、`tool_result_ref`、`observation_ref` 的 alias。
- 支持按 scope、path、range、hash、mtime 查找 exact artifact。
- 允许空文件 artifact。
- 不做 edit 授权。
- 不读取任意外部路径，只读自身 artifact store。

建议存储根：

```text
<runtime_storage_root>/read_observations/<task_run_id>/<artifact_digest>.json
<runtime_storage_root>/read_observations/<task_run_id>/<artifact_digest>.txt
<runtime_storage_root>/read_observations/<task_run_id>/aliases.json
```

建议数据结构：

```python
ReadObservationArtifact = {
    "artifact_ref": "read_observation:<digest>",
    "observation_ref": "observation:...",
    "tool_result_ref": "tool_result:...",
    "tool_call_id": "...",
    "task_run_id": "...",
    "scope_kind": "task_run",
    "scope_id": "...",
    "path": "...",
    "repository_id": "...",
    "start_line": 1,
    "end_line": 240,
    "line_count": 240,
    "total_lines": 1000,
    "has_more": True,
    "next_start_line": 241,
    "content_sha256": "sha256:...",
    "text_sha256": "sha256:...",
    "mtime_ns": 0,
    "size_bytes": 0,
    "content_omitted": False,
    "created_at": 0.0,
    "authority": "runtime_objects.read_observation_artifact.v1",
}
```

`text` 可单独存 `.txt`，metadata 存 `.json`。metadata 必须能校验 text digest。

### 7.2 空文件规则

空文件必须被视为合法 exact read，而不是“未读”：

- `text == ""`
- `size_bytes == 0`
- `line_count == 0`
- `total_lines == 0`
- `content_sha256 == sha256("")`
- `visible_exact == True`
- `exact_artifact_ref` 必须存在

编辑空文件时：

- `edit_file` 不能因为 old_text 为空就认为未读。
- 只有当前磁盘仍为空，且 active exact empty read window 当前有效时，才允许按空文件插入语义执行。
- 如果当前磁盘非空或 read evidence 过期，必须要求重新 `read_file`。

### 7.3 FileReadRange 新字段

`backend/runtime/memory/file_state_authority.py`

建议字段：

```python
exact_artifact_ref: str | None
artifact_ref_status: Literal["exact", "missing", "stale", "not_applicable"]
visible_exact: bool
content_omitted: bool
omission_reason: str | None
```

语义：

- `content_omitted=True` 只说明当前模型消息没有 exact text。
- `visible_exact=True` 说明当前 assembled context 中 exact text 可见。
- `exact_artifact_ref` 说明 exact text 可由 read observation artifact 恢复。
- `artifact_ref_status="exact"` 才能参与 exact reuse。
- `coverage.complete` 只代表 line coverage。
- 新增或派生 `exact_coverage.complete` 才能代表 exact evidence coverage。

## 8. 目标链路设计

### 8.1 正常读取

```text
模型调用 read_file(path, start_line, limit)
  -> NativeReadFileTool 读取当前磁盘
  -> build_read_file_window_result 生成 exact window
  -> ReadObservationArtifactStore.write_pending(...)
  -> tool_result 带 exact_artifact_ref/tool_result_ref
  -> tool_result_envelope 推导 read file_state_event
  -> FileStateAuthorityStore 记录 exact read range
  -> context assembly 在压力允许时保留 exact visible text
```

### 8.2 重复读取

```text
模型再次 read_file 同 path/range
  -> _unchanged_previous_read_window 查询 active read range
  -> 必须满足：
       文件 hash/mtime 未变
       range 非 stale
       range 有 exact_artifact_ref 且 artifact 可读
       earlier exact text 当前可见，或 context assembly 能注入 exact artifact
  -> 满足才可返回 lightweight stub
  -> 不满足则返回真实当前 window
```

重要：如果旧 range 是 `content_omitted=True` 且没有 exact artifact，不允许返回 stub。必须真实读取当前窗口。

### 8.3 上下文装配

```text
dynamic context manager
  -> 收集当前任务目标文件、active read ranges、artifact refs
  -> 判断 context pressure
  -> 当前 edit target / exact claim target：
       低压力：注入 exact text
       高压力且 artifact 存在：注入 metadata + 明确可恢复 artifact 标记
       artifact 不存在：注入 read_file current window request
  -> provider protocol replay 只保留协议连续性
```

### 8.4 工具输出压缩

```text
generic non-read large output
  -> ToolResultStore.apply_budget
  -> read_persisted_tool_result

read_file output
  -> 不走 ToolResultStore.apply_budget
  -> 走 ReadObservationArtifactStore
```

### 8.5 编辑

```text
模型调用 edit_file(path, old_text, new_text)
  -> edit_file 检查 FileStateAuthorityStore 中当前 exact read range
  -> 读取当前磁盘
  -> 检查 mtime/hash 或内容一致性
  -> old_text 在当前磁盘中唯一匹配
  -> 写入
  -> 旧 read ranges stale
  -> 写入后更新 file state
```

artifact restore 不能自动授权 edit。它最多让 context assembly 把 exact text 给模型看。

## 9. 文件级修改方案

### 9.1 新增 `backend/runtime_objects/read_observation_artifacts.py`

实现内容：

- `ReadObservationArtifactStore`
- `write_pending_read(...)`
- `bind_observation_ref(tool_result_ref, observation_ref)`
- `read_by_artifact_ref(...)`
- `read_by_observation_ref(...)`
- `find_exact(scope, path, start_line, end_line, content_sha256, mtime_ns)`
- digest 校验
- 空文件 artifact 支持
- store 内路径安全校验

不允许：

- 不判断 edit 是否允许。
- 不根据旧 ref 读取任意磁盘文件。
- 不接入 `read_persisted_tool_result`。

### 9.2 修改 `backend/runtime/tool_runtime/native_tools.py`

`NativeReadFileTool`：

- 每次真实读取后写 read observation artifact。
- tool result structured payload 增加：
  - `exact_artifact_ref`
  - `artifact_ref_status`
  - `visible_exact`
  - `read_observation_authority`
- 不把 `previous_observation_ref` 当 `reusable_result_ref`。

`_unchanged_previous_read_window`：

- 新增硬条件：
  - 旧 segment 不能是 `content_omitted=True` 且无 exact artifact。
  - 必须能 resolve exact artifact。
  - hash/mtime 仍匹配。
  - range 覆盖目标窗口。
- 如果不能满足，返回 `None`，让真实读取结果继续返回给模型。

`NativeReadPersistedToolResultTool`：

- 删除 `_rehydrated_read_file_evidence` read_file 分支。
- 不再生成 `read_intent=rehydrate_omitted_read_file`。
- 不再写 read file_state_event。
- 保留 generic non-read persisted output 能力。

不允许：

- 不新增“旧 read_file persisted output 兼容恢复”。
- 不新增 BaseTool 第二链路。

### 9.3 修改 `backend/runtime/tool_runtime/tool_result_envelope.py`

改动：

- read_file event 透传 `exact_artifact_ref`、`artifact_ref_status`、`visible_exact`。
- 如果 `content_omitted=True` 且无 exact artifact，不能生成可作为 active exact range 的 event。
- `file_unchanged` 只表示文件状态未变，不等于 exact content 可见。

验收：

- envelope 不再把 omitted stub 伪装成 exact read evidence。

### 9.4 修改 `backend/runtime/memory/file_state_authority.py`

改动：

- `FileReadRange` 增加 exact artifact 字段。
- 拆分：
  - `line_coverage`
  - `exact_coverage`
  - `visible_exact_coverage`
- `_active_read_ranges` 或新方法 `_active_exact_read_ranges` 排除：
  - stale
  - `content_omitted=True` 且无 exact artifact
  - artifact status 非 exact
- `coverage.complete` 不再被下游解释为 exact。

验收：

- omitted range 不能触发 do-not-repeat。
- exact artifact-backed range 可以被 context assembly 恢复。

### 9.5 修改 `backend/runtime/memory/file_state_store.py`

改动：

- 提交 read observation 后绑定 `observation_ref -> artifact_ref` alias。
- 状态序列化和恢复保留 exact artifact 字段。
- stale/write/edit 事件继续让旧 exact ranges 失效。

验收：

- 跨 turn 能通过 observation_ref 找到 artifact。
- 写入后旧 artifact 不再代表当前 evidence。

### 9.6 修改 `backend/harness/runtime/dynamic_context/tool_result_projector.py`

改动：

- 对 `tool_name == "read_file"` 跳过 `ToolResultStore.apply_budget`。
- read_file projection 改为 read-specific：
  - 低压力或当前关键目标：保留 exact text。
  - 高压力：保留 metadata、range、exact_artifact_ref、continuation。
  - 无 exact artifact：要求 current read_file。
- 不生成 `read_persisted_tool_result_for_omitted_read_file`。
- 不在 read_file 的 `content_replacements` 中生成 replacement。

generic non-read：

- 仍使用 `ToolResultStore.apply_budget`。
- 仍可生成 `read_persisted_tool_result` capability。

验收：

- `source_tool_name == "read_file"` 不再出现在 generic content replacement。

### 9.7 修改 `backend/harness/runtime/dynamic_context/task_state_projector.py`

改动：

- `read_windows_available` 增加 exact 字段。
- `_file_reusable_result_ref` 不再从 `previous_observation_ref` 或裸 `observation_ref` 推出可恢复 ref。
- `_file_evidence_decisions_projection`：
  - exact visible/restorable：`reuse_current_window`
  - exact artifact restorable but not visible：`inject_read_artifact`
  - omitted/no artifact：`read_missing_window`
  - stale：`read_after_stale`
- `do_not_repeat_read_ranges` 只输出 exact visible/restorable range。

验收：

- content omitted without artifact 时，模型看到的是“读当前窗口”，不是“不重复读”。

### 9.8 修改 `backend/harness/runtime/compiler.py`

改动：

- provider protocol replay 的 read_file tool result 标记为 protocol continuity only。
- `_PROVIDER_PROTOCOL_PREVIEW_WARNING` 删除 read_file rehydrate omitted bytes 文案。
- `_project_provider_protocol_messages` 不再为 read_file 生成 generic persisted replacement。
- 增加或接入 read evidence injection 阶段：
  - 从 file_state 和 read artifact store 选择当前关键 read windows。
  - 低压力 exact 注入。
  - 高压力 metadata + artifact ref。
  - artifact 缺失时生成 current read request。

验收：

- 850K preset、低 usage 时，当前 edit target read content 不被 provider replay 3K preview 替代。

### 9.9 修改 `backend/harness/runtime/context_budget_policy.py`

改动：

- 增加 read evidence budget policy。
- provider protocol tool result preview 仍可小，但不适用于 read evidence truth。
- 建议阈值：
  - context usage < 70%：当前目标 read windows exact visible。
  - 70% 到 90%：保留 edit target exact，非目标窗口可 artifact metadata。
  - > 90%：尽量保留最小 edit target exact，其他用 read artifact/request。

验收：

- 总上下文宽裕时不发生低级压缩。
- 大 generic output 仍能被预算控制。

### 9.10 修改 `backend/harness/runtime/bound_task_context.py`

改动：

- 替换 `file_precision` 文案：

```text
已知绑定文件路径不需要重新搜索。
做行级编辑或精确判断前，必须有当前有效的 exact read evidence。
如果目标范围已在当前上下文中 exact 可见，直接使用。
如果系统已注入 exact read artifact，使用该注入内容。
如果目标范围缺失、过期、只有 omitted preview 或没有 exact artifact，调用 read_file 读取当前目标窗口。
```

不写：

- 不写 “rehydrate omitted tool_result bytes”。
- 不写 “read_persisted_tool_result 恢复 read_file 后可作为证据”。

### 9.11 修改 `backend/prompt_library/rules.py`

改动：

- non-code omitted output：可以用 `read_persisted_tool_result`。
- read_file omitted output：不能用 generic persisted result 当 code evidence。
- exact file claim/edit 前必须满足：
  - current visible exact read window，或
  - context assembly 注入 exact read artifact，或
  - 重新 read_file。

### 9.12 修改 `backend/prompt_library/tool_prompts.py`

改动：

- `read_persisted_tool_result` 工具说明限定为 generic non-read output。
- 删除 read_file file_state 未变即可复用的说法。
- 说明恢复结果只是历史工具输出，不授予当前 edit 权限。

### 9.13 修改 capability registry

文件：

- `backend/capability_system/tools/native_tool_catalog.py`
- `backend/capability_system/tools/registries/TOOLS_REGISTRY.json`
- `backend/harness/runtime/tool_scheduling.py`
- `backend/harness/runtime/assembly.py`

改动：

- 保留 `read_persisted_tool_result` 作为 generic non-read output tool。
- 描述明确 not for read_file code evidence。
- 不恢复 `backend/capability_system/tools/tool_units/persisted_tool_result_tool.py`。
- 不新增 BaseTool fallback。

验收：

- native runtime 仍是唯一 `read_persisted_tool_result` 执行入口。
- read_file 不再被调度到 generic persisted output 恢复链。

## 10. 测试修改方案

### 10.1 `backend/tests/read_file_authority_chain_regression.py`

删除或重写旧测试：

- `test_native_read_file_omits_unchanged_window`
- `test_native_read_file_session_scope_omits_unchanged_window`
- `test_native_read_file_omits_subwindow_covered_by_larger_current_read`
- `test_read_persisted_tool_result_rehydrates_read_file_as_current_evidence`
- `test_read_persisted_tool_result_rejects_stale_read_file_evidence`

新增目标测试：

- `test_read_file_writes_exact_artifact_for_real_read`
- `test_read_file_does_not_stub_without_exact_artifact`
- `test_read_file_does_not_chain_content_omitted_stub`
- `test_read_file_reuse_requires_exact_artifact_ref`
- `test_read_observation_artifact_empty_file`
- `test_empty_file_edit_requires_current_exact_empty_read`
- `test_generic_persisted_output_does_not_emit_file_read_events`
- `test_edit_guard_requires_current_exact_read_window`

### 10.2 `backend/tests/tool_result_projection_regression.py`

删除或重写：

- `test_tool_result_projector_marks_oversized_read_file_preview_as_partial_code_window`

新增目标测试：

- `test_tool_result_projector_does_not_content_replace_read_file`
- `test_tool_result_projector_keeps_current_read_file_exact_under_low_pressure`
- `test_tool_result_projector_uses_read_artifact_metadata_under_high_pressure`
- `test_tool_result_projector_keeps_generic_non_read_persisted_output`

### 10.3 `backend/tests/dynamic_prompt_context_projection_test.py`

重写涉及 `file_evidence_decisions` 的旧期望：

- content omitted without exact artifact -> `read_missing_window`
- exact artifact exists but not visible -> `inject_read_artifact`
- exact visible -> `reuse_current_window`
- stale -> `read_after_stale`

新增：

- `test_task_state_projector_no_do_not_repeat_for_omitted_without_artifact`
- `test_task_state_projector_do_not_repeat_requires_exact_artifact_or_visible_exact`
- `test_task_state_projector_previous_observation_ref_is_not_reusable_result`

### 10.4 新增 `backend/tests/runtime_context_compiler_read_evidence_regression.py`

新增：

- `test_provider_protocol_does_not_make_read_file_3k_truth`
- `test_low_pressure_context_injects_current_edit_target_exact_read`
- `test_context_requests_current_read_when_artifact_missing`
- `test_read_artifact_injection_survives_provider_protocol_preview`

### 10.5 `backend/tests/file_state_authority_regression.py`

新增：

- `test_content_omitted_range_not_exact_coverage`
- `test_exact_artifact_range_counts_as_restorable_exact_coverage`
- `test_write_marks_exact_artifact_ranges_stale`
- `test_line_coverage_does_not_imply_exact_coverage`

### 10.6 禁止的测试方向

不写以下测试：

- 不测试旧 `persisted_tool_result_tool.py` 被防御。
- 不测试旧 read_file persisted output 被专门拒绝。
- 不测试旧 replacement id 格式仍兼容。
- 不通过断言 prompt 句子代替真实 read/edit 行为。
- 不 mock 掉核心 read_file/edit_file 来制造通过。

## 11. 分阶段实施计划

### Phase 0：落地前基线确认

目标：

- 确认当前失败链路和旧测试保护点。
- 不改代码。

动作：

```powershell
pytest backend/tests/read_file_authority_chain_regression.py -q
pytest backend/tests/tool_result_projection_regression.py -q
rg "read_persisted_tool_result_for_omitted_read_file|rehydrate_omitted_read_file|persisted_tool_result_tool|BaseTool.*read_persisted" backend
```

完成条件：

- 记录当前失败或旧行为基线。
- 确认旧链路入口列表。

### Phase 1：建立 ReadObservationArtifactStore

目标：

- read_file 每次真实读取都有 exact artifact。
- 空文件也有 exact artifact。

文件：

- 新增 `backend/runtime_objects/read_observation_artifacts.py`
- 修改 `backend/runtime/tool_runtime/native_tools.py`
- 修改 `backend/runtime/tool_runtime/tool_result_envelope.py`
- 修改 `backend/runtime/memory/file_state_store.py`

完成条件：

- `read_file` result 带 `exact_artifact_ref`。
- `FileStateAuthorityStore` 能保存 exact artifact ref。
- 空文件读不被当成未读。

### Phase 2：修正 FileStateAuthority exact 语义

目标：

- active read range 与 exact read range 分开。
- omitted stub 不再算 exact evidence。

文件：

- `backend/runtime/memory/file_state_authority.py`
- `backend/runtime/memory/file_state_store.py`
- `backend/harness/runtime/dynamic_context/task_state_projector.py`

完成条件：

- `content_omitted=True` without exact artifact 不输出 `do_not_repeat`。
- `coverage.complete` 不再被当 exact coverage。

### Phase 3：切断 read_file generic persisted output

目标：

- read_file 不再进入 `ToolResultStore.apply_budget`。
- `read_persisted_tool_result` 不再恢复或授权 read_file evidence。

文件：

- `backend/harness/runtime/dynamic_context/tool_result_projector.py`
- `backend/runtime/tool_runtime/native_tools.py`
- `backend/runtime_objects/tool_result_storage.py`
- `backend/capability_system/tools/native_tool_catalog.py`
- `backend/capability_system/tools/registries/TOOLS_REGISTRY.json`

完成条件：

- `rg "read_persisted_tool_result_for_omitted_read_file|rehydrate_omitted_read_file" backend` 无运行链路残留。
- generic non-read persisted output 测试仍通过。

### Phase 4：重写 context assembly 与 provider replay

目标：

- provider replay 不再承载 read evidence truth。
- 低上下文压力下当前目标 read window exact visible。

文件：

- `backend/harness/runtime/compiler.py`
- `backend/harness/runtime/context_budget_policy.py`
- `backend/harness/runtime/dynamic_context/tool_result_projector.py`
- `backend/harness/runtime/dynamic_context/task_state_projector.py`

完成条件：

- 850K preset、低 usage、当前 edit target 不被 3K preview 替代。
- artifact 缺失时输出 current read request。

### Phase 5：清理 prompt 与旧测试

目标：

- prompt 不再引导旧 rehydration 链。
- 测试保护目标行为而不是旧结构。

文件：

- `backend/harness/runtime/bound_task_context.py`
- `backend/prompt_library/rules.py`
- `backend/prompt_library/tool_prompts.py`
- `backend/tests/read_file_authority_chain_regression.py`
- `backend/tests/tool_result_projection_regression.py`
- `backend/tests/dynamic_prompt_context_projection_test.py`
- 新增 `backend/tests/runtime_context_compiler_read_evidence_regression.py`

完成条件：

- 旧链路测试被删除或改写。
- 新测试覆盖 artifact、empty file、omitted without artifact、provider replay、edit guard。

### Phase 6：真实链路验证

目标：

- 用真实任务验证不再重复读。
- 涉及运行链路时按项目固定端口启动。

命令：

```powershell
pytest backend/tests/read_file_authority_chain_regression.py -q
pytest backend/tests/tool_result_projection_regression.py -q
pytest backend/tests/file_state_authority_regression.py -q
pytest backend/tests/dynamic_prompt_context_projection_test.py -q
pytest backend/tests/runtime_context_compiler_read_evidence_regression.py -q
```

运行链路验证：

```powershell
# 后端固定 http://127.0.0.1:8003
# 前端固定 http://127.0.0.1:3000
```

真实场景：

1. 读取一个超过 3000 字符但远小于 850K 剩余上下文的文件窗口。
2. 触发同范围重复读。
3. 验证第二次不返回不可还原 stub。
4. 验证如果返回 stub，context 已注入 exact artifact 或 artifact 可恢复。
5. 使用窗口内 exact `old_text` 执行 `edit_file`。
6. 验证 edit 成功，或失败时明确要求 current read window，不进入 read loop。

## 12. 验收标准

必须满足：

- `read_file` exact bytes 不再走 generic `ToolResultStore` 主链。
- `read_persisted_tool_result` 只服务 non-read generic output。
- `content_omitted` without exact artifact 不进入 `do_not_repeat_read_ranges`。
- `previous_observation_ref` 不再被当成可恢复 bytes。
- provider replay 的 3K preview 不再代表 code truth。
- 低上下文压力下当前 edit target exact visible。
- 空文件读写有明确 exact evidence 路径。
- `edit_file` 仍是当前文件写入最终守卫。
- 删除旧链路相关提示、投影和测试。

最终残留扫描：

```powershell
rg "read_persisted_tool_result_for_omitted_read_file|rehydrate_omitted_read_file" backend
rg "persisted_tool_result_tool|BaseTool.*read_persisted" backend
rg "rehydrate omitted tool_result bytes|read_file.*read_persisted_tool_result" backend
```

预期：

- 第一条无运行链路残留。
- 第二条不出现恢复旧 BaseTool 的实现。
- 第三条不出现 prompt 引导 read_file 走 generic persisted output。

## 13. 不允许事项

- 不做 prompt-only 修复。
- 不保留两条 read evidence 主链。
- 不用兼容、兜底、防御为理由保留旧 read_file persisted 链路。
- 不恢复 `backend/capability_system/tools/tool_units/persisted_tool_result_tool.py`。
- 不把 `content_omitted` stub 当 active exact read window。
- 不把 `coverage.complete` 当 exact coverage。
- 不把 provider protocol replay 当 code truth。
- 不让 `read_persisted_tool_result` 写 read file_state_event。
- 不为已删除旧链路写专门保护测试。
- 不降低断言、跳过测试、mock 核心逻辑来制造通过。

## 14. 预期收益

- 模型不会在“读到 stub -> 恢复失败 -> 再读到 stub”的循环里卡死。
- read/search/edit 的边界更接近成熟 coding agent。
- 上下文装配不再在低压力下乱压当前关键代码。
- 文件状态权威只记录可验证的 read evidence。
- 后续维护者能清楚知道：代码证据来自 read observation artifact，不来自 generic persisted tool output。
