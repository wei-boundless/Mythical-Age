from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from json_file_store import JsonFilePayloadCorrupt, JsonFileStoreError, json_file_lock, read_json_dict, write_json_dict

from .file_state_authority import FileStateAuthority, file_state_events_from_observation


FILE_STATE_STORE_AUTHORITY = "runtime.memory.file_state_store"
FILE_STATE_EVENT_HISTORY_LIMIT = 500


class FileStateAuthorityStore:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)
        self.file_state_dir = self.root_dir / "file_state"
        self.file_state_dir.mkdir(parents=True, exist_ok=True)

    def load(self, task_run_id: str) -> FileStateAuthority:
        task_id = str(task_run_id or "").strip()
        if not task_id:
            return FileStateAuthority()
        with json_file_lock(self._payload_path(task_id)):
            payload = self._load_payload(task_id)
        return self._authority_from_payload(task_id, payload)

    def apply_observation(self, task_run_id: str, observation: dict[str, Any]) -> FileStateAuthority:
        extracted = file_state_events_from_observation(dict(observation or {}))
        return self.apply_events(
            task_run_id,
            extracted.events,
            observation_ref=extracted.observation_ref,
            tool_call_id=extracted.tool_call_id,
        )

    def apply_events(
        self,
        task_run_id: str,
        events: list[dict[str, Any]] | tuple[dict[str, Any], ...],
        *,
        observation_ref: str = "",
        tool_call_id: str = "",
    ) -> FileStateAuthority:
        task_id = str(task_run_id or "").strip()
        if not task_id:
            return FileStateAuthority()
        normalized_events = tuple(dict(item) for item in list(events or []) if isinstance(item, dict))
        with json_file_lock(self._payload_path(task_id)):
            payload = self._load_payload(task_id)
            authority = self._authority_from_payload(task_id, payload)
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
                task_id,
                {
                    "task_run_id": task_id,
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

    def snapshot(self, task_run_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        return self.load(task_run_id).projection(limit=limit)

    def prune_task_runs(self, task_run_ids: set[str] | list[str] | tuple[str, ...]) -> dict[str, Any]:
        targets = {str(item).strip() for item in task_run_ids if str(item).strip()}
        deleted: list[str] = []
        for task_run_id in sorted(targets):
            path = self._payload_path(task_run_id)
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

    def _payload_path(self, task_run_id: str) -> Path:
        return self.file_state_dir / f"{_safe_id(task_run_id)}.json"

    def _load_payload(self, task_run_id: str) -> dict[str, Any]:
        path = self._payload_path(task_run_id)
        try:
            return read_json_dict(
                path,
                label=f"file state authority {task_run_id}",
                missing_factory=lambda: {"task_run_id": task_run_id, "state": FileStateAuthority(task_run_id=task_run_id).to_dict(), "events": []},
            )
        except (JsonFileStoreError, JsonFilePayloadCorrupt) as exc:
            raise RuntimeError(str(exc)) from exc

    def _write_payload(self, task_run_id: str, payload: dict[str, Any]) -> None:
        path = self._payload_path(task_run_id)
        try:
            write_json_dict(path, payload, label=f"file state authority {task_run_id}")
        except JsonFileStoreError as exc:
            raise RuntimeError(str(exc)) from exc

    def _authority_from_payload(self, task_run_id: str, payload: dict[str, Any]) -> FileStateAuthority:
        state_payload = dict(payload.get("state") or payload)
        authority = FileStateAuthority.from_dict(state_payload)
        if authority.task_run_id != task_run_id:
            authority = FileStateAuthority(task_run_id=task_run_id, files=authority.files)
        if authority.files or not payload.get("events"):
            return authority
        replayed = FileStateAuthority(task_run_id=task_run_id)
        for item in [dict(raw) for raw in list(payload.get("events") or []) if isinstance(raw, dict)]:
            event = dict(item.get("event") or item)
            replayed = replayed.apply_event(
                event,
                observation_ref=str(item.get("observation_ref") or event.get("observation_ref") or ""),
                tool_call_id=str(item.get("tool_call_id") or event.get("tool_call_id") or ""),
            )
        return replayed


def _event_payload(event: dict[str, Any], *, observation_ref: str, tool_call_id: str) -> dict[str, Any]:
    payload = dict(event or {})
    if observation_ref and not str(payload.get("observation_ref") or "").strip():
        payload["observation_ref"] = observation_ref
    if tool_call_id and not str(payload.get("tool_call_id") or "").strip():
        payload["tool_call_id"] = tool_call_id
    return _drop_empty(payload)


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
