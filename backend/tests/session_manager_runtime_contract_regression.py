from __future__ import annotations

import concurrent.futures
import json
import logging
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pytest

import sessions as sessions_module
from sessions import SessionManager, SessionPayloadCorrupt, SessionStorageError, SessionTaskBindingConflict


def test_session_manager_exposes_runtime_session_record(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    manager = SessionManager(backend_dir)
    session = manager.create_session(title="Runtime contract")
    session_id = session["id"]
    manager.append_messages(
        session_id,
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi", "image": {"src": "/x.png"}},
        ],
    )

    record = manager.load_session_record(session_id)

    assert record["id"] == session_id
    assert record["title"] == "Runtime contract"
    assert record["compressed_context"] == ""
    assert [item["content"] for item in record["messages"]] == ["hello", "hi"]
    assert record["task_binding"] == {}


def test_session_manager_reports_corrupt_payload_and_keeps_list_available(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    manager = SessionManager(backend_dir)
    session = manager.create_session(title="Corrupt session")
    manager._session_path(session["id"]).write_text("{not-json", encoding="utf-8")

    with pytest.raises(SessionPayloadCorrupt):
        manager.get_history(session["id"])

    caplog.set_level(logging.WARNING, logger="sessions")
    sessions = manager.list_sessions()
    assert sessions[0]["id"] == session["id"]
    assert sessions[0]["storage_status"] == "unreadable"
    assert "corrupt session payload" in sessions[0]["storage_error"]
    assert "Skipping unreadable session payload" in caplog.text


def test_session_manager_atomic_write_preserves_existing_payload_on_replace_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    manager = SessionManager(backend_dir)
    session = manager.create_session(title="Original")
    session_path = manager._session_path(session["id"])
    original_payload = json.loads(session_path.read_text(encoding="utf-8"))

    def fail_replace(_src: object, _dst: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(sessions_module.os, "replace", fail_replace)

    with pytest.raises(SessionStorageError):
        manager.rename_session(session["id"], "Broken")

    assert json.loads(session_path.read_text(encoding="utf-8")) == original_payload
    assert list(session_path.parent.glob(f".{session_path.name}.*.tmp")) == []


def test_session_manager_serializes_concurrent_message_appends(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    manager = SessionManager(backend_dir)
    session_id = manager.create_session(title="Concurrent")["id"]
    expected = {f"message-{index}" for index in range(40)}

    def append_message(index: int) -> None:
        manager.append_messages(session_id, [{"role": "user", "content": f"message-{index}"}])

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        list(executor.map(append_message, range(40)))

    actual = {item["content"] for item in manager.get_history(session_id)["messages"]}
    assert actual == expected


def test_session_manager_binds_one_graph_task_instance_per_session(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    manager = SessionManager(backend_dir)
    session = manager.create_session(
        title="Graph session",
        scope={
            "workspace_view": "task_environment",
            "task_environment_id": "env.creation.writing",
            "project_id": "proj:novel",
        },
    )
    session_id = session["id"]

    binding = manager.bind_session_graph_instance(
        session_id,
        graph_run_id="grun:novel:1",
        task_run_id="taskrun:novel:1",
        graph_id="graph.novel",
        graph_harness_config_id="ghcfg:novel",
        session_scope={
            "workspace_view": "task_environment",
            "task_environment_id": "env.creation.writing",
            "project_id": "proj:novel",
        },
    )

    assert binding["graph_run_id"] == "grun:novel:1"
    assert manager.get_history(session_id)["task_binding"]["graph_run_id"] == "grun:novel:1"
    assert manager.bind_session_graph_instance(session_id, graph_run_id="grun:novel:1") == binding
    with pytest.raises(SessionTaskBindingConflict):
        manager.bind_session_graph_instance(session_id, graph_run_id="grun:novel:2")


def test_session_manager_agent_history_filters_to_model_messages(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    manager = SessionManager(backend_dir)
    session_id = manager.create_session(title="Agent history")["id"]
    manager.append_messages(
        session_id,
        [
            {"role": "system", "content": "hidden"},
            {"role": "user", "content": "visible user"},
            {"role": "assistant", "content": ""},
            {"role": "assistant", "content": "visible assistant", "image": {"src": "/x.png"}},
        ],
    )

    history = manager.load_session_for_agent(session_id)

    assert history == [
        {"role": "user", "content": "visible user"},
        {"role": "assistant", "content": "visible assistant"},
    ]


def test_session_manager_records_conversation_environment_state_without_polluting_agent_history(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    manager = SessionManager(backend_dir)
    session = manager.create_session(title="Environment state")
    session_id = session["id"]

    state = manager.set_active_task_environment(
        session_id,
        {
            "task_environment_id": "env.coding.vibe_workspace",
            "environment_label": "Vibe Coding Workspace",
            "source": "workspace-mode",
        },
    )
    manager.append_messages(session_id, [{"role": "user", "content": "写一个测试", "turn_id": "turn:test:1"}])
    snapshot = manager.update_turn_environment_snapshot(
        session_id,
        turn_id="turn:test:1",
        snapshot={
            "turn_id": "turn:test:1",
            "task_environment_id": "env.coding.vibe_workspace",
            "environment_kind": "coding",
            "environment_prompt_refs": ["environment.coding.vibe_workspace.orientation"],
            "runtime_assembly_id": "rtasm:test",
        },
    )

    history = manager.get_history(session_id)
    agent_history = manager.load_session_for_agent(session_id)

    assert state["active_task_environment"]["task_environment_id"] == "env.coding.vibe_workspace"
    assert history["conversation_state"]["active_task_environment"]["task_environment_id"] == "env.coding.vibe_workspace"
    assert snapshot["updated"] is True
    assert history["messages"][0]["turn_environment_snapshot"]["runtime_assembly_id"] == "rtasm:test"
    assert agent_history == [{"role": "user", "content": "写一个测试"}]


def test_session_manager_records_permission_mode_as_conversation_state(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    manager = SessionManager(backend_dir)
    session = manager.create_session(title="Permission state")
    session_id = session["id"]

    assert session["conversation_state"]["permission_mode"] == "full_access"

    state = manager.set_permission_mode(session_id, "plan")
    history = manager.get_history(session_id)

    assert state["permission_mode"] == "plan"
    assert history["conversation_state"]["permission_mode"] == "plan"
    assert manager.load_session_for_agent(session_id) == []


def test_session_manager_agent_history_never_injects_compressed_context_as_message(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    manager = SessionManager(backend_dir)
    session_id = manager.create_session(title="Compressed")["id"]
    payload = manager.get_history(session_id)
    payload["compressed_context"] = "此前摘要"
    manager._write_payload(session_id, payload)
    manager.append_messages(session_id, [{"role": "user", "content": "继续"}])

    history = manager.load_session_for_agent(session_id)

    assert history == [
        {"role": "user", "content": "继续"},
    ]


def test_session_manager_keeps_api_transcript_hidden_but_loadable(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    manager = SessionManager(backend_dir)
    session_id = manager.create_session(title="DeepSeek protocol")["id"]
    manager.append_messages(
        session_id,
        [
            {"role": "user", "content": "查天气", "turn_id": "turn:1"},
            {"role": "assistant", "content": "结果", "turn_id": "turn:1"},
        ],
    )
    manager.append_api_messages(
        session_id,
        [
            {"role": "user", "content": "查天气", "turn_id": "turn:1"},
            {
                "role": "assistant",
                "content": "",
                "turn_id": "turn:1",
                "reasoning_content": "hidden reasoning",
                "tool_calls": [{"id": "call_1", "name": "get_date", "args": {}, "type": "tool_call"}],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "2026-04-20", "turn_id": "turn:1"},
            {"role": "assistant", "content": "结果", "turn_id": "turn:1"},
        ],
    )

    public_history = manager.get_history(session_id)
    api_history = manager.load_session_for_api(session_id)

    assert "api_transcript" not in public_history
    assert len(public_history["messages"]) == 2
    assert api_history[1]["reasoning_content"] == "hidden reasoning"
    assert api_history[1]["tool_calls"][0]["id"] == "call_1"
    assert api_history[2]["role"] == "tool"


def test_session_manager_public_history_filters_structured_tool_protocol_messages(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    manager = SessionManager(backend_dir)
    session_id = manager.create_session(title="Tool protocol filtering")["id"]
    payload = manager._read_payload(session_id)
    payload["messages"] = [
        {"role": "user", "content": "修复 bug", "turn_id": "turn:1"},
        {
            "role": "assistant",
            "content": "",
            "turn_id": "turn:1",
            "tool_calls": [{"id": "call_1", "name": "edit_file", "args": {}, "type": "tool_call"}],
        },
        {
            "role": "tool",
            "content": "Edit failed: old_text not found",
            "turn_id": "turn:1",
            "name": "edit_file",
            "tool_call_id": "call_1",
        },
        {"role": "assistant", "content": "已完成修复。", "turn_id": "turn:2"},
    ]
    manager._write_payload(session_id, payload)

    public_messages = manager.load_session(session_id)
    public_text = "\n".join(item["content"] for item in public_messages)

    assert [item["role"] for item in public_messages] == ["user", "assistant"]
    assert "Edit failed" not in public_text
    assert manager.load_session_for_agent(session_id) == [
        {"role": "user", "content": "修复 bug"},
        {"role": "assistant", "content": "已完成修复。"},
    ]

    truncated = manager.truncate_messages_from(session_id, 1)

    assert truncated["messages"] == [{"role": "user", "content": "修复 bug", "turn_id": "turn:1"}]




