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
OVERLAY_COPY_ON_WRITE_TOOL_NAMES = {"edit_file"}
OVERLAY_COPY_ON_READ_TOOL_NAMES = {"read_file", "read_structured_file"}


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
        }


class LocalOverlaySandboxBackend:
    """Local copy-on-write sandbox boundary for workspace tools."""

    backend_name = "local_overlay"

    def context_for_tool(self, *, tool_name: str, sandbox_policy: dict[str, Any] | None) -> SandboxToolContext | None:
        policy = dict(sandbox_policy or {})
        if policy.get("enabled") is not True:
            return None
        effective_tool_name = str(tool_name or "").strip()
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
        )

    def prepare_tool_call(self, *, tool_name: str, tool_args: dict[str, Any], context: SandboxToolContext) -> None:
        if not context.overlay_copy_on_write:
            return
        effective_tool_name = str(tool_name or "").strip()
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
        if target.exists() or not source.exists() or not source.is_file():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

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


def _backend_relative_source(workspace_root: Path, relative_path: str) -> Path | None:
    backend_root = (workspace_root / "backend").resolve()
    if not backend_root.exists():
        return None
    candidate = (backend_root / relative_path).resolve()
    if candidate == backend_root or backend_root in candidate.parents:
        return candidate
    return None


