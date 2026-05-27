from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any

from dulwich.objects import Blob

from .models import ManagedFileRef, stable_content_hash


@dataclass(frozen=True, slots=True)
class FileOperationReceipt:
    receipt_id: str
    operation_id: str
    tool_call_id: str
    task_run_id: str
    agent_run_id: str
    repository_id: str
    repository_kind: str
    logical_path: str
    managed_file_ref: str
    access_decision: str
    approval_fingerprint: str = ""
    before_hash: str = ""
    after_hash: str = ""
    version_id: str = ""
    commit_id: str = ""
    rollback_ref: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "file_management.operation_receipt"

    @classmethod
    def create(
        cls,
        *,
        operation_id: str,
        tool_call_id: str,
        task_run_id: str,
        agent_run_id: str,
        file_ref: ManagedFileRef,
        access_decision: str,
        before_content: bytes | str | None = None,
        after_content: bytes | str | None = None,
        approval_fingerprint: str = "",
        commit_id: str = "",
        rollback_ref: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> "FileOperationReceipt":
        before_hash = stable_content_hash(before_content) if before_content is not None else ""
        after_hash = stable_content_hash(after_content) if after_content is not None else file_ref.content_hash
        version_id = file_ref.version_id or dulwich_blob_id(after_content if after_content is not None else file_ref.content_hash)
        receipt_id = _receipt_id(
            task_run_id,
            agent_run_id,
            tool_call_id,
            operation_id,
            file_ref.repository_id,
            file_ref.logical_path,
            access_decision,
            before_hash,
            after_hash,
            approval_fingerprint,
        )
        return cls(
            receipt_id=receipt_id,
            operation_id=str(operation_id or ""),
            tool_call_id=str(tool_call_id or ""),
            task_run_id=str(task_run_id or ""),
            agent_run_id=str(agent_run_id or ""),
            repository_id=file_ref.repository_id,
            repository_kind=file_ref.repository_kind,
            logical_path=file_ref.logical_path,
            managed_file_ref=file_ref.file_ref,
            access_decision=str(access_decision or ""),
            approval_fingerprint=str(approval_fingerprint or ""),
            before_hash=before_hash,
            after_hash=after_hash,
            version_id=version_id,
            commit_id=str(commit_id or ""),
            rollback_ref=str(rollback_ref or ""),
            metadata=dict(metadata or {}),
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "operation_id": self.operation_id,
            "tool_call_id": self.tool_call_id,
            "task_run_id": self.task_run_id,
            "agent_run_id": self.agent_run_id,
            "repository_id": self.repository_id,
            "logical_path": self.logical_path,
            "managed_file_ref": self.managed_file_ref,
            "access_decision": self.access_decision,
            "approval_fingerprint": self.approval_fingerprint,
            "before_hash": self.before_hash,
            "after_hash": self.after_hash,
            "version_id": self.version_id,
            "commit_id": self.commit_id,
            "authority": self.authority,
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FileCommitReceipt:
    commit_receipt_id: str
    task_run_id: str
    agent_run_id: str
    repository_id: str
    source_receipt_ids: tuple[str, ...] = ()
    review_receipt_id: str = ""
    commit_id: str = ""
    status: str = "candidate"
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "file_management.commit_receipt"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_receipt_ids"] = list(self.source_receipt_ids)
        return payload


def dulwich_blob_id(content: bytes | str | None) -> str:
    payload = content if isinstance(content, bytes) else str(content or "").encode("utf-8")
    blob = Blob.from_string(payload)
    return blob.id.decode("ascii")


def _receipt_id(*parts: str) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return f"filerec:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"


