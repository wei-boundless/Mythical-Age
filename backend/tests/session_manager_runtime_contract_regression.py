from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sessions import SessionManager


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


def test_session_manager_agent_history_can_include_compressed_context(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    manager = SessionManager(backend_dir)
    session_id = manager.create_session(title="Compressed")["id"]
    payload = manager.get_history(session_id)
    payload["compressed_context"] = "此前摘要"
    manager._write_payload(session_id, payload)
    manager.append_messages(session_id, [{"role": "user", "content": "继续"}])

    history = manager.load_session_for_agent(session_id, include_compressed_context=True)

    assert history == [
        {"role": "assistant", "content": "[Compressed session context]\n此前摘要"},
        {"role": "user", "content": "继续"},
    ]



