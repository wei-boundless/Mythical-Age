# Backend Tests

后端测试入口以 pytest 为准，默认命令：

```powershell
python -m pytest
```

`pytest.ini` 只从 `backend/tests` 收集这些活跃用例：

- `*_regression.py`
- `*_test.py`
- `test_*.py`

## Organization

- `*_regression.py`：主链路、跨模块合同、权限边界、运行时投影、回归保护。
- `*_test.py` / `test_*.py`：仍需进入默认门禁的集中单元或模型合同测试。
- `support/`：测试支撑代码，只放 fixture、stub、trace helper，不放断言用例。
- `fixtures/`：测试输入资产和小型样例项目。
- `system_eval/`：长场景、压力实验和人工可读报告；默认 pytest 只收集其中的 `*_regression.py`，实验脚本必须显式运行。

## Rules

- 不保留指向旧 harness、旧 case registry 或不存在 runner 的测试入口。
- 不把旧计划书、`__pycache__`、手工实验残留当作测试资产提交。
- 进入 pytest 命名规则的文件必须提供真实 `test_*` 用例，不能只保留 `main()` 脚本。
- 新测试必须进入默认 pytest 发现规则；确实不能进入快速门禁的长场景，放入 `system_eval/` 并在对应 README 说明运行方式。
- 测试应保护当前行为合同，不保护已经退出主链路的内部形状。

## Focused Commands

```powershell
python -m pytest backend/tests/run_monitor_projection_test.py -q
python -m pytest backend/tests/context_compaction_api_regression.py -q
python -m pytest backend/tests/system_eval/long_scenarios_regression.py -q
```
