# Agent运行期Steer与Runtime私有边界治理计划书

日期：2026-06-11  
状态：待审阅  
范围：Active turn steer、TaskRun 补充要求排队、workspace 文件工具边界、runtime 私有上下文、任务/工具公开投影  
不在本方案范围：重做前端任务窗口、隐藏工具活动、改模型供应商、重写 TaskGraph、迁移历史 session 数据  

## 1. 背景

当前用户反馈集中在两个现象：

1. 任务执行期间发送补充消息时，缺少以前那种“排队补充到当前任务”的效果，容易表现为旧任务被替换或任务状态被新的回合抢占。
2. 主会话和工具活动区域会反复冒出 `runtime_state/dynamic_context/replacements/*.json`、`runtime_context/tool_results` 这类内部文件路径，看起来像普通工具搜索结果或工具返回内容。

这两个现象不能用“前端屏蔽工具窗口”解决。成熟 coding agent 的标准是：工具执行、终端、任务轨迹应当对用户可见；内部上下文、压缩产物、rehydration 存储不应作为普通 workspace 文件暴露。

本计划的核心裁决是：

```text
保留工具/任务公开轨迹；
切断普通 workspace 工具对 runtime 私有存储的默认访问；
把 active steer 固定为当前任务补充信号，而不是悄悄退化成新任务替换；
presentation 层只做净化，不承担主要安全边界。
```

## 2. 成熟架构参照

外部成熟 agent 的共同做法：

- Codex / Claude Code 都会展示一部分工具执行窗口、终端轨迹、任务进度。
- 边界控制发生在 sandbox、approval、permission、workspace access、tool visibility 层。
- 内部上下文和运行时恢复产物不作为普通文件搜索结果暴露。

参考资料：

- OpenAI Codex CLI：[https://developers.openai.com/codex/cli](https://developers.openai.com/codex/cli)
- OpenAI Codex sandboxing：[https://developers.openai.com/codex/concepts/sandboxing](https://developers.openai.com/codex/concepts/sandboxing)
- OpenAI Codex agent approvals and security：[https://developers.openai.com/codex/agent-approvals-security](https://developers.openai.com/codex/agent-approvals-security)
- Claude Code overview：[https://docs.anthropic.com/en/docs/claude-code/overview](https://docs.anthropic.com/en/docs/claude-code/overview)
- Claude Code settings / permissions：[https://docs.anthropic.com/en/docs/claude-code/settings](https://docs.anthropic.com/en/docs/claude-code/settings)
- Claude Code permission modes：[https://code.claude.com/docs/en/permission-modes](https://code.claude.com/docs/en/permission-modes)
- Claude Code permissions：[https://code.claude.com/docs/en/permissions](https://code.claude.com/docs/en/permissions)

本轮核对结论：

- Codex 公开资料强调 coding agent 会读写代码、运行命令、在 sandbox / approval / workspace 边界下工作；这支持“工具活动可见，但工具访问受边界约束”。
- Claude Code 公开资料强调 permissions、settings、hooks 等控制面；这支持“通过权限和路径边界治理工具能力”，而不是 UI 层隐藏工具生命周期。
- 两者都不是把内部 runtime 状态当成普通项目文件让 agent 搜索、读取、再靠前端擦掉。

可借鉴标准：

```text
User Input
-> RequestFacts
-> Active Work Boundary
-> Model Turn Decision
-> Tool Authorization
-> Workspace File Boundary
-> Runtime Execution
-> Public Projection
-> Session Commit Gate
```

各层只做自己的决定：

- `Active Work Boundary`：判断用户输入是否属于当前任务控制或补充。
- `Model Turn Decision`：在没有 active steer/control fast path 时做语义裁决。
- `Tool Authorization`：决定工具是否可调用。
- `Workspace File Boundary`：决定普通文件工具能不能访问某路径。
- `Runtime Execution`：执行、记录事实，不重新发明用户意图。
- `Public Projection`：把已批准的执行事实投影为公开进度。
- `Session Commit Gate`：决定什么能成为正式 assistant 正文。

## 3. 当前问题定义

### 3.1 Active steer 边界不稳定

理想行为：

```text
用户在 active task 期间发送普通补充
-> expected_active_turn_id 匹配
-> active_turn_input_policy=steer
-> append_instruction_to_active_work
-> 当前 TaskRun 在下一个安全边界消费补充要求
```

不理想行为：

```text
用户在 active task 期间发送普通补充
-> 退回普通 single-agent turn
-> 模型裁决为 request_task_run
-> 新任务 replacement 停掉旧任务
-> 旧任务 stop closeout 抢占主会话体验
```

截至本计划撰写时，当前源码中 `_active_turn_steer_fast_path()` 已经恢复非控制类补充进入 `_active_turn_append_instruction_events()` 的路径。后续需要用测试锁住该行为，避免再次被删除。

相关代码：

- `backend/harness/entrypoint/runtime_facade.py`
- `backend/harness/loop/active_work.py`
- `backend/api/orchestration_harness.py`

### 3.2 Runtime 私有产物被 workspace 工具暴露

泄露路径示例：

```text
backend/mythical-agent/sessions/session-.../environments/coding/vibe-workspace/runtime_state/dynamic_context/replacements/replacement_....json
runtime_context/tool_results/...
```

问题本质：

- `search_text`
- `search_files`
- `glob_paths`
- `read_file`
- `list_dir`
- `stat_path` / `path_exists` / `path_info` 类路径探测
- `write_file` / `edit_file`
- native tool runtime fallback search

这些普通 workspace 工具把 runtime 私有存储当作项目文件扫描、读取、探测或修改。

这不是前端展示问题，也不只是 `DEFAULT_SEARCH_EXCLUDED_PATHS` 太短，而是 workspace file boundary 缺少 runtime-private 硬边界。默认搜索排除只影响部分默认搜索路径；显式 `paths=[...]`、显式 root、`glob_paths()`、`list_dir()`、`stat_path()`、`path_exists()`、`read_file()`、`write_file()`、`edit_file()` 和 native fallback 仍可能绕过。

相关代码：

- `backend/capability_system/tools/workspace_file_service.py`
- `backend/capability_system/tools/tool_units/search_files_tool.py`
- `backend/capability_system/tools/tool_units/file_system_tools.py`
- `backend/capability_system/tools/tool_units/write_file_tool.py`
- `backend/runtime/tool_runtime/native_tools.py`
- `backend/capability_system/tools/tool_units/persisted_tool_result_tool.py`

### 3.3 工具窗口被错误屏蔽

之前的错误方向是：在 public projection / frontend timeline 层根据内部路径或 persisted result failure 直接隐藏工具调用、工具返回或任务活动。

这个方向会误伤成熟 agent 必须展示的内容：

- 工具开始
- 工具完成
- 任务进度
- TaskRun projection
- session runtime timeline
- runtime attachments

正确方向是：

```text
工具活动项保留；
内部路径和 raw protocol 文本不进入普通工具结果；
presentation 层只在兜底场景净化文本，不删除整条活动。
```

相关代码：

- `backend/api/chat.py`
- `backend/harness/runtime/progress_presenter.py`
- `backend/harness/runtime/projection/task_projection.py`
- `backend/harness/runtime/session_timeline.py`
- `frontend/src/lib/projection/timeline.ts`
- `frontend/src/components/chat/agentRunProjection.ts`

## 4. 信号分类与标记

本计划将运行期信息统一标记为以下信号类型。后续实现和测试必须以这些标记为验收标准。

| 标记 | 信号类型 | 例子 | 可见范围 | 处理策略 |
| --- | --- | --- | --- | --- |
| `PUBLIC_ACTIVITY` | 用户可见执行轨迹 | 工具开始、工具结束、任务阶段、终端状态 | UI、session timeline、runtime attachment | 保留显示 |
| `PUBLIC_RESULT_SUMMARY` | 可公开结果摘要 | “已读取文件”“测试通过”“产生 1 个产物” | UI、模型后续上下文 | 保留，限制长度，禁止 raw protocol |
| `USER_STEER_SIGNAL` | 用户补充要求 | “继续修复篮球游戏”“补上移动端适配” | 当前 active TaskRun | append 到当前任务队列 |
| `CONTROL_SIGNAL` | 控制类指令 | pause、stop、continue、resume | runtime control plane | 走控制 API 和 active work control，不走普通模型裁决 |
| `MODEL_DECISION_SIGNAL` | 模型动作裁决 | respond、tool_call、request_task_run、ask_user、block | runtime 内部，必要摘要可见 | 记录为 runtime decision，不直接当正文展示 |
| `TOOL_CALL_SIGNAL` | 工具调用请求 | `search_text`、`read_file`、`apply_patch` | 工具窗口可见 | 显示工具名和安全目标摘要 |
| `TOOL_OBSERVATION_SIGNAL` | 工具返回 | 搜索结果、文件读取、命令输出 | 工具窗口可见 | 显示安全结果摘要和普通结果 |
| `RUNTIME_PRIVATE_ARTIFACT` | runtime 私有产物 | replacement json、tool result store、dynamic context fragment | runtime 专用 | 普通 search/read/list/stat/write/edit 默认禁止 |
| `REHYDRATION_REF` | 专用恢复引用 | `replacement_id`、trusted path、task_run_id | 模型可见为引用，不可猜路径 | 只允许专用 persisted result 工具读取 |
| `INTERNAL_PROTOCOL_SIGNAL` | 内部协议或机器状态 | raw JSON、DSML、plan_id/items、machine status | 不给用户 | projection 层净化或丢弃文本 |
| `SESSION_CANONICAL_MESSAGE` | 正式 assistant 正文 | 最终回答、明确阻塞说明 | session messages | 必须有 turn_id，经过 commit gate |
| `BACKGROUND_TASK_PROJECTION` | 后台任务投影 | task projection、progress entries、public timeline | UI 工具/任务窗口 | 保留，不写成普通正文 |
| `RUN_MONITOR_RECORD` | 运行监控历史记录 | `management.lanes.recent`、`management.lanes.hidden`、completed task record | 运行管理台 records/cleanup | 保留记录，但不进入右侧常驻任务 lane，不自动选中 |
| `DEBUG_TRACE_SIGNAL` | 调试轨迹 | raw event id、step_summary_recorded、runtime packet | monitor/debug only | 不进入主聊天正文 |

### 4.1 信号边界规则

#### 4.1.1 可公开但不是正文

以下信号可以在工具窗口、任务窗口、runtime attachment 中出现，但不能直接作为主 assistant 正文：

- `PUBLIC_ACTIVITY`
- `TOOL_CALL_SIGNAL`
- `TOOL_OBSERVATION_SIGNAL`
- `BACKGROUND_TASK_PROJECTION`

#### 4.1.2 可成为正文

只有以下信号可成为主会话正式 assistant message：

- `SESSION_CANONICAL_MESSAGE`
- 经过 output boundary 批准的 `PUBLIC_RESULT_SUMMARY`
- 明确阻塞或失败说明

强制要求：

```text
必须有 turn_id；
必须通过 Session Commit Gate；
不能来自 replacement stop closeout；
不能是 internal protocol 清洗残片。
```

#### 4.1.3 只允许 runtime 内部访问

以下信号不能通过普通 workspace 工具枚举、搜索或读取：

- `RUNTIME_PRIVATE_ARTIFACT`
- runtime-owned dynamic context replacement 文件
- runtime-owned tool result store 文件
- rehydration 存储文件

#### 4.1.4 专用引用访问

`REHYDRATION_REF` 不是普通路径能力。它只能通过专用工具读取：

```text
replacement_id + task_run_id + trusted path
-> persisted_tool_result / rehydration 专用工具
-> trusted runtime roots
```

禁止：

```text
模型猜测 runtime_state 路径；
模型用 search_text 搜 replacement 文件；
模型用 read_file 直接读 runtime 私有 JSON；
```

## 5. Timeline 对照与边界显示规则

信号分类只解决“这是什么”。timeline 对照要解决“它什么时候出现、显示在哪、边界时怎么收口”。

本章的 timeline 是广义公开显示时序，不等同于当前代码里的 `runtimeAttachments[].public_timeline` 数组。当前实现中，`assistant_body` 和 `tool_window` 有独立过滤/渲染路径；如果实施时不先统一通道权威，就会出现正文、工具窗口、runtime attachment 三套重复解释。

本系统的公开显示时序不应是一条混杂文本流，而应拆成 7 个显示面：

| 显示面 | 对应字段 | 允许内容 | 禁止内容 |
| --- | --- | --- | --- |
| Assistant 正文 | session assistant message / assistant stream；语义上可对应 `slot=body` + `surface=assistant_body` | 正式回答、开局判断、阻塞说明、可公开阶段总结 | 工具 raw output、runtime path、控制回执、debug event |
| 工具窗口 | `ToolActivityLifecycle`；语义上可对应 `slot=tool` + `surface=tool_window` | 工具生命周期运行、完成、失败、安全目标摘要 | runtime 私有路径、raw protocol、整项隐藏、重复 start/return 行 |
| 任务/状态 timeline | `slot=status/task/timeline` + `surface=timeline/status_bar` | 任务接管、等待、排队、阶段性公开进展 | 空泛机器状态刷屏 |
| 控制面 | `slot=control` + `surface=control` | pause/stop/continue/steer ack、safe boundary wait | 正文回答、工具结果 |
| 常驻运行监视台 | `RunMonitorPanel` + `selectRunMonitorTaskLane()` | 当前运行、等待、需关注、项目级 active/attention 信号 | `recent`、`hidden`、completed/stopped 历史记录、默认选中旧记录 |
| 运行管理台 | `RunManagementWorkbench` + `management.lanes.recent/hidden` | 最近完成、已清出、可清理的运行记录 | 把历史记录伪装成当前运行、抢占常驻任务窗口 |
| Debug/Monitor | raw runtime event / technical trace | event id、payload、step、diagnostics | 进入主聊天正文 |

当前代码对照：

- `backend/harness/runtime/projection/authority.py` 会过滤 `slot=body`、`surface=assistant_body` 和 `surface=tool_window`。
- `frontend/src/lib/projection/reducer.ts` 的 `isValidProjectionItem()` 也会过滤 body 和 tool window item。
- `frontend/src/lib/store/events.ts` 另有 `tool_item_started` / `tool_item_completed` 路径生成 `work_action`。

因此实施时必须先做一个明确裁决：

```text
Assistant 正文权威 = session message / assistant text stream / commit gate
工具生命周期权威 = ToolActivityLifecycle 公共事件合同
runtime attachment public_timeline = 状态、任务、控制、可合并的 companion timeline
```

除非同步扩展 `PublicProjectionFrame` 合同，否则不能把 `tool_window` 或 `assistant_body` item 塞进 runtime projection envelope 后期待前端显示。

### 5.1 Timeline 阶段表

| 阶段 | 触发信号 | 典型 runtime event / API event | 目标 timeline item | 显示位置 | 边界规则 |
| --- | --- | --- | --- | --- | --- |
| T0 用户消息入站 | 用户输入 | chat request / user message persisted | 用户消息本身 | 主会话用户气泡 | 不生成 runtime public item |
| T1 active steer 接收 | `USER_STEER_SIGNAL` | `active_task_steer_recorded` / `active_task_steer_accepted` | `active_task_steer` 或 `status_update` | 控制面或任务 timeline | 不生成新 assistant 正文，不创建 replacement TaskRun |
| T2 active control 接收 | `CONTROL_SIGNAL` | pause/stop/continue API event、`active_work_control_observed` | `control_state` / `safe_boundary_wait` | 控制面 | 控制回执可见，但不占主正文 |
| T3 TaskRun 启动/接管 | `BACKGROUND_TASK_PROJECTION` | `task_run_lifecycle_started` / `task_run_executor_started` / `task_run_executor_scheduled` | task projection + `status_update` | 任务窗口、状态 timeline | 可见任务已接管；避免空泛“正在处理”刷屏 |
| T4 模型作出动作裁决 | `MODEL_DECISION_SIGNAL` | `model_action_request_received` / `model_action_admission_checked` | 若需要正文，走 assistant stream / session message；若只是进展，走 `status_update`；工具动作进入 `ToolActivityLifecycle` | 正文、状态 timeline 或工具窗口 | 模型 JSON/action 本体不显示；只显示公开字段；不要把 body/tool item 塞进当前 projection envelope |
| T5 工具生命周期开始 | `TOOL_CALL_SIGNAL` | `model_action_admission` / `tool_item_started` | 创建或更新同一 `work_action(state=running)` | 工具窗口 | 以 `tool_call_id/action_ref` 作为生命周期键；不显示成独立“开始记录” |
| T6 工具生命周期完成 | `TOOL_OBSERVATION_SIGNAL` | `turn_tool_observation_recorded` / `task_tool_observation_recorded` / `tool_item_completed` | 用返回结果 terminalize 同一 `work_action(state=done/error)`，必要时补 `observation_report` | 同一个工具窗口项；模型总结后可进入正文 | 工具项保留并更新；raw output 不直接变正文；不新增重复返回项 |
| T7 runtime 私有产物生成 | `RUNTIME_PRIVATE_ARTIFACT` | dynamic context replacement / tool result store write | 无 public timeline item | runtime 内部 | 不进入工具窗口，不进入搜索结果，不进入正文 |
| T8 rehydration 引用读取 | `REHYDRATION_REF` | persisted tool result 专用工具 | 最多显示“上下文已恢复”类状态；默认可 debug only | 任务 timeline 或 debug | 不显示内部路径；不通过普通 read/search |
| T9 用户补充被任务消费 | `USER_STEER_SIGNAL` | `active_task_steer_included` / `active_task_steer_consumed` | `status_update` 或 task activity “纳入补充要求” | 任务 timeline | 下一次模型决策必须能看到补充要求 |
| T10 正常完成 | `SESSION_CANONICAL_MESSAGE` | assistant final commit + terminal event | assistant 正文 + terminalized timeline items | 正文、任务窗口 | 必须有 `turn_id`，commit gate 允许后才能入 session message |
| T11 阻塞/失败 | `PUBLIC_RESULT_SUMMARY` 或 control error | `agent_turn_failed` / `loop_error` / blocked action | `blocked` / `error_notice` / 正式阻塞说明 | 控制面；需要用户行动时可正文 | 不暴露 stack、raw JSON、内部路径 |
| T12 停止/替换 | `CONTROL_SIGNAL` / replacement stop | `task_run_lifecycle_finished`、`terminal_reason=user_aborted` | 旧 task projection 变 stopped；新 task 另起 lifecycle | 任务窗口 | replacement stop closeout 不写主 assistant 正文 |
| T13 hydrate/reconnect | persisted runtime attachment | session timeline / monitor snapshot | 合并已有 `public_timeline` | 原锚点 assistant message | 不生成新语义 item，不重复显示 |
| T14 无 anchor / mismatch | `DEBUG_TRACE_SIGNAL` 或 steer mismatch | missing `anchor_turn_id`、expected turn mismatch | debug only；或明确 blocked receipt | debug；必要时控制面 | 不能挂到最近消息猜测显示 |

### 5.2 信号到 PublicTimelineItem 的路由表

| 信号标记 | 目标 `kind` | 目标 `slot` | 目标 `surface` | 是否可进 assistant 正文 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `PUBLIC_ACTIVITY` | `status_update` / `work_action` | `timeline` / `tool` / `status` | `timeline` / `tool_window` / `status_bar` | 否 | 记录 agent 正在做什么，不当最终回答 |
| `PUBLIC_RESULT_SUMMARY` | `observation_report` / `stage_summary` / `final_summary` | `body` 或 `timeline` | `assistant_body` 或 `timeline` | 有条件 | 只有经过 output boundary 和 public text 净化后可进正文 |
| `USER_STEER_SIGNAL` | `active_task_steer` / `status_update` | `control` 或 `task` | `control` 或 `timeline` | 否 | 表示补充要求已接入当前任务 |
| `CONTROL_SIGNAL` | `control_state` / `safe_boundary_wait` | `control` | `control` | 否 | 控制回执，不是 assistant 回答 |
| `MODEL_DECISION_SIGNAL` | `opening_judgment` / `status_update` / none | `body`、`timeline` 或 none | `assistant_body`、`timeline` 或 none | 有条件 | 正文走 assistant/session 通道；runtime attachment 只承载 companion timeline |
| `TOOL_CALL_SIGNAL` | `work_action` | `tool` | `tool_window` | 否 | 创建或推进工具生命周期，不单独生成“开始”展示行 |
| `TOOL_OBSERVATION_SIGNAL` | `work_action` / `observation_report` | `tool` 或 `body` | `tool_window` 或 `assistant_body` | 有条件 | 先 terminalize 同一工具生命周期；模型解释后的含义才可正文 |
| `RUNTIME_PRIVATE_ARTIFACT` | none | none | none | 否 | 不进入 public timeline |
| `REHYDRATION_REF` | `status_update` 或 none | `status` 或 none | `timeline` 或 none | 否 | 默认不显示；必要时只显示抽象状态 |
| `INTERNAL_PROTOCOL_SIGNAL` | none | none | none | 否 | projection 层净化或丢弃 |
| `SESSION_CANONICAL_MESSAGE` | `final_summary` 或 assistant message content | `body` | `assistant_body` | 是 | 必须经过 commit gate |
| `BACKGROUND_TASK_PROJECTION` | task projection / `status_update` | `task` / `timeline` | task panel / timeline | 否 | 用于任务窗口和 runtime attachment |
| `RUN_MONITOR_RECORD` | monitor record row | management records | run management workbench | 否 | 只在 records/cleanup 或显式打开详情时出现，不参与右侧任务 lane 自动选择 |
| `DEBUG_TRACE_SIGNAL` | none | none | debug only | 否 | 仅 monitor/debug |

### 5.3 边界场景显示规则

#### 5.3.1 Active steer 命中当前任务

```text
用户补充
-> active_task_steer_accepted
-> control surface / session activity 显示“已收到补充要求”
-> TaskRun activity 显示“纳入补充要求”
-> 不生成 assistant 正文
-> 不创建新 TaskRun
```

#### 5.3.2 Active steer 失配

```text
expected_active_turn_id 缺失或不匹配
-> control surface / session activity 显示 blocked receipt
-> 不 append 到任何任务
-> 不默认改成新任务
```

#### 5.3.3 Stop requested 但 executor 还未到安全边界

```text
stop_task_run()
-> task control state=stop_requested
-> control surface / session activity 显示“停止请求已记录/等待安全边界”
-> task projection 仍显示 stopping/running until terminal
-> 不写最终 assistant 正文
```

#### 5.3.4 Replacement stop 旧任务

```text
new task request replaces old task
-> old task terminal_reason=user_aborted + replacement_stop
-> old task projection 显示 stopped
-> old closeout 不进入 SESSION_CANONICAL_MESSAGE
-> new task lifecycle 挂到新 turn
```

#### 5.3.5 普通 workspace 文件操作命中 runtime-private

```text
search_files/search_text/read_file/glob_paths/list_dir/stat_path/path_exists/write_file/edit_file 请求 runtime private path
-> Workspace File Boundary 拒绝或默认排除
-> 工具窗口可显示安全错误摘要
-> 不显示真实内部绝对路径或 replacement JSON 路径
-> 不把结果写进 assistant 正文
```

#### 5.3.6 专用 rehydration 读取

```text
persisted_tool_result(replacement_id/path/task_run_id)
-> trusted root 校验
-> runtime 内部恢复上下文
-> public timeline 默认不显示；必要时只显示抽象状态
-> 不暴露 replacement JSON 路径
```

#### 5.3.7 工具 raw output 很长或像协议

```text
TOOL_OBSERVATION_SIGNAL
-> 找到同一 tool_call_id/action_ref 对应的工具生命周期项
-> 工具窗口更新该活动项为 done/error
-> raw output 被折叠、摘要化或标记 raw_output_suppressed
-> 只有模型后续给出的 observation_report 可进入正文
```

#### 5.3.8 工具生命周期合并

```text
tool_item_started / model_action_admission
-> backend creates ToolActivityLifecycle(id=tool_lifecycle_id)
-> render work_action(state=running)

tool_item_completed / task_tool_observation_recorded
-> backend emits same tool_lifecycle_id
-> update work_action(state=done/error, observation=...)
-> do not append a second visible row

missing started event
-> observation may create a completed lifecycle item
-> mark source as recovered_from_observation

missing completed event
-> terminal event finalizes running lifecycle as stopped/error according to terminal state
```

固定约束：

- 工具窗口显示的是生命周期对象，不是 event list。
- start 和 observation 可以来自不同 stream，但必须通过后端提供的 `tool_lifecycle_id` 合并；`tool_call_id`、`action_request_ref`、`observation_ref` 是生成 lifecycle id 的候选输入。
- 同一工具生命周期最多显示一行；状态从 `running` 变为 `done/error/stopped`。
- `publicTimelineSemanticKey()` 的工具合并规则只能作为兜底，首选后端提供稳定 lifecycle id。
- `tool_item_started/completed` 与 runtime monitor projection 不能各自生成不同 id；否则刷新或 SSE 重连后会重复显示。

`ToolActivityLifecycle` 最小合同：

```text
tool_lifecycle_id: 稳定、同一工具调用全程不变
anchor_turn_id: 归属 turn，缺失时只允许 debug/monitor
task_run_id: 归属 TaskRun，可为空但不能伪造
tool_call_id / action_request_ref / observation_ref: 追踪引用
tool_name: 工具名
state: running | done | error | stopped
started_at / completed_at: 可选时间戳
public_target: 已净化目标摘要，不能是 runtime-private path
public_observation: 已净化结果摘要，不能是 raw protocol
raw_observation_ref: 内部引用，只给 debug/rehydration，不给普通 UI
```

切换规则：

- 后端必须先能对 started/completed 产生同一个 `tool_lifecycle_id`，前端再改合并策略。
- 前端显示层只认 lifecycle identity，不根据标题文本猜同一工具。
- 如果缺少 started，只允许 observation 恢复成一条 `state=done/error` 的 lifecycle item。
- 如果缺少 completed，TaskRun terminal event 负责把运行中的 lifecycle item 收口为 `stopped/error`。

#### 5.3.9 hydrate/reconnect

```text
session timeline / runtime attachment hydrate
-> 按 item_id / trace_refs / semantic key 合并
-> 不产生新语义事件
-> 不重复显示旧工具项
```

#### 5.3.10 全局运行监控 recent 记录

```text
GET /api/orchestration/runtime-monitor
-> management.lanes.current / projects / attention 进入右侧常驻任务 lane
-> management.lanes.recent / hidden 只进入运行管理台 records/cleanup
-> reducer 默认 auto-select 只允许 live task lane 候选
-> 用户显式打开历史记录时，才允许用 signal_id 选中 recent/hidden 详情
```

固定约束：

- 后端可以返回 recent/hidden，因为管理台需要历史、清理和诊断能力。
- 右侧常驻 `RunMonitorPanel` 只能展示当前运行、等待、需关注和项目级 active/attention 信号。
- completed/stopped/recent/hidden 不能因为 SSE 重连、刷新、空态 fallback 或默认选择逻辑跳回常驻任务窗口。
- 显式选择历史记录是用户动作，不能被 reducer 的默认 selection 当作“最新任务”推断。

### 5.4 当前源码对照点

当前已有的 timeline 类型和路由位置：

- `frontend/src/lib/api.ts` 定义 `PublicChatTimelineItem.kind/slot/surface`。
- `backend/harness/runtime/projection/items.py` 定义 `opening_judgment_item`、`work_action_item`、`status_item`、`control_item`。
- `backend/harness/runtime/projection/timeline_builder.py` 将 runtime event 映射到 public event type。
- `backend/harness/runtime/projection/projector.py` 将 public event type 映射为 timeline item。
- `frontend/src/lib/projection/timeline.ts` 负责 sanitize、merge、terminalize。

需要特别审查的点：

1. `model_action_admission` 当前如果被视为 legacy live tool event，可能不会产生 public timeline item；工具开始是否改由 `tool_item_started` 路径承担，需要在实现时明确。
2. `runtime_status` 当前可能不产生 item，但 task projection 会随 envelope 附加；任务接管类状态应避免正文刷屏。
3. `active_task_steer_accepted` 应该是 control surface / session activity / task projection 状态，不应进入 assistant body，也不要求进入工具活动列表。
4. `work_action` 的 `subject_label` 必须经过 runtime-private path boundary 后再生成。
5. `frontend/src/components/layout/RunMonitorPanel.tsx` 必须只消费 `selectRunMonitorTaskLane()`；`frontend/src/lib/run-monitor/reducer.ts` 默认 selection 必须只从 live task lane 自动选择，不能从 `allRunMonitorSignals()` 里的 recent/hidden 兜底。
6. 前端 `normalizePublicTimelineItems()` 当前会过滤 body/status_bar/todo_plan，只合并 companion timeline；这决定了正文和活动窗口必须分路输入。
7. 工具开始和工具返回必须合并为同一个 `ToolActivityLifecycle`；不能把 event list 直接渲染成两条 UI 记录。
8. `PublicProjectionFrame` 当前会过滤 `tool_window` 和 `assistant_body`，所以如果目标是用 projection envelope 承载这两类 item，必须先改 projection authority 和前端 reducer；否则应保持它们分别走 assistant/session 和 ToolActivityLifecycle 通道。
9. `PublicTimelineActivity` 当前会过滤 control item；control 类信号主要体现在 session activity、stage status 或 task projection，不应要求它出现在工具/活动列表里。

## 6. 目标架构边界

### 6.1 Active steer 目标流

```text
User message during active task
-> request.expected_active_turn_id
-> active_turn_input_policy=steer
-> _active_turn_steer_fast_path()
   -> CONTROL_SIGNAL: pause / stop / continue
   -> USER_STEER_SIGNAL: append instruction
-> TaskRun executor consumes queued instruction at safe boundary
-> public projection shows "纳入补充要求"
```

规则：

- 普通补充不应退回普通 single-agent turn。
- 控制指令不应进入普通模型裁决。
- active turn 失效时必须给出明确 blocked receipt，不悄悄新建任务。
- 只有用户明确提出独立新任务时，才允许 replacement。

### 6.2 Runtime 私有文件目标流

```text
runtime writes replacement/tool_results
-> marked RUNTIME_PRIVATE_ARTIFACT
-> WorkspaceFileService default excludes
-> search_files/search_text/glob_paths/list_dir/read_file/stat_path/path_exists/write_file/edit_file cannot expose by default
-> rehydration tool can read via trusted REHYDRATION_REF
```

规则：

- runtime 私有目录不属于普通 workspace 搜索面。
- 如果用户明确要求排查 runtime 内部存储，应该通过开发者工具或专用 debug 路径，而不是 agent 普通文件工具。
- 公开 projection 不应该收到这些路径；收到时只作为兜底净化。
- runtime-private 判断必须是无条件硬边界；不能只挂在 `include_default_search_excludes=True` 的默认搜索分支上。
- 显式 path/root/glob 命中 runtime-private 时，应拒绝或返回安全错误，而不是临时放开排除。

### 6.3 工具/任务公开投影目标流

```text
Runtime event
-> progress presenter / task projection / session timeline
-> public_timeline / runtime attachment
-> frontend task/tool activity window
```

规则：

- 工具活动项不因内部路径规则被整条隐藏。
- 工具返回如果是失败，也要保留失败活动；只隐藏空白或纯内部协议文本。
- 主聊天摘要不应被 `工具已返回` 这类泛化文本占据。

## 7. 实施计划

### 7.0 执行顺序与切换规则

实施必须按以下顺序推进，避免在旧链路上继续堆补丁：

1. 先确认错误屏蔽方案已经撤干净，保证工具窗口和任务窗口不被整体隐藏。
2. 先补 active steer、runtime-private、tool lifecycle 的行为测试，让目标行为变成测试约束。
3. 再落 runtime-private hard boundary，覆盖默认搜索、显式路径、glob、read_file、list_dir、stat_path、path_exists、write_file、edit_file、native fallback。
4. 保留并校验专用 rehydration 通道，确认上下文恢复不依赖普通 workspace read/search。
5. 落 `ToolActivityLifecycle` 稳定 id 合同，让工具开始/返回合并为同一个可见生命周期项。
6. 最后清理 projection/presentation 文本净化，确保只净化文本，不删除工具活动。
7. 收口 Session commit gate，确保 replacement stop closeout 不成为无 turn_id 主正文。

切换规则：

- 不保留两套长期并行工具显示链路；如果 lifecycle 合同切换失败，回退整个阶段修改，而不是加兼容分支。
- 不把 runtime-private hard boundary 降级成 UI scrub；presentation scrub 只作为最后防线。
- 不扩展 `PublicProjectionFrame` 承载 body/tool，除非同一阶段同步修改后端 authority、前端 reducer、store events 和测试。
- 每阶段结束必须能说明旧决策权是否已删除、转移或仍被保留；不能留下“旧链路也许还会生效”的隐性分支。

### 阶段 0：确认回滚边界

目标：确认之前错误的“屏蔽工具窗口”方案已经从工作树中退出，不再作为后续设计基础。

检查文件：

- `backend/harness/runtime/progress_presenter.py`
- `backend/harness/runtime/projection/task_projection.py`
- `backend/harness/runtime/session_timeline.py`
- `backend/harness/runtime/projection/filters.py`
- `backend/api/chat.py`
- `frontend/src/lib/projection/timeline.ts`
- `frontend/src/components/chat/agentRunProjection.ts`

完成标准：

- 不存在 `should_hide_public_tool_call` 这类隐藏整个工具调用的主路径。
- 工具生命周期仍能形成 public activity，并且 start/return 合并为同一显示项。
- 任务 projection 仍能生成 `activities`。

### 阶段 1：固化 active steer append 行为

目标：任务期间普通补充消息稳定进入当前任务补充队列。

修改或补测文件：

- `backend/harness/entrypoint/runtime_facade.py`
- `backend/harness/loop/active_work.py`
- `backend/tests/harness_runtime_facade_regression.py`
- 可新增 `backend/tests/active_turn_steer_boundary_regression.py`

实现要求：

1. `active_turn_input_policy=steer` 且 `expected_active_turn_id` 匹配时，先走 `_active_turn_steer_fast_path()`。
2. pause/stop/continue 进入 `CONTROL_SIGNAL` 分支。
3. 其他用户文本进入 `_active_turn_append_instruction_events()`。
4. active work 不存在或 turn mismatch 时，返回明确 blocked receipt。
5. 不允许这类 steer 文本退回普通 single-agent turn 后被模型裁决成新 task replacement。

测试场景：

- active task running，用户发“把移动端也修一下”，应记录 `USER_STEER_SIGNAL`，不创建新 TaskRun。
- active task paused，用户发“继续”，应进入 `CONTROL_SIGNAL` continue。
- expected active turn mismatch，返回 blocked，不 append 到错误任务。

### 阶段 2：建立 runtime-private workspace 文件边界

目标：普通 workspace 文件工具默认看不到 runtime 私有存储。

修改文件：

- `backend/capability_system/tools/workspace_file_service.py`
- `backend/capability_system/tools/tool_units/search_files_tool.py`
- `backend/capability_system/tools/tool_units/file_system_tools.py`
- `backend/capability_system/tools/tool_units/write_file_tool.py`
- `backend/runtime/tool_runtime/native_tools.py`

建议新增统一判断：

```text
is_runtime_private_path(path) -> bool
```

默认私有模式包括：

```text
mythical-agent/sessions/**
backend/mythical-agent/sessions/**
storage/sessions/**
storage/session_environments/**
storage/runtime_context/**
storage/runtime_state/**
runtime_context/tool_results/**
runtime_state/dynamic_context/replacements/**
runtime_state/tool_results/**
dynamic_context/replacements/replacement_*.json
backend/storage/session_environments/**
backend/storage/runtime_context/**
backend/storage/runtime_state/**
**/runtime_state/dynamic_context/replacements/**
**/runtime_context/tool_results/**
**/dynamic_context/replacements/replacement_*.json
```

实现要求：

1. `rg --files` 路径加入默认排除。
2. `search_text` 的 `rg` 路径加入默认排除。
3. fallback `rglob` 路径无条件调用 runtime-private 判断；默认搜索排除仍可继续使用 `include_default_search_excludes=True`。
4. `glob_paths` 默认排除 runtime-private。
5. 精确 `paths=[...]` 搜索也要拒绝 runtime-private，除非走专用 rehydration 工具。
6. `read_file` / native read 路径不能直接读取 runtime-private。
7. `list_dir`、`stat_path`、`path_exists` / native path_info 类路径探测不能枚举 runtime-private。
8. `write_file`、`edit_file`、`write_text`、`edit_text` 这类普通文件写入入口不能修改 runtime-private。
9. `_targets_default_excluded_path()` 不能导致 runtime-private 被“显式命中后放行”；runtime-private 与默认搜索排除要分成两套判断。

完成标准：

- 普通搜索不返回 replacement JSON。
- 普通 read 不读取 runtime private 文件。
- 普通 glob 不枚举 runtime private 文件。
- 普通 list/stat/exists 不揭示 runtime private 目录结构。
- 普通 write_file/edit_file 无法写入 runtime private。

### 阶段 3：保留专用 rehydration 通道

目标：runtime 自己仍能读取压缩/替换后的上下文，不破坏长上下文恢复能力。

检查文件：

- `backend/capability_system/tools/tool_units/persisted_tool_result_tool.py`
- `backend/runtime/tool_runtime/native_tools.py`
- `backend/harness/runtime/dynamic_context/manager.py`
- `backend/harness/runtime/dynamic_context/replacement_store.py`

实现要求：

1. 专用工具只接受 rehydration plan 提供的 `replacement_id`、`path`、`task_run_id`。
2. 专用工具校验 path 位于 trusted runtime roots。
3. 专用工具的返回只给模型必要内容和引用，不暴露完整内部目录结构到 public timeline。
4. 普通 workspace read/search 和专用 rehydration read 不能共用同一个“只要路径存在就读”的入口。

完成标准：

- 上下文恢复可用。
- 普通文件工具不可见 runtime 私有路径。
- 专用工具不能被模型猜路径滥用。

### 阶段 4：公开投影只净化文本，不隐藏活动

目标：presentation 层回归展示职责，不承担主要访问控制。

修改或检查文件：

- `backend/api/chat.py`
- `backend/harness/runtime/progress_presenter.py`
- `backend/harness/runtime/projection/task_projection.py`
- `backend/harness/runtime/session_timeline.py`
- `backend/harness/runtime/public_progress.py`
- `frontend/src/lib/projection/timeline.ts`
- `frontend/src/components/chat/agentRunProjection.ts`

规则：

- `TOOL_CALL_SIGNAL` 要显示为工具活动。
- `TOOL_OBSERVATION_SIGNAL` 要显示为工具完成或失败。
- `tool_item_started` 和 `tool_item_completed` 不能分别渲染成两行，必须共享 `tool_lifecycle_id`。
- `INTERNAL_PROTOCOL_SIGNAL` 可以被净化为空。
- `RUNTIME_PRIVATE_ARTIFACT` 路径如果兜底进入 projection，应替换为通用说明或清空文本，但不能删除整个工具项。
- 泛化文本如“工具已返回”不能作为主正文摘要，但可以作为工具窗口状态。
- `assistant_body` 不通过 runtime attachment companion timeline 兜底生成；正式正文仍由 assistant stream / session commit gate 负责。

完成标准：

- 工具窗口仍显示。
- 工具开始和工具返回显示为同一个生命周期项的状态变化。
- 任务记录仍显示。
- 主聊天不被空泛工具回执刷屏。
- 内部路径不再出现在普通用户可见文本中。
- 每类信号都能按第 5 章映射到正确 `kind/slot/surface`，或明确留在 debug。
- 如果选择扩展 `PublicProjectionFrame` 承载 tool/body，必须同步修改后端 authority、前端 reducer 和对应测试；否则不得把这两类 item 塞进 projection envelope。

### 阶段 5：Session commit gate 校验旧任务收口

目标：被 replacement stop 的旧任务 closeout 不抢占新 turn 主正文。

相关文件：

- `backend/orchestration/commit_gate.py`
- `backend/harness/loop/task_executor.py`
- `backend/tests/output_boundary_final_text_regression.py`

已有目标规则：

```text
replacement stop closeout
-> 不作为 SESSION_CANONICAL_MESSAGE
-> 不写无 turn_id assistant 正文
-> 只作为 task projection terminal state
```

完成标准：

- `turn_id` 缺失时不能 commit assistant session message。
- `source=harness.loop.task_executor.replacement_stop` 且 `terminal_reason=user_aborted` 时不能 commit 主正文。
- 旧任务停止状态进入 task projection，不盖住新任务生命周期。

### 阶段 6：测试与真实验证

后端 focused tests：

```powershell
pytest backend/tests/workspace_file_tools_regression.py backend/tests/read_file_authority_chain_regression.py -q
pytest backend/tests/workspace_runtime_private_boundary_regression.py -q
pytest backend/tests/public_projection_contract_test.py backend/tests/session_task_projection_test.py backend/tests/session_runtime_timeline_contract_test.py backend/tests/public_progress_contract_test.py -q
pytest backend/tests/output_boundary_final_text_regression.py -q
```

前端 focused tests：

```powershell
cd frontend
.\node_modules\.bin\vitest.cmd run src/lib/projection/timeline.test.ts src/components/chat/PublicTimelineActivity.test.ts
```

真实运行验证：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/project_stack.ps1 -Action stop
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/project_stack.ps1 -Action start -FrontendMode dev
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/project_stack.ps1 -Action check
```

固定端口：

- 前端：`http://127.0.0.1:3000`
- 后端：`http://127.0.0.1:8003`

人工验证：

1. 启动一个长任务。
2. 任务执行中发送普通补充要求。
3. 确认补充要求进入当前任务，不创建 replacement 新任务。
4. 确认工具/任务窗口仍显示。
5. 用搜索请求触发 `search_text` / `search_files`，确认不返回 replacement/tool_results 私有路径。
6. 刷新会话，确认 runtime attachment 和 task projection 仍可见。
7. 触发一次工具调用，确认 started 和 completed 合并为同一工具生命周期项。
8. SSE 重连或刷新后，确认同一个工具生命周期不重复显示。

## 8. 文件级执行清单

| 文件 | 当前职责 | 计划动作 |
| --- | --- | --- |
| `backend/harness/entrypoint/runtime_facade.py` | active steer fast path、single-agent turn entrypoint | 补测试锁定 append 行为，禁止 steer 退回 replacement |
| `backend/harness/loop/active_work.py` | active work context 和控制动作 | 明确 `USER_STEER_SIGNAL` / `CONTROL_SIGNAL` 标记 |
| `backend/capability_system/tools/workspace_file_service.py` | workspace 文件解析、默认搜索根和排除 | 增加 runtime-private path boundary |
| `backend/capability_system/tools/tool_units/search_files_tool.py` | LangChain search_files/search_text 工具 | rg 与 fallback 统一排除 runtime-private |
| `backend/capability_system/tools/tool_units/file_system_tools.py` | LangChain list_dir/stat_path/path_exists/glob_paths 工具 | 普通路径探测统一受 runtime-private boundary 约束 |
| `backend/capability_system/tools/tool_units/write_file_tool.py` | LangChain write_file/edit_file 工具 | 普通写入/编辑禁止命中 runtime-private |
| `backend/runtime/tool_runtime/native_tools.py` | native search/read/glob/list/stat/exists/write/edit 工具 | native 路径统一使用 runtime-private boundary；专用 rehydration 例外 |
| `backend/capability_system/tools/tool_units/persisted_tool_result_tool.py` | 专用 persisted result 读取 | 保留 trusted rehydration ref，不走普通 workspace read |
| `backend/harness/runtime/progress_presenter.py` | progress presentation | 保留工具活动，净化文本，不隐藏整项 |
| `backend/harness/runtime/projection/task_projection.py` | TaskRun projection | 保留 activity，避免 raw internal text |
| `backend/harness/runtime/projection/authority.py` | public projection envelope 授权 | 明确是否继续过滤 body/tool window；若扩展合同必须同步改前端 |
| `backend/harness/runtime/session_timeline.py` | session runtime attachment/timeline | 保留 task projection 和工具 timeline |
| `backend/api/chat.py` | public stream projection | 只做 public 数据净化，不作为私有路径主防线 |
| `frontend/src/lib/store/events.ts` | stream event reducer、tool_item 生命周期现有入口 | 若保留该入口，必须接收后端稳定 `tool_lifecycle_id` 并与 hydrate 合并 |
| `frontend/src/lib/projection/reducer.ts` | PublicProjectionEnvelope 消费 | 避免和 `events.ts` 对 tool/body 形成双权威；若扩展合同需改过滤规则 |
| `frontend/src/lib/projection/timeline.ts` | public timeline 前端净化和合并 | 不隐藏工具项，只处理 raw output 防御 |
| `frontend/src/components/chat/PublicTimelineActivity.tsx` | 活动窗口渲染 | 明确过滤 control item，工具 lifecycle 只显示一行 |
| `frontend/src/components/chat/agentRunProjection.ts` | agent run projection 展示 | 保留工具窗口和任务轨迹 |

## 9. 验收矩阵

| 场景 | 预期结果 | 失败表现 |
| --- | --- | --- |
| active task 中发普通补充 | 记录 `USER_STEER_SIGNAL`，append 到当前任务 | 新建 TaskRun replacement 旧任务 |
| active task 中发 stop | 记录 `CONTROL_SIGNAL`，停止当前任务 | 进入普通模型回复 |
| 默认 search_text 搜 replacement | 无结果或只返回普通项目文件 | 返回 `runtime_state/dynamic_context/replacements` |
| 默认 search_files 搜 tool_results | 无 runtime 私有路径 | 返回 `runtime_context/tool_results` |
| 显式 paths 搜 replacement JSON | 返回安全拒绝 | 绕过默认排除并返回 replacement 内容 |
| glob/list/stat/exists 指向 runtime_state | 返回安全拒绝或无公开结果 | 枚举 runtime 私有目录结构 |
| 普通 write_file/edit_file 指向 runtime 私有目录 | 拒绝 | 写入 runtime 私有文件 |
| 专用 rehydration 读 trusted ref | 成功读取必要内容 | 要求用普通 read_file 读内部路径 |
| 工具失败 | 工具窗口显示失败活动和安全错误摘要 | 整条工具记录消失 |
| 工具成功但结果泛化 | 工具窗口显示完成，主正文不被“工具已返回”覆盖 | 主聊天反复刷空泛工具回执 |
| replacement stop 旧任务 | 旧任务 projection 显示 stopped，不写主正文 | 无 turn_id assistant message 盖住新任务 |
| active steer accepted display | `active_task_steer` 进入 control surface / session activity，TaskRun activity 显示补充已纳入 | 作为 assistant 正文显示，或要求出现在工具活动列表 |
| tool lifecycle started | `work_action(state=running)` 进入 tool window，带稳定 lifecycle id | 工具开始不可见或缺少 id |
| tool lifecycle completed | 同一 lifecycle item terminalize 为 done/error | 新增重复工具项或整项消失 |
| projection envelope body/tool filtering | body 走 assistant/session，tool 走 lifecycle；或显式扩展合同后一致显示 | 文档要求显示但 envelope/reducer 实际过滤 |
| runtime private artifact timeline | 不生成 public timeline item | replacement JSON 路径显示在正文或工具窗口 |
| hydrate/reconnect timeline | 按 key 合并旧 public timeline | 刷新后重复显示同一工具项 |

## 10. 禁止事项

1. 禁止用前端隐藏整条工具记录解决 runtime 私有路径泄露。
2. 禁止屏蔽任务窗口或 task projection。
3. 禁止把 runtime 私有文件先暴露给普通工具，再靠 UI 正则擦掉。
4. 禁止保留坏旧链路作为“兼容兜底”。
5. 禁止通过降低测试断言、删除失败测试、mock 核心逻辑制造通过。
6. 禁止把开发说明式文字写进 agent prompt。
7. 禁止随机切换本地端口。
8. 禁止针对某张截图路径写特判。

## 11. 风险与控制

### 风险 1：runtime-private 排除过宽

可能误伤用户真正想搜索的项目文件。

控制：

- 只排除明确 runtime storage roots 和动态上下文存储形态。
- 对用户项目根下普通 `docs/backend/frontend` 文件不做额外限制。
- 如需 debug runtime storage，应设计专用 debug 工具或开发者入口。

### 风险 2：active steer 过度接管

用户可能在任务执行期间提出无关新请求。

控制：

- `expected_active_turn_id + active_turn_input_policy=steer` 表示前端已经把该输入作为当前任务 steer 发送。
- 普通输入入口仍可由模型裁决新任务。
- 前端应只在当前任务输入框/active stream 场景发送 steer policy。

### 风险 3：presentation 净化不足

内部路径可能通过工具 error 文本进入 UI。

控制：

- 主防线在工具边界。
- projection 层保留兜底 scrub，但只清文本，不删活动。
- 测试覆盖 raw path 出现在 observation text 的兜底场景。

### 风险 4：专用 rehydration 被误封

过度收紧普通 read/search 可能影响上下文恢复。

控制：

- 普通 workspace 工具和 rehydration 专用工具分权。
- 专用工具用 trusted roots 和 replacement refs，不依赖普通 workspace file service 的默认搜索面。

## 12. 本轮审查发现与修正

本计划对照当前 timeline/projection 源码后，确认以下遗漏和冲突已经纳入计划：

| 发现 | 源码证据 | 风险 | 计划修正 |
| --- | --- | --- | --- |
| `assistant_body` 和 `tool_window` 当前会被 `PublicProjectionFrame` 授权层过滤 | `backend/harness/runtime/projection/authority.py` | 文档若要求 projection envelope 显示 body/tool，会落空 | 明确 body 走 assistant/session，tool 走 `ToolActivityLifecycle`；除非同步扩展合同 |
| 前端 `applyPublicProjectionEnvelope()` 也过滤 body/tool item | `frontend/src/lib/projection/reducer.ts` | 后端即使发了 body/tool item，前端也不显示 | 文件清单加入 reducer；扩展合同时必须同步改 |
| 工具 lifecycle 当前实际由 `tool_item_started/completed` 分支生成 | `frontend/src/lib/store/events.ts` | runtime monitor projection 和 chat stream 可能双路生成工具项 | 要求后端提供稳定 `tool_lifecycle_id`，两路必须合并 |
| control item 不进入活动窗口列表 | `frontend/src/components/chat/PublicTimelineActivity.tsx` | 文档若要求 control 在活动列表显示，会与现状冲突 | 改为 control surface/session activity/stage status 显示 |
| runtime private 排除范围原来只写 backend 路径 | 当前 workspace 同时存在顶层 `mythical-agent`、`storage` 和 `backend/storage` | 默认 root 或显式 root 搜索仍可能扫到私有目录 | 扩展默认私有模式，覆盖顶层和 backend 内部 runtime storage |
| 工具生命周期缺少显式后端 id 合同 | 当前主要靠 `tool_call_id` 或 semantic key | 刷新、hydrate、不同 stream 来源下容易重复 | 新增 `tool_lifecycle_id` 作为计划要求，semantic key 只做兜底 |
| `glob_paths()` 对命中默认排除路径会放宽 exclude | `backend/capability_system/tools/workspace_file_service.py` | 用户显式 glob runtime_state 时可能绕开默认排除 | runtime-private 独立为硬边界，不受 `_targets_default_excluded_path()` 放宽逻辑影响 |
| `read_file` / `list_dir` / `stat_path` / `path_exists` / `write_file` / `edit_file` 不是搜索，但同样会泄露路径、内容或修改 runtime 状态 | `backend/runtime/tool_runtime/native_tools.py`、`backend/capability_system/tools/tool_units/file_system_tools.py`、`backend/capability_system/tools/tool_units/write_file_tool.py`、`WorkspaceFileService` | 只修 search 会留下旁路 | 所有普通 workspace 文件能力统一调用 runtime-private boundary |

仍需实施时二选一的设计点：

1. 保持当前通道分工：assistant 正文走 assistant/session，工具窗口走 `tool_item_*` / `ToolActivityLifecycle`，runtime attachment 只承载 companion timeline。
   这是当前计划的推荐方向，改动小，符合现有代码分层。
2. 扩展 `PublicProjectionFrame`：允许 body/tool_window item 进入 envelope。
   如果选择这个方向，必须同步修改后端 authority、前端 reducer、store events 旧分支和测试，避免双权威。

推荐采用第 1 种，不扩展 projection envelope 承载 body/tool，先把工具生命周期和 runtime-private 边界修稳。

## 13. 审阅点

实施前建议确认：

1. 是否接受 `mythical-agent/sessions/**`、`backend/mythical-agent/sessions/**`、`storage/sessions/**`、`storage/session_environments/**`、`storage/runtime_context/**`、`storage/runtime_state/**`、`backend/storage/session_environments/**`、`backend/storage/runtime_context/**` 和 `backend/storage/runtime_state/**` 默认不属于普通 agent workspace 文件面，包括 search/read_file/glob_paths/list_dir/stat_path/path_exists/write_file/edit_file。
2. 是否需要额外提供一个开发者 debug 工具查看 runtime 私有存储。
3. active steer 的用户补充是否一律以当前任务为目标，除非前端明确走普通消息入口。
4. replacement stop closeout 是否只允许进入 task projection，不允许成为主 assistant 正文。
5. 是否采用推荐方向：不扩展 `PublicProjectionFrame` 承载 body/tool，而是把 body、tool lifecycle、companion timeline 三条通道的权威固定下来。

## 14. 最终目标

完成后，系统行为应稳定为：

```text
任务期间用户发补充
-> 当前任务收到补充要求
-> 工具/任务窗口继续显示执行轨迹
-> 普通搜索看不到 runtime 私有文件
-> 专用 rehydration 仍可恢复上下文
-> 主聊天不被旧任务 stop closeout 或内部路径刷屏
```

这才是成熟 agent 的边界：用户看得到 agent 在做什么，但看不到 runtime 用来维持自身运行的私有机械结构。
