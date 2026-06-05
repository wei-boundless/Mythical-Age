# System Eval

`system_eval` 只承担长场景目录合同，不作为普通快速回归以外的实验入口目录。

## Position

- `long_scenarios_regression.py` 是轻量目录合同，进入默认 pytest。
- `long_scenarios.py` 是场景数据源，不直接执行。
- 长任务、压力实验和人工报告入口不放在测试目录；需要进入门禁的行为必须写成普通 pytest 文件。

## Entrypoints

- 场景目录合同：
  - `python -m pytest backend/tests/system_eval/long_scenarios_regression.py -q`
不要在本目录新增旧 profile runner、case registry、手工 experiment 或 HealthSystem 维护入口。需要进入默认门禁的行为测试应写成普通 pytest 文件。
