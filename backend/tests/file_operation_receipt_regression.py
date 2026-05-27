from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from file_management import FileManagementMetadataStore, ManagedFileRef
from file_management.receipts import FileOperationReceipt, dulwich_blob_id


def test_managed_file_ref_rejects_path_traversal_and_absolute_paths() -> None:
    with pytest.raises(ValueError, match="repository-relative"):
        ManagedFileRef.create(
            repository_id="repo.writing.draft_workspace",
            repository_kind="draft_workspace",
            logical_path="/chapter.md",
        )

    with pytest.raises(ValueError, match="traversal"):
        ManagedFileRef.create(
            repository_id="repo.writing.draft_workspace",
            repository_kind="draft_workspace",
            logical_path="../chapter.md",
        )


def test_managed_file_ref_is_content_addressed() -> None:
    ref = ManagedFileRef.create(
        repository_id="repo.writing.draft_workspace",
        repository_kind="draft_workspace",
        logical_path="volume_001/chapter_001.md",
        content="chapter body",
    )

    assert ref.file_ref.startswith("managed-file:")
    assert ref.content_hash
    assert ref.logical_path == "volume_001/chapter_001.md"


def test_file_operation_receipt_contains_identity_and_dulwich_version_id() -> None:
    ref = ManagedFileRef.create(
        repository_id="repo.writing.draft_workspace",
        repository_kind="draft_workspace",
        logical_path="volume_001/chapter_001.md",
        content="after body",
    )
    receipt = FileOperationReceipt.create(
        operation_id="op.write_file",
        tool_call_id="toolcall:one",
        task_run_id="taskrun:one",
        agent_run_id="agentrun:one",
        file_ref=ref,
        access_decision="allow",
        before_content="before body",
        after_content="after body",
        approval_fingerprint="approval:abc",
    )

    identity = receipt.identity_payload()
    assert identity["task_run_id"] == "taskrun:one"
    assert identity["agent_run_id"] == "agentrun:one"
    assert identity["tool_call_id"] == "toolcall:one"
    assert identity["operation_id"] == "op.write_file"
    assert identity["repository_id"] == "repo.writing.draft_workspace"
    assert identity["logical_path"] == "volume_001/chapter_001.md"
    assert identity["access_decision"] == "allow"
    assert identity["approval_fingerprint"] == "approval:abc"
    assert identity["before_hash"] != identity["after_hash"]
    assert identity["version_id"] == dulwich_blob_id("after body")


def test_file_operation_receipt_can_be_persisted_in_metadata_store(tmp_path: Path) -> None:
    ref = ManagedFileRef.create(
        repository_id="repo.coding.sandbox_workspace",
        repository_kind="sandbox_workspace",
        logical_path="src/app.py",
        content="print('ok')",
    )
    receipt = FileOperationReceipt.create(
        operation_id="op.write_file",
        tool_call_id="toolcall:persist",
        task_run_id="taskrun:persist",
        agent_run_id="agentrun:persist",
        file_ref=ref,
        access_decision="allow",
        after_content="print('ok')",
    )
    store = FileManagementMetadataStore(tmp_path / "file_management.sqlite")
    store.record_operation_receipt(receipt)

    rows = store.list_operation_receipts()
    assert rows[0]["receipt_id"] == receipt.receipt_id
    assert rows[0]["repository_id"] == "repo.coding.sandbox_workspace"
    assert rows[0]["logical_path"] == "src/app.py"
    assert "toolcall:persist" in rows[0]["access_decision"]


