from __future__ import annotations

import re
from typing import Any, Callable

from understanding import analyze_memory_intent, evaluate_memory_write

from .contracts import MemoryWriteCandidate


SessionHistoryLoader = Callable[[str], list[dict[str, Any]]]


class MemoryWritebackPreviewService:
    """Adapter for preview-only memory writeback flows.

    QueryRuntime should not decide how memory writes are built or committed. It
    may pass projections/messages into this service and receive blocked gate
    previews or user-visible candidate acknowledgements.
    """

    def __init__(self, memory_facade: Any, *, session_history_loader: SessionHistoryLoader | None = None) -> None:
        self.memory_facade = memory_facade
        self.session_history_loader = session_history_loader

    def preview_session_projection(self, session_id: str, projection: dict[str, Any] | None):
        if not projection:
            return self._gate(session_id, ())
        builder = getattr(self.memory_facade, "build_session_memory_write_candidates_from_context_state", None)
        if not callable(builder):
            return self._gate(session_id, ())
        candidates = builder(
            session_id,
            projection.get("main_context"),
            task_summaries=list(projection.get("task_summary_refs", []) or []),
            corrections=list(projection.get("corrections", []) or []),
        )
        return self._gate(session_id, tuple(candidates or ()))

    def preview_durable_message(self, session_id: str, message: str):
        builder = getattr(self.memory_facade, "build_durable_memory_write_candidates", None)
        if not callable(builder):
            return self._gate(session_id, ())
        candidates = builder(session_id, [{"role": "user", "content": str(message or "")}])
        return self._gate(session_id, tuple(candidates or ()))

    def preview_durable_projections(self, session_id: str, projections: list[dict[str, Any]]):
        candidates: list[MemoryWriteCandidate] = []
        builder = getattr(self.memory_facade, "build_durable_memory_write_candidates_from_context_state", None)
        if callable(builder):
            for projection in list(projections or []):
                candidates.extend(
                    builder(
                        session_id,
                        projection.get("main_context"),
                        task_summaries=list(projection.get("task_summary_refs", []) or []),
                        corrections=list(projection.get("corrections", []) or []),
                    )
                )
        return self._gate(session_id, tuple(candidates))

    def preview_durable_history(self, session_id: str):
        if self.session_history_loader is None:
            return self._gate(session_id, ())
        builder = getattr(self.memory_facade, "build_durable_memory_write_candidates", None)
        if not callable(builder):
            return self._gate(session_id, ())
        history = self.session_history_loader(session_id)
        candidates = builder(session_id, history)
        return self._gate(session_id, tuple(candidates or ()))

    def has_explicit_durable_projection(self, projections: list[dict[str, Any]]) -> bool:
        for projection in list(projections or []):
            main_context = projection.get("main_context")
            if isinstance(main_context, dict):
                active_goal = str(main_context.get("active_goal", "") or "").strip()
            else:
                active_goal = str(getattr(main_context, "active_goal", "") or "").strip()
            intent = analyze_memory_intent(active_goal)
            if str(getattr(intent, "intent", "") or "") == "durable_memory_statement":
                return True
        return False

    def build_acknowledgement(self, message: str) -> str:
        normalized = normalize_memory_write_statement(message)
        decision = evaluate_memory_write(message)
        if decision.action == "durable_fact":
            if normalized:
                return f"好，这条已作为长期记忆候选进入写回审核：{normalized}"
            return "好，这条已作为长期记忆候选进入写回审核。"
        if decision.action == "session_only":
            if normalized:
                return f"这条会作为当前会话记忆候选处理，不直接写入长期记忆：{normalized}"
            return "这条会作为当前会话记忆候选处理，不直接写入长期记忆。"
        if normalized:
            return f"这条我不会写入长期记忆；它更适合作为当前会话约定或静态设定处理：{normalized}"
        return "这条我不会写入长期记忆；它更适合作为当前会话约定或静态设定处理。"

    def _gate(self, session_id: str, candidates: tuple[MemoryWriteCandidate, ...]):
        builder = getattr(self.memory_facade, "build_memory_gate_preview", None)
        if not callable(builder):
            return None
        return builder(
            candidates,
            gate_id=f"memory-gate:{session_id or 'session'}:writeback-preview",
            reason="query_runtime_writeback_preview_only",
        )


def normalize_memory_write_statement(message: str) -> str:
    normalized = _sanitize_visible_text(str(message or "")).strip()
    if not normalized:
        return ""
    return re.sub(
        r"^(?:记住|记一下|别忘了|记到长期记忆|remember that|remember|don't forget)\s*[:：,，-]*\s*",
        "",
        normalized,
        count=1,
        flags=re.IGNORECASE,
    ).strip()


def _sanitize_visible_text(text: str) -> str:
    # Keep MemorySystem independent from OutputBoundary while preserving
    # the local need: strip empty/control-only text before candidate rendering.
    return "".join(char for char in str(text or "") if char == "\n" or char == "\t" or ord(char) >= 32).strip()
