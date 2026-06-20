from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


FILE_OBSERVATION_POLICY_AUTHORITY = "runtime.shared.file_observation_policy.v1"

READ_FILE_DEFAULT_START_LINE = 1
READ_FILE_DEFAULT_LINE_COUNT = 900
READ_FILE_MAX_LINE_COUNT = 2000
READ_FILE_FULL_FILE_LINE_LIMIT = 900
READ_FILE_TAIL_FULL_READ_LINE_LIMIT = 450

SEARCH_MATCH_DEFAULT_CONTEXT_LINES = 40
SEARCH_MATCH_MAX_CONTEXT_LINES = 120


@dataclass(frozen=True, slots=True)
class FileReadWindowSelection:
    start_line: int
    line_count: int
    reason: str
    requested_line_count: int | None = None
    total_lines: int | None = None
    authority: str = FILE_OBSERVATION_POLICY_AUTHORITY

    @property
    def end_line(self) -> int | None:
        if self.total_lines is None or self.total_lines < 1:
            return None
        return min(int(self.total_lines), self.start_line + self.line_count - 1)

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))


def select_read_window(
    *,
    total_lines: int | None = None,
    start_line: int | None = None,
    requested_line_count: int | None = None,
    read_intent: str = "",
) -> FileReadWindowSelection:
    total = _normalize_total_lines(total_lines)
    start = max(READ_FILE_DEFAULT_START_LINE, int(start_line or READ_FILE_DEFAULT_START_LINE))
    explicit_count = _positive_int_or_none(requested_line_count)
    if explicit_count is not None:
        return FileReadWindowSelection(
            start_line=start,
            line_count=_clamp_line_count(explicit_count),
            requested_line_count=explicit_count,
            total_lines=total,
            reason="explicit_line_count",
        )

    if total == 0:
        return FileReadWindowSelection(
            start_line=start,
            line_count=1,
            total_lines=total,
            reason="empty_file",
        )

    if total is not None and total > 0:
        remaining = max(0, total - start + 1)
        if remaining <= 0:
            return FileReadWindowSelection(
                start_line=start,
                line_count=_clamp_line_count(READ_FILE_DEFAULT_LINE_COUNT),
                total_lines=total,
                reason="start_beyond_known_file",
            )
        if start == 1 and total <= READ_FILE_FULL_FILE_LINE_LIMIT:
            return FileReadWindowSelection(
                start_line=start,
                line_count=max(1, remaining),
                total_lines=total,
                reason="small_file_full_read",
            )
        if remaining <= READ_FILE_TAIL_FULL_READ_LINE_LIMIT:
            return FileReadWindowSelection(
                start_line=start,
                line_count=max(1, remaining),
                total_lines=total,
                reason="remaining_tail_full_read",
            )

    intent = str(read_intent or "").strip()
    reason = "default_large_window"
    if intent == "edit_target":
        reason = "edit_target_default_window"
    elif intent:
        reason = f"{intent}_default_window"
    return FileReadWindowSelection(
        start_line=start,
        line_count=_clamp_line_count(READ_FILE_DEFAULT_LINE_COUNT),
        total_lines=total,
        reason=reason,
    )


def recommended_window_for_match(
    *,
    match_line: int,
    total_lines: int | None = None,
    context_lines: int | None = None,
    path: str = "",
    query: str = "",
    source_observation_ref: str = "",
) -> dict[str, Any]:
    line = int(match_line or 0)
    if line <= 0:
        return {}
    total = _normalize_total_lines(total_lines)
    context = _context_line_count(context_lines)
    if total is not None and 0 < total <= READ_FILE_FULL_FILE_LINE_LIMIT:
        start_line = 1
        line_count = total
        reason = f"small file contains match near line {line}"
    else:
        start_line = max(1, line - context)
        line_count = _clamp_line_count((context * 2) + 1)
        if total is not None and total > 0:
            line_count = max(1, min(line_count, total - start_line + 1))
        reason = f"match near line {line}"
    return _drop_empty(
        {
            "path": _normalize_path(path),
            "start_line": start_line,
            "line_count": line_count,
            "match_line": line,
            "query": str(query or "").strip(),
            "source_observation_ref": str(source_observation_ref or "").strip(),
            "reason": reason,
            "authority": FILE_OBSERVATION_POLICY_AUTHORITY,
        }
    )


def recommended_windows_for_matches(
    matches: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    context_lines: int | None = None,
    total_lines_by_path: dict[str, int] | None = None,
    query: str = "",
    source_observation_ref: str = "",
) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int, int]] = set()
    totals = {_normalize_path(path): int(value) for path, value in dict(total_lines_by_path or {}).items()}
    for item in list(matches or []):
        if not isinstance(item, dict):
            continue
        path = _normalize_path(item.get("path"))
        line = int(item.get("line") or item.get("match_line") or 0)
        if not path or line <= 0:
            continue
        window = recommended_window_for_match(
            match_line=line,
            total_lines=totals.get(path),
            context_lines=context_lines,
            path=path,
            query=query,
            source_observation_ref=source_observation_ref,
        )
        if not window:
            continue
        key = (path, int(window["start_line"]), int(window["line_count"]), line)
        if key in seen:
            continue
        seen.add(key)
        windows.append(window)
    return windows


def recommended_window_for_gap(
    *,
    start_line: int,
    end_line: int | None = None,
    total_lines: int | None = None,
    reason: str = "fill first unread gap",
) -> dict[str, Any]:
    start = max(1, int(start_line or 1))
    total = _normalize_total_lines(total_lines)
    end = _positive_int_or_none(end_line)
    if total is not None and total > 0:
        end = min(end or total, total)
    if end is not None and end >= start:
        line_count = max(1, min(_clamp_line_count(end - start + 1), READ_FILE_DEFAULT_LINE_COUNT))
    else:
        line_count = _clamp_line_count(READ_FILE_DEFAULT_LINE_COUNT)
        if total is not None and total > 0:
            line_count = max(1, min(line_count, total - start + 1))
    return _drop_empty(
        {
            "start_line": start,
            "line_count": line_count,
            "end_line": end,
            "reason": str(reason or "fill first unread gap"),
            "authority": FILE_OBSERVATION_POLICY_AUTHORITY,
        }
    )


def recommended_window_for_continuation(
    *,
    next_start_line: int,
    total_lines: int | None = None,
    previous_line_count: int | None = None,
    reason: str = "continue from latest read window",
) -> dict[str, Any]:
    start = max(1, int(next_start_line or 1))
    total = _normalize_total_lines(total_lines)
    count = _positive_int_or_none(previous_line_count) or READ_FILE_DEFAULT_LINE_COUNT
    count = _clamp_line_count(count)
    if total is not None and total > 0:
        remaining = max(1, total - start + 1)
        count = min(count, remaining)
    return _drop_empty(
        {
            "start_line": start,
            "line_count": count,
            "reason": str(reason or "continue from latest read window"),
            "authority": FILE_OBSERVATION_POLICY_AUTHORITY,
        }
    )


def read_window_fingerprint_defaults() -> dict[str, int]:
    return {
        "start_line": READ_FILE_DEFAULT_START_LINE,
        "line_count": READ_FILE_DEFAULT_LINE_COUNT,
    }


def _context_line_count(value: int | None) -> int:
    parsed = int(value or 0)
    if parsed <= 0:
        return SEARCH_MATCH_DEFAULT_CONTEXT_LINES
    return max(0, min(parsed, SEARCH_MATCH_MAX_CONTEXT_LINES))


def _clamp_line_count(value: int) -> int:
    return max(1, min(int(value or 1), READ_FILE_MAX_LINE_COUNT))


def _normalize_total_lines(value: int | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, parsed)


def _positive_int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _normalize_path(value: Any) -> str:
    return str(value or "").replace("\\", "/").strip().strip("/")


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {}, ())}
