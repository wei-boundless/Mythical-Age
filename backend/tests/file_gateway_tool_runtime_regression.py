from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from capability_system.tools.native_tool_runtime import ToolRuntime
from orchestration.runtime_directive import RuntimeDirective
from runtime.shared.action_request import RuntimeActionRequest
from runtime.shared.execution_record import RuntimeExecutionStore, build_idempotency_token, build_request_fingerprint
from runtime.tool_runtime.tool_executor import ToolRuntimeExecutor


def test_runtime_write_file_uses_file_gateway_sandbox_repository(tmp_path: Path) -> None:
    project = tmp_path / "project"
    sandbox = tmp_path / "sandbox" / "workspace"
    (project / "docs").mkdir(parents=True)
    (project / "docs" / "note.md").write_text("real", encoding="utf-8")

    result = _run_tool(
        workspace=project,
        sandbox_root=sandbox,
        tool_name="write_file",
        tool_args={"path": "docs/note.md", "content": "sandbox"},
        operation_id="op.write_file",
    )

    envelope = result["observation"].payload["result_envelope"]
    gateway_payload = envelope["structured_payload"]["file_gateway"]
    receipt = gateway_payload["receipt"]

    assert result["error"] == ""
    assert (project / "docs" / "note.md").read_text(encoding="utf-8") == "real"
    assert (sandbox / "docs" / "note.md").read_text(encoding="utf-8") == "sandbox"
    assert gateway_payload["access_decision"] == "allow"
    assert receipt["repository_id"] == "repo.coding.sandbox_workspace"
    assert receipt["operation_id"] == "op.write_file"
    assert receipt["tool_call_id"] == "call-write_file"


def test_runtime_edit_file_uses_file_gateway_copy_on_read_before_edit(tmp_path: Path) -> None:
    project = tmp_path / "project"
    sandbox = tmp_path / "sandbox" / "workspace"
    (project / "src").mkdir(parents=True)
    (project / "src" / "app.py").write_text("print('old')", encoding="utf-8")

    result = _run_tool(
        workspace=project,
        sandbox_root=sandbox,
        tool_name="edit_file",
        tool_args={"path": "src/app.py", "old_text": "old", "new_text": "new"},
        operation_id="op.edit_file",
    )

    envelope = result["observation"].payload["result_envelope"]
    receipt = envelope["structured_payload"]["file_gateway"]["receipt"]

    assert result["error"] == ""
    assert (project / "src" / "app.py").read_text(encoding="utf-8") == "print('old')"
    assert (sandbox / "src" / "app.py").read_text(encoding="utf-8") == "print('new')"
    assert receipt["before_hash"]
    assert receipt["after_hash"]
    assert receipt["before_hash"] != receipt["after_hash"]


def test_runtime_read_file_uses_file_gateway_sandbox_overlay(tmp_path: Path) -> None:
    project = tmp_path / "project"
    sandbox = tmp_path / "sandbox" / "workspace"
    (project / "docs").mkdir(parents=True)
    (project / "docs" / "source.md").write_text("copy through gateway", encoding="utf-8")

    result = _run_tool(
        workspace=project,
        sandbox_root=sandbox,
        tool_name="read_file",
        tool_args={"path": "docs/source.md"},
        operation_id="op.read_file",
    )

    envelope = result["observation"].payload["result_envelope"]
    tool_result = envelope["structured_payload"]["tool_result"]

    assert result["error"] == ""
    assert result["observation"].payload["result"] == "copy through gateway"
    assert (sandbox / "docs" / "source.md").read_text(encoding="utf-8") == "copy through gateway"
    assert tool_result["repository_id"] == "repo.coding.sandbox_workspace"
    assert envelope["structured_payload"]["file_gateway"]["access_decision"] == "allow"


def test_runtime_project_workspace_write_is_rejected_without_file_approval(tmp_path: Path) -> None:
    project = tmp_path / "project"
    sandbox = tmp_path / "sandbox" / "workspace"

    result = _run_tool(
        workspace=project,
        sandbox_root=sandbox,
        tool_name="write_file",
        tool_args={"path": "docs/direct.md", "content": "blocked"},
        operation_id="op.write_file",
        file_repositories={"write": "repo.coding.project_workspace"},
    )

    observation = result["observation"]
    assert result["execution_record"].status == "failed"
    assert observation.payload["structured_payload"]["reason"] == "file_gateway_approval_required"
    assert not (project / "docs" / "direct.md").exists()
    assert not (sandbox / "docs" / "direct.md").exists()


def test_runtime_file_management_works_when_sandbox_is_disabled(tmp_path: Path) -> None:
    project = tmp_path / "project"
    sandbox = tmp_path / "sandbox" / "workspace"

    result = _run_tool(
        workspace=project,
        sandbox_root=sandbox,
        tool_name="write_file",
        tool_args={"path": "chapter-01.md", "content": "draft without sandbox"},
        operation_id="op.write_file",
        sandbox_enabled=False,
        file_profile_id="file_profile.writing_manuscript",
        file_repositories={"write": "repo.writing.draft_workspace"},
    )

    envelope = result["observation"].payload["result_envelope"]
    gateway_payload = envelope["structured_payload"]["file_gateway"]

    assert result["error"] == ""
    assert gateway_payload["receipt"]["repository_id"] == "repo.writing.draft_workspace"
    assert (project / ".managed-files" / "writing" / "drafts" / "chapter-01.md").read_text(encoding="utf-8") == "draft without sandbox"
    assert not (sandbox / "chapter-01.md").exists()


def _run_tool(
    *,
    workspace: Path,
    sandbox_root: Path,
    tool_name: str,
    tool_args: dict[str, str],
    operation_id: str,
    sandbox_enabled: bool = True,
    file_profile_id: str = "file_profile.vibe_coding_project",
    file_repositories: dict[str, str] | None = None,
) -> dict:
    workspace.mkdir(parents=True, exist_ok=True)
    sandbox_root.mkdir(parents=True, exist_ok=True)
    task_run_id = f"taskrun-gateway-{tool_name}"
    action_request = RuntimeActionRequest(
        request_id=f"rtact:{tool_name}",
        task_run_id=task_run_id,
        request_type="tool_call",
        step_id="step:1",
        directive_ref=f"runtime-directive:{tool_name}",
        operation_id=operation_id,
        payload={
            "tool_name": tool_name,
            "tool_call": {"id": f"call-{tool_name}", "name": tool_name, "args": tool_args},
        },
    )
    directive = RuntimeDirective(
        directive_id=f"runtime-directive:{tool_name}",
        task_id="task:file-gateway-tool-runtime",
        plan_ref="plan:file-gateway-tool-runtime",
        stage_ref="stage:file-gateway-tool-runtime",
        executor_type="tool",
        adopted_resource_policy_ref="respol:file-gateway-tool-runtime",
        operation_refs=(operation_id,),
    )
    execution_store = RuntimeExecutionStore(workspace / ".runtime-test")
    fingerprint = build_request_fingerprint(
        step_id="step:1",
        operation_id=operation_id,
        payload=action_request.payload,
    )
    record = execution_store.create_record(
        task_run_id=task_run_id,
        step_id="step:1",
        action_request=action_request,
        directive_ref=directive.directive_id,
        operation_id=operation_id,
        executor_type="tool",
        replay_policy="deny_auto_replay",
        request_fingerprint=fingerprint,
        idempotency_token=build_idempotency_token(
            task_run_id=task_run_id,
            step_id="step:1",
            operation_id=operation_id,
            request_fingerprint=fingerprint,
        ),
    )
    executor = ToolRuntimeExecutor(tool_runtime=ToolRuntime(workspace))
    return asyncio.run(
        executor.run(
            task_run_id=task_run_id,
            action_request=action_request,
            directive=directive,
            execution_record=record,
            execution_store=execution_store,
            sandbox_policy={
                "enabled": bool(sandbox_enabled),
                "mode": "workspace_overlay",
                "sandbox_root": str(sandbox_root),
                "workspace_root": str(workspace),
            },
            file_management_policy={
                "enabled": True,
                "profile_id": file_profile_id,
                "repositories": {
                    "read": "repo.coding.sandbox_workspace",
                    "write": "repo.coding.sandbox_workspace",
                    "edit": "repo.coding.sandbox_workspace",
                    **dict(file_repositories or {}),
                },
                "managed_storage_root": str(workspace / ".managed-files"),
            },
        )
    )


