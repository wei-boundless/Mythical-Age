from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from task_system.assembly import TaskRuntimeAssemblyRequestBuilder
from task_system.environments import default_task_environment_registry
from task_system.primitives import TaskActivationRequest, TaskLifecycle, TaskRuntimeAssemblyRequest


@dataclass(frozen=True, slots=True)
class TaskLifecycleCreation:
    activation_request: TaskActivationRequest | None = None
    lifecycle: TaskLifecycle | None = None
    runtime_assembly_request: TaskRuntimeAssemblyRequest | None = None

    def projection(self) -> dict[str, Any]:
        return {
            "task_activation_request": (
                self.activation_request.to_dict() if self.activation_request is not None else None
            ),
            "task_lifecycle": self.lifecycle.to_dict() if self.lifecycle is not None else None,
            "task_runtime_assembly_request": (
                self.runtime_assembly_request.to_dict()
                if self.runtime_assembly_request is not None
                else None
            ),
            "authority": "task_system.task_lifecycle_creation_projection",
        }


@dataclass(frozen=True, slots=True)
class TaskLifecycleFactory:
    """Creates TaskLifecycle objects from accepted activation requests."""

    authority: str = "task_system.task_lifecycle_factory"

    def create_from_activation(
        self,
        activation: TaskActivationRequest,
        *,
        legacy_refs: dict[str, Any] | None = None,
    ) -> TaskLifecycleCreation:
        now = time.time()
        environment_id = _require_known_environment(
            str(activation.environment_id or activation.environment_hint or "").strip()
        )
        task_id = f"tasklife:{uuid.uuid4().hex[:12]}"
        lifecycle = TaskLifecycle(
            task_id=task_id,
            session_id=activation.session_id,
            environment_id=environment_id,
            source=activation.source,
            dispatch=activation.dispatch,
            objective=activation.objective,
            activation_id=activation.activation_id,
            parent_task_id=activation.parent_task_id,
            source_ref=activation.source_ref,
            dispatch_ref=activation.dispatch_ref,
            working_objects=activation.working_objects,
            input_refs=activation.input_refs,
            resource_scope=dict(activation.resource_needs),
            tool_scope=dict(activation.capability_needs.get("tools") or {}),
            state_scope={"state_owner": "task_system.task_lifecycle"},
            artifact_scope=dict(activation.expected_output.get("artifact_scope") or {}),
            memory_scope=dict(activation.resource_needs.get("memory") or {}),
            agent_assignment=dict(activation.capability_needs.get("agent_assignment") or {}),
            output_contract=dict(activation.expected_output),
            acceptance_policy=dict(activation.acceptance_hint),
            recovery_policy={"lifecycle_need": list(activation.lifecycle_need)},
            approval_policy=dict(activation.risk_or_side_effects),
            legacy_refs=dict(legacy_refs or {}),
            status="created",
            created_at=now,
            updated_at=now,
            metadata={
                "created_by": self.authority,
                "relation_to_parent": activation.relation_to_parent,
            },
        )
        accepted_activation = TaskActivationRequest(
            **{
                **activation.to_dict(),
                "status": "accepted",
                "metadata": {
                    **dict(activation.metadata or {}),
                    "created_task_lifecycle_id": task_id,
                },
            }
        )
        runtime_assembly_request = TaskRuntimeAssemblyRequestBuilder().build(lifecycle)
        lifecycle_with_runtime_ref = TaskLifecycle(
            **{
                **lifecycle.to_dict(),
                "runtime_assembly_ref": runtime_assembly_request.request_id,
            }
        )
        return TaskLifecycleCreation(
            activation_request=accepted_activation,
            lifecycle=lifecycle_with_runtime_ref,
            runtime_assembly_request=runtime_assembly_request,
        )

    def create_from_task_order_creation(self, creation: Any) -> TaskLifecycleCreation:
        if creation.order is None:
            return TaskLifecycleCreation()
        order = creation.order
        now = time.time()
        environment_id = _environment_id_from_order_creation(creation)
        activation = TaskActivationRequest(
            activation_id=f"activation:{uuid.uuid4().hex[:12]}",
            session_id=order.session_id,
            source="explicit_requirement",
            dispatch=_dispatch_from_order_kind(order.order_kind),
            objective=order.objective,
            environment_id=environment_id,
            source_ref=order.source_ref,
            dispatch_ref=order.order_id,
            working_objects=_working_objects_from_order_creation(creation),
            input_refs=_input_refs_from_order_creation(creation),
            resource_needs={
                "context_policy": dict(order.context_policy or {}),
                "input_contract": dict(order.input_contract or {}),
            },
            capability_needs={
                "executor_policy": dict(order.executor_policy or {}),
                "agent_assignment": dict(order.executor_policy or {}),
            },
            expected_output={
                **dict(order.output_contract or {}),
                "artifact_scope": dict(order.artifact_policy or {}),
            },
            acceptance_hint=dict(order.acceptance_policy or {}),
            lifecycle_need=tuple(creation.intent_decision.lifecycle_needs),
            risk_or_side_effects=dict(order.metadata.get("risk_or_side_effects") or {}),
            relation_to_parent="within_scope",
            status="requested",
            created_at=now,
            metadata={
                "created_by": self.authority,
                "legacy_order_id": order.order_id,
                "legacy_order_kind": order.order_kind,
            },
        )
        return self.create_from_activation(
            activation,
            legacy_refs={
                "task_order_id": order.order_id,
                "conversation_turn_id": creation.conversation_turn.turn_id,
                "intent_decision_id": creation.intent_decision.decision_id,
            },
        )


def _dispatch_from_order_kind(order_kind: str) -> str:
    if order_kind == "graph_node_task":
        return "graph_node_dispatch"
    if order_kind == "human_work":
        return "human_dispatch"
    return "order_dispatch"


def _environment_id_from_order_creation(creation: Any) -> str:
    order = creation.order
    if order is None:
        return ""
    candidates = [
        dict(order.input_contract or {}).get("environment_id"),
        dict(order.input_contract or {}).get("task_environment_id"),
        dict(order.metadata or {}).get("environment_id"),
        dict(order.metadata or {}).get("task_environment_id"),
    ]
    for item in candidates:
        value = str(item or "").strip()
        if value:
            return _require_known_environment(value)
    return _require_known_environment("env.general_workspace")


def _require_known_environment(environment_id: str) -> str:
    value = str(environment_id or "").strip()
    if not value:
        raise ValueError("TaskLifecycle requires environment_id")
    registry = default_task_environment_registry()
    if registry.get(value) is None:
        raise ValueError(f"unknown task environment: {value}")
    return value


def _working_objects_from_order_creation(creation: Any) -> tuple[dict[str, Any], ...]:
    order = creation.order
    if order is None:
        return ()
    objects: list[dict[str, Any]] = []
    task_id = str(order.task_id or "").strip()
    if task_id:
        objects.append({"kind": "task_definition", "ref": task_id})
    for key in ("target_object", "working_object", "file_ref", "artifact_ref"):
        value = dict(order.input_contract or {}).get(key)
        if value:
            objects.append({"kind": key, "ref": value})
    return tuple(objects)


def _input_refs_from_order_creation(creation: Any) -> tuple[dict[str, Any], ...]:
    order = creation.order
    if order is None:
        return ()
    refs: list[dict[str, Any]] = [
        {"kind": "source", "ref": order.source_ref},
    ]
    if creation.conversation_turn.turn_id:
        refs.append({"kind": "conversation_turn", "ref": creation.conversation_turn.turn_id})
    task_record = dict(order.input_contract or {}).get("task_record")
    if task_record:
        refs.append({"kind": "task_record", "ref": task_record})
    return tuple(refs)
