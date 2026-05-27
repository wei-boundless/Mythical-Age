from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from .checkpoint_adapter import CoordinationCheckpoint, GraphCoordinationCheckpointStore


@dataclass(frozen=True, slots=True)
class KernelStreamEvent:
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    authority: str = "harness.graph_coordination_kernel_stream_event"

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "payload": dict(self.payload),
            "created_at": float(self.created_at or 0.0),
            "authority": self.authority,
        }


@dataclass(frozen=True, slots=True)
class KernelStepResult:
    state: dict[str, Any]
    checkpoint: CoordinationCheckpoint
    physical_events: tuple[KernelStreamEvent, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.graph_coordination_kernel_step_result"

    @property
    def checkpoint_ref(self) -> str:
        return self.checkpoint.checkpoint_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": dict(self.state),
            "checkpoint": self.checkpoint.to_dict(),
            "checkpoint_ref": self.checkpoint_ref,
            "physical_events": [item.to_dict() for item in self.physical_events],
            "diagnostics": dict(self.diagnostics),
            "authority": self.authority,
        }


class GraphCoordinationKernel:
    """Physical LangGraph execution boundary for GraphLoop coordination.

    The kernel owns the mechanics of invoking the compiled LangGraph app and
    linking the resulting state to a durable checkpoint. It deliberately does
    not allocate TaskGraph semantic clock values; that belongs to TimelineLedger.
    """

    authority = "harness.graph_coordination_kernel"

    def __init__(
        self,
        *,
        app: Any,
        checkpoints: GraphCoordinationCheckpointStore,
    ) -> None:
        self.app = app
        self.checkpoints = checkpoints

    def invoke(
        self,
        *,
        state: dict[str, Any],
        thread_id: str,
        reason: str,
        checkpoint_metadata: dict[str, Any] | None = None,
    ) -> KernelStepResult:
        clean_thread_id = _required_thread_id(thread_id)
        started_at = time.time()
        result = self.app.invoke(
            dict(state or {}),
            config={"configurable": {"thread_id": clean_thread_id}},
        )
        final_state = dict(result or state or {})
        checkpoint = self.checkpoint(
            state=final_state,
            thread_id=clean_thread_id,
            reason=reason,
            checkpoint_metadata={
                "kernel_reason": reason,
                "started_at": started_at,
                **dict(checkpoint_metadata or {}),
            },
        ).checkpoint
        return KernelStepResult(
            state=final_state,
            checkpoint=checkpoint,
            physical_events=(
                KernelStreamEvent(
                    event_type="langgraph_invoke_completed",
                    payload={
                        "thread_id": clean_thread_id,
                        "reason": reason,
                        "checkpoint_ref": checkpoint.checkpoint_id,
                    },
                    created_at=time.time(),
                ),
            ),
            diagnostics={
                "kernel": self.authority,
                "reason": reason,
                "thread_id": clean_thread_id,
            },
        )

    def checkpoint(
        self,
        *,
        state: dict[str, Any],
        thread_id: str,
        reason: str,
        checkpoint_metadata: dict[str, Any] | None = None,
    ) -> KernelStepResult:
        clean_thread_id = _required_thread_id(thread_id)
        checkpoint = self.checkpoints.put_state(
            thread_id=clean_thread_id,
            state=dict(state or {}),
            metadata={
                "event": reason,
                "kernel": self.authority,
                **dict(checkpoint_metadata or {}),
            },
        )
        return KernelStepResult(
            state=dict(state or {}),
            checkpoint=checkpoint,
            physical_events=(
                KernelStreamEvent(
                    event_type="langgraph_checkpoint_written",
                    payload={
                        "thread_id": clean_thread_id,
                        "reason": reason,
                        "checkpoint_ref": checkpoint.checkpoint_id,
                    },
                    created_at=checkpoint.created_at,
                ),
            ),
            diagnostics={
                "kernel": self.authority,
                "reason": reason,
                "thread_id": clean_thread_id,
            },
        )

    def stream(
        self,
        *,
        state: dict[str, Any],
        thread_id: str,
        reason: str,
        checkpoint_metadata: dict[str, Any] | None = None,
    ) -> Iterable[KernelStreamEvent]:
        clean_thread_id = _required_thread_id(thread_id)
        if not hasattr(self.app, "stream"):
            yield KernelStreamEvent(
                event_type="langgraph_stream_unavailable",
                payload={"thread_id": clean_thread_id, "reason": reason},
                created_at=time.time(),
            )
            return
        for item in self.app.stream(
            dict(state or {}),
            config={"configurable": {"thread_id": clean_thread_id}},
        ):
            yield KernelStreamEvent(
                event_type="langgraph_stream_item",
                payload={"thread_id": clean_thread_id, "reason": reason, "item": item},
                created_at=time.time(),
            )
        self.checkpoint(
            state=dict(state or {}),
            thread_id=clean_thread_id,
            reason=reason,
            checkpoint_metadata=checkpoint_metadata,
        )


def _required_thread_id(thread_id: str) -> str:
    clean = str(thread_id or "").strip()
    if not clean:
        raise ValueError("GraphCoordinationKernel requires thread_id")
    return clean




