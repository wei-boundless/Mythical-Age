# 测试系统瘦身计划 2026-05-22

## 审查结论

- `health_system/maintenance/harness` 的职责是进程入口、profile 调度、运行产物持久化，结构基本清楚，不应把普通 pytest 夹具塞进去。
- `health_system/maintenance/test_system` 的职责是用例登记、测试语义、断言、harness 记录和 runtime loop 证据归一化，适合作为测试治理层。
- `backend/tests/system_eval` 是长场景/系统场景 runner，但公共函数仍散落在 `runner.py` 和 `long_runner.py`。
- `backend/tests` 缺少共享测试支撑层，导致 runtime stub、settings stub、trace reader、写作配置 seed helper 被多处复制。
- `case_registry` 和 `TestAgentAdvisor` 只发现 `*_regression.py` 等文件，漏掉 `*_test.py` 和 `test_*.py`，测试地图会低估真实用例。

## 目标结构

- `backend/tests/support/runtime_stubs.py`：通用 API/runtime/query runtime stub。
- `backend/tests/support/trace_stubs.py`：trace reader、state index、task run stub。
- `backend/tests/support/writing_fixtures.py`：写作配置脚本加载和 storage seed。
- `backend/tests/system_eval/execution_core.py`：系统/长场景 runner 共享工具函数。
- `backend/health_system/maintenance/test_system/case_registry.py` 与 `agent.py`：统一测试文件发现规则。

## 实施阶段

1. 新增 `tests/support`，迁移重复 runtime/trace/writing fixture。
2. 将 `runner.py` 与 `long_runner.py` 的重复公共函数回收到 `execution_core.py`。
3. 修正 case discovery，让测试治理层覆盖 pytest 的常见命名。
4. 删除测试与 maintenance 下的 `__pycache__` 运行残留。
5. 运行聚焦回归：support 迁移涉及的测试、harness/test_system 测试、system_eval warning/registry 测试。

## 不做的事

- 不删除真实场景资产，如 `backend/tests/fixtures/professional_task_suite`。
- 不把 harness 进程执行层和 pytest fixture 层混在一起。
- 不为了兼容保留被迁移后的私有重复 stub。
