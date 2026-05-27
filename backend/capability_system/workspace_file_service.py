from __future__ import annotations

import os
import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from project_layout import ProjectLayout


DEFAULT_SEARCH_ROOTS: tuple[str, ...] = ("docs", "backend", "frontend", "knowledge")
DEFAULT_EXCLUDED_DIRS: tuple[str, ...] = (
    ".git",
    ".pytest_cache",
    ".tmp-tests-runtime",
    "__pycache__",
    "node_modules",
    "output",
)
DEFAULT_SEARCH_EXCLUDED_PATHS: tuple[str, ...] = ("backend/knowledge",)
TEXT_ENCODINGS: tuple[str, ...] = ("utf-8", "utf-8-sig", "gb18030", "gbk")


@dataclass(frozen=True, slots=True)
class WorkspacePathInfo:
    path: Path
    relative_path: str
    exists: bool
    is_dir: bool
    is_file: bool
    size_bytes: int
    suffix: str


class WorkspaceFileService:
    """Shared workspace file boundary for local file tools and safety validators."""

    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.workspace_root = ProjectLayout.from_backend_dir(self.root_dir).project_root.resolve()

    def resolve(self, path: str = ".", *, require_path: bool = False) -> Path:
        raw = str(path or "").strip()
        if require_path and not raw:
            raise ValueError("Path is required.")
        normalized = raw or "."
        if normalized.startswith("\\\\") or normalized.startswith("//"):
            raise ValueError("Path traversal detected.")
        if "://" in normalized:
            raise ValueError("Path uses URL syntax.")
        candidate = Path(normalized)
        resolved = candidate.resolve() if candidate.is_absolute() else (self.workspace_root / candidate).resolve()
        if not self._is_inside_workspace(resolved):
            raise ValueError("Path traversal detected.")
        return resolved

    def relative_path(self, path: str | Path) -> str:
        resolved = Path(path).resolve()
        try:
            return resolved.relative_to(self.workspace_root).as_posix()
        except ValueError:
            return str(resolved)

    def read_text(self, path: str | Path, *, limit: int | None = None) -> str:
        file_path = self.resolve(str(path), require_path=True) if not isinstance(path, Path) else path.resolve()
        for encoding in TEXT_ENCODINGS:
            try:
                content = file_path.read_text(encoding=encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        if limit is None:
            return content
        return content[: max(0, int(limit))]

    def write_text(self, path: str, content: str) -> Path:
        file_path = self.resolve(path, require_path=True)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(str(content or ""), encoding="utf-8")
        return file_path

    def edit_text(self, path: str, old_text: str, new_text: str) -> Path:
        file_path = self.resolve(path, require_path=True)
        if not file_path.exists():
            raise FileNotFoundError("file does not exist")
        if file_path.is_dir():
            raise IsADirectoryError("path is a directory")
        content = self.read_text(file_path)
        target = str(old_text or "")
        if not target:
            raise ValueError("old_text is required")
        if target not in content:
            raise LookupError("old_text not found")
        file_path.write_text(content.replace(target, str(new_text or ""), 1), encoding="utf-8")
        return file_path

    def list_dir(self, path: str = ".") -> list[Path]:
        directory = self.resolve(path)
        if not directory.exists():
            raise FileNotFoundError("directory does not exist")
        if not directory.is_dir():
            raise NotADirectoryError("path is not a directory")
        return sorted(directory.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))

    def path_info(self, path: str) -> WorkspacePathInfo:
        target = self.resolve(path, require_path=True)
        exists = target.exists()
        stat = target.stat() if exists else None
        return WorkspacePathInfo(
            path=target,
            relative_path=self.relative_path(target),
            exists=exists,
            is_dir=target.is_dir() if exists else False,
            is_file=target.is_file() if exists else False,
            size_bytes=stat.st_size if stat is not None else 0,
            suffix=target.suffix.lower(),
        )

    def exists(self, path: str) -> bool:
        return self.resolve(path, require_path=True).exists()

    def safe_roots(
        self,
        roots: Iterable[str] | None,
        *,
        defaults: Iterable[str] = DEFAULT_SEARCH_ROOTS,
        fallback_to_workspace: bool = True,
    ) -> list[Path]:
        requested = [str(item or "").strip().replace("\\", "/") for item in list(roots or [])]
        using_defaults = not requested
        if using_defaults:
            requested = list(defaults)
        safe: list[Path] = []
        seen: set[Path] = set()
        for item in requested:
            if not item or item.startswith("-"):
                continue
            try:
                candidate = self.resolve(item)
            except ValueError:
                continue
            if not candidate.exists() or candidate in seen:
                continue
            seen.add(candidate)
            safe.append(candidate)
        if safe or not fallback_to_workspace or not using_defaults:
            return safe
        return [self.workspace_root]

    def glob_paths(self, pattern: str, *, max_results: int = 80) -> list[str]:
        normalized = str(pattern or "").replace("\\", "/").strip()
        if not normalized or normalized.startswith("/") or ".." in Path(normalized).parts:
            raise ValueError("invalid pattern")
        limit = max(1, min(int(max_results or 80), 300))
        matches: list[str] = []
        for directory, dirnames, filenames in os.walk(self.workspace_root):
            dirnames[:] = [
                dirname
                for dirname in dirnames
                if not self.is_excluded(Path(directory) / dirname)
            ]
            candidates = [
                Path(directory) / dirname
                for dirname in dirnames
            ] + [
                Path(directory) / filename
                for filename in filenames
            ]
            for candidate in candidates:
                rel = self.relative_path(candidate)
                if _glob_matches(rel, normalized):
                    matches.append(rel)
                    if len(matches) >= limit:
                        return sorted(dict.fromkeys(matches))
        return sorted(dict.fromkeys(matches))[:limit]

    def is_excluded(self, path: Path, *, include_default_search_excludes: bool = False) -> bool:
        parts = {part.lower() for part in path.parts}
        if any(excluded.lower() in parts for excluded in DEFAULT_EXCLUDED_DIRS):
            return True
        if include_default_search_excludes:
            relative = self.relative_path(path).lower()
            for excluded in DEFAULT_SEARCH_EXCLUDED_PATHS:
                if relative == excluded or relative.startswith(f"{excluded}/"):
                    return True
        return False

    def _is_inside_workspace(self, path: Path) -> bool:
        return path == self.workspace_root or self.workspace_root in path.parents


def _glob_matches(relative_path: str, pattern: str) -> bool:
    variants = {pattern}
    if "**/" in pattern:
        variants.add(pattern.replace("**/", ""))
    if "/**/" in pattern:
        variants.add(pattern.replace("/**/", "/"))
    return any(fnmatch.fnmatch(relative_path, variant) for variant in variants)


