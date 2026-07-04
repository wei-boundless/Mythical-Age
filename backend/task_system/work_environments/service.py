from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .models import TaskEvent, TaskInstance, TaskWorkEnvironment, stable_task_environment_id
from .repository import TaskEnvironmentRepository


class TaskWorkEnvironmentService:
    authority = "task_system.task_work_environment_service"

    def __init__(self, base_dir: str | Path) -> None:
        self.repository = TaskEnvironmentRepository(base_dir)

    def create_task_environment(
        self,
        *,
        task_kind: str,
        title: str,
        goal: str,
        environment_kind: str,
        caller_kind: str,
        idempotency_key: str,
        owner_agent_id: str = "",
        owner_user_id: str = "",
        project_id: str = "",
        workspace_view: str = "",
        acceptance_contract_ref: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> TaskWorkEnvironment:
        key = str(idempotency_key or "").strip()
        if not key:
            raise ValueError("create_task_environment requires idempotency_key")
        now = time.time()
        task_instance_id = stable_task_environment_id("taskinst", task_kind, title, goal, key)
        task_environment_id = stable_task_environment_id("taskenv", task_instance_id, environment_kind, caller_kind, key)
        existing = self.repository.get_task_environment(task_environment_id)
        if existing is not None:
            return existing
        instance = TaskInstance(
            task_instance_id=task_instance_id,
            task_kind=task_kind,
            title=title,
            goal=goal,
            status="active",
            owner_agent_id=owner_agent_id,
            owner_user_id=owner_user_id,
            project_id=project_id,
            workspace_view=workspace_view,
            acceptance_contract_ref=acceptance_contract_ref,
            root_task_environment_id=task_environment_id,
            created_at=now,
            updated_at=now,
            metadata=dict(metadata or {}),
        )
        environment = TaskWorkEnvironment(
            task_environment_id=task_environment_id,
            task_instance_id=task_instance_id,
            environment_kind=environment_kind,
            caller_kind=caller_kind,
            status="ready",
            created_at=now,
            updated_at=now,
            metadata=dict(metadata or {}),
        )
        self.repository.upsert_task_instance(instance)
        self.repository.upsert_task_environment(environment)
        created_event = TaskEvent(
            event_id=stable_task_environment_id("taskevent", task_environment_id, "created", key),
            task_environment_id=task_environment_id,
            task_instance_id=task_instance_id,
            event_seq=0,
            event_type="task_environment_created",
            actor_kind="system",
            idempotency_key=f"create:{key}",
            payload={
                "task_kind": task_kind,
                "environment_kind": environment_kind,
                "caller_kind": caller_kind,
            },
            created_at=now,
        )
        self.repository.append_event(created_event, expected_revision=0, snapshot_patch={"status": "ready"})
        return self.repository.get_task_environment(task_environment_id) or environment
