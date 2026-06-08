from __future__ import annotations

import json
from pathlib import Path

from harness.runtime.action_schema_manifest import build_action_schema_manifest
from harness.runtime.compiler import RuntimeCompiler, task_execution_action_schema


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


def test_action_schema_manifest_renders_legacy_task_execution_payload() -> None:
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
    assert manifest.to_model_visible_payload() == {"schema": schema}


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
