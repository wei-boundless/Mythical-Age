from __future__ import annotations


class TraceReaderStub:
    def __init__(self, traces: dict[str, dict]) -> None:
        self.traces = dict(traces)

    def get_trace(
        self,
        task_run_id: str,
        *,
        include_payloads: bool = False,
        include_model_messages: bool = False,
    ):
        return self.traces.get(task_run_id)


class StateIndexStub:
    def __init__(self, task_runs=()) -> None:
        self._task_runs = tuple(task_runs)

    def list_task_runs(self):
        return self._task_runs


class TaskRunStub:
    def __init__(self, *, task_run_id: str, updated_at: float) -> None:
        self.task_run_id = task_run_id
        self.updated_at = updated_at
