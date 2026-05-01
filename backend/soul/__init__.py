"""Soul system contracts and runtime helpers."""

from soul.agent_prompt_bundle import build_agent_prompt_bundle
from soul.projection import (
    build_soul_runtime_view,
    soul_skill_view_from_skill_runtime_view,
    soul_tool_view_from_resource_runtime_view,
)

__all__ = [
    "build_agent_prompt_bundle",
    "build_soul_runtime_view",
    "soul_skill_view_from_skill_runtime_view",
    "soul_tool_view_from_resource_runtime_view",
]
