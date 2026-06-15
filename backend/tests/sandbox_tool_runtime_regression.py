from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from capability_system.tools.native_tool_catalog import get_tool_definition_map
from capability_system.tools.tool_units.sandbox_command_guard import validate_sandbox_command_text
from capability_system.tools.native_tool_runtime import ToolRuntime
from harness.runtime.sandbox_execution_scope import compile_sandbox_execution_scope
from orchestration.runtime_directive import RuntimeDirective
from runtime.shared.action_request import RuntimeActionRequest
from runtime.shared.execution_record import RuntimeExecutionStore, build_idempotency_token, build_request_fingerprint
from runtime.tool_runtime.tool_executor import ToolRuntimeExecutor


def test_tool_runtime_executor_does_not_depend_on_taskrun_tool_task_control() -> None:
    source = (BACKEND_DIR / "runtime" / "tool_runtime" / "tool_executor.py").read_text(encoding="utf-8")

    assert "attach_tool_task" not in source
    assert "clear_tool_task" not in source
    assert "peek_executor_signal" not in source


def test_write_file_overwrite_intent_fields_are_model_visible(tmp_path: Path) -> None:
    runtime = ToolRuntime(tmp_path)
    definition = runtime.get_definition("write_file")
    tool = runtime.get_instance("write_file")

    assert definition is not None
    assert tool is not None
    assert "allow_overwrite" in definition.contract.optional_inputs
    assert "expected_previous_sha256" in definition.contract.optional_inputs

    schema = tool.args_schema.model_json_schema()
    properties = dict(schema.get("properties") or {})

    assert properties["allow_overwrite"]["type"] == "boolean"
    assert properties["expected_previous_sha256"]["type"] == "string"
    assert "allow_overwrite" not in set(schema.get("required") or [])
    assert "expected_previous_sha256" not in set(schema.get("required") or [])


def test_sandbox_read_file_copies_workspace_file_into_overlay(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox" / "workspace"
    (workspace / "docs").mkdir(parents=True)
    (workspace / "docs" / "note.md").write_text("real content", encoding="utf-8")

    result = _run_tool(
        workspace=workspace,
        sandbox_root=sandbox_root,
        tool_name="read_file",
        tool_args={"path": "docs/note.md"},
        operation_id="op.read_file",
    )

    assert result["error"] == ""
    assert result["observation"].payload["result"] == "1 | real content"
    assert (sandbox_root / "docs" / "note.md").read_text(encoding="utf-8") == "real content"
    assert result["sandbox"]["backend"] == "local_overlay"


def test_sandbox_read_file_accepts_absolute_path_inside_bound_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox" / "workspace"
    (workspace / "docs").mkdir(parents=True)
    source = workspace / "docs" / "note.md"
    source.write_text("absolute content", encoding="utf-8")

    result = _run_tool(
        workspace=workspace,
        sandbox_root=sandbox_root,
        tool_name="read_file",
        tool_args={"path": str(source)},
        operation_id="op.read_file",
    )

    envelope = result["observation"].payload["result_envelope"]

    assert result["error"] == ""
    assert result["observation"].payload["result"] == "1 | absolute content"
    assert (sandbox_root / "docs" / "note.md").read_text(encoding="utf-8") == "absolute content"
    assert envelope["tool_args"]["path"] == "docs/note.md"
    assert envelope["structured_payload"]["tool_result"]["path"] == "docs/note.md"


def test_agent_turn_core_read_file_accepts_absolute_path_inside_bound_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox" / "workspace"
    (workspace / "docs").mkdir(parents=True)
    source = workspace / "docs" / "note.md"
    source.write_text("agent turn absolute content", encoding="utf-8")
    executor = ToolRuntimeExecutor(tool_runtime=ToolRuntime(workspace))

    result = asyncio.run(
        executor.execute_control_plane_request(
            request=SimpleNamespace(
                caller_kind="agent_turn",
                caller_ref="turnrun:absolute",
                session_id="session:absolute",
                turn_id="turn:absolute:1",
                invocation_id="toolinvoke:absolute",
                tool_name="read_file",
                tool_call_id="call:read",
                tool_args={"path": str(source)},
                operation_id="op.read_file",
            ),
            sandbox_policy={
                "enabled": True,
                "mode": "workspace_overlay",
                "sandbox_root": str(sandbox_root),
                "workspace_root": str(workspace),
                "permission_mode": "default",
            },
        )
    )

    assert result["status"] == "ok"
    assert result["text"] == "1 | agent turn absolute content"
    assert result["result_envelope"]["tool_args"]["path"] == "docs/note.md"
    assert (sandbox_root / "docs" / "note.md").read_text(encoding="utf-8") == "agent turn absolute content"


def test_sandbox_search_text_accepts_absolute_root_inside_bound_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox" / "workspace"
    docs = workspace / "docs"
    docs.mkdir(parents=True)
    (docs / "note.md").write_text("alpha\nneedle here\nomega", encoding="utf-8")

    result = _run_tool(
        workspace=workspace,
        sandbox_root=sandbox_root,
        tool_name="search_text",
        tool_args={"query": "needle", "roots": [str(workspace)], "max_results": 10},
        operation_id="op.search_text",
    )

    assert result["error"] == ""
    assert "Search failed: no safe search roots" not in result["observation"].payload["result"]
    assert "docs/note.md" in result["observation"].payload["result"]
    assert "needle here" in result["observation"].payload["result"]


def test_sandbox_search_files_accepts_absolute_root_inside_bound_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox" / "workspace"
    docs = workspace / "docs"
    docs.mkdir(parents=True)
    (docs / "needle-plan.md").write_text("ok", encoding="utf-8")

    result = _run_tool(
        workspace=workspace,
        sandbox_root=sandbox_root,
        tool_name="search_files",
        tool_args={"query": "needle", "roots": [str(workspace)], "max_results": 10},
        operation_id="op.search_files",
    )

    assert result["error"] == ""
    assert "Search failed: no safe search roots" not in result["observation"].payload["result"]
    assert "docs/needle-plan.md" in result["observation"].payload["result"]


def test_sandbox_command_guard_allows_absolute_path_inside_bound_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    outside = tmp_path / "outside"
    workspace.mkdir(parents=True)
    outside.mkdir(parents=True)

    assert validate_sandbox_command_text(f'cd "{workspace}"', kind="command", workspace_root=workspace) == ""
    assert validate_sandbox_command_text(f'cd "{outside}"', kind="command", workspace_root=workspace) == (
        "Blocked: command references an absolute path outside the sandbox workspace."
    )


def test_sandbox_terminal_allows_absolute_path_inside_execution_root(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox" / "workspace"

    result = _run_tool(
        workspace=workspace,
        sandbox_root=sandbox_root,
        tool_name="terminal",
        tool_args={"command": f'cd "{sandbox_root}"; pwd'},
        operation_id="op.shell",
    )

    assert result["error"] == ""
    assert result["execution_record"].status == "completed"
    assert "absolute path outside the sandbox workspace" not in result["observation"].payload["result"]


def test_sandbox_read_file_rejects_absolute_path_outside_bound_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox" / "workspace"
    workspace.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")

    result = _run_tool(
        workspace=workspace,
        sandbox_root=sandbox_root,
        tool_name="read_file",
        tool_args={"path": str(outside)},
        operation_id="op.read_file",
    )

    assert result["error"] == ""
    assert "Path traversal detected" in result["observation"].payload["result"]
    assert not (sandbox_root / "outside.md").exists()


def test_sandbox_read_file_respects_line_window_and_reports_window(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox" / "workspace"
    (workspace / "docs").mkdir(parents=True)
    (workspace / "docs" / "note.md").write_text("line1\nline2\nline3\nline4", encoding="utf-8")

    result = _run_tool(
        workspace=workspace,
        sandbox_root=sandbox_root,
        tool_name="read_file",
        tool_args={"path": "docs/note.md", "start_line": 2, "line_count": 2},
        operation_id="op.read_file",
    )

    envelope = result["observation"].payload["result_envelope"]
    tool_result = envelope["structured_payload"]["tool_result"]

    assert result["error"] == ""
    assert result["observation"].payload["result"] == "2 | line2\n3 | line3"
    assert tool_result["start_line"] == 2
    assert tool_result["end_line"] == 3
    assert tool_result["next_start_line"] == 4
    assert tool_result["line_count"] == 2
    assert tool_result["returned_lines"] == 2
    assert tool_result["total_lines"] == 4
    assert tool_result["has_more"] is True


def test_sandbox_read_file_rejects_unknown_window_arguments(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox" / "workspace"
    (workspace / "docs").mkdir(parents=True)
    (workspace / "docs" / "note.md").write_text("0123456789abcdef", encoding="utf-8")

    result = _run_tool(
        workspace=workspace,
        sandbox_root=sandbox_root,
        tool_name="read_file",
        tool_args={"path": "docs/note.md", "max_chars": 5},
        operation_id="op.read_file",
    )

    observation = result["observation"]

    assert result["execution_record"].status == "failed"
    assert result["recoverable_error"] == "unexpected_tool_inputs"
    assert "max_chars" in observation.payload["result"]
    assert observation.payload["recoverable"] is True
    assert observation.payload["repair_kind"] == "tool_invocation_validation"


def test_sandbox_edit_file_copies_then_edits_overlay_without_touching_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox" / "workspace"
    (workspace / "docs").mkdir(parents=True)
    real_file = workspace / "docs" / "note.md"
    real_file.write_text("hello old", encoding="utf-8")
    task_run_id = "taskrun-sandbox-edit-after-read"

    read = _run_tool(
        workspace=workspace,
        sandbox_root=sandbox_root,
        tool_name="read_file",
        tool_args={"path": "docs/note.md"},
        operation_id="op.read_file",
        task_run_id=task_run_id,
    )
    assert read["error"] == ""

    result = _run_tool(
        workspace=workspace,
        sandbox_root=sandbox_root,
        tool_name="edit_file",
        tool_args={"path": "docs/note.md", "old_text": "old", "new_text": "sandbox"},
        operation_id="op.edit_file",
        task_run_id=task_run_id,
    )

    assert result["error"] == ""
    assert real_file.read_text(encoding="utf-8") == "hello old"
    assert (sandbox_root / "docs" / "note.md").read_text(encoding="utf-8") == "hello sandbox"


def test_sandbox_terminal_blocks_absolute_workspace_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox" / "workspace"
    workspace.mkdir(parents=True)
    outside_path = tmp_path / "outside.txt"

    result = _run_tool(
        workspace=workspace,
        sandbox_root=sandbox_root,
        tool_name="terminal",
        tool_args={"command": f"Get-Content {outside_path}"},
        operation_id="op.shell",
    )

    assert "Blocked:" in result["observation"].payload["result"]


def test_sandbox_python_repl_blocks_absolute_workspace_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox" / "workspace"
    workspace.mkdir(parents=True)
    outside_path = tmp_path / "outside.txt"

    result = _run_tool(
        workspace=workspace,
        sandbox_root=sandbox_root,
        tool_name="python_repl",
        tool_args={"code": f"from pathlib import Path\nprint(Path(r'{outside_path}').read_text())"},
        operation_id="op.python_repl",
    )

    assert "Blocked:" in result["observation"].payload["result"]


def test_sandbox_keeps_image_generate_bound_to_backend_config_root(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox" / "workspace"
    workspace.mkdir(parents=True)
    sandbox_root.mkdir(parents=True)
    (workspace / ".env").write_text("IMAGE_API_KEY=workspace-key\n", encoding="utf-8")
    (sandbox_root / ".env").write_text("IMAGE_API_KEY=sandbox-key\n", encoding="utf-8")

    from capability_system.tools.tool_units.image_generation_tool import ImageGenerationTool

    observed_roots: list[Path] = []

    async def _fake_arun(self, *args, **kwargs):
        observed_roots.append(Path(self._root_dir).resolve())
        return "{\"ok\": true}"

    monkeypatch.setattr(ImageGenerationTool, "_arun", _fake_arun)

    result = _run_tool(
        workspace=workspace,
        sandbox_root=sandbox_root,
        tool_name="image_generate",
        tool_args={"prompt": "test image"},
        operation_id="op.image_generate",
    )

    assert result["error"] == ""
    assert observed_roots == [workspace.resolve()]


def test_image_generate_tool_task_is_cancelled_by_runtime_stop(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox" / "workspace"
    workspace.mkdir(parents=True)
    runtime_host = _ControlRuntimeHost()
    task_run_id = "taskrun-image-control"
    executor_epoch = 7

    from capability_system.tools.tool_units.image_generation_tool import ImageGenerationTool
    from harness.loop.task_run_execution_control import register_executor_epoch, request_executor_stop

    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def _fake_arun(self, *args, **kwargs):
        started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return "{\"ok\": true}"

    monkeypatch.setattr(ImageGenerationTool, "_arun", _fake_arun)
    register_executor_epoch(runtime_host, task_run_id=task_run_id, executor_epoch=executor_epoch)

    async def _run_and_stop() -> dict:
        execution_store = RuntimeExecutionStore(workspace / ".runtime-test")
        action_request, directive = _tool_request_and_directive(
            task_run_id=task_run_id,
            tool_name="image_generate",
            tool_args={"prompt": "slow image"},
            operation_id="op.image_generate",
        )
        fingerprint = build_request_fingerprint(step_id="step:1", operation_id="op.image_generate", payload=action_request.payload)
        record = execution_store.create_record(
            task_run_id=task_run_id,
            step_id="step:1",
            action_request=action_request,
            directive_ref=directive.directive_id,
            operation_id="op.image_generate",
            executor_type="tool",
            replay_policy="deny_auto_replay",
            request_fingerprint=fingerprint,
            idempotency_token=build_idempotency_token(
                task_run_id=task_run_id,
                step_id="step:1",
                operation_id="op.image_generate",
                request_fingerprint=fingerprint,
            ),
        )
        tool_runtime = ToolRuntime(workspace)
        setattr(tool_runtime, "runtime_host", runtime_host)
        task = asyncio.create_task(
            ToolRuntimeExecutor(tool_runtime=tool_runtime).run(
                task_run_id=task_run_id,
                action_request=action_request,
                directive=directive,
                execution_record=record,
                execution_store=execution_store,
                sandbox_policy={
                    "enabled": True,
                    "mode": "workspace_overlay",
                    "sandbox_root": str(sandbox_root),
                    "workspace_root": str(workspace),
                    "executor_epoch": executor_epoch,
                },
            )
        )
        await asyncio.wait_for(started.wait(), timeout=2)
        request_executor_stop(runtime_host, task_run_id=task_run_id, reason="test_stop", requested_by="user")
        result = await asyncio.wait_for(task, timeout=2)
        await asyncio.wait_for(cancelled.wait(), timeout=1)
        return result

    result = asyncio.run(_run_and_stop())

    assert result["error"].startswith("Tool execution interrupted by runtime control: stop")
    assert result["execution_record"].status == "failed"
    assert "Tool execution interrupted by runtime control" in result["observation"].payload["error"]
    assert result["observation"].payload["failure_kind"] == "runtime_control_interrupted"
    assert result["observation"].payload["error_code"] == "runtime_control_stop"
    assert result["observation"].payload["diagnostics"]["runtime_control"]["reason"] == "test_stop"


def test_tool_task_cancelled_without_runtime_signal_is_not_reported_as_runtime_stop(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir(parents=True)

    from capability_system.tools.tool_units.image_generation_tool import ImageGenerationTool

    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def _fake_arun(self, *args, **kwargs):
        started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return "{\"ok\": true}"

    monkeypatch.setattr(ImageGenerationTool, "_arun", _fake_arun)

    async def _run_and_cancel() -> dict:
        execution_store = RuntimeExecutionStore(workspace / ".runtime-test")
        action_request, directive = _tool_request_and_directive(
            task_run_id="taskrun-bare-cancel",
            tool_name="image_generate",
            tool_args={"prompt": "slow image"},
            operation_id="op.image_generate",
        )
        fingerprint = build_request_fingerprint(step_id="step:1", operation_id="op.image_generate", payload=action_request.payload)
        record = execution_store.create_record(
            task_run_id="taskrun-bare-cancel",
            step_id="step:1",
            action_request=action_request,
            directive_ref=directive.directive_id,
            operation_id="op.image_generate",
            executor_type="tool",
            replay_policy="deny_auto_replay",
            request_fingerprint=fingerprint,
            idempotency_token=build_idempotency_token(
                task_run_id="taskrun-bare-cancel",
                step_id="step:1",
                operation_id="op.image_generate",
                request_fingerprint=fingerprint,
            ),
        )
        task = asyncio.create_task(
            ToolRuntimeExecutor(tool_runtime=ToolRuntime(workspace)).run(
                task_run_id="taskrun-bare-cancel",
                action_request=action_request,
                directive=directive,
                execution_record=record,
                execution_store=execution_store,
                sandbox_policy={
                    "enabled": True,
                    "mode": "workspace_overlay",
                    "sandbox_root": str(tmp_path / "sandbox" / "workspace"),
                    "workspace_root": str(workspace),
                },
            )
        )
        await asyncio.wait_for(started.wait(), timeout=2)
        task.cancel()
        result = await asyncio.wait_for(task, timeout=2)
        await asyncio.wait_for(cancelled.wait(), timeout=1)
        return result

    result = asyncio.run(_run_and_cancel())

    assert "runtime control: stop" not in result["observation"].payload["error"]
    assert result["observation"].payload["failure_kind"] == "tool_task_cancelled_without_runtime_control_signal"
    assert result["observation"].payload["error_code"] == "tool_task_cancelled_without_runtime_control_signal"
    assert result["observation"].payload["diagnostics"]["runtime_control"] == {}


def test_terminal_nonzero_exit_returns_structured_failure_feedback(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox" / "workspace"

    result = _run_tool(
        workspace=workspace,
        sandbox_root=sandbox_root,
        tool_name="terminal",
        tool_args={"command": "exit 7"},
        operation_id="op.shell",
    )

    payload = result["observation"].payload
    envelope = payload["result_envelope"]
    structured = envelope["structured_payload"]
    receipt = payload["command_receipt"]

    assert result["error"] == ""
    assert payload["result"].startswith("命令失败:")
    assert receipt["exit_code"] == 7
    assert receipt["passed"] is False
    assert receipt["failure_kind"] == "command_exit_nonzero"
    assert structured["kind"] == "command_execution_error"
    assert structured["failure_kind"] == "command_exit_nonzero"
    assert structured["tool_executed"] is True
    assert "repair_instruction" in structured


def test_terminal_command_snapshot_skips_runtime_private_directories(tmp_path: Path, monkeypatch) -> None:
    from runtime.tool_runtime.native_tools import _capture_command_file_snapshot
    from runtime.tool_runtime.tool_use_context import ToolUseContext

    workspace = tmp_path / "project"
    (workspace / "docs").mkdir(parents=True)
    (workspace / "docs" / "note.md").write_text("public", encoding="utf-8")
    private_events = workspace / "storage" / "runtime_state" / "events"
    private_events.mkdir(parents=True)
    (private_events / "turnrun-secret.jsonl").write_text("secret", encoding="utf-8")

    visited_dirs: list[str] = []
    original_iterdir = Path.iterdir

    def _tracking_iterdir(path: Path):
        try:
            visited_dirs.append(path.resolve().relative_to(workspace.resolve()).as_posix())
        except ValueError:
            pass
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", _tracking_iterdir)

    snapshot = _capture_command_file_snapshot(
        ToolUseContext(workspace_root=workspace),
        force=False,
        command="New-Item -ItemType Directory -Path docs/reviews -Force",
    )

    assert snapshot is not None
    assert "docs/note.md" in snapshot["entries"]
    assert "storage/runtime_state" not in visited_dirs
    assert "storage/runtime_state/events" not in visited_dirs
    assert not any(str(path).startswith("storage/runtime_state/") for path in snapshot["entries"])


def test_python_repl_nonzero_exit_returns_structured_failure_feedback(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox" / "workspace"

    result = _run_tool(
        workspace=workspace,
        sandbox_root=sandbox_root,
        tool_name="python_repl",
        tool_args={"code": "import sys\nsys.exit(9)"},
        operation_id="op.python_repl",
    )

    payload = result["observation"].payload
    envelope = payload["result_envelope"]
    structured = envelope["structured_payload"]
    receipt = payload["command_receipt"]

    assert result["error"] == ""
    assert payload["result"].startswith("命令失败:")
    assert receipt["exit_code"] == 9
    assert receipt["passed"] is False
    assert receipt["failure_kind"] == "command_exit_nonzero"
    assert structured["kind"] == "command_execution_error"
    assert structured["failure_kind"] == "command_exit_nonzero"
    assert structured["tool_name"] == "python_repl"
    assert structured["tool_executed"] is True
    assert structured["command_receipt"]["exit_code"] == 9
    assert "repair_instruction" in structured


def test_image_generate_tool_allows_bounded_agent_retry_on_provider_failure(tmp_path: Path, monkeypatch) -> None:
    from capability_system.tools.tool_units.image_generation_tool import ImageGenerationTool
    from capability_system.capabilities.image_generation.image_asset_service import ImageAssetError, ImageAssetService

    async def _fail_generate(self, **kwargs):
        raise ImageAssetError(
            "provider timed out",
            code="timeout",
            retryable=True,
            attempts=[{"code": "timeout", "retryable": True}],
        )

    monkeypatch.setattr(ImageAssetService, "generate", _fail_generate)

    result = asyncio.run(ImageGenerationTool(tmp_path)._arun(prompt="large image"))
    payload = json.loads(result)
    structured_error = dict(payload["structured_error"])

    assert payload["ok"] is False
    assert structured_error["retryable"] is True
    assert structured_error["provider_retryable"] is True
    assert structured_error["agent_auto_retry_allowed"] is True
    assert structured_error["agent_retry_policy"] == "bounded_retry_with_backoff"
    assert structured_error["max_agent_retry_attempts"] == 2
    assert structured_error["suggested_retry_delay_seconds"] == 15


def test_image_generate_executor_injects_stable_target_and_does_not_overwrite_by_default(tmp_path: Path, monkeypatch) -> None:
    from capability_system.capabilities.image_generation.image_asset_service import ImageAssetService

    workspace = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox" / "workspace"
    workspace.mkdir(parents=True)
    calls: list[dict] = []

    async def _fake_generate(self, **kwargs):
        project_path = f"storage/generated/images/chat-{kwargs['target_id']}.png"
        absolute_path = tmp_path / project_path
        calls.append(dict(kwargs))
        return {
            "asset_path": f"/api/image-assets/files/chat-{kwargs['target_id']}.png",
            "path": project_path,
            "project_path": project_path,
            "file_path": str(absolute_path),
            "absolute_path": str(absolute_path),
            "storage_authority": "image_asset_store",
            "bypass_sandbox_publish": True,
            "bytes": 10,
            "provider_size": "1024x1024",
            "final_size": "1024x1024",
            "duration_ms": 1,
            "model": "gpt-image-2",
        }

    monkeypatch.setattr(ImageAssetService, "generate", _fake_generate)

    result = _run_tool(
        workspace=workspace,
        sandbox_root=sandbox_root,
        tool_name="image_generate",
        tool_args={"prompt": "first"},
        operation_id="op.image_generate",
    )

    assert result["error"] == ""
    assert len(calls) == 1
    assert calls[0]["target_id"].startswith("tool-toolinv-")
    assert calls[0]["overwrite"] is False
    assert result["observation"].payload["tool_args"]["target_id"] == calls[0]["target_id"]
    artifact = result["observation"].payload["artifact_refs"][0]
    assert artifact["path"].startswith("storage/generated/images/chat-tool-toolinv-")
    assert artifact["src"].startswith("/api/image-assets/files/chat-tool-toolinv-")
    assert artifact["storage_authority"] == "image_asset_store"
    assert artifact["bypass_sandbox_publish"] is True
    assert Path(artifact["absolute_path"]).is_absolute()


def test_sandbox_search_uses_real_workspace_view_without_overlay_materialization(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox" / "workspace"
    (workspace / "docs" / "experiments" / "roguelike_long_task").mkdir(parents=True)
    (workspace / "docs" / "experiments" / "roguelike_long_task" / "index.html").write_text("<canvas></canvas>", encoding="utf-8")
    (sandbox_root / "docs" / "experiments" / "roguelike_long_task" / "assets").mkdir(parents=True)
    (sandbox_root / "docs" / "experiments" / "roguelike_long_task" / "assets" / "test.txt").write_text("sandbox only", encoding="utf-8")

    read_result = _run_tool(
        workspace=workspace,
        sandbox_root=sandbox_root,
        tool_name="read_file",
        tool_args={"path": "docs/experiments/roguelike_long_task/index.html"},
        operation_id="op.read_file",
    )
    result = _run_tool(
        workspace=workspace,
        sandbox_root=sandbox_root,
        tool_name="glob_paths",
        tool_args={"pattern": "**/*roguelike*/**/*"},
        operation_id="op.glob_paths",
    )

    payload = result["observation"].payload
    assert read_result["error"] == ""
    assert result["error"] == ""
    assert "docs/experiments/roguelike_long_task/index.html" in payload["result"]
    assert "docs/experiments/roguelike_long_task/assets/test.txt" not in payload["result"]


def test_sandbox_search_text_accepts_paths_and_rejects_files_in_roots(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox" / "workspace"
    (workspace / "docs").mkdir(parents=True)
    (workspace / "docs" / "plan.md").write_text("alpha\nneedle here\nneedle later\nomega", encoding="utf-8")
    (workspace / "docs" / "other.md").write_text("needle elsewhere", encoding="utf-8")

    read_result = _run_tool(
        workspace=workspace,
        sandbox_root=sandbox_root,
        tool_name="read_file",
        tool_args={"path": "docs/plan.md"},
        operation_id="op.read_file",
    )
    result = _run_tool(
        workspace=workspace,
        sandbox_root=sandbox_root,
        tool_name="search_text",
        tool_args={"query": "needle", "paths": ["docs/plan.md"], "max_results": 10},
        operation_id="op.search_text",
    )
    misuse = _run_tool(
        workspace=workspace,
        sandbox_root=sandbox_root,
        tool_name="search_text",
        tool_args={"query": "needle", "roots": ["docs/plan.md"], "max_results": 10},
        operation_id="op.search_text",
    )

    assert read_result["error"] == ""
    assert result["error"] == ""
    assert result["observation"].payload["result"].splitlines() == [
        "docs/plan.md:2:1:needle here",
        "docs/plan.md:3:1:needle later",
    ]
    assert "docs/other.md" not in result["observation"].payload["result"]
    assert misuse["observation"].payload["result_envelope"]["status"] == "error"
    assert "roots accepts directories only" in misuse["observation"].payload["result"]
    assert "paths" in misuse["observation"].payload["result"]


def test_sandbox_terminal_materializes_explicit_directory_before_command(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox" / "workspace"
    asset = workspace / "docs" / "experiments" / "roguelike_long_task" / "assets" / "player.png"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"png")

    result = _run_tool(
        workspace=workspace,
        sandbox_root=sandbox_root,
        tool_name="terminal",
        tool_args={"command": "Test-Path docs/experiments/roguelike_long_task/assets/player.png"},
        operation_id="op.shell",
        sandbox_policy_extra={"materialized_roots": ["docs/experiments/roguelike_long_task"]},
    )

    assert result["error"] == ""
    assert result["observation"].payload["result"] == "True"
    assert (sandbox_root / "docs" / "experiments" / "roguelike_long_task" / "assets" / "player.png").exists()


def test_sandbox_scope_does_not_materialize_contract_or_publish_roots_by_default() -> None:
    scope = compile_sandbox_execution_scope(
        environment_payload={"artifact_policy": {"artifact_root": "environment_scoped_artifacts"}},
        contract={"required_artifacts": [{"path": "docs/experiments/roguelike_long_task/assets/player.png"}]},
        safety_envelope={"default_publish_targets": ["docs/experiments/roguelike_long_task"]},
    )

    assert scope.publish_roots
    assert scope.canonical_output_paths
    assert scope.materialized_roots == ()


def test_sandbox_terminal_does_not_materialize_full_workspace_by_default(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox" / "workspace"
    (workspace / "backend" / "api").mkdir(parents=True)
    (workspace / "backend" / "tests" / "api").mkdir(parents=True)
    (workspace / "backend" / "api" / "chat.py").write_text("CHAT = True\n", encoding="utf-8")
    (workspace / "backend" / "tests" / "api" / "chat_api_regression.py").write_text("TEST = True\n", encoding="utf-8")

    result = _run_tool(
        workspace=workspace,
        sandbox_root=sandbox_root,
        tool_name="terminal",
        tool_args={
            "command": "python -c \"from pathlib import Path; print(Path('backend/api/chat.py').exists()); print(Path('backend/tests/api/chat_api_regression.py').exists())\""
        },
        operation_id="op.shell",
    )

    assert result["error"] == ""
    assert result["observation"].payload["result"].splitlines() == ["False", "False"]
    assert not (sandbox_root / "backend" / "api" / "chat.py").exists()
    assert not (sandbox_root / "backend" / "tests" / "api" / "chat_api_regression.py").exists()


def test_sandbox_terminal_explicit_workspace_materialization_excludes_secrets_git_and_dependency_dirs(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox" / "workspace"
    (workspace / "backend").mkdir(parents=True)
    (workspace / "backend" / "app.py").write_text("APP = True\n", encoding="utf-8")
    (workspace / ".env.production").write_text("SECRET=1\n", encoding="utf-8")
    (workspace / ".git").mkdir(parents=True)
    (workspace / ".git" / "config").write_text("[core]\n", encoding="utf-8")
    (workspace / "node_modules" / "pkg").mkdir(parents=True)
    (workspace / "node_modules" / "pkg" / "index.js").write_text("module.exports = 1\n", encoding="utf-8")

    result = _run_tool(
        workspace=workspace,
        sandbox_root=sandbox_root,
        tool_name="terminal",
        tool_args={
            "command": "python -c \"from pathlib import Path; print(Path('backend/app.py').exists()); print(Path('.env.production').exists()); print(Path('.git/config').exists()); print(Path('node_modules/pkg/index.js').exists())\""
        },
        operation_id="op.shell",
        sandbox_policy_extra={"materialized_roots": ["."]},
    )

    assert result["error"] == ""
    assert result["observation"].payload["result"].splitlines() == ["True", "False", "False", "False"]
    assert (sandbox_root / "backend" / "app.py").exists()
    assert not (sandbox_root / ".env.production").exists()
    assert not (sandbox_root / ".git" / "config").exists()
    assert not (sandbox_root / "node_modules" / "pkg" / "index.js").exists()


def test_sandbox_terminal_explicit_workspace_materialization_excludes_runtime_generated_dirs(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox" / "workspace"
    (workspace / "backend").mkdir(parents=True)
    (workspace / "backend" / "app.py").write_text("APP = True\n", encoding="utf-8")
    (workspace / "storage" / "runtime_state" / "sandboxes" / "old" / "nested").mkdir(parents=True)
    (workspace / "storage" / "runtime_state" / "sandboxes" / "old" / "nested" / "state.json").write_text("{}", encoding="utf-8")
    (workspace / "output" / "sandbox_runs" / "old").mkdir(parents=True)
    (workspace / "output" / "sandbox_runs" / "old" / "artifact.txt").write_text("old", encoding="utf-8")
    (workspace / "storage" / "runtime_cache" / "sandboxes" / "old").mkdir(parents=True)
    (workspace / "storage" / "runtime_cache" / "sandboxes" / "old" / "cache.txt").write_text("cache", encoding="utf-8")
    (workspace / "logs").mkdir(parents=True)
    (workspace / "logs" / "backend.log").write_text("old log", encoding="utf-8")

    result = _run_tool(
        workspace=workspace,
        sandbox_root=sandbox_root,
        tool_name="terminal",
        tool_args={
            "command": "python -c \"from pathlib import Path; print(Path('backend/app.py').exists()); print(Path('storage/runtime_state/sandboxes/old/nested/state.json').exists()); print(Path('storage/runtime_cache/sandboxes/old/cache.txt').exists()); print(Path('output/sandbox_runs/old/artifact.txt').exists()); print(Path('logs/backend.log').exists())\""
        },
        operation_id="op.shell",
        sandbox_policy_extra={"materialized_roots": ["."]},
    )

    assert result["error"] == ""
    assert result["observation"].payload["result"].splitlines() == ["True", "False", "False", "False", "False"]
    assert (sandbox_root / "backend" / "app.py").exists()
    assert not (sandbox_root / "storage" / "runtime_state" / "sandboxes" / "old" / "nested" / "state.json").exists()
    assert not (sandbox_root / "storage" / "runtime_cache" / "sandboxes" / "old" / "cache.txt").exists()
    assert not (sandbox_root / "output" / "sandbox_runs" / "old" / "artifact.txt").exists()
    assert not (sandbox_root / "logs" / "backend.log").exists()


def test_sandbox_terminal_keeps_command_writes_in_sandbox(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox" / "workspace"
    (workspace / "backend").mkdir(parents=True)
    (workspace / "backend" / "app.py").write_text("APP = True\n", encoding="utf-8")

    result = _run_tool(
        workspace=workspace,
        sandbox_root=sandbox_root,
        tool_name="terminal",
        tool_args={
            "command": "python -c \"from pathlib import Path; Path('generated.txt').write_text('sandbox', encoding='utf-8')\""
        },
        operation_id="op.shell",
    )

    assert result["error"] == ""
    assert not (workspace / "generated.txt").exists()
    assert (sandbox_root / "generated.txt").read_text(encoding="utf-8") == "sandbox"


def test_sandbox_terminal_blocks_direct_real_workspace_absolute_path(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox" / "workspace"
    real_file = workspace / "backend" / "app.py"
    real_file.parent.mkdir(parents=True)
    real_file.write_text("APP = True\n", encoding="utf-8")

    result = _run_tool(
        workspace=workspace,
        sandbox_root=sandbox_root,
        tool_name="terminal",
        tool_args={"command": f"Get-Content \"{real_file}\""},
        operation_id="op.shell",
    )

    assert "Blocked: command references an absolute path outside the sandbox workspace." in result["observation"].payload["result"]
    assert real_file.read_text(encoding="utf-8") == "APP = True\n"


def test_full_access_terminal_uses_real_workspace_for_absolute_workspace_paths(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox" / "workspace"
    real_file = workspace / "backend" / "app.py"
    real_file.parent.mkdir(parents=True)
    real_file.write_text("APP = True\n", encoding="utf-8")

    result = _run_tool(
        workspace=workspace,
        sandbox_root=sandbox_root,
        tool_name="terminal",
        tool_args={"command": f"Remove-Item -LiteralPath \"{real_file}\""},
        operation_id="op.shell",
        sandbox_policy_extra={"permission_mode": "full_access"},
    )

    assert result["error"] == ""
    assert result["execution_record"].status == "completed"
    assert "absolute path outside the sandbox workspace" not in result["observation"].payload["result"]
    assert not real_file.exists()


def test_sandbox_terminal_fails_closed_when_sandbox_context_missing(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox" / "workspace"
    workspace.mkdir(parents=True)

    result = _run_tool(
        workspace=workspace,
        sandbox_root=sandbox_root,
        tool_name="terminal",
        tool_args={"command": "New-Item -ItemType File real-workspace-write.txt"},
        operation_id="op.shell",
        sandbox_policy_extra={"overlay_tools": ["read_file"]},
    )

    assert result["execution_record"].status == "failed"
    assert "recoverable_error" in result
    assert "sandbox_context_required_for_side_effect_tool" in result["recoverable_error"]
    assert not (workspace / "real-workspace-write.txt").exists()
    assert result["observation"].payload["structured_payload"]["policy"] == "sandbox_boundary"


def test_sandbox_python_repl_fails_closed_when_sandbox_context_missing(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox" / "workspace"
    workspace.mkdir(parents=True)

    result = _run_tool(
        workspace=workspace,
        sandbox_root=sandbox_root,
        tool_name="python_repl",
        tool_args={"code": "from pathlib import Path\nPath('real-workspace-write.txt').write_text('bad')"},
        operation_id="op.python_repl",
        sandbox_policy_extra={"overlay_tools": ["read_file"]},
    )

    assert result["execution_record"].status == "failed"
    assert "recoverable_error" in result
    assert "sandbox_context_required_for_side_effect_tool" in result["recoverable_error"]
    assert not (workspace / "real-workspace-write.txt").exists()
    assert result["observation"].payload["structured_payload"]["policy"] == "sandbox_boundary"


def test_agent_todo_is_bound_to_runtime_task_scope_even_when_model_sends_defaults(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox" / "workspace"

    result = _run_tool(
        workspace=workspace,
        sandbox_root=sandbox_root,
        tool_name="agent_todo",
        tool_args={
            "operation": "replace",
            "session_id": "default",
            "task_id": "runtime",
            "items": [{"content": "Fix task bug", "status": "in_progress"}],
        },
        operation_id="op.agent_todo",
        sandbox_policy_extra={"session_id": "session-real"},
    )

    payload = result["observation"].payload["result"]
    assert result["execution_record"].status == "completed"
    assert "agent-todo:session-real:taskrun-agent_todo" in payload
    assert "agent-todo:default:runtime" not in payload
    assert (workspace / "storage" / "runtime_state" / "agent_todo" / "session-real__taskrun-agent_todo.json").exists()
    assert not (workspace / "storage" / "runtime_state" / "agent_todo" / "default__runtime.json").exists()


def test_tool_runtime_executor_returns_recoverable_invocation_validation_feedback_before_tool_invocation(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir(parents=True)

    result = _run_tool(
        workspace=workspace,
        sandbox_root=tmp_path / "sandbox" / "workspace",
        tool_name="write_file",
        tool_args={"filepath": "docs/note.md", "content": "hello"},
        operation_id="op.write_file",
    )

    assert result["execution_record"].status == "failed"
    assert "recoverable_error" in result
    assert "error" not in result
    assert result["observation"].observation_type == "tool_result"
    assert result["observation"].needs_model_followup is True
    assert result["observation"].payload["recoverable"] is True
    assert result["observation"].payload["repair_kind"] == "tool_invocation_validation"
    assert result["observation"].payload["missing_inputs"] == ["path"]
    assert result["observation"].payload["required_inputs"] == ["path", "content"]
    assert "Retry the same tool" in result["observation"].payload["result"]


def test_tool_runtime_control_plane_request_preserves_agent_turn_execution_receipt(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox" / "workspace"
    workspace.mkdir(parents=True)
    executor = ToolRuntimeExecutor(tool_runtime=ToolRuntime(workspace))

    result = asyncio.run(
        executor.execute_control_plane_request(
            request=SimpleNamespace(
                caller_kind="agent_turn",
                caller_ref="turnrun:receipt",
                session_id="session:receipt",
                turn_id="turn:receipt:1",
                invocation_id="toolinvoke:receipt",
                tool_name="write_file",
                tool_call_id="call:write",
                tool_args={"path": "artifacts/note.txt", "content": "hello"},
                operation_id="op.write_file",
            ),
            sandbox_policy={
                "enabled": True,
                "mode": "workspace_overlay",
                "sandbox_root": str(sandbox_root),
                "workspace_root": str(workspace),
                "permission_mode": "default",
                "write_scopes": ["artifacts"],
            },
        )
    )

    envelope = result["result_envelope"]
    receipt = envelope["execution_receipt"]

    assert result["status"] == "ok"
    assert (sandbox_root / "artifacts" / "note.txt").read_text(encoding="utf-8") == "hello"
    assert receipt["execution_id"] == "rtcore:toolinvoke:receipt"
    assert receipt["status"] == "completed"
    assert receipt["operation_id"] == "op.write_file"
    assert receipt["caller_kind"] == "agent_turn"
    assert receipt["idempotency_key"]


def test_tool_runtime_control_plane_request_allows_image_generate_fixed_store_without_sandbox_context(tmp_path: Path, monkeypatch) -> None:
    from capability_system.capabilities.image_generation.image_asset_service import ImageAssetService

    workspace = tmp_path / "project"
    workspace.mkdir(parents=True)
    executor = ToolRuntimeExecutor(tool_runtime=ToolRuntime(workspace))

    async def _fake_generate(self, **kwargs):
        project_path = "storage/generated/images/chat-toolinvoke-image.png"
        absolute_path = workspace / project_path
        absolute_path.parent.mkdir(parents=True, exist_ok=True)
        absolute_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        return {
            "asset_path": "/api/image-assets/files/chat-toolinvoke-image.png",
            "path": project_path,
            "project_path": project_path,
            "file_path": str(absolute_path),
            "absolute_path": str(absolute_path),
            "storage_authority": "image_asset_store",
            "bypass_sandbox_publish": True,
            "bytes": absolute_path.stat().st_size,
            "provider_size": "1024x1024",
            "final_size": "1024x1024",
            "duration_ms": 1,
            "model": "gpt-image-2",
        }

    monkeypatch.setattr(ImageAssetService, "generate", _fake_generate)

    result = asyncio.run(
        executor.execute_control_plane_request(
            request=SimpleNamespace(
                caller_kind="agent_turn",
                caller_ref="turnrun:image",
                session_id="session:image",
                turn_id="turn:image:1",
                invocation_id="toolinvoke:image",
                tool_name="image_generate",
                tool_call_id="call:image",
                tool_args={"prompt": "pixel tower"},
                operation_id="op.image_generate",
            ),
            sandbox_policy={
                "enabled": True,
                "side_effect_policy": "sandbox_boundary",
                "side_effect_operations": ["op.image_generate"],
                "permission_mode": "default",
            },
        )
    )

    assert result["status"] == "ok"
    assert "recoverable_error" not in result
    receipt = result["result_envelope"]["execution_receipt"]
    assert receipt["status"] == "completed"
    assert receipt["operation_id"] == "op.image_generate"
    assert receipt["caller_kind"] == "agent_turn"
    artifact = result["artifact_refs"][0]
    assert artifact["path"] == "storage/generated/images/chat-toolinvoke-image.png"
    assert artifact["src"] == "/api/image-assets/files/chat-toolinvoke-image.png"
    assert artifact["storage_authority"] == "image_asset_store"
    assert artifact["bypass_sandbox_publish"] is True


def test_tool_runtime_preflight_rejects_missing_input_before_execution_record(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir(parents=True)
    executor = ToolRuntimeExecutor(tool_runtime=ToolRuntime(workspace))
    action_request, directive = _tool_request_and_directive(
        task_run_id="taskrun-preflight",
        tool_name="write_file",
        tool_args={"filepath": "docs/note.md", "content": "hello"},
        operation_id="op.write_file",
    )

    preflight = executor.preflight_validate(
        task_run_id="taskrun-preflight",
        action_request=action_request,
        directive=directive,
        sandbox_policy={
            "enabled": True,
            "mode": "workspace_overlay",
            "sandbox_root": str(tmp_path / "sandbox" / "workspace"),
            "workspace_root": str(workspace),
        },
    )

    assert preflight["allowed"] is False
    observation = preflight["observation"]
    assert observation.observation_type == "tool_result"
    assert observation.needs_model_followup is True
    assert observation.payload["missing_inputs"] == ["path"]
    assert observation.payload["required_inputs"] == ["path", "content"]


def test_tool_runtime_preflight_rejects_missing_tool_definition(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir(parents=True)
    executor = ToolRuntimeExecutor(tool_runtime=_MissingDefinitionRuntime(workspace))
    action_request, directive = _tool_request_and_directive(
        task_run_id="taskrun-missing-definition",
        tool_name="missing_tool",
        tool_args={},
        operation_id="op.missing_tool",
    )

    preflight = executor.preflight_validate(
        task_run_id="taskrun-missing-definition",
        action_request=action_request,
        directive=directive,
    )

    assert preflight["allowed"] is False
    assert preflight["error"].startswith("tool_not_available")
    observation = preflight["observation"]
    assert observation.observation_type == "tool_result"
    assert observation.needs_model_followup is True
    assert observation.payload["repair_kind"] == "tool_not_available"
    assert observation.payload["structured_payload"]["tool_executed"] is False


def test_tool_runtime_preflight_rejects_unavailable_runtime_tool_instance(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir(parents=True)
    executor = ToolRuntimeExecutor(tool_runtime=_MissingInstanceRuntime(workspace))
    action_request, directive = _tool_request_and_directive(
        task_run_id="taskrun-missing-instance",
        tool_name="agent_todo",
        tool_args={"operation": "list"},
        operation_id="op.agent_todo",
    )

    preflight = executor.preflight_validate(
        task_run_id="taskrun-missing-instance",
        action_request=action_request,
        directive=directive,
        sandbox_policy={"enabled": False},
    )

    assert preflight["allowed"] is False
    assert preflight["error"] == "tool_runtime_unavailable: agent_todo"
    observation = preflight["observation"]
    assert observation.observation_type == "tool_result"
    assert observation.payload["repair_kind"] == "tool_runtime_unavailable"
    assert "agent_todo" in observation.payload["result"]


def test_native_write_file_write_scopes_do_not_restrict_sandbox_root(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox" / "workspace"

    result = _run_tool(
        workspace=workspace,
        sandbox_root=sandbox_root,
        tool_name="write_file",
        tool_args={"path": "private/note.md", "content": "allowed"},
        operation_id="op.write_file",
        sandbox_policy_extra={"write_scopes": ["allowed"]},
    )

    observation = result["observation"]
    assert result["execution_record"].status == "completed"
    assert observation.observation_type == "tool_result"
    assert (sandbox_root / "private" / "note.md").read_text(encoding="utf-8") == "allowed"


def test_native_write_file_default_mode_keeps_file_gateway_approval_as_control_boundary(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox" / "workspace"

    result = _run_tool(
        workspace=workspace,
        sandbox_root=sandbox_root,
        tool_name="write_file",
        tool_args={"path": "docs/needs-approval.md", "content": "blocked"},
        operation_id="op.write_file",
        sandbox_policy_extra={"permission_mode": "default", "write_scopes": ["docs"]},
        file_management_policy={
            "profile_id": "file_profile.managed_project_workspace",
            "repositories": {"write": "repo.managed_project.project_workspace"},
        },
    )

    observation = result["observation"]
    assert result["execution_record"].status == "failed"
    assert result["recoverable_error"] == "file_gateway_approval_required"
    assert observation.payload["structured_payload"]["reason"] == "file_gateway_approval_required"
    assert not (workspace / "docs" / "needs-approval.md").exists()


def test_native_write_file_full_access_satisfies_file_gateway_approval(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox" / "workspace"

    result = _run_tool(
        workspace=workspace,
        sandbox_root=sandbox_root,
        tool_name="write_file",
        tool_args={"path": "docs/full-access.md", "content": "allowed"},
        operation_id="op.write_file",
        sandbox_policy_extra={"permission_mode": "full_access", "write_scopes": ["docs"]},
        file_management_policy={
            "profile_id": "file_profile.managed_project_workspace",
            "repositories": {"write": "repo.managed_project.project_workspace"},
        },
    )

    envelope = result["observation"].payload["result_envelope"]
    receipt = envelope["structured_payload"]["file_gateway"]["receipt"]
    assert result["error"] == ""
    assert (workspace / "docs" / "full-access.md").read_text(encoding="utf-8") == "allowed"
    assert result["execution_record"].status == "completed"
    assert envelope["structured_payload"]["file_gateway"]["access_decision"] == "ask:approved"
    assert receipt["approval_fingerprint"].startswith("runtime-permission:full_access:")


def test_tool_runtime_executor_blocks_operation_mismatch_before_tool_invocation(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox" / "workspace"
    (workspace / "docs").mkdir(parents=True)
    (workspace / "docs" / "note.md").write_text("real content", encoding="utf-8")

    result = _run_tool(
        workspace=workspace,
        sandbox_root=sandbox_root,
        tool_name="read_file",
        tool_args={"path": "docs/note.md"},
        operation_id="op.write_file",
    )

    assert result["execution_record"].status == "failed"
    assert "Tool execution blocked by dispatch guard" in result["error"]
    assert "action_request_operation_mismatch" in result["error"]
    assert "directive_operation_refs_mismatch" in result["error"]
    assert "execution_record_operation_mismatch" in result["error"]
    assert result["observation"].observation_type == "executor_error"


def test_tool_runtime_executor_blocks_tool_call_name_mismatch(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    (workspace / "docs").mkdir(parents=True)
    (workspace / "docs" / "note.md").write_text("real content", encoding="utf-8")

    result = _run_tool(
        workspace=workspace,
        sandbox_root=tmp_path / "sandbox" / "workspace",
        tool_name="read_file",
        tool_args={"path": "docs/note.md"},
        operation_id="op.read_file",
        tool_call_name="write_file",
    )

    assert result["execution_record"].status == "failed"
    assert "Tool execution blocked by dispatch guard" in result["error"]
    assert "tool_call_name_mismatch" in result["error"]


def _run_tool(
    *,
    workspace: Path,
    sandbox_root: Path,
    tool_name: str,
    tool_args: dict[str, str],
    operation_id: str,
    task_run_id: str | None = None,
    tool_call_name: str | None = None,
    runtime_host: object | None = None,
    sandbox_policy_extra: dict | None = None,
    file_management_policy: dict | None = None,
) -> dict:
    workspace.mkdir(parents=True, exist_ok=True)
    sandbox_root.mkdir(parents=True, exist_ok=True)
    task_run_id = task_run_id or f"taskrun-{tool_name}"
    action_request, directive = _tool_request_and_directive(
        task_run_id=task_run_id,
        tool_name=tool_name,
        tool_args=tool_args,
        operation_id=operation_id,
        tool_call_name=tool_call_name,
    )
    execution_store = RuntimeExecutionStore(workspace / ".runtime-test")
    fingerprint = build_request_fingerprint(
        step_id="step:1",
        operation_id=operation_id,
        payload=action_request.payload,
    )
    record = execution_store.create_record(
        task_run_id=task_run_id,
        step_id="step:1",
        action_request=action_request,
        directive_ref=directive.directive_id,
        operation_id=operation_id,
        executor_type="tool",
        replay_policy="deny_auto_replay",
        request_fingerprint=fingerprint,
        idempotency_token=build_idempotency_token(
            task_run_id=task_run_id,
            step_id="step:1",
            operation_id=operation_id,
            request_fingerprint=fingerprint,
        ),
    )
    tool_runtime = ToolRuntime(workspace)
    if runtime_host is not None:
        setattr(tool_runtime, "runtime_host", runtime_host)
    executor = ToolRuntimeExecutor(tool_runtime=tool_runtime)
    return asyncio.run(
        executor.run(
            task_run_id=task_run_id,
            action_request=action_request,
            directive=directive,
            execution_record=record,
            execution_store=execution_store,
            sandbox_policy={
                "enabled": True,
                "mode": "workspace_overlay",
                "sandbox_root": str(sandbox_root),
                "workspace_root": str(workspace),
                **dict(sandbox_policy_extra or {}),
            },
            file_management_policy=dict(file_management_policy or {}),
        )
    )


def _tool_request_and_directive(
    *,
    task_run_id: str,
    tool_name: str,
    tool_args: dict[str, str],
    operation_id: str,
    tool_call_name: str | None = None,
) -> tuple[RuntimeActionRequest, RuntimeDirective]:
    action_request = RuntimeActionRequest(
        request_id=f"rtact:{tool_name}",
        task_run_id=task_run_id,
        request_type="tool_call",
        step_id="step:1",
        directive_ref=f"runtime-directive:{tool_name}",
        operation_id=operation_id,
        payload={
            "tool_name": tool_name,
            "tool_call": {"id": f"call-{tool_name}", "name": tool_call_name or tool_name, "args": tool_args},
        },
    )
    directive = RuntimeDirective(
        directive_id=f"runtime-directive:{tool_name}",
        task_id="task:sandbox-tool-runtime",
        plan_ref="plan:sandbox-tool-runtime",
        stage_ref="stage:sandbox-tool-runtime",
        executor_type="tool",
        adopted_resource_policy_ref="respol:sandbox-tool-runtime",
        operation_refs=(operation_id,),
    )
    return action_request, directive


class _MissingDefinitionRuntime:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir

    def get_definition(self, _name):
        return None


class _MissingInstanceRuntime:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.definition = get_tool_definition_map()["agent_todo"]

    def get_definition(self, name):
        return self.definition if str(name or "").strip() == "agent_todo" else None

    def get_instance(self, _name):
        return None


class _ControlRuntimeHost:
    pass

