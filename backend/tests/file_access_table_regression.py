from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from file_management import build_file_access_table, resolve_file_environment


def test_writing_access_table_allows_open_but_gates_canonical_write() -> None:
    environment = resolve_file_environment("file_profile.writing_manuscript")
    table = build_file_access_table(environment)

    assert table.is_allowed(repository_id="repo.writing.official_work", action="open") is True
    assert table.is_allowed(repository_id="repo.writing.official_work", action="read") is True
    assert table.requires_approval(repository_id="repo.writing.official_work", action="write") is True
    assert table.requires_approval(repository_id="repo.writing.official_work", action="commit") is True

    official_write = table.grants_for(repository_id="repo.writing.official_work", action="write")[0]
    assert official_write.behavior == "ask"
    assert official_write.requires_review_receipt is True
    assert official_write.requires_commit_gate is True
    assert official_write.metadata["canonical"] is True

    assert table.is_allowed(repository_id="repo.writing.draft_workspace", action="write") is True
    assert table.is_allowed(repository_id="repo.writing.artifact_repository", action="write") is True
    assert table.is_allowed(repository_id="repo.writing.memory_repository", action="write") is True


def test_managed_project_workspace_access_table_distinguishes_real_workspace_from_sandbox() -> None:
    environment = resolve_file_environment("file_profile.managed_project_workspace")
    table = build_file_access_table(environment)

    assert table.is_allowed(repository_id="repo.managed_project.project_workspace", action="read") is True
    assert table.is_allowed(repository_id="repo.managed_project.project_workspace", action="search") is True
    assert table.requires_approval(repository_id="repo.managed_project.project_workspace", action="write") is True
    assert table.is_allowed(repository_id="repo.managed_project.sandbox_workspace", action="write") is True
    assert table.requires_approval(repository_id="repo.managed_project.sandbox_workspace", action="write") is False
    assert table.is_allowed(repository_id="repo.managed_project.artifacts", action="write") is True
    assert table.requires_approval(repository_id="repo.managed_project.artifacts", action="write") is False

    git_write_denial = [
        denial
        for denial in table.denials
        if denial.repository_id == "repo.managed_project.git_worktree_view" and denial.action == "write"
    ]
    assert git_write_denial
    assert "git mutations" in git_write_denial[0].reason


def test_file_access_table_filters_by_agent_file_action_ceiling() -> None:
    environment = resolve_file_environment("file_profile.managed_project_workspace")
    table = build_file_access_table(environment, agent_allowed_actions=("read", "search"))

    assert table.is_allowed(repository_id="repo.managed_project.project_workspace", action="read") is True
    assert table.is_allowed(repository_id="repo.managed_project.sandbox_workspace", action="write") is False
    assert any(
        denial.repository_id == "repo.managed_project.sandbox_workspace"
        and denial.action == "write"
        and denial.source == "agent_profile"
        for denial in table.denials
    )


def test_file_access_table_can_be_narrowed_by_task_requirements() -> None:
    environment = resolve_file_environment(
        "file_profile.managed_project_workspace",
        repository_requirements={
            "repo.managed_project.sandbox_workspace": {"writable": False},
        },
    )
    table = build_file_access_table(environment)

    assert table.is_allowed(repository_id="repo.managed_project.sandbox_workspace", action="read") is True
    assert table.is_allowed(repository_id="repo.managed_project.sandbox_workspace", action="write") is False


