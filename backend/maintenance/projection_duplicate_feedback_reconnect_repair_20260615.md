# Projection Duplicate Feedback Reconnect Repair - 2026-06-15

## Problem

断线重连后，模型过程反馈正文可能在主对话中出现两遍。截图中的重复不是工具窗口重复，而是同一组 `runtime_step_summary` 模型反馈正文被按相同顺序再次追加。

## Root Cause

投影链路有三条可见入口：

1. 实时 chat run stream 通过 `public_projection_frame` 进入前端 reducer。
2. 会话历史 hydrate 通过 stream runtime attachment 重放 chat run public ledger。
3. 会话历史 hydrate 通过 task runtime attachment 从 task event log 重建 public projection frames。

实时流桥能从 event refs 推出 `feedback_identity`，但 task runtime attachment 重建时直接拿 `step_summary_recorded.payload` 投影。旧 task event 的 `action_request_ref` 只在 refs 里，不在 payload 里，导致同一模型反馈在实时流和历史重建中得到不同 `item_id/frame_id`。

前端 reducer 之前只按 `frame_id/projection_id/source_event_id` 判断 body frame 是否已处理。断线重放或历史重建一旦让帧包装身份漂移，同一模型反馈就会被当成新正文追加。

## Fixed Chain

目标链路：

```text
model_action_request
-> step_summary_recorded(refs.action_request_ref)
-> runtime_step_summary.feedback_identity
-> public_projection_frame.item_id(model-action-feedback-body:...)
-> frontend projection ledger semantic body id
-> one visible body block
```

改动：

- `backend/harness/loop/task_executor.py`
  - 新写入的 model action step summary 会把 refs 中的 `action_request_ref` / `batch_action_request_ref` / `runtime_invocation_packet_ref` 显式落到 `feedback_identity`。
- `backend/harness/runtime/session_timeline.py`
  - 历史 task attachment 重建旧 `step_summary_recorded` 时，如果 payload 没有 `feedback_identity`，会从 event refs 恢复。
- `frontend/src/lib/projection/reducer.ts`
  - 对 `runtime_step_summary` 产生的模型反馈正文，除了帧身份外，再按 `item_id` 作为语义身份去重。
  - 普通 assistant text delta 仍按帧身份追加，不按文本清洗或中文文案过滤。

## Verification

- `python -m pytest backend/tests/session_runtime_timeline_contract_test.py -q`
  - 通过，覆盖旧 task event refs 恢复为与 stream ledger 一致的 feedback frame identity。
- `npm run test -- src/lib/projection/reducer.test.ts`
  - 通过，覆盖同一模型反馈身份经 live/history 两路重放只生成一次正文块。

## Boundary

这次修复没有改变工具窗口、收口逻辑、普通正文流式 delta 的追加规则，也没有用 UI 文本过滤来隐藏重复。权威身份仍由后端投影产生，前端只做幂等合并。
