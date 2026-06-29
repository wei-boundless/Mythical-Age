from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from core.json_file_store import JsonFilePayloadCorrupt, JsonFileStoreError, json_file_lock, read_json_dict, write_json_dict

from .turn_memory_models import (
    TURN_MEMORY_AUTHORITY,
    TurnMemoryCheckpoint,
    TurnMemoryRecord,
    replace_turn_memory,
    sha256_text,
    stable_json_hash,
)


TURN_MEMORY_STORE_AUTHORITY = "runtime.turn_memory.store"

_TURN_MEMORY_LOCK = threading.RLock()


class TurnMemoryStore:
    authority = TURN_MEMORY_STORE_AUTHORITY

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)
        self.store_dir = self.root_dir / "turn_memory"
        self.store_dir.mkdir(parents=True, exist_ok=True)

    def create_or_get_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        turn_run_id: str = "",
        branch_id: str = "",
        parent_turn_id: str = "",
        current_user_message_ref: str = "",
    ) -> TurnMemoryRecord:
        normalized_session = _clean_id(session_id)
        normalized_turn = _clean_id(turn_id)
        if not normalized_session:
            raise ValueError("TurnMemory requires session_id")
        if not normalized_turn:
            raise ValueError("TurnMemory requires turn_id")
        path = self._turn_path(normalized_session, normalized_turn)
        now = time.time()
        with _TURN_MEMORY_LOCK, json_file_lock(path):
            existing = self._read_turn(normalized_session, normalized_turn)
            if existing is not None:
                if not _turn_memory_requires_replacement(existing):
                    return existing
                self._archive_superseded_turn(
                    existing,
                    reason="reused_turn_id_after_edit_resend",
                    replacement_turn_run_id=str(turn_run_id or ""),
                )
            record = TurnMemoryRecord(
                session_id=normalized_session,
                turn_id=normalized_turn,
                turn_run_id=str(turn_run_id or ""),
                branch_id=str(branch_id or normalized_session),
                parent_turn_id=str(parent_turn_id or ""),
                current_user_message_ref=str(current_user_message_ref or ""),
                created_at=now,
                updated_at=now,
            )
            self._write_turn(record)
            return record

    def get_turn(self, session_id: str, turn_id: str) -> TurnMemoryRecord | None:
        normalized_session = _clean_id(session_id)
        normalized_turn = _clean_id(turn_id)
        if not normalized_session or not normalized_turn:
            return None
        return self._read_turn(normalized_session, normalized_turn)

    def list_session_turns(self, session_id: str, *, include_released: bool = True) -> list[TurnMemoryRecord]:
        normalized_session = _clean_id(session_id)
        if not normalized_session:
            return []
        turns_dir = self._turns_dir(normalized_session)
        records: list[TurnMemoryRecord] = []
        if not turns_dir.exists():
            return []
        for path in sorted(turns_dir.glob("*.json")):
            try:
                payload = read_json_dict(path, label=f"turn memory {path.stem}")
                record = TurnMemoryRecord.from_dict(payload)
            except (JsonFileStoreError, ValueError):
                continue
            if not include_released and record.status == "released":
                continue
            records.append(record)
        return records

    def session_signature(self, session_id: str) -> tuple[int, int]:
        normalized_session = _clean_id(session_id)
        if not normalized_session:
            return (0, 0)
        session_dir = self.store_dir / _safe_segment(normalized_session)
        if not session_dir.exists():
            return (0, 0)
        newest_mtime_ns = 0
        total_size = 0
        for path in session_dir.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix == ".tmp":
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            newest_mtime_ns = max(newest_mtime_ns, int(stat.st_mtime_ns))
            total_size += int(stat.st_size)
        return newest_mtime_ns, total_size

    def session_projection(self, session_id: str, *, limit: int = 20) -> dict[str, Any]:
        normalized_session = _clean_id(session_id)
        if not normalized_session:
            return {
                "authority": "runtime.turn_memory.session_projection",
                "available": False,
                "reason": "missing_session_id",
                "turn_count": 0,
                "recent_turns": [],
            }
        records = sorted(
            self.list_session_turns(normalized_session, include_released=True),
            key=lambda item: (float(item.updated_at or item.created_at or 0.0), float(item.created_at or 0.0)),
        )
        checkpoint = self._last_checkpoint(normalized_session)
        latest = records[-1] if records else None
        active_or_pending = [
            record.turn_id
            for record in records
            if record.status not in {"terminal", "released", "superseded"}
        ]
        recent = [
            _project_turn_summary(record)
            for record in reversed(records[-max(1, min(int(limit or 20), 100)):])
        ]
        return {
            "authority": "runtime.turn_memory.session_projection",
            "available": bool(records),
            "session_id": normalized_session,
            "turn_count": len(records),
            "active_or_pending_turns": active_or_pending[-32:],
            "latest_turn": _project_turn_summary(latest) if latest is not None else {},
            "latest_physical_prefix_frame_id": str(getattr(latest, "physical_prefix_frame_id", "") or "") if latest is not None else "",
            "latest_provider_request_refs": list(getattr(latest, "provider_request_refs", ()) or ())[-16:] if latest is not None else [],
            "latest_provider_payload_manifest_refs": list(getattr(latest, "provider_payload_manifest_refs", ()) or ())[-16:] if latest is not None else [],
            "latest_commit_state": str(getattr(latest, "commit_state", "") or "") if latest is not None else "",
            "latest_current_append_hash": str(getattr(latest, "current_append_hash", "") or "") if latest is not None else "",
            "latest_checkpoint_hash": str(getattr(checkpoint, "checkpoint_hash", "") or "") if checkpoint is not None else "",
            "latest_checkpoint_kind": str(getattr(checkpoint, "checkpoint_kind", "") or "") if checkpoint is not None else "",
            "recent_turns": recent,
        }

    def patch_turn(self, session_id: str, turn_id: str, **changes: Any) -> TurnMemoryRecord:
        normalized_session = _clean_id(session_id)
        normalized_turn = _clean_id(turn_id)
        if not normalized_session or not normalized_turn:
            raise ValueError("TurnMemory patch requires session_id and turn_id")
        path = self._turn_path(normalized_session, normalized_turn)
        with _TURN_MEMORY_LOCK, json_file_lock(path):
            current = self._read_turn(normalized_session, normalized_turn)
            if current is None:
                raise ValueError(f"TurnMemory missing: {session_id}/{turn_id}")
            cleaned = _clean_changes(changes)
            updated = replace_turn_memory(current, updated_at=time.time(), **cleaned)
            self._write_turn(updated)
            return updated

    def add_steer_ref(self, *, session_id: str, turn_id: str, steer_ref: str) -> TurnMemoryRecord:
        normalized_ref = str(steer_ref or "").strip()
        if not normalized_ref:
            raise ValueError("steer_ref is required")
        current = self.get_turn(session_id, turn_id)
        if current is None:
            raise ValueError(f"TurnMemory missing: {session_id}/{turn_id}")
        refs = tuple(dict.fromkeys((*current.active_steer_refs, normalized_ref)))
        return self.patch_turn(session_id, turn_id, active_steer_refs=refs)

    def update_assistant_draft(
        self,
        *,
        session_id: str,
        turn_id: str,
        text: str = "",
        draft_ref: str = "",
        public_event_cursor: dict[str, Any] | None = None,
    ) -> TurnMemoryRecord:
        changes: dict[str, Any] = {}
        if draft_ref:
            changes["assistant_draft_ref"] = str(draft_ref or "")
        if text:
            changes["assistant_draft_sha256"] = sha256_text(text)
        if public_event_cursor is not None:
            changes["public_event_cursor"] = dict(public_event_cursor or {})
        if not changes:
            return self.get_turn(session_id, turn_id) or self.create_or_get_turn(session_id=session_id, turn_id=turn_id)
        self.create_or_get_turn(session_id=session_id, turn_id=turn_id)
        return self.patch_turn(session_id, turn_id, **changes)

    def record_assistant_final(
        self,
        *,
        session_id: str,
        turn_id: str,
        text: str = "",
        final_ref: str = "",
    ) -> TurnMemoryRecord:
        changes: dict[str, Any] = {"status": "final_ready"}
        if final_ref:
            changes["assistant_final_ref"] = str(final_ref or "")
        if text:
            changes["assistant_final_sha256"] = sha256_text(text)
        current = self.get_turn(session_id, turn_id)
        if current is not None and _turn_memory_write_closed(current):
            return current
        return self.patch_turn(session_id, turn_id, **changes)

    def append_provider_request_ref(
        self,
        *,
        session_id: str,
        turn_id: str,
        request_ref: str,
        provider_payload_manifest_ref: str = "",
        current_append_hash: str = "",
    ) -> TurnMemoryRecord:
        current = self.get_turn(session_id, turn_id)
        if current is None:
            raise ValueError(f"TurnMemory missing: {session_id}/{turn_id}")
        if _turn_memory_write_closed(current):
            return current
        request_refs = tuple(dict.fromkeys((*current.provider_request_refs, str(request_ref or "").strip())))
        manifest_refs = current.provider_payload_manifest_refs
        if str(provider_payload_manifest_ref or "").strip():
            manifest_refs = tuple(dict.fromkeys((*manifest_refs, str(provider_payload_manifest_ref or "").strip())))
        changes: dict[str, Any] = {
            "phase": "provider_request",
            "provider_request_refs": tuple(ref for ref in request_refs if ref),
            "provider_payload_manifest_refs": tuple(ref for ref in manifest_refs if ref),
        }
        if current_append_hash:
            changes["current_append_hash"] = str(current_append_hash or "")
        return self.patch_turn(session_id, turn_id, **changes)

    def record_provider_result(
        self,
        *,
        session_id: str,
        turn_id: str,
        request_ref: str,
        status: str,
        provider_payload_manifest_ref: str = "",
        physical_prefix_frame_id: str = "",
        frame_promotion_ref: str = "",
        pending_commit_summary: dict[str, Any] | None = None,
    ) -> TurnMemoryRecord:
        self.create_or_get_turn(session_id=session_id, turn_id=turn_id)
        current = self.get_turn(session_id, turn_id)
        if current is None:
            raise ValueError(f"TurnMemory missing: {session_id}/{turn_id}")
        if _turn_memory_write_closed(current):
            return current
        request_refs = tuple(dict.fromkeys((*current.provider_request_refs, str(request_ref or "").strip())))
        manifest_refs = current.provider_payload_manifest_refs
        if str(provider_payload_manifest_ref or "").strip():
            manifest_refs = tuple(dict.fromkeys((*manifest_refs, str(provider_payload_manifest_ref or "").strip())))
        summary = {
            **dict(current.pending_commit_summary or {}),
            **dict(pending_commit_summary or {}),
            "latest_provider_request_ref": str(request_ref or ""),
            "latest_provider_request_status": str(status or ""),
        }
        changes: dict[str, Any] = {
            "provider_request_refs": tuple(ref for ref in request_refs if ref),
            "provider_payload_manifest_refs": tuple(ref for ref in manifest_refs if ref),
            "pending_commit_summary": summary,
        }
        if str(physical_prefix_frame_id or "").strip():
            changes["physical_prefix_frame_id"] = str(physical_prefix_frame_id or "").strip()
        if str(frame_promotion_ref or "").strip():
            changes["frame_promotion_ref"] = str(frame_promotion_ref or "").strip()
        return self.patch_turn(session_id, turn_id, **changes)

    def record_tool_round(
        self,
        *,
        session_id: str,
        turn_id: str,
        tool_round: dict[str, Any],
        closed_tool_round_refs: tuple[str, ...] | list[str] = (),
    ) -> TurnMemoryRecord:
        current = self.get_turn(session_id, turn_id)
        if current is None:
            raise ValueError(f"TurnMemory missing: {session_id}/{turn_id}")
        if _turn_memory_write_closed(current):
            return current
        compact_round = _compact_tool_round(tool_round)
        rounds = tuple((*current.tool_rounds, compact_round))[-32:]
        closed_refs = tuple(
            dict.fromkeys(
                (
                    *current.closed_tool_round_refs,
                    *(str(item) for item in list(closed_tool_round_refs or []) if str(item or "").strip()),
                )
            )
        )[-128:]
        pending_tool_summary = {
            "latest_tool_round_ref": str(compact_round.get("tool_round_ref") or ""),
            "latest_tool_iteration": compact_round.get("tool_iteration"),
            "latest_statuses": list(compact_round.get("statuses") or []),
            "latest_error_count": int(compact_round.get("error_count") or 0),
            "authority": "runtime.turn_memory.tool_round_summary",
        }
        return self.patch_turn(
            session_id,
            turn_id,
            phase="tool_round",
            tool_rounds=rounds,
            closed_tool_round_refs=closed_refs,
            pending_tool_summary=pending_tool_summary,
        )

    def record_checkpoint(
        self,
        *,
        session_id: str,
        turn_id: str,
        checkpoint_kind: str,
        payload: dict[str, Any] | None = None,
    ) -> TurnMemoryCheckpoint:
        normalized_session = _clean_id(session_id)
        normalized_turn = _clean_id(turn_id)
        if not normalized_session or not normalized_turn:
            raise ValueError("checkpoint requires session_id and turn_id")
        record = self.get_turn(normalized_session, normalized_turn)
        if record is None:
            raise ValueError(f"TurnMemory missing: {session_id}/{turn_id}")
        checkpoints_path = self._checkpoints_path(normalized_session)
        with _TURN_MEMORY_LOCK, json_file_lock(checkpoints_path):
            previous = self._last_checkpoint(normalized_session)
            sequence = int(previous.sequence if previous is not None else 0) + 1
            body = {
                "checkpoint_id": f"turnmemckpt:{uuid.uuid4().hex}",
                "session_id": normalized_session,
                "turn_id": normalized_turn,
                "checkpoint_kind": str(checkpoint_kind or "checkpoint"),
                "sequence": sequence,
                "turn_memory_hash": stable_json_hash(record.to_dict()),
                "payload": dict(payload or {}),
                "previous_checkpoint_hash": previous.checkpoint_hash if previous is not None else "",
                "created_at": time.time(),
                "authority": "runtime.turn_memory.checkpoint",
            }
            body["checkpoint_hash"] = stable_json_hash(body)
            checkpoint = TurnMemoryCheckpoint.from_dict(body)
            self._append_jsonl(checkpoints_path, checkpoint.to_dict())
        if record.status == "active":
            self.patch_turn(normalized_session, normalized_turn, status="checkpointed")
        return checkpoint

    def record_edit_resend_cutoff(
        self,
        *,
        session_id: str,
        branch_cutoff_message_index: int,
        edit_resend_ref: str = "",
        superseded_turn_refs: tuple[str, ...] | list[str] = (),
    ) -> dict[str, Any]:
        normalized_session = _clean_id(session_id)
        if not normalized_session:
            raise ValueError("edit-resend cutoff requires session_id")
        payload = {
            "event_id": f"turnmemedit:{uuid.uuid4().hex}",
            "session_id": normalized_session,
            "branch_cutoff_message_index": max(0, int(branch_cutoff_message_index)),
            "edit_resend_ref": str(edit_resend_ref or ""),
            "superseded_turn_refs": [str(item) for item in list(superseded_turn_refs or []) if str(item or "").strip()],
            "created_at": time.time(),
            "authority": "runtime.turn_memory.edit_resend_cutoff",
        }
        payload["event_hash"] = stable_json_hash(payload)
        path = self._edit_resend_path(normalized_session)
        with _TURN_MEMORY_LOCK, json_file_lock(path):
            self._append_jsonl(path, payload)
        for turn_ref in payload["superseded_turn_refs"]:
            current = self.get_turn(normalized_session, turn_ref)
            if current is None or current.status in {"released", "superseded"}:
                continue
            self.patch_turn(
                normalized_session,
                turn_ref,
                status="superseded",
                phase="terminal",
                edit_resend_ref=str(edit_resend_ref or payload["event_id"]),
                branch_cutoff_message_index=payload["branch_cutoff_message_index"],
                recovery_state="superseded_by_edit_resend",
            )
        return payload

    def record_commit_result(
        self,
        *,
        session_id: str,
        turn_id: str,
        receipt: dict[str, Any],
    ) -> TurnMemoryRecord:
        current = self.get_turn(session_id, turn_id)
        if current is None:
            raise ValueError(f"TurnMemory missing: {session_id}/{turn_id}")
        if _turn_memory_write_closed(current):
            return current
        payload = dict(receipt or {})
        state = str(payload.get("state") or payload.get("status") or "").strip()
        anchor_message_id = str(payload.get("anchor_message_id") or "").strip()
        event_id = str(payload.get("event_id") or "").strip()
        event_type = str(payload.get("event_type") or "").strip()
        frame_ref = str(current.frame_promotion_ref or "").strip()
        frame_confirmed = bool(frame_ref and str(current.physical_prefix_frame_id or "").strip() == frame_ref)
        frame_pending = bool(state == "committed" and frame_ref and not frame_confirmed)
        status = "frame_pending" if frame_pending else ("terminal" if state == "committed" else "commit_pending")
        commit_state = "pending_frame_promotion" if frame_pending else ("committed" if state == "committed" else "pending_commit")
        summary = {
            "state": state,
            "status": str(payload.get("status") or ""),
            "reason": str(payload.get("reason") or ""),
            "event_type": event_type,
            "event_id": event_id,
            "checked_event_offset": payload.get("checked_event_offset"),
            "commit_allowed": bool(payload.get("commit_allowed") is True),
            "frame_promotion_ref": frame_ref,
            "physical_prefix_frame_id": str(current.physical_prefix_frame_id or ""),
            "authority": "runtime.turn_memory.commit_result",
        }
        return self.patch_turn(
            session_id,
            turn_id,
            status=status,
            phase="terminal" if status == "terminal" else "committing",
            commit_state=commit_state,
            session_commit_ref=anchor_message_id or event_id,
            pending_commit_summary=summary,
        )

    def record_terminal(
        self,
        *,
        session_id: str,
        turn_id: str,
        status: str,
        terminal_reason: str,
        terminal_event_ref: str = "",
    ) -> TurnMemoryRecord:
        current = self.get_turn(session_id, turn_id)
        if current is None:
            raise ValueError(f"TurnMemory missing: {session_id}/{turn_id}")
        if current.status in {"commit_pending", "frame_pending", "handoff_ready", "released", "superseded"}:
            return current
        summary = {
            **dict(current.pending_commit_summary or {}),
            "terminal_status": str(status or ""),
            "terminal_reason": str(terminal_reason or ""),
            "terminal_event_ref": str(terminal_event_ref or ""),
            "authority": "runtime.turn_memory.terminal",
        }
        return self.patch_turn(
            session_id,
            turn_id,
            status="terminal",
            phase="terminal",
            pending_commit_summary=summary,
        )

    def release_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        reason: str,
    ) -> TurnMemoryRecord:
        current = self.get_turn(session_id, turn_id)
        if current is None:
            raise ValueError(f"TurnMemory missing: {session_id}/{turn_id}")
        tombstone_seed = {
            "session_id": current.session_id,
            "turn_id": current.turn_id,
            "turn_run_id": current.turn_run_id,
            "reason": str(reason or "released"),
            "turn_memory_hash": stable_json_hash(current.to_dict()),
        }
        tombstone_hash = stable_json_hash(tombstone_seed)
        released = self.patch_turn(
            session_id,
            turn_id,
            status="released",
            release_state="released",
            released_at=time.time(),
            tombstone_hash=tombstone_hash,
        )
        tombstone = {
            **tombstone_seed,
            "tombstone_hash": tombstone_hash,
            "released_at": released.released_at,
            "authority": "runtime.turn_memory.release_tombstone",
        }
        path = self._tombstones_path(released.session_id)
        with _TURN_MEMORY_LOCK, json_file_lock(path):
            self._append_jsonl(path, tombstone)
        return released

    def _read_turn(self, session_id: str, turn_id: str) -> TurnMemoryRecord | None:
        path = self._turn_path(session_id, turn_id)
        if not path.exists():
            return None
        try:
            payload = read_json_dict(path, label=f"turn memory {session_id}/{turn_id}")
        except JsonFilePayloadCorrupt:
            raise
        except JsonFileStoreError:
            raise
        return TurnMemoryRecord.from_dict(payload)

    def _write_turn(self, record: TurnMemoryRecord) -> None:
        write_json_dict(
            self._turn_path(record.session_id, record.turn_id),
            record.to_dict(),
            label=f"turn memory {record.session_id}/{record.turn_id}",
            sort_keys=True,
        )

    def _archive_superseded_turn(
        self,
        record: TurnMemoryRecord,
        *,
        reason: str,
        replacement_turn_run_id: str,
    ) -> None:
        archive_seed = {
            "session_id": record.session_id,
            "turn_id": record.turn_id,
            "turn_run_id": record.turn_run_id,
            "replacement_turn_run_id": str(replacement_turn_run_id or ""),
            "reason": str(reason or "superseded_turn_archived"),
            "turn_memory_hash": stable_json_hash(record.to_dict()),
            "created_at": time.time(),
            "authority": "runtime.turn_memory.superseded_archive",
        }
        archive_id = archive_seed["turn_memory_hash"].removeprefix("sha256:")[:16]
        path = self._superseded_turn_path(record.session_id, record.turn_id, archive_id)
        write_json_dict(
            path,
            {
                **archive_seed,
                "record": record.to_dict(),
            },
            label=f"superseded turn memory {record.session_id}/{record.turn_id}",
            sort_keys=True,
        )

    def _last_checkpoint(self, session_id: str) -> TurnMemoryCheckpoint | None:
        path = self._checkpoints_path(session_id)
        if not path.exists():
            return None
        last: dict[str, Any] | None = None
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                last = item
        return TurnMemoryCheckpoint.from_dict(last) if last else None

    def _turns_dir(self, session_id: str) -> Path:
        return self.store_dir / _safe_segment(session_id) / "turns"

    def _turn_path(self, session_id: str, turn_id: str) -> Path:
        return self._turns_dir(session_id) / f"{_safe_segment(turn_id)}.json"

    def _checkpoints_path(self, session_id: str) -> Path:
        return self.store_dir / _safe_segment(session_id) / "checkpoints.jsonl"

    def _tombstones_path(self, session_id: str) -> Path:
        return self.store_dir / _safe_segment(session_id) / "tombstones.jsonl"

    def _edit_resend_path(self, session_id: str) -> Path:
        return self.store_dir / _safe_segment(session_id) / "edit_resend_cutoffs.jsonl"

    def _superseded_turn_path(self, session_id: str, turn_id: str, archive_id: str) -> Path:
        return (
            self.store_dir
            / _safe_segment(session_id)
            / "superseded_turns"
            / f"{_safe_segment(turn_id)}__{_safe_segment(archive_id)}.json"
        )

    @staticmethod
    def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            handle.write("\n")


def _clean_id(value: str, *, limit: int = 240) -> str:
    return str(value or "").strip()[:limit]


def _turn_memory_requires_replacement(record: TurnMemoryRecord) -> bool:
    if record.status == "superseded":
        return True
    if str(record.recovery_state or "").strip() == "superseded_by_edit_resend":
        return True
    if str(record.edit_resend_ref or "").strip() and int(record.branch_cutoff_message_index or -1) >= 0:
        return True
    return False


def _turn_memory_write_closed(record: TurnMemoryRecord) -> bool:
    return record.status in {"released", "superseded"}


def _safe_segment(value: str, *, limit: int = 180) -> str:
    text = str(value or "").strip()
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in text)[:limit] or "default"


def _clean_changes(changes: dict[str, Any]) -> dict[str, Any]:
    allowed = set(TurnMemoryRecord.__dataclass_fields__) - {"session_id", "turn_id", "created_at", "authority", "schema_version"}
    cleaned: dict[str, Any] = {}
    for key, value in dict(changes or {}).items():
        if key not in allowed:
            continue
        if key in {
            "active_steer_refs",
            "provider_request_refs",
            "provider_payload_manifest_refs",
            "closed_tool_round_refs",
            "aborted_action_refs",
            "public_projection_refs",
            "uncertain_side_effect_refs",
        }:
            cleaned[key] = tuple(str(item) for item in list(value or []) if str(item or "").strip())
        elif key == "tool_rounds":
            cleaned[key] = tuple(dict(item) for item in list(value or []) if isinstance(item, dict))
        elif key in {"pending_tool_summary", "public_event_cursor", "pending_commit_summary"}:
            cleaned[key] = dict(value or {})
        else:
            cleaned[key] = value
    return cleaned


def _compact_tool_round(payload: dict[str, Any]) -> dict[str, Any]:
    item = dict(payload or {})
    tool_calls = [
        _compact_tool_call(dict(entry))
        for entry in list(item.get("tool_calls") or [])
        if isinstance(entry, dict)
    ][:16]
    observations = [
        _compact_observation(dict(entry))
        for entry in list(item.get("observations") or [])
        if isinstance(entry, dict)
    ][:16]
    return {
        "tool_round_ref": str(item.get("tool_round_ref") or item.get("tool_batch_ref") or ""),
        "tool_iteration": item.get("tool_iteration"),
        "packet_ref": str(item.get("packet_ref") or ""),
        "tool_call_count": len(tool_calls),
        "observation_count": len(observations),
        "tool_calls": tool_calls,
        "observation_refs": [
            str(entry.get("observation_id") or entry.get("observation_ref") or "")
            for entry in observations
            if str(entry.get("observation_id") or entry.get("observation_ref") or "").strip()
        ],
        "statuses": [str(entry.get("status") or "") for entry in observations],
        "error_count": sum(1 for entry in observations if str(entry.get("status") or "") in {"error", "aborted", "canceled"}),
        "tool_context_refs": [
            str(entry.get("ref") or "")
            for entry in list(item.get("tool_context_entries") or [])
            if isinstance(entry, dict) and str(entry.get("ref") or "").strip()
        ][:32],
        "authority": "runtime.turn_memory.tool_round",
    }


def _compact_tool_call(payload: dict[str, Any]) -> dict[str, Any]:
    function = payload.get("function") if isinstance(payload.get("function"), dict) else {}
    return {
        "id": str(payload.get("id") or payload.get("tool_call_id") or ""),
        "name": str(payload.get("name") or payload.get("tool_name") or function.get("name") or ""),
        "type": str(payload.get("type") or "tool_call"),
    }


def _compact_observation(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "observation_id": str(payload.get("observation_id") or payload.get("observation_ref") or ""),
        "invocation_id": str(payload.get("invocation_id") or payload.get("tool_invocation_id") or ""),
        "tool_name": str(payload.get("tool_name") or payload.get("name") or ""),
        "tool_call_id": str(payload.get("tool_call_id") or ""),
        "status": str(payload.get("status") or ""),
        "result_ref": str(payload.get("result_ref") or ""),
        "artifact_refs": [str(item) for item in list(payload.get("artifact_refs") or [])[:8] if str(item or "").strip()],
    }


def _project_turn_summary(record: TurnMemoryRecord | None) -> dict[str, Any]:
    if record is None:
        return {}
    return {
        "turn_id": record.turn_id,
        "turn_run_id": record.turn_run_id,
        "branch_id": record.branch_id,
        "status": record.status,
        "phase": record.phase,
        "current_user_message_ref": record.current_user_message_ref,
        "provider_request_refs": list(record.provider_request_refs)[-16:],
        "provider_payload_manifest_refs": list(record.provider_payload_manifest_refs)[-16:],
        "physical_prefix_frame_id": record.physical_prefix_frame_id,
        "frame_promotion_ref": record.frame_promotion_ref,
        "current_append_hash": record.current_append_hash,
        "assistant_draft_ref": record.assistant_draft_ref,
        "assistant_draft_sha256": record.assistant_draft_sha256,
        "assistant_final_ref": record.assistant_final_ref,
        "assistant_final_sha256": record.assistant_final_sha256,
        "closed_tool_round_refs": list(record.closed_tool_round_refs)[-16:],
        "tool_round_count": len(record.tool_rounds),
        "active_steer_refs": list(record.active_steer_refs)[-16:],
        "edit_resend_ref": record.edit_resend_ref,
        "branch_cutoff_message_index": record.branch_cutoff_message_index,
        "commit_state": record.commit_state,
        "session_commit_ref": record.session_commit_ref,
        "pending_tool_summary": dict(record.pending_tool_summary),
        "pending_commit_summary": dict(record.pending_commit_summary),
        "recovery_state": record.recovery_state,
        "handoff_state": record.handoff_state,
        "release_state": record.release_state,
        "released_at": record.released_at,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "authority": "runtime.turn_memory.turn_projection",
    }
