from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
LOG_ROOT = REPO_ROOT / "output" / "codex_hook_monitor"
LOG_PATH = LOG_ROOT / "writing_supervision_watchdog_hook.jsonl"
WATCHDOG_PID_PATH = REPO_ROOT / "output" / "novel_artifacts" / "simple_novel" / "supervision" / "watchdog.pid"


def read_event() -> dict[str, Any]:
    try:
        return json.loads(sys.stdin.read() or "{}")
    except Exception:
        return {}


def append_log(payload: dict[str, Any]) -> None:
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def pid_alive(pid: str) -> bool:
    pid = str(pid or "").strip()
    if not pid.isdigit():
        return False
    try:
        proc = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=5,
        )
    except Exception:
        return False
    output = proc.stdout.strip()
    return bool(output and pid in output and "No tasks" not in output and "INFO:" not in output)


def current_watchdog_pid() -> str:
    try:
        return WATCHDOG_PID_PATH.read_text(encoding="utf-8-sig").strip()
    except Exception:
        return ""


def main() -> int:
    event = read_event()
    hook_event_name = str(event.get("hook_event_name") or event.get("event") or "")
    if hook_event_name and hook_event_name != "Stop":
        return 0

    pid = current_watchdog_pid()
    if pid_alive(pid):
        append_log(
            {
                "created_at": time.time(),
                "already_running": True,
                "pid": pid,
                "authority": "codex.hook.writing_supervision_watchdog",
            }
        )
        return 0

    script = REPO_ROOT / "scripts" / "start_writing_watchdog.ps1"
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-IntervalSeconds",
        "120",
        "-StaleSeconds",
        "300",
        "-StartNewIfMissing",
    ]
    try:
        proc = subprocess.run(
            command,
            cwd=str(REPO_ROOT),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=30,
        )
        append_log(
            {
                "created_at": time.time(),
                "returncode": proc.returncode,
                "stdout": proc.stdout[-2000:],
                "stderr": proc.stderr[-2000:],
                "authority": "codex.hook.writing_supervision_watchdog",
            }
        )
    except Exception as exc:
        append_log(
            {
                "created_at": time.time(),
                "error": str(exc),
                "authority": "codex.hook.writing_supervision_watchdog",
            }
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
