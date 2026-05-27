from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from file_management import (
    FileGateway,
    FileGatewayApprovalRequired,
    FileGatewayRequestContext,
    build_file_access_table,
    resolve_file_environment,
    stable_content_hash,
)


def test_file_gateway_reads_project_workspace_through_access_table(tmp_path: Path) -> None:
    project = tmp_path / "project"
    sandbox = tmp_path / "sandbox" / "workspace"
    (project / "docs").mkdir(parents=True)
    (project / "docs" / "note.md").write_text("real content", encoding="utf-8")

    gateway = _coding_gateway(project=project, sandbox=sandbox, managed=tmp_path / "managed")
    result = gateway.read_text("repo.coding.project_workspace", "docs/note.md", _context())

    assert result.content == "real content"
    assert result.repository_id == "repo.coding.project_workspace"
    assert result.access_decision == "allow"
    assert result.managed_file_ref.content_hash == stable_content_hash("real content")
    assert result.receipt is None


def test_file_gateway_blocks_project_workspace_write_without_approval(tmp_path: Path) -> None:
    project = tmp_path / "project"
    sandbox = tmp_path / "sandbox" / "workspace"
    gateway = _coding_gateway(project=project, sandbox=sandbox, managed=tmp_path / "managed")

    with pytest.raises(FileGatewayApprovalRequired) as exc:
        gateway.write_text(
            "repo.coding.project_workspace",
            "docs/new.md",
            "should not land",
            _context(),
        )

    assert exc.value.repository_id == "repo.coding.project_workspace"
    assert exc.value.action == "write"
    assert not (project / "docs" / "new.md").exists()


def test_file_gateway_project_workspace_write_requires_approval_fingerprint(tmp_path: Path) -> None:
    project = tmp_path / "project"
    sandbox = tmp_path / "sandbox" / "workspace"
    gateway = _coding_gateway(project=project, sandbox=sandbox, managed=tmp_path / "managed")

    result = gateway.write_text(
        "repo.coding.project_workspace",
        "docs/approved.md",
        "approved content",
        _context(tool_call_id="call-approved"),
        approval_fingerprint="approval:human-review",
    )

    assert (project / "docs" / "approved.md").read_text(encoding="utf-8") == "approved content"
    assert result.access_decision == "ask:approved"
    assert result.receipt is not None
    assert result.receipt.approval_fingerprint == "approval:human-review"


def test_file_gateway_sandbox_write_does_not_touch_real_workspace(tmp_path: Path) -> None:
    project = tmp_path / "project"
    sandbox = tmp_path / "sandbox" / "workspace"
    (project / "docs").mkdir(parents=True)
    (project / "docs" / "note.md").write_text("real content", encoding="utf-8")
    gateway = _coding_gateway(project=project, sandbox=sandbox, managed=tmp_path / "managed")

    result = gateway.write_text(
        "repo.coding.sandbox_workspace",
        "docs/note.md",
        "sandbox content",
        _context(tool_call_id="call-sandbox-write"),
    )

    assert (project / "docs" / "note.md").read_text(encoding="utf-8") == "real content"
    assert (sandbox / "docs" / "note.md").read_text(encoding="utf-8") == "sandbox content"
    assert result.access_decision == "allow"
    assert result.receipt is not None
    assert result.receipt.repository_id == "repo.coding.sandbox_workspace"
    assert result.receipt.logical_path == "docs/note.md"
    assert result.receipt.before_hash == ""
    assert result.receipt.after_hash == stable_content_hash("sandbox content")


def test_file_gateway_sandbox_read_copies_project_file_into_overlay(tmp_path: Path) -> None:
    project = tmp_path / "project"
    sandbox = tmp_path / "sandbox" / "workspace"
    (project / "docs").mkdir(parents=True)
    (project / "docs" / "source.md").write_text("copy me", encoding="utf-8")
    gateway = _coding_gateway(project=project, sandbox=sandbox, managed=tmp_path / "managed")

    result = gateway.read_text("repo.coding.sandbox_workspace", "docs/source.md", _context())

    assert result.content == "copy me"
    assert (sandbox / "docs" / "source.md").read_text(encoding="utf-8") == "copy me"
    assert (project / "docs" / "source.md").read_text(encoding="utf-8") == "copy me"


def test_file_gateway_rejects_path_traversal_before_touching_disk(tmp_path: Path) -> None:
    project = tmp_path / "project"
    sandbox = tmp_path / "sandbox" / "workspace"
    gateway = _coding_gateway(project=project, sandbox=sandbox, managed=tmp_path / "managed")

    with pytest.raises(ValueError, match="traversal"):
        gateway.read_text("repo.coding.project_workspace", "../secret.txt", _context())


def test_file_gateway_edit_receipt_records_before_and_after_hashes(tmp_path: Path) -> None:
    project = tmp_path / "project"
    sandbox = tmp_path / "sandbox" / "workspace"
    (project / "src").mkdir(parents=True)
    (project / "src" / "app.py").write_text("print('old')", encoding="utf-8")
    gateway = _coding_gateway(project=project, sandbox=sandbox, managed=tmp_path / "managed")

    result = gateway.edit_text(
        "repo.coding.sandbox_workspace",
        "src/app.py",
        "old",
        "new",
        _context(tool_call_id="call-edit"),
    )

    assert (project / "src" / "app.py").read_text(encoding="utf-8") == "print('old')"
    assert (sandbox / "src" / "app.py").read_text(encoding="utf-8") == "print('new')"
    assert result.receipt is not None
    assert result.receipt.before_hash == stable_content_hash("print('old')")
    assert result.receipt.after_hash == stable_content_hash("print('new')")
    assert result.receipt.tool_call_id == "call-edit"


def _coding_gateway(*, project: Path, sandbox: Path, managed: Path) -> FileGateway:
    environment = resolve_file_environment("file_profile.vibe_coding_project")
    return FileGateway.for_roots(
        environment=environment,
        access_table=build_file_access_table(environment),
        project_root=project,
        sandbox_root=sandbox,
        managed_storage_root=managed,
    )


def _context(tool_call_id: str = "call-file") -> FileGatewayRequestContext:
    return FileGatewayRequestContext(
        task_run_id="taskrun:file-gateway",
        agent_run_id="agentrun:file-gateway",
        tool_call_id=tool_call_id,
        actor_id="agent:file-gateway",
    )


