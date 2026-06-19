from __future__ import annotations

import json

from harness.runtime.compiler import RuntimeCompiler
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


def _payload_with_title(packet, title: str) -> dict[str, object]:
    for message in packet.model_messages:
        content = str(dict(message).get("content") or "")
        if content.startswith(title + "\n"):
            return json.loads(content.split("\n", 1)[1])
    raise AssertionError(f"missing model message title: {title}")


def _cache_record_for_packet(packet):
    segment_map = CanonicalPromptSerializer().build_segment_map(
        request_id="modelreq:evidence-index",
        messages=packet.model_messages,
        provider="deepseek",
        model="deepseek-v4-pro",
        segment_plan=packet.segment_plan,
    )
    return PromptCachePlanner().plan(segment_map)
