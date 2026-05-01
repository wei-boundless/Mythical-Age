from __future__ import annotations

from memory.facade import MemoryFacade
from memory_system import MemoryRuntimeView
from memory_system.contracts import MemoryContextCandidate
from context_policy import build_context_package_result
from structured_memory import MemoryNote
from structured_memory.process_state import ContextSlots, ProcessState


def test_context_policy_builds_package_from_memory_runtime_view(tmp_path) -> None:
    session_id = "context-policy-session"
    facade = MemoryFacade(tmp_path)
    manager = facade.session_memory.manager(session_id)
    manager.overwrite(
        """# Key User Requests
_Stable instructions or constraints from the user within this session._
- 用户要求记忆系统必须三层分明

# Key Results
_Current-turn outputs, conclusions, or artifacts that remain active._
- 已建立 MemoryRuntimeView
"""
    )
    manager.state_manager.overwrite(
        ProcessState(
            active_goal="Wire ContextPolicy",
            context_slots=ContextSlots(active_result_handle_id="result-context-policy"),
        )
    )
    note = MemoryNote(
        slug="context-policy-principle",
        title="长期记忆不能覆盖当前事实",
        summary="长期记忆只能作为可验证的上下文候选。",
        canonical_statement="长期记忆不能覆盖当前任务事实。",
        body="若长期记忆与当前文件或检索结果冲突，应相信当前观察。",
        memory_type="project",
        memory_class="work",
    )

    result = facade.build_memory_context_package_result(
        session_id=session_id,
        query="记忆系统原则是什么？",
        relevant_notes=[note],
    )
    package = result.package

    assert result.read_only is True
    assert result.authority == "context_policy_result"
    assert package.model_visible_sections["active_process_context"]
    assert package.model_visible_sections["hot_truth_window"]
    assert package.model_visible_sections["relevant_durable_context"]
    assert "result-context-policy" in "\n".join(package.model_visible_sections["active_process_context"])
    assert "三层分明" in "\n".join(package.model_visible_sections["hot_truth_window"])
    assert "长期记忆不能覆盖当前任务事实" in "\n".join(package.model_visible_sections["relevant_durable_context"])
    assert all(decision.decision == "include" for decision in result.decisions)
    assert result.diagnostics["memory_write_allowed"] is False


def test_context_policy_drops_long_term_before_state_when_budget_is_tight() -> None:
    state_candidate = MemoryContextCandidate(
        candidate_id="state-candidate",
        memory_layer="state",
        source="test",
        rendered_preview="active_result_handle_id: result-1",
        token_estimate=20,
        budget_class="preferred",
        requires_verification_before_use=False,
    )
    long_term_candidate = MemoryContextCandidate(
        candidate_id="long-term-candidate",
        memory_layer="long_term",
        source="test",
        rendered_preview="长期记忆候选" * 50,
        token_estimate=500,
        budget_class="optional",
        requires_verification_before_use=True,
    )
    view = MemoryRuntimeView(
        view_id="memory-runtime:test",
        session_id="test",
        context_candidates=(state_candidate, long_term_candidate),
    )

    result = build_context_package_result(
        view,
        available_context_tokens=60,
        reserved_output_tokens=20,
        long_term_token_cap=40,
    )

    included = {decision.candidate_id for decision in result.decisions if decision.decision == "include"}
    dropped = {decision.candidate_id for decision in result.decisions if decision.decision == "drop"}

    assert "state-candidate" in included
    assert "long-term-candidate" in dropped
    assert result.package.model_visible_sections["active_process_context"]
    assert not result.package.model_visible_sections["relevant_durable_context"]
    assert any("long_term_budget_cap_exceeded" in item for item in result.package.dropped_items)
