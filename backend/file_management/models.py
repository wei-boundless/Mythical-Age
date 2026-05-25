from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath
from typing import Any, Literal


RepositoryKind = Literal[
    "project_workspace",
    "sandbox_workspace",
    "official_work",
    "draft_workspace",
    "review_workspace",
    "artifact_repository",
    "memory_repository",
    "material_mount",
    "download_cache",
    "evidence_archive",
    "citation_snapshot_repository",
    "git_worktree_view",
    "runtime_output",
    "test_artifacts",
    "asset_repository",
]

StorageAdapter = Literal[
    "fsspec_local",
    "dulwich_git",
    "artifact_repository",
    "formal_memory",
    "working_memory",
    "sandbox_overlay",
    "git_worktree",
]

FileAction = Literal[
    "open",
    "read",
    "search",
    "write",
    "edit",
    "commit",
    "publish",
    "rollback",
    "archive",
]

AccessBehavior = Literal["allow", "deny", "ask"]


@dataclass(frozen=True, slots=True)
class VersioningPolicy:
    enabled: bool = False
    backend: str = "none"
    content_addressed: bool = False
    require_content_hash: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CommitPolicy:
    required_for_canonical_write: bool = False
    requires_review_receipt: bool = False
    requires_approval: bool = False
    allowed_commit_sources: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_commit_sources"] = list(self.allowed_commit_sources)
        return payload


@dataclass(frozen=True, slots=True)
class FileAccessRule:
    action: str
    behavior: AccessBehavior = "allow"
    reason: str = ""
    requires_review_receipt: bool = False
    requires_commit_gate: bool = False
    source: str = "file_management.profile"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ManagedFileRepositorySpec:
    repository_id: str
    repository_kind: RepositoryKind
    storage_adapter: StorageAdapter = "fsspec_local"
    scope_kind: str = "run_scoped"
    root_ref: str = ""
    title: str = ""
    readable: bool = False
    writable: bool = False
    searchable: bool = False
    versioned: bool = False
    canonical: bool = False
    commit_required: bool = False
    rollback_supported: bool = False
    access_rules: tuple[FileAccessRule, ...] = ()
    versioning_policy: VersioningPolicy = field(default_factory=VersioningPolicy)
    commit_policy: CommitPolicy = field(default_factory=CommitPolicy)
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "file_management.repository_spec"

    def __post_init__(self) -> None:
        if not str(self.repository_id or "").strip():
            raise ValueError("ManagedFileRepositorySpec requires repository_id")
        if not str(self.repository_kind or "").strip():
            raise ValueError("ManagedFileRepositorySpec requires repository_kind")

    def rules_for_action(self, action: str) -> tuple[FileAccessRule, ...]:
        normalized = str(action or "").strip()
        return tuple(rule for rule in self.access_rules if rule.action == normalized or rule.action == "*")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["access_rules"] = [rule.to_dict() for rule in self.access_rules]
        payload["versioning_policy"] = self.versioning_policy.to_dict()
        payload["commit_policy"] = self.commit_policy.to_dict()
        return payload


@dataclass(frozen=True, slots=True)
class ManagedFileEnvironmentProfile:
    profile_id: str
    title: str = ""
    description: str = ""
    repository_specs: tuple[ManagedFileRepositorySpec, ...] = ()
    default_access_policy: dict[str, Any] = field(default_factory=dict)
    default_version_policy: dict[str, Any] = field(default_factory=dict)
    default_commit_policy: dict[str, Any] = field(default_factory=dict)
    default_projection_policy: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "file_management.environment_profile"

    def __post_init__(self) -> None:
        if not str(self.profile_id or "").strip():
            raise ValueError("ManagedFileEnvironmentProfile requires profile_id")
        repository_ids = [spec.repository_id for spec in self.repository_specs]
        if len(repository_ids) != len(set(repository_ids)):
            raise ValueError(f"duplicate repository_id in {self.profile_id}")

    def repository(self, repository_id: str) -> ManagedFileRepositorySpec | None:
        target = str(repository_id or "").strip()
        return next((spec for spec in self.repository_specs if spec.repository_id == target), None)

    def repositories_by_kind(self, repository_kind: str) -> tuple[ManagedFileRepositorySpec, ...]:
        target = str(repository_kind or "").strip()
        return tuple(spec for spec in self.repository_specs if spec.repository_kind == target)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["repository_specs"] = [spec.to_dict() for spec in self.repository_specs]
        return payload


@dataclass(frozen=True, slots=True)
class ManagedFileRef:
    file_ref: str
    repository_id: str
    repository_kind: str
    logical_path: str
    scope_kind: str = "run_scoped"
    scope_id: str = ""
    version_id: str = ""
    content_hash: str = ""
    status: str = "active"
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "file_management.managed_file_ref"

    @classmethod
    def create(
        cls,
        *,
        repository_id: str,
        repository_kind: str,
        logical_path: str,
        scope_kind: str = "run_scoped",
        scope_id: str = "",
        version_id: str = "",
        content: bytes | str | None = None,
        status: str = "active",
        metadata: dict[str, Any] | None = None,
    ) -> "ManagedFileRef":
        normalized_path = normalize_logical_path(logical_path)
        repo_id = str(repository_id or "").strip()
        kind = str(repository_kind or "").strip()
        if not repo_id:
            raise ValueError("ManagedFileRef requires repository_id")
        if not kind:
            raise ValueError("ManagedFileRef requires repository_kind")
        content_hash = stable_content_hash(content) if content is not None else ""
        identity = stable_content_hash("|".join((repo_id, kind, str(scope_kind or ""), str(scope_id or ""), normalized_path, version_id, content_hash)))
        return cls(
            file_ref=f"managed-file:{identity[:24]}",
            repository_id=repo_id,
            repository_kind=kind,
            logical_path=normalized_path,
            scope_kind=str(scope_kind or "run_scoped"),
            scope_id=str(scope_id or ""),
            version_id=str(version_id or ""),
            content_hash=content_hash,
            status=str(status or "active"),
            metadata=dict(metadata or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_logical_path(value: str) -> str:
    raw = str(value or "").replace("\\", "/").strip()
    if not raw:
        raise ValueError("logical_path is required")
    if "://" in raw or raw.startswith(("/", "\\")) or raw.startswith("//"):
        raise ValueError("logical_path must be a repository-relative path")
    path = PurePosixPath(raw)
    parts = path.parts
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("logical_path cannot contain traversal segments")
    return str(path)


def stable_content_hash(value: bytes | str) -> str:
    payload = value if isinstance(value, bytes) else str(value or "").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
