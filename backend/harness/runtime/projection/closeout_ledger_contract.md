# 投影收口时序契约修复方案

## 问题结论

收口前的轨迹和执行日志入口不应该由 UI 或消息刷新层补出来。它们属于同一个严格时序投影 ledger：

```text
public_projection_frame
-> chronological ledger
-> assistant_text_final / visible_final marks final body
-> commit_ack marks runtime commit state
-> committed projection view
-> activity_archive + final body + log_entry
```

当前问题的核心风险是：流式阶段已经观察到完整轨迹，但 commit 后的 runtime projection 回读可能返回被裁剪或弱化的 projection slice。当前端用这个弱 slice 重新 hydrate 时，`activity_archive` 和 `log_entry` 会同时消失。live/running 投影允许轻量裁剪，默认上限为每个 attachment 60 帧；committed/closeout 投影不允许裁剪。

## 目标原则

1. `public_projection_frame` 是主聊天投影的唯一事实来源。
2. `assistant_text_final` / `visible_final` 是正文收口边界；`commit_ack` 只是 runtime 写回确认，不参与划分收口前轨迹。
3. committed/closeout projection slice 必须保持完整时序，不能按轻量刷新帧数裁剪。
4. 前端 hydrate 只能重放满足契约的 chronological projection slice。
5. `assistant_text_delta` 产生的最终正文流式影子在 `assistant_text_final` 后视为被 final 覆盖，不进入 `activity_archive`，也不重复显示在正文区。
6. UI 只展示 `projectionView`，不决定轨迹是否存在，也不单独伪造日志入口。

## 权责边界

### 后端 projector

负责把运行事件转换成公开投影 frame，并保证 frame 带有稳定的 anchor、offset、event family 和 source authority。

### 后端 session timeline

负责把 stream replay 中的公开 frame 组装成 `runtime_attachments.projection_slices`。对 committed closeout slice，它必须返回从本轮开始到 `commit_ack` 的完整 frame 序列，但不把 `commit_ack` 当作正文收口边界。

### 前端 projection accumulator

负责按 offset 严格归约 frame，生成 chronological ledger。它不做 UI 裁决。

### 前端 projection view model

负责唯一的收口视图转换：在 committed/closeout 状态下，以第一条 `assistant_text_final` / `visible_final` 正文为 final body 起点，把它之前已经投影过的过程 body、tool、todo、status 折叠进 `activity_archive`，保留 final body，并生成 `log_entry`。被 `assistant_text_final` 覆盖的 `assistant_text_delta` / `assistant_stream_repair` body 属于最终正文的流式影子，既不是历史记录，也不是第二份正文。

### 前端 hydration

负责从 runtime attachments 重放历史投影。它必须拒绝不满足 committed 完整性的 slice，避免弱历史覆盖完整 live ledger。

### UI

只展示 `projectionView.blocks`。`本轮记录` 位于最终正文上方，日志入口来自同一个 committed view 的 `logRef/toolEventCount`。

## 实施步骤

1. 后端：调整 `session_timeline` 的 frame bounding 策略。live projection 可以按 60 帧轻量裁剪；committed/closeout projection slice 不允许裁剪掉历史 frame 和 `commit_ack`。
2. 后端：为 projection slice 写入完整性 metadata，至少包含 `integrity: "complete"`、`committed: true`、`frame_count`。
3. 前端：`projectionHydration` 校验 committed slice。若 display hint 是 committed/closeout，但 slice 缺少 `commit_ack` 或 cursor/frame_count 不匹配，则不重放该 slice。
4. 前端：`projectionViewFromLedger` 将 closeout body 分为最终正文、过程记录、final 覆盖的流式影子三类；只有过程记录进入 archive。
5. 测试：增加后端 contract test，证明 committed projection 即使超过默认 frame limit 也完整保留，且包含 tool frames、final body、commit ack、log ref。
6. 测试：增加前端 hydration test，证明完整 committed slice 能恢复 `activity_archive` 和 `log_entry`；不完整 committed slice 不会生成弱 committed view。
6. UI 验证：确认折叠记录在最终正文上方，工具框线不回归，执行日志入口恢复。

## 验证命令

```bash
python -m pytest backend/tests/session_runtime_timeline_contract_test.py
npm test -- --run src/lib/store/runtime/projectionHydration.test.ts src/lib/projection/reducer.test.ts src/components/chat/ChatMessage.test.ts
npx tsc --noEmit
```

涉及运行链路后，必须用固定端口实测：

```text
frontend: http://127.0.0.1:3000
backend:  http://127.0.0.1:8003
```
