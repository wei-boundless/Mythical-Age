# Runtime Observability 与 Trace 系统重构方案

日期：2026-06-05

状态：计划书，待确认后实施

## 1. 目标结论

本项目应将现有本地 trace 和 RuntimeMonitor 升级为统一的 Runtime Observability System：

```text
RuntimeObservabilitySystem
  ├─ RuntimeMonitorService   # 实时监控、运行态投影、UI 与用户操作入口
  ├─ RuntimeTraceService     # 后台 trace/span/event 记录、排障证据链
  ├─ RuntimeTraceStore       # 本地持久化、索引、查询
  └─ ExportSinks             # Local snapshot / LangSmith / OpenTelemetry 可选导出
```

核心裁决：

- 主权接入 RuntimeSystem，而不是 TaskSystem、ArtifactSystem 或 LangSmith。
- RuntimeMonitor 与 RuntimeTrace 同源，但职责不同：Monitor 负责实时投影，Trace 负责后台记录。
- Trace 系统采用 OpenTelemetry-compatible 的 trace/span/context 语义，但本地 RuntimeTraceStore 是第一事实来源。
- LangSmith 只作为外部 AI observability sink，不作为内部 trace 主模型。
- ArtifactSystem 只负责 trace 文件的治理、保留和清理策略，不拥有运行事实。

## 2. 当前系统事实

### 2.1 现有 RuntimeSystem 已经具备可接入位置

`backend/harness/runtime/single_agent_host.py` 当前集中初始化运行时事实系统：

- `RuntimeEventLog`
- `RuntimeRunRegistry`
- `RuntimeStreamReplayService`
- `PromptAccountingLedger`
- `RuntimeExecutionStore`
- `FileStateAuthorityStore`
- `RuntimeStateIndex`
- `RuntimeObjectStore`
- `GraphCheckpointStore`
- `RuntimeMonitorService`

这些系统已经覆盖运行事实、状态索引、执行记录、模型 token usage、图 checkpoint 和实时 monitor。Trace 系统应该接入这里，成为 RuntimeSystem 的观测子系统。

### 2.2 当前 local trace 是轻量入口日志

`backend/observability/langsmith_tracing.py` 当前包含：

- `LangSmithTurnTrace`
- `LocalTurnTrace`
- `start_turn_trace(...)`
- `build_debug_trace_event(...)`

当前 local trace 特征：

- 一个 turn 结束时写一个 JSON 文件。
- 默认路径为 `output/local_traces/YYYYMMDD/local-*.json`。
- 支持 `stage(...)` API，但生产链路没有实际打 stage。
- 支持 `mark_terminal(...)`，但生产链路没有调用；测试中有手工调用。
- Trace 文件记录 `session_id`、截断后的 `user_message`、`metadata`、`annotations`、`stages`、`error` 等。

问题：

- Trace 没有真实连接模型调用、工具调用、ActionPermit、TaskExecutor、GraphLoop、PromptAccounting。
- Trace 层含有 `_NON_ERROR_TERMINAL_STATUSES`，会替 runtime 判断哪些 stream close 算成功，边界不正确。
- `__exit__` 时一次性写文件，长任务卡死或进程崩溃时会丢失前序诊断。
- `stages` 为空时，trace 只能证明请求进过入口，不能定位 runtime 内部问题。

### 2.3 RuntimeEventLog 不适合作为高频 span 主存储

`backend/runtime/shared/event_log.py` 当前是 JSONL event log，并带 event index、payload externalization 和 subscription。

它适合作为运行事件权威日志，但 `backend/artifact_system/governance.py` 将 `runtime.events` 标记为：

```text
RuntimeSystem / runtime_fact / recovery_critical / archive_not_delete
```

因此不应把所有 trace span 细节直接写入 RuntimeEventLog，避免把诊断级高频数据混入 recovery-critical 事件流。

正确做法：

- RuntimeEventLog 继续记录核心状态事件。
- RuntimeTraceStore 单独记录高频 span/event。
- Trace span 通过 refs 指向 event offset、packet ref、action_request_ref、tool_invocation_id、prompt_usage_id 等证据。

### 2.4 RuntimeMonitor 应接入，但不能拥有 trace 主权

RuntimeMonitor 当前负责：

- 全局运行监控
- session monitor
- task monitor
- turn monitor
- graph monitor
- monitor action
- retention / hidden / restore / delete 等 UI 侧管理

它适合作为 trace 的实时投影层，但不适合作为 trace 主存储：

- Monitor 会聚合、裁剪、隐藏、恢复和清理。
- Monitor 面向 UI，payload 必须简洁。
- Trace 需要保留完整 span 链路、refs、错误和耗时信息。

目标关系：

```text
Runtime emits observability event once
  -> RuntimeMonitorService receives live projection
  -> RuntimeTraceService writes durable diagnostic span/event
```

不是：

```text
RuntimeMonitor summary -> reconstruct trace
```

## 3. 外部参考标准

### 3.1 OpenTelemetry

OpenTelemetry 提供成熟的 trace、span、context、baggage、logs、metrics 语义，并支持 OTLP 导出。其 trace/span 模型适合作为本项目内部 trace schema 的兼容方向。

参考：

- https://opentelemetry.io/docs/reference/specification/overview/
- https://opentelemetry.io/docs/concepts/signals/traces/
- https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/

采用原则：

- 内部字段使用 `trace_id`、`span_id`、`parent_span_id`、`attributes`、`events`、`status` 等 OTel 风格。
- 不在第一阶段强制引入 OpenTelemetry SDK，避免把实现复杂度一次性推高。
- 后续通过 `OtelSink` 导出 OTLP。

### 3.2 W3C Trace Context

跨线程、跨进程、跨服务传播 trace 应参考 W3C Trace Context，使用 `traceparent` / `tracestate` 语义。

参考：

- https://www.w3.org/TR/trace-context/

采用原则：

- 当前项目先在单进程 runtime 内传播 `trace_id` / `span_id`。
- 后续接入 MCP、子进程、浏览器自动化、外部工具时，再扩展 `traceparent`。

### 3.3 LangSmith

LangSmith 适合作为 LLM/agent 观测平台，能展示模型调用、tool call、agent steps 和决策路径。

参考：

- https://docs.langchain.com/oss/python/langchain/observability

采用原则：

- LangSmith 作为可选 sink。
- 本地 RuntimeTraceStore 是内部第一事实来源。
- 不把项目 trace schema 反向设计成 LangSmith 专用 schema。

## 4. 目标权威边界

| 模块 | 目标职责 | 明确禁止 |
|---|---|---|
| RuntimeObservabilityService | 统一打点入口，分发 live monitor 与 durable trace | 不做业务状态推断 |
| RuntimeTraceService | 记录 span、event、refs、耗时、错误 | 不决定任务是否成功，不修改 runtime state |
| RuntimeTraceStore | 本地持久化和索引 | 不成为恢复事实来源 |
| RuntimeMonitorService | 实时投影、UI 状态、用户操作入口 | 不拥有完整 trace，不由 summary 反推 trace |
| RuntimeEventLog | 核心运行事件、恢复关键事实 | 不承载所有高频 span |
| PromptAccountingLedger | token usage 与 prompt cache 账本 | 不拥有 trace，只被 trace 引用 |
| RuntimeExecutionStore | 工具/操作执行记录 | 不拥有 trace，只被 trace 引用 |
| ArtifactSystem | 文件治理、保留、清理 | 不拥有运行事实 |
| LangSmithSink | 外部导出 | 不作为本地唯一 truth |

## 5. 目标数据模型

### 5.1 TraceRun

```json
{
  "trace_id": "trace:...",
  "run_kind": "chat_turn | task_run | graph_run | graph_node | model_call | tool_call",
  "root_run_id": "turn_run_id | task_run_id | graph_run_id",
  "session_id": "",
  "turn_id": "",
  "task_run_id": "",
  "graph_run_id": "",
  "status": "running | completed | blocked | failed | canceled | interrupted",
  "terminal_status": "",
  "terminal_reason": "",
  "started_at": 0.0,
  "ended_at": 0.0,
  "latency_ms": 0.0,
  "refs": {},
  "attributes": {},
  "authority": "runtime.observability.trace_run"
}
```

### 5.2 TraceSpan

```json
{
  "trace_id": "trace:...",
  "span_id": "span:...",
  "parent_span_id": "",
  "name": "single_agent_turn.model_invoke",
  "span_kind": "internal | model | tool | runtime | graph | storage",
  "status": "running | ok | error | blocked | canceled",
  "started_at": 0.0,
  "ended_at": 0.0,
  "latency_ms": 0.0,
  "refs": {
    "runtime_event_ref": "",
    "runtime_invocation_packet_ref": "",
    "action_request_ref": "",
    "action_permit_id": "",
    "tool_invocation_id": "",
    "observation_id": "",
    "prompt_usage_id": ""
  },
  "attributes": {},
  "error": {
    "type": "",
    "message": "",
    "recoverable": false
  },
  "authority": "runtime.observability.trace_span"
}
```

### 5.3 TraceEvent

```json
{
  "trace_id": "trace:...",
  "span_id": "",
  "event_id": "traceevt:...",
  "name": "runtime_branch_decided",
  "created_at": 0.0,
  "refs": {},
  "attributes": {},
  "authority": "runtime.observability.trace_event"
}
```

## 6. 存储布局

新增：

```text
storage/runtime_state/traces/
  runs/
    <safe_trace_id>.jsonl
  snapshots/
    <safe_trace_id>.json
  index/
    trace_index.jsonl
```

保留但降级为导出：

```text
output/local_traces/YYYYMMDD/<trace_id>.json
```

治理策略调整：

- `storage/runtime_state/traces`：RuntimeSystem / diagnostic_trace / ttl_keep_failures
- `output/local_traces`：DiagnosticOutput / exported_trace_snapshot / keep_last_n 或 ttl

注意：

- TraceStore 不是 recovery-critical。
- RuntimeEventLog 仍是恢复关键事实。
- TraceStore 可以被清理，但失败 trace 应保留更久。

## 7. 统一 API 设计

### 7.1 RuntimeObservabilityService

```python
class RuntimeObservabilityService:
    def start_trace(self, *, run_kind: str, refs: dict, attributes: dict) -> TraceContext: ...
    def record_event(self, context: TraceContext, *, name: str, refs: dict = None, attributes: dict = None) -> None: ...
    def start_span(self, context: TraceContext, *, name: str, span_kind: str, refs: dict = None, attributes: dict = None) -> TraceSpanContext: ...
    def finish_span(self, span: TraceSpanContext, *, status: str = "ok", refs: dict = None, attributes: dict = None, error: Exception | dict | None = None) -> None: ...
    def mark_terminal(self, context: TraceContext, *, status: str, reason: str, refs: dict = None, attributes: dict = None) -> None: ...
```

### 7.2 Span context manager

```python
with observability.span(context, "single_agent_turn.model_invoke", span_kind="model", refs={...}):
    ...
```

要求：

- sink 写入失败不得影响 runtime。
- TraceContext 只携带观测 ID 和 refs，不携带业务裁决。
- TraceContext 不允许进入 model-visible prompt。

## 8. 打点分层

### 8.1 EntryPoint

文件：

- `backend/harness/entrypoint/runtime_facade.py`

span/event：

- `entrypoint.history_assembly`
- `entrypoint.input_commit`
- `entrypoint.direct_system_route`
- `entrypoint.runtime_assembly`
- `entrypoint.runtime_branch_decision`
- `entrypoint.memory_context`
- `entrypoint.dispatch`
- `entrypoint.terminal`

### 8.2 Single Agent Turn

文件：

- `backend/harness/loop/single_agent_turn.py`

span/event：

- `single_agent_turn.packet_compile`
- `single_agent_turn.model_invoke`
- `single_agent_turn.action_parse`
- `single_agent_turn.protocol_repair`
- `single_agent_turn.admission`
- `single_agent_turn.action_permit`
- `single_agent_turn.tool_batch`
- `single_agent_turn.final_commit`
- `single_agent_turn.terminal`

### 8.3 Task Executor

文件：

- `backend/harness/loop/task_executor.py`

span/event：

- `task_executor.claim`
- `task_executor.packet_compile`
- `task_executor.model_action_wait`
- `task_executor.model_action_parse`
- `task_executor.protocol_repair_observation`
- `task_executor.admission`
- `task_executor.repeated_admission_guard`
- `task_executor.tool_batch`
- `task_executor.approval_wait`
- `task_executor.completion_gate`
- `task_executor.finish`
- `task_executor.pause`
- `task_executor.block`

### 8.4 Model Gateway

文件：

- `backend/runtime/model_gateway/model_runtime.py`

span/event：

- `model.invoke`
- `model.invoke_with_tools`
- `model.stream`
- `model.retry`
- `model.candidate_switch`
- `model.provider_usage_recorded`
- `model.prompt_cache_reported`

refs：

- `request_id`
- `usage_id`
- `provider`
- `model`
- `prompt_accounting_record_id`

### 8.5 Tool Control Plane

文件：

- `backend/runtime/tool_runtime/tool_control_plane.py`
- `backend/runtime/shared/execution_record.py`

span/event：

- `tool_control.action_permit`
- `tool_control.operation_gate`
- `tool_control.execution_record_create`
- `tool_control.dispatch`
- `tool_control.observation`
- `tool_control.approval_required`
- `tool_control.denied`

refs：

- `action_request_ref`
- `action_permit_id`
- `execution_id`
- `operation_id`
- `tool_invocation_id`
- `observation_id`

### 8.6 Graph Runtime

文件：

- `backend/harness/graph/loop.py`
- `backend/harness/graph/work_order_executor.py`
- `backend/harness/graph_harness.py`

span/event：

- `graph.start`
- `graph.dispatch_ready`
- `graph.node_work_order_materialized`
- `graph.node_execute`
- `graph.node_result_accept`
- `graph.quality_gate`
- `graph.human_gate_wait`
- `graph.checkpoint`
- `graph.terminal`

refs：

- `graph_run_id`
- `node_id`
- `work_order_id`
- `checkpoint_id`
- `node_result_id`

## 9. Monitor 与 Trace 的接入方式

RuntimeObservabilityService 每次收到 event/span 后分发：

```text
TraceStoreSink.write(...)
MonitorLiveSink.update(...)
LocalSnapshotSink.update(...)
LangSmithSink.write(...)        # 可选
OtelSink.write(...)             # 后置
```

Monitor 侧只保留摘要：

```json
{
  "trace_id": "",
  "trace_status": "",
  "trace_url": "",
  "latest_span": "",
  "latest_error": "",
  "model_latency_ms": 0,
  "tool_latency_ms": 0,
  "prompt_usage_ref": ""
}
```

Trace 侧保留完整 span/event refs。

禁止：

- 由 monitor summary 反推 trace。
- 由 trace 层决定 runtime 是否成功。
- 把完整 prompt、完整 tool output 默认写入 trace。
- 把 trace context 写进 model-visible prompt。

## 10. 实施阶段

### Phase 1：Observability 基础设施

目标：

- 新增 Trace schema、TraceStore、ObservabilityService。
- 保留 `start_turn_trace(...)` 作为兼容入口，但内部改为调用 ObservabilityService。
- 写入 `storage/runtime_state/traces`。
- `output/local_traces` 改为 snapshot export。

涉及文件：

- `backend/observability/langsmith_tracing.py`
- `backend/runtime/trace/schema.py`
- `backend/runtime/trace/store.py`
- `backend/runtime/trace/service.py`
- `backend/runtime/trace/context.py`
- `backend/runtime/trace/sinks/local_snapshot.py`
- `backend/harness/runtime/single_agent_host.py`
- `backend/artifact_system/governance.py`

完成标准：

- 本地 trace 可以增量写 span/event。
- sink 失败不影响 runtime。
- 老的 local trace 测试迁移到新 API。

### Phase 2：EntryPoint 与 Monitor 打通

目标：

- `runtime_facade.py` 创建 root trace。
- 正常、失败、blocked、task scheduled、stream close 都明确 mark terminal。
- RuntimeMonitor 展示 trace summary 和 trace link。

涉及文件：

- `backend/harness/entrypoint/runtime_facade.py`
- `backend/harness/runtime/run_monitor/projector.py`
- `backend/harness/runtime/run_monitor/service.py`
- `backend/tests/local_turn_trace_regression.py`
- `backend/tests/runtime_monitor_projection_test.py`

完成标准：

- 每次 chat turn 都有 trace id。
- Monitor 能显示 trace link。
- terminal status 不再由 trace 层猜测。

### Phase 3：单轮模型与工具链路接入

目标：

- 给 single-agent turn 的 packet/model/action/admission/permit/tool/final commit 打 span。
- 给 model runtime 的 invoke/retry/provider usage 打 span。
- 给 tool control plane 的 permit/gate/dispatch/observation 打 span。

涉及文件：

- `backend/harness/loop/single_agent_turn.py`
- `backend/runtime/model_gateway/model_runtime.py`
- `backend/runtime/tool_runtime/tool_control_plane.py`
- `backend/runtime/shared/execution_record.py`
- `backend/tests/harness_runtime_facade_regression.py`
- `backend/tests/model_runtime_regression.py`
- `backend/tests/runtime_tool_control_plane_regression.py`

完成标准：

- 一次带工具的单轮请求能从 trace 看到完整模型和工具链路。
- trace span 包含 action_request_ref、action_permit_id、observation_id、usage_id。

### Phase 4：TaskExecutor 与 GraphLoop 接入

目标：

- 给 task executor 的 repair/admission/tool/completion/pause/block 打 span。
- 给 graph dispatch/node/checkpoint/quality/human gate 打 span。

涉及文件：

- `backend/harness/loop/task_executor.py`
- `backend/harness/graph/loop.py`
- `backend/harness/graph/work_order_executor.py`
- `backend/harness/graph_harness.py`
- `backend/tests/graph_task_runtime_facade_regression.py`
- `backend/tests/graph_harness_api_regression.py`
- `backend/tests/writing_chapter_loop_progress_regression.py`

完成标准：

- graph run 能按 graph_run_id 查到 trace。
- node result、quality gate、checkpoint 均有 trace refs。
- task executor 卡住时能从 trace 定位到最后一个模型动作、准入或工具阶段。

### Phase 5：外部导出与查询

目标：

- 增加 LangSmithSink。
- 增加 OtelSink 或 OTLP export 预留。
- 增加 trace 查询 API。
- 前端可从 monitor 打开 trace summary。

涉及文件：

- `backend/runtime/trace/sinks/langsmith.py`
- `backend/runtime/trace/sinks/otel.py`
- `backend/api/runtime_trace.py`
- `backend/api/routes.py`
- `frontend/src/lib/api.ts`
- `frontend/src/components/chat/*`

完成标准：

- 不启用 LangSmith 时，本地 trace 完整可用。
- 启用 LangSmith 时，外部平台仅作为附加 sink。
- 前端可以查看最近 trace、失败 trace、某 session trace。

## 11. 测试计划

新增测试：

- `backend/tests/runtime_observability_service_regression.py`
- `backend/tests/runtime_trace_store_regression.py`
- `backend/tests/runtime_trace_monitor_projection_regression.py`
- `backend/tests/runtime_trace_single_turn_regression.py`
- `backend/tests/runtime_trace_task_executor_regression.py`
- `backend/tests/runtime_trace_graph_regression.py`

重点断言：

- trace sink 写失败不影响 runtime。
- terminal status 由 runtime 明确写入。
- local snapshot 和 trace store 引用同一个 trace id。
- monitor item 有 trace summary，但不包含完整 trace。
- model span 有 usage refs。
- tool span 有 permit/execution/observation refs。
- graph span 有 checkpoint/node result refs。
- 禁止把完整 prompt/tool output 默认写入 trace。

首批验证命令：

```powershell
python -m pytest backend/tests/local_turn_trace_regression.py -q
python -m pytest backend/tests/runtime_monitor_projection_test.py -q
python -m pytest backend/tests/model_runtime_regression.py -q
python -m pytest backend/tests/runtime_tool_control_plane_regression.py -q
python -m pytest backend/tests/harness_runtime_facade_regression.py -q
```

Graph 接入后追加：

```powershell
python -m pytest backend/tests/graph_task_runtime_facade_regression.py -q
python -m pytest backend/tests/graph_harness_api_regression.py -q
python -m pytest backend/tests/writing_chapter_loop_progress_regression.py -q
```

涉及真实运行链路或前端展示时，必须按项目固定端口启动：

```text
前端：127.0.0.1:3000
后端：127.0.0.1:8003
API Base：http://127.0.0.1:8003/api
```

## 12. 迁移与删除规则

### 12.1 保留项

- `start_turn_trace(...)` 可保留为 public facade，但内部不得继续维护旧 local/langsmith 双类逻辑。
- `output/local_traces` 可保留为人类可读导出目录。

### 12.2 删除或重写项

- 删除 `LocalTurnTrace` 中的 runtime 状态判断逻辑。
- 删除 trace 层 `_NON_ERROR_TERMINAL_STATUSES` 这类业务终态推断。
- 删除只在测试中成立、生产未调用的 terminal 判断假设。
- 重写 `LangSmithTurnTrace` 为 sink，不再与 local trace 分裂成两套主对象。

### 12.3 禁止兼容残留

- 不允许同时保留“旧 local trace truth”和“新 RuntimeTraceStore truth”。
- 不允许 RuntimeMonitor summary 反向生成 trace。
- 不允许 LangSmith 失败导致 runtime 失败。
- 不允许 trace 写入完整 prompt 或完整用户正文，除非显式开启本地调试开关。

## 13. 风险控制

### 13.1 性能风险

风险：高频 span 写入影响模型/工具执行。

控制：

- TraceStore 使用 append-only JSONL。
- 大 payload 外部化或只存 refs。
- 默认记录 metadata summary，不写正文。
- sink 失败吞掉并写内部诊断，不抛给 runtime。

### 13.2 隐私风险

风险：trace 记录用户消息、prompt、tool output。

控制：

- 默认只记录截断 summary 和 refs。
- 完整 prompt/tool output 必须显式开启 `RUNTIME_TRACE_CAPTURE_PAYLOADS=1`。
- 外部 sink 默认不发送完整 prompt/tool output。

### 13.3 权威混乱风险

风险：trace 或 monitor 开始推断 runtime 终态。

控制：

- Runtime loop 显式 mark terminal。
- Trace 只记录传入事实。
- Monitor 只投影，不裁决。

### 13.4 旧测试锁死风险

风险：旧测试只保护 `LocalTurnTrace` 类，而不保护目标行为。

控制：

- 测试迁移到 RuntimeObservabilityService 行为。
- 旧类测试不保留为兼容目标。

## 14. 最终交付标准

完成后应满足：

- 任意 chat turn 都能拿到 trace id。
- RuntimeMonitor 能显示 trace summary 和 trace link。
- 本地 trace store 能按 session、turn、task、graph、status 查询。
- 单轮模型调用、工具调用、任务执行、图节点执行均有 span。
- PromptAccounting、ExecutionStore、RuntimeEventLog、GraphCheckpoint 通过 refs 与 trace 互相定位。
- LangSmith 可选开启，不影响本地 trace 完整性。
- OpenTelemetry export 可后续接入，不需要重写内部 trace schema。

