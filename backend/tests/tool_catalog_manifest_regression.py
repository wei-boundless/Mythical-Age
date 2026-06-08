from __future__ import annotations

import json
from pathlib import Path

from harness.runtime.compiler import RuntimeCompiler
from harness.runtime.tool_catalog_manifest import build_tool_catalog_manifest


def _backend_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def _tools() -> list[dict[str, object]]:
    return [
        {
            "tool_name": "read_file",
            "operation_id": "op.read_file",
            "prompt_exposure_policy": "schema_plus_guidance",
            "required_inputs": ["path"],
            "owner_scope": "workspace",
            "read_only": True,
            "input_schema": {
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "encoding": {"type": "string", "default": "utf-8"},
                },
            },
        }
    ]


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


def test_tool_catalog_manifest_renders_legacy_model_visible_payload() -> None:
    manifest = build_tool_catalog_manifest(
        invocation_kind="task_execution",
        tool_payloads=_tools(),
        source_ref="task_execution.available_tools",
    )

    payload = manifest.to_model_visible_payload(include_catalog_hash=True)
    tool = payload["available_tools"][0]

    assert manifest.raw_tool_count == 1
    assert manifest.visible_tool_count == 1
    assert manifest.tool_names == ("read_file",)
    assert payload["tool_catalog_hash"] == manifest.tool_catalog_hash
    assert payload["tool_guidance_refs"] == ["tool.guidance.read_file"]
    assert "input_schema" not in tool
    assert tool["input_schema_ref"].startswith("sha256:")
    assert tool["input_schema_summary"]["properties"]["path"] == "string"
    assert tool["input_schema_summary"]["properties"]["encoding"] == 'string default="utf-8"'
    assert tool["input_schema_summary"]["required"] == ["path"]
    assert manifest.to_model_visible_payload(include_catalog_hash=False).get("tool_catalog_hash") is None


def test_single_agent_turn_attaches_tool_catalog_manifest_without_rendering_hash() -> None:
    result = RuntimeCompiler(base_dir=_backend_dir()).compile_single_agent_turn_packet(
        session_id="session:tool-catalog-single",
        turn_id="turn:tool-catalog-single",
        agent_invocation_id="aginvoke:tool-catalog-single",
        user_message="Answer briefly.",
        history=[],
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "available_tools": _tools(),
        },
    )

    packet = result.packet
    stable_payload = _message_payload_with_title(packet, "Single agent turn stable boundary")
    prompt_manifest = dict(packet.diagnostics["prompt_manifest"])

    assert "tool_catalog_hash" not in stable_payload
    assert stable_payload["available_tools"] == packet.tool_catalog_manifest["model_visible_catalog"]
    assert prompt_manifest["tool_catalog_manifest"] == packet.tool_catalog_manifest
    assert packet.diagnostics["tool_catalog_manifest"] == packet.tool_catalog_manifest


def test_task_execution_tool_index_uses_tool_catalog_manifest_payload() -> None:
    tools = _tools()
    result = RuntimeCompiler(base_dir=_backend_dir()).compile_task_execution_packet(
        session_id="session:tool-catalog-task",
        task_run={"task_run_id": "taskrun:tool-catalog-task", "diagnostics": {"executor_status": "running"}},
        contract={"task_run_goal": "Validate tool catalog manifest", "completion_criteria": ["manifest attached"]},
        observations=[],
        available_tools=tools,
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    packet = result.packet
    expected = build_tool_catalog_manifest(
        invocation_kind="task_execution",
        tool_payloads=tools,
        source_ref="task_execution.available_tools",
    ).to_model_visible_payload(include_catalog_hash=True)
    tool_index_payload = _message_payload_with_title(packet, "Task execution tool index")
    tool_segment = next(
        segment
        for segment in list(packet.segment_plan.get("segments") or [])
        if dict(segment).get("kind") == "tool_index_stable"
    )

    assert tool_index_payload == expected
    assert packet.tool_catalog_manifest["tool_catalog_hash"] == expected["tool_catalog_hash"]
    assert dict(packet.diagnostics["prompt_manifest"])["tool_catalog_manifest"] == packet.tool_catalog_manifest
    assert str(tool_segment.get("source_ref") or "").startswith("sha256:")


def test_observation_followup_stable_contract_uses_tool_catalog_manifest_payload() -> None:
    result = RuntimeCompiler(base_dir=_backend_dir()).compile_observation_followup_packet(
        session_id="session:tool-catalog-observation",
        turn_id="turn:tool-catalog-observation",
        agent_invocation_id="aginvoke:tool-catalog-observation",
        user_message="Continue.",
        history=[],
        observations=[{"observation_id": "obs:1", "payload": {"status": "ok"}}],
        available_tools=_tools(),
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    packet = result.packet
    stable_payload = _message_payload_with_title(packet, "Observation followup stable contract")

    assert stable_payload["tool_catalog_hash"] == packet.tool_catalog_manifest["tool_catalog_hash"]
    assert stable_payload["available_tools"] == packet.tool_catalog_manifest["model_visible_catalog"]
    assert dict(packet.diagnostics["prompt_manifest"])["tool_catalog_manifest"] == packet.tool_catalog_manifest
