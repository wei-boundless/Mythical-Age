from __future__ import annotations

from pathlib import Path
from typing import Any

from .catalog_service import SoulCatalogService
from .registry import SoulRegistry, normalize_path, read_text, write_text


class SoulRegistryService:
    """Formal registry boundary for soul seeds and profiles."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.registry = SoulRegistry(self.base_dir)
        self.catalog_service = SoulCatalogService(self.base_dir, registry=self.registry)

    def build_catalog(self) -> dict[str, Any]:
        catalog = self.registry.build_catalog()
        catalog["resource_catalog"] = self.catalog_service.to_dict()
        catalog["management"] = {
            **dict(catalog.get("management") or {}),
            "planes": [
                "resources",
                "worlds",
                "stories",
                "cards",
                "work_prompts",
                "system_contracts",
                "common_contracts",
                "manifestations",
                "activity",
                "projection",
                "runtime",
            ],
            "resource_catalog_enabled": True,
        }
        return catalog

    def build_resource_catalog(self) -> dict[str, Any]:
        return self.catalog_service.to_dict()

    def profiles(self, *, include_disabled: bool = False) -> dict[str, Any]:
        return {
            key: value.to_dict()
            for key, value in self.registry.profiles(include_disabled=include_disabled).items()
        }

    def projection_profiles(self) -> list[dict[str, Any]]:
        return [profile.to_dict() for profile in self.registry.profiles().values()]

    def get_profile(self, soul_id: str):
        return self.registry.get_profile(str(soul_id or "").strip().lower())

    def active_soul_id(self) -> str:
        return self.registry.active_soul_id()

    def switch(self, soul_id: str) -> dict[str, Any]:
        self.registry.switch(str(soul_id or "").strip().lower())
        return self.build_catalog()

    def resolve_editable_path(self, path: str) -> Path:
        return self.registry.resolve_editable_path(normalize_path(path))

    def save_managed_file(self, path: str, content: str) -> dict[str, Any]:
        target = self.resolve_editable_path(path)
        write_text(target, content)
        return self.build_catalog()

    def create_or_update_custom_soul(
        self,
        *,
        soul_id: str,
        name: str,
        description: str = "",
        soul_markdown: str = "# Soul Seed\n",
        preferred_role_types: list[str] | None = None,
        preferred_task_modes: list[str] | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        normalized = str(soul_id or "").strip().lower()
        if normalized in {item.soul_id for item in self.registry.builtin_profiles().values()}:
            raise ValueError("自制灵魂不能覆盖内置灵魂")
        soul_dir = (self.base_dir / "soul" / "custom" / normalized).resolve()
        custom_root = (self.base_dir / "soul" / "custom").resolve()
        if custom_root not in soul_dir.parents:
            raise ValueError("Invalid custom soul path")
        profile = {
            "soul_id": normalized,
            "name": name,
            "source": "user",
            "description": description,
            "preferred_role_types": list(preferred_role_types or []),
            "preferred_task_modes": list(preferred_task_modes or []),
            "enabled": bool(enabled),
        }
        write_text(soul_dir / "SOUL.md", soul_markdown)
        import json

        write_text(soul_dir / "profile.json", json.dumps(profile, ensure_ascii=False, indent=2))
        return self.build_catalog()

    def set_custom_soul_enabled(self, soul_id: str, enabled: bool) -> dict[str, Any]:
        import json

        normalized = str(soul_id or "").strip().lower()
        profile_path = self.base_dir / "soul" / "custom" / normalized / "profile.json"
        if not profile_path.exists():
            raise KeyError(normalized)
        raw = json.loads(read_text(profile_path) or "{}")
        raw["enabled"] = bool(enabled)
        write_text(profile_path, json.dumps(raw, ensure_ascii=False, indent=2))
        return self.build_catalog()

    def delete_custom_soul(self, soul_id: str) -> dict[str, Any]:
        import shutil

        normalized = str(soul_id or "").strip().lower()
        soul_dir = (self.base_dir / "soul" / "custom" / normalized).resolve()
        custom_root = (self.base_dir / "soul" / "custom").resolve()
        if custom_root not in soul_dir.parents or not soul_dir.exists():
            raise KeyError(normalized)
        shutil.rmtree(soul_dir)
        return self.build_catalog()
