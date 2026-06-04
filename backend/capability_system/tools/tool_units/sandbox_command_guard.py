from __future__ import annotations

from pathlib import Path
import re


BLOCKED_COMMAND_PATTERNS = (
    "rm -rf /",
    "shutdown",
    "reboot",
    "mkfs",
    "format ",
    ":(){:|:&};:",
)

BLOCKED_PATH_PATTERNS = (
    "../",
    "..\\",
    "\\windows",
    "/etc/",
    "/var/",
    "/usr/",
    "/root/",
    "/home/",
    "/users/",
)

ABSOLUTE_WINDOWS_PATH_RE = re.compile(r"(?i)(?:^|[\s'\"=;])([a-z]:[\\/][^\s'\";|&<>`]*)")
ABSOLUTE_UNIX_PATH_RE = re.compile(r"(?:^|[\s'\"=;])/(?:etc|var|usr|root|home|users|windows|mnt|proc|sys|dev)(?:/|\\|\s|$)")


def validate_sandbox_command_text(value: str, *, kind: str, workspace_root: str | Path | None = None) -> str:
    text = str(value or "")
    lowered = text.lower()
    if any(pattern in lowered for pattern in BLOCKED_COMMAND_PATTERNS):
        return f"Blocked: {kind} matches the sandbox command blacklist."
    if any(pattern in lowered for pattern in BLOCKED_PATH_PATTERNS):
        return f"Blocked: {kind} references a path outside the sandbox workspace."
    if _has_unauthorized_windows_absolute_path(text, workspace_root=workspace_root) or ABSOLUTE_UNIX_PATH_RE.search(text):
        return f"Blocked: {kind} references an absolute path outside the sandbox workspace."
    return ""


def _has_unauthorized_windows_absolute_path(value: str, *, workspace_root: str | Path | None) -> bool:
    matches = [match.group(1) for match in ABSOLUTE_WINDOWS_PATH_RE.finditer(value)]
    if not matches:
        return False
    root = _resolved_workspace_root(workspace_root)
    if root is None:
        return True
    return any(not _path_inside_root(raw_path, root) for raw_path in matches)


def _resolved_workspace_root(workspace_root: str | Path | None) -> Path | None:
    text = str(workspace_root or "").strip()
    if not text:
        return None
    try:
        root = Path(text).expanduser().resolve()
    except OSError:
        return None
    return root if root.is_dir() else None


def _path_inside_root(raw_path: str, root: Path) -> bool:
    try:
        path = Path(str(raw_path or "").strip().strip("'\"")).expanduser().resolve()
    except OSError:
        return False
    return path == root or root in path.parents


