# Agent Main Output Feedback And Todo Persistence Plan - 2026-06-04

## 结论

这次问题不是单纯 UI 丑，也不是把工具名换成中文就够了。主页面需要展示的是 agent 的公开工作状态：

- 开局判断：我理解了什么、为什么先做这一步。
- 执行清单：任务拆成哪些待办，当前正在推进哪一个。
- 行动反馈：我正在做什么，不强调用了什么工具。
- 观察报告：动作返回后我看到了什么，这对下一步意味着什么。
- 最终总结：完成了什么、验证了什么、还剩什么风险。

现有代码已经有一部分基础：

- `backend/capability_system/tools/tool_units/agent_todo_tool.py` 已经把 todo 落盘到 `.tmp/agent_todo`。
- `backend/harness/runtime/session_timeline.py` 已经会从事件日志恢复 `runtime_attachments`。
- `backend/harness/runtime/progress_presenter.py` 已经把事件聚合成 `mission/work_units/technical_trace`。
- `backend/harness/runtime/public_chat_timeline.py` 已经投影 `final_summary`、`tool_activity`、`blocked`。
- `frontend/src/components/chat/PublicRunActivity.tsx` 已经用主会话内联活动行呈现进展。
- `frontend/src/components/chat/agentRunPresentation.ts` 已经在前端把工具行为翻译成“读取上下文/搜索引用/运行验证”。

但当前仍然缺少成熟 agent 体验的核心链路：

1. todo 状态只是工具私有文件，不是 session runtime attachment 的公开状态，因此刷新后不能稳定跟随主会话恢复。
2. `agent_todo` 结果被当成内部观察过滤掉了，用户看不到“我已经把任务拆成了哪些待办、现在做到哪一步”。
3. 工具观察仍然多处靠前端和后端猜测，容易显示成“工具完成/工具返回”，而不是“观察：读到了什么/验证说明什么”。
4. 开局反馈依赖 `assistant_text` 或 fallback 推断，不是一个明确的公开事件类型。
5. 最终总结依赖已有回答或 `closeout_summary`，如果运行缺少高质量 closeout，UI 就只能显示泛化收口。

所以目标是新增一条“公开执行反馈”主链路，而不是继续堆 CSS 或前端 regex。

## 目标体验

主页面应该类似成熟 coding agent 的反馈节奏：

```text
开局判断
我先读取项目约定和主会话渲染链路，把改动建立在真实上下文上。

处理清单
✓ 确认现有事件投影链路
● 持久化 todo 到会话公开状态
○ 优化观察报告和最终总结

执行中
正在读取主会话组件。
观察：运行反馈挂在 assistant turn 上，但 todo 只是工具私有状态，刷新不能恢复成公开清单。

收口
已完成：todo 可以刷新恢复，工具观察转换成用户可读报告，最终总结不再重复工具日志。
验证：后端投影测试、前端组件测试、固定端口页面实测通过。
```

主页面不应该出现：

```text
Agent Todo
tool: agent_todo
工具已完成
工具返回成功，正在根据结果继续
查看技术细节
event_id / taskrun / step_summary_recorded
```

## 权威链

目标链路：

```text
Runtime Events / Agent Todo State
-> Public Execution State Projector
-> Session Runtime Timeline Attachment
-> Public Chat Timeline
-> Chat UI Renderer
```

职责边界：

| 层级 | 负责 | 不负责 |
| --- | --- | --- |
| `agent_todo_tool.py` | 维护真实 todo 状态，提供结构化 plan | 给用户写 UI 文案 |
| Runtime event log | 记录工具调用、观察、生命周期事实 | 决定主页面怎么说 |
| 新的公开执行状态投影 | 把 todo、模型判断、工具观察、验证、收口转成用户语义 | 渲染 CSS |
| `session_timeline.py` | 把公开状态挂到正确 assistant turn，支持刷新恢复 | 临时猜测任务意图 |
| `public_chat_timeline.py` | 输出主会话可渲染 item | 展示原始工具名和事件名 |
| 前端 store | 合并 live draft 与 persisted attachment | 推断业务意义 |
| `PublicRunActivity` | 排版、折叠、响应式、可读性 | 用 regex 修复后端语义 |

关键原则：后端拥有公开语义，前端只负责呈现和轻量去重。

## 数据模型

### 公开执行状态

在 `SessionRuntimeAttachment` 中新增或稳定这些字段：

```ts
type PublicExecutionState = {
  opening?: {
    text: string;
    state: "thinking" | "done" | "error";
  };
  todo_plan?: {
    plan_id: string;
    active_item_id: string;
    completion_ready: boolean;
    items: Array<{
      todo_id: string;
      content: string;
      active_form?: string;
      status: "pending" | "in_progress" | "completed" | "blocked";
      notes?: string;
      updated_at?: number;
    }>;
  };
  observations?: Array<{
    item_id: string;
    title: string;
    detail: string;
    implication?: string;
    state: "running" | "done" | "error";
    trace_refs?: string[];
  }>;
  final_summary?: {
    text: string;
    verified?: string[];
    remaining_risks?: string[];
  };
};
```

不把这套模型暴露为“工具状态”。它是用户级执行状态。

### Public Chat Timeline Item

扩展现有 `PublicChatTimelineItem`，增加用户语义 item：

```ts
type PublicChatTimelineItem =
  | { kind: "opening_judgment"; text: string; state: "running" | "done" | "error" }
  | { kind: "todo_plan"; title: string; items: PublicTodoItem[]; active_item_id?: string; state: "running" | "done" }
  | { kind: "observation_report"; title: string; detail: string; implication?: string; state: "done" | "error" }
  | existing_public_timeline_items;
```

前端组件可以把 `todo_plan` 渲染成三到五行紧凑清单，超过折叠，不要求用户横向拖拽，也不展示 tool 名。

## 实施计划

### Phase 1 - 后端 todo 状态纳入公开投影

文件：

- `backend/capability_system/tools/tool_units/agent_todo_tool.py`
- `backend/harness/runtime/session_timeline.py`
- 新文件：`backend/harness/runtime/public_execution_state.py`
- `backend/tests/agent_todo_tool_regression.py`
- `backend/tests/runtime_progress_presenter_regression.py`
- `backend/tests/runtime_monitor_projection_test.py`

任务：

1. 保留 `agent_todo_tool.py` 的真实落盘能力，但补齐可公开读取的 normalized plan 输出。
2. 新增 `public_execution_state.py`，从近期 events 中识别最新 todo plan：
   - `agent_todo_initialized`
   - `task_tool_observation_recorded` 中的 `agent_todo` 结构化结果
   - `turn_tool_observation_recorded` 中的 `agent_todo` 结构化结果
3. `session_timeline.py` 在生成 attachment 时附加 `public_execution_state.todo_plan`。
4. `public_chat_timeline.py` 根据 todo plan 生成 `todo_plan` item。
5. 原始 `agent_todo` JSON 继续不直接展示。

验收：

- 刷新会话后，主页面仍能看到同一个 todo 清单和当前项。
- todo 清单不显示 `agent_todo`、`plan_id`、JSON。
- 每个任务最多一个 `in_progress`。
- 完成态清单显示为已完成，不继续转圈。

### Phase 2 - 开局判断成为公开事件

文件：

- `backend/harness/runtime/progress_presenter.py`
- `backend/harness/runtime/public_timeline_stream.py`
- `backend/harness/runtime/public_chat_timeline.py`
- `frontend/src/components/chat/ChatMessage.tsx`
- `frontend/src/components/chat/agentRunPresentation.ts`

任务：

1. 后端优先使用 `model_action_request.public_progress_note` / `public_action_state.current_judgment` 生成 `opening_judgment`。
2. 没有明确判断时，只使用与当前动作相关的安全 fallback：
   - 读取项目约定
   - 定位调用链
   - 校验输出
   - 等待用户确认
3. 前端 `AssistantOutputSignal` 消费 `opening_judgment`，不再从工具活动里硬猜“开局判断”。
4. 对没有工具的普通回答，不显示开局框。

验收：

- 一开始就有自然反馈，而不是只转工具。
- 文案像 agent 对用户说话，不像开发说明。
- 没有有效判断时不硬凑一句。

### Phase 3 - 工具观察转成观察报告

文件：

- `backend/harness/runtime/progress_presenter.py`
- `backend/harness/runtime/public_chat_timeline.py`
- `backend/harness/runtime/public_timeline_stream.py`
- `frontend/src/components/chat/PublicRunActivity.tsx`
- `frontend/src/components/chat/agentRunPresentation.ts`

任务：

1. 后端生成 `observation_report`，字段必须包含：
   - 动作返回结果
   - 用户可理解观察
   - 对下一步的含义
2. 针对常见工具族做后端语义映射：
   - read/path/list：读到了什么，是否足以判断
   - search：命中或未命中，下一步是否需要换入口
   - write/edit：改了什么，下一步需要验证
   - terminal：验证结果通过/失败/需继续修
   - todo：更新处理清单，不作为工具观察展示
3. 前端删除“工具已完成/工具返回成功”作为主展示文案的路径。
4. 前端可以继续缩短路径，但不再决定观察含义。

验收：

- 工具返回后有“观察：...”。
- 不展示“工具返回成功，正在根据结果继续”。
- 观察报告能说明为什么下一步这样做。
- 失败时显示一个阻塞说明和恢复建议，不喷原始堆栈。

### Phase 4 - 最终总结收口

文件：

- `backend/harness/runtime/progress_presenter.py`
- `backend/harness/runtime/public_chat_timeline.py`
- `backend/harness/runtime/session_timeline.py`
- `frontend/src/components/chat/PublicRunActivity.tsx`
- `frontend/src/components/chat/ChatMessage.tsx`

任务：

1. 后端用这些来源合成一个最终总结：
   - assistant final answer
   - progress presentation closeout
   - completed todo items
   - artifact refs
   - verification evidence
2. final summary 必须说明：
   - 完成内容
   - 验证情况
   - 产物位置
   - 未覆盖风险
3. 如果 assistant 正文已经包含相同总结，`final_summary` 不重复渲染。
4. 如果任务只是普通直接回答，不生成额外 final summary 卡片。

验收：

- 完成后有充分总结，而不是一句“已完成”。
- 不重复显示同一段总结。
- 有产物/验证时明确列出。

### Phase 5 - 前端呈现优化

文件：

- `frontend/src/components/chat/PublicRunActivity.tsx`
- `frontend/src/components/chat/ChatMessage.tsx`
- `frontend/src/components/chat/agentRunPresentation.ts`
- `frontend/src/components/chat/PublicRunActivity.test.ts`
- `frontend/src/app/globals.css`

任务：

1. `PublicRunActivity` 支持：
   - `opening_judgment`
   - `todo_plan`
   - `observation_report`
   - existing `tool_activity/artifact/final_summary/blocked`
2. todo 清单紧凑展示：
   - 当前项突出
   - 已完成项弱化
   - 待处理项最多展示 3 条，剩余折叠
   - 不需要用户横向拖拽
3. 视觉调整：
   - 字体略小，和主会话框对齐，略微往左但不过左。
   - 长内容自动换行，多一行也不要产生横向滚动。
   - 不用大卡片堆叠，保持内联、安静、可信。
4. 删除不再使用的旧样式块，避免继续在 `globals.css` 多层覆盖。

验收：

- 主会话反馈宽度接近会话框，略往左。
- 字体更小但可读。
- 长路径/长命令不撑破布局。
- 用户不需要往左拉清空或查看内容。
- 页面读起来像 agent 在工作，而不是工具面板。

## 测试计划

后端：

```powershell
pytest backend/tests/agent_todo_tool_regression.py -q
pytest backend/tests/runtime_progress_presenter_regression.py -q
pytest backend/tests/runtime_monitor_projection_test.py -q
```

前端：

```powershell
cd frontend
npx vitest run src/components/chat/PublicRunActivity.test.ts src/components/chat/ChatMessage.test.ts src/lib/runtimeVisibilityProjection.test.ts src/lib/store/runtime.test.ts
npx tsc --noEmit
```

固定端口实测：

```powershell
cd backend
python run_uvicorn.py --host 127.0.0.1 --port 8003

cd frontend
npm run dev -- --hostname 127.0.0.1 --port 3000
```

浏览器验证使用本地 Edge，验证四类任务：

1. 普通直接回答：不出现执行面板。
2. 长工具任务：开局判断、todo 清单、观察报告持续更新。
3. 刷新页面：todo 清单和当前进度恢复。
4. 完成任务：有充分总结，不重复，不显示工具名。

## 删除规则

必须删除或停用：

- 主会话中展示 `agent_todo` 工具名的路径。
- 把原始 todo JSON 当作 observation 的路径。
- “工具返回成功，正在根据结果继续”这类主文案。
- 前端把工具名作为主要展示内容的 fallback。
- 不再使用的旧 CSS 覆盖块。

允许保留：

- monitor/debug 里的原始 trace ref。
- `progress_entries` 作为调试/监控输入。
- `agent_todo` 文件落盘作为真实状态存储。

禁止：

- 为了过测试硬编码某个 demo 文案。
- 用前端 regex 当主要语义层。
- 为兼容旧显示链路保留两套主会话进展组件。
- 把开发说明写成给 agent 的 prompt。

## 完成标准

- 用户能看到 agent 开局在判断，而不是无声转工具。
- 用户能看到任务清单，而且刷新后还在。
- 用户能看到每次关键动作后的观察报告。
- 用户不会看到 todo/tool/event 这些开发词作为主反馈。
- 完成后有充分总结，说明做了什么、验证了什么、风险是什么。
- 所有 live SSE 与刷新恢复后的显示一致。
- 测试和固定端口页面实测通过。
