from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from capability_system.tools.native_tool_catalog import get_tool_definition_map
from runtime.tool_runtime.docker_sandbox_backend import (
    DockerSandboxBackend,
    DockerSandboxConfig,
    _host_path_to_sbx_mount_path,
    _sandbox_name,
)
from runtime.tool_runtime.native_tools import build_native_runtime_tool
from runtime.tool_runtime.tool_use_context import ToolUseContext


class RecordingRunner:
    def __init__(self, *, stdout: str = "ok\n", stderr: str = "", returncode: int = 0) -> None:
        self.calls: list[dict] = []
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode

    def __call__(self, args, **kwargs):
        self.calls.append({"args": list(args), "kwargs": dict(kwargs)})
        return subprocess.CompletedProcess(args=list(args), returncode=self.returncode, stdout=self.stdout, stderr=self.stderr)


def test_sbx_backend_builds_create_and_exec_commands(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox = tmp_path / "sandbox" / "workspace"
    workspace.mkdir(parents=True)
    sandbox.mkdir(parents=True)
    backend = DockerSandboxBackend(runner=RecordingRunner())
    config = DockerSandboxConfig.from_policy(
        {
            "execution_backend": "docker_sandboxes",
            "workspace_key": "Task Run: 001",
            "sbx": {
                "executable": "sbx",
                "memory": "1g",
                "cpus": "1",
            },
        }
    )

    create_command = backend.build_sbx_create_command(
        workspace_root=workspace,
        sandbox_root=sandbox,
        config=config,
        sandbox_name="task-run-001",
    )
    exec_command = backend.build_sbx_exec_command(
        container_command=("bash", "-lc", "pytest -q"),
        config=config,
        sandbox_name="task-run-001",
        sandbox_root=sandbox,
    )

    assert create_command[:5] == ("sbx", "create", "--quiet", "--name", "task-run-001")
    assert "--memory" in create_command and create_command[create_command.index("--memory") + 1] == "1g"
    assert "--cpus" in create_command and create_command[create_command.index("--cpus") + 1] == "1"
    assert create_command[-3:] == ("shell", sandbox.as_posix(), f"{workspace.as_posix()}:ro")
    assert exec_command[:2] == ("sbx", "exec")
    assert exec_command[:4] == ("sbx", "exec", "--workdir", _host_path_to_sbx_mount_path(sandbox))
    assert exec_command[-4:] == ("task-run-001", "bash", "-lc", "pytest -q")


def test_sbx_backend_creates_then_executes_sandbox(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox = tmp_path / "sandbox" / "workspace"
    workspace.mkdir(parents=True)
    sandbox.mkdir(parents=True)
    runner = RecordingRunner(stdout="sbx ok\n")
    backend = DockerSandboxBackend(runner=runner)

    result = backend.run_shell(
        command="echo ok",
        workspace_root=workspace,
        sandbox_root=sandbox,
        sandbox_policy={
            "enabled": True,
            "execution_backend": "docker_sandboxes",
            "workspace_key": "unit-sbx",
            "sbx": {
                "executable": "sbx",
                "timeout_seconds": 6,
            },
        },
    )

    assert result.exit_code == 0
    assert result.output == "sbx ok"
    assert result.receipt["backend"] == "docker_sandboxes"
    assert result.receipt["engine"] == "sbx"
    assert result.receipt["network"] == "sbx_policy"
    assert runner.calls[0]["args"][:2] == ["sbx", "create"]
    assert runner.calls[1]["args"][:2] == ["sbx", "exec"]


def test_sbx_backend_recreates_existing_named_sandbox_before_exec(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox = tmp_path / "sandbox" / "workspace"
    workspace.mkdir(parents=True)
    sandbox.mkdir(parents=True)

    class ExistingSandboxRunner:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def __call__(self, args, **kwargs):
            self.calls.append({"args": list(args), "kwargs": dict(kwargs)})
            if len(self.calls) == 1:
                return subprocess.CompletedProcess(
                    args=list(args),
                    returncode=1,
                    stdout="",
                    stderr="sandbox unit-sbx already exists",
                )
            return subprocess.CompletedProcess(args=list(args), returncode=0, stdout="fresh ok\n", stderr="")

    runner = ExistingSandboxRunner()
    backend = DockerSandboxBackend(runner=runner)

    result = backend.run_shell(
        command="pwd",
        workspace_root=workspace,
        sandbox_root=sandbox,
        sandbox_policy={
            "enabled": True,
            "execution_backend": "docker_sandboxes",
            "workspace_key": "unit-sbx",
            "sbx": {
                "executable": "sbx",
                "timeout_seconds": 6,
            },
        },
    )

    assert result.exit_code == 0
    assert result.output == "fresh ok"
    assert [call["args"][:2] for call in runner.calls] == [
        ["sbx", "create"],
        ["sbx", "rm"],
        ["sbx", "create"],
        ["sbx", "exec"],
    ]
    assert runner.calls[1]["args"] == ["sbx", "rm", "--force", "unit-sbx"]


def test_sbx_sandbox_name_is_valid_after_truncating_long_workspace_key() -> None:
    name = _sandbox_name(
        "session-session-professional-verify-gate-get-item-scope-output-vibe-code-smoke",
        run_id="abc123",
    )

    assert len(name) <= 63
    assert name[0].isalnum()
    assert name[-1].isalnum()
    assert all(ch.isalnum() or ch in {"-", "_"} for ch in name)


def test_sbx_backend_reports_missing_sbx_without_host_fallback(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox = tmp_path / "sandbox" / "workspace"
    workspace.mkdir(parents=True)
    sandbox.mkdir(parents=True)

    def missing_runner(*args, **kwargs):
        raise FileNotFoundError("sbx")

    backend = DockerSandboxBackend(runner=missing_runner)

    result = backend.run_shell(
        command="echo should-not-run-on-host",
        workspace_root=workspace,
        sandbox_root=sandbox,
        sandbox_policy={"enabled": True, "execution_backend": "docker_sandboxes"},
    )

    assert result.exit_code == 127
    assert "Docker Sandboxes executable not found" in result.output
    assert result.receipt["backend"] == "docker_sandboxes"
    assert result.receipt["passed"] is False


def test_sbx_backend_treats_oci_exec_failure_as_failed_even_when_sbx_returns_zero(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox = tmp_path / "sandbox" / "workspace"
    workspace.mkdir(parents=True)
    sandbox.mkdir(parents=True)

    class OciFailureRunner:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def __call__(self, args, **kwargs):
            self.calls.append({"args": list(args), "kwargs": dict(kwargs)})
            if len(self.calls) == 1:
                return subprocess.CompletedProcess(args=list(args), returncode=0, stdout="", stderr="")
            return subprocess.CompletedProcess(
                args=list(args),
                returncode=0,
                stdout="",
                stderr="OCI runtime exec failed: chdir to `/workspace`: No such file or directory",
            )

    runner = OciFailureRunner()
    backend = DockerSandboxBackend(runner=runner)

    result = backend.run_shell(
        command="pwd",
        workspace_root=workspace,
        sandbox_root=sandbox,
        sandbox_policy={
            "enabled": True,
            "execution_backend": "docker_sandboxes",
            "workspace_key": "unit-sbx",
            "sbx": {
                "executable": "sbx",
                "workdir": "/workspace",
            },
        },
    )

    assert result.exit_code == 1
    assert result.receipt["passed"] is False
    assert "OCI runtime exec failed" in result.output


def test_native_terminal_uses_sbx_backend_when_policy_selects_sbx(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "project"
    sandbox = tmp_path / "sandbox" / "workspace"
    workspace.mkdir(parents=True)
    sandbox.mkdir(parents=True)

    runner = RecordingRunner(stdout="terminal ok\n")
    monkeypatch.setattr(
        "runtime.tool_runtime.native_tools.DockerSandboxBackend",
        lambda: DockerSandboxBackend(runner=runner),
    )
    tool = build_native_runtime_tool(capability_definition=get_tool_definition_map()["terminal"])

    envelope = _run_native_tool(
        tool,
        {"command": "echo ok"},
        workspace=workspace,
        sandbox=sandbox,
    )

    assert envelope.status == "ok"
    assert envelope.text == "terminal ok"
    assert envelope.command_receipt["backend"] == "docker_sandboxes"
    assert runner.calls[0]["args"][:2] == ["sbx", "create"]
    assert runner.calls[1]["args"][-3:] == ["bash", "-lc", "echo ok"]


def test_native_python_repl_uses_sbx_backend_when_policy_selects_sbx(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "project"
    sandbox = tmp_path / "sandbox" / "workspace"
    workspace.mkdir(parents=True)
    sandbox.mkdir(parents=True)

    runner = RecordingRunner(stdout="python ok\n")
    monkeypatch.setattr(
        "runtime.tool_runtime.native_tools.DockerSandboxBackend",
        lambda: DockerSandboxBackend(runner=runner),
    )
    tool = build_native_runtime_tool(capability_definition=get_tool_definition_map()["python_repl"])

    envelope = _run_native_tool(
        tool,
        {"code": "print('ok')"},
        workspace=workspace,
        sandbox=sandbox,
    )

    assert envelope.status == "ok"
    assert envelope.text == "python ok"
    assert envelope.command_receipt["backend"] == "docker_sandboxes"
    assert runner.calls[1]["args"][-3:] == ["python", "-c", "print('ok')"]


def _run_native_tool(tool, args: dict, *, workspace: Path, sandbox: Path):
    import asyncio

    context = ToolUseContext(
        workspace_root=sandbox,
        sandbox_root=sandbox,
        sandbox_policy={
            "enabled": True,
            "execution_backend": "docker_sandboxes",
            "workspace_root": str(workspace),
            "sandbox_root": str(sandbox),
            "sbx": {"executable": "sbx", "timeout_seconds": 5},
        },
        environment_snapshot={"workspace_root": str(workspace), "sandbox_root": str(sandbox)},
    )
    return asyncio.run(tool.call(args, context))


