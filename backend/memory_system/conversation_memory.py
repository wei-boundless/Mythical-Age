from __future__ import annotations

from pathlib import Path
from typing import Any

from structured_memory.session_memory import SessionMemoryManager
from structured_memory.text_utils import normalize_storage_text

from .contracts import ConversationMemorySnapshot, MemoryContextCandidate, MemoryWriteCandidate


CONVERSATION_SECTION_HEADERS: tuple[str, ...] = (
    "# Key User Requests",
    "# Errors and Corrections",
    "# Decisions and Learnings",
    "# Key Results",
    "# Worklog",
)


class ConversationMemoryStoreAdapter:
    """Read-only adapter over existing session summary/compaction views."""

    def __init__(self, session_root: str | Path) -> None:
        self.session_root = Path(session_root)
        self.session_root.mkdir(parents=True, exist_ok=True)

    def manager(self, session_id: str) -> SessionMemoryManager:
        root = self.session_root.resolve()
        target = (root / _safe_session_id(session_id)).resolve()
        if target == root or root not in target.parents:
            raise ValueError("Invalid session_id")
        return SessionMemoryManager(target)

    def load_snapshot(self, session_id: str) -> ConversationMemorySnapshot:
        safe_session_id = _safe_session_id(session_id)
        manager = self.manager(safe_session_id)
        summary = _read_existing(manager.summary_path) or manager.load()
        compaction_view = manager.compact_view()
        sections = manager.parse_sections(summary)

        key_requests = tuple(_section_items(sections, "# Key User Requests"))
        key_results = tuple(_section_items(sections, "# Key Results"))
        worklog = tuple(_section_items(sections, "# Worklog"))
        errors = tuple(_section_items(sections, "# Errors and Corrections"))
        decisions = tuple(_section_items(sections, "# Decisions and Learnings"))

        hot_truth_window = _take_nonempty([*key_results, *decisions, *errors], limit=6)
        recent_dialogue_refs = _take_nonempty([*key_requests, *worklog], limit=8)

        return ConversationMemorySnapshot(
            session_id=safe_session_id,
            recent_dialogue_refs=recent_dialogue_refs,
            hot_truth_window=hot_truth_window,
            compact_summary_ref=str(manager.compaction_view_path if manager.compaction_view_path.exists() else manager.summary_path),
            key_results=key_results[:6],
            worklog=worklog[:8],
            last_updated_at=_latest_mtime_iso([manager.summary_path, manager.agent_view_path, manager.compaction_view_path]),
            extraction_trigger="session_summary_adapter",
        )

    def context_candidates(self, session_id: str) -> tuple[MemoryContextCandidate, ...]:
        safe_session_id = _safe_session_id(session_id)
        manager = self.manager(safe_session_id)
        summary = _read_existing(manager.summary_path) or manager.load()
        sections = manager.parse_sections(summary)
        rendered_preview = self._render_conversation_preview(sections)
        if not rendered_preview:
            return ()
        snapshot = self.load_snapshot(safe_session_id)
        return (
            MemoryContextCandidate(
                candidate_id=f"memory-context:{safe_session_id}:conversation:summary",
                memory_layer="conversation",
                source="structured_memory.session_summary",
                content_ref=snapshot.compact_summary_ref,
                rendered_preview=rendered_preview,
                relevance=0.72,
                confidence=0.66,
                staleness="session_scoped",
                token_estimate=max(1, len(rendered_preview) // 4),
                budget_class="preferred",
                requires_verification_before_use=False,
                metadata={
                    "recent_dialogue_ref_count": len(snapshot.recent_dialogue_refs),
                    "hot_truth_count": len(snapshot.hot_truth_window),
                    "last_updated_at": snapshot.last_updated_at,
                },
            ),
        )

    def propose_summary_update_candidate(
        self,
        *,
        session_id: str,
        content: str,
        source_event_refs: tuple[str, ...] = (),
    ) -> MemoryWriteCandidate | None:
        rendered = normalize_storage_text(content).strip()
        if not rendered:
            return None
        safe_session_id = _safe_session_id(session_id)
        return MemoryWriteCandidate(
            candidate_id=f"memory-write:{safe_session_id}:conversation:summary",
            target_layer="conversation",
            write_kind="update_summary",
            content=rendered,
            source_event_refs=source_event_refs,
            stability="session_scoped",
            gate_decision="pending",
            gate_reason="session_memory_write_requires_memory_gate",
            risk_flags=("session_memory_preview", "no_auto_commit"),
            metadata={
                "session_id": safe_session_id,
                "target": "session_summary",
            },
        )

    def _render_conversation_preview(self, sections: dict[str, list[str]]) -> str:
        chunks: list[str] = []
        for header in CONVERSATION_SECTION_HEADERS:
            items = _section_items(sections, header)
            if not items:
                continue
            chunks.append(header)
            chunks.extend(f"- {item}" for item in items[:6])
            chunks.append("")
        return "\n".join(chunks).strip()


def _safe_session_id(session_id: str) -> str:
    value = str(session_id or "").strip()
    return value or "default"


def _read_existing(path: Path) -> str:
    if not path.exists():
        return ""
    return normalize_storage_text(path.read_text(encoding="utf-8")).strip()


def _section_items(sections: dict[str, list[str]], header: str) -> tuple[str, ...]:
    items: list[str] = []
    for line in sections.get(header, []) or []:
        item = str(line or "").strip()
        if not item:
            continue
        if item.startswith("_") and item.endswith("_"):
            continue
        if item.startswith("- "):
            item = item[2:].strip()
        if item:
            items.append(item)
    return tuple(items)


def _take_nonempty(values: list[str], *, limit: int) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
        if len(result) >= limit:
            break
    return tuple(result)


def _latest_mtime_iso(paths: list[Path]) -> str:
    mtimes = [path.stat().st_mtime for path in paths if path.exists()]
    if not mtimes:
        return ""
    from datetime import datetime, timezone

    return datetime.fromtimestamp(max(mtimes), tz=timezone.utc).isoformat()
