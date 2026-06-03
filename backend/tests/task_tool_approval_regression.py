from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from harness.loop.task_tool_approval import (
    append_task_tool_approval_grant,
    approval_state_for_task_run,
    build_task_tool_approval_grant,
    consume_matching_task_tool_approval,
    grant_matches_pending,
    matching_approval_grant_for_pending,
    tool_args_hash,
)
from runtime.shared.models import TaskRun


def test_task_tool_approval_grant_requires_bound_directive_and_risk_fingerprint() -> None:
    task_run = TaskRun(
        task_run_id="taskrun:approval",
        session_id="session:approval",
        task_id="task:approval",
        execution_runtime_kind="single_agent_task",
        status="waiting_approval",
    )

    grant = build_task_tool_approval_grant(
        task_run=task_run,
        pending_approval={
            "task_run_id": task_run.task_run_id,
            "action_request_ref": "action:write",
            "operation_id": "op.write_file",
        },
        requested_by="user",
    )

    assert grant is None


def test_task_tool_approval_grant_is_consumed_only_for_matching_risk() -> None:
    pending = {
        "status": "pending",
        "task_run_id": "taskrun:approval",
        "action_request_ref": "action:write",
        "tool_call_id": "call:write",
        "tool_name": "write_file",
        "operation_id": "op.write_file",
        "directive_ref": "runtime-directive:taskrun:approval:tool:action:write",
        "approval_risk_fingerprint": "risk:write:path-a",
        "tool_args_hash": tool_args_hash({"path": "docs/a.md", "content": "approved"}),
    }
    task_run = TaskRun(
        task_run_id="taskrun:approval",
        session_id="session:approval",
        task_id="task:approval",
        execution_runtime_kind="single_agent_task",
        status="waiting_approval",
        diagnostics={"pending_approval": pending},
    )
    grant = build_task_tool_approval_grant(
        task_run=task_run,
        pending_approval=pending,
        requested_by="user",
    )
    assert grant is not None
    assert grant_matches_pending(grant, pending)

    task_with_grant = TaskRun(
        task_run_id=task_run.task_run_id,
        session_id=task_run.session_id,
        task_id=task_run.task_id,
        execution_runtime_kind=task_run.execution_runtime_kind,
        status=task_run.status,
        diagnostics={**append_task_tool_approval_grant(task_run, grant), "pending_approval": pending},
    )

    assert matching_approval_grant_for_pending(task_with_grant) is not None
    assert approval_state_for_task_run(task_with_grant).find_granted_token(
        operation_id="op.write_file",
        directive_ref=pending["directive_ref"],
        risk_fingerprint="risk:write:path-a",
    ) is not None
    assert approval_state_for_task_run(task_with_grant).find_granted_token(
        operation_id="op.write_file",
        directive_ref=pending["directive_ref"],
        risk_fingerprint="risk:write:path-b",
    ) is None

    consumed = consume_matching_task_tool_approval(
        task_with_grant,
        operation_id="op.write_file",
        directive_ref=pending["directive_ref"],
        approval_risk_fingerprint="risk:write:path-a",
    )

    assert consumed["approval_state"]["status"] == "consumed"
    assert consumed["approval_state"]["grants"][0]["consumed"] is True
