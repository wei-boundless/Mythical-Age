from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from capability_system.tools.authorization import build_tool_authorization_index
from capability_system.tools.native_tool_catalog import build_tool_instances, get_tool_definition_map, get_tool_definitions
from capability_system.tools.native_tool_runtime import ToolRuntime
from harness.runtime.assembly import assemble_runtime
from harness.runtime.dynamic_context.manager import DynamicContextManager
from harness.runtime.dynamic_context.models import DynamicContextInput
from orchestration.runtime_directive import RuntimeDirective
from runtime.memory.file_state_store import FileStateAuthorityStore
from runtime.shared.action_request import RuntimeActionRequest
from runtime.shared.execution_record import RuntimeExecutionStore, build_idempotency_token, build_request_fingerprint
from runtime.tool_runtime.native_tools import build_native_runtime_tool
from runtime.tool_runtime.tool_executor import ToolRuntimeExecutor
from runtime.tool_runtime.tool_use_context import ToolUseContext


def test_read_file_is_native_only_but_model_visible_with_schema() -> None:
    definitions = get_tool_definition_map()
    read_file = definitions["read_file"]

    assert read_file.native_runtime_only is True
    assert read_file.factory is None
    assert all(str(getattr(tool, "name", "") or "") != "read_file" for tool in build_tool_instances(BACKEND_DIR))

    profile = SimpleNamespace(
        agent_profile_id="read-file-authority-agent",
        allowed_operations=("op.model_response", "op.read_file"),
        blocked_operations=(),
        metadata={},
    )
    index = build_tool_authorization_index(get_tool_definitions())
    assembly = assemble_runtime(
        backend_dir=BACKEND_DIR,
        session_id="session-read-file-authority",
        turn_id="turn-read-file-authority",
        agent_invocation_id="agent-invocation-read-file-authority",
        runtime_contract={"task_environment_id": "env.coding.vibe_workspace"},
        model_selection={},
        agent_runtime_profile=profile,
        tool_instances=build_tool_instances(BACKEND_DIR),
        definitions_by_name=index.definitions_by_name,
    ).to_dict()

    tools = {str(item.get("tool_name") or ""): dict(item) for item in list(assembly.get("available_tools") or [])}
    schema = dict(tools["read_file"].get("input_schema") or {})
    properties = dict(schema.get("properties") or {})

    assert "read_file" in tools
    assert schema["required"] == ["path"]
    assert schema["additionalProperties"] is False
    assert set(properties) == {"path", "start_line", "line_count"}
    assert properties["start_line"]["type"] == "integer"
    assert ToolRuntime(BACKEND_DIR).get_instance("read_file") is None
    assert ToolRuntime(BACKEND_DIR).get_definition("read_file") is not None


def test_native_read_file_agent_turn_returns_structured_window_and_events(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("alpha\nbeta\ngamma", encoding="utf-8")
    definition = get_tool_definition_map()["read_file"]
    tool = build_native_runtime_tool(capability_definition=definition)
    assert tool is not None

    envelope = asyncio.run(
        tool.call(
            {"path": "notes.txt", "start_line": 2, "line_count": 1},
            ToolUseContext(
                workspace_root=workspace,
                caller_kind="agent_turn",
                caller_ref="turn:read-file",
                tool_call_id="call:agent-read",
                execution_receipt={
                    "caller_kind": "agent_turn",
                    "caller_ref": "turn:read-file",
                    "tool_call_id": "call:agent-read",
                    "request_ref": "rtact:agent-read",
                },
            ),
        )
    )

    tool_result = envelope.structured_payload["tool_result"]
    event = envelope.file_state_events[0]

    assert envelope.text == "2 | beta"
    assert tool_result["authority"] == "runtime.tool_result.read_file_window.v1"
    assert tool_result["path"] == "notes.txt"
    assert tool_result["content_sha256"]
    assert tool_result["start_line"] == 2
    assert tool_result["end_line"] == 2
    assert tool_result["has_more"] is True
    assert event["event_type"] == "read"
    assert event["path"] == "notes.txt"
    assert event["content_sha256"] == tool_result["content_sha256"]


def test_task_run_read_file_commits_file_state_and_dynamic_context_reads_store(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "src").mkdir()
    (workspace / "src" / "app.py").write_text("line1\nline2\nline3\nline4", encoding="utf-8")
    execution_store = RuntimeExecutionStore(workspace / ".runtime")
    task_run_id = "taskrun:read-file-authority-chain"

    result = _run_read_file(
        workspace=workspace,
        execution_store=execution_store,
        task_run_id=task_run_id,
        tool_args={"path": "src/app.py", "start_line": 1, "line_count": 2},
    )

    envelope = result["observation"].payload["result_envelope"]
    tool_result = envelope["structured_payload"]["tool_result"]
    snapshot = FileStateAuthorityStore(execution_store.root_dir).snapshot(task_run_id)

    assert result["error"] == ""
    assert result["file_state_commit"]["event_count"] == 1
    assert tool_result["path"] == "src/app.py"
    assert envelope["file_state_events"][0]["event_type"] == "read"
    assert snapshot[0]["status"] == "partial"
    assert snapshot[0]["read_ranges"][0]["observation_ref"] == result["observation"].observation_id
    assert snapshot[0]["next_suggested_read"]["start_line"] == 3

    projection = DynamicContextManager(base_dir=workspace).project(
        DynamicContextInput(
            invocation_kind="task_execution",
            session_id="session:read-file-authority-chain",
            task_run_id=task_run_id,
            task_run={"task_run_id": task_run_id},
            execution_state={"system_projection": {"runtime_status": "running"}},
            runtime_assembly={
                "task_environment": {
                    "storage_space": {"runtime_state_root": str(execution_store.root_dir)},
                },
            },
        )
    )
    file_state = projection.volatile_state_projection["task_state"]["file_state"]

    assert file_state[0]["path"] == "src/app.py"
    assert file_state[0]["status"] == "partial"
    assert file_state[0]["next_suggested_read"]["start_line"] == 3

    store = FileStateAuthorityStore(execution_store.root_dir)
    stale = store.apply_events(
        task_run_id,
        [{"event_type": "edit", "path": "src/app.py", "content_sha256": "sha256:after"}],
        observation_ref="obs:edit",
        tool_call_id="call:edit",
    ).projection()[0]

    assert stale["status"] == "stale"
    assert stale["read_ranges"][0]["stale"] is True
    assert stale["write_events"][0]["operation"] == "edit"


def _run_read_file(
    *,
    workspace: Path,
    execution_store: RuntimeExecutionStore,
    task_run_id: str,
    tool_args: dict[str, object],
) -> dict:
    action_request = RuntimeActionRequest(
        request_id="rtact:read-file-authority",
        task_run_id=task_run_id,
        request_type="tool_call",
        step_id="step:read-file-authority",
        directive_ref="rtdir:read-file-authority",
        operation_id="op.read_file",
        payload={
            "tool_name": "read_file",
            "tool_call": {"id": "call:read-file-authority", "name": "read_file", "args": tool_args},
        },
    )
    directive = RuntimeDirective(
        directive_id="rtdir:read-file-authority",
        task_id="task:read-file-authority",
        plan_ref="plan:read-file-authority",
        stage_ref="stage:read-file-authority",
        executor_type="tool",
        adopted_resource_policy_ref="respol:read-file-authority",
        operation_refs=("op.read_file",),
    )
    fingerprint = build_request_fingerprint(
        step_id="step:read-file-authority",
        operation_id="op.read_file",
        payload=action_request.payload,
    )
    record = execution_store.create_record(
        task_run_id=task_run_id,
        step_id="step:read-file-authority",
        action_request=action_request,
        directive_ref=directive.directive_id,
        operation_id="op.read_file",
        executor_type="tool",
        replay_policy="replay_read",
        request_fingerprint=fingerprint,
        idempotency_token=build_idempotency_token(
            task_run_id=task_run_id,
            step_id="step:read-file-authority",
            operation_id="op.read_file",
            request_fingerprint=fingerprint,
        ),
    )
    return asyncio.run(
        ToolRuntimeExecutor(tool_runtime=ToolRuntime(workspace)).run(
            task_run_id=task_run_id,
            action_request=action_request,
            directive=directive,
            execution_record=record,
            execution_store=execution_store,
            sandbox_policy={"workspace_root": str(workspace)},
        )
    )
