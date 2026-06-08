from __future__ import annotations

from pathlib import Path

from harness.runtime.compiler import RuntimeCompiler
from harness.runtime.prompt_segment_plan import build_prompt_segment_plan
from prompt_composition import PromptCompositionLayerInput, build_shadow_prompt_composition_manifest
from prompt_library import PromptAssemblyRequest, PromptAssemblyService


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
    composition = _composition_manifest(packet)
    coverage = dict(composition.get("coverage") or {})
    segment_plan = dict(packet.segment_plan)
    assert coverage["segment_count"] == len(list(segment_plan.get("segments") or []))
    assert coverage["all_segments_explained"] is True
    assert coverage["slot_count"] >= coverage["registered_prompt_slot_count"]
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
    assert statuses["registered_prompt_bound"] == 1
    assert statuses["runtime_action_schema"] == 1
    assert coverage["registered_prompt_slot_count"] > 0
    assert coverage["runtime_shadow_slot_count"] == 1


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
    assert coverage["dynamic_context_fragment_count"] >= 1
