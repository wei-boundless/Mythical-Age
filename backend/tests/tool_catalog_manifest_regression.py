from __future__ import annotations

import json
from pathlib import Path

from harness.runtime.compiler import RuntimeCompiler
from harness.runtime.tool_catalog_manifest import build_tool_catalog_manifest
from harness.runtime.tool_plan import build_runtime_tool_plan
from prompt_library.tool_prompts import _TOOL_GUIDANCE_REFS_BY_NAME
from runtime.model_gateway.model_request import ModelRequestBuilder

_TOOL_GUIDANCE_DEFAULTS = {key: key for refs in _TOOL_GUIDANCE_REFS_BY_NAME.values() for key in refs}


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


def _provider_tools() -> list[dict[str, object]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file",
                "parameters": _tools()[0]["input_schema"],
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
        tool_guidance_prompt_defaults=_TOOL_GUIDANCE_DEFAULTS,
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


def test_tool_catalog_manifest_drops_hidden_and_debug_tools() -> None:
    manifest = build_tool_catalog_manifest(
        invocation_kind="task_execution",
        tool_payloads=[
            *_tools(),
            {
                "tool_name": "python_repl",
                "operation_id": "op.python_repl",
                "prompt_exposure_policy": "hidden",
            },
            {
                "tool_name": "debug_probe",
                "operation_id": "op.debug_probe",
                "prompt_exposure_policy": "debug_only",
            },
        ],
        source_ref="task_execution.available_tools",
        tool_guidance_prompt_defaults=_TOOL_GUIDANCE_DEFAULTS,
    )
    payload = manifest.to_model_visible_payload(include_catalog_hash=True)
    tool_names = {str(item.get("tool_name") or "") for item in payload["available_tools"]}

    assert manifest.raw_tool_count == 3
    assert manifest.visible_tool_count == 1
    assert tool_names == {"read_file"}
    assert payload["tool_guidance_refs"] == ["tool.guidance.read_file"]


def test_single_agent_turn_renders_stable_tool_index_for_provider_cache() -> None:
    tools = _tools()
    runtime_assembly = {
        "profile": {
            "profile_ref": "main_interactive_agent",
            "prompt_policy": {"tool_guidance_prompt_defaults": _TOOL_GUIDANCE_DEFAULTS},
        },
        "task_environment": {"environment_id": "env.general.workspace"},
        "available_tools": tools,
    }
    result = RuntimeCompiler(base_dir=_backend_dir()).compile_single_agent_turn_packet(
        session_id="session:tool-catalog-single",
        turn_id="turn:tool-catalog-single",
        agent_invocation_id="aginvoke:tool-catalog-single",
        user_message="Answer briefly.",
        history=[],
        runtime_assembly=runtime_assembly,
    )

    packet = result.packet
    stable_payload = _message_payload_with_title(packet, "Single agent turn stable boundary")
    tool_plan = build_runtime_tool_plan(
        runtime_assembly=runtime_assembly,
        invocation_kind="single_agent_turn",
        tool_definitions_by_name={},
    )
    expected = build_tool_catalog_manifest(
        invocation_kind="single_agent_turn",
        tool_payloads=tool_plan.model_visible_tools,
        source_ref="runtime_assembly.available_tools",
        tool_guidance_prompt_defaults=_TOOL_GUIDANCE_DEFAULTS,
    ).to_model_visible_payload(include_catalog_hash=True)
    tool_index_payload = _message_payload_with_title(packet, "Single agent turn tool index")
    tool_segment = next(
        segment
        for segment in list(packet.segment_plan.get("segments") or [])
        if dict(segment).get("kind") == "tool_index_stable"
    )
    prompt_manifest = dict(packet.diagnostics["prompt_manifest"])

    assert "tool_catalog_hash" not in stable_payload
    assert "available_tools" not in stable_payload
    assert tool_index_payload == expected
    assert packet.tool_catalog_manifest["tool_catalog_hash"] == expected["tool_catalog_hash"]
    assert str(tool_segment.get("source_ref") or "").startswith("sha256:")
    assert prompt_manifest["tool_catalog_manifest"] == packet.tool_catalog_manifest
    assert packet.diagnostics["tool_catalog_manifest"] == packet.tool_catalog_manifest


def test_single_agent_turn_model_request_promotes_matching_tool_schema() -> None:
    result = RuntimeCompiler(base_dir=_backend_dir()).compile_single_agent_turn_packet(
        session_id="session:tool-catalog-single-model-request",
        turn_id="turn:tool-catalog-single-model-request",
        agent_invocation_id="aginvoke:tool-catalog-single-model-request",
        user_message="Answer briefly.",
        history=[],
        runtime_assembly={
            "profile": {
                "profile_ref": "main_interactive_agent",
                "prompt_policy": {"tool_guidance_prompt_defaults": _TOOL_GUIDANCE_DEFAULTS},
            },
            "task_environment": {"environment_id": "env.general.workspace"},
            "available_tools": _tools(),
        },
    )

    packet = result.packet
    model_request = ModelRequestBuilder().build(
        request_id="modelreq:tool-catalog-single-model-request",
        messages=packet.model_messages,
        tools=_provider_tools(),
        provider="deepseek",
        model="deepseek-v4-pro",
        segment_plan=packet.segment_plan,
        metadata={"prompt_manifest": dict(packet.diagnostics["prompt_manifest"])},
    )
    provider_tool_segment = next(
        segment
        for segment in model_request.provider_payload_manifest.segments
        if segment.transport_location == "tools"
    )

    assert model_request.tool_catalog_manifest == packet.tool_catalog_manifest
    assert provider_tool_segment.cache_role == "session_stable"
    assert provider_tool_segment.prefix_tier == "session"
    assert provider_tool_segment.metadata["tool_schema_cache_decision"] == "derived_from_tool_catalog_manifest"
    assert provider_tool_segment.metadata["tool_catalog_manifest_ref"] == packet.tool_catalog_manifest["manifest_id"]


def test_task_execution_tool_index_uses_tool_catalog_manifest_payload() -> None:
    tools = _tools()
    result = RuntimeCompiler(base_dir=_backend_dir()).compile_task_execution_packet(
        session_id="session:tool-catalog-task",
        task_run={"task_run_id": "taskrun:tool-catalog-task", "diagnostics": {"executor_status": "running"}},
        contract={"task_run_goal": "Validate tool catalog manifest", "completion_criteria": ["manifest attached"]},
        observations=[],
        available_tools=tools,
        runtime_assembly={
            "profile": {
                "profile_ref": "main_interactive_agent",
                "prompt_policy": {"tool_guidance_prompt_defaults": _TOOL_GUIDANCE_DEFAULTS},
            },
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    packet = result.packet
    expected = build_tool_catalog_manifest(
        invocation_kind="task_execution",
        tool_payloads=tools,
        source_ref="task_execution.available_tools",
        tool_guidance_prompt_defaults=_TOOL_GUIDANCE_DEFAULTS,
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
            "profile": {
                "profile_ref": "main_interactive_agent",
                "prompt_policy": {"tool_guidance_prompt_defaults": _TOOL_GUIDANCE_DEFAULTS},
            },
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    packet = result.packet
    stable_payload = _message_payload_with_title(packet, "Observation followup stable contract")

    assert stable_payload["tool_catalog_hash"] == packet.tool_catalog_manifest["tool_catalog_hash"]
    assert stable_payload["available_tools"] == packet.tool_catalog_manifest["model_visible_catalog"]
    assert dict(packet.diagnostics["prompt_manifest"])["tool_catalog_manifest"] == packet.tool_catalog_manifest


def test_model_request_tool_schema_cache_uses_tool_catalog_manifest_metadata() -> None:
    result = RuntimeCompiler(base_dir=_backend_dir()).compile_task_execution_packet(
        session_id="session:tool-catalog-model-request",
        task_run={"task_run_id": "taskrun:tool-catalog-model-request", "diagnostics": {"executor_status": "running"}},
        contract={"task_run_goal": "Validate provider payload tool catalog manifest", "completion_criteria": ["manifest used"]},
        observations=[],
        available_tools=_tools(),
        runtime_assembly={
            "profile": {
                "profile_ref": "main_interactive_agent",
                "prompt_policy": {"tool_guidance_prompt_defaults": _TOOL_GUIDANCE_DEFAULTS},
            },
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    packet = result.packet
    model_request = ModelRequestBuilder().build(
        request_id="modelreq:tool-catalog-manifest",
        messages=packet.model_messages,
        tools=_provider_tools(),
        provider="deepseek",
        model="deepseek-v4-pro",
        segment_plan=packet.segment_plan,
        metadata={"prompt_manifest": dict(packet.diagnostics["prompt_manifest"])},
    )
    provider_tool_segment = next(
        segment
        for segment in model_request.provider_payload_manifest.segments
        if segment.transport_location == "tools"
    )

    assert model_request.tool_catalog_manifest == packet.tool_catalog_manifest
    assert provider_tool_segment.cache_role == "session_stable"
    assert provider_tool_segment.prefix_tier == "task"
    assert provider_tool_segment.metadata["tool_schema_cache_decision"] == "derived_from_tool_catalog_manifest"
    assert provider_tool_segment.metadata["tool_catalog_manifest_ref"] == packet.tool_catalog_manifest["manifest_id"]


def test_model_request_keeps_tool_schema_uncached_when_manifest_drifts_from_tool_index() -> None:
    result = RuntimeCompiler(base_dir=_backend_dir()).compile_task_execution_packet(
        session_id="session:tool-catalog-model-request-drift",
        task_run={"task_run_id": "taskrun:tool-catalog-model-request-drift", "diagnostics": {"executor_status": "running"}},
        contract={"task_run_goal": "Validate provider payload drift detection", "completion_criteria": ["drift detected"]},
        observations=[],
        available_tools=_tools(),
        runtime_assembly={
            "profile": {
                "profile_ref": "main_interactive_agent",
                "prompt_policy": {"tool_guidance_prompt_defaults": _TOOL_GUIDANCE_DEFAULTS},
            },
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    packet = result.packet
    drifted_manifest = dict(packet.tool_catalog_manifest)
    drifted_catalog = [dict(item) for item in drifted_manifest["model_visible_catalog"]]
    drifted_catalog[0]["tool_name"] = "write_file"
    drifted_manifest["model_visible_catalog"] = drifted_catalog
    model_request = ModelRequestBuilder().build(
        request_id="modelreq:tool-catalog-manifest-drift",
        messages=packet.model_messages,
        tools=_provider_tools(),
        provider="deepseek",
        model="deepseek-v4-pro",
        segment_plan=packet.segment_plan,
        metadata={"tool_catalog_manifest": drifted_manifest},
    )
    provider_tool_segment = next(
        segment
        for segment in model_request.provider_payload_manifest.segments
        if segment.transport_location == "tools"
    )

    assert provider_tool_segment.cache_role == "never_cache"
    assert provider_tool_segment.prefix_tier == "none"
    assert provider_tool_segment.metadata["tool_schema_cache_reason"] == "stable_tool_index_does_not_match_tool_catalog_manifest"
