# task_selection 串线与环境绑定重构计划书

日期：2026-06-08

## 结论

当前 `task_selection` 不是一个真实的任务选择层，而是把四类不同权威混在了同一个字段里：

1. 用户/界面选择的环境绑定。
2. graph/task 节点下发的运行契约。
3. 工具能力与执行许可。
4. 记忆系统是否进行长期记忆召回的触发信号。

主聊天并没有 `task selection`。主聊天只应携带用户显式选择的 `environment_binding`，这个绑定只能约束工作区、文件/工具边界、记忆命名空间和展示范围，不能被解释为“用户正在执行某个任务”。图任务则应从 `work_order` / `TaskRunContract` 生成显式运行契约，不能伪装成主聊天任务选择。

这也是本次慢回复的直接原因：主聊天发送了环境绑定，但字段名是 `task_selection`；memory provider 看到非空 `task_selection` 后触发 `memory.durable_recall_selector`，导致主回答前多了一次串行 DeepSeek 调用。

## 已确认的问题证据

最近一次慢运行：

- 会话：`session-1bbe0b7b504f436d`
- 运行：`strun:9a0527846c4d4baaa406d27dc95dce51`
- SSE 总耗时约 50s。
- `input_commit_gate -> runtime_branch_decided` 约 22.6s。
- `single_agent_turn_started -> assistant_message_committed` 约 22.1s。

对应两次串行模型请求：

1. `memory.durable_recall_selector`，约 21.95s。
2. 主 agent turn，约 21.94s。

因此性能问题不是投影本身慢，而是主回答前被长期记忆 selector 阻塞了一轮。

## 当前链路

### 主聊天入口

- `frontend/src/lib/api.ts`
  - `ChatRunCreatePayload.task_selection?: Record<string, unknown>`
- `frontend/src/lib/store/runtime.ts`
  - `sendMessage` 发送 `task_selection: this.chatTaskSelectionPayload(requestState)`
  - `chatTaskSelectionPayload` 实际返回的是环境绑定字段：
    - `task_environment_id`
    - `environment_id`
    - `environment_label`
    - `binding_kind`
    - `binding_source`
    - `bound_at`
- `backend/api/chat.py`
  - `ChatRequest.task_selection`
  - 转成 `HarnessRuntimeRequest.task_selection`
- `backend/harness/entrypoint/runtime_facade.py`
  - 把 `request.task_selection` 同时传给 runtime assembly、turn facts、session emphasis、memory context。

### 记忆触发

- `backend/memory_system/runtime_context_provider.py`
  - `should_consider_long_term_memory` 对任意非空 `task_selection` 返回 true。
  - `should_inject_session_emphasis` 也对任意非空 `task_selection` 返回 true。

这使得“用户选择了环境”被错误解释成“需要长期任务记忆召回”。

### Graph/task 链路

- `backend/harness/graph/work_order_contract.py`
  - `_graph_node_task_selection` 把 `selected_task_id`、`task_environment_id`、`runtime_profile`、`prompt_contract`、`allowed_operations` 混成 selection。
- `backend/harness/loop/task_lifecycle.py`
  - `_runtime_task_selection_from_contract` 从 `TaskRunContract` 生成旧 selection bag。
- `backend/harness/loop/task_executor.py`
  - 从 diagnostics 的 `runtime_task_selection` 读取模型、环境和运行策略。
- `backend/harness/runtime/run_monitor/projector.py`
  - 从 `runtime_task_selection` / `task_selection` 推断 scope。

Graph 节点确实有“任务契约”，但不应命名为 `task_selection`。它应该是 `runtime_contract` 或更具体的 `graph_node_runtime_contract`。

## 成熟 agent 参考

本次审查参考了本地 Codex 与 Claude Code dump 的外显结构：

- Codex `codex-rs/core/src/session/turn_context.rs`
  - `TurnContext` 将 `environments`、`permission_profile`、`tool_mode`、`dynamic_tools` 分开保存。
- Codex `codex-rs/core/src/session/turn.rs`
  - prompt 构建使用 `ToolRouter` 的 model-visible specs，工具暴露由 router 负责，不混入任务意图字段。
- Codex `codex-rs/codex-mcp/src/tools.rs`
  - 工具过滤、模型可见 schema 和原始工具身份分层处理。
- Claude Code dump `query.ts`
  - memory prefetch 是零等待消费；未完成时跳过本轮注入，不阻塞主 assistant turn。
- Claude Code dump `context.ts`
  - system/user context 会缓存，不在每轮主回答前无条件串行重算。

可采用的成熟链路是：

```text
RequestFacts
-> BoundaryPolicy
-> ContextCandidates
-> ModelTurnDecision
-> ActionPermit
-> RuntimeStartPacket
-> ExecutionLoop
```

环境绑定属于 `RequestFacts / BoundaryPolicy`；长期记忆候选属于 `ContextCandidates`；工具许可属于 `ActionPermit`；graph 节点契约属于 `RuntimeStartPacket`。这些层不能复用同一个 `task_selection` 字段。

## 目标契约

### `environment_binding`

用户或 UI 选择的当前运行环境。

允许用途：

- 解析 workspace / project / task environment scope。
- 约束文件、工具、终端、memory namespace。
- 作为 UI 展示和 trace 记录。

禁止用途：

- 不得触发长期记忆 selector。
- 不得被当作用户任务类型或 selected task。
- 不得授予工具能力。
- 不得改写 prompt 角色。

建议结构：

```json
{
  "task_environment_id": "env.coding.vibe_workspace",
  "environment_id": "env.coding.vibe_workspace",
  "environment_label": "Vibe Workspace",
  "binding_kind": "conversation_active_task_environment",
  "binding_source": "conversation",
  "bound_at": "2026-06-08T..."
}
```

### `active_work_context`

运行时从当前会话状态、进行中的执行、最近结果中观察到的工作上下文。

允许用途：

- 帮助 memory/provider 判断是否存在真实工作连续性。
- 帮助 runtime 恢复显式存在的 active turn。

禁止用途：

- 不得凭空创建任务类型。
- 不得从环境绑定推断 active work。

### `runtime_contract`

由 graph/work_order/task contract 或外部明确 contract 生成。

允许包含：

- `task_id` / `node_id` / `run_id`
- `task_environment_id`
- `prompt_contract`
- `runtime_profile`
- `allowed_operations`
- `execution_permit`
- `model_requirement`

禁止用途：

- 不得承载主聊天环境绑定。
- 不得被主聊天默认构造。

### `runtime_capability_request`

本轮运行需要的模型、工具、权限能力申请。

允许来源：

- graph contract
- 用户显式请求
- runtime profile

禁止来源：

- 环境绑定字段。
- memory provider 的推断。

## 目标链路

### 主聊天

```text
Frontend active environment
-> ChatRequest.environment_binding
-> HarnessRuntimeRequest.environment_binding
-> runtime assembly environment_scope
-> memory namespace only
-> main model turn
```

关键约束：

- 主聊天 request 不再发送 `task_selection`。
- environment binding 不触发 durable recall selector。
- durable recall 只在以下条件触发：
  - 用户显式要求读取/回忆长期记忆。
  - 存在真实 active work context。
  - 存在 recent work outcome。
  - graph/task runtime contract 明确要求。

### Graph/task

```text
Graph work_order
-> TaskRunContract
-> GraphNodeRuntimeContract
-> runtime_contract / execution_permit
-> task executor
-> diagnostics.runtime_contract
```

关键约束：

- `_graph_node_task_selection` 改成 graph runtime contract projection。
- diagnostics 不再写 `runtime_task_selection`。
- task executor / monitor 不再从 selection bag 推断环境或模型。

## Prompt 修复标准

Prompt 必须写给 agent 本身，而不是写给开发者或 runtime 节点。

禁止写法：

```text
这是 runtime 节点。
根据任务图执行 world_review。
这个节点用于校验资产。
```

正确写法：

```text
你是一名世界观审核员。
你只负责评审当前世界观设定是否完整、一致、可支撑后续写作。
你不负责替创作者扩写设定。
你需要指出问题、给出裁决、说明是否允许进入下一阶段。
```

本次需要搜索并修复：

- `task_selection`
- `runtime_task_selection`
- `selected_task_id`
- `任务选择`
- `runtime 节点`
- `根据任务图执行`
- `这个节点用于`

Prompt 中允许出现环境信息，但必须表达为边界和可用上下文，不能表达为任务意图。

## 实施计划

### Phase 1：切断主聊天慢路径

文件：

- `frontend/src/lib/api.ts`
- `frontend/src/lib/store/runtime.ts`
- `frontend/src/lib/store/runtime.test.ts`
- `backend/api/chat.py`
- `backend/harness/entrypoint/models.py`
- `backend/harness/entrypoint/runtime_facade.py`
- `backend/memory_system/runtime_context_provider.py`
- `backend/memory_system/environment_context.py`

改动：

1. 前端 payload 改为 `environment_binding`。
2. 后端请求模型改为 `environment_binding`。
3. runtime facade 不再把主聊天环境传入 `task_selection`。
4. memory provider 删除“任意非空 task_selection 触发长期记忆”的逻辑。
5. 增加回归测试：仅有 environment binding 时，不触发 durable recall selector。

完成标准：

- 主聊天 API payload 不含 `task_selection`。
- 主聊天绑定环境不会启动 durable selector。
- 现有聊天仍能拿到正确环境 scope。

### Phase 2：拆分 runtime assembly 契约

文件：

- `backend/harness/runtime/assembly.py`
- `backend/harness/runtime/tool_scheduling.py`
- `backend/harness/runtime/tool_plan.py`
- `backend/harness/runtime/semantic_compaction_adapter.py`
- `backend/api/orchestration_catalog.py`
- `backend/cli/main.py`
- `backend/cli/client.py`
- 相关 tests

改动：

1. `request_task_selection` 替换为明确参数：
   - `environment_binding`
   - `runtime_contract`
   - `runtime_capability_request`
2. `RuntimeAssembly.task_selection` 删除或改成明确字段。
3. 工具计划只读取 `runtime_capability_request` / `runtime_contract.execution_permit`。
4. CLI 不再发送 `task_selection`，只发送 `environment_binding`。

完成标准：

- `assemble_runtime` 不再需要 `request_task_selection`。
- runtime assembly 输出不再包含 `task_selection`。

### Phase 3：Graph/task contract 正名

文件：

- `backend/harness/graph/work_order_contract.py`
- `backend/harness/loop/task_lifecycle.py`
- `backend/harness/loop/task_executor.py`
- `backend/harness/runtime/run_monitor/projector.py`
- graph/task regression tests

改动：

1. `_graph_node_task_selection` 改为 `_graph_node_runtime_contract`。
2. `_runtime_task_selection_from_contract` 改为 `_runtime_contract_from_task_run_contract`。
3. diagnostics 改为 `runtime_contract`。
4. executor / projector 从 contract 读取环境、模型和 permission。

完成标准：

- graph/task 仍可按节点契约执行。
- `runtime_task_selection` 不再出现在 active runtime diagnostics 中。

### Phase 4：Prompt 审查与修复

文件范围：

- `backend/prompt_library`
- `backend/prompting`
- `backend/task_system`
- graph/node prompt 配置
- runtime semantic prompt 文件

改动：

1. 删除给模型看的开发说明式 prompt。
2. 将节点 prompt 改为角色、职责、边界、输入、输出、裁决标准和失败处理。
3. 删除把 `task_selection` 当作 agent 可见任务依据的 prompt 片段。

完成标准：

- prompt 搜索不再命中开发式节点说明。
- graph 节点 prompt 明确角色和裁决标准。

### Phase 5：验证

后端 focused tests：

```powershell
python -m pytest backend/tests/runtime_memory_context_provider_regression.py backend/tests/harness_runtime_facade_regression.py -q
python -m pytest backend/tests/task_environment_registry_regression.py backend/tests/graph_task_runtime_facade_regression.py -q
```

前端 focused tests：

```powershell
npm --prefix frontend test -- runtime.test.ts
```

固定端口实测：

```powershell
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8003
npm --prefix frontend run dev -- --hostname 127.0.0.1 --port 3000
```

验收点：

- `3000` 只有一个前端进程监听。
- `8003` 只有一个后端进程监听。
- 前端请求目标为 `http://127.0.0.1:8003/api`。
- 主聊天环境绑定请求不会产生 `memory.durable_recall_selector`。
- graph 任务仍能按 contract 运行。

## 删除标准

本次不保留无意义兼容层。旧代码满足以下条件即删除或改名：

1. 字段或函数名仍表达 `task_selection`，但实际承载环境、许可或契约。
2. 逻辑根据 `task_selection` 推断用户意图。
3. prompt 将 runtime/node 技术说明暴露给 agent。
4. 测试只保护旧字段名，而不保护真实行为。

如果存在外部公开 API 迁移窗口，必须在代码中标明迁移边界和删除条件；本项目内部链路不以兼容为理由保留旧路径。
