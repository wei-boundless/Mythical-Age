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
    ".codex",
    ".codex-run-logs",
    ".codex_runtime_logs",
    ".cache",
    ".next",
    ".playwright-cli",
    ".pytest_cache",
    ".runtime",
    ".tmp",
    ".turbo",
    ".tmp-tests-runtime",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "logs",
    "node_modules",
    "output",
    "runtime_logs",
    "venv",
)
DEFAULT_SEARCH_EXCLUDED_PATHS: tuple[str, ...] = (
    "backend/knowledge",
    "output",
    "storage/runtime_cache",
    "storage/runtime_state/sandboxes",
)
DEFAULT_RUNTIME_PRIVATE_PATHS: tuple[str, ...] = (
    "mythical-agent/sessions/**",
    "backend/mythical-agent/sessions/**",
    "storage/sessions/**",
    "storage/session_environments/**",
    "storage/runtime_context/**",
    "storage/runtime_state/**",
    "runtime_context/tool_results/**",
    "runtime_state/dynamic_context/replacements/**",
    "runtime_state/tool_results/**",
    "dynamic_context/replacements/replacement_*.json",
    "backend/storage/session_environments/**",
    "backend/storage/runtime_context/**",
    "backend/storage/runtime_state/**",
    "**/runtime_state/dynamic_context/replacements/**",
    "**/runtime_state/tool_results/**",
    "**/runtime_context/tool_results/**",
    "**/dynamic_context/replacements/replacement_*.json",
)
RUNTIME_PRIVATE_PATH_ERROR = "Runtime private path is not accessible through workspace file tools."
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
        self.layout = ProjectLayout.from_backend_dir(self.root_dir)
        self.workspace_root = self.layout.project_root.resolve()
        self._logical_roots = {
            "knowledge": self.layout.knowledge_storage_dir.resolve(),
        }

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
        logical_target = self._resolve_logical_root(normalized)
        resolved = (
            candidate.resolve()
            if candidate.is_absolute()
            else logical_target
            if logical_target is not None
            else (self.workspace_root / candidate).resolve()
        )
        if not self._is_inside_allowed_root(resolved):
            raise ValueError("Path traversal detected.")
        self.assert_public_workspace_path(resolved)
        return resolved

    def relative_path(self, path: str | Path) -> str:
        resolved = Path(path).resolve()
        for prefix, root in self._logical_roots.items():
            try:
                return f"{prefix}/{resolved.relative_to(root).as_posix()}".rstrip("/")
            except ValueError:
                continue
        try:
            return resolved.relative_to(self.workspace_root).as_posix()
        except ValueError:
            return str(resolved)

    def read_text(self, path: str | Path, *, limit: int | None = None) -> str:
        file_path = self.resolve(str(path), require_path=True) if not isinstance(path, Path) else path.resolve()
        self.assert_public_workspace_path(file_path)
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

    def write_text(self, path: str, content: str, *, allow_overwrite: bool = False, expected_previous_sha256: str = "") -> Path:
        file_path = self.resolve(path, require_path=True)
        if file_path.exists() and not bool(allow_overwrite):
            raise FileExistsError("file already exists; pass allow_overwrite=true to replace it")
        expected_hash = str(expected_previous_sha256 or "").strip().lower()
        if file_path.exists() and expected_hash and _file_sha256(file_path) != expected_hash:
            raise ValueError("expected_previous_sha256 does not match current file")
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
        return sorted(
            (item for item in directory.iterdir() if not self.is_runtime_private_path(item)),
            key=lambda item: (not item.is_dir(), item.name.lower()),
        )

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
        include_default_excludes = not _targets_default_excluded_path(normalized)
        matches: list[str] = []
        for walk_root in self._glob_walk_roots(normalized):
            for directory, dirnames, filenames in os.walk(walk_root):
                dirnames[:] = [
                    dirname
                    for dirname in dirnames
                    if not self.is_excluded(Path(directory) / dirname, include_default_search_excludes=include_default_excludes)
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

    def _glob_walk_roots(self, normalized_pattern: str) -> list[Path]:
        fixed_prefix = _fixed_glob_prefix(normalized_pattern)
        if fixed_prefix:
            try:
                fixed_target = self.resolve(fixed_prefix)
            except ValueError:
                return []
            if fixed_target.is_file():
                return [fixed_target.parent]
            if fixed_target.is_dir():
                return [fixed_target]
            return []
        head = normalized_pattern.split("/", 1)[0]
        logical_root = self._logical_roots.get(head)
        if logical_root is not None:
            return [logical_root] if logical_root.exists() else []
        roots = [self.workspace_root]
        for root in self._logical_roots.values():
            if root.exists() and not (root == self.workspace_root or self.workspace_root in root.parents):
                roots.append(root)
        return roots

    def iter_files(self, root: Path) -> list[Path]:
        found: list[Path] = []
        for path in root.rglob("*"):
            if path.is_file() and not self.is_excluded(path, include_default_search_excludes=True):
                found.append(path)
        return found

    def is_external_root(self, root: Path) -> bool:
        resolved = root.resolve()
        return not (resolved == self.workspace_root or self.workspace_root in resolved.parents)

    def search_root_args_are_workspace_relative(self, roots: Iterable[Path]) -> bool:
        return not any(self.is_external_root(root) for root in roots)

    def is_excluded(self, path: Path, *, include_default_search_excludes: bool = False) -> bool:
        if self.is_runtime_private_path(path):
            return True
        parts = {part.lower() for part in path.parts}
        if any(excluded.lower() in parts for excluded in DEFAULT_EXCLUDED_DIRS):
            return True
        if include_default_search_excludes:
            relative = self.relative_path(path).lower()
            for excluded in DEFAULT_SEARCH_EXCLUDED_PATHS:
                if relative == excluded or relative.startswith(f"{excluded}/"):
                    return True
        return False

    def is_runtime_private_path(self, path: str | Path) -> bool:
        relative = self.relative_path(path).replace("\\", "/").strip("/").lower()
        if not relative:
            return False
        for pattern in DEFAULT_RUNTIME_PRIVATE_PATHS:
            if _runtime_private_pattern_matches(relative, pattern):
                return True
        return False

    def assert_public_workspace_path(self, path: str | Path) -> None:
        if self.is_runtime_private_path(path):
            raise ValueError(RUNTIME_PRIVATE_PATH_ERROR)

    def _resolve_logical_root(self, normalized_path: str) -> Path | None:
        normalized = normalized_path.replace("\\", "/").strip("/")
        if not normalized:
            return None
        head, _, tail = normalized.partition("/")
        root = self._logical_roots.get(head)
        if root is None:
            return None
        return (root / tail).resolve() if tail else root

    def _is_inside_allowed_root(self, path: Path) -> bool:
        if path == self.workspace_root or self.workspace_root in path.parents:
            return True
        return any(path == root or root in path.parents for root in self._logical_roots.values())


def _glob_matches(relative_path: str, pattern: str) -> bool:
    variants = {pattern}
    if "**/" in pattern:
        variants.add(pattern.replace("**/", ""))
    if "/**/" in pattern:
        variants.add(pattern.replace("/**/", "/"))
    return any(fnmatch.fnmatch(relative_path, variant) for variant in variants)


def _runtime_private_pattern_matches(relative_path: str, pattern: str) -> bool:
    normalized = str(pattern or "").replace("\\", "/").strip("/").lower()
    if not normalized:
        return False
    if normalized.endswith("/**") and "*" not in normalized[:-3] and "?" not in normalized[:-3] and "[" not in normalized[:-3]:
        prefix = normalized[:-3].rstrip("/")
        return relative_path == prefix or relative_path.startswith(f"{prefix}/")
    return fnmatch.fnmatch(relative_path, normalized)


def _file_sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixed_glob_prefix(pattern: str) -> str:
    parts: list[str] = []
    for part in str(pattern or "").replace("\\", "/").split("/"):
        if not part or any(token in part for token in ("*", "?", "[")):
            break
        parts.append(part)
    return "/".join(parts)


def _targets_default_excluded_path(pattern: str) -> bool:
    normalized = str(pattern or "").replace("\\", "/").strip("/")
    if not normalized:
        return False
    fixed_prefix = _fixed_glob_prefix(normalized)
    if not fixed_prefix:
        return False
    fixed_prefix = fixed_prefix.lower()
    for excluded in DEFAULT_SEARCH_EXCLUDED_PATHS:
        target = excluded.lower().strip("/")
        if fixed_prefix == target or fixed_prefix.startswith(f"{target}/"):
            return True
    return False


