from __future__ import annotations

from pathlib import Path

from harness.runtime.compiler import RuntimeCompiler
from harness.runtime.prompt_segment_plan import build_prompt_segment_plan
from prompt_composition import (
    PromptCompositionLayerInput,
    build_content_fragments_from_message_specs,
    build_content_fragments_from_model_messages,
    build_model_message_spec,
    build_runtime_payload_message_spec,
    build_shadow_prompt_composition_manifest,
    render_model_messages_from_projection,
    render_runtime_payload_fragment,
)
from prompt_library import PromptAssemblyRequest, PromptAssemblyResult, PromptAssemblyService, PromptSection


def _backend_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def _composition_manifest(packet) -> dict[str, object]:
    manifest = dict(packet.diagnostics["prompt_manifest"])
    composition = dict(manifest.get("prompt_composition") or {})
    assert dict(packet.prompt_composition_manifest) == composition
    assert composition.get("shadow_mode") is True
    assert composition.get("status") != "failed"
    return composition


def _assert_shadow_manifest_covers_packet(packet) -> dict[str, object]:
    prompt_manifest = dict(packet.diagnostics["prompt_manifest"])
    composition = _composition_manifest(packet)
    render = dict(prompt_manifest.get("prompt_composition_render") or {})
    coverage = dict(composition.get("coverage") or {})
    segment_plan = dict(packet.segment_plan)
    segments = list(segment_plan.get("segments") or [])
    projection = list(composition.get("message_projection") or [])
    assert packet.diagnostics["model_input_authority"] == "prompt_composition.message_projection"
    assert render["renderer"] == "prompt_composition.message_projection"
    assert render["rendered_message_count"] == len(packet.model_messages)
    assert render["content_fragment_count"] == len(packet.model_messages)
    source_counts = dict(render["content_fragment_source_counts"])
    assert sum(source_counts.values()) == len(packet.model_messages)
    assert source_counts.get("prompt_assembly.content", 0) >= 1
    assert any(source != "runtime_sanitized_model_message" for source in source_counts)
    materialized_counts = dict(render["content_fragment_materialized_from_counts"])
    assert sum(materialized_counts.values()) == len(packet.model_messages)
    assert materialized_counts.get("message_spec", 0) >= 1
    assert render["rendered_from_content_fragment_count"] == len(packet.model_messages)
    assert render["source_message_fallback_count"] == 0
    assert render["content_hash_mismatch_count"] == 0
    assert render["hash_mismatch_count"] == 0
    assert render.get("renderer_fallback_to_source_messages") is not True
    assert coverage["segment_count"] == len(list(segment_plan.get("segments") or []))
    assert coverage["all_segments_explained"] is True
    assert coverage["slot_count"] >= coverage["registered_prompt_slot_count"]
    assert coverage["legacy_runtime_text_count"] == 0
    assert len(projection) == len(segments)
    assert [item["segment_id"] for item in projection] == [item["segment_id"] for item in segments]
    assert [item["model_message_index"] for item in projection] == list(range(len(segments)))
    assert [item["model_message_hash"] for item in projection] == [item["model_message_hash"] for item in segments]
    assert all("content" not in item for item in projection)
    return composition


def test_shadow_manifest_binds_registered_prompts_and_marks_legacy_runtime_text() -> None:
    backend_dir = _backend_dir()
    runtime_pack = PromptAssemblyService(backend_dir).assemble(
        PromptAssemblyRequest(invocation_kind="task_execution")
    )
    segment_plan = build_prompt_segment_plan(
        packet_id="packet:prompt-composition-shadow",
        invocation_kind="task_execution",
        message_specs=[
            {
                "role": "system",
                "content": runtime_pack.content,
                "kind": "global_static",
                "source_ref": ",".join(runtime_pack.prompt_pack_refs),
                "cache_scope": "global",
                "cache_role": "cacheable_prefix",
                "compression_role": "preserve",
            },
            {
                "role": "system",
                "content": "Task execution action schema\n{}",
                "kind": "action_schema_static",
                "source_ref": "task_execution_action_schema",
                "cache_scope": "session",
                "cache_role": "session_stable",
                "compression_role": "preserve",
            },
        ],
    )

    manifest = build_shadow_prompt_composition_manifest(
        invocation_kind="task_execution",
        packet_id="packet:prompt-composition-shadow",
        layers=(
            PromptCompositionLayerInput(
                layer_id="runtime_pack",
                slot_layer="global_static",
                assembly=runtime_pack,
                message_kinds=("global_static",),
                lifecycle="global_static",
            ),
        ),
        segment_plan=segment_plan.to_dict(),
    ).to_dict()

    coverage = dict(manifest["coverage"])
    statuses = dict(coverage["segment_binding_status_counts"])
    cache_boundary = dict(manifest["diagnostics"]["cache_boundary"])
    projection = list(manifest["message_projection"])
    assert statuses["registered_prompt_bound"] == 1
    assert statuses["runtime_action_schema"] == 1
    assert [item["kind"] for item in projection] == ["global_static", "action_schema_static"]
    assert all("content" not in item for item in projection)
    assert coverage["registered_prompt_slot_count"] > 0
    assert coverage["runtime_shadow_slot_count"] == 1
    assert cache_boundary["status"] == "ok"
    assert cache_boundary["prefix_tier_sequence"] == ["provider_global", "session"]


def test_message_projection_renderer_reconstructs_ordered_messages() -> None:
    messages = [
        {"role": "system", "content": "global runtime"},
        {"role": "user", "content": "current request"},
    ]
    segment_plan = build_prompt_segment_plan(
        packet_id="packet:prompt-composition-renderer",
        invocation_kind="single_agent_turn",
        message_specs=[
            {
                "role": "system",
                "content": messages[0]["content"],
                "kind": "global_static",
                "source_ref": "runtime.test",
                "cache_scope": "global",
                "cache_role": "cacheable_prefix",
                "prefix_tier": "provider_global",
                "compression_role": "preserve",
            },
            {
                "role": "user",
                "content": messages[1]["content"],
                "kind": "volatile_user",
                "source_ref": "turn.current",
                "cache_scope": "none",
                "cache_role": "volatile",
                "prefix_tier": "volatile",
                "compression_role": "summarize",
            },
        ],
    )
    manifest = build_shadow_prompt_composition_manifest(
        invocation_kind="single_agent_turn",
        packet_id="packet:prompt-composition-renderer",
        layers=(),
        segment_plan=segment_plan.to_dict(),
    ).to_dict()
    content_fragments = build_content_fragments_from_model_messages(
        segment_plan=segment_plan,
        model_messages=messages,
    )

    result = render_model_messages_from_projection(manifest=manifest, content_fragments=content_fragments)

    assert list(result.messages) == messages
    assert result.diagnostics["rendered_message_count"] == 2
    assert result.diagnostics["content_fragment_count"] == 2
    assert result.diagnostics["content_fragment_source_counts"]["runtime_sanitized_model_message"] == 2
    assert result.diagnostics["content_fragment_materialized_from_counts"]["sanitized_model_message"] == 2
    assert result.diagnostics["rendered_from_content_fragment_count"] == 2
    assert result.diagnostics["source_message_fallback_count"] == 0
    assert result.diagnostics["renderer_fallback_to_source_messages"] is False
    assert result.diagnostics["content_hash_mismatch_count"] == 0
    assert result.diagnostics["hash_mismatch_count"] == 0
    assert all("content" not in item for item in manifest["message_projection"])


def test_message_projection_renderer_marks_source_message_fallback() -> None:
    messages = [
        {"role": "system", "content": "global runtime"},
        {"role": "user", "content": "current request"},
    ]
    segment_plan = build_prompt_segment_plan(
        packet_id="packet:prompt-composition-renderer-fallback",
        invocation_kind="single_agent_turn",
        message_specs=[
            {
                "role": "system",
                "content": messages[0]["content"],
                "kind": "global_static",
                "source_ref": "runtime.test",
                "cache_scope": "global",
                "cache_role": "cacheable_prefix",
                "compression_role": "preserve",
            },
            {
                "role": "user",
                "content": messages[1]["content"],
                "kind": "volatile_user",
                "source_ref": "turn.current",
                "cache_scope": "none",
                "cache_role": "volatile",
                "compression_role": "summarize",
            },
        ],
    )
    manifest = build_shadow_prompt_composition_manifest(
        invocation_kind="single_agent_turn",
        packet_id="packet:prompt-composition-renderer-fallback",
        layers=(),
        segment_plan=segment_plan.to_dict(),
    ).to_dict()
    content_fragments = build_content_fragments_from_model_messages(
        segment_plan=segment_plan,
        model_messages=messages[:1],
    )

    result = render_model_messages_from_projection(
        manifest=manifest,
        content_fragments=content_fragments,
        source_messages=messages,
    )

    assert list(result.messages) == messages
    assert result.diagnostics["rendered_from_content_fragment_count"] == 1
    assert result.diagnostics["source_message_fallback_count"] == 1
    assert result.diagnostics["renderer_fallback_to_source_messages"] is True
    assert result.diagnostics["fallback_reason"] == "content_fragment_incomplete"


def test_model_message_spec_builder_assigns_content_source() -> None:
    spec = build_model_message_spec(
        role="system",
        content="agent",
        kind="agent_stable",
        source_ref="agent.test",
        cache_scope="session",
        cache_role="session_stable",
        compression_role="preserve",
    )
    override = build_model_message_spec(
        role="system",
        content="custom",
        kind="agent_stable",
        source_ref="agent.test",
        cache_scope="session",
        cache_role="session_stable",
        compression_role="preserve",
        metadata={"content_source": "test.override"},
    )

    assert spec["metadata"]["content_source"] == "prompt_composition.section_renderer.agent"
    assert override["metadata"]["content_source"] == "test.override"


def test_content_fragments_from_message_specs_prefers_registered_sources() -> None:
    message_specs = [
        build_model_message_spec(
            role="system",
            content="人格",
            kind="personality_stable",
            source_ref="personality.demo",
            cache_scope="session",
            cache_role="session_stable",
            compression_role="preserve",
        ),
        build_model_message_spec(
            role="system",
            content="动态",
            kind="dynamic_projection",
            source_ref="runtime.delta",
            cache_scope="none",
            cache_role="volatile",
            compression_role="summarize",
        ),
    ]
    segment_plan = build_prompt_segment_plan(
        packet_id="packet:prompt-composition-source-aware-fragments",
        invocation_kind="single_agent_turn",
        message_specs=message_specs,
    )
    fallback_messages = [
        {"role": "system", "content": "sanitized personality should not win"},
        {"role": "system", "content": "sanitized dynamic wins"},
    ]

    fragments = build_content_fragments_from_message_specs(
        segment_plan=segment_plan,
        message_specs=message_specs,
        fallback_model_messages=fallback_messages,
    )

    assert fragments[0].model_message["content"] == "人格"
    assert fragments[0].materialized_from == "message_spec"
    assert fragments[1].model_message["content"] == "动态"
    assert fragments[1].materialized_from == "message_spec"


def test_runtime_payload_fragment_renderer_uses_stable_json() -> None:
    content = render_runtime_payload_fragment(
        "Runtime payload",
        {"z": 1, "a": {"b": True}, "text": "中文"},
    )

    assert content == 'Runtime payload\n{"a":{"b":true},"text":"中文","z":1}'


def test_runtime_payload_message_spec_keeps_typed_fragment_metadata() -> None:
    spec = build_runtime_payload_message_spec(
        title="Runtime payload",
        payload={"z": 1, "a": 2},
        role="system",
        kind="task_contract_stable",
        source_ref="contract.demo",
        cache_scope="task",
        cache_role="session_stable",
        compression_role="preserve",
        preamble="你只根据任务合同工作。",
        metadata={"custom": "value"},
    )

    assert spec["content"] == '你只根据任务合同工作。\nRuntime payload\n{"a":2,"z":1}\n'
    assert spec["metadata"]["content_source"] == "runtime.task_contract_manifest"
    assert spec["metadata"]["runtime_fragment_title"] == "Runtime payload"
    assert spec["metadata"]["runtime_fragment_payload_keys"] == ["a", "z"]
    assert spec["metadata"]["runtime_fragment_authority"] == "prompt_composition.runtime_fragment"
    assert spec["metadata"]["custom"] == "value"


def test_provider_protocol_replay_keeps_sanitized_materialization() -> None:
    message_specs = [
        build_model_message_spec(
            role="tool",
            content="raw protocol output",
            kind="provider_protocol_history",
            source_ref="api_transcript:1",
            cache_scope="none",
            cache_role="never_cache",
            compression_role="preserve",
            metadata={"content_source": "runtime.provider_protocol_replay"},
        ),
    ]
    segment_plan = build_prompt_segment_plan(
        packet_id="packet:prompt-composition-provider-protocol",
        invocation_kind="single_agent_turn",
        message_specs=message_specs,
    )
    fallback_messages = [
        {"role": "tool", "tool_call_id": "call-1", "content": "sanitized protocol output"},
    ]

    fragments = build_content_fragments_from_message_specs(
        segment_plan=segment_plan,
        message_specs=message_specs,
        fallback_model_messages=fallback_messages,
    )

    assert fragments[0].model_message["content"] == "sanitized protocol output"
    assert fragments[0].model_message["tool_call_id"] == "call-1"
    assert fragments[0].materialized_from == "sanitized_model_message"


def test_shadow_manifest_flags_stable_segment_after_volatile_boundary() -> None:
    segment_plan = build_prompt_segment_plan(
        packet_id="packet:prompt-composition-volatile-break",
        invocation_kind="task_execution",
        message_specs=[
            {
                "role": "system",
                "content": "global runtime",
                "kind": "global_static",
                "source_ref": "runtime.test",
                "cache_scope": "global",
                "cache_role": "cacheable_prefix",
                "prefix_tier": "provider_global",
                "compression_role": "preserve",
            },
            {
                "role": "user",
                "content": "current user message",
                "kind": "volatile_user",
                "source_ref": "turn.current",
                "cache_scope": "none",
                "cache_role": "volatile",
                "prefix_tier": "volatile",
                "compression_role": "summarize",
            },
            {
                "role": "system",
                "content": "late task contract",
                "kind": "task_contract_stable",
                "source_ref": "contract.late",
                "cache_scope": "task",
                "cache_role": "session_stable",
                "prefix_tier": "task",
                "compression_role": "preserve",
            },
        ],
    )

    manifest = build_shadow_prompt_composition_manifest(
        invocation_kind="task_execution",
        packet_id="packet:prompt-composition-volatile-break",
        layers=(),
        segment_plan=segment_plan.to_dict(),
    ).to_dict()

    cache_boundary = dict(manifest["diagnostics"]["cache_boundary"])
    violations = list(cache_boundary["segment_prefix_violations"])

    assert cache_boundary["status"] == "warning"
    assert violations[0]["code"] == "stable_segment_after_volatile_boundary"
    assert violations[0]["kind"] == "task_contract_stable"


def test_shadow_manifest_flags_layer_cache_policy_mismatch() -> None:
    assembly = PromptAssemblyResult(
        assembly_id="promptasm:session-role",
        invocation_kind="single_agent_turn",
        sections=(
            PromptSection(
                section_id="agent.role:1",
                prompt_ref="agent.role.session",
                category="agent",
                subtype="role",
                title="Agent Role",
                content="你是一名会话级 agent。",
                owner_layer="agent",
                cache_scope="session_stable",
                source_ref="agent.role.session",
                order=1,
            ),
        ),
    )
    segment_plan = build_prompt_segment_plan(
        packet_id="packet:prompt-composition-layer-mismatch",
        invocation_kind="single_agent_turn",
        message_specs=[
            {
                "role": "system",
                "content": assembly.content,
                "kind": "global_static",
                "source_ref": "agent.role.session",
                "cache_scope": "global",
                "cache_role": "cacheable_prefix",
                "prefix_tier": "provider_global",
                "compression_role": "preserve",
            },
        ],
    )

    manifest = build_shadow_prompt_composition_manifest(
        invocation_kind="single_agent_turn",
        packet_id="packet:prompt-composition-layer-mismatch",
        layers=(
            PromptCompositionLayerInput(
                layer_id="wrong_global_layer",
                slot_layer="global_static",
                assembly=assembly,
                message_kinds=("global_static",),
                lifecycle="global_static",
            ),
        ),
        segment_plan=segment_plan.to_dict(),
    ).to_dict()

    cache_boundary = dict(manifest["diagnostics"]["cache_boundary"])
    violations = list(cache_boundary["layer_cache_policy_violations"])

    assert cache_boundary["status"] == "warning"
    assert violations[0]["code"] == "slot_prefix_tier_outside_layer_policy"
    assert violations[0]["layer"] == "global_static"


def test_shadow_manifest_reports_legacy_stable_runtime_text_samples() -> None:
    segment_plan = build_prompt_segment_plan(
        packet_id="packet:prompt-composition-legacy-stable",
        invocation_kind="task_execution",
        message_specs=[
            {
                "role": "system",
                "content": "compiler generated stable header",
                "kind": "compiler_header_stable",
                "source_ref": "compiler.header",
                "cache_scope": "session",
                "cache_role": "session_stable",
                "prefix_tier": "session",
                "compression_role": "preserve",
            },
        ],
    )

    manifest = build_shadow_prompt_composition_manifest(
        invocation_kind="task_execution",
        packet_id="packet:prompt-composition-legacy-stable",
        layers=(),
        segment_plan=segment_plan.to_dict(),
    ).to_dict()

    coverage = dict(manifest["coverage"])
    sample = coverage["legacy_runtime_text_samples"][0]
    assert coverage["legacy_runtime_text_count"] == 1
    assert coverage["stable_unregistered_segment_count"] == 1
    assert coverage["runtime_shadow_slot_source_kind_counts"]["legacy_runtime_text"] == 1
    assert sample["kind"] == "compiler_header_stable"
    assert sample["source_ref"] == "compiler.header"


def test_runtime_compiler_attaches_shadow_manifest_for_single_agent_turn() -> None:
    result = RuntimeCompiler(base_dir=_backend_dir()).compile_single_agent_turn_packet(
        session_id="session:prompt-composition-single",
        turn_id="turn:prompt-composition-single",
        agent_invocation_id="aginvoke:prompt-composition-single",
        user_message="直接回答。",
        history=[],
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "agent_prompt_refs_by_invocation": {
                "single_agent_turn": ["agent.main_interactive_agent.single_agent_turn.work_role"]
            },
        },
    )

    composition = _assert_shadow_manifest_covers_packet(result.packet)
    coverage = dict(composition["coverage"])
    assert coverage["registered_prompt_bound_count"] >= 1
    assert coverage["runtime_protocol_count"] >= 1
    assert coverage["dynamic_context_fragment_count"] >= 1


def test_runtime_compiler_attaches_shadow_manifest_for_task_execution() -> None:
    result = RuntimeCompiler(base_dir=_backend_dir()).compile_task_execution_packet(
        session_id="session:prompt-composition-task",
        task_run={"task_run_id": "taskrun:prompt-composition-task", "diagnostics": {"executor_status": "running"}},
        contract={"task_run_goal": "验证 prompt composition shadow manifest", "completion_criteria": ["生成 shadow manifest"]},
        observations=[],
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "agent_prompt_refs_by_invocation": {
                "task_execution": ["agent.main_interactive_agent.task_execution.work_role"]
            },
        },
    )

    composition = _assert_shadow_manifest_covers_packet(result.packet)
    coverage = dict(composition["coverage"])
    assert coverage["registered_prompt_bound_count"] >= 1
    assert coverage["runtime_action_schema_count"] >= 1
    assert coverage["runtime_artifact_scope_count"] >= 1
    assert coverage["runtime_contract_count"] >= 1
    assert coverage["tool_catalog_count"] >= 1


def test_runtime_compiler_attaches_shadow_manifest_for_observation_followup() -> None:
    result = RuntimeCompiler(base_dir=_backend_dir()).compile_observation_followup_packet(
        session_id="session:prompt-composition-observation",
        turn_id="turn:prompt-composition-observation",
        agent_invocation_id="aginvoke:prompt-composition-observation",
        user_message="继续。",
        history=[],
        observations=[{"observation_id": "obs:1", "payload": {"status": "ok", "text": "done"}}],
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "agent_prompt_refs_by_invocation": {
                "tool_observation_followup": ["agent.main_interactive_agent.tool_observation_followup.work_role"]
            },
        },
    )

    composition = _assert_shadow_manifest_covers_packet(result.packet)
    coverage = dict(composition["coverage"])
    assert coverage["registered_prompt_bound_count"] >= 1
    assert coverage["runtime_contract_count"] >= 1
    assert coverage["dynamic_context_fragment_count"] >= 1


def test_runtime_compiler_attaches_shadow_manifest_for_semantic_compaction() -> None:
    result = RuntimeCompiler(base_dir=_backend_dir()).compile_semantic_compaction_packet(
        semantic_request={
            "request_id": "ctxcompact:prompt-composition-shadow",
            "pressure_level": "full_compact",
            "summary_target_tokens": 512,
            "messages": [],
            "recent_messages": [],
            "dropped_message_count": 0,
            "instructions": "保留当前任务和用户约束。",
            "diagnostics": {"session_id": "session:prompt-composition-semantic"},
        },
        runtime_assembly={
            "profile": {"profile_ref": "context_compactor_agent"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "agent_prompt_refs_by_invocation": {
                "semantic_compaction": ["agent.context_compactor_agent.semantic_compaction.work_role"]
            },
        },
        session_id="session:prompt-composition-semantic",
        turn_id="turn:prompt-composition-semantic",
    )

    composition = _assert_shadow_manifest_covers_packet(result.packet)
    coverage = dict(composition["coverage"])
    assert coverage["registered_prompt_bound_count"] >= 1
    assert coverage["semantic_compaction_boundary_count"] == 1
    assert coverage["dynamic_context_fragment_count"] >= 1
