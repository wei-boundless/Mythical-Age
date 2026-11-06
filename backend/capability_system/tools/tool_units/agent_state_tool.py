from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Literal

from capability_system.tools.base_tool import AsyncCallbackManagerForToolRun, BaseTool, CallbackManagerForToolRun
from capability_system.tools.tool_units.agent_todo_tool import AgentTodoTool, AgentTodoItemInput
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr


class AgentStateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["replace", "append", "start", "complete", "update_status", "remove", "clear", "view"] = Field(
        default="replace",
        description="State action for the visible execution todo list.",
    )
    session_id: str = Field(default="default", description="Runtime-bound session id; keep default unless runtime binds it.")
    task_id: str = Field(default="runtime", description="Runtime-bound task id; keep runtime unless runtime binds it.")
    items: list[AgentTodoItemInput] = Field(default_factory=list, description="Todo items for replace or append.")
    todo_id: str = Field(default="", description="Target todo id for item-level actions.")
    status: Literal["", "pending", "in_progress", "completed"] = Field(default="", description="Target status for update_status.")
    notes: str = Field(default="", description="Brief progress, blocker, or evidence note.")


class AgentStateTool(BaseTool):
    name: str = "agent_state"
    description: str = (
        "Maintain the agent's visible execution state for the current task. "
        "Use it to create, inspect, and update concrete todo items; keep at most one item in_progress."
    )
    args_schema: type[BaseModel] = AgentStateInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _delegate: AgentTodoTool = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._delegate = AgentTodoTool(root_dir=root_dir)

    def _run(
        self,
        action: str = "replace",
        session_id: str = "default",
        task_id: str = "runtime",
        items: list[dict[str, Any]] | None = None,
        todo_id: str = "",
        status: str = "",
        notes: str = "",
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        _ = run_manager
        return self._delegate.invoke(
            {
                "operation": action,
                "session_id": session_id,
                "task_id": task_id,
                "items": list(items or []),
                "todo_id": todo_id,
                "status": status,
                "notes": notes,
            }
        )

    async def _arun(
        self,
        action: str = "replace",
        session_id: str = "default",
        task_id: str = "runtime",
        items: list[dict[str, Any]] | None = None,
        todo_id: str = "",
        status: str = "",
        notes: str = "",
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        return await asyncio.to_thread(self._run, action, session_id, task_id, items, todo_id, status, notes, None)
