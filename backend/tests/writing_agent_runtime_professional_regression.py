from __future__ import annotations

from pathlib import Path

from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry
from prompting.strategy_prototypes import strategy_prototype_for_task_goal
from task_system.registry.flow_registry import TaskFlowRegistry
from tests.support.writing_fixtures import load_writing_modular_config_module, seed_writing_storage


_load_config_module = load_writing_modular_config_module
_seed_storage = seed_writing_storage


def test_writing_task_graph_uses_agent_runtime_phase_policy_not_old_writing_private_chain(tmp_path: Path) -> None:
    base_dir = _seed_storage(tmp_path)
    config = _load_config_module()
    config.configure(base_dir)

    registry = TaskFlowRegistry(base_dir)
    graphs = {graph.graph_id: graph for graph in registry.list_task_graphs()}
    chapter_graph = graphs["graph.writing.modular_novel.chapter_cycle"]

    assert strategy_prototype_for_task_goal("writing_graph_long_run").prototype_id == "generic_professional_task"
    assert chapter_graph.loop_frames[0]["frame_id"] == "loop.chapter_batch"
    assert chapter_graph.loop_frames[0]["entry_node_id"] == "chapter_outline"
    assert chapter_graph.loop_frames[0]["continue_node_id"] == "chapter_outline"
    assert chapter_graph.loop_frames[0]["exit_node_id"] == "volume_review"
    retired_writing_tokens = ("_".join(("writing", "simple")), "_".join(("writing", "team")))
    assert not any(any(token in node.node_id for token in retired_writing_tokens) for node in chapter_graph.nodes)

    batch_policy_nodes: set[str] = set()
    for node in chapter_graph.nodes:
        if node.node_id.startswith("memory."):
            continue
        runtime = node.contract_bindings["runtime"]
        governance = node.contract_bindings["governance"]
        if "batch_acceptance_policy" in runtime:
            batch_policy_nodes.add(node.node_id)
            assert runtime["batch_acceptance_policy"]["mode"] in {"review_then_commit", "single_commit", "review_gate", "final_acceptance"}
        assert governance["state_boundary"]["raw_dialogue_visibility"] == "forbidden"
        assert governance["memory_pollution_guard"]["commit_nodes_are_the_only_memory_authority"] is True

    assert batch_policy_nodes == {"chapter_draft"}


def test_writing_text_artifact_worker_profiles_have_no_tool_side_effects(tmp_path: Path) -> None:
    base_dir = _seed_storage(tmp_path)
    config = _load_config_module()
    config.configure(base_dir)

    runtime_registry = AgentRuntimeRegistry(base_dir)
    for agent_id in (
        "agent:writing_modular_worker",
        "agent:writing_modular_memory_steward",
        "agent:writing_modular_runtime_monitor",
    ):
        profile = runtime_registry.get_profile(agent_id)
        assert profile is not None
        assert profile.metadata["agent_mode"] == "text_artifact_worker"
        assert profile.metadata["runtime_mode"] == "text_artifact_runtime"
        assert profile.metadata["text_artifact_runtime"] is True
        assert profile.metadata["preexpanded_context_required"] is True
        assert profile.metadata["pseudo_tool_output_forbidden"] is True
        assert profile.metadata["file_and_memory_side_effects_owned_by"] == "orchestration_runtime"
        assert profile.metadata["agent_side_memory_read_allowed"] is True
        assert profile.metadata["agent_side_memory_read_tool"] == "memory_search"
        assert profile.default_runtime_mode == "standard"
        assert "custom" in profile.enabled_runtime_modes
        assert profile.model_profile.thinking_mode == "enabled"
        assert profile.model_profile.reasoning_effort == "high"
        assert set(profile.allowed_operations).issubset({"op.model_response", "op.memory_read", "op.text_metric"})
        assert "op.delegate_to_agent" in profile.blocked_operations
        assert "op.write_file" in profile.blocked_operations
        assert "op.read_file" in profile.blocked_operations


