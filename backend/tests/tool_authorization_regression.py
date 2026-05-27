from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from capability_system import build_default_operation_registry
from permissions import OperationGate, ResourcePolicy
from harness.loop.agent_execution import handle_tool_call_requested_event
from harness.runtime.execution_policy import tool_instances_for_policy_and_permit
from runtime.shared.context_manager import RuntimeContextManager
from runtime.shared.event_log import RuntimeEventLog
from runtime.shared.action_request import build_tool_result_observation
from runtime.shared.execution_record import OperationExecutionRecord, RuntimeExecutionStore, build_execution_receipt
from harness.loop.state import HarnessLoopState
from runtime.shared.models import TaskRun
from harness import HarnessServiceHost
from capability_system.tool_authorization import build_authorized_tool_set, build_tool_authorization_index, resolve_tool_operation_id
from capability_system.tool_definitions import build_tool_instances, get_tool_definitions


class _ApprovalToolExecutorStub:
    def __init__(self) -> None:
        self.calls = []

    async def run(
        self,
        *,
        task_run_id,
        action_request,
        directive,
        execution_record,
        execution_store=None,
        max_result_size_chars=0,
        sandbox_policy=None,
        file_management_policy=None,
    ):
        self.calls.append(
            {
                "task_run_id": task_run_id,
                "operation_id": execution_record.operation_id,
                "directive_ref": directive.directive_id,
                "request_ref": action_request.request_id,
                "tool_name": action_request.payload.get("tool_name"),
                "sandbox_policy": dict(sandbox_policy or {}),
                "file_management_policy": dict(file_management_policy or {}),
            }
        )
        final_record = execution_record
        if execution_store is not None and isinstance(execution_record, OperationExecutionRecord):
            dispatched = execution_store.mark_dispatched(execution_record, diagnostics={"test": "approval_resume"})
            final_record = execution_store.mark_completed(
                dispatched,
                result_ref=f"execution-result:{dispatched.execution_id}",
                result_payload={"result": "approved write executed"},
            )
        receipt = build_execution_receipt(final_record).to_dict()
        observation = build_tool_result_observation(
            task_run_id=task_run_id,
            request_ref=action_request.request_id,
            directive_ref=directive.directive_id,
            tool_name=str(action_request.payload.get("tool_name") or ""),
            tool_call_id=str(dict(action_request.payload.get("tool_call") or {}).get("id") or action_request.request_id),
            tool_args=dict(dict(action_request.payload.get("tool_call") or {}).get("args") or {}),
            result="approved write executed",
            execution_receipt=receipt,
            result_ref=receipt.get("result_ref", ""),
        )
        return {"observation": observation, "execution_record": final_record, "error": ""}


def _record_execution_event(event_log: RuntimeEventLog):
    def _record(task_run_id, *, event_type, record, reason="", diagnostics=None):
        return event_log.append(
            task_run_id,
            event_type,
            payload={
                "record": record.to_dict(),
                "reason": reason,
                "diagnostics": dict(diagnostics or {}),
            },
            refs={"execution_ref": record.execution_id},
        )

    return _record


def test_all_builtin_tools_have_explicit_operation_id() -> None:
    definitions = get_tool_definitions()

    assert definitions
    assert all(definition.operation_id.startswith("op.") for definition in definitions)


def test_tool_definition_defaults_are_fail_closed() -> None:
    definition = get_tool_definitions()[0]
    defaulted = type(definition)(
        name="minimal_tool",
        display_name="Minimal Tool",
        operation_id="op.minimal_tool",
        module="tools.minimal",
        factory=definition.factory,
    )

    assert defaulted.safe_for_auto_route is False
    assert defaulted.is_read_only is False
    assert defaulted.is_concurrency_safe is False


def test_tool_operation_resolution_does_not_use_operation_alias_collision() -> None:
    index = build_tool_authorization_index(get_tool_definitions())

    assert resolve_tool_operation_id("read_file", definitions_by_name=index.definitions_by_name) == "op.read_file"
    assert resolve_tool_operation_id("web_search", definitions_by_name=index.definitions_by_name) == "op.web_search"
    assert resolve_tool_operation_id("text_metric", definitions_by_name=index.definitions_by_name) == "op.text_metric"
    assert resolve_tool_operation_id("list_dir", definitions_by_name=index.definitions_by_name) == "op.list_dir"
    assert resolve_tool_operation_id("git_status", definitions_by_name=index.definitions_by_name) == "op.git_status"
    assert resolve_tool_operation_id("index_multimodal_file", definitions_by_name=index.definitions_by_name) == ""


def test_authorized_tool_set_filters_by_explicit_operation_and_main_runtime_visibility() -> None:
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)
    instances = build_tool_instances(Path.cwd())
    authorized = build_authorized_tool_set(
        tool_instances=instances,
        definitions_by_name=index.definitions_by_name,
        allowed_operations={"op.read_file", "op.list_dir", "op.mcp_pdf", "op.shell"},
        runtime_lane="main_runtime",
    )

    assert "read_file" in authorized.tool_names
    assert "list_dir" in authorized.tool_names
    assert "pdf_analysis" not in authorized.tool_names
    assert "terminal" not in authorized.tool_names
    assert "op.read_file" in authorized.operation_ids
    assert any(item["tool_name"] == "terminal" and item["reason"] == "not_main_runtime_visible" for item in authorized.filtered_out)


def test_harness_service_host_tool_filter_uses_tool_definition_operation_id() -> None:
    instances = build_tool_instances(Path.cwd())
    index = build_tool_authorization_index(get_tool_definitions())
    registry = build_default_operation_registry()
    policy = ResourcePolicy(
        policy_id="respol-test",
        task_id="task-test",
        allowed_operations=("op.mcp_pdf",),
        adopted=True,
        runtime_executable=True,
        runtime_view_only=False,
    )

    visible = tool_instances_for_policy_and_permit(
        tool_instances=instances,
        resource_policy=policy,
        definitions_by_name=index.definitions_by_name,
        normalize_operation_id=registry.normalize_id,
    )

    assert visible == []


def test_harness_service_host_tool_filter_uses_execution_permit_as_task_authority() -> None:
    instances = build_tool_instances(Path.cwd())
    index = build_tool_authorization_index(get_tool_definitions())
    registry = build_default_operation_registry()
    policy = ResourcePolicy(
        policy_id="respol-test-permit-authority",
        task_id="task-test",
        allowed_operations=("op.read_file",),
        adopted=True,
        runtime_executable=True,
        runtime_view_only=False,
    )

    visible = tool_instances_for_policy_and_permit(
        tool_instances=instances,
        resource_policy=policy,
        definitions_by_name=index.definitions_by_name,
        normalize_operation_id=registry.normalize_id,
        execution_permit={
            "permit_id": "permit:test",
            "allowed_operations": ["op.browser_control"],
            "visible_tools": ["browser_control"],
            "dispatchable_tools": ["browser_control"],
        },
    )
    names = {getattr(tool, "name", "") for tool in visible}

    assert names == {"browser_control"}


def test_sandbox_does_not_make_hidden_tools_model_visible() -> None:
    instances = build_tool_instances(Path.cwd())
    index = build_tool_authorization_index(get_tool_definitions())
    registry = build_default_operation_registry()
    policy = ResourcePolicy(
        policy_id="respol-test-sandbox-hidden-tools",
        task_id="task-test",
        allowed_operations=("op.read_file", "op.shell", "op.python_repl"),
        adopted=True,
        runtime_executable=True,
        runtime_view_only=False,
    )

    visible = tool_instances_for_policy_and_permit(
        tool_instances=instances,
        resource_policy=policy,
        definitions_by_name=index.definitions_by_name,
        normalize_operation_id=registry.normalize_id,
        sandbox_policy={"enabled": True, "mode": "isolated_workspace"},
        execution_permit={
            "permit_id": "permit:test-sandbox",
            "allowed_operations": ["op.read_file", "op.shell", "op.python_repl"],
            "visible_tools": ["read_file"],
            "dispatchable_tools": ["read_file"],
        },
    )
    names = {getattr(tool, "name", "") for tool in visible}

    assert "read_file" in names
    assert "terminal" not in names
    assert "python_repl" not in names


def test_permit_explicit_visible_hidden_tool_can_be_model_visible() -> None:
    instances = build_tool_instances(Path.cwd())
    index = build_tool_authorization_index(get_tool_definitions())
    registry = build_default_operation_registry()
    policy = ResourcePolicy(
        policy_id="respol-test-permit-hidden-tool",
        task_id="task-test",
        allowed_operations=("op.model_response", "op.shell"),
        adopted=True,
        runtime_executable=True,
        runtime_view_only=False,
    )

    visible = tool_instances_for_policy_and_permit(
        tool_instances=instances,
        resource_policy=policy,
        definitions_by_name=index.definitions_by_name,
        normalize_operation_id=registry.normalize_id,
        execution_permit={
            "permit_id": "permit:test-hidden-terminal",
            "allowed_operations": ["op.model_response", "op.shell"],
            "visible_tools": ["terminal"],
            "dispatchable_tools": ["terminal"],
            "model_visible_tool_refs": ["terminal"],
        },
    )
    names = {getattr(tool, "name", "") for tool in visible}

    assert names == {"terminal"}


def test_harness_service_host_reads_permission_mode_from_provider(tmp_path: Path) -> None:
    loop = HarnessServiceHost(tmp_path / "runtime-loop", permission_mode_provider=lambda: "headless")

    assert loop._current_permission_mode() == "headless"


def test_text_metric_tool_is_schema_visible_as_read_only_operation() -> None:
    definitions = {definition.name: definition for definition in get_tool_definitions()}

    assert definitions["text_metric"].operation_id == "op.text_metric"
    assert definitions["text_metric"].is_read_only is True
    assert definitions["text_metric"].is_destructive is False
    assert definitions["text_metric"].safe_for_auto_route is True


def test_write_and_edit_tools_are_registered_as_main_runtime_schema_tools() -> None:
    definitions = {definition.name: definition for definition in get_tool_definitions()}

    assert definitions["write_file"].operation_id == "op.write_file"
    assert definitions["edit_file"].operation_id == "op.edit_file"
    assert definitions["write_file"].runtime_visibility == "main_runtime"
    assert definitions["edit_file"].runtime_visibility == "main_runtime"
    assert definitions["write_file"].prompt_exposure_policy == "schema_only"
    assert definitions["edit_file"].prompt_exposure_policy == "schema_only"


def test_requires_approval_operations_can_be_schema_visible_before_gate_execution() -> None:
    instances = build_tool_instances(Path.cwd())
    index = build_tool_authorization_index(get_tool_definitions())
    registry = build_default_operation_registry()
    policy = ResourcePolicy(
        policy_id="respol-test-approval-visible",
        task_id="task-test",
        allowed_operations=("op.read_file",),
        requires_approval_operations=("op.write_file", "op.edit_file"),
        adopted=True,
        runtime_executable=True,
        runtime_view_only=False,
    )

    visible = tool_instances_for_policy_and_permit(
        tool_instances=instances,
        resource_policy=policy,
        definitions_by_name=index.definitions_by_name,
        normalize_operation_id=registry.normalize_id,
    )
    names = {getattr(tool, "name", "") for tool in visible}

    assert {"read_file", "write_file", "edit_file"} <= names
    assert "terminal" not in names
    assert "python_repl" not in names


def test_requires_approval_schema_visible_tool_still_needs_gate_approval_token() -> None:
    registry = build_default_operation_registry()
    gate = OperationGate(registry)
    policy = ResourcePolicy(
        policy_id="respol-test-approval-gate",
        task_id="task-test",
        allowed_operations=("op.model_response",),
        requires_approval_operations=("op.write_file",),
        adopted=True,
        runtime_executable=True,
        runtime_view_only=False,
    )

    result = gate.check(
        "op.write_file",
        resource_policy=policy,
        directive_ref="runtime-directive:test:write-file",
    )

    assert result.allowed is False
    assert result.requires_approval is True
    assert result.decision == "requires_approval"


def test_denied_tool_call_gets_synthetic_tool_result(tmp_path: Path) -> None:
    event_log = RuntimeEventLog(tmp_path / "runtime-tool-protocol-deny")
    context_manager = RuntimeContextManager(lambda **_: "base")
    registry = build_default_operation_registry()
    gate = OperationGate(registry)
    policy = ResourcePolicy(
        policy_id="respol-deny-read",
        task_id="task-test",
        allowed_operations=("op.model_response",),
        adopted=True,
        runtime_executable=True,
        runtime_view_only=False,
    )

    import asyncio

    events = asyncio.run(
        handle_tool_call_requested_event(
            event_log=event_log,
            runtime_context_manager=context_manager,
            task_run_id="taskrun:tool-deny",
            event={"type": "tool_call_requested", "tool_call": {"id": "call-read", "name": "read_file", "args": {"path": "a.md"}}},
            current_step_id="step:1",
            task_id="task-test",
            task_operation={},
            adopted_resource_policy=policy,
            user_message="read",
            model_response_executor=None,
            tool_runtime_executor=None,
            definitions_by_name=build_tool_authorization_index(get_tool_definitions()).definitions_by_name,
            operation_gate=gate,
            permission_mode="default",
            root_dir=tmp_path,
            allowed_search_sources=None,
            sandbox_policy={},
            file_management_policy={},
            execution_store=RuntimeExecutionStore(tmp_path / "runtime-tool-protocol-deny"),
            record_execution_event=_record_execution_event(event_log),
            build_pending_approval_state=lambda **_: {},
            list_parent_agent_runs=lambda _task_run_id: [],
            build_delegation_request=lambda **_: None,
            execute_delegation=lambda **_: {},
        )
    )

    event_types = [event.event_type for event in events]
    tool_result = next(event for event in events if event.event_type == "tool_result_received")
    observation_payload = dict(dict(tool_result.payload["observation"]).get("payload") or {})

    assert "tool_call_requested" in event_types
    assert "tool_protocol_guard_synthetic_result" in event_types
    assert observation_payload["tool_call_id"] == "call-read"
    assert observation_payload["result_envelope"]["synthetic_tool_result"] is True
    assert observation_payload["result_envelope"]["status"] == "error"
    gate_event = next(event for event in events if event.event_type == "operation_gate_checked")
    assert gate_event.payload["permission_decision"]["behavior"] == "deny"
    assert gate_event.payload["permission_decision"]["tool_name"] == "read_file"
    assert gate_event.payload["permission_receipt"]["operation_id"] == "op.read_file"
    assert gate_event.payload["tool_supervision"]["authority"] == "runtime.tooling.tool_supervisor"


def test_allowed_tool_without_executor_gets_synthetic_tool_result(tmp_path: Path) -> None:
    event_log = RuntimeEventLog(tmp_path / "runtime-tool-protocol-no-executor")
    context_manager = RuntimeContextManager(lambda **_: "base")
    registry = build_default_operation_registry()
    gate = OperationGate(registry)
    policy = ResourcePolicy(
        policy_id="respol-allow-read",
        task_id="task-test",
        allowed_operations=("op.read_file",),
        adopted=True,
        runtime_executable=True,
        runtime_view_only=False,
    )

    import asyncio

    events = asyncio.run(
        handle_tool_call_requested_event(
            event_log=event_log,
            runtime_context_manager=context_manager,
            task_run_id="taskrun:tool-no-executor",
            event={"type": "tool_call_requested", "tool_call": {"id": "call-read", "name": "read_file", "args": {"path": "a.md"}}},
            current_step_id="step:1",
            task_id="task-test",
            task_operation={},
            adopted_resource_policy=policy,
            user_message="read",
            model_response_executor=None,
            tool_runtime_executor=None,
            definitions_by_name=build_tool_authorization_index(get_tool_definitions()).definitions_by_name,
            operation_gate=gate,
            permission_mode="default",
            root_dir=tmp_path,
            allowed_search_sources=None,
            sandbox_policy={},
            file_management_policy={},
            execution_store=RuntimeExecutionStore(tmp_path / "runtime-tool-protocol-no-executor"),
            record_execution_event=_record_execution_event(event_log),
            build_pending_approval_state=lambda **_: {},
            list_parent_agent_runs=lambda _task_run_id: [],
            build_delegation_request=lambda **_: None,
            execute_delegation=lambda **_: {},
        )
    )

    tool_result = next(event for event in events if event.event_type == "tool_result_received")
    observation_payload = dict(dict(tool_result.payload["observation"]).get("payload") or {})

    assert "Tool runtime executor unavailable" in observation_payload["result"]
    assert observation_payload["tool_call_id"] == "call-read"
    assert observation_payload["result_envelope"]["synthetic_tool_result"] is True


def test_search_policy_blocked_tool_call_gets_tool_result(tmp_path: Path) -> None:
    event_log = RuntimeEventLog(tmp_path / "runtime-tool-protocol-search-policy")
    context_manager = RuntimeContextManager(lambda **_: "base")
    registry = build_default_operation_registry()
    gate = OperationGate(registry)
    policy = ResourcePolicy(
        policy_id="respol-allow-read-search-blocked",
        task_id="task-test",
        allowed_operations=("op.read_file",),
        adopted=True,
        runtime_executable=True,
        runtime_view_only=False,
    )

    import asyncio

    events = asyncio.run(
        handle_tool_call_requested_event(
            event_log=event_log,
            runtime_context_manager=context_manager,
            task_run_id="taskrun:tool-search-policy",
            event={"type": "tool_call_requested", "tool_call": {"id": "call-read", "name": "read_file", "args": {"path": "a.md"}}},
            current_step_id="step:1",
            task_id="task-test",
            task_operation={},
            adopted_resource_policy=policy,
            user_message="read",
            model_response_executor=None,
            tool_runtime_executor=None,
            definitions_by_name=build_tool_authorization_index(get_tool_definitions()).definitions_by_name,
            operation_gate=gate,
            permission_mode="default",
            root_dir=tmp_path,
            allowed_search_sources={"rag"},
            sandbox_policy={},
            file_management_policy={},
            execution_store=RuntimeExecutionStore(tmp_path / "runtime-tool-protocol-search-policy"),
            record_execution_event=_record_execution_event(event_log),
            build_pending_approval_state=lambda **_: {},
            list_parent_agent_runs=lambda _task_run_id: [],
            build_delegation_request=lambda **_: None,
            execute_delegation=lambda **_: {},
        )
    )

    event_types = [event.event_type for event in events]
    tool_result = next(event for event in events if event.event_type == "tool_result_received")
    observation_payload = dict(dict(tool_result.payload["observation"]).get("payload") or {})

    assert "tool_call_blocked_by_search_policy" in event_types
    assert observation_payload["tool_call_id"] == "call-read"
    assert observation_payload["result_envelope"]["synthetic_tool_result"] is True
    assert observation_payload["result_envelope"]["status"] == "error"


def test_harness_service_host_records_waiting_approval_checkpoint(tmp_path: Path) -> None:
    loop = HarnessServiceHost(tmp_path / "runtime-approval")
    task_run = TaskRun(
        task_run_id="taskrun:approval-wait",
        session_id="session-approval",
        task_id="task-approval",
        status="running",
        created_at=1.0,
        updated_at=1.0,
    )
    loop.state_index.upsert_task_run(task_run)

    state, approval_event, checkpoint_event, _ = loop._enter_waiting_approval(
        task_run_id=task_run.task_run_id,
        approval_state={
            "status": "pending",
            "task_run_id": task_run.task_run_id,
            "operation_id": "op.write_file",
            "directive_ref": "runtime-directive:approval:write",
            "action_request_ref": "rtact:approval:write",
            "tool_name": "write_file",
            "tool_args": {"path": "docs/a.md", "content": "hello"},
        },
        current_state=HarnessLoopState(task_run_id=task_run.task_run_id, status="running"),
        current_task_run=task_run,
    )
    stored = loop.state_index.get_task_run(task_run.task_run_id)
    checkpoint = loop.checkpoints.load_latest(task_run.task_run_id)

    assert state.status == "waiting_approval"
    assert state.terminal_reason == "waiting_approval"
    assert approval_event.event_type == "approval_waiting"
    assert checkpoint_event.event_type == "checkpoint_written"
    assert stored is not None
    assert stored.status == "waiting_approval"
    assert stored.terminal_reason == "waiting_approval"
    assert checkpoint is not None
    assert checkpoint.loop_state.pending_approval_state["operation_id"] == "op.write_file"


def test_harness_service_host_rejects_pending_approval_without_executing_tool(tmp_path: Path) -> None:
    loop = HarnessServiceHost(tmp_path / "runtime-approval-reject")
    task_run = TaskRun(
        task_run_id="taskrun:approval-reject",
        session_id="session-approval",
        task_id="task-approval",
        status="running",
        created_at=1.0,
        updated_at=1.0,
    )
    loop.state_index.upsert_task_run(task_run)
    loop._enter_waiting_approval(
        task_run_id=task_run.task_run_id,
        approval_state={
            "status": "pending",
            "task_run_id": task_run.task_run_id,
            "operation_id": "op.write_file",
            "directive_ref": "runtime-directive:approval:write",
            "action_request_ref": "rtact:approval:write",
            "tool_name": "write_file",
            "tool_call_id": "call-write",
            "tool_args": {"path": "docs/a.md", "content": "hello"},
            "directive": {
                "directive_id": "runtime-directive:approval:write",
                "task_id": "task-approval",
                "plan_ref": "orchplan:approval",
                "stage_ref": "orchstage:approval",
                "executor_type": "tool",
                "adopted_resource_policy_ref": "respol:approval",
                "operation_refs": ["op.write_file"],
            },
            "resource_policy": {
                "policy_id": "respol:approval",
                "task_id": "task-approval",
                "requires_approval_operations": ["op.write_file"],
                "adopted": True,
                "runtime_executable": True,
            },
        },
        current_state=HarnessLoopState(task_run_id=task_run.task_run_id, status="running"),
        current_task_run=task_run,
    )

    import asyncio

    result = asyncio.run(
        loop.resolve_pending_approval(
            task_run.task_run_id,
            decision="reject",
            message="not this turn",
        )
    )
    stored = loop.state_index.get_task_run(task_run.task_run_id)
    checkpoint = loop.checkpoints.load_latest(task_run.task_run_id)

    assert result["decision"] == "rejected"
    assert result["resume_result"]["executed"] is False
    assert stored is not None
    assert stored.status == "blocked"
    assert checkpoint is not None
    assert checkpoint.loop_state.pending_approval_state["status"] == "rejected"
    assert loop.execution_store.list_task_run_records(task_run.task_run_id) == []


def test_harness_service_host_approves_pending_approval_with_bound_token_and_gate(tmp_path: Path) -> None:
    loop = HarnessServiceHost(tmp_path / "runtime-approval-approve")
    task_run = TaskRun(
        task_run_id="taskrun:approval-approve",
        session_id="session-approval",
        task_id="task-approval",
        status="running",
        created_at=1.0,
        updated_at=1.0,
    )
    loop.state_index.upsert_task_run(task_run)
    loop._enter_waiting_approval(
        task_run_id=task_run.task_run_id,
        approval_state={
            "status": "pending",
            "task_run_id": task_run.task_run_id,
            "operation_id": "op.write_file",
            "directive_ref": "runtime-directive:approval:write",
            "action_request_ref": "rtact:approval:write",
            "tool_name": "write_file",
            "tool_call_id": "call-write",
            "tool_args": {"path": "docs/a.md", "content": "hello"},
            "directive": {
                "directive_id": "runtime-directive:approval:write",
                "task_id": "task-approval",
                "plan_ref": "orchplan:approval",
                "stage_ref": "orchstage:approval",
                "executor_type": "tool",
                "adopted_resource_policy_ref": "respol:approval",
                "operation_refs": ["op.write_file"],
            },
            "resource_policy": {
                "policy_id": "respol:approval",
                "task_id": "task-approval",
                "requires_approval_operations": ["op.write_file"],
                "adopted": True,
                "runtime_executable": True,
            },
        },
        current_state=HarnessLoopState(task_run_id=task_run.task_run_id, status="running"),
        current_task_run=task_run,
    )

    import asyncio

    executor = _ApprovalToolExecutorStub()
    result = asyncio.run(
        loop.resolve_pending_approval(
            task_run.task_run_id,
            decision="approve",
            message="ok",
            tool_runtime_executor=executor,
        )
    )
    stored = loop.state_index.get_task_run(task_run.task_run_id)
    checkpoint = loop.checkpoints.load_latest(task_run.task_run_id)
    gate = result["resume_result"]["gate"]

    assert result["decision"] == "approved"
    assert result["resume_result"]["executed"] is True
    assert len(executor.calls) == 1
    call = executor.calls[0]
    assert call["task_run_id"] == task_run.task_run_id
    assert call["operation_id"] == "op.write_file"
    assert call["directive_ref"] == "runtime-directive:approval:write"
    assert call["request_ref"] == "rtact:approval:write"
    assert call["tool_name"] == "write_file"
    assert call["sandbox_policy"] == {}
    assert call["file_management_policy"]["approval_token"]["operation_id"] == "op.write_file"
    assert call["file_management_policy"]["approval_token"]["granted"] is True
    assert gate["decision"] == "allow"
    resume_gate_event = next(
        event for event in result["resume_result"]["events"] if event["event_type"] == "operation_gate_checked"
    )
    assert resume_gate_event["payload"]["approval_resume"] is True
    assert resume_gate_event["payload"]["permission_decision"]["behavior"] == "allow"
    assert resume_gate_event["payload"]["permission_receipt"]["operation_id"] == "op.write_file"
    assert (
        resume_gate_event["refs"]["permission_receipt_ref"]
        == resume_gate_event["payload"]["permission_receipt"]["receipt_id"]
    )
    assert resume_gate_event["payload"]["tool_supervision"]["authority"] == "runtime.tooling.tool_supervisor"
    assert stored is not None
    assert stored.status == "completed"
    assert checkpoint is not None
    assert checkpoint.loop_state.pending_approval_state["status"] == "approved"
    token = checkpoint.loop_state.pending_approval_state["approval_token"]
    assert token["operation_id"] == "op.write_file"
    assert token["directive_ref"] == "runtime-directive:approval:write"


