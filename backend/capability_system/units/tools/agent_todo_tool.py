from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Literal

from langchain_core.callbacks.manager import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr


class AgentTodoInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    operation: Literal["replace", "append", "start", "complete", "update_status", "remove", "clear", "view"] = Field(
        default="replace",
        description="Todo operation. Use replace for a fresh task list, append for discovered work, start/complete/update_status for progress, remove for irrelevant items, clear to reset, view to inspect.",
    )
    session_id: str = Field(default="default", description="Current session id; use default when no runtime session id is provided.")
    task_id: str = Field(default="runtime", description="Current task id; use runtime when no task id is provided.")
    items: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Todo items for replace/append. Each item should include content, optional active_form, status, evidence_expectations, and contract_refs. Use this field instead of todos.",
    )
    todo_id: str = Field(default="", description="Target todo id for start, complete, update_status, or remove.")
    status: str = Field(default="", description="Target status for update_status: pending, in_progress, or completed.")
    notes: str = Field(default="", description="Short note explaining a status update or blocker.")


class AgentTodoTool(BaseTool):
    name: str = "agent_todo"
    description: str = (
        "Create and maintain the agent's visible todo list for the current task. "
        "Use it after understanding a non-trivial request, when the user provides multiple steps, "
        "when you start a step, when you complete a step, or when new work is discovered. "
        "Todo items are execution state: they must be concrete, update as work changes, and should not replace the user's goal or the semantic task contract. "
        "Keep at most one item in_progress. Do not mark an item completed unless the work is actually done or the blocker is recorded."
    )
    args_schema: type[BaseModel] = AgentTodoInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _state_dir: Path = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self._state_dir = Path(root_dir).resolve() / ".tmp" / "agent_todo"
        self._state_dir.mkdir(parents=True, exist_ok=True)

    def _run(
        self,
        operation: str = "replace",
        session_id: str = "default",
        task_id: str = "runtime",
        items: list[dict[str, Any]] | None = None,
        todos: list[dict[str, Any]] | None = None,
        todo_id: str = "",
        status: str = "",
        notes: str = "",
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        try:
            from runtime.agent_runtime.agent_todo import build_agent_todo_plan, update_agent_todo_plan

            normalized_items = _normalize_items(items=items, todos=todos)
            current = self._read_state(session_id=session_id, task_id=task_id)
            if operation == "view":
                plan = build_agent_todo_plan(
                    session_id=session_id,
                    task_id=task_id,
                    items=[dict(item) for item in list(current.get("items") or []) if isinstance(item, dict)],
                )
            else:
                plan = update_agent_todo_plan(
                    current,
                    session_id=session_id,
                    task_id=task_id,
                    operation=operation,
                    items=normalized_items,
                    todo_id=todo_id,
                    status=status,
                    notes=notes,
                )
                self._write_state(session_id=session_id, task_id=task_id, payload=plan.to_dict())
        except Exception as exc:
            return f"agent_todo failed: {exc}"
        payload = plan.to_dict()
        return json.dumps(
            {
                "status": "ok",
                "plan_id": payload["plan_id"],
                "active_item_id": payload["active_item_id"],
                "completion_ready": payload["completion_ready"],
                "items": payload["items"],
                "diagnostics": payload["diagnostics"],
            },
            ensure_ascii=False,
            indent=2,
        )

    async def _arun(
        self,
        operation: str = "replace",
        session_id: str = "default",
        task_id: str = "runtime",
        items: list[dict[str, Any]] | None = None,
        todos: list[dict[str, Any]] | None = None,
        todo_id: str = "",
        status: str = "",
        notes: str = "",
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        return await asyncio.to_thread(self._run, operation, session_id, task_id, items, todos, todo_id, status, notes, None)

    def _state_path(self, *, session_id: str, task_id: str) -> Path:
        safe_session = _safe_key(session_id or "default")
        safe_task = _safe_key(task_id or "runtime")
        return self._state_dir / f"{safe_session}__{safe_task}.json"

    def _read_state(self, *, session_id: str, task_id: str) -> dict[str, Any]:
        path = self._state_path(session_id=session_id, task_id=task_id)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write_state(self, *, session_id: str, task_id: str, payload: dict[str, Any]) -> None:
        path = self._state_path(session_id=session_id, task_id=task_id)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _safe_key(value: str) -> str:
    result = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or ""))
    return result.strip("_")[:80] or "runtime"


def _normalize_items(
    *,
    items: list[dict[str, Any]] | None = None,
    todos: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    raw_items = list(items or [])
    if not raw_items and todos:
        raw_items = list(todos or [])
    return [dict(item) for item in raw_items if isinstance(item, dict)]
