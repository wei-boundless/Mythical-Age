from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from harness.loop.task_executor import _observations_for_packet, _strip_terminal_diagnostics
from tests.support.runtime_stubs import build_harness_runtime


def _runtime_fingerprint(**overrides: str) -> dict[str, str]:
    return {
        "tool_registry_hash": "tools-v1",
        "tool_config_hash": "tool-config-v1",
        "sandbox_policy_hash": "sandbox-v1",
        "permission_policy_hash": "permission-v1",
        "backend_config_hash": "backend-v1",
        **overrides,
    }


def test_task_observation_projection_separates_active_failures_from_stale_runtime_failures() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:test:observation-projection"
    stale_fingerprint = _runtime_fingerprint(tool_config_hash="tool-config-old")
    current_fingerprint = _runtime_fingerprint(tool_config_hash="tool-config-current")

    host.event_log.append(
        task_run_id,
        "task_tool_observation_recorded",
        payload={
            "observation": {
                "observation_id": "obs:stale-image",
                "task_run_id": task_run_id,
                "observation_type": "executor_error",
                "source": "tool:image_generate",
                "payload": {
                    "tool_name": "image_generate",
                    "tool_args": {"prompt": "hero"},
                    "error": "old config failure",
                    "runtime_fingerprint": stale_fingerprint,
                },
                "error": "old config failure",
            }
        },
    )
    host.event_log.append(
        task_run_id,
        "task_tool_observation_recorded",
        payload={
            "observation": {
                "observation_id": "obs:active-read",
                "task_run_id": task_run_id,
                "observation_type": "executor_error",
                "source": "tool:read_file",
                "payload": {
                    "tool_name": "read_file",
                    "tool_args": {"path": "missing.md"},
                    "error": "file missing",
                    "runtime_fingerprint": current_fingerprint,
                },
                "error": "file missing",
            }
        },
    )

    projection = _observations_for_packet(
        host,
        task_run_id,
        current_fingerprint=current_fingerprint,
    )["execution_state"]["system_projection"]

    assert projection["active_failures"][0]["tool_name"] == "read_file"
    assert projection["active_failures"][0]["error"]["message"] == "file missing"
    assert projection["historical_failures"][0]["tool_name"] == "image_generate"
    assert projection["historical_failures"][0]["current_runtime_fact"] is False


def test_task_observation_projection_extracts_structured_errors_and_artifact_evidence() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:test:observation-current-facts"
    fingerprint = _runtime_fingerprint()

    host.event_log.append(
        task_run_id,
        "task_tool_observation_recorded",
        payload={
            "observation": {
                "observation_id": "obs:image-json-error",
                "task_run_id": task_run_id,
                "observation_type": "tool_result",
                "source": "tool:image_generate",
                "payload": {
                    "tool_name": "image_generate",
                    "tool_args": {"prompt": "mine"},
                    "result": json.dumps(
                        {
                            "ok": False,
                            "error": "gateway timeout",
                            "structured_error": {
                                "code": "image_provider_transient_error",
                                "message": "Image API failed with status 504",
                                "retryable": True,
                                "origin": "image_provider",
                            },
                        }
                    ),
                    "runtime_fingerprint": fingerprint,
                },
            }
        },
    )
    host.event_log.append(
        task_run_id,
        "task_tool_observation_recorded",
        payload={
            "observation": {
                "observation_id": "obs:image-ok",
                "task_run_id": task_run_id,
                "observation_type": "tool_result",
                "source": "tool:image_generate",
                "payload": {
                    "tool_name": "image_generate",
                    "runtime_fingerprint": fingerprint,
                    "result_envelope": {
                        "tool_name": "image_generate",
                        "status": "ok",
                        "text": "generated",
                        "artifact_refs": [{"path": "storage/generated/images/hero.png", "kind": "image"}],
                    },
                },
            }
        },
    )

    context = _observations_for_packet(host, task_run_id, current_fingerprint=fingerprint)
    projection = context["execution_state"]["system_projection"]

    assert projection["active_failures"][0]["error"]["code"] == "image_provider_transient_error"
    assert projection["active_failures"][0]["error"]["origin"] == "image_provider"
    assert projection["artifact_evidence"][0]["path"] == "storage/generated/images/hero.png"
    assert context["artifact_refs"][0]["kind"] == "image"


def test_task_observation_projection_treats_missing_fingerprint_as_historical_not_active() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:test:missing-fingerprint"
    host.event_log.append(
        task_run_id,
        "task_tool_observation_recorded",
        payload={
            "observation": {
                "observation_id": "obs:legacy-error",
                "task_run_id": task_run_id,
                "observation_type": "executor_error",
                "source": "tool:image_generate",
                "payload": {
                    "tool_name": "image_generate",
                    "tool_args": {"prompt": "hero"},
                    "error": "legacy failure without runtime fingerprint",
                },
                "error": "legacy failure without runtime fingerprint",
            }
        },
    )

    projection = _observations_for_packet(
        host,
        task_run_id,
        current_fingerprint=_runtime_fingerprint(),
    )["execution_state"]["system_projection"]

    assert projection["active_failures"] == []
    assert projection["historical_failures"][0]["tool_name"] == "image_generate"
    assert projection["historical_failures"][0]["reason"] == "missing_runtime_fingerprint"


def test_task_observation_projection_reports_serial_exploration_as_non_blocking_advisory() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:test:exploration-advisory"
    fingerprint = _runtime_fingerprint()
    tool_calls = [
        ("list_dir", {"path": "."}),
        ("search_text", {"query": "runtime", "roots": ["backend/harness"]}),
        ("glob_paths", {"pattern": "backend/**/*.py"}),
        ("read_file", {"path": "backend/harness/runtime/compiler.py"}),
        ("search_files", {"query": "subagent"}),
        ("read_file", {"path": "backend/harness/loop/task_executor.py"}),
    ]
    for index, (tool_name, tool_args) in enumerate(tool_calls, start=1):
        host.event_log.append(
            task_run_id,
            "task_tool_observation_recorded",
            payload={
                "observation": {
                    "observation_id": f"obs:explore:{index}",
                    "task_run_id": task_run_id,
                    "observation_type": "tool_result",
                    "source": f"tool:{tool_name}",
                    "payload": {
                        "tool_name": tool_name,
                        "tool_args": tool_args,
                        "result": f"{tool_name} ok",
                        "runtime_fingerprint": fingerprint,
                    },
                }
            },
        )

    advisory = _observations_for_packet(
        host,
        task_run_id,
        current_fingerprint=fingerprint,
    )["execution_state"]["system_projection"]["exploration_advisory"]

    assert advisory["triggered"] is True
    assert advisory["non_blocking"] is True
    assert advisory["consecutive_exploration_tool_calls"] == len(tool_calls)
    assert advisory["recent_tools"][-1]["tool_name"] == "read_file"


def test_task_observation_projection_ignores_already_projected_pending_records() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host

    context = _observations_for_packet(
        host,
        "taskrun:test:projected-record",
        current_fingerprint=_runtime_fingerprint(),
        pending_observations=[
            {
                "observation_ref": "rtobs:already-projected",
                "tool_name": "read_file",
                "status": "ok",
                "runtime_freshness": {"visibility": "active"},
                "authority": "orchestration.tool_observation_record",
            }
        ],
    )

    assert context["raw_observations"] == []
    assert context["packet_observations"] == []


def test_terminal_diagnostics_are_stripped_before_task_resume_packet() -> None:
    cleaned = _strip_terminal_diagnostics(
        {
            "contract": {"user_visible_goal": "continue task"},
            "action_request": {"action_type": "block", "blocking_reason": "old blocker"},
            "terminal_reason": "old blocker",
            "recoverable_error": {"detail": "old model error"},
            "recovery_action": "rerun_task_executor",
            "latest_step_summary": "old blocked summary",
        }
    )

    assert cleaned == {"contract": {"user_visible_goal": "continue task"}}
