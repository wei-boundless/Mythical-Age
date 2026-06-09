from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from permissions.context_models import PermissionContext
from permissions.decision_models import PermissionDecision
from permissions.receipt_models import PermissionReceipt


def test_permission_decision_behaviors_are_explicit() -> None:
    allow = PermissionDecision.allow("op.read_file", reason="read grant")
    ask = PermissionDecision.ask("op.write_file", reason="canonical write", approval_fingerprint="approval:fingerprint")
    deny = PermissionDecision.deny("op.shell", reason="environment denied")
    sandbox = PermissionDecision.sandbox("op.edit_file", reason="sandbox write")
    repair = PermissionDecision.repair("op.write_file", reason="path outside grant")

    assert allow.allowed is True
    assert allow.requires_approval is False
    assert ask.allowed is False
    assert ask.requires_approval is True
    assert deny.allowed is False
    assert deny.denied is True
    assert sandbox.allowed is True
    assert repair.allowed is False
    assert repair.behavior == "repair"


def test_permission_context_carries_file_and_tool_authority_refs() -> None:
    context = PermissionContext(
        context_id="permctx:one",
        task_run_id="taskrun:one",
        agent_run_id="agentrun:one",
        environment_id="env.office.file_search",
        tool_capability_table_id="tool-capability:env.office.file_search",
        file_access_table_ids=("file-access:env.office.file_search:file_profile.base_workspace",),
        session_approval_refs=("approval:one",),
    )

    payload = context.to_dict()
    assert payload["environment_id"] == "env.office.file_search"
    assert payload["tool_capability_table_id"] == "tool-capability:env.office.file_search"
    assert payload["file_access_table_ids"] == ["file-access:env.office.file_search:file_profile.base_workspace"]
    assert payload["session_approval_refs"] == ["approval:one"]


def test_permission_receipt_identity_contains_decision_fingerprint() -> None:
    decision = PermissionDecision.ask(
        "op.write_file",
        reason="canonical write requires approval",
        approval_fingerprint="approval:write:abc",
        risk_level="high",
    )
    receipt = PermissionReceipt.from_decision(
        task_run_id="taskrun:one",
        agent_run_id="agentrun:one",
        tool_call_id="toolcall:one",
        decision=decision,
    )

    identity = receipt.identity_payload()
    assert identity["task_run_id"] == "taskrun:one"
    assert identity["agent_run_id"] == "agentrun:one"
    assert identity["tool_call_id"] == "toolcall:one"
    assert identity["operation_id"] == "op.write_file"
    assert identity["behavior"] == "ask"
    assert identity["approval_fingerprint"] == "approval:write:abc"
    assert identity["risk_level"] == "high"
    assert receipt.metadata["decision_authority"] == "permissions.permission_decision"


