# Claude式统一续接主链修复计划书

> 目的：针对当前系统中 `follow-up handle` 只完成局部重构、未形成统一主链协议的问题，基于当前代码真实状态，严格对照既有 docs 设计原则，完成一次“统一续接主链”的专项修复规划。  
> 本计划书不是单点 bug 清单，而是对以下几类残留问题的统一收口：
>
> - `这份 PDF / 那个表 / 第三个子任务` 这类 follow-up 不能稳定续接到既有执行单元
> - single direct tool 路径与 compound task 路径使用了两套不同的 task 真相
> - `binding_ref` 已能解析，但 runtime 未真正消费
> - `MainContextState`、session/process、task registry、tool summary 各自持有一部分“当前真相”，没有统一 owner
> - output boundary 尚未和 follow-up handle 主链彻底打通，导致 raw tool output、错误状态、陈旧控制面继续扩散
>
> 本文严格对照：
>
> - [docs/06-上下文管理.md](/D:/AI应用/langchain-agent/docs/06-上下文管理.md)
> - [docs/12-Agent-系统.md](/D:/AI应用/langchain-agent/docs/12-Agent-系统.md)
> - [docs/14-任务系统.md](/D:/AI应用/langchain-agent/docs/14-任务系统.md)
> - [docs/23-Memory系统.md](/D:/AI应用/langchain-agent/docs/23-Memory系统.md)
> - [docs/25-架构模式总结.md](/D:/AI应用/langchain-agent/docs/25-架构模式总结.md)
> - [docs/28-上下文隔离逐文件改造清单.md](/D:/AI应用/langchain-agent/docs/28-上下文隔离逐文件改造清单.md)
> - [docs/33-Claude式结构化数据绑定修复计划书.md](/D:/AI应用/langchain-agent/docs/33-Claude式结构化数据绑定修复计划书.md)
> - [docs/34-Claude式Follow-up句柄续接修复计划书.md](/D:/AI应用/langchain-agent/docs/34-Claude式Follow-up句柄续接修复计划书.md)
> - [docs/35-Claude式输出边界去泄露重构计划书.md](/D:/AI应用/langchain-agent/docs/35-Claude式输出边界去泄露重构计划书.md)

---

## 1. 这份计划书的定位

这不是“继续补 follow-up resolver”的补丁清单，而是一份统一续接主链的专项修复蓝图。

本轮要解决的问题，本质上不是：

- 某个关键词没命中
- 某个 history fallback 次序不对
- 某个 output sanitize 不够全

而是：

> 当前系统还没有形成一个真正统一的“续接主链协议”。

目前系统中，至少并存了四条部分重叠的续接/绑定路径：

1. `QueryFollowupResolver` 的 handle 解析路径
2. `QueryContinuationResolver` 的文本/历史续接路径
3. direct tool execution 的临时 summary/task 生成路径
4. compound subtask execution 的 `TaskCoordinator` 持久 task 路径

这些路径没有收敛到同一套 execution handle、binding owner、runtime dispatch 和 output boundary 上。

因此，本计划书的目标不是“再调优某个 resolver”，而是：

1. 统一 execution handle 的生产方式
2. 统一 binding owner 的归属方式
3. 统一 follow-up protocol 的解析入口
4. 统一 runtime 对 handle 的消费分流
5. 统一 main thread 只保留控制面真相的更新方式
6. 统一 answer/output boundary 只消费 summary/result ref 的输出方式

---

## 2. 先给结论：为什么这个问题在之前重构后仍然存在

按现有 docs，`follow-up handle` 本应在之前几轮改造中已经成为主链协议。

但当前代码的真实状态是：

### 2.1 handle 结构只落了一半

- compound 路径有 `TaskRecord + TaskContextRef`
- direct tool 路径只有临时 `TaskSummaryRef`

结果：

- compound query 的 follow-up 可以部分走 task handle
- single PDF / single structured tool 的 follow-up 没有稳定 handle 可续接

### 2.2 binding_ref 解析有了，运行时分流没完成

当前 [backend/query/followup_resolver.py](/D:/AI应用/langchain-agent/backend/query/followup_resolver.py) 已经会产出：

- `task_ref`
- `compound_subset`
- `binding_ref`

但 [backend/query/runtime.py](/D:/AI应用/langchain-agent/backend/query/runtime.py) 实际 direct follow-up 只接：

- `task_ref`
- `compound_subset`

`binding_ref` 没有进入局部重执行 path，而是重新掉回普通 planner。

### 2.3 “当前真相”分散在多个层，且 owner 不统一

当前至少有这些层都在持有某种“当前 PDF / 当前 dataset / 当前 task”信息：

- `TaskRecord.context_ref.bindings`
- `TaskSummaryRef.key_points`
- `MainContextState.active_constraints`
- session/process state 中的 `active_pdf / active_dataset`
- planner/tool_input_resolver 的现场推断结果

这些层既没有统一 owner，也没有严格的写入顺序和覆盖顺序。

### 2.4 output boundary 和 follow-up handle 还是分离实施

当前 output boundary 已经有初步模块，但 follow-up 续接链仍然可能：

- 从 planner fresh route 重新猜绑定
- 从 raw tool output 直接生成用户答案
- 把失败输出和工作态一起投影回控制面

这使得“错误续接”和“错误输出扩散”实际上是同一类结构问题的两个表象。

---

## 3. 当前系统状态总览

这一节只描述当前代码的真实状态，不做理想化假设。

### 3.1 已经有的结构

当前项目已经具备下面这些可复用基础：

- `FollowupResolution`
- `MainContextState`
- `TaskRecord`
- `TaskContextRef`
- `TaskSummaryRef`
- `TaskResultRef`
- `AnswerAssembler`
- `AssistantOutputBoundary`

这些对象说明架构方向本身是对的，问题不是“缺理念”，而是“缺统一主链”。

### 3.2 还没有统一的部分

当前未统一的关键点有：

1. execution handle 的生产入口不统一  
   compound 走 `TaskCoordinator.run_query_tasks()`，direct tool 走 `run_tool_task()`，两者持久化粒度不一致。

2. binding owner 不统一  
   `planner / tool_input_resolver / task_coordinator / session/process` 都在不同阶段决定或恢复 binding。

3. runtime dispatch 不完整  
   `binding_ref` 没有独立执行路径。

4. summary/result ref 还不是唯一输出来源  
   raw tool output 仍会直接进入用户答案。

5. session/process 仍可能暴露陈旧控制面  
   follow-up 未命中 handle 时，会把旧工作态继续投影到 model-visible context。

### 3.3 直接导致的现象

这会直接造成：

- `这份 PDF` 没续接到当前 PDF，而是被当作 fresh PDF query
- 第四页读取失败后，下一轮仍保留陈旧 `active_goal / next_step`
- direct tool 场景中 `followup_target_task_id` 为空
- `task_summary_refs` 中出现 synthetic task id，不能回查真实 task registry
- `binding_ref` 理论可解析，实践不可闭环

---

## 4. 本轮必须严格遵守的设计原则

下面这些不是建议，而是本轮的硬约束。

### 4.1 单一真相源

对同一次可续接执行而言，必须存在唯一 execution handle owner。

具体要求：

- 任何可续接的执行都必须落为真实 `TaskRecord`
- `TaskRecord.task_id` 是续接唯一主键
- `TaskContextRef.bindings` 是 binding owner 真相
- `TaskSummaryRef` 只允许引用既有 task，不得发明新的 synthetic task owner

禁止项：

- 不允许 direct tool 继续只产出 summary、不注册完整 task
- 不允许 planner、continuation、session/process 同时竞争“当前 PDF 是谁”

### 4.2 默认隔离，显式共享

对照 [docs/12-Agent-系统.md](/D:/AI应用/langchain-agent/docs/12-Agent-系统.md) 与 [docs/25-架构模式总结.md](/D:/AI应用/langchain-agent/docs/25-架构模式总结.md)：

- task-local truth 默认留在 task 层
- main thread 只通过显式 handle 消费 task truth
- session/process 只能拿控制面投影，不能直接接收 task 内部工作文本

禁止项：

- 不允许通过 prose 把 task-local truth 回写主线程
- 不允许以“当前 summary 看起来够用”为理由跳过 task registry 落地

### 4.3 恢复层只恢复，不裁决

对照 [docs/06-上下文管理.md](/D:/AI应用/langchain-agent/docs/06-上下文管理.md) 与 [docs/33-Claude式结构化数据绑定修复计划书.md](/D:/AI应用/langchain-agent/docs/33-Claude式结构化数据绑定修复计划书.md)：

- session/process/warm snapshot 只能作为恢复索引
- 当已有明确 task handle / binding owner 时，恢复层不得覆盖

禁止项：

- 不允许 `active_pdf` 这类恢复态字段越权成为当前轮 binding 裁决源
- 不允许 history fallback 在 handle 已命中后重新猜一次

### 4.4 主线程只保留控制面真相

对照 [docs/34-Claude式Follow-up句柄续接修复计划书.md](/D:/AI应用/langchain-agent/docs/34-Claude式Follow-up句柄续接修复计划书.md) 与 [docs/35-Claude式输出边界去泄露重构计划书.md](/D:/AI应用/langchain-agent/docs/35-Claude式输出边界去泄露重构计划书.md)：

主线程允许持有：

- 当前指向哪个 task
- 当前选择了哪些 task
- 当前 binding key / active constraint
- 当前输出约束

主线程禁止持有：

- continuation prose
- raw tool output
- worklog/debug/thinking text
- task-local page snippet / retrieval snippet

### 4.5 summary-first，result-ref-second，raw-output-last

对照 [docs/28-上下文隔离逐文件改造清单.md](/D:/AI应用/langchain-agent/docs/28-上下文隔离逐文件改造清单.md)：

- 主线程答复优先消费 `TaskSummaryRef`
- 需要更高保真时通过 `TaskResultRef / EvidenceRef` 回查
- raw tool output 不直接作为用户答案来源

禁止项：

- 不允许 direct tool done content 原样成为最终用户答案
- 不允许把 raw tool output 直接写进 session history 的 canonical truth

---

## 5. 本轮总目标架构

本轮围绕这 7 个结构层统一收口。

### 5.1 Unified Execution Handle Layer

职责：

- 把 compound subtask 和 direct tool execution 统一落成稳定 task handle

唯一真相：

- `TaskRecord.task_id`

核心对象：

- `TaskRecord`
- `TaskContextRef`
- `TaskResultRef`

### 5.2 Task Local Truth Layer

职责：

- 承载某个 task 的局部真相

唯一真相：

- `TaskContextRef.bindings`
- `TaskContextRef.constraints`
- `TaskContextRef.result_ref_id`

### 5.3 Binding Owner Layer

职责：

- 给任意续接型 query 提供唯一 binding owner

唯一真相：

- `TaskContextRef.bindings`

允许来源：

- `explicit_path`
- `semantic_default`
- `task_ref`
- `session_restore`
- `history_fallback`

### 5.4 Followup Protocol Layer

职责：

- 把用户 follow-up 解析成结构化 handle，不生成工作文本

唯一真相：

- `FollowupResolution`

### 5.5 Handle-First Runtime Dispatch Layer

职责：

- 按 handle 类型进入不同执行路径

三种路径：

- `task_ref`
- `compound_subset`
- `binding_ref`

### 5.6 Main Control Plane Layer

职责：

- 主线程只保存控制面真相

唯一对象：

- `MainContextState`

### 5.7 Summary / Output Boundary Layer

职责：

- 把 task-local truth 装配成用户可见答案

唯一入口：

- `AnswerAssembler`
- `AssistantOutputBoundary`

---

## 6. 本轮必须一起搭起来的相关结构

这一节是本计划书最重要的部分。它明确说明：要修 follow-up handle，不是只改 resolver，而要把哪些相关结构一起搭起来。

### 6.1 direct tool task 必须升级为一级 task

当前问题：

- `run_tool_task()` 只记录 generic tool task
- 没有 `TaskContextRef`
- 没有稳定 binding owner

本轮要求：

- direct tool 执行完成后，必须拥有真实 `TaskRecord`
- `TaskRecord.context_ref` 不能为空
- `TaskRecord.summary`、`TaskRecord.result_ref`、`TaskRecord.context_ref.bindings` 必须齐全

结果：

- PDF/表格/weather 这类 single tool 场景都能被统一续接

### 6.2 direct tool 和 compound task 的 task_id 体系必须统一

当前问题：

- compound task 是 `session-1-subtask-2` 这种真实 id
- direct tool summary 常是 `tool:pdf`、`tool:main` 这种 synthetic id

本轮要求：

- `TaskSummaryRef.task_id` 必须引用真实 `TaskRecord.task_id`
- 不允许 answer/runtime/session memory 再制造 synthetic continuation id

### 6.3 binding owner 必须从 task 层向上投影，而不是从主线程反推

当前问题：

- `active_pdf` 有时来自 execution.tool_input
- 有时来自 session/process 恢复
- 有时来自 history fallback

本轮要求：

- 主线程 `active_pdf / active_dataset` 只能从 task owner 投影
- 不允许主线程控制面反过来成为 task binding 的来源

### 6.4 FollowupResolution 必须能表达 owner，而不仅是 key

当前问题：

- `binding_key=active_pdf` 只能表达“依赖某个资源”
- 不能表达“这个资源属于哪个 task”

本轮要求：

- `FollowupResolution` 必须能携带 binding owner task
- runtime 在 `binding_ref` 模式下可以直接找到既有 owner，并按该 owner 局部重执行

### 6.5 MainContextState 只能持有控制面投影

本轮要求：

- `followup_target_task_id`
- `followup_target_task_ids`
- `active_constraints`
- `next_step`

允许留在控制面。

不允许继续塞入：

- page snippet
- task raw result
- continuation prose
- planner guess text

### 6.6 session/process 只能消费 projection，不能参与当前续接裁决

本轮要求：

- session/process 只能作为：
  - 恢复索引
  - debug trace 辅助
  - 主线程 context rebuild 输入

不得作为：

- follow-up 主路由源
- 当前 binding owner 裁决源
- direct tool continuation owner

### 6.7 AnswerAssembler 和 OutputBoundary 必须参与同一闭环

本轮要求：

- `task_ref / compound_subset` 直接消费已有 summaries
- `binding_ref` 的局部重执行结果先生成 summary/ref，再交给 assembler
- raw tool output 只能进入 result/evidence channel，不直接进入用户答案

---

## 7. 分阶段实施计划

这一节明确每一阶段的输入、处理流程、产物、退出条件和禁止偏移项。

### Phase 0：结构护栏与基线观测

目的：

- 在改代码前，先把“真正想锁住的行为”变成可验证 contract

输入：

- 当前长场景 `research-brief-and-document-resume`
- 当前 follow-up 相关 regression

处理流程：

1. 为 single PDF direct tool 场景补充 regression：
   - 打开 PDF
   - 第三页
   - 第四页
   - 这份 PDF 的核心结论
2. 断言以下字段必须可观察：
   - `followup_mode`
   - `followup_task_id`
   - `followup_task_ids`
   - `used_task_summary_refs`
   - `tool_start.input.path`
   - `main_context.active_constraints.active_pdf`
3. 长场景断言不再只看：
   - `plan.tool=pdf_analysis`
   - `response.nonempty`
4. 增加语义断言：
   - follow-up path 是否沿用同一 task/binding
   - 最终 path 是否等于上一轮 active_pdf

产物：

- 新的 regression gate
- 明确的失败前置样例

退出条件：

- 当前系统在这些场景下的失败模式可以被测试稳定捕获

禁止偏移：

- 不允许在没有增加新的闭环断言前进入实现阶段

### Phase 1：统一 execution handle 生产

目的：

- 让 compound 和 direct tool 都生成同一种 task handle

输入：

- `QueryExecutionPlan`
- direct tool execution
- compound subtask execution

处理流程：

1. 把 direct tool task 从 generic log 升级为真实 `TaskRecord`
2. direct tool task 创建时同步建立 `TaskContextRef`
3. 对 direct tool 执行完成后补齐：
   - `summary`
   - `result_ref`
   - `bindings`
   - `constraints`
4. `TaskSummaryRef.task_id` 改为引用真实 task id
5. single execution `done.task_summary_refs` 从 task registry 取，不再现场 synthetic 生成

产物：

- 统一 task registry
- 统一 task_id

退出条件：

- same session 中 direct tool PDF 执行完成后，可被 `TaskCoordinator.list_tasks()` 查到
- 该 task 持有 `context_ref.bindings.active_pdf`

禁止偏移：

- 不允许 direct tool 路径继续只产出 `TaskSummaryRef` 而不落 `TaskRecord`

### Phase 2：统一 binding owner

目的：

- 确定 binding 从哪里来，以及谁有资格覆盖谁

输入：

- current explicit binding
- task context binding
- session restore
- history fallback

处理流程：

1. 明确 binding resolution 的唯一顺序：
   1. 当前轮显式路径
   2. 当前轮强语义默认绑定
   3. follow-up handle 指向 task 的 binding
   4. session 最近有效 task binding
   5. history fallback
2. `TaskContextRef.bindings` 成为 binding owner 真相
3. `MainContextState.active_constraints.active_pdf/active_dataset` 只作为 owner 投影
4. `tool_input_resolver` 降级为 consumer，不再拥有 binding 裁决权

产物：

- binding owner 统一
- 覆盖顺序固定

退出条件：

- 当前轮显式路径和 follow-up owner binding 不会再被 session/history 覆盖

禁止偏移：

- 不允许新增新的“猜 binding”入口

### Phase 3：统一 follow-up protocol

目的：

- 把 follow-up 从文本续接彻底收成结构化协议

输入：

- 用户 follow-up message
- task registry
- binding owner registry

处理流程：

1. 收紧 `FollowupResolution` 为纯协议对象
2. 增加 `binding_owner_task_id` 或等价字段
3. `QueryFollowupResolver` 只做：
   - `task_ref`
   - `compound_subset`
   - `binding_ref`
   - `none`
4. direct tool 场景补齐 PDF / dataset / weather 续接型指代识别
5. 不再允许 resolver 生成工作文本或 planner hints

产物：

- 统一 follow-up protocol

退出条件：

- `这份 PDF`
- `这个表`
- `第一个和第三个`

都能产出稳定协议结果。

禁止偏移：

- 不允许再通过 prose 改写来“补救” follow-up

### Phase 4：runtime 改为完整 handle-first 分流

目的：

- 让 runtime 真正把三类 handle 都当作一等执行入口

输入：

- `FollowupResolution`
- task registry
- binding owner task

处理流程：

1. `task_ref`
   - 不重建 planner
   - 直接从 `TaskSummaryRef / TaskResultRef` 取结果
2. `compound_subset`
   - 不重跑原 compound tools
   - 直接重组 selected tasks
3. `binding_ref`
   - 不落回普通 planner
   - 以 binding owner task 为基准构造局部执行 plan
   - 只共享 binding/constraints，不共享 task-local raw text
4. `none`
   - 才允许走普通 planner

产物：

- 完整 handle-first runtime

退出条件：

- `binding_ref` 不再回落 planner-first
- `followup_mode` 在 binding follow-up 场景下不为空

禁止偏移：

- 不允许 `binding_ref` 继续被当作普通 fresh query

### Phase 5：控制面更新收口

目的：

- 保证主线程只保留控制面真相

输入：

- runtime follow-up result
- task summary refs
- owner binding projection

处理流程：

1. `MainContextState` 只写：
   - `followup_target_task_id`
   - `followup_target_task_ids`
   - `active_constraints`
   - `next_step`
2. 陈旧 active goal / old failure state 不再跨轮残留
3. session/process projection 只读 control-plane payload

产物：

- 干净的 main thread control plane

退出条件：

- turn-08 不再看到 turn-07 的阻塞目标继续出现在 model-visible active goal

禁止偏移：

- 不允许把错误信息、page snippet、tool dump 再塞回控制面

### Phase 6：summary-first answer / output boundary 闭环

目的：

- 保证 follow-up 结果从 summary/ref 输出，而不是 raw output 直吐

输入：

- selected task summaries
- result refs
- active style constraints

处理流程：

1. `AnswerAssembler` 统一消费 `TaskSummaryRef`
2. `binding_ref` 局部重执行后先形成 summary，再进入 assembler
3. `AssistantOutputBoundary` 只处理 canonical visible answer
4. raw tool output 进入 `TaskResultRef / EvidenceRef`

产物：

- follow-up answer 的 summary-first 闭环

退出条件：

- 用户要“三条行动建议”时，不再看到 raw PDF browse dump

禁止偏移：

- 不允许把 direct tool raw output 再直接回给用户

### Phase 7：旧路径清理与门禁固化

目的：

- 清理会把系统重新拖回旧路径的兼容逻辑

处理流程：

1. 收紧 `QueryContinuationResolver` 的职责
2. 清理 single execution synthetic task summary 逻辑
3. 收紧 session/process 对 follow-up 的越权恢复
4. 把关键长场景语义断言纳入回归门禁

退出条件：

- 续接相关主链只剩统一协议入口

禁止偏移：

- 不允许在旧路径上继续叠加特判

---

## 8. 逐文件实施清单

### 8.1 [backend/tasks/coordinator.py](/D:/AI应用/langchain-agent/backend/tasks/coordinator.py)

本轮职责：

- 成为统一 execution handle 的注册中心

要改：

- 把 direct tool task 从“工具日志”升级成“可续接 task”
- direct tool 任务创建时也要建立 `TaskContextRef`
- direct tool 完成后补齐 `summary/result_ref/bindings/constraints`

退出标准：

- `TaskCoordinator.list_tasks(session_id)` 能查到 single PDF/direct tool 对应 task

### 8.2 [backend/tasks/models.py](/D:/AI应用/langchain-agent/backend/tasks/models.py)

本轮职责：

- 统一任务真相模型

要改：

- 保证 single tool / compound subtask 使用同一 `TaskRecord` 结构
- 明确 metadata 中的：
  - `session_id`
  - `parent_query_id`
  - `subtask_index`
  - `execution_kind`

### 8.3 [backend/tasks/context_models.py](/D:/AI应用/langchain-agent/backend/tasks/context_models.py)

本轮职责：

- 承载 task-local truth 和 binding owner

要改：

- 强化 `TaskBindings` 对 PDF/dataset/location 的承载
- 约束 `TaskConstraints` 只承载局部控制约束
- 必要时增加 binding source/owner 信息

### 8.4 [backend/query/followup_models.py](/D:/AI应用/langchain-agent/backend/query/followup_models.py)

本轮职责：

- 承载 follow-up 协议

要改：

- 保持纯协议对象
- 补齐 binding owner 追踪字段
- 禁止文本改写字段回归

### 8.5 [backend/query/followup_resolver.py](/D:/AI应用/langchain-agent/backend/query/followup_resolver.py)

本轮职责：

- 从 task/binding registry 解析 follow-up handle

要改：

- 支持 direct tool 续接型指代表达
- `binding_ref` 解析必须返回 owner task
- 不负责生成 prose

### 8.6 [backend/query/runtime.py](/D:/AI应用/langchain-agent/backend/query/runtime.py)

本轮职责：

- 统一 handle-first dispatch

要改：

- `binding_ref` 局部重执行 path 落地
- `task_ref / compound_subset / binding_ref / none` 四路分流固定化
- single execution task summary 不再 synthetic 生成 task owner
- `MainContextState` 只写控制面真相

### 8.7 [backend/query/context_models.py](/D:/AI应用/langchain-agent/backend/query/context_models.py)

本轮职责：

- 承载主线程控制面

要改：

- 明确 `MainContextState` 仅保留控制面字段
- `TaskSummaryRef` 成为 assembler 的唯一 summary 输入

### 8.8 [backend/query/answer_assembler.py](/D:/AI应用/langchain-agent/backend/query/answer_assembler.py)

本轮职责：

- 统一输出装配

要改：

- 以 `TaskSummaryRef` 为主输入
- `binding_ref` 局部执行的结果也必须走 summary-first
- 禁止 fallback 到 raw tool output 直吐

### 8.9 [backend/memory/context.py](/D:/AI应用/langchain-agent/backend/memory/context.py)

本轮职责：

- 控制 model-visible vs debug-visible 边界

要改：

- follow-up 相关 projection 只暴露控制面
- debug trace 和恢复细节继续留在 debug sections

### 8.10 [backend/context_management/context_models.py](/D:/AI应用/langchain-agent/backend/context_management/context_models.py)

本轮职责：

- 维护 model/debug 分层

要改：

- 确保 follow-up 控制面字段能单独进入 model-visible section
- task-local/raw/debug 继续只留 debug view

### 8.11 测试文件

至少新增或强化：

- `backend/tests/followup_resolution_regression.py`
- `backend/tests/query_runtime_route_guard_regression.py`
- `backend/tests/pdf_followup_history_regression.py`
- `backend/tests/system_eval/long_scenarios_regression.py`
- `backend/tests/system_eval/long_scenarios.py`

---

## 9. 每阶段必须锁住的流程细节

为了防止后续实现时再次偏移，这里把每阶段的“标准流程”写死。

### 9.1 standard direct tool turn

标准流程必须是：

`user message`
-> `planner builds single execution`
-> `runtime executes direct tool`
-> `task registry records real TaskRecord`
-> `task context stores bindings/constraints/result ref`
-> `summary ref points to same task_id`
-> `MainContextState stores only control-plane projection`
-> `AnswerAssembler / OutputBoundary emit canonical answer`

### 9.2 standard follow-up task_ref turn

标准流程必须是：

`user message`
-> `FollowupResolution(mode=task_ref)`
-> `runtime direct follow-up path`
-> `task summary/result ref lookup`
-> `AnswerAssembler`
-> `MainContextState only updates target task ids / constraints`

### 9.3 standard follow-up binding_ref turn

标准流程必须是：

`user message`
-> `FollowupResolution(mode=binding_ref, binding_owner_task_id=...)`
-> `runtime binding continuation path`
-> `inherit binding owner only`
-> `construct local execution`
-> `produce new task result + summary`
-> `AnswerAssembler`
-> `MainContextState updates new selected owner projection`

### 9.4 standard compound_subset turn

标准流程必须是：

`user message`
-> `FollowupResolution(mode=compound_subset)`
-> `runtime subset assembly path`
-> `reuse existing task summaries`
-> `do not rerun original tools`
-> `AnswerAssembler`

---

## 10. 回归门禁

本轮验收不能再只看 `passed/failed` 或 `response.nonempty`。

### 10.1 结构门禁

- 所有可续接 direct tool 执行都必须注册真实 task
- `TaskSummaryRef.task_id` 必须能在 `TaskCoordinator` 中回查
- `binding_ref` 不得回落普通 planner
- `MainContextState` 不得携带 raw output

### 10.2 语义门禁

- 打开某 PDF 后，“这份 PDF”必须续接同一份 PDF
- 结构化数据 follow-up 必须续接同一份 dataset
- “第一个和第三个”不应重跑 compound tools
- 用户请求压缩/重写时，不得把 raw tool dump 原样回给用户

### 10.3 长场景门禁

长场景至少要断言：

- `followup_mode != ""`
- `followup_target_task_id` 正确
- `tool_start.input.path == previous active_pdf`
- `used_task_summary_refs` 命中已存在 task
- `response` 符合 style constraint，不是 raw browse dump

---

## 11. 本轮明确不做的事

为了防止范围失控，本轮明确不做：

- 不重写整个 memory framework
- 不引入外部 agent/runtime 框架
- 不把问题扩成 durable memory 全链重构
- 不通过追加更多 prompt/regex 补丁代替结构修复
- 不继续维护两套并存的 follow-up 主链

---

## 12. 实施顺序建议

严格按照下面顺序执行，不允许跳步：

1. `Phase 0`：补结构护栏与长场景语义断言
2. `Phase 1`：统一 execution handle 生产
3. `Phase 2`：统一 binding owner
4. `Phase 3`：统一 follow-up protocol
5. `Phase 4`：runtime 完成 handle-first 四路分流
6. `Phase 5`：主线程控制面收口
7. `Phase 6`：summary-first answer / output boundary 闭环
8. `Phase 7`：旧路径清理与门禁固化

执行纪律：

- 默认连续执行，除非遇到真实结构冲突、关键契约不清或回归门禁无法解释，否则不中途停下来等待确认。
- 每完成一个 phase，必须先补或更新 regression，再进入下一阶段
- 未形成单向主链前，不允许开始“优化回答质量”
- 未完成 runtime dispatch 前，不允许只修 resolver 识别词

---

## 13. 最终收口标准

当下面这些条件同时满足时，本轮才算真正完成：

1. direct tool 与 compound task 都有统一 task handle
2. `FollowupResolution` 成为 follow-up 唯一主协议
3. `binding_ref` 可以真正闭环执行
4. `MainContextState` 只承载控制面真相
5. session/process 不再越权裁决当前 binding
6. `AnswerAssembler + OutputBoundary` 成为唯一用户答案出口
7. 长场景中：
   - `这份 PDF`
   - `那个表`
   - `第一个和第三个`

   都能稳定续接且不出现 raw output 泄露

---

## 14. 一句话总结

本轮不是“修 follow-up”，而是：

> 把当前系统中分裂的 execution handle、binding owner、follow-up protocol、runtime dispatch、main control plane、answer boundary，统一为一条严格的 Claude 式续接主链。
