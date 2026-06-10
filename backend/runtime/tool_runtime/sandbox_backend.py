from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_SIDE_EFFECT_TOOL_NAMES = {"write_file", "edit_file", "terminal", "python_repl"}
REAL_WORKSPACE_READ_TOOL_NAMES = {
    "read_file",
    "read_structured_file",
    "stat_path",
    "path_exists",
    "glob_paths",
    "search_files",
    "search_text",
    "list_dir",
}
DEFAULT_OVERLAY_TOOL_NAMES = {
    "read_file",
    "read_structured_file",
    "stat_path",
    "path_exists",
    "glob_paths",
    "search_files",
    "search_text",
    "write_file",
    "edit_file",
    "terminal",
    "python_repl",
}
FIXED_STORE_TOOL_NAMES = {"image_generate"}
OVERLAY_COPY_ON_WRITE_TOOL_NAMES = {"edit_file"}
OVERLAY_COPY_ON_READ_TOOL_NAMES = {"read_file", "read_structured_file", "stat_path", "path_exists"}
OVERLAY_MATERIALIZE_BEFORE_TOOL_NAMES = {"terminal", "python_repl", "glob_paths", "search_files", "search_text", "list_dir"}
DEFAULT_FULL_WORKSPACE_EXCLUDED_DIR_NAMES = {
    ".cache",
    ".git",
    ".gradle",
    ".hg",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".svn",
    ".turbo",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "env",
    "node_modules",
    "target",
    "venv",
}
DEFAULT_FULL_WORKSPACE_EXCLUDED_PATH_PREFIXES = {
    "backend/mythical-agent/sessions",
    "backend/storage/logs",
    "logs",
    "output/sandbox_runs",
    "storage/runtime_cache",
    "storage/runtime_state",
}
DEFAULT_FULL_WORKSPACE_EXCLUDED_FILE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    "id_rsa",
    "id_dsa",
}
DEFAULT_FULL_WORKSPACE_EXCLUDED_FILE_SUFFIXES = {
    ".key",
    ".pem",
    ".p12",
    ".pfx",
}


@dataclass(frozen=True, slots=True)
class SandboxToolContext:
    enabled: bool
    backend: str
    mode: str
    sandbox_root: Path
    workspace_root: Path | None
    tool_name: str
    real_workspace_access: str
    overlay_copy_on_write: bool
    materialized_roots: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "backend": self.backend,
            "mode": self.mode,
            "sandbox_root": str(self.sandbox_root),
            "workspace_root": str(self.workspace_root) if self.workspace_root is not None else "",
            "tool_name": self.tool_name,
            "real_workspace_access": self.real_workspace_access,
            "overlay_copy_on_write": self.overlay_copy_on_write,
            "materialized_roots": list(self.materialized_roots),
        }


class LocalOverlaySandboxBackend:
    """Local copy-on-write sandbox boundary for workspace tools."""

    backend_name = "local_overlay"

    def context_for_tool(self, *, tool_name: str, sandbox_policy: dict[str, Any] | None) -> SandboxToolContext | None:
        policy = dict(sandbox_policy or {})
        if policy.get("enabled") is not True:
            return None
        effective_tool_name = str(tool_name or "").strip()
        if effective_tool_name in FIXED_STORE_TOOL_NAMES:
            return None
        overlay_tools = {
            str(item or "").strip()
            for item in list(policy.get("overlay_tools") or DEFAULT_OVERLAY_TOOL_NAMES)
            if str(item or "").strip()
        }
        if effective_tool_name not in overlay_tools:
            return None
        sandbox_root_text = str(policy.get("sandbox_root") or "").strip()
        if not sandbox_root_text:
            return None
        sandbox_root = Path(sandbox_root_text).resolve()
        sandbox_root.mkdir(parents=True, exist_ok=True)
        workspace_root = None
        workspace_root_text = str(policy.get("workspace_root") or "").strip()
        if workspace_root_text:
            workspace_root = Path(workspace_root_text).resolve()
        return SandboxToolContext(
            enabled=True,
            backend=str(policy.get("backend") or self.backend_name),
            mode=str(policy.get("mode") or "workspace_overlay"),
            sandbox_root=sandbox_root,
            workspace_root=workspace_root,
            tool_name=effective_tool_name,
            real_workspace_access=str(policy.get("real_workspace_access") or "read_only"),
            overlay_copy_on_write=bool(policy.get("overlay_copy_on_write") is not False),
            materialized_roots=tuple(
                normalize_relative_path(item)
                for item in list(policy.get("materialized_roots") or [])
                if normalize_relative_path(item)
            ),
        )

    def prepare_tool_call(self, *, tool_name: str, tool_args: dict[str, Any], context: SandboxToolContext) -> None:
        if not context.overlay_copy_on_write:
            return
        effective_tool_name = str(tool_name or "").strip()
        requested_roots = _requested_materialized_roots(context, effective_tool_name, tool_args)
        if effective_tool_name in OVERLAY_MATERIALIZE_BEFORE_TOOL_NAMES:
            self._materialize_roots(context, requested_roots=requested_roots)
        if effective_tool_name not in OVERLAY_COPY_ON_WRITE_TOOL_NAMES and effective_tool_name not in OVERLAY_COPY_ON_READ_TOOL_NAMES:
            return
        relative_path = normalize_relative_path(tool_args.get("path"))
        if not relative_path or context.workspace_root is None:
            return
        source = (context.workspace_root / relative_path).resolve()
        target = (context.sandbox_root / relative_path).resolve()
        if not _is_inside(source, context.workspace_root):
            return
        if not _is_inside(target, context.sandbox_root):
            return
        if not source.exists():
            alternate_source = _backend_relative_source(context.workspace_root, relative_path)
            if alternate_source is not None:
                source = alternate_source
        if target.exists() or not source.exists():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_file():
            shutil.copy2(source, target)
        elif source.is_dir():
            target.mkdir(parents=True, exist_ok=True)

    def _materialize_roots(self, context: SandboxToolContext, *, requested_roots: tuple[str, ...] = ()) -> None:
        if context.workspace_root is None:
            return
        for raw in _materialized_roots(context, requested_roots=requested_roots):
            source = (context.workspace_root / raw).resolve()
            target = (context.sandbox_root / raw).resolve()
            if not _is_inside(source, context.workspace_root) or not _is_inside(target, context.sandbox_root):
                continue
            if not source.exists():
                continue
            if _should_skip_workspace_path(source, root=context.workspace_root, context=context):
                continue
            if source.is_file():
                if _should_skip_workspace_file(source, root=context.workspace_root, context=context):
                    continue
                if target.exists():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                continue
            for child in source.rglob("*"):
                if _should_skip_workspace_path(child, root=context.workspace_root, context=context):
                    continue
                if not child.is_file():
                    continue
                relative = child.resolve().relative_to(source).as_posix()
                child_target = (target / relative).resolve()
                if not _is_inside(child_target, context.sandbox_root) or child_target.exists():
                    continue
                child_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(child, child_target)

    def execution_root(self, context: SandboxToolContext) -> Path:
        return context.sandbox_root

    def tool_workspace_root(self, context: SandboxToolContext) -> Path:
        if context.mode == "workspace_overlay":
            return context.sandbox_root
        if context.tool_name in REAL_WORKSPACE_READ_TOOL_NAMES and context.workspace_root is not None:
            return context.workspace_root
        return context.sandbox_root


def normalize_relative_path(value: Any) -> str:
    text = str(value or "").replace("\\", "/").strip().strip("/")
    while "//" in text:
        text = text.replace("//", "/")
    if not text or text.startswith("../") or "/../" in f"/{text}/":
        return ""
    if "://" in text or text.startswith(("/", "\\")):
        return ""
    return text


def _is_inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _materialized_roots(context: SandboxToolContext, *, requested_roots: tuple[str, ...] = ()) -> tuple[str, ...]:
    roots = [
        normalize_relative_path(item)
        for item in [*context.materialized_roots, *requested_roots]
        if normalize_relative_path(item)
    ]
    return tuple(dict.fromkeys(roots))


def _should_skip_workspace_path(path: Path, *, root: Path, context: SandboxToolContext) -> bool:
    if _is_inside(path.resolve(), context.sandbox_root.resolve()):
        return True
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        return True
    if any(part in DEFAULT_FULL_WORKSPACE_EXCLUDED_DIR_NAMES for part in relative.parts):
        return True
    if _is_excluded_workspace_relative_path(relative):
        return True
    if path.is_file() and _should_skip_workspace_file(path, root=root, context=context):
        return True
    return False


def _should_skip_workspace_file(path: Path, *, root: Path, context: SandboxToolContext) -> bool:
    if _is_inside(path.resolve(), context.sandbox_root.resolve()):
        return True
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        return True
    if _is_excluded_workspace_relative_path(relative):
        return True
    name = path.name
    lowered_name = name.lower()
    if lowered_name == ".env" or lowered_name.startswith(".env."):
        return True
    if name in DEFAULT_FULL_WORKSPACE_EXCLUDED_FILE_NAMES or lowered_name in DEFAULT_FULL_WORKSPACE_EXCLUDED_FILE_NAMES:
        return True
    return any(lowered_name.endswith(suffix) for suffix in DEFAULT_FULL_WORKSPACE_EXCLUDED_FILE_SUFFIXES)


def _is_excluded_workspace_relative_path(relative: Path) -> bool:
    normalized = relative.as_posix().strip("/")
    if not normalized or normalized == ".":
        return False
    return any(
        normalized == prefix or normalized.startswith(f"{prefix}/")
        for prefix in DEFAULT_FULL_WORKSPACE_EXCLUDED_PATH_PREFIXES
    )


def _requested_materialized_roots(context: SandboxToolContext, tool_name: str, tool_args: dict[str, Any]) -> tuple[str, ...]:
    args = dict(tool_args or {})
    if tool_name in {"search_files", "search_text"}:
        roots = _normalized_path_list(args.get("roots"), workspace_root=context.workspace_root)
        if roots:
            return roots
        paths = _normalized_path_list(args.get("paths"), workspace_root=context.workspace_root)
        if paths:
            return tuple(dict.fromkeys(_parent_root(path) for path in paths if path))
    if tool_name == "list_dir":
        return tuple(_normalized_path_list(args.get("path") or ".", workspace_root=context.workspace_root))
    return ()


def _normalized_path_list(value: Any, *, workspace_root: Path | None) -> tuple[str, ...]:
    raw_values = value if isinstance(value, list) else [value]
    return tuple(
        dict.fromkeys(
            normalized
            for item in raw_values
            for normalized in [_workspace_relative_materialized_path(item, workspace_root=workspace_root)]
            if normalized
        )
    )


def _workspace_relative_materialized_path(value: Any, *, workspace_root: Path | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    candidate = Path(text)
    if candidate.is_absolute():
        if workspace_root is None:
            return ""
        try:
            return candidate.resolve().relative_to(workspace_root.resolve()).as_posix() or "."
        except ValueError:
            return ""
    return normalize_relative_path(text)


def _parent_root(path: str) -> str:
    parent = str(Path(path).parent).replace("\\", "/")
    return "." if parent in {"", "."} else parent


def _backend_relative_source(workspace_root: Path, relative_path: str) -> Path | None:
    backend_root = (workspace_root / "backend").resolve()
    if not backend_root.exists():
        return None
    candidate = (backend_root / relative_path).resolve()
    if candidate == backend_root or backend_root in candidate.parents:
        return candidate
    return None


