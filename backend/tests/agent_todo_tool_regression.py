from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from capability_system.tool_definitions import get_tool_definitions
from capability_system.units.tools.agent_todo_tool import AgentTodoTool
from harness.runtime.agent_todo import build_agent_todo_plan, update_agent_todo_plan


def test_agent_todo_plan_allows_one_active_item_and_completion_ready() -> None:
    plan = build_agent_todo_plan(
        session_id="s1",
        task_id="t1",
        items=[
            {"todo_id": "inspect", "content": "Inspect code", "status": "completed"},
            {"todo_id": "verify", "content": "Run verification", "status": "completed"},
        ],
    )

    assert plan.completion_ready is True
    assert plan.active_item_id == ""

    started = update_agent_todo_plan(
        plan.to_dict(),
        session_id="s1",
        task_id="t1",
        operation="start",
        todo_id="verify",
    )

    assert started.active_item_id == "verify"
    assert [item.status for item in started.items] == ["completed", "in_progress"]


def test_agent_todo_tool_persists_and_updates_state(tmp_path: Path) -> None:
    tool = AgentTodoTool(root_dir=tmp_path)
    created = json.loads(
        tool._run(
            operation="replace",
            session_id="s",
            task_id="t",
            items=[
                {"todo_id": "read", "content": "Read current code", "active_form": "Reading current code"},
                {"todo_id": "test", "content": "Run tests", "active_form": "Running tests"},
            ],
        )
    )
    assert created["status"] == "ok"
    assert len(created["items"]) == 2

    started = json.loads(tool._run(operation="start", session_id="s", task_id="t", todo_id="read"))
    assert started["active_item_id"] == "read"

    completed = json.loads(tool._run(operation="complete", session_id="s", task_id="t", todo_id="read"))
    assert completed["items"][0]["status"] == "completed"

    viewed = json.loads(tool._run(operation="view", session_id="s", task_id="t"))
    assert viewed["items"][0]["todo_id"] == "read"


def test_agent_todo_registered_as_non_destructive_tool() -> None:
    definitions = {definition.name: definition for definition in get_tool_definitions()}
    todo = definitions["agent_todo"]

    assert todo.operation_id == "op.agent_todo"
    assert todo.safe_for_auto_route is False
    assert todo.is_destructive is False
    assert todo.prompt_exposure_policy == "schema_only"
    assert "progress_tracking" in todo.capability_tags
