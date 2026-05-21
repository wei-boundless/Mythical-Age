from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry
from runtime.execution.agent_delegation_executor import AgentDelegationExecutor
from runtime.shared.context_manager import _render_agent_delegation_guidance_block
from runtime.shared.models import AgentRun
from task_system.services.assembly_builder import build_task_execution_assembly_bundle
from understanding.task_understanding import analyze_task_understanding


def _delegate_resolution(*, user_goal: str, understanding: dict) -> dict:
    profile = AgentRuntimeRegistry(BACKEND_DIR).get_profile("agent:0")
    assert profile is not None
    bundle = build_task_execution_assembly_bundle(
        base_dir=BACKEND_DIR,
        session_id="session-natural-delegation",
        task_id=f"taskinst:natural:{abs(hash(user_goal))}",
        user_goal=user_goal,
        source="test",
        query_understanding=understanding,
        agent_runtime_profile=profile,
    )
    requirement = bundle["operation_requirement"]
    return dict(dict(requirement.get("metadata") or {}).get("runtime_operation_resolution") or {})


def test_main_agent_natural_scenarios_select_expected_child_agents() -> None:
    scenarios = [
        (
            "查一下知识库里关于向量召回准确率的结论，给我证据来源。",
            "agent:rag_analyst",
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
        understanding = asdict(analyze_task_understanding(user_goal))
        resolution = _delegate_resolution(user_goal=user_goal, understanding=understanding)
        assert resolution["execution_mode"] == "delegate"
        assert resolution["delegate_target_agent_id"] == expected_agent
        assert resolution["fallback_operation"] == fallback_operation


def test_realtime_information_uses_direct_web_search_not_child_delegation() -> None:
    profile = AgentRuntimeRegistry(BACKEND_DIR).get_profile("agent:0")
    assert profile is not None
    bundle = build_task_execution_assembly_bundle(
        base_dir=BACKEND_DIR,
        session_id="session-realtime-direct",
        task_id="taskinst:realtime:direct",
        user_goal="北京今天天气怎么样，直接给温度范围和时间口径。",
        source="test",
        query_understanding=asdict(analyze_task_understanding("北京今天天气怎么样，直接给温度范围和时间口径。")),
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
    bundle = build_task_execution_assembly_bundle(
        base_dir=BACKEND_DIR,
        session_id="session-natural-general",
        task_id="taskinst:natural:general",
        user_goal="用一句话解释为什么要先给结论。",
        source="test",
        query_understanding={"route": "general"},
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
    assert "公开网页" in block
    assert "官方来源" in block


def test_web_research_kind_resolves_to_web_researcher_at_runtime() -> None:
    executor = AgentDelegationExecutor(BACKEND_DIR)
    parent_run = AgentRun(
        agent_run_id="agrun:taskrun:test:main",
        task_run_id="taskrun:test",
        agent_id="agent:0",
        agent_profile_id="main_interactive_agent",
        status="running",
    )

    resolved = executor._resolve_target_agent_id(
        "",
        delegation_kind="official_source_lookup",
        parent_agent_run=parent_run,
    )

    assert resolved == "agent:web_researcher"
