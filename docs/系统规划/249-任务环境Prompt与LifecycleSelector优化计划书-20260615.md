# 249-任务环境 Prompt 与 Lifecycle Selector 优化计划书

日期：2026-06-15  
状态：已实施（基础架构落地）  
适用范围：现有三套任务环境 prompt、拟新增纯聊天环境设计、environment lifecycle prompt、PromptMountPlan、prompt cache 稳定性、结构性回归测试  
不在范围：重写 runtime 主循环、改工具权限体系、改前端 UI、实现环境自动切换控制面、模型主动发起环境切换、删除现有任务环境、实现完整角色市场或角色编辑器

## 实施记录

2026-06-15 已按确认方向完成基础落地：

1. `environment_prompt_controller` 已将 lifecycle selector 收束为 core / capability / state 三层，并按 `ENVIRONMENT_LIFECYCLE_PROMPT_SLOTS` 固定顺序输出。
2. selector 不读取用户自然语言关键词；只根据 invocation kind、环境 ID、allowed actions、visible tools、active work、memory context、observations、execution state 和 session context 这些结构状态挂载 lifecycle prompt。
3. General 保持默认通用工作环境定位；普通无 active work / memory / compaction 的 single-agent turn 不再常驻挂载这些 state slots。
4. Coding 新增 `coding.rule.core_work_protocol`，作为短核心工作协议，放在 coding workspace boundary 后、细分 coding rule 前。
5. 新增独立 Chat 环境 `env.chat.role_conversation` 与 `environment_group.chat`，默认不挂任务 lifecycle，不暴露 tool_call / request_task_run，不继承 Coding / Office 规则。
6. 移除 controller 中模型主动环境切换 action 的未来占位，只保留用户/会话控制的环境选择声明。
7. 旧的 lifecycle 数量、消息下标和完整 segment 顺序断言已改为结构护栏：验证条件触发、cache 分层、环境隔离、prompt hygiene 和动态内容隔离。

仍留给后续独立设计的部分：

1. 角色市场、角色编辑器和角色 prompt schema。
2. Chat 专用 conversation lifecycle prompt 类型。
3. 角色长期记忆的写入策略、可视化管理和用户确认流程。

## 一、目标结论

本计划的目标是在不破坏 prompt cache 的前提下，收紧三套任务环境的 lifecycle selector，使模型每轮只看到当前阶段真正需要的生命周期规则，减少 prompt 噪声，提升 coding agent 的执行稳定性。

本次优化不是继续堆更长 prompt，而是把当前 prompt 体系收束为：

```text
稳定核心 prompt
-> 稳定结构条件触发的 lifecycle prompt
-> volatile runtime/context facts
```

其中：

- 稳定核心 prompt 保持 `static_environment`，适合进入 provider prompt cache 和项目内部 prompt authority cache。
- 条件 lifecycle prompt 只由稳定结构条件触发，例如 invocation kind、环境 ID、可见 action、可见工具、active work 是否存在、memory payload 是否存在。
- 用户文本、工具输出、报错文案、观察内容细节只能进入 volatile runtime/context payload，不能驱动 stable prompt refs 频繁变化。

目标状态：

1. Coding 环境保留成熟 coding loop 的关键纪律，但减少无条件挂载的低相关 lifecycle slot。
2. Office 环境继续作为轻量办公文件检索环境，不引入 coding 执行规则。
3. General 环境保持“默认通用入口”定位，让用户不必先判断场景也能直接开始使用；它不是轻量环境，也不是过渡环境。
4. 新增纯聊天环境时，应作为独立 chat kind，而不是 General 的低配版；它主打角色氛围、会话延续和表达风格，不进入任务执行心智。
5. PromptMountPlan 的 refs 顺序稳定、原因可追踪、cache 指纹可复查。
6. 测试只作为结构护栏；旧测试如果保护旧遗漏、旧 selector 或旧消息位置，应删除或重写，不能反向决定 prompt 架构。

## 二、当前现状与依据

### 2.1 当前三套环境定义与目标四环境分层

当前项目内置三套任务环境：

| 环境 ID | 类型 | 当前定位 |
| --- | --- | --- |
| `env.coding.vibe_workspace` | coding | 专用编码工作区，支持项目检查、实现、调试、验证、shell、git、artifact 和 file state |
| `env.office.file_search` | office | 轻量办公文件检索，支持文件读取、整理、来源检索和办公产物，不支持 shell/git/code execution |
| `env.general.workspace` | general | 默认通用工作区，用户不必预先选择场景即可使用；承载问答、资料整理、混合任务、多步骤执行和未归入专门环境的通用工作 |

当前三套环境中，只有 Office 是轻量办公型环境；General 不是轻量环境，也不应被写成“轻任务环境”。General 的职责是通用、宽口径、默认可用，让用户不管什么场景都能先直接用起来。专用 Coding / Office / Chat 环境是更强的专业化入口，不是 General 能力的削弱理由。

建议新增第四套环境：

| 环境 ID 建议 | 类型 | 目标定位 |
| --- | --- | --- |
| `env.chat.role_conversation` | chat | 纯聊天与角色氛围环境，只挂基本系统规则、上下文拼接、角色/人格 prompt 和会话安全边界，不挂任务执行 lifecycle、工具调度、代码/办公工作流 |

核心定义位于：

- `backend/task_system/environments/default_environments.py`
- `backend/task_system/environments/prompt_resources.py`
- `backend/prompt_library/environment_lifecycle_prompts.py`
- `backend/harness/runtime/environment_prompt_controller.py`

### 2.2 当前 Coding 环境的优点

`env.coding.vibe_workspace` 已经具备成熟 coding agent 的基础要素：

- 独立 coding environment prompt。
- 受管项目工作区资源提示。
- sandbox overlay 资源提示。
- 文件管理规则。
- codebase inspection。
- large scope exploration。
- editing rule。
- verification rule。
- debug discipline。
- git safety。
- Windows shell discipline。
- task progress rule。
- environment lifecycle prompt defaults。
- prompt authority / prompt mount plan。

抽样结果显示，Coding 环境当前 base environment refs 为 13 个：

```text
runtime.rule.file_management.generic
environment.resource.managed_project_workspace.orientation
environment.resource.sandbox_overlay.orientation
environment.coding.vibe_workspace.orientation
environment.rule.coding_workspace
coding.rule.codebase_inspection
coding.rule.large_scope_exploration
coding.rule.editing
coding.rule.verification
coding.rule.debug_discipline
coding.rule.git_safety
coding.rule.windows_shell
coding.rule.task_progress
```

这说明当前体系已经不是简单的“你是 coding agent”式提示词，而是有资源、权限、文件、验证和收口纪律的环境化 prompt。

### 2.3 当前主要问题

#### 2.3.1 Lifecycle slot 挂载偏宽

当前 selector 在多个 invocation 下会挂载 11-14 个 lifecycle slot。抽样结果：

| 环境 | base chars | single_agent_turn lifecycle | task_execution lifecycle | observation followup lifecycle |
| --- | ---: | ---: | ---: | ---: |
| Coding | 约 3070 | 14 slots / 约 4127 chars | 14 slots / 约 3127 chars | 11 slots / 约 2666 chars |
| Office | 约 959 | 14 slots / 约 3187 chars | 14 slots / 约 2275 chars | 11 slots / 约 1950 chars |
| General | 约 804 | 14 slots / 约 3283 chars | 14 slots / 约 2565 chars | 11 slots / 约 2221 chars |

这会带来两个风险：

1. 模型每轮看到过多不相关规则，注意力被稀释。
2. lifecycle selector 的行为越来越像“安全感清单”，而不是按运行阶段精确挂载。

#### 2.3.2 General 环境存在 selector 结构漂移，但不能被降级成轻量环境

当前 General single-agent turn 会挂载以下 lifecycle refs：

```text
environment.general.lifecycle.context_intake
environment.general.lifecycle.request_judgment
environment.general.lifecycle.work_relation
environment.general.lifecycle.environment_capability_alignment
environment.general.lifecycle.plan_gate
environment.general.lifecycle.action_selection
environment.general.lifecycle.user_steer_contract_revision
environment.general.lifecycle.task_run_handoff
environment.general.lifecycle.tool_dispatch
environment.general.lifecycle.memory_read_context
environment.general.lifecycle.compaction_handoff
environment.general.lifecycle.finalization
```

这说明当前 selector 存在结构漂移：一些 active work、memory、compaction 类 slot 在缺少对应结构状态时也可能进入 prompt。这里的判断不以旧测试预期为准，而以目标 prompt 架构为准：General 是通用工作环境，可以很强，但不应让无状态支撑的 lifecycle prompt 常驻污染每轮判断。

需要特别澄清：General 的 selector 收紧不是把 General 降级成轻量环境。General 仍然是通用工作环境，可以承载多步骤执行、文件处理、资料整理、一般研究和混合任务。收紧的对象只是“无状态支撑的 lifecycle prompt 常驻挂载”，不是削弱 General 的任务能力。

#### 2.3.3 旧测试不能约束新 prompt 架构

当前测试体系中仍存在两类不应继续保护的旧测试：

1. 固定旧 lifecycle 数量的测试。
2. 依赖 `packet.model_messages[-2]` 这类消息位置的测试。

这些测试保护的是旧实现形态，不是 agent prompt 体系的成熟结构。后续实施时，如果某个测试只是保护旧遗漏、旧 selector、旧消息顺序、旧字段或旧 prompt 拼接方式，应直接删除或重写为结构护栏。不能为了让旧测试通过而保留次等 prompt 结构。

成熟 prompt packet 测试应验证：

- prompt authority 顺序是否正确。
- lifecycle selector 是否按结构状态触发。
- stable prompt 和 volatile context 是否分层。
- role prompt、environment prompt、runtime protocol prompt 是否分层。
- Chat / General / Office / Coding 是否互不污染。

不应验证：

- 某个旧数组下标。
- 某个过时固定 refs 数量。
- 某个旧 diagnostic 字段是否仍存在。
- 某个旧 prompt 拼接顺序是否被兼容保留。

#### 2.3.4 Prompt hygiene 覆盖面偏窄

当前已有测试检查 coding 静态 prompt 不含开发说明式语言，例如：

```text
这是 runtime 节点
根据任务图执行
runtime packet
```

但覆盖范围主要是 coding environment refs，没有系统覆盖：

- runtime pack prompt。
- utility repair prompt。
- compiler dynamic instruction。
- lifecycle prompt。
- graph node prompt。

对 agent 项目而言，prompt hygiene 必须覆盖所有会进入模型的 prompt 层，防止开发说明被当成 agent prompt。

## 三、成熟 Agent 标准对照

成熟 coding agent 的 prompt 体系不应只追求“规则多”，而应具备以下工程特征：

```text
稳定身份与职责
-> 明确工作循环
-> 工具与权限边界
-> 当前状态观察
-> 失败恢复策略
-> 验证与收口标准
```

对 Coding 环境，成熟标准至少包括：

1. 不把普通问答自动扩大成代码修改。
2. 修改前先读取当前代码事实。
3. 对未知位置先定位文件、调用链、配置入口和测试入口。
4. 编辑保持最小必要变更，遵循既有架构。
5. 调试时基于失败证据定位第一次偏离，不猜修。
6. 修改后按风险运行真实测试、构建、类型检查、服务或浏览器验证。
7. git 操作只在用户明确要求时执行，且不碰用户已有改动。
8. 工具失败后必须改变假设、参数、路径或计划。
9. 收口时只报告真实修改、真实验证和剩余风险。

当前项目大部分规则已经存在，但分散在多段 prompt 中，缺一个短而高优先级的 Coding 核心工作协议来压住模型主行为。

## 四、Prompt Cache 风险分析

### 4.1 收紧 selector 不等于破坏 cache

收紧 lifecycle selector 本身不会破坏 prompt cache。真正影响 cache 的是：

```text
每轮 stable prompt refs 是否频繁变化
refs 顺序是否漂移
stable section 内容是否动态生成
动态事实是否误入 stable prefix
```

如果 selector 按稳定结构条件触发，并保持 refs 顺序固定，cache 不会被破坏，反而会更干净。

### 4.2 正确收紧方式

允许作为 selector 条件的稳定因素：

- `invocation_kind`
- `selected_environment_id`
- allowed action types
- visible tool names / tool kinds
- active work context 是否存在
- pending user steer 是否存在
- memory context 是否非空
- observations 是否非空
- execution_state 是否有 compaction/recovery/plan mode 标记
- prompt pack 是否为 graph node execution

不允许作为 selector 条件的高波动因素：

- 用户自然语言关键词。
- 具体报错字符串。
- 工具输出正文。
- 文件名片段。
- 搜索命中内容。
- 模型上一轮自然语言表述。
- 未结构化历史摘要。

这些高波动事实应进入 volatile runtime context，不应改变 stable lifecycle refs。

### 4.3 Cache 保护规则

1. `PromptResource.content` 不动态生成。
2. lifecycle prompt 保持 `cache_scope="static_environment"`。
3. selector 只输出 prompt refs，不拼接动态文本。
4. refs 按 `ENVIRONMENT_LIFECYCLE_PROMPT_SLOTS` 固定顺序输出。
5. `lifecycle_trigger_reasons` 只进入 diagnostics，不进入 stable prompt 内容。
6. dynamic runtime facts 继续放入 `Task execution runtime boundary`、`Task execution current state` 等 volatile packet。
7. 同一结构状态重复编译，`prompt_mount_plan.lifecycle_prompt_refs` 必须完全一致。

## 五、目标 Selector 设计

### 5.1 三层选择模型

建议将 `prompt_mount_plan_for_invocation()` 内部的 lifecycle 选择拆成三层：

```text
core slots
capability slots
state slots
```

#### Core slots

由 `invocation_kind + environment_kind` 决定，稳定常驻。

#### Capability slots

由 allowed actions 和 visible tools 决定，例如是否允许 tool_call、request_task_run、active_work_control，是否存在 subagent tools。

#### State slots

由结构化 runtime state 决定，例如 active work、pending steer、memory context、observations、compaction/recovery 标记。

输出仍保持：

```text
LifecyclePromptSelection(
    refs=...,
    keys=...,
    trigger_reasons=...,
    omitted_keys=...,
)
```

但 trigger reason 建议增加分类前缀：

```text
core: task_execution requires verification gate
capability: tool_call action is allowed
state: active_work_context is present
state: memory_context is present
```

### 5.2 固定排序

无论 slot 来自 core、capability 还是 state，都必须按 `ENVIRONMENT_LIFECYCLE_PROMPT_SLOTS` 顺序输出，不能按触发顺序输出。

目标算法：

```text
1. 生成 selected_keys set
2. 按 ENVIRONMENT_LIFECYCLE_PROMPT_SLOTS 遍历
3. 如果 key in selected_keys，则 resolve prompt ref
4. dedupe refs
5. 输出 refs / keys / trigger_reasons
```

这样可以保证 cache 指纹稳定。

## 六、Coding 环境优化方案

### 6.1 新增 Coding 核心工作协议

建议新增一个短核心 prompt，例如：

```text
coding.rule.core_work_protocol
```

内容建议：

```text
你是一名项目级 coding agent。
你先根据用户目标判断是否需要改代码；普通解释、审查和方案讨论不要自动扩大为修改。
需要修改时，先定位相关文件、调用链、配置入口、测试入口和已有改动。
修改前必须有当前读窗证据；修改后必须按风险运行真实验证。
失败时先定位第一次偏离，不要猜修，不要原样重试。
收口时只报告真实修改、真实验证、未验证风险和后续条件。
```

该 prompt 的定位不是替代现有规则，而是作为 coding 工作心智的短主轴，减少模型在多段规则之间来回找主线。

### 6.2 Coding single_agent_turn slot 策略

#### 常驻 core slots

```text
context_intake
request_judgment
environment_capability_alignment
plan_gate
action_selection
finalization
```

理由：

- single-agent turn 必须先判断用户到底是问答、审查、实现、修复、重构、运行验证还是控制当前工作。
- plan gate 对 coding 高风险改动必要。
- finalization 防止把工具状态或计划当完成。

#### 条件 slots

| Slot | 触发条件 |
| --- | --- |
| `work_relation` | active work context 存在 |
| `active_work_control` | `active_work_control` action 可用且 active work fresh |
| `user_steer_contract_revision` | pending steer 存在，或 active work context 存在 |
| `task_run_handoff` | `request_task_run` action 可用 |
| `tool_dispatch` | `tool_call` action 可用且 visible tools 非空 |
| `subagent_delegation` | subagent tools 可见 |
| `memory_read_context` | memory context 非空 |
| `compaction_handoff` | session context 或 execution state 显示压缩/恢复边界 |

### 6.3 Coding task_execution slot 策略

#### 常驻 core slots

```text
context_intake
environment_capability_alignment
action_selection
tool_observation_recovery
verification_gate
finalization
```

理由：

- task_execution 已经处在持续任务合同内，不需要每轮挂 request_judgment。
- 工具观察恢复、验证、收口是 coding 任务核心。
- action_selection 保证每轮只选择一个 schema-valid next action。

#### 条件 slots

| Slot | 触发条件 |
| --- | --- |
| `plan_gate` | plan mode、合同要求计划、或 execution_state 标记高风险结构改动 |
| `user_steer_contract_revision` | pending user steer 非空 |
| `tool_dispatch` | 可见工具非空且 `tool_call` action 可用 |
| `subagent_delegation` | subagent control tools 可见 |
| `subagent_result_integration` | observations 中存在 subagent result |
| `memory_read_context` | memory context 非空 |
| `memory_write_handoff` | memory write capability 可见，或 closeout 阶段存在稳定结论候选 |
| `compaction_handoff` | compaction/recovery/long task boundary 存在 |

### 6.4 Coding tool_observation_followup slot 策略

#### 常驻 core slots

```text
context_intake
tool_observation_recovery
action_selection
finalization
```

#### 条件 slots

| Slot | 触发条件 |
| --- | --- |
| `environment_capability_alignment` | 工具失败、权限拒绝、工具不可见、端口/依赖/路径问题 |
| `tool_dispatch` | 观察后仍允许继续 tool_call |
| `task_run_handoff` | followup 可升级到持续任务 |
| `subagent_result_integration` | 当前 observation 是 subagent result |
| `subagent_delegation` | 后续仍可调 subagent tools |
| `memory_read_context` | memory context 非空 |
| `compaction_handoff` | recovery/compaction 标记存在 |

## 七、Office 环境优化方案

Office 环境当前定位较清楚，应继续保持窄边界：

- 文件读取。
- 本地搜索。
- 来源检索。
- 表格/文档/材料整理。
- 可复核办公产物。

不应自动挂载 coding 类执行 prompt，也不应让 shell、git、代码执行、浏览器自动化出现在模型心智中。

### 7.1 Office single_agent_turn core slots

```text
context_intake
request_judgment
environment_capability_alignment
action_selection
finalization
```

### 7.2 Office 条件 slots

| Slot | 触发条件 |
| --- | --- |
| `task_run_handoff` | 多文件整理、来源核验、产物生成需要持续任务 |
| `tool_dispatch` | 文件/检索工具可见 |
| `tool_observation_recovery` | 文件不存在、格式不可解析、搜索失败、来源不可达 |
| `verification_gate` | 生成办公产物、引用外部来源、表格/文档结构需要检查 |
| `memory_read_context` | memory context 非空 |
| `compaction_handoff` | 大材料整理或恢复场景 |
| `subagent_delegation` | 大范围资料研究、PDF/表格分析、外部来源核验复杂 |

### 7.3 Office 禁止事项

Office lifecycle 不应包含：

- coding inspection。
- coding editing。
- coding verification。
- git safety。
- Windows shell discipline。
- coding debug discipline。

如果用户目标需要这些能力，应由模型说明当前 Office 环境的能力边界，并在当前环境内完成可完成的部分；是否切到 Coding 环境由用户手动选择，模型不得主动发起环境切换。

## 八、General 环境优化方案

General 是通用工作环境，不是轻量环境。它的职责是承载没有被明确归入 Coding、Office、Chat 或图任务专用环境的通用工作，包括问答、资料整理、一般研究、文件处理、混合任务和多步骤执行。

当前 General single-agent turn 实际挂载了 `work_relation`、`user_steer_contract_revision`、`memory_read_context`、`compaction_handoff` 等 slot。对于普通问答，这些规则可能增加噪声，并使旧任务、旧记忆、压缩恢复过度影响新请求。

因此 General 的优化目标不是削弱能力，而是避免无状态支撑的 lifecycle prompt 抢占通用判断。General 仍可启动任务、读取文件、调用工具、做资料整理或混合执行；只是它不应默认套用 Coding 的工程闭环，也不应默认进入纯聊天角色氛围。

### 8.1 General single_agent_turn core slots

```text
context_intake
request_judgment
environment_capability_alignment
action_selection
finalization
```

### 8.2 General 条件 slots

| Slot | 触发条件 |
| --- | --- |
| `work_relation` | active work context 存在 |
| `active_work_control` | active work fresh 且 control action 可用 |
| `user_steer_contract_revision` | pending steer 或 active work context 存在 |
| `task_run_handoff` | `request_task_run` action 可用且目标需要多步执行 |
| `tool_dispatch` | `tool_call` action 可用且 visible tools 非空 |
| `tool_observation_recovery` | invocation 是 observation followup，或 observations 非空 |
| `memory_read_context` | memory context 非空 |
| `compaction_handoff` | compaction/recovery 标记存在 |
| `subagent_delegation` | subagent tools 可见且任务范围适合委派 |

### 8.3 General 与专用环境的分工

General 可以直接承载大量通用工作，包括用户尚未明确分类的复杂任务。以下场景有更贴合的专用环境，但这只是产品分工说明，不代表 General 只能中转或只能轻量处理，也不要求模型主动发起环境切换：

- 真实 coding 修改、重构、调试、测试验证：优先 Coding。
- 轻量办公文件检索、表格/文档整理、来源核验办公产物：优先 Office。
- 角色陪伴、氛围对话、人格表达、纯聊天：优先 Chat。
- 图任务节点专业执行：优先图任务环境。

General 的定位是“默认通用工作面”，不是“轻量工作面”。复杂任务可以从 General 发起并推进；当任务目标明确属于某个专用环境时，模型只需说明当前环境边界和当前可完成范围，不主动发起切换。用户如果想使用专用环境，可以自己在 UI 中手动调整。

## 九、纯聊天环境设计方案

### 9.1 设计判断

新增纯聊天环境是合理的，而且建议作为独立 environment kind：`chat`。

它不应是 General 的低配版，也不应继承 Coding / Office 的任务执行心智。纯聊天环境的价值是：

- 主打角色氛围。
- 保持会话连续性。
- 强化人格、语气、关系感和表达风格。
- 支持轻量上下文拼接。
- 避免工具、任务、验证、artifact、git、shell 等工作流规则污染对话体验。

如果项目主打“给角色氛围”，这个环境非常必要。否则 General 会同时承担通用工作和角色聊天，prompt 会天然拉扯：一边要求任务判断、工具执行、验证收口，一边要求氛围、陪伴、表达风格。成熟方案应该把它们拆开。

### 9.2 建议环境 ID 与定位

建议新增：

```text
env.chat.role_conversation
```

或更短：

```text
env.chat.pure_conversation
```

推荐使用 `env.chat.role_conversation`，因为它明确表达“角色氛围”和“会话”两个重点。

### 9.3 Chat 环境能力边界

Chat 环境默认能力应非常克制：

| 能力 | 默认策略 |
| --- | --- |
| shell / terminal | denied |
| browser automation | denied |
| git | denied |
| code execution | denied |
| file write/edit | denied |
| file read/search | 默认 denied；如后续支持角色资料库，可通过专用 profile 或显式材料上下文提供 |
| network/search | 默认 denied；如果角色设定需要联网事实，应切 General 或 Research 类环境 |
| artifact | 默认不生成正式 artifact；仅允许会话文本 |
| memory | 可读写角色长期记忆，但必须有专门边界，不把所有聊天内容自动长期化 |
| task_run | 默认不启动持续任务 |

Chat 环境只应看到：

```text
基础系统 prompt
当前会话上下文
角色/人格 prompt
用户可见的对话历史摘要
必要的安全与边界规则
```

### 9.4 Chat Prompt 层级

推荐层级：

```text
system foundation
-> chat environment boundary
-> role/personality prompt
-> relationship/context memory
-> current conversation context
```

其中：

- `system foundation` 负责底线安全和通用输出边界。
- `chat environment boundary` 只说明当前是纯聊天，不执行工具任务，不伪造外部事实。
- `role/personality prompt` 是主角，负责身份、语气、关系、情绪表达和风格。
- `relationship/context memory` 只放稳定关系事实、用户偏好和角色连续性，不放可重新从历史读取的普通闲聊。
- `current conversation context` 负责最近对话连续性。

不要把 Chat prompt 写成：

```text
这是聊天环境。
用于普通聊天。
```

应写成：

```text
你正在进行一场以角色氛围和关系连续性为核心的对话。
你优先保持角色声音、情绪质感、上下文延续和自然回应。
你不主动启动任务、不调用开发工具、不伪造文件读取或外部检索。
当用户转向需要真实执行、文件处理、代码修改或来源核验的目标时，你需要说明当前聊天环境的能力边界，并继续完成当前环境内能完成的部分。是否切到其他工作环境由用户手动决定；你不要主动发起环境切换。
```

### 9.5 Chat Lifecycle 策略

Chat 环境不建议复用当前 18 个通用 environment lifecycle slots。原因是这些 slot 大多围绕任务执行、工具派发、子 agent、验证、memory handoff、compaction handoff 和 finalization，容易破坏角色氛围。

更成熟的方案是给 chat kind 单独定义轻量 conversation lifecycle，或在当前 selector 中对 Chat 环境使用极小 core：

```text
conversation_context_intake
role_consistency
conversation_boundary
response_style
```

如果短期不新增新 lifecycle 类型，也可以只挂：

```text
context_intake
finalization
```

但这只是过渡方案。长期建议不要把 task lifecycle 套到纯聊天环境。

### 9.6 Chat 与 General 的边界

| 用户目标 | 推荐环境 |
| --- | --- |
| 陪伴、角色扮演、氛围聊天、情绪交流 | Chat |
| 普通问答、解释、轻量建议、未分类请求 | General 默认承接；如果用户处在角色对话入口，则 Chat 承接 |
| 文件处理、资料整理、来源核验 | Office 或 General |
| 编程实现、调试、测试、重构 | Coding |
| 多节点创作/审核/流程化任务 | TaskGraph / 专用环境 |

关键原则：

```text
Chat 负责氛围和关系。
General 负责默认通用工作入口，保证用户不选场景也能直接使用。
Office 负责轻量办公文件检索。
Coding 负责真实工程执行。
```

### 9.7 Chat 与 Prompt Cache

Chat 环境有利于 prompt cache：

- 基础系统 prompt 稳定。
- chat environment boundary 稳定。
- 角色 prompt 可作为 session-stable 或 role-stable segment。
- 当前对话上下文放 volatile。
- 角色长期记忆用结构化 memory projection，不直接把整段历史塞进 stable prompt。

需要避免：

- 每轮动态重写角色 prompt。
- 把用户最新情绪和长历史全塞入 stable role prompt。
- 根据用户文本临时拼不同的系统规则。

### 9.8 Chat 测试要求

新增 Chat 环境后，应增加结构测试：

```text
test_chat_environment_exposes_no_development_tools
test_chat_environment_uses_role_prompt_layer
test_chat_environment_does_not_mount_coding_or_office_rules
test_chat_environment_does_not_request_task_run_by_default
test_chat_role_prompt_is_session_stable
test_chat_dynamic_context_does_not_mutate_stable_role_prompt
```

### 9.9 Chat 实施建议

建议把 Chat 环境作为本计划的后续 Phase，而不是和 lifecycle selector 收紧混在同一批直接落代码。

原因：

1. 新增 environment kind 会影响 registry、catalog、prompt mount plan、UI 选择和测试。
2. Chat 最好有独立 role prompt / personality prompt 管理，不应简单塞进 General。
3. 如果角色氛围是产品主打能力，应单独设计角色 prompt schema、角色记忆边界和会话风格测试。

推荐顺序：

```text
先修正 General / Office / Coding selector
-> 再新增 Chat environment kind
-> 再接角色 prompt 管理和角色记忆
```

## 十、Prompt 文案优化要求

### 10.1 Agent-facing 语言

所有进入模型的 prompt 都必须写给 agent 执行，而不是写给开发者理解。

禁止：

```text
这是 runtime 节点。
根据任务图执行 xxx。
这个节点用于校验资产。
```

应写成：

```text
你是一名世界观审核员。
你只负责评审当前世界观设定是否完整、一致、可支撑后续写作。
你不负责替创作者扩写设定。
你需要指出问题、给出裁决、说明是否允许进入下一阶段。
```

### 10.2 协议语言与角色语言分离

角色 prompt 描述：

- 身份。
- 职责。
- 边界。
- 输入。
- 输出。
- 判断标准。
- 失败处理。

协议 prompt 描述：

- JSON schema。
- action type。
- authority 字段。
- tool call 格式。
- admission 结果处理。

环境 prompt 不应承担 schema 教学，schema prompt 不应承担业务角色定义。

### 10.3 权限语言收紧

应区分：

| 类型 | 推荐表述 | 禁止泛化 |
| --- | --- | --- |
| 安全/沙盒/审批拒绝 | permission denied / safety denied | 不要用于 active work 状态不匹配 |
| 工具或资源不可用 | operation unavailable | 不要说用户请求被拒绝 |
| 当前任务过期或不匹配 | state mismatch | 不要说系统不允许回应 |
| 模型动作结构错误 | contract invalid | 不要说用户不能这样问 |
| 可交回模型恢复的问题 | observation | 不要在模型前直接形成最终拒绝正文 |

## 十一、结构护栏与旧测试清理方案

### 11.1 旧测试处理原则

本计划不以修复旧测试为目标。测试只服务于目标 prompt 架构；如果测试保护旧遗漏，应删除或重写。

必须删除或重写的测试类型：

- 断言旧 lifecycle refs 固定数量的测试。
- 依赖 `packet.model_messages[-2]` 等数组位置的测试。
- 保护旧 prompt 拼接顺序的测试。
- 保护旧 selector 常驻挂载策略的测试。
- 保护旧 diagnostic 字段存在的测试。
- 为旧 runtime 结构兜底的语义测试。

保留或新增的测试必须是结构性测试：

- core slots 必含。
- 条件 slots 必须有结构状态支撑。
- prompt authority 顺序稳定。
- stable prompt 不含 volatile runtime facts。
- environment / role / runtime protocol 不互相越权。
- Chat / General / Office / Coding 环境互不污染。

### 11.2 新增 selector 结构护栏

建议新增结构护栏：

```text
test_lifecycle_selector_keeps_core_slots_for_each_environment
test_lifecycle_selector_omits_active_work_slots_without_active_work
test_lifecycle_selector_omits_memory_slots_without_memory_context
test_lifecycle_selector_omits_subagent_slots_without_subagent_tools
test_lifecycle_selector_keeps_stable_order_for_same_structural_state
test_lifecycle_selector_does_not_use_user_text_keywords
test_chat_environment_does_not_mount_task_lifecycle_by_default
```

### 11.3 新增 prompt cache 稳定护栏

结构护栏目标：

1. 同一环境、同一 invocation、同一结构状态下，重复 compile packet。
2. 断言：

```text
prompt_mount_plan.lifecycle_prompt_refs 相同
prompt_mount_plan.base_prompt_refs 相同
section_fingerprint 相同
cache_scope_order 相同
```

3. 改变 volatile 用户文本，不应改变 lifecycle refs。
4. 改变结构状态，例如添加 memory_context，才允许增加 memory slot。

### 11.4 Prompt hygiene 结构护栏

检查范围应包括：

- environment prompts。
- lifecycle prompts。
- runtime packs。
- utility prompts。
- compiler dynamic instruction。
- graph node execution prompt。

禁止 marker 至少包括：

```text
这是 runtime 节点
根据任务图执行
这个节点用于
该节点用于
本节点用于
这是一个 runtime
runtime packet
developer note
```

注意：不是禁止出现 `runtime` 这个词本身，而是禁止开发说明式 prompt。

## 十二、实施阶段

### Phase 0：现状快照

目标：在改代码前生成三环境 prompt mount 基线。

动作：

1. 输出三环境在 `single_agent_turn`、`task_execution`、`tool_observation_followup` 下的：
   - base refs
   - lifecycle refs
   - lifecycle keys
   - chars
   - trigger reasons
   - section fingerprint
2. 保存为审查记录或测试 fixture。

完成标准：

- 有可复查基线。
- 不改行为。

### Phase 1：Selector 结构拆分

目标：将当前 `_lifecycle_prompt_selection_for_invocation()` 拆成可读、可测的三层选择。

建议函数：

```python
_core_lifecycle_keys_for_invocation(...)
_capability_lifecycle_keys(...)
_state_lifecycle_keys(...)
_ordered_lifecycle_selection(...)
```

完成标准：

- 输出结构不变。
- 不为旧测试回退目标结构；旧测试若保护旧结构，应删除或重写。
- diagnostics 能区分 core/capability/state 原因。

### Phase 2：先收紧 General / Office

目标：先在低风险环境跑通条件 slot 模式。

动作：

1. General 无 active work 时不挂 `work_relation`。
2. General 无 memory context 时不挂 `memory_read_context`。
3. General 无 compaction/recovery 标记时不挂 `compaction_handoff`。
4. Office 不挂与当前办公任务无关的 active work / memory / compaction slot。

完成标准：

- General selector 按目标结构收紧；旧测试若保护旧数量或旧顺序，应删除或重写。
- Office 不被 coding 或 General 工作控制规则污染。

### Phase 3：收紧 Coding

目标：保留 coding 成熟工作闭环，减少无条件挂载。

动作：

1. Coding `single_agent_turn` 保留 request judgment、plan gate、action selection、finalization 等核心。
2. Coding `task_execution` 保留 tool recovery、verification、finalization 等核心。
3. active work、steer、memory、subagent、compaction 改为条件触发。
4. 不根据用户文本关键词触发。

完成标准：

- Coding task_execution 仍包含开发任务必要纪律。
- 无 active work 不挂 active work 类 slot。
- 无 memory payload 不挂 memory 类 slot。
- 无 subagent 工具不挂 subagent delegation。

### Phase 4：新增 Coding 核心协议

目标：给 coding agent 一个短主轴，降低多规则之间的冲突。

动作：

1. 新增 `coding.rule.core_work_protocol`。
2. 将其加入 Coding base refs，位置在 environment rule 之后、细分 coding rule 之前。
3. 更新结构护栏，删除保护旧 refs 顺序或旧数量的测试断言。

完成标准：

- prompt 文案 agent-facing。
- 不重复长篇规则。
- 不引入开发说明式语言。

### Phase 5：旧测试清理与结构护栏补充

目标：删除保护旧结构的测试，用结构性护栏保护 prompt authority。

动作：

1. 删除保护旧 lifecycle 数量、旧消息位置、旧 prompt 顺序的测试。
2. 删除保护旧 selector 常驻挂载策略的测试。
3. 必要时用 title/source_ref/manifest 建立结构查找。
4. 增加 cache 稳定护栏。
5. 增加 selector 条件负例。
6. 增加 prompt hygiene 覆盖。

完成标准：

- 测试保护目标 prompt 架构，而不是保护旧实现。
- 不为过旧测试保留旧 prompt 链路。
- 不通过降低断言制造通过；旧测试若错，应删除并用结构护栏替代。

### Phase 6：验证与审查记录

目标：完成 focused verification。

建议命令：

```powershell
python -m pytest backend/tests/task_environment_registry_regression.py backend/tests/coding_environment_capability_isolation_regression.py -q
python -m pytest backend/tests/prompt_library_registry_regression.py backend/tests/prompt_accounting_ledger_test.py -q
python -m pytest backend/tests/dynamic_prompt_context_projection_test.py backend/tests/action_schema_manifest_regression.py -q
```

如果改动影响前后端运行链路、SSE、监控或 Electron，必须按项目固定端口真实启动：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/project_stack.ps1 -Action stop
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/project_stack.ps1 -Action start -FrontendMode dev
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/project_stack.ps1 -Action check
```

固定节点：

```text
前端：http://127.0.0.1:3000
后端：http://127.0.0.1:8003
前端 API Base：http://127.0.0.1:8003/api
```

### Phase 7：新增 Chat 环境设计与落地

目标：在 selector 收紧稳定后，新增纯聊天环境。

动作：

1. 新增 `environment_group.chat`。
2. 新增 `env.chat.role_conversation`。
3. 新增 chat environment prompt。
4. 新增或复用 personality / role prompt layer。
5. Chat 默认禁用 shell、browser、git、code execution、file write/edit、task_run handoff。
6. Selector 对 Chat 环境使用极小 conversation lifecycle 或 chat 专用 lifecycle。
7. 增加 Chat 环境结构性测试。

完成标准：

- Chat 环境不挂 Coding / Office 规则。
- Chat 环境不会默认发起 task run。
- Chat 环境角色 prompt 稳定，动态对话上下文不污染 stable role prompt。
- 用户转向真实执行任务时，模型说明当前 Chat 环境边界和可完成范围，不在 Chat 环境里伪装执行，也不主动发起环境切换。

## 十三、验收矩阵

| 验收项 | 通过标准 |
| --- | --- |
| Coding core loop | 有短核心协议，且不替代细分规则 |
| General selector | 作为通用工作环境保留混合任务能力，但普通 single turn 不挂无状态支撑的 active work / memory / compaction slot |
| Office selector | 不挂 coding 执行规则，不诱导 shell/git/code execution |
| Chat 环境 | 独立 chat kind，不挂任务执行/coding/office 规则，主打角色氛围和会话连续性 |
| Cache 稳定 | 同结构状态重复编译，refs 和顺序完全一致 |
| Dynamic 隔离 | 用户文本变化不改变 lifecycle refs |
| State 条件 | active work、memory、subagent、compaction 只有结构状态存在时触发 |
| Prompt hygiene | 所有模型可见 prompt 无开发说明式语言 |
| 结构护栏 | 验证 prompt authority、selector 条件、cache 稳定、环境隔离，不保护旧实现形态 |
| 旧测试清理 | 保护旧遗漏、旧 selector、旧消息位置的测试被删除或重写 |

## 十四、风险与控制

### 风险 1：收紧过度导致模型忘记关键纪律

控制：

- Coding 保留 core protocol。
- task_execution 常驻 tool recovery、verification、finalization。
- 高风险改动仍触发 plan gate。
- 验证测试覆盖 coding 必要 slot。

### 风险 2：cache 命中下降

控制：

- selector 不依赖用户文本。
- refs 顺序固定。
- dynamic facts 不进入 stable prompt。
- 增加 cache fingerprint 回归测试。

### 风险 3：条件判断来源分散

控制：

- 条件只来自 `allowed_actions`、`visible_tools`、`active_work_context`、`memory_context`、`observations`、`execution_state`、`session_context`。
- 每个触发原因写入 diagnostics。
- 不从历史摘要或自然语言中推断 selector 状态。

### 风险 4：旧测试反向绑架 prompt 架构

控制：

- 先确立目标 prompt 架构，再决定测试去留。
- 旧测试保护旧遗漏时直接删除，不做兼容。
- 需要保留验证时，重写为结构护栏。
- 禁止为了旧测试通过而保留旧 prompt 链路、旧 selector 或旧字段。

### 风险 5：Chat 环境被做成 General 的低配版

控制：

- Chat 使用独立 environment kind。
- Chat prompt 以角色氛围和会话连续性为核心。
- Chat 默认不挂 task handoff、tool dispatch、verification gate、coding/office rules。
- 真实执行任务是否进入 General / Office / Coding 由用户手动选择；模型只说明当前 Chat 环境边界，不主动切换。

## 十五、文件级清单

| 文件 | 动作 |
| --- | --- |
| `backend/harness/runtime/environment_prompt_controller.py` | 拆分 selector，稳定排序，条件化 lifecycle slots |
| `backend/task_system/environments/default_environments.py` | 如新增 `coding.rule.core_work_protocol`，加入 Coding environment refs；后续新增 `env.chat.role_conversation` |
| `backend/prompt_library/rules.py` | 新增或调整 coding core protocol；检查权限/状态语言 |
| `backend/prompt_library/environment_lifecycle_prompts.py` | 必要时压缩 lifecycle 文案，去掉过宽内部协议语言 |
| `backend/prompt_library/personality_prompts.py` | 后续为 Chat 环境承载角色/人格 prompt 选择与稳定层 |
| `backend/prompt_composition/section_renderer.py` | 保持环境/lifecycle 渲染结构稳定，避免动态内容混入 stable prompt |
| `backend/harness/runtime/compiler.py` | 保持 runtime boundary title/source_ref 稳定；不为旧位置测试保留消息顺序 |
| `backend/tests/task_environment_registry_regression.py` | 删除旧数量/旧位置断言，重写为 selector 结构护栏 |
| `backend/tests/coding_environment_capability_isolation_regression.py` | 增加环境隔离与 coding 必要规则保护 |
| `backend/tests/prompt_library_registry_regression.py` | 扩展 prompt hygiene 与 prompt authority 测试 |
| `backend/tests/prompt_accounting_ledger_test.py` | 增加 cache 稳定性断言 |

## 十六、实施前审阅点

实施前需要确认：

1. 是否确认 General 是通用工作环境，不是轻量环境；轻量环境只指 Office 文件检索。
2. 是否接受 Coding task_execution 的 `plan_gate` 从常驻改为 plan/high-risk 条件触发。
3. 是否新增 `coding.rule.core_work_protocol` 作为 Coding 主协议。
4. 是否接受删除保护旧遗漏、旧 selector、旧消息位置的测试，并用结构护栏替代。
5. 是否接受 selector 不读取用户文本关键词，以保护 prompt cache 稳定。
6. 是否新增 `env.chat.role_conversation` 作为独立纯聊天环境。
7. Chat 环境是否默认只启用基础系统 prompt、上下文拼接、角色/人格 prompt 和最小安全边界，不启用工具/任务执行心智。

## 十七、最终目标

完成后，本项目 prompt 体系应达到以下状态：

```text
环境 prompt 定义长期边界
General 保持通用工作环境定位
Office 保持轻量办公文件检索定位
Chat 独立承载角色氛围与纯聊天
lifecycle selector 只按稳定结构状态挂载必要规则
volatile runtime context 承载每轮动态事实
prompt authority 负责顺序和缓存边界
测试保护结构行为而不是脆弱字符串位置
```

这会让 Coding 环境更接近成熟 vibe coding agent：

- 会判断是否该改代码。
- 会先读代码事实。
- 会小步实现。
- 会真实验证。
- 会处理失败恢复。
- 会保护用户已有改动。
- 会在收口时只报告真实结果。

同时不会因为每轮动态选择过度聪明而损害 prompt cache。
