from __future__ import annotations

from pathlib import Path

import pytest

from agent_system.profiles.runtime_profile_registry import default_agent_runtime_profiles
from harness.runtime.compiler import RuntimeCompiler
from prompt_library import PromptAssemblyRequest, PromptAssemblyService, PromptRuleCompiler


def test_runtime_pack_manifest_reports_prompt_rule_coverage(tmp_path: Path) -> None:
    assembly = PromptAssemblyService(tmp_path).assemble(
        PromptAssemblyRequest(invocation_kind="task_execution")
    )

    prompt_rules = assembly.manifest["prompt_rules"]
    assert prompt_rules["coverage"]["has_runtime_protocol"] is True
    assert "runtime.task_execution.v1" in prompt_rules["rule_refs"]
    assert "runtime.rule.output_boundary.v1" in prompt_rules["rule_refs"]
    assert "runtime.rule.error_recovery.v1" in prompt_rules["rule_refs"]
    assert prompt_rules["rejected_rules"] == []

    compiled = PromptRuleCompiler().compile(assembly.sections, invocation_kind="task_execution")
    assert "runtime.protocol" in compiled.rule_kinds
    assert "runtime.output_boundary" in compiled.rule_kinds


def test_prompt_rule_compiler_rejects_multiple_runtime_protocols(tmp_path: Path) -> None:
    assembly = PromptAssemblyService(tmp_path).assemble(
        PromptAssemblyRequest(
            invocation_kind="task_execution",
            prompt_refs=(
                "runtime.task_execution.v1",
                "runtime.graph_node_execution.v1",
            ),
        )
    )

    with pytest.raises(ValueError, match="multiple_runtime_protocol_rules"):
        PromptRuleCompiler().compile(assembly.sections, invocation_kind="task_execution")


def test_prompt_rule_compiler_rejects_missing_required_file_management_rule(tmp_path: Path) -> None:
    assembly = PromptAssemblyService(tmp_path).assemble(
        PromptAssemblyRequest(
            invocation_kind="environment",
            prompt_refs=("coding.rule.editing.v1",),
            task_environment_ref="env.coding.vibe_workspace",
        )
    )

    with pytest.raises(ValueError, match="prompt_rule_requirement_missing"):
        PromptRuleCompiler().compile(assembly.sections, invocation_kind="environment")


def test_main_profile_uses_prompt_library_refs_not_embedded_work_role_prompts() -> None:
    profile = next(
        item
        for item in default_agent_runtime_profiles()
        if item.agent_profile_id == "main_interactive_agent"
    )
    metadata = dict(profile.metadata or {})

    assert metadata["agent_prompt_refs_by_invocation"] == {
        "single_agent_turn": ["agent.main_interactive_agent.single_agent_turn.work_role.v1"],
        "tool_observation_followup": ["agent.main_interactive_agent.tool_observation_followup.work_role.v1"],
        "task_execution": ["agent.main_interactive_agent.task_execution.work_role.v1"],
    }
    assert "work_role_prompt" not in metadata
    assert "agent_work_role_prompt" not in metadata
    assert "work_role_prompt_by_invocation" not in metadata
    assert "agent_work_role_prompt_by_invocation" not in metadata
    assert "work_role_prompt_refs_by_invocation" not in metadata


def test_coding_rules_do_not_leak_into_writing_environment_runtime_packet() -> None:
    packet = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:writing-rule-isolation",
        task_run={
            "task_run_id": "taskrun:writing-rule-isolation",
            "task_id": "task:writing-rule-isolation",
            "agent_profile_id": "main_interactive_agent",
        },
        contract={"task_run_goal": "审查章节草稿", "completion_criteria": ["给出审查结论"]},
        observations=[],
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "environment_prompt_refs": [
                "runtime.rule.file_management.generic.v1",
                "environment.resource.writing_manuscript.orientation.v1",
                "environment.creation.writing.orientation.v1",
                "environment.rule.writing_workspace.v1",
            ],
            "task_environment": {
                "environment_id": "env.creation.writing",
                "title": "Creative Writing",
            },
        },
    ).packet

    model_input = "\n".join(str(message["content"]) for message in packet.model_messages)
    manifest = packet.diagnostics["prompt_manifest"]
    assert "environment.rule.writing_workspace.v1" in manifest["stable_prompt_refs"]
    assert "coding.rule.editing.v1" not in manifest["stable_prompt_refs"]
    assert "coding.rule.verification.v1" not in manifest["stable_prompt_refs"]
    assert "写作环境不继承 coding 的测试、shell、git 或代码编辑规则" in model_input
    assert "你处在 coding 或 development 环境时" not in model_input


def test_graph_node_runtime_pack_has_single_graph_protocol(tmp_path: Path) -> None:
    assembly = PromptAssemblyService(tmp_path).assemble(
        PromptAssemblyRequest(
            invocation_kind="task_execution",
            prompt_pack_refs=("runtime.pack.graph_node_execution.v1",),
        )
    )

    prompt_rules = assembly.manifest["prompt_rules"]
    assert prompt_rules["coverage"]["has_runtime_protocol"] is True
    assert "runtime.graph_node_execution.v1" in prompt_rules["rule_refs"]
    assert "runtime.task_execution.v1" not in prompt_rules["rule_refs"]
    assert "graph.rule.node_boundary.v1" in prompt_rules["rule_refs"]
    assert prompt_rules["rejected_rules"] == []
