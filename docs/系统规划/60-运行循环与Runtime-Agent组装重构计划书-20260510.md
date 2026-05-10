# 运行循环与 Runtime Agent 组装重构计划书

日期：2026-05-10

## 目标

把当前 `QueryRuntime -> AgentRuntimeChainAssembler -> TaskRunLoop` 这条运行主链，从“入口可运行、装配分散、图任务路径存在隐性断点”的状态，重构为一套职责清晰、状态真实、可恢复、可验证的 Agent 运行循环系统。

本计划只讨论计划与实施边界，不直接修改代码。

本次重构关注四个核心目标：

1. 修复图任务 runtime 组装路径中的确定性错误。
2. 让显式任务选择、能力识别、图任务装配共享同一份运行真相。
3. 取消 runtime start 阶段的空图占位 dispatch plan，只记录真实编排状态。
4. 修复会话 turn / task 实例 ID 的并发生成风险，避免事件流和 task run 关联被污染。

---

## 一、现状总览

当前一次用户请求的主链大致是：

```text
QueryRuntime.astream()
  -> 读取 session / history
  -> 生成 turn_id / task_id
  -> commit 用户消息
  -> AgentRuntimeChainAssembler.build_runtime()
      -> 理解用户意图
      -> 显式任务选择对齐
      -> 组装 memory / task / capability / orchestration bundle
  -> TaskRunLoop.run_single_agent_stream()
      -> TaskRunLoop.start()
      -> 写入 task_run / agent_run / coordination_run
      -> 构造 runtime directive
      -> 执行模型与工具循环
      -> 写入事件、checkpoint、结果
```

相关主要文件：

- `backend/query/runtime.py`
- `backend/orchestration/agent_runtime_chain.py`
- `backend/orchestration/runtime_loop/task_run_loop.py`
- `backend/orchestration/runtime_loop/checkpoint.py`
- `backend/orchestration/runtime_loop/state_index.py`
- `backend/tasks/assembly_builder.py`
- `backend/tasks/assembly_support.py`
- `backend/tasks/flow_registry.py`
- `backend/tasks/task_graph_models.py`

---

## 二、已确认问题

### 1. 图任务路径存在确定性运行错误

位置：

- `backend/orchestration/runtime_loop/task_run_loop.py`
- `_sync_runtime_objects_after_task_contract()`

当前在创建 `CoordinationRun` 时使用了：

```python
task_graph_payload.get("graph_id")
```

但该函数入参和局部作用域中没有 `task_graph_payload`，只有 `graph_payload`。

影响：

1. 一旦命中 `graph_payload` 非空的图任务路径，运行时对象同步可能直接 `NameError`。
2. 这个错误发生在 `start()` 之后，意味着 task run / agent run 可能已经被写入，随后中断，留下半初始化运行状态。
3. 这会让调试结果表现为“任务已经开始，但编排对象没有完整落盘”。

结论：

这是必须优先修复的 P0 级 runtime 组装错误。

### 2. 显式任务选择会清空能力上下文

位置：

- `backend/orchestration/agent_runtime_chain.py`
- `_align_understanding_with_explicit_task_selection()`

当前显式选择任务后，会强制重写理解结果：

```text
route = agent
execution_posture = task_runtime
preferred_skill = None
skill_name = None
tool_name = None
capability_requests = []
candidate_tools = []
tool_input = {"selected_task_id": selected_task_id}
should_skip_rag = True
```

影响：

1. 用户消息里原本被识别出的 Skill / Tool / MCP 需求被清空。
2. Runtime assembly 只能靠任务元数据重新推断能力，而不是继承理解层已经拿到的信号。
3. 显式任务选择变成“覆盖理解结果”，而不是“锁定任务资产并保留能力需求”。

结论：

显式任务选择应该只锁定任务或图资产，不应该抹掉能力候选。能力候选应进入 runtime assembly，由授权层和任务图约束继续过滤。

### 3. `turn_id` / `task_id` 生成存在并发碰撞风险

位置：

- `backend/query/runtime.py`
- `QueryRuntime.astream()`

当前逻辑：

```text
读取 session messages
turn_index = len(messages) + 1
turn_id = turn:{session_id}:{turn_index}
task_id = taskinst:{turn_id}:{suffix}
再 commit 用户消息
```

影响：

1. 同一个 session 下两个请求并发进入时，可能读到相同 messages 长度。
2. 两个请求会生成相同 `turn_id` 和相同前缀的 `task_id`。
3. 下游 trace、event log、runtime state、checkpoint 都可能被错误关联。

结论：

turn / task instance ID 不能依赖“提交前的历史消息数量”。必须改为提交事务返回的单调 turn 序号，或使用 UUID / ULID 作为运行实例 ID。

### 4. `TaskRunLoop.start()` 会写入空图 dispatch plan

位置：

- `backend/orchestration/runtime_loop/task_run_loop.py`
- `TaskRunLoop.start()`

当前只要 `resolved_graph_ref` 存在，就会在 `start()` 阶段调用：

```text
_compile_agent_dispatch_plan_from_graph_payload(
  graph_payload={},
  topology_template_payload={}
)
```

随后写入 `agent_dispatch_plan_compiled` 事件。

影响：

1. event log 中出现一份没有真实图节点、没有真实拓扑的 dispatch plan。
2. 后续同步阶段会再次基于真实 `graph_payload` 编译 dispatch plan，造成同一 task run 内存在两份语义不同的 plan。
3. 调试、恢复、前端可视化如果消费了早期 plan，会看到错误的编排状态。

结论：

`start()` 只允许写入已知真实状态。dispatch plan 必须在 graph payload 和 topology payload 都可用后生成。

---

## 三、设计原则对齐

本次重构严格参照 `docs/设计原则` 中与运行循环、任务系统、工具系统、权限系统相关的原则。

### 1. 对话循环：AsyncGenerator 是状态机边界

来自：

- `docs/设计原则/05-对话循环.md`

约束：

1. 运行循环应持续产出真实事件，而不是占位事件。
2. 每次 continue / retry / tool result / terminal 都必须有明确 transition。
3. 恢复路径不能反复覆盖当前轮的真实状态。

落地到本项目：

`TaskRunLoop` 应把 `start`、`assemble`、`dispatch`、`execute`、`checkpoint` 拆成可追踪阶段，每个阶段只写自己已经确定的事实。

### 2. 任务系统：任务生命周期和状态隔离

来自：

- `docs/设计原则/14-任务系统.md`

约束：

1. task run / agent run / coordination run 必须有清晰生命周期。
2. 子任务或图节点失败不应污染其他运行对象。
3. kill / resume / checkpoint 的状态来源必须稳定。

落地到本项目：

图任务不应在 `start()` 阶段先伪造 coordination dispatch。应先创建 task run，再在 graph assembly 成功后创建真实 coordination runtime objects。

### 3. 工具注册表：单一来源 + 分层过滤

来自：

- `docs/设计原则/09-工具系统设计.md`
- `docs/设计原则/25-架构模式总结.md`

约束：

1. 能力候选来自能力注册层和统一候选入口。
2. 过滤可以分层，但注册真相不能分散。
3. 默认保守，但不能用静默清空替代授权判断。

落地到本项目：

显式任务选择不应该清空 `candidate_tools` / `capability_requests`。正确方式是把它们带入 assembly，再由任务图、Agent runtime profile、OperationGate 逐层过滤。

### 4. 权限系统：运行授权独立于识别结果

来自：

- `docs/设计原则/16-权限系统.md`

约束：

1. “识别出可能需要某能力”不等于“允许执行该能力”。
2. deny / allow / ask 应作为运行授权层处理。
3. 权限判断失败要进入 diagnostics，而不是静默退化。

落地到本项目：

能力上下文应该保留到 runtime assembly；执行前由 `allowed_operations`、`blocked_operations`、tool policy 和 MCP policy 判定是否可用。

---

## 四、目标架构

### 1. 固定主链

目标主链：

```text
QueryRuntime
  -> TurnAllocator
      产出唯一 turn_id / task_instance_id
  -> InputCommitGate
      写入用户消息并返回 commit ref
  -> AgentRuntimeChainAssembler
      产出 RuntimeAssembly
        - selected_task_ref
        - selected_graph_ref
        - understanding_frame
        - capability_candidates
        - authorization_candidates
        - memory_runtime_view
        - orchestration_bundle
  -> TaskRunLoop.start()
      只创建 task_run / primary agent_run
  -> TaskRunLoop.bind_runtime_assembly()
      根据 RuntimeAssembly 创建真实 graph / coordination / dispatch runtime objects
  -> TaskRunLoop.execute()
      模型、工具、MCP、checkpoint、结果提交
```

### 2. 固定职责边界

#### QueryRuntime

职责：

- API 输入适配
- 唯一 turn / task instance ID 分配
- 用户消息提交
- 启动 runtime loop
- 向前端流式输出事件

禁止：

- 根据消息数量直接生成可碰撞 ID
- 在入口层决定能力候选
- 在入口层伪造任务图运行状态

#### AgentRuntimeChainAssembler

职责：

- 汇总理解结果
- 合并显式任务选择
- 保留能力候选
- 构造 runtime assembly
- 输出运行时装配诊断

禁止：

- 因为选择了任务就清空能力候选
- 把 `SpecificTaskRecord` 当作图任务的唯一运行真相
- 静默吞掉 skill policy / tool policy 的失败原因

#### TaskRunLoop

职责：

- 维护 task run 生命周期
- 创建真实 agent run / coordination run / dispatch plan
- 执行模型和工具循环
- 写入 event log / checkpoint / state index

禁止：

- 用空 payload 编译正式 dispatch plan
- 在 graph payload 不完整时写入“已编译”的编排事件
- 在一个函数里同时承担 start、assembly bind、execute、finalize 的全部职责

#### RuntimeAssembly

职责：

- 成为 runtime loop 消费的唯一装配入口。
- 保存任务、图、能力、授权、记忆、编排的稳定 refs。

禁止：

- 同一份事实同时散落在 `task_selection`、`query_understanding`、`task_operation`、`graph_payload`、`diagnostics` 里。

---

## 五、关键概念口径

### 1. 特定任务

`SpecificTaskRecord` 是业务任务定义或任务资源。

它可以描述一个任务要做什么、属于哪个任务族群、有哪些元数据，但不应该作为 runtime 图编排的唯一主入口。

### 2. 图任务

`TaskGraphDefinition` 是图编排资产。

它负责描述节点、边、拓扑、协调策略、worker 绑定和输出契约。运行时的 coordination / dispatch 应以图任务为核心。

### 3. Runtime Assembly

`RuntimeAssembly` 是当前请求进入 runtime loop 前的定稿对象。

它不是 UI 展示结构，也不是临时 diagnostics，而是 runtime loop 后续执行、恢复、观测的主输入合同。

### 4. Capability Candidates

能力候选表示“本轮可能需要这些 skill / tool / MCP”。

它不等于授权结果。授权结果由 runtime profile、operation allow / block、tool policy、MCP policy 决定。

---

## 六、实施计划

### 阶段一：Runtime 组装错误修复与防回归

目标：

- 修复图任务路径中的确定性崩溃。
- 增加最小回归测试，证明图任务 payload 能成功创建 coordination runtime object。

涉及文件：

- `backend/orchestration/runtime_loop/task_run_loop.py`
- `backend/tests/*runtime*graph*` 或新增 runtime loop 回归测试文件

实施要点：

1. 将 `_sync_runtime_objects_after_task_contract()` 中的 `task_graph_payload` 错误引用收敛为 `graph_payload`。
2. 明确 `graph_ref` 的取值优先级：
   - `graph_payload.graph_id`
   - `graph_payload.task_graph_id`
   - `start_result` 已解析 graph ref
3. 增加测试覆盖：
   - `graph_payload` 非空时不抛异常
   - `CoordinationRun.graph_ref` 正确
   - `AgentRun.role` 正确变为 `coordinator`

完成标准：

- 图任务路径不再因未定义变量中断。
- 失败时有清晰 diagnostics，而不是半初始化静默残留。

### 阶段二：Turn / Task Instance ID 分配收口

目标：

- 消除同 session 并发请求下 `turn_id` / `task_id` 碰撞。

涉及文件：

- `backend/query/runtime.py`
- session manager 相关文件
- runtime commit gate 相关测试

实施要点：

1. 新增或复用一个 turn allocator：
   - 方案 A：用户消息 commit 时返回单调 turn index。
   - 方案 B：运行实例使用 UUID / ULID，turn index 仅作为展示序号。
2. `task_id` 不再直接依赖提交前的 `len(messages)`。
3. trace metadata 同时记录：
   - `turn_id`
   - `task_instance_id`
   - `input_commit_ref`

完成标准：

- 两个并发请求不会生成相同 runtime task id。
- 测试能模拟同 session 并发入口。

### 阶段三：显式任务选择与能力上下文分离

目标：

- 显式任务选择只锁定任务资产，不再覆盖能力候选。

涉及文件：

- `backend/orchestration/agent_runtime_chain.py`
- `backend/understanding/task_understanding.py`
- `backend/capability_system/skill_policy.py`
- `backend/capability_system/tool_registry.py`
- `backend/tasks/assembly_builder.py`

实施要点：

1. 将 `_align_understanding_with_explicit_task_selection()` 改为“增强结构信号”：
   - 保留 `selected_task_id`
   - 保留原始 `capability_requests`
   - 保留原始 `candidate_tools`
   - 保留 `preferred_skill` / `tool_name`，除非任务图明确禁止
2. 新增明确字段：
   - `selected_task_ref`
   - `selected_graph_ref`
   - `task_selection_reason`
   - `selection_is_user_explicit`
3. 能力候选进入 runtime assembly，由授权层过滤。

完成标准：

- 显式选择任务后，理解层能力候选仍可进入 assembly。
- 如果能力被禁止，diagnostics 显示“识别到了，但授权拒绝”，而不是直接消失。

### 阶段四：RuntimeAssembly 成为唯一运行装配合同

目标：

- 把任务、图、能力、授权、记忆、编排的运行输入收敛为单一结构。

涉及文件：

- `backend/tasks/assembly_builder.py`
- `backend/tasks/assembly_support.py`
- `backend/orchestration/agent_runtime_chain.py`
- `backend/orchestration/runtime_loop/runtime_assembly_models.py`
- `backend/orchestration/runtime_loop/task_run_loop.py`

实施要点：

1. 明确 `RuntimeAssembly` 必含：
   - `assembly_id`
   - `task_instance_ref`
   - `selected_task_ref`
   - `selected_graph_ref`
   - `capability_candidates`
   - `authorized_operations`
   - `blocked_operations`
   - `memory_runtime_view`
   - `orchestration_bundle`
2. Runtime loop 只消费 `RuntimeAssembly`，不再到处读取散落的 `task_selection`、`diagnostics`、`task_operation`。
3. assembly builder 负责把旧输入折叠到新合同里。

完成标准：

- `TaskRunLoop` 的启动输入能通过一个 assembly payload 解释清楚。
- diagnostics 只记录诊断，不再承载主流程真相。

### 阶段五：取消空图 dispatch plan

目标：

- event log 中只出现真实 dispatch plan。

涉及文件：

- `backend/orchestration/runtime_loop/task_run_loop.py`
- `backend/orchestration/runtime_loop/trace_reader.py`
- 相关前端运行态展示读取逻辑，如存在

实施要点：

1. `TaskRunLoop.start()` 不再调用空 payload 的 `_compile_agent_dispatch_plan_from_graph_payload()`。
2. 当 graph payload / topology payload 准备完成后，统一在 `bind_runtime_assembly` 或 `_sync_runtime_objects_after_task_contract()` 阶段编译 dispatch plan。
3. 事件命名明确：
   - `runtime_assembly_bound`
   - `coordination_run_created`
   - `agent_dispatch_plan_compiled`
4. 如果图 payload 缺失，只写 `coordination_pending_graph_payload` 或 failure diagnostics，不写 compiled。

完成标准：

- 同一个 task run 不再出现空图 plan 和真实 plan 两套事实。
- trace reader 读取到的第一份 dispatch plan 就是真实可执行计划。

### 阶段六：RuntimeLoop 分层整理

目标：

- 降低 `TaskRunLoop` 单文件过大造成的维护风险。

涉及文件：

- `backend/orchestration/runtime_loop/task_run_loop.py`
- 可新增：
  - `backend/orchestration/runtime_loop/runtime_start.py`
  - `backend/orchestration/runtime_loop/runtime_assembly_binding.py`
  - `backend/orchestration/runtime_loop/dispatch_plan_compiler.py`
  - `backend/orchestration/runtime_loop/runtime_finalizer.py`

实施要点：

1. 先抽纯函数和无状态 builder。
2. 再抽 start / bind / execute / finalize 阶段对象。
3. 不在同一阶段混入行为变化和文件搬迁。

完成标准：

- `TaskRunLoop` 保留主流程编排职责。
- dispatch plan 编译、runtime object 绑定、finalize 分别可单测。

---

## 七、固定执行流

实施完成后的固定执行流：

```text
1. QueryRuntime 接收请求
2. TurnAllocator 生成唯一 turn_id / task_instance_id
3. CommitGate 写入用户消息
4. AgentRuntimeChainAssembler 生成 RuntimeAssembly
5. TaskRunLoop.start 创建 task_run + primary agent_run
6. TaskRunLoop.bind_runtime_assembly 绑定真实任务图、能力授权、记忆视图
7. 如果是图任务，创建 coordination_run 并编译真实 dispatch plan
8. Runtime loop 执行模型 / 工具 / MCP
9. 每轮写入 event log 和 checkpoint
10. finalize 写入结果、状态、assistant message commit
```

禁止出现的路径：

1. 根据 session message 长度生成唯一运行 ID。
2. 显式任务选择后清空能力候选。
3. graph payload 缺失时写入 `agent_dispatch_plan_compiled`。
4. diagnostics 字段承载主流程真相。
5. `SpecificTaskRecord` 代替 `TaskGraphDefinition` 成为图编排运行源。

---

## 八、测试与验证矩阵

### 1. 单元测试

覆盖：

- `turn_id` / `task_id` 唯一性
- 显式任务选择后能力候选保留
- graph payload 创建 coordination run
- dispatch plan 只在真实 graph payload 下生成
- 授权拒绝进入 diagnostics

### 2. 集成测试

覆盖：

- 普通聊天任务
- 显式选择普通任务
- 显式选择图任务
- 图任务 + skill
- 图任务 + tool
- 图任务 + MCP
- 能力被 allow
- 能力被 block
- 并发同 session 两个请求

### 3. 回归测试

建议命令：

```bash
python -m pytest backend/tests/runtime_commit_gate_regression.py backend/tests/runtime_assembly_builder_test.py backend/tests/orchestration_cutover_regression.py -q
```

如新增测试，命名建议：

```text
backend/tests/runtime_loop_graph_assembly_regression.py
backend/tests/query_runtime_turn_allocator_regression.py
backend/tests/explicit_task_capability_context_regression.py
```

### 4. 手工验证

验证场景：

1. 在前端选择一个图任务并运行。
2. 检查事件流中是否只有真实 dispatch plan。
3. 检查 runtime diagnostics 是否包含 selected graph、capability candidates、authorization result。
4. 并发提交两条同 session 消息，确认 task run 不串线。

---

## 九、迁移与切换规则

### 1. 迁移原则

1. 先修确定性 bug，再收束结构。
2. 先让新 assembly 可被 runtime 消费，再清理旧字段。
3. 旧字段只允许作为输入兼容，不允许继续作为 runtime 主真相。

### 2. 切换顺序

```text
修复图任务作用域错误
-> 引入唯一 turn/task instance 分配
-> 显式任务选择保留能力上下文
-> RuntimeAssembly 承接任务 / 图 / 能力 / 授权
-> TaskRunLoop 只消费 RuntimeAssembly
-> 删除空 dispatch plan
-> 清理旧 diagnostics 主流程字段
```

### 3. 回滚规则

每阶段都要能单独回滚：

1. 阶段一只修 bug，不改变协议。
2. 阶段二只改变 ID 分配，保留展示 turn index。
3. 阶段三保留旧字段，但新增能力上下文保留。
4. 阶段四开始前必须有完整测试，否则不进入切换。
5. 阶段五移除空 dispatch plan 前，确认没有前端或 trace reader 依赖该占位事件。

---

## 十、文件级执行清单

### `backend/query/runtime.py`

- 新增或接入 turn allocator。
- `task_id` 改为基于唯一 task instance ref。
- trace metadata 增加 commit ref。

### `backend/orchestration/agent_runtime_chain.py`

- 改造 `_align_understanding_with_explicit_task_selection()`。
- 显式任务选择只增加 selection frame，不清空能力候选。
- 将 capability candidates 写入 runtime assembly。

### `backend/tasks/assembly_builder.py`

- 明确 RuntimeAssembly 输出合同。
- 合并 selected task / selected graph / capability / authorization。
- 清理 legacy adoption plan 的主流程地位。

### `backend/tasks/assembly_support.py`

- 提供 graph ref、task ref、capability ref 的规范化工具。
- 避免各层重复解析任务选择结构。

### `backend/orchestration/runtime_loop/runtime_assembly_models.py`

- 补齐 RuntimeAssembly 数据模型。
- 明确哪些字段是主流程合同，哪些是 diagnostics。

### `backend/orchestration/runtime_loop/task_run_loop.py`

- 修复 `task_graph_payload` 未定义问题。
- 删除空图 dispatch plan 写入。
- 分离 start / bind assembly / execute / finalize。

### `backend/orchestration/runtime_loop/trace_reader.py`

- 适配真实 dispatch plan 事件。
- 不再把空 plan 当成有效编排状态。

### `backend/orchestration/runtime_loop/state_index.py`

- 检查 task run / agent run / coordination run 多对象写入顺序。
- 后续可引入批量写入或一致性校验。

### `backend/orchestration/runtime_loop/checkpoint.py`

- 确认 checkpoint 中保存真实 runtime assembly ref 和 dispatch plan ref。
- 后续评估是否保留阶段快照，而不只是 latest checkpoint。

---

## 十一、完成标准

本次重构完成后，应满足：

1. 图任务路径不会因 runtime object 同步直接崩溃。
2. 显式任务选择不会抹掉能力识别结果。
3. event log 不再出现空图 dispatch plan。
4. 同 session 并发请求不会生成相同 task instance。
5. RuntimeAssembly 成为 runtime loop 的唯一装配入口。
6. `SpecificTaskRecord` 和 `TaskGraphDefinition` 的边界清晰：
   - 特定任务是业务任务资源。
   - 图任务是编排运行资产。
7. 能力识别、运行授权、图编排分别有清晰职责，不互相吞并真相。

---

## 十二、非目标

本计划不包含：

1. 前端 UI 重构。
2. 新增能力注册字段。
3. RAG 主链重构。
4. MCP 协议实现重写。
5. 大规模数据库迁移。
6. 重新定义所有任务模板。

这些可以在 runtime 主链稳定后再分别处理。

