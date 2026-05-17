# 138-delegate_to_agent非图化通信链收口实施计划

日期：2026-05-17

## 1. 问题定义

60 轮真实情景测试中，旧模板注册表错误已经消失，但普通 `delegate_to_agent` 轮次仍出现运行态降级：

```text
Legacy coordination continuation path was removed for unsupported coordination run: coordrun:delegation:req:*
```

追踪结果表明，当前 delegation 链路处在“半图半非图”的结构中：

1. 主 agent 调用子 agent 本身已经有通信协议：`DelegationCatalog`、`AgentDelegationRequest`、`AgentDelegationResult`、child runtime context、parent observation。
2. 但执行阶段额外创建了 `CoordinationRun`、`CoordinationNodeRun`、`AgentHandoffEnvelope`，让普通 delegation 看起来像 TaskGraph 协调运行。
3. 这些 coordination 对象又没有完整 TaskGraph runtime 所需的 `task_graph_definition_ref`、`task_graph_runtime_spec_ref`、`coordination_graph_spec_ref`。
4. 因此收尾和续跑阶段会被 `LangGraphCoordinationRuntime.supports()` 拒绝，导致 `finished_task_run_state_write` 降级。

结论：问题不是普通 delegation 缺少通信协议，而是普通 delegation 被错误地半图化了。

## 2. 架构决策

普通主 agent 长任务不图化。

`delegate_to_agent` 默认回归现有 delegation/A2A/handoff 通信协议，不创建 TaskGraph `CoordinationRun`。

图化运行只分配给显式多 agent TaskGraph 任务，包括：

- 用户明确选择或启动 TaskGraph。
- 系统已有 TaskGraph 节点调度。
- 多 agent 协调任务需要节点级 monitor、resume、manual gate、merge、retry 或下钻审计。

普通主 agent 长任务包括：

- 自然搜索网站再分析。
- 自然读取 PDF、知识库、表格后综合。
- 根据需要临时调用一个或多个内置子 agent。
- 像 Codex 一样边探索、边记录证据、边收口。

这类任务不要求用户提前创建图，也不把每次子 agent 调用提升成 TaskGraph 子图。

## 3. 设计目标

1. 任务发起自然：主 agent 仍然按用户目标自然规划和委派，不需要理解 TaskGraph。
2. 子任务执行自然：子 agent 收到角色化、任务化的委派说明，不接收 runtime 节点说明。
3. 父级收口自然：父 agent 基于 `AgentDelegationResult` 和 parent observation 自然采纳、拒绝、补充或降级。
4. 通信协议保留：继续使用现有 delegation request/result、catalog、context policy、timeout policy、child context、parent observation。
5. 图化边界清晰：普通 delegation 不创建 `CoordinationRun`；显式多 agent TaskGraph 仍使用 `CoordinationRun`。
6. 运行不冲突：普通 delegation 不再进入 LangGraph continuation support 判定，也不再触发 unsupported coordination run。

## 4. 保留的现有通信能力

普通 `delegate_to_agent` 保留以下对象和流程：

- `DelegationCatalog`
  - 决定哪些内置子 agent 可用。
  - 暴露 delegation kind、输入输出契约、context policy。
- `AgentDelegationRequest`
  - 表达目标子 agent、委派类型、任务说明、输入载荷、预期输出和限制。
- `AgentRun`
  - 记录一次子 agent 执行。
  - `spawn_mode="delegation"`，`context_scope="delegation_scoped"`。
  - 普通 delegation 下不写 `coordination_run_ref`。
- `AgentDelegationResult`
  - 返回摘要、候选答案、证据引用、产物引用、置信度、限制和追问。
- `AgentRunResult`
  - 记录子 agent run 的结果引用。
- runtime event log
  - 记录 request、child run、child runtime start、quality check、result created、parent observation。
- parent observation
  - 给主 agent 一个结构化观察，用于自然收口。

说明：`AgentHandoffEnvelope` 当前强依赖 `coordination_run_id`，因此普通 delegation 不再强行创建它；handoff envelope 继续留给显式 TaskGraph coordination run 使用。

## 5. 不再创建的半图对象

普通 `delegate_to_agent` 默认不再创建：

- `CoordinationRun`
- `CoordinationNodeRun`
- `CoordinationMergeResult`
- `AgentHandoffEnvelope`
- `delegation_graph`
- `coordrun:delegation:req:*`

这不是削弱通信，而是停止制造不完整的 TaskGraph 运行对象。

如果未来某个入口确实需要“图化 delegation”，必须从显式 TaskGraph 多 agent 任务发起，走完整 TaskGraph/LangGraph runtime，而不是从普通 `delegate_to_agent` 偷偷半图化。

## 6. 自然性边界

### 6.1 发起自然

主 agent 模型可见能力仍然是 `delegate_to_agent`。

主 agent 可以自然决定：

- 是否委派。
- 委派给哪个子 agent。
- 一轮或多轮中是否多次委派。
- 子结果不足时是否换工具、换子 agent 或直接说明限制。
- 何时综合已有结果并回复用户。

不要求主 agent 手写 TaskGraph，也不把 coordination 节点名写入 prompt。

### 6.2 执行自然

子 agent prompt 必须是角色职责说明，不是 runtime 节点说明。

错误示例：

```text
这是 delegate_agent 节点。
根据任务图执行 pdf_reading。
```

正确示例：

```text
你是一名 PDF 阅读员。
你只负责阅读当前指定 PDF，并提取与父任务问题直接相关的结论和证据。
你不负责替父 agent 做最终综合判断。
你需要返回：关键结论、证据位置、无法确认的部分、是否足以支持父任务继续。
```

### 6.3 收口自然

父 agent 不复制子 agent 输出了事，而是读取 parent observation 后自然综合：

- 子结果是否可采纳。
- 哪些证据支持结论。
- 哪些地方仍不足。
- 是否需要继续查证。
- 最终如何面向用户回答。

普通 delegation 的收口状态由 `AgentDelegationResult.status` 和质量门诊断承载，不需要 `CoordinationMergeResult`。

## 7. 与 TaskGraph 的关系

### 7.1 普通长任务

普通主 agent 长任务使用：

```text
TaskRun
  -> model/tool/delegate events
  -> AgentRun
  -> AgentDelegationRequest
  -> AgentDelegationResult
  -> AgentRunResult
  -> parent observation
  -> final answer
```

这条链路适合自然搜索、分析、临时委派和单轮/多轮探索。

### 7.2 显式多 agent TaskGraph

显式多 agent TaskGraph 使用：

```text
TaskGraphDefinition
  -> CoordinationRun
  -> CoordinationNodeRun
  -> AgentDispatchPlan
  -> AgentHandoffEnvelope
  -> CoordinationMergeResult
  -> monitor/resume/manual gate
```

这条链路适合固定多节点协作、可重复流程、后台监测、人工接管和节点级续跑。

### 7.3 边界规则

规则：

- 用户没有显式选择 TaskGraph 时，普通 `delegate_to_agent` 不图化。
- 用户启动 TaskGraph 或运行时已处在 TaskGraph 节点中时，多 agent 协作按 TaskGraph 运行。
- 不允许普通 delegation 创建不完整 `CoordinationRun`。
- 不允许为了压掉错误恢复旧 legacy coordination continuation path。

## 8. 实施计划

### 阶段一：改写普通 delegation 执行链

涉及文件：

- `backend/orchestration/runtime_loop/agent_delegation_executor.py`

目标：

- 移除普通 `delegate_to_agent` 对 `DelegationGraphAdapter.create_runtime_objects()` 的调用。
- child `AgentRun` 不再写入 `coordination_run_ref`。
- 删除 `_complete_delegation_graph` 在普通 delegation 中的调用。
- 增加普通 delegation 的 request/result/observation 事件，保持审计能力。

完成标准：

- 普通 delegation 执行成功或失败时，`state_index.list_task_coordination_runs(task_run_id)` 为空。
- 仍然有 `AgentDelegationRequest`、`AgentRun`、`AgentDelegationResult`、`AgentRunResult`。
- 返回给主 agent 的 parent observation 不变或更清晰。

### 阶段二：收口半图化残留

涉及文件：

- `backend/orchestration/runtime_loop/delegation_graph_adapter.py`
- delegation 相关测试

目标：

- 普通 delegation 不再引用 `delegation_graph_adapter`。
- `delegation_graph_adapter` 若仍保留，只作为历史/显式图化迁移候选，不在普通主链使用。
- 测试不再要求普通 delegation 创建 coordination node/handoff envelope。

完成标准：

- `AgentDelegationExecutor` 不依赖 `DelegationGraphAdapter`。
- 普通 delegation 事件中不再出现 `coordination_run_created`、`coordination_node_run_created`、`handoff_envelope_created`。

### 阶段三：保持显式 TaskGraph 多 agent 链路

涉及文件：

- `backend/orchestration/runtime_loop/task_run_loop.py`
- `backend/orchestration/runtime_loop/langgraph_coordination_runtime.py`
- TaskGraph 相关测试

目标：

- 不破坏显式 TaskGraph 的 `CoordinationRun`、`CoordinationNodeRun`、`AgentHandoffEnvelope`、`CoordinationMergeResult`。
- 保持 136/137 的 monitor、resume、manual gate 能力。

完成标准：

- TaskGraph coordination regression 继续通过。
- 多 agent TaskGraph 场景仍能创建正式 coordination objects。

### 阶段四：回归验证

建议命令：

```powershell
python -m py_compile backend/orchestration/runtime_loop/agent_delegation_executor.py backend/orchestration/runtime_loop/delegation_models.py backend/orchestration/runtime_loop/task_run_loop.py
python -m pytest backend/tests/agent_delegation_permission_regression.py backend/tests/agent_evidence_packet_regression.py backend/tests/main_agent_natural_delegation_regression.py
python -m pytest backend/tests/orchestration_cutover_regression.py backend/tests/langgraph_coordination_runtime_regression.py
python -m backend.tests.system_eval.long_runner --scenario-set mega
```

验收标准：

- 普通 `delegate_to_agent` 不再创建 `coordrun:delegation:req:*`。
- 60 轮长场景不再出现 `Legacy coordination continuation path was removed for unsupported coordination run: coordrun:delegation:req:*`。
- 普通长任务仍能自然调用子 agent，并自然收口。
- 显式 TaskGraph 多 agent 任务仍能创建正式 coordination objects。
- 子 agent prompt 不出现 runtime 节点说明。
- 不伪造测试结果，不绕过 state writeback。

## 9. 不做事项

- 不新增 delegation group。
- 不新增 delegation 专用调度框架。
- 不新增 delegation 专用 API 主链。
- 不恢复旧模板注册表。
- 不让 `supports()` 靠 run id 前缀特判 delegation。
- 不恢复 legacy coordination continuation path。
- 不把主 agent 自然长任务硬编码成 TaskGraph。
- 不把 runtime 节点说明直接写进 agent prompt。
- 不为普通 delegation 强行创建空 `coordination_run_id` 的 handoff envelope。

## 10. 最终目标状态

改造后系统应呈现以下状态：

```text
普通主 agent 长任务：
  自然规划 -> 工具/子 agent 通信 -> 证据沉淀 -> 主 agent 自然收口
  不创建 CoordinationRun

显式多 agent TaskGraph：
  TaskGraphDefinition -> CoordinationRun -> 节点调度 -> handoff -> merge -> monitor/resume
  完整图化运行
```

这条路线的核心价值是：保留主 agent 像 Codex 一样自然推进长任务的能力，同时把 TaskGraph 留给真正需要图化调度、监控和接管的多 agent 任务。普通 delegation 不再半图化，也就不会和 LangGraph continuation 冲突。
