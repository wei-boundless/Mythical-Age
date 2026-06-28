# 提示词库与运行接线标准化设计书

## 0. 文档状态

状态：待用户审阅后实施。

本文承接 `Turn 运行提示词系统标准化重构设计书`，继续解决提示词库和运行接线的治理问题。目标不是把现有 prompt 简单拆短，而是把提示词资源、提示词组合、agent 私有配置、环境变体、运行状态提示、provider 协议和最终模型消息装配成一套可维护的标准系统。

最终目标：每一个 agent 都可以拥有自己的提示词配置；runtime 根据当前 invocation、agent、环境、工具能力、状态和协议边界，解析出一份明确的运行接线计划，再编译成模型可见消息和 provider schema。

## 1. 当前问题

现有系统已经有可用骨架，但职责边界不够清晰：

- `PromptResource` 是原子提示词资源。
- `PromptPack` 是按 invocation 排列的一组 prompt refs。
- `AgentRuntimeProfile.metadata.agent_prompt_refs_by_invocation` 可以让 agent 指定不同 invocation 的工作角色 prompt。
- `PromptMountPlan` 负责环境 prompt、personality prompt、lifecycle prompt、tool guidance defaults/overrides。
- `PromptAssemblyService` 负责把 pack/ref 装配成 `PromptSection`。
- `environment_lifecycle_prompts.py` 已有 coding / office / general 三套生命周期提示词，并且这三套已经分别通过三个主 agent 的默认环境接入。

真正的问题是：

- agent 的 prompt 配置只是 metadata 里的散列字段，不是显式模型。
- prompt pack、agent prompt、environment prompt、lifecycle prompt、personality prompt 和 tool guidance 没有统一 slot 体系。
- `PromptMountPlan` 同时处理环境、生命周期、工具提示和 personality，接线职责过宽。
- “生命周期提示词”承载了很多不同功能：请求判断、动作选择、环境能力、工具调度、恢复、记忆、收口。这不是生命周期，而是不同 prompt slot。
- compiler 直接知道太多接线细节，后续每个 agent 自配 prompt set 会继续扩大分支。

正确终态：

```text
PromptResource
-> PromptPack
-> PromptSet
-> AgentPromptBinding
-> RuntimePromptWiringPlan
-> PromptAssembly
-> ModelMessages + ProviderSchema
```

## 2. 源码依据

### 2.1 Prompt 库现状

关键文件：

- `backend/prompt_library/models.py`
  - `PromptResource` 已有 category、subtype、owner_layer、allowed_invocation_kinds、allowed_agent_refs、allowed_environment_refs、cache_scope。
  - `PromptPack` 已有 invocation_kind、ordered_prompt_refs、allowed_agent_refs、allowed_environment_refs。
  - `PromptAssemblyRequest` 已有 prompt_pack_refs、prompt_refs、skill_prompt_refs、soul_prompt_ref、agent_profile_ref、task_environment_ref。
- `backend/prompt_library/registry.py`
  - 内置资源和存储资源统一由 `PromptLibraryRegistry` 合并。
  - 当前只持久化 `prompt_resources.json` 和 `prompt_packs.json`。
- `backend/prompt_library/assembly.py`
  - `PromptAssemblyService` 负责展开 pack/ref、去重、权限过滤、构造 `PromptSection`。
- `backend/prompt_library/agent_prompts.py`
  - 主 agent 已有 `single_agent_turn`、`task_execution`、`tool_observation_followup` 三个工作角色 prompt。
- `backend/prompt_library/worker_prompts.py`
  - worker blueprint 已能返回 `agent_prompt_refs_by_invocation` metadata。
- `backend/prompt_library/environment_lifecycle_prompts.py`
  - 当前存在 `env.coding.vibe_workspace`、`env.office.file_search`、`env.general.workspace` 三套 18-slot 生命周期 prompt。
  - 这三套不是孤立环境模板，而是被三个主 agent profile 分别选中为默认环境提示词配置。

### 2.2 Runtime 接线现状

关键文件：

- `backend/agent_system/profiles/runtime_profile_models.py`
  - `AgentRuntimeProfile` 有 `metadata`，但没有显式 prompt set 字段。
- `backend/agent_system/profiles/runtime_profile_registry.py`
  - 默认 profile 通过 metadata 写入 `agent_prompt_refs_by_invocation` 和 `runtime_policy.prompt_policy`。
  - `main_interactive_agent` 默认绑定 `env.general.workspace`。
  - `main_coding_agent` 默认绑定 `env.coding.vibe_workspace`。
  - `main_office_agent` 默认绑定 `env.office.file_search`。
- `backend/harness/runtime/assembly.py`
  - `RuntimeAssembly` 已有 `agent_prompt_refs`、`agent_prompt_refs_by_invocation`、`personality_prompt_refs`、`environment_prompt_refs`、`prompt_mount_plan`。
  - `_agent_prompt_refs_by_invocation` 从 profile metadata 读取。
  - `_build_system_wiring_manifest` 已把 system group、prompt resources、context segments 和 feedback channels 串起来。
- `backend/harness/runtime/environment_prompt_controller.py`
  - `PromptMountPlan` 负责构造 environment/lifecycle prompt refs。
  - `_lifecycle_prompt_selection_for_invocation` 按 invocation、allowed_actions、active_work、observations、tools、memory 等动态选择 stable/runtime lifecycle prompts。
- `backend/harness/runtime/compiler.py`
  - compiler 根据 runtime assembly 重新组装 agent、personality、environment、lifecycle、runtime lifecycle 等提示词。

## 3. 外部成熟架构原则

参考成熟 agent 系统的共同结构，不复制命名：

- Codex 将 session state、active turn、turn state、running task 拆分，说明运行资源、工具、审批、动态工具响应都应是 turn state 或 session state，不应被写成另一套 prompt 生命周期。
- Claude Code 状态设计强调向下依赖、向上隔离；这对应 prompt 接线：agent profile 可以声明需求，runtime wiring 可以解析资源，但 prompt resource 不应反向决定 runtime 行为。
- 成熟 agent prompt 通常有精确角色 prompt、工具协议、输出边界、恢复反馈；但技术 schema 由工具定义或 provider function calling 承载，而不是靠多段自然语言重复字段。

抽象原则：

- prompt library 管资源。
- prompt set 管组合意图。
- wiring plan 管本次 invocation 的接线结果。
- compiler 只渲染 wiring plan，不重新判断应该挂什么。
- agent 可以配置 prompt set，但不能绕过 runtime action/permission/output 边界。

## 4. 标准模型

### 4.1 PromptResource

保留现名。

职责：一个可引用的原子提示词资源。

必要字段继续保留：

- `prompt_id`
- `category`
- `subtype`
- `owner_layer`
- `allowed_invocation_kinds`
- `allowed_agent_refs`
- `allowed_environment_refs`
- `cache_scope`
- `metadata.prompt_rule`

新增规范字段建议放入 metadata，避免一次性破坏存储结构：

- `prompt_slot`
- `prompt_layer`
- `prompt_contract`
- `visibility`
- `schema_role`

### 4.2 PromptPack

保留现名。

职责：一组按顺序复用的 prompt refs，通常绑定某个 invocation。

限制：

- pack 只能描述稳定组合，不根据当前 active work、工具观察或恢复状态动态选择。
- pack 不能表达 agent 私有配置的全部含义；它只是 PromptSet 可引用的一个构件。

### 4.3 PromptSet

新增概念。

职责：一个可复用、可继承、可绑定 agent/environment 的提示词配置集合。

建议结构：

```json
{
  "prompt_set_id": "prompt_set.main_interactive.default",
  "owner": {"kind": "agent", "ref": "main_interactive_agent"},
  "extends": ["prompt_set.runtime.default_turn"],
  "slots": {
    "agent_work_role": {
      "single_agent_turn": ["agent.main_interactive_agent.single_agent_turn.work_role"],
      "tool_observation_followup": ["agent.main_interactive_agent.tool_observation_followup.work_role"],
      "task_execution": ["agent.main_interactive_agent.task_execution.work_role"]
    },
    "runtime_prompt_pack": {
      "single_agent_turn": ["runtime.pack.single_agent_turn"]
    },
    "turn_state_guidance": {
      "default": ["environment.general.state.context_intake"]
    }
  },
  "policies": {
    "allow_agent_override": ["agent_work_role", "personality"],
    "locked_slots": ["system_foundation", "action_protocol", "output_boundary"]
  }
}
```

PromptSet 的价值：

- agent 不再通过零散 metadata 配 prompt。
- 可以明确继承默认 runtime prompt set。
- 可以声明哪些 slot 允许 agent 覆盖，哪些 slot 由系统锁定。
- 可以为 coding / office / general 环境配置不同变体。

### 4.4 AgentPromptBinding

新增概念。

职责：把 `AgentRuntimeProfile` 绑定到一个或多个 PromptSet。

建议结构：

```json
{
  "agent_profile_id": "main_coding_agent",
  "prompt_set_refs": [
    "prompt_set.runtime.default_turn",
    "prompt_set.agent.main_interactive",
    "prompt_set.environment.coding"
  ],
  "invocation_overrides": {
    "semantic_compaction": ["prompt_set.agent.context_compactor"]
  }
}
```

迁移方式：

- 现有 `metadata.agent_prompt_refs_by_invocation` 先迁移为 inline AgentPromptBinding。
- 后续再持久化到 `prompt_sets.json` 或 agent profile 的显式字段。

### 4.5 RuntimePromptWiringPlan

新增 canonical 接线结果。

职责：一次 invocation 的最终提示词接线计划。它不是 prompt library 的资源，而是 runtime 编译前的已解析结果。

建议结构：

```json
{
  "wiring_id": "promptwiring:{turn_id}:{hash}",
  "agent_profile_id": "main_interactive_agent",
  "invocation_kind": "single_agent_turn",
  "environment_id": "env.general.workspace",
  "slots": [
    {
      "slot": "system_foundation",
      "refs": ["system.foundation"],
      "cache_scope": "global",
      "visibility": "model_visible",
      "owner_layer": "system"
    },
    {
      "slot": "agent_work_role",
      "refs": ["agent.main_interactive_agent.single_agent_turn.work_role"],
      "cache_scope": "session_stable",
      "visibility": "model_visible",
      "owner_layer": "agent"
    }
  ],
  "schema_refs": ["turn_action_request_schema", "control_action_schema"],
  "diagnostics": {
    "source_prompt_sets": [],
    "omitted_slots": [],
    "rejected_refs": []
  }
}
```

RuntimePromptWiringPlan 取代当前 `PromptMountPlan` 的总线地位。

`PromptMountPlan` 可以短期保留为环境 prompt mount 的内部结构，但不再作为全局接线模型。

## 5. 标准 Prompt Slots

统一 slot 名称，避免继续用 lifecycle 包打天下。

### 5.1 稳定前缀 slots

- `system_foundation`
- `runtime_invocation_prompt`
- `runtime_decision_rule`
- `runtime_output_boundary`
- `runtime_error_recovery`
- `agent_work_role`
- `agent_personality`
- `environment_orientation`
- `tool_guidance`
- `skill_prompt`
- `project_instruction`

### 5.2 动态尾部 slots

- `current_user_request`
- `current_runtime_state`
- `turn_state_guidance`
- `turn_attention_index`
- `current_file_evidence`
- `tool_observation_delta`
- `recovery_feedback`
- `active_work_boundary`

### 5.3 协议和 schema slots

这些不作为自然语言 prompt 主体：

- `action_protocol_schema`
- `control_action_schema`
- `provider_tool_schema`
- `output_commit_schema`
- `context_fragment_metadata`

它们进入 provider schema、context metadata 或结构化 payload。

## 6. 三个主 Agent 的环境提示词迁移

当前三套已经分别由三个主 agent profile 选用：

- `main_interactive_agent` -> `env.general.workspace`
- `main_coding_agent` -> `env.coding.vibe_workspace`
- `main_office_agent` -> `env.office.file_search`

因此这不是“尚未分配的三套环境提示词”，而是“已经由三个主 agent 间接配置的三套环境提示词”。当前需要标准化的是接线模型：从 `AgentRuntimeProfile.metadata.default_task_environment_id` 和 environment lifecycle defaults，升级为显式 `AgentPromptBinding + PromptSet + RuntimePromptWiringPlan`。

当前 18 个 slot：

- `context_intake`
- `request_judgment`
- `work_relation`
- `environment_capability_alignment`
- `plan_gate`
- `action_selection`
- `active_work_control`
- `task_run_handoff`
- `user_steer_contract_revision`
- `tool_dispatch`
- `tool_observation_recovery`
- `subagent_delegation`
- `subagent_result_integration`
- `verification_gate`
- `memory_read_context`
- `memory_write_handoff`
- `compaction_handoff`
- `finalization`

迁移目标：

- 不再统称 `lifecycle_prompt`。
- 改为 `environment_prompt_set` 下的功能 slot。
- `action_selection` 归入 `runtime_decision_rule` 或删除，由统一 turn decision rule 负责。
- `finalization` 归入 `runtime_output_boundary` 或 environment-specific output guidance。
- `tool_observation_recovery` 归入 `recovery_feedback`。
- `context_intake`、`work_relation`、`environment_capability_alignment` 归入 `turn_state_guidance`。
- `tool_dispatch` 归入 `tool_guidance`。
- `memory_read_context`、`memory_write_handoff` 归入 memory-specific guidance。
- `task_run_handoff` 暂时保留为 `request_task_run_guidance`，后续任务体系重做时再进入 TaskRun 资源契约。

命名建议：

旧：

```text
environment.coding.lifecycle.context_intake
```

新：

```text
environment.coding.turn_state.context_intake
```

旧：

```text
environment.general.lifecycle.finalization
```

新：

```text
environment.general.output.finalization_guidance
```

旧名只通过迁移表转换，不保留双轨 prompt。

## 7. 接线权威链

目标接线顺序：

```text
AgentRuntimeProfile
-> AgentPromptBinding
-> PromptSetResolver
-> RuntimePromptWiringPlan
-> PromptAssemblyService
-> RuntimeCompiler
-> ModelMessages / ProviderSchema
```

各层权威：

| 层 | 拥有什么权威 | 不允许做什么 |
|---|---|---|
| AgentRuntimeProfile | 声明 agent 身份、工具权限、默认 prompt set refs | 不直接拼 model messages |
| AgentPromptBinding | 绑定 agent 和 prompt sets | 不判断当前用户意图 |
| PromptSetResolver | 解析继承、override、slot refs | 不根据运行观察重写 agent 配置 |
| RuntimePromptWiringPlan | 表达本次 invocation 最终接线 | 不渲染文本，不执行工具 |
| PromptAssemblyService | 将 refs 编译为 sections | 不选择 prompt set，不判断动作 |
| RuntimeCompiler | 将 sections 和 state 编译成 provider payload | 不重新解释 prompt ownership |
| ProviderSchema | 承载工具和控制动作 schema | 不讲自然语言行为准则 |

## 8. 模块计划

### 8.1 `backend/prompt_library/models.py`

新增：

- `PromptSet`
- `PromptSetSlot`
- `AgentPromptBinding`
- `RuntimePromptWiringPlan`
- `RuntimePromptWiringSlot`

保留：

- `PromptResource`
- `PromptPack`
- `PromptAssemblyRequest`
- `PromptAssemblyResult`

### 8.2 `backend/prompt_library/registry.py`

新增：

- `prompt_sets.json`
- `list_prompt_sets`
- `get_prompt_set`
- `upsert_prompt_set`

调整：

- 资源和 pack 仍按现有路径读取。
- PromptSet 是组合层，不混进 resource 列表。

### 8.3 `backend/prompt_library/assembly.py`

调整：

- 继续只负责 ref -> section。
- 不引入 agent prompt set 解析逻辑。
- 增加从 `RuntimePromptWiringPlan` 装配 sections 的入口。

### 8.4 新增 `backend/prompt_library/wiring.py`

职责：

- 解析 AgentPromptBinding。
- 合并 PromptSet 继承。
- 处理 slot override。
- 生成 RuntimePromptWiringPlan。
- 输出 diagnostics：source sets、omitted slots、conflicts、locked slot violations。

禁止：

- 不渲染 prompt text。
- 不判断用户意图。
- 不决定工具权限。

### 8.5 `backend/agent_system/profiles/runtime_profile_models.py`

新增显式字段的方向：

- `prompt_set_refs`
- `prompt_bindings`

短期兼容：

- 先从 metadata 中读取旧字段。
- 迁移完成后删除旧 metadata 读取路径。

### 8.6 `backend/agent_system/profiles/runtime_profile_registry.py`

调整默认 profile：

- `main_interactive_agent`
- `main_coding_agent`
- `main_office_agent`
- `memory_system_agent`
- `context_compactor_agent`
- 各子 agent

都改为引用 PromptSet，而不是直接写 `agent_prompt_refs_by_invocation`。

### 8.7 `backend/harness/runtime/assembly.py`

调整：

- 从 agent profile 读取 prompt binding。
- 调用 PromptSetResolver 生成 RuntimePromptWiringPlan。
- RuntimeAssembly 保留 `prompt_mount_plan` 过渡期字段，但新增 `prompt_wiring_plan`。
- `_build_system_wiring_manifest` 使用 wiring plan 中的 prompt slots，而不是直接读 lifecycle refs。

### 8.8 `backend/harness/runtime/environment_prompt_controller.py`

调整：

- 将生命周期选择逻辑拆出为 environment prompt set 解析。
- `PromptMountPlan` 缩小为 environment mount 或逐步删除。
- `_lifecycle_prompt_selection_for_invocation` 改为 `environment_guidance_selection_for_invocation`。

### 8.9 `backend/harness/runtime/compiler.py`

调整：

- compiler 读取 `prompt_wiring_plan`。
- 按 slot 编译稳定前缀、动态尾部、schema metadata。
- 不再直接知道 lifecycle prompt refs。

### 8.10 `backend/prompt_library/migrations.py`

新增迁移：

- `agent_prompt_refs_by_invocation` -> inline AgentPromptBinding
- `prompt_pack_refs_by_invocation` -> PromptSet slots
- `environment.*.lifecycle.*` -> environment functional slots

## 9. 分阶段实施计划

### Phase 1：文档和 slot 词表锁定

目标：

- 确定标准 slot。
- 确定 PromptSet / AgentPromptBinding / RuntimePromptWiringPlan 数据结构。

产物：

- 本设计书。
- 可实施的数据模型 checklist。

完成标准：

- 不再使用 lifecycle 作为总称。
- 明确哪些 slot 可由 agent 覆盖，哪些由系统锁定。

### Phase 2：PromptSet 数据模型和注册表

目标：

- 在 prompt library 中加入组合层。

文件：

- `backend/prompt_library/models.py`
- `backend/prompt_library/registry.py`
- `backend/prompt_library/migrations.py`

完成标准：

- 能 list/get/upsert PromptSet。
- 不影响现有 resource/pack 装配。

### Phase 3：AgentPromptBinding 迁移

目标：

- 每个 agent profile 都能显式绑定 prompt set。

文件：

- `backend/agent_system/profiles/runtime_profile_models.py`
- `backend/agent_system/profiles/runtime_profile_registry.py`
- `backend/prompt_library/agent_prompts.py`
- `backend/prompt_library/worker_prompts.py`

完成标准：

- 默认主 agent 和 worker agents 都由 PromptSet 声明 prompt。
- 旧 `agent_prompt_refs_by_invocation` 只作为迁移输入，不作为主链路。

### Phase 4：RuntimePromptWiringPlan 接线

目标：

- runtime assembly 生成标准接线计划。

文件：

- `backend/prompt_library/wiring.py`
- `backend/harness/runtime/assembly.py`
- `backend/harness/runtime/compiler.py`

完成标准：

- compiler 消费 wiring plan。
- wiring diagnostics 能说明每个 prompt ref 来自哪个 prompt set、哪个 slot、哪个 owner。

### Phase 5：三个主 Agent 的环境提示词迁移

目标：

- 将 `main_interactive_agent`、`main_coding_agent`、`main_office_agent` 当前默认接入的 general / coding / office lifecycle prompts 迁移为对应 agent prompt binding 中的 environment prompt sets。

文件：

- `backend/prompt_library/environment_lifecycle_prompts.py`
- 新文件：`backend/prompt_library/environment_prompt_sets.py`
- `backend/harness/runtime/environment_prompt_controller.py`
- `backend/runtime/context_management/context_capability_policy.py`

完成标准：

- `environment.*.lifecycle.*` 不再作为主 ref。
- 旧 lifecycle refs 通过 migration 映射到新 ref。
- 环境提示词按功能 slot 接入 wiring plan。

### Phase 6：清理旧接线

目标：

- 删除旧 lifecycle 总线和 metadata 散列配置。

清理项：

- `lifecycle_prompt_refs`
- `runtime_lifecycle_prompt_refs`
- `lifecycle_prompt_defaults`
- `lifecycle_prompt_overrides`
- `agent_prompt_refs_by_invocation` 主链路读取
- compiler 中直接装配 lifecycle prompt 的逻辑

完成标准：

- `rg "lifecycle_prompt_refs|runtime_lifecycle_prompt_refs|agent_prompt_refs_by_invocation"` 只剩迁移层或历史文档。
- RuntimeAssembly 以 `prompt_wiring_plan` 为提示词接线真相。

## 10. 验证策略

不新增测试文件。使用编译、静态审查和真实 CLI 验证。

必须执行：

```powershell
python -m compileall backend\prompt_library backend\agent_system backend\harness\runtime backend\runtime\context_management
```

静态审查：

```powershell
rg "lifecycle_prompt_refs|runtime_lifecycle_prompt_refs|agent_prompt_refs_by_invocation|environment\\..*\\.lifecycle\\." backend
```

运行验证：

- 主 agent 单轮对话正常。
- coding agent 能拿到 coding prompt set。
- office agent 能拿到 office prompt set。
- memory/context compactor 等系统 agent 能拿到自己的工作角色 prompt。
- `request_task_run` 仍保持任务体系切断状态，不重启旧任务执行器。

涉及前后端联调时，必须使用固定端口：

- backend: `http://127.0.0.1:8003`
- frontend: `http://127.0.0.1:3000`

## 11. 禁止事项

- 不把每个 agent 的 prompt 配置继续塞进无结构 metadata。
- 不让 `PromptMountPlan` 继续承担全局接线总线。
- 不用 lifecycle 继续命名所有环境提示词。
- 不让 compiler 自己决定 prompt set。
- 不让 prompt resource 反向决定工具权限、动作面或输出提交。
- 不用兼容理由保留旧 lifecycle prompt 双轨。
- 不把技术 schema 重复写成自然语言 prompt。
- 不让 agent 自配 prompt set 绕过系统锁定 slot。

## 12. 预期结果

完成后，提示词系统会形成清晰治理结构：

- prompt library 存资源、pack、set。
- agent profile 绑定 prompt set。
- runtime 根据 agent、invocation、environment 和 state 生成 wiring plan。
- compiler 只编译 wiring plan。
- schema 和 metadata 承载技术协议。
- 每个 agent 可以拥有自己的提示词配置，但系统核心规则、动作协议和输出边界仍由 runtime 锁定。

这会让后续扩展新 agent、新环境、新工作角色、新工具协议时，不再需要在 compiler、assembly、environment controller、profile metadata 多处补线。
