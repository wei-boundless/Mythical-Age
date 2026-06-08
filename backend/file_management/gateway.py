from __future__ import annotations

import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from .access_table import FileAccessGrant, FileAccessTable
from .filesystem_adapter import FsspecLocalFileAdapter
from .models import ManagedFileRef, ManagedFileRepositorySpec, normalize_logical_path
from .receipts import FileOperationReceipt
from .resolver import ResolvedFileEnvironment


@dataclass(frozen=True, slots=True)
class FileGatewayRequestContext:
    task_run_id: str
    agent_run_id: str
    tool_call_id: str = ""
    actor_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RepositoryRootBinding:
    repository_id: str
    repository_kind: str
    root_ref: str
    storage_adapter: str
    root: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository_id": self.repository_id,
            "repository_kind": self.repository_kind,
            "root_ref": self.root_ref,
            "storage_adapter": self.storage_adapter,
            "root": str(self.root),
        }


@dataclass(frozen=True, slots=True)
class FileGatewayResult:
    repository_id: str
    repository_kind: str
    logical_path: str
    action: str
    access_decision: str
    managed_file_ref: ManagedFileRef
    content: str = ""
    before_content: str | None = None
    physical_path: str = ""
    receipt: FileOperationReceipt | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository_id": self.repository_id,
            "repository_kind": self.repository_kind,
            "logical_path": self.logical_path,
            "action": self.action,
            "access_decision": self.access_decision,
            "managed_file_ref": self.managed_file_ref.to_dict(),
            "content": self.content,
            "before_content": self.before_content,
            "physical_path": self.physical_path,
            "receipt": self.receipt.to_dict() if self.receipt is not None else None,
            "metadata": dict(self.metadata),
        }


class FileGatewayPermissionError(PermissionError):
    def __init__(
        self,
        *,
        repository_id: str,
        action: str,
        reason: str,
        source: str = "file_gateway",
    ) -> None:
        self.repository_id = str(repository_id or "")
        self.action = str(action or "")
        self.reason = str(reason or "")
        self.source = str(source or "file_gateway")
        super().__init__(f"{self.action} denied for {self.repository_id}: {self.reason}")


class FileGatewayApprovalRequired(FileGatewayPermissionError):
    pass


class RepositoryRootResolver:
    """Resolves profile root refs into concrete platform-managed repository roots."""

    def __init__(
        self,
        *,
        project_root: str | Path,
        sandbox_root: str | Path | None = None,
        managed_storage_root: str | Path | None = None,
        runtime_output_root: str | Path | None = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.sandbox_root = Path(sandbox_root).resolve() if sandbox_root is not None else None
        self.managed_storage_root = Path(managed_storage_root).resolve() if managed_storage_root is not None else self.project_root / ".managed-files"
        self.runtime_output_root = Path(runtime_output_root).resolve() if runtime_output_root is not None else self.managed_storage_root / "runtime"

    def resolve(self, repository: ManagedFileRepositorySpec) -> RepositoryRootBinding:
        root_ref = str(repository.root_ref or "").strip()
        if root_ref in {"workspace://project", "git://worktree"}:
            root = self.project_root
        elif root_ref == "sandbox://workspace":
            root = self._require_sandbox_root(repository.repository_id)
        elif root_ref == "sandbox://materials":
            root = self._require_sandbox_root(repository.repository_id) / ".materials"
        elif root_ref == "runtime://test_artifacts":
            root = self.runtime_output_root / "test_artifacts"
        elif root_ref.startswith("writing://"):
            root = self.managed_storage_root / "writing" / _safe_root_fragment(root_ref.removeprefix("writing://"))
        elif root_ref.startswith("artifact://"):
            root = self.managed_storage_root / "artifacts" / _safe_root_fragment(root_ref.removeprefix("artifact://"))
        elif root_ref.startswith("memory://"):
            root = self.managed_storage_root / "memory" / _safe_root_fragment(root_ref.removeprefix("memory://"))
        elif root_ref.startswith("research://"):
            root = self.managed_storage_root / "research" / _safe_root_fragment(root_ref.removeprefix("research://"))
        elif not root_ref:
            root = self.managed_storage_root / "repositories" / _safe_root_fragment(repository.repository_id.replace(".", "/"))
        else:
            raise ValueError(f"unsupported repository root_ref: {root_ref}")

        return RepositoryRootBinding(
            repository_id=repository.repository_id,
            repository_kind=repository.repository_kind,
            root_ref=root_ref,
            storage_adapter=repository.storage_adapter,
            root=root.resolve(),
        )

    def _require_sandbox_root(self, repository_id: str) -> Path:
        if self.sandbox_root is None:
            raise ValueError(f"sandbox root is required for {repository_id}")
        return self.sandbox_root


class FileGateway:
    """System-owned file boundary for managed task environments."""

    def __init__(
        self,
        *,
        environment: ResolvedFileEnvironment,
        access_table: FileAccessTable,
        root_resolver: RepositoryRootResolver,
        metadata_store: Any | None = None,
    ) -> None:
        self.environment = environment
        self.access_table = access_table
        self.root_resolver = root_resolver
        self.metadata_store = metadata_store

    @classmethod
    def for_roots(
        cls,
        *,
        environment: ResolvedFileEnvironment,
        access_table: FileAccessTable,
        project_root: str | Path,
        sandbox_root: str | Path | None = None,
        managed_storage_root: str | Path | None = None,
        runtime_output_root: str | Path | None = None,
        metadata_store: Any | None = None,
    ) -> "FileGateway":
        return cls(
            environment=environment,
            access_table=access_table,
            root_resolver=RepositoryRootResolver(
                project_root=project_root,
                sandbox_root=sandbox_root,
                managed_storage_root=managed_storage_root,
                runtime_output_root=runtime_output_root,
            ),
            metadata_store=metadata_store,
        )

    def read_text(
        self,
        repository_id: str,
        logical_path: str,
        context: FileGatewayRequestContext,
        *,
        operation_id: str = "op.read_file",
    ) -> FileGatewayResult:
        repository, binding, adapter, normalized_path = self._repository_adapter(repository_id, logical_path)
        access_decision = self.check_access(repository_id, "read", approval_fingerprint="")
        if repository.storage_adapter == "sandbox_overlay":
            self._copy_from_project_if_missing(binding=binding, logical_path=normalized_path)
        content = adapter.read_text(normalized_path)
        file_ref = ManagedFileRef.create(
            repository_id=repository.repository_id,
            repository_kind=repository.repository_kind,
            logical_path=normalized_path,
            scope_kind=repository.scope_kind,
            scope_id=context.task_run_id,
            content=content,
            metadata={"operation_id": operation_id},
        )
        return self._result(
            repository=repository,
            binding=binding,
            logical_path=normalized_path,
            action="read",
            access_decision=access_decision,
            file_ref=file_ref,
            content=content,
            physical_path=str(adapter.resolve(normalized_path)),
        )

    def write_text(
        self,
        repository_id: str,
        logical_path: str,
        content: str,
        context: FileGatewayRequestContext,
        *,
        operation_id: str = "op.write_file",
        approval_fingerprint: str = "",
    ) -> FileGatewayResult:
        repository, binding, adapter, normalized_path = self._repository_adapter(repository_id, logical_path)
        access_decision = self.check_access(repository_id, "write", approval_fingerprint=approval_fingerprint)
        before_content = adapter.read_text(normalized_path) if adapter.exists(normalized_path) else None
        adapter.write_text(normalized_path, content)
        return self._write_result(
            repository=repository,
            binding=binding,
            adapter=adapter,
            logical_path=normalized_path,
            content=str(content or ""),
            before_content=before_content,
            action="write",
            operation_id=operation_id,
            access_decision=access_decision,
            approval_fingerprint=approval_fingerprint,
            context=context,
        )

    def edit_text(
        self,
        repository_id: str,
        logical_path: str,
        old_text: str,
        new_text: str,
        context: FileGatewayRequestContext,
        *,
        operation_id: str = "op.edit_file",
        approval_fingerprint: str = "",
    ) -> FileGatewayResult:
        repository, binding, adapter, normalized_path = self._repository_adapter(repository_id, logical_path)
        access_decision = self.check_access(repository_id, "edit", approval_fingerprint=approval_fingerprint)
        if repository.storage_adapter == "sandbox_overlay":
            self._copy_from_project_if_missing(binding=binding, logical_path=normalized_path)
        before_content = adapter.read_text(normalized_path)
        target = str(old_text or "")
        if not target:
            raise ValueError("old_text is required")
        if target not in before_content:
            raise LookupError("old_text not found")
        after_content = before_content.replace(target, str(new_text or ""), 1)
        adapter.write_text(normalized_path, after_content)
        return self._write_result(
            repository=repository,
            binding=binding,
            adapter=adapter,
            logical_path=normalized_path,
            content=after_content,
            before_content=before_content,
            action="edit",
            operation_id=operation_id,
            access_decision=access_decision,
            approval_fingerprint=approval_fingerprint,
            context=context,
        )

    def _repository_adapter(
        self,
        repository_id: str,
        logical_path: str,
    ) -> tuple[ManagedFileRepositorySpec, RepositoryRootBinding, FsspecLocalFileAdapter, str]:
        normalized_path = normalize_logical_path(logical_path)
        repository = self.environment.repository(repository_id)
        if repository is None:
            raise KeyError(f"unknown file repository: {repository_id}")
        binding = self.root_resolver.resolve(repository)
        return repository, binding, FsspecLocalFileAdapter(binding.root), normalized_path

    def check_access(
        self,
        repository_id: str,
        action: str,
        *,
        approval_fingerprint: str,
    ) -> str:
        repository = self.environment.repository(repository_id)
        if repository is None:
            raise KeyError(f"unknown file repository: {repository_id}")
        grants = self.access_table.grants_for(repository_id=repository.repository_id, action=action)
        if not grants:
            denial = next(
                (
                    item
                    for item in self.access_table.denials
                    if item.repository_id == repository.repository_id and item.action == action
                ),
                None,
            )
            raise FileGatewayPermissionError(
                repository_id=repository.repository_id,
                action=action,
                reason=denial.reason if denial is not None else "no file access grant",
                source=denial.source if denial is not None else "file_access_table",
            )

        grant = _strongest_grant(grants)
        if grant.behavior == "allow":
            return "allow"
        if grant.behavior == "ask":
            if not str(approval_fingerprint or "").strip():
                raise FileGatewayApprovalRequired(
                    repository_id=repository.repository_id,
                    action=action,
                    reason=grant.reason or "approval required",
                    source=grant.source,
                )
            return "ask:approved"
        raise FileGatewayPermissionError(
            repository_id=repository.repository_id,
            action=action,
            reason=grant.reason or "denied by file access grant",
            source=grant.source,
        )

    def _write_result(
        self,
        *,
        repository: ManagedFileRepositorySpec,
        binding: RepositoryRootBinding,
        adapter: FsspecLocalFileAdapter,
        logical_path: str,
        content: str,
        before_content: str | None,
        action: str,
        operation_id: str,
        access_decision: str,
        approval_fingerprint: str,
        context: FileGatewayRequestContext,
    ) -> FileGatewayResult:
        file_ref = ManagedFileRef.create(
            repository_id=repository.repository_id,
            repository_kind=repository.repository_kind,
            logical_path=logical_path,
            scope_kind=repository.scope_kind,
            scope_id=context.task_run_id,
            content=content,
            metadata={"operation_id": operation_id},
        )
        receipt = FileOperationReceipt.create(
            operation_id=operation_id,
            tool_call_id=context.tool_call_id,
            task_run_id=context.task_run_id,
            agent_run_id=context.agent_run_id,
            file_ref=file_ref,
            access_decision=access_decision,
            before_content=before_content,
            after_content=content,
            approval_fingerprint=approval_fingerprint,
            metadata={
                "actor_id": context.actor_id,
                "repository_root_ref": binding.root_ref,
                "storage_adapter": binding.storage_adapter,
                "physical_path": str(adapter.resolve(logical_path)),
                **dict(context.metadata),
            },
        )
        if self.metadata_store is not None:
            self.metadata_store.record_operation_receipt(receipt)
        return self._result(
            repository=repository,
            binding=binding,
            logical_path=logical_path,
            action=action,
            access_decision=access_decision,
            file_ref=file_ref,
            content=content,
            before_content=before_content,
            physical_path=str(adapter.resolve(logical_path)),
            receipt=receipt,
        )

    def _result(
        self,
        *,
        repository: ManagedFileRepositorySpec,
        binding: RepositoryRootBinding,
        logical_path: str,
        action: str,
        access_decision: str,
        file_ref: ManagedFileRef,
        content: str = "",
        before_content: str | None = None,
        physical_path: str = "",
        receipt: FileOperationReceipt | None = None,
    ) -> FileGatewayResult:
        return FileGatewayResult(
            repository_id=repository.repository_id,
            repository_kind=repository.repository_kind,
            logical_path=logical_path,
            action=action,
            access_decision=access_decision,
            managed_file_ref=file_ref,
            content=content,
            before_content=before_content,
            physical_path=physical_path,
            receipt=receipt,
            metadata={
                "profile_id": self.environment.profile_id,
                "root_binding": binding.to_dict(),
            },
        )

    def _copy_from_project_if_missing(self, *, binding: RepositoryRootBinding, logical_path: str) -> None:
        project_source = (self.root_resolver.project_root / logical_path).resolve()
        sandbox_target = (binding.root / logical_path).resolve()
        if not _is_inside(project_source, self.root_resolver.project_root):
            return
        if not _is_inside(sandbox_target, binding.root):
            return
        if sandbox_target.exists() or not project_source.exists() or not project_source.is_file():
            return
        sandbox_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(project_source, sandbox_target)


def _strongest_grant(grants: tuple[FileAccessGrant, ...]) -> FileAccessGrant:
    ask = next((grant for grant in grants if grant.behavior == "ask"), None)
    if ask is not None:
        return ask
    return grants[0]


def _safe_root_fragment(value: str) -> Path:
    normalized = str(value or "").replace("\\", "/").strip().strip("/")
    if not normalized:
        raise ValueError("repository root fragment is required")
    path = PurePosixPath(normalized)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("repository root fragment cannot contain traversal segments")
    return Path(*path.parts)


def _is_inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


