from __future__ import annotations

from memory_system.storage.models import MemoryNote
from memory_system.storage.process_state import ContextSlots, FlowState, ProcessState, TaskState
from memory_system.storage.session_memory import SessionMemoryManager

from memory_system import MemoryFacade
from memory_system.conversation_memory import ConversationMemoryStoreAdapter
from memory_system.contracts import ConversationMemorySnapshot, MemoryContextCandidate, StateMemoryRestoreCandidate
from memory_system.runtime_view import MemoryRuntimeView
from memory_system.state_memory import StateMemoryStoreAdapter
from memory_system.runtime_supply import (
    MemoryBundle,
    build_memory_request,
    build_memory_scope_policy,
)


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
    assert "表格/数据集工作对象" in candidate.rendered_preview


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

    snapshot = facade.bundle_service.build_state_memory_snapshot(session_id)
    restore_candidates = facade.bundle_service.build_state_memory_restore_candidates(session_id)
    context_candidates = facade.bundle_service.build_state_memory_context_candidates(session_id)

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


def test_state_memory_snapshot_rejects_unserializable_state_sections(tmp_path) -> None:
    adapter = StateMemoryStoreAdapter(tmp_path)

    class BrokenManager:
        def load_state(self):
            return type(
                "BrokenState",
                (),
                {
                    "active_goal": "bad state section",
                    "flow_state": object(),
                    "task_state": {},
                    "context_slots": {},
                    "bundle_result_refs": [],
                    "current_result_refs": [],
                    "key_results": [],
                    "historical_result_refs": [],
                    "next_step": [],
                    "updated_at": "",
                },
            )()

    adapter.manager = lambda _session_id: BrokenManager()  # type: ignore[method-assign]

    try:
        adapter.load_snapshot("session-broken-state")
    except ValueError as exc:
        assert "not serializable" in str(exc)
    else:
        raise AssertionError("Unserializable process state section was silently dropped")


def test_session_memory_layer_rejects_path_traversal_session_id(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)

    for call in (facade.session_memory.manager, facade.session_memory.session_dir):
        try:
            call("../outside")
        except ValueError as exc:
            assert "Invalid session_id" in str(exc)
        else:
            raise AssertionError("SessionMemoryLayer accepted an unsafe session id")


def test_foreground_continuity_state_is_immediately_available_without_runtime_wiring(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)

    state = facade.save_foreground_continuity_state(
        session_id="session-foreground",
        turn_id="turn:1",
        main_context={"active_goal": "继续分析库存表", "active_dataset": "data/inventory.csv"},
        task_summary_refs=[{"query": "分析库存表", "summary": "缺货集中在 A 仓。"}],
        bundle_summary_refs=[{"ordinal": 2, "task_id": "task:2", "summary": "第二项已完成"}],
    )
    loaded = facade.load_foreground_continuity_state("session-foreground")

    assert state.active_goal == "继续分析库存表"
    assert loaded is not None
    assert loaded.active_bindings["active_dataset"] == "data/inventory.csv"
    assert "缺货集中在 A 仓。" in loaded.latest_result_refs
    assert loaded.bundle_result_refs[0]["ordinal"] == 2


def test_foreground_continuity_state_corruption_is_not_silently_ignored(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    path = facade.foreground_state.state_path("session-foreground-corrupt")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{broken-json", encoding="utf-8")

    try:
        facade.load_foreground_continuity_state("session-foreground-corrupt")
    except ValueError as exc:
        assert "Expecting property name" in str(exc)
    else:
        raise AssertionError("Foreground continuity state corruption was silently ignored")


def test_process_state_corruption_is_not_silently_replaced_by_mirror(tmp_path) -> None:
    manager = SessionMemoryManager(tmp_path / "session-process-corrupt")
    manager.state_manager.overwrite(ProcessState(active_goal="valid mirror exists"))
    manager.state_manager.process_state_path.write_text("{broken-json", encoding="utf-8")

    try:
        manager.load_state()
    except ValueError as exc:
        assert "Expecting property name" in str(exc)
    else:
        raise AssertionError("Corrupt process_state.json was silently replaced by state.json")


def test_session_memory_projection_does_not_guess_task_switch_from_keywords(tmp_path) -> None:
    manager = SessionMemoryManager(tmp_path / "session-switch")
    manager.state_manager.overwrite(
        ProcessState(
            active_goal="阅读 PDF 报告",
            context_slots=ContextSlots(active_pdf="docs/report.pdf"),
            warm_context=["上一轮 PDF 结论"],
            key_results=["PDF 结论"],
        )
    )

    state = manager.update_runtime_state_from_context_state(
        {"active_goal": "现在做代码重构"},
        task_summaries=[],
    )

    assert state.active_goal == "现在做代码重构"
    assert "上一轮 PDF 结论" in state.warm_context
    assert not any("上一阶段" in item or "切换后" in item for item in state.warm_context)


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
    assert "不要把状态记忆写进长期记忆" not in snapshot.hot_truth_window
    assert "用户要求先保持记忆分层" in snapshot.recent_dialogue_refs
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.memory_layer == "conversation"
    assert candidate.authority == "candidate_only"
    assert candidate.can_override_current_turn is False
    assert "Key User Requests" in candidate.rendered_preview
    assert "Errors and Corrections" not in candidate.rendered_preview
    assert "不要把状态记忆写进长期记忆" not in candidate.rendered_preview
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

    snapshot = facade.bundle_service.build_conversation_memory_snapshot(session_id)
    candidates = facade.bundle_service.build_conversation_memory_context_candidates(session_id)

    assert snapshot.session_id == session_id
    assert "继续推进 ConversationMemory" in snapshot.recent_dialogue_refs
    assert candidates[0].memory_layer == "conversation"


def test_long_term_memory_context_candidate_carries_verification_policy(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    note = MemoryNote(
        slug="answer-style",
        title="用户偏好先讲结论",
        summary="复杂问题先讲结论再展开。",
        canonical_statement="复杂问题先讲结论。",
        body="回答复杂设计问题时先讲结论，再分层展开。",
        memory_type="user",
        memory_class="preference",
        confidence="high",
    )

    candidates = facade.bundle_service.build_long_term_memory_context_candidates(
        session_id="session-style",
        query="回答风格",
        relevant_notes=[note],
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.memory_layer == "long_term"
    assert candidate.metadata["memory_class"] == "preference"
    assert candidate.metadata["verification_policy"] == "verify_file_function_flag_claims_against_current_state"
    assert candidate.confidence == 0.82


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

    candidates = facade.bundle_service.build_long_term_memory_context_candidates(
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
            context_slots=ContextSlots(
                active_dataset="Data/employees.xlsx",
                active_result_handle_id="result-runtime-view",
                active_subset_handle_id="subset-runtime-view",
                active_subset_filter_column="name",
                active_subset_labels=["Alice", "Bob"],
            ),
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

    default_view = facade.bundle_service.build_memory_runtime_view(
        session_id=session_id,
        query="记忆系统原则是什么？",
        relevant_notes=[note],
    )
    requested_view = facade.bundle_service.build_memory_runtime_view(
        session_id=session_id,
        query="记忆系统原则是什么？",
        relevant_notes=[note],
        memory_request_profile={
            "requested_memory_layers": ["state", "long_term"],
            "allow_long_term_memory": True,
        },
    )

    assert isinstance(default_view, MemoryRuntimeView)
    assert default_view.read_only is True
    assert default_view.memory_write_allowed is False
    assert default_view.context_candidates == ()
    assert default_view.restore_candidates == ()
    assert default_view.state_snapshot is None
    assert default_view.diagnostics["state_read_requested"] is False
    assert default_view.diagnostics["memory_write_allowed"] is False
    assert {candidate.memory_layer for candidate in requested_view.context_candidates} == {"state", "long_term"}
    assert requested_view.restore_candidates
    assert requested_view.state_snapshot is not None
    assert requested_view.state_snapshot.context_slots["active_constraints"]["subset_filter_column"] == "name"
    assert requested_view.state_snapshot.context_slots["active_constraints"]["subset_labels"] == ["Alice", "Bob"]
    assert all(candidate.authority == "candidate_only" for candidate in requested_view.restore_candidates)
    assert requested_view.diagnostics["state_read_requested"] is True
    assert "long_term_records" not in requested_view.to_dict()


def test_long_term_records_are_not_exposed_even_when_long_term_requested(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    facade.memory_manager.save_note(
        MemoryNote(
            slug="project-memory-policy",
            title="项目记忆政策",
            summary="长期记忆只作为召回候选。",
            canonical_statement="长期记忆记录不能直接注入 prompt。",
            body="只有召回候选可以进入上下文。",
            memory_type="project",
            memory_class="work",
        )
    )

    view = facade.bundle_service.build_memory_runtime_view(
        session_id="session-long-term-records",
        query="无关问题",
        memory_request_profile={"requested_memory_layers": ["long_term"], "allow_long_term_memory": True},
    )

    assert "long_term_records" not in view.to_dict()
    assert view.diagnostics["long_term_candidate_count"] == 0


def test_memory_runtime_view_rejects_unknown_memory_layer(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)

    try:
        facade.bundle_service.build_memory_runtime_view(
            session_id="session-invalid-layer",
            memory_request_profile={"requested_memory_layers": ["state", "legacy_magic"]},
        )
    except ValueError as exc:
        assert "Unknown memory layer: legacy_magic" in str(exc)
    else:
        raise AssertionError("Memory runtime view accepted an unknown memory layer")


def test_long_term_recall_without_selector_does_not_use_keyword_fallback(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    facade.memory_manager.save_note(
        MemoryNote(
            slug="answer-style",
            title="回答风格",
            summary="复杂问题先讲结论。",
            canonical_statement="复杂问题先讲结论。",
            body="用户偏好复杂问题先讲结论。",
            memory_type="user",
            memory_class="preference",
        )
    )

    result = facade.bundle_service.recall_durable_memories(
        query="回答风格",
        memory_intent=None,
        note_limit=5,
    )

    assert result.selected_notes == []
    assert result.selection.should_recall is False
    assert result.selection.reason == "no_durable_memory_selector_configured"


def test_preselected_long_term_notes_do_not_require_query_signal(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    note = MemoryNote(
        slug="preselected-note",
        title="系统预选记忆",
        summary="系统已经显式选择这条长期记忆。",
        canonical_statement="预选长期记忆不需要 query 触发。",
        body="这条记忆由上层 plan 或人工流程显式提供。",
        memory_type="project",
        memory_class="work",
    )

    result = facade.bundle_service.recall_durable_memories(
        query="",
        selected_notes=[note],
    )

    assert result.selection.reason == "preselected_notes"
    assert result.selection.should_recall is True
    assert result.selected_notes[0]["note_id"] == "preselected-note"


def test_memory_runtime_view_collects_conversation_only_when_requested(tmp_path) -> None:
    session_id = "session-h-conversation"
    facade = MemoryFacade(tmp_path)
    manager = facade.session_memory.manager(session_id)
    manager.overwrite(
        """# Key User Requests
_Stable instructions or constraints from the user within this session._
- 用户要求保持会话连续性

# Errors and Corrections
_Failures, corrections, and approaches to avoid repeating._
- 本轮委派被限流，下一轮继续

# Key Results
_Current-turn outputs, conclusions, or artifacts that remain active._
- 已完成会话连续性检查
"""
    )

    default_view = facade.bundle_service.build_memory_runtime_view(
        session_id=session_id,
        query="继续",
    )
    requested_view = facade.bundle_service.build_memory_runtime_view(
        session_id=session_id,
        query="继续",
        memory_request_profile={"requested_memory_layers": ["conversation"]},
    )

    assert all(candidate.memory_layer != "conversation" for candidate in default_view.context_candidates)
    assert {candidate.memory_layer for candidate in requested_view.context_candidates} == {"conversation"}
    rendered = "\n".join(candidate.rendered_preview for candidate in requested_view.context_candidates)
    assert "已完成会话连续性检查" in rendered
    assert "本轮委派被限流" not in rendered


def test_memory_maintenance_without_agent_does_not_use_heuristic_fallback(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)

    receipt = facade.run_memory_maintenance_after_commit(
        session_id="session-i",
        messages=[{"role": "user", "content": "请记住：我偏好复杂问题先讲结论。"}],
    )

    assert receipt.status == "failed"
    assert receipt.durable_write_count == 0
    assert facade.memory_manager.list_notes() == []


def test_memory_manager_normalizes_incoming_note_slug_before_persisting(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    note = MemoryNote(
        slug="记住：以后复杂问题先给结论。",
        title="记住：以后复杂问题先给结论。",
        summary="以后复杂问题先给结论。",
        canonical_statement="以后复杂问题先给结论。",
        body="回答复杂问题时先给结论。",
        memory_type="project",
        memory_class="work",
    )

    path = facade.memory_manager.save_note(note)

    assert path.name == "记住-以后复杂问题先给结论.md"
    assert path.exists()


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

    receipt = facade.run_memory_maintenance_after_commit(
        session_id="session-contract-isolation",
        messages=messages,
    )
    assert receipt.status == "failed"
    assert receipt.durable_write_count == 0
    assert facade.memory_manager.list_notes() == []


def test_memory_request_and_scope_policy_follow_task_profile(tmp_path) -> None:
    _ = MemoryFacade(tmp_path)

    request = build_memory_request(
        task_id="task.memory.review",
        session_id="session-k",
        agent_id="agent:0",
        memory_request_profile={
            "requested_memory_layers": ["conversation", "state", "long_term"],
            "requested_topics": ["memory", "contracts"],
            "memory_priority": "high",
            "allow_long_term_memory": True,
        },
    )
    policy = build_memory_scope_policy(
        agent_id="agent:0",
        memory_request_profile={
            "requested_memory_layers": ["conversation", "state", "long_term"],
            "allow_long_term_memory": True,
        },
    )

    assert request.requested_memory_layers == ("conversation", "state", "long_term")
    assert request.requested_topics == ("memory", "contracts")
    assert request.allow_long_term_memory is True
    assert policy.allowed_layers == ("conversation", "state", "long_term")
    assert policy.allow_long_term_read is True


def test_memory_facade_builds_formal_memory_bundle(tmp_path) -> None:
    session_id = "session-l"
    facade = MemoryFacade(tmp_path)
    manager = facade.session_memory.manager(session_id)
    manager.overwrite(
        """# Key User Requests
_Stable instructions or constraints from the user within this session._
- 记忆系统要正式建模

# Key Results
_Current-turn outputs, conclusions, or artifacts that remain active._
- 已建立正式 MemoryBundle
"""
    )

    bundle = facade.bundle_service.build_memory_bundle(
        task_id="task.memory.bundle",
        session_id=session_id,
        agent_id="agent:0",
        query="请整理记忆系统正式边界",
        memory_request_profile={
            "requested_memory_layers": ["conversation"],
            "requested_topics": ["memory_bundle"],
        },
    )

    assert isinstance(bundle, MemoryBundle)
    assert bundle.authority == "memory_system.memory_bundle"
    assert bundle.selected_layers == ("conversation",)
    assert bundle.context_package
    assert bundle.runtime_view.read_only is True
    assert bundle.diagnostics["context_policy_attached"] is True


def test_memory_bundle_reuses_single_runtime_view_for_context_package(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    calls = {"runtime_view": 0}
    original = facade.bundle_service.build_memory_runtime_view

    def _counting_build_memory_runtime_view(**kwargs):
        calls["runtime_view"] += 1
        return original(**kwargs)

    facade.bundle_service.build_memory_runtime_view = _counting_build_memory_runtime_view  # type: ignore[method-assign]

    facade.bundle_service.build_memory_bundle(
        task_id="task.memory.single-read",
        session_id="session-single-read",
        agent_id="agent:0",
        memory_request_profile={"requested_memory_layers": ["conversation"]},
    )

    assert calls["runtime_view"] == 1


def test_context_budget_provider_failure_is_visible(tmp_path) -> None:
    def _broken_budget():
        raise RuntimeError("budget resolver unavailable")

    facade = MemoryFacade(tmp_path, context_budget_provider=_broken_budget)

    try:
        facade.bundle_service.build_memory_context_package_result(
            session_id="session-budget-failure",
            memory_request_profile={"requested_memory_layers": ["state"]},
        )
    except RuntimeError as exc:
        assert "budget resolver unavailable" in str(exc)
    else:
        raise AssertionError("Context budget provider failure was silently replaced with a default")


def test_context_package_does_not_expand_memory_layers_from_relevant_notes(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    note = MemoryNote(
        slug="explicit-long-term-only",
        title="长期记忆必须显式读取",
        summary="relevant_notes 不能自动打开 long_term。",
        canonical_statement="长期记忆读取必须由 read plan 授权。",
        body="候选可以被上层预选，但是否注入仍由显式读取计划控制。",
        memory_type="project",
        memory_class="work",
    )

    result = facade.bundle_service.build_memory_context_package_result(
        session_id="session-no-implicit-long-term",
        query="记忆规则是什么？",
        relevant_notes=[note],
    )

    assert result.package.model_visible_sections["relevant_durable_context"] == []
    assert result.diagnostics["context_candidate_count"] == 0


def test_context_package_requires_explicit_state_read_plan(tmp_path) -> None:
    session_id = "session-no-implicit-state"
    facade = MemoryFacade(tmp_path)
    manager = facade.session_memory.manager(session_id)
    manager.state_manager.overwrite(ProcessState(active_goal="不要默认注入 state"))

    result = facade.bundle_service.build_memory_context_package_result(
        session_id=session_id,
        query="继续",
    )

    assert result.package.model_visible_sections["active_process_context"] == []
    assert result.diagnostics["context_candidate_count"] == 0


def test_context_budget_provider_empty_payload_is_rejected(tmp_path) -> None:
    facade = MemoryFacade(tmp_path, context_budget_provider=lambda: {})

    try:
        facade.session_memory.context_controller("session-empty-budget")
    except ValueError as exc:
        assert "context budget provider returned an empty payload" in str(exc)
    else:
        raise AssertionError("Empty context budget provider payload was accepted")





