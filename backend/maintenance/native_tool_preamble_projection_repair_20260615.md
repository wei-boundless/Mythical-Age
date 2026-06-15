# Native Tool Preamble Projection Repair - 2026-06-15

## Problem

截图中同一段模型反馈被显示成三段：

```text
模型正文反馈
工具窗口 A
模型正文反馈
工具窗口 B
模型正文反馈
工具窗口 C
```

这不是工具窗口分组问题，而是信号归属错位。一次模型 native tool 决策里，模型 `content` / packet preamble 应当只进入正文 body 一次；每个工具调用只应携带自己的 `tool_call_id`、工具名、参数和生命周期状态。

## Root Cause

`backend/harness/loop/single_agent_turn.py` 的 native tool 解析链路把 `packet_public_progress_note` 传给每个 `_tool_action_request_from_native_tool_calls()` 子请求。

结果是：

1. 模型 packet preamble 已经通过 `runtime_step_summary` 投影为正文。
2. 每个 tool action 又继承同一段 `public_progress_note`。
3. 每个 `model_action_admission` 被 chat 投影桥再次转成 `runtime_step_summary`。
4. 前端收到多个不同工具请求身份下的正文帧，只能按时序显示成多段。

## Fixed Wiring

目标信号线：

```text
model packet content / packet_public_progress_note
-> runtime_step_summary
-> body_append
-> 正文显示一次

native tool call
-> ModelActionRequest(tool_call, public_progress_note="")
-> model_action_admission
-> tool_call_requested
-> 工具窗口 / tool_call_id 生命周期
```

保留规则：

- 工具调用的显式用户可见字段只允许来自工具调用参数内的 `public_progress_note/public_note/current_judgment/reason/purpose/user_visible_reason`。
- packet preamble 不能作为每个工具调用的 fallback。
- 一轮多工具通过 `single-agent-tool:<iteration>` 的 request id 继续归到同一个工具轮次。

## Verification

- `python -m py_compile backend/harness/loop/single_agent_turn.py`
- `python -m pytest backend/tests/harness_single_agent_tool_runtime_regression.py -k "native_tool_call_action_keeps_agent_text_out_of_tool_projection or batches_multiple_read_only_tools" -q`
- 临时多工具探针确认：
  - `runtime_step_summary_count = 1`
  - 两个工具 admission 的 `public_progress_note = ""`
  - 两个工具仍保留各自 `tool_call_id`

