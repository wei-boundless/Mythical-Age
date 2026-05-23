from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from agent_system.assembly.runtime_bundle_builder import build_orchestration_runtime_bundle
from agent_system.profiles.runtime_profile_models import AgentRuntimeProfile
from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry
from task_system.services.assembly_builder import build_task_execution_assembly_bundle


def test_orchestration_runtime_bundle_builds_formal_objects() -> None:
    task_bundle = build_task_execution_assembly_bundle(
        session_id="session-orch-runtime",
        task_id="taskinst:turn:session-orch-runtime:1:general_response",
        user_goal="请生成一个可以直接运行的网页贪吃蛇小游戏。",
        source="test",
        current_turn_context={
            "authority": "context.current_turn",
            "turn_id": "turn:session-orch-runtime:1",
            "selected_task_id": "task.dev.light_web_game",
        },
    )

    payload = build_orchestration_runtime_bundle(
        base_dir=BACKEND_DIR,
        session_id="session-orch-runtime",
        task_id="taskinst:turn:session-orch-runtime:1:general_response",
        user_goal="请生成一个可以直接运行的网页贪吃蛇小游戏。",
        task_assembly_bundle=task_bundle,
        current_turn_context={
            "authority": "context.current_turn",
            "turn_id": "turn:session-orch-runtime:1",
            "selected_task_id": "task.dev.light_web_game",
        },
        memory_runtime_view={"view_id": "memview:test"},
        context_policy_result={"result_id": "ctxpolicy:test"},
    )

    body = payload["agent_body_profile"]
    prompt = payload["prompt_structure_profile"]
    memory_scope = payload["memory_scope_profile"]
    lane = payload["runtime_lane_profile"]
    output = payload["output_boundary_profile"]
    orchestration = payload["task_body_orchestration"]
    runtime_spec = payload["agent_runtime_spec"]

    assert body["authority"] == "orchestration.agent_body_profile"
    assert prompt["authority"] == "orchestration.prompt_structure_profile"
    assert memory_scope["authority"] == "orchestration.memory_scope_profile"
    assert lane["authority"] == "orchestration.runtime_lane_profile"
    assert output["authority"] == "orchestration.output_boundary_profile"
    assert orchestration["authority"] == "orchestration.task_body_orchestration"
    assert runtime_spec["authority"] == "orchestration.agent_runtime_spec"
    assert orchestration["task_execution_assembly_ref"] == task_bundle["task_execution_assembly"]["assembly_id"]
    assert runtime_spec["task_body_orchestration_ref"] == orchestration["orchestration_id"]
    assert runtime_spec["resource_policy_candidate_ref"] == task_bundle["operation_requirement"]["requirement_id"]
    assert orchestration["projection_requirement"]["role_type"]
    assert orchestration["projection_requirement"]["reason"]
    assert orchestration["projection_requirement"]["projection_optional"] is True
    assert orchestration["projection_requirement"]["resolution_source"] in {"task_requirement", "agent_default", "no_projection"}
    assert orchestration["diagnostics"]["projection_resolution"]["status"] in {"ok", "warning"}
    assert orchestration["prompt_manifest"]["manifest_id"]
    assert orchestration["soul_runtime_view"]["sections"]
    assert orchestration["projection_ref"] == orchestration["projection_requirement"]["projection_id"] or not orchestration["projection_requirement"]["projection_id"]


def test_professional_mode_overrides_registered_light_web_game_recipe() -> None:
    task_bundle = build_task_execution_assembly_bundle(
        session_id="session-professional-game",
        task_id="taskinst:turn:session-professional-game:1:light_web_game",
        user_goal="请用专业模式完成一个多文件网页贪吃蛇小游戏。",
        source="test",
        current_turn_context={
            "authority": "context.current_turn",
            "turn_id": "turn:session-professional-game:1",
            "selected_task_id": "task.dev.light_web_game",
            "interaction_mode": "professional_mode",
            "intent_decision": {"execution_strategy": "professional_task_run", "interaction_mode": "professional_mode"},
            "runtime_assembly_hint": {
                "execution_strategy": "professional_task_run",
                "runtime_mode": "professional_task",
                "interaction_mode": "professional_mode",
            },
        },
    )

    shape = task_bundle["execution_shape"]
    recipe = task_bundle["selected_recipe"]
    assert shape["recipe_id"] == "runtime.recipe.professional_task"
    assert recipe["metadata"]["runtime_driver"] == "professional_task_run"


def test_removed_health_task_selection_does_not_mount_old_profiles() -> None:
    task_bundle = build_task_execution_assembly_bundle(
        session_id="session-orch-health",
        task_id="taskinst:turn:session-orch-health:1:health_issue_triage",
        user_goal="请检查这个 health issue 的修复建议。",
        source="test",
        current_turn_context={
            "authority": "context.current_turn",
            "turn_id": "turn:session-orch-health:1",
            "selected_task_id": "task.health.issue_triage",
        },
    )

    assembly = task_bundle["task_execution_assembly"]

    assert AgentRuntimeRegistry(BACKEND_DIR).get_profile("agent:3") is None
    assert assembly["task_family"] == "general"
    assert assembly["flow_contract_id"] == ""
    assert assembly["workflow_id"] == ""
    assert assembly["communication_protocol_ref"] == ""
    assert assembly["graph_ref"] == ""


def test_orchestration_runtime_bundle_respects_shared_contract_flag() -> None:
    task_bundle = build_task_execution_assembly_bundle(
        session_id="session-orch-shared-contract",
        task_id="taskinst:turn:session-orch-shared-contract:1:general_response",
        user_goal="测试共同契约是否进入编排运行时。",
        source="test",
    )
    profile = AgentRuntimeRegistry(BACKEND_DIR).get_profile("agent:0")
    assert profile is not None

    payload_with_shared = build_orchestration_runtime_bundle(
        base_dir=BACKEND_DIR,
        session_id="session-orch-shared-contract",
        task_id="taskinst:turn:session-orch-shared-contract:1:general_response",
        user_goal="测试共同契约是否进入编排运行时。",
        task_assembly_bundle=task_bundle,
        agent_runtime_profile=profile,
    )
    section_ids_with_shared = [
        str(section.get("section_id") or "")
        for section in payload_with_shared["task_body_orchestration"]["soul_runtime_view"].get("sections", [])
        if isinstance(section, dict)
    ]
    sections_with_shared = [
        dict(section)
        for section in payload_with_shared["task_body_orchestration"]["soul_runtime_view"].get("sections", [])
        if isinstance(section, dict)
    ]

    profile_without_shared = AgentRuntimeProfile(
        agent_profile_id=profile.agent_profile_id,
        agent_id=profile.agent_id,
        allowed_runtime_lanes=profile.allowed_runtime_lanes,
        allowed_operations=profile.allowed_operations,
        blocked_operations=profile.blocked_operations,
        allowed_memory_scopes=profile.allowed_memory_scopes,
        allowed_context_sections=profile.allowed_context_sections,
        use_shared_contract=False,
        approval_policy=profile.approval_policy,
        trace_policy=profile.trace_policy,
        lifecycle_policy=profile.lifecycle_policy,
        metadata=profile.metadata,
    )
    payload_without_shared = build_orchestration_runtime_bundle(
        base_dir=BACKEND_DIR,
        session_id="session-orch-shared-contract",
        task_id="taskinst:turn:session-orch-shared-contract:1:general_response",
        user_goal="测试共同契约是否进入编排运行时。",
        task_assembly_bundle=task_bundle,
        agent_runtime_profile=profile_without_shared,
    )
    section_ids_without_shared = [
        str(section.get("section_id") or "")
        for section in payload_without_shared["task_body_orchestration"]["soul_runtime_view"].get("sections", [])
        if isinstance(section, dict)
    ]

    assert "protected_system_rules" in section_ids_with_shared
    assert "protected_system_rules" in section_ids_without_shared
    assert "shared_common_contract" in section_ids_with_shared
    assert "shared_common_contract" not in section_ids_without_shared
    system_contract = next(section for section in sections_with_shared if section.get("section_id") == "protected_system_rules")
    system_content = str(system_contract.get("content") or "")
    assert "## 禁令等级" in system_content
    assert "## 通用禁止条例" in system_content
    assert "禁止伪造事实" in system_content
    assert "禁止把开发说明当作给 agent 的 prompt" in system_content
    shared_contract = next(section for section in sections_with_shared if section.get("section_id") == "shared_common_contract")
    shared_content = str(shared_contract.get("content") or "")
    assert "## 禁令等级" not in shared_content
    assert "## 通用禁止条例" not in shared_content


def test_removed_story_task_selection_falls_back_to_general_runtime() -> None:
    task_bundle = build_task_execution_assembly_bundle(
        session_id="session-orch-story",
        task_id="taskinst:turn:session-orch-story:1:short_story",
        user_goal="请完成一篇短篇小说。",
        source="test",
        current_turn_context={
            "authority": "context.current_turn",
            "turn_id": "turn:session-orch-story:1",
            "selected_task_id": "task.writing.short_story",
        },
    )

    assembly = task_bundle["task_execution_assembly"]

    assert assembly["task_mode"] == "general_task"
    assert assembly["task_family"] == "general"
    assert assembly["flow_contract_id"] == ""
    assert assembly["communication_protocol_ref"] == ""
    assert assembly["graph_ref"] == ""
    assert assembly["topology_template_ref"] == ""


def test_removed_longform_writing_runtime_residue_stays_absent() -> None:
    from task_system.registry.flow_registry import TaskFlowRegistry
    from agent_system.assembly.runtime_chain import _align_understanding_with_explicit_task_selection
    from understanding.query_understanding import analyze_query_understanding

    registry = TaskFlowRegistry(BACKEND_DIR)

    assert not hasattr(registry, "template_registry")
    assert registry.get_task_graph("graph.writing.longform_project_bootstrap") is None
    assert registry.get_task_graph("graph.writing.chapter_pipeline") is None
    assert registry.get_task_communication_protocol("protocol.writing.longform_project_bootstrap") is None
    assert registry.get_task_communication_protocol("protocol.writing.chapter_pipeline") is None
    assert registry.get_specific_task_record("task.writing.chapter_planning") is None
    assert registry.get_specific_task_record("task.writing.chapter_drafting") is None

    message = (
        "这是写作域的真实执行任务，不是文档阅读、文件解读、PDF分析。"
        "请生成第001章到第003章短批次规划，并写入 "
        "docs/系统规划/任务系统实测记录/artifacts/20260506/E5/batches/batch_001_003_plan.md。"
    )
    understanding = analyze_query_understanding(message)
    aligned = _align_understanding_with_explicit_task_selection(
        BACKEND_DIR,
        understanding,
        task_selection={"selected_task_id": "task.writing.chapter_planning"},
    )

    assert aligned.source_kind != "task_system"
    assert aligned.task_kind != "chapter_planning"


def test_delegate_preferred_templates_mount_delegate_operation_for_main_agent() -> None:
    profile = AgentRuntimeRegistry(BACKEND_DIR).get_profile("agent:0")
    assert profile is not None

    scenarios = [
        ("请帮我检索知识库里和向量召回有关的结论。", {"route": "rag", "execution_posture": "direct_rag"}, "op.mcp_retrieval", "agent:rag_analyst"),
        ("请读取这个 PDF 文档并总结前三页要点。", {"route": "pdf"}, "op.mcp_pdf", "agent:pdf_reader"),
        ("请分析这份表格数据并给我趋势结论。", {"route": "structured_data"}, "op.mcp_structured_data", "agent:table_analyst"),
    ]
    for user_goal, understanding, fallback_operation, target_agent_id in scenarios:
        task_bundle = build_task_execution_assembly_bundle(
            base_dir=BACKEND_DIR,
            session_id="session-delegate-preferred",
            task_id=f"taskinst:{target_agent_id}",
            user_goal=user_goal,
            source="test",
            query_understanding=understanding,
            agent_runtime_profile=profile,
        )
        requirement = task_bundle["operation_requirement"]
        resolution = dict(requirement.get("metadata") or {}).get("runtime_operation_resolution") or {}

        assert "op.delegate_to_agent" in set(requirement["required_operations"])
        assert fallback_operation not in set(requirement["required_operations"])
        assert resolution.get("execution_mode") == "delegate"
        assert resolution.get("delegate_target_agent_id") == target_agent_id


def test_information_search_template_mounts_direct_web_search_for_main_agent() -> None:
    profile = AgentRuntimeRegistry(BACKEND_DIR).get_profile("agent:0")
    assert profile is not None

    task_bundle = build_task_execution_assembly_bundle(
        base_dir=BACKEND_DIR,
        session_id="session-direct-web",
        task_id="taskinst:direct:web",
        user_goal="帮我联网查 OpenAI API 最新更新，并说明来源。",
        source="test",
        query_understanding={"route": "realtime_network"},
        agent_runtime_profile=profile,
    )
    requirement = task_bundle["operation_requirement"]
    resolution = dict(requirement.get("metadata") or {}).get("runtime_operation_resolution") or {}

    assert "op.web_search" in set(requirement["required_operations"])
    assert "op.delegate_to_agent" not in set(requirement["required_operations"])
    assert resolution.get("strategy") == "direct"


def test_delegate_preferred_templates_fall_back_to_direct_operation_for_specialist_agent() -> None:
    profile = AgentRuntimeRegistry(BACKEND_DIR).get_profile("agent:pdf_reader")
    assert profile is not None

    task_bundle = build_task_execution_assembly_bundle(
        base_dir=BACKEND_DIR,
        session_id="session-delegate-fallback",
        task_id="taskinst:agent7:pdf",
        user_goal="请读取这个 PDF 文档并总结前三页要点。",
        source="test",
        query_understanding={"route": "pdf"},
        agent_runtime_profile=profile,
    )
    requirement = task_bundle["operation_requirement"]
    resolution = dict(requirement.get("metadata") or {}).get("runtime_operation_resolution") or {}

    assert "op.mcp_pdf" in set(requirement["required_operations"])
    assert "op.delegate_to_agent" not in set(requirement["required_operations"])
    assert resolution.get("execution_mode") == "direct_fallback"
