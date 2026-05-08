from __future__ import annotations

from pathlib import Path
from typing import Any

from .projection_builder import SoulProjectionBuilder
from .registry import SoulRegistry
from .runtime_assembly import SoulRuntimeAssemblyBuilder


class SoulAssemblyService:
    """Formal identity-assembly boundary for orchestration/runtime."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.registry = SoulRegistry(self.base_dir)
        self.projection_builder = SoulProjectionBuilder(self.registry)
        self.runtime_builder = SoulRuntimeAssemblyBuilder(self.base_dir)

    def build_projection_bundle(self, request: Any) -> dict[str, Any]:
        return self.projection_builder.build(request)

    def build_runtime_view(
        self,
        *,
        task_prompt_contract: Any,
        projection_requirement: Any,
        skill_views: list[Any],
        resource_views: list[Any],
        soul_id: str = "runtime",
        agent_profile_id: str = "runtime_agent",
        use_shared_contract: bool = True,
    ) -> dict[str, Any]:
        return self.runtime_builder.build_runtime_view(
            task_prompt_contract=task_prompt_contract,
            projection_requirement=projection_requirement,
            skill_views=skill_views,
            resource_views=resource_views,
            soul_id=soul_id,
            agent_profile_id=agent_profile_id,
            use_shared_contract=use_shared_contract,
        )
