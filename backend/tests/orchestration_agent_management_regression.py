from __future__ import annotations

import pytest

from orchestration.agent_group_registry import AgentGroupRegistry
from orchestration.agent_registry import AgentRegistry
from orchestration.agent_runtime_models import AgentRuntimeProfile
from orchestration.agent_runtime_registry import AgentRuntimeRegistry
from orchestration.runtime_loop.runtime_assembly_builder import build_single_agent_runtime_assembly
from orchestration.runtime_loop.contract_compiler_models import CompiledGlobalContract, ContractManifest
from orchestration.worker_agent_factory import default_worker_agent_blueprints


def test_builtin_agents_are_locked_and_have_runtime_profiles(tmp_path):
    agents = AgentRegistry(tmp_path).list_agents()
    profiles = AgentRuntimeRegistry(tmp_path).list_profiles()
    profile_by_agent = {item.agent_id: item for item in profiles}

    builtin_ids = {f"agent:{index}" for index in range(6)}
    builtin_agents = [item for item in agents if item.agent_id in builtin_ids]

    assert {item.agent_id for item in builtin_agents} == builtin_ids
    assert all(item.builtin for item in builtin_agents)
    assert all(item.enabled for item in builtin_agents)
    assert all(item.editable is False for item in builtin_agents)
    assert all(item.lifecycle_policy == "system_locked" for item in builtin_agents)
    assert all(item.definition_source == "system_builtin" for item in builtin_agents)
    assert builtin_ids.issubset(profile_by_agent)
    assert all(profile_by_agent[agent_id].lifecycle_policy == "system_builtin" for agent_id in builtin_ids)


def test_builtin_agent_upsert_and_runtime_profile_updates_fail_closed(tmp_path):
    agent_registry = AgentRegistry(tmp_path)
    runtime_registry = AgentRuntimeRegistry(tmp_path)

    with pytest.raises(PermissionError):
        agent_registry.upsert_agent(
            agent_id="agent:1",
            agent_name="被篡改的权限 Agent",
            agent_category="worker_sub_agent",
            enabled=False,
        )

    with pytest.raises(PermissionError):
        runtime_registry.upsert_profile(
            agent_id="agent:1",
            agent_profile_id="mutated_permission_agent",
            allowed_operations=("op.model_response", "op.write_file"),
        )


def test_agent_group_members_must_be_existing_unlocked_workers(tmp_path):
    agent_registry = AgentRegistry(tmp_path)
    group_registry = AgentGroupRegistry(tmp_path)
    agent_registry.upsert_agent(
        agent_id="agent:6",
        agent_name="测试子 Agent",
        agent_category="worker_sub_agent",
        task_scope=("bounded_patch",),
    )

    group = group_registry.upsert_group(
        group_id="group.custom.worker_group_01",
        title="测试子 Agent 组",
        group_kind="coordination_team",
        coordinator_agent_id="",
        member_agent_ids=("agent:6",),
    )

    assert group.member_agent_ids == ("agent:6",)
    assert group.coordinator_agent_id == ""

    with pytest.raises(PermissionError):
        group_registry.upsert_group(
            group_id="group.custom.invalid_builtin",
            title="非法内置组",
            group_kind="coordination_team",
            coordinator_agent_id="agent:0",
            member_agent_ids=("agent:0",),
        )

    with pytest.raises(ValueError):
        group_registry.upsert_group(
            group_id="group.custom.invalid_missing",
            title="非法缺失组",
            group_kind="coordination_team",
            coordinator_agent_id="",
            member_agent_ids=("agent:404",),
        )


def test_runtime_assembly_filters_context_sections_by_agent_profile():
    manifest = ContractManifest(
        manifest_id="contract-manifest:test",
        manifest_kind="single",
        task_ref="task.test",
        workflow_id="workflow.test",
        global_contracts=(
            CompiledGlobalContract(
                contract_id="contract.test.output",
                title_zh="输出契约",
                contract_kind="final_output",
                source_ref="task.test",
                output_fields=({"field_id": "answer", "required": True},),
            ),
        ),
    )
    profile = AgentRuntimeProfile(
        agent_profile_id="task_only_agent",
        agent_id="agent:99",
        allowed_context_sections=("task",),
    )

    assembly = build_single_agent_runtime_assembly(
        manifest=manifest,
        agent_profile=profile,
        explicit_inputs={"goal": "测试"},
    )
    payload = assembly.to_dict()

    assert [item["section_id"] for item in payload["context_sections"]] == ["task_inputs"]
    assert payload["diagnostics"]["context_sections_hidden_by_profile"] == [
        "main_session_history",
        "runtime_contracts",
    ]


def test_worker_agent_blueprints_include_role_templates():
    blueprint_ids = {item.blueprint_id for item in default_worker_agent_blueprints()}

    assert {
        "worker.dev.prototype",
        "worker.explorer",
        "worker.planner",
        "worker.verification",
        "worker.execution",
        "worker.review",
    }.issubset(blueprint_ids)
