# System Eval

这层不是替代模块回归，而是把回归门禁、真实 SSE smoke、前端 reducer 和产物报告串成统一 baseline。

## Profiles

- `smoke`
  - 一条 in-process `/api/chat` SSE smoke
  - 前端 `events.test.ts`
- `stable`
  - `smoke`
  - `core` regression gate
- `full`
  - `stable`
  - `full` regression gate
  - 前端 `build`
- `deep`
  - `full`
  - memory / context 实验
- `long`
  - 可执行长对话场景
  - 覆盖工作台全链路、跨会话 durable memory、多 session 隔离、复合任务拆分
- `benchmark`
  - 当前先复用 `full`，保留后续扩展 timing benchmark 的入口

## Outputs

每次运行默认会落到 `output/test_runs/<run_id>/`：

- `report.md`
- `run_result.json`
- `issues.json`
- `trace.jsonl`
- `artifacts/`

如果 LangSmith 开启，失败项和 smoke 结果里会包含 `trace_id` / `trace_url`。
