from __future__ import annotations

import json
from pathlib import Path

from harness.runtime.compiler import RuntimeCompiler
from runtime.memory.file_evidence_scope import task_run_file_evidence_scope
from runtime.memory.file_state_store import FileStateAuthorityStore
from runtime_objects.read_observation_artifacts import ReadObservationArtifactStore


def _payload_after_title(packet, title: str) -> dict[str, object]:
    for message in packet.model_messages:
        content = str(dict(message).get("content") or "")
        if content.startswith(title + "\n"):
            return json.loads(content.split("\n", 1)[1])
    raise AssertionError(f"missing model message title: {title}")


def test_task_execution_compiler_injects_exact_read_observation_text(tmp_path: Path) -> None:
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

    payload = _payload_after_title(result.packet, "Task current exact read evidence")
    injection = payload["read_evidence_injections"][0]

    assert payload["visible_exact_in_packet"] is True
    assert injection["path"] == "notes.txt"
    assert injection["content"] == text
    assert injection["artifact_ref"] == artifact["artifact_ref"]
    assert injection["visible_exact_in_packet"] is True


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
        observations=[],
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
