from __future__ import annotations

import asyncio
from pathlib import Path

from api import task_system as tasks_api
from task_system.environments.kind_templates import TaskEnvironmentKindTemplateRepository
from tests.support.runtime_stubs import RuntimeBaseDirStub


def test_environment_kind_template_repository_persists_policy_template(tmp_path: Path) -> None:
    repository = TaskEnvironmentKindTemplateRepository(tmp_path)

    template = repository.upsert(
        {
            "kind_id": "qa_review",
            "title": "QA Review",
            "description": "Review environments with bounded files and explicit review prompts.",
            "group_id": "environment_group.general",
            "allowed_resource_refs": ["file_profile.general_workspace", "review.memory"],
            "default_sandbox_policy": {"shell_policy": "denied"},
            "default_execution_policy": {"browser_execution_policy": "denied"},
            "default_risk_policy": {"default_permission_mode": "review_gate"},
            "default_prompt_cache_scope": "static_environment",
            "allowed_task_graph_kinds": ["coordination"],
            "enabled": True,
        }
    )

    loaded = TaskEnvironmentKindTemplateRepository(tmp_path).get("qa_review")

    assert template.kind_id == "qa_review"
    assert loaded is not None
    assert loaded.default_sandbox_policy["shell_policy"] == "denied"
    assert loaded.allowed_resource_refs == ("file_profile.general_workspace", "review.memory")
    assert loaded.allowed_task_graph_kinds == ("coordination",)


def test_environment_kind_template_api_round_trip(tmp_path: Path) -> None:
    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: RuntimeBaseDirStub(tmp_path)  # type: ignore[assignment]
    try:
        payload = asyncio.run(
            tasks_api.upsert_task_system_environment_kind_template(
                "analysis",
                tasks_api.TaskEnvironmentKindTemplateUpsertRequest(
                    kind_id="ignored-by-route",
                    title="Analysis",
                    group_id="environment_group.general",
                    allowed_resource_refs=["file_profile.general_workspace"],
                    default_execution_policy={"network_execution_policy": "allowed"},
                    allowed_task_graph_kinds=["single_agent"],
                ),
            )
        )
        assert any(
            item["kind_id"] == "analysis"
            for item in payload["environment_kind_management"]["kind_templates"]
        )

        listed = asyncio.run(tasks_api.list_task_system_environment_kind_templates())
        assert any(item["kind_id"] == "analysis" for item in listed["kind_templates"])

        deleted = asyncio.run(tasks_api.delete_task_system_environment_kind_template("analysis"))
        assert not any(
            item["kind_id"] == "analysis"
            for item in deleted["environment_kind_management"]["kind_templates"]
        )
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

