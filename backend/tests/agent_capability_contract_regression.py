from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from agent_system.profiles.runtime_profile_registry import default_agent_runtime_profiles
from capability_system.tools.authorization import build_tool_authorization_index
from capability_system.tools.native_tool_catalog import build_tool_instances, get_tool_definitions
from harness.loop.task_executor import _duplicate_read_only_tool_call_observation, _observations_for_packet
from harness.runtime import RuntimeCompiler, assemble_runtime
from harness.runtime.tool_catalog_manifest import build_tool_catalog_manifest
from prompt_library.environment_lifecycle_prompts import list_builtin_environment_lifecycle_prompt_resources
from prompt_library.rules import list_builtin_prompt_rule_resources
from prompt_library.tool_prompts import _TOOL_GUIDANCE_REFS_BY_NAME, list_builtin_tool_prompt_resources
from tests.support.runtime_stubs import build_harness_runtime

_TOOL_GUIDANCE_DEFAULTS = {key: key for refs in _TOOL_GUIDANCE_REFS_BY_NAME.values() for key in refs}


def _message_payload_for_segment_kind(packet, kind: str) -> dict[str, object]:
    segment = next(
        item
        for item in list(packet.segment_plan.get("segments") or [])
        if dict(item).get("kind") == kind
    )
    message_index = int(dict(segment).get("model_message_index") or 0)
    content = str(dict(packet.model_messages[message_index]).get("content") or "")
    json_start = content.find("{")
    assert json_start >= 0
    return json.loads(content[json_start:])


def _main_profile_with_alias_subagents():
    profile = next(item for item in default_agent_runtime_profiles() if item.agent_profile_id == "main_interactive_agent")
    return replace(
        profile,
        subagent_policy=replace(
            profile.subagent_policy,
            allowed_subagent_ids=("agent.codebase_searcher", "agent.verifier"),
        ),
    )


def _assembled_runtime_with_real_tools(runtime_contract: dict[str, object] | None = None) -> dict[str, object]:
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)
    return assemble_runtime(
        backend_dir=BACKEND_DIR,
        session_id="session:agent-capability-contract",
        turn_id="turn:agent-capability-contract",
        agent_invocation_id="aginvoke:agent-capability-contract",
        runtime_contract={"task_environment_id": "env.coding.vibe_workspace", **dict(runtime_contract or {})},
        model_selection={},
        agent_runtime_profile=_main_profile_with_alias_subagents(),
        tool_instances=build_tool_instances(BACKEND_DIR),
        definitions_by_name=index.definitions_by_name,
    ).to_dict()


def test_task_runtime_boundary_projects_canonical_allowed_subagent_ids() -> None:
    assembly = _assembled_runtime_with_real_tools()
    allowed_ids = dict(dict(assembly["profile"])["subagent_policy"])["allowed_subagent_ids"]

    packet = RuntimeCompiler(base_dir=BACKEND_DIR).compile_task_execution_packet(
        session_id="session:agent-capability-contract",
        task_run={"task_run_id": "taskrun:agent-capability-contract", "diagnostics": {"executor_status": "running"}},
        contract={"task_run_goal": "Verify subagent boundary", "completion_criteria": ["canonical ids visible"]},
        observations=[],
        available_tools=assembly["available_tools"],
        runtime_assembly=assembly,
    ).packet
    boundary = _message_payload_for_segment_kind(packet, "task_runtime_boundary_dynamic")
    boundary_segment = next(
        item
        for item in list(packet.segment_plan.get("segments") or [])
        if dict(item).get("kind") == "task_runtime_boundary_dynamic"
    )
    tool_boundary = boundary["runtime_context"]["tool_boundary"]

    assert boundary_segment["cache_scope"] == "none"
    assert boundary_segment["cache_role"] == "volatile"
    assert allowed_ids == ["agent:codebase_searcher", "agent:verifier"]
    assert tool_boundary["allowed_subagent_ids"] == ["agent:codebase_searcher", "agent:verifier"]
    assert "codebase_searcher" not in tool_boundary["allowed_subagent_ids"]


def test_capability_directory_projects_contract_requested_groups_and_candidate_skills() -> None:
    assembly = _assembled_runtime_with_real_tools(
        {
            "capability_intent": {
                "needed_capability_groups": ["file_work"],
                "preferred_tool_namespaces": ["file_work"],
                "reason": "需要读取项目文件。",
            }
        }
    )
    directory = dict(assembly["capability_directory"])
    groups = {
        str(item.get("group_id") or ""): dict(item)
        for item in list(directory.get("capability_groups") or [])
    }
    file_work = groups["file_work"]
    tools = {str(item.get("tool_name") or "") for item in list(file_work.get("candidate_tools") or [])}
    skills = {str(item.get("skill_id") or "") for item in list(file_work.get("candidate_skills") or [])}

    assert "file_work" in directory["requested_capability_groups"]
    assert file_work["contract_requested"] is True
    assert "read_file" in tools
    assert "skill.skill-creator" in skills
    assert directory["skill_selection_available"] is True


def test_active_skill_body_is_dynamic_and_excluded_from_task_cache_prefix() -> None:
    assembly = _assembled_runtime_with_real_tools(
        {
            "capability_intent": {
                "needed_capability_groups": ["general_task"],
                "reason": "需要读取 PDF skill 的完整说明。",
            },
            "skill_activation": {
                "selected_skill_ids": ["skill.pdf-analysis"],
                "selection_source": "model_action",
                "selection_reason": "测试激活 skill。",
            },
        }
    )
    packet = RuntimeCompiler(base_dir=BACKEND_DIR).compile_task_execution_packet(
        session_id="session:agent-capability-contract",
        task_run={"task_run_id": "taskrun:agent-capability-contract", "diagnostics": {"executor_status": "running"}},
        contract={"task_run_goal": "Verify active skill cache boundary", "completion_criteria": ["skill body dynamic"]},
        observations=[],
        available_tools=assembly["available_tools"],
        runtime_assembly=assembly,
    ).packet
    active_segment = next(
        item
        for item in list(packet.segment_plan.get("segments") or [])
        if dict(item).get("kind") == "active_skills"
    )
    assert active_segment["cache_scope"] == "none"
    assert active_segment["cache_role"] == "volatile"


def test_tool_catalog_exposes_todo_subagent_and_io_schema_contracts() -> None:
    assembly = _assembled_runtime_with_real_tools()
    manifest = build_tool_catalog_manifest(
        invocation_kind="task_execution",
        tool_payloads=assembly["available_tools"],
        source_ref="task_execution.available_tools",
        tool_guidance_prompt_defaults=_TOOL_GUIDANCE_DEFAULTS,
    )
    tools = {
        str(item.get("tool_name") or ""): dict(item)
        for item in manifest.to_model_visible_payload(include_catalog_hash=True)["available_tools"]
    }

    todo_summary = dict(tools["agent_todo"]["input_schema_summary"])
    todo_fields = dict(todo_summary["field_paths"])
    todo_contract = dict(tools["agent_todo"]["tool_contract_summary"])
    assert todo_fields["items[].status"]["enum"] == ["pending", "in_progress", "completed"]
    assert todo_fields["status"]["enum"] == ["", "pending", "in_progress", "completed"]
    assert "active" not in todo_fields["items[].status"]["enum"]
    assert todo_contract["critical_fields"]["todo_id"]["type"] == "string"
    assert "id" in todo_contract["forbidden_fields"]

    spawn_contract = dict(tools["spawn_subagent"]["tool_contract_summary"])
    assert tools["spawn_subagent"]["input_schema_summary"]["required"] == ["target_agent_id", "goal"]
    assert "allowed_subagent_ids" in spawn_contract["runtime_constraint"]

    write_contract = dict(tools["write_file"]["tool_contract_summary"])
    assert write_contract["critical_fields"]["allow_overwrite"]["default"] is False
    assert tools["write_file"]["input_schema_summary"]["additionalProperties"] is False

    read_contract = dict(tools["read_file"]["tool_contract_summary"])
    assert read_contract["critical_fields"]["read_intent"]["enum"] == [
        "edit_target",
        "verify_behavior",
        "understand_api",
        "locate_symbol",
        "inspect_dependency",
        "recover_failure",
    ]

    search_contract = dict(tools["search_text"]["tool_contract_summary"])
    assert search_contract["critical_fields"]["output_mode"]["enum"] == ["content", "files_with_matches", "count"]
    assert "recommended_read_windows" in search_contract["output_facts"]


def test_prompt_contracts_do_not_teach_todo_active_or_bare_subagent_ids() -> None:
    contents = "\n".join(
        [
            *(resource.content for resource in list_builtin_tool_prompt_resources()),
            *(resource.content for resource in list_builtin_environment_lifecycle_prompt_resources()),
            *(resource.content for resource in list_builtin_prompt_rule_resources()),
        ]
    )

    assert "active 项" not in contents
    assert "status: active" not in contents
    assert '"status": "active"' not in contents
    assert "todo_id" in contents
    assert "allowed_subagent_ids" in contents
    assert "agent:codebase_searcher" in contents
    assert "agent:web_researcher" in contents
    assert " codebase_searcher " not in contents
    assert " web_researcher " not in contents


def test_exploration_advisory_and_read_resource_state_remain_non_deciding_facts() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:agent-capability-exploration"
    fingerprint = {
        "tool_registry_hash": "tools-v1",
        "tool_config_hash": "tool-config-v1",
        "sandbox_policy_hash": "sandbox-v1",
        "permission_policy_hash": "permission-v1",
        "backend_config_hash": "backend-v1",
    }
    tool_calls = [
        ("list_dir", {"path": "."}),
        ("search_text", {"query": "runtime", "roots": ["backend/harness"]}),
        ("glob_paths", {"pattern": "backend/**/*.py"}),
        ("read_file", {"path": "backend/harness/runtime/compiler.py"}),
        ("search_files", {"query": "subagent"}),
        ("read_file", {"path": "backend/harness/loop/task_executor.py"}),
    ]
    for index, (tool_name, tool_args) in enumerate(tool_calls, start=1):
        host.event_log.append(
            task_run_id,
            "task_tool_observation_recorded",
            payload={
                "observation": {
                    "observation_id": f"obs:agent-capability:{index}",
                    "task_run_id": task_run_id,
                    "observation_type": "tool_result",
                    "source": f"tool:{tool_name}",
                    "payload": {
                        "tool_name": tool_name,
                        "tool_args": tool_args,
                        "result": f"{tool_name} ok",
                        "runtime_fingerprint": fingerprint,
                    },
                }
            },
        )

    advisory = _observations_for_packet(
        host,
        task_run_id,
        current_fingerprint=fingerprint,
    )["execution_state"]["system_projection"]["exploration_advisory"]
    advisory_text = json.dumps(advisory, ensure_ascii=False)

    assert advisory["authority_boundary"] == "observation_pattern_only"
    assert advisory["non_blocking"] is True
    assert "recommended_action" not in advisory
    assert "codebase_searcher" not in advisory_text
    assert "edit_readiness" not in advisory_text
    assert "stop_read" not in advisory_text


def test_duplicate_read_only_guard_stops_empty_identical_read_dispatch_after_contract_failures() -> None:
    previous_observations = [
        {
            "observation_id": f"obs:read-repeat:{index}",
            "source": "tool:read_file",
            "payload": {
                "tool_name": "read_file",
                "tool_args": {"path": "backend/harness/loop/task_executor.py", "start_line": 1, "line_count": 240},
                "result_envelope": {"tool_name": "read_file", "status": "ok"},
            },
        }
        for index in range(5)
    ]
    previous_observations.extend(
        [
            {
                "observation_id": "obs:todo-schema-failed",
                "source": "tool:agent_todo",
                "payload": {"error": "tool_input_schema_validation_failed", "tool_name": "agent_todo"},
                "error": "tool_input_schema_validation_failed",
            },
            {
                "observation_id": "obs:subagent-denied",
                "source": "tool:spawn_subagent",
                "payload": {"error": "target_subagent_not_allowed", "tool_name": "spawn_subagent"},
                "error": "target_subagent_not_allowed",
            },
        ]
    )

    observation = _duplicate_read_only_tool_call_observation(
        task_run_id="taskrun:agent-capability-duplicate-read",
        packet_ref="packet:duplicate-read",
        action_request=SimpleNamespace(
            request_id="action:duplicate-read",
            tool_call={"tool_name": "read_file", "args": {"path": "backend/harness/loop/task_executor.py"}},
        ),
        previous_observations=previous_observations,
        runtime_fingerprint={"tool_registry_hash": "tools-v1"},
    )

    assert observation is not None
    payload = dict(observation["payload"])
    assert payload["error_code"] == "duplicate_read_only_tool_call"
    assert payload["structured_error"]["origin"] == "runtime_guard"
    assert payload["structured_error"]["tool_name"] == "read_file"
    assert payload["previous_observation_refs"] == [f"obs:read-repeat:{index}" for index in range(5)]
