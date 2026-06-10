from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from artifact_system.artifact_authority import model_visible_artifact_refs, normalize_artifact_ref


@dataclass(frozen=True, slots=True)
class BoundTaskContext:
    context_id: str
    context_hash: str
    source_ref: str
    plan_refs: tuple[str, ...] = ()
    task_files: tuple[dict[str, Any], ...] = ()
    edit_targets: tuple[dict[str, Any], ...] = ()
    artifact_refs: tuple[dict[str, Any], ...] = ()
    context_refs: tuple[str, ...] = ()
    rehydration_refs: tuple[dict[str, Any], ...] = ()
    restore_policy: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.runtime.bound_task_context"

    @property
    def empty(self) -> bool:
        return not self._stable_payload_body()

    def to_model_visible_payload(self) -> dict[str, Any]:
        body = self._stable_payload_body()
        if not body:
            return {}
        return _drop_empty_payload(
            {
                "bound_task_context": {
                    "context_hash": self.context_hash,
                    **body,
                    "authority": self.authority,
                }
            }
        )

    def to_manifest_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["plan_refs"] = list(self.plan_refs)
        payload["task_files"] = [dict(item) for item in self.task_files]
        payload["edit_targets"] = [dict(item) for item in self.edit_targets]
        payload["artifact_refs"] = [dict(item) for item in self.artifact_refs]
        payload["context_refs"] = list(self.context_refs)
        payload["rehydration_refs"] = [dict(item) for item in self.rehydration_refs]
        payload["restore_policy"] = dict(self.restore_policy)
        payload["diagnostics"] = dict(self.diagnostics)
        return payload

    def _stable_payload_body(self) -> dict[str, Any]:
        return _drop_empty_payload(
            {
                "plan_refs": list(self.plan_refs),
                "context_refs": list(self.context_refs),
                "restore_policy": dict(self.restore_policy),
            }
        )


def build_bound_task_context(
    *,
    contract: dict[str, Any] | None = None,
    planning_protocol: dict[str, Any] | None = None,
    dynamic_context: Any | None = None,
    task_state_projection: dict[str, Any] | None = None,
    task_run_id: str = "",
) -> BoundTaskContext:
    contract_payload = dict(contract or {})
    planning_payload = dict(planning_protocol or {})
    state_payload = _task_state_payload(task_state_projection)
    replay_entries = tuple(dict(item) for item in tuple(getattr(dynamic_context, "task_state_replay_entries", ()) or ()) if isinstance(item, dict))
    context_refs = _string_tuple(getattr(dynamic_context, "context_refs", ()))
    artifact_refs = _artifact_refs(
        state_payload.get("artifact_evidence"),
        tuple(getattr(dynamic_context, "artifact_refs", ()) or ()),
    )
    task_files = _task_files(state_payload.get("file_state"))
    rehydration_refs = _rehydration_refs(task_files=task_files, replay_entries=replay_entries)
    edit_targets = _edit_targets(task_files)
    plan_refs = _plan_refs(contract_payload, planning_payload)
    stable_seed = _drop_empty_payload(
        {
            "plan_refs": list(plan_refs),
            "context_refs": list(context_refs),
            "restore_policy": _restore_policy(enabled=bool(plan_refs or context_refs)),
        }
    )
    runtime_state_seed = _drop_empty_payload(
        {
            "task_files": task_files,
            "edit_targets": edit_targets,
            "artifact_refs": artifact_refs,
            "rehydration_refs": rehydration_refs,
        }
    )
    context_hash = _stable_hash(stable_seed)
    runtime_state_hash = _stable_hash(runtime_state_seed) if runtime_state_seed else ""
    context_id = "boundctx:" + context_hash.removeprefix("sha256:")[:16]
    return BoundTaskContext(
        context_id=context_id,
        context_hash=context_hash,
        source_ref=context_id,
        plan_refs=plan_refs,
        task_files=tuple(task_files),
        edit_targets=tuple(edit_targets),
        artifact_refs=tuple(artifact_refs),
        context_refs=context_refs,
        rehydration_refs=tuple(rehydration_refs),
        restore_policy=_restore_policy(enabled=bool(plan_refs or context_refs)),
        diagnostics={
            "task_run_id": str(task_run_id or ""),
            "plan_ref_count": len(plan_refs),
            "task_file_count": len(task_files),
            "edit_target_count": len(edit_targets),
            "artifact_ref_count": len(artifact_refs),
            "context_ref_count": len(context_refs),
            "rehydration_ref_count": len(rehydration_refs),
            "runtime_state_hash": runtime_state_hash,
            "source_authority": "harness.runtime.bound_task_context.builder",
        },
    )


def _plan_refs(contract: dict[str, Any], planning_protocol: dict[str, Any]) -> tuple[str, ...]:
    implementation_lock = dict(contract.get("implementation_lock") or {})
    candidates = [
        contract.get("external_plan_ref"),
        contract.get("plan_ref"),
        contract.get("approved_plan_ref"),
        implementation_lock.get("plan_ref"),
        planning_protocol.get("plan_ref"),
    ]
    return _dedupe_strings(str(item).strip() for item in candidates if str(item or "").strip())


def _task_state_payload(value: Any) -> dict[str, Any]:
    payload = dict(value or {}) if isinstance(value, dict) else {}
    nested = payload.get("task_state")
    if isinstance(nested, dict):
        return dict(nested)
    return payload


def _task_files(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in list(value or []):
        if not isinstance(item, dict):
            continue
        path = _clean_path(item.get("path"))
        if not path:
            continue
        read_windows = _read_windows(item.get("read_ranges"))
        projected = _drop_empty_payload(
            {
                "path": path,
                "status": str(item.get("status") or "").strip(),
                "read_windows": read_windows[-8:],
                "coverage": dict(item.get("coverage") or {}),
                "total_lines": item.get("total_lines") if isinstance(item.get("total_lines"), int) else None,
                "content_sha256": str(item.get("content_sha256") or "").strip(),
                "last_observation_ref": str(item.get("last_observation_ref") or "").strip(),
                "has_more": item.get("has_more") if isinstance(item.get("has_more"), bool) else None,
                "write_event_count": item.get("write_event_count") if isinstance(item.get("write_event_count"), int) else None,
                "next_suggested_read": dict(item.get("next_suggested_read") or {}),
                "evidence_refs": _string_list(item.get("evidence_refs"))[-5:],
            }
        )
        if projected:
            result.append(projected)
    return result[-20:]


def _read_windows(value: Any) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    for item in list(value or []):
        if not isinstance(item, dict):
            continue
        start_line = _int_or_none(item.get("start_line"))
        end_line = _int_or_none(item.get("end_line"))
        if start_line is None or end_line is None:
            continue
        windows.append(
            _drop_empty_payload(
                {
                    "start_line": start_line,
                    "end_line": end_line,
                    "observation_ref": str(item.get("observation_ref") or "").strip(),
                }
            )
        )
    return windows


def _edit_targets(task_files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in task_files:
        write_count = _int_or_none(item.get("write_event_count")) or 0
        status = str(item.get("status") or "").strip().lower()
        if write_count <= 0 and status not in {"modified", "written", "stale"}:
            continue
        result.append(
            _drop_empty_payload(
                {
                    "path": str(item.get("path") or ""),
                    "status": str(item.get("status") or ""),
                    "write_event_count": write_count or None,
                    "content_sha256": str(item.get("content_sha256") or ""),
                    "last_observation_ref": str(item.get("last_observation_ref") or ""),
                }
            )
        )
    return result[-12:]


def _artifact_refs(*values: Any) -> list[dict[str, Any]]:
    refs: list[Any] = []
    for value in values:
        if isinstance(value, (list, tuple)):
            refs.extend(value)
        elif value:
            refs.append(value)
    return model_visible_artifact_refs(
        [normalize_artifact_ref(item) for item in refs],
        limit=12,
        summary_limit=500,
    )


def _rehydration_refs(*, task_files: list[dict[str, Any]], replay_entries: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for item in task_files:
        next_read = dict(item.get("next_suggested_read") or {})
        if next_read:
            refs.append(
                _drop_empty_payload(
                    {
                        "source": "file_state",
                        "path": str(item.get("path") or ""),
                        "next_read": next_read,
                        "reason": "bound file window is partial or stale",
                    }
                )
            )
    for entry in replay_entries:
        plan = dict(entry.get("rehydration_plan") or {})
        content_range = dict(entry.get("content_range") or {})
        replacement_ref = str(entry.get("replacement_ref") or "").strip()
        path = _clean_path(entry.get("path") or content_range.get("path"))
        if not (plan or content_range or replacement_ref):
            continue
        refs.append(
            _drop_empty_payload(
                {
                    "source": "task_state_replay",
                    "path": path,
                    "replacement_ref": replacement_ref,
                    "content_range": _content_range(content_range),
                    "instruction": str(plan.get("instruction") or "").strip(),
                }
            )
        )
    return _dedupe_dicts(refs)[-12:]


def _content_range(value: dict[str, Any]) -> dict[str, Any]:
    return _drop_empty_payload(
        {
            "path": _clean_path(value.get("path")),
            "start_line": _int_or_none(value.get("start_line")),
            "end_line": _int_or_none(value.get("end_line")),
            "has_more": value.get("has_more") if isinstance(value.get("has_more"), bool) else None,
            "next_start_line": _int_or_none(value.get("next_start_line")),
            "content_sha256": str(value.get("content_sha256") or "").strip(),
        }
    )


def _restore_policy(*, enabled: bool) -> dict[str, Any]:
    if not enabled:
        return {}
    return {
        "mode": "task_bound_context_restore",
        "compact_resume": "Restore bound plan refs and context refs before relying on older transcript summaries.",
        "volatile_state_boundary": "Current file windows, edit receipts, artifact evidence, and rehydration refs are carried by volatile task state and replay entries, not by this stable binding segment.",
        "file_precision": "Before line-level edits or exact claims, re-read the current target range from the live file state.",
    }


def _string_tuple(value: Any) -> tuple[str, ...]:
    return _dedupe_strings(str(item).strip() for item in list(value or []) if str(item).strip())


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return [str(item).strip() for item in list(value or []) if str(item).strip()]


def _dedupe_strings(values: Any) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        item = str(raw or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return tuple(result)


def _dedupe_dicts(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in values:
        payload = _drop_empty_payload(dict(item or {}))
        if not payload:
            continue
        key = _stable_hash(payload)
        if key in seen:
            continue
        seen.add(key)
        result.append(payload)
    return result


def _clean_path(value: Any) -> str:
    return str(value or "").replace("\\", "/").strip().strip("/")


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _drop_empty_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: projected
            for key, item in value.items()
            for projected in [_drop_empty_payload(item)]
            if projected not in (None, "", [], {})
        }
    if isinstance(value, list):
        return [
            projected
            for item in value
            for projected in [_drop_empty_payload(item)]
            if projected not in (None, "", [], {})
        ]
    if isinstance(value, tuple):
        return tuple(
            projected
            for item in value
            for projected in [_drop_empty_payload(item)]
            if projected not in (None, "", [], {})
        )
    return value


def _stable_hash(value: Any) -> str:
    payload = json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)
