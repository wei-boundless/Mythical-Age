from __future__ import annotations

from response_system import AssistantOutputBoundary
from response_system.classification.classifier import classify_output_candidate


def _classify(text: str):
    boundary = AssistantOutputBoundary()
    boundary.ingest_ai_update(text, has_tool_calls=False)
    boundary.finalize_segment(fallback_content=text)
    return boundary.build_response(user_message="为我写一个贪吃蛇小游戏")


def test_execution_promise_without_tool_receipt_is_not_stable_answer() -> None:
    response = _classify(
        "收到。这次我会直接用文件工具创建 snake.html，然后用 ls -l "
        "当场验证文件是否真正落盘，把终端反馈展示给你确认。开始"
    )

    assert response.selected_channel == "fallback_answer"
    assert response.canonical_state == "progress_only"
    assert response.persist_policy == "persist_debug_only"
    assert response.fallback_reason == "no_receipt_tool_claim"
    assert response.canonical_answer == "当前没有可验证的执行结果。"


def test_file_creation_claim_without_tool_receipt_is_not_stable_answer() -> None:
    response = _classify("写了，已经完成。snake.html 已经落盘。")

    assert response.selected_channel == "fallback_answer"
    assert response.canonical_state == "progress_only"
    assert response.persist_policy == "persist_debug_only"
    assert response.fallback_reason == "no_receipt_tool_claim"


def test_real_conclusion_still_survives_progress_guard() -> None:
    response = _classify("结论：系统把进度话术误判为稳定答案。")

    assert response.selected_channel == "answer_candidate"
    assert response.canonical_state == "stable_answer"
    assert response.persist_policy == "persist_canonical"
    assert response.canonical_answer == "系统把进度话术误判为稳定答案。"


def test_web_search_json_is_not_misclassified_as_visible_summary() -> None:
    candidate = classify_output_candidate(
        text='{"ok":true,"query":"黄金价格 今日 2026","response_time":0.96,"request_id":"abc","results":[{"title":"Gold price today","content":"Gold opened at $4569.30 and rose to $4711.90."}]}',
        route="builtin_tool_lane",
        source="tool_result",
        tool_name="web_search",
        allow_unlabeled_answer=True,
        has_tool_receipt=True,
    )

    assert candidate is not None
    assert candidate.channel == "tool_raw_output"
