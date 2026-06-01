# Query / Intent / ResponseSystem 残留清理与主链路分层迁移计划

日期：2026-06-02

## 1. 修正后的判断

本次清理不能把旧结构整体搬进 `harness`。`harness` 只应该承载运行编排权，不应该成为旧 `query`、`intent`、`response_system` 的收容层。

正确分层如下：

```text
api
-> harness.entrypoint
-> harness.loop / harness.graph
-> runtime.model_gateway / runtime.tool_runtime
-> runtime.output_boundary
-> task_system.contracts
```

## 2. 迁移归属

### 2.1 `backend/query`

拆分处理：

- `QueryRequest` 迁到 `backend/harness/entrypoint/models.py`，改名为 `HarnessRuntimeRequest`。
- `QueryRuntime` 的入口编排部分迁到 `backend/harness/entrypoint/runtime_facade.py`，改名为 `HarnessRuntimeFacade`。
- `run_direct_system_route` 不进 harness，迁到 `backend/api/chat_direct_routes.py`。它是 API 前置直达系统路由，不是 agent harness 编排。
- 图节点 work order / contract helper 下沉到 `backend/harness/graph/work_order_contract.py`。
- 迁移后删除 `backend/query`。

### 2.2 `backend/intent`

拆分处理：

- `intent.communication_frame` 删除。它是旧 intent 分类器，会和模型 turn decision、response boundary 争夺决策权。
- `ExecutionObligation` 和 `build_execution_obligation` 迁到 `backend/task_system/contracts/execution_obligation_models.py` 与 `backend/task_system/contracts/execution_obligation.py`。
- 迁移后删除 `backend/intent`。

### 2.3 `backend/response_system`

拆分处理：

- 输出边界不进 harness，迁到 `backend/runtime/output_boundary`。
- `AssistantOutputBoundary`、输出分类器、输出模型、sanitizer 迁入 runtime output boundary。
- RAG finalizer 迁到 `backend/runtime/output_boundary/rag_finalizer.py`，由 evidence output policy 调用。
- `AnswerAssembler` 与 `tool_output_adapter` 若无生产引用，删除。
- 迁移后删除 `backend/response_system`。

## 3. 关键调用点

必须更新：

- `backend/bootstrap/app_runtime.py`
  - `query_runtime` 改为 `harness_runtime`。
- `backend/api/chat.py`
  - `QueryRequest` 改为 `HarnessRuntimeRequest`。
  - `runtime.query_runtime.astream()` 改为 `runtime.harness_runtime.astream()`。
- 所有 `backend/api/*`
  - `runtime.query_runtime.*` 改为 `runtime.harness_runtime.*`，或改为更明确的 runtime host/service 访问。
- `backend/api/health_system.py`
  - `HealthRuntimeQueryAdapter` 改为 `HealthRuntimeHarnessAdapter`。
- `backend/scripts/diagnose_real_writing_prompt_cache.py`
  - `query.runtime` helper 改为 `harness.graph.work_order_contract`。
- `backend/runtime/model_gateway/model_response.py`
  - 改从 `runtime.output_boundary` 引入输出边界。
- `backend/harness/loop/presentation.py`
  - 改从 `runtime.output_boundary` 引入 sanitizer。
- `backend/memory_system/continuity.py`
  - 改从 `runtime.output_boundary` 引入 sanitizer。
- `backend/evidence/output_policy.py` 与 `backend/evidence/orchestrator.py`
  - 改从 `runtime.output_boundary.rag_finalizer` 引入 RAG finalizer。
- `backend/task_system/services/assembly_support.py`
  - 改从 `task_system.contracts.execution_obligation` 引入。

## 4. 测试策略

不只改少数代表测试。必须用静态扫描全量迁移：

```powershell
rg -n "from query|import query|query_runtime|QueryRuntime|QueryRequest|from intent|import intent|from response_system|response_system" backend -g "!**/__pycache__/**" -g "!**/.pytest_cache/**"
```

重点测试：

- `backend/tests/query_runtime_runtime_loop_regression.py` 改名/改导入为 harness runtime facade regression。
- `backend/tests/graph_task_runtime_facade_regression.py`
- `backend/tests/graph_memory_output_gate_regression.py`
- `backend/tests/graph_node_prompt_budget_regression.py`
- `backend/tests/execution_obligation_regression.py`
- `backend/tests/output_boundary_progress_regression.py`
- `backend/tests/rag_finalizer_prompt_accounting_test.py`
- `backend/tests/capability_quality_regression.py`
- `backend/tests/app_smoke_regression.py`
- `backend/tests/health_management_control_plane_regression.py`

只保护旧模块内部形状、且没有目标行为价值的旧测试删除或改写。

## 5. 完成标准

- `backend/query` 不存在。
- `backend/intent` 不存在。
- `backend/response_system` 不存在。
- 生产代码没有 `runtime.query_runtime`、`from query`、`from intent`、`from response_system`。
- 主入口在 `backend/harness/entrypoint`。
- 图 work order 契约 helper 在 `backend/harness/graph`。
- 输出边界在 `backend/runtime/output_boundary`。
- 执行义务在 `backend/task_system/contracts`。
- 核心回归通过。
- 涉及启动链路时，固定端口 `3000` / `8003` 真实启动可用。
