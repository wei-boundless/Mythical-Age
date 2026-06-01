from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from capability_system.tools.workspace_file_service import WorkspaceFileService
from .providers import TextHit


@dataclass(frozen=True, slots=True)
class FileSlice:
    file: str
    start_line: int
    end_line: int
    matched_line: int
    snippet: str


class FileSlicer:
    def __init__(self, root_dir: Path) -> None:
        self.files = WorkspaceFileService(root_dir)

    def slices_for_hits(self, hits: list[TextHit], *, max_slices: int, max_slice_lines: int) -> list[FileSlice]:
        slices: list[FileSlice] = []
        seen: set[tuple[str, int]] = set()
        for hit in hits:
            if len(slices) >= max_slices:
                break
            key = (hit.file, hit.line)
            if key in seen:
                continue
            seen.add(key)
            item = self.slice_file(hit.file, matched_line=hit.line, max_slice_lines=max_slice_lines)
            if item is not None:
                slices.append(item)
        return slices

    def slice_file(self, path: str, *, matched_line: int, max_slice_lines: int) -> FileSlice | None:
        try:
            file_path = self.files.resolve(path, require_path=True)
        except ValueError:
            return None
        if not file_path.exists() or file_path.is_dir() or self.files.is_excluded(file_path):
            return None
        text = self.files.read_text(file_path, limit=400_000)
        lines = text.splitlines()
        if not lines:
            return None
        line_index = max(0, min(int(matched_line or 1) - 1, len(lines) - 1))
        half_window = max(5, int(max_slice_lines or 120) // 2)
        start = max(0, line_index - half_window)
        end = min(len(lines), line_index + half_window + 1)
        if file_path.suffix.lower() in {".py", ".ts", ".tsx", ".js", ".jsx"}:
            start = _expand_to_symbol_start(lines, line_index, fallback=start)
        if end - start > max_slice_lines:
            end = min(len(lines), start + max_slice_lines)
        numbered = [f"{index + 1}: {line}" for index, line in enumerate(lines[start:end], start=start)]
        return FileSlice(
            file=self.files.relative_path(file_path),
            start_line=start + 1,
            end_line=end,
            matched_line=line_index + 1,
            snippet="\n".join(numbered)[:12000],
        )


def _expand_to_symbol_start(lines: list[str], line_index: int, *, fallback: int) -> int:
    for index in range(line_index, max(-1, line_index - 80), -1):
        if index < 0:
            break
        if re.match(r"^\s*(class|def|async def|function|export\s+(class|function|const|interface)|interface)\b", lines[index]):
            return index
    return fallback


