from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from health_system.maintenance.experiments.artifacts import summarize_run_result
from health_system.maintenance.test_system.case_registry import active_cases
from health_system.maintenance.test_system.service import TestSystemService, test_system_service

from .models import VerificationArtifact, VerificationArtifactManifest, VerificationProfile, VerificationRun
from .verification_models import RegressionGateDecision


class HealthVerificationService:
    def __init__(self, base_dir: Path, *, service: TestSystemService | None = None) -> None:
        self.base_dir = Path(base_dir)
        self.test_system_service = service or test_system_service

    def list_verification_runs(self, *, limit: int = 10) -> list[VerificationRun]:
        from .store import HealthStore

        store = HealthStore(self.base_dir)
        return sorted(store.load_verification_runs(), key=lambda item: item.started_at, reverse=True)[:limit]

    def sync_verification_runs_from_test_system(self, *, limit: int = 20) -> list[VerificationRun]:
        runs = [
            self.record_verification_run(item)
            for item in self.test_system_service.list_runs(limit=limit)
        ]
        return runs[:limit]

    def record_verification_run(self, payload: dict[str, Any], *, command_ref: str = "") -> VerificationRun:
        from .store import HealthStore

        store = HealthStore(self.base_dir)
        source_run_ref = str(payload.get("run_id") or "")
        profile_id = str(payload.get("profile") or "unknown")
        verification_run_id = f"health-verify:{source_run_ref or profile_id}"
        output_dir = Path(str(payload.get("output_dir") or ""))
        manifest = self._build_artifact_manifest(verification_run_id=verification_run_id, output_dir=output_dir)
        store.upsert_verification_artifact_manifest(manifest)
        summary = dict(payload.get("summary") or {})
        normalized_summary = summarize_run_result({"metadata": summary})
        status = _normalize_verification_status(str(payload.get("status") or "unknown"), manifest=manifest, summary=normalized_summary)
        artifact_refs = tuple(item.relative_ref or item.path for item in manifest.artifacts if item.present)
        run = VerificationRun(
            verification_run_id=verification_run_id,
            profile_id=profile_id,
            status=status,
            command_ref=command_ref,
            source_run_ref=source_run_ref,
            process_ref=f"pid:{payload.get('pid')}" if payload.get("pid") else "",
            output_dir=str(output_dir),
            log_path=str(payload.get("log_path") or ""),
            artifact_manifest_ref=manifest.manifest_id,
            summary=normalized_summary,
            artifact_refs=artifact_refs,
            issue_refs=tuple(item for item in (str(normalized_summary.get("first_failure") or ""),) if item),
            report_refs=(),
            trace_refs=tuple(item.relative_ref for item in manifest.artifacts if item.artifact_type == "trace" and item.present),
            started_at=float(payload.get("started_at") or 0.0),
            ended_at=float(payload.get("ended_at") or 0.0),
            metadata={
                "authority_source": "health_system.verification_service",
                "raw_status": str(payload.get("status") or "unknown"),
                "returncode": payload.get("returncode"),
            },
        )
        store.upsert_verification_run(run)
        return run

    def get_verification_run(self, verification_run_id: str) -> VerificationRun | None:
        from .store import HealthStore

        return next(
            (item for item in HealthStore(self.base_dir).load_verification_runs() if item.verification_run_id == verification_run_id),
            None,
        )

    def build_verification_resource_catalog(self) -> dict[str, Any]:
        profiles = self.list_profiles()
        cases = [
            case.to_dict()
            for case in active_cases()
            if case.status == "active"
        ]
        return {
            "authority": "health_system.verification_resources",
            "cases": cases,
            "profiles": [item.to_dict() for item in profiles],
            "summary": {
                "case_count": len(cases),
                "profile_count": len(profiles),
                "profile_refs": [item.profile_id for item in profiles],
            },
        }

    def list_profiles(self) -> list[VerificationProfile]:
        cases = active_cases()
        profiles: dict[str, dict[str, Any]] = {}
        for case in cases:
            for profile in list(case.profiles or []):
                bucket = profiles.setdefault(
                    str(profile),
                    {
                        "profile_id": str(profile),
                        "layer": str(profile),
                        "purpose": f"{profile} regression verification",
                        "case_refs": [],
                    },
                )
                bucket["case_refs"].append(case.case_id)
        ordered_profiles = []
        for profile_id, payload in sorted(profiles.items()):
            ordered_profiles.append(
                VerificationProfile(
                    profile_id=profile_id,
                    layer=str(payload["layer"]),
                    purpose=str(payload["purpose"]),
                    case_refs=tuple(dict.fromkeys(payload["case_refs"])),
                    harness_profile=profile_id,
                    default_timeout_sec=1800 if profile_id in {"scenario", "long"} else 600,
                    required_artifacts=("run_result.json", "issues.json", "trace.jsonl", "report.md"),
                    cutover_required=profile_id in {"chain", "functional", "system"},
                )
            )
        return ordered_profiles

    def build_regression_gate_decision(self, profile: str) -> RegressionGateDecision:
        matched = [item for item in self.list_verification_runs(limit=50) if item.profile_id == profile]
        latest = matched[0] if matched else None
        summary = dict(latest.summary) if latest is not None else {"total": 0, "passed": 0, "failed": 0, "first_failure": ""}
        failed = int(summary.get("failed") or 0)
        total = int(summary.get("total") or 0)
        blocker_refs = tuple(item for item in ((latest.verification_run_id if latest else ""), str(summary.get("first_failure") or "")) if item)
        result_refs = tuple(item.verification_run_id for item in matched[:10] if item.verification_run_id)
        return RegressionGateDecision(
            gate_decision_id=f"health-gate:{profile}",
            profile=profile,
            passed=failed == 0 and total > 0 and (latest.status if latest is not None else "unknown") == "passed",
            total=total,
            failed=failed,
            blocker_refs=blocker_refs,
            result_refs=result_refs,
            summary=f"profile={profile} total={total} failed={failed}",
            diagnostics={"latest_run": latest.to_dict() if latest is not None else {}},
        )

    def build_gate_projection(self) -> dict[str, Any]:
        profiles = [item.profile_id for item in self.list_profiles() if item.cutover_required]
        if "stable" not in profiles:
            profiles.append("stable")
        decisions = [self.build_regression_gate_decision(profile) for profile in profiles]
        return {
            "authority": "health_system.gate_projection",
            "decisions": [item.to_dict() for item in decisions],
            "summary": {
                "profile_count": len(decisions),
                "failing_profile_count": sum(1 for item in decisions if not item.passed),
            },
        }

    def _build_artifact_manifest(self, *, verification_run_id: str, output_dir: Path) -> VerificationArtifactManifest:
        artifacts: list[VerificationArtifact] = []
        required_files = {
            "run_result.json": "run_result",
            "issues.json": "issues",
            "trace.jsonl": "trace",
            "report.md": "report",
            "runner.log": "log",
        }
        for filename, artifact_type in required_files.items():
            path = output_dir / filename
            present = path.exists()
            artifacts.append(
                VerificationArtifact(
                    name=filename,
                    artifact_type=artifact_type,
                    path=str(path),
                    relative_ref=_relative_ref(path, self.base_dir),
                    producer="health_system.maintenance.harness",
                    required=filename != "runner.log",
                    present=present,
                    checksum=_checksum(path) if present else "",
                    size_bytes=path.stat().st_size if present else 0,
                )
            )
        return VerificationArtifactManifest(
            manifest_id=f"health-artifact-manifest:{verification_run_id}",
            verification_run_id=verification_run_id,
            artifacts=tuple(artifacts),
            created_at=max((path.stat().st_mtime for path in output_dir.glob("*") if path.exists()), default=0.0),
            metadata={"output_dir": str(output_dir)},
        )


def _normalize_verification_status(status: str, *, manifest: VerificationArtifactManifest, summary: dict[str, Any]) -> str:
    normalized = str(status or "unknown").lower()
    required_missing = any(item.required and not item.present for item in manifest.artifacts)
    if normalized == "cancelled":
        return "cancelled"
    if normalized == "running":
        return "running"
    if required_missing and normalized not in {"running", "cancelled"}:
        return "stale"
    if normalized == "passed" and int(summary.get("failed") or 0) == 0:
        return "passed"
    if normalized == "failed" or int(summary.get("failed") or 0) > 0:
        return "failed"
    return normalized if normalized in {"unknown", "blocked", "rejected", "timed_out"} else "unknown"


def _relative_ref(path: Path, base_dir: Path) -> str:
    try:
        return str(path.resolve().relative_to(base_dir.resolve())).replace("\\", "/")
    except Exception:
        return str(path)


def _checksum(path: Path) -> str:
    digest = hashlib.sha1()
    try:
        digest.update(path.read_bytes())
    except OSError:
        return ""
    return digest.hexdigest()
