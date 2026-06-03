from __future__ import annotations

from pathlib import Path

import pytest

from agent_system.profiles.runtime_profile_registry import default_agent_runtime_profiles
from harness.runtime.compiler import RuntimeCompiler
from prompt_library import FOUNDATION_PROMPT_REFS, PromptAssemblyRequest, PromptAssemblyService, PromptRuleCompiler, PromptSection
from prompt_library.rules import rule_metadata


def test_runtime_pack_manifest_reports_prompt_rule_coverage(tmp_path: Path) -> None:
    assembly = PromptAssemblyService(tmp_path).assemble(
        PromptAssemblyRequest(invocation_kind="task_execution")
    )

    prompt_rules = assembly.manifest["prompt_rules"]
    assert assembly.manifest["stable_prompt_refs"][: len(FOUNDATION_PROMPT_REFS)] == list(FOUNDATION_PROMPT_REFS)
    assert prompt_rules["coverage"]["has_system_foundation"] is True
    assert prompt_rules["coverage"]["has_runtime_protocol"] is True
    assert prompt_rules["coverage"]["has_system_call_protocol"] is True
    assert prompt_rules["coverage"]["has_intent_feedback"] is True
    assert "runtime.task_execution.v1" in prompt_rules["rule_refs"]
    assert "runtime.rule.system_call_protocol.v1" in prompt_rules["rule_refs"]
    assert "runtime.rule.intent_feedback.v1" in prompt_rules["rule_refs"]
    assert "runtime.rule.output_boundary.v1" in prompt_rules["rule_refs"]
    assert "runtime.rule.error_recovery.v1" in prompt_rules["rule_refs"]
    assert prompt_rules["rejected_rules"] == []

    compiled = PromptRuleCompiler().compile(assembly.sections, invocation_kind="task_execution")
    assert "runtime.protocol" in compiled.rule_kinds
    assert "system.foundation.vibe_coding_agent" in compiled.rule_kinds
    assert "runtime.system_call_protocol" in compiled.rule_kinds
    assert "runtime.intent_feedback" in compiled.rule_kinds
    assert "runtime.output_boundary" in compiled.rule_kinds


def test_runtime_protocol_requires_system_call_protocol_rule(tmp_path: Path) -> None:
    assembly = PromptAssemblyService(tmp_path).assemble(
        PromptAssemblyRequest(
            invocation_kind="task_execution",
            prompt_refs=("runtime.task_execution.v1",),
        )
    )

    prompt_rules = assembly.manifest["prompt_rules"]
    assert prompt_rules["coverage"]["has_runtime_protocol"] is True
    assert prompt_rules["coverage"]["has_system_call_protocol"] is False
    assert prompt_rules["rejected_rules"][0]["reason"] == "prompt_rule_requirement_missing"
    assert prompt_rules["rejected_rules"][0]["requires"] == "runtime.rule.system_call_protocol.v1"
    with pytest.raises(ValueError, match="prompt_rule_requirement_missing"):
        PromptRuleCompiler().compile(assembly.sections, invocation_kind="task_execution")


def test_foundation_refs_precede_runtime_protocol_in_runtime_packs(tmp_path: Path) -> None:
    service = PromptAssemblyService(tmp_path)

    pack_cases = (
        ("single_agent_turn", "runtime.pack.single_agent_turn.v1", "runtime.single_agent_turn.v1"),
        ("task_execution", "runtime.pack.task_execution.v1", "runtime.task_execution.v1"),
        ("task_execution", "runtime.pack.graph_node_execution.v1", "runtime.graph_node_execution.v1"),
        ("tool_observation_followup", "runtime.pack.observation_followup.v1", "runtime.observation_followup.v1"),
    )
    for invocation_kind, pack_ref, protocol_ref in pack_cases:
        assembly = service.assemble(
            PromptAssemblyRequest(invocation_kind=invocation_kind, prompt_pack_refs=(pack_ref,))
        )
        stable_refs = assembly.manifest["stable_prompt_refs"]
        assert stable_refs[: len(FOUNDATION_PROMPT_REFS)] == list(FOUNDATION_PROMPT_REFS)
        assert stable_refs[len(FOUNDATION_PROMPT_REFS)] == protocol_ref
        assert assembly.manifest["prompt_rules"]["coverage"]["has_system_foundation"] is True
        assert assembly.manifest["prompt_rules"]["rejected_rules"] == []
        PromptRuleCompiler().compile(assembly.sections, invocation_kind=invocation_kind)


def test_foundation_is_not_in_semantic_compaction_pack(tmp_path: Path) -> None:
    assembly = PromptAssemblyService(tmp_path).assemble(
        PromptAssemblyRequest(
            invocation_kind="semantic_compaction",
            prompt_pack_refs=("runtime.pack.semantic_compaction.v1",),
        )
    )

    assert all(prompt_ref not in assembly.manifest["stable_prompt_refs"] for prompt_ref in FOUNDATION_PROMPT_REFS)
    assert "runtime.semantic_compaction.v1" in assembly.manifest["stable_prompt_refs"]


def test_non_graph_runtime_protocol_requires_intent_feedback_rule(tmp_path: Path) -> None:
    assembly = PromptAssemblyService(tmp_path).assemble(
        PromptAssemblyRequest(
            invocation_kind="task_execution",
            prompt_refs=(
                "runtime.task_execution.v1",
                "runtime.rule.system_call_protocol.v1",
            ),
        )
    )

    prompt_rules = assembly.manifest["prompt_rules"]
    assert prompt_rules["coverage"]["has_runtime_protocol"] is True
    assert prompt_rules["coverage"]["has_system_call_protocol"] is True
    assert prompt_rules["coverage"]["has_intent_feedback"] is False
    assert any(
        item["reason"] == "prompt_rule_requirement_missing"
        and item["requires"] == "runtime.rule.intent_feedback.v1"
        for item in prompt_rules["rejected_rules"]
    )
    with pytest.raises(ValueError, match="prompt_rule_requirement_missing"):
        PromptRuleCompiler().compile(assembly.sections, invocation_kind="task_execution")


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


def test_prompt_rule_compiler_rejects_cache_tier_scope_mismatch() -> None:
    section = PromptSection(
        section_id="runtime.bad_environment_rule:1",
        prompt_ref="test.rule.bad_environment_scope.v1",
        category="runtime",
        subtype="rule",
        title="Bad environment-scoped rule",
        content="你需要遵守当前环境边界。",
        owner_layer="runtime",
        cache_scope="static",
        metadata={
            "prompt_rule": rule_metadata(
                rule_id="test.rule.bad_environment_scope.v1",
                prompt_ref="test.rule.bad_environment_scope.v1",
                rule_kind="environment.boundary",
                owner_layer="environment",
                cache_tier="static_environment",
                enforcement_mode="compiler_validated",
            )
        },
    )

    with pytest.raises(ValueError, match="prompt_rule_cache_tier_scope_mismatch"):
        PromptRuleCompiler().compile((section,), invocation_kind="task_execution")


def test_prompt_rule_compiler_rejects_invocation_scope_mismatch() -> None:
    section = PromptSection(
        section_id="runtime.single_turn_only:1",
        prompt_ref="test.rule.single_turn_only.v1",
        category="runtime",
        subtype="rule",
        title="Single turn only rule",
        content="你只在单轮对话中使用这条规则。",
        owner_layer="runtime",
        cache_scope="static",
        metadata={
            "prompt_rule": rule_metadata(
                rule_id="test.rule.single_turn_only.v1",
                prompt_ref="test.rule.single_turn_only.v1",
                rule_kind="runtime.test_scope",
                owner_layer="runtime",
                allowed_invocation_kinds=("single_agent_turn",),
                cache_tier="global_static",
                enforcement_mode="compiler_validated",
            )
        },
    )

    with pytest.raises(ValueError, match="prompt_rule_invocation_scope_mismatch"):
        PromptRuleCompiler().compile((section,), invocation_kind="task_execution")


def test_prompt_rule_compiler_rejects_developer_style_prompt_text() -> None:
    section = PromptSection(
        section_id="runtime.bad_style:1",
        prompt_ref="test.rule.bad_style.v1",
        category="runtime",
        subtype="rule",
        title="Bad style rule",
        content="这是 runtime 节点。根据任务图执行 world_review。这个节点用于校验资产。",
        owner_layer="runtime",
        cache_scope="static",
        metadata={
            "prompt_rule": rule_metadata(
                rule_id="test.rule.bad_style.v1",
                prompt_ref="test.rule.bad_style.v1",
                rule_kind="runtime.bad_style",
                owner_layer="runtime",
                allowed_invocation_kinds=("task_execution",),
                cache_tier="global_static",
                enforcement_mode="compiler_validated",
            )
        },
    )

    with pytest.raises(ValueError, match="developer_style_prompt_text"):
        PromptRuleCompiler().compile((section,), invocation_kind="task_execution")


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
    assert manifest["prompt_rules"]["coverage"]["has_system_call_protocol"] is True
    assert manifest["prompt_rules"]["coverage"]["has_intent_feedback"] is True
    assert "runtime.rule.system_call_protocol.v1" in manifest["stable_prompt_refs"]
    assert "runtime.rule.intent_feedback.v1" in manifest["stable_prompt_refs"]
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
    assert prompt_rules["coverage"]["has_system_call_protocol"] is True
    assert prompt_rules["coverage"]["has_intent_feedback"] is False
    assert "runtime.graph_node_execution.v1" in prompt_rules["rule_refs"]
    assert "runtime.task_execution.v1" not in prompt_rules["rule_refs"]
    assert "runtime.rule.system_call_protocol.v1" in prompt_rules["rule_refs"]
    assert "runtime.rule.intent_feedback.v1" not in prompt_rules["rule_refs"]
    assert "runtime.rule.tool_use.v1" not in prompt_rules["rule_refs"]
    assert "graph.rule.node_boundary.v1" in prompt_rules["rule_refs"]
    assert prompt_rules["rejected_rules"] == []
