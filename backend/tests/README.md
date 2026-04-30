# Backend Test System

后端测试体系现在以 `test_system.case_registry` 为登记权威，按四层组织：

- `chain`：验证真实主链的关键接线，例如 RuntimeLoop 事件、测试登记表、QueryRuntime adapter、任务-操作 preview。
- `functional`：验证单个系统合同，例如操作系统、记忆系统、灵魂系统、工具注册、权限服务。
- `system`：验证跨系统装配、应用 smoke、测试产物持久化和门禁运行。
- `scenario`：验证长场景与真实实测报告，不作为快速开发门禁。

## Entry Points

- 链路级门禁：
  - `python backend/tests/run_regression_gate.py --profile chain`
- 功能级门禁：
  - `python backend/tests/run_regression_gate.py --profile functional`
- 系统级门禁：
  - `python backend/tests/run_regression_gate.py --profile system`
- 场景实测：
  - `python backend/tests/run_regression_gate.py --profile scenario`

统一 harness 入口也支持同样的 profile：

- `python -m harness.run --profile chain`
- `python -m harness.run --profile functional`
- `python -m harness.run --profile system`
- `python -m harness.run --profile scenario`

## Case Governance

- 活跃用例必须登记在 `backend/test_system/case_registry.py` 的 `ACTIVE_CASES`。
- 旧链路参考用例放在 `backend/tests/legacy/`，登记为 `legacy`，不进入 curated gate。
- 未确认是否保留的历史用例由登记表自动暴露为 `candidate`，不进入 curated gate。
- 新增测试文件时，先决定它属于 `chain / functional / system / scenario` 哪一层，再登记 owner、profile、tags 和断言边界。

测试 agent 的治理报告入口：

- API：`GET /api/test-system/agent/report`
- Python：`from test_system.agent import TestAgentAdvisor`

## RuntimeLoop Assertions

当前测试系统优先判断 RuntimeLoop 事实：

- `loop.event=<event_type>`
- `loop.tool=<tool_name>`
- `loop.completed`
- `loop.terminal_reason=<reason>`
- `tool.pairing_ok`
- `commit.assistant_session=true`
- `memory.session_refresh=true`
- `memory.durable_commit=true`

旧 `plan.* / followup.* / main.*` 断言不再作为新测试核心事实源。需要恢复时，应先接入任务系统、状态记忆或上下文管理的专用 adapter。
