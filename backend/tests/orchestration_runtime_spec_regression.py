from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from orchestration import build_orchestration_runtime_bundle
from tasks.assembly_builder import build_task_execution_assembly_bundle


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


def test_orchestration_runtime_bundle_uses_selected_task_profiles() -> None:
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

    payload = build_orchestration_runtime_bundle(
        base_dir=BACKEND_DIR,
        session_id="session-orch-health",
        task_id="taskinst:turn:session-orch-health:1:health_issue_triage",
        user_goal="请检查这个 health issue 的修复建议。",
        task_assembly_bundle=task_bundle,
        current_turn_context={
            "authority": "context.current_turn",
            "turn_id": "turn:session-orch-health:1",
            "selected_task_id": "task.health.issue_triage",
        },
    )

    runtime_spec = payload["agent_runtime_spec"]
    orchestration = payload["task_body_orchestration"]

    assert runtime_spec["runtime_lane"] in {"health_issue_read", "full_interactive"}
    assert orchestration["resource_binding_plan"]["operation_requirement_ref"].startswith("opreq:")
    assert orchestration["verification_gate_plan"]["task_constraints"] == task_bundle["task_execution_assembly"]["task_constraints"]


def test_orchestration_runtime_bundle_uses_formal_short_story_task_profiles() -> None:
    task_bundle = build_task_execution_assembly_bundle(
        session_id="session-orch-story",
        task_id="taskinst:turn:session-orch-story:1:short_story",
        user_goal="请完成一个经过创意审核、正文编写、内容纠察和验收的短篇小说。",
        source="test",
        current_turn_context={
            "authority": "context.current_turn",
            "turn_id": "turn:session-orch-story:1",
            "selected_task_id": "task.writing.short_story",
        },
    )

    assembly = task_bundle["task_execution_assembly"]

    assert assembly["task_mode"] == "short_story"
    assert assembly["task_family"] == "writing"
    assert assembly["workflow_id"] == "workflow.writing.short_story"
    assert assembly["flow_contract_id"] == "flow.writing.short_story"
    assert assembly["communication_protocol_ref"] == "protocol.writing.short_story_pipeline"
    assert assembly["coordination_task_ref"] == "coord.writing.short_story_pipeline"
    assert assembly["topology_template_ref"] == "topology.writing.short_story_pipeline"


def test_orchestration_runtime_bundle_uses_longform_chapter_pipeline_instead_of_short_story_defaults() -> None:
    task_bundle = build_task_execution_assembly_bundle(
        session_id="session-orch-longform",
        task_id="taskinst:turn:session-orch-longform:1:chapter_drafting",
        user_goal="请根据长篇小说设定生成第12章正文并通过审校。",
        source="test",
        current_turn_context={
            "authority": "context.current_turn",
            "turn_id": "turn:session-orch-longform:1",
            "selected_task_id": "task.writing.chapter_drafting",
        },
    )

    assembly = task_bundle["task_execution_assembly"]
    execution_policy = task_bundle["task_execution_policy"]
    coordination = task_bundle["coordination_task_record"]

    assert assembly["task_mode"] == "chapter_drafting"
    assert assembly["workflow_id"] == "workflow.writing.chapter_drafting"
    assert assembly["flow_contract_id"] == "flow.writing.chapter_drafting"
    assert assembly["communication_protocol_ref"] == "protocol.writing.chapter_pipeline"
    assert assembly["coordination_task_ref"] == "coord.writing.chapter_pipeline"
    assert assembly["topology_template_ref"] == "topology.writing.chapter_pipeline"
    assert assembly["metadata"]["template_id"] == "template.writing.chapter_drafting"
    assert execution_policy["execution_chain_type"] == "coordination_chain"
    assert execution_policy["metadata"]["agent_group_id"] == "group.writing.longform_novel_core"
    assert coordination["agent_group_id"] == "group.writing.longform_novel_core"
    assert coordination["participant_agent_ids"] == ["agent:23", "agent:24", "agent:25", "agent:26"]
    assert coordination["stop_conditions"] == ["chapter_work_accepted", "review_completed", "revision_loop_closed", "revision_budget_exhausted"]
    assert coordination["subtask_refs"] == [
        "task.writing.chapter_planning",
        "task.writing.chapter_drafting",
        "task.writing.chapter_revision",
        "task.writing.continuity_audit",
    ]


def test_longform_project_bootstrap_contract_routes_chapter_planning_before_drafting() -> None:
    from tasks.flow_registry import TaskFlowRegistry

    registry = TaskFlowRegistry(BACKEND_DIR)
    coordination = registry.get_coordination_task("coord.writing.longform_project_bootstrap")
    topology = registry.get_topology_template("topology.writing.longform_project_bootstrap")

    assert coordination is not None
    assert topology is not None
    stage_contracts = list(coordination.metadata["stage_contracts"])
    stage_order = [dict(item)["stage_id"] for item in stage_contracts]
    assert stage_order.index("volume_planning") < stage_order.index("chapter_planning")
    assert stage_order.index("chapter_planning") < stage_order.index("chapter_pipeline")
    by_stage = {dict(item)["stage_id"]: dict(item) for item in stage_contracts}
    assert by_stage["chapter_planning"]["task_ref"] == "task.writing.chapter_planning"
    assert by_stage["chapter_pipeline"]["task_ref"] == "task.writing.chapter_drafting"
    assert any(
        dict(edge).get("from") == "chapter_pipeline" and dict(edge).get("to") == "chapter_drafting"
        for edge in topology.edges
    )


def test_longform_chapter_coordination_keeps_structure_and_carries_user_request_at_runtime() -> None:
    from tasks.template_registry import default_task_templates
    from tasks.flow_registry import TaskFlowRegistry

    templates = {item.template_id: item for item in default_task_templates()}
    longform_template_ids = {
        "template.writing.longform_novel_project",
        "template.writing.novel_bible_build",
        "template.writing.volume_planning",
        "template.writing.chapter_planning",
        "template.writing.chapter_drafting",
        "template.writing.chapter_revision",
        "template.writing.continuity_audit",
        "template.writing.final_compilation",
    }

    for template_id in longform_template_ids:
        template = templates[template_id]
        assert template.required_operations == ("op.model_response", "op.write_file")
        assert template.optional_operations == ()
        assert template.metadata["runtime_limits"]["max_runtime_seconds"] is None
        assert template.metadata["runtime_tool_policy"] == "write_first_artifact"

    registry = TaskFlowRegistry(BACKEND_DIR)
    coordination = registry.get_coordination_task("coord.writing.chapter_pipeline")
    protocol = registry.get_task_communication_protocol("protocol.writing.chapter_pipeline")

    assert coordination is not None
    assert coordination.title == "长篇小说章节协作流水线"
    assert coordination.metadata["structure_role"] == "stable_coordination_skeleton"
    assert coordination.metadata["request_policy"] == "runtime_request_is_carried_as_natural_language_brief"
    assert "chapter_work_accepted" in coordination.stop_conditions
    assert "revision_budget_exhausted" in coordination.stop_conditions
    assert coordination.coordination_mode == "chapter_collaboration_loop"
    for forbidden_key in ("batch_size", "target_chars", "parallel_batch_slots", "review_intensity", "review_policy", "revision_budget"):
        assert forbidden_key not in coordination.metadata

    assert protocol is not None
    assert "revision_loop_optional" in protocol.signal_rules
    assert protocol.metadata.get("protocol_role", "message_contract_only") == "message_contract_only"
    for forbidden_key in ("batch_size", "target_chars", "parallel_batch_slots", "review_intensity", "review_policy", "revision_budget"):
        assert forbidden_key not in protocol.metadata

    task_bundle = build_task_execution_assembly_bundle(
        session_id="session-orch-longform-request-brief",
        task_id="taskinst:turn:session-orch-longform-request-brief:1:chapter_drafting",
        user_goal="按既定长篇结构先推进前100章，目标约20万字，节奏快一点但工作流不要变。",
        source="test",
        current_turn_context={
            "authority": "context.current_turn",
            "turn_id": "turn:session-orch-longform-request-brief:1",
            "selected_task_id": "task.writing.chapter_drafting",
        },
    )
    brief = task_bundle["coordination_request_brief"]
    assert brief["authority"] == "task_system.coordination_request_brief"
    assert brief["coordination_task_id"] == "coord.writing.chapter_pipeline"
    assert brief["natural_request"] == "按既定长篇结构先推进前100章，目标约20万字，节奏快一点但工作流不要变。"
    assert brief["planning_policy"] == "coordinator_agent_interprets_request_inside_stable_workflow"
    assert task_bundle["task_execution_assembly"]["metadata"]["coordination_request_ref"] == brief["brief_id"]


def test_explicit_longform_task_selection_suppresses_document_route_noise() -> None:
    from orchestration.agent_runtime_chain import _align_understanding_with_explicit_task_selection
    from understanding.query_understanding import analyze_query_understanding

    message = (
        "这是写作域的真实执行任务，不是文档阅读、文件解读、PDF分析。"
        "请生成第001章到第003章短批次规划，并写入 "
        "docs/系统规划/任务系统实测记录/artifacts/20260506/E5/batches/batch_001_003_plan.md。"
    )
    understanding = analyze_query_understanding(message)

    assert understanding.capability_requests == ["document_analysis"]
    assert understanding.intent == "pdf_document_section"

    aligned = _align_understanding_with_explicit_task_selection(
        BACKEND_DIR,
        understanding,
        task_selection={"selected_task_id": "task.writing.chapter_planning"},
    )

    assert aligned.source_kind == "task_system"
    assert aligned.task_kind == "chapter_planning"
    assert aligned.route == "agent"
    assert aligned.execution_posture == "task_runtime"
    assert aligned.capability_requests == []
    assert aligned.candidate_tools == []
    assert aligned.tool_name is None
    assert aligned.structural_signals["understanding_aligned_to_explicit_task"] is True
