from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from runtime.tooling import ToolCapabilityBuildRequest, build_tool_capability_table
from task_system.environments import resolve_task_environment
from task_system.registry.flow_models import SpecificTaskRecord, TaskExecutionPolicy
from task_system.tasks import resolve_specific_task_assembly_policy


def test_coding_tool_table_intersects_environment_task_agent_and_file_access() -> None:
    resolved = resolve_task_environment("env.coding.vibe_workspace")
    table = build_tool_capability_table(
        ToolCapabilityBuildRequest(
            environment=resolved.spec,
            file_access_tables=resolved.file_access_tables,
            task_required_operations=("op.read_file", "op.search_text", "op.edit_file", "op.shell"),
            agent_profile_allowed_operations=("op.model_response", "op.read_file", "op.search_text", "op.edit_file"),
        )
    )

    assert "read_file" in table.dispatchable_tools
    assert "search_text" in table.dispatchable_tools
    assert "edit_file" in table.dispatchable_tools
    assert "terminal" not in table.visible_tools
    assert any(issue.operation_id == "op.shell" and issue.source == "agent_profile" for issue in table.filtered)
    edit_capability = table.capability_for_operation("op.edit_file")
    assert edit_capability is not None
    assert any(grant.startswith("repo.managed_project.sandbox_workspace:edit") for grant in edit_capability.file_repository_grants)


def test_development_tool_table_keeps_base_workspace_read_only() -> None:
    resolved = resolve_task_environment("env.development.sandbox")
    table = build_tool_capability_table(
        ToolCapabilityBuildRequest(
            environment=resolved.spec,
            file_access_tables=resolved.file_access_tables,
            task_required_operations=("op.read_file", "op.search_text", "op.edit_file"),
            agent_profile_allowed_operations=("op.model_response", "op.read_file", "op.search_text", "op.edit_file"),
        )
    )

    assert "read_file" in table.dispatchable_tools
    assert "search_text" in table.dispatchable_tools
    assert "edit_file" not in table.dispatchable_tools
    assert any(issue.operation_id == "op.edit_file" and issue.source == "file_access_table" for issue in table.filtered)


def test_writing_tool_table_keeps_agent_allowed_shell_visible_and_gates_official_write() -> None:
    resolved = resolve_task_environment("env.creation.writing")
    table = build_tool_capability_table(
        ToolCapabilityBuildRequest(
            environment=resolved.spec,
            file_access_tables=resolved.file_access_tables,
            task_required_operations=("op.read_file", "op.write_file", "op.shell"),
            agent_profile_allowed_operations=("op.model_response", "op.read_file", "op.write_file", "op.shell"),
        )
    )

    assert "terminal" in table.visible_tools
    assert not any(issue.operation_id == "op.shell" and issue.source == "task_environment" for issue in table.filtered)

    write_capability = table.capability_for_operation("op.write_file")
    assert write_capability is not None
    assert "write_file" in table.dispatchable_tools
    assert write_capability.requires_approval is True
    assert any(grant.startswith("repo.writing.draft_workspace:write") for grant in write_capability.file_repository_grants)
    assert any(grant.startswith("repo.writing.official_work:write") for grant in write_capability.file_repository_grants)


def test_file_operation_without_file_access_table_is_filtered() -> None:
    resolved = resolve_task_environment("env.development.sandbox")
    table = build_tool_capability_table(
        ToolCapabilityBuildRequest(
            environment=resolved.spec,
            file_access_tables=(),
            task_required_operations=("op.read_file",),
            agent_profile_allowed_operations=("op.read_file",),
        )
    )

    assert "read_file" not in table.dispatchable_tools
    assert any(issue.operation_id == "op.read_file" and issue.source == "file_access_table" for issue in table.filtered)


def test_tool_table_consumes_specific_task_assembly_policy() -> None:
    resolved = resolve_task_environment("env.coding.vibe_workspace")
    assembly_policy = resolve_specific_task_assembly_policy(
        task_record=SpecificTaskRecord(
            task_id="task.frontend.fix",
            task_title="Frontend Fix",
            metadata={"environment_id": "env.coding.vibe_workspace"},
            task_policy={
                "tool_capability_requirements": {
                    "required_operations": ["op.read_file", "op.edit_file"],
                    "optional_operations": ["op.shell"],
                    "denied_operations": ["op.browser_control"],
                }
            },
        ),
        execution_policy=TaskExecutionPolicy(
            policy_id="taskexecpol:frontend.fix",
            task_id="task.frontend.fix",
            execution_mode="single_agent",
            default_agent_id="agent:0",
        ),
    )

    table = build_tool_capability_table(
        ToolCapabilityBuildRequest.from_assembly_policy(
            environment=resolved.spec,
            assembly_policy=assembly_policy,
            file_access_tables=resolved.file_access_tables,
            agent_profile_allowed_operations=("op.read_file", "op.edit_file", "op.shell", "op.browser_control"),
        )
    )

    assert table.table_id == f"tool-capability:{assembly_policy.policy_id}"
    assert "read_file" in table.dispatchable_tools
    assert "edit_file" in table.dispatchable_tools
    assert "terminal" in table.dispatchable_tools
    assert "browser_control" not in table.dispatchable_tools
    assert any(issue.operation_id == "op.browser_control" and issue.source == "specific_task" for issue in table.filtered)
    assert any(trace.source == "specific_task_assembly_policy" and trace.detail == assembly_policy.policy_id for trace in table.source_trace)


