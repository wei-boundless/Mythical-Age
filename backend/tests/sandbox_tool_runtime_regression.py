from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from capability_system.tool_runtime import ToolRuntime
from orchestration.runtime_directive import RuntimeDirective
from runtime.shared.action_request import RuntimeActionRequest
from runtime.shared.execution_record import RuntimeExecutionStore, build_idempotency_token, build_request_fingerprint
from runtime.tool_runtime.tool_executor import ToolRuntimeExecutor


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
    assert result["observation"].payload["result"] == "real content"
    assert (sandbox_root / "docs" / "note.md").read_text(encoding="utf-8") == "real content"
    assert result["sandbox"]["backend"] == "local_overlay"


def test_sandbox_edit_file_copies_then_edits_overlay_without_touching_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox" / "workspace"
    (workspace / "docs").mkdir(parents=True)
    real_file = workspace / "docs" / "note.md"
    real_file.write_text("hello old", encoding="utf-8")

    result = _run_tool(
        workspace=workspace,
        sandbox_root=sandbox_root,
        tool_name="edit_file",
        tool_args={"path": "docs/note.md", "old_text": "old", "new_text": "sandbox"},
        operation_id="op.edit_file",
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
    (workspace / ".env").write_text("SOUL_IMAGE_API_KEY=workspace-key\n", encoding="utf-8")
    (sandbox_root / ".env").write_text("SOUL_IMAGE_API_KEY=sandbox-key\n", encoding="utf-8")

    from capability_system.units.tools.image_generation_tool import ImageGenerationTool

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


def test_sandbox_search_uses_overlay_view_after_read_copies_workspace_file(tmp_path: Path) -> None:
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
    assert "docs/experiments/roguelike_long_task/assets/test.txt" in payload["result"]


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


def test_native_write_file_permission_rejection_is_model_visible_tool_result(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox" / "workspace"

    result = _run_tool(
        workspace=workspace,
        sandbox_root=sandbox_root,
        tool_name="write_file",
        tool_args={"path": "private/note.md", "content": "blocked"},
        operation_id="op.write_file",
        sandbox_policy_extra={"write_scopes": ["allowed"]},
    )

    observation = result["observation"]
    assert result["execution_record"].status == "failed"
    assert "recoverable_error" in result
    assert observation.observation_type == "tool_result"
    assert observation.payload["structured_payload"]["type"] == "tool_policy_rejection"
    assert observation.payload["structured_payload"]["policy"] == "tool_permission"
    assert observation.payload["structured_payload"]["reason"] == "path_outside_write_scopes"
    assert observation.payload["structured_payload"]["tool_executed"] is False
    assert observation.payload["structured_payload"]["is_tool_execution_failure"] is False
    assert "No tool side effect occurred" in observation.payload["result"]
    assert observation.needs_model_followup is True


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
    tool_call_name: str | None = None,
    sandbox_policy_extra: dict | None = None,
) -> dict:
    workspace.mkdir(parents=True, exist_ok=True)
    sandbox_root.mkdir(parents=True, exist_ok=True)
    task_run_id = f"taskrun-{tool_name}"
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
    executor = ToolRuntimeExecutor(tool_runtime=ToolRuntime(workspace))
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


