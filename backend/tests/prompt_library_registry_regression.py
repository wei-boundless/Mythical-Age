from __future__ import annotations

import json
from pathlib import Path

from prompt_library import FOUNDATION_PROMPT_REFS, PromptLibraryRegistry, PromptResource


def test_prompt_library_lists_only_runtime_agent_and_environment_resources_by_default(tmp_path: Path) -> None:
    registry = PromptLibraryRegistry(tmp_path)

    resources = registry.list_resources()
    resource_by_id = {item.resource_id: item for item in resources}

    for prompt_ref in FOUNDATION_PROMPT_REFS:
        resource = resource_by_id[prompt_ref]
        assert resource.category == "system"
        assert resource.owner_layer == "system"
        assert resource.cache_scope == "static"
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

    assert resource_by_id["runtime.single_agent_turn.v1"].category == "runtime"
    assert resource_by_id["runtime.task_execution.v1"].category == "runtime"
    assert resource_by_id["runtime.rule.system_call_protocol.v1"].category == "runtime"
    assert resource_by_id["runtime.rule.intent_feedback.v1"].category == "runtime"
    assert resource_by_id["runtime.rule.tool_use.v1"].category == "runtime"
    assert resource_by_id["runtime.rule.file_management.generic.v1"].resource_type == "environment.file_management_rule"
    assert resource_by_id["agent.main_interactive_agent.single_agent_turn.work_role.v1"].allowed_invocation_kinds == ("single_agent_turn",)
    assert resource_by_id["agent.main_interactive_agent.task_execution.work_role.v1"].allowed_invocation_kinds == ("task_execution",)
    assert resource_by_id["agent.main_interactive_agent.task_execution.work_role.v1"].source_ref.startswith("prompt_library.agent_prompts")
    assert resource_by_id["agent.main_interactive_agent.task_execution.work_role.v1"].cache_scope == "session_stable"
    assert resource_by_id["environment.general.workspace.orientation.v1"].category == "environment"
    assert resource_by_id["environment.resource.general_workspace.orientation.v1"].category == "environment"
    assert resource_by_id["environment.resource.general_workspace.orientation.v1"].allowed_environment_refs == ()
    assert not [item for item in resources if "metadata.work_role_prompt" in item.source_ref]
    assert not [item for item in resources if item.resource_id.startswith("prompt.default.")]
    assert not [item for item in resources if item.resource_type in {"task_goal_role", "stage_role", "understanding_policy"}]
    assert not (tmp_path / "storage" / "prompt_library" / "prompt_resources.json").exists()

    rules = registry.list_prompt_rules()
    rule_by_id = {item.rule_id: item for item in rules}
    assert rule_by_id["system.foundation.vibe_coding_agent.v1"].rule_kind == "system.foundation.vibe_coding_agent"
    assert rule_by_id["system.foundation.vibe_coding_agent.v1"].cache_tier == "global_static"
    assert rule_by_id["runtime.task_execution.v1"].rule_kind == "runtime.protocol"
    assert rule_by_id["runtime.task_execution.v1"].requires == (
        "runtime.rule.system_call_protocol.v1",
        "runtime.rule.intent_feedback.v1",
    )
    assert rule_by_id["runtime.graph_node_execution.v1"].requires == ("runtime.rule.system_call_protocol.v1",)
    assert rule_by_id["runtime.rule.system_call_protocol.v1"].rule_kind == "runtime.system_call_protocol"
    assert rule_by_id["runtime.rule.intent_feedback.v1"].rule_kind == "runtime.intent_feedback"
    assert rule_by_id["runtime.rule.tool_use.v1"].rule_kind == "runtime.tool_use"
    assert rule_by_id["agent.main_interactive_agent.task_execution.work_role.v1"].cache_tier == "session_stable"
    assert rule_by_id["coding.rule.editing.v1"].requires == ("runtime.rule.file_management.generic.v1",)


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
    assert "system.foundation.vibe_coding_agent.v1" not in stored_ids
    assert "runtime.single_agent_turn.v1" not in stored_ids
    assert len(stored_ids) == 1
    assert registry.get_resource("runtime.single_agent_turn.v1") is not None


def test_prompt_library_stored_resource_overrides_default_resource(tmp_path: Path) -> None:
    registry = PromptLibraryRegistry(tmp_path)
    registry.upsert_resource(
        PromptResource(
            prompt_id="runtime.single_agent_turn.v1",
            resource_id="runtime.single_agent_turn.v1",
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

    resource = registry.get_resource("runtime.single_agent_turn.v1")

    assert resource is not None
    assert resource.title == "覆盖后的 single agent turn"
    assert resource.content == "这是用户覆盖后的 single agent turn prompt。"
    assert resource.source_ref == "test.override"


def test_task_graph_node_prompt_migration_writes_graph_node_role_resource(tmp_path: Path) -> None:
    registry = PromptLibraryRegistry(tmp_path)

    resource = registry.migrate_task_graph_node_prompt(
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
    assert resource.allowed_invocation_kinds == ()
    assert "applies_to_task_goal_types" not in payload
    assert "applies_to_domains" not in payload
    assert "applies_to_modes" not in payload
    assert "stage_role" not in resource.resource_id


