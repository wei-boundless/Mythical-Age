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


def test_local_read_summary_runtime_contract_does_not_default_to_web_search() -> None:
    runtime = build_task_runtime_contract(
        session_id="session-2",
        task_id="task-local-read",
        user_goal="读取 docs/系统规划/灵魂系统/05-讨论-20260428.md 并总结",
    )

    operations = set(runtime["operation_requirement"]["required_operations"])

    assert {"op.read_file", "op.search_files", "op.search_text"} <= operations
    assert "op.web_search" not in operations


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


def test_explicit_local_path_still_requests_local_read_operations() -> None:
    runtime = build_task_runtime_contract(
        session_id="session-explicit-local",
        task_id="task-explicit-local",
        user_goal="打开 backend/soul/agent_core/CORE.md 看一下并总结",
    )

    operations = set(runtime["operation_requirement"]["required_operations"])

    assert runtime["definitions"][0]["definition_id"] == "task.local_material_read"
    assert {"op.read_file", "op.search_files", "op.search_text"} <= operations


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
