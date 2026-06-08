from __future__ import annotations

import pytest
from pydantic import ValidationError

from api.chat import ChatRequest, _query_request_from_payload


def test_chat_request_maps_environment_binding_without_task_selection() -> None:
    payload = ChatRequest(
        message="检查当前文件。",
        session_id="session-env-binding",
        environment_binding={
            "task_environment_id": "env.coding.vibe_workspace",
            "environment_id": "env.coding.vibe_workspace",
            "binding_kind": "conversation_active_task_environment",
        },
    )

    request = _query_request_from_payload(payload, session_id="session-env-binding")

    assert request.environment_binding["task_environment_id"] == "env.coding.vibe_workspace"
    assert request.runtime_contract == {}


def test_chat_request_rejects_legacy_task_selection_payload() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(
            message="检查当前文件。",
            session_id="session-env-binding",
            task_selection={"task_environment_id": "env.coding.vibe_workspace"},
        )
