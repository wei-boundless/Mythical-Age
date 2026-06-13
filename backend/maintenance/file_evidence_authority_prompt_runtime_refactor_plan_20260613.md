# File Evidence Authority 与 Prompt Runtime 疏通修复计划

日期：2026-06-13

## 1. 计划状态

状态：已实施并通过聚焦回归验证。

本计划用于修复 agent 在已有文件证据时仍持续 `read_file` 的结构性问题。目标不是在某个 prompt 里追加“不要重复读取”，而是把文件证据裁决权收回到单一权威链路，让 prompt、动态上下文、provider transcript replay、rehydration plan 和工具结果投影都遵循同一套规则。

实施结果：

- 已新增 `file_evidence_decisions` 动态投影，明确 `reuse_current_window`、`rehydrate_existing_window`、`read_missing_window`、`read_after_stale`。
- 已让 `read_resource_state` 和 `bound_task_context` 引用该证据决策，不再自行制造读文件策略。
- 已将 provider protocol 大工具输出标记为 replay evidence，并要求通过 `file_evidence_decisions` 判断复用、恢复或最小重读。
- 已统一 prompt 中的硬读取口径为“必须具备当前有效读窗证据”。
- 已补充回归测试并通过聚焦验证。

目标行为应接近 Codex / Claude Code 一类成熟 coding agent：

```text
定位候选
-> 读取必要窗口
-> 记录当前有效文件证据
-> 复用未过期证据推进判断、编辑或验证
-> 只有缺失、过期、文件变更或目标行未覆盖时才再次读取
```

## 2. 直接结论

当前问题不是模型“笨”或工具单点失败，而是读取证据的决策权被拆散了：

- `FileStateAuthority` 已经记录 read ranges、hash、stale、coverage、next suggested read。
- `read_file` 已经能识别相同范围和 hash，并返回 `content_omitted` / `reusable_result_ref`。
- 但 prompt、动态上下文、工具结果 replay、provider transcript、rehydration plan 仍在用不同语言提示模型“修改前读当前内容”或“preview 不可靠”，没有明确告诉模型哪些窗口已经是当前有效证据。
- 结果是：模型看到旧读取像 preview、候选、风险或不完整内容，于是为了“安全”不断重复读文件。

正确修复方向是建立单向权威链：

```text
Tool Observation
-> FileStateAuthority
-> File Evidence Decision Projection
-> Runtime Prompt / Bound Context / Provider Replay
-> Model Turn Decision
```

其中只有 `FileStateAuthority` 及其派生的 evidence decision 可以裁决某个文件窗口是：

- `reuse_current_window`
- `rehydrate_existing_window`
- `read_missing_window`
- `read_after_stale`

其他层只能引用这个裁决，不再自己发明“必须重读”的规则。

## 3. 当前执行链路

与本问题直接相关的主链路如下：

```text
native read_file / write_file / edit_file
-> ToolResultEnvelope.file_state_events
-> FileStateAuthorityStore.apply_observation
-> FileStateAuthority.projection
-> DynamicContextManager
-> TaskStateProjector.file_state / read_resource_state
-> BoundTaskContext.known_task_files / rehydration_refs / restore_policy
-> RuntimeCompiler provider protocol replay
-> prompt_library rules / tool prompts / environment lifecycle prompts
-> 模型决定下一步
```

关键代码位置：

- `backend/runtime/tool_runtime/native_tools.py`
  - `read_file` 执行、重复窗口 hash 检测、`content_omitted` stub。
- `backend/runtime/tool_runtime/tool_result_envelope.py`
  - 从工具结果推导 `file_state_events`。
- `backend/runtime/memory/file_state_authority.py`
  - 文件状态权威，记录读取窗口、写入事件、stale、coverage、next suggested read。
- `backend/runtime/memory/file_state_store.py`
  - 按 `task_run_id` 持久化文件状态。
- `backend/harness/runtime/dynamic_context/task_state_projector.py`
  - 将 file state 投影给模型；当前需要升级为 evidence decision。
- `backend/harness/runtime/dynamic_context/tool_result_projector.py`
  - 工具结果、content range、rehydration plan 投影。
- `backend/harness/runtime/dynamic_context/replacement_store.py`
  - 大工具输出替换记录；不得泄露内部 `replacement:` 引用。
- `backend/harness/runtime/bound_task_context.py`
  - 任务恢复上下文、known files、rehydration refs、restore policy。
- `backend/harness/runtime/compiler.py`
  - provider protocol transcript replay 与大工具输出压缩。
- `backend/prompt_library/rules.py`
- `backend/prompt_library/tool_prompts.py`
- `backend/prompt_library/io_capability_prompts.py`
- `backend/prompt_library/worker_prompts.py`
- `backend/prompt_library/environment_lifecycle_prompts.py`
  - 需要统一“当前有效读窗证据”口径。

## 4. 已确认的问题

### 4.1 文件状态有权威，但模型可见裁决不够明确

`FileStateAuthority` 已有足够结构：

- `read_ranges`
- `content_sha256`
- `content_omitted`
- `previous_observation_ref`
- `reusable_result_ref`
- `stale`
- `coverage`
- `next_suggested_read`

但 `read_resource_state` 目前偏弱，仍然写着模型自行判断是否需要更多上下文。这会让模型把“已有窗口”理解成普通历史事实，而不是当前有效证据。

目标修复：

- 增加 `file_evidence_decisions`，明确每个文件的可执行证据状态。
- 对已覆盖且未过期窗口显式投影 `reuse_current_window`。
- 对被省略但 hash 未变的窗口投影 `rehydrate_existing_window`。
- 对缺失范围才投影 `read_missing_window`。
- 对写入或编辑后的旧窗口投影 `read_after_stale`。

### 4.2 Prompt 口径仍存在无条件重读倾向

当前 prompt 中存在类似口径：

```text
修改前读取目标当前内容
修改前读到目标当前内容和精确行窗口
旧摘要、旧工具记录只能作为线索，必须重新读取当前事实
```

这些句子在没有 evidence authority 的上下文中是合理的，但在已有未过期 read window 时会诱导重复读取。

目标修复：

统一改为：

```text
修改、行级判断或精确引用前，必须具备当前有效读窗证据。
已有覆盖目标行且未过期的 read_file 窗口可以复用。
只有窗口缺失、过期、文件已变更、目标行未覆盖或 hash 无法确认时，才读取最小必要窗口。
```

搜索、摘要、code structure 和 provider 历史仍只能作为定位线索，不能替代 read window。

### 4.3 Provider transcript replay 会放大历史工具输出

用户关注的“最新消息记录为什么还在很大、为什么一直读文件”，关键不在 public messages，而在 session 的 `api_transcript`：

```text
storage/sessions/session-*.json
-> api_transcript
-> provider protocol replay
-> 历史 tool output / read_file preview 重新进入模型输入
```

如果 replay 把大段旧工具输出继续作为主要上下文，模型会把它理解成“历史材料不完整，需要再读”。

目标修复：

- provider replay 对大工具输出使用 compact evidence note，而不是重复推送大 preview。
- read_file replay 必须标注为 evidence replay，不是新的读取任务。
- replay 中的省略内容只能通过 `tool_result:` rehydration 恢复，不能暴露内部 `replacement:`。
- 如果 file state 证明窗口未过期且覆盖目标，replay 应提示复用或恢复旧窗口，而不是重新读取同一范围。

### 4.4 Rehydration 与 read_file 的边界不够硬

rehydration 只恢复旧工具输出被省略的字节，不等于自动证明文件当前未变。

目标修复：

- rehydration plan 明确：
  - 非代码 omitted output：精确引用前调用 `read_persisted_tool_result`。
  - read_file omitted window：只有 `file_state` 证明 unchanged 且覆盖目标时，恢复窗口可作为当前证据。
  - 文件 stale、changed 或目标行不在 coverage 内时，必须读最小必要窗口。
- `read_persisted_tool_result` 只接受 `tool_result:` 引用。
- 所有模型可见内容禁止出现内部 `replacement:`。

### 4.5 Bound task context 的恢复策略仍需对齐 evidence authority

`BoundTaskContext.restore_policy.file_precision` 已经接近目标，但它仍是文字策略，不是统一 evidence decision。

目标修复：

- `known_task_files` 只表示路径已定位，不表示内容有效。
- `task_files` / `rehydration_refs` 引用 `file_evidence_decisions`。
- `restore_policy` 只描述边界，不再独立决定读还是不读。

## 5. 目标设计

### 5.1 单一权威：File Evidence Decision

新增或扩展动态投影结构：

```json
{
  "kind": "file_evidence_decisions",
  "authority": "runtime.memory.file_state_authority.evidence_decision_projection",
  "files": [
    {
      "path": "backend/harness/runtime/compiler.py",
      "status": "partial",
      "content_sha256": "...",
      "current_windows": [
        {
          "decision": "reuse_current_window",
          "start_line": 2529,
          "end_line": 2849,
          "observation_ref": "obs:...",
          "reusable_result_ref": "tool_result:...",
          "instruction": "Do not repeat this unchanged covered read range."
        }
      ],
      "missing_windows": [
        {
          "decision": "read_missing_window",
          "start_line": 2850,
          "line_count": 240,
          "reason": "target outside current coverage"
        }
      ],
      "stale_windows": []
    }
  ]
}
```

该结构只陈述证据状态和边界，不替模型决定任务语义。模型仍然决定是否编辑、验证、回答或继续读取。

### 5.2 Prompt 统一规则

所有 prompt 层统一成一条规则：

```text
需要代码行级判断、精确引用或编辑时，你必须具备当前有效读窗证据。
read_file 已返回且未被后续写入/编辑标记为 stale、并覆盖目标行的窗口，就是当前有效读窗证据。
不要重复读取同一未变化、已覆盖的窗口。
只有窗口缺失、目标行未覆盖、文件 stale/changed、hash 缺失或证据冲突时，才读取最小必要窗口。
```

禁止再出现无上下文的：

```text
修改前必须读取目标当前内容
旧工具记录一律不能作为当前事实
```

### 5.3 Provider Replay 降权

provider transcript replay 的目标改为：

```text
维持 provider 工具调用协议配对
-> 保留最近必要 assistant/tool turn
-> 大工具输出压缩为 evidence note / rehydration ref
-> 不再把历史 preview 当成主要上下文
```

模型可见 replay note 应表达：

```text
This is provider protocol replay evidence. It preserves tool-call continuity.
For read_file content, use file_evidence_decisions to decide reuse, rehydrate, or read.
Do not repeat unchanged covered read ranges.
```

### 5.4 工具结果投影边界

`ToolResultProjector` 应继续区分：

- `read_file_line_window`
- `code_locator`
- `tool_output_preview`

但 read_file 的 `fresh_read_conditions` 需要与 file state 对齐：

- visible content preview truncated -> 优先 rehydrate，不是直接重新 read_file。
- target_line_outside_visible_range -> 读取缺失窗口。
- content_hash_missing -> 需要当前事实时读取。
- stale/changed -> 读取最小必要窗口。

## 6. 实施计划

### 阶段 1：增加 evidence decision 投影

修改：

- `backend/harness/runtime/dynamic_context/task_state_projector.py`

动作：

- 从 `file_state` 派生 `file_evidence_decisions`。
- `read_resource_state` 引用该结构，弱化“模型自行判断是否需要更多上下文”的旧句子。
- 对同一文件窗口去重，保留最近有效 evidence refs。
- 输出明确字段：
  - `reuse_current_windows`
  - `rehydrate_existing_windows`
  - `read_missing_windows`
  - `read_after_stale_windows`
  - `do_not_repeat_read_ranges`

删除或改写：

- 任何把 `next_suggested_read` 作为主要推进动作的表述。

### 阶段 2：Bound context 对齐

修改：

- `backend/harness/runtime/bound_task_context.py`

动作：

- `task_files` 带入 evidence decision 摘要。
- `rehydration_refs` 只列真实可恢复的 `tool_result:`。
- `restore_policy.file_precision` 改为引用当前有效读窗证据，不再要求已知路径必读。

删除或改写：

- “known path -> use read_file directly before line-level edits” 这类无条件读取口径。

### 阶段 3：Provider protocol replay 压缩

修改：

- `backend/harness/runtime/compiler.py`

动作：

- 对 provider transcript 中的大 tool output 使用 compact evidence note。
- read_file tool replay 加入 evidence replay note。
- 保持 provider-native tool call / tool result 配对，不破坏协议。
- 大输出只提供 `tool_result:` rehydration 引用。

删除或改写：

- replay 中让 preview 看起来像当前主要上下文的表达。

### 阶段 4：Prompt 体系统一

修改：

- `backend/prompt_library/rules.py`
- `backend/prompt_library/tool_prompts.py`
- `backend/prompt_library/io_capability_prompts.py`
- `backend/prompt_library/worker_prompts.py`
- `backend/prompt_library/environment_lifecycle_prompts.py`

动作：

- 将“必须重新读取”改为“必须具备当前有效读窗证据”。
- 保留 search/code_structure 作为 locator-only。
- 保留写后 stale 的最小重读要求。
- 保留外部资料、非代码文档、引用场景的精确来源要求。

删除或改写：

- 无条件“修改前读取目标当前内容”。
- “旧工具记录一律不能作为当前事实”的笼统表达。

### 阶段 5：Rehydration 与 replacement 泄漏清理

修改：

- `backend/harness/runtime/dynamic_context/tool_result_projector.py`
- `backend/harness/runtime/dynamic_context/replacement_store.py`
- `backend/runtime/tool_runtime/native_tools.py`
- `backend/capability_system/tools/tool_units/persisted_tool_result_tool.py`

动作：

- 模型可见 rehydration ref 只允许 `tool_result:`。
- 内部 `replacement:` 只在存储层使用。
- read_file omitted result 的说明改为“恢复旧窗口”，不是“重新读取”。

删除或改写：

- 所有模型可见 `replacement:`。

### 阶段 6：测试与回归

修改或新增：

- `backend/tests/dynamic_prompt_context_projection_test.py`
- `backend/tests/tool_result_projection_regression.py`
- `backend/tests/file_state_authority_regression.py`
- 必要时补充 `backend/tests/context_compaction_api_regression.py`
- 必要时补充 `backend/tests/session_manager_runtime_contract_regression.py`

测试必须覆盖：

1. 已读同一 path/range/hash 时，投影 `reuse_current_window`，且出现 `do_not_repeat_read_ranges`。
2. 省略 read_file 内容且 file state unchanged 时，投影 `rehydrate_existing_window`，不是 `read_missing_window`。
3. 目标行不在 coverage 内时，只建议最小 `read_missing_window`。
4. write/edit 后，旧 read ranges 标记 stale，允许 `read_after_stale`。
5. provider replay 中大工具输出被压缩为 evidence note，不重复塞完整旧输出。
6. prompt 文本不再出现无条件“修改前必须读取目标当前内容”。
7. 模型可见内容中不出现内部 `replacement:`。

## 7. 验收标准

修复完成后，应满足：

- 模型输入中有一个清晰、结构化、可追踪的 file evidence authority artifact。
- 已覆盖且未过期的 read_file window 会被明确标为可复用。
- 只有缺口、stale、changed、hash 缺失或目标行未覆盖时才建议 read_file。
- prompt、tool projection、bound context、provider replay 不再互相冲突。
- `api_transcript` 的历史工具输出不会继续作为大体量主上下文反复进入模型。
- 模型可见 rehydration 引用只使用 `tool_result:`。
- 相关聚焦测试真实通过，没有通过 mock、降低断言或删除失败用例制造通过。

## 8. 验证命令

聚焦验证：

```powershell
pytest backend/tests/tool_result_projection_regression.py backend/tests/dynamic_prompt_context_projection_test.py backend/tests/file_state_authority_regression.py
```

provider transcript 相关修改后追加：

```powershell
pytest backend/tests/context_compaction_api_regression.py backend/tests/session_manager_runtime_contract_regression.py
```

最终静态检查：

```powershell
git diff --check
rg -n "replacement:|修改前必须读取目标当前内容|must read_file before edit|must read source before edit" backend
```

## 9. 不做的事

- 不通过降低 prompt 要求来解决重复读取。
- 不把 search/code_structure 升级成可编辑证据。
- 不让 UI 或前端显示层决定文件证据是否有效。
- 不为旧 prompt 口径保留兼容分支。
- 不通过删除 `api_transcript` 来掩盖 provider replay 设计问题。
- 不让 rehydration 假装文件当前未变；当前性必须来自 file state。

## 10. 风险与处理

- 风险：provider-native tool call 协议要求 assistant/tool message 成对，过度压缩可能破坏模型 API 协议。
  - 处理：只压缩 tool content，不破坏 role、tool_call_id、tool result pairing。

- 风险：prompt 改得过宽会让模型在缺少行级证据时直接编辑。
  - 处理：规则写成“当前有效读窗证据”，并由 evidence decision 指出 coverage / stale / missing。

- 风险：旧测试保护旧字段。
  - 处理：删除保护旧内部形状的断言，改为行为测试：复用、缺口、stale、rehydration、无泄漏。

- 风险：`api_transcript` 存储仍然很大。
  - 处理：本计划优先修复 replay 输入体量和模型行为；若仍需缩小落盘体积，再单独做 session transcript storage compaction，不与本次 evidence authority 混在一起。
