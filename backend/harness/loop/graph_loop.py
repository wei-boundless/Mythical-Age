from __future__ import annotations

from typing import Any


class GraphLoop:
    """Harness graph loop facade for graph state advancement.

    GraphLoop is the only dynamic owner of graph progression. The coordination
    engine is an implementation detail behind this facade.
    """

    def __init__(self, *, service_host: Any) -> None:
        self._service_host = service_host

    @property
    def _engine(self) -> Any:
        return self._service_host.graph_coordination_engine

    @property
    def checkpoints(self) -> Any:
        return self._engine.checkpoints

    def start_run(self, **kwargs: Any) -> Any:
        return self._service_host.start_task_graph_run(**kwargs)

    def dispatch_ready_batch_requests(self, **kwargs: Any) -> Any:
        return self._engine.dispatch_ready_batch_requests(**kwargs)

    def resume_human_gate(self, **kwargs: Any) -> Any:
        return self._engine.resume_human_gate(**kwargs)

    def resume_from_task_result(self, **kwargs: Any) -> Any:
        return self._engine.resume_from_task_result(**kwargs)

    def rewind_from_stage(self, **kwargs: Any) -> Any:
        return self._engine.rewind_from_stage(**kwargs)

