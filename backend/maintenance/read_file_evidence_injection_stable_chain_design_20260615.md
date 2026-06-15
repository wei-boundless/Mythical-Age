# Read File Evidence Injection Stable Chain Design

日期：2026-06-15

状态：正式实施前方案。本文只沉淀链路审查、目标设计和执行计划，不修改运行代码。

## 1. 目的

本方案修复 agent 在编辑任务中反复 `read_file`、拿到 `content_omitted` stub 后不进入编辑的结构性问题。

要修正的系统性质不是“少读几次文件”，而是：

- `read_file` 代码证据必须有唯一主链。
- 历史 exact bytes、当前模型可见正文、当前文件编辑授权必须分层。
- 上下文压缩和 provider replay 不能把代码证据压成不可行动的 preview。
- artifact ref 不能只停在状态表里；如果系统声称可用，就必须被装配成模型可见的 exact text。

最终目标是让运行链保持畅通：

```text
read current exact window
  -> store exact read observation
  -> record current file evidence
  -> inject exact evidence into model packet when needed
  -> model edits with visible old_text
  -> edit_file performs final current-file guard
```

## 2. 当前故障

### 2.1 复现任务事实

相关任务：

```text
task_run_id = taskrun:turn:session-9458b9376ed8437e:40:199feb77
session_id = session-9458b9376ed8437e
target_file = fps_game.html
```

关键状态文件：

- `storage/runtime_state/events/taskrun_turn_session-9458b9376ed8437e_40_199feb77.jsonl`
- `storage/runtime_state/executions/taskrun_turn_session-9458b9376ed8437e_40_199feb77.json`
- `storage/runtime_state/file_state/taskrun_turn_session-9458b9376ed8437e_40_199feb77.json`

从执行记录可见：

- `fps_game.html` 已被写入完整文件。
- 文件状态中已有 `exact_artifact_ref`，例如 `read_observation:84f397ad7985b6c61d7ddeee35521513`。
- 后续 `read_file` 多次返回 `status=reused_current_window`、`content_omitted=true`。
- 模型曾调用 `read_persisted_tool_result`，但传入 `toolobs:...` 这类 dynamic-context 内部 ref，被 `invalid_rehydration_replacement_id` 拒绝。
- 执行记录里没有稳定进入 `edit_file` 主路径，说明模型没有拿到可编辑的 exact `old_text`。

### 2.2 表层表现

模型反复读：

```text
read_file -> "reused current evidence" stub
read_persisted_tool_result -> invalid replacement id
read_file -> "reused current evidence" stub
...
```

这不是模型“不想编辑”。它被放进了一个不可行动状态：

- 系统告诉它“已有当前读窗，不要重复读”。
- 系统又没有把 exact 正文放进当前模型输入。
- 恢复工具又不是 read observation artifact 的恢复工具。
- 模型无法构造 `edit_file.old_text`，只能继续读。

### 2.3 深层根因

根因是三种概念被混成一个字段或一条链：

| 概念 | 当前混用 | 正确归属 |
| --- | --- | --- |
| 曾经从磁盘读到 exact bytes | `visible_exact`、`exact_artifact_ref`、`content_omitted` 混在 file_state | `ReadObservationArtifactStore` |
| 当前模型输入是否能看见 exact text | 被 file_state 的 `visible_exact` 间接推断 | compiler / packet-level injection |
| 当前是否允许编辑 | 被 rehydration / read state 间接影响 | `edit_file` current-file guard |

最关键的错误是：`visible_exact` 作为持久 file_state 字段会过期。一次 read 调用曾经返回过正文，不代表后续上下文压缩、provider replay 或动态投影后，模型当前仍能看见正文。

## 3. 源码证据

### 3.1 read_file 已写 artifact，但随后仍自我省略

`backend/runtime/tool_runtime/native_tools.py`：

- `NativeReadFileTool` 在真实读取后写 read observation artifact：约 `364`、`453` 行。
- artifact 字段写入 tool result：约 `382`、`471` 行。
- 随后仍调用 `_unchanged_previous_read_window(...)`：约 `383`、`472` 行。
- 命中后把 `visible_exact` 设为 `False` 并把返回正文替换成 `_file_unchanged_read_stub(...)`：约 `395-396`、`484-485` 行。
- `_unchanged_previous_read_window(...)` 位于约 `747` 行。
- `_file_unchanged_read_stub(...)` 位于约 `811` 行。

这说明当前工具层同时做了两件冲突的事：

```text
observe exact current bytes
decide model does not need exact bytes
```

成熟链路里，`read_file` 只能负责 observe。是否压缩、是否注入、是否可见，属于 context assembly。

### 3.2 Artifact store 是恢复历史 bytes 的正确位置

`backend/runtime_objects/read_observation_artifacts.py`：

- `ReadObservationArtifactStore` 位于约 `16` 行。
- `write_read_observation(...)` 位于约 `22` 行。
- `artifact_ref = read_observation:<digest>` 位于约 `60` 行。
- `bind_observation_ref(...)` 位于约 `103` 行。
- `resolve_ref(...)` 位于约 `128` 行。
- `read_text(...)` 位于约 `153` 行。

这条链已经具备 exact bytes 存储能力，但目前缺少 runtime compiler 对 `read_observation:` 的专用展开阶段。

### 3.3 file_state 已记录 artifact，但不应拥有当前可见性

`backend/runtime/memory/file_state_authority.py`：

- `FileReadRange` 已有 `content_omitted`、`exact_artifact_ref`、`artifact_ref_status`、`visible_exact` 字段：约 `18-23` 行。
- `exact_coverage` 已存在：约 `95-97`、`507-508` 行。

问题不在于 artifact 字段缺失，而在于：

- `exact_coverage` 只证明 store 中有 exact bytes 或 read range exact。
- 它不能证明当前模型 packet 中能看到 exact text。
- `visible_exact` 不应由 file_state 持久保存为长期真值。

### 3.4 task_state 投影把 artifact 可恢复误当成当前证据

`backend/harness/runtime/dynamic_context/task_state_projector.py`：

- `_file_evidence_decisions_projection(...)` 位于约 `1245` 行。
- `current_read_evidence = bool(reuse_windows or rehydrate_windows)` 位于约 `1269` 行。
- `inject_read_artifact_windows` 位于约 `1273` 行。
- `_inject_read_artifact_window_decision(...)` 位于约 `1315` 行。
- `_segment_visible_exact(...)` 位于约 `1330` 行。
- `_segment_has_exact_artifact(...)` 位于约 `1335` 行。
- `_segment_exact_available(...)` 位于约 `1343` 行。

当前投影已经识别出 `inject_read_artifact`，但它只产出 ref 和决策元数据。没有证明 compiler 已经把 artifact 正文注入下一轮模型输入。

因此：

```text
artifact_available != model_visible_exact
```

### 3.5 bound_task_context 只携带恢复提示，不携带 exact text

`backend/harness/runtime/bound_task_context.py`：

- `inject_read_artifact_windows` 被收进 bounded decision：约 `238` 行。
- `_bounded_decision_windows(...)` 保留 `exact_artifact_ref`：约 `262` 行。

它仍然只是传递 ref。它不是 artifact text injection。

### 3.6 compiler 目前没有 read_observation 专用注入消费者

`backend/harness/runtime/compiler.py`：

- 有普通 graph `artifact_payloads` 处理：约 `4903-4935`、`5184-5188` 行。
- 这些路径处理普通文件 artifact payload，不认识 `read_observation:` store。
- compiler 顶部 provider replay note 已把 read_file exact 依赖说成“visible or backed by injected read artifact”：约 `91-93` 行。

问题是：文案提到了 injected read artifact，但代码中没有对应的 read observation injection 主链。

### 3.7 prompt 已开始纠偏，但 prompt 不能代替链路

`backend/prompt_library/rules.py`：

- 已说明 non-code omitted output 才走 `read_persisted_tool_result`：约 `63-64` 行。
- 已说明代码编辑必须依赖 exact read evidence 或 read observation artifact 注入：约 `65-66` 行。

`backend/prompt_library/tool_prompts.py`：

- 已说明 `read_persisted_tool_result` 不用于恢复 `read_file` 代码证据：约 `84-87` 行。

这些提示方向是对的，但 prompt 不能弥补“artifact 正文没有装进模型 packet”的断边。

### 3.8 当前测试仍有旧行为残留

`backend/tests/read_file_authority_chain_regression.py`：

- `test_native_read_file_preserves_intent_and_omits_unchanged_window`：约 `130` 行。
- `test_native_read_file_session_scope_omits_unchanged_window`：约 `187` 行。
- `test_native_read_file_omits_subwindow_covered_by_larger_current_read`：约 `242` 行。

这些测试保护了“read_file 重复读返回 omitted stub”的旧行为。目标链路下，这类测试必须删除或重写。

## 4. 成熟 agent 对照结论

本地此前已审查成熟实现：

- Claude Code：Read 输出有 read-specific budget，重复读 stub 的前提是 earlier exact Read tool_result 仍在 conversation 中；compact 后会重新注入真实文件内容。
- OpenAI Codex：raw observation 和模型可见 truncation 分离；大输出截断有明确 omitted metadata；compaction 是显式 handoff。
- Pi coding-agent：read 截断由 read 工具自身给 continuation，不能被 generic projection 隐式改写。
- opencode：view/read 与 edit 分离，edit 前检查当前磁盘、mtime、old string 唯一性。

可借鉴的稳定原则：

1. Search 只定位候选，不是代码事实。
2. Read 是代码证据观察，不走 generic persisted output 主链。
3. Read 可以窗口化，但窗口内容必须 exact。
4. 省略必须有可见 exact text 或真正可注入 artifact 作为前提。
5. 历史恢复不能授权当前 edit。
6. edit_file 是最终当前文件守卫。

本项目不能只复制 Claude 的 stub 文案。Claude 的 stub 成立条件是 earlier exact Read tool_result 仍可见，并且 compact 后会恢复真实文件内容。本项目目前没有这条 guarantee，因此不能让 `read_file` 自己返回 stub。

## 5. 设计决策

### 5.1 决策一：read_file 永远返回当前 exact 窗口

在目标链路中，`read_file` 不再返回 `file_unchanged/content_omitted` stub。

原因：

- 工具执行时无法可靠知道下一轮模型 packet 是否仍能看到之前 exact text。
- file_state 中的可见性会随着压缩和投影变化。
- 让 observe 层决定省略，会重复制造不可行动状态。

允许的优化只有一种：context assembly 可以在后续 packet 中省略旧 read text，但必须同时完成 read artifact injection 或明确要求重新 `read_file`。

### 5.2 决策二：`visible_exact` 从 file_state 真值降级

目标语义：

- file_state 记录 `returned_exact` 或 `has_exact_artifact`。
- 当前 packet 是否可见 exact text，只能由 compiler 产出 `visible_exact_in_packet`。

兼容迁移：

- 旧 `visible_exact=true` 在迁移期只能解释为“原始 read tool result 曾返回 exact text”。
- 不能解释为“当前模型仍能看到 exact text”。

### 5.3 决策三：新增 Read Evidence Injection 阶段

新增 compiler 内部阶段：

```text
ReadEvidenceInjector
  input:
    file_state exact ranges
    task_state read artifact candidates
    ReadObservationArtifactStore
    context budget policy
    current task target paths / edit intent
  output:
    exact read evidence model segment
    packet-level injection receipts
    read_required decisions when injection cannot happen
```

这是唯一允许把 `read_observation:` exact bytes 变成模型可见 text 的层。

### 5.4 决策四：`read_persisted_tool_result` 只服务 non-read generic output

禁止：

```text
read_file -> ToolResultStore -> read_persisted_tool_result -> code evidence
```

允许：

```text
terminal / web / non-code large output -> ToolResultStore -> read_persisted_tool_result
```

### 5.5 决策五：edit_file 仍是唯一写入授权层

Read artifact injection 只解决“模型看见 exact old_text”。

它不能直接授权 edit。

`edit_file` 仍必须检查：

- 当前文件存在性。
- content hash / mtime 是否匹配。
- active exact read range 是否覆盖 old_text span。
- old_text 在当前磁盘内容中是否唯一。
- 写入后旧 read ranges stale。

## 6. 目标链路

### 6.1 正常读取

```text
model -> read_file(path, start_line, line_count, read_intent)
  -> NativeReadFileTool normalizes and reads current disk
  -> returns exact line-numbered text
  -> writes ReadObservationArtifactStore
  -> emits file_state read event with exact_artifact_ref
  -> FileStateAuthorityStore records current exact read range
```

禁止：

- 返回 `content_omitted` stub。
- 把 `previous_observation_ref` 当可恢复 bytes。
- 让 `read_persisted_tool_result` 参与 read_file evidence。

### 6.2 后续上下文装配

```text
compiler -> ReadEvidenceInjector
  -> selects current edit-target / recently needed read windows
  -> reads exact text from ReadObservationArtifactStore
  -> verifies scope/path/range/hash/mtime metadata
  -> injects exact text into a dedicated model-visible segment
  -> emits injection receipt
```

如果不能注入：

```text
artifact missing / stale / hash mismatch / budget exceeded
  -> do not claim current_read_evidence
  -> emit read_required decision for minimal current window
```

### 6.3 模型决策

模型只能在以下条件下做行级编辑：

- 本轮刚收到 `read_file` exact text。
- 本轮 packet 中包含 `read_evidence_injection` exact text。

不能从以下材料编辑：

- search snippet
- code_structure summary
- provider replay preview
- content_omitted stub
- artifact ref without injected text
- generic persisted output

### 6.4 编辑

```text
model -> edit_file(path, old_text, new_text)
  -> edit_file reads current disk
  -> checks current file_state exact read evidence
  -> checks old_text span covered by current exact read range
  -> checks old_text unique
  -> writes file
  -> marks old read ranges stale
  -> records write/edit event
```

### 6.5 Provider replay / compaction

Provider replay 只负责协议连续性：

```text
provider_protocol_history -> tool call/result continuity preview
```

它不承载代码事实。

如果 replay/compaction 导致 read text 不再可见，下一轮必须通过 ReadEvidenceInjector 注入 exact artifact，或要求重新 `read_file`。

## 7. 数据模型变更

### 7.1 ReadObservationArtifact

保留现有 store，补齐语义：

```json
{
  "artifact_ref": "read_observation:<digest>",
  "task_run_id": "...",
  "scope_kind": "task_run|session",
  "scope_id": "...",
  "path": "fps_game.html",
  "start_line": 1,
  "end_line": 769,
  "total_lines": 769,
  "has_more": false,
  "content_sha256": "...",
  "text_sha256": "...",
  "mtime_ns": 123,
  "size_bytes": 123,
  "source_tool_name": "read_file",
  "content_omitted": false,
  "authority": "runtime_objects.read_observation_artifact.v1"
}
```

空文件合法：

```json
{
  "text": "",
  "start_line": 1,
  "end_line": 0,
  "total_lines": 0,
  "size_bytes": 0
}
```

### 7.2 FileReadRange

目标字段：

```json
{
  "start_line": 1,
  "end_line": 769,
  "observation_ref": "...",
  "content_sha256": "...",
  "mtime_ns": 123,
  "read_intent": "edit_target",
  "exact_artifact_ref": "read_observation:<digest>",
  "artifact_ref_status": "exact",
  "returned_exact": true,
  "stale": false
}
```

废弃或降级：

- `visible_exact` 不再作为持久当前可见性。
- `content_omitted` 不再由 `read_file` 写入正常 read event。
- `reusable_result_ref` 不再指向 `previous_observation_ref`。

### 7.3 ReadEvidenceInjectionReceipt

新增 packet-level 结构：

```json
{
  "packet_id": "...",
  "path": "fps_game.html",
  "start_line": 1,
  "end_line": 769,
  "artifact_ref": "read_observation:<digest>",
  "content_sha256": "...",
  "text_sha256": "...",
  "injected_chars": 32000,
  "truncated": false,
  "visible_exact_in_packet": true,
  "authority": "harness.runtime.compiler.read_evidence_injection"
}
```

如果未注入：

```json
{
  "path": "fps_game.html",
  "start_line": 1,
  "line_count": 240,
  "decision": "read_required",
  "reason": "artifact_missing|artifact_stale|budget_exceeded|hash_mismatch"
}
```

## 8. 权力边界

| Layer | Owner | Allowed decision | Forbidden decision |
| --- | --- | --- | --- |
| Locate | search/glob/code_structure | locate candidate paths/ranges | treat snippets as edit evidence |
| Observe | read_file | read current disk and return exact window | decide model can omit current window |
| Store | ReadObservationArtifactStore | persist exact historical bytes | authorize current edit |
| Record | FileStateAuthorityStore | record current file read/write state | claim model packet visibility |
| Project | task_state/tool_result projector | expose candidates and evidence state | turn artifact availability into visible text |
| Assemble | RuntimeCompiler ReadEvidenceInjector | inject exact artifact text or demand read | use generic preview as code truth |
| Decide | model | choose edit/tool call from visible exact evidence | edit from refs, summaries, stubs |
| Authorize | edit_file | current disk/read-window/old_text guard | trust historical artifact alone |
| Present | UI/monitor | show state and diagnostics | rewrite evidence authority |

## 9. 断边审计矩阵

| Line | Current status | Broken edge | Required fix |
| --- | --- | --- | --- |
| L1 read request -> exact result | Broken | `read_file` may replace exact text with stub | remove native unchanged stub path |
| L2 exact result -> artifact store | Connected | artifact written by read tool | keep and test empty/non-empty |
| L3 artifact -> file_state | Partially connected | alias/event exists, but `visible_exact` semantics wrong | persist artifact exactness, not packet visibility |
| L4 file_state -> task_state | Partially connected | artifact availability becomes `current_read_evidence` | split `artifact_available` from `visible_exact_in_packet` |
| L5 task_state -> compiler injection | Missing | `inject_read_artifact_windows` has no text injector | add ReadEvidenceInjector |
| L6 compiler injection -> model packet | Missing | no dedicated exact read evidence segment | add preserved volatile segment |
| L7 model -> edit_file | Blocked by missing old_text | model only sees stub/ref | inject text or return exact read result |
| L8 edit_file -> write/stale | Connected | guard exists | keep as final authority |
| L9 non-read persisted output | Connected but must stay scoped | generic output uses `read_persisted_tool_result` | ensure read_file never enters this route |
| L10 compaction/provider replay | Partially connected | replay preview can be mistaken for truth | mark protocol-only; rely on injection/read_required |

Severity:

- L5/L6 are P1: exact evidence exists but is not transported to the model.
- L1 is P1: observe layer makes an assembly decision.
- L3/L4 are P2: persistent state semantics can drift under compaction.

## 10. 模块实施计划

### 10.1 `backend/runtime/tool_runtime/native_tools.py`

Action:

- Delete or disable `_unchanged_previous_read_window(...)` from normal `read_file` flow.
- Delete `_file_unchanged_read_stub(...)` if no longer referenced.
- `NativeReadFileTool` always returns `window.text` for successful reads.
- Continue writing `ReadObservationArtifactStore`.
- Emit `returned_exact=true`, `exact_artifact_ref`, `artifact_ref_status=exact`.
- Do not emit `file_unchanged/content_omitted/previous_observation_ref/reusable_result_ref` for normal read results.
- Keep `NativeReadPersistedToolResultTool` scoped to non-read generic persisted output.

Done condition:

- Repeated `read_file` on unchanged file returns exact text.
- No runtime path returns `read_file reused current evidence ... content omitted`.

### 10.2 `backend/runtime_objects/read_observation_artifacts.py`

Action:

- Keep as exact read bytes store.
- Add helper for bounded read payload:
  - `read_payload(ref) -> metadata + text`
  - validates store path and metadata hash.
- Keep empty artifact support.

Done condition:

- `read_observation:` can be resolved by artifact ref, observation ref, tool result ref where bound.
- Empty file returns empty string with valid metadata, not missing artifact.

### 10.3 `backend/runtime/memory/file_state_authority.py`

Action:

- Rename or reinterpret persistent `visible_exact` as `returned_exact`.
- Keep `exact_coverage` based on exact artifact availability.
- Do not use file_state to assert current model visibility.
- Exclude stale ranges from exact coverage.

Done condition:

- File state can answer “do we have exact bytes in store?”.
- File state cannot answer “does current packet contain the bytes?”.

### 10.4 `backend/runtime/memory/file_state_store.py`

Action:

- Continue binding observation refs to read artifacts.
- Ensure aliases are bound only for exact read events.
- Preserve artifact refs during serialization.

Done condition:

- Cross-invocation artifact lookup by observation ref works.
- Write/edit makes old ranges stale without deleting historical artifacts.

### 10.5 `backend/runtime/tool_runtime/tool_result_envelope.py`

Action:

- Pass through `exact_artifact_ref`, `artifact_ref_status`, `returned_exact`.
- Stop treating omitted read stubs as active exact read events.
- Do not generate read file_state_event from `read_persisted_tool_result`.

Done condition:

- `read_file` event means exact current observation.
- Generic persisted rehydration does not mutate read state.

### 10.6 `backend/harness/runtime/dynamic_context/tool_result_projector.py`

Action:

- Keep existing rule that `read_file` skips generic `ToolResultStore.apply_budget`.
- Remove remaining read_file-oriented `read_persisted_tool_result` preference.
- For read_file projection:
  - exact current text in preview when present.
  - content_range metadata.
  - read_file_range continuation for partial windows.
  - no generic content replacement.

Done condition:

- `content_replacements` never has `source_tool_name=read_file`.
- `read_persisted_tool_result` appears only for non-read output.

### 10.7 `backend/harness/runtime/dynamic_context/task_state_projector.py`

Action:

- Replace `current_read_evidence=bool(reuse_windows or rehydrate_windows)` with explicit states:
  - `visible_exact_windows`
  - `artifact_available_windows`
  - `artifact_injection_required_windows`
  - `read_required_windows`
  - `stale_windows`
- `do_not_repeat_read_ranges` only emitted after compiler has an injection receipt or current exact read is in the active model packet.
- Do not let bare `previous_observation_ref` become reusable evidence.

Done condition:

- Artifact availability never tells the model “do not read” unless exact text is visible in packet.

### 10.8 `backend/harness/runtime/compiler.py`

Action:

- Add `ReadEvidenceInjector`.
- Inputs:
  - task_state file evidence decisions.
  - file_state exact ranges.
  - dynamic_context_storage_root.
  - context budget policy.
  - task target paths / edit intent.
- It reads `ReadObservationArtifactStore.read_text(...)`.
- It emits a dedicated system segment:

```text
Task current exact read evidence
```

Payload:

```json
{
  "read_evidence_injections": [
    {
      "path": "...",
      "start_line": 1,
      "end_line": 240,
      "content": "1 | ...",
      "artifact_ref": "read_observation:...",
      "visible_exact_in_packet": true
    }
  ]
}
```

- Segment metadata:
  - `authority_class=read_evidence_injection`
  - `cache_scope=none`
  - `cache_role=volatile`
  - `compression_role=preserve`

Done condition:

- If task_state says artifact injection is required, compiler either injects exact text or emits read_required.
- No packet claims current exact evidence without text.

### 10.9 `backend/harness/runtime/bound_task_context.py`

Action:

- Stop exposing raw `inject_read_artifact_windows` as if model can act on it.
- Include packet-level injection receipts.
- Include read_required windows when injection failed.

Done condition:

- Model sees either exact content or a direct read request, not a dangling artifact ref.

### 10.10 Prompt files

Files:

- `backend/prompt_library/rules.py`
- `backend/prompt_library/tool_prompts.py`
- `backend/prompt_library/environment_lifecycle_prompts.py`
- `backend/prompt_library/worker_prompts.py`

Action:

- Keep non-code persisted-output guidance.
- For code:
  - exact current `read_file` output is usable.
  - exact read evidence injection is usable.
  - artifact refs alone are not usable.
  - provider preview is not usable.

Done condition:

- Prompt matches runtime reality and does not advertise unavailable recovery paths.

## 11. Context budget policy

Add read evidence policy to `context_budget_policy.py` or compiler-local config:

```text
READ_EVIDENCE_TOTAL_EXACT_CHARS = 120000
READ_EVIDENCE_PER_WINDOW_CHARS = 60000
READ_EVIDENCE_LOW_PRESSURE_RATIO = 0.70
READ_EVIDENCE_MEDIUM_PRESSURE_RATIO = 0.90
```

Policy:

- Low pressure: inject current edit-target exact windows up to total budget.
- Medium pressure: inject latest edit-target / failure-repair windows first.
- High pressure: do not silently preview; emit read_required for minimal target windows.
- If a single window exceeds per-window budget, request narrower `read_file` window instead of truncating code and calling it exact.

Important:

- Truncated code payload is not exact evidence.
- A truncated read evidence injection must set `visible_exact_in_packet=false` and include `read_required`.

## 12. Phase plan

### Phase 0：baseline and old-chain inventory

Goal:

- Confirm current old-chain tests and runtime routes.

Commands:

```powershell
rg "content_omitted|_file_unchanged_read_stub|_unchanged_previous_read_window|read_persisted_tool_result_for_omitted_read_file" backend
pytest backend/tests/read_file_authority_chain_regression.py -q
pytest backend/tests/tool_result_projection_regression.py -q
```

Output:

- Baseline failures or old behavior snapshot.

Prohibited:

- Do not edit prompt only.
- Do not add compatibility fallback.

### Phase 1：make read_file exact-only

Goal:

- `read_file` no longer returns omitted stub.

Files:

- `backend/runtime/tool_runtime/native_tools.py`
- `backend/runtime/tool_runtime/tool_result_envelope.py`
- `backend/tests/read_file_authority_chain_regression.py`

Output:

- Rewritten tests:
  - repeated read returns exact text.
  - subwindow read returns exact subwindow text.
  - session scope repeated read returns exact text.

Prohibited:

- Do not keep a disabled-but-reachable old stub path.

### Phase 2：separate persistent exactness from packet visibility

Goal:

- file_state no longer owns current model visibility.

Files:

- `backend/runtime/memory/file_state_authority.py`
- `backend/runtime/memory/file_state_store.py`
- `backend/harness/runtime/dynamic_context/task_state_projector.py`
- tests for file_state and task_state projection.

Output:

- `artifact_available_windows` and `read_required_windows` replace ambiguous `current_read_evidence`.

Prohibited:

- Do not use `visible_exact` from persisted state to suppress reading.

### Phase 3：add ReadEvidenceInjector

Goal:

- compiler injects exact read artifact text into model packet.

Files:

- `backend/harness/runtime/compiler.py`
- optionally new helper: `backend/harness/runtime/read_evidence_injection.py`
- `backend/runtime_objects/read_observation_artifacts.py`
- new tests: `backend/tests/runtime_context_compiler_read_evidence_regression.py`

Output:

- Dedicated exact read evidence segment.
- Injection receipts.
- read_required fallback when injection cannot happen.

Prohibited:

- Do not call `read_persisted_tool_result` for read artifacts.
- Do not inject truncated code as exact.

### Phase 4：bound context and prompt cleanup

Goal:

- model-visible runtime context matches actual injection state.

Files:

- `backend/harness/runtime/bound_task_context.py`
- prompt files listed in section 10.10.

Output:

- No dangling artifact ref presented as actionable evidence.

Prohibited:

- Do not tell the model to use a ref unless exact content is also present or a tool exists for that ref.

### Phase 5：old-chain deletion and tests

Goal:

- Remove old read stub tests and old prompt paths.

Files:

- `backend/tests/read_file_authority_chain_regression.py`
- `backend/tests/tool_result_projection_regression.py`
- `backend/tests/file_state_authority_regression.py`
- `backend/tests/runtime_context_compiler_read_evidence_regression.py`

Required tests:

- repeated read returns exact text.
- read artifact store persists non-empty and empty files.
- artifact available without injection does not emit do-not-repeat.
- compiler injects exact artifact under low pressure.
- compiler emits read_required on missing/stale/hash mismatch/budget exceeded.
- `read_persisted_tool_result` non-read output still works.
- `edit_file` still rejects stale/ambiguous/out-of-window old_text.

### Phase 6：real runtime verification

Goal:

- Reproduce the original failure with a real task and verify no loop.

Fixed ports per project rules:

```text
frontend: http://127.0.0.1:3000
backend:  http://127.0.0.1:8003
api base: http://127.0.0.1:8003/api
```

Scenario:

1. Read a file larger than provider replay preview but smaller than context budget.
2. Trigger a follow-up edit.
3. Confirm model packet contains exact read text or current read_file exact result.
4. Confirm no `read_file reused current evidence` stub appears.
5. Confirm edit proceeds or fails with precise current read request.

## 13. Validation matrix

| Case | Expected result | Test |
| --- | --- | --- |
| repeated same read | exact text returned | native read regression |
| subwindow after larger read | exact subwindow returned | native read regression |
| old artifact available after compaction | compiler injects exact text | compiler read evidence test |
| artifact missing | read_required emitted | compiler read evidence test |
| artifact hash mismatch | read_required emitted | compiler read evidence test |
| artifact too large | narrower read_required, not truncated exact | budget test |
| generic large terminal output | `read_persisted_tool_result` works | projection/native test |
| read_file output large | no generic content replacement | projection test |
| empty file | exact artifact with empty text | artifact/native test |
| edit after current read | succeeds if old_text unique and covered | edit guard test |
| edit after file change | rejected stale | edit guard test |

## 14. Migration and cutover rules

### 14.1 Old path freeze

Immediately after Phase 1:

- No new code may call `_unchanged_previous_read_window`.
- No new prompt may mention read_file recovery through `read_persisted_tool_result`.
- No new test may assert `content_omitted` for read_file normal output.

### 14.2 Shadow period

During Phase 2-3:

- Keep reading existing `visible_exact` field only as legacy `returned_exact`.
- Emit diagnostics when old persisted state contains `content_omitted=true`.
- Do not let old omitted ranges suppress read_file.

### 14.3 Cutover

Promote new chain when:

- compiler injection tests pass.
- old read stub tests are deleted or rewritten.
- real runtime scenario no longer loops.
- scans show no read_file -> read_persisted main path.

### 14.4 Rollback

Rollback trigger:

- compiler injection produces corrupted text.
- edit_file accepts edit without current file guard.
- generic non-read persisted output is broken.

Rollback rule:

- Roll back ReadEvidenceInjector segment and task_state projection changes together.
- Do not restore native read_file stub.
- Fallback behavior is exact `read_file`, not omitted read.

## 15. Prohibited shortcuts

- No prompt-only fix.
- No retained old stub path under “compatibility”.
- No `read_persisted_tool_result` for read_file code evidence.
- No generic content replacement for read_file output.
- No truncated injected code marked exact.
- No `previous_observation_ref` as bytes handle.
- No file_state `visible_exact` as current packet visibility.
- No semantic tests that only assert prompt wording.
- No mocked read/edit core behavior to manufacture green tests.

## 16. File-level checklist

| File | Current role | Action | Done condition |
| --- | --- | --- | --- |
| `backend/runtime/tool_runtime/native_tools.py` | native read/edit tools | remove read stub route; keep edit guard | repeated read exact; no reused-current stub |
| `backend/runtime_objects/read_observation_artifacts.py` | exact read bytes store | add bounded payload helper | compiler can read metadata+text |
| `backend/runtime/tool_runtime/tool_result_envelope.py` | file event inference | read event means exact observation | no omitted read event from rehydration |
| `backend/runtime/memory/file_state_authority.py` | file evidence record | separate exact artifact from packet visibility | no do-not-read based on stale visibility |
| `backend/runtime/memory/file_state_store.py` | state persistence | keep alias binding | artifact lookup survives observation commit |
| `backend/harness/runtime/dynamic_context/tool_result_projector.py` | tool result projection | keep read out of generic persistence | read_file has no content_replacements |
| `backend/harness/runtime/dynamic_context/task_state_projector.py` | runtime evidence projection | split available/injected/required | no dangling artifact as current evidence |
| `backend/harness/runtime/compiler.py` | model packet assembly | add ReadEvidenceInjector segment | exact text or read_required |
| `backend/harness/runtime/bound_task_context.py` | bound runtime context | surface injection receipts | no actionable ref without text |
| `backend/prompt_library/*.py` | model rules/tool guidance | align with new chain | no old read recovery prompt |
| `backend/tests/read_file_authority_chain_regression.py` | native read/edit tests | rewrite old stub tests | target behavior protected |
| `backend/tests/runtime_context_compiler_read_evidence_regression.py` | new compiler tests | add injection/budget/stale cases | missing L5/L6 edge covered |

## 17. Final chain self-audit

### Producer gate

Pass when:

- `read_file` always produces exact text and exact artifact.
- `ReadEvidenceInjector` produces either exact text injection or read_required.

### Identity gate

Pass when:

- `artifact_ref`, `observation_ref`, `task_run_id`, `path`, `start_line`, `end_line`, `content_sha256`, `text_sha256` survive from read through injection receipt.

### Authority gate

Pass when:

- Only compiler can claim `visible_exact_in_packet`.
- Only edit_file can authorize writes.
- ToolResultStore cannot become read evidence authority.

### Transport gate

Pass when:

- `read_observation:` can be resolved only by `ReadObservationArtifactStore`.
- No generic filesystem artifact reader is expected to understand `read_observation:`.

### Consumer gate

Pass when:

- Model sees exact text, not only refs.
- edit_file reads current disk and checks file_state.

### Terminal gate

Pass when:

- Missing/stale/oversized artifact ends in read_required, not loop.
- edit success stales old ranges.
- failed read injection does not emit do-not-repeat.

### Test gate

Pass when:

- Each edge in section 13 has real tests.
- Old stub tests are gone.

## 18. Expected outcome

After implementation:

- The agent will not be trapped in `read_file -> omitted stub -> bad rehydrate -> read_file`.
- Current edit targets remain exact under low context pressure.
- Context compaction has a real recovery path for read evidence.
- `search`、`read`、`artifact restore`、`context assembly`、`edit` 的权力边界清楚。
- The system can maintain stable operation without duplicate read-evidence chains.

