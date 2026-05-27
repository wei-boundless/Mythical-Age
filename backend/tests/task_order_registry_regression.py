from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from task_system.lifecycle import TaskLifecycleCreation
from task_system.orders.intent_decision import TaskIntentDecisionService
from task_system.orders.models import (
    ConversationTurn,
    ExecutionChannel,
    TaskExecutionEnvelope,
    TaskIntentDecision,
    TaskOrder,
    TaskOrderDraft,
    TaskOrderRun,
)
from task_system.orders.legacy_runtime_adapter import attach_legacy_runtime_read_model
from task_system.orders.order_factory import TaskOrderFactory
from task_system.orders.order_registry import TaskOrderRegistry
from task_system.primitives import TaskActivationRequest, TaskLifecycle, TaskRuntimeAssemblyRequest


@dataclass(slots=True)
class InMemoryTaskOrderStore:
    turns: dict[str, ConversationTurn] = field(default_factory=dict)
    decisions: dict[str, TaskIntentDecision] = field(default_factory=dict)
    drafts: dict[str, TaskOrderDraft] = field(default_factory=dict)
    orders: dict[str, TaskOrder] = field(default_factory=dict)
    runs: dict[str, TaskOrderRun] = field(default_factory=dict)
    channels: dict[str, ExecutionChannel] = field(default_factory=dict)
    envelopes: dict[str, TaskExecutionEnvelope] = field(default_factory=dict)
    activations: dict[str, TaskActivationRequest] = field(default_factory=dict)
    lifecycles: dict[str, TaskLifecycle] = field(default_factory=dict)
    runtime_assembly_requests: dict[str, TaskRuntimeAssemblyRequest] = field(default_factory=dict)
    turn_by_order: dict[str, str] = field(default_factory=dict)
    decision_by_order: dict[str, str] = field(default_factory=dict)
    runs_by_order: dict[str, list[str]] = field(default_factory=dict)
    channel_by_order_run: dict[str, str] = field(default_factory=dict)
    envelope_by_order_run: dict[str, str] = field(default_factory=dict)
    lifecycle_by_order: dict[str, str] = field(default_factory=dict)
    lifecycle_by_activation: dict[str, str] = field(default_factory=dict)

    def upsert_conversation_turn(self, turn: ConversationTurn) -> None:
        self.turns[turn.turn_id] = turn
        if turn.task_order_ref:
            self.turn_by_order[turn.task_order_ref] = turn.turn_id

    def upsert_task_intent_decision(self, decision: TaskIntentDecision) -> None:
        self.decisions[decision.decision_id] = decision
        if decision.created_order_id:
            self.decision_by_order[decision.created_order_id] = decision.decision_id

    def upsert_task_order_draft(self, draft: TaskOrderDraft) -> None:
        self.drafts[draft.draft_id] = draft

    def upsert_task_order(self, order: TaskOrder) -> None:
        self.orders[order.order_id] = order

    def upsert_task_order_run(self, run: TaskOrderRun) -> None:
        self.runs[run.run_id] = run
        self.runs_by_order.setdefault(run.order_id, [])
        if run.run_id not in self.runs_by_order[run.order_id]:
            self.runs_by_order[run.order_id].append(run.run_id)
        if run.primary_execution_channel_id:
            self.channel_by_order_run[run.run_id] = run.primary_execution_channel_id

    def upsert_execution_channel(self, channel: ExecutionChannel) -> None:
        self.channels[channel.channel_id] = channel
        self.channel_by_order_run[channel.order_run_id] = channel.channel_id

    def upsert_task_execution_envelope(self, envelope: TaskExecutionEnvelope) -> None:
        self.envelopes[envelope.envelope_id] = envelope
        self.envelope_by_order_run[envelope.order_run_id] = envelope.envelope_id

    def upsert_task_activation_request(self, request: TaskActivationRequest) -> None:
        self.activations[request.activation_id] = request

    def upsert_task_lifecycle(self, lifecycle: TaskLifecycle) -> None:
        self.lifecycles[lifecycle.task_id] = lifecycle
        if lifecycle.activation_id:
            self.lifecycle_by_activation[lifecycle.activation_id] = lifecycle.task_id
        order_id = str(dict(lifecycle.legacy_refs or {}).get("task_order_id") or "")
        if order_id:
            self.lifecycle_by_order[order_id] = lifecycle.task_id

    def upsert_task_runtime_assembly_request(self, request: TaskRuntimeAssemblyRequest) -> None:
        self.runtime_assembly_requests[request.request_id] = request

    def claim_task_order_run_for_execution(
        self,
        *,
        order_run_id: str,
        diagnostics: dict[str, Any] | None = None,
    ) -> tuple[bool, str]:
        run = self.runs.get(order_run_id)
        if run is None:
            return False, "missing"
        if run.status != "created":
            return False, run.status
        self.runs[order_run_id] = TaskOrderRun(**{**run.to_dict(), "status": "running"})
        return True, "running"

    def get_task_order_run(self, order_run_id: str) -> TaskOrderRun | None:
        return self.runs.get(order_run_id)

    def get_task_order(self, order_id: str) -> TaskOrder | None:
        return self.orders.get(order_id)

    def get_execution_channel(self, channel_id: str) -> ExecutionChannel | None:
        return self.channels.get(channel_id)

    def get_execution_channel_by_order_run(self, order_run_id: str) -> ExecutionChannel | None:
        channel_id = self.channel_by_order_run.get(order_run_id, "")
        return self.get_execution_channel(channel_id) if channel_id else None

    def get_task_execution_envelope_by_order_run(self, order_run_id: str) -> TaskExecutionEnvelope | None:
        envelope_id = self.envelope_by_order_run.get(order_run_id, "")
        return self.envelopes.get(envelope_id) if envelope_id else None

    def get_conversation_turn_by_order(self, order_id: str) -> ConversationTurn | None:
        turn_id = self.turn_by_order.get(order_id, "")
        return self.turns.get(turn_id) if turn_id else None

    def get_task_intent_decision_by_order(self, order_id: str) -> TaskIntentDecision | None:
        decision_id = self.decision_by_order.get(order_id, "")
        return self.decisions.get(decision_id) if decision_id else None

    def list_turn_intent_decisions(self, turn_id: str) -> list[TaskIntentDecision]:
        return [item for item in self.decisions.values() if item.turn_id == turn_id]

    def list_order_runs(self, order_id: str) -> list[TaskOrderRun]:
        return [self.runs[item] for item in self.runs_by_order.get(order_id, []) if item in self.runs]

    def get_task_activation_request(self, activation_id: str) -> TaskActivationRequest | None:
        return self.activations.get(activation_id)

    def get_task_lifecycle(self, task_id: str) -> TaskLifecycle | None:
        return self.lifecycles.get(task_id)

    def get_task_lifecycle_by_activation(self, activation_id: str) -> TaskLifecycle | None:
        task_id = self.lifecycle_by_activation.get(activation_id, "")
        return self.get_task_lifecycle(task_id) if task_id else None

    def get_task_lifecycle_by_order(self, order_id: str) -> TaskLifecycle | None:
        task_id = self.lifecycle_by_order.get(order_id, "")
        return self.get_task_lifecycle(task_id) if task_id else None

    def get_task_runtime_assembly_request(self, request_id: str) -> TaskRuntimeAssemblyRequest | None:
        return self.runtime_assembly_requests.get(request_id)

    def lifecycle_creation_for_order(self, order_id: str) -> TaskLifecycleCreation | None:
        lifecycle = self.get_task_lifecycle_by_order(order_id)
        if lifecycle is None:
            return None
        activation = self.get_task_activation_request(lifecycle.activation_id)
        runtime_assembly_request = self.get_task_runtime_assembly_request(lifecycle.runtime_assembly_ref)
        return TaskLifecycleCreation(
            activation_request=activation,
            lifecycle=lifecycle,
            runtime_assembly_request=runtime_assembly_request,
        )

    def bind_task_order_run_to_task_run(
        self,
        *,
        order_run_id: str,
        task_run_id: str,
        execution_channel_id: str = "",
        coordination_run_id: str = "",
        agent_run_id: str = "",
        status: str = "running",
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        run = self.runs[order_run_id]
        self.runs[order_run_id] = TaskOrderRun(**{**run.to_dict(), "task_run_id": task_run_id, "status": status})
        channel_id = execution_channel_id or run.primary_execution_channel_id
        if channel_id and channel_id in self.channels:
            channel = self.channels[channel_id]
            self.channels[channel_id] = ExecutionChannel(**{**channel.to_dict(), "task_run_id": task_run_id, "status": status})

    def update_task_order_run_status(
        self,
        *,
        order_run_id: str,
        status: str,
        terminal_reason: str = "",
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        run = self.runs[order_run_id]
        self.runs[order_run_id] = TaskOrderRun(**{**run.to_dict(), "status": status, "terminal_reason": terminal_reason})

    def update_task_order_runtime_status(
        self,
        *,
        task_run_id: str,
        status: str,
        terminal_reason: str = "",
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        for run in self.runs.values():
            if run.task_run_id == task_run_id:
                self.update_task_order_run_status(
                    order_run_id=run.run_id,
                    status=status,
                    terminal_reason=terminal_reason,
                    diagnostics=diagnostics,
                )


def test_registry_persists_order_read_model_and_task_lifecycle_without_runtime_index() -> None:
    store = InMemoryTaskOrderStore()
    registry = TaskOrderRegistry(store)
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
        task_selection={
            "selected_task_id": "task.dev.frontend_ui",
            "mode": "single_task",
            "environment_id": "env.vibe_coding",
        },
    )
    creation = attach_legacy_runtime_read_model(creation)

    registry.upsert_creation(creation)

    assert creation.order is not None
    assert creation.order_run is not None
    assert creation.execution_channel is not None
    assert creation.lifecycle_creation is not None
    assert creation.lifecycle_creation.lifecycle is not None

    lifecycle = registry.lifecycle_registry.get_lifecycle_by_order(creation.order.order_id)
    assert lifecycle is not None
    assert lifecycle.source == "explicit_requirement"
    assert lifecycle.dispatch == "order_dispatch"
    assert lifecycle.environment_id == "env.vibe_coding"
    assert lifecycle.runtime_assembly_ref
    assert lifecycle.legacy_refs["task_order_id"] == creation.order.order_id
    assert registry.lifecycle_registry.get_runtime_assembly_request(lifecycle.runtime_assembly_ref) is not None

    reconstructed = registry.creation_for_order(creation.order.order_id)
    assert reconstructed is not None
    assert reconstructed.lifecycle_creation is not None
    assert reconstructed.lifecycle_creation.lifecycle == lifecycle
    assert reconstructed.lifecycle_creation.runtime_assembly_request is not None


def test_registry_bind_runtime_updates_legacy_order_read_model_only() -> None:
    store = InMemoryTaskOrderStore()
    registry = TaskOrderRegistry(store)
    creation = TaskOrderFactory().create_specific_task_order(
        session_id="session",
        task_record={
            "task_id": "task.dev.frontend_ui",
            "task_title": "Frontend UI",
            "environment_id": "env.vibe_coding",
        },
        objective="请修改前端页面并运行测试。",
    )
    creation = attach_legacy_runtime_read_model(creation)
    registry.upsert_creation(creation)
    assert creation.order_run is not None
    assert creation.execution_channel is not None

    registry.bind_runtime(
        order_run_id=creation.order_run.run_id,
        task_run_id="taskrun:session:test",
        execution_channel_id=creation.execution_channel.channel_id,
    )

    updated_run = store.get_task_order_run(creation.order_run.run_id)
    updated_channel = store.get_execution_channel(creation.execution_channel.channel_id)
    assert updated_run is not None
    assert updated_channel is not None
    assert updated_run.task_run_id == "taskrun:session:test"
    assert updated_channel.task_run_id == "taskrun:session:test"
