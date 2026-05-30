from __future__ import annotations

from pathlib import Path
from typing import Any

from artifact_system import ArtifactInventoryService
from project_layout import ProjectLayout


class HealthArtifactGovernanceViewBuilder:
    """Health-system view over artifact pressure without owning raw stores."""

    def __init__(self, backend_dir: str | Path) -> None:
        self.layout = ProjectLayout.from_backend_dir(backend_dir)
        self.inventory = ArtifactInventoryService(self.layout.project_root)

    def build_view(self) -> dict[str, Any]:
        inventory = self.inventory.build_inventory()
        ports = [dict(item) for item in list(inventory.get("ports") or []) if isinstance(item, dict)]
        large_ports = sorted(ports, key=lambda item: int(item.get("size_bytes") or 0), reverse=True)[:8]
        diagnostic_ports = [item for item in ports if str(item.get("artifact_class") or "") in {"diagnostic_trace", "build_cache"}]
        runtime_fact_ports = [item for item in ports if str(item.get("artifact_class") or "") == "runtime_fact"]
        return {
            "authority": "health_system.artifact_governance",
            "mode": "read_only",
            "summary": {
                **dict(inventory.get("summary") or {}),
                "diagnostic_size_mb": round(sum(int(item.get("size_bytes") or 0) for item in diagnostic_ports) / 1024 / 1024, 2),
                "runtime_fact_size_mb": round(sum(int(item.get("size_bytes") or 0) for item in runtime_fact_ports) / 1024 / 1024, 2),
            },
            "large_ports": large_ports,
            "diagnostic_ports": diagnostic_ports,
            "runtime_fact_ports": runtime_fact_ports,
            "inventory": inventory,
            "maintenance_policy": {
                "requires_dry_run": True,
                "runtime_fact_delete_forbidden": True,
                "task_records_managed_by_health_system": True,
                "diagnostics_can_use_ttl": True,
                "authority": "health_system.artifact_governance_policy",
            },
            "updated_at": inventory.get("updated_at"),
        }
