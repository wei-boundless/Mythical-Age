from __future__ import annotations

import pytest

from orchestration.agent_group_registry import AgentGroupRegistry
from orchestration.agent_registry import AgentRegistry
from orchestration.agent_runtime_models import AgentRuntimeProfile
from orchestration.agent_runtime_registry import AgentRuntimeRegistry
from orchestration.assembly_builder import build_orchestration_runtime_bundle
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


def test_custom_agent_runtime_profile_persists_output_contracts(tmp_path):
    agent_registry = AgentRegistry(tmp_path)
    runtime_registry = AgentRuntimeRegistry(tmp_path)
    agent_registry.upsert_agent(
        agent_id="agent:6",
        agent_name="契约测试 Agent",
        agent_category="worker_sub_agent",
    )

    runtime_registry.upsert_profile(
        agent_id="agent:6",
        agent_profile_id="agent_6_runtime",
        allowed_operations=("op.model_response",),
        output_contracts=("contract.test.chapter_draft", "contract.test.review_report"),
    )

    loaded = runtime_registry.get_profile("agent:6")

    assert loaded is not None
    assert loaded.output_contracts == ("contract.test.chapter_draft", "contract.test.review_report")


def test_custom_agent_runtime_profile_persists_shared_contract_flag(tmp_path):
    agent_registry = AgentRegistry(tmp_path)
    runtime_registry = AgentRuntimeRegistry(tmp_path)
    agent_registry.upsert_agent(
        agent_id="agent:6",
        agent_name="共同契约测试 Agent",
        agent_category="worker_sub_agent",
    )

    runtime_registry.upsert_profile(
        agent_id="agent:6",
        agent_profile_id="agent_6_runtime",
        allowed_operations=("op.model_response",),
        use_shared_contract=False,
    )

    loaded = runtime_registry.get_profile("agent:6")

    assert loaded is not None
    assert loaded.use_shared_contract is False


def test_custom_agent_prompt_profile_metadata_is_not_runtime_adopted(tmp_path):
    agent_registry = AgentRegistry(tmp_path)

    agent_registry.upsert_agent(
        agent_id="agent:6",
        agent_name="投影绑定测试 Agent",
        agent_category="worker_sub_agent",
        default_soul_id="xuannv",
        default_projection_id="xuannv__primary",
        metadata={
            "managed_by": "orchestration_console",
            "prompt_profile": {
                "authority": "orchestration.agent_prompt_profile",
                "system_prompt": "这段旧名册 Prompt 不能进入 runtime prompt。",
                "guardrails": ["旧护栏不能进入 runtime prompt"],
                "output_style": "旧输出风格不能进入 runtime prompt。",
                "storage_policy": "agent_metadata_frontend_configured",
            },
        },
    )
    runtime_registry = AgentRuntimeRegistry(tmp_path)
    runtime_registry.upsert_profile(
        agent_id="agent:6",
        agent_profile_id="agent_6_runtime",
        allowed_task_modes=("projection_test",),
        allowed_runtime_lanes=("full_interactive",),
        allowed_operations=("op.model_response",),
        allowed_context_sections=("task", "projection", "prompt_manifest"),
        output_contracts=("AssistantFinalAnswer",),
    )

    loaded = agent_registry.get_agent("agent:6")

    assert loaded is not None
    assert loaded.metadata["prompt_profile"]["authority"] == "orchestration.agent_prompt_profile"
    bundle = build_orchestration_runtime_bundle(
        base_dir=tmp_path,
        session_id="session:projection-test",
        task_id="task:projection-test",
        user_goal="测试旧名册 Prompt 不进入 runtime。",
        task_assembly_bundle={
            "task_contract": {"user_goal": "测试旧名册 Prompt 不进入 runtime。"},
            "task_execution_assembly": {
                "assembly_id": "assembly:projection-test",
                "task_mode": "projection_test",
                "task_family": "test",
                "output_contract_id": "AssistantFinalAnswer",
                "requested_outputs": ["AssistantFinalAnswer"],
            },
            "projection_selection": {},
            "operation_requirement": {"requirement_id": "opreq:projection-test"},
        },
        agent_runtime_profile=runtime_registry.get_profile("agent:6"),
    )
    orchestration = bundle["task_body_orchestration"]
    rendered = "\n".join(
        str(section.get("content") or "")
        for section in orchestration["prompt_manifest"].get("sections", [])
        if isinstance(section, dict)
    )

    assert "这段旧名册 Prompt 不能进入 runtime prompt" not in rendered
    assert "旧护栏不能进入 runtime prompt" not in rendered
    assert orchestration["projection_ref"] == "xuannv__primary"


def test_builtin_agent_runtime_profile_allows_only_output_contract_updates(tmp_path):
    runtime_registry = AgentRuntimeRegistry(tmp_path)
    current = runtime_registry.get_profile("agent:3")

    assert current is not None

    updated = runtime_registry.upsert_profile(
        agent_id="agent:3",
        agent_profile_id=current.agent_profile_id,
        allowed_task_modes=current.allowed_task_modes,
        allowed_runtime_lanes=current.allowed_runtime_lanes,
        allowed_operations=current.allowed_operations,
        blocked_operations=current.blocked_operations,
        allowed_memory_scopes=current.allowed_memory_scopes,
        allowed_context_sections=current.allowed_context_sections,
        output_contracts=("HealthTriageResult", "HealthTraceAnalysis"),
        approval_policy=current.approval_policy,
        trace_policy=current.trace_policy,
        lifecycle_policy=current.lifecycle_policy,
    )

    assert updated.output_contracts == ("HealthTriageResult", "HealthTraceAnalysis")
    assert updated.allowed_operations == current.allowed_operations

    with pytest.raises(PermissionError):
        runtime_registry.upsert_profile(
            agent_id="agent:3",
            agent_profile_id=current.agent_profile_id,
            allowed_task_modes=current.allowed_task_modes,
            allowed_runtime_lanes=current.allowed_runtime_lanes,
            allowed_operations=(*current.allowed_operations, "op.write_file"),
            blocked_operations=current.blocked_operations,
            allowed_memory_scopes=current.allowed_memory_scopes,
            allowed_context_sections=current.allowed_context_sections,
            output_contracts=updated.output_contracts,
            approval_policy=current.approval_policy,
            trace_policy=current.trace_policy,
            lifecycle_policy=current.lifecycle_policy,
        )


def test_agent_group_members_must_be_existing_unlocked_workers(tmp_path):
    agent_registry = AgentRegistry(tmp_path)
    group_registry = AgentGroupRegistry(tmp_path)
    agent_registry.upsert_agent(
        agent_id="agent:6",
        agent_name="测试子 Agent",
        agent_category="worker_sub_agent",
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
