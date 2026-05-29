# System Eval

`system_eval` 只承担场景实测和长链评估，不再混作普通模块回归。

## Position

- 快速链路验证走 `chain` profile。
- 单系统合同验证走 `functional` profile。
- 跨系统装配验证走 `system` profile。
- 长链、真实任务、人工可读报告走 `scenario` profile 或 `long` runner。

## Entrypoints

- 场景登记合同：
  - `python backend/tests/run_regression_gate.py --profile scenario`
- 长场景 runner：
  - `python backend/tests/run_regression_gate.py --profile scenario`
- 旧兼容 runner：
  - `python backend/tests/system_eval/runner.py --profile smoke`
  - `python backend/tests/system_eval/runner.py --profile stable`
  - `python backend/tests/system_eval/runner.py --profile full`

## Outputs

每次运行默认落到 `output/test_runs/<run_id>/`：

- `report.md`
- `run_result.json`
- `issues.json`
- `trace.jsonl`
- `artifacts/`

健康系统只消费场景实测结果形成健康风险；测试 harness 和测试治理入口不再挂在 `/api/health-system/maintenance/test-system/*` 下。
