# Agent 工具调用体系标准化重构计划书

日期：2026-06-27

状态：已审查修正，核心工具调用合同链路已实施。本文取代旧版“工具调用语义契约”计划中的 `tool_transport_adapter.py` 路线。

执行记录：

- 2026-06-27：新增 `backend/harness/runtime/tool_call_contract.py`，并接入 `compiler.py`、`single_agent_turn.py`、`runtime_delta_projector.py` 和 provider payload 缓存诊断。
- 2026-06-27：普通工具调用默认走 provider 工具选择；控制动作继续走结构化动作对象；二者都归一到同一 admission / execution / observation 链。
- 2026-06-27：工具 sidecar 保持当前请求传输结构，`cache_scope=none`、`cache_role=never_cache`、`provider_payload_prefix_component=false`，不进入 stable message prefix。

## 1. 审查结论

现有项目里确实有工具调用相关计划，但它不是一份完整、可执行、可验收的“工具调用体系标准化重构计划”。

已有文档的真实状态：

- `capability_system_standardization_plan_20260627.md` 是能力系统总规划，覆盖 `Tools / MCP / Skills`，但工具调用 transport 只在 7.3 节短暂提到，没有锁定完整执行链。
- 旧版 `agent_tool_call_semantic_contract_refactor_plan_20260627.md` 主要处理 agent 可见语义污染，方向有价值，但后半段提出过 `backend/harness/runtime/tool_transport_adapter.py`，这条路线已经被否定，当前文件也不存在。
- 当前代码里 provider-native tool call、JSON action、工具目录、权限准入、工具观察 follow-up 和缓存 sidecar 仍分散在多个模块里，没有一个明确的工具调用合同作为单一事实源。

因此，正确修正不是继续给旧链路打补丁，而是把工具调用体系拆成六个独立但串联的权威层：

```text
Capability Resolver
-> Runtime Tool Plan
-> Tool Call Contract
-> Provider Payload / Action Object Transport
-> Admission + Batch Execution
-> Observation + Agent Feedback
```

## 2. 当前问题源报告

### 2.1 工具能力选择已有基础，但不是最终权威

`backend/harness/runtime/tool_plan.py` 已经能根据 `runtime_assembly.available_tools` 和 `operation_authorization` 生成 `RuntimeToolPlan`：

- `model_visible_tools`
- `dispatchable_tool_names`
- `capability_table`
- `operation_authorization`

这条链路应该保留，未来接入 `CapabilityResolver` 后，`RuntimeToolPlan` 不再自己承担能力来源判断，只负责把 resolver 产出的 mounted tools 变成当前回合工具执行面。

### 2.2 工具目录与 provider schema 已经分离，但合同没有统一命名

`backend/harness/runtime/tool_catalog_manifest.py` 负责稳定工具目录和 agent 可见工具摘要。

`backend/harness/runtime/provider_tool_schema.py` 负责 provider-native tools payload。

`backend/runtime/model_gateway/provider_payload.py` 把 provider tools sidecar 标为：

```text
cache_scope=none
cache_role=never_cache
provider_payload_transport_location=tools
provider_payload_prefix_component=false
```

这个方向是对的：provider tools sidecar 是当前请求传输结构，不是 message prefix，不应该进入 stable prompt。

当前缺口是：工具目录、provider sidecar、JSON action fallback 之间没有一个统一的 `ToolCallContract` 来声明本轮到底允许哪种提交方式。

### 2.3 agent 可见运行契约仍泄漏工程 transport

`backend/harness/runtime/compiler.py` 当前仍在多个 agent-visible payload 里写入类似：

```text
provider_native_tool_call
json_action
provider_direct_tool_selection
assistant_or_json_control_action
```

这些词对工程诊断有意义，但不应该成为 agent 的工作语言。agent 需要看到的是：

```text
你可以选择当前可用工具，并填写参数。
控制动作需要按动作对象提交。
如果工具不可用或被拒绝，系统会返回观察，你据此继续判断。
```

agent 不应该被要求理解 provider-native、sidecar、transport、JSON action 这些工程概念。

### 2.4 parser 已经能归一工具请求，但缺少明确 transport 边界

`backend/harness/loop/single_agent_turn.py` 目前支持：

- provider-native tool calls 解析为 `ModelActionRequest(action_type="tool_call")`
- JSON action 里的 `tool_call/tool_calls` 解析为同一类 `ModelActionRequest`
- native tool call 和 JSON action 同时出现时拒绝

这个归一方向是正确的。

缺口是 parser 现在承担了太多 transport 判断。是否启用 provider tools、是否要求 action object、是否允许自然回答，不应散落在 parser 和 prompt 文案里，应由本轮隐藏 `ToolCallContract` 决定。

### 2.5 权限反馈方向基本正确，但还需要纳入工具调用合同

当前 single turn 已经有这些正向机制：

- 工具次数耗尽时生成 `tool_budget_exhausted` control signal，让 agent 基于已观察事实收口。
- 连续工具失败时生成 `consecutive_tool_failures`，不是静默关闭。
- 模型动作未执行时生成 `model_protocol_violation`，把未执行事实反馈给 agent。
- final answer 未提交时生成 `final_output_not_committable`，允许 agent 继续判断。

这符合用户要求：越界不要执行，但要反馈给 agent，不要直接停下。

还需要修正的是：这些反馈必须统一挂到工具调用合同上，agent 看到的不是“系统格式错了”，而是“上一轮行动没有执行、原因是什么、现在还能做什么”。

## 3. 标准化目标

### 3.1 工具调用体系的单一主链

目标链路：

```text
CapabilityResolver
  -> mounted_tools
RuntimeToolPlan
  -> visible_tools + dispatchable_tools + permission projection
ToolCallContract
  -> agent_visible_tool_instruction + hidden_transport_policy
ProviderPayload / ActionObject
  -> provider tools sidecar or structured action object
SingleAgentActionParser
  -> ModelActionRequest(action_type="tool_call")
Admission
  -> allow / ask_approval / deny / feedback
ToolBatchPlan
  -> concurrency + resource locks
ToolExecutor
  -> ToolObservation
RuntimeDeltaProjector
  -> agent follow-up context
```

所有工具请求最终都必须进入同一个 `ModelActionRequest(action_type="tool_call")`，再进入同一个 admission/execution 链。禁止保留并行旧执行链。

### 3.2 provider-native 是普通工具调用主路径

普通工具调用默认优先 provider-native，因为成熟 coding agent 的工具选择应该走 provider 工具选择，而不是让 agent 手写 JSON。

目标：

- provider 支持 tools 且本轮允许工具时，普通工具调用走 provider-native。
- provider tools sidecar 只进入 provider payload 的 `tools` 字段，不进入稳定 message prefix。
- agent 可见 prompt 只描述“选择当前可用工具并填写参数”，不说 provider-native。
- provider-native 工具调用返回后，由系统构造成标准 assistant tool-call message + tool observation，保持后续协议完整。

### 3.3 JSON/action-object 作为后备与控制动作通道

JSON 体系保留，但必须分离：

- 控制动作：`respond / ask_user / block / request_task_run / active_work_control / resume_recoverable_work` 使用 action object。
- 工具后备：仅当 provider tools 不可用、运行模式显式要求、或调试策略切换时，工具请求才走 action object。
- JSON/action-object 不得和 provider-native 工具提交同时提示给 agent。
- JSON/action-object 的 agent 可见说明要写成“提交本次行动对象”，不要写成“满足 JSON 协议”。

### 3.4 MCP 工具进入同一个工具执行面

MCP 不应该是另一个工具调用体系。

标准规则：

- MCP server install / inspect / enable 属于 capability 系统。
- MCP tool 被 resolver 选中后，映射为 mounted tool。
- mounted MCP tool 与 builtin tool 一样进入 `RuntimeToolPlan`。
- agent 只看到当前可用工具名和用途，不看到 MCP server command/env/token。
- MCP tool 执行也必须通过 permission admission。

### 3.5 权限和边界反馈必须回到 agent

系统边界负责“不执行越界动作”，不是“关闭 agent”。

标准行为：

- 工具名不存在：不执行，返回可理解反馈和当前可用工具范围。
- 参数不合法：不执行，返回缺失或错误字段，让 agent 重新判断。
- 权限拒绝：不执行，返回拒绝原因、可选替代动作、是否可请求用户授权。
- 需要审批：暂停执行该工具，返回审批状态，不伪造观察。
- 工具预算耗尽：不再执行工具，要求 agent 基于已观察事实 `respond / ask_user / block`。
- 连续失败：不继续循环工具，要求 agent 反馈失败原因和下一步。

## 4. Target ToolCallContract

新增或改造目标不是恢复 `tool_transport_adapter.py`。建议使用更明确的合同模块名：

```text
backend/harness/runtime/tool_call_contract.py
```

合同结构：

```python
ToolCallContract(
    contract_id: str,
    invocation_kind: str,
    mounted_tool_names: tuple[str, ...],
    ordinary_tool_submission: Literal["provider_tool_selection", "action_object", "none"],
    control_action_submission: Literal["action_object", "none"],
    provider_tools_enabled: bool,
    action_object_tool_fallback_enabled: bool,
    multi_tool_calls_allowed: bool,
    agent_visible_instruction: dict[str, Any],
    hidden_transport_policy: dict[str, Any],
    cache_policy: dict[str, Any],
)
```

设计约束：

- `ToolCallContract` 是当前回合工具调用合同，不是能力安装注册表。
- agent 可见部分不得包含 provider/native/sidecar/JSON transport 词。
- hidden policy 可以包含工程字段，但只能用于 provider payload、parser 和 diagnostics。
- 合同由 `RuntimeToolPlan` 派生，不允许 parser 或 model gateway 自己重新判断工具集合。

## 5. Prompt 语义标准

### 5.1 agent 应看到的工具说明

推荐语义：

```text
当前回合可使用工具。
当你需要读取、查证、修改、搜索或验证时，选择一个当前可用工具并填写参数。
你可以先给用户一个简短公开判断，说明本次工具行动要确认什么。
工具返回观察后，你需要根据观察继续判断：继续查证、询问用户、说明阻塞或给出最终回答。
```

禁止语义：

```text
provider-native tool call
tools sidecar
JSON action required
tool channel closed
runtime closeout
修复通道
伪工具块
```

### 5.2 工具目录应该表达什么

稳定工具目录只表达：

- 工具精确名称。
- 适用场景。
- 关键参数字段。
- 权限或副作用边界。
- schema ref / catalog hash。

稳定工具目录不表达：

- 完整 provider schema 大对象。
- provider tools sidecar。
- MCP server 安装细节。
- transport 选择机制。

## 6. 缓存标准

工具调用体系必须遵守以下缓存边界：

- `Tool Capability Surface` 可以是 session stable，但必须瘦身，只保留语义摘要和 schema refs。
- provider tools sidecar 永远是 current provider request 的传输结构，`cache_scope=none`，`cache_role=never_cache`。
- 不再生成重复的大型 `tool_schema_catalog` message。
- `tool_index_stable` 与 provider sidecar 必须共用同一 canonical schema ref。
- 如果 provider sidecar 与 stable catalog 不匹配，诊断应明确失败，不应把 drift 当作正常稳定前缀。

## 7. 实施阶段

### 阶段 1：文档与旧路线清理

目标：

- 以本文作为工具调用体系标准化计划。
- 旧 `tool_transport_adapter.py` 路线废弃，不再恢复该文件名。
- capability 总规划保留，但其 7.3 节只作为能力系统与工具调用合同的接口说明。

完成标准：

- 文档里不再把 `tool_transport_adapter.py` 作为目标文件。
- 后续实施以 `tool_call_contract.py` 或等价合同模块为准。

### 阶段 2：定义 ToolCallContract

涉及文件：

- `backend/harness/runtime/tool_call_contract.py`
- `backend/harness/runtime/tool_plan.py`
- `backend/harness/runtime/compiler.py`

目标：

- 从 `RuntimeToolPlan` 派生本轮工具调用合同。
- 默认普通工具为 `provider_tool_selection`。
- 仅在 provider 不支持 tools 或显式配置时切到 `action_object`。
- 控制动作始终使用 action object。

完成标准：

- 编译出的 packet 有 hidden `tool_call_contract`。
- agent 可见运行投影不出现 provider/native/sidecar/JSON transport 词。
- model gateway 和 parser 都读取同一合同，不自行判断。

### 阶段 3：compiler prompt 契约收口

涉及文件：

- `backend/harness/runtime/compiler.py`
- `backend/harness/runtime/dynamic_context/runtime_delta_projector.py`
- `backend/prompt_library/rules.py`
- `backend/prompt_library/utility_prompts.py`

目标：

- 去掉 agent-visible transport 工程词。
- 把工具行动描述成“选择工具并填写参数”。
- 把控制动作描述成“提交本次行动对象”。
- 工具观察后的 follow-up prompt 只反馈事实和下一步，不诱导 agent 手写 JSON 工具对象。

完成标准：

- agent 可见文本不出现 `provider-native / sidecar / tool channel / closeout / JSON action required`。
- 工具调用前公开判断被明确允许。
- 工具观察后 agent 能继续判断，而不是被系统压成固定格式修复。

### 阶段 4：provider payload 与 action object 分离

涉及文件：

- `backend/harness/runtime/provider_tool_schema.py`
- `backend/runtime/model_gateway/provider_payload.py`
- `backend/runtime/model_gateway/lightweight_chat_model.py`
- `backend/harness/loop/single_agent_turn.py`

目标：

- provider mode：`available_tools` -> provider tools sidecar。
- action-object mode：不挂 provider tools sidecar，工具请求通过 action object 表达。
- 两种模式共享 mounted tool names、canonical schema refs、admission/execution。
- 不允许同时向 agent 暴露两套工具提交方法。

完成标准：

- provider mode diagnostics：`ordinary_tool_submission=provider_tool_selection`。
- action-object fallback diagnostics：`ordinary_tool_submission=action_object`。
- 任一模式下最终都归一为 `ModelActionRequest(action_type="tool_call")`。

### 阶段 5：权限反馈标准化

涉及文件：

- `backend/harness/loop/single_agent_turn.py`
- `backend/harness/loop/admission.py`
- `backend/harness/loop/execution_kernel.py`
- `backend/runtime/tool_runtime/tool_executor.py`

目标：

- denied / approval / invalid args / unknown tool / budget exhausted 都返回 agent-visible feedback。
- 过边界不执行，但不静默终止 agent。
- 工具次数耗尽后只关闭工具动作，仍让 agent `respond / ask_user / block`。

完成标准：

- 任何未执行工具意图都记录 `attempted_actions_not_executed`。
- agent follow-up 能看到“未执行原因”和“当前允许动作”。
- 没有真实 observation 时，agent 不会被诱导说已经执行。

### 阶段 6：MCP 工具并入同一合同

涉及文件：

- `backend/capability_system/mcp/*`
- `backend/capability_system/catalog_projection.py`
- `backend/harness/runtime/tool_plan.py`
- `backend/harness/runtime/tool_call_contract.py`

目标：

- MCP tool 经过 install / inspect / enable / permission 后进入 mounted tools。
- agent 不看到 MCP 安装细节，只看到当前可用工具。
- MCP tool 和 builtin tool 一样走 ToolCallContract、admission、batch plan 和 observation。

完成标准：

- MCP tool 不绕过 operation permission。
- MCP server command/env/token 不进 agent prompt。
- MCP tool 不形成第二套工具调用协议。

## 8. 验证方式

不新增测试文件。

验证顺序：

1. 静态阅读确认工具调用链只有一个主入口。
2. `python -m py_compile` 检查被改文件。
3. 固定后端 `127.0.0.1:8003`、前端 `127.0.0.1:3000` 真实启动。
4. 真实 single-agent turn 验证 provider-native 工具调用：
   - 请求读取一个文件。
   - 检查 provider tool call 是否进入 `ModelActionRequest(action_type="tool_call")`。
   - 检查 observation 是否回填。
5. 真实 fallback 验证 action-object 工具调用：
   - 显式关闭 provider tools。
   - 检查 action object 工具请求是否进入同一 execution 链。
6. 权限边界验证：
   - 请求越界工具或越界路径。
   - 确认不执行，且 agent 获得可反馈事实。
7. 缓存验证：
   - 三轮普通对话检查 provider sidecar 不进入 stable prefix。
   - 检查 `tool_index_stable` 与 provider sidecar schema ref 一致。

## 9. 文件级执行清单

优先级从高到低：

1. `backend/harness/runtime/tool_call_contract.py`
   - 新增当前回合工具调用合同。
   - 不命名为 `tool_transport_adapter.py`。

2. `backend/harness/runtime/compiler.py`
   - 接入 `ToolCallContract`。
   - 清理 agent-visible transport 词。
   - 输出稳定工具语义面和 hidden transport policy。

3. `backend/harness/loop/single_agent_turn.py`
   - parser 读取合同。
   - provider-native 和 action-object 归一为同一 `ModelActionRequest`。
   - 工具观察 follow-up 反馈按合同生成。

4. `backend/harness/runtime/provider_tool_schema.py`
   - 只负责 provider tools schema 生成。
   - 不承担 agent-visible 工具目录。

5. `backend/runtime/model_gateway/provider_payload.py`
   - provider tools sidecar 继续标为 never-cache。
   - drift 诊断使用 canonical schema ref。

6. `backend/harness/runtime/tool_catalog_manifest.py`
   - 保留工具摘要、关键字段、schema refs。
   - 不输出重复大 schema。

7. `backend/harness/runtime/dynamic_context/runtime_delta_projector.py`
   - 当前回合动态投影只展示 agent 可理解的工具行动边界。

8. `backend/capability_system/mcp/*`
   - MCP 工具接入 mounted tools，不建立第二套调用协议。

## 10. 不允许事项

- 不恢复 `backend/harness/runtime/tool_transport_adapter.py`。
- 不把 provider sidecar 写进 stable prompt。
- 不把 Skills 当 Tools 执行。
- 不让 MCP tool 绕过 permission admission。
- 不让 parser 根据用户自然语言替 agent 选择工具。
- 不同时向 agent 暴露 provider-native 和 action-object 两套工具提交方法。
- 不用“格式错误”“工具通道关闭”“closeout”等工程词污染 agent 可见反馈。
- 不在工具越界、工具次数耗尽、权限拒绝时直接静默终止 agent。

## 11. 最终验收标准

- 工具调用体系有唯一主链。
- provider-native 是普通工具调用主路径。
- JSON/action-object 是控制动作和明确 fallback，不污染 provider 主路径。
- agent 可见语义低污染，只表达工具能力、行动边界和反馈事实。
- 所有工具请求最终进入同一 admission/execution/observation 链。
- 权限系统只阻止越界执行，不阻止 agent 合法反馈。
- provider sidecar 不再卡 stable prefix 缓存。
- MCP、builtin tools、未来远程能力都能接入同一工具调用合同。
