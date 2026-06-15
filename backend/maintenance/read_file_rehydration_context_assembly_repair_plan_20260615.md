# Read File Evidence Rehydration And Context Assembly Repair Plan

日期：2026-06-15

## 1. 目的

修复新任务运行时在文件读取、上下文装配、工具输出省略和编辑前证据校验上的结构性问题。

本计划只处理一个核心性质：`read_file` 产生的代码证据必须可见、可恢复、可验证，不能在总上下文仍很宽裕时被通用工具输出压缩机制提前压成不可用的 preview 或 stub。

本计划先作为实施前设计文档。涉及 runtime、tool calling、context assembly、state 和测试结构，按项目规则需要确认后再落代码。

## 2. 当前故障

### 2.1 表现

- 截图显示上下文使用量只有 `62.9K / 850.0K 7%`，不是总上下文窗口耗尽。
- 模型反复调用 `read_file`，但拿到的是类似“文件未变化，内容省略，使用之前读取结果”的 stub。
- 旧的精确代码窗口已经不在当前可见上下文里，或者只剩 `previous_observation_ref` / `reusable_result_ref`，无法还原为原始 bytes。
- `read_persisted_tool_result` 有时拒绝恢复，因为它发现源是 `content_omitted` 的 read_file stub，或当前文件证据状态与历史元数据不一致。
- `edit_file` 需要当前有效 read window 和精确 `old_text`，但模型可见上下文里只有 stub / preview，因此进入“读、被省略、再读、再省略”的循环。

### 2.2 根因一句话

本项目把 `read_file` 的精确代码证据当成通用工具输出压缩，又让重复读取依赖一个不可还原的 `previous_observation_ref`，同时把“恢复历史 bytes”和“验证当前文件能否编辑”混在 `read_persisted_tool_result` 里，导致模型既看不到旧代码，也无法通过 ref 取回旧代码，只能重复读。

## 3. 本地源码证据

### 3.1 read_file 会主动返回省略 stub

`backend/runtime/tool_runtime/native_tools.py:363-381`：

- 读取当前文件窗口后调用 `_unchanged_previous_read_window(...)`。
- 如果命中旧状态，就把真实 `window.text` 替换为 `_file_unchanged_read_stub(...)`。
- structured payload 里会带 `file_unchanged`、`content_omitted`、`previous_observation_ref`、`reusable_result_ref`。

`backend/runtime/tool_runtime/native_tools.py:871-935`：

- `_unchanged_previous_read_window` 只检查路径、范围、hash、mtime、stale。
- 它没有拒绝 `segment.content_omitted == True` 的旧 read range。
- 因此一个已省略的 stub 也可能成为下一次 stub 的依据，形成“stub 指向 stub”的链。

`backend/runtime/tool_runtime/tool_result_envelope.py:273-314`：

- `read_file` 的 structured payload 会被自动推导成 file state event。
- 如果 `tool_result` 带 `file_unchanged`、`content_omitted`、`previous_observation_ref`，这些字段会进入 file state。

`backend/runtime/tool_runtime/tool_executor.py:1423-1465` 与 `backend/runtime/memory/file_state_store.py:32-78`：

- executor 会把 envelope 上的 file state event 提交进 `FileStateAuthorityStore`。
- 所以 stub 不是一次性的展示文本，它会变成后续 `_unchanged_previous_read_window` 的候选状态。

这就是“为什么重复读”：当前实现认为同范围已读且文件未变，所以重复读不再返回内容。但这个判断没有确认早先内容仍在模型上下文中，也没有确认存在 observation-ref 级别的 exact artifact 可以还原。

### 3.2 通用工具输出存储不是 read observation artifact store

`backend/runtime_objects/tool_result_storage.py:60-104`：

- `ToolResultStore.apply_budget` 遍历 `.text`、`.content` 等通用字段。
- 字段超 `field_limit_bytes` 或 payload 超 `payload_budget_bytes` 时，写入 `tool_results/<run_id>/*-digest.txt`，再用 `<persisted-output>` preview 替换。

`backend/runtime_objects/tool_result_storage.py:184-225`：

- `read_persisted_tool_result` 通过 `replacement_id` 或 path 读取通用 persisted tool result。
- 它不是按 `observation_ref` 建索引，也不知道某次 read_file 原始窗口在后续 stub 中应该如何恢复。

所以 `previous_observation_ref` 不是可恢复 bytes 的句柄。它只是 file state 里的观察引用。

### 3.3 read_persisted_tool_result 混合了两种权力

`backend/runtime/tool_runtime/native_tools.py:521-598`：

- 先调用通用 `read_persisted_tool_result(...)` 恢复存储内容。
- 然后调用 `_rehydrated_read_file_evidence(...)` 判断它是否还能作为当前文件证据。

`backend/runtime/tool_runtime/native_tools.py:601-765`：

- 对 read_file 来源，它会继续检查 file evidence scope、当前文件状态、hash、mtime、磁盘文件和 active read windows。
- 如果 source metadata 里 `content_omitted == True`，直接拒绝：`persisted_read_file_was_already_omitted`。

这个函数同时做了：

- `retrieve`：恢复历史工具输出 bytes。
- `authorize/decide`：判断当前文件证据是否可用于 edit。

成熟 agent 里这两个权力不应混在一起。历史 bytes 恢复只能说明“这是当时看到的内容”；当前 edit 许可应由 `edit_file` 最终检查当前磁盘和 read evidence。

### 3.4 provider protocol replay 有独立硬预算

`backend/harness/runtime/context_budget_policy.py:207-227`：

- `tool_result_preview_chars` 被夹在 `4000..24000`。
- `provider_protocol_char_budget` 被夹在 `6000..24000`。
- `provider_protocol_tool_result_preview_chars` 被夹在 `800..3000`。

`backend/harness/runtime/compiler.py:3013-3018`：

- 即使上游 `tool_result_preview_chars` 更大，provider protocol tool result preview 仍被压到最多 `3000`。

`backend/harness/runtime/compiler.py:2861-2871`：

- provider protocol replay 先选最近消息，再按字符预算裁剪。

这解释了为什么 `850K` 上下文只用了 `7%`，代码证据仍被省略：省略来自项目自己的 provider replay 和 tool projection 预算，不是模型上下文满了。

### 3.5 测试正在保护旧链路

`backend/tests/tool_result_projection_regression.py:131-180`：

- `test_tool_result_projector_marks_oversized_read_file_preview_as_partial_code_window` 明确断言大型 `read_file` 会产生 `content_replacements`。
- 它还断言 rehydration capability 是 `read_persisted_tool_result`。

这正好保护了当前错误方向：把 read_file 代码证据压进通用 persisted tool result，然后让模型再调工具取回。

## 4. 外部源码审查

### 4.1 OpenAI Codex

本地源码目录：`D:\AI应用\openai-codex`

`D:\AI应用\openai-codex\codex-rs\file-search\src\lib.rs:105-112`：

- 文件搜索明确只是 candidate discovery。
- 它有 ignore 语义，默认尊重 gitignore，但用 `require_git(true)` 限定父目录 ignore 不能误杀仓库内文件。

`D:\AI应用\openai-codex\codex-rs\file-search\src\lib.rs:276-283`：

- 搜索结果有 total match count 和 shown count，结果被截断时显式 warning。

`D:\AI应用\openai-codex\codex-rs\core\src\unified_exec\mod.rs:68-70`：

- unified exec 输出上限是 `1 MiB`，并换算 token 上限，不是几 KB provider replay 硬切。

`D:\AI应用\openai-codex\codex-rs\core\src\unified_exec\head_tail_buffer.rs:4-17`：

- 大输出保留 head/tail，并统计 `omitted_bytes`，省略是显式元数据。

`D:\AI应用\openai-codex\codex-rs\core\src\tools\context.rs:312-318`：

- exec 工具保存 `raw_output`，再按 `TruncationPolicy` 生成模型响应文本。

`D:\AI应用\openai-codex\codex-rs\core\templates\compact\prompt.md`：

- compaction 是显式 handoff summary，不是静默丢弃关键工具证据。

可借鉴点：

- 搜索只定位候选，不替代读取证据。
- 大输出可截断，但要保留原始 bytes 或明确 omitted 元数据。
- 压缩是有触发条件和交接语义的，不应在低上下文压力下静默抹掉当前关键代码。

### 4.2 Claude Code

本地源码目录：`D:\AI应用\claude-code-nb-main`

`D:\AI应用\claude-code-nb-main\tools\FileReadTool\FileReadTool.ts:340-342`：

- Read 工具声明 `maxResultSizeChars: Infinity`。
- 注释写明 Read 已由 `maxTokens` 自限，把 Read 输出持久化到文件再让模型用 Read 读回来是循环，所以永不持久化。

`D:\AI应用\claude-code-nb-main\tools\FileReadTool\limits.ts:2-7` 和 `:18`：

- Read 有自己的限制：默认 `25000` tokens，文件大小默认 `256 KB`。
- 这是 read-specific budget，不是通用工具输出压缩。

`D:\AI应用\claude-code-nb-main\tools\FileReadTool\prompt.ts:7-8`：

- 重复读 stub 的语义是： earlier Read tool_result in this conversation is still current。
- 这个 stub 成立的前提是早先真实 Read 仍在对话可见。

`D:\AI应用\claude-code-nb-main\tools\FileReadTool\FileReadTool.ts:523-525`：

- 代码注释也明确：早先 Read tool_result 还在 context 里，重复发完整内容浪费 token。

`D:\AI应用\claude-code-nb-main\services\compact\compact.ts:1399-1405`：

- compaction 后为最近访问文件创建附件，使用 FileReadTool 重新读取真实内容。

`D:\AI应用\claude-code-nb-main\services\compact\compact.ts:1606-1608`：

- 如果 preserved tail 里是 dedup stub，它不会把 stub 当作真实内容；会重新注入真实内容。

`D:\AI应用\claude-code-nb-main\services\compact\compact.ts:122-124`：

- post-compact 文件恢复有单文件 `5000` tokens 和总预算 `50000`。

`D:\AI应用\claude-code-nb-main\utils\toolResultStorage.ts:59-63`：

- `Infinity` 是 hard opt-out，Read 不受通用工具输出持久化实验覆盖。

`D:\AI应用\claude-code-nb-main\tools\FileEditTool\FileEditTool.ts:275-280`、`:442-454`、`:520-524`：

- edit 需要先读文件。
- 写入前读取当前文件并检查 mtime/content 是否仍匹配。
- 写入成功后更新 read state。

可借鉴点：

- Read 是独立预算和独立状态，不进入通用工具结果持久化。
- 重复读 stub 只在早先完整 Read 仍可见或可恢复时成立。
- compact 后恢复真实文件内容，不把 stub 当真。
- edit 是当前文件守卫，不是 rehydration 工具来授权编辑。

关键纠偏：

- 不能只抄 Claude 的 `file_unchanged` stub 文案。
- Claude 的 stub 前提是“earlier Read tool_result in this conversation is still current”，并且 Read 被 `maxResultSizeChars: Infinity` 排除在通用持久化预算之外。
- 本项目当前做法是：早先内容可能已被 provider replay / tool projection 省略，却仍根据 file state 返回 stub。这不是 Claude Code 的设计，是把 Claude 的局部优化拆掉前提后误用。

### 4.3 Pi coding-agent

本地源码目录：`D:\AI应用\pi-main\packages\coding-agent`

`D:\AI应用\pi-main\packages\coding-agent\src\core\tools\truncate.ts:4-8`：

- 截断按 line limit 和 byte limit，且不返回部分行。

`D:\AI应用\pi-main\packages\coding-agent\src\core\tools\truncate.ts:11-12`：

- 默认 `2000` lines 和 `50KB`。

`D:\AI应用\pi-main\packages\coding-agent\src\core\tools\read.ts:215`：

- Read 描述明确：输出截断时用 `offset/limit` 继续。

`D:\AI应用\pi-main\packages\coding-agent\src\core\tools\read.ts:301-317`：

- 截断时生成下一段 `offset`，告诉模型如何继续。

可借鉴点：

- 可以限制 read，但必须显式给 continuation。
- 截断元数据和下一步读法属于 Read 工具本身，不应由 provider replay 静默改写。

### 4.4 opencode

本地源码目录：`D:\AI应用\opencode-main`

`D:\AI应用\opencode-main\internal\llm\tools\view.go:38-67`：

- View 工具是窗口化读取：默认 2000 行，支持 offset/limit，明确告诉模型大文件从指定 offset 继续读。

`D:\AI应用\opencode-main\internal\llm\tools\view.go:172-187`：

- 读取结果带行号；如果文件还有更多行，返回明确 continuation 提示。

`D:\AI应用\opencode-main\internal\llm\tools\edit.go:267-280` 与 `:386-400`：

- edit 前必须读过文件。
- 写入前检查文件 mtime 是否晚于 last read。
- 然后当前磁盘读取文件并要求 `old_string` 唯一匹配。

`D:\AI应用\opencode-main\internal\llm\tools\grep.go:78-80`、`:145-173`：

- 搜索结果截断时显式告诉模型 refine search。

可借鉴点：

- 搜索是定位候选，读取是文件证据。
- 读可以窗口化，但必须给 offset continuation。
- edit 的授权依据是当前文件读状态和当前磁盘，不是一个历史工具输出恢复器。

## 5. 成熟 agent 标准

面向本项目，成熟标准应是：

1. `search_files` / `search_text` / code structure 只负责定位候选，不能当完整源码事实。
2. `read_file` 是代码证据观察者，返回精确窗口和结构化范围元数据。
3. `read_file` 可以窗口化和显式截断，但不能在低上下文压力下被通用 tool result budget 隐性压成 preview。
4. 重复读取 stub 只允许在早先 exact read 仍模型可见，或存在 exact observation artifact 可恢复时使用。
5. content-omitted read range 不能作为下一次 content-omitted stub 的依据。
6. generic tool output 可以进 `ToolResultStore`，但 read_file 代码证据不走这条通用持久化链。
7. compaction 或 provider replay 省略了 read 内容时，context assembly 要么自动恢复 exact read artifact，要么明确要求重新 `read_file` 当前窗口。
8. `edit_file` 是最终当前文件写入守卫，负责检查当前磁盘、hash/mtime、active read window 和 `old_text` 唯一性。
9. 恢复历史 bytes 不能授权当前 edit；当前 edit 也不能要求恢复工具历史才能证明文件没变。
10. 禁止保留两条 read 证据链：不能同时保留 `read_file -> ToolResultStore -> read_persisted_tool_result` 和新的 read observation artifact 链。

## 6. 目标权力链

```text
search_files/search_text
  -> candidate locator only

read_file
  -> observe current file window
  -> emit exact visible text when needed
  -> store ReadObservationArtifact
  -> emit file_state_event with exact_artifact_ref

ReadObservationArtifactStore
  -> retrieve exact historical read bytes by observation_ref/tool_result_ref
  -> no edit authorization

FileStateAuthorityStore
  -> record current file read windows, hashes, mtime, artifact refs, stale state
  -> decide whether a read window is exact, omitted, stale, or restorable

Context compiler/projectors
  -> assemble model-visible context
  -> preserve current critical read windows while pressure is low
  -> auto-reinject exact read artifacts when a stub would otherwise be the only evidence
  -> never make provider replay preview the source of code truth

edit_file
  -> read current disk before write
  -> verify current active read window covers old_text
  -> verify hash/mtime or content equality
  -> write or reject with a precise current-read request
```

明确唯一主链：

```text
read_file exact bytes
  -> ReadObservationArtifactStore
  -> FileStateAuthorityStore exact_artifact_ref
  -> context assembly injects exact evidence or requests current read
  -> edit_file performs final current-file guard
```

明确删除旧主链：

```text
read_file exact bytes
  -> ToolResultStore content_replacements
  -> read_persisted_tool_result
  -> file_state_event rehydrate_omitted_read_file
```

## 7. 数据模型变更

新增内部存储：`ReadObservationArtifactStore`。

建议位置：`backend/runtime_objects/read_observation_artifacts.py`。

核心对象：

```python
ReadObservationArtifact = {
    "artifact_ref": "read_observation:<digest>",
    "observation_ref": "...",
    "tool_result_ref": "...",
    "tool_call_id": "...",
    "task_run_id": "...",
    "scope_kind": "task_run|session",
    "scope_id": "...",
    "path": "...",
    "repository_id": "...",
    "start_line": 1,
    "end_line": 240,
    "line_count": 240,
    "total_lines": 1000,
    "has_more": True,
    "next_start_line": 241,
    "content_sha256": "...",
    "text_sha256": "...",
    "mtime_ns": 123,
    "size_bytes": 12345,
    "text": "... exact read_file output window ...",
    "content_omitted": False,
    "created_at": 0.0,
    "authority": "runtime_objects.read_observation_artifact.v1",
}
```

注意：

- 空文件 artifact 合法：`text == ""`，`size_bytes == 0`，`total_lines == 0`。
- artifact 必须区分 `tool_result_ref` 和 `observation_ref`。
- 如果 read_file 执行时 observation_ref 尚未分配，先用 `tool_result_ref` 写 pending artifact，观察提交后在 `ToolRuntimeExecutor` 或 observation ledger 提交阶段建立 `observation_ref -> artifact_ref` alias。

## 8. 模块计划

### 8.1 `backend/runtime/tool_runtime/native_tools.py`

改动：

- `NativeReadFileTool` 每次真实读取后都写 `ReadObservationArtifact`。
- `_unchanged_previous_read_window` 只能复用满足以下条件的 range：
  - `content_omitted` 不是 true。
  - range 有 `exact_artifact_ref` 或 `reusable_result_ref` 指向 exact artifact。
  - 文件 hash/mtime 仍匹配。
  - 当前 context assembly 确认可见，或 artifact store 可恢复。
- 如果旧 range 是 omitted stub，不再返回 stub，必须返回真实当前 window。
- `reusable_result_ref` 不再用裸 `previous_observation_ref` 伪装成可恢复结果。
- `NativeReadPersistedToolResultTool` 不处理 `read_file` 证据，不恢复 read_file bytes，不写 read file_state_event。
- 删除 `_rehydrated_read_file_evidence` 的 read_file 授权分支；不要把它改成“兼容旧 read_file 持久化结果”的防御分支。
- `read_persisted_tool_result` 只恢复 generic non-read 大工具输出。它不能成为 read/edit 链路的一环。

### 8.2 `backend/runtime_objects/tool_result_storage.py`

改动：

- 保留为 generic non-read tool result store。
- 明确不作为 `read_file` exact code evidence 的主路径。
- `read_persisted_tool_result` 继续服务非代码、非 read_file 的大工具输出。

### 8.3 新增 `backend/runtime_objects/read_observation_artifacts.py`

职责：

- 写入 pending read artifact。
- 根据 `tool_result_ref`、`observation_ref` 建 alias。
- 支持按 scope/path/range 查找 exact artifact。
- 只恢复历史 read bytes，不判断当前 edit 是否允许。
- 防止任意路径读取：只能读取自身 store 下的 artifact。

### 8.4 `backend/runtime/memory/file_state_authority.py`

改动：

- `FileReadRange` 增加 `exact_artifact_ref`、`artifact_ref_status`。
- `content_omitted == True` 的 range 不能参与 `_active_read_ranges` 的 exact evidence 复用。
- `coverage.complete` 只能表示文件行覆盖，不等于模型可见 exact content；需要新增 `exact_coverage` 或 `visible_exact_coverage`。
- write/edit 后继续把旧 range 标记 stale。

### 8.5 `backend/runtime/memory/file_state_store.py`

改动：

- 提交 observation 时把 read artifact alias 从 `tool_result_ref` 绑定到 `observation_ref`。
- 存储 file_state event 时保留 `exact_artifact_ref`。

### 8.6 `backend/harness/runtime/dynamic_context/tool_result_projector.py`

改动：

- `read_file` 不再默认进入 `ToolResultStore.apply_budget`。
- read_file projection 改为：
  - 小窗口或低压力：保留 exact visible text。
  - 高压力：保留 read range metadata + exact artifact ref + explicit continuation，不给 `read_persisted_tool_result` capability。
  - content omitted 时只允许指向 `ReadObservationArtifactStore` 或要求重新 `read_file`。
- 删除把 oversized read_file 视为通用 `content_replacements` 的路径。
- `content_replacements` 中不再出现 `source_tool_name == "read_file"`。
- 不再生成提示模型调用 `read_persisted_tool_result` 来恢复 read_file 的 capability / rehydration_plan。

### 8.7 `backend/harness/runtime/dynamic_context/task_state_projector.py`

改动：

- `read_windows_available` 中区分 `exact_artifact_ref`、`content_omitted`、`visible_exact`。
- `do_not_repeat_read_ranges` 只对 exact visible 或 exact artifact-restorable 的 range 生效。
- 如果只有 omitted stub，不输出“不要重复读”，而输出“需要重新 read_file 当前窗口”。
- 如果 range 只有 `previous_observation_ref` 而没有 exact artifact ref，不允许把它标成可复用。

### 8.8 `backend/harness/runtime/bound_task_context.py`

改动：

- `file_precision` 文案从“rehydrate omitted tool_result bytes”改为：
  - read_file 当前代码证据优先 exact visible read window。
  - 如果有 exact read observation artifact，context assembly 会恢复或标注。
  - 没有 exact artifact 时，调用 read_file 读取目标范围。
- 不再引导模型把 read_file 内容交给 `read_persisted_tool_result`。

### 8.9 `backend/harness/runtime/context_budget_policy.py`

改动：

- 删除 provider replay 对工具结果固定 `3000` 的 read_file 路径。
- 新增 pressure-aware read evidence budget：
  - 当 estimated usage 低于阈值，比如 70%，当前任务的 edit-target/read-target 窗口保持 exact。
  - 只有上下文压力高、窗口过大或非当前目标时，才按 read-specific policy 缩减。
- provider replay 仍可保持小预算，但它只负责协议连续性，不能承载代码证据真相。

### 8.10 `backend/harness/runtime/compiler.py`

改动：

- provider protocol replay 中 read_file 工具结果不再作为 exact evidence。
- context assembly 增加 read evidence injection 阶段：
  - 收集当前目标文件、active read windows、artifact refs。
  - 如果窗口关键且上下文压力低，注入 exact artifact text。
  - 如果 artifact 不存在，注入明确的 `read_file` 请求，不给不可执行的 rehydration hint。
- 删除 `read_file content -> read_persisted_tool_result` 的提示链路。

### 8.11 `backend/capability_system/tools/native_tool_catalog.py` 和 `TOOLS_REGISTRY.json`

改动：

- `read_persisted_tool_result` 保留为 generic persisted output tool，但说明不用于 read_file code evidence。
- 不恢复 `backend/capability_system/tools/tool_units/persisted_tool_result_tool.py`。
- 不新增旧 BaseTool 链路。
- 不新增“历史 read_file persisted result 仍可恢复”的兼容说明。

### 8.12 Prompt 文案

改动：

- `backend/prompt_library/tool_prompts.py`
- `backend/prompt_library/rules.py`

原则：

- 对 agent 说清楚角色和操作边界。
- 不把开发说明写成 prompt。
- 不再让模型把 read_file 代码证据通过 generic persisted output 还原。
- 对 omitted read evidence 的处理只有两个选择：
  - 当前文件未变且 context 已注入 exact artifact：可用。
  - 否则重新 `read_file` 目标窗口。

## 9. 测试计划

### 9.1 新增或重写测试

`backend/tests/read_file_authority_chain_regression.py`

- `test_read_file_does_not_stub_when_previous_range_has_no_exact_artifact`
- `test_read_file_does_not_chain_stub_to_content_omitted_stub`
- `test_read_file_reuses_only_exact_artifact_backed_previous_range`
- `test_empty_file_read_writes_zero_byte_exact_artifact_and_complete_state`
- `test_edit_empty_old_text_allowed_only_for_current_confirmed_empty_file`
- `test_edit_file_remains_final_current_file_guard_after_artifact_restore`
- 删除或重写当前保护旧行为的用例：
  - `test_native_read_file_omits_unchanged_window`
  - `test_native_read_file_session_scope_omits_unchanged_window`
  - `test_native_read_file_omits_subwindow_covered_by_larger_current_read`
  - `test_read_persisted_tool_result_rehydrates_read_file_as_current_evidence`
  - `test_read_persisted_tool_result_rejects_stale_read_file_evidence`

`backend/tests/tool_result_projection_regression.py`

- 删除或重写 `test_tool_result_projector_marks_oversized_read_file_preview_as_partial_code_window`。
- 新断言：低压力 read_file projection 保留 exact text，不产生 `content_replacements`。
- 新断言：高压力 read_file projection 输出 read observation artifact ref，不输出 `read_persisted_tool_result` capability。
- generic non-read large output 仍产生 `content_replacements`。

`backend/tests/runtime_context_compiler_read_evidence_regression.py`

- 850K preset + 低 usage 下，provider replay 不把当前 edit target read window 压到 3000 字符。
- provider replay 只作为协议连续性，不是 file evidence authority。
- context assembly 能从 read observation artifact 注入 exact current target window。

`backend/tests/file_state_authority_regression.py`

- `content_omitted` range 不参与 exact reuse。
- write/edit 后 exact artifact-backed ranges 被 stale。
- coverage 和 exact coverage 分开计算。

### 9.2 删除或禁止的测试方向

- 不保留防御已删除 `persisted_tool_result_tool.py` 的 BaseTool 兼容测试。
- 不写“旧 replacement id 格式仍可用”的兼容测试。
- 不写“read_persisted_tool_result 能拒绝旧 read_file persisted output”的防御测试；旧 read_file persisted output 链路必须从上游消失，而不是被下游守着。
- 不用“断言 prompt 包含某句提示”代替真实 read/edit 行为测试。
- 不通过降低断言、mock 掉 read_file、硬编码结果制造通过。

## 10. 分阶段实施

### Phase 1：建立 read observation artifact 单一证据链

输入：

- 当前 `read_file` envelope。
- 当前 file evidence scope。
- 当前 runtime storage root。

输出：

- `ReadObservationArtifactStore`。
- file_state read range 带 `exact_artifact_ref`。
- observation commit 后可用 `observation_ref` 恢复 exact text。

禁止：

- 不改 prompt 伪装修复。
- 不恢复删除的 BaseTool rehydration 链。

完成条件：

- repeated read 只有在 exact artifact 存在时才允许 stub。
- content_omitted stub 不能成为下一个 stub 的依据。
- 当前 exact artifact 不存在时，重复 read 返回真实当前窗口，而不是返回“去看之前”的 stub。

### Phase 2：拆开恢复和当前编辑授权

输入：

- Phase 1 artifact store。
- 现有 `read_persisted_tool_result`。
- 现有 `edit_file` guard。

输出：

- generic persisted output 只服务 non-read 工具输出。
- read_file 历史 bytes 由 internal read observation artifact 恢复。
- `edit_file` 独立负责当前磁盘和 active read window 守卫。
- `read_persisted_tool_result` 不再产生 read_file file_state_event。

禁止：

- 不让 `read_persisted_tool_result` 更新 read_file file_state。
- 不让历史 artifact 自动授权 edit。
- 不保留 read_file 旧 rehydration 分支。

完成条件：

- rehydrate 历史 bytes 成功与否不改变 edit guard。
- edit 成功必须依赖当前文件状态和当前 read window。

### Phase 3：修正上下文装配预算

输入：

- context budget preset。
- current context usage。
- file evidence decisions。
- read observation artifact refs。

输出：

- pressure-aware read evidence retention。
- provider replay 不再以 3K preview 作为 code truth。
- 低压力时当前关键 read windows exact visible。

禁止：

- 不用固定 3000 字符截断 read_file 当前证据。
- 不在 provider replay 里偷偷改变 file evidence authority。

完成条件：

- 850K preset、低 usage、当前 edit target read window 不被提前省略。
- 非 read 大输出仍能被通用 ToolResultStore 压缩。

### Phase 4：清理旧链路和旧测试

输入：

- Phase 1 到 Phase 3 已通过。

输出：

- 删除 read_file -> generic content_replacements -> read_persisted_tool_result 的主链路。
- 删除或重写保护旧链路的测试。
- registry/prompt/tool guidance 与新链路一致。

禁止：

- 不保留“兼容旧 read rehydration”的分支。
- 不保留防御已删除工具的代码。

完成条件：

- `rg "persisted_tool_result_tool|BaseTool.*read_persisted|read_persisted_tool_result_for_omitted_read_file"` 没有旧链路残留。
- 只有 non-read generic persisted output 仍引用 `read_persisted_tool_result`。

## 11. 验证命令

实施后至少运行：

```powershell
pytest backend/tests/read_file_authority_chain_regression.py -q
pytest backend/tests/tool_result_projection_regression.py -q
pytest backend/tests/file_state_authority_regression.py -q
pytest backend/tests/runtime_context_compiler_read_evidence_regression.py -q
```

涉及运行链路时，按项目固定端口真实启动：

```powershell
# backend: http://127.0.0.1:8003
# frontend: http://127.0.0.1:3000
```

并用真实任务复现：

1. 读取一个超过 3000 字符但远小于 850K 剩余上下文的代码文件窗口。
2. 触发一次重复读取同范围。
3. 验证第二次不再返回不可还原 stub，或者 stub 带 exact artifact 且 context 已恢复原文。
4. 用该窗口中的 exact `old_text` 执行 `edit_file`。
5. 验证 edit 成功或给出精确 current read 请求，不进入 read loop。

## 12. 明确不做

- 不做 prompt-only 修复。
- 不继续把 read_file 代码证据作为通用 persisted tool output。
- 不恢复 `backend/capability_system/tools/tool_units/persisted_tool_result_tool.py`。
- 不保留两条 read rehydration 主链路。
- 不让 content_omitted stub 继续当作 future read evidence。
- 不用“文件未变”作为省略依据，除非 exact text 仍可见或 exact artifact 可恢复。
- 不为了测试通过而 mock 掉核心 read/edit 行为。

## 13. 预期结果

- 低上下文压力下，当前关键代码窗口不会被乱压。
- `read_file` 重复读不会产生不可还原的 stub 链。
- 空文件读写有明确合法路径，不会被“未读拒绝”误伤。
- `search`、`read`、`rehydrate`、`context assembly`、`edit` 的权力分离清楚。
- 后续 agent 不再因为看不到 exact `old_text` 而卡在重复读和编辑拒绝之间。
