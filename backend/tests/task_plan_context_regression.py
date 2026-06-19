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
        contract={"task_run_goal": "fix prompt cache", "completion_criteria": ["cache issue fixed"]},
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
    assert task_plan_context["task_plan_cursor"]["active_item_id"] == "step:2"
    assert task_plan_context["task_plan_cursor"]["active_step_ref"].endswith(":step:step:2")
    assert "todo_plan" not in current_state_text
    assert "todo_plan" not in replay_text
    assert "task_plan_context" not in current_state_payload
    assert "todos" not in dict(current_state_payload["task_state"].get("task_progress_facts") or {})
    cache_record = _cache_record_for_packet(result.packet)
    assert cache_record.diagnostics["task_plan_context_predicted_tokens"] > 0


def _payload_with_title(packet, title: str) -> dict[str, object]:
    for message in packet.model_messages:
        content = str(dict(message).get("content") or "")
        if content.startswith(title + "\n"):
            return json.loads(content.split("\n", 1)[1])
    raise AssertionError(f"missing model message title: {title}")


def _cache_record_for_packet(packet):
    segment_map = CanonicalPromptSerializer().build_segment_map(
        request_id="modelreq:task-plan-context",
        messages=packet.model_messages,
        provider="deepseek",
        model="deepseek-v4-pro",
        segment_plan=packet.segment_plan,
    )
    return PromptCachePlanner().plan(segment_map)
