"""Soul system contracts, services, and runtime helpers."""

from soul.agent_prompt_bundle import build_agent_prompt_bundle
from soul.facade import SoulFacade
from soul.projection_builder import SoulProjectionBuilder
from soul.runtime_assembly import build_soul_runtime_view
from soul.view_mapping import (
    soul_skill_view_from_skill_runtime_view,
    soul_tool_view_from_resource_runtime_view,
)

__all__ = [
    "build_agent_prompt_bundle",
    "SoulFacade",
    "SoulProjectionBuilder",
    "build_soul_runtime_view",
    "soul_skill_view_from_skill_runtime_view",
    "soul_tool_view_from_resource_runtime_view",
]
