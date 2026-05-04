from __future__ import annotations

from health_system.verification_service import HealthVerificationService


def test_health_verification_service_builds_gate_projection(tmp_path) -> None:
    service = HealthVerificationService(tmp_path)

    payload = service.build_gate_projection()

    assert payload["authority"] == "health_system.gate_projection"
    assert payload["summary"]["profile_count"] >= 1
    assert all(item["authority"] == "health_system.regression_gate_decision" for item in payload["decisions"])


def test_health_verification_service_builds_verification_resource_catalog(tmp_path) -> None:
    service = HealthVerificationService(tmp_path)

    payload = service.build_verification_resource_catalog()

    assert payload["authority"] == "health_system.verification_resources"
    assert payload["summary"]["case_count"] >= 1
    assert isinstance(payload["cases"], list)
