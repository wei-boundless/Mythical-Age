from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from task_system.environments import build_task_environment_catalog, default_task_environment_registry, resolve_task_environment
from agent_system.profiles.runtime_profile_registry import default_agent_runtime_profiles
from capability_system.skill_registry import SkillRegistry
from capability_system.tool_authorization import build_tool_authorization_index
from capability_system.tool_definitions import build_tool_instances, get_tool_definitions
from harness.runtime import RuntimeCompiler, assemble_runtime
from task_system.tasks.definitions import default_task_definitions


def test_default_task_environments_are_grouped_scene_platforms() -> None:
    registry = default_task_environment_registry()
    groups = {item.group_id for item in registry.list_groups()}

    assert {
        "environment_group.development",
        "environment_group.creation",
        "environment_group.general",
    } == groups

    development = registry.require("env.development.sandbox").spec
    writing = registry.require("env.creation.writing").spec
    general = registry.require("env.general.workspace").spec

    assert development.sandbox_policy.enabled is True
    assert development.sandbox_policy.shell_policy == "sandboxed"
    assert "op.image_generate" in development.sandbox_policy.side_effect_operations
    assert development.resource_space.storage_namespace == "development/sandbox"
    assert development.environment_prompts
    assert "skill.browser-operation" in development.skill_space.default_skill_refs
    assert "skill.visual-asset-generation" in development.skill_space.optional_skill_refs
    development_prompt = "\n".join(item.content for item in development.environment_prompts)
    assert "优先使用 search_text、search_files、glob_paths、read_file、list_dir" in development_prompt
    assert "sandbox overlay" in development_prompt
    assert "old_text not found" in development_prompt

    assert "file_profile.writing_manuscript" in writing.file_management.file_profile_refs
    assert "skill.image-prompt-design" in writing.skill_space.default_skill_refs
    assert writing.resource_space.storage_namespace == "creation/writing"
    assert writing.file_management.constraints["official_work_canonical_write"] == "ask"
    assert writing.artifact_policy.artifact_root == "repo.writing.artifact_repository"

    assert general.runtime_policy.graph_allowed is False
    assert "skill.rag-skill" in general.skill_space.default_skill_refs
    assert general.sandbox_policy.shell_policy == "denied"


def test_task_definitions_do_not_declare_skill_authority() -> None:
    for definition in default_task_definitions().values():
        assert "default_skill_refs" not in definition.to_dict()


def test_legacy_environment_ids_are_not_accepted() -> None:
    registry = default_task_environment_registry()

    for environment_id in (
        "env.vibe_coding",
        "env.writing",
        "env.web_research",
        "env.document_processing",
        "env.general_workspace",
    ):
        try:
            registry.require(environment_id)
        except KeyError:
            continue
        raise AssertionError(f"legacy environment id should not resolve: {environment_id}")


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
    operation_auth = dict(assembly.get("operation_authorization") or {})
    decisions = {
        str(item.get("operation_id") or ""): dict(item)
        for item in list(operation_auth.get("decisions") or [])
    }
    assert decisions["op.shell"]["final_decision"] == "allow"
    assert decisions["op.shell"]["environment_policy"] == "sandboxed"


def test_runtime_mode_does_not_bind_task_environment_without_explicit_selection() -> None:
    profile = next(item for item in default_agent_runtime_profiles() if item.agent_profile_id == "main_interactive_agent")
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)

    assembly = assemble_runtime(
        backend_dir=BACKEND_DIR,
        session_id="session-mode-env",
        turn_id="turn-mode-env",
        agent_invocation_id="agent-invocation-mode-env",
        request_task_selection={"runtime_mode": "professional"},
        model_selection={},
        agent_runtime_profile=profile,
        tool_instances=build_tool_instances(BACKEND_DIR),
        definitions_by_name=index.definitions_by_name,
    ).to_dict()

    assert dict(assembly.get("profile") or {}).get("mode") == "professional"
    assert dict(assembly.get("task_environment") or {}).get("environment_id") == "env.general.workspace"
    assert dict(dict(assembly.get("diagnostics") or {}).get("task_environment") or {}).get("source") == "fallback_default"


def test_explicit_task_environment_selection_is_orthogonal_to_runtime_mode() -> None:
    profile = next(item for item in default_agent_runtime_profiles() if item.agent_profile_id == "main_interactive_agent")
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)

    assembly = assemble_runtime(
        backend_dir=BACKEND_DIR,
        session_id="session-mode-writing",
        turn_id="turn-mode-writing",
        agent_invocation_id="agent-invocation-mode-writing",
        request_task_selection={"runtime_mode": "professional", "task_environment_id": "env.creation.writing"},
        model_selection={},
        agent_runtime_profile=profile,
        tool_instances=build_tool_instances(BACKEND_DIR),
        definitions_by_name=index.definitions_by_name,
    ).to_dict()

    assert dict(assembly.get("profile") or {}).get("mode") == "professional"
    assert dict(assembly.get("task_environment") or {}).get("environment_id") == "env.creation.writing"
    assert dict(dict(assembly.get("diagnostics") or {}).get("task_environment") or {}).get("source") == "explicit_selection"


def test_development_environment_prompt_is_in_task_execution_packet() -> None:
    profile = next(item for item in default_agent_runtime_profiles() if item.agent_profile_id == "main_interactive_agent")
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)
    assembly = assemble_runtime(
        backend_dir=BACKEND_DIR,
        session_id="session-env-prompt",
        turn_id="turn-env-prompt",
        agent_invocation_id="agent-invocation-env-prompt",
        request_task_selection={"runtime_mode": "professional", "task_environment_id": "env.development.sandbox"},
        model_selection={},
        agent_runtime_profile=profile,
        tool_instances=build_tool_instances(BACKEND_DIR),
        definitions_by_name=index.definitions_by_name,
    )

    packet = RuntimeCompiler().compile_task_execution_packet(
        session_id="session-env-prompt",
        task_run={
            "task_run_id": "taskrun:env-prompt",
            "session_id": "session-env-prompt",
            "task_id": "task:env-prompt",
            "agent_profile_id": "main_interactive_agent",
        },
        contract={"user_visible_goal": "修复代码 bug", "completion_criteria": ["bug 修复并验证"]},
        observations=[],
        execution_state={},
        agent_profile_ref="main_interactive_agent",
        available_tools=assembly.available_tools,
        runtime_assembly=assembly,
        invocation_index=1,
    ).packet

    assert "当前任务环境说明" in packet.system_instructions
    assert "优先使用 search_text、search_files、glob_paths、read_file、list_dir" in packet.system_instructions
    assert "old_text not found" in packet.system_instructions
    assert "sandbox overlay" in packet.system_instructions


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


def test_task_environment_catalog_is_single_normalized_resource_surface() -> None:
    catalog = build_task_environment_catalog(
        specific_task_records=[
            {
                "task_id": "task.test.writing",
                "metadata": {"task_environment_id": "env.creation.writing"},
                "task_policy": {},
            }
        ]
    )
    management = catalog.management_payload()
    development = catalog.runtime_environment_payload("env.development.sandbox")
    writing_item = next(
        item
        for item in management["environments"]
        if item["record"]["environment_id"] == "env.creation.writing"
    )

    assert management["authority"] == "task_system.task_environment_catalog"
    assert management["summary"]["environment_count"] == 6
    assert "resource_space" in development
    assert "memory_space" in development
    assert "skill_space" in development
    assert "file_access_tables" in development
    assert development["storage_space"]["task_library_root"] == "storage/task_environments/development/sandbox/task_library"
    assert "skill.browser-operation" in development["skill_space"]["default_skill_refs"]
    assert writing_item["task_library"]["task_ids"] == ["task.test.writing"]


def test_default_environment_skill_refs_exist_in_skill_registry() -> None:
    registry = default_task_environment_registry()
    skill_registry = SkillRegistry(BACKEND_DIR)

    for definition in registry.list():
        skill_refs = [
            *list(definition.spec.skill_space.default_skill_refs),
            *list(definition.spec.skill_space.optional_skill_refs),
            *list(definition.spec.skill_space.denied_skill_refs),
        ]
        for skill_ref in skill_refs:
            skill_name = str(skill_ref).removeprefix("skill.")
            assert skill_registry.get_by_name(skill_name) is not None, f"{definition.record.environment_id}: {skill_ref}"


def test_environment_skill_space_does_not_grant_tools() -> None:
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)
    profile = SimpleNamespace(
        agent_profile_id="skill-space-readonly-agent",
        enabled_runtime_modes=("professional",),
        default_runtime_mode="professional",
        allowed_operations=("op.model_response",),
        blocked_operations=(),
        can_delegate_to_agents=False,
        max_delegate_calls_per_turn=0,
        allowed_delegate_agent_ids=(),
        metadata={},
    )

    assembly = assemble_runtime(
        backend_dir=BACKEND_DIR,
        session_id="session-skill-space-no-tool",
        turn_id="turn-skill-space-no-tool",
        agent_invocation_id="agent-invocation-skill-space-no-tool",
        request_task_selection={"runtime_mode": "professional", "task_environment_id": "env.development.sandbox"},
        model_selection={},
        agent_runtime_profile=profile,
        tool_instances=build_tool_instances(BACKEND_DIR),
        definitions_by_name=index.definitions_by_name,
    ).to_dict()

    tool_names = {str(item.get("tool_name") or "") for item in list(assembly.get("available_tools") or [])}
    skill_space = dict(dict(assembly.get("task_environment") or {}).get("skill_space") or {})
    candidates = {str(item.get("skill_id") or ""): dict(item) for item in list(assembly.get("skill_candidates") or [])}

    assert "skill.visual-asset-generation" in list(skill_space.get("optional_skill_refs") or [])
    assert candidates["skill.visual-asset-generation"]["availability"] == "unavailable"
    assert candidates["skill.visual-asset-generation"]["missing_operations"] == ["op.image_generate"]
    assert "image_generate" not in tool_names
    assert "browser_control" not in tool_names
    assert "terminal" not in tool_names


def test_environment_does_not_filter_agent_allowed_tools() -> None:
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)
    profile = SimpleNamespace(
        agent_profile_id="env-constraint-agent",
        enabled_runtime_modes=("professional",),
        default_runtime_mode="professional",
        allowed_operations=("op.model_response", "op.shell", "op.browser_control", "op.web_search", "op.write_file"),
        blocked_operations=(),
        can_delegate_to_agents=False,
        max_delegate_calls_per_turn=0,
        allowed_delegate_agent_ids=(),
        metadata={},
    )

    assembly = assemble_runtime(
        backend_dir=BACKEND_DIR,
        session_id="session-env-constraint",
        turn_id="turn-env-constraint",
        agent_invocation_id="agent-invocation-env-constraint",
        request_task_selection={"runtime_mode": "professional", "task_environment_id": "env.development.readonly"},
        model_selection={},
        agent_runtime_profile=profile,
        tool_instances=build_tool_instances(BACKEND_DIR),
        definitions_by_name=index.definitions_by_name,
    ).to_dict()

    tool_names = {str(item.get("tool_name") or "") for item in list(assembly.get("available_tools") or [])}
    decisions = {
        str(item.get("operation_id") or ""): dict(item)
        for item in list(dict(assembly.get("operation_authorization") or {}).get("decisions") or [])
    }

    assert "terminal" in tool_names
    assert "browser_control" in tool_names
    assert "web_search" in tool_names
    assert "write_file" in tool_names
    assert decisions["op.shell"]["reason"] == "agent_allowed"
    assert decisions["op.browser_control"]["reason"] == "agent_allowed"
    assert decisions["op.write_file"]["reason"] == "agent_allowed"
    assert decisions["op.web_search"]["final_decision"] == "allow"


def test_runtime_compiler_puts_skill_candidates_in_stable_payload() -> None:
    profile = next(item for item in default_agent_runtime_profiles() if item.agent_profile_id == "main_interactive_agent")
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)
    assembly = assemble_runtime(
        backend_dir=BACKEND_DIR,
        session_id="session-skill-packet",
        turn_id="turn-skill-packet",
        agent_invocation_id="agent-invocation-skill-packet",
        request_task_selection={"runtime_mode": "professional", "task_environment_id": "env.development.sandbox"},
        model_selection={},
        agent_runtime_profile=profile,
        tool_instances=build_tool_instances(BACKEND_DIR),
        definitions_by_name=index.definitions_by_name,
    )

    packet = RuntimeCompiler().compile_task_execution_packet(
        session_id="session-skill-packet",
        task_run={
            "task_run_id": "taskrun:skill-packet",
            "session_id": "session-skill-packet",
            "task_id": "task:skill-packet",
            "agent_profile_id": "main_interactive_agent",
        },
        contract={"user_visible_goal": "验证 skill candidates", "completion_criteria": ["packet 包含 skill candidates"]},
        observations=[],
        execution_state={},
        agent_profile_ref="main_interactive_agent",
        available_tools=assembly.available_tools,
        runtime_assembly=assembly,
        invocation_index=1,
    ).packet
    stable_message = packet.model_messages[1]["content"]
    stable_payload = json.loads(stable_message.split("\n", 1)[1])
    candidate_ids = {str(item.get("skill_id") or "") for item in list(stable_payload.get("skill_candidates") or [])}

    assert "skill.browser-operation" in candidate_ids
    assert stable_payload["runtime_context"]["skill_candidate_count"] == len(stable_payload["skill_candidates"])
    assert stable_payload["operation_authorization"]["authority"] == "harness.runtime.operation_authorization_projection"
    assert stable_payload["runtime_context"]["allowed_operation_count"] == len(stable_payload["operation_authorization"]["allowed_operations"])


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
