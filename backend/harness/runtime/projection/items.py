from __future__ import annotations

from typing import Any

from .guards import text


def action_kind_for_tool(tool_name: str, raw_target: Any = "") -> str:
    normalized = text(tool_name).lower()
    target = text(raw_target).lower()
    if normalized == "read_persisted_tool_result":
        return "runtime_read"
    if normalized == "memory_search":
        return "memory"
    if normalized in {"path_exists", "stat_path", "list_dir"}:
        return "inspect"
    if normalized in {"read_file", "read_path"} or "read" in normalized:
        return "read"
    if normalized in {"search_text", "search_files", "glob_paths"} or any(token in normalized for token in ("search", "grep", "glob")):
        return "search"
    if normalized in {"write_file", "edit_file", "apply_patch"} or any(token in normalized for token in ("write", "edit", "patch")):
        return "edit"
    if any(token in normalized for token in ("terminal", "shell", "command", "powershell")):
        return "verify" if any(token in target for token in ("test", "pytest", "npm", "vitest", "pnpm")) else "run"
    if "agent" in normalized:
        return "subagent"
    return "work"
