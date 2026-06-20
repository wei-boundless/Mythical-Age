from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import threading
import time
from typing import Any, Callable, Coroutine


AsyncWorkFactory = Callable[[], Coroutine[Any, Any, Any]]
WorkerDoneCallback = Callable[["AgentWorkerHandle"], None]


@dataclass(slots=True)
class AgentWorkerHandle:
    worker_id: str
    run_cell_id: str
    thread: threading.Thread
    started_at: float
    done_at: float = 0.0
    result: Any = None
    error: BaseException | None = None
    cancel_requested: bool = False
    cancel_delivered: bool = False
    cancelled: bool = False
    cancel_reason: str = ""
    loop: asyncio.AbstractEventLoop | None = None
    task: asyncio.Task[Any] | None = None
    done_event: threading.Event = field(default_factory=threading.Event)

    def request_cancel(self, reason: str = "agent_cell_cancelled") -> bool:
        self.cancel_requested = True
        self.cancel_reason = str(reason or "").strip() or "agent_cell_cancelled"
        loop = self.loop
        task = self.task
        if loop is None or task is None:
            return self.is_running()
        if task.done():
            return False
        self.cancel_delivered = True
        loop.call_soon_threadsafe(task.cancel, self.cancel_reason)
        return True

    def is_running(self) -> bool:
        return self.thread.is_alive() and not self.done_event.is_set()

    def join(self, timeout: float | None = None) -> bool:
        self.thread.join(timeout=timeout)
        return self.done_event.is_set()


class AgentWorkerBackend:
    backend_name = "abstract"

    def start(self, *, run_cell_id: str, work_factory: AsyncWorkFactory, on_done: WorkerDoneCallback | None = None) -> AgentWorkerHandle:
        raise NotImplementedError


class ThreadAgentWorkerBackend(AgentWorkerBackend):
    backend_name = "thread"

    def start(self, *, run_cell_id: str, work_factory: AsyncWorkFactory, on_done: WorkerDoneCallback | None = None) -> AgentWorkerHandle:
        handle = AgentWorkerHandle(
            worker_id=f"agent-worker:{run_cell_id}",
            run_cell_id=run_cell_id,
            thread=threading.Thread(),
            started_at=time.time(),
        )

        def _runner() -> None:
            loop = asyncio.new_event_loop()
            handle.loop = loop
            try:
                asyncio.set_event_loop(loop)
                task = loop.create_task(work_factory())
                handle.task = task
                if handle.cancel_requested:
                    handle.cancel_delivered = True
                    task.cancel(handle.cancel_reason)
                handle.result = loop.run_until_complete(task)
            except asyncio.CancelledError as exc:
                handle.cancelled = True
                handle.error = exc
            except BaseException as exc:  # noqa: BLE001
                handle.error = exc
            finally:
                handle.done_at = time.time()
                try:
                    _cancel_pending(loop)
                finally:
                    loop.close()
                    handle.done_event.set()
                    if on_done is not None:
                        on_done(handle)

        thread = threading.Thread(target=_runner, name=f"agent-cell:{run_cell_id}", daemon=True)
        handle.thread = thread
        thread.start()
        return handle


def _cancel_pending(loop: asyncio.AbstractEventLoop) -> None:
    pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
    if not pending:
        return
    for task in pending:
        task.cancel()
    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
