from __future__ import annotations

import json
from pathlib import Path

from harness.runtime import (
    RuntimeCompiler,
    RuntimePacketContext,
    build_single_agent_turn_packet_context,
    build_task_execution_packet_context,
    runtime_packet_evidence_projection_event_payload,
    runtime_packet_evidence_projection_ref,
    runtime_packet_evidence_signal_scope,
)
from harness.runtime.single_agent_host import SingleAgentRuntimeHost
from runtime.memory.file_evidence_scope import session_file_evidence_scope, task_run_file_evidence_scope
from runtime.memory.file_state_store import FileStateAuthorityStore
from runtime_objects.read_observation_artifacts import ReadObservationArtifactStore


def test_single_turn_packet_context_owns_action_surface_independent_of_current_work_receipt() -> None:
    context = build_single_agent_turn_packet_context(
        session_id="session:packet-context",
        turn_id="turn:packet-context",
        agent_invocation_id="aginvoke:packet-context",
        user_message="继续。",
        history=[],
        current_work_boundary_receipt={
            "receipt_id": "cwreceipt:unavailable",
            "boundary_decision": "current_work_unavailable",
            "operation_availability": {"active_work_control": False},
        },
        runtime_assembly={
            "profile": {"mode": "conversation"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "control_capabilities": {"may_request_task_run": True, "may_control_active_work": True},
        },
    )

    assert context.authority == "harness.runtime.packet_context"
    assert context.model_action_surface.source_authority == "harness.runtime.packet_assembler.model_action_surface"
    assert context.allowed_action_types == ("respond", "ask_user", "block", "request_task_run", "active_work_control")
    assert context.current_work_boundary_receipt["operation_availability"]["active_work_control"] is False
    assert context.operation_availability["active_work_control"] is False
    assert context.effective_control_capabilities["may_control_active_work"] is True


def test_single_turn_packet_context_adds_tool_call_only_from_runtime_tool_plan() -> None:
    context = build_single_agent_turn_packet_context(
        session_id="session:packet-context-tool",
        turn_id="turn:packet-context-tool",
        agent_invocation_id="aginvoke:packet-context-tool",
        user_message="读文件。",
        history=[],
        runtime_assembly={
            "session_id": "session:packet-context-tool",
            "turn_id": "turn:packet-context-tool",
            "agent_invocation_id": "aginvoke:packet-context-tool",
            "profile": {"mode": "conversation"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "control_capabilities": {"may_request_task_run": True, "may_call_tools": True},
            "available_tools": [{"tool_name": "read_file", "operation_id": "op.read_file"}],
        },
    )

    assert "tool_call" in context.allowed_action_types
    assert [item["tool_name"] for item in context.model_visible_tools] == ["read_file"]
    assert context.tool_plan.diagnostics["visible_tool_count"] == 1


def test_single_turn_packet_context_owns_session_file_evidence_projection(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime_state"
    session_id = "session:packet-context-evidence"
    scope = session_file_evidence_scope(session_id)
    artifact = ReadObservationArtifactStore(runtime_root).write_read_observation(
        task_run_id="",
        scope=scope,
        path="src/app.py",
        text="1 | print('hello')",
        start_line=1,
        end_line=1,
        returned_lines=1,
        line_count=1,
        total_lines=1,
        has_more=False,
        content_sha256="sha256:app",
        tool_call_id="call:read:session",
    )
    FileStateAuthorityStore(runtime_root).apply_events_scope(
        scope,
        [
            {
                "event_type": "read",
                "path": "src/app.py",
                "start_line": 1,
                "end_line": 1,
                "returned_lines": 1,
                "line_count": 1,
                "total_lines": 1,
                "has_more": False,
                "content_sha256": "sha256:app",
                "exact_artifact_ref": artifact["artifact_ref"],
                "artifact_ref_status": "exact",
                "visible_exact": True,
            }
        ],
        observation_ref="obs:read:session",
        tool_call_id="call:read:session",
    )

    context = build_single_agent_turn_packet_context(
        session_id=session_id,
        turn_id="turn:packet-context-evidence",
        agent_invocation_id="aginvoke:packet-context-evidence",
        user_message="继续。",
        history=[],
        base_dir=Path(__file__).resolve().parents[1],
        runtime_assembly={
            "profile": {"mode": "conversation"},
            "task_environment": {
                "environment_id": "env.general.workspace",
                "storage_space": {"runtime_state_root": str(runtime_root)},
            },
            "control_capabilities": {"may_request_task_run": True},
        },
    )

    evidence_ref = context.read_evidence_payload["read_evidence_refs"][0]
    assert context.file_evidence_scope == scope
    assert context.file_state[0]["path"] == "src/app.py"
    assert context.evidence_projection["authority"] == "harness.runtime.packet_assembler.evidence_projection"
    assert context.evidence_projection["file_state_count"] == 1
    assert evidence_ref["artifact_ref"] == artifact["artifact_ref"]
    assert context.read_evidence_payload["visible_exact_in_packet"] is False


def test_runtime_packet_context_diagnostics_redacts_exact_read_evidence() -> None:
    context = RuntimePacketContext(
        invocation_kind="single_agent_turn",
        session_id="session:packet-context-redaction",
        turn_id="turn:packet-context-redaction",
        read_evidence_payload={
            "packet_id": "rtpacket:redaction",
            "read_evidence_injections": [{"path": "secret.txt", "content": "exact secret text"}],
        },
    )

    diagnostics = context.to_dict()
    encoded = json.dumps(diagnostics, ensure_ascii=False)

    assert diagnostics["read_evidence_payload"]["read_evidence_injection_count"] == 1
    assert diagnostics["read_evidence_payload"]["read_evidence_injections_redacted"] is True
    assert "read_evidence_injections" not in diagnostics["read_evidence_payload"]
    assert "exact secret text" not in encoded


def test_packet_evidence_projection_event_payload_is_redacted_and_stable() -> None:
    context = RuntimePacketContext(
        invocation_kind="task_execution",
        session_id="session:packet-context-event",
        task_run_id="taskrun:packet-context-event",
        packet_id="rtpacket:packet-context-event",
        agent_scope={
            "session_id": "session:packet-context-event",
            "agent_run_id": "agentrun:packet-context-event",
            "run_cell_id": "runcell:packet-context-event",
            "task_run_id": "taskrun:packet-context-event",
        },
        file_evidence_scope=task_run_file_evidence_scope(
            "taskrun:packet-context-event",
            session_id="session:packet-context-event",
        ),
        file_state=(
            {
                "path": "secret.txt",
                "status": "fresh",
                "read_ranges": [{"start_line": 1, "end_line": 1, "stale": False}],
                "evidence_refs": ["obs:secret"],
            },
        ),
        read_evidence_payload={
            "packet_id": "rtpacket:packet-context-event",
            "read_evidence_injections": [{"path": "secret.txt", "content": "exact secret text"}],
            "read_evidence_refs": [{"path": "secret.txt", "artifact_ref": "readartifact:secret"}],
        },
        evidence_projection={"file_state_count": 1, "read_evidence_ref_count": 1},
    )

    projection_ref = runtime_packet_evidence_projection_ref(context)
    payload = runtime_packet_evidence_projection_event_payload(context)
    scope = runtime_packet_evidence_signal_scope(context)
    encoded = json.dumps(payload, ensure_ascii=False)

    assert projection_ref == runtime_packet_evidence_projection_ref(context.to_dict())
    assert payload["authority"] == "harness.runtime.packet_context.evidence_projection_event"
    assert payload["file_state_summary"]["files"][0]["path"] == "secret.txt"
    assert payload["read_evidence_payload"]["read_evidence_injection_count"] == 1
    assert payload["read_evidence_payload"]["read_evidence_injections_redacted"] is True
    assert "read_evidence_injections" not in payload["read_evidence_payload"]
    assert "exact secret text" not in encoded
    assert scope.agent_run_id == "agentrun:packet-context-event"
    assert scope.run_cell_id == "runcell:packet-context-event"


def test_runtime_gateway_records_packet_evidence_projection_without_draining_as_control(tmp_path: Path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=tmp_path / "backend")
    context = RuntimePacketContext(
        invocation_kind="single_agent_turn",
        session_id="session:evidence-gateway",
        turn_id="turn:evidence-gateway",
        packet_id="rtpacket:evidence-gateway",
        agent_scope={"session_id": "session:evidence-gateway", "turn_id": "turn:evidence-gateway"},
        read_evidence_payload={
            "packet_id": "rtpacket:evidence-gateway",
            "read_evidence_injections": [{"path": "private.txt", "content": "do not publish"}],
        },
    )
    projection_ref = runtime_packet_evidence_projection_ref(context)
    payload = runtime_packet_evidence_projection_event_payload(context)
    scope = runtime_packet_evidence_signal_scope(context)

    first = host.runtime_gateway.publish_evidence_projection(
        "turnrun:evidence-gateway",
        projection_ref=projection_ref,
        scope=scope,
        payload=payload,
        refs={"runtime_invocation_packet_ref": context.packet_id},
    )
    second = host.runtime_gateway.publish_evidence_projection(
        "turnrun:evidence-gateway",
        projection_ref=projection_ref,
        scope=scope,
        payload=payload,
        refs={"runtime_invocation_packet_ref": context.packet_id},
    )
    events = host.event_log.list_events("turnrun:evidence-gateway")
    encoded = json.dumps([event.to_dict() for event in events], ensure_ascii=False)

    assert first.event_id == second.event_id
    assert [event.event_type for event in events] == ["runtime_evidence_projection_published"]
    assert events[0].refs["evidence_projection_ref"] == projection_ref
    assert "do not publish" not in encoded
    assert host.runtime_gateway.drain("turnrun:evidence-gateway", scope=scope).pending_signals == ()


def test_task_execution_packet_context_owns_task_read_evidence_projection(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime_state"
    session_id = "session:packet-context-task-evidence"
    task_run_id = "taskrun:packet-context-task-evidence"
    scope = task_run_file_evidence_scope(task_run_id, session_id=session_id)
    text = "1 | alpha\n2 | beta"
    artifact = ReadObservationArtifactStore(runtime_root).write_read_observation(
        task_run_id=task_run_id,
        scope=scope,
        path="notes.txt",
        text=text,
        start_line=1,
        end_line=2,
        returned_lines=2,
        line_count=2,
        total_lines=2,
        has_more=False,
        content_sha256="sha256:notes",
        tool_call_id="call:read:task",
    )
    FileStateAuthorityStore(runtime_root).apply_events_scope(
        scope,
        [
            {
                "event_type": "read",
                "path": "notes.txt",
                "start_line": 1,
                "end_line": 2,
                "returned_lines": 2,
                "line_count": 2,
                "total_lines": 2,
                "has_more": False,
                "content_sha256": "sha256:notes",
                "exact_artifact_ref": artifact["artifact_ref"],
                "artifact_ref_status": "exact",
                "visible_exact": True,
            }
        ],
        observation_ref="obs:read:task",
        tool_call_id="call:read:task",
    )
    context = build_task_execution_packet_context(
        session_id=session_id,
        task_run={
            "task_run_id": task_run_id,
            "diagnostics": {
                "executor_epoch": 3,
                "agent_run_scope": {
                    "session_id": session_id,
                    "agent_run_id": "agentrun:packet-context-task-evidence",
                    "run_cell_id": "runcell:packet-context-task-evidence",
                    "task_run_id": task_run_id,
                },
            },
        },
        base_dir=Path(__file__).resolve().parents[1],
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {
                "environment_id": "env.general.workspace",
                "storage_space": {"runtime_state_root": str(runtime_root)},
            },
        },
        available_tools=[{"tool_name": "read_file", "operation_id": "op.read_file"}],
        task_state_payload={"file_state": FileStateAuthorityStore(runtime_root).snapshot_scope(scope)},
        current_observations=[
            {
                "observation_id": "obs:read:task",
                "tool_name": "read_file",
                "status": "ok",
                "structured_payload": {
                    "tool_result": {
                        "path": "notes.txt",
                        "start_line": 1,
                        "end_line": 2,
                        "exact_artifact_ref": artifact["artifact_ref"],
                        "artifact_ref_status": "exact",
                        "visible_exact": True,
                    }
                },
            }
        ],
    )

    injection = context.read_evidence_payload["read_evidence_injections"][0]
    diagnostics = context.to_dict()
    encoded = json.dumps(diagnostics, ensure_ascii=False)

    assert context.packet_id == f"rtpacket:{task_run_id}:task_execution:3:1"
    assert context.allowed_action_types == ("respond", "ask_user", "tool_call", "block")
    assert [item["tool_name"] for item in context.model_visible_tools] == ["read_file"]
    assert context.file_evidence_scope == scope
    assert context.agent_scope["agent_run_id"] == "agentrun:packet-context-task-evidence"
    assert runtime_packet_evidence_signal_scope(context).run_cell_id == "runcell:packet-context-task-evidence"
    assert context.evidence_projection["file_state_count"] == 1
    assert injection["content"] == text
    assert diagnostics["read_evidence_payload"]["read_evidence_injections_redacted"] is True
    assert text not in encoded


def test_compiler_records_packet_context_authority_in_diagnostics() -> None:
    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:packet-context-compiler",
        turn_id="turn:packet-context-compiler",
        agent_invocation_id="aginvoke:packet-context-compiler",
        user_message="继续。",
        history=[],
        runtime_assembly={
            "profile": {"mode": "conversation"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "control_capabilities": {"may_request_task_run": True, "may_control_active_work": True},
        },
    )

    packet_context = result.packet.diagnostics["runtime_packet_context"]
    assert packet_context["authority"] == "harness.runtime.packet_context"
    assert packet_context["model_action_surface"]["source_authority"] == "harness.runtime.packet_assembler.model_action_surface"
    assert result.packet.allowed_action_types == tuple(packet_context["model_action_surface"]["allowed_action_types"])


def test_task_execution_compiler_records_packet_context_authority_in_diagnostics() -> None:
    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:packet-context-task-compiler",
        task_run={"task_run_id": "taskrun:packet-context-task-compiler", "diagnostics": {"executor_epoch": 2}},
        contract={"task_run_goal": "检查 packet context。", "completion_criteria": ["完成检查"]},
        observations=[],
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    packet_context = result.packet.diagnostics["runtime_packet_context"]
    assert packet_context["authority"] == "harness.runtime.packet_context"
    assert packet_context["invocation_kind"] == "task_execution"
    assert packet_context["packet_id"] == result.packet.packet_id
    assert packet_context["task_run_id"] == result.packet.task_run_id
    assert result.packet.allowed_action_types == tuple(packet_context["model_action_surface"]["allowed_action_types"])
