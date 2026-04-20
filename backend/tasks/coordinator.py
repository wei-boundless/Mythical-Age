from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from agents import EXPLORER_AGENT, WORKER_AGENT
from tasks.models import TaskRecord


class TaskCoordinator:
    def __init__(self) -> None:
        self._tasks: dict[str, TaskRecord] = {}

    @property
    def tasks(self) -> list[TaskRecord]:
        return list(self._tasks.values())

    def get_task(self, task_id: str) -> TaskRecord | None:
        return self._tasks.get(task_id)

    def list_tasks(self, *, session_id: str | None = None) -> list[TaskRecord]:
        tasks = list(self._tasks.values())
        if session_id is not None:
            tasks = [
                task
                for task in tasks
                if str(task.metadata.get("session_id", "")) == session_id
            ]
        return sorted(tasks, key=lambda task: task.created_at)

    def _register(self, task: TaskRecord) -> TaskRecord:
        self._tasks[task.task_id] = task
        return task

    def _query_task(self, session_id: str, subquery: str, index: int) -> TaskRecord:
        return self._register(
            TaskRecord(
                task_id=f"{session_id}-subtask-{index}",
                task_type="query",
                query=subquery,
                agent_type=EXPLORER_AGENT.agent_type,
                metadata={"session_id": session_id, "subtask_index": index},
            )
        )

    def _tool_task(self, session_id: str, tool_name: str) -> TaskRecord:
        return self._register(
            TaskRecord(
                task_id=f"{session_id}-tool-{tool_name}-{len(self._tasks) + 1}",
                task_type="tool",
                query=tool_name,
                agent_type=WORKER_AGENT.agent_type,
                metadata={"session_id": session_id, "tool_name": tool_name},
            )
        )

    async def run_query_tasks(
        self,
        session_id: str,
        executions: list[Any],
        runner: Callable[[Any], AsyncIterator[dict[str, object]]],
    ) -> AsyncIterator[dict[str, object]]:
        for index, execution in enumerate(executions, start=1):
            subquery = execution.message
            task = self._query_task(session_id, subquery, index)
            task.mark_running()
            task.add_event("subtask_start", payload={"index": index, "query": subquery})
            yield {"type": "subtask_start", "index": index, "query": subquery}

            final_subcontent = ""
            try:
                async for event in runner(execution):
                    event_type = str(event.get("type", ""))
                    if event_type == "token":
                        continue
                    if event_type == "done":
                        final_subcontent = str(event.get("content", "") or "")
                        continue
                    forwarded = dict(event)
                    forwarded["subtask_index"] = index
                    forwarded["subtask_query"] = subquery
                    task.add_event(event_type or "event", payload=forwarded)
                    yield forwarded
            except Exception as exc:
                task.mark_failed(str(exc))
                task.add_event("subtask_error", message=str(exc))
                raise

            task.mark_completed(final_subcontent)
            task.add_event(
                "subtask_end",
                payload={"index": index, "query": subquery, "content": final_subcontent},
            )
            yield {
                "type": "subtask_end",
                "index": index,
                "query": subquery,
                "content": final_subcontent,
                "task_id": task.task_id,
            }

    async def run_tool_task(
        self,
        session_id: str,
        tool_name: str,
        runner: Callable[[], Awaitable[Any]],
    ) -> Any:
        task = self._tool_task(session_id, tool_name)
        task.mark_running()
        task.add_event("tool_task_start", payload={"tool_name": tool_name})
        try:
            result = await runner()
        except Exception as exc:
            task.mark_failed(str(exc))
            task.add_event("tool_task_error", message=str(exc))
            raise
        task.mark_completed(str(result))
        task.add_event("tool_task_end", payload={"tool_name": tool_name})
        return result
