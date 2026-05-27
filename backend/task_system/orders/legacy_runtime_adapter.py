from __future__ import annotations

import time
import uuid
from dataclasses import replace

from .execution_channel import create_execution_channel
from .models import TaskExecutionEnvelope, TaskOrderRun
from .order_factory import TaskOrderCreation


def attach_legacy_runtime_read_model(creation: TaskOrderCreation) -> TaskOrderCreation:
    """Attach temporary read models for the current runtime adapter."""

    if creation.order is None:
        return creation
    if creation.order_run is not None and creation.execution_channel is not None and creation.envelope is not None:
        return creation
    order = creation.order
    lifecycle = creation.lifecycle_creation.lifecycle if creation.lifecycle_creation is not None else None
    now = time.time()
    order_run_id = f"orderrun:{uuid.uuid4().hex[:12]}"
    channel = create_execution_channel(
        order_id=order.order_id,
        order_run_id=order_run_id,
        session_id=order.session_id,
        channel_kind="single_agent",
        diagnostics={
            "created_by": "task_system.legacy_runtime_adapter",
            "legacy_adapter": True,
            "task_lifecycle_ref": lifecycle.task_id if lifecycle is not None else "",
        },
    )
    run = TaskOrderRun(
        run_id=order_run_id,
        order_id=order.order_id,
        session_id=order.session_id,
        primary_execution_channel_id=channel.channel_id,
        executor_assignment=dict(order.executor_policy or {}),
        status="created",
        created_at=now,
        updated_at=now,
        diagnostics={
            "created_by": "task_system.legacy_runtime_adapter",
            "legacy_adapter": True,
            "task_lifecycle_ref": lifecycle.task_id if lifecycle is not None else "",
            "runtime_assembly_ref": lifecycle.runtime_assembly_ref if lifecycle is not None else "",
        },
    )
    envelope = TaskExecutionEnvelope(
        envelope_id=f"taskenv:{uuid.uuid4().hex[:12]}",
        order_id=order.order_id,
        order_run_id=order_run_id,
        execution_channel_id=channel.channel_id,
        session_id=order.session_id,
        role_contract=dict(order.role_contract or {}),
        responsibility_boundary={
            "source": "legacy_runtime_adapter",
            "task_id": order.task_id,
            "environment_id": str(dict(order.input_contract or {}).get("environment_id") or ""),
            "task_lifecycle_ref": lifecycle.task_id if lifecycle is not None else "",
            "runtime_assembly_ref": lifecycle.runtime_assembly_ref if lifecycle is not None else "",
        },
        input_contract=dict(order.input_contract or {}),
        output_contract=dict(order.output_contract or {}),
        artifact_policy=dict(order.artifact_policy or {}),
        acceptance_policy=dict(order.acceptance_policy or {}),
        executor_policy=dict(order.executor_policy or {}),
        permission_ceiling={},
        context_package={
            "legacy_adapter": True,
            "environment_id": str(dict(order.input_contract or {}).get("environment_id") or ""),
            "task_lifecycle_ref": lifecycle.task_id if lifecycle is not None else "",
            "runtime_assembly_ref": lifecycle.runtime_assembly_ref if lifecycle is not None else "",
        },
        source_refs={
            "task_order_ref": order.order_id,
            "task_definition_ref": order.task_definition_ref,
            "source_ref": order.source_ref,
        },
        created_at=now,
    )
    return replace(creation, order_run=run, execution_channel=channel, envelope=envelope)
