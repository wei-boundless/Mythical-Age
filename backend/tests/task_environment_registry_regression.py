from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from task_system.environments import default_task_environment_registry, resolve_task_environment


def test_default_task_environments_reference_file_profiles() -> None:
    registry = default_task_environment_registry()
    writing = registry.require("env.writing").spec
    coding = registry.require("env.vibe_coding").spec
    research = registry.require("env.web_research").spec

    assert writing.tool_space.shell_policy == "denied"
    assert "file_profile.writing_manuscript" in writing.file_management.file_profile_refs
    assert {
        "official_work",
        "draft_workspace",
        "artifact_repository",
        "memory_repository",
    } <= set(writing.file_management.required_repository_kinds)
    assert writing.file_management.constraints["official_work_open"] == "allowed"
    assert writing.file_management.constraints["official_work_canonical_write"] == "ask"
    assert writing.artifact_policy.artifact_root == "repo.writing.artifact_repository"
    assert writing.memory_space.projection_policy == "from_file_management"

    assert "file_profile.vibe_coding_project" in coding.file_management.file_profile_refs
    assert coding.resource_space.workspace_policy == "project_workspace"
    assert coding.execution_policy.shell_execution_policy == "ask"

    assert "file_profile.web_research_evidence" in research.file_management.file_profile_refs
    assert research.tool_space.network_policy == "allowed"
    assert research.execution_policy.network_execution_policy == "allowed"


def test_resolved_writing_environment_builds_file_access_table() -> None:
    resolved = resolve_task_environment("env.writing")

    assert resolved.spec.environment_id == "env.writing"
    assert len(resolved.file_access_tables) == 1
    table = resolved.file_access_tables[0]
    assert table.profile_id == "file_profile.writing_manuscript"
    assert table.is_allowed(repository_id="repo.writing.official_work", action="open") is True
    assert table.requires_approval(repository_id="repo.writing.official_work", action="write") is True
    assert table.is_allowed(repository_id="repo.writing.draft_workspace", action="write") is True


def test_resolved_environment_can_apply_agent_file_action_ceiling() -> None:
    resolved = resolve_task_environment("env.vibe_coding", agent_allowed_file_actions=("read", "search"))
    table = resolved.file_access_tables[0]

    assert table.is_allowed(repository_id="repo.coding.project_workspace", action="read") is True
    assert table.is_allowed(repository_id="repo.coding.sandbox_workspace", action="write") is False
    assert any(denial.source == "agent_profile" and denial.action == "write" for denial in table.denials)
