from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sessions import SessionManager
from scripts.migrate_legacy_task_session_scope import migrate_legacy_task_session_scope


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


def test_legacy_task_workspace_view_migrates_to_task_environment_scope(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    manager = SessionManager(backend_dir)
    session = manager.create_session(
        title="Legacy task session",
        scope={"workspace_view": "task", "task_environment_id": "env.development.sandbox"},
    )

    dry_run = migrate_legacy_task_session_scope(backend_dir=backend_dir, dry_run=True)
    result = migrate_legacy_task_session_scope(backend_dir=backend_dir, dry_run=False)
    history = manager.get_history(session["id"])

    assert dry_run["changed_count"] == 1
    assert result["changed_count"] == 1
    assert history["scope"] == {
        "workspace_view": "task_environment",
        "task_environment_id": "env.development.sandbox",
        "project_id": "",
    }



