from __future__ import annotations

from health_system.maintenance.experiments.catalog import get_profile as get_experiment_profile
from health_system.maintenance.experiments.catalog import list_profiles as list_experiment_profiles

from .contracts import TestProfile


def list_profiles() -> list[TestProfile]:
    return [_from_experiment_profile(item) for item in list_experiment_profiles()]


def get_profile(profile_id: str) -> TestProfile | None:
    profile = get_experiment_profile(profile_id)
    return _from_experiment_profile(profile) if profile is not None else None


def _from_experiment_profile(profile) -> TestProfile:
    return TestProfile(
        profile_id=str(profile.id),
        title=str(profile.title),
        description=str(profile.description),
        command_preview=str(profile.command_preview),
        risk=str(profile.risk),
        estimated_duration=str(profile.estimated_duration),
        harness_profile=str(profile.harness_profile or profile.id),
        extra_args=tuple(profile.extra_args),
        requires_confirmation=bool(profile.requires_confirmation),
    )
