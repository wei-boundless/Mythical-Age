from __future__ import annotations

import json
from pathlib import Path

from harness.runtime.compiler import RuntimeCompiler
from runtime.memory.file_evidence_scope import session_file_evidence_scope
from runtime.memory.file_state_store import FileStateAuthorityStore
from runtime.prompt_accounting import CanonicalPromptSerializer, PromptCachePlanner


def test_task_execution_emits_evidence_index_cursor_outside_volatile_task_state() -> None:
    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:evidence-index",
        task_run={"task_run_id": "taskrun:evidence-index", "diagnostics": {"executor_status": "running"}},
        contract={"task_run_goal": "fix prompt cache", "completion_criteria": ["cache issue fixed"]},
        observations=[],
        execution_state={
            "system_projection": {
                "runtime_status": "running",
                "file_state_source": "runtime.memory.file_state_store",
                "file_state": [
                    {
                        "path": "src/app.py",
                        "status": "partial",
                        "content_sha256": "sha256:app",
                        "total_lines": 30,
                        "has_more": True,
                        "read_ranges": [
                            {
                                "start_line": 1,
                                "end_line": 10,
                                "observation_ref": "obs:read:1",
                                "exact_artifact_ref": "read_observation:obs-read-1",
                                "artifact_ref_status": "exact",
                                "visible_exact": True,
                            }
                        ],
                        "next_suggested_read": {"path": "src/app.py", "start_line": 11, "line_count": 20},
                    }
                ],
            }
        },
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    kinds = [segment["kind"] for segment in result.packet.segment_plan["segments"]]
    evidence_payload = _payload_with_title(result.packet, "Task execution evidence index cursor")
    current_state_payload = _payload_with_title(result.packet, "Task execution current state")
    bound_runtime_payload = _payload_with_title(result.packet, "Task execution bound runtime context")
    serialized_current_state = json.dumps(current_state_payload, ensure_ascii=False)
    evidence_file = evidence_payload["evidence_index_cursor"]["files"][0]

    assert kinds.index("evidence_index_cursor") < kinds.index("volatile_task_state")
    assert evidence_file["path"] == "src/app.py"
    assert evidence_file["freshness"] == "fresh"
    assert evidence_file["read_window_refs"][0]["exact_artifact_ref"] == "read_observation:obs-read-1"
    assert "file_state" not in serialized_current_state
    assert "file_evidence_decisions" not in serialized_current_state
    assert "read_resource_state" not in serialized_current_state
    assert "evidence_confidence" not in serialized_current_state
    assert bound_runtime_payload["bound_task_runtime_context"]["known_task_files"][0]["path"] == "src/app.py"

    cache_record = _cache_record_for_packet(result.packet)
    assert cache_record.diagnostics["evidence_index_cursor_predicted_tokens"] > 0
    assert cache_record.diagnostics["volatile_task_state_predicted_tokens"] > 0


def test_single_agent_turn_moves_session_file_state_out_of_dynamic_runtime(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime_state"
    session_id = "session:single-turn-evidence-index"
    scope = session_file_evidence_scope(session_id)
    FileStateAuthorityStore(runtime_root).apply_events_scope(
        scope,
        [
            {
                "event_type": "read",
                "path": "src/app.py",
                "start_line": 1,
                "end_line": 20,
                "total_lines": 80,
                "has_more": True,
                "content_sha256": "sha256:single-turn-app",
            }
        ],
        observation_ref="obs:single-turn-read",
        tool_call_id="call:single-turn-read",
    )

    result = RuntimeCompiler(base_dir=tmp_path).compile_single_agent_turn_packet(
        session_id=session_id,
        turn_id="turn:single-turn-evidence-index",
        agent_invocation_id="aginvoke:single-turn-evidence-index",
        user_message="继续。",
        history=[],
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {
                "environment_id": "env.general.workspace",
                "storage_space": {"runtime_state_root": str(runtime_root)},
            },
        },
    )

    kinds = [segment["kind"] for segment in result.packet.segment_plan["segments"]]
    evidence_payload = _payload_with_title(result.packet, "Evidence index cursor")
    dynamic_payload = _optional_payload_with_title(result.packet, "Current Runtime Boundary")
    serialized_dynamic = json.dumps(dynamic_payload, ensure_ascii=False)
    evidence_file = evidence_payload["evidence_index_cursor"]["files"][0]

    if "dynamic_projection" in kinds:
        assert kinds.index("evidence_index_cursor") < kinds.index("dynamic_projection")
    assert evidence_file["path"] == "src/app.py"
    assert evidence_file["read_window_refs"][0]["observation_ref"] == "obs:single-turn-read"
    assert "file_state" not in serialized_dynamic
    assert "file_evidence_decisions" not in serialized_dynamic
    assert "read_resource_state" not in serialized_dynamic


def _payload_with_title(packet, title: str) -> dict[str, object]:
    for message in packet.model_messages:
        content = str(dict(message).get("content") or "")
        if content.startswith(title + "\n"):
            return json.loads(content.split("\n", 1)[1])
    raise AssertionError(f"missing model message title: {title}")


def _optional_payload_with_title(packet, title: str) -> dict[str, object]:
    for message in packet.model_messages:
        content = str(dict(message).get("content") or "")
        if content.startswith(title + "\n"):
            return json.loads(content.split("\n", 1)[1])
    return {}


def _cache_record_for_packet(packet):
    segment_map = CanonicalPromptSerializer().build_segment_map(
        request_id="modelreq:evidence-index",
        messages=packet.model_messages,
        provider="deepseek",
        model="deepseek-v4-pro",
        segment_plan=packet.segment_plan,
    )
    return PromptCachePlanner().plan(segment_map)


