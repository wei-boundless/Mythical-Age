from __future__ import annotations

import pytest

from runtime.agent_runtime.professional.state_machine import (
    initial_professional_run_state,
    unsatisfied_obligations_from_verification,
)


def test_professional_state_machine_enforces_temporal_transitions() -> None:
    state = initial_professional_run_state("taskrun:state")

    with pytest.raises(ValueError, match="invalid professional run transition"):
        state.advance("complete", reason="cannot skip")

    state = state.advance("mode_policy_bound", reason="mode")
    state = state.advance("obligation_bound", reason="obligation")
    state = state.advance("prototype_bound", reason="prototype")
    state = state.advance("plan_drafted", reason="plan")
    state = state.advance("action_dispatched", reason="action")
    state = state.advance("tool_observed", reason="read", evidence_refs=("obs:read",))
    state = state.advance("deliverable_validating", reason="validate", evidence_refs=("obs:read",))
    state = state.advance("complete", reason="passed", unsatisfied_obligations=())

    assert state.state == "complete"
    assert [transition.to_state for transition in state.transitions] == [
        "mode_policy_bound",
        "obligation_bound",
        "prototype_bound",
        "plan_drafted",
        "action_dispatched",
        "tool_observed",
        "deliverable_validating",
        "complete",
    ]


def test_professional_state_machine_rejects_complete_with_unsatisfied_obligations() -> None:
    state = initial_professional_run_state("taskrun:blocked")
    state = state.advance("mode_policy_bound", reason="mode")
    state = state.advance("obligation_bound", reason="obligation")
    state = state.advance("prototype_bound", reason="prototype")
    state = state.advance("plan_drafted", reason="plan")
    state = state.advance("action_dispatched", reason="action")
    state = state.advance("verification_observed", reason="pytest", evidence_refs=("obs:pytest",))
    state = state.advance("deliverable_validating", reason="validate")

    with pytest.raises(ValueError, match="cannot complete with unsatisfied obligations"):
        state.advance("complete", reason="bad closeout", unsatisfied_obligations=("verify_command",))

    blocked = state.advance(
        "blocked",
        reason="validation_failed",
        unsatisfied_obligations=("verify_command",),
        blocked_reason="unsatisfied_execution_obligations",
    )

    assert blocked.state == "blocked"
    assert blocked.blocked_reason == "unsatisfied_execution_obligations"
    assert blocked.unsatisfied_obligations == ("verify_command",)


def test_professional_state_machine_allows_observation_cycles_after_verification() -> None:
    state = initial_professional_run_state("taskrun:cycles")
    state = state.advance("mode_policy_bound", reason="mode")
    state = state.advance("obligation_bound", reason="obligation")
    state = state.advance("prototype_bound", reason="prototype")
    state = state.advance("plan_drafted", reason="plan")
    state = state.advance("action_dispatched", reason="action")
    state = state.advance("verification_observed", reason="pwd", evidence_refs=("obs:pwd",))
    state = state.advance("tool_observed", reason="read incident", evidence_refs=("obs:read",))
    state = state.advance("verification_observed", reason="confirm cwd", evidence_refs=("obs:pwd2",))
    state = state.advance("artifact_written", reason="write draft", evidence_refs=("obs:write",))
    state = state.advance("deliverable_validating", reason="validate")
    state = state.advance("complete", reason="passed", unsatisfied_obligations=())

    assert state.state == "complete"
    assert [transition.to_state for transition in state.transitions][-5:] == [
        "tool_observed",
        "verification_observed",
        "artifact_written",
        "deliverable_validating",
        "complete",
    ]


def test_professional_state_machine_allows_repeated_artifact_writes_for_multifile_delivery() -> None:
    state = initial_professional_run_state("taskrun:multifile")
    state = state.advance("mode_policy_bound", reason="mode")
    state = state.advance("obligation_bound", reason="obligation")
    state = state.advance("prototype_bound", reason="prototype")
    state = state.advance("plan_drafted", reason="plan")
    state = state.advance("action_dispatched", reason="action")
    state = state.advance("artifact_written", reason="write index", evidence_refs=("obs:index",))
    state = state.advance("artifact_written", reason="write styles", evidence_refs=("obs:styles",))
    state = state.advance("artifact_written", reason="write script", evidence_refs=("obs:script",))
    state = state.advance("verification_observed", reason="verify files", evidence_refs=("obs:verify",))

    assert state.state == "verification_observed"
    assert [transition.reason for transition in state.transitions[-4:]] == [
        "write index",
        "write styles",
        "write script",
        "verify files",
    ]


def test_professional_state_machine_allows_readback_after_artifact_write() -> None:
    state = initial_professional_run_state("taskrun:write-readback")
    state = state.advance("mode_policy_bound", reason="mode")
    state = state.advance("obligation_bound", reason="obligation")
    state = state.advance("prototype_bound", reason="prototype")
    state = state.advance("plan_drafted", reason="plan")
    state = state.advance("action_dispatched", reason="action")
    state = state.advance("artifact_written", reason="write game", evidence_refs=("obs:write",))
    state = state.advance("tool_observed", reason="read back game", evidence_refs=("obs:read",))
    state = state.advance("deliverable_validating", reason="validate")

    assert state.state == "deliverable_validating"
    assert [transition.to_state for transition in state.transitions[-3:]] == [
        "artifact_written",
        "tool_observed",
        "deliverable_validating",
    ]


def test_unsatisfied_obligations_from_verification_deduplicates_missing_items() -> None:
    assert unsatisfied_obligations_from_verification(
        {
            "missing_required_actions": ["write_output", "write_output", "verify_command"],
            "missing_output_paths": ["frontend/public/games/snake_plus/game.js"],
            "missing_response_terms": ["ignored_when_actions_exist"],
        }
    ) == ("write_output", "verify_command", "frontend/public/games/snake_plus/game.js", "ignored_when_actions_exist")
    assert unsatisfied_obligations_from_verification(
        {
            "missing_response_terms": ["结构性根因", "结构性根因"],
            "deliverable_validation": {
                "missing_deliverables": ["evidence_limits"],
                "unsupported_claims": ["claims_fix_without_test"],
                "protocol_leak_detected": True,
            },
        }
    ) == ("结构性根因", "evidence_limits", "claims_fix_without_test", "protocol_boundary")
