from __future__ import annotations

from pathlib import Path
from typing import Any

from .activity_service import SoulActivityService
from .assembly_service import SoulAssemblyService
from .projection_service import SoulProjectionService
from .registry_service import SoulRegistryService


class SoulFacade:
    """Formal public boundary for the soul system."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.registry_service = SoulRegistryService(self.base_dir)
        self.projection_service = SoulProjectionService(
            self.base_dir,
            registry_service=self.registry_service,
        )
        self.assembly_service = SoulAssemblyService(self.base_dir)
        self.activity_service = SoulActivityService(self.base_dir)

    def build_catalog(self) -> dict[str, Any]:
        return self.registry_service.build_catalog()

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

    def list_projection_cards(self) -> dict[str, Any]:
        return self.projection_service.list_projection_cards()

    def upsert_projection_card(self, *, request: dict[str, Any], select_after_create: bool = False) -> dict[str, Any]:
        return self.projection_service.upsert_projection_card(
            request=request,
            select_after_create=select_after_create,
        )

    def select_projection_card(self, projection_id: str) -> dict[str, Any]:
        return self.projection_service.select_projection_card(projection_id)

    def delete_projection_card(self, projection_id: str) -> dict[str, Any]:
        return self.projection_service.delete_projection_card(projection_id)

    def get_projection_card(self, projection_id: str) -> dict[str, Any] | None:
        return self.projection_service.get_projection_card(projection_id)

    def build_template_catalog(self) -> dict[str, Any]:
        return self.projection_service.build_template_catalog()

    def get_template(self, template_id: str):
        return self.projection_service.get_template(template_id)

    def preview_instance(self, **payload: Any) -> dict[str, Any]:
        return self.projection_service.preview_instance(**payload)

    def build_runtime_view(self, **payload: Any) -> dict[str, Any]:
        return self.assembly_service.build_runtime_view(**payload)

    def get_work_log(self, soul_id: str, *, limit: int = 20) -> dict[str, Any]:
        return self.activity_service.work_log(soul_id, limit=limit).to_dict()
