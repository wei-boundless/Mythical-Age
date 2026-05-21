# 通用图编辑器 Step 机制重思考与运行语义重构计划

日期：2026-05-22

## 1. 纠偏结论

这次设计对象是通用图编辑器，不是写作任务图。

写作任务只能作为模板和回归场景，不能反向污染底层协议。底层协议只能表达通用图运行能力：

- 节点职责。
- 边职责。
- 资源读写。
- 产物生命周期。
- 校验与发布。
- 并发与汇合。
- 失败、重试、隔离、失效、恢复。
- 运行 step/checkpoint。

因此，底层不允许出现世界观、人设、章节、记忆提交这类领域词。领域模板可以把通用语义显示成行业语言，但不能修改底层语义。

## 2. LangGraph Step 的真实作用

参考 LangGraph 官方文档：

- Pregel runtime 的核心是 actor/channel/message passing 模型。
- checkpoint 会在每个 super-step 边界保存状态。
- `StateSnapshot` 包含 `values`、`next`、`metadata.step`、`tasks` 等字段。
- super-step 是一次运行 tick：本轮被调度的节点执行，状态更新在下一轮可见。

这说明 step 的价值在运行层：

- 记录一次 dispatch wave。
- 形成 checkpoint 边界。
- 支持恢复、time travel、interrupt 后 resume。
- 表示本轮有哪些 task 被派发。

step 不适合作为图编辑器的业务结构：

- 同一张图在不同并发限制下会产生不同 step。
- 同一张图在失败恢复后会产生不同 step。
- step 是运行结果，不是用户建模时应该画出来的结构。
- 如果把 step 当编辑器层级，资源调度策略会污染图语义。

## 3. 现有系统的问题

当前系统有几个结构性问题：

### 3.1 `sequence_index` 被当成运行语义

它现在确实被 scheduler 消费，会产生 `sequence_wait`。但这不是通用图语义，只是 legacy timing gate。

问题在于：

- 它把展示顺序和阻塞关系混在一起。
- 它会把无依赖节点错误串行化。
- 它让用户误以为编号就是因果关系。

### 3.2 `timeline_group_id` 像并发组，但不是真并发组

它被保留到 RuntimeSpec，但运行时没有按它同步启动或汇合。

所以它只能是 legacy/display 字段，不能作为通用并发权威。

### 3.3 `timeline_policy` 和 `phase_definitions` 不是强调度协议

编译器已经把 `timeline_policy` 标为 unsupported，`phase_definitions` 标为 partial。

这类字段可以辅助展示生命周期，但不能被编辑器展示成已经生效的调度能力。

### 3.4 当前缺少通用运行语义权威

系统有 scheduler support report，但它只回答“当前字段是否被 scheduler 消费”。

它不能回答：

- 节点在通用运行语义里是什么职责。
- 边是启动依赖、数据输入、校验输入，还是发布输入。
- step 是不是用户可编辑概念。
- legacy 字段是不是在污染图语义。
- 后续切换调度时应该消费哪个权威对象。

## 4. 目标设计

新增一个通用影子权威：

```text
TaskGraphRuntimeSemanticsManifest
```

它不改变当前运行行为，但把通用语义编译出来，作为后续编辑器和调度重构的唯一依据。

### 4.1 节点语义

通用节点职责：

```text
producer
validator
approver
publisher
aggregator
router
resource
monitor
```

这些是通用词，不属于任何领域。

### 4.2 边语义

通用边职责：

```text
activation
data_input
validation_input
approval_input
publish_input
resource_read
resource_write
reference
retry
failure_route
```

边职责决定 ready、可见性、失败传播和失效范围。不是靠 step 或 sequence 推断。

### 4.3 产物生命周期

通用产物状态：

```text
produced
pending_validation
validated
published
rejected
superseded
quarantined
```

领域模板可以把它显示成候选、审核通过、提交等词，但底层只使用通用状态。

### 4.4 Step 的位置

step 只保留在运行层：

```text
dispatch_wave
checkpoint_boundary
resume_boundary
debug_snapshot
```

编辑器不能让用户把 step 当节点、阶段、子图或并发组来画。

### 4.5 时序的通用职责

时序保留，但降级为生命周期坐标和账本：

- phase。
- iteration。
- attempt。
- checkpoint。
- lifecycle event。
- invalidation event。

时序不再是默认阻塞链。

## 5. 重构计划

### 5.1 第一轮：通用 Runtime Semantics Manifest

新增：

- `backend/task_system/runtime_semantics/__init__.py`
- `backend/task_system/runtime_semantics/models.py`
- `backend/task_system/runtime_semantics/compiler.py`

接入：

- `backend/task_system/compiler/coordination_graph_compiler.py`
- `backend/task_system/graphs/task_graph_standard_models.py`
- `frontend/src/lib/api.ts`
- `frontend/src/components/workspace/views/task-system/TaskGraphExecutionPackagePanel.tsx`

完成后：

- RuntimeSpec diagnostics 暴露 `runtime_semantics`。
- 标准视图 timeline 暴露 `runtime_semantics`。
- 前端执行包能看到通用语义摘要。
- legacy 字段被诊断为 legacy/noise，而不是当成新语义。

### 5.2 第二轮：编辑器按通用语义展示

后续编辑器主界面应该展示：

- node semantic role。
- edge semantic role。
- artifact lifecycle。
- runtime step 只出现在运行监控页。

不再把每个节点包装成伪 step。

### 5.3 第三轮：调度切换

等 Manifest 稳定后，再把 scheduler 从 legacy phase/sequence gate 切到通用 ready set：

- 显式边决定启动依赖。
- 边职责决定输入状态要求。
- publish/lifecycle 决定下游可见性。
- dispatch wave 只记录运行派发，不进入编辑器语义。

## 6. 禁止事项

1. 禁止把领域任务边界写入底层通用协议。
2. 禁止把 step 做成编辑器可画的主概念。
3. 禁止继续把 `sequence_index` 包装成通用因果关系。
4. 禁止把 `timeline_group_id` 包装成并发组。
5. 禁止前端展示未被后端消费的强能力。
6. 禁止为了某个模板写 runtime 特判。
7. 禁止通过 prompt 修补运行边界问题。

## 7. 本轮验收标准

本轮重构完成后必须做到：

- 有通用 Runtime Semantics Manifest。
- Manifest 不含领域概念。
- Manifest 明确 step 只是 runtime dispatch/checkpoint。
- Manifest 能识别节点职责与边职责。
- Manifest 能指出 `sequence_index`、`timeline_group_id`、`timeline_policy` 这类 legacy/noise 风险。
- RuntimeSpec 和标准视图都能读取 Manifest。
- 新增通用测试覆盖 Manifest，不用写作任务做唯一证明。

