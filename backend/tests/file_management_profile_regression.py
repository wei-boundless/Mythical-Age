from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from file_management import (
    FileManagementMetadataStore,
    FsspecLocalFileAdapter,
    default_file_environment_registry,
    resolve_file_environment,
)


def test_writing_profile_exposes_managed_manuscript_repositories() -> None:
    registry = default_file_environment_registry()
    profile = registry.require_profile("file_profile.writing_manuscript")

    repo_ids = {repo.repository_id for repo in profile.repository_specs}
    assert {
        "repo.writing.official_work",
        "repo.writing.draft_workspace",
        "repo.writing.artifact_repository",
        "repo.writing.memory_repository",
    } <= repo_ids

    official = profile.repository("repo.writing.official_work")
    assert official is not None
    assert official.repository_kind == "official_work"
    assert official.storage_adapter == "dulwich_git"
    assert official.canonical is True
    assert official.commit_required is True
    assert official.commit_policy.requires_review_receipt is True
    assert official.commit_policy.requires_approval is True
    assert any(rule.action == "open" and rule.behavior == "allow" for rule in official.access_rules)
    assert any(rule.action == "write" and rule.behavior == "ask" for rule in official.access_rules)

    artifact = profile.repository("repo.writing.artifact_repository")
    memory = profile.repository("repo.writing.memory_repository")
    assert artifact is not None and artifact.metadata["projection_owner"] == "artifact_policy"
    assert memory is not None and memory.metadata["projection_owner"] == "memory_space"


def test_managed_project_workspace_profile_uses_project_and_sandbox_repositories() -> None:
    profile = default_file_environment_registry().require_profile("file_profile.managed_project_workspace")
    repo_ids = {repo.repository_id for repo in profile.repository_specs}

    assert {
        "repo.managed_project.project_workspace",
        "repo.managed_project.sandbox_workspace",
        "repo.managed_project.git_worktree_view",
        "repo.managed_project.test_artifacts",
    } <= repo_ids
    project = profile.repository("repo.managed_project.project_workspace")
    sandbox = profile.repository("repo.managed_project.sandbox_workspace")
    assert project is not None and project.readable is True and project.searchable is True
    assert any(rule.action == "write" and rule.behavior == "ask" for rule in project.access_rules)
    assert sandbox is not None and sandbox.writable is True
    assert any(rule.action == "write" and rule.behavior == "allow" for rule in sandbox.access_rules)


def test_resolved_environment_records_mature_backends() -> None:
    resolved = resolve_file_environment("file_profile.web_research_evidence")

    assert resolved.filesystem_backend == "fsspec.local"
    assert resolved.metadata_backend == "sqlalchemy.core"
    assert resolved.migration_backend == "alembic"
    assert resolved.version_backend == "dulwich"
    assert resolved.policy_backend == "casbin"
    assert "managed_file_repositories" in resolved.metadata["sqlalchemy_tables"]
    assert "managed_file_operation_receipts" in resolved.metadata["sqlalchemy_tables"]
    assert resolved.repository("repo.research.evidence_archive") is not None


def test_file_management_infrastructure_uses_fsspec_and_sqlalchemy(tmp_path: Path) -> None:
    adapter = FsspecLocalFileAdapter(tmp_path / "repo")
    adapter.write_text("chapters/chapter_001.md", "chapter body")
    assert adapter.exists("chapters/chapter_001.md") is True
    assert adapter.read_text("chapters/chapter_001.md") == "chapter body"

    store = FileManagementMetadataStore(tmp_path / "file_management.sqlite")
    resolved = resolve_file_environment("file_profile.writing_manuscript")
    for repo in resolved.repositories:
        store.upsert_repository(profile_id=resolved.profile_id, repository=repo)
    rows = store.list_repositories()

    assert {row["repository_id"] for row in rows} >= {
        "repo.writing.official_work",
        "repo.writing.draft_workspace",
        "repo.writing.memory_repository",
    }


