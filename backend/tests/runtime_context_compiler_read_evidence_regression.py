from __future__ import annotations

import json
from pathlib import Path

from harness.runtime.compiler import RuntimeCompiler
from runtime.memory.file_evidence_scope import session_file_evidence_scope, task_run_file_evidence_scope
from runtime.memory.file_state_store import FileStateAuthorityStore
from runtime_objects.read_observation_artifacts import ReadObservationArtifactStore


def _payload_after_title(packet, title: str) -> dict[str, object]:
    for message in packet.model_messages:
        content = str(dict(message).get("content") or "")
        if content.startswith(title + "\n"):
            return json.loads(content.split("\n", 1)[1])
        inner_marker = "\n" + title + "\n"
        if inner_marker in content:
            return json.loads(content.split(inner_marker, 1)[1])
    raise AssertionError(f"missing model message title: {title}")


def test_task_execution_compiler_injects_current_exact_read_observation_text_once(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime_state"
    task_run_id = "taskrun:read-evidence-injection"
    session_id = "session:read-evidence-injection"
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
        tool_call_id="call:read",
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
        observation_ref="obs:read",
        tool_call_id="call:read",
    )

    result = RuntimeCompiler(base_dir=Path(__file__).resolve().parents[1]).compile_task_execution_packet(
        session_id=session_id,
        task_run={"task_run_id": task_run_id, "diagnostics": {"executor_status": "running"}},
        contract={"task_run_goal": "edit notes", "completion_criteria": ["edit notes"]},
        observations=[
            {
                "observation_id": "obs:read",
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
        execution_state={
            "system_projection": {
                "runtime_status": "running",
                "file_state": FileStateAuthorityStore(runtime_root).snapshot_scope(scope),
                "file_state_source": "runtime.memory.file_state_store",
            }
        },
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {
                "environment_id": "env.general.workspace",
                "storage_space": {"runtime_state_root": str(runtime_root)},
            },
        },
    )

    payload = _payload_after_title(result.packet, "Task current exact read evidence")
    injection = payload["read_evidence_injections"][0]

    assert payload["visible_exact_in_packet"] is True
    assert injection["path"] == "notes.txt"
    assert injection["content"] == text
    assert injection["artifact_ref"] == artifact["artifact_ref"]
    assert injection["visible_exact_in_packet"] is True
    assert payload["read_evidence_refs"][0]["artifact_ref"] == artifact["artifact_ref"]


def test_task_execution_read_evidence_uses_evidence_index_for_historical_refs(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime_state"
    task_run_id = "taskrun:read-evidence-history-index"
    session_id = "session:read-evidence-history-index"
    scope = task_run_file_evidence_scope(task_run_id, session_id=session_id)
    artifact = ReadObservationArtifactStore(runtime_root).write_read_observation(
        task_run_id=task_run_id,
        scope=scope,
        path="notes.txt",
        text="1 | alpha\n2 | beta",
        start_line=1,
        end_line=2,
        returned_lines=2,
        line_count=2,
        total_lines=2,
        has_more=False,
        content_sha256="sha256:notes",
        tool_call_id="call:read:historical",
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
        observation_ref="obs:read:historical",
        tool_call_id="call:read:historical",
    )

    result = RuntimeCompiler(base_dir=Path(__file__).resolve().parents[1]).compile_task_execution_packet(
        session_id=session_id,
        task_run={"task_run_id": task_run_id, "diagnostics": {"executor_status": "running"}},
        contract={"task_run_goal": "continue notes", "completion_criteria": ["continue notes"]},
        observations=[],
        execution_state={
            "system_projection": {
                "runtime_status": "running",
                "file_state": FileStateAuthorityStore(runtime_root).snapshot_scope(scope),
                "file_state_source": "runtime.memory.file_state_store",
            }
        },
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {
                "environment_id": "env.general.workspace",
                "storage_space": {"runtime_state_root": str(runtime_root)},
            },
        },
    )

    read_payload = _payload_after_title(result.packet, "Task current exact read evidence")
    evidence_payload = _payload_after_title(result.packet, "Task execution evidence index cursor")
    evidence_file = evidence_payload["evidence_index_cursor"]["files"][0]

    assert read_payload["visible_exact_in_packet"] is False
    assert "read_evidence_refs" not in read_payload
    assert read_payload["projection_policy"]["historical_read_evidence"] == "evidence_index_cursor"
    assert evidence_file["path"] == "notes.txt"
    assert evidence_file["read_window_refs"][0]["exact_artifact_ref"] == artifact["artifact_ref"]


def test_single_agent_turn_compiler_inherits_session_read_evidence_as_ref_only(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime_state"
    session_id = "session:single-turn-read-evidence"
    scope = session_file_evidence_scope(session_id)
    text = "571 | function spawnWave() {\n572 |   spawnEnemy();\n573 | }"
    artifact = ReadObservationArtifactStore(runtime_root).write_read_observation(
        task_run_id="",
        scope=scope,
        path="fps_game.html",
        text=text,
        start_line=571,
        end_line=573,
        returned_lines=3,
        line_count=3,
        total_lines=1200,
        has_more=False,
        content_sha256="sha256:fps",
        tool_call_id="call:read:previous-turn",
    )
    FileStateAuthorityStore(runtime_root).apply_events_scope(
        scope,
        [
            {
                "event_type": "read",
                "path": "fps_game.html",
                "start_line": 571,
                "end_line": 573,
                "returned_lines": 3,
                "line_count": 3,
                "total_lines": 1200,
                "has_more": False,
                "content_sha256": "sha256:fps",
                "exact_artifact_ref": artifact["artifact_ref"],
                "artifact_ref_status": "exact",
                "visible_exact": True,
                "stale": False,
            }
        ],
        observation_ref="obs:read:previous-turn",
        tool_call_id="call:read:previous-turn",
    )

    result = RuntimeCompiler(base_dir=Path(__file__).resolve().parents[1]).compile_single_agent_turn_packet(
        session_id=session_id,
        turn_id="turn:single-turn-read-evidence:followup",
        agent_invocation_id="aginvoke:single-turn-read-evidence:followup",
        user_message="继续刚才的修复。",
        history=[],
        session_context={
            "interrupted_turn_work": {
                "continuation_id": "turncont:previous:21:0",
                "session_id": session_id,
                "turn_run_id": "turnrun:previous",
                "turn_id": "turn:previous",
                "state": "interrupted_continuation_context",
                "interruption_kind": "tool_budget_exhausted",
                "terminal_status": "blocked",
                "terminal_reason": "single_turn_tool_iteration_limit",
                "authority": "harness.continuation.interrupted_turn_record",
            }
        },
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {
                "environment_id": "env.general.workspace",
                "storage_space": {"runtime_state_root": str(runtime_root)},
            },
            "control_capabilities": {"may_request_task_run": True, "may_control_active_work": True},
        },
    )

    evidence_payload = _payload_after_title(result.packet, "Task current exact read evidence")
    evidence_ref = evidence_payload["read_evidence_refs"][0]
    dynamic_payload = _payload_after_title(result.packet, "Single agent turn dynamic runtime")

    assert evidence_payload["visible_exact_in_packet"] is False
    assert "read_evidence_injections" not in evidence_payload
    assert evidence_ref["path"] == "fps_game.html"
    assert evidence_ref["artifact_ref"] == artifact["artifact_ref"]
    assert evidence_ref["content_sha256"] == "sha256:fps"
    assert evidence_payload["projection_policy"]["rehydration"] == "read_again_or_artifact_lookup_when_exact_text_is_needed"
    assert text not in json.dumps(evidence_payload, ensure_ascii=False)
    assert dynamic_payload["interrupted_turn_work"]["turn_run_id"] == "turnrun:previous"
    read_evidence_segment = next(
        segment
        for segment in list(result.packet.segment_plan.get("segments") or [])
        if str(segment.get("kind") or "") == "read_evidence_injection"
    )
    assert read_evidence_segment["cache_role"] == "volatile"


def test_task_execution_compiler_emits_read_required_when_read_artifact_exceeds_budget(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime_state"
    task_run_id = "taskrun:read-evidence-budget"
    session_id = "session:read-evidence-budget"
    scope = task_run_file_evidence_scope(task_run_id, session_id=session_id)
    text = "1 | " + ("x" * 80)
    artifact = ReadObservationArtifactStore(runtime_root).write_read_observation(
        task_run_id=task_run_id,
        scope=scope,
        path="large.txt",
        text=text,
        start_line=1,
        end_line=1,
        returned_lines=1,
        line_count=1,
        total_lines=1,
        has_more=False,
        content_sha256="sha256:large",
        tool_call_id="call:read",
    )
    FileStateAuthorityStore(runtime_root).apply_events_scope(
        scope,
        [
            {
                "event_type": "read",
                "path": "large.txt",
                "start_line": 1,
                "end_line": 1,
                "returned_lines": 1,
                "line_count": 1,
                "total_lines": 1,
                "has_more": False,
                "content_sha256": "sha256:large",
                "exact_artifact_ref": artifact["artifact_ref"],
                "artifact_ref_status": "exact",
                "visible_exact": True,
            }
        ],
        observation_ref="obs:read",
        tool_call_id="call:read",
    )

    result = RuntimeCompiler(base_dir=Path(__file__).resolve().parents[1]).compile_task_execution_packet(
        session_id=session_id,
        task_run={"task_run_id": task_run_id, "diagnostics": {"executor_status": "running"}},
        contract={"task_run_goal": "edit large", "completion_criteria": ["edit large"]},
        observations=[
            {
                "observation_id": "obs:read",
                "tool_name": "read_file",
                "status": "ok",
                "structured_payload": {
                    "tool_result": {
                        "path": "large.txt",
                        "start_line": 1,
                        "end_line": 1,
                        "exact_artifact_ref": artifact["artifact_ref"],
                        "artifact_ref_status": "exact",
                        "visible_exact": True,
                    }
                },
            }
        ],
        execution_state={
            "system_projection": {
                "runtime_status": "running",
                "file_state": FileStateAuthorityStore(runtime_root).snapshot_scope(scope),
                "file_state_source": "runtime.memory.file_state_store",
            }
        },
        model_selection={
            "context_budget_policy": {
                "read_evidence_total_exact_chars": 40,
                "read_evidence_per_window_chars": 40,
            }
        },
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {
                "environment_id": "env.general.workspace",
                "storage_space": {"runtime_state_root": str(runtime_root)},
            },
        },
    )

    payload = _payload_after_title(result.packet, "Task current exact read evidence")
    required = payload["read_required_windows"][0]

    assert payload["visible_exact_in_packet"] is False
    assert "read_evidence_injections" not in payload
    assert required["path"] == "large.txt"
    assert required["reason"] == "budget_exceeded"
    assert required["artifact_ref"] == artifact["artifact_ref"]
