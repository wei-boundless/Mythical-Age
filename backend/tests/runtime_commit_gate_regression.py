from __future__ import annotations

from orchestration.commit_gate import build_assistant_session_message_commit_decision


def test_assistant_commit_blocks_missing_answer_fallback() -> None:
    decision = build_assistant_session_message_commit_decision(
        session_id="session-1",
        task_run_id="taskrun-1",
        task_id="turn-1",
        content="当前尚未形成可直接展示的结论，请继续细化问题或提供更多上下文。",
        answer_channel="fallback_answer",
        answer_source="runtime_directive:model_response",
        answer_canonical_state="missing_answer",
        answer_persist_policy="do_not_persist",
        answer_fallback_reason="generic_missing_answer",
    )

    assert decision.commit_allowed is False
    assert decision.status == "blocked"
    assert decision.reason == "missing_answer_not_committable"
    assert decision.commit_candidate.allowed is False


def test_assistant_commit_allows_stable_answer() -> None:
    decision = build_assistant_session_message_commit_decision(
        session_id="session-1",
        task_run_id="taskrun-1",
        task_id="turn-1",
        content="这是可以展示的结论。",
        answer_channel="answer_candidate",
        answer_source="runtime_directive:model_response",
        answer_canonical_state="stable_answer",
        answer_persist_policy="persist_canonical",
    )

    assert decision.commit_allowed is True
    assert decision.status == "allowed"
    assert decision.reason == "assistant_session_message_allowed"


def test_assistant_commit_allows_visible_progress_without_memory_persistence() -> None:
    decision = build_assistant_session_message_commit_decision(
        session_id="session-1",
        task_run_id="taskrun-1",
        task_id="turn-1",
        content="本轮运行时间达到上限，所以先停止继续调用工具。",
        answer_channel="answer_candidate",
        answer_source="harness_loop_control",
        answer_canonical_state="progress_only",
        answer_persist_policy="persist_debug_only",
        answer_fallback_reason="runtime_budget_exhausted",
    )

    assert decision.commit_allowed is True
    assert decision.status == "allowed"
    assert decision.reason == "assistant_session_message_allowed"


