from __future__ import annotations

import json
import pytest

from agent_system.groups.registry import AgentGroupRegistry
from agent_system.identity import agent_id_aliases, normalize_agent_id
from agent_system.registry.agent_registry import AgentRegistry
from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry
from agent_system.assembly.runtime_bundle_builder import build_orchestration_runtime_bundle
from agent_system.registry.worker_agent_factory import default_worker_agent_blueprints


def test_builtin_agents_are_seeded_as_system_builtin_and_have_runtime_profiles(tmp_path):
    agents = AgentRegistry(tmp_path).list_agents()
    profiles = AgentRuntimeRegistry(tmp_path).list_profiles()
    profile_by_agent = {item.agent_id: item for item in profiles}

    builtin_ids = {
        "agent:0",
        "agent:1",
        "agent:2",
        "agent:3",
        "agent:4",
        "agent:5",
        "agent:rag_analyst",
        "agent:pdf_reader",
        "agent:table_analyst",
        "agent:web_researcher",
        "agent:verifier"}
    builtin_agents = [item for item in agents if item.agent_id in builtin_ids]
    builtin_by_id = {item.agent_id: item for item in builtin_agents}
    runtime_profile_expected_ids = builtin_ids - {"agent:3"}

    assert {item.agent_id for item in builtin_agents} == builtin_ids
    assert all(item.builtin for item in builtin_agents)
    assert all(item.enabled for item in builtin_agents)
    assert all(item.editable is True for item in builtin_agents)
    assert all(item.lifecycle_policy == "system_builtin" for item in builtin_agents)
    assert all(item.definition_source == "system_builtin" for item in builtin_agents)
    assert runtime_profile_expected_ids.issubset(profile_by_agent)
    assert "agent:3" not in profile_by_agent
    assert all(profile_by_agent[agent_id].lifecycle_policy == "system_builtin" for agent_id in runtime_profile_expected_ids)
    assert builtin_by_id["agent:1"].agent_name == "记忆管理Agent"
    assert builtin_by_id["agent:1"].interface_target == "memory_system_window"
    assert builtin_by_id["agent:1"].metadata["system_key"] == "memory_system"
    assert profile_by_agent["agent:0"].can_delegate_to_agents is True
    assert profile_by_agent["agent:0"].allowed_delegate_agent_ids == ("agent:rag_analyst", "agent:pdf_reader", "agent:table_analyst", "agent:web_researcher", "agent:verifier")
    assert profile_by_agent["agent:0"].max_delegate_calls_per_turn == 2
    assert "op.delegate_to_agent" in profile_by_agent["agent:0"].allowed_operations
    assert "conversation_readonly" in profile_by_agent["agent:0"].allowed_memory_scopes
    assert "state_readonly" in profile_by_agent["agent:0"].allowed_memory_scopes
    assert "conversation_read_write" not in profile_by_agent["agent:0"].allowed_memory_scopes
    assert "state_read_write" not in profile_by_agent["agent:0"].allowed_memory_scopes
    memory_profile = profile_by_agent["agent:1"]
    assert memory_profile.agent_profile_id == "memory_system_agent"
    assert "session_memory_maintenance" in memory_profile.allowed_runtime_lanes
    assert memory_profile.allowed_operations == ("op.model_response", "op.memory_read", "op.memory_write_candidate")
    assert "op.memory_write_candidate" not in memory_profile.blocked_operations
    assert "op.write_file" in memory_profile.blocked_operations
    assert "op.delegate_to_agent" in memory_profile.blocked_operations
    assert "session_memory_write_candidate" in memory_profile.allowed_memory_scopes
    assert profile_by_agent["agent:rag_analyst"].allowed_operations == ("op.model_response", "op.mcp_retrieval", "op.memory_read")
    assert profile_by_agent["agent:rag_analyst"].can_delegate_to_agents is False
    assert "op.delegate_to_agent" in profile_by_agent["agent:rag_analyst"].blocked_operations
    assert profile_by_agent["agent:pdf_reader"].allowed_operations == (
        "op.model_response",
        "op.mcp_pdf",
        "op.read_file",
    )
    assert profile_by_agent["agent:pdf_reader"].can_delegate_to_agents is False
    assert profile_by_agent["agent:table_analyst"].allowed_operations == (
        "op.model_response",
        "op.mcp_structured_data",
        "op.read_structured_file",
        "op.read_file",
    )
    assert profile_by_agent["agent:table_analyst"].can_delegate_to_agents is False
    assert profile_by_agent["agent:web_researcher"].allowed_operations == ("op.model_response", "op.web_search", "op.fetch_url")
    assert profile_by_agent["agent:web_researcher"].can_delegate_to_agents is False
    assert profile_by_agent["agent:verifier"].allowed_operations == (
        "op.model_response",
        "op.read_file",
        "op.search_files",
        "op.search_text",
        "op.git_diff",
        "op.git_status",
    )
    assert profile_by_agent["agent:verifier"].can_delegate_to_agents is False
    assert "completion_verification" in profile_by_agent["agent:verifier"].metadata["delegation_kinds"]


def test_builtin_specialist_agent_aliases_resolve_to_registered_ids():
    assert normalize_agent_id("agent.rag_retriever") == "agent:rag_analyst"
    assert normalize_agent_id("agent.pdf_analyst") == "agent:pdf_reader"
    assert normalize_agent_id("agent.table_analyst") == "agent:table_analyst"
    assert normalize_agent_id("agent.web_researcher") == "agent:web_researcher"
    assert normalize_agent_id("agent.verifier") == "agent:verifier"
    assert normalize_agent_id("agent:9") == "agent:9"
    assert "agent.rag_retriever" in agent_id_aliases("agent:rag_analyst")
    assert "agent.pdf_analyst" in agent_id_aliases("agent:pdf_reader")
    assert "agent.table_analyst" in agent_id_aliases("agent:table_analyst")
    assert "builtin-web-researcher" in agent_id_aliases("agent:web_researcher")
    assert "builtin-verifier" in agent_id_aliases("agent:verifier")


def test_builtin_agent_upsert_and_runtime_profile_updates_follow_regular_management(tmp_path):
    agent_registry = AgentRegistry(tmp_path)
    runtime_registry = AgentRuntimeRegistry(tmp_path)

    updated_agent = agent_registry.upsert_agent(
        agent_id="agent:1",
        agent_name="被改名的记忆 Agent",
        agent_category="builtin_agent",
        enabled=False,
        interface_target="memory_console_v2",
    )
    updated_profile = runtime_registry.upsert_profile(
        agent_id="agent:1",
        agent_profile_id="mutated_memory_agent",
        allowed_operations=("op.model_response", "op.write_file"),
    )

    assert updated_agent.agent_name == "被改名的记忆 Agent"
    assert updated_agent.agent_category == "builtin_agent"
    assert updated_agent.builtin_kind == "system_manager"
    assert updated_agent.enabled is False
    assert updated_agent.interface_target == "memory_console_v2"
    assert updated_profile.allowed_operations == ("op.model_response", "op.write_file")


def test_custom_agent_runtime_profile_does_not_persist_task_contracts(tmp_path):
    agent_registry = AgentRegistry(tmp_path)
    runtime_registry = AgentRuntimeRegistry(tmp_path)
    agent_registry.upsert_agent(
        agent_id="agent:9",
        agent_name="契约测试 Agent",
        agent_category="custom_agent",
    )

    runtime_registry.upsert_profile(
        agent_id="agent:9",
        agent_profile_id="agent_9_runtime",
        allowed_operations=("op.model_response",),
        can_delegate_to_agents=True,
        allowed_delegate_agent_ids=("agent:rag_analyst",),
        max_delegate_calls_per_turn=2,
    )

    loaded = runtime_registry.get_profile("agent:9")

    assert loaded is not None
    assert not hasattr(loaded, "output_contracts")
    assert loaded.can_delegate_to_agents is True
    assert loaded.allowed_delegate_agent_ids == ("agent:rag_analyst",)
    assert loaded.max_delegate_calls_per_turn == 2


def test_system_builtin_profile_storage_is_migrated_with_required_default_permissions(tmp_path):
    path = tmp_path / "storage" / "orchestration" / "agent_runtime_profiles.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "agent_profile_id": "main_interactive_agent",
                        "agent_id": "agent:0",
                        "allowed_runtime_lanes": ["full_interactive"],
                        "allowed_operations": ["op.model_response", "op.mcp_retrieval"],
                        "blocked_operations": ["op.python_repl"],
                        "allowed_memory_scopes": ["conversation_read_write"],
                        "allowed_context_sections": ["conversation"],
                        "use_shared_contract": True,
                        "can_delegate_to_agents": True,
                        "allowed_delegate_agent_ids": ["agent:6"],
                        "max_delegate_calls_per_turn": 1,
                        "delegate_context_policy": "summary_and_refs_only",
                        "approval_policy": "default",
                        "trace_policy": "runtime_event_log",
                        "lifecycle_policy": "system_builtin",
                        "metadata": {}}
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    profile = AgentRuntimeRegistry(tmp_path).get_profile("agent:0")

    assert profile is not None
    assert not hasattr(profile, "allowed_task_modes")
    assert "allowed_task_modes" not in profile.to_dict()
    assert "op.delegate_to_agent" in profile.allowed_operations
    assert "op.memory_read" in profile.allowed_operations
    assert "full_interactive" in profile.allowed_runtime_lanes
    assert "conversation_readonly" in profile.allowed_memory_scopes
    assert "conversation_read_write" not in profile.allowed_memory_scopes


def test_custom_agent_runtime_profile_persists_shared_contract_flag(tmp_path):
    agent_registry = AgentRegistry(tmp_path)
    runtime_registry = AgentRuntimeRegistry(tmp_path)
    agent_registry.upsert_agent(
        agent_id="agent:9",
        agent_name="共同契约测试 Agent",
        agent_category="custom_agent",
    )

    runtime_registry.upsert_profile(
        agent_id="agent:9",
        agent_profile_id="agent_9_runtime",
        allowed_operations=("op.model_response",),
        use_shared_contract=False,
    )

    loaded = runtime_registry.get_profile("agent:9")

    assert loaded is not None
    assert loaded.use_shared_contract is False


def test_runtime_profile_rejects_unregistered_runtime_lane(tmp_path):
    agent_registry = AgentRegistry(tmp_path)
    runtime_registry = AgentRuntimeRegistry(tmp_path)
    agent_registry.upsert_agent(
        agent_id="agent:9",
        agent_name="运行场景权限测试 Agent",
        agent_category="custom_agent",
    )

    with pytest.raises(ValueError, match="unknown runtime lane"):
        runtime_registry.upsert_profile(
            agent_id="agent:9",
            agent_profile_id="agent_9_runtime",
            allowed_runtime_lanes=("not_registered_lane",),
            allowed_operations=("op.model_response",),
        )


def test_runtime_profile_system_modes_derive_runtime_lanes(tmp_path):
    agent_registry = AgentRegistry(tmp_path)
    runtime_registry = AgentRuntimeRegistry(tmp_path)
    agent_registry.upsert_agent(
        agent_id="agent:mode_test",
        agent_name="模式派生测试 Agent",
        agent_category="custom_agent",
    )

    profile = runtime_registry.upsert_profile(
        agent_id="agent:mode_test",
        agent_profile_id="agent_mode_test_runtime",
        enabled_runtime_modes=("role", "professional"),
        default_runtime_mode="professional",
        allowed_runtime_lanes=("readonly_exploration",),
        allowed_operations=("op.model_response",),
    )

    assert profile.enabled_runtime_modes == ("role", "professional")
    assert profile.default_runtime_mode == "professional"
    assert profile.allowed_runtime_lanes == ("role_interaction", "professional_task")


def test_runtime_profile_custom_mode_preserves_manual_runtime_lanes(tmp_path):
    agent_registry = AgentRegistry(tmp_path)
    runtime_registry = AgentRuntimeRegistry(tmp_path)
    agent_registry.upsert_agent(
        agent_id="agent:custom_mode_test",
        agent_name="自定义模式测试 Agent",
        agent_category="custom_agent",
    )

    profile = runtime_registry.upsert_profile(
        agent_id="agent:custom_mode_test",
        agent_profile_id="agent_custom_mode_test_runtime",
        enabled_runtime_modes=("custom",),
        default_runtime_mode="custom",
        allowed_runtime_lanes=("readonly_exploration",),
        allowed_operations=("op.model_response",),
        metadata={"custom_runtime_modes": [{"mode": "custom.saved", "label": "不应保留"}]},
    )
    loaded = runtime_registry.get_profile("agent:custom_mode_test")

    assert profile.enabled_runtime_modes == ("custom",)
    assert profile.default_runtime_mode == "custom"
    assert profile.allowed_runtime_lanes == ("readonly_exploration",)
    assert loaded is not None
    assert "custom_runtime_modes" not in loaded.metadata
    assert [item["mode"] for item in loaded.to_dict()["runtime_mode_catalog"]] == [
        "role",
        "standard",
        "professional",
        "vibe_coding",
        "custom",
    ]


def test_runtime_profile_vibe_coding_mode_derives_project_owned_lane(tmp_path):
    agent_registry = AgentRegistry(tmp_path)
    runtime_registry = AgentRuntimeRegistry(tmp_path)
    agent_registry.upsert_agent(
        agent_id="agent:vibe_mode_test",
        agent_name="Vibe Coding 模式测试 Agent",
        agent_category="custom_agent",
    )

    profile = runtime_registry.upsert_profile(
        agent_id="agent:vibe_mode_test",
        agent_profile_id="agent_vibe_mode_test_runtime",
        enabled_runtime_modes=("vibe_coding",),
        default_runtime_mode="vibe_coding",
        allowed_operations=("op.model_response", "op.read_file", "op.edit_file", "op.shell"),
    )
    loaded = runtime_registry.get_profile("agent:vibe_mode_test")

    assert profile.enabled_runtime_modes == ("vibe_coding",)
    assert profile.default_runtime_mode == "vibe_coding"
    assert profile.allowed_runtime_lanes == ("vibe_coding_task",)
    assert loaded is not None
    assert loaded.enabled_runtime_modes == ("vibe_coding",)
    assert loaded.allowed_runtime_lanes == ("vibe_coding_task",)


def test_runtime_profile_migration_adds_custom_for_mixed_legacy_lanes(tmp_path):
    path = tmp_path / "storage" / "orchestration" / "agent_runtime_profiles.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    AgentRegistry(tmp_path).upsert_agent(
        agent_id="agent:mixed_lane_test",
        agent_name="混合旧 lane 测试 Agent",
        agent_category="custom_agent",
    )
    path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "agent_profile_id": "mixed_lane_runtime",
                        "agent_id": "agent:mixed_lane_test",
                        "allowed_runtime_lanes": ["role_interaction", "readonly_exploration"],
                        "allowed_operations": ["op.model_response"],
                        "metadata": {}}
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    profile = AgentRuntimeRegistry(tmp_path).get_profile("agent:mixed_lane_test")

    assert profile is not None
    assert profile.enabled_runtime_modes == ("role", "custom")
    assert profile.allowed_runtime_lanes == ("role_interaction", "readonly_exploration")


def test_runtime_lane_profile_marks_denied_request_without_silent_success(tmp_path):
    agent_registry = AgentRegistry(tmp_path)
    runtime_registry = AgentRuntimeRegistry(tmp_path)
    agent_registry.upsert_agent(
        agent_id="agent:9",
        agent_name="运行场景准入测试 Agent",
        agent_category="custom_agent",
    )
    runtime_profile = runtime_registry.upsert_profile(
        agent_id="agent:9",
        agent_profile_id="agent_9_runtime",
        allowed_runtime_lanes=("readonly_exploration",),
        allowed_operations=("op.model_response",),
    )

    bundle = build_orchestration_runtime_bundle(
        base_dir=tmp_path,
        session_id="session:runtime-lane-denied",
        task_id="task:runtime-lane-denied",
        user_goal="测试运行场景权限拒绝。",
        task_assembly_bundle={
            "task_contract": {"user_goal": "测试运行场景权限拒绝。"},
            "task_execution_assembly": {
                "assembly_id": "assembly:runtime-lane-denied",
                "task_mode": "test",
                "output_contract_id": "AssistantFinalAnswer",
                "runtime_lane": "web_research_delegate"},
            "operation_requirement": {"requirement_id": "opreq:runtime-lane-denied"}},
        agent_runtime_profile=runtime_profile,
    )

    lane_profile = bundle["runtime_lane_profile"]
    assert lane_profile["lane_id"] == "readonly_exploration"
    assert lane_profile["metadata"]["requested_runtime_lane"] == "web_research_delegate"
    assert lane_profile["metadata"]["permission_state"] == "denied"
    assert lane_profile["metadata"]["lane_issue"] == "runtime_lane_not_allowed"


def test_legacy_read_write_memory_scopes_are_rejected(tmp_path):
    agent_registry = AgentRegistry(tmp_path)
    runtime_registry = AgentRuntimeRegistry(tmp_path)
    agent_registry.upsert_agent(
        agent_id="agent:9",
        agent_name="旧记忆范围测试 Agent",
        agent_category="custom_agent",
    )

    updated = runtime_registry.upsert_profile(
        agent_id="agent:9",
        agent_profile_id="agent_9_runtime",
        allowed_memory_scopes=("conversation_read_write", "state_read_write", "session_memory_write_candidate"),
    )

    assert updated.allowed_memory_scopes == ()


def test_custom_agent_prompt_profile_metadata_is_not_runtime_adopted(tmp_path):
    agent_registry = AgentRegistry(tmp_path)

    agent_registry.upsert_agent(
        agent_id="agent:9",
        agent_name="投影绑定测试 Agent",
        agent_category="custom_agent",
        default_soul_id="xuannv",
        default_projection_id="xuannv__primary",
        metadata={
            "managed_by": "orchestration_console",
            "prompt_profile": {
                "authority": "orchestration.agent_prompt_profile",
                "system_prompt": "这段旧名册 Prompt 不能进入 runtime prompt。",
                "guardrails": ["旧护栏不能进入 runtime prompt"],
                "output_style": "旧输出风格不能进入 runtime prompt。",
                "storage_policy": "agent_metadata_frontend_configured"}},
    )
    runtime_registry = AgentRuntimeRegistry(tmp_path)
    runtime_registry.upsert_profile(
        agent_id="agent:9",
        agent_profile_id="agent_9_runtime",
        allowed_runtime_lanes=("full_interactive",),
        allowed_operations=("op.model_response",),
        allowed_context_sections=("task", "projection", "prompt_manifest"),
    )

    loaded = agent_registry.get_agent("agent:9")

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
                "output_contract_id": "AssistantFinalAnswer",
                "requested_outputs": ["AssistantFinalAnswer"]},
            "projection_selection": {},
            "operation_requirement": {"requirement_id": "opreq:projection-test"}},
        agent_runtime_profile=runtime_registry.get_profile("agent:9"),
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


def test_builtin_agent_runtime_profile_allows_regular_updates(tmp_path):
    runtime_registry = AgentRuntimeRegistry(tmp_path)
    current = runtime_registry.get_profile("agent:2")

    assert current is not None

    updated = runtime_registry.upsert_profile(
        agent_id="agent:2",
        agent_profile_id=current.agent_profile_id,
        allowed_runtime_lanes=current.allowed_runtime_lanes,
        allowed_operations=(*current.allowed_operations, "op.write_file"),
        blocked_operations=current.blocked_operations,
        allowed_memory_scopes=current.allowed_memory_scopes,
        allowed_context_sections=current.allowed_context_sections,
        approval_policy=current.approval_policy,
        trace_policy=current.trace_policy,
        lifecycle_policy=current.lifecycle_policy,
    )

    assert updated.allowed_operations == (*current.allowed_operations, "op.write_file")


def test_agent_group_members_must_be_existing_workers(tmp_path):
    agent_registry = AgentRegistry(tmp_path)
    group_registry = AgentGroupRegistry(tmp_path)
    agent_registry.upsert_agent(
        agent_id="agent:9",
        agent_name="测试子 Agent",
        agent_category="custom_agent",
    )

    group = group_registry.upsert_group(
        group_id="group.custom.worker_group_01",
        title="测试子 Agent 组",
        group_kind="coordination_team",
        coordinator_agent_id="",
        member_agent_ids=("agent:9",),
    )

    assert group.member_agent_ids == ("agent:9",)
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


def test_deleted_custom_agent_does_not_resurrect_from_defaults(tmp_path):
    agent_registry = AgentRegistry(tmp_path)
    group_registry = AgentGroupRegistry(tmp_path)
    runtime_registry = AgentRuntimeRegistry(tmp_path)
    agents_path = tmp_path / "storage" / "orchestration" / "agents.json"
    profiles_path = tmp_path / "storage" / "orchestration" / "agent_runtime_profiles.json"
    groups_path = tmp_path / "storage" / "orchestration" / "agent_groups.json"
    agents_path.parent.mkdir(parents=True, exist_ok=True)
    agents_path.write_text(
        json.dumps(
            {
                "agents": [
                    {
                        "agent_id": "agent:custom_deleted_worker",
                        "agent_name": "已删除测试 Agent",
                        "agent_category": "custom_agent",
                        "interface_target": "worker_task_console",
                        "enabled": True,
                        "metadata": {"definition_source": "user_custom_agent"}}
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    profiles_path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "agent_profile_id": "custom_deleted_worker_runtime",
                        "agent_id": "agent:custom_deleted_worker",
                        "allowed_runtime_lanes": ["readonly_exploration"],
                        "allowed_operations": ["op.model_response"],
                        "metadata": {"managed_by": "orchestration_console"}}
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    groups_path.write_text(
        json.dumps(
            {
                "groups": [
                    {
                        "group_id": "group.custom.deleted_worker",
                        "title": "自定义 Agent 组",
                        "group_kind": "coordination_team",
                        "coordinator_agent_id": "",
                        "member_agent_ids": ["agent:custom_deleted_worker"]}
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    agent_registry.delete_agent("agent:custom_deleted_worker")
    runtime_registry.delete_profile("agent:custom_deleted_worker")
    group_registry.remove_agent_refs("agent:custom_deleted_worker")

    assert agent_registry.get_agent("agent:custom_deleted_worker") is None
    assert runtime_registry.get_profile("agent:custom_deleted_worker") is None
    assert group_registry.get_group("group.custom.deleted_worker").member_agent_ids == ()


def test_worker_agent_blueprints_include_role_templates():
    blueprint_ids = {item.blueprint_id for item in default_worker_agent_blueprints()}

    assert {
        "worker.dev.prototype",
        "worker.explorer",
        "worker.planner",
        "worker.verification",
        "worker.execution",
        "worker.review"}.issubset(blueprint_ids)
