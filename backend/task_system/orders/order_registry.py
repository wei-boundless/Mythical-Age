from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime.memory.state_index import RuntimeStateIndex

from .models import (
    ConversationTurn,
    ExecutionChannel,
    TaskExecutionEnvelope,
    TaskIntentDecision,
    TaskOrder,
    TaskOrderDraft,
    TaskOrderRun,
)
from .order_factory import TaskOrderCreation


@dataclass(frozen=True, slots=True)
class TaskOrderRegistry:
    """Thin registry facade over RuntimeStateIndex task-order buckets."""

    state_index: RuntimeStateIndex
    authority: str = "task_system.task_order_registry"

    def upsert_conversation_turn(self, turn: ConversationTurn) -> None:
        self.state_index.upsert_conversation_turn(turn)

    def upsert_intent_decision(self, decision: TaskIntentDecision) -> None:
        self.state_index.upsert_task_intent_decision(decision)

    def upsert_draft(self, draft: TaskOrderDraft) -> None:
        self.state_index.upsert_task_order_draft(draft)

    def upsert_order(self, order: TaskOrder) -> None:
        self.state_index.upsert_task_order(order)

    def upsert_order_run(self, run: TaskOrderRun) -> None:
        self.state_index.upsert_task_order_run(run)

    def upsert_execution_channel(self, channel: ExecutionChannel) -> None:
        self.state_index.upsert_execution_channel(channel)

    def upsert_task_execution_envelope(self, envelope: TaskExecutionEnvelope) -> None:
        self.state_index.upsert_task_execution_envelope(envelope)

    def claim_order_run_for_execution(
        self,
        *,
        order_run_id: str,
        diagnostics: dict[str, Any] | None = None,
    ) -> tuple[bool, str]:
        return self.state_index.claim_task_order_run_for_execution(
            order_run_id=order_run_id,
            diagnostics=diagnostics,
        )

    def creation_for_order_run(self, order_run_id: str) -> TaskOrderCreation | None:
        run = self.state_index.get_task_order_run(order_run_id)
        if run is None:
            return None
        order = self.state_index.get_task_order(run.order_id)
        if order is None:
            return None
        channel = (
            self.state_index.get_execution_channel(run.primary_execution_channel_id)
            if run.primary_execution_channel_id
            else self.state_index.get_execution_channel_by_order_run(run.run_id)
        )
        envelope = self.state_index.get_task_execution_envelope_by_order_run(run.run_id)
        turn = self.state_index.get_conversation_turn_by_order(order.order_id)
        decision = self.state_index.get_task_intent_decision_by_order(order.order_id)
        decisions = self.state_index.list_turn_intent_decisions(turn.turn_id) if turn is not None and decision is None else []
        decision = decision or (decisions[-1] if decisions else None)
        if turn is None or decision is None:
            return None
        return TaskOrderCreation(
            conversation_turn=turn,
            intent_decision=decision,
            order=order,
            order_run=run,
            execution_channel=channel,
            envelope=envelope,
        )

    def creation_for_order(self, order_id: str) -> TaskOrderCreation | None:
        runs = self.state_index.list_order_runs(order_id)
        if not runs:
            return None
        return self.creation_for_order_run(runs[-1].run_id)

    def upsert_creation(self, creation: TaskOrderCreation) -> None:
        self.upsert_conversation_turn(creation.conversation_turn)
        self.upsert_intent_decision(creation.intent_decision)
        if creation.draft is not None:
            self.upsert_draft(creation.draft)
        if creation.order is not None:
            self.upsert_order(creation.order)
        if creation.order_run is not None:
            self.upsert_order_run(creation.order_run)
        if creation.execution_channel is not None:
            self.upsert_execution_channel(creation.execution_channel)
        if creation.envelope is not None:
            self.upsert_task_execution_envelope(creation.envelope)

    def bind_runtime(
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
        self.state_index.bind_task_order_run_to_task_run(
            order_run_id=order_run_id,
            task_run_id=task_run_id,
            execution_channel_id=execution_channel_id,
            coordination_run_id=coordination_run_id,
            agent_run_id=agent_run_id,
            status=status,
            diagnostics=diagnostics,
        )

    def finish_order_run(
        self,
        *,
        order_run_id: str,
        status: str,
        terminal_reason: str = "",
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        self.state_index.update_task_order_run_status(
            order_run_id=order_run_id,
            status=status,
            terminal_reason=terminal_reason,
            diagnostics=diagnostics,
        )

    def sync_runtime_terminal(
        self,
        *,
        task_run_id: str,
        status: str,
        terminal_reason: str = "",
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        self.state_index.update_task_order_runtime_status(
            task_run_id=task_run_id,
            status=status,
            terminal_reason=terminal_reason,
            diagnostics=diagnostics,
        )
