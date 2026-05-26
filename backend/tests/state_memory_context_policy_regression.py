from __future__ import annotations

from memory_system import MemoryFacade
from memory_system.contracts import MemoryContextCandidate
from memory_system.runtime_view import MemoryRuntimeView
from context_system.policy import build_context_package_result
from context_system.models.context_models import hash_context_section_package
from memory_system.storage.models import MemoryNote
from memory_system.storage.process_state import ContextSlots, ProcessState
from prompting.builder import _render_context_package_block
from runtime.shared.context_manager import _render_context_policy_block
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
        memory_request_profile={
            "requested_memory_layers": ["state", "long_term"],
            "allow_long_term_memory": True,
        },
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
    assert result.sealed_receipt.read_only is True
    assert package.sealed_receipt == result.sealed_receipt
    assert result.sealed_receipt.memory_runtime_view_ref == result.diagnostics["memory_runtime_view_ref"]
    assert result.sealed_receipt.package_sha256 == hash_context_section_package(package.model_visible_sections)
    assert set(result.sealed_receipt.included_candidate_ids) == {decision.candidate_id for decision in result.decisions}


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
    assert result.sealed_receipt.included_candidate_ids == ("supplied-state",)


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
    assert set(result.sealed_receipt.included_candidate_ids) == included
    assert set(result.sealed_receipt.dropped_candidate_ids) == dropped
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
    included_hashes = {
        entry.rendered_sha256
        for entry in result.sealed_receipt.included_entries
        if entry.source_kind == "retrieval_evidence"
    }
    assert included_hashes == set(result.sealed_receipt.section_item_hashes["retrieval_evidence"])


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


def test_context_policy_sealed_receipt_allows_only_included_candidate_content() -> None:
    included_candidate = MemoryContextCandidate(
        candidate_id="allowed-state",
        memory_layer="state",
        source="test",
        content_ref="state:allowed",
        rendered_preview="active_result_handle_id: allowed-result",
        token_estimate=20,
        budget_class="required",
        requires_verification_before_use=False,
    )
    dropped_candidate = MemoryContextCandidate(
        candidate_id="denied-long-term",
        memory_layer="long_term",
        source="test",
        content_ref="note:denied",
        rendered_preview="这条长期记忆因为预算不足不能进入模型可见上下文。" * 20,
        token_estimate=400,
        budget_class="optional",
        requires_verification_before_use=True,
    )
    view = MemoryRuntimeView(
        view_id="memory-runtime:sealed-ledger",
        session_id="test",
        context_candidates=(included_candidate, dropped_candidate),
    )

    result = build_context_package_result(
        view,
        available_context_tokens=60,
        reserved_output_tokens=20,
        long_term_token_cap=30,
    )

    rendered_model_context = "\n".join(
        item
        for items in result.package.model_visible_sections.values()
        for item in items
    )
    included_by_policy = {entry.candidate_id for entry in result.sealed_receipt.included_entries}
    dropped_by_policy = {entry.candidate_id for entry in result.sealed_receipt.dropped_entries}

    assert "allowed-result" in rendered_model_context
    assert "预算不足不能进入模型可见上下文" not in rendered_model_context
    assert included_by_policy == {"allowed-state"}
    assert dropped_by_policy == {"denied-long-term"}
    assert all(entry.rendered_sha256 for entry in result.sealed_receipt.included_entries)
    assert all(not entry.rendered_sha256 for entry in result.sealed_receipt.dropped_entries)
    assert result.to_dict()["sealed_receipt"]["included_candidate_ids"] == ["allowed-state"]


def test_sealed_context_receipt_rejects_tampered_model_visible_sections() -> None:
    candidate = MemoryContextCandidate(
        candidate_id="sealed-state",
        memory_layer="state",
        source="test",
        rendered_preview="active_result_handle_id: sealed-result",
        token_estimate=20,
        budget_class="required",
        requires_verification_before_use=False,
    )
    view = MemoryRuntimeView(
        view_id="memory-runtime:tamper-check",
        session_id="test",
        context_candidates=(candidate,),
    )
    result = build_context_package_result(view)

    result.package.model_visible_sections["active_process_context"].append("unauthorized injected memory")
    tampered_payload = result.to_dict()

    try:
        _render_context_package_block(result.package, include_durable_context=True)
    except ValueError as exc:
        assert "sealed receipt" in str(exc)
    else:
        raise AssertionError("Prompt builder rendered a tampered sealed context package")

    try:
        _render_context_policy_block(tampered_payload)
    except ValueError as exc:
        assert "sealed receipt" in str(exc)
    else:
        raise AssertionError("Runtime context renderer accepted tampered sealed context package")


