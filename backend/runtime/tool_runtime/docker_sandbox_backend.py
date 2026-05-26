from __future__ import annotations

import subprocess
import uuid
from dataclasses import asdict, dataclass, field
from hashlib import sha1
from pathlib import Path
from typing import Any, Callable, Sequence

from runtime_encoding import utf8_subprocess_text_kwargs


SandboxRunner = Callable[..., subprocess.CompletedProcess[str]]
DEFAULT_SBX_EXECUTABLE = str(Path.home() / "AppData" / "Local" / "DockerSandboxes" / "bin" / "sbx.exe")


@dataclass(frozen=True, slots=True)
class DockerSandboxConfig:
    template: str = ""
    sbx_executable: str = DEFAULT_SBX_EXECUTABLE
    sbx_agent: str = "shell"
    sbx_name: str = ""
    workdir: str = ""
    memory: str = "1g"
    cpus: str = "1.0"
    environment: dict[str, str] = field(default_factory=dict)
    output_limit_chars: int = 5000
    timeout_seconds: int = 30

    @classmethod
    def from_policy(cls, policy: dict[str, Any] | None, *, default_timeout_seconds: int = 30) -> "DockerSandboxConfig":
        payload = dict(policy or {})
        sbx = dict(payload.get("sbx") or {})
        environment = {
            str(key): str(value)
            for key, value in dict(sbx.get("environment") or {}).items()
            if str(key).strip()
        }
        return cls(
            template=str(sbx.get("template") or payload.get("template") or "").strip(),
            sbx_executable=str(sbx.get("executable") or DEFAULT_SBX_EXECUTABLE).strip() or DEFAULT_SBX_EXECUTABLE,
            sbx_agent=str(sbx.get("agent") or "shell").strip() or "shell",
            sbx_name=str(sbx.get("name") or payload.get("workspace_key") or "").strip(),
            workdir=str(sbx.get("workdir") or "").strip(),
            memory=str(sbx.get("memory") or "1g").strip() or "1g",
            cpus=str(sbx.get("cpus") or "1.0").strip() or "1.0",
            environment=environment,
            output_limit_chars=max(1000, int(sbx.get("output_limit_chars") or payload.get("output_limit_chars") or 5000)),
            timeout_seconds=max(1, int(sbx.get("timeout_seconds") or payload.get("timeout_seconds") or default_timeout_seconds)),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["environment"] = dict(self.environment)
        return payload


@dataclass(frozen=True, slots=True)
class DockerSandboxExecution:
    command: str
    exec_command: tuple[str, ...]
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    timed_out: bool = False
    output: str = ""
    receipt: dict[str, Any] = field(default_factory=dict)


class DockerSandboxBackend:
    """Docker Sandboxes execution backend for shell and Python tools.

    Permission decisions happen before this backend is called. This class only
    prepares and executes an sbx sandbox with explicit workspace mounts.
    """

    backend_name = "docker_sandboxes"

    def __init__(self, *, runner: SandboxRunner | None = None) -> None:
        self._runner = runner or subprocess.run

    def is_enabled(self, sandbox_policy: dict[str, Any] | None) -> bool:
        policy = dict(sandbox_policy or {})
        backend = str(policy.get("execution_backend") or policy.get("backend") or "").strip().lower()
        return policy.get("enabled") is True and backend in {"sbx", "docker_sandboxes", "docker-sandboxes"}

    def run_shell(
        self,
        *,
        command: str,
        workspace_root: str | Path,
        sandbox_root: str | Path,
        sandbox_policy: dict[str, Any] | None,
    ) -> DockerSandboxExecution:
        container_command_text = _normalize_shell_command_for_sbx(str(command or ""))
        return self._run(
            command=str(command or ""),
            container_command=("bash", "-lc", container_command_text),
            workspace_root=workspace_root,
            sandbox_root=sandbox_root,
            sandbox_policy=sandbox_policy,
            execution_kind="shell",
        )

    def run_python(
        self,
        *,
        code: str,
        workspace_root: str | Path,
        sandbox_root: str | Path,
        sandbox_policy: dict[str, Any] | None,
    ) -> DockerSandboxExecution:
        return self._run(
            command=str(code or ""),
            container_command=("python", "-c", str(code or "")),
            workspace_root=workspace_root,
            sandbox_root=sandbox_root,
            sandbox_policy=sandbox_policy,
            execution_kind="python",
        )

    def build_sbx_create_command(
        self,
        *,
        workspace_root: str | Path,
        sandbox_root: str | Path,
        config: DockerSandboxConfig,
        sandbox_name: str,
    ) -> tuple[str, ...]:
        workspace = Path(workspace_root).resolve()
        sandbox = Path(sandbox_root).resolve()
        if not workspace.exists():
            raise FileNotFoundError("workspace_root does not exist")
        sandbox.mkdir(parents=True, exist_ok=True)
        if _is_inside(workspace, sandbox):
            raise ValueError("workspace_root cannot be inside sandbox_root")
        args: list[str] = [
            config.sbx_executable,
            "create",
            "--quiet",
            "--name",
            sandbox_name,
            "--memory",
            config.memory,
            "--cpus",
            _cpus_as_sbx_value(config.cpus),
        ]
        if config.template:
            args.extend(["--template", config.template])
        args.extend(
            [
                config.sbx_agent,
                _host_path(sandbox),
                f"{_host_path(workspace)}:ro",
            ]
        )
        return tuple(args)

    def build_sbx_exec_command(
        self,
        *,
        container_command: Sequence[str],
        config: DockerSandboxConfig,
        sandbox_name: str,
        sandbox_root: str | Path | None = None,
    ) -> tuple[str, ...]:
        args: list[str] = [
            config.sbx_executable,
            "exec",
        ]
        workdir = _sbx_workdir(config, sandbox_root=sandbox_root)
        if workdir:
            args.extend(["--workdir", workdir])
        for key, value in sorted(config.environment.items()):
            args.extend(["--env", f"{key}={value}"])
        args.append(sandbox_name)
        args.extend(str(item) for item in container_command)
        return tuple(args)

    def _run(
        self,
        *,
        command: str,
        container_command: Sequence[str],
        workspace_root: str | Path,
        sandbox_root: str | Path,
        sandbox_policy: dict[str, Any] | None,
        execution_kind: str,
    ) -> DockerSandboxExecution:
        config = DockerSandboxConfig.from_policy(sandbox_policy)
        run_id = uuid.uuid4().hex[:12]
        sandbox_name = _sandbox_name(config.sbx_name, run_id=run_id)
        create_command = self.build_sbx_create_command(
            workspace_root=workspace_root,
            sandbox_root=sandbox_root,
            config=config,
            sandbox_name=sandbox_name,
        )
        exec_command = self.build_sbx_exec_command(
            container_command=container_command,
            config=config,
            sandbox_name=sandbox_name,
            sandbox_root=sandbox_root,
        )
        try:
            create_result = self._runner(
                list(create_command),
                cwd=str(Path(sandbox_root).resolve()),
                capture_output=True,
                timeout=config.timeout_seconds,
                check=False,
                **utf8_subprocess_text_kwargs(),
            )
            if int(create_result.returncode or 0) not in {0} and _sbx_already_exists(create_result):
                remove_command = self.build_sbx_remove_command(
                    config=config,
                    sandbox_name=sandbox_name,
                )
                remove_result = self._runner(
                    list(remove_command),
                    cwd=str(Path(sandbox_root).resolve()),
                    capture_output=True,
                    timeout=config.timeout_seconds,
                    check=False,
                    **utf8_subprocess_text_kwargs(),
                )
                if int(remove_result.returncode or 0) not in {0}:
                    stdout = (remove_result.stdout or "") + (create_result.stdout or "")
                    stderr = (remove_result.stderr or "") + (create_result.stderr or "")
                    exit_code = int(remove_result.returncode or 0)
                    timed_out = False
                    output = ((stdout or "") + (stderr or "")).strip() or "[no output]"
                    return self._execution_result(
                        command=command,
                        exec_command=exec_command,
                        stdout=stdout,
                        stderr=stderr,
                        exit_code=exit_code,
                        timed_out=timed_out,
                        output=output[: config.output_limit_chars],
                        config=config,
                        run_id=run_id,
                        execution_kind=f"{execution_kind}.create",
                        workspace_root=workspace_root,
                        sandbox_root=sandbox_root,
                        create_command=create_command,
                    )
                create_result = self._runner(
                    list(create_command),
                    cwd=str(Path(sandbox_root).resolve()),
                    capture_output=True,
                    timeout=config.timeout_seconds,
                    check=False,
                    **utf8_subprocess_text_kwargs(),
                )
            if int(create_result.returncode or 0) not in {0}:
                stdout = create_result.stdout or ""
                stderr = create_result.stderr or ""
                exit_code = int(create_result.returncode or 0)
                timed_out = False
                output = ((stdout or "") + (stderr or "")).strip() or "[no output]"
                return self._execution_result(
                    command=command,
                    exec_command=exec_command,
                    stdout=stdout,
                    stderr=stderr,
                    exit_code=exit_code,
                    timed_out=timed_out,
                    output=output[: config.output_limit_chars],
                    config=config,
                    run_id=run_id,
                    execution_kind=f"{execution_kind}.create",
                    workspace_root=workspace_root,
                    sandbox_root=sandbox_root,
                    create_command=create_command,
                )
            completed = self._runner(
                list(exec_command),
                cwd=str(Path(sandbox_root).resolve()),
                capture_output=True,
                timeout=config.timeout_seconds,
                check=False,
                **utf8_subprocess_text_kwargs(),
            )
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            exit_code = _effective_sbx_exit_code(
                returncode=int(completed.returncode or 0),
                stdout=stdout,
                stderr=stderr,
            )
            timed_out = False
        except FileNotFoundError:
            stdout = ""
            stderr = "Docker Sandboxes executable not found."
            exit_code = 127
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            stdout = str(exc.stdout or "")
            stderr = str(exc.stderr or "") or f"Timed out after {config.timeout_seconds} seconds."
            exit_code = 124
            timed_out = True
        output = ((stdout or "") + (stderr or "")).strip() or "[no output]"
        output = _normalize_sbx_output(
            command=command,
            output=output,
            exit_code=exit_code,
            sandbox_root=sandbox_root,
        )
        output = output[: config.output_limit_chars]
        return self._execution_result(
            command=command,
            exec_command=exec_command,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            timed_out=timed_out,
            output=output,
            config=config,
            run_id=run_id,
            execution_kind=execution_kind,
            workspace_root=workspace_root,
            sandbox_root=sandbox_root,
            create_command=create_command,
        )

    def _execution_result(
        self,
        *,
        command: str,
        exec_command: tuple[str, ...],
        stdout: str,
        stderr: str,
        exit_code: int,
        timed_out: bool,
        output: str,
        config: DockerSandboxConfig,
        run_id: str,
        execution_kind: str,
        workspace_root: str | Path,
        sandbox_root: str | Path,
        create_command: tuple[str, ...] = (),
    ) -> DockerSandboxExecution:
        receipt = {
            "backend": self.backend_name,
            "engine": "sbx",
            "execution_kind": execution_kind,
            "template": config.template,
            "run_id": run_id,
            "exit_code": exit_code,
            "passed": exit_code == 0,
            "timed_out": timed_out,
            "workspace_mount": {"source": str(Path(workspace_root).resolve()), "target": "host_path_readonly", "mode": "read_only"},
            "sandbox_mount": {"source": str(Path(sandbox_root).resolve()), "target": "host_path", "mode": "read_write"},
            "network": "sbx_policy",
            "limits": {"memory": config.memory, "cpus": config.cpus, "timeout_seconds": config.timeout_seconds},
            "exec_command": _redacted_command(exec_command),
            "create_command": _redacted_command(create_command),
            "output_preview": output[:500],
        }
        return DockerSandboxExecution(
            command=command,
            exec_command=exec_command,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            timed_out=timed_out,
            output=output,
            receipt=receipt,
        )

    def build_sbx_remove_command(
        self,
        *,
        config: DockerSandboxConfig,
        sandbox_name: str,
    ) -> tuple[str, ...]:
        return (config.sbx_executable, "rm", "--force", sandbox_name)


def _sandbox_name(value: str, *, run_id: str) -> str:
    raw = str(value or "").strip() or f"agent-sandbox-{run_id}"
    safe = "".join(ch.lower() if ch.isalnum() or ch in {"-", "_"} else "-" for ch in raw).strip("-_")
    safe = "-".join(part for part in safe.split("-") if part)
    if len(safe) > 63:
        digest = sha1(raw.encode("utf-8")).hexdigest()[:10]
        safe = f"{safe[:52].strip('-_')}-{digest}".strip("-_")
    return safe or f"agent-sandbox-{run_id}"


def _normalize_shell_command_for_sbx(command: str) -> str:
    text = str(command or "").strip()
    if text == "Get-Location | Select-Object -ExpandProperty Path":
        return "pwd"
    if text.startswith("Get-Item -Path ") and "| Select-Object Name, Length, LastWriteTime" in text:
        path = text.split("Get-Item -Path ", 1)[1].split("|", 1)[0].strip().strip("\"'")
        escaped = path.replace("'", "'\"'\"'")
        return (
            f"if [ -f '{escaped}' ]; then "
            f"size=$(wc -c < '{escaped}' | tr -d ' '); "
            f"mtime=$(stat -c %Y '{escaped}' 2>/dev/null || echo unknown); "
            f"printf 'Name Length LastWriteTime\\n%s %s %s\\n' \"$(basename '{escaped}')\" \"$size\" \"$mtime\"; "
            f"else echo 'missing: {escaped}' >&2; exit 1; fi"
        )
    return text


def _normalize_sbx_output(
    *,
    command: str,
    output: str,
    exit_code: int,
    sandbox_root: str | Path,
) -> str:
    text = _strip_sbx_telemetry_lines(str(output or ""))
    if int(exit_code or 0) == 0 and str(command or "").strip() == "Get-Location | Select-Object -ExpandProperty Path":
        return str(Path(sandbox_root).resolve())
    return text or "[no output]"


def _strip_sbx_telemetry_lines(output: str) -> str:
    lines = []
    for line in str(output or "").splitlines():
        stripped = line.strip()
        if stripped.startswith('{"time":"') and '"upload failed' in stripped and '"level":"WARN"' in stripped:
            continue
        if stripped.startswith("INFO: Started Docker daemon"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _cpus_as_sbx_value(value: str) -> str:
    try:
        parsed = float(str(value or "1").strip())
    except ValueError:
        return "1"
    return str(max(1, int(round(parsed))))


def _sbx_workdir(config: DockerSandboxConfig, *, sandbox_root: str | Path | None = None) -> str:
    if config.workdir:
        return config.workdir
    if sandbox_root is not None:
        return _host_path_to_sbx_mount_path(Path(sandbox_root))
    return ""


def _effective_sbx_exit_code(*, returncode: int, stdout: str, stderr: str) -> int:
    text = f"{stdout or ''}\n{stderr or ''}".lower()
    fatal_markers = (
        "oci runtime exec failed",
        "container not found",
        "sandbox not found",
    )
    if int(returncode or 0) == 0 and any(marker in text for marker in fatal_markers):
        return 1
    return int(returncode or 0)


def _host_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/")


def _host_path_to_sbx_mount_path(path: Path) -> str:
    value = str(path.resolve()).replace("\\", "/")
    if len(value) >= 3 and value[1:3] == ":/":
        return f"/{value[0].lower()}{value[2:]}"
    return value


def _is_inside(path: Path, root: Path) -> bool:
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    return resolved_path == resolved_root or resolved_root in resolved_path.parents


def _redacted_command(command: Sequence[str]) -> list[str]:
    redacted: list[str] = []
    hide_next = False
    for item in command:
        value = str(item)
        if hide_next:
            redacted.append("<redacted>")
            hide_next = False
            continue
        if value == "-e":
            redacted.append(value)
            hide_next = True
            continue
        redacted.append(value)
    return redacted


def _sbx_already_exists(completed: subprocess.CompletedProcess[str]) -> bool:
    text = f"{completed.stdout or ''}\n{completed.stderr or ''}".lower()
    return "already exists" in text or "exists already" in text
