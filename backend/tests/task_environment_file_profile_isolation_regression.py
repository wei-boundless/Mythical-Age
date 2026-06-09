from __future__ import annotations

from file_management.default_profiles import default_file_environment_profiles
from task_system.environments import default_task_environment_registry


def test_managed_project_workspace_profile_exists_but_is_not_global_default() -> None:
    profile_ids = {profile.profile_id for profile in default_file_environment_profiles()}
    registry = default_task_environment_registry()
    bindings = {
        env_id: tuple(definition.spec.file_management.file_profile_refs)
        for env_id, definition in registry.definitions.items()
    }

    assert "file_profile.managed_project_workspace" in profile_ids
    assert bindings["env.coding.vibe_workspace"] == ("file_profile.managed_project_workspace",)
    assert bindings["env.office.file_search"] == ("file_profile.base_workspace",)
    assert bindings["env.general.workspace"] == ("file_profile.general_workspace",)


def test_non_coding_environments_keep_their_repository_kinds() -> None:
    registry = default_task_environment_registry()

    office = registry.require("env.office.file_search").spec.file_management
    general = registry.require("env.general.workspace").spec.file_management

    assert office.required_repository_kinds == ("project_workspace", "conversation_artifacts")
    assert general.required_repository_kinds == ("conversation_artifacts",)
    assert "git_worktree_view" not in office.required_repository_kinds
    assert "test_artifacts" not in general.required_repository_kinds
