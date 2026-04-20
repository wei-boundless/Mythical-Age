# Claude式结构化数据绑定修复计划书

> 目的：把长场景中“结构化数据任务显式切换数据集失败”的问题，从零散修补改成一份可执行的专项计划。  
> 本计划书直接承接 [32-Claude式记忆召回与主线程去污逐文件执行清单.md](/D:/AI应用/langchain-agent/docs/32-Claude式记忆召回与主线程去污逐文件执行清单.md) 的第一类残留问题，但不再泛化讨论 memory 全链路，而是聚焦 `structured_data_analysis` 的绑定、延续、恢复与去污边界。

---

## 1. 问题定义

当前长场景中的典型错误不是工具能力不足，而是**绑定优先级错位**：

- 用户显式说了 `employees.xlsx`
- 当前轮语义也明显指向员工/薪资
- 但运行时仍然沿用了历史中的 `inventory.xlsx`

这会产生三类错误：

1. 显式切换数据集失败  
   例：`现在换成 employees.xlsx，找出薪资前五的人。` 仍落到 `inventory.xlsx`

2. follow-up 延续对象错误  
   例：切到 `employees.xlsx` 后再问 `按部门汇总这些高薪员工`，结果仍按库存表处理

3. session/process state 抢当前轮绑定  
   例：`active_dataset=inventory.xlsx` 被当成当前真相，而不是弱恢复线索

这不是“模型随机漂移”，而是当前实现违背了上下文隔离的边界纪律。

---

## 2. 采用的 Claude Code 准则

本计划采用的不是 Claude Code 的完整框架，而是它已经验证过的几条边界原则。

### 2.1 显式覆盖优先

来源：

- `claude-code-nb-main/utils/forkedAgent.ts`

可直接抽象成：

- `explicit override > inherited/shared state > fallback`

落到本项目中的含义是：

- 当前轮显式文件绑定
- 当前轮强语义绑定
- task/session 恢复绑定
- history fallback

必须严格按这个顺序决策。

### 2.2 恢复只补上下文，不重建当前真相

来源：

- `claude-code-nb-main/services/compact/compact.ts`

Claude Code 的 post-compact restore 是“恢复最近必要附件”，不是“把旧状态重新扶正”。  
落到本项目中的含义是：

- `active_dataset`
- `recent tool result`
- `history dataset mention`

都只能做恢复线索，不能压过当前轮输入。

### 2.3 旧状态冲突时信当前观察

来源：

- `claude-code-nb-main/memdir/memoryTypes.ts`

Claude Code 对 memory drift 的要求是：

- recalled context 与当前观察冲突时，信当前观察

落到本项目中：

- 历史里最近一次数据集是 `inventory.xlsx`
- 当前轮显式说 `employees.xlsx`

则必须信当前轮，并把旧 dataset 降级为 background hint。

---

## 3. 本计划的正式目标

把结构化数据任务的绑定链路改成下面这条单向优先级：

1. 当前轮显式文件绑定
2. 当前轮语义绑定
3. 当前活跃 task binding
4. session/process 恢复绑定
5. history fallback

并同时满足以下约束：

- history 不能覆盖当前轮显式输入
- follow-up 只能在“当前轮没有重绑定”时沿用旧 dataset
- session/process state 只能恢复，不能裁决
- tool input 中的 `path` 一旦决出，就成为本轮唯一真相源

---

## 4. 当前链路的真实问题

### 4.1 `tool_input_resolver` 优先级反了

文件：

- [backend/query/tool_input_resolver.py](/D:/AI应用/langchain-agent/backend/query/tool_input_resolver.py)

当前行为：

1. `tool_input.path` 缺失
2. 先 `resolve_dataset_path_from_history(...)`
3. 再 `resolve_dataset_path(..., query)`

这意味着历史绑定会先抢占当前轮语义。

### 4.2 `task_understanding` 能识别语义，但没把绑定做硬

文件：

- [backend/understanding/task_understanding.py](/D:/AI应用/langchain-agent/backend/understanding/task_understanding.py)

当前状态：

- 已能识别 `employee / inventory / sales / customer`
- 已能识别 `salary / warehouse / shortage / department`
- 但没有把显式文件路径和强语义绑定升级成稳定 `tool_input.path`

### 4.3 `continuation_resolver` 把“继续问”和“重绑定”混在一起

文件：

- [backend/query/continuation_resolver.py](/D:/AI应用/langchain-agent/backend/query/continuation_resolver.py)

当前问题：

- `understanding.route == "tool"` 时过早返回
- 导致显式 `切到 employees.xlsx` 这种消息即使已经被判为 tool，也失去了 rebind 修复机会

### 4.4 session/process state 继承太宽

文件：

- [backend/structured_memory/session_memory.py](/D:/AI应用/langchain-agent/backend/structured_memory/session_memory.py)
- [backend/structured_memory/process_engine.py](/D:/AI应用/langchain-agent/backend/structured_memory/process_engine.py)

当前问题：

- 当前轮没有抽出文件时，会直接继承 `previous_state.context_slots.active_dataset`
- 这本来是恢复机制，但在绑定层级不清时，会被误用成“当前真相”

---

## 5. 目标架构

### 5.1 绑定决策层

职责：

- 只决定这轮 `structured_data_analysis` 用哪个 dataset

唯一输出：

- `tool_input["path"]`

输入优先级：

1. 当前轮显式路径
2. 当前轮语义默认路径
3. 当前任务上下文中的 `active_dataset`
4. history 中最近的有效 dataset

### 5.2 延续判定层

职责：

- 判断当前消息是“继续上一张表”，还是“切到新表”

规则：

- 显式文件名、`切到`、`换成`、`再切回`、`回到 ...xlsx` 一律视为重绑定
- 只有未出现显式重绑定信号时，才允许 follow-up 延续

### 5.3 恢复层

职责：

- 保存 `active_dataset` 供后续无显式绑定时恢复

限制：

- 恢复层绝不反向覆盖已决出的 `tool_input.path`

---

## 6. 逐文件改造清单

### 6.1 [backend/query/tool_input_resolver.py](/D:/AI应用/langchain-agent/backend/query/tool_input_resolver.py)

修改目标：

- 把 dataset 解析顺序改成 Claude 式 `explicit > current-turn semantics > restored state`

具体修改：

1. 保持 `tool_input.path` 为第一优先级
2. 对 `structured_data_analysis` 改成：
   - 先 `resolve_dataset_path(..., query)`
   - 失败后再 `resolve_dataset_path_from_history(...)`
3. 一旦解析成功，立即写回 `tool_input["path"]`
4. 不允许出现：
   - `semantic_hints.target_object=employee`
   - 但 `path=inventory.xlsx`

退出条件：

- 当前轮显式 `employees.xlsx` 永远不会再被旧 `inventory.xlsx` 覆盖

### 6.2 [backend/understanding/task_understanding.py](/D:/AI应用/langchain-agent/backend/understanding/task_understanding.py)

修改目标：

- 把“可识别的语义”升级成“可消费的绑定信号”

具体修改：

1. 增加显式文件路径抽取：
   - `.xlsx`
   - `.csv`
   - `.xls`
   - `.json`
2. 若用户消息中存在显式文件，直接写入 `parameters["path"]`
3. 保留 `target_object`、`semantic_hints`
4. 给强语义场景增加稳定信号：
   - `employee + salary/department/title`
   - `inventory + shortage/warehouse/reorder`

退出条件：

- understanding 阶段就能把“显式文件”和“强语义目标”可靠地下传

### 6.3 [backend/understanding/query_understanding.py](/D:/AI应用/langchain-agent/backend/understanding/query_understanding.py)

修改目标：

- 确保上游识别到的 binding 不在 routing 阶段丢失

具体修改：

1. 保真传递 `TaskUnderstanding.parameters`
2. 若已有 `tool_input.path`，后续 skill/tool routing 不得清空
3. 保证 `tool_input` 成为 planner 的 binding 真相入口

退出条件：

- `task_understanding` 产出的 `path` 和强语义参数在 `QueryUnderstanding` 中完整保留

### 6.4 [backend/query/continuation_resolver.py](/D:/AI应用/langchain-agent/backend/query/continuation_resolver.py)

修改目标：

- 把“继续上一张表”与“重绑定新表”明确分开

具体修改：

1. `promote_structured_query()` 不再对所有 `route == "tool"` 直接 early return
2. 增加“显式重绑定检测”：
   - 文件名
   - `切到`
   - `换成`
   - `回到`
   - `再切回`
3. 若检测到重绑定：
   - 允许修正/补全 `tool_input.path`
   - 禁止直接沿用 history dataset
4. 只有纯 follow-up 场景才调用 `resolve_dataset_path_from_history(...)`

退出条件：

- `继续问` 和 `换数据集` 两类消息的路由与绑定不再混淆

### 6.5 [backend/query/followup_resolver.py](/D:/AI应用/langchain-agent/backend/query/followup_resolver.py)

修改目标：

- 显式切换指令不再被误判为普通延续

具体修改：

1. 扩展 `_looks_explicit()`：
   - 任意结构化数据文件名
   - `切到`
   - `换成`
   - `回到 ...xlsx`
   - `再切回`
2. 只对真正的省略式 follow-up 做重写
3. 对显式切换消息直接返回空解析结果，交给当前轮 planner 处理

退出条件：

- follow-up resolver 不再拦截用户的显式重绑定语句

### 6.6 [backend/structured_memory/session_memory.py](/D:/AI应用/langchain-agent/backend/structured_memory/session_memory.py)

修改目标：

- 把 `active_dataset` 从“疑似当前真相”收口成“恢复索引”

具体修改：

1. 当前轮有显式文件时，直接覆盖旧 `active_dataset`
2. 当前轮发生 source/task switch 时，清除不相关旧 binding
3. 若本轮已经决出 `tool_input.path`，session projection 只同步，不再反推

退出条件：

- session state 只记录结果，不再参与当前轮绑定裁决

### 6.7 [backend/structured_memory/process_engine.py](/D:/AI应用/langchain-agent/backend/structured_memory/process_engine.py)

修改目标：

- 收紧 process-state 对 dataset 的继承条件

具体修改：

1. 把显式数据集切换识别为强 `task_switch`
2. `not task_switch` 时才允许继承旧 `active_dataset`
3. 外部 lookup / pdf flow 继续清空 dataset
4. structured flow 下只保留当前有效 dataset

退出条件：

- `inventory -> employees -> inventory` 的三段切换不会被 process-state 串味

---

## 7. 回归测试计划

### 7.1 定向单测

修改或新增：

- [backend/tests/structured_followup_history_regression.py](/D:/AI应用/langchain-agent/backend/tests/structured_followup_history_regression.py)
- 新增 `backend/tests/structured_dataset_switch_regression.py`
- [backend/tests/query_planner_regression.py](/D:/AI应用/langchain-agent/backend/tests/query_planner_regression.py)

必须覆盖：

1. `inventory.xlsx -> employees.xlsx`
2. `employees.xlsx -> 按部门汇总这些高薪员工`
3. `employees.xlsx -> inventory.xlsx`
4. 显式文件与语义冲突时，以显式文件为准
5. 纯 follow-up 仍沿用上一张表

### 7.2 长场景断言

文件：

- [backend/tests/system_eval/long_scenarios.py](/D:/AI应用/langchain-agent/backend/tests/system_eval/long_scenarios.py)

补强断言：

1. `现在换成 employees.xlsx，找出薪资前五的人`
   - `event.tool=structured_data_analysis`
   - tool input path 必须是 `employees.xlsx`
2. `按部门汇总这些高薪员工`
   - 必须延续 `employees.xlsx`
3. `再回到 inventory.xlsx，哪一个仓库最该优先补货`
   - 必须重新绑定 `inventory.xlsx`

---

## 8. 实施顺序

### Phase A：绑定优先级修正

文件：

- `backend/query/tool_input_resolver.py`
- `backend/understanding/task_understanding.py`
- `backend/understanding/query_understanding.py`

目标：

- 先把“当前轮绑定”立起来

### Phase B：延续与重绑定拆分

文件：

- `backend/query/continuation_resolver.py`
- `backend/query/followup_resolver.py`

目标：

- 先分清“继续上一张表”和“切换到新表”

### Phase C：恢复层收口

文件：

- `backend/structured_memory/session_memory.py`
- `backend/structured_memory/process_engine.py`

目标：

- 把恢复层从判决层降级成索引层

### Phase D：回归与长场景验证

目标：

- 跑定向 regression
- 跑长场景
- 追踪是否仍有 dataset 串味

---

## 9. 退出标准

本专项计划完成的判断标准不是“代码改了”，而是以下 5 条同时满足：

1. 显式文件切换永远优先于历史 dataset
2. 强语义切换不会再错误继承旧 dataset
3. 纯 follow-up 仍能稳定沿用上一张表
4. session/process state 不再反向污染当前轮绑定
5. 长场景中的 `inventory -> employees -> inventory` 切换稳定通过

---

## 10. 与 `docs/32` 的关系

这份计划书不是替代 [docs/32-Claude式记忆召回与主线程去污逐文件执行清单.md](/D:/AI应用/langchain-agent/docs/32-Claude式记忆召回与主线程去污逐文件执行清单.md)，而是把其中第一类残留问题单独下钻。

关系如下：

- `docs/32` 负责 memory recall / session visible state / main-thread governance 的总收口
- 本文负责其中“结构化数据绑定与恢复边界”的专项修复

后续真正实施代码修改时，应以本文作为这一类问题的直接执行依据。
