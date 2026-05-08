from __future__ import annotations

from pathlib import Path

from api.tasks import _task_system_payload
from tasks.flow_registry import TaskFlowRegistry


def test_task_graph_registry_round_trips_single_agent_graph(tmp_path: Path) -> None:
    registry = TaskFlowRegistry(tmp_path)

    graph = registry.upsert_task_graph(
        graph_id="graph.test.single_agent",
        title="测试单 Agent 图",
        graph_kind="single_agent",
        nodes=(
            {"node_id": "input", "node_type": "input", "title": "输入"},
            {"node_id": "agent", "node_type": "agent", "title": "主 Agent", "agent_id": "agent:0"},
            {"node_id": "output", "node_type": "output", "title": "输出"},
        ),
        edges=(
            {"edge_id": "edge_input_agent", "source_node_id": "input", "target_node_id": "agent"},
            {"edge_id": "edge_agent_output", "source_node_id": "agent", "target_node_id": "output", "edge_type": "finalize"},
        ),
    )

    assert graph.valid is True
    assert graph.entry_node_id == "input"
    assert graph.output_node_id == "output"

    loaded = registry.get_task_graph("graph.test.single_agent")
    assert loaded is not None
    assert loaded.graph_kind == "single_agent"
    assert len(loaded.nodes) == 3
    assert len(loaded.edges) == 2


def test_task_system_overview_exposes_task_graph_management(tmp_path: Path) -> None:
    TaskFlowRegistry(tmp_path).upsert_task_graph(
        graph_id="graph.test.single_agent",
        title="测试单 Agent 图",
        graph_kind="single_agent",
        nodes=(
            {"node_id": "input", "node_type": "input", "title": "输入"},
            {"node_id": "agent", "node_type": "agent", "title": "主 Agent", "agent_id": "agent:0"},
            {"node_id": "output", "node_type": "output", "title": "输出"},
        ),
        edges=(
            {"edge_id": "edge_input_agent", "source_node_id": "input", "target_node_id": "agent"},
            {"edge_id": "edge_agent_output", "source_node_id": "agent", "target_node_id": "output", "edge_type": "finalize"},
        ),
    )

    payload = _task_system_payload(tmp_path)

    assert payload["summary"]["task_graph_count"] == 1
    assert payload["task_graph_management"]["task_graphs"][0]["graph_id"] == "graph.test.single_agent"
