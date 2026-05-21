from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

from orchestration.agent_runtime_registry import AgentRuntimeRegistry
from prompting.strategy_prototypes import strategy_prototype_for_task_goal
from tasks.flow_registry import TaskFlowRegistry


REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIGURE_SCRIPT = REPO_ROOT / "scripts" / "configure_writing_modular_novel_graph.py"


def _load_config_module():
    spec = importlib.util.spec_from_file_location("configure_writing_modular_novel_graph", CONFIGURE_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _seed_storage(tmp_path: Path) -> Path:
    storage = tmp_path / "storage"
    storage.mkdir(parents=True, exist_ok=True)
    shutil.copytree(REPO_ROOT / "storage" / "tasks", storage / "tasks")
    shutil.copytree(REPO_ROOT / "storage" / "orchestration", storage / "orchestration")
    return tmp_path


def test_writing_task_graph_uses_generic_professional_runtime_not_old_writing_private_chain(tmp_path: Path) -> None:
    base_dir = _seed_storage(tmp_path)
    config = _load_config_module()
    config.configure(base_dir)

    registry = TaskFlowRegistry(base_dir)
    graphs = {graph.graph_id: graph for graph in registry.list_task_graphs()}
    chapter_graph = graphs["graph.writing.modular_novel.chapter_cycle"]

    assert strategy_prototype_for_task_goal("writing_graph_long_run").prototype_id == "generic_professional_task"
    assert chapter_graph.metadata["runtime_loop_policy"]["enabled"] is True
    assert chapter_graph.metadata["runtime_loop_policy"]["frames"][0]["frame_id"] == "loop.chapter_batch"
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
        assert set(profile.allowed_operations).issubset({"op.model_response", "op.memory_read", "op.text_metric"})
        assert "op.delegate_to_agent" in profile.blocked_operations
        assert "op.write_file" in profile.blocked_operations
        assert "op.read_file" in profile.blocked_operations
