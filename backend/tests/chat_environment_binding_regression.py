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


def test_chat_request_maps_explicit_runtime_contract() -> None:
    payload = ChatRequest(
        message="启动任务。",
        session_id="session-runtime-contract",
        runtime_contract={
            "system_issued_contract": True,
            "task_contract": {
                "contract_id": "contract:cli:start",
                "user_visible_goal": "执行 CLI 启动任务。",
                "task_run_goal": "执行 CLI 启动任务。",
                "completion_criteria": ["任务启动成功"],
            },
        },
    )

    request = _query_request_from_payload(payload, session_id="session-runtime-contract")

    assert request.runtime_contract["system_issued_contract"] is True
    assert request.runtime_contract["task_contract"]["contract_id"] == "contract:cli:start"


def test_chat_request_rejects_legacy_task_selection_payload() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(
            message="检查当前文件。",
            session_id="session-env-binding",
            task_selection={"task_environment_id": "env.coding.vibe_workspace"},
        )
