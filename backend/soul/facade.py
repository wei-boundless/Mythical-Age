from __future__ import annotations

from pathlib import Path
from typing import Any

from .activity_service import SoulActivityService
from .assembly_service import SoulAssemblyService
from .mode_assembly import SoulModeAssemblyService
from .registry_service import SoulRegistryService


class SoulFacade:
    """Formal public boundary for the soul system."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.registry_service = SoulRegistryService(self.base_dir)
        self.assembly_service = SoulAssemblyService(self.base_dir)
        self.activity_service = SoulActivityService(self.base_dir)
        self.mode_assembly_service = SoulModeAssemblyService(self.base_dir)

    def build_catalog(self) -> dict[str, Any]:
        return self.registry_service.build_catalog()

    def build_resource_catalog(self) -> dict[str, Any]:
        return self.registry_service.build_resource_catalog()

    def switch(self, soul_id: str) -> dict[str, Any]:
        return self.registry_service.switch(soul_id)

    def save_managed_file(self, path: str, content: str) -> dict[str, Any]:
        return self.registry_service.save_managed_file(path, content)

    def get_profile(self, soul_id: str):
        return self.registry_service.get_profile(soul_id)

    def create_or_update_custom_soul(self, **payload: Any) -> dict[str, Any]:
        return self.registry_service.create_or_update_custom_soul(**payload)

    def set_custom_soul_enabled(self, soul_id: str, enabled: bool) -> dict[str, Any]:
        return self.registry_service.set_custom_soul_enabled(soul_id, enabled)

    def build_role_prompt(self, **payload: Any) -> dict[str, Any]:
        return self.assembly_service.build_role_prompt(**payload)

    def get_work_log(self, soul_id: str, *, limit: int = 20) -> dict[str, Any]:
        return self.activity_service.work_log(soul_id, limit=limit).to_dict()

    def preview_mode(self, **payload: Any) -> dict[str, Any]:
        return self.mode_assembly_service.preview(**payload).to_dict()


