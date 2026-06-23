from __future__ import annotations

import json

from harness.runtime.compiler import RuntimeCompiler
from runtime.prompt_accounting import CanonicalPromptSerializer, PromptCachePlanner


def test_task_execution_projects_todo_plan_as_dedicated_task_plan_context() -> None:
    todo_plan = {
        "plan_id": "plan:cache-refactor",
        "active_item_id": "step:2",
        "completion_ready": False,
        "items": [
            {
                "todo_id": "step:1",
                "content": "Audit prompt cache miss families",
                "active_form": "Auditing prompt cache miss families",
                "status": "completed",
                "notes": "Stable prompt and tool schema were inspected.",
            },
            {
                "todo_id": "step:2",
                "content": "Split task plan from volatile task state",
                "active_form": "Splitting task plan from volatile task state",
                "status": "in_progress",
                "notes": "Keep plan visible without replaying it in tool results.",
                "evidence_expectations": ["task_plan_context segment is present"],
            },
        ],
    }
    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:task-plan-context",
        task_run={"task_run_id": "taskrun:task-plan-context", "diagnostics": {"executor_status": "running"}},
        contract={
            "task_run_goal": "fix prompt cache",
            "completion_criteria": ["cache issue fixed"],
            "plan_contract": {
                "plan_id": "plan:cache-refactor",
                "plan_version": "3",
                "plan_status": "agent_managed",
                "strategy_summary": "Split the durable plan from the execution cursor.",
                "major_steps": [
                    {"step_id": "phase:1", "title": "Audit prompt cache miss families"},
                    {"step_id": "phase:2", "title": "Split plan contract from todo cursor"},
                ],
                "allowed_plan_operations": ["update", "replan"],
            },
        },
        observations=[],
        execution_state={
            "system_projection": {
                "runtime_status": "running",
                "last_action_receipts": [
                    {
                        "observation_ref": "obs:todo:1",
                        "tool_name": "agent_todo",
                        "tool_call_id": "call:todo:1",
                        "status": "ok",
                        "summary": "Current todo plan.",
                        "todo_plan": todo_plan,
                        "event_offset": 7,
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
    task_plan_payload = _payload_with_title(result.packet, "Task execution task plan context")
    current_state_payload = _payload_with_title(result.packet, "Task execution current state")
    replay_payload = _payload_with_title(result.packet, "Task execution replayed state evidence obs:todo:1")
    task_plan_context = task_plan_payload["task_plan_context"]
    current_state_text = json.dumps(current_state_payload, ensure_ascii=False)
    replay_text = json.dumps(replay_payload, ensure_ascii=False)

    assert kinds.index("task_plan_context") < kinds.index("volatile_task_state")
    assert task_plan_payload["task_plan_context"]["task_plan_baseline"]["plan_id"] == "plan:cache-refactor"
    assert task_plan_payload["task_plan_context"]["task_plan_baseline"]["plan_version"] == "3"
    assert task_plan_payload["task_plan_context"]["task_plan_baseline"]["items"][0]["source"] == "plan_contract"
    assert task_plan_context["todo_cursor"]["active_item_id"] == "step:2"
    assert task_plan_context["todo_cursor"]["active_step_ref"].endswith(":step:step:2")
    assert task_plan_context["todo_cursor"]["completion_ready_signal"] == {
        "reported_by": "agent_todo",
        "value": False,
        "authority": "progress_signal_not_completion_gate",
    }
    assert "todo_plan" not in current_state_text
    assert "todo_plan" not in replay_text
    assert "task_plan_context" not in current_state_payload
    assert "todos" not in dict(current_state_payload["task_state"].get("task_progress_facts") or {})
    cache_record = _cache_record_for_packet(result.packet)
    assert cache_record.diagnostics["task_plan_context_predicted_tokens"] > 0


def test_task_execution_projects_plan_contract_without_todo_cursor() -> None:
    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:task-plan-without-todo",
        task_run={"task_run_id": "taskrun:task-plan-without-todo", "diagnostics": {"executor_status": "running"}},
        contract={
            "task_run_goal": "stabilize task mechanism",
            "plan_contract": {
                "plan_id": "plan:task-mechanism",
                "plan_status": "agent_managed",
                "strategy_summary": "Use the contract as the durable plan and todo only as a cursor.",
                "major_steps": ["Tighten task entry", "Layer contracts", "Verify feedback"],
            },
            "acceptance_contract": {"completion_criteria": ["task mechanism is stable"]},
        },
        observations=[],
        execution_state={"system_projection": {"runtime_status": "running", "last_action_receipts": []}},
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    task_plan_payload = _payload_with_title(result.packet, "Task execution task plan context")
    context = task_plan_payload["task_plan_context"]

    assert context["task_plan_baseline"]["plan_id"] == "plan:task-mechanism"
    assert [item["title"] for item in context["task_plan_baseline"]["items"]] == [
        "Tighten task entry",
        "Layer contracts",
        "Verify feedback",
    ]
    assert "todo_cursor" not in context


def test_task_execution_incremental_context_cursor_indexes_steer_and_runtime_signals() -> None:
    historical_exact_text = "SECRET_OLD_EXACT_TEXT_SHOULD_NOT_BE_DUPLICATED"
    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:feedback-context",
        task_run={"task_run_id": "taskrun:feedback-context", "diagnostics": {"executor_status": "running"}},
        contract={
            "task_run_goal": "apply user steer safely",
            "plan_contract": {"plan_id": "plan:feedback", "major_steps": ["Consume steer"]},
            "acceptance_contract": {"completion_criteria": ["steer handled with evidence"]},
        },
        observations=[],
        execution_state={
            "system_projection": {
                "runtime_status": "running",
                "pending_user_steers": [
                    {
                        "steer_id": "steer:feedback:1",
                        "task_run_id": "taskrun:feedback-context",
                        "content": "先处理新的验收要求。",
                    }
                ],
                "runtime_control_signals": [
                    {"runtime_control_signal_ref": "rtsig:budget:1", "signal_kind": "budget_exhausted"}
                ],
                "last_action_receipts": [
                    {
                        "tool_name": "read_file",
                        "status": "ok",
                        "summary": "Evidence loaded.",
                        "content": historical_exact_text,
                        "observation_ref": "obs:read:1",
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
    cursor_segment = _segment_by_kind(result.packet, "incremental_context_cursor")
    current_state_payload = _payload_with_title(result.packet, "Task execution current state")
    cursor_payload = _payload_with_title(result.packet, "Task execution current delta cursor")
    cursor = cursor_payload["incremental_context_cursor"]
    cursor_text = json.dumps(cursor, ensure_ascii=False)
    event_refs = {item.get("event_ref") for item in cursor["current_invocation"]["new_event_refs"]}
    runtime_control_refs = {item.get("event_ref") for item in cursor["current_invocation"]["runtime_control_refs"]}
    task_state = current_state_payload["task_state"]

    assert kinds.index("volatile_task_state") < kinds.index("incremental_context_cursor")
    assert kinds.index("user_steering_context_append") < kinds.index("volatile_task_state")
    assert kinds.index("incremental_context_cursor") < kinds.index("user_steering_consumption_tail")
    assert cursor_segment["cache_role"] == "volatile"
    assert cursor_segment["cache_scope"] == "none"
    assert cursor_segment["prefix_tier"] == "volatile"
    assert dict(cursor_segment.get("metadata") or {})["cache_impact"] == "volatile_suffix_only"
    assert cursor["frame_type"] == "dynamic_execution_tail"
    assert cursor["frame_scope"] == "task_execution"
    assert cursor["sealed_context_cursor"]["latest_task_state_replay_ref"] == "obs:read:1"
    assert cursor["execution_contract"]["memory_source"] == "sealed_context_prefix+context_append"
    assert cursor["execution_contract"]["tail_scope"] == "current_invocation_control_only"
    assert "steer:feedback:1" in event_refs
    assert "rtsig:budget:1" in runtime_control_refs
    assert "obs:read:1" in event_refs
    assert "append_only_replay" not in cursor
    assert "changed_state" not in cursor
    assert "dynamic_context_refs" not in cursor
    assert "payload_hash" not in cursor_text
    assert "先处理新的验收要求" not in cursor_text
    assert "Facts, memory" not in cursor_text
    assert "latest_runtime_control_signal" not in current_state_payload
    assert "runtime_control_signals" not in current_state_payload
    assert "latest_tool_results" not in task_state
    assert "current_facts" not in task_state
    assert historical_exact_text not in cursor_text


def test_task_execution_read_file_tool_memory_uses_refs_without_replaying_exact_text() -> None:
    exact_text = "SECRET_READ_FILE_BODY_SHOULD_NOT_BE_REPLAYED\nline 2\nline 3"
    observation = {
        "observation_id": "obs:read:structured",
        "source": "tool:read_file",
        "status": "ok",
        "payload": {
            "tool_name": "read_file",
            "tool_call_id": "call:read:structured",
            "result": exact_text,
            "result_envelope": {
                "envelope_id": "tool-result:read-structured",
                "tool_name": "read_file",
                "tool_call_id": "call:read:structured",
                "status": "ok",
                "text": exact_text,
                "observed_paths": ["backend/example.py"],
                "structured_payload": {
                    "tool_result": {
                        "kind": "text_file",
                        "path": "backend/example.py",
                        "start_line": 1,
                        "end_line": 3,
                        "returned_lines": 3,
                        "line_count": 3,
                        "total_lines": 3,
                        "has_more": False,
                        "truncated": False,
                        "content_sha256": "sha256:example-content",
                        "exact_artifact_ref": "read_observation:example-content",
                        "visible_exact": True,
                        "text_sha256": "sha256:example-text",
                    }
                },
            },
        },
    }
    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:tool-memory-refs",
        task_run={"task_run_id": "taskrun:tool-memory-refs", "diagnostics": {"executor_status": "running"}},
        contract={
            "task_run_goal": "avoid replaying exact read_file bodies",
            "acceptance_contract": {"completion_criteria": ["exact body appears once only"]},
        },
        observations=[observation],
        execution_state={"system_projection": {"runtime_status": "running", "last_action_receipts": []}},
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    replay_payload = _payload_with_title(result.packet, "Task execution replayed state evidence obs:read:structured")
    current_state_payload = _payload_with_title(result.packet, "Task execution current state")
    frame_payload = _payload_with_title(result.packet, "Task execution current delta cursor")
    replay_text = json.dumps(replay_payload, ensure_ascii=False)
    current_state_text = json.dumps(current_state_payload, ensure_ascii=False)
    frame_text = json.dumps(frame_payload, ensure_ascii=False)

    assert exact_text not in replay_text
    assert exact_text not in current_state_text
    assert exact_text not in frame_text
    assert replay_payload["task_state_replay_entry"]["content_range"]["path"] == "backend/example.py"
    assert replay_payload["task_state_replay_entry"]["content_range"]["exact_artifact_ref"] == "read_observation:example-content"
    assert "latest_tool_results" not in current_state_payload["task_state"]
    assert frame_payload["incremental_context_cursor"]["sealed_context_cursor"]["latest_task_state_replay_ref"] == "obs:read:structured"


def _payload_with_title(packet, title: str) -> dict[str, object]:
    for message in packet.model_messages:
        content = str(dict(message).get("content") or "")
        if content.startswith(title + "\n"):
            return json.loads(content.split("\n", 1)[1])
        marker = "\n" + title + "\n"
        if marker in content:
            return json.loads(content.split(marker, 1)[1])
    raise AssertionError(f"missing model message title: {title}")


def _segment_by_kind(packet, kind: str) -> dict[str, object]:
    for segment in packet.segment_plan["segments"]:
        if segment["kind"] == kind:
            return dict(segment)
    raise AssertionError(f"missing segment kind: {kind}")


def _cache_record_for_packet(packet):
    segment_map = CanonicalPromptSerializer().build_segment_map(
        request_id="modelreq:task-plan-context",
        messages=packet.model_messages,
        provider="deepseek",
        model="deepseek-v4-pro",
        segment_plan=packet.segment_plan,
    )
    return PromptCachePlanner().plan(segment_map)
