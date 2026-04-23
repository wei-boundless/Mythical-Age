# Claude式 Follow-up 边界收缩与主链仲裁修复计划书

> 编写日期：2026-04-23  
> 直接输入：`docs/50-长场景显性语义错误问题清单与根因追踪-20260423.md`  
> 本地参考实现：`D:/AI应用/claude-code-nb-main/`  
> 目的：不重构整套系统，只针对当前 follow-up / continuation / binding / tool input 交叉越权问题，按 Claude Code 的边界治理方式做一轮精修。

## 0. 当前执行进度

截至本轮代码落地，已完成以下收口：

1. `runtime` 已增加 binding follow-up 仲裁门，不再允许 candidate 在 planner 前直接短路主链。
2. `followup_resolver` 已补上全局综合类请求的排除规则，避免“总总结 / 四段组织 / 跨源综合”被单源 binding 抢走。
3. `tool_input_resolver` 已固定结构化数据 authority，`structured_binding.dataset_path` 不再被弱短路径覆盖。
4. `TaskCoordinator` 已修复同 session 多轮 `run_query_tasks()` 子任务编号冲突，避免旧任务被覆盖导致 owner 解析漂移。
5. `binding follow-up` 执行后的 `main_context.followup_target_task_id` 与 `task_summary_refs` 已对齐到本次真实执行任务，保证后续汇总、记忆投影、trace 分析可追。
6. `planner` 已切到 compound 子任务顺序构建，并显式滚动传递 authoritative context；同源 PDF / 数据表子任务可以继承父级 authority，跨源子任务不会被错误劫持。

本轮已验证通过的回归：

- `backend/tests/query_runtime_route_guard_regression.py`
- `backend/tests/followup_resolution_regression.py`
- `backend/tests/structured_followup_history_regression.py`
- `backend/tests/answer_assembler_regression.py`
- `backend/tests/task_coordinator_regression.py`
- `backend/tests/query_planner_regression.py`
- `backend/tests/pdf_followup_history_regression.py`
- `backend/tests/compound_query_regression.py`

---

## 1. 当前问题定义

当前长场景中的若干显性语义错误，已经追到一条共同主链：

`follow-up 启发式越权 -> planner 前被短路 -> source owner 丢失或被劫持 -> tool_input 接受错误 authority -> 主链继续把错误结果包装成可见答案`

这不是单一文件的 bug，而是如下四层职责没有切开：

1. 当前输入显式提升
2. 历史任务续接候选
3. 当前 turn 正式仲裁
4. tool input 最终物化

当前代码里，这四层职责分别散落并互相重叠在：

- `backend/query/continuation_resolver.py`
- `backend/query/followup_resolver.py`
- `backend/query/planner.py`
- `backend/query/runtime.py`
- `backend/query/tool_input_resolver.py`

结果就是：

1. 启发式不只是“帮助识别候选”，而是直接决定是否绕过 planner 主链。
2. follow-up 不是一个候选层，而变成了一个轻量路由器。
3. 显式短路径、binding、task owner、query regex hit 之间没有稳定 authority 顺序。
4. compound / cross-source / global synthesis 请求会被单源 binding 劫持。

因此，本计划书的目标不是“提高启发式命中率”，而是：

`把启发式从裁决层降回候选层，把主链裁决权收回 runtime，把 tool input 收缩成纯物化层。`

---

## 2. 本轮修复要遵守的设计原则

本计划书以本仓库以下原则文档为正式约束：

- `docs/设计原则/03-状态管理.md`
- `docs/设计原则/05-对话循环.md`
- `docs/设计原则/06-上下文管理.md`
- `docs/设计原则/12-Agent-系统.md`
- `docs/设计原则/14-任务系统.md`
- `docs/设计原则/23-Memory系统.md`
- `docs/设计原则/25-架构模式总结.md`

抽象成可执行约束后，当前修复必须遵守下面 6 条：

### 2.1 restore 不等于 decide

- 历史 binding、task owner、显式文件名、generic follow-up hint 都只能产生“候选”。
- 当前 turn 的正式路由，必须在统一仲裁点完成。
- 任一早期启发式层都不得直接越过 planner 主链抢占执行。

### 2.2 单一 authority 优先于弱 hint

- 解析后的正式 path / binding 是 authority。
- 短文件名、query regex 命中、generic object reference 只是 hint。
- hint 不能覆盖 authority。

### 2.3 默认隔离，显式共享

- 子任务和 follow-up 候选层默认不应污染主线程正式决策。
- 只有被显式声明为“允许穿透”的信息，才能进入主线程执行态。

### 2.4 planner 负责当前 turn 理解，follow-up 只负责续接候选

- 当前 turn 的 intent、route、tool、compound/synthesis 判断应由 planner 主链负责。
- follow-up 层不能单独承担整轮问题类型判断。

### 2.5 tool input 必须是物化层，不是推断层

- `tool_input_resolver` 只能消费上游正式结论并物化成最终入参。
- 它不能再额外承担 source 猜测、对象续接和 authority 裁判。

### 2.6 复合任务和全局总结必须先过主链仲裁

- cross-source synthesis、session summary、compound fanout 不得被单一 binding follow-up 劫持。
- 单源续接只能是主链仲裁后的特例，不是默认优先级更高的快捷路径。

---

## 3. 对照 Claude Code 的本地参考结论

本轮已检查目录外本地源码：

- `D:/AI应用/claude-code-nb-main/utils/userPromptKeywords.ts`
- `D:/AI应用/claude-code-nb-main/utils/processUserInput/processTextPrompt.ts`
- `D:/AI应用/claude-code-nb-main/query.ts`
- `D:/AI应用/claude-code-nb-main/utils/forkedAgent.ts`

### 3.1 Claude Code 的关键信号

Claude Code 在“续接”层只保留了非常轻的 prompt 级判断：

- `continue`
- `keep going`
- `go on`

它没有做本系统现在这种：

- pdf / xlsx follow-up 绑定推断
- task owner 级 source binding 续接路由
- planner 前 regex 短路

它更依赖：

1. 当前 turn 的消息本身
2. transcript / attachment / task-notification
3. query loop 主链统一执行
4. 默认隔离、显式共享的上下文传递

### 3.2 可借鉴的不是“功能列表”，而是边界结构

从 Claude Code 参考实现里，本系统最应该借鉴的是这三条：

1. prompt 级启发式应保持极轻，不能演化成 follow-up 路由器。
2. 真正的决策权必须留在 query loop 主链，而不是放在前置正则层。
3. 上下文共享必须显式声明，不能靠模糊词命中隐式穿透。

### 3.3 结论

因此，本系统后续修复方向应当是：

- 向 Claude Code 的边界治理方式靠拢
- 不照搬它的全部结构
- 但必须收缩当前 `followup_resolver` 的越权范围

---

## 4. 目标设计

本轮精修后的目标结构如下：

### 4.1 `continuation_resolver` 的正式职责

文件：

- `backend/query/continuation_resolver.py`

只负责：

1. 基于当前 turn 的显式输入做 route promotion
2. 例如：
   - 显式 `.pdf` -> `pdf_analysis`
   - 显式 `.xlsx/.csv` 且有强结构化操作 -> `structured_data_analysis`
   - 明确 session summary -> `memory`

禁止：

1. 基于历史 task owner 决定 binding
2. 基于 generic follow-up hint 决定对象续接
3. 直接劫持 planner 主链

### 4.2 `followup_resolver` 的正式职责

文件：

- `backend/query/followup_resolver.py`
- `backend/query/followup_models.py`

只负责：

1. 从 task registry 中解析 follow-up candidate
2. 产出：
   - `task_ref_candidate`
   - `binding_ref_candidate`
   - `clarify_candidate`
   - `none`

允许使用的启发式：

1. ordinal task 识别
2. 显式文件名与既有 binding 的精确对齐
3. binding owner 候选去重
4. 歧义澄清

禁止：

1. 用 generic regex 直接给出最终 `binding_ref` 裁决
2. 在此层直接屏蔽 planner
3. 用“总总结 / 四段 / PDF / 数据 / 天气”等词组直接做 route 决定

### 4.3 `runtime` 的正式职责

文件：

- `backend/query/runtime.py`

负责：

1. 在当前 turn 里统一仲裁：
   - planner 结果
   - continuation promotion 结果
   - follow-up candidate
2. 决定是否允许：
   - 直接 task_ref answer
   - binding follow-up execute
   - 正常 planner 主链执行

仲裁规则：

1. planner 明确是 `compound`、`memory`、`rag synthesis` 时，binding follow-up 不得抢占。
2. follow-up 为 `ordinal task_ref` 且对象明确时，可优先直答。
3. binding follow-up 只有在“当前 turn 未显式改换任务类型”且“owner 与当前 intent 一致”时才能成立。
4. weak candidate 永远不能压过当前 turn 的显式 query intent。

### 4.4 `tool_input_resolver` 的正式职责

文件：

- `backend/query/tool_input_resolver.py`

只负责：

1. 把上游已经确定的 authority 物化成最终 tool input

authority 顺序固定为：

1. 当前 turn 显式解析成功的正式 path
2. 正式 binding
3. 已验证可用的 `query_understanding.tool_input`

禁止：

1. 再次做对象猜测
2. 再次做 source owner 续接
3. 在 authority 和 hint 之间自行裁决

### 4.5 `planner` 的正式职责

文件：

- `backend/query/planner.py`

负责：

1. 形成当前 turn 的正式 `QueryExecutionPlan`
2. 在 compound 情况下保持父级执行语义不被前置层截断

后续要求：

1. compound subqueries 构建时，应允许显式传递父级 authoritative binding
2. 但该传递必须由 planner/runtime 显式声明，而不是 coordinator 文本重猜

---

## 5. 正式修复路线

本轮不做大重构，分 4 个阶段连续推进。

### Phase 1：收缩 `followup_resolver` 权限

目标：

把 `followup_resolver` 从“轻量路由器”降级成“候选解析器”。

执行项：

1. 清点当前所有 `_looks_like_*` 规则
2. 区分：
   - 候选识别规则
   - 越权裁决规则
3. 对越权规则做如下处理：
   - 降级成 candidate hint
   - 或移出 `followup_resolver`
4. 为 `FollowupResolution` 增加更清楚的候选语义字段
   - 可继续沿用当前模型结构，但语义上改为 candidate-first

完成标准：

1. `followup_resolver` 不再因为 generic hint 直接给出强 `binding_ref`
2. `explicit_input` 不再承担 planner 旁路职责
3. 只保留：
   - ordinal task 识别
   - explicit binding 对齐
   - clarify

### Phase 2：在 `runtime` 建立统一仲裁门

目标：

把“是否采用 follow-up candidate”的最终权力收回 `runtime._execution_events(...)`。

执行项：

1. 新增 runtime 仲裁函数
2. 输入：
   - planner 结果
   - follow-up candidate
   - 当前 message
   - follow-up owner state
3. 输出：
   - `answer_from_followup`
   - `execute_binding_followup`
   - `fall_through_to_planner`

必须覆盖的场景：

1. 全局总结 / 四段汇总 / 跨源综合
2. compound fanout
3. 纯 ordinal task_ref
4. 单源明确追问
5. 模糊弱提示

完成标准：

1. planner 在 compound / global synthesis 请求上重新成为主通道
2. binding follow-up 只在明确适用时触发
3. follow-up 不再默认优先于 planner

### Phase 3：固化 binding authority 顺序

目标：

彻底消除“弱路径覆盖正式 binding”的问题。

执行项：

1. 固定 authority 顺序
2. 明确哪些字段是：
   - authority
   - weak hint
3. 在 `tool_input_resolver` 中只消费 authority
4. 在 `runtime._binding_execution_from_owner(...)` 中继续保持 owner binding 直写
5. 在 `planner` / `binding_resolver` 侧补注释和回归，防止后来又把短路径抬成正式入参

完成标准：

1. `structured_binding.dataset_path` 不再被短文件名覆盖
2. `active_pdf/active_dataset` 成为 owner follow-up 的唯一正式来源
3. 最终 tool input 不再接受未经确认的弱 path

### Phase 4：补全 compound 继承与回归门禁

目标：

让 compound 子任务不再丢 source owner，同时防止 follow-up 精修后再次回退。

执行项：

1. 在 planner/runtime 中明确 compound 子任务可继承的 authoritative context
2. 不允许 coordinator 只靠 query 文本重猜 binding
3. 增补以下回归：
   - 混合 `PDF + xlsx + weather` 的 compound
   - 全局四段总结
   - 单源追问
   - 弱 hint 不劫持

完成标准：

1. compound 子任务在有父 authority 时不再裸奔
2. 全局总结不会再被单源 binding 抢走
3. 回归样例覆盖当前已知问题链

---

## 6. 文件级执行清单

### 第一组：候选解析层

- `backend/query/followup_resolver.py`
- `backend/query/followup_models.py`

要做：

1. 清理越权 `_looks_like_*` 决策规则
2. 保留 explicit / ordinal / clarify 主路径
3. 明确 candidate-first 语义

### 第二组：当前 turn 仲裁层

- `backend/query/runtime.py`

要做：

1. 加入统一仲裁门
2. 调整 `_execution_events(...)` 顺序
3. 限制 `_stream_binding_followup(...)` 的适用条件

### 第三组：当前输入显式提升层

- `backend/query/continuation_resolver.py`

要做：

1. 保留 explicit promotion
2. 去掉与 follow-up resolver 职责重叠的模糊续接判断

### 第四组：入参物化层

- `backend/query/tool_input_resolver.py`
- `backend/query/binding_resolver.py`

要做：

1. 固定 authority 顺序
2. 保证 resolver 只物化，不越权推断

### 第五组：计划生成层

- `backend/query/planner.py`
- `backend/query/models.py`

要做：

1. 给 compound 子任务 authoritative binding 传递留接口
2. 保持 plan 对当前 turn 的正式解释权

### 第六组：回归测试

- `backend/tests/followup_resolution_regression.py`
- `backend/tests/structured_followup_history_regression.py`
- `backend/tests/pdf_followup_history_regression.py`
- `backend/tests/query_runtime_route_guard_regression.py`
- 需要时新增：
  - `backend/tests/compound_followup_authority_regression.py`

---

## 7. 固定执行流

修复后，正式执行流应固定为：

1. `analyze_query_understanding`
2. `continuation_resolver`
3. `planner` 形成当前 turn 正式 plan
4. `followup_resolver` 只产出 candidate
5. `runtime` 统一仲裁
6. 如需要，才走：
   - task_ref answer
   - binding follow-up execute
7. 最终由 `tool_input_resolver` 物化 authority input

必须禁止的旧行为：

1. `followup_resolver` 在 planner 前直接决定 route
2. generic hint 直接产出强 `binding_ref`
3. tool input 接受弱路径覆盖正式 binding

---

## 8. 迁移与收口规则

### 8.1 Cutover 规则

本轮采用小步 cutover：

1. 先改 `followup_resolver` 语义
2. 再改 `runtime` 仲裁
3. 再固化 authority
4. 最后补 compound 继承

### 8.2 Rollback 规则

出现以下情况必须回退到上一步：

1. 单源 follow-up 全部失效
2. 现有 direct tool 路由被大面积打断
3. compound 路由正常率明显下降
4. tests 中出现“follow-up direct answer 全面回落到 planner”现象

### 8.3 重叠窗口规则

在 Phase 1-2 之间允许旧字段与新语义短暂共存，但必须满足：

1. 字段兼容不等于语义兼容
2. 所有调用点都按 candidate-first 理解 `FollowupResolution`
3. 在 runtime 仲裁生效前，不再继续给 `followup_resolver` 加新启发式

---

## 9. 验证矩阵

### 9.1 功能验证

1. `只展开第二个子任务`
2. `把这份 PDF 的核心结论压成三条行动建议`
3. `最后给我一个总总结，按 PDF、数据、实时、长期记忆四段组织，而且先给结论`
4. `给我 inventory.xlsx 最缺货的前三个仓库`
5. `再按仓库展开一下`
6. `先总结 PDF 第三页，再给我 inventory.xlsx 最缺货的前三个仓库，最后补一句北京天气`

### 9.2 边界验证

1. weak hint 不得劫持 planner
2. authority path 必须压过短路径
3. cross-source synthesis 不得被单源 binding 抢占
4. compound 子任务不得丢失父 authority

### 9.3 回归命令

建议至少持续跑：

```powershell
python backend/tests/followup_resolution_regression.py
python backend/tests/structured_followup_history_regression.py
python backend/tests/pdf_followup_history_regression.py
python backend/tests/query_runtime_route_guard_regression.py
```

---

## 10. 本计划书的最终判断

这轮问题不需要再用“大重构”来处理，但也不能继续靠补启发式往前堆。

最合理的方向是：

1. 收缩 `followup_resolver`
2. 强化 `runtime` 仲裁
3. 固化 binding authority
4. 让 `tool_input_resolver` 回归纯物化层

这条路线既符合本仓库的设计原则，也更接近本地 Claude Code 参考实现的边界治理方式。

因此，后续推进时应统一遵守一句话：

`follow-up 只能提名，主链才能裁决；authority 才能执行，hint 不能入参。`
