from __future__ import annotations

from task_system.orders.intent_decision import TaskIntentDecisionService


def test_discussion_stays_chat_turn() -> None:
    decision = TaskIntentDecisionService().decide(
        turn_id="turn:session:1",
        message="我们先讨论一下任务系统设计方案。",
        task_selection={},
    )

    assert decision.decision == "chat_turn"
    assert decision.created_order_id == ""


def test_agent_mode_projection_is_weak_signal_only() -> None:
    decision = TaskIntentDecisionService().decide(
        turn_id="turn:session:1",
        message="你好，解释一下当前页面。",
        task_selection={
            "agent_id": "agent:0",
            "agent_profile_id": "main_interactive_agent",
            "runtime_lane": "full_interactive",
        },
    )

    assert decision.decision == "chat_turn"
    assert "main_agent_mode_projection" in decision.weak_signals
    assert not decision.hard_signals


def test_specific_task_selection_is_hard_signal_when_run_mode_is_explicit() -> None:
    decision = TaskIntentDecisionService().decide(
        turn_id="turn:session:1",
        message="请执行这个任务。",
        task_selection={"selected_task_id": "task.dev.frontend_ui", "mode": "single_task"},
    )

    assert decision.decision == "executable_task"
    assert "legacy_task_selection:selected_task_id" in decision.hard_signals
