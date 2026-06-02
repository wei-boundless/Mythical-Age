from __future__ import annotations

import json
from types import SimpleNamespace

from harness.runtime.progress_presenter import build_progress_presentation


def _task_run(**kwargs: object) -> SimpleNamespace:
    return SimpleNamespace(
        status=kwargs.get("status", "running"),
        diagnostics=kwargs.get(
            "diagnostics",
            {
                "contract": {
                    "user_visible_goal": "创建 calculator.html 并验证路径可用",
                }
            },
        ),
    )


def test_progress_presenter_translates_path_exists_false_without_visible_raw_bool() -> None:
    task_run = _task_run()
    events = [
        {
            "event_id": "rtevt:model-action",
            "run_id": "taskrun:turn:session-progress:1:abc",
            "event_type": "model_action_request_received",
            "offset": 1,
            "created_at": 1.0,
            "payload": {
                "model_action_request": {
                    "request_id": "act:path-check",
                    "action_type": "tool_call",
                    "public_progress_note": "我先确认目标文件是否已经存在。",
                    "public_action_state": {
                        "current_judgment": "需要先确认 artifact 路径状态。",
                        "next_action": "检查 calculator.html 是否存在。",
                    },
                    "tool_call": {
                        "name": "path_exists",
                        "args": {"path": "storage/task_environments/general/workspace/calculator.html"},
                    },
                }
            },
            "refs": {"action_request_ref": "act:path-check"},
        },
        {
            "event_id": "rtevt:model-step",
            "run_id": "taskrun:turn:session-progress:1:abc",
            "event_type": "step_summary_recorded",
            "offset": 2,
            "created_at": 2.0,
            "payload": {
                "step": "model_action_received:1",
                "status": "running",
                "summary": "正在执行必要操作，随后会根据结果继续。",
                "public_progress_note": "我先确认目标文件是否已经存在。",
                "public_action_state": {
                    "current_judgment": "需要先确认 artifact 路径状态。",
                    "next_action": "检查 calculator.html 是否存在。",
                },
            },
            "refs": {"action_request_ref": "act:path-check"},
        },
        {
            "event_id": "rtevt:observation",
            "run_id": "taskrun:turn:session-progress:1:abc",
            "event_type": "task_tool_observation_recorded",
            "offset": 3,
            "created_at": 3.0,
            "payload": {
                "observation": {
                    "observation_id": "obs:path-check",
                    "source": "tool:path_exists",
                    "action_request_ref": "act:path-check",
                    "payload": {
                        "tool_name": "path_exists",
                        "tool_args": {"path": "storage/task_environments/general/workspace/calculator.html"},
                        "result": "false",
                    },
                }
            },
            "refs": {"action_request_ref": "act:path-check", "observation_ref": "obs:path-check"},
        },
        {
            "event_id": "rtevt:observation-step",
            "run_id": "taskrun:turn:session-progress:1:abc",
            "event_type": "step_summary_recorded",
            "offset": 4,
            "created_at": 4.0,
            "payload": {
                "step": "task_tool_observation_recorded:1",
                "status": "running",
                "summary": "工具调用已完成，正在根据结果继续。",
                "agent_brief_output": "false",
            },
            "refs": {"observation_ref": "obs:path-check", "tool_name": "path_exists"},
        },
    ]

    presentation = build_progress_presentation(events=events, task_run=task_run, monitor={})

    assert presentation["mission"]["goal"] == "创建 calculator.html 并验证路径可用"
    assert presentation["work_units"]
    assert len(presentation["work_units"]) == 1
    unit = presentation["work_units"][0]
    assert unit["title"] == "确认 artifact 路径"
    assert unit["judgment"] == "需要先确认 artifact 路径状态。"
    assert unit["evidence"][0]["summary"] == "目标文件尚未存在，路径检查成功；下一步需要创建。"
    assert unit["next_action"].startswith("创建")

    visible_text = json.dumps(
        {"mission": presentation["mission"], "work_units": presentation["work_units"]},
        ensure_ascii=False,
    )
    assert "false" not in visible_text.lower()
    assert "工具调用已完成，正在根据结果继续" not in visible_text
    assert any(item.get("raw_preview") == "false" for item in presentation["technical_trace"])


def test_progress_presenter_suppresses_empty_runtime_sync_steps() -> None:
    presentation = build_progress_presentation(
        events=[
            {
                "event_id": "rtevt:packet",
                "run_id": "taskrun:turn:session-progress:1:abc",
                "event_type": "step_summary_recorded",
                "offset": 1,
                "created_at": 1.0,
                "payload": {
                    "step": "task_execution_packet_compiled:1",
                    "status": "running",
                    "summary": "已同步最新进展。",
                    "public_progress_note": "已同步最新进展。",
                },
                "refs": {"runtime_invocation_packet_ref": "packet:1"},
            },
            {
                "event_id": "rtevt:model",
                "run_id": "taskrun:turn:session-progress:1:abc",
                "event_type": "step_summary_recorded",
                "offset": 2,
                "created_at": 2.0,
                "payload": {
                    "step": "model_action_received:2",
                    "status": "running",
                    "summary": "开始验证交付文件。",
                    "public_action_state": {
                        "current_judgment": "需要补齐交付证据。",
                        "next_action": "读取目标文件并检查关键内容。",
                    },
                },
                "refs": {"action_request_ref": "act:verify"},
            },
        ],
        task_run=_task_run(),
        monitor={},
    )

    visible_text = json.dumps(
        {"mission": presentation["mission"], "work_units": presentation["work_units"]},
        ensure_ascii=False,
    )
    assert "已同步最新进展" not in visible_text
    assert "需要补齐交付证据" in visible_text
    assert presentation["technical_trace"][0]["raw_preview"] == "已同步最新进展。"


def test_progress_presenter_keeps_tool_error_as_evidence_not_split_trace_card() -> None:
    events = [
        {
            "event_id": "rtevt:action",
            "run_id": "taskrun:turn:session-progress:1:abc",
            "event_type": "model_action_request_received",
            "offset": 1,
            "created_at": 1.0,
            "payload": {
                "model_action_request": {
                    "request_id": "act:image",
                    "action_type": "tool_call",
                    "public_action_state": {
                        "current_judgment": "需要生成主角资源。",
                        "next_action": "调用图像生成工具。",
                    },
                    "tool_call": {"name": "image_generate", "args": {"prompt": "hero"}},
                }
            },
            "refs": {"action_request_ref": "act:image"},
        },
        {
            "event_id": "rtevt:obs",
            "run_id": "taskrun:turn:session-progress:1:abc",
            "event_type": "task_tool_observation_recorded",
            "offset": 2,
            "created_at": 2.0,
            "payload": {
                "observation": {
                    "observation_id": "obs:image",
                    "source": "tool:image_generate",
                    "action_request_ref": "act:image",
                    "payload": {
                        "tool_name": "image_generate",
                        "tool_args": {"prompt": "hero"},
                        "result": json.dumps({"ok": False, "error": "Image API request timed out"}),
                    },
                }
            },
            "refs": {"action_request_ref": "act:image", "observation_ref": "obs:image"},
        },
    ]

    presentation = build_progress_presentation(events=events, task_run=_task_run(), monitor={})

    assert len(presentation["work_units"]) == 1
    unit = presentation["work_units"][0]
    assert unit["judgment"] == "需要生成主角资源。"
    assert unit["state"] == "error"
    assert unit["evidence"] == [
        {
            "label": "image_generate",
            "summary": "工具返回失败：Image API request timed out",
            "status": "error",
        }
    ]
    assert len(unit["technical_trace_refs"]) == 2


def test_progress_presenter_adds_closeout_summary_when_task_completed() -> None:
    presentation = build_progress_presentation(
        events=[
            {
                "event_id": "rtevt:finish",
                "run_id": "taskrun:turn:session-progress:1:abc",
                "event_type": "task_run_lifecycle_finished",
                "offset": 1,
                "created_at": 1.0,
                "payload": {"task_run": {"status": "completed", "terminal_reason": "completed"}},
                "refs": {},
            }
        ],
        task_run=_task_run(
            status="completed",
            diagnostics={
                "contract": {"user_visible_goal": "完成五层地下塔长任务验收"},
                "final_answer": "已完成五层地下塔的核心结构、关键交互和验收记录。",
            },
        ),
        monitor={},
    )

    assert presentation["mission"]["state"] == "completed"
    assert presentation["mission"]["closeout_summary"] == "已完成五层地下塔的核心结构、关键交互和验收记录。"
    assert presentation["mission"]["current_action"] == "已完成五层地下塔的核心结构、关键交互和验收记录。"
    assert presentation["work_units"][-1]["kind"] == "terminal"
    assert presentation["work_units"][-1]["judgment"] == "已完成五层地下塔的核心结构、关键交互和验收记录。"
