from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from harness.loop.task_executor import _observations_for_packet, _strip_terminal_diagnostics
from harness.runtime.compiler import _runtime_observations_model_visible_payload
from harness.runtime.dynamic_context.semantic_payload_classifier import pending_tool_control_actions_from_observation
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


def test_subagent_ref_error_result_envelope_reaches_model_visible_observation_projection() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:test:subagent-ref-observation"
    fingerprint = _runtime_fingerprint()
    observation = {
        "observation_id": "obs:subagent-wrong-ref",
        "task_run_id": task_run_id,
        "observation_type": "executor_error",
        "source": "tool:collect_subagent_result",
        "payload": {
            "tool_name": "collect_subagent_result",
            "tool_args": {"subagent_run_ref": "submsg:taskrun:test:abc"},
            "runtime_fingerprint": fingerprint,
            "result_envelope": {
                "tool_name": "collect_subagent_result",
                "status": "error",
                "text": '{"ok": false, "error": "wrong_ref_type_for_collect_subagent_result"}',
                "structured_payload": {
                    "structured_error": {
                        "code": "wrong_ref_type_for_collect_subagent_result",
                        "message": "wrong_ref_type_for_collect_subagent_result",
                        "origin": "subagent_control",
                        "retryable": True,
                        "expected_ref_type": "subagent_run_ref",
                        "expected_prefix": "agrun:",
                        "received_ref_type": "message_ref",
                        "repair_instruction": "subagent_run_ref 必须使用 agrun:...:main；submsg:... 只能放入 since_message_ref。",
                    }
                },
            },
        },
        "needs_model_followup": True,
        "authority": "orchestration.runtime_observation",
    }
    host.event_log.append(
        task_run_id,
        "task_tool_observation_recorded",
        payload={"observation": observation},
    )

    context = _observations_for_packet(host, task_run_id, current_fingerprint=fingerprint)
    active_failure = context["execution_state"]["system_projection"]["active_failures"][0]
    model_visible = _runtime_observations_model_visible_payload([observation])
    model_observation = model_visible["observations"][0]

    assert active_failure["error"]["code"] == "wrong_ref_type_for_collect_subagent_result"
    assert active_failure["error"]["expected_prefix"] == "agrun:"
    assert active_failure["error"]["received_ref_type"] == "message_ref"
    assert "since_message_ref" in active_failure["error"]["repair_instruction"]
    assert model_observation["error_code"] == "wrong_ref_type_for_collect_subagent_result"
    assert model_observation["structured_error"]["origin"] == "subagent_control"
    assert "since_message_ref" in model_observation["repair_instruction"]
    assert model_visible["boundary_code"] == "agent_addressed_runtime_observations"


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
    assert advisory["authority_boundary"] == "observation_pattern_only"
    assert advisory["non_blocking"] is True
    assert advisory["consecutive_exploration_tool_calls"] == len(tool_calls)
    assert advisory["recent_tools"][-1]["tool_name"] == "read_file"
    assert "recommended_action" not in advisory


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


def test_task_observation_projection_preserves_subagent_collect_control_action() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:test:subagent-control-action"
    fingerprint = _runtime_fingerprint()
    subagent_run_ref = "agrun:taskrun:test:subagent-control-action:child"
    result_ref = "rtobj:agent_run_result:projection-child"

    host.event_log.append(
        task_run_id,
        "task_tool_observation_recorded",
        payload={
            "observation": {
                "observation_id": "obs:observe-subagents:completed",
                "task_run_id": task_run_id,
                "observation_type": "tool_result",
                "source": "tool:observe_subagents",
                "payload": {
                    "tool_name": "observe_subagents",
                    "tool_args": {},
                    "runtime_fingerprint": fingerprint,
                    "result_envelope": {
                        "envelope_id": "tool-result:observe-subagents:completed",
                        "tool_name": "observe_subagents",
                        "tool_call_id": "call:observe-subagents",
                        "action_request_id": "act:observe-subagents",
                        "status": "ok",
                        "text": "summary does not own subagent control",
                        "structured_payload": {
                            "subagent_control": {
                                "ok": True,
                                "subagents": [
                                    {
                                        "subagent_run_ref": subagent_run_ref,
                                        "status": "completed",
                                        "result_ref": result_ref,
                                        "result_state": "unread",
                                        "result_unread": True,
                                        "result_available": True,
                                        "result_read_authority": "collect_subagent_result",
                                        "collect_subagent_result_args": {"subagent_run_ref": subagent_run_ref},
                                        "result_ref_usage": "Do not pass result_ref to read_persisted_tool_result.",
                                    }
                                ],
                            }
                        },
                    },
                },
            }
        },
    )

    projection = _observations_for_packet(
        host,
        task_run_id,
        current_fingerprint=fingerprint,
    )["execution_state"]["system_projection"]

    action = projection["pending_tool_control_actions"][0]
    assert action["source_tool"] == "observe_subagents"
    assert action["tool_call_id"] == "call:observe-subagents"
    assert action["action"] == "collect_subagent_result"
    assert action["args"] == {"subagent_run_ref": subagent_run_ref}
    assert action["result_ref"] == result_ref
    assert action["result_state"] == "unread"
    assert action["result_available"] is True
    assert action["result_read_authority"] == "collect_subagent_result"


def test_task_observation_projection_preserves_collected_subagent_final_answer() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:test:subagent-collected-result"
    fingerprint = _runtime_fingerprint()
    final_answer = "CHILD FINAL ANSWER\n" + "important evidence\n" * 80

    host.event_log.append(
        task_run_id,
        "task_tool_observation_recorded",
        payload={
            "observation": {
                "observation_id": "obs:collect-subagent-result",
                "task_run_id": task_run_id,
                "observation_type": "tool_result",
                "source": "tool:collect_subagent_result",
                "payload": {
                    "tool_name": "collect_subagent_result",
                    "tool_args": {"subagent_run_ref": "agrun:taskrun:test:subagent-collected-result:child"},
                    "runtime_fingerprint": fingerprint,
                    "result_envelope": {
                        "envelope_id": "tool-result:collect-subagent-result",
                        "tool_name": "collect_subagent_result",
                        "tool_call_id": "call:collect-subagent-result",
                        "action_request_id": "act:collect-subagent-result",
                        "status": "ok",
                        "text": "short child summary",
                        "structured_payload": {
                            "subagent_control": {
                                "subagent_run_ref": "agrun:taskrun:test:subagent-collected-result:child",
                                "status": "completed",
                                "result_ref": "rtobj:agent_run_result:projection-child",
                                "result_state": "read",
                                "result": {
                                    "result_ref": "rtobj:agent_run_result:projection-child",
                                    "final_answer": final_answer,
                                    "summary": "short child summary",
                                    "evidence_refs": ["backend/harness/loop/task_executor.py:1"],
                                },
                            }
                        },
                    },
                },
            }
        },
    )

    projection = _observations_for_packet(
        host,
        task_run_id,
        current_fingerprint=fingerprint,
    )["execution_state"]["system_projection"]

    subagent_result = projection["authoritative_subagent_results"][0]["subagent_result"]
    assert subagent_result["final_answer"] == final_answer
    assert subagent_result["result_ref"] == "rtobj:agent_run_result:projection-child"
    assert projection["last_action_receipts"][0]["subagent_result"]["final_answer"] == final_answer


def test_pending_tool_control_action_observation_projection_merges_structured_payload_sources() -> None:
    subagent_run_ref = "agrun:taskrun:merged-structured-control:child"
    result_ref = "rtobj:agent_run_result:merged-child"

    actions = pending_tool_control_actions_from_observation(
        {
            "observation_id": "obs:observe-subagents:merged",
            "source": "tool:observe_subagents",
            "payload": {
                "tool_name": "observe_subagents",
                "structured_payload": {"tool_result": {"display": "status index"}},
                "result_envelope": {
                    "tool_name": "observe_subagents",
                    "tool_call_id": "call:observe-subagents:merged",
                    "action_request_id": "act:observe-subagents:merged",
                    "structured_payload": {
                        "subagent_control": {
                            "subagents": [
                                {
                                    "subagent_run_ref": subagent_run_ref,
                                    "status": "completed",
                                    "result_ref": result_ref,
                                    "result_state": "unread",
                                    "result_unread": True,
                                    "result_available": True,
                                    "collect_subagent_result_args": {"subagent_run_ref": subagent_run_ref},
                                }
                            ]
                        }
                    },
                },
            },
        }
    )

    assert actions[0]["tool_call_id"] == "call:observe-subagents:merged"
    assert actions[0]["action"] == "collect_subagent_result"
    assert actions[0]["args"] == {"subagent_run_ref": subagent_run_ref}
    assert actions[0]["result_ref"] == result_ref


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
