from __future__ import annotations

from pathlib import Path
from typing import Any

from .projection_instances import ProjectionInstanceRegistry
from .projection_store import (
    delete_projection_card,
    get_projection_card,
    list_projection_cards,
    reconcile_projection_store,
    select_projection_card,
    upsert_projection_card,
)
from .projection_templates import ProjectionTemplateRegistry
from .registry_service import SoulRegistryService


class SoulProjectionService:
    """Formal projection catalog/template/instance boundary."""

    def __init__(self, base_dir: Path, *, registry_service: SoulRegistryService) -> None:
        self.base_dir = Path(base_dir)
        self.registry_service = registry_service
        self.templates = ProjectionTemplateRegistry(self.base_dir)
        self.instances = ProjectionInstanceRegistry(self.base_dir)

    def list_projection_cards(self) -> dict[str, Any]:
        return list_projection_cards(
            self.base_dir,
            soul_profiles=self.registry_service.projection_profiles(),
            active_soul_id=self.registry_service.active_soul_id(),
        )

    def upsert_projection_card(self, *, request: dict[str, Any], select_after_create: bool = False) -> dict[str, Any]:
        soul_id = str(request.get("soul_id") or "").strip().lower()
        profile = self.registry_service.get_profile(soul_id)
        if profile is None or not profile.enabled:
            raise KeyError(soul_id)
        request_payload = dict(request)
        request_payload["soul_id"] = soul_id
        request_payload["projection_id"] = str(request_payload.get("projection_id") or "").strip()
        store = upsert_projection_card(
            self.base_dir,
            request=request_payload,
            soul_name=profile.display_name,
            soul_profile=profile.to_dict(),
            selected=bool(select_after_create),
        )
        return reconcile_projection_store(
            self.base_dir,
            store=store,
            soul_profiles=self.registry_service.projection_profiles(),
            active_soul_id=self.registry_service.active_soul_id(),
            persist=True,
        )

    def select_projection_card(self, projection_id: str) -> dict[str, Any]:
        store = select_projection_card(self.base_dir, projection_id)
        return reconcile_projection_store(
            self.base_dir,
            store=store,
            soul_profiles=self.registry_service.projection_profiles(),
            active_soul_id=self.registry_service.active_soul_id(),
            persist=True,
        )

    def delete_projection_card(self, projection_id: str) -> dict[str, Any]:
        store = delete_projection_card(self.base_dir, projection_id)
        return reconcile_projection_store(
            self.base_dir,
            store=store,
            soul_profiles=self.registry_service.projection_profiles(),
            active_soul_id=self.registry_service.active_soul_id(),
            persist=True,
        )

    def get_projection_card(self, projection_id: str) -> dict[str, Any] | None:
        return get_projection_card(self.base_dir, projection_id)

    def build_template_catalog(self) -> dict[str, Any]:
        return self.templates.build_catalog()

    def get_template(self, template_id: str):
        return self.templates.get_template(template_id)

    def preview_instance(
        self,
        *,
        template_id: str,
        task_id: str,
        agent_id: str,
        runtime_lane: str,
        task_run_id: str = "",
        resource_policy_ref: str = "",
        context_snapshot_ref: str = "",
    ) -> dict[str, Any]:
        return self.instances.preview_instance(
            template_id=template_id,
            task_id=task_id,
            task_run_id=task_run_id,
            agent_id=agent_id,
            runtime_lane=runtime_lane,
            resource_policy_ref=resource_policy_ref,
            context_snapshot_ref=context_snapshot_ref,
        ).to_dict()
