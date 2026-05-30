# Active Task Steering 强实测实验书

日期：2026-05-30

状态：实施后的强实测设计。本文用于验证 `codex_style_active_task_steering_runtime_rebuild_plan_20260530.md` 已经真实落地，并且能稳定解决“用户中途补充要求后 agent 继续旧任务、长期 running、无法完成修复”的结构性问题。

## 0. 实验结论标准

本实验不以“代码能跑”或“某个单测通过”为充分条件。只有同时满足以下条件，才允许判断功能稳定实现：

```text
用户中途输入必然成为 UserSubmission。
运行中任务的新要求必然成为 ActiveTaskSteer。
ActiveTaskSteer 必然进入下一次 RuntimeInvocationPacket。
agent 未处理 steer 时不能完成 TaskRun。
改变目标或验收标准的输入必然进入 TaskContractRevision 裁决。
resume / execute / restart 后 executor id 和 invocation id 不重复。
running 任务不会被重复启动 executor。
monitor / SSE 能观察 pending steer、contract revision、executor epoch、stale 和 terminal 状态。
固定端口 3000 / 8003 的真实前后端链路可用。
故障注入时系统 fail closed，而不是静默吞掉用户要求或假完成。
```

如果任何路径仍然允许“用户新要求只进入 `resume_context` 或普通 observation，agent 可以忽略后完成”，本次重构视为未通过强实测。

## 1. 实验边界

覆盖范围：

```text
backend/query/runtime.py
backend/harness/loop/user_submission.py
backend/harness/loop/task_steering.py
backend/harness/loop/executor_sequence.py
backend/harness/loop/task_contract_revision.py
backend/harness/loop/task_executor.py
backend/harness/loop/task_checkout.py
backend/harness/runtime/compiler.py
backend/harness/runtime/monitor_projection.py
backend/harness/runtime/session_timeline.py
backend/api/orchestration_harness.py
backend/api/chat.py
frontend API proxy / runtime monitor 页面
```

真实入口：

```text
POST /api/chat
GET  /api/orchestration/harness/live-monitor?limit=...
GET  /api/orchestration/harness/monitor-events?limit=...
GET  /api/orchestration/harness/task-runs/{task_run_id}
GET  /api/orchestration/harness/task-runs/{task_run_id}/live-monitor
POST /api/orchestration/harness/task-runs/{task_run_id}/execute
POST /api/orchestration/harness/task-runs/{task_run_id}/pause
POST /api/orchestration/harness/task-runs/{task_run_id}/resume
POST /api/orchestration/harness/task-runs/{task_run_id}/stop
```

固定端口：

```text
前端 Next.js: http://127.0.0.1:3000
后端 FastAPI / Uvicorn: http://127.0.0.1:8003
前端 API Base: http://127.0.0.1:8003/api
```

## 2. 反作弊规则

实验期间禁止：

```text
跳过失败用例。
降低断言强度。
mock 掉 RuntimeCompiler、TaskExecutor、EventLog、MonitorProjection 的核心行为。
硬编码 event payload 或固定 model response 来制造通过。
只检查最终自然语言回答，不检查 trace/event/monitor。
绕过固定端口，临时换 3001、8004 等随机端口。
用静态检查替代前后端真实启动。
把 pending steer 手动标 consumed 来绕过 completion gate。
删除旧失败数据来掩盖 stale / duplicate executor 问题。
```

允许：

```text
确定性协议测试可以使用 runtime stubs。
负向实验可以注入故意错误的 model action。
真实全链路实验必须使用真实 API、真实 event log、真实 monitor/SSE。
模型不可控时，可以用专门的 deterministic model adapter 做系统评测，但 adapter 必须走真实 executor 和 packet 编译路径。
```

## 3. 观测证据

每轮实验必须保留以下证据：

```text
task_run_id
session_id
trace JSON: /api/orchestration/harness/task-runs/{task_run_id}?include_payloads=true&include_model_messages=true
task monitor JSON: /api/orchestration/harness/task-runs/{task_run_id}/live-monitor
global monitor JSON: /api/orchestration/harness/live-monitor?limit=20
SSE 首屏 snapshot 和至少一个 runtime_monitor_event
前端固定端口健康检查结果
后端固定端口健康检查结果
pytest 命令和结果
如涉及文件修复，保留真实 git diff 或 artifact receipt
```

关键事件必须可在 trace 中按顺序出现：

```text
user_submission_recorded
active_task_steer_recorded
active_task_steer_included
runtime_invocation_packet_compiled
model_action_request_received
active_task_steer_consumed 或 task_completion_repair_required
task_contract_revision_recorded 或 task_contract_revision_decided
task_run_executor_claimed
task_run_lifecycle_finished
```

允许某些场景没有 `task_contract_revision_recorded`，但凡用户输入改变目标、范围、约束或验收标准，就必须出现合同修订事件或明确的 revision decision。

## 4. 实验层级

### 4.1 L1 确定性协议回归

目的：证明核心协议不依赖真实模型运气。

命令：

```powershell
python -m pytest `
  backend\tests\task_steering_protocol_regression.py `
  backend\tests\query_runtime_runtime_loop_regression.py `
  backend\tests\runtime_monitor_projection_test.py `
  backend\tests\runtime_event_index_test.py `
  backend\tests\task_run_state_machine_regression.py `
  backend\tests\runtime_loop_budget_regression.py `
  backend\tests\orchestration_execution_scheduler_regression.py `
  -q
```

必须断言：

```text
create_active_task_steer 先写 user_submission_recorded，再写 active_task_steer_recorded。
pending steer 可以 included，再 consumed。
consumed steer 不会被 late include 重新打开。
running task 收到用户补充只记录 steer，不重复 schedule executor。
paused task 收到用户补充先 steer，再 resume。
checkout fork 不再把当前用户要求只写入 resume_context.user_instruction。
runtime_invocation_packet_compiled 的 payload 包含 pending_user_steers。
agent 没有 consumed_steer_refs 时完成请求被 task_completion_repair_required 拦截。
contract_revision_decisions 能关闭 active contract revision。
monitor projection 暴露 pending_user_steer_count、active_contract_revision_count、executor_epoch、next_invocation_index。
```

失败定义：

```text
任何新用户要求没有 steer_ref。
任何 pending steer 没有进入 packet。
任何未消费 steer 的 completed 被接受。
任何 resume 后生成旧式重复 model-action:{task_run_id}:1。
```

### 4.2 L2 API 级真实 runtime 实验

目的：不经过 UI，直接用真实 FastAPI + runtime host 验证 API 控制面。

步骤：

```text
1. 通过 POST /api/chat 创建一个需要长任务执行的请求。
2. 从 stream 或 live-monitor 找到 task_run_id。
3. 调用 GET /api/orchestration/harness/task-runs/{task_run_id}/live-monitor，确认 status 为 running 或 waiting/runnable。
4. 在任务未终止前，再次 POST /api/chat，session_id 相同，message 为用户补充要求。
5. 查询 trace，确认出现 user_submission_recorded 和 active_task_steer_recorded。
6. 若任务仍 running，确认没有新的 task_run_executor_scheduled 造成重复 executor。
7. 触发或等待下一轮 execute。
8. 查询 trace，确认 active_task_steer_included 早于对应 runtime_invocation_packet_compiled 或与其同轮可追踪。
9. 检查 packet payload 里有 execution_state.system_projection.pending_user_steers。
10. 若 model 直接请求完成但未 consumed steer，确认出现 task_completion_repair_required，而不是 completed。
```

补充输入样例：

```text
不是继续旧方向。请优先处理我刚才指出的加载失败，并且完成前必须给出真实验证结果。
```

通过条件：

```text
同一个 task_run_id 下有 steer 生命周期事件。
pending_user_steer_count 从 1 变为 0 的过程可解释。
如果 pending_user_steer_count 长时间不变，monitor 必须能显示卡点。
没有 duplicate executor claim。
没有用户补充被写成 resume_context 的新写入。
```

### 4.3 L3 固定端口全栈实测

目的：证明前端、后端、SSE、proxy 和 monitor 在真实运行时一致。

启动前检查：

```powershell
netstat -ano | findstr ":3000"
netstat -ano | findstr ":8003"
```

规则：

```text
3000 只能有一个本项目前端进程。
8003 只能有一个本项目后端进程。
如果固定端口被非本项目进程占用，停止实验并告知用户。
前端必须从干净 .next 启动。
```

健康检查：

```powershell
Invoke-WebRequest http://127.0.0.1:8003/docs -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:3000/ -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:8003/api/orchestration/harness/live-monitor?limit=5 -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:3000/api/orchestration/harness/live-monitor?limit=5 -UseBasicParsing
```

SSE 检查：

```text
连接 /api/orchestration/harness/monitor-events?limit=1。
首个事件必须是 runtime_monitor_snapshot。
后续 task event 必须产出 runtime_monitor_event。
断线重连后不能造成重复 executor。
```

浏览器检查：

```text
使用本地 Edge 浏览器打开 http://127.0.0.1:3000。
发起长任务。
在任务 running 时输入修订要求。
观察 UI 是否展示任务仍在同一 run 内接收补充要求。
观察 monitor 是否显示 pending steer / executor epoch / latest event。
最终完成前必须能在 trace 中看到 steer consumed 或 repair required。
```

失败定义：

```text
前端请求落到 8002 / 8004 / 3001 等随机端口。
SSE 只有 heartbeat，没有 runtime_monitor_snapshot。
UI 显示完成，但 trace 仍有 pending steer。
UI 显示 running，但 monitor 没有 last activity / stale / blocked 诊断。
```

### 4.4 L4 故障注入实验

目的：证明系统遇到坏模型输出、竞态和 stale 状态时 fail closed。

实验 A：模型忽略 steer 直接完成

```text
构造 pending_user_steers。
让 deterministic model 返回 respond/final，但 diagnostics.consumed_steer_refs 为空。
```

通过条件：

```text
TaskRun 不得 completed。
trace 必须出现 task_completion_repair_required。
monitor 必须显示 pending_user_steer_count > 0 或 latest_step 为 repair required。
```

实验 B：模型引用不存在的 consumed_steer_refs

```text
pending steer 为 steer:A。
model 返回 consumed_steer_refs = ["steer:missing"]。
```

通过条件：

```text
steer:A 仍 pending 或 included。
不存在 steer:missing 的 consumed event。
completion gate 不得把任务放行。
```

实验 C：合同修订未裁决

```text
用户补充要求改变验收标准。
生成 active TaskContractRevision。
model 请求完成但 diagnostics.contract_revision_decisions 为空。
```

通过条件：

```text
TaskRun 不得 completed。
trace 必须出现 task_completion_repair_required，payload 带 active_contract_revision_ids。
```

实验 D：重复执行器启动

```text
任务已有 executor_status=running / claimed。
同时调用 execute API 或 resume API。
```

通过条件：

```text
第二次请求返回 409 task_run_executor_already_running。
event log 不出现第二个有效 executor claim。
```

实验 E：resume 后 id 单调性

```text
执行 task_run 到 invocation N。
pause / resume / execute 多轮。
```

通过条件：

```text
packet_id 形如 rtpacket:{task_run_id}:task_execution:{executor_epoch}:{invocation_index}。
model action id 形如 model-action:{task_run_id}:epoch:{executor_epoch}:invocation:{invocation_index}:{suffix}。
同一 task_run 内无重复 request_id / packet_id。
executor_epoch 单调增加，invocation_index 不回退。
```

实验 F：SSE 断线重连

```text
任务 running 时打开 monitor-events。
断开 SSE。
继续提交用户 steer。
重连 monitor-events。
```

通过条件：

```text
重连首包 snapshot 能反映当前 pending_user_steer_count。
断线不会丢 event log。
断线不会触发 duplicate executor。
```

### 4.5 L5 长稳与压力实验

目的：证明稳定性不是单次成功。

建议执行矩阵：

```text
同一 session 连续 20 次：创建任务 -> running steer -> packet include -> consumed/repair -> terminal。
同一 task_run 连续 5 次：pause -> steer -> resume。
同一 task_run 连续 5 次：用户改变验收标准 -> contract revision -> decision。
并发 5 个 session：每个 session 1 个 active task，分别追加 steer。
SSE monitor 持续连接 30 分钟，期间持续有任务事件。
```

统计指标：

```text
steer_recorded_count == user_followup_count。
steer_included_count == steer_recorded_count，除非任务 terminal 前明确 rejected/superseded。
steer_consumed_count + repair_required_count + rejected_count + superseded_count == steer_included_count。
duplicate_request_id_count == 0。
duplicate_packet_id_count == 0。
duplicate_executor_claim_count == 0。
unexpected_completed_with_pending_steer_count == 0。
monitor_snapshot_parse_error_count == 0。
frontend_proxy_mismatch_count == 0。
```

通过门槛：

```text
核心阻断指标必须全为 0。
非核心网络波动允许重试，但重试后 trace 必须能解释，不允许静默丢输入。
```

## 5. 推荐新增实验脚本

建议新增两个脚本，但脚本本身必须遵守反作弊规则。

### 5.1 系统评测脚本

路径建议：

```text
backend/tests/system_eval/active_task_steering_live_experiment.py
```

职责：

```text
通过真实 API 创建任务。
在 active task running 时追加用户输入。
轮询 trace 和 monitor。
断言 event 顺序、packet payload、completion gate、monitor 字段。
输出 JSON 实验报告。
```

输出报告结构：

```json
{
  "experiment": "active_task_steering_live",
  "session_id": "...",
  "task_run_id": "...",
  "passed": true,
  "event_order": [],
  "packet_refs": [],
  "steer_refs": [],
  "contract_revision_refs": [],
  "executor_epochs": [],
  "request_ids": [],
  "monitor_snapshots": [],
  "failures": []
}
```

### 5.2 固定端口验收脚本

路径建议：

```text
scripts/run_active_task_steering_strong_experiment.ps1
```

职责：

```text
检查 3000 / 8003 端口归属。
按项目规则启动后端和前端。
执行健康检查。
执行 live-monitor 和 monitor-events 检查。
调用系统评测脚本。
保存 trace / monitor / SSE 证据到 storage/experiments/{timestamp}/。
```

注意：

```text
脚本不得自动关闭非本项目占用端口的进程。
脚本不得在失败时清空证据目录。
脚本不得用随机端口替代固定端口。
```

## 6. 最小上线门禁

每次修改 active task steering、runtime compiler、task executor、resume、checkout、monitor、SSE 或 `/api/chat` 后，至少执行：

```powershell
python -m pytest `
  backend\tests\task_steering_protocol_regression.py `
  backend\tests\query_runtime_runtime_loop_regression.py `
  backend\tests\runtime_monitor_projection_test.py `
  backend\tests\runtime_event_index_test.py `
  backend\tests\task_run_state_machine_regression.py `
  -q
```

然后执行固定端口真实启动检查：

```text
后端 /docs 返回 200。
前端 / 返回 200。
后端 live-monitor 返回 JSON。
前端 proxy live-monitor 返回 JSON。
monitor-events 返回 runtime_monitor_snapshot。
```

如果改动涉及 completion gate 或 executor sequence，还必须执行 L4 故障注入 A、D、E。

如果改动涉及前端 runtime monitor，还必须使用本地 Edge 浏览器完成 L3 浏览器检查。

## 7. 判定表

| 场景 | 必须看到 | 不允许看到 |
| --- | --- | --- |
| running 中用户补充要求 | `user_submission_recorded` -> `active_task_steer_recorded` | 只写 `resume_context.user_instruction` |
| 下一轮 executor packet | `pending_user_steers` 出现在 packet | packet 无 steer 但模型继续执行 |
| 模型忽略 steer 完成 | `task_completion_repair_required` | `task_run_lifecycle_finished:completed` |
| 用户改变验收标准 | `task_contract_revision_recorded` 或 revision decision | 当作普通 observation 消失 |
| pause 后补充并 resume | steer 先记录，resume 后 included | resume 吞掉 message |
| terminal checkout fork | child contract 有 current user revision | 最新要求只在 resume_context |
| 多次 resume | epoch/invocation 单调 | request_id / packet_id 重复 |
| SSE 重连 | snapshot 反映当前 monitor | 重连触发 duplicate executor |
| 前端代理 | 请求指向 8003 API | 请求落到随机端口 |

## 8. 当前基线

本轮重构后的基础回归已通过：

```text
86 passed, 1 warning
```

已验证的基础项：

```text
active steer 协议回归。
pending_user_steers 注入 packet。
completion repair gate 阻断未消费 steer。
contract revision decision 事件。
executor epoch / invocation id 单调格式。
monitor projection 暴露 steer/revision/executor 字段。
固定 3000 / 8003 前后端健康检查。
live-monitor 与 monitor-events 基础可用。
```

但该基线仍不足以替代 L2-L5 强实测。后续只要继续改 runtime 主链，就必须按本文门禁补齐真实 API、全栈、故障注入和压力重复证据。

## 9. 最终验收语句

通过强实测后，验收结论必须能具体写成：

```text
在固定 3000 / 8003 的真实前后端环境中，用户在 TaskRun running / paused / checkoutable 状态下追加要求，系统均能把输入记录为 UserSubmission 并路由为 ActiveTaskSteer 或 TaskContractRevision；下一次 RuntimeInvocationPacket 可观测地包含这些输入；agent 未消费或未裁决时 completion gate 会阻断完成；resume 和重复执行不会产生重复 executor 或重复 action id；monitor/SSE 能解释 pending、stale、blocked、terminal 状态；连续和并发实验未发现丢输入、假完成、重复执行器或随机端口问题。
```

如果不能写出这句话，并且不能附上对应 trace / monitor / SSE / test 证据，则不能宣称该功能稳定实现。
