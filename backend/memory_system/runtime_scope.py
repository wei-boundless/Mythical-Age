from __future__ import annotations

from pathlib import Path

from memory_system.runtime_services import MemoryRuntimeServices


def project_id_for_task_run(storage_root: Path, task_run_id: str) -> str:
    normalized_task_run_id = str(task_run_id or "").strip()
    if not normalized_task_run_id:
        return ""
    runtime_root = Path(storage_root)
    if runtime_root.name == "storage":
        runtime_root = runtime_root / "runtime_state"
    if runtime_root.name != "runtime_state":
        runtime_root = MemoryRuntimeServices.from_runtime_root(runtime_root).storage_root / "runtime_state"
    try:
        from runtime.memory.state_index import RuntimeStateIndex

        task_run = RuntimeStateIndex(runtime_root).get_task_run(normalized_task_run_id)
    except Exception:
        task_run = None
    if task_run is None:
        return ""
    return str(dict(getattr(task_run, "diagnostics", {}) or {}).get("project_id") or "").strip()


__all__ = ["project_id_for_task_run"]
