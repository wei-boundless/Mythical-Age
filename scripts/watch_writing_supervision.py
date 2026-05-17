from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SUPERVISION_ROOT = REPO_ROOT / "output" / "novel_artifacts" / "simple_novel" / "supervision"
ACTIVE_MARKER = SUPERVISION_ROOT / "active_codex_supervision.json"
STOP_FLAG = SUPERVISION_ROOT / "STOP_SUPERVISION.flag"
WATCHDOG_LOG = SUPERVISION_ROOT / "watchdog.jsonl"
WATCHDOG_STATE = SUPERVISION_ROOT / "watchdog_state.json"


def now() -> float:
    return time.time()


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.stem}.{os.getpid()}.{int(now() * 1000)}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def log(event_type: str, payload: dict[str, Any]) -> None:
    SUPERVISION_ROOT.mkdir(parents=True, exist_ok=True)
    event = {
        "event_type": event_type,
        "created_at": now(),
        "payload": payload,
        "authority": "scripts.watch_writing_supervision",
    }
    with WATCHDOG_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    atomic_write_json(WATCHDOG_STATE, event)


def api_get(base_url: str, path: str, timeout: float) -> tuple[dict[str, Any], str]:
    url = f"{base_url.rstrip('/')}{path}"
    request = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
        return json.loads(raw or "{}"), ""
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(exc)
        return {}, f"HTTP {exc.code}: {detail[:400]}"
    except Exception as exc:
        return {}, str(exc)


def test_backend_health(health_url: str, timeout: float) -> tuple[bool, str]:
    request = urllib.request.Request(url=health_url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8") or "{}")
        return payload.get("status") == "ok", ""
    except Exception as exc:
        return False, str(exc)


def run_powershell(script: Path, args: list[str], timeout: int) -> tuple[int, str, str]:
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        *args,
    ]
    proc = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


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


def stop_pid(pid: str) -> None:
    pid = str(pid or "").strip()
    if not pid.isdigit():
        return
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", f"Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        timeout=10,
    )


def state_path_from_marker(marker: dict[str, Any]) -> Path | None:
    raw = str(marker.get("state_path") or "")
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_absolute() else REPO_ROOT / path


def pid_path_from_state(state_path: Path | None) -> Path | None:
    if state_path is None:
        return None
    return state_path.parent / "supervisor.pid"


def supervisor_pid(marker: dict[str, Any]) -> str:
    pid_path = pid_path_from_state(state_path_from_marker(marker))
    if pid_path is None:
        return ""
    try:
        return pid_path.read_text(encoding="utf-8-sig").strip()
    except Exception:
        return ""


def state_age_seconds(marker: dict[str, Any], state_path: Path | None) -> int:
    candidates: list[float] = []
    state = read_json(state_path) if state_path is not None else {}
    for value in (state.get("updated_at"), marker.get("updated_at")):
        try:
            ts = float(value or 0.0)
        except (TypeError, ValueError):
            ts = 0.0
        if ts > 0:
            candidates.append(ts)
    if state_path is not None and state_path.exists():
        candidates.append(state_path.stat().st_mtime)
    if not candidates:
        return 10**9
    return max(0, int(now() - max(candidates)))


def project_runtime(base_url: str, project_id: str, timeout: float) -> tuple[dict[str, Any], str]:
    encoded = urllib.parse.quote(project_id, safe="")
    payload, error = api_get(base_url, f"/orchestration/projects/{encoded}/runtime-status", timeout)
    return dict(payload.get("project_runtime_status") or {}), error


def project_is_completed(project_status: dict[str, Any], target_words: int) -> bool:
    status = str(project_status.get("project_runtime_status") or "")
    completed = int(project_status.get("completed_metric_total") or project_status.get("completed_words_total") or 0)
    target = int(project_status.get("target_metric_total") or target_words)
    return completed >= target and status in {"completed", "succeeded"}


def restart_backend(args: argparse.Namespace) -> None:
    script = REPO_ROOT / "scripts" / "start_writing_stack.ps1"
    ps_args = [
        "-BindHost",
        args.bind_host,
        "-BindPort",
        str(args.bind_port),
        "-PythonExe",
        args.python_exe,
        "-SkipRunStart",
        "-StartupTimeoutSeconds",
        str(args.backend_startup_timeout),
    ]
    code, stdout, stderr = run_powershell(script, ps_args, timeout=args.backend_startup_timeout + 30)
    log("backend_restart", {"returncode": code, "stdout": stdout[-2000:], "stderr": stderr[-2000:]})
    if code != 0:
        raise RuntimeError(f"backend restart failed: {stderr or stdout}")


def start_supervisor(args: argparse.Namespace, project_status: dict[str, Any], reason: str) -> None:
    coordination_run_id = str(project_status.get("active_coordination_run_id") or "")
    task_run_id = _root_task_run_id_for_supervision(project_status, coordination_run_id=coordination_run_id)
    completed = project_is_completed(project_status, args.target_words)
    if completed:
        log("supervisor_start_skipped", {"reason": "project_completed", "project_status": project_status})
        return

    script = REPO_ROOT / "scripts" / "start_writing_supervisor.ps1"
    session_id = f"{args.session_prefix}-{time.strftime('%Y%m%d-%H%M%S')}"
    ps_args = [
        "-BaseUrl",
        args.base_url,
        "-SessionId",
        session_id,
        "-ProjectId",
        args.project_id,
        "-ProjectTitle",
        args.project_title,
        "-ProjectBriefFile",
        args.project_brief_file,
        "-TargetWords",
        str(args.target_words),
        "-ChapterTargetWords",
        str(args.chapter_target_words),
        "-ChaptersPerRound",
        str(args.chapters_per_round),
        "-IntervalSeconds",
        str(args.supervisor_interval_seconds),
    ]
    if task_run_id:
        ps_args.extend(["-AttachExisting", "-TaskRunId", task_run_id])
        if coordination_run_id:
            ps_args.extend(["-CoordinationRunId", coordination_run_id])
    elif not args.start_new_if_missing:
        log("supervisor_start_skipped", {"reason": "no_active_run_and_start_new_disabled", "trigger": reason})
        return

    code, stdout, stderr = run_powershell(script, ps_args, timeout=90)
    log(
        "supervisor_started_by_watchdog",
        {
            "reason": reason,
            "returncode": code,
            "stdout": stdout[-3000:],
            "stderr": stderr[-3000:],
            "attached_task_run_id": task_run_id,
            "attached_coordination_run_id": coordination_run_id,
        },
    )
    if code != 0:
        raise RuntimeError(f"supervisor start failed: {stderr or stdout}")


def _root_task_run_id_for_supervision(project_status: dict[str, Any], *, coordination_run_id: str) -> str:
    active_task_run_id = str(project_status.get("active_task_run_id") or "").strip()
    root_from_coordination = _root_task_run_id_from_coordination_run_id(coordination_run_id)
    if root_from_coordination and (not active_task_run_id or ":taskinst:" in active_task_run_id):
        return root_from_coordination
    return active_task_run_id or root_from_coordination


def _root_task_run_id_from_coordination_run_id(coordination_run_id: str) -> str:
    value = str(coordination_run_id or "").strip()
    if not value.startswith("coordrun:"):
        return ""
    root = value[len("coordrun:") :]
    if root.endswith(":primary"):
        root = root[: -len(":primary")]
    return root.strip()


def supervise_once(args: argparse.Namespace) -> None:
    if STOP_FLAG.exists():
        log("watchdog_paused_by_stop_flag", {"stop_flag": str(STOP_FLAG)})
        return

    healthy, health_error = test_backend_health(args.health_url, args.request_timeout)
    if not healthy:
        failure_count = consecutive_backend_health_failure_count()
        marker = read_json(ACTIVE_MARKER)
        state_path = state_path_from_marker(marker)
        active_state_age = state_age_seconds(marker, state_path)
        active_supervisor_alive = pid_alive(supervisor_pid(marker))
        runtime_event_age = latest_runtime_event_age_seconds()
        log(
            "backend_unhealthy",
            {
                "health_url": args.health_url,
                "error": health_error,
                "consecutive_failure_count": failure_count,
                "restart_threshold": 2,
                "active_supervisor_alive": active_supervisor_alive,
                "active_state_age_seconds": active_state_age,
                "runtime_event_age_seconds": runtime_event_age,
                "stale_seconds": args.stale_seconds,
            },
        )
        if runtime_event_age <= args.stale_seconds:
            return
        if active_supervisor_alive and active_state_age <= args.stale_seconds:
            return
        if failure_count >= 2:
            restart_backend(args)
        return

    project_status, project_error = project_runtime(args.base_url, args.project_id, args.request_timeout)
    if project_error:
        log("project_status_unavailable", {"error": project_error})
        return
    if project_is_completed(project_status, args.target_words):
        log("watchdog_project_completed", {"project_status": project_status})
        return

    marker = read_json(ACTIVE_MARKER)
    state_path = state_path_from_marker(marker)
    pid = supervisor_pid(marker)
    alive = pid_alive(pid)
    age = state_age_seconds(marker, state_path)
    marker_enabled = marker.get("enabled") is True
    marker_status = str(marker.get("status") or "")

    should_restart = False
    reason = ""
    if not marker_enabled or marker_status in {"stopped", "failed"}:
        should_restart = True
        reason = f"marker_not_running:{marker_status or 'missing'}"
    elif not alive:
        should_restart = True
        reason = "supervisor_process_missing"
    elif age > args.stale_seconds:
        should_restart = True
        reason = f"supervisor_state_stale:{age}s"
        stop_pid(pid)

    if should_restart:
        start_supervisor(args, project_status, reason)
        return

    log(
        "watchdog_ok",
        {
            "supervisor_pid": pid,
            "state_age_seconds": age,
            "active_task_run_id": project_status.get("active_task_run_id"),
            "active_run_status": project_status.get("active_run_status"),
            "completed_metric_total": project_status.get("completed_metric_total"),
            "target_metric_total": project_status.get("target_metric_total"),
        },
    )


def consecutive_backend_health_failure_count() -> int:
    state = read_json(WATCHDOG_STATE)
    if str(state.get("event_type") or "") != "backend_unhealthy":
        return 1
    payload = dict(state.get("payload") or {})
    previous = int(payload.get("consecutive_failure_count") or 1)
    return previous + 1


def latest_runtime_event_age_seconds() -> int:
    event_root = REPO_ROOT / "storage" / "runtime_state" / "events"
    try:
        latest = max((path.stat().st_mtime for path in event_root.glob("*.jsonl")), default=0.0)
    except Exception:
        latest = 0.0
    if latest <= 0:
        return 10**9
    return max(0, int(now() - latest))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Low-frequency watchdog for the writing supervision process.")
    parser.add_argument("--bind-host", default="127.0.0.1")
    parser.add_argument("--bind-port", type=int, default=8004)
    parser.add_argument("--base-url", default="http://127.0.0.1:8004/api")
    parser.add_argument("--health-url", default="http://127.0.0.1:8004/health")
    parser.add_argument("--python-exe", default=r"C:\Users\admin\.conda\envs\agent\python.exe")
    parser.add_argument("--project-id", default="project:honghuang-times")
    parser.add_argument("--project-title", default="洪荒时代")
    parser.add_argument("--project-brief-file", default="output/novel_artifacts/simple_novel/project_brief.md")
    parser.add_argument("--target-words", type=int, default=1_000_000)
    parser.add_argument("--chapter-target-words", type=int, default=2_000)
    parser.add_argument("--chapters-per-round", type=int, default=10)
    parser.add_argument("--interval", type=int, default=120)
    parser.add_argument("--stale-seconds", type=int, default=300)
    parser.add_argument("--request-timeout", type=float, default=8.0)
    parser.add_argument("--backend-startup-timeout", type=int, default=45)
    parser.add_argument("--supervisor-interval-seconds", type=int, default=8)
    parser.add_argument("--session-prefix", default="writing-simple-novel-honghuang-supervised-watchdog")
    parser.add_argument("--start-new-if-missing", action="store_true")
    parser.add_argument("--once", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    log("watchdog_started", {"interval": args.interval, "stale_seconds": args.stale_seconds, "once": args.once})
    while True:
        try:
            supervise_once(args)
        except Exception as exc:
            log("watchdog_error", {"error": str(exc), "type": exc.__class__.__name__})
        if args.once:
            return 0
        time.sleep(max(30, int(args.interval)))


if __name__ == "__main__":
    raise SystemExit(main())
