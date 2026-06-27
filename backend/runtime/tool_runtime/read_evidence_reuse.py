from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from runtime.memory.file_evidence_scope import normalize_file_evidence_scope
from runtime.memory.file_state_authority import FileReadRange, TaskFileState
from runtime.memory.file_state_store import FileStateAuthorityStore
from runtime.shared.file_observation_policy import select_read_window


READ_EVIDENCE_REUSE_AUTHORITY = "runtime.tool_runtime.read_evidence_reuse.v1"


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
    authority: str = READ_EVIDENCE_REUSE_AUTHORITY

    @property
    def should_reuse(self) -> bool:
        return self.decision == "reuse_unchanged"

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))

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
                    "This observation does not show new file text; call read_file again only for a different "
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


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {}, ())}
