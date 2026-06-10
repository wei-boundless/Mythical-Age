# Graph Runtime Interruption Recovery Boundary Plan

## 背景

图任务运行时不能依赖“不要在节点执行中重启后端”这种人工纪律。后端重启、进程崩溃、模型连接中断、后台任务丢失都必须是图任务系统的正式边界条件。

核心原则：

```text
恢复的是 GraphNodeWorkOrder，不是半截模型响应。
推进图的是已接受的 NodeResultEnvelope，不是 running 状态、sandbox 文件或 synthetic receipt。
```

## 当前已具备的基础

- `GraphLoopState.active_work_orders` 持久化了当前正在执行的节点 work order。
- `GraphNodeWorkOrder` 已持久化到 runtime object store，monitor 会返回可恢复的 active work order。
- 图节点 `TaskRun` 的 ID 由 `work_order_id` 派生，同一个 active work order 重跑时不会创建第二个节点任务。
- `GraphResumeService` 能在 resume 时把 stale graph node executor TaskRun 改回 `waiting_executor`。
- `GraphRunBackgroundSupervisor.submit_until_idle()` 会先 resume，再根据 active work order 重新提交后台执行。
- `GraphLoop.accept_node_result()` 校验 `NodeResultEnvelope.work_order_id` 必须等于当前 active work order，能阻止旧结果推进新节点。

这些是正确方向，但还不足以声明“运行中断一定可恢复”。

## 必须明确的运行边界

### 1. Dispatch Boundary

图把 ready node 编译为 `GraphNodeWorkOrder` 并写入 checkpoint 后，节点才算进入可恢复执行态。

可恢复承诺：

- 后端重启后可以从 active work order 重新执行。
- 不允许因为 background task 丢失而丢失节点。

### 2. Executor Lease Boundary

后台任务开始执行 work order 时，必须取得显式执行租约。

租约记录最少包含：

```text
graph_run_id
work_order_id
node_id
node_task_run_id
owner_instance_id
attempt
status
claimed_at
heartbeat_at
expires_at
```

可恢复承诺：

- 当前进程仍持有租约时，不重复提交同一个 work order。
- 进程重启后，旧 `owner_instance_id` 的租约过期，work order 可重新执行。
- 租约不是图推进事实；它只是执行协调。

### 3. Model Call Boundary

模型调用本身不是可恢复事务。后端中断时，半截模型响应不能作为节点结果使用。

可恢复承诺：

- 中断发生在模型调用期间，只能重跑同一个 work order。
- 已记录的 session transcript 可作为上下文，但不能替代 `NodeResultEnvelope`。
- 可能消耗重复 provider 成本，但不能产生重复图推进。

### 4. Tool / Sandbox Boundary

工具调用和 sandbox cache 不是图推进事实。

可恢复承诺：

- 有工具 receipt 的副作用可以用于后续审计。
- 没有被 `NodeResultEnvelope` 引用和接受的 sandbox 文件不能推进图。
- `storage/runtime_cache` 可删除、可重建；不能作为恢复事实。

### 5. Node Result Commit Boundary

只有 `NodeResultEnvelope` 被 `GraphLoop.accept_node_result()` 接受后，节点才完成。

可恢复承诺：

- result accepted 后重启，图必须从下一节点继续。
- result 未 accepted 前重启，图必须停在同一个 active work order。
- result store 和 checkpoint 之间发生中断时，恢复逻辑必须能发现同一 `work_order_id` 的真实 result，并修复 checkpoint；不能重跑已完成节点。

### 6. Edge Propagation Boundary

边传播只读取已接受的 node result。

可恢复承诺：

- 不允许由 running TaskRun、sandbox 文件、session 消息直接触发边传播。
- 不允许 synthetic progress receipt 代替真实上游产物。

### 7. Human Gate Boundary

人工审核/退稿是正式图控制输入，不是外部临时状态。

可恢复承诺：

- human gate 决策必须持久化为 graph control event / result。
- 重启后人工 gate 状态仍可见、可继续。

## 当前缺口

1. 缺少一等 `GraphWorkOrderLease`，现在只靠后台 task name 和 TaskRun executor_status 推断是否正在跑。
2. runtime start recovery 当前跳过 `origin_kind=graph_node_assigned` 的 TaskRun，图节点恢复主要依赖后续 resume/submit 调用，不是启动时自动完成。
3. background work order 失败只写 `graph_work_order_background_failed` 事件，没有统一把 active work order 标成 recoverable lease expired。
4. 缺少 `work_order_id -> accepted result_ref` 的显式索引。若 result 已写入 object store 但 checkpoint 未完成，恢复逻辑不够强。
5. 同一个 work order 的 completed TaskRun 没有在 graph work order executor 入口显式短路为“从 durable TaskRun materialize result”，容易重跑已经完成但未推进的节点。
6. monitor 的 stale 修复还没有成为统一 recovery service，容易出现 projection 与事实状态不一致。
7. 启动恢复没有覆盖非终态 GraphRun 的 active work order 自动重提交流程。

## 已落地修正记录

### 2026-06-10：质量门返修后台续跑

问题：

- `quality_gate_failed` 会生成 recoverable blocked result。
- `GraphLoop` 会把同一节点放回 ready/blocked recovery 状态。
- 旧 `GraphRunBackgroundSupervisor` 在一个 work order 执行完成后只检查 active work order；当质量门返修处于 ready/blocked、尚未 dispatch 成 active work order 时，后台链路会停止，必须外部再调用一次 submit/resume。

修正：

- `GraphRunBackgroundSupervisor._execute_order_and_schedule_next()` 现在会在 state 存在 active work order、ready node、blocked/failed recovery node 时继续 submit。
- 新增回归测试覆盖 recoverable blocked -> ready repair -> background resubmit。

剩余：

- 这只是质量门返修续跑修复，不替代 WorkOrder Lease、runtime start recovery 和 result idempotency。

## 目标权威链

```text
GraphRun durable fact
-> GraphLoopCheckpoint
-> GraphNodeWorkOrder
-> GraphWorkOrderLease
-> GraphNode TaskRun / AgentRun
-> NodeResultEnvelope
-> GraphLoop.accept_node_result
-> Edge propagation
-> Formal artifact / memory commit
```

禁止链路：

```text
running TaskRun
-> session message / sandbox file / synthetic receipt
-> graph advance
```

## 目标恢复算法

新增 `GraphRunRecoveryService.recover_runtime_start()`：

1. 扫描非终态 GraphRun。
2. 加载 latest checkpoint 和 active work orders。
3. 对每个 active work order：
   - 如果已有 accepted result for `work_order_id`，修复 checkpoint 并清理 active lease。
   - 如果 node TaskRun completed 但未生成 NodeResult，用 durable TaskRun 输出重新 materialize `NodeResultEnvelope`，再走 `accept_node_result()`。
   - 如果 node TaskRun running/scheduled 且 owner runtime 已不存在，标记为 `waiting_executor`，lease 置为 expired。
   - 如果 node TaskRun failed/blocked 且 recoverable，保留 active work order 并等待重跑。
   - 如果没有 node TaskRun，保留 active work order 并重新提交。
4. 对仍 active 的 work order 调用 background supervisor 重新提交。
5. 写 recovery receipt，供 monitor 和前端解释。

注意：

- “materialize NodeResultEnvelope”只能从 durable TaskRun final answer、artifact refs、tool receipts、memory receipts 中提取，不允许凭空生成业务结果。
- progress receipt router 仍只能基于真实 inbound artifact evidence 生成确定性 receipt。
- recovery service 只修复事实/投影关系，不改写图拓扑和节点 prompt。

## 数据结构调整

新增 runtime object kind：

```text
graph_work_order_lease
graph_recovery_receipt
```

扩展 graph result index：

```text
accepted_result_by_work_order_id: {
  "<work_order_id>": {
    "node_id": "...",
    "result_ref": "...",
    "accepted_at": 0.0,
    "checkpoint_id": "..."
  }
}
```

如果不想先改 checkpoint schema，可先作为 runtime object / projection 存储，但必须由 `GraphLoop.accept_node_result()` 写入，不能由 monitor 推断。

## 实施阶段

### 第一阶段：定义边界与测试夹具

- 新增 graph interruption recovery 测试图。
- 覆盖 active work order、completed TaskRun、stale running TaskRun、background failure 四类场景。
- 不改写作图拓扑。

### 第二阶段：WorkOrder Lease

- 新增 lease store / helper。
- background supervisor 执行前 claim，完成后 release。
- 重复 submit 同一 work order 时检查 lease owner/expiry。

### 第三阶段：Result Idempotency

- `GraphLoop.accept_node_result()` 写 `work_order_id -> result_ref` 索引。
- `GraphNodeWorkOrderExecutor` 执行前检查同 work order 是否已有 accepted result。
- 如果 TaskRun completed 但 result 未 accepted，重新 materialize result 并 accept，不重跑模型。

### 第四阶段：Runtime Start Recovery

- `ApplicationRuntimeFacade` 初始化后调用 graph recovery service。
- 对非终态 GraphRun 的 active work order 自动恢复和重新提交。
- 恢复结果写 `graph_recovery_receipt`。

### 第五阶段：Monitor Repair

- monitor 遇到 stale active view 时调用 recovery read model。
- projection stale 只触发 projection rebuild，不合成 node result。

## 验证计划

必须新增/更新测试：

```text
python -m pytest backend/tests/graph_harness_interruption_recovery_regression.py -q
python -m pytest backend/tests/graph_harness_api_regression.py::test_graph_run_monitor_returns_recoverable_active_work_orders -q
python -m pytest backend/tests/graph_harness_api_regression.py::test_graph_harness_background_submit_executes_work_order_and_advances_loop -q
python -m pytest backend/tests/harness_task_executor_control_regression.py -q
```

必须实测：

- 固定后端 `127.0.0.1:8003` 重启。
- 运行中断 active graph node 后，自动恢复同一 work order。
- 已 accepted result 的节点不重复执行。
- 已 completed TaskRun 但未 accept 的节点能从 durable 输出恢复推进。
- 写作图任务重启后继续向后推进，不重复已完成章节。

## 成熟度判定

完成后，我们才能声明：

```text
图任务允许运行中断。
中断最多导致当前 work order 重跑，不会丢图、不会错推、不会重复接受节点结果。
```

在这之前，只能说：

```text
当前系统已有 active work order resume 基础，但运行中断恢复边界还没有完整产品化。
```
