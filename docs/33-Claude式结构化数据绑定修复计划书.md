# Claude式结构化数据绑定重构计划书

> 目的：针对长场景中“结构化数据任务切换数据集时发生串味、误绑、follow-up 漂移”的问题，重新从架构层而不是补丁层设计修复方案。  
> 本文严格对照：
>
> - [docs/06-上下文管理.md](/D:/AI应用/langchain-agent/docs/06-上下文管理.md)
> - [docs/12-Agent-系统.md](/D:/AI应用/langchain-agent/docs/12-Agent-系统.md)
> - [docs/14-任务系统.md](/D:/AI应用/langchain-agent/docs/14-任务系统.md)
> - [docs/23-Memory系统.md](/D:/AI应用/langchain-agent/docs/23-Memory系统.md)
> - [docs/25-架构模式总结.md](/D:/AI应用/langchain-agent/docs/25-架构模式总结.md)
> - [docs/28-上下文隔离逐文件改造清单.md](/D:/AI应用/langchain-agent/docs/28-上下文隔离逐文件改造清单.md)
> - [docs/32-Claude式记忆召回与主线程去污逐文件执行清单.md](/D:/AI应用/langchain-agent/docs/32-Claude式记忆召回与主线程去污逐文件执行清单.md)
>
> 同时参考本地 Claude Code 源码中三条已经验证过的纪律：
>
> - `utils/forkedAgent.ts`：`explicit override > inherited/shared state > fallback`
> - `services/compact/compact.ts`：恢复只补上下文，不重建当前真相
> - `memdir/memoryTypes.ts`：历史记录与当前观察冲突时，信当前观察

---

## 1. 这份计划书的定位

这不是“调一调 structured resolver 优先级”的临时修补清单，而是一份从零开始的专项重构蓝图。

它要解决的不是单一 case，而是一类结构性问题：

- 当前轮明确说了 `employees.xlsx`，仍可能落到 `inventory.xlsx`
- follow-up 明明是在延续员工表，却被库存表上下文接管
- `active_dataset` 这种恢复态字段被误当成当前事实
- planner、continuation、followup、session/process 多处都在各自猜 dataset，导致谁先命中谁说了算

因此，这份计划书的目标是：

1. 明确谁拥有 dataset binding 的裁决权
2. 明确哪些模块只能消费 binding，不能生产 binding
3. 明确哪些状态层只能恢复，不能覆盖当前轮
4. 给出逐文件改造方案、实施顺序、删除旧逻辑的时机和回归标准

---

## 2. 先给结论：之前容易走偏的地方是什么

之前最容易犯的错误，是把问题看成“当前轮优先级不够高”，于是自然会想到：

- 调 `tool_input_resolver`
- 加 `followup_resolver` 显式判断
- 在 `continuation_resolver` 里补一个 `rebind` 分支

这些改法只能止血，不能治本。  
因为 docs 的原则要求的是：

- **单一真相源**
- **默认隔离，显式共享**
- **任务局部状态拥有自己的边界**
- **session/process 只做恢复，不做当前裁决**

而当前项目中 dataset binding 的真正问题是：

> 没有一个明确、唯一、可追踪的 binding owner。

所以，只要 owner 不建立起来，不管你把哪个 resolver 写得更聪明，系统迟早还会回到多入口竞争、上下文串味的状态。

---

## 3. 当前代码的真实结构问题

下面这些判断不是理念推测，而是基于当前代码现状得出的。

### 3.1 `QueryExecutionPlan` 没有显式 binding model

文件：

- [backend/query/models.py](/D:/AI应用/langchain-agent/backend/query/models.py)

现状：

- `QueryExecutionPlan` 只有：
  - `message`
  - `query_understanding`
  - `tool_input`
  - `execution_kind`
- 没有“这轮结构化数据绑定是谁、为什么、来自哪里”的显式字段

结果：

- binding 只能隐含在 `tool_input["path"]` 或 `query_understanding.semantic_hints` 中
- 任何后续模块都可能继续猜一次

这违反了 docs 的“Main Working Context / Task Local Context 都应有显式状态对象”的原则。

### 3.2 `TaskCoordinator` 自己在派生 binding，而不是接收 binding

文件：

- [backend/tasks/coordinator.py](/D:/AI应用/langchain-agent/backend/tasks/coordinator.py)
- [backend/tasks/context_models.py](/D:/AI应用/langchain-agent/backend/tasks/context_models.py)

现状：

- `TaskCoordinator._build_task_context_ref()` 是从 `query` 文本再做一次 regex 派生
- `TaskBindings.active_dataset` 不是 planner 传进来的，而是 coordinator 自己猜出来的

结果：

- task-local context 本应是 binding 的承载者
- 但现在它不是“真相源”，而是“二次推断结果”

这直接违反 [docs/28-上下文隔离逐文件改造清单.md](/D:/AI应用/langchain-agent/docs/28-上下文隔离逐文件改造清单.md) 的 Task Local Context Layer 设计目标。

### 3.3 `ToolInputResolver` 在决定 binding，而它本不该拥有裁决权

文件：

- [backend/query/tool_input_resolver.py](/D:/AI应用/langchain-agent/backend/query/tool_input_resolver.py)

现状：

- 当 `structured_data_analysis` 没有 `path` 时
- 它会去 history、query 里推导 dataset

结果：

- resolver 既是补全器，又变成事实裁决器
- binding 并不是上游决定好后向下游传递，而是在工具调用前最后一刻才被拼出来

这违反了“显式状态应在上游定型，下游只消费”的原则。

### 3.4 `ContinuationResolver` 和 `FollowupResolver` 也在争 binding

文件：

- [backend/query/continuation_resolver.py](/D:/AI应用/langchain-agent/backend/query/continuation_resolver.py)
- [backend/query/followup_resolver.py](/D:/AI应用/langchain-agent/backend/query/followup_resolver.py)

现状：

- `ContinuationResolver.promote_structured_query()` 会从 history 推 `path`
- `FollowupResolver` 会把之前任务的 `active_dataset` 塞回改写后的消息

结果：

- follow-up 层既在做“引用目标选择”，又在做“binding 构造”
- 于是它会和 planner/tool_input_resolver 竞争

按 docs，follow-up 系统应该优先做 **引用解析**，不该自己重建 task-local binding 真相。

### 3.5 `session_memory` / `process_engine` 的 `active_dataset` 只是恢复态，却被迫承担事实语义

文件：

- [backend/structured_memory/session_memory.py](/D:/AI应用/langchain-agent/backend/structured_memory/session_memory.py)
- [backend/structured_memory/process_engine.py](/D:/AI应用/langchain-agent/backend/structured_memory/process_engine.py)

现状：

- 两边都会从 `file_hints` 里抽 dataset
- 没抽到就继承 `previous_state.context_slots.active_dataset`

结果：

- 它们本来只是恢复索引
- 但因为上游没有稳定 owner，它们就被系统“借用”为当前事实来源

这违反了：

- [docs/06-上下文管理.md](/D:/AI应用/langchain-agent/docs/06-上下文管理.md)：恢复是 restore，不是 current truth
- [docs/23-Memory系统.md](/D:/AI应用/langchain-agent/docs/23-Memory系统.md)：working/session 不是 transcript truth warehouse
- [docs/32-Claude式记忆召回与主线程去污逐文件执行清单.md](/D:/AI应用/langchain-agent/docs/32-Claude式记忆召回与主线程去污逐文件执行清单.md)：恢复态不能抢主路由

---

## 4. 设计原则：这次必须严格遵守什么

### 4.1 单一真相源

同一轮 `structured_data_analysis` 的 dataset binding 只能有一个 owner。

允许存在：

- 显式输入
- 语义推断
- task-local 恢复
- session/process 恢复

但这些只能是 **候选输入**，不能都变成事实源。

### 4.2 默认隔离，显式共享

借鉴 Claude Code 的原则：

- 默认不要让 history、session、task 互相覆盖
- 只有通过明确协议，才允许把 binding 从一个层传到另一个层

落到这里就是：

- 当前轮 binding 不默认继承旧 state
- 只有 follow-up 解析明确指向某个 task 时，才共享那个 task 的 binding

### 4.3 恢复层只恢复，不裁决

`active_dataset`、`warm_context`、`history dataset mention` 都只能用于：

- 当当前轮没有明确 binding 时做兜底

不能用于：

- 覆盖已决出的当前轮 binding

### 4.4 任务层持有局部 binding

结构化数据问题天然是 task-local 的。

因此：

- dataset
- group_by
- top_n
- metric
- analysis_type

这些都应先进入 task-local context，而不是先写进 session/process。

### 4.5 删除旧猜测路径，而不是无限叠加兼容壳

如果一个模块不该再拥有 binding 裁决权，就不应长期保留“兼容性猜测逻辑”。

否则系统会在未来再次回到多入口竞争。

---

## 5. 从零开始的目标架构

这次重构之后，结构化数据 binding 应该沿着下面这条链单向流动：

`user message`
-> `binding candidate extraction`
-> `binding decision`
-> `QueryExecutionPlan.binding`
-> `TaskContextRef.bindings`
-> `tool_input.path`
-> `session/process sync`

其中真正拥有裁决权的只有一个点：

- `binding decision`

建议由 planner 阶段产出，并写入执行计划。

### 5.1 Binding Candidate Layer

职责：

- 从当前轮提取候选 binding 输入

包括：

- 显式文件路径
- 语义 target object
- follow-up 指向的 task binding
- 当前 task 的 active_dataset
- session/process 的恢复值

注意：

- 这里只收集候选，不产出事实

### 5.2 Binding Decision Layer

职责：

- 产出这轮唯一的 dataset binding

规则：

1. 当前轮显式路径
2. 当前轮强语义默认路径
3. follow-up 指向 task 的 binding
4. 当前 session 最近有效 task 的 binding
5. history fallback

输出：

- 一个显式 binding 对象，而不是零散字符串

### 5.3 Task Local Binding Layer

职责：

- 持有本轮/本子任务的 binding 真相

要求：

- `TaskContextRef.bindings.active_dataset` 必须来自 planner 决策结果
- coordinator 不再自己 regex 猜 dataset

### 5.4 Tool Consumption Layer

职责：

- 只把 binding 渲染成 `tool_input.path`

要求：

- `ToolInputResolver` 只做 normalization / validation
- 不再自己从 history 决策 dataset

### 5.5 Session / Process Sync Layer

职责：

- 只同步已完成的 binding 结果，供未来恢复

要求：

- `active_dataset` 是恢复索引
- 它的写入来自 committed task / execution result
- 它不再反向裁决当前轮 binding

---

## 6. 核心数据模型重构

### 6.1 新增显式 binding model

建议新增：

- `backend/query/binding_models.py`

建议模型：

```python
@dataclass(slots=True)
class StructuredDatasetBinding:
    dataset_path: str = ""
    target_object: str = ""
    source: str = ""  # explicit_path / semantic_default / task_ref / session_restore / history_fallback
    confidence: float = 0.0
    derived_from_task_id: str = ""
    explicit_switch: bool = False
```

这不是为了“多一个 dataclass”，而是为了把 dataset binding 从散落在：

- `tool_input["path"]`
- `semantic_hints`
- `active_dataset`
- rewritten message

这些地方里解耦出来，成为可追踪、可测试、可传递的状态对象。

### 6.2 扩展 `QueryExecutionPlan`

文件：

- [backend/query/models.py](/D:/AI应用/langchain-agent/backend/query/models.py)

新增字段建议：

- `structured_binding: StructuredDatasetBinding | None = None`

意义：

- planner 产出的 binding 决策必须进入执行计划
- runtime、task coordinator、tool resolver 都只消费它

### 6.3 扩展 `TaskContextRef`

文件：

- [backend/tasks/context_models.py](/D:/AI应用/langchain-agent/backend/tasks/context_models.py)

当前已有 `TaskBindings.active_dataset`，但来源不对。  
这次不一定要新增字段，但要改 ownership：

- `TaskBindings.active_dataset` 不再由 coordinator 自己 regex 派生
- 改由 planner/QueryExecutionPlan 显式写入

---

## 7. 逐文件重构清单

### 7.1 [backend/understanding/task_understanding.py](/D:/AI应用/langchain-agent/backend/understanding/task_understanding.py)

当前职责：

- 把 query 判成 dataset/pdf/rag/weather 等 route，并给出语义 hints

保留：

- `target_object`
- `analysis_type`
- `semantic_hints`

不再让它承担：

- 最终 dataset binding 决策

具体修改：

1. 增加显式文件候选提取，但只作为 candidate
2. 保持语义 target object 的识别
3. 输出应偏向：
   - `explicit_path_candidate`
   - `semantic_dataset_candidate`
   而不是直接把最终 `path` 写死在这里

退出条件：

- 该模块只负责“识别候选”，不再偷偷承担最终 binding ownership

### 7.2 新增 [backend/query/binding_resolver.py](/D:/AI应用/langchain-agent/backend/query/binding_resolver.py)

这是本轮最核心的新模块。

职责：

- 收集候选
- 决策 dataset binding
- 返回显式 `StructuredDatasetBinding`

输入：

- 当前 message
- `QueryUnderstanding`
- `history`
- follow-up resolution
- 可选 task references

规则：

1. 当前轮显式文件
2. 当前轮强语义默认数据集
3. follow-up 指向 task 的 active_dataset
4. 当前 session 最近有效 structured task 的 active_dataset
5. history fallback

输出：

- `StructuredDatasetBinding`

退出条件：

- dataset binding 决策逻辑在一个模块里闭合，不再散在多个 resolver 中

### 7.3 [backend/query/planner.py](/D:/AI应用/langchain-agent/backend/query/planner.py)

当前问题：

- planner 产出 plan，但没有 owning binding

具体修改：

1. 注入 `binding_resolver`
2. 在 `_build_execution()` 中：
   - 先得到 `QueryUnderstanding`
   - 再解析 `FollowupResolution`
   - 再调用 `binding_resolver`
3. 将 binding 写入：
   - `QueryExecutionPlan.structured_binding`
   - `tool_input["path"]` 仅作为投影结果

退出条件：

- planner 成为 binding 决策 owner

### 7.4 [backend/query/tool_input_resolver.py](/D:/AI应用/langchain-agent/backend/query/tool_input_resolver.py)

当前问题：

- 它在做 binding 决策

具体修改：

1. 降级为 normalizer / validator
2. 如果 execution 已有 `structured_binding.dataset_path`：
   - 只做规范化和相对路径转换
3. 仅在兼容期内保留 fallback
4. 兼容期结束后，删除 `resolve_dataset_path_from_history(...)` 主路由

退出条件：

- 这个模块不再拥有事实裁决权

### 7.5 [backend/tasks/coordinator.py](/D:/AI应用/langchain-agent/backend/tasks/coordinator.py)

当前问题：

- `_derive_task_bindings()` 通过 regex 再猜一次 dataset

具体修改：

1. `_build_task_context_ref()` 改成接收 execution 里的 binding
2. `TaskBindings.active_dataset` 直接来自 `QueryExecutionPlan.structured_binding`
3. `_derive_task_bindings()` 降级或删除 dataset 猜测职责

退出条件：

- task-local context 真正承接上游 binding，而不是自己二次推断

### 7.6 [backend/query/followup_resolver.py](/D:/AI应用/langchain-agent/backend/query/followup_resolver.py)

当前问题：

- 既做引用解析，又隐式帮助重建 binding

具体修改：

1. 保留：
   - ordinal task reference
   - binding task reference
2. 不再通过重写消息来构造 binding 真相
3. 输出只表达：
   - 指向哪个 task
   - 指向哪个 binding key

退出条件：

- follow-up resolver 只做 reference resolution，不再做 binding construction

### 7.7 [backend/query/continuation_resolver.py](/D:/AI应用/langchain-agent/backend/query/continuation_resolver.py)

当前问题：

- `promote_structured_query()` 会从 history 直接生成 `path`

具体修改：

1. 把职责收窄为 route promotion
2. 对 structured follow-up：
   - 只负责判断“是不是 structured continuation”
   - 不再直接写 `path`
3. dataset binding 改由 `binding_resolver` 统一决策

退出条件：

- continuation resolver 不再和 planner 竞争 binding ownership

### 7.8 [backend/structured_memory/session_memory.py](/D:/AI应用/langchain-agent/backend/structured_memory/session_memory.py)

当前问题：

- projection 层会自己从 `file_hints` 和 previous state 推导 `active_dataset`

具体修改：

1. 将 `active_dataset` 的来源改成：
   - 已提交 execution/task 的 binding 投影
2. 只在没有 committed binding 时，才允许历史恢复兜底
3. projection 中不再通过 `active_goal` 文本去猜当前 dataset 真相

退出条件：

- session memory 只记录 committed binding，不再参与当前轮裁决

### 7.9 [backend/structured_memory/process_engine.py](/D:/AI应用/langchain-agent/backend/structured_memory/process_engine.py)

当前问题：

- `active_dataset` 的继承逻辑仍然把恢复态当作事实候选

具体修改：

1. `ContextSlots.active_dataset` 改成 committed restore slot
2. task switch 时只做清理/同步，不负责猜测新的当前 binding
3. `file_hints` 仅作为观测线索，不直接生成当前真相

退出条件：

- process engine 不再是 dataset binding 的事实生产者

### 7.10 [backend/query/runtime.py](/D:/AI应用/langchain-agent/backend/query/runtime.py)

当前问题：

- direct tool execution 仍然从 `tool_input` 消费，而 `tool_input` 不是稳定 owner

具体修改：

1. runtime 读取 execution 的显式 binding
2. task summary / main context / session sync 统一引用同一个 binding 结果
3. compound path 中，每个 subtask 的 binding 保持独立

退出条件：

- runtime 不再依赖分散的字符串拼装状态判断当前数据集

---

## 8. 删除与保留策略

这轮不能只讲“新增什么”，还要讲清“删什么”。

### 8.1 保留

- `TaskBindings`
- `TaskContextRef`
- `QueryExecutionPlan`
- `active_dataset` 作为恢复索引字段

这些基础结构方向是对的，只是 ownership 没立起来。

### 8.2 要降级

- `tool_input_resolver` 的 history-driven binding 决策
- `continuation_resolver` 的 path 生成
- `followup_resolver` 通过 rewritten message 携带 binding 的隐式模式

### 8.3 最终要删除

在新链路稳定后，以下逻辑应清理：

- coordinator 中针对 dataset 的 regex 推断主路径
- session/process 中基于文本 file hint 的当前事实推断
- 多处各自维护的 “explicit dataset heuristics”

否则后面维护时又会重新形成多入口竞争。

---

## 9. 实施阶段

### Phase 0：护栏与观测

目标：

- 先把 binding 决策和传播过程观测出来

修改：

- 为 execution / task / tool_start 增加 binding trace
- 增加 regression：
  - 明确断言 binding source
  - 明确断言 owner

### Phase 1：建立显式 binding model

目标：

- 新增 `StructuredDatasetBinding`
- 扩展 `QueryExecutionPlan`

退出条件：

- 运行时第一次拥有显式 binding 对象

### Phase 2：planner 接管 binding ownership

目标：

- `binding_resolver` 落地
- planner 成为 binding owner

退出条件：

- 本轮 binding 不再由 resolver/tool/session 临时拼装

### Phase 3：task 层承接 binding

目标：

- `TaskContextRef.bindings.active_dataset` 来自 execution binding

退出条件：

- task-local context 成为 binding 的下游承载者

### Phase 4：resolver 去裁决化

目标：

- `tool_input_resolver`
- `continuation_resolver`
- `followup_resolver`

都收窄为消费层/引用层

退出条件：

- 多入口竞争消失

### Phase 5：session/process 降级为恢复层

目标：

- `active_dataset` 只同步 committed binding

退出条件：

- session/process 不再影响当前轮 dataset 决策

### Phase 6：清理兼容层

目标：

- 删除旧 heuristic 主路径

退出条件：

- binding 主链路清晰、唯一、可维护

---

## 10. 回归测试方案

### 10.1 定向结构测试

文件建议：

- `backend/tests/structured_dataset_binding_regression.py`
- `backend/tests/query_planner_regression.py`
- `backend/tests/followup_resolution_regression.py`
- `backend/tests/task_coordinator_regression.py`

必须覆盖：

1. 当前轮显式 `employees.xlsx` 必须压过旧 `inventory.xlsx`
2. 当前轮强语义 `薪资前五` 在无显式文件时默认落到 `employees.xlsx`
3. follow-up “按部门汇总这些高薪员工” 必须引用员工 task binding
4. “回到 inventory.xlsx” 必须触发新的 binding，而不是沿用员工 task
5. `TaskContextRef.bindings.active_dataset` 必须等于 planner 决策结果

### 10.2 恢复层测试

文件建议：

- `backend/tests/session_memory_regression.py`

必须覆盖：

1. committed binding 会同步到 `active_dataset`
2. 当前轮已有 explicit binding 时，旧 `active_dataset` 不得覆盖
3. topic switch / external tool 后仍能通过 task binding 正确回到之前的数据任务

### 10.3 长场景测试

文件：

- `backend/tests/system_eval/long_scenarios.py`

重点验证：

- `inventory -> employees -> inventory`
- `structured -> realtime -> structured`
- compound query 中 dataset 子任务和其他子任务互不污染

---

## 11. 退出标准

本专项可以算完成，必须同时满足下面 6 条：

1. dataset binding 在代码中有唯一 owner
2. planner 产出显式 binding 对象
3. task context 接收 binding，而不是自己再猜
4. session/process 只同步 committed binding，不反向裁决当前轮
5. follow-up / continuation / tool resolver 不再多处竞争 binding 真相
6. 长场景中的数据集切换和恢复稳定通过

---

## 12. 这次明确不做什么

- 不引入 LangGraph / AutoGen / Letta 之类新框架
- 不把 runtime 全量改写成 agent graph
- 不用“补 prompt”替代边界重构
- 不让 session/process 继续偷偷承担主路由语义
- 不保留长期并行存在的多套 binding 主路径

---

## 13. 下一步执行建议

执行顺序建议严格如下：

1. 先做 Phase 0 和 Phase 1
2. 再做 Phase 2 和 Phase 3
3. 然后做 Phase 4
4. 最后做 Phase 5 和 Phase 6

也就是：

- 先建立 binding model
- 再建立 planner ownership
- 再把 task 层接上
- 然后削掉 resolver 的裁决权
- 最后把 session/process 降级成恢复层

这才是符合 docs 原则的推进顺序。
