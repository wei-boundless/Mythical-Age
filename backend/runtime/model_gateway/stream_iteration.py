from __future__ import annotations

import asyncio
import contextlib
from typing import Any, AsyncIterator


async def iterate_stream_with_due_ticks(
    stream: Any,
    *,
    timeout_seconds: float,
    tick_seconds: float,
) -> AsyncIterator[tuple[str, Any]]:
    timeout = max(0.01, float(timeout_seconds or 0.01))
    tick = max(0.001, float(tick_seconds or 0.001))
    iterator = stream.__aiter__()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    next_task = asyncio.create_task(iterator.__anext__())
    try:
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                await _close_stream_iterator(iterator, stream)
                raise asyncio.TimeoutError
            done, _pending = await asyncio.wait({next_task}, timeout=min(remaining, tick))
            if not done:
                if deadline - loop.time() <= 0:
                    await _close_stream_iterator(iterator, stream)
                    raise asyncio.TimeoutError
                yield ("tick", None)
                continue
            try:
                chunk = next_task.result()
            except StopAsyncIteration:
                return
            yield ("chunk", chunk)
            next_task = asyncio.create_task(iterator.__anext__())
    finally:
        if not next_task.done():
            next_task.cancel()
            next_task.add_done_callback(_discard_task_exception)


async def _close_stream_iterator(iterator: Any, stream: Any) -> None:
    close = getattr(iterator, "aclose", None) or getattr(stream, "aclose", None)
    if callable(close):
        with contextlib.suppress(BaseException):
            await close()


def _discard_task_exception(task: asyncio.Task[Any]) -> None:
    with contextlib.suppress(BaseException):
        task.exception()
