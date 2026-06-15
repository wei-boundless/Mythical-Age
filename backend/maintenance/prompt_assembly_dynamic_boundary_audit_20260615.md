# Prompt 组装动态边界审查（2026-06-15）

## 审查目标

重新审查 runtime prompt 组装逻辑，确认是否把不应放在动态上下文的 prompt、规则或任务约束放进了动态段，导致模型看到的规则漂移、任务约束丢失、反复读取文件或 prompt cache 命中偏低。

## 证据来源

- `backend/harness/runtime/compiler.py`
- `backend/harness/runtime/task_contract_manifest.py`
- `backend/harness/runtime/bound_task_context.py`
- `backend/harness/runtime/dynamic_context/manager.py`
- `backend/harness/runtime/dynamic_context/task_state_projector.py`
- `backend/harness/runtime/environment_prompt_controller.py`
- `backend/prompt_composition/section_renderer.py`
- 运行事件：
  - `storage/runtime_state/events/taskrun_turn_session-9458b9376ed8437e_34_20c7c2a1.jsonl`
  - `storage/runtime_state/events/taskrun_turn_session-9458b9376ed8437e_7_1d695d8e.jsonl`

## 目标分层

成熟 agent 的 prompt 输入应按权威分层：

1. 全局稳定协议：角色、输出协议、动作 schema、控制动作语义、工具调用边界。
2. 会话稳定环境：环境说明、项目规则、固定能力边界。
3. 任务稳定合同：用户目标、任务目标、验收标准、工作范围、用户明确约束、禁止事项、计划锁。
4. 任务运行事实：当前 step、工具观察、文件读窗、覆盖率、stale 状态、待处理用户补充、运行控制信号。
5. 动态证据索引：可复用 observation ref、rehydration ref、缺失/过期窗口、最新编辑器预览。

规则、协议、用户约束不能依赖动态上下文作为唯一来源。动态上下文只能携带“当前事实”和“事实对应的结构化决策”，不能成为工具准入和模型行为规则的唯一权威。

## Findings

### P1：任务合同稳定投影漏掉 `working_scope.known_constraints`

`contract_from_action_request()` 会把模型生成的 `task_contract_seed.working_scope.known_constraints` 规范化进任务合同：

- `backend/harness/loop/task_lifecycle.py:115`
- `backend/harness/loop/task_lifecycle.py:173-179`

但 `project_task_contract_for_prompt()` 投给模型的稳定合同只投影顶层 `constraints`，没有投影 `working_scope`、`known_constraints`、`target_objects`、`excluded_scope`：

- `backend/harness/runtime/task_contract_manifest.py:118-141`

实证：最近任务的 `task_contract_stable` 真实 model message 只有 `user_visible_goal`、`task_run_goal`、`completion_criteria` 等字段，搜索不到：

- `known_constraints`
- `working_scope`
- `不要再反复读取`

这说明“不要反复读取文件，应基于已有代码结构直接修改”这类用户约束进入了合同对象，但没有进入模型可见稳定任务合同。模型后续只能从动态 `file_evidence_decisions` 里看到建议，而看不到用户明确约束。

目标修复边界：

- `task_contract_stable` 必须投影 `working_scope`，至少包括 `target_objects`、`source_refs`、`excluded_scope`、`known_constraints`。
- 顶层 `constraints` 可以保留为兼容输入，但不能替代 canonical `working_scope.known_constraints`。

### P1：运行协议规则被塞进 `task_runtime_boundary_dynamic`

`_runtime_projection_instruction()` 生成大量行为规则，然后作为 `task_runtime_boundary_dynamic` 的 preamble 进入 volatile 段：

- `backend/harness/runtime/compiler.py:4222-4443`
- `backend/harness/runtime/compiler.py:1308-1325`

这些内容包括：

- JSON action / request_task_run / active_work_control 必须遵守。
- pending_user_steers 必须先处理。
- 工具调用只能用可见工具。
- task_execution 每次只能提交一个 JSON action。
- public_action_state 何时写反馈。
- todo 何时 start/complete。
- 最终完成必须有证据。

这些不是运行态事实，而是稳定协议和生命周期规则。放在 dynamic 的问题是：

- 它们随 `agent_visible_runtime_projection` 被当作动态上下文，不是稳定协议的唯一权威。
- 它们进入 volatile suffix，降低 prompt cache 稳定性。
- 它们和 lifecycle prompt 重复，形成双权威。
- 如果动态段被预算、摘要或投影策略影响，规则会漂移。

目标修复边界：

- 稳定协议规则应迁入注册 prompt / action schema / stable runtime protocol。
- `task_runtime_boundary_dynamic` 只保留当前事实值：`allowed_action_types`、`visible_tool_count`、`permission_mode`、`runtime_control_signals`、`operation_authorization` 摘要等。

### P1：动态选择的 lifecycle prompt 被标成 `environment_stable`

`prompt_mount_plan_for_invocation()` 根据 invocation、allowed_actions、visible_tools、execution_state 等动态选择生命周期 prompt：

- `backend/harness/runtime/environment_prompt_controller.py:145-197`
- `backend/harness/runtime/environment_prompt_controller.py:200-295`

但这些生命周期 prompt 最终被 `render_environment_instruction()` 合并进 `environment_stable`，并在 compiler 中标记为 `cache_scope="session"`、`cache_role="session_stable"`：

- `backend/prompt_composition/section_renderer.py:40-79`
- `backend/prompt_composition/section_renderer.py:99-114`
- `backend/harness/runtime/compiler.py:1111-1132`

实证：真实 packet 中 `environment_stable` 同时包含环境规则和 `environment.coding.lifecycle.*`，且被标成 session stable。它的内容来源包括十几条 lifecycle prompt，但选择逻辑本身不是纯 session-stable。

目标修复边界：

- 固定的生命周期规则可以作为 session/task stable，但选择结果不能伪装成 session-stable。
- 若 lifecycle prompt 按 invocation_kind 固定，则应拆成明确的 `lifecycle_stable` 段，cache_scope 至少是 `task` 或 invocation profile stable。
- 若 lifecycle prompt 依赖 visible_tools、allowed_actions、execution_state，则应拆为 `lifecycle_runtime_context` 或只投动态事实，稳定规则仍来自注册 prompt。

### P2：`bound_task_runtime_context` 动态段携带稳定 `restore_policy`

`BoundTaskContext.to_runtime_model_visible_payload()` 会把 `restore_policy` 放入 runtime payload；该 payload 在 task_execution 中作为 volatile `bound_task_runtime_context`：

- `backend/harness/runtime/bound_task_context.py:48-61`
- `backend/harness/runtime/bound_task_context.py:84-96`
- `backend/harness/runtime/bound_task_context.py:395-403`
- `backend/harness/runtime/compiler.py:1273-1291`

其中 `restore_policy.file_precision` 是稳定行为规则：

- 已知文件路径不要用 search_files/search_text 重新发现。
- 对精确编辑应依赖当前有效读窗。
- 已覆盖读窗应复用。
- 只有缺失、过期、变化、未覆盖窗口才 read_file。

这些规则不应只在 dynamic runtime context 里出现。动态段应该只放 `known_task_files`、`rehydration_refs`、当前 content hash、read windows、stale 状态。

目标修复边界：

- 将 `restore_policy.file_precision` 的规则上移到稳定 file evidence/tool dispatch 规则。
- `bound_task_runtime_context` 保留结构化事实和 refs，不再承担规则权威。

### P2：`file_evidence_decisions` 是动态事实，但内部混入规则文本

`TaskStateProjector` 将当前文件覆盖率和读窗投为动态事实，这是正确的；但里面混入了 `instruction`、`decision_boundary`、`reliability_note` 这类自然语言规则：

- `backend/harness/runtime/dynamic_context/task_state_projector.py:1235-1284`
- `backend/harness/runtime/dynamic_context/task_state_projector.py:1287-1320`
- `backend/harness/runtime/dynamic_context/task_state_projector.py:1434-1494`

这类字段可以作为事实解释，但不能成为阻止重复读取的唯一机制。最近任务里动态段已经出现 `do_not_repeat_read_ranges`，模型仍继续调用 `read_file`，说明提示建议不能替代 tool admission。

目标修复边界：

- 动态段保留结构化决策：`reuse_current_windows`、`rehydrate_existing_windows`、`read_missing_windows`、`read_after_stale_windows`、`do_not_repeat_read_ranges`。
- 行为规则进入 stable tool/file evidence contract。
- 重复读取已覆盖非 stale 窗口必须由 admission/tool control plane 拦截或转为 rehydrate observation，不能只靠模型遵守提示。

### P2：用户补充的处理规则放进 volatile user message

`_user_steering_updates_payload()` 把用户补充内容和处理规则混在一个 volatile `user` 段里：

- `backend/harness/runtime/compiler.py:1087`
- `backend/harness/runtime/compiler.py:1338-1361`
- `backend/harness/runtime/compiler.py:3478-3500`

其中 `handling_rules` 和 `required_completion_gate` 是系统规则，不是用户原文。它们不应放在 user role 的动态消息中承担权威。

目标修复边界：

- user steering 动态段只携带用户补充内容、steer_id、priority、editor_context。
- “必须处理后才能收口”的规则进入 stable lifecycle / contract revision protocol。

## 已确认合理的动态内容

以下内容放动态是合理的：

- 工具观察和 task_state replay。
- 当前文件覆盖率、读窗、content hash、stale 状态。
- 当前 editor_context 和 active_file preview。
- pending_user_steers 的用户原文和提交 id。
- runtime_control_signals。
- visible tool count、permission_mode、operation_authorization 摘要。
- rehydration refs 和 observation refs。

关键边界：动态段可以说“当前有哪些事实”，不能成为“你必须如何行动”的唯一规则来源。

## 对反复读取问题的直接结论

这次反复读取不是单纯模型坏，也不是前端显示问题。根因是 prompt 和执行权威分裂：

1. 用户明确约束 `known_constraints` 被任务合同保存，但没有投影进 `task_contract_stable`。
2. 已读覆盖率和 `do_not_repeat_read_ranges` 被放在动态事实里，但只是提示，不是 tool admission 约束。
3. 稳定文件读取策略散落在 lifecycle prompt、runtime dynamic preamble、bound runtime context、file evidence dynamic note 中，形成多处弱权威。

因此模型在“确切内容被省略”时会把再次 `read_file` 当作合理例外；后端 admission 又没有以 file evidence authority 拦截，所以重复读取真实发生。

## 修复建议

1. 先修稳定任务合同投影：
   - 在 `project_task_contract_for_prompt()` 输出 canonical `working_scope`。
   - `known_constraints` 必须作为 task stable 输入进入模型。

2. 再拆 runtime dynamic preamble：
   - `_runtime_projection_instruction()` 不再输出稳定协议规则。
   - stable 规则迁入注册 lifecycle/action protocol。
   - dynamic runtime boundary 只保留当前事实和计数。

3. 拆 lifecycle prompt 与 environment prompt：
   - 环境说明只放环境。
   - lifecycle prompt 独立成 `lifecycle_stable` 或按真实依赖标成 volatile。

4. 收敛文件读取规则权威：
   - stable：文件证据/读取策略规则。
   - dynamic：读窗、覆盖率、stale、rehydrate refs。
   - admission：阻止重复读取已覆盖非 stale 窗口，或返回可复用/rehydrate 观察。

5. 清理动态 payload 中的规则文本：
   - `restore_policy.file_precision`
   - `file_evidence_decisions.instruction`
   - `decision_boundary`
   - `read_resource_state.reliability_note`
   - `user_steering_updates.handling_rules`

这些字段可以改成结构化状态码、reason code 或 stable rule ref，避免动态自然语言继续当规则。

