# CurrentWorkBoundary 单 Agent 控制链审查与精准修复计划

日期：2026-06-14

范围：单 agent 控制系统、CurrentWorkBoundary、active turn、task run 控制入口。

不在范围：图任务、图像任务、前端展示重构、工具调用投影链路。

## 一、目标标准

本轮以成熟 coding agent 的控制系统为标准。目标链路必须保持单向权威：

```text
RequestFacts
-> BoundaryPolicy
-> ModelTurnDecision
-> ActionPermit/Receipt
-> RuntimeStartPacket
-> ExecutionLoop
```

关键要求：

- active work 只能来自 active turn 绑定，不能从最近任务、历史任务或 waiting_executor 记录中推断。
- CurrentWorkBoundary receipt 是唯一当前工作控制许可。
- receipt 被消费前必须重新确认同一个 active turn 与同一个 task run 仍然有效。
- 执行层不得把过期上下文重新绑定为当前工作。
- 终态判断必须统一，不允许不同层持有不同终态集合。
- 替换当前工作必须精确替换 receipt 指向的 task run，不能替换执行瞬间碰巧出现的其他任务。

## 二、审查结论

当前新链路方向正确：边界模型已窄化、普通 turn 不再因 active_work_context 自动获得 active_work_control、single_agent_turn 收到 active_work_control 会 fail-close。

仍需修复的控制缺口：

1. receipt 生成后到 control-only 执行前缺少二次绑定校验，存在 stale receipt 执行窗口。
2. append_instruction_to_active_work 写入 steer 前未拒绝终态或已停止 task run。
3. replace_current_work 消费 receipt 时未强校验 current task id 是否等于 receipt.task_run_ref。
4. ActiveTurn、RuntimeFacade、CurrentWorkBoundary、TaskLifecycle 的终态集合不完全一致。
5. control-only 中属于公开回答的 `answer_about_active_work` / `answer_then_continue_active_work` 需要显式落库，避免刷新后丢失解释。

## 三、目标修复

本轮采用精准修复，不引入新调度框架，不改图任务，不重写 prompt。

### 1. 统一终态口径

新增单一 task run 状态谓词，供 CurrentWorkBoundary、ActiveTurn、RuntimeFacade、TaskLifecycle、TaskExecutor 使用。

目标状态集合：

```text
completed, success, failed, error, aborted, cancelled, canceled, stopped, user_aborted
```

同时将 runtime_control.state 为 `stop_requested` 或 `stopped` 的 task 视为不可控制当前工作。

### 2. control-only 执行前重新校验

在 `_run_current_work_control_receipt` 执行前重新读取 active turn 与 task run，要求：

- active turn 仍存在。
- active turn id 等于 receipt.active_work_ref.actual_active_turn_id。
- bound task run id 等于 receipt.task_run_ref。
- task run 仍为 single_agent_task。
- task run 非终态、非 stopped/stop_requested。

任一失败，转为 terminal block，不执行 append、continue、pause、stop。

### 3. append steer 写入前拒绝终态

在 `append_user_work_instruction` 入口拒绝：

- terminal task status。
- runtime_control 为 stopped/stop_requested。
- 非 single_agent_task。
- graph_node_assigned。

这保证即使上层漏校验，底层写入也 fail-close。

### 4. replacement receipt 强绑定

`_execute_current_task_replacement_receipt` 必须要求：

- receipt.task_run_ref 非空。
- current_session_task_run 的 task_run_id 等于 receipt.task_run_ref。

否则返回 blocked/error，不停止其他任务。

### 5. 回归测试

新增或更新测试覆盖：

- terminal/stopped task 不会被 ActiveTurnRegistry 解析为 current active turn。
- terminal task 不能 append steer。
- replacement receipt 不会停止非 receipt 指向的 current task。
- control receipt 在 active turn/task 过期时 fail-close，不执行控制动作。
- control-only 的公开回答使用 conversation channel 提交，纯控制动作仍保持 runtime_control。

### 6. control-only 公开回答持久化

仅当控制动作本身包含公开回答时提交 assistant message：

- `answer_about_active_work`
- `answer_then_continue_active_work`

纯执行控制如 continue、append、pause、stop 不额外提交正文，避免把控制确认伪装成最终交付。

## 四、验收标准

聚焦测试必须通过：

```powershell
pytest backend/tests/current_work_boundary_regression.py backend/tests/active_turn_authority_regression.py backend/tests/harness_task_lifecycle_control_regression.py
```

代码复查必须确认：

- `active_work_control` 仍只能由 CurrentWorkBoundary receipt 授权。
- ordinary turn 仍不能消费 active_work_control。
- 没有新增旧链路兼容 fallback。
- 没有引入图任务控制分支。
