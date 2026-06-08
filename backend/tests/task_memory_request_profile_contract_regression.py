from __future__ import annotations

import json
from pathlib import Path

from task_system.registry.flow_models import TaskMemoryRequestProfile


VALID_RUNTIME_MEMORY_LAYERS = {"conversation", "state", "working", "long_term"}
REMOVED_RUNTIME_MEMORY_LAYERS = {"task_durable", "task_durable_memory", "artifact_refs"}


def test_task_memory_request_profile_normalizes_only_runtime_memory_layers() -> None:
    profile = TaskMemoryRequestProfile(
        profile_id="taskmem:task.memory.valid",
        task_id="task.memory.valid",
        requested_memory_layers=("state", "working_memory", "durable", "state"),
    )

    assert profile.requested_memory_layers == ("state", "working", "long_term")


def test_task_memory_request_profile_rejects_removed_or_non_memory_layers() -> None:
    for layer in sorted(REMOVED_RUNTIME_MEMORY_LAYERS):
        error = ""
        try:
            TaskMemoryRequestProfile(
                profile_id=f"taskmem:task.memory.invalid.{layer}",
                task_id="task.memory.invalid",
                requested_memory_layers=("state", layer),
            )
        except ValueError as exc:
            error = str(exc)

        assert "memory layer" in error


def test_stored_task_memory_request_profiles_do_not_request_removed_layers() -> None:
    project_root = Path(__file__).resolve().parents[2]
    path = project_root / "storage" / "tasks" / "task_memory_request_profiles.json"
    if not path.exists():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    invalid_profiles = []

    for profile in list(payload.get("memory_request_profiles") or []):
        layers = {str(item or "").strip() for item in list(profile.get("requested_memory_layers") or [])}
        invalid_layers = sorted(layer for layer in layers if layer in REMOVED_RUNTIME_MEMORY_LAYERS or layer not in VALID_RUNTIME_MEMORY_LAYERS)
        if invalid_layers:
            invalid_profiles.append(
                {
                    "task_id": str(profile.get("task_id") or ""),
                    "invalid_layers": invalid_layers,
                }
            )

    assert invalid_profiles == []
