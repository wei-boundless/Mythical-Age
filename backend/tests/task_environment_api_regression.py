from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException

from api import sessions as sessions_api
from api import task_system as tasks_api
from sessions import SessionManager
from tests.support.runtime_stubs import RuntimeBaseDirStub


def test_task_environment_api_upserts_and_deletes_configured_environment(tmp_path: Path) -> None:
    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: RuntimeBaseDirStub(tmp_path)  # type: ignore[assignment]
    try:
        payload = asyncio.run(
            tasks_api.upsert_task_system_environment_group(
                "environment_group.custom_api",
                tasks_api.TaskEnvironmentGroupUpsertRequest(
                    group_id="environment_group.custom_api",
                    title="Custom API",
                    description="API managed environment group.",
                ),
            )
        )
        assert any(
            item["group_id"] == "environment_group.custom_api"
            for item in payload["task_environment_management"]["groups"]
        )

        payload = asyncio.run(
            tasks_api.upsert_task_system_environment(
                "env.custom.api",
                tasks_api.TaskEnvironmentUpsertRequest(
                    environment_id="env.custom.api",
                    title="API Environment",
                    group_id="environment_group.custom_api",
                    environment_prompts=[
                        {
                            "prompt_id": "environment.custom.api",
                            "content": "你处在 API 配置的任务环境中。",
                        }
                    ],
                    file_management={"file_profile_refs": ["file_profile.general_workspace"]},
                    resource_space={"storage_namespace": "custom/api"},
                    memory_space={
                        "environment_memory_refs": ["memory.custom.api"],
                        "project_knowledge_refs": ["knowledge.custom.api"],
                        "retrieval_index_refs": ["retrieval.custom.api"],
                    },
                    execution_policy={"shell_execution_policy": "denied"},
                ),
            )
        )
        environment = next(
            item
            for item in payload["task_environment_management"]["environments"]
            if item["record"]["environment_id"] == "env.custom.api"
        )
        assert environment["environment_prompts"][0]["content"].startswith("你处在 API 配置")
        assert (
            environment["environment_boundary"]["boundary_contract"]["environment_prompts_source"]
            == "resource_prompt_library_and_task_environment_config"
        )
        assert environment["storage_space"]["storage_namespace"] == "custom/api"
        assert environment["memory_space"]["environment_memory_refs"] == ["memory.custom.api"]
        assert environment["memory_space"]["project_knowledge_refs"] == ["knowledge.custom.api"]
        assert environment["memory_space"]["retrieval_index_refs"] == ["retrieval.custom.api"]

        payload = asyncio.run(tasks_api.delete_task_system_environment("env.custom.api"))
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    assert not any(
        item["record"]["environment_id"] == "env.custom.api"
        for item in payload["task_environment_management"]["environments"]
    )


def test_task_environment_catalog_endpoint_reads_registry(tmp_path: Path) -> None:
    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: RuntimeBaseDirStub(tmp_path)  # type: ignore[assignment]
    try:
        payload = asyncio.run(tasks_api.task_environment_catalog())
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    environment_ids = {item["record"]["environment_id"] for item in payload["environments"]}
    assert "env.general.workspace" in environment_ids
    assert "env.coding.vibe_workspace" in environment_ids
    assert payload["summary"]["environment_count"] >= 4


def test_session_active_task_environment_api_validates_registry(tmp_path: Path) -> None:
    runtime = RuntimeBaseDirStub(tmp_path)
    runtime.session_manager = SessionManager(tmp_path)  # type: ignore[attr-defined]
    session = runtime.session_manager.create_session(title="Global chat")  # type: ignore[attr-defined]
    session_id = session["id"]
    original = sessions_api.require_runtime
    sessions_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    try:
        state = asyncio.run(
            sessions_api.set_session_active_task_environment(
                session_id,
                sessions_api.ActiveTaskEnvironmentRequest(
                    task_environment_id="env.coding.vibe_workspace",
                    environment_label="Vibe Coding Workspace",
                    source="workspace-mode",
                ),
                workspace_view=None,
                task_environment_id=None,
                project_id=None,
            )
        )
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                sessions_api.set_session_active_task_environment(
                    session_id,
                    sessions_api.ActiveTaskEnvironmentRequest(
                        task_environment_id="env.missing.workspace",
                    ),
                    workspace_view=None,
                    task_environment_id=None,
                    project_id=None,
                )
            )
    finally:
        sessions_api.require_runtime = original  # type: ignore[assignment]

    assert state["active_task_environment"]["task_environment_id"] == "env.coding.vibe_workspace"
    assert exc_info.value.status_code == 404


def test_session_permission_mode_api_updates_conversation_state(tmp_path: Path) -> None:
    runtime = RuntimeBaseDirStub(tmp_path)
    runtime.session_manager = SessionManager(tmp_path)  # type: ignore[attr-defined]
    session = runtime.session_manager.create_session(title="Permission session")  # type: ignore[attr-defined]
    session_id = session["id"]
    original = sessions_api.require_runtime
    sessions_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    try:
        state = asyncio.run(
            sessions_api.set_session_permission_mode(
                session_id,
                sessions_api.SessionPermissionModeRequest(mode="plan"),
                workspace_view=None,
                task_environment_id=None,
                project_id=None,
            )
        )
    finally:
        sessions_api.require_runtime = original  # type: ignore[assignment]

    assert state["permission_mode"] == "plan"
    assert runtime.session_manager.get_history(session_id)["conversation_state"]["permission_mode"] == "plan"  # type: ignore[attr-defined]
