from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json
import time
from typing import Any
import uuid

from .models import json_clone, stable_json, stable_json_hash


@dataclass(frozen=True, slots=True)
class ReplacementRecord:
    replacement_key: str
    source_kind: str
    source_id: str
    content_hash: str
    projection_policy_hash: str
    projector_version: str
    projection: dict[str, Any]
    task_run_id: str = ""
    rehydration_plan: dict[str, Any] = field(default_factory=dict)
    budget_decision: dict[str, Any] = field(default_factory=dict)
    store_status: str = "created"
    authority: str = "harness.runtime.dynamic_context.replacement_record"

    def to_dict(self) -> dict[str, Any]:
        return {
            "replacement_key": self.replacement_key,
            "source_kind": self.source_kind,
            "source_id": self.source_id,
            "content_hash": self.content_hash,
            "projection_policy_hash": self.projection_policy_hash,
            "projector_version": self.projector_version,
            "projection": dict(self.projection),
            "task_run_id": self.task_run_id,
            "rehydration_plan": dict(self.rehydration_plan),
            "budget_decision": dict(self.budget_decision),
            "store_status": self.store_status,
            "authority": self.authority,
        }


class ReplacementStore:
    def __init__(self, root_dir: Path, *, namespace: str = "dynamic_context") -> None:
        self.root_dir = Path(root_dir)
        self.base_dir = self.root_dir / namespace / "replacements"

    def key(
        self,
        *,
        source_kind: str,
        source_id: str,
        content_hash: str,
        projection_policy_hash: str,
        projector_version: str,
    ) -> str:
        seed = {
            "source_kind": str(source_kind or ""),
            "source_id": str(source_id or ""),
            "content_hash": str(content_hash or ""),
            "projection_policy_hash": str(projection_policy_hash or ""),
            "projector_version": str(projector_version or ""),
        }
        return "replacement:" + stable_json_hash(seed).removeprefix("sha256:")[:24]

    def get(self, replacement_key: str) -> dict[str, Any] | None:
        payload = self.get_record(replacement_key)
        if not payload:
            return None
        projection = payload.get("projection")
        return dict(projection) if isinstance(projection, dict) else None

    def get_record(self, replacement_key: str) -> dict[str, Any] | None:
        path = self._path_for_key(replacement_key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return dict(payload) if isinstance(payload, dict) else None

    def get_frozen(
        self,
        *,
        source_kind: str,
        source_id: str,
        task_run_id: str = "",
        content: Any,
        projection_policy: dict[str, Any],
        projector_version: str,
    ) -> tuple[dict[str, Any], ReplacementRecord] | None:
        identity = self._identity(
            source_kind=source_kind,
            source_id=source_id,
            task_run_id=task_run_id,
            content=content,
            projection_policy=projection_policy,
            projector_version=projector_version,
        )
        payload = self.get_record(identity["replacement_key"])
        if not payload:
            return None
        selected_projection = _strip_internal_replacement_refs(json_clone(dict(payload.get("projection") or {})))
        if not selected_projection or not _projection_external_refs_available(selected_projection):
            return None
        rehydration_plan = _rehydration_plan_from_projection(selected_projection)
        if rehydration_plan:
            rehydration_plan.pop("replacement_ref", None)
            rehydration_plan.setdefault("content_hash", identity["content_hash"])
            selected_projection["rehydration_plan"] = rehydration_plan
        record = ReplacementRecord(
            replacement_key=identity["replacement_key"],
            source_kind=str(source_kind or ""),
            source_id=identity["scoped_source_id"],
            content_hash=identity["content_hash"],
            projection_policy_hash=identity["projection_policy_hash"],
            projector_version=str(projector_version or ""),
            projection=selected_projection,
            task_run_id=identity["task_run_id"],
            rehydration_plan=rehydration_plan,
            budget_decision=_budget_decision_from_payload(
                payload.get("budget_decision"),
                content_hash=identity["content_hash"],
                projection_policy_hash=identity["projection_policy_hash"],
                store_status="reused",
                include_default=True,
            ),
            store_status="reused",
        )
        return selected_projection, record

    def get_or_put(
        self,
        *,
        source_kind: str,
        source_id: str,
        task_run_id: str = "",
        content: Any,
        projection_policy: dict[str, Any],
        projector_version: str,
        projection: dict[str, Any],
        budget_decision: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], ReplacementRecord]:
        identity = self._identity(
            source_kind=source_kind,
            source_id=source_id,
            task_run_id=task_run_id,
            content=content,
            projection_policy=projection_policy,
            projector_version=projector_version,
        )
        replacement_key = identity["replacement_key"]
        existing_payload = self.get_record(replacement_key)
        existing_projection = dict(existing_payload.get("projection") or {}) if existing_payload else {}
        if existing_projection and not _projection_external_refs_available(existing_projection):
            existing_payload = None
            existing_projection = {}
        selected_projection = _strip_internal_replacement_refs(json_clone(existing_projection or projection))
        rehydration_plan = _rehydration_plan_from_projection(selected_projection)
        if rehydration_plan:
            rehydration_plan.pop("replacement_ref", None)
            rehydration_plan.setdefault("content_hash", identity["content_hash"])
            selected_projection["rehydration_plan"] = rehydration_plan
        store_status = "reused" if existing_payload is not None else "created"
        record = ReplacementRecord(
            replacement_key=replacement_key,
            source_kind=str(source_kind or ""),
            source_id=identity["scoped_source_id"],
            content_hash=identity["content_hash"],
            projection_policy_hash=identity["projection_policy_hash"],
            projector_version=str(projector_version or ""),
            projection=selected_projection,
            task_run_id=identity["task_run_id"],
            rehydration_plan=rehydration_plan,
            budget_decision=_budget_decision_from_payload(
                existing_payload.get("budget_decision") if existing_payload else budget_decision,
                content_hash=identity["content_hash"],
                projection_policy_hash=identity["projection_policy_hash"],
                store_status=store_status,
                include_default=bool(budget_decision) or bool(existing_payload and existing_payload.get("budget_decision")),
            ),
            store_status=store_status,
        )
        if existing_payload is not None:
            return selected_projection, record
        self._write(record)
        return selected_projection, record

    def _identity(
        self,
        *,
        source_kind: str,
        source_id: str,
        task_run_id: str,
        content: Any,
        projection_policy: dict[str, Any],
        projector_version: str,
    ) -> dict[str, str]:
        normalized_task_run_id = str(task_run_id or "").strip()
        normalized_source_id = str(source_id or "")
        scoped_source_id = (
            f"{normalized_task_run_id}::{normalized_source_id}"
            if normalized_task_run_id and normalized_source_id
            else normalized_source_id
        )
        content_hash = stable_json_hash(content)
        projection_policy_hash = stable_json_hash(projection_policy)
        replacement_key = self.key(
            source_kind=source_kind,
            source_id=scoped_source_id,
            content_hash=content_hash,
            projection_policy_hash=projection_policy_hash,
            projector_version=projector_version,
        )
        return {
            "task_run_id": normalized_task_run_id,
            "scoped_source_id": scoped_source_id,
            "content_hash": content_hash,
            "projection_policy_hash": projection_policy_hash,
            "replacement_key": replacement_key,
        }

    def _write(self, record: ReplacementRecord) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        path = self._path_for_key(record.replacement_key)
        self._atomic_write_text(path, stable_json(record.to_dict()))
        if record.task_run_id:
            self._index_task_run_record(record)

    def _path_for_key(self, replacement_key: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in str(replacement_key or ""))
        if not safe:
            safe = "replacement_empty"
        return self.base_dir / f"{safe}.json"

    def _index_task_run_record(self, record: ReplacementRecord) -> None:
        path = self._task_run_index_path(record.task_run_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except Exception:
            payload = {}
        keys = [str(item) for item in list(payload.get("replacement_keys") or []) if str(item)]
        if record.replacement_key not in keys:
            keys.append(record.replacement_key)
        body = {
            "task_run_id": record.task_run_id,
            "replacement_keys": keys[-2000:],
            "authority": "harness.runtime.dynamic_context.replacement_store.task_run_index",
        }
        self._atomic_write_text(path, stable_json(body))

    def _task_run_index_path(self, task_run_id: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in str(task_run_id or ""))
        if not safe:
            safe = "task_run"
        return self.base_dir / "task_runs" / f"{safe}.json"

    def _atomic_write_text(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        last_error: OSError | None = None
        for attempt in range(5):
            tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
            try:
                tmp.write_text(content, encoding="utf-8")
                tmp.replace(path)
                return
            except OSError as exc:
                last_error = exc
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
                winerror = getattr(exc, "winerror", None)
                if not isinstance(exc, PermissionError) and winerror not in {5, 32}:
                    raise
                if attempt >= 4:
                    raise
                time.sleep(0.05 * (attempt + 1))
        if last_error is not None:
            raise last_error

    def prune_task_runs(self, task_run_ids: set[str] | list[str] | tuple[str, ...]) -> dict[str, Any]:
        targets = {str(item).strip() for item in task_run_ids if str(item).strip()}
        deleted_keys: list[str] = []
        deleted_paths: list[str] = []
        if not targets or not self.base_dir.exists():
            return {
                "authority": "harness.runtime.dynamic_context.replacement_store.prune_task_runs",
                "requested_task_run_ids": sorted(targets),
                "deleted_replacement_keys": [],
                "deleted_count": 0,
            }
        for task_run_id in sorted(targets):
            index_path = self._task_run_index_path(task_run_id)
            try:
                payload = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
            except Exception:
                payload = {}
            for replacement_key in [str(item) for item in list(payload.get("replacement_keys") or []) if str(item)]:
                path = self._path_for_key(replacement_key)
                if not path.exists():
                    continue
                try:
                    path.unlink()
                except OSError:
                    continue
                deleted_keys.append(replacement_key)
                deleted_paths.append(str(path))
            try:
                index_path.unlink(missing_ok=True)
            except OSError:
                continue
        return {
            "authority": "harness.runtime.dynamic_context.replacement_store.prune_task_runs",
            "requested_task_run_ids": sorted(targets),
            "deleted_replacement_keys": deleted_keys,
            "deleted_paths": deleted_paths,
            "deleted_count": len(deleted_keys),
            "scan_mode": "task_run_index",
        }


class MemoryReplacementStore(ReplacementStore):
    def __init__(self) -> None:
        self._records: dict[str, dict[str, Any]] = {}

    def get(self, replacement_key: str) -> dict[str, Any] | None:
        value = self._records.get(str(replacement_key or ""))
        projection = dict(value.get("projection") or {}) if isinstance(value, dict) else {}
        return json_clone(projection) if projection else None

    def get_record(self, replacement_key: str) -> dict[str, Any] | None:
        value = self._records.get(str(replacement_key or ""))
        return json_clone(dict(value)) if isinstance(value, dict) else None

    def _write(self, record: ReplacementRecord) -> None:
        self._records[record.replacement_key] = record.to_dict()

    def prune_task_runs(self, task_run_ids: set[str] | list[str] | tuple[str, ...]) -> dict[str, Any]:
        targets = {str(item).strip() for item in task_run_ids if str(item).strip()}
        deleted: list[str] = []
        for key, payload in list(self._records.items()):
            if not _record_matches_task_run(dict(payload or {}), targets):
                continue
            self._records.pop(key, None)
            deleted.append(key)
        return {
            "authority": "harness.runtime.dynamic_context.memory_replacement_store.prune_task_runs",
            "requested_task_run_ids": sorted(targets),
            "deleted_replacement_keys": deleted,
            "deleted_count": len(deleted),
        }


def _rehydration_plan_from_projection(projection: dict[str, Any]) -> dict[str, Any]:
    value = projection.get("rehydration_plan")
    return dict(value) if isinstance(value, dict) else {}


def _budget_decision_from_payload(
    value: Any,
    *,
    content_hash: str,
    projection_policy_hash: str,
    store_status: str,
    include_default: bool = False,
) -> dict[str, Any]:
    payload = dict(value or {}) if isinstance(value, dict) else {}
    if not payload and not include_default:
        return {}
    payload.setdefault("frozen", True)
    payload.setdefault("model_visible", False)
    payload.setdefault("content_hash", str(content_hash or ""))
    payload.setdefault("projection_policy_hash", str(projection_policy_hash or ""))
    payload["store_status"] = str(store_status or "")
    payload.setdefault("authority", "harness.runtime.dynamic_context.tool_result_budget_decision")
    return payload


def _projection_external_refs_available(projection: dict[str, Any]) -> bool:
    for ref in _projection_content_replacement_refs(projection):
        path = str(ref.get("path") or "").strip()
        if path and not Path(path).exists():
            return False
    return True


def _projection_content_replacement_refs(projection: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    refs.extend(dict(item) for item in list(projection.get("content_replacements") or []) if isinstance(item, dict))
    plan = dict(projection.get("rehydration_plan") or {})
    for capability in list(plan.get("capabilities") or []):
        if not isinstance(capability, dict):
            continue
        refs.extend(
            dict(item)
            for item in list(capability.get("content_replacements") or [])
            if isinstance(item, dict)
        )
    return refs


def _strip_internal_replacement_refs(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _strip_internal_replacement_refs(item)
            for key, item in value.items()
            if str(key) != "replacement_ref"
        }
    if isinstance(value, list):
        return [_strip_internal_replacement_refs(item) for item in value]
    if isinstance(value, tuple):
        return [_strip_internal_replacement_refs(item) for item in value]
    return value


def _record_matches_task_run(payload: dict[str, Any], targets: set[str]) -> bool:
    task_run_id = str(payload.get("task_run_id") or "").strip()
    if task_run_id in targets:
        return True
    source_id = str(payload.get("source_id") or "")
    if any(source_id == target or source_id.startswith(f"{target}::") for target in targets):
        return True
    projection = dict(payload.get("projection") or {})
    for key in ("task_run_id", "root_task_run_id", "current_task_run_id"):
        if str(projection.get(key) or "").strip() in targets:
            return True
    return False
