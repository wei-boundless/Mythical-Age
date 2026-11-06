# Turn 神经系统标准化重构设计书

## 0. 文档状态

状态：历史方案，已被 `turn_runtime_prompt_system_standardization_design_20260628.md` 取代。

说明：本文保留为早期审计记录，不再作为实施基准。正式代码和新设计不再使用 `neural`、`reflex` 等比喻命名；对应概念以 `turn_operating_contract`、`turn_state_attention`、`turn_attention_index` 和 `turn_state_guidance` 为准。

本文解决的问题不是“任务系统怎么写提示词”，而是先把 `turn` 原本的合同审查清楚，并把任务资源、工具动作、active work 控制、公开反馈、观察结果、状态写回和最终输出整合成一条标准化神经系统。

核心判断：

- `turn` 是唯一模型运行生命周期。
- `TaskRun` 是 agent 通过控制动作向系统申请的长任务运行资源。
- 工具、任务、恢复、暂停、输出都不是第二套生命周期；它们都是 turn 神经系统里的不同反射动作。
- 标准化目标不是新建“大脑”，而是把现有分散合同统一成一个 `TurnNeuralContract`。

## 1. 问题定义

当前系统已经有 turn 合同雏形，但它没有被统一命名和标准化。

结果是：

- compiler 在写一套 action prompt；
- provider strict tool/function calling 在写一套 control action schema；
- `model_action_protocol.py` 在写一套解析和旧任务合同归一化；
- `admission.py` 在写一套工具/任务/副作用权限判断；
- `single_agent_turn.py` 在写一套 repair、工具执行、最终提交；
- dynamic tail 在写一套 task/todo/plan 注意力索引；
- `task_executor` 仍保留第二套任务模型循环。

这些东西本来都应该是 turn 神经系统里的不同神经反射点，但现在像多个脑区各自写自己的合同。

正确终态：

```text
RequestFacts
-> TurnBoundaryReflex
-> ContextReflex
-> ActionSurfaceReflex
-> ModelDecisionReflex
-> ActionAdmissionReflex
-> ExecutionReflex
-> ObservationFeedbackReflex
-> StateCommitReflex
-> OutputCommitReflex
```

每个反射点只拥有自己的权威，不重猜上游语义，不替下游执行。

## 2. 源码审查：turn 原生合同在哪里

### 2.1 入口与边界合同

证据：

- `backend/harness/entrypoint/runtime_facade.py:688`：每轮先决定 current work boundary。
- `backend/harness/entrypoint/runtime_facade.py:743`：`single_agent_turn` 是普通 turn 分支。
- `backend/harness/entrypoint/runtime_facade.py:759`：仍存在 `explicit_contract_task` 分支。
- `backend/harness/entrypoint/runtime_facade.py:860`：普通 turn 内部定义 `start_task` 回调。
- `backend/harness/entrypoint/runtime_facade.py:890`：普通 turn 调用 `run_single_agent_turn(...)`。
- `backend/harness/entrypoint/runtime_facade.py:2407`：仍可直接执行 `execute_task_run`。

判断：

入口层已经具备 turn 中心结构，但还保留显式任务分支和 executor 分支。标准化后，普通 chat task 只能作为 turn 内资源申请和 overlay 投影，不再成为第二条模型执行路径。

### 2.2 RuntimePacketContext 是动作面雏形

证据：

- `backend/harness/runtime/packet_context.py:13`：`RuntimePacketModelActionSurface.allowed_action_types`。
- `backend/harness/runtime/packet_context.py:25`：`RuntimePacketContext`。
- `backend/harness/runtime/packet_context.py:43`：`operation_availability`。
- `backend/harness/runtime/packet_context.py:57`：默认动作面是 `respond / ask_user / block`。
- `backend/harness/runtime/packet_context.py:77`：`allowed_action_types` 从 `model_action_surface` 派生。
- `backend/harness/runtime/packet_assembler.py:20`：构建 `single_agent_turn` packet context。
- `backend/harness/runtime/packet_assembler.py:548`：单 turn 动作面根据控制能力加入 `request_task_run` 和 `active_work_control`。

判断：

这是标准神经系统的 `ActionSurfaceReflex` 原型。它应该成为本轮可行动作的唯一事实源，而不是让 compiler、tool contract、schema、admission 各自推断动作面。

### 2.3 compiler 已经在生成 turn 行动合同，但混入旧 task 语义

证据：

- `backend/harness/runtime/compiler.py:381`：`compile_single_agent_turn_packet` 是普通 turn prompt 编译入口。
- `backend/harness/runtime/compiler.py:1059`：仍存在 `compile_task_execution_packet`。
- `backend/harness/runtime/compiler.py:2897`：`model_action_request_schema` 定义 `respond / ask_user / tool_call / request_task_run / active_work_control / resume_task_recovery / block`。
- `backend/harness/runtime/compiler.py:2999`：`request_task_run_shape_rules` 仍使用旧任务生命周期表述。
- `backend/harness/runtime/compiler.py:3027`：`request_task_run_intent_contract` 仍要求旧 `entry_reason`。
- `backend/harness/runtime/compiler.py:3672`：`_single_agent_turn_output_contract`。
- `backend/harness/runtime/compiler.py:3690`：输出合同仍写“持续任务生命周期”。
- `backend/harness/runtime/compiler.py:6970`：`_current_task_attention_index_payload`。

判断：

compiler 是模型可见神经反射的主要出口，但当前把普通 turn 合同、任务启动说明、工具行动、公开反馈、输出合同混在一个大 schema 里。标准化后，compiler 只投影统一的 `TurnNeuralContract`，不再拥有独立 task 说明体系。

### 2.4 ModelActionRequest 是 turn 动作合同核心

证据：

- `backend/harness/loop/model_action_protocol.py:6`：`ModelActionType` 包含 `respond / ask_user / tool_call / request_task_run / active_work_control / resume_task_recovery / pause_for_user_steer / block`。
- `backend/harness/loop/model_action_protocol.py:26`：`ModelActionRequest`。
- `backend/harness/loop/model_action_protocol.py:71`：`TaskExecutionModelActionRequest` 形成第二套 action contract。
- `backend/harness/loop/model_action_protocol.py:109`：`model_action_request_from_payload` 解析和校验模型动作。
- `backend/harness/loop/model_action_protocol.py:162`：`request_task_run` 进入任务 seed 归一化。
- `backend/harness/loop/model_action_protocol.py:497`：仍通过 `work_modes` 找 primary mode。
- `backend/harness/loop/model_action_protocol.py:502`：仍要求 `container_contract.entry_reason`。
- `backend/harness/loop/model_action_protocol.py:569`：compact intent 仍读取 `primary_mode`。
- `backend/harness/loop/model_action_protocol.py:570`：旧七类 mode 仍在枚举内。
- `backend/harness/loop/model_action_protocol.py:572`：unsupported mode fallback 到 `open_work`。

判断：

`ModelActionRequest` 应升级为 canonical turn action contract。`TaskExecutionModelActionRequest` 和旧 task seed 归一化应退出普通 task 路径。动作解析层只能 normalize/validate，不再补猜任务模式。

### 2.5 Provider strict control action schema 是动作通道，不是第二个合同源

证据：

- `backend/harness/runtime/tool_call_contract.py:24`：`ToolCallContract` 同时描述普通工具和控制动作提交方式。
- `backend/harness/runtime/tool_call_contract.py:82`：`build_tool_call_contract(...)` 按 allowed actions 构造本轮工具/控制动作通道。
- `backend/harness/runtime/tool_call_contract.py:180`：agent-visible instruction 仍描述 control action。
- `backend/harness/runtime/control_action_schema.py:34`：`provider_control_action_bindings(...)` 生成 provider strict control tool。
- `backend/harness/runtime/control_action_schema.py:46`：provider control action 使用 `strict: True`。
- `backend/harness/runtime/control_action_schema.py:162`：`request_task_run` 描述为 durable task lifecycle。
- `backend/harness/runtime/control_action_schema.py:197`：`request_task_run` schema。
- `backend/harness/runtime/control_action_schema.py:198`：仍要求 `entry_reason` 和旧 `primary_mode` 枚举。

判断：

provider strict tool/function calling 只能承载 `TurnActionRequest` 的传输 schema。字段语义必须来自统一 `TurnNeuralContract`，不能自己再定义一套任务生命周期。

### 2.6 Admission / Permit 是授权反射，但仍带旧 task 价值判断

证据：

- `backend/harness/loop/admission.py:18`：`AdmissionDecision`。
- `backend/harness/loop/admission.py:57`：`admit_model_action(...)`。
- `backend/harness/loop/admission.py:58`：先检查动作是否在 `packet_allowed_action_types`。
- `backend/harness/loop/admission.py:87`：工具调用进入工具授权分支。
- `backend/harness/loop/admission.py:142`：task-scoped tool 会要求 `request_task_run`。
- `backend/harness/loop/admission.py:200`：副作用工具会要求先提交 `request_task_run`。
- `backend/harness/loop/admission.py:231`：`request_task_run` admission。
- `backend/harness/loop/admission.py:271`：`active_work_control` admission。
- `backend/harness/loop/action_permit.py:12`：`ActionPermit`。
- `backend/harness/loop/execution_kernel.py:214`：`decide_model_action_lifecycle(...)` 调用 admission 并生成 `ActionLifecycleDecision`。

判断：

Admission/Permit 应只做动作合法性、权限、工具可用性、运行边界和副作用许可，不应把“需要 task”写成旧语义判断。正确表述是“需要系统资源/边界/许可”。如果某工具要求 task resource，应返回 resource requirement，而不是教 agent 进入任务模式。

### 2.7 single_agent_turn 是唯一应保留的模型执行循环

证据：

- `backend/harness/loop/single_agent_turn.py:1783`：`run_single_agent_turn(...)`。
- `backend/harness/loop/single_agent_turn.py:2603`：工具行动进入 `decide_model_action_lifecycle(...)`。
- `backend/harness/loop/single_agent_turn.py:3316`：模型动作进入生命周期判断。
- `backend/harness/loop/single_agent_turn.py:3444`：`respond` 分支。
- `backend/harness/loop/single_agent_turn.py:3498`：`request_task_run` 分支。
- `backend/harness/loop/single_agent_turn.py:3499`：当前 terminal reason 仍是 `task_executor_scheduled`。
- `backend/harness/loop/single_agent_turn.py:3683`：`active_work_control` 分支。
- `backend/harness/loop/single_agent_turn.py:5546`：`request_task_run` repair 示例。
- `backend/harness/loop/single_agent_turn.py:5693`：repair 仍要求 `entry_reason`。
- `backend/harness/loop/single_agent_turn.py:9257`：最终消息提交函数。

判断：

`single_agent_turn` 是标准神经系统的 `ExecutionReflex` 主体。它必须继续作为唯一模型循环；`request_task_run` 后应返回“资源已创建/已绑定/下一 turn overlay”，不能把 terminal reason 写成 `task_executor_scheduled`。

### 2.8 动态 tail 已有缓存正确方向，但命名还在 task mode

证据：

- `backend/harness/runtime/dynamic_context/manager.py:84`：生成 volatile request projection。
- `backend/harness/runtime/dynamic_context/manager.py:233`：生成 volatile state projection。
- `backend/harness/runtime/dynamic_context/manager.py:252`：调用 `build_task_mode_tail_contexts(...)`。
- `backend/harness/runtime/dynamic_context/manager.py:491`：挂载 `task_todo_context`。
- `backend/harness/runtime/dynamic_context/task_mode_tail_context.py:9`：`build_task_mode_tail_contexts(...)`。
- `backend/harness/runtime/compiler.py:1869`：`Current Task Attention Index` 以 volatile segment 注入。

判断：

这是 `OrientReflex / StateReflex` 的现有资产。需要重命名和重构为 `Turn Reflex Index`，把 task/todo/plan 作为当前 turn 状态投影，而不是 task mode tail。

## 3. 当前权威冲突表

| 层 | 当前文件 | 当前职责 | 冲突 | 目标动作 |
|---|---|---|---|---|
| 动作面 | `packet_assembler.py` / `packet_context.py` | allowed action types、operation availability | compiler/tool schema/admission 也在解释动作面 | 升级为唯一 `TurnActionSurface` |
| 模型可见合同 | `compiler.py` | action schema、output contract、task guidance | 混入旧 task lifecycle、entry_reason、七类 mode | 改为投影 `TurnNeuralContract` 的 agent reflex 文案 |
| provider strict schema | `control_action_schema.py` | provider-native control action schema | 自己定义旧 TaskStartIntent | 只承载 canonical `TurnActionRequest` schema |
| action parser | `model_action_protocol.py` | 解析模型动作 | 旧 compact intent fallback 到 open_work；`TaskExecutionModelActionRequest` 并存 | 只 normalize/validate；无 silent fallback |
| admission | `admission.py` | 授权动作和工具 | 用旧“进入持续任务”表达 resource/permission requirement | 改成 resource requirement / action feedback |
| execution loop | `single_agent_turn.py` | 模型循环、工具执行、回复提交 | `request_task_run` 终止到 executor；repair 仍旧 | 保留唯一模型循环；task start 是资源申请 |
| dynamic tail | `task_mode_tail_context.py` | 任务目标/计划/todo 动态投影 | 命名是 task mode；todo 容易被看成 mode | 改为 `turn_reflex_tail` / `todo_cursor` |
| task execution | `compile_task_execution_packet` / `task_executor.py` | 第二套任务模型循环 | 与 single turn 抢执行权 | 普通 task 路径移除默认模型执行权 |

## 4. 推荐设计：TurnNeuralContract

### 4.1 总体定义

`TurnNeuralContract` 是每个 turn 的唯一运行合同。

它不是一段大 prompt，而是一组系统和 agent 都能对齐的结构化合同：

```text
TurnNeuralContract
├─ turn_identity
├─ request_facts
├─ boundary_receipt
├─ resource_projection
├─ context_reflex
├─ action_surface
├─ action_transport
├─ prompt_reflex
├─ action_request_schema
├─ action_admission_policy
├─ execution_observation_policy
├─ state_commit_policy
├─ output_commit_policy
└─ trace_contract
```

### 4.2 核心原则

- agent 只在 turn 中行动。
- agent 拥有语义下一步选择权。
- 系统拥有资源分配、权限、状态持久化、输出提交和恢复边界。
- provider strict tool/function calling 是动作传输通道，不是第二份语义合同。
- task resource、tool call、active work control、respond、ask_user、block 都是同一 `ModelActionRequest` 的不同动作。
- 所有 repair feedback 都必须回到同一 ActionFeedback 通道。

## 5. 标准神经反射链

### N0 RequestFacts Reflex

输入：

- 用户当前消息；
- session；
- attachments；
- workspace refs；
- 当前 runtime profile；
- 已绑定 active task resource；
- explicit user steer。

输出：

- `TurnRequestFacts`。

权威：

- 只观察，不决定。

禁止：

- 猜用户意图；
- 选择 task；
- 选择工具；
- 改写用户目标。

### N1 Boundary Reflex

输入：

- `TurnRequestFacts`；
- active turn / active task resource；
- current work facts。

输出：

- `TurnBoundaryReceipt`。

职责：

- 判断当前 turn 是否有 active resource；
- 判断 `active_work_control` 是否可用；
- 判断当前 active work 是可控、只读、terminal 还是无关。

禁止：

- 生成 prompt；
- 选择模型动作；
- 调工具。

### N2 Context Reflex

输入：

- boundary receipt；
- tool/capability facts；
- memory hints；
- evidence ledger；
- task resource projection。

输出：

- `TurnContextPacket`；
- stable prefix candidates；
- append context；
- volatile tail。

职责：

- 收集和排序上下文；
- 标注 cache tier；
- 将当前动态状态放入 volatile tail。

禁止：

- 决定最终动作；
- 把 provider transport sidecar 写进 agent memory；
- 把 task resource 说明写成 agent 模式说明。

### N3 Action Surface Reflex

输入：

- runtime profile；
- boundary receipt；
- operation availability；
- tool plan；
- resource policy。

输出：

- `TurnActionSurface`。

标准字段：

```text
allowed_action_types
allowed_tool_names
control_action_names
ordinary_tool_submission
control_action_submission
operation_availability
resource_requirements
```

职责：

- 定义本 turn 可选动作；
- 定义 provider strict schema 是否绑定；
- 定义工具是否可见/可执行。

禁止：

- 教 agent 为什么要选某动作；
- 偷偷加入未授权动作。

### N4 Prompt Reflex

输入：

- `TurnNeuralContract` 的稳定部分；
- `TurnActionSurface`；
- `Turn Reflex Index`。

输出：

- agent-facing prompt。

prompt 标准：

- 短促；
- 可执行；
- 按 turn 反射点写；
- 不写开发说明；
- 不写“这是 runtime 节点”；
- 不把 TaskRun 写成 agent 模式。

示例核心文案：

```text
你正在执行当前 turn。
先回应用户当前输入，再选择一个本轮动作。

如果本轮能完成，使用 respond。
如果缺少用户信息，使用 ask_user。
如果需要工具观察，使用 tool_call 或 tool_calls。
如果需要系统分配长任务资源保存目标、游标、恢复点或验收边界，使用 request_task_run。
如果当前 turn 已绑定可控工作，并且用户是在控制这项工作，使用 active_work_control。
如果不能继续，使用 block。
```

### N5 Model Decision Reflex

输入：

- prompt；
- action surface；
- current context；
- tool observations。

输出：

- `ModelActionRequest`。

职责：

- agent 选择唯一语义动作；
- 填写动作字段；
- 提供必要公开反馈。

禁止：

- 自授权限；
- 写系统字段；
- 把动作合同写进普通自然语言；
- 同时发普通工具和控制动作。

### N6 Action Parse / Normalize Reflex

输入：

- provider-native control tool call；
- JSON action；
- assistant final text。

输出：

- canonical `ModelActionRequest`。

职责：

- 解析；
- 归一化；
- 校验字段形状；
- 报告字段错误。

禁止：

- silent fallback；
- unsupported mode 自动改 `open_work`；
- 补猜 task mode；
- 把旧 seed 转成新合同后继续当新动作执行。

### N7 Admission / Permit Reflex

输入：

- `ModelActionRequest`；
- action surface；
- tool plan；
- permission mode；
- boundary receipt。

输出：

- `ActionLifecycleDecision`；
- `ActionPermit`；
- `ActionFeedback`。

职责：

- 校验动作是否在本轮动作面；
- 校验工具是否可用；
- 校验副作用许可；
- 校验 active work 控制是否可用；
- 将拒绝转成可恢复反馈。

禁止：

- 替 agent 换动作；
- 把权限缺口表达成旧 task 模式；
- 静默降级为 respond/tool_call。

### N8 Execution Reflex

输入：

- allowed `ModelActionRequest`；
- action permit；
- runtime tool control plane；
- task resource allocator。

输出：

- tool observation；
- task resource allocation receipt；
- active work control observation；
- final response candidate。

职责：

- 执行已允许动作；
- 产生观察；
- 保留 refs；
- 不重猜用户意图。

### N9 Observation Feedback Reflex

输入：

- tool observation；
- admission denial；
- protocol repair；
- resource allocation result。

输出：

- agent-visible `ActionFeedback`；
- public progress projection；
- dynamic tail update candidate。

职责：

- 把系统观察转成 agent 下一步可执行反馈；
- 说明字段错误、权限拒绝、工具失败、资源缺口。

禁止：

- 给开发式分类说明；
- 伪造成功；
- 用自然语言绕过结构化动作。

### N10 State Commit Reflex

输入：

- tool observation；
- task resource allocation receipt；
- final answer；
- todo cursor changes；
- active plan step；
- acceptance progress。

输出：

- `TurnStatePatch`；
- `TaskResourcePatch`；
- evidence commit candidate；
- run monitor event。

职责：

- 写回 task resource 状态；
- 写回 todo cursor；
- 写回 evidence refs；
- 写回 terminal reason。

禁止：

- 仅靠 final answer 自动完成 task；
- 把旧历史状态覆盖当前 turn truth；
- 在 output 层再决定任务状态。

### N11 Output Commit Reflex

输入：

- final answer candidate；
- output boundary；
- public stream contract；
- state commit result。

输出：

- committed assistant message；
- public stream event；
- blocked/repair feedback。

职责：

- 防止协议泄漏；
- 提交用户可见回复；
- 保证 final answer 是 agent 自己写给用户的自然语言。

禁止：

- 改写底层决策；
- 把工具事件当用户回复；
- 把内部 action payload 泄漏给用户。

## 6. 数据合同变更

### 6.1 新增 canonical 合同

建议新增：

```text
backend/harness/runtime/turn_neural_contract.py
```

包含：

```text
TurnNeuralContract
TurnRequestFacts
TurnBoundaryReceiptRef
TurnActionSurface
TurnActionTransport
TurnReflexIndex
TurnActionRequestContract
TurnFeedbackContract
TurnStatePatchContract
TurnOutputCommitContract
```

这些对象先作为统一语义合同和诊断 payload，不急着拆大文件。

### 6.2 需要降级的旧对象

- `TaskExecutionModelActionRequest`：普通 task 路径不再使用；保留仅作为迁移审查对象。
- `task_mode_tail_context`：改为 turn reflex tail。
- `entry_reason`：退出 agent-facing 启动合同。
- 七类 `primary_mode`：退出 turn action schema。
- `task_executor_scheduled`：退出普通 `request_task_run` terminal reason。

## 7. 文件级计划

### 7.1 `backend/harness/runtime/packet_context.py`

当前角色：

- 持有 `RuntimePacketContext` 和 `RuntimePacketModelActionSurface`。

目标动作：

- 让 `RuntimePacketModelActionSurface` 成为 `TurnActionSurface` 的数据源；
- 明确它只表达动作面，不表达 prompt 文案；
- 增加 trace id 或 authority 字段供 `TurnNeuralContract` 引用。

完成条件：

- 后续 compiler/schema/admission 都消费同一 action surface。

### 7.2 `backend/harness/runtime/packet_assembler.py`

当前角色：

- 生成 single turn 和 task execution 的 packet context；
- 根据 control capabilities 添加 `request_task_run / active_work_control`。

目标动作：

- 统一 single turn action surface；
- 普通 task-bound turn 使用 single turn surface；
- task execution surface 从普通 chat task 路径移除。

完成条件：

- 普通 task path 不再需要 `build_task_execution_packet_context`。

### 7.3 `backend/harness/runtime/compiler.py`

当前角色：

- 生成模型可见动作合同、输出合同、task attention index。

目标动作：

- 删除旧 task lifecycle prompt；
- 投影 `TurnNeuralContract`；
- 将 `model_action_request_schema` 改成 turn reflex prompt；
- 将 `_single_agent_turn_output_contract` 改成统一 `TurnOutputContract`；
- 将 `Current Task Attention Index` 改成 `Turn Reflex Index`；
- 不再在 prompt 中出现 `entry_reason`、七类 `primary_mode`、task mode 说明。

完成条件：

- prompt 只描述当前 turn 如何行动。

### 7.4 `backend/harness/runtime/control_action_schema.py`

当前角色：

- provider strict control action schema。

目标动作：

- 从独立 task schema 改为 `TurnActionRequest` transport schema；
- `request_task_run` schema 对齐 TaskStartIntent；
- 移除 `entry_reason`；
- `primary_mode` 只保留 `goal | plan`；
- 新增 `task_shape` 和可选 `todo_tool_contract`。

完成条件：

- provider-native control action 与 JSON action 得到同一 canonical `ModelActionRequest`。

### 7.5 `backend/harness/runtime/tool_call_contract.py`

当前角色：

- 描述普通工具和控制动作提交方式。

目标动作：

- 改为 `TurnActionTransportContract`；
- 只说明本 turn 走 provider-native 还是 action object；
- agent-facing 文案不再独立定义 task。

完成条件：

- strict tool/function calling 是通道，不是语义源。

### 7.6 `backend/harness/loop/model_action_protocol.py`

当前角色：

- 解析、归一化、校验模型动作。

目标动作：

- 保留 canonical `ModelActionRequest`；
- 删除普通路径的 `TaskExecutionModelActionRequest` 依赖；
- 删除旧 compact intent fallback；
- 字段错误输出统一 `ActionFeedback`；
- 不再把旧 seed 自动转成新合同继续执行。

完成条件：

- 解析层只 normalize/validate，不决定任务语义。

### 7.7 `backend/harness/loop/admission.py`

当前角色：

- 动作 admission、工具可用性、权限和资源缺口判断。

目标动作：

- 把“需要持续任务”文案改成“需要长任务资源/执行边界/许可”；
- 不再把 side-effect tool 直接等同于 request_task_run；
- 返回 resource requirement feedback；
- active work control 只检查 boundary receipt。

完成条件：

- admission 是授权反射，不是任务语义裁判。

### 7.8 `backend/harness/loop/execution_kernel.py`

当前角色：

- 将 action request + admission 组合成 `ActionLifecycleDecision`。

目标动作：

- 对齐 `TurnActionLifecycle`；
- lifecycle id 绑定 turn/action/permit；
- 不携带 executor 旧状态；
- admission denial 统一转 ActionFeedback。

完成条件：

- action lifecycle 是执行观测链，不是任务状态机。

### 7.9 `backend/harness/loop/single_agent_turn.py`

当前角色：

- 唯一普通模型执行循环；
- 工具执行、request_task_run、active_work_control、respond、repair、final commit 都在这里。

目标动作：

- 保留为唯一模型循环；
- `request_task_run` 变成 resource allocation action；
- 删除 `task_executor_scheduled` 作为普通 task start terminal；
- repair prompt 改成 ActionFeedback；
- turn 结束前输出 `TurnStatePatch`；
- final answer 只由 output commit 提交。

完成条件：

- 普通 task-bound 工作不再跳出 single turn 心智模型。

### 7.10 `backend/harness/runtime/dynamic_context/task_mode_tail_context.py`

当前角色：

- goal/plan/todo tail context。

目标动作：

- 改为 `turn_reflex_tail_context.py`；
- todo 是 cursor；
- active plan step 是 current step；
- task resource projection 是 turn state；
- 输出 `Turn Reflex Index`。

完成条件：

- tail 是当前 turn 注意力锚点，不是 task mode 说明。

### 7.11 `backend/harness/loop/task_lifecycle.py`

当前角色：

- 创建 TaskRun；
- 绑定 active turn；
- 当前仍调度 executor。

目标动作：

- 改为 `TaskRunResourceAllocator`；
- 只分配资源、保存合同、绑定 turn；
- 不默认调度模型 executor；
- 输出 resource allocation receipt。

完成条件：

- TaskRun 是系统资源，不是模型循环入口。

### 7.12 `backend/harness/runtime/active_turn.py`

当前角色：

- Active turn 与 task run 绑定；
- 状态包含 `waiting_executor`。

目标动作：

- 状态改成 turn/resource 绑定语义；
- 移除 executor 等待态对普通 task 的影响；
- active work control 通过 boundary receipt 控制。

完成条件：

- active turn 不再暗示 task executor handoff。

## 8. 固定执行流

### 8.1 普通 turn 直接回答

```text
RequestFacts
-> BoundaryReceipt(no_active_resource)
-> ActionSurface(respond/tool_call/ask_user/block/request_task_run)
-> PromptReflex
-> ModelActionRequest(respond)
-> Admission(allow)
-> OutputCommit
-> TurnTrace
```

### 8.2 普通 turn 使用工具

```text
ModelActionRequest(tool_call/tool_calls)
-> Admission/Permit
-> ToolExecution
-> ToolObservation
-> ObservationFeedback
-> next ModelActionRequest 或 respond
-> StateCommit
-> OutputCommit
```

### 8.3 申请长任务资源

```text
ModelActionRequest(request_task_run)
-> ActionParse(TaskStartIntent)
-> Admission(resource allocation allowed)
-> TaskRunResourceAllocator
-> ResourceAllocationReceipt(task_run_id)
-> TurnStatePatch(bind resource)
-> OutputCommit(public receipt or next-step note)
-> next turn receives Turn Reflex Index
```

### 8.4 已绑定长任务资源的 turn

```text
RequestFacts
-> BoundaryReceipt(active_resource)
-> ContextReflex(resource projection + todo cursor + active step)
-> Turn Reflex Index
-> ModelActionRequest(tool_call/respond/active_work_control/block/ask_user)
-> Execution
-> StatePatch(resource progress/todo/acceptance)
-> OutputCommit
```

### 8.5 控制 active work

```text
BoundaryReceipt(active_work_control=true)
-> ModelActionRequest(active_work_control)
-> Admission(check receipt)
-> ActiveWorkControl
-> ControlObservation
-> StatePatch
-> OutputCommit
```

## 9. 分阶段实施计划

### Phase 1：定义 TurnNeuralContract

目标：

- 新增 canonical 合同文件；
- 不改行为；
- 让 compiler、packet、single turn 可输出 shadow diagnostics。

文件：

- `backend/harness/runtime/turn_neural_contract.py`
- `backend/harness/runtime/packet_context.py`
- `backend/harness/runtime/packet_assembler.py`

完成条件：

- 每个 single turn 能产生 `turn_neural_contract_ref`。

### Phase 2：统一 agent-facing prompt

目标：

- compiler 只投影 turn reflex prompt；
- 删除旧 task lifecycle 文案；
- request_task_run 改成资源申请反射；
- tail 改为 Turn Reflex Index。

文件：

- `backend/harness/runtime/compiler.py`
- `backend/harness/runtime/dynamic_context/task_mode_tail_context.py`
- `backend/harness/runtime/dynamic_context/manager.py`

完成条件：

- agent-facing prompt 不再出现 `entry_reason` 和七类 `primary_mode`。

### Phase 3：统一 control action schema 和 parser

目标：

- provider strict schema 与 JSON action 同源；
- `ModelActionRequest` 成为唯一普通 turn action contract；
- 无效动作进入 ActionFeedback。

文件：

- `backend/harness/runtime/control_action_schema.py`
- `backend/harness/runtime/tool_call_contract.py`
- `backend/harness/loop/model_action_protocol.py`
- `backend/harness/loop/single_agent_turn.py`

完成条件：

- 旧 task start schema 被拒绝；
- repair 只反馈字段错误和下一动作。

### Phase 4：统一 admission / permit / feedback

目标：

- Admission 只做授权与资源要求；
- 统一 ActionFeedback；
- 删除旧“进入任务模式”权限文案。

文件：

- `backend/harness/loop/admission.py`
- `backend/harness/loop/action_permit.py`
- `backend/harness/loop/execution_kernel.py`
- `backend/harness/loop/single_agent_turn.py`

完成条件：

- 权限拒绝、工具缺口、资源缺口、协议错误都走同一 feedback。

### Phase 5：TaskRun 资源化

目标：

- `request_task_run` 创建资源，不调度普通 task executor；
- task overlay 由后续 turn 消费；
- active turn 状态不再等待 executor。

文件：

- `backend/harness/loop/task_lifecycle.py`
- `backend/harness/runtime/active_turn.py`
- `backend/harness/entrypoint/runtime_facade.py`
- `backend/harness/loop/single_agent_turn.py`

完成条件：

- `request_task_run` 后不出现 `task_executor_scheduled`。

### Phase 6：移除普通 task_execution 模型路径

目标：

- 普通 chat task 不再进入 `compile_task_execution_packet` / `task_executor` 模型循环；
- graph/worker 特殊迁移另案处理；
- 删除或降级普通路径旧 executor prompt。

文件：

- `backend/harness/runtime/compiler.py`
- `backend/harness/loop/task_executor.py`
- `backend/harness/entrypoint/runtime_facade.py`

完成条件：

- 普通 task-bound 工作只走 `single_agent_turn`。

## 10. 验证方式

不新增回归测试文件。

静态检查：

```powershell
rg -n "entry_reason|primary_mode.*todo|primary_mode.*investigation|持续任务生命周期|任务模式|task_executor_scheduled" backend/harness
rg -n "compile_task_execution_packet|TaskExecutionModelActionRequest|execute_task_run" backend/harness
```

CLI 真实验证：

```text
1. 普通 turn respond。
2. 普通 turn tool_call。
3. provider strict request_task_run 创建 TaskRun resource。
4. 下一 turn 看到 Turn Reflex Index。
5. task-bound turn 更新 todo cursor / active step。
6. active_work_control 只在 boundary receipt 允许时可用。
7. final answer 由 single_agent_turn 提交。
8. request_task_run 不调度 task_executor。
```

运行链路验证必须使用固定端口：

- 前端：`http://127.0.0.1:3000`
- 后端：`http://127.0.0.1:8003`

## 11. 禁止事项

- 不新建第二套 agent runtime。
- 不在旧 task prompt 外包新 prompt。
- 不让 parser/admission/executor 替 agent 猜语义。
- 不保留 silent fallback 到 `open_work`。
- 不把 todo 当 primary mode。
- 不把 provider strict schema 当第二套语义合同。
- 不让 task resource 分配自动调度普通 task executor。
- 不把动态状态塞进 stable prefix。
- 不用开发说明冒充 agent prompt。

## 12. 预期结果

完成后，项目会有一套真正标准化的 turn 神经系统：

- `RuntimePacketContext` 给出本轮动作面；
- `TurnNeuralContract` 统一神经合同；
- compiler 只投影反射式 prompt；
- provider strict schema 只承载动作传输；
- `ModelActionRequest` 是唯一普通 turn 动作合同；
- admission/permit 是授权反射；
- single_agent_turn 是唯一普通模型执行循环；
- TaskRun 是系统资源；
- Turn Reflex Index 是尾部状态反射；
- OutputCommit 是唯一最终输出门。

这样 task、tool、memory、context、permission、feedback、output 都会挂回同一条 turn 神经弧，而不是继续分裂成多个“模式”和多套合同。
