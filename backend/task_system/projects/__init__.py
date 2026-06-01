from __future__ import annotations

from typing import Any

__all__ = [
    "ProjectInstance",
    "ProjectFileService",
    "ProjectLibraryManifest",
    "ProjectLifecycleService",
]


def __getattr__(name: str) -> Any:
    if name == "ProjectInstance":
        from .project_instance import ProjectInstance

        return ProjectInstance
    if name == "ProjectLibraryManifest":
        from .project_library_manifest import ProjectLibraryManifest

        return ProjectLibraryManifest
    if name == "ProjectFileService":
        from .project_file_service import ProjectFileService

        return ProjectFileService
    if name == "ProjectLifecycleService":
        from .project_lifecycle_service import ProjectLifecycleService

        return ProjectLifecycleService
    raise AttributeError(name)
