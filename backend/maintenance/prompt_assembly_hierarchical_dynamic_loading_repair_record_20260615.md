# Prompt 组装分层修复记录（2026-06-15）

## 本次审查结论

对照 `prompt_assembly_hierarchical_dynamic_loading_plan_20260615.md` 和当前代码后，计划方向成立，但有两处需要调整执行方式：

1. `PromptSlotPlan` 全量主链路迁移不适合和本次修复一次性混在一起。当前先用现有 `message_specs -> segment_plan -> prompt_composition manifest` 承接分层，避免在同一轮重写 compiler 主干、renderer、manifest 和 provider projection。
2. `read_file` 重复读取准入不应放在 `harness.loop.admission`。那里只有模型 action 和工具定义，拿不到当前 `file_evidence_scope` 的真实窗口状态。实际准入权威放到 `runtime.tool_runtime.tool_control_plane`，在工具执行前读取 `FileStateAuthorityStore`。

## 已修复链路

| 目标线 | 修复结果 |
| --- | --- |
| 任务合同稳定投影 | `task_contract_stable` 已投影 canonical `working_scope`，包含 `target_objects`、`workspace_refs`、`source_refs`、`excluded_scope`、`known_constraints`。 |
| environment/lifecycle 分离 | `render_environment_instruction()` 不再合并 lifecycle；新增 `render_lifecycle_instruction()`；compiler 三个入口都生成独立 `lifecycle_stable` 段。 |
| file evidence 稳定策略 | 新增 `file_evidence_policy_stable` 段；`bound_task_context.restore_policy` 只保留 policy ref，不再携带 `file_precision` 规则文本。 |
| runtime dynamic 去规则化 | `_runtime_projection_instruction()` 只输出 `当前运行事实` 前导，旧大段协议规则已删除。 |
| 动态事实去自然语言规则 | `file_evidence_decisions`、`read_resource_state`、`user_steering_updates`、`recent_work_outcome` 改为 `policy_ref`、`decision_code`、`state_code`、`boundary_code`。 |
| replay 分层识别 | `task_state_replay_entry` 在 tracing 中先按 segment kind 识别为 `runtime_task_state_replay`，不再被 `cache_role=volatile` 抢先归为普通 dynamic fragment。 |
| read_file 重复读取准入 | `RuntimeToolControlPlane` 在 executor 前拦截已覆盖且未 stale 的 read_file 请求，返回同一 `tool_call_id` 的 ok 工具观察并完成 execution record，不再真实重读。 |
| PromptSlotPlan 主链路 | compiler 四个入口均生成 `prompt_slot_plan`，每个 model message 都带 `prompt_slot_id`、slot layer/source/cache/dynamic tier。 |
| RuntimeContextLoadPlan 主链路 | 新增 `RuntimeContextLoadPlan`，由 slot plan 决定 `stable_prefix -> active_skills -> history_replay -> append_only_task_evidence -> current_runtime_cursor -> file_evidence_cursor -> user_editor_volatile -> assistant_completion_prefix` 装载顺序。 |
| Segment materializer | `message_specs` 由 `RuntimeContextLoadPlan` 物化，metadata 同时带 slot 追踪和 load phase/order，segment plan 只消费已分层排序后的 specs。 |
| 旧 shadow 链路清理 | 删除 `build_shadow_prompt_composition_manifest`、旧 `PromptCompositionLayerInput` planner、旧 slot-only materializer 和 `turn_context` 映射；compiler 不再构造旧 composition layers。 |
| skill 动态层修正 | `active_skills`、`skill_candidates` 先按语义归入 `active_skills` 动态层，不会因 cache role 被吞进 stable prefix。 |
| task replay 装载顺序 | `task_state_replay_entry` 作为 append-only evidence 在 load plan 中排到 current runtime cursor 之前，assistant completion prefix 固定最后。 |

## 当前权威线

```text
PromptSources currently produced by RuntimeCompiler
-> RuntimePromptSlotPlan
-> RuntimeContextLoadPlan
-> materialized message specs
-> PromptSegmentPlan
-> PromptCompositionManifest
-> RuntimeInvocationPacket
-> tool control plane file_evidence_admission
-> native tool executor
```

动态装载时序：

```text
stable_prefix
-> active_skills
-> history_replay
-> append_only_task_evidence
-> current_runtime_cursor
-> file_evidence_cursor
-> user_editor_volatile
-> assistant_completion_prefix
```

## 验证

- `python -m compileall` 已通过以下文件：
  - `backend/harness/runtime/compiler.py`
  - `backend/harness/runtime/task_contract_manifest.py`
  - `backend/harness/runtime/bound_task_context.py`
  - `backend/harness/runtime/dynamic_context/task_state_projector.py`
  - `backend/harness/runtime/dynamic_context/history_projector.py`
  - `backend/prompt_composition/section_renderer.py`
  - `backend/prompt_composition/tracing.py`
  - `backend/prompt_composition/manifest.py`
  - `backend/runtime/tool_runtime/tool_control_plane.py`
- 已扫描目标残留字段：`decision_boundary`、`reliability_note`、`handling_rules`、`required_completion_gate`、`file_precision`，当前改动范围内无残留。
- 冒烟验证已通过：
  - `task_contract_stable.working_scope.known_constraints` 能投影用户约束。
  - `task_state_replay_entry` 映射为 `runtime_task_state_replay`。
  - `lifecycle_stable` 映射为 `runtime_lifecycle`。
  - `file_evidence_policy_stable` 映射为 `runtime_file_evidence_policy`。
  - 已覆盖 read_file 窗口能被 file evidence admission 识别为复用。
- 新增结构冒烟已通过：
  - `active_skills` 被装载到 `active_skills` phase。
  - `task_state_replay_entry` 被装载到 `append_only_task_evidence` phase，且排在 `dynamic_projection` 前。
  - `bound_task_runtime_context` 被装载到 `file_evidence_cursor` phase。
  - `user_steering_updates` 被装载到 `user_editor_volatile` phase。
  - `graph_node_completion_prefix` 被装载到 `assistant_completion_prefix` phase 并保持最后。
  - 每个 segment 都绑定到明确 runtime prompt slot，`prompt_composition.shadow_mode` 为 `False`。

## 未做项

更前置的 `PromptSources` 仍由 `RuntimeCompiler` 手写 specs 产生，尚未抽成独立 source registry。当前已完成的是 compiler 内部主链路从扁平 specs 解释，升级为 `RuntimePromptSlotPlan -> RuntimeContextLoadPlan -> materialized specs -> ProviderMessageProjection`。
