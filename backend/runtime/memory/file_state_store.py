from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from core.json_file_store import JsonFilePayloadCorrupt, JsonFileStoreError, json_file_lock, read_json_dict, write_json_dict
from runtime_objects.read_observation_artifacts import ReadObservationArtifactStore

from .file_evidence_scope import (
    normalize_file_evidence_scope,
    session_file_evidence_scope,
    task_run_file_evidence_scope,
)
from .file_state_authority import FileStateAuthority, file_state_events_from_observation


FILE_STATE_STORE_AUTHORITY = "runtime.memory.file_state_store"
FILE_STATE_EVENT_HISTORY_LIMIT = 500


class FileStateAuthorityStore:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)
        self.file_state_dir = self.root_dir / "file_state"
        self.file_state_dir.mkdir(parents=True, exist_ok=True)

    def load_scope(self, scope: dict[str, Any] | None) -> FileStateAuthority:
        evidence_scope = normalize_file_evidence_scope(scope)
        if not evidence_scope:
            return FileStateAuthority()
        with json_file_lock(self._payload_path(evidence_scope)):
            payload = self._load_payload(evidence_scope)
        return self._authority_from_payload(evidence_scope, payload)

    def apply_observation_scope(self, scope: dict[str, Any] | None, observation: dict[str, Any]) -> FileStateAuthority:
        extracted = file_state_events_from_observation(dict(observation or {}))
        return self.apply_events_scope(
            scope,
            extracted.events,
            observation_ref=extracted.observation_ref,
            tool_call_id=extracted.tool_call_id,
        )

    def apply_events_scope(
        self,
        scope: dict[str, Any] | None,
        events: list[dict[str, Any]] | tuple[dict[str, Any], ...],
        *,
        observation_ref: str = "",
        tool_call_id: str = "",
    ) -> FileStateAuthority:
        evidence_scope = normalize_file_evidence_scope(scope)
        if not evidence_scope:
            return FileStateAuthority()
        normalized_events = tuple(dict(item) for item in list(events or []) if isinstance(item, dict))
        with json_file_lock(self._payload_path(evidence_scope)):
            payload = self._load_payload(evidence_scope)
            authority = self._authority_from_payload(evidence_scope, payload)
            if not normalized_events:
                return authority
            now = time.time()
            committed_events = []
            updated = authority
            for event in normalized_events:
                event_payload = _event_payload(
                    event,
                    observation_ref=observation_ref,
                    tool_call_id=tool_call_id,
                )
                _bind_read_observation_alias(
                    self.root_dir,
                    event_payload,
                    observation_ref=str(event_payload.get("observation_ref") or ""),
                )
                updated = updated.apply_event(
                    event_payload,
                    observation_ref=str(event_payload.get("observation_ref") or ""),
                    tool_call_id=str(event_payload.get("tool_call_id") or ""),
                )
                committed_events.append(
                    {
                        "committed_at": now,
                        "observation_ref": str(event_payload.get("observation_ref") or ""),
                        "tool_call_id": str(event_payload.get("tool_call_id") or ""),
                        "event": event_payload,
                    }
                )
            self._write_payload(
                evidence_scope,
                {
                    **_scope_payload(evidence_scope),
                    "updated_at": now,
                    "state": updated.to_dict(),
                    "events": _bounded_event_history(
                        [dict(item) for item in list(payload.get("events") or []) if isinstance(item, dict)]
                        + committed_events
                    ),
                    "latest_observation_ref": str(committed_events[-1].get("observation_ref") or "") if committed_events else "",
                    "latest_tool_call_id": str(committed_events[-1].get("tool_call_id") or "") if committed_events else "",
                    "authority": FILE_STATE_STORE_AUTHORITY,
                },
            )
        return updated

    def snapshot_scope(self, scope: dict[str, Any] | None, *, limit: int = 20) -> list[dict[str, Any]]:
        return self.load_scope(scope).projection(limit=limit)

    def materialize_snapshot_scope(
        self,
        target_scope: dict[str, Any] | None,
        snapshot: list[dict[str, Any]] | tuple[dict[str, Any], ...],
        *,
        source_scope: dict[str, Any] | None = None,
        observation_ref: str = "",
        tool_call_id: str = "",
    ) -> dict[str, Any]:
        evidence_scope = normalize_file_evidence_scope(target_scope)
        if not evidence_scope:
            return {
                "status": "skipped",
                "reason": "missing_target_file_evidence_scope",
                "authority": f"{FILE_STATE_STORE_AUTHORITY}.snapshot_materialization",
            }
        events = _file_state_snapshot_events(
            snapshot,
            source_scope=normalize_file_evidence_scope(source_scope),
        )
        if not events:
            return {
                "status": "empty",
                "target_file_evidence_scope": evidence_scope,
                "source_file_evidence_scope": normalize_file_evidence_scope(source_scope),
                "applied_snapshot_event_count": 0,
                "authority": f"{FILE_STATE_STORE_AUTHORITY}.snapshot_materialization",
            }
        self.apply_events_scope(
            evidence_scope,
            events,
            observation_ref=str(observation_ref or "file_state_snapshot_materialization"),
            tool_call_id=str(tool_call_id or "file_state_snapshot_materialization"),
        )
        return {
            "status": "recorded",
            "target_file_evidence_scope": evidence_scope,
            "source_file_evidence_scope": normalize_file_evidence_scope(source_scope),
            "snapshot_file_count": len([item for item in list(snapshot or []) if isinstance(item, dict)]),
            "applied_snapshot_event_count": len(events),
            "authority": f"{FILE_STATE_STORE_AUTHORITY}.snapshot_materialization",
        }

    def prune_task_runs(self, task_run_ids: set[str] | list[str] | tuple[str, ...]) -> dict[str, Any]:
        targets = {str(item).strip() for item in task_run_ids if str(item).strip()}
        deleted: list[str] = []
        for task_run_id in sorted(targets):
            path = self._payload_path(task_run_file_evidence_scope(task_run_id))
            if not path.exists():
                continue
            try:
                path.unlink()
            except OSError:
                continue
            deleted.append(task_run_id)
        return {
            "authority": f"{FILE_STATE_STORE_AUTHORITY}.prune_task_runs",
            "requested_task_run_ids": sorted(targets),
            "deleted_task_run_ids": deleted,
            "deleted_count": len(deleted),
        }

    def _payload_path(self, scope: dict[str, Any]) -> Path:
        return self.file_state_dir / f"{_scope_storage_key(scope)}.json"

    def _load_payload(self, scope: dict[str, Any]) -> dict[str, Any]:
        path = self._payload_path(scope)
        scope_payload = _scope_payload(scope)
        try:
            return read_json_dict(
                path,
                label=f"file state authority {_scope_label(scope)}",
                missing_factory=lambda: {
                    **scope_payload,
                    "state": _authority_for_scope(scope).to_dict(),
                    "events": [],
                },
            )
        except (JsonFileStoreError, JsonFilePayloadCorrupt) as exc:
            raise RuntimeError(str(exc)) from exc

    def _write_payload(self, scope: dict[str, Any], payload: dict[str, Any]) -> None:
        path = self._payload_path(scope)
        try:
            write_json_dict(path, payload, label=f"file state authority {_scope_label(scope)}")
        except JsonFileStoreError as exc:
            raise RuntimeError(str(exc)) from exc

    def _authority_from_payload(self, scope: dict[str, Any], payload: dict[str, Any]) -> FileStateAuthority:
        state_payload = dict(payload.get("state") or payload)
        authority = FileStateAuthority.from_dict(state_payload)
        scope_authority = _authority_for_scope(scope, files=authority.files)
        if (
            authority.task_run_id != scope_authority.task_run_id
            or authority.scope_kind != scope_authority.scope_kind
            or authority.scope_id != scope_authority.scope_id
            or authority.session_id != scope_authority.session_id
        ):
            authority = scope_authority
        if authority.files or not payload.get("events"):
            return authority
        replayed = _authority_for_scope(scope)
        for item in [dict(raw) for raw in list(payload.get("events") or []) if isinstance(raw, dict)]:
            event = dict(item.get("event") or item)
            replayed = replayed.apply_event(
                event,
                observation_ref=str(item.get("observation_ref") or event.get("observation_ref") or ""),
                tool_call_id=str(item.get("tool_call_id") or event.get("tool_call_id") or ""),
            )
        return replayed


def _scope_payload(scope: dict[str, Any]) -> dict[str, Any]:
    evidence_scope = normalize_file_evidence_scope(scope)
    return _drop_empty(
        {
            "scope_kind": str(evidence_scope.get("kind") or ""),
            "scope_id": str(evidence_scope.get("scope_id") or ""),
            "session_id": str(evidence_scope.get("session_id") or ""),
            "task_run_id": str(evidence_scope.get("task_run_id") or ""),
            "file_evidence_scope": evidence_scope,
            "authority": FILE_STATE_STORE_AUTHORITY,
        }
    )


def _bind_read_observation_alias(root_dir: Path, event: dict[str, Any], *, observation_ref: str) -> None:
    if str(event.get("event_type") or event.get("type") or "") != "read":
        return
    artifact_ref = str(event.get("exact_artifact_ref") or "").strip()
    if not artifact_ref:
        return
    try:
        ReadObservationArtifactStore(root_dir).bind_observation_ref(
            artifact_ref=artifact_ref,
            observation_ref=str(observation_ref or ""),
            tool_result_ref=str(event.get("tool_result_ref") or ""),
        )
    except Exception:
        return


def _authority_for_scope(scope: dict[str, Any], *, files: tuple[Any, ...] = ()) -> FileStateAuthority:
    evidence_scope = normalize_file_evidence_scope(scope)
    return FileStateAuthority(
        task_run_id=str(evidence_scope.get("task_run_id") or ""),
        scope_kind=str(evidence_scope.get("kind") or ""),
        scope_id=str(evidence_scope.get("scope_id") or ""),
        session_id=str(evidence_scope.get("session_id") or ""),
        files=tuple(files),
    )


def _scope_storage_key(scope: dict[str, Any]) -> str:
    evidence_scope = normalize_file_evidence_scope(scope)
    kind = str(evidence_scope.get("kind") or "").strip()
    scope_id = str(evidence_scope.get("scope_id") or "").strip()
    if kind == "task_run":
        return _safe_id(scope_id)
    return f"{_safe_id(kind)}__{_safe_id(scope_id)}"


def _scope_label(scope: dict[str, Any]) -> str:
    evidence_scope = normalize_file_evidence_scope(scope)
    kind = str(evidence_scope.get("kind") or "").strip() or "unknown"
    scope_id = str(evidence_scope.get("scope_id") or "").strip() or "unknown"
    return f"{kind}:{scope_id}"


def _event_payload(event: dict[str, Any], *, observation_ref: str, tool_call_id: str) -> dict[str, Any]:
    payload = dict(event or {})
    if observation_ref and not str(payload.get("observation_ref") or "").strip():
        payload["observation_ref"] = observation_ref
    if tool_call_id and not str(payload.get("tool_call_id") or "").strip():
        payload["tool_call_id"] = tool_call_id
    return _drop_empty(payload)


def _file_state_snapshot_events(
    snapshot: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    source_scope: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], ...]:
    events: list[dict[str, Any]] = []
    source = normalize_file_evidence_scope(source_scope)
    source_kind = str(source.get("kind") or "")
    source_scope_id = str(source.get("scope_id") or "")
    for raw_file_state in [dict(item) for item in list(snapshot or []) if isinstance(item, dict)]:
        path = str(raw_file_state.get("path") or "").replace("\\", "/").strip().strip("/")
        if not path:
            continue
        total_lines = raw_file_state.get("total_lines")
        file_hash = raw_file_state.get("content_sha256")
        file_mtime = raw_file_state.get("mtime_ns")
        for raw_range in [dict(item) for item in list(raw_file_state.get("read_ranges") or []) if isinstance(item, dict)]:
            if raw_range.get("stale") is True:
                continue
            events.append(
                _drop_empty(
                    {
                        "event_type": "read",
                        "path": path,
                        "start_line": raw_range.get("start_line"),
                        "end_line": raw_range.get("end_line"),
                        "total_lines": total_lines,
                        "content_sha256": raw_range.get("content_sha256") or file_hash,
                        "mtime_ns": raw_range.get("mtime_ns") or file_mtime,
                        "read_intent": raw_range.get("read_intent"),
                        "reusable_result_ref": raw_range.get("reusable_result_ref"),
                        "exact_artifact_ref": raw_range.get("exact_artifact_ref"),
                        "artifact_ref_status": raw_range.get("artifact_ref_status"),
                        "visible_exact": raw_range.get("visible_exact"),
                        "text_sha256": raw_range.get("text_sha256"),
                        "next_start_line": raw_range.get("next_start_line"),
                        "has_more": raw_range.get("has_more"),
                        "observation_ref": raw_range.get("observation_ref") or raw_file_state.get("last_observation_ref"),
                        "tool_call_id": raw_range.get("tool_call_id") or raw_file_state.get("last_tool_call_id"),
                        "source_scope_kind": source_kind,
                        "source_scope_id": source_scope_id,
                    }
                )
            )
        search_hits_by_query: dict[str, list[dict[str, Any]]] = {}
        for raw_hit in [dict(item) for item in list(raw_file_state.get("search_hits") or []) if isinstance(item, dict)]:
            query = str(raw_hit.get("query") or "")
            if not query:
                continue
            search_hits_by_query.setdefault(query, []).append(
                _drop_empty({"line": raw_hit.get("line"), "preview": raw_hit.get("preview")})
            )
        for query, matches in search_hits_by_query.items():
            events.append(
                _drop_empty(
                    {
                        "event_type": "search",
                        "path": path,
                        "query": query,
                        "matches": matches,
                        "observation_ref": raw_file_state.get("last_observation_ref"),
                        "tool_call_id": raw_file_state.get("last_tool_call_id"),
                        "source_scope_kind": source_kind,
                        "source_scope_id": source_scope_id,
                    }
                )
            )
        for raw_write in [dict(item) for item in list(raw_file_state.get("write_events") or []) if isinstance(item, dict)]:
            operation = str(raw_write.get("operation") or "").strip()
            if operation not in {"write", "edit"}:
                continue
            events.append(
                _drop_empty(
                    {
                        "event_type": operation,
                        "path": path,
                        "content_sha256": raw_write.get("content_sha256_after") or file_hash,
                        "observation_ref": raw_write.get("observation_ref") or raw_file_state.get("last_observation_ref"),
                        "tool_call_id": raw_file_state.get("last_tool_call_id"),
                        "source_scope_kind": source_kind,
                        "source_scope_id": source_scope_id,
                    }
                )
            )
        if raw_file_state.get("exists") is False:
            events.append(
                _drop_empty(
                    {
                        "event_type": "exists",
                        "path": path,
                        "exists": False,
                        "observation_ref": raw_file_state.get("last_observation_ref"),
                        "tool_call_id": raw_file_state.get("last_tool_call_id"),
                        "source_scope_kind": source_kind,
                        "source_scope_id": source_scope_id,
                    }
                )
            )
    return tuple(events)


def _bounded_event_history(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return events[-FILE_STATE_EVENT_HISTORY_LIMIT:]


def _safe_id(value: str, *, limit: int = 160) -> str:
    raw = str(value or "")
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in raw).strip("_")
    if not safe:
        return "runtime"
    if len(safe) <= limit:
        return safe
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    head_limit = max(1, limit - len(digest) - 1)
    return f"{safe[:head_limit].rstrip('_')}_{digest}"


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {}, ())}

