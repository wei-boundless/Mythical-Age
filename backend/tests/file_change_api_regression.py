from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from api import file_changes as file_changes_api
from project_layout import ProjectLayout
from runtime.file_changes import FileChangeTracker


def test_file_changes_api_lists_records_by_session(tmp_path: Path, monkeypatch) -> None:
    runtime = SimpleNamespace(base_dir=tmp_path)
    monkeypatch.setattr(file_changes_api, "require_runtime", lambda: runtime)
    tracker = FileChangeTracker(tmp_path)
    record = _record_change(tracker, tmp_path, session_id="session-api")
    _record_change(tracker, tmp_path, session_id="session-other", logical_path="src/other.txt")

    payload = asyncio.run(
        file_changes_api.list_file_changes(
            session_id="session-api",
            task_run_id=None,
            status=None,
            limit=10,
        )
    )

    assert payload["authority"] == "api.file_changes.list"
    assert payload["summary"]["count"] == 1
    assert payload["records"][0]["record_id"] == record["record_id"]


def test_file_changes_api_returns_frontend_diff_content(tmp_path: Path, monkeypatch) -> None:
    runtime = SimpleNamespace(base_dir=tmp_path)
    monkeypatch.setattr(file_changes_api, "require_runtime", lambda: runtime)
    record = _record_change(FileChangeTracker(tmp_path), tmp_path, session_id="session-api")

    payload = asyncio.run(file_changes_api.get_file_change_diff(record["record_id"]))

    assert payload["authority"] == "api.file_changes.diff"
    assert payload["diff"]["logical_path"] == "src/app.txt"
    assert payload["diff"]["before_content"] == "before"
    assert payload["diff"]["after_content"] == "after"


def test_file_changes_api_returns_write_review_frontend_diff(tmp_path: Path, monkeypatch) -> None:
    runtime = SimpleNamespace(base_dir=tmp_path)
    monkeypatch.setattr(file_changes_api, "require_runtime", lambda: runtime)
    proposal_id = "write-review-test"
    snapshot_dir = ProjectLayout.from_backend_dir(tmp_path).storage_root / "write_reviews" / proposal_id
    snapshot_dir.mkdir(parents=True)
    (snapshot_dir / "before.txt").write_text("before proposal", encoding="utf-8")
    (snapshot_dir / "after.txt").write_text("after proposal", encoding="utf-8")
    (snapshot_dir / "metadata.json").write_text(
        json.dumps(
            {
                "proposal_id": proposal_id,
                "logical_path": "src/proposal.txt",
                "before_exists": True,
                "after_exists": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = asyncio.run(file_changes_api.get_write_review_diff(proposal_id))

    assert payload["authority"] == "api.file_changes.write_review_diff"
    assert payload["diff"]["logical_path"] == "src/proposal.txt"
    assert payload["diff"]["before_content"] == "before proposal"
    assert payload["diff"]["after_content"] == "after proposal"


def test_file_changes_api_rollback_rejects_external_target_change(tmp_path: Path, monkeypatch) -> None:
    runtime = SimpleNamespace(base_dir=tmp_path)
    monkeypatch.setattr(file_changes_api, "require_runtime", lambda: runtime)
    record = _record_change(FileChangeTracker(tmp_path), tmp_path, session_id="session-api")
    (tmp_path / "src" / "app.txt").write_text("changed after agent write", encoding="utf-8")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            file_changes_api.rollback_file_change(
                record["record_id"],
                file_changes_api.FileChangeRollbackRequest(force=False),
            )
        )

    assert exc_info.value.status_code == 409


def test_file_changes_api_rollback_restores_previous_content(tmp_path: Path, monkeypatch) -> None:
    runtime = SimpleNamespace(base_dir=tmp_path)
    monkeypatch.setattr(file_changes_api, "require_runtime", lambda: runtime)
    record = _record_change(FileChangeTracker(tmp_path), tmp_path, session_id="session-api")

    payload = asyncio.run(
        file_changes_api.rollback_file_change(
            record["record_id"],
            file_changes_api.FileChangeRollbackRequest(force=False),
        )
    )

    assert payload["rolled_back"] is True
    assert payload["record"]["status"] == "rolled_back"
    assert (tmp_path / "src" / "app.txt").read_text(encoding="utf-8") == "before"


def _record_change(
    tracker: FileChangeTracker,
    workspace_root: Path,
    *,
    session_id: str,
    logical_path: str = "src/app.txt",
) -> dict:
    target = workspace_root / logical_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("after", encoding="utf-8")
    return tracker.record_text_change(
        session_id=session_id,
        task_run_id="taskrun-api",
        agent_run_id="agentrun-api",
        tool_call_id="toolcall-api",
        tool_name="write_file",
        operation_id="op.write_file",
        workspace_root=workspace_root,
        logical_path=logical_path,
        absolute_path=target,
        before_content="before",
        after_content="after",
    )
