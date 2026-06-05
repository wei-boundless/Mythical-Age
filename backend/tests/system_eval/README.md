# System Eval

`system_eval` 只承担长场景目录合同、压力实验和人工可读报告，不作为普通快速回归的主要目录。

## Position

- `long_scenarios_regression.py` 是轻量目录合同，进入默认 pytest。
- `long_scenarios.py` 是场景数据源，不直接执行。
- `*_experiment.py` 是显式实验脚本，可能启动长任务、写报告或依赖本地运行时状态，不进入默认 pytest。

## Entrypoints

- 场景目录合同：
  - `python -m pytest backend/tests/system_eval/long_scenarios_regression.py -q`
- 显式实验脚本：
  - `python backend/tests/system_eval/task_run_control_live_experiment.py`
  - `python backend/tests/system_eval/dual_node_semantic_monitor_experiment.py`
  - `python backend/tests/system_eval/active_task_steering_fault_and_stress_experiment.py`
  - `python backend/tests/system_eval/active_task_steering_live_experiment.py`
  - `python backend/tests/system_eval/long_task_natural_language_control_experiment.py`
  - `python backend/tests/system_eval/long_task_natural_language_pressure_experiment.py`

## Outputs

每次运行默认落到 `output/test_runs/<run_id>/`：

- `report.md`
- `run_result.json`
- `issues.json`
- `trace.jsonl`
- `artifacts/`

不要在本目录新增旧 profile runner、case registry 或 HealthSystem 维护入口。需要进入默认门禁的行为测试应写成普通 pytest 文件。
