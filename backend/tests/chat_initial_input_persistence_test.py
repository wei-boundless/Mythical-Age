from __future__ import annotations

from types import SimpleNamespace

from harness.entrypoint.models import HarnessRuntimeRequest
from harness.entrypoint.runtime_facade import HarnessRuntimeFacade, _history_without_current_user_request
from sessions import SessionManager


def _facade_with_session_manager(session_manager: SessionManager) -> HarnessRuntimeFacade:
    facade = HarnessRuntimeFacade.__new__(HarnessRuntimeFacade)
    facade.session_manager = session_manager
    facade.memory_facade = SimpleNamespace()
    return facade


def test_chat_run_schedule_precommits_initial_user_message_before_execution(tmp_path) -> None:
    session_manager = SessionManager(tmp_path)
    session_id = "session:initial-input"
    session_manager.create_session(session_id=session_id)
    facade = _facade_with_session_manager(session_manager)

    prepared = facade.prepare_chat_run_request_for_schedule(
        HarnessRuntimeRequest(
            session_id=session_id,
            message="刷新后还在",
            client_message_id="user:client:initial",
        ),
        stream_run_id="strun:initial",
    )

    turn_id = prepared.runtime_profile["precommitted_user_message_turn_id"]
    assert turn_id == f"turn:{session_id}:1"
    assert prepared.runtime_profile["precommitted_user_message_id"] == "user:client:initial"

    messages = session_manager.load_session(session_id)
    assert len(messages) == 1
    assert messages[0]["created_at"] > 0
    assert messages[0] | {"created_at": "<time>"} == {
        "id": "user:client:initial",
        "message_id": "user:client:initial",
        "role": "user",
        "content": "刷新后还在",
        "turn_id": turn_id,
        "attachments": [],
        "source": "harness.entrypoint.chat_run_schedule",
        "client_message_id": "user:client:initial",
        "created_at": "<time>",
    }
    api_messages = session_manager.load_session_for_api(session_id)
    assert len(api_messages) == 1
    assert api_messages[0]["created_at"] > 0
    assert api_messages[0] | {"created_at": "<time>"} == {
        "role": "user",
        "content": "刷新后还在",
        "turn_id": turn_id,
        "created_at": "<time>",
    }


def test_runtime_user_commit_is_idempotent_for_precommitted_initial_input(tmp_path) -> None:
    session_manager = SessionManager(tmp_path)
    session_id = "session:initial-input-idempotent"
    session_manager.create_session(session_id=session_id)
    facade = _facade_with_session_manager(session_manager)

    prepared = facade.prepare_chat_run_request_for_schedule(
        HarnessRuntimeRequest(
            session_id=session_id,
            message="不要重复写入",
            client_message_id="user:client:dedupe",
        ),
        stream_run_id="strun:dedupe",
    )
    turn_id = str(prepared.runtime_profile["precommitted_user_message_turn_id"])

    facade._commit_user_message(
        session_id=session_id,
        content="不要重复写入",
        api_content="不要重复写入",
        turn_id=turn_id,
        message_id="user:client:dedupe",
        client_message_id="user:client:dedupe",
    )

    assert len(session_manager.load_session(session_id)) == 1
    assert len(session_manager.load_session_for_api(session_id)) == 1


def test_precommitted_initial_input_is_excluded_from_model_history(tmp_path) -> None:
    session_manager = SessionManager(tmp_path)
    session_id = "session:initial-input-history"
    session_manager.create_session(session_id=session_id)
    facade = _facade_with_session_manager(session_manager)

    prepared = facade.prepare_chat_run_request_for_schedule(
        HarnessRuntimeRequest(
            session_id=session_id,
            message="当前这条不要进历史",
            client_message_id="user:client:history",
        ),
        stream_run_id="strun:history",
    )
    turn_id = str(prepared.runtime_profile["precommitted_user_message_turn_id"])

    assert _history_without_current_user_request(
        session_manager.load_session_for_agent(session_id),
        turn_id=turn_id,
        user_message="当前这条不要进历史",
    ) == []
    assert _history_without_current_user_request(
        session_manager.load_session_for_api(session_id),
        turn_id=turn_id,
        user_message="当前这条不要进历史",
    ) == []
