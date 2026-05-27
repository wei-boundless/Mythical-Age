from __future__ import annotations

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

ABSOLUTE_WINDOWS_PATH_RE = re.compile(r"(?i)(?:^|[\s'\"=;])(?:[a-z]:[\\/])")
ABSOLUTE_UNIX_PATH_RE = re.compile(r"(?:^|[\s'\"=;])/(?:etc|var|usr|root|home|users|windows|mnt|proc|sys|dev)(?:/|\\|\s|$)")


def validate_sandbox_command_text(value: str, *, kind: str) -> str:
    text = str(value or "")
    lowered = text.lower()
    if any(pattern in lowered for pattern in BLOCKED_COMMAND_PATTERNS):
        return f"Blocked: {kind} matches the sandbox command blacklist."
    if any(pattern in lowered for pattern in BLOCKED_PATH_PATTERNS):
        return f"Blocked: {kind} references a path outside the sandbox workspace."
    if ABSOLUTE_WINDOWS_PATH_RE.search(text) or ABSOLUTE_UNIX_PATH_RE.search(text):
        return f"Blocked: {kind} references an absolute path outside the sandbox workspace."
    return ""


