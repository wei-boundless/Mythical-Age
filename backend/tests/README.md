# Test Layout

当前仓库的测试体系已经切成三层：

- `backend/tests/run_regression_gate.py`
  负责后端 curated regression gate，适合改完代码后做快速门禁。
- `backend/tests/system_eval/runner.py`
  负责 profile 化 system eval，统一落 `report.md`、`run_result.json`、`issues.json`、`trace.jsonl`。
- `backend/observability/langsmith_tracing.py`
  负责可选 LangSmith trace 适配。测试本身不依赖 LangSmith 才能运行，但开启后会把 trace id/url 挂回评测结果。

## Execution Model

- `core` regression gate：关键运行时、路由、SSE smoke、场景目录合同。
- `full` regression gate：在 `core` 之上补 memory / retrieval / pdf / structured / task 回归。
- `smoke` system eval：一条真实 in-process SSE 聊天 smoke，加前端流式 reducer 测试。
- `stable` system eval：`smoke` + `core` regression gate。
- `full` system eval：`stable` + `full` regression gate + 前端 production build。
- `deep` system eval：`full` + 长链/记忆实验。

## Recommended Entrypoints

- 后端快速回归：
  - `python backend/tests/run_regression_gate.py --profile core`
- 后端完整回归：
  - `python backend/tests/run_regression_gate.py --profile full`
- 统一 smoke：
  - `python -m harness.run --profile smoke`
- 统一 stable：
  - `python -m harness.run --profile stable`
- 统一 full：
  - `python -m harness.run --profile full`
- 长情景：
  - `python -m harness.run --profile long`

## LangSmith

启用 LangSmith 需要这些环境变量之一：

- `LANGSMITH_API_KEY` 或 `LANGCHAIN_API_KEY`
- `LANGSMITH_TRACING=true` 或 `LANGCHAIN_TRACING_V2=true`
- 可选：`LANGSMITH_PROJECT`
- 可选：`LANGSMITH_DEV_TRACE_LINKS=true`

启用后，query runtime 会在开发环境的 SSE `debug` 事件里带出 `trace_id` / `trace_url`，system eval 会把它们写进结果和失败报告。
