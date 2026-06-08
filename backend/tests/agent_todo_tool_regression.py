from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from capability_system.tools.native_tool_catalog import get_tool_definitions
from capability_system.tools.tool_units.agent_todo_tool import AgentTodoTool
from capability_system.tools.tool_units.agent_todo_tool import _build_plan, _update_plan


def test_agent_todo_plan_allows_one_active_item_and_completion_ready() -> None:
    plan = _build_plan(
        session_id="s1",
        task_id="t1",
        items=[
            {"todo_id": "inspect", "content": "Inspect code", "status": "completed"},
            {"todo_id": "verify", "content": "Run verification", "status": "completed"},
        ],
    )

    assert plan["completion_ready"] is True
    assert plan["active_item_id"] == ""

    started = _update_plan(
        plan,
        session_id="s1",
        task_id="t1",
        operation="start",
        todo_id="verify",
        items=[],
        status="",
        notes="",
    )

    assert started["active_item_id"] == "verify"
    assert [item["status"] for item in started["items"]] == ["completed", "in_progress"]


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


def test_agent_todo_rejects_target_operations_without_todo_id(tmp_path: Path) -> None:
    tool = AgentTodoTool(root_dir=tmp_path)
    tool._run(
        operation="replace",
        session_id="s",
        task_id="t",
        items=[
            {"todo_id": "read", "content": "Read current code", "status": "in_progress"},
            {"todo_id": "test", "content": "Run tests", "status": "pending"},
        ],
    )

    rejected = json.loads(tool._run(operation="complete", session_id="s", task_id="t"))
    viewed = json.loads(tool._run(operation="view", session_id="s", task_id="t"))

    assert rejected["status"] == "error"
    assert "requires todo_id" in rejected["error"]
    assert [item["status"] for item in viewed["items"]] == ["in_progress", "pending"]


def test_agent_todo_rejects_unknown_todo_id_without_mutating_state(tmp_path: Path) -> None:
    tool = AgentTodoTool(root_dir=tmp_path)
    tool._run(
        operation="replace",
        session_id="s",
        task_id="t",
        items=[
            {"todo_id": "read", "content": "Read current code", "status": "in_progress"},
            {"todo_id": "test", "content": "Run tests", "status": "pending"},
        ],
    )

    rejected = json.loads(tool._run(operation="remove", session_id="s", task_id="t", todo_id="missing"))
    viewed = json.loads(tool._run(operation="view", session_id="s", task_id="t"))

    assert rejected["status"] == "error"
    assert "todo_id not found" in rejected["error"]
    assert [item["todo_id"] for item in viewed["items"]] == ["read", "test"]


def test_agent_todo_preserves_subagent_orchestration_metadata() -> None:
    plan = _build_plan(
        session_id="s1",
        task_id="t1",
        items=[
            {
                "todo_id": "backend-runtime",
                "content": "审查 backend runtime",
                "owner_agent_id": "agent:codebase_searcher",
                "scope": "backend/harness",
                "handoff_goal": "定位 runtime 执行循环和风险点",
                "subagent_run_ref": "agrun:child",
                "parallel_group": "project-audit",
                "depends_on": ["top-level-scale-check"],
            }
        ],
    )

    item = plan["items"][0]
    assert item["owner_agent_id"] == "agent:codebase_searcher"
    assert item["scope"] == "backend/harness"
    assert item["handoff_goal"] == "定位 runtime 执行循环和风险点"
    assert item["subagent_run_ref"] == "agrun:child"
    assert item["parallel_group"] == "project-audit"
    assert item["depends_on"] == ["top-level-scale-check"]


def test_agent_todo_registered_as_non_destructive_tool() -> None:
    definitions = {definition.name: definition for definition in get_tool_definitions()}
    todo = definitions["agent_todo"]

    assert todo.operation_id == "op.agent_todo"
    assert todo.safe_for_auto_route is False
    assert todo.is_destructive is False
    assert todo.prompt_exposure_policy == "schema_plus_guidance"
    assert "progress_tracking" in todo.capability_tags


