from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any


DEFAULT_EVENT_PAYLOAD_INLINE_BYTES = 32 * 1024
PAYLOAD_PREVIEW_CHARS = 1200


class RuntimeEventPayloadStore:
    """Sidecar storage for oversized runtime event payloads.

    Runtime JSONL remains the append-only fact chain, but the hot event row must
    stay small enough for monitor, trace tail, and resume indexes. Oversized
    payloads are written first and the event row stores a stable reference plus
    a public preview.
    """

    authority = "orchestration.runtime_event_payload_store"

    def __init__(self, root_dir: Path, *, inline_bytes: int = DEFAULT_EVENT_PAYLOAD_INLINE_BYTES) -> None:
        self.root_dir = Path(root_dir)
        self.payload_dir = self.root_dir / "event_payloads"
        self.payload_dir.mkdir(parents=True, exist_ok=True)
        self.inline_bytes = max(1024, int(inline_bytes or DEFAULT_EVENT_PAYLOAD_INLINE_BYTES))

    def externalize_if_needed(
        self,
        *,
        run_id: str,
        event_id: str,
        offset: int,
        event_type: str,
        payload: dict[str, Any],
        refs: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        payload_dict = dict(payload or {})
        refs_dict = dict(refs or {})
        encoded = _json_bytes(payload_dict)
        if len(encoded) <= self.inline_bytes:
            return payload_dict, refs_dict

        payload_ref, relative_path = self._write_payload(
            run_id=run_id,
            event_id=event_id,
            offset=offset,
            event_type=event_type,
            payload=payload_dict,
            size_bytes=len(encoded),
        )
        compact_payload = _compact_payload_preview(payload_dict)
        compact_payload["payload_externalized"] = True
        compact_payload["payload_ref"] = payload_ref
        compact_payload["payload_size_bytes"] = len(encoded)
        refs_dict = {
            **refs_dict,
            "payload_ref": payload_ref,
            "payload_path": relative_path,
            "payload_size_bytes": len(encoded),
            "payload_externalized": True,
        }
        return compact_payload, refs_dict

    def hydrate_event_payload(self, event: dict[str, Any]) -> dict[str, Any]:
        refs = dict(event.get("refs") or {})
        payload_ref = str(refs.get("payload_ref") or dict(event.get("payload") or {}).get("payload_ref") or "").strip()
        if not payload_ref:
            return event
        stored = self.load_payload(payload_ref)
        if stored is None:
            return event
        return {
            **dict(event),
            "payload": stored,
            "refs": {
                **refs,
                "payload_ref": payload_ref,
                "payload_externalized": True,
            },
        }

    def load_payload(self, payload_ref: str) -> dict[str, Any] | None:
        ref = str(payload_ref or "").strip()
        if not ref.startswith("rtpayload:"):
            return None
        digest = ref.split(":", 1)[1]
        if not digest or any(ch not in "0123456789abcdef" for ch in digest.lower()):
            return None
        path = self.payload_dir / digest[:2] / f"{digest}.json"
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        payload = envelope.get("payload") if isinstance(envelope, dict) else None
        return dict(payload) if isinstance(payload, dict) else None

    def delete_payloads_for_run(self, run_id: str) -> int:
        safe_run_id = _safe_id(run_id)
        deleted = 0
        for path in self.payload_dir.glob("*/*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            stored_run_id = str(payload.get("run_id") or payload.get("task_run_id") or "")
            stored_safe_id = str(payload.get("safe_run_id") or payload.get("safe_task_run_id") or "")
            if stored_run_id != run_id or stored_safe_id != safe_run_id:
                continue
            try:
                path.unlink()
                deleted += 1
            except OSError:
                pass
        return deleted

    def _write_payload(
        self,
        *,
        run_id: str,
        event_id: str,
        offset: int,
        event_type: str,
        payload: dict[str, Any],
        size_bytes: int,
    ) -> tuple[str, str]:
        digest_source = json.dumps(
            {
                "run_id": run_id,
                "event_id": event_id,
                "offset": offset,
                "event_type": event_type,
                "payload": payload,
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ).encode("utf-8")
        digest = hashlib.sha256(digest_source).hexdigest()
        path = self.payload_dir / digest[:2] / f"{digest}.json"
        envelope = {
            "authority": self.authority,
            "payload_ref": f"rtpayload:{digest}",
            "run_id": run_id,
            "safe_run_id": _safe_id(run_id),
            "event_id": event_id,
            "offset": int(offset),
            "event_type": str(event_type or ""),
            "size_bytes": int(size_bytes),
            "payload": payload,
        }
        _atomic_write_json(path, envelope)
        return f"rtpayload:{digest}", path.relative_to(self.root_dir).as_posix()


def _compact_payload_preview(payload: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key in (
        "step",
        "status",
        "summary",
        "public_progress_note",
        "agent_brief_output",
        "presentation_source",
        "terminal_reason",
        "error",
        "reason",
        "run_id",
        "task_run_id",
        "invocation_index",
    ):
        value = payload.get(key)
        if value not in (None, "", [], {}):
            compact[key] = _compact_value(value)
    observation = payload.get("observation")
    if isinstance(observation, dict):
        compact["observation"] = {
            key: _compact_value(observation.get(key))
            for key in ("source", "summary", "observation_type")
            if observation.get(key) not in (None, "")
        }
    action_request = payload.get("action_request")
    if isinstance(action_request, dict):
        compact["action_request"] = {
            key: _compact_value(action_request.get(key))
            for key in ("action_type", "tool_name", "request_type", "final_answer")
            if action_request.get(key) not in (None, "")
        }
    packet = payload.get("packet")
    if isinstance(packet, dict):
        compact["packet"] = {
            key: _compact_value(packet.get(key))
            for key in ("packet_id", "task_run_id", "invocation_kind", "invocation_index")
            if packet.get(key) not in (None, "")
        }
    if not compact:
        compact["preview"] = _compact_value(payload)
    return compact


def _compact_value(value: Any, *, limit: int = PAYLOAD_PREVIEW_CHARS) -> Any:
    if isinstance(value, str):
        text = value.strip()
        return text if len(text) <= limit else f"{text[: limit - 3]}..."
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _compact_value(item, limit=limit) for key, item in list(value.items())[:16]}
    if isinstance(value, (list, tuple)):
        return [_compact_value(item, limit=limit) for item in list(value)[:8]]
    return _compact_value(str(value), limit=limit)


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


def _safe_id(value: str, *, limit: int = 180) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or "")).strip("_")
    return (safe or "runtime")[:limit]
