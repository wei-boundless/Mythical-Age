from __future__ import annotations

import pytest

from prompt_composition import (
    build_model_message_spec,
    build_prompt_assembly_plan,
    build_prompt_source_bundle,
    materialize_prompt_packet,
    render_model_messages_from_projection,
)
from harness.runtime.prompt_segment_plan import build_prompt_segment_plan
from runtime.model_gateway.model_request import ModelRequestBuilder
from harness.runtime.compiler import RuntimeCompiler, _render_model_messages_from_prompt_composition


def _spec(*, kind: str, content: str, cache_scope: str, cache_role: str) -> dict[str, object]:
    return build_model_message_spec(
        role="system",
        content=content,
        kind=kind,
        source_ref=kind,
        cache_scope=cache_scope,
        cache_role=cache_role,
        compression_role="preserve",
    )


def test_prompt_assembly_plan_is_the_topology_authority() -> None:
    source_bundle = build_prompt_source_bundle(
        invocation_kind="task_execution",
        packet_id="packet:assembly-authority",
        message_specs=[
            _spec(
                kind="global_static",
                content="Global protocol",
                cache_scope="global",
                cache_role="cacheable_prefix",
            ),
            _spec(
                kind="agent_stable",
                content="You are a coding agent.",
                cache_scope="session",
                cache_role="session_stable",
            ),
            _spec(
                kind="task_contract_stable",
                content="Task contract\n{\"goal\":\"fix cache\"}",
                cache_scope="task",
                cache_role="session_stable",
            ),
            _spec(
                kind="volatile_task_state",
                content="Current state\n{\"step\":\"diagnose\"}",
                cache_scope="none",
                cache_role="volatile",
            ),
        ],
    )

    assembly_plan = build_prompt_assembly_plan(source_bundle=source_bundle)
    materialized = materialize_prompt_packet(assembly_plan=assembly_plan)

    assert assembly_plan.diagnostics["status"] == "ok"
    assert [slot.prefix_tier for slot in assembly_plan.slots] == [
        "provider_global",
        "session",
        "task",
        "volatile",
    ]
    assert [spec["kind"] for spec in materialized.message_specs] == [
        "global_static",
        "agent_stable",
        "task_contract_stable",
        "volatile_task_state",
    ]
    assert assembly_plan.diagnostics["assembly_order_policy"] == "model_visible_source_order_prefix_locked"


def test_prompt_assembly_rejects_stable_segment_after_volatile_source_order() -> None:
    source_bundle = build_prompt_source_bundle(
        invocation_kind="task_execution",
        packet_id="packet:tool-schema-catalog",
        message_specs=[
            _spec(
                kind="volatile_task_state",
                content="Current state\n{\"step\":\"run\"}",
                cache_scope="none",
                cache_role="volatile",
            ),
            _spec(
                kind="tool_schema_catalog",
                content="Tool schema catalog\n{\"tools\":[{\"name\":\"read_file\"}]}",
                cache_scope="task",
                cache_role="session_stable",
            ),
            _spec(
                kind="global_static",
                content="Global protocol",
                cache_scope="global",
                cache_role="cacheable_prefix",
            ),
        ],
    )

    with pytest.raises(ValueError, match="stable_slot_after_volatile_boundary"):
        build_prompt_assembly_plan(source_bundle=source_bundle)


def test_volatile_runtime_tail_preserves_source_order() -> None:
    source_bundle = build_prompt_source_bundle(
        invocation_kind="task_execution",
        packet_id="packet:append-only-topology",
        message_specs=[
            _spec(
                kind="volatile_task_state",
                content="Current cursor\n{\"step\":\"run\"}",
                cache_scope="none",
                cache_role="volatile",
            ),
            _spec(
                kind="runtime_memory_context",
                content="Runtime memory\n{\"selected_sections\":[\"relevant_durable_context\"]}",
                cache_scope="none",
                cache_role="volatile",
            ),
            _spec(
                kind="bound_task_runtime_context",
                content="Bound context\n{\"known_task_files\":[{\"path\":\"src/app.py\"}]}",
                cache_scope="none",
                cache_role="volatile",
            ),
            _spec(
                kind="task_state_replay_entry",
                content="Replay\n{\"observation_ref\":\"obs:1\"}",
                cache_scope="none",
                cache_role="volatile",
            ),
            _spec(
                kind="task_runtime_boundary_dynamic",
                content="Runtime boundary\n{\"allowed_actions\":[\"tool_call\"]}",
                cache_scope="none",
                cache_role="volatile",
            ),
            _spec(
                kind="lifecycle_runtime_guidance",
                content="Lifecycle guidance\n{\"prompt\":\"memory\"}",
                cache_scope="none",
                cache_role="volatile",
            ),
            _spec(
                kind="task_start_inherited_context",
                content="Task start\n{\"handoff_ref\":\"handoff:1\"}",
                cache_scope="none",
                cache_role="volatile",
            ),
        ],
    )

    assembly_plan = build_prompt_assembly_plan(source_bundle=source_bundle)
    materialized = materialize_prompt_packet(assembly_plan=assembly_plan)
    kinds = [spec["kind"] for spec in materialized.message_specs]

    assert kinds == [
        "volatile_task_state",
        "runtime_memory_context",
        "bound_task_runtime_context",
        "task_state_replay_entry",
        "task_runtime_boundary_dynamic",
        "lifecycle_runtime_guidance",
        "task_start_inherited_context",
    ]
    assert assembly_plan.diagnostics["assembly_order_policy"] == "model_visible_source_order_prefix_locked"


def test_task_execution_cursor_does_not_duplicate_user_steers_or_runtime_controls() -> None:
    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:cursor-dedupe",
        task_run={"task_run_id": "taskrun:cursor-dedupe", "diagnostics": {"executor_status": "running"}},
        contract={"task_run_goal": "fix cache", "completion_criteria": ["cache fixed"]},
        observations=[],
        execution_state={
            "system_projection": {
                "runtime_status": "running",
                "pending_user_steers": [
                    {
                        "steer_id": "steer:1",
                        "content": "Do not drop memory.",
                        "priority": "high",
                    }
                ],
                "runtime_control_signals": [
                    {"signal_id": "sig:legacy", "kind": "legacy", "reason": "old alias"},
                    {"runtime_control_signal_ref": "sig:1", "signal_kind": "continue", "reason": "probe"},
                ],
                "latest_runtime_control_signal": {
                    "runtime_control_signal_ref": "sig:stale",
                    "signal_kind": "stale",
                },
            }
        },
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    current_state = _payload_with_title(result.packet, "Task execution current state")
    user_steer = _payload_with_title(result.packet, "User steering updates for this task")
    task_state = current_state["task_state"]
    baseline = result.packet.diagnostics["prompt_manifest"]["context_window"]["stable_runtime_baseline_refs"][
        "task_context_baseline"
    ]

    assert "pending_user_steers" not in task_state
    assert "runtime_control_signals" not in task_state
    assert "latest_runtime_control_signal" not in task_state
    control_signal = current_state["runtime_control_signals"][0]
    latest_control_signal = current_state["latest_runtime_control_signal"]
    assert len(current_state["runtime_control_signals"]) == 1
    assert control_signal["runtime_control_signal_ref"] == "sig:1"
    assert control_signal["signal_kind"] == "continue"
    assert "signal_id" not in control_signal
    assert "kind" not in control_signal
    assert latest_control_signal["runtime_control_signal_ref"] == "sig:1"
    assert latest_control_signal["signal_kind"] == "continue"
    assert "signal_id" not in latest_control_signal
    assert "kind" not in latest_control_signal
    assert user_steer["pending_user_steers"][0]["content"] == "Do not drop memory."
    assert baseline["memory_contract"] == "baseline_plus_append_only_replay_plus_bounded_cursor"
    assert baseline["baseline_id"].startswith("taskctx:")


def test_task_runtime_boundary_uses_protocol_refs_not_repeated_rule_text() -> None:
    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:runtime-boundary-cursor",
        task_run={"task_run_id": "taskrun:runtime-boundary-cursor", "diagnostics": {"executor_status": "running"}},
        contract={"task_run_goal": "fix cache", "completion_criteria": ["cache fixed"]},
        observations=[],
        available_tools=[
            {
                "tool_name": "read_file",
                "description": "Read file",
                "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
            }
        ],
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    runtime_boundary = _payload_with_title(result.packet, "Task execution runtime boundary")
    runtime_context = runtime_boundary["runtime_context"]
    model_contract = runtime_context["model_decision_contract"]
    service_surface = runtime_context["service_surface"]
    serialized = __import__("json").dumps(runtime_boundary, ensure_ascii=False)

    assert model_contract["protocol_ref"] == "action_schema_static"
    assert model_contract["json_action_contract_ref"] == "action_schema_static.json_action_shape_rules"
    assert service_surface["mounted_tools_ref"] == "tool_index_stable.available_tools"
    assert "task_entry_conditions" not in serialized
    assert "respond_requires_top_level_final_answer" not in serialized
    assert "\"mounted_tools\":" not in serialized


def test_prompt_projection_renderer_does_not_fill_missing_fragments_from_source_messages() -> None:
    render = render_model_messages_from_projection(
        manifest={
            "manifest_id": "manifest:strict-render",
            "message_projection": [
                {
                    "segment_id": "segment:missing",
                    "kind": "runtime_boundary",
                    "ordinal": 1,
                    "model_message_index": 0,
                    "model_message_role": "system",
                }
            ],
        },
        content_fragments=[],
        source_messages=[{"role": "system", "content": "old source message must not re-enter"}],
    )

    diagnostics = dict(render.diagnostics)
    assert list(render.messages) == []
    assert diagnostics["rendered_message_count"] == 0
    assert diagnostics["source_message_fallback_count"] == 0
    assert diagnostics["renderer_fallback_to_source_messages"] is False
    assert diagnostics["missing_content_fragment_segment_ids"] == ["segment:missing"]


def test_compiler_prompt_render_fails_closed_instead_of_source_message_fallback() -> None:
    prompt_manifest: dict[str, object] = {}

    try:
        _render_model_messages_from_prompt_composition(
            prompt_manifest=prompt_manifest,
            prompt_composition_manifest={
                "manifest_id": "manifest:compiler-strict-render",
                "message_projection": [
                    {
                        "segment_id": "segment:missing",
                        "kind": "runtime_boundary",
                        "ordinal": 1,
                        "model_message_index": 0,
                        "model_message_role": "system",
                    }
                ],
            },
            content_fragments=(),
            model_messages=[{"role": "system", "content": "old source message must not be sent"}],
        )
    except RuntimeError as exc:
        assert str(exc) == "prompt_composition_render_failed"
    else:
        raise AssertionError("compiler prompt render must fail closed when projection is incomplete")

    render_diagnostics = dict(prompt_manifest["prompt_composition_render"])
    assert render_diagnostics["status"] == "failed"
    assert render_diagnostics["renderer_fallback_to_source_messages"] is False
    assert render_diagnostics["source_message_fallback_count"] == 0
    assert render_diagnostics["fallback_reason"] == "content_fragment_incomplete"


def _payload_with_title(packet, title: str) -> dict[str, object]:
    import json

    for message in packet.model_messages:
        content = str(dict(message).get("content") or "")
        if content.startswith(title + "\n"):
            return json.loads(content.split("\n", 1)[1])
        marker = "\n" + title + "\n"
        if marker in content:
            return json.loads(content.split(marker, 1)[1])
    raise AssertionError(f"missing model message title: {title}")
