from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from memory_system.storage.models import utc_now_iso
from memory_system.storage.text_utils import normalize_storage_text

from .paths import normalize_session_id, safe_session_dir


@dataclass(frozen=True, slots=True)
class ForegroundContinuityState:
    session_id: str
    updated_at: str
    turn_id: str = ""
    active_goal: str = ""
    active_bindings: dict[str, Any] = field(default_factory=dict)
    latest_result_refs: tuple[str, ...] = ()
    bundle_result_refs: tuple[dict[str, Any], ...] = ()
    corrections: tuple[str, ...] = ()
    next_step: tuple[str, ...] = ()
    source: str = "foreground_commit_projection"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["latest_result_refs"] = list(self.latest_result_refs)
        payload["bundle_result_refs"] = [dict(item) for item in self.bundle_result_refs]
        payload["corrections"] = list(self.corrections)
        payload["next_step"] = list(self.next_step)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ForegroundContinuityState":
        return cls(
            session_id=normalize_session_id(payload.get("session_id")),
            updated_at=str(payload.get("updated_at") or ""),
            turn_id=str(payload.get("turn_id") or ""),
            active_goal=str(payload.get("active_goal") or ""),
            active_bindings=dict(payload.get("active_bindings") or {}),
            latest_result_refs=tuple(_strings(payload.get("latest_result_refs"))),
            bundle_result_refs=tuple(
                dict(item)
                for item in list(payload.get("bundle_result_refs") or [])
                if isinstance(item, dict)
            ),
            corrections=tuple(_strings(payload.get("corrections"))),
            next_step=tuple(_strings(payload.get("next_step"))),
            source=str(payload.get("source") or "foreground_commit_projection"),
        )


class ForegroundContinuityStateStore:
    def __init__(self, session_root: str | Path) -> None:
        self.session_root = Path(session_root)
        self.session_root.mkdir(parents=True, exist_ok=True)

    def state_path(self, session_id: str) -> Path:
        return safe_session_dir(self.session_root, session_id) / "foreground_state.json"

    def load(self, session_id: str) -> ForegroundContinuityState | None:
        path = self.state_path(session_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        return ForegroundContinuityState.from_dict(payload)

    def save(self, state: ForegroundContinuityState) -> ForegroundContinuityState:
        path = self.state_path(state.session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return state

    def project_from_commit(
        self,
        *,
        session_id: str,
        turn_id: str = "",
        main_context: dict[str, Any] | None = None,
        task_summary_refs: list[dict[str, Any]] | None = None,
        bundle_summary_refs: list[dict[str, Any]] | None = None,
        corrections: list[str] | tuple[str, ...] = (),
        next_step: list[str] | tuple[str, ...] = (),
    ) -> ForegroundContinuityState:
        context = dict(main_context or {})
        task_refs = [dict(item) for item in list(task_summary_refs or []) if isinstance(item, dict)]
        bundle_refs = [dict(item) for item in list(bundle_summary_refs or []) if isinstance(item, dict)]
        active_goal = _clean(
            context.get("active_goal")
            or next((item.get("query") for item in task_refs if _clean(item.get("query"))), "")
            or "继续当前任务"
        )
        latest_result_refs = _dedupe(
            [
                *[_clean(item.get("answer") or item.get("summary") or item.get("response")) for item in task_refs],
                *[_clean(item.get("summary") or item.get("answer")) for item in bundle_refs],
            ],
            limit=8,
        )
        active_bindings = {
            key: value
            for key, value in {
                "active_pdf": context.get("active_pdf") or context.get("explicit_pdf_path"),
                "active_dataset": context.get("active_dataset") or context.get("explicit_dataset_path"),
                "active_binding_identity": context.get("active_binding_identity"),
                "active_object_handle_id": context.get("active_object_handle_id"),
                "active_result_handle_id": context.get("active_result_handle_id"),
                "active_subset_handle_id": context.get("active_subset_handle_id"),
                "followup_binding_owner_task_id": context.get("followup_binding_owner_task_id"),
            }.items()
            if value not in ("", None, [], {})
        }
        return self.save(
            ForegroundContinuityState(
                session_id=normalize_session_id(session_id),
                updated_at=utc_now_iso(),
                turn_id=str(turn_id or ""),
                active_goal=active_goal,
                active_bindings=active_bindings,
                latest_result_refs=tuple(latest_result_refs),
                bundle_result_refs=tuple(bundle_refs[:8]),
                corrections=tuple(_dedupe(_strings(corrections), limit=8)),
                next_step=tuple(_dedupe(_strings(next_step), limit=8)),
            )
        )


def _strings(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value if _clean(item)]
    text = _clean(value)
    return [text] if text else []


def _clean(value: Any) -> str:
    return normalize_storage_text(str(value or "")).strip()


def _dedupe(values: list[str], *, limit: int) -> list[str]:
    result: list[str] = []
    for value in values:
        item = _clean(value)
        if item and item not in result:
            result.append(item)
        if len(result) >= limit:
            break
    return result
