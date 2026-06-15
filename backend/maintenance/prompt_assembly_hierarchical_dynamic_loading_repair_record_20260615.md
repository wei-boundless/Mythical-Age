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
| PromptSources 主链路 | 新增 `RuntimePromptSourceManifest`，compiler 四个入口先把可发送的 message specs 固化为 source manifest，再进入 slot/load/segment，不再让 slot plan 直接解释 compiler 临时 specs。 |
| PromptSlotPlan 主链路 | compiler 四个入口均生成 `prompt_slot_plan`，每个 model message 都带 `prompt_slot_id`、slot layer/source/cache/dynamic tier。 |
| RuntimeContextLoadPlan 主链路 | 新增 `RuntimeContextLoadPlan`，由 slot plan 决定 `stable_prefix -> active_skills -> history_replay -> append_only_task_evidence -> current_runtime_cursor -> file_evidence_cursor -> user_editor_volatile -> assistant_completion_prefix` 装载顺序。 |
| Segment materializer | `message_specs` 由 `RuntimeContextLoadPlan` 物化，metadata 同时带 slot 追踪和 load phase/order，segment plan 只消费已分层排序后的 specs。 |
| 旧 shadow 链路清理 | 删除 `build_shadow_prompt_composition_manifest`、旧 `PromptCompositionLayerInput` planner、旧 slot-only materializer 和 `turn_context` 映射；compiler 不再构造旧 composition layers。 |
| skill 动态层修正 | `active_skills`、`skill_candidates` 先按语义归入 `active_skills` 动态层，不会因 cache role 被吞进 stable prefix。 |
| task replay 装载顺序 | `task_state_replay_entry` 作为 append-only evidence 在 load plan 中排到 current runtime cursor 之前，assistant completion prefix 固定最后。 |
| Source identity 精度 | `RuntimePromptSource.source_id` 同时纳入 content hash 与完整 `model_message_hash`，避免 tool call、assistant prefix 等非普通正文消息只靠空 content 生成模糊身份。 |

## 当前权威线

```text
RuntimeCompiler filtered sendable specs
-> RuntimePromptSourceManifest
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
  - `backend/prompt_composition/models.py`
  - `backend/prompt_composition/runtime_sources.py`
  - `backend/prompt_composition/runtime_slot_plan.py`
  - `backend/prompt_composition/runtime_context_load_plan.py`
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
- PromptSources 增量冒烟已通过：
  - `single_agent_turn` 生成 `runtime_prompt_source_manifest_ref`、`prompt_slot_plan_ref`、`runtime_context_load_plan_ref`。
  - `single_agent_turn` 的 source/slot/load entry/segment 数量一致，`prompt_composition.shadow_mode=False`，renderer 没有 fallback。
  - 每个 segment metadata 都带 `runtime_prompt_source_id`、`prompt_slot_id`、`runtime_context_load_entry_id`。
  - `runtime_prompt_source_id` 由完整 model message hash 参与生成，metadata 同时暴露 `runtime_prompt_source_content_hash` 与 `runtime_prompt_source_model_message_hash`。
  - `task_execution` 的 source/slot/load entry/segment 数量一致。
  - `task_execution` 中 `task_state_replay_entry` 仍装载到 `append_only_task_evidence`，并排在 `task_runtime_boundary_dynamic` 前。
  - `task_execution` 中 `user_steering_updates` 装载到 `user_editor_volatile`。

## 当前剩余事项

`PromptSources` 已成为 compiler 内部主链路的第一层权威清单。更前置的 source registry 是否继续抽离，应作为下一阶段独立设计：只有在需要把 prompt source 的采集权从 compiler 迁出到专门 registry 时才推进，不能再回到旧 shadow planner 或旧 layer input。

## 新对话实证复查（session-9458b9376ed8437e / turn 40）

复查对象：

- 会话：`session-9458b9376ed8437e`
- 任务：`taskrun:turn:session-9458b9376ed8437e:40:199feb77`
- 最新实查 packet：`rtpacket:taskrun:turn:session-9458b9376ed8437e:40:199feb77:task_execution:1:16`
- 最新 payload：`storage/runtime_state/event_payloads/9a/9a38607c89182af83d28159990db53ec50c54d7f3e3d14da5815c2010f5cce08.json`
- 最新任务状态：`running`，`latest_event_offset=253` 时已进入第 16 次模型调用等待。

### 已确认接对的线

| 线 | 实证结论 |
| --- | --- |
| 任务合同稳定投影 | `task_contract_stable` 已包含 `working_scope.target_objects=["fps_game.html"]` 和 `known_constraints`，包括“不再反复读取文件，一次性读取后直接重写完整修正”。 |
| PromptSources 主链路 | 最新 packet 中 `RuntimePromptSourceManifest -> RuntimePromptSlotPlan -> RuntimeContextLoadPlan -> SegmentPlan -> PromptCompositionManifest` 均存在，且 `shadow_mode=false`。 |
| 动态装载顺序 | `task_state_replay_entry` 被放入 `append_only_task_evidence`，在 `task_runtime_boundary_dynamic` 之前；`bound_task_runtime_context` 被放入 `file_evidence_cursor`。 |
| 文件读证据 | `file_state` 已记录 `fps_game.html` 的 exact read observation，写后当前文件 `total_lines=769`，current read windows 覆盖完整文件。 |
| 重复 read_file 控制面 | 第 14、15 轮开始，重复读取已覆盖窗口时返回 `read_file reused current evidence...`，说明 `RuntimeToolControlPlane` 的 file evidence admission 已生效。 |

### 仍未接准的线

| 问题 | 证据 | 影响 | 修复边界 |
| --- | --- | --- | --- |
| `file_evidence_policy_stable` 前缀层级错序 | 最新 packet 的 prefix tier sequence 为 `provider_global, session..., task, task, session, task, volatile...`，`file_evidence_policy_stable` 位于两个 task 段之后但仍标记为 `session`。 | prompt cache 诊断持续 `warning`，并产生 `prefix_tier_order_regression`。这是真实分层错序，不是 accounting 误报。 | 要么把 `file_evidence_policy_stable` 移到所有 task 段之前；要么若它依赖 task tool/file 范围，就把 cache_scope 改为 `task` 并保持在 task prefix 内。当前内容是全局读窗策略，应优先移到 session stable 区。 |
| `task_state_replay_entry` layer 策略误报 | latest packet 中 16 个 replay entry 均为 `cache_scope=none/cache_role=volatile/prefix_tier=volatile`，但 slot layer 被命名为 `task_state_replay_stable`，manifest policy 要求 task/session stable，导致 32 条 layer violation。 | accounting 把正常 append-only runtime evidence 误判为层违规，污染 prompt cache 诊断。 | 将 runtime source kind `runtime_task_state_replay` 的 layer 改为 append-only/dynamic evidence 层，或在 manifest policy 中把该层定义为 volatile append-only。不要把 replay evidence 当 stable。 |
| 已知 target path 仍先 search | 第 1 次模型 action 直接 `search_files(query="fps_game.html")`，reasoning 中承认合同目标是 `fps_game.html`，但仍认为需要先定位。 | 目标文件已知时多余搜索，降低执行效率，也增加后续上下文噪声。 | `task_contract_stable.working_scope.target_objects` 需要被明确解释为“已知工作对象；像相对路径的对象应先 `path_exists/read_file`，不要通过 search 重新发现”。同时 tool index 中 `search_files` 的 usage_hint 也应与该规则一致。 |

### 当前判断

这次新对话的 prompt 装配不是整体失败：任务合同、运行事实、读证据、动态装载主线已经进入真实 packet。但仍有两个结构性问题必须修：

1. cache prefix 分层顺序仍不干净：session 段不能插在 task 段后面。
2. replay evidence 的层语义不准确：它是 append-only volatile evidence，不是 task stable。

另有一个行为策略缺口：`target_objects` 虽进入合同，但模型没有被足够明确地告知“已知路径对象不需要 search”。这不是前端问题，也不是单纯模型坏；它属于任务合同语义到工具选择策略之间的连接线不够硬。

## 本轮修复结果（2026-06-15）

### 已完成

- `task_execution` 的 `file_evidence_policy_stable` 已移到所有 task 前缀段之前，避免 session 段插在 task 段后形成 prefix 顺序错位。
- `runtime_task_state_replay` 的层语义已改为 `append_only_task_evidence`，不再伪装成 stable layer。
- `task_contract.working_scope.target_objects/source_refs/workspace_refs` 只要呈现为文件样路径，就会投影为 known path policy，优先 `path_exists/read_file`，不再默认先 `search_files/search_text`。
- 共享工具提示已同步收口，避免 runtime、合同和工具目录对“已知路径”的说法互相打架。

### 验证结果

- `python -m compileall` 已通过相关 runtime / prompt 组件文件。
- 结构脚本已通过，确认：
  - `fps_game.html` 会进入 known path policy。
  - replay slot 的 `layer` 和 `dynamic_tier` 都是 `append_only_task_evidence`。
  - replay layer policy 不再报 violation。

### 仍需关注

- 后续新 packet 是否还会出现别的 prompt 源残留“已知路径先 search”的旧表述，需要继续按源头清理，而不是在下游再补丁化纠偏。
