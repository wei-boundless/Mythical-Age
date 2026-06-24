from __future__ import annotations

import threading
import time
import uuid
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Literal

from core.json_file_store import JsonFilePayloadCorrupt, JsonFileStoreError, json_file_lock, read_json_dict, write_json_dict


QueuedUserInputStatus = Literal["queued", "dispatching", "dispatched", "failed", "canceled"]
QueuedUserInputPolicy = Literal["auto", "steer"]

_QUEUE_LOCK = threading.RLock()
_QUEUE_STATUSES: set[str] = {"queued", "dispatching", "dispatched", "failed", "canceled"}
_QUEUE_POLICIES: set[str] = {"auto", "steer"}


@dataclass(frozen=True, slots=True)
class QueuedUserInput:
    queue_item_id: str
    session_id: str
    client_message_id: str
    content: str
    input_policy: QueuedUserInputPolicy
    status: QueuedUserInputStatus
    created_at: float
    updated_at: float
    attachments: list[dict[str, Any]]
    session_scope: dict[str, Any]
    environment_binding: dict[str, Any]
    runtime_contract: dict[str, Any]
    explicit_subtasks: list[dict[str, Any]]
    model_selection: dict[str, Any]
    permission_mode: str = ""
    expected_active_turn_id: str = ""
    task_run_id: str = ""
    editor_context: dict[str, Any] | None = None
    dispatch_stream_run_id: str = ""
    failure_reason: str = ""
    authority: str = "runtime.queued_user_input_store"

    def __post_init__(self) -> None:
        if self.authority != "runtime.queued_user_input_store":
            raise ValueError("QueuedUserInput authority must be runtime.queued_user_input_store")
        if not self.queue_item_id:
            raise ValueError("QueuedUserInput requires queue_item_id")
        if not self.session_id:
            raise ValueError("QueuedUserInput requires session_id")
        if self.status not in _QUEUE_STATUSES:
            raise ValueError(f"invalid queued input status: {self.status}")
        if self.input_policy not in _QUEUE_POLICIES:
            raise ValueError(f"invalid queued input policy: {self.input_policy}")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["attachments"] = [dict(item) for item in list(self.attachments or []) if isinstance(item, dict)]
        payload["session_scope"] = dict(self.session_scope or {})
        payload["environment_binding"] = dict(self.environment_binding or {})
        payload["runtime_contract"] = dict(self.runtime_contract or {})
        payload["explicit_subtasks"] = [dict(item) for item in list(self.explicit_subtasks or []) if isinstance(item, dict)]
        payload["model_selection"] = dict(self.model_selection or {})
        payload["editor_context"] = dict(self.editor_context or {})
        return payload


class QueuedUserInputStore:
    authority = "runtime.queued_user_input_store"

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)
        self.queue_dir = self.root_dir / "queued_user_inputs"
        self.queue_dir.mkdir(parents=True, exist_ok=True)

    def enqueue(
        self,
        *,
        session_id: str,
        content: str,
        client_message_id: str = "",
        input_policy: str = "auto",
        expected_active_turn_id: str = "",
        task_run_id: str = "",
        attachments: list[dict[str, Any]] | None = None,
        session_scope: dict[str, Any] | None = None,
        environment_binding: dict[str, Any] | None = None,
        runtime_contract: dict[str, Any] | None = None,
        explicit_subtasks: list[dict[str, Any]] | None = None,
        model_selection: dict[str, Any] | None = None,
        permission_mode: str = "",
        editor_context: dict[str, Any] | None = None,
    ) -> QueuedUserInput:
        normalized_session_id = _clean_text(session_id, limit=240)
        if not normalized_session_id:
            raise ValueError("QueuedUserInput requires session_id")
        normalized_content = str(content or "").strip()
        if not normalized_content:
            raise ValueError("QueuedUserInput requires content")
        normalized_client_message_id = _clean_text(client_message_id, limit=240)
        normalized_policy = _clean_policy(input_policy)
        path = self._session_path(normalized_session_id)
        now = time.time()
        with _QUEUE_LOCK, json_file_lock(path):
            payload = self._read_session_payload(normalized_session_id)
            items = self._items_from_payload(payload, normalized_session_id)
            if normalized_client_message_id:
                for item in items:
                    if item.client_message_id == normalized_client_message_id:
                        return item
            item = QueuedUserInput(
                queue_item_id=f"qinp:{uuid.uuid4().hex}",
                session_id=normalized_session_id,
                client_message_id=normalized_client_message_id or f"client:qinp:{uuid.uuid4().hex}",
                content=normalized_content,
                input_policy=normalized_policy,
                expected_active_turn_id=_clean_text(expected_active_turn_id, limit=300),
                task_run_id=_clean_text(task_run_id, limit=300),
                attachments=_dict_list(attachments),
                session_scope=dict(session_scope or {}),
                environment_binding=dict(environment_binding or {}),
                runtime_contract=dict(runtime_contract or {}),
                explicit_subtasks=_dict_list(explicit_subtasks),
                model_selection=dict(model_selection or {}),
                permission_mode=_clean_text(permission_mode, limit=80),
                editor_context=dict(editor_context or {}),
                status="queued",
                dispatch_stream_run_id="",
                failure_reason="",
                created_at=now,
                updated_at=now,
            )
            items.append(item)
            self._write_items(normalized_session_id, items)
            return item

    def list_session(self, session_id: str, *, include_terminal: bool = True) -> list[QueuedUserInput]:
        normalized_session_id = _clean_text(session_id, limit=240)
        if not normalized_session_id:
            return []
        items = self._items_from_payload(self._read_session_payload(normalized_session_id), normalized_session_id)
        if include_terminal:
            return items
        return [item for item in items if item.status in {"queued", "dispatching"}]

    def claim_next(self, session_id: str, *, policy: str = "") -> QueuedUserInput | None:
        normalized_session_id = _clean_text(session_id, limit=240)
        if not normalized_session_id:
            return None
        normalized_policy = _clean_policy(policy) if policy else ""
        path = self._session_path(normalized_session_id)
        now = time.time()
        with _QUEUE_LOCK, json_file_lock(path):
            items = self._items_from_payload(self._read_session_payload(normalized_session_id), normalized_session_id)
            for index, item in enumerate(items):
                if item.status != "queued":
                    continue
                if normalized_policy and item.input_policy != normalized_policy:
                    continue
                claimed = replace(item, status="dispatching", updated_at=now, failure_reason="")
                items[index] = claimed
                self._write_items(normalized_session_id, items)
                return claimed
        return None

    def claim_for_active_turn(
        self,
        session_id: str,
        *,
        turn_id: str,
        task_run_id: str = "",
        limit: int = 8,
    ) -> list[QueuedUserInput]:
        normalized_session_id = _clean_text(session_id, limit=240)
        normalized_turn_id = _clean_text(turn_id, limit=300)
        normalized_task_run_id = _clean_text(task_run_id, limit=300)
        if not normalized_session_id or not normalized_turn_id:
            return []
        max_items = max(1, min(32, int(limit or 8)))
        path = self._session_path(normalized_session_id)
        now = time.time()
        claimed: list[QueuedUserInput] = []
        with _QUEUE_LOCK, json_file_lock(path):
            items = self._items_from_payload(self._read_session_payload(normalized_session_id), normalized_session_id)
            updated_items: list[QueuedUserInput] = []
            for item in items:
                if item.status != "queued" or len(claimed) >= max_items:
                    updated_items.append(item)
                    continue
                expected_turn_id = _clean_text(item.expected_active_turn_id, limit=300)
                expected_task_run_id = _clean_text(item.task_run_id, limit=300)
                if expected_turn_id and expected_turn_id != normalized_turn_id:
                    updated_items.append(item)
                    continue
                if expected_task_run_id and expected_task_run_id != normalized_task_run_id:
                    updated_items.append(item)
                    continue
                active_turn_item = replace(
                    item,
                    input_policy="steer",
                    expected_active_turn_id=normalized_turn_id,
                    task_run_id=normalized_task_run_id or expected_task_run_id,
                    status="dispatching",
                    updated_at=now,
                    failure_reason="",
                )
                claimed.append(active_turn_item)
                updated_items.append(active_turn_item)
            if claimed:
                self._write_items(normalized_session_id, updated_items)
        return claimed

    def retarget_for_dispatch(
        self,
        session_id: str,
        queue_item_id: str,
        *,
        input_policy: str,
        expected_active_turn_id: str = "",
        task_run_id: str = "",
    ) -> QueuedUserInput | None:
        normalized_session_id = _clean_text(session_id, limit=240)
        normalized_queue_item_id = _clean_text(queue_item_id, limit=240)
        if not normalized_session_id or not normalized_queue_item_id:
            return None
        normalized_policy = _clean_policy(input_policy)
        path = self._session_path(normalized_session_id)
        now = time.time()
        with _QUEUE_LOCK, json_file_lock(path):
            items = self._items_from_payload(self._read_session_payload(normalized_session_id), normalized_session_id)
            for index, item in enumerate(items):
                if item.queue_item_id != normalized_queue_item_id or item.status != "queued":
                    continue
                updated = replace(
                    item,
                    input_policy=normalized_policy,
                    expected_active_turn_id=_clean_text(expected_active_turn_id, limit=300),
                    task_run_id=_clean_text(task_run_id, limit=300),
                    updated_at=now,
                    failure_reason="",
                )
                items[index] = updated
                self._write_items(normalized_session_id, items)
                return updated
        return None

    def mark_dispatched(self, session_id: str, queue_item_id: str, *, stream_run_id: str) -> QueuedUserInput | None:
        return self._update_item(
            session_id,
            queue_item_id,
            status="dispatched",
            dispatch_stream_run_id=_clean_text(stream_run_id, limit=240),
            failure_reason="",
        )

    def mark_failed(self, session_id: str, queue_item_id: str, *, reason: str) -> QueuedUserInput | None:
        return self._update_item(
            session_id,
            queue_item_id,
            status="failed",
            failure_reason=_clean_text(reason, limit=500),
        )

    def cancel(self, session_id: str, queue_item_id: str, *, reason: str = "user_canceled") -> QueuedUserInput | None:
        current = self.get_item(session_id, queue_item_id)
        if current is None or current.status not in {"queued", "dispatching"}:
            return current
        return self._update_item(
            session_id,
            queue_item_id,
            status="canceled",
            failure_reason=_clean_text(reason, limit=500),
        )

    def get_item(self, session_id: str, queue_item_id: str) -> QueuedUserInput | None:
        normalized_queue_item_id = _clean_text(queue_item_id, limit=240)
        for item in self.list_session(session_id):
            if item.queue_item_id == normalized_queue_item_id:
                return item
        return None

    def reset_stale_dispatching(self, session_id: str, *, max_age_seconds: float = 300.0) -> list[QueuedUserInput]:
        normalized_session_id = _clean_text(session_id, limit=240)
        if not normalized_session_id:
            return []
        path = self._session_path(normalized_session_id)
        now = time.time()
        reset: list[QueuedUserInput] = []
        with _QUEUE_LOCK, json_file_lock(path):
            items = self._items_from_payload(self._read_session_payload(normalized_session_id), normalized_session_id)
            updated: list[QueuedUserInput] = []
            for item in items:
                if item.status == "dispatching" and now - float(item.updated_at or 0.0) >= max(1.0, float(max_age_seconds or 0.0)):
                    item = replace(item, status="queued", updated_at=now, failure_reason="")
                    reset.append(item)
                updated.append(item)
            if reset:
                self._write_items(normalized_session_id, updated)
        return reset

    def _update_item(
        self,
        session_id: str,
        queue_item_id: str,
        *,
        status: QueuedUserInputStatus,
        dispatch_stream_run_id: str | None = None,
        failure_reason: str | None = None,
    ) -> QueuedUserInput | None:
        normalized_session_id = _clean_text(session_id, limit=240)
        normalized_queue_item_id = _clean_text(queue_item_id, limit=240)
        if not normalized_session_id or not normalized_queue_item_id:
            return None
        path = self._session_path(normalized_session_id)
        now = time.time()
        with _QUEUE_LOCK, json_file_lock(path):
            items = self._items_from_payload(self._read_session_payload(normalized_session_id), normalized_session_id)
            for index, item in enumerate(items):
                if item.queue_item_id != normalized_queue_item_id:
                    continue
                updated = replace(
                    item,
                    status=status,
                    dispatch_stream_run_id=item.dispatch_stream_run_id if dispatch_stream_run_id is None else dispatch_stream_run_id,
                    failure_reason=item.failure_reason if failure_reason is None else failure_reason,
                    updated_at=now,
                )
                items[index] = updated
                self._write_items(normalized_session_id, items)
                return updated
        return None

    def _read_session_payload(self, session_id: str) -> dict[str, Any]:
        path = self._session_path(session_id)
        try:
            payload = read_json_dict(
                path,
                label=f"queued user inputs {session_id}",
                missing_factory=lambda: self._empty_payload(session_id),
            )
        except (JsonFileStoreError, JsonFilePayloadCorrupt):
            return self._empty_payload(session_id)
        return payload

    def _items_from_payload(self, payload: dict[str, Any], session_id: str) -> list[QueuedUserInput]:
        items: list[QueuedUserInput] = []
        for raw in list(dict(payload or {}).get("items") or []):
            if not isinstance(raw, dict):
                continue
            try:
                items.append(_queued_input_from_payload(raw, session_id=session_id))
            except (TypeError, ValueError):
                continue
        return sorted(items, key=lambda item: (item.created_at, item.queue_item_id))

    def _write_items(self, session_id: str, items: list[QueuedUserInput]) -> None:
        write_json_dict(
            self._session_path(session_id),
            {
                **self._empty_payload(session_id),
                "updated_at": time.time(),
                "items": [item.to_dict() for item in items],
            },
            label=f"queued user inputs {session_id}",
            sort_keys=True,
        )

    def _session_path(self, session_id: str) -> Path:
        return self.queue_dir / f"{_safe_segment(session_id)}.json"

    @classmethod
    def _empty_payload(cls, session_id: str) -> dict[str, Any]:
        return {
            "session_id": str(session_id or "").strip(),
            "items": [],
            "updated_at": 0.0,
            "authority": cls.authority,
        }


def _queued_input_from_payload(payload: dict[str, Any], *, session_id: str) -> QueuedUserInput:
    status = str(payload.get("status") or "queued").strip()
    if status not in _QUEUE_STATUSES:
        status = "queued"
    policy = _clean_policy(payload.get("input_policy") or "auto")
    return QueuedUserInput(
        queue_item_id=_clean_text(payload.get("queue_item_id"), limit=240),
        session_id=_clean_text(payload.get("session_id") or session_id, limit=240),
        client_message_id=_clean_text(payload.get("client_message_id"), limit=240),
        content=str(payload.get("content") or "").strip(),
        input_policy=policy,
        expected_active_turn_id=_clean_text(payload.get("expected_active_turn_id"), limit=300),
        task_run_id=_clean_text(payload.get("task_run_id"), limit=300),
        attachments=_dict_list(payload.get("attachments")),
        session_scope=dict(payload.get("session_scope") or {}),
        environment_binding=dict(payload.get("environment_binding") or {}),
        runtime_contract=dict(payload.get("runtime_contract") or {}),
        explicit_subtasks=_dict_list(payload.get("explicit_subtasks")),
        model_selection=dict(payload.get("model_selection") or {}),
        permission_mode=_clean_text(payload.get("permission_mode"), limit=80),
        editor_context=dict(payload.get("editor_context") or {}),
        status=status,  # type: ignore[arg-type]
        dispatch_stream_run_id=_clean_text(payload.get("dispatch_stream_run_id"), limit=240),
        failure_reason=_clean_text(payload.get("failure_reason"), limit=500),
        created_at=_safe_float(payload.get("created_at")),
        updated_at=_safe_float(payload.get("updated_at")),
        authority=_clean_text(payload.get("authority"), limit=120) or QueuedUserInputStore.authority,
    )


def _clean_policy(value: Any) -> QueuedUserInputPolicy:
    normalized = str(value or "auto").strip().lower()
    return "steer" if normalized == "steer" else "auto"


def _clean_text(value: Any, *, limit: int) -> str:
    return str(value or "").replace("\r", " ").replace("\n", " ").replace("\t", " ").strip()[: max(0, int(limit))]


def _dict_list(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)]


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _safe_segment(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or ""))[:180]

