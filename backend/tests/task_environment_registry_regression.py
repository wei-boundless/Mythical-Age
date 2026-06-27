from __future__ import annotations

from dataclasses import replace
import json
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from task_system.environments import (
    TaskEnvironmentConfigError,
    TaskEnvironmentRepository,
    build_task_environment_catalog,
    default_task_environment_registry,
    resolve_task_environment,
    task_environment_registry_from_backend_dir,
)
from agent_system.profiles.runtime_profile_registry import default_agent_runtime_profiles
from capability_system.tools.authorization import build_tool_authorization_index
from capability_system.tools.native_tool_catalog import build_tool_instances, get_tool_definitions
from harness.runtime import RuntimeCompiler, assemble_runtime, build_runtime_tool_plan
from prompt_library import (
    DEFAULT_PERSONALITY_PROMPT_REF,
    ENVIRONMENT_LIFECYCLE_PROMPT_IDS_BY_ENVIRONMENT,
    ENVIRONMENT_LIFECYCLE_PROMPT_SLOTS,
    PromptLibraryRegistry,
    PromptResource,
)
from task_system.tasks.definitions import default_task_definitions


def _model_input_text(packet) -> str:
    return "\n\n".join(str(message.get("content") or "") for message in packet.model_messages)


def test_default_task_environments_are_grouped_scene_platforms() -> None:
    registry = default_task_environment_registry()
    groups = {item.group_id for item in registry.list_groups()}

    assert {
        "environment_group.chat",
        "environment_group.coding",
        "environment_group.office",
        "environment_group.general",
    } == groups

    coding = registry.require("env.coding.vibe_workspace").spec
    office = registry.require("env.office.file_search").spec
    general = registry.require("env.general.workspace").spec
    chat = registry.require("env.chat.role_conversation").spec

    assert coding.sandbox_policy.enabled is True
    assert coding.resource_space.storage_namespace == "coding/vibe-workspace"
    assert coding.file_management.file_profile_refs == ("file_profile.managed_project_workspace",)
    assert coding.file_management.constraints["default_read_repository"] == "repo.managed_project.sandbox_workspace"
    assert coding.observability_policy["file_state_authority"] == "runtime.memory.file_state_authority"

    assert [item.prompt_id for item in coding.environment_prompts] == [
        "environment.coding.vibe_workspace.orientation",
        "environment.rule.coding_workspace",
        "coding.rule.core_work_protocol",
        "coding.rule.codebase_inspection",
        "coding.rule.large_scope_exploration",
        "coding.rule.editing",
        "coding.rule.verification",
        "coding.rule.debug_discipline",
        "coding.rule.git_safety",
        "coding.rule.windows_shell",
        "coding.rule.task_progress",
    ]
    assert all(not item.content for item in coding.environment_prompts)
    prompt_registry = PromptLibraryRegistry(BACKEND_DIR)
    coding_prompt = prompt_registry.get_active_resource("environment.coding.vibe_workspace.orientation")
    assert coding_prompt is not None
    sandbox_resource_prompt = prompt_registry.get_active_resource("environment.resource.sandbox_overlay.orientation")
    assert sandbox_resource_prompt is not None

    assert office.sandbox_policy.enabled is False
    assert office.sandbox_policy.shell_policy == "denied"
    assert office.sandbox_policy.browser_policy == "denied"
    assert office.sandbox_policy.network_policy == "allowed"
    assert office.resource_space.storage_namespace == "office/file-search"
    assert office.file_management.file_profile_refs == ("file_profile.base_workspace",)
    assert office.file_management.constraints["project_workspace_search"] == "allowed"
    assert office.artifact_policy.artifact_root == "conversation_artifacts"
    assert [item.prompt_id for item in office.environment_prompts] == [
        "environment.office.file_search.orientation",
        "environment.rule.office_file_search",
    ]

    assert general.sandbox_policy.shell_policy == "task_decided"
    assert general.execution_policy.shell_execution_policy == "task_decided"
    assert [item.prompt_id for item in general.environment_prompts] == [
        "environment.general.workspace.orientation",
        "environment.rule.general_workspace",
    ]
    assert all(item.prompt_kind != "lifecycle" for item in general.environment_prompts)
    assert chat.sandbox_policy.shell_policy == "denied"
    assert chat.sandbox_policy.browser_policy == "denied"
    assert chat.execution_policy.network_execution_policy == "denied"
    assert chat.file_management.file_profile_refs == ()
    assert chat.lifecycle_policy["task_lifecycle_prompts"] == "disabled"
    assert [item.prompt_id for item in chat.environment_prompts] == [
        "environment.chat.role_conversation.orientation",
        "environment.rule.chat_role_conversation",
    ]


def test_task_definitions_do_not_declare_skill_authority() -> None:
    for definition in default_task_definitions().values():
        assert "default_skill_refs" not in definition.to_dict()


def test_obsolete_environment_ids_are_not_accepted() -> None:
    registry = default_task_environment_registry()

    for environment_id in (
        "env.vibe_coding",
        "env.writing",
        "env.web_research",
        "env.document_processing",
        "env.general_workspace",
        "env.development.readonly",
        "env.research.web",
        "env.document.processing",
        "env." + "development.sandbox",
        "env." + "creation.writing",
        "env.system_eval.dual_node",
    ):
        try:
            registry.require(environment_id)
        except KeyError:
            continue
        raise AssertionError(f"legacy environment id should not resolve: {environment_id}")


def test_development_environment_exposes_shell_image_generation_and_image_read_tools_for_authorized_agent() -> None:
    profile = next(item for item in default_agent_runtime_profiles() if item.agent_profile_id == "main_interactive_agent")
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)

    assembly = assemble_runtime(
        backend_dir=BACKEND_DIR,
        session_id="session-test",
        turn_id="turn-test",
        agent_invocation_id="agent-invocation-test",
        runtime_contract={"task_environment_id": "env.coding.vibe_workspace"},
        model_selection={},
        agent_runtime_profile=profile,
        tool_instances=build_tool_instances(BACKEND_DIR),
        definitions_by_name=index.definitions_by_name,
    ).to_dict()

    tool_names = {str(item.get("tool_name") or "") for item in list(assembly.get("available_tools") or [])}
    sandbox_policy = dict(dict(assembly.get("task_environment") or {}).get("sandbox_policy") or {})
    assert "terminal" in tool_names
    assert "image_generate" in tool_names
    assert "attachment_extract_text" in tool_names
    assert "op.image_generate" in list(sandbox_policy.get("side_effect_operations") or [])
    assert "op.mcp_image_ocr" not in list(sandbox_policy.get("side_effect_operations") or [])
    operation_auth = dict(assembly.get("operation_authorization") or {})
    decisions = {
        str(item.get("operation_id") or ""): dict(item)
        for item in list(operation_auth.get("decisions") or [])
    }
    assert decisions["op.shell"]["final_decision"] == "allow"


def test_full_access_does_not_expand_or_unhide_model_visible_tools() -> None:
    profile = next(item for item in default_agent_runtime_profiles() if item.agent_profile_id == "main_interactive_agent")
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)

    assembly = assemble_runtime(
        backend_dir=BACKEND_DIR,
        session_id="session-full-access-tools",
        turn_id="turn-full-access-tools",
        agent_invocation_id="agent-invocation-full-access-tools",
        runtime_contract={"task_environment_id": "env.coding.vibe_workspace"},
        model_selection={},
        agent_runtime_profile=profile,
        tool_instances=build_tool_instances(BACKEND_DIR),
        definitions_by_name=index.definitions_by_name,
        permission_mode="full_access",
    ).to_dict()

    tool_names = {str(item.get("tool_name") or "") for item in list(assembly.get("available_tools") or [])}
    decisions = {
        str(item.get("operation_id") or ""): dict(item)
        for item in list(dict(assembly.get("operation_authorization") or {}).get("decisions") or [])
    }

    assert "terminal" in tool_names
    assert "python_repl" not in tool_names
    assert "git_push" not in tool_names
    assert decisions["op.python_repl"]["final_decision"] == "deny"
    assert decisions["op.python_repl"]["reason"] == "agent_permission_missing"
    assert decisions["op.browser_control"]["final_decision"] == "deny"
    assert decisions["op.browser_control"]["reason"] == "agent_permission_missing"
    assert decisions["op.git_push"]["final_decision"] == "deny"
    assert decisions["op.git_push"]["reason"] == "agent_permission_missing"


def test_coding_environment_exposes_core_development_tools_for_authorized_agent() -> None:
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)
    profile = SimpleNamespace(
        agent_profile_id="coding-env-authorized-agent",
        allowed_operations=(
            "op.model_response",
            "op.read_file",
            "op.write_file",
            "op.edit_file",
            "op.shell",
            "op.python_repl",
            "op.git_status",
            "op.python_symbol_search",
        ),
        blocked_operations=(),
        metadata={},
    )

    assembly = assemble_runtime(
        backend_dir=BACKEND_DIR,
        session_id="session-coding-env-tools",
        turn_id="turn-coding-env-tools",
        agent_invocation_id="agent-invocation-coding-env-tools",
        runtime_contract={"task_environment_id": "env.coding.vibe_workspace"},
        model_selection={},
        agent_runtime_profile=profile,
        tool_instances=build_tool_instances(BACKEND_DIR),
        definitions_by_name=index.definitions_by_name,
    ).to_dict()

    tool_names = {str(item.get("tool_name") or "") for item in list(assembly.get("available_tools") or [])}
    operation_auth = dict(assembly.get("operation_authorization") or {})
    decisions = {
        str(item.get("operation_id") or ""): dict(item)
        for item in list(operation_auth.get("decisions") or [])
    }

    assert {"read_file", "write_file", "edit_file", "terminal", "python_symbol_search"} <= tool_names
    assert "python_repl" not in tool_names
    assert decisions["op.read_file"]["final_decision"] == "allow"
    assert decisions["op.write_file"]["final_decision"] == "allow"
    assert decisions["op.edit_file"]["final_decision"] == "allow"
    assert decisions["op.shell"]["final_decision"] == "allow"
    assert decisions["op.python_repl"]["final_decision"] == "allow"


def test_runtime_available_tools_expose_canonical_tool_input_schema() -> None:
    profile = next(item for item in default_agent_runtime_profiles() if item.agent_profile_id == "main_interactive_agent")
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)

    assembly = assemble_runtime(
        backend_dir=BACKEND_DIR,
        session_id="session-tool-schema",
        turn_id="turn-tool-schema",
        agent_invocation_id="agent-invocation-tool-schema",
        runtime_contract={"task_environment_id": "env.coding.vibe_workspace"},
        model_selection={},
        agent_runtime_profile=profile,
        tool_instances=build_tool_instances(BACKEND_DIR),
        definitions_by_name=index.definitions_by_name,
    ).to_dict()

    tools = {
        str(item.get("tool_name") or ""): dict(item)
        for item in list(assembly.get("available_tools") or [])
    }
    todo = tools["agent_todo"]
    input_schema = dict(todo.get("input_schema") or {})
    properties = dict(input_schema.get("properties") or {})

    assert properties["operation"]["enum"] == [
        "replace",
        "append",
        "start",
        "complete",
        "update_status",
        "remove",
        "clear",
        "view",
    ]
    assert "complete_item" not in properties["operation"]["enum"]
    assert "todos" not in properties
    assert "todos" not in todo["optional_inputs"]


def test_main_agent_profile_selects_default_task_environment_without_explicit_selection() -> None:
    profile = next(item for item in default_agent_runtime_profiles() if item.agent_profile_id == "main_interactive_agent")
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)

    assembly = assemble_runtime(
        backend_dir=BACKEND_DIR,
        session_id="session-profile-env",
        turn_id="turn-profile-env",
        agent_invocation_id="agent-invocation-profile-env",
        runtime_contract={},
        model_selection={},
        agent_runtime_profile=profile,
        tool_instances=build_tool_instances(BACKEND_DIR),
        definitions_by_name=index.definitions_by_name,
    ).to_dict()

    assert dict(assembly.get("profile") or {}).get("profile_ref") == "main_interactive_agent"
    assert dict(assembly.get("task_environment") or {}).get("environment_id") == "env.general.workspace"
    assert dict(dict(assembly.get("diagnostics") or {}).get("task_environment") or {}).get("source") == "agent_runtime_profile"


def test_runtime_policy_default_environment_does_not_override_agent_profile_default_environment() -> None:
    profile = next(item for item in default_agent_runtime_profiles() if item.agent_profile_id == "main_interactive_agent")
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)

    assembly = assemble_runtime(
        backend_dir=BACKEND_DIR,
        session_id="session-policy-env",
        turn_id="turn-policy-env",
        agent_invocation_id="agent-invocation-policy-env",
        runtime_contract={
            "runtime_policy": {
                "context_policy": {"default_environment_id": "env.coding.vibe_workspace"},
            },
            "runtime_profile": {
                "runtime_policy": {
                    "context_policy": {"default_environment_id": "env.office.file_search"},
                },
            },
        },
        model_selection={},
        agent_runtime_profile=profile,
        tool_instances=build_tool_instances(BACKEND_DIR),
        definitions_by_name=index.definitions_by_name,
    ).to_dict()

    assert dict(assembly.get("task_environment") or {}).get("environment_id") == "env.general.workspace"
    assert dict(dict(assembly.get("diagnostics") or {}).get("task_environment") or {}).get("source") == "agent_runtime_profile"


def test_explicit_task_environment_selection_is_orthogonal_to_agent_runtime_profile() -> None:
    profile = next(item for item in default_agent_runtime_profiles() if item.agent_profile_id == "main_interactive_agent")
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)

    assembly = assemble_runtime(
        backend_dir=BACKEND_DIR,
        session_id="session-profile-writing",
        turn_id="turn-profile-writing",
        agent_invocation_id="agent-invocation-profile-writing",
        runtime_contract={"task_environment_id": "env.office.file_search"},
        model_selection={},
        agent_runtime_profile=profile,
        tool_instances=build_tool_instances(BACKEND_DIR),
        definitions_by_name=index.definitions_by_name,
    ).to_dict()

    assert dict(assembly.get("profile") or {}).get("profile_ref") == "main_interactive_agent"
    assert dict(assembly.get("task_environment") or {}).get("environment_id") == "env.office.file_search"
    assert dict(dict(assembly.get("diagnostics") or {}).get("task_environment") or {}).get("source") == "runtime_contract"


def test_development_environment_prompt_is_in_task_execution_packet() -> None:
    profile = next(item for item in default_agent_runtime_profiles() if item.agent_profile_id == "main_interactive_agent")
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)
    assembly = assemble_runtime(
        backend_dir=BACKEND_DIR,
        session_id="session-env-prompt",
        turn_id="turn-env-prompt",
        agent_invocation_id="agent-invocation-env-prompt",
        runtime_contract={"task_environment_id": "env.coding.vibe_workspace"},
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

    model_input = _model_input_text(packet)
    stable_message = _message_content_with_title(packet, "Task execution environment boundary")
    stable_payload = _payload_after_title(stable_message, "Task execution environment boundary")
    manifest = packet.diagnostics["prompt_manifest"]
    expected_environment_refs = [
        "runtime.rule.file_management.generic",
        "environment.resource.managed_project_workspace.orientation",
        "environment.resource.sandbox_overlay.orientation",
        "environment.coding.vibe_workspace.orientation",
        "environment.rule.coding_workspace",
        "coding.rule.core_work_protocol",
        "coding.rule.codebase_inspection",
        "coding.rule.large_scope_exploration",
        "coding.rule.editing",
        "coding.rule.verification",
        "coding.rule.debug_discipline",
        "coding.rule.git_safety",
        "coding.rule.windows_shell",
        "coding.rule.task_progress",
    ]
    assert assembly.environment_prompt_refs == tuple(expected_environment_refs)
    assert manifest["prompt_mount_plan"]["base_prompt_refs"] == expected_environment_refs
    assert manifest["prompt_mount_plan"].get("overlay_prompt_refs", []) == []
    assert "environment_prompt_refs" not in stable_payload["task_environment"]
    assert "prompt_mount_plan" not in stable_payload["task_environment"]
    assert stable_payload["task_environment"]["prompt_mount_summary"]["environment_prompt_count"] == len(
        expected_environment_refs
    )


def test_coding_environment_prompt_is_isolated_from_development_prompt() -> None:
    profile = next(item for item in default_agent_runtime_profiles() if item.agent_profile_id == "main_interactive_agent")
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)
    assembly = assemble_runtime(
        backend_dir=BACKEND_DIR,
        session_id="session-coding-env-prompt",
        turn_id="turn-coding-env-prompt",
        agent_invocation_id="agent-invocation-coding-env-prompt",
        runtime_contract={"task_environment_id": "env.coding.vibe_workspace"},
        model_selection={},
        agent_runtime_profile=profile,
        tool_instances=build_tool_instances(BACKEND_DIR),
        definitions_by_name=index.definitions_by_name,
    )

    packet = RuntimeCompiler().compile_task_execution_packet(
        session_id="session-coding-env-prompt",
        task_run={
            "task_run_id": "taskrun:coding-env-prompt",
            "session_id": "session-coding-env-prompt",
            "task_id": "task:coding-env-prompt",
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

    model_input = _model_input_text(packet)
    stable_message = _message_content_with_title(packet, "Task execution environment boundary")
    stable_payload = _payload_after_title(stable_message, "Task execution environment boundary")
    manifest = packet.diagnostics["prompt_manifest"]
    expected_environment_refs = [
        "runtime.rule.file_management.generic",
        "environment.resource.managed_project_workspace.orientation",
        "environment.resource.sandbox_overlay.orientation",
        "environment.coding.vibe_workspace.orientation",
        "environment.rule.coding_workspace",
        "coding.rule.core_work_protocol",
        "coding.rule.codebase_inspection",
        "coding.rule.large_scope_exploration",
        "coding.rule.editing",
        "coding.rule.verification",
        "coding.rule.debug_discipline",
        "coding.rule.git_safety",
        "coding.rule.windows_shell",
        "coding.rule.task_progress",
    ]

    assert assembly.environment_prompt_refs == tuple(expected_environment_refs)
    assert manifest["prompt_mount_plan"]["base_prompt_refs"] == expected_environment_refs
    assert manifest["prompt_mount_plan"].get("overlay_prompt_refs", []) == []
    assert "environment_prompt_refs" not in stable_payload["task_environment"]
    assert "prompt_mount_plan" not in stable_payload["task_environment"]
    assert "coding.rule.engineering_judgment" not in manifest["prompt_mount_plan"]["base_prompt_refs"]


def test_coding_environment_prompt_text_uses_agent_facing_language() -> None:
    registry = PromptLibraryRegistry(BACKEND_DIR)
    coding_refs = [
        "environment.resource.managed_project_workspace.orientation",
        "environment.resource.sandbox_overlay.orientation",
        "environment.coding.vibe_workspace.orientation",
        "environment.rule.coding_workspace",
        "coding.rule.core_work_protocol",
        "coding.rule.codebase_inspection",
        "coding.rule.large_scope_exploration",
        "coding.rule.editing",
        "coding.rule.verification",
        "coding.rule.debug_discipline",
        "coding.rule.git_safety",
        "coding.rule.windows_shell",
        "coding.rule.task_progress",
    ]

    content_by_ref = {}
    for prompt_ref in coding_refs:
        resource = registry.get_active_resource(prompt_ref)
        assert resource is not None
        content_by_ref[prompt_ref] = resource.content

    combined = "\n".join(content_by_ref.values())
    assert "这是 runtime 节点" not in combined
    assert "根据任务图执行" not in combined
    assert "runtime packet" not in combined
    assert ".v1" not in combined
    assert "confidence" not in combined.lower()


def test_coding_lifecycle_prompts_own_control_signal_closeout_without_polluting_other_environments() -> None:
    registry = PromptLibraryRegistry(BACKEND_DIR)
    coding_refs = ENVIRONMENT_LIFECYCLE_PROMPT_IDS_BY_ENVIRONMENT["env.coding.vibe_workspace"]
    office_refs = ENVIRONMENT_LIFECYCLE_PROMPT_IDS_BY_ENVIRONMENT["env.office.file_search"]
    general_refs = ENVIRONMENT_LIFECYCLE_PROMPT_IDS_BY_ENVIRONMENT["env.general.workspace"]

    coding_text = "\n".join(
        registry.get_active_resource(prompt_ref).content
        for prompt_ref in coding_refs
        if registry.get_active_resource(prompt_ref) is not None
    )
    office_text = "\n".join(
        registry.get_active_resource(prompt_ref).content
        for prompt_ref in office_refs
        if registry.get_active_resource(prompt_ref) is not None
    )
    general_text = "\n".join(
        registry.get_active_resource(prompt_ref).content
        for prompt_ref in general_refs
        if registry.get_active_resource(prompt_ref) is not None
    )

    assert len(coding_refs) == len(ENVIRONMENT_LIFECYCLE_PROMPT_SLOTS)
    assert "系统运行控制信号" in coding_text
    assert "pause/stop/replan" in coding_text
    assert "系统控制信号" in coding_text
    assert "runtime_control" in coding_text
    assert "pause/stop/replan" not in office_text
    assert "pause/stop/replan" not in general_text


def test_resolved_environment_exports_storage_and_file_boundaries() -> None:
    resolved = resolve_task_environment("env.coding.vibe_workspace")
    payload = resolved.to_dict()

    assert resolved.group is not None
    assert resolved.group.group_id == "environment_group.coding"
    assert payload["storage_space"]["storage_namespace"] == "coding/vibe-workspace"
    assert payload["storage_space"]["artifact_root"] == "storage/task_environments/coding/vibe-workspace/artifacts"
    assert payload["sandbox_policy"]["enabled"] is True
    assert len(resolved.file_access_tables) == 1
    assert resolved.file_access_tables[0].profile_id == "file_profile.managed_project_workspace"


def test_task_environment_catalog_is_single_normalized_resource_surface() -> None:
    catalog = build_task_environment_catalog(
        engagement_plans=[
            {
                "plan_id": "engage.test.writing",
                "task_environment_id": "env.office.file_search",
            }
        ]
    )
    management = catalog.management_payload()
    development = catalog.runtime_environment_payload("env.coding.vibe_workspace")
    writing_item = next(
        item
        for item in management["environments"]
        if item["record"]["environment_id"] == "env.office.file_search"
    )

    assert management["authority"] == "task_system.task_environment_catalog"
    assert management["summary"]["environment_count"] == 4
    assert management["summary"]["builtin_template_count"] == 4
    assert management["summary"]["workspace_environment_count"] == 0
    assert management["summary"]["system_internal_environment_count"] == 0
    assert writing_item["definition_source"] == "builtin_default"
    assert writing_item["management_scope"] == "builtin_template"
    assert "resource_space" in development
    assert "memory_space" in development
    assert "file_access_tables" in development
    assert development["storage_space"]["task_library_root"] == "storage/task_environments/coding/vibe-workspace/task_library"
    assert writing_item["task_library"]["engagement_plan_ids"] == ["engage.test.writing"]
    assert writing_item["task_library"]["task_ids"] == ["engage.test.writing"]


def test_task_environment_does_not_filter_agent_authorized_operations() -> None:
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)
    profile = SimpleNamespace(
        agent_profile_id="env-constraint-agent",
        allowed_operations=("op.model_response", "op.shell", "op.browser_control", "op.web_search", "op.write_file"),
        blocked_operations=(),
        metadata={},
    )

    assembly = assemble_runtime(
        backend_dir=BACKEND_DIR,
        session_id="session-env-constraint",
        turn_id="turn-env-constraint",
        agent_invocation_id="agent-invocation-env-constraint",
        runtime_contract={"task_environment_id": "env.office.file_search"},
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
    assert decisions["op.shell"]["final_decision"] == "allow"
    assert decisions["op.browser_control"]["final_decision"] == "allow"
    assert decisions["op.write_file"]["final_decision"] == "allow"
    assert decisions["op.web_search"]["final_decision"] == "allow"


def test_runtime_operation_ceiling_limits_tools_before_prompt_index() -> None:
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)
    profile = next(item for item in default_agent_runtime_profiles() if item.agent_profile_id == "main_interactive_agent")

    assembly = assemble_runtime(
        backend_dir=BACKEND_DIR,
        session_id="session-execution-permit",
        turn_id="turn-execution-permit",
        agent_invocation_id="agent-invocation-execution-permit",
        runtime_contract={
            "task_environment_id": "env.coding.vibe_workspace",
            "runtime_profile": {
                "execution_permit": {
                    "operation_ceiling": ["op.model_response", "op.read_file"],
                },
            },
        },
        model_selection={},
        agent_runtime_profile=profile,
        tool_instances=build_tool_instances(BACKEND_DIR),
        definitions_by_name=index.definitions_by_name,
    ).to_dict()

    tool_names = {str(item.get("tool_name") or "") for item in list(assembly.get("available_tools") or [])}
    allowed_operations = set(dict(assembly.get("operation_authorization") or {}).get("allowed_operations") or [])
    decisions = {
        str(item.get("operation_id") or ""): dict(item)
        for item in list(dict(assembly.get("operation_authorization") or {}).get("decisions") or [])
    }

    assert tool_names == {"read_file"}
    assert allowed_operations == {"op.model_response", "op.read_file"}
    assert decisions["op.write_file"]["reason"] == "agent_permission_missing"
    assert decisions["op.shell"]["reason"] == "agent_permission_missing"


def test_full_access_still_respects_explicit_operation_ceiling() -> None:
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)
    profile = next(item for item in default_agent_runtime_profiles() if item.agent_profile_id == "main_interactive_agent")

    assembly = assemble_runtime(
        backend_dir=BACKEND_DIR,
        session_id="session-full-access-ceiling",
        turn_id="turn-full-access-ceiling",
        agent_invocation_id="agent-invocation-full-access-ceiling",
        runtime_contract={
            "task_environment_id": "env.coding.vibe_workspace",
            "runtime_profile": {
                "execution_permit": {
                    "operation_ceiling": ["op.model_response", "op.read_file"],
                },
            },
        },
        model_selection={},
        agent_runtime_profile=profile,
        tool_instances=build_tool_instances(BACKEND_DIR),
        definitions_by_name=index.definitions_by_name,
        permission_mode="full_access",
    ).to_dict()

    tool_names = {str(item.get("tool_name") or "") for item in list(assembly.get("available_tools") or [])}
    allowed_operations = set(dict(assembly.get("operation_authorization") or {}).get("allowed_operations") or [])
    decisions = {
        str(item.get("operation_id") or ""): dict(item)
        for item in list(dict(assembly.get("operation_authorization") or {}).get("decisions") or [])
    }

    assert tool_names == {"read_file"}
    assert allowed_operations == {"op.model_response", "op.read_file"}
    assert decisions["op.write_file"]["reason"] == "agent_permission_missing"
    assert decisions["op.shell"]["reason"] == "agent_permission_missing"


def test_allowed_operation_requests_do_not_cut_agent_profile_permissions() -> None:
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)
    profile = next(item for item in default_agent_runtime_profiles() if item.agent_profile_id == "main_interactive_agent")

    assembly = assemble_runtime(
        backend_dir=BACKEND_DIR,
        session_id="session-disjoint-operation-scopes",
        turn_id="turn-disjoint-operation-scopes",
        agent_invocation_id="agent-invocation-disjoint-operation-scopes",
        runtime_contract={
            "task_environment_id": "env.coding.vibe_workspace",
            "allowed_operations": ["op.read_file"],
            "runtime_profile": {
                "execution_permit": {
                    "allowed_operations": ["op.write_file"],
                },
            },
        },
        model_selection={},
        agent_runtime_profile=profile,
        tool_instances=build_tool_instances(BACKEND_DIR),
        definitions_by_name=index.definitions_by_name,
    ).to_dict()

    tool_names = {str(item.get("tool_name") or "") for item in list(assembly.get("available_tools") or [])}
    allowed_operations = set(dict(assembly.get("operation_authorization") or {}).get("allowed_operations") or [])
    decisions = {
        str(item.get("operation_id") or ""): dict(item)
        for item in list(dict(assembly.get("operation_authorization") or {}).get("decisions") or [])
    }

    assert "read_file" in tool_names
    assert "write_file" in tool_names
    assert "terminal" in tool_names
    assert {"op.read_file", "op.write_file", "op.shell"} <= allowed_operations
    assert decisions["op.write_file"]["final_decision"] == "allow"
    assert decisions["op.shell"]["final_decision"] == "allow"


def test_development_environment_keeps_document_capability_routes() -> None:
    profile = next(item for item in default_agent_runtime_profiles() if item.agent_profile_id == "main_interactive_agent")
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)

    assembly = assemble_runtime(
        backend_dir=BACKEND_DIR,
        session_id="session-document-tools",
        turn_id="turn-document-tools",
        agent_invocation_id="agent-invocation-document-tools",
        runtime_contract={"task_environment_id": "env.coding.vibe_workspace"},
        model_selection={},
        agent_runtime_profile=profile,
        tool_instances=build_tool_instances(BACKEND_DIR),
        definitions_by_name=index.definitions_by_name,
    )
    plan = build_runtime_tool_plan(
        runtime_assembly=assembly,
        invocation_kind="task_execution",
        tool_definitions_by_name=index.definitions_by_name,
    )
    tool_names = {str(item.get("tool_name") or "") for item in list(assembly.available_tools)}
    decisions = {
        str(item.get("operation_id") or ""): dict(item)
        for item in list(dict(assembly.operation_authorization or {}).get("decisions") or [])
    }
    pdf_capability = plan.capability_table.capability_for_operation("op.mcp_pdf")

    assert "read_file" in tool_names
    assert "read_structured_file" in tool_names
    assert "git_status" in tool_names
    assert "python_symbol_search" in tool_names
    assert decisions["op.git_status"]["final_decision"] == "allow"
    assert decisions["op.python_symbol_search"]["final_decision"] == "allow"
    assert decisions["op.mcp_pdf"]["final_decision"] == "allow"
    assert pdf_capability is not None
    assert pdf_capability.metadata["route"] == "pdf"
    assert pdf_capability.dispatchable is False


def test_single_agent_turn_packet_keeps_development_environment_authorized_side_effect_tools() -> None:
    profile = next(item for item in default_agent_runtime_profiles() if item.agent_profile_id == "main_interactive_agent")
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)

    assembly = assemble_runtime(
        backend_dir=BACKEND_DIR,
        session_id="session-single-turn-side-effects",
        turn_id="turn-single-turn-side-effects",
        agent_invocation_id="agent-invocation-single-turn-side-effects",
        runtime_contract={"task_environment_id": "env.coding.vibe_workspace"},
        model_selection={},
        agent_runtime_profile=profile,
        tool_instances=build_tool_instances(BACKEND_DIR),
        definitions_by_name=index.definitions_by_name,
    )
    packet = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session-single-turn-side-effects",
        turn_id="turn-single-turn-side-effects",
        agent_invocation_id="agent-invocation-single-turn-side-effects",
        user_message="生成一个像素风地下塔素材。",
        history=[],
        runtime_assembly=assembly,
    ).packet
    tool_names = {str(item.get("tool_name") or item.get("name") or "") for item in packet.available_tools}

    assert "image_generate" in tool_names
    assert "terminal" in tool_names
    assert "write_file" in tool_names
    assert "spawn_subagent" not in tool_names
    assert "wait_subagent" not in tool_names
    assert "list_subagents" not in tool_names
    assert any(dict(item).get("read_only") is False for item in packet.available_tools)
    assert "tool_call" in packet.allowed_action_types
    assert packet.output_contract["native_actions"]["tool_call"]["boundary"] == "runtime_visible_tools_only"


def test_general_single_agent_turn_packet_includes_lifecycle_environment_prompts() -> None:
    profile = next(item for item in default_agent_runtime_profiles() if item.agent_profile_id == "main_interactive_agent")
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)
    expected_environment_refs = [
        "runtime.rule.file_management.generic",
        "environment.resource.general_workspace.orientation",
        "environment.general.workspace.orientation",
        "environment.rule.general_workspace",
    ]
    general_lifecycle_defaults = ENVIRONMENT_LIFECYCLE_PROMPT_IDS_BY_ENVIRONMENT["env.general.workspace"]
    expected_lifecycle_refs = [
        ref
        for ref in general_lifecycle_defaults
        if ref.rsplit(".", 1)[-1]
        in {
            "context_intake",
            "request_judgment",
            "environment_capability_alignment",
            "action_selection",
            "task_run_handoff",
            "tool_dispatch",
            "finalization",
        }
    ]

    assembly = assemble_runtime(
        backend_dir=BACKEND_DIR,
        session_id="session-general-lifecycle",
        turn_id="turn-general-lifecycle",
        agent_invocation_id="agent-invocation-general-lifecycle",
        runtime_contract={"task_environment_id": "env.general.workspace"},
        model_selection={},
        agent_runtime_profile=profile,
        tool_instances=build_tool_instances(BACKEND_DIR),
        definitions_by_name=index.definitions_by_name,
    )
    packet = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session-general-lifecycle",
        turn_id="turn-general-lifecycle",
        agent_invocation_id="agent-invocation-general-lifecycle",
        user_message="继续审查这个系统。",
        history=[],
        runtime_assembly=assembly,
    ).packet
    stable_message = _message_content_with_title(packet, "Operating Contract")
    stable_payload = _payload_after_title(stable_message, "Operating Contract")
    model_input = _model_input_text(packet)
    lifecycle_message = next(
        str(message.get("content") or "")
        for message in packet.model_messages
        if "General 请求判断生命周期" in str(message.get("content") or "")
    )

    assert assembly.environment_prompt_refs == tuple(expected_environment_refs)
    assert assembly.personality_prompt_refs == (DEFAULT_PERSONALITY_PROMPT_REF,)
    assert "environment_prompt_refs" not in stable_payload["task_environment"]
    assert "prompt_mount_plan" not in stable_payload["task_environment"]
    assert stable_payload["task_environment"]["prompt_mount_summary"]["environment_prompt_count"] == len(
        expected_environment_refs
    )
    assert stable_payload["task_environment"]["prompt_mount_summary"]["lifecycle_prompt_count"] == len(
        expected_lifecycle_refs
    )
    assert stable_payload["task_environment"]["prompt_mount_summary"]["personality_prompt_count"] == 1
    assert packet.diagnostics["prompt_manifest"]["stable_prompt_refs"].count(DEFAULT_PERSONALITY_PROMPT_REF) == 1
    assert packet.diagnostics["prompt_manifest"]["prompt_mount_plan"]["base_prompt_refs"] == expected_environment_refs
    assert packet.diagnostics["prompt_manifest"]["prompt_mount_plan"].get("overlay_prompt_refs", []) == []
    assert packet.diagnostics["prompt_manifest"]["prompt_mount_plan"]["lifecycle_prompt_refs"] == expected_lifecycle_refs
    assert set(
        packet.diagnostics["prompt_manifest"]["prompt_mount_plan"]["lifecycle_trigger_reasons"]
    ) == set(expected_lifecycle_refs)
    assert (
        packet.diagnostics["prompt_manifest"]["prompt_mount_plan"]["lifecycle_trigger_reasons"][
            "environment.general.lifecycle.tool_dispatch"
        ]
        == "capability: tool_call action is allowed and visible tools are present"
    )
    assert "environment.general.lifecycle.plan_gate" not in packet.diagnostics["prompt_manifest"]["prompt_mount_plan"]["lifecycle_trigger_reasons"]
    assert "environment.general.lifecycle.work_relation" not in packet.diagnostics["prompt_manifest"]["prompt_mount_plan"]["lifecycle_trigger_reasons"]
    assert "environment.general.lifecycle.memory_read_context" not in packet.diagnostics["prompt_manifest"]["prompt_mount_plan"]["lifecycle_trigger_reasons"]
    assert "environment.general.lifecycle.compaction_handoff" not in packet.diagnostics["prompt_manifest"]["prompt_mount_plan"]["lifecycle_trigger_reasons"]
    assert "environment.general.lifecycle.subagent_delegation" not in packet.diagnostics["prompt_manifest"]["prompt_mount_plan"]["lifecycle_trigger_reasons"]
    assert packet.diagnostics["prompt_manifest"]["prompt_mount_plan"]["personality_prompt_refs"] == [
        DEFAULT_PERSONALITY_PROMPT_REF
    ]
    assert set(expected_lifecycle_refs).issubset(set(general_lifecycle_defaults))


def test_task_execution_lifecycle_prompts_are_main_agent_specific() -> None:
    profiles = {item.agent_profile_id: item for item in default_agent_runtime_profiles()}
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)
    cases = {
        "main_coding_agent": {
            "environment_id": "env.coding.vibe_workspace",
            "prefix": "environment.coding.lifecycle.",
            "included": "Coding 动作选择生命周期",
            "excluded": ("Office 动作选择生命周期", "General 动作选择生命周期"),
        },
        "main_office_agent": {
            "environment_id": "env.office.file_search",
            "prefix": "environment.office.lifecycle.",
            "included": "Office 动作选择生命周期",
            "excluded": ("Coding 动作选择生命周期", "General 动作选择生命周期"),
        },
        "main_interactive_agent": {
            "environment_id": "env.general.workspace",
            "prefix": "environment.general.lifecycle.",
            "included": "General 动作选择生命周期",
            "excluded": ("Coding 动作选择生命周期", "Office 动作选择生命周期"),
        },
    }

    for profile_id, expectation in cases.items():
        profile = profiles[profile_id]
        environment_id = str(expectation["environment_id"])
        assembly = assemble_runtime(
            backend_dir=BACKEND_DIR,
            session_id=f"session-{profile_id}",
            turn_id=f"turn-{profile_id}",
            agent_invocation_id=f"agent-{profile_id}",
            runtime_contract={},
            model_selection={},
            agent_runtime_profile=profile,
            tool_instances=build_tool_instances(BACKEND_DIR),
            definitions_by_name=index.definitions_by_name,
        )
        packet = RuntimeCompiler().compile_task_execution_packet(
            session_id=f"session-{profile_id}",
            task_run={
                "task_run_id": f"taskrun:{profile_id}",
                "session_id": f"session-{profile_id}",
                "task_id": f"task:{profile_id}",
                "agent_profile_id": profile_id,
            },
            contract={"user_visible_goal": "验证主 agent 生命周期提示词", "completion_criteria": ["提示词按主 agent 隔离"]},
            observations=[],
            execution_state={},
            agent_profile_ref=profile_id,
            available_tools=assembly.available_tools,
            runtime_assembly=assembly,
            invocation_index=1,
        ).packet
        manifest = packet.diagnostics["prompt_manifest"]
        lifecycle_refs = list(manifest["prompt_mount_plan"]["lifecycle_prompt_refs"])
        prompt_defaults = dict(assembly.profile.prompt_policy.get("lifecycle_prompt_defaults") or {})
        wiring_prompt_gates = dict(
            dict(assembly.system_wiring_manifest.get("compiled") or {}).get("prompt_resource_gates") or {}
        )
        wiring_lifecycle_refs = [ref for ref in wiring_prompt_gates if ".lifecycle." in ref]

        assert assembly.task_environment["environment_id"] == environment_id
        assert dict(assembly.diagnostics["task_environment"]).get("source") == "agent_runtime_profile"
        assert prompt_defaults
        assert all(ref.startswith(str(expectation["prefix"])) for ref in prompt_defaults.values())
        assert wiring_lifecycle_refs
        assert all(ref.startswith(str(expectation["prefix"])) for ref in wiring_lifecycle_refs)
        assert lifecycle_refs
        assert all(ref.startswith(str(expectation["prefix"])) for ref in lifecycle_refs)
        assert set(lifecycle_refs).issubset(set(ENVIRONMENT_LIFECYCLE_PROMPT_IDS_BY_ENVIRONMENT[environment_id]))


def test_chat_environment_uses_role_prompt_boundary_without_task_lifecycle() -> None:
    profile = next(item for item in default_agent_runtime_profiles() if item.agent_profile_id == "main_interactive_agent")
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)
    assembly = assemble_runtime(
        backend_dir=BACKEND_DIR,
        session_id="session-chat-env",
        turn_id="turn-chat-env",
        agent_invocation_id="agent-chat-env",
        runtime_contract={"task_environment_id": "env.chat.role_conversation"},
        model_selection={},
        agent_runtime_profile=profile,
        tool_instances=build_tool_instances(BACKEND_DIR),
        definitions_by_name=index.definitions_by_name,
    )
    packet = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session-chat-env",
        turn_id="turn-chat-env",
        agent_invocation_id="agent-chat-env",
        user_message="今晚想聊会儿。",
        history=[],
        runtime_assembly=assembly,
    ).packet
    manifest = packet.diagnostics["prompt_manifest"]
    model_input = _model_input_text(packet)

    assert assembly.environment_prompt_refs == (
        "environment.chat.role_conversation.orientation",
        "environment.rule.chat_role_conversation",
    )
    assert tuple(packet.available_tools) == ()
    assert "tool_call" not in packet.allowed_action_types
    assert "request_task_run" not in packet.allowed_action_types
    assert manifest["prompt_mount_plan"]["lifecycle_prompt_refs"] == []
    assert manifest["prompt_mount_plan"]["base_prompt_refs"] == [
        "environment.chat.role_conversation.orientation",
        "environment.rule.chat_role_conversation",
    ]
    assert "environment.coding.lifecycle." not in model_input
    assert "environment.office.lifecycle." not in model_input
    assert "角色氛围" in model_input


def test_agent_prompt_policy_owns_lifecycle_defaults_over_environment_selection() -> None:
    profile = next(item for item in default_agent_runtime_profiles() if item.agent_profile_id == "main_interactive_agent")
    polluted_profile = replace(
        profile,
        metadata={
            **dict(profile.metadata),
            "runtime_policy": {
                "prompt_policy": {
                    "lifecycle_prompt_defaults": {
                        "context_intake": "environment.general.lifecycle.context_intake",
                        "action_selection": "environment.general.lifecycle.action_selection",
                        "finalization": "environment.general.lifecycle.finalization",
                    }
                }
            },
        },
    )
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)

    assembly = assemble_runtime(
        backend_dir=BACKEND_DIR,
        session_id="session-lifecycle-boundary-authority",
        turn_id="turn-lifecycle-boundary-authority",
        agent_invocation_id="agent-lifecycle-boundary-authority",
        runtime_contract={"task_environment_id": "env.coding.vibe_workspace"},
        model_selection={},
        agent_runtime_profile=polluted_profile,
        tool_instances=build_tool_instances(BACKEND_DIR),
        definitions_by_name=index.definitions_by_name,
    )

    assert (
        assembly.profile.prompt_policy["lifecycle_prompt_defaults"]["action_selection"]
        == "environment.general.lifecycle.action_selection"
    )
    mount_defaults = assembly.prompt_mount_plan["lifecycle_prompt_defaults"]
    assert mount_defaults["action_selection"] == "environment.general.lifecycle.action_selection"
    assert set(mount_defaults.values()) == {
        "environment.general.lifecycle.context_intake",
        "environment.general.lifecycle.action_selection",
        "environment.general.lifecycle.finalization",
    }

    fallback_payload = assembly.to_dict()
    fallback_payload["prompt_mount_plan"] = {}
    packet = RuntimeCompiler().compile_task_execution_packet(
        session_id="session-lifecycle-boundary-authority",
        task_run={
            "task_run_id": "taskrun:lifecycle-boundary-authority",
            "session_id": "session-lifecycle-boundary-authority",
            "task_id": "task:lifecycle-boundary-authority",
            "agent_profile_id": "main_interactive_agent",
        },
        contract={"user_visible_goal": "验证生命周期提示词权威", "completion_criteria": ["按 agent 配置装配"]},
        observations=[],
        execution_state={},
        agent_profile_ref="main_interactive_agent",
        available_tools=assembly.available_tools,
        runtime_assembly=fallback_payload,
        invocation_index=1,
    ).packet

    lifecycle_refs = packet.diagnostics["prompt_manifest"]["prompt_mount_plan"]["lifecycle_prompt_refs"]
    assert lifecycle_refs
    assert all(ref.startswith("environment.general.lifecycle.") for ref in lifecycle_refs)
    assert "environment.coding.lifecycle.action_selection" not in lifecycle_refs


def test_runtime_compiler_stable_payload_keeps_environment_and_operation_projection_only() -> None:
    profile = next(item for item in default_agent_runtime_profiles() if item.agent_profile_id == "main_interactive_agent")
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)
    assembly = assemble_runtime(
        backend_dir=BACKEND_DIR,
        session_id="session-skill-packet",
        turn_id="turn-skill-packet",
        agent_invocation_id="agent-invocation-skill-packet",
        runtime_contract={"task_environment_id": "env.coding.vibe_workspace"},
        model_selection={},
        agent_runtime_profile=profile,
        tool_instances=build_tool_instances(BACKEND_DIR),
        definitions_by_name=index.definitions_by_name,
    )
    assembly_payload = assembly.to_dict()

    packet = RuntimeCompiler().compile_task_execution_packet(
        session_id="session-skill-packet",
        task_run={
            "task_run_id": "taskrun:skill-packet",
            "session_id": "session-skill-packet",
            "task_id": "task:skill-packet",
            "agent_profile_id": "main_interactive_agent",
        },
        contract={"user_visible_goal": "验证环境资源面", "completion_criteria": ["packet 只包含环境资源边界和运行时授权投影"]},
        observations=[],
        execution_state={},
        agent_profile_ref="main_interactive_agent",
        available_tools=assembly.available_tools,
        runtime_assembly=assembly,
        invocation_index=1,
    ).packet
    stable_message = _message_content_with_title(packet, "Task execution environment boundary")
    stable_payload = _payload_after_title(stable_message, "Task execution environment boundary")
    dynamic_payload = _payload_after_title(
        _message_content_with_title(packet, "Current Runtime Boundary"),
        "Current Runtime Boundary",
    )

    assert "task_environment" in stable_payload
    assert "storage" in stable_payload["task_environment"]
    assert "resource_boundary" in stable_payload["task_environment"]
    assert "operation_authorization" not in stable_payload
    operation_summary = dynamic_payload["operation_permission_summary"]
    runtime_context = dynamic_payload["runtime_context"]
    assert "authority" not in operation_summary
    assert operation_summary["allowed_operation_count"] == runtime_context["tool_capability_surface"]["allowed_operation_count"]
    assert "allowed_operations" not in operation_summary
    assert "denied_operations" not in operation_summary
    assert operation_summary["omitted_denial_details"] is True


def test_resolved_office_environment_builds_file_access_table() -> None:
    resolved = resolve_task_environment("env.office.file_search")

    assert resolved.spec.environment_id == "env.office.file_search"
    assert len(resolved.file_access_tables) == 1
    table = resolved.file_access_tables[0]
    assert table.profile_id == "file_profile.base_workspace"
    assert table.is_allowed(repository_id="repo.base.project_workspace", action="read") is True
    assert table.is_allowed(repository_id="repo.base.project_workspace", action="search") is True


def test_resolved_environment_can_apply_agent_file_action_ceiling() -> None:
    resolved = resolve_task_environment("env.coding.vibe_workspace", agent_allowed_file_actions=("read", "search"))
    table = resolved.file_access_tables[0]

    assert table.is_allowed(repository_id="repo.managed_project.project_workspace", action="read") is True
    assert table.is_allowed(repository_id="repo.managed_project.sandbox_workspace", action="write") is False
    assert any(denial.source == "agent_profile" and denial.action == "write" for denial in table.denials)


def test_all_default_task_environments_resolve_file_access_tables() -> None:
    for environment_id in (
        "env.coding.vibe_workspace",
        "env.office.file_search",
        "env.general.workspace",
    ):
        resolved = resolve_task_environment(environment_id)
        assert resolved.spec.environment_id == environment_id
        assert resolved.file_access_tables
    chat = resolve_task_environment("env.chat.role_conversation")
    assert chat.spec.environment_id == "env.chat.role_conversation"
    assert chat.file_access_tables == ()


def test_configured_task_environment_loads_from_backend_storage(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    config_dir = backend_dir / "task_system" / "storage" / "task_environments"
    config_dir.mkdir(parents=True)
    (config_dir / "environments.json").write_text(
        json.dumps(
            {
                "groups": [
                    {
                        "group_id": "environment_group.custom_lab",
                        "title": "Custom Lab",
                        "description": "Custom bounded runtime resources.",
                    }
                ],
                "environments": [
                    {
                        "record": {
                            "environment_id": "env.custom.lab",
                            "title": "Custom Lab",
                            "group_id": "environment_group.custom_lab",
                            "environment_kind": "custom",
                        },
                        "spec": {
                            "spec_id": "envspec.custom.lab.v1",
                            "environment_id": "env.custom.lab",
                            "environment_prompts": [
                                {
                                    "prompt_id": "environment.custom.lab",
                                    "content": "你处在自定义实验环境中。只能在环境声明的 artifact/storage 边界内写入。",
                                }
                            ],
                            "sandbox_policy": {
                                "enabled": False,
                                "sandbox_mode": "none",
                                "workspace_access": "read_mostly",
                                "write_policy": "artifact_only",
                                "shell_policy": "denied",
                            },
                            "file_management": {
                                "file_profile_refs": ["file_profile.general_workspace"],
                                "required_repository_kinds": ["conversation_artifacts"],
                                "canonical_write_policy": "artifact_only",
                            },
                            "resource_space": {
                                "storage_namespace": "custom/lab",
                                "workspace_policy": "read_mostly",
                                "artifact_root_policy": "conversation_artifacts",
                            },
                            "execution_policy": {
                                "real_workspace_access": "read_only",
                                "write_scope_policy": "artifact_only",
                                "shell_execution_policy": "denied",
                                "browser_execution_policy": "denied",
                                "network_execution_policy": "denied",
                            },
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    registry = task_environment_registry_from_backend_dir(backend_dir)
    catalog = build_task_environment_catalog(registry=registry)
    payload = catalog.runtime_environment_payload("env.custom.lab")

    assert registry.require("env.custom.lab").record.title == "Custom Lab"
    assert payload["storage_space"]["environment_storage_root"] == "storage/task_environments/custom/lab"
    assert payload["environment_boundary"]["prompt_refs"] == [
        "runtime.rule.file_management.generic",
        "environment.resource.general_workspace.orientation",
        "environment.custom.lab",
    ]
    assert (
        payload["environment_boundary"]["boundary_contract"]["environment_prompts_source"]
        == "resource_prompt_library_and_task_environment_config"
    )
    assert payload["environment_boundary"]["boundary_contract"]["tool_authority"] == "agent_profile_only"
    assert payload["environment_boundary"]["boundary_contract"]["skill_authority"] == "agent_profile_only"
    assert payload["file_access_tables"]
    assert payload["resource_space"]["storage_namespace"] == "custom/lab"


def test_configured_task_environment_rejects_unknown_flat_fields(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    config_dir = backend_dir / "task_system" / "storage" / "task_environments"
    config_dir.mkdir(parents=True)
    (config_dir / "environments.json").write_text(
        json.dumps(
            {
                "environments": [
                    {
                        "environment_id": "env.bad.unknown",
                        "title": "Bad Unknown",
                        "group_id": "environment_group.general",
                        "unexpected_field": {"value": True},
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    try:
        task_environment_registry_from_backend_dir(backend_dir)
    except TaskEnvironmentConfigError as exc:
        assert "unexpected_field" in str(exc)
    else:
        raise AssertionError("task environment config must reject fields outside the environment schema")


def test_task_environment_repository_persists_upsert_and_delete(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    repository = TaskEnvironmentRepository(backend_dir)

    repository.upsert_group(
        {
            "group_id": "environment_group.custom_repo",
            "title": "Custom Repo",
            "description": "Repository managed environments.",
        }
    )
    repository.upsert_environment(
        {
            "environment_id": "env.custom.repo",
            "title": "Repo Environment",
            "group_id": "environment_group.custom_repo",
            "environment_prompts": [
                {
                    "prompt_id": "environment.custom.repo",
                    "content": "你处在仓库持久化测试环境中。",
                }
            ],
            "file_management": {"file_profile_refs": ["file_profile.general_workspace"]},
            "resource_space": {"storage_namespace": "custom/repo"},
        }
    )

    registry = task_environment_registry_from_backend_dir(backend_dir)
    assert registry.require("env.custom.repo").record.title == "Repo Environment"

    repository.delete_environment("env.custom.repo")
    registry_after_delete = task_environment_registry_from_backend_dir(backend_dir)
    assert registry_after_delete.get("env.custom.repo") is None


def test_task_environment_repository_migrates_deprecated_prompt_refs_on_load(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    config_dir = backend_dir / "task_system" / "storage" / "task_environments"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "environments.json"
    config_path.write_text(
        json.dumps(
            {
                "environments": [
                    {
                        "record": {
                            "environment_id": "env.custom.legacy_prompts",
                            "title": "Legacy Prompt Environment",
                            "group_id": "environment_group.general",
                            "environment_kind": "custom",
                        },
                        "spec": {
                            "spec_id": "envspec.custom.legacy_prompts.v1",
                            "environment_id": "env.custom.legacy_prompts",
                            "environment_prompts": [
                                {"prompt_id": "runtime.rule.file_management.generic.v1"},
                                {"prompt_id": "environment.rule.general_workspace.v1"},
                            ],
                            "file_management": {"file_profile_refs": ["file_profile.general_workspace"]},
                            "resource_space": {"storage_namespace": "custom/legacy-prompts"},
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    _, environments = TaskEnvironmentRepository(backend_dir).load()
    environment = next(item for item in environments if item.record.environment_id == "env.custom.legacy_prompts")

    assert [item.prompt_id for item in environment.spec.environment_prompts] == [
        "runtime.rule.file_management.generic",
        "environment.rule.general_workspace",
    ]
    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    persisted_prompts = persisted["environments"][0]["spec"]["environment_prompts"]
    assert [item["prompt_id"] for item in persisted_prompts] == [
        "runtime.rule.file_management.generic",
        "environment.rule.general_workspace",
    ]


def test_runtime_assembly_can_select_configured_task_environment(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    config_dir = backend_dir / "task_system" / "storage" / "task_environments"
    config_dir.mkdir(parents=True)
    (config_dir / "environments.json").write_text(
        json.dumps(
            {
                "environments": [
                    {
                        "record": {
                            "environment_id": "env.custom.runtime",
                            "title": "Custom Runtime",
                            "group_id": "environment_group.general",
                            "environment_kind": "custom",
                        },
                        "spec": {
                            "spec_id": "envspec.custom.runtime.v1",
                            "environment_id": "env.custom.runtime",
                            "environment_prompts": [
                                {
                                    "prompt_id": "environment.custom.runtime",
                                    "content": "你处在自定义 runtime 环境中。环境只声明边界；可用工具以本轮可见工具列表为准。",
                                }
                            ],
                            "file_management": {
                                "file_profile_refs": ["file_profile.general_workspace"],
                                "required_repository_kinds": ["conversation_artifacts"],
                            },
                            "resource_space": {"storage_namespace": "custom/runtime"},
                            "execution_policy": {
                                "shell_execution_policy": "denied",
                                "browser_execution_policy": "denied",
                                "network_execution_policy": "denied",
                            },
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    profile = SimpleNamespace(
        agent_profile_id="custom-env-agent",
        allowed_operations=("op.model_response",),
        blocked_operations=(),
        metadata={},
    )
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)

    assembly = assemble_runtime(
        backend_dir=backend_dir,
        session_id="session-custom-env",
        turn_id="turn-custom-env",
        agent_invocation_id="agent-invocation-custom-env",
        runtime_contract={"task_environment_id": "env.custom.runtime"},
        model_selection={},
        agent_runtime_profile=profile,
        tool_instances=build_tool_instances(BACKEND_DIR),
        definitions_by_name=index.definitions_by_name,
    ).to_dict()

    environment = dict(assembly.get("task_environment") or {})
    tool_names = {str(item.get("tool_name") or "") for item in list(assembly.get("available_tools") or [])}

    assert environment["environment_id"] == "env.custom.runtime"
    assert environment["storage_space"]["storage_namespace"] == "custom/runtime"
    assert (
        environment["environment_boundary"]["boundary_contract"]["environment_prompts_source"]
        == "resource_prompt_library_and_task_environment_config"
    )
    assert environment["environment_boundary"]["prompt_refs"] == [
        "runtime.rule.file_management.generic",
        "environment.resource.general_workspace.orientation",
        "environment.custom.runtime",
    ]
    assert environment["environment_boundary"]["boundary_contract"]["tool_authority"] == "agent_profile_only"
    assert tool_names == set()


def test_runtime_packet_includes_environment_prompt_boundary_from_configured_environment(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    config_dir = backend_dir / "task_system" / "storage" / "task_environments"
    config_dir.mkdir(parents=True)
    (config_dir / "environments.json").write_text(
        json.dumps(
            {
                "environments": [
                    {
                        "record": {
                            "environment_id": "env.custom.prompted",
                            "title": "Prompted Runtime",
                            "group_id": "environment_group.general",
                            "environment_kind": "custom",
                        },
                        "spec": {
                            "spec_id": "envspec.custom.prompted.v1",
                            "environment_id": "env.custom.prompted",
                            "environment_prompts": [
                                {
                                    "prompt_id": "environment.custom.prompted",
                                    "content": "你处在自定义提示环境中。这里的环境 prompt 来自任务环境配置。",
                                }
                            ],
                            "file_management": {"file_profile_refs": ["file_profile.general_workspace"]},
                            "resource_space": {"storage_namespace": "custom/prompted"},
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    profile = SimpleNamespace(
        agent_profile_id="custom-prompted-agent",
        allowed_operations=("op.model_response",),
        blocked_operations=(),
        metadata={},
    )
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)
    assembly = assemble_runtime(
        backend_dir=backend_dir,
        session_id="session-custom-prompted",
        turn_id="turn-custom-prompted",
        agent_invocation_id="agent-invocation-custom-prompted",
        runtime_contract={"task_environment_id": "env.custom.prompted"},
        model_selection={},
        agent_runtime_profile=profile,
        tool_instances=build_tool_instances(BACKEND_DIR),
        definitions_by_name=index.definitions_by_name,
    )

    packet = RuntimeCompiler().compile_task_execution_packet(
        session_id="session-custom-prompted",
        task_run={
            "task_run_id": "taskrun:custom-prompted",
            "session_id": "session-custom-prompted",
            "task_id": "task:custom-prompted",
            "agent_profile_id": "custom-prompted-agent",
        },
        contract={"user_visible_goal": "验证环境 prompt", "completion_criteria": ["环境 prompt 已装配"]},
        observations=[],
        execution_state={},
        agent_profile_ref="custom-prompted-agent",
        available_tools=assembly.available_tools,
        runtime_assembly=assembly,
        invocation_index=1,
    ).packet
    stable_message = _message_content_with_title(packet, "Task execution environment boundary")
    stable_payload = _payload_after_title(stable_message, "Task execution environment boundary")
    manifest = packet.diagnostics["prompt_manifest"]

    assert manifest["prompt_mount_plan"]["base_prompt_refs"] == [
        "runtime.rule.file_management.generic",
        "environment.resource.general_workspace.orientation",
        "environment.custom.prompted",
    ]
    assert "environment_prompt_refs" not in stable_payload["task_environment"]
    assert "prompt_mount_plan" not in stable_payload["task_environment"]
    assert "environment_prompts" not in stable_payload["task_environment"]
    assert "你处在自定义提示环境中" not in json.dumps(stable_payload, ensure_ascii=False)
    assert (
        stable_payload["task_environment"]["boundary_contract"]["environment_prompts_source"]
        == "resource_prompt_library_and_task_environment_config"
    )


def test_configured_environment_can_reuse_prompt_library_resources(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    PromptLibraryRegistry(backend_dir).upsert_resource(
        PromptResource(
            prompt_id="environment.shared.readonly_workspace.orientation",
            resource_id="environment.shared.readonly_workspace.orientation",
            category="environment",
            subtype="orientation",
            resource_type="environment_prompt",
            title="共享只读工作区导览",
            content="当前环境复用共享只读工作区导览。先读取事实，再报告限制；不要假设可以写入。",
            owner_layer="environment",
            cache_scope="static_environment",
            model_visible=True,
            source_ref="test.shared_environment_prompt",
            version="v1",
            enabled=True,
            status="active",
        )
    )
    config_dir = backend_dir / "task_system" / "storage" / "task_environments"
    config_dir.mkdir(parents=True)
    (config_dir / "environments.json").write_text(
        json.dumps(
            {
                "environments": [
                    {
                        "record": {
                            "environment_id": "env.custom.reused_prompt",
                            "title": "Reused Prompt Runtime",
                            "group_id": "environment_group.general",
                            "environment_kind": "custom",
                        },
                        "spec": {
                            "spec_id": "envspec.custom.reused_prompt.v1",
                            "environment_id": "env.custom.reused_prompt",
                            "environment_prompts": [
                                {"prompt_id": "environment.shared.readonly_workspace.orientation"}
                            ],
                            "file_management": {"file_profile_refs": ["file_profile.general_workspace"]},
                            "resource_space": {"storage_namespace": "custom/reused-prompt"},
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    profile = SimpleNamespace(
        agent_profile_id="custom-reused-prompt-agent",
        allowed_operations=("op.model_response",),
        blocked_operations=(),
        metadata={},
    )
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)
    assembly = assemble_runtime(
        backend_dir=backend_dir,
        session_id="session-custom-reused-prompt",
        turn_id="turn-custom-reused-prompt",
        agent_invocation_id="agent-invocation-custom-reused-prompt",
        runtime_contract={"task_environment_id": "env.custom.reused_prompt"},
        model_selection={},
        agent_runtime_profile=profile,
        tool_instances=build_tool_instances(BACKEND_DIR),
        definitions_by_name=index.definitions_by_name,
    )

    packet = RuntimeCompiler().compile_task_execution_packet(
        session_id="session-custom-reused-prompt",
        task_run={
            "task_run_id": "taskrun:custom-reused-prompt",
            "session_id": "session-custom-reused-prompt",
            "task_id": "task:custom-reused-prompt",
            "agent_profile_id": "custom-reused-prompt-agent",
        },
        contract={"user_visible_goal": "验证复用环境 prompt", "completion_criteria": ["复用 prompt 已装配"]},
        observations=[],
        execution_state={},
        agent_profile_ref="custom-reused-prompt-agent",
        available_tools=assembly.available_tools,
        runtime_assembly=assembly,
        invocation_index=1,
    ).packet
    stable_message = _message_content_with_title(packet, "Task execution environment boundary")
    stable_payload = _payload_after_title(stable_message, "Task execution environment boundary")
    manifest = packet.diagnostics["prompt_manifest"]

    assert manifest["prompt_mount_plan"]["base_prompt_refs"] == [
        "runtime.rule.file_management.generic",
        "environment.resource.general_workspace.orientation",
        "environment.shared.readonly_workspace.orientation",
    ]
    assert "environment_prompt_refs" not in stable_payload["task_environment"]
    assert "prompt_mount_plan" not in stable_payload["task_environment"]
    assert stable_payload["task_environment"]["boundary_contract"]["environment_prompts_source"] == "prompt_library"


def test_runtime_contract_can_select_custom_personality_prompt(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    custom_personality_ref = "personality.user.spark"
    PromptLibraryRegistry(backend_dir).upsert_resource(
        PromptResource(
            prompt_id=custom_personality_ref,
            resource_id=custom_personality_ref,
            category="personality",
            subtype="user",
            resource_type="agent_personality",
            title="Spark custom personality",
            content=(
                "你当前使用用户自定义人格：星火。\n"
                "这个人格只影响称呼和表达风格，不能改变权限、工具、验证、记忆或任务合同。"
            ),
            owner_layer="personality",
            cache_scope="session_stable",
            model_visible=True,
            allowed_invocation_kinds=("single_agent_turn", "task_execution", "tool_observation_followup"),
            source_ref="test.custom_personality",
            version="2026-06-08",
            enabled=True,
            status="active",
            metadata={"authority_scope": "identity_and_style_only", "user_configurable": True},
        )
    )
    profile = next(item for item in default_agent_runtime_profiles() if item.agent_profile_id == "main_interactive_agent")
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)
    assembly = assemble_runtime(
        backend_dir=backend_dir,
        session_id="session-custom-personality",
        turn_id="turn-custom-personality",
        agent_invocation_id="agent-invocation-custom-personality",
        runtime_contract={
            "task_environment_id": "env.general.workspace",
            "personality_prompt_ref": custom_personality_ref,
        },
        model_selection={},
        agent_runtime_profile=profile,
        tool_instances=build_tool_instances(BACKEND_DIR),
        definitions_by_name=index.definitions_by_name,
    )
    packet = RuntimeCompiler(base_dir=backend_dir).compile_single_agent_turn_packet(
        session_id="session-custom-personality",
        turn_id="turn-custom-personality",
        agent_invocation_id="agent-invocation-custom-personality",
        user_message="介绍一下你自己。",
        history=[],
        runtime_assembly=assembly,
    ).packet
    stable_message = _message_content_with_title(packet, "Operating Contract")
    stable_payload = _payload_after_title(stable_message, "Operating Contract")
    model_input = _model_input_text(packet)
    manifest = packet.diagnostics["prompt_manifest"]

    assert assembly.personality_prompt_refs == (custom_personality_ref,)
    assert assembly.personality_prompt_selection["selected_personality_ref"] == custom_personality_ref
    assert assembly.personality_prompt_selection["selection_source"] == "runtime_contract"
    assert "prompt_mount_plan" not in stable_payload["task_environment"]
    assert stable_payload["task_environment"]["prompt_mount_summary"]["personality_prompt_count"] == 1
    assert manifest["prompt_mount_plan"]["personality_prompt_refs"] == [custom_personality_ref]
    assert custom_personality_ref in manifest["stable_prompt_refs"]
    assert DEFAULT_PERSONALITY_PROMPT_REF not in manifest["stable_prompt_refs"]


def _payload_after_title(content: str, title: str) -> dict[str, object]:
    marker = title + "\n"
    assert marker in content
    return json.loads(content.split(marker, 1)[1])


def _message_content_with_title(packet, title: str) -> str:
    marker = title + "\n"
    for message in packet.model_messages:
        content = str(message.get("content") or "")
        if marker in content:
            return content
    raise AssertionError(f"packet message title not found: {title}")


def _payload_from_packet_message(packet, title: str) -> dict[str, object]:
    return _payload_after_title(_message_content_with_title(packet, title), title)

