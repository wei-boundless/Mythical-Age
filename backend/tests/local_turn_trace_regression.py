from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from observability.langsmith_tracing import LocalTurnTrace


def test_local_trace_treats_scheduled_task_stream_close_as_success(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LOCAL_TRACE_ENABLED", "1")
    monkeypatch.setenv("LOCAL_TRACE_DIR", str(tmp_path))
    trace = LocalTurnTrace(
        session_id="session-trace",
        user_message="启动长任务",
        history_length=0,
    )

    trace.__enter__()
    trace.mark_terminal(status="task_executor_scheduled", reason="task_executor_scheduled")
    trace.__exit__(GeneratorExit, GeneratorExit(), None)

    payload = json.loads(Path(trace.trace_url).read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    assert payload["terminal_status"] == "task_executor_scheduled"
    assert payload["terminal_reason"] == "task_executor_scheduled"
    assert payload["error"] == ""


def test_local_trace_keeps_real_exception_as_error(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LOCAL_TRACE_ENABLED", "1")
    monkeypatch.setenv("LOCAL_TRACE_DIR", str(tmp_path))
    trace = LocalTurnTrace(
        session_id="session-trace-error",
        user_message="请求",
        history_length=0,
    )
    exc = RuntimeError("model failed")

    trace.__enter__()
    trace.mark_terminal(status="task_executor_scheduled", reason="task_executor_scheduled")
    trace.__exit__(RuntimeError, exc, None)

    payload = json.loads(Path(trace.trace_url).read_text(encoding="utf-8"))
    assert payload["status"] == "error"
    assert payload["error"] == "model failed"
