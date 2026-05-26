from __future__ import annotations

from memory_system import MemoryFacade
from memory_system.contracts import MemoryContextCandidate
from memory_system.runtime_view import MemoryRuntimeView
from context_system.policy import build_context_package_result
from memory_system.storage.models import MemoryNote
from memory_system.storage.process_state import ContextSlots, ProcessState
from token_accounting import count_text_tokens


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

    result = facade.bundle_service.build_memory_context_package_result(
        session_id=session_id,
        query="记忆系统原则是什么？",
        relevant_notes=[note],
    )
    package = result.package

    assert result.read_only is True
    assert result.authority == "context_policy_result"
    assert package.model_visible_sections["active_process_context"]
    assert not package.model_visible_sections["hot_truth_window"]
    assert package.model_visible_sections["relevant_durable_context"]
    assert "result-context-policy" in "\n".join(package.model_visible_sections["active_process_context"])
    assert "长期记忆不能覆盖当前任务事实" in "\n".join(package.model_visible_sections["relevant_durable_context"])
    assert all(decision.decision == "include" for decision in result.decisions)
    assert result.diagnostics["memory_write_allowed"] is False


def test_context_policy_result_reuses_supplied_memory_runtime_view(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    candidate = MemoryContextCandidate(
        candidate_id="supplied-state",
        memory_layer="state",
        source="test",
        rendered_preview="active_result_handle_id: supplied-result",
        token_estimate=20,
        budget_class="preferred",
        requires_verification_before_use=False,
    )
    supplied_view = MemoryRuntimeView(
        view_id="memory-runtime:supplied",
        session_id="context-policy-session",
        context_candidates=(candidate,),
    )

    def _fail_rebuild(**_kwargs):
        raise AssertionError("memory runtime view should be reused")

    facade.bundle_service.build_memory_runtime_view = _fail_rebuild  # type: ignore[method-assign]

    result = facade.bundle_service.build_memory_context_package_result(
        session_id="context-policy-session",
        query="复用上下文",
        memory_view=supplied_view,
    )

    assert result.package.model_visible_sections["active_process_context"]
    assert "supplied-result" in "\n".join(result.package.model_visible_sections["active_process_context"])


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


def test_context_policy_accounts_retrieval_evidence_in_budget() -> None:
    state_candidate = MemoryContextCandidate(
        candidate_id="state-candidate",
        memory_layer="state",
        source="test",
        rendered_preview="active_result_handle_id: result-1",
        token_estimate=20,
        budget_class="preferred",
        requires_verification_before_use=False,
    )
    view = MemoryRuntimeView(
        view_id="memory-runtime:retrieval-budget",
        session_id="test",
        context_candidates=(state_candidate,),
    )

    result = build_context_package_result(
        view,
        retrieval_results=[
            {"source": "knowledge/a.md", "text": "A" * 120},
            {"source": "knowledge/b.md", "text": "B" * 2000},
        ],
        available_context_tokens=120,
        reserved_output_tokens=20,
        long_term_token_cap=40,
    )

    retrieval_items = result.package.model_visible_sections["retrieval_evidence"]
    assert retrieval_items
    assert result.package.token_accounting["retrieval_tokens"] > 0
    assert result.diagnostics["retrieval_evidence_dropped_count"] >= 1
    assert any("retrieval_budget_exceeded" in item for item in result.package.dropped_items)


def test_context_policy_uses_shared_token_counter_for_retrieval_accounting() -> None:
    text = "这是一个用于验证统一 token 计数路径的检索证据片段。"
    view = MemoryRuntimeView(
        view_id="memory-runtime:token-counter",
        session_id="test",
        context_candidates=(),
    )

    result = build_context_package_result(
        view,
        retrieval_results=[{"source": "knowledge/a.md", "text": text}],
        available_context_tokens=1000,
        reserved_output_tokens=100,
        long_term_token_cap=40,
    )

    rendered = result.package.model_visible_sections["retrieval_evidence"][0]
    assert result.package.token_accounting["retrieval_tokens"] == count_text_tokens(rendered)


