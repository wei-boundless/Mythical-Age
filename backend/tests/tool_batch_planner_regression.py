from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from harness.loop.action_permit import action_permit_from_admission
from harness.loop.admission import AdmissionDecision
from harness.loop.model_action_protocol import ModelActionRequest
from harness.runtime import build_runtime_tool_plan, build_tool_batch_plan


def test_tool_batch_planner_groups_consecutive_read_only_tools_in_parallel(tmp_path: Path) -> None:
    plan = _tool_plan({"read_file": "op.read_file", "path_exists": "op.path_exists"})
    rows = [
        _row("read_file", operation_id="op.read_file", args={"path": "requirements.txt"}),
        _row("path_exists", operation_id="op.path_exists", args={"path": "requirements.txt"}),
    ]

    batch = build_tool_batch_plan(
        turn_id="turn:test",
        packet_ref="packet:test",
        invocation_rows=rows,
        tool_plan=plan,
        definitions_by_name=_definitions({"read_file": "op.read_file", "path_exists": "op.path_exists"}),
        workspace_root=tmp_path,
    )

    assert len(batch.groups) == 1
    assert batch.groups[0].parallel is True
    assert batch.groups[0].execution_class == "parallel_read"
    assert batch.groups[0].item_indexes == (0, 1)
    assert [item.execution_class for item in batch.items] == ["parallel_read", "parallel_read"]


def test_tool_batch_planner_keeps_side_effect_tools_exclusive(tmp_path: Path) -> None:
    plan = _tool_plan({"write_file": "op.write_file", "edit_file": "op.edit_file"})
    rows = [
        _row("write_file", operation_id="op.write_file", args={"path": "demo.txt", "content": "a"}),
        _row("edit_file", operation_id="op.edit_file", args={"path": "demo.txt", "old": "a", "new": "b"}),
    ]

    batch = build_tool_batch_plan(
        turn_id="turn:test",
        packet_ref="packet:test",
        invocation_rows=rows,
        tool_plan=plan,
        definitions_by_name=_definitions({"write_file": "op.write_file", "edit_file": "op.edit_file"}),
        workspace_root=tmp_path,
    )

    assert [group.execution_class for group in batch.groups] == ["exclusive", "exclusive"]
    assert [group.parallel for group in batch.groups] == [False, False]
    assert [item.execution_class for item in batch.items] == ["exclusive", "exclusive"]


def test_tool_batch_planner_defaults_unknown_operation_to_exclusive(tmp_path: Path) -> None:
    plan = _tool_plan({"unknown_tool": "op.unknown"})
    rows = [_row("unknown_tool", operation_id="op.unknown", args={"path": "demo.txt"})]

    batch = build_tool_batch_plan(
        turn_id="turn:test",
        packet_ref="packet:test",
        invocation_rows=rows,
        tool_plan=plan,
        definitions_by_name={},
        workspace_root=tmp_path,
    )

    assert len(batch.groups) == 1
    assert batch.groups[0].execution_class == "exclusive"
    assert batch.items[0].concurrency_descriptor.reason == "operation_not_concurrency_safe"


def test_tool_batch_planner_excludes_approval_blocked_items_from_execution_groups(tmp_path: Path) -> None:
    plan = _tool_plan({"write_file": "op.write_file"})
    rows = [
        _row(
            "write_file",
            operation_id="op.write_file",
            args={"path": "demo.txt", "content": "a"},
            admission_decision="ask_approval",
        )
    ]

    batch = build_tool_batch_plan(
        turn_id="turn:test",
        packet_ref="packet:test",
        invocation_rows=rows,
        tool_plan=plan,
        definitions_by_name=_definitions({"write_file": "op.write_file"}),
        workspace_root=tmp_path,
    )

    assert batch.groups == ()
    assert batch.items[0].execution_class == "approval_blocked"
    assert batch.diagnostics["approval_blocked_count"] == 1


def test_tool_batch_planner_keeps_read_write_same_path_behind_exclusive_barrier(tmp_path: Path) -> None:
    plan = _tool_plan({"read_file": "op.read_file", "write_file": "op.write_file", "path_exists": "op.path_exists"})
    rows = [
        _row("read_file", operation_id="op.read_file", args={"path": "demo.txt"}),
        _row("write_file", operation_id="op.write_file", args={"path": "demo.txt", "content": "updated"}),
        _row("path_exists", operation_id="op.path_exists", args={"path": "demo.txt"}),
    ]

    batch = build_tool_batch_plan(
        turn_id="turn:test",
        packet_ref="packet:test",
        invocation_rows=rows,
        tool_plan=plan,
        definitions_by_name=_definitions({"read_file": "op.read_file", "write_file": "op.write_file", "path_exists": "op.path_exists"}),
        workspace_root=tmp_path,
    )

    assert [group.execution_class for group in batch.groups] == ["parallel_read", "exclusive", "parallel_read"]
    assert [group.item_indexes for group in batch.groups] == [(0,), (1,), (2,)]
    assert all(group.parallel is False for group in batch.groups)


def _tool_plan(tools: dict[str, str]):
    return build_runtime_tool_plan(
        runtime_assembly=SimpleNamespace(
            to_dict=lambda: {
                "session_id": "session:test",
                "turn_id": "turn:test",
                "agent_invocation_id": "aginvoke:test",
                "available_tools": [
                    {"name": name, "tool_name": name, "operation_id": operation_id}
                    for name, operation_id in tools.items()
                ],
                "task_environment": {"environment_id": "env.general.workspace"},
                "operation_authorization": {},
            }
        ),
        invocation_kind="single_agent_turn",
        tool_definitions_by_name=_definitions(tools),
    )


def _definitions(tools: dict[str, str]) -> dict[str, object]:
    return {
        name: SimpleNamespace(operation_id=operation_id, is_read_only=operation_id in {"op.read_file", "op.path_exists"})
        for name, operation_id in tools.items()
    }


def _row(
    tool_name: str,
    *,
    operation_id: str,
    args: dict[str, object],
    admission_decision: str = "allow",
) -> dict[str, object]:
    action = ModelActionRequest(
        request_id=f"action:{tool_name}:{operation_id}",
        turn_id="turn:test",
        action_type="tool_call",
        tool_call={"tool_name": tool_name, "name": tool_name, "id": f"call-{tool_name}", "args": dict(args)},
    )
    admission = AdmissionDecision(
        admission_id=f"admission:{tool_name}:{operation_id}",
        action_request_ref=action.request_id,
        decision=admission_decision,  # type: ignore[arg-type]
        permission_delta={
            "tool_name": tool_name,
            "operation_id": operation_id,
            "read_only": operation_id in {"op.read_file", "op.path_exists"},
        },
    )
    permit = action_permit_from_admission(
        action,
        admission,
        invocation_kind="agent_turn",
        packet_allowed_action_types=("respond", "ask_user", "block", "tool_call"),
        allowed_tool_names={tool_name},
        permission_mode="default",
        side_effect_policy="runtime_authorized",
    )
    return {
        "action_request": action,
        "tool_call": {"id": f"call-{tool_name}", "name": tool_name, "tool_name": tool_name, "args": dict(args)},
        "admission": admission,
        "action_permit": permit.to_dict(),
        "observation": None,
    }
