from __future__ import annotations

import asyncio

from api.tasks import TaskRuntimeContractRequest, task_runtime_contract
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
    assert runtime["task_spec"]["selected_agent_id"] == "agent:main"


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
