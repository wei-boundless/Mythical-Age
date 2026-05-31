from __future__ import annotations

import asyncio
from pathlib import Path

from api import task_system as tasks_api
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
                            "prompt_id": "environment.custom.api.v1",
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
        assert environment["environment_boundary"]["boundary_contract"]["environment_prompts_source"] == "task_environment_config"
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
