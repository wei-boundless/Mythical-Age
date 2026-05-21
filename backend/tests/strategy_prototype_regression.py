from __future__ import annotations

from prompting.professional_profiles import get_professional_prompt_profile
from prompting.strategy_prototypes import get_strategy_prototype, strategy_prototype_for_task_goal
from task_system.services.assembly_support import build_runtime_task_intent_contract


def test_unknown_professional_goal_keeps_generic_strategy_without_losing_obligations() -> None:
    contract = build_runtime_task_intent_contract(
        session_id="session-generic-prototype",
        task_id="task-generic",
        user_goal="执行一个新的复杂仓库治理任务，修改相关文件，并运行 pytest 验证。",
        query_understanding={"route": "workspace_read", "source_kind": "workspace"},
        current_turn_context={"semantic_task_type": "unregistered_professional_goal"},
    )

    semantic = contract.semantic_task_contract
    obligation = contract.execution_obligation

    assert semantic["strategy_prototype_id"] == "generic_professional_task"
    assert obligation["required_writes"]
    assert obligation["required_commands"]
    assert "apply_real_change" in semantic["required_actions"]
    assert "run_verification" in semantic["required_actions"]
    assert semantic["validation_schema"]["require_write_observation"] is True
    assert semantic["validation_schema"]["require_verification_observation"] is True


def test_strategy_prototype_only_supplies_defaults_not_permissions() -> None:
    prototype = strategy_prototype_for_task_goal("test_report_triage")

    assert prototype.prototype_id == "test_report_triage"
    assert prototype.authority == "runtime.strategy_prototype"
    assert "write" not in prototype.to_dict()
    assert "forbidden_actions" not in prototype.to_dict()
    assert get_strategy_prototype("missing") is None


def test_professional_profiles_do_not_contain_hard_code_write_suppression() -> None:
    profile = get_professional_prompt_profile("professional.test_report_triage")

    assert profile is not None
    assert "你是一名专业长任务测试报告诊断员" in profile.prompt
    assert "你不负责修改代码" not in profile.prompt
    assert "不能擅自修改代码" not in profile.prompt
    assert "必须服从执行义务" in profile.prompt
