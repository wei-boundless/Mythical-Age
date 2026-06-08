from __future__ import annotations

import json
from pathlib import Path

from prompt_library import (
    DEFAULT_PERSONALITY_PROMPT_REF,
    FOUNDATION_PROMPT_REFS,
    GENERAL_LIFECYCLE_PROMPT_IDS,
    PromptLibraryRegistry,
    PromptResource,
)


def test_prompt_library_lists_only_runtime_agent_and_environment_resources_by_default(tmp_path: Path) -> None:
    registry = PromptLibraryRegistry(tmp_path)

    resources = registry.list_resources()
    resource_by_id = {item.resource_id: item for item in resources}
    pack_by_id = {item.pack_id: item for item in registry.list_packs()}
    migrated_legacy_refs = {
        "runtime.single_agent_turn.v1",
        "runtime.task_execution.v1",
        "runtime.graph_node_execution.v1",
        "runtime.observation_followup.v1",
        "runtime.semantic_compaction.v1",
        "runtime.rule.system_call_protocol.v1",
        "runtime.rule.intent_feedback.v1",
        "runtime.rule.tool_use.v1",
        "runtime.rule.output_boundary.v1",
        "runtime.rule.error_recovery.v1",
        "runtime.rule.context_memory.v1",
        "runtime.rule.permission_denial.v1",
        "runtime.rule.subagent_delegation.v1",
        "runtime.rule.subagent_invocation_protocol.v1",
        "runtime.rule.multi_tool_scheduling.v1",
        "runtime.rule.plan_mode_boundary.v1",
        "graph.rule.node_boundary.v1",
        "graph.rule.node_output_contract.v1",
        "runtime.rule.file_management.generic.v1",
        "coding.rule.codebase_inspection.v1",
        "coding.rule.large_scope_exploration.v1",
        "coding.rule.editing.v1",
        "coding.rule.verification.v1",
        "coding.rule.debug_discipline.v1",
        "coding.rule.git_safety.v1",
        "coding.rule.windows_shell.v1",
        "coding.rule.task_progress.v1",
        "environment.rule.coding_workspace.v1",
        "environment.rule.development_sandbox.v1",
        "environment.rule.writing_workspace.v1",
        "environment.rule.general_workspace.v1",
        "environment.resource.base_workspace.orientation.v1",
        "environment.resource.managed_project_workspace.orientation.v1",
        "environment.resource.sandbox_overlay.orientation.v1",
        "environment.resource.writing_manuscript.orientation.v1",
        "environment.resource.general_workspace.orientation.v1",
        "environment.coding.vibe_workspace.orientation.v1",
        "environment.development.sandbox.orientation.v1",
        "environment.creation.writing.orientation.v1",
        "environment.general.workspace.orientation.v1",
    }
    migrated_legacy_packs = {
        "runtime.pack.single_agent_turn.v1",
        "runtime.pack.task_execution.v1",
        "runtime.pack.graph_node_execution.v1",
        "runtime.pack.observation_followup.v1",
        "runtime.pack.semantic_compaction.v1",
    }
    assert migrated_legacy_refs.isdisjoint(resource_by_id)
    assert migrated_legacy_packs.isdisjoint(pack_by_id)

    for prompt_ref in FOUNDATION_PROMPT_REFS:
        resource = resource_by_id[prompt_ref]
        assert resource.category == "system"
        assert resource.owner_layer == "system"
        assert resource.cache_scope == "static"
        assert not resource.prompt_id.endswith(".v1")
        assert "Mythical Age" not in resource.content
        assert "洪荒智能" not in resource.content
        assert resource.allowed_invocation_kinds == (
            "single_agent_turn",
            "task_execution",
            "tool_observation_followup",
        )
        assert resource.source_ref.startswith("prompt_library.system_prompts")
        assert "AGENTS.md" not in resource.content
        assert "{cwd}" not in resource.content
        assert "工具列表" not in resource.content
        assert "当前日期" not in resource.content

    assert resource_by_id["runtime.single_agent_turn"].category == "runtime"
    assert resource_by_id["runtime.task_execution"].category == "runtime"
    assert resource_by_id["runtime.rule.system_call_protocol"].category == "runtime"
    assert resource_by_id["runtime.rule.intent_feedback"].category == "runtime"
    assert resource_by_id["runtime.rule.tool_use"].category == "runtime"
    assert resource_by_id["runtime.rule.subagent_invocation_protocol"].category == "runtime"
    assert resource_by_id["runtime.rule.file_management.generic"].resource_type == "environment.file_management_rule"
    assert resource_by_id["coding.rule.large_scope_exploration"].resource_type == "environment.coding_rule"
    assert resource_by_id["coding.rule.large_scope_exploration"].cache_scope == "static_environment"
    assert resource_by_id["agent.main_interactive_agent.single_agent_turn.work_role"].allowed_invocation_kinds == ("single_agent_turn",)
    assert resource_by_id["agent.main_interactive_agent.task_execution.work_role"].allowed_invocation_kinds == ("task_execution",)
    assert resource_by_id["agent.main_interactive_agent.task_execution.work_role"].source_ref.startswith("prompt_library.agent_prompts")
    assert resource_by_id["agent.main_interactive_agent.task_execution.work_role"].cache_scope == "session_stable"
    assert resource_by_id[DEFAULT_PERSONALITY_PROMPT_REF].category == "personality"
    assert resource_by_id[DEFAULT_PERSONALITY_PROMPT_REF].owner_layer == "personality"
    assert resource_by_id[DEFAULT_PERSONALITY_PROMPT_REF].resource_type == "agent_personality"
    assert resource_by_id[DEFAULT_PERSONALITY_PROMPT_REF].cache_scope == "session_stable"
    assert resource_by_id[DEFAULT_PERSONALITY_PROMPT_REF].metadata["authority_scope"] == "identity_and_style_only"
    assert "不改变系统规则" in resource_by_id[DEFAULT_PERSONALITY_PROMPT_REF].content
    assert resource_by_id["environment.general.workspace.orientation"].category == "environment"
    assert resource_by_id["environment.resource.general_workspace.orientation"].category == "environment"
    assert resource_by_id["environment.resource.general_workspace.orientation"].allowed_environment_refs == ()
    for prompt_id in GENERAL_LIFECYCLE_PROMPT_IDS:
        resource = resource_by_id[prompt_id]
        assert resource.category == "environment"
        assert resource.owner_layer == "environment"
        assert resource.resource_type == "environment_prompt"
        assert resource.subtype.startswith("lifecycle_")
        assert resource.allowed_invocation_kinds == ("environment",)
        assert resource.allowed_environment_refs == ("env.general.workspace",)
        assert resource.cache_scope == "static_environment"
        assert resource.version == "2026-06-08"
        assert not resource.prompt_id.endswith(".v1")
    active_work_prompt = resource_by_id["environment.general.lifecycle.active_work_control"]
    assert "confidence" not in active_work_prompt.content.lower()
    assert "active_work_control action" in active_work_prompt.content
    assert resource_by_id["environment.general.lifecycle.memory_read_context"].resource_type == "environment_prompt"
    assert resource_by_id["environment.general.lifecycle.memory_write_handoff"].resource_type == "environment_prompt"
    assert resource_by_id["environment.general.lifecycle.verification_gate"].resource_type == "environment_prompt"
    assert not [item for item in resources if "metadata.work_role_prompt" in item.source_ref]
    assert not [item for item in resources if item.resource_id.startswith("prompt.default.")]
    assert not [item for item in resources if item.resource_type in {"task_goal_role", "stage_role", "understanding_policy"}]
    assert not (tmp_path / "storage" / "prompt_library" / "prompt_resources.json").exists()

    rules = registry.list_prompt_rules()
    rule_by_id = {item.rule_id: item for item in rules}
    assert rule_by_id["system.foundation.local_collaboration"].rule_kind == "system.foundation.local_collaboration"
    assert rule_by_id["system.foundation.local_collaboration"].cache_tier == "global_static"
    assert rule_by_id["system.foundation.current_request_authority"].rule_kind == "system.foundation.current_request_authority"
    assert rule_by_id["system.foundation.truth_and_verification"].rule_kind == "system.foundation.truth_and_verification"
    assert rule_by_id["runtime.task_execution"].rule_kind == "runtime.protocol"
    assert rule_by_id["runtime.task_execution"].requires == (
        "runtime.rule.system_call_protocol",
        "runtime.rule.intent_feedback",
    )
    assert rule_by_id["runtime.graph_node_execution"].requires == ("runtime.rule.system_call_protocol",)
    assert rule_by_id["runtime.rule.system_call_protocol"].rule_kind == "runtime.system_call_protocol"
    assert rule_by_id["runtime.rule.intent_feedback"].rule_kind == "runtime.intent_feedback"
    assert rule_by_id["runtime.rule.tool_use"].rule_kind == "runtime.tool_use"
    assert rule_by_id["runtime.rule.subagent_invocation_protocol"].rule_kind == "runtime.subagent_invocation_protocol"
    assert rule_by_id["coding.rule.large_scope_exploration"].rule_kind == "coding.large_scope_exploration"
    assert rule_by_id["coding.rule.large_scope_exploration"].cache_tier == "static_environment"
    assert rule_by_id["agent.main_interactive_agent.task_execution.work_role"].cache_tier == "session_stable"
    assert rule_by_id[DEFAULT_PERSONALITY_PROMPT_REF].rule_kind == "personality.identity_style"
    assert rule_by_id[DEFAULT_PERSONALITY_PROMPT_REF].cache_tier == "session_stable"
    assert rule_by_id[DEFAULT_PERSONALITY_PROMPT_REF].owner_layer == "personality"
    assert rule_by_id["coding.rule.editing"].requires == ("runtime.rule.file_management.generic",)


def test_graph_node_runtime_protocol_includes_respond_action_json_shape(tmp_path: Path) -> None:
    registry = PromptLibraryRegistry(tmp_path)

    resource = registry.get_resource("runtime.graph_node_execution")

    assert resource is not None
    assert "JSON 顶层必须包含 authority、action_type、public_progress_note、public_action_state 和 final_answer" in resource.content
    assert 'authority 固定为 "harness.loop.model_action_request"' in resource.content
    assert 'action_type 通常使用 "respond"' in resource.content
    assert "交付内容必须全部放入 final_answer" in resource.content
    assert "不要把正文、汇总稿、审核报告、记忆提交包或说明文字写在 JSON 外" in resource.content


def test_prompt_library_upsert_does_not_persist_all_default_resources(tmp_path: Path) -> None:
    registry = PromptLibraryRegistry(tmp_path)
    registry.upsert_resource(
        PromptResource(
            resource_id="prompt.user.custom.output",
            resource_type="output_boundary",
            title="用户自定义输出边界",
            content="你需要用用户指定的格式收口。",
            source_ref="test",
        )
    )

    storage_path = tmp_path / "storage" / "prompt_library" / "prompt_resources.json"
    payload = json.loads(storage_path.read_text(encoding="utf-8"))
    stored_ids = {str(item.get("resource_id") or "") for item in list(payload.get("resources") or [])}

    assert "prompt.user.custom.output" in stored_ids
    assert "system.foundation.local_collaboration" not in stored_ids
    assert "runtime.single_agent_turn" not in stored_ids
    assert len(stored_ids) == 1
    assert registry.get_resource("runtime.single_agent_turn") is not None


def test_prompt_library_stored_resource_overrides_default_resource(tmp_path: Path) -> None:
    registry = PromptLibraryRegistry(tmp_path)
    registry.upsert_resource(
        PromptResource(
            prompt_id="runtime.single_agent_turn",
            resource_id="runtime.single_agent_turn",
            category="runtime",
            subtype="single_agent_turn",
            resource_type="runtime.single_agent_turn",
            title="覆盖后的 single agent turn",
            content="这是用户覆盖后的 single agent turn prompt。",
            allowed_invocation_kinds=("single_agent_turn",),
            source_ref="test.override",
            priority=1,
        )
    )

    resource = registry.get_resource("runtime.single_agent_turn")

    assert resource is not None
    assert resource.title == "覆盖后的 single agent turn"
    assert resource.content == "这是用户覆盖后的 single agent turn prompt。"
    assert resource.source_ref == "test.override"


def test_task_graph_node_role_prompt_writes_graph_node_role_resource(tmp_path: Path) -> None:
    registry = PromptLibraryRegistry(tmp_path)

    resource = registry.upsert_task_graph_node_role_prompt(
        graph_id="graph.demo",
        graph_title="Demo graph",
        domain_id="domain.demo",
        node={
            "node_id": "review",
            "task_id": "task.demo.review",
            "workflow_id": "workflow.demo.node.review",
            "title": "Review",
        },
        prompt="你是一名审核员，只负责裁决是否通过。",
    )

    payload = resource.to_dict()

    assert resource.category == "graph_node"
    assert resource.subtype == "role"
    assert resource.resource_type == "graph_node.role"
    assert resource.source_ref == "task_graph:graph.demo#nodes.review.role_prompt"
    assert resource.metadata["managed_by"] == "prompt_library.task_graph_role_prompt"
    assert resource.allowed_invocation_kinds == ()
    assert "applies_to_task_goal_types" not in payload
    assert "applies_to_domains" not in payload
    assert "applies_to_modes" not in payload
    assert "stage_role" not in resource.resource_id


