from __future__ import annotations

import asyncio

from api.chat import ChatRequest, _query_request_from_payload
from harness.entrypoint.models import HarnessRuntimeRequest
from harness.runtime.request_facts import build_turn_input_facts
from tests.support.runtime_stubs import SingleMessageModelRuntimeStub, build_harness_runtime


def test_chat_request_passes_editor_context_into_runtime_request_and_turn_facts() -> None:
    editor_context = {
        "source": "vscode",
        "captured_at": "2026-06-04T00:00:00Z",
        "workspace_roots": ["D:/repo"],
        "active_file": {
            "path": "D:/repo/backend/main.py",
            "language_id": "python",
            "dirty": True,
            "selection": {
                "start": {"line": 1, "character": 0},
                "end": {"line": 2, "character": 4},
                "text": "print('hi')",
                "truncated": False,
            },
        },
        "visible_files": [{"path": "D:/repo/backend/main.py", "language_id": "python", "dirty": True}],
        "diagnostics": [],
    }

    payload = ChatRequest(
        message="检查当前文件。",
        session_id="session-vscode",
        editor_context=editor_context,
    )
    request = _query_request_from_payload(payload, session_id="session-vscode")
    facts = build_turn_input_facts(
        session_id=request.session_id,
        turn_id="turn:session-vscode:1",
        user_message=request.message,
        editor_context=request.editor_context,
    )

    assert request.editor_context["source"] == "vscode"
    assert request.editor_context["active_file"]["dirty"] is True
    assert facts.to_dict()["editor_context"]["active_file"]["path"] == "D:/repo/backend/main.py"


def test_task_run_created_from_turn_freezes_parent_editor_context() -> None:
    editor_context = {
        "source": "vscode",
        "workspace_roots": ["D:/repo"],
        "active_file": {
            "path": "D:/repo/backend/harness/entrypoint/runtime_facade.py",
            "language_id": "python",
            "dirty": True,
        },
        "visible_files": [],
        "diagnostics": [],
    }
    action_request = {
        "authority": "harness.loop.model_action_request",
        "request_id": "model-action:test:request-task-run",
        "turn_id": "",
        "action_type": "request_task_run",
        "public_progress_note": "已接收任务，准备启动持续处理。",
        "public_action_state": {
            "current_judgment": "当前请求需要持续执行。",
            "next_action": "启动任务运行。",
            "completion_status": "working",
        },
        "task_contract_seed": {
            "user_visible_goal": "修复当前打开文件的问题。",
            "task_run_goal": "修复当前打开文件的问题。",
            "completion_criteria": ["当前打开文件问题已处理并说明结果。"],
        },
        "completion_contract": {},
        "permission_request": {},
        "diagnostics": {"test_action_request": True},
    }
    runtime = build_harness_runtime(
        model_runtime=SingleMessageModelRuntimeStub(agent_turn_action_request=action_request),
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-vscode-task-freeze",
                message="按当前打开文件启动任务。",
                editor_context=editor_context,
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    task_runs = list(runtime.single_agent_runtime_host.state_index.list_session_task_runs("session-vscode-task-freeze"))
    task_run = task_runs[0]
    diagnostics = dict(task_run.diagnostics or {})

    assert any(event.get("type") == "task_run_lifecycle_started" for event in events)
    assert diagnostics["editor_context"]["source"] == "vscode"
    assert diagnostics["editor_context"]["active_file"]["path"] == "D:/repo/backend/harness/entrypoint/runtime_facade.py"
    assert diagnostics["editor_context_binding"]["source"] == "parent_turn"
