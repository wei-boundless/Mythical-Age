from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Any, Callable, Coroutine

from runtime.tool_runtime.tool_invocation_control import (
    ToolInvocationControlRegistry,
    bind_thread_tool_invocation_registry,
    clear_thread_tool_invocation_registry,
)

from .agent_scope import AgentRunScope
from .agent_worker_backend import AgentWorkerBackend, AgentWorkerHandle
from .cell_mailbox import BoundedCellMailbox, CellMailboxItem


AsyncWorkFactory = Callable[[], Coroutine[Any, Any, Any]]
MailboxOverflowHandler = Callable[[AgentRunScope, CellMailboxItem, dict[str, Any]], None]


class CellCancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()
        self.reason = ""
        self.requested_at = 0.0

    def cancel(self, reason: str = "agent_cell_cancelled") -> None:
        self.reason = str(reason or "").strip() or "agent_cell_cancelled"
        self.requested_at = time.time()
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


@dataclass(frozen=True, slots=True)
class AgentCellHeartbeat:
    run_cell_id: str
    status: str
    updated_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_cell_id": self.run_cell_id,
            "status": self.status,
            "updated_at": self.updated_at,
        }


class AgentRuntimeCell:
    def __init__(
        self,
        *,
        scope: AgentRunScope,
        worker_backend: AgentWorkerBackend,
        mailbox_size: int = 128,
        mailbox_overflow_handler: MailboxOverflowHandler | None = None,
    ) -> None:
        self.scope = scope
        self.worker_backend = worker_backend
        self._mailbox_overflow_handler = mailbox_overflow_handler
        self.mailbox = BoundedCellMailbox(maxsize=mailbox_size, on_overflow=self._handle_mailbox_overflow)
        self.cancellation_token = CellCancellationToken()
        self.tool_invocation_registry = ToolInvocationControlRegistry(
            agent_run_id=scope.agent_run_id,
            run_cell_id=scope.run_cell_id,
        )
        self.created_at = time.time()
        self.started_at = 0.0
        self.completed_at = 0.0
        self.status = "created"
        self.worker_handle: AgentWorkerHandle | None = None
        self._lock = threading.RLock()

    def start(self, work_factory: AsyncWorkFactory, *, on_done: Callable[[AgentWorkerHandle], None] | None = None) -> AgentWorkerHandle:
        with self._lock:
            if self.worker_handle is not None and self.worker_handle.is_running():
                return self.worker_handle
            self.started_at = time.time()
            self.status = "running"
            self.mailbox.put("cell.started", {"agent_scope": self.scope.to_dict()})

            async def _scoped_work() -> Any:
                bind_thread_tool_invocation_registry(self.tool_invocation_registry)
                try:
                    return await work_factory()
                finally:
                    clear_thread_tool_invocation_registry()

            handle = self.worker_backend.start(
                run_cell_id=self.scope.run_cell_id,
                work_factory=_scoped_work,
                on_done=on_done,
            )
            self.worker_handle = handle
            return handle

    def request_cancel(self, reason: str = "agent_cell_cancelled") -> bool:
        with self._lock:
            self.cancellation_token.cancel(reason)
            tool_cancelled_count = self.tool_invocation_registry.cancel_by_caller(
                task_run_id=self.scope.task_run_id,
                agent_run_id=self.scope.agent_run_id,
                run_cell_id=self.scope.run_cell_id,
                kind="cancel",
                reason=self.cancellation_token.reason,
                requested_by="agent_runtime_cell",
            )
            self.mailbox.put(
                "cell.cancel_requested",
                {
                    "reason": self.cancellation_token.reason,
                    "tool_cancelled_count": tool_cancelled_count,
                },
            )
            if self.worker_handle is None:
                self.status = "cancelled"
                self.completed_at = time.time()
                return False
            self.status = "cancel_requested"
            return self.worker_handle.request_cancel(self.cancellation_token.reason)

    def mark_done(self, handle: AgentWorkerHandle) -> None:
        with self._lock:
            self.completed_at = handle.done_at or time.time()
            if handle.cancelled or handle.cancel_delivered:
                self.status = "cancelled"
            elif handle.error is not None:
                self.status = "failed"
            else:
                self.status = "completed"
            self.mailbox.close()

    def _handle_mailbox_overflow(self, item: CellMailboxItem, details: dict[str, Any]) -> None:
        handler = self._mailbox_overflow_handler
        if callable(handler):
            handler(self.scope, item, details)

    def is_running(self) -> bool:
        handle = self.worker_handle
        return bool(handle is not None and handle.is_running())

    def heartbeat(self) -> AgentCellHeartbeat:
        return AgentCellHeartbeat(
            run_cell_id=self.scope.run_cell_id,
            status=self.status,
            updated_at=time.time(),
        )

    def to_dict(self) -> dict[str, Any]:
        handle = self.worker_handle
        return {
            "agent_scope": self.scope.to_dict(),
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "worker": {
                "worker_id": handle.worker_id if handle is not None else "",
                "backend": self.worker_backend.backend_name,
                "running": handle.is_running() if handle is not None else False,
                "cancel_requested": handle.cancel_requested if handle is not None else False,
                "cancel_delivered": handle.cancel_delivered if handle is not None else False,
                "cancelled": handle.cancelled if handle is not None else False,
                "error": str(handle.error or "") if handle is not None else "",
            },
            "mailbox": {
                "size": self.mailbox.qsize(),
                "closed": self.mailbox.closed,
                "dropped_count": self.mailbox.dropped_count,
            },
            "heartbeat": self.heartbeat().to_dict(),
        }
