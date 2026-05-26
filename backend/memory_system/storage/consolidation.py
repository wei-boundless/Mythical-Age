from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
import hashlib
import threading
import time
from typing import Callable

from .memory_manager import MemoryManager


@dataclass(slots=True)
class DuplicateCandidate:
    reason: str
    value: str
    filenames: list[str]


@dataclass(slots=True)
class MergeCandidate:
    reason: str
    primary_filename: str
    merge_filenames: list[str]
    rationale: str


@dataclass(slots=True)
class ConsolidationReport:
    status: str
    note_count: int
    index_entries: int
    class_counts: dict[str, int]
    type_counts: dict[str, int]
    duplicate_candidates: list[DuplicateCandidate] = field(default_factory=list)
    merge_candidates: list[MergeCandidate] = field(default_factory=list)
    empty_body_candidates: list[str] = field(default_factory=list)
    repair_payload: dict[str, object] = field(default_factory=dict)
    durable_memory_dir: str = ""
    report_id: str = ""

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["duplicate_candidates"] = [
            asdict(candidate) for candidate in self.duplicate_candidates
        ]
        payload["merge_candidates"] = [
            asdict(candidate) for candidate in self.merge_candidates
        ]
        return payload


@dataclass(slots=True)
class ConsolidationConfig:
    min_saved_notes_between_runs: int = 3
    min_seconds_between_runs: int = 1800


class DurableMemoryConsolidator:
    """Rule-based consolidation for durable memory.

    Phase 1 goals:
    - normalize all notes through MemoryManager.repair_store()
    - identify likely duplicate candidates
    - identify suspicious/empty notes
    - rebuild a clean MEMORY.md via MemoryManager
    - return a report without destructive auto-pruning
    """

    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)
        self.manager = MemoryManager(self.root_dir)

    def run(self) -> ConsolidationReport:
        self.manager._migrate_flat_layout()
        repair_payload = self.manager.repair_store()
        notes = self.manager.load_relevant_notes(limit=10_000)

        class_counts = Counter(note.memory_class for note in notes)
        type_counts = Counter(note.memory_type for note in notes)
        duplicate_candidates = self._find_duplicate_candidates(notes)
        merge_candidates = self._build_merge_candidates(notes, duplicate_candidates)
        empty_body_candidates = sorted(
            note.filename
            for note in notes
            if not (note.content or "").strip()
        )

        report_id = self._build_report_id(notes)
        return ConsolidationReport(
            status="ok",
            note_count=len(notes),
            index_entries=len(self.manager.list_index_entries()),
            class_counts=dict(class_counts),
            type_counts=dict(type_counts),
            duplicate_candidates=duplicate_candidates,
            merge_candidates=merge_candidates,
            empty_body_candidates=empty_body_candidates,
            repair_payload=repair_payload,
            durable_memory_dir=str(self.root_dir),
            report_id=report_id,
        )

    def _find_duplicate_candidates(self, notes: list[object]) -> list[DuplicateCandidate]:
        candidates: list[DuplicateCandidate] = []

        by_title: dict[str, list[str]] = defaultdict(list)
        by_summary: dict[str, list[str]] = defaultdict(list)
        by_body_fingerprint: dict[str, list[str]] = defaultdict(list)

        for note in notes:
            title_key = self._normalize_key(getattr(note, "title", ""))
            summary_key = self._normalize_key(getattr(note, "summary", ""))
            content_key = self._normalize_key(getattr(note, "content", ""))

            if title_key:
                by_title[title_key].append(getattr(note, "filename", ""))
            if summary_key:
                by_summary[summary_key].append(getattr(note, "filename", ""))
            if content_key:
                body_hash = hashlib.sha1(content_key.encode("utf-8")).hexdigest()[:12]
                by_body_fingerprint[body_hash].append(getattr(note, "filename", ""))

        for reason, mapping in (
            ("same_title", by_title),
            ("same_summary", by_summary),
            ("same_body", by_body_fingerprint),
        ):
            for value, filenames in mapping.items():
                unique_filenames = sorted({name for name in filenames if name})
                if len(unique_filenames) < 2:
                    continue
                candidates.append(
                    DuplicateCandidate(
                        reason=reason,
                        value=value,
                        filenames=unique_filenames,
                    )
                )

        candidates.sort(key=lambda item: (item.reason, item.value, item.filenames))
        return candidates

    def _build_merge_candidates(
        self,
        notes: list[object],
        duplicate_candidates: list[DuplicateCandidate],
    ) -> list[MergeCandidate]:
        note_map = {
            getattr(note, "filename", ""): note
            for note in notes
            if getattr(note, "filename", "")
        }
        merge_candidates: list[MergeCandidate] = []
        seen_groups: set[tuple[str, ...]] = set()

        for duplicate in duplicate_candidates:
            filenames = sorted({name for name in duplicate.filenames if name in note_map})
            if len(filenames) < 2:
                continue
            group_key = tuple(filenames)
            if group_key in seen_groups:
                continue
            seen_groups.add(group_key)

            primary_filename = self._select_primary_filename(
                [note_map[name] for name in filenames]
            )
            merge_filenames = [name for name in filenames if name != primary_filename]
            if not merge_filenames:
                continue

            rationale = self._build_merge_rationale(
                duplicate.reason,
                primary_filename,
                merge_filenames,
                note_map,
            )
            merge_candidates.append(
                MergeCandidate(
                    reason=duplicate.reason,
                    primary_filename=primary_filename,
                    merge_filenames=merge_filenames,
                    rationale=rationale,
                )
            )

        merge_candidates.sort(
            key=lambda item: (item.reason, item.primary_filename, item.merge_filenames)
        )
        return merge_candidates

    def _select_primary_filename(self, notes: list[object]) -> str:
        ranked = sorted(
            notes,
            key=lambda note: (
                -self._note_richness_score(note),
                -(1 if getattr(note, "updated_at", "") else 0),
                getattr(note, "updated_at", ""),
                getattr(note, "filename", ""),
            ),
        )
        return getattr(ranked[0], "filename", "")

    def _note_richness_score(self, note: object) -> int:
        content = getattr(note, "content", "") or ""
        summary = getattr(note, "summary", "") or ""
        title = getattr(note, "title", "") or ""
        return len(content.strip()) + len(summary.strip()) * 2 + len(title.strip())

    def _build_merge_rationale(
        self,
        reason: str,
        primary_filename: str,
        merge_filenames: list[str],
        note_map: dict[str, object],
    ) -> str:
        primary = note_map[primary_filename]
        parts: list[str] = []

        if reason == "same_title":
            parts.append("标题相同，主题高度重合。")
        elif reason == "same_summary":
            parts.append("摘要相同，信息很可能重复。")
        elif reason == "same_body":
            parts.append("正文内容相同，属于重复记录。")
        else:
            parts.append("内容高度重合。")

        if getattr(primary, "updated_at", ""):
            parts.append(f"建议保留 {primary_filename}，因为它带有更新时间且内容更完整。")
        else:
            parts.append(f"建议保留 {primary_filename}，因为它的内容更完整。")

        merge_titles = [
            getattr(note_map[name], "title", name)
            for name in merge_filenames
            if name in note_map
        ]
        if merge_titles:
            parts.append(f"候选并入主题：{' / '.join(merge_titles)}。")

        return " ".join(parts)

    def _normalize_key(self, value: str) -> str:
        normalized = " ".join((value or "").strip().lower().split())
        return normalized

    def _build_report_id(self, notes: list[object]) -> str:
        joined = "|".join(sorted(getattr(note, "filename", "") for note in notes))
        if not joined:
            return "empty"
        return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:12]


class ConsolidationScheduler:
    """Lightweight background scheduler for durable memory consolidation."""

    def __init__(
        self,
        root_dir: str | Path,
        config: ConsolidationConfig | None = None,
        on_completed: Callable[[ConsolidationReport], None] | None = None,
    ) -> None:
        self.root_dir = Path(root_dir)
        self.config = config or ConsolidationConfig()
        self.on_completed = on_completed
        self._lock = threading.Lock()
        self._saved_since_run = 0
        self._last_run_at = 0.0
        self._in_progress = False
        self._last_report: ConsolidationReport | None = None

    def notify_saved(self, saved_count: int) -> bool:
        if saved_count <= 0:
            return False

        with self._lock:
            self._saved_since_run += saved_count
            if self._in_progress:
                return False
            if self._saved_since_run < self.config.min_saved_notes_between_runs:
                return False
            now = time.time()
            if (now - self._last_run_at) < self.config.min_seconds_between_runs:
                return False
            self._in_progress = True
            self._saved_since_run = 0

        threading.Thread(
            target=self._run_background,
            name="durable-memory-consolidation",
            daemon=True,
        ).start()
        return True

    def last_report(self) -> ConsolidationReport | None:
        with self._lock:
            return self._last_report

    def _run_background(self) -> None:
        report: ConsolidationReport | None = None
        try:
            report = DurableMemoryConsolidator(self.root_dir).run()
            if self.on_completed is not None:
                self.on_completed(report)
        finally:
            with self._lock:
                self._in_progress = False
                self._last_run_at = time.time()
                self._last_report = report
