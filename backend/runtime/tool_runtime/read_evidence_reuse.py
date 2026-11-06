from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from runtime.memory.file_evidence_scope import normalize_file_evidence_scope
from runtime.memory.file_state_authority import FileReadRange, TaskFileState
from runtime.memory.file_state_store import FileStateAuthorityStore
from runtime.shared.file_observation_policy import select_read_window


READ_EVIDENCE_REUSE_AUTHORITY = "runtime.tool_runtime.read_evidence_reuse"


@dataclass(frozen=True, slots=True)
class ReadFileCurrentFacts:
    path: str
    content_sha256: str = ""
    mtime_ns: int | None = None
    size_bytes: int | None = None
    repository_id: str = ""
    exists: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))


@dataclass(frozen=True, slots=True)
class ReadEvidenceReuseDecision:
    decision: str
    reason: str
    path: str
    start_line: int
    line_count: int
    end_line: int
    read_intent: str = ""
    total_lines: int | None = None
    source_start_line: int | None = None
    source_end_line: int | None = None
    reused_observation_ref: str = ""
    reusable_result_ref: str = ""
    exact_artifact_ref: str = ""
    artifact_ref_status: str = ""
    visible_exact: bool = False
    content_sha256: str = ""
    mtime_ns: int | None = None
    text_sha256: str = ""
    next_start_line: int | None = None
    has_more: bool | None = None
    repository_id: str = ""
    coverage: ReadWindowCoverage | None = None
    authority: str = READ_EVIDENCE_REUSE_AUTHORITY

    @property
    def should_reuse(self) -> bool:
        return self.decision == "reuse_unchanged"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("coverage", None)
        if self.coverage is not None:
            payload["coverage"] = self.coverage.to_dict()
        return _drop_empty(payload)

    def to_tool_result(self) -> dict[str, Any]:
        return _drop_empty(
            {
                "kind": "read_file_reuse",
                "status": self.decision,
                "reason": self.reason,
                "path": self.path,
                "repository_id": self.repository_id,
                "start_line": self.start_line,
                "line_count": self.line_count,
                "returned_lines": max(0, self.end_line - self.start_line + 1) if self.end_line >= self.start_line else 0,
                "end_line": self.end_line,
                "total_lines": self.total_lines,
                "source_start_line": self.source_start_line,
                "source_end_line": self.source_end_line,
                "reused_observation_ref": self.reused_observation_ref,
                "observation_ref": self.reused_observation_ref,
                "reusable_result_ref": self.reusable_result_ref,
                "exact_artifact_ref": self.exact_artifact_ref,
                "artifact_ref_status": self.artifact_ref_status,
                "visible_exact": self.visible_exact,
                "content_sha256": self.content_sha256,
                "mtime_ns": self.mtime_ns,
                "text_sha256": self.text_sha256,
                "next_start_line": self.next_start_line,
                "has_more": self.has_more,
                "read_intent": self.read_intent,
                "semantic_delta": self.to_semantic_delta(),
                "authority": self.authority,
            }
        )

    def to_semantic_delta(self) -> dict[str, Any]:
        return _drop_empty(
            {
                "subject": "file_window_evidence",
                "change_state": "unchanged",
                "path": self.path,
                "requested_range": _drop_empty(
                    {
                        "start_line": self.start_line,
                        "end_line": self.end_line,
                        "line_count": self.line_count,
                    }
                ),
                "valid_prior_evidence": _drop_empty(
                    {
                        "observation_ref": self.reused_observation_ref,
                        "exact_artifact_ref": self.exact_artifact_ref,
                        "reusable_result_ref": self.reusable_result_ref,
                        "content_sha256": self.content_sha256,
                        "mtime_ns": self.mtime_ns,
                    }
                ),
                "current_observation": {
                    "confirms_prior_evidence_is_current": True,
                    "includes_file_text": False,
                },
                "agent_guidance": (
                    "Use the prior exact read evidence for this file range as still current. "
                    "This observation does not show new file text; call workspace_read(action=file) again only for a different "
                    "range, changed file state, or when exact text must be rehydrated."
                ),
            }
        )

    def to_visible_text(self) -> str:
        location = f"{self.path}:{self.start_line}-{self.end_line}" if self.end_line >= self.start_line else f"{self.path}:empty"
        refs: list[str] = []
        if self.reused_observation_ref:
            refs.append(f"observation_ref={self.reused_observation_ref}")
        if self.exact_artifact_ref:
            refs.append(f"exact_artifact_ref={self.exact_artifact_ref}")
        if self.reusable_result_ref:
            refs.append(f"reusable_result_ref={self.reusable_result_ref}")
        suffix = "; ".join(refs)
        return (
            f"The requested file window is unchanged from prior exact read evidence: {location}. "
            f"Use the prior evidence reference for content reasoning. This observation confirms freshness "
            f"and does not repeat the file text."
            + (f" {suffix}." if suffix else "")
        )


def allow_read_file_decision(
    *,
    path: str,
    start_line: int,
    line_count: int | None,
    read_intent: str = "",
    reason: str,
) -> ReadEvidenceReuseDecision:
    selection = select_read_window(
        total_lines=None,
        start_line=start_line,
        requested_line_count=line_count,
        read_intent=read_intent,
    )
    return ReadEvidenceReuseDecision(
        decision="allow_read",
        reason=str(reason or "read_required"),
        path=_normalize_path(path),
        start_line=selection.start_line,
        line_count=selection.line_count,
        end_line=selection.start_line + selection.line_count - 1,
        read_intent=str(read_intent or "").strip(),
    )


def decide_read_evidence_reuse(
    *,
    file_evidence_scope: dict[str, Any] | None,
    storage_roots: tuple[Path, ...] | list[Path],
    path: str,
    start_line: int,
    line_count: int | None,
    read_intent: str = "",
    current_facts: ReadFileCurrentFacts | None = None,
    repository_id: str = "",
) -> ReadEvidenceReuseDecision:
    normalized_path = _normalize_path(path)
    if not normalized_path:
        return allow_read_file_decision(
            path=path,
            start_line=start_line,
            line_count=line_count,
            read_intent=read_intent,
            reason="missing_path",
        )
    if current_facts is not None and current_facts.exists is False:
        return allow_read_file_decision(
            path=normalized_path,
            start_line=start_line,
            line_count=line_count,
            read_intent=read_intent,
            reason="current_file_missing",
        )
    scope = normalize_file_evidence_scope(file_evidence_scope)
    if not scope:
        return allow_read_file_decision(
            path=normalized_path,
            start_line=start_line,
            line_count=line_count,
            read_intent=read_intent,
            reason="missing_file_evidence_scope",
        )
    roots = tuple(Path(item) for item in list(storage_roots or []) if str(item or "").strip())
    if not roots:
        return allow_read_file_decision(
            path=normalized_path,
            start_line=start_line,
            line_count=line_count,
            read_intent=read_intent,
            reason="missing_file_state_store",
        )
    file_state = _load_best_file_state(
        scope=scope,
        storage_roots=roots,
        path=normalized_path,
        current_facts=current_facts,
    )
    if file_state is None:
        return allow_read_file_decision(
            path=normalized_path,
            start_line=start_line,
            line_count=line_count,
            read_intent=read_intent,
            reason="no_prior_file_state",
        )
    status = str(file_state.status or "").strip().lower()
    if status in {"", "unread", "stale", "changed", "missing"}:
        return _allow_from_state(
            path=normalized_path,
            start_line=start_line,
            line_count=line_count,
            read_intent=read_intent,
            file_state=file_state,
            reason=f"file_state_{status or 'unread'}",
        )
    if not _file_state_matches_current_facts(file_state=file_state, current_facts=current_facts):
        return _allow_from_state(
            path=normalized_path,
            start_line=start_line,
            line_count=line_count,
            read_intent=read_intent,
            file_state=file_state,
            reason="file_freshness_changed",
        )
    if file_state.read_ranges and all(item.stale for item in file_state.read_ranges):
        # Stale evidence means "do not assert from this window", not "do not
        # read again". Refusing the read here would leave the agent with no way
        # to recover a fresh window, which is a harmless failure the runtime
        # must not create.
        return _allow_from_state(
            path=normalized_path,
            start_line=start_line,
            line_count=line_count,
            read_intent=read_intent,
            file_state=file_state,
            reason="all_read_ranges_stale",
        )
    selection = select_read_window(
        total_lines=file_state.total_lines,
        start_line=start_line,
        requested_line_count=line_count,
        read_intent=read_intent,
    )
    if file_state.total_lines is not None and file_state.total_lines > 0 and selection.start_line > file_state.total_lines:
        return _allow_from_state(
            path=normalized_path,
            start_line=start_line,
            line_count=line_count,
            read_intent=read_intent,
            file_state=file_state,
            reason="start_beyond_known_file",
        )
    requested_start = int(selection.start_line)
    requested_end = _requested_end_line(selection_start=requested_start, line_count=selection.line_count, total_lines=file_state.total_lines)
    segment = _best_covering_exact_segment(
        tuple(file_state.read_ranges or ()),
        start_line=requested_start,
        end_line=requested_end,
        total_lines=file_state.total_lines,
        current_facts=current_facts,
    )
    if segment is None:
        return ReadEvidenceReuseDecision(
            decision="allow_read",
            reason="missing_exact_covering_read_window",
            path=normalized_path,
            start_line=requested_start,
            line_count=selection.line_count,
            end_line=requested_end,
            read_intent=str(read_intent or "").strip(),
            total_lines=file_state.total_lines,
            repository_id=str(repository_id or getattr(current_facts, "repository_id", "") or ""),
            coverage=compute_read_window_coverage(
                ranges=tuple(file_state.read_ranges or ()),
                path=normalized_path,
                start_line=requested_start,
                end_line=requested_end,
                current_facts=current_facts,
                total_lines=file_state.total_lines,
            ),
        )

    return ReadEvidenceReuseDecision(
        decision="reuse_unchanged",
        reason="exact_read_window_unchanged",
        path=normalized_path,
        start_line=requested_start,
        line_count=selection.line_count,
        end_line=requested_end,
        read_intent=str(read_intent or "").strip(),
        total_lines=file_state.total_lines,
        source_start_line=segment.start_line,
        source_end_line=segment.end_line,
        reused_observation_ref=segment.observation_ref,
        reusable_result_ref=segment.reusable_result_ref,
        exact_artifact_ref=segment.exact_artifact_ref,
        artifact_ref_status=segment.artifact_ref_status,
        visible_exact=bool(segment.visible_exact),
        content_sha256=segment.content_sha256 or file_state.content_sha256,
        mtime_ns=segment.mtime_ns if segment.mtime_ns is not None else file_state.mtime_ns,
        text_sha256=segment.text_sha256,
        next_start_line=segment.next_start_line,
        has_more=segment.has_more,
        repository_id=str(repository_id or getattr(current_facts, "repository_id", "") or ""),
        coverage=compute_read_window_coverage(
            ranges=tuple(file_state.read_ranges or ()),
            path=normalized_path,
            start_line=requested_start,
            end_line=requested_end,
            current_facts=current_facts,
            total_lines=file_state.total_lines,
        ),
    )


def _allow_from_state(
    *,
    path: str,
    start_line: int,
    line_count: int | None,
    read_intent: str,
    file_state: TaskFileState,
    reason: str,
) -> ReadEvidenceReuseDecision:
    selection = select_read_window(
        total_lines=file_state.total_lines,
        start_line=start_line,
        requested_line_count=line_count,
        read_intent=read_intent,
    )
    return ReadEvidenceReuseDecision(
        decision="allow_read",
        reason=reason,
        path=path,
        start_line=selection.start_line,
        line_count=selection.line_count,
        end_line=_requested_end_line(
            selection_start=selection.start_line,
            line_count=selection.line_count,
            total_lines=file_state.total_lines,
        ),
        read_intent=str(read_intent or "").strip(),
        total_lines=file_state.total_lines,
    )


def _load_best_file_state(
    *,
    scope: dict[str, Any],
    storage_roots: tuple[Path, ...],
    path: str,
    current_facts: ReadFileCurrentFacts | None,
) -> TaskFileState | None:
    first: TaskFileState | None = None
    normalized = _normalize_path(path)
    for root in storage_roots:
        try:
            authority = FileStateAuthorityStore(root).load_scope(scope)
        except Exception:
            continue
        for item in authority.files:
            if _normalize_path(item.path) != normalized:
                continue
            if first is None:
                first = item
            if _file_state_matches_current_facts(file_state=item, current_facts=current_facts):
                return item
    return first


def _file_state_matches_current_facts(
    *,
    file_state: TaskFileState,
    current_facts: ReadFileCurrentFacts | None,
) -> bool:
    if current_facts is None:
        return True
    if current_facts.exists is False:
        return False
    state_hash = str(file_state.content_sha256 or "").strip()
    fact_hash = str(current_facts.content_sha256 or "").strip()
    if fact_hash:
        return bool(state_hash and state_hash == fact_hash)
    fact_mtime = current_facts.mtime_ns
    if fact_mtime is not None:
        state_mtime = file_state.mtime_ns
        return state_mtime is not None and int(state_mtime) == int(fact_mtime)
    return True


def _best_covering_exact_segment(
    ranges: tuple[FileReadRange, ...],
    *,
    start_line: int,
    end_line: int,
    total_lines: int | None,
    current_facts: ReadFileCurrentFacts | None,
) -> FileReadRange | None:
    candidates = [
        item
        for item in ranges
        if _segment_covers_window(item, start_line=start_line, end_line=end_line, total_lines=total_lines)
        and _segment_has_exact_recovery(item)
        and _segment_matches_current_facts(item, current_facts=current_facts)
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (max(0, item.end_line - item.start_line), item.start_line, item.end_line))[0]


def _segment_covers_window(
    segment: FileReadRange,
    *,
    start_line: int,
    end_line: int,
    total_lines: int | None,
) -> bool:
    if segment.stale is True:
        return False
    if total_lines == 0 and start_line == 1 and end_line == 0:
        return segment.start_line == 1 and segment.end_line == 0
    if start_line < 1 or end_line < start_line:
        return False
    return segment.start_line <= start_line and segment.end_line >= end_line


def _segment_has_exact_recovery(segment: FileReadRange) -> bool:
    exact_ref = str(segment.exact_artifact_ref or "").strip()
    artifact_status = str(segment.artifact_ref_status or "").strip()
    return bool(segment.visible_exact or (exact_ref and artifact_status == "exact"))


def _segment_matches_current_facts(
    segment: FileReadRange,
    *,
    current_facts: ReadFileCurrentFacts | None,
) -> bool:
    if current_facts is None:
        return True
    fact_hash = str(current_facts.content_sha256 or "").strip()
    if fact_hash:
        return bool(segment.content_sha256 and segment.content_sha256 == fact_hash)
    fact_mtime = current_facts.mtime_ns
    if fact_mtime is not None:
        return segment.mtime_ns is not None and int(segment.mtime_ns) == int(fact_mtime)
    return True


def _requested_end_line(*, selection_start: int, line_count: int, total_lines: int | None) -> int:
    if total_lines == 0:
        return 0
    end_line = int(selection_start) + max(1, int(line_count or 1)) - 1
    if total_lines is not None and total_lines > 0:
        return min(int(total_lines), end_line)
    return end_line


def _normalize_path(path: Any) -> str:
    return str(path or "").replace("\\", "/").strip().strip("/")


@dataclass(frozen=True, slots=True)
class ReadWindowCoverageSegment:
    start_line: int
    end_line: int
    source: FileReadRange | None = None

    @property
    def line_count(self) -> int:
        if self.end_line < self.start_line:
            return 0
        return self.end_line - self.start_line + 1

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "start_line": self.start_line,
            "end_line": self.end_line,
            "line_count": self.line_count,
        }
        if self.source is not None:
            payload.update(
                _drop_empty(
                    {
                        "observation_ref": str(self.source.observation_ref or ""),
                        "exact_artifact_ref": str(self.source.exact_artifact_ref or ""),
                        "artifact_ref_status": str(self.source.artifact_ref_status or ""),
                        "visible_exact": bool(self.source.visible_exact),
                        "text_sha256": str(self.source.text_sha256 or ""),
                        "content_sha256": str(self.source.content_sha256 or ""),
                        "read_intent": str(self.source.read_intent or ""),
                    }
                )
            )
        return payload


@dataclass(frozen=True, slots=True)
class ReadWindowCoverage:
    """Split a requested window into already-read parts and new parts.

    Reading must stay a continuous forward motion. The reader protocol returns
    only the gap text and references the covered parts, so previously read
    windows are not repeated into the model context.
    """

    path: str
    requested_start_line: int
    requested_end_line: int
    covered_segments: tuple[ReadWindowCoverageSegment, ...] = ()
    gap_segments: tuple[ReadWindowCoverageSegment, ...] = ()
    file_total_lines: int | None = None
    file_read_ranges: tuple[tuple[int, int], ...] = ()
    file_unread_ranges: tuple[tuple[int, int], ...] = ()
    authority: str = READ_EVIDENCE_REUSE_AUTHORITY

    @property
    def requested_line_count(self) -> int:
        if self.requested_end_line < self.requested_start_line:
            return 0
        return self.requested_end_line - self.requested_start_line + 1

    @property
    def covered_line_count(self) -> int:
        return sum(item.line_count for item in self.covered_segments)

    @property
    def gap_line_count(self) -> int:
        return sum(item.line_count for item in self.gap_segments)

    @property
    def fully_covered(self) -> bool:
        return bool(self.requested_line_count) and not self.gap_segments

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(
            {
                "path": self.path,
                "requested_range": _drop_empty(
                    {
                        "start_line": self.requested_start_line,
                        "end_line": self.requested_end_line,
                        "line_count": self.requested_line_count,
                    }
                ),
                "requested_fully_covered": self.fully_covered,
                "covered_line_count": self.covered_line_count,
                "gap_line_count": self.gap_line_count,
                "file_progress": _drop_empty(
                    {
                        "total_lines": self.file_total_lines,
                        "read_ranges": [list(item) for item in self.file_read_ranges],
                        "unread_ranges": [list(item) for item in self.file_unread_ranges],
                    }
                ),
                "covered_segments": [item.to_dict() for item in self.covered_segments],
                "gap_segments": [item.to_dict() for item in self.gap_segments],
                "authority": self.authority,
            }
        )


def compute_read_window_coverage(
    *,
    ranges: tuple[FileReadRange, ...] | list[FileReadRange],
    path: str,
    start_line: int,
    end_line: int,
    current_facts: ReadFileCurrentFacts | None = None,
    total_lines: int | None = None,
) -> ReadWindowCoverage:
    requested_start = int(start_line or 0)
    requested_end = int(end_line or 0)
    normalized_path = _normalize_path(path)
    if requested_start < 1 or requested_end < requested_start:
        return ReadWindowCoverage(
            path=normalized_path,
            requested_start_line=max(1, requested_start),
            requested_end_line=max(1, requested_end),
        )
    overlaps: list[tuple[int, int, FileReadRange]] = []
    for item in tuple(ranges or ()):
        if item.stale is True:
            continue
        if not _segment_has_exact_recovery(item):
            continue
        if not _segment_matches_current_facts(item, current_facts=current_facts):
            continue
        overlap_start = max(requested_start, int(item.start_line))
        overlap_end = min(requested_end, int(item.end_line))
        if overlap_end < overlap_start:
            continue
        overlaps.append((overlap_start, overlap_end, item))
    covered: list[ReadWindowCoverageSegment] = []
    for overlap_start, overlap_end, item in sorted(overlaps, key=lambda entry: (entry[0], entry[1])):
        if covered and overlap_start <= covered[-1].end_line + 1:
            last = covered[-1]
            covered[-1] = ReadWindowCoverageSegment(
                start_line=last.start_line,
                end_line=max(last.end_line, overlap_end),
                source=last.source,
            )
            continue
        covered.append(
            ReadWindowCoverageSegment(start_line=overlap_start, end_line=overlap_end, source=item)
        )
    gaps: list[ReadWindowCoverageSegment] = []
    cursor = requested_start
    for segment in covered:
        if segment.start_line > cursor:
            gaps.append(ReadWindowCoverageSegment(start_line=cursor, end_line=segment.start_line - 1))
        cursor = max(cursor, segment.end_line + 1)
    if cursor <= requested_end:
        gaps.append(ReadWindowCoverageSegment(start_line=cursor, end_line=requested_end))
    file_read_ranges: list[tuple[int, int]] = []
    file_unread_ranges: list[tuple[int, int]] = []
    normalized_total = int(total_lines) if total_lines is not None else 0
    if normalized_total > 0:
        merged: list[tuple[int, int]] = []
        for raw_start, raw_end in sorted(
            (
                max(1, int(item.start_line)),
                min(normalized_total, int(item.end_line)),
            )
            for item in tuple(ranges or ())
            if item.stale is not True
            and _segment_has_exact_recovery(item)
            and _segment_matches_current_facts(item, current_facts=current_facts)
            and int(item.start_line) <= normalized_total
            and int(item.end_line) >= 1
        ):
            if raw_end < raw_start:
                continue
            if merged and raw_start <= merged[-1][1] + 1:
                merged[-1] = (merged[-1][0], max(merged[-1][1], raw_end))
                continue
            merged.append((raw_start, raw_end))
        file_read_ranges = merged
        cursor = 1
        for raw_start, raw_end in merged:
            if raw_start > cursor:
                file_unread_ranges.append((cursor, raw_start - 1))
            cursor = max(cursor, raw_end + 1)
        if cursor <= normalized_total:
            file_unread_ranges.append((cursor, normalized_total))
    return ReadWindowCoverage(
        path=normalized_path,
        requested_start_line=requested_start,
        requested_end_line=requested_end,
        covered_segments=tuple(covered),
        gap_segments=tuple(gaps),
        file_total_lines=normalized_total or None,
        file_read_ranges=tuple(file_read_ranges),
        file_unread_ranges=tuple(file_unread_ranges),
    )


def load_read_window_coverage(
    *,
    file_evidence_scope: dict[str, Any] | None,
    storage_roots: tuple[Path, ...] | list[Path],
    path: str,
    start_line: int,
    end_line: int,
    current_facts: ReadFileCurrentFacts | None = None,
) -> ReadWindowCoverage | None:
    """Load the stored read ranges for a path and split the window by coverage.

    Returns None when the file state cannot be resolved, so the caller keeps
    its previous behaviour instead of silently reading everything again.
    """
    scope = normalize_file_evidence_scope(file_evidence_scope)
    if not scope:
        return None
    roots = tuple(Path(item) for item in list(storage_roots or []) if str(item or "").strip())
    if not roots:
        return None
    file_state = _load_best_file_state(
        scope=scope,
        storage_roots=roots,
        path=_normalize_path(path),
        current_facts=current_facts,
    )
    if file_state is None:
        return None
    return compute_read_window_coverage(
        ranges=file_state.read_ranges,
        path=path,
        start_line=start_line,
        end_line=end_line,
        current_facts=current_facts,
        total_lines=file_state.total_lines,
    )


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {}, ())}
