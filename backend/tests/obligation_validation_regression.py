from __future__ import annotations

from types import SimpleNamespace

from runtime.contracts.obligation_validation import validate_obligations
from runtime.memory.tool_observation_ledger import ToolObservationLedger


def test_material_review_requirement_is_not_dropped_when_scope_is_unbound() -> None:
    result = validate_obligations(
        execution_obligation={},
        semantic_contract={"task_goal_type": "inspection"},
        goal_contract=SimpleNamespace(
            required_material_paths=(),
            required_output_paths=(),
            requires_material_review=True,
            requires_write_output=False,
            requires_verification_command=False,
            requires_subagent_lifecycle=False,
            response_must_include=(),
        ),
        tool_observation_ledger=ToolObservationLedger(
            ledger_id="ledger:inspection",
            task_run_id="taskrun:inspection",
        ),
        final_content="完整审查报告",
        terminal_reason="completed",
    )

    assert result.passed is False
    assert "read_material" in result.missing_required_actions
    assert result.satisfactions[0].missing_reason == "missing_read_observation"
