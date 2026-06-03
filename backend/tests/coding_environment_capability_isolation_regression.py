from __future__ import annotations

from task_system.environments import default_task_environment_registry


def test_coding_environment_capabilities_do_not_leak_to_general_or_writing() -> None:
    registry = default_task_environment_registry()
    coding = registry.require("env.coding.vibe_workspace").spec
    writing = registry.require("env.creation.writing").spec
    general = registry.require("env.general.workspace").spec

    coding_ops = set(coding.sandbox_policy.side_effect_operations)

    assert {"op.shell", "op.python_repl", "op.git_commit", "op.browser_control"}.issubset(coding_ops)
    assert writing.sandbox_policy.side_effect_operations == ()
    assert general.sandbox_policy.side_effect_operations == ()
    assert writing.resource_space.managed_file_environment_policy == "file_profile.writing_manuscript"
    assert general.resource_space.managed_file_environment_policy == "file_profile.general_workspace"


def test_development_sandbox_is_not_vibe_coding_workspace() -> None:
    registry = default_task_environment_registry()
    coding = registry.require("env.coding.vibe_workspace").spec
    development = registry.require("env.development.sandbox").spec

    coding_prompt_ids = {item.prompt_id for item in coding.environment_prompts}
    development_prompt_ids = {item.prompt_id for item in development.environment_prompts}

    assert development.file_management.file_profile_refs == ("file_profile.base_workspace",)
    assert development.resource_space.project_file_policy == "file_profile.base_workspace"
    assert development.metadata.get("dedicated_task_environment") is None
    assert development.metadata.get("managed_project_workspace_profile") is None
    assert "environment.rule.coding_workspace.v1" in coding_prompt_ids
    assert "environment.rule.development_sandbox.v1" not in coding_prompt_ids
    assert "environment.rule.development_sandbox.v1" in development_prompt_ids
    assert "environment.rule.coding_workspace.v1" not in development_prompt_ids
