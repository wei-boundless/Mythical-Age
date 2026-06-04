from __future__ import annotations

import json
from types import SimpleNamespace

from harness.runtime.progress_presenter import build_progress_presentation
from harness.runtime.public_chat_timeline import build_public_chat_timeline
from harness.runtime.public_progress import public_runtime_progress_summary


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
    assert unit["evidence"][0]["summary"] == "目标文件尚未存在，路径检查已完成。"
    assert unit["next_action"] == "检查 calculator.html 是否存在。"

    visible_text = json.dumps(
        {"mission": presentation["mission"], "work_units": presentation["work_units"]},
        ensure_ascii=False,
    )
    assert "false" not in visible_text.lower()
    assert "工具调用已完成，正在根据结果继续" not in visible_text
    assert any(item.get("raw_preview") == "false" for item in presentation["technical_trace"])


def test_progress_presenter_marks_nested_result_envelope_failure_as_error() -> None:
    task_run = _task_run()
    events = [
        {
            "event_id": "rtevt:nested-failure",
            "run_id": "taskrun:turn:session-progress:1:abc",
            "event_type": "task_tool_observation_recorded",
            "offset": 1,
            "created_at": 1.0,
            "payload": {
                "observation": {
                    "observation_id": "obs:nested-failure",
                    "source": "tool:read_file",
                    "action_request_ref": "act:nested-failure",
                    "payload": {
                        "tool_name": "read_file",
                        "tool_args": {"path": "missing.txt"},
                        "result_envelope": {
                            "status": "failed",
                            "text": "file not found",
                        },
                    },
                }
            },
            "refs": {"action_request_ref": "act:nested-failure", "observation_ref": "obs:nested-failure"},
        }
    ]

    presentation = build_progress_presentation(events=events, task_run=task_run, monitor={})

    assert presentation["work_units"]
    unit = presentation["work_units"][0]
    assert unit["state"] == "error"
    assert unit["evidence"][0]["status"] == "error"
    assert "file not found" in unit["evidence"][0]["summary"]


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
    assert presentation["technical_trace"] == []


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


def test_public_progress_scrubs_legacy_provider_failure_details() -> None:
    text = public_runtime_progress_summary(
        "当前处理已停止：图像生成服务不可用（Image generation is not configured），"
        "无法生成合同要求的像素风场景图（target_id: five-floor-dungeon-pixel-tower-*）。"
        "下一步使用指定 target_id 继续。"
        "当前 image_generate 的 agent_auto_retry_allowed 为 false，agent_retry_policy 为 do_not_auto_retry，无法通过重试解决。"
    )

    assert "当前步骤遇到阻塞" in text
    assert "生图服务没有配置" in text
    assert "Image generation is not configured" not in text
    assert "target_id" not in text
    assert "图像目标" in text
    assert "agent_auto_retry_allowed" not in text
    assert "do_not_auto_retry" not in text


def test_public_chat_timeline_projects_tool_activity_without_raw_trace() -> None:
    timeline = build_public_chat_timeline(
        progress_presentation={
            "mission": {"state": "running", "current_action": "检查目标文件。"},
            "work_units": [
                {
                    "unit_id": "workunit:path-check",
                    "kind": "inspect_path",
                    "title": "确认 artifact 路径",
                    "state": "completed",
                    "evidence": [
                        {
                            "label": "path_exists",
                            "summary": "目标文件尚未存在，路径检查已完成。",
                            "status": "negative_evidence",
                        }
                    ],
                    "technical_trace_refs": ["rtevt:obs"],
                }
            ],
        },
        status="running",
    )

    assert timeline == [
        {
            "item_id": "workunit:path-check",
            "kind": "tool_activity",
            "title": "确认 artifact 路径",
            "detail": "目标文件尚未存在，路径检查已完成。",
            "state": "done",
            "trace_refs": ["rtevt:obs"],
        }
    ]
    assert "false" not in json.dumps(timeline, ensure_ascii=False).lower()


def test_public_chat_timeline_suppresses_generic_terminal_receipts() -> None:
    timeline = build_public_chat_timeline(
        progress_presentation={
            "mission": {
                "state": "completed",
                "current_action": "回答已生成并写回会话",
                "closeout_summary": "completed",
            },
            "work_units": [
                {
                    "unit_id": "done",
                    "kind": "terminal",
                    "title": "done",
                    "state": "completed",
                    "judgment": "回答已生成并写回会话",
                    "technical_trace_refs": ["agent_turn_terminal"],
                }
            ],
        },
        status="completed",
        terminal_reason="completed",
        assistant_text="任务完成。",
    )

    visible = json.dumps(timeline, ensure_ascii=False)
    assert timeline == []
    assert "回答已生成并写回会话" not in visible
    assert "agent_turn_terminal" not in visible


def test_public_chat_timeline_deduplicates_final_summary_against_assistant_text() -> None:
    timeline = build_public_chat_timeline(
        progress_presentation={
            "mission": {
                "state": "completed",
                "closeout_summary": "已完成五层地下塔的核心结构、关键交互和验收记录。",
            },
            "work_units": [],
        },
        final_answer="已完成五层地下塔的核心结构、关键交互和验收记录。",
        status="completed",
        assistant_text="已完成五层地下塔的核心结构、关键交互和验收记录。",
    )

    assert timeline == []


def test_public_chat_timeline_projects_provider_failure_as_blocked_item() -> None:
    timeline = build_public_chat_timeline(
        progress_presentation={
            "mission": {
                "state": "failed",
                "current_action": "图像生成这一步卡住了，因为生图服务还没有可用配置。",
                "next_action": "确认生图服务配置后重试。",
            },
            "work_units": [],
        },
        status="failed",
        terminal_reason="task_executor_schedule_failed",
    )

    assert timeline == [
        {
            "item_id": timeline[0]["item_id"],
            "kind": "blocked",
            "text": "图像生成这一步卡住了，因为生图服务还没有可用配置。",
            "state": "error",
        }
    ]


def test_duplicate_tool_guard_is_not_public_activity() -> None:
    events = [
        {
            "event_id": "rtevt:duplicate",
            "run_id": "taskrun:turn:session-progress:1:abc",
            "event_type": "task_duplicate_tool_call_guarded",
            "offset": 1,
            "created_at": 1.0,
            "payload": {
                "observation": {
                    "observation_id": "obs:duplicate",
                    "source": "system:duplicate_tool_call_guard",
                    "action_request_ref": "act:stat",
                    "payload": {
                        "tool_name": "duplicate_tool_call_guard",
                        "error_code": "duplicate_read_only_tool_call",
                    },
                }
            },
            "refs": {"action_request_ref": "act:stat", "observation_ref": "obs:duplicate"},
        },
        {
            "event_id": "rtevt:duplicate-step",
            "run_id": "taskrun:turn:session-progress:1:abc",
            "event_type": "step_summary_recorded",
            "offset": 2,
            "created_at": 2.0,
            "payload": {
                "step": "task_duplicate_tool_call_guarded:2",
                "status": "running",
                "summary": "重复工具调用没有提供新增信息，已要求模型改用已有观察、换验证方式或收口。",
            },
            "refs": {"action_request_ref": "act:stat", "observation_ref": "obs:duplicate"},
        },
    ]

    presentation = build_progress_presentation(events=events, task_run=_task_run(), monitor={})
    timeline = build_public_chat_timeline(progress_presentation=presentation, status="running")

    visible = json.dumps({"presentation": presentation, "timeline": timeline}, ensure_ascii=False)
    assert presentation["work_units"] == []
    assert timeline == []
    assert "重复工具调用" not in visible


def test_agent_feedback_survives_tool_activity_projection() -> None:
    events = [
        {
            "event_id": "rtevt:model-action",
            "run_id": "taskrun:turn:session-progress:1:abc",
            "event_type": "model_action_request_received",
            "offset": 1,
            "created_at": 1.0,
            "payload": {
                "model_action_request": {
                    "request_id": "act:stat",
                    "action_type": "tool_call",
                    "public_progress_note": "我先检查文件写入权限和可用路径，然后创建游戏文件。",
                    "tool_calls": [{"tool_name": "stat_path", "args": {"path": "output"}}],
                }
            },
            "refs": {"action_request_ref": "act:stat"},
        },
        {
            "event_id": "rtevt:tool-start",
            "run_id": "taskrun:turn:session-progress:1:abc",
            "event_type": "step_summary_recorded",
            "offset": 2,
            "created_at": 2.0,
            "payload": {
                "step": "task_tool_batch_started:1",
                "status": "running",
                "summary": "正在使用路径信息工具处理 output。",
            },
            "refs": {"action_request_ref": "act:stat"},
        },
    ]

    presentation = build_progress_presentation(events=events, task_run=_task_run(), monitor={})
    timeline = build_public_chat_timeline(progress_presentation=presentation, status="running")

    assert [item["kind"] for item in timeline] == ["assistant_text", "tool_activity"]
    assert timeline[0]["title"] == "我先检查文件写入权限和可用路径，然后创建游戏文件。"
    assert timeline[1]["title"] == "检查路径信息"


def test_public_progress_scrubs_bounded_retry_policy_details() -> None:
    text = public_runtime_progress_summary(
        "当前处理已停止：image_generation_failed，"
        "当前 image_generate 的 agent_auto_retry_allowed 为 true，"
        "agent_retry_policy 为 bounded_retry_with_backoff。"
    )

    assert "当前步骤遇到阻塞" in text
    assert "生图失败" in text
    assert "agent_auto_retry_allowed" not in text
    assert "bounded_retry_with_backoff" not in text
    assert "有限退避重试" in text
