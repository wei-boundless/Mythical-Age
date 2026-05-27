from __future__ import annotations

import pytest

from task_system.orders.models import (
    ConversationTurn,
    ExecutionChannel,
    TaskOrder,
    TaskOrderRun,
)
from task_system.orders.legacy_runtime_adapter import attach_legacy_runtime_read_model
from task_system.orders.order_factory import TaskOrderFactory
from task_system.primitives import TaskActivationRequest, TaskLifecycle


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


def test_task_lifecycle_source_and_dispatch_are_separate() -> None:
    activation = TaskActivationRequest(
        activation_id="activation:test",
        session_id="session",
        source="explicit_requirement",
        dispatch="graph_node_dispatch",
        objective="Run graph node review",
        environment_id="env.writing",
    )
    lifecycle = TaskLifecycle(
        task_id="tasklife:test",
        session_id=activation.session_id,
        environment_id=activation.environment_id,
        source=activation.source,
        dispatch=activation.dispatch,
        objective=activation.objective,
        activation_id=activation.activation_id,
    )

    assert activation.source == "explicit_requirement"
    assert activation.dispatch == "graph_node_dispatch"
    assert lifecycle.source == activation.source
    assert lifecycle.dispatch == activation.dispatch
    assert lifecycle.authority == "task_system.task_lifecycle"


def test_specific_task_order_creation_writes_environment_into_lifecycle() -> None:
    creation = TaskOrderFactory().create_specific_task_order(
        session_id="session",
        task_record={
            "task_id": "task.test",
            "task_title": "Test Task",
            "environment_id": "env.writing",
        },
        objective="Write a review.",
    )

    assert creation.lifecycle_creation is not None
    assert creation.lifecycle_creation.lifecycle is not None
    assert creation.lifecycle_creation.runtime_assembly_request is not None
    assert creation.order_run is None
    assert creation.execution_channel is None
    assert creation.envelope is None
    assert creation.lifecycle_creation.lifecycle.environment_id == "env.writing"
    assert creation.lifecycle_creation.runtime_assembly_request.environment_ref == "env.writing"
    assert creation.lifecycle_creation.lifecycle.source == "explicit_requirement"
    assert creation.lifecycle_creation.lifecycle.dispatch == "order_dispatch"


def test_legacy_runtime_adapter_attaches_old_read_models_outside_factory() -> None:
    creation = TaskOrderFactory().create_specific_task_order(
        session_id="session",
        task_record={
            "task_id": "task.test",
            "task_title": "Test Task",
            "environment_id": "env.writing",
        },
        objective="Write a review.",
    )

    adapted = attach_legacy_runtime_read_model(creation)

    assert adapted.order_run is not None
    assert adapted.execution_channel is not None
    assert adapted.envelope is not None
    assert adapted.order_run.diagnostics["legacy_adapter"] is True
    assert adapted.envelope.context_package["legacy_adapter"] is True
    assert adapted.envelope.context_package["runtime_assembly_ref"] == adapted.lifecycle_creation.lifecycle.runtime_assembly_ref  # type: ignore[union-attr]
