# 工具观察后的模型反馈链路审查（2026-06-15）

## 结论

当前问题不是工具失败观察完全丢失，而是普通 `single_agent_turn` 的工具 follow-up 允许模型在失败工具观察返回后继续发起工具动作但不提供公开语义反馈。于是用户看到的是工具窗口或系统状态，而不是大模型基于失败观察给出的解释。

成熟 agent 的正确链路应是：

```text
模型请求工具
-> 系统执行工具并形成 observation
-> observation 回填给模型
-> 模型基于 observation 决定：解释、继续工具、询问、阻塞或收口
-> 只有模型的 public_progress_note / public_action_state / final_answer 进入正文反馈
```

系统失败原因只能作为工具观察和模型输入，不能替代 assistant 正文。

## 已确认链路

1. 系统观察生成存在。
   - `backend/api/chat.py::_tool_item_completed_data` 会从 `tool_observation` / `result_envelope` / `execution_receipt` 中提取 `observation` 和 `error`，并投影为 `TOOL_ITEM_COMPLETED_EVENT`。

2. 模型反馈投影入口存在。
   - `backend/api/chat.py::_model_action_feedback_step_data` 会把 `model_action_request.public_progress_note` 或 `public_action_state.current_judgment` 转成 `runtime_step_summary`。
   - `backend/harness/runtime/projection/projector.py::_runtime_step_summary_spec` 会把 `presentation_source=model_action.*` 的反馈作为 `body_append` 投影到正文流。

3. 观察 follow-up packet 存在。
   - `backend/harness/runtime/compiler.py::compile_observation_followup_packet` 会把观察组装进 `tool_observation_followup` 的模型输入。

## 断点

普通 turn 的工具循环原来在解析 follow-up 输出时使用：

```python
public_response_required=tool_iteration == 0
```

位置：

- `backend/harness/loop/single_agent_turn.py` 工具循环主解析。
- 同文件协议修复调用也沿用相同条件。

含义是：第一轮工具调用要求公开反馈，但工具观察返回后的第二轮、第三轮如果模型继续调用工具，就不再根据观察状态强制 `public_progress_note/current_judgment`。这会导致失败、拒绝、取消、缺合同等用户可见故障只停留在工具观察里，没有被模型解释给用户。

- `backend/harness/runtime/compiler.py::single_agent_action_schema` 已写明工具观察发现错误、阻塞、权限问题、缺失信息、测试失败、运行异常或与用户预期冲突时必须解释。
- 但协议解析层没有执行“失败观察必须反馈”的硬约束。

## 修复边界

本次修复应在后端权威层完成：

1. 普通 `single_agent_turn` 在首轮工具调用前，仍必须先有模型公开反馈，用于回应用户当前输入。
2. 普通 `single_agent_turn` 在上一轮工具观察包含失败、拒绝、取消、缺合同、运行错误或 result envelope error 后，如果模型继续请求工具，必须有模型公开反馈。
3. 成功的低层读取、搜索、目录枚举等观察不由解析层强制刷正文；是否解释由模型根据 prompt 中的公开观察规则决定，避免把工具噪声当正文。
4. 如果连续两轮工具观察都失败，系统必须停止继续工具循环，不允许第三次继续撞同类失败；后端发出 runtime control signal，由模型基于失败观察收口反馈用户。
5. 反馈来源只能是模型输出的正文前言、`public_progress_note` 或 `public_action_state.current_judgment`。
6. 系统工具失败原因仍只作为工具窗口/观察和模型输入，不作为 assistant 正文。
7. TaskRun 主执行链路已经在 `_invoke_task_model_action` 中要求 `public_response_required=True`，本次不改变它。

## 已实施修复

1. `backend/harness/loop/single_agent_turn.py` 在工具循环中保留上一轮 `ToolObservation` payload。
2. 新增 `_tool_followup_public_response_required(tool_iteration, recent_observations)`：
   - `tool_iteration <= 0`：首轮工具调用必须有公开反馈。
   - 最近观察状态为 `error/failed/denied/needs_contract/aborted/canceled/cancelled`：下一次模型动作必须有公开反馈。
   - `result_envelope.status`、`result_envelope.error/error_code`、`execution_receipt.status` 同样参与结构化失败判定。
   - `needs_approval` 不直接作为普通单轮正文反馈；当前链路会先转换为可恢复任务要求或审批边界观察。
3. 协议修复提示已从单一“回应用户输入本身”改成按阶段区分：
   - 首次工具调用前回应用户当前输入。
   - 工具观察返回后，尤其失败观察后，基于观察说明已确认的公开事实、影响和下一步。
4. 新增连续失败边界：
   - `_CONSECUTIVE_TOOL_FAILURE_CLOSEOUT_THRESHOLD = 2`。
   - 每一轮工具批次只要全部观察都属于需要模型反馈的失败状态，连续失败计数加一；出现成功/普通观察则清零。
   - 达到阈值后，后端在 observation 已写回模型上下文、下一次模型/工具动作之前发出 `single_turn_consecutive_tool_failures` 控制信号。
   - 后端不直接生成失败正文；它调用 agent-authored closeout，让模型输出自然语言收口。
