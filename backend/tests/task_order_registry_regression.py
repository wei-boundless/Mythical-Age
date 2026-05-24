from __future__ import annotations

from runtime.memory.state_index import RuntimeStateIndex
from task_system.orders.intent_decision import TaskIntentDecisionService
from task_system.orders.models import ConversationTurn
from task_system.orders.order_factory import TaskOrderFactory
from task_system.orders.order_registry import TaskOrderRegistry


def test_registry_persists_order_run_channel_and_reverse_task_run_binding(tmp_path) -> None:
    state_index = RuntimeStateIndex(tmp_path)
    registry = TaskOrderRegistry(state_index)
    turn = ConversationTurn(turn_id="turn:session:1", session_id="session")
    decision = TaskIntentDecisionService().decide(
        turn_id=turn.turn_id,
        message="请修改前端页面并运行测试。",
        task_selection={"selected_task_id": "task.dev.frontend_ui", "mode": "single_task"},
    )
    creation = TaskOrderFactory().create_from_conversation_turn(
        conversation_turn=turn,
        intent_decision=decision,
        message="请修改前端页面并运行测试。",
        task_selection={"selected_task_id": "task.dev.frontend_ui", "mode": "single_task"},
    )

    registry.upsert_creation(creation)
    assert creation.order is not None
    assert creation.order_run is not None
    assert creation.execution_channel is not None

    registry.bind_runtime(
        order_run_id=creation.order_run.run_id,
        task_run_id="taskrun:session:test",
        execution_channel_id=creation.execution_channel.channel_id,
        agent_run_id="agrun:taskrun:session:test:main",
    )

    projection = state_index.task_order_projection_for_task_run("taskrun:session:test")
    assert projection["projection_kind"] == "task_order"
    assert projection["task_order"]["order_kind"] == "specific_task"
    assert projection["task_order"]["task_id"] == "task.dev.frontend_ui"
    assert projection["task_order_run"]["task_run_id"] == "taskrun:session:test"
    assert projection["execution_channel"]["task_run_id"] == "taskrun:session:test"


def test_unbound_task_run_has_no_task_order_projection(tmp_path) -> None:
    state_index = RuntimeStateIndex(tmp_path)

    projection = state_index.task_order_projection_for_task_run("taskrun:legacy")

    assert projection is None
