from __future__ import annotations

from task_system.environments import default_task_environment_registry


def test_coding_environment_capabilities_do_not_leak_to_general_or_office() -> None:
    registry = default_task_environment_registry()
    coding = registry.require("env.coding.vibe_workspace").spec
    office = registry.require("env.office.file_search").spec
    general = registry.require("env.general.workspace").spec

    coding_ops = set(coding.sandbox_policy.side_effect_operations)

    assert {"op.shell", "op.python_repl", "op.git_commit", "op.browser_control"}.issubset(coding_ops)
    assert office.sandbox_policy.side_effect_operations == ()
    assert general.sandbox_policy.side_effect_operations == ()
    assert office.resource_space.managed_file_environment_policy == "file_profile.base_workspace"
    assert general.resource_space.managed_file_environment_policy == "file_profile.general_workspace"


def test_office_environment_is_not_vibe_coding_workspace() -> None:
    registry = default_task_environment_registry()
    coding = registry.require("env.coding.vibe_workspace").spec
    office = registry.require("env.office.file_search").spec

    coding_prompt_ids = {item.prompt_id for item in coding.environment_prompts}
    office_prompt_ids = {item.prompt_id for item in office.environment_prompts}

    assert office.file_management.file_profile_refs == ("file_profile.base_workspace",)
    assert office.resource_space.project_file_policy == "file_profile.base_workspace"
    assert office.metadata.get("dedicated_task_environment") is None
    assert office.metadata.get("managed_project_workspace_profile") is None
    assert "environment.rule.coding_workspace" in coding_prompt_ids
    assert "environment.rule.office_file_search" not in coding_prompt_ids
    assert "environment.rule.office_file_search" in office_prompt_ids
    assert "environment.rule.coding_workspace" not in office_prompt_ids
