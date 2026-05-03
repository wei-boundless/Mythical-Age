from __future__ import annotations

import asyncio
from pathlib import Path

from api.tasks import TaskRuntimeContractRequest, task_runtime_contract
from orchestration import AgentRuntimeRegistry
from orchestration.runtime_loop.model_adoption import build_model_response_runtime_adoption
from tasks import build_task_runtime_contract


def test_search_task_runtime_contract_keeps_resources_out_of_prompt() -> None:
    runtime = build_task_runtime_contract(
        session_id="session-1",
        task_id="task-search",
        user_goal="帮我联网搜索 Claude Code subagent 官方资料",
    )

    assert runtime["status"] == "runtime"
    assert runtime["runtime_executable"] is True
    assert runtime["task_contract"]["authority"] == "task_contract"
    assert runtime["operation_requirement"]["authority"] == "candidate_only"
    assert runtime["task_prompt_contract"]["resource_section"] == ""
    assert runtime["task_prompt_contract"]["guardrail_section"] == ""
    assert runtime["task_prompt_contract"]["metadata"]["runtime_directive_enabled"] is True
    assert runtime["task_prompt_contract"]["metadata"]["runtime_executable"] is True
    assert runtime["selected_template"]["template_id"] == "template.search.information_search"
    assert runtime["task_spec"]["template_id"] == "template.search.information_search"
    assert runtime["task_spec"]["task_spec_ref"] == runtime["task_contract"]["task_spec_ref"]
    assert runtime["task_intent_contract"]["authority"] == "task_system.task_intent_contract"
    assert runtime["template_match"]["authority"] == "task_system.template_match"
    assert runtime["projection_selection"]["authority"] == "task_system.projection_selection_result"
    assert runtime["task_execution_assembly"]["authority"] == "task_system.task_execution_assembly"
    assert runtime["task_execution_assembly"]["task_spec_ref"] == runtime["task_spec"]["task_spec_ref"]
    assert runtime["task_execution_assembly"]["operation_requirement_ref"] == runtime["operation_requirement"]["requirement_id"]
    assert runtime["task_projection_binding"]["authority"] == "task_system.task_projection_binding"
    assert runtime["task_flow_contract_binding"]["authority"] == "task_system.task_flow_contract_binding"
    assert runtime["task_agent_adoption_plan"]["authority"] == "task_system.task_agent_adoption_plan"
    assert runtime["task_memory_request_profile"]["authority"] == "task_system.task_memory_request_profile"
    assert runtime["task_spec"]["task_intent_ref"] == runtime["task_intent_contract"]["task_intent_id"]
    assert runtime["task_spec"]["template_match_ref"] == runtime["template_match"]["match_id"]
    assert runtime["task_spec"]["step_input_bindings"]


def test_local_read_summary_runtime_contract_does_not_default_to_web_search() -> None:
    runtime = build_task_runtime_contract(
        session_id="session-2",
        task_id="task-local-read",
        user_goal="读取 docs/系统规划/灵魂系统/05-讨论-20260428.md 并总结",
    )

    operations = set(runtime["operation_requirement"]["required_operations"])

    assert {"op.read_file", "op.search_files", "op.search_text"} <= operations
    assert "op.web_search" not in operations
    assert runtime["selected_template"]["template_id"] == "template.dev.workspace_patch"
    assert runtime["task_spec"]["selected_agent_id"] == "agent:0"


def test_visible_prompt_feedback_stays_current_context_only_without_local_read_tools() -> None:
    runtime = build_task_runtime_contract(
        session_id="session-visible-context",
        task_id="task-visible-context",
        user_goal="基于已读取内容总结一下当前 prompts 反馈，看看还有哪些矛盾",
    )

    operations = set(runtime["operation_requirement"]["required_operations"])

    assert runtime["definitions"][0]["definition_id"] == "task.request_intake"
    assert "op.model_response" in operations
    assert "op.read_file" not in operations
    assert "op.search_files" not in operations
    assert "op.search_text" not in operations
    assert runtime["task_spec"]["requested_outputs"] == ["final_answer"]


def test_explicit_local_path_still_requests_local_read_operations() -> None:
    runtime = build_task_runtime_contract(
        session_id="session-explicit-local",
        task_id="task-explicit-local",
        user_goal="打开 backend/soul/agent_core/CORE.md 看一下并总结",
    )

    operations = set(runtime["operation_requirement"]["required_operations"])

    assert runtime["definitions"][0]["definition_id"] == "task.local_material_read"
    assert {"op.read_file", "op.search_files", "op.search_text"} <= operations
    assert runtime["selected_template"]["template_id"] == "template.dev.workspace_patch"


def test_modify_then_review_runtime_contract_requests_edit_without_exposing_resource_prompt() -> None:
    runtime = build_task_runtime_contract(
        session_id="session-3",
        task_id="task-modify-review",
        user_goal="修改任务系统文档，然后检查有没有前后矛盾",
    )

    operations = set(runtime["operation_requirement"]["required_operations"])
    manifest_sections = {item["section_id"]: item for item in runtime["prompt_manifest"]["sections"]}

    assert "op.edit_file" in operations
    assert runtime["task_prompt_contract"]["guardrail_section"] == ""
    assert "resource_section" not in manifest_sections
    assert "guardrail_section" not in manifest_sections
    assert runtime["selected_template"]["template_id"] == "template.dev.workspace_patch"


def test_task_runtime_contract_api_returns_runtime_contract() -> None:
    payload = TaskRuntimeContractRequest(
        session_id="session-api",
        task_id="task-api",
        user_goal="读取 docs/系统规划/操作系统与任务系统/03-任务系统与操作系统接线方案-20260429.md 并总结",
    )

    runtime = asyncio.run(task_runtime_contract(payload))

    assert runtime["status"] == "runtime"
    assert runtime["runtime_executable"] is True
    assert runtime["task_prompt_contract"]["metadata"]["runtime_directive_enabled"] is True
    assert runtime["task_spec"]["operation_requirement_ref"].startswith("opreq:")


def test_direct_tool_runtime_contract_does_not_fall_back_to_request_intake() -> None:
    runtime = build_task_runtime_contract(
        session_id="session-weather",
        task_id="task-weather",
        user_goal="再查一下北京今天天气。",
        query_understanding={
            "execution_posture": "direct_tool",
            "route_hint": "tool",
            "source_kind": "external_web",
            "task_kind": "realtime_lookup",
            "modality": "realtime",
            "candidate_tools": ["get_weather"],
            "capability_requests": ["weather"],
        },
    )

    definition_ids = [item["definition_id"] for item in runtime["definitions"]]
    task_section = runtime["task_prompt_contract"]["task_section"]
    output_section = runtime["task_prompt_contract"]["output_section"]
    operations = set(runtime["operation_requirement"]["required_operations"])

    assert "task.request_intake" not in definition_ids
    assert "task.capability_execution" in definition_ids
    assert "No execution is performed." not in task_section
    assert "execute the relevant capability" in output_section
    assert "op.model_response" in operations
    assert runtime["selected_template"]["template_id"] == "template.capability.direct_tool"


def test_direct_rag_runtime_contract_does_not_fall_back_to_request_intake() -> None:
    runtime = build_task_runtime_contract(
        session_id="session-rag",
        task_id="task-rag",
        user_goal="基于本地知识库，告诉我 AI 治理里最常见的三类风险。",
        query_understanding={
            "execution_posture": "direct_rag",
            "route_hint": "rag",
            "source_kind": "knowledge_base",
            "task_kind": "knowledge_lookup",
            "modality": "general",
            "preferred_skill": "rag-skill",
            "capability_requests": ["knowledge_lookup"],
        },
    )

    definition_ids = [item["definition_id"] for item in runtime["definitions"]]
    task_section = runtime["task_prompt_contract"]["task_section"]

    assert "task.request_intake" not in definition_ids
    assert definition_ids[0] == "task.knowledge_retrieval"
    assert "No execution is performed." not in task_section
    assert runtime["selected_template"]["template_id"] == "template.rag.knowledge_answer"


def test_bundle_runtime_contract_exposes_task_spec_and_bundle_template() -> None:
    runtime = build_task_runtime_contract(
        session_id="session-bundle",
        task_id="task-bundle",
        user_goal="先总结 PDF 第三页，再给我 inventory.xlsx 最缺货的前三个仓库，最后补一句北京天气。",
        current_turn_context={
            "authority": "context.current_turn",
            "execution_mode": "bundle",
            "explicit_inputs": {
                "bound_pdf_path": "knowledge/AI Knowledge/report.pdf",
                "explicit_dataset_path": "knowledge/E-commerce Data/inventory.xlsx",
            },
            "bundle_items": [
                {"ordinal": 1, "user_text": "总结 PDF 第三页", "capability_kind": "pdf", "required_tool": "pdf_analysis"},
                {"ordinal": 2, "user_text": "inventory.xlsx 最缺货的前三个仓库", "capability_kind": "structured_data", "required_tool": "structured_data_analysis"},
                {"ordinal": 3, "user_text": "补一句北京天气", "capability_kind": "weather", "required_tool": "get_weather"},
            ],
            "resolved_bindings": [
                {"binding_kind": "source_file", "file_kind": "pdf", "metadata": {"path": "knowledge/AI Knowledge/report.pdf"}},
                {"binding_kind": "source_file", "file_kind": "dataset", "metadata": {"path": "knowledge/E-commerce Data/inventory.xlsx"}},
            ],
        },
        query_understanding={
            "intent": "multi_capability_request",
            "candidate_tools": ["pdf_analysis", "structured_data_analysis", "get_weather"],
        },
    )

    assert runtime["selected_template"]["template_id"] == "template.bundle.multi_capability"
    assert runtime["task_contract"]["selected_template_id"] == "template.bundle.multi_capability"
    assert runtime["task_spec"]["template_id"] == "template.bundle.multi_capability"
    assert runtime["task_spec"]["task_spec_ref"] == runtime["task_contract"]["task_spec_ref"]
    assert runtime["bundle_spec"]["authority"] == "task_system.bundle_spec"
    assert runtime["task_spec"]["bundle_spec_ref"] == runtime["bundle_spec"]["bundle_id"]
    assert len(runtime["bundle_spec"]["items"]) == 3
    assert runtime["bundle_spec"]["items"][0]["template_id"] == "template.pdf.document_analysis"
    assert runtime["task_spec"]["step_input_bindings"][0]["input_refs"] == ["input.bundle_spec"]
    assert "bundle_items" not in runtime["task_spec"]["inputs"]


def test_specific_light_web_game_task_contract_promotes_development_execution_shape() -> None:
    runtime = build_task_runtime_contract(
        session_id="session-game-contract",
        task_id="task-game-contract",
        user_goal="请生成一个可以直接运行的网页贪吃蛇小游戏。",
        current_turn_context={
            "authority": "context.current_turn",
            "selected_task_id": "task.dev.light_web_game",
        },
    )

    definition_ids = [item["definition_id"] for item in runtime["definitions"]]
    required_operations = set(runtime["operation_requirement"]["required_operations"])
    optional_operations = set(runtime["operation_requirement"]["optional_operations"])
    denied_operations = set(runtime["operation_requirement"]["denied_operations"])

    assert runtime["registered_task"]["task_id"] == "task.dev.light_web_game"
    assert runtime["selected_template"]["template_id"] == "template.dev.light_web_game"
    assert definition_ids == ["task.task_execution", "task.inspection_and_correction"]
    assert runtime["operation_requirement"]["metadata"]["approval_policy"] == "task_bounded_write"
    assert {"op.edit_file", "op.read_file", "op.search_files"} <= required_operations
    assert "op.write_file" in optional_operations
    assert "op.edit_file" not in denied_operations
    assert "op.write_file" not in denied_operations


def test_specific_arcade_game_bundle_contract_exposes_bounded_write_safety_envelope() -> None:
    runtime = build_task_runtime_contract(
        session_id="session-arcade-contract",
        task_id="task-arcade-contract",
        user_goal="生成一个多文件网页小游戏包，包含开始界面、游戏逻辑和说明。",
        current_turn_context={
            "authority": "context.current_turn",
            "selected_task_id": "task.dev.arcade_game_bundle",
            "target_root": "frontend/public/games/arcade_bundle",
        },
    )

    safety_envelope = runtime["task_spec"]["safety_envelope"]
    operations = set(runtime["operation_requirement"]["required_operations"])

    assert runtime["registered_task"]["task_id"] == "task.dev.arcade_game_bundle"
    assert runtime["selected_template"]["template_id"] == "template.dev.arcade_game_bundle"
    assert safety_envelope["safety_class"] == "S1_bounded_artifact_write"
    assert safety_envelope["write_mode"] == "bounded_create"
    assert safety_envelope["write_roots"] == ["frontend/public/games/arcade_bundle"]
    assert "backend" in safety_envelope["forbidden_paths"]
    assert {"op.read_file", "op.search_files", "op.search_text", "op.edit_file"} <= operations


def test_specific_bounded_patch_contract_exposes_scoped_patch_safety_envelope() -> None:
    runtime = build_task_runtime_contract(
        session_id="session-bounded-patch",
        task_id="task-bounded-patch",
        user_goal="在 frontend/src/components 内修复一个按钮状态问题。",
        current_turn_context={
            "authority": "context.current_turn",
            "selected_task_id": "task.dev.bounded_patch",
            "target_root": "frontend/src/components",
        },
    )

    safety_envelope = runtime["task_spec"]["safety_envelope"]
    required_operations = set(runtime["operation_requirement"]["required_operations"])

    assert runtime["registered_task"]["task_id"] == "task.dev.bounded_patch"
    assert runtime["selected_template"]["template_id"] == "template.dev.workspace_patch"
    assert safety_envelope["safety_class"] == "S2_bounded_patch"
    assert safety_envelope["write_mode"] == "scoped_patch"
    assert safety_envelope["write_roots"] == ["frontend/src/components"]
    assert ".git" in safety_envelope["forbidden_paths"]
    assert {"op.read_file", "op.search_files", "op.search_text", "op.edit_file"} <= required_operations


def test_runtime_contract_compat_projection_preserves_task_selection_without_projection_card() -> None:
    runtime = build_task_runtime_contract(
        session_id="session-explicit-projection",
        task_id="task-explicit-projection",
        user_goal="帮我联网搜索 Claude Code subagent 官方资料。",
        current_turn_context={
            "authority": "context.current_turn",
            "selected_projection_id": "projection.shadow.only",
        },
    )

    projection_selection = runtime["projection_selection"]
    projection_requirement = runtime["projection_requirement"]
    prompt_metadata = runtime["task_prompt_contract"]["metadata"]

    assert projection_selection["selection_source"] == "current_turn_context"
    assert projection_selection["selected_projection_id"] == "projection.shadow.only"
    assert projection_requirement["projection_id"] == "projection.shadow.only"
    assert projection_requirement["role_type"] == projection_selection["role_type"]
    assert projection_requirement["reason"] == "selected by current turn context"
    assert "projection_prompt" not in projection_requirement or projection_requirement["projection_prompt"] == ""
    assert "projection_title" not in projection_requirement or projection_requirement["projection_title"] == ""
    assert prompt_metadata["projection_source"] == "current_turn_context"


def test_specific_task_runtime_contract_exposes_formal_task_side_profiles() -> None:
    runtime = build_task_runtime_contract(
        session_id="session-specific-profiles",
        task_id="task-specific-profiles",
        user_goal="请生成一个可以直接运行的网页贪吃蛇小游戏。",
        current_turn_context={
            "authority": "context.current_turn",
            "selected_task_id": "task.dev.light_web_game",
        },
    )

    specific_task_record = runtime["specific_task_record"]
    adoption_plan = runtime["task_agent_adoption_plan"]
    memory_request_profile = runtime["task_memory_request_profile"]
    flow_contract_binding = runtime["task_flow_contract_binding"]
    execution_assembly = runtime["task_execution_assembly"]

    assert specific_task_record["task_id"] == "task.dev.light_web_game"
    assert specific_task_record["default_flow_contract_id"] == "flow.dev.light_web_game"
    assert adoption_plan["task_id"] == "task.dev.light_web_game"
    assert adoption_plan["adoption_mode"] == "adopt_existing"
    assert "long_term" in list(memory_request_profile["requested_memory_layers"])
    assert flow_contract_binding["flow_contract_id"] == "flow.dev.light_web_game"
    assert execution_assembly["agent_adoption_plan_ref"] == adoption_plan["plan_id"]
    assert execution_assembly["memory_request_profile_ref"] == memory_request_profile["profile_id"]
    assert execution_assembly["flow_contract_id"] == "flow.dev.light_web_game"


def test_model_runtime_adoption_uses_task_execution_assembly_contract_refs() -> None:
    runtime = build_task_runtime_contract(
        session_id="session-model-adoption",
        task_id="task-model-adoption",
        user_goal="请生成一个可以直接运行的网页贪吃蛇小游戏。",
        current_turn_context={
            "authority": "context.current_turn",
            "selected_task_id": "task.dev.light_web_game",
        },
    )

    directive, _policy = build_model_response_runtime_adoption(
        runtime,
        agent_runtime_profile=AgentRuntimeRegistry(Path(__file__).resolve().parents[1]).get_profile("agent:0"),
    )

    assert directive.input_contract_ref == "LightWebGameTaskInput"
    assert directive.output_contract_ref == "LightWebGameResult"
    assert directive.diagnostics["task_execution_assembly_ref"] == runtime["task_execution_assembly"]["assembly_id"]
