from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any


READ_FILE_WINDOW_AUTHORITY = "runtime.tool_result.read_file_window.v1"
READ_FILE_DEFAULT_LINE_COUNT = 240
READ_FILE_MAX_LINE_COUNT = 2000


@dataclass(frozen=True, slots=True)
class ReadFileWindowResult:
    path: str
    text: str
    total_lines: int
    start_line: int
    line_count: int
    returned_lines: int
    end_line: int
    next_start_line: int | None
    has_more: bool
    truncated: bool
    content_sha256: str
    status: str = "ok"
    kind: str = "text_file"
    repository_id: str = ""
    managed_file_ref: dict[str, Any] | None = None
    error: str = ""
    authority: str = READ_FILE_WINDOW_AUTHORITY

    def to_dict(self, *, include_text: bool = True) -> dict[str, Any]:
        payload = asdict(self)
        if not include_text:
            payload.pop("text", None)
        if payload.get("managed_file_ref") is None:
            payload.pop("managed_file_ref", None)
        return _drop_empty(payload)


def build_read_file_window_result(
    content: str,
    *,
    path: str,
    start_line: int,
    line_count: int,
    repository_id: str = "",
    managed_file_ref: dict[str, Any] | None = None,
) -> ReadFileWindowResult:
    lines = str(content or "").splitlines()
    total_lines = len(lines)
    start = max(1, int(start_line or 1))
    count = max(1, min(int(line_count or READ_FILE_DEFAULT_LINE_COUNT), READ_FILE_MAX_LINE_COUNT))
    if total_lines == 0:
        end_line = 0
        selected: list[str] = []
    elif start > total_lines:
        raise ValueError(f"start_line {start} exceeds total_lines {total_lines}")
    else:
        end_line = min(total_lines, start + count - 1)
        selected = lines[start - 1 : end_line]
    width = max(1, len(str(max(end_line, start, total_lines))))
    text = "\n".join(f"{line_no:>{width}} | {line}" for line_no, line in enumerate(selected, start=start))
    has_more = bool(total_lines and end_line < total_lines)
    return ReadFileWindowResult(
        path=str(path or "").strip(),
        repository_id=str(repository_id or "").strip(),
        managed_file_ref=dict(managed_file_ref or {}) or None,
        text=text,
        total_lines=total_lines,
        start_line=start,
        line_count=count,
        returned_lines=len(selected),
        end_line=end_line,
        next_start_line=end_line + 1 if has_more else None,
        has_more=has_more,
        truncated=has_more,
        content_sha256=hashlib.sha256(str(content or "").encode("utf-8", errors="replace")).hexdigest(),
    )


def build_read_file_error_result(
    *,
    path: str,
    error: str,
    repository_id: str = "",
) -> dict[str, Any]:
    return _drop_empty(
        {
            "authority": READ_FILE_WINDOW_AUTHORITY,
            "kind": "text_file",
            "status": "error",
            "path": str(path or "").strip(),
            "repository_id": str(repository_id or "").strip(),
            "error": str(error or "").strip(),
        }
    )


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {})}
