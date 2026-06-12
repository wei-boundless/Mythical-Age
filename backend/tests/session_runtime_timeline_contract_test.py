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
from harness.runtime.projection.timeline_builder import project_public_timeline_from_events
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


def test_session_runtime_timeline_reconciles_tool_start_and_completion_lifecycle() -> None:
    events = [
        {
            "event_id": "event:start",
            "event_type": "model_action_admission_checked",
            "run_id": "turnrun:turn:test:1",
            "offset": 1,
            "created_at": 1.0,
            "payload": {
                "model_action_request": {
                    "request_id": "request:read",
                    "action_type": "tool_call",
                    "tool_call": {
                        "id": "call:read",
                        "tool_name": "read_file",
                        "args": {"path": "backend/harness/runtime/session_timeline.py"},
                    },
                }
            },
            "refs": {"action_request_ref": "request:read", "turn_run_ref": "turnrun:turn:test:1"},
        },
        {
            "event_id": "event:done",
            "event_type": "turn_tool_observation_recorded",
            "run_id": "turnrun:turn:test:1",
            "offset": 2,
            "created_at": 2.0,
            "payload": {
                "tool_observation": {
                    "tool_name": "read_file",
                    "status": "ok",
                    "tool_call_id": "call:read",
                    "result_envelope": {
                        "tool_name": "read_file",
                        "tool_call_id": "call:read",
                        "tool_args": {"path": "backend/harness/runtime/session_timeline.py"},
                    },
                }
            },
            "refs": {"turn_run_ref": "turnrun:turn:test:1"},
        },
    ]

    items = project_public_timeline_from_events(events, run_id="turnrun:turn:test:1", turn_run_id="turnrun:turn:test:1")

    tool_items = [item for item in items if item.get("slot") == "tool"]
    assert len(tool_items) == 1
    assert tool_items[0]["item_id"] == "call:read"
    assert tool_items[0]["tool_lifecycle_id"] == "call:read"
    assert tool_items[0]["tool_call_id"] == "call:read"
    assert tool_items[0]["state"] == "done"
    assert tool_items[0]["subject_label"] == "backend/harness/runtime/session_timeline.py"


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
    assert "final_answer" not in attachment
    assert attachment["anchor_role"] == "assistant"
    task_projection = dict(attachment.get("task_projection") or {})
    assert task_projection
    assert "final_answer" not in task_projection
    assert attachment["public_timeline"]
    visible_attachment_text = json.dumps(
        {
            "summary": attachment["summary"],
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


def test_session_runtime_timeline_uses_task_projection_as_task_attachment_display_authority() -> None:
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
    task_projection = dict(attachment.get("task_projection") or {})
    current_action = dict(task_projection.get("current_action") or {})
    assert task_projection["status"] == "running"
    assert current_action.get("title")
    assert current_action.get("detail")
    assert current_action.get("state") == "running"
    assert current_action.get("display_surface") == "timeline"
    assert current_action.get("visibility_level") == "secondary"
    assert current_action.get("source_kind") == "stage_feedback"
    assert not any(item.get("kind") == "blocked" for item in task_projection.get("activities", []))
    assert attachment["public_timeline"]
    assert any(item.get("kind") == "tool_observation" for item in task_projection.get("activities", []))
    assert any(item.get("kind") in {"status_update", "error_notice"} for item in attachment["public_timeline"])


def test_session_runtime_timeline_does_not_synthesize_generic_success_feedback() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:turn:session-generic-success:1:abc"
    turn_id = "turn:session-generic-success:1"
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id="session-generic-success",
            task_id="task:turn:session-generic-success:1",
            execution_runtime_kind="single_agent_task",
            status="completed",
            terminal_reason="completed",
            created_at=1.0,
            updated_at=4.0,
            diagnostics={"turn_id": turn_id},
        )
    )
    host.event_log.append(
        task_run_id,
        "task_run_lifecycle_started",
        payload={"task_run": {"task_run_id": task_run_id, "status": "running"}},
        refs={"turn_ref": turn_id},
    )
    host.event_log.append(
        task_run_id,
        "task_tool_observation_recorded",
        payload={
            "observation": {
                "observation_id": "rtobs:generic-success",
                "source": "tool:search_text",
                "payload": {
                    "tool_name": "search_text",
                    "result": json.dumps({"ok": True}),
                },
            }
        },
        refs={"turn_ref": turn_id, "observation_ref": "rtobs:generic-success"},
    )
    host.event_log.append(
        task_run_id,
        "step_summary_recorded",
        payload={
            "task_run_id": task_run_id,
            "step": "task_tool_observation_recorded:1",
            "status": "running",
            "summary": "工具调用已完成，正在根据结果继续。",
            "agent_brief_output": json.dumps({"ok": True}),
        },
        refs={"turn_ref": turn_id, "observation_ref": "rtobs:generic-success"},
    )
    host.event_log.append(
        task_run_id,
        "task_run_lifecycle_finished",
        payload={"task_run": {"task_run_id": task_run_id, "status": "completed", "terminal_reason": "completed"}},
        refs={"turn_ref": turn_id},
    )

    timeline = build_session_runtime_timeline(
        session_id="session-generic-success",
        history={
            "messages": [
                {"role": "user", "content": "run task", "turn_id": turn_id},
                {"role": "assistant", "content": "", "turn_id": turn_id, "id": "message:assistant"},
            ]
        },
        runtime_host=host,
    )

    attachment = timeline["runtime_attachments"][0]
    visible = json.dumps(
        {
            "public_timeline": attachment.get("public_timeline"),
            "task_projection": attachment.get("task_projection"),
            "summary": attachment.get("summary"),
        },
        ensure_ascii=False,
    )
    assert "工具返回成功" not in visible
    assert "工具调用已完成，正在根据结果继续" not in visible
    assert "处理完成" not in visible
    assert "已开始处理" not in visible


def test_session_runtime_timeline_does_not_project_system_tool_step_summaries() -> None:
    events = [
        {
            "event_id": "event:batch",
            "event_type": "step_summary_recorded",
            "run_id": "taskrun:turn:session-tool-system:1:abc",
            "offset": 1,
            "created_at": 1.0,
            "payload": {
                "task_run_id": "taskrun:turn:session-tool-system:1:abc",
                "step": "task_tool_batch_started:3",
                "status": "running",
                "summary": "执行 7 个工具调用：读取文件 backend/harness/runtime/compiler.py 等。",
                "presentation_source": "system.tool_call_status",
            },
        },
        {
            "event_id": "event:repair",
            "event_type": "step_summary_recorded",
            "run_id": "taskrun:turn:session-tool-system:1:abc",
            "offset": 2,
            "created_at": 2.0,
            "payload": {
                "task_run_id": "taskrun:turn:session-tool-system:1:abc",
                "step": "task_tool_repair_required:3",
                "status": "running",
                "summary": "工具调用失败，正在根据失败原因调整处理路径。",
            },
        },
    ]

    items = project_public_timeline_from_events(events, run_id="taskrun:turn:session-tool-system:1:abc", task_run_id="taskrun:turn:session-tool-system:1:abc")

    visible = json.dumps({"items": items}, ensure_ascii=False)
    assert "执行 7 个工具调用" not in visible
    assert "工具调用失败" not in visible
    assert items == []


def test_session_runtime_timeline_orders_public_items_across_projection_sources() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    session_id = "session-timeline-order"
    turn_id = "turn:session-timeline-order:1"
    task_run_id = "taskrun:turn:session-timeline-order:1:abc"
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id=session_id,
            task_id="task:turn:session-timeline-order:1",
            agent_profile_id="main_interactive_agent",
            execution_runtime_kind="single_agent_task",
            status="running",
            created_at=1.0,
            updated_at=4.0,
            diagnostics={"turn_id": turn_id},
        )
    )
    host.event_log.append(
        task_run_id,
        "step_summary_recorded",
        payload={
            "task_run_id": task_run_id,
            "step": "model_action_received:1",
            "status": "running",
            "summary": "先确认需求。",
            "public_progress_note": "先确认需求。",
        },
        refs={"turn_ref": turn_id},
    )
    host.event_log.append(
        task_run_id,
        "task_tool_observation_recorded",
        payload={
            "observation": {
                "observation_id": "rtobs:timeline-order:search",
                "source": "tool:search_text",
                "summary": "搜索证据已返回。",
                "payload": {"result": "搜索证据已返回。"},
            }
        },
        refs={"turn_ref": turn_id, "observation_ref": "rtobs:timeline-order:search"},
    )
    host.event_log.append(
        task_run_id,
        "step_summary_recorded",
        payload={
            "task_run_id": task_run_id,
            "step": "model_action_received:2",
            "status": "running",
            "summary": "再整理结论。",
            "public_progress_note": "再整理结论。",
        },
        refs={"turn_ref": turn_id},
    )

    timeline = build_session_runtime_timeline(
        session_id=session_id,
        history={"messages": []},
        runtime_host=host,
    )

    items = timeline["runtime_attachments"][0]["public_timeline"]
    offsets = [int(item["event_offset"]) for item in items]
    assert offsets == sorted(offsets)
    visible = json.dumps(items, ensure_ascii=False)
    assert visible.index("先确认需求") < visible.index("搜索证据已返回") < visible.index("再整理结论")


def test_session_runtime_timeline_keeps_runtime_rehydration_tool_on_public_surfaces() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    session_id = "session-show-rehydration"
    turn_id = "turn:session-show-rehydration:1"
    task_run_id = "taskrun:turn:session-show-rehydration:1:abc"
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id=session_id,
            task_id="task:turn:session-show-rehydration:1",
            agent_profile_id="main_interactive_agent",
            execution_runtime_kind="single_agent_task",
            status="running",
            created_at=1.0,
            updated_at=4.0,
            diagnostics={"turn_id": turn_id},
        )
    )
    host.event_log.append(
        task_run_id,
        "model_action_admission_checked",
        payload={
            "model_action_request": {
                "request_id": "model-action:rehydrate",
                "turn_id": turn_id,
                "action_type": "tool_call",
                "public_progress_note": "读取工具输出缓存。",
                "tool_call": {
                    "id": "call:rehydrate",
                    "tool_name": "read_persisted_tool_result",
                    "args": {"replacement_id": "tool_result:abc"},
                },
            }
        },
        refs={"turn_ref": turn_id, "action_request_ref": "model-action:rehydrate"},
    )
    host.event_log.append(
        task_run_id,
        "task_tool_observation_recorded",
        payload={
            "observation": {
                "observation_id": "rtobs:rehydrate",
                "source": "tool:read_persisted_tool_result",
                "summary": "旧工具输出缓存内容。",
                "payload": {"tool_name": "read_persisted_tool_result", "result": "旧工具输出缓存内容。"},
            }
        },
        refs={"turn_ref": turn_id, "observation_ref": "rtobs:rehydrate"},
    )
    host.event_log.append(
        task_run_id,
        "step_summary_recorded",
        payload={
            "task_run_id": task_run_id,
            "step": "task_tool_observation_recorded:1",
            "status": "running",
            "summary": "旧工具输出缓存内容。",
            "agent_brief_output": "旧工具输出缓存内容。",
        },
        refs={"turn_ref": turn_id, "observation_ref": "rtobs:rehydrate"},
    )

    timeline = build_session_runtime_timeline(
        session_id=session_id,
        history={"messages": []},
        runtime_host=host,
    )

    attachment = timeline["runtime_attachments"][0]
    visible = json.dumps(
        {
            "public_timeline": attachment.get("public_timeline"),
            "task_projection": attachment.get("task_projection"),
        },
        ensure_ascii=False,
    )
    assert "read_persisted_tool_result" in visible
    assert "旧工具输出缓存内容" in visible
    assert "工具输出" in visible


def test_session_runtime_timeline_uses_resume_boundary_for_running_public_segment() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    session_id = "session-resume-boundary"
    turn_id = "turn:session-resume-boundary:1"
    task_run_id = "taskrun:turn:session-resume-boundary:1:abc"
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id=session_id,
            task_id="task:turn:session-resume-boundary:1",
            agent_profile_id="main_interactive_agent",
            execution_runtime_kind="single_agent_task",
            status="running",
            created_at=1.0,
            updated_at=4.0,
            diagnostics={"turn_id": turn_id},
        )
    )
    host.event_log.append(
        task_run_id,
        "task_tool_observation_recorded",
        payload={
            "observation": {
                "observation_id": "rtobs:resume-boundary:old-read",
                "source": "tool:read_file",
                "summary": "旧文件 backend/old_context.py 已读取。",
                "payload": {"result": "旧文件 backend/old_context.py 已读取。"},
            }
        },
        refs={"turn_ref": turn_id, "observation_ref": "rtobs:resume-boundary:old-read"},
    )
    resume_event = host.event_log.append(
        task_run_id,
        "task_run_resume_requested",
        payload={"task_run_id": task_run_id, "requested_by": "user"},
        refs={"turn_ref": turn_id},
    )
    host.event_log.append(
        task_run_id,
        "step_summary_recorded",
        payload={
            "task_run_id": task_run_id,
            "step": "model_action_received:2",
            "status": "running",
            "summary": "继续后正在重新判断。",
            "public_progress_note": "继续后正在重新判断。",
        },
        refs={"turn_ref": turn_id},
    )

    timeline = build_session_runtime_timeline(
        session_id=session_id,
        history={"messages": []},
        runtime_host=host,
    )

    attachment = timeline["runtime_attachments"][0]
    visible = json.dumps(
        {
            "public_timeline": attachment.get("public_timeline"),
            "task_projection": attachment.get("task_projection"),
        },
        ensure_ascii=False,
    )
    assert attachment["public_since_offset"] == resume_event.offset
    assert "backend/old_context.py" not in visible
    assert "继续后正在重新判断" in visible


def test_session_runtime_timeline_uses_latest_user_interaction_as_public_lifecycle_boundary() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    session_id = "session-user-boundary"
    original_turn_id = "turn:session-user-boundary:1"
    latest_turn_id = "turn:session-user-boundary:3"
    task_run_id = "taskrun:turn:session-user-boundary:1:abc"
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id=session_id,
            task_id="task:turn:session-user-boundary:1",
            agent_profile_id="main_interactive_agent",
            execution_runtime_kind="single_agent_task",
            status="running",
            created_at=1.0,
            updated_at=4.0,
            diagnostics={
                "turn_id": original_turn_id,
                "latest_interaction_turn_id": latest_turn_id,
            },
        )
    )
    host.event_log.append(
        task_run_id,
        "task_tool_observation_recorded",
        payload={
            "observation": {
                "observation_id": "rtobs:user-boundary:old-read",
                "source": "tool:read_file",
                "summary": "旧文件 backend/old_context.py 已读取。",
                "payload": {"result": "旧文件 backend/old_context.py 已读取。"},
            }
        },
        refs={"turn_ref": original_turn_id, "observation_ref": "rtobs:user-boundary:old-read"},
    )
    boundary_event = host.event_log.append(
        task_run_id,
        "active_task_steer_recorded",
        payload={
            "steer": {
                "turn_id": latest_turn_id,
                "content": "检查最新对话显示。",
            }
        },
        refs={"turn_ref": latest_turn_id},
    )
    host.event_log.append(
        task_run_id,
        "step_summary_recorded",
        payload={
            "task_run_id": task_run_id,
            "step": "model_action_received:after-user-boundary",
            "status": "running",
            "summary": "正在检查最新对话显示。",
            "public_progress_note": "正在检查最新对话显示。",
        },
        refs={"turn_ref": latest_turn_id},
    )

    timeline = build_session_runtime_timeline(
        session_id=session_id,
        history={
            "messages": [
                {"role": "user", "content": "start", "turn_id": original_turn_id},
                {"role": "assistant", "content": "accepted", "id": "message:old-assistant", "turn_id": original_turn_id},
                {"role": "user", "content": "continue", "turn_id": latest_turn_id},
                {"role": "assistant", "content": "继续检查。", "id": "message:latest-assistant", "turn_id": latest_turn_id},
            ]
        },
        runtime_host=host,
    )

    attachment = timeline["runtime_attachments"][0]
    visible = json.dumps(
        {
            "public_timeline": attachment.get("public_timeline"),
            "task_projection": attachment.get("task_projection"),
        },
        ensure_ascii=False,
    )
    assert attachment["public_since_offset"] == boundary_event.offset
    assert attachment["anchor_turn_id"] == latest_turn_id
    assert attachment["anchor_message_id"] == "message:latest-assistant"
    assert "backend/old_context.py" not in visible
    assert "正在检查最新对话显示" in visible


def test_session_runtime_timeline_keeps_resume_boundary_after_task_completes() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    session_id = "session-resume-boundary-completed"
    turn_id = "turn:session-resume-boundary-completed:1"
    task_run_id = "taskrun:turn:session-resume-boundary-completed:1:abc"
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id=session_id,
            task_id="task:turn:session-resume-boundary-completed:1",
            agent_profile_id="main_interactive_agent",
            execution_runtime_kind="single_agent_task",
            status="completed",
            terminal_reason="completed",
            created_at=1.0,
            updated_at=4.0,
            diagnostics={"turn_id": turn_id},
        )
    )
    host.event_log.append(
        task_run_id,
        "task_tool_observation_recorded",
        payload={
            "observation": {
                "observation_id": "rtobs:resume-boundary-completed:old-read",
                "source": "tool:read_file",
                "summary": "旧文件 backend/old_context.py 已读取。",
                "payload": {"result": "旧文件 backend/old_context.py 已读取。"},
            }
        },
        refs={"turn_ref": turn_id, "observation_ref": "rtobs:resume-boundary-completed:old-read"},
    )
    resume_event = host.event_log.append(
        task_run_id,
        "task_run_resume_requested",
        payload={"task_run_id": task_run_id, "requested_by": "user"},
        refs={"turn_ref": turn_id},
    )
    host.event_log.append(
        task_run_id,
        "step_summary_recorded",
        payload={
            "task_run_id": task_run_id,
            "step": "model_action_received:after-resume",
            "status": "running",
            "summary": "继续后已经完成核查。",
            "public_progress_note": "继续后已经完成核查。",
        },
        refs={"turn_ref": turn_id},
    )
    host.event_log.append(
        task_run_id,
        "task_run_lifecycle_finished",
        payload={"task_run": {"task_run_id": task_run_id, "status": "completed", "terminal_reason": "completed"}},
        refs={"turn_ref": turn_id},
    )

    timeline = build_session_runtime_timeline(
        session_id=session_id,
        history={"messages": []},
        runtime_host=host,
    )

    attachment = timeline["runtime_attachments"][0]
    visible = json.dumps(
        {
            "public_timeline": attachment.get("public_timeline"),
            "task_projection": attachment.get("task_projection"),
        },
        ensure_ascii=False,
    )
    assert attachment["public_since_offset"] == resume_event.offset
    assert "backend/old_context.py" not in visible
    assert "继续后已经完成核查" in visible


def test_session_runtime_timeline_preserves_process_after_runtime_restart_recovery() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    session_id = "session-runtime-restart"
    turn_id = "turn:session-runtime-restart:1"
    task_run_id = "taskrun:turn:session-runtime-restart:1:abc"
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id=session_id,
            task_id="task:turn:session-runtime-restart:1",
            agent_profile_id="main_interactive_agent",
            execution_runtime_kind="single_agent_task",
            status="waiting_executor",
            terminal_reason="waiting_executor",
            created_at=1.0,
            updated_at=4.0,
            diagnostics={
                "turn_id": turn_id,
                "latest_current_judgment": "正在读取掉线前的旧文件。",
                "latest_next_action": "继续掉线前的旧步骤。",
                "latest_step": "task_executor_recovered_after_runtime_start",
                "latest_step_summary": "后端运行时已重启，当前任务可继续。",
                "latest_public_progress_note": "后端运行时已重启，当前任务可继续。",
                "executor_status": "waiting_executor",
                "recoverable_error": {
                    "error_code": "task_executor_interrupted_by_runtime_restart",
                    "retryable": True,
                    "user_message": "后端运行时已重启，任务可以继续续跑。",
                },
                "recovery_action": "rerun_task_executor",
            },
        )
    )
    host.event_log.append(
        task_run_id,
        "task_tool_observation_recorded",
        payload={
            "observation": {
                "observation_id": "rtobs:restart:read",
                "source": "tool:read_file",
                "summary": "已读取文件：backend/harness/runtime/session_timeline.py",
                "payload": {
                    "tool_name": "read_file",
                    "result": "已读取文件：backend/harness/runtime/session_timeline.py",
                },
            }
        },
        refs={"turn_ref": turn_id, "observation_ref": "rtobs:restart:read"},
    )
    host.event_log.append(
        task_run_id,
        "task_run_executor_recovered_after_runtime_start",
        payload={
            "task_run_id": task_run_id,
            "previous_status": "running",
            "previous_executor_status": "running",
        },
        refs={"turn_ref": turn_id},
    )

    timeline = build_session_runtime_timeline(
        session_id=session_id,
        history={
            "messages": [
                {"role": "user", "content": "继续", "turn_id": turn_id},
                {"role": "assistant", "content": "任务已启动。", "turn_id": turn_id, "id": "message:assistant"},
            ]
        },
        runtime_host=host,
    )

    attachment = timeline["runtime_attachments"][0]
    task_projection = dict(attachment.get("task_projection") or {})
    current_action = dict(task_projection.get("current_action") or {})
    visible = json.dumps(
        {
            "public_timeline": attachment.get("public_timeline"),
            "task_projection": task_projection,
        },
        ensure_ascii=False,
    )
    assert attachment["public_since_offset"] == 0
    assert "backend/harness/runtime/session_timeline.py" in visible
    assert "后端运行时已重启" in visible
    assert "后端运行时已重启，任务可以继续续跑" in visible
    assert "正在读取掉线前的旧文件" not in visible
    assert "继续掉线前的旧步骤" not in visible
    assert current_action["kind"] == "lifecycle"
    assert current_action["state"] == "waiting"
    assert "后端运行时已重启" in current_action["title"]
    assert "掉线前" not in current_action["title"]


def test_session_runtime_timeline_does_not_expose_line_numbered_tool_output() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    session_id = "session-raw-tool-output"
    turn_id = "turn:session-raw-tool-output:1"
    task_run_id = "taskrun:turn:session-raw-tool-output:1:abc"
    raw_output = "  1 | # LangChain-Agent 项目代码审查报告\n  2 | 这是工具读取的文件原文。"
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id=session_id,
            task_id="task:turn:session-raw-tool-output:1",
            agent_profile_id="main_interactive_agent",
            execution_runtime_kind="single_agent_task",
            status="completed",
            terminal_reason="completed",
            created_at=1.0,
            updated_at=2.0,
            diagnostics={"turn_id": turn_id},
        )
    )
    host.event_log.append(
        task_run_id,
        "task_tool_observation_recorded",
        payload={
            "observation": {
                "observation_id": "rtobs:raw-file",
                "source": "tool:read_file",
                "summary": raw_output,
                "payload": {"result": raw_output},
            },
        },
        refs={"turn_ref": turn_id, "observation_ref": "rtobs:raw-file"},
    )

    timeline = build_session_runtime_timeline(
        session_id=session_id,
        history={
            "messages": [
                {"role": "user", "content": "审查项目", "turn_id": turn_id},
                {"role": "assistant", "content": "", "turn_id": turn_id, "id": "message:assistant"},
            ]
        },
        runtime_host=host,
    )

    visible = json.dumps(timeline["runtime_attachments"], ensure_ascii=False)
    assert "LangChain-Agent" not in visible
    assert "1 | #" not in visible


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
    assert not any(
        item.get("kind") == "final_summary"
        and item.get("text") == "Turn update is complete."
        for item in attachment["public_timeline"]
    )


def test_session_runtime_timeline_does_not_project_plain_assistant_message_as_runtime_body() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    session_id = "session-plain-answer"
    turn_id = "turn:session-plain-answer:3"
    turn_run_id = f"turnrun:{turn_id}"
    host.state_index.upsert_turn_run(
        TurnRun(
            turn_run_id=turn_run_id,
            session_id=session_id,
            turn_id=turn_id,
            status="completed",
            terminal_reason="assistant_message",
            created_at=1.0,
            updated_at=2.0,
        )
    )
    host.event_log.append(
        turn_run_id,
        "agent_turn_terminal",
        payload={
            "turn_id": turn_id,
            "status": "completed",
            "terminal_reason": "assistant_message",
        },
        refs={"turn_ref": turn_id, "turn_run_ref": turn_run_id},
    )

    timeline = build_session_runtime_timeline(
        session_id=session_id,
        history={
            "messages": [
                {"role": "user", "content": "你可以干什么", "turn_id": turn_id},
                {
                    "role": "assistant",
                    "content": "我可以帮你阅读代码、修改文件并运行验证。",
                    "turn_id": turn_id,
                    "id": "message:assistant",
                },
            ]
        },
        runtime_host=host,
    )

    assert timeline["runtime_attachments"] == []


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


def test_session_runtime_timeline_anchors_visible_segment_to_latest_interaction_turn() -> None:
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
    assert attachment["anchor_turn_id"] == "turn:session-anchor-message:3"
    assert attachment["anchor_message_id"] == "message:new-assistant"


def test_session_runtime_timeline_leaves_anchor_message_empty_when_original_assistant_is_missing() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:turn:session-missing-anchor:1:abc"
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id="session-missing-anchor",
            task_id="task:turn:session-missing-anchor:1",
            agent_profile_id="main_interactive_agent",
            execution_runtime_kind="single_agent_task",
            status="completed",
            terminal_reason="completed",
            created_at=1.0,
            updated_at=2.0,
            diagnostics={"turn_id": "turn:session-missing-anchor:1"},
        )
    )

    timeline = build_session_runtime_timeline(
        session_id="session-missing-anchor",
        history={
            "messages": [
                {"role": "user", "content": "start old task", "turn_id": "turn:session-missing-anchor:1"},
                {"role": "user", "content": "new request", "turn_id": "turn:session-missing-anchor:2"},
                {"role": "assistant", "content": "new reply", "id": "message:new-assistant", "turn_id": "turn:session-missing-anchor:2"},
            ]
        },
        runtime_host=host,
    )

    attachment = timeline["runtime_attachments"][0]
    assert attachment["anchor_turn_id"] == "turn:session-missing-anchor:1"
    assert attachment["anchor_message_id"] == ""


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
    assert "legacy_task_run_child_created" not in json.dumps(
        {
            "public_timeline": attachment.get("public_timeline", []),
            "task_projection": attachment.get("task_projection", {}),
        },
        ensure_ascii=False,
    )
