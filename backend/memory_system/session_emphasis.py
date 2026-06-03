from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from .paths import normalize_session_id, safe_session_dir


SessionEmphasisStatus = Literal["active", "superseded", "resolved", "archived"]
SessionEmphasisPriority = Literal["low", "medium", "high"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_text(value: Any) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def priority_score(priority: str) -> int:
    normalized = str(priority or "").strip().lower()
    if normalized == "high":
        return 90
    if normalized == "low":
        return 30
    return 60


@dataclass(slots=True)
class SessionPinnedUserSteer:
    emphasis_id: str
    session_id: str
    turn_id: str
    task_environment_id: str
    scope: str
    content: str
    source_message_ref: str
    priority: SessionEmphasisPriority = "medium"
    status: SessionEmphasisStatus = "active"
    superseded_by: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SessionPinnedUserSteer":
        return cls(
            emphasis_id=normalize_text(payload.get("emphasis_id")),
            session_id=normalize_session_id(payload.get("session_id")),
            turn_id=normalize_text(payload.get("turn_id")),
            task_environment_id=normalize_text(payload.get("task_environment_id")),
            scope=normalize_text(payload.get("scope")) or "session_task",
            content=normalize_text(payload.get("content")),
            source_message_ref=normalize_text(payload.get("source_message_ref")),
            priority=_coerce_priority(payload.get("priority")),
            status=_coerce_status(payload.get("status")),
            superseded_by=normalize_text(payload.get("superseded_by")),
            created_at=normalize_text(payload.get("created_at")) or utc_now_iso(),
            updated_at=normalize_text(payload.get("updated_at")) or utc_now_iso(),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_pinned_fact(self) -> dict[str, Any]:
        return {
            "fact_id": self.emphasis_id,
            "kind": "session_emphasis",
            "content": self.content,
            "scope": self.scope,
            "priority": self.priority,
            "source_message_ref": self.source_message_ref,
            "task_environment_id": self.task_environment_id,
            "authority": "memory_system.session_emphasis",
        }


class SessionEmphasisStore:
    def __init__(self, session_root: str | Path) -> None:
        self.session_root = Path(session_root)
        self.session_root.mkdir(parents=True, exist_ok=True)

    def load_all(self, session_id: str) -> list[SessionPinnedUserSteer]:
        path = self._path(session_id)
        if not path.exists():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Session emphasis payload must be a JSON object")
        items = payload.get("items")
        if not isinstance(items, list):
            return []
        return [
            SessionPinnedUserSteer.from_dict(item)
            for item in items
            if isinstance(item, dict) and normalize_text(item.get("content"))
        ]

    def list_active(self, session_id: str, *, limit: int = 8) -> list[SessionPinnedUserSteer]:
        active = [item for item in self.load_all(session_id) if item.status == "active" and item.content]
        active.sort(key=lambda item: (priority_score(item.priority), item.updated_at), reverse=True)
        return active[: max(1, int(limit or 8))]

    def render_pinned_facts(self, session_id: str, *, limit: int = 8) -> list[dict[str, Any]]:
        return [item.to_pinned_fact() for item in self.list_active(session_id, limit=limit)]

    def upsert(
        self,
        *,
        session_id: str,
        emphasis_id: str,
        turn_id: str = "",
        task_environment_id: str = "",
        scope: str = "session_task",
        content: str,
        source_message_ref: str,
        priority: str = "medium",
    ) -> SessionPinnedUserSteer:
        normalized_session = normalize_session_id(session_id)
        existing = self.load_all(normalized_session)
        now = utc_now_iso()
        target_id = normalize_text(emphasis_id) or self._stable_id(content, source_message_ref)
        updated = SessionPinnedUserSteer(
            emphasis_id=target_id,
            session_id=normalized_session,
            turn_id=normalize_text(turn_id),
            task_environment_id=normalize_text(task_environment_id),
            scope=normalize_text(scope) or "session_task",
            content=normalize_text(content),
            source_message_ref=normalize_text(source_message_ref),
            priority=_coerce_priority(priority),
            status="active",
            created_at=now,
            updated_at=now,
        )
        replaced = False
        for index, item in enumerate(existing):
            if item.emphasis_id == target_id:
                updated.created_at = item.created_at
                existing[index] = updated
                replaced = True
                break
        if not replaced:
            existing.append(updated)
        self._save(normalized_session, existing)
        return updated

    def mark_status(
        self,
        *,
        session_id: str,
        emphasis_id: str,
        status: SessionEmphasisStatus,
        superseded_by: str = "",
    ) -> bool:
        normalized_session = normalize_session_id(session_id)
        target_id = normalize_text(emphasis_id)
        if not target_id:
            return False
        items = self.load_all(normalized_session)
        changed = False
        for item in items:
            if item.emphasis_id == target_id:
                item.status = status
                item.superseded_by = normalize_text(superseded_by)
                item.updated_at = utc_now_iso()
                changed = True
        if changed:
            self._save(normalized_session, items)
        return changed

    def _path(self, session_id: str) -> Path:
        session_dir = safe_session_dir(self.session_root, session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir / "session_emphasis.json"

    def _save(self, session_id: str, items: list[SessionPinnedUserSteer]) -> None:
        path = self._path(session_id)
        payload = {
            "authority": "memory_system.session_emphasis_store",
            "session_id": normalize_session_id(session_id),
            "updated_at": utc_now_iso(),
            "items": [item.to_dict() for item in items],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _stable_id(self, content: str, source_message_ref: str) -> str:
        seed = f"{normalize_text(source_message_ref)}:{normalize_text(content)}"
        normalized = "".join(ch.lower() if ch.isalnum() else "-" for ch in seed).strip("-")
        while "--" in normalized:
            normalized = normalized.replace("--", "-")
        return f"session-emphasis:{normalized[:80] or 'item'}"


@dataclass(frozen=True, slots=True)
class SessionEmphasisCaptureDecision:
    should_capture: bool
    signals: tuple[str, ...] = ()
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "should_capture": self.should_capture,
            "signals": list(self.signals),
            "reason": self.reason,
            "authority": "memory_system.session_emphasis_capture_gate",
        }


class SessionEmphasisCaptureGate:
    _SIGNAL_TERMS = (
        "请记住",
        "记住",
        "长期记忆",
        "以后",
        "始终",
        "不要再",
        "以后不要",
        "偏好",
        "纠正",
        "更正",
        "不对",
        "记忆",
        "remember",
        "preference",
        "always",
        "never",
    )

    def evaluate(self, messages: list[dict[str, Any]], *, last_index: int = 0) -> SessionEmphasisCaptureDecision:
        new_messages = list(messages or [])[max(0, int(last_index or 0)) :]
        signals: list[str] = []
        for item in new_messages:
            if str(item.get("role") or "") != "user":
                continue
            content = normalize_text(item.get("content"))
            if not content:
                continue
            lowered = content.lower()
            for term in self._SIGNAL_TERMS:
                if term.lower() in lowered:
                    signals.append(f"user_explicit:{term}")
                    break
        if signals:
            return SessionEmphasisCaptureDecision(True, tuple(dict.fromkeys(signals)), "explicit_user_emphasis")
        return SessionEmphasisCaptureDecision(False, (), "no_explicit_session_emphasis_signal")


def _coerce_priority(value: Any) -> SessionEmphasisPriority:
    normalized = str(value or "").strip().lower()
    if normalized in {"low", "medium", "high"}:
        return normalized  # type: ignore[return-value]
    return "medium"


def _coerce_status(value: Any) -> SessionEmphasisStatus:
    normalized = str(value or "").strip().lower()
    if normalized in {"active", "superseded", "resolved", "archived"}:
        return normalized  # type: ignore[return-value]
    return "active"
