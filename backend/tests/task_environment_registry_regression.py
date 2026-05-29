from __future__ import annotations

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
    development_prompt = "\n".join(item.content for item in development.environment_prompts)
    assert "优先使用 search_text、search_files、glob_paths、read_file、list_dir" in development_prompt
    assert "sandbox overlay" in development_prompt
    assert "old_text not found" in development_prompt

    assert "file_profile.writing_manuscript" in writing.file_management.file_profile_refs
    assert writing.resource_space.storage_namespace == "creation/writing"
    assert writing.file_management.constraints["official_work_canonical_write"] == "ask"
    assert writing.artifact_policy.artifact_root == "repo.writing.artifact_repository"

    assert general.sandbox_policy.shell_policy == "denied"
    assert general.execution_policy.shell_execution_policy == "denied"


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
    assert decisions["op.shell"]["environment_constraint"] == "sandboxed"


def test_runtime_available_tools_expose_canonical_tool_input_schema() -> None:
    profile = next(item for item in default_agent_runtime_profiles() if item.agent_profile_id == "main_interactive_agent")
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)

    assembly = assemble_runtime(
        backend_dir=BACKEND_DIR,
        session_id="session-tool-schema",
        turn_id="turn-tool-schema",
        agent_invocation_id="agent-invocation-tool-schema",
        request_task_selection={"runtime_mode": "professional", "task_environment_id": "env.development.sandbox"},
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
        engagement_plans=[
            {
                "plan_id": "engage.test.writing",
                "task_environment_id": "env.creation.writing",
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
    assert "file_access_tables" in development
    assert development["storage_space"]["task_library_root"] == "storage/task_environments/development/sandbox/task_library"
    assert writing_item["task_library"]["engagement_plan_ids"] == ["engage.test.writing"]
    assert writing_item["task_library"]["task_ids"] == ["engage.test.writing"]


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
    assert decisions["op.shell"]["environment_constraint"] == "denied"


def test_runtime_compiler_stable_payload_keeps_environment_and_operation_projection_only() -> None:
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
    stable_message = packet.model_messages[1]["content"]
    stable_payload = json.loads(stable_message.split("\n", 1)[1])

    assert "task_environment" in stable_payload
    assert "storage_space" in stable_payload["task_environment"]
    assert "environment_boundary" in stable_payload["task_environment"]
    assert "operation_authorization" in stable_payload
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
                                    "prompt_id": "environment.custom.lab.v1",
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
    assert payload["environment_prompts"][0]["content"].startswith("你处在自定义实验环境中")
    assert payload["environment_boundary"]["prompt_refs"] == ["environment.custom.lab.v1"]
    assert payload["environment_boundary"]["boundary_contract"]["environment_prompts_source"] == "task_environment_config"
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
                    "prompt_id": "environment.custom.repo.v1",
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
                                    "prompt_id": "environment.custom.runtime.v1",
                                    "content": "你处在自定义 runtime 环境中。环境只声明边界，不授予工具。",
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
        enabled_runtime_modes=("professional",),
        default_runtime_mode="professional",
        allowed_operations=("op.model_response",),
        blocked_operations=(),
        can_delegate_to_agents=False,
        max_delegate_calls_per_turn=0,
        allowed_delegate_agent_ids=(),
        metadata={},
    )
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)

    assembly = assemble_runtime(
        backend_dir=backend_dir,
        session_id="session-custom-env",
        turn_id="turn-custom-env",
        agent_invocation_id="agent-invocation-custom-env",
        request_task_selection={"runtime_mode": "professional", "task_environment_id": "env.custom.runtime"},
        model_selection={},
        agent_runtime_profile=profile,
        tool_instances=build_tool_instances(BACKEND_DIR),
        definitions_by_name=index.definitions_by_name,
    ).to_dict()

    environment = dict(assembly.get("task_environment") or {})
    tool_names = {str(item.get("tool_name") or "") for item in list(assembly.get("available_tools") or [])}

    assert environment["environment_id"] == "env.custom.runtime"
    assert environment["storage_space"]["storage_namespace"] == "custom/runtime"
    assert environment["environment_boundary"]["boundary_contract"]["environment_prompts_source"] == "task_environment_config"
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
                                    "prompt_id": "environment.custom.prompted.v1",
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
        enabled_runtime_modes=("professional",),
        default_runtime_mode="professional",
        allowed_operations=("op.model_response",),
        blocked_operations=(),
        can_delegate_to_agents=False,
        max_delegate_calls_per_turn=0,
        allowed_delegate_agent_ids=(),
        metadata={},
    )
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)
    assembly = assemble_runtime(
        backend_dir=backend_dir,
        session_id="session-custom-prompted",
        turn_id="turn-custom-prompted",
        agent_invocation_id="agent-invocation-custom-prompted",
        request_task_selection={"runtime_mode": "professional", "task_environment_id": "env.custom.prompted"},
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
    stable_payload = json.loads(packet.model_messages[1]["content"].split("\n", 1)[1])

    assert "你处在自定义提示环境中" in packet.system_instructions
    assert stable_payload["task_environment"]["environment_boundary"]["prompt_refs"] == ["environment.custom.prompted.v1"]
    assert stable_payload["runtime_context"]["environment_boundary"]["environment_prompts_source"] == "task_environment_config"
