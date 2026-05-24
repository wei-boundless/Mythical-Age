from __future__ import annotations

from agent_system.registry.agent_registry import default_agent_descriptors
from agent_system.profiles.runtime_profile_registry import default_agent_runtime_profiles
from orchestration.runtime_lane_registry import DEFAULT_RUNTIME_LANE_REGISTRY


def test_context_compactor_is_builtin_agent_with_runtime_profile() -> None:
    agents = {item.agent_id: item for item in default_agent_descriptors(now=1.0)}
    profiles = {item.agent_id: item for item in default_agent_runtime_profiles()}

    agent = agents["agent:context_compactor"]
    profile = profiles["agent:context_compactor"]

    assert agent.agent_category == "builtin_agent"
    assert agent.metadata["system_key"] == "context_management"
    assert agent.metadata["delegation_enabled"] is False
    assert profile.allowed_operations == ("op.model_response",)
    assert "op.web_search" in profile.blocked_operations
    assert "op.delegate_to_agent" in profile.blocked_operations
    assert profile.metadata["runtime_config"]["template_id"] == "runtime.template.context_compactor"
    assert profile.metadata["runtime_config"]["runtime_kind"] == "context_compactor"
    assert profile.metadata["runtime_config"]["context_compaction"]["output_contract"] == "context_recovery_point"


def test_context_compaction_runtime_lane_is_registered_system_only() -> None:
    lane = DEFAULT_RUNTIME_LANE_REGISTRY.get("context_compaction")

    assert lane is not None
    assert lane.system_only is True
    assert lane.default_operations == ("op.model_response",)
    assert "runtime_trace" in lane.default_context_sections
    assert "builtin.system.context_compactor" in lane.runtime_template_hints
