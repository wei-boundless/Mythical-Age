from __future__ import annotations

import pytest

from task_system.orders.models import (
    ConversationTurn,
    ExecutionChannel,
    TaskOrder,
    TaskOrderRun,
)


def test_conversation_turn_is_not_task_order() -> None:
    turn = ConversationTurn(turn_id="turn:session:1", session_id="session")

    assert turn.authority == "conversation.turn"
    assert turn.interaction_kind == "chat_turn"
    assert turn.task_order_ref == ""


def test_task_order_rejects_chat_turn_kind() -> None:
    with pytest.raises(ValueError, match="chat_turn is not a TaskOrder kind"):
        TaskOrder(
            order_id="order:test",
            session_id="session",
            order_kind="chat_turn",  # type: ignore[arg-type]
            source="conversation_turn",
            source_ref="conversation.turn:turn:session:1",
            objective="hello",
        )


def test_task_order_run_and_channel_have_separate_identity() -> None:
    run = TaskOrderRun(run_id="run:test", order_id="order:test", session_id="session")
    channel = ExecutionChannel(
        channel_id="channel:test",
        order_run_id=run.run_id,
        order_id=run.order_id,
        session_id=run.session_id,
    )

    assert run.run_id != channel.channel_id
    assert channel.order_run_id == run.run_id
    assert channel.authority == "task_system.execution_channel"
