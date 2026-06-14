# Agent Runtime 单一行为协议重构计划书

状态：待审阅  
日期：2026-06-14  
范围：行为协议、当前工作边界、active work 控制、工具生命周期、公开投影、前端消费与测试体系。  
约束：本文只基于当前代码逻辑和本地成熟实现源码，不引用旧项目文档。

## 1. 目的

本计划用于修复当前 agent 运行链路中的结构性问题：

- 用户输入“继续”等控制命令时，被当前工作边界误判或阻止。
- 当前项目同时存在多套可解释用户意图的协议，导致行为串线。
- 工具生命周期在 UI 中重复或无法明确收口。
- 公开投影可能把旧时序、旧任务或旧状态挂到新对话轮次中。
- closeout/正文收口后，timeline 仍暴露不该继续显示的运行过程。
- `turn_id`、`turn_run_id`、`run_id`、`task_run_id` 等身份字段没有被严格分层使用。

目标不是补一个“继续”关键词，也不是让 UI 隐藏症状，而是把 runtime 主链路收敛成成熟 coding agent 风格的单一行为协议：

```text
RequestFacts
-> CurrentWorkPermit
-> ContextCandidates
-> ModelActionRequest
-> ActionPermit
-> RuntimeStartPacket
-> ExecutionLoop
-> PublicProjection
-> OutputCommit
```

## 2. 当前破坏点

### 2.1 根因

当前代码中至少三套结构可以解释或裁决同一个用户输入：

- `CurrentWorkBoundaryDecision`：在 `backend/harness/entrypoint/current_work_boundary.py` 中，由当前工作边界模型或硬规则选择 `boundary_action`。
- `ModelActionRequest`：在 `backend/harness/loop/model_action_protocol.py` 中，由主模型输出 `action_type`，包括 `respond`、`tool_call`、`request_task_run`、`active_work_control`。
- `ActiveWorkTurnDecision`：在 `backend/harness/loop/active_work.py` 中，再次解析 active work 控制动作、关系和执行策略。

这导致一个控制请求可能先被 current-work 边界要求输出 `action` 或 `boundary_action`，再被主模型协议要求输出 `action_type=active_work_control`，最后又被 active-work 执行层解析一遍。

### 2.2 “继续”被阻止的直接代码原因

`backend/harness/entrypoint/current_work_boundary.py:290` 的 `current_work_boundary_decision_from_payload()` 只读取顶层：

```text
raw.get("action") or raw.get("boundary_action")
```

如果模型按主协议输出：

```json
{
  "action_type": "active_work_control",
  "active_work_control": {
    "action": "continue_active_work"
  }
}
```

边界解析器读不到顶层 `action`，会走：

```text
_model_boundary_denied(..., "boundary_action_required")
```

`backend/harness/entrypoint/current_work_boundary.py:429` 的 `_model_boundary_denied()` 在 `active_turn_input_policy=steer` 时返回 `block`。这就是“继续是用户命令，却被边界阻止”的结构性原因。

这不是提示词措辞问题，也不是某个关键词识别问题，而是两套行为协议形状不一致。

### 2.3 工具重复与生命周期噪音

当前投影层已有工具生命周期约束，但身份字段需要继续收紧：

- `backend/harness/runtime/projection/projector.py:31` 的 `ProjectionLifecycleState` 已追踪生命周期状态。
- `backend/harness/runtime/projection/projector.py:390`、`:434`、`:460` 要求工具事件带 `tool_call_id` 与 `permission_decision_id`。
- `backend/api/chat.py:2036`、`:2063`、`:2127` 从 runtime/admission/observation 提取工具生命周期字段。
- `frontend/src/lib/projection/reducer.ts:476` 使用 `tool_call_id`、`tool_lifecycle_id` 合并 timeline item。

剩余风险是：如果 request、permission、started、completed 在不同层用不同 identity 生成公开 item，前端只能“看起来合并”，但 producer 层仍可能发出重复生命周期。

### 2.4 投影旧时序串入新时序

公开投影锚点当前来自：

- `backend/harness/runtime/projection/authority.py:56` `build_public_projection_frame()`
- `backend/harness/runtime/projection/authority.py:156` `projection_anchor()`
- `backend/api/chat.py:391` `PublicTurnOutputContext`
- `backend/api/chat.py:415` `ChatTaskBridgeContext`
- `frontend/src/lib/projection/reducer.ts:578` `streamAnchorMatchesFrame()`
- `frontend/src/lib/projection/reducer.ts:616` `projectionAnchorsAreCompatible()`

正确方向已经出现：投影必须按 `session_id + turn_id + turn_run_id + task_run_id/stream_run_id` 组合锚定，而不是只看当前 active task 或一个裸 `task_run_id`。

需要继续重构的是：`run_id` 目前在 public anchor 中常表示 chat stream run，而 task event 的 `run_id` 常表示 task run/event log run。这个字段名复用会让后续维护者把 transport run 和 task run 混用。后续实现中应把内部路由统一改为显式字段：`stream_run_id`、`turn_run_id`、`task_run_id`，公开兼容字段 `run_id` 不得作为 reducer 的强匹配主键。

## 3. 源代码依据

### 3.1 当前项目证据

行为协议与边界：

- `backend/harness/entrypoint/current_work_boundary.py:11` 定义 `CurrentWorkBoundaryAction`。
- `backend/harness/entrypoint/current_work_boundary.py:72` 定义 `CurrentWorkBoundaryDecision`。
- `backend/harness/entrypoint/current_work_boundary.py:120` 定义 `CurrentWorkBoundaryReceipt`。
- `backend/harness/entrypoint/current_work_boundary.py:174` `decide_current_work_boundary()` 执行硬边界裁决。
- `backend/harness/entrypoint/current_work_boundary.py:290` `current_work_boundary_decision_from_payload()` 解析模型边界输出。
- `backend/harness/entrypoint/current_work_boundary.py:429` `_model_boundary_denied()` 把缺失边界动作转成 `ask_user` 或 `block`。
- `backend/harness/loop/model_action_protocol.py:8` 定义 `ModelActionType`。
- `backend/harness/loop/model_action_protocol.py:17` 仍定义 `CurrentWorkBoundaryActionType`。
- `backend/harness/loop/model_action_protocol.py:95` 定义 `CurrentWorkBoundaryActionRequest`，这是第二套边界动作对象。
- `backend/harness/loop/model_action_protocol.py:121` `model_action_request_from_payload()` 是主模型动作解析器。
- `backend/harness/loop/model_action_protocol.py:217` 在主协议中解析 `active_work_control`。
- `backend/harness/loop/active_work.py:128` 定义 `ActiveWorkTurnDecision`。
- `backend/harness/loop/active_work.py:147` `active_work_turn_decision_from_payload()` 再次解释 active work 控制。

runtime 主链路：

- `backend/harness/entrypoint/runtime_facade.py:503` 每轮先执行 `_decide_current_work_boundary_for_turn()`。
- `backend/harness/entrypoint/runtime_facade.py:751` `_decide_current_work_boundary_for_turn()` 构造边界输入。
- `backend/harness/entrypoint/runtime_facade.py:799` `_run_current_work_boundary_model()` 单独编译并调用边界模型。
- `backend/harness/entrypoint/runtime_facade.py:850` `_current_work_boundary_terminal_events()` 能直接终止本轮。
- `backend/harness/entrypoint/runtime_facade.py:898` `_run_current_work_control_receipt()` 执行 current-work 控制 receipt。
- `backend/harness/entrypoint/runtime_facade.py:1644` `_apply_active_work_turn_decision()` 再执行 active work 决策。
- `backend/harness/entrypoint/runtime_facade.py:1718` `_apply_continue_active_work()` 实际继续 active work。

compiler 与 prompt/packet：

- `backend/harness/runtime/compiler.py:346` `compile_single_agent_turn_packet()` 是主单轮 packet 编译入口。
- `backend/harness/runtime/compiler.py:385` 读取 `current_work_boundary_receipt` 决定允许动作。
- `backend/harness/runtime/compiler.py:787` `compile_current_work_boundary_packet()` 是单独边界模型 packet，目标方案应从主路径移除。
- `backend/harness/runtime/compiler.py:2390` `_receipt_allowed_action_types()` 从 receipt 反推下一 packet 允许动作。
- `backend/harness/runtime/compiler.py:2401` `_current_work_boundary_receipt_model_visible_payload()` 把边界 receipt 暴露给模型。
- `backend/harness/runtime/compiler.py:4084` `_model_decision_contract_payload()` 生成主模型动作契约。

single-agent loop：

- `backend/harness/loop/single_agent_turn.py:864` 收到 `active_work_control` 后认为必须由 current-work boundary 处理。
- `backend/harness/loop/single_agent_turn.py:1589` `active_work_control_final_dispatch_unreachable` 是最终分发不可达错误。
- `backend/harness/loop/single_agent_turn.py:2353` `_single_agent_action_request_from_response()` 是主模型响应解析入口。
- `backend/harness/loop/single_agent_turn.py:2660` `_is_model_action_json_payload()` 识别主动作 JSON。

公开投影与 API：

- `backend/harness/runtime/projection/authority.py:56` 生成 public projection frame。
- `backend/harness/runtime/projection/authority.py:156` 生成 projection anchor。
- `backend/harness/runtime/projection/projector.py:203` `projection_spec_for_event()` 按事件生成投影 spec。
- `backend/harness/runtime/projection/projector.py:232` `runtime_status` 目前会进入 `_status_spec()`。
- `backend/harness/runtime/projection/projector.py:543` `_commit_spec()` 是正文提交权威。
- `backend/harness/runtime/projection/projector.py:599` `_turn_terminal_spec()` 是轮次终止投影。
- `backend/harness/runtime/projection/projector.py:620` `_status_spec()` 当前把 runtime status 变为可见 status。
- `backend/harness/runtime/projection/projector.py:733` `_hidden_trace_spec()` 是 trace-only 目标形态。
- `backend/api/chat.py:161` 允许 `active_task_steer_accepted` 进入公开投影。
- `backend/api/chat.py:165` 允许 `runtime_status` 进入公开投影。
- `backend/api/chat.py:1842` `_project_public_stream_event()` 执行 public event 投影。
- `backend/api/chat.py:2426` `_attach_public_projection_frame()` 挂载 public projection frame。

前端消费：

- `frontend/src/lib/api.ts:337` 定义 `PublicProjectionFrame` 类型。
- `frontend/src/lib/projection/reducer.ts:36` `applyPublicProjectionFrame()` 是 reducer 入口。
- `frontend/src/lib/projection/reducer.ts:49` 更新 `activeTurnSnapshot`。
- `frontend/src/lib/projection/reducer.ts:257` 处理 `item_retire`。
- `frontend/src/lib/projection/reducer.ts:295` `commit_ack` 是正文提交权威。
- `frontend/src/lib/projection/reducer.ts:307` `turn_terminal` 处理终止态。
- `frontend/src/lib/projection/reducer.ts:476` `timelineItemFromFrame()` 生成 timeline item。
- `frontend/src/lib/projection/reducer.ts:578` `streamAnchorMatchesFrame()` 匹配 stream anchor。
- `frontend/src/lib/store/events.ts:1178` 读取 `public_projection_frame`。
- `frontend/src/lib/store/events.ts:1186` 调用 reducer 应用投影。
- `frontend/src/lib/store/runtime.ts:1612` steer 请求携带 `expected_active_turn_id`。
- `frontend/src/lib/store/runtime.ts:1613` steer 请求携带 `active_turn_input_policy=steer`。
- `frontend/src/lib/store/runtime.ts:2741` 普通输入携带 `expected_active_turn_id`。
- `frontend/src/lib/store/runtime.ts:2742` 普通输入携带 `active_turn_input_policy=auto`。
- `frontend/src/components/chat/ChatMessage.tsx:362` 从 projection 生成公开 timeline。
- `frontend/src/components/chat/ChatMessage.tsx:383` 判断 projection body 是否已关闭。
- `frontend/src/components/chat/PublicTimelineActivity.tsx:27` 渲染工具/状态 timeline。

### 3.2 本地成熟实现参考

Codex 本地源码：

- `D:\AI应用\openai-codex\codex-rs\protocol\src\protocol.rs:498` `Op` 是客户端提交协议。
- `D:\AI应用\openai-codex\codex-rs\protocol\src\protocol.rs:1160` `EventMsg` 是 agent 事件协议。
- `D:\AI应用\openai-codex\codex-rs\protocol\src\models.rs:754` `ResponseItem` 统一表达 `Message`、`FunctionCall`、`FunctionCallOutput` 等模型输出。
- `D:\AI应用\openai-codex\codex-rs\core\src\session\turn.rs:1849` 与 `:1892` 在同一 turn loop 内处理消息和函数调用。

Claude Code 本地源码：

- `D:\AI应用\claude-code-nb-main\query.ts:552` 维护 `toolResults`。
- `D:\AI应用\claude-code-nb-main\query.ts:554` 明确注释 `stop_reason === 'tool_use'` 不可靠。
- `D:\AI应用\claude-code-nb-main\query.ts:557` 使用 `toolUseBlocks` 作为工具 loop 的实际信号。
- `D:\AI应用\claude-code-nb-main\query.ts:731` 重试时防止旧 `tool_use_id` 的 orphan tool result 泄漏。
- `D:\AI应用\claude-code-nb-main\utils\messages.ts:1146` `MessageLookups` 建立 tool_use/result 映射。
- `D:\AI应用\claude-code-nb-main\utils\messages.ts:5119` `ensureToolResultPairing()` 校验和修复工具 use/result 配对。

参考结论：

- 成熟系统可以有多个事件类型、状态类型和展示类型。
- 但模型行为决策应只有一个主协议。
- 工具生命周期必须用稳定 identity 贯穿 request、permission、start、result、failure、retry、replay。
- 边界层负责许可，不负责重新解释用户语义。

## 4. 设计取舍

### 4.1 采用

- 采用 Codex 风格：模型输出协议集中在一个行为 contract 中，消息、工具调用、结果观察属于同一 turn loop。
- 采用 Claude Code 风格：工具生命周期以工具调用 id 贯穿，并在 retry/replay 时拒绝旧 id 泄漏。
- 采用项目内已有 `ActionPermit`：`backend/harness/loop/action_permit.py` 已存在动作许可层，current-work 边界应收敛到 permit 思路。

### 4.2 不采用

- 不保留 current-work boundary 的独立模型动作协议。
- 不让 UI 作为重复工具、旧时序、私有状态的第一道防线。
- 不通过关键词扩展修复“继续”。
- 不保留 `CurrentWorkBoundaryActionRequest` 这类没有主路径权威的旧结构。
- 不让 `ActiveWorkTurnDecision` 再次决定用户语义；它只能成为已授权动作的执行参数或执行结果。

## 5. 目标权责链

| 层 | 目标职责 | 不允许做的事 | 目标代码位置 |
| --- | --- | --- | --- |
| RequestFacts | 记录用户文本、附件、session、active-turn hint | 猜测用户意图、选择动作 | `backend/harness/runtime/request_facts.py`、`backend/api/chat.py` |
| CurrentWorkPermit | 确认当前输入是否允许控制已有 active work | 输出第二套模型动作、替模型决定语义 | 重写 `backend/harness/entrypoint/current_work_boundary.py` |
| ContextCandidates | 提供 active work、session、tool、project 上下文候选 | 把候选变成隐藏命令 | `backend/harness/runtime/compiler.py` |
| ModelActionRequest | 唯一模型行为协议 | 自授权限、绕过 permit | `backend/harness/loop/model_action_protocol.py` |
| ActionPermit | 授权或拒绝动作执行 | 改写用户目标为替代动作 | `backend/harness/loop/admission.py`、`backend/harness/loop/action_permit.py` |
| ExecutionLoop | 执行已许可动作并产出观察 | 重新解释“继续/暂停/替换”等语义 | `backend/harness/loop/single_agent_turn.py`、`backend/harness/entrypoint/runtime_facade.py`、`backend/harness/loop/task_executor.py` |
| PublicProjection | 将事件投影为公开 frame | 决定语义、隐藏 producer 已经发错的事件 | `backend/harness/runtime/projection/*`、`backend/api/chat.py` |
| UI Present | 渲染公开 frame 和最终正文 | 作为安全边界或生命周期修复层 | `frontend/src/lib/projection/reducer.ts`、`frontend/src/components/chat/*` |

## 6. 固定执行流

```text
1. 用户输入进入 ChatRequest
   输入：message, session_id, expected_active_turn_id, active_turn_input_policy
   输出：RequestFacts
   权威：API/runtime request layer

2. runtime 查询 active turn 状态
   输入：RequestFacts, state_index active turn/task run
   输出：CurrentWorkPermit
   权威：CurrentWorkPermit
   禁止：调用模型重新选择 boundary_action

3. compiler 编译主 single-agent packet
   输入：RequestFacts, ContextCandidates, CurrentWorkPermit
   输出：RuntimeStartPacket，allowed_action_types
   权威：RuntimeCompiler
   禁止：从旧 boundary receipt 反推第二套行为协议

4. 模型只输出 ModelActionRequest
   输入：RuntimeStartPacket
   输出：respond/tool_call/request_task_run/active_work_control/block/ask_user
   权威：ModelActionRequest

5. admission/action permit 校验动作
   输入：ModelActionRequest, CurrentWorkPermit, permission policy
   输出：ActionPermit 或 denial observation
   权威：ActionPermit

6. execution loop 执行动作
   输入：ActionPermit + action payload
   输出：observation/lifecycle event/final body candidate
   权威：ExecutionLoop
   禁止：把拒绝改成新任务或继续旧任务

7. public projection 生成公开 frame
   输入：runtime events
   输出：public_projection_frame
   权威：PublicProjection
   禁止：没有强锚点的 frame 进入主视图

8. commit gate 收口正文
   输入：commit_ack/commit_failed/turn_terminal
   输出：final assistant body 与 retired transient timeline
   权威：OutputCommit
```

## 7. 数据与协议变更

### 7.1 ModelActionRequest 成为唯一行为协议

保留并强化：

```json
{
  "authority": "harness.loop.model_action_request",
  "action_type": "active_work_control",
  "active_work_control": {
    "action": "continue_active_work",
    "relation_to_current_work": "current_work",
    "response": "..."
  }
}
```

要求：

- `active_work_control.action` 是控制动词，例如 `continue_active_work`、`append_instruction_to_active_work`、`pause_active_work`、`stop_active_work`。
- 不再接受 bare `{"action":"continue_active_work"}` 作为主模型行为。
- 不再要求模型先输出 `current_work_boundary_decision`。

### 7.2 CurrentWorkBoundary 降级为 CurrentWorkPermit

目标结构：

```json
{
  "authority": "harness.entrypoint.current_work_permit",
  "permit_id": "cwpermit:<turn_id>",
  "decision": "allow|deny|needs_user",
  "allows": {
    "active_work_control": true,
    "request_task_run": false
  },
  "active_work_ref": {
    "active_turn_id": "...",
    "task_run_id": "..."
  },
  "expected_active_turn_id": "...",
  "actual_active_turn_id": "...",
  "task_run_id": "...",
  "denied_reason": ""
}
```

要求：

- 它只回答“是否允许控制当前 active work”，不回答“模型应该做什么动作”。
- `boundary_action`、`allowed_action_types_for_next_packet`、`active_work_control_payload` 不再作为主链路权威字段。
- `current_work_boundary_receipt` 仅允许作为迁移期内部诊断名出现；实施完成后改名为 `current_work_permit`，并清理旧字段。

### 7.3 ActiveWorkTurnDecision 降级

目标：

- `active_work.py` 只负责校验和规范化已授权控制动作。
- `ActiveWorkTurnDecision` 改为 `ActiveWorkControlResult` 或执行参数/结果对象。
- relation、answer obligation、continuation strategy 不再作为第二模型裁决来源。

### 7.4 ID 分层规范

| 字段 | 目标含义 | 可否作为强匹配主键 | 说明 |
| --- | --- | --- | --- |
| `turn_id` | 用户可理解的一轮对话逻辑 id | 是，但需配合 session | 一轮用户输入/助手回应的逻辑身份 |
| `turn_run_id` | 本轮执行实例 id | 是 | retry/resume/reconnect 时区分同一 turn 的执行实例 |
| `stream_run_id` | chat SSE/API stream run id | 是 | 替代内部使用的裸 `run_id` |
| `task_run_id` | task executor 或 agent task run id | 是，但不可单独匹配 assistant turn | 旧 task event 不得只凭它进入当前 assistant |
| `run_id` | 历史泛用字段 | 否 | 后续只能作为外部兼容/诊断别名，不作为 reducer 强匹配主键 |
| `tool_call_id` | 工具调用生命周期 id | 是 | request/start/completed/failure/replay 合并主键 |
| `permission_decision_id` | 权限/admission 决策 id | 是，但不替代 `tool_call_id` | 用于证明 start 在 permission 之后 |

## 8. 修改位置审查

### 8.1 后端行为协议

| 文件 | 当前角色 | 修改动作 | 完成条件 |
| --- | --- | --- | --- |
| `backend/harness/loop/model_action_protocol.py` | 主模型动作协议，但夹带 `CurrentWorkBoundaryActionRequest` | 删除 `CurrentWorkBoundaryActionType`、`CurrentWorkBoundaryActionRequest`；强化 `active_work_control.action` | `ModelActionRequest` 是唯一模型行为对象 |
| `backend/harness/loop/single_agent_turn.py` | 主 turn loop，但把 `active_work_control` 当作 boundary 后错误 | 移除 `active_work_control_must_be_handled_by_current_work_boundary` 不可达错误；让主 loop 接受已 permit 的 active work control | `active_work_control` 不再被二次协议挡住 |
| `backend/harness/loop/admission.py` | 动作 admission | 增加 current-work permit 参与 active_work_control admission | 未获 permit 的控制动作输出 denial observation |
| `backend/harness/loop/action_permit.py` | 已有动作许可对象 | 保留并扩展 active_work_control permit 字段 | permit 能表达 active work 控制授权 |

### 8.2 当前工作边界

| 文件 | 当前角色 | 修改动作 | 完成条件 |
| --- | --- | --- | --- |
| `backend/harness/entrypoint/current_work_boundary.py` | 同时做硬边界、模型边界动作解析、receipt 生成 | 重写为 deterministic `CurrentWorkPermit`；删除模型 payload parser 的主链路权威 | 不再存在 `current_work_boundary_decision_from_payload()` 主路径调用 |
| `backend/harness/entrypoint/runtime_facade.py` | 每轮先跑 boundary model，再按 receipt 分叉 | `_decide_current_work_boundary_for_turn()` 改为 permit 生成；移除 `_run_current_work_boundary_model()` 主路径；active work control 进入主模型协议/permit/admission/execute 链路 | “继续”不再需要 boundary model 先输出 `boundary_action` |
| `backend/harness/runtime/compiler.py` | 编译主 packet 与 boundary packet | 删除或停用 `compile_current_work_boundary_packet()` 主路径；`compile_single_agent_turn_packet()` 读取 `current_work_permit` | compiler 不再暴露第二套 boundary action contract |

### 8.3 Active Work 执行

| 文件 | 当前角色 | 修改动作 | 完成条件 |
| --- | --- | --- | --- |
| `backend/harness/loop/active_work.py` | 解析 active work 控制并产出 decision | 改为规范化执行参数和结果；不再做语义裁决 | active work 只执行已授权动作 |
| `backend/harness/entrypoint/runtime_facade.py` | 执行 continue/pause/stop/append/replacement | `_apply_active_work_turn_decision()` 改为接收 `ModelActionRequest + ActionPermit` | 执行层不再读 `boundary_action` 判断语义 |
| `backend/harness/loop/task_executor.py` | task run 执行 loop/admission/tool | 保持 admission/permit 模式，与 turn loop 的 active work control 统一事件与观察形状 | 任务执行和单轮执行共享许可语义 |

### 8.4 公开投影后端

| 文件 | 当前角色 | 修改动作 | 完成条件 |
| --- | --- | --- | --- |
| `backend/harness/runtime/projection/authority.py` | public frame 与 anchor 权威 | anchor 增加/标准化 `stream_run_id`；禁止内部强依赖裸 `run_id` | frame anchor 能区分 stream、turn run、task run |
| `backend/harness/runtime/projection/projector.py` | runtime event 到 projection spec | `runtime_status` 默认 trace-only；只允许白名单 public status 入 timeline；工具生命周期继续强制 permission/start/result 顺序 | boundary/status 噪音不再显示成公开 activity |
| `backend/api/chat.py` | public stream/event bridge | `_project_public_stream_event()` 和 `_attach_public_projection_frame()` 统一 anchor 字段；拒绝缺少 turn context 的正文/工具/commit 事件 | 旧 task/turn terminal 不会进入新 assistant |
| `backend/runtime/output_stream/public_contract.py` | public event 常量 | 如需新增 public status kind，在这里定义可公开事件边界 | public contract 不靠字符串散落 |
| `backend/runtime/shared/tool_identity.py` | 工具/权限 identity | 保留 `permission_decision_id()`；确保 tool lifecycle 主键以 `tool_call_id` 为中心 | 工具重复从 producer 层被阻止 |

### 8.5 前端 reducer、store、UI

| 文件 | 当前角色 | 修改动作 | 完成条件 |
| --- | --- | --- | --- |
| `frontend/src/lib/api.ts` | public projection 类型 | 明确 `stream_run_id`、`turn_run_id`、`task_run_id`、`tool_call_id` 字段语义；降低 `run_id` 地位 | 类型层阻止 run_id 混用 |
| `frontend/src/lib/projection/reducer.ts` | public frame reducer | strong anchor 必须匹配 `session_id + turn_id/turn_run_id + stream/task`；commit 后 retire transient；tool timeline 以 `tool_call_id` 合并 | 旧 frame、重复工具、已收口 timeline 被结构性拒绝 |
| `frontend/src/lib/store/events.ts` | stream event 分发 | 只把合法 `public_projection_frame` 交给 reducer；缺 anchor 的 frame 不创建 visible message | store 不创造幽灵消息 |
| `frontend/src/lib/store/runtime.ts` | 发送 chat run/active input | steer/auto 输入都明确传 `expected_active_turn_id` 与 policy；避免从 stale snapshot 发错 active turn | “继续”命令绑定当前 active turn |
| `frontend/src/components/chat/ChatMessage.tsx` | 消息渲染 | body committed/finalized 后只显示正文，transient timeline 只在未收口时显示 | UI 与 commit gate 一致 |
| `frontend/src/components/chat/PublicTimelineActivity.tsx` | timeline 渲染 | 不承担生命周期修复，只渲染 reducer 已合并的 public item | UI 不再是修复层 |
| `frontend/src/components/chat/ChatPanel.tsx` | 消息列表容器 | 确认 projection 消息归属和 closeout 展示一致 | 多轮消息不串线 |

### 8.6 测试审查

必须重写或删除保护旧结构的测试：

- `backend/tests/current_work_boundary_regression.py`
  - 当前直接导入 `CurrentWorkBoundaryDecision`、`current_work_boundary_decision_from_payload()`、`compile_current_work_boundary_packet()`。
  - 目标：改为 `CurrentWorkPermit` 行为测试；删除保护旧 boundary action 的用例。
- `backend/tests/harness_model_action_protocol_regression.py`
  - 保留主协议 strict JSON 测试。
  - 修改 `active_work_control` 用例，断言唯一合法形状是 `ModelActionRequest`。
- `backend/tests/active_turn_authority_regression.py`
  - 改为验证 expected/actual active turn permit、mismatch denial、replacement cleanup。
- `backend/tests/dynamic_prompt_context_projection_test.py`
  - 更新 `current_work_boundary_receipt` 文案/字段，确保 prompt 是 agent 可执行职责说明，不是开发说明。
- `backend/tests/public_projection_contract_test.py`
  - 增加 runtime_status trace-only、old anchor rejection、tool lifecycle identity 测试。
- `frontend/src/lib/projection/reducer.test.ts`
  - 增加旧 `task_run_id` 不能挂新 turn、run_id 不作为强匹配、commit 后 retire transient 测试。
- `frontend/src/components/chat/ChatMessage.test.ts`
  - 增加正文收口后只显示正文、不显示 boundary/status 噪音测试。
- `frontend/src/components/chat/ChatPanel.test.ts`
  - 增加多轮投影归属测试。
- `frontend/src/lib/store/runtime.test.ts`
  - 增加 steer/auto active turn request payload 与 stale snapshot 测试。
- `frontend/src/lib/store/assistantStreamReplay.test.ts`
  - 增加 replay 不重复工具、不复活旧 terminal 测试。
- `frontend/src/lib/internalControlText.test.ts`
  - 确保内部控制文字不作为用户可见正文泄漏。

## 9. 连线审查矩阵

| 线 | 期望连接 | 当前证据 | 状态 | 必要修复 |
| --- | --- | --- | --- | --- |
| L1 | 用户“继续” -> active turn request payload | `frontend/src/lib/store/runtime.ts:1612`、`:1613` 发送 expected active turn 与 steer policy | 部分连接 | 后端不得再要求 boundary model 输出 `boundary_action` |
| L2 | request facts -> current work permit | `backend/harness/entrypoint/runtime_facade.py:751` 构造 boundary input | 破损 | 改为 deterministic permit，不调用 boundary model 决策动作 |
| L3 | current work permit -> model packet allowed actions | `backend/harness/runtime/compiler.py:385`、`:2390` 由 receipt 推 allowed actions | 破损 | receipt 改 permit，allowed actions 由 permit + main protocol 共同生成 |
| L4 | model output -> single action parser | `backend/harness/loop/model_action_protocol.py:121` 是主解析器 | 部分连接 | 删除 `CurrentWorkBoundaryActionRequest` 旧协议 |
| L5 | active_work_control -> execution | `backend/harness/loop/single_agent_turn.py:864` 当前将 active_work_control 视为错误 | 破损 | 让已 permit 的 active_work_control 进入执行链路 |
| L6 | action request -> action permit -> execution | `backend/harness/loop/action_permit.py` 已存在；task executor 已使用 admission/permit | 部分连接 | active_work_control 也接入 permit，不只 tool_call 接入 |
| L7 | tool request -> permission -> started -> completed | `backend/harness/runtime/projection/projector.py:390`、`:434`、`:460` 强制 id | 基本连接 | producer 层统一 `tool_call_id`，前端不再补救重复 |
| L8 | runtime event -> public projection anchor | `backend/harness/runtime/projection/authority.py:156` 生成 anchor | 部分连接 | 引入显式 `stream_run_id`，弱化裸 `run_id` |
| L9 | public frame -> reducer -> message | `frontend/src/lib/projection/reducer.ts:578` 匹配 anchor | 部分连接 | 强锚点不兼容时拒绝创建/更新可见 message |
| L10 | commit ack -> final body -> retire transient timeline | `frontend/src/lib/projection/reducer.ts:295` commit；`ChatMessage.tsx:383` 检测关闭 | 部分连接 | 后端也发出明确 retire/trace-only，UI 只渲染最终正文 |
| L11 | runtime_status -> public surface | `backend/harness/runtime/projection/projector.py:620` 默认可见 status | 破损 | 默认 trace-only，仅白名单 status 可见 |
| L12 | old terminal/replay -> current assistant | `backend/api/chat.py:1301` 有 task run mismatch 拒绝；前端已有 anchor 匹配 | 部分连接 | 补齐 turn_run/stream_run/task_run 组合拒绝与测试 |

## 10. 分阶段实施计划

### Phase 0：冻结设计

目标：用户确认本文后再开始代码实施。  
禁止：提前改 runtime 主链路。  
完成条件：本文经审阅通过，或用户指出需要调整的方向。

### Phase 1：冻结旧 boundary 模型裁决

文件：

- `backend/harness/entrypoint/current_work_boundary.py`
- `backend/harness/entrypoint/runtime_facade.py`
- `backend/harness/runtime/compiler.py`

改动：

- 停用 `_run_current_work_boundary_model()` 主路径。
- 将 `decide_current_work_boundary()` 改成生成 deterministic permit。
- 删除或隔离 `compile_current_work_boundary_packet()`。

完成条件：

- “继续”不需要模型先输出 `boundary_action`。
- 搜索主路径不存在 `current_work_boundary_decision_from_payload()` 调用。

### Phase 2：统一模型行为协议

文件：

- `backend/harness/loop/model_action_protocol.py`
- `backend/harness/loop/single_agent_turn.py`
- `backend/harness/loop/admission.py`
- `backend/harness/loop/action_permit.py`

改动：

- 删除 `CurrentWorkBoundaryActionRequest`。
- `ModelActionRequest` 成为唯一行为 contract。
- `active_work_control` 进入 admission/permit。
- bare active work JSON 明确拒绝为协议错误。

完成条件：

- 主模型动作解析只有 `ModelActionRequest`。
- `single_agent_turn.py` 不再把 active_work_control 视为 boundary 误入。

### Phase 3：收口 active work 执行

文件：

- `backend/harness/loop/active_work.py`
- `backend/harness/entrypoint/runtime_facade.py`
- `backend/harness/loop/task_executor.py`

改动：

- `active_work.py` 从“决策对象”改为“执行参数/结果对象”。
- `_apply_active_work_turn_decision()` 改名并改签名，接收已 permit 的 action。
- continue/append/pause/stop/replacement 都使用同一许可检查结果。

完成条件：

- active work 执行层不读取 `boundary_action`。
- mismatch active turn 返回 denial observation，不会自动变新任务或 block 用户命令。

### Phase 4：重建 public projection 边界

文件：

- `backend/harness/runtime/projection/authority.py`
- `backend/harness/runtime/projection/projector.py`
- `backend/api/chat.py`
- `backend/runtime/output_stream/public_contract.py`

改动：

- public anchor 显式包含 `stream_run_id`。
- `runtime_status` 默认 `trace_only`。
- current-work boundary/status 事件不进入 chat timeline。
- 工具 lifecycle producer 统一以 `tool_call_id` 为主生命周期 id。

完成条件：

- 缺少 turn context 的正文、工具、commit、terminal 不进入主视图。
- 旧 task terminal/status 无法挂载到新 assistant。

### Phase 5：前端 reducer 与 UI 收口

文件：

- `frontend/src/lib/api.ts`
- `frontend/src/lib/projection/reducer.ts`
- `frontend/src/lib/store/events.ts`
- `frontend/src/lib/store/runtime.ts`
- `frontend/src/components/chat/ChatMessage.tsx`
- `frontend/src/components/chat/PublicTimelineActivity.tsx`
- `frontend/src/components/chat/ChatPanel.tsx`

改动：

- reducer 使用强锚点组合匹配。
- commit 后 retire transient timeline。
- ChatMessage 在正文 finalized/committed 后只展示正文。
- PublicTimelineActivity 只展示 reducer 已确认的 timeline item。

完成条件：

- 工具不会重复显示。
- 收口后只显示正文。
- 旧时序投影不进入新消息。

### Phase 6：测试重写与清理

文件：

- 后端测试：`current_work_boundary_regression.py`、`harness_model_action_protocol_regression.py`、`active_turn_authority_regression.py`、`dynamic_prompt_context_projection_test.py`、`public_projection_contract_test.py`
- 前端测试：`reducer.test.ts`、`ChatMessage.test.ts`、`ChatPanel.test.ts`、`runtime.test.ts`、`assistantStreamReplay.test.ts`、`internalControlText.test.ts`

改动：

- 删除保护旧 boundary action/receipt 形状的测试。
- 增加 permit、strong anchor、tool lifecycle、commit gate、replay/old terminal 测试。

完成条件：

- 测试保护目标行为，不保护旧内部结构。
- 没有通过降低断言、跳过测试或 mock 核心逻辑制造通过。

## 11. 验证矩阵

后端 focused：

```powershell
python -m pytest backend/tests/current_work_boundary_regression.py backend/tests/active_turn_authority_regression.py backend/tests/public_projection_contract_test.py backend/tests/harness_model_action_protocol_regression.py -q
```

前端 focused：

```powershell
npm test -- --run src/lib/projection/reducer.test.ts src/components/chat/ChatMessage.test.ts src/components/chat/ChatPanel.test.ts src/lib/store/runtime.test.ts src/lib/store/assistantStreamReplay.test.ts
```

类型检查：

```powershell
npx tsc --noEmit
```

项目栈检查：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/project_stack.ps1 -Action check
```

涉及运行链路实施后，必须按项目固定端口真实启动：

- 前端：`http://127.0.0.1:3000`
- 后端：`http://127.0.0.1:8003`
- 前端 API Base：`http://127.0.0.1:8003/api`

手工/浏览器验证使用本地 Edge，验证场景：

- active work 运行中输入“继续”，不得被 boundary block。
- 输入普通新问题时，不应误控制旧 active work。
- 工具 request/permission/start/result 只显示一个生命周期 item。
- closeout/commit 后只显示正文，不显示收口前工具/status 噪音。
- replay/reconnect 不复活旧工具、不把旧 terminal 贴到新消息。

## 12. 迁移与清理规则

- 不做长期双协议兼容。
- 实施期间如果必须临时保留旧字段，必须满足：
  - 仅限同一 phase 内部过渡。
  - 有明确删除点。
  - 不进入模型可见主 contract。
  - 不作为前端 reducer 主匹配键。
- 旧测试若只保护 `boundary_action`、`current_work_boundary_decision`、`allowed_action_types_for_next_packet` 等旧内部形状，应删除或重写。
- 不允许以 UI filter 代替 producer/contract 修复。
- 不允许用关键词、正则、自然语言 marker 覆盖模型行为协议。
- 不允许在 execution loop 中猜测用户意图来恢复。

## 13. 禁止的捷径

- 不把 `continue`、`继续`、`go on` 加进边界规则当修复。
- 不让 `current_work_boundary_decision_from_payload()` 兼容 `ModelActionRequest`，因为这会保留第二套协议。
- 不把 runtime_status 只在前端隐藏，后端仍发 visible timeline。
- 不用 `task_run_id` 单字段匹配当前 assistant。
- 不把 `permission_decision_id` 当作工具生命周期唯一主键替代 `tool_call_id`。
- 不用 mock 掉核心 runtime/projection 让测试通过。
- 不保留已经无权威的旧 prompt、旧 parser、旧 receipt 字段。

## 14. 预期结果

完成后应达到：

- “继续”作为当前 active work 控制命令时，走 `ModelActionRequest -> CurrentWorkPermit -> ActionPermit -> ExecutionLoop`，不会被旧 boundary action 协议阻止。
- 普通新请求不会因为存在 active work 而被强行纳入旧任务。
- 工具生命周期按 `tool_call_id` 合并，permission/start/result 顺序可证明。
- 公开投影以强锚点进入对应 assistant，旧时序不能串入新时序。
- commit/closeout 后主视图只显示收口正文，运行过程保留为 trace 或已 retire。
- runtime 行为协议可维护，后续新增动作只需要扩展 `ModelActionRequest` 和 permit/admission，不再新增平行行为协议。

