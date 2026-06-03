from __future__ import annotations

from task_system.environments import default_task_environment_registry


def test_writing_environment_keeps_shell_browser_denied_after_runtime_maturity_upgrade() -> None:
    registry = default_task_environment_registry()
    writing = registry.require("env.creation.writing").spec

    assert writing.sandbox_policy.shell_policy == "denied"
    assert writing.sandbox_policy.browser_policy == "denied"
    assert writing.execution_policy.shell_execution_policy == "denied"
    assert writing.execution_policy.browser_execution_policy == "denied"
    assert writing.file_management.file_profile_refs == ("file_profile.writing_manuscript",)
    assert writing.file_management.canonical_write_policy == "review_receipt_and_commit_gate_required"


def test_general_workspace_does_not_default_to_coding_permissions() -> None:
    registry = default_task_environment_registry()
    general = registry.require("env.general.workspace").spec

    assert general.file_management.file_profile_refs == ("file_profile.general_workspace",)
    assert general.sandbox_policy.side_effect_policy == "permission_context"
    assert general.execution_policy.side_effect_policy == "permission_context"
    assert "file_profile.managed_project_workspace" not in general.file_management.file_profile_refs


def test_coding_runtime_boundary_is_explicit_environment_policy() -> None:
    registry = default_task_environment_registry()
    coding = registry.require("env.coding.vibe_workspace").spec

    assert coding.file_management.file_profile_refs == ("file_profile.managed_project_workspace",)
    assert coding.sandbox_policy.enabled is True
    assert coding.sandbox_policy.shell_policy == "sandboxed"
    assert coding.sandbox_policy.browser_policy == "sandboxed"
    assert coding.lifecycle_policy["graph_entry_policy"] == "fixed_entry_not_scheduled_by_environment"
