# Prompt 组装与动态分层装载优化计划（2026-06-15）

## 结论

上下文拼接逻辑有结构性问题。

当前链路不是“先分层装载，再渲染成 provider messages”，而是 `RuntimeCompiler` 在 Python list 里手工拼 `message_specs`，再由 `prompt_segment_plan` 和 `prompt_composition` 事后解释这些字符串。也就是说，分层现在主要是标签，不是装载权威。

这会带来四个直接后果：

1. 稳定规则会被拼进动态 preamble。
2. 动态事实会夹带自然语言规则。
3. lifecycle prompt 被动态选择后又标成 `environment_stable`。
4. append-only replay、当前 cursor、用户补充、editor preview 都被粗暴归进 volatile，无法形成清晰缓存层级。

## 现有链路证据

### 1. 主拼接权威在 `RuntimeCompiler`

`compile_task_execution_packet()` 直接手写 message spec 顺序：

- `backend/harness/runtime/compiler.py:1088-1382`

这里同时拼：

- global static
- action schema
- environment + lifecycle
- personality
- agent role
- project instructions
- artifact scope
- tool index
- task contract
- bound task context
- active skills
- bound runtime context
- runtime boundary dynamic
- task state replay
- volatile task state
- user steering updates

这些层级性质不同，但都在一个 list 中按顺序直接拼。

### 2. runtime payload 只是 `preamble + title + JSON`

`build_runtime_payload_message_spec()` 最终调用：

- `backend/prompt_composition/runtime_fragments.py:25-50`

实际渲染是：

```text
preamble
title
json.dumps(payload)
```

它不理解稳定规则、动态事实、append-only replay、当前 cursor 的边界，只负责拼字符串。

### 3. prompt composition 是 shadow，不是主装载权威

`_render_model_messages_from_prompt_composition()` 用 composition projection 重渲染，但 projection 本身来自已经生成好的 `message_specs`：

- `backend/harness/runtime/compiler.py:3287-3318`
- `backend/prompt_composition/fragments.py:40-84`
- `backend/prompt_composition/renderer.py:22-126`

因此 prompt composition 目前是解释器和诊断器，不是第一生产者。

### 4. append-only replay 被错误归类为动态碎片

`RUNTIME_SOURCE_KIND_BY_SEGMENT_KIND` 已经把 `task_state_replay_entry` 定义为 `runtime_task_state_replay`：

- `backend/prompt_composition/tracing.py:23-37`

但 `runtime_source_kind_for_segment()` 先判断 `cache_role == volatile`，导致 replay 实际被归成 `dynamic_context_fragment`：

- `backend/prompt_composition/tracing.py:98-106`

这说明动态分层在 tracing 层也被打平了。

## 目标架构

采用一条清晰权威链：

```text
PromptSources
-> PromptSlotPlan
-> RuntimeContextLoadPlan
-> SegmentMaterializer
-> ProviderMessageProjection
-> RuntimeInvocationPacket
```

各层职责：

| 层级 | 职责 |
| --- | --- |
| PromptSources | 注册 prompt、任务合同、工具目录、项目规则、运行态事实的原始来源 |
| PromptSlotPlan | 决定哪些 slot 应该出现，以及 slot 的权威层级 |
| RuntimeContextLoadPlan | 决定动态上下文按哪些层级装载、预算和顺序 |
| SegmentMaterializer | 将每个 slot 渲染成模型消息，禁止跨层混拼 |
| ProviderMessageProjection | 只做 provider 兼容投影，不重新决定语义 |
| RuntimeInvocationPacket | 保存最终模型输入和可审计 manifest |

## 新分层

### Stable Prefix

稳定前缀只放长期或任务级稳定规则：

1. `global_static`
2. `runtime_protocol_stable`
3. `action_schema_stable`
4. `environment_stable`
5. `lifecycle_stable`
6. `agent_stable`
7. `project_instructions_stable`
8. `tool_catalog_stable`
9. `artifact_scope_stable`
10. `task_contract_stable`
11. `file_evidence_policy_stable`

要求：

- 不含当前 invocation id、event offset、tool observation、editor preview、runtime_status。
- 不含动态拼出来的自然语言规则。
- 用户任务约束必须在 `task_contract_stable`。

### Append-Only Task Evidence

单独装载任务已发生证据：

1. `task_state_replay_append_only`
2. `tool_observation_replay_append_only`
3. `file_read_window_replay_append_only`

要求：

- 已有条目字节稳定，只允许尾部追加。
- 位于 stable task prefix 之后、current cursor 之前。
- 不和当前 volatile cursor 混在一起。
- tracing 必须识别为 `runtime_task_state_replay`，不能归成普通 `dynamic_context_fragment`。

### Current Runtime Cursor

只放当前最新状态：

1. `runtime_boundary_current`
2. `task_state_cursor_current`
3. `file_state_cursor_current`
4. `read_resource_cursor_current`
5. `runtime_control_signals_current`

要求：

- 只表达当前事实。
- 不携带“必须/不要/只能”等规则文本。
- 文件读取策略只通过结构化字段表达：covered、stale、missing、rehydrate_ref、do_not_repeat_range。

### User/Editor Volatile

单独放用户和编辑器输入：

1. `current_user_request`
2. `pending_user_steers`
3. `editor_context_snapshot`

要求：

- `pending_user_steers` 只放用户原文和 ids。
- 处理规则进入 stable lifecycle，不放在 user role 动态 payload。
- editor preview 只能是证据，不扩大权限，不当作完整文件事实。

### Active Skills

`active_skills` 保持独立动态层：

- skill body 可以很大，而且由本轮激活决定。
- 不能插在 task stable prefix 中间。
- 位置应在 stable rules 后、append-only replay 前或 current cursor 前，保持明确。

## 具体修复项

### 阶段 1：修正任务合同稳定投影

文件：

- `backend/harness/runtime/task_contract_manifest.py`

改动：

- `project_task_contract_for_prompt()` 输出 canonical `working_scope`。
- 包含：
  - `target_objects`
  - `workspace_refs`
  - `source_refs`
  - `excluded_scope`
  - `known_constraints`
- `constraints` 保留为顶层兼容输入，但不能替代 `working_scope.known_constraints`。

验收：

- 最近任务中 `known_constraints` 能出现在 `task_contract_stable`。
- 用户明确“不要反复读取”类约束不再只依赖动态事实。

### 阶段 2：新增 PromptSlotPlan 主装载路径

文件：

- `backend/prompt_composition/planner.py`
- `backend/prompt_composition/models.py`
- `backend/harness/runtime/compiler.py`

改动：

- 让 compiler 先构建 slot plan，而不是先构建扁平 message_specs。
- 每个 slot 带：
  - `layer`
  - `authority_class`
  - `cache_tier`
  - `dynamic_tier`
  - `source_ref`
  - `render_contract`
- `message_specs` 由 slot materializer 生成。

验收：

- `prompt_composition.shadow_mode` 不再是事实上的唯一解释层；主链路以 slot plan 为输入。
- 每个 model message 都能追溯到一个 slot。

### 阶段 3：拆分 environment 与 lifecycle

文件：

- `backend/prompt_composition/section_renderer.py`
- `backend/harness/runtime/compiler.py`
- `backend/harness/runtime/environment_prompt_controller.py`

改动：

- `render_environment_instruction()` 不再合并 lifecycle prompt。
- 新增 `render_lifecycle_instruction()` 或 lifecycle slot materializer。
- `environment_stable` 只包含环境说明和环境规则。
- `lifecycle_stable` 单独承载生命周期规则。
- 如果 lifecycle selection 依赖当前工具或 action availability，selection 结果必须进入对应 runtime metadata，不伪装成 session-stable。

验收：

- `environment_stable.source_ref` 不再混入 `environment.coding.lifecycle.*`。
- lifecycle 有独立 segment 和 cache/layer 诊断。

### 阶段 4：拆 runtime dynamic preamble

文件：

- `backend/harness/runtime/compiler.py`

改动：

- `_runtime_projection_instruction()` 不再输出稳定协议规则。
- 稳定规则迁入：
  - `runtime_protocol_stable`
  - `lifecycle_stable`
  - `file_evidence_policy_stable`
- `task_runtime_boundary_dynamic` 只保留当前事实 JSON。

验收：

- `task_runtime_boundary_dynamic` 不再出现大量“必须/不要/只能”的自然语言规则。
- 规则存在于 stable slot。

### 阶段 5：动态上下文分级装载

文件：

- `backend/harness/runtime/dynamic_context/manager.py`
- `backend/harness/runtime/dynamic_context/models.py`
- `backend/harness/runtime/dynamic_context/task_state_projector.py`
- `backend/prompt_composition/tracing.py`
- `backend/harness/runtime/prompt_segment_plan.py`

改动：

- 将动态上下文拆成：
  - `append_only_replay`
  - `current_runtime_cursor`
  - `file_evidence_cursor`
  - `user_editor_volatile`
- `task_state_replay_entry` 不再被 `cache_role=volatile` 抢先归为 `dynamic_context_fragment`。
- 新增 append-only cache/lifecycle 标识，保持旧 replay 的字节稳定和顺序稳定。

验收：

- replay、cursor、editor/user volatile 在 segment plan 中是不同层。
- cache boundary diagnostics 能显示 append-only 层级。

### 阶段 6：清理动态 payload 内规则文本

文件：

- `backend/harness/runtime/bound_task_context.py`
- `backend/harness/runtime/dynamic_context/task_state_projector.py`
- `backend/harness/runtime/dynamic_context/tool_result_projector.py`
- `backend/harness/runtime/compiler.py`

改动：

- 移除或改写动态 payload 中的自然语言规则字段：
  - `restore_policy.file_precision`
  - `decision_boundary`
  - `instruction`
  - `reliability_note`
  - `handling_rules`
  - `required_completion_gate`
- 替换为：
  - `policy_ref`
  - `decision_code`
  - `reason_code`
  - `evidence_ref`
  - `rehydration_ref`

验收：

- 动态上下文只提供事实和结构化决策码。
- 模型行为规则来自 stable prompt/contract。

### 阶段 7：文件读取准入硬化

文件：

- `backend/harness/loop/admission.py`
- `backend/harness/loop/task_executor.py`
- `backend/runtime/tool_runtime/native_tools.py`

改动：

- 对 `read_file` 请求做 file evidence admission：
  - 覆盖且非 stale 的范围不允许重复 read_file。
  - exact omitted content 需要时返回 rehydrate 指引或调用专用 rehydrate 工具。
  - stale、changed、missing、uncovered 才允许重新读取。
- 这不是 prompt 提示，而是执行准入。

验收：

- 模型再次请求已覆盖非 stale 窗口时，后端不会真实重复读。
- 观察返回告诉模型使用已有 evidence/rehydrate。

## 最终验收标准

1. `task_contract_stable` 包含用户明确约束。
2. 稳定规则不再只存在于 dynamic preamble。
3. environment、lifecycle、runtime protocol、task contract、file evidence policy 各有独立 slot。
4. 动态上下文按 append-only replay、current cursor、file cursor、user/editor volatile 分层。
5. prompt cache 诊断能看出各层 prefix 顺序。
6. 重复读取由 admission 阻止，不靠模型自觉。
7. 实际 runtime packet 中每个 model message 都能追溯到明确 slot 和 authority。

## 执行顺序

先做阶段 1、3、4、5，因为它们修正 prompt 输入结构。  
再做阶段 6 清理动态规则文本。  
最后做阶段 7，把文件读取策略从 prompt 建议升级为 runtime 准入。

