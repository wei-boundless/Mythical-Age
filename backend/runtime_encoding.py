from __future__ import annotations

import os
import platform
import sys
from collections.abc import Mapping
from typing import Any

UTF8_ENV_VARS = {
    "PYTHONUTF8": "1",
    "PYTHONIOENCODING": "utf-8",
}

# Common mojibake fragments produced when UTF-8 Chinese text is decoded as GBK.
MOJIBAKE_MARKERS = (
    "\ufffd",
    "\u951f",
    "\u951b",
    "\u9286",
    "\u93c8\u93c2",
    "\u699b\u52ef\u567e\u6d60\u950b\u7278",
    "\u7f01\u64b4\u7049",
    "\u6fb6\u8fab\u89e6",
    "\u9471\u65c2\u7d89\u93bc\u6ec5\u50a8",
    "\u6d60\u5a42\u3049",
    "\u95c2\u68f0",
    "\u7487\u5cf0\u5e9c",
    "\u9359\u6d60",
    "cl?ture",
    "Mise ? jour",
)

POWERSHELL_UTF8_BOOTSTRAP = "\n".join(
    (
        "[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)",
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)",
        "$OutputEncoding = [System.Text.UTF8Encoding]::new($false)",
        "$env:PYTHONUTF8 = '1'",
        "$env:PYTHONIOENCODING = 'utf-8'",
        "chcp 65001 > $null",
    )
)


def build_utf8_env(base_env: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base_env is None else base_env)
    env.update(UTF8_ENV_VARS)
    return env


def utf8_subprocess_text_kwargs(
    base_env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "env": build_utf8_env(base_env),
    }


def configure_process_utf8() -> None:
    os.environ.update(UTF8_ENV_VARS)
    for stream_name in ("stdin", "stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None or not hasattr(stream, "reconfigure"):
            continue
        kwargs: dict[str, Any] = {
            "encoding": "utf-8",
            "errors": "replace",
        }
        if stream_name != "stdin":
            kwargs["write_through"] = True
        try:
            stream.reconfigure(**kwargs)
        except (AttributeError, OSError, ValueError):
            continue


def build_windows_powershell_command(command: str) -> list[str]:
    return [
        "powershell",
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        f"{POWERSHELL_UTF8_BOOTSTRAP}\n{command}",
    ]


def is_windows() -> bool:
    return platform.system().lower().startswith("win")


def looks_like_mojibake(text: str) -> bool:
    sample = str(text or "")
    return any(marker in sample for marker in MOJIBAKE_MARKERS)


def count_mojibake_markers(text: str) -> int:
    sample = str(text or "")
    return sum(sample.count(marker) for marker in MOJIBAKE_MARKERS)
