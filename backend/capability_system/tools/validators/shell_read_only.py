from __future__ import annotations

import re
import shlex
from typing import Any


CONTROL_OPERATORS = ("&&", "||", ";", "|", "`", "$(", ">", "<")
READ_ONLY_COMMANDS = {
    "cat",
    "dir",
    "findstr",
    "git",
    "grep",
    "head",
    "ls",
    "pwd",
    "rg",
    "tail",
    "type",
    "wc",
}
GIT_READ_ONLY_SUBCOMMANDS = {
    "branch",
    "diff",
    "log",
    "show",
    "status",
}
GIT_DANGEROUS_FLAGS = {
    "-c",
    "--config-env",
    "--exec-path",
    "--git-dir",
    "--work-tree",
}
SHELL_VARIABLE_RE = re.compile(r"(^|[^\\])(\$[A-Za-z_][A-Za-z0-9_]*|%[A-Za-z_][A-Za-z0-9_]*%)")


def validate_shell_read_only(operation_input: dict[str, Any]) -> tuple[bool, str]:
    """Minimal deterministic read-only shell validator.

    This is deliberately conservative. It is not a general shell parser; it is
    a phase-1 safety gate for future read-only shell directives.
    """

    command = str(operation_input.get("command") or "").strip()
    if not command:
        return False, "shell command is empty"
    if _has_control_operator(command):
        return False, "shell command uses control operators"
    if "\\" * 2 in command or command.startswith("//"):
        return False, "shell command uses UNC/network path"
    if SHELL_VARIABLE_RE.search(command):
        return False, "shell command uses variable expansion"
    if "*" in command or "?" in command:
        return False, "shell command uses glob expansion"
    try:
        parts = shlex.split(command, posix=False)
    except ValueError:
        return False, "shell command cannot be parsed safely"
    if not parts:
        return False, "shell command is empty"
    executable = parts[0].lower()
    if executable not in READ_ONLY_COMMANDS:
        return False, "shell command executable is not allowlisted read-only"
    if executable == "git":
        return _validate_git_read_only(parts[1:])
    return True, "shell command passed read-only validator"


def _has_control_operator(command: str) -> bool:
    return any(operator in command for operator in CONTROL_OPERATORS)


def _validate_git_read_only(args: list[str]) -> tuple[bool, str]:
    if not args:
        return False, "git command missing read-only subcommand"
    for arg in args:
        lowered = arg.lower()
        if lowered in GIT_DANGEROUS_FLAGS:
            return False, "git command uses dangerous configuration flag"
    subcommand = ""
    for arg in args:
        if arg.startswith("-"):
            continue
        subcommand = arg.lower()
        break
    if subcommand not in GIT_READ_ONLY_SUBCOMMANDS:
        return False, "git subcommand is not allowlisted read-only"
    return True, "git command passed read-only validator"


