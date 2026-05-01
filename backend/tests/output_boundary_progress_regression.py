from __future__ import annotations

from output_boundary import AssistantOutputBoundary


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
