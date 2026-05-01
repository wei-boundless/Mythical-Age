from __future__ import annotations

from structured_memory import MemoryNote
from structured_memory.process_state import ContextSlots, FlowState, ProcessState, TaskState
from structured_memory.session_memory import SessionMemoryManager

from memory.facade import MemoryFacade
from memory_system import ConversationMemoryStoreAdapter, LongTermMemoryStoreAdapter, StateMemoryStoreAdapter
from memory_system.contracts import (
    ConversationMemorySnapshot,
    LongTermMemoryRecord,
    MemoryContextCandidate,
    MemoryWriteCandidate,
    StateMemoryRestoreCandidate,
)
from memory_system.gate import MemoryGateDecision
from memory_system.runtime_view import MemoryRuntimeView


def test_state_memory_restore_candidates_remain_candidate_only(tmp_path) -> None:
    session_id = "session-a"
    manager = SessionMemoryManager(tmp_path / session_id)
    manager.state_manager.overwrite(
        ProcessState(
            active_goal="Refactor memory system",
            flow_state=FlowState(flow_id="flow:memory", flow_type="refactor", status="active", confidence=0.8),
            task_state=TaskState(current_step="define contracts", next_step="wire state memory"),
            context_slots=ContextSlots(
                committed_pdf="docs/spec.pdf",
                committed_pdf_owner_task_id="task-1",
                active_binding_kind="pdf",
                active_binding_identity="docs/spec.pdf",
                active_binding_owner_task_id="task-1",
                active_result_handle_id="result-7",
            ),
            next_step=["wire state memory"],
        )
    )

    adapter = StateMemoryStoreAdapter(tmp_path)
    snapshot = adapter.load_snapshot(session_id)
    candidates = adapter.restore_candidates_from_snapshot(snapshot)

    assert snapshot.context_slots["committed_pdf"] == "docs/spec.pdf"
    assert any(candidate.restore_kind == "context_slot" for candidate in candidates)
    assert any(candidate.restore_kind == "result_handle" for candidate in candidates)
    assert all(isinstance(candidate, StateMemoryRestoreCandidate) for candidate in candidates)
    assert all(candidate.authority == "candidate_only" for candidate in candidates)
    assert all(candidate.can_promote_to_current_fact is False for candidate in candidates)


def test_state_memory_context_candidate_is_layered_and_non_authoritative(tmp_path) -> None:
    session_id = "session-b"
    manager = SessionMemoryManager(tmp_path / session_id)
    manager.state_manager.overwrite(
        ProcessState(
            active_goal="Keep state memory explicit",
            context_slots=ContextSlots(committed_dataset="data/orders.csv"),
            next_step=["build ContextPolicy adapter"],
        )
    )

    adapter = StateMemoryStoreAdapter(tmp_path)
    candidates = adapter.context_candidates(session_id)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert isinstance(candidate, MemoryContextCandidate)
    assert candidate.memory_layer == "state"
    assert candidate.authority == "candidate_only"
    assert candidate.can_override_current_turn is False
    assert "committed_dataset: data/orders.csv" in candidate.rendered_preview


def test_memory_facade_exposes_state_memory_preview_without_committing(tmp_path) -> None:
    session_id = "session-c"
    facade = MemoryFacade(tmp_path)
    manager = facade.session_memory.manager(session_id)
    manager.state_manager.overwrite(
        ProcessState(
            active_goal="Expose StateMemory through facade",
            context_slots=ContextSlots(active_result_handle_id="result-11"),
        )
    )

    snapshot = facade.build_state_memory_snapshot(session_id)
    restore_candidates = facade.build_state_memory_restore_candidates(session_id)
    context_candidates = facade.build_state_memory_context_candidates(session_id)

    assert snapshot.active_goal == "Expose StateMemory through facade"
    assert any(candidate.value == "result-11" for candidate in restore_candidates)
    assert all(candidate.authority == "candidate_only" for candidate in restore_candidates)
    assert context_candidates[0].memory_layer == "state"


def test_state_memory_rejects_path_traversal_session_id(tmp_path) -> None:
    adapter = StateMemoryStoreAdapter(tmp_path)

    try:
        adapter.load_snapshot("../outside")
    except ValueError as exc:
        assert "Invalid session_id" in str(exc)
    else:
        raise AssertionError("StateMemoryStoreAdapter accepted an unsafe session id")


def test_conversation_memory_adapter_excludes_state_sections(tmp_path) -> None:
    session_id = "session-e"
    manager = SessionMemoryManager(tmp_path / session_id)
    manager.overwrite(
        """# Active Goal
_What is the user currently trying to achieve?_
- should not be in conversation candidate

# Context Slots
_Which contextual bindings are active for the current flow?_
- active_pdf: docs/state.pdf

# Key User Requests
_Stable instructions or constraints from the user within this session._
- 用户要求先保持记忆分层

# Errors and Corrections
_Failures, corrections, and approaches to avoid repeating._
- 不要把状态记忆写进长期记忆

# Key Results
_Current-turn outputs, conclusions, or artifacts that remain active._
- 已完成 StateMemory 候选化

# Worklog
_Short chronological bullets of meaningful events._
- 添加了 memory_system/contracts.py
"""
    )

    adapter = ConversationMemoryStoreAdapter(tmp_path)
    snapshot = adapter.load_snapshot(session_id)
    candidates = adapter.context_candidates(session_id)

    assert isinstance(snapshot, ConversationMemorySnapshot)
    assert "已完成 StateMemory 候选化" in snapshot.hot_truth_window
    assert "用户要求先保持记忆分层" in snapshot.recent_dialogue_refs
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.memory_layer == "conversation"
    assert candidate.authority == "candidate_only"
    assert candidate.can_override_current_turn is False
    assert "Key User Requests" in candidate.rendered_preview
    assert "Context Slots" not in candidate.rendered_preview
    assert "should not be in conversation candidate" not in candidate.rendered_preview


def test_memory_facade_exposes_conversation_memory_preview(tmp_path) -> None:
    session_id = "session-f"
    facade = MemoryFacade(tmp_path)
    manager = facade.session_memory.manager(session_id)
    manager.overwrite(
        """# Key User Requests
_Stable instructions or constraints from the user within this session._
- 继续推进 ConversationMemory

# Key Results
_Current-turn outputs, conclusions, or artifacts that remain active._
- 对话记忆只读适配完成
"""
    )

    snapshot = facade.build_conversation_memory_snapshot(session_id)
    candidates = facade.build_conversation_memory_context_candidates(session_id)

    assert snapshot.session_id == session_id
    assert "继续推进 ConversationMemory" in snapshot.recent_dialogue_refs
    assert candidates[0].memory_layer == "conversation"


def test_long_term_memory_records_are_runtime_visible_and_verification_scoped(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    facade.memory_manager.save_note(
        MemoryNote(
            slug="answer-style",
            title="用户偏好先讲结论",
            summary="复杂问题先讲结论再展开。",
            canonical_statement="复杂问题先讲结论。",
            body="回答复杂设计问题时先讲结论，再分层展开。",
            memory_type="user",
            memory_class="preference",
            confidence="high",
        )
    )

    adapter = LongTermMemoryStoreAdapter(facade.memory_manager.root_dir)
    records = adapter.load_records()

    assert len(records) == 1
    record = records[0]
    assert isinstance(record, LongTermMemoryRecord)
    assert record.memory_type == "user_preference"
    assert record.verification_policy == "required_for_file_function_flag_claims"
    assert record.metadata["eligible_for_injection"] is True


def test_long_term_memory_context_candidates_are_optional_and_do_not_override(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    note = MemoryNote(
        slug="project-principle",
        title="项目原则：状态记忆不能长期化",
        summary="状态记忆只描述当前工作现场，不应写入长期记忆。",
        canonical_statement="状态记忆不能被默认保存为长期记忆。",
        body="这是记忆系统重构的关键边界。",
        memory_type="project",
        memory_class="work",
        confidence="medium",
    )

    candidates = facade.build_long_term_memory_context_candidates(
        session_id="session-g",
        query="记忆系统边界是什么？",
        relevant_notes=[note],
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.memory_layer == "long_term"
    assert candidate.budget_class == "optional"
    assert candidate.requires_verification_before_use is True
    assert candidate.can_override_current_turn is False
    assert "状态记忆不能被默认保存为长期记忆" in candidate.rendered_preview


def test_long_term_memory_write_candidate_stays_pending(tmp_path) -> None:
    adapter = LongTermMemoryStoreAdapter(tmp_path / "durable_memory")

    candidate = adapter.propose_write_candidate(
        candidate_id="memory-write:demo",
        content="用户偏好先讲结论。",
        source_event_refs=("turn-1",),
        stability="stable",
    )

    assert candidate.target_layer == "long_term"
    assert candidate.gate_decision == "pending"
    assert candidate.authority == "candidate_only"
    assert "no_auto_commit" in candidate.risk_flags


def test_memory_runtime_view_collects_three_layers_without_write_authority(tmp_path) -> None:
    session_id = "session-h"
    facade = MemoryFacade(tmp_path)
    manager = facade.session_memory.manager(session_id)
    manager.overwrite(
        """# Key User Requests
_Stable instructions or constraints from the user within this session._
- 保持三层记忆边界

# Key Results
_Current-turn outputs, conclusions, or artifacts that remain active._
- runtime view 汇总候选
"""
    )
    manager.state_manager.overwrite(
        ProcessState(
            active_goal="Build memory runtime view",
            context_slots=ContextSlots(active_result_handle_id="result-runtime-view"),
        )
    )
    note = MemoryNote(
        slug="runtime-view-principle",
        title="长期记忆只能作为候选",
        summary="长期记忆不能覆盖当前任务事实。",
        canonical_statement="长期记忆只能作为上下文候选。",
        body="使用长期记忆前需要验证是否仍然成立。",
        memory_type="project",
        memory_class="work",
    )

    view = facade.build_memory_runtime_view(
        session_id=session_id,
        query="记忆系统原则是什么？",
        relevant_notes=[note],
    )

    assert isinstance(view, MemoryRuntimeView)
    assert view.read_only is True
    assert view.memory_write_allowed is False
    assert {candidate.memory_layer for candidate in view.context_candidates} == {
        "conversation",
        "state",
        "long_term",
    }
    assert view.restore_candidates
    assert all(candidate.authority == "candidate_only" for candidate in view.restore_candidates)
    assert view.diagnostics["memory_write_allowed"] is False


def test_durable_extraction_preview_builds_write_candidates_without_saving(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)

    candidates = facade.build_durable_memory_write_candidates(
        "session-i",
        [{"role": "user", "content": "请记住：我偏好复杂问题先讲结论。"}],
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert isinstance(candidate, MemoryWriteCandidate)
    assert candidate.target_layer == "long_term"
    assert candidate.write_kind == "propose_long_term_fact"
    assert candidate.gate_decision == "pending"
    assert candidate.authority == "candidate_only"
    assert "no_auto_commit" in candidate.risk_flags
    assert facade.memory_manager.list_notes() == []


def test_memory_message_adapter_excludes_control_plane_contracts_from_memory(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    messages = [
        {
            "role": "system",
            "content": "## Runtime Stage Projection\nOperationGate\nResourcePolicy\nruntime_view_only: true",
        },
        {
            "role": "assistant",
            "content": "调试复述：## Runtime Context Package\nResourcePolicy\nOperationGate\nResourceRuntimeView",
        },
        {
            "role": "user",
            "content": "请记住：我偏好复杂问题先给结论。",
        },
    ]

    converted = facade.adapter.to_messages(messages, session_id="session-contract-isolation")
    rendered = "\n".join(message.content for message in converted)

    assert [message.role for message in converted] == ["user"]
    assert "我偏好复杂问题先给结论" in rendered
    for marker in (
        "Runtime Stage Projection",
        "Runtime Context Package",
        "OperationGate",
        "ResourcePolicy",
        "ResourceRuntimeView",
        "runtime_view_only",
    ):
        assert marker not in rendered

    candidates = facade.build_durable_memory_write_candidates("session-contract-isolation", messages)
    serialized = "\n".join(candidate.content for candidate in candidates)

    assert candidates
    assert "我偏好复杂问题先给结论" in serialized
    for marker in (
        "Runtime Stage Projection",
        "Runtime Context Package",
        "OperationGate",
        "ResourcePolicy",
        "ResourceRuntimeView",
        "runtime_view_only",
    ):
        assert marker not in serialized


def test_memory_gate_preview_blocks_write_candidates(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    candidates = facade.build_durable_memory_write_candidates(
        "session-j",
        [{"role": "user", "content": "请记住：我偏好设计讨论先给结论。"}],
    )

    gate = facade.build_memory_gate(candidates, gate_id="memory-gate:session-j:writeback")

    assert isinstance(gate, MemoryGateDecision)
    assert gate.status == "blocked"
    assert gate.read_only is True
    assert gate.memory_write_allowed is False
    assert gate.commit_allowed is False
    assert gate.write_candidates == candidates
    assert gate.diagnostics["write_candidate_count"] == len(candidates)
    assert facade.memory_manager.list_notes() == []
