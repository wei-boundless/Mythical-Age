from __future__ import annotations

from tests.support.harness_runtime_facade_support import *

def test_public_stream_projection_emits_public_timeline_delta_for_tool_progress() -> None:
    projected = _project_public_stream_event(
        "runtime_step_summary",
        {
            "type": "runtime_step_summary",
            "step": "task_tool_executed",
            "status": "running",
            "public_progress_note": "正在写入 docs/plan.md",
            "event": {
                "event_id": "rtevt:tool-progress",
                "payload": {
                    "tool_name": "write_file",
                    "tool_target": "docs/plan.md",
                },
            },
        },
    )

    assert projected is not None
    _, data = projected
    item = data["public_timeline_delta"][0]
    assert item["kind"] == "work_action"
    assert item["action_kind"] == "edit"
    assert item["public_summary"] == "正在更新文件 docs/plan.md"

def test_public_stream_projection_hides_raw_shell_command_from_main_projection() -> None:
    projected = _project_public_stream_event(
        "runtime_step_summary",
        {
            "type": "runtime_step_summary",
            "step": "task_tool_executed",
            "status": "running",
            "event": {
                "event_id": "rtevt:shell-progress",
                "payload": {
                    "tool_name": "terminal",
                    "tool_target": 'New-Item -ItemType Directory -Path "frontend/src/app/adventure-island" -Force',
                },
            },
        },
    )

    assert projected is not None
    _, data = projected
    visible = json.dumps(data["public_timeline_delta"], ensure_ascii=False)
    item = data["public_timeline_delta"][0]
    assert item["kind"] == "work_action"
    assert item["action_kind"] == "prepare"
    assert item["public_summary"] == "正在准备输出 输出目录"
    assert "New-Item" not in visible
    assert "ItemType" not in visible
    assert "frontend/src/app/adventure-island" not in visible

def test_public_stream_projection_does_not_duplicate_handoff_status_delta() -> None:
    projected = _project_public_stream_event(
        "done",
        {
            "type": "done",
            "terminal_reason": "task_executor_scheduled",
            "answer_channel": "task_control",
            "runtime_task_run_id": "taskrun:test:handoff",
        },
    )

    assert projected is not None
    _, data = projected
    assert "public_timeline_delta" not in data

def test_public_stream_projection_uses_inspection_language_for_path_exists() -> None:
    projected = _project_public_stream_event(
        "runtime_step_summary",
        {
            "type": "runtime_step_summary",
            "step": "task_tool_executed",
            "status": "running",
            "public_progress_note": "已发起工具调用，正在等待工具返回：path_exists。",
            "event": {
                "event_id": "rtevt:path-exists",
                "payload": {
                    "tool_name": "path_exists",
                    "tool_target": "storage/task_environments/general/workspace/artifacts/mythical_sphere.html",
                },
            },
        },
    )

    assert projected is not None
    _, data = projected
    item = data["public_timeline_delta"][0]
    assert item["kind"] == "work_action"
    assert item["action_kind"] == "inspect"
    assert item["public_summary"] == "正在确认目标 artifacts/mythical_sphere.html"
    assert "storage/task_environments" not in json.dumps(item, ensure_ascii=False)

def test_public_stream_projection_emits_live_tool_admission_delta() -> None:
    projected = _project_public_stream_event(
        "model_action_admission",
        {
            "type": "model_action_admission",
            "event": {
                "event_id": "rtevt:tool-admission",
                "payload": {
                    "model_action_request": {
                        "action_type": "tool_call",
                        "public_progress_note": "已发起工具调用，正在等待工具返回：write_file。",
                        "tool_call": {
                            "name": "write_file",
                            "args": {
                                "path": "storage/task_environments/general/workspace/artifacts/football.html",
                            },
                        },
                    },
                },
            },
        },
    )

    assert projected is not None
    _, data = projected
    item = data["public_timeline_delta"][0]
    assert item["kind"] == "work_action"
    assert item["action_kind"] == "edit"
    assert item["public_summary"] == "正在更新文件 artifacts/football.html"

def test_public_stream_projection_rewrites_raw_edit_failure_observation() -> None:
    projected = _project_public_stream_event(
        "turn_tool_observation_recorded",
        {
            "type": "turn_tool_observation_recorded",
            "event": {
                "event_id": "rtevt:edit-failed",
                "payload": {
                    "tool_observation": {
                        "tool_name": "edit_file",
                        "status": "failed",
                        "text": "Edit failed: old_text not found. Read the current file content and retry with exact current text.",
                        "result_envelope": {
                            "tool_name": "edit_file",
                            "tool_args": {"path": "frontend/src/components/chat/ChatMessage.tsx"},
                        },
                    },
                },
            },
        },
    )

    assert projected is not None
    _, data = projected
    visible = json.dumps(data["public_timeline_delta"], ensure_ascii=False)
    item = data["public_timeline_delta"][0]
    assert item["kind"] == "work_action"
    assert item["action_kind"] == "edit"
    assert item["state"] == "error"
    assert item["observation"] == "文件更新未完成：当前内容与预期不一致，需要先读取最新片段再修改。"
    assert "Edit failed" not in visible
    assert "old_text" not in visible

def test_public_stream_projection_keeps_tool_admission_out_of_agent_feedback() -> None:
    projected = _project_public_stream_event(
        "model_action_admission",
        {
            "type": "model_action_admission",
            "event": {
                "event_id": "rtevt:agent-feedback-before-tool",
                "payload": {
                    "model_action_request": {
                        "action_type": "tool_call",
                        "public_progress_note": "我先定位主页面里动画循环的真实引用，再判断要改哪里。",
                        "tool_call": {
                            "name": "search_text",
                            "args": {"query": "requestAnimationFrame"},
                        },
                    },
                },
            },
        },
    )

    assert projected is not None
    _, data = projected
    items = data["public_timeline_delta"]
    assert [item["kind"] for item in items] == ["work_action"]
    assert items[0]["action_kind"] == "search"
    assert items[0]["public_summary"] == "正在搜索引用 requestAnimationFrame"
    assert "我先定位" not in json.dumps(items, ensure_ascii=False)

def test_public_stream_projection_projects_ask_user_as_status_not_body() -> None:
    projected = _project_public_stream_event(
        "model_action_admission",
        {
            "type": "model_action_admission",
            "event": {
                "event_id": "rtevt:ask-user-admission",
                "payload": {
                    "model_action_request": {
                        "action_type": "ask_user",
                        "public_progress_note": "需要用户补充信息后才能继续。",
                        "user_question": "请补充要优先审查的范围。",
                    },
                },
            },
        },
    )

    assert projected is not None
    _, data = projected
    items = data["public_timeline_delta"]
    assert len(items) == 1
    assert items[0]["kind"] == "status_update"
    assert items[0]["title"] == "等待补充信息"
    assert items[0]["detail"] == "请补充要优先审查的范围。"
    assert items[0].get("surface") != "body"
    assert not any(item["kind"] == "opening_judgment" for item in items)

def test_public_timeline_rebuild_keeps_ask_user_control_out_of_body_items() -> None:
    from harness.runtime.runtime_monitor_public_projection import project_public_timeline_from_events

    action = {
        "request_id": "act:ask-user",
        "action_type": "ask_user",
        "public_progress_note": "需要用户补充信息后才能继续。",
        "user_question": "请补充要优先审查的范围。",
    }
    items = project_public_timeline_from_events(
        [
            {
                "event_id": "rtevt:ask-user-request",
                "event_type": "model_action_request_received",
                "run_id": "turnrun:turn:session:ask:1",
                "payload": {"model_action_request": action},
            },
            {
                "event_id": "rtevt:ask-user-admission",
                "event_type": "model_action_admission_checked",
                "run_id": "turnrun:turn:session:ask:1",
                "payload": {"model_action_request": action},
            },
            {
                "event_id": "rtevt:ask-user-terminal",
                "event_type": "agent_turn_terminal",
                "run_id": "turnrun:turn:session:ask:1",
                "payload": {
                    "status": "completed",
                    "terminal_reason": "ask_user",
                    "content": "ask_user",
                },
            },
        ],
        run_id="turnrun:turn:session:ask:1",
        turn_run_id="turnrun:turn:session:ask:1",
        status="completed",
        final_answer="ask_user",
        assistant_text="ask_user",
    )

    assert len(items) == 1
    assert items[0]["kind"] == "status_update"
    assert items[0]["title"] == "等待补充信息"
    assert items[0]["detail"] == "请补充要优先审查的范围。"
    assert items[0]["state"] == "waiting"
    assert items[0]["phase"] == "waiting_user"

def test_session_timeline_does_not_rebuild_ask_user_progress_as_body_item() -> None:
    from harness.runtime.session_timeline import _public_timeline_from_progress_entries

    items = _public_timeline_from_progress_entries([
        {
            "id": "rtevt:ask-user-admission",
            "eventType": "model_action_admission_checked",
            "title": "等待补充信息",
            "body": "请补充要优先审查的范围。",
            "kind": "stage",
            "level": "waiting",
            "statusText": "waiting_user",
            "publicNote": "需要用户补充信息后才能继续。",
            "evidenceType": "model_action",
        }
    ])

    assert items == []

def test_public_stream_projection_simplifies_image_generation_tool() -> None:
    projected = _project_public_stream_event(
        "model_action_admission",
        {
            "type": "model_action_admission",
            "event": {
                "event_id": "rtevt:image-tool-admission",
                "payload": {
                    "model_action_request": {
                        "action_type": "tool_call",
                        "public_progress_note": "已发起工具调用，正在等待工具返回：image_generate。",
                        "tool_call": {
                            "name": "image_generate",
                            "args": {
                                "prompt": "hero concept art",
                            },
                        },
                    },
                },
            },
        },
    )

    assert projected is not None
    _, data = projected
    visible = json.dumps(data["public_timeline_delta"], ensure_ascii=False)
    item = data["public_timeline_delta"][0]
    assert item["kind"] == "work_action"
    assert item["action_kind"] == "image"
    assert item["public_summary"] == "正在生成图像"
    assert "image_generate" not in visible
    assert "正在等待工具返回" not in visible

def test_public_stream_projection_emits_agent_analysis_after_tool_result() -> None:
    projected = _project_public_stream_event(
        "runtime_step_summary",
        {
            "type": "runtime_step_summary",
            "step": "model_action_received:3",
            "status": "running",
            "public_progress_note": "已确认动画循环只在入口页面使用，下一步改入口组件即可。",
            "current_judgment": "已确认动画循环只在入口页面使用。",
            "event": {
                "event_id": "rtevt:model-analysis",
                "payload": {
                    "step": "model_action_received:3",
                    "public_progress_note": "已确认动画循环只在入口页面使用，下一步改入口组件即可。",
                    "public_action_state": {
                        "current_judgment": "已确认动画循环只在入口页面使用。",
                        "next_action": "修改入口组件并验证画面。",
                    },
                },
            },
        },
    )

    assert projected is not None
    _, data = projected
    item = data["public_timeline_delta"][0]
    assert item["kind"] == "observation_report"
    assert item["detail"] == "已确认动画循环只在入口页面使用。"
    assert item["implication"] == "修改入口组件并验证画面。"

def test_public_stream_projection_emits_live_tool_result_delta() -> None:
    projected = _project_public_stream_event(
        "turn_tool_observation_recorded",
        {
            "type": "turn_tool_observation_recorded",
            "event": {
                "event_id": "rtevt:tool-result",
                "payload": {
                    "tool_observation": {
                        "tool_name": "path_exists",
                        "status": "ok",
                        "text": "true",
                        "result_envelope": {
                            "tool_args": {
                                "path": "storage/task_environments/general/workspace/artifacts/football.html",
                            },
                            "structured_payload": {
                                "tool_result": {
                                    "kind": "path_exists",
                                    "path": "storage/task_environments/general/workspace/artifacts/football.html",
                                    "exists": True,
                                },
                            },
                        },
                    },
                },
            },
        },
    )

    assert projected is not None
    _, data = projected
    item = data["public_timeline_delta"][0]
    assert item["kind"] == "work_action"
    assert item["title"] == "已确认目标"
    assert item["subject_label"] == "artifacts/football.html"
    assert item["observation"] == "目标路径存在"

def test_public_stream_projection_summarizes_memory_search_without_internal_payload() -> None:
    projected = _project_public_stream_event(
        "turn_tool_observation_recorded",
        {
            "type": "turn_tool_observation_recorded",
            "event": {
                "event_id": "rtevt:memory-search",
                "payload": {
                    "tool_observation": {
                        "tool_name": "memory_search",
                        "status": "ok",
                        "text": json.dumps(
                            {
                                "authority": "formal_memory.memory_search_tool",
                                "query": "主角设定",
                                "result_count": 2,
                                "results": [{"summary": "主角来自边境城。"}],
                                "diagnostics": {"matched_version_count": 2},
                            },
                            ensure_ascii=False,
                        ),
                        "result_envelope": {
                            "tool_args": {"query": "主角设定"},
                        },
                    },
                },
            },
        },
    )

    assert projected is not None
    _, data = projected
    visible = json.dumps(data["public_timeline_delta"], ensure_ascii=False)
    item = data["public_timeline_delta"][0]
    assert item["kind"] == "work_action"
    assert item["title"] == "记忆检索已返回"
    assert item["subject_label"] == "相关记忆"
    assert item["observation"] == "记忆检索命中 2 条相关记录"
    assert "formal_memory.memory_search_tool" not in visible
    assert "diagnostics" not in visible
    assert "matched_version_count" not in visible
    assert "memory_search" not in visible

def test_public_stream_projection_summarizes_search_results_as_observation() -> None:
    projected = _project_public_stream_event(
        "turn_tool_observation_recorded",
        {
            "type": "turn_tool_observation_recorded",
            "event": {
                "event_id": "rtevt:search-result",
                "payload": {
                    "tool_observation": {
                        "tool_name": "search_text",
                        "status": "ok",
                        "text": "requestAnimationFrame",
                        "result_envelope": {
                            "tool_args": {"query": "requestAnimationFrame"},
                            "structured_payload": {
                                "matched_paths": [
                                    "frontend/src/app/game/page.tsx",
                                    "frontend/src/app/game/loop.ts",
                                ],
                            },
                        },
                    },
                },
            },
        },
    )

    assert projected is not None
    _, data = projected
    item = data["public_timeline_delta"][0]
    assert item["kind"] == "work_action"
    assert item["action_kind"] == "search"
    assert item["public_summary"] == "已搜索引用 requestAnimationFrame"
    assert item["observation"] == "已找到相关引用：frontend/src/app/game/page.tsx、frontend/src/app/game/loop.ts"

def test_public_stream_projection_hides_sandbox_boundary_command_failures() -> None:
    projected = _project_public_stream_event(
        "turn_tool_observation_recorded",
        {
            "type": "turn_tool_observation_recorded",
            "event": {
                "event_id": "rtevt:sandbox-boundary",
                "payload": {
                    "tool_observation": {
                        "tool_name": "terminal",
                        "status": "error",
                        "error": "Blocked: command references an absolute path outside the sandbox workspace.",
                        "text": "Blocked: command references an absolute path outside the sandbox workspace.",
                        "result_envelope": {
                            "tool_args": {
                                "command": 'cd "D:\\AI应用\\langchain-agent"; python -m pytest backend/tests/',
                            },
                            "structured_error": {
                                "message": "Blocked: command references an absolute path outside the sandbox workspace.",
                            },
                        },
                    },
                },
            },
        },
    )

    assert projected is not None
    _, data = projected
    assert "public_timeline_delta" not in data

def test_chat_public_projection_filters_internal_runtime_payloads() -> None:
    assert _project_public_stream_event(
        "runtime_assembly_compiled",
        {"type": "runtime_assembly_compiled", "runtime_assembly": {"backend_dir": "D:/secret"}},
    ) is None
    assert _project_public_stream_event(
        "runtime_invocation_packet",
        {
            "type": "runtime_invocation_packet",
            "packet_ref": "rtpacket:test",
            "compilation": {"packet": {"model_messages": [{"role": "system", "content": "hidden"}]}},
        },
    ) is None

    projected = _project_public_stream_event(
        "runtime_branch_decided",
        {
            "type": "runtime_branch_decided",
            "runtime_branch": {
                "branch_kind": "single_agent_turn",
                "invocation_kind": "single_agent_turn",
                "dispatch_target": "harness_runtime.single_agent_turn",
                "reason": "default_agent_runtime_turn",
                "control_capabilities": {"may_call_tools": False},
                "diagnostics": {"backend_dir": "D:/secret"},
            },
            "runtime_assembly": {"backend_dir": "D:/secret"},
            "model_messages": [{"role": "system", "content": "hidden"}],
        },
    )

    assert projected is not None
    public_event_type, data = projected
    assert public_event_type == "runtime_branch_decided"
    assert "runtime_assembly" not in data
    assert "model_messages" not in data
    branch = dict(data.get("runtime_branch") or {})
    assert branch == {
        "branch_kind": "single_agent_turn",
        "reason": "default_agent_runtime_turn",
    }


def test_chat_public_projection_keeps_runtime_status_as_status_only() -> None:
    projected = _project_public_stream_event(
        "runtime_status",
        {
            "type": "runtime_status",
            "title": "当前工作控制未执行",
            "detail": "边界校验未通过，模型会继续处理当前请求。",
            "state": "warning",
            "phase": "active_work_control",
            "runtime_event_id": "rtevt:active-work-control",
            "runtime_run_id": "turnrun:active-work-control",
            "created_at": 66,
            "event": {
                "event_id": "rtevt:active-work-control",
                "payload": {
                    "observation": {
                        "observation_kind": "active_work_control",
                        "admission": {"decision": "deny"},
                        "runtime_branch": {"diagnostics": {"secret": "hidden"}},
                    }
                },
            },
        },
    )

    assert projected is not None
    event_type, data = projected
    assert event_type == "runtime_status"
    assert data["runtime_event_id"] == "rtevt:active-work-control"
    serialized = json.dumps(data, ensure_ascii=False)
    assert "event" not in data
    assert "observation" not in serialized
    assert "admission" not in serialized
    assert "hidden" not in serialized


def test_chat_public_projection_redacts_internal_packet_fields_from_allowed_events() -> None:
    projected = _project_public_stream_event(
        "agent_turn_terminal",
        {
            "type": "agent_turn_terminal",
            "event": {
                "event_type": "agent_turn_completed",
                "payload": {
                    "status": "completed",
                    "runtime_assembly": {"backend_dir": "D:/secret"},
                    "action_request": {
                        "final_answer": "ok",
                        "model_messages": [{"role": "system", "content": "hidden"}],
                    },
                },
            },
            "compilation": {"packet": {"model_messages": [{"role": "system", "content": "hidden"}]}},
        },
    )

    assert projected is not None
    _event_type, data = projected
    serialized = json.dumps(data, ensure_ascii=False)
    assert "model_messages" not in serialized
    assert "runtime_assembly" not in serialized
    assert "compilation" not in serialized
    assert "D:/secret" not in serialized

def test_chat_stream_runtime_refs_separate_turn_run_from_task_run() -> None:
    refs = _runtime_run_refs_from_event(
        {
            "type": "agent_turn_terminal",
            "event": {
                "run_id": "turnrun:session-a:1",
                "payload": {
                    "turn_run": {"turn_run_id": "turnrun:session-a:1"},
                    "task_run": {"task_run_id": "taskrun:turn:session-a:1:formal"},
                },
            },
        }
    )

    assert refs == {
        "turn_run_id": "turnrun:session-a:1",
        "task_run_id": "taskrun:turn:session-a:1:formal",
    }

def test_chat_stream_runtime_refs_expose_active_turn_from_task_lifecycle_refs() -> None:
    refs = _runtime_run_refs_from_event(
        {
            "type": "task_run_lifecycle_started",
            "event": {
                "run_id": "taskrun:turn:session-a:1:formal",
                "refs": {
                    "turn_ref": "turn:session-a:1",
                },
                "payload": {
                    "task_run": {"task_run_id": "taskrun:turn:session-a:1:formal"},
                },
            },
        }
    )

    assert refs == {
        "turn_run_id": "",
        "task_run_id": "taskrun:turn:session-a:1:formal",
        "active_turn_id": "turn:session-a:1",
    }

def test_chat_stream_runtime_refs_do_not_treat_bare_turn_ref_as_active_task_turn() -> None:
    refs = _runtime_run_refs_from_event(
        {
            "type": "agent_turn_terminal",
            "event": {
                "run_id": "turnrun:session-a:2",
                "refs": {
                    "turn_ref": "turn:session-a:2",
                },
                "payload": {
                    "turn_run": {"turn_run_id": "turnrun:session-a:2"},
                },
            },
        }
    )

    assert refs == {
        "turn_run_id": "turnrun:session-a:2",
        "task_run_id": "",
    }

def test_chat_stream_runtime_refs_supplement_bound_active_task_for_runtime_status() -> None:
    runtime = build_harness_runtime()
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:active-control-public-ref",
        session_id="session-active-control-public-ref",
    )
    host = runtime.single_agent_runtime_host
    host.active_turn_registry.start(
        session_id="session-active-control-public-ref",
        turn_id="turn:active-control-public-ref:1",
        turn_run_id="turnrun:active-control-public-ref:1",
    )
    host.active_turn_registry.bind_task_run(
        session_id="session-active-control-public-ref",
        turn_id="turn:active-control-public-ref:1",
        task_run_id=task_run_id,
        state="waiting_executor",
    )

    refs = _runtime_run_refs_for_public_event(
        SimpleNamespace(harness_runtime=runtime),
        "session-active-control-public-ref",
        {
            "type": "runtime_status",
            "phase": "active_work_control",
            "state": "running",
        },
    )

    assert refs == {
        "turn_run_id": "turnrun:active-control-public-ref:1",
        "task_run_id": "taskrun:active-control-public-ref",
        "active_turn_id": "turn:active-control-public-ref:1",
    }

def test_chat_public_projection_hides_turn_trace_only_harness_start() -> None:
    assert _project_public_stream_event(
        "harness_run_started",
        {
            "type": "harness_run_started",
            "turn_run": {
                "turn_run_id": "turnrun:session-a:1",
                "execution_runtime_kind": "single_agent_turn",
            },
            "event": {
                "run_id": "turnrun:session-a:1",
                "payload": {
                    "turn_run": {"turn_run_id": "turnrun:session-a:1"},
                },
            },
        },
    ) is None

    projected = _project_public_stream_event(
        "harness_run_started",
        {
            "type": "harness_run_started",
            "task_run": {"task_run_id": "taskrun:session-a:1", "status": "running"},
            "event": {
                "run_id": "taskrun:session-a:1",
                "payload": {"task_run": {"task_run_id": "taskrun:session-a:1"}},
            },
        },
    )
    assert projected is not None
    public_event_type, data = projected
    assert public_event_type == "harness_run_started"
    assert dict(data.get("task_run") or {}).get("task_run_id") == "taskrun:session-a:1"

def test_global_live_monitor_groups_waiting_completed_and_failed_runs(monkeypatch) -> None:
    monkeypatch.setattr("harness.runtime.single_agent_host.time.time", lambda: 1000.0)
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    host.state_index.upsert_task_run(TaskRun(
        task_run_id="taskrun:old-running",
        session_id="session-monitor",
        task_id="task:old",
        status="running",
        created_at=100.0,
        updated_at=200.0,
        execution_runtime_kind="single_agent_task",
    ))
    host.state_index.upsert_task_run(TaskRun(
        task_run_id="taskrun:failed-stale",
        session_id="session-monitor",
        task_id="task:failed",
        status="failed",
        created_at=800.0,
        updated_at=900.0,
        execution_runtime_kind="single_agent_task",
        terminal_reason="internal_error",
    ))
    host.state_index.upsert_task_run(TaskRun(
        task_run_id="taskrun:old-waiting-executor",
        session_id="session-monitor",
        task_id="task:old-waiting-executor",
        status="waiting_executor",
        created_at=300.0,
        updated_at=400.0,
        execution_runtime_kind="single_agent_task",
        terminal_reason="task_executor_rebuild_pending",
    ))
    host.state_index.upsert_task_run(TaskRun(
        task_run_id="taskrun:fresh-waiting-executor",
        session_id="session-monitor",
        task_id="task:fresh-waiting-executor",
        status="waiting_executor",
        created_at=940.0,
        updated_at=980.0,
        execution_runtime_kind="single_agent_task",
        terminal_reason="waiting_executor",
    ))
    host.state_index.upsert_task_run(TaskRun(
        task_run_id="taskrun:waiting-approval",
        session_id="session-monitor",
        task_id="task:waiting-approval",
        status="waiting_approval",
        created_at=300.0,
        updated_at=400.0,
        execution_runtime_kind="single_agent_task",
        terminal_reason="waiting_approval",
    ))

    monitor = host.list_global_live_monitor(limit=20)

    assert {item["task_run_id"] for item in monitor["task_runs"]} == {
        "taskrun:fresh-waiting-executor",
    }
    buckets = {item["task_run_id"]: item["bucket"] for item in monitor["task_runs"]}
    assert {item["task_run_id"] for item in monitor["buckets"]["waiting"]} == {
        "taskrun:fresh-waiting-executor",
    }
    assert monitor["buckets"]["diagnostics"] == []
    assert monitor["buckets"]["failed"] == []
    assert buckets["taskrun:fresh-waiting-executor"] == "waiting"
    assert monitor["summary"]["total"] == 1
    assert monitor["summary"]["running"] == 0
    assert monitor["summary"]["waiting"] == 1
    assert monitor["summary"]["failed"] == 0
    assert monitor["summary"]["diagnostics"] == 0
    assert monitor["summary"]["action_required"] == 0

def test_task_run_detail_monitor_exposes_step_summary_and_recent_terminal_status(monkeypatch) -> None:
    monkeypatch.setattr("harness.runtime.single_agent_host.time.time", lambda: 1000.0)
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run = TaskRun(
        task_run_id="taskrun:recent-completed",
        session_id="session-monitor",
        task_id="task:recent-completed",
        status="completed",
        created_at=600.0,
        updated_at=990.0,
        execution_runtime_kind="single_agent_task",
        terminal_reason="completed",
        diagnostics={
            "artifact_refs": [{"path": "storage/task/result.md"}],
            "latest_step": "final_self_review",
            "latest_step_status": "completed",
            "latest_step_summary": "agent 已完成最终自检并确认交付物存在。",
        },
    )
    host.state_index.upsert_task_run(task_run)
    host.event_log.append(
        task_run.task_run_id,
        "step_summary_recorded",
        payload={
            "task_run_id": task_run.task_run_id,
            "step": "final_self_review",
            "status": "completed",
            "summary": "agent 已完成最终自检并确认交付物存在。",
        },
    )

    global_monitor = host.list_global_live_monitor(limit=20)
    item = host.get_task_run_live_monitor(task_run.task_run_id)
    assert item is not None

    assert item["task_run_id"] == task_run.task_run_id
    assert item["bucket"] == "completed"
    assert item["latest_step_name"] == "final_self_review"
    assert item["latest_step_status"] == "completed"
    assert item["latest_step_summary"] == "助手已完成最终自检并确认交付物存在。"
    _assert_no_visible_runtime_internals(item["latest_step_summary"])
    assert item["artifact_count"] == 1
    assert item["resource_class"] == "static"
    assert item["ended_at"] == 990.0
    assert item["duration_seconds"] == 390.0
    assert global_monitor["summary"]["completed"] == 0
    assert task_run.task_run_id not in {item["task_run_id"] for item in global_monitor["task_runs"]}
    assert global_monitor["buckets"]["completed"] == []

def test_session_runtime_timeline_keeps_completed_task_attachment() -> None:
    from harness.runtime.session_timeline import build_session_runtime_timeline

    runtime = build_harness_runtime(
        model_runtime=_TaskExecutorSequenceModelRuntime(
            [
                _action_request(
                    action_type="respond",
                    final_answer="Timeline final answer.",
                    public_progress_note="我已完成 timeline 验证，正在整理最终回复。",
                )
            ],
            agent_turn_action_request=_action_request(action_type="respond", final_answer="unused"),
        )
    )
    host = runtime.single_agent_runtime_host
    contract = TaskRunContract(
        contract_id="task-contract:timeline",
        contract_source="test",
        user_visible_goal="验证 timeline attachment。",
        task_run_goal="完成后仍保留运行附件。",
        completion_criteria=("final answer 已形成",),
    )
    contract_ref = host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
    lifecycle = TaskLifecycleRecord(
        task_run_id="taskrun:turn:session-timeline:1:abc",
        contract_ref=contract_ref,
        status="waiting_executor",
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
            status="waiting_executor",
            created_at=1.0,
            updated_at=1.0,
            diagnostics={"turn_id": "turn:session-timeline:1", "contract": contract.to_dict()},
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
    assert attachment["run_id"] == lifecycle.task_run_id
    assert attachment["task_run_id"] == lifecycle.task_run_id
    assert attachment["anchor_turn_id"] == "turn:session-timeline:1"
    assert attachment["status"] == "completed"
    assert attachment["final_answer"] == "Timeline final answer."
    assert attachment["anchor_role"] == "assistant"
    assert attachment["debug_trace_ref"] == lifecycle.task_run_id
    assert "public_timeline" in attachment
    assert attachment["progress_entries"]
    assert any(
        item.get("publicNote") == "我已完成 timeline 验证，正在整理最终回复。"
        for item in attachment["progress_entries"]
    )
    assert any(
        item.get("agentBrief") == "Timeline final answer."
        for item in attachment["progress_entries"]
    )
    visible_attachment_text = json.dumps(
        {
            "summary": attachment["summary"],
            "latest_step_summary": attachment["latest_step_summary"],
            "progress_entries": [
                {"title": item.get("title"), "body": item.get("body"), "publicNote": item.get("publicNote")}
                for item in attachment["progress_entries"]
            ],
        },
        ensure_ascii=False,
    )
    _assert_no_visible_runtime_internals(visible_attachment_text)

def test_session_runtime_timeline_projects_tool_observation_as_agent_visible_observation() -> None:
    from harness.runtime.session_timeline import build_session_runtime_timeline

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
                    "result": json.dumps(
                        {
                            "ok": False,
                            "error": "Image API request timed out",
                            "retryable": True,
                        },
                        ensure_ascii=False,
                    ),
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
            "summary": "工具调用已完成，正在根据结果继续。",
            "agent_brief_output": json.dumps(
                {
                    "ok": False,
                    "error": "Image API request timed out",
                    "retryable": True,
                },
                ensure_ascii=False,
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
        "step_summary_recorded",
        payload={
            "task_run_id": task_run_id,
            "step": "model_action_received:4",
            "status": "running",
            "summary": "重试生成主角美术图片，调整参数避免超时。",
            "public_progress_note": "重试生成主角美术图片，调整参数避免超时。",
            "public_action_state": {
                "current_judgment": "远程生图超时，但可以重试。",
                "next_action": "降低并发后继续生成资源。",
            },
        },
        refs={"turn_ref": "turn:session-observation:1"},
    )

    timeline = build_session_runtime_timeline(
        session_id="session-observation",
        history={"messages": []},
        runtime_host=host,
    )

    entries = timeline["runtime_attachments"][0]["progress_entries"]
    public_timeline = timeline["runtime_attachments"][0]["public_timeline"]
    assert [item["kind"] for item in entries] == ["observation", "model"]
    assert entries[0]["kind"] == "observation"
    assert entries[0]["title"] == "图像结果已返回"
    assert entries[0]["level"] == "error"
    assert entries[0]["body"] == "工具返回失败：Image API request timed out"
    assert entries[1]["kind"] == "model"
    assert entries[0]["toolName"] == "image_generate"
    assert entries[1]["body"] == "重试生成主角美术图片，调整参数避免超时。"
    assert entries[1]["meta"] == [
        {"label": "模型说明", "value": "远程生图超时，但可以重试。"},
        {"label": "计划动作", "value": "降低并发后继续生成资源。"},
    ]
    assert any(
        item.get("kind") == "opening_judgment"
        and item.get("text") == "重试生成主角美术图片，调整参数避免超时。"
        for item in public_timeline
    )

def test_session_runtime_timeline_projects_turn_run_tool_progress() -> None:
    from harness.runtime.session_timeline import build_session_runtime_timeline

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
        "model_action_admission_checked",
        payload={
            "turn_id": turn_id,
            "model_action_request": {
                "request_id": "model-action:turn-timeline:write",
                "turn_id": turn_id,
                "action_type": "tool_call",
                "public_progress_note": "已发起工具调用，正在等待工具返回：write_file。",
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
                {"role": "user", "content": "写文件", "turn_id": turn_id},
                {"role": "assistant", "content": "完成", "turn_id": turn_id, "id": "message:assistant"},
            ]
        },
        runtime_host=host,
    )

    attachment = timeline["runtime_attachments"][0]
    entries = attachment["progress_entries"]
    assert attachment["run_id"] == turn_run_id
    assert attachment["turn_run_id"] == turn_run_id
    assert attachment["task_run_id"] == ""
    assert attachment["anchor_turn_id"] == turn_id
    assert attachment["anchor_message_id"] == "message:assistant"
    assert attachment["debug_trace_ref"] == turn_run_id
    assert [item["title"] for item in entries] == [
        "正在写入 docs/turn.md",
        "写入完成 docs/turn.md",
    ]
    assert entries[1]["kind"] == "tool"
    assert entries[1]["toolName"] == "write_file"
    assert entries[1]["statusText"] == "已完成"
    assert entries[1]["artifacts"] == [{"label": "产物", "path": "docs/turn.md"}]
    assert any(
        item.get("kind") == "work_action"
        and item.get("action_kind") == "edit"
        and item.get("public_summary") == "已更新文件 docs/turn.md"
        for item in attachment["public_timeline"]
    )

def test_session_runtime_timeline_derives_turn_anchor_from_structural_task_run_id() -> None:
    from harness.runtime.session_timeline import build_session_runtime_timeline

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

def test_session_runtime_timeline_emits_stable_anchor_message_id_for_original_assistant_turn() -> None:
    from harness.runtime.session_timeline import build_session_runtime_timeline

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
                {"role": "user", "content": "开始旧任务"},
                {"role": "assistant", "content": "旧任务已接管", "id": "message:old-assistant"},
                {"role": "user", "content": "新的继续"},
                {"role": "assistant", "content": "新的回复", "id": "message:new-assistant"},
            ]
        },
        runtime_host=host,
    )

    attachment = timeline["runtime_attachments"][0]
    assert attachment["anchor_turn_id"] == "turn:session-anchor-message:1"
    assert attachment["anchor_message_id"] == "message:old-assistant"
    assert attachment["anchor_role"] == "assistant"

def test_session_runtime_timeline_ignores_legacy_child_event_as_control_anchor() -> None:
    from harness.runtime.session_timeline import build_session_runtime_timeline

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
                {"role": "user", "content": "开始任务"},
                {"role": "assistant", "content": "任务已接管"},
                {"role": "user", "content": "继续"},
                {"role": "assistant", "content": "我会继续处理"},
                {"role": "user", "content": "预算已经调大，请继续完成。"},
                {"role": "assistant", "content": "收到，继续执行。"},
            ]
        },
        runtime_host=host,
    )

    attachment = next(
        item for item in timeline["runtime_attachments"]
        if item["task_run_id"] == task_run_id
    )
    assert attachment["run_id"] == task_run_id
    assert attachment["anchor_turn_id"] == "turn:session-child-anchor:8"
    assert not any(item.get("eventType") == "legacy_task_run_child_created" for item in attachment["progress_entries"])

def test_tool_call_status_does_not_replace_agent_public_judgment() -> None:
    action = ModelActionRequest(
        request_id="model-action:test:tool",
        turn_id="taskrun:test",
        action_type="tool_call",
        public_progress_note="我看到缺少入口文件，下一步先读取目录确认项目结构。",
        public_action_state={
            "current_judgment": "需要先读文件确认结构。",
            "next_action": "读取 index.html。",
        },
        tool_call={"tool_name": "read_file", "args": {"path": "index.html"}},
    )

    summary = _tool_call_progress_summary(action)

    assert summary == "读取文件：index.html。"
    assert "我看到缺少入口文件" not in summary

def test_public_runtime_progress_preserves_user_level_task_wording() -> None:
    from harness.runtime.public_progress import public_runtime_progress_summary

    assert public_runtime_progress_summary("不需要开启正式任务。") == "不需要开启正式任务。"
    assert public_runtime_progress_summary("正式任务生命周期已完成。") == "正式任务生命周期已完成。"

def test_task_observation_projection_separates_stale_and_active_failures() -> None:
    from harness.loop.task_executor import _observations_for_packet

    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:test:observation-projection"
    stale_fingerprint = {
        "tool_registry_hash": "tools-v1",
        "tool_config_hash": "image-config-v1",
        "sandbox_policy_hash": "sandbox-v1",
        "permission_policy_hash": "permission-v1",
        "backend_config_hash": "backend-v1",
    }
    current_fingerprint = {
        **stale_fingerprint,
        "tool_config_hash": "image-config-v2",
        "backend_config_hash": "backend-v2",
    }
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

    context = _observations_for_packet(host, task_run_id, current_fingerprint=current_fingerprint)
    projection = context["execution_state"]["system_projection"]

    assert projection["historical_failures"][0]["tool_name"] == "image_generate"
    assert projection["historical_failures"][0]["current_runtime_fact"] is False
    assert projection["active_failures"][0]["tool_name"] == "read_file"
    assert projection["active_failures"][0]["error"]["message"] == "file missing"

def test_task_observation_projection_adds_non_blocking_exploration_advisory() -> None:
    from harness.loop.task_executor import _observations_for_packet

    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:test:exploration-advisory"
    fingerprint = {
        "tool_registry_hash": "tools-v1",
        "tool_config_hash": "tool-config-v1",
        "sandbox_policy_hash": "sandbox-v1",
        "permission_policy_hash": "permission-v1",
        "backend_config_hash": "backend-v1",
    }
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

    context = _observations_for_packet(host, task_run_id, current_fingerprint=fingerprint)
    advisory = context["execution_state"]["system_projection"]["exploration_advisory"]

    assert advisory["triggered"] is True
    assert advisory["non_blocking"] is True
    assert advisory["consecutive_exploration_tool_calls"] == 6
    assert advisory["recent_tools"][-1]["tool_name"] == "read_file"
    assert advisory["recommended_action"] == "pause_serial_exploration_and_consider_agent_todo_plus_codebase_searcher_split"

def test_task_observation_projection_extracts_structured_error_from_tool_json_result() -> None:
    from harness.loop.task_executor import _observations_for_packet

    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:test:image-json-error"
    fingerprint = {
        "tool_registry_hash": "tools-v1",
        "tool_config_hash": "image-config-v1",
        "sandbox_policy_hash": "sandbox-v1",
        "permission_policy_hash": "permission-v1",
        "backend_config_hash": "backend-v1",
    }
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
                    "tool_args": {"prompt": "mine", "quality": "low"},
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

    context = _observations_for_packet(host, task_run_id, current_fingerprint=fingerprint)
    projection = context["execution_state"]["system_projection"]

    assert projection["current_facts"] == []
    assert projection["active_failures"][0]["tool_name"] == "image_generate"
    assert projection["active_failures"][0]["error"]["code"] == "image_provider_transient_error"
    assert projection["active_failures"][0]["error"]["origin"] == "image_provider"

def test_task_observation_projection_treats_missing_fingerprint_failure_as_historical() -> None:
    from harness.loop.task_executor import _observations_for_packet

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

    context = _observations_for_packet(host, task_run_id, current_fingerprint={"tool_config_hash": "current"})
    projection = context["execution_state"]["system_projection"]

    assert projection["active_failures"] == []
    assert projection["historical_failures"][0]["tool_name"] == "image_generate"
    assert projection["historical_failures"][0]["reason"] == "missing_runtime_fingerprint"

def test_task_observation_projection_does_not_classify_historical_success_as_failure() -> None:
    from harness.loop.task_executor import _observations_for_packet

    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:test:historical-success"
    host.event_log.append(
        task_run_id,
        "task_tool_observation_recorded",
        payload={
            "observation": {
                "observation_id": "obs:todo-init",
                "task_run_id": task_run_id,
                "observation_type": "tool_result",
                "source": "system:agent_todo",
                "payload": {
                    "tool_name": "system",
                    "result": json.dumps({"status": "ok", "items": []}),
                },
            }
        },
    )

    context = _observations_for_packet(host, task_run_id, current_fingerprint={"tool_config_hash": "current"})
    projection = context["execution_state"]["system_projection"]

    assert projection["active_failures"] == []
    assert projection["historical_failures"] == []
    assert projection["last_action_receipts"][0]["status"] == "ok"
    assert projection["last_action_receipts"][0]["visibility"] == "historical"

def test_task_observation_projection_marks_superseded_success_as_historical() -> None:
    from harness.loop.task_executor import _observations_for_packet

    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:test:superseded-success"
    stale_fingerprint = {
        "tool_registry_hash": "tools-v1",
        "tool_config_hash": "config-v1",
        "sandbox_policy_hash": "sandbox-v1",
        "permission_policy_hash": "perm-v1",
        "backend_config_hash": "backend-v1",
    }
    current_fingerprint = {
        **stale_fingerprint,
        "sandbox_policy_hash": "sandbox-v2",
    }
    host.event_log.append(
        task_run_id,
        "task_tool_observation_recorded",
        payload={
            "observation": {
                "observation_id": "obs:stale-glob",
                "task_run_id": task_run_id,
                "observation_type": "tool_result",
                "source": "tool:glob_paths",
                "payload": {
                    "tool_name": "glob_paths",
                    "tool_args": {"pattern": "**/*roguelike*/**/*"},
                    "result": "docs/experiments/roguelike_long_task/assets/test.txt",
                    "runtime_fingerprint": stale_fingerprint,
                },
            }
        },
    )

    context = _observations_for_packet(host, task_run_id, current_fingerprint=current_fingerprint)
    projection = context["execution_state"]["system_projection"]

    assert projection["current_facts"] == []
    historical = context["packet_observations"][0]
    assert historical["tool_name"] == "glob_paths"
    assert dict(historical["runtime_freshness"])["reason"] == "superseded_by_runtime_change"

def test_task_observation_projection_keeps_success_artifact_evidence() -> None:
    from harness.loop.task_executor import _observations_for_packet

    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:test:observation-artifact"
    fingerprint = {"tool_config_hash": "current"}
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
                        "tool_args": {"prompt": "hero"},
                        "status": "ok",
                        "text": "generated",
                        "artifact_refs": [{"path": "storage/generated/images/hero.png", "kind": "image"}],
                        "structured_payload": {
                            "artifact_refs": [{"path": "storage/generated/images/hero.png", "kind": "image"}]
                        },
                    },
                },
            }
        },
    )

    context = _observations_for_packet(host, task_run_id, current_fingerprint=fingerprint)
    projection = context["execution_state"]["system_projection"]

    assert projection["current_facts"][0]["tool_name"] == "image_generate"
    assert projection["artifact_evidence"][0]["path"] == "storage/generated/images/hero.png"
    assert context["artifact_refs"][0]["kind"] == "image"

def test_task_observation_projection_ignores_already_projected_records() -> None:
    from harness.loop.task_executor import _observations_for_packet

    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    context = _observations_for_packet(
        host,
        "taskrun:test:projected-record",
        current_fingerprint={"tool_config_hash": "current"},
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
