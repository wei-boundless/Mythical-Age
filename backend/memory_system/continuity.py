from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from context_system import ContextController
from context_system.budget.presets import get_context_budget_preset
from project_layout import ProjectLayout
from response_system.boundary.boundary import sanitize_visible_assistant_content

from .paths import normalize_session_id, safe_session_dir
from .storage.models import Message, utc_now_iso
from .storage.session_memory import SessionMemoryManager
from .storage.text_utils import normalize_storage_text


class MemoryMessageAdapter:
    CONTROL_PLANE_MARKERS = (
        "Runtime Stage Projection",
        "Runtime Context Package",
        "OperationGate",
        "ResourcePolicy",
        "ResourceRuntimeView",
        "当前投影",
        "任务契约",
        "资源边界",
        "护栏",
        "共同契约",
        "身份锚点",
    )
    CONTROL_PLANE_INLINE_MARKERS = (
        "runtime_view_only",
        "runtime_executable=false",
        "runtime_executable: false",
        "authorization_owner=ResourcePolicy",
    )

    def looks_like_skill_document(self, content: str) -> bool:
        normalized = content.strip()
        if not normalized:
            return False
        lowered = normalized.lower()
        if "/skills/" in lowered and "/skill.md" in lowered:
            return True
        has_skill_frontmatter = (
            (normalized.startswith("---") or lowered.startswith("name:"))
            and "metadata:" in lowered
            and "description:" in lowered
        )
        heading_hits = sum(
            1
            for marker in (
                "## execution steps",
                "## lessons learned",
                "## troubleshooting",
                "## output format",
                "目标",
                "执行步骤",
                "输出格式",
                "故障排查",
                "查询策略",
            )
            if marker in normalized or marker in lowered
        )
        if has_skill_frontmatter and heading_hits >= 1:
            return True
        if "display_name:" in lowered and heading_hits >= 1:
            return True
        return False

    def looks_like_control_plane_contract(self, content: str) -> bool:
        normalized = str(content or "").strip()
        if not normalized:
            return False
        lowered = normalized.lower()
        if any(marker.lower() in lowered for marker in self.CONTROL_PLANE_INLINE_MARKERS):
            return True
        marker_hits = sum(1 for marker in self.CONTROL_PLANE_MARKERS if marker.lower() in lowered)
        if marker_hits >= 2:
            return True
        if "# 当前风格" in normalized and "# 共同契约" in normalized:
            return True
        if "## Runtime Stage Projection" in normalized or "## Runtime Context Package" in normalized:
            return True
        return False

    def sanitize_memory_content(self, role: str, content: str) -> str:
        if role in {"assistant", "tool"}:
            content = sanitize_visible_assistant_content(content)
        if self.looks_like_control_plane_contract(content):
            return ""
        return content.strip()

    def should_skip_message(self, role: str, content: str, item: dict[str, Any] | None = None) -> bool:
        if role == "system":
            return True
        if self.looks_like_control_plane_contract(content):
            return True
        if role == "tool":
            return self.looks_like_skill_document(content)
        if role == "assistant":
            canonical_state = str((item or {}).get("answer_canonical_state", "") or "").strip()
            if canonical_state and canonical_state not in {"stable_answer", "tool_summary"}:
                return True
        if role == "assistant" and self.looks_like_skill_document(content):
            return True
        return False

    def to_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        session_id: str | None = None,
    ) -> list[Message]:
        converted: list[Message] = []
        for item in messages:
            role = str(item.get("role", "") or "")
            if role not in {"system", "user", "assistant", "tool"}:
                continue
            content = str(item.get("content", "") or "")
            content = self.sanitize_memory_content(role, content)
            if self.should_skip_message(role, content, item):
                continue
            if not content.strip():
                continue
            meta = dict(item.get("meta", {}) or {})
            for key in (
                "answer_channel",
                "answer_source",
                "answer_canonical_state",
                "answer_persist_policy",
                "answer_finalization_policy",
                "answer_fallback_reason",
            ):
                value = item.get(key)
                if value is None:
                    continue
                normalized = str(value or "").strip()
                if normalized:
                    meta[key] = normalized
            if session_id:
                meta["session_id"] = session_id
            converted.append(Message(role=role, content=content, meta=meta))
        return converted


class SessionMemoryLayer:
    def __init__(self, base_dir: Path, context_budget_provider: Callable[[], dict[str, Any]] | None = None) -> None:
        self.base_dir = base_dir
        self._context_budget_provider = context_budget_provider
        self.session_root = ProjectLayout.from_backend_dir(base_dir).session_memory_dir
        self.session_root.mkdir(parents=True, exist_ok=True)

    def session_dir(self, session_id: str) -> Path:
        return safe_session_dir(self.session_root, session_id)

    def delete_session(self, session_id: str) -> bool:
        normalized = str(session_id or "").strip()
        if not normalized:
            return False

        target = safe_session_dir(self.session_root, normalized)
        if not target.exists():
            return True
        if not target.is_dir():
            raise ValueError("Session memory path is not a directory")
        shutil.rmtree(target)
        return True

    def manager(self, session_id: str) -> SessionMemoryManager:
        return SessionMemoryManager(self.session_dir(session_id))

    def compactor(self, session_id: str):
        from context_system import ContextCompactor

        budget = self._context_budget()
        return ContextCompactor(
            self.manager(session_id),
            effective_history_token_budget=int(budget["available_context_tokens"]),
        )

    def context_controller(self, session_id: str) -> ContextController:
        budget = self._context_budget()
        return ContextController(
            self.manager(session_id),
            reserved_output_tokens=int(budget["reserved_output_tokens"]),
            effective_history_token_budget=int(budget["available_context_tokens"]),
        )

    def refresh(self, session_id: str, messages: list[Message]) -> str:
        return self.manager(session_id).load()

    def refresh_from_context_state(
        self,
        session_id: str,
        main_context: Any,
        *,
        task_summaries: list[Any] | None = None,
        bundle_summaries: list[Any] | None = None,
        corrections: list[str] | None = None,
    ) -> str:
        self.update_runtime_state_from_context_state(
            session_id,
            main_context,
            task_summaries=task_summaries,
            bundle_summaries=bundle_summaries,
            corrections=corrections,
        )
        return self.manager(session_id).load()

    def update_runtime_state_from_context_state(
        self,
        session_id: str,
        main_context: Any,
        *,
        task_summaries: list[Any] | None = None,
        bundle_summaries: list[Any] | None = None,
        corrections: list[str] | None = None,
    ):
        return self.manager(session_id).update_runtime_state_from_context_state(
            main_context,
            task_summaries=task_summaries,
            bundle_summaries=bundle_summaries,
            corrections=corrections,
        )

    def _context_budget(self) -> dict[str, Any]:
        if self._context_budget_provider is not None:
            payload = dict(self._context_budget_provider())
            if not payload:
                raise ValueError("context budget provider returned an empty payload")
            return payload
        return get_context_budget_preset("deepseek_1m").to_dict()


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
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Foreground continuity state payload must be a JSON object")
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


