from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from .models import TaskRun


class RuntimeStateIndex:
    """Fast lookup index for latest TaskRun state."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)
        self.index_path = self.root_dir / "state_index.json"
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def upsert_task_run(self, task_run: TaskRun) -> None:
        payload = self._read()
        task_runs = dict(payload.get("task_runs") or {})
        task_runs[task_run.task_run_id] = task_run.to_dict()
        payload["task_runs"] = task_runs
        sessions = dict(payload.get("sessions") or {})
        session_runs = list(sessions.get(task_run.session_id) or [])
        if task_run.task_run_id not in session_runs:
            session_runs.append(task_run.task_run_id)
        sessions[task_run.session_id] = session_runs
        payload["sessions"] = sessions
        payload["updated_at"] = time.time()
        self._atomic_write(payload)

    def get_task_run(self, task_run_id: str) -> TaskRun | None:
        task_run = dict((self._read().get("task_runs") or {}).get(task_run_id) or {})
        if not task_run:
            return None
        return _task_run_from_payload(task_run)

    def list_session_task_runs(self, session_id: str) -> list[TaskRun]:
        payload = self._read()
        task_runs = dict(payload.get("task_runs") or {})
        ids = list((payload.get("sessions") or {}).get(session_id) or [])
        return [_task_run_from_payload(task_runs[item]) for item in ids if item in task_runs]

    def _read(self) -> dict[str, Any]:
        if not self.index_path.exists():
            return {"task_runs": {}, "sessions": {}, "updated_at": 0.0}
        return json.loads(self.index_path.read_text(encoding="utf-8"))

    def _atomic_write(self, payload: dict[str, Any]) -> None:
        tmp = self.index_path.with_suffix(f"{self.index_path.suffix}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.index_path)


def _task_run_from_payload(payload: dict[str, Any]) -> TaskRun:
    return TaskRun(
        task_run_id=str(payload.get("task_run_id") or ""),
        session_id=str(payload.get("session_id") or ""),
        task_id=str(payload.get("task_id") or ""),
        task_contract_ref=str(payload.get("task_contract_ref") or ""),
        owner_agent_seat_id=str(payload.get("owner_agent_seat_id") or "main"),
        agent_id=str(payload.get("agent_id") or "agent:main"),
        agent_profile_id=str(payload.get("agent_profile_id") or "main_interactive_agent"),
        runtime_lane=str(payload.get("runtime_lane") or "full_interactive"),
        status=payload.get("status", "created"),
        created_at=float(payload.get("created_at") or 0.0),
        updated_at=float(payload.get("updated_at") or 0.0),
        latest_event_offset=int(payload.get("latest_event_offset", -1)),
        latest_checkpoint_ref=str(payload.get("latest_checkpoint_ref") or ""),
        terminal_reason=payload.get("terminal_reason", ""),
        diagnostics=dict(payload.get("diagnostics") or {}),
    )
