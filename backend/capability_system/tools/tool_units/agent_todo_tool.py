from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Literal

from capability_system.tools.agent_todo_state import (
    AgentTodoStateStore,
    agent_todo_state_store_from_root,
    build_todo_plan,
    normalize_todo_items,
    render_todo_tool_payload,
    todo_items,
    update_todo_plan,
)
from capability_system.tools.base_tool import AsyncCallbackManagerForToolRun, BaseTool, CallbackManagerForToolRun
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr


class AgentTodoItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(description="Concrete todo item content.")
    active_form: str = Field(default="", description="Short active-form wording for the item while it is in progress.")
    status: Literal["pending", "in_progress", "completed"] = Field(
        default="pending",
        description="Current item status. Use in_progress for the one item currently being worked; never use active.",
    )
    notes: str = Field(default="", description="Brief evidence, blocker, or progress note for this item.")
    evidence_expectations: list[str] = Field(default_factory=list, description="Evidence expected before this item can be completed.")
    contract_refs: list[str] = Field(default_factory=list, description="Task contract references this item satisfies.")
    owner_agent_id: str = Field(default="", description="Optional subagent or owner agent id responsible for this item.")
    scope: str = Field(default="", description="Optional work scope for this item.")
    subagent_run_ref: str = Field(default="", description="Optional subagent run reference.")
    depends_on: list[str] = Field(default_factory=list, description="Todo ids that must be completed before this item.")
    handoff_goal: str = Field(default="", description="Optional goal when handing the item to another agent.")
    parallel_group: str = Field(default="", description="Optional group id for items that can progress in parallel.")


class AgentTodoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["replace", "append", "start", "complete", "update_status", "remove", "clear", "view"] = Field(
        default="replace",
        description="Todo operation. Use replace for a fresh task list, append for discovered work, start/complete/update_status for progress, remove for irrelevant items, clear to reset, view to inspect.",
    )
    session_id: str = Field(default="default", description="Current session id; use default when no runtime session id is provided.")
    task_id: str = Field(default="runtime", description="Current task id; task execution runtime binds default/runtime to the active task run.")
    items: list[AgentTodoItemInput] = Field(
        default_factory=list,
        description=(
            "Todo items for replace/append. Each item should include content, optional active_form, status, "
            "evidence_expectations, contract_refs, and optional subagent orchestration metadata such as "
            "owner_agent_id, scope, subagent_run_ref, depends_on, handoff_goal, or parallel_group."
        ),
    )
    todo_id: str = Field(default="", description="Target todo id for start, complete, update_status, or remove. Use this field name, not id.")
    status: Literal["", "pending", "in_progress", "completed"] = Field(
        default="",
        description="Target status for update_status: pending, in_progress, or completed. Leave empty for other operations; never use active.",
    )
    notes: str = Field(default="", description="Short note explaining a status update or blocker.")


class AgentTodoTool(BaseTool):
    name: str = "agent_todo"
    description: str = (
        "Create and maintain the agent's visible todo list for the current task. "
        "Use it after understanding a non-trivial request, when the user provides multiple steps, "
        "when you start a step, when you complete a step, or when new work is discovered. "
        "Todo items are execution state: they must be concrete, update as work changes, and should not replace the user's goal or the semantic task contract. "
        "Keep at most one item in_progress. Do not mark an item completed unless the work is actually done or the blocker is recorded. "
        "In task execution, omit session_id/task_id or leave their defaults to update the current task-bound plan."
    )
    args_schema: type[BaseModel] = AgentTodoInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _state_store: AgentTodoStateStore = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self._state_store = agent_todo_state_store_from_root(root_dir)

    def _run(
        self,
        operation: str = "replace",
        session_id: str = "default",
        task_id: str = "runtime",
        items: list[dict[str, Any]] | None = None,
        todo_id: str = "",
        status: str = "",
        notes: str = "",
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        try:
            normalized_items = normalize_todo_items(items=list(items or []))
            current = self._state_store.read(session_id=session_id, task_id=task_id)
            if operation == "view":
                plan = build_todo_plan(session_id=session_id, task_id=task_id, items=todo_items(current))
            else:
                plan = update_todo_plan(
                    current,
                    session_id=session_id,
                    task_id=task_id,
                    operation=operation,
                    items=normalized_items,
                    todo_id=todo_id,
                    status=status,
                    notes=notes,
                )
                self._state_store.write(session_id=session_id, task_id=task_id, payload=plan)
        except Exception as exc:
            return json.dumps(
                {
                    "status": "error",
                    "error": str(exc),
                    "diagnostics": {
                        "operation": str(operation or ""),
                        "session_id": str(session_id or ""),
                        "task_id": str(task_id or ""),
                        "authority": "agent.todo_plan",
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        payload = render_todo_tool_payload(dict(plan))
        return json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )

    async def _arun(
        self,
        operation: str = "replace",
        session_id: str = "default",
        task_id: str = "runtime",
        items: list[dict[str, Any]] | None = None,
        todo_id: str = "",
        status: str = "",
        notes: str = "",
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        return await asyncio.to_thread(self._run, operation, session_id, task_id, items, todo_id, status, notes, None)

_build_plan = build_todo_plan
_update_plan = update_todo_plan


