# Claude式 Follow-up 句柄续接修复计划书

> 目的：针对长场景 `compound-task-decomposition-and-focus-return` 中暴露出来的第一类问题，彻底把 follow-up 从“自然语言改写续接”改造成“句柄/引用续接”。
>
> 本计划书不再沿用“改写 prompt 让主线程重新理解”的修补思路，而是明确参考 Claude Code 的实际源码机制：
>
> - 子 agent 默认隔离，只允许显式共享少数状态
> - 继续既有执行单元靠稳定句柄，而不是靠自然语言续写
> - side-query 返回结构化选择结果，主线程直接消费结果
> - 子链路不向主线程的全局上下文管理器注册自己的中间状态
> - 预取/选择结果以 attachment / result handle 注入，而不是回写成主线程工作文本

---

## 1. 这份计划书解决的具体问题

当前第一类问题不是泛泛的“上下文污染”，而是下面这条结构性错误链：

1. 用户 follow-up 命中了子任务引用
2. `followup_resolver` 先识别到目标 task
3. 但又把结果降级成 `rewritten_message`
4. `runtime` 用改写后的自然语言重新规划
5. 这段 continuation prose 被写回 session/process/context
6. 主线程后续再从污染后的 working text 中生成答案

这导致的直接问题包括：

- task-local truth 回流主线程
- compound follow-up 退化成主线程二次猜测
- session memory 像工作日志而不是恢复索引
- `active_rule` / `active_goal` / `current_step` 被 continuation prose 污染
- 长场景中出现 `</think>`、```thinking` 之类明显不该出现在用户答案里的内容

---

## 2. 参考的 Claude Code 源码要点

这轮设计不只参考本地 docs，也直接参考你机器上的 Claude Code 源码目录：

- [utils/forkedAgent.ts](/D:/AI应用/claude-code-nb-main/utils/forkedAgent.ts)
- [tools/AgentTool/prompt.ts](/D:/AI应用/claude-code-nb-main/tools/AgentTool/prompt.ts)
- [tools/SendMessageTool/SendMessageTool.ts](/D:/AI应用/claude-code-nb-main/tools/SendMessageTool/SendMessageTool.ts)
- [memdir/findRelevantMemories.ts](/D:/AI应用/claude-code-nb-main/memdir/findRelevantMemories.ts)
- [utils/sideQuery.ts](/D:/AI应用/claude-code-nb-main/utils/sideQuery.ts)
- [services/compact/microCompact.ts](/D:/AI应用/claude-code-nb-main/services/compact/microCompact.ts)
- [query.ts](/D:/AI应用/claude-code-nb-main/query.ts)

从这些实现中，本轮明确借鉴五条机制：

1. 默认隔离，显式共享  
   子 agent 默认 clone/fresh mutable state，主线程不能隐式吸收子链路状态。

2. 继续既有执行单元靠句柄  
   Claude Code 继续已有 agent 靠 `agent_id`/`name`，不是靠把“继续上一次任务”改写成 prompt。

3. 结构化 side-query 输出直接驱动主链  
   召回选择结果是结构化输出，主线程不再做一轮自然语言二次理解。

4. 子链路不能污染主线程的上下文管理器  
   子链路中间 tool results 不得注册进主线程的全局 cached/context 管理状态。

5. 结果通过 attachment/result handle 注入，而不是回写工作文本  
   预取成熟后被消费为独立结果，不被写成新的 session/process prose。

---

## 3. 本轮正式目标

把当前 follow-up 主链：

`user turn -> rewritten_message -> planner 重新理解 -> session/process 吸收 prose -> 模型在污染上下文中再生成`

改成：

`user turn -> FollowupResolution(handle) -> runtime 直接按 task/binding handle 路由 -> AnswerAssembler 重组 -> 主线程只写控制面真相`

最终效果：

- follow-up 不再是“文本续接”
- follow-up 变成“句柄续接”
- task-local truth 留在 task 层
- session memory 只保留恢复索引
- model-visible context 只保留控制面真相

---

## 4. 硬性设计原则

### 4.1 Follow-up 必须是协议问题，不是 prompt 问题

`FollowupResolution` 必须成为主执行协议本体，而不是中间提示词。

### 4.2 Main thread 只保留控制面真相

主线程允许持有：

- 当前指向哪个 task
- 当前选择了哪些 task
- 当前输出约束是什么

主线程禁止持有：

- continuation prose
- subtask raw output
- worklog/debug/thinking 文本

### 4.3 Task-local truth 不得回流 session/process

task 的 bindings、constraints、summary、result ref 应留在 task registry，不得写成主线程 prose。

### 4.4 Session memory 只做恢复索引

session memory 不能再兼任：

- follow-up routing source
- 当前工作日志
- continuation prose 存储区

### 4.5 Model-visible context 必须小于 debug context

debug/governance 信息可以保留给 trace 和测试，但不得继续作为模型工作真相。

---

## 5. 当前必须删除的反模式

下面这些链路不是“待优化”，而是本轮要明确清掉的旧路径：

1. [backend/query/followup_resolver.py](/D:/AI应用/langchain-agent/backend/query/followup_resolver.py) 中 `_rewrite_message()` 产出的 `rewritten_message`
2. [backend/query/runtime.py](/D:/AI应用/langchain-agent/backend/query/runtime.py) 中 `effective_message = followup_resolution.rewritten_message or message`
3. [backend/structured_memory/session_memory_view.py](/D:/AI应用/langchain-agent/backend/structured_memory/session_memory_view.py) 或其上游把 continuation prose 写进：
   - `active_goal`
   - `active_rule`
   - `current_step`
   - `next_step`
4. [backend/context_management/context_controller.py](/D:/AI应用/langchain-agent/backend/context_management/context_controller.py) 把这类治理 prose 继续塞进 model-visible `active_process_context`

---

## 6. 目标协议

### 6.1 FollowupResolution 的目标结构

`FollowupResolution` 应收口为纯协议对象，只保留：

- `mode`
- `task_id`
- `task_ids`
- `binding_key`
- `confidence`
- `reason`
- `source_query`

必要时可新增：

- `constraints`
- `selection_mode`

### 6.2 mode 语义

- `task_ref`
  - 单个既有 task 的直接续接
- `compound_subset`
  - 从 compound 任务集合中选择子集重组
- `binding_ref`
  - 依赖资源绑定，如 `active_pdf`、`active_dataset`
- `none`
  - 无显式句柄命中，走普通 planner

### 6.3 禁止项

- 不允许 `rewritten_message` 再作为主执行入口
- 不允许 resolver 负责生成新的工作文本

---

## 7. 逐文件实施清单

### 7.1 [backend/query/followup_models.py](/D:/AI应用/langchain-agent/backend/query/followup_models.py)

当前职责：

- 承载 follow-up 解析结果

现存问题：

- `rewritten_message` 让协议结果退化成 prompt 结果

修改要求：

- 删除或废弃 `rewritten_message` 的主路径职责
- 收紧为句柄型结构
- 支持单 task 和多 task 选择

验收标准：

- `FollowupResolution` 本身可以直接驱动 runtime 路由

### 7.2 [backend/query/followup_resolver.py](/D:/AI应用/langchain-agent/backend/query/followup_resolver.py)

当前职责：

- 识别 ordinal task / binding task
- 生成 continuation prose

现存问题：

- 正确命中 task 后又降级成 `rewritten_message`

修改要求：

- 保留 ordinal / binding 解析能力
- 增加多 task subset 解析能力
- 不再返回 continuation prose
- 所有 follow-up 解析仅产出结构化 handle

验收标准：

- “只展开第二个子任务”返回稳定 `task_id`
- “第一个和第三个”返回稳定 `task_ids`
- “刚才那个表 / 那份 PDF”返回 `binding_key + task_id`

### 7.3 [backend/query/runtime.py](/D:/AI应用/langchain-agent/backend/query/runtime.py)

当前职责：

- 主线程执行编排

现存问题：

- follow-up 通过 `effective_message` 回落到 planner-first 路线

修改要求：

- 删除 rewritten-message 主入口
- 将 `_execution_events()` 改成 handle-first 分流：
  - `task_ref` -> 直接 task continuation path
  - `compound_subset` -> 直接 summary subset assembly path
  - `binding_ref` -> 局部重执行 path
  - `none` -> 普通 planner path

具体要求：

- `task_ref` 不重建全量 query plan
- `compound_subset` 不重跑 compound tools
- `binding_ref` 仅影响局部 task execution
- follow-up turn 更新 `MainContextState` 时，只写控制面事实

验收标准：

- “只展开第二个子任务”不再触发 planner 猜路由
- “把第一个和第三个压成一句话”不重跑原 compound 工具链

### 7.4 [backend/query/answer_assembler.py](/D:/AI应用/langchain-agent/backend/query/answer_assembler.py)

当前职责：

- 结果拼接与基础 style 处理

现存问题：

- 更像末端格式器，不像基于句柄的任务重组器

修改要求：

- 输入改成以 `TaskSummaryRef` 为主
- 支持：
  - `task_ids` 子集选择
  - 排除指定 task
  - 每 task 独立 style
  - dedupe
  - 保序

验收标准：

- follow-up answer 直接消费已有 summary/result ref
- 不再依赖混合上下文重新生成

### 7.5 [backend/tasks/models.py](/D:/AI应用/langchain-agent/backend/tasks/models.py)

当前职责：

- TaskRecord 基本数据

现存问题：

- task 还不够像稳定句柄

修改要求：

- 确保每个 task 持有：
  - `task_id`
  - `parent_query_id`
  - `subtask_index`
  - `context_ref`
  - `summary`
  - `result_ref`
  - `bindings`
  - `constraints`
  - `status`

验收标准：

- `subtask_index -> task_id` 映射稳定可追踪

### 7.6 [backend/tasks/context_models.py](/D:/AI应用/langchain-agent/backend/tasks/context_models.py)

当前职责：

- task local context 模型

现存问题：

- bindings / constraints / refs 还未完全作为续接句柄使用

修改要求：

- 明确 task-local truth 的归属边界
- 强化 bindings/constraints/result_ref 的可引用性

验收标准：

- binding follow-up 查询不再依赖 session/process 的文字残影

### 7.7 [backend/tasks/coordinator.py](/D:/AI应用/langchain-agent/backend/tasks/coordinator.py)

当前职责：

- 管理 compound 子任务执行与结果回收

现存问题：

- 结果虽有 summary-first 倾向，但 follow-up 还没有真正按 task handle 消费

修改要求：

- `subtask_end` 产出结构化 summary
- 确保 raw result 留在 ref，不直接灌回主线程
- resolver/runtime 的 task 查询以 coordinator/task registry 为单一来源

验收标准：

- task registry 成为 follow-up 唯一真相来源

### 7.8 [backend/query/context_models.py](/D:/AI应用/langchain-agent/backend/query/context_models.py)

当前职责：

- 主线程 context 建模

现存问题：

- 仍缺少严格的控制面/叙述面边界

修改要求：

- `MainContextState` 只保留：
  - `active_goal`
  - `active_work_item`
  - `followup_target_task_id`
  - `followup_target_task_ids`
  - `active_constraints`
  - `latest_correction`
  - `next_step`

验收标准：

- 单看 `MainContextState` 就能表达当前控制真相

### 7.9 [backend/structured_memory/session_memory.py](/D:/AI应用/langchain-agent/backend/structured_memory/session_memory.py)

当前职责：

- 维护 session 级工作记忆

现存问题：

- 混合恢复索引和治理日志

修改要求：

- 输入改成 summary-first / control-first
- 不再接受 continuation prose 作为事实

验收标准：

- session memory 不再承担 task routing

### 7.10 [backend/structured_memory/session_memory_view.py](/D:/AI应用/langchain-agent/backend/structured_memory/session_memory_view.py)

当前职责：

- 渲染 session memory 视图

现存问题：

- model-visible 与 governance/debug 混杂

修改要求：

- 切成两种视图：
  - `model-visible restore view`
  - `debug/governance view`
- model-visible 只保留恢复事实

验收标准：

- `active_rule`、`current_step` 不再出现 continuation prose

### 7.11 [backend/context_management/context_models.py](/D:/AI应用/langchain-agent/backend/context_management/context_models.py)

当前职责：

- context package 结构

现存问题：

- 还允许治理文本进入 model-visible 路径

修改要求：

- 强化 model-visible/debug-visible 分层
- 为 follow-up handle 注入预留结构化字段

验收标准：

- model-visible sections 由白名单控制

### 7.12 [backend/context_management/context_controller.py](/D:/AI应用/langchain-agent/backend/context_management/context_controller.py)

当前职责：

- context 选层、压缩、输出

现存问题：

- `active_process_context` 和 `hot_truth_window` 在 follow-up 场景中权重过高

修改要求：

- compound follow-up 场景下优先注入：
  - 当前 follow-up target refs
  - 最近 task summaries
  - 当前输出约束
- 降低治理文本和热窗口的 model-visible 权重
- 禁止将 continuation prose、`</think>`、```thinking` 等脏文本送入 model-visible context

验收标准：

- model-visible context 足以支撑 follow-up，但不依赖整段旧对话

### 7.13 [backend/query/prompt_builder.py](/D:/AI应用/langchain-agent/backend/query/prompt_builder.py)

当前职责：

- 构建系统 prompt

现存问题：

- 仍接收过宽的 session/context 视图

修改要求：

- 只注入 model-visible restore facts
- 不注入 governance/debug prose

验收标准：

- prompt 中不再出现 continuation prose

### 7.14 [backend/tests/system_eval/long_runner.py](/D:/AI应用/langchain-agent/backend/tests/system_eval/long_runner.py)

当前职责：

- 长场景 turn 观测与 artifact 输出

现存问题：

- 当前 `plan.route / plan.tool` 是 pre-runtime 视角，容易和真实执行链路混淆

修改要求：

- artifact 增加：
  - `followup_mode`
  - `followup_task_id`
  - `followup_task_ids`
  - `runtime_effective_route`
  - `used_task_summary_refs`

验收标准：

- 测试能区分 planner 预判和 runtime 实际执行

### 7.15 [backend/tests/followup_resolution_regression.py](/D:/AI应用/langchain-agent/backend/tests/followup_resolution_regression.py)

修改要求：

- 增加：
  - ordinal task 命中断言
  - multi-task subset 命中断言
  - binding task 命中断言
  - resolver 不产出 continuation prose 断言

### 7.16 [backend/tests/task_coordinator_regression.py](/D:/AI应用/langchain-agent/backend/tests/task_coordinator_regression.py)

修改要求：

- 增加：
  - task registry 成为 follow-up 真相来源的断言
  - raw result 不进入 main context 的断言

---

## 8. 分阶段执行顺序

### Phase 1：协议收口

先改：

- `followup_models.py`
- `followup_resolver.py`

目标：

- `rewritten_message` 退出主路径
- FollowupResolution 成为纯句柄协议

### Phase 2：runtime 改为 handle-first

再改：

- `runtime.py`
- `answer_assembler.py`

目标：

- follow-up 直接按 task/binding handle 走
- subset follow-up 直接装配已有 summaries

### Phase 3：task registry 成为单一真相来源

再改：

- `tasks/models.py`
- `tasks/context_models.py`
- `tasks/coordinator.py`

目标：

- task_id / bindings / result_ref 稳定可追踪

### Phase 4：主线程去 prose 污染

再改：

- `context_models.py`
- `session_memory.py`
- `session_memory_view.py`
- `context_controller.py`
- `prompt_builder.py`

目标：

- 主线程和 model-visible context 不再吸收 continuation prose

### Phase 5：测试与观测补强

最后改：

- `long_runner.py`
- `followup_resolution_regression.py`
- `task_coordinator_regression.py`

目标：

- 能稳定验证本轮修复没有回退

---

## 9. 本轮硬性禁止项

- 不准再靠 prompt 改写兜底
- 不准新增 continuation marker heuristic
- 不准让 session memory 承担 task routing
- 不准让 debug/worklog/governance prose 继续成为 model-visible truth
- 不准让 compound follow-up 无必要重跑整条工具链

---

## 10. 验收标准

本轮最终必须满足：

1. “只展开第二个子任务”直接按第二个 `task_id` 输出，不重跑 planner 猜路由
2. “把第一个和第三个子任务各压成一句话，不要重复第二个”直接按 `task_ids=[1,3]` 装配
3. 主线程状态里不再出现“延续之前的子任务……”这类 continuation prose
4. `session_memory.model_preview` 不再像工作日志
5. `context_slots.active_rule` 不再被 continuation prose 污染
6. 长场景 artifact 可以清楚显示 follow-up 是按句柄续接，而不是按文本续接

---

## 11. 与现有文档的关系

- [docs/32-Claude式记忆召回与主线程去污逐文件执行清单.md](/D:/AI应用/langchain-agent/docs/32-Claude式记忆召回与主线程去污逐文件执行清单.md)
  - 关注记忆召回和主线程去污
- [docs/33-Claude式结构化数据绑定修复计划书.md](/D:/AI应用/langchain-agent/docs/33-Claude式结构化数据绑定修复计划书.md)
  - 关注结构化数据绑定问题
- 本文档
  - 专注解决 `compound follow-up` 从文本续接退化为句柄续接的问题

这三份文档的边界要保持清晰：本轮以 follow-up handle continuity 为主，不把范围再次扩成整轮 memory/context 重构。
