from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from harness.loop.task_lifecycle import TaskLifecycleRecord, TaskRunContract
from harness.runtime.session_timeline import build_session_runtime_timeline
from runtime.shared.models import TaskRun, TurnRun
from tests.support.runtime_stubs import build_harness_runtime


_VISIBLE_RUNTIME_INTERNAL_MARKERS = (
    "TaskRun",
    "runtime packet",
    "agent action",
    "executor",
)


def _assert_no_visible_runtime_internals(text: str) -> None:
    leaked = [marker for marker in _VISIBLE_RUNTIME_INTERNAL_MARKERS if marker in text]
    assert leaked == []


def _action_request(
    *,
    action_type: str,
    final_answer: str = "",
    public_progress_note: str = "Working on the current request.",
) -> dict[str, object]:
    return {
        "authority": "harness.loop.model_action_request",
        "request_id": f"model-action:test:{action_type}",
        "turn_id": "",
        "action_type": action_type,
        "public_progress_note": public_progress_note,
        "public_action_state": {
            "current_judgment": public_progress_note,
            "next_action": public_progress_note,
        },
        "final_answer": final_answer,
        "tool_call": {},
        "task_contract_seed": {},
        "completion_contract": {},
        "permission_request": {},
        "active_work_control": {},
        "diagnostics": {"test_action_request": True},
    }


class _TaskExecutorSequenceModelRuntime:
    def __init__(self, task_actions: list[dict[str, object]], *, agent_turn_action_request: dict[str, object]) -> None:
        self.task_actions = list(task_actions)
        self.agent_turn_action_request = dict(agent_turn_action_request)

    async def invoke_messages(self, messages, **_kwargs):
        content = str(list(messages or [])[0].get("content") or "")
        if "持续处理流程" in content or "task_execution" in str(messages):
            action = self.task_actions.pop(0) if len(self.task_actions) > 1 else self.task_actions[0]
            return SimpleNamespace(content=json.dumps(action, ensure_ascii=False))
        return SimpleNamespace(content=json.dumps(self.agent_turn_action_request, ensure_ascii=False))


def test_session_runtime_timeline_keeps_completed_task_attachment() -> None:
    runtime = build_harness_runtime(
        model_runtime=_TaskExecutorSequenceModelRuntime(
            [
                _action_request(
                    action_type="respond",
                    final_answer="Timeline final answer.",
                    public_progress_note="I have finished the timeline verification.",
                )
            ],
            agent_turn_action_request=_action_request(action_type="respond", final_answer="unused"),
        )
    )
    host = runtime.single_agent_runtime_host
    contract = TaskRunContract(
        contract_id="task-contract:timeline",
        contract_source="test",
        user_visible_goal="Verify timeline attachment.",
        task_run_goal="Keep the runtime attachment after completion.",
        completion_criteria=("final answer is ready",),
    )
    contract_ref = host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
    lifecycle = TaskLifecycleRecord(
        task_run_id="taskrun:turn:session-timeline:1:abc",
        contract_ref=contract_ref,
        status="running",
        created_at=1.0,
        updated_at=1.0,
    )
    host.runtime_objects.put_object("task_lifecycle", lifecycle.task_run_id, lifecycle.to_dict())
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=lifecycle.task_run_id,
            session_id="session-timeline",
            task_id="task:turn:session-timeline:1",
            task_contract_ref=contract_ref,
            agent_profile_id="main_interactive_agent",
            execution_runtime_kind="single_agent_task",
            status="running",
            created_at=1.0,
            updated_at=1.0,
            diagnostics={
                "turn_id": "turn:session-timeline:1",
                "contract": contract.to_dict(),
                "executor_status": "lost",
                "executor_lease_state": "lost",
                "recovery_action": "rerun_task_executor",
                "recoverable_error": {
                    "error_code": "test_resume_checkpoint",
                    "retryable": True,
                },
            },
        )
    )

    result = asyncio.run(runtime.execute_task_run(lifecycle.task_run_id, max_steps=2))
    timeline = build_session_runtime_timeline(
        session_id="session-timeline",
        history={"messages": runtime.session_manager.load_session("session-timeline")},
        runtime_host=host,
    )

    attachment = timeline["runtime_attachments"][0]
    assert result["ok"] is True
    assert attachment["task_run_id"] == lifecycle.task_run_id
    assert attachment["anchor_turn_id"] == "turn:session-timeline:1"
    assert attachment["status"] == "completed"
    assert attachment["final_answer"] == "Timeline final answer."
    assert attachment["anchor_role"] == "assistant"
    assert attachment["public_timeline"]
    task_projection = dict(attachment.get("task_projection") or {})
    visible_attachment_text = json.dumps(
        {
            "summary": attachment["summary"],
            "latest_step_summary": attachment["latest_step_summary"],
            "public_timeline": attachment["public_timeline"],
            "task_projection": {
                "current_action": task_projection.get("current_action"),
                "todo": task_projection.get("todo"),
                "activities": task_projection.get("activities"),
                "final_answer": task_projection.get("final_answer"),
            },
        },
        ensure_ascii=False,
    )
    _assert_no_visible_runtime_internals(visible_attachment_text)


def test_session_runtime_timeline_projects_tool_observation_as_agent_visible_observation() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:turn:session-observation:1:abc"
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id="session-observation",
            task_id="task:turn:session-observation:1",
            execution_runtime_kind="single_agent_task",
            status="running",
            created_at=1.0,
            updated_at=2.0,
            diagnostics={"turn_id": "turn:session-observation:1"},
        )
    )
    host.event_log.append(
        task_run_id,
        "task_tool_observation_recorded",
        payload={
            "observation": {
                "observation_id": "rtobs:session-observation:image",
                "source": "tool:image_generate",
                "payload": {
                    "tool_name": "image_generate",
                    "result": json.dumps({"ok": False, "error": "Image API request timed out", "retryable": True}),
                },
            }
        },
    )
    host.event_log.append(
        task_run_id,
        "step_summary_recorded",
        payload={
            "task_run_id": task_run_id,
            "step": "task_tool_observation_recorded:3",
            "status": "running",
            "summary": "Tool call finished.",
            "agent_brief_output": json.dumps(
                {"ok": False, "error": "Image API request timed out", "retryable": True}
            ),
        },
        refs={
            "turn_ref": "turn:session-observation:1",
            "observation_ref": "rtobs:session-observation:image",
            "tool_name": "image_generate",
        },
    )
    host.event_log.append(
        task_run_id,
        "model_action_request_received",
        payload={
            "model_action_request": {
                "request_id": "model-action:retry-image",
                "turn_id": "turn:session-observation:1",
                "action_type": "tool_call",
                "public_progress_note": "Retry image generation with safer parameters.",
                "public_action_state": {
                    "current_judgment": "The image provider timed out but retry is possible.",
                    "next_action": "Retry with safer parameters.",
                },
                "tool_call": {"name": "image_generate", "args": {"prompt": "safer parameters"}},
            },
        },
        refs={"turn_ref": "turn:session-observation:1", "action_request_ref": "model-action:retry-image"},
    )
    host.event_log.append(
        task_run_id,
        "step_summary_recorded",
        payload={
            "task_run_id": task_run_id,
            "step": "model_action_received:4",
            "status": "running",
            "summary": "Retry image generation with safer parameters.",
            "public_progress_note": "Retry image generation with safer parameters.",
            "public_action_state": {
                "current_judgment": "The image provider timed out but retry is possible.",
                "next_action": "Retry with safer parameters.",
            },
        },
        refs={"turn_ref": "turn:session-observation:1"},
    )

    timeline = build_session_runtime_timeline(
        session_id="session-observation",
        history={"messages": []},
        runtime_host=host,
    )

    attachment = timeline["runtime_attachments"][0]
    public_timeline = attachment["public_timeline"]
    assert any(
        item.get("kind") == "observation_report"
        and item.get("detail") == "The image provider timed out but retry is possible."
        for item in public_timeline
    )
    assert any(
        item.get("kind") == "work_action"
        and item.get("action_kind") == "image"
        and item.get("state") == "error"
        for item in public_timeline
    )
    assert not any(item.get("kind") == "blocked" for item in public_timeline)


def test_session_runtime_timeline_projects_turn_run_tool_progress() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    session_id = "session-turn-timeline"
    turn_id = "turn:session-turn-timeline:7"
    turn_run_id = f"turnrun:{turn_id}"
    host.state_index.upsert_turn_run(
        TurnRun(
            turn_run_id=turn_run_id,
            session_id=session_id,
            turn_id=turn_id,
            status="completed",
            created_at=1.0,
            updated_at=3.0,
        )
    )
    host.event_log.append(
        turn_run_id,
        "assistant_text",
        payload={
            "turn_id": turn_id,
            "content": "I found the target file and will write the update next.",
            "answer_channel": "stage_feedback",
            "answer_source": "harness.single_agent_turn.tool_commentary",
            "answer_canonical_state": "progress_only",
            "answer_persist_policy": "persist_debug_only",
        },
        refs={"turn_ref": turn_id, "turn_run_ref": turn_run_id},
    )
    host.event_log.append(
        turn_run_id,
        "model_action_admission_checked",
        payload={
            "turn_id": turn_id,
            "model_action_request": {
                "request_id": "model-action:turn-timeline:write",
                "turn_id": turn_id,
                "action_type": "tool_call",
                "public_progress_note": "Writing docs/turn.md.",
                "tool_call": {"tool_name": "write_file", "args": {"path": "docs/turn.md"}},
            },
            "admission": {"decision": "allow"},
        },
        refs={"turn_ref": turn_id, "turn_run_ref": turn_run_id},
    )
    host.event_log.append(
        turn_run_id,
        "turn_tool_observation_recorded",
        payload={
            "turn_id": turn_id,
            "tool_observation": {
                "observation_id": "toolobs:turn",
                "invocation_id": "toolinv:turn",
                "caller_kind": "turn_run",
                "caller_ref": turn_run_id,
                "tool_name": "write_file",
                "operation_id": "op:write",
                "status": "ok",
                "text": "Write succeeded: docs/turn.md",
                "result_envelope": {"tool_args": {"path": "docs/turn.md"}},
                "artifact_refs": [{"path": "docs/turn.md", "kind": "file"}],
            },
        },
        refs={"turn_ref": turn_id, "turn_run_ref": turn_run_id},
    )

    timeline = build_session_runtime_timeline(
        session_id=session_id,
        history={
            "messages": [
                {"role": "user", "content": "write file", "turn_id": turn_id},
                {"role": "assistant", "content": "Turn update is complete.", "turn_id": turn_id, "id": "message:assistant"},
            ]
        },
        runtime_host=host,
    )

    attachment = timeline["runtime_attachments"][0]
    assert attachment["run_id"] == turn_run_id
    assert attachment["task_run_id"] == ""
    assert attachment["anchor_turn_id"] == turn_id
    assert attachment["anchor_message_id"] == "message:assistant"
    assert any(item.get("kind") == "work_action" for item in attachment["public_timeline"])
    assert "docs/turn.md" in json.dumps(attachment["public_timeline"], ensure_ascii=False)
    assert any(
        item.get("kind") == "stage_summary"
        and item.get("text") == "I found the target file and will write the update next."
        for item in attachment["public_timeline"]
    )
    assert any(
        item.get("kind") == "final_summary"
        and item.get("text") == "Turn update is complete."
        for item in attachment["public_timeline"]
    )


def test_session_runtime_timeline_derives_turn_anchor_from_structural_task_run_id() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id="taskrun:turn:session-anchor:3:abc",
            session_id="session-anchor",
            task_id="task:turn:session-anchor:3",
            agent_profile_id="main_interactive_agent",
            execution_runtime_kind="single_agent_task",
            status="completed",
            terminal_reason="completed",
            created_at=1.0,
            updated_at=2.0,
            diagnostics={},
        )
    )

    timeline = build_session_runtime_timeline(
        session_id="session-anchor",
        history={"messages": []},
        runtime_host=host,
    )

    attachment = timeline["runtime_attachments"][0]
    assert attachment["run_id"] == "taskrun:turn:session-anchor:3:abc"
    assert attachment["anchor_turn_id"] == "turn:session-anchor:3"


def test_session_runtime_timeline_anchors_to_original_assistant_turn_message() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id="taskrun:turn:session-anchor-message:1:abc",
            session_id="session-anchor-message",
            task_id="task:turn:session-anchor-message:1",
            agent_profile_id="main_interactive_agent",
            execution_runtime_kind="single_agent_task",
            status="completed",
            terminal_reason="completed",
            created_at=1.0,
            updated_at=2.0,
            diagnostics={"turn_id": "turn:session-anchor-message:1"},
        )
    )

    timeline = build_session_runtime_timeline(
        session_id="session-anchor-message",
        history={
            "messages": [
                {"role": "user", "content": "start old task", "turn_id": "turn:session-anchor-message:1"},
                {"role": "assistant", "content": "old task accepted", "id": "message:old-assistant", "turn_id": "turn:session-anchor-message:1"},
                {"role": "user", "content": "new continuation", "turn_id": "turn:session-anchor-message:2"},
                {"role": "assistant", "content": "new reply", "id": "message:new-assistant", "turn_id": "turn:session-anchor-message:2"},
            ]
        },
        runtime_host=host,
    )

    attachment = timeline["runtime_attachments"][0]
    assert attachment["anchor_turn_id"] == "turn:session-anchor-message:1"
    assert attachment["anchor_message_id"] == "message:old-assistant"
    assert attachment["anchor_role"] == "assistant"


def test_session_runtime_timeline_does_not_move_task_anchor_to_later_continue_turn() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:turn:session-anchor-message:1:abc"
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id="session-anchor-message",
            task_id="task:turn:session-anchor-message:1",
            agent_profile_id="main_interactive_agent",
            execution_runtime_kind="single_agent_task",
            status="waiting_executor",
            terminal_reason="waiting_executor",
            created_at=1.0,
            updated_at=4.0,
            diagnostics={
                "turn_id": "turn:session-anchor-message:1",
                "latest_interaction_turn_id": "turn:session-anchor-message:3",
            },
        )
    )
    host.event_log.append(
        task_run_id,
        "step_summary_recorded",
        payload={
            "step": "task_run_executor_scheduled",
            "status": "running",
            "summary": "继续请求已记录。",
        },
        refs={"turn_ref": "turn:session-anchor-message:3"},
    )

    timeline = build_session_runtime_timeline(
        session_id="session-anchor-message",
        history={
            "messages": [
                {"role": "user", "content": "start old task", "turn_id": "turn:session-anchor-message:1"},
                {"role": "assistant", "content": "old task accepted", "id": "message:old-assistant", "turn_id": "turn:session-anchor-message:1"},
                {"role": "user", "content": "continue", "turn_id": "turn:session-anchor-message:3"},
                {"role": "assistant", "content": "new reply", "id": "message:new-assistant", "turn_id": "turn:session-anchor-message:3"},
            ]
        },
        runtime_host=host,
    )

    attachment = timeline["runtime_attachments"][0]
    assert attachment["anchor_turn_id"] == "turn:session-anchor-message:1"
    assert attachment["anchor_message_id"] == "message:old-assistant"


def test_session_runtime_timeline_ignores_legacy_child_event_as_control_anchor() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:turn:session-child-anchor:8:abc"
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id="session-child-anchor",
            task_id="task:turn:session-child-anchor:8",
            agent_profile_id="main_interactive_agent",
            execution_runtime_kind="single_agent_task",
            status="aborted",
            terminal_reason="user_aborted",
            created_at=1.0,
            updated_at=2.0,
            diagnostics={"turn_id": "turn:session-child-anchor:8"},
        )
    )
    host.event_log.append(
        task_run_id,
        "legacy_task_run_child_created",
        payload={"lineage": {"turn_id": "turn:session-child-anchor:16"}},
        refs={"turn_ref": "turn:session-child-anchor:16"},
    )

    timeline = build_session_runtime_timeline(
        session_id="session-child-anchor",
        history={
            "messages": [
                {"role": "user", "content": "start task"},
                {"role": "assistant", "content": "task accepted"},
                {"role": "user", "content": "continue"},
                {"role": "assistant", "content": "continuing"},
            ]
        },
        runtime_host=host,
    )

    attachment = next(item for item in timeline["runtime_attachments"] if item["task_run_id"] == task_run_id)
    assert attachment["run_id"] == task_run_id
    assert attachment["anchor_turn_id"] == "turn:session-child-anchor:8"
    assert "legacy_task_run_child_created" not in json.dumps(attachment.get("public_timeline", []), ensure_ascii=False)
