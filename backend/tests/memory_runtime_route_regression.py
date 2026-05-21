from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from memory_system.facade import MemoryFacade
from agent_system.assembly.runtime_chain import AgentRuntimeChainAssembler
from agent_system.profiles.runtime_profile_registry import default_agent_runtime_profiles
from task_system.tasks.definitions import default_task_definitions, select_runtime_task_definitions
from understanding.memory_intent import analyze_memory_intent
from understanding.query_understanding import analyze_query_understanding


def test_memory_route_selects_memory_recall_task_definition() -> None:
    definitions = select_runtime_task_definitions(
        "如果我之后再问复杂问题，你应该先怎么回答？",
        query_understanding={
            "route_hint": "memory",
            "execution_posture": "direct_memory",
            "source_kind": "memory",
            "modality": "memory",
            "capability_resolution": {
                "route": "memory",
                "execution_posture": "direct_memory",
            },
        },
    )

    assert [item.definition_id for item in definitions] == ["task.memory_recall"]
    assert default_task_definitions()["task.memory_recall"].task_mode == "memory_recall"


def test_main_runtime_profile_allows_memory_recall_and_memory_read() -> None:
    main_profile = next(item for item in default_agent_runtime_profiles() if item.agent_id == "agent:0")

    assert "full_interactive" in main_profile.allowed_runtime_lanes
    assert "op.memory_read" in main_profile.allowed_operations


def test_memory_read_intent_covers_call_name_and_insufficient_info_preferences() -> None:
    call_name_intent = analyze_memory_intent("你之后应该怎么称呼我？")
    call_name_understanding = analyze_query_understanding("你之后应该怎么称呼我？", call_name_intent)

    assert call_name_intent.intent == "memory_read_signal"
    assert call_name_intent.memory_read_mode == "durable_semantic"
    assert call_name_intent.preferred_types == ["user"]
    assert call_name_intent.preferred_memory_classes == ["preference"]
    assert call_name_understanding.route == "memory"
    assert call_name_understanding.execution_posture == "direct_memory"

    insufficient_info_intent = analyze_memory_intent("如果信息不足，你应该怎么处理？")
    insufficient_info_understanding = analyze_query_understanding("如果信息不足，你应该怎么处理？", insufficient_info_intent)

    assert insufficient_info_intent.intent == "memory_read_signal"
    assert insufficient_info_intent.memory_read_mode == "durable_semantic"
    assert insufficient_info_intent.preferred_types == ["user"]
    assert insufficient_info_intent.preferred_memory_classes == ["preference"]
    assert insufficient_info_understanding.route == "memory"
    assert insufficient_info_understanding.execution_posture == "direct_memory"


def test_memory_route_requests_long_term_and_declares_memory_read() -> None:
    base_dir = Path(__file__).resolve().parents[1]
    assembler = AgentRuntimeChainAssembler(
        base_dir=base_dir,
        memory_facade=MemoryFacade(base_dir),
    )

    runtime = assembler.build_runtime(
        session_id="test-memory-route-long-term",
        task_id="task-runtime",
        message="你之后应该怎么称呼我？",
        source="test",
    )
    task_operation = dict(runtime.get("task_operation") or {})
    memory_profile = dict(task_operation.get("task_memory_request_profile") or {})
    operation_requirements = dict(task_operation.get("operation_requirement") or {})
    diagnostics = dict(dict(runtime.get("memory_runtime_view") or {}).get("diagnostics") or {})

    assert "long_term" in list(memory_profile.get("requested_memory_layers") or [])
    assert memory_profile.get("allow_long_term_memory") is True
    assert "op.memory_read" in list(operation_requirements.get("required_operations") or [])
    assert "long_term_candidate_count" in diagnostics
    assert diagnostics.get("memory_write_allowed") is False


def test_explicit_insufficient_info_preference_is_written_by_memory_agent(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)

    async def invoker(_messages):
        return SimpleNamespace(
            content=json.dumps(
                {
                    "session_memory": {
                        "session_title": "信息不足偏好",
                        "active_goal": "记录用户偏好",
                        "key_user_requests": ["信息不足时先说明缺什么"],
                    },
                    "durable_memory": {
                        "actions": [
                            {
                                "action": "create",
                                "note_id": "insufficient-info-preference",
                                "memory_type": "user",
                                "memory_class": "preference",
                                "title": "信息不足时先说明缺什么",
                                "canonical_statement": "用户偏好：如果信息不足，先明确告诉用户缺什么，不要直接猜。",
                                "summary": "信息不足时先说明缺口。",
                                "confidence": "high",
                                "reason": "这是跨会话稳定偏好。",
                                "evidence_excerpt": "记住：如果信息不足，先明确告诉我缺什么，不要直接猜。",
                                "source_message_refs": ["message:0"],
                            }
                        ]
                    },
                },
                ensure_ascii=False,
            )
        )

    facade.set_model_invoker(invoker)
    receipt = facade.run_memory_maintenance_after_commit(
        session_id="test-memory-write-insufficient-info",
        messages=[{"role": "user", "content": "记住：如果信息不足，先明确告诉我缺什么，不要直接猜。"}],
    )

    notes = facade.memory_manager.list_notes()
    assert receipt.durable_write_count == 1
    assert notes
    assert any(note.memory_type == "user" and note.memory_class == "preference" for note in notes)
    assert any("信息不足" in note.canonical_statement and "不要直接猜" in note.canonical_statement for note in notes)
