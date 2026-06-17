# 回档前 Chronological 公开投影恢复计划书

日期：2026-06-17  
状态：待用户审阅，未实施  
范围：回档前公开投影档案定位、Chronological Projection 后端合同、前端 projection reducer / view model / ChatMessage 渲染、session restore 投影水合、相关测试  
不在范围：DynamicContextManager 上下文装配恢复、RuntimeCompiler task_execution packet 重构、tool runtime 文件证据链回滚、任务图语义重写

## 1. 结论

回档前档案仍然存在。

当前分支：

```text
codex/rollback-last-optimization
HEAD = 39e628300
提交时间 = 2026-06-16 04:14:47 +0800
提交说明 = 最后的优化
```

回档前分支：

```text
codex/mature-harness-projection-memory-vscode-backport
HEAD = d69ae20c4
提交时间 = 2026-06-17 15:23:01 +0800
提交说明 = 11111
```

`git reflog` 显示，2026-06-17 17:38:36 从 `codex/mature-harness-projection-memory-vscode-backport` 切换到了 `codex/rollback-last-optimization`。因此 `d69ae20c4` 就是本次“回档之前”的代码档案锚点。

用户补充判断是正确的：公开投影链路不是当前上下文装配问题的坏源头。恢复上下文装配时不能把回档前已经修好的 Chronological Projection 删除或降级。

## 2. 回档前投影档案

回档前已有两份直接相关的投影方案文档：

| 文档 | 状态 | 价值 |
| --- | --- | --- |
| `docs/系统架构/157-按时序精确投影系统重构方案-20260616.md` | 回档前存在，当前分支缺失 | 定义 Chronological Projection 目标架构 |
| `docs/系统架构/158-投影系统信号对齐与冲突收束计划书-20260617.md` | 回档前存在，当前分支缺失 | 定义已完成进展、剩余冲突和收束计划 |

核心目标架构：

```text
Runtime/Public Event Log
-> Public Projection Contract
-> Chronological Projection Slice
-> Frontend Projection Normalizer
-> Projection Accumulator
-> Projection ViewModel
-> Store Adapter / Visible Flush
-> ChatMessageView
```

这条链路解决的是公开显示、SSE 投影、刷新恢复、工具轨迹和 assistant 正文时序问题，不负责模型上下文装配。

## 3. 必须恢复的投影主线

### 3.1 后端公开投影合同

候选恢复文件：

```text
backend/harness/runtime/projection/authority.py
backend/harness/runtime/projection/projector.py
backend/harness/runtime/run_monitor/projector.py
backend/harness/runtime/run_monitor/service.py
backend/harness/runtime/run_monitor/signals.py
backend/harness/runtime/session_timeline.py
```

恢复目标：

- 公开 projection frame 保持单一权威。
- frame 带稳定 anchor、event offset、source event identity。
- session restore 使用 canonical public ledger / chronological projection slice。
- raw runtime event tail 不能重新发明主聊天 frame，只能用于 diagnostics / trace。

### 3.2 前端 Chronological Projection

候选恢复文件：

```text
frontend/src/lib/projection/reducer.ts
frontend/src/lib/projection/reducer.test.ts
frontend/src/lib/projection/chronological/accumulator.ts
frontend/src/lib/projection/chronological/index.ts
frontend/src/lib/projection/chronological/normalize.ts
frontend/src/lib/projection/chronological/types.ts
frontend/src/lib/projection/chronological/viewModel.ts
```

恢复目标：

- 一个事件时钟。
- 一个 projection key。
- 一个 frame identity。
- 一个 accumulator 折叠权威。
- 一个 view model。
- `message.content` 不再被 live projection body 反复回写。

### 3.3 前端 Store / Hydration

候选恢复文件：

```text
frontend/src/lib/store.tsx
frontend/src/lib/store/types.ts
frontend/src/lib/store/runtime.ts
frontend/src/lib/store/events.ts
frontend/src/lib/store/core.ts
frontend/src/lib/store/hooks.ts
frontend/src/lib/store/utils.ts
frontend/src/lib/store/runtime/projectionHydration.ts
frontend/src/lib/store/runtime/text.ts
frontend/src/lib/store/runtime/streamEvents.ts
frontend/src/lib/store/runtime/chatThinking.ts
```

恢复目标：

- live 投影和 refresh/hydration 走同一 accumulator。
- projection slice replay 幂等。
- 高频 body frame 进行可见刷新合并。
- 工具、权限、错误、terminal 不被正文节流延迟。

### 3.4 Chat 渲染组件

候选恢复文件：

```text
frontend/src/components/chat/ChatMessage.tsx
frontend/src/components/chat/ChatPanel.tsx
frontend/src/components/chat/PublicTimelineActivity.tsx
frontend/src/components/chat/AssistantMessage.tsx
frontend/src/components/chat/UserMessage.tsx
frontend/src/components/chat/AssistantTrace.tsx
frontend/src/components/chat/RuntimeLogEntry.tsx
frontend/src/components/chat/ToolTrace.tsx
frontend/src/components/chat/TodoPlan.tsx
frontend/src/components/chat/MessageAttachments.tsx
frontend/src/components/chat/projectionMessageBlocks.ts
```

恢复目标：

- `ChatMessage` 只消费 projection view blocks。
- `PublicTimelineActivity` 渲染 typed blocks，不重新推断协议。
- 工具窗口、todo plan、runtime log、assistant body 按同一时序呈现。
- 删除 `useNaturalizedStreamText` 这种从自然语言猜显示的旧链路。

## 4. 明确不能一起恢复的链路

以下文件虽然也在 `39e628300..d69ae20c4` 中有变化，但它们属于上下文装配、工具证据或执行循环，不应随公开投影一起恢复：

```text
backend/harness/loop/task_executor.py
backend/harness/runtime/compiler.py
backend/harness/runtime/dynamic_context/manager.py
backend/harness/runtime/dynamic_context/task_state_projector.py
backend/harness/runtime/dynamic_context/tool_result_projector.py
backend/runtime/tool_runtime/*
backend/runtime/memory/*
```

原因：

- 当前暴露的问题集中在模型上下文装配，不能把这些回档前新链路盲目带回。
- `task_state_replay_entries`、`bound_task_context`、`read_evidence_injection` 等需要单独审查。
- 公开投影只负责用户可见显示，不应承担模型上下文事实权威。

## 5. 实施方案

### Phase 1：恢复投影档案文档

恢复：

```text
docs/系统架构/157-按时序精确投影系统重构方案-20260616.md
docs/系统架构/158-投影系统信号对齐与冲突收束计划书-20260617.md
```

目的：

- 让后续实施有回档前的真实设计依据。
- 避免用 153 号上下文装配计划误删公开投影。

### Phase 2：恢复后端公开投影合同

只恢复 `backend/harness/runtime/projection/*` 与必要 session timeline / run monitor 投影文件。

要求：

- 不引入 `compiler.py` / `dynamic_context` / `task_executor.py` 改动。
- 若后端 projection 依赖缺失字段，优先在 projection 层显式适配，不向上下文装配层借权。

### Phase 3：恢复前端 Chronological Projection

恢复 `frontend/src/lib/projection/chronological/*`、`reducer.ts`、相关 store hydration 和 chat 渲染组件。

要求：

- 不恢复无关 workspace shell / UI framework 大重构。
- 不恢复与投影无关的 API 拆包，除非 TypeScript 编译证明必须恢复。
- 如果 `frontend/src/lib/api.ts` 类型不足，只补投影需要的类型字段，不做整套 API 模块迁移。

### Phase 4：删除旧公开投影链路

删除或停止使用：

```text
frontend/src/components/chat/useNaturalizedStreamText.ts
frontend/src/components/chat/useNaturalizedStreamText.test.ts
```

删除标准：

- 如果显示依赖自然语言猜测正文 / 工具窗口，该链路无投影权威。
- 旧测试如果只保护自然语言显示猜测，应删除或改写为 Chronological Projection 行为测试。

### Phase 5：测试与真实启动验证

后端测试：

```powershell
python -m pytest backend/tests/public_projection_contract_test.py backend/tests/runtime_monitor_projection_test.py backend/tests/session_runtime_timeline_contract_test.py -q
```

前端测试：

```powershell
npm test -- --run frontend/src/lib/projection/reducer.test.ts frontend/src/components/chat/ChatMessage.test.ts frontend/src/components/chat/ChatPanel.test.ts
```

前端构建检查：

```powershell
npm run lint
npm run build
```

涉及前后端运行链路时，必须固定端口真实启动：

```powershell
uvicorn backend.api.main:app --host 127.0.0.1 --port 8003
npm run dev -- --hostname 127.0.0.1 --port 3000
```

验收：

- `127.0.0.1:3000` 只有一个前端项目进程。
- `127.0.0.1:8003` 只有一个后端项目进程。
- 前端 API Base 为 `http://127.0.0.1:8003/api`。
- 图写作任务运行时，assistant body、工具轨迹、todo/status、terminal 按 event offset 单调呈现。
- 刷新后不重复正文、不重复工具块、不丢 terminal。

## 6. 停止条件

实施中遇到以下情况必须暂停：

- 投影恢复需要恢复 `compiler.py`、`dynamic_context`、`task_executor.py` 的回档前改动。
- 后端 projection 缺失字段只能通过修改模型上下文装配获得。
- 前端恢复必须带回无关 workspace shell / API 大拆包。
- 测试发现 Chronological Projection 与当前 public event contract 不兼容，需要重新制定合同。

## 7. 最终目标

恢复后系统应同时满足两件事：

```text
公开投影：使用回档前成熟 Chronological Projection
上下文装配：单独修复，不误伤公开投影
```

公开投影不替模型做语义决策，只把 runtime/public event log 精确、按时序、可恢复地呈现给用户。上下文装配问题按 153 号计划另行处理，但实施 153 前必须先保护本计划中的公开投影主线。
