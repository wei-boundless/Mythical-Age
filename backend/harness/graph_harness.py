from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

from .loop.coordination_delivery import run_coordination_delivery_stream
from .loop.graph_loop import GraphLoop
from .runtime import CoordinationStageAgentRunRequest


class GraphHarness:
    """Production control facade for task graph orchestration.

    GraphHarness advances graph state and delegates agent nodes into
    AgentHarness. It must not implement a second model/tool loop.
    """

    def __init__(self, *, service_host: Any, agent_harness: Any | None = None) -> None:
        self._service_host = service_host
        self._agent_harness = agent_harness
        self._graph_loop = GraphLoop(service_host=service_host)

    @property
    def graph_loop(self) -> GraphLoop:
        return self._graph_loop

    @property
    def state_index(self) -> Any:
        return self._service_host.state_index

    @property
    def checkpoints(self) -> Any:
        return self._graph_loop.checkpoints

    @property
    def task_checkpoints(self) -> Any:
        return self._service_host.checkpoints

    @property
    def runtime_objects(self) -> Any:
        return self._service_host.runtime_objects

    def start_run(self, **kwargs: Any) -> Any:
        return self._graph_loop.start_run(**kwargs)

    async def run_coordination_stage_stream(
        self,
        request: CoordinationStageAgentRunRequest,
    ) -> AsyncIterator[dict[str, Any]]:
        if self._agent_harness is None:
            raise RuntimeError("AgentHarness is required to execute a graph coordination stage")
        current_request = request
        while True:
            next_payload: dict[str, Any] = {}
            suppress_done = bool(dict(current_request.continuation_payload or {}).get("suppress_done"))
            async for event in run_coordination_delivery_stream(
                self._service_host,
                self._agent_harness,
                current_request,
            ):
                if event.get("type") == "done":
                    next_payload = dict(event.get("coordination_continuation") or {})
                    if not suppress_done:
                        yield event
                    continue
                yield event
            if not next_payload:
                return
            current_request = replace(current_request, continuation_payload=next_payload)

    def append_event(
        self,
        task_run_id: str,
        event_type: str,
        *,
        payload: dict[str, Any] | None = None,
        refs: dict[str, Any] | None = None,
    ) -> Any:
        return self._service_host.event_log.append(
            task_run_id,
            event_type,
            payload=dict(payload or {}),
            refs=dict(refs or {}),
        )

    def list_task_events(self, task_run_id: str) -> tuple[Any, ...]:
        return tuple(self._service_host.event_log.list_events(task_run_id))

    def get_trace(self, task_run_id: str, **kwargs: Any) -> dict[str, Any] | None:
        return self._service_host.get_trace(task_run_id, **kwargs)

    def get_coordination_run_monitor(self, coordination_run_id: str) -> dict[str, Any] | None:
        return self._service_host.get_coordination_run_monitor(coordination_run_id)

    def get_coordination_run(self, coordination_run_id: str) -> Any | None:
        return self.state_index.get_coordination_run(coordination_run_id)

    def get_task_run(self, task_run_id: str) -> Any | None:
        return self.state_index.get_task_run(task_run_id)

    @property
    def root_dir(self) -> Any:
        return self._service_host.root_dir

    def upsert_task_run(self, task_run: Any) -> None:
        self.state_index.upsert_task_run(task_run)

    def upsert_coordination_run(self, coordination_run: Any) -> None:
        self.state_index.upsert_coordination_run(coordination_run)

    def upsert_agent_run(self, agent_run: Any) -> None:
        self.state_index.upsert_agent_run(agent_run)

    def list_task_runs(self) -> tuple[Any, ...]:
        return tuple(self.state_index.list_task_runs())

    def list_task_agent_runs(self, task_run_id: str) -> tuple[Any, ...]:
        return tuple(self.state_index.list_task_agent_runs(task_run_id))

    def list_coordination_node_runs(self, coordination_run_id: str) -> tuple[Any, ...]:
        return tuple(self.state_index.list_coordination_node_runs(coordination_run_id))

    def upsert_coordination_node_run(self, node_run: Any) -> None:
        self.state_index.upsert_coordination_node_run(node_run)

    def list_session_task_runs(self, session_id: str) -> tuple[Any, ...]:
        return tuple(self.state_index.list_session_task_runs(session_id))

    def list_task_coordination_runs(self, task_run_id: str) -> tuple[Any, ...]:
        return tuple(self.state_index.list_task_coordination_runs(task_run_id))

    def get_latest_coordination_merge_result(self, coordination_run_id: str) -> Any | None:
        return self.state_index.get_latest_coordination_merge_result(coordination_run_id)

    def load_latest_task_checkpoint(self, task_run_id: str) -> Any | None:
        return self.task_checkpoints.load_latest(task_run_id)

    def recover_completed_checkpoint_task_run(
        self,
        *,
        task_run_id: str,
        current_turn_context: dict[str, Any],
    ) -> Any:
        return self._service_host.recover_completed_checkpoint_task_run(
            task_run_id=task_run_id,
            current_turn_context=dict(current_turn_context or {}),
        )

    def put_runtime_object(self, collection: str, object_id: str, payload: dict[str, Any]) -> str:
        return self.runtime_objects.put_object(collection, object_id, payload)

    def get_runtime_object(self, object_ref: str) -> dict[str, Any]:
        return dict(self.runtime_objects.get_object(object_ref) or {})

    def get_checkpoint_state(self, coordination_run_id: str) -> dict[str, Any]:
        return dict(self.checkpoints.get_state(thread_id=coordination_run_id) or {})

    def put_checkpoint_state(
        self,
        *,
        coordination_run_id: str,
        state: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        return self.checkpoints.put_state(
            thread_id=coordination_run_id,
            state=state,
            metadata=dict(metadata or {}),
        )

    def dispatch_ready_batch_requests(self, **kwargs: Any) -> Any:
        return self._graph_loop.dispatch_ready_batch_requests(**kwargs)

    def resume_human_gate(self, **kwargs: Any) -> Any:
        return self._graph_loop.resume_human_gate(**kwargs)

    def resume_from_task_result(self, **kwargs: Any) -> Any:
        return self._graph_loop.resume_from_task_result(**kwargs)

    def rewind_from_stage(self, **kwargs: Any) -> Any:
        return self._graph_loop.rewind_from_stage(**kwargs)


