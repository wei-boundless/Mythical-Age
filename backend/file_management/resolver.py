from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fsspec.implementations.local import LocalFileSystem
from sqlalchemy import Column, MetaData, String, Table

from .models import ManagedFileEnvironmentProfile, ManagedFileRepositorySpec
from .models import FileAccessRule
from .registry import FileEnvironmentRegistry, default_file_environment_registry


metadata = MetaData()

managed_file_repositories_table = Table(
    "managed_file_repositories",
    metadata,
    Column("repository_id", String, primary_key=True),
    Column("profile_id", String, nullable=False),
    Column("repository_kind", String, nullable=False),
    Column("storage_adapter", String, nullable=False),
    Column("scope_kind", String, nullable=False),
    Column("root_ref", String, nullable=False, default=""),
)

managed_file_operation_receipts_table = Table(
    "managed_file_operation_receipts",
    metadata,
    Column("receipt_id", String, primary_key=True),
    Column("task_run_id", String, nullable=False, default=""),
    Column("agent_run_id", String, nullable=False, default=""),
    Column("repository_id", String, nullable=False, default=""),
    Column("logical_path", String, nullable=False, default=""),
    Column("access_decision", String, nullable=False, default=""),
)


@dataclass(frozen=True, slots=True)
class ResolvedFileEnvironment:
    profile_id: str
    repositories: tuple[ManagedFileRepositorySpec, ...]
    filesystem_backend: str = "fsspec.local"
    metadata_backend: str = "sqlalchemy.core"
    migration_backend: str = "alembic"
    version_backend: str = "dulwich"
    policy_backend: str = "casbin"
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "file_management.resolved_environment"

    def repository(self, repository_id: str) -> ManagedFileRepositorySpec | None:
        target = str(repository_id or "").strip()
        return next((repo for repo in self.repositories if repo.repository_id == target), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "repositories": [repo.to_dict() for repo in self.repositories],
            "filesystem_backend": self.filesystem_backend,
            "metadata_backend": self.metadata_backend,
            "migration_backend": self.migration_backend,
            "version_backend": self.version_backend,
            "policy_backend": self.policy_backend,
            "metadata": dict(self.metadata),
            "authority": self.authority,
        }


def resolve_file_environment(
    profile_id: str,
    *,
    registry: FileEnvironmentRegistry | None = None,
    repository_requirements: dict[str, dict[str, Any]] | None = None,
) -> ResolvedFileEnvironment:
    active_registry = registry or default_file_environment_registry()
    profile = active_registry.require_profile(profile_id)
    requirements = dict(repository_requirements or {})
    repositories = tuple(
        _merge_repository_requirement(repo, requirements.get(repo.repository_id, {}))
        for repo in profile.repository_specs
    )
    return ResolvedFileEnvironment(
        profile_id=profile.profile_id,
        repositories=repositories,
        metadata={
            "profile_title": profile.title,
            "sqlalchemy_tables": sorted(table.name for table in metadata.sorted_tables),
            "fsspec_protocol": LocalFileSystem.protocol,
        },
    )


def _merge_repository_requirement(
    repo: ManagedFileRepositorySpec,
    requirement: dict[str, Any],
) -> ManagedFileRepositorySpec:
    if not requirement:
        return repo
    # Requirements can only narrow writable/searchable/readable defaults in this foundation slice.
    readable = repo.readable and bool(requirement.get("readable", repo.readable))
    writable = repo.writable and bool(requirement.get("writable", repo.writable))
    searchable = repo.searchable and bool(requirement.get("searchable", repo.searchable))
    narrowed_rules = tuple(_narrow_rule(rule, readable=readable, writable=writable, searchable=searchable) for rule in repo.access_rules)
    return ManagedFileRepositorySpec(
        repository_id=repo.repository_id,
        repository_kind=repo.repository_kind,
        storage_adapter=repo.storage_adapter,
        scope_kind=repo.scope_kind,
        root_ref=repo.root_ref,
        title=repo.title,
        readable=readable,
        writable=writable,
        searchable=searchable,
        versioned=repo.versioned,
        canonical=repo.canonical,
        commit_required=repo.commit_required,
        rollback_supported=repo.rollback_supported,
        access_rules=narrowed_rules,
        versioning_policy=repo.versioning_policy,
        commit_policy=repo.commit_policy,
        metadata={**repo.metadata, "requirement_narrowed": True},
    )


def _narrow_rule(
    rule: FileAccessRule,
    *,
    readable: bool,
    writable: bool,
    searchable: bool,
) -> FileAccessRule:
    if rule.action in {"open", "read"} and not readable:
        return FileAccessRule(action=rule.action, behavior="deny", reason="task file requirement removed read grant", source="specific_task.file_requirements")
    if rule.action == "search" and not searchable:
        return FileAccessRule(action=rule.action, behavior="deny", reason="task file requirement removed search grant", source="specific_task.file_requirements")
    if rule.action in {"write", "edit"} and not writable:
        return FileAccessRule(action=rule.action, behavior="deny", reason="task file requirement removed write grant", source="specific_task.file_requirements")
    return rule


