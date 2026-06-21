from __future__ import annotations

import json
from pathlib import Path

from harness.runtime.action_schema_manifest import build_action_schema_manifest
from harness.runtime.compiler import RuntimeCompiler, model_action_request_schema, task_execution_action_schema


def _backend_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def _payload_after_title(content: str, title: str) -> dict[str, object]:
    text = str(content or "")
    assert text.startswith(title + "\n")
    return json.loads(text.split("\n", 1)[1])


def _message_payload_with_title(packet, title: str) -> dict[str, object]:
    for message in packet.model_messages:
        content = str(dict(message).get("content") or "")
        if content.startswith(title + "\n"):
            return _payload_after_title(content, title)
    raise AssertionError(f"missing model message title: {title}")


def test_action_schema_manifest_renders_task_execution_model_visible_payload() -> None:
    schema = task_execution_action_schema()
    manifest = build_action_schema_manifest(
        invocation_kind="task_execution",
        schema=schema,
        source_ref="task_execution_action_schema",
    )

    assert manifest.invocation_kind == "task_execution"
    assert manifest.source_ref == "task_execution_action_schema"
    assert manifest.schema_hash.startswith("sha256:")
    assert manifest.allowed_action_types == ("respond", "ask_user", "tool_call", "block")
    assert "必须回应用户当前输入本身" in str(schema["public_response_obligation"]["rule"])
    assert "must_explain_when" in schema["public_response_obligation"]["tool_observation_reporting"]
    assert manifest.to_model_visible_payload() == {"schema": schema}


def test_action_schemas_keep_long_running_observation_feedback_obligation() -> None:
    single_turn_schema = model_action_request_schema("turn:feedback-obligation")
    task_schema = task_execution_action_schema()

    for schema in (single_turn_schema, task_schema):
        reporting = schema["public_response_obligation"]["tool_observation_reporting"]
        assert any("多个工具批次" in item for item in reporting["must_explain_when"])
        assert any("失败恢复、写入、验证" in item for item in reporting["must_explain_when"])
        assert any("短链路" in item for item in reporting["may_keep_internal_when"])
        assert "不允许长时间任务只剩工具列表" in reporting["explanation_shape"]


def test_single_turn_request_task_run_schema_shows_nested_contract_shape() -> None:
    schema = model_action_request_schema("turn:request-task-run-shape")

    shape_rules = [str(item) for item in list(schema.get("request_task_run_shape_rules") or [])]
    example = dict(schema.get("minimal_valid_request_task_run_example") or {})
    seed = dict(example.get("task_contract_seed") or {})

    assert any("不要使用 payload" in rule for rule in shape_rules)
    assert any("必须放在 task_contract_seed 内" in rule for rule in shape_rules)
    assert any("provider-native canonical request_task_run" in rule for rule in shape_rules)
    assert any("不要写 selected_groups" in rule for rule in shape_rules)
    assert "capability_intent" not in example
    assert "skill_intent" not in example
    assert "observation_contract" not in example
    assert "capability_intent" in seed
    assert "skill_intent" in seed
    assert "observation_contract" in seed
    assert dict(seed["capability_intent"])["needed_capability_groups"] == ["file_work"]
    assert dict(seed["observation_contract"])["evidence_policy"] == "observation_required"


def test_single_turn_active_work_control_contract_exposes_canonical_control_fields() -> None:
    result = RuntimeCompiler(base_dir=_backend_dir()).compile_single_agent_turn_packet(
        session_id="session:active-work-control-shape",
        turn_id="turn:active-work-control-shape",
        agent_invocation_id="aginvoke:active-work-control-shape",
        user_message="继续当前任务。",
        history=[],
        active_work_context={
            "session_id": "session:active-work-control-shape",
            "active_work_id": "turn:active",
            "task_run_id": "taskrun:active-work-control-shape",
            "status": "waiting_executor",
            "resumable": True,
        },
        current_work_boundary_receipt={
            "receipt_id": "cwreceipt:active-work-control-shape",
            "boundary_decision": "current_work_control_required",
            "observation_state": "controllable_current_work",
            "active_work_ref": {"task_run_id": "taskrun:active-work-control-shape", "actual_active_turn_id": "turn:active"},
            "operation_availability": {"active_work_control": True},
            "authority": "harness.entrypoint.current_work_boundary_receipt",
        },
        runtime_assembly={
            "profile": {"mode": "conversation"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "control_capabilities": {"may_request_task_run": True, "may_control_active_work": True},
        },
    )

    control_actions = dict(result.packet.output_contract.get("control_actions") or {})
    active_work = dict(control_actions.get("active_work_control") or {})
    payload_schema = dict(active_work.get("payload_schema") or {})

    assert payload_schema["relation_to_current_work"].startswith("current_work")
    assert "turn_response_policy" in payload_schema
    assert "user_turn_kind" in payload_schema
    assert "answer_obligation" in payload_schema
    assert "evidence" in payload_schema
    assert "resume_strategy" not in payload_schema
    assert "response_obligation" not in payload_schema
    assert "routing_evidence" not in payload_schema


def test_single_turn_resume_recoverable_work_schema_shows_nested_handle_shape() -> None:
    schema = model_action_request_schema("turn:resume-shape")

    shape_rules = [str(item) for item in list(schema.get("resume_recoverable_work_shape_rules") or [])]
    example = dict(schema.get("minimal_valid_resume_recoverable_work_example") or {})
    recovery_resume = dict(example.get("recovery_resume") or {})

    assert "resume_recoverable_work" in str(schema.get("action_type") or "")
    assert any("provider-native canonical resume_recoverable_work" in rule for rule in shape_rules)
    assert any("必须放在 recovery_resume 对象内" in rule for rule in shape_rules)
    assert "task_run_id" not in example
    assert "continuation_id" not in example
    assert recovery_resume["task_run_id"].startswith("taskrun:")
    assert recovery_resume["continuation_id"].startswith("cont:")


def test_task_execution_packet_attaches_action_schema_manifest_without_prompt_drift() -> None:
    result = RuntimeCompiler(base_dir=_backend_dir()).compile_task_execution_packet(
        session_id="session:action-schema-manifest",
        task_run={"task_run_id": "taskrun:action-schema-manifest", "diagnostics": {"executor_status": "running"}},
        contract={"task_run_goal": "Validate action schema manifest", "completion_criteria": ["manifest attached"]},
        observations=[],
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    packet = result.packet
    action_payload = _message_payload_with_title(packet, "Task execution action schema")
    action_segment = next(
        segment
        for segment in list(packet.segment_plan.get("segments") or [])
        if dict(segment).get("kind") == "action_schema_static"
    )
    prompt_manifest = dict(packet.diagnostics["prompt_manifest"])

    assert action_payload == {"schema": packet.action_schema_manifest["schema"]}
    assert action_payload["schema"] == packet.output_contract["schema"]
    assert action_segment["source_ref"] == packet.action_schema_manifest["source_ref"]
    assert prompt_manifest["action_schema_manifest"] == packet.action_schema_manifest
    assert packet.diagnostics["action_schema_manifest"] == packet.action_schema_manifest
    assert packet.action_schema_manifest["schema_hash"].startswith("sha256:")


def test_single_agent_turn_does_not_attach_task_action_schema_manifest() -> None:
    result = RuntimeCompiler(base_dir=_backend_dir()).compile_single_agent_turn_packet(
        session_id="session:action-schema-single",
        turn_id="turn:action-schema-single",
        agent_invocation_id="aginvoke:action-schema-single",
        user_message="Answer briefly.",
        history=[],
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    packet = result.packet
    prompt_manifest = dict(packet.diagnostics["prompt_manifest"])

    assert packet.action_schema_manifest == {}
    assert "action_schema_manifest" not in prompt_manifest
    assert "action_schema_manifest" not in packet.diagnostics
