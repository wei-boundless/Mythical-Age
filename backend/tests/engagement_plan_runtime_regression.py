from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import json

import asyncio
import pytest
from pydantic import ValidationError

from api import task_system as tasks_api
from capability_system.tool_runtime import ToolRuntime
from harness.runtime import SingleAgentRuntimeHost
from query import QueryRuntime
from task_system.engagement import EngagementPlanRepository, EngagementRunRepository, EngagementService, sync_engagement_run_closeout
from task_system.environments import build_task_environment_catalog
from tests.support.runtime_stubs import (
    DefaultPermissionStub,
    EmptySkillRegistryStub,
    InMemorySessionManagerStub,
    PrimarySettingsStub,
    QueryRuntimeMemoryFacadeStub,
)


class _EngagementExecutionModelRuntime:
    def __init__(self, artifact_path: str) -> None:
        self.artifact_path = artifact_path
        self.task_invocation_count = 0

    async def invoke_messages(self, messages, **_kwargs):
        content = str(list(messages or [])[0].get("content") or "")
        if "正式 TaskRun 的执行 agent" not in content:
            return SimpleNamespace(content=json.dumps(_model_action("respond", final_answer="ready"), ensure_ascii=False))
        self.task_invocation_count += 1
        if self.task_invocation_count == 1:
            return SimpleNamespace(
                content=json.dumps(
                    _model_action(
                        "tool_call",
                        tool_call={
                            "tool_name": "write_file",
                            "args": {
                                "path": self.artifact_path,
                                "content": "<!doctype html><title>engagement probe</title><main>ok</main>",
                            },
                        },
                    ),
                    ensure_ascii=False,
                )
            )
        return SimpleNamespace(
            content=json.dumps(
                _model_action(
                    "respond",
                    final_answer="已完成特定任务并写入真实 index.html。",
                    diagnostics={"artifacts": [{"path": self.artifact_path, "kind": "html_document", "source": "model_closeout"}]},
                ),
                ensure_ascii=False,
            )
        )


def _model_action(
    action_type: str,
    *,
    final_answer: str = "",
    tool_call: dict[str, object] | None = None,
    diagnostics: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "authority": "harness.loop.model_action_request",
        "request_id": f"model-action:test:{action_type}",
        "turn_id": "",
        "action_type": action_type,
        "final_answer": final_answer,
        "tool_call": dict(tool_call or {}),
        "task_contract_seed": {},
        "completion_contract": {},
        "permission_request": {},
        "diagnostics": dict(diagnostics or {}),
    }


def _active_task_run_plan() -> dict[str, object]:
    return {
        "plan_id": "engage.test.dungeon",
        "title": "Five Floor Dungeon",
        "description": "Build a playable five-floor dungeon game.",
        "version": "1.0.0",
        "status": "active",
        "task_environment_id": "env.development.sandbox",
        "assignee": {"kind": "agent", "agent_id": "agent:0"},
        "runtime_profile": {"runtime_mode": "professional", "runtime_mode_policy": {}},
        "execution_strategy": {"kind": "single_agent_task_run"},
        "input_contract": {},
        "output_contract": {
            "required_artifacts": [{"path": "storage/task_environments/development/sandbox/artifacts/index.html"}],
            "completion_criteria": ["game can be opened and replayed after death"],
        },
        "prompt_contract": {"user_visible_goal": "完成一个可打开、可游玩的五层地下塔小游戏。"},
        "acceptance_policy": {"required_verifications": [{"kind": "manual_or_browser_check"}]},
    }


def test_engagement_repository_and_environment_catalog_use_new_plan_source(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    EngagementPlanRepository(backend_dir).upsert(_active_task_run_plan())

    plans = [item.to_dict() for item in EngagementPlanRepository(backend_dir).list()]
    catalog = build_task_environment_catalog(engagement_plans=plans)
    environment = catalog.management_payload()["environments"]
    development = next(item for item in environment if item["record"]["environment_id"] == "env.development.sandbox")

    assert development["task_library"]["engagement_plan_ids"] == ["engage.test.dungeon"]
    assert development["task_library"]["task_ids"] == ["engage.test.dungeon"]


def test_engagement_start_rejects_environment_strategy_and_mode_overrides(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    EngagementPlanRepository(backend_dir).upsert(_active_task_run_plan())
    runtime_host = SingleAgentRuntimeHost(tmp_path / "runtime_state", backend_dir=backend_dir)

    result = EngagementService(backend_dir).start(
        runtime_host=runtime_host,
        plan_id="engage.test.dungeon",
        session_id="session:test",
        startup_parameters={
            "environment_id": "env.general.workspace",
            "execution_strategy_override": "turn_contract",
            "runtime_mode_override": "role",
        },
    )

    assert result["decision"] == "invalid_request"
    assert "forbidden_start_field:environment_id" in result["errors"]
    assert "forbidden_start_field:execution_strategy_override" in result["errors"]
    assert "forbidden_start_field:runtime_mode_override" in result["errors"]


def test_single_agent_engagement_starts_task_run_with_plan_environment(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    EngagementPlanRepository(backend_dir).upsert(_active_task_run_plan())
    runtime_host = SingleAgentRuntimeHost(tmp_path / "runtime_state", backend_dir=backend_dir)

    result = EngagementService(backend_dir).start(
        runtime_host=runtime_host,
        plan_id="engage.test.dungeon",
        session_id="session:test",
        startup_parameters={},
    )

    assert result["decision"] == "started"
    task_run = runtime_host.state_index.get_task_run(result["task_run"]["task_run_id"])
    assert task_run is not None
    assert task_run.execution_runtime_kind == "single_agent_task"
    contract = runtime_host.runtime_objects.get_object(task_run.task_contract_ref)
    assert contract["external_plan_ref"] == "engage.test.dungeon"
    assert contract["task_environment_id"] == "env.development.sandbox"
    assert contract["runtime_profile"]["runtime_mode"] == "professional"
    assert dict(task_run.diagnostics)["runtime_task_selection"]["task_environment_id"] == "env.development.sandbox"


def test_engagement_closeout_syncs_terminal_task_run_artifacts(tmp_path: Path) -> None:
    from dataclasses import replace

    backend_dir = tmp_path / "backend"
    EngagementPlanRepository(backend_dir).upsert(_active_task_run_plan())
    runtime_host = SingleAgentRuntimeHost(tmp_path / "runtime_state", backend_dir=backend_dir)
    result = EngagementService(backend_dir).start(
        runtime_host=runtime_host,
        plan_id="engage.test.dungeon",
        session_id="session:test",
        startup_parameters={},
    )
    task_run_id = result["task_run"]["task_run_id"]
    engagement_run_id = result["engagement_run"]["engagement_run_id"]
    artifact_path = tmp_path / "storage" / "task_environments" / "development" / "sandbox" / "artifacts" / "index.html"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text("<!doctype html><title>dungeon</title>", encoding="utf-8")
    task_run = runtime_host.state_index.get_task_run(task_run_id)
    assert task_run is not None
    runtime_host.state_index.upsert_task_run(
        replace(
            task_run,
            status="completed",
            terminal_reason="completed",
            diagnostics={
                **dict(task_run.diagnostics or {}),
                "artifact_refs": [{"path": "storage/task_environments/development/sandbox/artifacts/index.html"}],
            },
        )
    )

    closeout = sync_engagement_run_closeout(
        backend_dir=backend_dir,
        runtime_host=runtime_host,
        engagement_run_id=engagement_run_id,
    )

    updated = EngagementRunRepository(backend_dir).get_run(engagement_run_id)
    assert closeout["changed"] is True
    assert updated is not None
    assert updated.status == "completed"
    assert updated.artifact_refs
    assert updated.artifact_refs[0]["path"] == "storage/task_environments/development/sandbox/artifacts/index.html"
    assert updated.closeout["verified_artifact_count"] == 1


def test_engagement_run_api_lists_gets_and_syncs_closeout(tmp_path: Path) -> None:
    from dataclasses import replace

    backend_dir = tmp_path / "backend"
    EngagementPlanRepository(backend_dir).upsert(_active_task_run_plan())
    runtime_host = SingleAgentRuntimeHost(tmp_path / "runtime_state", backend_dir=backend_dir)
    runtime_stub = SimpleNamespace(
        base_dir=backend_dir,
        query_runtime=SimpleNamespace(single_agent_runtime_host=runtime_host),
    )
    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: runtime_stub  # type: ignore[assignment]
    try:
        start = asyncio.run(
            tasks_api.start_task_system_engagement_plan(
                "engage.test.dungeon",
                tasks_api.EngagementStartRequest(session_id="session:test", startup_parameters={}),
            )
        )
        task_run_id = start["task_run"]["task_run_id"]
        engagement_run_id = start["engagement_run"]["engagement_run_id"]
        artifact_path = tmp_path / "storage" / "task_environments" / "development" / "sandbox" / "artifacts" / "index.html"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text("<!doctype html><title>dungeon</title>", encoding="utf-8")
        task_run = runtime_host.state_index.get_task_run(task_run_id)
        assert task_run is not None
        runtime_host.state_index.upsert_task_run(
            replace(
                task_run,
                status="completed",
                terminal_reason="completed",
                diagnostics={
                    **dict(task_run.diagnostics or {}),
                    "artifact_refs": [{"path": "storage/task_environments/development/sandbox/artifacts/index.html"}],
                },
            )
        )

        listing = asyncio.run(tasks_api.list_task_system_engagement_runs())
        detail = asyncio.run(tasks_api.get_task_system_engagement_run(engagement_run_id))
        synced = asyncio.run(tasks_api.sync_task_system_engagement_run_closeout(engagement_run_id))
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    assert listing["summary"]["engagement_run_count"] == 1
    assert detail["engagement_run"]["engagement_run_id"] == engagement_run_id
    assert synced["changed"] is True
    assert synced["engagement_run"]["status"] == "completed"
    assert synced["engagement_run"]["artifact_refs"][0]["path"] == "storage/task_environments/development/sandbox/artifacts/index.html"


def test_engagement_plan_starts_executes_writes_real_artifact_and_closes_out(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    artifact_path = "storage/task_environments/development/sandbox/artifacts/manual_probe/index.html"
    plan = {
        **_active_task_run_plan(),
        "plan_id": "engage.test.manual_probe",
        "output_contract": {
            "required_artifacts": [{"path": artifact_path}],
            "completion_criteria": ["真实 index.html 已经通过 write_file 写出并发布到项目 artifact 区。"],
        },
        "prompt_contract": {"user_visible_goal": "写出一个真实 index.html 并完成特定任务。"},
    }
    EngagementPlanRepository(backend_dir).upsert(plan)
    model_runtime = _EngagementExecutionModelRuntime(artifact_path)
    tool_runtime = ToolRuntime(backend_dir)
    runtime = QueryRuntime(
        base_dir=backend_dir,
        settings_service=PrimarySettingsStub(),
        session_manager=InMemorySessionManagerStub(),
        memory_facade=QueryRuntimeMemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=tool_runtime,
        skill_registry=EmptySkillRegistryStub(),
        permission_service=DefaultPermissionStub(),
        model_runtime=model_runtime,
    )

    runtime_host = runtime.single_agent_runtime_host
    result = EngagementService(backend_dir).start(
        runtime_host=runtime_host,
        plan_id="engage.test.manual_probe",
        session_id="session:engagement-real-exec",
        startup_parameters={},
    )
    task_run_id = result["task_run"]["task_run_id"]
    engagement_run_id = result["engagement_run"]["engagement_run_id"]

    execution = asyncio.run(runtime.execute_task_run(task_run_id, max_steps=4))
    task_run = runtime_host.state_index.get_task_run(task_run_id)
    updated_run = EngagementRunRepository(backend_dir).get_run(engagement_run_id)
    artifact_file = tmp_path / artifact_path

    assert execution["ok"] is True
    assert task_run is not None
    assert task_run.status == "completed"
    assert artifact_file.exists()
    assert "engagement probe" in artifact_file.read_text(encoding="utf-8")
    assert updated_run is not None
    assert updated_run.status == "completed"
    assert updated_run.artifact_refs
    assert updated_run.artifact_refs[0]["path"] == artifact_path
    assert updated_run.closeout["verified_artifact_count"] == 1
    assert model_runtime.task_invocation_count == 2


def test_engagement_api_start_payload_rejects_top_level_override_fields() -> None:
    with pytest.raises(ValidationError) as exc:
        tasks_api.EngagementStartRequest.model_validate(
            {
                "session_id": "session:test",
                "startup_parameters": {},
                "task_environment_id": "env.general.workspace",
            }
        )

    assert "extra_forbidden" in str(exc.value)
