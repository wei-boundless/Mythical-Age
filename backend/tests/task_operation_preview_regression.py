from __future__ import annotations

import asyncio

from api.tasks import TaskRuntimeContractPreviewRequest, task_runtime_contract_preview
from operations import RuntimeApprovalContext
from tasks import build_task_runtime_contract_preview


def test_search_task_preview_builds_resource_section_without_execution() -> None:
    preview = build_task_runtime_contract_preview(
        session_id="session-1",
        task_id="task-search",
        user_goal="帮我联网搜索 Claude Code subagent 官方资料",
    )

    assert preview["status"] == "preview_only"
    assert preview["task_contract"]["authority"] == "task_contract"
    assert preview["operation_requirement"]["authority"] == "candidate_only"
    assert preview["resource_policy"]["authority"] == "resource_policy"
    assert preview["resource_policy"]["preview_only"] is True
    assert preview["resource_policy"]["adopted"] is False
    assert preview["orchestration_plan_preview"]["topology_mode"] == "single_agent"
    assert preview["plan_validation"]["status"] == "blocked"
    assert preview["execution_graph_preview"]["runtime_executable"] is False
    assert preview["adoption_candidate_preview"]["status"] == "blocked"
    assert preview["adoption_block"]["blocked"] is True
    assert preview["runtime_directive_candidates"][0]["authority"] == "candidate_only"
    assert preview["runtime_directive_block"]["blocked"] is True
    assert preview["operation_gate_preflight"]["operation_gate_passed"] is False
    assert preview["directive_only_executor_preview"]["accepted_input_type"] == "RuntimeDirective"
    assert preview["directive_only_executor_preview"]["will_dispatch"] is False
    assert preview["commit_gate_preview"]["status"] == "blocked"
    assert preview["commit_gate_preview"]["commit_allowed"] is False
    assert all(candidate["allowed"] is False for candidate in preview["commit_gate_preview"]["commit_candidates"])
    assert {item["candidate_type"] for item in preview["understanding_candidate_preview"]} >= {
        "intent_frame_candidate",
        "route_candidate",
        "task_family_candidate",
        "capability_need_candidate",
        "memory_intent_candidate",
    }
    assert all(item["authority"] == "candidate_only" for item in preview["understanding_candidate_preview"])
    assert preview["control_kernel_diagnostics"]["runtime_directive_enabled"] is False

    decisions = {item["operation_id"]: item for item in preview["resource_policy"]["decisions"]}
    resource_section = preview["task_prompt_contract"]["resource_section"]

    assert decisions["op.web_search"]["decision"] == "allow"
    assert decisions["op.fetch_url"]["decision"] == "allow"
    assert decisions["op.write_file"]["decision"] == "deny"
    assert "Available in preview: op.model_response, op.web_search, op.fetch_url." in resource_section
    assert "This preview does not grant runtime execution permission." in resource_section


def test_local_read_summary_preview_does_not_default_to_web_search() -> None:
    preview = build_task_runtime_contract_preview(
        session_id="session-2",
        task_id="task-local-read",
        user_goal="读取 docs/系统规划/灵魂系统/05-讨论-20260428.md 并总结",
    )

    decisions = {item["operation_id"]: item for item in preview["resource_policy"]["decisions"]}
    resource_section = preview["task_prompt_contract"]["resource_section"]

    assert decisions["op.read_file"]["decision"] == "allow"
    assert decisions["op.search_files"]["decision"] == "allow"
    assert decisions["op.search_text"]["decision"] == "allow"
    assert "op.web_search" not in decisions
    assert "op.web_search" not in resource_section
    assert preview["task_prompt_contract"]["metadata"]["resource_policy_adopted"] is False
    assert preview["candidate_set_preview"]
    assert preview["orchestration_plan_preview"]["runtime_executable"] is False
    assert preview["commit_gate_preview"]["runtime_executable"] is False


def test_modify_then_review_preview_requires_edit_approval_and_review_policy() -> None:
    preview = build_task_runtime_contract_preview(
        session_id="session-3",
        task_id="task-modify-review",
        user_goal="修改任务系统文档，然后检查有没有前后矛盾",
    )

    decisions = {item["operation_id"]: item for item in preview["resource_policy"]["decisions"]}
    views = {item["resource_id"]: item for item in preview["resource_runtime_views"]}
    guardrail_section = preview["task_prompt_contract"]["guardrail_section"]

    assert decisions["op.read_file"]["decision"] == "allow"
    assert decisions["op.search_text"]["decision"] == "allow"
    assert decisions["op.edit_file"]["decision"] == "requires_approval"
    assert views["op.edit_file"]["requires_approval"] is True
    assert views["op.edit_file"]["runtime_executable"] is False
    assert "Review policy: required." in guardrail_section
    assert preview["resource_policy"]["runtime_executable"] is False
    soul_tools = {item["tool_id"]: item for item in preview["soul_projection_request"]["tool_views"]}
    manifest_sections = {item["section_id"]: item for item in preview["prompt_manifest_preview"]["sections"]}
    assert soul_tools["op.edit_file"]["requires_approval"] is True
    assert soul_tools["op.edit_file"]["runtime_executable"] is False
    assert manifest_sections["resource_section"]["source_type"] == "resource_policy"
    assert manifest_sections["resource_section"]["owner_layer"] == "resource_policy"
    assert manifest_sections["resource_section"]["cache_scope"] == "dynamic"
    assert preview["control_kernel_diagnostics"]["prompt_manifest_ref"].startswith("manifest-")
    assert preview["control_kernel_diagnostics"]["plan_validation_status"] == "blocked"
    assert preview["control_kernel_diagnostics"]["operation_gate_passed"] is False
    assert preview["control_kernel_diagnostics"]["executor_dispatch_enabled"] is False
    assert preview["control_kernel_diagnostics"]["commit_gate_status"] == "blocked"
    assert preview["control_kernel_diagnostics"]["commit_allowed"] is False


def test_task_preview_headless_edit_fails_closed() -> None:
    preview = build_task_runtime_contract_preview(
        session_id="session-4",
        task_id="task-headless",
        user_goal="修改任务系统文档，然后检查有没有前后矛盾",
        approval_context=RuntimeApprovalContext(
            interactive_ui_available=False,
            headless_mode=True,
        ),
    )
    decisions = {item["operation_id"]: item for item in preview["resource_policy"]["decisions"]}

    assert decisions["op.edit_file"]["decision"] == "deny"
    assert decisions["op.edit_file"]["reason"] == "approval unavailable in headless context"
    assert preview["resource_policy"]["preview_only"] is True
    assert preview["resource_policy"]["adopted"] is False


def test_task_runtime_contract_preview_api_returns_same_preview_boundary() -> None:
    payload = TaskRuntimeContractPreviewRequest(
        session_id="session-api",
        task_id="task-api",
        user_goal="读取 docs/系统规划/操作系统与任务系统/03-任务系统与操作系统接线方案-20260429.md 并总结",
    )

    preview = asyncio.run(task_runtime_contract_preview(payload))

    assert preview["status"] == "preview_only"
    assert preview["task_prompt_contract"]["metadata"]["preview_only"] is True
    assert preview["task_prompt_contract"]["metadata"]["runtime_directive_enabled"] is False
    assert preview["control_kernel_diagnostics"]["fail_closed"] is True
