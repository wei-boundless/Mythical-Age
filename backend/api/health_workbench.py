from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from api.deps import require_runtime
from health_system.workbench import HealthWorkbenchBuilder

router = APIRouter()


@router.get("/health-workbench/overview")
async def health_workbench_overview() -> dict[str, Any]:
    runtime = require_runtime()
    return HealthWorkbenchBuilder(runtime.base_dir, settings_service=runtime.settings).build_overview()


@router.get("/health-workbench/evidence-packets")
async def health_workbench_evidence_packets() -> dict[str, Any]:
    runtime = require_runtime()
    overview = HealthWorkbenchBuilder(runtime.base_dir, settings_service=runtime.settings).build_overview()
    return {
        "authority": "health_system.workbench.evidence_packets",
        "evidence_packets": list(overview.get("evidence_packets") or []),
        "failure_chains": list(overview.get("failure_chains") or []),
        "summary": {
            "evidence_packet_count": int(dict(overview.get("summary") or {}).get("evidence_packet_count") or 0),
            "failure_chain_count": int(dict(overview.get("summary") or {}).get("failure_chain_count") or 0),
        },
    }


@router.get("/health-workbench/diagnosis-inbox")
async def health_workbench_diagnosis_inbox() -> dict[str, Any]:
    runtime = require_runtime()
    overview = HealthWorkbenchBuilder(runtime.base_dir, settings_service=runtime.settings).build_overview()
    return {
        "authority": "health_system.workbench.diagnosis_inbox",
        "diagnosis_inbox": list(overview.get("diagnosis_inbox") or []),
        "evidence_gaps": list(overview.get("evidence_gaps") or []),
        "summary": {
            "diagnosis_inbox_count": int(dict(overview.get("summary") or {}).get("diagnosis_inbox_count") or 0),
            "evidence_gap_count": int(dict(overview.get("summary") or {}).get("evidence_gap_count") or 0),
        },
    }


@router.get("/health-workbench/recovery-inbox")
async def health_workbench_recovery_inbox() -> dict[str, Any]:
    runtime = require_runtime()
    overview = HealthWorkbenchBuilder(runtime.base_dir, settings_service=runtime.settings).build_overview()
    return {
        "authority": "health_system.workbench.recovery_inbox",
        "recovery_inbox": list(overview.get("recovery_inbox") or []),
        "summary": {
            "recovery_inbox_count": int(dict(overview.get("summary") or {}).get("recovery_inbox_count") or 0),
        },
    }


@router.get("/health-workbench/regression-samples")
async def health_workbench_regression_samples() -> dict[str, Any]:
    runtime = require_runtime()
    overview = HealthWorkbenchBuilder(runtime.base_dir, settings_service=runtime.settings).build_overview()
    governance = dict(overview.get("test_governance") or {})
    return {
        "authority": "health_system.workbench.regression_samples",
        "regression_sample_inbox": list(overview.get("regression_sample_inbox") or []),
        "regression_samples": list(governance.get("regression_samples") or []),
        "scenario_contracts": list(governance.get("scenario_contracts") or []),
        "summary": {
            "regression_sample_count": int(dict(overview.get("summary") or {}).get("regression_sample_count") or 0),
            "scenario_contract_count": int(dict(overview.get("summary") or {}).get("scenario_contract_count") or 0),
            "pending_regression_verification_count": int(dict(overview.get("summary") or {}).get("pending_regression_verification_count") or 0),
        },
    }
