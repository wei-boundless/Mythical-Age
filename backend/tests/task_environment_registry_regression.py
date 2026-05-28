from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from task_system.environments import default_task_environment_registry, resolve_task_environment
from agent_system.profiles.runtime_profile_registry import default_agent_runtime_profiles
from capability_system.tool_authorization import build_tool_authorization_index
from capability_system.tool_definitions import build_tool_instances, get_tool_definitions
from harness.runtime import assemble_runtime


def test_default_task_environments_are_grouped_scene_platforms() -> None:
    registry = default_task_environment_registry()
    groups = {item.group_id for item in registry.list_groups()}

    assert {
        "environment_group.development",
        "environment_group.creation",
        "environment_group.research",
        "environment_group.document",
        "environment_group.general",
    } <= groups

    development = registry.require("env.development.sandbox").spec
    writing = registry.require("env.creation.writing").spec
    general = registry.require("env.general.workspace").spec

    assert development.sandbox_policy.enabled is True
    assert development.sandbox_policy.shell_policy == "sandboxed"
    assert "op.image_generate" in development.sandbox_policy.side_effect_operations
    assert development.resource_space.storage_namespace == "development/sandbox"
    assert development.environment_prompts

    assert "file_profile.writing_manuscript" in writing.file_management.file_profile_refs
    assert writing.resource_space.storage_namespace == "creation/writing"
    assert writing.file_management.constraints["official_work_canonical_write"] == "ask"
    assert writing.artifact_policy.artifact_root == "repo.writing.artifact_repository"

    assert general.runtime_policy.graph_allowed is False
    assert general.sandbox_policy.shell_policy == "denied"


def test_professional_development_runtime_exposes_shell_and_image_generation_tools() -> None:
    profile = next(item for item in default_agent_runtime_profiles() if item.agent_profile_id == "main_interactive_agent")
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)

    assembly = assemble_runtime(
        backend_dir=BACKEND_DIR,
        session_id="session-test",
        turn_id="turn-test",
        agent_invocation_id="agent-invocation-test",
        request_task_selection={"runtime_mode": "professional", "task_environment_id": "env.development.sandbox"},
        model_selection={},
        agent_runtime_profile=profile,
        tool_instances=build_tool_instances(BACKEND_DIR),
        definitions_by_name=index.definitions_by_name,
    ).to_dict()

    tool_names = {str(item.get("tool_name") or "") for item in list(assembly.get("available_tools") or [])}
    sandbox_policy = dict(dict(assembly.get("task_environment") or {}).get("sandbox_policy") or {})
    assert "terminal" in tool_names
    assert "image_generate" in tool_names
    assert "op.image_generate" in list(sandbox_policy.get("side_effect_operations") or [])


def test_legacy_environment_ids_resolve_to_new_scene_platform_ids() -> None:
    registry = default_task_environment_registry()

    assert registry.require("env.vibe_coding").record.environment_id == "env.development.sandbox"
    assert registry.require("env.writing").record.environment_id == "env.creation.writing"
    assert registry.require("env.web_research").record.environment_id == "env.research.web"
    assert registry.require("env.document_processing").record.environment_id == "env.document.processing"
    assert registry.require("env.general_workspace").record.environment_id == "env.general.workspace"


def test_resolved_environment_exports_storage_and_file_boundaries() -> None:
    resolved = resolve_task_environment("env.development.sandbox")
    payload = resolved.to_dict()

    assert resolved.group is not None
    assert resolved.group.group_id == "environment_group.development"
    assert payload["storage_space"]["storage_namespace"] == "development/sandbox"
    assert payload["storage_space"]["artifact_root"] == "storage/task_environments/development/sandbox/artifacts"
    assert payload["sandbox_policy"]["enabled"] is True
    assert len(resolved.file_access_tables) == 1
    assert resolved.file_access_tables[0].profile_id == "file_profile.vibe_coding_project"


def test_resolved_writing_environment_builds_file_access_table() -> None:
    resolved = resolve_task_environment("env.creation.writing")

    assert resolved.spec.environment_id == "env.creation.writing"
    assert len(resolved.file_access_tables) == 1
    table = resolved.file_access_tables[0]
    assert table.profile_id == "file_profile.writing_manuscript"
    assert table.is_allowed(repository_id="repo.writing.official_work", action="open") is True
    assert table.requires_approval(repository_id="repo.writing.official_work", action="write") is True
    assert table.is_allowed(repository_id="repo.writing.draft_workspace", action="write") is True


def test_resolved_environment_can_apply_agent_file_action_ceiling() -> None:
    resolved = resolve_task_environment("env.development.sandbox", agent_allowed_file_actions=("read", "search"))
    table = resolved.file_access_tables[0]

    assert table.is_allowed(repository_id="repo.coding.project_workspace", action="read") is True
    assert table.is_allowed(repository_id="repo.coding.sandbox_workspace", action="write") is False
    assert any(denial.source == "agent_profile" and denial.action == "write" for denial in table.denials)


def test_all_default_task_environments_resolve_file_access_tables() -> None:
    for environment_id in (
        "env.creation.writing",
        "env.development.sandbox",
        "env.development.readonly",
        "env.research.web",
        "env.document.processing",
        "env.general.workspace",
    ):
        resolved = resolve_task_environment(environment_id)
        assert resolved.spec.environment_id == environment_id
        assert resolved.file_access_tables
