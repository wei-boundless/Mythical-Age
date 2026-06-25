from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any


LAUNCH_GATE_PASS_KIND = "task_launch_gate_pass"


@dataclass(frozen=True, slots=True)
class TaskLaunchGatePass:
    pass_id: str
    task_run_id: str
    gate_id: str
    gate_type: str
    passed: bool
    requested_by: str = "user"
    passed_at: float = 0.0
    source: str = "task_launch_gate_api"
    pending_gate_ref: str = ""
    authority: str = "harness.loop.task_launch_gate"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.authority != "harness.loop.task_launch_gate":
            raise ValueError("TaskLaunchGatePass authority must be harness.loop.task_launch_gate")
        if not self.pass_id:
            raise ValueError("TaskLaunchGatePass requires pass_id")
        if not self.task_run_id:
            raise ValueError("TaskLaunchGatePass requires task_run_id")
        if not self.gate_id:
            raise ValueError("TaskLaunchGatePass requires gate_id")
        if not self.gate_type:
            raise ValueError("TaskLaunchGatePass requires gate_type")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload


def pending_launch_gate_from_task_run(task_run: Any) -> dict[str, Any]:
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    pending = diagnostics.get("pending_launch_gate")
    return dict(pending or {}) if isinstance(pending, dict) else {}


def build_task_launch_gate_pass(
    *,
    task_run: Any,
    pending_launch_gate: dict[str, Any],
    requested_by: str,
    reason: str = "",
) -> TaskLaunchGatePass | None:
    pending = dict(pending_launch_gate or {})
    if str(pending.get("status") or "") != "pending":
        return None
    if pending.get("allow_direct_pass", True) is False:
        return None
    task_run_id = str(getattr(task_run, "task_run_id", "") or pending.get("task_run_id") or "").strip()
    gate_type = str(pending.get("gate_type") or "task_launch_supervision").strip()
    gate_id = launch_gate_id_for_pending(task_run=task_run, pending_launch_gate=pending)
    if not (task_run_id and gate_type and gate_id):
        return None
    now = time.time()
    identity = _stable_hash(
        {
            "task_run_id": task_run_id,
            "gate_id": gate_id,
            "gate_type": gate_type,
            "created_at": pending.get("created_at"),
        }
    )[:24]
    return TaskLaunchGatePass(
        pass_id=f"launch-gate-pass:{task_run_id}:{identity}",
        task_run_id=task_run_id,
        gate_id=gate_id,
        gate_type=gate_type,
        passed=True,
        requested_by=str(requested_by or "user"),
        passed_at=now,
        source="task_launch_gate_api",
        pending_gate_ref=gate_id,
        diagnostics={
            "reason": str(reason or ""),
            "pending_launch_gate": public_pending_launch_gate(pending),
        },
    )


def matching_launch_gate_pass_for_pending(task_run: Any) -> TaskLaunchGatePass | None:
    pending = pending_launch_gate_from_task_run(task_run)
    if str(pending.get("status") or "") not in {"pending", "passed"}:
        return None
    for gate_pass in task_launch_gate_passes(task_run):
        if not gate_pass_matches_pending(gate_pass, task_run=task_run, pending_launch_gate=pending):
            continue
        if gate_pass.passed:
            return gate_pass
    return None


def task_launch_gate_passes(task_run: Any) -> tuple[TaskLaunchGatePass, ...]:
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    state = diagnostics.get("launch_gate_state")
    if not isinstance(state, dict):
        return ()
    passes: list[TaskLaunchGatePass] = []
    for item in list(state.get("passes") or []):
        if not isinstance(item, dict):
            continue
        try:
            passes.append(_pass_from_payload(item))
        except Exception:
            continue
    return tuple(passes)


def append_task_launch_gate_pass(task_run: Any, gate_pass: TaskLaunchGatePass) -> dict[str, Any]:
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    state = dict(diagnostics.get("launch_gate_state") or {}) if isinstance(diagnostics.get("launch_gate_state"), dict) else {}
    passes = [
        dict(item)
        for item in list(state.get("passes") or [])
        if isinstance(item, dict) and str(item.get("pass_id") or "") != gate_pass.pass_id
    ]
    passes.append(gate_pass.to_dict())
    state = {
        **state,
        "status": "passed",
        "latest_pass_id": gate_pass.pass_id,
        "passes": passes,
        "authority": "harness.loop.task_launch_gate",
    }
    return {**diagnostics, "launch_gate_state": state}


def gate_pass_matches_pending(
    gate_pass: TaskLaunchGatePass,
    *,
    task_run: Any,
    pending_launch_gate: dict[str, Any],
) -> bool:
    pending = dict(pending_launch_gate or {})
    return (
        gate_pass.task_run_id == str(getattr(task_run, "task_run_id", "") or pending.get("task_run_id") or "")
        and gate_pass.gate_id == launch_gate_id_for_pending(task_run=task_run, pending_launch_gate=pending)
        and gate_pass.gate_type == str(pending.get("gate_type") or "task_launch_supervision")
    )


def launch_gate_id_for_pending(*, task_run: Any, pending_launch_gate: dict[str, Any]) -> str:
    pending = dict(pending_launch_gate or {})
    explicit = str(pending.get("gate_id") or "").strip()
    if explicit:
        return explicit
    task_run_id = str(getattr(task_run, "task_run_id", "") or pending.get("task_run_id") or "").strip()
    gate_type = str(pending.get("gate_type") or "task_launch_supervision").strip()
    if not task_run_id:
        return ""
    created_at = str(pending.get("created_at") or "").strip()
    suffix = _stable_hash({"task_run_id": task_run_id, "gate_type": gate_type, "created_at": created_at})[:12]
    return f"task-launch-gate:{task_run_id}:{suffix}"


def public_pending_launch_gate(pending_launch_gate: dict[str, Any]) -> dict[str, Any]:
    pending = dict(pending_launch_gate or {})
    return {
        key: pending.get(key)
        for key in (
            "gate_id",
            "gate_type",
            "mode",
            "task_run_id",
            "status",
            "created_at",
            "user_prompt",
            "allow_direct_pass",
            "passed_at",
            "pass_id",
            "passed_by",
            "reason",
        )
        if pending.get(key) is not None
    }


def _pass_from_payload(payload: dict[str, Any]) -> TaskLaunchGatePass:
    data = dict(payload or {})
    return TaskLaunchGatePass(
        pass_id=str(data.get("pass_id") or ""),
        task_run_id=str(data.get("task_run_id") or ""),
        gate_id=str(data.get("gate_id") or ""),
        gate_type=str(data.get("gate_type") or ""),
        passed=bool(data.get("passed") is True),
        requested_by=str(data.get("requested_by") or "user"),
        passed_at=float(data.get("passed_at") or 0.0),
        source=str(data.get("source") or "task_launch_gate_api"),
        pending_gate_ref=str(data.get("pending_gate_ref") or ""),
        authority=str(data.get("authority") or "harness.loop.task_launch_gate"),
        diagnostics=dict(data.get("diagnostics") or {}) if isinstance(data.get("diagnostics"), dict) else {},
    )


def _stable_hash(value: Any) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()
