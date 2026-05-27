from __future__ import annotations

import json
import subprocess
import threading
import time
import uuid
from pathlib import Path
from queue import Empty, Queue
from typing import Any

from code_environment.models import PiSidecarStatus


class PiSidecarManager:
    """Small JSONL RPC process manager for Pi.

    This phase intentionally supports only read-only smoke commands. Prompting and
    editing are added later after project-owned permission and change-set gates.
    """

    def __init__(self) -> None:
        self._process: subprocess.Popen[str] | None = None
        self._stdout_queue: Queue[dict[str, Any]] = Queue()
        self._stderr_lines: list[str] = []
        self._workspace_root = ""
        self._cli_path = ""
        self._started_at: float | None = None
        self._last_error = ""
        self._lock = threading.Lock()

    def status(self) -> PiSidecarStatus:
        process = self._process
        running = process is not None and process.poll() is None
        return PiSidecarStatus(
            running=running,
            pid=process.pid if running and process is not None else None,
            workspace_root=self._workspace_root,
            cli_path=self._cli_path,
            started_at=self._started_at if running else None,
            last_error=self._last_error,
            stderr_tail="\n".join(self._stderr_lines[-20:]),
        )

    def start(self, *, cli_path: str | Path, workspace_root: str | Path) -> PiSidecarStatus:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return self.status()
            cli = Path(cli_path).resolve()
            cwd = Path(workspace_root).resolve()
            if not cli.exists():
                self._last_error = f"Pi CLI does not exist: {cli}"
                raise FileNotFoundError(self._last_error)
            self._stdout_queue = Queue()
            self._stderr_lines = []
            self._workspace_root = str(cwd)
            self._cli_path = str(cli)
            self._last_error = ""
            self._process = subprocess.Popen(
                ["node", str(cli), "--mode", "rpc", "--no-session"],
                cwd=str(cwd),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            self._started_at = time.time()
            threading.Thread(target=self._read_stdout, daemon=True).start()
            threading.Thread(target=self._read_stderr, daemon=True).start()
            time.sleep(0.15)
            if self._process.poll() is not None:
                self._last_error = f"Pi sidecar exited immediately with code {self._process.returncode}."
                raise RuntimeError(self._last_error)
            return self.status()

    def stop(self) -> PiSidecarStatus:
        with self._lock:
            process = self._process
            if process is None:
                return self.status()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            self._process = None
            return self.status()

    def send_readonly_command(self, command: str, timeout_seconds: float = 10) -> dict[str, Any]:
        if command not in {"get_state", "get_available_models"}:
            raise ValueError(f"Unsupported read-only Pi RPC command: {command}")
        process = self._process
        if process is None or process.poll() is not None or process.stdin is None:
            raise RuntimeError("Pi sidecar is not running.")
        request_id = f"req_{uuid.uuid4().hex}"
        payload = {"id": request_id, "type": command}
        process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        process.stdin.flush()
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            try:
                item = self._stdout_queue.get(timeout=0.25)
            except Empty:
                continue
            if item.get("type") == "response" and item.get("id") == request_id:
                return item
        raise TimeoutError(f"Timed out waiting for Pi RPC response: {command}")

    def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        for raw_line in process.stdout:
            line = raw_line.rstrip("\r\n")
            if not line:
                continue
            try:
                self._stdout_queue.put(json.loads(line))
            except json.JSONDecodeError:
                self._stdout_queue.put({"type": "raw_stdout", "line": line})

    def _read_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        for raw_line in process.stderr:
            line = raw_line.rstrip("\r\n")
            if line:
                self._stderr_lines.append(line)
                if len(self._stderr_lines) > 200:
                    self._stderr_lines = self._stderr_lines[-200:]


PI_SIDECAR_MANAGER = PiSidecarManager()


