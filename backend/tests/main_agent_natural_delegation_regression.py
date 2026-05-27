from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry
from harness.execution.agent_delegation_executor import AgentDelegationExecutor
from runtime.shared.context_manager import _render_agent_delegation_guidance_block
from runtime.shared.models import AgentRun
from request_intent.request_signals import build_request_signals
from task_system.services.assembly_builder import build_task_execution_assembly_bundle
from tests.support.runtime_stubs import model_turn_context


def _task_goal_type_for_goal(user_goal: str) -> str:
    lowered = user_goal.lower()
    if ".pdf" in lowered:
        return "pdf_analysis"
    if any(suffix in lowered for suffix in (".xlsx", ".xls", ".csv", ".tsv")):
        return "structured_data_analysis"
    if "知识库" in user_goal or "knowledge/" in lowered:
        return "knowledge_retrieval"
    if "天气" in user_goal:
        return "external_research"
    return "conversation"


def _target_objects_for_goal(user_goal: str) -> list[str]:
    lowered = user_goal.lower()
    if ".pdf" in lowered:
        return ["knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf"]
    if "inventory.xlsx" in lowered:
        return ["inventory.xlsx"]
    if "employees.xlsx" in lowered:
        return ["employees.xlsx"]
    if "知识库" in user_goal:
        return ["knowledge/vector_recall_accuracy"]
    return []


def _query_understanding_for_goal(user_goal: str, *, action_intent: str, work_mode: str = "read_only_analysis") -> tuple[dict, dict]:
    turn_context = model_turn_context(
        action_intent=action_intent,
        work_mode=work_mode,
        interaction_intent="answer",
        target_objects=_target_objects_for_goal(user_goal),
        desired_outcome=user_goal,
        deliverables=["grounded_answer"],
        task_goal_type=_task_goal_type_for_goal(user_goal),
        task_domain="external_web" if action_intent == "search_external" else "workspace",
    )
    understanding = {
        **build_request_signals(user_goal).to_dict(),
        "model_turn_decision": dict(turn_context["model_turn_decision"]),
        "request_facts": dict(turn_context["request_facts"]),
        "boundary_policy": dict(turn_context["boundary_policy"]),
        "action_permit": dict(turn_context["action_permit"]),
    }
    return understanding, turn_context


def _delegate_resolution(*, user_goal: str, understanding: dict, current_turn_context: dict) -> dict:
    profile = AgentRuntimeRegistry(BACKEND_DIR).get_profile("agent:0")
    assert profile is not None
    bundle = build_task_execution_assembly_bundle(
        base_dir=BACKEND_DIR,
        session_id="session-natural-delegation",
        task_id=f"taskinst:natural:{abs(hash(user_goal))}",
        user_goal=user_goal,
        source="test",
        query_understanding=understanding,
        current_turn_context=current_turn_context,
        agent_runtime_profile=profile,
    )
    requirement = bundle["operation_requirement"]
    return dict(dict(requirement.get("metadata") or {}).get("runtime_operation_resolution") or {})


def test_main_agent_natural_scenarios_select_expected_child_agents() -> None:
    scenarios = [
        (
            "查一下知识库里关于向量召回准确率的结论，给我证据来源。",
            "agent:knowledge_searcher",
            "op.mcp_retrieval",
        ),
        (
            "请阅读 knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf 的结论部分，并说明哪些页是真正结论页。",
            "agent:pdf_reader",
            "op.mcp_pdf",
        ),
        (
            "分析 inventory.xlsx，按仓库汇总缺口最高的前三名。",
            "agent:table_analyst",
            "op.mcp_structured_data",
        ),
        (
            "打开 knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf，总结第二部分。",
            "agent:pdf_reader",
            "op.mcp_pdf",
        ),
        (
            "帮我看 employees.xlsx 里薪资最高的前五名，带上部门。",
            "agent:table_analyst",
            "op.mcp_structured_data",
        ),
    ]

    for user_goal, expected_agent, fallback_operation in scenarios:
        understanding, turn_context = _query_understanding_for_goal(user_goal, action_intent="read_context")
        resolution = _delegate_resolution(user_goal=user_goal, understanding=understanding, current_turn_context=turn_context)
        assert resolution["execution_mode"] == "delegate"
        assert resolution["delegate_target_agent_id"] == expected_agent
        assert resolution["fallback_operation"] == fallback_operation


def test_realtime_information_uses_direct_web_search_not_child_delegation() -> None:
    profile = AgentRuntimeRegistry(BACKEND_DIR).get_profile("agent:0")
    assert profile is not None
    understanding, turn_context = _query_understanding_for_goal(
        "北京今天天气怎么样，直接给温度范围和时间口径。",
        action_intent="search_external",
    )
    bundle = build_task_execution_assembly_bundle(
        base_dir=BACKEND_DIR,
        session_id="session-realtime-direct",
        task_id="taskinst:realtime:direct",
        user_goal="北京今天天气怎么样，直接给温度范围和时间口径。",
        source="test",
        query_understanding=understanding,
        current_turn_context=turn_context,
        agent_runtime_profile=profile,
    )
    requirement = bundle["operation_requirement"]
    resolution = dict(dict(requirement.get("metadata") or {}).get("runtime_operation_resolution") or {})
    task_inputs = dict(dict(bundle["task_spec"]).get("inputs") or {})

    assert resolution["strategy"] == "direct"
    assert "op.web_search" in set(requirement["required_operations"])
    assert "op.delegate_to_agent" not in set(requirement["required_operations"])
    assert "agent_communication_protocol" not in task_inputs


def test_general_conversation_does_not_mount_delegate_operation() -> None:
    profile = AgentRuntimeRegistry(BACKEND_DIR).get_profile("agent:0")
    assert profile is not None
    understanding, turn_context = _query_understanding_for_goal(
        "用一句话解释为什么要先给结论。",
        action_intent="answer_only",
        work_mode="conversation",
    )
    bundle = build_task_execution_assembly_bundle(
        base_dir=BACKEND_DIR,
        session_id="session-natural-general",
        task_id="taskinst:natural:general",
        user_goal="用一句话解释为什么要先给结论。",
        source="test",
        query_understanding=understanding,
        current_turn_context=turn_context,
        agent_runtime_profile=profile,
    )
    requirement = bundle["operation_requirement"]
    resolution = dict(dict(requirement.get("metadata") or {}).get("runtime_operation_resolution") or {})

    assert resolution["strategy"] == "direct"
    assert "op.delegate_to_agent" not in set(requirement["required_operations"])


def test_main_agent_prompt_guidance_names_web_researcher() -> None:
    block = _render_agent_delegation_guidance_block({"agent_id": "agent:0"})

    assert "agent:web_researcher" in block
    assert "web_research" in block
    assert "agent:codebase_searcher" in block
    assert "local_search" in block
    assert "agent:memory_searcher" in block
    assert "memory_lookup" in block
    assert "公开网页" in block
    assert "本地文件" in block
    assert "知识库" in block
    assert "正式记忆" in block
    assert "agent:verifier" in block
    assert "completion_verification" in block
    assert "交付复核" in block


def test_delegation_executor_does_not_pick_web_researcher_from_kind_only() -> None:
    executor = AgentDelegationExecutor(BACKEND_DIR)
    parent_run = AgentRun(
        agent_run_id="agrun:taskrun:test:main",
        task_run_id="taskrun:test",
        agent_id="agent:0",
        agent_profile_id="main_interactive_agent",
        status="running",
    )

    from harness.execution.delegation_models import AgentDelegationRequest

    request = AgentDelegationRequest(
        request_id="delegation:req:web-kind-only",
        task_run_id="taskrun:test",
        session_id="session:test",
        parent_agent_run_ref=parent_run.agent_run_id,
        source_agent_id="agent:0",
        target_agent_id="",
        delegation_kind="official_source_lookup",
        instruction="请核验官方来源。",
        input_payload={"query": "release notes"},
    )
    normalized = executor._normalize_request_target(request, parent_agent_run=parent_run)
    validation = executor.validate_request(normalized, parent_agent_run=parent_run)

    assert normalized.target_agent_id == ""
    assert "target_agent_required" in validation["blocked_reasons"]


def test_delegation_executor_does_not_pick_verifier_from_kind_only() -> None:
    executor = AgentDelegationExecutor(BACKEND_DIR)
    parent_run = AgentRun(
        agent_run_id="agrun:taskrun:test:main",
        task_run_id="taskrun:test",
        agent_id="agent:0",
        agent_profile_id="main_interactive_agent",
        status="running",
    )

    from harness.execution.delegation_models import AgentDelegationRequest

    request = AgentDelegationRequest(
        request_id="delegation:req:verifier-kind-only",
        task_run_id="taskrun:test",
        session_id="session:test",
        parent_agent_run_ref=parent_run.agent_run_id,
        source_agent_id="agent:0",
        target_agent_id="",
        delegation_kind="completion_verification",
        instruction="请复核候选交付。",
        input_payload={"final_answer_candidate": "已完成"},
    )
    normalized = executor._normalize_request_target(request, parent_agent_run=parent_run)
    validation = executor.validate_request(normalized, parent_agent_run=parent_run)

    assert normalized.target_agent_id == ""
    assert "target_agent_required" in validation["blocked_reasons"]



