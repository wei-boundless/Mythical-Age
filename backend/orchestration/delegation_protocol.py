from __future__ import annotations

from typing import Any


def default_expected_output_contract(*, source_kind: str = "", delegation_kind: str = "") -> dict[str, Any]:
    source = str(source_kind or "").strip()
    kind = str(delegation_kind or "").strip()
    if _is_verifier_kind(kind):
        return {
            "authority": "orchestration.agent_delegation_output_contract",
            "contract_id": f"contract.agent_delegation.{kind}",
            "required": ["summary", "verdict"],
            "optional": [
                "answer_candidate",
                "missing_requirements",
                "unsupported_claims",
                "required_revisions",
                "evidence_refs",
                "artifact_refs",
                "confidence",
                "limitations",
            ],
            "quality_rules": [
                "Return pass, needs_revision, or blocked as the verdict.",
                "Judge only from supplied goals, final answer candidates, artifacts, and evidence.",
                "Do not invent missing evidence or rewrite the main Agent final answer.",
            ],
        }
    return {
        "authority": "orchestration.agent_delegation_output_contract",
        "contract_id": f"contract.agent_delegation.{source or kind or 'general'}",
        "required": ["summary", "answer_candidate"],
        "optional": ["evidence_refs", "artifact_refs", "confidence", "limitations", "followup_questions", "consumed_handles", "produced_handles"],
        "quality_rules": [
            "Answer only within the delegated scope.",
            "Return concrete evidence refs when available.",
            "State missing inputs or extraction limits explicitly.",
        ],
    }


def _is_verifier_kind(delegation_kind: str) -> bool:
    return str(delegation_kind or "").strip() in {
        "completion_verification",
        "semantic_verification",
        "deliverable_review",
        "artifact_review",
        "quality_review",
        "plan_review",
    }


