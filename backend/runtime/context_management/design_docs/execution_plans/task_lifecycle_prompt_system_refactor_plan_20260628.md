# Turn 生命周期与长任务资源反射体系重构设计书

## 0. 文档状态

状态：等待用户审阅后再实施。

本文替代上一版“任务生命周期提示词体系”文档。

上一版的问题是：仍然把 task 当成一套需要 agent 阅读和理解的生命周期说明。这个方向不对。

本版的核心修正：

- 生命周期属于 `turn`，不是 task prompt。
- agent 不应该感到自己进入了一个“任务模式生命周期”。
- `TaskRun` 是 agent 通过控制动作向系统开启的一段长任务运行资源。
- 任务模式真正考验的是系统能力：资源分配、状态持久化、恢复、投影、预算、暂停、收口和验收。
- task 在 agent prompt 中只表现为系统投射进 turn 的持续工作状态、边界、游标和验收压力。
- 提示词不应该写成开发说明，而应该像神经系统反射一样，在 turn 的关键时刻触发 agent 的注意、动作选择和状态回写。
- `request_task_run` 不是普通工具，也不是语义解释；它是 turn 中的一个控制反射：当当前工作需要长任务资源时，agent 向控制系统发出启动信号。

一句话定义：

> TaskRun 是系统资源；task 不是另一条 agent 生命周期；task 在 prompt 中只是 turn 生命周期里的持续状态反射。

## 1. 正确关系

### 1.1 Turn 是唯一生命周期

每一次模型运行都只能处在一个 turn 生命周期中。

一个 turn 的真实生命周期是：

```text
接收输入
→ 定向当前工作
→ 选择动作
→ 执行工具或控制动作
→ 吸收观察结果
→ 写回状态
→ 回复、继续或收口
```

task 不应该新增第二套：

```text
启动任务
→ 任务模式思考
→ 任务模式执行
→ 任务模式回复
```

这会让 agent 学到两套心智模型，也会让 runtime 出现两套执行路径。

### 1.2 TaskRun 是系统资源，task 投影是 turn 反射输入

系统可以有 `TaskRun` 这个持久对象，但它的本质不是 agent 的新心智模式，而是控制系统分配给长任务运行的一段资源。

系统负责这段资源的生命周期：

- 分配任务身份和运行资源；
- 绑定当前 turn 或后续 turn；
- 持久化目标、范围、计划、todo、恢复点和验收边界；
- 控制暂停、恢复、替换、停止和收口；
- 在每个 turn 开始前投影当前任务状态；
- 在每个 turn 结束后接收状态写回。

agent 负责的是：

- 在 turn 中判断是否需要申请这段资源；
- 通过 `request_task_run` 发出明确控制信号；
- 在后续 turn 中读取系统投影；
- 按当前目标、游标和验收压力继续行动；
- 必要时发出更新、转向、暂停、收口等控制动作。

因此，agent-facing prompt 不能把 `TaskRun` 写成另一种执行生命周期。

对 agent 来说，task 只表现为：

- 本 turn 是否绑定持续工作；
- 当前目标是什么；
- 当前边界是什么；
- 当前 active step 是什么；
- todo 游标在哪里；
- 这轮完成后需要更新什么状态；
- 是否已经达到验收；
- 是否需要暂停、恢复、转向或收口。

也就是说，`TaskRun` 在系统侧是长任务资源；task 在 prompt 侧是一组投射到 turn 神经反射里的状态，不是一个要 agent 进入的容器。

### 1.3 Prompt 是反射，不是说明书

给 agent 的 prompt 不应该说：

```text
这是任务生命周期覆盖层。
系统会将 TaskRun 注入 turn。
你需要根据 task overlay 更新状态。
```

应该说：

```text
先确认本 turn 是否已经绑定持续工作。
如果已经绑定，先沿当前目标和 active step 推进。
不要丢掉 todo 游标。
如果本轮改变了计划、范围或完成状态，结束前写回。
如果已经满足验收条件，收口任务。
```

这才是 agent 能直接执行的神经反射。

## 2. 当前体系的问题

### 2.1 它把 task 写成了第二套生命周期

当前提示词里存在 `task mode`、`task_execution`、`TaskStartIntent`、tail context、repair template 等多套说法。

问题不只是词不准，而是这些说法给了 agent 错误暗示：

- 普通 turn 是一种工作；
- task 是另一种工作；
- 启动任务后要进入另一套执行语义。

目标体系必须反过来：

- 永远只有 turn 在执行；
- task 只改变 turn 内部的注意方向和状态压力；
- agent 每轮仍然按普通 turn 做判断、调用工具、回复用户。

### 2.2 它让 agent 读开发意图，而不是触发行动

例如：

```text
当你判断当前目标需要跨多步执行、可恢复状态、阶段反馈...
```

这句话不是错，但它太像设计说明。agent 读完后仍然要自己翻译成“我现在应该做什么”。

反射式写法应该直接压到动作上：

```text
如果这件事不能在本 turn 稳定完成，并且后续需要保存目标、步骤、todo、恢复点或验收边界，发出 request_task_run。
只提交可执行合同，不解释动机。
```

### 2.3 它把合同字段变成了概念教学

`entry_reason` 是典型错误。系统不需要 agent 解释“为什么要进入任务”，系统需要可执行状态：

- 要承载什么；
- 下一步是什么；
- 看哪些对象；
- 怎么验收；
- 是否需要 todo 游标；
- 当前形态是调查、恢复、监控还是普通推进。

合同字段必须是系统可消费的状态，不是人类可读的辩护。

### 2.4 它没有把 task 状态放进 turn 反射点

真正重要的不是“给 agent 看一段任务说明”，而是在 turn 关键点触发：

- turn 开始时：先定向当前任务；
- 动作选择前：判断是继续、启动、转向还是收口；
- 工具结果后：吸收观察并更新任务状态；
- 回复前：检查验收和 todo 游标；
- 失败时：留下恢复点。

如果 prompt 没有嵌到这些反射点，agent 就会把任务当成背景信息，而不是行动约束。

## 3. 目标模型：Turn Reflex Loop

目标不再叫“任务生命周期 prompt”。

目标叫：

```text
Turn Reflex Loop
```

它把一个 turn 分成六个反射点。

```text
Turn Start
→ Orient Reflex
→ Action Reflex
→ Observation Reflex
→ Commit Reflex
→ Response Reflex
```

task 只在这些点上施加状态压力。

本文只修正 turn 生命周期和提示词反射关系。

具体任务系统如何分配资源、保存状态、恢复运行、调度预算、处理暂停/恢复/收口，是下一份任务系统设计书要解决的问题。这里不能把系统资源设计偷换成 agent prompt 说明。

## 4. 六个反射点

### 4.1 Turn Start：进入本轮

目的：

- 不让 agent 先入为主地把用户新消息当成孤立请求；
- 先确认本轮是否存在 active task；
- 如果没有 active task，再判断是否普通完成或启动任务。

agent-facing prompt：

```text
每个 turn 开始时，先确认当前是否绑定持续工作。

如果没有绑定：
- 能在本 turn 完成的，直接完成；
- 需要系统分配长任务资源来保存目标、步骤、todo、恢复点或验收边界的，选择 request_task_run。

如果已经绑定：
- 先沿当前任务目标、active step 和 todo 游标定向；
- 用户的新消息如果是在调整当前任务，按转向处理；
- 用户的新消息如果明确开启无关目标，先处理边界，不要悄悄丢掉当前任务。
```

### 4.2 Orient Reflex：定向当前工作

目的：

- 把动态状态压到 agent 注意力最前面；
- 不是解释任务系统，而是告诉 agent 此刻该看哪里。

位置：

- volatile tail；
- 靠近 prompt 最后；
- 每 turn 更新；
- 不进入稳定缓存。

格式：

```text
Turn Reflex Index

当前 turn 绑定持续工作。
先按这个索引定向，再选择动作。

task_run_id: <id>
目标: <task_objective>
当前契约: <goal | plan, one-line>
当前形态: <standard | investigation | recovery | monitor | open_work, one-line>
当前步骤: <active step or none>
todo 游标: <active todo / next todo / none>
范围: <focus refs, exclusions, constraints>
验收焦点: <done criteria focus>
恢复点/阻塞点: <handle or none>
用户最新转向: <pending steer or none>
```

无 active task 时：

```text
Turn Reflex Index

当前 turn 没有绑定持续工作。
直接完成本轮请求；如果需要持续承载，并且 request_task_run 可用，发出 request_task_run。
```

### 4.3 Action Reflex：选择动作

目的：

- 让 agent 在动作选择时自动考虑任务控制；
- 不靠系统猜语义；
- 不把任务合同写进普通回复。

agent-facing prompt：

```text
选择动作前，先判断当前工作是否需要系统分配长任务资源。

如果不需要，继续普通工具调用或直接回复。

如果需要长任务资源，并且 request_task_run 可用，发出 request_task_run。
request_task_run 是控制动作，不是给用户看的说明。
不要把任务合同写进普通自然语言回复。
```

`request_task_run` 触发条件要写成动作判断，而不是抽象概念：

```text
当至少一个条件成立时，选择 request_task_run：
- 工作无法在本 turn 稳定完成，并且后续还要继续；
- 需要系统保存目标、计划、todo 游标、恢复点或验收边界；
- 需要跨 turn 接收阶段反馈或用户转向；
- 失败后需要保留恢复点继续；
- 需要持续观察目标直到触发停止条件。
```

### 4.4 Control Signal Reflex：启动持续承载

目的：

- `request_task_run` 是 turn 内的控制信号；
- strict tool/function calling 是这个信号的结构化通道；
- 合同字段必须是系统状态，不是解释文字。

agent-facing prompt：

```text
request_task_run 表示：请控制系统为这项工作开启一段长任务资源，并从下一步开始持续承载。

只提交可执行合同：
- task_objective：要持续承载并最终验收的目标；
- primary_mode：goal 或 plan；
- task_shape：standard、investigation、recovery、monitor 或 open_work；
- minimum_viable_next_step：任务接受后的第一步；
- working_scope：当前必须关注和排除的对象；
- acceptance：完成标准和最终回复要求；
- mode_payload：goal_contract 或 plan_contract；
- shape_payload：当前形态所需的最小信息；
- todo_tool_contract：只有需要清单、状态或 active item 时填写。

不要填写 entry_reason。
不要把 todo 写成 primary_mode。
不要让 investigation、recovery、monitor 或 open_work 代替 goal / plan。
```

### 4.5 Observation Reflex：工具结果后吸收状态

目的：

- 工具调用后，agent 不只是“继续回答”，还要检查观察结果是否改变任务状态。

agent-facing prompt：

```text
每次拿到工具结果后，先判断它是否改变当前任务。

如果它完成了当前步骤，推进 active step。
如果它完成、新增或取消了事项，更新 todo。
如果它改变了范围，更新 working_scope。
如果它暴露失败，记录阻塞点和下一恢复动作。
如果它满足验收条件，准备收口。
```

### 4.6 Commit Reflex：本轮结束前写回

目的：

- 状态更新不应该只藏在自然语言里；
- task 状态必须在 turn 结束前被提交。

agent-facing prompt：

```text
本 turn 结束前，检查是否需要写回持续工作状态。

需要写回的，只写必要变化：
- 当前步骤；
- todo 游标；
- 新约束或范围变化；
- 验收进度；
- 阻塞点；
- 下一恢复动作；
- 是否完成或暂停。

不要重复写完整历史。
```

### 4.7 Response Reflex：回复或收口

目的：

- final answer 不是脱离 task 的普通总结；
- 如果任务完成，要按 acceptance 收口；
- 如果没完成，要说明当前状态和下一步。

agent-facing prompt：

```text
回复用户前，检查验收条件。

如果已经满足 acceptance，收口任务，并按最终回复要求回答。
如果还没满足，但本轮有进展，说明当前进展和下一步。
如果被阻塞，说明阻塞点、已保留的恢复动作，以及需要什么外部输入。
不要把未完成的任务说成已经完成。
```

## 5. 合同不再是“任务模式说明”

`TaskStartIntent` 只是 `request_task_run` 的控制信号载荷。

它不应该教 agent 理解系统架构，只负责让系统分配长任务资源、绑定持续状态，并准备后续 turn 投影。

目标结构：

```text
TaskStartIntent
├─ task_objective
├─ primary_mode: goal | plan
├─ task_shape: standard | investigation | recovery | monitor | open_work
├─ minimum_viable_next_step
├─ working_scope
├─ acceptance
├─ mode_payload
├─ shape_payload
└─ todo_tool_contract
```

关键语义：

- `primary_mode` 是主执行契约，只能是 `goal | plan`。
- `todo_tool_contract` 是执行游标，不是模式。
- `task_shape` 是当前工作形态，不是主契约。
- 系统不猜 `primary_mode`。
- 无效合同直接 repair，不 silent fallback。

## 6. 缓存设计

缓存不是按“任务文档层级”切，而是按 turn 反射稳定性切。

### 6.1 可缓存内容

只放稳定神经线路：

- turn 是唯一生命周期；
- `TaskRun` 是系统长任务资源；
- task 在 prompt 中是持续状态投影；
- 六个反射点；
- `request_task_run` 的动作本质；
- `TaskStartIntent` 的字段语义；
- 禁止事项。

这些内容短而稳定，可以进 stable prefix。

### 6.2 不可缓存内容

放在 volatile tail：

- 当前是否有 active task；
- `task_run_id`；
- 当前目标；
- active step；
- todo 游标；
- pending steer；
- 恢复点；
- 验收焦点；
- 本轮需要优先写回的状态。

这些内容必须每 turn 更新，不能进入 stable prefix。

### 6.3 Provider 动作面

放在 request overlay：

- 当前是否允许 `request_task_run`；
- 当前是否使用 provider strict tool/function calling；
- 当前可用工具、权限、预算和控制动作。

它不是任务说明，而是本 turn 的动作面。

## 7. 文件级重构方向

### 7.1 `backend/harness/runtime/compiler.py`

要做的不是再加一段 task prompt，而是重排 prompt 神经线路：

- stable prefix 只保留 turn reflex 原则；
- request overlay 暴露本 turn 动作面；
- volatile tail 输出 `Turn Reflex Index`；
- 删除旧 task mode 文案；
- 删除 `entry_reason` 引导；
- 删除七类 `primary_mode`；
- 删除把 task 写成独立执行人格的表达。

完成标准：

- agent 读到的是“本 turn 怎么反射”，不是“任务系统怎么设计”。

### 7.2 `backend/harness/runtime/control_action_schema.py`

重构 schema：

- `primary_mode` 只接受 `goal | plan`；
- 新增或对齐 `task_shape`；
- 移除 `entry_reason`；
- `todo_tool_contract` 作为独立字段；
- descriptions 写成字段动作语义，不写开发说明。

完成标准：

- schema 本身就是控制反射通道；
- 旧合同无法通过。

### 7.3 `backend/harness/loop/model_action_protocol.py`

重构动作解析：

- 不根据自然语言猜是否启动任务；
- 不把 unsupported mode fallback 成 `open_work`；
- 无效 `request_task_run` 只返回字段级 repair；
- repair 要求重发同一个控制动作。

完成标准：

- runtime 只校验控制信号，不替 agent 作语义选择。

### 7.4 `backend/harness/loop/single_agent_turn.py`

重构 repair 和 turn 结束逻辑：

- repair prompt 改成反射式字段反馈；
- task start 后仍回到普通 turn；
- 本轮结束前能承接状态写回；
- 不暗示进入独立 task executor 心智模型。

完成标准：

- agent 不会在普通 turn 和 task turn 之间切换人格。

### 7.5 `backend/harness/runtime/dynamic_context/task_mode_tail_context.py`

重命名思路上从 task mode tail 改为 turn reflex tail。

内容上：

- 输出 active task 的最小注意索引；
- todo 作为游标；
- plan 只暴露 active step 和必要摘要；
- shape 只暴露本轮工作焦点；
- 不注入长历史。

完成标准：

- 尾部内容能让 agent 立刻知道本 turn 该怎么继续。

### 7.6 `backend/harness/runtime/dynamic_context/manager.py`

确保动态任务状态挂在 volatile tail。

完成标准：

- tail 每 turn 更新；
- stable prefix 不被动态任务污染；
- 最新 todo 游标和 active step 不被缓存旧值覆盖。

### 7.7 `backend/harness/runtime/task_contract_manifest.py`

从“任务合同展示”改成“turn reflex index 的数据源”。

完成标准：

- manifest 能提供 `Turn Reflex Index` 所需字段；
- 不输出旧 task mode 混合结构。

### 7.8 `backend/harness/entrypoint/task_mode_slash_command.py`

slash 启动也不能构造旧任务模式。

完成标准：

- slash 入口也只产生同一套 `TaskStartIntent`；
- 不再写 `entry_reason`；
- 不绕过 `primary_mode / task_shape / acceptance`。

### 7.9 `backend/harness/entrypoint/runtime_facade.py`

入口层要服从同一原则：

- 普通工作进入普通 turn；
- task start 只是申请并绑定长任务资源；
- 后续仍由 turn 生命周期承载；
- 不让普通聊天任务进入第二套 task prompt loop。

完成标准：

- runtime 分支不再让 prompt 语义分裂。

## 8. 实施阶段

### 阶段一：重写 prompt 神经线路

改：

- stable turn reflex 原则；
- action reflex 文案；
- `request_task_run` 字段说明；
- repair prompt；
- tail index 文案。

不改：

- 不新增另一个 prompt 层；
- 不写任务系统说明书。

验收：

- agent-facing 文案都能直接转化为动作。

### 阶段二：收紧 schema 和协议

改：

- `TaskStartIntent` schema；
- mode 枚举；
- 无效动作 repair；
- 删除 silent fallback。

验收：

- 旧合同被拒绝；
- 新合同可通过；
- 系统不猜。

### 阶段三：把动态状态压到 tail

改：

- `Turn Reflex Index`；
- active step；
- todo cursor；
- acceptance focus；
- recovery/blocker。

验收：

- 每个 task-bound turn 尾部都有最新任务反射索引；
- 长 plan 不污染缓存；
- todo 更新后下一 turn 可见。

### 阶段四：入口和执行路径收敛

改：

- slash / CLI / agent-emitted control action 同合同；
- task-bound 工作回到普通 turn；
- 普通聊天任务不默认进入独立 task execution prompt loop。

验收：

- agent 只看到一套 turn 心智模型；
- task 只表现为持续状态反射。

## 9. 验证方式

不新增回归测试文件。

### 9.1 静态验证

检查：

- agent-facing prompt 中没有 `entry_reason`；
- 没有七类 `primary_mode`；
- 没有把 todo 当 mode；
- 没有把 task 写成第二套生命周期；
- 所有任务文案都能转化成“本 turn 该怎么做”。

### 9.2 CLI 真实验证

验证：

- 普通 turn 能直接完成；
- 需要长任务资源时，agent 能发出 `request_task_run`；
- `primary_mode=goal` 合法；
- `primary_mode=plan` 合法；
- `primary_mode=todo` 被拒绝；
- `primary_mode=investigation` 被拒绝；
- 带 `entry_reason` 的旧合同被拒绝；
- task-bound 下一轮能看到 `Turn Reflex Index`；
- todo 游标更新后能被下一轮读取；
- 达到验收条件后能收口。

## 10. 禁止事项

实施时禁止：

- 把 prompt 写成开发说明；
- 再造一套 task lifecycle；
- 在旧 task prompt 外包新 prompt；
- 让系统猜用户语义或 agent 语义；
- 保留旧七类 mode 作为兼容；
- 把 todo 写成主任务模式；
- 把动态任务状态塞进 stable prefix；
- 用普通回复伪装控制动作；
- 用 silent fallback 掩盖合同错误。

## 11. 最终状态

重构完成后，系统应该呈现这样的行为：

- agent 只活在 turn 生命周期里；
- `TaskRun` 是系统侧长任务资源；
- task 在 agent 侧只是 turn 内部的持续状态压力；
- prompt 是短促、可执行的反射；
- `request_task_run` 是 action reflex 的控制信号；
- provider strict schema 是控制信号的通道；
- tail index 是每轮的任务定向反射；
- todo 是游标；
- recovery 是恢复点；
- acceptance 是收口反射；
- runtime 不猜，agent 不读说明书，系统只承接明确控制动作。
