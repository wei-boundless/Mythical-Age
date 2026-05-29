# Runtime Mode Prompt 投影优化计划

## 1. 结论

`mode` 是 runtime 装配控制项，不是 agent prompt 的直接权威来源。

当前 `RuntimeCompiler._mode_instruction()` 直接根据 `role / standard / professional` 拼接提示词。这是旧结构残留：它能临时告诉 agent 本轮模式含义，但会让 mode 名称越过装配层，直接进入 prompt 决策层。成熟 agent 架构中，模型不应依赖模式名理解系统能力，而应读取本次 runtime 装配后的可执行边界。

目标结构：

```text
runtime mode / profile / environment / task contract
-> RuntimeAssembly
-> AgentVisibleRuntimeProjection
-> RuntimeInvocationPacket
-> Agent action decision
```

## 2. 当前问题

### 2.1 Mode 被当成 prompt source

当前链路：

```text
RuntimeAssembly.profile.mode
-> RuntimeCompiler._mode_instruction(mode_policy)
-> system prompt
```

问题：

- mode 名称直接生成行为说明。
- prompt 中出现“当前 runtime 是 professional 模式”这类描述，说明 agent 在读模式名，而不是读装配结果。
- 如果以后新增自定义模式，容易继续复制 `_mode_instruction()` 分支。
- mode 与权限、工具、任务生命周期、上下文策略的真实装配结果可能产生重复或冲突。

### 2.2 Prompt 权威边界不干净

现在 agent 同时看到：

- mode instruction。
- environment instruction。
- work role prompt。
- stable payload 中的 profile / operation authorization / task environment。

这会形成多处行为解释源。正确结构应该是：

- mode/profile/environment 只参与装配。
- 装配结果生成一个 agent-visible runtime projection。
- prompt 只呈现 projection，不再单独解释 mode。

### 2.3 Cache 边界被弱化

`_mode_instruction()` 是 system prompt 的一部分。只要模式策略文案变动，第一段 system_static 变动，cache prefix 失效。后续应把稳定 prompt pack 与 runtime projection 分开。

本次先做结构修正，不扩大到完整 prompt pack 重构。

## 3. 目标设计

### 3.1 新增 AgentVisibleRuntimeProjection

它不是新的决策层，只是 `RuntimeAssembly` 的可见投影。

职责：

- 把已经装配完成的 runtime 边界转成 agent 能执行的自然语言。
- 不重新判断用户意图。
- 不根据关键词选择任务。
- 不授权工具。
- 不覆盖 task contract。
- 不输出内部 task id。

输入：

- `profile.mode`
- `profile.task_lifecycle_policy`
- `profile.planning_policy`
- `profile.self_review_policy`
- `profile.step_summary_policy`
- `profile.permission_policy`
- `profile.subagent_policy`
- `operation_authorization`
- `task_environment`
- invocation kind

输出：

- compact text：放入 system prompt。
- structured payload：放入 stable payload 的 `runtime_context.agent_visible_runtime_projection`，便于审计。

### 3.2 Agent 可见表达原则

不要写：

```text
当前 runtime 是 professional 模式。
```

应写：

```text
本次运行边界：
- 你可以直接回答、询问用户、调用本次可见工具。
- 当目标需要真实交付物、持续执行、文件修改、命令验证或失败恢复时，可以请求正式 TaskRun。
- 正式 TaskRun 收口必须基于合同、真实产物和验证证据。
```

这体现的是装配结果，不是模式名。

### 3.3 Mode 的保留位置

mode 仍保留在：

- `RuntimeAssembly.profile.mode`
- `RuntimeEnvelope.mode_policy`
- diagnostics / monitor / admin view

mode 不再作为 prompt 文案分支的直接来源。

## 4. 实施步骤

### Step 1：新增 projection helper

在 `backend/harness/runtime/compiler.py` 内新增小型 helper：

- `_agent_visible_runtime_projection(...) -> dict`
- `_runtime_projection_instruction(projection) -> str`

暂时放在 compiler 内，避免创建过早抽象。后续完整 prompt pack 重构时再迁入独立模块。

### Step 2：替换 `_mode_instruction()`

修改：

- `compile_turn_action_packet()`
- `compile_observation_followup_packet()`
- `compile_task_execution_packet()`

把：

```python
+ _mode_instruction(mode_policy)
```

替换为：

```python
+ _runtime_projection_instruction(agent_visible_runtime_projection)
```

TaskRun 执行 prompt 不需要重新解释 mode，但仍应呈现装配边界，如 TaskRun 内禁止再次 request_task_run、完成前自审等。

### Step 3：stable payload 加入结构化投影

在 `stable_payload["runtime_context"]` 中加入：

```json
"agent_visible_runtime_projection": {
  "allowed_action_types": [...],
  "task_lifecycle": {...},
  "planning": {...},
  "self_review": {...},
  "step_summary": {...},
  "tool_boundary": {...},
  "permission_boundary": {...},
  "environment_boundary": {...}
}
```

注意：不放 `mode_instruction`，不放模式解释文案。

### Step 4：删除 `_mode_instruction()`

确认没有引用后删除该函数。

### Step 5：测试

更新或新增 focused tests：

- turn action packet system prompt 不包含“当前 runtime 是 professional/standard/role 模式”。
- role mode 仍禁止 `request_task_run`。
- professional mode 仍允许 TaskRun，并要求真实交付、验证、自审。
- runtime_context 中存在 `agent_visible_runtime_projection`。
- environment prompt 仍能进入 system prompt。

## 5. 非目标

本次不做：

- 完整 prompt pack 文件化。
- 删除旧 `prompting` / `prompt_library`。
- 改 TaskRun 状态机。
- 改 graph prompt contract。
- 改工具权限判定。

这些属于下一阶段。

## 6. 验收标准

- 单 agent 主链不再由 mode 名称直接生成 prompt 文案。
- agent 仍能看见本次 runtime 的行动边界。
- role/standard/professional/custom 仍作为装配输入生效。
- 现有环境 prompt、work role prompt、soul role prompt 继续按边界装配。
- focused backend tests 通过。

