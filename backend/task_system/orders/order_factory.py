from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

from .execution_channel import create_execution_channel
from .intent_decision import decision_with_created_order
from .models import (
    ConversationTurn,
    ExecutionChannel,
    TaskExecutionEnvelope,
    TaskIntentDecision,
    TaskOrder,
    TaskOrderDraft,
    TaskOrderRun,
)


@dataclass(frozen=True, slots=True)
class TaskOrderCreation:
    conversation_turn: ConversationTurn
    intent_decision: TaskIntentDecision
    order: TaskOrder | None = None
    order_run: TaskOrderRun | None = None
    execution_channel: ExecutionChannel | None = None
    envelope: TaskExecutionEnvelope | None = None
    draft: TaskOrderDraft | None = None

    def projection(self) -> dict[str, Any]:
        return {
            "conversation_turn": self.conversation_turn.to_dict(),
            "task_intent_decision": self.intent_decision.to_dict(),
            "task_order": self.order.to_dict() if self.order is not None else None,
            "task_order_run": self.order_run.to_dict() if self.order_run is not None else None,
            "execution_channel": self.execution_channel.to_dict() if self.execution_channel is not None else None,
            "task_execution_envelope": self.envelope.to_dict() if self.envelope is not None else None,
            "task_order_draft": self.draft.to_dict() if self.draft is not None else None,
            "authority": "task_system.task_order_creation_projection",
        }


@dataclass(frozen=True, slots=True)
class TaskOrderFactory:
    """Creates task authority objects from already classified task intent."""

    authority: str = "task_system.task_order_factory"

    def create_specific_task_order(
        self,
        *,
        session_id: str,
        task_record: dict[str, Any],
        objective: str = "",
        source: str = "task_library",
        source_ref: str = "",
        domain_id: str = "",
        flow_contract_binding: dict[str, Any] | None = None,
        execution_policy: dict[str, Any] | None = None,
        order_intent: dict[str, Any] | None = None,
        idempotency_key: str = "",
    ) -> TaskOrderCreation:
        task = dict(task_record or {})
        task_id = str(task.get("task_id") or "").strip()
        if not task_id:
            raise ValueError("specific task order requires task_id")
        task_title = str(task.get("task_title") or task_id).strip() or task_id
        resolved_domain_id = str(domain_id or task.get("domain_id") or "").strip()
        explicit_intent = dict(order_intent or {})
        flow_binding = dict(flow_contract_binding or {})
        execution = dict(execution_policy or {})
        now = time.time()
        turn_id = str(explicit_intent.get("turn_id") or f"taskorder:{uuid.uuid4().hex[:12]}")
        order_kind = "specific_task"
        order_id = f"order:{order_kind}:{uuid.uuid4().hex[:12]}"
        order_run_id = f"orderrun:{uuid.uuid4().hex[:12]}"
        decision = TaskIntentDecision(
            decision_id=f"intent:{turn_id}:{uuid.uuid4().hex[:8]}",
            turn_id=turn_id,
            decision="executable_task",
            confidence=1.0,
            hard_signals=("task_orders_api:create_specific_task_order",),
            contract_signals=("specific_task_record",),
            evidence_spans=(
                {"source": "task_record.task_id", "text": task_id},
                {"source": "task_record.task_title", "text": task_title},
            ),
            created_order_id=order_id,
            reason="A task library action explicitly created a specific task order.",
            created_at=now,
            metadata={
                "classifier": "structured_task_order_api",
                "source": source,
                "domain_id": resolved_domain_id,
            },
        )
        turn = ConversationTurn(
            turn_id=turn_id,
            session_id=session_id,
            interaction_kind="executable_task",
            task_intent_decision_id=decision.decision_id,
            task_order_ref=order_id,
            created_at=now,
            status="created",
            metadata={
                "source": source,
                "source_ref": source_ref or task_id,
                "task_id": task_id,
            },
        )
        task_policy = dict(task.get("task_policy") or {})
        input_contract = {
            "objective": str(objective or explicit_intent.get("objective") or task.get("description") or task_title).strip(),
            "task_record": _safe_projection(task),
            "task_selection_projection": {
                "selected_task_id": task_id,
                "domain_id": resolved_domain_id,
                "label": task_title,
                "mode": "specific_task",
            },
            "task_order_intent": _safe_projection(explicit_intent),
        }
        output_contract = {
            "contract_id": str(task.get("output_contract_id") or "").strip(),
            "flow_contract_binding": _safe_projection(flow_binding),
        }
        role_contract = {
            "source": "specific_task_record",
            "task_definition_ref": task_id,
            "title": task_title,
            "description": str(task.get("description") or "").strip(),
            "input_contract_id": str(task.get("input_contract_id") or "").strip(),
            "output_contract_id": str(task.get("output_contract_id") or "").strip(),
            "flow_contract_id": str(flow_binding.get("flow_contract_id") or task.get("default_flow_contract_id") or "").strip(),
            "workflow_id": str(task.get("default_workflow_id") or "").strip(),
            "effective_role_note": "Use this task contract for this invocation only; do not rewrite the agent profile.",
        }
        acceptance_policy = {
            "acceptance_profile_id": str(task.get("acceptance_profile_id") or "").strip(),
            "verification_gate_profile": str(flow_binding.get("verification_gate_profile") or "").strip(),
            "fallback_policy": str(flow_binding.get("fallback_policy") or "").strip(),
        }
        artifact_policy = dict(task_policy.get("artifact_policy") or {})
        executor_policy = {
            **execution,
            "executor_type": "agent",
            "task_execution_policy_ref": str(execution.get("policy_id") or "").strip(),
            "default_agent_id": str(execution.get("default_agent_id") or "agent:0").strip() or "agent:0",
            "execution_chain_type": str(execution.get("execution_chain_type") or "single_agent_chain").strip(),
            "runtime_agent_selection_policy": str(execution.get("runtime_agent_selection_policy") or "orchestration_default").strip(),
            "allow_worker_agent_spawn": bool(execution.get("allow_worker_agent_spawn") or False),
        }
        context_policy = {}
        order = TaskOrder(
            order_id=order_id,
            session_id=session_id,
            order_kind=order_kind,
            source=source,
            source_ref=source_ref or f"task_system.specific_task:{task_id}",
            objective=str(objective or explicit_intent.get("objective") or task.get("description") or task_title).strip() or task_title,
            task_id=task_id,
            task_definition_ref=task_id,
            input_contract=input_contract,
            output_contract=output_contract,
            role_contract=role_contract,
            acceptance_policy=acceptance_policy,
            artifact_policy=artifact_policy,
            executor_policy=executor_policy,
            context_policy=context_policy,
            status="accepted",
            idempotency_key=idempotency_key or _idempotency_key(
                conversation_turn=turn,
                order_kind=order_kind,
                task_id=task_id,
                message=str(objective or task_title),
            ),
            created_at=now,
            updated_at=now,
            metadata={
                "shadow_phase": True,
                "created_by": self.authority,
                "domain_id": resolved_domain_id,
                "task_title": task_title,
            },
        )
        channel = create_execution_channel(
            order_id=order_id,
            order_run_id=order_run_id,
            session_id=session_id,
            channel_kind="single_agent",
            diagnostics={
                "created_by": self.authority,
                "source": source,
                "task_id": task_id,
                "shadow_phase": True,
            },
        )
        run = TaskOrderRun(
            run_id=order_run_id,
            order_id=order_id,
            session_id=session_id,
            primary_execution_channel_id=channel.channel_id,
            executor_assignment=executor_policy,
            status="created",
            created_at=now,
            updated_at=now,
            diagnostics={
                "created_by": self.authority,
                "source": source,
                "task_id": task_id,
                "shadow_phase": True,
            },
        )
        envelope = TaskExecutionEnvelope(
            envelope_id=f"taskenv:{uuid.uuid4().hex[:12]}",
            order_id=order_id,
            order_run_id=order_run_id,
            execution_channel_id=channel.channel_id,
            session_id=session_id,
            role_contract=order.role_contract,
            responsibility_boundary={
                "source": "specific_task_record",
                "task_id": task_id,
                "domain_id": resolved_domain_id,
                "description": str(task.get("description") or "").strip(),
            },
            input_contract=order.input_contract,
            output_contract=order.output_contract,
            artifact_policy=order.artifact_policy,
            acceptance_policy=order.acceptance_policy,
            executor_policy=order.executor_policy,
            permission_ceiling=dict(task_policy.get("safety_policy") or {}),
            context_package={
                "task_record": _safe_projection(task),
                "flow_contract_binding": _safe_projection(flow_binding),
            },
            source_refs={
                "specific_task_ref": task_id,
                "task_definition_ref": task_id,
                "flow_contract_binding_ref": str(flow_binding.get("binding_id") or "").strip(),
                "task_execution_policy_ref": str(execution.get("policy_id") or "").strip(),
            },
            created_at=now,
        )
        return TaskOrderCreation(
            conversation_turn=turn,
            intent_decision=decision,
            order=order,
            order_run=run,
            execution_channel=channel,
            envelope=envelope,
        )

    def create_from_conversation_turn(
        self,
        *,
        conversation_turn: ConversationTurn,
        intent_decision: TaskIntentDecision,
        message: str,
        task_selection: dict[str, Any] | None = None,
        task_order_intent: dict[str, Any] | None = None,
    ) -> TaskOrderCreation:
        selection = dict(task_selection or {})
        explicit_intent = dict(task_order_intent or {})
        now = time.time()
        if intent_decision.decision == "chat_turn":
            updated_turn = ConversationTurn(
                **{
                    **conversation_turn.to_dict(),
                    "interaction_kind": "chat_turn",
                    "task_intent_decision_id": intent_decision.decision_id,
                }
            )
            return TaskOrderCreation(conversation_turn=updated_turn, intent_decision=intent_decision)
        if intent_decision.decision == "task_order_draft":
            draft = TaskOrderDraft(
                draft_id=f"draft:{conversation_turn.turn_id}:{uuid.uuid4().hex[:8]}",
                turn_id=conversation_turn.turn_id,
                session_id=conversation_turn.session_id,
                decision_id=intent_decision.decision_id,
                objective=str(message or "").strip(),
                candidate_order_kind=_candidate_order_kind(selection, explicit_intent),
                missing_fields=tuple(intent_decision.missing_fields),
                candidate_inputs={
                    "message": str(message or ""),
                    "task_selection_projection": _safe_projection(selection),
                    "task_order_intent": _safe_projection(explicit_intent),
                },
                created_at=now,
                updated_at=now,
            )
            updated_turn = ConversationTurn(
                **{
                    **conversation_turn.to_dict(),
                    "interaction_kind": "task_order_draft",
                    "task_intent_decision_id": intent_decision.decision_id,
                }
            )
            return TaskOrderCreation(
                conversation_turn=updated_turn,
                intent_decision=intent_decision,
                draft=draft,
            )

        order_kind = _candidate_order_kind(selection, explicit_intent)
        selected_task_id = str(selection.get("selected_task_id") or explicit_intent.get("task_id") or "").strip()
        order_id = f"order:{order_kind}:{uuid.uuid4().hex[:12]}"
        order_run_id = f"orderrun:{uuid.uuid4().hex[:12]}"
        idempotency_key = _idempotency_key(
            conversation_turn=conversation_turn,
            order_kind=order_kind,
            task_id=selected_task_id,
            message=message,
        )
        order = TaskOrder(
            order_id=order_id,
            session_id=conversation_turn.session_id,
            order_kind=order_kind,  # type: ignore[arg-type]
            source="conversation_turn",
            source_ref=f"conversation.turn:{conversation_turn.turn_id}",
            objective=str(explicit_intent.get("objective") or message or "").strip() or "User accepted task order.",
            task_id=selected_task_id or order_id,
            task_definition_ref=selected_task_id,
            input_contract={
                "message": str(message or ""),
                "task_selection_projection": _safe_projection(selection),
                "task_order_intent": _safe_projection(explicit_intent),
            },
            output_contract=dict(explicit_intent.get("output_contract") or {}),
            role_contract=_role_contract(selection, explicit_intent, order_kind=order_kind),
            acceptance_policy=dict(explicit_intent.get("acceptance_policy") or {}),
            artifact_policy=dict(selection.get("artifact_policy") or explicit_intent.get("artifact_policy") or {}),
            executor_policy=_executor_policy(selection, explicit_intent),
            context_policy=dict(explicit_intent.get("context_policy") or {}),
            status="accepted",
            idempotency_key=idempotency_key,
            created_at=now,
            updated_at=now,
            metadata={
                "shadow_phase": True,
                "task_selection_is_projection": True,
            },
        )
        channel = create_execution_channel(
            order_id=order_id,
            order_run_id=order_run_id,
            session_id=conversation_turn.session_id,
            channel_kind="single_agent",
            diagnostics={"created_by": self.authority, "shadow_phase": True},
        )
        run = TaskOrderRun(
            run_id=order_run_id,
            order_id=order_id,
            session_id=conversation_turn.session_id,
            primary_execution_channel_id=channel.channel_id,
            executor_assignment=_executor_policy(selection, explicit_intent),
            status="created",
            created_at=now,
            updated_at=now,
            diagnostics={"created_by": self.authority, "shadow_phase": True},
        )
        envelope = TaskExecutionEnvelope(
            envelope_id=f"taskenv:{uuid.uuid4().hex[:12]}",
            order_id=order_id,
            order_run_id=order_run_id,
            execution_channel_id=channel.channel_id,
            session_id=conversation_turn.session_id,
            role_contract=order.role_contract,
            responsibility_boundary=dict(explicit_intent.get("responsibility_boundary") or {}),
            input_contract=order.input_contract,
            output_contract=order.output_contract,
            artifact_policy=order.artifact_policy,
            acceptance_policy=order.acceptance_policy,
            executor_policy=order.executor_policy,
            permission_ceiling=dict(explicit_intent.get("permission_ceiling") or {}),
            context_package={
                "conversation_turn_id": conversation_turn.turn_id,
                "task_selection_projection": _safe_projection(selection),
            },
            source_refs={
                "conversation_turn_ref": f"conversation.turn:{conversation_turn.turn_id}",
                "intent_decision_ref": intent_decision.decision_id,
                "task_definition_ref": selected_task_id,
            },
            created_at=now,
        )
        updated_decision = decision_with_created_order(intent_decision, order_id)
        updated_turn = ConversationTurn(
            **{
                **conversation_turn.to_dict(),
                "interaction_kind": "executable_task",
                "task_intent_decision_id": updated_decision.decision_id,
                "task_order_ref": order_id,
            }
        )
        return TaskOrderCreation(
            conversation_turn=updated_turn,
            intent_decision=updated_decision,
            order=order,
            order_run=run,
            execution_channel=channel,
            envelope=envelope,
        )


def _candidate_order_kind(selection: dict[str, Any], explicit_intent: dict[str, Any]) -> str:
    explicit = str(explicit_intent.get("order_kind") or "").strip()
    if explicit:
        return explicit
    if str(selection.get("selected_task_id") or "").strip():
        return "specific_task"
    if str(explicit_intent.get("graph_id") or "").strip():
        return "graph_run"
    return "ad_hoc_task"


def _role_contract(selection: dict[str, Any], explicit_intent: dict[str, Any], *, order_kind: str) -> dict[str, Any]:
    role_contract = dict(explicit_intent.get("role_contract") or {})
    if role_contract:
        role_contract.setdefault("source", "task_order_intent")
        return role_contract
    selected_task_id = str(selection.get("selected_task_id") or "").strip()
    if selected_task_id:
        return {
            "source": "specific_task_projection",
            "task_definition_ref": selected_task_id,
            "effective_role_note": "Use the selected task contract for this invocation only; do not rewrite the agent profile.",
        }
    return {
        "source": "ad_hoc_contract",
        "order_kind": order_kind,
        "effective_role_note": "Use the accepted task objective for this invocation only; do not rewrite the agent profile.",
    }


def _executor_policy(selection: dict[str, Any], explicit_intent: dict[str, Any]) -> dict[str, Any]:
    policy = dict(explicit_intent.get("executor_policy") or {})
    for key in ("agent_id", "agent_profile_id", "runtime_lane"):
        value = str(selection.get(key) or "").strip()
        if value and key not in policy:
            policy[key] = value
    policy.setdefault("executor_type", "agent")
    return policy


def _safe_projection(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        json.dumps(payload, ensure_ascii=False)
        return dict(payload)
    except TypeError:
        return {str(key): str(value) for key, value in dict(payload or {}).items()}


def _idempotency_key(*, conversation_turn: ConversationTurn, order_kind: str, task_id: str, message: str) -> str:
    digest = hashlib.sha256(str(message or "").encode("utf-8")).hexdigest()[:16]
    return ":".join(
        [
            "conversation_turn",
            conversation_turn.turn_id,
            order_kind,
            task_id or "ad_hoc",
            digest,
        ]
    )
