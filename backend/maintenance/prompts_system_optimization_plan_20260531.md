# Prompts 系统优化计划书（2026-05-31）

## 1. 背景

本轮审查基于单 agent 短搜索实测 `session-ab960fe175234c3b` 的真实 runtime packet、当前 prompt library、runtime compiler、task environment 与 skill runtime view。

短测证明：

- 单 agent 能完成普通联网搜索 turn。
- `web_search` 工具可见且可调用。
- skill candidate 已进入 runtime packet。
- 没有误启动正式 TaskRun。

同时暴露出 prompts 系统的结构问题：

- `runtime_invocation_packet` 首包 payload 约 120KB。
- 真正进入 `model_messages[*].content` 的内容约 56K 字符。
- 其中自然语言角色 prompt 不大，主要体积来自 stable contract、tool catalog、operation authorization、runtime envelope 与 task environment projection。
- 部分 prompt 是正向工作指令，部分是系统内部字段说明，部分是为了防旧链路的负向噪声。

本计划目标不是单纯压缩字数，而是重新校准 prompts 系统的职责边界：让 agent 看到足够理解和执行任务的内容，不把系统内部控制结构、冗余元数据和旧链路防御词塞给 agent。

## 2. 设计原则

### 2.1 模型只接收最小可执行投影

本地用于 trace、cache、manifest、segment、event、权限审计的结构，不应直接进入 `model_messages`。

模型应该看到：

- 当前身份和行动协议。
- 用户目标和历史必要摘要。
- 可选动作。
- 可见工具的最小调用说明。
- 当前环境资源边界。
- 当前任务合同或观察结果。
- 必要的失败事实和恢复要求。

模型不应该看到：

- 完整 runtime envelope。
- 完整 operation authorization deny 列表。
- 完整 task environment 配置对象。
- 本地 manifest、segment plan、payload ref、event ref。
- 与当前任务无关的旧控制字段。

### 2.2 Prompt 按职责分层，不能互相抢职责

目标分层如下：

| 类型 | 职责 | 不应承担 |
| --- | --- | --- |
| Runtime Protocol Prompt | 定义当前 invocation 可输出哪些 action，输出 JSON 规则 | 环境边界、工具细节、任务内容 |
| Agent Work Role Prompt | 定义 agent 工作姿态、职责、收口标准 | 权限授予、环境资源说明 |
| Environment Prompt | 定义资源空间、写入边界、artifact/storage 约束 | 工具授予、skill 选择、agent 行为风格 |
| Skill Candidate Card | 让 agent 判断是否激活某个 skill | 完整 skill 正文、重复输出规则、泛化系统原因 |
| Active Skill Body | 被 agent 选择后提供完整工作方法 | 覆盖用户目标、覆盖权限边界 |
| Stable Contract Projection | 本轮长期稳定、可缓存的执行协议摘要 | 完整系统对象、动态状态 |
| Dynamic Runtime Projection | 当前可变状态、权限摘要、观察/失败摘要 | 静态 prompt 重复、完整 deny 明细 |
| Volatile Current Request | 当前用户消息、必要历史、最新观察 | 完整 envelope、完整 trace |

### 2.3 优先正向表达，减少旧结构防御噪声

不要用大量“不要输出 X、不要暴露 Y、不要再走旧流程”的历史防御词污染 prompt。

应改为：

- 明确合法输出形态。
- 明确用户可见表达边界。
- 明确何时直接回答、何时调用工具、何时请求持续任务。
- 明确失败后怎么恢复。

例如：

当前问题写法：

```text
不要输出意图分类字段、任务类型字段、task_run_id 或其他内部控制协议。
```

目标写法：

```text
只输出当前 schema 允许的 JSON action。用户可见内容只描述任务进展、结果、问题或阻塞原因，不包含内部编号和系统结构。
```

### 2.4 Cache 优化不能伤害 agent 判断能力

缓存优化不是把重要上下文删掉，而是把稳定内容和动态内容分开：

- Global static：runtime protocol prompt。
- Session stable：agent role、environment boundary、tool catalog compact、skill candidate compact。
- Task stable：task contract、definition of done、artifact requirements。
- Dynamic：authorization summary、current failures、observations、current todo。
- Volatile：当前用户消息、最新工具结果、临时 steer。

高频变化字段不能混入 cacheable prefix，否则会破坏 prompt cache。

### 2.5 Skill 是 agent 自装配能力，不是系统替 agent 做意图识别

系统只暴露候选能力卡片，agent 自己决定是否选择。

不能按用户关键词硬编码选 skill。

但是候选卡片必须足够清楚：

- 这个 skill 能做什么。
- 什么时候该用。
- 什么时候不该用。
- 需要哪些工具/权限。
- 选择后会展开完整 skill body。

当前 `use_when` 写成“当前权限边界下可用”是错误职责，应修复。

## 3. 当前问题清单

### P0：operation authorization 过度暴露

位置：

- `backend/harness/runtime/compiler.py`
- `compile_turn_action_packet`
- `compile_observation_followup_packet`

现状：

- turn/followup dynamic payload 直接放入完整 `operation_authorization`。
- 短测中该字段约 13K 字符。
- 大量 deny decision 对模型没有直接执行价值。

问题：

- 增加 token 成本。
- 干扰 agent 注意力。
- 把系统权限裁决细节暴露给模型。
- 与自然语言 runtime boundary 重复。

目标：

- turn/followup 默认只给 summary：
  - allowed operation ids。
  - visible tool names。
  - critical denied capability groups。
  - permission scope。
  - authorization ref/hash。
- 完整 decisions 只保存在 trace，不进入 model messages。

### P0：task environment projection 过重

位置：

- `backend/harness/runtime/compiler.py::_environment_stable_payload`
- `backend/task_system/environments/default_environments.py`

现状：

- stable contract 中放入完整 task environment payload。
- 环境 prompt 正文已省略，但 file/resource/policy/space 仍大量进入模型。

问题：

- agent 不需要完整环境配置对象。
- environment prompt 与 stable environment payload 职责重复。
- 一些系统字段是给 runtime 用的，不是给 agent 决策用的。

目标：

- model-visible environment payload 只保留：
  - `environment_id`
  - `title`
  - `group_id`
  - `storage_space.environment_storage_root`
  - `storage_space.artifact_root`
  - `execution_boundary` 摘要
  - `write_boundary` 摘要
  - `environment_prompt_refs`
  - `policy_ref/hash`
- 完整环境对象只进入本地 trace。

### P0：runtime envelope 进入 current request 过重

位置：

- `backend/harness/runtime/compiler.py`
- `compile_turn_action_packet`
- `compile_observation_followup_packet`

现状：

- `volatile_payload.runtime_envelope = envelope.to_dict()`。
- 短测中 current request 约 6.4K 字符，大部分来自 envelope。

问题：

- envelope 是系统执行容器，不是 agent 语义上下文。
- 包含大量 agent 不需要直接推理的控制字段。

目标：

- turn/followup 也使用 `_runtime_envelope_model_visible()` 或新增更严格的 `turn_runtime_envelope_model_visible()`。
- 只保留：
  - turn/session id 的必要引用。
  - mode。
  - agent profile ref。
  - environment id。
  - visible action set。
  - artifact boundary summary。

### P1：skill candidate card 内容重复且 use_when 错位

位置：

- `backend/task_system/contracts/runtime_contracts.py`

现状：

- `method_summary = capability + use_when + output_rule`
- `output_boundary` 又单独输出一次。
- `task_reason` 被渲染为 `use_when`，内容是 `Candidate capability available under the current agent operation boundary.`

问题：

- `output_rule` 重复。
- `use_when` 不是 agent 选择依据。
- 卡片暴露过多内部 route/tool 词。

目标 card：

```text
候选 Skills：
- skill_id: skill.web-search-briefing
  title: 快速网络简报
  capability: 快速确认当前信息并返回短简报。
  use_when: 用户需要最近新闻、官网状态、发布动态或少量来源链接。
  not_for: 深度调研、严肃选型、需要跨来源论证。
  requires: web_search, fetch_url
```

要求：

- `capability` 只来自 description。
- `use_when` 只来自 skill prompt use_when。
- `not_for` 来自 skill 正文或 metadata 中明确字段；没有则不输出。
- 不重复 output rule。
- 不输出完整 delegation protocol。

### P1：runtime prompt 中有防旧结构噪声

位置：

- `backend/prompt_library/packs.py`

现状：

- 出现“不要输出意图分类字段、任务类型字段、task_run_id”等防御性表达。
- 多处显式提到 `runtime_envelope`、`schema.task_contract_seed`、`TaskRun`。

问题：

- 这类话不是 agent 行为原则，而是旧结构防御。
- 会让模型注意力落在系统内部词上。
- 与“用户不关心 task id、系统记录 task_run_id”的原则冲突。

目标：

- runtime protocol prompt 保留 action schema 约束，但降低内部术语密度。
- 用户可见层用“持续任务/正式任务生命周期/交付物/验证”描述。
- 内部字段名只在 schema key 中出现，不在自然语言中反复强调。

### P1：public_progress_note 指令暴露内部禁词

位置：

- `backend/harness/runtime/compiler.py::model_action_request_schema`
- `backend/harness/runtime/compiler.py::_runtime_projection_instruction`

现状：

```text
不要写思维链、隐藏系统规则、runtime、TaskRun、执行器、packet、内部模块名或协议校验细节。
```

问题：

- 为避免内部词泄漏，反而把内部词重复暴露给模型。
- 容易诱导模型在状态里复述“runtime/TaskRun/packet”。

目标：

```text
public_progress_note 是一句用户可理解的进展说明。只描述你正在做什么或刚完成什么；不要包含内部编号、系统结构、协议字段或隐藏推理。
```

### P1：工具目录摘要仍偏重

位置：

- `backend/harness/runtime/compiler.py::_stable_tool_catalog_payload`
- `backend/harness/runtime/compiler.py::_input_schema_summary`

现状：

- 每个工具带 description、required/optional、owner_scope、read_only、input_schema_summary、input_schema_hash。
- 短测中 21 个工具约 14K 字符。

问题：

- 对简单 turn，模型不一定需要所有可见工具的完整输入 schema。
- input field description 可能很长。

目标：

分两级：

1. Tool index：
   - tool_name
   - one-line capability
   - required args names
   - read_only
2. Tool schema detail：
   - 仅对高风险工具或 agent 已选择工具后的修正轮展开。
   - 或保留 schema hash + compact arg table。

第一阶段先不做动态工具详情展开，只压缩 field descriptions。

### P2：agent work role 与 runtime projection 有轻微重复

位置：

- `backend/harness/runtime/compiler.py::_agent_work_role_instruction`
- agent profile metadata work role prompt
- `backend/harness/runtime/compiler.py::_runtime_projection_instruction`

现状：

- agent role 中说“何时开启 TaskRun、工具失败如何恢复、自我审查”。
- runtime projection 中也说“何时请求持续处理、工具失败、最终完成证据、自我审查”。

问题：

- 原则重复。
- role prompt 应描述稳定身份和工作质量，runtime projection 应描述本轮具体可做什么。

目标：

- agent role：
  - 稳定职责、质量标准、用户目标优先、不能伪完成。
- runtime projection：
  - 本轮 action 边界、工具边界、任务生命周期边界、权限边界。

## 4. 目标架构

### 4.1 Model Message 目标结构

#### Turn Action

```text
1. system: runtime.turn_action.protocol.static
2. system: agent.work_role.static
3. system: environment.boundary.session_stable
4. system: tool.index.session_stable
5. system: skill.candidates.session_stable
6. system: runtime.dynamic_projection.volatile
7. user: current_request.volatile
```

#### Observation Followup

```text
1. system: runtime.observation_followup.protocol.static
2. system: agent.work_role.static
3. system: environment.boundary.session_stable
4. system: tool.index.session_stable
5. system: skill.candidates.session_stable
6. system: runtime.dynamic_projection.volatile
7. user: observations_and_request.volatile
```

#### Task Execution

```text
1. system: runtime.task_execution.protocol.static
2. system: agent.work_role.static
3. system: environment.boundary.session_stable
4. system: task.contract.task_stable
5. system: active.skills.task_stable_or_selected
6. system: tool.index.task_stable
7. system: runtime.dynamic_projection.volatile
8. user: current_execution_state.volatile
```

### 4.2 Cache 分层目标

| Segment | Cache Scope | 内容 |
| --- | --- | --- |
| global_static | global | runtime protocol prompt |
| agent_stable | session | agent work role |
| environment_stable | session | compact environment boundary |
| tool_index | session | compact tool index |
| skill_candidates | session | compact skill cards |
| task_contract | task | task goal / artifacts / definition of done |
| active_skills | task | selected skill bodies |
| dynamic_projection | none | authorization summary / failures / current facts |
| volatile_user | none | current user message / latest observations |

## 5. 实施计划

### 阶段 1：建立 prompt packet 审计器

目标：

- 在不改 runtime 行为前，先能稳定看到每类 message 的大小和来源。

文件：

- 新增或扩展 `backend/scripts/inspect_runtime_prompt_packet.py`

能力：

- 输入 payload ref 或 task_run_id。
- 输出：
  - message index
  - role
  - kind
  - source_ref
  - chars
  - cache_scope
  - 是否包含内部控制词
  - JSON payload 顶层字段大小

验收：

- 能对短测 packet 输出稳定 breakdown。
- 能定位 top 5 最大字段。

### 阶段 2：压缩 operation authorization model projection

目标：

- turn/followup 不再把完整 operation decisions 发给模型。

改动：

- 统一使用 `_operation_authorization_model_visible()`。
- 为 turn/followup 引入默认 projection policy：
  - `mode=summary_without_denials`
- summary 内容：
  - allowed_operations
  - denied_operation_count
  - critical_denied_groups
  - permission_scope
  - authorization_hash

验收：

- 短测 dynamic projection 至少减少 8K 字符。
- agent 仍能调用 `web_search`。
- denied 详情仍保存在 trace，不丢审计能力。

### 阶段 3：重写 environment model-visible payload

目标：

- stable contract 不再携带完整 environment 配置。

改动：

- 新增 `_environment_model_visible_payload()` 替代 `_environment_stable_payload()` 进入 model messages。
- 完整 environment payload 只保留在 event externalized payload / trace。

保留字段：

- environment_id
- title
- group_id
- storage_space.environment_storage_root
- storage_space.artifact_root
- execution_boundary summary
- write_boundary summary
- environment_prompt_refs
- policy_hash

验收：

- stable contract 中 task_environment 从约 10K 降到 1K 以内。
- environment prompt 仍正常进入 `environment_stable` message。
- 任务环境选择和 artifact root 不受影响。

### 阶段 4：压缩 runtime envelope projection

目标：

- current request 不再携带完整 envelope。

改动：

- turn/followup 使用 `turn_runtime_envelope_model_visible()`。
- task execution 继续使用更严格的 `_runtime_envelope_model_visible()`，并复查字段。

保留字段：

- session_id / turn_id / task_run_id（仅内部 JSON 字段，不用户可见）
- mode
- agent_profile_ref
- task_environment_id
- artifact boundary summary
- visible action set

验收：

- current request 减少 3K 以上。
- 不影响 action parser 和 trace。

### 阶段 5：重写 skill candidate card

目标：

- 保留二阶段 skill 装配，但候选卡片更短、更准确。

改动：

- `SkillRuntimeView` 拆分：
  - `capability`
  - `use_when`
  - `not_for`
  - `required_operations`
  - `canonical_path`
- 不再用 `method_summary` 拼接 capability/use_when/output_rule。
- `render_skill_candidate_cards()` 不重复 output rule。

验收：

- skill candidate 从约 5K 降到 2K 左右。
- `web-search-briefing` 和 `deep-web-research` 的 use_when 是真实选择条件。
- 短搜索任务能看到快速搜索 skill。
- 深度搜索任务至少能看到 deep research skill。

### 阶段 6：清理 runtime prompt 防旧结构噪声

目标：

- runtime prompt 更像专业 agent 控制协议，而不是旧链路防御说明。

改动：

- `backend/prompt_library/packs.py`
- 改写：
  - `runtime.turn_action.v1`
  - `runtime.observation_followup.v1`
  - `runtime.task_execution.v1`

原则：

- 保留 action schema 约束。
- 降低内部术语密度。
- 用“持续任务生命周期”替代反复暴露 `TaskRun`。
- 用“内部编号/系统结构/协议字段”替代列举 `runtime、packet、task_run_id`。

验收：

- prompt 中内部词出现次数下降。
- action JSON 解析测试通过。
- 普通对话不误启动任务。
- 需要真实交付物的任务仍会请求持续任务。

### 阶段 7：工具目录摘要瘦身

目标：

- 工具 index 足以让 agent 选择工具，但不塞完整冗余 schema。

改动：

- `_stable_tool_catalog_payload()`
- `_input_schema_summary()`

策略：

- description 限制为一行。
- field description 限制长度或默认省略。
- required args 保留。
- enum/default 保留。
- schema hash 保留。

验收：

- 21 个工具 catalog 从约 14K 降到 6K 以内。
- `web_search`、`fetch_url`、`write_file`、`edit_file`、`agent_todo` 参数仍足以被模型正确调用。

### 阶段 8：回归实测

必须做真实 CLI 测试：

1. 普通对话：
   - 不调用工具。
   - 不启动 task run。

2. 快速搜索：
   - 调用 `web_search`。
   - 返回精确来源链接。
   - 不启动 task run。

3. 深度搜索：
   - 候选 skill 可见。
   - agent 可以选择 deep search skill 或请求正式任务。
   - 如果调用子 agent，父任务必须完成收口。

4. 长任务：
   - 启动 TaskRun。
   - todo 正常记录。
   - artifact 真实存在。
   - 失败恢复不阻塞。
   - monitor 最终没有 active 残留。

5. Prompt cache 检查：
   - global/static/session stable segments 不因 current request 改变而破坏 hash。
   - dynamic/volatile 不进入 cacheable prefix。

## 6. 验收指标

### 成本指标

- 短测首包 `model_messages content` 从约 56K 字符降到 35K 以下。
- `payload_size_bytes` 从约 120K 降到 80K 以下。
- skill candidates 从约 5K 降到 2K 左右。
- operation authorization model-visible 从约 13K 降到 2K 以下。

### 质量指标

- 普通搜索必须返回真实来源链接。
- 需要原文确认时 agent 应使用 `fetch_url`。
- 任务启动判断仍由 agent 决定，不引入关键词启发式。
- 环境不授予工具，工具可见性仍只由 agent profile/权限决定。
- role/standard/professional/custom 模式仍只是 runtime 装配配置，不占据通用 loop 架构。

### 控制流指标

- 子 agent 完成后父任务必须能读取结果并收口。
- stop/resume 后 monitor 状态准确。
- 被停止或完成的任务不能继续显示为 active。

## 7. 风险与处理

### 风险 1：压缩 tool schema 后模型调用参数错误

处理：

- 保留 required args。
- 保留 enum/default。
- 对高风险工具保留必要 field description。
- 用 CLI 实测 `web_search`、`fetch_url`、`write_file`、`edit_file`。

### 风险 2：减少 authorization 明细后模型不知道为什么不能做某事

处理：

- summary 保留 critical denied groups。
- 真正越界时由 admission/tool observation 返回具体失败。
- 失败观察进入下一轮 dynamic context。

### 风险 3：减少 environment payload 后 artifact 边界不清

处理：

- environment model-visible payload 必须保留 artifact root 和 write boundary。
- environment prompt 继续说明资源边界。

### 风险 4：skill body 二阶段激活仍不稳定

处理：

- 候选卡片先变清楚。
- 后续可加明确 activation followup：当 model 返回 selected_skill_ids 且还未执行动作时，runtime 可先展开 skill body 再让模型决策。
- 本阶段不引入关键词选 skill。

## 8. 不在本计划内的事项

- 不重做图任务 runtime。
- 不重做前端图编辑器。
- 不引入关键词意图识别。
- 不改变 agent profile 权限模型。
- 不改变任务环境不授予工具的原则。
- 不为了通过测试伪造输出。

## 9. 推荐执行顺序

1. 阶段 1：prompt packet 审计器。
2. 阶段 2：authorization summary。
3. 阶段 3：environment projection。
4. 阶段 4：runtime envelope projection。
5. 阶段 5：skill cards。
6. 阶段 6：runtime prompt 文案清理。
7. 阶段 7：tool catalog 瘦身。
8. 阶段 8：CLI 实测与 trace 对照。

这个顺序先处理最大 token 成本，再处理 agent 理解质量，最后做真实行为回归，避免为了压缩 prompt 破坏工具调用和任务控制流。
