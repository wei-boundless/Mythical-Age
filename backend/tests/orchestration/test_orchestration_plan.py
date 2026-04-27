from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from orchestration import CandidateEnvelope, CandidateSet, ControlKernel, TaskContract


def test_candidates_are_collected_but_not_promoted_to_directives() -> None:
    candidates = CandidateSet()
    candidates.add(
        CandidateEnvelope(
            candidate_id="legacy:planner:1",
            producer="query.planner",
            candidate_type="legacy_plan",
            payload={"route": "tool", "tool": "pdf_analysis"},
            confidence=0.8,
        )
    )

    result = ControlKernel().collect(
        task=TaskContract(task_id="task-1", user_goal="分析 PDF"),
        candidates=candidates,
    )

    assert result.status == "blocked"
    assert len(result.candidates) == 1
    assert result.candidates[0].authority == "candidate_only"
    assert result.directives == ()
    assert result.diagnostics["candidate_count"] == 1


def test_candidate_envelope_rejects_decision_authority() -> None:
    try:
        CandidateEnvelope(
            candidate_id="bad",
            producer="legacy",
            candidate_type="legacy_plan",
            authority="decision",  # type: ignore[arg-type]
        )
    except ValueError as exc:
        assert "decision authority" in str(exc)
    else:
        raise AssertionError("candidate with decision authority should be rejected")
