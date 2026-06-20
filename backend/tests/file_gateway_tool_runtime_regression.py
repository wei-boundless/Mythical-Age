from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from capability_system.tools.native_tool_runtime import ToolRuntime
from orchestration.runtime_directive import RuntimeDirective
from runtime.shared.file_observation_policy import READ_FILE_DEFAULT_LINE_COUNT
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
    artifact_refs = [dict(item) for item in list(envelope.get("artifact_refs") or [])]

    assert result["error"] == ""
    assert (project / "docs" / "note.md").read_text(encoding="utf-8") == "real"
    assert (sandbox / "docs" / "note.md").read_text(encoding="utf-8") == "sandbox"
    assert gateway_payload["access_decision"] == "allow"
    assert artifact_refs[0]["absolute_path"] == str((sandbox / "docs" / "note.md").resolve())
    assert artifact_refs[0]["sandbox_path"] == "docs/note.md"
    assert artifact_refs[0].get("bypass_sandbox_publish") is not True
    assert receipt["repository_id"] == "repo.managed_project.sandbox_workspace"
    assert receipt["operation_id"] == "op.write_file"
    assert receipt["tool_call_id"] == "call-write_file"


def test_runtime_edit_file_uses_file_gateway_copy_on_read_before_edit(tmp_path: Path) -> None:
    project = tmp_path / "project"
    sandbox = tmp_path / "sandbox" / "workspace"
    (project / "src").mkdir(parents=True)
    (project / "src" / "app.py").write_text("print('old')", encoding="utf-8")
    task_run_id = "taskrun-gateway-edit-after-read"

    read = _run_tool(
        workspace=project,
        sandbox_root=sandbox,
        tool_name="read_file",
        tool_args={"path": "src/app.py"},
        operation_id="op.read_file",
        task_run_id=task_run_id,
    )
    assert read["error"] == ""

    result = _run_tool(
        workspace=project,
        sandbox_root=sandbox,
        tool_name="edit_file",
        tool_args={"path": "src/app.py", "old_text": "old", "new_text": "new"},
        operation_id="op.edit_file",
        task_run_id=task_run_id,
    )

    envelope = result["observation"].payload["result_envelope"]
    receipt = envelope["structured_payload"]["file_gateway"]["receipt"]

    assert result["error"] == ""
    assert (project / "src" / "app.py").read_text(encoding="utf-8") == "print('old')"
    assert (sandbox / "src" / "app.py").read_text(encoding="utf-8") == "print('new')"
    assert receipt["before_hash"]
    assert receipt["after_hash"]
    assert receipt["before_hash"] != receipt["after_hash"]


def test_runtime_batch_edit_file_uses_file_gateway_copy_on_read_before_edit(tmp_path: Path) -> None:
    project = tmp_path / "project"
    sandbox = tmp_path / "sandbox" / "workspace"
    (project / "src").mkdir(parents=True)
    (project / "src" / "app.py").write_text("alpha old\nbeta old\ngamma", encoding="utf-8")
    task_run_id = "taskrun-gateway-batch-edit-after-read"

    read = _run_tool(
        workspace=project,
        sandbox_root=sandbox,
        tool_name="read_file",
        tool_args={"path": "src/app.py", "start_line": 1, "line_count": 3},
        operation_id="op.read_file",
        task_run_id=task_run_id,
    )
    assert read["error"] == ""
    tool_result = read["observation"].payload["result_envelope"]["structured_payload"]["tool_result"]

    result = _run_tool(
        workspace=project,
        sandbox_root=sandbox,
        tool_name="batch_edit_file",
        tool_args={
            "path": "src/app.py",
            "base_sha256": tool_result["content_sha256"],
            "base_mtime_ns": tool_result["mtime_ns"],
            "edits": [
                {"old_text": "alpha old", "new_text": "alpha new"},
                {"old_text": "beta old", "new_text": "beta new"},
            ],
        },
        operation_id="op.edit_file",
        task_run_id=task_run_id,
    )

    envelope = result["observation"].payload["result_envelope"]
    receipt = envelope["structured_payload"]["file_gateway"]["receipt"]
    artifact_refs = [dict(item) for item in list(envelope.get("artifact_refs") or [])]

    assert result["error"] == ""
    assert (project / "src" / "app.py").read_text(encoding="utf-8") == "alpha old\nbeta old\ngamma"
    assert (sandbox / "src" / "app.py").read_text(encoding="utf-8") == "alpha new\nbeta new\ngamma"
    assert envelope["structured_payload"]["tool_result"]["kind"] == "file_batch_edit"
    assert envelope["structured_payload"]["tool_result"]["edit_count"] == 2
    assert artifact_refs[0]["sandbox_path"] == "src/app.py"
    assert receipt["before_hash"]
    assert receipt["after_hash"]
    assert receipt["before_hash"] != receipt["after_hash"]


def test_runtime_batch_edit_file_gateway_applies_safe_items_and_reports_rejections(tmp_path: Path) -> None:
    project = tmp_path / "project"
    sandbox = tmp_path / "sandbox" / "workspace"
    (project / "src").mkdir(parents=True)
    (project / "src" / "app.py").write_text("alpha old\nrepeat\nrepeat\nomega old", encoding="utf-8")
    task_run_id = "taskrun-gateway-batch-edit-partial"

    read = _run_tool(
        workspace=project,
        sandbox_root=sandbox,
        tool_name="read_file",
        tool_args={"path": "src/app.py", "start_line": 1, "line_count": 4},
        operation_id="op.read_file",
        task_run_id=task_run_id,
    )
    assert read["error"] == ""
    tool_result = read["observation"].payload["result_envelope"]["structured_payload"]["tool_result"]

    result = _run_tool(
        workspace=project,
        sandbox_root=sandbox,
        tool_name="batch_edit_file",
        tool_args={
            "path": "src/app.py",
            "base_sha256": tool_result["content_sha256"],
            "base_mtime_ns": tool_result["mtime_ns"],
            "edits": [
                {"old_text": "alpha old", "new_text": "alpha new"},
                {"old_text": "missing old", "new_text": "missing new"},
                {"old_text": "repeat", "new_text": "single"},
                {"old_text": "omega old", "new_text": "omega new"},
            ],
        },
        operation_id="op.edit_file",
        task_run_id=task_run_id,
    )

    envelope = result["observation"].payload["result_envelope"]
    batch_result = dict(envelope["structured_payload"]["tool_result"])
    rejected_by_index = {item["edit_index"]: item["code"] for item in batch_result["rejected_edits"]}

    assert result["error"] == ""
    assert envelope["status"] == "ok"
    assert (project / "src" / "app.py").read_text(encoding="utf-8") == "alpha old\nrepeat\nrepeat\nomega old"
    assert (sandbox / "src" / "app.py").read_text(encoding="utf-8") == "alpha new\nrepeat\nrepeat\nomega new"
    assert batch_result["requested_edit_count"] == 4
    assert batch_result["applied_count"] == 2
    assert batch_result["rejected_count"] == 2
    assert batch_result["partial_failure"] is True
    assert rejected_by_index == {
        1: "batch_edit_old_text_not_found",
        2: "batch_edit_old_text_not_unique",
    }
    assert "structured_error" not in envelope["structured_payload"]


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
    assert result["observation"].payload["result"] == "1 | copy through gateway"
    assert (sandbox / "docs" / "source.md").read_text(encoding="utf-8") == "copy through gateway"
    assert tool_result["repository_id"] == "repo.managed_project.sandbox_workspace"
    assert envelope["structured_payload"]["file_gateway"]["access_decision"] == "allow"


def test_runtime_read_file_gateway_respects_line_window(tmp_path: Path) -> None:
    project = tmp_path / "project"
    sandbox = tmp_path / "sandbox" / "workspace"
    (project / "docs").mkdir(parents=True)
    (project / "docs" / "source.md").write_text("line1\nline2\nline3\nline4", encoding="utf-8")

    result = _run_tool(
        workspace=project,
        sandbox_root=sandbox,
        tool_name="read_file",
        tool_args={"path": "docs/source.md", "start_line": 2, "line_count": 2},
        operation_id="op.read_file",
    )

    envelope = result["observation"].payload["result_envelope"]
    tool_result = envelope["structured_payload"]["tool_result"]

    assert result["error"] == ""
    assert result["observation"].payload["result"] == "2 | line2\n3 | line3"
    assert tool_result["start_line"] == 2
    assert tool_result["end_line"] == 3
    assert tool_result["next_start_line"] == 4
    assert tool_result["line_count"] == 2
    assert tool_result["returned_lines"] == 2
    assert tool_result["total_lines"] == 4
    assert tool_result["has_more"] is True


def test_runtime_read_file_default_window_comes_from_shared_policy_for_large_files(tmp_path: Path) -> None:
    project = tmp_path / "project"
    sandbox = tmp_path / "sandbox" / "workspace"
    (project / "docs").mkdir(parents=True)
    total_lines = READ_FILE_DEFAULT_LINE_COUNT + 301
    (project / "docs" / "large.md").write_text("\n".join(f"line{i}" for i in range(1, total_lines + 1)), encoding="utf-8")

    result = _run_tool(
        workspace=project,
        sandbox_root=sandbox,
        tool_name="read_file",
        tool_args={"path": "docs/large.md"},
        operation_id="op.read_file",
    )

    envelope = result["observation"].payload["result_envelope"]
    tool_result = envelope["structured_payload"]["tool_result"]

    assert result["error"] == ""
    assert tool_result["line_count"] == READ_FILE_DEFAULT_LINE_COUNT
    assert tool_result["returned_lines"] == READ_FILE_DEFAULT_LINE_COUNT
    assert tool_result["end_line"] == READ_FILE_DEFAULT_LINE_COUNT
    assert tool_result["next_start_line"] == READ_FILE_DEFAULT_LINE_COUNT + 1
    assert tool_result["has_more"] is True


def test_runtime_read_file_reads_small_files_in_one_default_window(tmp_path: Path) -> None:
    project = tmp_path / "project"
    sandbox = tmp_path / "sandbox" / "workspace"
    (project / "docs").mkdir(parents=True)
    (project / "docs" / "small.md").write_text("\n".join(f"line{i}" for i in range(1, 4)), encoding="utf-8")

    result = _run_tool(
        workspace=project,
        sandbox_root=sandbox,
        tool_name="read_file",
        tool_args={"path": "docs/small.md"},
        operation_id="op.read_file",
    )

    tool_result = result["observation"].payload["result_envelope"]["structured_payload"]["tool_result"]

    assert result["error"] == ""
    assert result["observation"].payload["result"] == "1 | line1\n2 | line2\n3 | line3"
    assert tool_result["line_count"] == 3
    assert tool_result["returned_lines"] == 3
    assert tool_result["end_line"] == 3
    assert tool_result["has_more"] is False


def test_runtime_full_access_reads_project_workspace_after_project_edit(tmp_path: Path) -> None:
    project = tmp_path / "project"
    sandbox = tmp_path / "sandbox" / "workspace"
    (project / "src").mkdir(parents=True)
    (project / "src" / "app.js").write_text("const label = 'old';", encoding="utf-8")

    first_read = _run_tool(
        workspace=project,
        sandbox_root=sandbox,
        tool_name="read_file",
        tool_args={"path": "src/app.js"},
        operation_id="op.read_file",
        permission_mode="full_access",
        task_run_id="taskrun-gateway-full-access-edit",
    )
    assert first_read["error"] == ""

    edit = _run_tool(
        workspace=project,
        sandbox_root=sandbox,
        tool_name="edit_file",
        tool_args={"path": "src/app.js", "old_text": "old", "new_text": "new"},
        operation_id="op.edit_file",
        permission_mode="full_access",
        task_run_id="taskrun-gateway-full-access-edit",
    )
    assert edit["error"] == ""
    assert (project / "src" / "app.js").read_text(encoding="utf-8") == "const label = 'new';"

    second_read = _run_tool(
        workspace=project,
        sandbox_root=sandbox,
        tool_name="read_file",
        tool_args={"path": "src/app.js"},
        operation_id="op.read_file",
        permission_mode="full_access",
    )

    envelope = second_read["observation"].payload["result_envelope"]
    tool_result = envelope["structured_payload"]["tool_result"]
    assert second_read["error"] == ""
    assert second_read["observation"].payload["result"] == "1 | const label = 'new';"
    assert tool_result["repository_id"] == "repo.managed_project.project_workspace"


def test_runtime_project_workspace_write_is_rejected_without_file_approval(tmp_path: Path) -> None:
    project = tmp_path / "project"
    sandbox = tmp_path / "sandbox" / "workspace"

    result = _run_tool(
        workspace=project,
        sandbox_root=sandbox,
        tool_name="write_file",
        tool_args={"path": "docs/direct.md", "content": "blocked"},
        operation_id="op.write_file",
        file_repositories={"write": "repo.managed_project.project_workspace"},
    )

    observation = result["observation"]
    assert result["execution_record"].status == "failed"
    assert observation.payload["structured_payload"]["reason"] == "file_gateway_approval_required"
    assert not (project / "docs" / "direct.md").exists()
    assert not (sandbox / "docs" / "direct.md").exists()


def test_runtime_managed_project_artifact_write_is_allowed_without_sandbox(tmp_path: Path) -> None:
    project = tmp_path / "project"
    sandbox = tmp_path / "sandbox" / "workspace"

    result = _run_tool(
        workspace=project,
        sandbox_root=sandbox,
        tool_name="write_file",
        tool_args={"path": "reports/summary.md", "content": "managed artifact"},
        operation_id="op.write_file",
        sandbox_enabled=False,
        default_file_repositories=False,
    )

    envelope = result["observation"].payload["result_envelope"]
    gateway_payload = envelope["structured_payload"]["file_gateway"]
    receipt = gateway_payload["receipt"]
    artifact_refs = [dict(item) for item in list(envelope.get("artifact_refs") or [])]
    artifact_path = project / ".managed-files" / "artifacts" / "managed-project" / "artifacts" / "reports" / "summary.md"

    assert result["error"] == ""
    assert result["execution_record"].status == "completed"
    assert gateway_payload["access_decision"] == "allow"
    assert receipt["repository_id"] == "repo.managed_project.artifacts"
    assert artifact_path.read_text(encoding="utf-8") == "managed artifact"
    assert not (project / "reports" / "summary.md").exists()
    assert not (sandbox / "reports" / "summary.md").exists()
    assert artifact_refs[0]["repository_id"] == "repo.managed_project.artifacts"
    assert artifact_refs[0]["repository_kind"] == "artifact_repository"
    assert artifact_refs[0]["bypass_sandbox_publish"] is True
    assert artifact_refs[0]["absolute_path"] == str(artifact_path.resolve())


def test_runtime_managed_project_artifact_write_requires_explicit_overwrite(tmp_path: Path) -> None:
    project = tmp_path / "project"
    sandbox = tmp_path / "sandbox" / "workspace"
    artifact_path = project / ".managed-files" / "artifacts" / "managed-project" / "artifacts" / "reports" / "summary.md"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text("existing artifact", encoding="utf-8")

    blocked = _run_tool(
        workspace=project,
        sandbox_root=sandbox,
        tool_name="write_file",
        tool_args={"path": "reports/summary.md", "content": "replacement"},
        operation_id="op.write_file",
        sandbox_enabled=False,
        default_file_repositories=False,
    )

    assert blocked["execution_record"].status == "failed"
    assert blocked["recoverable_error"] == "existing_file_overwrite_requires_explicit_intent"
    assert artifact_path.read_text(encoding="utf-8") == "existing artifact"

    overwritten = _run_tool(
        workspace=project,
        sandbox_root=sandbox,
        tool_name="write_file",
        tool_args={"path": "reports/summary.md", "content": "replacement", "allow_overwrite": True},
        operation_id="op.write_file",
        sandbox_enabled=False,
        default_file_repositories=False,
    )

    assert overwritten["execution_record"].status == "completed"
    assert artifact_path.read_text(encoding="utf-8") == "replacement"


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
    file_profile_id: str = "file_profile.managed_project_workspace",
    file_repositories: dict[str, str] | None = None,
    default_file_repositories: bool = True,
    permission_mode: str = "",
    task_run_id: str | None = None,
) -> dict:
    workspace.mkdir(parents=True, exist_ok=True)
    sandbox_root.mkdir(parents=True, exist_ok=True)
    task_run_id = task_run_id or f"taskrun-gateway-{tool_name}"
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
    default_repositories = {
        "read": "repo.managed_project.sandbox_workspace",
        "write": "repo.managed_project.sandbox_workspace",
        "edit": "repo.managed_project.sandbox_workspace",
    } if default_file_repositories else {}
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
                **({"permission_mode": permission_mode} if permission_mode else {}),
            },
            file_management_policy={
                "enabled": True,
                "profile_id": file_profile_id,
                "repositories": {
                    **default_repositories,
                    **dict(file_repositories or {}),
                },
                "managed_storage_root": str(workspace / ".managed-files"),
            },
        )
    )
