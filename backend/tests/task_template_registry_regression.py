from __future__ import annotations

from tasks import TaskFlowRegistry, TaskTemplateRegistry
from understanding import analyze_memory_intent, analyze_task_understanding


def test_task_template_registry_lists_core_templates() -> None:
    templates = TaskTemplateRegistry().list_templates()
    template_ids = {item.template_id for item in templates}

    assert "template.general.main_conversation" in template_ids
    assert "template.chat.general_response" in template_ids
    assert "template.rag.knowledge_answer" in template_ids
    assert "template.pdf.document_analysis" in template_ids
    assert "template.data.structured_analysis" in template_ids
    assert "template.dev.workspace_patch" in template_ids
    assert "template.dev.light_web_game" in template_ids


def test_task_template_registry_fallback_uses_canonical_general_template() -> None:
    registry = TaskTemplateRegistry()
    template = registry.select_template(
        user_goal="给我一个简短结论",
        query_understanding={},
        current_turn_context={"authority": "context.current_turn", "execution_mode": "single"},
        definitions=[],
    )

    assert template.template_id == "template.general.main_conversation"


def test_task_template_registry_never_returns_unregistered_template() -> None:
    registry = TaskTemplateRegistry()
    template_ids = {item.template_id for item in registry.list_templates()}
    scenarios = [
        ({}, {"authority": "context.current_turn"}),
        ({"route_hint": "rag", "execution_posture": "direct_rag"}, {"authority": "context.current_turn"}),
        ({"route_hint": "pdf", "preferred_skill": "pdf-analysis"}, {"authority": "context.current_turn"}),
        ({"route_hint": "structured_data", "preferred_skill": "structured-data-analysis"}, {"authority": "context.current_turn"}),
        ({"route_hint": "workspace_read", "execution_posture": "builtin_tool_lane"}, {"authority": "context.current_turn"}),
    ]
    for query_understanding, current_turn_context in scenarios:
        task_intent = registry.build_task_intent_contract(
            session_id="session-template-registered",
            task_id="task-template-registered",
            user_goal="测试任务模板选择",
            query_understanding=query_understanding,
            current_turn_context=current_turn_context,
        )
        match = registry.match_template(
            task_intent_contract=task_intent,
            query_understanding=query_understanding,
            current_turn_context=current_turn_context,
            definitions=[],
        )
        assert match.template_id in template_ids


def test_task_template_registry_prefers_capability_resolution_when_present() -> None:
    registry = TaskTemplateRegistry()
    task_intent = registry.build_task_intent_contract(
        session_id="session-template-resolution",
        task_id="task-template-resolution",
        user_goal="帮我看一下 inventory.xlsx 里销量前五的有哪些",
        query_understanding={
            "route_hint": "agent",
            "execution_posture": "direct_mcp",
            "preferred_skill": "",
            "capability_resolution": {
                "route": "structured_data",
                "selected_candidate_type": "mcp",
                "selected_candidate_name": "structured_data",
            },
        },
        current_turn_context={"authority": "context.current_turn", "execution_mode": "single"},
    )

    match = registry.match_template(
        task_intent_contract=task_intent,
        query_understanding={
            "route_hint": "agent",
            "execution_posture": "direct_mcp",
            "preferred_skill": "",
            "capability_resolution": {
                "route": "structured_data",
                "selected_candidate_type": "mcp",
                "selected_candidate_name": "structured_data",
            },
        },
        current_turn_context={"authority": "context.current_turn", "execution_mode": "single"},
        definitions=[],
    )

    assert match.template_id == "template.data.structured_analysis"


def test_task_template_registry_prefers_current_dataset_route_over_stale_pdf_binding() -> None:
    registry = TaskTemplateRegistry()
    query_understanding = {
        "route_hint": "structured_data",
        "execution_posture": "direct_mcp",
        "source_kind": "dataset",
        "modality": "table",
        "preferred_skill": "structured-data-analysis",
        "capability_requests": ["dataset_analysis"],
        "capability_resolution": {
            "route": "structured_data",
            "execution_posture": "direct_mcp",
            "selected_candidate_type": "mcp",
            "selected_candidate_name": "structured_data",
        },
    }
    task_intent = registry.build_task_intent_contract(
        session_id="session-dataset-overrides-pdf",
        task_id="task-dataset-overrides-pdf",
        user_goal="切到 Data/inventory.xlsx，按仓库概览库存缺口。",
        query_understanding=query_understanding,
        current_turn_context={
            "authority": "context.current_turn",
            "execution_mode": "single",
            "resolved_bindings": [
                {"binding_kind": "source_file", "file_kind": "dataset", "binding_id": "binding:dataset"},
                {"binding_kind": "source_file", "file_kind": "pdf", "binding_id": "binding:pdf"},
            ],
            "explicit_inputs": {
                "explicit_dataset_path": "Data/inventory.xlsx",
                "bound_pdf_path": "knowledge/old.pdf",
                "capability_requests": ["dataset_analysis"],
            },
        },
    )

    match = registry.match_template(
        task_intent_contract=task_intent,
        query_understanding=query_understanding,
        current_turn_context={"authority": "context.current_turn", "execution_mode": "single"},
        definitions=[],
    )

    assert match.template_id == "template.data.structured_analysis"
    assert "structured_data_mcp_route" in match.match_reasons


def test_task_template_registry_prefers_realtime_request_over_stale_file_bindings() -> None:
    registry = TaskTemplateRegistry()
    task_intent = registry.build_task_intent_contract(
        session_id="session-realtime-over-stale-bindings",
        task_id="task-realtime-over-stale-bindings",
        user_goal="把实时查询结果改写成值班提示，至少要同时提到黄金和北京天气。",
        query_understanding={
            "source_kind": "mixed_sources",
            "modality": "multi",
            "capability_requests": ["weather", "latest_information", "gold_price"],
            "capability_resolution": {
                "route": "agent",
                "execution_posture": "bounded_agent",
                "selected_candidate_type": "agent",
            },
        },
        current_turn_context={
            "authority": "context.current_turn",
            "execution_mode": "single",
            "explicit_inputs": {
                "bound_dataset_path": "Data/employees.xlsx",
                "bound_pdf_path": "backend/knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf",
                "capability_requests": ["weather", "latest_information", "gold_price"],
                "tool_input": {"query": "把实时查询结果改写成值班提示，至少要同时提到黄金和北京天气。"},
            },
            "resolved_bindings": [
                {"binding_kind": "source_file", "file_kind": "pdf", "binding_id": "binding:pdf"},
                {"binding_kind": "source_file", "file_kind": "dataset", "binding_id": "binding:dataset"},
            ],
        },
    )

    match = registry.match_template(
        task_intent_contract=task_intent,
        query_understanding={
            "source_kind": "mixed_sources",
            "modality": "multi",
            "capability_requests": ["weather", "latest_information", "gold_price"],
            "capability_resolution": {
                "route": "agent",
                "execution_posture": "bounded_agent",
                "selected_candidate_type": "agent",
            },
        },
        current_turn_context={"authority": "context.current_turn", "execution_mode": "single"},
        definitions=[],
    )

    assert match.template_id == "template.search.information_search"
    assert "candidate_template:template.search.information_search" in match.match_reasons


def test_task_template_registry_selects_game_template_for_light_web_game_request() -> None:
    template = TaskTemplateRegistry().select_template(
        user_goal="开发一个贪吃蛇小游戏，并接到当前前端页面里。",
        query_understanding={"source_kind": "workspace", "candidate_tools": ["read_file", "edit_file"]},
        current_turn_context={"authority": "context.current_turn", "execution_mode": "single"},
        definitions=[],
    )

    assert template.template_id == "template.dev.light_web_game"
    assert any(step.step_kind == "verify" for step in template.step_blueprints)


def test_task_template_registry_matches_followup_bundle_item_by_contract() -> None:
    registry = TaskTemplateRegistry()
    task_intent = registry.build_task_intent_contract(
        session_id="session-followup",
        task_id="task-followup",
        user_goal="只展开第二个子任务。",
        query_understanding={"intent": "bundle_followup", "capability_requests": ["structured_data"]},
        current_turn_context={
            "authority": "context.current_turn",
            "intent": "bundle_followup",
            "execution_mode": "single",
            "bundle_items": [
                {
                    "item_id": "bundle:task-followup:item:2",
                    "ordinal": 2,
                    "user_text": "inventory.xlsx 最缺货的前三个仓库",
                    "template_id": "template.data.structured_analysis",
                    "capability_kind": "structured_data",
                    "required_tool": "",
                }
            ],
            "followup_target_refs": ["bundle:2:inventory"],
        },
    )

    match = registry.match_template(
        task_intent_contract=task_intent,
        query_understanding={"intent": "bundle_followup", "capability_requests": ["structured_data"]},
        current_turn_context={
            "authority": "context.current_turn",
            "intent": "bundle_followup",
            "execution_mode": "single",
        },
        definitions=[],
    )

    assert match.template_id == "template.data.structured_analysis"
    assert match.match_source == "binding_contract"
    assert "candidate_template:template.data.structured_analysis" in match.match_reasons


def test_task_template_registry_marks_bundle_ordinal_followup_even_with_active_dataset() -> None:
    registry = TaskTemplateRegistry()
    task_intent = registry.build_task_intent_contract(
        session_id="session-bundle-ordinal-followup",
        task_id="task-bundle-ordinal-followup",
        user_goal="把第一个和第三个子任务各压成一句话，不要再提第二个。",
        query_understanding={
            "source_kind": "knowledge_base",
            "task_kind": "knowledge_lookup",
            "structural_signals": {
                "followup_target_kind": "bundle_ordinals",
                "followup_ordinals": [1, 3],
            },
        },
        current_turn_context={
            "authority": "context.current_turn",
            "execution_mode": "single",
            "explicit_inputs": {"bound_dataset_path": "Data/inventory.xlsx"},
        },
    )

    assert task_intent.execution_intent == "bundle_followup_item"
    assert task_intent.diagnostics["followup_target_kind"] == "bundle_ordinals"

    match = registry.match_template(
        task_intent_contract=task_intent,
        query_understanding={
            "source_kind": "bundle_result",
            "task_kind": "bundle_followup",
            "route_hint": "bundle_followup",
            "structural_signals": {
                "followup_target_kind": "bundle_ordinals",
                "followup_ordinals": [1, 3],
            },
        },
        current_turn_context={"authority": "context.current_turn", "execution_mode": "single"},
        definitions=[],
    )

    assert match.template_id == "template.bundle.multi_capability"
    assert "bundle_followup_item" in match.match_reasons


def test_task_system_overview_exposes_templates_and_validation_matrix(tmp_path) -> None:
    payload = TaskFlowRegistry(tmp_path).build_overview()

    assert payload["summary"]["task_template_count"] >= 6
    assert payload["summary"]["projection_binding_count"] == 0
    assert payload["summary"]["derived_projection_binding_count"] == 0
    assert payload["summary"]["effective_projection_binding_count"] == 0
    assert payload["summary"]["flow_contract_binding_count"] == 0
    assert payload["summary"]["derived_flow_contract_binding_count"] == 0
    assert payload["summary"]["effective_flow_contract_binding_count"] == 0
    assert payload["summary"]["adoption_plan_count"] == 0
    assert payload["summary"]["derived_adoption_plan_count"] == 0
    assert payload["summary"]["effective_adoption_plan_count"] == 0
    assert payload["summary"]["memory_request_profile_count"] == 0
    assert payload["summary"]["derived_memory_request_profile_count"] == 0
    assert payload["summary"]["effective_memory_request_profile_count"] == 0
    assert payload["summary"]["communication_protocol_count"] == 0
    assert payload["templates"]
    assert payload["template_validation_matrix"]["authority"] == "task_system.template_validation_matrix"
    assert all("template_id" in row for row in payload["template_validation_matrix"]["rows"])


def test_semantic_memory_read_prefers_memory_route() -> None:
    memory_intent = analyze_memory_intent("如果我之后再问复杂问题，你应该先怎么回答？")
    understanding = analyze_task_understanding("如果我之后再问复杂问题，你应该先怎么回答？", memory_intent)

    assert memory_intent.intent == "memory_read_signal"
    assert memory_intent.memory_read_mode == "durable_semantic"
    assert memory_intent.should_skip_rag is True
    assert understanding.route_hint == "memory"
    assert understanding.execution_posture == "direct_memory"
    assert understanding.source_kind == "memory"


def test_task_template_registry_selects_memory_template_for_memory_route() -> None:
    registry = TaskTemplateRegistry()
    task_intent = registry.build_task_intent_contract(
        session_id="session-memory-template",
        task_id="task-memory-template",
        user_goal="如果我之后再问复杂问题，你应该先怎么回答？",
        query_understanding={
            "intent": "memory_read_signal",
            "route_hint": "memory",
            "execution_posture": "direct_memory",
            "source_kind": "memory",
            "modality": "memory",
            "capability_resolution": {
                "route": "memory",
                "execution_posture": "direct_memory",
            },
        },
        current_turn_context={"authority": "context.current_turn", "execution_mode": "single"},
    )

    match = registry.match_template(
        task_intent_contract=task_intent,
        query_understanding={
            "intent": "memory_read_signal",
            "route_hint": "memory",
            "execution_posture": "direct_memory",
            "source_kind": "memory",
            "modality": "memory",
            "capability_resolution": {
                "route": "memory",
                "execution_posture": "direct_memory",
            },
        },
        current_turn_context={"authority": "context.current_turn", "execution_mode": "single"},
        definitions=[],
    )

    assert match.template_id == "template.memory.recall_answer"
    assert "memory_route" in match.match_reasons
