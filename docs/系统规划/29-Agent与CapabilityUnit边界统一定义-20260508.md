# Agent 与 Capability Unit 边界统一定义

## 1. 目标

解决系统中 `agent / capability unit / mcp endpoint / tool` 四类对象长期混用的问题，统一编排系统、任务图系统、能力系统和运行时中的对象语义，避免能力单元被错误投影成 agent。

本定义作为后续任务图编排、装配、RunLoop、能力系统前端、健康系统追踪与测试体系的共同边界。


## 2. 四层对象定义

### 2.1 Agent

Agent 是编排主体，不是执行插件。

Agent 必须具备以下特征：

- 有稳定 `agent_id`
- 可被任务系统直接绑定到任务节点
- 可作为主会话、协调者或 worker 参与编排
- 有独立 runtime profile / soul / projection / task carrying 语义
- 在任务图、协调图、A2A 协议和运行时 trace 中可以作为责任主体出现

当前系统中，只有 `AgentRegistry` 中登记的实体才是 Agent。


### 2.2 Capability Unit

Capability Unit 是内部能力单元，不是编排主体。

它表示一组面向特定输入源或特定处理域的封装能力，例如：

- `retrieval`
- `pdf`
- `structured_data`

Capability Unit 可以：

- 有稳定 `unit_id`
- 绑定固定 operation
- 绑定固定 worker / executor
- 暴露为内部 MCP endpoint
- 被 orchestrator 选中并调度

Capability Unit 不可以：

- 拥有 `agent_id`
- 出现在 agent registry
- 被任务图节点直接当作 agent 绑定
- 出现在 A2A agent cards 中
- 在前端以“某个 agent”的身份展示


### 2.3 MCP Endpoint

MCP Endpoint 是能力暴露接口，不是能力主体。

它是 Capability Unit 的调用面，负责描述：

- route
- operation_id
- input/output schema
- transport
- invocation_mode
- model_visibility

MCP Endpoint 的 owner 应该是 `owner_units`，而不是 `owner_agents`。


### 2.4 Tool

Tool 是模型可见或运行时可见的调用工具。

Tool 的职责是：

- 描述调用契约
- 进入 operation registry / tool registry
- 决定是否对主运行时可见
- 决定是否需要 approval / gate / policy

Tool 不是 Agent，也不是 Capability Unit。


## 3. 责任边界

### 3.1 Agent 的责任

- 理解任务
- 参与任务图和协调图
- 进行上下文组织、分工、汇总、交接
- 承担 trace 中的责任主体


### 3.2 Capability Unit 的责任

- 在特定领域内执行处理
- 产出 canonical result / evidence / handles
- 为 orchestrator 提供可调度但非人格化的执行单元


### 3.3 Orchestrator 的责任

- 决定调用哪个 Agent
- 决定调用哪个 Capability Unit
- 决定是否走 main runtime / local mcp / direct rag
- 负责把结果回收并重新投影到主线程


## 4. 数据模型约束

后续代码中应遵守以下硬约束：

### 4.1 Agent 相关模型

只有以下链路允许出现 `agent_id`：

- `AgentRegistry`
- task / workflow / coordination / task graph node
- runtime assembly
- run loop trace
- health / maintenance / diagnostics 中的 agent run


### 4.2 Capability Unit 相关模型

能力单元必须使用：

- `unit_id`
- `route`
- `operation_id`

不得再引入以下字段语义：

- fake `agent_id`
- `a2a_name`
- `a2a_description`
- `a2a_skill_*`


### 4.3 Endpoint 相关模型

端点所有权统一使用：

- `owner_units`

不得继续输出：

- `owner_agents`


## 5. UI 展示约束

### 5.1 Agent 页面

Agent 页面只展示真实 Agent：

- 主 Agent
- 系统管理 Agent
- Worker Sub Agent

不展示：

- pdf
- retrieval / rag
- structured_data


### 5.2 能力系统页面

能力系统页面展示：

- skills
- tools
- capability endpoints
- local capability units

这里的能力对象不得使用 Agent 文案，不得出现“宿主 Agent”这类误导信息。


### 5.3 任务图 / 协调图页面

任务图节点的 `agent_id` 只能来自真实 agent 目录。

能力单元如果需要被引用，必须通过以下方式间接进入：

- task mode / route hint
- operation binding
- runtime lane
- endpoint / unit metadata

不能直接拿 capability unit 冒充 agent 节点。


## 6. 运行时判定原则

RunLoop 中统一采用以下判定：

- `agent`：编排主体
- `mcp`：内部端点调度
- `tool`：主运行时或受控运行时调用对象
- `capability_unit`：被 orchestrator 绑定到 mcp route 的内部执行单元

判定顺序应优先基于对象类型，而不是基于命名风格或历史兼容字段。


## 7. 清理结论

本次已完成的清理：

- 移除本地 MCP 单元 fake `agent_id`
- 移除 capability endpoint 的 `owner_agents`
- 移除 capability catalog 中 MCP 单元的 agent projection
- 移除本地能力单元伪造的 A2A agent cards
- 将任务系统中的 A2A agent cards 改为真实 agent registry 来源


## 8. 下一步执行项

下一阶段建议继续收敛以下几条链路：

1. 检查 `task_graph_models.py`、task graph compiler、coordination graph spec，确认节点层只接受真实 agent
2. 检查 runloop trace / health trace 中是否还存在 capability unit 被记作 agent 的字段
3. 检查前端 TaskSystemView / CoordinationEditorWorkbench 是否还有“能力对象 = agent”的展示假设
4. 为 capability unit / endpoint / agent 增补结构性回归测试，禁止旧模型回流


## 9. 最终原则

一句话定规矩：

- Agent 负责编排
- Capability Unit 负责处理
- MCP Endpoint 负责暴露
- Tool 负责调用

四者可以协作，但不能再互相冒名顶替。
