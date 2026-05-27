from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from task_system.primitives import TaskLifecycle, TaskRuntimeAssemblyRequest


@dataclass(frozen=True, slots=True)
class TaskRuntimeAssemblyRequestBuilder:
    """Builds task-system-side runtime assembly requests from TaskLifecycle."""

    authority: str = "task_system.task_runtime_assembly_request_builder"

    def build(
        self,
        lifecycle: TaskLifecycle,
        *,
        dispatch_context_ref: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> TaskRuntimeAssemblyRequest:
        if lifecycle.authority != "task_system.task_lifecycle":
            raise ValueError("TaskRuntimeAssemblyRequest requires TaskLifecycle authority")
        request_id = f"taskruntimeasm:{uuid.uuid4().hex[:12]}"
        return TaskRuntimeAssemblyRequest(
            request_id=request_id,
            task_lifecycle_ref=lifecycle.task_id,
            environment_ref=lifecycle.environment_id,
            activation_ref=lifecycle.activation_id,
            agent_assignment_ref=_scope_ref(lifecycle.task_id, "agent_assignment", lifecycle.agent_assignment),
            tool_scope_ref=_scope_ref(lifecycle.task_id, "tool_scope", lifecycle.tool_scope),
            resource_scope_ref=_scope_ref(lifecycle.task_id, "resource_scope", lifecycle.resource_scope),
            memory_scope_ref=_scope_ref(lifecycle.task_id, "memory_scope", lifecycle.memory_scope),
            artifact_scope_ref=_scope_ref(lifecycle.task_id, "artifact_scope", lifecycle.artifact_scope),
            output_contract_ref=_scope_ref(lifecycle.task_id, "output_contract", lifecycle.output_contract),
            acceptance_policy_ref=_scope_ref(lifecycle.task_id, "acceptance_policy", lifecycle.acceptance_policy),
            recovery_policy_ref=_scope_ref(lifecycle.task_id, "recovery_policy", lifecycle.recovery_policy),
            approval_policy_ref=_scope_ref(lifecycle.task_id, "approval_policy", lifecycle.approval_policy),
            dispatch_context_ref=dispatch_context_ref or lifecycle.dispatch_ref,
            created_at=time.time(),
            metadata={
                "created_by": self.authority,
                "source": lifecycle.source,
                "dispatch": lifecycle.dispatch,
                "parent_task_id": lifecycle.parent_task_id,
                "status_at_build": lifecycle.status,
                **dict(metadata or {}),
            },
        )


def _scope_ref(task_id: str, scope_name: str, payload: dict[str, Any]) -> str:
    if not dict(payload or {}):
        return ""
    safe_task_id = str(task_id or "").replace(":", "_")
    return f"taskscope:{safe_task_id}:{scope_name}"
