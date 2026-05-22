# 断点重续与人工介入体系计划

日期：2026-05-22

## 1. 问题判断

当前系统已经具备 checkpoint、resume decision、approval、rewind、monitor 和 trace reader，但这些能力仍是分散的。

真正的问题不是“能不能恢复”，而是：

1. 恢复和决策混在一起。
2. 人工介入没有统一的控制记录。
3. 图任务的断点续重分散在多个 API 和 runtime 分支里。
4. 监控层能看见事实，但不能代表控制权。

所以这次要修的是控制平面，不是展示层。

正确目标是：

- checkpoint 只负责恢复现场。
- resume decision 只负责判断当前该怎么走。
- human intervention 只负责记录人工接管、审批、重试、回退、暂停和继续。
- graph task resume 只负责把图任务从正确边界接回去。

## 2. 现有证据

### 2.1 已有恢复资产

`backend/runtime/shared/checkpoint.py`

- `RuntimeCheckpointStore` 已经持久化 `RuntimeLoopState`、`approval_state`、`commit_state`、执行摘要和运行对象摘要。
- 这是恢复现场的唯一可靠基座。

`backend/runtime/shared/resume_decision.py`

- 已有 `decide_professional_run_resume()`，但它只覆盖很窄的专业任务恢复判断。
- 目前更像一个局部策略函数，还不是统一的恢复裁决层。

### 2.2 已有人工介入资产

`backend/runtime/coordination_runtime/runtime.py`

- `resume_human_gate()` 已经能把人审结果写回 state。
- `_resume_human_gate_state()` 已经处理 approve / retry / reject / waiting。
- 但它缺少独立、可追溯的人工介入账本。

`backend/api/orchestration_runtime_loop.py`

- `approval` 和 `stop` 已经暴露给外部。
- 但这些入口是分散的，且语义还不够统一。

`backend/api/orchestration.py`

- `resume_coordination_run()`
- `continue_coordination_current_stage()`
- `rewind_from_stage()`

这三个入口已经构成图任务恢复的雏形，但现在是多分支拼接，不是单一控制协议。

### 2.3 已有监控资产

`backend/runtime/memory/trace_reader.py`

- 只读地把 checkpoint、事件、coordination、monitor 汇成可观察事实。
- 适合做看板，不适合做控制决策。

`backend/runtime/graph_runtime/run_monitor.py`

- 已能呈现图任务运行事实、节点状态、失败信息、时序信息和健康提示。
- 但它不能承担恢复或人工介入责任。

## 3. 设计判断

### 3.1 恢复、决策、执行、展示必须拆开

恢复：只加载 checkpoint、state、ledger、trace、未消费结果。

决策：只判断当前应该 `continue / restart / rewind / clarify / wait_for_human / abort`。

执行：只改 runtime state 并写事件、checkpoint、介入记录。

展示：只读事实，不发起控制。

这是这次重构最重要的边界。

### 3.2 checkpoint 不是 continue 的理由

有 checkpoint 不等于应该继续旧动作。

checkpoint 只能说明：

- 上次停在哪。
- 当前状态是否可恢复。
- 哪些结果已经落盘。

是否继续、回退、重做、人工处理，必须由当前意图和当前状态共同决定。

### 3.3 人工介入必须是第一类对象

人工介入不能只靠“approval”这个单点。

它必须记录：

- 谁介入。
- 介入的是哪个 task run / coordination run / stage / node。
- 介入原因。
- 介入动作。
- 动作前状态。
- 动作后状态。
- 是否产生新的 resume payload。

没有这层记录，人工接管就只是 UI 按钮，不是系统能力。

### 3.4 图任务恢复必须按边界恢复

图任务不能只靠“继续当前 stage”一个入口硬接。

它至少要区分：

- 从 checkpoint 恢复当前活动 stage。
- 从未消费的 task result 恢复。
- 从 human gate 恢复。
- 从 stage rewind 后重新调度。
- 从 completed checkpoint 修复半收尾状态。

### 3.5 监控不是控制

右侧监控、trace、task graph monitor 只能回答：

- 现在发生了什么。
- 为什么卡住。
- 哪些节点在等人。
- 哪些 checkpoint 可恢复。

它们不能直接改状态。

## 4. 目标模型

### 4.1 三个核心对象

#### 1. Resume Candidate

表示“可以考虑恢复”的对象。

来源可能是：

- 最新 checkpoint
- 未消费 task result
- human gate pending state
- completed checkpoint with missing closeout

#### 2. Resume Decision

表示“当前该怎么走”的裁决。

建议统一成：

- `continue`
- `restart`
- `rewind`
- `clarify`
- `wait_for_human`
- `abort`

#### 3. Human Intervention Record

表示人工接管事实。

建议统一字段：

- `intervention_id`
- `actor`
- `target_type`
- `target_id`
- `action`
- `reason`
- `payload`
- `before_ref`
- `after_ref`
- `created_at`

### 4.2 图任务恢复坐标

图任务恢复要明确四个坐标：

- `task_run_id`
- `coordination_run_id`
- `stage_id`
- `checkpoint_ref`

恢复时必须知道自己是在恢复哪个层级，不能只说“恢复任务”。

### 4.3 控制面唯一职责

建议统一一个控制面语义：

- 先判定 resume candidate。
- 再生成 resume decision。
- 再写 intervention record。
- 最后执行 state mutation。

这样才能避免 API 里散落多个互相覆盖的恢复逻辑。

## 5. 实施计划

### 阶段一：统一恢复语义

目标：

- 把 checkpoint、resume decision、human intervention 的语义统一。
- 形成一个可复用的恢复裁决层。

要做的事：

1. 扩展 `backend/runtime/shared/resume_decision.py`。
2. 把 `decide_professional_run_resume()` 收敛成更通用的决策入口。
3. 让决策显式区分恢复、重启、回退、澄清、等待人工、终止。

不做的事：

- 不改前端结构。
- 不改健康系统。
- 不在 monitor 层做决策。

### 阶段二：建立人工介入账本

目标：

- 让人工介入成为可追踪、可审计、可回放的控制事实。

要做的事：

1. 新增人工介入记录模型。
2. 在 coordination human gate、approval、stop、rewind 等控制点写入记录。
3. 在 checkpoint 里保留介入摘要引用。

不做的事：

- 不把人工介入写成纯 diagnostics。
- 不只靠事件文本表示人工操作。

### 阶段三：统一图任务恢复入口

目标：

- 把图任务恢复从多个分支收束为统一控制路径。

要做的事：

1. 统一 `resume_coordination_run()`、`continue_coordination_current_stage()`、`rewind_from_stage()` 的入口语义。
2. 明确“从 checkpoint 恢复”“从未消费结果恢复”“从 human gate 恢复”“从 rewind 恢复”的分支。
3. 让每条分支都产出清晰的 resume decision 和 intervention record。

不做的事：

- 不允许 monitor 反向触发恢复。
- 不允许多个恢复分支各自维护一套隐式状态。

### 阶段四：图任务断点重续与人工介入

目标：

- 让 graph task 能在 stage / node / coordination 三个层级进行断点重续。
- 让人工介入能暂停、批准、重试、回退、继续。

要做的事：

1. 支持 stage 级 pause / resume / rewind。
2. 支持 human gate 的 approve / retry / reject / hold。
3. 支持 completed checkpoint 的 closeout 修复后再继续。
4. 支持未消费结果与 checkpoint 的自动对齐。

不做的事：

- 不把“继续”做成无条件 replay。
- 不把“审批”只理解成一个按钮结果。

### 阶段五：监控只读化

目标：

- 监控只提供事实和建议，不持有控制权。

要做的事：

1. 让 trace_reader 输出 resume candidate、waiting reason、human intervention summary。
2. 让 run monitor 明确显示当前是否可恢复、是否需人工、是否可回退。
3. 保留现有监控面板，但不在里面塞控制逻辑。

## 6. 文件级执行清单

- `backend/runtime/shared/checkpoint.py`
  - 增加介入摘要引用字段或扩展现有 checkpoint 摘要结构。
- `backend/runtime/shared/resume_decision.py`
  - 扩展为统一恢复裁决入口。
- `backend/runtime/coordination_runtime/runtime.py`
  - 收敛 human gate resume、rewind、stage continuation 的状态写入。
- `backend/api/orchestration_runtime_loop.py`
  - 统一 approval / stop / resume 的控制语义。
- `backend/api/orchestration.py`
  - 明确 coordination resume / continue / rewind 的边界和返回值。
- `backend/runtime/memory/trace_reader.py`
  - 增加恢复候选与人工介入的只读摘要。
- `backend/runtime/graph_runtime/run_monitor.py`
  - 补充“可恢复 / 等待人工 / 已回退 / 已暂停”监控语义。
- `backend/tests/*`
  - 新增恢复、人工介入、rewind、completed checkpoint closeout 的回归测试。

## 7. 验证标准

必须证明以下场景真实可用：

1. 有 checkpoint 时，系统不会自动误继续，而是先给出明确 resume decision。
2. human gate 可以被 approve / retry / reject，并正确写回状态和记录。
3. graph task 可以从 stage 级 checkpoint 正确恢复。
4. graph task 可以在 rewind 后重新进入正确 stage。
5. completed checkpoint 半收尾问题可以修复后继续，而不是重跑或伪造输出。
6. 监控页能看见恢复候选和人工介入状态，但不能直接改控制权。

## 8. 风险控制

### 8.1 不能再犯的错误

- 把 checkpoint 当决策。
- 把 diagnostics 当账本。
- 把 monitor 当控制面。
- 把图任务恢复写成多个互不兼容的分支。

### 8.2 兼容性原则

只保留真正有运行意义的旧入口。

没有运行意义的旧残留直接清掉，不为了兼容保留假能力。

### 8.3 失败回退

如果某个恢复分支无法安全判定：

- 先进入 `clarify` 或 `wait_for_human`。
- 不允许默默继续。
- 不允许默默重跑。

## 9. 结论

这次要做的是一个成熟的断点重续与人工介入控制面。

它的核心不是“多几个按钮”，而是：

- checkpoint 负责记住现场。
- resume decision 负责做判断。
- human intervention 负责留痕。
- graph runtime 负责正确接回。
- monitor 只负责看见。

只要这五件事分清，图任务的断点重续和人工介入才会真正有用。
