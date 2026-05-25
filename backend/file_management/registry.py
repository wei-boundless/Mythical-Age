from __future__ import annotations

from dataclasses import dataclass

from .default_profiles import default_file_environment_profiles
from .models import ManagedFileEnvironmentProfile


@dataclass(slots=True)
class FileEnvironmentRegistry:
    profiles: dict[str, ManagedFileEnvironmentProfile]

    @classmethod
    def with_defaults(cls) -> "FileEnvironmentRegistry":
        return cls({profile.profile_id: profile for profile in default_file_environment_profiles()})

    def get_profile(self, profile_id: str) -> ManagedFileEnvironmentProfile | None:
        return self.profiles.get(str(profile_id or "").strip())

    def require_profile(self, profile_id: str) -> ManagedFileEnvironmentProfile:
        profile = self.get_profile(profile_id)
        if profile is None:
            raise KeyError(f"unknown file environment profile: {profile_id}")
        return profile

    def list_profiles(self) -> tuple[ManagedFileEnvironmentProfile, ...]:
        return tuple(self.profiles[key] for key in sorted(self.profiles))


def default_file_environment_registry() -> FileEnvironmentRegistry:
    return FileEnvironmentRegistry.with_defaults()
