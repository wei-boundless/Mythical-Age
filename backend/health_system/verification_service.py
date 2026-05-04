from __future__ import annotations

from pathlib import Path
from typing import Any

from health_system.maintenance.harness.regression_gate import summarize_outcomes
from health_system.maintenance.test_system.case_registry import active_cases
from health_system.maintenance.test_system.service import TestSystemService, test_system_service

from .verification_models import HealthVerificationRun, RegressionGateDecision


class HealthVerificationService:
    def __init__(self, base_dir: Path, *, service: TestSystemService | None = None) -> None:
        self.base_dir = Path(base_dir)
        self.test_system_service = service or test_system_service

    def list_verification_runs(self, *, limit: int = 10) -> list[HealthVerificationRun]:
        runs = self.test_system_service.list_runs(limit=limit)
        return [_verification_run_from_test_run(item) for item in runs]

    def build_verification_resource_catalog(self) -> dict[str, Any]:
        cases = [
            case.to_dict()
            for case in active_cases()
            if case.status == "active"
        ]
        return {
            "authority": "health_system.verification_resources",
            "cases": cases,
            "summary": {
                "case_count": len(cases),
                "profile_refs": sorted({profile for case in cases for profile in list(case.get("profiles") or [])}),
            },
        }

    def build_regression_gate_decision(self, profile: str) -> RegressionGateDecision:
        runs = self.test_system_service.list_runs(limit=50)
        matched = [item for item in runs if str(item.get("profile") or "") == profile]
        latest = matched[0] if matched else {
            "profile": profile,
            "summary": {"total": 0, "passed": 0, "failed": 0, "warning": 0, "first_failure": ""},
            "run_id": "",
            "status": "unknown",
        }
        summary = dict(latest.get("summary") or {})
        failed = int(summary.get("failed") or 0)
        total = int(summary.get("total") or 0)
        run_id = str(latest.get("run_id") or "")
        first_failure = str(summary.get("first_failure") or "")
        blocker_refs = tuple(item for item in (run_id, first_failure) if item)
        result_refs = tuple(
            str(item.get("run_id") or "")
            for item in matched[:10]
            if str(item.get("run_id") or "")
        )
        return RegressionGateDecision(
            gate_decision_id=f"health-gate:{profile}",
            profile=profile,
            passed=failed == 0 and total > 0,
            total=total,
            failed=failed,
            blocker_refs=blocker_refs,
            result_refs=result_refs,
            summary=f"profile={profile} total={total} failed={failed}",
            diagnostics={"latest_run": latest},
        )

    def build_gate_projection(self) -> dict[str, Any]:
        profiles = ["chain", "functional", "system", "stable"]
        decisions = [self.build_regression_gate_decision(profile) for profile in profiles]
        return {
            "authority": "health_system.gate_projection",
            "decisions": [item.to_dict() for item in decisions],
            "summary": {
                "profile_count": len(decisions),
                "failing_profile_count": sum(1 for item in decisions if not item.passed),
            },
        }


def _verification_run_from_test_run(payload: dict[str, Any]) -> HealthVerificationRun:
    summary = dict(payload.get("summary") or {})
    return HealthVerificationRun(
        verification_run_id=f"health-verify:{payload.get('run_id') or 'unknown'}",
        source_run_ref=str(payload.get("run_id") or ""),
        profile=str(payload.get("profile") or ""),
        status=str(payload.get("status") or "unknown"),
        verdict="passed" if str(payload.get("status") or "") == "passed" else "failed" if str(payload.get("status") or "") == "failed" else "pending",
        summary=summary,
        artifact_refs=tuple(
            item
            for item in (
                str(payload.get("output_dir") or ""),
                str(payload.get("log_path") or ""),
            )
            if item
        ),
        issue_refs=tuple(item for item in (str(summary.get("first_failure") or ""),) if item),
        scenario_refs=(),
        started_at=float(payload.get("started_at") or 0.0),
        finished_at=float(payload.get("ended_at") or 0.0),
    )
