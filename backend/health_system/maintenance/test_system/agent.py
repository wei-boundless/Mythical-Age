from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .case_registry import active_cases, all_cases, candidate_cases, cases_for_profile
from .test_discovery import discover_test_files


@dataclass(frozen=True, slots=True)
class TestAgentFinding:
    severity: str
    code: str
    message: str
    path: str = ""
    case_id: str = ""
    recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TestAgentReport:
    authority: str = "test_system.test_agent"
    summary: dict[str, Any] = field(default_factory=dict)
    findings: tuple[TestAgentFinding, ...] = ()
    profile_targets: dict[str, list[str]] = field(default_factory=dict)
    registered_paths: list[str] = field(default_factory=list)
    unregistered_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["findings"] = [item.to_dict() for item in self.findings]
        return payload


class TestAgentAdvisor:
    """A deterministic test-agent core for test file governance.

    This is not a multi-agent runtime. It is the backend tool surface that a
    future test agent can call to understand registered cases, orphan files,
    profile coverage, and cleanup recommendations.
    """

    __test__ = False

    def __init__(self, backend_root: Path | None = None) -> None:
        self.backend_root = backend_root or Path(__file__).resolve().parents[1]
        self.tests_root = self.backend_root / "tests"

    def build_report(self) -> dict[str, Any]:
        registered = {
            case.path.replace("\\", "/"): case
            for case in all_cases(include_candidates=True)
        }
        active = {case.path.replace("\\", "/"): case for case in active_cases()}
        discovered = self._discover_test_files()
        active_paths = sorted(active)
        candidate_paths = sorted(case.path.replace("\\", "/") for case in candidate_cases())
        registered_paths = sorted(registered)
        unregistered_paths = sorted(path for path in discovered if path not in registered)
        findings = list(self._missing_registered_files(registered))
        findings.extend(self._orphan_findings(unregistered_paths))
        profile_targets = {
            profile: sorted({case.path.replace("\\", "/") for case in cases_for_profile(profile)})
            for profile in ("chain", "functional", "system", "scenario", "stable", "full")
        }
        report = TestAgentReport(
            summary={
                "active_case_count": len(active_paths),
                "candidate_case_count": len(candidate_paths),
                "registered_file_count": len(registered_paths),
                "discovered_test_file_count": len(discovered),
                "unregistered_file_count": len(unregistered_paths),
                "finding_count": len(findings),
            },
            findings=tuple(findings),
            profile_targets=profile_targets,
            registered_paths=registered_paths,
            unregistered_paths=unregistered_paths,
        )
        return report.to_dict()

    def _discover_test_files(self) -> list[str]:
        return discover_test_files(self.tests_root)

    def _missing_registered_files(
        self,
        registered: dict[str, Any],
    ) -> list[TestAgentFinding]:
        findings: list[TestAgentFinding] = []
        for path, case in sorted(registered.items()):
            if (self.backend_root / path).exists():
                continue
            findings.append(
                TestAgentFinding(
                    severity="error" if case.status == "active" else "warning",
                    code="registered_file_missing",
                    message="Registered test case points to a file that is not present.",
                    path=path,
                    case_id=case.case_id,
                    recommendation="Update the case registry path or remove the stale case registration.",
                )
            )
        return findings

    def _orphan_findings(self, paths: list[str]) -> list[TestAgentFinding]:
        findings: list[TestAgentFinding] = []
        for path in paths:
            severity = "warning"
            recommendation = "Register this file as active/candidate, or rename it out of pytest discovery."
            findings.append(
                TestAgentFinding(
                    severity=severity,
                    code="unregistered_test_file",
                    message="Test file is not governed by test_system.case_registry.",
                    path=path,
                    recommendation=recommendation,
                )
            )
        return findings


test_agent_advisor = TestAgentAdvisor()
